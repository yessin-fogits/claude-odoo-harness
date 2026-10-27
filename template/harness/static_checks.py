#!/usr/bin/env python3
"""Layer 1 static checks that need no Odoo and no Docker (standard library only).

    harness/static_checks.py              check all modules in scope
    harness/static_checks.py FILE...      check only these files (used after each edit)

Checks: Python compiles, XML is well formed, manifests are consistent, security CSV
headers, and the project checks in harness/checks/ (born from code reviews).
"""

import ast
import importlib.util
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hlib  # noqa: E402

ACCESS_HEADER = "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink"
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


def check_access_csv(path):
    first = Path(path).read_text().splitlines()[:1]
    if first and first[0].strip() != ACCESS_HEADER:
        return [Finding(rel(path), 1, "wrong ir.model.access.csv header",
                        "Odoo maps CSV columns by header; a wrong header loads wrong or no rights.",
                        f"Use exactly: {ACCESS_HEADER}")]
    return []


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
    if path.name == "ir.model.access.csv":
        return check_access_csv(path)
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
        for path, line, detail in check.detect(files):
            out.append(Finding(rel(path), line, f"[{check.ID}] {detail}", check.WHY, check.FIX))
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
