#!/usr/bin/env python3
"""Install or update the odoo-harness files of an Odoo repository.

    install_template.py TARGET [overrides]          first install (layout detected)
    install_template.py TARGET --update             update the project's harness files, and
                                                    migrate a project from the old vendored
                                                    harness (before 2.0)
    install_template.py TARGET --show FILE          print a rendered template file
    install_template.py TARGET --workspace DIR      also clean the files the old harness
                                                    generated in the client workspace DIR
    install_template.py --allow-command             allow `odoo-harness` in the user's Claude
                                                    Code settings (once per machine)

TARGET is the root of an Odoo project repository. Its layout (custom and third-party
addon folders, Odoo Enterprise, Dockerfile, Odoo version, base branch, GitLab project,
deployment files) is detected by detect_project.py; the overrides replace what was detected.

The engine is not copied: it is installed once per machine with the plugin (engine/, run
through the `odoo-harness` command). The repository gets only its state and configuration.

Deterministic and idempotent. Files have an owner:
- state (PROGRESS.md, DECISIONS.md, feature_list.json, BOOTSTRAP.md, ARCHITECTURE.md):
  never overwritten;
- project (harness.env, e2e/conftest.py, .pylintrc...): created once, then the project's;
  --update keeps them and reports when the template changed. HARNESS_VERSION in harness.env
  is raised to the installed engine's version by --update;
- merged (CLAUDE.md block, .claude/settings.json, .gitignore): merged every time. The
  `# This project` section of CLAUDE.md is the project's: added when missing, never changed.

The workspace is the folder Claude Code is started in when it is not the repository
itself: the fogits client folder ~/Project/<client>, with the repository in git/. Nothing is
generated there any more: the hooks find git/ and load its CLAUDE.md themselves.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys
from pathlib import Path

# The Odoo versions the harness supports, with their settings. The project's version is
# data: detected from its Dockerfile, or given with --odoo-version.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
VERSIONS = json.loads((PLUGIN_ROOT / "versions.json").read_text())
ENGINE_VERSION = (PLUGIN_ROOT / "engine" / "VERSION").read_text().strip()
DEFAULT_MARKETPLACE_REPO = "yessin-fogits/claude-odoo-harness"
PLUGIN_ID = "odoo-harness@odoo-harness"
# Plugins of the old one-plugin-per-version layout, and their permission rules.
LEGACY_PLUGIN_RE = re.compile(r"^odoo-harness-\d+@odoo-harness$")
LEGACY_RULE_RE = re.compile(r"^Bash\((?:\S+/)?harness/\w+\.(?:py|sh)[:)]|"
                            r"^Bash\(python3? (?:\S+/)?harness/\w+\.py[:)]")
# The engine files the old harness copied into harness/ (removed by --update).
LEGACY_ENGINE_FILES = [f"harness/{name}" for name in (
    "feature.py", "verify.py", "verify.sh", "init.sh", "lib.sh", "loop.py", "gitlab.py",
    "guide.py", "guide_pdf.py", "project_map.py", "static_checks.py", "errors.py", "hlib.py",
    "docker-compose.yml", "odoo.conf", "checks/model_access.py",
    "checks/no_debug_leftovers.py", "checks/no_hardcoded_secrets.py",
    "checks/odoo_version_api.py", "docker/e2e.Dockerfile", "docker/lint.Dockerfile",
    "e2e_plugins/harness_guide.py")]
# Entries of the old .pre-commit-config.yaml that ran the vendored scripts.
LEGACY_PRECOMMIT = {"entry: python3 harness/feature.py check": "entry: odoo-harness feature check",
                    "entry: python3 harness/static_checks.py": "entry: odoo-harness static"}
WORKSPACE_BLOCK_RE = re.compile(r"<!-- odoo-harness:start -->.*?<!-- odoo-harness:end -->\n?",
                                re.S)

TEMPLATE_DIR = PLUGIN_ROOT / "template"
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
    p.add_argument("target", type=Path, nargs="?", help="root of the Odoo repository")
    p.add_argument("--odoo-version", help=f"Odoo version of the project ({', '.join(VERSIONS)}; "
                   "default: detected from its Dockerfile)")
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
    p.add_argument("--workspace", type=Path, help="client workspace containing the repository "
                   "(~/Project/<client> for TARGET ~/Project/<client>/git): remove the files the "
                   "old harness generated there")
    p.add_argument("--allow-command", action="store_true",
                   help="add Bash(odoo-harness:*) to the user's Claude Code settings and exit")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true",
                      help="overwrite every existing file except state files")
    mode.add_argument("--update", action="store_true",
                      help="update the harness files, keep project and state files")
    mode.add_argument("--show", metavar="FILE", help="print the rendered template of FILE")
    args = p.parse_args(argv)
    if args.target is None and not args.allow_command:
        p.error("TARGET is required")
    return args


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
    if args.update and not existing:
        raise SystemExit(f"{target / HARNESS_ENV} not found: --update needs an installed "
                         "harness (run the init skill first)")
    found = detect_project.detect(target)
    version = existing.get("ODOO_VERSION")
    if version and args.odoo_version and args.odoo_version != version:
        raise SystemExit(
            f"this project targets Odoo {version}: moving it to {args.odoo_version} is a "
            "version migration, not an update. Change ODOO_VERSION and ODOO_IMAGE in "
            "harness/harness.env and follow references/migrations.md of the odoo skill.")
    version = version or args.odoo_version or found["odoo_version"]
    if not version:
        raise SystemExit("the Odoo version of this project was not detected (no Dockerfile "
                         f"FROM odoo:<version>): pass --odoo-version ({', '.join(VERSIONS)})")
    if version not in VERSIONS:
        raise SystemExit(f"Odoo {version} is not supported by the harness "
                         f"(supported: {', '.join(VERSIONS)})")

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
        image = f"{name}-odoo:local" if dockerfile else f"odoo:{version}"
    pinned = existing.get("HARNESS_VERSION", "")
    if args.update and version_tuple(pinned) > version_tuple(ENGINE_VERSION):
        raise SystemExit(f"this project needs odoo-harness {pinned} and the plugin is "
                         f"{ENGINE_VERSION}: update the plugin first (claude plugin update "
                         f"{PLUGIN_ID})")
    return target, {
        "HARNESS_VERSION": ENGINE_VERSION,
        "ODOO_VERSION": version,
        "ODOO_IMAGE": image,
        "ODOO_DOCKERFILE": dockerfile,
        "POSTGRES_IMAGE": existing.get("POSTGRES_IMAGE", VERSIONS[version]["postgres_image"]),
        "CUSTOM_ADDONS": custom,
        "THIRD_PARTY_ADDONS": third,
        "ENTERPRISE_DIR": enterprise,
        "TEST_DB": test_db,
        "ODOO_PORT": pick(args.port, "ODOO_PORT", "18069"),
        "BASE_BRANCH": pick(args.base_branch, "BASE_BRANCH", found["base_branch"]),
        "GITLAB_URL": pick(None, "GITLAB_URL", found["gitlab_url"]),
        "GITLAB_PROJECT": pick(None, "GITLAB_PROJECT", found["gitlab_project"]),
        "PROTECTED_PATHS": pick(None, "PROTECTED_PATHS", ",".join(found["deployment_files"])),
        "PROJECT_NAME": name,
        "MARKETPLACE_REPO": args.marketplace_repo,
        "PLUGIN_ID": PLUGIN_ID,
        "DATE": datetime.date.today().isoformat(),
        "DETECTED": detect_project.summary(found),
    }


def version_tuple(version):
    """'2.0.1' -> (2, 0, 1); '' -> ()."""
    parts = []
    for part in str(version or "").split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


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


def workspace_dir(target, workspace):
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace {workspace} is not a directory")
    if not target.is_relative_to(workspace) or target == workspace:
        raise SystemExit(f"the repository {target} is not inside the workspace {workspace}")
    return workspace


def clean_workspace(target, workspace):
    """Remove what the old harness generated in the workspace: the CLAUDE.md block that
    imported the repository's rules, and its permission rules and plugin in settings.json.
    The hooks find the repository and load its CLAUDE.md themselves now."""
    workspace = workspace_dir(target, workspace)
    report = []
    claude = workspace / CLAUDE_MD
    if claude.is_file() and WORKSPACE_BLOCK_RE.search(claude.read_text()):
        rest = WORKSPACE_BLOCK_RE.sub("", claude.read_text()).strip()
        if rest:
            claude.write_text(rest + "\n")
            report.append(("cleaned", f"{claude}"))
        else:
            claude.unlink()
            report.append(("removed", f"{claude}"))
    settings = workspace / SETTINGS
    if settings.is_file():
        current = json.loads(settings.read_text())
        cleaned = without_legacy(current)
        if cleaned != current:
            if cleaned:
                settings.write_text(json.dumps(cleaned, indent=2) + "\n")
                report.append(("cleaned", f"{settings}"))
            else:
                settings.unlink()
                report.append(("removed", f"{settings}"))
    return report


def without_legacy(settings):
    """Settings without the old per-version plugins and the rules of the vendored scripts."""
    out = json.loads(json.dumps(settings))
    plugins = out.get("enabledPlugins", {})
    for key in [k for k in plugins if LEGACY_PLUGIN_RE.match(k)]:
        del plugins[key]
    perms = out.get("permissions", {})
    for key, rules in perms.items():
        perms[key] = [r for r in rules if not LEGACY_RULE_RE.match(r)]
    for parent in ("enabledPlugins", "permissions"):
        if parent in out:
            out[parent] = {k: v for k, v in out[parent].items() if v != []}
            if not out[parent]:
                del out[parent]
    if not out.get("enabledPlugins") and "odoo-harness" in out.get("extraKnownMarketplaces", {}):
        del out["extraKnownMarketplaces"]["odoo-harness"]
        if not out["extraKnownMarketplaces"]:
            del out["extraKnownMarketplaces"]
    return out


def migrate_legacy(target):
    """Remove the engine copy of the old vendored harness and rewrite its pre-commit
    entries. State and configuration are kept. Returns (action, path) pairs."""
    report = []
    for rel in LEGACY_ENGINE_FILES:
        path = target / rel
        if path.is_file():
            path.unlink()
            report.append(("removed", rel))
    for folder in ("harness/docker", "harness/e2e_plugins", "harness/__pycache__",
                   "harness/checks/__pycache__", "harness/e2e_plugins/__pycache__"):
        path = target / folder
        if path.is_dir():
            shutil.rmtree(path) if path.name == "__pycache__" else (
                path.rmdir() if not any(path.iterdir()) else None)
    precommit = target / ".pre-commit-config.yaml"
    if precommit.is_file():
        text = precommit.read_text()
        new = text
        for old, replacement in LEGACY_PRECOMMIT.items():
            new = new.replace(old, replacement)
        if new != text:
            precommit.write_text(new)
            report.append(("migrated", ".pre-commit-config.yaml"))
    return report


def raise_pin(target):
    """HARNESS_VERSION in harness.env becomes the installed engine's version (never lower)."""
    env_file = target / HARNESS_ENV
    current = read_env(env_file).get("HARNESS_VERSION", "")
    if version_tuple(current) >= version_tuple(ENGINE_VERSION):
        return ("kept", HARNESS_ENV)
    text = re.sub(r"^HARNESS_VERSION=.*$", f"HARNESS_VERSION={ENGINE_VERSION}",
                  env_file.read_text(), flags=re.M)
    env_file.write_text(text)
    return ("merged", HARNESS_ENV)


def allow_command(settings_file):
    """Bash(odoo-harness:*) in the user's settings, so no workspace needs its own rules."""
    rule = "Bash(odoo-harness:*)"
    current = json.loads(settings_file.read_text()) if settings_file.is_file() else {}
    allow = current.setdefault("permissions", {}).setdefault("allow", [])
    if rule in allow:
        return ("kept", str(settings_file))
    allow.append(rule)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(current, indent=2) + "\n")
    return ("merged", str(settings_file))


def merge_settings(dest, content):
    """Union the harness permissions and plugin settings into existing settings, without
    the old per-version plugins and vendored-script rules."""
    current = json.loads(dest.read_text())
    harness = json.loads(content)
    merged = without_legacy(current)
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


def user_settings_file():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def main(argv=None):
    args = parse_args(argv)
    if args.allow_command:
        action, path = allow_command(user_settings_file())
        print(f"{action:8} {path}")
        return 0
    target, ctx = build_context(args)
    if args.show:
        src = TEMPLATE_DIR / ("gitignore" if args.show == ".gitignore" else args.show)
        if not src.is_file():
            raise SystemExit(f"{args.show} is not a template file")
        sys.stdout.write(render(src.read_text(), ctx))
        return 0
    report = migrate_legacy(target) if args.update else []
    report += install(target, ctx, force=args.force, update=args.update)
    if args.update:
        report.append(raise_pin(target))
    if args.workspace:
        report += clean_workspace(target, args.workspace)
    if not args.update:
        print(ctx["DETECTED"] + "\n")
    for action, rel in report:
        print(f"{action:8} {rel}")
    if args.update:
        print(f"\nodoo-harness files updated for Odoo {ctx['ODOO_VERSION']} in {target} "
              f"(engine {ENGINE_VERSION})")
        if any(action == "removed" and rel.startswith("harness/") for action, rel in report):
            print("removed: the copy of the old harness engine; the plugin's odoo-harness "
                  "command runs it now.")
        if any(action == "kept*" for action, _ in report):
            print("kept*: a project file was kept but the template changed. Compare with:\n"
                  f"  python3 {Path(__file__).resolve()} . --show <file>")
    else:
        print(f"\nodoo-harness installed for Odoo {ctx['ODOO_VERSION']} in {target} "
              f"(engine {ENGINE_VERSION})")
        print("Next: run odoo-harness init (initialization step 1).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
