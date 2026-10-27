"""Red-pen catalog of the harness: known failure patterns mapped to WHY and HOW TO FIX.

This file belongs to the harness and is replaced by harness updates. Add the
patterns of this project to harness/errors_project.py, which updates never touch.
`{1}`, `{2}`... are regex groups.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    id: str
    pattern: str
    why: str
    fix: str


CATALOG = [
    # --- Odoo server / module loading ---------------------------------------------
    Entry("xmlid-not-found",
          r"External ID not found in the system: ([\w.]+)",
          "A record refers to the XML id '{1}', which is not loaded when this file is loaded.",
          "Check the spelling of '{1}'. If it belongs to another module, add that module to "
          "'depends' in __manifest__.py. If it is in this module, load its file earlier in "
          "the manifest 'data' list."),
    Entry("field-does-not-exist",
          r"Field \"?([\w.]+)\"? does not exist in model \"?([\w.]+)\"?",
          "A view or domain uses the field '{1}', which model '{2}' does not have.",
          "Define the field on '{2}' (in a model that inherits it), check the spelling, and make "
          "sure the Python file is imported in the module's __init__.py."),
    Entry("model-no-access-rules",
          r"The models \['([\w.]+)'.*? have no access rules in module (\w+)",
          "Model '{1}' of module '{2}' has no access rights, so only the superuser can use it.",
          "Add a line for '{1}' in {2}/security/ir.model.access.csv (model_id:id = "
          "model_{1_underscored}) and list the CSV file in the manifest 'data'."),
    Entry("access-error",
          r"odoo\.exceptions\.AccessError: (.+)",
          "The test user is not allowed to do this: {1}",
          "Add the missing access line or record rule for the right group, or run the step "
          "with a user that has the group. Do not hide it with sudo() unless it is intended."),
    Entry("view-parse-error",
          r"odoo\.tools\.convert\.ParseError: (.+)",
          "Odoo could not load an XML data file: {1}",
          "Open the file and line named in the message. Typical causes: invalid view "
          "architecture for this Odoo version, an xpath that matches nothing, a wrong field name."),
    Entry("xpath-not-found",
          r"Element '(.+)' cannot be located in parent view",
          "An inherited view uses an xpath that matches nothing in the parent view: {1}",
          "Read the parent view's real architecture for this Odoo version and fix the expr."),
    Entry("python-module-missing",
          r"ModuleNotFoundError: No module named '([\w.]+)'",
          "Python cannot import '{1}'.",
          "If it is your own file, fix the import or the __init__.py chain. If it is a library, "
          "add it to 'external_dependencies' in the manifest and to the Odoo image."),
    Entry("model-not-found",
          r"KeyError: '([a-z_]+\.[\w.]+)'",
          "The model '{1}' is not in the registry when this code runs.",
          "Add the module defining '{1}' to 'depends' in __manifest__.py, or fix the model name."),
    Entry("not-null-violation",
          r"null value in column \"(\w+)\" of relation \"(\w+)\" violates not-null constraint",
          "A record of table '{2}' was created without the required column '{1}'.",
          "Give '{1}' a value where the record is created (test data, default, or compute)."),
    Entry("unique-violation",
          r"duplicate key value violates unique constraint \"(\w+)\"",
          "A record breaks the unique constraint '{1}'.",
          "Use unique values in the test data or search the existing record before creating."),
    Entry("modules-not-loaded",
          r"Some modules are not loaded, some dependencies or manifest may be missing: (.+)",
          "Odoo could not load these modules: {1}",
          "Check that each one is in the addons path, has a valid manifest and that all its "
          "'depends' exist."),
    Entry("test-failure",
          r"FAIL: ([\w.]+(?: \([\w.]+\))?)",
          "The test {1} failed: the code does not behave as the test expects.",
          "Read the assertion message under the FAIL line. Fix the code, not the test, unless "
          "the test is wrong about the expected behavior."),
    Entry("test-error",
          r"ERROR: ([\w.]+(?: \([\w.]+\))?)",
          "The test {1} raised an exception before reaching its assertions.",
          "Read the traceback under the ERROR line and fix its first frame in your module."),
    # --- Playwright e2e ---------------------------------------------------------
    Entry("playwright-timeout",
          r"TimeoutError: (?:Locator|Page)\.(\w+): Timeout (\d+)ms exceeded",
          "Playwright waited {2} ms for '{1}' and the element never became ready.",
          "Open the trace (path in the e2e artifacts) to see the page at that moment. Check the "
          "selector, that the view really shows the element, and that the action before it "
          "succeeded. Do not just raise the timeout."),
    Entry("playwright-strict-mode",
          r"strict mode violation: (.+) resolved to (\d+) elements",
          "The locator {1} matches {2} elements, so Playwright cannot pick one.",
          "Make the locator precise (role and name, or scope it inside the right container). "
          "If the duplicates are records left by earlier runs (the test DB persists), give "
          "the records the test creates unique names with the `unique` fixture."),
    Entry("playwright-assertion",
          r"AssertionError: Locator expected to (.+)",
          "An e2e expectation failed: the page did not reach the expected state ({1}).",
          "Reproduce the steps by hand on http://localhost:<ODOO_PORT> and fix the behavior."),
    Entry("odoo-unreachable",
          r"net::ERR_CONNECTION_REFUSED",
          "The e2e browser could not reach the Odoo server.",
          "Run harness/init.sh --check, then harness/init.sh if the server is down."),
]

# Fix hints for common pylint-odoo / pylint messages, keyed by symbol.
PYLINT_FIXES = {
    "print-used": "Replace print() with `_logger = logging.getLogger(__name__)` and _logger.info().",
    "sql-injection": "Pass values as query parameters: cr.execute(query, (value,)) or use "
                     "odoo.tools.SQL; never format values into the SQL string.",
    "translation-required": "Wrap user-facing strings in _() (or self.env._() on 18+).",
    "missing-return": "Return the result of super() in the overriding method.",
    "manifest-version-format": "Use the version format <odoo_version>.x.y.z, e.g. 17.0.1.0.0.",
    "attribute-deprecated": "Remove the deprecated attribute; use the current Odoo API.",
    "method-compute": "Name compute methods _compute_<field>.",
    "method-required-super": "Call super() in this overridden method.",
    "except-pass": "Do not silence exceptions: log them or re-raise.",
    "manifest-superfluous-key": "Remove the key from the manifest: it equals the default value.",
    "unused-import": "Remove the unused import.",
    "external-request-timeout": "Pass timeout= to the HTTP request.",
}


def _expand(template, match):
    groups = {str(i): (g or "") for i, g in enumerate(match.groups(), start=1)}
    groups.update({f"{k}_underscored": v.replace(".", "_") for k, v in groups.items()})
    return re.sub(r"\{(\w+)\}", lambda m: groups.get(m.group(1), m.group(0)), template)


def project_catalog():
    """Entries of harness/errors_project.py (checked first); empty if the file is missing."""
    try:
        import errors_project
    except ImportError:
        return []
    return list(getattr(errors_project, "PROJECT_CATALOG", []))


def explain(text):
    """Return [(entry_id, why, fix)] for each entry matching text: project entries first."""
    found = []
    for entry in project_catalog() + CATALOG:
        match = re.search(entry.pattern, text)
        if match:
            found.append((entry.id, _expand(entry.why, match), _expand(entry.fix, match)))
    return found


def pylint_fix(symbol):
    return PYLINT_FIXES.get(
        symbol, f"Run `pylint --load-plugins=pylint_odoo --help-msg={symbol}` for the rule, "
                "then fix the code (do not disable the rule to pass).")


UNKNOWN_FIX = ("No catalog entry for this error. Read the excerpt above and fix the first error. "
               "Then add a pattern for it in harness/errors_project.py so the next agent gets "
               "the fix.")
