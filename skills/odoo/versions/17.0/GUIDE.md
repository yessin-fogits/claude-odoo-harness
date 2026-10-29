# Odoo 17.0

Examples you have seen may be older (14 to 16) or newer (18 to 20). Everything here was
checked against the Odoo 17.0 source (see `references/version-facts.md`, generated from it).

## The 12 things other versions get wrong in 17.0

1. `attrs` and `states` are gone: write `invisible="state != 'draft'"`, `readonly="..."`,
   `required="..."`, `column_invisible="..."` directly.
2. Display name: override `_compute_display_name`; `name_get` is deprecated.
3. List views are still `<tree>` with `view_mode` `tree,form` (`<list>` is 18.0).
4. Kanban views use `<t t-name="kanban-box">`; forms end with `<div class="oe_chatter">`.
5. Field aggregation is `group_operator='sum'` (`aggregator` is 18.0).
6. Access checks: `check_access_rights('write')` + `check_access_rule('write')`,
   `_filter_access_rules('read')` (`check_access()` is 18.0).
7. Translations in Python: `from odoo import _` then `_("text")`.
8. SQL constraints are `_sql_constraints = [...]`.
9. JSON routes are `type='json'`.
10. Domains are lists; combine them with `expression.AND`/`OR`.
11. Users' groups field is `groups_id`; groups have `category_id` and `users`.
12. Front end is OWL 2 (`static props`, `useState`); server calls through `useService("rpc")`.

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
| What changed from 16.0 to 17.0 | `references/version-notes.md` |
| Exact API list of this version | `references/version-facts.md` |

## In this harness

`odoo-harness static` (run after each edit and at verify) already rejects several
other-version patterns (rule `odoo-version-api`) and new models without access rights
(rule `model-access`). Fix what it reports instead of working around it.
