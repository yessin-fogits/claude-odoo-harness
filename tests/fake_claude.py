#!/usr/bin/env python3
"""Stand-in for `claude -p` in loop tests.

Maker (no --agent): FAKE_MAKER = fix | break | break-then-fix | none.
Reviewer (--agent): FAKE_REVIEWS = comma-separated verdicts returned in order.
Every call is appended to FAKE_AGENT_CALLS as JSON.
"""

import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
calls = Path(os.environ["FAKE_AGENT_CALLS"])
history = calls.read_text().splitlines() if calls.exists() else []
with calls.open("a") as fh:
    fh.write(json.dumps(args) + "\n")

if "--agent" in args:
    verdicts = os.environ.get("FAKE_REVIEWS", "Accept").split(",")
    n = sum(1 for line in history if "--agent" in json.loads(line))
    verdict = verdicts[min(n, len(verdicts) - 1)]
    print(json.dumps({"result": f"### Verdict\n{verdict}: reviewed.\n\n### Findings\nnone"}))
    sys.exit(0)

thing = Path("addons/demo_mod/models/thing.py")
mode = os.environ.get("FAKE_MAKER", "fix")
broken = mode == "break" or (mode == "break-then-fix" and "Attempt 1 of" in prompt)
if mode != "none":
    if broken:
        thing.write_text(thing.read_text() + "\ndef broken(:\n")
    else:
        text = thing.read_text().replace("\ndef broken(:\n", "")
        thing.write_text(text + "\n# implemented by the maker\n")
    progress = Path("PROGRESS.md")
    progress.write_text(progress.read_text() + "\n- maker note\n")
print(json.dumps({"result": "done"}))
