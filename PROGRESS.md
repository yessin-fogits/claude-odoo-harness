# Progress

## Current state
- Last commit: Phase 6 (autonomous maker-checker loop, fixes from live runs)
- Test status: 197 passed on each version branch; odoo-e2e (real Odoo + Playwright) passing on 17.0, 18.0, 19.0, 20.0 (`python -m pytest -q`), including pylint-odoo run on a real module and the compose file validated with `docker compose config`
- Lint: shellcheck clean on template scripts

## Completed tasks
- [x] Phase 1: plugin manifest, template (CLAUDE.md, BOOTSTRAP.md, PROGRESS.md, DECISIONS.md, feature_list.json), harness/init.sh, docker-compose, installer, /odoo-harness:init command
- [x] Phase 2: harness/feature.py (WIP = 1, only verify sets passing, evidence + fingerprint, check), harness/verify.py (L1 static + pylint-odoo, L2 Odoo tests, L3 Playwright e2e + clean server log + fresh install), red-pen catalog harness/errors.py, project checks (harness/checks/), lint and e2e containers, e2e fixtures, pre-commit config

- [x] Phase 3: plugin hooks (hooks/hooks.json): SessionStart context injection + session snapshot, PreToolUse guard (feature list, evidence, Odoo core/enterprise, non-test DBs, docker volumes, --no-verify), PostToolUse static checks on the edited file, Stop gate (rewrites Current state, blocks unclean state, no infinite loop)
- [x] Phase 4: tools/odoo-skill-extract (fetch_odoo.sh, extract.py, check_skill.py); branches 18.0, 19.0, 20.0; odoo skill per branch checked against the real Odoo source (20.0 first, adapted to 19.0, 18.0, 17.0); version-aware security checks; odoo-version-api and model-access project checks; CI jobs skill-check and branches
- [x] Phase 5: add-harness-check skill, odoo-reviewer and odoo-explorer agents, init as a user-only skill, per-version plugin names, main branch with the marketplace and README (EN/FR), demo project builder and odoo-e2e CI job against real Odoo 17-20 (found and fixed: Odoo 20 listening on 127.0.0.1, non-unique e2e data, duplicate red pen for the test summary)

- [x] Update and uninstall paths: unpinned plugin version, autoUpdate, installer --update/--show with file ownership, update skill, errors_project.py, README sections (collaborators, update, uninstall) in EN/FR

- [x] Phase 6: autonomous maker-checker loop (harness/loop.py run/status), bounded attempts and budgets, stash + block on failure, optional odoo-reviewer gate, events log; README section (EN/FR). Live runs with a real Claude maker and reviewer (Docker/curl simulated) found two bugs, both fixed with regression tests: verify refused a feature the maker had already verified, and the Stop gate blocked the reviewer session for the maker's uncommitted work. Third live run: F-001 implemented, verified, reviewed (Accept) and committed in one attempt ($0.19 maker, $0.05 reviewer)

## In progress

## Known issues
- A live headless Claude Code session with the plugin installed from the GitHub marketplace received the SessionStart context, had a shell write to feature_list.json denied by the guard, and ran feature.py. The loop worked a full feature end to end with real agents, but Docker and curl were simulated there: real Odoo is covered by the odoo-e2e CI job, not yet by an agent-driven run.
- Files written by the e2e container in `.harness/runs/` may be owned by root on Linux hosts.
- The repository default branch is not main yet (repository settings cannot be changed from this environment); installs pin main explicitly.

## Next steps
- [ ] Try the plugin on a real client project and turn what goes wrong into checks.
