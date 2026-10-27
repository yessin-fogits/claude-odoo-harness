import json
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, TESTS

sys.path.insert(0, str(ROOT / "tools"))
import make_demo_project  # noqa: E402


def test_build_demo_project(tmp_path):
    dest = make_demo_project.build(tmp_path / "demo")
    features = json.loads((dest / "feature_list.json").read_text())["features"]
    assert [f["id"] for f in features] == ["F-001"]
    assert (dest / make_demo_project.E2E_FILE).is_file()
    assert (dest / "addons/demo_mod/views/thing_menus.xml").is_file()
    assert not subprocess.run(["git", "status", "--porcelain"], cwd=dest, capture_output=True,
                              text=True).stdout.strip()
    result = subprocess.run([sys.executable, "harness/static_checks.py"], cwd=dest,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version", ["17.0", "18.0", "19.0", "20.0"])
def test_demo_module_is_valid_for_each_version(hrepo, version):
    """The adapted module passes the static and version checks of every version."""
    module = hrepo.path / "addons" / "demo_mod"
    shutil.rmtree(module)
    shutil.copytree(TESTS / "fixtures" / "demo_mod", module)
    make_demo_project.adapt_fixture_module(module, version)
    make_demo_project.add_menus(module, version)
    result = hrepo.run(sys.executable, "harness/static_checks.py", odoo_version=version)
    assert result.returncode == 0, result.stderr
