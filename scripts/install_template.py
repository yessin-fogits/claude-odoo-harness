#!/usr/bin/env python3
"""Install the odoo-harness template into an Odoo repository.

Deterministic and idempotent: it fills the template placeholders, never
overwrites project state (PROGRESS.md, DECISIONS.md, feature_list.json), and
merges the harness block into an existing CLAUDE.md instead of replacing it.
"""

import argparse
import datetime
import json
import re
import shutil
import stat
import sys
from pathlib import Path

# The Odoo version this branch of the harness targets.
ODOO_VERSION = "17.0"
POSTGRES_IMAGE = "postgres:16"
DEFAULT_MARKETPLACE_REPO = "yessin-fogits/claude-odoo-harness"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"

# Files holding project state: created once, never overwritten.
STATE_FILES = {"PROGRESS.md", "DECISIONS.md", "feature_list.json", "BOOTSTRAP.md"}
# Files merged into the target instead of copied.
CLAUDE_MD = "CLAUDE.md"
SETTINGS = ".claude/settings.json"
GITIGNORE_FRAGMENT = "gitignore"
BLOCK_RE = re.compile(r"<!-- odoo-harness:start -->.*?<!-- odoo-harness:end -->\n?", re.S)

MODULES_RE = re.compile(r"^([a-z0-9_]+(,[a-z0-9_]+)*)?$")
DB_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("target", type=Path, help="root of the Odoo repository")
    p.add_argument("--modules", default="", help="comma-separated custom modules in scope")
    p.add_argument("--addons-dir", default="addons", help="custom addons dir, relative to target")
    p.add_argument("--test-db", default="harness_test")
    p.add_argument("--port", type=int, default=8069)
    p.add_argument("--project-name", default=None, help="docker compose project name")
    p.add_argument("--marketplace-repo", default=DEFAULT_MARKETPLACE_REPO)
    p.add_argument("--force", action="store_true",
                   help="overwrite existing harness files (never state files)")
    return p.parse_args(argv)


def build_context(args):
    target = args.target.resolve()
    modules = args.modules.replace(" ", "")
    if not MODULES_RE.match(modules):
        raise SystemExit(f"invalid --modules {args.modules!r}: expected 'mod_a,mod_b'")
    if not DB_RE.match(args.test_db):
        raise SystemExit(f"invalid --test-db {args.test_db!r}: letters, digits and _ only")
    addons_dir = args.addons_dir.strip().removeprefix("./").rstrip("/")
    if not addons_dir or Path(addons_dir).is_absolute() or ".." in Path(addons_dir).parts:
        raise SystemExit(f"invalid --addons-dir {args.addons_dir!r}: must be inside the repository")
    project = args.project_name or re.sub(r"[^a-z0-9_-]", "-", target.name.lower()).strip("-")
    return target, {
        "ODOO_VERSION": ODOO_VERSION,
        "ODOO_IMAGE": f"odoo:{ODOO_VERSION}",
        "POSTGRES_IMAGE": POSTGRES_IMAGE,
        "MODULES": modules,
        "ADDONS_DIR": addons_dir,
        "TEST_DB": args.test_db,
        "ODOO_PORT": str(args.port),
        "PROJECT_NAME": project or "odoo-harness",
        "MARKETPLACE_REPO": args.marketplace_repo,
        "DATE": datetime.date.today().isoformat(),
    }


def render(text, ctx):
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: ctx[m.group(1)], text)


def install(target, ctx, force=False):
    """Install the template into target. Returns a list of (action, relpath)."""
    if not target.is_dir():
        raise SystemExit(f"target {target} is not a directory")
    report = []
    for src in sorted(TEMPLATE_DIR.rglob("*")):
        rel = src.relative_to(TEMPLATE_DIR)
        if src.is_dir() or "__pycache__" in rel.parts:
            continue
        content = render(src.read_text(), ctx)
        if rel.as_posix() == GITIGNORE_FRAGMENT:
            report.append(merge_gitignore(target / ".gitignore", content))
            continue
        dest = target / rel
        if rel.as_posix() == CLAUDE_MD and dest.exists():
            report.append(merge_claude_md(dest, content))
            continue
        if rel.as_posix() == SETTINGS and dest.exists():
            report.append(merge_settings(dest, content))
            continue
        if dest.exists() and (rel.as_posix() in STATE_FILES or not force):
            report.append(("kept", rel.as_posix()))
            continue
        action = "updated" if dest.exists() else "created"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        shutil.copymode(src, dest)
        if rel.parent.as_posix() == "harness" and dest.suffix in {".sh", ".py"}:
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        report.append((action, rel.as_posix()))
    (target / ctx["ADDONS_DIR"]).mkdir(parents=True, exist_ok=True)
    return report


def merge_claude_md(dest, block):
    current = dest.read_text()
    if BLOCK_RE.search(current):
        new = BLOCK_RE.sub(lambda _: block, current, count=1)
    else:
        new = current.rstrip("\n") + "\n\n" + block
    if new == current:
        return ("kept", CLAUDE_MD)
    dest.write_text(new)
    return ("merged", CLAUDE_MD)


def merge_settings(dest, content):
    """Union the harness permissions and plugin settings into existing settings."""
    current = json.loads(dest.read_text())
    harness = json.loads(content)
    merged = json.loads(json.dumps(current))
    perms = merged.setdefault("permissions", {})
    for key, rules in harness["permissions"].items():
        existing = perms.setdefault(key, [])
        existing.extend(r for r in rules if r not in existing)
    for key in ("extraKnownMarketplaces", "enabledPlugins"):
        merged.setdefault(key, {}).update(harness[key])
    if merged == current:
        return ("kept", SETTINGS)
    dest.write_text(json.dumps(merged, indent=2) + "\n")
    return ("merged", SETTINGS)


def merge_gitignore(dest, fragment):
    current = dest.read_text() if dest.exists() else ""
    missing = [line for line in fragment.splitlines()
               if line and line not in current.splitlines()]
    if not missing:
        return ("kept", ".gitignore")
    sep = "" if not current or current.endswith("\n") else "\n"
    dest.write_text(current + sep + "\n".join(missing) + "\n")
    return ("merged", ".gitignore")


def main(argv=None):
    args = parse_args(argv)
    target, ctx = build_context(args)
    for action, rel in install(target, ctx, force=args.force):
        print(f"{action:8} {rel}")
    print(f"\nodoo-harness installed for Odoo {ODOO_VERSION} in {target}")
    print("Next: run harness/init.sh (initialization step 1).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
