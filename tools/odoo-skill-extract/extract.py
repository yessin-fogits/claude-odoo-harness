#!/usr/bin/env python3
"""Extract version facts from an Odoo source tree, without importing Odoo.

    extract.py ODOO_SRC [-o facts.json]

ODOO_SRC is a checkout of github.com/odoo/odoo (a sparse checkout is enough, see
fetch_odoo.sh). The facts feed the skill (references/version-facts.md is
generated from them) and check_skill.py, which verifies that the skill's
references only use API that exists in that version.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

DEPRECATION_RE = re.compile(
    r"""warn(?:ings\.warn)?\(\s*(?:f?["'](?P<msg>(?:[^"'\\]|\\.){10,300})["'])[^)]*DeprecationWarning""",
    re.S)


def read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError):
        return ""


def first_existing(src, *candidates):
    for rel in candidates:
        if (src / rel).exists():
            return src / rel
    return None


def odoo_version(src):
    text = read(src / "odoo" / "release.py")
    match = re.search(r"version_info\s*=\s*\((\d+),\s*(\d+)", text)
    if not match:
        raise SystemExit(f"{src}: odoo/release.py has no version_info, not an Odoo checkout?")
    return f"{match.group(1)}.{match.group(2)}"


def exported_names(path):
    """Names a module makes public: its imports, top-level defs and assignments."""
    if path is None or not path.exists():
        return []
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        return []
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname or a.name for a in node.names if a.name != "*"}
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return sorted(n for n in names if not n.startswith("_"))


def module_path(src, dotted):
    """odoo/api -> odoo/api/__init__.py or odoo/api.py, whichever exists."""
    base = src / dotted
    return first_existing(src, f"{dotted}/__init__.py", f"{dotted}.py") if base else None


def field_types(src):
    """{class name: field type} for every Field subclass that sets `type = '...'`."""
    files = sorted((src / "odoo" / "orm").glob("fields*.py")) or [src / "odoo" / "fields.py"]
    out = {}
    for path in files:
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                targets = stmt.targets if isinstance(stmt, ast.Assign) else (
                    [stmt.target] if isinstance(stmt, ast.AnnAssign) else [])
                if any(isinstance(t, ast.Name) and t.id == "type" for t in targets) and \
                        isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    out[node.name] = stmt.value.value
    return dict(sorted(out.items()))


def view_rng(src):
    rng_dir = src / "odoo" / "addons" / "base" / "rng"
    files = sorted(p.name for p in rng_dir.glob("*.rng"))
    list_tag = None
    for name in ("list_view.rng", "tree_view.rng"):
        text = read(rng_dir / name)
        match = re.search(r'<rng:element name="(list|tree)"', text)
        if match:
            list_tag = match.group(1)
            break
    return files, list_tag


def security(src):
    base_sec = src / "odoo" / "addons" / "base" / "security"
    for name, model in (("ir.access.csv", "ir.access"), ("ir.model.access.csv", "ir.model.access")):
        path = base_sec / name
        if path.exists():
            header = read(path).splitlines()[0].strip()
            return {"model": model, "csv": name, "header": header,
                    "record_rules": (src / "odoo/addons/base/models/ir_rule.py").exists()}
    return {"model": None, "csv": None, "header": None, "record_rules": None}


def route_types(src):
    texts = [read(p) for p in sorted((src / "odoo" / "http").glob("*.py"))] or [
        read(src / "odoo" / "http.py")]
    found = set()
    for text in texts:
        found |= set(re.findall(r"routing_type\s*=\s*['\"](\w+)['\"]", text))
    return sorted(found)


def owl_version(src):
    text = read(src / "addons" / "web" / "static" / "lib" / "owl" / "owl.js")
    match = re.search(r"""version\s*=\s*["'](\d+\.\d+\.\d+[^"']*)["']""", text)
    return match.group(1) if match else None


def owl_exports(src):
    """Public names of the bundled OWL (esbuild export map in owl.js)."""
    text = read(src / "addons" / "web" / "static" / "lib" / "owl" / "owl.js")
    match = re.search(r"__export\(\w+,\s*\{(.*?)\n\s*\}\);", text, re.S)
    if match:
        return sorted(set(re.findall(r"^\s*(\w+):", match.group(1), re.M)) - {"__info__"})
    match = re.search(r"exports\.(\w+)\s*=", text)  # OWL 2 bundles: exports.X = X;
    return sorted(set(re.findall(r"\bexports\.(\w+)\s*=", text)) - {"__info__"}) if match else []


def test_api(src):
    names = set(exported_names(module_path(src, "odoo/tests")))
    common = src / "odoo" / "tests" / "common.py"
    tree = ast.parse(read(common)) if common.exists() else ast.Module(body=[], type_ignores=[])
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and not node.name.startswith("_"):
            names.add(node.name)
    keep = {"BaseCase", "TransactionCase", "SingleTransactionCase", "HttpCase", "Form", "tagged",
            "users", "warmup", "new_test_user", "freeze_time", "no_retry", "Like", "RecordCapturer",
            "standalone", "can_import", "loaded_demo_data", "O2MProxy", "M2MProxy"}
    return sorted(names & keep)


def upgrade_steps(src):
    folder = src / "odoo" / "upgrade_code"
    return sorted(p.stem for p in folder.glob("[0-9]*.py"))


def deprecations(src):
    roots = [src / "odoo" / d for d in ("orm", "api", "fields", "models", "tools", "http")]
    roots += [src / "odoo" / f for f in ("models.py", "fields.py", "api.py", "http.py")]
    messages = set()
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*.py")) if root.is_dir() else []
        for path in files:
            for match in DEPRECATION_RE.finditer(read(path)):
                msg = " ".join(match.group("msg").split())
                messages.add(msg)
    return sorted(messages)


def manifest_keys(src):
    text = read(src / "odoo" / "modules" / "module.py")
    match = re.search(r"_DEFAULT_MANIFEST\s*=\s*\{(.*?)\n\}", text, re.S)
    return sorted(set(re.findall(r"^\s*['\"](\w+)['\"]\s*:", match.group(1), re.M))) if match else []


def extract(src):
    src = Path(src).resolve()
    rng_files, list_tag = view_rng(src)
    api_path = module_path(src, "odoo/api")
    decorators = [n for n in exported_names(api_path)
                  if n in {"autovacuum", "constrains", "depends", "depends_context", "model",
                           "model_create_multi", "onchange", "ondelete", "private", "readonly",
                           "returns"}]
    return {
        "odoo_version": odoo_version(src),
        "api_decorators": decorators,
        "api_exports": exported_names(api_path),
        "models_exports": exported_names(module_path(src, "odoo/models")),
        "fields_exports": exported_names(module_path(src, "odoo/fields")),
        "field_types": field_types(src),
        "view_rng_files": rng_files,
        "list_view_tag": list_tag,
        "security": security(src),
        "route_types": route_types(src),
        "owl_version": owl_version(src),
        "owl_exports": owl_exports(src),
        "tests_exports": test_api(src),
        "manifest_keys": manifest_keys(src),
        "upgrade_steps": upgrade_steps(src),
        "deprecations": deprecations(src),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("odoo_src", type=Path)
    p.add_argument("-o", "--output", type=Path, help="write the JSON here instead of stdout")
    args = p.parse_args(argv)
    facts = extract(args.odoo_src)
    text = json.dumps(facts, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
