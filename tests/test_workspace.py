"""Claude Code started in the client workspace (~/Project/<client>), the harness in git/."""

import shutil
import subprocess
from types import SimpleNamespace

import pytest

import install_template
from conftest import CLI, MODULE_DIR, TESTS, HarnessRepo, add_feature
from make_demo_project import adapt_fixture_module, write_layout
from test_hooks import denied, hook, pre, start_session, stop
from conftest import ODOO_VERSION  # noqa: E402


@pytest.fixture
def ws(tmp_path):
    """~/Project/acme with the repository in git/ and Odoo Enterprise in enterprise/."""
    workspace = tmp_path / "acme"
    target = workspace / "git"
    target.mkdir(parents=True)
    (workspace / "enterprise" / "web_studio").mkdir(parents=True)
    write_layout(target, client="client", version=ODOO_VERSION)
    module = target / MODULE_DIR
    shutil.copytree(TESTS / "fixtures" / "demo_mod", module,
                    ignore=shutil.ignore_patterns("__pycache__"))
    adapt_fixture_module(module, ODOO_VERSION)
    repo = HarnessRepo(target, tmp_path / "calls.jsonl")
    repo.git("init", "-q", "-b", "staging")
    install_template.main([str(target), "--enterprise-dir", "../enterprise"])
    repo.commit("initial")
    return SimpleNamespace(path=workspace, env=repo.env, repo=repo)


# --- installer --------------------------------------------------------------------

def test_nothing_is_generated_in_the_workspace(ws):
    """The hooks find git/ themselves: the workspace stays the developer's."""
    assert not (ws.path / "CLAUDE.md").exists()
    assert not (ws.path / ".claude").exists()


@pytest.mark.parametrize("extra", [["--workspace", "{other}"], ["--workspace", "{repo}"]])
def test_workspace_errors(ws, tmp_path, extra):
    other = tmp_path / "other"
    other.mkdir()
    args = [a.format(other=other, repo=ws.path / "git") for a in extra]
    with pytest.raises(SystemExit):
        install_template.main([str(ws.path / "git"), *args])


def test_the_command_finds_the_repository_from_the_workspace(ws):
    result = subprocess.run([CLI, "where"], cwd=ws.path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"repository: {(ws.path / 'git').resolve()}" in result.stdout
    status = subprocess.run([CLI, "feature", "status"], cwd=ws.path, capture_output=True,
                            text=True, env=ws.env)
    assert status.returncode == 0, status.stderr


# --- hooks ------------------------------------------------------------------------

def test_session_start_finds_the_repository(ws):
    context = start_session(ws)["hookSpecificOutput"]["additionalContext"]
    assert "## Workspace" in context and "`odoo-harness ...` finds `git/`" in context
    assert "PROGRESS.md" in context
    assert (ws.path / "git" / ".harness" / "session.json").is_file()
    assert not (ws.path / ".harness").exists()


def test_session_start_brings_the_repository_rules(ws):
    context = start_session(ws)["hookSpecificOutput"]["additionalContext"]
    assert "## git/CLAUDE.md (the project rules, loaded by the harness)" in context
    assert "# Work Rules" in context


def test_session_start_does_not_repeat_imported_rules(ws):
    (ws.path / "CLAUDE.md").write_text("@git/CLAUDE.md\n")
    context = start_session(ws)["hookSpecificOutput"]["additionalContext"]
    assert "# Work Rules" not in context


def test_session_in_the_repository_has_no_workspace_section(ws):
    context = start_session(ws.repo)["hookSpecificOutput"]["additionalContext"]
    assert "## Workspace" not in context


def test_guard_from_the_workspace(ws):
    git = ws.path / "git"
    assert denied(pre(ws, "Edit", file_path=str(git / "feature_list.json")))
    assert denied(pre(ws, "Edit", file_path="git/feature_list.json"))
    assert denied(pre(ws, "Write", file_path=str(ws.path / "enterprise/web_studio/x.py")))
    assert denied(pre(ws, "Edit", file_path=str(git / "Dockerfile")))
    assert pre(ws, "Edit", file_path=str(git / MODULE_DIR / "models/thing.py")) is None
    assert pre(ws, "Edit", file_path="notes.md") is None


@pytest.mark.parametrize("command,ok", [
    ("odoo-harness feature verify F-001", True),
    ("~/.local/bin/odoo-harness feature status", True),
    ("cat git/feature_list.json", True),
    ("git -C git diff", True),
    ("git -C git push -u origin T2003", True),
    ("git -C git push origin staging", False),
    ("git -c user.name=x push origin main", False),
    ("sed -i 's/x/y/' git/feature_list.json", False),
    ("echo '{}' > git/feature_list.json", False),
    ("docker compose run --rm odoo odoo -d client_prod -u all", False),
])
def test_guard_bash_from_the_workspace(ws, command, ok):
    assert (pre(ws, "Bash", command=command) is None) is ok, command


def test_post_edit_checks_the_repository(ws):
    bad = ws.path / "git" / MODULE_DIR / "models" / "broken.py"
    bad.write_text("def broken(:\n")
    out = hook(ws, "post_edit_check", {"hook_event_name": "PostToolUse", "tool_name": "Edit",
                                       "tool_input": {"file_path": str(bad)}})
    assert out and out["decision"] == "block"


def test_stop_writes_the_repository_progress(ws):
    add_feature(ws.repo)
    start_session(ws)
    assert stop(ws) is None
    assert "Last commit" in (ws.path / "git" / "PROGRESS.md").read_text()
    assert not (ws.path / "PROGRESS.md").exists()
