"""The odoo-harness command: finds the repository, refuses what it must, runs the engine."""

import os
import re
import subprocess
from pathlib import Path

from conftest import CLI, ROOT


def cli(cwd, *args, env=None):
    return subprocess.run([CLI, *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def test_help_lists_the_commands(tmp_path):
    out = cli(tmp_path, "--help").stdout
    for command in ("init", "verify", "feature", "loop", "gitlab", "guide", "map", "static",
                    "compose", "link", "where"):
        assert f"odoo-harness {command}" in out


def test_no_harness_is_a_red_pen(tmp_path):
    result = cli(tmp_path, "feature", "status")
    assert result.returncode == 2
    assert "no harness in" in result.stderr and "/odoo-harness:init" in result.stderr


def test_unknown_command(tmp_path):
    result = cli(tmp_path, "deploy")
    assert result.returncode == 2 and "unknown command" in result.stderr


def test_finds_the_repository_from_a_subfolder(hrepo):
    sub = hrepo.path / "extra-addons"
    result = cli(sub, "where")
    assert result.returncode == 0 and f"repository: {hrepo.path.resolve()}" in result.stdout


def test_refuses_a_project_pinned_to_a_newer_engine(hrepo):
    env = hrepo.path / "harness/harness.env"
    env.write_text(re.sub(r"^HARNESS_VERSION=.*$", "HARNESS_VERSION=99.0.0", env.read_text(),
                          flags=re.M))
    result = cli(hrepo.path, "feature", "status")
    assert result.returncode == 2 and "needs odoo-harness 99.0.0" in result.stderr


def test_evidence_records_the_engine_version(hrepo):
    from conftest import add_feature
    add_feature(hrepo)
    hrepo.commit("feature")
    hrepo.feature("start", "F-001", "--no-branch")
    (hrepo.path / "extra-addons/client/demo_mod/models/thing.py").write_text(
        (hrepo.path / "extra-addons/client/demo_mod/models/thing.py").read_text() + "# F-001\n")
    result = hrepo.feature("verify", "F-001")
    assert result.returncode == 0, result.stderr
    import json
    evidence = json.loads((hrepo.path / "harness/evidence/F-001.json").read_text())
    assert evidence["engine_version"] == (ROOT / "engine" / "VERSION").read_text().strip()


def test_link_writes_the_stable_path_and_the_shim(tmp_path):
    env = {"ODOO_HARNESS_HOME": str(tmp_path / "h"), "ODOO_HARNESS_BIN": str(tmp_path / "bin")}
    assert cli(tmp_path, "link", env=env).returncode == 0
    assert (tmp_path / "h" / "current").resolve() == ROOT
    shim = tmp_path / "bin" / "odoo-harness"
    assert os.readlink(shim) == str(tmp_path / "h" / "current" / "bin" / "odoo-harness")
    # the shim runs the command through the stable path
    result = subprocess.run([str(shim), "--help"], capture_output=True, text=True)
    assert result.returncode == 0 and "odoo-harness feature" in result.stdout
    # idempotent: a second run changes nothing
    again = cli(tmp_path, "link", env=env).stdout
    assert "->" not in again
    # and it never replaces a file that is not ours
    shim.unlink()
    shim.write_text("#!/bin/sh\n")
    out = cli(tmp_path, "link", env=env).stdout
    assert "is not ours" in out and shim.read_text() == "#!/bin/sh\n"


def test_nested_commands_reach_the_same_engine(hrepo):
    """Children of odoo-harness (loop.py's agents, git hooks) find it on their PATH."""
    result = hrepo.run(CLI, "compose", "--version", harness_compose="sh -c 'command -v odoo-harness' x")
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == ROOT / "bin" / "odoo-harness"
