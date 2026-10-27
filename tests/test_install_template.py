import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import install_template  # noqa: E402


def run_install(target, *extra):
    return install_template.main([str(target), "--modules", "sale_x,stock_y", *extra])


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / "client-project"
    target.mkdir()
    return target


def test_installs_all_template_files(repo):
    run_install(repo)
    for rel in ["CLAUDE.md", "BOOTSTRAP.md", "PROGRESS.md", "DECISIONS.md", "feature_list.json",
                "docker-compose.yml", "odoo.conf", ".claude/settings.json", ".gitignore",
                "harness/init.sh", "harness/lib.sh", "harness/harness.env"]:
        assert (repo / rel).is_file(), rel
    assert (repo / "addons").is_dir()
    assert not (repo / "gitignore").exists()


def test_no_placeholder_left(repo):
    run_install(repo)
    for path in repo.rglob("*"):
        if path.is_file():
            assert "{{" not in path.read_text(), path


def test_values_are_filled(repo):
    run_install(repo, "--test-db", "my_test", "--port", "8070")
    env = (repo / "harness/harness.env").read_text()
    assert f"ODOO_VERSION={install_template.ODOO_VERSION}" in env
    assert "MODULES=sale_x,stock_y" in env
    assert "TEST_DB=my_test" in env
    assert "ODOO_PORT=8070" in env
    assert "COMPOSE_PROJECT_NAME=client-project" in env
    assert "dbfilter = ^my_test$" in (repo / "odoo.conf").read_text()


def test_feature_list_is_minimal_and_empty(repo):
    run_install(repo)
    data = json.loads((repo / "feature_list.json").read_text())
    assert data == {"version": 1, "features": []}


def test_progress_has_required_sections(repo):
    run_install(repo)
    progress = (repo / "PROGRESS.md").read_text()
    for section in ["## Current state", "## Completed tasks", "## In progress",
                    "## Known issues", "## Next steps"]:
        assert section in progress
    for item in ["Last commit", "Test status", "Lint"]:
        assert item in progress


def test_claude_md_has_rules(repo):
    run_install(repo)
    claude = (repo / "CLAUDE.md").read_text()
    for heading in ["# Work Rules", "# Feature List Rules", "# Definition of Done",
                    "# Validation Hierarchy"]:
        assert heading in claude
    assert "WIP = 1" in claude


def test_scripts_are_executable(repo):
    run_install(repo)
    assert os.access(repo / "harness/init.sh", os.X_OK)


def test_rerun_is_idempotent(repo):
    run_install(repo)
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    report = install_template.install(*install_template.build_context(
        install_template.parse_args([str(repo), "--modules", "sale_x,stock_y"])))
    assert all(action == "kept" for action, _ in report), report
    after = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert before == after


def test_state_files_never_overwritten_even_with_force(repo):
    run_install(repo)
    (repo / "PROGRESS.md").write_text("my progress")
    (repo / "feature_list.json").write_text('{"version": 1, "features": [{"id": "F-001"}]}')
    run_install(repo, "--force")
    assert (repo / "PROGRESS.md").read_text() == "my progress"
    assert "F-001" in (repo / "feature_list.json").read_text()


def test_existing_claude_md_is_merged_not_replaced(repo):
    (repo / "CLAUDE.md").write_text("# Project notes\nKeep me.\n")
    run_install(repo)
    claude = (repo / "CLAUDE.md").read_text()
    assert claude.startswith("# Project notes\nKeep me.\n")
    assert claude.count("<!-- odoo-harness:start -->") == 1
    run_install(repo)
    assert (repo / "CLAUDE.md").read_text().count("<!-- odoo-harness:start -->") == 1


def test_existing_settings_are_merged(repo):
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_text(json.dumps(
        {"permissions": {"allow": ["Bash(make:*)"]}, "model": "x"}))
    run_install(repo)
    settings = json.loads((repo / ".claude/settings.json").read_text())
    assert "Bash(make:*)" in settings["permissions"]["allow"]
    assert "Edit(feature_list.json)" in settings["permissions"]["deny"]
    assert settings["model"] == "x"
    major = install_template.ODOO_VERSION.split(".")[0]
    assert settings["enabledPlugins"][f"odoo-harness-{major}@odoo-harness"] is True


def test_existing_gitignore_is_merged(repo):
    (repo / ".gitignore").write_text("*.pyc")
    run_install(repo)
    run_install(repo)
    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines[0] == "*.pyc"
    assert lines.count(".harness/") == 1


@pytest.mark.parametrize("args", [
    ["--modules", "Bad-Name"],
    ["--test-db", "x;drop"],
    ["--addons-dir", "../outside"],
    ["--addons-dir", "/abs"],
])
def test_rejects_invalid_values(repo, args):
    with pytest.raises(SystemExit):
        install_template.main([str(repo), *args])


def test_shell_scripts_pass_syntax_and_shellcheck(repo):
    run_install(repo)
    for script in ["harness/init.sh", "harness/lib.sh"]:
        subprocess.run(["bash", "-n", str(repo / script)], check=True)
    if shutil.which("shellcheck"):
        subprocess.run(["shellcheck", "-x", "harness/init.sh", "harness/lib.sh"],
                       cwd=repo, check=True)


@pytest.mark.skipif(not shutil.which("docker"), reason="docker CLI not installed")
def test_compose_file_is_valid(repo):
    run_install(repo)
    subprocess.run(["docker", "compose", "--env-file", "harness/harness.env", "config", "-q"],
                   cwd=repo, check=True)


def test_init_check_reports_red_pen_without_docker(repo, tmp_path):
    """Without a docker CLI, init.sh must fail with a WHY / HOW TO FIX message."""
    run_install(repo)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in ["bash", "dirname", "mkdir", "cat", "grep", "head"]:
        (fake_bin / tool).symlink_to(shutil.which(tool))
    result = subprocess.run([str(repo / "harness/init.sh"), "--check"], capture_output=True,
                            text=True, env={"PATH": str(fake_bin)})
    assert result.returncode == 1
    assert "✗ [env] docker not found" in result.stderr
    assert "WHY:" in result.stderr and "HOW TO FIX:" in result.stderr
