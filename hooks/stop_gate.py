#!/usr/bin/env python3
"""Stop: automatic session end. Runs each time the agent finishes a turn.

1. Rewrites the "## Current state" section of PROGRESS.md (last commit, test
   status, lint, working tree, feature in progress).
2. Blocks the stop, with red-pen instructions, when the session would leave an
   unclean state:
   - layer-1 static checks fail (syntax, XML, manifest, debug leftovers, ...);
   - the feature list fails its integrity check;
   - this session changed module or e2e code but PROGRESS.md was not updated.
If the agent was already blocked once and the problems remain, the stop is let
through and the problems are recorded in PROGRESS.md "Known issues" for the next
session (no infinite loop).
"""

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

AUTO_NOTE = "<!-- Rewritten automatically by the harness at the end of each session. -->"


def test_status(root):
    report = c.load_json(root / ".harness" / "last-verify.json", None)
    if not report:
        return "not run yet (harness/verify.sh or harness/feature.py verify)"
    layers = report.get("layers", {})
    details = []
    for name in ("static", "runtime", "system"):
        layer = layers.get(name)
        if not layer:
            continue
        extra = ""
        if name == "runtime" and "tests" in layer:
            extra = f", {layer['tests']} tests"
        if name == "system" and "passed" in layer:
            extra = f", {layer['passed']} e2e{' full suite' if layer.get('full_suite') else ''}"
        details.append(f"{name} {layer.get('status')}{extra}")
    who = report.get("feature") or "baseline"
    when = report.get("finished_at", "?")
    return f"{report.get('result', '?')} ({who}, {when}): {'; '.join(details) or 'no layer ran'}"


def lint_status(root, static_ok, static_count):
    report = c.load_json(root / ".harness" / "last-verify.json", None) or {}
    static = report.get("layers", {}).get("static") or {}
    pylint = ("not run yet" if not static else
              "clean at last verify" if not static.get("lint_messages") else
              f"{static['lint_messages']} message(s) at last verify")
    now = "clean" if static_ok else f"{static_count} finding(s)"
    return f"static checks {now} (now); pylint-odoo {pylint}"


def current_feature(root):
    try:
        feats = json.loads((root / "feature_list.json").read_text())["features"]
    except (OSError, ValueError, KeyError, TypeError):
        return "unreadable feature_list.json"
    current = [f for f in feats if f.get("state") == "in_progress"]
    return f"{current[0]['id']} {current[0]['behavior']}" if current else "none"


def session_changed_code(root, env, session):
    """Files under the addons dir or e2e/ changed since the session started."""
    names = set()
    start = session.get("start_commit")
    if start:
        names |= set(c.git(root, "diff", "--name-only", start).splitlines())
    names |= set(c.git(root, "diff", "--name-only", "HEAD").splitlines())
    names |= set(c.git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    addons = env.get("ADDONS_DIR", "addons").rstrip("/") + "/"
    code = {n for n in names if n.startswith(addons) or n.startswith("e2e/")}
    before = session.get("dirty_at_start") or {}
    if before and code:
        now = c.dirty_files(root)
        # unchanged since the session started: changed by someone else before it
        code = {n for n in code if not (n in before and now.get(n) == before[n])}
    return sorted(code)


def main():
    payload = c.read_input()
    root = c.project_dir(payload)
    if not c.has_harness(root):
        sys.exit(0)
    env = c.load_env(root)
    progress_path = root / "PROGRESS.md"
    progress = progress_path.read_text() if progress_path.is_file() else "# Progress\n"

    static_rc, static_out = c.run(root, [sys.executable, "harness/static_checks.py"], timeout=60)
    static_count = static_out.count("\n✗ [") + static_out.startswith("✗ [")
    check_rc, check_out = c.run(root, [sys.executable, "harness/feature.py", "check"], timeout=30)

    dirty = [ln for ln in c.git(root, "status", "--porcelain").splitlines() if ln.strip()]
    last_commit = c.git(root, "log", "-1", "--format=%h %s (%cr)") or "(none yet)"
    state_lines = [
        AUTO_NOTE,
        f"- Last commit: {last_commit}",
        f"- Working tree: {'clean' if not dirty else f'{len(dirty)} uncommitted change(s)'}",
        f"- Test status: {test_status(root)}",
        f"- Lint: {lint_status(root, static_rc == 0, static_count)}",
        f"- Feature in progress: {current_feature(root)}",
    ]

    problems = []
    if static_rc != 0:
        problems.append(static_out)
    if check_rc != 0:
        problems.append(check_out)
    session = c.load_json(root / ".harness" / "session.json", {})
    if session.get("progress_body") is not None:
        changed = session_changed_code(root, env, session)
        if changed and c.body_without(progress, "Current state") == session["progress_body"]:
            listed = ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else "")
            problems.append(c.redpen(
                "session end", "code changed this session but PROGRESS.md was not updated",
                f"The next session starts from PROGRESS.md only; it would not know about: {listed}",
                "Update PROGRESS.md: the feature line in 'In progress' (what is done, what is "
                "left), 'Known issues', 'Next steps'. Commit finished work."))

    if problems and payload.get("stop_hook_active"):
        today = datetime.date.today().isoformat()
        summary = "; ".join(p.splitlines()[0].lstrip("✗ ").strip() for p in problems)
        note = f"- {today}: session ended with an unclean state: {summary}"
        if note not in progress:
            progress = c.replace_section(
                progress, "Known issues",
                [ln for ln in c.section_text(progress, "Known issues").splitlines() if ln.strip()]
                + [note])
        problems = []

    new = c.replace_section(progress, "Current state", state_lines)
    if new != progress or not progress_path.is_file():
        progress_path.write_text(new)

    if problems:
        c.emit({"decision": "block",
                "reason": "The harness found an unclean state. Fix it before ending:\n\n"
                          + "\n\n".join(problems)})
    sys.exit(0)


if __name__ == "__main__":
    main()
