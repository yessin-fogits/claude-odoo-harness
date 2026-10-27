"""Project check: <the kind of mistake this check catches, one line>.

Found in the review of <feature id>, <YYYY-MM-DD>.
"""

import re

ID = "<kebab-case-id>"
WHY = "<why it is wrong: the consequence for users or data>"
FIX = "<what to write instead, concrete>"

PATTERN = re.compile(r"<regex that matches the mistake on one line>")
SUFFIXES = {".py"}


def detect(files):
    """Return (path, line, detail) for each occurrence. `files` are pathlib.Path objects."""
    found = []
    for path in files:
        if path.suffix not in SUFFIXES:
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            if PATTERN.search(line):
                found.append((path, lineno, line.strip()))
    return found
