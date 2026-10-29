# What changed from Odoo 17.0 to 19.0

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
