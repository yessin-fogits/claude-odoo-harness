#!/usr/bin/env python3
"""Layer 1 static checks that need no Odoo and no Docker (standard library only).

    harness/static_checks.py              check the custom modules changed on this branch
                                          (project checks: only on the changed lines)
    harness/static_checks.py --all        check the whole project: every custom module and
                                          the project files (debt report, used by discovery)
    harness/static_checks.py FILE...      check only these files (used after each edit)

Checks: Python compiles, XML is well formed, manifests are consistent, security CSV
headers, and the project checks in harness/checks/ (born from code reviews). With
--all, also the project files outside the modules (configs, scripts, compose files:
hard-coded secrets) and the lint configuration (Odoo version it validates).
"""

import ast
import csv
import importlib.util
import re
import subprocess
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
    # Breaking findings (syntax, XML, manifest, security CSV) stop the module install: they
    # always block. Quality findings (project checks) block only on lines changed on the
    # branch; older ones are debt.
    breaking: bool = True

    def redpen(self):
        return hlib.format_redpen("L1 static", f"{self.path}:{self.line}: {self.what}",
                                  self.why, self.fix)


def rel(path):
    try:
        return str(Path(path).resolve().relative_to(hlib.REPO_ROOT))
    except ValueError:
        return str(path)


PROJECT_FILE_RE = re.compile(r"(\.(py|conf|cfg|ini|ya?ml|sh|env|json|toml)|Dockerfile[^/]*|"
                             r"Jenkinsfile[^/]*)$")
LINT_CONFIGS = (".pylintrc-mandatory", ".pylintrc")


def module_dirs(env, names=None):
    """Custom module dirs: all of them, or only `names` (unknown names are ignored)."""
    found = hlib.custom_modules(env)
    if names is None:
        return [found[m] for m in sorted(found)]
    return [found[m] for m in sorted(set(names)) if m in found]


def project_files(env):
    """Tracked files outside the addon folders that may hold configuration or secrets."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=hlib.REPO_ROOT, capture_output=True,
                             text=True, check=True).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        return []
    addon_roots = [p + "/" for p in hlib.env_list(env, "CUSTOM_ADDONS")
                   + hlib.env_list(env, "THIRD_PARTY_ADDONS")]
    return [hlib.REPO_ROOT / f for f in out
            if PROJECT_FILE_RE.search(f) and not f.startswith(("harness/", "e2e/", ".claude/"))
            and not any(f.startswith(r) for r in addon_roots)
            and (hlib.REPO_ROOT / f).is_file()]


def check_lint_config(env):
    version = env.get("ODOO_VERSION", "")
    out = []
    for name in LINT_CONFIGS:  # project-level debt, reported by --all
        path = hlib.REPO_ROOT / name
        if not path.is_file():
            continue
        match = re.search(r"^\s*valid[-_]odoo[-_]versions\s*=\s*(.+)$", path.read_text(), re.M)
        if match and version not in [v.strip() for v in match.group(1).split(",")]:
            out.append(Finding(name, 1, f"lint config validates Odoo {match.group(1).strip()}, "
                               f"the project runs Odoo {version}",
                               "pylint-odoo then flags every manifest version of the project, so "
                               "the lint is ignored or fails for the wrong reason (the harness "
                               "passes --valid-odoo-versions itself).",
                               f"Set valid-odoo-versions={version} in {name} (a human change "
                               "shared with CI and pre-commit)."))
    return out


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
    other_series = (re.match(r"^\d{2}\.0\.", version + ".")
                    and not version.startswith(odoo_version))
    if "version" in manifest and (other_series or not all(p.isdigit() for p in parts)):
        # Odoo prefixes a plain version ('1.0' -> '18.0.1.0'); a version of another series
        # means the module was not ported to this Odoo version.
        bad(f"manifest version '{version}' is not a version of Odoo {odoo_version}",
            "Odoo uses the version to run migrations; a version from another Odoo series means "
            "the module was not ported, and a non-numeric one cannot be compared.",
            f"Port the module, then set 'version': '{odoo_version}.1.0.0' and bump it on "
            "each change that needs a migration.")
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
            out.append(Finding(rel(path), line, f"[{check.ID}] {detail}", why, fix,
                               breaking=False))
    return out


def module_files(module_dir):
    return sorted(p for p in module_dir.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts)


def run(env, files=None, modules=None, whole_project=False):
    """Run the layer 1 static checks on files, or on the files of `modules` (names; None
    means every custom module). whole_project adds the project files and lint config."""
    version = env.get("ODOO_VERSION", "")
    findings = []
    if files is None:
        files = []
        for mdir in module_dirs(env, modules):
            files += module_files(mdir)
    for path in files:
        findings += check_file(path, version)
    extra = project_files(env) if whole_project else []
    findings += run_project_checks([Path(f) for f in files + extra])
    if whole_project:
        findings += check_lint_config(env)
    return findings


def new_on_branch(env, findings):
    """Breaking findings, and quality findings on lines changed on this branch."""
    lines = hlib.changed_lines(hlib.base_ref(env))
    return [f for f in findings if f.breaking or hlib.is_changed(lines, f.path, f.line)]


def main(argv):
    env = hlib.load_env()
    if argv == ["--all"]:
        findings = run(env, whole_project=True)
    elif argv:
        findings = new_on_branch(env, run(env, [Path(a) for a in argv if Path(a).is_file()]))
    else:
        findings = new_on_branch(env, run(env, modules=hlib.changed_modules(env)))
    for finding in findings:
        print(finding.redpen(), file=sys.stderr)
    if not findings:
        print("✓ static checks passed")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
