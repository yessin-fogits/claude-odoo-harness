# claude-odoo-harness

A [Claude Code](https://claude.com/claude-code) harness for Odoo projects, based on
[Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/fr/).

A harness is the work system around the model. It makes an agent reliable on a whole Odoo
project, new or already developed (custom modules, OCA addons, Odoo Enterprise, Docker,
GitLab):
- **State lives in the repo**: `PROGRESS.md`, `DECISIONS.md` and `feature_list.json`.
- **WIP = 1**: one feature at a time. The next one starts only after e2e verification passes.
- **The harness owns feature states**: the agent cannot mark its own work `passing`.
- **Three verification layers**: static analysis (pylint-odoo), Odoo tests, then Playwright e2e.
- **Red-pen errors**: every failure says what failed, WHY and HOW TO FIX it.
- **Automatic sessions**: hooks load the context at start and check for a clean state at stop.
- **Odoo tasks → features → merge request**: each Odoo task (`T2003`) is split into features,
  worked on its own branch, and shipped as a merge request when every feature passes.

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
1. Add the marketplace (`/plugin marketplace add yessin-fogits/claude-odoo-harness@main`) and install `odoo-harness-<N>@odoo-harness` for your Odoo version.
2. Start Claude Code in the client folder (fogits layout: `~/Project/<client>`, with the git
   repository in `git/` and Odoo Enterprise in `enterprise/`), or in the repository itself,
   and run `/odoo-harness-<N>:init`. The harness is installed in the repository (`git/`) and
   versioned with it; the client folder gets a `CLAUDE.md` that imports `git/CLAUDE.md` and
   a `.claude/settings.json` that enables the plugin (not versioned). After cloning a project
   that already has the harness, `/odoo-harness-<N>:update` writes just these two files.
   The init:
   - **detects the project**: `addons_path` from `odoo-stag.conf` / `odoo-main.conf`, custom
     modules (`extra-addons/<client>`), third-party addons (`extra-addons/oca`, read-only),
     Enterprise, the Odoo version and image from the `Dockerfile`, the base branch (`staging`),
     the GitLab project and the deployment files (read-only). You confirm it;
   - **discovers an existing project**: writes `ARCHITECTURE.md` (module map from
     `harness/project_map.py`, dependencies, risks and debt from
     `harness/static_checks.py --all`) and a `# This project` section in `CLAUDE.md`, reads the
     open tasks of the matching project in your Odoo through the Odoo MCP connector (read
     only) and proposes them as features;
   - runs the 4 initialization steps: executable environment (the project's image, its own
     database with demo data and port, never your dev stack), verifiable test frame,
     bootstrap contract (`BOOTSTRAP.md`), task breakdown (`feature_list.json`).

No SSH key is needed: plugins are cloned over HTTPS. If an install fails with
`Permission denied (publickey)`, run `/plugin marketplace update odoo-harness` and install again.

## What the harness checks, and what it leaves alone
- It tests the modules a branch changes **and every custom module that depends on them**;
  the full e2e suite runs when more than one module changes.
- Problems that were already there do not block a feature: lint and project checks block
  only on the lines the branch changed. `harness/static_checks.py --all` lists the rest as
  debt. Breaking errors (syntax, XML, manifest) always block.
- pylint-odoo runs with the project's own `.pylintrc-mandatory`, at the project's Odoo version.
- Never edited by the agent: Odoo core and Enterprise, third-party addons, deployment files
  (Dockerfile, compose files, `odoo-*.conf`, `.gitlab-ci.yml`), databases other than the test
  database, `staging` and `main` (no direct push), and secrets (`no-hardcoded-secrets` check).

## Odoo tasks and merge requests
```
harness/feature.py add --task T2003 --behavior "..." --verify "unit: ..." --verify "e2e: ..."
harness/feature.py start F-001      # checks out branch T2003 (created from staging)
harness/feature.py verify F-001     # passing + evidence; commit "[T2003] F-001 ..."
harness/gitlab.py mr T2003          # when every feature of T2003 passes: push + merge request
```
The merge request targets `staging` and lists the features with their evidence. It needs a
GitLab token with the `api` scope in `GITLAB_TOKEN` (environment, or the git-ignored `.env`
file of the repository); never commit it. The autonomous loop opens it by itself when it
finishes a task (`--no-mr` to turn that off).

## Autonomous loop

`harness/loop.py run` works through `feature_list.json` on its own, with Claude Code
headless, as a maker-checker graph:

```mermaid
flowchart TD
    P["preflight<br/>clean tree, valid feature list, healthy environment"] --> S["select<br/>a feature to work on?"]
    S -->|"none left"| E(["end of run"])
    S -->|"F-xxx"| M["maker<br/>claude -p implements the feature"]
    M --> V["verify<br/>harness/feature.py verify"]
    V -->|"fail"| A{"attempts left?"}
    V -->|"pass, with --review"| R["review<br/>odoo-reviewer agent"]
    V -->|"pass, no --review"| C["commit<br/>feat(F-xxx): ..."]
    R -->|"Accept"| C
    R -->|"Revise / Block"| A
    A -->|"yes: retry with the red pens<br/>or the review findings"| M
    A -->|"no"| B["shelve<br/>work saved in a git stash,<br/>feature blocked with the reason"]
    C --> N{"--max-features reached?"}
    B --> N
    N -->|"no"| S
    N -->|"yes"| E
```

Each step:

1. **preflight**: the working tree is clean, `feature.py check` passes and the environment is healthy.
2. **select**: the feature in progress, else the first `not_started` one.
3. **maker**: a headless Claude Code session (`claude -p`) implements the feature.
4. **verify**: `harness/feature.py verify` runs the 3 layers; it is the only judge of done.
5. **review** (with `--review`): the `odoo-reviewer` agent, in a fresh context, must answer Accept.
6. **commit** the verified work, or **shelve** it once the attempts are used up.

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
BOOTSTRAP.md, ARCHITECTURE.md) and configuration (harness/harness.env, e2e/conftest.py,
harness/errors_project.py), regenerates `harness/docker-compose.yml` and `harness/odoo.conf`
from `harness/harness.env`, shows how the templates of the kept files changed, runs the
checks, and records the update. Commit the result. A harness installed before full-project
mode (`MODULES`, `ADDONS_DIR`) is migrated by the same command.

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
3. Stop the harness containers:
   `docker compose --project-directory . -f harness/docker-compose.yml --env-file harness/harness.env down`
   (add `-v` only to delete the test database volumes).
4. Delete `harness/`, `.harness/`, and the files the harness added that you do not keep:
   `e2e/`, and `.pylintrc` / `.pre-commit-config.yaml` if the harness created them.
5. Keep or archive `PROGRESS.md`, `DECISIONS.md`, `feature_list.json`, `BOOTSTRAP.md` and
   `ARCHITECTURE.md`: they are the history and the map of the project.

## Status
Phases 1 to 7 are in place: core harness, state machine and 3-layer verification, automatic session hooks, the Odoo skill per version, the review → check loop, the autonomous loop, and full-project mode (detection, discovery, Odoo tasks, merge requests). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full plan
and [PROGRESS.md](PROGRESS.md) for the current state.

## Develop

Shared changes go to `17.0`, then are merged forward: `17.0 → 18.0 → 19.0 → 20.0`.
Only `odoo_version.json` and `skills/odoo/` differ between branches
(run `git config merge.ours.driver true` once so merges keep them).

```
pip install pytest shellcheck-py "pylint-odoo==10.0.12"
python -m pytest -q
```
