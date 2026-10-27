<!-- odoo-harness:start -->
# Odoo harness — Odoo {{ODOO_VERSION}}

This repository is driven by a harness. The repository is the system of record:
everything you need to continue is in these files, not in your memory.

| File | Role |
|---|---|
| `BOOTSTRAP.md` | Bootstrap contract: how to start, verify, reset; what is in and out of scope |
| `PROGRESS.md` | Current state, completed / in-progress tasks, known issues, next steps |
| `DECISIONS.md` | Dated decisions. Read before changing direction; append when you decide |
| `feature_list.json` | The work, split into features. State is owned by the harness |
| `harness/` | Scripts that run the environment and the verification |

Custom modules in scope: `{{MODULES}}` (in `{{ADDONS_DIR}}`).

# Sessions (automatic)
- At session start the harness loads PROGRESS.md, recent decisions, the current feature and the baseline health into your context. Start from there.
- After each edit of a module file, fast static checks run on that file. Fix what they report right away.
- When you end a turn, the harness rewrites "Current state" in PROGRESS.md and refuses to stop if the state is unclean: static check failures, a broken feature list, or code changed this session without PROGRESS.md being updated.
- Edits of feature_list.json, harness/evidence/, Odoo core/enterprise code and commands on non-test databases are denied.

# Work Rules
- Work on one feature at a time (WIP = 1).
- Only start the next feature after the current one passes e2e verification.
- Do less, but finish. A small feature that passes beats a large one that almost works.
- Stay inside the current feature. If you discover other work, add it as a new feature, do not do it now.
- Never edit Odoo core or enterprise code. Extend by inheritance in custom modules only.
- If the baseline is broken (`harness/init.sh` fails), fix the baseline before anything else.

# Feature List Rules
- `feature_list.json` is changed only through `harness/feature.py`. Never edit it by hand.
- Each feature has: `id`, `behavior`, `verification`, `state`, `evidence`.
- States: `not_started` → `in_progress` → `passing` (or `blocked`).
- You may: `add` a feature, `start` one (refused if another is `in_progress`), `block` one with a reason.
- You may NOT set `passing`. Only `harness/feature.py verify <id>` sets it, after all verification layers pass, and it records the evidence.

# Definition of Done
A feature is done only when ALL of these are true:
1. `harness/feature.py verify <id>` passed and set the state to `passing` with evidence.
2. Lint (pylint-odoo) is clean on the changed modules.
3. `PROGRESS.md` is updated (completed task, known issues, next steps).
4. Any decision taken is appended to `DECISIONS.md`.
5. The work is committed.

"It should work" or "the code looks right" is not done. Evidence is done.

# Validation Hierarchy
Completion is judged by the harness, in three layers:
1. Syntax and static analysis: Python compiles, XML is valid, manifest is consistent, pylint-odoo, project checks in `harness/checks/`.
2. Runtime behaviour: Odoo unit tests (level 1) and integration tests (level 2): module install/upgrade on a test DB, cross-model flows.
3. System confirmation: Playwright e2e tests (level 3) against a running instance. Every feature has its own e2e test. The full e2e suite must pass when a change touches more than one module or shared components.

Only the e2e test is real verification. Unit tests passing is not enough to declare a feature done.

# Error messages
Harness failures are printed as `✗ [layer] what`, `WHY:`, `HOW TO FIX:`. Read the HOW TO FIX line and apply it before trying anything else.

# When a review finds a new mistake type
Turn it into a check: add a file in `harness/checks/` that detects it with a WHY / HOW TO FIX message (copy the shape of `harness/checks/no_debug_leftovers.py`), then append a line to `DECISIONS.md`.
When a failure prints "No catalog entry", add its pattern to `harness/errors_project.py` once it is fixed.
<!-- odoo-harness:end -->
