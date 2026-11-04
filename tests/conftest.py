import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
ENGINE = ROOT / "engine"
# The harness command, as a developer runs it (bin/odoo-harness -> engine/cli.py).
CLI = str(ROOT / "bin" / "odoo-harness")
sys.path.insert(0, str(ROOT / "scripts"))

import install_template  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))

from make_demo_project import adapt_fixture_module, write_layout  # noqa: E402

# The suite runs for one Odoo version at a time; CI runs it for each (a matrix).
ODOO_VERSION = os.environ.get("HARNESS_TEST_ODOO_VERSION", "20.0")
assert ODOO_VERSION in install_template.VERSIONS, f"unsupported HARNESS_TEST_ODOO_VERSION {ODOO_VERSION}"
IR_ACCESS = tuple(int(x) for x in ODOO_VERSION.split(".")) >= (20, 0)


class HarnessRepo:
    """An Odoo repository with the harness installed, driven through its real scripts."""

    def __init__(self, path, calls):
        self.path = path
        self.calls_file = calls
        self.env = {**os.environ, "HARNESS_COMPOSE": f"{sys.executable} {TESTS / 'fake_compose.py'}",
                    "FAKE_CALLS": str(calls)}

    def run(self, *args, **fake):
        env = {**self.env, **{k.upper(): str(v) for k, v in fake.items()}}
        return subprocess.run(list(args), cwd=self.path, env=env, capture_output=True, text=True)

    def feature(self, *args, **fake):
        return self.run(CLI, "feature", *args, **fake)

    def verify(self, *args, **fake):
        return self.run(CLI, "verify", *args, **fake)

    def features(self):
        """Every feature with its task, as the engine reads them (tasks/<task>.json)."""
        out = []
        for path in sorted((self.path / "tasks").glob("*.json")):
            out += [{**f, "task": path.stem} for f in json.loads(path.read_text())["features"]]
        return out

    def calls(self):
        if not self.calls_file.exists():
            return []
        return [json.loads(line) for line in self.calls_file.read_text().splitlines()]

    def services_run(self):
        """Compose services started with `run`, in order (psql statements apart: psql_calls)."""
        out = []
        for argv in self.calls():
            args = argv[argv.index("--env-file") + 2:]
            if args[0] == "run" and "--entrypoint=sh" not in args:
                out.append([a for a in args[1:] if not a.startswith("-")][0])
        return out

    def psql_calls(self):
        """(database, SQL) of each psql statement run through hlib.psql_args, in order."""
        out = []
        for argv in self.calls():
            args = argv[argv.index("--env-file") + 2:]
            if args[0] == "run" and "--entrypoint=sh" in args:
                out.append((args[-2], args[-1]))
        return out

    def compose_files(self):
        """The -f files of the last compose call, by name."""
        argv = self.calls()[-1]
        return [Path(argv[i + 1]).name for i, a in enumerate(argv) if a == "-f"]

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True)

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


@pytest.fixture(autouse=True, scope="session")
def harness_home(tmp_path_factory):
    """The hooks and `odoo-harness link` write ~/.odoo-harness and ~/.local/bin/odoo-harness:
    keep them out of the real home."""
    home = tmp_path_factory.mktemp("home")
    real = [Path.home() / ".odoo-harness", Path.home() / ".local" / "bin" / "odoo-harness"]
    existed = {p: p.is_symlink() or p.exists() for p in real}
    saved = {k: os.environ.get(k) for k in ("ODOO_HARNESS_HOME", "ODOO_HARNESS_BIN")}
    os.environ["ODOO_HARNESS_HOME"] = str(home / ".odoo-harness")
    os.environ["ODOO_HARNESS_BIN"] = str(home / ".local" / "bin")
    yield home
    touched = [str(p) for p in real if (p.is_symlink() or p.exists()) and not existed[p]]
    assert not touched, f"the tests wrote into the real home: {touched}"
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def hrepo(tmp_path):
    target = tmp_path / "client"
    target.mkdir()
    write_layout(target, client="client", version=ODOO_VERSION)
    module = target / MODULE_DIR
    shutil.copytree(TESTS / "fixtures" / "demo_mod", module,
                    ignore=shutil.ignore_patterns("__pycache__"))
    adapt_fixture_module(module, ODOO_VERSION)
    repo = HarnessRepo(target, tmp_path / "calls.jsonl")
    repo.git("init", "-q", "-b", "staging")
    install_template.main([str(target), "--enterprise-dir", ""])
    repo.commit("initial")
    return repo


E2E_FILE = "e2e/test_T1_1_thing.py"
MODULE_DIR = "extra-addons/client/demo_mod"
# The task of the features add_feature creates; tests of the task workflow use their own.
TASK = "T1"


def add_feature(repo, behavior="User creates a demo thing", e2e=E2E_FILE):
    """A feature of task T1: the first one checks out the branch T1 (the task workflow is
    tested in test_tasks.py)."""
    result = repo.feature("add", "--task", TASK, "--behavior", behavior,
                          "--verify", "unit: /demo_mod:TestThing", "--verify", f"e2e: {e2e}")
    assert result.returncode == 0, result.stderr
    (repo.path / e2e).write_text("def test_thing(odoo_page):\n    pass\n")
    return result
