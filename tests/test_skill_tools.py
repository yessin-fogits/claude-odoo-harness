import importlib.util
import json
import re
import sys

import pytest

from conftest import CLI, ROOT

TOOLS = ROOT / "tools" / "odoo-skill-extract"


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


extract = load("extract")
check_skill = load("check_skill")


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def mini_odoo(tmp_path):
    """A tiny Odoo-shaped source tree with the files extract.py reads (20.0 style)."""
    src = tmp_path / "odoo"
    put(src, "odoo/release.py", "version_info = (20, 0, 0, FINAL, 0, '')\n")
    put(src, "odoo/api/__init__.py",
        "from odoo.orm.decorators import (\n    depends,\n    model,\n    private,\n)\n"
        "from odoo.orm.cache import ormcache\n")
    put(src, "odoo/models/__init__.py",
        "from odoo.orm.models import AbstractModel, Model\n"
        "from odoo.orm.table_objects import Constraint\n")
    put(src, "odoo/fields/__init__.py",
        "from odoo.orm.fields_textual import Char\nfrom odoo.orm.domains import Domain\n")
    put(src, "odoo/orm/fields_textual.py",
        "class Char(_String):\n    \"\"\"doc\"\"\"\n    type = 'char'\n    size = None\n")
    put(src, "odoo/orm/models.py",
        "import warnings\nwarnings.warn('Since 20.0, use only SQL in the where clause', "
        "DeprecationWarning)\n")
    put(src, "odoo/tests/__init__.py", "from .common import *\nfrom .form import Form\n")
    put(src, "odoo/tests/common.py", "class TransactionCase:\n    pass\ndef tagged(*a):\n    pass\n")
    put(src, "odoo/addons/base/rng/list_view.rng", '<rng:element name="list">\n')
    put(src, "odoo/addons/base/security/ir.access.csv",
        "id,name,model_id,group_id/id,operation,domain\n")
    put(src, "odoo/http/dispatcher.py",
        "class A:\n    routing_type = 'http'\nclass B:\n    routing_type = 'jsonrpc'\n")
    put(src, "odoo/upgrade_code/19.4-00-ir-access.py", "")
    put(src, "odoo/modules/module.py", "_DEFAULT_MANIFEST = {\n    'data': [],\n    'depends': [],\n}\n")
    put(src, "addons/web/static/lib/owl/owl.js",
        'var version = "3.0.0-alpha.1";\n__export(index_exports, {\n  Component: () => Component,\n'
        '  proxy: () => proxy,\n  __info__: () => __info__\n});\n')
    return src


def test_extract_reads_the_source(mini_odoo):
    facts = extract.extract(mini_odoo)
    assert facts["odoo_version"] == "20.0"
    assert facts["api_decorators"] == ["depends", "model", "private"]
    assert "ormcache" in facts["api_exports"]
    assert facts["models_exports"] == ["AbstractModel", "Constraint", "Model"]
    assert facts["field_types"] == {"Char": "char"}
    assert facts["list_view_tag"] == "list"
    assert facts["security"] == {"model": "ir.access", "csv": "ir.access.csv",
                                 "header": "id,name,model_id,group_id/id,operation,domain",
                                 "record_rules": False}
    assert facts["route_types"] == ["http", "jsonrpc"]
    assert facts["owl_version"] == "3.0.0-alpha.1"
    assert facts["owl_exports"] == ["Component", "proxy"]
    assert facts["tests_exports"] == ["Form", "TransactionCase", "tagged"]
    assert facts["upgrade_steps"] == ["19.4-00-ir-access"]
    assert facts["manifest_keys"] == ["data", "depends"]
    assert facts["deprecations"] == ["Since 20.0, use only SQL in the where clause"]


def test_extract_rejects_non_odoo_dir(tmp_path):
    with pytest.raises(SystemExit):
        extract.extract(tmp_path)


def make_skill(root, facts, refs):
    skill = root / "skill"
    put(skill, "GUIDE.md", f"# Odoo {facts['odoo_version']}\n\nReference.\n")
    for name, text in refs.items():
        put(skill, f"references/{name}", text)
    check_skill.check(facts, skill, write=True)
    return skill


def test_check_accepts_matching_skill(mini_odoo, tmp_path):
    facts = extract.extract(mini_odoo)
    skill = make_skill(tmp_path, facts, {"orm.md": (
        "Use `@api.depends` (`from odoo.fields import Domain`); never `bool(domain)`.\n"
        "```python\nfrom odoo.fields import Char, Domain\n\n\nclass A:\n"
        "    pass\nfrom odoo.api import (\n    depends,\n    model,\n)\n"
        "name = fields.Char()\n"
        "_uniq = models.Constraint('UNIQUE(name)')\n"
        "@http.route('/x', type='jsonrpc')\n```\n"
        "```python\nfrom odoo.tests import TransactionCase, tagged\n```\n"
        "```javascript\nimport { Component, proxy } from \"@odoo/owl\";\n```\n"
        "```xml\n<list><field name=\"name\"/></list>\n```\nSee security/ir.access.csv.\n")})
    assert check_skill.check(facts, skill) == []


@pytest.mark.parametrize("snippet,problem", [
    ("`@api.returns`", "@api.returns does not exist"),
    ("`models.TransientModel`", "models.TransientModel does not exist"),
    ("`fields.Monetary()`", "fields.Monetary does not exist"),
    ("```python\nfrom odoo.tests import SingleTransactionCase\n```", "odoo.tests.SingleTransactionCase"),
    ('```js\nimport { useState } from "@odoo/owl";\n```', "@odoo/owl does not export useState"),
    ("```python\n@http.route('/x', type='json')\n```", "route type='json' does not exist"),
    ("```xml\n<tree/>\n```", "<tree> in a code block"),
    ("Add a line to ir.model.access.csv", "ir.model.access is not the access format"),
    ("```python\nfrom odoo.fields import Monetary\n```", "odoo.fields.Monetary does not exist"),
    ("```python\nfrom odoo.api import returns\n```", "odoo.api.returns does not exist"),
])
def test_check_finds_wrong_api(mini_odoo, tmp_path, snippet, problem):
    facts = extract.extract(mini_odoo)
    skill = make_skill(tmp_path, facts, {"orm.md": snippet + "\n"})
    problems = check_skill.check(facts, skill)
    assert any(problem in p for p in problems), problems


def test_version_notes_are_exempt(mini_odoo, tmp_path):
    facts = extract.extract(mini_odoo)
    skill = make_skill(tmp_path, facts, {"version-notes.md": "`<tree>` became `<list>`; "
                                         "ir.model.access.csv became ir.access.csv.\n"})
    assert check_skill.check(facts, skill) == []


def test_stale_version_facts_detected(mini_odoo, tmp_path):
    facts = extract.extract(mini_odoo)
    skill = make_skill(tmp_path, facts, {})
    facts["owl_version"] = "3.0.1"
    assert any("out of date" in p for p in check_skill.check(facts, skill))


def test_new_odoo_commit_alone_is_not_stale(mini_odoo, tmp_path):
    facts = extract.extract(mini_odoo)
    facts["source_commit"] = "aaaaaaaaaaaa"
    skill = make_skill(tmp_path, facts, {})
    facts["source_commit"] = "bbbbbbbbbbbb"
    assert check_skill.check(facts, skill) == []


def test_title_must_name_version(mini_odoo, tmp_path):
    facts = extract.extract(mini_odoo)
    skill = make_skill(tmp_path, facts, {})
    (skill / "GUIDE.md").write_text("# Odoo\n")
    assert any("title" in p for p in check_skill.check(facts, skill))


def test_cli(mini_odoo, tmp_path):
    facts_path = tmp_path / "facts.json"
    assert extract.main([str(mini_odoo), "-o", str(facts_path)]) == 0
    skill = make_skill(tmp_path, json.loads(facts_path.read_text()), {})
    assert check_skill.main([str(facts_path), str(skill)]) == 0


VERSIONS = json.loads((ROOT / "versions.json").read_text())


@pytest.mark.parametrize("version", sorted(VERSIONS))
def test_every_version_has_its_guide(version):
    """Each supported version has a guide whose facts describe that version."""
    guide = ROOT / "skills" / "odoo" / "versions" / version
    facts_md = (guide / "references" / "version-facts.md").read_text()
    assert facts_md.startswith(f"# Odoo {version}: version facts")
    assert (guide / "GUIDE.md").read_text().startswith(f"# Odoo {version}\n")


def test_no_guide_without_a_version():
    guides = {p.name for p in (ROOT / "skills" / "odoo" / "versions").iterdir()}
    assert guides == set(VERSIONS)


FENCE_LANG = {"python": ".py", "xml": ".xml", "javascript": ".js", "js": ".js"}


def test_skill_examples_pass_the_harness_version_rules(hrepo):
    """Code shown by the skill must not be rejected by the harness for the same version."""
    from conftest import ODOO_VERSION
    SKILL_DIR = ROOT / "skills" / "odoo" / "versions" / ODOO_VERSION
    examples = hrepo.path / "extra-addons" / "client" / "demo_mod" / "skill_examples"
    examples.mkdir()
    files = []
    for ref in sorted((SKILL_DIR / "references").glob("*.md")):
        if ref.name in check_skill.EXEMPT:
            continue
        for i, m in enumerate(re.finditer(r"```(\w+)\n(.*?)```", ref.read_text(), re.S)):
            suffix = FENCE_LANG.get(m.group(1))
            if suffix:
                path = examples / f"{ref.stem}_{i}{suffix}"
                path.write_text(m.group(2))
                files.append(str(path))
    assert files
    result = hrepo.run(CLI, "static", *files,
                       odoo_version=ODOO_VERSION)
    flagged = [line for line in result.stderr.splitlines() if "[odoo-version-api]" in line]
    assert not flagged, "\n".join(flagged)
