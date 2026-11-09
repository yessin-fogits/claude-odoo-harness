<!-- odoo-harness:start -->
# Odoo harness — Odoo {{ODOO_VERSION}}

This repository is driven by a harness. The repository is the system of record:
everything you need to continue is in these files, not in your memory.

| File | Role |
|---|---|
| `BOOTSTRAP.md` | Bootstrap contract: how to start, verify, reset; what is in and out of scope |
| `tasks/<task>.json` | The features of one Odoo task. State is owned by the harness |
| `tasks/<task>.md` | The notes of one task: its features, what is done and left, known issues, decisions, next steps |
| `PROGRESS.md` | What concerns the whole project: known issues, next steps. Never the harness setup (that is `BOOTSTRAP.md`) |
| `DECISIONS.md` | Dated decisions of the whole project. Read before changing direction |
| `ARCHITECTURE.md` | Map of the project: modules, what they do, how they depend on each other, risks |
| `harness/` | The project's harness settings (`harness.env`, shared by the team; `dev.local.env`, this developer's port, dev DB mode and passwords, never committed), its own checks and red pens, the evidence |

The harness itself is the `odoo-harness` command, installed once per machine with the plugin:
`odoo-harness init` (test environment), `odoo-harness feature ...` (the feature workflow),
`odoo-harness verify`, `odoo-harness gitlab`, `odoo-harness guide`, `odoo-harness static`.
Run it from this repository (or its client workspace).

This is a whole Odoo project. Its own modules are in `{{CUSTOM_ADDONS}}`; third-party addons
(`{{THIRD_PARTY_ADDONS}}`) may be changed too. Odoo core and Enterprise are read-only.
`ARCHITECTURE.md` maps the modules; read it before changing a module you do not know.

# Sessions (automatic)
- At session start the harness loads this checkout's current state, PROGRESS.md, the notes of the current branch's task, the tasks and their features, recent decisions and the baseline health into your context. Start from there.
- After each edit of a module file, fast static checks run on that file. Fix what they report right away.
- When you end a turn, the harness records the current state in `.harness/` (never versioned) and refuses to stop if the state is unclean: static check failures, a broken feature list, or code changed this session without the task's notes (`tasks/<task>.md`) being updated.
- Several developers work on this repository, each on their own task branch. A branch changes only the files of its own task (`tasks/<task>.*`); a feature in progress on another branch is a teammate's, not yours.
- Edits of tasks/*.json, harness/evidence/, the harness engine, Odoo core/enterprise code and deployment files, commands on databases other than the test DB and the dev DB, any drop of a database other than the test DB, and pushes to shared branches are denied.

# Work Rules
- Work on one feature at a time (WIP = 1).
- Only start the next feature after the current one passes e2e verification.
- Do less, but finish. A small feature that passes beats a large one that almost works.
- Stay inside the current feature. If you discover other work, add it as a new feature, do not do it now.
- Before writing code, state your reading of the feature: which users, companies and standard flows it touches. If the task allows more than one reading, ask. Without a human to ask (the autonomous loop), take the simplest reading and write it under Known issues in the task's notes.
- Write the least code that does the behavior, and make it work for any client. No abstractions or behavior the task does not ask for; no handling of cases that cannot happen. But a value that would differ for another client or company (a rate, a threshold, an account, a journal, a product, a partner, an email, a URL) is never a literal in the code: read it from configuration (a setting backed by `ir.config_parameter`, a field on `res.company`, or a data record a user can change), with the client's value as the default.
- Change only the lines the feature needs. Do not reformat, rename or "improve" code next to yours, and do not delete dead code you did not create: mention it in the task's notes. Remove only what your own change made unused.
- Never edit Odoo core or Enterprise. Extend them by inheritance in custom modules.
- Never edit deployment files (Dockerfile, compose files, server configs, CI). If the deployment must change (a new Python dependency, a config option), say what and why; a human changes them.
- If the baseline is broken (`odoo-harness init` fails), fix the baseline before anything else.
- Never write a token or password in a tracked file. Secrets come from the environment or the git-ignored `.env`.

# Odoo tasks and git
- The work comes from Odoo tasks (code `T2003`). A task is split into one or more features: `odoo-harness feature add --task T2003 ...`, which checks out the task's branch and writes `tasks/T2003.json` there. Add a task's features when you take the task.
- No Odoo task yet? Do not wait: use any short name (`--task remise-devis`, letters, digits, `-` and `_`). When the task exists, `odoo-harness feature rename-task remise-devis T2003` renames its files and its branch (feature ids are kept), then commit. Commits already made keep the old name.
- A task is worked on its own branch, named after the task. `odoo-harness feature add` and `start` check it out: the local branch, else a teammate's from GitLab (`origin/T2003`), else a new one from `{{BASE_BRANCH}}`.
- Commit each verified feature with the message `[T2003] F-T2003-1 <behavior>` (`odoo-harness feature verify` prints it).
- When every feature of the task passes and is committed: `odoo-harness gitlab mr T2003` pushes the branch and opens the merge request to `{{BASE_BRANCH}}`. Never push to `{{BASE_BRANCH}}` or `main` yourself.

# Shared submodules
- A git submodule under the addons folders (`.gitmodules`) is a GitLab project that other projects include too. Its modules are verified like this project's, but a change there reaches every project that uses it: keep it backward compatible (never rename or remove a field, method, XML id, menu or view; add instead; new behavior users see stays off by default).
- Before changing one, read its own `CLAUDE.md`, `ARCHITECTURE.md` and `DECISIONS.md` (the session start shows its last decisions once this branch changes it). Record the decisions about its modules in its `DECISIONS.md`, not this project's.
- Commit inside it first, with the task's message (`git -C <path> add -A && git -C <path> commit -m "[T2003] F-T2003-1 <behavior>"`), then commit this project, its new pointer included.
- `odoo-harness gitlab mr T2003` ships it in two merge requests, merged in this order: the submodule's (branch `T2003` of its project, to its `.gitmodules` branch), then this project's, opened as Draft meanwhile. Once the submodule's is merged, run `odoo-harness gitlab mr T2003` again: it pulls the submodule's branch into this branch (the pointer moves to the merged commit) and marks the merge request ready. Never push to the submodule's branch yourself.

# Feature List Rules
- `tasks/<task>.json` is changed only through `odoo-harness feature`. Never edit it by hand. The task's notes, `tasks/<task>.md`, are yours to write (the harness keeps the lines under Features).
- Each feature has: `id` (`F-T2003-1`, numbered within its task), `behavior`, `verification`, `state`, `evidence`; its task is the file it is in.
- The e2e test of a feature is named after its id: `e2e/test_T2003_1_<name>.py`.
- States: `not_started` → `in_progress` → `passing` (or `blocked`).
- You may: `add` a feature, `start` one (refused if another is `in_progress` in this checkout or in its task), `block` one with a reason.
- You may NOT set `passing`. Only `odoo-harness feature verify <id>` sets it, after all verification layers pass, and it records the evidence.

# Definition of Done
A feature is done only when ALL of these are true:
1. `odoo-harness feature verify <id>` passed and set the state to `passing` with evidence.
2. Lint (pylint-odoo) is clean on the changed modules.
3. The task's notes, `tasks/<task>.md`, are updated (what is done and left, known issues, next steps).
4. Any decision taken is recorded: under Decisions in the task's notes, or in `DECISIONS.md` when it concerns the whole project.
5. The work is committed (`[T2003] F-T2003-1 <behavior>`).
6. When it was the last feature of its task: the merge request is open (`odoo-harness gitlab mr <task>`); it stays Draft while the merge request of a shared submodule waits.

"It should work" or "the code looks right" is not done. Evidence is done.

# Validation Hierarchy
Completion is judged by the harness, in three layers:
1. Syntax and static analysis: Python compiles, XML is valid, manifest is consistent, pylint-odoo, project checks in `harness/checks/`.
2. Runtime behaviour: Odoo unit tests (level 1) and integration tests (level 2): module install/upgrade on a test DB, cross-model flows.
3. System confirmation: Playwright e2e tests (level 3) against a running instance. Every feature has its own e2e test. The full e2e suite must pass when a change touches more than one module or shared components.

The tests run on a disposable database with demo data. When the developer sets `DEV_DB` in their `harness/dev.local.env` (dev DB mode), the e2e tests run on the developer's database instead: a neutralized copy of the client's data, updated by verify and never reset. So an e2e test creates the records it needs with unique names (the `unique` fixture) and relies on neither demo records nor a particular client record: it must pass twice in a row (verify runs it, then the user guide replays it on the same database). The tests cover the modules you changed and every custom module that depends on them. Problems in modules you did not touch do not block you: `odoo-harness static --all` lists them as debt. When you touch a module, you own the problems on the lines you change and those that block your feature; report the others, do not fix them now.

Only the e2e test is real verification. Unit tests passing is not enough to declare a feature done.

In e2e tests, ask for the `guide` fixture and call `guide.step("<caption in French>")` after each screen a user sees (after its `expect`), with `highlight=<locator>` for the element to click or fill. It does nothing during verify; `odoo-harness guide` replays the tests to take the screenshots of the task's user guide.

# User guides
`/odoo-harness:guide T2003` writes the user guide of a completed task (every feature passing and committed): a PDF in French for developers, in `docs/guides/T2003.pdf`, with screenshots from the replayed e2e tests. `odoo-harness guide check` lists the guides that a later change made stale.

# Error messages
Harness failures are printed as `✗ [layer] what`, `WHY:`, `HOW TO FIX:`. Read the HOW TO FIX line and apply it before trying anything else.

# When a review finds a new mistake type
Turn it into a check: add a file in `harness/checks/` that detects it with a WHY / HOW TO FIX message (the `add-harness-check` skill scaffolds it), then append a line to `DECISIONS.md`.
When a failure prints "No catalog entry", add its pattern to `harness/errors_project.py` once it is fixed.
<!-- odoo-harness:end -->

# This project
<!-- Written by /odoo-harness:init, then owned by the project: updates never change it.
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
- Commit messages: `[<task>] F-<id> <behavior>`; task branches start from `{{BASE_BRANCH}}`.

## Risky to change
- TODO modules with many dependents or no tests, and why.
