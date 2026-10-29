import json

from conftest import add_feature

FAILED_LOG = """\
2026-10-27 10:00:00,100 42 INFO harness_test odoo.modules.loading: loading demo_mod
2026-10-27 10:00:01,000 42 ERROR harness_test odoo.addons.demo_mod.tests.test_thing: FAIL: TestThing.test_create
Traceback (most recent call last):
  File "/mnt/extra-extra-addons/client/demo_mod/tests/test_thing.py", line 7, in test_create
    self.assertEqual(thing.name, "x")
AssertionError: 'y' != 'x'
2026-10-27 10:00:01,100 42 INFO harness_test odoo.tests.result: 1 failed, 0 error(s) of 3 tests when loading database 'harness_test'
"""


def test_add_assigns_ids_and_minimal_format(hrepo):
    add_feature(hrepo)
    add_feature(hrepo, "User archives a demo thing", "e2e/test_F002_archive.py")
    feats = hrepo.features()
    assert [f["id"] for f in feats] == ["F-001", "F-002"]
    assert set(feats[0]) == {"id", "behavior", "verification", "state", "evidence"}
    assert feats[0]["state"] == "not_started" and feats[0]["evidence"] is None


def test_add_requires_an_e2e_verification(hrepo):
    result = hrepo.feature("add", "--behavior", "x", "--verify", "unit: /demo_mod")
    assert result.returncode == 1
    assert "needs at least one 'e2e:" in result.stderr
    assert "WHY:" in result.stderr and "HOW TO FIX:" in result.stderr
    assert hrepo.features() == []


def test_wip_is_one(hrepo):
    add_feature(hrepo)
    add_feature(hrepo, "Second", "e2e/test_F002_x.py")
    assert hrepo.feature("start", "F-001").returncode == 0
    result = hrepo.feature("start", "F-002")
    assert result.returncode == 1
    assert "F-001 is in_progress" in result.stderr and "WIP = 1" in result.stderr
    assert [f["state"] for f in hrepo.features()] == ["in_progress", "not_started"]


def test_start_updates_progress(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-001")
    progress = (hrepo.path / "PROGRESS.md").read_text()
    in_progress = progress.split("## In progress")[1].split("## ")[0]
    assert "- [ ] F-001 User creates a demo thing" in in_progress


def test_block_records_reason_and_frees_wip(hrepo):
    add_feature(hrepo)
    add_feature(hrepo, "Second", "e2e/test_F002_x.py")
    hrepo.feature("start", "F-001")
    result = hrepo.feature("block", "F-001", "--reason", "waiting for the client's tax rules")
    assert result.returncode == 0
    progress = (hrepo.path / "PROGRESS.md").read_text()
    assert "F-001 blocked" in progress.split("## Known issues")[1]
    assert "- [ ] F-001" not in progress
    assert hrepo.feature("start", "F-002").returncode == 0


def test_verify_refuses_feature_not_in_progress(hrepo):
    add_feature(hrepo)
    result = hrepo.feature("verify", "F-001")
    assert result.returncode == 1
    assert "not in_progress" in result.stderr
    assert hrepo.calls() == []


def test_verify_success_sets_passing_with_evidence(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-001")
    thing = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + "\n# the feature's change\n")
    result = hrepo.feature("verify", "F-001")
    assert result.returncode == 0, result.stdout + result.stderr
    feat = hrepo.features()[0]
    assert feat["state"] == "passing"
    evidence = json.loads((hrepo.path / feat["evidence"]["file"]).read_text())
    assert evidence["report"]["result"] == "pass"
    assert set(evidence["report"]["layers"]) == {"static", "runtime", "system"}
    assert evidence["report"]["layers"]["runtime"]["tests"] == 3
    progress = (hrepo.path / "PROGRESS.md").read_text()
    assert "- [x] F-001" in progress.split("## Completed tasks")[1].split("## ")[0]
    assert "- [ ] F-001" not in progress
    # lint, odoo tests, e2e, then the fresh-DB install
    assert hrepo.services_run() == ["lint", "odoo", "e2e", "odoo"]
    assert hrepo.feature("check").returncode == 0


def test_verify_failure_keeps_in_progress_with_red_pen(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-001")
    result = hrepo.feature("verify", "F-001", fake_odoo_log=FAILED_LOG, fake_odoo_rc=1)
    assert result.returncode == 1
    assert "✗ [L2 runtime]" in result.stderr
    assert "The test TestThing.test_create failed" in result.stderr
    assert "HOW TO FIX:" in result.stderr
    assert "stays in_progress" in result.stderr
    feat = hrepo.features()[0]
    assert feat["state"] == "in_progress" and feat["evidence"] is None
    assert "e2e" not in hrepo.services_run()  # layers stop at the first failure


def test_hand_edited_passing_is_rejected(hrepo):
    add_feature(hrepo)
    data = json.loads((hrepo.path / "feature_list.json").read_text())
    data["features"][0]["state"] = "passing"
    (hrepo.path / "feature_list.json").write_text(json.dumps(data))
    result = hrepo.feature("check")
    assert result.returncode == 1
    assert "passing without evidence" in result.stderr


def test_forged_evidence_is_rejected(hrepo):
    add_feature(hrepo)
    data = json.loads((hrepo.path / "feature_list.json").read_text())
    data["features"][0]["state"] = "passing"
    data["features"][0]["evidence"] = {"file": "harness/evidence/F-001.json"}
    (hrepo.path / "feature_list.json").write_text(json.dumps(data))
    result = hrepo.feature("check")
    assert result.returncode == 1
    assert "evidence file" in result.stderr


def test_changing_a_verified_feature_breaks_integrity(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-001")
    assert hrepo.feature("verify", "F-001").returncode == 0
    data = json.loads((hrepo.path / "feature_list.json").read_text())
    data["features"][0]["behavior"] = "Something bigger than what was verified"
    (hrepo.path / "feature_list.json").write_text(json.dumps(data))
    result = hrepo.feature("check")
    assert result.returncode == 1
    assert "changed after it was verified" in result.stderr


def test_reopen_passing_feature(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-001")
    hrepo.feature("verify", "F-001")
    assert hrepo.feature("start", "F-001").returncode == 1
    assert hrepo.feature("start", "F-001", "--reopen").returncode == 0
    feat = hrepo.features()[0]
    assert feat["state"] == "in_progress" and feat["evidence"] is None


def test_invalid_json_gives_red_pen(hrepo):
    (hrepo.path / "feature_list.json").write_text("{not json")
    result = hrepo.feature("status")
    assert result.returncode == 1
    assert "not valid JSON" in result.stderr and "git checkout feature_list.json" in result.stderr


def test_status_points_to_next_action(hrepo):
    add_feature(hrepo)
    assert "Next: odoo-harness feature start F-001" in hrepo.feature("status").stdout
    hrepo.feature("start", "F-001")
    assert "odoo-harness feature verify F-001" in hrepo.feature("status").stdout
