import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT, add_feature

HOOKS = ROOT / "hooks"


def hook(repo_or_dir, name, payload):
    path = getattr(repo_or_dir, "path", repo_or_dir)
    env = dict(getattr(repo_or_dir, "env", {}))
    env["CLAUDE_PROJECT_DIR"] = str(path)
    env.setdefault("PATH", "/usr/bin:/bin")
    # never the real ~/.odoo-harness and ~/.local/bin (conftest.harness_home)
    for key in ("ODOO_HARNESS_HOME", "ODOO_HARNESS_BIN"):
        env[key] = os.environ[key]
    result = subprocess.run([sys.executable, str(HOOKS / f"{name}.py")], input=json.dumps(payload),
                            capture_output=True, text=True, cwd=path, env=env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def pre(repo, tool, **tool_input):
    return hook(repo, "pre_tool_guard", {"hook_event_name": "PreToolUse", "tool_name": tool,
                                         "tool_input": tool_input})


def denied(out):
    return out is not None and out["hookSpecificOutput"]["permissionDecision"] == "deny"


def start_session(repo, session_id="s1", source="startup"):
    return hook(repo, "session_start", {"hook_event_name": "SessionStart", "source": source,
                                        "session_id": session_id})


def stop(repo, active=False):
    return hook(repo, "stop_gate", {"hook_event_name": "Stop", "stop_hook_active": active})


# --- plugin wiring --------------------------------------------------------------

def test_hooks_json_points_to_existing_scripts():
    config = json.loads((HOOKS / "hooks.json").read_text())
    for event, groups in config["hooks"].items():
        for group in groups:
            for h in group["hooks"]:
                script = h["command"].split("/hooks/")[1].rstrip('"')
                assert (HOOKS / script).is_file(), (event, script)


@pytest.mark.parametrize("name", ["session_start", "pre_tool_guard", "post_edit_check",
                                  "stop_gate"])
def test_hooks_do_nothing_outside_a_harness_project(tmp_path, name):
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "feature_list.json")}}
    assert hook(tmp_path, name, payload) is None


# --- SessionStart -----------------------------------------------------------------

def test_session_start_injects_state(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    out = start_session(hrepo)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "## Current state" in ctx and "## PROGRESS.md (whole project): Next steps" in ctx
    assert "## Task T1: tasks/T1.md" in ctx and "F-T1-1 User creates a demo thing" in ctx
    assert "Feature in progress: F-T1-1" in ctx
    assert "verification: e2e: e2e/test_T1_1_thing.py" in ctx
    assert "Adopt the odoo-harness" in ctx  # recent decisions
    assert "Initialization incomplete" in ctx  # BOOTSTRAP boxes not ticked
    assert "Baseline health" in ctx
    assert (hrepo.path / ".harness/session.json").is_file()


def test_session_start_names_the_task_branch(hrepo):
    result = hrepo.feature("add", "--task", "T2003", "--no-branch", "--behavior",
                           "User sees the overview", "--verify", "e2e: e2e/test_T2003_1_x.py")
    assert result.returncode == 0, result.stderr
    hrepo.commit("feature")
    hrepo.feature("start", "F-T2003-1", "--no-branch")
    ctx = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    assert "Feature in progress: F-T2003-1 — User sees the overview (Odoo task T2003)" in ctx
    assert "git checkout T2003 before working" in ctx


def test_session_start_reports_broken_integrity(hrepo):
    add_feature(hrepo)
    data = json.loads((hrepo.path / "tasks/T1.json").read_text())
    data["features"][0]["state"] = "passing"
    (hrepo.path / "tasks/T1.json").write_text(json.dumps(data))
    ctx = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    assert "Feature list integrity: FAILED" in ctx


def test_session_start_shows_a_teammates_feature_as_elsewhere(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    hrepo.commit("in progress")
    hrepo.git("checkout", "-q", "staging")
    hrepo.git("merge", "-q", "T1")
    (hrepo.path / ".harness/state.json").unlink()  # a teammate's checkout
    ctx = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    assert "In progress on other branches (teammates' work, not yours): F-T1-1 [T1]" in ctx
    assert "Feature in progress: F-T1-1" not in ctx


def test_compaction_keeps_the_session_snapshot(hrepo):
    start_session(hrepo, "s1")
    snapshot = (hrepo.path / ".harness/session.json").read_text()
    (hrepo.path / "PROGRESS.md").write_text((hrepo.path / "PROGRESS.md").read_text() + "\nnote\n")
    start_session(hrepo, "s1", source="compact")
    assert (hrepo.path / ".harness/session.json").read_text() == snapshot
    start_session(hrepo, "s2", source="startup")
    assert (hrepo.path / ".harness/session.json").read_text() != snapshot


# --- PreToolUse -------------------------------------------------------------------

@pytest.mark.parametrize("tool,field", [("Edit", "file_path"), ("Write", "file_path"),
                                        ("MultiEdit", "file_path")])
@pytest.mark.parametrize("target", ["tasks/T2003.json", "feature_list.json"])
def test_guard_denies_feature_list_edits(hrepo, tool, field, target):
    out = pre(hrepo, tool, **{field: str(hrepo.path / target)})
    assert denied(out)
    assert "odoo-harness feature" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_allows_the_task_notes(hrepo):
    assert pre(hrepo, "Edit", file_path=str(hrepo.path / "tasks/T2003.md")) is None


def test_guard_denies_evidence_edits(hrepo):
    assert denied(pre(hrepo, "Write", file_path=str(hrepo.path / "harness/evidence/F-T1-1.json")))


def test_guard_allows_module_edits(hrepo):
    assert pre(hrepo, "Edit", file_path=str(hrepo.path / "extra-addons/client/demo_mod/models/thing.py")) is None
    assert pre(hrepo, "Edit", file_path="extra-addons/client/demo_mod/models/thing.py") is None


def test_guard_denies_odoo_core_and_enterprise(hrepo):
    core = hrepo.path / "odoo-src"
    (core / "odoo/addons/base").mkdir(parents=True)
    (core / "odoo-bin").write_text("")
    assert denied(pre(hrepo, "Edit", file_path=str(core / "odoo/addons/base/models/res.py")))
    ent = hrepo.path / "enterprise/sale_subscription"
    ent.mkdir(parents=True)
    (ent / "__manifest__.py").write_text("{'name': 'x', 'author': 'Odoo S.A.', "
                                         "'license': 'OEEL-1'}")
    out = pre(hrepo, "Write", file_path=str(ent / "models/x.py"))
    assert denied(out)
    assert "sale_subscription" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_protected_paths_setting(hrepo):
    env = hrepo.path / "harness/harness.env"
    env.write_text(env.read_text().replace("PROTECTED_PATHS=", "PROTECTED_PATHS=vendor/,docs/x,"))
    assert denied(pre(hrepo, "Edit", file_path=str(hrepo.path / "vendor/lib.py")))
    assert denied(pre(hrepo, "Edit", file_path=str(hrepo.path / "docs/x/y.md")))
    assert pre(hrepo, "Edit", file_path=str(hrepo.path / "extra-addons/client/demo_mod/x.py")) is None


def test_guard_denies_enterprise_and_deployment_files(hrepo):
    env = hrepo.path / "harness/harness.env"
    env.write_text(env.read_text().replace("ENTERPRISE_DIR=\n", "ENTERPRISE_DIR=../enterprise\n"))
    assert pre(hrepo, "Edit", file_path=str(hrepo.path / "extra-addons/oca/web_x/models.py")) is None
    enterprise = hrepo.path.parent / "enterprise" / "web_studio" / "models.py"
    assert denied(pre(hrepo, "Write", file_path=str(enterprise)))
    for rel in ("Dockerfile", "odoo-stag.conf", "docker_compose_stag.yml", ".gitlab-ci.yml"):
        out = pre(hrepo, "Edit", file_path=str(hrepo.path / rel))
        assert denied(out), rel
        assert "a human edits these files" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert pre(hrepo, "Edit", file_path=str(hrepo.path / "extra-addons/client/demo_mod/x.py")) is None


def test_guard_protects_an_enterprise_checkout_set_on_this_machine(hrepo):
    """A developer whose Enterprise checkout is elsewhere sets it in the local file: the guard
    reads the same settings as the engine."""
    (hrepo.path / "harness/dev.local.env").write_text("ENTERPRISE_DIR=../odoo-ee\n")
    assert denied(pre(hrepo, "Write", file_path=str(hrepo.path.parent / "odoo-ee/web_studio/x.py")))


def test_session_start_reports_machine_settings_in_the_shared_file(hrepo):
    env = hrepo.path / "harness/harness.env"
    shared = env.read_text()
    env.write_text(shared + "DEV_DB=client_dev\n")
    (hrepo.path / "harness/dev.local.env").write_text("TEST_DB=mine\n")
    context = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    assert "holds this machine's DEV_DB" in context and "/odoo-harness:update moves them" in context
    assert "sets TEST_DB, ignored" in context
    env.write_text(shared)
    (hrepo.path / "harness/dev.local.env").write_text("DEV_DB_PASSWORD=pg-secret\n")
    context = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    assert "the dev DB mode is off on this machine" in context and "pg-secret" not in context


@pytest.mark.parametrize("command,ok", [
    ("git push -u origin T2003", True),
    ("git push origin T2003:T2003", True),
    ("git push origin staging", False),
    ("git push origin T2003:staging", False),
    ("git push origin main", False),
    ("git push", False),
    ("git push origin HEAD", False),
    ("git push --force origin T2003", False),
    ("git push origin --delete T2003", False),
    ("cd x && git push origin +T1:main", False),
])
def test_guard_pushes(hrepo, command, ok):
    assert (pre(hrepo, "Bash", command=command) is None) is ok, command


@pytest.mark.parametrize("command", [
    "echo '{}' > feature_list.json",
    "sed -i 's/in_progress/passing/' feature_list.json",
    "python3 -c \"open('feature_list.json','w').write('x')\"",
    "jq '.features[0].state=\"passing\"' feature_list.json | tee feature_list.json",
    "cp /tmp/x.json harness/evidence/F-T1-1.json",
    "echo '{}' > tasks/T1.json",
    "sed -i 's/in_progress/passing/' tasks/T1.json",
    "cp /tmp/x.json tasks/T1.json",
    "dropdb -U odoo production",
    "docker compose exec db psql -c 'DROP DATABASE client_prod'",
    "docker compose run --rm odoo odoo -d client_prod -u all --stop-after-init",
    "docker compose down -v",
    "docker volume rm client_db-data",
    "git commit --no-verify -m wip",
])
def test_guard_denies_dangerous_bash(hrepo, command):
    assert denied(pre(hrepo, "Bash", command=command)), command


@pytest.mark.parametrize("command", [
    "harness/feature.py verify F-T1-1",
    "python3 harness/feature.py status",
    "cat feature_list.json",
    "jq '.features[] | .state' feature_list.json",
    "git checkout feature_list.json",
    "cat tasks/T1.json",
    "odoo-harness feature list",
    "sed -i 's/left/done/' tasks/T1.md",
    "echo '- note' >> tasks/T1.md",
    "git diff harness/evidence/F-T1-1.json",
    "harness/init.sh --reset",
    "dropdb -U odoo harness_test",
    "docker compose run --rm odoo odoo -d harness_test -u demo_mod --stop-after-init",
    "docker compose down",
    "git commit -m 'feat: discount'",
])
def test_guard_allows_safe_bash(hrepo, command):
    assert pre(hrepo, "Bash", command=command) is None, command


def test_guard_ignores_dropdb_inside_an_argument(hrepo):
    assert pre(hrepo, "Bash", command="grep -n 'psql\\|dropdb' hooks/x.py engine/y.py") is None
    assert denied(pre(hrepo, "Bash", command="/usr/bin/dropdb -U odoo client_prod"))


@pytest.mark.parametrize("command,ok", [
    ("docker compose run --rm odoo odoo -d client_dev -u demo_mod --stop-after-init", True),
    ("docker compose run --rm odoo odoo -d client_prod -u demo_mod --stop-after-init", False),
    ("dropdb -U odoo client_dev", False),
    ("psql -c 'DROP DATABASE client_dev'", False),
    ("dropdb -U odoo harness_test", True),
])
def test_guard_dev_db_is_updated_never_dropped(hrepo, command, ok):
    # the dev DB is this developer's: the guard reads it from the local file
    (hrepo.path / "harness/dev.local.env").write_text("DEV_DB=client_dev\n")
    assert (pre(hrepo, "Bash", command=command) is None) is ok, command


@pytest.mark.parametrize("command,ok", [
    ("odoo -d stca-sta-22092026-dup -u demo_mod --stop-after-init", True),
    ("odoo -d 'stca-sta-22092026-dup' -u demo_mod --stop-after-init", True),
    ("odoo -d stca-sta-22092026-dup.old -u demo_mod --stop-after-init", False),
    ("dropdb stca-sta-22092026-dup", False),
])
def test_guard_reads_any_database_name_whole(hrepo, command, ok):
    (hrepo.path / "harness/dev.local.env").write_text("DEV_DB=stca-sta-22092026-dup\n")
    assert (pre(hrepo, "Bash", command=command) is None) is ok, command


# --- PostToolUse --------------------------------------------------------------------

def post(repo, path):
    return hook(repo, "post_edit_check", {"hook_event_name": "PostToolUse", "tool_name": "Edit",
                                          "tool_input": {"file_path": str(path)}})


def test_post_edit_reports_red_pen_for_broken_file(hrepo):
    path = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
    path.write_text("import pdb\n")
    out = post(hrepo, path)
    assert out["decision"] == "block"
    assert "[no-debug-leftovers]" in out["reason"] and "HOW TO FIX:" in out["reason"]


def test_post_edit_silent_on_clean_or_unrelated_files(hrepo):
    assert post(hrepo, hrepo.path / "extra-addons/client/demo_mod/models/thing.py") is None
    (hrepo.path / "notes.py").write_text("def x(:\n")
    assert post(hrepo, hrepo.path / "notes.py") is None


# --- Stop ---------------------------------------------------------------------------

def current_state(repo):
    return (repo.path / ".harness/current-state.md").read_text()


def test_stop_rewrites_current_state(hrepo):
    start_session(hrepo)
    assert stop(hrepo) is None
    state = current_state(hrepo)
    assert "- Last commit: " in state and "initial" in state
    assert "- Test status: not run yet" in state
    assert "- Lint: static checks clean (now)" in state
    assert "- Feature in progress: none" in state
    # machine-local: no tracked file changes, so no teammate ever merges it
    assert subprocess.run(["git", "status", "--porcelain"], cwd=hrepo.path, capture_output=True,
                          text=True).stdout == ""


def test_stop_reports_last_verify(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    hrepo.feature("verify", "F-T1-1")
    start_session(hrepo)
    stop(hrepo)
    state = current_state(hrepo)
    assert "pass (F-T1-1" in state and "runtime pass, 3 tests" in state


def test_stop_blocks_when_code_changed_without_progress(hrepo):
    start_session(hrepo)
    thing = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + "\n# more\n")
    out = stop(hrepo)
    assert out["decision"] == "block"
    assert "PROGRESS.md was not updated" in out["reason"]
    assert "extra-addons/client/demo_mod/models/thing.py" in out["reason"]
    # after the agent records its progress, the stop goes through
    progress = hrepo.path / "PROGRESS.md"
    progress.write_text(progress.read_text().replace(
        "## Known issues", "## Known issues\n- thing.py comment pending review"))
    assert stop(hrepo) is None


def test_stop_asks_for_the_task_notes_on_a_task_branch(hrepo):
    add_feature(hrepo)
    hrepo.commit("feature")
    start_session(hrepo)
    thing = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + "\n# more\n")
    out = stop(hrepo)
    assert out["decision"] == "block" and "tasks/T1.md was not updated" in out["reason"]
    notes = hrepo.path / "tasks/T1.md"
    notes.write_text(notes.read_text().replace("## Notes", "## Notes\n- comment added"))
    assert stop(hrepo) is None


def test_stop_counts_third_party_addon_changes_as_code(hrepo):
    start_session(hrepo)
    patched = hrepo.path / "extra-addons/oca/web_x/models.py"
    patched.parent.mkdir(parents=True)
    patched.write_text("# patched\n")
    out = stop(hrepo)
    assert out["decision"] == "block"
    assert "extra-addons/oca/web_x/models.py" in out["reason"]


def test_stop_blocks_on_static_findings(hrepo):
    start_session(hrepo)
    progress = hrepo.path / "PROGRESS.md"
    progress.write_text(progress.read_text() + "\n- note\n")
    (hrepo.path / "extra-addons/client/demo_mod/models/thing.py").write_text("breakpoint()\n")
    out = stop(hrepo)
    assert out["decision"] == "block"
    assert "no-debug-leftovers" in out["reason"]


def test_stop_does_not_loop_forever(hrepo):
    start_session(hrepo)
    (hrepo.path / "extra-addons/client/demo_mod/models/thing.py").write_text("breakpoint()\n")
    assert stop(hrepo)["decision"] == "block"
    assert stop(hrepo, active=True) is None
    known = (hrepo.path / "PROGRESS.md").read_text().split("## Known issues")[1]
    assert "session ended with an unclean state" in known
    stop(hrepo, active=True)
    assert (hrepo.path / "PROGRESS.md").read_text().count("session ended with an unclean") == 1


def test_stop_ignores_changes_made_before_the_session(hrepo):
    """A reviewer (or a human) opening a session on uncommitted work is not blocked for it."""
    thing = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + "\n# maker's work, before this session\n")
    start_session(hrepo, "reviewer")
    assert stop(hrepo) is None
    # but a change made during the session still counts
    thing.write_text(thing.read_text() + "\n# changed during the session\n")
    out = stop(hrepo)
    assert out["decision"] == "block" and "extra-addons/client/demo_mod/models/thing.py" in out["reason"]


# --- one plugin, installed once per machine -------------------------------------------

def test_session_start_names_the_version_and_its_guide(hrepo):
    from conftest import ODOO_VERSION
    context = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    guide = ROOT / "skills" / "odoo" / "versions" / ODOO_VERSION / "GUIDE.md"
    assert f"Odoo version: {ODOO_VERSION}." in context and str(guide) in context


def test_session_start_puts_the_command_on_the_bash_path(hrepo, tmp_path):
    env_file = tmp_path / "claude.env"
    hrepo.env["CLAUDE_ENV_FILE"] = str(env_file)
    start_session(hrepo)
    assert f'export PATH="{ROOT / "bin"}:$PATH"' in env_file.read_text()


def test_session_start_refreshes_the_stable_path(tmp_path):
    hook(tmp_path, "session_start", {"hook_event_name": "SessionStart", "source": "startup"})
    current = Path(os.environ["ODOO_HARNESS_HOME"]) / "current"
    shim = Path(os.environ["ODOO_HARNESS_BIN"]) / "odoo-harness"
    assert current.resolve() == ROOT
    assert shim.resolve() == (ROOT / "bin" / "odoo-harness").resolve()


def test_session_start_warns_when_the_engine_is_older_than_the_pin(hrepo):
    env = hrepo.path / "harness/harness.env"
    env.write_text(re.sub(r"^HARNESS_VERSION=.*$", "HARNESS_VERSION=99.0.0", env.read_text(),
                          flags=re.M))
    context = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    assert "needs odoo-harness 99.0.0" in context and "claude plugin update" in context


def odoo_repo(path):
    module = path / "addons" / "my_mod"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name': 'x'}")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def test_session_start_offers_init_once_in_an_odoo_repository(tmp_path):
    repo = odoo_repo(tmp_path / "proj")
    first = hook(repo, "session_start", {"hook_event_name": "SessionStart", "source": "startup"})
    assert "/odoo-harness:init" in first["hookSpecificOutput"]["additionalContext"]
    again = hook(repo, "session_start", {"hook_event_name": "SessionStart", "source": "startup"})
    assert again is None


def test_session_start_offers_nothing_outside_odoo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("")
    assert hook(tmp_path, "session_start", {"hook_event_name": "SessionStart"}) is None


def make_legacy(repo):
    (repo.path / "harness/feature.py").write_text("# old vendored copy\n")


def test_hooks_stand_down_on_an_unmigrated_repository(hrepo):
    make_legacy(hrepo)
    context = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    assert "/odoo-harness:update" in context and "## Features" not in context
    # the old per-version plugin still guards it; this one does not answer twice
    assert pre(hrepo, "Edit", file_path=str(hrepo.path / "feature_list.json")) is None
    assert stop(hrepo) is None


@pytest.mark.parametrize("target", ["engine/verify.py", "hooks/stop_gate.py", "skills/odoo/SKILL.md"])
def test_guard_denies_edits_of_the_engine(hrepo, target):
    out = pre(hrepo, "Edit", file_path=str(ROOT / target))
    assert denied(out) and "harness engine" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_denies_edits_through_the_stable_path(hrepo):
    home = Path(os.environ["ODOO_HARNESS_HOME"])
    assert denied(pre(hrepo, "Write", file_path=str(home / "current" / "engine" / "hlib.py")))
