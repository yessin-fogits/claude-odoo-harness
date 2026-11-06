# What changed from Odoo 15.0 to 16.0

Use this to recognize 15.0-era code (training data, OCA modules, the client's existing
code) and translate it. Each line was checked in the Odoo 15.0 and 16.0 sources.

| Before (15.0) | In 16.0 |
|---|---|
| `ir.translation` records, translated columns as `varchar`/`text` | `ir.translation` is gone; a translated field is one JSONB column per record (`{"en_US": ..., "fr_FR": ...}`); write another language with `record.with_context(lang='fr_FR').name = ...` or `record.update_field_translations('name', {'fr_FR': ...})` |
| `records.flush()`, `records.invalidate_cache()`, `records.recompute()` | `flush_model()`, `flush_recordset()`, `env.flush_all()`; `invalidate_model()`, `invalidate_recordset()`, `env.invalidate_all()` (the old names are deprecated) |
| `records.refresh()` | `invalidate_recordset()` (deprecated) |
| `fields_view_get()`, `_fields_view_get()`, `load_views()` | `get_views()`, `get_view()`, `_get_view()` (the old names are deprecated) |
| `fields_get_keys()` | `self._fields` (deprecated) |
| `record.get_xml_id()` | `record.get_external_id()` (deprecated) |
| OWL 1 (`owl.Component`, `owl.hooks`), legacy `web.AbstractField` and `field_registry` widgets | OWL 2 (`import { Component } from "@odoo/owl"`); form, list and kanban views are OWL, field widgets are components in `registry.category("fields")` |
| `web.assets_qweb` bundle for templates | templates go in the bundle of their JS (`web.assets_backend`) |
| `request.jsonrequest` | `request.get_json_data()` (the HTTP layer was rewritten) |
| `http.send_file(...)` | `http.Stream.from_attachment(...)` / `Stream.from_path(...)` then `.get_response()` |
| `request.session.geoip` | `request.geoip` |
| `odoo.tools.ignore(...)` | `contextlib.suppress(...)` |
| — | `fields.Properties` / `fields.PropertiesDefinition`, `fields.Json`; `@api.private`; `_rec_names_search` |

Still the same as 15.0 (changed only in 17.0 or later): `attrs`/`states`, `name_get`, `<tree>`,
`kanban-box`, `group_operator`, `check_access_rights`/`check_access_rule`, `_sql_constraints`,
`type='json'` routes, `_read_group` returning dicts.
