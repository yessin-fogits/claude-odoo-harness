"""pytest plugin of the harness: the `guide` fixture of the e2e tests.

Loaded by odoo-harness verify and odoo-harness guide (`-p harness_guide`, with this folder on
PYTHONPATH). A test marks each step a user sees with a caption, in French:

    def test_salesman_applies_discount(odoo_page, unique, guide):
        page = odoo_page
        page.goto("/web#action=sale_discount.sale_discount_action")
        guide.step("Ouvrir Ventes > Remises")
        page.get_by_role("button", name="New").click()
        guide.step("Créer une remise et saisir le taux", highlight=page.get_by_label("Rate"))

In a verify run `guide.step()` does nothing. When odoo-harness guide replays the test for a
user guide (HARNESS_GUIDE_DIR set), each step takes a screenshot, outlines the `highlight`
element, and records the caption in <HARNESS_GUIDE_DIR>/<test>/steps.json. A test without
any step gets one screenshot of its final screen.
"""

import json
import os
import re
from pathlib import Path

import pytest

VIEWPORT = {"width": 1440, "height": 900}
HIGHLIGHT_ON = """el => {
    el.scrollIntoView({block: 'center', inline: 'nearest'});
    el.dataset.harnessGuideOutline = el.style.outline;
    el.dataset.harnessGuideOffset = el.style.outlineOffset;
    el.style.outline = '3px solid #e53935';
    el.style.outlineOffset = '2px';
}"""
HIGHLIGHT_OFF = """el => {
    el.style.outline = el.dataset.harnessGuideOutline || '';
    el.style.outlineOffset = el.dataset.harnessGuideOffset || '';
}"""
FINAL_CAPTION = "Écran à la fin du scénario"


def test_dir_name(nodeid):
    """e2e/test_F001_discount.py::test_apply -> test_F001_discount__test_apply"""
    path, _, name = nodeid.partition("::")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{Path(path).stem}__{name}").strip("_")


class Guide:
    def __init__(self, page, out_dir, nodeid):
        self.page, self.out_dir, self.nodeid = page, out_dir, nodeid
        self.steps = []
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            page.set_viewport_size(VIEWPORT)

    def step(self, caption, highlight=None):
        """Screenshot of the current screen for the user guide; no-op outside guide mode."""
        if not self.out_dir:
            return
        try:
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:  # noqa: BLE001 - Odoo keeps a long-polling connection open
            pass
        target = highlight.first if highlight is not None else None
        if target is not None:
            target.evaluate(HIGHLIGHT_ON)
        image = f"{len(self.steps) + 1:02d}.png"
        self.page.screenshot(path=str(self.out_dir / image))
        if target is not None:
            target.evaluate(HIGHLIGHT_OFF)
        self.steps.append({"caption": caption, "image": image, "url": self.page.url})

    def finish(self, passed):
        if not self.out_dir or not passed:
            return
        if not self.steps:
            self.step(FINAL_CAPTION)
        (self.out_dir / "steps.json").write_text(json.dumps(
            {"test": self.nodeid, "steps": self.steps}, indent=2, ensure_ascii=False) + "\n")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item.harness_guide_passed = report.passed


@pytest.fixture
def guide(request, page):
    root = os.environ.get("HARNESS_GUIDE_DIR")
    out_dir = Path(root) / test_dir_name(request.node.nodeid) if root else None
    recorder = Guide(page, out_dir, request.node.nodeid)
    yield recorder
    recorder.finish(getattr(request.node, "harness_guide_passed", False))


@pytest.fixture(autouse=True)
def _harness_guide_final_screen(request):
    """In guide mode, tests that do not ask for `guide` still get their final screen."""
    if os.environ.get("HARNESS_GUIDE_DIR") and "page" in request.fixturenames:
        request.getfixturevalue("guide")
    yield
