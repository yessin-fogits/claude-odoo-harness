#!/usr/bin/env python3
"""Feature workflow. The only way to change feature_list.json.

  feature.py status                         list features and what to do next
  feature.py add --behavior TEXT --verify "e2e: e2e/test_F001_x.py" [--verify ...]
                 [--task T2003] [--id F-001]
  feature.py start ID [--reopen] [--no-branch]
                                            begin work (refused if another is in_progress);
                                            a feature of an Odoo task is worked on the task's
                                            branch (T2003), created from BASE_BRANCH
  feature.py rename-task OLD NEW            give a task its real code once it exists in Odoo:
                                            its features, its branch and PROGRESS.md
  feature.py block ID --reason TEXT         park a feature, the reason goes to PROGRESS.md
  feature.py verify ID                      run the 3 layers; on success -> passing + evidence
  feature.py check                          integrity check (pre-commit, CI)

States: not_started -> in_progress -> passing, or blocked. WIP = 1.
Only `verify` can set passing; it records evidence in harness/evidence/<ID>.json.
When every feature of a task passes and is committed, `odoo-harness gitlab mr <task>`
pushes the task branch and opens its merge request.
"""

import argparse
import datetime
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hlib  # noqa: E402
from hlib import RedPen  # noqa: E402


def today():
    return datetime.date.today().isoformat()


def task_line(feat, done=False, suffix=""):
    task = f"[{feat['task']}] " if feat.get("task") else ""
    return f"- [{'x' if done else ' '}] {feat['id']} {task}{feat['behavior']}{suffix}"


def in_progress(data):
    return [f for f in data["features"] if f["state"] == "in_progress"]


# --- commands -----------------------------------------------------------------

def cmd_status(_args):
    data = hlib.load_features()
    if not data["features"]:
        print("No features yet. Add them with: odoo-harness feature add --behavior ... --verify ...")
        return 0
    marks = {"not_started": " ", "in_progress": ">", "blocked": "!", "passing": "✓"}
    for feat in data["features"]:
        task = f"[{feat['task']}] " if feat.get("task") else ""
        print(f"[{marks[feat['state']]}] {feat['id']}  {feat['state']:<11}  {task}"
              f"{feat['behavior']}")
    current = in_progress(data)
    if current:
        feat = current[0]
        print(f"\nCurrent: {feat['id']}. Verification:")
        for entry in feat["verification"]:
            print(f"  - {entry}")
        print(f"When it works: odoo-harness feature verify {feat['id']}")
    else:
        todo = [f for f in data["features"] if f["state"] == "not_started"]
        if todo:
            print(f"\nNext: odoo-harness feature start {todo[0]['id']}")
        else:
            print("\nNothing left to start.")
    return 0


def next_id(data):
    numbers = [int(f["id"][2:]) for f in data["features"]]
    return f"F-{(max(numbers) + 1 if numbers else 1):03d}"


def check_task_name(task):
    """A task name is also its git branch and part of file names; a shared branch is refused."""
    if not hlib.TASK_RE.match(task):
        raise RedPen("features", f"invalid task name {task!r}",
                     "A task name is also its git branch and part of file names: only letters, "
                     "digits, - and _.",
                     "Use the Odoo task code (T2003), or a short name until the task exists "
                     "(remise-devis).")
    shared = {"HEAD", "main", "master", "production", hlib.load_env().get("BASE_BRANCH") or "staging"}
    if task in shared:
        raise RedPen("features", f"a task cannot be named {task}",
                     "A task is worked on the branch of the same name, and this one is shared.",
                     "Use the Odoo task code (T2003), or a short name until the task exists "
                     "(remise-devis).")


def cmd_add(args):
    data = hlib.load_features()
    fid = args.id or next_id(data)
    if any(f["id"] == fid for f in data["features"]):
        raise RedPen("features", f"{fid} already exists", "Feature ids are unique.",
                     "Omit --id to get the next free id.")
    feat = {"id": fid, "behavior": args.behavior.strip(), "verification": args.verify,
            "state": "not_started", "evidence": None}
    if args.task:
        feat["task"] = args.task.strip()
        check_task_name(feat["task"])
        # An Odoo code may already have its branch; a free name may be an environment (preprod).
        if (not hlib.task_features(data, feat["task"]) and branch_exists(feat["task"])
                and not hlib.TASK_CODE_RE.match(feat["task"])):
            raise RedPen("features", f"a branch named {feat['task']} already exists",
                         "A task is worked on the branch of the same name, and this one may be "
                         "shared (preprod, recette...).",
                         "Choose another name, or the Odoo task code (T2003) if this is its branch.")
    problems = hlib.validate({"version": 1, "features": [feat]})
    if problems:
        raise RedPen("features", f"cannot add {fid}: " + "; ".join(problems),
                     "A feature needs one observable behavior and the tests that prove it, "
                     "including its own e2e test.",
                     "Example: --task T2003 --behavior 'Salesperson applies a discount on a "
                     "quotation line' --verify 'unit: /sale_discount:TestDiscount' "
                     f"--verify 'e2e: e2e/test_{fid.replace('-', '')}_discount.py'")
    data["features"].append(feat)
    hlib.save_features(data)
    print(f"✓ added {fid}: {feat['behavior']}")
    return 0


def cmd_start(args):
    data = hlib.load_features()
    feat = hlib.find_feature(data, args.id)
    others = [f["id"] for f in in_progress(data) if f["id"] != feat["id"]]
    if others:
        raise RedPen("features", f"cannot start {feat['id']}: {others[0]} is in_progress",
                     "WIP = 1: finish the current feature before starting another one.",
                     f"Finish {others[0]} (odoo-harness feature verify {others[0]}), or if it "
                     f"cannot progress: odoo-harness feature block {others[0]} --reason '...'")
    if feat["state"] == "in_progress":
        print(f"{feat['id']} is already in progress.")
        return 0
    if feat["state"] == "passing" and not args.reopen:
        raise RedPen("features", f"{feat['id']} is already passing",
                     "A passing feature is reopened only when it regressed.",
                     f"If it regressed: odoo-harness feature start {feat['id']} --reopen")
    if feat.get("task") and not args.no_branch:
        switch_to_task_branch(feat["task"])
    feat["state"], feat["evidence"] = "in_progress", None
    hlib.save_features(data)
    state = hlib.load_state()
    state[feat["id"]] = {"start_commit": hlib.head_commit(), "started_at": hlib.now_iso()}
    hlib.save_state(state)
    hlib.progress_set_task(feat["id"], task_line(feat), "In progress")
    print(f"✓ {feat['id']} in progress: {feat['behavior']}")
    print("Verification to satisfy:")
    for entry in feat["verification"]:
        print(f"  - {entry}")
    return 0


def has_harness(ref):
    return subprocess.run(["git", "cat-file", "-e", f"{ref}:harness/harness.env"],
                          cwd=hlib.REPO_ROOT, capture_output=True).returncode == 0


def switch_to_task_branch(task):
    """Check out the task's branch, creating it from the base branch the first time."""
    branch = hlib.current_branch()
    if branch == task or not hlib.head_commit():
        return
    if hlib.working_tree_dirty():
        raise RedPen("git", f"cannot switch to the branch of {task}: uncommitted changes on "
                     f"'{branch or 'HEAD'}'",
                     "Each Odoo task is worked on its own branch; switching now would carry "
                     "unrelated changes into it.",
                     "Commit the finished work (or stash it), then start the feature again.")
    env = hlib.load_env()
    base = env.get("BASE_BRANCH", "")
    if hlib.git("rev-parse", "--verify", "-q", f"refs/heads/{task}"):
        args = ["checkout", "-q", task]
    else:
        # Start from the base branch, but only from a commit that has the harness: until the
        # harness install is merged upstream, the local base branch is the one that has it.
        refs = [base, f"origin/{base}"] if base else []
        start = next((r for r in refs if has_harness(r)), "HEAD")
        args = ["checkout", "-q", "-b", task, start]
    out = subprocess.run(["git", *args], cwd=hlib.REPO_ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise RedPen("git", f"git {' '.join(args)} failed", out.stderr.strip()[:300],
                     "Fix the git state (see the message), then start the feature again.")
    print(f"✓ on branch {task}" + (f" (new, from {args[-1]})" if "-b" in args else ""))


def ref_exists(ref):
    return bool(hlib.git("rev-parse", "--verify", "-q", ref))


def branch_exists(name):
    """Locally or on origin (as of the last fetch)."""
    return ref_exists(f"refs/heads/{name}") or ref_exists(f"refs/remotes/origin/{name}")


def cmd_rename_task(args):
    """Rename a task. Its commits keep the old name: published history is not rewritten, and
    the evidence stays valid because the fingerprint does not cover the task."""
    old, new = args.old, args.new
    data = hlib.load_features()
    feats = hlib.task_features(data, old)
    if not feats:
        raise RedPen("features", f"no feature belongs to task {old}",
                     "Only a task of feature_list.json can be renamed.",
                     "Run `odoo-harness feature status` to list the tasks.")
    check_task_name(new)
    if hlib.task_features(data, new) or branch_exists(new):
        raise RedPen("features", f"task or branch {new} already exists",
                     "Renaming onto it would mix two tasks.",
                     f"Choose another name, or move {new} out of the way first.")
    has_branch = ref_exists(f"refs/heads/{old}")
    if has_branch and hlib.current_branch() != old:
        raise RedPen("git", f"not on the branch of {old} (on '{hlib.current_branch()}')",
                     "feature_list.json must change on the branch that carries the task.",
                     f"git checkout {old}, then run the command again.")
    pdf = f"docs/guides/{old}.pdf"
    if (hlib.REPO_ROOT / pdf).exists():
        raise RedPen("guide", f"task {old} already has a user guide",
                     "The guide is printed with the old name, and guides are indexed by task.",
                     f"Remove {pdf} and the {old} entry of docs/guides/guides.json, run this "
                     f"command again, then /odoo-harness:guide {new}.")
    if has_branch:
        out = subprocess.run(["git", "branch", "-m", old, new], cwd=hlib.REPO_ROOT,
                             capture_output=True, text=True)
        if out.returncode != 0:
            raise RedPen("git", f"git branch -m {old} {new} failed", out.stderr.strip()[:300],
                         "Fix the git state (see the message), then run the command again.")
    for feat in feats:
        feat["task"] = new
        hlib.progress_rename_task(feat["id"], old, new)
    hlib.save_features(data)
    print(f"✓ task {old} is now {new}: {', '.join(f['id'] for f in feats)}"
          + (f", branch {new}" if has_branch else ""))
    print(f"Commit it: git add feature_list.json PROGRESS.md && "
          f"git commit -m '[{new}] Rename task {old}'")
    mr = hlib.STATE_DIR / "mr" / f"{old}.json"
    if ref_exists(f"refs/remotes/origin/{old}") or mr.is_file():
        url = json.loads(mr.read_text()).get("url") if mr.is_file() else None
        print(f"Still on GitLab under the old name: branch {old}"
              + (f" and its merge request {url}" if url else "")
              + f". Close or delete them there (the harness does not); `odoo-harness gitlab mr "
              f"{new}` opens the new one.")
    return 0


def cmd_block(args):
    data = hlib.load_features()
    feat = hlib.find_feature(data, args.id)
    if feat["state"] == "passing":
        raise RedPen("features", f"{feat['id']} is passing and cannot be blocked",
                     "Blocking is for work that cannot progress.",
                     "If it regressed, reopen it with start --reopen first.")
    feat["state"] = "blocked"
    hlib.save_features(data)
    hlib.progress_set_task(feat["id"], "", None)
    hlib.progress_append("Known issues",
                         f"- {feat['id']} blocked ({today()}): {args.reason.strip()}")
    print(f"✓ {feat['id']} blocked. Reason recorded in PROGRESS.md (Known issues).")
    return 0


def verify_command():
    custom = os.environ.get("HARNESS_VERIFY_CMD")
    if custom:
        return shlex.split(custom)
    return [sys.executable, str(hlib.ENGINE_DIR / "verify.py")]


def cmd_verify(args):
    data = hlib.load_features()
    feat = hlib.find_feature(data, args.id)
    if feat["state"] != "in_progress":
        raise RedPen("features", f"{feat['id']} is {feat['state']}, not in_progress",
                     "Only the feature being worked on can be verified into passing.",
                     f"Start it first: odoo-harness feature start {feat['id']}")
    cmd = verify_command() + ["--feature", feat["id"], "--fresh-install"]
    for entry in feat["verification"]:
        kind, target = hlib.parse_verification(entry)
        cmd += ["--e2e", target] if kind == "e2e" else ["--tags", target]
    report_path = hlib.STATE_DIR / "verify" / f"{feat['id']}.json"
    report_path.unlink(missing_ok=True)
    cmd += ["--report", str(report_path)]
    rc = subprocess.run(cmd, cwd=hlib.REPO_ROOT).returncode
    try:
        report = json.loads(report_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        report = None
    if rc != 0 or not report or report.get("result") != "pass":
        print(f"\n✗ {feat['id']} is NOT verified; it stays in_progress. Fix the failures above "
              f"and run odoo-harness feature verify {feat['id']} again.", file=sys.stderr)
        return 1

    fp = hlib.fingerprint(feat)
    evidence_file = hlib.EVIDENCE_DIR / f"{feat['id']}.json"
    record = {"feature": feat["id"], "behavior": feat["behavior"],
              "verification": feat["verification"], "fingerprint": fp,
              "verified_at": hlib.now_iso(), "engine_version": hlib.ENGINE_VERSION,
              "report": report}
    hlib.write_atomic(evidence_file, json.dumps(record, indent=2) + "\n")
    data = hlib.load_features()
    feat = hlib.find_feature(data, args.id)
    feat["state"] = "passing"
    feat["evidence"] = {"file": str(evidence_file.relative_to(hlib.REPO_ROOT)),
                        "commit": report.get("commit"), "verified_at": record["verified_at"],
                        "fingerprint": fp}
    hlib.save_features(data)
    hlib.progress_set_task(feat["id"], task_line(feat, done=True, suffix=f" (verified {today()})"),
                           "Completed tasks")
    print(f"\n✓ {feat['id']} passing. Evidence: {feat['evidence']['file']}")
    print("Before moving on: update PROGRESS.md (Known issues, Next steps), append decisions "
          f"to DECISIONS.md, commit with the message: {hlib.commit_message(feat)}")
    if feat.get("task"):
        left = [f["id"] for f in hlib.task_features(data, feat["task"])
                if f["state"] != "passing"]
        if left:
            print(f"Task {feat['task']}: {', '.join(left)} still to do.")
        else:
            print(f"Task {feat['task']}: every feature passes. After the commit: "
                  f"odoo-harness gitlab mr {feat['task']} (pushes the branch, opens the merge "
                  "request).")
    return 0


def cmd_check(_args):
    """Integrity: valid file, WIP = 1, every passing feature backed by real evidence."""
    data = hlib.load_features()
    problems = []
    for feat in data["features"]:
        if feat["state"] != "passing":
            continue
        ev = feat["evidence"]
        path = hlib.REPO_ROOT / ev.get("file", "")
        try:
            record = json.loads(path.read_text())
        except (FileNotFoundError, IsADirectoryError, json.JSONDecodeError):
            problems.append(f"{feat['id']}: evidence file {ev.get('file')!r} missing or invalid")
            continue
        fp = hlib.fingerprint(feat)
        if not (record.get("feature") == feat["id"] and record.get("fingerprint") == fp
                and ev.get("fingerprint") == fp):
            problems.append(f"{feat['id']}: behavior/verification changed after it was verified")
        elif record.get("report", {}).get("result") != "pass":
            problems.append(f"{feat['id']}: evidence does not record a passing verification")
    if problems:
        raise RedPen("features", "feature list integrity: " + "; ".join(problems),
                     "A feature is marked passing without matching verification evidence. "
                     "Only odoo-harness feature verify may set passing.",
                     "Reopen the feature (odoo-harness feature start <id> --reopen) and verify it "
                     "again. Do not edit feature_list.json or harness/evidence/ by hand.")
    print(f"✓ feature list OK ({len(data['features'])} features)")
    return 0


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    add = sub.add_parser("add")
    add.add_argument("--behavior", required=True, help="one observable behavior")
    add.add_argument("--verify", action="append", required=True,
                     help="'unit: <test-tags>', 'integration: <test-tags>' or 'e2e: <file>'")
    add.add_argument("--id")
    add.add_argument("--task", help="code of the Odoo task this feature belongs to (T2003), or "
                     "any short name until it exists (then rename-task)")
    add.set_defaults(fn=cmd_add)
    start = sub.add_parser("start")
    start.add_argument("id")
    start.add_argument("--reopen", action="store_true", help="reopen a passing feature")
    start.add_argument("--no-branch", action="store_true",
                       help="stay on the current branch even if the feature has a task")
    start.set_defaults(fn=cmd_start)
    rename = sub.add_parser("rename-task")
    rename.add_argument("old")
    rename.add_argument("new")
    rename.set_defaults(fn=cmd_rename_task)
    block = sub.add_parser("block")
    block.add_argument("id")
    block.add_argument("--reason", required=True)
    block.set_defaults(fn=cmd_block)
    verify = sub.add_parser("verify")
    verify.add_argument("id")
    verify.set_defaults(fn=cmd_verify)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        return args.fn(args)
    except RedPen as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
