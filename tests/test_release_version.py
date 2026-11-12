import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "tools" / "check_release_version.py"


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def write_version(repo, version):
    market = {"plugins": [{"name": "odoo-harness", "version": version}]}
    path = repo / ".claude-plugin" / "marketplace.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(market))


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    write_version(repo, "1.0.0")
    (repo / "hooks").mkdir()
    (repo / "hooks" / "a.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "change")
    return repo


def commit(repo, path, text):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", path)


def run(repo):
    return subprocess.run([sys.executable, str(CHECK), "main"], cwd=repo,
                          capture_output=True, text=True)


def test_shipped_change_without_bump_fails(tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "hooks/a.py", "x = 2\n")
    result = run(repo)
    assert result.returncode == 1
    assert "hooks/a.py" in result.stdout and "HOW TO FIX" in result.stdout


def test_shipped_change_with_bump_passes(tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "hooks/a.py", "x = 2\n")
    write_version(repo, "1.0.1")
    git(repo, "commit", "-qam", "bump")
    assert run(repo).returncode == 0


def test_lower_version_fails(tmp_path):
    repo = make_repo(tmp_path)
    write_version(repo, "0.9.0")
    git(repo, "commit", "-qam", "lower")
    assert run(repo).returncode == 1


def test_developer_only_change_needs_no_bump(tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "tests/test_x.py", "def test(): pass\n")
    commit(repo, "README.md", "doc\n")
    assert run(repo).returncode == 0
