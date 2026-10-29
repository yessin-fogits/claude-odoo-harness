#!/usr/bin/env python3
"""Autonomous feature loop: a maker-checker graph over feature_list.json.

    odoo-harness loop run [--max-features 1] [--attempts 3] [--review] [--branch NAME]
    odoo-harness loop status

The graph (each name is a function below; the code follows it one to one):

    preflight --> select --(none left)--> end
                    |
                    v
                  maker  (claude -p: implement the feature, may run the verification)
                    |
                    v
                  verify (odoo-harness feature verify: the machine judge; the maker cannot
                    |     mark its own work passing)
          fail -----+----- pass
           |                |
     attempts left?    review? (odoo-reviewer agent, fresh context) -- Revise/Block --> retry
       yes: retry           | Accept / no review
       no:  shelve          v
            (git stash +  commit --> select (next feature, within --max-features)
             feature.py block)

Budgets: features per run (default 1, so a human reviews each one), attempts per feature,
turns and dollars per agent call, wall-clock timeout per call. Every step is logged to
.harness/loop/<run>/events.jsonl with the agents' outputs, and the run summary goes to
.harness/loop/last.json.
"""

import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hlib  # noqa: E402

LOOP_DIR = hlib.STATE_DIR / "loop"
VERDICT_RE = re.compile(r"###\s*Verdict\s*\n+\s*`?\*{0,2}(Accept|Revise|Block)", re.I)
MAKER_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(odoo-harness feature:*)", "Bash(odoo-harness verify:*)",
    "Bash(odoo-harness init:*)", "Bash(odoo-harness static:*)",
    "Bash(odoo-harness compose ps:*)", "Bash(odoo-harness compose logs:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
]
REVIEWER_TOOLS = ["Read", "Glob", "Grep", "Bash(git diff:*)", "Bash(git status:*)",
                  "Bash(git log:*)", "Bash(odoo-harness feature status:*)"]


class Stop(Exception):
    """A preflight or git failure that ends the run (red pen in the message)."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class Run:
    def __init__(self, args):
        self.args = args
        self.id = f"{now()}"
        self.dir = LOOP_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.summary = {"run": self.id, "passing": [], "blocked": [], "stopped": None}

    def event(self, kind, **data):
        line = json.dumps({"at": now(), "event": kind, **data})
        with (self.dir / "events.jsonl").open("a") as fh:
            fh.write(line + "\n")
        detail = " ".join(f"{k}={v}" for k, v in data.items() if k not in ("output",))
        print(f"→ loop {kind} {detail}", flush=True)


# --- helpers ---------------------------------------------------------------------

def sh(*args, check=False, timeout=None):
    proc = subprocess.run(list(args), cwd=hlib.REPO_ROOT, capture_output=True, text=True,
                          timeout=timeout, errors="replace")
    if check and proc.returncode != 0:
        raise Stop(f"`{' '.join(args)}` failed:\n{proc.stdout}{proc.stderr}")
    return proc


def agent_cmd():
    return shlex.split(os.environ.get("HARNESS_AGENT", "claude"))


def plugin_name():
    return "odoo-harness"


def run_agent(run, label, prompt, tools, agent=None):
    args = run.args
    cmd = agent_cmd() + ["-p", prompt, "--output-format", "json",
                         "--max-turns", str(args.max_turns),
                         "--permission-mode", "acceptEdits",
                         "--allowedTools", *tools]
    if args.max_budget_usd:
        cmd += ["--max-budget-usd", str(args.max_budget_usd)]
    if agent:
        cmd += ["--agent", agent]
    try:
        proc = subprocess.run(cmd, cwd=hlib.REPO_ROOT, capture_output=True, text=True,
                              timeout=args.timeout, errors="replace")
        out, rc = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, rc = (exc.stdout or "") if isinstance(exc.stdout, str) else "", 124
    except FileNotFoundError:
        raise Stop(hlib.format_redpen(
            "loop", f"agent command not found: {agent_cmd()[0]}",
            "The loop runs Claude Code headless (claude -p) for the maker and reviewer.",
            "Install Claude Code, or set HARNESS_AGENT to the command to use."))
    (run.dir / f"{label}.json").write_text(out)
    try:
        result = json.loads(out).get("result", "")
    except (json.JSONDecodeError, AttributeError):
        result = out
    return rc, result or ""


# --- graph nodes -------------------------------------------------------------------

def preflight(run):
    changes = [ln for ln in sh("git", "status", "--porcelain").stdout.splitlines() if ln.strip()]
    if changes:
        raise Stop(hlib.format_redpen(
            "loop", "the working tree is not clean",
            "The loop commits verified work and shelves failed work with git; it must start "
            "from a committed state so nothing of yours gets mixed in.",
            "Commit or stash your changes, then run the loop again."))
    check = sh(sys.executable, str(hlib.ENGINE_DIR / "feature.py"), "check")
    if check.returncode != 0:
        raise Stop(check.stdout + check.stderr)
    if not os.environ.get("HARNESS_LOOP_SKIP_HEALTH"):
        health = sh("bash", str(hlib.ENGINE_DIR / "init.sh"), "--check", timeout=120)
        if health.returncode != 0:
            raise Stop(health.stdout + health.stderr + "\n" + hlib.format_redpen(
                "loop", "the baseline is not healthy",
                "Agents must not start feature work on a broken environment.",
                "Run odoo-harness init until it ends with ✓ baseline OK, then run the loop."))
    if run.args.branch:
        sh("git", "checkout", "-b", run.args.branch, check=True)
    run.event("preflight", branch=sh("git", "branch", "--show-current").stdout.strip())


def select():
    """The feature in progress, else the first not started one, else None."""
    features = hlib.load_features()["features"]
    for state in ("in_progress", "not_started"):
        for feat in features:
            if feat["state"] == state:
                return feat
    return None


def maker(run, feat, attempt, feedback):
    prompt = f"""You are the maker in the odoo-harness loop. Implement feature {feat['id']}:
"{feat['behavior']}". Attempt {attempt} of {run.args.attempts}.

Follow CLAUDE.md (Work Rules, Definition of Done) and the odoo skill for this Odoo version.
The feature's verification: {'; '.join(feat['verification'])}. Write those tests if they do
not exist yet, then the code. Run `odoo-harness feature verify {feat['id']}` to check
your work: only that command can mark the feature passing, and the loop runs it again
after you. Update PROGRESS.md (the feature line under In progress, Known issues, Next steps).
Do not commit; do not start another feature; do not edit feature_list.json.
"""
    if feedback:
        prompt += f"\nThe previous attempt failed. What the checker reported:\n{feedback}\n"
    rc, result = run_agent(run, f"{feat['id']}-attempt{attempt}-maker", prompt, MAKER_TOOLS)
    run.event("maker", feature=feat["id"], attempt=attempt, exit=rc)
    return rc


def verify(run, feat, attempt):
    """The loop's own verification. If the maker already marked the feature passing (it may
    run verify itself), reopen it: the judge re-runs the check, it does not trust the maker."""
    state = hlib.find_feature(hlib.load_features(), feat["id"])["state"]
    if state == "passing":
        sh(sys.executable, str(hlib.ENGINE_DIR / "feature.py"), "start", feat["id"], "--reopen", check=True)
    proc = sh(sys.executable, str(hlib.ENGINE_DIR / "feature.py"), "verify", feat["id"])
    output = proc.stdout + proc.stderr
    (run.dir / f"{feat['id']}-attempt{attempt}-verify.log").write_text(output)
    passed = proc.returncode == 0
    run.event("verify", feature=feat["id"], attempt=attempt, passed=passed)
    redpens = [ln for ln in output.splitlines() if ln.startswith(("✗", "WHY:", "HOW TO FIX:"))]
    return passed, "\n".join(redpens[:30]) or output[-3000:]


def review(run, feat, attempt):
    prompt = (f"Review feature {feat['id']} (\"{feat['behavior']}\") of this repository. "
              "It just passed odoo-harness feature verify. The changes are not committed yet on "
              "purpose: the loop commits them after your Accept, so judge the code, tests and "
              "scope, not the missing commit. Answer in your report format, starting with "
              "the ### Verdict section.")
    rc, result = run_agent(run, f"{feat['id']}-attempt{attempt}-review", prompt, REVIEWER_TOOLS,
                           agent=f"{plugin_name()}:odoo-reviewer")
    match = VERDICT_RE.search(result)
    verdict = match.group(1).capitalize() if match else "none"
    run.event("review", feature=feat["id"], attempt=attempt, verdict=verdict)
    if verdict == "none":
        result = ("The reviewer gave no verdict (its last message is below); the work is not "
                  "accepted.\n" + result)
    return verdict == "Accept", verdict, result[-4000:]


def commit(run, feat):
    sh("git", "add", "-A", check=True)
    sh("git", "commit", "-q", "-m", f"{hlib.commit_message(feat)}\n\n"
       f"Verified by odoo-harness feature verify (loop run {run.id}).", check=True)
    run.event("commit", feature=feat["id"], sha=sh("git", "rev-parse", "--short", "HEAD").stdout.strip())
    run.summary["passing"].append(feat["id"])


def ship(run, feat):
    """When the feature completes its Odoo task: push the branch, open the merge request."""
    task = feat.get("task")
    if not task or run.args.no_mr:
        return
    if any(f["state"] != "passing" for f in hlib.task_features(hlib.load_features(), task)):
        return
    proc = sh(sys.executable, str(hlib.ENGINE_DIR / "gitlab.py"), "mr", task)
    url = next((ln.split(": ", 1)[1] for ln in proc.stdout.splitlines()
                if ln.startswith("✓ merge request")), None)
    run.event("merge_request", task=task, ok=proc.returncode == 0, url=url,
              error=None if proc.returncode == 0 else proc.stderr.strip()[:300])
    if proc.returncode == 0:
        run.summary.setdefault("merge_requests", []).append(url or task)
    else:
        print(proc.stderr, file=sys.stderr)


def shelve(run, feat, start_commit, reason):
    """Keep the failed work in a named stash, restore the start state, block the feature."""
    label = f"harness-loop {run.id} {feat['id']}"
    sh("git", "stash", "push", "-u", "-m", label, check=True)
    stash = next((ln.split(":")[0] for ln in sh("git", "stash", "list").stdout.splitlines()
                  if label in ln), "stash")
    head = sh("git", "rev-parse", "HEAD").stdout.strip()
    if head != start_commit:
        raise Stop(f"HEAD moved during the feature ({start_commit[:8]} -> {head[:8]}); stopping.")
    sh(sys.executable, str(hlib.ENGINE_DIR / "feature.py"), "block", feat["id"], "--reason",
       f"loop {run.id}: {reason}. Work saved in git stash '{label}' ({stash}).", check=True)
    sh("git", "add", "-A", check=True)
    sh("git", "commit", "-q", "-m", f"chore({feat['id']}): blocked by the loop ({reason})",
       check=True)
    run.event("shelve", feature=feat["id"], stash=label, reason=reason)
    run.summary["blocked"].append(feat["id"])


# --- the graph ---------------------------------------------------------------------------

def run_graph(args):
    run = Run(args)
    try:
        preflight(run)
        for _ in range(args.max_features):
            feat = select()
            if feat is None:
                run.summary["stopped"] = "no feature left to start"
                break
            if feat["state"] == "not_started":
                # may check out the branch of the feature's Odoo task
                sh(sys.executable, str(hlib.ENGINE_DIR / "feature.py"), "start", feat["id"], check=True)
            start_commit = sh("git", "rev-parse", "HEAD").stdout.strip()
            run.event("select", feature=feat["id"])
            feedback, done, failure = "", False, "not verified"
            for attempt in range(1, args.attempts + 1):
                maker(run, feat, attempt, feedback)
                passed, feedback = verify(run, feat, attempt)
                if not passed:
                    failure = "not verified"
                    continue
                if args.review:
                    accepted, verdict, feedback = review(run, feat, attempt)
                    if not accepted:
                        failure = f"verified, but the review verdict was {verdict}"
                        sh(sys.executable, str(hlib.ENGINE_DIR / "feature.py"), "start", feat["id"], "--reopen",
                           check=True)
                        continue
                commit(run, feat)
                ship(run, feat)
                done = True
                break
            if not done:
                shelve(run, feat, start_commit, f"{failure} after {args.attempts} attempts")
        else:
            run.summary["stopped"] = f"--max-features {args.max_features} reached"
    except Stop as exc:
        run.summary["stopped"] = "error"
        print(str(exc), file=sys.stderr)
        run.event("stop", reason=str(exc).splitlines()[0][:200])
    hlib.write_atomic(LOOP_DIR / "last.json", json.dumps(run.summary, indent=2) + "\n")
    hlib.write_atomic(run.dir / "summary.json", json.dumps(run.summary, indent=2) + "\n")
    print(f"\nloop {run.id}: passing {run.summary['passing'] or '-'}, "
          f"blocked {run.summary['blocked'] or '-'}, stopped: {run.summary['stopped']}")
    print(f"log: {run.dir.relative_to(hlib.REPO_ROOT)}/events.jsonl")
    if run.summary["stopped"] == "error":
        return 2
    return 1 if run.summary["blocked"] else 0


def cmd_status(_args):
    try:
        print((LOOP_DIR / "last.json").read_text(), end="")
    except FileNotFoundError:
        print("No loop run yet: odoo-harness loop run")
    return 0


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="work through the feature list")
    r.add_argument("--max-features", type=int, default=1,
                   help="features to finish in this run (default 1: a human reviews each)")
    r.add_argument("--attempts", type=int, default=3, help="maker attempts per feature")
    r.add_argument("--max-turns", type=int, default=80, help="turns per agent call")
    r.add_argument("--max-budget-usd", type=float, help="dollar budget per agent call")
    r.add_argument("--timeout", type=int, default=3600, help="seconds per agent call")
    r.add_argument("--review", action="store_true",
                   help="also require an Accept verdict from the odoo-reviewer agent")
    r.add_argument("--branch", help="create this branch first and work on it")
    r.add_argument("--no-mr", action="store_true",
                   help="do not push and open the merge request when a task is complete")
    r.set_defaults(fn=run_graph)
    sub.add_parser("status", help="summary of the last run").set_defaults(fn=cmd_status)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
