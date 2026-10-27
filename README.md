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
/plugin marketplace add yessin-fogits/claude-odoo-harness
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
- **Skills**: `init`, `add-harness-check`, and `odoo`: the Odoo reference for the plugin's
  version (ORM, views, security, OWL, controllers, tests, migrations, version notes),
  written from the real `odoo/odoo` source and checked against it in CI.
- **Agents**: `odoo-reviewer` (rubric + Odoo checklist, proposes new checks) and
  `odoo-explorer` (finds the parent definitions in the Odoo source of your version).

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
