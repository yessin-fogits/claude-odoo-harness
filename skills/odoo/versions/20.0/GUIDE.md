# Odoo 20.0

Most Odoo code you have seen is for Odoo 14 to 17. A lot of it is wrong in 20.0.
Everything here was checked against the Odoo 20.0 source (see
`references/version-facts.md`, generated from it).

## The 12 things older code gets wrong in 20.0

1. List views are `<list>` and `view_mode` is `list,form` (since 18.0).
2. Access rights are one CSV, `security/ir.access.csv`, header
   `id,name,model_id,group_id/id,operation,domain`. `operation` is `crud`, `cru`, `r`...
   (letters in c, r, u, d order); `domain` replaces record rules. → `references/security.md`
3. SQL constraints are class attributes: `_name_uniq = models.Constraint('UNIQUE(name)', 'msg')`.
4. `self.env.cr`, `self.env.uid`, `self.env.context` (not `self._cr`...).
5. Access checks: `records.check_access('write')`, `records._filtered_access('read')`.
6. Display name: override `_compute_display_name`; there is no `name_get`.
7. JSON routes are `type='jsonrpc'`; `type='json2'` is the new JSON-2 API. → `references/controllers.md`
8. Domains can be `Domain` objects (`from odoo.fields import Domain`); never `bool(domain)`.
9. Front end is OWL 3: `props = useProps(...)`, `proxy()`/`signal()` instead of `useState`,
   templates read component members through `this.` and use `t-out`. → `references/owl.md`
10. `t-call` parameters are attributes: `<t t-call="mod.tmpl" title="record.name" label.f="Text"/>`.
11. Demo data is not installed by default (19.0+): tests create their own records.
12. `ormcache` comes from `odoo.api`; `SingleTransactionCase` no longer exists.

## Where to look

| Task | Read |
|---|---|
| Models, fields, compute, constraints, domains, SQL | `references/orm.md` |
| List/form/search/kanban views, actions, menus, QWeb | `references/views.md` |
| Groups, ir.access, multi-company, sudo | `references/security.md` |
| JS components, fields widgets, plugins, assets | `references/owl.md` |
| HTTP routes, JSON-RPC, JSON-2 | `references/controllers.md` |
| Odoo tests and Playwright e2e tests | `references/testing.md` |
| Version bumps and migration scripts | `references/migrations.md` |
| What changed from 17.0 to 20.0 | `references/version-notes.md` |
| Exact API list of this version | `references/version-facts.md` |

## In this harness

`odoo-harness static` (run after each edit and at verify) already rejects several
old-version patterns (rule `odoo-version-api`) and new models without access rights
(rule `model-access`). Fix what it reports instead of working around it.
