#!/usr/bin/env python3
"""Detect the layout of an Odoo project repository. Standard library only.

    detect_project.py [TARGET]          print what was found (human summary)
    detect_project.py [TARGET] --json   same, as JSON

The repository is a whole Odoo project, not a list of modules. Detection reads:
- addons_path from the project's Odoo config (odoo-stag.conf, odoo-main.conf,
  docker-compose/config/odoo.conf, odoo.conf...) and maps each container path to a
  folder of the repository (/mnt/extra-addons/qafila -> extra-addons/qafila);
- which folders are custom (the project's own code, Claude may edit) and which are
  third-party (OCA and other vendors, read-only); enterprise is outside the repo;
- the Odoo version and image from the Dockerfile (ARG BASE_IMAGE=odoo:19.0, FROM ...);
- the base branch (staging when it exists) and the GitLab project from the origin remote;
- deployment files that the agent must not change (compose files, configs, CI).
Without a config, folders that contain modules are found by scanning the repository.
"""

import argparse
import ast
import configparser
import json
import re
import subprocess
import sys
from pathlib import Path

CONF_CANDIDATES = ("odoo-stag.conf", "odoo-main.conf", "docker-compose/config/odoo.conf",
                   "odoo.conf", "config/odoo.conf", "etc/odoo.conf")
DOCKERFILES = ("Dockerfile", "Dockerfile-stag", "docker/Dockerfile")
THIRD_PARTY_NAMES = {"oca", "third_party", "third-party", "thirdparty", "vendor", "external",
                     "addons-external", "community"}
DEPLOYMENT_GLOBS = ("Dockerfile*", "docker_compose_*.yml", "docker-compose*.yml",
                    "docker-compose*.yaml", "odoo-*.conf", ".gitlab-ci.yml", "Jenkinsfile*",
                    "docker-compose")
SKIP_DIRS = {".git", "harness", "e2e", "node_modules", ".harness", "__pycache__", ".venv",
             "venv", ".claude"}
VERSION_RE = re.compile(r"(?<![\d.])(\d{2})\.0(?![\d])")


def git(target, *args):
    try:
        out = subprocess.run(["git", *args], cwd=target, capture_output=True, text=True,
                             check=True)
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out.stdout.strip()


def module_dirs(folder):
    """Modules directly inside folder (each has a __manifest__.py)."""
    if not folder.is_dir():
        return []
    return sorted(p.parent for p in folder.glob("*/__manifest__.py"))


def manifest(module_dir):
    try:
        return ast.literal_eval((module_dir / "__manifest__.py").read_text())
    except (OSError, ValueError, SyntaxError):
        return {}


def read_addons_path(conf):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(conf.read_text())
    except (OSError, configparser.Error):
        return []
    raw = parser.get("options", "addons_path", fallback="")
    return [p.strip() for p in raw.split(",") if p.strip()]


def map_to_repo(target, container_path):
    """Longest suffix of a container path that is a folder of the repository."""
    parts = [p for p in Path(container_path).parts if p not in ("/", "")]
    for start in range(len(parts)):
        candidate = Path(*parts[start:])
        if (target / candidate).is_dir():
            return candidate.as_posix()
    return None


def scan_addon_roots(target, max_depth=3):
    """Folders holding modules, when the project has no config to read."""
    roots = []

    def walk(folder, depth):
        if depth > max_depth or folder.name in SKIP_DIRS:
            return
        if module_dirs(folder):
            roots.append(folder.relative_to(target).as_posix())
            return
        for child in sorted(p for p in folder.iterdir() if p.is_dir()):
            walk(child, depth + 1)

    for child in sorted(p for p in target.iterdir() if p.is_dir()):
        walk(child, 1)
    return roots


def is_third_party(target, folder):
    name = Path(folder).name.lower()
    if name in THIRD_PARTY_NAMES or "oca" in name.split("-") or "oca" in name.split("_"):
        return True
    mods = module_dirs(target / folder)
    if not mods:
        return False
    oca = [m for m in mods if "Odoo Community Association" in str(manifest(m).get("author", ""))]
    return len(oca) == len(mods)


def detect_version(text):
    match = VERSION_RE.search(text or "")
    return f"{match.group(1)}.0" if match else None


def detect_image(target):
    """(dockerfile, base image, odoo version) from the project's Dockerfile."""
    for name in DOCKERFILES:
        path = target / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        args = dict(re.findall(r"^\s*ARG\s+(\w+)=(\S+)", text, re.M))
        froms = re.findall(r"^\s*FROM\s+(\S+)", text, re.M)
        base = froms[0] if froms else ""
        base = re.sub(r"\$\{?(\w+)\}?", lambda m: args.get(m.group(1), m.group(0)), base)
        return name, base, detect_version(base)
    return "", "", None


def gitlab_remote(target):
    url = git(target, "remote", "get-url", "origin")
    match = (re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", url)
             or re.match(r"^(?:ssh://git@|https?://(?:[^@/]+@)?)([^/:]+)(?::\d+)?/(.+?)(?:\.git)?$",
                         url))
    if not match or "gitlab" not in match.group(1):
        return "", ""
    return f"https://{match.group(1)}", match.group(2)


def base_branch(target):
    for ref in ("origin/staging", "staging"):
        if git(target, "rev-parse", "--verify", "-q", ref):
            return "staging"
    head = git(target, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head.split("/", 1)[1]
    return git(target, "symbolic-ref", "-q", "--short", "HEAD") or "main"


def project_name(target, gitlab_project):
    name = target.name
    if name.lower() in ("git", "src", "repo", "code") and target.parent.name:
        name = target.parent.name
    if gitlab_project:
        name = gitlab_project.rsplit("/", 1)[-1]
    return re.sub(r"[^a-z0-9_-]", "-", name.lower()).strip("-") or "odoo"


def deployment_files(target):
    found = set()
    for pattern in DEPLOYMENT_GLOBS:
        found |= {p.relative_to(target).as_posix() for p in target.glob(pattern)}
    return sorted(found)


def detect(target):
    target = Path(target).resolve()
    warnings = []
    conf = next((target / c for c in CONF_CANDIDATES if (target / c).is_file()), None)
    custom, third, enterprise_seen, unmapped = [], [], False, []
    entries = read_addons_path(conf) if conf else []
    for entry in entries:
        folder = map_to_repo(target, entry)
        if folder is None:
            if "enterprise" in entry.lower():
                enterprise_seen = True
            elif not re.search(r"odoo/addons|site-packages|dist-packages", entry):
                unmapped.append(entry)
            continue
        if folder in custom or folder in third:
            continue
        (third if is_third_party(target, folder) else custom).append(folder)
    if not entries:
        for folder in scan_addon_roots(target):
            (third if is_third_party(target, folder) else custom).append(folder)
        if conf is None:
            warnings.append("no Odoo config with addons_path found: addon folders were found by "
                            "scanning the repository")
    for entry in unmapped:
        warnings.append(f"addons_path entry {entry} matches no folder of the repository")
    enterprise = ""
    if enterprise_seen or (target.parent / "enterprise").is_dir():
        enterprise = "../enterprise"
        if not (target / enterprise).is_dir():
            warnings.append("the project uses Odoo Enterprise but ../enterprise does not exist: "
                            "clone it next to the repository (same branch as the Odoo version)")
    dockerfile, base_image, version = detect_image(target)
    if version is None and conf is not None:
        version = detect_version(conf.read_text(errors="replace"))
    gitlab_url, gitlab_project = gitlab_remote(target)
    modules = {}
    for folder in custom:
        for mod in module_dirs(target / folder):
            modules[mod.name] = f"{folder}/{mod.name}"
    return {
        "root": str(target),
        "config": conf.relative_to(target).as_posix() if conf else "",
        "custom_addons": custom,
        "third_party_addons": third,
        "enterprise_dir": enterprise,
        "odoo_version": version,
        "dockerfile": dockerfile,
        "base_image": base_image,
        "base_branch": base_branch(target),
        "gitlab_url": gitlab_url,
        "gitlab_project": gitlab_project,
        "project_name": project_name(target, gitlab_project),
        "deployment_files": deployment_files(target),
        "custom_modules": modules,
        "warnings": warnings,
    }


def summary(found):
    lines = [f"Odoo project in {found['root']}",
             f"  config read:        {found['config'] or '(none)'}",
             f"  Odoo version:       {found['odoo_version'] or '(unknown)'}"
             f"{' from ' + found['dockerfile'] if found['dockerfile'] else ''}",
             f"  custom addons:      {', '.join(found['custom_addons']) or '(none)'}"
             f"  ({len(found['custom_modules'])} modules)",
             f"  third-party addons: {', '.join(found['third_party_addons']) or '(none)'}"
             "  (read-only)",
             f"  enterprise:         {found['enterprise_dir'] or '(not used)'}",
             f"  base branch:        {found['base_branch']}",
             f"  GitLab project:     {found['gitlab_project'] or '(none)'}",
             f"  deployment files:   {', '.join(found['deployment_files']) or '(none)'}"
             "  (read-only)"]
    lines += [f"  ! {w}" for w in found["warnings"]]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("target", nargs="?", default=".", type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    found = detect(args.target)
    print(json.dumps(found, indent=2) if args.json else summary(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
