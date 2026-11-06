# Module versions and migrations (Odoo 16.0)

## Version numbers

`'version': '16.0.x.y.z'` in `__manifest__.py`: the first two parts are the Odoo version,
then major.minor.patch of the module. Bump it whenever installed databases need data or
schema changes beyond what the ORM does by itself on `-u`; migration scripts only run
when the version increases.

## Migration scripts

Odoo runs files named `pre-*.py`, `post-*.py` and `end-*.py` from
`<module>/migrations/<version>/`:

```text
sale_discount/
`-- migrations/
    `-- 16.0.1.1.0/
        |-- pre-rename_rate.py     # before the module's models and data are loaded
        |-- post-fill_codes.py     # after the module is updated
        `-- end-cleanup.py         # after all modules are updated
```

Each file defines `migrate(cr, version)`; `version` is the previously installed version:

```python
def migrate(cr, version):
    # pre-: the ORM is not ready for this module yet, use SQL
    cr.execute("ALTER TABLE sale_discount RENAME COLUMN percent TO rate")
```

```python
from odoo import api
from odoo.api import SUPERUSER_ID


def migrate(cr, version):
    # post-: the ORM is ready
    env = api.Environment(cr, SUPERUSER_ID, {})
    for discount in env['sale.discount'].search([('code', '=', False)]):
        discount.code = f"D{discount.id:05d}"
```

- A folder named `0.0.0` runs on every version change.
- Scripts must be idempotent enough to survive a re-run on a partially migrated DB.
- Translated columns are JSONB in 16.0 (`{"en_US": "...", "fr_FR": "..."}`): SQL that reads
  or writes them must handle the JSON, e.g. `name->>'en_US'`.
- In this harness, a migration is verified like any feature: an Odoo test or the
  fresh-install + upgrade layer of `odoo-harness feature verify`.

## Moving code from 15.0

Odoo 16.0 has no automatic code rewriting command. Read `version-notes.md` and port by
hand; the harness check `odoo-version-api` reports the patterns it knows.
