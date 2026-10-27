"""Project check: a new model without access rights.

A concrete model (models.Model / TransientModel with its own _name) that has no
line in the module's security CSV can only be used by the superuser: forms open
for admin in tests but fail for real users. Odoo only logs a WARNING (17-19) or
nothing (20), so the harness checks it statically.
"""

import csv
import re

import hlib

ID = "model-access"
WHY = "A model without access rights is unusable for normal users."
FIX = "Add a line for the model in the module's security CSV and list the file in the manifest."

MODEL_RE = re.compile(
    r"^class \w+\(\s*models\.(?P<kind>Model|TransientModel|AbstractModel)\s*\)\s*:(?P<body>(?:\n(?:[ \t]+.*|[ \t]*))*)",
    re.M)
NAME_RE = re.compile(r"^\s+_name\s*=\s*['\"]([\w.]+)['\"]", re.M)
INHERIT_RE = re.compile(r"^\s+_inherit\s*=\s*['\"]([\w.]+)['\"]", re.M)


def module_root(path):
    for parent in path.parents:
        if (parent / "__manifest__.py").is_file():
            return parent
    return None


def declared_access(module, ir_access):
    """Model names covered by the module's security CSV files."""
    covered = set()
    for csv_path in module.rglob("ir.access.csv" if ir_access else "ir.model.access.csv"):
        rows = list(csv.reader(csv_path.read_text().splitlines()))
        if not rows:
            continue
        header = [h.strip() for h in rows[0]]
        column = "model_id" if ir_access else "model_id:id"
        if column not in header:
            continue
        idx = header.index(column)
        for row in rows[1:]:
            if len(row) > idx and row[idx].strip():
                value = row[idx].strip()
                covered.add(value if ir_access else value.split(".")[-1].removeprefix("model_"))
    return covered


def defines_access_in_xml(module):
    return any(re.search(r'model="ir\.(model\.)?access"', p.read_text(errors="replace"))
               for p in module.rglob("*.xml"))


def detect(files):
    ir_access = hlib.version_tuple(hlib.load_env().get("ODOO_VERSION")) >= (20, 0)
    found, cache = [], {}
    for path in files:
        if path.suffix != ".py" or "tests" in path.parts:
            continue
        module = module_root(path)
        if module is None:
            continue
        text = path.read_text(errors="replace")
        for match in MODEL_RE.finditer(text):
            if match.group("kind") == "AbstractModel":
                continue
            name = NAME_RE.search(match.group("body"))
            if not name:
                continue  # extension of an existing model (_inherit only)
            inherit = INHERIT_RE.search(match.group("body"))
            if inherit and inherit.group(1) == name.group(1):
                continue  # _name == _inherit: still an extension
            if module not in cache:
                cache[module] = (declared_access(module, ir_access), defines_access_in_xml(module))
            covered, in_xml = cache[module]
            key = name.group(1) if ir_access else name.group(1).replace(".", "_")
            if key in covered or in_xml:
                continue
            line = text.count("\n", 0, match.start()) + 1
            if ir_access:
                fix = (f"Add to {module.name}/security/ir.access.csv: "
                       f"access_{name.group(1).replace('.', '_')}_user,{name.group(1)} user,"
                       f"{name.group(1)},base.group_user,crud,")
            else:
                xid = name.group(1).replace(".", "_")
                fix = (f"Add to {module.name}/security/ir.model.access.csv: "
                       f"access_{xid}_user,{name.group(1)} user,model_{xid},base.group_user,1,1,1,1")
            found.append((path, line, f"model '{name.group(1)}' has no access rights", WHY,
                          fix + " (and list the CSV in the manifest 'data')."))
    return found
