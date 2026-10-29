#!/usr/bin/env python3
"""odoo-harness: the harness command, installed once per machine with the plugin.

    odoo-harness init [--check | --reset]       the test environment (initialization step 1)
    odoo-harness verify [...]                   the 3 verification layers on the changed modules
    odoo-harness feature status|add|start|block|verify|check
                                                the feature workflow, the only way to change
                                                feature_list.json
    odoo-harness loop run|status                the autonomous maker-checker loop
    odoo-harness gitlab push|mr TASK            push the task branch, open its merge request
    odoo-harness guide capture|build|check      user guides of completed tasks
    odoo-harness map [--json]                   the project map (modules, models, dependencies)
    odoo-harness static [--all | FILE...]       the static checks of layer 1
    odoo-harness compose ARGS...                docker compose on the harness stack
                                                (e.g. `compose logs odoo`, `compose ps`)
    odoo-harness link                           refresh ~/.odoo-harness/current and the
                                                ~/.local/bin/odoo-harness shim
    odoo-harness where                          the repository, the engine and their versions

The repository is found from the current folder: the folder itself or a parent holding
harness/harness.env, or git/ of a client workspace (~/Project/<client>). HARNESS_REPO
overrides it. Commands run with the repository as their working directory.

Standard library only. Exit codes: the command's own, or 2 when it cannot run.
"""

import os
import shutil
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = ENGINE_DIR.parent
ENGINE_VERSION = (ENGINE_DIR / "VERSION").read_text().strip()
WORKSPACE_REPO = "git"
HOME_DIR = Path(os.environ.get("ODOO_HARNESS_HOME") or Path.home() / ".odoo-harness")
SHIM = Path(os.environ.get("ODOO_HARNESS_BIN") or Path.home() / ".local" / "bin") / "odoo-harness"

# command -> (interpreter, engine script)
COMMANDS = {
    "init": ("bash", "init.sh"),
    "verify": ("python3", "verify.py"),
    "feature": ("python3", "feature.py"),
    "loop": ("python3", "loop.py"),
    "gitlab": ("python3", "gitlab.py"),
    "guide": ("python3", "guide.py"),
    "map": ("python3", "project_map.py"),
    "static": ("python3", "static_checks.py"),
    "compose": ("python3", "hlib.py"),
}
# Projects installed before 2.0 carry a copy of the engine in their harness/ folder.
LEGACY_MARKER = Path("harness") / "feature.py"


def redpen(what, why, fix):
    print(f"✗ [odoo-harness] {what}\nWHY: {why}\nHOW TO FIX: {fix}", file=sys.stderr)
    return 2


def has_harness(root):
    return (root / "harness" / "harness.env").is_file()


def find_repo(start):
    """The repository holding the harness for a command run in `start`, or None."""
    start = Path(start).resolve()
    for folder in (start, *start.parents):
        if has_harness(folder):
            return folder
    if has_harness(start / WORKSPACE_REPO):
        return start / WORKSPACE_REPO
    return None


def version_tuple(version):
    parts = []
    for part in str(version).split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def read_env(root):
    values = {}
    for line in (root / "harness" / "harness.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def check_repo(root):
    """None when the engine may run on root, else the exit code of the red pen printed."""
    if (root / LEGACY_MARKER).is_file():
        return redpen(f"{root} still carries a copy of the old harness (harness/feature.py)",
                      "Since 2.0 the harness engine is installed once per machine with the "
                      "plugin; the repository keeps only its state and configuration.",
                      "Run /odoo-harness:update in Claude Code: it removes the copy and keeps "
                      "the state. Commit the result.")
    pinned = read_env(root).get("HARNESS_VERSION", "")
    if pinned and version_tuple(pinned) > version_tuple(ENGINE_VERSION):
        return redpen(f"this project needs odoo-harness {pinned}, this machine has "
                      f"{ENGINE_VERSION}",
                      "HARNESS_VERSION in harness/harness.env is the oldest engine the project "
                      "accepts: an older one could judge a feature differently.",
                      "Update the plugin: claude plugin update odoo-harness@odoo-harness, then "
                      "/reload-plugins.")
    return None


def link():
    """~/.odoo-harness/current -> this plugin, ~/.local/bin/odoo-harness -> its command."""
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    current = HOME_DIR / "current"
    report = []
    if not (current.is_symlink() and current.resolve() == PLUGIN_ROOT):
        if current.exists() and not current.is_symlink():
            return [f"✗ {current} exists and is not a symlink: remove it, then run "
                    "`odoo-harness link`"]
        tmp = HOME_DIR / ".current.tmp"
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(PLUGIN_ROOT, target_is_directory=True)
        os.replace(tmp, current)
        report.append(f"{current} -> {PLUGIN_ROOT}")
    target = current / "bin" / "odoo-harness"
    if not (SHIM.is_symlink() and Path(os.readlink(SHIM)) == target):
        if SHIM.exists() and not SHIM.is_symlink():
            report.append(f"✗ {SHIM} exists and is not ours: left as it is")
        else:
            SHIM.parent.mkdir(parents=True, exist_ok=True)
            SHIM.unlink(missing_ok=True)
            SHIM.symlink_to(target)
            report.append(f"{SHIM} -> {target}")
    if str(SHIM.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        report.append(f"note: {SHIM.parent} is not on your PATH; add it to use odoo-harness "
                      "in a terminal")
    return report


def child_env(root):
    """The command's own bin/ first on PATH, so nested calls (loop.py's headless Claude
    sessions, git hooks) reach this same engine."""
    path = os.environ.get("PATH", "")
    bin_dir = str(PLUGIN_ROOT / "bin")
    return {**os.environ, "HARNESS_REPO": str(root),
            "PATH": os.pathsep.join([bin_dir, path]) if path else bin_dir}


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    command, args = argv[0], argv[1:]
    if command == "link":
        for line in link():
            print(line)
        return 0
    if command not in COMMANDS and command != "where":
        return redpen(f"unknown command {command!r}", "See `odoo-harness --help`.",
                      f"Use one of: {', '.join([*COMMANDS, 'link', 'where'])}.")
    cwd = Path.cwd()
    root = Path(os.environ["HARNESS_REPO"]).resolve() if os.environ.get("HARNESS_REPO") \
        else find_repo(cwd)
    if root is None or not has_harness(root):
        return redpen(f"no harness in {cwd}",
                      "odoo-harness works on an Odoo repository with harness/harness.env, run "
                      "from it or from its client workspace (git/).",
                      "cd into the repository, or install the harness with /odoo-harness:init.")
    if command == "where":
        env = read_env(root)
        print(f"repository: {root}\nengine:     {ENGINE_DIR} ({ENGINE_VERSION})\n"
              f"odoo:       {env.get('ODOO_VERSION', '?')}\n"
              f"pinned:     {env.get('HARNESS_VERSION') or '(none)'}")
        return 0
    refused = check_repo(root)
    if refused is not None:
        return refused
    interpreter, script = COMMANDS[command]
    if command == "static":
        # FILE arguments are relative to the folder the command was typed in
        args = [a if a.startswith("-") or Path(a).is_absolute() else str(cwd / a) for a in args]
    if command == "compose":
        args = ["compose", *args]
    program = sys.executable if interpreter == "python3" else shutil.which(interpreter)
    if not program:
        return redpen(f"{interpreter} not found", "The engine needs it to run.",
                      f"Install {interpreter}.")
    os.chdir(root)
    os.execve(program, [program, str(ENGINE_DIR / script), *args], child_env(root))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
