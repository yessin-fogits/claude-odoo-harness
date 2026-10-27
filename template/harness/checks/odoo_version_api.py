"""Project check: API that does not match this project's Odoo version.

Agents often write the Odoo API of another version (from training data). Each
rule applies to a version range [min, max) and is grounded in the Odoo source
(odoo/upgrade_code scripts, DeprecationWarnings, RNG schemas, OWL exports).
The version comes from ODOO_VERSION in harness/harness.env.
"""

import re

import hlib

ID = "odoo-version-api"
WHY = "This API does not match the Odoo version of the project."
FIX = "Use the API of this Odoo version (see the odoo skill, references/version-notes.md)."

OWL3_REMOVED = {
    "useState": "proxy() (or signal())",
    "reactive": "proxy()",
    "useRef": "signal.ref()",
    "useEnv": "import it from '@web/owl2/utils'",
    "useSubEnv": "import it from '@web/owl2/utils'",
    "useChildSubEnv": "import it from '@web/owl2/utils'",
    "useComponent": "import it from '@web/owl2/utils'",
    "onWillRender": "import it from '@web/owl2/utils'",
    "onRendered": "import it from '@web/owl2/utils'",
    "useExternalListener": "useListener() from '@odoo/owl', or '@web/owl2/utils'",
}

# (id, min_version, max_version (exclusive) or None, suffixes, pattern, detail, why, fix)
RULES = [
    ("list-tag", (18, 0), None, {".xml"}, r"<tree[\s>/]",
     "<tree> view tag",
     "Since Odoo 18.0 the list view tag is <list>; the view RNG rejects <tree>.",
     "Use <list>, view_mode 'list' and list_view_ref."),
    ("list-view-mode", (18, 0), None, {".xml", ".py"},
     r"""view_mode['"]?\s*(?:[:=]|>)\s*['"]?[\w,]*\btree\b""",
     "view_mode with 'tree'",
     "Since Odoo 18.0 the view type is 'list'.",
     "Replace 'tree' by 'list' in view_mode."),
    ("tree-tag", (0, 0), (18, 0), {".xml"}, r"<list[\s>/]",
     "<list> view tag",
     "Before Odoo 18.0 the list view tag is <tree>.",
     "Use <tree> and view_mode 'tree'."),
    ("sql-constraints", (19, 0), None, {".py"}, r"^\s*_sql_constraints\s*=",
     "_sql_constraints",
     "Since Odoo 19.0 SQL constraints are models.Constraint class attributes.",
     "Write: _name_uniq = models.Constraint('UNIQUE(name)', 'The name must be unique.')"),
    ("constraint-objects", (0, 0), (19, 0), {".py"}, r"\bmodels\.(Constraint|Index|UniqueIndex)\(",
     "models.Constraint / Index",
     "models.Constraint, Index and UniqueIndex arrive in Odoo 19.0.",
     "Use _sql_constraints = [('name_uniq', 'unique(name)', 'The name must be unique.')]."),
    ("route-json", (19, 0), None, {".py"}, r"""\btype\s*=\s*['"]json['"]""",
     "route type='json'",
     "Since Odoo 19.0 JSON-RPC routes are type='jsonrpc' (type='json2' is the JSON-2 API).",
     "Use type='jsonrpc'."),
    ("route-jsonrpc", (0, 0), (19, 0), {".py"}, r"""\btype\s*=\s*['"](jsonrpc|json2)['"]""",
     "route type='jsonrpc'/'json2'",
     "Before Odoo 19.0 JSON routes are type='json'.",
     "Use type='json'."),
    ("env-properties", (19, 0), None, {".py"}, r"\._(cr|uid|context)\b",
     "self._cr / self._uid / self._context",
     "Since Odoo 19.0 these model properties are deprecated.",
     "Use self.env.cr, self.env.uid, self.env.context."),
    ("check-access", (18, 0), None, {".py"},
     r"\.(check_access_rights|check_access_rule|_filter_access_rules(_python)?)\(",
     "check_access_rights / check_access_rule / _filter_access_rules",
     "Deprecated since Odoo 18.0.",
     "Use records.check_access('read'|'write'|...) or records._filtered_access(operation)."),
    ("api-returns", (19, 0), None, {".py"}, r"@api\.returns\b",
     "@api.returns",
     "api.returns no longer exists since Odoo 19.0.",
     "Remove the decorator; return records directly."),
    ("name-get", (17, 0), None, {".py"}, r"\bdef name_get\(",
     "name_get()",
     "name_get was removed in Odoo 17.0; the display name is the computed field display_name.",
     "Override _compute_display_name() and set record.display_name."),
    ("single-transaction-case", (20, 0), None, {".py"}, r"\bSingleTransactionCase\b",
     "SingleTransactionCase",
     "SingleTransactionCase was removed in Odoo 20.0.",
     "Use TransactionCase; put shared data in setUpClass."),
    ("ormcache-import", (20, 0), None, {".py"},
     r"from odoo\.tools(?:\.cache)? import [^\n]*\bormcache\b",
     "ormcache imported from odoo.tools",
     "Since Odoo 20.0 ormcache is imported from odoo.api.",
     "from odoo.api import ormcache"),
    ("registry-clear-cache", (20, 0), None, {".py"}, r"\bregistry\.clear_cache\(",
     "registry.clear_cache()",
     "Since Odoo 20.0 the ORM cache is invalidated on the transaction.",
     "Use self.env.transaction.invalidate_ormcache()."),
    ("rec-names-search", (20, 0), None, {".py"}, r"\b_rec_names_search\s*=\s*\[",
     "_rec_names_search as a list",
     "Since Odoo 20.0 _rec_names_search is a tuple.",
     "Write _rec_names_search = ('name', 'code')."),
    ("xml-base64", (20, 0), None, {".xml"}, r'type="base64"[^>]*\bfile=',
     'field type="base64" with file=',
     "Since Odoo 20.0 binary files in XML data use type=\"bytes\".",
     'Use type="bytes".'),
    ("search-date-range", (20, 0), None, {".xml"}, r"\b(start|end)_(month|year)\s*=",
     "start_month/end_month/start_year/end_year on a date filter",
     "Odoo 20.0 no longer parses these attributes and the RNG rejects them.",
     'Keep only <filter name="..." date="field"/>.'),
    ("t-esc", (20, 0), None, {".xml", ".js"}, r"\bt-esc\s*=",
     "t-esc",
     "Odoo 20.0 (OWL 3) templates use t-out; t-esc was migrated away.",
     "Use t-out (it escapes unless the value is markup)."),
]


def owl3_imports(text):
    for match in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*[\"']@odoo/owl[\"']", text):
        for name in re.split(r"[,\s]+", match.group(1)):
            name = name.split(" as ")[0].strip()
            if name in OWL3_REMOVED:
                yield match.start(), name


def detect(files):
    version = hlib.version_tuple(hlib.load_env().get("ODOO_VERSION"))
    rules = [r for r in RULES if version >= r[1] and (r[2] is None or version < r[2])]
    found = []
    for path in files:
        if path.suffix not in {".py", ".xml", ".js"}:
            continue
        text = path.read_text(errors="replace")
        for _id, _min, _max, suffixes, pattern, detail, why, fix in rules:
            if path.suffix not in suffixes:
                continue
            for match in re.finditer(pattern, text, re.M):
                line = text.count("\n", 0, match.start()) + 1
                found.append((path, line, detail, why, fix))
        if path.suffix == ".js" and version >= (20, 0):
            for pos, name in owl3_imports(text):
                line = text.count("\n", 0, pos) + 1
                found.append((path, line, f"'{name}' imported from @odoo/owl",
                              f"OWL 3 (Odoo 20.0) does not export {name}.",
                              f"Use {OWL3_REMOVED[name]}."))
    return found
