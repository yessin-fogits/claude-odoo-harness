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


def task_file(repo, task="T1"):
    return repo.path / "tasks" / f"{task}.json"


def edit_task_file(repo, change, task="T1"):
    data = json.loads(task_file(repo, task).read_text())
    change(data["features"])
    task_file(repo, task).write_text(json.dumps(data))


def notes(repo, task="T1"):
    return (repo.path / "tasks" / f"{task}.md").read_text()


def test_add_assigns_ids_and_minimal_format(hrepo):
    add_feature(hrepo)
    add_feature(hrepo, "User archives a demo thing", "e2e/test_T1_2_archive.py")
    feats = hrepo.features()
    assert [f["id"] for f in feats] == ["F-T1-1", "F-T1-2"]
    stored = json.loads(task_file(hrepo).read_text())
    assert stored["version"] == 2 and stored["task"] == "T1"
    assert set(stored["features"][0]) == {"id", "behavior", "verification", "state", "evidence"}
    assert feats[0]["state"] == "not_started" and feats[0]["evidence"] is None
    # the task's notes list its features
    assert "- [ ] F-T1-2 User archives a demo thing" in notes(hrepo).split("## Features")[1]


def test_add_requires_a_task(hrepo):
    result = hrepo.feature("add", "--behavior", "x", "--verify", "e2e: e2e/test_x.py")
    assert result.returncode != 0 and "--task" in result.stderr
    assert hrepo.features() == []


def test_add_requires_an_e2e_verification(hrepo):
    result = hrepo.feature("add", "--task", "T1", "--behavior", "x", "--verify", "unit: /demo_mod")
    assert result.returncode == 1
    assert "needs at least one 'e2e:" in result.stderr
    assert "WHY:" in result.stderr and "HOW TO FIX:" in result.stderr
    assert "e2e/test_T1_1_discount.py" in result.stderr
    assert hrepo.features() == []


def test_wip_is_one(hrepo):
    add_feature(hrepo)
    add_feature(hrepo, "Second", "e2e/test_T1_2_x.py")
    assert hrepo.feature("start", "F-T1-1").returncode == 0
    result = hrepo.feature("start", "F-T1-2")
    assert result.returncode == 1
    assert "F-T1-1 is in_progress" in result.stderr and "WIP = 1" in result.stderr
    assert [f["state"] for f in hrepo.features()] == ["in_progress", "not_started"]


def test_start_updates_the_task_notes(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    assert "- [ ] F-T1-1 User creates a demo thing (in progress)" in notes(hrepo)
    # PROGRESS.md is the whole project's: the harness does not write it
    assert "F-T1-1" not in (hrepo.path / "PROGRESS.md").read_text()


def test_block_records_reason_and_frees_wip(hrepo):
    add_feature(hrepo)
    add_feature(hrepo, "Second", "e2e/test_T1_2_x.py")
    hrepo.feature("start", "F-T1-1")
    result = hrepo.feature("block", "F-T1-1", "--reason", "waiting for the client's tax rules")
    assert result.returncode == 0
    text = notes(hrepo)
    assert "F-T1-1 blocked" in text.split("## Known issues")[1]
    assert "- [ ] F-T1-1 User creates a demo thing (blocked)" in text
    assert hrepo.feature("start", "F-T1-2").returncode == 0


def test_verify_refuses_feature_not_in_progress(hrepo):
    add_feature(hrepo)
    result = hrepo.feature("verify", "F-T1-1")
    assert result.returncode == 1
    assert "not in_progress" in result.stderr
    assert hrepo.calls() == []


def test_verify_success_sets_passing_with_evidence(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    thing = hrepo.path / "extra-addons/client/demo_mod/models/thing.py"
    thing.write_text(thing.read_text() + "\n# the feature's change\n")
    result = hrepo.feature("verify", "F-T1-1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[T1] F-T1-1 User creates a demo thing" in result.stdout
    feat = hrepo.features()[0]
    assert feat["state"] == "passing"
    assert feat["evidence"]["file"] == "harness/evidence/F-T1-1.json"
    evidence = json.loads((hrepo.path / feat["evidence"]["file"]).read_text())
    assert evidence["report"]["result"] == "pass"
    assert set(evidence["report"]["layers"]) == {"static", "runtime", "system"}
    assert evidence["report"]["layers"]["runtime"]["tests"] == 3
    text = notes(hrepo)
    assert "- [x] F-T1-1 User creates a demo thing (verified" in text
    assert "- [ ] F-T1-1" not in text
    # lint, odoo tests, e2e, then the fresh-DB install
    assert hrepo.services_run() == ["lint", "odoo", "e2e", "odoo"]
    assert hrepo.feature("check").returncode == 0


def test_verify_failure_keeps_in_progress_with_red_pen(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    result = hrepo.feature("verify", "F-T1-1", fake_odoo_log=FAILED_LOG, fake_odoo_rc=1)
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
    edit_task_file(hrepo, lambda feats: feats[0].update(state="passing"))
    result = hrepo.feature("check")
    assert result.returncode == 1
    assert "passing without evidence" in result.stderr


def test_forged_evidence_is_rejected(hrepo):
    add_feature(hrepo)
    edit_task_file(hrepo, lambda feats: feats[0].update(
        state="passing", evidence={"file": "harness/evidence/F-T1-1.json"}))
    result = hrepo.feature("check")
    assert result.returncode == 1
    assert "evidence file" in result.stderr


def test_changing_a_verified_feature_breaks_integrity(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    assert hrepo.feature("verify", "F-T1-1").returncode == 0
    edit_task_file(hrepo, lambda feats: feats[0].update(
        behavior="Something bigger than what was verified"))
    result = hrepo.feature("check")
    assert result.returncode == 1
    assert "changed after it was verified" in result.stderr


def test_reopen_passing_feature(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    hrepo.feature("verify", "F-T1-1")
    assert hrepo.feature("start", "F-T1-1").returncode == 1
    assert hrepo.feature("start", "F-T1-1", "--reopen").returncode == 0
    feat = hrepo.features()[0]
    assert feat["state"] == "in_progress" and feat["evidence"] is None


def test_invalid_json_gives_red_pen(hrepo):
    add_feature(hrepo)
    task_file(hrepo).write_text("{not json")
    result = hrepo.feature("status")
    assert result.returncode == 1
    assert "not valid JSON" in result.stderr and "git checkout tasks/T1.json" in result.stderr


def test_task_file_must_match_its_name(hrepo):
    add_feature(hrepo)
    data = json.loads(task_file(hrepo).read_text())
    task_file(hrepo, "T2").write_text(json.dumps(data))  # says task T1
    result = hrepo.feature("status")
    assert result.returncode == 1 and "tasks/T2.json is invalid" in result.stderr


def test_duplicate_ids_across_tasks_are_rejected(hrepo):
    add_feature(hrepo)
    data = json.loads(task_file(hrepo).read_text())
    task_file(hrepo, "T2").write_text(json.dumps({**data, "task": "T2"}))
    result = hrepo.feature("check")
    assert result.returncode == 1 and "F-T1-1: duplicate id" in result.stderr


def test_legacy_feature_list_asks_for_the_update(hrepo):
    (hrepo.path / "tasks" / ".gitkeep").unlink()
    (hrepo.path / "tasks").rmdir()
    (hrepo.path / "feature_list.json").write_text('{"version": 1, "features": []}\n')
    result = hrepo.feature("status")
    assert result.returncode == 1
    assert "feature_list.json" in result.stderr and "/odoo-harness:update" in result.stderr


def test_legacy_ids_still_load(hrepo):
    add_feature(hrepo)
    edit_task_file(hrepo, lambda feats: feats[0].update(id="F-001"))
    assert hrepo.feature("check").returncode == 0
    assert hrepo.feature("start", "F-001").returncode == 0


def test_status_points_to_next_action(hrepo):
    add_feature(hrepo)
    assert "Next: odoo-harness feature start F-T1-1" in hrepo.feature("status").stdout
    hrepo.feature("start", "F-T1-1")
    assert "odoo-harness feature verify F-T1-1" in hrepo.feature("status").stdout


def test_list_gives_the_features_and_those_in_progress_here(hrepo):
    add_feature(hrepo)
    hrepo.feature("start", "F-T1-1")
    view = json.loads(hrepo.feature("list").stdout)
    assert view["branch"] == "T1" and view["here"] == ["F-T1-1"]
    assert view["features"][0]["task"] == "T1"
