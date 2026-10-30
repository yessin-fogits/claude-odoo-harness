"""User guide of a completed task: the gate, the e2e replay, the PDF and stale guides."""

import importlib.util
import json
import sys

import pytest

from conftest import CLI, ROOT
from test_tasks import add_task_feature, change_module, finish, trepo  # noqa: F401

PLUGIN = ROOT / "engine" / "e2e_plugins" / "harness_guide.py"


def guide(repo, *args, **fake):
    return repo.run(CLI, "guide", *args, **fake)


def content_path(repo, task="T2003"):
    return repo.path / ".harness" / "guide" / task / "content.json"


def fill_content(repo, task="T2003"):
    path = content_path(repo, task)
    content = json.loads(path.read_text())
    content["title"] = f"{task} : Remises sur les devis"
    content["summary"] = "Les commerciaux appliquent une **remise** sur un devis."
    for feat in content["features"].values():
        feat["summary"] = "Créer une remise."
        feat["technical"] = "- Modèle `sale.discount`\n- Vue `sale_discount.form`"
        feat["steps"] = {key: f"Étape <{key}>" for key in feat["steps"]}
    path.write_text(json.dumps(content, ensure_ascii=False))


@pytest.fixture
def done(trepo):  # noqa: F811
    """Task T2003 with two features, both passing and committed."""
    add_task_feature(trepo, "T2003", 1, "Salesperson creates a discount")
    add_task_feature(trepo, "T2003", 2, "Salesperson applies the discount")
    trepo.commit("features")
    for fid in ("F-001", "F-002"):
        assert trepo.feature("start", fid).returncode == 0
        finish(trepo, fid)
    return trepo


# --- the "completed only" gate -------------------------------------------------

def test_unknown_task_is_refused(done):
    result = guide(done, "capture", "T9999")
    assert result.returncode == 1
    assert "no feature belongs to task T9999" in result.stderr and "T2003" in result.stderr


def test_task_with_a_feature_not_passing_is_refused(trepo):  # noqa: F811
    add_task_feature(trepo, "T2003", 1)
    add_task_feature(trepo, "T2003", 2)
    trepo.commit("features")
    trepo.feature("start", "F-001")
    finish(trepo, "F-001")
    before = len(trepo.calls())
    result = guide(trepo, "capture", "T2003")
    assert result.returncode == 1
    assert "task T2003 is not completed: F-002 (not_started)" in result.stderr
    assert "WHY:" in result.stderr and "HOW TO FIX:" in result.stderr
    assert len(trepo.calls()) == before


def test_feature_verified_but_not_committed_is_refused(trepo):  # noqa: F811
    add_task_feature(trepo, "T2003", 1, "Salesperson creates a discount")
    trepo.commit("features")
    trepo.feature("start", "F-001")
    change_module(trepo, "F-001")
    assert trepo.feature("verify", "F-001").returncode == 0
    trepo.commit("wip")
    result = guide(trepo, "capture", "T2003")
    assert result.returncode == 1
    assert "no commit '[T2003] F-001 Salesperson creates a discount'" in result.stderr


def test_uncommitted_module_changes_are_refused(done):
    change_module(done, "later")
    result = guide(done, "capture", "T2003")
    assert result.returncode == 1
    assert "uncommitted changes: extra-addons/client/demo_mod/models/thing.py" in result.stderr


def test_renamed_task_keeps_its_commits_under_the_old_name(done):
    assert done.feature("rename-task", "T2003", "T2004").returncode == 0
    done.commit("[T2004] Rename task T2003")
    assert guide(done, "capture", "T2004").returncode == 0


def test_rename_refused_while_the_task_has_a_guide(done):
    (done.path / "docs/guides").mkdir(parents=True, exist_ok=True)
    (done.path / "docs/guides/T2003.pdf").write_bytes(b"%PDF")
    result = done.feature("rename-task", "T2003", "T2004")
    assert result.returncode == 1
    assert "/odoo-harness:guide T2004" in result.stderr


# --- capture -------------------------------------------------------------------

def test_capture_replays_each_feature_with_the_guide_plugin(done):
    result = guide(done, "capture", "T2003")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [c for c in done.calls() if "pytest" in c and any(
        a.startswith("--env=HARNESS_GUIDE_DIR=") for a in c)]
    assert len(calls) == 2
    assert "e2e/test_F001_x.py" in calls[0] and "e2e/test_F002_x.py" in calls[1]
    assert "--env=PYTHONPATH=/opt/odoo-harness/e2e_plugins" in calls[0]
    assert calls[0][calls[0].index("-p") + 1] == "harness_guide"
    manifest = json.loads((done.path / ".harness/guide/T2003/steps.json").read_text())
    assert [f["id"] for f in manifest["features"]] == ["F-001", "F-002"]
    steps = manifest["features"][0]["tests"][0]["steps"]
    assert [s["caption"] for s in steps] == ["Ouvrir le menu", "Enregistrer"]
    assert steps[0]["key"] == "F-001/test_F001_x__test_x/01"
    assert (done.path / steps[0]["image"]).is_file()
    content = json.loads(content_path(done).read_text())
    assert content["features"]["F-001"]["steps"]["F-001/test_F001_x__test_x/02"] == "À RÉDIGER"
    assert "odoo-harness guide build T2003" in result.stdout


def test_capture_keeps_the_text_already_written(done):
    guide(done, "capture", "T2003")
    fill_content(done)
    assert guide(done, "capture", "T2003").returncode == 0
    content = json.loads(content_path(done).read_text())
    assert content["title"] == "T2003 : Remises sur les devis"


def test_a_regressed_feature_stops_the_capture(done):
    result = guide(done, "capture", "T2003", fake_e2e_out="1 failed in 2s\n", fake_e2e_rc=1)
    assert result.returncode == 1
    assert "F-001 regressed since it was verified" in result.stderr
    assert "odoo-harness feature start F-001 --reopen" in result.stderr


# --- build ---------------------------------------------------------------------

def test_build_refuses_text_still_to_write(done):
    guide(done, "capture", "T2003")
    result = guide(done, "build", "T2003")
    assert result.returncode == 1
    assert "field(s) still to write: title, summary" in result.stderr


def test_build_refuses_without_capture(done):
    result = guide(done, "build", "T2003")
    assert result.returncode == 1 and "odoo-harness guide capture T2003" in result.stderr


def test_build_writes_the_pdf_and_records_it(done):
    guide(done, "capture", "T2003")
    fill_content(done)
    result = guide(done, "build", "T2003")
    assert result.returncode == 0, result.stdout + result.stderr
    pdf = done.path / "docs" / "guides" / "T2003.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
    page = (done.path / ".harness/guide/T2003/guide.html").read_text()
    assert "<html lang='fr'>" in page and "<b>remise</b>" in page
    assert "<code>sale.discount</code>" in page and "Étape &lt;F-001/" in page
    assert "src='" in page and "/test_F001_x__test_x/01.png'" in page
    assert "Détails techniques" in page and "<code>demo_mod</code>" in page
    index = json.loads((done.path / "docs/guides/guides.json").read_text())
    assert index["T2003"]["pdf"] == "docs/guides/T2003.pdf"
    assert set(index["T2003"]["features"]) == {"F-001", "F-002"}
    assert "[T2003] Guide utilisateur" in result.stdout


def test_build_reports_a_pdf_failure(done):
    guide(done, "capture", "T2003")
    fill_content(done)
    result = guide(done, "build", "T2003", fake_pdf_rc=1)
    assert result.returncode == 1 and "the PDF could not be rendered" in result.stderr
    assert not (done.path / "docs/guides/T2003.pdf").exists()


# --- stale guides --------------------------------------------------------------

def test_check_flags_a_guide_whose_feature_was_reopened(done):
    guide(done, "capture", "T2003")
    fill_content(done)
    guide(done, "build", "T2003")
    done.commit("[T2003] Guide utilisateur")
    result = guide(done, "check")
    assert result.returncode == 0 and "✓ T2003: docs/guides/T2003.pdf up to date" in result.stdout
    assert done.feature("start", "F-002", "--reopen").returncode == 0
    result = guide(done, "check")
    assert result.returncode == 1
    assert "✗ T2003: stale (F-002 is in_progress)" in result.stdout and ":guide T2003" in result.stdout


def test_check_without_guides(done):
    result = guide(done, "check")
    assert result.returncode == 0 and "no user guide yet" in result.stdout


# --- verify loads the plugin ---------------------------------------------------

def test_verify_gives_e2e_tests_the_guide_fixture(done):
    e2e = [c for c in done.calls() if "pytest" in c][0]
    assert "--env=PYTHONPATH=/opt/odoo-harness/e2e_plugins" in e2e
    assert e2e[e2e.index("-p") + 1] == "harness_guide"


# --- the pytest plugin ---------------------------------------------------------

def load_plugin():
    spec = importlib.util.spec_from_file_location("harness_guide", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLocator:
    def __init__(self):
        self.calls = []

    @property
    def first(self):
        return self

    def evaluate(self, script):
        self.calls.append(script)


class FakePage:
    url = "http://odoo:8069/odoo/action-1"

    def __init__(self):
        self.shots, self.viewport = [], None

    def set_viewport_size(self, size):
        self.viewport = size

    def wait_for_load_state(self, *_args, **_kw):
        raise TimeoutError("long polling")

    def screenshot(self, path):
        self.shots.append(path)
        open(path, "wb").close()


def test_plugin_step_is_a_no_op_outside_guide_mode():
    plugin = load_plugin()
    page = FakePage()
    recorder = plugin.Guide(page, None, "e2e/test_F001_x.py::test_x")
    recorder.step("Ouvrir le menu")
    recorder.finish(True)
    assert page.shots == [] and page.viewport is None


def test_plugin_records_steps_and_highlights(tmp_path):
    plugin = load_plugin()
    page, button = FakePage(), FakeLocator()
    out = tmp_path / plugin.test_dir_name("e2e/test_F001_x.py::test_x[chromium]")
    assert out.name == "test_F001_x__test_x_chromium"
    recorder = plugin.Guide(page, out, "e2e/test_F001_x.py::test_x")
    recorder.step("Ouvrir le menu")
    recorder.step("Cliquer sur Nouveau", highlight=button)
    recorder.finish(True)
    assert page.viewport == plugin.VIEWPORT
    assert len(button.calls) == 2 and "outline" in button.calls[0]
    steps = json.loads((out / "steps.json").read_text())["steps"]
    assert [s["image"] for s in steps] == ["01.png", "02.png"]
    assert steps[1]["caption"] == "Cliquer sur Nouveau"


def test_plugin_takes_the_final_screen_of_a_test_without_steps(tmp_path):
    plugin = load_plugin()
    page = FakePage()
    recorder = plugin.Guide(page, tmp_path / "t", "e2e/test_F001_x.py::test_x")
    recorder.finish(True)
    steps = json.loads((tmp_path / "t" / "steps.json").read_text())["steps"]
    assert [s["caption"] for s in steps] == [plugin.FINAL_CAPTION]


def test_plugin_writes_nothing_for_a_failed_test(tmp_path):
    plugin = load_plugin()
    recorder = plugin.Guide(FakePage(), tmp_path / "t", "e2e/test_F001_x.py::test_x")
    recorder.step("Ouvrir le menu")
    recorder.finish(False)
    assert not (tmp_path / "t" / "steps.json").exists()
