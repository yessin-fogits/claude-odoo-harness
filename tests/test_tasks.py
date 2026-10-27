"""Odoo tasks: features grouped by task, task branches, [TASK] commits, merge requests."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import pytest

from conftest import TESTS, add_feature


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo.path, capture_output=True, text=True).stdout.strip()


def add_task_feature(repo, task, n, behavior=None):
    e2e = f"e2e/test_F{n:03d}_x.py"
    result = repo.feature("add", "--task", task, "--behavior", behavior or f"Behavior {n}",
                          "--verify", "unit: /demo_mod:TestThing", "--verify", f"e2e: {e2e}")
    assert result.returncode == 0, result.stderr
    (repo.path / e2e).write_text("def test_x(odoo_page):\n    pass\n")


def change_module(repo, note):
    thing = repo.path / "extra-addons/client/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + f"\n# {note}\n")


def finish(repo, fid):
    """start (already done), change, verify, commit: the Definition of Done."""
    change_module(repo, fid)
    result = repo.feature("verify", fid)
    assert result.returncode == 0, result.stdout + result.stderr
    feat = next(f for f in repo.features() if f["id"] == fid)
    repo.commit(f"[{feat['task']}] {fid} {feat['behavior']}")
    return result


@pytest.fixture
def trepo(hrepo, tmp_path):
    hrepo.git("config", "user.name", "dev")
    hrepo.git("config", "user.email", "dev@example.com")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    hrepo.git("remote", "add", "origin", str(origin))
    hrepo.git("push", "-q", "origin", "staging")
    return hrepo


# --- feature list --------------------------------------------------------------

def test_feature_carries_its_task(trepo):
    add_task_feature(trepo, "T2003", 1, "User sees the overview page")
    assert trepo.features()[0]["task"] == "T2003"
    assert "[T2003] User sees the overview page" in trepo.feature("status").stdout
    assert trepo.feature("check").returncode == 0
    bad = trepo.feature("add", "--task", "not a task", "--behavior", "x",
                        "--verify", "e2e: e2e/test_F009_x.py")
    assert bad.returncode == 1 and "task must be an Odoo task code" in bad.stderr


def test_features_without_task_keep_the_minimal_format(trepo):
    add_feature(trepo)
    assert set(trepo.features()[0]) == {"id", "behavior", "verification", "state", "evidence"}


# --- branches ------------------------------------------------------------------

def test_start_creates_the_task_branch_from_the_base_branch(trepo):
    add_task_feature(trepo, "T2003", 1)
    add_task_feature(trepo, "T2003", 2)
    trepo.commit("features")
    base = git(trepo, "rev-parse", "HEAD")
    result = trepo.feature("start", "F-001")
    assert result.returncode == 0, result.stderr
    assert "on branch T2003 (new, from staging)" in result.stdout
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "T2003"
    assert git(trepo, "merge-base", "HEAD", "staging") == base
    finish(trepo, "F-001")
    # the second feature of the same task stays on the branch
    result = trepo.feature("start", "F-002")
    assert result.returncode == 0 and "on branch" not in result.stdout
    verify = finish(trepo, "F-002")
    assert "Task T2003: every feature passes" in verify.stdout
    assert "harness/gitlab.py mr T2003" in verify.stdout
    assert git(trepo, "log", "-1", "--format=%s") == "[T2003] F-002 Behavior 2"


def test_start_refuses_to_switch_task_with_uncommitted_work(trepo):
    add_task_feature(trepo, "T1", 1)
    add_task_feature(trepo, "T2", 2)
    trepo.commit("features")
    trepo.feature("start", "F-001")
    change_module(trepo, "work in progress")
    trepo.feature("block", "F-001", "--reason", "waiting for the client")
    result = trepo.feature("start", "F-002")
    assert result.returncode == 1
    assert "uncommitted changes" in result.stderr and "HOW TO FIX" in result.stderr
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "T1"


def test_task_branch_starts_where_the_harness_is(trepo):
    """Until the harness install is merged upstream, origin/staging has no harness."""
    empty_tree = git(trepo, "hash-object", "-t", "tree", "/dev/null")
    upstream = git(trepo, "commit-tree", empty_tree, "-m", "staging without the harness")
    trepo.git("push", "-q", "-f", "origin", f"{upstream}:refs/heads/staging")
    trepo.git("fetch", "-q", "origin")
    trepo.git("checkout", "-q", "-b", "harness-install")
    trepo.git("branch", "-D", "staging")
    add_task_feature(trepo, "T7", 1)
    trepo.commit("features, not pushed")
    result = trepo.feature("start", "F-001")
    assert result.returncode == 0, result.stderr
    assert "(new, from HEAD)" in result.stdout
    assert (trepo.path / "harness/feature.py").is_file()


# --- merge requests --------------------------------------------------------------

class FakeGitLab(BaseHTTPRequestHandler):
    requests = []
    open_mrs = []

    def log_message(self, *args):
        pass

    def reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length)) if length else None
        url = urlparse(self.path)
        FakeGitLab.requests.append({"method": self.command, "path": url.path,
                                    "query": parse_qs(url.query), "payload": payload,
                                    "token": self.headers.get("PRIVATE-TOKEN")})
        if self.headers.get("PRIVATE-TOKEN") != "secret":
            return self.reply(401, {"message": "401 Unauthorized"})
        if self.command == "GET":
            return self.reply(200, FakeGitLab.open_mrs)
        mr = {"iid": 7, "web_url": "https://gitlab.test/acme/-/merge_requests/7"}
        if self.command == "POST":
            FakeGitLab.open_mrs.append(mr)
        return self.reply(201 if self.command == "POST" else 200, mr)

    do_GET = do_POST = do_PUT = handle_any


@pytest.fixture
def gitlab(trepo):
    FakeGitLab.requests, FakeGitLab.open_mrs = [], []
    server = HTTPServer(("127.0.0.1", 0), FakeGitLab)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    trepo.env.update({"GITLAB_URL": f"http://127.0.0.1:{server.server_port}",
                      "GITLAB_PROJECT": "k8s/acme", "GITLAB_TOKEN": "secret",
                      "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
    yield FakeGitLab
    server.shutdown()


def gitlab_cmd(repo, *args, **fake):
    return repo.run(sys.executable, "harness/gitlab.py", *args, **fake)


def test_mr_is_refused_until_the_task_is_finished(trepo, gitlab):
    add_task_feature(trepo, "T2003", 1)
    add_task_feature(trepo, "T2003", 2)
    trepo.commit("features")
    trepo.feature("start", "F-001")
    finish(trepo, "F-001")
    result = gitlab_cmd(trepo, "mr", "T2003")
    assert result.returncode == 1
    assert "task T2003 is not finished: F-002 not passing" in result.stderr
    assert gitlab.requests == []


def test_mr_pushes_and_opens_then_updates(trepo, gitlab):
    add_task_feature(trepo, "T2003", 1, "User sees the overview page")
    trepo.commit("features")
    trepo.feature("start", "F-001")
    finish(trepo, "F-001")
    result = gitlab_cmd(trepo, "mr", "T2003")
    assert result.returncode == 0, result.stderr
    assert "✓ pushed T2003" in result.stdout
    assert "merge request opened: https://gitlab.test/acme/-/merge_requests/7" in result.stdout
    assert git(trepo, "ls-remote", "--heads", "origin", "T2003")
    post = [r for r in gitlab.requests if r["method"] == "POST"][0]
    assert post["path"] == "/api/v4/projects/k8s%2Facme/merge_requests"
    assert post["payload"]["source_branch"] == "T2003"
    assert post["payload"]["target_branch"] == "staging"
    assert post["payload"]["title"] == "[T2003] User sees the overview page"
    assert "| F-001 | User sees the overview page |" in post["payload"]["description"]
    assert "Modules tested: demo_mod." in post["payload"]["description"]
    record = json.loads((trepo.path / ".harness/mr/T2003.json").read_text())
    assert record["iid"] == 7 and record["features"] == ["F-001"]
    # running it again updates the open merge request instead of opening a second one
    result = gitlab_cmd(trepo, "mr", "T2003")
    assert "merge request updated" in result.stdout
    assert [r["method"] for r in gitlab.requests].count("POST") == 1
    assert gitlab.requests[-1]["method"] == "PUT"


def test_mr_explains_a_missing_or_bad_token(trepo, gitlab):
    add_task_feature(trepo, "T5", 1)
    trepo.commit("features")
    trepo.feature("start", "F-001")
    finish(trepo, "F-001")
    trepo.env.pop("GITLAB_TOKEN")
    result = gitlab_cmd(trepo, "mr", "T5")
    assert result.returncode == 1 and "GITLAB_TOKEN is not set" in result.stderr
    assert "Never commit it" in result.stderr
    result = gitlab_cmd(trepo, "mr", "T5", gitlab_token="wrong")
    assert result.returncode == 1 and "(401)" in result.stderr
    assert "invalid or expired" in result.stderr


def test_mr_refuses_uncommitted_work(trepo, gitlab):
    add_task_feature(trepo, "T5", 1)
    trepo.commit("features")
    trepo.feature("start", "F-001")
    change_module(trepo, "x")
    assert trepo.feature("verify", "F-001").returncode == 0
    result = gitlab_cmd(trepo, "mr", "T5")
    assert result.returncode == 1 and "not committed" in result.stderr


# --- the loop ships a finished task ------------------------------------------------

def test_loop_commits_with_the_task_and_opens_the_mr(trepo, gitlab, tmp_path):
    trepo.env.update({"HARNESS_AGENT": f"{sys.executable} {TESTS / 'fake_claude.py'}",
                      "HARNESS_LOOP_SKIP_HEALTH": "1",
                      "FAKE_AGENT_CALLS": str(tmp_path / "agent_calls.jsonl")})
    add_task_feature(trepo, "T2003", 1, "User sees the overview page")
    trepo.commit("features")
    result = trepo.run(sys.executable, "harness/loop.py", "run", fake_maker="fix")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "T2003"
    assert git(trepo, "log", "-1", "--format=%s") == "[T2003] F-001 User sees the overview page"
    summary = json.loads((trepo.path / ".harness/loop/last.json").read_text())
    assert summary["merge_requests"] == ["https://gitlab.test/acme/-/merge_requests/7"]
    assert git(trepo, "ls-remote", "--heads", "origin", "T2003")
