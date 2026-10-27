# Decisions

Append-only. One line per decision: `- YYYY-MM-DD: decision (why)`.

- 2026-10-27: Distribute as a Claude Code plugin + a template installed by `/odoo-harness:init` (shared logic updated in one place, project state stays in the project repo).
- 2026-10-27: One branch per Odoo version (17.0 → 20.0); shared harness changes land on 17.0 and are forward-ported.
- 2026-10-27: Docker Compose runtime with a disposable test DB (`dbfilter` locks the server to it).
- 2026-10-27: Instruction files in English; README and docs in English and French.
- 2026-10-27: No /session-start or /session-end commands; session start and end are automatic (hooks).
- 2026-10-27: Lint with pylint-odoo; e2e with Playwright.
- 2026-10-27: The template installer is a deterministic Python script; it never overwrites state files and merges CLAUDE.md, settings.json and .gitignore.
