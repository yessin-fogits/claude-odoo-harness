# Shared Odoo modules: {{NAME}}

This repository holds Odoo modules shared by several projects. Each project includes it as a
git submodule (for example `extra-addons/{{NAME}}`) and pins a commit of its `.gitmodules`
branch. A change here reaches every project that uses it the day that project moves its
pointer: the other projects get your change without having asked for it.

- Work on these modules from a project that uses them: its harness verifies the change with
  its own modules (`odoo-harness feature verify`) and ships it (`odoo-harness gitlab mr <task>`
  opens this repository's merge request, then the project's).
- Commit here first, with the task's message (`[T2003] F-T2003-1 <behavior>`), then commit
  the new pointer in the project.
- Keep every change backward compatible. Never rename or remove a field, a method, an XML id,
  a menu or a view that a project may use: add new ones instead. A change of behavior that
  users would see stays off by default, behind a setting.
- Record each decision about these modules in `DECISIONS.md`, with its task. Keep
  `ARCHITECTURE.md` current when a module, a model or a dependency changes.
