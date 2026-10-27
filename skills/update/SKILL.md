---
name: update
description: Update the odoo-harness files of this Odoo repository to the version of the installed plugin (harness scripts, checks, red-pen catalog, CLAUDE.md block, settings), keeping the project's state and configuration.
disable-model-invocation: true
---

You are updating the harness files of this repository to the installed plugin version.
The plugin itself is updated by Claude Code (`claude plugin update`); this skill updates the
files the plugin once copied into the repository.

## 1. Start from a clean tree

Run `git status --porcelain`. If anything is uncommitted, ask the user to commit or stash
first, so the update is one reviewable commit.

## 2. Update

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_template.py" . --update
```

Show the user the report. What each action means:
- `updated`: a harness file replaced by the new version (`harness/*.py`, `*.sh`, checks,
  docker files, `harness/docker-compose.yml`, `harness/odoo.conf` rendered from
  `harness/harness.env`);
- `merged`: the CLAUDE.md harness block, `.claude/settings.json`, `.gitignore` or new
  settings appended to `harness/harness.env`;
- `kept`: unchanged, or project state (PROGRESS.md, DECISIONS.md, feature_list.json,
  BOOTSTRAP.md, ARCHITECTURE.md) which updates never touch;
- `kept*`: a project file (e2e/conftest.py, .pylintrc...) kept as is, although the template
  changed.

A harness installed before full-project mode (with `MODULES` and `ADDONS_DIR`) is migrated:
`CUSTOM_ADDONS` takes the old `ADDONS_DIR`, and the new settings (third-party addons,
enterprise, base branch, GitLab project) are appended to `harness/harness.env` with their
detected values. Check them with the user. Old root `docker-compose.yml` and `odoo.conf`
files written by the earlier harness are no longer used: propose to delete them if the
project does not use them itself.

For each `kept*` file, show the difference:

```
diff <file> <(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install_template.py" . --show <file>)
```

Propose to apply the template's changes that do not undo a project customization, and
apply only what the user accepts.

If the installer refuses because the project targets another Odoo version, stop: that is a
version migration (see the `odoo` skill, `references/migrations.md`), not an update.

## 3. Check

- `python3 harness/static_checks.py`: new checks may report existing code. List what they
  report; fix it as features or record it in PROGRESS.md "Known issues".
- `python3 harness/feature.py check`.
- `harness/init.sh --check` when Docker is available.

## 4. Record

Append to DECISIONS.md: `- YYYY-MM-DD: Updated the odoo-harness files (plugin <version from
claude plugin list>).` and commit: `chore: update odoo-harness files`.
