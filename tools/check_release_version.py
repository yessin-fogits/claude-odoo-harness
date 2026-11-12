#!/usr/bin/env python3
"""Fail when a change ships to users without raising the plugin version.

    tools/check_release_version.py BASE_REF

The version of the odoo-harness entry in .claude-plugin/marketplace.json is what Claude
Code and the desktop app compare to offer an update: a merge that keeps it reaches no one.
Every file of the repository ships in the plugin, except the ones only developers of the
harness read (EXEMPT). When the changes since BASE_REF touch a shipped file, the version
must be higher than on BASE_REF.
"""

import json
import subprocess
import sys

MARKETPLACE = ".claude-plugin/marketplace.json"
EXEMPT_DIRS = ("tests/", "docs/", "tools/", ".github/")
EXEMPT_FILES = {"README.md", "README.fr.md", "DECISIONS.md", "PROGRESS.md", "pytest.ini",
                ".gitignore", ".gitattributes"}


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def plugin_version(text):
    market = json.loads(text)
    entry = next(p for p in market["plugins"] if p["name"] == "odoo-harness")
    return entry.get("version", "")


def version_tuple(version):
    return tuple(int(p) for p in version.split("."))


def shipped(path):
    return not path.startswith(EXEMPT_DIRS) and path not in EXEMPT_FILES


def main(base):
    changed = [p for p in git("diff", "--name-only", f"{base}...HEAD").splitlines() if shipped(p)]
    if not changed:
        print("No shipped file changed: no new plugin version needed.")
        return 0
    head = plugin_version(open(MARKETPLACE).read())
    try:
        before = plugin_version(git("show", f"{base}:{MARKETPLACE}"))
    except subprocess.CalledProcessError:
        before = ""
    if before and version_tuple(head) <= version_tuple(before):
        print(f"These files ship in the plugin, but its version stays {head} (base {before}):")
        print("".join(f"  {p}\n" for p in changed), end="")
        print(f"WHY: users get a change only when the version in {MARKETPLACE} goes up.")
        print(f"HOW TO FIX: raise \"version\" of the odoo-harness entry in {MARKETPLACE}.")
        return 1
    print(f"Plugin version {before or '(none)'} -> {head}.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
