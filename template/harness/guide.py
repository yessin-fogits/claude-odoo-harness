#!/usr/bin/env python3
"""User guide of a completed Odoo task: a PDF in French, with screenshots, for developers.

  guide.py capture TASK   check the task is completed, then replay the e2e tests of its
                          features and take a screenshot at each guide.step()
  guide.py build TASK     turn the screenshots and the text written in
                          .harness/guide/<TASK>/content.json into docs/guides/<TASK>.pdf
  guide.py check          list the guides that no longer match their task (stale)

A task is completed when every one of its features is passing with valid evidence and
committed ([T2003] F-001 ...), and nothing uncommitted is left in the custom modules or
e2e/. The screenshots come from the features' own e2e tests, so the guide shows behavior
a test proved. The /odoo-harness-<version>:guide skill runs the three steps.
"""

import argparse
import datetime
import html
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hlib  # noqa: E402
import verify  # noqa: E402
from hlib import RedPen  # noqa: E402

GUIDES_DIR = hlib.REPO_ROOT / "docs" / "guides"
GUIDES_INDEX = GUIDES_DIR / "guides.json"
TODO = "À RÉDIGER"
CSS = """
body { font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif; color: #222;
       font-size: 11pt; line-height: 1.45; }
h1 { font-size: 20pt; margin: 0 0 4pt; color: #714b67; }
h2 { font-size: 15pt; margin: 18pt 0 6pt; color: #714b67; border-bottom: 1px solid #ddd;
     padding-bottom: 3pt; }
h3 { font-size: 12pt; margin: 12pt 0 4pt; }
.meta { color: #666; font-size: 9pt; margin-bottom: 12pt; }
.meta td { padding: 1pt 10pt 1pt 0; }
.feature { break-before: page; }
.step { break-inside: avoid; margin: 10pt 0 14pt; }
.step p { margin: 2pt 0 4pt; }
.step img { width: 100%; border: 1px solid #ccc; border-radius: 3px; }
.caption { color: #666; font-size: 9pt; }
.num { display: inline-block; min-width: 18pt; font-weight: bold; color: #714b67; }
code { background: #f3f3f3; padding: 0 3px; border-radius: 2px; font-size: 9.5pt; }
.tech { background: #f8f8f8; border-left: 3px solid #714b67; padding: 4pt 10pt; }
"""


# --- the "completed only" gate ----------------------------------------------

def completed_features(task):
    """The features of `task`, in order, or a RedPen saying why the task is not completed."""
    data = hlib.load_features()
    feats = hlib.task_features(data, task)
    if not feats:
        tasks = sorted({f["task"] for f in data["features"] if f.get("task")})
        raise RedPen("guide", f"no feature belongs to task {task}",
                     "A guide documents the features of one Odoo task (feature_list.json).",
                     f"Use a task code from the list: {', '.join(tasks) or 'none yet'} "
                     "(harness/feature.py status).")
    todo = [f"{f['id']} ({f['state']})" for f in feats if f["state"] != "passing"]
    if todo:
        raise RedPen("guide", f"task {task} is not completed: {', '.join(todo)}",
                     "A user guide is written only for a completed task: every feature passing, "
                     "verified and committed.",
                     "Finish the task first (harness/feature.py verify <id>, then commit), and "
                     "ask for the guide again.")
    problems = []
    subjects = set(hlib.git("log", "--format=%s").splitlines())
    for feat in feats:
        problems += evidence_problems(feat)
        if hlib.commit_message(feat) not in subjects:
            problems.append(f"{feat['id']}: no commit '{hlib.commit_message(feat)}'")
    if problems:
        raise RedPen("guide", f"task {task} is not completed: " + "; ".join(problems),
                     "Every feature must be verified (valid evidence) and committed with its "
                     "[task] F-xxx message before its guide is written.",
                     "Run harness/feature.py check, verify again what it reports, and commit "
                     "with the message harness/feature.py verify printed.")
    env = hlib.load_env()
    dirty = sorted(f for f in hlib.changed_files()
                   if f.startswith("e2e/") or hlib.module_of(env, f))
    if dirty:
        raise RedPen("guide", f"uncommitted changes: {', '.join(dirty[:8])}",
                     "The guide must show the committed code, the code that was verified.",
                     "Commit or stash these changes, then ask for the guide again.")
    return feats


def evidence_problems(feat):
    """What is wrong with the evidence of a passing feature (feature.py check rules)."""
    ev = feat["evidence"]
    try:
        record = json.loads((hlib.REPO_ROOT / ev.get("file", "")).read_text())
    except (FileNotFoundError, IsADirectoryError, json.JSONDecodeError):
        return [f"{feat['id']}: evidence file missing or invalid"]
    fp = hlib.fingerprint(feat)
    if not (record.get("feature") == feat["id"] and record.get("fingerprint") == fp
            and ev.get("fingerprint") == fp):
        return [f"{feat['id']}: behavior/verification changed after it was verified"]
    if record.get("report", {}).get("result") != "pass":
        return [f"{feat['id']}: evidence does not record a passing verification"]
    return []


def evidence_record(feat):
    return json.loads((hlib.REPO_ROOT / feat["evidence"]["file"]).read_text())


def e2e_files(feat):
    return [t for k, t in map(hlib.parse_verification, feat["verification"]) if k == "e2e"]


def task_dir(task):
    return hlib.STATE_DIR / "guide" / task


# --- capture ------------------------------------------------------------------

def cmd_capture(args):
    task = args.task
    feats = completed_features(task)
    env = hlib.load_env()
    stamp = hlib.now_iso().replace(":", "").replace("+0000", "Z")
    run_dir = task_dir(task) / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    modules = sorted({m for f in feats
                      for m in evidence_record(f).get("report", {}).get("changed_modules", [])})
    if modules:
        verify.step(f"update {','.join(modules)} on the test DB")
        log = run_dir / "odoo-update.log"
        rc, out = verify.run_logged(["run", "--rm", "-T", "odoo", "odoo", "-d", env["TEST_DB"],
                                     "-u", ",".join(modules), "--stop-after-init"], log)
        if rc != 0 or verify.odoo_error_blocks(out):
            verify.redpen_from_text("guide", "module update on the test DB failed", out, log)
            return 1
    verify.step("restart Odoo with the committed code")
    rc, _ = verify.run_logged(["restart", "odoo"], run_dir / "restart.log")
    if rc == 0:
        rc, _ = verify.run_logged(["up", "-d", "--wait", "odoo"], run_dir / "restart.log")
    if rc != 0:
        hlib.print_redpen("guide", "Odoo did not come back healthy after restart",
                          "The server does not start with the current code.",
                          "Run harness/init.sh --check, fix what it reports, capture again.")
        return 1

    manifest = {"task": task, "commit": hlib.head_commit(), "captured_at": hlib.now_iso(),
                "run_dir": verify.rel(run_dir), "features": []}
    for feat in feats:
        shots = run_dir / feat["id"]
        shots.mkdir(parents=True, exist_ok=True)
        files = e2e_files(feat)
        log = run_dir / f"e2e-{feat['id']}.log"
        verify.step(f"replay {feat['id']}: playwright {' '.join(files)}")
        rc, out = verify.run_logged(
            ["run", "--rm", "-T", f"--env=PYTHONPATH={verify.E2E_PLUGINS}",
             f"--env=HARNESS_GUIDE_DIR={verify.rel(shots)}", "e2e", "pytest", *files,
             "--base-url", "http://odoo:8069", "-p", "harness_guide", "-p", "no:cacheprovider",
             "-q"], log)
        counts = verify.parse_pytest(out)
        if rc != 0 or counts["failed"] or counts["errors"] or not counts["passed"]:
            verify.redpen_from_text(
                "guide", f"the e2e test of {feat['id']} fails on the committed code", out, log)
            hlib.print_redpen("guide", f"{feat['id']} regressed since it was verified",
                              "The guide replays the tests that proved the feature; one fails now.",
                              f"Reopen it (harness/feature.py start {feat['id']} --reopen), fix "
                              "it and verify again before writing its guide.")
            return 1
        tests = []
        for steps_file in sorted(shots.glob("*/steps.json")):
            record = json.loads(steps_file.read_text())
            tests.append({"test": record["test"], "steps": [
                {"key": f"{feat['id']}/{steps_file.parent.name}/{s['image'][:-4]}",
                 "caption": s["caption"], "url": s["url"],
                 "image": verify.rel(steps_file.parent / s["image"])}
                for s in record["steps"]]})
        if not tests:
            hlib.print_redpen("guide", f"no screenshot recorded for {feat['id']}",
                              "The replay passed but the guide plugin wrote nothing.",
                              "Check that the e2e tests use the Playwright `page` fixture "
                              f"(directly or through odoo_page); log: {verify.rel(log)}.")
            return 1
        manifest["features"].append({"id": feat["id"], "behavior": feat["behavior"],
                                     "modules": evidence_record(feat).get("report", {})
                                     .get("changed_modules", []),
                                     "verification": feat["verification"], "tests": tests})
    hlib.write_atomic(task_dir(task) / "steps.json",
                      json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    content_path = task_dir(task) / "content.json"
    content = merge_skeleton(load_json(content_path), manifest)
    hlib.write_atomic(content_path, json.dumps(content, indent=2, ensure_ascii=False) + "\n")
    count = sum(len(t["steps"]) for f in manifest["features"] for t in f["tests"])
    verify.ok(f"{count} screenshot(s) of {len(feats)} feature(s): {verify.rel(task_dir(task))}"
              "/steps.json")
    left = todo_keys(content)
    print(f"Next: write the text in French in {verify.rel(content_path)} "
          f"({len(left)} field(s) marked {TODO!r}), then: harness/guide.py build {task}")
    return 0


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def merge_skeleton(content, manifest):
    """content.json with every field the guide needs; text already written is kept."""
    old = content.get("features", {}) if isinstance(content.get("features"), dict) else {}
    out = {"title": content.get("title") or f"{manifest['task']} : {TODO}",
           "summary": content.get("summary") or TODO, "features": {}}
    for feat in manifest["features"]:
        prev = old.get(feat["id"], {})
        prev_steps = prev.get("steps", {}) if isinstance(prev.get("steps"), dict) else {}
        out["features"][feat["id"]] = {
            "summary": prev.get("summary") or TODO,
            "steps": {s["key"]: prev_steps.get(s["key"]) or TODO
                      for t in feat["tests"] for s in t["steps"]},
            "technical": prev.get("technical") or TODO,
            "notes": prev.get("notes", ""),
        }
    return out


def todo_keys(content):
    """Paths of the fields still to write (empty or containing the TODO marker)."""
    left = []

    def walk(value, path):
        if isinstance(value, dict):
            for key, sub in value.items():
                walk(sub, f"{path}.{key}" if path else key)
        elif isinstance(value, str) and path.split(".")[-1] != "notes" and (
                not value.strip() or TODO in value):
            left.append(path)
    walk(content, "")
    return left


# --- build --------------------------------------------------------------------

INLINE_CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def inline(text):
    text = html.escape(text)
    text = INLINE_CODE_RE.sub(r"<code>\1</code>", text)
    return BOLD_RE.sub(r"<b>\1</b>", text)


def blocks(text):
    """Paragraphs separated by blank lines; lines starting with '- ' make a list."""
    out = []
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [ln.strip() for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(ln.startswith("- ") for ln in lines):
            out.append("<ul>" + "".join(f"<li>{inline(ln[2:])}</li>" for ln in lines) + "</ul>")
        else:
            out.append(f"<p>{inline(' '.join(lines))}</p>")
    return "\n".join(out)


def render_html(manifest, content, feats, base):
    """The guide as one HTML page; image paths are relative to `base`."""
    env = hlib.load_env()
    by_id = {f["id"]: f for f in feats}
    today = datetime.date.today().strftime("%d/%m/%Y")
    parts = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
             f"<title>{html.escape(content['title'])}</title><style>{CSS}</style></head><body>",
             f"<h1>{inline(content['title'])}</h1>",
             "<table class='meta'>"
             f"<tr><td>Tâche Odoo</td><td><b>{html.escape(manifest['task'])}</b></td></tr>"
             f"<tr><td>Version d'Odoo</td><td>{html.escape(env.get('ODOO_VERSION', ''))}</td></tr>"
             f"<tr><td>Commit</td><td><code>{html.escape((manifest['commit'] or '')[:12])}</code>"
             "</td></tr>"
             f"<tr><td>Généré le</td><td>{today}</td></tr></table>",
             blocks(content["summary"]),
             "<h3>Fonctionnalités</h3><ul>"]
    parts += [f"<li><b>{f['id']}</b> : {inline(f['behavior'])}</li>" for f in manifest["features"]]
    parts.append("</ul>")
    for feat in manifest["features"]:
        text = content["features"][feat["id"]]
        evidence = by_id[feat["id"]]["evidence"]
        parts += [f"<section class='feature'><h2>{feat['id']} : {inline(feat['behavior'])}</h2>",
                  blocks(text["summary"]), "<h3>Pas à pas</h3>"]
        number = 0
        for test in feat["tests"]:
            for step in test["steps"]:
                number += 1
                src = (hlib.REPO_ROOT / step["image"]).relative_to(base).as_posix()
                parts.append(
                    f"<div class='step'><p><span class='num'>{number}.</span>"
                    f"{inline(text['steps'][step['key']])}</p>"
                    f"<img src='{html.escape(str(src))}' alt='{html.escape(step['caption'])}'>"
                    f"<div class='caption'>{inline(step['caption'])}</div></div>")
        parts += ["<h3>Détails techniques</h3><div class='tech'>", blocks(text["technical"]),
                  "<ul>",
                  f"<li>Modules : {', '.join(f'<code>{m}</code>' for m in feat['modules']) or '-'}"
                  "</li>",
                  "<li>Tests : " + ", ".join(f"<code>{html.escape(v)}</code>"
                                             for v in feat["verification"]) + "</li>",
                  f"<li>Vérifiée le {html.escape(evidence['verified_at'][:10])}"
                  f" (commit <code>{html.escape((evidence.get('commit') or '')[:12])}</code>)</li>",
                  "</ul></div>"]
        if text.get("notes", "").strip():
            parts += ["<h3>Bon à savoir</h3>", blocks(text["notes"])]
        parts.append("</section>")
    parts.append("</body></html>")
    return "\n".join(parts)


def cmd_build(args):
    task = args.task
    feats = completed_features(task)
    manifest = load_json(task_dir(task) / "steps.json")
    if manifest.get("commit") != hlib.head_commit():
        raise RedPen("guide", f"the screenshots of {task} are missing or older than HEAD",
                     "The screenshots must come from a replay of the current commit.",
                     f"Run harness/guide.py capture {task} first.")
    if [f["id"] for f in manifest["features"]] != [f["id"] for f in feats]:
        raise RedPen("guide", f"the features of {task} changed since the capture",
                     "The screenshots do not cover the current features of the task.",
                     f"Run harness/guide.py capture {task} again.")
    content_path = task_dir(task) / "content.json"
    content = load_json(content_path)
    if content != merge_skeleton(content, manifest):
        raise RedPen("guide", f"{verify.rel(content_path)} does not match the screenshots",
                     "Each step key of steps.json needs its text, and only those keys.",
                     f"Run harness/guide.py capture {task} (it adds the missing fields and keeps "
                     "the text already written), then fill in the fields marked "
                     f"{TODO!r}.")
    left = todo_keys(content)
    if left:
        raise RedPen("guide", f"{len(left)} field(s) still to write: {', '.join(left[:6])}",
                     "Every field of the guide needs its text in French.",
                     f"Write them in {verify.rel(content_path)}, then build again.")
    base = task_dir(task)
    html_path = base / "guide.html"
    html_path.write_text(render_html(manifest, content, feats, base))
    run_dir = hlib.REPO_ROOT / manifest["run_dir"]
    pdf_tmp = run_dir / f"{task}.pdf"
    log = run_dir / "pdf.log"
    verify.step(f"render {verify.rel(html_path)} to PDF")
    rc, out = verify.run_logged(["run", "--rm", "-T", "e2e", "python", "harness/guide_pdf.py",
                                 verify.rel(html_path), verify.rel(pdf_tmp)], log)
    if rc != 0 or not pdf_tmp.is_file():
        verify.redpen_from_text("guide", "the PDF could not be rendered", out, log)
        return 1
    GUIDES_DIR.mkdir(parents=True, exist_ok=True)
    pdf = GUIDES_DIR / f"{task}.pdf"
    shutil.copyfile(pdf_tmp, pdf)
    index = load_json(GUIDES_INDEX)
    index[task] = {"pdf": verify.rel(pdf), "commit": manifest["commit"],
                   "generated_at": hlib.now_iso(),
                   "features": {f["id"]: {"fingerprint": f["evidence"]["fingerprint"],
                                          "verified_at": f["evidence"]["verified_at"]}
                                for f in feats}}
    hlib.write_atomic(GUIDES_INDEX, json.dumps(dict(sorted(index.items())), indent=2,
                                               ensure_ascii=False) + "\n")
    verify.ok(f"guide of {task}: {verify.rel(pdf)}")
    print(f"Commit it: git add {verify.rel(pdf)} {verify.rel(GUIDES_INDEX)} && "
          f"git commit -m '[{task}] Guide utilisateur'")
    return 0


# --- check --------------------------------------------------------------------

def stale_reasons(task, record, data):
    feats = {f["id"]: f for f in hlib.task_features(data, task)}
    reasons = []
    if set(feats) != set(record.get("features", {})):
        reasons.append("the task's features changed")
    for fid, rec in record.get("features", {}).items():
        feat = feats.get(fid)
        if not feat:
            continue
        if feat["state"] != "passing":
            reasons.append(f"{fid} is {feat['state']}")
        elif (feat["evidence"]["fingerprint"] != rec.get("fingerprint")
              or feat["evidence"]["verified_at"] != rec.get("verified_at")):
            reasons.append(f"{fid} was verified again since the guide")
    if not (hlib.REPO_ROOT / record.get("pdf", "")).is_file():
        reasons.append("the PDF is missing")
    return reasons


def cmd_check(_args):
    index = load_json(GUIDES_INDEX)
    if not index:
        print("no user guide yet (harness/guide.py capture <task>)")
        return 0
    data = hlib.load_features()
    stale = 0
    for task, record in index.items():
        reasons = stale_reasons(task, record, data)
        if reasons:
            stale += 1
            print(f"✗ {task}: stale ({'; '.join(reasons)}). Generate it again: "
                  f"/odoo-harness-{hlib.version_tuple(hlib.load_env().get('ODOO_VERSION'))[0]}"
                  f":guide {task}")
        else:
            print(f"✓ {task}: {record['pdf']} up to date")
    return 1 if stale else 0


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn in (("capture", cmd_capture), ("build", cmd_build)):
        cmd = sub.add_parser(name)
        cmd.add_argument("task", help="code of the Odoo task (T2003)")
        cmd.set_defaults(fn=fn)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        return args.fn(args)
    except RedPen as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
