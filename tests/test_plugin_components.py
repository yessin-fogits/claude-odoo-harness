import json
import re
import shutil
import sys

import pytest

from conftest import ODOO_VERSION, ROOT


def frontmatter(path):
    text = path.read_text()
    assert text.startswith("---\n"), path
    head = text.split("---")[1]
    return dict(re.findall(r"^([\w-]+):\s*(.*)$", head, re.M))


def test_plugin_name_matches_branch_version():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == f"odoo-harness-{ODOO_VERSION.split('.')[0]}"
    assert ODOO_VERSION in manifest["description"]


@pytest.mark.parametrize("skill", sorted(p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")))
def test_skills_have_frontmatter(skill):
    meta = frontmatter(ROOT / "skills" / skill / "SKILL.md")
    assert meta.get("description"), skill


def test_init_is_user_only_and_its_script_exists():
    meta = frontmatter(ROOT / "skills" / "init" / "SKILL.md")
    assert meta["disable-model-invocation"] == "true"
    text = (ROOT / "skills" / "init" / "SKILL.md").read_text()
    for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text):
        assert (ROOT / rel).exists(), rel


@pytest.mark.parametrize("agent", ["odoo-reviewer", "odoo-explorer"])
def test_agents_are_read_only(agent):
    meta = frontmatter(ROOT / "agents" / f"{agent}.md")
    assert meta["name"] == agent and meta["description"]
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert not tools & {"Edit", "Write", "NotebookEdit"}


def test_add_harness_check_template_works(hrepo):
    """Filling the template the way the skill says gives a working project check."""
    skill = ROOT / "skills" / "add-harness-check"
    for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", (skill / "SKILL.md").read_text()):
        assert (ROOT / rel).exists(), rel
    check = hrepo.path / "harness" / "checks" / "sudo_browse.py"
    shutil.copy(skill / "check_template.py", check)
    text = check.read_text()
    text = text.replace('"<kebab-case-id>"', '"sudo-browse-request-ids"')
    text = text.replace('"<why it is wrong: the consequence for users or data>"',
                        '"Any user can read any record by passing its id."')
    text = text.replace('"<what to write instead, concrete>"',
                        '"Browse without sudo() and call check_access(\'read\')."')
    text = text.replace('r"<regex that matches the mistake on one line>"',
                        r'r"sudo\(\)\.browse\(.*(kw|params|post)\["')
    check.write_text(text)

    bad = hrepo.path / "addons" / "demo_mod" / "controllers.py"
    bad.write_text("def get(self, **kw):\n    return env['x'].sudo().browse(kw['id'])\n")
    result = hrepo.run(sys.executable, "harness/static_checks.py", str(bad),
                       odoo_version=ODOO_VERSION)
    assert "[sudo-browse-request-ids]" in result.stderr
    assert "WHY: Any user can read any record" in result.stderr
    bad.write_text("def get(self, **kw):\n    return env['x'].browse(int(kw['id']))\n")
    result = hrepo.run(sys.executable, "harness/static_checks.py", str(bad),
                       odoo_version=ODOO_VERSION)
    assert result.returncode == 0, result.stderr
