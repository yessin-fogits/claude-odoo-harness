"""Shared helpers for the harness Python scripts. Standard library only.

    hlib.py modules     print the custom modules of the project, comma-separated
    hlib.py runtime     write .harness/odoo.conf from harness/harness.env
    hlib.py compose ... run docker compose on the harness stack (`odoo-harness compose`)

The engine (this folder) is installed once per machine with the plugin; it works on the
repository in $HARNESS_REPO, set by the odoo-harness command (default: the current folder).
"""

import ast
import datetime
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
ENGINE_VERSION = (ENGINE_DIR / "VERSION").read_text().strip()
REPO_ROOT = Path(os.environ.get("HARNESS_REPO") or os.getcwd()).resolve()
# The project's own harness files: harness.env, project checks, errors_project.py, evidence.
HARNESS_DIR = REPO_ROOT / "harness"
HARNESS_ENV = HARNESS_DIR / "harness.env"
FEATURE_LIST = REPO_ROOT / "feature_list.json"
PROGRESS = REPO_ROOT / "PROGRESS.md"
EVIDENCE_DIR = HARNESS_DIR / "evidence"
STATE_DIR = REPO_ROOT / ".harness"
STATE_FILE = STATE_DIR / "state.json"
ODOO_CONF = STATE_DIR / "odoo.conf"

STATES = ("not_started", "in_progress", "blocked", "passing")
FEATURE_KEYS = {"id", "behavior", "verification", "state", "evidence"}
# Optional: the Odoo task the feature belongs to: its code (T2003), or any short name until
# the Odoo task exists (then `feature rename-task`). A task is split into one or more
# features, worked on the git branch of the same name; the name is also used in file names.
OPTIONAL_KEYS = {"task"}
TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
TASK_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*$")
VERIFY_KINDS = ("unit", "integration", "e2e")
ID_RE = re.compile(r"^F-\d{3,}$")


# --- red pen --------------------------------------------------------------

class RedPen(Exception):
    """A failure an agent can act on: what failed, why, and how to fix it."""

    def __init__(self, layer, what, why, fix):
        super().__init__(what)
        self.layer, self.what, self.why, self.fix = layer, what, why, fix

    def __str__(self):
        return format_redpen(self.layer, self.what, self.why, self.fix)


def format_redpen(layer, what, why, fix):
    return f"✗ [{layer}] {what}\nWHY: {why}\nHOW TO FIX: {fix}"


def print_redpen(layer, what, why, fix):
    print(format_redpen(layer, what, why, fix), file=sys.stderr)


# --- environment ----------------------------------------------------------

def load_env():
    """harness.env values; real environment variables of the same name win."""
    values = {}
    for line in HARNESS_ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    for key in values:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def render_odoo_conf(env):
    """The test runtime's odoo.conf, from the engine template and harness.env values."""
    mounts = [f"/mnt/repo/{p}" for p in env_list(env, "CUSTOM_ADDONS")
              + env_list(env, "THIRD_PARTY_ADDONS")]
    if env.get("ENTERPRISE_DIR", "").strip():
        mounts.append("/mnt/enterprise")
    demo = ("with_demo = True" if version_tuple(env.get("ODOO_VERSION")) >= (19, 0)
            else "without_demo = False")
    values = {"ADDONS_PATH": ",".join(mounts), "DEMO_OPTION": demo,
              "TEST_DB": env.get("TEST_DB", "harness_test")}
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)],
                  (ENGINE_DIR / "odoo.conf").read_text())


def write_runtime(env=None):
    """Files the compose stack reads that are derived from harness.env (not versioned)."""
    text = render_odoo_conf(env or load_env())
    if not ODOO_CONF.is_file() or ODOO_CONF.read_text() != text:
        write_atomic(ODOO_CONF, text)


def compose_env():
    """Environment of every compose call: the engine folder holds the build contexts."""
    return {**os.environ, "HARNESS_HOME": str(ENGINE_DIR)}


def compose_cmd(env=None):
    """The docker compose command of the harness stack, for the repository REPO_ROOT.

    Every caller goes through it (or `hlib.py runtime` for the shell scripts), so the
    runtime files exist and HARNESS_HOME is set (compose_env)."""
    write_runtime(env)
    base = shlex.split(os.environ.get("HARNESS_COMPOSE", "docker compose"))
    return base + ["--project-directory", str(REPO_ROOT),
                   "-f", str(ENGINE_DIR / "docker-compose.yml"),
                   "--env-file", str(HARNESS_ENV)]


def version_tuple(version):
    """'17.0' -> (17, 0); 'saas~18.3' -> (18, 3). Unknown -> (0, 0)."""
    match = re.search(r"(\d+)\.(\d+)", str(version or ""))
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def env_list(env, key):
    return [p.strip().strip("/") for p in env.get(key, "").split(",") if p.strip().strip("/")]


def custom_roots(env):
    """Folders of the project's own modules (CUSTOM_ADDONS), the code the agent may edit."""
    return [REPO_ROOT / p for p in env_list(env, "CUSTOM_ADDONS")]


def custom_modules(env):
    """{module name: module dir} for every custom module of the project."""
    found = {}
    for root in custom_roots(env):
        if root.is_dir():
            for manifest in sorted(root.glob("*/__manifest__.py")):
                found.setdefault(manifest.parent.name, manifest.parent)
    return found


def read_manifest(module_dir):
    try:
        return ast.literal_eval((Path(module_dir) / "__manifest__.py").read_text())
    except (OSError, ValueError, SyntaxError):
        return {}


def dependents(env, names):
    """Custom modules that depend on any of names, directly or not (names excluded)."""
    modules = custom_modules(env)
    depends = {m: set(read_manifest(d).get("depends") or []) for m, d in modules.items()}
    found, frontier = set(), set(names)
    while frontier:
        frontier = {m for m, deps in depends.items() if deps & frontier} - found - set(names)
        found |= frontier
    return sorted(found)


def module_of(env, path):
    """Name of the custom module that contains path (repo-relative or absolute), or None."""
    path = Path(path)
    path = path if path.is_absolute() else REPO_ROOT / path
    for root in custom_roots(env):
        try:
            parts = path.resolve().relative_to(root.resolve()).parts
        except ValueError:
            continue
        if len(parts) > 1 and (root / parts[0] / "__manifest__.py").is_file():
            return parts[0]
    return None


def base_ref(env):
    """The commit this branch started from: merge-base with origin/BASE_BRANCH or BASE_BRANCH."""
    branch = env.get("BASE_BRANCH", "")
    for ref in (f"origin/{branch}", branch) if branch else ():
        if git("rev-parse", "--verify", "-q", ref):
            return git("merge-base", "HEAD", ref) or None
    return None


def changed_files(since=None):
    """Paths changed since a commit (default: HEAD), staged or not, plus untracked files."""
    names = set(git("diff", "--name-only", since or "HEAD").splitlines())
    names |= set(git("ls-files", "--others", "--exclude-standard").splitlines())
    return {n for n in names if n}


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)


def changed_lines(since=None):
    """{repo-relative path: set of changed line numbers, or None for a whole new file}."""
    out = {}
    current = None
    for line in git("diff", "-U0", "--no-color", "--no-ext-diff", since or "HEAD").splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
            if current:
                out.setdefault(current, set())
            continue
        match = HUNK_RE.match(line)
        if match and current:
            start, count = int(match.group(1)), int(match.group(2) or 1)
            out[current].update(range(start, start + count))
    for name in git("ls-files", "--others", "--exclude-standard").splitlines():
        if name:
            out[name] = None
    return out


def is_changed(lines, path, line):
    """True when path:line is new or changed according to changed_lines()."""
    if path not in lines:
        return False
    return lines[path] is None or line in lines[path] or (line <= 1 and bool(lines[path]))


def changed_modules(env, since=None):
    """Custom modules with changes on this branch (since `since`, or the base branch)."""
    since = since or base_ref(env)
    names = {module_of(env, f) for f in changed_files(since)}
    return sorted(n for n in names if n)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def git(*args):
    try:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
                             check=True)
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out.stdout.strip()


def head_commit():
    return git("rev-parse", "HEAD") or None


def working_tree_dirty():
    return bool(git("status", "--porcelain"))


# --- feature list ----------------------------------------------------------

def load_features():
    try:
        data = json.loads(FEATURE_LIST.read_text())
    except FileNotFoundError:
        raise RedPen("features", "feature_list.json not found",
                     "The harness keeps the work split into features in feature_list.json.",
                     "Run the odoo-harness init skill (/odoo-harness:init), or "
                     "restore the file from git.")
    except json.JSONDecodeError as exc:
        raise RedPen("features", f"feature_list.json is not valid JSON (line {exc.lineno})",
                     "The file was edited by hand and broken.",
                     "Restore it with `git checkout feature_list.json`, then use odoo-harness feature.")
    problems = validate(data)
    if problems:
        raise RedPen("features", "feature_list.json is invalid: " + "; ".join(problems),
                     "The file does not match the harness format, probably edited by hand.",
                     "Restore it with `git checkout feature_list.json`; change it only with "
                     "odoo-harness feature.")
    return data


def validate(data):
    problems = []
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(
            data.get("features"), list):
        return ["expected {\"version\": 1, \"features\": [...]}"]
    seen = set()
    for i, feat in enumerate(data["features"]):
        if not isinstance(feat, dict):
            problems.append(f"features[{i}] is not an object")
            continue
        fid = feat.get("id", f"features[{i}]")
        if not FEATURE_KEYS <= set(feat) <= FEATURE_KEYS | OPTIONAL_KEYS:
            problems.append(f"{fid}: keys must be {sorted(FEATURE_KEYS)} (+ optional "
                            f"{sorted(OPTIONAL_KEYS)})")
            continue
        if "task" in feat and not (isinstance(feat["task"], str) and TASK_RE.match(feat["task"])):
            problems.append(f"{fid}: task must use only letters, digits, - and _ "
                            "(T2003, remise-devis)")
        if not isinstance(fid, str) or not ID_RE.match(fid):
            problems.append(f"{fid}: id must look like F-001")
        elif fid in seen:
            problems.append(f"{fid}: duplicate id")
        seen.add(fid)
        if not isinstance(feat["behavior"], str) or not feat["behavior"].strip():
            problems.append(f"{fid}: behavior must be a non-empty sentence")
        problems += [f"{fid}: {p}" for p in validate_verification(feat["verification"])]
        if feat["state"] not in STATES:
            problems.append(f"{fid}: state must be one of {', '.join(STATES)}")
        if feat["state"] == "passing" and not isinstance(feat["evidence"], dict):
            problems.append(f"{fid}: passing without evidence")
        if feat["state"] != "passing" and feat["evidence"] is not None:
            problems.append(f"{fid}: evidence is only allowed on passing features")
    in_progress = [f.get("id") for f in data["features"]
                   if isinstance(f, dict) and f.get("state") == "in_progress"]
    if len(in_progress) > 1:
        problems.append(f"WIP = 1 violated, in_progress: {', '.join(in_progress)}")
    return problems


def validate_verification(entries):
    if not isinstance(entries, list) or not entries:
        return ["verification must be a non-empty list"]
    problems = []
    for entry in entries:
        kind, _, target = entry.partition(":") if isinstance(entry, str) else ("", "", "")
        if kind.strip() not in VERIFY_KINDS or not target.strip():
            problems.append(f"bad verification {entry!r}, expected '<unit|integration|e2e>: <target>'")
    if not any(parse_verification(e)[0] == "e2e" for e in entries if isinstance(e, str)):
        problems.append("needs at least one 'e2e: e2e/test_<id>_....py' verification")
    return problems


def parse_verification(entry):
    kind, _, target = entry.partition(":")
    return kind.strip(), target.strip()


def save_features(data):
    problems = validate(data)
    if problems:
        raise AssertionError("refusing to save an invalid feature list: " + "; ".join(problems))
    write_atomic(FEATURE_LIST, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def task_features(data, task):
    return [f for f in data["features"] if f.get("task") == task]


def commit_message(feat):
    """Commit message of a verified feature: [T2003] F-001 behavior, or feat(F-001): ..."""
    if feat.get("task"):
        return f"[{feat['task']}] {feat['id']} {feat['behavior']}"
    return f"feat({feat['id']}): {feat['behavior']}"


def current_branch():
    return git("symbolic-ref", "-q", "--short", "HEAD")


def find_feature(data, fid):
    for feat in data["features"]:
        if feat["id"] == fid:
            return feat
    raise RedPen("features", f"unknown feature {fid}",
                 "There is no feature with this id in feature_list.json.",
                 "Run `odoo-harness feature status` to list the ids.")


def fingerprint(feat):
    """Hash of what was verified; changes if behavior or verification change later."""
    payload = json.dumps({"id": feat["id"], "behavior": feat["behavior"],
                          "verification": feat["verification"]}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


# --- local harness state (not versioned) ------------------------------------

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    write_atomic(STATE_FILE, json.dumps(state, indent=2) + "\n")


# --- PROGRESS.md -------------------------------------------------------------

def _task_re(fid):
    return re.compile(rf"^- \[[ xX]\] {re.escape(fid)}\b")


def progress_set_task(fid, line, section):
    """Remove the task line of fid everywhere, then add `line` under `## section`."""
    lines = PROGRESS.read_text().splitlines() if PROGRESS.exists() else []
    lines = [ln for ln in lines if not _task_re(fid).match(ln)]
    if section:
        lines = _append_to_section(lines, section, line)
    write_atomic(PROGRESS, "\n".join(lines) + "\n")


def progress_rename_task(fid, old, new):
    """Change the task of fid's line, which stays in its section."""
    if PROGRESS.exists():
        pattern = rf"^(- \[[ xX]\] {re.escape(fid)}) \[{re.escape(old)}\] "
        write_atomic(PROGRESS, re.sub(pattern, rf"\1 [{new}] ", PROGRESS.read_text(), flags=re.M))


def progress_append(section, line):
    lines = PROGRESS.read_text().splitlines() if PROGRESS.exists() else []
    write_atomic(PROGRESS, "\n".join(_append_to_section(lines, section, line)) + "\n")


def _append_to_section(lines, section, line):
    header = f"## {section}"
    if header not in lines:
        lines = lines + ["", header]
    start = lines.index(header) + 1
    end = start
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines = lines[:insert_at] + [line] + lines[insert_at:]
    # keep one blank line before the next section
    nxt = insert_at + 1
    if nxt < len(lines) and lines[nxt].startswith("## "):
        lines.insert(nxt, "")
    return lines


if __name__ == "__main__":
    if sys.argv[1:] == ["modules"]:
        print(",".join(custom_modules(load_env())))
    elif sys.argv[1:] == ["runtime"]:
        write_runtime()
    elif sys.argv[1:2] == ["compose"]:
        cmd = compose_cmd() + sys.argv[2:]
        os.execvpe(cmd[0], cmd, compose_env())
    else:
        sys.exit("usage: hlib.py modules | runtime | compose ARGS...")
