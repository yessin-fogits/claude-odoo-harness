#!/usr/bin/env python3
"""Stop: automatic session end. Runs each time the agent finishes a turn.

1. Writes the current state (last commit, test status, lint, working tree, feature
   in progress) to .harness/current-state.md: it is this checkout's, never versioned.
2. Blocks the stop, with red-pen instructions, when the session would leave an
   unclean state:
   - layer-1 static checks fail (syntax, XML, manifest, debug leftovers, ...);
   - the feature list fails its integrity check;
   - this session changed module or e2e code but wrote no progress notes (the
     task's tasks/<task>.md, or PROGRESS.md off a task branch).
If the agent was already blocked once and the problems remain, the stop is let
through and the problems are recorded under "Known issues" of those notes for the
next session (no infinite loop).
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def test_status(root):
    report = c.load_json(root / ".harness" / "last-verify.json", None)
    if not report:
        return "not run yet (odoo-harness verify or odoo-harness feature verify)"
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


def current_feature(view, error):
    if view is None:
        return f"unreadable task files ({error.splitlines()[0] if error else '?'})"
    here = [f for f in view["features"] if f["id"] in view["here"]]
    return f"{here[0]['id']} {here[0]['behavior']}" if here else "none"


def session_changes(root, session):
    """Files changed since the session started (committed or not), minus those that were
    already changed, and are unchanged, from before it."""
    names = set()
    start = session.get("start_commit")
    if start:
        names |= set(c.git(root, "diff", "--name-only", start).splitlines())
    names |= set(c.git(root, "diff", "--name-only", "HEAD").splitlines())
    names |= set(c.git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    names |= c.changed_submodules(root)
    before = session.get("dirty_at_start") or {}
    if before and names:
        now = c.dirty_files(root)
        # unchanged since the session started: changed by someone else before it
        names = {n for n in names if not (n in before and now.get(n) == before[n])}
    return names


def session_changed_code(env, names):
    """Files under the custom or third-party addons or e2e/ among the session's changes. A
    submodule shows as its path: one that is, or is under, an addons folder is code."""
    roots = c.custom_roots(env) + c.env_paths(env, "THIRD_PARTY_ADDONS")
    prefixes = tuple(r + "/" for r in roots) + ("e2e/",)
    return sorted(n for n in names if (n + "/").startswith(prefixes))


def notes_changed(names):
    """The session wrote progress notes: a task's notes or PROGRESS.md."""
    return any(n == "PROGRESS.md" or (n.startswith("tasks/") and n.endswith(".md"))
               for n in names)


def main():
    payload = c.read_input()
    root = c.project_dir(payload)
    if not c.active(root):
        sys.exit(0)
    env = c.load_env(root)

    static_rc, static_out = c.run(root, c.engine("static_checks.py"), timeout=60)
    static_count = static_out.count("\n✗ [") + static_out.startswith("✗ [")
    check_rc, check_out = c.run(root, c.engine("feature.py", "check"), timeout=30)
    view, view_error = c.features(root)

    dirty = [ln for ln in c.git(root, "status", "--porcelain").splitlines() if ln.strip()]
    last_commit = c.git(root, "log", "-1", "--format=%h %s (%cr)") or "(none yet)"
    # Machine-local, so never in a tracked file: each developer's checkout has its own.
    state_lines = [
        f"- Last commit: {last_commit}",
        f"- Working tree: {'clean' if not dirty else f'{len(dirty)} uncommitted change(s)'}",
        f"- Test status: {test_status(root)}",
        f"- Lint: {lint_status(root, static_rc == 0, static_count)}",
        f"- Feature in progress: {current_feature(view, view_error)}",
    ]
    (c.state_dir(root) / "current-state.md").write_text("\n".join(state_lines) + "\n")

    problems = []
    if static_rc != 0:
        problems.append(static_out)
    if check_rc != 0:
        problems.append(check_out)
    task = c.current_task(root, view)
    notes = c.notes_path(root, task)
    session = c.load_json(root / ".harness" / "session.json", {})
    if session:
        names = session_changes(root, session)
        changed = session_changed_code(env, names)
        if changed and not notes_changed(names):
            listed = ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else "")
            where = f"tasks/{task}.md" if task else "PROGRESS.md"
            problems.append(c.redpen(
                "session end", f"code changed this session but {where} was not updated",
                f"The next session starts from the notes only; it would not know about: {listed}",
                f"Update {where}: what is done and what is left, Known issues, Next steps. "
                "Commit finished work."))

    if problems and payload.get("stop_hook_active"):
        today = datetime.date.today().isoformat()
        summary = "; ".join(p.splitlines()[0].lstrip("✗ ").strip() for p in problems)
        note = f"- {today}: session ended with an unclean state: {summary}"
        text = notes.read_text() if notes.is_file() else f"# Task {task}\n" if task else "# Progress\n"
        if note not in text:
            notes.write_text(c.replace_section(
                text, "Known issues",
                [ln for ln in c.section_text(text, "Known issues").splitlines() if ln.strip()]
                + [note]))
        problems = []

    if problems:
        c.emit({"decision": "block",
                "reason": "The harness found an unclean state. Fix it before ending:\n\n"
                          + "\n\n".join(problems)})
    sys.exit(0)


if __name__ == "__main__":
    main()
