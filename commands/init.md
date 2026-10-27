---
description: Install the odoo-harness in this Odoo repository and run the 4 initialization steps
argument-hint: "[modules,comma,separated] [addons-dir]"
---

You are initializing the odoo-harness in the current repository. Work through the four steps
below in order. Do not skip a step, and do not start any feature work: initialization ends
when the bootstrap contract holds and the feature list is reviewed.

Arguments given: `$ARGUMENTS`

## Step 0: install the template
1. Find the custom addons directory and the custom modules in scope. Use the arguments if given.
   Otherwise look for directories containing `__manifest__.py`, and confirm with the user.
2. Run the installer from the plugin:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_template.py" . --modules <mods> --addons-dir <dir>
   ```
   If `CLAUDE_PLUGIN_ROOT` is empty, the plugin root is the directory two levels above this
   command file (`commands/init.md`).
3. Show the user the installer report (created / merged / kept). Files reported `kept` were
   not touched: point out any that may need a manual look.

## Step 1: executable environment
Run `harness/init.sh`. It must end with `✓ baseline OK`.
- On failure, read the `WHY:` and `HOW TO FIX:` lines and fix the cause, then run it again.
- If the only failure is that `harness/verify.sh` is missing, continue to step 2.

## Step 2: verifiable test frame
Every level of the validation hierarchy needs at least one test that passes:
- level 1 unit and level 2 integration: Odoo tests in each module's `tests/` package;
- level 3 e2e: a Playwright test in `e2e/`.
If a level has no test yet, write the smallest meaningful one (for example: the module
installs and its main menu opens). Then `harness/init.sh` must reach `✓ baseline OK`.

## Step 3: bootstrap contract
Open `BOOTSTRAP.md` and check every value against the reality you just observed (commands,
ports, modules, test DB). Fix what is wrong, tick the first two boxes of "Ready means",
and ask the user to review the contract. Tick box 3 only after the user approves it.

## Step 4: task breakdown
Ask the user for the requirements (spec, ticket, notes). Split them into small features,
each one observable by a user and checkable by an e2e test, with:
- `behavior`: one sentence, what a user can do or see;
- `verification`: the unit/integration test and the e2e test that prove it.
Present the list to the user. After approval, add each feature with `harness/feature.py add`
(never by editing `feature_list.json`). Tick box 4 in `BOOTSTRAP.md`.

## Finish
- Append the initialization decisions to `DECISIONS.md` (one dated line each).
- Update `PROGRESS.md`: "Next steps" lists the first feature to start.
- Commit: `chore: install odoo-harness`.
