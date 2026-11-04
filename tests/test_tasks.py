"""Odoo tasks: one file per task, task branches, [TASK] commits, merge requests, and several
developers working on the same repository."""

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import pytest

from conftest import CLI, TESTS, HarnessRepo


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo.path, capture_output=True, text=True).stdout.strip()


def add_task_feature(repo, task, n, behavior=None):
    """Feature n of task: checks out the task's branch, like a developer taking the task."""
    e2e = f"e2e/test_{task.replace('-', '_')}_{n}_x.py"
    result = repo.feature("add", "--task", task, "--behavior", behavior or f"Behavior {n}",
                          "--verify", "unit: /demo_mod:TestThing", "--verify", f"e2e: {e2e}")
    assert result.returncode == 0, result.stderr
    (repo.path / e2e).write_text("def test_x(odoo_page):\n    pass\n")
    return result


def change_module(repo, note, name="models/thing.py"):
    path = repo.path / "extra-addons/client/demo_mod" / name
    path.write_text(path.read_text() + f"\n# {note}\n")


def finish(repo, fid, name="models/thing.py"):
    """start (already done), change, verify, commit: the Definition of Done."""
    change_module(repo, fid, name)
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
    hrepo.origin = origin
    return hrepo


def clone(trepo, tmp_path, name):
    """A teammate's checkout of the same origin."""
    path = tmp_path / name
    subprocess.run(["git", "clone", "-q", "-b", "staging", str(trepo.origin), str(path)],
                   check=True)
    repo = HarnessRepo(path, tmp_path / f"{name}-calls.jsonl")
    repo.git("config", "user.name", name)
    repo.git("config", "user.email", f"{name}@example.com")
    return repo


# --- feature list --------------------------------------------------------------

def test_feature_carries_its_task(trepo):
    add_task_feature(trepo, "T2003", 1, "User sees the overview page")
    assert trepo.features()[0]["task"] == "T2003"
    assert trepo.features()[0]["id"] == "F-T2003-1"
    assert "[T2003] User sees the overview page" in trepo.feature("status").stdout
    assert trepo.feature("check").returncode == 0


def test_add_works_on_the_task_branch(trepo):
    result = add_task_feature(trepo, "T2003", 1)
    assert "on branch T2003 (new, from staging)" in result.stdout
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "T2003"
    # the base branch does not get the task's files
    assert not git(trepo, "ls-tree", "--name-only", "staging", "tasks/T2003.json")


def test_add_no_branch_writes_on_the_current_branch(trepo):
    """Initialization adds the features of several tasks on the install branch."""
    for task in ("T1", "T2"):
        result = trepo.feature("add", "--task", task, "--no-branch", "--behavior", "x",
                               "--verify", f"e2e: e2e/test_{task}_1_x.py")
        assert result.returncode == 0, result.stderr
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "staging"
    assert [f["id"] for f in trepo.features()] == ["F-T1-1", "F-T2-1"]


def test_task_can_be_named_before_it_exists_in_odoo(trepo):
    add_task_feature(trepo, "remise-devis", 1)
    assert trepo.features()[0]["task"] == "remise-devis"
    assert trepo.features()[0]["id"] == "F-remise-devis-1"
    assert trepo.feature("check").returncode == 0


@pytest.mark.parametrize("name", ["not a task", "a/b", "-x", "../x", "staging", "main", "HEAD"])
def test_task_name_must_be_a_private_branch_and_a_file_name(trepo, name):
    bad = trepo.feature("add", f"--task={name}", "--behavior", "x",
                        "--verify", "e2e: e2e/test_x_1_x.py")
    assert bad.returncode == 1 and "task" in bad.stderr
    assert trepo.features() == []


def test_free_task_name_cannot_land_on_an_existing_branch(trepo):
    git(trepo, "push", "-q", "origin", "staging:preprod")
    git(trepo, "fetch", "-q", "origin")
    bad = trepo.feature("add", "--task", "preprod", "--behavior", "x",
                        "--verify", "e2e: e2e/test_preprod_1_x.py")
    assert bad.returncode == 1 and "already exists" in bad.stderr
    assert trepo.features() == []


def test_second_feature_joins_a_free_named_task_on_its_branch(trepo):
    add_task_feature(trepo, "remise-devis", 1)
    trepo.commit("features")
    assert trepo.feature("start", "F-remise-devis-1").returncode == 0
    add_task_feature(trepo, "remise-devis", 2)
    assert [f["id"] for f in trepo.features()] == ["F-remise-devis-1", "F-remise-devis-2"]


def test_rename_task_refuses_a_branch_a_colleague_pushed(trepo):
    add_task_feature(trepo, "remise-devis", 1)
    git(trepo, "push", "-q", "origin", "staging:T2003")
    git(trepo, "fetch", "-q", "origin")
    taken = trepo.feature("rename-task", "remise-devis", "T2003")
    assert taken.returncode == 1 and "already exists" in taken.stderr
    assert trepo.features()[0]["task"] == "remise-devis"


# --- rename --------------------------------------------------------------------

def test_rename_task_moves_its_files_and_branch_and_keeps_the_ids(trepo):
    add_task_feature(trepo, "remise-devis", 1)
    add_task_feature(trepo, "remise-devis", 2)
    trepo.commit("features")
    assert trepo.feature("start", "F-remise-devis-1").returncode == 0
    finish(trepo, "F-remise-devis-1")
    assert trepo.feature("start", "F-remise-devis-2").returncode == 0

    result = trepo.feature("rename-task", "remise-devis", "T2003")

    assert result.returncode == 0, result.stderr
    assert [(f["task"], f["id"]) for f in trepo.features()] == [
        ("T2003", "F-remise-devis-1"), ("T2003", "F-remise-devis-2")]
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "T2003"
    assert not git(trepo, "rev-parse", "--verify", "-q", "refs/heads/remise-devis")
    tasks = trepo.path / "tasks"
    assert not (tasks / "remise-devis.json").exists() and not (tasks / "remise-devis.md").exists()
    notes = (tasks / "T2003.md").read_text()
    assert notes.startswith("# Task T2003")
    assert "- [x] F-remise-devis-1 Behavior 1" in notes and "F-remise-devis-2 Behavior 2" in notes
    assert trepo.feature("check").returncode == 0  # the evidence stays valid
    assert "still on gitlab" not in result.stdout.lower()


def test_a_new_task_reusing_a_renamed_free_name_continues_its_numbering(trepo):
    add_task_feature(trepo, "remise-devis", 1)
    assert trepo.feature("rename-task", "remise-devis", "T2003").returncode == 0
    trepo.commit("renamed")
    trepo.git("checkout", "-q", "staging")
    trepo.git("merge", "-q", "T2003")  # its merge request
    add_task_feature(trepo, "remise-devis", 2)
    assert [f["id"] for f in trepo.features()] == ["F-remise-devis-1", "F-remise-devis-2"]
    assert trepo.feature("check").returncode == 0


def test_rename_task_without_a_branch_yet(trepo):
    result = trepo.feature("add", "--task", "remise-devis", "--no-branch", "--behavior", "x",
                           "--verify", "e2e: e2e/test_remise_devis_1_x.py")
    assert result.returncode == 0, result.stderr
    assert trepo.feature("rename-task", "remise-devis", "T2003").returncode == 0
    assert trepo.features()[0]["task"] == "T2003"
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "staging"


def test_rename_task_refuses_what_it_cannot_do(trepo):
    add_task_feature(trepo, "remise-devis", 1)
    trepo.commit("features")
    git(trepo, "checkout", "-q", "staging")
    add_task_feature(trepo, "T2003", 1)
    trepo.commit("features")
    git(trepo, "merge", "-q", "remise-devis")
    assert trepo.feature("rename-task", "unknown", "T9").returncode == 1
    assert trepo.feature("rename-task", "remise-devis", "not a task").returncode == 1
    assert trepo.feature("rename-task", "remise-devis", "staging").returncode == 1
    taken = trepo.feature("rename-task", "remise-devis", "T2003")
    assert taken.returncode == 1 and "already exists" in taken.stderr
    elsewhere = trepo.feature("rename-task", "remise-devis", "T3000")
    assert elsewhere.returncode == 1 and "git checkout remise-devis" in elsewhere.stderr
    assert {f["task"] for f in trepo.features()} == {"remise-devis", "T2003"}


def test_rename_task_reports_what_stays_on_gitlab(trepo):
    add_task_feature(trepo, "remise-devis", 1)
    trepo.commit("features")
    assert trepo.feature("start", "F-remise-devis-1").returncode == 0
    git(trepo, "push", "-q", "-u", "origin", "remise-devis")
    mr_dir = trepo.path / ".harness/mr"
    mr_dir.mkdir(parents=True, exist_ok=True)
    (mr_dir / "remise-devis.json").write_text(json.dumps({"url": "https://gitlab/mr/1"}))
    result = trepo.feature("rename-task", "remise-devis", "T2003")
    assert result.returncode == 0, result.stderr
    assert "branch remise-devis" in result.stdout and "https://gitlab/mr/1" in result.stdout
    assert git(trepo, "ls-remote", "--heads", "origin", "remise-devis")


# --- branches ------------------------------------------------------------------

def test_start_creates_the_task_branch_from_the_base_branch(trepo):
    result = trepo.feature("add", "--task", "T2003", "--no-branch", "--behavior", "Behavior 1",
                           "--verify", "unit: /demo_mod:TestThing",
                           "--verify", "e2e: e2e/test_T2003_1_x.py")
    assert result.returncode == 0, result.stderr
    (trepo.path / "e2e/test_T2003_1_x.py").write_text("def test_x(odoo_page):\n    pass\n")
    trepo.commit("seeded at initialization")
    base = git(trepo, "rev-parse", "HEAD")
    result = trepo.feature("start", "F-T2003-1")
    assert result.returncode == 0, result.stderr
    assert "on branch T2003 (new, from staging)" in result.stdout
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "T2003"
    assert git(trepo, "merge-base", "HEAD", "staging") == base
    add_task_feature(trepo, "T2003", 2)
    finish(trepo, "F-T2003-1")
    # the second feature of the same task stays on the branch
    result = trepo.feature("start", "F-T2003-2")
    assert result.returncode == 0 and "on branch" not in result.stdout
    verify = finish(trepo, "F-T2003-2")
    assert "Task T2003: every feature passes" in verify.stdout
    assert "odoo-harness gitlab mr T2003" in verify.stdout
    assert git(trepo, "log", "-1", "--format=%s") == "[T2003] F-T2003-2 Behavior 2"


def test_start_refuses_to_switch_task_with_uncommitted_work(trepo):
    for task in ("T1", "T2"):
        trepo.feature("add", "--task", task, "--no-branch", "--behavior", "x",
                      "--verify", f"e2e: e2e/test_{task}_1_x.py")
    trepo.commit("features")
    trepo.feature("start", "F-T1-1")
    change_module(trepo, "work in progress")
    trepo.feature("block", "F-T1-1", "--reason", "waiting for the client")
    result = trepo.feature("start", "F-T2-1")
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
    result = add_task_feature(trepo, "T7", 1)
    assert "(new, from HEAD)" in result.stdout
    assert (trepo.path / "harness/harness.env").is_file()


# --- several developers -----------------------------------------------------------

def test_two_developers_on_two_tasks_merge_without_conflict(trepo, tmp_path):
    alice, bob = clone(trepo, tmp_path, "alice"), clone(trepo, tmp_path, "bob")
    for dev, task in ((alice, "T1"), (bob, "T2")):
        add_task_feature(dev, task, 1)
        add_task_feature(dev, task, 2)
        dev.commit("features")
        for n in (1, 2):
            assert dev.feature("start", f"F-{task}-{n}").returncode == 0
            # each task changes its own code: only the harness files could conflict
            finish(dev, f"F-{task}-{n}", "models/thing.py" if task == "T1" else "__init__.py")
        dev.git("push", "-q", "origin", task)
    # staging takes both merge requests
    trepo.git("fetch", "-q", "origin")
    for task in ("T1", "T2"):
        merged = subprocess.run(["git", "merge", "--no-edit", "-q", f"origin/{task}"],
                                cwd=trepo.path, capture_output=True, text=True)
        assert merged.returncode == 0, merged.stdout + merged.stderr
    check = trepo.feature("check")
    assert check.returncode == 0, check.stderr
    assert sorted(f["id"] for f in trepo.features()) == ["F-T1-1", "F-T1-2", "F-T2-1", "F-T2-2"]
    assert len(list((trepo.path / "harness/evidence").glob("F-*.json"))) == 4
    # PROGRESS.md was written by nobody since the install, so it conflicts with nobody
    assert len(git(trepo, "log", "--format=%h", "--", "PROGRESS.md").splitlines()) == 1


def test_a_teammates_feature_in_progress_does_not_block(trepo, tmp_path):
    alice = clone(trepo, tmp_path, "alice")
    add_task_feature(alice, "T1", 1)
    alice.commit("features")
    assert alice.feature("start", "F-T1-1").returncode == 0
    alice.commit("work in progress")
    alice.git("push", "-q", "origin", "T1")
    # merged by hand into staging while still in progress
    trepo.git("fetch", "-q", "origin")
    trepo.git("merge", "-q", "--no-edit", "origin/T1")
    status = trepo.feature("status").stdout
    assert "in_progress, other branch" in status
    add_task_feature(trepo, "T2", 1)
    trepo.commit("features")
    result = trepo.feature("start", "F-T2-1")
    assert result.returncode == 0, result.stderr
    trepo.commit("T2 in progress")
    # another feature of T1 joins alice's branch, and waits for her feature
    trepo.git("checkout", "-q", "staging")
    result = add_task_feature(trepo, "T1", 2)
    assert "(from origin/T1)" in result.stdout
    trepo.commit("a second T1 feature")
    waiting = trepo.feature("start", "F-T1-2")
    assert waiting.returncode == 1 and "F-T1-1 is in_progress" in waiting.stderr


def test_start_continues_a_teammates_branch(trepo, tmp_path):
    alice = clone(trepo, tmp_path, "alice")
    add_task_feature(alice, "T3", 1)
    add_task_feature(alice, "T3", 2)
    alice.commit("features")
    assert alice.feature("start", "F-T3-1").returncode == 0
    finish(alice, "F-T3-1")
    alice.git("push", "-q", "origin", "T3")
    # bob takes over the task: he has no branch T3 and never fetched it
    bob = clone(trepo, tmp_path, "bob")
    bob.git("fetch", "-q", "origin", "staging")
    bob.git("update-ref", "-d", "refs/remotes/origin/T3")
    result = bob.feature("add", "--task", "T3", "--behavior", "Behavior 3",
                         "--verify", "e2e: e2e/test_T3_3_x.py")
    assert result.returncode == 0, result.stderr
    assert "on branch T3 (from origin/T3)" in result.stdout
    assert [f["id"] for f in bob.features()] == ["F-T3-1", "F-T3-2", "F-T3-3"]
    assert git(bob, "rev-parse", "--abbrev-ref", "T3@{upstream}") == "origin/T3"
    # alice pushes more, bob's start brings his branch up to date
    bob.commit("bob's feature")
    bob.git("push", "-q", "origin", "T3")
    alice.git("pull", "-q", "--ff-only", "origin", "T3")
    assert alice.feature("start", "F-T3-2").returncode == 0
    finish(alice, "F-T3-2")
    alice.git("push", "-q", "origin", "T3")
    result = bob.feature("start", "F-T3-3")
    assert result.returncode == 0, result.stderr
    assert "fast-forwarded to origin/T3" in result.stdout
    assert next(f for f in bob.features() if f["id"] == "F-T3-2")["state"] == "passing"


def test_start_refuses_a_branch_that_diverged_from_origin(trepo, tmp_path):
    alice = clone(trepo, tmp_path, "alice")
    add_task_feature(alice, "T4", 1)
    alice.commit("features")
    alice.git("push", "-q", "origin", "T4")
    bob = clone(trepo, tmp_path, "bob")
    bob.git("checkout", "-q", "-b", "T4", "origin/T4")
    alice.git("commit", "-q", "--allow-empty", "-m", "alice")
    alice.git("push", "-q", "origin", "T4")
    bob.git("commit", "-q", "--allow-empty", "-m", "bob")
    result = bob.feature("start", "F-T4-1")
    assert result.returncode == 1
    assert "diverged" in result.stderr and "git pull --rebase origin T4" in result.stderr


def test_a_branch_from_before_the_harness_is_not_joined_silently(trepo):
    """T7027 was pushed in 2025, before the harness: its tree has no tasks/."""
    empty_tree = git(trepo, "hash-object", "-t", "tree", "/dev/null")
    old = git(trepo, "commit-tree", empty_tree, "-m", "old work")
    trepo.git("push", "-q", "origin", f"{old}:refs/heads/T7027")
    result = trepo.feature("add", "--task", "T7027", "--behavior", "x",
                           "--verify", "e2e: e2e/test_T7027_1_x.py")
    assert result.returncode == 1
    assert "was created before the harness" in result.stderr
    assert "git merge origin/staging" in result.stderr and "--task T7027_" in result.stderr
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "staging"


def test_a_merged_and_deleted_branch_is_not_joined(trepo):
    """A stale origin/T8 (deleted on GitLab after its merge) gives a new branch."""
    trepo.git("push", "-q", "origin", "staging:T8")
    subprocess.run(["git", "--git-dir", str(trepo.origin), "update-ref", "-d", "refs/heads/T8"],
                   check=True)
    assert git(trepo, "rev-parse", "--verify", "-q", "refs/remotes/origin/T8")
    result = add_task_feature(trepo, "T8", 1)
    assert "(new, from staging)" in result.stdout


def test_loop_leaves_a_teammates_task_alone(trepo, tmp_path):
    trepo.env.update({"HARNESS_AGENT": f"{sys.executable} {TESTS / 'fake_claude.py'}",
                      "HARNESS_LOOP_SKIP_HEALTH": "1",
                      "FAKE_AGENT_CALLS": str(tmp_path / "agent_calls.jsonl")})
    for task in ("T1", "T2"):
        trepo.feature("add", "--task", task, "--no-branch", "--behavior", f"Behavior {task}",
                      "--verify", "unit: /demo_mod:TestThing",
                      "--verify", f"e2e: e2e/test_{task}_1_x.py")
        (trepo.path / f"e2e/test_{task}_1_x.py").write_text("def test_x(odoo_page):\n    pass\n")
    trepo.commit("seeded")
    trepo.git("push", "-q", "origin", "staging:T1")  # a teammate took T1
    result = trepo.run(CLI, "loop", "run", "--no-mr", fake_maker="fix")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "T2"
    assert git(trepo, "log", "-1", "--format=%s") == "[T2] F-T2-1 Behavior T2"


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
    return repo.run(CLI, "gitlab", *args, **fake)


def test_mr_is_refused_until_the_task_is_finished(trepo, gitlab):
    add_task_feature(trepo, "T2003", 1)
    add_task_feature(trepo, "T2003", 2)
    trepo.commit("features")
    trepo.feature("start", "F-T2003-1")
    finish(trepo, "F-T2003-1")
    result = gitlab_cmd(trepo, "mr", "T2003")
    assert result.returncode == 1
    assert "task T2003 is not finished: F-T2003-2 not passing" in result.stderr
    assert gitlab.requests == []


def test_mr_pushes_and_opens_then_updates(trepo, gitlab):
    add_task_feature(trepo, "T2003", 1, "User sees the overview page")
    trepo.commit("features")
    trepo.feature("start", "F-T2003-1")
    finish(trepo, "F-T2003-1")
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
    assert "| F-T2003-1 | User sees the overview page |" in post["payload"]["description"]
    assert "Modules tested: demo_mod." in post["payload"]["description"]
    record = json.loads((trepo.path / ".harness/mr/T2003.json").read_text())
    assert record["iid"] == 7 and record["features"] == ["F-T2003-1"]
    # running it again updates the open merge request instead of opening a second one
    result = gitlab_cmd(trepo, "mr", "T2003")
    assert "merge request updated" in result.stdout
    assert [r["method"] for r in gitlab.requests].count("POST") == 1
    assert gitlab.requests[-1]["method"] == "PUT"


def test_mr_explains_a_missing_or_bad_token(trepo, gitlab):
    add_task_feature(trepo, "T5", 1)
    trepo.commit("features")
    trepo.feature("start", "F-T5-1")
    finish(trepo, "F-T5-1")
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
    trepo.feature("start", "F-T5-1")
    change_module(trepo, "x")
    assert trepo.feature("verify", "F-T5-1").returncode == 0
    result = gitlab_cmd(trepo, "mr", "T5")
    assert result.returncode == 1 and "not committed" in result.stderr


# --- the loop ships a finished task ------------------------------------------------

def test_loop_commits_with_the_task_and_opens_the_mr(trepo, gitlab, tmp_path):
    trepo.env.update({"HARNESS_AGENT": f"{sys.executable} {TESTS / 'fake_claude.py'}",
                      "HARNESS_LOOP_SKIP_HEALTH": "1",
                      "FAKE_AGENT_CALLS": str(tmp_path / "agent_calls.jsonl")})
    add_task_feature(trepo, "T2003", 1, "User sees the overview page")
    trepo.commit("features")
    result = trepo.run(CLI, "loop", "run", fake_maker="fix")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(trepo, "symbolic-ref", "--short", "HEAD") == "T2003"
    assert git(trepo, "log", "-1", "--format=%s") == "[T2003] F-T2003-1 User sees the overview page"
    summary = json.loads((trepo.path / ".harness/loop/last.json").read_text())
    assert summary["merge_requests"] == ["https://gitlab.test/acme/-/merge_requests/7"]
    assert git(trepo, "ls-remote", "--heads", "origin", "T2003")
