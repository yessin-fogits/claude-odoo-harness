---
name: odoo
description: Odoo 19.0 development reference, checked against the Odoo 19.0 source code. Use when writing, reviewing or fixing Odoo module code (models and fields, views XML, security with ir.model.access and ir.rule, controllers, OWL 2 components, tests, migrations) so the code matches Odoo 19.0 and not an older or newer version.
---

# Odoo 19.0

Most Odoo code you have seen is for Odoo 14 to 17. Several things changed by 19.0.
Everything here was checked against the Odoo 19.0 source (see
`references/version-facts.md`, generated from it).

## The 12 things older code gets wrong in 19.0

1. List views are `<list>` and `view_mode` is `list,form` (since 18.0).
2. SQL constraints are class attributes: `_name_uniq = models.Constraint('UNIQUE(name)', 'msg')`;
   indexes with `models.Index` / `models.UniqueIndex`.
3. `self.env.cr`, `self.env.uid`, `self.env.context` (not `self._cr`...).
4. Access checks: `records.check_access('write')`, `records._filtered_access('read')`.
5. Display name: override `_compute_display_name`; there is no `name_get`.
6. JSON routes are `type='jsonrpc'`; `type='json2'` is the new JSON-2 API. → `references/controllers.md`
7. Domains can be `Domain` objects (`from odoo.fields import Domain`); never `bool(domain)`.
8. Users' groups are `group_ids` (and `all_group_ids`); groups belong to a `res.groups.privilege`.
9. Field aggregation is `aggregator='sum'` (not `group_operator`).
10. Translations in Python: `self.env._("text")`.
11. Demo data is not installed by default: tests create their own records.
12. Front end is OWL 2 (`static props`, `useState`); do not copy OWL 3 code from Odoo 20.

## Where to look

| Task | Read |
|---|---|
| Models, fields, compute, constraints, domains, SQL | `references/orm.md` |
| List/form/search/kanban views, actions, menus, QWeb | `references/views.md` |
| Groups, access rights, record rules, multi-company, sudo | `references/security.md` |
| JS components, field widgets, services, assets | `references/owl.md` |
| HTTP routes, JSON-RPC, JSON-2 | `references/controllers.md` |
| Odoo tests and Playwright e2e tests | `references/testing.md` |
| Version bumps and migration scripts | `references/migrations.md` |
| What changed from 17.0 to 19.0 | `references/version-notes.md` |
| Exact API list of this version | `references/version-facts.md` |

## In this harness

`harness/static_checks.py` (run after each edit and at verify) already rejects several
other-version patterns (rule `odoo-version-api`) and new models without access rights
(rule `model-access`). Fix what it reports instead of working around it.
