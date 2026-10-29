---
name: odoo
description: Odoo 17.0, 18.0, 19.0 and 20.0 development reference, each checked against the Odoo source of its version. Use when writing, reviewing or fixing Odoo module code (models and fields, views XML, security, controllers, OWL components, tests, migrations) so the code matches the project's Odoo version and not another one.
---

# Odoo, by version

The APIs differ a lot between Odoo versions, and most examples you have seen are for another
version. Use only the guide of the project's version.

1. Find the project's version: the session context names it ("Odoo version: ... guide: ..."),
   otherwise it is `ODOO_VERSION` in `harness/harness.env` (or the `FROM odoo:<version>` of the
   project's Dockerfile).
2. Read `versions/<version>/GUIDE.md` in this skill's folder. It lists what other versions get
   wrong and routes to its `references/` (ORM, views, security, OWL, controllers, tests,
   migrations, version notes, the exact API facts).

Guides: `versions/17.0/`, `versions/18.0/`, `versions/19.0/`, `versions/20.0/`. Moving a project
to another version is a migration: read `references/migrations.md` and `references/version-notes.md`
of the target version.
