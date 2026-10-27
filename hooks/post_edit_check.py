#!/usr/bin/env python3
"""PostToolUse: fast layer-1 checks on the file that was just edited.

Runs the project's harness/static_checks.py on that one file (syntax, XML,
manifest, security CSV, project checks) and hands red-pen findings back to the
agent right away, instead of at verify time.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

CHECKED_SUFFIXES = {".py", ".xml", ".csv", ".js"}


def main():
    payload = c.read_input()
    root = c.project_dir(payload)
    if not c.has_harness(root):
        sys.exit(0)
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path")
    if not path:
        sys.exit(0)
    path = Path(path) if Path(path).is_absolute() else root / path
    addons = (root / c.load_env(root).get("ADDONS_DIR", "addons")).resolve()
    try:
        path.resolve().relative_to(addons)
    except ValueError:
        sys.exit(0)
    if path.suffix not in CHECKED_SUFFIXES or not path.is_file():
        sys.exit(0)
    rc, out = c.run(root, [sys.executable, "harness/static_checks.py", str(path)], timeout=30)
    if rc != 0:
        c.emit({"decision": "block",
                "reason": f"{out}\n\nFix this before continuing; harness/feature.py verify "
                          "will fail on it at layer 1 anyway."})
    sys.exit(0)


if __name__ == "__main__":
    main()
