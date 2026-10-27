# Progress

## Current state
- Last commit: Phase 3 (automatic session hooks)
- Test status: 109 passed (`python -m pytest -q`), including pylint-odoo run on a real module and the compose file validated with `docker compose config`
- Lint: shellcheck clean on template scripts

## Completed tasks
- [x] Phase 1: plugin manifest, template (CLAUDE.md, BOOTSTRAP.md, PROGRESS.md, DECISIONS.md, feature_list.json), harness/init.sh, docker-compose, installer, /odoo-harness:init command
- [x] Phase 2: harness/feature.py (WIP = 1, only verify sets passing, evidence + fingerprint, check), harness/verify.py (L1 static + pylint-odoo, L2 Odoo tests, L3 Playwright e2e + clean server log + fresh install), red-pen catalog harness/errors.py, project checks (harness/checks/), lint and e2e containers, e2e fixtures, pre-commit config

- [x] Phase 3: plugin hooks (hooks/hooks.json): SessionStart context injection + session snapshot, PreToolUse guard (feature list, evidence, Odoo core/enterprise, non-test DBs, docker volumes, --no-verify), PostToolUse static checks on the edited file, Stop gate (rewrites Current state, blocks unclean state, no infinite loop)

## In progress

## Known issues
- Nothing has run against real Odoo / Docker yet (no Docker daemon in the build environment): verify.py is tested through a fake `docker compose` that replays Odoo, pylint and Playwright output. Real run planned in CI (Phase 5).
- The Odoo log formats parsed by verify.py (test summary, FAIL lines) are from Odoo 16+; to confirm on each version branch.
- Files written by the e2e container in `.harness/runs/` may be owned by root on Linux hosts.
- To confirm: `${CLAUDE_PLUGIN_ROOT}` expansion inside command files, and the syntax to install the plugin from a version branch.
- Hooks are tested by feeding them the documented hook JSON; not yet exercised inside a live Claude Code session with the plugin installed.

## Next steps
- [ ] Phase 4: Odoo skill built from the odoo/odoo source (20.0 first, or master if 20.0 is not cut), with the extractor in tools/odoo-skill-extract/, then adapted to 19.0, 18.0 and 17.0.
