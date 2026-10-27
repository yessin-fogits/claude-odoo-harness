# Progress

## Current state
- Last commit: Phase 1 (core harness)
- Test status: 19 passed (`python -m pytest -q`), compose file validated with `docker compose config`
- Lint: shellcheck clean on template scripts

## Completed tasks
- [x] Phase 1: plugin manifest, template (CLAUDE.md, BOOTSTRAP.md, PROGRESS.md, DECISIONS.md, feature_list.json), harness/init.sh, docker-compose, installer, /odoo-harness:init command

## In progress

## Known issues
- `harness/init.sh` has not run against a real Odoo container yet (no Docker daemon in the build environment). To verify in CI with Docker (Phase 5) or on a dev machine.
- `harness/verify.sh` and `harness/feature.py` are referenced but arrive in Phase 2, so the baseline cannot reach `✓ baseline OK` yet.
- To confirm: `${CLAUDE_PLUGIN_ROOT}` expansion inside command files, and the syntax to install the plugin from a version branch.

## Next steps
- [ ] Phase 2: `harness/feature.py` (state machine, WIP = 1), `harness/verify.sh` (3 layers: pylint-odoo, Odoo tests, Playwright), `errors.yaml` red-pen catalog, evidence store.
