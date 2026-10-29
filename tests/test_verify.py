import importlib.util
import shutil
import subprocess
import sys

import pytest

from conftest import CLI, ODOO_VERSION, ROOT, add_feature

HARNESS = ROOT / "engine"


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


MOD = "extra-addons/client/demo_mod"
OTHER = "extra-addons/client/other_mod"


@pytest.mark.parametrize("files,expected", [
    ({f"{MOD}/models/x.py"}, (False, ["demo_mod"], [])),
    ({f"{MOD}/models/x.py", "e2e/test_F001_x.py", "PROGRESS.md"}, (False, ["demo_mod"], [])),
    ({f"{MOD}/x.py", f"{OTHER}/y.py"}, (True, ["demo_mod", "other_mod"], [])),
    ({f"{MOD}/x.py", "e2e/conftest.py"}, (True, ["demo_mod"], ["e2e/conftest.py"])),
    ({f"{MOD}/x.py", "Dockerfile"}, (True, ["demo_mod"], ["Dockerfile"])),
    ({f"{MOD}/x.py", "extra-addons/oca/web_x/models.py"},
     (True, ["demo_mod"], ["extra-addons/oca/web_x/models.py"])),
])
def test_cross_component(hrepo, monkeypatch, files, expected):
    (hrepo.path / OTHER).mkdir()
    (hrepo.path / OTHER / "__manifest__.py").write_text("{'name': 'o', 'depends': ['demo_mod']}")
    monkeypatch.setattr(verify.hlib, "REPO_ROOT", hrepo.path)
    env = {"CUSTOM_ADDONS": "extra-addons/client", "THIRD_PARTY_ADDONS": "extra-addons/oca"}
    assert verify.cross_component(env, files) == expected
    assert verify.hlib.dependents(env, ["demo_mod"]) == ["other_mod"]
    assert verify.hlib.dependents(env, ["other_mod"]) == []


# --- layers, through the real script with a fake docker compose -------------------

def test_baseline_runs_all_layers_and_full_e2e(hrepo):
    result = hrepo.verify()
    assert result.returncode == 0, result.stderr
    assert "✓ verification passed" in result.stdout
    e2e_call = [c for c in hrepo.calls() if "e2e" in c and "pytest" in c][0]
    assert e2e_call[e2e_call.index("pytest") + 1] == "e2e"


def test_static_failure_stops_before_runtime(hrepo):
    (hrepo.path / "extra-addons/client/demo_mod/models/thing.py").write_text("def broken(:\n")
    result = hrepo.verify()
    assert result.returncode == 1
    assert "✗ [L1 static] extra-addons/client/demo_mod/models/thing.py:1: Python syntax error" in result.stderr
    assert "odoo" not in hrepo.services_run()


def touch(hrepo, rel=f"{MOD}/models/thing.py"):
    path = hrepo.path / rel
    path.write_text(path.read_text() + "\n# changed\n")


def test_pylint_messages_fail_layer_one_with_fix(hrepo):
    touch(hrepo)
    out = "extra-addons/client/demo_mod/models/thing.py:9: [W8116(print-used)] Print used.\n"
    result = hrepo.verify(fake_pylint_out=out)
    assert result.returncode == 1
    assert "✗ [L1 lint] extra-addons/client/demo_mod/models/thing.py:9: print-used" in result.stderr
    assert "_logger" in result.stderr


ZERO_TESTS = "x odoo.tests.result: 0 failed, 0 error(s) of 0 tests when loading database 'd'\n"


def test_zero_tests_is_a_failure_for_a_feature(hrepo):
    result = hrepo.verify("--tags", "/demo_mod:TestThing", fake_odoo_log=ZERO_TESTS)
    assert result.returncode == 1
    assert "no Odoo test ran" in result.stderr


def test_baseline_of_modules_without_tests_passes(hrepo):
    """Legacy projects often have no tests: the baseline installs and updates every module."""
    result = hrepo.verify(fake_odoo_log=ZERO_TESTS)
    assert result.returncode == 0, result.stderr
    assert "no Odoo test exists yet" in result.stdout


def test_static_checks_only_cover_changed_modules(hrepo):
    """Debt in modules this branch does not touch does not block; --all reports it."""
    legacy = hrepo.path / "extra-addons/client/legacy_mod"
    legacy.mkdir()
    (legacy / "__manifest__.py").write_text("{'name': 'legacy', 'version': '1.0', 'depends': []}")
    (legacy / "__init__.py").write_text("import pdb\n")
    hrepo.commit("legacy module")
    result = hrepo.verify("--only", "1")
    assert result.returncode == 0, result.stderr
    assert "no custom module changed" in result.stdout
    debt = hrepo.run(CLI, "static", "--all")
    assert debt.returncode == 1 and "legacy_mod/__init__.py:1" in debt.stderr
    touch(hrepo, "extra-addons/client/legacy_mod/__init__.py")
    result = hrepo.verify("--only", "1")
    assert result.returncode == 1 and "no-debug-leftovers" in result.stderr


def test_feature_tests_modules_that_depend_on_the_change(hrepo):
    other = hrepo.path / OTHER
    other.mkdir()
    (other / "__manifest__.py").write_text("{'name': 'o', 'depends': ['demo_mod']}")
    hrepo.commit("other module")
    add_feature(hrepo)
    hrepo.feature("start", "F-001")
    touch(hrepo)
    result = hrepo.feature("verify", "F-001")
    assert result.returncode == 0, result.stderr
    odoo = [c for c in hrepo.calls() if "--test-tags" in c][0]
    assert odoo[odoo.index("-u") + 1] == "demo_mod,other_mod"
    assert odoo[odoo.index("--test-tags") + 1] == "/demo_mod:TestThing,/demo_mod,/other_mod"
    assert "modules depending on the change are tested too: other_mod" in result.stdout


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
    (hrepo.path / "extra-addons/client/demo_mod/models/thing.py").write_text(
        (hrepo.path / "extra-addons/client/demo_mod/models/thing.py").read_text() + "\n")
    assert hrepo.feature("verify", "F-001").returncode == 0
    e2e_call = [c for c in hrepo.calls() if "pytest" in c][0]
    assert e2e_call[e2e_call.index("pytest") + 1] == "e2e/test_F001_thing.py"


def test_cross_module_feature_runs_full_e2e(hrepo):
    add_feature(hrepo)
    hrepo.commit("add feature")
    hrepo.feature("start", "F-001")
    other = hrepo.path / "extra-addons/client/other_mod"
    shutil.copytree(hrepo.path / "extra-addons/client/demo_mod", other)
    thing = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
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
    result = hrepo.run(CLI, "verify", "--only", "1")
    assert result.returncode == 0, result.stderr


# --- pylint-odoo config, against the real linter when available ----------------------

@pytest.mark.skipif(shutil.which("pylint") is None, reason="pylint-odoo not installed")
def test_pylintrc_is_valid_and_finds_odoo_issues(hrepo):
    thing = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + "\n    def act(self):\n        print('x')\n")
    result = subprocess.run(
        ["pylint", "--rcfile=.pylintrc", verify.PYLINT_DISABLE,
         f"--msg-template={verify.PYLINT_TEMPLATE}", "extra-addons/client/demo_mod"],
        cwd=hrepo.path, capture_output=True, text=True)
    messages = [m.group("symbol") for m in map(verify.PYLINT_RE.match, result.stdout.splitlines())
                if m]
    assert "config-parse-error" not in result.stdout
    assert messages == ["print-used"], result.stdout


ODOO20_FAILED_LOG = """\
2026-10-27 11:10:24,300 1 ERROR harness_test odoo.addons.demo_mod.tests.test_thing: FAIL: TestThing.test_create
Traceback (most recent call last):
  File "/mnt/extra-extra-addons/client/demo_mod/tests/test_thing.py", line 7, in test_create
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


ODOO17_FAILED_LOG = """\
2026-10-27 11:28:16,223 1 ERROR harness_test odoo.addons.demo_mod.tests.test_thing: FAIL: TestThing.test_create
Traceback (most recent call last):
  File "/mnt/extra-extra-addons/client/demo_mod/tests/test_thing.py", line 7, in test_create
    self.assertEqual(thing.name, "x")
AssertionError: 'X' != 'x'
2026-10-27 11:28:16,248 1 ERROR harness_test odoo.modules.loading: Module demo_mod: 1 failures, 0 errors of 1 tests
2026-10-27 11:28:16,570 1 ERROR harness_test odoo.modules.loading: At least one test failed when loading the modules.
2026-10-27 11:28:16,600 1 INFO harness_test odoo.tests.result: 1 failed, 0 error(s) of 1 tests when loading database 'harness_test'
"""


def test_odoo17_summary_records_are_not_separate_errors(hrepo):
    """Real Odoo 17 output (odoo-e2e CI): one red pen with the assertion."""
    result = hrepo.verify(fake_odoo_log=ODOO17_FAILED_LOG, fake_odoo_rc=1)
    assert result.returncode == 1
    assert result.stderr.count("✗ [L2 runtime]") == 1
    assert "AssertionError: 'X' != 'x'" in result.stderr
    assert "No catalog entry" not in result.stderr


def test_older_findings_in_a_touched_module_are_debt_not_blockers(hrepo):
    """Touching a module does not make its whole history the feature's problem."""
    thing = hrepo.path / f"{MOD}/models/thing.py"
    thing.write_text(thing.read_text() + "\nimport pdb  # left by someone, long ago\n")
    hrepo.commit("legacy debug leftover")
    old_line = len(thing.read_text().splitlines())
    thing.write_text("# a new comment at the top\n" + thing.read_text())
    lint = (f"{MOD}/models/thing.py:{old_line + 1}: [W8116(print-used)] Print used.\n"
            f"{MOD}/models/thing.py:1: [C8107(translation-required)] needs translation.\n")
    result = hrepo.verify("--only", "1", fake_pylint_out=lint)
    assert result.returncode == 1
    assert "translation-required" in result.stderr  # on a changed line: blocks
    assert "print-used" not in result.stderr and "no-debug-leftovers" not in result.stderr
    assert "older finding(s) on lines this branch did not change" in result.stdout
    result = hrepo.verify("--only", "1", fake_pylint_out=lint.splitlines()[0] + "\n")
    assert result.returncode == 0, result.stderr
    # the hooks' command line follows the same rule; --all still lists everything
    assert hrepo.run(CLI, "static").returncode == 0
    assert hrepo.run(CLI, "static", "--all").returncode == 1
    thing.write_text(thing.read_text() + "breakpoint()\n")
    result = hrepo.run(CLI, "static")
    assert result.returncode == 1 and "no-debug-leftovers" in result.stderr


def test_project_rcfile_and_odoo_version_are_passed_to_pylint(hrepo):
    (hrepo.path / ".pylintrc-mandatory").write_text("[ODOOLINT]\nvalid-odoo-versions=11.0\n")
    hrepo.commit("project lint config")
    (hrepo.path / f"{MOD}/models/thing.py").write_text(
        (hrepo.path / f"{MOD}/models/thing.py").read_text() + "\n# x\n")
    hrepo.verify("--only", "1")
    lint = [c for c in hrepo.calls() if "pylint" in c][0]
    assert "--rcfile=.pylintrc-mandatory" in lint
    assert f"--valid-odoo-versions={ODOO_VERSION}" in lint
    assert any("unknown-option-value" in a for a in lint)
    debt = hrepo.run(CLI, "static", "--all")
    assert "lint config validates Odoo 11.0" in debt.stderr
