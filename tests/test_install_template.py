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

sys.path.insert(0, str(ROOT / "tools"))
from make_demo_project import write_layout  # noqa: E402

VERSION = install_template.ODOO_VERSION


def run_install(target, *extra):
    return install_template.main([str(target), *extra])


def module(target, path, author="fogits"):
    mod = target / path
    mod.mkdir(parents=True)
    (mod / "__init__.py").write_text("")
    (mod / "__manifest__.py").write_text(
        f"{{'name': '{mod.name}', 'version': '{VERSION}.1.0.0', 'author': '{author}', "
        "'license': 'LGPL-3', 'depends': ['base']}")


@pytest.fixture
def repo(tmp_path):
    """A fogits project checked out in ~/Project/acme/git, enterprise next to it."""
    target = tmp_path / "acme" / "git"
    target.mkdir(parents=True)
    write_layout(target, client="acme")
    module(target, "extra-addons/acme/sale_x")
    module(target, "extra-addons/acme/stock_y")
    module(target, "extra-addons/oca/web_tool", author="Odoo Community Association (OCA)")
    (tmp_path / "acme" / "enterprise" / "web_studio").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "staging"], cwd=target, check=True)
    return target


def test_installs_all_template_files(repo):
    run_install(repo)
    for rel in ["CLAUDE.md", "BOOTSTRAP.md", "PROGRESS.md", "DECISIONS.md", "feature_list.json",
                "harness/docker-compose.yml", "harness/odoo.conf", ".claude/settings.json",
                ".gitignore", "harness/init.sh", "harness/lib.sh", "harness/harness.env"]:
        assert (repo / rel).is_file(), rel
    assert not (repo / "gitignore").exists()
    # the project's own deployment files are never replaced by the harness
    assert not (repo / "docker-compose.yml").exists() and not (repo / "odoo.conf").exists()


def test_no_placeholder_left(repo):
    run_install(repo)
    for path in repo.rglob("*"):
        if path.is_file():
            assert "{{" not in path.read_text(), path


def test_layout_is_detected(repo):
    run_install(repo, "--test-db", "my_test", "--port", "8070")
    env = (repo / "harness/harness.env").read_text()
    assert f"ODOO_VERSION={VERSION}" in env
    assert "CUSTOM_ADDONS=extra-addons/acme\n" in env
    assert "THIRD_PARTY_ADDONS=extra-addons/oca\n" in env
    assert "ENTERPRISE_DIR=../enterprise\n" in env
    assert "ODOO_DOCKERFILE=Dockerfile\n" in env and "ODOO_IMAGE=acme-harness-odoo:local" in env
    assert "BASE_BRANCH=staging" in env
    assert "TEST_DB=my_test" in env and "ODOO_PORT=8070" in env
    assert "COMPOSE_PROJECT_NAME=acme-harness" in env  # the repo is checked out in acme/git
    protected = env.split("PROTECTED_PATHS=")[1].splitlines()[0].split(",")
    assert {"Dockerfile", "odoo-stag.conf", "docker_compose_stag.yml", ".gitlab-ci.yml"} <= set(
        protected)
    conf = (repo / "harness/odoo.conf").read_text()
    assert "dbfilter = ^my_test$" in conf
    assert ("addons_path = /mnt/repo/extra-addons/acme,/mnt/repo/extra-addons/oca,"
            "/mnt/enterprise\n") in conf
    demo = "with_demo = True" if int(VERSION.split(".")[0]) >= 19 else "without_demo = False"
    assert demo in conf


def test_overrides_win_over_detection(repo):
    run_install(repo, "--custom-addons", "extra-addons/acme,extra-addons/shared",
                "--third-party-addons", "", "--enterprise-dir", "", "--dockerfile", "",
                "--base-branch", "develop")
    env = (repo / "harness/harness.env").read_text()
    assert "CUSTOM_ADDONS=extra-addons/acme,extra-addons/shared" in env
    assert "THIRD_PARTY_ADDONS=\n" in env and "ENTERPRISE_DIR=\n" in env
    assert f"ODOO_IMAGE=odoo:{VERSION}" in env and "BASE_BRANCH=develop" in env
    assert "addons_path = /mnt/repo/extra-addons/acme,/mnt/repo/extra-addons/shared\n" in (
        repo / "harness/odoo.conf").read_text()
    assert (repo / "extra-addons/shared").is_dir()


def test_refuses_a_project_of_another_odoo_version(repo):
    other = "16.0" if VERSION != "16.0" else "17.0"
    dockerfile = repo / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text().replace(f"odoo:{VERSION}", f"odoo:{other}"))
    with pytest.raises(SystemExit, match=f"odoo-harness-{other.split('.')[0]}@odoo-harness"):
        run_install(repo)


def test_fresh_repository_without_layout(tmp_path):
    """A new project with no config yet: modules go to addons/ by default."""
    target = tmp_path / "newproj"
    target.mkdir()
    run_install(target)
    env = (target / "harness/harness.env").read_text()
    assert "CUSTOM_ADDONS=addons\n" in env and (target / "addons").is_dir()


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
        install_template.parse_args([str(repo)])))
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
    marketplace = settings["extraKnownMarketplaces"]["odoo-harness"]["source"]
    assert marketplace == {"source": "github", "repo": "yessin-fogits/claude-odoo-harness",
                           "ref": "main"}


def test_existing_gitignore_is_merged(repo):
    (repo / ".gitignore").write_text("*.pyc")
    run_install(repo)
    run_install(repo)
    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines[0] == "*.pyc"
    assert lines.count(".harness/") == 1


@pytest.mark.parametrize("args", [
    ["--test-db", "x;drop"],
    ["--custom-addons", "../outside"],
    ["--custom-addons", "/abs"],
    ["--dockerfile", "../Dockerfile"],
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
    subprocess.run(["docker", "compose", "--project-directory", ".", "-f",
                    "harness/docker-compose.yml", "--env-file", "harness/harness.env", "config",
                    "-q"], cwd=repo, check=True)


def test_init_check_reports_red_pen_without_docker(repo, tmp_path):
    """Without a docker CLI, init.sh must fail with a WHY / HOW TO FIX message."""
    run_install(repo)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in ["bash", "dirname", "mkdir", "cat", "grep", "head", "python3"]:
        (fake_bin / tool).symlink_to(shutil.which(tool))
    result = subprocess.run([str(repo / "harness/init.sh"), "--check"], capture_output=True,
                            text=True, env={"PATH": str(fake_bin)})
    assert result.returncode == 1
    assert "✗ [env] docker not found" in result.stderr
    assert "WHY:" in result.stderr and "HOW TO FIX:" in result.stderr


# --- update ---------------------------------------------------------------------

def test_update_replaces_harness_files_and_keeps_the_rest(repo, capsys):
    run_install(repo, "--test-db", "client_test", "--port", "8070")
    (repo / "harness/verify.py").write_text("# old harness version\n")
    (repo / "PROGRESS.md").write_text("my progress")
    conftest = repo / "e2e/conftest.py"
    conftest.write_text(conftest.read_text() + "# project customization\n")
    capsys.readouterr()
    assert install_template.main([str(repo), "--update"]) == 0
    out = capsys.readouterr().out
    assert "updated  harness/verify.py" in out
    assert "kept*    e2e/conftest.py" in out and "--show <file>" in out
    assert "# old harness version" not in (repo / "harness/verify.py").read_text()
    assert (repo / "PROGRESS.md").read_text() == "my progress"
    assert conftest.read_text().endswith("# project customization\n")
    env = (repo / "harness/harness.env").read_text()
    assert "TEST_DB=client_test" in env and "ODOO_PORT=8070" in env
    assert "CUSTOM_ADDONS=extra-addons/acme\n" in env


def test_update_appends_new_settings_to_harness_env(repo):
    run_install(repo)
    env = repo / "harness/harness.env"
    env.write_text("\n".join(line for line in env.read_text().splitlines()
                             if not line.startswith("PROTECTED_PATHS")) + "\n")
    install_template.main([str(repo), "--update"])
    text = env.read_text()
    assert text.count("PROTECTED_PATHS=") == 1
    assert "CUSTOM_ADDONS=extra-addons/acme\n" in text


def test_update_migrates_a_module_list_harness(repo):
    """Harnesses installed before full-project mode had MODULES and ADDONS_DIR."""
    run_install(repo)
    env = repo / "harness/harness.env"
    env.write_text("\n".join(line for line in env.read_text().splitlines()
                             if not line.startswith(("CUSTOM_ADDONS", "THIRD_PARTY_ADDONS")))
                   + "\nADDONS_DIR=extra-addons/acme\nMODULES=sale_x\n")
    install_template.main([str(repo), "--update"])
    text = env.read_text()
    assert "CUSTOM_ADDONS=extra-addons/acme\n" in text
    assert "/mnt/repo/extra-addons/acme" in (repo / "harness/odoo.conf").read_text()


def test_update_is_idempotent(repo):
    run_install(repo)
    install_template.main([str(repo), "--update"])
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    install_template.main([str(repo), "--update"])
    assert {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()} == before


def test_update_refuses_another_odoo_version(repo):
    run_install(repo)
    env = repo / "harness/harness.env"
    env.write_text(env.read_text().replace(f"ODOO_VERSION={install_template.ODOO_VERSION}",
                                           "ODOO_VERSION=16.0"))
    with pytest.raises(SystemExit, match="version migration"):
        install_template.main([str(repo), "--update"])


def test_update_needs_an_installed_harness(repo):
    with pytest.raises(SystemExit, match="needs an installed harness"):
        install_template.main([str(repo), "--update"])


def test_show_renders_with_project_values(repo, capsys):
    run_install(repo, "--test-db", "client_test")
    capsys.readouterr()
    install_template.main([str(repo), "--show", "harness/odoo.conf"])
    assert "dbfilter = ^client_test$" in capsys.readouterr().out


def test_project_error_catalog_is_kept_and_used(repo):
    run_install(repo)
    catalog = repo / "harness/errors_project.py"
    catalog.write_text(catalog.read_text().replace(
        "PROJECT_CATALOG = [\n]",
        'PROJECT_CATALOG = [\n    Entry("custom", r"boom (\\w+)", "it went boom: {1}", "defuse {1}"),\n]'))
    install_template.main([str(repo), "--update"])
    assert '"custom"' in catalog.read_text()
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'harness'); import errors; "
                               "print(errors.explain('boom bomb'))"],
        cwd=repo, capture_output=True, text=True)
    assert "it went boom: bomb" in result.stdout and "defuse bomb" in result.stdout


def test_settings_enable_auto_update(repo):
    run_install(repo)
    settings = json.loads((repo / ".claude/settings.json").read_text())
    assert settings["extraKnownMarketplaces"]["odoo-harness"]["autoUpdate"] is True
