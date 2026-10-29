# claude-odoo-harness

A [Claude Code](https://claude.com/claude-code) harness for Odoo projects, based on
[Learn Harness Engineering](https://walkinglabs.github.io/learn-harness-engineering/fr/).

> 🇫🇷 [Version française](README.fr.md)

A harness is the work system around the model. It makes Claude reliable on long Odoo
projects: the state lives in the repository, one feature is done at a time, and only the
harness can declare a feature done, after real verification.

## Install

**Once per machine**, one plugin for every Odoo version (17.0 to 20.0):

```
/plugin marketplace add yessin-fogits/claude-odoo-harness@main
/plugin install odoo-harness@odoo-harness
```

Install it at user scope (the default): every project on the machine gets it, and a plugin
update reaches all of them at once. Then, **once per project**, start Claude Code at the root
of the Odoo repository, or in its client workspace (fogits layout: `~/Project/<client>`, with
the repository in `git/` and Odoo Enterprise in `enterprise/`), and run `/odoo-harness:init`.
In an Odoo repository without the harness, the first session offers it once.

The harness covers the **whole project**, new or already developed:

- **Detection**: custom modules, third-party (OCA) addons, Enterprise, the Odoo version and
  image, the base branch, the GitLab project and the deployment files are read from the
  project itself (`odoo-stag.conf`, `Dockerfile`, git). You confirm them.
- **Discovery of an existing project**: `ARCHITECTURE.md` (module map, dependencies, risks
  and debt), a project section in `CLAUDE.md`, and the open tasks of the project in your Odoo
  (read through the Odoo MCP connector) proposed as features.

Then the 4 initialization steps:

1. **Executable environment**: the project's own image, its own PostgreSQL, port and
   disposable test DB with demo data (never your dev stack), every custom module installed
   (`odoo-harness init`).
2. **Verifiable test frame**: a passing test at each level (unit, integration, e2e).
3. **Bootstrap contract**: `BOOTSTRAP.md`, reviewed by a human.
4. **Task breakdown**: small features in `feature_list.json`, reviewed by a human.

`init` also offers, once per machine, to allow the `odoo-harness` command in your user
settings, so sessions in any client workspace don't ask for permission at each command.
Requirements: Docker with the compose plugin, Python 3.10+, git.

No SSH key is needed: the plugin is cloned over HTTPS from this public repository.

## How it is split

The engine is installed once per machine; the repository holds no copy of it. The
repository stays the team's system of record: the feature list, the evidence and
PROGRESS.md are versioned with the code.

| Where | What |
|---|---|
| The plugin (once per machine) | the `odoo-harness` command and its engine (feature workflow, 3-layer verification, test environment, loop, GitLab, guides, red-pen catalog, harness checks, Docker files), the hooks, skills and agents |
| The Odoo repository | the state (`PROGRESS.md`, `DECISIONS.md`, `feature_list.json`, `BOOTSTRAP.md`, `ARCHITECTURE.md`, `harness/evidence/`) and the project's configuration (`harness/harness.env`, its own checks and red pens, `e2e/`) |
| `~/.odoo-harness/` | `current`, a link to the installed plugin; the `~/.local/bin/odoo-harness` shim points through it |

`harness/harness.env` pins `HARNESS_VERSION`, the oldest engine the project accepts: a
teammate with an older plugin is asked to update it before `odoo-harness` runs, so everyone
verifies with the same rules. Each evidence file records the engine version that produced it.

## What you get in the Odoo repository

| File | Role |
|---|---|
| `CLAUDE.md` | Work Rules (WIP = 1, do less but finish), Feature List Rules, Definition of Done, Validation Hierarchy |
| `PROGRESS.md` | Current state (rewritten automatically), completed / in progress, known issues, next steps |
| `DECISIONS.md` | `- date: decision` |
| `ARCHITECTURE.md` | Map of the project: modules, models, dependencies, risks and debt |
| `feature_list.json` | `id`, `behavior`, `verification`, `state`, `evidence`, and the Odoo `task` (`T2003`); changed only by `odoo-harness feature` |
| `harness/harness.env` | The project's harness settings: Odoo version and image, addon folders, test DB and port, base branch, GitLab project, protected paths, `HARNESS_VERSION` |
| `harness/checks/` | Project checks; every new kind of mistake found in a review becomes one |
| `harness/errors_project.py` | The project's red pens: each failure prints WHY and HOW TO FIX |
| `harness/evidence/` | One evidence file per passing feature |

## The `odoo-harness` command

Run it from the repository or its client workspace; it finds the repository itself.

| Command | Does |
|---|---|
| `odoo-harness init [--check \| --reset]` | The test environment: the project's image, its own PostgreSQL and port, the custom modules installed on a disposable DB, the baseline verification |
| `odoo-harness feature add \| start \| block \| verify \| check \| status` | The feature workflow. `start` is refused if another feature is in progress and checks out the task branch; `verify` is the only way to `passing` |
| `odoo-harness verify` | Three layers on the changed modules and every module that depends on them: static checks + pylint-odoo (the project's rcfile), Odoo tests, Playwright e2e with a clean server log. Older findings are debt, not blockers |
| `odoo-harness gitlab mr T2003` | Once every feature of the task passes, push the task branch and open its merge request to `staging` |
| `odoo-harness guide capture \| build \| check` | The French user guide of a completed task, from the replayed e2e tests |
| `odoo-harness static [--all]`, `odoo-harness map` | The static checks (`--all`: the debt report), the project map |
| `odoo-harness compose ...` | `docker compose` on the harness stack (`compose logs odoo`, `compose ps`) |
| `odoo-harness loop run \| status` | The autonomous loop (below) |
| `odoo-harness where`, `odoo-harness link` | The repository, the engine and their versions; refresh the shim |

## What the plugin adds to Claude Code

- **Automatic sessions** (hooks): context loaded at session start (with the project's Odoo
  version and its guide); edits of the feature list, the evidence, the harness engine, Odoo
  core/Enterprise, third-party addons, deployment files and non-test databases denied, and no push to `staging`/`main`; static checks after each
  edit; a clean-state gate at the end of each turn.
- **Skills**: `init`, `update` (refresh the project's harness files, or migrate a project
  from the old vendored harness), `add-harness-check`, `guide`, and `odoo`: the Odoo
  reference with one guide per version (ORM, views, security, OWL, controllers, tests,
  migrations, version notes), written from the real `odoo/odoo` source and checked against it
  in CI. The session context names the guide of the project's version.
- **Agents**: `odoo-reviewer` (rubric + Odoo checklist, proposes new checks) and
  `odoo-explorer` (finds the parent definitions in the Odoo source of your version).

## Autonomous loop

`odoo-harness loop run` works through `feature_list.json` on its own, with Claude Code
headless, as a maker-checker graph:

```mermaid
flowchart TD
    P["preflight<br/>clean tree, valid feature list, healthy environment"] --> S["select<br/>a feature to work on?"]
    S -->|"none left"| E(["end of run"])
    S -->|"F-xxx"| M["maker<br/>claude -p implements the feature"]
    M --> V["verify<br/>odoo-harness feature verify"]
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
4. **verify**: `odoo-harness feature verify` runs the 3 layers; it is the only judge of done.
5. **review** (with `--review`): the `odoo-reviewer` agent, in a fresh context, must answer Accept.
6. **commit** the verified work, or **shelve** it once the attempts are used up.

- The maker never judges its own work: only `feature.py verify` can mark a feature
  passing, and `--review` adds the `odoo-reviewer` agent as a second, independent checker.
- Only verified work is committed. Failed work is kept in a named `git stash` and the
  feature is blocked with the reason and the stash name in PROGRESS.md.
- Budgets: `--max-features` (default 1, so a human reviews each feature), `--attempts`
  (default 3), `--max-turns` and `--max-budget-usd` per agent call, `--timeout`.
- `--branch loop/<name>` works on a new branch. Logs and agent outputs:
  `.harness/loop/<run>/`; last summary: `odoo-harness loop status`.
- Requirements: a clean working tree, a healthy baseline (`odoo-harness init --check`), and
  the `claude` CLI logged in with the plugin installed.

## Collaborators

Each person installs the plugin once on their machine:

```
claude plugin install odoo-harness@odoo-harness
```

The repository's `.claude/settings.json` enables the plugin and its marketplace, so Claude
Code offers it to anyone who opens the repository without it. A fresh clone needs nothing
else: the harness files are versioned, and nothing is generated in the client workspace.

## Update

**The plugin** (engine, hooks, skills, agents). The `odoo-harness` marketplace auto-updates:
Claude Code updates the plugin in the background, for every project at once, and asks you to
run `/reload-plugins`. To update now:

```
claude plugin update odoo-harness@odoo-harness
```

or `/plugin` → **Installed** → `odoo-harness` → **Update now**. To stop automatic updates:
`/plugin` → **Marketplaces** → `odoo-harness` → **Disable auto-update**.

**A project's harness files** (the CLAUDE.md block, settings, the version pin). Run
`/odoo-harness:update` in the project when the plugin changed its templates, or to raise the
project's `HARNESS_VERSION`. It keeps the project state (PROGRESS.md, DECISIONS.md,
feature_list.json, BOOTSTRAP.md) and configuration (harness/harness.env, e2e/conftest.py,
harness/errors_project.py, harness/checks/), shows how the templates of the kept files
changed, runs the checks, and records the update. Commit the result.

**A project installed before 2.0** (one plugin per Odoo version, the engine copied into
`harness/`). Install `odoo-harness`, then run `/odoo-harness:update` in the project: it deletes
the copied engine, rewrites the permission and pre-commit entries, removes the old plugin
from the repository and workspace settings, writes `HARNESS_VERSION`, and keeps the state.
Until then, the old `odoo-harness-<N>` plugin keeps driving the project and the new one stays
out of its way. The old plugins stay in the marketplace, marked deprecated, until every project
is migrated; uninstall yours afterwards: `claude plugin uninstall odoo-harness-<N>@odoo-harness`.

**Another Odoo version.** Moving a project from one Odoo version to the next is a migration,
not an update: change `ODOO_VERSION` and `ODOO_IMAGE` in `harness/harness.env`, then follow
`references/migrations.md` of the new version's guide in the `odoo` skill.

## Uninstall

- Turn it off for yourself in one project: `claude plugin disable odoo-harness@odoo-harness --scope local`
- Uninstall the plugin: `claude plugin uninstall odoo-harness@odoo-harness`, then remove
  `~/.odoo-harness/` and `~/.local/bin/odoo-harness`
- Remove the marketplace and every plugin installed from it: `claude plugin marketplace remove odoo-harness`

Uninstalling the plugin does not touch your Odoo repositories. To remove the harness from one:

1. Delete the block between `<!-- odoo-harness:start -->` and `<!-- odoo-harness:end -->` in `CLAUDE.md`.
2. In `.claude/settings.json`, remove `odoo-harness@odoo-harness` from `enabledPlugins`,
   `odoo-harness` from `extraKnownMarketplaces`, and the harness permission rules you no longer want.
3. Stop the containers: `odoo-harness compose down` (add `-v` only to delete the test
   database volumes), before uninstalling the plugin.
4. Delete `harness/`, `.harness/`, and the files the harness added that you do not keep:
   `e2e/`, `.pylintrc`, `.pre-commit-config.yaml`.
5. Keep or archive `PROGRESS.md`, `DECISIONS.md`, `feature_list.json` and `BOOTSTRAP.md`:
   they are the history of the project.

## How it is verified

On each push, for each Odoo version (17.0 to 20.0):
- the test suite (the `odoo-harness` command, hooks, state machine, verification layers,
  version rules, installer and migration);
- `skill-check`: the version's guide in the `odoo` skill against facts extracted from the
  matching `odoo/odoo` source;
- `odoo-e2e`: a demo project against real Odoo, PostgreSQL and Playwright in Docker, driven by
  `odoo-harness`; a feature goes to `passing`, then an injected bug must fail verification with
  a red-pen message.

## Maintain

Everything lives on `main`. Version-specific knowledge is data: `versions.json` (the
supported versions and their PostgreSQL image) and `skills/odoo/versions/<version>/`. To
support a new Odoo version, add it to `versions.json`, write its guide (run
`tools/odoo-skill-extract/` on its source), and add it to the CI matrix. The `17.0`...`20.0`
branches are frozen: they only serve the deprecated per-version plugins.

Bump `engine/VERSION` whenever a change can alter a verdict or a command of the engine
(verification layers, checks, red pens, feature rules). It is the only engine version:
`plugin.json` has none on purpose. The next `/odoo-harness:update` of a project raises its
`HARNESS_VERSION` pin to it.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.
