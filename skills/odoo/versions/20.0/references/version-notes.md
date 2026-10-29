# What changed from Odoo 17.0 to 20.0

Use this to recognize older-version code (from training data, OCA modules, the client's
existing code) and translate it. Each line was checked in the Odoo source of the version
named; "upgrade_code" marks changes that `odoo-bin upgrade_code` rewrites for you.

## 18.0

| Before (17.0) | From 18.0 |
|---|---|
| `<tree>` list views, `view_mode` `tree,form`, `tree_view_ref` | `<list>`, `list,form`, `list_view_ref` (upgrade_code 17.5) |
| `group_operator='avg'` on fields | `aggregator='avg'` (`group_operator` removed in 20.0) |
| `_("text")` imported from `odoo` | `self.env._("text")` |
| `check_access_rights(op)` + `check_access_rule(op)` | `check_access(op)`, `has_access(op)` |
| `_filter_access_rules(op)` | `_filtered_access(op)` |
| `@api.readonly` | new: RPC methods that may run on a read-only cursor |

## 19.0

| Before | From 19.0 |
|---|---|
| `_sql_constraints = [('name_uniq', 'unique(name)', 'msg')]` | `_name_uniq = models.Constraint('unique(name)', 'msg')`; also `models.Index`, `models.UniqueIndex` (upgrade_code 18.1) |
| `@http.route(type='json')` | `type='jsonrpc'` (upgrade_code 18.1); new `type='json2'` and the `/json/2/<model>/<method>` API |
| `self._cr`, `self._uid`, `self._context` | `self.env.cr`, `self.env.uid`, `self.env.context` (upgrade_code 18.5) |
| domain lists only, `expression.AND/OR` | `Domain` objects (`from odoo.fields import Domain`); lower-case operators; never `bool(domain)` |
| `@api.returns` | removed |
| `res.users.groups_id` | `group_ids` (explicit) and `all_group_ids` (with implied) |
| `res.groups.category_id` for the user form | `res.groups.privilege` record + `privilege_id` on groups |
| demo data installed by default | not installed unless `--with-demo` |
| `request.cr`, `request.uid`, `request.context` | `request.env.cr`, `request.env.uid`, `request.env.context` |

## 20.0

| Before | From 20.0 |
|---|---|
| `security/ir.model.access.csv` (`model_id:id`, `perm_read`...) + `ir.rule` records | one `security/ir.access.csv`: `id,name,model_id,group_id/id,operation,domain` (upgrade_code 19.4) |
| OWL 2: `useState`, `reactive` | OWL 3: `proxy()`, `signal()`, `computed()` (upgrade_code owl3-migration) |
| `static props = {...}` | `props = useProps({...})` with `t.*` type helpers |
| `useRef`, `t-ref` | `signal.ref()` |
| `useEnv`, `useSubEnv`, `useComponent`, `onWillRender`, `onRendered`, `useExternalListener` from `@odoo/owl` | not in OWL 3: `useListener`, or the compatibility module `@web/owl2/utils` |
| template expressions `props.x`, `state.y` | `this.props.x`, `this.state.y` |
| `t-esc` | `t-out` |
| `<t t-call="x"><t t-set="title" t-value="..."/></t>` | `<t t-call="x" title="..."/>`, `name.f="..."`, `name.translate="..."` (upgrade_code 19.1) |
| `<field type="base64" file="...">` | `type="bytes"` (upgrade_code 19.3) |
| `_rec_names_search = ['name']` | a tuple (upgrade_code 19.5) |
| `registry.clear_cache()` | `self.env.transaction.invalidate_ormcache()` (upgrade_code 19.4) |
| `from odoo.tools import ormcache` | `from odoo.api import ormcache` |
| `SingleTransactionCase` | removed: use `TransactionCase` |
| date filters with `start_month`... | only `date="field"` (upgrade_code 20.0) |
| `<i class="fa fa-user"/>` (Font Awesome) | `<i class="oi" data-icon="person"/>` (Material Symbols, upgrade_code 19.5) |
| — | `models.CachedModel` (stable cache for some fields) |
