---
name: add-harness-check
description: Turn a mistake found in a code review into an automated harness check (a file in harness/checks/ with a WHY / HOW TO FIX message), so no agent repeats it. Use when a review (the odoo-reviewer agent, a human, or your own) finds a new kind of mistake, or when the user asks to add a check.
argument-hint: "[short description of the mistake]"
---

# Add a harness check

Every new kind of agent mistake found in a review becomes a check. A check runs in
layer 1 (`harness/static_checks.py`): after each edit of a module file, at every
`harness/feature.py verify`, and at the end of each turn. Mistake to turn into a check: $ARGUMENTS

## 1. Name the kind of mistake, not the instance

"`sudo()` on a record id taken from request params" is a kind; "line 42 of
controllers/main.py" is an instance. First look in `harness/checks/` and
`harness/errors.py`: if an existing check covers the kind, extend it instead of adding one.

Decide where it belongs:
- visible in the source (a pattern in .py, .xml, .js, .csv): a check in `harness/checks/`;
- visible only at runtime (a log line, a traceback, a Playwright error): an `Entry` in
  `harness/errors.py` with its WHY and HOW TO FIX.

## 2. Write the check

Copy the template and fill it in:

```
cp "${CLAUDE_PLUGIN_ROOT}/skills/add-harness-check/check_template.py" harness/checks/<snake_case_id>.py
```

- `ID`: kebab-case, the kind of mistake (`sudo-on-request-ids`).
- `WHY`: the consequence for users or data, one sentence.
- `FIX`: what to write instead, concrete enough to apply without searching.
- `detect(files)`: return `(path, line, detail)` per occurrence, or
  `(path, line, detail, why, fix)` when the message depends on the occurrence.
  Keep it simple (a regex per line is often enough) and specific (no false positives
  on correct code). For a rule that depends on the Odoo version, read it with
  `hlib.version_tuple(hlib.load_env().get("ODOO_VERSION"))`, as in `odoo_version_api.py`.

## 3. Prove it works

1. Write the smallest file that contains the mistake (in a module of the project, or a
   temporary one) and run `python3 harness/static_checks.py <that file>`: the output must
   show `[<ID>]` with your WHY and HOW TO FIX.
2. Apply the HOW TO FIX to that file and run the same command: no finding.
3. Run `python3 harness/static_checks.py` on the whole project: no false positives. If
   it finds real occurrences, fix them (or record them in PROGRESS.md "Known issues").
4. Delete the temporary file.

## 4. Record it

- Append to `DECISIONS.md`: `- YYYY-MM-DD: New check <ID>: <the kind of mistake> (found in the review of F-xxx).`
- If the check is not specific to this project, add to PROGRESS.md "Next steps":
  `Upstream check <ID> to the odoo-harness plugin.`
- Commit the check with the fix of the instance that revealed it.
