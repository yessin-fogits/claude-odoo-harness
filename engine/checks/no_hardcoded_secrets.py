"""Project check: secrets written in tracked files.

Born from the first project discovery: a GitHub token was committed in the URL of a
`git clone` in a dev launcher script, in every project built from the same template.
The finding never prints the secret itself.
"""

import re

ID = "no-hardcoded-secrets"
WHY = ("Anyone who can read the repository (or a leaked copy of it) can use this secret; "
       "git keeps it in the history even after the line is removed.")
FIX = ("Revoke the secret where it was issued, then read it from the environment or a "
       "git-ignored .env file (e.g. os.environ['GITHUB_TOKEN'], ${GITHUB_TOKEN}); never "
       "commit the value.")

PATTERNS = [
    ("GitHub token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_\w{30,}")),
    ("GitLab token", re.compile(r"\bglpat-[\w-]{20,}")),
    ("credentials in a URL", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:[^/\s@'\"$]{6,}@")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]
# Odoo master password in a tracked config: allowed only when it is the harness dev value.
ADMIN_PASSWD = re.compile(r"^\s*admin_passwd\s*=\s*(\S+)")
SKIPPED_SUFFIXES = {".po", ".pot", ".svg", ".png", ".jpg", ".pdf", ".min.js"}


def detect(files):
    found = []
    for path in files:
        if path.suffix in SKIPPED_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in PATTERNS:
                if pattern.search(line):
                    found.append((path, lineno, f"{kind} written in the file (value not shown)"))
                    break
            else:
                match = ADMIN_PASSWD.match(line)
                if (match and path.suffix == ".conf"
                        and match.group(1) not in ("harness-dev-only", "False", "admin")):
                    found.append((path, lineno, "Odoo admin_passwd written in a tracked config "
                                  "(value not shown)",
                                  "The master password lets anyone create, drop or restore "
                                  "databases on that server.",
                                  "Set admin_passwd on the server (environment, secret mount) "
                                  "and keep a placeholder in the tracked config."))
    return found
