"""Project check: API that does not match this project's Odoo version.

Agents often write the Odoo API of another version (from training data). Each
rule applies to a version range [min, max) and is grounded in the Odoo source
(odoo/upgrade_code scripts, DeprecationWarnings, RNG schemas, OWL exports).
RULES are patterns; FILE_RULES judge a whole file (what it lacks, the value of an
attribute). The version comes from ODOO_VERSION in harness/harness.env.
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
    ("aggregator", (18, 0), None, {".py"}, r"\bgroup_operator\s*=",
     "group_operator= on a field",
     "Since Odoo 18.0 the field parameter is aggregator (group_operator is removed in 20.0).",
     "Write aggregator='sum' (or 'avg', 'min', 'max', 'count'...)."),
    ("group-operator", (0, 0), (18, 0), {".py"}, r"\baggregator\s*=\s*['\"]",
     "aggregator= on a field",
     "Before Odoo 18.0 the field parameter is group_operator.",
     "Write group_operator='sum'."),
    ("env-translate", (0, 0), (18, 0), {".py"}, r"\.env\._\(",
     "self.env._()",
     "self.env._() arrives in Odoo 18.0.",
     "Use `from odoo import _` and _('text')."),
    ("user-group-ids", (19, 0), None, {".py", ".xml"}, r"\bgroups_id\b",
     "groups_id (res.users)",
     "Since Odoo 19.0 the user's groups field is group_ids (all_group_ids with implied groups).",
     "Use group_ids, or all_group_ids to include implied groups."),
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
    ("sql-wrapper", (0, 0), (17, 0), {".py"}, r"from odoo\.tools(?:\.sql)? import [^\n]*\bSQL\b",
     "SQL imported from odoo.tools",
     "odoo.tools.SQL arrives in Odoo 17.0.",
     "Pass the values as query parameters: self.env.cr.execute(query, (value,))."),
    ("search-fetch", (0, 0), (17, 0), {".py"}, r"\.search_fetch\(",
     "search_fetch()",
     "search_fetch arrives in Odoo 17.0.",
     "Use search(domain), or search_read(domain, fields) for the values."),
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


# The constants of odoo.tools.str2bool: before 17.0 the only modifier values not evaluated
# against the context.
MODIFIER_CONSTANTS = {"y", "yes", "1", "true", "t", "on", "n", "no", "0", "false", "f", "off"}
MODIFIERS = r"invisible|readonly|required|column_invisible"
# The attribute on the element, or set by an inherited view (position="attributes").
MODIFIER_RES = (
    re.compile(rf"""(?<![\w:.@-])(?P<attr>{MODIFIERS})=(["'])(?P<value>.*?)\2"""),
    re.compile(rf"""<attribute\s+name=(["'])(?P<attr>{MODIFIERS})\1\s*>"""
               r"(?P<value>[^<]*)</attribute>"),
)
ATTRS_STATES_RE = re.compile(r"""(?<![\w:.@-])(?:attrs|states)=["']|"""
                             r"""<attribute\s+name=["'](?:attrs|states)["']\s*>""")
# odoo/tools/js_transpiler.py ODOO_MODULE_RE: the comment must open the file.
ODOO_MODULE_RE = re.compile(r"\s*/(?:\*|/).*\s*@odoo-module")
ES_MODULE_RE = re.compile(r"""^\s*(?:import\s+[\w{*"']|import[{*"']|export\s)""", re.M)


def record_modifiers(path, text):
    """Modifiers of view XML with an expression on the record (17.0 syntax). OWL templates
    (static/) are not views; HTML boolean attributes (required="required") are not modifiers."""
    if "static" in path.parts:
        return []
    found = []
    for regex in MODIFIER_RES:
        for m in regex.finditer(text):
            attr, value = m["attr"], m["value"].strip()
            constant = value.lower() in MODIFIER_CONSTANTS or value in ("", attr)
            if attr == "column_invisible" or not (constant or "context" in value):
                found.append(m.start())
    return sorted(found)


def attrs_or_states(path, text):
    """attrs/states on a view element or set by an inherited view; OWL templates are not views."""
    return [] if "static" in path.parts else [m.start() for m in ATTRS_STATES_RE.finditer(text)]


def display_name_without_name_get(path, text):
    if re.search(r"^\s+def name_get\(", text, re.M):
        return []
    return [m.start() for m in re.finditer(r"^\s+def _compute_display_name\(", text, re.M)]


def field_widget_object(path, text):
    """A field widget registered as a {component, supportedTypes...} object (17.0)."""
    if not re.search(r"""registry\.category\(\s*["']fields["']\s*\)\.add\(""", text):
        return []
    return [m.start() for m in re.finditer(r"(?<![.\w])supportedTypes\s*:", text)]


def untranspiled_module(path, text):
    """Only module assets are bundled (static/), and libraries (static/lib/) are not modules."""
    if "static" not in path.parts or "/static/lib/" in path.as_posix() or \
            ODOO_MODULE_RE.match(text):
        return []
    match = ES_MODULE_RE.search(text)
    return [match.start()] if match else []


# (id, min_version, max_version (exclusive) or None, suffix, finder(path, text) -> positions,
#  detail, why, fix)
FILE_RULES = [
    ("view-modifier-expression", (0, 0), (17, 0), ".xml", record_modifiers,
     "view modifier with an expression on the record",
     "Before Odoo 17.0, invisible/readonly/required take only 1/0/True/False or a context "
     "expression (the view fails when opened), and column_invisible is not an attribute.",
     "Use attrs=\"{'invisible': [('state', '!=', 'draft')]}\" or states=\"draft\"; in a list, "
     "attrs=\"{'column_invisible': [('parent.state', '!=', 'draft')]}\"."),
    ("view-attrs-states", (17, 0), None, ".xml", attrs_or_states,
     "attrs / states on a view element",
     "Since Odoo 17.0 views have no attrs and states attributes: the view fails to load.",
     "Write the condition itself: invisible=\"state != 'draft'\", readonly=\"...\", "
     "required=\"...\"; in a list, column_invisible=\"...\"."),
    ("display-name-compute", (0, 0), (17, 0), ".py", display_name_without_name_get,
     "_compute_display_name without name_get()",
     "Before Odoo 17.0 the display name is name_get(): name_search and the many2one dropdowns "
     "call it, so they keep showing the old name.",
     "Override name_get() and return [(record.id, name), ...]."),
    ("field-widget-object", (0, 0), (17, 0), ".js", field_widget_object,
     "field widget registered as an object",
     "Before Odoo 17.0 the fields registry takes the component class; its supportedTypes, "
     "displayName and extractProps are static members.",
     "Set MyField.supportedTypes = [...] and add MyField itself: "
     "registry.category(\"fields\").add(\"my_widget\", MyField)."),
    ("odoo-module-header", (0, 0), (18, 0), ".js", untranspiled_module,
     "ES module without the @odoo-module comment",
     "Before Odoo 18.0 a JS file is transpiled only when it starts with the @odoo-module "
     "comment; otherwise its import/export break the whole asset bundle.",
     "Make /** @odoo-module **/ the first line of the file."),
]


def in_range(rule, version):
    return version >= rule[1] and (rule[2] is None or version < rule[2])


def detect(files):
    version = hlib.version_tuple(hlib.load_env().get("ODOO_VERSION"))
    rules = [r for r in RULES if in_range(r, version)]
    file_rules = [r for r in FILE_RULES if in_range(r, version)]
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
        for _id, _min, _max, suffix, finder, detail, why, fix in file_rules:
            if path.suffix != suffix:
                continue
            for pos in finder(path, text):
                found.append((path, text.count("\n", 0, pos) + 1, detail, why, fix))
        if path.suffix == ".js" and version >= (20, 0):
            for pos, name in owl3_imports(text):
                line = text.count("\n", 0, pos) + 1
                found.append((path, line, f"'{name}' imported from @odoo/owl",
                              f"OWL 3 (Odoo 20.0) does not export {name}.",
                              f"Use {OWL3_REMOVED[name]}."))
    return found
