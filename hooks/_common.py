"""Shared helpers for the odoo-harness hooks.

Hooks are thin: they read the hook JSON on stdin, find the project's harness and call the
engine of this plugin on it. The plugin is installed once per machine, so the hooks run in
every session: in a folder without the harness they do nothing, after a cheap file check.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def read_input():
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


WORKSPACE_REPO = "git"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = PLUGIN_ROOT / "engine"


def launch_dir(payload):
    """The folder Claude Code was started in."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()).resolve()


def harness_root(launch):
    """The Odoo repository holding the harness, for a session started in `launch`.

    Claude Code runs either in the repository itself or in the client workspace that
    contains it (fogits layout: ~/Project/<client> with the repository in git/ and
    Odoo Enterprise in enterprise/). Returns `launch` when no harness is found."""
    if has_harness(launch):
        return launch
    if has_harness(launch / WORKSPACE_REPO):
        return launch / WORKSPACE_REPO
    try:
        found = [d for d in launch.iterdir() if d.is_dir() and has_harness(d)]
    except OSError:
        found = []
    return found[0] if len(found) == 1 else launch


def project_dir(payload):
    return harness_root(launch_dir(payload))


def has_harness(root):
    """The marker of a repository with the harness: its settings and its feature list."""
    return (root / "harness" / "harness.env").is_file() and (root / "feature_list.json").exists()


def is_legacy(root):
    """A repository that still carries the engine copy of the old vendored harness (< 2.0).
    The old per-version plugin drives it until /odoo-harness:update migrates it."""
    return (root / "harness" / "feature.py").is_file()


def active(root):
    """True when this plugin drives the repository: the harness is there, without the old
    vendored engine (that one is still driven by the old plugin until it is migrated)."""
    return has_harness(root) and not is_legacy(root)


def engine(script, *args):
    """The command line of an engine script; run it with run(root, ...)."""
    interpreter = ["bash"] if script.endswith(".sh") else [sys.executable]
    return [*interpreter, str(ENGINE_DIR / script), *map(str, args)]


def tool_path(payload, path):
    """A file path from a tool call: relative paths are relative to the launch folder."""
    path = Path(path)
    return path if path.is_absolute() else launch_dir(payload) / path


def emit(obj):
    print(json.dumps(obj))
    sys.exit(0)


def load_env(root):
    values = {}
    env_file = root / "harness" / "harness.env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def custom_roots(env):
    """Repo-relative folders of the project's own modules (CUSTOM_ADDONS)."""
    raw = env.get("CUSTOM_ADDONS") or env.get("ADDONS_DIR") or "addons"
    return [p.strip().strip("/") for p in raw.split(",") if p.strip().strip("/")]


def env_paths(env, key):
    return [p.strip().strip("/") for p in env.get(key, "").split(",") if p.strip().strip("/")]


def run(root, args, timeout=60):
    """Run a project command; returns (rc, combined output). Never raises.

    The engine finds the repository through HARNESS_REPO (see engine/cli.py)."""
    env = {**os.environ, "HARNESS_REPO": str(root),
           "PATH": os.pathsep.join([str(PLUGIN_ROOT / "bin"), os.environ.get("PATH", "")])}
    try:
        proc = subprocess.run(args, cwd=root, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=timeout,
                              errors="replace")
        return proc.returncode, proc.stdout.strip()
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {' '.join(map(str, args))}"
    except OSError as exc:
        return 127, str(exc)


def git(root, *args):
    rc, out = run(root, ["git", *args], timeout=30)
    return out if rc == 0 else ""


def redpen(layer, what, why, fix):
    return f"✗ [{layer}] {what}\nWHY: {why}\nHOW TO FIX: {fix}"


# --- PROGRESS.md sections -------------------------------------------------------

def sections(text):
    """Ordered {heading: body_lines} of the '## ' sections, plus '' for the preamble."""
    out, current = {"": []}, ""
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = []
        else:
            out[current].append(line)
    return out


def section_text(text, name):
    return "\n".join(sections(text).get(name, [])).strip()


def body_without(text, name):
    """PROGRESS.md content without one section (to detect real edits by the agent)."""
    parts = sections(text)
    parts.pop(name, None)
    return "\n".join(f"{k}\n{chr(10).join(v)}" for k, v in parts.items()).strip()


def replace_section(text, name, body_lines):
    lines = text.splitlines()
    header = f"## {name}"
    if header not in lines:
        return text.rstrip("\n") + f"\n\n{header}\n" + "\n".join(body_lines) + "\n"
    start = lines.index(header) + 1
    end = start
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    new = lines[:start] + body_lines + ([""] if end < len(lines) else []) + lines[end:]
    return "\n".join(new) + "\n"


def state_dir(root):
    path = root / ".harness"
    path.mkdir(exist_ok=True)
    return path


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")



def dirty_files(root):
    """{path: blob hash} of files modified or untracked right now (content fingerprint)."""
    names = set(git(root, "diff", "--name-only", "HEAD").splitlines())
    names |= set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    names = sorted(n for n in names if n and (root / n).is_file())
    if not names:
        return {}
    rc, out = run(root, ["git", "hash-object", "--", *names], timeout=60)
    hashes = out.splitlines() if rc == 0 else []
    return dict(zip(names, hashes)) if len(hashes) == len(names) else {}
