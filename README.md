# claude-odoo-harness

A [Claude Code](https://claude.com/claude-code) harness for Odoo projects, based on
[Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/fr/).

> 🇫🇷 [Version française](README.fr.md)

A harness is the work system around the model. It makes Claude reliable on long Odoo
projects: the state lives in the repository, one feature is done at a time, and only the
harness can declare a feature done, after real verification.

## Install

One plugin per Odoo version, all from this marketplace:

| Odoo | Plugin | Branch |
|---|---|---|
| 17.0 | `odoo-harness-17` | [`17.0`](../../tree/17.0) |
| 18.0 | `odoo-harness-18` | [`18.0`](../../tree/18.0) |
| 19.0 | `odoo-harness-19` | [`19.0`](../../tree/19.0) |
| 20.0 | `odoo-harness-20` | [`20.0`](../../tree/20.0) |

```
/plugin marketplace add yessin-fogits/claude-odoo-harness@main
/plugin install odoo-harness-20@odoo-harness
```

Then, in your Odoo repository, run `/odoo-harness-20:init` (with the number of your
version). It installs the harness files and walks through the 4 initialization steps:

1. **Executable environment**: Docker Compose (Odoo, PostgreSQL), a disposable test DB,
   your modules installed (`harness/init.sh`).
2. **Verifiable test frame**: a passing test at each level (unit, integration, e2e).
3. **Bootstrap contract**: `BOOTSTRAP.md`, reviewed by a human.
4. **Task breakdown**: small features in `feature_list.json`, reviewed by a human.

The project's `.claude/settings.json` then enables the right plugin for everyone who
opens the repository. Requirements: Docker with the compose plugin, Python 3.10+, git.

## What you get in the Odoo repository

| File | Role |
|---|---|
| `CLAUDE.md` | Work Rules (WIP = 1, do less but finish), Feature List Rules, Definition of Done, Validation Hierarchy |
| `PROGRESS.md` | Current state (rewritten automatically), completed / in progress, known issues, next steps |
| `DECISIONS.md` | `- date: decision` |
| `feature_list.json` | `id`, `behavior`, `verification`, `state`, `evidence`; changed only by `harness/feature.py` |
| `harness/feature.py` | `add`, `start` (refused if another feature is in progress), `block`, `verify` (the only way to `passing`), `check` |
| `harness/verify.sh` | Three layers: static checks + pylint-odoo, Odoo unit/integration tests, Playwright e2e with a clean server log |
| `harness/checks/` | Project checks; every new kind of mistake found in a review becomes one |
| `harness/errors.py` | Red-pen catalog: each failure prints WHY and HOW TO FIX |

## What the plugin adds to Claude Code

- **Automatic sessions** (hooks): context loaded at session start; edits of the feature
  list, the evidence, Odoo core/enterprise and non-test databases denied; static checks
  after each edit; a clean-state gate at the end of each turn.
- **Skills**: `init`, `update` (refresh the harness files after a plugin update), `add-harness-check`, and `odoo`: the Odoo reference for the plugin's
  version (ORM, views, security, OWL, controllers, tests, migrations, version notes),
  written from the real `odoo/odoo` source and checked against it in CI.
- **Agents**: `odoo-reviewer` (rubric + Odoo checklist, proposes new checks) and
  `odoo-explorer` (finds the parent definitions in the Odoo source of your version).

## Autonomous loop

`harness/loop.py run` works through `feature_list.json` on its own, with Claude Code
headless, as a maker-checker graph:

```
select -> maker (claude -p) -> verify (harness/feature.py verify) -> [review] -> commit -> select
             ^---- retry with the red-pen output (bounded attempts) ----|
             attempts exhausted -> work saved in a git stash, feature blocked with the reason
```

- The maker never judges its own work: only `feature.py verify` can mark a feature
  passing, and `--review` adds the `odoo-reviewer` agent as a second, independent checker.
- Only verified work is committed. Failed work is kept in a named `git stash` and the
  feature is blocked with the reason and the stash name in PROGRESS.md.
- Budgets: `--max-features` (default 1, so a human reviews each feature), `--attempts`
  (default 3), `--max-turns` and `--max-budget-usd` per agent call, `--timeout`.
- `--branch loop/<name>` works on a new branch. Logs and agent outputs:
  `.harness/loop/<run>/`; last summary: `harness/loop.py status`.
- Requirements: a clean working tree, a healthy baseline (`harness/init.sh --check`), and
  the `claude` CLI logged in with the plugin installed.

## Collaborators

In the commands below, `<N>` is your Odoo major version (17, 18, 19 or 20).


The init skill enables the plugin in the project's `.claude/settings.json`, but Claude Code
does not download a plugin from project settings alone. Each person installs it once:

```
claude plugin install odoo-harness-<N>@odoo-harness --scope project
```

## Update

**The plugin** (skills, agents, hooks). Projects installed by the init skill turn on
auto-update for the `odoo-harness` marketplace: Claude Code updates the plugin in the
background and asks you to run `/reload-plugins`. To update now:

```
claude plugin update odoo-harness-<N>@odoo-harness
```

or `/plugin` → **Installed** → `odoo-harness-<N>` → **Update now**. To stop automatic
updates: `/plugin` → **Marketplaces** → `odoo-harness` → **Disable auto-update**.

**The harness files in your Odoo repository** (harness scripts, checks, red-pen catalog,
CLAUDE.md block). After a plugin update, run `/odoo-harness-<N>:update`. It replaces the
harness files, keeps the project state (PROGRESS.md, DECISIONS.md, feature_list.json,
BOOTSTRAP.md) and configuration (docker-compose.yml, odoo.conf, harness/harness.env,
e2e/conftest.py, harness/errors_project.py), shows how the templates of the kept files
changed, runs the checks, and records the update. Commit the result.

**Another Odoo version.** Moving a project from one Odoo version to the next is a
migration, not an update: install the plugin of the new version, change `ODOO_VERSION`
and `ODOO_IMAGE` in `harness/harness.env` and the enabled plugin in
`.claude/settings.json`, then follow `references/migrations.md` of the new `odoo` skill.

## Uninstall

- Turn it off for yourself in one project: `claude plugin disable odoo-harness-<N>@odoo-harness --scope local`
- Uninstall the plugin: `claude plugin uninstall odoo-harness-<N>@odoo-harness`
  (`--scope project` removes it from the project's `.claude/settings.json` for everyone)
- Remove the marketplace and every plugin installed from it: `claude plugin marketplace remove odoo-harness`

Uninstalling the plugin does not touch your Odoo repository. To remove the harness from it:

1. Delete the block between `<!-- odoo-harness:start -->` and `<!-- odoo-harness:end -->` in `CLAUDE.md`.
2. In `.claude/settings.json`, remove `odoo-harness-<N>@odoo-harness` from `enabledPlugins`,
   `odoo-harness` from `extraKnownMarketplaces`, and the harness permission rules you no longer want.
3. Stop the containers: `docker compose --env-file harness/harness.env down`
   (add `-v` only to delete the test database volumes).
4. Delete `harness/`, `.harness/`, and the files the harness added that you do not keep:
   `e2e/`, `docker-compose.yml`, `odoo.conf`, `.pylintrc`, `.pre-commit-config.yaml`.
5. Keep or archive `PROGRESS.md`, `DECISIONS.md`, `feature_list.json` and `BOOTSTRAP.md`:
   they are the history of the project.

## How it is verified

Every version branch runs, on each push:
- the test suite (hooks, state machine, verification layers, version rules);
- `skill-check`: the `odoo` skill against facts extracted from the matching `odoo/odoo` source;
- `odoo-e2e`: a demo project against real Odoo, PostgreSQL and Playwright in Docker; a
  feature goes to `passing`, then an injected bug must fail verification with a red-pen message;
- `branches`: shared files identical on all version branches.

## Maintain

Shared changes are made on `17.0` and merged forward: `17.0 → 18.0 → 19.0 → 20.0`.
Only `odoo_version.json`, `.claude-plugin/plugin.json` and `skills/odoo/` differ between
branches (`git config merge.ours.driver true` once, so merges keep them).
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.
