"""Claude Code started in the client workspace (~/Project/<client>), the harness in git/."""

import json
import shutil
from types import SimpleNamespace

import pytest

import install_template
from conftest import MODULE_DIR, TESTS, HarnessRepo, add_feature
from make_demo_project import adapt_fixture_module, write_layout
from test_hooks import denied, hook, pre, start_session, stop

MAJOR = install_template.ODOO_VERSION.split(".")[0]


@pytest.fixture
def ws(tmp_path):
    """~/Project/acme with the repository in git/ and Odoo Enterprise in enterprise/."""
    workspace = tmp_path / "acme"
    target = workspace / "git"
    target.mkdir(parents=True)
    (workspace / "enterprise" / "web_studio").mkdir(parents=True)
    write_layout(target, client="client")
    module = target / MODULE_DIR
    shutil.copytree(TESTS / "fixtures" / "demo_mod", module,
                    ignore=shutil.ignore_patterns("__pycache__"))
    adapt_fixture_module(module)
    repo = HarnessRepo(target, tmp_path / "calls.jsonl")
    repo.git("init", "-q", "-b", "staging")
    install_template.main([str(target), "--enterprise-dir", "../enterprise",
                           "--workspace", str(workspace)])
    repo.commit("initial")
    return SimpleNamespace(path=workspace, env=repo.env, repo=repo)


# --- installer --------------------------------------------------------------------

def test_workspace_files_import_the_repository(ws):
    claude = (ws.path / "CLAUDE.md").read_text()
    assert "@git/CLAUDE.md" in claude
    assert "`enterprise/`, read-only" in claude
    assert f"/odoo-harness-{MAJOR}:update" in claude
    assert "{{" not in claude
    settings = json.loads((ws.path / ".claude/settings.json").read_text())
    assert settings["enabledPlugins"][f"odoo-harness-{MAJOR}@odoo-harness"] is True
    assert "Bash(git/harness/feature.py:*)" in settings["permissions"]["allow"]
    assert "Bash(git -C git status:*)" in settings["permissions"]["allow"]
    assert "Edit(git/feature_list.json)" in settings["permissions"]["deny"]
    assert "Read(git/.env)" in settings["permissions"]["deny"]


def test_workspace_files_are_not_in_the_repository(ws):
    assert not (ws.path / "git" / "git").exists()
    assert "@git/CLAUDE.md" not in (ws.path / "git" / "CLAUDE.md").read_text()


def test_workspace_files_are_merged(ws):
    (ws.path / "CLAUDE.md").write_text("# My notes\n")
    settings = ws.path / ".claude/settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(make:*)"]}}))
    install_template.main([str(ws.path / "git"), "--workspace", str(ws.path), "--workspace-only"])
    install_template.main([str(ws.path / "git"), "--workspace", str(ws.path), "--workspace-only"])
    claude = (ws.path / "CLAUDE.md").read_text()
    assert claude.startswith("# My notes\n") and claude.count("@git/CLAUDE.md") == 1
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    assert "Bash(make:*)" in allow and allow.count("Bash(git/harness/feature.py:*)") == 1


def test_workspace_only_does_not_touch_the_repository(ws):
    (ws.path / "CLAUDE.md").unlink()
    install_template.main([str(ws.path / "git"), "--workspace", str(ws.path), "--workspace-only"])
    assert (ws.path / "CLAUDE.md").is_file()
    assert ws.repo.run("git", "status", "--porcelain").stdout == ""


@pytest.mark.parametrize("extra", [["--workspace-only"], ["--workspace", "{other}"],
                                   ["--workspace", "{repo}"]])
def test_workspace_errors(ws, tmp_path, extra):
    other = tmp_path / "other"
    other.mkdir()
    args = [a.format(other=other, repo=ws.path / "git") for a in extra]
    with pytest.raises(SystemExit):
        install_template.main([str(ws.path / "git"), *args])


# --- hooks ------------------------------------------------------------------------

def test_session_start_finds_the_repository(ws):
    context = start_session(ws)["hookSpecificOutput"]["additionalContext"]
    assert "## Workspace" in context and "`git/harness/feature.py ...`" in context
    assert "PROGRESS.md" in context
    assert "the project rules; this workspace does not import it" not in context
    assert (ws.path / "git" / ".harness" / "session.json").is_file()
    assert not (ws.path / ".harness").exists()


def test_session_start_brings_the_rules_without_workspace_files(ws):
    (ws.path / "CLAUDE.md").unlink()
    context = start_session(ws)["hookSpecificOutput"]["additionalContext"]
    assert "this workspace does not import it" in context
    assert "# Work Rules" in context
    assert f"/odoo-harness-{MAJOR}:update" in context


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
    ("git/harness/feature.py verify F-001", True),
    ("python3 git/harness/feature.py status", True),
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
