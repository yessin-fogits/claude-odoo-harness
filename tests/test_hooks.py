import json
import subprocess
import sys

import pytest

from conftest import ROOT, add_feature

HOOKS = ROOT / "hooks"


def hook(repo_or_dir, name, payload):
    path = getattr(repo_or_dir, "path", repo_or_dir)
    env = dict(getattr(repo_or_dir, "env", {}))
    env["CLAUDE_PROJECT_DIR"] = str(path)
    env.setdefault("PATH", "/usr/bin:/bin")
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
    hrepo.feature("start", "F-001")
    out = start_session(hrepo)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "## PROGRESS.md: Current state" in ctx and "## PROGRESS.md: Next steps" in ctx
    assert "Feature in progress: F-001" in ctx
    assert "verification: e2e: e2e/test_F001_thing.py" in ctx
    assert "Adopt the odoo-harness" in ctx  # recent decisions
    assert "Initialization incomplete" in ctx  # BOOTSTRAP boxes not ticked
    assert "Baseline health" in ctx
    assert (hrepo.path / ".harness/session.json").is_file()


def test_session_start_reports_broken_integrity(hrepo):
    add_feature(hrepo)
    data = json.loads((hrepo.path / "feature_list.json").read_text())
    data["features"][0]["state"] = "passing"
    (hrepo.path / "feature_list.json").write_text(json.dumps(data))
    ctx = start_session(hrepo)["hookSpecificOutput"]["additionalContext"]
    assert "Feature list integrity: FAILED" in ctx


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
def test_guard_denies_feature_list_edits(hrepo, tool, field):
    out = pre(hrepo, tool, **{field: str(hrepo.path / "feature_list.json")})
    assert denied(out)
    assert "harness/feature.py" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_guard_denies_evidence_edits(hrepo):
    assert denied(pre(hrepo, "Write", file_path=str(hrepo.path / "harness/evidence/F-001.json")))


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


def test_guard_denies_third_party_enterprise_and_deployment_files(hrepo):
    env = hrepo.path / "harness/harness.env"
    env.write_text(env.read_text().replace("ENTERPRISE_DIR=\n", "ENTERPRISE_DIR=../enterprise\n"))
    out = pre(hrepo, "Edit", file_path=str(hrepo.path / "extra-addons/oca/web_x/models.py"))
    assert denied(out) and "third-party addon" in out["hookSpecificOutput"][
        "permissionDecisionReason"]
    enterprise = hrepo.path.parent / "enterprise" / "web_studio" / "models.py"
    assert denied(pre(hrepo, "Write", file_path=str(enterprise)))
    for rel in ("Dockerfile", "odoo-stag.conf", "docker_compose_stag.yml", ".gitlab-ci.yml"):
        out = pre(hrepo, "Edit", file_path=str(hrepo.path / rel))
        assert denied(out), rel
        assert "a human edits these files" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert pre(hrepo, "Edit", file_path=str(hrepo.path / "extra-addons/client/demo_mod/x.py")) is None


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
    "cp /tmp/x.json harness/evidence/F-001.json",
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
    "harness/feature.py verify F-001",
    "python3 harness/feature.py status",
    "cat feature_list.json",
    "jq '.features[] | .state' feature_list.json",
    "git checkout feature_list.json",
    "git diff harness/evidence/F-001.json",
    "harness/init.sh --reset",
    "dropdb -U odoo harness_test",
    "docker compose run --rm odoo odoo -d harness_test -u demo_mod --stop-after-init",
    "docker compose down",
    "git commit -m 'feat: discount'",
])
def test_guard_allows_safe_bash(hrepo, command):
    assert pre(hrepo, "Bash", command=command) is None, command


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
    text = (repo.path / "PROGRESS.md").read_text()
    return text.split("## Current state")[1].split("\n## ")[0]


def test_stop_rewrites_current_state(hrepo):
    start_session(hrepo)
    assert stop(hrepo) is None
    state = current_state(hrepo)
    assert "- Last commit: " in state and "initial" in state
    assert "- Test status: not run yet" in state
    assert "- Lint: static checks clean (now)" in state
    assert "- Feature in progress: none" in state
    # the other sections are untouched
    assert "## Next steps" in (hrepo.path / "PROGRESS.md").read_text()


def test_stop_reports_last_verify(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-001")
    hrepo.feature("verify", "F-001")
    start_session(hrepo)
    stop(hrepo)
    state = current_state(hrepo)
    assert "pass (F-001" in state and "runtime pass, 3 tests" in state


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
