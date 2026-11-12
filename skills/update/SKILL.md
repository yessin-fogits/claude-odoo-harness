---
name: update
description: Bring this Odoo repository's harness files up to the installed odoo-harness plugin (CLAUDE.md block, settings, version pin), and migrate a project that still carries a copy of the old vendored harness engine (harness/feature.py), keeping the project's state and configuration.
disable-model-invocation: true
---

The harness engine is not in the repository: it is this plugin, installed once per machine
and updated by Claude Code (`claude plugin update odoo-harness@odoo-harness`). A plugin
update reaches every project at once. This skill only refreshes what the repository holds
(the CLAUDE.md block, `.claude/settings.json`, new settings in `harness/harness.env`), raises
the project's `HARNESS_VERSION` pin, and migrates projects installed before 2.0.

`REPO` below is the repository: `.` when Claude Code runs in it, `git` when it runs in the
client workspace (`~/Project/<client>`, with the repository in `git/`). In a workspace, add
`--workspace .` to the installer command and run git as `git -C git ...`.

## 1. Start from a clean tree

Run `git -C REPO status --porcelain`. If anything is uncommitted, ask the user to commit or
stash first, so the update is one reviewable commit.

## 2. Update

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_template.py" REPO --update [--workspace .]
```

Show the user the report. What each action means:
- `removed`: a file of the old vendored harness (`harness/feature.py`, `verify.py`, `init.sh`,
  the harness checks, the docker files...). The plugin's `odoo-harness` command runs the
  engine now. Project checks the team wrote in `harness/checks/` are kept. In a workspace, the
  CLAUDE.md block and settings the old harness generated there are removed as well (what the
  user wrote there is kept);
- `migrated`: `.pre-commit-config.yaml` entries that ran the vendored scripts now run
  `odoo-harness`;
- `merged`: the CLAUDE.md harness block, `.claude/settings.json` (the old
  `odoo-harness-<N>@odoo-harness` plugin and its `harness/...` rules are removed, the
  `odoo-harness` rules added), `.gitignore`, new settings appended to `harness/harness.env`,
  `HARNESS_VERSION` raised to the installed engine, or `ODOO_IMAGE` moved from the image the
  harness built to the dev stack's image (then offer the user `docker image rm <old image>`;
  never remove it yourself). The `# This project` section below the
  block is never changed; when CLAUDE.md had none, an empty one is added: fill its `TODO`
  lines as the init skill describes ("Project description");
- `kept`: unchanged, or project state (PROGRESS.md, DECISIONS.md, tasks/, BOOTSTRAP.md,
  ARCHITECTURE.md) which updates never touch;
- `migrated`: a project of an engine before 3.0. `feature_list.json` is split into one file per
  task, `tasks/<task>.json` (ids kept), the feature lines of PROGRESS.md move to each task's
  notes, `tasks/<task>.md`, and its "Current state" goes (it is in `.harness/` now). If the
  update stops because features have no task, show them to the user, ask which task each one
  belongs to, set `"task"` in `feature_list.json` (this one time, by hand), and run it again.
  Tell the user to commit it and merge it into the base branch **before anyone starts a task
  branch**: a branch from before the migration still has `feature_list.json` and conflicts
  with it;
- `kept*`: a project file (e2e/conftest.py, .pylintrc...) kept as is, although the template
  changed;
- `moved`: this machine's values (`ODOO_PORT`, the dev database mode `DEV_*`) left the versioned
  `harness/harness.env` for the git-ignored `harness/dev.local.env` of the user running the
  update (a value already set there is kept). Tell the user: once the update reaches the base
  branch, each teammate sets their own port and dev database mode in their own
  `harness/dev.local.env` (`odoo-harness init` creates it from the template when missing);
  until they do, their harness uses port 18069 and runs the e2e tests on the test DB.
- `renamed` / `link` / `duplicate`: a project document under another name or place
  (`Architecture.md`, `docs/decisions.md`...) was renamed to the harness name, a file still points
  to its old path, or a second copy sits next to the harness file. Fix the paths, then check and
  merge those documents as step 4b of the init skill describes.

`HARNESS_VERSION` is the oldest engine the project accepts: once this update is committed, a
teammate whose plugin is older is asked to update it before `odoo-harness` runs. Tell the user.

For each `kept*` file, show the difference:

```
diff REPO/<file> <(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_template.py" REPO --show <file>)
```

Propose to apply the template's changes that do not undo a project customization, and
apply only what the user accepts.

If the installer refuses because of the Odoo version, stop: moving to another Odoo version is
a migration, not an update (the `odoo` skill, `references/migrations.md` of the target
version).

After a migration from the vendored harness, also tell the user:
- each teammate installs the plugin once on their machine
  (`claude plugin install odoo-harness@odoo-harness`) and can uninstall the old one
  (`claude plugin uninstall odoo-harness-<N>@odoo-harness`);
- scripts or CI jobs that called `harness/<script>` now call `odoo-harness <command>`
  (`harness/feature.py` → `odoo-harness feature`, `harness/init.sh` → `odoo-harness init`,
  `harness/verify.sh` → `odoo-harness verify`, `harness/static_checks.py` → `odoo-harness static`,
  `harness/project_map.py` → `odoo-harness map`). Grep the repository for `harness/` to find
  them; deployment files are changed by a human.

## 3. Check

- `odoo-harness where`: the repository, the engine version and the pin.
- `odoo-harness static`: new checks may report existing code. List what they report; fix it
  as features or record it in PROGRESS.md "Known issues".
- `odoo-harness feature check`.
- `odoo-harness init --check` when Docker is available. After an engine update, a full
  `odoo-harness init` also removes the tool images older engines built for this project.

## 4. Record

Append to DECISIONS.md: `- YYYY-MM-DD: Updated the odoo-harness files (engine <version from
odoo-harness where>).` (after a migration: `Moved to the odoo-harness plugin installed once
per machine; removed the vendored engine.`) and commit: `chore: update odoo-harness files`.
