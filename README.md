# claude-odoo-harness

A [Claude Code](https://claude.com/claude-code) harness for Odoo projects, based on
[Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/fr/).

A harness is the work system around the model. It makes an agent reliable on long Odoo projects:
- **State lives in the repo**: `PROGRESS.md`, `DECISIONS.md` and `feature_list.json`.
- **WIP = 1**: one feature at a time. The next one starts only after e2e verification passes.
- **The harness owns feature states**: the agent cannot mark its own work `passing`.
- **Three verification layers**: static analysis (pylint-odoo), Odoo tests, then Playwright e2e.
- **Red-pen errors**: every failure says what failed, WHY and HOW TO FIX it.
- **Automatic sessions**: hooks load the context at start and check for a clean state at stop.

> 🇫🇷 [Version française](README.fr.md)

## Branches = Odoo versions
| Branch | Odoo |
|---|---|
| `17.0` | 17.0 |
| `18.0` | 18.0 |
| `19.0` | 19.0 |
| `20.0` | 20.0 |

## The Odoo skill

Each branch ships `skills/odoo/` for its Odoo version: ORM, views, security, OWL,
controllers, tests, migrations, and the changes since the previous versions. It is written
from the real `odoo/odoo` source and CI checks it against that source:

```
tools/odoo-skill-extract/fetch_odoo.sh 20.0 /tmp/odoo-20.0
python3 tools/odoo-skill-extract/extract.py /tmp/odoo-20.0 -o /tmp/facts.json
python3 tools/odoo-skill-extract/check_skill.py /tmp/facts.json skills/odoo
```

## Install in an Odoo project
1. Add the marketplace (`/plugin marketplace add yessin-fogits/claude-odoo-harness@main`) and install `odoo-harness-<major>@odoo-harness` for your Odoo version.
2. In your Odoo repository, run `/odoo-harness-<major>:init`. It goes through the 4 initialization steps:
   1. executable environment (Docker Compose, test DB, modules installed);
   2. verifiable test frame (a passing test at each level);
   3. bootstrap contract (`BOOTSTRAP.md`);
   4. task breakdown (`feature_list.json`).

## Status
Phases 1 to 4 are in place: core harness, state machine and 3-layer verification, automatic session hooks, and the Odoo skill per version. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full plan
and [PROGRESS.md](PROGRESS.md) for the current state.

## Develop

Shared changes go to `17.0`, then are merged forward: `17.0 → 18.0 → 19.0 → 20.0`.
Only `odoo_version.json` and `skills/odoo/` differ between branches
(run `git config merge.ours.driver true` once so merges keep them).

```
pip install pytest shellcheck-py "pylint-odoo==10.0.12"
python -m pytest -q
```
