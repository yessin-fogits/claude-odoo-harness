# Bootstrap contract

This file is the contract between the humans and the agents working on this repository.
`harness/init.sh` must satisfy it before any feature work starts. If it does not, fixing it is the first task.

## Environment
- Odoo version: {{ODOO_VERSION}} (image `{{ODOO_IMAGE}}`), PostgreSQL image `{{POSTGRES_IMAGE}}`
- Runtime: Docker Compose (`docker-compose.yml`), settings in `harness/harness.env`
- Custom addons directory: `{{ADDONS_DIR}}`
- Modules in scope: `{{MODULES}}`
- Test database: `{{TEST_DB}}` (disposable, recreated by `harness/init.sh --reset`)

## Commands
| Purpose | Command |
|---|---|
| Start / initialize | `harness/init.sh` |
| Quick health check | `harness/init.sh --check` |
| Reset the test DB | `harness/init.sh --reset` |
| Verify (3 layers) | `harness/verify.sh` |
| Feature workflow | `harness/feature.py status \| add \| start \| block \| verify` |
| Web UI | http://localhost:{{ODOO_PORT}} |

## Expected baseline
`harness/init.sh` ends with `✓ baseline OK`, which means:
- the `db` and `odoo` containers are running and Odoo answers on `/web/login`;
- the test DB exists and the modules in scope install without error;
- `harness/verify.sh` passes on the current code.

## Off-limits
- Odoo core and enterprise source code (only extend through custom modules).
- Any database other than the test DB.
- Production configuration files and credentials.

## Ready means
The four initialization steps are done:
1. [ ] Executable environment: `harness/init.sh` reaches `✓ baseline OK`.
2. [ ] Verifiable test frame: at least one passing test at each level (unit, integration, e2e).
3. [ ] This contract is filled in and reviewed by a human.
4. [ ] The work is split into features in `feature_list.json`, reviewed by a human.
