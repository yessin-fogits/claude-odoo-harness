"""Shared submodules: a GitLab project several projects include (extra-addons/l10n_tn_account,
branch 19.0). Its changes are verified in the project, shipped as its own merge request merged
first, then pulled into the project's; its knowledge files travel with it."""

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from conftest import CLI, ENGINE, ODOO_VERSION, ROOT
from test_hooks import denied, pre, start_session, stop
from test_tasks import add_task_feature, git, trepo  # noqa: F401 (trepo: a fixture)

SUB = "extra-addons/shared"
SHARED_URL = "git@127.0.0.1:k8s/shared.git"
SHARED_FILE = f"{SUB}/shared_mod/tools.py"


def run(cwd, *args):
    out = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture
def srepo(trepo, tmp_path, monkeypatch):
    """The project of test_tasks.trepo with a shared submodule at extra-addons/shared: a custom
    addons folder holding shared_mod, which demo_mod depends on. Its GitLab URL is mapped to a
    local bare repository (url.insteadOf), so the engine sees the real kind of URL."""
    shared = tmp_path / "shared.git"
    config = tmp_path / "gitconfig"
    config.write_text(f'[user]\n\tname = dev\n\temail = dev@example.com\n'
                      f'[protocol "file"]\n\tallow = always\n'
                      f'[url "{shared}"]\n\tinsteadOf = {SHARED_URL}\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    trepo.env["GIT_CONFIG_GLOBAL"] = str(config)
    work = tmp_path / "shared-work"
    module = work / "shared_mod"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        f"{{'name': 'Shared', 'version': '{ODOO_VERSION}.1.0.0', 'license': 'LGPL-3', "
        "'depends': ['base'], 'data': []}\n")
    (module / "__init__.py").write_text("from . import tools\n")
    (module / "tools.py").write_text("RATE = 1\n")
    run(tmp_path, "git", "init", "-q", "-b", "19.0", str(work))
    run(work, "git", "add", "-A")
    run(work, "git", "commit", "-q", "-m", "shared modules")
    run(tmp_path, "git", "init", "-q", "--bare", str(shared))
    run(work, "git", "push", "-q", str(shared), "19.0")
    trepo.git("submodule", "add", "-q", "-b", "19.0", SHARED_URL, SUB)
    env_file = trepo.path / "harness/harness.env"
    env_file.write_text(env_file.read_text().replace(
        "CUSTOM_ADDONS=extra-addons/client", f"CUSTOM_ADDONS=extra-addons/client,{SUB}"))
    manifest = trepo.path / "extra-addons/client/demo_mod/__manifest__.py"
    manifest.write_text(manifest.read_text().replace('"depends": ["base"]',
                                                     '"depends": ["base", "shared_mod"]'))
    trepo.commit("shared submodule")
    trepo.git("push", "-q", "origin", "staging")
    trepo.shared, trepo.work = shared, work
    return trepo


def hlib_call(repo, expr):
    """The value of a hlib expression, evaluated by the engine on the repository."""
    code = f"import json, hlib\nprint(json.dumps({expr}, default=sorted))"
    result = subprocess.run([sys.executable, "-c", code], cwd=repo.path, capture_output=True,
                            text=True, env={**repo.env, "HARNESS_REPO": str(repo.path),
                                            "PYTHONPATH": str(ENGINE)})
    return result


def value(repo, expr):
    result = hlib_call(repo, expr)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def sub_git(repo, *args):
    return run(repo.path / SUB, "git", *args)


def change_shared(repo, note="2"):
    (repo.path / SHARED_FILE).write_text(f"RATE = {note}\n")


# --- the branch's changes, seen through the pointer -----------------------------------

def test_changes_inside_a_submodule_are_the_branchs_changes(srepo):
    assert value(srepo, "hlib.submodules()") == [{
        "name": SUB, "path": SUB, "url": SHARED_URL, "branch": "19.0", "initialized": True}]
    change_shared(srepo)
    (srepo.path / SUB / "shared_mod/new.py").write_text("X = 1\n")
    files = value(srepo, "hlib.changed_files('HEAD')")
    assert sorted(files) == [f"{SUB}/shared_mod/new.py", SHARED_FILE]  # not the pointer
    lines = value(srepo, "hlib.changed_lines('HEAD')")
    assert lines == {SHARED_FILE: [1], f"{SUB}/shared_mod/new.py": None}
    env = "{'CUSTOM_ADDONS': 'extra-addons/client,%s'}" % SUB
    assert value(srepo, f"hlib.changed_modules({env}, 'HEAD')") == ["shared_mod"]
    # committed inside the submodule and as the project's pointer: still the branch's change
    sub_git(srepo, "commit", "-qam", "rate")
    srepo.commit("pointer")
    assert SHARED_FILE in value(srepo, "hlib.changed_files('HEAD~1')")
    assert value(srepo, "hlib.changed_files('HEAD')") == [f"{SUB}/shared_mod/new.py"]


def test_a_submodule_added_since_the_base_is_all_new(srepo):
    files = value(srepo, "hlib.changed_files('HEAD~1')")
    assert {f"{SUB}/shared_mod/__manifest__.py", SHARED_FILE, ".gitmodules"} <= set(files)
    assert SUB not in files


def commit_pointer(repo, sha, message):
    """Commit a pointer without checking it out (git add would take the submodule's HEAD)."""
    repo.git("update-index", "--cacheinfo", f"160000,{sha},{SUB}")
    repo.git("commit", "-q", "-m", message)


def test_what_cannot_be_seen_is_a_red_pen(srepo, tmp_path):
    real = git(srepo, "rev-parse", f"HEAD:{SUB}")
    # the base points to a commit the submodule's clone does not have
    commit_pointer(srepo, "d" * 40, "pointer to a missing commit")
    commit_pointer(srepo, real, "pointer back")
    result = hlib_call(srepo, "hlib.changed_files('HEAD~1')")
    assert result.returncode == 1 and f"commit dddddddddddd of the submodule {SUB} is missing" \
        in result.stderr and f"git -C {SUB} fetch origin" in result.stderr
    # a submodule inside the submodule
    inner = tmp_path / "inner.git"
    run(tmp_path, "git", "init", "-q", "-b", "main", str(tmp_path / "inner"))
    run(tmp_path / "inner", "git", "commit", "-q", "--allow-empty", "-m", "inner")
    run(tmp_path, "git", "clone", "-q", "--bare", str(tmp_path / "inner"), str(inner))
    sub_git(srepo, "submodule", "add", "-q", str(inner), "nested")
    result = hlib_call(srepo, "hlib.changed_files()")
    assert result.returncode == 1 and "a submodule inside the submodule" in result.stderr


def test_a_changed_submodule_that_is_not_checked_out_is_a_red_pen(srepo):
    srepo.git("submodule", "deinit", "-q", "-f", SUB)
    result = srepo.run(sys.executable, str(ENGINE / "hlib.py"), "submodules")
    assert result.returncode == 1 and f"the submodule {SUB} is not checked out" in result.stderr
    assert f"git submodule update --init {SUB}" in result.stderr
    commit_pointer(srepo, "e" * 40, "pointer moved")
    result = hlib_call(srepo, "hlib.changed_files('HEAD~1')")
    assert result.returncode == 1 and "changed but is not checked out" in result.stderr


def test_verify_tests_the_shared_module_and_its_dependents(srepo):
    add_task_feature(srepo, "T9", 1)
    srepo.commit("feature")
    srepo.feature("start", "F-T9-1")
    change_shared(srepo)
    result = srepo.feature("verify", "F-T9-1")
    assert result.returncode == 0, result.stdout + result.stderr
    # no knowledge files yet: they go in the same commit as the change
    assert f"The shared submodule {SUB} changed: add its knowledge files (python3 " \
        f"{ROOT / 'scripts/install_template.py'} --shared {SUB}, then fill its ARCHITECTURE.md), " \
        "record the decisions" in result.stdout
    report = json.loads((srepo.path / "harness/evidence/F-T9-1.json").read_text())["report"]
    assert report["changed_modules"] == ["shared_mod"]
    assert report["tested_modules"] == ["demo_mod", "shared_mod"]
    assert report["layers"]["static"]["modules"] == ["shared_mod"]
    # what was tested, before anything is committed in the submodule
    sub_git(srepo, "commit", "-qam", "rate")
    assert report["submodules"] == {SUB: sub_git(srepo, "rev-parse", "HEAD^{tree}")}


# --- branches -------------------------------------------------------------------

def test_switching_task_checks_out_the_submodule_commit_it_records(srepo):
    start = sub_git(srepo, "rev-parse", "HEAD")
    add_task_feature(srepo, "T9", 1)
    change_shared(srepo)
    sub_git(srepo, "commit", "-qam", "rate")
    srepo.commit("[T9] shared rate")
    changed = sub_git(srepo, "rev-parse", "HEAD")
    add_task_feature(srepo, "T10", 1)  # a new branch from staging, where the pointer is older
    assert git(srepo, "symbolic-ref", "--short", "HEAD") == "T10"
    assert sub_git(srepo, "rev-parse", "HEAD") == start
    srepo.commit("[T10] feature")
    add_task_feature(srepo, "T9", 2)  # back on T9
    assert sub_git(srepo, "rev-parse", "HEAD") == changed
    # work in progress in the submodule is never moved: the switch is refused
    change_shared(srepo, "3")
    result = srepo.feature("add", "--task", "T12", "--behavior", "x", "--verify",
                           "unit: /demo_mod:TestThing", "--verify", "e2e: e2e/test_T12_1_x.py")
    assert result.returncode == 1 and "uncommitted changes" in result.stderr
    assert (srepo.path / SHARED_FILE).read_text() == "RATE = 3\n"


# --- hooks ----------------------------------------------------------------------

def test_guard_protects_the_branch_every_project_pulls(srepo):
    assert denied(pre(srepo, "Bash", command=f"git -C {SUB} push origin 19.0"))
    assert denied(pre(srepo, "Bash", command=f"cd {SUB} && git push origin HEAD:19.0"))
    assert pre(srepo, "Bash", command=f"git -C {SUB} push origin HEAD:refs/heads/T9") is None


def test_stop_counts_a_new_file_in_a_shared_module_as_code(srepo):
    start_session(srepo)
    (srepo.path / SUB / "shared_mod/new.py").write_text("X = 1\n")
    out = stop(srepo)
    assert out["decision"] == "block" and "PROGRESS.md was not updated" in out["reason"]
    assert SUB in out["reason"]


def test_stop_ignores_a_submodule_changed_before_the_session(srepo):
    change_shared(srepo)
    start_session(srepo, "reviewer")
    assert stop(srepo) is None
    change_shared(srepo, "3")
    assert stop(srepo)["decision"] == "block"


def shared_section(repo, session):
    context = start_session(repo, session)["hookSpecificOutput"]["additionalContext"]
    return context.split("## Shared submodules")[1].split("\n## ")[0]


def test_session_start_shows_the_decisions_of_the_shared_submodules_the_task_changes(srepo):
    decision = "  - 2026-11-09: [T8] Rates come from settings"
    # untouched: one line, nothing else
    shared = shared_section(srepo, "s1")
    assert f"`{SUB}`: GitLab project k8s/shared, branch 19.0" in shared
    assert "DECISIONS.md before changing it" in shared and "This task changes it" not in shared
    # work in progress inside it: its last decisions, and the knowledge files it lacks
    change_shared(srepo)
    shared = shared_section(srepo, "s2")
    assert "This task changes it" in shared
    assert "No CLAUDE.md, DECISIONS.md, ARCHITECTURE.md yet" in shared
    srepo.run(sys.executable, str(ROOT / "scripts/install_template.py"), "--shared", SUB)
    decisions = srepo.path / SUB / "DECISIONS.md"
    decisions.write_text(decisions.read_text() + decision[2:] + "\n")
    shared = shared_section(srepo, "s3")
    assert decision in shared and "yet" not in shared
    # merged into the base branch: nothing of this task left in it
    sub_git(srepo, "add", "-A")
    sub_git(srepo, "commit", "-qm", "[T8] rates")
    srepo.commit("[T8] shared rates")
    srepo.git("push", "-q", "origin", "staging")
    assert decision not in shared_section(srepo, "s4")
    # a task branch whose pointer moved: committed, not in progress
    srepo.git("checkout", "-q", "-b", "T9")
    change_shared(srepo, "3")
    sub_git(srepo, "commit", "-qam", "[T9] rate")
    srepo.commit("[T9] pointer")
    assert decision in shared_section(srepo, "s5")


def test_install_shared_writes_the_missing_knowledge_files_only(srepo):
    claude = srepo.path / SUB / "CLAUDE.md"
    claude.write_text("# Our own rules\n")
    result = srepo.run(sys.executable, str(ROOT / "scripts/install_template.py"), "--shared", SUB)
    assert result.returncode == 0, result.stderr
    assert "kept     CLAUDE.md" in result.stdout and "created  DECISIONS.md" in result.stdout
    assert claude.read_text() == "# Our own rules\n"
    assert "Projects using it" in (srepo.path / SUB / "ARCHITECTURE.md").read_text()
    assert "DECISIONS.md merge=union" in (srepo.path / SUB / ".gitattributes").read_text()


# --- shipping: the submodule's merge request first, then the pull ------------------

class FakeGitLab(BaseHTTPRequestHandler):
    """Merge requests per project; a test merges one by changing its state."""
    mrs, requests, fail_posts = {}, [], 0

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
        parts = url.path.split("/")  # '', api, v4, projects, <project>, merge_requests[, iid]
        project = unquote(parts[4])
        FakeGitLab.requests.append({"method": self.command, "project": project,
                                    "query": parse_qs(url.query), "payload": payload})
        mrs = FakeGitLab.mrs.setdefault(project, [])
        if self.command == "GET":
            query = parse_qs(url.query)
            found = [mr for mr in reversed(mrs)
                     if all(mr.get(key) == values[0] for key, values in query.items())]
            return self.reply(200, found)
        if self.command == "POST" and FakeGitLab.fail_posts:
            FakeGitLab.fail_posts -= 1
            return self.reply(500, {"message": "try again"})
        if self.command == "POST":
            mr = {**payload, "iid": len(mrs) + 1, "state": "opened",
                  "web_url": f"https://gitlab.test/{project}/-/merge_requests/{len(mrs) + 1}"}
            mrs.append(mr)
        else:
            mr = next(m for m in mrs if m["iid"] == int(parts[6]))
            mr.update(payload)
        mr["draft"] = mr["title"].startswith("Draft:")
        return self.reply(201 if self.command == "POST" else 200, mr)

    do_GET = do_POST = do_PUT = handle_any


@pytest.fixture
def gitlab(srepo):
    FakeGitLab.mrs, FakeGitLab.requests, FakeGitLab.fail_posts = {}, [], 0
    server = HTTPServer(("127.0.0.1", 0), FakeGitLab)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    srepo.env.update({"GITLAB_URL": f"http://127.0.0.1:{server.server_port}",
                      "GITLAB_PROJECT": "k8s/acme", "GITLAB_TOKEN": "secret",
                      "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
    yield FakeGitLab
    server.shutdown()


def finish_shared_task(repo, task="T9", knowledge=True):
    """A task that changes the shared module, verified, committed in the submodule and in the
    project: the Definition of Done before the merge request."""
    add_task_feature(repo, task, 1, "Rates come from the settings")
    repo.commit("feature")
    repo.feature("start", f"F-{task}-1")
    change_shared(repo)
    if knowledge:
        repo.run(sys.executable, str(ROOT / "scripts/install_template.py"), "--shared", SUB)
    result = repo.feature("verify", f"F-{task}-1")
    assert result.returncode == 0, result.stdout + result.stderr
    sub_git(repo, "add", "-A")
    sub_git(repo, "commit", "-qm", f"[{task}] F-{task}-1 Rates come from the settings")
    repo.commit(f"[{task}] F-{task}-1 Rates come from the settings")
    return result


def merge_in_shared(repo, gitlab, extra=False):
    """The submodule's merge request is merged on GitLab, with a merge commit; with extra,
    someone else's change reached 19.0 first."""
    clone = repo.path.parent / "shared-merge"
    run(repo.path.parent, "git", "clone", "-q", "-b", "19.0", str(repo.shared), str(clone))
    if extra:
        (clone / "shared_mod/other.py").write_text("OTHER = 1\n")
        run(clone, "git", "add", "-A")
        run(clone, "git", "commit", "-q", "-m", "another project's change")
    run(clone, "git", "fetch", "-q", "origin", "T9")
    run(clone, "git", "merge", "-q", "--no-ff", "-m", "Merge branch 'T9' into '19.0'", "FETCH_HEAD")
    run(clone, "git", "push", "-q", "origin", "19.0")
    mr = gitlab.mrs["k8s/shared"][0]
    mr.update(state="merged", merge_commit_sha=run(clone, "git", "rev-parse", "HEAD"))


def test_mr_ships_the_submodule_first_then_pulls_it(srepo, gitlab):
    finish_shared_task(srepo)
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    # pass 1: the submodule's commit on its project's branch T9, its merge request to 19.0
    assert run(srepo.path, "git", "ls-remote", str(srepo.shared), "refs/heads/T9").split()[0] \
        == sub_git(srepo, "rev-parse", "HEAD")
    shared_mr = gitlab.mrs["k8s/shared"][0]
    assert shared_mr["target_branch"] == "19.0" and shared_mr["source_branch"] == "T9"
    assert shared_mr["title"] == "[T9] F-T9-1 Rates come from the settings"
    assert "`k8s/acme` (branch `T9`)" in shared_mr["description"]
    # the project's is a Draft that links it
    project_mr = gitlab.mrs["k8s/acme"][0]
    assert project_mr["title"] == "Draft: [T9] Rates come from the settings"
    assert "| `extra-addons/shared` | [!1](https://gitlab.test/k8s/shared/-/merge_requests/1) " \
           "open: merge it first |" in project_mr["description"]
    assert "Next: get the merge request of extra-addons/shared reviewed and merged" in result.stdout
    # pass 2: once merged, the pointer moves to 19.0 and the project's is ready
    merge_in_shared(srepo, gitlab)
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sub_git(srepo, "rev-parse", "HEAD") == shared_mr["merge_commit_sha"]
    assert git(srepo, "log", "-1", "--format=%s") == f"[T9] {SUB} on 19.0 after !1"
    assert git(srepo, "rev-parse", f"origin/T9:{SUB}") == shared_mr["merge_commit_sha"]
    assert project_mr["title"] == "[T9] Rates come from the settings"
    assert "merged, pointer on `19.0`" in project_mr["description"]
    assert "✓ ready to merge" in result.stdout
    assert len(gitlab.mrs["k8s/acme"]) == len(gitlab.mrs["k8s/shared"]) == 1
    record = json.loads((srepo.path / ".harness/mr/T9.json").read_text())
    assert record["draft"] is False and record["submodules"][SUB]["state"] == "pulled"


def test_mr_stays_draft_when_the_pull_brings_untested_changes(srepo, gitlab):
    finish_shared_task(srepo)
    assert srepo.run(CLI, "gitlab", "mr", "T9").returncode == 0
    merge_in_shared(srepo, gitlab, extra=True)
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 1
    assert f"the merge request stays Draft: {SUB} not verified" in result.stderr
    assert "odoo-harness feature start F-T9-1 --reopen" in result.stderr
    assert gitlab.mrs["k8s/acme"][0]["title"].startswith("Draft:")
    # verified again with the other change, then committed: ready
    assert srepo.feature("start", "F-T9-1", "--reopen").returncode == 0
    assert srepo.feature("verify", "F-T9-1").returncode == 0
    srepo.commit("[T9] F-T9-1 verified with 19.0")
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert gitlab.mrs["k8s/acme"][0]["title"] == "[T9] Rates come from the settings"


def reverify(repo, fid="F-T9-1"):
    assert repo.feature("start", fid, "--reopen").returncode == 0
    result = repo.feature("verify", fid)
    assert result.returncode == 0, result.stdout + result.stderr
    repo.commit(f"[T9] {fid} verified again")


def test_new_shared_commits_after_the_merge_get_their_own_mr(srepo, gitlab):
    finish_shared_task(srepo)
    srepo.run(CLI, "gitlab", "mr", "T9")
    merge_in_shared(srepo, gitlab)
    assert srepo.run(CLI, "gitlab", "mr", "T9").returncode == 0  # pulled, ready
    change_shared(srepo, "7")
    sub_git(srepo, "commit", "-qam", "[T9] F-T9-1 one more rate")
    reverify(srepo)
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [mr["state"] for mr in gitlab.mrs["k8s/shared"]] == ["merged", "opened"]
    assert gitlab.mrs["k8s/acme"][0]["title"].startswith("Draft:")


def test_the_pull_never_drops_commits_made_after_the_merge(srepo, gitlab):
    finish_shared_task(srepo)
    srepo.run(CLI, "gitlab", "mr", "T9")
    merge_in_shared(srepo, gitlab)
    change_shared(srepo, "7")  # on top of the task's commit, not of the merge
    sub_git(srepo, "commit", "-qam", "[T9] F-T9-1 one more rate")
    reverify(srepo)
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 1 and "has commits after its merged merge request !1" \
        in result.stderr and f"git -C {SUB} rebase origin/19.0" in result.stderr
    assert (srepo.path / SHARED_FILE).read_text() == "RATE = 7\n"


def test_mr_asks_for_the_knowledge_files_before_anything_is_pushed(srepo, gitlab):
    finish_shared_task(srepo, knowledge=False)
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 1
    assert f"the shared submodule {SUB} has no CLAUDE.md, DECISIONS.md, ARCHITECTURE.md" \
        in result.stderr and f"install_template.py --shared {SUB}" in result.stderr
    assert gitlab.requests == []
    assert not git(srepo, "ls-remote", "--heads", "origin", "T9")


def test_mr_refuses_a_submodule_it_cannot_ship(srepo, gitlab):
    finish_shared_task(srepo)
    srepo.git("config", "-f", ".gitmodules", "--unset", f"submodule.{SUB}.branch")
    srepo.commit("no branch")
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 1 and f"no branch for the submodule {SUB}" in result.stderr
    srepo.git("config", "-f", ".gitmodules", f"submodule.{SUB}.branch", "19.0")
    srepo.git("config", "-f", ".gitmodules", f"submodule.{SUB}.url", "git@github.com:OCA/x.git")
    srepo.commit("elsewhere")
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 1 and "is not a project of http://127.0.0.1" in result.stderr
    assert gitlab.requests == []


def test_mr_refuses_a_submodule_merge_request_closed_without_merge(srepo, gitlab):
    finish_shared_task(srepo)
    assert srepo.run(CLI, "gitlab", "mr", "T9").returncode == 0
    gitlab.mrs["k8s/shared"][0]["state"] = "closed"
    result = srepo.run(CLI, "gitlab", "mr", "T9")
    assert result.returncode == 1 and "was closed without merge" in result.stderr


def take_published_change(repo):
    """Task T11 moves the pointer to a commit already on 19.0 (merged elsewhere), verified and
    committed."""
    run(repo.work, "git", "pull", "-q", str(repo.shared), "19.0")
    (repo.work / "shared_mod/tools.py").write_text("RATE = 5\n")
    run(repo.work, "git", "commit", "-qam", "merged elsewhere")
    run(repo.work, "git", "push", "-q", str(repo.shared), "19.0")
    add_task_feature(repo, "T11", 1, "Use the new shared rate")
    repo.commit("feature")
    repo.feature("start", "F-T11-1")
    sub_git(repo, "fetch", "-q", "origin", "19.0")
    sub_git(repo, "checkout", "-q", "--detach", "origin/19.0")
    assert repo.feature("verify", "F-T11-1").returncode == 0
    repo.commit("[T11] F-T11-1 Use the new shared rate")


def test_a_pointer_moved_to_the_shared_branch_needs_no_submodule_mr(srepo, gitlab):
    """Another project takes the shared change: its pointer moves to a commit of 19.0."""
    take_published_change(srepo)
    result = srepo.run(CLI, "gitlab", "mr", "T11")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not gitlab.mrs.get("k8s/shared")
    assert gitlab.mrs["k8s/acme"][0]["title"] == "[T11] Use the new shared rate"
    assert "none: the pointer moves to a commit already on `19.0`" \
        in gitlab.mrs["k8s/acme"][0]["description"]


def test_a_foreign_submodule_moved_to_a_published_commit_needs_nothing(srepo, gitlab):
    """An OCA submodule on GitHub, with no branch in .gitmodules, updated to a newer upstream
    commit: nothing to push or open there."""
    srepo.git("config", "-f", ".gitmodules", f"submodule.{SUB}.url", "git@github.com:OCA/x.git")
    srepo.git("config", "-f", ".gitmodules", "--unset", f"submodule.{SUB}.branch")
    srepo.commit("an OCA submodule")
    srepo.git("push", "-q", "origin", "staging")
    take_published_change(srepo)
    result = srepo.run(CLI, "gitlab", "mr", "T11")
    assert result.returncode == 0, result.stdout + result.stderr
    assert {r["project"] for r in gitlab.requests} == {"k8s/acme"}
    assert gitlab.mrs["k8s/acme"][0]["title"] == "[T11] Use the new shared rate"
    assert "none: the pointer moves to a commit already on a branch of its origin" \
        in gitlab.mrs["k8s/acme"][0]["description"]


# --- the knowledge files of every shared submodule, before any task changes it -------

KNOWLEDGE = f".harness/shared/{SUB}"


def shared_git(repo, *args):
    return run(repo.path, "git", "--git-dir", str(repo.shared), *args)


def remote_branch(repo, task):
    return shared_git(repo, "ls-remote", str(repo.shared), f"refs/heads/{task}").split()[:1]


def advance_shared(repo):
    """Another project's change reaches 19.0 after this project's pointer."""
    run(repo.work, "git", "pull", "-q", str(repo.shared), "19.0")
    (repo.work / "shared_mod/other.py").write_text("OTHER = 1\n")
    run(repo.work, "git", "add", "-A")
    run(repo.work, "git", "commit", "-q", "-m", "another project's change")
    run(repo.work, "git", "push", "-q", str(repo.shared), "19.0")
    return run(repo.work, "git", "rev-parse", "HEAD")


def add_knowledge(repo, task="T9"):
    """The runs of gitlab shared, ARCHITECTURE.md filled before the last one."""
    if not (repo.path / KNOWLEDGE).exists():
        assert repo.run(CLI, "gitlab", "shared", task).returncode == 0
    architecture = repo.path / KNOWLEDGE / "ARCHITECTURE.md"
    architecture.write_text(architecture.read_text().replace(
        "## Modules\n", "## Modules\n- shared_mod: the rates every project uses.\n"))
    result = repo.run(CLI, "gitlab", "shared", task)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_shared_adds_the_knowledge_files_in_two_runs(srepo, gitlab):
    tip = advance_shared(srepo)
    pointer = git(srepo, "rev-parse", f"HEAD:{SUB}")
    # run 1: the files, written in a worktree of the branch tip; nothing pushed
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    folder = srepo.path / KNOWLEDGE
    assert f"✓ {SUB}: knowledge files written in {KNOWLEDGE} (19.0)" in result.stdout
    assert "Next: fill the ARCHITECTURE.md" in result.stdout
    assert "# Shared Odoo modules: shared" in (folder / "CLAUDE.md").read_text()
    assert (folder / "shared_mod/other.py").is_file()  # the branch tip, not the pointer
    assert not [r for r in gitlab.requests if r["method"] == "POST"]
    assert not remote_branch(srepo, "T9")
    # the project and the submodule's checkout are left as they are
    assert git(srepo, "status", "--porcelain") == ""
    assert sub_git(srepo, "rev-parse", "HEAD") == pointer
    assert not (srepo.path / SUB / "CLAUDE.md").exists()
    # run 2 with ARCHITECTURE.md still the template: refused, nothing pushed
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 1
    assert f"not filled yet: {KNOWLEDGE}/ARCHITECTURE.md" in result.stderr
    assert not remote_branch(srepo, "T9")
    # filled: one commit on the branch tip, pushed to T9, merge request to 19.0
    result = add_knowledge(srepo)
    pushed = remote_branch(srepo, "T9")[0]
    assert shared_git(srepo, "rev-parse", f"{pushed}~1") == tip
    assert shared_git(srepo, "diff", "--name-only", tip, pushed).split() == [
        ".gitattributes", "ARCHITECTURE.md", "CLAUDE.md", "DECISIONS.md"]
    assert "- shared_mod: the rates" in shared_git(srepo, "show", f"{pushed}:ARCHITECTURE.md")
    mr = gitlab.mrs["k8s/shared"][0]
    assert (mr["source_branch"], mr["target_branch"], mr["title"]) == (
        "T9", "19.0", "[T9] odoo-harness knowledge files")
    assert "`k8s/acme`" in mr["description"]
    assert f"✓ {SUB}: pushed T9, merge request opened: {mr['web_url']}" in result.stdout
    assert not folder.exists()
    assert git(srepo, "status", "--porcelain") == ""
    assert sub_git(srepo, "rev-parse", "HEAD") == pointer
    # again: its open merge request; once merged, its branch has them
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert f"✓ {SUB}: merge request open: {mr['web_url']}" in result.stdout
    merge_in_shared(srepo, gitlab)
    result = srepo.run(CLI, "gitlab", "shared", "T10")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"✓ {SUB}: its branch 19.0 has the knowledge files" in result.stdout
    assert len(gitlab.mrs["k8s/shared"]) == 1


def test_shared_skips_the_submodules_that_are_not_shared_modules(srepo, gitlab):
    env_file = srepo.path / "harness/harness.env"
    env_file.write_text(env_file.read_text().replace(f",{SUB}", ""))
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"- {SUB}: skipped (not in CUSTOM_ADDONS)" in result.stdout
    srepo.git("checkout", "--", "harness/harness.env")
    srepo.git("config", "-f", ".gitmodules", f"submodule.{SUB}.url", "git@github.com:OCA/x.git")
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"- {SUB}: skipped (not a project of http://127.0.0.1" in result.stdout
    assert "No shared submodule: nothing to do." in result.stdout
    assert gitlab.requests == [] and not (srepo.path / ".harness/shared").exists()


def test_shared_refuses_before_writing_anything(srepo, gitlab):
    result = srepo.run(CLI, "gitlab", "shared", "staging")
    assert result.returncode == 1 and "a task cannot be named staging" in result.stderr
    sub_git(srepo, "push", "-q", "origin", "HEAD:refs/heads/T9")  # a change of T9, made by hand
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 1
    assert f"the branch T9 already exists in the project of {SUB}" in result.stderr
    srepo.git("config", "-f", ".gitmodules", "--unset", f"submodule.{SUB}.branch")
    result = srepo.run(CLI, "gitlab", "shared", "T10")
    assert result.returncode == 1 and f"no branch for the submodule {SUB}" in result.stderr
    assert not (srepo.path / ".harness/shared").exists()
    assert not [r for r in gitlab.requests if r["method"] != "GET"]


def test_a_refused_run_never_hides_the_filled_file(srepo, gitlab):
    """A refusal of the second run leaves nothing staged that the next run would take for the
    template; a worktree folder removed by hand is written again."""
    assert srepo.run(CLI, "gitlab", "shared", "T9").returncode == 0
    folder = srepo.path / KNOWLEDGE
    shutil.rmtree(folder)
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (folder / "ARCHITECTURE.md").is_file()
    (folder / "shared_mod/x.py").write_text("X = 1\n")
    architecture = folder / "ARCHITECTURE.md"
    architecture.write_text(architecture.read_text() + "- shared_mod\n")
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 1
    assert "changes more than the knowledge files: shared_mod/x.py" in result.stderr
    (folder / "shared_mod/x.py").unlink()
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "merge request opened" in result.stdout


def test_shared_needs_the_gitlab_settings(srepo, gitlab):
    srepo.env["GITLAB_URL"] = ""
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 1 and "GITLAB_URL or GITLAB_PROJECT is empty" in result.stderr


def test_the_guard_and_the_stop_gate_let_claude_fill_the_knowledge_files(srepo, gitlab):
    start_session(srepo)
    assert srepo.run(CLI, "gitlab", "shared", "T9").returncode == 0
    architecture = srepo.path / KNOWLEDGE / "ARCHITECTURE.md"
    assert pre(srepo, "Edit", file_path=str(architecture), old_string="## Modules\n",
               new_string="## Modules\n- shared_mod\n") is None
    architecture.write_text(architecture.read_text() + "- shared_mod\n")
    assert stop(srepo) is None


def test_knowledge_files_merged_after_the_pointer_are_not_asked_for_again(srepo, gitlab):
    """The knowledge files reached 19.0 after this project's pointer: a task that changes the
    module from that pointer ships without a copy of its own."""
    add_knowledge(srepo)
    merge_in_shared(srepo, gitlab)
    stale = sub_git(srepo, "rev-parse", "origin/19.0")
    sub_git(srepo, "fetch", "-q", "origin", "19.0")
    change_shared(srepo)
    assert "are on 19.0, not in this checkout: rebase it onto origin/19.0" \
        in shared_section(srepo, "s1")
    srepo.git("checkout", "--", ".")
    sub_git(srepo, "checkout", "--", ".")
    # verify fetches: origin/19.0 as last fetched still predates the merge
    sub_git(srepo, "update-ref", "refs/remotes/origin/19.0", stale)
    verified = finish_shared_task(srepo, task="T10", knowledge=False)
    assert "its knowledge files are on 19.0, not in this checkout" in verified.stdout
    assert f"git -C {SUB} rebase --autostash origin/19.0" in verified.stdout
    result = srepo.run(CLI, "gitlab", "mr", "T10")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [mr["source_branch"] for mr in gitlab.mrs["k8s/shared"]] == ["T9", "T10"]


def test_a_failed_merge_request_is_opened_by_the_next_run(srepo, gitlab):
    """The push went through, the merge request did not: the next run opens it, from the same
    worktree, without taking the branch it pushed for someone else's."""
    assert srepo.run(CLI, "gitlab", "shared", "T9").returncode == 0
    architecture = srepo.path / KNOWLEDGE / "ARCHITECTURE.md"
    architecture.write_text(architecture.read_text() + "\n\n")  # blank lines fill nothing
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 1 and "not filled yet" in result.stderr
    architecture.unlink()  # a deleted map is not a filled one
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 1 and "not filled yet" in result.stderr
    shutil.rmtree(srepo.path / KNOWLEDGE)
    assert srepo.run(CLI, "gitlab", "shared", "T9").returncode == 0
    gitlab.fail_posts = 1
    architecture.write_text(architecture.read_text() + "- shared_mod\n")
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 1 and remote_branch(srepo, "T9")
    assert (srepo.path / KNOWLEDGE).exists()
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(gitlab.mrs["k8s/shared"]) == 1 and not (srepo.path / KNOWLEDGE).exists()


def test_a_filled_worktree_is_kept_when_the_files_arrive_another_way(srepo, gitlab):
    assert srepo.run(CLI, "gitlab", "shared", "T9").returncode == 0
    architecture = srepo.path / KNOWLEDGE / "ARCHITECTURE.md"
    architecture.write_text(architecture.read_text() + "- shared_mod: the rates\n")
    run(srepo.work, "git", "pull", "-q", str(srepo.shared), "19.0")
    for name in ("CLAUDE.md", "DECISIONS.md", "ARCHITECTURE.md"):
        (srepo.work / name).write_text(f"# {name}\n")
    run(srepo.work, "git", "add", "-A")
    run(srepo.work, "git", "commit", "-q", "-m", "another project's knowledge files")
    run(srepo.work, "git", "push", "-q", str(srepo.shared), "19.0")
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"! {SUB}: {KNOWLEDGE} kept, its ARCHITECTURE.md is filled" in result.stdout
    assert "- shared_mod: the rates" in architecture.read_text()


def test_another_open_merge_request_adding_the_files_is_not_doubled(srepo, gitlab):
    add_knowledge(srepo, "T100")  # another project's install, not merged yet
    result = srepo.run(CLI, "gitlab", "shared", "T200")
    assert result.returncode == 0, result.stdout + result.stderr
    url = gitlab.mrs["k8s/shared"][0]["web_url"]
    assert f"✓ {SUB}: merge request {url} adds the knowledge files" in result.stdout
    assert len(gitlab.mrs["k8s/shared"]) == 1 and not (srepo.path / KNOWLEDGE).exists()
    # a task that adds them in the submodule's checkout ships them itself
    srepo.run(sys.executable, str(ROOT / "scripts/install_template.py"), "--shared", SUB)
    gitlab.mrs["k8s/shared"][0]["state"] = "closed"
    result = srepo.run(CLI, "gitlab", "shared", "T200")
    assert f"✓ {SUB}: its checkout has the knowledge files" in result.stdout


def test_a_relative_submodule_url_is_a_project_of_the_gitlab(srepo, gitlab):
    srepo.git("config", "-f", ".gitmodules", f"submodule.{SUB}.url", "../k8s/shared.git")
    assert value(srepo, "hlib.submodules()")[0]["url"] == SHARED_URL
    result = srepo.run(CLI, "gitlab", "shared", "T9")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"✓ {SUB}: knowledge files written in {KNOWLEDGE}" in result.stdout
