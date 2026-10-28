#!/usr/bin/env python3
"""Stand-in for `docker compose` in tests: replays canned output, records calls.

Environment: FAKE_CALLS (file to append argv as JSON lines) and per command
FAKE_PYLINT_OUT, FAKE_ODOO_LOG / FAKE_ODOO_RC, FAKE_FRESH_LOG, FAKE_E2E_OUT /
FAKE_E2E_RC, FAKE_SERVER_LOG. In guide mode (--env=HARNESS_GUIDE_DIR=...) the e2e run
writes FAKE_GUIDE_STEPS (JSON list of captions, default two) like the harness_guide plugin;
`e2e python harness/guide_pdf.py HTML PDF` writes a fake PDF unless FAKE_PDF_RC is set.
"""

import json
import os
import sys
from pathlib import Path

DEFAULT_ODOO_LOG = ("2026-10-27 10:00:00,100 42 INFO harness_test odoo.tests.result: "
                    "0 failed, 0 error(s) of 3 tests when loading database 'harness_test'\n")

args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as fh:
    fh.write(json.dumps(args) + "\n")
args = args[args.index("--env-file") + 2:]
command = args[0]


def reply(text, rc=0):
    sys.stdout.write(text)
    sys.exit(rc)


if command == "run":
    service = [a for a in args[1:] if not a.startswith("-")][0]
    if service == "lint":
        out = os.environ.get("FAKE_PYLINT_OUT", "")
        reply(out, 16 if out else 0)
    if service == "odoo":
        if "-i" in args:
            reply(os.environ.get("FAKE_FRESH_LOG", ""))
        reply(os.environ.get("FAKE_ODOO_LOG", DEFAULT_ODOO_LOG),
              int(os.environ.get("FAKE_ODOO_RC", "0")))
    if service == "e2e":
        guide_dir = next((a.split("=", 2)[2] for a in args
                          if a.startswith("--env=HARNESS_GUIDE_DIR=")), None)
        if guide_dir:
            out = Path(guide_dir) / "test_F001_x__test_x"
            out.mkdir(parents=True, exist_ok=True)
            captions = json.loads(os.environ.get("FAKE_GUIDE_STEPS",
                                                 '["Ouvrir le menu", "Enregistrer"]'))
            steps = []
            for n, caption in enumerate(captions, 1):
                (out / f"{n:02d}.png").write_bytes(b"\x89PNG fake")
                steps.append({"caption": caption, "image": f"{n:02d}.png", "url": "/odoo"})
            (out / "steps.json").write_text(json.dumps(
                {"test": "e2e/test_F001_x.py::test_x", "steps": steps}))
        if "harness/guide_pdf.py" in args:
            rc = int(os.environ.get("FAKE_PDF_RC", "0"))
            if not rc:
                Path(args[-1]).write_bytes(b"%PDF-1.4 fake\n" + Path(args[-2]).read_bytes())
            reply("", rc)
        reply(os.environ.get("FAKE_E2E_OUT", "1 passed in 1.23s\n"),
              int(os.environ.get("FAKE_E2E_RC", "0")))
if command == "logs":
    reply(os.environ.get("FAKE_SERVER_LOG", ""))
reply("")
