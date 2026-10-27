import sys

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
    write(hrepo, "addons/demo_mod/__manifest__.py",
          '{"name": "D", "version": "16.0.1.0.0", "license": "LGPL-3", "depends": ["base"],'
          ' "data": ["views/missing.xml"]}')
    result = run_static(hrepo)
    assert result.returncode == 1
    assert "is not 17.0.x.y.z" in result.stderr
    assert "'data' lists 'views/missing.xml', which does not exist" in result.stderr


def test_broken_xml_points_to_line(hrepo):
    write(hrepo, "addons/demo_mod/views/thing_views.xml", "<odoo>\n<record>\n</odoo>\n")
    result = run_static(hrepo)
    assert "views/thing_views.xml:3: XML is not well formed" in result.stderr


def test_access_csv_header(hrepo):
    write(hrepo, "addons/demo_mod/security/ir.model.access.csv", "id,name,model\n")
    assert "wrong ir.model.access.csv header" in run_static(hrepo).stderr


def test_debug_leftovers_project_check(hrepo):
    write(hrepo, "addons/demo_mod/models/thing.py", "import pdb\n")
    write(hrepo, "addons/demo_mod/static/src/x.js", "  debugger;\n")
    result = run_static(hrepo)
    assert "[no-debug-leftovers] debug statement: import pdb" in result.stderr
    assert "x.js:1: [no-debug-leftovers]" in result.stderr


def test_file_mode_checks_only_given_files(hrepo):
    bad = write(hrepo, "addons/demo_mod/models/bad.py", "def x(:\n")
    good = hrepo.path / "addons/demo_mod/models/thing.py"
    assert run_static(hrepo, str(good)).returncode == 0
    assert run_static(hrepo, str(bad)).returncode == 1


def test_modules_outside_scope_are_ignored(hrepo):
    write(hrepo, "addons/not_mine/__manifest__.py", "{broken")
    assert run_static(hrepo).returncode == 0


# --- red-pen catalog ---------------------------------------------------------------

def test_catalog_patterns_compile_and_expand():
    found = errors.explain("External ID not found in the system: sale.view_order_form")
    assert found[0][0] == "xmlid-not-found"
    assert "'sale.view_order_form'" in found[0][1]


def test_catalog_underscored_group():
    found = errors.explain("WARNING db odoo.modules.loading: The model demo.thing has no access "
                           "rules, consider adding one.")
    assert "model_demo_thing" in found[0][2]


def test_catalog_unknown_text():
    assert errors.explain("all good") == []


def test_pylint_fix_fallback():
    assert "--help-msg=weird-rule" in errors.pylint_fix("weird-rule")
