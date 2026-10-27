#!/usr/bin/env python3
"""Layer 1 static checks that need no Odoo and no Docker (standard library only).

    harness/static_checks.py              check all modules in scope
    harness/static_checks.py FILE...      check only these files (used after each edit)

Checks: Python compiles, XML is well formed, manifests are consistent, security CSV
headers, and the project checks in harness/checks/ (born from code reviews).
"""

import ast
import csv
import importlib.util
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hlib  # noqa: E402

# Security CSV formats. Odoo 20 merged ir.model.access and ir.rule into ir.access.
MODEL_ACCESS_HEADER = ["id", "name", "model_id:id", "group_id:id", "perm_read", "perm_write",
                       "perm_create", "perm_unlink"]
IR_ACCESS_HEADER = ["id", "name", "model_id", "group_id/id", "operation", "domain"]
IR_ACCESS_OPERATIONS = {"crud", "cru", "crd", "cud", "rud", "cr", "cu", "cd", "ru", "rd", "ud",
                        "c", "r", "u", "d"}
CHECKS_DIR = hlib.HARNESS_DIR / "checks"


@dataclass
class Finding:
    path: str
    line: int
    what: str
    why: str
    fix: str

    def redpen(self):
        return hlib.format_redpen("L1 static", f"{self.path}:{self.line}: {self.what}",
                                  self.why, self.fix)


def rel(path):
    try:
        return str(Path(path).resolve().relative_to(hlib.REPO_ROOT))
    except ValueError:
        return str(path)


def module_dirs(env):
    root = hlib.addons_dir(env)
    wanted = hlib.modules_in_scope(env)
    if not root.is_dir():
        return []
    found = sorted(p.parent for p in root.glob("*/__manifest__.py"))
    return [d for d in found if not wanted or d.name in wanted]


def check_python(path):
    try:
        compile(Path(path).read_text(), str(path), "exec")
    except SyntaxError as exc:
        return [Finding(rel(path), exc.lineno or 1, f"Python syntax error: {exc.msg}",
                        "The file does not compile, so Odoo cannot import the module.",
                        "Fix the syntax at the line shown.")]
    return []


def check_xml(path):
    try:
        ET.parse(path)
    except ET.ParseError as exc:
        return [Finding(rel(path), exc.position[0], f"XML is not well formed: {exc}",
                        "Odoo cannot load a broken XML file; the module install fails.",
                        "Fix the tag or character at the line shown (unclosed tag, stray '&' "
                        "must be '&amp;', '<' in text must be '&lt;').")]
    return []


def check_access_csv(path, odoo_version):
    path = Path(path)
    uses_ir_access = hlib.version_tuple(odoo_version) >= (20, 0)
    if path.name == "ir.model.access.csv" and uses_ir_access:
        return [Finding(rel(path), 1, "ir.model.access.csv does not exist in Odoo 20",
                        "Odoo 20 replaced ir.model.access and ir.rule by a single ir.access model.",
                        "Write security/ir.access.csv with the header "
                        f"{','.join(IR_ACCESS_HEADER)}; model_id is the model name (sale.order), "
                        "operation a subset of 'crud' in that order, domain optional.")]
    if path.name == "ir.access.csv" and not uses_ir_access:
        return [Finding(rel(path), 1, f"ir.access.csv does not exist in Odoo {odoo_version}",
                        "ir.access arrives in Odoo 20; this version uses ir.model.access + ir.rule.",
                        f"Write security/ir.model.access.csv with the header "
                        f"{','.join(MODEL_ACCESS_HEADER)}, and record rules in XML.")]
    rows = list(csv.reader(path.read_text().splitlines()))
    if not rows:
        return []
    expected = IR_ACCESS_HEADER if uses_ir_access else MODEL_ACCESS_HEADER
    if [c.strip() for c in rows[0]] != expected:
        return [Finding(rel(path), 1, f"wrong {path.name} header",
                        "Odoo maps CSV columns by header; a wrong header loads wrong or no rights.",
                        f"Use exactly: {','.join(expected)}")]
    out = []
    for lineno, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(expected):
            out.append(Finding(rel(path), lineno, f"{len(row)} columns, expected {len(expected)}",
                               "A row with the wrong number of columns fails the module install.",
                               "Quote values containing commas (domains) with double quotes."))
        elif uses_ir_access and row[4].strip() not in IR_ACCESS_OPERATIONS:
            out.append(Finding(rel(path), lineno, f"invalid operation {row[4]!r}",
                               "ir.access.operation is a selection of the letters c, r, u, d in "
                               "this order.",
                               "Use one of: " + ", ".join(sorted(IR_ACCESS_OPERATIONS, key=len,
                                                                 reverse=True))))
    return out


def check_manifest(module_dir, odoo_version):
    path = module_dir / "__manifest__.py"
    findings = check_python(path)
    if findings:
        return findings
    try:
        manifest = ast.literal_eval(path.read_text())
    except (ValueError, SyntaxError):
        return [Finding(rel(path), 1, "manifest is not a plain dict literal",
                        "Odoo reads the manifest with literal_eval; code in it is not allowed.",
                        "Keep only a dict of literals (strings, lists, booleans).")]
    out = []

    def bad(what, why, fix):
        out.append(Finding(rel(path), 1, what, why, fix))

    for key in ("name", "version", "license", "depends"):
        if key not in manifest:
            bad(f"manifest misses '{key}'", "Every module manifest needs it.",
                f"Add '{key}' to __manifest__.py.")
    version = str(manifest.get("version", ""))
    parts = version.split(".")
    if "version" in manifest and (not version.startswith(odoo_version + ".") or len(parts) != 5
                                  or not all(p.isdigit() for p in parts)):
        bad(f"manifest version '{version}' is not {odoo_version}.x.y.z",
            "Odoo uses the version to run migrations; the first part must match the server.",
            f"Set 'version': '{odoo_version}.1.0.0' and bump x.y.z on each change "
            "that needs a migration.")
    if not isinstance(manifest.get("depends", []), list):
        bad("'depends' must be a list", "Odoo expects a list of module names.",
            "Write 'depends': ['base', ...].")
    for key in ("data", "demo"):
        for item in manifest.get(key, []) or []:
            if not (module_dir / item).is_file():
                bad(f"'{key}' lists '{item}', which does not exist",
                    "The module install fails when a listed data file is missing.",
                    f"Create {module_dir.name}/{item} or remove it from '{key}'.")
    return out


def check_file(path, odoo_version):
    path = Path(path)
    if path.name == "__manifest__.py":
        return check_manifest(path.parent, odoo_version)
    if path.suffix == ".py":
        return check_python(path)
    if path.suffix == ".xml":
        return check_xml(path)
    if path.name in ("ir.model.access.csv", "ir.access.csv"):
        return check_access_csv(path, odoo_version)
    return []


def load_project_checks():
    checks = []
    for path in sorted(CHECKS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"harness_check_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        checks.append(mod)
    return checks


def run_project_checks(files):
    out = []
    for check in load_project_checks():
        for item in check.detect(files):
            path, line, detail = item[:3]
            why, fix = item[3:5] if len(item) == 5 else (check.WHY, check.FIX)
            out.append(Finding(rel(path), line, f"[{check.ID}] {detail}", why, fix))
    return out


def module_files(module_dir):
    return sorted(p for p in module_dir.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts)


def run(env, files=None):
    """Run every layer 1 static check. files=None means all modules in scope."""
    version = env.get("ODOO_VERSION", "")
    findings = []
    if files is None:
        files = []
        for mdir in module_dirs(env):
            files += module_files(mdir)
    for path in files:
        findings += check_file(path, version)
    findings += run_project_checks([Path(f) for f in files])
    return findings


def main(argv):
    env = hlib.load_env()
    files = [Path(a) for a in argv if Path(a).is_file()] if argv else None
    findings = run(env, files)
    for finding in findings:
        print(finding.redpen(), file=sys.stderr)
    if not findings:
        print("✓ static checks passed")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
