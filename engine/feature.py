#!/usr/bin/env python3
"""Feature workflow. The only way to change tasks/<task>.json.

  feature.py status                         list features and what to do next
  feature.py add --task T2003 --behavior TEXT --verify "e2e: e2e/test_T2003_1_x.py"
                 [--verify ...] [--id F-T2003-1] [--no-branch]
                                            add a feature to a task, on the task's branch
  feature.py start ID [--reopen] [--no-branch]
                                            begin work (refused if another is in_progress here)
                                            on the task's branch (T2003): the existing one, a
                                            teammate's from origin, or a new one from
                                            BASE_BRANCH
  feature.py rename-task OLD NEW            give a task its real code once it exists in Odoo:
                                            its files and its branch (ids are kept)
  feature.py block ID --reason TEXT         park a feature, the reason goes to the task notes
  feature.py verify ID                      run the 3 layers; on success -> passing + evidence
  feature.py check                          integrity check (pre-commit, CI)
  feature.py list                           every feature as JSON, with those in progress here

Each task has its features in tasks/<task>.json and its notes in tasks/<task>.md, written on
its own branch only, so two developers on two tasks never change the same file.
States: not_started -> in_progress -> passing, or blocked. WIP = 1 per checkout.
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
    return f"- [{'x' if done else ' '}] {feat['id']} {feat['behavior']}{suffix}"


def in_progress(data):
    return [f for f in data["features"] if f["state"] == "in_progress"]


# --- commands -----------------------------------------------------------------

def cmd_status(_args):
    data = hlib.load_features()
    if not data["features"]:
        print("No features yet. Add them with: odoo-harness feature add --task T2003 "
              "--behavior ... --verify ...")
        return 0
    marks = {"not_started": " ", "in_progress": ">", "blocked": "!", "passing": "✓"}
    here = hlib.in_progress_here(data)
    elsewhere = [f for f in in_progress(data) if f not in here]
    for feat in data["features"]:
        state = "in_progress, other branch" if feat in elsewhere else feat["state"]
        print(f"[{marks[feat['state']]}] {feat['id']}  {state:<11}  [{feat['task']}] "
              f"{feat['behavior']}")
    if here:
        feat = here[0]
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


def next_id(data, task):
    """F-<task>-<n>, n after every id with that prefix: a renamed task keeps its ids, so a new
    task reusing its old free name continues the numbering."""
    prefix = f"F-{task}-"
    numbers = [int(f["id"][len(prefix):]) for f in data["features"]
               if f["id"].startswith(prefix) and f["id"][len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"


def e2e_example(fid):
    return f"e2e/test_{fid.removeprefix('F-').replace('-', '_')}_discount.py"


def cmd_add(args):
    task = args.task.strip()
    hlib.check_task_name(task)
    data = hlib.load_features()
    # An Odoo code may already have its branch; a free name may be an environment (preprod).
    if (not hlib.task_features(data, task) and branch_exists(task)
            and not hlib.TASK_CODE_RE.match(task)):
        raise RedPen("features", f"a branch named {task} already exists",
                     "A task is worked on the branch of the same name, and this one may be "
                     "shared (preprod, recette...).",
                     "Choose another name, or the Odoo task code (T2003) if this is its branch.")
    if not args.no_branch:
        # A task's files are written on its own branch only.
        switch_to_task_branch(task, "add the feature")
        data = hlib.load_features()
    fid = args.id or next_id(data, task)
    if any(f["id"] == fid for f in data["features"]):
        raise RedPen("features", f"{fid} already exists", "Feature ids are unique.",
                     "Omit --id to get the next free id.")
    feat = {"id": fid, "behavior": args.behavior.strip(), "verification": args.verify,
            "state": "not_started", "evidence": None, "task": task}
    problems = hlib.validate({"version": 1, "features": [feat]})
    if problems:
        raise RedPen("features", f"cannot add {fid}: " + "; ".join(problems),
                     "A feature needs one observable behavior and the tests that prove it, "
                     "including its own e2e test.",
                     f"Example: --task {task} --behavior 'Salesperson applies a discount on a "
                     "quotation line' --verify 'unit: /sale_discount:TestDiscount' "
                     f"--verify 'e2e: {e2e_example(fid)}'")
    data["features"].append(feat)
    hlib.save_features(data)
    hlib.notes_set_feature(feat, task_line(feat))
    print(f"✓ added {fid}: {feat['behavior']}")
    return 0


def wip_conflicts(data, feat):
    """Features in progress that forbid starting feat: one in this checkout, or one of its
    task (worked on the same branch)."""
    here = hlib.in_progress_here(data)
    same_task = [f for f in in_progress(data) if f["task"] == feat["task"]]
    return [f["id"] for f in here + same_task if f["id"] != feat["id"]]


def refuse_wip(feat, others):
    raise RedPen("features", f"cannot start {feat['id']}: {others[0]} is in_progress",
                 "WIP = 1: finish the current feature before starting another one.",
                 f"Finish {others[0]} (odoo-harness feature verify {others[0]}), or if it "
                 f"cannot progress: odoo-harness feature block {others[0]} --reason '...'")


def cmd_start(args):
    data = hlib.load_features()
    feat = hlib.find_feature(data, args.id)
    others = wip_conflicts(data, feat)
    if others:
        refuse_wip(feat, others)
    if not args.no_branch:
        switch_to_task_branch(feat["task"], "start the feature")
        # the task branch has its own version of the task files (a teammate's, for one)
        data = hlib.load_features()
        try:
            feat = hlib.find_feature(data, args.id)
        except RedPen:
            raise RedPen("features", f"{args.id} is not on the branch {feat['task']}",
                         "The task branch does not have this feature: it was added elsewhere "
                         "and not merged there.",
                         f"Add it on the branch: odoo-harness feature add --task {feat['task']} "
                         "...")
        others = wip_conflicts(data, feat)
        if others:
            refuse_wip(feat, others)
    if feat["state"] == "in_progress":
        print(f"{feat['id']} is already in progress.")
        return 0
    if feat["state"] == "passing" and not args.reopen:
        raise RedPen("features", f"{feat['id']} is already passing",
                     "A passing feature is reopened only when it regressed.",
                     f"If it regressed: odoo-harness feature start {feat['id']} --reopen")
    feat["state"], feat["evidence"] = "in_progress", None
    hlib.save_features(data)
    state = hlib.load_state()
    state[feat["id"]] = {"start_commit": hlib.head_commit(), "started_at": hlib.now_iso()}
    hlib.save_state(state)
    hlib.notes_set_feature(feat, task_line(feat, suffix=" (in progress)"))
    print(f"✓ {feat['id']} in progress: {feat['behavior']}")
    print("Verification to satisfy:")
    for entry in feat["verification"]:
        print(f"  - {entry}")
    return 0


def has_harness(ref):
    """The commit has the harness, in the layout of this engine (one file per task)."""
    return all(subprocess.run(["git", "cat-file", "-e", f"{ref}:{path}"], cwd=hlib.REPO_ROOT,
                              capture_output=True).returncode == 0
               for path in ("harness/harness.env", "tasks"))


def has_legacy_harness(ref):
    return subprocess.run(["git", "cat-file", "-e", f"{ref}:feature_list.json"],
                          cwd=hlib.REPO_ROOT, capture_output=True).returncode == 0


def fetch_task_branch(task):
    """Refresh origin/<task>, best effort: without the network the last fetch is used."""
    if not hlib.git("remote", "get-url", "origin"):
        return
    try:
        out = subprocess.run(["git", "fetch", "-q", "origin", f"refs/heads/{task}"],
                             cwd=hlib.REPO_ROOT, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"! git fetch origin {task} timed out: using the last fetch", file=sys.stderr)
        return
    remote = f"refs/remotes/origin/{task}"
    if out.returncode == 0:
        hlib.git("update-ref", remote, "FETCH_HEAD")
    elif "couldn't find remote ref" in out.stderr:
        hlib.git("update-ref", "-d", remote)  # deleted on GitLab (merged): not a branch to join
    else:
        print(f"! git fetch origin {task} failed, using the last fetch: "
              f"{out.stderr.strip()[:200]}", file=sys.stderr)


def git_or_redpen(*args, doing):
    out = subprocess.run(["git", *args], cwd=hlib.REPO_ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise RedPen("git", f"git {' '.join(args)} failed", out.stderr.strip()[:300],
                     f"Fix the git state (see the message), then {doing} again.")


def is_ancestor(ref, of):
    return subprocess.run(["git", "merge-base", "--is-ancestor", ref, of], cwd=hlib.REPO_ROOT,
                          capture_output=True).returncode == 0


def catch_up_with_origin(task, doing):
    """The local task branch takes the commits a teammate pushed to origin/<task>."""
    remote = f"refs/remotes/origin/{task}"
    if not ref_exists(remote) or is_ancestor(remote, task):
        return  # nothing on origin, or nothing new there
    if not is_ancestor(task, remote):
        raise RedPen("git", f"the branch {task} and origin/{task} have diverged",
                     "Someone pushed to the task branch while you had local commits on it.",
                     f"Bring them together: git pull --rebase origin {task}, then {doing} again.")
    git_or_redpen("merge", "-q", "--ff-only", remote, doing=doing)
    print(f"✓ {task} fast-forwarded to origin/{task}")


def clean_submodules():
    """Submodules checked out at the commit the project records, without changes: those a
    branch switch moves along (the others hold work in progress, left as they are)."""
    return [s["path"] for s in hlib.submodules() if s["initialized"]
            and hlib.git("rev-parse", "HEAD", cwd=hlib.REPO_ROOT / s["path"])
            == hlib.git("rev-parse", f"HEAD:{s['path']}")
            and not hlib.git("status", "--porcelain", cwd=hlib.REPO_ROOT / s["path"])]


def switch_to_task_branch(task, doing):
    """Check out the task's branch (see checkout_task_branch), and the submodule commits it
    records: git checkout leaves the submodules where they were, so the tests would run on
    another commit of a shared module."""
    before, clean = hlib.head_commit(), clean_submodules()
    checkout_task_branch(task, doing)
    if clean and hlib.head_commit() != before:
        git_or_redpen("submodule", "update", "-q", "--", *clean, doing=doing)


def checkout_task_branch(task, doing):
    """Check out the task's branch: the local one, else a teammate's from origin, else a new
    one from the base branch. `doing` names the command for the red pens."""
    fetch_task_branch(task)
    branch = hlib.current_branch()
    if branch == task:
        catch_up_with_origin(task, doing)
        return
    if not hlib.head_commit():
        return
    if hlib.working_tree_dirty():
        raise RedPen("git", f"cannot switch to the branch of {task}: uncommitted changes on "
                     f"'{branch or 'HEAD'}'",
                     "Each Odoo task is worked on its own branch; switching now would carry "
                     "unrelated changes into it.",
                     f"Commit the finished work (or stash it), then {doing} again.")
    env = hlib.load_env()
    base = env.get("BASE_BRANCH", "")
    note = ""
    if ref_exists(f"refs/heads/{task}"):
        args = ["checkout", "-q", task]
    elif ref_exists(f"refs/remotes/origin/{task}"):
        if not has_harness(f"origin/{task}"):
            legacy = has_legacy_harness(f"origin/{task}")
            raise RedPen("git", f"the branch {task} on origin "
                         + ("has the harness of an engine before 3.0 (feature_list.json)"
                            if legacy else "was created before the harness"),
                         "A task is worked on the branch of the same name, and this one does "
                         "not have the harness files of this engine (tasks/).",
                         f"Either continue it: git checkout -b {task} origin/{task} && git merge "
                         f"origin/{base or 'staging'}"
                         + (" (then /odoo-harness:update if feature_list.json remains)"
                            if legacy else "")
                         + f", then {doing} again; or work under a new name, e.g. "
                         f"--task {task}_{datetime.date.today():%d%m%Y}.")
        args = ["checkout", "-q", "-b", task, "--track", f"origin/{task}"]
        note = f" (from origin/{task})"
    else:
        # Start from the base branch, but only from a commit that has the harness: until the
        # harness install is merged upstream, the local base branch is the one that has it.
        refs = [base, f"origin/{base}"] if base else []
        start = next((r for r in refs if has_harness(r)), "HEAD")
        args = ["checkout", "-q", "-b", task, start]
        note = f" (new, from {start})"
    git_or_redpen(*args, doing=doing)
    if not note:
        catch_up_with_origin(task, doing)
    print(f"✓ on branch {task}{note}")


def ref_exists(ref):
    return bool(hlib.git("rev-parse", "--verify", "-q", ref))


def branch_exists(name):
    """Locally or on origin (as of the last fetch)."""
    return ref_exists(f"refs/heads/{name}") or ref_exists(f"refs/remotes/origin/{name}")


def cmd_rename_task(args):
    """Rename a task. Its commits keep the old name: published history is not rewritten, and
    the evidence stays valid because the fingerprint does not cover the task. The feature
    ids are kept too (F-remise-devis-1): they are only labels, and stay unique."""
    old, new = args.old, args.new
    data = hlib.load_features()
    feats = hlib.task_features(data, old)
    if not feats:
        raise RedPen("features", f"no feature belongs to task {old}",
                     "Only a task with a file in tasks/ can be renamed.",
                     "Run `odoo-harness feature status` to list the tasks.")
    hlib.check_task_name(new)
    if hlib.task_features(data, new) or branch_exists(new):
        raise RedPen("features", f"task or branch {new} already exists",
                     "Renaming onto it would mix two tasks.",
                     f"Choose another name, or move {new} out of the way first.")
    has_branch = ref_exists(f"refs/heads/{old}")
    if has_branch and hlib.current_branch() != old:
        raise RedPen("git", f"not on the branch of {old} (on '{hlib.current_branch()}')",
                     "The task files must change on the branch that carries the task.",
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
    hlib.save_features(data)
    hlib.notes_rename(old, new)
    print(f"✓ task {old} is now {new}: {', '.join(f['id'] for f in feats)}"
          + (f", branch {new}" if has_branch else ""))
    print(f"Commit it: git add -A tasks && git commit -m '[{new}] Rename task {old}'")
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
    hlib.notes_set_feature(feat, task_line(feat, suffix=" (blocked)"))
    hlib.notes_append(feat["task"], "Known issues",
                      f"- {feat['id']} blocked ({today()}): {args.reason.strip()}")
    print(f"✓ {feat['id']} blocked. Reason recorded in tasks/{feat['task']}.md (Known issues).")
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
    hlib.notes_set_feature(feat, task_line(feat, done=True, suffix=f" (verified {today()})"))
    print(f"\n✓ {feat['id']} passing. Evidence: {feat['evidence']['file']}")
    print(f"Before moving on: update tasks/{feat['task']}.md (Notes, Known issues, Decisions, "
          f"Next steps), commit with the message: {hlib.commit_message(feat)}")
    clean = clean_submodules()
    for sub in hlib.submodules():
        if sub["initialized"] and sub["path"] not in clean:
            path = sub["path"]
            missing = [f for f in hlib.SHARED_FILES if not (hlib.REPO_ROOT / path / f).is_file()]
            first = ""
            if missing and hlib.shared_files_upstream(sub):
                first = (f"its knowledge files are on {sub['branch']}, not in this checkout: "
                         f"rebase it before recording its decisions (git -C {path} rebase "
                         f"origin/{sub['branch']}), verify again, ")
            elif missing:
                first = (f"add its knowledge files (python3 {hlib.INSTALL_TEMPLATE} --shared "
                         f"{path}, then fill its ARCHITECTURE.md), ")
            print(f"The shared submodule {path} changed: {first}record the decisions about it "
                  f"in its DECISIONS.md, commit inside it first (git -C {path} add -A "
                  f"&& git -C {path} commit -m \"{hlib.commit_message(feat)}\"), then "
                  "commit the project (its pointer included).")
    left = [f["id"] for f in hlib.task_features(data, feat["task"]) if f["state"] != "passing"]
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
                     "again. Do not edit tasks/*.json or harness/evidence/ by hand.")
    print(f"✓ feature list OK ({len(data['features'])} features)")
    return 0


def cmd_list(_args):
    """The features as JSON, for the hooks: one reader of the task files."""
    data = hlib.load_features()
    print(json.dumps({"branch": hlib.current_branch(),
                      "here": [f["id"] for f in hlib.in_progress_here(data)],
                      "features": data["features"]}, ensure_ascii=False))
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
    add.add_argument("--task", required=True,
                     help="code of the Odoo task this feature belongs to (T2003), or any short "
                     "name until it exists (then rename-task)")
    add.add_argument("--no-branch", action="store_true",
                     help="write the task file on the current branch (initialization only)")
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
    sub.add_parser("list").set_defaults(fn=cmd_list)
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
