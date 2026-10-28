<!-- odoo-harness:start -->
# Odoo harness — Odoo {{ODOO_VERSION}}

This repository is driven by a harness. The repository is the system of record:
everything you need to continue is in these files, not in your memory.

| File | Role |
|---|---|
| `BOOTSTRAP.md` | Bootstrap contract: how to start, verify, reset; what is in and out of scope |
| `PROGRESS.md` | Current state, completed / in-progress tasks, known issues, next steps |
| `DECISIONS.md` | Dated decisions. Read before changing direction; append when you decide |
| `ARCHITECTURE.md` | Map of the project: modules, what they do, how they depend on each other, risks |
| `feature_list.json` | The work, split into features. State is owned by the harness |
| `harness/` | Scripts that run the environment and the verification |

This is a whole Odoo project. Its own modules are in `{{CUSTOM_ADDONS}}`: the only code you change.
Third-party addons (`{{THIRD_PARTY_ADDONS}}`) and Odoo Enterprise are read-only.
`ARCHITECTURE.md` maps the modules; read it before changing a module you do not know.

# Sessions (automatic)
- At session start the harness loads PROGRESS.md, recent decisions, the current feature and the baseline health into your context. Start from there.
- After each edit of a module file, fast static checks run on that file. Fix what they report right away.
- When you end a turn, the harness rewrites "Current state" in PROGRESS.md and refuses to stop if the state is unclean: static check failures, a broken feature list, or code changed this session without PROGRESS.md being updated.
- Edits of feature_list.json, harness/evidence/, Odoo core/enterprise code, third-party addons and deployment files, commands on non-test databases and pushes to shared branches are denied.

# Work Rules
- Work on one feature at a time (WIP = 1).
- Only start the next feature after the current one passes e2e verification.
- Do less, but finish. A small feature that passes beats a large one that almost works.
- Stay inside the current feature. If you discover other work, add it as a new feature, do not do it now.
- Never edit Odoo core, Enterprise or third-party (OCA) addons. Extend by inheritance in custom modules only.
- Never edit deployment files (Dockerfile, compose files, server configs, CI). If the deployment must change (a new Python dependency, a config option), say what and why; a human changes them.
- If the baseline is broken (`harness/init.sh` fails), fix the baseline before anything else.
- Never write a token or password in a tracked file. Secrets come from the environment or the git-ignored `.env`.

# Odoo tasks and git
- The work comes from Odoo tasks (code `T2003`). A task is split into one or more features: `harness/feature.py add --task T2003 ...`.
- A task is worked on its own branch, named after the task. `harness/feature.py start` checks it out, creating it from `{{BASE_BRANCH}}` the first time.
- Commit each verified feature with the message `[T2003] F-001 <behavior>` (feature.py verify prints it).
- When every feature of the task passes and is committed: `harness/gitlab.py mr T2003` pushes the branch and opens the merge request to `{{BASE_BRANCH}}`. Never push to `{{BASE_BRANCH}}` or `main` yourself.

# Feature List Rules
- `feature_list.json` is changed only through `harness/feature.py`. Never edit it by hand.
- Each feature has: `id`, `behavior`, `verification`, `state`, `evidence`, and the `task` it belongs to.
- States: `not_started` → `in_progress` → `passing` (or `blocked`).
- You may: `add` a feature, `start` one (refused if another is `in_progress`), `block` one with a reason.
- You may NOT set `passing`. Only `harness/feature.py verify <id>` sets it, after all verification layers pass, and it records the evidence.

# Definition of Done
A feature is done only when ALL of these are true:
1. `harness/feature.py verify <id>` passed and set the state to `passing` with evidence.
2. Lint (pylint-odoo) is clean on the changed modules.
3. `PROGRESS.md` is updated (completed task, known issues, next steps).
4. Any decision taken is appended to `DECISIONS.md`.
5. The work is committed (`[T2003] F-001 <behavior>`).
6. When it was the last feature of its task: the merge request is open (`harness/gitlab.py mr <task>`).

"It should work" or "the code looks right" is not done. Evidence is done.

# Validation Hierarchy
Completion is judged by the harness, in three layers:
1. Syntax and static analysis: Python compiles, XML is valid, manifest is consistent, pylint-odoo, project checks in `harness/checks/`.
2. Runtime behaviour: Odoo unit tests (level 1) and integration tests (level 2): module install/upgrade on a test DB, cross-model flows.
3. System confirmation: Playwright e2e tests (level 3) against a running instance. Every feature has its own e2e test. The full e2e suite must pass when a change touches more than one module or shared components.

The tests run on a disposable database with demo data. They cover the modules you changed and every custom module that depends on them. Problems in modules you did not touch do not block you: `harness/static_checks.py --all` lists them as debt. When you touch a module, you own its problems.

Only the e2e test is real verification. Unit tests passing is not enough to declare a feature done.

# Error messages
Harness failures are printed as `✗ [layer] what`, `WHY:`, `HOW TO FIX:`. Read the HOW TO FIX line and apply it before trying anything else.

# When a review finds a new mistake type
Turn it into a check: add a file in `harness/checks/` that detects it with a WHY / HOW TO FIX message (copy the shape of `harness/checks/no_debug_leftovers.py`), then append a line to `DECISIONS.md`.
When a failure prints "No catalog entry", add its pattern to `harness/errors_project.py` once it is fixed.
<!-- odoo-harness:end -->

# This project
<!-- Written by /odoo-harness-{{ODOO_MAJOR}}:init, then owned by the project: updates never change it.
     Replace every TODO line. Keep it short: the module map belongs in ARCHITECTURE.md. -->

## Client and business
- Client: TODO who they are (company, sector, country) and who uses Odoo there.
- Business context: TODO what the project does for them, in two lines, and the main business flows it supports.

## Odoo
- Version: Odoo {{ODOO_VERSION}}, TODO Community or Enterprise; localization and languages.
- Odoo apps in use: TODO (for example sale, purchase, stock, account, mrp, hr).
- Custom modules: `{{CUSTOM_ADDONS}}`. TODO the key modules, one line each, and where a new module goes.

## Conventions
- TODO module name prefix, manifest author and version scheme, translations, other project rules.
- Commit messages: `[T<code>] F-<id> <behavior>`; task branches start from `{{BASE_BRANCH}}`.

## Risky to change
- TODO modules with many dependents or no tests, and why.
