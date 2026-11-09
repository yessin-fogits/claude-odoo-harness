# Design: several developers on one project

Status: implemented in engine 3.0.0, 2026-11-04.

## Problem

The harness assumes one person writes its state. On a Fogits project such as bpa (8 active
developers) or internship2026 (20 members), each developer works on their own task branch, and
every branch changes the same tracked files:

| File | Who writes it | What goes wrong with two branches |
|---|---|---|
| `feature_list.json` | every `feature add/start/verify/block` | Both branches append to one JSON array, so every pair of MRs conflicts |
| feature IDs | `next_id()` = local max + 1 | Two branches both create `F-007`: duplicate IDs, and the same `harness/evidence/F-007.json` |
| `PROGRESS.md` "Current state" | the stop hook, at **every turn** | Machine-local data (last commit, dirty tree) committed on every branch: guaranteed conflict |
| `PROGRESS.md` feature lines | `feature start/verify/block` | Same sections edited on every branch |
| `DECISIONS.md` | the agent, append at end of file | Two appends at the end of the file conflict |
| WIP = 1 | `validate()`, over the whole file | Another branch's `in_progress`, merged by hand, blocks everyone's `feature start` |

On top of this, task branches that already exist on GitLab are not continued. `feature start
T10387` with no local branch creates a new `T10387` from the base branch, even when
`origin/T10387` exists. The push is then rejected, and the guard blocks the force push. The
four projects with history (bpa, conforama, moveandconnect, evms) have dozens of such branches.

The task-seeding step of `init` also commits features to the local base branch. Every task
branch created afterwards carries every seeded task, so the MRs of two tasks add the same files.

## Rule the design follows

**One task = one branch = one developer, and a branch only writes the files of its own task.**
Two MRs for two tasks then touch disjoint tracked files and cannot conflict on harness state.
Everything that is per checkout (current state, last verify) is git-ignored.

## Changes

### 1. One feature file per task: `tasks/<task>.json`

`feature_list.json` is replaced by one file per task:

```json
{"version": 2, "task": "T2003", "features": [
  {"id": "F-T2003-1", "behavior": "...", "verification": ["unit: ...", "e2e: ..."],
   "state": "not_started", "evidence": null}
]}
```

- `hlib.load_features()` keeps returning the merged view `{"version": 1, "features": [...]}`. It
  reads every `tasks/*.json` and puts `task` back on each feature from the file. Its callers
  (`feature.py`, `gitlab.py`, `guide.py`, `loop.py`) do not change.
- **Order:** tasks in natural order (`T9300` before `T10283`), then file order within a task. The
  result is the same in every clone, unlike modification times.
- `hlib.save_features(data)` groups by task and rewrites only the files whose content changed.
  A command on T2003 never rewrites `tasks/T5.json`.
- `--task` becomes **mandatory** on `feature add`, because a feature without a task has no file
  to live in. A free short name (`remise-devis`) is still accepted, as today.
- `validate()` checks each file, plus duplicate IDs across all files. Duplicates can only appear
  through a manual mistake now, and the check catches them at the first command after the merge.
- The hooks stop parsing `feature_list.json` themselves. `session_start` and `stop_gate` call a
  new `feature.py list --json`, which prints the merged view, so there is one reader.
- **Protection** moves from `feature_list.json` to `tasks/*.json`, and only those files.
  `tasks/*.md` (see 4) stays editable by the agent. This applies to the `pre_tool_guard` paths
  and its shell-command check, `template/.claude/settings.json` (`Edit(tasks/*.json)`), and the
  pre-commit hook in `template/.pre-commit-config.yaml`.
- **Activation:** a repository has the harness when it has `harness/harness.env` and a `tasks/`
  folder. This replaces the `feature_list.json` test in `hooks/_common.has_harness`,
  `engine/cli.has_harness`, `bin/odoo-harness`, and `offer_init` in session_start. Without
  this, removing `feature_list.json` would silently switch off every hook.

### 2. Feature IDs scoped to their task: `F-<task>-<n>`

- `next_id(data, task)` is 1 + the highest `n` among **all** IDs that start with `F-<task>-`, not
  only the task's current features. A task's features exist on its branch only, so two
  developers cannot pick the same ID.
- `rename-task` **keeps** the IDs. `F-remise-devis-1` stays its ID after the task becomes
  `T2003`, so the evidence, its fingerprint and the e2e file names stay valid. Because `n` is
  computed from every ID with the prefix, a later task reusing the free name `remise-devis`
  continues at `-2`.
- `ID_RE` accepts both forms: `^F-(\d{3,}|[A-Za-z0-9][A-Za-z0-9_-]*-\d+)$`. Legacy `F-001` IDs keep
  working.
- The e2e file convention becomes `e2e/test_<id without "F-", "-" as "_">_<name>.py`, for example
  `e2e/test_T2003_1_discount.py`. This goes in the red pen example of `feature add`, in the
  template CLAUDE.md, and in the init skill.
- Commit message: `[T2003] F-T2003-1 <behavior>`.

### 3. WIP = 1 per task branch

- `validate()` no longer counts `in_progress` across the repository. It allows at most one
  `in_progress` per task file.
- `feature start X` is refused while a feature is `in_progress` in the task of the **current
  branch** or in the task of **X**. This keeps today's refusal for "switch task with a feature
  still in progress". A feature `in_progress` in any other task belongs to another branch: it
  never blocks.
- The `feature status` and session-start summaries show it as "in progress on another branch"
  with its task, instead of as the current feature.
- **Loop selection** (`loop.select`): first the `in_progress` feature of the current branch's
  task, then the first `not_started` feature whose task has no branch on `origin` (after a
  fetch). This stops the loop from taking a task a teammate already pushed.

### 4. Task notes in `tasks/<task>.md`, and nothing machine-local in git

- `feature add` creates `tasks/<task>.md` for the first feature of a task, with these sections:
  `Features` (lines kept by the harness), `Notes` (done / left), `Known issues`, `Decisions`,
  `Next steps`.
- `progress_set_task`, `progress_rename_task` and the `block` reason write to the task's notes
  file instead of `PROGRESS.md`. `rename-task` moves both `tasks/` files.
- **"Current state"** is no longer in a tracked file. `stop_gate` computes it as today and writes
  it to `.harness/current-state.md`, which is git-ignored. `session_start` reads it from there.
- **`PROGRESS.md`** keeps only project-wide `Known issues` and `Next steps`. Nothing in the
  harness writes it any more, and it is rarely edited. Once the stop hook stops writing it, it
  conflicts no more often than any other doc.
- **The "notes not updated" rule of the stop hook:** the turn is refused when code changed this
  session but neither the current task's notes nor `PROGRESS.md` changed since the session's
  start commit or in the working tree. Today the rule compares one file's body against a
  snapshot taken at session start. That breaks when `feature start` switches branch during the
  session, and the new check doesn't.
- **What session start loads:**
  - the current state;
  - `PROGRESS.md`;
  - the notes of the current branch's task;
  - a task index built from `feature.py list --json`: each task, its feature counts by state, and
    whether it is in progress elsewhere;
  - the last decisions.
- **Decisions:** a task's decisions go to its notes. `DECISIONS.md` keeps project-wide ones, and
  gets `merge=union` in `.gitattributes`. That attribute is a safety net only, since it is
  unverified whether GitLab's server-side merge honours it. The design doesn't depend on it.
  `PROGRESS.md` is left out of `merge=union`, because union on markdown sections can silently
  duplicate or misplace lines. `install_template.py` merges the `.gitattributes` line the same
  way it merges `.gitignore`.

### 5. `feature add` works on the task branch

- `feature add --task T` checks out the task branch first, as `start` does: same clean-tree rule,
  same branch logic (see 6). A task's files are therefore only ever created on its own branch.
- `--no-branch` (new on `add`) skips the switch. The init skill's step 4 uses it, because seeding
  happens on the install branch before the base has the harness. Seeded files reach the base
  with the install MR, `not_started`, and each one is then changed only on its task branch.

### 6. Task branches that already exist on GitLab

`switch_to_task_branch(task)`, used by `start` and now `add`:

1. `git fetch -q origin <task>`, best effort. If the network is down, the last fetch is used, with
   a warning.
2. **Local branch exists:** check it out. If `origin/<task>` is ahead, fast-forward it
   (`merge --ff-only`). If the two have diverged, a red pen tells the user to pull or rebase.
3. **Only `origin/<task>` exists and it has the harness in the new layout:** run
   `git checkout -b <task> --track origin/<task>`. This is a teammate's branch being continued.
4. **Only `origin/<task>` exists and it predates the harness:** red pen with two choices:
   - continue that branch by merging the base into it (exact commands given);
   - or work under a new name, `--task T7027_<ddmmyyyy>`, which is the team's existing convention.
5. **No branch anywhere:** create it from the base, as today, including the "start where the
   harness is" rule.

`has_harness(ref)` checks the new layout (`harness/harness.env` and `tasks/`). A branch that
still has `feature_list.json` and no `tasks/` gets a red pen: run `/odoo-harness:update` first.

### 7. Migration of existing projects (`/odoo-harness:update`)

The migration is one-shot. No code path reads both layouts.

- `feature_list.json` is split into `tasks/<task>.json` (IDs kept), then deleted. If a feature
  has no task, the update stops and lists it. No project has any today, so no tool is built for
  that case.
- From `PROGRESS.md`, the feature lines under `In progress` and `Completed tasks` move to each
  task's notes, and `Current state` is dropped.
- `engine/VERSION` and the project's `HARNESS_VERSION` are raised, so every teammate's engine
  switches layout at the same time. An older engine refuses to run.
- **Rollout rule:** migrate when no task branch is open. A branch from before the migration still
  has `feature_list.json`, and merging the base into it gives a modify/delete conflict.
  Pre-rollout, this is true for every Fogits repo. The only install is the local qafila
  checkout: old layout, 0 features. It is the migration test case.

## Files touched

| Area | Files |
|---|---|
| Engine | `hlib.py` (load/save, validate, ID_RE, notes helpers), `feature.py` (add, start, rename, check, list, next_id, branch switch), `loop.py` (select, maker prompt), `gitlab.py` (committed check on `tasks/<task>.*`), `verify.py` (`tasks/` counts as docs), `guide.py` (message), `cli.py` (activation) |
| Hooks | `_common.py` (activation, feature list via `feature.py list --json`), `session_start.py`, `stop_gate.py`, `pre_tool_guard.py` (paths) |
| Install | `scripts/install_template.py` (migration, `.gitattributes`), `template/` (remove `feature_list.json`, add `tasks/.gitkeep`, slim `PROGRESS.md`, `CLAUDE.md` block, `settings.json`, `.pre-commit-config.yaml`, `gitignore`), `bin/odoo-harness` |
| Skills, docs | `skills/init` (step 4 with `--no-branch`), `skills/update`, `skills/guide`, `skills/add-harness-check`, `agents/odoo-reviewer.md`, `README.md`, `README.fr.md`, `docs/ARCHITECTURE.md`, `DECISIONS.md` |
| CI and tests | `.github/workflows/ci.yml` (reads `feature_list.json`), `tests/*` |

## Acceptance tests

1. **Two developers, one merge.** One origin, two clones. Clone A adds and finishes two features
   of `T1`. Clone B, in parallel, does the same for `T2`. Both push. On `staging`, both branches
   merge: `git merge` exits 0 both times, and `feature check` passes. The IDs are `F-T1-1`,
   `F-T1-2`, `F-T2-1` and `F-T2-2`, with four distinct evidence files.
2. **Stale work in progress.** A branch with `F-T1-1 in_progress` is merged into `staging`. On
   `staging`, `feature start F-T2-1` succeeds and the status shows `F-T1-1` as being on another
   branch.
3. **Continue a teammate's branch.** `origin/T3` exists with the harness and no local branch
   exists: `feature start` tracks it, then `gitlab push` fast-forwards. If `origin/T3` predates
   the harness, the red pen gives both choices. A local branch that is behind fast-forwards; a
   diverged one gets a red pen.
4. **The stop hook leaves git alone.** On a clean tree, after a turn ends, `git status` is still
   clean.
5. **Rename.** `rename-task remise-devis T2003` moves both task files and keeps `F-remise-devis-1`.
   A new feature of a new `remise-devis` task gets `-2`.
6. **Migration.** An old-layout repository with features in two tasks is split, the hooks stay
   active, and `feature check` passes.
7. **Loop.** It skips a task whose branch exists on `origin`.
8. **Legacy IDs.** `F-001` IDs load and verify.

## Decisions for you

1. **ID format `F-T2003-1`:** OK, or do you prefer another separator?
2. **Init bulk-seeding.** Today step 4 imports every open Odoo task as features, with no owner.
   I recommend that `init` seeds nothing on a project with several developers, and each
   developer adds a task's features when they take it (`feature add` on its branch). Seeding stays
   for a project with a single developer.

## Not in this change

- **Base branch detection** (it picks `staging` even where MRs go to `staging19` or
  `post-upgrade`): a separate fix in `detect_project.py`.
- **Edits inside git submodules:** not seen by verification. Done in engine 3.4.0: see
  "Shared submodules" in `docs/ARCHITECTURE.md`.
- **ai-workflow is dropped.** Rollout step: remove its global commands and agents from
  `~/.claude/commands` and `~/.claude/agents` on each machine (`/task`, `/implement`, `/pre-mr`,
  `/review`, `odoo-analyst`, ...), so they don't run beside the harness.
