# Plan: `claude-odoo-harness`, a Claude Code harness for Odoo projects

## Context
We are building a GitHub project that gives any Odoo project a ready-made Claude Code harness. It follows the *Learn Harness Engineering* course (walkinglabs) and the user's notes.

The course's core idea is that reliability comes from the system around the model, not from the model itself. That system has five parts: instructions, tools, environment, state and feedback.

The user's notes add these requirements:
- Context lives in `PROGRESS.md` and `DECISIONS.md`.
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
repository: the feature list, the evidence and PROGRESS.md are the team's shared record.

| Where | What | Updated by |
|---|---|---|
| The plugin (`claude plugin install odoo-harness@odoo-harness`, user scope) | hooks, skills, agents, the engine (`engine/`: feature, verify, init, loop, gitlab, guide, static checks, generic checks, red-pen catalog, Docker files) and the `odoo-harness` command (`bin/`) | the plugin update, for every project at once |
| The repository | state (`PROGRESS.md`, `DECISIONS.md`, `feature_list.json`, `BOOTSTRAP.md`, `ARCHITECTURE.md`, `harness/evidence/`), project config (`harness/harness.env`, `harness/errors_project.py`, project checks in `harness/checks/`, `e2e/`, `.pylintrc`), the `CLAUDE.md` block and `.claude/settings.json` | the project |
| `~/.odoo-harness/` | `current`, a symlink to the installed plugin, refreshed at each session start; the `odoo-harness` shim in `~/.local/bin` points through it | the session start hook |

- **One command.** `odoo-harness <init|verify|feature|loop|gitlab|guide|map|static>` replaces
  `harness/<script>`. It finds the repository from the current folder (the repository itself,
  or `git/` in a client workspace) and runs the engine on it. Claude's Bash tool gets the
  plugin's `bin/` on its PATH from the session start hook (`CLAUDE_ENV_FILE`); humans use the
  shim; the command puts its own `bin/` first on the PATH of every child process, so
  `loop.py`'s headless sessions reach the same engine.
- **Docker.** The compose file is the engine's. Its build contexts and the engine mount
  (`/opt/odoo-harness`, read-only, in the lint and e2e containers) come from `HARNESS_HOME`,
  which every compose call exports through one function. `odoo.conf` is rendered from
  `harness/harness.env` into `.harness/odoo.conf` before each compose call.
- **Engine version.** `engine/VERSION`, not `plugin.json` (a `version` there would change how
  Claude Code detects updates). `harness/harness.env` pins a minimum, `HARNESS_VERSION`:
  the engine refuses to run on a project pinned to a newer engine, so a teammate with an old
  plugin cannot verify. It is a minimum, not an exact match, so auto-updates never block
  anyone. Every evidence file records the engine version that produced it. `engine/VERSION`
  is bumped with every change that can alter a verdict or a command; otherwise two different
  engines would carry the same number and the pin could not tell them apart.
- **Activation by marker.** The hooks run in every session, so each one first checks for
  `harness/harness.env` and `feature_list.json` in the launch folder or `git/`, and exits
  otherwise. In an Odoo repository without the harness (`__manifest__.py` one level down in
  the folder or `git/`, never a recursive scan), the session start hook offers `init` once.
- **Client workspace.** Started in `~/Project/<client>`, the hooks find `git/` and inject the
  repository's `CLAUDE.md`: nothing is generated in the workspace.
- **Permissions.** A user-scope plugin cannot ship permission rules. `init` asks the user
  once per machine whether to add `Bash(odoo-harness:*)` to `~/.claude/settings.json`; the
  repository's `.claude/settings.json` keeps its deny rules and enables the plugin for
  teammates.
- **The engine is protected.** Edits under the plugin folder and `~/.odoo-harness/` are denied
  like `feature_list.json`: the judge cannot be rewritten by the agent it judges.
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
- **Versions**: one plugin for every Odoo version (17.0 to 20.0); the version is data.
  - `versions.json` lists the supported versions and their PostgreSQL image.
  - The project's version is `ODOO_VERSION` in `harness/harness.env`, detected by `init`.
  - The `odoo` skill holds one guide per version: `skills/odoo/versions/<version>/`.
  - CI runs the tests, the skill check and the e2e demo for each version (a matrix).
  - The old `17.0`...`20.0` branches are frozen: they serve the deprecated
    `odoo-harness-<N>` plugins until every project is migrated.
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
PROGRESS.md          # Current state | Completed | In progress | Known issues | Next steps
DECISIONS.md         # "YYYY-MM-DD: decision (why)", append-only
ARCHITECTURE.md      # map of the project: modules, dependencies, risks and debt
feature_list.json    # minimal format, state changed only by `odoo-harness feature`
harness/
  harness.env        # the project's harness settings, HARNESS_VERSION (engine pin)
  checks/            # project checks born from code reviews (one file per mistake type)
  errors_project.py  # the project's red pens
  evidence/          # per-feature evidence (JSON committed; traces gitignored)
e2e/                 # Playwright (pytest-playwright) tests, one file per feature: test_<feature_id>_*.py
.pylintrc (pylint-odoo), .pre-commit-config.yaml
.claude/settings.json  # deny rules, the odoo-harness command allowed, the plugin enabled
.harness/            # not versioned: odoo.conf rendered from harness.env, logs, session state
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
- **PROGRESS.md** has five sections:
  - `## Current state`: last commit, test status and lint status. The Stop hook rewrites this section automatically.
  - `## Completed tasks`: `- [x] F-001 …`
  - `## In progress`: `- [ ] F-010 …`
  - `## Known issues`
  - `## Next steps`
- **DECISIONS.md**: one line per decision, `- 2026-10-27: Use Playwright for e2e (Odoo tours too coupled to JS assets)`.
- **feature_list.json** uses the minimal fields `id`, `behavior`, `verification`, `state` and `evidence`:
  ```json
  {"features": [{"id": "F-001",
    "behavior": "Salesperson applies a 10% discount on a quotation line",
    "verification": ["unit: sale_discount.tests.test_discount", "e2e: e2e/test_F001_discount.py"],
    "state": "not_started", "evidence": null}]}
  ```
  `state` is one of `not_started`, `in_progress`, `blocked` or `passing`.

## Initialization (4 steps, done by `/odoo-harness:init` and re-checked each session)
1. **Executable environment**: `odoo-harness init` (the engine's compose stack). Odoo starts, the test DB is created and the custom modules install cleanly.
2. **Verifiable test frame**: `verify.sh` runs pylint-odoo, the `odoo-bin --test-enable` unit and integration tests, and the Playwright e2e tests. A sample passing test exists at each level.
3. **Bootstrap contract**: `BOOTSTRAP.md` defines what "ready" means:
   - the start, verify and reset commands;
   - the expected baseline output;
   - the modules in scope and the paths that are off-limits (core and enterprise).
   - `init` refuses to finish until the contract holds.
4. **Task breakdown**: the requirements are turned into small features in `feature_list.json`, each with a behavior and verification steps. The user reviews them before work starts.

## CLAUDE.md content (short; details live in skills)
- `# Work Rules`
  - Work on one feature at a time (WIP = 1).
  - Start the next feature only after the current one passes e2e verification.
  - Do less, but finish.
  - Never edit Odoo core or enterprise code.
- `# Feature List Rules`
  - Change state only through `odoo-harness feature`.
  - Never edit `feature_list.json` by hand.
  - Never mark a feature `passing` yourself. Only `feature.py verify` can do it.
  - New work goes into the list through `feature.py add`.
- `# Definition of Done`
  - The feature's verification steps all pass through `feature.py verify`.
  - The evidence is recorded.
  - Lint is clean.
  - PROGRESS.md is updated.
  - The work is committed.
- `# Validation Hierarchy`
  - Level 1: unit tests.
  - Level 2: integration tests (module install and upgrade, cross-model flows).
  - Level 3: e2e (Playwright). Every feature needs its own e2e test. The full e2e suite is required when the change touches more than one module or shared components.
- `# When a review finds a new mistake type`: add a check in `harness/checks/` and log it in DECISIONS.md.

## Harness-controlled state transitions
- `feature.py start ID` is refused if another feature is `in_progress` (WIP = 1).
- `feature.py block ID --reason` sets `blocked`.
- `feature.py verify ID` is the only way to reach `passing`:
  - It runs the 3 layers.
  - It writes evidence: commit SHA, a log summary, and the paths to Playwright traces and screenshots.
  - It updates PROGRESS.md (Completed / In progress).
- A `passing` feature goes back to `in_progress` if a later verify shows a regression.
- Enforcement:
  - The PreToolUse hook denies `Edit` and `Write` on `feature_list.json`.
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
HOW TO FIX: add @api.depends('order_line.price_unit') on _compute_discount_rate; re-run odoo-harness feature verify F-001
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
  - Injects into the context: the PROGRESS.md "Current state" and "Next steps" sections, the last 10 DECISIONS, and the `in_progress` feature with its verification steps.
  - If the baseline is broken, it tells the agent to fix it first.
- **PreToolUse**:
  - Protects `feature_list.json`.
  - Blocks edits to Odoo core and enterprise paths.
  - Blocks `dropdb` on non-test DBs and production configs.
- **PostToolUse** (on Edit and Write of `.py` and `.xml` files): runs fast layer 1 checks on the changed file and returns red-pen feedback.
- **Stop** (the automatic session end):
  - Rewrites the PROGRESS.md "Current state" section (last commit, test and lint status).
  - Blocks stopping, with red-pen instructions, if any of these is true:
    - there are uncommitted changes that PROGRESS.md does not mention;
    - lint fails;
    - the `in_progress` feature has no notes in PROGRESS;
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
  3. Runs `odoo-harness feature start F-001` and `verify F-001`, which must reach `passing` with evidence.
  4. Injects a deliberate bug and asserts that verify fails with a red-pen message.
- The CI `skill-check` job checks each version's guide against that version's Odoo source.
