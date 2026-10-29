# What changed from Odoo 16.0 to 17.0

Use this to recognize 16.0-era code (training data, OCA modules, the client's existing
code) and translate it. Each line was checked in the Odoo 16.0 and 17.0 sources.

| Before (16.0) | In 17.0 |
|---|---|
| `attrs="{'invisible': [('state', '!=', 'draft')]}"`, `states="draft"` | `invisible="state != 'draft'"`, `readonly="..."`, `required="..."`; in lists `column_invisible="..."`. Views with `attrs`/`states` fail to load |
| `def name_get(self)` returning `[(id, name)]` | `_compute_display_name()` setting `record.display_name`; `name_get` is deprecated |
| `_read_group(domain, fields, groupby, lazy=...)` | `_read_group(domain, groupby, aggregates)` returning tuples, e.g. `aggregates=['amount:sum']` |
| `search` then `read` | `search_fetch(domain, field_names)` |
| — | `records.grouped('field')` |
| raw SQL strings with `%s` | `SQL("... %s", value)` wrapper (`from odoo.tools import SQL`), `SQL.identifier(name)` |
| `model.clear_cache()` | `self.env.registry.clear_cache()` |
| `_generate_order_by()` / `_inherits_join_calc()` | `_order_to_sql()` / `_field_to_sql()` |
| `with self.env.norecompute():` | not needed |

Still the same as 16.0 (changed only in 18.0 or later): `<tree>`, `kanban-box`,
`group_operator`, `check_access_rights`/`check_access_rule`, `_sql_constraints`,
`type='json'` routes, OWL 2.
