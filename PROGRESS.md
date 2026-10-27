# Progress

## Current state
- Last commit: Phase 5 (review -> check loop, real Odoo e2e CI, main branch marketplace)
- Test status: 175 passed on each version branch; odoo-e2e (real Odoo + Playwright) passing on 17.0, 18.0, 19.0, 20.0 (`python -m pytest -q`), including pylint-odoo run on a real module and the compose file validated with `docker compose config`
- Lint: shellcheck clean on template scripts

## Completed tasks
- [x] Phase 1: plugin manifest, template (CLAUDE.md, BOOTSTRAP.md, PROGRESS.md, DECISIONS.md, feature_list.json), harness/init.sh, docker-compose, installer, /odoo-harness:init command
- [x] Phase 2: harness/feature.py (WIP = 1, only verify sets passing, evidence + fingerprint, check), harness/verify.py (L1 static + pylint-odoo, L2 Odoo tests, L3 Playwright e2e + clean server log + fresh install), red-pen catalog harness/errors.py, project checks (harness/checks/), lint and e2e containers, e2e fixtures, pre-commit config

- [x] Phase 3: plugin hooks (hooks/hooks.json): SessionStart context injection + session snapshot, PreToolUse guard (feature list, evidence, Odoo core/enterprise, non-test DBs, docker volumes, --no-verify), PostToolUse static checks on the edited file, Stop gate (rewrites Current state, blocks unclean state, no infinite loop)
- [x] Phase 4: tools/odoo-skill-extract (fetch_odoo.sh, extract.py, check_skill.py); branches 18.0, 19.0, 20.0; odoo skill per branch checked against the real Odoo source (20.0 first, adapted to 19.0, 18.0, 17.0); version-aware security checks; odoo-version-api and model-access project checks; CI jobs skill-check and branches
- [x] Phase 5: add-harness-check skill, odoo-reviewer and odoo-explorer agents, init as a user-only skill, per-version plugin names, main branch with the marketplace and README (EN/FR), demo project builder and odoo-e2e CI job against real Odoo 17-20 (found and fixed: Odoo 20 listening on 127.0.0.1, non-unique e2e data, duplicate red pen for the test summary)

- [x] Update and uninstall paths: unpinned plugin version, autoUpdate, installer --update/--show with file ownership, update skill, errors_project.py, README sections (collaborators, update, uninstall) in EN/FR

## In progress

## Known issues
- The hooks are tested with the documented hook JSON and the plugin installs and loads for real (3 skills, 2 agents, 4 hooks), but no full Claude Code session has yet worked a feature end to end with the plugin active.
- Files written by the e2e container in `.harness/runs/` may be owned by root on Linux hosts.
- The repository default branch is not main yet (repository settings cannot be changed from this environment); installs pin main explicitly.

## Next steps
- [ ] Phase 6 (later): autonomous loops (course lectures 13-14), e.g. a headless `claude -p` loop over feature_list.json.
- [ ] Try the plugin on a real client project and turn what goes wrong into checks.
