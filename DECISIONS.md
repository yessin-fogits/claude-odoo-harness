# Decisions

Append-only. One line per decision: `- YYYY-MM-DD: decision (why)`.

- 2026-10-27: Distribute as a Claude Code plugin + a template installed by `/odoo-harness:init` (shared logic updated in one place, project state stays in the project repo).
- 2026-10-27: One branch per Odoo version (17.0 → 20.0); shared harness changes land on 17.0 and are forward-ported.
- 2026-10-27: Docker Compose runtime with a disposable test DB (`dbfilter` locks the server to it).
- 2026-10-27: Instruction files in English; README and docs in English and French.
- 2026-10-27: No /session-start or /session-end commands; session start and end are automatic (hooks).
- 2026-10-27: Lint with pylint-odoo; e2e with Playwright.
- 2026-10-27: The template installer is a deterministic Python script; it never overwrites state files and merges CLAUDE.md, settings.json and .gitignore.
- 2026-10-27: Red-pen catalog is a Python module (`harness/errors.py`), not errors.yaml: no PyYAML needed on the host, and raw-string regexes are easy for agents to extend.
- 2026-10-27: Verification logic in Python (`harness/verify.py`, standard library only); `harness/verify.sh` is a thin wrapper.
- 2026-10-27: pylint-odoo and Playwright run in pinned containers (compose profile `tools`: `lint`, `e2e`), so every machine lints and tests the same way.
- 2026-10-27: The OCA-only rules manifest-required-author and missing-readme are disabled on the pylint command line (an rc-file `enable=odoolint` overrides any rc-file `disable`).
- 2026-10-27: Evidence integrity by fingerprint (sha256 of id + behavior + verification); changing a passing feature breaks `feature.py check`. `harness/evidence/` is write-denied to the agent.
- 2026-10-27: A feature's verification must include its own e2e test; zero Odoo tests or zero e2e tests count as a failure.
- 2026-10-27: Full e2e suite runs on the baseline, and on a feature verify when the change touches more than one module or shared files (anything outside one module, its e2e test files and docs).
- 2026-10-27: The fresh-DB install (L3) runs on `feature.py verify` only, not on the baseline, to keep `init.sh` fast.
- 2026-10-27: Hooks live in the plugin and stay thin: they call the project's harness scripts (static_checks.py, feature.py check, init.sh --check) and do nothing in projects without the harness.
- 2026-10-27: The Stop gate runs at the end of every turn, so it only blocks for an unclean state: static findings, broken feature list, or module/e2e code changed this session while PROGRESS.md (outside "Current state") is unchanged. With stop_hook_active it lets the turn end and records the problems in PROGRESS.md "Known issues" (no infinite loop).
- 2026-10-27: Odoo core/enterprise detection: an ancestor with odoo-bin, or a module whose manifest author is "Odoo S.A." or license OEEL; extra paths via PROTECTED_PATHS in harness.env.
- 2026-10-27: The Bash guard parses commands with shlex (quote-aware); a command mentioning feature_list.json or harness/evidence/ must be read-only or harness/feature.py; unparsable ones are denied.
- 2026-10-27: Commands on any database other than TEST_DB (and its _fresh twin), docker volume deletion and `git commit --no-verify` are denied.
- 2026-10-27: The odoo skill is written per version branch from the real odoo/odoo source of that version (20.0 first, then adapted to 19.0, 18.0, 17.0). tools/odoo-skill-extract extracts version facts (API exports, field types, view RNG, security format, route types, OWL exports, upgrade_code steps, deprecations) and check_skill.py fails CI if a reference uses API that does not exist in the branch's version.
- 2026-10-27: Shared harness files stay identical on all branches by being version-aware (ODOO_VERSION): security CSV format (ir.access from 20.0), odoo-version-api rules with version ranges, model-access check. Only odoo_version.json and skills/odoo/ differ per branch (merge=ours in .gitattributes).
- 2026-10-27: Every code example of a branch's skill must pass the harness odoo-version-api rules for that version (test), so the skill never teaches what the harness rejects.
- 2026-10-27: The e2e login presses Enter in the password field instead of clicking the first submit button (Odoo 20.0's login page has several).
- 2026-10-27: One marketplace on main, one plugin per Odoo version (odoo-harness-17 ... -20), each pinned to its branch with ref, so projects of different versions can use the harness on the same machine. plugin.json is per branch (entry name must equal manifest name).
- 2026-10-27: Projects pin the marketplace to ref main (the repository default branch could not be changed from this environment).
- 2026-10-27: init is a skill with disable-model-invocation (commands/ is the older plugin format); only the user starts initialization.
- 2026-10-27: The review -> check loop is a skill (add-harness-check) plus a read-only odoo-reviewer agent that proposes checks for new kinds of mistakes.
- 2026-10-27: CI runs the harness against real Odoo, PostgreSQL and Playwright in Docker on every version branch (tools/make_demo_project.py + odoo-e2e job), including an injected bug that must fail verification with a red-pen message and no unknown error.
- 2026-10-27: Odoo listens on 0.0.0.0 inside the container (Odoo 20.0 defaults to 127.0.0.1); the host port is published on 127.0.0.1 only.
- 2026-10-27: The e2e test DB persists between runs; e2e tests name what they create with the unique fixture.
- 2026-10-27: Red pens always show a short excerpt of the failing record (the assertion message), and the Odoo test summary record is not reported as a separate error.
- 2026-10-27: plugin.json has no version: Claude Code then versions the plugin by the commit of its branch, so pushes reach users (a pinned version keeps everyone on the cached copy).
- 2026-10-27: Projects turn on autoUpdate for the odoo-harness marketplace (third-party marketplaces do not auto-update by default).
- 2026-10-27: Installed files have an owner: state (never overwritten), project (created once, kept by --update which reports template changes as kept*), harness (replaced by --update), merged (CLAUDE.md block, settings, .gitignore). The update skill runs install_template.py --update; a different Odoo version is refused as a migration.
- 2026-10-27: The red-pen catalog is split: harness/errors.py (harness, updated) and harness/errors_project.py (project patterns, checked first, never overwritten).
