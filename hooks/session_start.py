#!/usr/bin/env python3
"""SessionStart: load the harness state into the context, automatically.

Every session (the plugin is installed once per machine):
  - puts the plugin's bin/ on the PATH of Claude's Bash tool (CLAUDE_ENV_FILE), and
    refreshes ~/.odoo-harness/current and the ~/.local/bin/odoo-harness shim;
  - in an Odoo repository without the harness, offers /odoo-harness:init once.
In a repository with the harness: injects the project's Odoo version and guide, the
PROGRESS.md state, the recent decisions, the current feature and the baseline health, and
records a snapshot that the Stop gate compares against. A repository that still carries the
old vendored engine only gets the instruction to migrate it.
"""

import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

MAX_DECISIONS = 10


def feature_summary(root):
    try:
        data = json.loads((root / "feature_list.json").read_text())
        feats = data["features"]
    except (OSError, ValueError, KeyError, TypeError):
        return ["feature_list.json is unreadable. Restore it with `git checkout feature_list.json`."]
    counts = {}
    for f in feats:
        counts[f.get("state")] = counts.get(f.get("state"), 0) + 1
    lines = ["Features: " + (", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "none yet")]
    current = [f for f in feats if f.get("state") == "in_progress"]
    branch = c.git(root, "symbolic-ref", "-q", "--short", "HEAD")
    if current:
        f = current[0]
        task = f" (Odoo task {f['task']})" if f.get("task") else ""
        lines.append(f"Feature in progress: {f['id']} — {f['behavior']}{task}")
        if f.get("task") and branch != f["task"]:
            lines.append(f"  You are on branch '{branch}', not on the task branch "
                         f"'{f['task']}': git checkout {f['task']} before working.")
        lines += [f"  verification: {v}" for v in f.get("verification", [])]
        lines.append(f"It becomes passing only through `odoo-harness feature verify {f['id']}`.")
    else:
        todo = [f for f in feats if f.get("state") == "not_started"]
        if todo:
            task = f" [{todo[0]['task']}]" if todo[0].get("task") else ""
            lines.append(f"No feature in progress. Next by order: {todo[0]['id']}{task} — "
                         f"{todo[0]['behavior']} (`odoo-harness feature start {todo[0]['id']}`).")
        elif not feats:
            lines.append("The feature list is empty: initialization step 4 (task breakdown) "
                         "is not done.")
    return lines


def unchecked_bootstrap(root):
    path = root / "BOOTSTRAP.md"
    if not path.is_file():
        return []
    ready = c.section_text(path.read_text(), "Ready means")
    return [ln.strip() for ln in ready.splitlines() if "[ ]" in ln]


INIT = "/odoo-harness:init"
UPDATE = "/odoo-harness:update"
HARNESS_HOME = Path(os.environ.get("ODOO_HARNESS_HOME") or Path.home() / ".odoo-harness")
OFFERED = HARNESS_HOME / "init-offered.json"
# Bounded look for Odoo modules: never a recursive scan (sessions start anywhere, even ~).
MANIFEST_GLOBS = ("*/__manifest__.py", "*/*/__manifest__.py", "*/*/*/__manifest__.py")
MAX_MANIFESTS = 1


def setup_path(payload):
    """The plugin's command on the PATH of the Bash tool, and the stable path refreshed."""
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        try:
            with open(env_file, "a") as out:
                out.write(f'export PATH="{c.PLUGIN_ROOT / "bin"}:$PATH"\n')
        except OSError:
            pass
    try:
        subprocess.run([sys.executable, str(c.ENGINE_DIR / "cli.py"), "link"],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def odoo_repo_without_harness(launch):
    """The git repository with Odoo modules in `launch` or its git/ folder, or None."""
    for folder in (launch, launch / c.WORKSPACE_REPO):
        if not (folder / ".git").exists() or c.has_harness(folder):
            continue
        manifests = itertools.chain.from_iterable(folder.glob(g) for g in MANIFEST_GLOBS)
        if list(itertools.islice(manifests, MAX_MANIFESTS)):
            return folder
    return None


def offer_init(folder):
    """Context offering init, once per repository (remembered in ~/.odoo-harness)."""
    offered = c.load_json(OFFERED, [])
    if str(folder) in offered:
        return None
    try:
        HARNESS_HOME.mkdir(parents=True, exist_ok=True)
        c.write_json(OFFERED, offered + [str(folder)])
    except OSError:
        pass
    return (f"# odoo-harness\n{folder} is an Odoo repository without the harness. If the user "
            f"wants to work on it with the harness, they can run {INIT} (it detects the "
            "project and asks before installing anything). Mention it once; do not insist.")


def version_key(version):
    return tuple(int(p) for p in version.split(".") if p.isdigit())


def version_context(root):
    env = c.load_env(root)
    version = env.get("ODOO_VERSION", "")
    guide = c.PLUGIN_ROOT / "skills" / "odoo" / "versions" / version / "GUIDE.md"
    lines = [f"Odoo version: {version or 'unknown'}."]
    if guide.is_file():
        lines.append(f"Odoo guide of this version (the `odoo` skill): {guide}. Use it, not "
                     "examples from other versions.")
    else:
        lines.append(f"The harness has no guide for Odoo {version}: check ODOO_VERSION in "
                     "harness/harness.env.")
    engine_version = (c.ENGINE_DIR / "VERSION").read_text().strip()
    pinned = env.get("HARNESS_VERSION", "")
    if pinned and version_key(pinned) > version_key(engine_version):
        lines.append(c.redpen("odoo-harness", f"this project needs odoo-harness {pinned}, this "
                              f"machine has {engine_version}",
                              "An older engine could judge a feature differently, so it refuses "
                              "to run on this project.",
                              "Ask the user to update the plugin: claude plugin update "
                              "odoo-harness@odoo-harness, then /reload-plugins."))
    lines.append("The harness is the `odoo-harness` command (odoo-harness feature | verify | "
                 "init | gitlab | guide | static | map | compose), run from the repository or "
                 "its workspace.")
    return "## Project\n" + "\n".join(lines)


def recent_decisions(root):
    path = root / "DECISIONS.md"
    if not path.is_file():
        return []
    return [ln for ln in path.read_text().splitlines() if ln.startswith("- ")][-MAX_DECISIONS:]


def workspace_context(launch, root):
    """When Claude Code runs in the client workspace, not in the repository itself."""
    rel = root.relative_to(launch).as_posix()
    lines = [f"Claude Code runs in the client workspace {launch}. The Odoo repository is "
             f"`{rel}/`: the custom modules and the harness state files live there, versioned "
             f"in git.",
             f"- `odoo-harness ...` finds `{rel}/` from here. Run git as `git -C {rel} ...`, or "
             f"`cd {rel}` first.",
             f"- Paths in PROGRESS.md, feature_list.json and the red pens are relative to `{rel}/`."]
    enterprise = c.load_env(root).get("ENTERPRISE_DIR", "").strip().rstrip("/")
    if enterprise:
        lines.append(f"- Odoo Enterprise (`{(root / enterprise).resolve()}`) is read-only.")
    bridge = launch / "CLAUDE.md"
    imported = bridge.is_file() and f"@{rel}/CLAUDE.md" in bridge.read_text()
    parts = ["## Workspace\n" + "\n".join(lines)]
    if not imported and (root / "CLAUDE.md").is_file():
        parts = ["## Workspace\n" + "\n".join(lines),
                 f"## {rel}/CLAUDE.md (the project rules, loaded by the harness)\n"
                 + (root / "CLAUDE.md").read_text().strip()]
    return parts


def main():
    payload = c.read_input()
    launch = c.launch_dir(payload)
    setup_path(payload)
    root = c.harness_root(launch)
    if not c.has_harness(root):
        folder = odoo_repo_without_harness(launch)
        offer = offer_init(folder) if folder else None
        if offer:
            c.emit({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                           "additionalContext": offer}})
        sys.exit(0)
    if c.is_legacy(root):
        c.emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": (
            f"# odoo-harness\n{root} still carries a copy of the old harness engine "
            "(harness/feature.py, before 2.0). Tell the user, before any other work, to run "
            f"{UPDATE}: it removes the copy, keeps the state and configuration, and moves the "
            "project to the odoo-harness plugin installed once per machine. Until then the old "
            "per-version plugin drives this repository.")}})

    parts = ["# odoo-harness session context (loaded automatically)", version_context(root)]
    if root != launch:
        parts += workspace_context(launch, root)

    progress = (root / "PROGRESS.md").read_text() if (root / "PROGRESS.md").is_file() else ""
    for name in ("Current state", "In progress", "Known issues", "Next steps"):
        body = c.section_text(progress, name)
        parts.append(f"## PROGRESS.md: {name}\n{body or '(empty)'}")

    parts.append("## Features\n" + "\n".join(feature_summary(root)))

    rc, out = c.run(root, c.engine("feature.py", "check"), timeout=30)
    if rc != 0:
        parts.append("## Feature list integrity: FAILED\n" + out)

    decisions = recent_decisions(root)
    if decisions:
        parts.append(f"## Last {len(decisions)} decisions (DECISIONS.md)\n" + "\n".join(decisions))

    pending = unchecked_bootstrap(root)
    if pending:
        parts.append("## Initialization incomplete (BOOTSTRAP.md, Ready means)\n"
                     + "\n".join(pending)
                     + "\nFeature work starts only after these are done "
                     f"({INIT}).")

    rc, out = c.run(root, c.engine("init.sh", "--check"), timeout=60)
    if rc == 0:
        parts.append("## Baseline health\n" + out)
    else:
        parts.append("## Baseline health: FAILED\n" + out + "\nPer the Work Rules, the baseline "
                     "is fixed first: run `odoo-harness init` and follow its HOW TO FIX lines.")

    session_file = c.state_dir(root) / "session.json"
    previous = c.load_json(session_file, {})
    same_session = (payload.get("source") in ("compact", "resume")
                    and previous.get("session_id") == payload.get("session_id"))
    if not same_session:
        c.write_json(session_file, {
            "session_id": payload.get("session_id"),
            "source": payload.get("source"),
            "start_commit": c.git(root, "rev-parse", "HEAD") or None,
            "progress_body": c.body_without(progress, "Current state"),
            # files already changed before this session: not this session's work
            "dirty_at_start": c.dirty_files(root),
        })

    c.emit({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                   "additionalContext": "\n\n".join(parts)}})


if __name__ == "__main__":
    main()
