#!/usr/bin/env python3
"""Facts about the project's modules, read from the code (no Odoo, no Docker).

    harness/project_map.py              markdown: module table, dependency graph, debt facts
    harness/project_map.py --json       the same facts as JSON

Discovery writes ARCHITECTURE.md from these facts plus reading the code: the facts
(models, dependencies, tests) come from here, so the map does not depend on memory.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hlib  # noqa: E402

NAME_RE = re.compile(r"^\s*_name\s*=\s*['\"]([\w.]+)['\"]", re.M)
INHERIT_RE = re.compile(r"^\s*_inherit\s*=\s*(\[[^\]]*\]|['\"][\w.]+['\"])", re.M)
CLASS_RE = re.compile(r"^class\s+\w+\(\s*models\.(Model|TransientModel|AbstractModel)\b", re.M)


def models_of(module_dir):
    """(models defined, models extended) by the module's Python code."""
    defined, extended = set(), set()
    for path in sorted(module_dir.rglob("*.py")):
        if "tests" in path.relative_to(module_dir).parts:
            continue
        text = path.read_text(errors="replace")
        for chunk in re.split(r"(?=^class\s)", text, flags=re.M):
            if not CLASS_RE.match(chunk):
                continue
            names = NAME_RE.findall(chunk)
            inherits = []
            for raw in INHERIT_RE.findall(chunk):
                try:
                    value = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    continue
                inherits += [value] if isinstance(value, str) else list(value)
            if names:
                defined.update(names)
                extended.update(m for m in inherits if m not in names)
            else:
                extended.update(inherits)
    return sorted(defined), sorted(extended - defined)


def module_facts(env):
    modules = hlib.custom_modules(env)
    facts = []
    for name, mdir in sorted(modules.items()):
        manifest = hlib.read_manifest(mdir)
        depends = list(manifest.get("depends") or [])
        defined, extended = models_of(mdir)
        tests = sorted(p.name for p in (mdir / "tests").glob("test_*.py")) \
            if (mdir / "tests").is_dir() else []
        facts.append({
            "module": name,
            "path": mdir.relative_to(hlib.REPO_ROOT).as_posix(),
            "name": manifest.get("name", ""),
            "summary": manifest.get("summary", ""),
            "version": manifest.get("version", ""),
            "author": manifest.get("author", ""),
            "depends_custom": [d for d in depends if d in modules],
            "depends_other": [d for d in depends if d not in modules],
            "models_defined": defined,
            "models_extended": extended,
            "data_files": len(manifest.get("data") or []),
            "tests": tests,
            "installable": manifest.get("installable", True),
        })
    return facts


def third_party(env):
    out = {}
    for folder in hlib.env_list(env, "THIRD_PARTY_ADDONS"):
        root = hlib.REPO_ROOT / folder
        out[folder] = sorted(p.parent.name for p in root.glob("*/__manifest__.py"))
    return out


def markdown(facts, env):
    lines = ["| Module | Name / summary | Models defined | Models extended | Depends on "
             "(custom) | Tests |", "|---|---|---|---|---|---|"]
    for f in facts:
        summary = " ".join(str(f["summary"]).split())
        summary = summary[:90] + "…" if len(summary) > 90 else summary
        title = " ".join(str(f["name"]).split()) + (f" — {summary}" if summary else "")
        title = title.replace("|", "/")
        lines.append(f"| `{f['module']}` | {title} | {', '.join(f['models_defined']) or '-'} | "
                     f"{', '.join(f['models_extended']) or '-'} | "
                     f"{', '.join(f['depends_custom']) or '-'} | {len(f['tests']) or 'none'} |")
    graph = ["```mermaid", "flowchart LR"]
    for f in facts:
        for dep in f["depends_custom"]:
            graph.append(f"    {dep} --> {f['module']}")
    if len(graph) == 2:
        graph.append("    %% no dependency between custom modules")
    graph.append("```")
    standard = sorted({d for f in facts for d in f["depends_other"]})
    no_tests = [f["module"] for f in facts if not f["tests"]]
    disabled = [f["module"] for f in facts if not f["installable"]]
    out = ["## Modules (facts from harness/project_map.py)", "", *lines, "",
           "## Dependencies between custom modules", "", *graph, "",
           "## Odoo and third-party modules the project builds on", "",
           ", ".join(f"`{d}`" for d in standard) or "-", ""]
    for folder, mods in third_party(env).items():
        out.append(f"- `{folder}` (read-only): {', '.join(mods) or 'empty'}")
    out += ["", "## Debt facts", "",
            f"- Modules without tests: {len(no_tests)} of {len(facts)}"
            + (f" ({', '.join(no_tests)})" if no_tests else ""),
            f"- Not installable: {', '.join(disabled) or 'none'}",
            "- Static checks over the whole project: run `harness/static_checks.py --all`."]
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    env = hlib.load_env()
    facts = module_facts(env)
    if args.json:
        print(json.dumps({"modules": facts, "third_party": third_party(env)}, indent=2))
    else:
        sys.stdout.write(markdown(facts, env))
    return 0


if __name__ == "__main__":
    sys.exit(main())
