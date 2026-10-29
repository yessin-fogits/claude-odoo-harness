import json
import shutil
import subprocess
import sys

import pytest

from conftest import CLI, ROOT, TESTS

sys.path.insert(0, str(ROOT / "tools"))
import make_demo_project  # noqa: E402


def test_build_demo_project(tmp_path):
    dest = make_demo_project.build(tmp_path / "demo")
    features = json.loads((dest / "feature_list.json").read_text())["features"]
    assert [f["id"] for f in features] == ["F-001"]
    assert (dest / make_demo_project.E2E_FILE).is_file()
    assert (dest / "extra-addons/demo/demo_mod/views/thing_menus.xml").is_file()
    assert not subprocess.run(["git", "status", "--porcelain"], cwd=dest, capture_output=True,
                              text=True).stdout.strip()
    env = (dest / "harness/harness.env").read_text()
    assert "CUSTOM_ADDONS=extra-addons/demo\n" in env and "ODOO_DOCKERFILE=Dockerfile" in env
    result = subprocess.run([CLI, "static", "--all"], cwd=dest,
                            capture_output=True, text=True)
    findings = [ln for ln in result.stderr.splitlines() if ln.startswith("✗")]
    # the demo keeps the fogits rcfile as it is: it validates Odoo 17.0 on every branch
    expected = [] if make_demo_project.ODOO_VERSION == "17.0" else [
        f"✗ [L1 static] .pylintrc-mandatory:1: lint config validates Odoo 17.0, the project "
        f"runs Odoo {make_demo_project.ODOO_VERSION}"]
    assert findings == expected, result.stderr


@pytest.mark.parametrize("version", ["17.0", "18.0", "19.0", "20.0"])
def test_demo_module_is_valid_for_each_version(hrepo, version):
    """The adapted module passes the static and version checks of every version."""
    module = hrepo.path / "extra-addons" / "client" / "demo_mod"
    shutil.rmtree(module)
    shutil.copytree(TESTS / "fixtures" / "demo_mod", module)
    make_demo_project.adapt_fixture_module(module, version)
    make_demo_project.add_menus(module, version)
    files = [str(p) for p in module.rglob("*") if p.is_file()]
    result = hrepo.run(CLI, "static", *files, odoo_version=version)
    assert result.returncode == 0, result.stderr
