# What changed from Odoo 17.0 to 18.0

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
