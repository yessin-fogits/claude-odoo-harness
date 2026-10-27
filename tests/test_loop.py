import json
import subprocess
import sys

import pytest

from conftest import TESTS, add_feature


@pytest.fixture
def loop_repo(hrepo, tmp_path):
    hrepo.git("config", "user.name", "loop")
    hrepo.git("config", "user.email", "loop@example.com")
    hrepo.env.update({
        "HARNESS_AGENT": f"{sys.executable} {TESTS / 'fake_claude.py'}",
        "HARNESS_LOOP_SKIP_HEALTH": "1",
        "FAKE_AGENT_CALLS": str(tmp_path / "agent_calls.jsonl"),
    })
    hrepo.agent_calls = tmp_path / "agent_calls.jsonl"
    return hrepo


def loop(repo, *args, **fake):
    return repo.run(sys.executable, "harness/loop.py", "run", *args, **fake)


def with_feature(repo, *behaviors):
    for i, behavior in enumerate(behaviors or ["User creates a demo thing"], start=1):
        add_feature(repo, behavior, f"e2e/test_F{i:03d}_x.py")
    repo.commit("features")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo.path, capture_output=True, text=True).stdout


def agent_prompts(repo):
    calls = [json.loads(line) for line in repo.agent_calls.read_text().splitlines()]
    return [c[c.index("-p") + 1] for c in calls if "--agent" not in c]


def test_feature_verified_and_committed(loop_repo):
    with_feature(loop_repo)
    result = loop(loop_repo, fake_maker="fix")
    assert result.returncode == 0, result.stdout + result.stderr
    assert loop_repo.features()[0]["state"] == "passing"
    assert "feat(F-001): User creates a demo thing" in git(loop_repo, "log", "-1", "--format=%s")
    assert git(loop_repo, "status", "--porcelain").strip() == ""
    summary = json.loads((loop_repo.path / ".harness/loop/last.json").read_text())
    assert summary["passing"] == ["F-001"] and summary["blocked"] == []


def test_retry_gets_the_red_pen_feedback(loop_repo):
    with_feature(loop_repo)
    result = loop(loop_repo, fake_maker="break-then-fix")
    assert result.returncode == 0, result.stdout + result.stderr
    prompts = agent_prompts(loop_repo)
    assert len(prompts) == 2
    assert "Attempt 2 of 3" in prompts[1]
    assert "The previous attempt failed" in prompts[1] and "Python syntax error" in prompts[1]
    assert loop_repo.features()[0]["state"] == "passing"


def test_exhausted_attempts_shelve_and_block(loop_repo):
    with_feature(loop_repo)
    before = (loop_repo.path / "addons/demo_mod/models/thing.py").read_text()
    result = loop(loop_repo, "--attempts", "2", fake_maker="break")
    assert result.returncode == 1
    assert len(agent_prompts(loop_repo)) == 2
    feat = loop_repo.features()[0]
    assert feat["state"] == "blocked"
    assert (loop_repo.path / "addons/demo_mod/models/thing.py").read_text() == before
    assert "harness-loop" in git(loop_repo, "stash", "list")
    assert git(loop_repo, "status", "--porcelain").strip() == ""
    known = (loop_repo.path / "PROGRESS.md").read_text().split("## Known issues")[1]
    assert "F-001 blocked" in known and "git stash" in known
    assert "chore(F-001): blocked by the loop" in git(loop_repo, "log", "-1", "--format=%s")


def test_review_revise_sends_the_maker_back(loop_repo):
    with_feature(loop_repo)
    result = loop(loop_repo, "--review", fake_maker="fix", fake_reviews="Revise,Accept")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in loop_repo.agent_calls.read_text().splitlines()]
    reviewers = [c for c in calls if "--agent" in c]
    assert len(reviewers) == 2
    assert reviewers[0][reviewers[0].index("--agent") + 1].endswith(":odoo-reviewer")
    assert "Revise: reviewed." in agent_prompts(loop_repo)[1]
    assert loop_repo.features()[0]["state"] == "passing"


def test_max_features_budget(loop_repo):
    with_feature(loop_repo, "First thing", "Second thing", "Third thing")
    result = loop(loop_repo, "--max-features", "2", fake_maker="fix")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [f["state"] for f in loop_repo.features()] == ["passing", "passing", "not_started"]
    assert "--max-features 2 reached" in result.stdout


def test_stops_when_nothing_left(loop_repo):
    result = loop(loop_repo, fake_maker="fix")
    assert result.returncode == 0
    assert "no feature left to start" in result.stdout
    assert not loop_repo.agent_calls.exists()


def test_refuses_a_dirty_tree(loop_repo):
    with_feature(loop_repo)
    (loop_repo.path / "notes.txt").write_text("wip")
    result = loop(loop_repo, fake_maker="fix")
    assert result.returncode == 2
    assert "the working tree is not clean" in result.stderr and "HOW TO FIX:" in result.stderr
    assert not loop_repo.agent_calls.exists()


def test_works_on_a_new_branch(loop_repo):
    with_feature(loop_repo)
    result = loop(loop_repo, "--branch", "loop/test", fake_maker="fix")
    assert result.returncode == 0, result.stderr
    assert git(loop_repo, "branch", "--show-current").strip() == "loop/test"


def test_status(loop_repo):
    assert "No loop run yet" in loop_repo.run(sys.executable, "harness/loop.py", "status").stdout
    loop(loop_repo, fake_maker="fix")
    assert '"stopped"' in loop_repo.run(sys.executable, "harness/loop.py", "status").stdout


def test_maker_that_verifies_itself_is_verified_again(loop_repo):
    """Real Claude makers run feature.py verify themselves (seen in a live run)."""
    with_feature(loop_repo)
    result = loop(loop_repo, fake_maker="fix-and-verify")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(agent_prompts(loop_repo)) == 1
    assert (loop_repo.agent_calls.parent / "agent_calls.jsonl.self-verified").read_text() == "F-001"
    assert loop_repo.features()[0]["state"] == "passing"
    events = (loop_repo.path / ".harness/loop").glob("*/events.jsonl")
    verifies = [json.loads(line) for f in events for line in f.read_text().splitlines()
                if '"verify"' in line]
    assert verifies[-1]["passed"] is True


def test_review_rejection_is_the_shelve_reason(loop_repo):
    with_feature(loop_repo)
    result = loop(loop_repo, "--review", "--attempts", "2", fake_maker="fix", fake_reviews="Block")
    assert result.returncode == 1
    known = (loop_repo.path / "PROGRESS.md").read_text().split("## Known issues")[1]
    assert "verified, but the review verdict was Block after 2 attempts" in known
