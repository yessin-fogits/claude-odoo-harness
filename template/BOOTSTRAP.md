# Bootstrap contract

This file is the contract between the humans and the agents working on this repository.
`odoo-harness init` must satisfy it before any feature work starts. If it does not, fixing it is the first task.

## Environment
- Odoo version: {{ODOO_VERSION}}, test image `{{ODOO_IMAGE}}` (built from `{{ODOO_DOCKERFILE}}` when set), PostgreSQL image `{{POSTGRES_IMAGE}}`
- Test runtime: the harness's own compose stack (its own containers, database and port; `odoo-harness init`), settings in `harness/harness.env`
- Custom addons (the project's code): `{{CUSTOM_ADDONS}}`
- Third-party addons (read-only): `{{THIRD_PARTY_ADDONS}}`
- Odoo Enterprise (read-only, outside the repository): `{{ENTERPRISE_DIR}}`
- Test database: `{{TEST_DB}}` with demo data (disposable, recreated by `odoo-harness init --reset`)
- Git: task branches `T<code>` start from `{{BASE_BRANCH}}`; merge requests target it (GitLab project `{{GITLAB_PROJECT}}`)

## Commands
| Purpose | Command |
|---|---|
| Start / initialize | `odoo-harness init` |
| Quick health check | `odoo-harness init --check` |
| Reset the test DB | `odoo-harness init --reset` |
| Verify (3 layers) | `odoo-harness verify` |
| Feature workflow | `odoo-harness feature status \| add \| start \| block \| verify` |
| Web UI | http://localhost:{{ODOO_PORT}} |

## Expected baseline
`odoo-harness init` ends with `✓ baseline OK`, which means:
- the `db` and `odoo` containers are running and Odoo answers on `/web/login`;
- the test DB exists and every custom module installs without error;
- `odoo-harness verify` passes on the current code.

## Off-limits
- Odoo core, Odoo Enterprise and third-party (OCA) addons: extend them in custom modules.
- Deployment files, changed by a human: `{{PROTECTED_PATHS}}`.
- Any database other than the test DB, including the dev stack's database.
- Credentials: never write a token or password in a tracked file.

## Ready means
The four initialization steps are done:
1. [ ] Executable environment: `odoo-harness init` reaches `✓ baseline OK`.
2. [ ] Verifiable test frame: at least one passing test at each level (unit, integration, e2e).
3. [ ] This contract is filled in and reviewed by a human.
4. [ ] The work is split into features in `feature_list.json`, reviewed by a human.
