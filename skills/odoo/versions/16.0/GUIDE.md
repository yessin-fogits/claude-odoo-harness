# Odoo 16.0

Most Odoo code you have seen is newer (17 to 20), and older examples may be 14 or 15.
Everything here was checked against the Odoo 16.0 source (see `references/version-facts.md`,
generated from it).

## The 12 things other versions get wrong in 16.0

1. Dynamic modifiers use `attrs` and `states`: `attrs="{'invisible': [('state', '!=', 'draft')]}"`,
   `states="draft"`. `invisible="state != 'draft'"` is 17.0: here a modifier attribute is only
   `1`/`0`/`True`/`False` or a `context` expression.
2. Display name: override `name_get()` returning `[(id, name)]`; `name_search` and the
   many2one dropdowns call it (`_compute_display_name` alone is not enough).
3. List views are `<tree>` with `view_mode` `tree,form` (`<list>` is 18.0).
4. Kanban views use `<t t-name="kanban-box">`; forms end with `<div class="oe_chatter">`.
5. Field aggregation is `group_operator='sum'` (`aggregator` is 18.0).
6. Access checks: `check_access_rights('write')` + `check_access_rule('write')`,
   `_filter_access_rules('read')` (`check_access()` is 18.0).
7. No `SQL` wrapper, no `search_fetch`, no `grouped()` (all 17.0): raw SQL is
   `cr.execute(query, params)`; `_read_group` takes `(domain, fields, groupby)` and returns dicts.
8. `check_company=True` does not add a domain by itself: write it on the field
   (`domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]"`).
9. JSON routes are `type='json'`; route auth is `user`, `public` or `none` (no `bearer`).
10. Every JS file starts with `/** @odoo-module **/`, or Odoo does not transpile it.
11. Front end is OWL 2, written in the 16.0 style: `X.template = "..."`, `X.props = {...}`;
    a field widget reads `this.props.value`, writes `this.props.update(value)`, and is
    registered as the component class itself.
12. The official `odoo:16.0` image runs Python 3.9: no `match` statement, no `X | None` in
    annotations evaluated at runtime.

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
| What changed from 15.0 to 16.0 | `references/version-notes.md` |
| Exact API list of this version | `references/version-facts.md` |

## In this harness

`odoo-harness static` (run after each edit and at verify) already rejects several
other-version patterns (rule `odoo-version-api`) and new models without access rights
(rule `model-access`). Fix what it reports instead of working around it.
