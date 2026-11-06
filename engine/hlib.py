"""Shared helpers for the harness Python scripts. Standard library only.

    hlib.py modules     print the custom modules of the project, comma-separated
    hlib.py localenv    create harness/dev.local.env from the template when missing
    hlib.py shellenv    print the settings as shell exports (lib.sh)
    hlib.py runtime     write .harness/odoo.conf from the settings
    hlib.py compose ... run docker compose on the harness stack (`odoo-harness compose`)
    hlib.py psql SQL    run one SQL statement on the harness's PostgreSQL server, print the rows
    hlib.py devcheck    check the dev database (DEV_DB) before the e2e layer uses it
    hlib.py prune-images  remove the tool images no project uses any more (init)

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
# harness.env is versioned: the settings every developer of the project shares.
HARNESS_ENV = HARNESS_DIR / "harness.env"
# This developer's machine, never versioned (.gitignore): read_settings() takes LOCAL_KEYS
# from it. Real environment variables win over both files.
LOCAL_ENV_NAME = "dev.local.env"
LOCAL_ENV = HARNESS_DIR / LOCAL_ENV_NAME
SECRET_KEYS = ("DEV_DB_PASSWORD", "DEV_ODOO_LOGIN", "DEV_ODOO_PASSWORD")
# Values that differ between developers (their port, their dev stack and database, their
# logins): set only in the local file. harness.env of engines before 3.1 still holds some.
MACHINE_KEYS = ("ODOO_PORT", "DEV_DB", "DEV_DB_HOST", "DEV_DB_PORT", "DEV_DB_USER",
                "DEV_NETWORK", "DEV_DATA_DIR", *SECRET_KEYS)
# What the local file may set: the machine keys, and ENTERPRISE_DIR, a shared default (the
# team's workspace layout) that a developer whose checkout is elsewhere overrides. Any other
# key is the project's: from the local file it is ignored, so every developer verifies with
# the same rules.
LOCAL_KEYS = (*MACHINE_KEYS, "ENTERPRISE_DIR")
DEFAULT_ODOO_PORT = "18069"
# The features of each task live in tasks/<task>.json and its notes in tasks/<task>.md: a task
# is worked on its own branch by one developer, so two branches never write the same file.
TASKS_DIR = REPO_ROOT / "tasks"
# The single feature list of engines before 3.0; /odoo-harness:update splits it into tasks/.
LEGACY_FEATURE_LIST = REPO_ROOT / "feature_list.json"
PROGRESS = REPO_ROOT / "PROGRESS.md"
EVIDENCE_DIR = HARNESS_DIR / "evidence"
STATE_DIR = REPO_ROOT / ".harness"
STATE_FILE = STATE_DIR / "state.json"
ODOO_CONF = STATE_DIR / "odoo.conf"
# Dev DB mode: the same config without demo data, mounted for the commands on the dev DB.
ODOO_NODEMO_CONF = STATE_DIR / "odoo-nodemo.conf"
NODEMO_CONF_MOUNT = "/etc/odoo/odoo-nodemo.conf"

STATES = ("not_started", "in_progress", "blocked", "passing")
# The keys stored in tasks/<task>.json. In memory each feature also carries `task`, the Odoo
# task it belongs to (the file name): its code (T2003), or any short name until the Odoo task
# exists (then `feature rename-task`). A task is split into one or more features, worked on
# the git branch of the same name; the name is also used in file names.
FEATURE_KEYS = {"id", "behavior", "verification", "state", "evidence"}
TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
TASK_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*$")
VERIFY_KINDS = ("unit", "integration", "e2e")
# F-T2003-1: numbered within its task, so developers on different tasks never pick the same
# id. F-001 is the id of engines before 3.0, still valid.
ID_RE = re.compile(r"^F-(\d{3,}|[A-Za-z0-9][A-Za-z0-9_-]*-\d+)$")
TASK_FILE_VERSION = 2
NOTES_SECTIONS = ("Features", "Notes", "Known issues", "Decisions", "Next steps")


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

def read_env_file(path):
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def read_settings(repo_root):
    """(settings, notes) of a repository: harness.env, then the LOCAL_KEYS of the local file.
    notes says what is misplaced: a project key in the local file (ignored), a machine value
    still in harness.env (used until /odoo-harness:update moves it), dev logins without a dev
    DB (a teammate's file from before 3.1). The hooks use it too."""
    harness_dir = Path(repo_root) / "harness"
    values = read_env_file(harness_dir / "harness.env")
    local = read_env_file(harness_dir / LOCAL_ENV_NAME)
    notes = []
    ignored = sorted(set(local) - set(LOCAL_KEYS))
    if ignored:
        notes.append(f"harness/{LOCAL_ENV_NAME} sets {', '.join(ignored)}, ignored: these are "
                     "the project's settings, shared in harness/harness.env")
    shared = [k for k in MACHINE_KEYS if values.get(k)]
    if shared:
        notes.append(f"harness/harness.env (versioned) holds this machine's {', '.join(shared)}: "
                     f"they belong in harness/{LOCAL_ENV_NAME}; /odoo-harness:update moves them")
    values.update({k: v for k, v in local.items() if k in LOCAL_KEYS})
    if not values.get("DEV_DB", "").strip() and any(values.get(k) for k in SECRET_KEYS):
        notes.append(f"harness/{LOCAL_ENV_NAME} has dev database logins but no DEV_DB: the dev "
                     "DB mode is off on this machine and the e2e tests run on the test DB; set "
                     f"DEV_DB and the other DEV_* in harness/{LOCAL_ENV_NAME} to turn it on")
    if not values.get("ODOO_PORT"):
        values["ODOO_PORT"] = DEFAULT_ODOO_PORT
    return values, notes


def ensure_local_env():
    """Create this developer's harness/dev.local.env from the plugin's template when missing,
    and only where git ignores it. True when it was created."""
    template = ENGINE_DIR.parent / "template" / "harness" / LOCAL_ENV_NAME
    if LOCAL_ENV.is_file() or not template.is_file():
        return False
    ignored = subprocess.run(["git", "check-ignore", "-q", str(LOCAL_ENV)], cwd=REPO_ROOT,
                             capture_output=True).returncode == 0
    if not ignored:
        raise RedPen("env", f"harness/{LOCAL_ENV_NAME} is not ignored by git",
                     "It holds this developer's settings and passwords: it must never be "
                     "committed.",
                     f"Add harness/{LOCAL_ENV_NAME} to .gitignore (/odoo-harness:update does it), "
                     "then run the command again.")
    port = read_settings(REPO_ROOT)[0]["ODOO_PORT"]
    write_atomic(LOCAL_ENV, template.read_text().replace("{{ODOO_PORT}}", port))
    return True


def load_env():
    """The settings of read_settings(); real environment variables win."""
    values = read_settings(REPO_ROOT)[0]
    for key in {*values, *SECRET_KEYS}:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def shell_exports(env):
    """`export KEY=value` lines of the settings for the shell scripts (lib.sh), secrets
    excepted: one loader for Python and bash."""
    return "".join(f"export {key}={shlex.quote(value)}\n" for key, value in sorted(env.items())
                   if key not in SECRET_KEYS and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key))


# --- dev database mode ------------------------------------------------------
# With DEV_DB set, the harness has no PostgreSQL of its own: its Odoo uses the dev stack's
# server, for the disposable TEST_DB (demo data, unit and integration tests) and for DEV_DB
# (the developer's database, a neutralized copy of the client's data, e2e tests). DEV_DB is
# updated with -u, never created, dropped or reset.

def dev_mode(env):
    return bool(env.get("DEV_DB", "").strip())


def db_server(env):
    """(host, port, user, password) of the PostgreSQL server the harness Odoo uses."""
    if dev_mode(env):
        return (env.get("DEV_DB_HOST", "").strip(), env.get("DEV_DB_PORT", "").strip() or "5432",
                env.get("DEV_DB_USER", "").strip() or "odoo", env.get("DEV_DB_PASSWORD", ""))
    return ("db", "5432", "odoo", "odoo")


def safe_test_db(name):
    """Any PostgreSQL name is accepted, but init --reset deletes filestore/<TEST_DB>: an empty
    name or a path would delete more than the test DB's filestore."""
    return bool(name) and "/" not in name and name not in (".", "..")


def sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def dev_config_problems(env):
    """What is missing or unsafe in the dev database settings (empty when DEV_DB is not set)."""
    if not dev_mode(env):
        return []
    problems = []
    dev_db, test_db = env["DEV_DB"].strip(), env.get("TEST_DB", "").strip()
    # init --reset deletes filestore/<TEST_DB>, inside the dev data directory in this mode
    if not safe_test_db(test_db):
        problems.append("TEST_DB must be set and must not be a path (/, . or ..)")
    if dev_db == test_db:
        problems.append("DEV_DB and TEST_DB must differ: init --reset drops the test DB")
    if not env.get("DEV_DB_HOST", "").strip():
        problems.append("DEV_DB_HOST is empty")
    data_dir = env.get("DEV_DATA_DIR", "").strip()
    if not data_dir:
        problems.append("DEV_DATA_DIR is empty")
    else:
        try:
            if not (REPO_ROOT / data_dir).is_dir():
                problems.append(f"DEV_DATA_DIR {data_dir} is not a directory")
        except PermissionError:
            pass  # a docker volume's Mountpoint: the daemon mounts it, this user cannot read it
    for key in ("DEV_ODOO_LOGIN", "DEV_ODOO_PASSWORD"):
        if not env.get(key):
            problems.append(f"{key} is not set (harness/{LOCAL_ENV_NAME})")
    return problems


def psql_args(env, sql, db="postgres"):
    """Compose arguments that run one SQL statement on the harness's PostgreSQL server: in the
    db container, or in dev DB mode with the psql of the Odoo image, on the server of
    db_server() (HOST, PORT, USER and PGPASSWORD of the odoo service)."""
    if not dev_mode(env):
        return ["exec", "-T", "db", "psql", "-U", "odoo", "-d", db, "-tAc", sql]
    script = 'exec psql -h "$HOST" -p "$PORT" -U "$USER" -d "$1" -v ON_ERROR_STOP=1 -tAc "$2"'
    return ["run", "--rm", "-T", "--entrypoint=sh", "odoo", "-c", script, "psql", db, sql]


def psql(env, sql, db="postgres"):
    """(returncode, rows as text) of one SQL statement on the harness's PostgreSQL server."""
    proc = subprocess.run(compose_cmd(env) + psql_args(env, sql, db), cwd=REPO_ROOT,
                          env=compose_env(env), capture_output=True, text=True, errors="replace")
    return proc.returncode, (proc.stdout if proc.returncode == 0 else proc.stderr).strip()


def dev_db_check(env):
    """The first reason the e2e layer must not run on DEV_DB, as a RedPen, or None."""
    problems = dev_config_problems(env)
    if problems:
        return RedPen("dev db", "the dev database settings are incomplete: " + "; ".join(problems),
                      "The e2e layer runs on the dev database only with complete, safe settings.",
                      f"Fill DEV_* and the logins in harness/{LOCAL_ENV_NAME} (see the comments "
                      "there), or empty DEV_DB to test on the test DB.")
    dev_db = env["DEV_DB"].strip()
    host, port, _user, _password = db_server(env)
    rc, out = psql(env, f"SELECT 1 FROM pg_database WHERE datname = {sql_literal(dev_db)}")
    if rc != 0:
        return RedPen("dev db", f"the dev PostgreSQL {host}:{port} is not reachable",
                      f"The harness uses the dev stack's database server. psql said: {out[-300:]}",
                      "Start the dev stack, then check DEV_DB_HOST, DEV_DB_PORT, DEV_NETWORK, "
                      f"DEV_DB_USER and DEV_DB_PASSWORD in harness/{LOCAL_ENV_NAME}.")
    if out != "1":
        return RedPen("dev db", f"the dev database '{dev_db}' does not exist on {host}:{port}",
                      "The harness never creates the dev database: it is the developer's copy of "
                      "the client's data.",
                      "Restore the client copy in the dev stack, or fix DEV_DB in "
                      f"harness/{LOCAL_ENV_NAME}.")
    rc, out = psql(env, "SELECT value FROM ir_config_parameter "
                        "WHERE key = 'database.is_neutralized'", db=dev_db)
    if rc != 0 or out.lower() not in ("true", "1"):
        return RedPen("dev db", f"the dev database '{dev_db}' is not neutralized",
                      "It holds the client's data: without neutralization the e2e tests can send "
                      "real e-mails, run scheduled actions and call payment, shipping or EDI "
                      "services.",
                      f"A human neutralizes it (odoo-bin neutralize -d {dev_db}, in the dev "
                      "stack), then runs the command again.")
    return None


def compose_files(env):
    """The engine's compose files for this project: the base stack, then the harness's own
    PostgreSQL, or the dev stack's server (its network when DEV_NETWORK is set)."""
    files = [ENGINE_DIR / "docker-compose.yml"]
    if not dev_mode(env):
        return files + [ENGINE_DIR / "docker-compose.own-db.yml"]
    files.append(ENGINE_DIR / "docker-compose.dev-db.yml")
    if env.get("DEV_NETWORK", "").strip():
        files.append(ENGINE_DIR / "docker-compose.dev-network.yml")
    return files


def render_odoo_conf(env, demo=True):
    """The test runtime's odoo.conf, from the engine template and the settings.
    demo=False: the config of the commands on the dev DB, where a module that -u installs
    (a new dependency) must not load demo data into the client's copy."""
    mounts = [f"/mnt/repo/{p}" for p in env_list(env, "CUSTOM_ADDONS")
              + env_list(env, "THIRD_PARTY_ADDONS")]
    if env.get("ENTERPRISE_DIR", "").strip():
        mounts.append("/mnt/enterprise")
    if version_tuple(env.get("ODOO_VERSION")) >= (19, 0):
        demo = f"with_demo = {demo}"
    else:
        demo = "without_demo = False" if demo else "without_demo = all"
    test_db = env.get("TEST_DB", "harness_test")
    dbs = [test_db, env["DEV_DB"].strip()] if dev_mode(env) else [test_db]
    host, port, user, _password = db_server(env)
    values = {"ADDONS_PATH": ",".join(mounts), "DEMO_OPTION": demo, "DB_HOST": host,
              "DB_PORT": port, "DB_USER": user,
              "DBFILTER": f"^({'|'.join(map(re.escape, dbs))})$" if len(dbs) > 1
              else f"^{re.escape(test_db)}$"}
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)],
                  (ENGINE_DIR / "odoo.conf").read_text())


def write_runtime(env=None):
    """Files the compose stack reads that are derived from the settings (not versioned)."""
    env = env or load_env()
    files = {ODOO_CONF: render_odoo_conf(env)}
    if dev_mode(env):
        files[ODOO_NODEMO_CONF] = render_odoo_conf(env, demo=False)
    for path, text in files.items():
        if not path.is_file() or path.read_text() != text:
            write_atomic(path, text)


def compose_env(env=None):
    """Environment of every compose call: the settings (compose interpolates the local ones
    too, the environment winning over --env-file), the engine folder with the build contexts,
    the database server of db_server(), the e2e tests logging in to the test DB, the tool
    images (one name per machine, tool_image)."""
    env = env or load_env()
    host, port, user, password = db_server(env)
    settings = {k: v for k, v in env.items() if k not in SECRET_KEYS}
    return {**os.environ, **settings, "HARNESS_HOME": str(ENGINE_DIR), "HARNESS_DB_HOST": host,
            "HARNESS_DB_PORT": port, "HARNESS_DB_USER": user, "HARNESS_DB_PASSWORD": password,
            "HARNESS_E2E_DB": env.get("TEST_DB", "harness_test"),
            "HARNESS_E2E_LOGIN": "admin", "HARNESS_E2E_PASSWORD": "admin",
            **{f"HARNESS_{name.upper()}_IMAGE": tool_image(name) for name in TOOL_IMAGES}}


# --- tool images ------------------------------------------------------------

# The lint and e2e images are the engine's, not a project's: every project of the machine
# shares one image per Dockerfile. Without a name, compose builds a private copy per project
# (<project>-e2e, 1.2 GB each).
TOOL_IMAGES = ("lint", "e2e")


def tool_image(name):
    """odoo-harness-<name>:<hash of its Dockerfile>: rebuilt only when the recipe changes."""
    recipe = (ENGINE_DIR / "docker" / f"{name}.Dockerfile").read_bytes()
    return f"odoo-harness-{name}:{hashlib.sha256(recipe).hexdigest()[:12]}"


def docker_refs(*filters):
    """repository:tag of the local images matching every filter kind (`docker image ls`)."""
    out = subprocess.run(["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}",
                          *(f"--filter={f}" for f in filters)], capture_output=True, text=True)
    return out.stdout.split()


def stale_tool_images(project):
    """Tool images no project uses any more: the copies of `project` that engines before
    3.1.1 built (<project>-lint, <project>-e2e), and the shared images of an older recipe."""
    stale = []
    for name in TOOL_IMAGES:
        if project:
            stale += docker_refs(f"reference={project}-{name}:latest",
                                 f"label=com.docker.compose.project={project}",
                                 f"label=com.docker.compose.service={name}")
        current = tool_image(name)
        stale += [ref for ref in docker_refs(f"reference={current.split(':')[0]}")
                  if ref != current]
    return stale


def prune_tool_images(project):
    for ref in stale_tool_images(project):
        # by reference: only that tag goes, and an image a container still uses is kept
        if subprocess.run(["docker", "image", "rm", ref], capture_output=True).returncode == 0:
            print(f"✓ removed unused tool image {ref}")


def dev_e2e_env(env):
    """compose_env() overrides that point the e2e tests at the dev database."""
    return {"HARNESS_E2E_DB": env["DEV_DB"].strip(), "HARNESS_E2E_LOGIN": env["DEV_ODOO_LOGIN"],
            "HARNESS_E2E_PASSWORD": env["DEV_ODOO_PASSWORD"]}


def compose_cmd(env=None):
    """The docker compose command of the harness stack, for the repository REPO_ROOT.

    Every caller goes through it (the shell scripts through `hlib.py compose`), so the
    runtime files exist and compose_env() is used."""
    env = env or load_env()
    write_runtime(env)
    base = shlex.split(os.environ.get("HARNESS_COMPOSE", "docker compose"))
    files = [arg for path in compose_files(env) for arg in ("-f", str(path))]
    return base + ["--project-directory", str(REPO_ROOT), *files,
                   "--env-file", str(HARNESS_ENV)]


def version_tuple(version):
    """'17.0' -> (17, 0); 'saas~18.3' -> (18, 3). Unknown -> (0, 0)."""
    match = re.search(r"(\d+)\.(\d+)", str(version or ""))
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def env_list(env, key):
    return [p.strip().strip("/") for p in env.get(key, "").split(",") if p.strip().strip("/")]


def custom_roots(env):
    """Folders of the project's own modules (CUSTOM_ADDONS)."""
    return [REPO_ROOT / p for p in env_list(env, "CUSTOM_ADDONS")]


def third_party_roots(env):
    """Folders of the third-party addons (THIRD_PARTY_ADDONS: OCA and other vendors)."""
    return [REPO_ROOT / p for p in env_list(env, "THIRD_PARTY_ADDONS")]


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


def module_of(env, path, roots=None):
    """Name of the module under roots (default: the custom ones) that contains path
    (repo-relative or absolute), or None."""
    path = Path(path)
    path = path if path.is_absolute() else REPO_ROOT / path
    for root in custom_roots(env) if roots is None else roots:
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


def changed_modules(env, since=None, roots=None):
    """Modules under roots (default: the custom ones) with changes on this branch (since
    `since`, or the base branch)."""
    since = since or base_ref(env)
    names = {module_of(env, f, roots) for f in changed_files(since)}
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

def task_sort_key(task):
    """Natural order, the same in every clone: T9300 before T10283."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", task)]


def task_file(task):
    return TASKS_DIR / f"{task}.json"


def load_features():
    """Every feature of every task file, in one view: {"version": 1, "features": [...]}, each
    feature with its `task`. Tasks in natural order, features in file order."""
    if not TASKS_DIR.is_dir():
        if LEGACY_FEATURE_LIST.exists():
            raise RedPen("features", "this project still keeps its features in feature_list.json",
                         f"odoo-harness {ENGINE_VERSION} keeps each task's features in its own "
                         "file, tasks/<task>.json, so that developers working on different "
                         "tasks never change the same file.",
                         "Run /odoo-harness:update (it moves the features into tasks/, keeping "
                         "their ids), then commit the result.")
        raise RedPen("features", "tasks/ not found",
                     "The harness keeps the work split into features, one file per task in "
                     "tasks/<task>.json.",
                     "Run the odoo-harness init skill (/odoo-harness:init), or restore tasks/ "
                     "from git.")
    features = []
    paths = sorted(TASKS_DIR.glob("*.json"), key=lambda p: task_sort_key(p.stem))
    for path in paths:
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            content = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise RedPen("features", f"{rel} is not valid JSON (line {exc.lineno})",
                         "The file was edited by hand and broken.",
                         f"Restore it with `git checkout {rel}`, then use odoo-harness feature.")
        problems = validate_task_file(content, path.stem)
        if problems:
            raise RedPen("features", f"{rel} is invalid: " + "; ".join(problems),
                         "The file does not match the harness format, probably edited by hand.",
                         f"Restore it with `git checkout {rel}`; change it only with "
                         "odoo-harness feature.")
        features += [{**feat, "task": path.stem} for feat in content["features"]]
    data = {"version": 1, "features": features}
    problems = validate(data)
    if problems:
        raise RedPen("features", "the task files are inconsistent: " + "; ".join(problems),
                     "Two task files disagree, usually after a merge or a hand edit.",
                     "Restore the files with git (git checkout <ref> -- tasks/<task>.json); "
                     "change them only with odoo-harness feature.")
    return data


def validate_task_file(content, task):
    if not TASK_RE.match(task):
        return [f"the file name must be a task name (letters, digits, - and _), not {task!r}"]
    if not isinstance(content, dict) or content.get("version") != TASK_FILE_VERSION or not \
            isinstance(content.get("features"), list) or content.get("task") != task:
        return [f'expected {{"version": {TASK_FILE_VERSION}, "task": "{task}", "features": '
                '[...]}']
    return [f"features[{i}] is not an object" for i, feat in enumerate(content["features"])
            if not isinstance(feat, dict)]


def validate(data):
    """Problems of the view returned by load_features (every feature with its task)."""
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
        if set(feat) != FEATURE_KEYS | {"task"}:
            problems.append(f"{fid}: keys must be {sorted(FEATURE_KEYS)}")
            continue
        if not (isinstance(feat["task"], str) and TASK_RE.match(feat["task"])):
            problems.append(f"{fid}: task must use only letters, digits, - and _ "
                            "(T2003, remise-devis)")
        if not isinstance(fid, str) or not ID_RE.match(fid):
            problems.append(f"{fid}: id must look like F-T2003-1 (or F-001)")
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
    # WIP = 1 per task: a task is worked on one branch. Two tasks may each have a feature in
    # progress, on two developers' branches; feature start keeps one per checkout.
    by_task = {}
    for f in data["features"]:
        if isinstance(f, dict) and f.get("state") == "in_progress":
            by_task.setdefault(f.get("task"), []).append(str(f.get("id")))
    for task, ids in by_task.items():
        if len(ids) > 1:
            problems.append(f"WIP = 1 violated in task {task}, in_progress: {', '.join(ids)}")
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
    """Write each task's file, only where it changed: a command on one task never rewrites the
    file of another. A task left without features (renamed) loses its file."""
    problems = validate(data)
    if problems:
        raise AssertionError("refusing to save an invalid feature list: " + "; ".join(problems))
    tasks = {}
    for feat in data["features"]:
        tasks.setdefault(feat["task"], []).append(
            {k: v for k, v in feat.items() if k != "task"})
    for task, feats in tasks.items():
        text = json.dumps({"version": TASK_FILE_VERSION, "task": task, "features": feats},
                          indent=2, ensure_ascii=False) + "\n"
        path = task_file(task)
        if not path.is_file() or path.read_text() != text:
            write_atomic(path, text)
    for path in TASKS_DIR.glob("*.json"):
        if path.stem not in tasks:
            path.unlink()


def task_features(data, task):
    return [f for f in data["features"] if f.get("task") == task]


def in_progress_here(data):
    """The features in progress in this checkout: those of the task of the current branch, and
    those started here (.harness/state.json, e.g. with --no-branch). Another task's feature in
    progress is another branch's work, merged here: it is not this checkout's WIP."""
    branch, started = current_branch(), load_state()
    return [f for f in data["features"]
            if f["state"] == "in_progress" and (f["task"] == branch or f["id"] in started)]


def commit_message(feat):
    """Commit message of a verified feature: [T2003] F-T2003-1 behavior."""
    return f"[{feat['task']}] {feat['id']} {feat['behavior']}"


def current_branch():
    return git("symbolic-ref", "-q", "--short", "HEAD")


def find_feature(data, fid):
    for feat in data["features"]:
        if feat["id"] == fid:
            return feat
    raise RedPen("features", f"unknown feature {fid}",
                 "There is no feature with this id in the task files of this branch (tasks/).",
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


# --- task notes: tasks/<task>.md ------------------------------------------------
# The progress of one task, written on its branch only: its feature lines (kept by the
# harness), what is done and left, its known issues, decisions and next steps. PROGRESS.md
# keeps what concerns the whole project; the harness does not write it.

def notes_file(task):
    return TASKS_DIR / f"{task}.md"


def _notes_lines(task):
    path = notes_file(task)
    if path.exists():
        return path.read_text().splitlines()
    lines = [f"# Task {task}"]
    for section in NOTES_SECTIONS:
        lines += ["", f"## {section}"]
    return lines


def _feature_line_re(fid):
    return re.compile(rf"^- \[[ xX]\] {re.escape(fid)}\b")


def notes_set_feature(feat, line):
    """The line of a feature, under Features of its task's notes (replacing the old one)."""
    lines = [ln for ln in _notes_lines(feat["task"]) if not _feature_line_re(feat["id"]).match(ln)]
    write_atomic(notes_file(feat["task"]),
                 "\n".join(_append_to_section(lines, "Features", line)) + "\n")


def notes_append(task, section, line):
    write_atomic(notes_file(task),
                 "\n".join(_append_to_section(_notes_lines(task), section, line)) + "\n")


def notes_rename(old, new):
    """Move tasks/<old>.md to tasks/<new>.md, with its title."""
    path = notes_file(old)
    if path.exists():
        text = re.sub(rf"^# Task {re.escape(old)}$", f"# Task {new}", path.read_text(), count=1,
                      flags=re.M)
        write_atomic(notes_file(new), text)
        path.unlink()


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
    elif sys.argv[1:] == ["localenv"]:
        try:
            if ensure_local_env():
                print(f"created harness/{LOCAL_ENV_NAME}: this machine's settings (not versioned)")
        except RedPen as pen:
            print(pen, file=sys.stderr)
            sys.exit(1)
    elif sys.argv[1:] == ["shellenv"]:
        print(shell_exports(load_env()), end="")
    elif sys.argv[1:] == ["runtime"]:
        write_runtime()
    elif sys.argv[1:2] == ["compose"]:
        cmd = compose_cmd() + sys.argv[2:]
        os.execvpe(cmd[0], cmd, compose_env())
    elif len(sys.argv) == 3 and sys.argv[1] == "psql":
        cmd = compose_cmd() + psql_args(load_env(), sys.argv[2])
        os.execvpe(cmd[0], cmd, compose_env())
    elif sys.argv[1:] == ["prune-images"]:
        prune_tool_images(load_env().get("COMPOSE_PROJECT_NAME", ""))
    elif sys.argv[1:] == ["devcheck"]:
        pen = dev_db_check(load_env())
        if pen:
            print(pen, file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit("usage: hlib.py modules | localenv | shellenv | runtime | compose ARGS... | psql SQL | "
                 "devcheck | prune-images")
