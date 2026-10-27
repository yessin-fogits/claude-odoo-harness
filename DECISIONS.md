# Decisions

Append-only. One line per decision: `- YYYY-MM-DD: decision (why)`.

- 2026-10-27: Distribute as a Claude Code plugin + a template installed by `/odoo-harness:init` (shared logic updated in one place, project state stays in the project repo).
- 2026-10-27: One branch per Odoo version (17.0 → 20.0); shared harness changes land on 17.0 and are forward-ported.
- 2026-10-27: Docker Compose runtime with a disposable test DB (`dbfilter` locks the server to it).
- 2026-10-27: Instruction files in English; README and docs in English and French.
- 2026-10-27: No /session-start or /session-end commands; session start and end are automatic (hooks).
- 2026-10-27: Lint with pylint-odoo; e2e with Playwright.
- 2026-10-27: The template installer is a deterministic Python script; it never overwrites state files and merges CLAUDE.md, settings.json and .gitignore.
- 2026-10-27: Red-pen catalog is a Python module (`harness/errors.py`), not errors.yaml: no PyYAML needed on the host, and raw-string regexes are easy for agents to extend.
- 2026-10-27: Verification logic in Python (`harness/verify.py`, standard library only); `harness/verify.sh` is a thin wrapper.
- 2026-10-27: pylint-odoo and Playwright run in pinned containers (compose profile `tools`: `lint`, `e2e`), so every machine lints and tests the same way.
- 2026-10-27: The OCA-only rules manifest-required-author and missing-readme are disabled on the pylint command line (an rc-file `enable=odoolint` overrides any rc-file `disable`).
- 2026-10-27: Evidence integrity by fingerprint (sha256 of id + behavior + verification); changing a passing feature breaks `feature.py check`. `harness/evidence/` is write-denied to the agent.
- 2026-10-27: A feature's verification must include its own e2e test; zero Odoo tests or zero e2e tests count as a failure.
- 2026-10-27: Full e2e suite runs on the baseline, and on a feature verify when the change touches more than one module or shared files (anything outside one module, its e2e test files and docs).
- 2026-10-27: The fresh-DB install (L3) runs on `feature.py verify` only, not on the baseline, to keep `init.sh` fast.
