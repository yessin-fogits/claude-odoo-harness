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
   With a workspace, every command below runs from the workspace with `REPO` as the path
   (`git/harness/init.sh`, `python3 git/harness/project_map.py`, `git -C git log`), and the
   paths the harness prints are relative to `REPO`.
1. Detect the layout:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_project.py" REPO
   ```
   It reads `addons_path` from the project's Odoo config, the Odoo version and image from the
   Dockerfile, the base branch, the GitLab project and the deployment files.
2. Show the summary to the user and ask them to confirm, in one question:
   - custom addon folders (the project's code, the only code you will change);
   - third-party addon folders (OCA and vendors, read-only);
   - the Odoo Enterprise checkout (default `../enterprise`) and the base branch (`staging`).
   Fix anything wrong with the installer options below. If the project runs another Odoo
   version than this plugin, stop and tell the user which plugin to install
   (`odoo-harness-<major>@odoo-harness`).
3. Install:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_template.py" REPO [--workspace .] \
     [--custom-addons a,b] [--third-party-addons x] [--enterprise-dir ../enterprise] \
     [--dockerfile Dockerfile] [--base-branch staging]
   ```
   Pass `--workspace .` when Claude Code runs in the workspace: it writes the workspace's
   `CLAUDE.md` (it imports `REPO/CLAUDE.md`) and `.claude/settings.json` (the same
   permissions and the plugin enabled). They are not versioned; each developer gets them
   from this skill or from `update`.
   Show the report (created / merged / kept). Files reported `kept` were not touched.
4. Decide which path applies: **existing project** when the custom folders already hold
   modules or the git history has feature work, otherwise **new project**. Tell the user.

## Discovery (existing project only)
The goal: the next session, human or agent, understands the project from the repository alone.

1. **Facts.** Run `python3 harness/project_map.py` (modules, models defined and extended,
   dependencies between custom modules, tests) and `python3 harness/static_checks.py --all`
   (debt over the whole project). Do not fix anything now.
2. **Reading.** For each custom module, read its manifest, models and main views, and write
   one plain sentence: what it does for the user. With many modules, use the `odoo-explorer`
   agent on groups of modules. Note the conventions you see: module name prefix, manifest
   author and version scheme, lint and formatting tools, translation languages, commit
   messages (`git log --oneline -30`), branch names (`git branch -r`).
3. **ARCHITECTURE.md.** Fill every section of `ARCHITECTURE.md`: the project, runtime and
   deployment (Dockerfile, compose files, configs, CI, git flow), one line per module, then the
   facts from `harness/project_map.py`, the dependency graph and what to watch, and the risks
   and debt. Debt includes modules without tests, findings of `--all` (group them; list
   hard-coded secrets first, without their values), version problems, and unfinished
   branches. Facts come from the tools and the code, never from memory.
4. **CLAUDE.md.** Fill the `# This project` section from what you read (see "Project
   description" below): the key modules, the conventions you saw, the risky modules (many
   dependents, no tests). Keep it short: details belong in ARCHITECTURE.md.
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
Run `harness/init.sh`. It builds the project image, starts the harness stack (its own
database and port, never the dev stack), installs every custom module on a fresh test
database with demo data, then runs the baseline verification. It must end with
`✓ baseline OK`.
- On failure, read the `WHY:` and `HOW TO FIX:` lines and fix the cause, then run it again.
- A custom module that does not install on a fresh database is a finding: tell the user. Fix
  it only if they agree (it becomes the first feature); never weaken the harness to pass.
- Problems in deployment files (Dockerfile, configs) are fixed by a human: explain what and why.

## Step 2: verifiable test frame
Every level of the validation hierarchy needs at least one test that passes in the project:
- level 1 unit and level 2 integration: Odoo tests in a module's `tests/` package;
- level 3 e2e: a Playwright test in `e2e/` (`e2e/test_smoke.py` is installed).
If a level has no test yet, write the smallest meaningful one in the most central custom module
(for example: its main model can be created, its main menu opens). Existing modules without
tests are debt, not a blocker. Then `harness/init.sh` must reach `✓ baseline OK`.

## Step 3: bootstrap contract
Open `BOOTSTRAP.md` and check every value against what you observed (image, addon folders,
enterprise, base branch, GitLab project, protected paths, commands, port, test DB). Fix what is
wrong, tick the first two boxes of "Ready means", and ask the user to review the contract.
Tick box 3 only after the user approves it.

## Step 4: task breakdown
Work comes from Odoo tasks (from discovery for an existing project; for a new project, ask the
user for the tasks or the requirements). Split each task into small features, each one
observable by a user and checkable by an e2e test, with:
- `task`: the Odoo task code (`T2003`), the same for all features of the task;
- `behavior`: one sentence, what a user can do or see;
- `verification`: the unit/integration test and the e2e test that prove it.
Present the list to the user, grouped by task. After approval, add each feature with
`harness/feature.py add --task <code> ...` (never by editing `feature_list.json`). Tick box 4
in `BOOTSTRAP.md`.

## Finish
- Append the initialization decisions to `DECISIONS.md` (one dated line each): the layout
  confirmed, the debt left as known issues, anything the user decided.
- Check that the `# This project` section of `CLAUDE.md` has no `TODO` line left.
- Update `PROGRESS.md`: "Next steps" lists the first task and its first feature.
- Commit on the current branch: `chore: install odoo-harness`. Tell the user that the harness
  install must reach the base branch (`staging`) through a merge request before task branches
  are shared, since task branches start from it.
- Remind the user: opening merge requests needs `GITLAB_TOKEN` (api scope) in the environment
  or in the git-ignored `.env`; never commit it.
