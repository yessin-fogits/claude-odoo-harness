#!/usr/bin/env python3
"""Three-layer completion validation. Run it through harness/verify.sh.

  L1 static   static_checks.py + pylint-odoo (lint container)
  L2 runtime  Odoo unit/integration tests on the test DB (odoo -u ... --test-tags)
  L3 system   Playwright e2e against the restarted server, clean server log,
              optional install on a fresh DB

Layers run in order and stop at the first failure. Without --e2e the whole e2e
suite runs. With --feature, the whole suite also runs when the feature's changes
touch more than one module or shared files (cross-component change).
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import errors  # noqa: E402
import hlib  # noqa: E402
import static_checks  # noqa: E402

PYLINT_TEMPLATE = "{path}:{line}: [{msg_id}({symbol})] {msg}"
# OCA-only rules, not relevant for client projects (cannot be disabled in .pylintrc).
PYLINT_DISABLE = "--disable=manifest-required-author,missing-readme"
PYLINT_RE = re.compile(r"^(?P<path>[^\s:]+):(?P<line>\d+): \[(?P<id>\w+)\((?P<symbol>[\w-]+)\)\] "
                       r"(?P<msg>.*)$")
ODOO_LOG_RE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \d+ (?P<level>[A-Z]+) ")
ODOO_RESULT_RE = re.compile(r"(\d+) failed, (\d+) error\(s\) of (\d+) tests")
ODOO_RAN_RE = re.compile(r"Ran (\d+) tests?")
# Test summary records (17.0-20.0) that Odoo logs at ERROR level after real failures.
ODOO_SUMMARY_RE = re.compile(r"odoo\.tests\.result: |Module \w+: \d+ failures?, \d+ errors? of "
                             r"\d+ tests|At least one test failed when loading the modules")
PYTEST_COUNT_RE = re.compile(r"(\d+) (passed|failed|errors?)\b")
PYTEST_FAILED_RE = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$", re.M)
DOC_SUFFIXES = {".md", ".rst", ".txt"}
EXCERPT_LINES = 15


class LayerFailed(Exception):
    pass


# --- process helpers ----------------------------------------------------------

def compose_cmd():
    base = shlex.split(os.environ.get("HARNESS_COMPOSE", "docker compose"))
    return base + ["--project-directory", str(hlib.REPO_ROOT), "--env-file", str(hlib.HARNESS_ENV)]


def run_logged(args, log_path):
    """Run a compose sub-command, save its combined output, return (rc, output)."""
    proc = subprocess.run(compose_cmd() + args, cwd=hlib.REPO_ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, errors="replace")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(proc.stdout)
    return proc.returncode, proc.stdout


def rel(path):
    try:
        return str(Path(path).resolve().relative_to(hlib.REPO_ROOT))
    except ValueError:
        return str(path)


def step(msg):
    print(f"→ {msg}", flush=True)


def ok(msg):
    print(f"✓ {msg}", flush=True)


def excerpt(text, lines=25):
    return "\n".join(text.strip().splitlines()[-lines:])


def redpen_from_text(layer, what, text, log_path):
    """Print the catalog explanation of text, or the unknown-error fallback."""
    print(excerpt(text, EXCERPT_LINES), file=sys.stderr)
    matches = errors.explain(text)
    if matches:
        _id, why, fix = matches[0]
        hlib.print_redpen(layer, what, why, f"{fix} (log: {rel(log_path)})")
    else:
        hlib.print_redpen(layer, what, f"See the excerpt above (full log: {rel(log_path)}).",
                          errors.UNKNOWN_FIX)


# --- L1 static --------------------------------------------------------------

def layer_static(env, run_dir):
    findings = static_checks.run(env)
    for finding in findings:
        print(finding.redpen(), file=sys.stderr)
    modules = static_checks.module_dirs(env)
    lint_messages = []
    if modules:
        log = run_dir / "pylint.log"
        rc, out = run_logged(["run", "--rm", "-T", "lint", "pylint", "--rcfile=.pylintrc",
                              PYLINT_DISABLE, f"--msg-template={PYLINT_TEMPLATE}",
                              *[rel(m) for m in modules]], log)
        lint_messages = [m.groupdict() for m in map(PYLINT_RE.match, out.splitlines()) if m]
        for msg in lint_messages:
            hlib.print_redpen("L1 lint", f"{msg['path']}:{msg['line']}: {msg['symbol']} "
                              f"({msg['id']})", msg["msg"], errors.pylint_fix(msg["symbol"]))
        if not lint_messages and rc & (1 | 32):
            print(excerpt(out), file=sys.stderr)
            hlib.print_redpen("L1 lint", "pylint-odoo could not run",
                              f"The lint container failed (exit {rc}); see the excerpt above.",
                              "Build the lint image: docker compose --profile tools build lint. "
                              "If the error is in .pylintrc, fix the config.")
            lint_messages.append({"symbol": "lint-tool-error"})
    result = {"status": "pass" if not findings and not lint_messages else "fail",
              "static_findings": len(findings), "lint_messages": len(lint_messages)}
    if result["status"] == "fail":
        raise LayerFailed(result)
    ok(f"L1 static: {len(modules)} module(s), no findings")
    return result


# --- L2 runtime -------------------------------------------------------------

def odoo_error_blocks(log_text):
    """Each ERROR/CRITICAL log record with its continuation lines (tracebacks)."""
    blocks, current = [], None
    for line in log_text.splitlines():
        record = ODOO_LOG_RE.match(line)
        if record:
            if current:
                blocks.append("\n".join(current))
            current = [line] if record.group("level") in ("ERROR", "CRITICAL") else None
        elif current is not None:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def parse_odoo_tests(log_text):
    """(tests, failed, errors) from the Odoo test summary, or None if no summary."""
    totals = [0, 0, 0]
    found = False
    for failed, errs, tests in ODOO_RESULT_RE.findall(log_text):
        found = True
        totals[0] += int(tests)
        totals[1] += int(failed)
        totals[2] += int(errs)
    if not found:
        ran = ODOO_RAN_RE.findall(log_text)
        if not ran:
            return None
        totals[0] = sum(int(n) for n in ran)
    return tuple(totals)


def layer_runtime(env, tags, run_dir):
    modules = hlib.modules_in_scope(env)
    if not modules:
        ok("L2 runtime: no modules in scope (MODULES is empty), skipped")
        return {"status": "skipped"}
    spec = ",".join(tags) if tags else ",".join(f"/{m}" for m in modules)
    log = run_dir / "odoo-tests.log"
    step(f"L2 runtime: odoo -u {','.join(modules)} --test-tags {spec}")
    rc, out = run_logged(["run", "--rm", "-T", "odoo", "odoo", "-d", env["TEST_DB"],
                          "-u", ",".join(modules), "--test-tags", spec, "--stop-after-init"], log)
    counts = parse_odoo_tests(out)
    tests, failed, errs = counts or (0, 0, 0)
    blocks = odoo_error_blocks(out)
    result = {"status": "pass", "test_tags": spec, "tests": tests, "failed": failed,
              "errors": errs, "log_errors": len(blocks), "log": rel(log)}
    if rc != 0 or failed or errs or blocks:
        result["status"] = "fail"
        # Summary records logged at ERROR level repeat the failures above them.
        blocks = [b for b in blocks if not ODOO_SUMMARY_RE.search(b.splitlines()[0])] or blocks
        for block in blocks[:5] or [out]:
            redpen_from_text("L2 runtime", f"Odoo tests failed ({failed} failed, {errs} errors "
                             f"of {tests})", block, log)
        raise LayerFailed(result)
    if tests == 0:
        result["status"] = "fail"
        hlib.print_redpen("L2 runtime", f"no Odoo test ran for --test-tags {spec}",
                          "A verification with zero tests proves nothing.",
                          "Write the tests in <module>/tests/ (imported in tests/__init__.py), "
                          "or fix the unit/integration entries of the feature to match "
                          "real test classes, e.g. 'unit: /my_module:TestMyFeature'.")
        raise LayerFailed(result)
    ok(f"L2 runtime: {tests} test(s) passed")
    return result


# --- L3 system --------------------------------------------------------------

def parse_pytest(out):
    counts = {"passed": 0, "failed": 0, "errors": 0}
    summary = [ln for ln in out.splitlines() if re.search(r"\b(passed|failed|error|no tests ran)\b",
                                                         ln)]
    if summary:
        for n, kind in PYTEST_COUNT_RE.findall(summary[-1]):
            counts["errors" if kind.startswith("error") else kind] += int(n)
    return counts


def changed_files(start_commit):
    names = set()
    if start_commit:
        names |= set(hlib.git("diff", "--name-only", start_commit).splitlines())
    for args in (("diff", "--name-only"), ("diff", "--name-only", "--cached"),
                 ("ls-files", "--others", "--exclude-standard")):
        names |= set(hlib.git(*args).splitlines())
    return {n for n in names if n}


def cross_component(env, files):
    """(is_cross_component, touched_modules) for a set of changed paths."""
    addons = Path(env.get("ADDONS_DIR", "addons")).parts
    modules, shared = set(), []
    for name in files:
        parts = Path(name).parts
        if parts[:len(addons)] == addons and len(parts) > len(addons) + 1:
            modules.add(parts[len(addons)])
        elif Path(name).suffix in DOC_SUFFIXES or name == "feature_list.json":
            continue
        elif parts[0] in (".harness",) or name.startswith("harness/evidence/"):
            continue
        elif parts[0] == "e2e" and Path(name).name.startswith("test_"):
            continue
        else:
            shared.append(name)
    return (len(modules) > 1 or bool(shared)), sorted(modules), sorted(shared)


def server_log_errors(since, run_dir):
    log = run_dir / "odoo-server.log"
    _rc, out = run_logged(["logs", "--no-color", "--since", since, "odoo"], log)
    lines = [ln for ln in out.splitlines()
             if re.search(r" (ERROR|CRITICAL) |Traceback \(most recent call last\)", ln)]
    return lines, log


def fresh_install(env, run_dir):
    db = env["TEST_DB"] + "_fresh"
    modules = ",".join(hlib.modules_in_scope(env))
    drop = ["exec", "-T", "db", "psql", "-U", "odoo", "-d", "postgres", "-c",
            f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)']
    run_logged(drop, run_dir / "fresh-drop.log")
    log = run_dir / "fresh-install.log"
    step(f"L3 system: install {modules} on a fresh DB '{db}'")
    rc, out = run_logged(["run", "--rm", "-T", "odoo", "odoo", "-d", db, "-i", modules,
                          "--stop-after-init"], log)
    run_logged(drop, run_dir / "fresh-drop.log")
    blocks = odoo_error_blocks(out)
    if rc != 0 or blocks:
        for block in blocks[:5] or [out]:
            redpen_from_text("L3 system", "module install on a fresh DB failed", block, log)
        return False
    return True


def layer_system(env, e2e_files, full, fresh, run_dir):
    targets = ["e2e"] if full else e2e_files
    missing = [f for f in targets if not (hlib.REPO_ROOT / f).exists()]
    result = {"status": "fail", "e2e_targets": targets, "full_suite": full}
    if missing:
        hlib.print_redpen("L3 system", f"e2e test file missing: {', '.join(missing)}",
                          "Every feature needs its own Playwright test; only e2e is real "
                          "verification.",
                          "Write the test in e2e/ (see e2e/test_smoke.py and the odoo_page fixture "
                          "in e2e/conftest.py), then verify again.")
        raise LayerFailed(result)
    step("L3 system: restarting Odoo with the new code")
    rc, out = run_logged(["restart", "odoo"], run_dir / "restart.log")
    if rc == 0:
        rc, out = run_logged(["up", "-d", "--wait", "odoo"], run_dir / "restart.log")
    if rc != 0:
        hlib.print_redpen("L3 system", "Odoo did not come back healthy after restart",
                          "The server crashes at startup with the current code.",
                          "Read `docker compose logs odoo`, fix the first error, verify again.")
        raise LayerFailed(result)
    since = hlib.now_iso()
    artifacts = run_dir / "e2e"
    log = run_dir / "e2e.log"
    step(f"L3 system: playwright {' '.join(targets)}")
    rc, out = run_logged(["run", "--rm", "-T", "e2e", "pytest", *targets,
                          "--base-url", "http://odoo:8069", "--output", rel(artifacts),
                          "--tracing", "retain-on-failure", "--screenshot", "only-on-failure",
                          "-p", "no:cacheprovider", "-q"], log)
    counts = parse_pytest(out)
    result.update(counts, artifacts=rel(artifacts), log=rel(log))
    if rc != 0 or counts["failed"] or counts["errors"] or not counts["passed"]:
        failures = PYTEST_FAILED_RE.findall(out)
        for _kind, test, msg in failures[:5]:
            redpen_from_text("L3 e2e", f"{test} failed", f"{msg}\n{out}", log)
        if not failures:
            redpen_from_text("L3 e2e", "the e2e run failed or ran no test", out, log)
        raise LayerFailed(result)
    log_errors, server_log = server_log_errors(since, run_dir)
    result["server_log_errors"] = len(log_errors)
    if log_errors:
        print("\n".join(log_errors[:20]), file=sys.stderr)
        redpen_from_text("L3 system", "the server logged errors during the e2e run",
                         "\n".join(log_errors), server_log)
        raise LayerFailed(result)
    if fresh:
        result["fresh_install"] = fresh_install(env, run_dir)
        if not result["fresh_install"]:
            raise LayerFailed(result)
    result["status"] = "pass"
    ok(f"L3 system: {counts['passed']} e2e test(s) passed"
       f"{' (full suite)' if full else ''}, clean server log")
    return result


# --- main -------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", type=int, choices=(1, 2, 3), help="run only this layer")
    p.add_argument("--feature", help="feature id, recorded in the report")
    p.add_argument("--tags", action="append", default=[], help="Odoo --test-tags spec")
    p.add_argument("--e2e", action="append", default=[], help="e2e test file")
    p.add_argument("--full-e2e", action="store_true", help="run the whole e2e suite")
    p.add_argument("--fresh-install", action="store_true",
                   help="also install the modules on a fresh DB (L3)")
    p.add_argument("--report", type=Path, help="where to write the JSON report")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    env = hlib.load_env()
    stamp = hlib.now_iso().replace(":", "").replace("+0000", "Z")
    run_dir = hlib.STATE_DIR / "runs" / f"{stamp}-{args.feature or 'baseline'}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report = {"feature": args.feature, "started_at": hlib.now_iso(),
              "commit": hlib.head_commit(), "dirty": hlib.working_tree_dirty(),
              "run_dir": rel(run_dir), "layers": {}, "result": "fail"}

    full = args.full_e2e or not args.e2e
    if args.feature and not full:
        start = hlib.load_state().get(args.feature, {}).get("start_commit")
        is_cross, touched, shared = cross_component(env, changed_files(start))
        report["touched_modules"] = touched
        report["shared_files"] = shared
        if is_cross:
            full = True
            reason = (f"modules {', '.join(touched)}" if len(touched) > 1
                      else f"shared files {', '.join(shared[:5])}")
            step(f"cross-component change ({reason}): full e2e suite required")

    layers = [(1, "static", lambda: layer_static(env, run_dir)),
              (2, "runtime", lambda: layer_runtime(env, args.tags, run_dir)),
              (3, "system", lambda: layer_system(env, args.e2e, full, args.fresh_install,
                                                 run_dir))]
    try:
        for number, name, fn in layers:
            if args.only and args.only != number:
                continue
            report["layers"][name] = fn()
        report["result"] = "pass"
    except LayerFailed as exc:
        report["layers"][name] = exc.args[0]
    finally:
        report["finished_at"] = hlib.now_iso()
        report_path = args.report.resolve() if args.report else run_dir / "report.json"
        hlib.write_atomic(report_path, json.dumps(report, indent=2) + "\n")
        hlib.write_atomic(hlib.STATE_DIR / "last-verify.json", json.dumps(report, indent=2) + "\n")
    if report["result"] == "pass":
        ok(f"verification passed (report: {rel(report_path)})")
        return 0
    print(f"✗ verification failed at layer '{name}' (report: {rel(report_path)})",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
