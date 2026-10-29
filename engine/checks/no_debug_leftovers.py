"""Project check: debugging leftovers in module code.

A project check is one Python file in harness/checks/ with ID, WHY, FIX and
detect(files) -> [(path, line, detail)]. Add one each time a code review finds a
new kind of agent mistake, and log it in DECISIONS.md.
"""

import re

ID = "no-debug-leftovers"
WHY = "Debugging statements left in the code stop the server or leak noise in production."
FIX = "Remove the statement. Use _logger.debug() in Python if the information is worth keeping."

PATTERNS = {
    ".py": re.compile(r"^\s*(import i?pdb\b|from i?pdb import|.*\b(i?pdb\.set_trace|breakpoint)\s*\()"),
    ".js": re.compile(r"^\s*(debugger\s*;?|console\.log\s*\()"),
}


def detect(files):
    found = []
    for path in files:
        pattern = PATTERNS.get(path.suffix)
        if not pattern:
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            if pattern.match(line):
                found.append((path, lineno, f"debug statement: {line.strip()}"))
    return found
