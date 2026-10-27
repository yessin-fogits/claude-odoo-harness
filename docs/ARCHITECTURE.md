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

## Decisions
- **Distribution**: a Claude Code plugin (hooks, skills, subagents, one `/odoo-harness:init` command) plus a template that `init` copies into the Odoo repo. Per-project state lives in the repo, which is the system of record.
- **Versions**: one branch per Odoo version: `17.0`, `18.0`, `19.0` and `20.0`.
  - Harness mechanics are identical on every branch. Changes land on `17.0` and are forward-ported.
  - A CI check fails if the shared files differ between branches.
  - Only the Odoo skill, the docker image tag and version-specific flags differ.
  - `main` holds the README, the docs and the marketplace manifest.
- **Runtime**: Docker Compose with these services:
  - `odoo`, using the image tag of the branch version.
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
feature_list.json    # minimal format, state changed only by the harness
harness/
  init.sh            # executable environment: compose up, create test DB, install modules, baseline verify
  verify.sh          # runs the 3 validation layers; called by feature.py
  feature.py         # state machine CLI: add | start | block | verify | status
  checks/            # project checks born from code reviews (one file per mistake type)
  errors.yaml        # red-pen catalog: error pattern → why + how to fix
  evidence/          # per-feature evidence summaries (JSON committed; traces gitignored)
e2e/                 # Playwright (pytest-playwright) tests, one file per feature: test_<feature_id>_*.py
docker-compose.yml, odoo.conf, .pylintrc (pylint-odoo), .pre-commit-config.yaml
.claude/settings.json  # permissions and the plugin enabled
```

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
1. **Executable environment**: `docker-compose.yml` and `harness/init.sh`. Odoo starts, the test DB is created and the custom modules install cleanly.
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
  - Change state only through `harness/feature.py`.
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
  - It also denies `Bash` commands that write to that file other than `harness/feature.py`.
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
HOW TO FIX: add @api.depends('order_line.price_unit') on _compute_discount_rate; re-run harness/feature.py verify F-001
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

## Plugin repo layout
```
.claude-plugin/{plugin.json, marketplace.json}
commands/init.md                 # the only command: 4-step initialization
hooks/{hooks.json, session_start.py, pre_tool_guard.py, post_edit_check.py, stop_gate.py}
skills/odoo/ (SKILL.md + references/)   skills/add-harness-check/   skills/feature-breakdown/
agents/{odoo-explorer.md, odoo-reviewer.md}   # reviewer looks for new mistake types and proposes checks
template/                        # files copied into the target repo (see the tree above)
tools/odoo-skill-extract/
examples/demo-odoo-project/      # CI fixture
tests/                           # pytest for hooks, feature.py, verify parsing, red-pen catalog
docs/en/, docs/fr/, README.md, README.fr.md
```

## Phases (do less, but finish: each phase ends verified)
1. **Core harness**: the template (CLAUDE.md, BOOTSTRAP.md, PROGRESS.md, DECISIONS.md, feature_list.json), `init.sh`, docker-compose, and `/odoo-harness:init` with the 4 steps.
2. **State machine and verification**: `feature.py`, `verify.sh` (3 layers, pylint-odoo, Playwright), `errors.yaml` red-pen messages, the evidence store.
3. **Automatic hooks**: SessionStart, PreToolUse, PostToolUse and Stop.
4. **Odoo 20 skill**: the extractor and references, then adapted to the `19.0`, `18.0` and `17.0` branches.
5. **Review → check loop**: the `add-harness-check` skill, the reviewer subagent, and CI across the branches.
6. **Autonomous loops** (course lectures 13–14): `harness/loop.py`, a maker-checker graph with bounded attempts and budgets.
7. **Full-project mode** (fogits projects): detection of the project layout, the project's own image and a separate test database, verify scope = changed modules + dependents, older findings as debt, Odoo tasks with `T<code>` branches and merge requests, discovery (`ARCHITECTURE.md`, open tasks through the Odoo MCP connector).

## Verification of the harness project itself
- `pytest tests/` covers:
  - every hook, fed with sample hook JSON payloads;
  - the `feature.py` transitions (WIP = 1 refusal, `passing` only via verify);
  - the red-pen formatting.
- The CI job on each branch:
  1. Runs `init` on `examples/demo-odoo-project`, then `docker compose up`.
  2. Runs `harness/init.sh`.
  3. Runs `feature.py start F-001` and `verify F-001`, which must reach `passing` with evidence.
  4. Injects a deliberate bug and asserts that verify fails with a red-pen message.
  5. Asserts that a direct edit of `feature_list.json` is denied by the hook.
- Cross-branch CI: the shared harness files are identical on all version branches.
