#!/usr/bin/env python3
"""Install or update the odoo-harness template in an Odoo repository.

    install_template.py TARGET [overrides]          first install (layout detected)
    install_template.py TARGET --update             update the harness files
    install_template.py TARGET --show FILE          print a rendered template file
    install_template.py TARGET --workspace DIR      also write the workspace files in DIR
    install_template.py TARGET --workspace DIR --workspace-only
                                                    only the workspace files (fresh clone)

TARGET is the root of an Odoo project repository. Its layout (custom and third-party
addon folders, Odoo Enterprise, Dockerfile, base branch, GitLab project, deployment
files) is detected by detect_project.py; the overrides replace what was detected.

Deterministic and idempotent. Files have an owner:
- state (PROGRESS.md, DECISIONS.md, feature_list.json, BOOTSTRAP.md, ARCHITECTURE.md):
  never overwritten;
- project (harness.env, e2e/conftest.py, .pylintrc...): created once, then the project's;
  --update keeps them and reports when the template changed;
- harness (harness/*.py, *.sh, checks, docker files, harness/docker-compose.yml,
  harness/odoo.conf): replaced by --update, rendered from harness.env;
- merged (CLAUDE.md block, .claude/settings.json, .gitignore): merged every time. The
  `# This project` section of CLAUDE.md is the project's: added when missing, never changed.

The workspace is the folder Claude Code is started in when it is not the repository
itself: the fogits client folder ~/Project/<client>, with the repository in git/ and
Odoo Enterprise in enterprise/. It gets a CLAUDE.md that imports the repository's
CLAUDE.md and a .claude/settings.json with the same permissions, rooted at the
repository, and the plugin enabled. Both are merged every time and are not versioned:
the harness itself stays in the repository.
"""

import argparse
import datetime
import json
import re
import shutil
import stat
import sys
from pathlib import Path

# The Odoo version this branch of the harness targets: the only per-branch file.
_BRANCH = json.loads((Path(__file__).resolve().parent.parent / "odoo_version.json").read_text())
ODOO_VERSION = _BRANCH["odoo_version"]
POSTGRES_IMAGE = _BRANCH["postgres_image"]
DEFAULT_MARKETPLACE_REPO = "yessin-fogits/claude-odoo-harness"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"
WORKSPACE_TEMPLATE = Path(__file__).resolve().parent.parent / "workspace" / "CLAUDE.md"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect_project  # noqa: E402

STATE_FILES = {"PROGRESS.md", "DECISIONS.md", "feature_list.json", "BOOTSTRAP.md", "ARCHITECTURE.md"}
PROJECT_FILES = {".pylintrc", ".pre-commit-config.yaml", "e2e/conftest.py", "e2e/test_smoke.py",
                 "harness/harness.env", "harness/errors_project.py"}
HARNESS_ENV = "harness/harness.env"
CLAUDE_MD = "CLAUDE.md"
SETTINGS = ".claude/settings.json"
GITIGNORE_FRAGMENT = "gitignore"
BLOCK_RE = re.compile(r"<!-- odoo-harness:start -->.*?<!-- odoo-harness:end -->\n?", re.S)
PROJECT_SECTION_RE = re.compile(r"^# This project\s*$", re.M)

DB_RE = re.compile(r"^[a-zA-Z0-9_]+$")
ENV_KEY_RE = re.compile(r"^([A-Z_]+)=(.*)$")


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("target", type=Path, help="root of the Odoo repository")
    p.add_argument("--custom-addons", help="comma-separated folders of the project's modules")
    p.add_argument("--third-party-addons", help="comma-separated read-only addon folders (OCA...)")
    p.add_argument("--enterprise-dir", help="Odoo Enterprise checkout, relative to target "
                   "(default: ../enterprise when the project uses it); '' for none")
    p.add_argument("--dockerfile", help="project Dockerfile the test image is built from; '' "
                   "to use the plain odoo:<version> image")
    p.add_argument("--base-branch", help="branch task branches start from (default: staging)")
    p.add_argument("--test-db", help="disposable test database (default: harness_test)")
    p.add_argument("--port", type=int, help="host port of the harness Odoo (default: 18069)")
    p.add_argument("--project-name", help="docker compose project name")
    p.add_argument("--marketplace-repo", default=DEFAULT_MARKETPLACE_REPO)
    p.add_argument("--workspace", type=Path, help="folder Claude Code is started in, when it "
                   "contains the repository (~/Project/<client> for TARGET ~/Project/<client>/git)")
    p.add_argument("--workspace-only", action="store_true",
                   help="only write the workspace files (an already installed harness)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true",
                      help="overwrite every existing file except state files")
    mode.add_argument("--update", action="store_true",
                      help="update the harness files, keep project and state files")
    mode.add_argument("--show", metavar="FILE", help="print the rendered template of FILE")
    return p.parse_args(argv)


def read_env(path):
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            match = ENV_KEY_RE.match(line.strip())
            if match:
                values[match.group(1)] = match.group(2).strip()
    return values


def clean_paths(raw, what, allow_outside=False):
    out = []
    for item in (raw or "").split(","):
        item = item.strip().removeprefix("./").rstrip("/")
        if not item:
            continue
        if Path(item).is_absolute() or (".." in Path(item).parts and not allow_outside):
            raise SystemExit(f"invalid {what} {item!r}: must be a path inside the repository")
        out.append(item)
    return ",".join(out)


def build_context(args):
    target = args.target.resolve()
    existing = read_env(target / HARNESS_ENV)
    if args.update:
        if not existing:
            raise SystemExit(f"{target / HARNESS_ENV} not found: --update needs an installed "
                             "harness (run the init skill first)")
        if existing.get("ODOO_VERSION") != ODOO_VERSION:
            raise SystemExit(
                f"this project targets Odoo {existing.get('ODOO_VERSION')} and this plugin "
                f"Odoo {ODOO_VERSION}: that is a version migration, not an update. Update with "
                f"the odoo-harness plugin of Odoo {existing.get('ODOO_VERSION')}.")
    found = detect_project.detect(target)
    if not existing and found["odoo_version"] and found["odoo_version"] != ODOO_VERSION:
        raise SystemExit(
            f"this project runs Odoo {found['odoo_version']} ({found['dockerfile']}) and this "
            f"plugin is for Odoo {ODOO_VERSION}: install odoo-harness-"
            f"{found['odoo_version'].split('.')[0]}@odoo-harness instead.")

    def pick(arg, key, detected):
        """Command line, then the installed harness.env, then detection."""
        if arg is not None:
            return str(arg)
        return existing[key] if key in existing else detected

    # Harnesses installed before full-project mode had ADDONS_DIR.
    custom = clean_paths(pick(args.custom_addons, "CUSTOM_ADDONS",
                              existing.get("ADDONS_DIR") or ",".join(found["custom_addons"])
                              or "addons"), "--custom-addons")
    third = clean_paths(pick(args.third_party_addons, "THIRD_PARTY_ADDONS",
                             ",".join(found["third_party_addons"])), "--third-party-addons")
    enterprise = clean_paths(pick(args.enterprise_dir, "ENTERPRISE_DIR", found["enterprise_dir"]),
                             "--enterprise-dir", allow_outside=True)
    dockerfile = clean_paths(pick(args.dockerfile, "ODOO_DOCKERFILE", found["dockerfile"]),
                             "--dockerfile")
    name = pick(args.project_name, "COMPOSE_PROJECT_NAME", f"{found['project_name']}-harness")
    test_db = pick(args.test_db, "TEST_DB", "harness_test")
    if not DB_RE.match(test_db):
        raise SystemExit(f"invalid --test-db {test_db!r}: letters, digits and _ only")
    image = existing.get("ODOO_IMAGE", "")
    if not image or (dockerfile and image.startswith("odoo:")):
        # never build the project's Dockerfile into an official image name
        image = f"{name}-odoo:local" if dockerfile else f"odoo:{ODOO_VERSION}"
    mounts = [f"/mnt/repo/{p}" for p in (custom + "," + third).split(",") if p]
    if enterprise:
        mounts.append("/mnt/enterprise")
    major = int(ODOO_VERSION.split(".")[0])
    return target, {
        "ODOO_VERSION": ODOO_VERSION,
        "ODOO_IMAGE": image,
        "ODOO_DOCKERFILE": dockerfile,
        "POSTGRES_IMAGE": existing.get("POSTGRES_IMAGE", POSTGRES_IMAGE),
        "CUSTOM_ADDONS": custom,
        "THIRD_PARTY_ADDONS": third,
        "ENTERPRISE_DIR": enterprise,
        "ADDONS_PATH": ",".join(mounts),
        "DEMO_OPTION": "with_demo = True" if major >= 19 else "without_demo = False",
        "TEST_DB": test_db,
        "ODOO_PORT": pick(args.port, "ODOO_PORT", "18069"),
        "BASE_BRANCH": pick(args.base_branch, "BASE_BRANCH", found["base_branch"]),
        "GITLAB_URL": pick(None, "GITLAB_URL", found["gitlab_url"]),
        "GITLAB_PROJECT": pick(None, "GITLAB_PROJECT", found["gitlab_project"]),
        "PROTECTED_PATHS": pick(None, "PROTECTED_PATHS", ",".join(found["deployment_files"])),
        "PROJECT_NAME": name,
        "MARKETPLACE_REPO": args.marketplace_repo,
        "PLUGIN_ID": f"odoo-harness-{major}@odoo-harness",
        "ODOO_MAJOR": str(major),
        "DATE": datetime.date.today().isoformat(),
        "DETECTED": detect_project.summary(found),
    }


def render(text, ctx):
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: ctx[m.group(1)], text)


def template_files():
    for src in sorted(TEMPLATE_DIR.rglob("*")):
        rel = src.relative_to(TEMPLATE_DIR)
        if src.is_file() and "__pycache__" not in rel.parts:
            yield src, rel.as_posix()


def install(target, ctx, force=False, update=False):
    """Install or update the template in target. Returns a list of (action, relpath)."""
    if not target.is_dir():
        raise SystemExit(f"target {target} is not a directory")
    report = []
    for src, rel in template_files():
        content = render(src.read_text(), ctx)
        if rel == GITIGNORE_FRAGMENT:
            report.append(merge_gitignore(target / ".gitignore", content))
            continue
        dest = target / rel
        if dest.exists():
            if rel == CLAUDE_MD:
                report.append(merge_claude_md(dest, content))
                continue
            if rel == SETTINGS:
                report.append(merge_settings(dest, content))
                continue
            if rel in STATE_FILES:
                report.append(("kept", rel))
                continue
            if update and rel == HARNESS_ENV:
                report.append(merge_env(dest, content))
                continue
            if update and rel in PROJECT_FILES:
                report.append(("kept*" if dest.read_text() != content else "kept", rel))
                continue
            if not (force or update):
                report.append(("kept", rel))
                continue
            if dest.read_text() == content:
                report.append(("kept", rel))
                continue
        action = "updated" if dest.exists() else "created"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        shutil.copymode(src, dest)
        if Path(rel).parent.as_posix() == "harness" and dest.suffix in {".sh", ".py"}:
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        report.append((action, rel))
    for folder in ctx["CUSTOM_ADDONS"].split(","):
        (target / folder).mkdir(parents=True, exist_ok=True)
    return report


def merge_claude_md(dest, content, name=CLAUDE_MD):
    """Replace the harness block; add the project section only when it is missing."""
    match = BLOCK_RE.search(content)
    block, section = match.group(0), content[match.end():].strip("\n")
    current = dest.read_text()
    if section and not PROJECT_SECTION_RE.search(current):
        block = block.rstrip("\n") + "\n\n" + section + "\n"
    if BLOCK_RE.search(current):
        new = BLOCK_RE.sub(lambda _: block, current, count=1)
    else:
        new = current.rstrip("\n") + "\n\n" + block
    if new == current:
        return ("kept", name)
    dest.write_text(new)
    return ("merged", name)


def workspace_repo(target, workspace):
    """The repository's path relative to the workspace (`git` in the fogits layout)."""
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace {workspace} is not a directory")
    try:
        rel = target.relative_to(workspace)
    except ValueError:
        raise SystemExit(f"the repository {target} is not inside the workspace {workspace}")
    if not rel.parts:
        raise SystemExit("the workspace is the repository itself: no --workspace needed")
    return workspace, rel.as_posix()


def workspace_rule(rule, rel):
    """A repository permission rule, as seen from the workspace."""
    tool, _, arg = rule.partition("(")
    arg = arg.removesuffix(")")
    if tool == "Bash" and arg.startswith("harness/"):
        return [f"Bash({rel}/{arg})"]
    if tool == "Bash" and arg.startswith("git "):
        return [rule, f"Bash(git -C {rel} {arg[4:]})"]
    if tool in ("Edit", "Read", "Write"):
        return [f"{tool}({rel}/{arg})"]
    return [rule]


def install_workspace(target, workspace, ctx):
    """CLAUDE.md and .claude/settings.json of the workspace. Returns (action, path) pairs."""
    workspace, rel = workspace_repo(target, workspace)
    note = "not used"
    if ctx["ENTERPRISE_DIR"]:
        enterprise = (target / ctx["ENTERPRISE_DIR"]).resolve()
        where = enterprise.relative_to(workspace) if enterprise.is_relative_to(workspace) \
            else enterprise
        note = f"`{where}/`, read-only"
    wctx = {**ctx, "REPO_DIR": rel, "ENTERPRISE_NOTE": note}
    report = []
    block = render(WORKSPACE_TEMPLATE.read_text(), wctx)
    dest = workspace / CLAUDE_MD
    if dest.exists():
        action, _ = merge_claude_md(dest, block)
    else:
        dest.write_text(block)
        action = "created"
    report.append((action, f"{workspace}/{CLAUDE_MD}"))

    settings = json.loads(render((TEMPLATE_DIR / SETTINGS).read_text(), ctx))
    settings["permissions"] = {
        key: [r for rule in rules for r in workspace_rule(rule, rel)]
        for key, rules in settings["permissions"].items()}
    content = json.dumps(settings, indent=2) + "\n"
    dest = workspace / SETTINGS
    if dest.exists():
        action, _ = merge_settings(dest, content)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        action = "created"
    report.append((action, f"{workspace}/{SETTINGS}"))
    return report


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


def merge_env(dest, content):
    """Keep the project's values; append settings the template added since (with comments)."""
    current = dest.read_text()
    present = set(read_env(dest))
    additions, comments = [], []
    for line in content.splitlines():
        match = ENV_KEY_RE.match(line.strip())
        if match and match.group(1) not in present:
            additions += comments + [line]
        comments = comments + [line] if line.startswith("#") else []
    if not additions:
        return ("kept", HARNESS_ENV)
    sep = "" if current.endswith("\n") else "\n"
    dest.write_text(current + sep + "\n".join(additions) + "\n")
    return ("merged", HARNESS_ENV)


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
    if args.show:
        src = TEMPLATE_DIR / ("gitignore" if args.show == ".gitignore" else args.show)
        if not src.is_file():
            raise SystemExit(f"{args.show} is not a template file")
        sys.stdout.write(render(src.read_text(), ctx))
        return 0
    if args.workspace_only:
        if not args.workspace:
            raise SystemExit("--workspace-only needs --workspace DIR")
        if not (target / HARNESS_ENV).is_file():
            raise SystemExit(f"{target / HARNESS_ENV} not found: install the harness first "
                             "(the init skill)")
        for action, rel in install_workspace(target, args.workspace, ctx):
            print(f"{action:8} {rel}")
        return 0
    report = install(target, ctx, force=args.force, update=args.update)
    if args.workspace:
        report += install_workspace(target, args.workspace, ctx)
    if not args.update:
        print(ctx["DETECTED"] + "\n")
    for action, rel in report:
        print(f"{action:8} {rel}")
    if args.update:
        print(f"\nodoo-harness files updated for Odoo {ODOO_VERSION} in {target}")
        if any(action == "kept*" for action, _ in report):
            print("kept*: a project file was kept but the template changed. Compare with:\n"
                  f"  python3 {Path(__file__).resolve()} . --show <file>")
    else:
        print(f"\nodoo-harness installed for Odoo {ODOO_VERSION} in {target}")
        print("Next: run harness/init.sh (initialization step 1).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
