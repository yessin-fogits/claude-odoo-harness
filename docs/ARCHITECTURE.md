# Plan: `claude-odoo-harness`, a Claude Code harness for Odoo projects

## Context
We are building a GitHub project that gives any Odoo project a ready-made Claude Code harness. It follows the *Learn Harness Engineering* course (walkinglabs) and the user's notes.

The course's core idea is that reliability comes from the system around the model, not from the model itself. That system has five parts: instructions, tools, environment, state and feedback.

The user's notes add these requirements:
- Context lives in `PROGRESS.md`, `DECISIONS.md` and each task's notes (`tasks/<task>.md`).
- Sessions start and end automatically, with no `/session-*` commands.
- Initialization follows 4 steps.
- WIP = 1, and the motto is "faire moins mais terminer" (do less, but finish).
- The harness owns feature state transitions.
- Completion is validated in 3 layers, with "red pen" error messages.
- E2E tests use Playwright. Lint uses pylint-odoo.
- Every new agent mistake found in a review becomes an automated check.
- The project ships an Odoo skill built from the `odoo/odoo` source for version 20 and adapted to each version.

## Install once per machine
A developer works on many Odoo projects, so the harness is split as gstack splits its own
tools: **the engine is installed once per machine, the repository holds no copy of it.** But
unlike gstack, which keeps project state in `~/.gstack/projects/`, the state stays in the
repository: the task files, the evidence and PROGRESS.md are the team's shared record.

| Where | What | Updated by |
|---|---|---|
| The plugin (`claude plugin install odoo-harness@odoo-harness`, user scope) | hooks, skills, agents, the engine (`engine/`: feature, verify, init, loop, gitlab, guide, static checks, generic checks, red-pen catalog, Docker files) and the `odoo-harness` command (`bin/`) | the plugin update, for every project at once |
| The repository | state (`PROGRESS.md`, `DECISIONS.md`, `tasks/`, `BOOTSTRAP.md`, `ARCHITECTURE.md`, `harness/evidence/`), project config (`harness/harness.env`, shared; the git-ignored `harness/dev.local.env` holds each developer's port, dev DB mode and passwords; `harness/errors_project.py`, project checks in `harness/checks/`, `e2e/`, `.pylintrc`), the `CLAUDE.md` block and `.claude/settings.json` | the project |
| `~/.odoo-harness/` | `current`, a symlink to the installed plugin, refreshed at each session start; the `odoo-harness` shim in `~/.local/bin` points through it | the session start hook |

- **One command.** `odoo-harness <init|verify|feature|loop|gitlab|guide|map|static>` replaces
  `harness/<script>`. It finds the repository from the current folder (the repository itself,
  or `git/` in a client workspace) and runs the engine on it. Claude's Bash tool gets the
  plugin's `bin/` on its PATH from the session start hook (`CLAUDE_ENV_FILE`); humans use the
  shim; the command puts its own `bin/` first on the PATH of every child process, so
  `loop.py`'s headless sessions reach the same engine.
- **Docker.** The compose file is the engine's. Its build contexts and the engine mount
  (`/opt/odoo-harness`, read-only, in the lint and e2e containers) come from `HARNESS_HOME`,
  which every compose call exports through one function (`hlib.compose_env`). The lint and
  e2e images are the machine's, not the project's: one image per Dockerfile
  (`odoo-harness-<tool>:<hash>`), shared by every project, and `init` removes the ones no
  project uses any more. `odoo.conf` is rendered from
  `harness/harness.env` and `harness/dev.local.env` into `.harness/odoo.conf` before each compose call.
- **Engine version.** `engine/VERSION`, not `plugin.json` (a `version` there would change how
  Claude Code detects updates). `harness/harness.env` pins a minimum, `HARNESS_VERSION`:
  the engine refuses to run on a project pinned to a newer engine, so a teammate with an old
  plugin cannot verify. It is a minimum, not an exact match, so auto-updates never block
  anyone. Every evidence file records the engine version that produced it. `engine/VERSION`
  is bumped with every change that can alter a verdict or a command; otherwise two different
  engines would carry the same number and the pin could not tell them apart.
- **Activation by marker.** The hooks run in every session, so each one first checks for
  `harness/harness.env` and `tasks/` (or a legacy `feature_list.json`) in the launch folder or `git/`, and exits
  otherwise. In an Odoo repository without the harness (`__manifest__.py` one level down in
  the folder or `git/`, never a recursive scan), the session start hook offers `init` once.
- **Client workspace.** Started in `~/Project/<client>`, the hooks find `git/` and inject the
  repository's `CLAUDE.md`: nothing is generated in the workspace.
- **Permissions.** A user-scope plugin cannot ship permission rules. `init` asks the user
  once per machine whether to add `Bash(odoo-harness:*)` to `~/.claude/settings.json`; the
  repository's `.claude/settings.json` keeps its deny rules and enables the plugin for
  teammates.
- **The engine is protected.** Edits under the plugin folder and `~/.odoo-harness/` are denied
  like `tasks/*.json`: the judge cannot be rewritten by the agent it judges.
- **Migration of a project with the old vendored harness.** While `harness/feature.py` is
  still in the repository, the new hooks stand down and tell the user to run
  `/odoo-harness:update`. The update deletes the vendored engine files, writes
  `HARNESS_VERSION`, rewrites the permission and pre-commit entries, removes
  `odoo-harness-<N>@odoo-harness` from the repository and workspace settings, and keeps state
  and config. The old plugin then sees no `harness/feature.py` and goes quiet by itself.

## Decisions
- **Distribution**: one Claude Code plugin, `odoo-harness`, installed once per machine (user
  scope). See "Install once per machine" below. Per-project state lives in the repo, which is
  the system of record.
- **Versions**: one plugin for every Odoo version (16.0 to 20.0); the version is data.
  - `versions.json` lists the supported versions and their PostgreSQL image.
  - The project's version is `ODOO_VERSION` in `harness/harness.env`, detected by `init`.
  - The `odoo` skill holds one guide per version: `skills/odoo/versions/<version>/`.
  - CI runs the tests, the skill check and the e2e demo for each version (a matrix).
  - The old `17.0`...`20.0` branches are frozen: they serve the deprecated
    `odoo-harness-<N>` plugins until every project is migrated. 16.0 came later and never
    had a branch: it exists only in the one plugin.
- **Runtime**: Docker Compose with these services:
  - `odoo`, using the image of the project's version.
  - `db`, running Postgres.
  - `e2e`, running Playwright for Python against `odoo:8069`.
  - Tests use a disposable DB, so the agent never touches real data.
- **Language**: instruction files (CLAUDE.md, skills, agents) are in English. The README and `docs/` exist in English and French.
- **Automatic sessions**: there are no `/session-start` or `/session-end` commands. Hooks do this work (see below).

## Target Odoo repo after `/odoo-harness:init`
```
CLAUDE.md            # Work Rules, Feature List Rules, Definition of Done, Validation Hierarchy
BOOTSTRAP.md         # bootstrap contract (init step 3)
PROGRESS.md          # the whole project: Known issues | Next steps (the harness never writes it)
DECISIONS.md         # "YYYY-MM-DD: decision (why)", append-only
ARCHITECTURE.md      # map of the project: modules, dependencies, risks and debt
tasks/
  <task>.json        # the features of one task, state changed only by `odoo-harness feature`
  <task>.md          # the task's notes: Features | Notes | Known issues | Decisions | Next steps
.gitattributes       # DECISIONS.md merge=union
harness/
  harness.env        # the project's harness settings, shared: HARNESS_VERSION (engine pin)
  dev.local.env      # not versioned: this developer's port, dev DB mode (DEV_*), passwords
  checks/            # project checks born from code reviews (one file per mistake type)
  errors_project.py  # the project's red pens
  evidence/          # per-feature evidence (JSON committed; traces gitignored)
e2e/                 # Playwright (pytest-playwright) tests, one file per feature: test_T2003_1_*.py for F-T2003-1
.pylintrc (pylint-odoo), .pre-commit-config.yaml
.claude/settings.json  # deny rules, the odoo-harness command allowed, the plugin enabled
.harness/            # not versioned: odoo.conf rendered from the settings, logs, session state, current-state.md
```
No engine file is copied: `odoo-harness` (the plugin) runs on this repository.

### Client workspace
Developers may start Claude Code in the client folder (`~/Project/<client>`) instead of the
repository (`~/Project/<client>/git`). Nothing is generated there: `odoo-harness` and the
hooks find the harness in `git/` on their own, and SessionStart injects `git/CLAUDE.md` when
the workspace does not import it. The permission prompts are avoided by `Bash(odoo-harness:*)`
in the user settings (offered once per machine by `init`). `update --workspace .` removes the
files the old harness generated there.

### File formats
- **PROGRESS.md** holds what concerns the whole project: `## Known issues` and `## Next steps`.
  The harness never writes it, so it changes only when a developer means to.
- **tasks/<task>.md**, the notes of one task: `## Features` (`- [x] F-T2003-1 …` once verified,
  `- [ ] F-T2003-2 …` otherwise, kept by the harness), `## Notes`, `## Known issues`,
  `## Decisions`, `## Next steps`. Only the developer on the task's branch writes it.
- **.harness/current-state.md** (not versioned): last commit, test and lint status. The Stop
  hook rewrites it; it is machine state, so it never reaches a merge request.
- **DECISIONS.md**: one line per decision, `- 2026-10-27: Use Playwright for e2e (Odoo tours too coupled to JS assets)`.
- **tasks/<task>.json** holds the features of one task, with the minimal fields `id`, `behavior`, `verification`, `state` and `evidence`:
  ```json
  {"version": 2, "task": "T2003",
   "features": [{"id": "F-T2003-1",
    "behavior": "Salesperson applies a 10% discount on a quotation line",
    "verification": ["unit: sale_discount.tests.test_discount", "e2e: e2e/test_T2003_1_discount.py"],
    "state": "not_started", "evidence": null}]}
  ```
  `state` is one of `not_started`, `in_progress`, `blocked` or `passing`. Ids are numbered per
  task, `F-<task>-<n>`, so two branches never pick the same one; they keep their task's name
  after a `rename-task`. Legacy ids (`F-001`) stay valid.

### Several developers on one project
A task is one branch (`T2003`) and its own files, `tasks/T2003.json` and `tasks/T2003.md`.
Developers on different tasks never touch the same harness file, so their merge requests merge
without conflict, whatever the order.
- **WIP = 1 per checkout and per task.** A feature in progress on a teammate's branch reaches
  your checkout once it is merged into the base; it does not block you. `feature status` shows
  it as `in_progress, other branch`; the session start hook lists it as a teammate's work.
- **Taking a task** (`feature add` or `feature start`) checks out its branch: the local one
  (fast-forwarded to GitLab, refused when the two diverged), else `origin/<task>` (a teammate's
  branch, tracked), else a new one from the base branch. An `origin/<task>` from before the
  harness, or with the legacy layout, is refused with the two ways out.
- **The loop** works only on the task of the current branch or on tasks that have no branch on
  GitLab: another one is a teammate's.
- **Migration.** `/odoo-harness:update` on a project of an engine before 3.0 splits the single
  feature file into task files (ids kept), moves the PROGRESS.md feature lines to the task
  notes and drops its "Current state". It must land in the base branch before anyone opens a
  task branch.

## Initialization (4 steps, done by `/odoo-harness:init` and re-checked each session)
1. **Executable environment**: `odoo-harness init` (the engine's compose stack). Odoo starts, the test DB is created and the custom modules install cleanly. In dev DB mode (`DEV_DB`) the harness has no PostgreSQL of its own: the test DB lives on the dev stack's server, and the e2e layer runs on the dev DB after checking it is neutralized and updating it with `-u` (never dropped or reset).
2. **Verifiable test frame**: `verify.sh` runs pylint-odoo, the `odoo-bin --test-enable` unit and integration tests, and the Playwright e2e tests. A sample passing test exists at each level.
3. **Bootstrap contract**: `BOOTSTRAP.md` defines what "ready" means:
   - the start, verify and reset commands;
   - the expected baseline output;
   - the modules in scope and the paths that are off-limits (core and enterprise).
   - `init` refuses to finish until the contract holds.
4. **Task breakdown**: the requirements are turned into small features in `tasks/<task>.json`, each with a behavior and verification steps. The user reviews them before work starts. With several developers, each one adds a task's features when taking it.

## CLAUDE.md content (short; details live in skills)
- `# Work Rules`
  - Work on one feature at a time (WIP = 1).
  - Start the next feature only after the current one passes e2e verification.
  - Do less, but finish.
  - State the reading of the feature before coding; ask when it is ambiguous.
  - Write the least code that does the behavior; change only the lines it needs.
  - Make it work for any client: values that differ between clients come from configuration, not literals.
  - Never edit Odoo core or enterprise code.
- `# Feature List Rules`
  - Change state only through `odoo-harness feature`.
  - Never edit `tasks/*.json` by hand.
  - Never mark a feature `passing` yourself. Only `feature.py verify` can do it.
  - New work goes into the list through `feature.py add`.
- `# Definition of Done`
  - The feature's verification steps all pass through `feature.py verify`.
  - The evidence is recorded.
  - Lint is clean.
  - The task's notes (`tasks/<task>.md`) are updated.
  - The work is committed.
- `# Validation Hierarchy`
  - Level 1: unit tests.
  - Level 2: integration tests (module install and upgrade, cross-model flows).
  - Level 3: e2e (Playwright). Every feature needs its own e2e test. The full e2e suite is required when the change touches more than one module or shared components.
- `# When a review finds a new mistake type`: add a check in `harness/checks/` and log it in DECISIONS.md.

## Harness-controlled state transitions
- `feature.py start ID` is refused if another feature is `in_progress` in this checkout or in the same task (WIP = 1).
- `feature.py block ID --reason` sets `blocked`.
- `feature.py verify ID` is the only way to reach `passing`:
  - It runs the 3 layers.
  - It writes evidence: commit SHA, a log summary, and the paths to Playwright traces and screenshots.
  - It ticks the feature in the task's notes (`tasks/<task>.md`).
- A `passing` feature goes back to `in_progress` if a later verify shows a regression.
- Enforcement:
  - The PreToolUse hook denies `Edit` and `Write` on `tasks/*.json`.
  - It also denies `Bash` commands that write to that file other than `odoo-harness feature`.
  - A pre-commit check rejects a `passing` state that has no matching evidence file.

## Three-layer completion validation (`verify.sh`)
1. **Syntax and static analysis**:
   - `py_compile`
   - XML well-formedness, plus view validation against the version's RNG schemas
   - manifest check (version bump, `depends`, data files exist)
   - **pylint-odoo**
   - the project checks in `harness/checks/`
2. **Runtime behavior**: `odoo-bin -d <testdb> -i/-u <modules> --test-enable --test-tags <tags> --stop-after-init`. The log is parsed: any ERROR or traceback fails the layer.
3. **System confirmation**:
   - Playwright e2e against a freshly upgraded instance;
   - a clean server log during the run;
   - the module upgrade succeeds on a fresh DB.

### Red-pen messages
Every failure is printed as:
```
✗ [L2 runtime] sale_discount: test_discount_applied FAILED
WHY: field 'discount_rate' computed without @api.depends → value never recomputed
HOW TO FIX: add @api.depends('order_line.price_unit') on _compute_discount_rate; re-run odoo-harness feature verify F-T2003-1
REF: skills/odoo/references/orm.md#computed-fields
```
`errors.yaml` maps known patterns to the WHY and HOW TO FIX lines. Patterns include pylint-odoo codes, `External ID not found`, `Field … does not exist`, `AccessError`, `ParseError` in views, and Playwright timeouts. Unknown errors print the raw failure and ask the agent to add a pattern.

### Review → check loop
When a code review finds a new type of agent mistake:
- The plugin skill `add-harness-check` scaffolds `harness/checks/<id>.py`. The check has a detect function and a red-pen message, and it runs in layer 1 from then on.
- A matching entry goes into DECISIONS.md.
- Generic checks are upstreamed into the plugin's template.

## Automatic session hooks (plugin `hooks/hooks.json`)
- **SessionStart**:
  - Runs a quick `init.sh --check`: containers up, DB exists, baseline lint.
  - Injects into the context: the current state (`.harness/current-state.md`), the PROGRESS.md "Known issues" and "Next steps", the last 10 DECISIONS, the notes of the current branch's task, the `in_progress` feature of this checkout with its verification steps, and the features in progress on other branches (teammates' work).
  - If the baseline is broken, it tells the agent to fix it first.
- **PreToolUse**:
  - Protects `tasks/*.json` and `harness/evidence/`.
  - Blocks edits to Odoo core and enterprise paths.
  - Blocks `dropdb` / `DROP DATABASE` on any DB but the test DB, and Odoo commands on DBs other than the test DB and the dev DB (`DEV_DB`).
- **PostToolUse** (on Edit and Write of `.py` and `.xml` files): runs fast layer 1 checks on the changed file and returns red-pen feedback.
- **Stop** (the automatic session end):
  - Rewrites `.harness/current-state.md` (last commit, test and lint status).
  - Blocks stopping, with red-pen instructions, if any of these is true:
    - code changed in the session and neither the task's notes nor PROGRESS.md did;
    - lint fails;
    - the `in_progress` feature has no notes in its task's notes;
    - debug leftovers remain (`pdb`, `print(`, `console.log`).

## Odoo skill (built from github.com/odoo/odoo, version 20 first)
- Source: the `20.0` branch of `odoo/odoo` (or `master` if `20.0` is not cut yet), shallow-cloned.
- `skills/odoo/SKILL.md` stays short and routes to `references/`:
  - `orm.md`: fields, decorators, compute/inverse/search, constraints, recordsets, `Command`, `sudo` and `with_context`
  - `views.md`: list, form, search and kanban, xpath inheritance, actions and menus, based on the real RNG schemas
  - `owl.md`: OWL components, assets bundles, `@web` imports
  - `security.md`: `ir.model.access.csv`, record rules, groups, multi-company
  - `testing.md`: `TransactionCase`, `Form`, tags, plus Playwright e2e patterns for the Odoo web client
  - `migrations.md`: pre/post/end scripts
  - `version-notes.md`: what changed compared with the previous version
- `tools/odoo-skill-extract/` is a script that pulls facts from the source: field classes, decorators, view RNG files, test base classes, the OWL version and deprecation warnings. It checks the references against the real code and produces the version diff.
- Per-version adaptation: on each branch (`19.0`, `18.0`, `17.0`), run the extractor on that Odoo branch. Then adjust the references, for example `<list>` versus `<tree>` before 18 and the API removals and renames. `version-notes.md` and the extractor's diff document each change.

## Plugin repo layout (branch `main`)
```
.claude-plugin/{plugin.json, marketplace.json}   # odoo-harness, plus the deprecated per-version plugins
bin/odoo-harness                 # the command (-> engine/cli.py)
engine/                          # the engine, run on the repository in $HARNESS_REPO
  cli.py VERSION hlib.py feature.py verify.py init.sh lib.sh loop.py gitlab.py guide.py
  guide_pdf.py project_map.py static_checks.py errors.py checks/ e2e_plugins/ docker/
  docker-compose.yml odoo.conf
hooks/{hooks.json, _common.py, session_start.py, pre_tool_guard.py, post_edit_check.py, stop_gate.py}
skills/{init, update, guide, add-harness-check}/   skills/odoo/ (SKILL.md + versions/<version>/)
agents/{odoo-explorer.md, odoo-reviewer.md}
scripts/{detect_project.py, install_template.py}
template/                        # the project files init writes (state, config, CLAUDE.md block)
versions.json                    # supported Odoo versions and their settings
tools/{odoo-skill-extract/, make_demo_project.py}
tests/                           # pytest, run once per Odoo version (HARNESS_TEST_ODOO_VERSION)
docs/, README.md, README.fr.md
```

## Phases (do less, but finish: each phase ends verified)
1. **Core harness**: the template (CLAUDE.md, BOOTSTRAP.md, PROGRESS.md, DECISIONS.md, feature_list.json), `init.sh`, docker-compose, and `/odoo-harness:init` with the 4 steps.
2. **State machine and verification**: `feature.py`, `verify.sh` (3 layers, pylint-odoo, Playwright), `errors.yaml` red-pen messages, the evidence store.
3. **Automatic hooks**: SessionStart, PreToolUse, PostToolUse and Stop.
4. **Odoo 20 skill**: the extractor and references, then adapted to the `19.0`, `18.0` and `17.0` branches.
5. **Review → check loop**: the `add-harness-check` skill, the reviewer subagent, and CI across the branches.
6. **Autonomous loops** (course lectures 13–14): `odoo-harness loop`, a maker-checker graph with bounded attempts and budgets.
7. **Full-project mode** (fogits projects): detection of the project layout, the project's own image and a separate test database, verify scope = changed modules + dependents, older findings as debt, Odoo tasks with `T<code>` branches and merge requests, discovery (`ARCHITECTURE.md`, open tasks through the Odoo MCP connector).
8. **Install once per machine**: one `odoo-harness` plugin for every Odoo version, the engine out of the repositories (the `odoo-harness` command), the version as data, CI per version, migration of the vendored projects.

## Verification of the harness project itself
- `pytest tests/`, once per supported Odoo version (`HARNESS_TEST_ODOO_VERSION`), covers:
  - the `odoo-harness` command (repository lookup, legacy refusal, version pin, link, PATH);
  - every hook, fed with sample hook JSON payloads;
  - the feature transitions (WIP = 1 refusal, `passing` only via verify);
  - the installer and the migration from the vendored harness;
  - the red-pen formatting.
- The CI `odoo-e2e` job, for each version:
  1. Builds a demo project (`tools/make_demo_project.py --odoo-version`).
  2. Runs `odoo-harness init`.
  3. Runs `odoo-harness feature start F-T0001-1` and `verify F-T0001-1`, which must reach `passing` with evidence.
  4. Injects a deliberate bug and asserts that verify fails with a red-pen message.
- The CI `skill-check` job checks each version's guide against that version's Odoo source.
