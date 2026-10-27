---
name: odoo
description: Odoo 18.0 development reference, checked against the Odoo 18.0 source code. Use when writing, reviewing or fixing Odoo module code (models and fields, views XML, security with ir.model.access and ir.rule, controllers, OWL 2 components, tests, migrations) so the code matches Odoo 18.0 and not an older or newer version.
---

# Odoo 18.0

Most Odoo code you have seen is for Odoo 14 to 17, and newer examples may be 19 or 20.
Everything here was checked against the Odoo 18.0 source (see
`references/version-facts.md`, generated from it).

## The 12 things other versions get wrong in 18.0

1. List views are `<list>` and `view_mode` is `list,form` (`<tree>` was renamed in 18.0).
2. Kanban views use `<t t-name="card">`; forms end with `<chatter/>`.
3. Field aggregation is `aggregator='sum'` (not `group_operator`).
4. Access checks: `records.check_access('write')`, `has_access()`, `_filtered_access('read')`
   (not `check_access_rights` / `check_access_rule`).
5. Translations in Python: `self.env._("text")`.
6. Display name: override `_compute_display_name`; there is no `name_get`.
7. SQL constraints are still `_sql_constraints = [...]` (constraint objects arrive in 19.0).
8. JSON routes are `type='json'` (`jsonrpc`/`json2` are 19.0).
9. Domains are lists; combine them with `expression.AND`/`OR` (`Domain` objects are 19.0).
10. Users' groups field is `groups_id`; groups have `category_id` and `users`.
11. Actions can have a `path` (readable URL `/odoo/<path>`).
12. Front end is OWL 2 (`static props`, `useState`); do not copy OWL 3 code from Odoo 20.

## Where to look

| Task | Read |
|---|---|
| Models, fields, compute, constraints, domains, SQL | `references/orm.md` |
| List/form/search/kanban views, actions, menus, QWeb | `references/views.md` |
| Groups, access rights, record rules, multi-company, sudo | `references/security.md` |
| JS components, field widgets, services, assets | `references/owl.md` |
| HTTP routes, JSON-RPC, external API | `references/controllers.md` |
| Odoo tests and Playwright e2e tests | `references/testing.md` |
| Version bumps and migration scripts | `references/migrations.md` |
| What changed from 17.0 to 18.0 | `references/version-notes.md` |
| Exact API list of this version | `references/version-facts.md` |

## In this harness

`harness/static_checks.py` (run after each edit and at verify) already rejects several
other-version patterns (rule `odoo-version-api`) and new models without access rights
(rule `model-access`). Fix what it reports instead of working around it.
