#!/usr/bin/env python3
"""PreToolUse guard: the harness, not the agent, owns feature state and real data.

Denies (with a red-pen reason):
  - Edit/Write of feature_list.json and harness/evidence/ (use harness/feature.py)
  - edits of Odoo core / enterprise code (extend in custom modules instead)
  - Bash commands that write those files, drop or target a non-test database,
    delete docker volumes, or skip git hooks with --no-verify
"""

import ast
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
STATE_PATHS = ("feature_list.json", "harness/evidence")
READ_ONLY_PREFIXES = ("harness/feature.py", "./harness/feature.py", "python3 harness/feature.py",
                      "python harness/feature.py", "cat ", "head ", "tail ", "less ", "grep ",
                      "jq ", "ls ", "wc ", "diff ", "git ")
OPERATORS = {"&&", "||", ";", "|", "&", ";;", "(", ")", "|&"}


def deny(what, why, fix):
    c.emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": c.redpen("guard", what, why, fix)}})


def rel_to(root, path):
    try:
        return Path(path).resolve().relative_to(root)
    except ValueError:
        return None


def check_state_file(rel):
    posix = rel.as_posix()
    if posix == "feature_list.json":
        deny("direct edit of feature_list.json",
             "The harness owns feature states; an agent cannot mark its own work passing.",
             "Use harness/feature.py: add | start | block | verify (verify is the only way to "
             "passing).")
    if posix.startswith("harness/evidence/"):
        deny(f"direct edit of {posix}",
             "Evidence is written only by `harness/feature.py verify` after the 3 layers pass.",
             "Run `harness/feature.py verify <id>`.")


def is_core_module(module_dir):
    try:
        manifest = ast.literal_eval((module_dir / "__manifest__.py").read_text())
    except (OSError, ValueError, SyntaxError):
        return False
    author = str(manifest.get("author", ""))
    return "Odoo S.A." in author or str(manifest.get("license", "")).startswith("OEEL")


def check_core(root, env, rel):
    for prefix in filter(None, (p.strip().rstrip("/") for p in
                                env.get("PROTECTED_PATHS", "").split(","))):
        if rel.as_posix() == prefix or rel.as_posix().startswith(prefix + "/"):
            deny(f"{rel} is in a protected path ({prefix})",
                 "BOOTSTRAP.md lists this path as off-limits.",
                 "Make the change in a custom module of the project instead.")
    parent = (root / rel).parent
    while parent != root and root in parent.parents:
        if (parent / "odoo-bin").is_file():
            deny(f"{rel} is Odoo core source",
                 "Odoo core is never edited: changes are lost on upgrade and break support.",
                 "Extend the behavior by inheritance (_inherit, xpath views) in a custom module.")
        if (parent / "__manifest__.py").is_file() and is_core_module(parent):
            deny(f"{rel} belongs to an Odoo S.A. module ({parent.name})",
                 "Odoo core and enterprise modules are never edited.",
                 f"Create or use a custom module that depends on '{parent.name}' and inherit "
                 "from it.")
        parent = parent.parent


def check_file_tool(root, env, tool_input):
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        return
    rel = rel_to(root, path if Path(path).is_absolute() else root / path)
    if rel is None:
        return
    check_state_file(rel)
    check_core(root, env, rel)


def allowed_dbs(env):
    test_db = env.get("TEST_DB", "harness_test")
    return {test_db, f"{test_db}_fresh"}


def shell_segments(command):
    """Split a command into simple commands (token lists), honoring quotes.

    Returns None when the command cannot be parsed (unbalanced quotes...)."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments, current = [], []
    for token in tokens:
        if token in OPERATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def check_state_commands(command):
    if not any(p in command for p in STATE_PATHS):
        return
    segments = shell_segments(command)
    if segments is None:
        deny("cannot parse a command that mentions harness state",
             "Commands touching feature_list.json or harness/evidence/ must be clearly read-only.",
             "Use harness/feature.py, or a plain read such as `cat feature_list.json`.")
    for tokens in segments:
        touches = [t for t in tokens if any(p in t for p in STATE_PATHS)]
        if not touches:
            continue
        for i, token in enumerate(tokens[:-1]):
            if token.endswith(">") and any(p in tokens[i + 1] for p in STATE_PATHS):
                deny("shell redirection into feature_list.json or harness/evidence/",
                     "The harness owns feature states and evidence.", "Use harness/feature.py.")
        text = " ".join(tokens)
        in_place = tokens[0] in ("sed", "perl") and any(t.startswith("-i") for t in tokens)
        if tokens[0] == "tee" or in_place or not text.startswith(READ_ONLY_PREFIXES):
            deny(f"command may modify harness state: {text[:120]}",
                 "Only harness/feature.py changes feature_list.json and harness/evidence/.",
                 "Use harness/feature.py add | start | block | verify. Reading the files with "
                 "cat/jq/git is fine.")


def check_bash(env, command):
    check_state_commands(command)
    dbs = allowed_dbs(env)
    targets = []
    for match in re.finditer(r"\bdropdb\b([^;&|\n]*)", command):
        names = [t for t in match.group(1).split() if not t.startswith("-")]
        targets += names[-1:] or ["<unknown>"]
    targets += re.findall(r"drop\s+database\s+(?:if\s+exists\s+)?[\"'`]?([\w-]+)", command, re.I)
    targets += re.findall(r"\bodoo(?:-bin)?\b[^;&|\n]*?(?:\s-d\s*|--database[ =])([\w-]+)",
                          command)
    for name in targets:
        if name not in dbs:
            deny(f"command targets database '{name}', not the test DB",
                 "The harness only works on the disposable test DB; other databases may hold "
                 "real data.",
                 f"Use the test DB '{env.get('TEST_DB', 'harness_test')}' (harness/init.sh "
                 "--reset recreates it). A human handles any other database.")
    if re.search(r"docker[\s-]+compose\b[^;&|\n]*\bdown\b[^;&|\n]*(\s-v\b|--volumes)", command) \
            or re.search(r"docker\s+volume\s+(rm|prune)\b", command):
        deny("command deletes docker volumes",
             "Volumes hold the databases and filestore; deleting them is not reversible.",
             "To start from a clean test DB use `harness/init.sh --reset`.")
    if re.search(r"\bgit\b[^;&|\n]*\bcommit\b[^;&|\n]*--no-verify", command):
        deny("git commit --no-verify",
             "Pre-commit runs the feature list integrity check and the static checks.",
             "Commit without --no-verify and fix what the hooks report.")


def main():
    payload = c.read_input()
    root = c.project_dir(payload)
    if not c.has_harness(root):
        sys.exit(0)
    env = c.load_env(root)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if tool in FILE_TOOLS:
        check_file_tool(root, env, tool_input)
    elif tool == "Bash":
        check_bash(env, tool_input.get("command", ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
