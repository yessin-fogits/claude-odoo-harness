---
name: guide
description: Write the user guide of a completed Odoo task (T2003) as a PDF in French with screenshots taken by replaying the task's Playwright e2e tests, saved in docs/guides/ of the project. Only for a task whose features all pass and are committed.
argument-hint: "T2003"
disable-model-invocation: true
---

# User guide of a completed task

Task: $ARGUMENTS

The guide is for the developers of the team: what the task added to Odoo, shown step by
step with screenshots, and the technical details they need to find it in the code. It is
written in French. It is a PDF committed in the project repository: `docs/guides/<task>.pdf`.

`REPO` below is the repository: `.` when Claude Code runs in it, `git` when it runs in the
client workspace (`~/Project/<client>`, with the repository in `git/`). `odoo-harness` finds
it from either folder; file paths below are relative to `REPO`.

If $ARGUMENTS is empty or is not a task code, run `odoo-harness feature status`, ask which
task, and stop.

## 1. Capture: the gate and the screenshots

```
odoo-harness guide capture <task>
```

It refuses a task that is not completed (a feature not passing, invalid evidence, a feature
not committed, uncommitted changes in the modules or `e2e/`). When it refuses, show the
user the red-pen message and stop. Do not try to make the task pass, verify features, or
commit for them: the guide is for completed work only.

When it passes, it has replayed each feature's e2e test on the committed code and written:
- `.harness/guide/<task>/steps.json`: for each feature, its tests and their steps (`key`,
  `caption` from `guide.step()`, `image`);
- `.harness/guide/<task>/content.json`: the text to write, every field marked `À RÉDIGER`
  (text from an earlier run is kept).

A test that has no `guide.step()` gets only one screenshot, its final screen. Say so in
your summary and suggest adding steps to that test (see the rule in CLAUDE.md); do not
change the tests yourself during this skill.

## 2. Look before you write

- Read `steps.json`, then open every screenshot (Read the PNG files) in order.
- Read the feature's code: `git log --format='%H %s' --grep '<task>'` gives the commits;
  `git show --stat <sha>` and the diff of the custom modules show the models, fields, views,
  security and data the feature added.

## 3. Write `content.json` in French

Fill every field marked `À RÉDIGER`, in French, for a developer who did not work on the task:

- `title`: `<task> : <what the task brings, in a few words>`.
- `summary`: two to four sentences: the business need and what the task adds.
- `features.<id>.summary`: what the feature lets the user do, in one or two sentences.
- `features.<id>.steps.<key>`: one or two sentences per screenshot: what the user does on
  this screen and what they see. Describe only what the screenshot shows.
- `features.<id>.technical`: where it lives in the code: module, models and fields,
  views (XML ids), security rules, methods to read first. Use `code` for names. A list
  with `- ` per line is fine.
- `features.<id>.notes` (optional): limits, configuration needed, known issues from PROGRESS.md.

Rules:
- Never describe behavior that no screenshot or code shows. The guide documents what the
  tests proved, nothing more.
- Write text only: no HTML. `**bold**`, `` `code` ``, blank lines between paragraphs and
  `- ` lists are rendered.
- Do not add or remove keys: `build` refuses a file that does not match the screenshots.

## 4. Build the PDF

```
odoo-harness guide build <task>
```

It writes `docs/guides/<task>.pdf` and records the guide in `docs/guides/guides.json`.
Fix what a red-pen message reports and build again.

## 5. Hand over

Commit the two files with the message `build` printed (`[<task>] Guide utilisateur`).
Then tell the user, in their language: the PDF path, how many features and screenshots
it has, and any test that had no `guide.step()`.

`odoo-harness guide check` lists the guides made stale by a later change (a feature
verified again or reopened). A stale guide is regenerated with this skill.
