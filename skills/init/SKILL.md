---
name: init
description: Install the odoo-harness in this Odoo project (new or already developed), discover the project (ARCHITECTURE.md, CLAUDE.md, open Odoo tasks) and run the 4 initialization steps (executable environment, verifiable test frame, bootstrap contract, task breakdown).
argument-hint: "[--custom-addons dir,...] [--enterprise-dir path] [--base-branch name]"
disable-model-invocation: true
---

You are initializing the odoo-harness in an Odoo project: a whole Odoo project, new or
already developed. Claude Code runs either in the client workspace (fogits layout:
`~/Project/<client>`, with the repository in `git/` and Odoo Enterprise in `enterprise/`) or in
the git repository itself. The harness is always installed in the repository, so it is
versioned with the project.

Work through the steps in order. Do not skip a step and do not start any feature work:
initialization ends when the bootstrap contract holds and the feature list is reviewed.

Arguments given: `$ARGUMENTS`

## Step 0: detect the project and install the harness
0. Find the repository (`REPO` below):
   - the current folder is the root of a git repository (`git rev-parse --show-toplevel`
     prints it): `REPO` is `.`, there is no workspace;
   - otherwise `git/` is the root of a git repository (fogits workspace): `REPO` is `git`
     and the workspace is `.`;
   - otherwise ask the user which folder holds the Odoo repository.
   `odoo-harness` finds `REPO` from the workspace by itself; run git as `git -C git ...`.
   The paths the harness prints are relative to `REPO`.
   If `REPO/harness/feature.py` exists, the project has the old vendored harness: stop and
   run the `update` skill instead (it migrates the project).
1. Detect the layout:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_project.py" REPO
   ```
   It reads `addons_path` from the project's Odoo config, the Odoo version and image from the
   Dockerfile, the base branch, the GitLab project and the deployment files.
2. Show the summary to the user and ask them to confirm, in one question:
   - custom addon folders (the project's code);
   - third-party addon folders (OCA and vendors);
   - the Odoo Enterprise checkout (default `../enterprise`) and the base branch (`staging`).
   - the Odoo version (from the Dockerfile; ask when it was not detected).
   Fix anything wrong with the installer options below. If the project runs an Odoo version
   the harness does not support (`versions.json`), stop and tell the user.
3. Install:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_template.py" REPO [--odoo-version 18.0] \
     [--custom-addons a,b] [--third-party-addons x] [--enterprise-dir ../enterprise] \
     [--dockerfile Dockerfile] [--base-branch staging]
   ```
   It writes the project's state and configuration only (no copy of the engine: the
   `odoo-harness` command of this plugin runs it). Nothing is written in the workspace.
   Show the report (created / merged / kept / renamed / duplicate). Files reported `kept` were
   not touched. `renamed`: a document the project already had under another name or place
   (`Architecture.md`, `docs/decisions.md`, `claude.md`...) now has the harness name, with its
   content unchanged; a `link` line names a file that still points to its old path: fix that
   path now. `duplicate`: the project has another copy of a harness document; discovery
   merges it. Tell the user which of their documents were moved or found.
   Then check the command works: `odoo-harness where` (it prints the repository, the engine
   and the Odoo version). If `odoo-harness` is not found, use
   `"${CLAUDE_PLUGIN_ROOT}/bin/odoo-harness"` for this session and tell the user that a new
   session puts it on the PATH.
3b. **Once per machine**, if `~/.claude/settings.json` does not allow it yet: ask the user
   whether to allow the `odoo-harness` command in their user settings, so sessions started in
   any client workspace do not ask for permission at each harness command. Only on a yes:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_template.py" --allow-command
   ```
4. Decide which path applies: **existing project** when the custom folders already hold
   modules or the git history has feature work, otherwise **new project**. Tell the user.

## Discovery (existing project only)
The goal: the next session, human or agent, understands the project from the repository alone.

1. **Facts.** Run `odoo-harness map` (modules, models defined and extended,
   dependencies between custom modules, tests) and `odoo-harness static --all`
   (debt over the whole project). Do not fix anything now.
2. **Reading.** For each custom module, read its manifest, models and main views, and write
   one plain sentence: what it does for the user. With many modules, use the `odoo-explorer`
   agent on groups of modules. Note the conventions you see: module name prefix, manifest
   author and version scheme, lint and formatting tools, translation languages, commit
   messages (`git log --oneline -30`), branch names (`git branch -r`).
3. **ARCHITECTURE.md.** Fill every section of `ARCHITECTURE.md`: the project, runtime and
   deployment (Dockerfile, compose files, configs, CI, git flow), one line per module, then the
   facts from `odoo-harness map`, the dependency graph and what to watch, and the risks
   and debt. Debt includes modules without tests, findings of `--all` (group them; list
   hard-coded secrets first, without their values), version problems, and unfinished
   branches. Facts come from the tools and the code, never from memory. List the **shared
   submodules** too (`.gitmodules`: the path, its GitLab project, its `branch`): other
   projects include them, so a change there reaches them all. Their knowledge files
   (`CLAUDE.md`, `DECISIONS.md`, `ARCHITECTURE.md` inside the submodule) belong to the shared
   project, never to this repository. When their branch lacks them, offer to add them now
   with `odoo-harness gitlab shared <task>`, using the install's task code. Ask first: it opens
   one merge request in each shared project. The first run writes the files in
   `.harness/shared/<path>/`, a checkout of the submodule's branch tip. Fill each
   `ARCHITECTURE.md` there from the code beside it: one line per module, the dependencies,
   this project under "Projects using it". Use the `odoo-explorer` agent when there are many
   modules. Then run the command again: it pushes the branch `<task>` and opens the merge
   requests. If the user declines, the first task that changes a submodule adds them
   (`odoo-harness feature verify` says how). A submodule that is not checked out is a
   `git submodule update --init <path>` before `odoo-harness init`.
   If the project already had an ARCHITECTURE.md (reported `kept` or `renamed` at install),
   do not start from the empty template: check each of its claims against the facts and the
   code, correct the false ones, keep the true ones in the author's words, and add the
   sections it lacks. Merge a `duplicate` copy the same way.
4. **CLAUDE.md.** Fill the `# This project` section from what you read (see "Project
   description" below): the key modules, the conventions you saw, the risky modules (many
   dependents, no tests). Keep it short: details belong in ARCHITECTURE.md. Text the project
   had in CLAUDE.md before the harness block is checked the same way: correct what the code
   contradicts (a module that no longer exists, a wrong version, a renamed folder).
4b. **The other documents the project had.** For DECISIONS.md, PROGRESS.md and BOOTSTRAP.md
   reported `kept`, `renamed` or `duplicate`:
   - DECISIONS.md is a history: never rewrite a past decision, even one that is no longer
     true; append a dated line that supersedes it. Write each past entry that is not a
     `- YYYY-MM-DD: ...` line as one (its date from the entry, or from `git log` of the file),
     since sessions only load those lines.
   - PROGRESS.md and BOOTSTRAP.md describe the present: correct what is false, keep the rest
     under the harness headings.
   Before writing, show the user each correction (what the document said, what the code
   shows). After merging a `duplicate`, remove it with `git rm` only when the user agrees.
5. **Open tasks from Odoo.** Use the Odoo MCP connector of this client (its tools are named
   `mcp__Odoo_<client>__*`; pick the one matching the project).
   - Find the `project.project` that matches the repository (the GitLab project name, the
     client name). Confirm it with the user if more than one could match.
   - List its open tasks: stages not folded or closed, not done or cancelled. Read the code
     (`T2003`), name, stage, assignee, deadline and description of each.
   - Match the codes with the branch names (`git branch -r`): a task with a branch has work
     started.
   - Show the list to the user. For each task they want in the harness, propose features
     (step 4 below). Nothing is written to Odoo: the harness only reads tasks.
   - If no Odoo connector is available, say so and ask the user to paste the open tasks (code,
     title, description).
6. **Debt decisions.** Present the risks and debt. For each item the user wants fixed, propose
   a feature (with its task code if there is one). Record the others under "Known issues" in
   `PROGRESS.md`. Hard-coded secrets are always reported to the user: they must be revoked
   by a human.

## Project description (both paths)
The installer puts a `# This project` section below the harness block of `CLAUDE.md` (it adds
one when the file has none, and never changes it afterwards). Every session loads it, so it is
how the agent knows which client and which business it works for. Replace every `TODO` line:
- **Client and business**: the client (company, sector, country, who uses Odoo) and what the
  project does for them in two lines, with the main business flows. Take it from the
  description of the matching `project.project` in Odoo when the connector is available, and
  from the user; never invent it. Ask the user, in one question, for what you cannot find.
- **Odoo**: Community or Enterprise, localization and languages (from the config and the
  manifests), the Odoo apps in use (the `depends` of the custom modules), the key custom
  modules and where a new module goes.
- **Conventions** and **Risky to change**: from discovery for an existing project. For a new
  project, write the conventions the user wants and leave "Risky to change" as `none yet`.
If the file had a project description under another heading, merge it into this section
instead of keeping two. Show the section to the user; initialization does not finish while a
`TODO` line is left in it.

## Step 1: executable environment
Run `odoo-harness init`. It builds the project image, or with the fogits dev stack uses the
dev stack's image and Odoo source as they are, starts the harness stack (its own
database and port, never the dev stack), installs every custom module on a fresh test
database with demo data, then runs the baseline verification. It must end with
`✓ baseline OK`.
- When the dev stack's image is missing, init prints the `docker build` command: give it to
  the user, never run it yourself. Do not pass `--dockerfile` to the installer when it
  detected a dev stack image: it would build the production Dockerfile instead.
- On failure, read the `WHY:` and `HOW TO FIX:` lines and fix the cause, then run it again.
- A custom module that does not install on a fresh database is a finding: tell the user. Fix
  it only if they agree (it becomes the first feature); never weaken the harness to pass.
- Problems in deployment files (Dockerfile, configs) are fixed by a human: explain what and why.

Dev DB mode (optional): ask the user, in one question, whether the e2e tests should run on
their dev database (a copy of the client's data from production or staging) instead of the
test DB. If yes, fill `DEV_DB`, `DEV_DB_HOST`, `DEV_DB_PORT`, `DEV_DB_USER`, `DEV_NETWORK` and
`DEV_DATA_DIR` in `harness/dev.local.env` (read them from the dev compose file and
`docker network ls`; the comments there explain each one), and ask the user to write
`DEV_DB_PASSWORD`, `DEV_ODOO_LOGIN` and `DEV_ODOO_PASSWORD` there (never write a password
yourself). That file is this developer's, git-ignored: their port (`ODOO_PORT`), dev stack and
dev database are never written in `harness/harness.env`, which every teammate shares. The dev DB must be neutralized: if `init`
reports it is not, the user runs `odoo-bin neutralize` in the dev stack. Never neutralize,
restore or drop the dev DB yourself.

## Step 2: verifiable test frame
Every level of the validation hierarchy needs at least one test that passes in the project:
- level 1 unit and level 2 integration: Odoo tests in a module's `tests/` package;
- level 3 e2e: a Playwright test in `e2e/` (`e2e/test_smoke.py` is installed).
If a level has no test yet, write the smallest meaningful one in the most central custom module
(for example: its main model can be created, its main menu opens). Existing modules without
tests are debt, not a blocker. Then `odoo-harness init` must reach `✓ baseline OK`.

## Step 3: bootstrap contract
Open `BOOTSTRAP.md` and check every value against what you observed (image, addon folders,
enterprise, base branch, GitLab project, protected paths, commands, test DB). Fix what is
wrong, tick the first two boxes of "Ready means", and ask the user to review the contract.
`BOOTSTRAP.md` is committed and shared by the team: write only the project's values, the ones
of `harness/harness.env`. Never write this developer's own values in it (their port, a local
Enterprise checkout, their dev stack or dev database): they belong in `harness/dev.local.env`,
and the port line stays `<ODOO_PORT>`.
Tick box 3 only after the user approves it.

## Step 4: task breakdown
Work comes from Odoo tasks (from discovery for an existing project; for a new project, ask the
user for the tasks or the requirements). Split each task into small features, each one
observable by a user and checkable by an e2e test, with:
- `task`: the Odoo task code (`T2003`), the same for all features of the task; if the task does
  not exist in Odoo yet, any short name (`remise-devis`), renamed later with
  `odoo-harness feature rename-task remise-devis T2003`;
- `behavior`: one sentence, what a user can do or see;
- `verification`: the unit/integration test and the e2e test that prove it.
Present the list to the user, grouped by task. After approval, add each feature with
`odoo-harness feature add --task <task> --no-branch ...` (never by editing `tasks/*.json`):
`--no-branch` writes each task's file on the install branch, so it reaches the base branch
with the install. Feature ids are numbered per task (`F-T2003-1`); name each e2e test after
its id (`e2e/test_T2003_1_<name>.py`). Tick box 4 in `BOOTSTRAP.md`.

**Several developers on the project** (ask the user, or see the GitLab members): do not add
the features of every open task here. Each developer adds a task's features when taking it,
with `odoo-harness feature add --task <task> ...` on the task's branch, so a task is only ever
in progress on one branch. Add here only the tasks the user is about to work on, and tick box
4 with that noted.

## Finish
- Append the initialization decisions to `DECISIONS.md` (one dated line each): the layout
  confirmed, the debt left as known issues, anything the user decided.
- Check that the `# This project` section of `CLAUDE.md` has no `TODO` line left.
- Update `PROGRESS.md`: "Next steps" lists the first task and its first feature. Task work is
  then recorded in each task's notes, `tasks/<task>.md`.
- Commit on the current branch: `chore: install odoo-harness`. Tell the user that the harness
  install must reach the base branch (`staging`) through a merge request before task branches
  are shared, since task branches start from it.
- Remind the user: opening merge requests needs `GITLAB_TOKEN` (api scope) in the environment
  or in the git-ignored `.env`; never commit it.
