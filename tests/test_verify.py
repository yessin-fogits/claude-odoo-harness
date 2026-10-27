import importlib.util
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, add_feature

HARNESS = ROOT / "template" / "harness"


def load(name):
    sys.path.insert(0, str(HARNESS))
    spec = importlib.util.spec_from_file_location(name, HARNESS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = load("verify")


# --- parsers ------------------------------------------------------------------

def test_parse_odoo_test_summary():
    log = ("x odoo.tests.result: 1 failed, 2 error(s) of 10 tests when loading database 'd'\n"
           "x odoo.tests.result: 0 failed, 0 error(s) of 5 tests when loading database 'd'\n")
    assert verify.parse_odoo_tests(log) == (15, 1, 2)
    assert verify.parse_odoo_tests("Ran 4 tests in 0.1s") == (4, 0, 0)
    assert verify.parse_odoo_tests("no summary") is None


def test_odoo_error_blocks_keep_tracebacks():
    log = ("2026-10-27 10:00:00,100 1 INFO db a: fine\n"
           "2026-10-27 10:00:00,200 1 ERROR db b: boom\n"
           "Traceback (most recent call last):\n"
           "  File x\n"
           "2026-10-27 10:00:00,300 1 INFO db c: fine\n")
    blocks = verify.odoo_error_blocks(log)
    assert len(blocks) == 1 and "Traceback" in blocks[0] and "fine" not in blocks[0]


def test_parse_pytest_summary():
    assert verify.parse_pytest("..F\n1 failed, 2 passed in 3.1s") == {
        "passed": 2, "failed": 1, "errors": 0}
    assert verify.parse_pytest("no tests ran in 0.01s")["passed"] == 0


@pytest.mark.parametrize("files,expected", [
    ({"addons/demo_mod/models/x.py"}, (False, ["demo_mod"], [])),
    ({"addons/demo_mod/models/x.py", "e2e/test_F001_x.py", "PROGRESS.md"},
     (False, ["demo_mod"], [])),
    ({"addons/a/x.py", "addons/b/y.py"}, (True, ["a", "b"], [])),
    ({"addons/a/x.py", "e2e/conftest.py"}, (True, ["a"], ["e2e/conftest.py"])),
    ({"addons/a/x.py", "docker-compose.yml"}, (True, ["a"], ["docker-compose.yml"])),
])
def test_cross_component(files, expected):
    assert verify.cross_component({"ADDONS_DIR": "addons"}, files) == expected


# --- layers, through the real script with a fake docker compose -------------------

def test_baseline_runs_all_layers_and_full_e2e(hrepo):
    result = hrepo.verify()
    assert result.returncode == 0, result.stderr
    assert "✓ verification passed" in result.stdout
    e2e_call = [c for c in hrepo.calls() if "e2e" in c and "pytest" in c][0]
    assert e2e_call[e2e_call.index("pytest") + 1] == "e2e"


def test_static_failure_stops_before_runtime(hrepo):
    (hrepo.path / "addons/demo_mod/models/thing.py").write_text("def broken(:\n")
    result = hrepo.verify()
    assert result.returncode == 1
    assert "✗ [L1 static] addons/demo_mod/models/thing.py:1: Python syntax error" in result.stderr
    assert "odoo" not in hrepo.services_run()


def test_pylint_messages_fail_layer_one_with_fix(hrepo):
    out = "addons/demo_mod/models/thing.py:9: [W8116(print-used)] Print used.\n"
    result = hrepo.verify(fake_pylint_out=out)
    assert result.returncode == 1
    assert "✗ [L1 lint] addons/demo_mod/models/thing.py:9: print-used" in result.stderr
    assert "_logger" in result.stderr


def test_zero_tests_is_a_failure(hrepo):
    log = "x odoo.tests.result: 0 failed, 0 error(s) of 0 tests when loading database 'd'\n"
    result = hrepo.verify(fake_odoo_log=log)
    assert result.returncode == 1
    assert "no Odoo test ran" in result.stderr


def test_unknown_error_asks_to_extend_the_catalog(hrepo):
    log = ("2026-10-27 10:00:00,200 1 ERROR db x: something nobody has seen\n"
           "x odoo.tests.result: 0 failed, 0 error(s) of 3 tests when loading database 'd'\n")
    result = hrepo.verify(fake_odoo_log=log)
    assert result.returncode == 1
    assert "something nobody has seen" in result.stderr
    assert "add a pattern for it in harness/errors_project.py" in result.stderr


def test_e2e_timeout_is_explained(hrepo):
    out = ("F\nFAILED e2e/test_smoke.py::test_web_client_loads - playwright._impl._errors."
           "TimeoutError: Locator.click: Timeout 30000ms exceeded.\n1 failed in 31.0s\n")
    result = hrepo.verify(fake_e2e_out=out, fake_e2e_rc=1)
    assert result.returncode == 1
    assert "✗ [L3 e2e] e2e/test_smoke.py::test_web_client_loads failed" in result.stderr
    assert "Open the trace" in result.stderr


def test_e2e_running_no_test_fails(hrepo):
    result = hrepo.verify(fake_e2e_out="no tests ran in 0.01s\n", fake_e2e_rc=5)
    assert result.returncode == 1


def test_server_log_errors_fail_system_layer(hrepo):
    log = "odoo-1  | 2026-10-27 10:00:00,200 1 ERROR db odoo.http: Exception during request\n"
    result = hrepo.verify(fake_server_log=log)
    assert result.returncode == 1
    assert "the server logged errors during the e2e run" in result.stderr


def test_feature_runs_only_its_e2e_when_single_module(hrepo):
    add_feature(hrepo)
    hrepo.commit("add feature")
    hrepo.feature("start", "F-001")
    (hrepo.path / "addons/demo_mod/models/thing.py").write_text(
        (hrepo.path / "addons/demo_mod/models/thing.py").read_text() + "\n")
    assert hrepo.feature("verify", "F-001").returncode == 0
    e2e_call = [c for c in hrepo.calls() if "pytest" in c][0]
    assert e2e_call[e2e_call.index("pytest") + 1] == "e2e/test_F001_thing.py"


def test_cross_module_feature_runs_full_e2e(hrepo):
    add_feature(hrepo)
    hrepo.commit("add feature")
    hrepo.feature("start", "F-001")
    other = hrepo.path / "addons/other_mod"
    shutil.copytree(hrepo.path / "addons/demo_mod", other)
    thing = hrepo.path / "addons/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + "\n")
    result = hrepo.feature("verify", "F-001")
    assert result.returncode == 0, result.stderr
    assert "full e2e suite required" in result.stdout
    e2e_call = [c for c in hrepo.calls() if "pytest" in c][0]
    assert e2e_call[e2e_call.index("pytest") + 1] == "e2e"


def test_missing_feature_e2e_file_is_reported(hrepo):
    add_feature(hrepo)
    (hrepo.path / "e2e/test_F001_thing.py").unlink()
    hrepo.commit("add feature")
    hrepo.feature("start", "F-001")
    result = hrepo.feature("verify", "F-001")
    assert result.returncode == 1
    assert "e2e test file missing: e2e/test_F001_thing.py" in result.stderr


def test_verify_sh_wrapper(hrepo):
    result = hrepo.run("harness/verify.sh", "--only", "1")
    assert result.returncode == 0, result.stderr


# --- pylint-odoo config, against the real linter when available ----------------------

@pytest.mark.skipif(shutil.which("pylint") is None, reason="pylint-odoo not installed")
def test_pylintrc_is_valid_and_finds_odoo_issues(hrepo):
    thing = hrepo.path / "addons/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + "\n    def act(self):\n        print('x')\n")
    result = subprocess.run(
        ["pylint", "--rcfile=.pylintrc", verify.PYLINT_DISABLE,
         f"--msg-template={verify.PYLINT_TEMPLATE}", "addons/demo_mod"],
        cwd=hrepo.path, capture_output=True, text=True)
    messages = [m.group("symbol") for m in map(verify.PYLINT_RE.match, result.stdout.splitlines())
                if m]
    assert "config-parse-error" not in result.stdout
    assert messages == ["print-used"], result.stdout


ODOO20_FAILED_LOG = """\
2026-10-27 11:10:24,300 1 ERROR harness_test odoo.addons.demo_mod.tests.test_thing: FAIL: TestThing.test_create
Traceback (most recent call last):
  File "/mnt/extra-addons/demo_mod/tests/test_thing.py", line 7, in test_create
    self.assertEqual(thing.name, "x")
AssertionError: 'X' != 'x'
2026-10-27 11:10:24,406 1 ERROR harness_test odoo.tests.result: 1 failed, 0 error(s) of 1 tests when loading database 'harness_test'
"""


def test_failure_shows_the_assertion_once(hrepo):
    """Real Odoo 20 output: one red pen, with the assertion text, no summary duplicate."""
    result = hrepo.verify(fake_odoo_log=ODOO20_FAILED_LOG, fake_odoo_rc=1)
    assert result.returncode == 1
    assert result.stderr.count("✗ [L2 runtime]") == 1
    assert "AssertionError: 'X' != 'x'" in result.stderr
    assert "No catalog entry" not in result.stderr


def test_cross_component_names_shared_files(hrepo):
    add_feature(hrepo)
    hrepo.commit("add feature")
    hrepo.feature("start", "F-001")
    (hrepo.path / "notes.log").write_text("x")
    result = hrepo.feature("verify", "F-001")
    assert "cross-component change (shared files notes.log)" in result.stdout
