import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

import install_template  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))

from make_demo_project import adapt_fixture_module, write_layout  # noqa: E402

ODOO_VERSION = install_template.ODOO_VERSION
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
        return self.run(sys.executable, "harness/feature.py", *args, **fake)

    def verify(self, *args, **fake):
        return self.run(sys.executable, "harness/verify.py", *args, **fake)

    def features(self):
        return json.loads((self.path / "feature_list.json").read_text())["features"]

    def calls(self):
        if not self.calls_file.exists():
            return []
        return [json.loads(line) for line in self.calls_file.read_text().splitlines()]

    def services_run(self):
        """Compose services started with `run`, in order."""
        out = []
        for argv in self.calls():
            args = argv[argv.index("--env-file") + 2:]
            if args[0] == "run":
                out.append([a for a in args[1:] if not a.startswith("-")][0])
        return out

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True)

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


@pytest.fixture
def hrepo(tmp_path):
    target = tmp_path / "client"
    target.mkdir()
    write_layout(target, client="client")
    module = target / MODULE_DIR
    shutil.copytree(TESTS / "fixtures" / "demo_mod", module,
                    ignore=shutil.ignore_patterns("__pycache__"))
    adapt_fixture_module(module)
    repo = HarnessRepo(target, tmp_path / "calls.jsonl")
    repo.git("init", "-q", "-b", "staging")
    install_template.main([str(target), "--enterprise-dir", ""])
    repo.commit("initial")
    return repo


E2E_FILE = "e2e/test_F001_thing.py"
MODULE_DIR = "extra-addons/client/demo_mod"


def add_feature(repo, behavior="User creates a demo thing", e2e=E2E_FILE):
    result = repo.feature("add", "--behavior", behavior, "--verify", "unit: /demo_mod:TestThing",
                          "--verify", f"e2e: {e2e}")
    assert result.returncode == 0, result.stderr
    (repo.path / e2e).write_text("def test_thing(odoo_page):\n    pass\n")
    return result
