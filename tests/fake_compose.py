#!/usr/bin/env python3
"""Stand-in for `docker compose` in tests: replays canned output, records calls.

Environment: FAKE_CALLS (file to append argv as JSON lines) and per command
FAKE_PYLINT_OUT, FAKE_ODOO_LOG / FAKE_ODOO_RC, FAKE_FRESH_LOG, FAKE_E2E_OUT /
FAKE_E2E_RC, FAKE_SERVER_LOG.
"""

import json
import os
import sys

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
        reply(os.environ.get("FAKE_E2E_OUT", "1 passed in 1.23s\n"),
              int(os.environ.get("FAKE_E2E_RC", "0")))
if command == "logs":
    reply(os.environ.get("FAKE_SERVER_LOG", ""))
reply("")
