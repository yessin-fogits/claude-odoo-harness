import sys

import pytest

from conftest import IR_ACCESS, ODOO_VERSION
from test_verify import load

static_checks = load("static_checks")
errors = load("errors")


def write(repo, rel, text):
    path = repo.path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def run_static(repo, *files):
    return repo.run(sys.executable, "harness/static_checks.py", *files)


def test_fixture_module_is_clean(hrepo):
    result = run_static(hrepo)
    assert result.returncode == 0, result.stderr


def test_manifest_version_and_missing_data_file(hrepo):
    write(hrepo, "extra-addons/client/demo_mod/__manifest__.py",
          '{"name": "D", "version": "16.0.1.0.0", "license": "LGPL-3", "depends": ["base"],'
          ' "data": ["views/missing.xml"]}')
    result = run_static(hrepo)
    assert result.returncode == 1
    assert f"is not {ODOO_VERSION}.x.y.z" in result.stderr
    assert "'data' lists 'views/missing.xml', which does not exist" in result.stderr


def test_broken_xml_points_to_line(hrepo):
    write(hrepo, "extra-addons/client/demo_mod/views/thing_views.xml", "<odoo>\n<record>\n</odoo>\n")
    result = run_static(hrepo)
    assert "views/thing_views.xml:3: XML is not well formed" in result.stderr


ACCESS_CSV = "ir.access.csv" if IR_ACCESS else "ir.model.access.csv"


def test_access_csv_header(hrepo):
    write(hrepo, f"extra-addons/client/demo_mod/security/{ACCESS_CSV}", "id,name,model\n")
    assert f"wrong {ACCESS_CSV} header" in run_static(hrepo).stderr


def test_access_csv_accepts_odoo_quoted_header(hrepo):
    path = hrepo.path / f"extra-addons/client/demo_mod/security/{ACCESS_CSV}"
    lines = path.read_text().splitlines()
    lines[0] = ",".join(f'"{c}"' for c in lines[0].split(","))
    path.write_text("\n".join(lines) + "\n")
    assert run_static(hrepo).returncode == 0


@pytest.mark.parametrize("version,name,ok", [
    ("19.0", "ir.model.access.csv", True), ("19.0", "ir.access.csv", False),
    ("20.0", "ir.access.csv", True), ("20.0", "ir.model.access.csv", False),
])
def test_security_csv_matches_version(hrepo, version, name, ok):
    for old in ("ir.model.access.csv", "ir.access.csv"):
        (hrepo.path / f"extra-addons/client/demo_mod/security/{old}").unlink(missing_ok=True)
    content = ("id,name,model_id,group_id/id,operation,domain\n"
               "a,demo,demo.thing,base.group_user,crud,\n") if name == "ir.access.csv" else (
               "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
               "a,demo,model_demo_thing,base.group_user,1,1,1,1\n")
    path = write(hrepo, f"extra-addons/client/demo_mod/security/{name}", content)
    result = hrepo.run(sys.executable, "harness/static_checks.py", str(path), odoo_version=version)
    assert (result.returncode == 0) is ok, result.stderr


def test_ir_access_operation_must_be_canonical(hrepo):
    path = write(hrepo, "extra-addons/client/demo_mod/security/ir.access.csv",
                 "id,name,model_id,group_id/id,operation,domain\n"
                 "a,demo,demo.thing,base.group_user,ur,\n"
                 'b,demo,demo.thing,base.group_user,r,"[(\'user_id\', \'=\', user.id)]"\n')
    result = hrepo.run(sys.executable, "harness/static_checks.py", str(path), odoo_version="20.0")
    assert "ir.access.csv:2: invalid operation 'ur'" in result.stderr
    assert ":3:" not in result.stderr


def test_debug_leftovers_project_check(hrepo):
    write(hrepo, "extra-addons/client/demo_mod/models/thing.py", "import pdb\n")
    write(hrepo, "extra-addons/client/demo_mod/static/src/x.js", "  debugger;\n")
    result = run_static(hrepo)
    assert "[no-debug-leftovers] debug statement: import pdb" in result.stderr
    assert "x.js:1: [no-debug-leftovers]" in result.stderr


def test_file_mode_checks_only_given_files(hrepo):
    bad = write(hrepo, "extra-addons/client/demo_mod/models/bad.py", "def x(:\n")
    good = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
    assert run_static(hrepo, str(good)).returncode == 0
    assert run_static(hrepo, str(bad)).returncode == 1


def test_modules_outside_scope_are_ignored(hrepo):
    write(hrepo, "vendor/not_mine/__manifest__.py", "{broken")
    assert run_static(hrepo).returncode == 0


# --- red-pen catalog ---------------------------------------------------------------

def test_catalog_patterns_compile_and_expand():
    found = errors.explain("External ID not found in the system: sale.view_order_form")
    assert found[0][0] == "xmlid-not-found"
    assert "'sale.view_order_form'" in found[0][1]


def test_catalog_underscored_group():
    # exact message of odoo/modules/loading.py (17.0 - 19.0)
    found = errors.explain("WARNING db odoo.modules.loading: The models ['demo.thing'] have no "
                           "access rules in module demo_mod, consider adding some, like:")
    assert found[0][0] == "model-no-access-rules"
    assert "model_demo_thing" in found[0][2] and "demo_mod" in found[0][1]


def test_catalog_unknown_text():
    assert errors.explain("all good") == []


def test_pylint_fix_fallback():
    assert "--help-msg=weird-rule" in errors.pylint_fix("weird-rule")
