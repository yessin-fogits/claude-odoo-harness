#!/usr/bin/env python3
"""Ship an Odoo task: push its branch and open its merge request on GitLab.

    odoo-harness gitlab push TASK                 push the task branch (git push -u origin TASK)
    odoo-harness gitlab mr TASK [--title TEXT]    push, then open (or update) the merge request
                                                TASK -> BASE_BRANCH

`mr` is refused until every feature of the task passes (odoo-harness feature verify) and
the work is committed: the merge request lists the features with their evidence.
Settings come from harness/harness.env (GITLAB_URL, GITLAB_PROJECT, BASE_BRANCH). The
token is GITLAB_TOKEN, from the environment or the git-ignored .env file of the
repository (a personal or project access token with the api scope); never commit it.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hlib  # noqa: E402
from hlib import RedPen  # noqa: E402

MR_DIR = hlib.STATE_DIR / "mr"


def token():
    value = os.environ.get("GITLAB_TOKEN", "").strip()
    dotenv = hlib.REPO_ROOT / ".env"
    if not value and dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            key, _, val = line.strip().partition("=")
            if key.strip() == "GITLAB_TOKEN":
                value = val.strip().strip("'\"")
    if not value:
        raise RedPen("gitlab", "GITLAB_TOKEN is not set",
                     "Opening a merge request calls the GitLab API as you.",
                     "Create a personal access token with the api scope on GitLab, then "
                     "`export GITLAB_TOKEN=...` or add GITLAB_TOKEN=... to the .env file at the "
                     "repository root (git-ignored). Never commit it.")
    return value


def api(env, method, path, payload=None):
    base = env.get("GITLAB_URL", "").rstrip("/")
    project = env.get("GITLAB_PROJECT", "")
    if not base or not project:
        raise RedPen("gitlab", "GITLAB_URL or GITLAB_PROJECT is empty in harness/harness.env",
                     "The harness does not know which GitLab project the repository belongs to.",
                     "Set GITLAB_URL=https://gitlab.example.com and GITLAB_PROJECT=group/project "
                     "in harness/harness.env.")
    url = f"{base}/api/v4/projects/{urllib.parse.quote(project, safe='')}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "PRIVATE-TOKEN": token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        hints = {401: "The token is invalid or expired: create a new one (api scope).",
                 403: "The token cannot write to this project: it needs the api scope and at "
                      "least the Developer role.",
                 404: f"Check GITLAB_PROJECT={project} in harness/harness.env (group/project)."}
        raise RedPen("gitlab", f"GitLab API {method} {path} failed ({exc.code})", detail,
                     hints.get(exc.code, "Read the GitLab message above and fix the cause."))
    except urllib.error.URLError as exc:
        raise RedPen("gitlab", f"cannot reach {base}", str(exc.reason),
                     "Check GITLAB_URL and the network (VPN, proxy).")


def git(*args):
    proc = subprocess.run(["git", *args], cwd=hlib.REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_branch(task):
    if hlib.current_branch() != task:
        raise RedPen("git", f"not on the branch of {task} (on '{hlib.current_branch()}')",
                     "A task is shipped from its own branch.",
                     f"git checkout {task}, then run the command again.")
    if hlib.working_tree_dirty():
        raise RedPen("git", "uncommitted changes",
                     "Only committed work is pushed; the merge request would miss them.",
                     "Commit the verified work (message: [TASK] F-xxx behavior), then run the "
                     "command again.")


def push(task):
    check_branch(task)
    rc, out = git("push", "-u", "origin", task)
    if rc != 0:
        raise RedPen("git", f"git push -u origin {task} failed", out[-400:],
                     "Fix the cause (credentials, network, rejected push: pull --rebase first), "
                     "then run the command again.")
    print(f"✓ pushed {task}")


def description(task, features):
    rows = ["| Feature | Behavior | Verified | Tests |", "|---|---|---|---|"]
    modules = set()
    for feat in features:
        record = {}
        try:
            record = json.loads((hlib.REPO_ROOT / feat["evidence"]["file"]).read_text())
        except (OSError, ValueError, KeyError, TypeError):
            pass
        report = record.get("report", {})
        layers = report.get("layers", {})
        modules |= set(report.get("tested_modules", []))
        tests = (f"{layers.get('runtime', {}).get('tests', 0)} Odoo, "
                 f"{layers.get('system', {}).get('passed', 0)} e2e")
        rows.append(f"| {feat['id']} | {feat['behavior']} | "
                    f"{feat['evidence'].get('verified_at', '')[:10]} | {tests} |")
    lines = [f"Odoo task **{task}**: every feature below passed `odoo-harness feature verify` "
             "(static checks and pylint-odoo, Odoo tests, Playwright e2e on a fresh test "
             "database).", "", *rows, ""]
    if modules:
        lines.append(f"Modules tested: {', '.join(sorted(modules))}.")
    lines.append("Evidence: `harness/evidence/<feature>.json` in this branch.")
    return "\n".join(lines)


def merge_request(task, title=None):
    env = hlib.load_env()
    data = hlib.load_features()
    features = hlib.task_features(data, task)
    if not features:
        raise RedPen("features", f"no feature belongs to task {task}",
                     "A merge request ships the verified features of one Odoo task.",
                     f"Add them with odoo-harness feature add --task {task} ...")
    left = [f["id"] for f in features if f["state"] != "passing"]
    if left:
        raise RedPen("features", f"task {task} is not finished: {', '.join(left)} not passing",
                     "A merge request is opened only when every feature of the task is verified.",
                     f"Finish {left[0]}: odoo-harness feature verify {left[0]}")
    committed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "feature_list.json"],
                               cwd=hlib.REPO_ROOT).returncode == 0
    if not committed:
        raise RedPen("git", "the passing states are not committed",
                     "The merge request must contain the evidence it lists.",
                     "Commit the work, then run the command again.")
    push(task)
    base = env.get("BASE_BRANCH") or "staging"
    title = f"[{task}] {title or features[0]['behavior']}"
    body = description(task, features)
    existing = api(env, "GET", "/merge_requests?state=opened&source_branch="
                   + urllib.parse.quote(task))
    if existing:
        mr = api(env, "PUT", f"/merge_requests/{existing[0]['iid']}", {"description": body})
        print(f"✓ merge request updated: {mr.get('web_url')}")
    else:
        mr = api(env, "POST", "/merge_requests", {
            "source_branch": task, "target_branch": base, "title": title,
            "description": body, "remove_source_branch": True})
        print(f"✓ merge request opened: {mr.get('web_url')}")
    hlib.write_atomic(MR_DIR / f"{task}.json", json.dumps(
        {"task": task, "iid": mr.get("iid"), "url": mr.get("web_url"),
         "features": [f["id"] for f in features], "at": hlib.now_iso()}, indent=2) + "\n")
    return mr


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("push").add_argument("task")
    mr = sub.add_parser("mr")
    mr.add_argument("task")
    mr.add_argument("--title", help="merge request title after [TASK] (default: first feature)")
    args = p.parse_args(argv)
    try:
        if args.command == "push":
            push(args.task)
        else:
            merge_request(args.task, args.title)
    except RedPen as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
