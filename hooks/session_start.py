#!/usr/bin/env python3
"""SessionStart: load the harness state into the context, automatically.

Injects the PROGRESS.md state, the recent decisions, the current feature and the
baseline health, and records a snapshot that the Stop gate compares against.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

MAX_DECISIONS = 10


def feature_summary(root):
    try:
        data = json.loads((root / "feature_list.json").read_text())
        feats = data["features"]
    except (OSError, ValueError, KeyError, TypeError):
        return ["feature_list.json is unreadable. Restore it with `git checkout feature_list.json`."]
    counts = {}
    for f in feats:
        counts[f.get("state")] = counts.get(f.get("state"), 0) + 1
    lines = ["Features: " + (", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "none yet")]
    current = [f for f in feats if f.get("state") == "in_progress"]
    if current:
        f = current[0]
        lines.append(f"Feature in progress: {f['id']} — {f['behavior']}")
        lines += [f"  verification: {v}" for v in f.get("verification", [])]
        lines.append(f"It becomes passing only through `harness/feature.py verify {f['id']}`.")
    else:
        todo = [f for f in feats if f.get("state") == "not_started"]
        if todo:
            lines.append(f"No feature in progress. Next by order: {todo[0]['id']} — "
                         f"{todo[0]['behavior']} (`harness/feature.py start {todo[0]['id']}`).")
        elif not feats:
            lines.append("The feature list is empty: initialization step 4 (task breakdown) "
                         "is not done.")
    return lines


def unchecked_bootstrap(root):
    path = root / "BOOTSTRAP.md"
    if not path.is_file():
        return []
    ready = c.section_text(path.read_text(), "Ready means")
    return [ln.strip() for ln in ready.splitlines() if "[ ]" in ln]


def init_command(root):
    major = c.load_env(root).get("ODOO_VERSION", "").split(".")[0] or "<version>"
    return f"/odoo-harness-{major}:init"


def recent_decisions(root):
    path = root / "DECISIONS.md"
    if not path.is_file():
        return []
    return [ln for ln in path.read_text().splitlines() if ln.startswith("- ")][-MAX_DECISIONS:]


def main():
    payload = c.read_input()
    root = c.project_dir(payload)
    if not c.has_harness(root):
        sys.exit(0)

    parts = ["# odoo-harness session context (loaded automatically)"]

    progress = (root / "PROGRESS.md").read_text() if (root / "PROGRESS.md").is_file() else ""
    for name in ("Current state", "In progress", "Known issues", "Next steps"):
        body = c.section_text(progress, name)
        parts.append(f"## PROGRESS.md: {name}\n{body or '(empty)'}")

    parts.append("## Features\n" + "\n".join(feature_summary(root)))

    rc, out = c.run(root, [sys.executable, "harness/feature.py", "check"], timeout=30)
    if rc != 0:
        parts.append("## Feature list integrity: FAILED\n" + out)

    decisions = recent_decisions(root)
    if decisions:
        parts.append(f"## Last {len(decisions)} decisions (DECISIONS.md)\n" + "\n".join(decisions))

    pending = unchecked_bootstrap(root)
    if pending:
        parts.append("## Initialization incomplete (BOOTSTRAP.md, Ready means)\n"
                     + "\n".join(pending)
                     + "\nFeature work starts only after these are done "
                     f"({init_command(root)}).")

    rc, out = c.run(root, ["bash", "harness/init.sh", "--check"], timeout=60)
    if rc == 0:
        parts.append("## Baseline health\n" + out)
    else:
        parts.append("## Baseline health: FAILED\n" + out + "\nPer the Work Rules, the baseline "
                     "is fixed first: run `harness/init.sh` and follow its HOW TO FIX lines.")

    session_file = c.state_dir(root) / "session.json"
    previous = c.load_json(session_file, {})
    same_session = (payload.get("source") in ("compact", "resume")
                    and previous.get("session_id") == payload.get("session_id"))
    if not same_session:
        c.write_json(session_file, {
            "session_id": payload.get("session_id"),
            "source": payload.get("source"),
            "start_commit": c.git(root, "rev-parse", "HEAD") or None,
            "progress_body": c.body_without(progress, "Current state"),
            # files already changed before this session: not this session's work
            "dirty_at_start": c.dirty_files(root),
        })

    c.emit({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                   "additionalContext": "\n\n".join(parts)}})


if __name__ == "__main__":
    main()
