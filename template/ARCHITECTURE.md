# Architecture

Map of this Odoo project for the people and agents who work on it. Written at
initialization (discovery) from `harness/project_map.py` and from reading the code;
updated when a feature adds a module, a model or a dependency between modules.

## The project
<!-- Who the client is, what the business does, what Odoo is used for (apps, flows). -->
- Odoo {{ODOO_VERSION}}, custom modules in `{{CUSTOM_ADDONS}}`, third-party addons in `{{THIRD_PARTY_ADDONS}}` (read-only), Odoo Enterprise in `{{ENTERPRISE_DIR}}` (read-only).

## Runtime and deployment
<!-- How the project runs: Dockerfile, deployment compose files and configs, CI, branches.
     These files are changed by a human (PROTECTED_PATHS). -->
- Git flow: task branches `T<code>` → merge request to `{{BASE_BRANCH}}` → `main`.

## Modules
<!-- One line per custom module: what it does for the user, in plain words. Then the facts
     from `harness/project_map.py` (models, dependencies, tests). -->

## Dependencies between custom modules
<!-- The mermaid graph from harness/project_map.py, and what to watch when changing a module
     others depend on. -->

## Risks and debt
<!-- From discovery: modules without tests, version problems, hard-coded secrets, findings of
     `harness/static_checks.py --all`. Each item is either a feature in feature_list.json or a
     known issue in PROGRESS.md. -->
