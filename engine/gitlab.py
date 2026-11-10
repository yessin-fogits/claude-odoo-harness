#!/usr/bin/env python3
"""Ship an Odoo task: push its branch and open its merge request on GitLab.

    odoo-harness gitlab push TASK                 push the task branch (git push -u origin TASK)
    odoo-harness gitlab mr TASK [--title TEXT]    push, then open (or update) the merge request
                                                TASK -> BASE_BRANCH
    odoo-harness gitlab shared TASK               add the knowledge files to each shared
                                                submodule: a branch TASK and a merge request
                                                in each one's project (run it twice)

`mr` is refused until every feature of the task passes (odoo-harness feature verify) and
the work is committed: the merge request lists the features with their evidence.

A task that changes a shared submodule (a GitLab project other projects include) ships in two
merge requests, merged in this order: the submodule's (TASK -> its .gitmodules branch), then
the project's. The first `mr` pushes the submodule's commit, opens its merge request, and
opens the project's as Draft. Once the submodule's is merged, `mr` again does the pull (the
pointer moves to the submodule's branch, committed and pushed) and marks the project's ready,
when the pointers hold the code the task's evidence verified.

`shared` gives every shared submodule its knowledge files (CLAUDE.md, DECISIONS.md,
ARCHITECTURE.md) before any task changes it. The first run writes the missing ones in a
worktree of its branch tip, .harness/shared/<path>; once each ARCHITECTURE.md is filled from
the code beside it, the second run commits them, pushes the branch TASK of the submodule's
project and opens its merge request to the .gitmodules branch. The project and its pointers
are left as they are: the files reach it when its pointer moves.

Settings come from harness/harness.env (GITLAB_URL, GITLAB_PROJECT, BASE_BRANCH). The
token is GITLAB_TOKEN, from the environment or the git-ignored .env file of the
repository (a personal or project access token with the api scope); never commit it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hlib  # noqa: E402
from hlib import RedPen  # noqa: E402

MR_DIR = hlib.STATE_DIR / "mr"
DRAFT_RE = re.compile(r"^\s*(draft:|\[draft\]|\(draft\)|draft\s+-|wip:)\s*", re.I)


def token():
    value = os.environ.get("GITLAB_TOKEN", "").strip()
    dotenv = hlib.REPO_ROOT / ".env"
    if not value and dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            key, _, val = line.strip().partition("=")
            if key.strip() == "GITLAB_TOKEN":
                value = val.strip().strip("'\"")
    if not value:
        raise RedPen("gitlab", "GITLAB_TOKEN is not set",
                     "Opening a merge request calls the GitLab API as you.",
                     "Create a personal access token with the api scope on GitLab, then "
                     "`export GITLAB_TOKEN=...` or add GITLAB_TOKEN=... to the .env file at the "
                     "repository root (git-ignored). Never commit it.")
    return value


def settings(env, project=None):
    """(GITLAB_URL, the project: default GITLAB_PROJECT, the repository's)."""
    base = env.get("GITLAB_URL", "").rstrip("/")
    project = project or env.get("GITLAB_PROJECT", "")
    if not base or not project:
        raise RedPen("gitlab", "GITLAB_URL or GITLAB_PROJECT is empty in harness/harness.env",
                     "The harness does not know which GitLab project the repository belongs to.",
                     "Set GITLAB_URL=https://gitlab.example.com and GITLAB_PROJECT=group/project "
                     "in harness/harness.env.")
    return base, project


def api(env, method, path, payload=None, project=None):
    """GitLab API call on the project (default: GITLAB_PROJECT, the repository's)."""
    base, project = settings(env, project)
    url = f"{base}/api/v4/projects/{urllib.parse.quote(project, safe='')}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "PRIVATE-TOKEN": token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        hints = {401: "The token is invalid or expired: create a new one (api scope).",
                 403: "The token cannot write to this project: it needs the api scope and at "
                      "least the Developer role.",
                 404: (f"Check GITLAB_PROJECT={project} in harness/harness.env (group/project)."
                       if project == env.get("GITLAB_PROJECT") else
                       f"Check that {project} (a submodule's project, from its URL) exists and "
                       "that the token can see it.")}
        raise RedPen("gitlab", f"GitLab API {method} {path} failed ({exc.code})", detail,
                     hints.get(exc.code, "Read the GitLab message above and fix the cause."))
    except urllib.error.URLError as exc:
        raise RedPen("gitlab", f"cannot reach {base}", str(exc.reason),
                     "Check GITLAB_URL and the network (VPN, proxy).")


def git(*args, cwd=None):
    proc = subprocess.run(["git", *args], cwd=cwd or hlib.REPO_ROOT, capture_output=True,
                          text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_branch(task):
    if hlib.current_branch() != task:
        raise RedPen("git", f"not on the branch of {task} (on '{hlib.current_branch()}')",
                     "A task is shipped from its own branch.",
                     f"git checkout {task}, then run the command again.")
    if hlib.working_tree_dirty():
        subs = [s["path"] for s in hlib.submodules()
                if hlib.git("status", "--porcelain", "--", s["path"])]
        raise RedPen("git", "uncommitted changes",
                     "Only committed work is pushed; the merge request would miss them.",
                     (f"Commit inside the submodule {subs[0]} first (git -C {subs[0]} add -A && "
                      f"git -C {subs[0]} commit -m '[TASK] F-xxx behavior'), then " if subs
                      else "") + "commit the verified work (message: [TASK] F-xxx behavior), "
                     "then run the command again.")


def push_project(task):
    rc, out = git("push", "-u", "origin", task)
    if rc != 0:
        raise RedPen("git", f"git push -u origin {task} failed", out[-400:],
                     "Fix the cause (credentials, network, rejected push: pull --rebase first), "
                     "then run the command again.")
    print(f"✓ pushed {task}")


def push(task):
    """The task branch, after the submodule commits its pointers need: a pointer to a commit
    that is only on this machine would break every clone of the branch."""
    check_branch(task)
    env = hlib.load_env()
    for sub in shipped_submodules(env):
        if check_submodule(env, sub, task, knowledge=False):
            push_submodule(sub, task)
    push_project(task)


# --- shared submodules --------------------------------------------------------

def shipped_submodules(env):
    """The submodules whose pointer this task branch moves (since the base branch)."""
    base = hlib.base_ref(env)
    if not base:
        return []
    return [sub for sub in hlib.submodules()
            if hlib.git("rev-parse", "--verify", "-q", f"HEAD:{sub['path']}")
            not in ("", hlib.git("rev-parse", "--verify", "-q", f"{base}:{sub['path']}"))]


def check_submodule(env, sub, task, knowledge=True):
    """True when the harness ships the submodule: a project of GITLAB_URL with its branch in
    .gitmodules (and, when its merge request is needed, its knowledge files). False when its
    pointer only moves to a commit already published elsewhere (an OCA update on GitHub).
    Otherwise a red pen: nobody would push that commit."""
    path = sub["path"]
    gitlab = env.get("GITLAB_URL", "")
    if not (ours(env, sub) and sub["branch"]) and published(sub, task):
        return False
    if not ours(env, sub):
        raise RedPen("gitlab", f"the submodule {path} is not a project of {gitlab or 'GITLAB_URL'}",
                     f"Its URL is {sub['url'] or '(none)'}: the harness pushes and opens merge "
                     "requests on the project's GitLab only, and this commit is on no branch of "
                     "its origin.",
                     f"Push the commit of {path} to its repository yourself and get it merged "
                     "there; the project's merge request is opened by hand meanwhile.")
    require_branch(env, sub)
    missing = [f for f in hlib.SHARED_FILES if not (hlib.REPO_ROOT / path / f).is_file()]
    # files merged on the branch since the pointer need no adding
    if knowledge and missing and not on_branch(sub) \
            and not hlib.shared_files_upstream(sub, fetch=True):
        raise RedPen("shared", f"the shared submodule {path} has no {', '.join(missing)}",
                     "Its rules, decisions and map travel with its code to every project that "
                     "uses it.",
                     f"python3 {hlib.INSTALL_TEMPLATE} --shared {path}; fill its ARCHITECTURE.md "
                     f"(Modules, Dependencies, Projects using it); commit the files inside "
                     f"{path}, then the pointer in the project; then run the command again.")
    return True


def require_branch(env, sub):
    if not sub["branch"]:
        raise RedPen("gitlab", f"no branch for the submodule {sub['path']} in .gitmodules",
                     "Its merge request targets the branch every project using it follows.",
                     f"git config -f .gitmodules submodule.{sub['name']}.branch "
                     f"{env.get('ODOO_VERSION') or '<branch>'}, commit .gitmodules, then run the "
                     "command again.")


def ours(env, sub):
    """The submodule is a project of the repository's GitLab (GITLAB_URL)."""
    host, project = hlib.git_host_project(sub["url"])
    return bool(project) and host == urllib.parse.urlparse(env.get("GITLAB_URL", "")).hostname


def published(sub, task):
    """The pointer is on a branch of the submodule's origin, other than the task's own."""
    folder = hlib.REPO_ROOT / sub["path"]
    rc, out = git("fetch", "-q", "origin", cwd=folder)
    if rc != 0:
        raise RedPen("git", f"cannot fetch the origin of the submodule {sub['path']}",
                     out[-300:], "Fix the cause (credentials, network), then run the command "
                     "again.")
    rc, out = git("branch", "-r", "--format=%(refname)", "--contains", pointer(sub), cwd=folder)
    return rc == 0 and any(ref.startswith("refs/remotes/origin/") and not ref.endswith("/HEAD")
                           and ref != f"refs/remotes/origin/{task}" for ref in out.split())


def fetch_branch(sub):
    rc, out = git("fetch", "-q", "origin", sub["branch"], cwd=hlib.REPO_ROOT / sub["path"])
    if rc != 0:
        raise RedPen("git", f"cannot fetch {sub['branch']} of the submodule {sub['path']}",
                     out[-300:], "Fix the cause (credentials, network), then run the command "
                     "again.")


def is_ancestor(sub, commit, of):
    return git("merge-base", "--is-ancestor", commit, of,
               cwd=hlib.REPO_ROOT / sub["path"])[0] == 0


def pointer(sub):
    return hlib.git("rev-parse", f"HEAD:{sub['path']}")


def on_branch(sub):
    """The pointer is a commit of the submodule's branch on GitLab: already shared."""
    fetch_branch(sub)
    return is_ancestor(sub, pointer(sub), f"origin/{sub['branch']}")


def push_submodule(sub, task):
    """Push the pointer's commit to the task's branch of the submodule's project, unless it is
    on the submodule's branch already. True when pushed."""
    if on_branch(sub):
        return False
    rc, out = git("push", "origin", f"{pointer(sub)}:refs/heads/{task}",
                  cwd=hlib.REPO_ROOT / sub["path"])
    if rc != 0:
        raise RedPen("git", f"cannot push {sub['path']} to its branch {task}", out[-400:],
                     f"If a teammate pushed to it: git -C {sub['path']} pull --rebase origin "
                     f"{task}, commit the pointer, then run the command again.")
    print(f"✓ pushed {sub['path']} to {task}")
    return True


def find_mr(env, task, project=None, state="opened"):
    """The task's most recent merge request in the project (any state when state is None)."""
    query = "/merge_requests?source_branch=" + urllib.parse.quote(task)
    found = api(env, "GET", query + (f"&state={state}" if state else ""), project=project)
    return found[0] if found else None


def ship_submodule(env, sub, task):
    """(state, merge request) of one shipped submodule:
    - "waiting": pass 1, its merge request is open (opened or updated here);
    - "pulled": pass 2, it was merged, the pointer moved to its branch here (not committed);
    - "merged": the pointer already holds the merged change;
    - "on-branch": no merge request, the pointer moved to a commit already on its branch."""
    project = hlib.git_host_project(sub["url"])[1]
    path, branch = sub["path"], sub["branch"]
    folder = hlib.REPO_ROOT / path
    mr = find_mr(env, task, project, state=None)
    if mr and mr.get("state") == "merged":
        fetch_branch(sub)
        here, shared = pointer(sub), f"origin/{branch}"
        merged = mr.get("merge_commit_sha") or mr.get("squash_commit_sha") or mr.get("sha")
        if merged and is_ancestor(sub, merged, here):
            if is_ancestor(sub, here, shared):
                return "merged", mr
            mr = None  # new commits after the merged one: they get a merge request of their own
        elif is_ancestor(sub, here, shared) or here == mr.get("sha"):
            rc, out = git("checkout", "-q", "--detach", shared, cwd=folder)
            if rc != 0:
                raise RedPen("git", f"cannot check out {branch} in {path}", out[-300:],
                             "Fix the submodule's state, then run the command again.")
            print(f"✓ {path} on {branch} after its merge request !{mr.get('iid')}")
            return "pulled", mr
        else:
            raise RedPen("git", f"{path} has commits after its merged merge request "
                         f"!{mr.get('iid')}",
                         f"The pull would move the pointer to {branch} and leave them out.",
                         f"git -C {path} rebase {shared}, commit the pointer, verify the "
                         "feature again, then run the command again: they get a merge request "
                         "of their own.")
    if mr and mr.get("state") == "closed":
        raise RedPen("gitlab", f"the merge request of {path} was closed without merge: "
                     f"{mr.get('web_url')}",
                     "The project's merge request needs that change merged in the shared "
                     "project first.",
                     "Reopen it on GitLab (or undo the change of the submodule and its pointer "
                     "on this branch), then run the command again.")
    if not push_submodule(sub, task) and not mr:
        return "on-branch", None
    body = (f"Part of Odoo task **{task}**, made and verified in the project "
            f"`{env.get('GITLAB_PROJECT', '')}` (branch `{task}`): its merge request waits "
            "for this one.\n\n"
            "These modules are shared: every project that includes this repository as a "
            "submodule gets this change when it moves its pointer (see \"Projects using it\" in "
            "ARCHITECTURE.md). Merge this request first; then `odoo-harness gitlab mr "
            f"{task}` in the project moves its pointer to `{branch}` and marks its merge "
            "request ready.")
    if mr:
        mr = api(env, "PUT", f"/merge_requests/{mr['iid']}", {"description": body},
                 project=project)
        print(f"✓ merge request of {path} updated: {mr.get('web_url')}")
    else:
        title = f"[{task}] " + hlib.git("log", "-1", "--format=%s", pointer(sub),
                                        cwd=folder).removeprefix(f"[{task}] ")
        mr = api(env, "POST", "/merge_requests", {
            "source_branch": task, "target_branch": branch, "title": title,
            "description": body, "remove_source_branch": True}, project=project)
        print(f"✓ merge request of {path} opened: {mr.get('web_url')}")
    return "waiting", mr


def commit_pulled(task, pulled):
    """Commit the pointers the pull moved."""
    paths = [sub["path"] for sub, _mr in pulled]
    message = f"[{task}] " + ", ".join(f"{sub['path']} on {sub['branch']} after !{mr.get('iid')}"
                                        for sub, mr in pulled)
    for args in (("add", "--", *paths), ("commit", "-q", "-m", message)):
        rc, out = git(*args)
        if rc != 0:
            raise RedPen("git", f"cannot commit the pointer of {', '.join(paths)}", out[-400:],
                         "Fix the cause (a pre-commit check), commit the pointer yourself "
                         f"with the message \"{message}\", then run the command again.")
    print(f"✓ committed: {message}")


def verified_trees(features):
    """{submodule path: git tree} that the task's latest evidence tested."""
    tested = {}
    for feat in sorted(features, key=lambda f: f["evidence"].get("verified_at", "")):
        try:
            record = json.loads((hlib.REPO_ROOT / feat["evidence"]["file"]).read_text())
        except (OSError, ValueError, KeyError, TypeError):
            continue
        tested.update(record.get("report", {}).get("submodules") or {})
    return tested


def unverified(subs, features):
    """The shipped submodules whose pointer does not hold the code the evidence tested: the
    pull brought someone else's changes, or the pointer moved after the verification."""
    tested = verified_trees(features)
    return [sub["path"] for sub in subs
            if not tested.get(sub["path"]) or tested[sub["path"]] != hlib.git(
                "rev-parse", "--verify", "-q", f"{pointer(sub)}^{{tree}}",
                cwd=hlib.REPO_ROOT / sub["path"])]


def description(task, features, shipped=()):
    rows = ["| Feature | Behavior | Verified | Tests |", "|---|---|---|---|"]
    modules = set()
    for feat in features:
        record = {}
        try:
            record = json.loads((hlib.REPO_ROOT / feat["evidence"]["file"]).read_text())
        except (OSError, ValueError, KeyError, TypeError):
            pass
        report = record.get("report", {})
        layers = report.get("layers", {})
        modules |= set(report.get("tested_modules", []))
        tests = (f"{layers.get('runtime', {}).get('tests', 0)} Odoo, "
                 f"{layers.get('system', {}).get('passed', 0)} e2e")
        rows.append(f"| {feat['id']} | {feat['behavior']} | "
                    f"{feat['evidence'].get('verified_at', '')[:10]} | {tests} |")
    e2e_on = ("the developer's dev database (neutralized client copy)"
              if hlib.dev_mode(hlib.load_env()) else "a fresh test database")
    lines = [f"Odoo task **{task}**: every feature below passed `odoo-harness feature verify` "
             f"(static checks and pylint-odoo, Odoo tests on a test database with demo data, "
             f"Playwright e2e on {e2e_on}).", "", *rows, ""]
    if modules:
        lines.append(f"Modules tested: {', '.join(sorted(modules))}.")
    lines.append("Evidence: `harness/evidence/<feature>.json` in this branch.")
    if shipped:
        lines += ["", "### Shared submodules", "",
                  "Merge their merge requests first: `odoo-harness gitlab mr "
                  f"{task}` then moves the pointers to their branch and marks this one ready.",
                  "", "| Submodule | Merge request |", "|---|---|"]
        for sub, state, mr in shipped:
            link = f"[!{mr.get('iid')}]({mr.get('web_url')})" if mr else ""
            branch = f"`{sub['branch']}`" if sub["branch"] else "a branch of its origin"
            lines.append(f"| `{sub['path']}` | " + {
                "waiting": f"{link} open: merge it first",
                "pulled": f"{link} merged, pointer on {branch}",
                "merged": f"{link} merged, pointer on {branch}",
                "on-branch": f"none: the pointer moves to a commit already on {branch}",
            }[state] + " |")
    return "\n".join(lines)


def draft_title(title, draft):
    bare = DRAFT_RE.sub("", title)
    return f"Draft: {bare}" if draft else bare


def merge_request(task, title=None):
    env = hlib.load_env()
    data = hlib.load_features()
    features = hlib.task_features(data, task)
    if not features:
        raise RedPen("features", f"no feature belongs to task {task}",
                     "A merge request ships the verified features of one Odoo task.",
                     f"Add them with odoo-harness feature add --task {task} ...")
    left = [f["id"] for f in features if f["state"] != "passing"]
    if left:
        raise RedPen("features", f"task {task} is not finished: {', '.join(left)} not passing",
                     "A merge request is opened only when every feature of the task is verified.",
                     f"Finish {left[0]}: odoo-harness feature verify {left[0]}")
    committed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", f"tasks/{task}.json",
                                "harness/evidence"], cwd=hlib.REPO_ROOT).returncode == 0
    if not committed:
        raise RedPen("git", "the passing states are not committed",
                     "The merge request must contain the evidence it lists.",
                     "Commit the work, then run the command again.")
    check_branch(task)
    subs = shipped_submodules(env)
    # every refusal before anything is pushed
    ships = {sub["path"]: check_submodule(env, sub, task) for sub in subs}
    shipped = [(sub, *(ship_submodule(env, sub, task) if ships[sub["path"]]
                       else ("on-branch", None))) for sub in subs]
    pulled = [(sub, mr) for sub, state, mr in shipped if state == "pulled"]
    if pulled:
        commit_pulled(task, pulled)
    push_project(task)
    waiting = [sub["path"] for sub, state, _mr in shipped if state == "waiting"]
    stale = [] if waiting else unverified(subs, features)
    draft = bool(waiting or stale)
    base = env.get("BASE_BRANCH") or "staging"
    body = description(task, features, shipped)
    existing = find_mr(env, task)
    if existing:
        update = {"description": body}
        if draft != bool(DRAFT_RE.match(existing.get("title", ""))):
            update["title"] = draft_title(existing.get("title", ""), draft)
        mr = api(env, "PUT", f"/merge_requests/{existing['iid']}", update)
        print(f"✓ merge request updated{' (Draft)' if draft else ''}: {mr.get('web_url')}")
    else:
        mr = api(env, "POST", "/merge_requests", {
            "source_branch": task, "target_branch": base,
            "title": draft_title(f"[{task}] {title or features[0]['behavior']}", draft),
            "description": body, "remove_source_branch": True})
        print(f"✓ merge request opened{' (Draft)' if draft else ''}: {mr.get('web_url')}")
    hlib.write_atomic(MR_DIR / f"{task}.json", json.dumps(
        {"task": task, "iid": mr.get("iid"), "url": mr.get("web_url"), "draft": draft,
         "features": [f["id"] for f in features],
         "submodules": {sub["path"]: {"state": state, "url": (sub_mr or {}).get("web_url")}
                        for sub, state, sub_mr in shipped},
         "at": hlib.now_iso()}, indent=2) + "\n")
    if waiting:
        print(f"Next: get the merge request of {', '.join(waiting)} reviewed and merged, then "
              f"run odoo-harness gitlab mr {task} again: it moves the pointer to its branch and "
              "marks this merge request ready.")
    elif stale:
        last = features[-1]["id"]
        raise RedPen("gitlab", f"the merge request stays Draft: {', '.join(stale)} not verified "
                     "with the commit it points to",
                     "The pull brought changes of the shared branch this task's evidence did "
                     "not test (someone else's merge), or the pointer moved after the "
                     "verification.",
                     f"odoo-harness feature start {last} --reopen, then odoo-harness feature "
                     f"verify {last} (it tests the shared modules with this project's), commit, "
                     f"then odoo-harness gitlab mr {task} again.")
    elif subs:
        print("✓ ready to merge: the shared submodules are merged and their pointers hold the "
              "verified code")
    return mr


# --- the knowledge files of the shared submodules ------------------------------

KNOWLEDGE_DIR = hlib.STATE_DIR / "shared"
KNOWLEDGE_PATHS = (*hlib.SHARED_FILES, ".gitattributes")


def knowledge_targets(env, task):
    """The shared submodules (in a CUSTOM_ADDONS folder, on the project's GitLab), after the
    checks that need nothing written. The other submodules are printed as skipped: an OCA
    mirror or an Odoo checkout hosted on the same GitLab is not shared modules."""
    shared = {sub["path"] for sub in hlib.addon_submodules(env, keys=("CUSTOM_ADDONS",))}
    if shared:
        settings(env)  # without GITLAB_URL every submodule would look foreign
    targets = []
    for sub in hlib.submodules():
        path = sub["path"]
        if path not in shared:
            print(f"- {path}: skipped (not in CUSTOM_ADDONS)")
            continue
        if not ours(env, sub):
            print(f"- {path}: skipped (not a project of {env.get('GITLAB_URL') or 'GITLAB_URL'}: "
                  f"{sub['url'] or 'no URL'})")
            continue
        require_branch(env, sub)
        if sub["branch"] == task:
            raise RedPen("gitlab", f"the task {task} is the branch of the submodule {path}",
                         "The command pushes the branch TASK: that would be the branch every "
                         "project using it pulls.",
                         "Use the Odoo task code (T2003).")
        if not sub["initialized"]:
            raise RedPen("git", f"the submodule {path} is not checked out",
                         "Its files are written from its own git repository.",
                         f"git submodule update --init {path}, then run the command again.")
        targets.append(sub)
    return targets


def knowledge_plan(env, task, sub):
    """(state, merge request) of one shared submodule, nothing written yet:
    - "has": its branch has every knowledge file;
    - "open": the task's merge request is open in its project;
    - "checkout": the submodule's checkout has them (a task's change brings them);
    - "elsewhere": another open merge request to its branch adds them;
    - "write": pass 1, the files are to be written;
    - "unfilled": pass 2, its new ARCHITECTURE.md is still the template;
    - "ship": pass 2, ARCHITECTURE.md is filled: commit, push, open the merge request."""
    path = sub["path"]
    folder = KNOWLEDGE_DIR / path
    project = hlib.git_host_project(sub["url"])[1]
    fetch_branch(sub)
    if hlib.shared_files_upstream(sub):
        return "has", None
    mr = find_mr(env, task, project)
    if mr:
        return "open", mr
    # a second set of files would conflict with theirs once both are merged
    if all((hlib.REPO_ROOT / path / f).is_file() for f in hlib.SHARED_FILES):
        return "checkout", None
    mr = adding_mr(env, sub, project)
    if mr:
        return "elsewhere", mr
    started = (folder / ".git").exists()
    remote = hlib.git("ls-remote", "--heads", "origin", f"refs/heads/{task}",
                      cwd=hlib.REPO_ROOT / path).split()
    if remote and not (started and remote[0] == hlib.git("rev-parse", "HEAD", cwd=folder)):
        raise RedPen("gitlab", f"the branch {task} already exists in the project of {path}",
                     "It holds commits this command did not make (a change of the task, or a "
                     "merge request closed without merge).",
                     f"Add the knowledge files with that change (python3 {hlib.INSTALL_TEMPLATE} "
                     f"--shared {path}), or delete the branch on GitLab if it is a leftover, "
                     "then run the command again.")
    if not started:
        return "write", None
    if unfilled(folder):
        return "unfilled", None
    changed = hlib.git("diff", "--name-only", "HEAD", cwd=folder).splitlines() \
        + hlib.git("ls-files", "--others", "--exclude-standard", cwd=folder).splitlines()
    other = set(changed) - set(KNOWLEDGE_PATHS)
    if other:
        raise RedPen("gitlab", f"{folder.relative_to(hlib.REPO_ROOT)} changes more than the "
                     f"knowledge files: {', '.join(sorted(other))}",
                     "This merge request adds the knowledge files only: a change of the "
                     "modules is a task's, verified with the project's modules.",
                     f"git -C {folder} checkout HEAD -- {' '.join(sorted(other))} (or remove "
                     "the new ones), then run the command again.")
    return "ship", None


def adding_mr(env, sub, project):
    """An open merge request to the submodule's branch whose source branch has every knowledge
    file (another project's `gitlab shared`, or a task that adds them with its change)."""
    folder = hlib.REPO_ROOT / sub["path"]
    query = "/merge_requests?state=opened&target_branch=" + urllib.parse.quote(sub["branch"])
    for mr in api(env, "GET", query, project=project) or []:
        if mr.get("source_project_id") != mr.get("target_project_id"):
            continue  # a fork: its branch is not on this origin
        if git("fetch", "-q", "origin", mr["source_branch"], cwd=folder)[0] == 0 and set(
                hlib.git("ls-tree", "--name-only", "FETCH_HEAD", "--", *hlib.SHARED_FILES,
                         cwd=folder).splitlines()) == set(hlib.SHARED_FILES):
            return mr
    return None


def written_map(folder):
    """The copy of the ARCHITECTURE.md pass 1 wrote, in the worktree's own git dir (removed
    with the worktree)."""
    return folder / hlib.git("rev-parse", "--git-path", "odoo-harness-architecture", cwd=folder)


def unfilled(folder):
    """ARCHITECTURE.md is new on the branch and still what pass 1 wrote, or missing."""
    if hlib.git("rev-parse", "--verify", "-q", "HEAD:ARCHITECTURE.md", cwd=folder):
        return False
    path, written = folder / "ARCHITECTURE.md", written_map(folder)
    return not path.is_file() or (
        written.is_file() and path.read_text().split() == written.read_text().split())


def filled_here(folder):
    """The worktree holds an ARCHITECTURE.md filled but not committed yet."""
    return (folder / ".git").exists() and not unfilled(folder) and bool(
        hlib.git("status", "--porcelain", "--", "ARCHITECTURE.md", cwd=folder))


def ship_knowledge(env, task, sub):
    """Commit the files written in pass 1, push the branch TASK, open the merge request."""
    path, branch = sub["path"], sub["branch"]
    folder = KNOWLEDGE_DIR / path
    message = f"[{task}] odoo-harness knowledge files"
    rc, out = git("add", "-A", "--", *KNOWLEDGE_PATHS, cwd=folder)
    if rc == 0 and hlib.git("diff", "--cached", "--name-only", cwd=folder):
        rc, out = git("commit", "-q", "-m", message, cwd=folder)
    if rc != 0:
        raise RedPen("git", f"cannot commit the knowledge files of {path}", out[-400:],
                     "Fix the cause (a pre-commit check of the shared project), then run the "
                     "command again.")
    rc, out = git("push", "origin", f"HEAD:refs/heads/{task}", cwd=folder)
    if rc != 0:
        raise RedPen("git", f"cannot push {path} to its branch {task}", out[-400:],
                     "Fix the cause (credentials, network), then run the command again.")
    body = (f"Adds the odoo-harness knowledge files of these shared modules, from Odoo task "
            f"**{task}** of the project `{env.get('GITLAB_PROJECT', '')}`:\n\n"
            "- `CLAUDE.md`: the rules for changing them (backward compatible, decisions "
            "recorded);\n"
            "- `DECISIONS.md`: the decisions about them, append-only;\n"
            "- `ARCHITECTURE.md`: their map (modules, dependencies, projects using them).\n\n"
            "No module changes. Every project that includes this repository as a submodule "
            "gets these files when it moves its pointer; its developers' sessions then read "
            "them before changing these modules.")
    mr = api(env, "POST", "/merge_requests", {
        "source_branch": task, "target_branch": branch, "title": message,
        "description": body, "remove_source_branch": True},
        project=hlib.git_host_project(sub["url"])[1])
    remove_worktree(sub)
    return mr


def remove_worktree(sub):
    folder = KNOWLEDGE_DIR / sub["path"]
    if folder.exists():
        git("worktree", "remove", "--force", str(folder), cwd=hlib.REPO_ROOT / sub["path"])


def knowledge(task):
    hlib.check_task_name(task)
    env = hlib.load_env()
    targets = knowledge_targets(env, task)
    if not targets:
        print("No shared submodule: nothing to do.")
        return
    # every refusal before anything is written or pushed
    plans = [(sub, *knowledge_plan(env, task, sub)) for sub in targets]
    not_filled = [str(KNOWLEDGE_DIR.relative_to(hlib.REPO_ROOT) / sub["path"] / "ARCHITECTURE.md")
                  for sub, state, _mr in plans if state == "unfilled"]
    if not_filled:
        raise RedPen("shared", f"not filled yet: {', '.join(not_filled)}",
                     "The map of the shared modules is what every project's sessions read "
                     "before changing them: an empty template tells them nothing.",
                     "Fill its sections (Modules, Dependencies, Projects using it, Risks and "
                     "debt) from the code in the same folder, then run the command again (a "
                     "deleted one: remove its folder, the next run writes it again).")
    written = []
    for sub, state, mr in plans:
        path, branch = sub["path"], sub["branch"]
        folder = KNOWLEDGE_DIR / path
        if state in ("has", "open", "checkout", "elsewhere"):
            if filled_here(folder):
                print(f"! {path}: {folder.relative_to(hlib.REPO_ROOT)} kept, its ARCHITECTURE.md "
                      "is filled: carry what applies into the one that ships, then remove it "
                      f"(git -C {path} worktree remove --force {folder})")
            else:
                remove_worktree(sub)
        if state == "has":
            print(f"✓ {path}: its branch {branch} has the knowledge files")
        elif state == "open":
            print(f"✓ {path}: merge request open: {mr.get('web_url')}")
        elif state == "checkout":
            print(f"✓ {path}: its checkout has the knowledge files: the task that changes it "
                  "ships them")
        elif state == "elsewhere":
            print(f"✓ {path}: merge request {mr.get('web_url')} adds the knowledge files")
        elif state == "write":
            folder = KNOWLEDGE_DIR / path
            folder.parent.mkdir(parents=True, exist_ok=True)
            git("worktree", "prune", cwd=hlib.REPO_ROOT / path)  # a folder removed by hand
            rc, out = git("worktree", "add", "-q", "--detach", str(folder), f"origin/{branch}",
                          cwd=hlib.REPO_ROOT / path)
            if rc != 0:
                raise RedPen("git", f"cannot check out {branch} of {path} in {folder}",
                             out[-300:], "Fix the cause, then run the command again.")
            installed = subprocess.run([sys.executable, str(hlib.INSTALL_TEMPLATE), "--shared",
                                        str(folder)], capture_output=True, text=True)
            if installed.returncode != 0:
                raise RedPen("shared", f"cannot write the knowledge files of {path}",
                             (installed.stdout + installed.stderr)[-300:],
                             "Fix the cause, then run the command again.")
            # what pass 2 compares against (unused when the branch has its own already)
            shutil.copyfile(folder / "ARCHITECTURE.md", written_map(folder))
            written.append(str(folder.relative_to(hlib.REPO_ROOT)))
            print(f"✓ {path}: knowledge files written in {written[-1]} ({branch})")
        else:
            mr = ship_knowledge(env, task, sub)
            print(f"✓ {path}: pushed {task}, merge request opened: {mr.get('web_url')}")
    if written:
        print(f"Next: fill the ARCHITECTURE.md of {', '.join(written)} (Modules, "
              "Dependencies, Projects using it, Risks and debt) from the code beside it, then "
              f"run odoo-harness gitlab shared {task} again: it commits the files, pushes the "
              "branch and opens the merge request of each.")
    elif any(state == "ship" for _sub, state, _mr in plans):
        print("Get them merged on GitLab. This project gets the files when its pointer moves "
              "(a task that changes the submodule, or a pointer update); nothing changes here.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("push").add_argument("task")
    mr = sub.add_parser("mr")
    mr.add_argument("task")
    mr.add_argument("--title", help="merge request title after [TASK] (default: first feature)")
    sub.add_parser("shared").add_argument("task")
    args = p.parse_args(argv)
    try:
        if args.command == "push":
            push(args.task)
        elif args.command == "shared":
            knowledge(args.task)
        else:
            merge_request(args.task, args.title)
    except RedPen as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
