#!/usr/bin/env python3
"""PreToolUse guard: the harness, not the agent, owns feature state and real data.

Denies (with a red-pen reason):
  - Edit/Write of tasks/<task>.json and harness/evidence/ (use `odoo-harness feature`);
    the task notes, tasks/<task>.md, stay the agent's
  - Edit/Write of the harness engine (this plugin, ~/.odoo-harness/): the judge is not
    rewritten by the agent it judges
  - edits of Odoo core / enterprise code, of the Enterprise checkout (ENTERPRISE_DIR) and
    of PROTECTED_PATHS (deployment files): extend in custom modules instead, a human
    changes deployment files
  - Bash commands that write those files, drop any database but the test DB, run Odoo on a
    database that is neither the test DB nor the dev DB (DEV_DB), delete docker volumes,
    skip git hooks with --no-verify, or push to the base branch or main (task branches are
    pushed by `odoo-harness gitlab`)
"""

import ast
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Feature states (tasks/<task>.json; feature_list.json before engine 3.0) and evidence. The
# task notes, tasks/<task>.md, are the agent's to write.
STATE_RE = re.compile(r"feature_list\.json|harness/evidence|(?<![\w.-])tasks/[^/\s]*\.json")


def mentions_state(text):
    return bool(STATE_RE.search(text))
READ_ONLY_PREFIXES = ("odoo-harness feature ", "cat ", "head ", "tail ", "less ", "grep ",
                      "jq ", "ls ", "wc ", "diff ", "git ")
HARNESS_HOME = Path(os.environ.get("ODOO_HARNESS_HOME") or Path.home() / ".odoo-harness")
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
    if posix == "feature_list.json" or re.fullmatch(r"tasks/[^/]+\.json", posix):
        deny(f"direct edit of {posix}",
             "The harness owns feature states; an agent cannot mark its own work passing.",
             "Use odoo-harness feature: add | start | block | verify (verify is the only way to "
             "passing).")
    if posix.startswith("harness/evidence/"):
        deny(f"direct edit of {posix}",
             "Evidence is written only by `odoo-harness feature verify` after the 3 layers pass.",
             "Run `odoo-harness feature verify <id>`.")


def is_core_module(module_dir):
    try:
        manifest = ast.literal_eval((module_dir / "__manifest__.py").read_text())
    except (OSError, ValueError, SyntaxError):
        return False
    author = str(manifest.get("author", ""))
    return "Odoo S.A." in author or str(manifest.get("license", "")).startswith("OEEL")


def under(rel, prefix):
    return rel.as_posix() == prefix or rel.as_posix().startswith(prefix + "/")


def check_core(root, env, rel):
    for prefix in c.env_paths(env, "PROTECTED_PATHS"):
        if under(rel, prefix):
            deny(f"{rel} is in a protected path ({prefix})",
                 "Deployment files (images, compose files, server configs, CI) are shared with "
                 "staging and production; BOOTSTRAP.md lists them as off-limits.",
                 "Make the change in a custom module. If the deployment itself must change "
                 "(a new Python dependency, a config option), tell the user what to change and "
                 "why; a human edits these files.")
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


def check_engine(path):
    for folder in (c.PLUGIN_ROOT, HARNESS_HOME):
        try:
            path.resolve().relative_to(folder.resolve())
        except (ValueError, OSError):
            continue
        deny(f"{path} is part of the harness engine",
             "The engine judges the work (verification, feature states): the agent it judges "
             "cannot change it. It is the plugin's, shared by every project on this machine.",
             "Fix the project instead. If the harness itself is wrong, tell the user; project "
             "rules go in harness/checks/ and harness/errors_project.py.")


def check_file_tool(root, env, payload, tool_input):
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        return
    path = c.tool_path(payload, path)
    check_engine(path)
    enterprise = env.get("ENTERPRISE_DIR", "").strip().rstrip("/")
    if enterprise:
        try:
            path.resolve().relative_to((root / enterprise).resolve())
            deny(f"{path} is Odoo Enterprise source ({enterprise})",
                 "Odoo Enterprise is never edited: changes are lost on upgrade and break support.",
                 "Extend the behavior by inheritance in a custom module.")
        except ValueError:
            pass
    rel = rel_to(root, path)
    if rel is None:
        return
    check_state_file(rel)
    check_core(root, env, rel)


def droppable_dbs(env):
    test_db = env.get("TEST_DB", "harness_test")
    return {test_db, f"{test_db}_fresh"}


def odoo_dbs(env):
    """Databases Odoo may run on: the test DBs, and the dev DB (updated, never dropped)."""
    dev_db = env.get("DEV_DB", "").strip()
    return droppable_dbs(env) | ({dev_db} if dev_db else set())


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


def normalize_feature_cli(tokens):
    """The feature command however it is spelled reads as `odoo-harness feature`: through a
    path to the command (~/.local/bin/odoo-harness), or the engine script itself."""
    out = list(tokens)
    if out and out[0].endswith("/odoo-harness"):
        out[0] = "odoo-harness"
    if len(out) > 1 and out[0] in ("python", "python3") and out[1].endswith("/engine/feature.py"):
        out = ["odoo-harness", "feature", *out[2:]]
    return out


def git_subcommand(segment):
    """(subcommand, its arguments) of a git command, skipping -C <dir>, -c <k=v>, --git-dir=..."""
    if segment[:1] != ["git"]:
        return None, []
    i = 1
    while i < len(segment) and segment[i].startswith("-"):
        i += 2 if segment[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    return (segment[i], segment[i + 1:]) if i < len(segment) else (None, [])


def check_state_commands(command):
    if not mentions_state(command):
        return
    segments = shell_segments(command)
    if segments is None:
        deny("cannot parse a command that mentions harness state",
             "Commands touching tasks/*.json or harness/evidence/ must be clearly read-only.",
             "Use odoo-harness feature, or a plain read such as `cat tasks/T2003.json`.")
    for tokens in segments:
        touches = [t for t in tokens if mentions_state(t)]
        if not touches:
            continue
        for i, token in enumerate(tokens[:-1]):
            if token.endswith(">") and mentions_state(tokens[i + 1]):
                deny("shell redirection into tasks/*.json or harness/evidence/",
                     "The harness owns feature states and evidence.", "Use odoo-harness feature.")
        text = " ".join(normalize_feature_cli(tokens)) + " "
        in_place = tokens[0] in ("sed", "perl") and any(t.startswith("-i") for t in tokens)
        if tokens[0] == "tee" or in_place or not text.startswith(READ_ONLY_PREFIXES):
            deny(f"command may modify harness state: {text[:120]}",
                 "Only odoo-harness feature changes tasks/*.json and harness/evidence/.",
                 "Use odoo-harness feature add | start | block | verify. Reading the files with "
                 "cat/jq/git is fine.")


def dropdb_targets(command):
    """The database of each dropdb command (the program, not the word inside an argument)."""
    segments = shell_segments(command)
    if segments is None:
        # unparseable: read every `dropdb` word as the program
        segments = [m.group(0).split() for m in re.finditer(r"\bdropdb\b[^;&|\n]*", command)]
    targets = []
    for tokens in segments:
        for i, token in enumerate(tokens):
            if token == "dropdb" or token.endswith("/dropdb"):
                names = [t for t in tokens[i + 1:] if not t.startswith("-")]
                targets += names[-1:] or ["<unknown>"]
    return targets


def check_bash(env, command):
    check_state_commands(command)
    test_db = env.get("TEST_DB", "harness_test")
    drops = dropdb_targets(command)
    drops += re.findall(r"drop\s+database\s+(?:if\s+exists\s+)?[\"'`]?([\w-]+)", command, re.I)
    for name in drops:
        if name not in droppable_dbs(env):
            deny(f"command drops database '{name}', not the test DB",
                 "Only the disposable test DB is ever dropped; the dev DB and any other database "
                 "may hold real data.",
                 f"Use `odoo-harness init --reset` to recreate the test DB '{test_db}'. A human "
                 "handles any other database.")
    runs = re.findall(r"\bodoo(?:-bin)?\b[^;&|\n]*?(?:\s-d\s*|--database[ =])([\w-]+)", command)
    for name in runs:
        if name not in odoo_dbs(env):
            deny(f"command targets database '{name}', not the test DB",
                 "The harness only works on the disposable test DB (and the dev DB, through "
                 "odoo-harness verify); other databases may hold real data.",
                 f"Use the test DB '{test_db}' (odoo-harness init --reset recreates it). A human "
                 "handles any other database.")
    if re.search(r"docker[\s-]+compose\b[^;&|\n]*\bdown\b[^;&|\n]*(\s-v\b|--volumes)", command) \
            or re.search(r"docker\s+volume\s+(rm|prune)\b", command):
        deny("command deletes docker volumes",
             "Volumes hold the databases and filestore; deleting them is not reversible.",
             "To start from a clean test DB use `odoo-harness init --reset`.")
    check_push(env, command)
    if re.search(r"\bgit\b[^;&|\n]*\bcommit\b[^;&|\n]*--no-verify", command):
        deny("git commit --no-verify",
             "Pre-commit runs the feature list integrity check and the static checks.",
             "Commit without --no-verify and fix what the hooks report.")


def check_push(env, command):
    protected = {"main", "master", "production", env.get("BASE_BRANCH") or "staging"}
    for segment in shell_segments(command) or []:
        sub, args = git_subcommand(segment)
        if sub != "push":
            continue
        if any(a in ("--force", "-f", "--mirror", "--all", "--delete", "-d")
               or a.startswith("--force") for a in args):
            deny(f"git push with a destructive option: {' '.join(segment)[:120]}",
                 "Force, mirror, --all and --delete pushes rewrite or remove shared history.",
                 "Push the task branch with odoo-harness gitlab push; a human handles anything else.")
        refs = [a for a in args if not a.startswith("-")][1:]
        targets = {r.split(":")[-1].removeprefix("refs/heads/").lstrip("+") for r in refs}
        if not refs or targets & protected or "HEAD" in targets:
            deny(f"git push to a shared branch: {' '.join(segment)[:120]}",
                 f"{', '.join(sorted(protected))} are deployed by CI; they change only through a "
                 "reviewed merge request.",
                 "Push the task branch and open its merge request with "
                 "`odoo-harness gitlab push` and `odoo-harness gitlab mr` (the feature workflow "
                 "does it when the task's features pass).")


def main():
    payload = c.read_input()
    root = c.project_dir(payload)
    if not c.active(root):
        sys.exit(0)
    env = c.load_env(root)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if tool in FILE_TOOLS:
        check_file_tool(root, env, payload, tool_input)
    elif tool == "Bash":
        check_bash(env, tool_input.get("command", ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
