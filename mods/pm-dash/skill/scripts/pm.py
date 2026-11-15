#!/usr/bin/env python3
"""Task ledger and herdr helpers for the pm skill.

State lives in the ledger home (PM_HOME; default ~/.dudu, or ~/.claude/pm where an
earlier install already keeps it): one JSON file per task in tasks/, and BOARD.md,
which is regenerated after every write. Each project has its own PM: a session of
any coding agent, registered in pms/. Workers are coding agents too; which program
plays which part is a matter of configuration (see AGENT_KINDS).
"""
import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import sys
import time
from pathlib import Path



def default_home():
    """The ledger home: PM_HOME, else ~/.claude/pm where an earlier install keeps it, else ~/.dudu."""
    earlier = Path.home() / ".claude" / "pm"
    return Path(os.environ.get("PM_HOME") or (earlier if earlier.exists() else Path.home() / ".dudu"))


STATE = default_home()
TASKS = STATE / "tasks"
PMS = STATE / "pms"
BOARD = STATE / "BOARD.md"
ACTIVE = ["proposed", "in_progress", "review", "blocked", "paused"]
CLOSED = ["merged", "released", "done", "abandoned"]
# A session is identified by its herdr pane, or in the herdr desktop app by its herdr-core terminal ("hc:t7").
HC_TERMINAL = os.environ.get("HC_TERMINAL_ID", "")
PANE = os.environ.get("HERDR_PANE_ID", "") or (f"hc:{HC_TERMINAL}" if HC_TERMINAL else "")
WORKSPACE = os.environ.get("HERDR_WORKSPACE_ID", "")
PROJECTS = STATE / "projects"
# Above this many context tokens a PM is told to hand over at the next task boundary.
ROTATE_TOKENS = int(os.environ.get("PM_ROTATE_TOKENS", "200000"))


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def herdr(*args):
    """Return the `result` object of a herdr CLI call, or None outside herdr."""
    try:
        out = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout)["result"]
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return None


def agents():
    return (herdr("agent", "list") or {}).get("agents", [])


def hc(*args, errors=False):
    """Parsed JSON of a herdr-core CLI call, or None when hc is missing or the call fails.
    With errors, a failed call returns hc's error object instead ({"error": {"kind": "not_found", ...}})."""
    try:
        # --json goes before a "--": what follows that belongs to the program being started.
        cut = args.index("--") if "--" in args else len(args)
        out = subprocess.run(["hc", *args[:cut], "--json", *args[cut:]], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return json.loads(out.stderr or "null") if errors else None
        return json.loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def hc_pm(root):
    """The registered herdr-core PM of the project at root, if its terminal is live and still labelled pm=<project>."""
    path = PMS / f"{project_slug(root)}.json"
    rec = json.loads(path.read_text()) if path.exists() else {}
    if rec.get("runtime") != "hc" or not rec.get("terminal"):
        return None
    term = hc("get", rec["terminal"]) or {}
    if term.get("state") != "live" or (term.get("labels") or {}).get("pm") != Path(root).name:
        return None
    return {"pane_id": f"hc:{rec['terminal']}", "name": rec["name"], "cwd": term.get("cwd"),
            "agent_status": (term.get("status") or {}).get("state", ""), "workspace_id": ""}


def project_slug(repo):
    """Lowercase project name usable in a herdr agent name."""
    return re.sub(r"[^a-z0-9_-]+", "-", Path(repo).resolve().name.lower()).strip("-")[:28] or "project"


def pm_name(repo):
    return f"pm-{project_slug(repo)}"


def pm_tab_name(repo):
    return f"PM-{Path(repo).name}"


def name_tab(terminal, name, only_if=None):
    """Rename the desktop tab that shows terminal; an empty name gives the tab its number back.
    With only_if, only a tab now called that. No app, or no tab (a bare or sub-agent terminal): nothing happens."""
    try:
        out = subprocess.run(["herdr-app", "ls"], capture_output=True, text=True, timeout=30)
        spaces = (json.loads(out.stdout).get("spaces") or []) if out.returncode == 0 else []
        for tab in (tab for space in spaces for tab in space.get("tabs") or []):
            if any(t.get("terminal") == terminal for t in tab.get("terminals") or []):
                if only_if is None or tab.get("name") == only_if:
                    subprocess.run(["herdr-app", "do", "tab.rename", json.dumps({"id": tab["id"], "name": name})],
                                   capture_output=True, text=True, timeout=30)
                return
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        pass


def find_pm(listing=None, repo=None):
    """The PM agent for the project containing repo (default: the current directory).

    The PM is the herdr agent named pm-<project slug>, or the herdr-core terminal its registration names
    (runtime "hc"); outside a repository there is none. The registration decides when both exist.
    """
    listing = agents() if listing is None else listing
    root = project_root(repo or ".")
    if not root:
        return None
    in_hc = hc_pm(root)
    if in_hc:
        return in_hc
    want = pm_name(root)
    pms = [a for a in listing if a.get("name") == want]
    pms.sort(key=lambda a: a.get("workspace_id") != WORKSPACE)
    return pms[0] if pms else None


def pm_record(repo):
    """The registration file of the PM for repo, or None."""
    root = project_root(repo or ".")
    path = PMS / f"{project_slug(root)}.json" if root else None
    return json.loads(path.read_text()) if path and path.exists() else None


def git(path, *args):
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def main_root(path):
    """The main checkout of the repository containing path, so worktrees map to one project."""
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return str(Path(common).parent) if common else None


def project_root(path):
    """Main checkout of the repository containing path, or the directory itself when it is not under git.

    A PM can coordinate a plain working directory (for example an issue-triage folder).
    """
    root = main_root(path)
    if root:
        return root
    d = Path(path).resolve()
    return str(d) if d.is_dir() else None


def base_branch(repo):
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", name) is not None:
            return name
    return "HEAD"


def merge_target(repo, base):
    """The branch a task's work is merged into: its base, or the repository's main branch once the base is deleted
    (a base branch is often merged and removed before the tasks built on it)."""
    return base if git(repo, "rev-parse", "--verify", "--quiet", base) is not None else base_branch(repo)


def git_state(path, branch, base):
    """(commits on branch not in base, changed files in path) or (None, None)."""
    ahead = git(path, "rev-list", "--count", f"{base}..{branch}") if branch else None
    status = git(path, "status", "--porcelain") if path and Path(path).is_dir() else None
    dirty = None
    if status is not None:
        # Linked tool caches such as `.tools` are expected in fresh worktrees.
        dirty = len([l for l in status.splitlines() if l and not l.endswith(" .tools")])
    return (int(ahead) if ahead and ahead.isdigit() else None), dirty


# ---- ledger -----------------------------------------------------------------

def load(task_id):
    path = TASKS / f"{task_id}.json"
    if not path.exists():
        sys.exit(f"no task {task_id}")
    return json.loads(path.read_text())


def save(task):
    TASKS.mkdir(parents=True, exist_ok=True)
    task["updated"] = now()
    tmp = TASKS / f".{task['id']}.json.tmp"
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(TASKS / f"{task['id']}.json")
    write_board()


def all_tasks():
    if not TASKS.exists():
        return []
    return sorted((json.loads(p.read_text()) for p in TASKS.glob("*.json")),
                  key=lambda t: t.get("updated", ""), reverse=True)


def note(task, text, **extra):
    """Log text on the task. extra (such as `options`, the quick answers a blocked task offers) joins the
    conversation event."""
    task.setdefault("log", []).append({"at": now(), "by": PANE or "user", "text": text})
    if task.get("repo"):  # every ledger entry is also an event in the project's conversation
        record(task["repo"], "thread", task=task.get("id"), title=task.get("title"), status=task.get("status"),
               by=PANE or "user", text=text, **extra)


class Why(argparse.Action):
    """`--why TEXT` explains the `--option` right before it (kept as {place of that option: text})."""

    def __call__(self, parser, namespace, value, option_string=None):
        given = getattr(namespace, "option", None) or []
        if not given:
            parser.error("--why explains an answer: put it right after that answer's --option")
        namespace.why = {**(getattr(namespace, "why", None) or {}), len(given) - 1: value}


def quick_answers(a):
    """The answers a question offers: (titles, fields for the task and its conversation event).
    --why gives the --option before it one line of explanation; --recommend says the first answer is
    the one the PM would pick. An answer is kept as written, and it alone is what a pick sends back."""
    raw = [o.strip() for o in getattr(a, "option", None) or []]
    why = {i: (text or "").strip() for i, text in (getattr(a, "why", None) or {}).items()}
    recommend = bool(getattr(a, "recommend", False))
    if recommend and not (raw and raw[0]):
        sys.exit("--recommend marks the first answer as your pick: give that answer with --option")
    if any(text and not (i < len(raw) and raw[i]) for i, text in why.items()):
        sys.exit("--why explains the --option before it, and that one is empty")
    kept = [i for i, title in enumerate(raw) if title]
    titles = [raw[i] for i in kept]
    fields = {"options": titles} if titles else {}
    if any(why.get(i) for i in kept):
        fields["option_notes"] = [why.get(i, "") for i in kept]
    if recommend:
        fields["recommended"] = True
    return titles, fields


QUESTION_FIELDS = ("options", "option_notes", "recommended")


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40].strip("-")


def new_id(project, hint):
    base = f"{project}-{slugify(hint) or datetime.datetime.now().strftime('%m%d-%H%M')}"
    candidate, n = base, 2
    while (TASKS / f"{candidate}.json").exists():
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def write_board():
    tasks = all_tasks()
    lines = [f"# PM Board", "", f"Updated {now()}. Ledger: `{TASKS}`.", ""]
    for project in sorted({t["project"] for t in tasks}):
        mine = [t for t in tasks if t["project"] == project]
        active = [t for t in mine if t["status"] in ACTIVE]
        closed = [t for t in mine if t["status"] in CLOSED][:8]
        lines += [f"## {project}", "", "| Task | Status | Owner | Where | Branch | Updated | Latest |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for t in active + closed:
            latest = (t.get("log") or [{}])[-1].get("text", "").replace("|", "/")[:80]
            where = " ".join(x for x in (t.get("pane"), t.get("agent")) if x)
            lines.append(f"| {t['title']} (`{t['id']}`) | {t['status']} | {t.get('owner', '')} | {where} "
                         f"| {t.get('branch') or ''} | {t['updated'][5:]} | {latest} |")
        lines.append("")
    STATE.mkdir(parents=True, exist_ok=True)
    BOARD.write_text("\n".join(lines))


TURN_LOG = STATE / "turns.log"


def turn_log(text):
    """Append one line to the turn log; hooks must never fail, so failures are swallowed."""
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with open(TURN_LOG, "a") as f:
            f.write(f"{now()} [{PANE or '-'}] {text}\n")
    except OSError:
        pass


# ---- commands ---------------------------------------------------------------

FIELDS = ["title", "status", "owner", "workspace", "pane", "agent", "branch", "worktree",
          "base", "brief", "commit", "release", "parent"]


def parent_of(task_id, parent):
    """`--parent`: the id of the task this one was split from (the project view lists it under that task).
    Checked against the ledger: a task id that exists, and no loop (the task itself, or one split from it,
    as its parent); '' removes it."""
    if not parent:
        return parent
    if not re.fullmatch(r"[^/\\\s.][^/\\\s]*", parent) or ".." in parent:  # a file name in tasks/, nothing more
        sys.exit(f"not a task id: {parent}")
    if not (TASKS / f"{parent}.json").exists():
        sys.exit(f"no task {parent} to be the parent of {task_id or 'this task'}")
    seen, up = set(), parent
    while up and up not in seen:
        if up == task_id:
            sys.exit(f"{parent} cannot be the parent of {task_id}: that would make a loop")
        seen.add(up)
        path = TASKS / f"{up}.json"
        up = json.loads(path.read_text()).get("parent") if path.exists() else None
    return parent


def remember_session(task):
    """A Claude Code session that writes to the ledger from the task's own terminal is the task's agent: its id
    lets `reattach` resume it once that terminal is gone. A PM's session is not the agent of the tasks parked on
    its pane, so it is not recorded."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if sid and PANE and task.get("pane") == PANE and not pm_record_for_pane(PANE):
        task["session"] = {"kind": "claude", "id": sid}


def cmd_new(a):
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    project = Path(repo).name
    pm = find_pm()
    task = {"id": new_id(project, a.slug or a.branch or a.title), "title": a.title, "project": project,
            "repo": repo, "status": a.status, "base": a.base or base_branch(repo),
            "owner": a.owner or ("pm" if pm and pm.get("pane_id") == PANE else "self"),
            # An explicit empty --pane/--workspace records work that is not tied to this session.
            "workspace": WORKSPACE if a.workspace is None else a.workspace,
            "pane": PANE if a.pane is None else a.pane, "created": now()}
    for f in ("agent", "branch", "worktree", "brief", "kind"):
        if getattr(a, f, None):
            task[f] = getattr(a, f)
    if getattr(a, "parent", None):
        task["parent"] = parent_of(task["id"], a.parent)
    remember_session(task)
    # A question for the user that belongs to no task yet: a blocked entry of its own, with its quick answers.
    options, asked = quick_answers(a)
    task.update(asked)
    note(task, a.note or f"registered ({task['status']})", **asked)
    save(task)
    print(task["id"])
    return task["id"]


def cmd_update(a):
    task = load(a.id)
    ask = getattr(a, "ask", False)
    if ask and getattr(a, "status", None) != "blocked":
        sys.exit(tr("--ask goes with --status blocked: it asks the user a follow-up",
                    "--ask 要和 --status blocked 一起用：它是向用户追问"))
    # Blocked again once the user has answered is a new question (asks_again): only with --ask. Recording the
    # answer is moving the task on; blocked means waiting for the user.
    log = PROJECTS / project_slug(task["repo"]) / "conversation.jsonl" if task.get("repo") else None
    if getattr(a, "status", None) == "blocked" and task["status"] == "blocked" and not ask and log and \
            task["id"] in answered_tasks(conversation_events(log), {task["id"]: task.get("title") or ""},
                                         {task["id"]: asked_at(task)}):
        sys.exit(tr(f"{task['id']}: the user has already answered. To record the answer, use --status in_progress "
                    "or --status done with --note; to ask a follow-up, add --ask.",
                    f"{task['id']}：用户已经回答了。要记下回答，用 --status in_progress 或 --status done 加 --note；"
                    "确实要追问，加 --ask。"))
    changes = []
    if getattr(a, "parent", None) is not None:
        parent_of(task["id"], a.parent)
    for f in FIELDS:
        value = getattr(a, f, None)
        if f == "parent" and value == "" and "parent" in task:
            changes.append("parent=")
            task.pop("parent")
        elif value is not None and task.get(f, "" if f == "parent" else None) != value:
            changes.append(f"{f}={value}")
            task[f] = value
        elif f == "status" and value == "blocked":
            # Blocked again while blocked: a new question (asks_again), even with the status unchanged.
            changes.append("status=blocked")
    # Quick answers the user can pick in the project view; they belong to the question being asked now,
    # so a status change without new ones drops the old ones.
    options, asked = quick_answers(a)
    offered = bool(options) and {f: task.get(f) for f in QUESTION_FIELDS if f in task} != asked
    if any(c.startswith("status=") for c in changes):
        task.pop("paused_from", None)  # set by an archive; a status given by hand replaces it
        task.pop("escalating", None)  # an escalation's question is over once the task moves on (declined, or not)
    if options or any(c.startswith("status=") for c in changes):
        for f in QUESTION_FIELDS:
            task.pop(f, None)
        task.update(asked)
    if a.note or changes or offered:
        text = "; ".join(x for x in [", ".join(changes), a.note] if x) or " / ".join(options)
        note(task, text, **asked)
    remember_session(task)
    save(task)
    print(f"{task['id']}: {task['status']}")
    # A merged task that the PM dispatched is cleaned up at once; its worker, worktree and branch have no further use.
    # Its review has done its job in any case, even when the worker is kept (retire closes it otherwise).
    auto = "status=merged" in changes and task.get("dispatched") and not a.keep
    closed = retire_review(task) if "status=merged" in changes and not auto else []
    if closed:
        print(f"{task['id']}: closed {', '.join(closed)}")
    if auto:
        try:
            cmd_retire(argparse.Namespace(id=task["id"], force=False))
        except SystemExit as stop:
            print(f"not retired: {stop}. Fix that, then run `pm.py retire {task['id']}`.")


def needs_cleanup(task):
    """Merged or released, but its worker terminal, worktree or branch has not been removed with `retire`."""
    return task["status"] in ("merged", "released") and not task.get("retired") and bool(
        task.get("branch") or task.get("worktree"))


def cmd_log(a):
    task = load(a.id)
    note(task, a.text)
    save(task)


def cmd_show(a):
    task = load(a.id)
    ahead, dirty = git_state(task.get("worktree") or task["repo"], task.get("branch"), task["base"])
    print(json.dumps({**task, "live": {"ahead": ahead, "dirty": dirty}}, ensure_ascii=False, indent=2))


def cmd_board(a):
    write_board()
    print(BOARD.read_text())


def cmd_status(a):
    listing = agents()
    by_pane = {x["pane_id"]: x for x in listing}
    labels = {w["workspace_id"]: w.get("label") for w in (herdr("workspace", "list") or {}).get("workspaces", [])}
    pm_panes = {x["pane_id"] for x in listing if str(x.get("name") or "").startswith("pm-")}
    print("PMs:")
    for x in listing:
        if x["pane_id"] in pm_panes:
            print(f"  {x['name']}  {x['pane_id']}{' (this session)' if x['pane_id'] == PANE else ''}  "
                  f"{x.get('agent_status')}  {x.get('cwd')}")
    in_hc = [pm for pm in (hc_pm(json.loads(p.read_text()).get("repo") or "") for p in sorted(PMS.glob("*.json"))
                           if json.loads(p.read_text()).get("runtime") == "hc") if pm] if PMS.exists() else []
    for pm in in_hc:
        print(f"  {pm['name']}  {pm['pane_id']}{' (this session)' if pm['pane_id'] == PANE else ''}  "
              f"{pm['agent_status']}  {pm['cwd']}")
    if not pm_panes and not in_hc:
        print("  (none)")
    tasks = all_tasks()
    # Merged or released work stays listed until `retire` removes its worktree and branch.
    active = [t for t in tasks if t["status"] in ACTIVE or (a.all and t["status"] in CLOSED)
              or (t["status"] in ("merged", "released") and not t.get("retired"))]
    linked_panes, linked_branches = set(), set()
    hc_live = live_hc_terminals() if any((t.get("pane") or "").startswith("hc:") for t in active) else None
    print("\nTasks:")
    for t in active:
        live = by_pane.get(t.get("pane") or "", {})
        state = live.get("agent_status", "-") if t.get("pane") else "-"
        ahead, dirty = git_state(t.get("worktree") or t["repo"], t.get("branch"), t["base"])
        linked_panes.add(t.get("pane"))
        linked_branches.add((t["repo"], t.get("branch")))
        latest = (t.get("log") or [{}])[-1].get("text", "")[:70]
        print(f"  [{t['status']}] {t['id']}  {t['title']}\n"
              f"      {t.get('pane') or '-'} {live.get('name') or t.get('agent') or ''} agent={state} "
              f"branch={t.get('branch') or '-'} ahead={ahead} dirty={dirty} updated={t['updated'][5:]}\n"
              f"      latest: {latest}"
              + (f"\n      not retired: run `pm.py retire {t['id']}`" if needs_cleanup(t) else "")
              + (f"\n      offline: its terminal is gone; `pm.py reattach {t['id']}` brings its agent back"
                 if task_offline(t, hc_live, set(by_pane) if listing else None) else ""))
    if not active:
        print("  (none)")
    # Work nobody registered: a busy or diverged pane, or a diverged worktree branch.
    found, repos = [], set()
    for x in listing:
        if x["pane_id"] in linked_panes or x["pane_id"] in pm_panes:
            continue
        repo = main_root(x.get("cwd") or "")
        if not repo:
            continue
        repos.add(repo)
        branch = git(x["cwd"], "branch", "--show-current")
        if (repo, branch) in linked_branches:
            continue
        ahead, dirty = git_state(x["cwd"], branch, base_branch(repo))
        if x.get("agent_status") == "working" or (ahead or 0) > 0 or (dirty or 0) > 0:
            found.append(f"  pane {x['pane_id']} [{labels.get(x.get('workspace_id'), '')}] {x.get('agent')} "
                         f"{x.get('agent_status')} {Path(repo).name}:{branch} ahead={ahead} dirty={dirty} "
                         f"— {x.get('terminal_title_stripped', '')[:60]}")
    for repo in repos | {t["repo"] for t in active}:
        base = base_branch(repo)
        porcelain = git(repo, "worktree", "list", "--porcelain") or ""
        for block in porcelain.split("\n\n"):
            path = re.search(r"^worktree (.+)$", block, re.M)
            branch = re.search(r"^branch refs/heads/(.+)$", block, re.M)
            if not path or not branch or branch.group(1) == base or (repo, branch.group(1)) in linked_branches:
                continue
            if any(t["repo"] == repo and t.get("branch") == branch.group(1) for t in tasks):
                continue
            ahead, dirty = git_state(path.group(1), branch.group(1), base)
            if (ahead or 0) > 0 or (dirty or 0) > 0:
                found.append(f"  worktree {path.group(1)} {Path(repo).name}:{branch.group(1)} "
                             f"ahead={ahead} dirty={dirty}")
    print("\nUnregistered work:")
    print("\n".join(dict.fromkeys(found)) if found else "  (none)")


def cmd_find(a):
    pm = find_pm(repo=a.repo)
    if not pm:
        sys.exit(1)
    print(pm["pane_id"])


def cmd_claim(a):
    # --pane lets the hub register a PM for another pane, usually a shell where the PM is then started.
    pane = a.pane or PANE
    if not pane:
        sys.exit("not running inside a herdr pane; pass --pane")
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    pm = find_pm(repo=repo)
    if pm and pm["pane_id"] != pane:
        sys.exit(f"PM for {Path(repo).name} already exists at {pm['pane_id']}; ask the user before replacing it")
    name = pm_name(repo)
    kind = getattr(a, "kind", None) or ""
    if pane.startswith("hc:"):
        workspace = ""
        if hc("label", pane[3:], f"pm={Path(repo).name}") is None:
            sys.exit(f"hc label {pane[3:]} failed")
        name_tab(pane[3:], pm_tab_name(repo))
        kind = kind or terminal_kind(hc("get", pane[3:]) or {})
    elif pane == PANE:
        workspace = WORKSPACE
        if not herdr("agent", "rename", PANE, name):
            sys.exit(f"herdr agent rename {PANE} {name} failed")
    else:
        # A shell pane has no agent to rename yet: start it with `herdr agent start <name>`.
        workspace = ((herdr("pane", "get", pane) or {}).get("pane") or {}).get("workspace_id")
        if not workspace:
            sys.exit(f"no herdr pane {pane}")
    PMS.mkdir(parents=True, exist_ok=True)
    rec_path = PMS / f"{project_slug(repo)}.json"
    rec = json.loads(rec_path.read_text()) if rec_path.exists() else {}
    rec.update({"project": Path(repo).name, "repo": repo, "name": name, "pane": pane, "workspace": workspace,
                "claimed": now()})
    rec.pop("discord", None)  # written by earlier versions
    if kind:
        rec["agent"] = kind  # which program this PM is: its successor is started the same way
    for key in ("runtime", "terminal"):
        rec.pop(key, None)
    if pane.startswith("hc:"):
        rec.update({"runtime": "hc", "terminal": pane[3:]})
    print(f"{pane} is now {name} (PM for {Path(repo).name})")
    rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    if pane != PANE and not pane.startswith("hc:"):
        print(f"start it: herdr agent start {name} --kind {kind or 'claude'} --pane {pane} -- <your usual flags>")


def cmd_notify(a):
    pm = find_pm(repo=a.repo)
    if not pm:
        print("no PM in herdr; the ledger entry is enough")
        return
    if pm["pane_id"] == PANE:
        print("this session is the PM")
        return
    text = f"[from {PANE or 'a session'}] {a.text}"
    if pm["pane_id"].startswith("hc:"):
        result = hc("send", pm["pane_id"][3:], text)
    else:
        result = herdr("agent", "prompt", pm["pane_id"], text)
    print(f"notified PM at {pm['pane_id']}" if result else "notify failed; the ledger entry still records it")


def cmd_dispatch(a):
    repo = main_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not in a git repository")
    brief = Path(a.brief).read_text()
    parent_of("", getattr(a, "parent", None))
    worker_defaults(a)
    held = held_task(repo, a.branch)
    if asks_first(a) and not getattr(a, "confirmed", False):
        return ask_first(a, repo, held)
    if PANE.startswith("hc:"):
        return dispatch_hc(a, repo, brief, held)
    place = (held or {}).get("held_in") or {}
    if place.get("pane") and Path(held.get("worktree") or "").is_dir():
        # A worker that exited at once: its worktree and pane are used again.
        workspace, pane, path = place.get("workspace") or "", place["pane"], held["worktree"]
    else:
        created = herdr("worktree", "create", "--cwd", repo, "--branch", a.branch, "--base",
                        a.base or base_branch(repo), "--label", a.label, "--no-focus")
        if not created:
            sys.exit("herdr worktree create failed")
        flat = json.dumps(created)
        found = [re.search(rf'"{k}": "([^"]+)"', flat) for k in ("workspace_id", "pane_id", "path")]
        if not all(found):
            sys.exit(f"unexpected worktree create result: {flat[:600]}")
        workspace, pane, path = (m.group(1) for m in found)
        if a.prep:
            subprocess.run(["zsh", "-c", a.prep], cwd=path, check=True, env={**os.environ, "MAIN": repo})
    args = ["agent", "start", a.name, "--kind", a.kind, "--pane", pane]
    argv = worker_argv(a, outside_reads(repo, a.brief))
    if len(argv) > 1:
        args += ["--", *argv[1:]]
    if not herdr(*args):
        sys.exit(f"agent start failed in {pane}")
    # Registered before the brief goes out: the report section names the task.
    task_id = register_worker(a, repo, held, workspace=workspace, pane=pane, worktree=path)["id"]
    sent = keep_sent(task_id, brief)
    # With an advisor, a worker gone from its pane exited at once: see advisor_refused.
    gone = lambda: a.advisor and tui_agent_gone(pane)
    if not herdr("agent", "prompt", a.name, sent.read_text()):
        if gone():
            hold_exited(task_id, a, tr("(no agent in the pane)", "（窗格里已经没有 agent）"),
                        {"workspace": workspace, "pane": pane})
        sys.exit(f"prompt failed; the agent is running. Send the brief by hand: "
                 f"herdr agent prompt {a.name} \"$(cat {shlex.quote(str(sent))})\"")
    # A startup screen (for example codex's hook trust review) can swallow the brief.
    if not herdr("agent", "wait", a.name, "--until", "working", "--timeout", "20000"):
        if gone():
            hold_exited(task_id, a, tr("(no agent in the pane)", "（窗格里已经没有 agent）"),
                        {"workspace": workspace, "pane": pane})
        print(f"warning: {a.name} did not start working; read its screen and resend the brief from {sent}",
              file=sys.stderr)
    print(f"workspace={workspace} pane={pane} worktree={path}")


def tui_agent_gone(pane):
    """In the herdr terminal UI: no agent runs in this pane any more (False when the list is not known)."""
    listing = agents()
    return bool(listing) and pane not in {x.get("pane_id") for x in listing}


def is_fable(model):
    return "fable" in (model or "").lower()


def asks_first(a):
    """The user decides before a Fable worker starts (the user's words: "deep 档先问我"): a profile in ASK_FIRST,
    or any Fable model, however it was named. A Fable advisor is hard's, which the PM picks on its own."""
    return a.profile in ASK_FIRST or is_fable(a.model)


def hold_exited(task_id, a, seen, place=None):
    """A worker started with an advisor exited at once: most likely the account has not agreed to Fable's billing.
    The task is blocked with a question and parked on the PM's pane (its terminal is gone, and the thread is not
    offline work to reattach); nothing is started again. place: the herdr TUI workspace and pane, used again by the
    next dispatch. Exits."""
    task = load(task_id)
    answers = [tr("I ran /model fable: dispatch again", "已运行 /model fable，重新派发"), no_fable_answer("hard")]
    task.update(status="blocked", held="advisor", options=answers, pane=PANE)
    if place:
        task["held_in"] = place
    note(task, tr(f"status=blocked; the worker exited at once with advisor {a.advisor} (its screen: {seen}). ",
                  f"status=blocked；带 advisor {a.advisor} 起的 worker 一启动就退出了（屏幕：{seen}）。")
         + advisor_refused(a), options=answers)
    save(task)
    sys.exit(tr(f"{task_id}: blocked. The worker exited at once with --advisor {a.advisor}: ",
                f"{task_id}：已标成 blocked。带 --advisor {a.advisor} 的 worker 一启动就退出了：")
             + advisor_refused(a)
             + tr(" Then run the same dispatch again; it reuses this task and its worktree.",
                  "之后再运行同一条 dispatch，会接着用这个任务和它的工作树。"))


def held_task(repo, branch):
    """The task dispatch registered for this branch without a worker at work in it: blocked on the user's yes to
    Fable ("held": "ask"), or on a worker that exited at once ("advisor"). Running dispatch again takes it up."""
    return next((t for t in all_tasks() if t.get("held") and t.get("status") == "blocked"
                 and t.get("repo") == repo and t.get("branch") == branch), None)


def dispatch_note(a):
    text = f"dispatched to {a.name} ({worker_summary(a)})"
    if a.advisor_dropped:
        text += tr(f"; {a.kind} takes no advisor, advisor {a.advisor_dropped} left out",
                   f"；{a.kind} 没有 advisor 参数，已忽略 advisor {a.advisor_dropped}")
    return text + fallback_said(a)


def register_worker(a, repo, held, **where):
    """The ledger entry of a worker dispatch started: a new task, or the held one taken up again. `where`: its
    workspace, pane and worktree. The task keeps what the worker runs as (`worker`) and, for escalation later,
    `escalations` and `rounds`."""
    if held:
        task = held
        # "session": a session that wrote the held entry is not this worker's (reattach would resume it).
        for f in (*QUESTION_FIELDS, "held", "held_in", "session"):
            task.pop(f, None)
        task.update(status="in_progress", title=a.title, agent=a.name, brief=str(Path(a.brief).resolve()),
                    base=a.base or task.get("base") or base_branch(repo), kind=a.kind, **where)
        if getattr(a, "parent", None):
            task["parent"] = a.parent
        note(task, dispatch_note(a))
        save(task)
        print(task["id"])
    else:
        task = load(cmd_new(argparse.Namespace(repo=repo, title=a.title, status="in_progress", owner="pm",
                                               base=a.base, agent=a.name, branch=a.branch, slug=a.label, kind=a.kind,
                                               brief=str(Path(a.brief).resolve()), note=dispatch_note(a),
                                               parent=getattr(a, "parent", None), **where)))
    task["worker"] = worker_record(a)
    task["worker_pane"] = where.get("pane") or ""  # the pane pm.py started the worker in (see own_worker)
    task.setdefault("escalations", [])
    task.setdefault("rounds", 0)
    save(task)
    return task


def ask_first(a, repo, held):
    """A Fable worker waits for the user's yes (see asks_first): the task is registered blocked with a question
    card, and no worktree or worker is made. The same dispatch run again takes it up: with --confirmed once the
    user agreed, or with another profile."""
    model = " ".join(x for x in (a.kind, a.model, a.effort) if x)
    what = tr(f"profile {a.profile} ({model})", f"{a.profile} 档（{model}）") if a.profile else model
    again = tr(f"Once the user agrees, run the same dispatch with --confirmed; for hard, with --profile hard.",
               f"用户同意后，加 --confirmed 再运行同一条 dispatch；改用 hard 就把 --profile 换成 hard 再运行。")
    if held and held.get("held") == "ask":
        print(tr(f"{held['id']}: still waiting for the user's answer on {what}. {again}",
                 f"{held['id']}：还在等用户回答是否用 {what}。{again}"))
        return held["id"]
    asked = tr(f"This task would run on {what}; the user decides before it starts. Agree?",
               f"这个任务要用 {what}，派发前先问你：同意吗？")
    options = [tr(f"Agree: {what}", f"同意，用 {what}"), tr("Use hard instead", "改用 hard")]
    if held:  # held for another reason (its worker exited at once): this question takes that one's place
        task = held
        for f in QUESTION_FIELDS:
            task.pop(f, None)
        task.update(options=options)
        note(task, asked, options=options)
    else:
        task = load(cmd_new(argparse.Namespace(
            repo=repo, title=a.title, status="blocked", owner="pm", base=a.base, workspace=None, pane=None,
            agent=None, branch=a.branch, worktree=None, brief=str(Path(a.brief).resolve()), slug=a.label,
            note=asked, option=options, parent=getattr(a, "parent", None))))
    task_id = task["id"]
    task["held"] = "ask"
    save(task)
    print(tr(f"{task_id}: blocked, no worker started: {what} needs the user's yes. {again}",
             f"{task_id}：已登记为 blocked，没有起 worker：{what} 要先等用户同意。{again}"))
    return task_id


def no_fable_answer(profile):
    """The question card's answer for a user who has no Fable at all (Bedrock, Vertex, a gateway, an account
    without it): /model fable does not help them."""
    return tr(f'No Fable: use {profile} without the advisor, and set "fable": false in config.json',
              f'没有 Fable：改用不带 advisor 的 {profile}，并在 config.json 里设置 "fable": false')


def advisor_refused(a):
    return tr(f"this account has not agreed to Fable's billing yet, or cannot use Fable at all. Billing: run /model "
              f"fable once in any Claude session. No Fable: use hard without the advisor (`--profile "
              f"{a.profile or 'hard'} --advisor none`), and set \"fable\": false in config.json so that hard runs "
              f"without it and no Fable is used again.",
              f"这个账号还没同意 Fable 计费，或者根本用不了 Fable。计费的问题：在任意 Claude 会话里运行一次 /model fable。"
              f"没有 Fable：改用不带 advisor 的 hard（`--profile {a.profile or 'hard'} --advisor none`），"
              f"并在 config.json 里设置 \"fable\": false，以后 hard 不带 advisor，也不会再用 Fable。")


def keep_sent(task_id, brief):
    """The brief as the worker gets it, report section included, kept as sent/<id>.md for a resend."""
    path = STATE / "sent" / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(brief + report_section(task_id) + docs_line())
    return path


def docs_line():
    """Said to every worker and reviewer where Herdr's API docs are: they are let read them (outside_reads), and the
    running app keeps its state in that folder, so nothing is written there."""
    if not HERDR_DOCS.is_dir():
        return ""
    where = f"~/{HERDR_DOCS.relative_to(Path.home())}" if HERDR_DOCS.is_relative_to(Path.home()) else str(HERDR_DOCS)
    return "\n" + tr(f"Herdr's API docs in {where} are for reading only: write nothing there (the running app keeps "
                     "its state in it).",
                     f"{where} 里的 Herdr API 文档只读：不要往这个目录写任何东西（正在运行的 Herdr 在里面存状态）。") + "\n"


def pm_command():
    """How a worker runs this script: the installed copy, with the ledger home when it is not the default."""
    home = f"PM_HOME={shlex.quote(str(STATE))} " if os.environ.get("PM_HOME") else ""
    return f"{home}python3 {shlex.quote(str(Path(__file__).resolve()))}"


def report_section(task_id):
    """Appended to every brief: the worker reports in the ledger, and that report is all the PM reads."""
    cmd = pm_command()
    return "\n\n" + tr(
        f"Reporting (task {task_id}):\n"
        f"- When done: `{cmd} update {task_id} --status review --commit <sha> --note \"<what changed; which "
        "checks ran; what was not verified>\"`\n"
        f"- When a person has to decide something: `{cmd} update {task_id} --status blocked --note \"<the question>\"`\n"
        "The PM reads only this report, never your screen. Keep the note under 600 characters, and write it, "
        "like every ledger note, in the user's language: the user reads it in the thread panel.",
        f"汇报（任务 {task_id}）：\n"
        f"- 做完时：`{cmd} update {task_id} --status review --commit <sha> --note \"<改了什么；跑了哪些检查；"
        "哪些没验证>\"`\n"
        f"- 需要人来决定时：`{cmd} update {task_id} --status blocked --note \"<问题>\"`\n"
        "PM 只看这条汇报，不会读你的屏幕。写在 600 字以内；这条和所有台账记录都用中文写，用户会在线程侧栏里读到。") + "\n"


def config():
    """Personal settings: config.json in the ledger home, for example
    {"worker": {"kind": "codex", "model": "...", "effort": "high"}, "pm": {"kind": "claude"}}."""
    try:
        return json.loads((STATE / "config.json").read_text())
    except (OSError, ValueError):
        return {}


def tr(en, zh):
    """Built-in text in the configured language: English unless config.json says {"lang": "zh"}."""
    return zh if config().get("lang") == "zh" else en


# Profiles: a PM picks a word (`dispatch --profile hard`), not a model ID. config.json's `profiles` replaces or adds
# whole entries ({"profiles": {"hard": {"kind": "codex", "effort": "xhigh"}}}); a profile without a kind is Claude's.
PROFILES = {
    "light": {"kind": "claude", "model": "sonnet", "effort": "medium"},
    "standard": {"kind": "claude", "model": "opus"},
    "hard": {"kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"},
    "deep": {"kind": "claude", "model": "fable", "effort": "high"},
}
# The user decides before these start, as before any Fable worker (asks_first): dispatch only asks, until --confirmed.
ASK_FIRST = ("deep",)
# Who reviews a profile's work, a model other than the one that wrote it; config.json's `review` changes entries.
# A value is a Claude model, or {"kind": ..., "model": ..., "effort": ...}.
REVIEW_MODELS = {"light": "opus", "standard": "fable", "hard": "fable", "deep": "opus"}
# Without Fable (config.json {"fable": false}: Bedrock, Vertex, a gateway, an account without it): hard runs without
# its Fable advisor, deep is not offered, and a review the table gave to Fable goes to this model, not Opus, so the
# model that wrote the code does not review it. Profiles and review entries the user wrote still win.
NO_FABLE_REVIEWER = "sonnet"
# What a Claude process that runs on Fable falls back to when Fable cannot be used (`--fallback-model`).
FABLE_FALLBACK = {"worker": "opus", "reviewer": "sonnet"}


def fable_on():
    """Fable can be used here: true unless config.json says {"fable": false}."""
    return config().get("fable", True) is not False


def builtin_profiles():
    if fable_on():
        return PROFILES
    return {k: {f: x for f, x in v.items() if not (f == "advisor" and is_fable(x))}
            for k, v in PROFILES.items() if not is_fable(v.get("model"))}


def profiles():
    mine = config().get("profiles") or {}
    return {**builtin_profiles(), **{k: v for k, v in mine.items() if isinstance(v, dict)}}


def review_models():
    table = REVIEW_MODELS if fable_on() else {k: NO_FABLE_REVIEWER if is_fable(v) else v
                                              for k, v in REVIEW_MODELS.items()}
    return {**table, **(config().get("review") or {})}


def fable_fallback(kind, model, role="worker"):
    """The --fallback-model for a Claude process that runs on Fable, else "". Claude switches without a word (only
    its session log says so), so the dispatch and review notes name it. A Fable advisor is not covered: an advisor
    that cannot be used makes Claude exit at once whatever the fallback (see hold_exited)."""
    return FABLE_FALLBACK[role] if kind == "claude" and is_fable(model) else ""


def fallback_said(a):
    fallback = getattr(a, "fallback", "")
    return tr(f"; falls back to {fallback} if Fable cannot be used", f"；Fable 不可用时会退到 {fallback}") \
        if fallback else ""


def worker_defaults(a, role="worker"):
    """Fill the worker's profile, kind, model, effort and advisor. The command line wins; then the profile it names;
    else config.json (the role's key, a reviewer falling back to "worker"; that key may name a profile, its other
    keys then change that profile); then the program's own defaults. Nothing configured: as before profiles."""
    cfg = config().get(role) or config().get("worker") or {}
    name = getattr(a, "profile", None) or cfg.get("profile") or ""
    base = cfg
    if name:
        table = profiles()
        if name not in table:
            off = name in PROFILES and not fable_on()
            sys.exit(tr(f"no profile {name}; known: {', '.join(table)}"
                        + (' (config.json has "fable": false: no Fable here)' if off else ""),
                        f"没有档位 {name}；已有：{', '.join(table)}"
                        + ("（config.json 里设了 \"fable\": false，这里用不了 Fable）" if off else "")))
        base = {"kind": "claude", **table[name]}
        if not getattr(a, "profile", None):
            extra = {k: v for k, v in cfg.items() if k != "profile"}
            if extra.get("kind") and extra["kind"] != base["kind"]:
                base = {}  # the profile's model, effort and advisor are its program's, not this one's
            base.update(extra)
    default = base.get("kind") or "codex"
    a.kind = a.kind or default
    # A configured model or effort belongs to the configured program, not to another one named on the command line.
    mine = base if a.kind == default else {}
    a.model = a.model or mine.get("model") or ""
    a.effort = a.effort or mine.get("effort") or ""
    given = getattr(a, "advisor", None)
    a.advisor = "" if given == "none" else given or mine.get("advisor") or ""
    # Only some programs take an advisor; for the others it is left out, and the dispatch note says so.
    a.advisor_dropped = a.advisor if a.advisor and not (agent_kinds().get(a.kind) or {}).get("advisor") else ""
    if a.advisor_dropped:
        a.advisor = ""
    a.fallback = fable_fallback(a.kind, a.model, "reviewer" if role == "reviewer" else "worker")
    a.profile = name
    return a


def worker_record(a):
    """The task's `worker` field: what the worker was actually started with."""
    return {"profile": a.profile, "kind": a.kind, "model": a.model, "effort": a.effort, "advisor": a.advisor}


def worker_summary(a):
    """"hard: claude opus xhigh, advisor fable", or "codex" without a profile, as the dispatch note says it."""
    said = " ".join(x for x in (a.kind, a.model, a.effort) if x) + (f", advisor {a.advisor}" if a.advisor else "")
    return f"{a.profile}: {said}" if a.profile else said


# How each coding agent is started, as a PM or as a worker. "{}" stands for the value. `prompt_arg`: the program
# takes its first prompt as a trailing argument; without it the prompt is typed in once the program is ready.
# config.json adds or overrides kinds: {"agents": {"mine": {"argv": ["mine", "--yes"], "model": ["--model", "{}"]}}}.
AGENT_KINDS = {
    # --advisor is not in `claude --help`; a Fable advisor needs the account to have agreed to Fable's billing once.
    "claude": {"argv": ["claude"], "model": ["--model", "{}"], "effort": ["--effort", "{}"],
               "advisor": ["--advisor", "{}"], "fallback": ["--fallback-model", "{}"], "prompt_arg": True},
    # No update prompt at startup: it would take the place of the input and the brief could not be delivered.
    "codex": {"argv": ["codex", "-c", "check_for_update_on_startup=false"], "model": ["-m", "{}"],
              "effort": ["-c", 'model_reasoning_effort="{}"'], "prompt_arg": True},
    "pi": {"argv": ["pi"], "model": ["--model", "{}"], "effort": ["--thinking", "{}"], "prompt_arg": True},
    "gemini": {"argv": ["gemini"], "model": ["-m", "{}"], "effort": []},
    "opencode": {"argv": ["opencode"], "model": ["-m", "{}"], "effort": []},
}
# What herdr-core calls a program where that differs from the kind's name.
APP_KINDS = {"claude-code": "claude"}


def agent_kinds():
    kinds = {k: dict(v) for k, v in AGENT_KINDS.items()}
    for name, spec in (config().get("agents") or {}).items():
        if isinstance(spec, dict) and spec.get("argv"):
            kinds[name] = {**kinds.get(name, {}), **spec}
    return kinds


def agent_argv(kind, model="", effort="", prompt=None, advisor="", fallback=""):
    """The command that starts an agent of this kind. An unknown kind is run as written ("myagent --flag").
    fallback: the model to switch to when `model` cannot be used, for programs that take one (see fable_fallback)."""
    spec = agent_kinds().get(kind)
    if not spec:
        return shlex.split(kind)
    fill = lambda flags, value: [f.replace("{}", value) for f in flags or []] if value else []
    return (list(spec["argv"]) + fill(spec.get("model"), model) + fill(spec.get("effort"), effort)
            + fill(spec.get("advisor"), advisor) + fill(spec.get("fallback"), fallback)
            + ([prompt] if prompt and spec.get("prompt_arg") else []))


def takes_prompt(kind):
    return bool((agent_kinds().get(kind) or {}).get("prompt_arg"))


def terminal_kind(term):
    """The kind of the agent running in a herdr-core terminal, from its program."""
    argv = (term.get("foreground") or {}).get("argv") or term.get("argv") or []
    program = Path(argv[0]).name if argv else ""
    for kind, spec in agent_kinds().items():
        if program and program == Path(spec["argv"][0]).name:
            return kind
    app = (term.get("status") or {}).get("app") or ""
    return APP_KINDS.get(app, app) or program


def send_when_ready(term, text, tries=8, pause=3, strict=False, trust=None, stop_on_exit=False):
    """Type text into an agent once its input is ready; a send that comes too early is refused.

    strict: never send before the program reports a status. A startup dialog has none, and it takes the pasted
    text and Enter as its answer (Claude Code's folder trust then picks "No, exit"). trust: a worktree dispatch
    made under ~/.herdr/worktrees; a folder-trust dialog for it is answered with its own Yes option, once.
    stop_on_exit: give up at once when the program has exited, instead of waiting out the tries."""
    trust = trust and Path(trust).resolve().is_relative_to((Path.home() / ".herdr" / "worktrees").resolve())
    for attempt in range(tries):
        time.sleep(pause)
        info = hc("get", term) or {}
        if stop_on_exit and info.get("state") not in (None, "live"):
            return False
        status = info.get("status")
        if trust:
            keys = trust_keys(screen_of(term))
            if keys:
                trust = not hc("keys", term, *keys)
                continue
        # Without strict, a program that reports no status at all gets the text after a short wait.
        ready = status.get("state") in ("idle", "done") if status else not strict and attempt >= 2
        sent = (hc("send", term, text) or {}) if ready else {}
        # A program that reports no status cannot say a turn started: the text went in, it is not typed again.
        if sent.get("started") or (not status and "started" in sent and sent.get("status") is None):
            return True
    return False


def screen_of(term):
    return (hc("read", term) or {}).get("text") or ""


# How Claude Code and codex ask whether to trust a folder.
TRUST_ASKS = ("trust this folder", "trust the files in this folder", "trust the contents of this directory",
              "allow codex to work in this folder")
OPTION = r"\s*(?:([❯›>])\s*)?(?:\d+\.\s*)?(Yes|No)\b"


def trust_keys(screen):
    """The keys that move a folder-trust dialog's cursor to its Yes option and confirm it, or None when the
    screen is not such a dialog. The default is not trusted: Claude Code puts the cursor on "No, exit"."""
    if not any(ask in screen.lower() for ask in TRUST_ASKS):
        return None
    options = [m for m in map(lambda line: re.match(OPTION, line), screen.splitlines()) if m]
    cursor = [i for i, m in enumerate(options) if m.group(1)]
    yes = [i for i, m in enumerate(options) if m.group(2) == "Yes"]
    if len(cursor) != 1 or len(yes) != 1:
        return None
    step = yes[0] - cursor[0]
    return ["down"] * step + ["up"] * -step + ["enter"]


def screen_line(term, width=160):
    """What a terminal shows, as one line for the task log."""
    lines = [s.strip() for s in screen_of(term).splitlines() if s.strip().strip("─━│╭╮╰╯ ")]
    return clip(" / ".join(lines[:3]), width) or "(empty screen)"


def worker_argv(a, reads=()):
    """reads: paths outside the worktree the worker is let read (outside_reads)."""
    argv = agent_argv(a.kind, a.model, a.effort, advisor=getattr(a, "advisor", ""), fallback=getattr(a, "fallback", ""))
    return argv + read_settings(a.kind, list(reads))


# Herdr's mod API docs (herdr.d.ts, AGENTS.md); the running app keeps its state here too, so workers only read it.
HERDR_DOCS = Path.home() / ".config" / "herdr-app"


def outside_reads(repo, *briefs):
    """What a worker reads outside its worktree: each brief's folder, the project's briefs/ (briefs and the
    screenshots they name) and Herdr's API docs. A brief kept in a wide folder (wide_folder) is let through alone,
    not its folder. Every spelling a read may arrive by: Claude Code follows no link."""
    places = [b if wide_folder(b.parent) else b.parent for b in (Path(x).absolute() for x in briefs if x)]
    out = []
    for place in [*places, Path(repo) / "briefs" if repo else None, HERDR_DOCS]:
        if place and place.exists():
            out += [p for p in dict.fromkeys((str(place.absolute()), str(place.resolve()))) if p not in out]
    return out


def wide_folder(place):
    """A folder too wide to let a worker read all of: the root, the home folder and those above it, the shared
    temporary folders."""
    home = Path.home()
    wide = [Path("/"), home, *home.parents, Path("/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir())]
    spell = lambda p: {str(p.absolute()), str(p.resolve())}
    return bool(spell(place) & set().union(*map(spell, wide)))


def read_settings(kind, paths):
    """For Claude Code: `--settings <file>` that lets it read these folders without asking. permissions.allow
    Read rules: auto mode asks before a read outside the working directories, and an allow rule answers it. With
    permissions.blockReadsOutsideWorkingDirectories on, which no allow rule lifts, blockReadsExemptPaths lets the
    same folders through (Claude Code takes that key only from --settings). Reads only: the folders do not become
    working directories (--add-dir would let a worker in acceptEdits write there) and no Edit or Write rule is added.
    A file, not the JSON itself: a short command line. The herdr terminal UI quotes each argument as it types the
    command into a shell (a path with spaces arrives whole), so the path is passed as it is, never quoted here.
    Other programs ask about no such reads."""
    program = Path(((agent_kinds().get(kind) or {}).get("argv") or [""])[0]).name
    if not paths or program != "claude":
        return []
    text = json.dumps({"permissions": {"allow": [f"Read(/{p}/**)" if Path(p).is_dir() else f"Read(/{p})"
                                                 for p in paths],
                                       "blockReadsExemptPaths": paths}}, indent=1, ensure_ascii=False) + "\n"
    path = STATE / "reads" / f"{hashlib.sha1(text.encode()).hexdigest()[:12]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_text() != text:
        path.write_text(text)
    return ["--settings", str(path)]


def worker_placement():
    """How `hc run` places a worker: as a sub-agent of the PM's terminal, so the app lists it under the PM,
    and outliving it, because a rotated PM's terminal ends. No notes typed into the PM: the ledger carries progress."""
    return ["--parent", PANE[3:], "--outlive-parent", "--no-notify"] if PANE.startswith("hc:") else ["--no-parent"]


def worktree_home(repo):
    """Where a project's worktrees are made in the desktop app."""
    return Path.home() / ".herdr" / "worktrees" / Path(repo).name


def dispatch_hc(a, repo, brief, held=None):
    """Dispatch from a PM in the herdr desktop app: a git worktree and a herdr-core terminal for the worker.
    held: a task dispatch registered without a worker (see held_task); its worktree, if it has one, is used again."""
    base = a.base or base_branch(repo)
    path = worktree_home(repo) / a.branch.replace("/", "-")
    if not (held and held.get("worktree") == str(path) and path.is_dir()):
        if path.exists():
            sys.exit(f"{path} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        if git(repo, "worktree", "add", str(path), "-b", a.branch, base) is None:
            sys.exit(f"git worktree add {path} -b {a.branch} {base} failed")
        if a.prep:
            subprocess.run(["zsh", "-c", a.prep], cwd=str(path), check=True, env={**os.environ, "MAIN": repo})
    made = (hc("run", "--bg", *worker_placement(), "--name", a.name, "--cwd", str(path),
               "--", *worker_argv(a, outside_reads(repo, a.brief))) or {}).get("address")
    if not made:
        sys.exit(f"hc run failed; the worktree {path} is ready, start the worker by hand")
    task = register_worker(a, repo, held, workspace="", pane=f"hc:{made}", worktree=str(path))
    task_id = task["id"]
    hc("label", made, f"task={task_id}")
    task["dispatched"] = True  # `update --status merged` retires only what `dispatch` created
    save(task)
    sent = keep_sent(task_id, brief)
    # About a minute for the worker to come up; claude and codex report a status once their input is ready.
    # With an advisor, a worker that exits at once is not waited for: see advisor_refused.
    if not send_when_ready(made, sent.read_text(), tries=30, pause=2, strict=a.kind in ("claude", "codex"),
                           trust=path, stop_on_exit=bool(a.advisor)):
        seen = screen_line(made, width=300)
        if a.advisor and worker_state(made) in ("exited", "removed"):
            end_terminal(made)  # what it said is in the note
            hold_exited(task_id, a, seen)
        task = load(task_id)
        note(task, tr(f"brief not sent; the worker's screen: {seen}", f"任务书没送达；worker 屏幕上是：{seen}"))
        save(task)
        sys.exit(f"the brief was not sent: the worker in hc:{made} is not ready. Its screen: {seen}\n"
                 f"Read it (hc read {made}); once it is ready, send the brief by hand: "
                 f"hc send {made} \"$(cat {shlex.quote(str(sent))})\"")
    print(f"pane=hc:{made} worktree={path}")


def hc_terminal_of(task):
    pane = task.get("pane") or ""
    return pane[3:] if pane.startswith("hc:") else ""


WAIT_POLL = 5  # seconds between looks at the task file


def worker_state(term):
    """Why the worker in a herdr-core terminal is not working: idle, done, blocked, error, exited or removed.
    "" while it works, and when nothing is known (no hc terminal, hc unavailable)."""
    info = hc("get", term, errors=True) if term else None
    if not info:
        return ""
    if (info.get("error") or {}).get("kind") == "not_found":
        return "removed"
    if info.get("error"):
        return ""
    if info.get("state") != "live":
        return "exited"
    state = (info.get("status") or {}).get("state")
    return state if state in ("idle", "done", "blocked", "error") else ""


def cmd_wait(a):
    """Wait until the worker reports in the ledger; print that report, never the worker's screen.

    A task already past in_progress (the PM answered a blocked worker or sent review findings) counts as
    reported only once a new log entry arrives, so an old report is not returned again."""
    deadline, stopped, last = time.time() + a.timeout, 0, ""
    task = load(a.id)
    term = hc_terminal_of(task)
    seen = len(task.get("log") or []) if task["status"] != "in_progress" else None
    while True:
        task = load(a.id)
        if task["status"] != "in_progress" and (seen is None or len(task.get("log") or []) > seen):
            latest = (task.get("log") or [{}])[-1]
            ahead, dirty = git_state(task.get("worktree") or task["repo"], task.get("branch"), task["base"])
            print(f"{task['id']}: {task['status']}" + (f" (commit {task['commit']})" if task.get("commit") else ""))
            print(clip(f"{latest.get('at', '')} {latest.get('by', '')}: {latest.get('text', '')}", 600))
            print(f"ahead={ahead} dirty={dirty}")
            return
        # Two looks in a row, so a turn that has only just started (or a report on its way) is not mistaken.
        state = worker_state(term)
        stopped, last = (stopped + 1 if state == last else 1, state) if state else (0, "")
        if stopped >= 2:
            if state in ("exited", "removed"):
                print(tr(f"{a.id}: the worker's terminal hc:{term} has {state} without reporting.",
                         f"{a.id}：worker 的终端 hc:{term} 已{'退出' if state == 'exited' else '被移除'}，没有汇报。"))
            elif state in ("blocked", "error"):
                print(tr(f"{a.id}: the worker is {state} (a prompt it waits on, or an error) and has not reported. "
                         f"It cannot report from there: read its screen (`hc read {term} | tail -40`).",
                         f"{a.id}：worker 处于 {state}（在等一个提示，或出错了），没有汇报。它在那里没法汇报："
                         f"看一下它的屏幕（`hc read {term} | tail -40`）。"))
            else:
                remind = tr(f"[from {PANE or 'the PM'}] Report in the ledger as your brief says: "
                            f"`{pm_command()} update {a.id} --status review|blocked --note \"...\"`",
                            f"[from {PANE or 'PM'}] 请按任务书末尾的说明在台账里汇报：`{pm_command()} update {a.id} "
                            "--status review|blocked --note \"...\"`")
                print(tr(f"{a.id}: the worker stopped ({state}) without reporting. Remind it:",
                         f"{a.id}：worker 停了（{state}）但没有汇报。提醒它："))
                print(f"hc send {term} {shlex.quote(remind)}")
            sys.exit(3)
        if time.time() >= deadline:
            print(tr(f"{a.id}: no new report after {a.timeout} s; wait again.",
                     f"{a.id}：{a.timeout} 秒后仍没有新的汇报，接着等。"))
            sys.exit(2)
        time.sleep(WAIT_POLL)


def checkout_of(repo, branch):
    """The checkout (the main one or a worktree) that has this branch checked out, or None."""
    for block in (git(repo, "worktree", "list", "--porcelain") or "").split("\n\n"):
        path = re.search(r"^worktree (.+)$", block, re.M)
        if path and re.search(rf"^branch refs/heads/{re.escape(branch)}$", block, re.M):
            return path.group(1)
    return None


def end_terminal(term):
    """End and remove a worker's herdr-core terminal; never a PM's. True when there was one to remove."""
    info = (hc("get", term) or {}) if term else {}
    if not info or (info.get("labels") or {}).get("pm"):
        return False
    if info.get("state") == "live":
        hc("kill", term)
    hc("rm", term)
    return True


def close_review(review, text):
    """Retire a review thread (`pm.py review`) and end its reviewer's terminal. It has no worktree or branch of its
    own: it read the task's. Returns what was removed."""
    term = hc_terminal_of(review)
    done = [f"terminal hc:{term}"] if end_terminal(term) else []
    review["retired"] = now()
    if review["status"] in ACTIVE:
        review["status"] = "done"
    note(review, text)
    save(review)
    return [f"{review['id']}"] + done


def retire_review(task, text=None):
    """Close the review thread of a task, if it has one that is still open."""
    path = TASKS / f"{task['id']}-review.json"
    review = json.loads(path.read_text()) if path.exists() else None
    if not review or review.get("retired") or review.get("review_of") != task["id"]:
        return []
    return close_review(review, text or tr(f"retired with {task['id']}", f"随 {task['id']} 一起回收"))


def cmd_retire(a):
    task = load(a.id)
    if task.get("review_of"):  # a review thread: only its reviewer's terminal goes
        done = close_review(task, "retired")[1:]
        print(f"{task['id']} retired: removed " + (", ".join(done) or "nothing"))
        return
    repo, branch, base = task["repo"], task.get("branch"), task["base"]
    worktree = task.get("worktree")
    # A worker that made its own worktree registers only the branch (`pm.py new --branch`): its worktree is the
    # checkout that has that branch.
    found = False
    if not worktree and branch and branch != base:
        worktree = checkout_of(repo, branch)
        found = bool(worktree)
    done = []
    target = merge_target(repo, base)
    gone = tr(f" ({base} no longer exists)", f"（{base} 已不存在）") if target != base else ""
    if branch and git(repo, "merge-base", "--is-ancestor", branch, target) is None and not a.force:
        sys.exit(tr(f"{branch} is not merged into {target}{gone}; pass --force to discard it",
                    f"{branch} 没合并进 {target}{gone}；要丢弃它就加 --force"))
    done += retire_review(task)
    # Several tasks can run one after another in the same worktree and terminal: the last one retired removes them.
    others = [t for t in all_tasks() if t["id"] != task["id"] and not t.get("retired")
              and t["status"] not in ("done", "abandoned")]
    def shares(t):
        if t.get("worktree"):
            return Path(t["worktree"]).resolve() == Path(worktree).resolve()
        return bool(branch) and t["repo"] == repo and t.get("branch") == branch
    if worktree and any(shares(t) for t in others):
        print(f"{worktree} is kept: another task still uses it")
        worktree = None
    if worktree and Path(worktree).is_dir() and Path(worktree).resolve() != Path(repo).resolve():
        _, dirty = git_state(worktree, None, base)
        if dirty and not a.force:
            sys.exit(f"{worktree} has {dirty} uncommitted changes")
        term = hc_terminal_of(task)
        info = (hc("get", term) or {}) if term and (found or f"hc:{term}" != PANE) else {}
        if found:
            # A worktree found by its branch holds a session's own task, and the task's terminal is that session's
            # conversation, often the user's. It is never ended, and its directory stays while it sits there.
            cwd = Path(info.get("cwd") or "/").resolve()
            if info.get("state") == "live" and Path(worktree).resolve() in (cwd, *cwd.parents):
                sys.exit(f"worktree {worktree} is kept: hc:{term} still works in it")
        # A recorded worktree: end the worker's terminal with it, never a PM's or one that sits elsewhere.
        elif (info and not (info.get("labels") or {}).get("pm")
                and Path(info.get("cwd") or "/").resolve() == Path(worktree).resolve()):
            if info.get("state") == "live":
                hc("kill", term)
            hc("rm", term)
            done.append(f"terminal hc:{term}")
        listed = herdr("worktree", "list", "--cwd", repo) or {}
        owned = [w for w in listed.get("worktrees", [])
                 if Path(w.get("path", "")).resolve() == Path(worktree).resolve() and w.get("open_workspace_id")]
        tools = Path(worktree) / ".tools"
        if tools.is_symlink():
            tools.unlink()
        # Only a workspace that herdr opened for this worktree is removed with it.
        if owned and owned[0]["open_workspace_id"] != WORKSPACE:
            herdr("worktree", "remove", "--workspace", owned[0]["open_workspace_id"], "--force")
        else:
            git(repo, "worktree", "remove", "--force", worktree)
        if not Path(worktree).is_dir():
            done.append(f"worktree {worktree}")
    kept = ""
    if branch and branch != base:
        # Merged was checked above; -D because git's own check compares with the checked-out branch.
        if git(repo, "branch", "-D", branch) is not None:
            done.append(f"branch {branch}")
        elif git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is not None:
            where = checkout_of(repo, branch)
            kept = f"; branch {branch} is kept: " + (f"checked out in {where}" if where else "git refused to delete it")
    task["retired"] = now()
    if task["status"] in ACTIVE:
        task["status"] = "abandoned" if a.force else "merged"
    summary = "retired: removed " + (", ".join(done) or "nothing") + kept
    if gone and branch and not a.force:
        summary += tr(f"; checked as merged into {target}{gone}", f"；按已合并进 {target} 判断{gone}")
    note(task, summary)
    save(task)
    print(f"{task['id']} {summary}")


# ---- land and review: the PM gets the verdict, not the reading --------------------

def verify_file(repo):
    return PROJECTS / project_slug(repo) / "verify"


def verify_commands(repo):
    """The project's checks, one shell command per line of projects/<project>/verify (`#` starts a comment);
    None when the file does not exist."""
    path = verify_file(repo)
    if not path.exists():
        return None
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


# `land` exit codes: 1 a check failed or timed out, 2 refused (nothing was changed), 4 conflicts,
# 5 the merge could not be undone (the main checkout's state is printed), 128+n stopped by signal n.
LAND_REFUSED, LAND_CONFLICTS, LAND_STUCK = 2, 4, 5


class LandStopped(Exception):
    pass


def refuse(text):
    print(text, file=sys.stderr)
    sys.exit(LAND_REFUSED)


def stop_group(proc):
    """Kill a check and everything it started (it runs in a process group of its own)."""
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()


def undo_merge(repo):
    """Abort the merge in progress, falling back to `git reset --merge`. True when the checkout is back to a clean
    HEAD with no merge in progress; never discards changes that git refuses to drop."""
    for args in (("merge", "--abort"), ("reset", "--merge")):
        subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
        merging = git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD") is not None
        if not merging and not git(repo, "status", "--porcelain", "--untracked-files=no"):
            return True
    return False


def stuck(repo):
    """The merge could not be undone: say what the main checkout holds now, and exit."""
    merging = git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD") is not None
    changed = (git(repo, "status", "--short", "--untracked-files=no") or "").splitlines()
    print(tr(f"the merge could not be undone; {repo} is left "
             + ("in the middle of the merge (MERGE_HEAD is set)" if merging else "with uncommitted changes")
             + ". Look at it and clean it up by hand (`git merge --abort`, or `git status`):",
             f"合并没能撤销；{repo} " + ("停在合并中途（MERGE_HEAD 还在）" if merging else "留有未提交的改动")
             + "。请手动查看并清理（`git merge --abort`，或 `git status`）："))
    print("\n".join(f"  {line}" for line in changed[:20]))
    sys.exit(LAND_STUCK)


def run_checks(repo, checks, timeout, running):
    """Run the checks in order within one time limit. None when all pass, else (check, why, output)."""
    deadline = time.time() + timeout
    for check in checks:
        proc = subprocess.Popen(check, shell=True, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env={**os.environ, "MAIN": repo}, start_new_session=True)
        running[:] = [proc]
        try:
            out, _ = proc.communicate(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            stop_group(proc)
            out = proc.communicate()[0]  # what it printed before it was stopped
            return check, tr(f"timed out: the checks have {timeout} s in all", f"超时：全部检查共 {timeout} 秒"), out
        if proc.returncode:
            return check, tr(f"exit {proc.returncode}", f"退出码 {proc.returncode}"), out
    running.clear()
    return None


def cmd_land(a):
    """Merge a task's branch in the main checkout, run the project's checks, and commit only when all pass."""
    task = load(a.id)
    repo, branch = task["repo"], task.get("branch")
    base = merge_target(repo, task["base"])
    if not branch:
        refuse(tr(f"{a.id} has no branch to land", f"{a.id} 没有可合并的分支"))
    checks = verify_commands(repo)
    if not checks:  # no file, or only comments
        refuse(tr(f"no checks for {Path(repo).name}: write them to {verify_file(repo)}, one shell command per line "
                  "(`#` starts a comment), then land again.",
                  f"{Path(repo).name} 没有验证命令：写进 {verify_file(repo)}，一行一条命令（`#` 开头是注释），再合并。"))
    current = git(repo, "branch", "--show-current")
    if base != "HEAD" and current != base:
        refuse(tr(f"{repo} is on {current or 'a detached HEAD'}, not {base}",
                  f"{repo} 当前在 {current or '游离 HEAD'}，不是 {base}"))
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        refuse(tr(f"{repo} has uncommitted changes; land merges only into a clean checkout",
                  f"{repo} 有未提交的改动，主检出干净时才合并"))
    if git(repo, "merge-base", "--is-ancestor", branch, "HEAD") is not None:
        refuse(tr(f"{branch} is already in {base}: `pm.py update {a.id} --status merged`",
                  f"{branch} 已经在 {base} 里了：`pm.py update {a.id} --status merged`"))
    run = lambda *args: subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    merged = run("merge", "--no-ff", "--no-commit", branch)
    if merged.returncode != 0:
        listed = run("diff", "--name-only", "--diff-filter=U", "-z").stdout
        conflicts = [f for f in listed.split("\0") if f]
        if not undo_merge(repo):
            stuck(repo)
        if not conflicts:  # git refused to start, for example over untracked files in the way
            refuse(f"git merge {branch}: {(merged.stderr or merged.stdout).strip()[-600:]}")
        print(tr(f"conflicts in {len(conflicts)} files; the merge is aborted. Merge by hand (playbook §5):",
                 f"{len(conflicts)} 个文件有冲突，已中止合并。按手册 §5 手动合并："))
        print("\n".join(f"  {f}" for f in conflicts))
        sys.exit(LAND_CONFLICTS)
    # From here on the main checkout is mid-merge: whatever happens, it is committed or undone.
    def stopped(signum, frame):
        raise LandStopped(signum)
    signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    before = {s: signal.signal(s, stopped) for s in signals}
    running, failed, landed, why_commit, signum = [], None, False, "", 0
    try:
        failed = run_checks(repo, checks, a.timeout, running)
        if not failed:
            committed = run("commit", "-q", "-m", a.message or f"merge {branch}: {task['title']}")
            landed = committed.returncode == 0
            why_commit = (committed.stderr or committed.stdout).strip()[-600:]
    except LandStopped as stop:
        signum = stop.args[0]
    finally:
        for s in signals:
            signal.signal(s, signal.SIG_IGN)  # a second ^C must not stop the undo half way
        if not landed:
            stop_group(running[0] if running else None)
            undone = undo_merge(repo)
        for s, handler in before.items():
            signal.signal(s, handler)
    if not landed:
        if not undone:
            stuck(repo)
        if signum:
            print(tr(f"stopped by signal {signum}; the merge is aborted", f"被信号 {signum} 中止，已撤销合并"))
            sys.exit(128 + signum)
        if not failed:
            print(f"git commit: {why_commit}")
            sys.exit(1)
        check, why, out = failed
        print(tr(f"check failed ({why}), the merge is aborted: {check}", f"检查失败（{why}），已中止合并：{check}"))
        print("\n".join(out.rstrip().splitlines()[-20:]))
        note(task, tr(f"land: check failed ({why}): {check}", f"land：检查失败（{why}）：{check}"))
        save(task)
        sys.exit(1)
    sha = git(repo, "rev-parse", "--short", "HEAD")
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        cmd_update(argparse.Namespace(id=a.id, status="merged", commit=sha, keep=a.keep,
                                      note=tr(f"landed: {len(checks)} checks passed",
                                              f"已合并：{len(checks)} 条检查通过")))
    print(tr(f"{a.id}: merged as {sha} on {base}; {len(checks)} checks passed",
             f"{a.id}：已合并为 {sha}（{base}），{len(checks)} 条检查通过"))
    print("\n".join(said.getvalue().splitlines()[1:]))  # what retire removed, or why it did not


def review_brief(task, rid, worktree):
    branch, base = task["branch"], task["base"]
    checks = verify_commands(task["repo"])
    cmd = f"{pm_command()} update {rid} --status done --note"  # done: a review is not work waiting to be merged
    run = "\n".join(f"  - `{c}`" for c in checks or [])
    return tr(
        f"Review (read-only) of task {task['id']}: {task['title']}\n"
        "Do not commit, edit files or create branches: read, run the checks, report.\n"
        f"- Brief: {task.get('brief') or '(none recorded)'}\n"
        f"- Worktree: {worktree}; range `git diff {base}...{branch}` (`--stat` first, then the source changes)\n"
        "- Checklist:\n"
        "  1. The diff against the brief: flag anything outside it.\n"
        "  2. Red lines: no `git add -A` debris, no secrets, no third-party assets, nothing that touches the user's "
        "running apps or system settings.\n"
        "  3. Correctness: edge cases the worker could not have seen (destructive file operations, compatibility "
        "with old peers, signing, OS-version behaviour). Test a claim in a scratch directory when it is cheap.\n"
        "  4. Visual or UX results: look at the evidence image.\n"
        + (f"- The project's checks (run them in the worktree; `git status` must stay clean):\n{run}\n" if checks
           else "- The project has no verify file: skip the checks.\n")
        + f"\nReport: `{cmd} \"<numbered findings, one per line; none: no blockers>\"`\n"
        "The PM reads only this report. Keep it under 600 characters, in the user's language. Then stop.\n"
        + docs_line(),
        f"审查（只读）任务 {task['id']}：{task['title']}\n"
        "不提交、不改文件、不开新分支：只读代码、跑检查、汇报。\n"
        f"- 任务书：{task.get('brief') or '（未登记）'}\n"
        f"- 工作树：{worktree}；范围 `git diff {base}...{branch}`（先 `--stat`，再读源码改动）\n"
        "- 检查清单：\n"
        "  1. 对照任务书看 diff：超出范围的都指出来。\n"
        "  2. 红线：没有 `git add -A` 带进来的杂物、密钥、第三方资源，没有碰用户正在运行的应用或系统设置。\n"
        "  3. 正确性：worker 看不到的边界情况（破坏性的文件操作、与旧版本的兼容、签名、系统版本差异）。"
        "便宜的就在临时目录里试一下。\n"
        "  4. 有界面结果的：看证据图。\n"
        + (f"- 项目的验证命令（在工作树里跑，跑完 `git status` 仍应干净）：\n{run}\n" if checks
           else "- 项目没有 verify 文件：跳过验证命令。\n")
        + f"\n汇报：`{cmd} \"<编号的问题清单，每条一行；没有问题就写 无阻塞>\"`\n"
        "PM 只看这条汇报。写在 600 字以内，用中文。然后停下。\n" + docs_line())


def reviewer_defaults(a, task):
    """The reviewer's kind, model and effort. A model on the command line, or a configured `reviewer`: as before.
    Otherwise the review table (review_models: REVIEW_MODELS, Sonnet for Fable without it, config.json `review`) by
    the profile the task's worker ran with, so a different model reviews the work; Claude unless the entry says
    otherwise. A Fable reviewer chosen so is a review, not a deep dispatch: nobody is asked; it falls back to Sonnet
    when Fable cannot be used. A task without a profile: as before."""
    entry = (review_models().get((task.get("worker") or {}).get("profile") or "")
             if not a.model and not config().get("reviewer") else None)
    entry = {"model": entry} if isinstance(entry, str) else entry if isinstance(entry, dict) else {}
    kind = entry.get("kind") or "claude"
    a.by_table = bool(entry.get("model")) and a.kind in (None, kind)
    if a.by_table:
        a.kind, a.model, a.effort = kind, entry["model"], a.effort or entry.get("effort") or ""
    else:
        worker_defaults(a, "reviewer")
    a.profile, a.advisor = "", ""  # a reviewer runs without a profile's advisor
    a.fallback = fable_fallback(a.kind, a.model, "reviewer")
    return a


def cmd_review(a):
    """Start a read-only reviewer on a task's branch, as a thread of its own: task <id>-review."""
    task = load(a.id)
    if task.get("review_of") or not task.get("branch"):
        sys.exit(tr(f"{a.id} has no branch to review", f"{a.id} 没有可审查的分支"))
    worktree = task.get("worktree") or checkout_of(task["repo"], task["branch"])
    if not worktree or not Path(worktree).is_dir():
        sys.exit(tr(f"no checkout has {task['branch']}", f"没有检出 {task['branch']} 的工作树"))
    reviewer_defaults(a, task)
    rid = f"{task['id']}-review"
    path = TASKS / f"{rid}.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    if old and old.get("review_of") != task["id"]:
        sys.exit(f"task {rid} exists and is not a review of {task['id']}")
    end_terminal(hc_terminal_of(old))  # a review that is run again starts from a fresh reviewer
    sent = STATE / "sent" / f"{rid}.md"
    sent.parent.mkdir(parents=True, exist_ok=True)
    sent.write_text(review_brief(task, rid, worktree))
    name = a.name or f"{task.get('agent') or slugify(task['id'])}-review"
    # A Claude Code reviewer is given no tool that writes files: it reads, runs the checks and reports.
    argv = (worker_argv(a, outside_reads(task["repo"], task.get("brief") or ""))
            + (["--disallowedTools", "Edit,Write,NotebookEdit"] if a.kind == "claude" else []))
    made = (hc("run", "--bg", *worker_placement(), "--name", name, "--cwd", worktree, "--", *argv) or {}).get("address")
    if not made:
        sys.exit("hc run failed; no reviewer was started")
    hc("label", made, f"task={rid}")
    # A review run again after the one before reported blockers: that round of work did not pass. Not after a pass
    # (a report that starts as the brief says, "no blockers"), after a review that never reported, or once the review
    # thread is closed (an escalation closes it, so the new worker's rounds start from nothing).
    reports = review_reports(old) if old and not old.get("retired") and old.get("status") != "in_progress" else []
    if reports and not PASSED.match(reports[-1][1]):
        fresh = load(task["id"])  # as it is now: its worker may have written to it meanwhile
        fresh["rounds"] = (fresh.get("rounds") or 0) + 1
        save(fresh)
    review = {**old, "id": rid, "title": tr("Review: ", "审查：") + task["title"], "project": task["project"],
              "repo": task["repo"], "status": "in_progress", "base": task["base"], "owner": "pm", "workspace": "",
              "pane": f"hc:{made}", "agent": name, "brief": str(sent), "review_of": task["id"],
              "worker": worker_record(a), "created": old.get("created") or now()}
    for f in ("retired", "commit", *QUESTION_FIELDS):
        review.pop(f, None)
    said = " ".join(x for x in (a.kind, a.model, a.effort) if x)
    of = (task.get("worker") or {}).get("profile") if a.by_table else ""
    note(review, tr(f"review started ({said}" + (f", the review model for {of})" if of else ")"),
                    f"开始审查（{said}" + (f"，{of} 档的评审模型）" if of else "）")) + fallback_said(a))
    save(review)
    if not send_when_ready(made, sent.read_text(), tries=30, pause=2, strict=a.kind in ("claude", "codex"),
                           trust=worktree):
        seen = screen_line(made)
        note(review, tr(f"brief not sent; the reviewer's screen: {seen}", f"任务书没送达；审查 worker 屏幕上是：{seen}"))
        save(review)
        sys.exit(f"the review brief was not sent to hc:{made}. Its screen: {seen}\nOnce it is ready, send it by hand: "
                 f"hc send {made} \"$(cat {shlex.quote(str(sent))})\"")
    print(tr(f"{rid}: reviewer in hc:{made}. Get its findings with `pm.py wait {rid}`.",
             f"{rid}：审查 worker 在 hc:{made}。用 `pm.py wait {rid}` 拿结论。"))


# ---- escalate: the same task again, on a stronger profile ---------------------------

# One step at a time, light to deep. Deep asks the user first, as any Fable worker does (asks_first).
LADDER = ("light", "standard", "hard", "deep")


def ladder():
    """The steps there are here: without Fable ({"fable": false}) it ends at hard, unless config.json's `profiles`
    brings deep back."""
    known = profiles()
    return tuple(p for p in LADDER if p in known)


def engine_label(b):
    """"Opus·xhigh": the model (else the program) and effort a worker runs with, as the task log says it."""
    model = b.model or b.kind
    return "·".join(x for x in (model[:1].upper() + model[1:], b.effort) if x)


def review_reports(review):
    """A review thread's reports, oldest first, as (at, text). A reviewer reports with `update --status done --note`,
    which logs "status=done; <findings>"."""
    found = [(e.get("at") or "", re.match(r"status=[^;]*; (.+)", e.get("text") or "", re.S))
             for e in review.get("log") or []]
    return [(at, m.group(1).strip()) for at, m in found if m]


# A review that passed: its report starts as the review brief asks ("none: no blockers", "没有问题就写 无阻塞").
PASSED = re.compile(r"\s*(?:无阻塞|no blockers?\b)", re.I)


def review_findings(task):
    """What the task's reviews have reported so far, oldest first: the reports in its <id>-review thread."""
    try:
        review = json.loads((TASKS / f"{task['id']}-review.json").read_text())
    except (OSError, ValueError):
        return []
    if review.get("review_of") != task["id"]:
        return []
    return [f"- {at}:\n  " + clip(text, 1200).replace("\n", "\n  ") for at, text in review_reports(review)]


def escalation_brief(task, b, worktree, why):
    """What the new worker of an escalated task is told: where it is and what is done, the review findings and the
    task's latest ledger entries, then the brief as the first worker got it (its report section included)."""
    tid, title, branch, base = task["id"], task.get("title") or task["id"], task["branch"], task["base"]
    because = tr(f" Why: {why}.", f"理由：{why}。") if why else ""
    text = "[from pm.py escalate] " + tr(
        f"You take over task {tid} ({title}), now on {worker_summary(b)}.{because} Another worker has worked on it: "
        f"its commits are already on branch {branch}, in this same worktree ({worktree}). Carry on from there, do not "
        f"start over: read `git log {base}..HEAD` and `git status` first, then fix what the reviews below found.",
        f"你来接手任务 {tid}（{title}），现在用 {worker_summary(b)}。{because}前一个 worker 的提交已经在分支 {branch} 上，"
        f"就在这个工作树（{worktree}）里。从这里接着做，不要从头重写：先看 `git log {base}..HEAD` 和 `git status`，"
        "再把下面评审指出的问题改掉。")
    findings = review_findings(task)
    text += "\n\n" + tr("The review findings so far:", "到目前为止的评审意见：") + "\n" + (
        "\n".join(findings) or tr("(no review has reported in the review thread; see the ledger entries)",
                                  "（评审线程里还没有汇报；看下面的台账记录）"))
    log = "\n".join(f"- {e.get('at')} {e.get('by')}: {clip(' '.join(str(e.get('text') or '').split()), 600)}"
                    for e in (task.get("log") or [])[-8:])
    if log:
        text += "\n\n" + tr("The task's latest ledger entries:", "任务最近的台账记录：") + "\n" + log
    brief = ""
    for path in (STATE / "sent" / f"{tid}.md", Path(task.get("brief") or "")):
        with contextlib.suppress(OSError):
            if str(path) and path.is_file():
                brief = path.read_text().strip()
                break
    text += "\n\n" + tr("The brief:", "原任务书：") + "\n" + (brief or tr("(none recorded)", "（未登记）"))
    return text + "\n" if f"update {tid} --status review" in brief else text + report_section(tid)


def escalated_name(name, profile):
    """The new worker's terminal name, beside the old one that is still live: hc wants it unique, 1-32 of a-z 0-9 - _."""
    base = re.sub(r"-(?:" + "|".join(LADDER) + r")$", "", re.sub(r"[^a-z0-9_-]+", "-", name.lower())).strip("-")
    return f"{base[:31 - len(profile)].rstrip('-') or 'worker'}-{profile}"


def ask_escalation(task, b, current, why):
    """A Fable worker waits for the user's yes (asks_first): the task is blocked with a question card, and nothing
    else changes; its worker keeps its terminal. The same escalate with --confirmed starts the worker."""
    what = tr(f"profile {b.profile} ({' '.join(x for x in (b.kind, b.model, b.effort) if x)})",
              f"{b.profile} 档（{' '.join(x for x in (b.kind, b.model, b.effort) if x)}）")
    again = tr(f"Once the user agrees, run `pm.py escalate {task['id']} --profile {b.profile} --confirmed`.",
               f"用户同意后运行 `pm.py escalate {task['id']} --profile {b.profile} --confirmed`。")
    if task["status"] == "blocked" and (task.get("escalating") or {}).get("to") == b.profile:
        print(tr(f"{task['id']}: still waiting for the user's answer on {what}. {again}",
                 f"{task['id']}：还在等用户回答是否升到 {what}。{again}"))
        return task["id"]
    since = current or tr("its worker", "现在的 worker")
    asked = tr(f"Escalate this task from {since} to {what}" + (f" ({why})" if why else "")
               + "? The user decides before a Fable worker starts.",
               f"这个任务要从 {since} 升到 {what}" + (f"，理由：{why}" if why else "") + "。用 Fable 前先问你：同意吗？")
    options = [tr(f"Agree: escalate to {what}", f"同意，升到 {what}"), tr("Do not escalate", "先不升级")]
    for f in QUESTION_FIELDS:
        task.pop(f, None)
    task.update(status="blocked", options=options, escalating={"to": b.profile, "why": why})
    note(task, "status=blocked; " + asked, options=options)
    save(task)
    print(tr(f"{task['id']}: blocked, no worker started: {what} needs the user's yes. {again}",
             f"{task['id']}：已标成 blocked，没有起 worker：升到 {what} 要先等用户同意。{again}"))
    return task["id"]


def escalation_refused(task_id, b, why, seen):
    """The new worker exited at once with its advisor (most likely Fable's billing is not agreed yet): the task is
    blocked with a question, its previous worker and record are kept. Exits."""
    task = load(task_id)
    answers = [tr("I ran /model fable: escalate again", "已运行 /model fable，重新升级"), no_fable_answer(b.profile)]
    for f in QUESTION_FIELDS:
        task.pop(f, None)
    task.update(status="blocked", options=answers, escalating={"to": b.profile, "why": why})
    note(task, tr(f"status=blocked; the escalated worker exited at once with advisor {b.advisor} (its screen: {seen}); "
                  "the previous worker is kept. ",
                  f"status=blocked；升级起的 worker 带 advisor {b.advisor} 一启动就退出了（屏幕：{seen}），"
                  "前一个 worker 还留着。") + advisor_refused(b), options=answers)
    save(task)
    sys.exit(tr(f"{task_id}: blocked. The escalated worker exited at once with --advisor {b.advisor}: ",
                f"{task_id}：已标成 blocked。带 --advisor {b.advisor} 起的升级 worker 一启动就退出了：")
             + advisor_refused(b)
             + tr(f" Then run `pm.py escalate {task_id} --profile {b.profile}` again.",
                  f"之后再运行 `pm.py escalate {task_id} --profile {b.profile}`。"))


def escalation_failed(task_id, b, why, seen):
    """The new worker exited at once. With an advisor that is most likely Fable's billing: a question for the user
    (escalation_refused). Otherwise the log says so. Either way the task keeps its previous worker and record. Exits."""
    if b.advisor:
        escalation_refused(task_id, b, why, seen)
    task = load(task_id)
    note(task, tr(f"not escalated to {b.profile}: the new worker exited at once (its screen: {seen}); the previous "
                  "worker is kept", f"没升到 {b.profile}：新 worker 一启动就退出了（屏幕：{seen}），前一个 worker 还留着"))
    save(task)
    sys.exit(tr(f"{task_id}: not escalated. The new worker exited at once; its screen: {seen}. The task and its worker "
                "are as they were.", f"{task_id}：没有升级。新 worker 一启动就退出了，屏幕上是：{seen}。任务和它的 worker 都没变。"))


def start_escalated(task, b, name, worktree, text, why):
    """Start the new worker in the task's worktree, where dispatch would (a herdr-core sub-agent of this PM, or a tab
    in the worktree's workspace in the herdr terminal UI), and give it the text. Returns (pane, workspace, the
    screen when the text was not delivered, else ""). Exits, with nothing changed, when no worker could be started."""
    if PANE.startswith("hc:"):
        made = (hc("run", "--bg", *worker_placement(), "--name", name, "--cwd", str(worktree), "--",
                   *worker_argv(b, outside_reads(task["repo"], task.get("brief") or ""))) or {}).get("address")
        if not made:
            sys.exit(tr(f"hc run failed; nothing changed for {task['id']}", f"hc run 失败；{task['id']} 什么都没改"))
        hc("label", made, f"task={task['id']}")
        if send_when_ready(made, text, tries=30, pause=2, strict=b.kind in ("claude", "codex"), trust=worktree,
                           stop_on_exit=True):
            return f"hc:{made}", "", ""
        seen = screen_line(made, width=300)
        if worker_state(made) in ("exited", "removed"):
            end_terminal(made)
            escalation_failed(task["id"], b, why, seen)
        return f"hc:{made}", "", seen or "(empty screen)"
    old = task.get("pane") or ""
    workspace = task.get("workspace") or (((herdr("pane", "get", old) or {}).get("pane") or {}).get("workspace_id")
                                          if old else "") or ""
    made = re.search(r'"pane_id": "([^"]+)"', json.dumps(
        herdr("tab", "create", "--workspace", workspace, "--cwd", str(worktree), "--label", name, "--no-focus")
        or {})) if workspace else None
    if not made:
        sys.exit(tr(f"no tab could be made in {task['id']}'s workspace; nothing changed",
                    f"没能在 {task['id']} 的工作区开出标签页；什么都没改"))
    pane = made.group(1)
    argv = worker_argv(b, outside_reads(task["repo"], task.get("brief") or ""))
    if not herdr("agent", "start", name, "--kind", b.kind, "--pane", pane, *(["--", *argv[1:]] if argv[1:] else [])):
        herdr("pane", "close", pane)
        sys.exit(tr(f"agent start failed in {pane}; nothing changed", f"在 {pane} 启动 agent 失败；什么都没改"))
    prompted = herdr("agent", "prompt", name, text)
    working = prompted and herdr("agent", "wait", name, "--until", "working", "--timeout", "20000")
    if not working and tui_agent_gone(pane):
        herdr("pane", "close", pane)
        escalation_failed(task["id"], b, why, tr("(no agent in the pane)", "（窗格里已经没有 agent）"))
    if prompted and not working:
        print(f"warning: {name} did not start working; read its screen", file=sys.stderr)
    return pane, workspace, "" if prompted else tr("(the prompt was refused)", "（提示没送进去）")


def own_worker(task, pane):
    """The pane holds a worker that pm.py started for this task, which escalate may stop and end: in hc, a terminal
    labelled task=<id> (dispatch, reattach and escalate label theirs); in the herdr TUI, the pane they recorded as
    `worker_pane`, with the task's agent still in it. Never a PM's, this session's, or a session taken over with
    `pm.py new --pane`."""
    if not pane or pane == PANE or pm_record_for_pane(pane):
        return False
    if pane.startswith("hc:"):
        labels = (hc("get", pane[3:]) or {}).get("labels") or {}
        return not labels.get("pm") and labels.get("task") == task["id"]
    return task.get("worker_pane") == pane and any(
        x.get("pane_id") == pane and x.get("name") == task.get("agent") for x in agents())


def worker_busy(pane):
    """The agent in this pane is in the middle of a turn: in hc, a live program whose status is none of the stopped
    states (as worker_state reads them); in the herdr TUI, an agent whose status is working."""
    if pane.startswith("hc:"):
        info = hc("get", pane[3:]) or {}
        state = (info.get("status") or {}).get("state")
        return info.get("state") == "live" and bool(state) and state not in ("idle", "done", "blocked", "error")
    return any(x.get("pane_id") == pane and x.get("agent_status") == "working" for x in agents())


def index_lock(worktree):
    """git's index.lock of this worktree while it exists (a commit, checkout or add under way), else None."""
    path = (git(str(worktree), "rev-parse", "--git-path", "index.lock") or "").strip()
    return Path(worktree, path) if path and Path(worktree, path).exists() else None


QUIET_TRIES = 30  # looks, two seconds apart, for the previous worker to go idle and for git's index.lock to go


def quiet_old_worker(task, pane, ours, worktree):
    """The previous worker stops before the new one starts, so the two never work in the worktree at once. This
    task's own worker (ours) is interrupted while it works and waited for until it is idle; another session (taken
    over, or the PM's) is never interrupted, so escalate stops while it works. Then git's index.lock must be gone.
    Returns whether it interrupted the worker; exits, with nothing changed, when the worktree does not get quiet."""
    interrupted = False
    if pane and pane != PANE and worker_busy(pane):
        if not ours:
            sys.exit(tr(f"{pane} is still working in {worktree} and is not a worker escalate may stop; nothing changed. "
                        "Let it finish or stop it, then escalate again.",
                        f"{pane} 还在 {worktree} 里干活，又不是 escalate 能停的 worker；什么都没改。等它做完或停下后再升级。"))
        if pane.startswith("hc:"):
            hc("interrupt", pane[3:], "--timeout", "10")
        else:
            herdr("agent", "send-keys", pane, "esc")
        interrupted = True
        for _ in range(QUIET_TRIES):
            if not worker_busy(pane):
                break
            time.sleep(2)
        else:
            sys.exit(tr(f"{pane} was interrupted but is still working; nothing else changed. Escalate again once it "
                        "has stopped.", f"已中断 {pane}，但它还在干活；别的都没改。等它停下后再升级。"))
    for _ in range(QUIET_TRIES):
        lock = index_lock(worktree)
        if not lock:
            return interrupted
        time.sleep(2)
    sys.exit(tr(f"git's {lock} is still there: something is writing to the worktree, so no new worker was started. "
                "If no git runs there, remove the file and escalate again.",
                f"git 的 {lock} 一直在：有程序在写这个工作树，所以没起新 worker。确认那里没有 git 在跑后删掉这个文件，再升级。"))


def cmd_escalate(a):
    """Run a task again on a stronger profile: a new worker with a fresh context, in the same worktree and on the
    same branch, given the review findings so far and the brief, to carry on from the previous worker's commits.
    One step up the ladder unless --profile names one; a Fable worker waits for the user's yes, as in dispatch.
    The task id stays; `escalations` and the log record the step; the previous worker's terminal ends."""
    task = load(a.id)
    if task.get("review_of"):
        sys.exit(tr(f"{a.id} is a review thread: escalate the task it reviews", f"{a.id} 是审查线程：升级它审查的那个任务"))
    if task["status"] not in ATTACHED:
        sys.exit(tr(f"{a.id} is {task['status']}: only open work (in progress, review, blocked) is escalated",
                    f"{a.id} 的状态是 {task['status']}：只有进行中、待审、阻塞的任务能升级"))
    worktree = task.get("worktree") or (checkout_of(task["repo"], task["branch"]) if task.get("branch") else None)
    if not task.get("branch") or not worktree or not Path(worktree).is_dir():
        sys.exit(tr(f"{a.id} has no branch checked out in a worktree to carry on from",
                    f"{a.id} 没有检出在工作树里的分支，新 worker 没处接着做"))
    current = (task.get("worker") or {}).get("profile") or "" if isinstance(task.get("worker"), dict) else ""
    steps = ladder()
    target = a.profile or (steps[steps.index(current) + 1] if current in steps[:-1] else "")
    if not target and current and current == steps[-1] and steps[-1] != LADDER[-1]:
        sys.exit(tr(f"{a.id} runs on {current}: without Fable (config.json \"fable\": false) that is the top profile, "
                    "so nothing was escalated and no worker started",
                    f"{a.id} 现在是 {current}：没有 Fable（config.json 里 \"fable\": false），这已经是最高一档；"
                    "没有升级，也没有起 worker"))
    if not target:
        sys.exit(tr(f"{a.id} runs on {current or 'no profile'}: there is no step up from it; name one with --profile "
                    f"({', '.join(steps)})",
                    f"{a.id} 现在是 {current or '无档位'}：没有上一档可升；用 --profile 指定（{', '.join(steps)}）"))
    b = worker_defaults(argparse.Namespace(profile=target, kind=None, model=None, effort=None, advisor=a.advisor))
    pending = task.get("escalating") or {}
    # The reason on the question card still open for this target, not one from an earlier question.
    asked = task["status"] == "blocked" and pending.get("to") == target
    why = (a.why or "").strip() or (pending.get("why") or "" if asked else "")
    if asks_first(b) and not a.confirmed:
        return ask_escalation(task, b, current, why)
    old, old_agent = task.get("pane") or "", task.get("agent") or ""
    ours = own_worker(task, old)  # decided now: after the switch the task names the new worker
    name = a.name or escalated_name(old_agent or task["id"], target)
    if name == old_agent:  # again on the profile it runs on: the old terminal still holds that name
        name = f"{name[:30]}-2"
    text = escalation_brief(task, b, worktree, why)
    sent = STATE / "sent" / f"{task['id']}.escalated.md"  # sent/<id>.md stays the first brief, which reattach sends
    sent.parent.mkdir(parents=True, exist_ok=True)
    sent.write_text(text)
    interrupted = quiet_old_worker(task, old, ours, worktree)
    try:
        pane, workspace, unsent = start_escalated(task, b, name, worktree, text, why)
    except SystemExit as stop:
        if not interrupted:
            raise
        # The new worker did not start, but the old one was stopped in its turn: it waits now, and nothing reports.
        said = tr(f"The previous worker {old} was interrupted for this escalation and is idle now: tell it to carry "
                  "on, or escalate again.", f"前一个 worker {old} 为这次升级被中断了，现在空着：让它接着做，或者再升级一次。")
        task = load(a.id)
        note(task, said)
        save(task)
        raise SystemExit(f"{stop.code}\n{said}")
    task = load(a.id)
    for f in (*QUESTION_FIELDS, "escalating", "session"):  # the old worker's session is not the new one's to resume
        task.pop(f, None)
    task.update(status="in_progress", pane=pane, workspace=workspace, agent=name, kind=b.kind, worker=worker_record(b),
                worker_pane=pane, rounds=0)  # the new worker's rounds start from nothing
    if not isinstance(task.get("escalations"), list):
        task["escalations"] = []
    task["escalations"].append({"from": current, "to": target, "why": why, "at": now()})
    note(task, tr(f"escalated to {target} ({engine_label(b)})" + (f": {why}" if why else ""),
                  f"升级到 {target}（{engine_label(b)}）" + (f"：{why}" if why else "")) + fallback_said(b))
    save(task)
    # The review thread has done its job: its findings went to the new worker, whose first review is a fresh round.
    retire_review(task, tr(f"closed: {task['id']} was escalated to {target}", f"{task['id']} 已升到 {target}，这轮审查收起"))
    ended = ours and old != pane and (end_terminal(old[3:]) if old.startswith("hc:")
                                      else herdr("pane", "close", old) is not None)
    kept = tr(f"; {old} kept: not a worker terminal of this task", f"；{old} 没关：不是这个任务的 worker 终端") \
        if old and old != pane and not ended else ""
    print(tr(f"{task['id']}: escalated {current or '-'} -> {target}; worker {name} in {pane}",
             f"{task['id']}：已从 {current or '-'} 升到 {target}；worker {name} 在 {pane}")
          + (tr(f"; ended {old}", f"；已结束 {old}") if ended else kept)
          + (tr(" (it was interrupted first)", "（先中断了它）") if interrupted else ""))
    if unsent:
        note(task, tr(f"brief not sent; the worker's screen: {unsent}", f"任务书没送达；worker 屏幕上是：{unsent}"))
        save(task)
        resend = (f"hc send {pane[3:]} \"$(cat {shlex.quote(str(sent))})\"" if pane.startswith("hc:")
                  else f"herdr agent prompt {name} \"$(cat {shlex.quote(str(sent))})\"")
        sys.exit(tr(f"the brief was not sent to {pane}. Its screen: {unsent}\nOnce it is ready, send it by hand: {resend}",
                    f"任务书没送到 {pane}。屏幕上是：{unsent}\n等它就绪后手动发送：{resend}"))


def cmd_hook_session_start(a):
    """SessionStart hook: tell a session inside herdr whether a PM exists."""
    if not PANE or (os.environ.get("HERDR_ENV") != "1" and not HC_TERMINAL):
        return
    pm = find_pm()
    if not pm:
        # A restarted PM loses its herdr name; restore it from the registration for this pane.
        rec = pm_record_for_pane(PANE)
        if rec and not rec.get("archived") and herdr("agent", "rename", PANE, rec["name"]):
            pm = {"pane_id": PANE, "name": rec["name"]}
        else:
            return
    if pm["pane_id"] == PANE:
        print(f"You are {pm.get('name')}, the PM for this project (pm skill). Ledger board: {BOARD}. "
              "If you have not read it in this session, run `pm.py handover` before anything else.")
        return
    print(f"A PM coordinator ({pm.get('name')}) runs in {pm['pane_id']}. Before implementing a non-trivial change, "
          "load the pm skill: register the task in the ledger (or hand it to the PM if the user asks), "
          "and mark it `review` when it is ready to merge.")


def pm_record_for_pane(pane):
    for path in PMS.glob("*.json") if PMS.exists() else []:
        rec = json.loads(path.read_text())
        if rec.get("pane") == pane:
            return rec
    return None


SLASH_COMMAND = re.compile(r"/[\w:.-]+(\s|$)")  # "/compact", not a path such as "/Users/me/shot.png"
HC_SENT = re.compile(r'<hc from="([^"]+)">(.*)</hc>$', re.S)


def cmd_hook_turn(a):
    """UserPromptSubmit/Stop hook of a PM session: keep the project's conversation log, note the turn for
    the board, and say when to hand over."""
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    event = data.get("hook_event_name", "")
    rec = pm_record_for_pane(PANE) if PANE else None
    if event not in ("UserPromptSubmit", "Stop") or not rec:
        return
    repo = rec.get("repo") or ""
    if event == "UserPromptSubmit":
        # What a UserPromptSubmit hook prints is added to the session's context.
        used = context_tokens(data.get("transcript_path") or "")
        if used > ROTATE_TOKENS:
            print(f"[pm] This PM session holds {used // 1000}k context tokens (limit {ROTATE_TOKENS // 1000}k). "
                  "Finish the step in hand, then hand over: `pm.py rotate --notes \"<what the ledger does not say>\"`.")
        prompt, sender = (data.get("prompt") or "").strip(), ""
        # Text typed in by another agent is not the user's turn: `hc send` from a terminal wraps it in
        # <hc from="t3">…</hc>, and `pm.py notify` starts it with "[from <pane>]".
        wrapped = HC_SENT.match(prompt)
        if wrapped:
            sender, prompt = f"hc:{wrapped.group(1)}", wrapped.group(2).strip()
        named = re.match(r"\[from ([^\]]+)\]\s*", prompt)
        if named:
            sender, prompt = sender or named.group(1), prompt[named.end():]
        if sender:
            if repo and prompt:
                record(repo, "agent", by=sender, text=prompt)
            return
        if not prompt or prompt.startswith("<") or SLASH_COMMAND.match(prompt):
            return  # task notifications, slash commands
        if repo:
            record(repo, "user", text=prompt)
    else:
        # The agent's Stop hook carries the final message of the turn (Claude Code and Codex name it so).
        reply = (data.get("last_assistant_message") or "").strip()
        if repo and reply:
            # `by`: which session spoke, so the project view can tell this PM's ledger entries from a worker's.
            record(repo, "pm", text=reply, **({"by": PANE} if PANE else {}))
    turn_log(f"{event}: turn")


cmd_hook_mirror = cmd_hook_turn  # the name earlier installs put in their hooks


# ---- rotation: the PM is the project's record, not one session ----------------

def project_dir(repo):
    d = PROJECTS / project_slug(repo)
    d.mkdir(parents=True, exist_ok=True)
    return d


def record(repo, kind, **fields):
    """Append one event to the project's conversation log, projects/<project>/conversation.jsonl.

    The log is the conversation as the project keeps it, in order: what the user said (`user`), the PM's
    final reply of each turn (`pm`), what other agents typed in (`agent`), ledger entries (`thread`) and
    decisions (`decision`). It belongs to the project, not to a session: a PM session of any agent appends
    to it and a fresh one reads it. Nothing may fail because of it, so errors are swallowed.
    """
    try:
        at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = json.dumps({"at": at, "type": kind, **fields}, ensure_ascii=False) + "\n"
        fd = os.open(project_dir(repo) / "conversation.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode())  # one write, so a hook and a ledger command cannot interleave lines
        finally:
            os.close(fd)
    except (OSError, TypeError, ValueError):
        pass


def conversation(repo):
    """The events of the project's conversation log, oldest first."""
    return conversation_events(project_dir(repo) / "conversation.jsonl")


def conversation_events(path):
    """The events of the conversation log at `path`, oldest first; none when it cannot be read."""
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):  # a stray `null` or `[]` line is not an event
            events.append(event)
    return events


def asks_again(event):
    """A ledger entry that asks the user a question: `update --status blocked` (its text says status=blocked,
    see cmd_update, also while the task already was blocked) or one that offers quick answers (--option).
    Entering blocked from another status asks too. The same rule as pm-project's asksAgain."""
    return bool(re.search(r"\bstatus=blocked\b", str(event.get("text") or ""))) or any(
        str(o or "").strip() for o in (event.get("options") if isinstance(event.get("options"), list) else []))


IMAGE_MARK = re.compile(r"\[Image #\d+\][ \t]*")  # as pm-project's model.js IMAGE_MARK


def asked_at(task):
    """When the ledger last asked the user about `task` ("YYYY-MM-DD HH:MM"): its latest entry that made it blocked
    (status=blocked, see cmd_update), else its first entry (a task registered blocked); "" without a log."""
    log = [e for e in task.get("log") or [] if isinstance(e, dict)]
    asking = [e for e in log if re.search(r"\bstatus\s*=\s*blocked\b", str(e.get("text") or ""))]
    return str((asking or log or [{}])[-1 if asking else 0].get("at") or "")


def answered_tasks(events, titles=None, asked=None):
    """The blocked tasks the user has answered: after the task last asked (entered blocked, or see asks_again), the user
    said something that starts with its 【title】, as a quick answer on the question card does
    (`【<title>】<option>`). Such a task waits for the PM, not for the user, until the PM moves it on; asking
    again is a new question, unanswered. The same rule as pm-project's answeredTasks.
    titles: {task id: its title in the ledger} of tasks blocked in the ledger; a task not there goes by its newest
    title in the log. One the log never shows asked (asked before the log began, or in another project's log) is
    as the ledger says: blocked, and asked when asked[task] says (see asked_at): words after that, anywhere in the
    log, that start with its 【title】 answer it. A ledger entry that asks nothing (`pm.py log`, a note) shows a task
    blocked in the log without asking: the first one asks only when it is no later than asked[task]."""
    when = asked or {}
    at = lambda e: str(e.get("at") or "")[:16]
    squash = lambda text: " ".join(str(text or "").split())
    # Claude Code records an image sent with the words as an "[Image #N]" mark before them; it says nothing.
    unmarked = lambda text: IMAGE_MARK.sub("", str(text or ""))
    named = {}
    for e in events:
        if e.get("type") == "thread" and e.get("task") and e.get("title"):
            named[e["task"]] = e["title"]
    named.update({k: v for k, v in (titles or {}).items() if v})
    # A thread event that asks: blocked, and asking again, or entering blocked from another status; a task's
    # first event in the log asks unless the ledger asked before it (it is then a note on that question).
    def asks(e, was):
        if e.get("status") != "blocked":
            return False
        if was is None:
            return asks_again(e) or not (when.get(e.get("task")) and at(e) > when[e["task"]])
        return was != "blocked" or asks_again(e)

    seen, shown = {}, set()
    for e in events:
        if e.get("type") == "thread" and e.get("task"):
            if asks(e, seen.get(e["task"])):
                shown.add(e["task"])
            seen[e["task"]] = e.get("status")
    unlogged = [t for t in (titles or {}) if t not in shown]
    # opened: the tasks whose question is open, the newest last
    status, opened, answered = dict.fromkeys(unlogged, "blocked"), list(unlogged), set()
    for e in events:
        kind, task = e.get("type"), e.get("task")
        if kind == "thread" and task and task not in unlogged:  # the ledger, not the log, says what those are
            if asks(e, status.get(task)):
                answered.discard(task)
                opened = [t for t in opened if t != task] + [task]
            status[task] = e.get("status")
        elif kind == "user":
            said = squash(unmarked(e.get("text")))
            # The newest open question whose 【title】 the words start with: they answer that one.
            # One asked before the log goes by the ledger's time: words said before it answer an older question.
            hit = next((t for t in reversed(opened) if status.get(t) == "blocked" and not (t in unlogged and at(e) < when.get(t, ""))
                        and said.startswith(squash(f"【{named.get(t, t)}】"))), None)
            if hit:
                answered.add(hit)
    return {t for t in answered if status.get(t) == "blocked"}


def clip(text, width):
    return text if not width or len(text) <= width else text[:width] + " …"


def log_tail(repo, turns=6, width=700):
    """The last exchanges in the conversation log: what the user said and the PM's reply to it.

    The reply to a user turn is the first `pm` event after it. Later ones answer something else (a finished
    background wait, the next session taking over), and so does any reply after an `agent` event.
    """
    out, awaiting_reply = [], False
    for event in conversation(repo):
        kind = event.get("type")
        if kind == "user":
            out.append({"user": str(event.get("text") or ""), "pm": ""})
            awaiting_reply = True
        elif kind == "agent":
            awaiting_reply = False
        elif kind == "pm" and awaiting_reply:
            out[-1]["pm"] = str(event.get("text") or "")
            awaiting_reply = False
    return [{"user": clip(t["user"], width), "pm": clip(t["pm"], width)} for t in out[-turns:]]


def cmd_conversation(a):
    """Print the end of the project's conversation log: how to look further back than a handover does."""
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    events = [e for e in conversation(repo) if not a.type or e.get("type") in a.type.split(",")]
    for e in events[-a.last:]:
        kind = e.get("type")
        who = {"user": tr("User", "用户"), "pm": "PM", "decision": tr("Decision", "决定"), "agent": e.get("by"),
               "thread": f"[{e.get('task')} · {e.get('status')}] {e.get('by')}"}.get(kind, kind)
        text = str(e.get("text") or "") + (f' — "{e["quote"]}"' if e.get("quote") else "")
        print(f"{e.get('at')} {who}: {clip(' '.join(text.split()), a.width)}")


def own_transcript():
    """Transcript file of the Claude Code session running this command, or "" (other agents: not read yet)."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    hits = list((Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl")) if sid else []
    return str(hits[0]) if hits else ""


def transcript_rows(path):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not row.get("isSidechain"):
            yield row


def context_tokens(path):
    """Context size of a session: the input side of its latest model call."""
    used = 0
    for row in transcript_rows(path):
        usage = (row.get("message") or {}).get("usage") if row.get("type") == "assistant" else None
        if usage:
            used = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens"))
    return used


def conversation_tail(path, turns=6, width=700):
    """The last exchanges of a session: what the user typed and the PM's final text of that turn."""
    out, current = [], None
    for row in transcript_rows(path):
        content = (row.get("message") or {}).get("content")
        if row.get("type") == "user":
            text = content if isinstance(content, str) else "\n".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            text = text.strip()
            if text and not text.startswith("<"):  # tool results and system notices are not the user speaking
                current = {"user": text, "pm": ""}
                out.append(current)
        elif row.get("type") == "assistant" and current is not None and isinstance(content, list):
            texts = [b["text"] for b in content if b.get("type") == "text" and b.get("text", "").strip()]
            if texts:
                current["pm"] = "\n".join(texts)  # later rows overwrite: the final message wins
    return [{"user": clip(t["user"], width), "pm": clip(t["pm"], width)} for t in out[-turns:]]


def cmd_decide(a):
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    line = f"- {now()[:10]} {a.text}" + (tr(f' — the user\'s words: "{a.quote}"', f" — 用户原话：「{a.quote}」") if a.quote else "")
    with open(project_dir(repo) / "decisions.md", "a") as f:
        f.write(line + "\n")
    record(repo, "decision", text=a.text, quote=a.quote or "")
    print(line)


def cmd_context(a):
    path = a.transcript or own_transcript()
    if not path:
        sys.exit("no transcript: pass --transcript")
    used = context_tokens(path)
    print(f"{used // 1000}k context tokens (hand over above {ROTATE_TOKENS // 1000}k)")


def cmd_handover(a):
    """Everything a fresh PM session needs, from the project's record on disk."""
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    rec, d, name = pm_record(repo) or {}, project_dir(repo), Path(repo).name
    out = [f"# Handover: PM of {name}", "",
           f"You are {pm_name(repo)}. Repository: {repo}. This text is the project's record; trust it over anything "
           "you think you remember, and do not read the previous session's transcript.",
           "Then read `references/pm-playbook.md` of the pm skill."]
    profile = Path(repo) / ".claude" / "coordination.md"
    if profile.exists():
        out.append(f"Project profile (read it): {profile}")
    for title, path in (("Decisions the user has made", d / "decisions.md"),
                        ("Notes from the previous PM", d / "handover.md")):
        if path.exists() and path.read_text().strip():
            out += ["", f"## {title}", path.read_text().strip()]
    tasks = [t for t in all_tasks() if t.get("project") == name and str(Path(t["repo"]).resolve()) == repo]
    active = [t for t in tasks if t["status"] in ACTIVE or (t["status"] in ("merged", "released") and not t.get("retired"))]
    out += ["", "## Open work"] + ([] if active else ["(none)"])
    for t in active:
        where = " ".join(f"{k}={t[k]}" for k in ("pane", "agent", "branch", "worktree", "brief") if t.get(k))
        out.append(f"- [{t['status']}] {t['id']}: {t['title']} (owner {t.get('owner')}; {where})")
        out += [f"    {e['at']} {e['by']}: {e['text'][:400]}" for e in (t.get("log") or [])[-3:]]
    day_ago = (datetime.datetime.now() - datetime.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")
    closed = [t for t in tasks if t not in active and t.get("updated", "") >= day_ago]
    if closed:
        out += ["", "## Closed in the last 48 h"] + [f"- [{t['status']}] {t['id']}: {t['title']}" for t in closed]
    # The conversation log is the source; a project whose log is still empty falls back to the last transcript.
    tail = log_tail(repo, turns=a.turns) or conversation_tail(
        (rec.get("previous") or {}).get("transcript") or "", turns=a.turns)
    if tail:
        out += ["", "## The last exchanges with the user (shortened; `pm.py conversation --last 40` shows more)"]
        for t in tail:
            out += [f"{tr('User', '用户')}: {t['user']}", f"PM: {t['pm'] or '(no final text)'}", ""]
    print("\n".join(out))


# Flags of the outgoing PM whose value is carried over to its successor.
KEEP_VALUE = ("--mcp-config", "--permission-mode", "--settings", "--add-dir", "--plugin-dir", "--allowed-tools",
              "--allowedTools", "--disallowed-tools", "--disallowedTools", "--append-system-prompt", "--agents",
              "--effort", "--setting-sources")


def successor_argv(kind, args, model, prompt):
    """The command of the next PM. Claude Code keeps the outgoing session's flags, minus anything that would
    resume it; other kinds start from their registry entry. The prompt follows `--`: a kept flag such as
    `--allowed-tools` takes any number of values and would take the prompt as one more."""
    if kind != "claude":
        return agent_argv(kind, model, prompt=prompt)
    argv = ["claude"]
    for i, arg in enumerate(args):
        if arg == "--":
            break  # what follows is the first prompt the outgoing session was started with
        if not arg.startswith("-") or arg in ("--resume", "-r", "--continue", "-c", "--model", "--fork-session"):
            continue  # also drops a session id, a model name and an initial prompt
        argv.append(arg)
        if arg in KEEP_VALUE and i + 1 < len(args):
            argv.append(args[i + 1])
    return argv + (["--model", model] if model else []) + ["--", prompt]


# A Claude Code PM edits no files itself: workers do. Write stays, for briefs. One value, so a rotation that carries
# the outgoing session's flags over keeps it whole.
NARROW = ["--disallowedTools", "Edit,NotebookEdit"]


def narrow_pm(kind, argv):
    """The PM's command with Edit and NotebookEdit denied (Claude Code only), unless config.json says
    {"pm": {"narrow_tools": false}}; then a denial carried over from the outgoing session is dropped too."""
    if kind != "claude":
        return argv
    cut = argv.index("--") if "--" in argv else len(argv)
    head, i = [], 0
    while i < cut:
        if argv[i:i + 2] == NARROW:
            i += 2
            continue
        head.append(argv[i])
        i += 1
    if (config().get("pm") or {}).get("narrow_tools", True) is not False:
        head += NARROW
    return head + argv[cut:]


def rotate_herdr(a, repo, rec, previous, prompt, is_self):
    """In herdr (TUI): the new PM starts in a new tab of the outgoing PM's workspace."""
    path, name, old = PMS / f"{project_slug(repo)}.json", rec["name"], rec.get("pane") or ""
    workspace = ((herdr("pane", "get", old) or {}).get("pane") or {}).get("workspace_id")
    made = re.search(r'"pane_id": "([^"]+)"', json.dumps(
        herdr("tab", "create", "--workspace", workspace, "--cwd", repo, "--label", "pm", "--no-focus") or {})
    ) if workspace else None
    if not made:
        rec["previous"] = previous
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        sys.exit(f"handover notes saved, but no tab could be opened beside {old or 'the old PM'}. Start a fresh "
                 f"session by hand (SKILL.md, \"Restart a PM\", without --resume) and give it this prompt:\n{prompt}")
    new = made.group(1)
    info = ((herdr("pane", "process-info", "--pane", old) or {}).get("process_info") or {})
    kind = rec.get("agent") or "claude"
    program = Path(agent_argv(kind)[0]).name
    args = next((p["argv"][1:] for p in info.get("foreground_processes", [])
                 if p.get("argv") and Path(p["argv"][0]).name == program), [])
    argv = narrow_pm(kind, successor_argv(kind, args, a.model, prompt))
    # The name must be free: the new session's SessionStart hook takes it from the registration of its pane.
    herdr("agent", "rename", old, f"ex-{name}")
    rec.update({"pane": new, "workspace": workspace, "claimed": now(), "previous": previous,
                "rotations": rec.get("rotations", 0) + 1})
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    herdr("pane", "run", new, shlex.join(argv))
    seen = herdr("agent", "wait", new, "--until", "working", "--until", "idle", "--until", "blocked",
                 "--timeout", "30000")
    print(f"new PM session started in {new}; {old} is retired"
          + (": stop acting as PM in this session and tell the user to continue there." if is_self else "."))
    if not seen:
        print(f"check {new}: it may be waiting at a startup dialog (folder trust) that the user has to confirm.")


def app_spaces():
    """The spaces of the open desktop window (`herdr-app ls`), or [] without one."""
    try:
        out = subprocess.run(["herdr-app", "ls"], capture_output=True, text=True, timeout=30)
        return (json.loads(out.stdout).get("spaces") or []) if out.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return []


def start_pm_terminal(repo, argv, space=None, new_space=""):
    """Start a PM's program in the desktop app: in a new space called new_space, or a tab in the given space,
    else a bare terminal (no app).

    A space.new that times out or answers without a terminal may still have made the space: that space's
    terminal is the PM, found by its name among the spaces that were not there before. None found: stop,
    so a second PM is not started in a bare terminal."""
    made = None
    if new_space or space:
        command = ("space.new", {"name": new_space, "folder": repo, "argv": argv}) if new_space else (
            "tab.new", {"space": space, "folder": repo, "argv": argv})
        before = {s.get("id") for s in app_spaces()} if new_space else set()
        unclear = False
        try:
            out = subprocess.run(["herdr-app", "do", command[0], json.dumps(command[1])],
                                 capture_output=True, text=True, timeout=30)
            if out.returncode == 0:
                try:
                    made = json.loads(out.stdout).get("terminal")
                except (ValueError, AttributeError):
                    made = None
                unclear = not made
        except subprocess.TimeoutExpired:
            unclear = True
        except OSError:
            made = None  # no app here: a bare terminal below
        if unclear and new_space:
            made = next((t.get("terminal") for s in app_spaces() if s.get("name") == new_space
                         and s.get("id") not in before for tab in s.get("tabs") or []
                         for t in tab.get("terminals") or [] if t.get("terminal")), None)
            if not made:
                sys.exit(tr(f"space.new gave no terminal and no new space \"{new_space}\" is open; no PM was "
                            "started. Look at the window (herdr-app ls) before trying again.",
                            f"space.new 没有给出终端，也没找到新建的 space「{new_space}」；没有启动 PM。"
                            "先看一下窗口（herdr-app ls）再重试。"))
    return made or (hc("run", "--bg", "--no-parent", "--cwd", repo, "--", *argv) or {}).get("address")


def cmd_start(a, prompt=None):
    """Start a PM session of any agent kind for a project and hand it the project's record.

    --space new (the default) gives the PM a space of its own, called --name (default: the folder's name);
    --space current puts it in a tab of the space this command runs in, as before."""
    if not Path(a.repo).is_dir():
        sys.exit(f"{a.repo} is not a directory")
    repo = project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    rec = pm_record(repo) or {}
    if rec.get("archived"):
        sys.exit(tr(f"{Path(repo).name} is archived ({rec['archived']}); bring it back with `pm.py restore`",
                    f"{Path(repo).name} 已归档（{rec['archived']}）；用 `pm.py restore` 恢复"))
    pm = find_pm(repo=repo)
    if pm:
        sys.exit(f"PM for {Path(repo).name} already exists at {pm['pane_id']}; use `pm.py rotate` to replace it")
    cfg = config().get("pm") or {}
    kind = a.kind or cfg.get("kind") or "claude"
    skill = Path(__file__).resolve().parent.parent
    handover = f"python3 {Path(__file__).resolve()} handover"
    prompt = prompt or "[from pm.py start] " + tr(
        f"You are the PM (project manager) of the {Path(repo).name} project. Read {skill}/SKILL.md and "
        f"{skill}/references/pm-playbook.md, then run `{handover}` and work from what it prints. Then tell the "
        "user in three or four sentences what is open and what is waiting for them.",
        f"你是 {Path(repo).name} 项目的 PM（项目协调者）。先读 {skill}/SKILL.md 和 "
        f"{skill}/references/pm-playbook.md，再运行 `{handover}`，按它给出的内容开始工作，"
        "然后用三四句话告诉用户：有哪些在办的事、哪些事在等他。")
    name = (getattr(a, "name", None) or "").strip() or rec.get("space_name") or Path(repo).name
    own = (hc("get", HC_TERMINAL) or {}) if HC_TERMINAL else {}
    current = (getattr(a, "space", None) or "new") == "current"
    if current and (getattr(a, "name", None) or "").strip():
        print(tr("--name names a new space; with --space current it is not used (the tab is called "
                 f"{pm_tab_name(repo)})", f"--name 用来给新 space 命名；--space current 时不用它"
                 f"（标签页叫 {pm_tab_name(repo)}）"), file=sys.stderr)
    model = a.model or cfg.get("model") or ""
    # Claude Code gets its prompt after `--`, where the tool flag `narrow_pm` adds cannot take it as a tool name.
    argv = (agent_argv(kind, model) + (["--", prompt] if takes_prompt(kind) else []) if kind == "claude"
            else agent_argv(kind, model, prompt=prompt))
    argv = narrow_pm(kind, argv)
    made = start_pm_terminal(repo, argv, (own.get("labels") or {}).get("herdr.space"), "" if current else name)
    if not made:
        sys.exit("could not start the PM session (is herdr-core running?)")
    try:
        cmd_claim(argparse.Namespace(repo=repo, pane=f"hc:{made}", kind=kind))
    except SystemExit:
        hc("kill", made)
        hc("rm", made)
        raise
    path = PMS / f"{project_slug(repo)}.json"
    if not current and path.exists():
        # The name the user gave the project: a restore opens its space under it again.
        path.write_text(json.dumps({**json.loads(path.read_text()), "space_name": name}, ensure_ascii=False,
                                   indent=2) + "\n")
    if not takes_prompt(kind) and not send_when_ready(made, prompt):
        print(f"the first prompt was not typed into hc:{made}; send it by hand:\n{prompt}")
    return made


# Statuses of open work that an archive pauses; a restore puts each back.
ARCHIVE_PAUSES = ("proposed", "in_progress", "review", "blocked")


def project_tasks(repo):
    name = Path(repo).name
    return [t for t in all_tasks() if t.get("project") == name and str(Path(t["repo"]).resolve()) == repo]


def registered_repo(project):
    """The folder of a project given as its folder, or as the name it is registered under."""
    if Path(project).is_dir():
        return project_root(project)
    for path in sorted(PMS.glob("*.json")) if PMS.exists() else []:
        rec = json.loads(path.read_text())
        if project in (rec.get("project"), path.stem) and rec.get("repo"):
            return rec["repo"]
    return None


def cmd_archive(a):
    """Put a project away: its PM's session ends and its open tasks are paused. The ledger, the conversation
    log, the decisions and the handover notes stay; `pm.py restore` brings it back."""
    repo = registered_repo(a.project)
    rec = pm_record(repo) if repo else None
    if not rec:
        sys.exit(f"no PM registered for {a.project}")
    name = Path(repo).name
    if rec.get("archived"):
        print(tr(f"{name} is already archived ({rec['archived']})", f"{name} 已经归档（{rec['archived']}）"))
        return
    rec["archived"] = now()[:10]
    (PMS / f"{project_slug(repo)}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    paused = 0
    for task in project_tasks(repo):
        if task["status"] in ARCHIVE_PAUSES:
            task["paused_from"], task["status"] = task["status"], "paused"
            note(task, tr("project archived", "项目归档"))
            save(task)
            paused += 1
    print(tr(f"{name} archived: {paused} tasks paused", f"{name} 已归档：{paused} 个任务暂停"))
    end_pm(rec, name)  # last: the PM may be the session running this command


def end_pm(rec, name):
    """End an archived project's PM session: the registered one only, and only while it is still this
    project's PM. It first stops being findable as the PM (label or name), so a restore does not take it
    for a live one even when it cannot be ended."""
    if rec.get("runtime") == "hc":
        term = rec.get("terminal") or ""
        info = (hc("get", term) or {}) if term else {}
        if not info or (info.get("labels") or {}).get("pm") != name:
            print(tr(f"PM hc:{term} is not running", f"PM hc:{term} 不在运行"))
            return
        hc("label", term, "pm=", f"pm.retired={name}")
        if (info.get("state") != "live" or hc("kill", term) is not None) and hc("rm", term) is not None:
            print(tr(f"PM hc:{term} ended", f"PM hc:{term} 已结束"))
        else:
            print(tr(f"PM hc:{term} could not be ended; close it by hand. It no longer counts as the PM.",
                     f"PM hc:{term} 结束不了，请手动关掉；它已不再算作 PM。"))
        return
    # A PM in the herdr terminal UI: the agent registered under the PM's name in that pane.
    pane, listing = rec.get("pane") or "", herdr("agent", "list")
    if listing is None:
        print(tr(f"herdr is not reachable, so PM {pane} could not be ended; close it by hand.",
                 f"herdr 连不上，没法结束 PM {pane}；请手动关掉。"))
        return
    if not any(x.get("pane_id") == pane and x.get("name") == rec.get("name") for x in listing.get("agents") or []):
        print(tr(f"PM {pane} is not running", f"PM {pane} 不在运行"))
        return
    herdr("agent", "rename", pane, f"ex-{rec['name']}")
    if herdr("pane", "close", pane) is not None:
        print(tr(f"PM {pane} ended", f"PM {pane} 已结束"))
    else:
        print(tr(f"PM {pane} could not be ended; close it by hand. It is renamed ex-{rec['name']} and no longer "
                 "counts as the PM.", f"PM {pane} 结束不了，请手动关掉；它已改名 ex-{rec['name']}，不再算作 PM。"))


def cmd_restore(a):
    """Bring an archived project back: its paused tasks return to where they were and a fresh PM starts from
    the handover. Either all of that happens or nothing does."""
    repo = registered_repo(a.project)
    rec = pm_record(repo) if repo else None
    if not rec:
        sys.exit(f"no PM registered for {a.project}")
    name, archived = Path(repo).name, rec.get("archived")
    if not archived:
        print(tr(f"{name} is not archived", f"{name} 没有归档"))
        return
    # What would make the start fail, checked before anything changes.
    if not Path(repo).is_dir():
        sys.exit(tr(f"{repo} is gone; {name} stays archived", f"{repo} 不存在了；{name} 仍是归档状态"))
    live = find_pm(repo=repo)
    if live:
        sys.exit(tr(f"the old PM of {name} still runs at {live['pane_id']}; end it first. {name} stays archived",
                    f"{name} 的旧 PM 还在 {live['pane_id']} 运行，先把它关掉；{name} 仍是归档状态"))
    if hc("server", "status") is None:
        sys.exit(tr(f"herdr-core is not reachable; {name} stays archived",
                    f"herdr-core 连不上；{name} 仍是归档状态"))
    path = PMS / f"{project_slug(repo)}.json"
    rec.pop("archived")
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    restored = {}
    for task in project_tasks(repo):
        if task["status"] == "paused" and task.get("paused_from"):
            restored[task["id"]] = task["paused_from"]
            task["status"] = task.pop("paused_from")
            note(task, tr("project restored", "项目恢复"))
            save(task)
    handover = f"python3 {Path(__file__).resolve()} handover"
    prompt = "[from pm.py restore] " + tr(
        f"You are the PM of the {name} project (pm skill); the project was archived and has just been restored. "
        f"First run `{handover}` and take over from what it prints, nothing else. Then tell the user in three or "
        "four sentences what you took over and what is waiting for them.",
        f"你是 {name} 项目的 PM（pm skill），这个项目刚从归档中恢复。"
        f"先运行 `{handover}`，只按它给出的内容接手，"
        "然后用三四句话告诉用户：你接手了哪些在办的事、哪些事在等他。")
    try:
        cmd_start(argparse.Namespace(repo=repo, kind=a.kind or rec.get("agent"), model=a.model, name="",
                                     space="new"), prompt=prompt)
    except SystemExit as stop:
        # Put it back as it was: archived, with the same tasks paused.
        path.write_text(json.dumps({**json.loads(path.read_text()), "archived": archived}, ensure_ascii=False,
                                   indent=2) + "\n")
        for task_id, status in restored.items():
            task = load(task_id)
            task["status"], task["paused_from"] = "paused", status
            note(task, tr("restore failed; paused again", "恢复失败，重新暂停"))
            save(task)
        sys.exit(tr(f"{name} was not restored ({stop}); it stays archived",
                    f"{name} 没有恢复（{stop}）；仍是归档状态"))
    print(tr(f"{name} restored: {len(restored)} tasks back", f"{name} 已恢复：{len(restored)} 个任务恢复原状态"))


def cmd_rotate(a):
    """Replace the PM session of a project with a fresh one that starts from `handover`."""
    repo = project_root(a.repo)
    rec = pm_record(repo) if repo else None
    if not rec:
        sys.exit("no PM registered for this project")
    d = project_dir(repo)
    is_self = rec.get("pane") == PANE
    transcript = a.transcript or (own_transcript() if is_self else "")
    notes = f"Written {now()} by the outgoing PM ({rec.get('pane')}).\n\n{a.notes.strip()}\n" if a.notes else ""
    (d / "handover.md").write_text(notes)
    previous = {"pane": rec.get("pane"), "transcript": transcript, "at": now(),
                "tokens": context_tokens(transcript) if transcript else 0}
    handover = f"python3 {Path(__file__).resolve()} handover"
    prompt = "[from pm.py rotate] " + tr(
        f"You are the PM of the {Path(repo).name} project (pm skill), replacing the session that was just rotated "
        "out. If the startup notice says another PM exists, that is the one you replace; the registration is "
        f"about to move to you. First run `{handover}` and take over from what it prints, nothing else. Then tell "
        "the user in three or four sentences what you took over and what is waiting for them.",
        f"你是 {Path(repo).name} 项目的 PM（pm skill），接替刚轮换下去的上一任会话。"
        "启动提示里如果说另有一个 PM，那就是你要接替的那一个，登记马上会转到你名下。"
        f"先运行 `{handover}`，只按它给出的内容接手，"
        "然后用三四句话告诉用户：你接手了哪些在办的事、哪些事在等他。")
    if rec.get("runtime") != "hc":
        return rotate_herdr(a, repo, rec, previous, prompt, is_self)
    old = hc("get", rec["terminal"]) or {}
    kind = rec.get("agent") or terminal_kind(old) or "claude"
    argv = narrow_pm(kind, successor_argv(kind, ((old.get("foreground") or {}).get("argv") or [])[1:], a.model, prompt))
    made = start_pm_terminal(repo, argv, (old.get("labels") or {}).get("herdr.space"))
    if not made:
        sys.exit("could not start the new PM session; the old one stays registered")
    hc("label", made, f"pm={Path(repo).name}")
    # The retired session stays open to read; the label keeps the project view from listing it as a conversation.
    hc("label", rec["terminal"], "pm=", f"pm.retired={Path(repo).name}")
    name_tab(made, pm_tab_name(repo))
    name_tab(rec["terminal"], "", only_if=pm_tab_name(repo))
    rec.update({"pane": f"hc:{made}", "terminal": made, "claimed": now(), "previous": previous, "agent": kind,
                "rotations": rec.get("rotations", 0) + 1})
    (PMS / f"{project_slug(repo)}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    if not takes_prompt(kind) and not send_when_ready(made, prompt):
        print(f"the handover prompt was not typed into hc:{made}; send it by hand:\n{prompt}")
    print(f"new PM session started in hc:{made}; {previous['pane']} is retired"
          + (": stop acting as PM in this session and tell the user to continue there." if is_self else "."))


# ---- offline threads: the terminal is gone, the work is not -------------------

# Open work whose terminal is looked at: a task in one of these that names a terminal that is gone is offline.
ATTACHED = ("in_progress", "review", "blocked")
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
# What the pm hooks put in a session's transcript: this one was a PM, not the agent of a task.
PM_SESSION_MARK = "the PM for this project (pm skill)"


def live_hc_terminals():
    """Addresses of the live herdr-core terminals on this computer, or None when hc cannot say."""
    listing = hc("ls")
    if not isinstance(listing, dict) or not isinstance(listing.get("terminals"), list):
        return None
    return {t.get("address") for t in listing["terminals"] if t.get("state", "live") == "live"}


def task_offline(task, hc_live, tui_panes):
    """The task is open and the terminal it names is gone: hc lists no live terminal at that address, or, in the
    herdr terminal UI, no agent runs in that pane. hc_live / tui_panes: what is live, None when it is not known
    (then nothing is offline). The status stays as it is: whether the work goes on is for the PM to say."""
    pane = task.get("pane") or ""
    if task.get("status") not in ATTACHED or not pane or "/" in pane:  # "/": a terminal on another machine
        return False
    if pane.startswith("hc:"):
        return hc_live is not None and pane[3:] not in hc_live
    return tui_panes is not None and pane not in tui_panes


def offline_now(task):
    hc_live = live_hc_terminals() if (task.get("pane") or "").startswith("hc:") else None
    listing = agents() if not (task.get("pane") or "").startswith("hc:") else []
    return task_offline(task, hc_live, {x.get("pane_id") for x in listing} if listing else None)


def claude_folder(path):
    """The folder under ~/.claude/projects where Claude Code keeps the sessions started in path."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def session_places(task, old_cwd=""):
    """Folders the task's agent may have been started in: its worktree, the old terminal's folder, its repository
    and the folders above that, short of the home folder (and of "/" and its folders)."""
    places = [p for p in (task.get("worktree"), old_cwd, task.get("repo")) if p]
    home = Path.home()
    parent = Path(task["repo"]).parent if task.get("repo") else None
    while parent and parent != home and len(parent.parts) > 2:
        places.append(str(parent))
        parent = parent.parent
    return list(dict.fromkeys(str(Path(p)) for p in places))


def created_at(task):
    try:
        return datetime.datetime.strptime(task.get("created") or "", "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        return 0


PM_PROMPT = re.compile(r"\[from pm\.py (?:start|rotate|restore)\]")


def opening(text):
    """A transcript's opening: its lines up to the first reply (startup hook output, the first prompt)."""
    head = []
    for line in text.split("\n"):
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if isinstance(row, dict) and "assistant" in (row.get("type"), (row.get("message") or {}).get("role"),
                                                     (row.get("payload") or {}).get("role")):
            break
        head.append(line)
    return "\n".join(head)


def pm_session(text):
    """A PM's session: it was started as one (pm.py start/rotate/restore) or told it is one at startup.
    Only the opening counts: a worker may quote those words later on."""
    head = opening(text)
    return PM_SESSION_MARK in head or bool(PM_PROMPT.search(head))


def session_score(text, task_id):
    """How surely a transcript is the agent of task_id: 2 when it reports on the task (`update <id>`, which its
    brief or its own registration put there), 1 when it only names it, 0 when it is not (a PM's session; a
    review's names `<id>-review`, which does not count as a report on the task)."""
    if task_id not in text or pm_session(text):
        return 0
    return 2 if re.search(rf"\b(?:update|log) {re.escape(task_id)}(?![\w.-])", text) else 1


def first_cwd(path):
    """The folder a transcript's session was started in: the first `cwd` it records."""
    try:
        with open(path, errors="replace") as f:
            for line in f:
                found = re.search(r'"cwd":\s*"((?:[^"\\]|\\.)*)"', line)
                if found:
                    return json.loads(f'"{found.group(1)}"')
    except OSError:
        pass
    return ""


def claude_sessions(task, places):
    since = created_at(task) - 600
    for place in places:
        folder = CLAUDE_PROJECTS / claude_folder(place)
        for path in folder.glob("*.jsonl") if folder.is_dir() else []:
            try:
                if path.stat().st_mtime < since:
                    continue
                score = session_score(path.read_text(errors="replace"), task["id"])
            except OSError:
                continue
            if score:
                yield {"kind": "claude", "id": path.stem, "path": str(path), "cwd": first_cwd(path) or place,
                       "score": score, "mtime": path.stat().st_mtime}


def codex_sessions(task, places):
    since = created_at(task) - 600
    for path in CODEX_SESSIONS.rglob("rollout-*.jsonl") if CODEX_SESSIONS.is_dir() else []:
        try:
            if path.stat().st_mtime < since:
                continue
            text = path.read_text(errors="replace")
            meta = (json.loads(text.split("\n", 1)[0]) or {}).get("payload") or {}
        except (OSError, ValueError, AttributeError):
            continue
        cwd = str(meta.get("cwd") or "")
        if not meta.get("id") or not any(cwd == p or cwd.startswith(p + "/") for p in places):
            continue
        score = session_score(text, task["id"])
        if score:
            yield {"kind": "codex", "id": str(meta["id"]), "path": str(path), "cwd": cwd, "score": score,
                   "mtime": path.stat().st_mtime}


def find_session(task, old_cwd=""):
    """The session of the task's agent: the one the ledger recorded, else the transcript that reports on the task
    most surely, newest first, among Claude Code's (~/.claude/projects) and Codex's (~/.codex/sessions) sessions
    started in one of the task's folders since it was registered. None when there is none."""
    kept = task.get("session") or {}
    if kept.get("kind") == "claude" and kept.get("id"):
        hits = list(CLAUDE_PROJECTS.glob(f"*/{kept['id']}.jsonl")) if CLAUDE_PROJECTS.is_dir() else []
        if hits:
            return {"kind": "claude", "id": kept["id"], "path": str(hits[0]), "cwd": first_cwd(hits[0])}
    places = session_places(task, old_cwd)
    found = list(claude_sessions(task, places)) + list(codex_sessions(task, places))
    found.sort(key=lambda s: (s["score"], s["mtime"]), reverse=True)
    return found[0] if found else None


def dispatched_with(task):
    """kind, model and effort the task's worker was dispatched with: its `worker` record, or, for a task from before
    that record, its dispatch note ("dispatched to w (codex gpt-5 high)")."""
    record = task.get("worker")
    if isinstance(record, dict) and record.get("kind"):
        return record["kind"], record.get("model") or "", record.get("effort") or ""
    for entry in task.get("log") or []:
        found = re.match(r"dispatched to \S+ \(([^()]*)\)$", entry.get("text") or "")
        if found:
            parts = found.group(1).split() + ["", "", ""]
            return parts[0], parts[1], parts[2]
    return task.get("kind") or "", "", ""


def resume_argv(kind, session_id, model="", effort="", advisor="", fallback=""):
    """The command that resumes a session of this kind, or None for a kind that cannot be resumed here."""
    argv = agent_argv(kind, model, effort, advisor=advisor, fallback=fallback)
    if kind == "claude":
        return argv + ["--resume", session_id]
    if kind == "codex":
        return [argv[0], "resume", *argv[1:], session_id]
    return None


def reattach_prompt(task, cwd, resumed):
    """What the agent of an offline task is told: a resumed session only that it is back; a fresh one the title,
    the brief, the latest ledger entries and how to report."""
    tid, title = task["id"], task.get("title") or task["id"]
    if resumed:
        return "[from pm.py reattach] " + tr(
            f"This session's terminal was gone and it has been reattached. Carry on with task {tid} ({title}): "
            f"read the ledger's latest entries (`{pm_command()} show {tid}`) and the state of {cwd}, then continue "
            "and report in the ledger as before.",
            f"这个会话的终端断开过，现在接回来了。继续任务 {tid}（{title}）：先看台账最近的记录"
            f"（`{pm_command()} show {tid}`）和 {cwd} 的现状，再接着做，照原来的方式在台账汇报。")
    sent = STATE / "sent" / f"{tid}.md"
    brief = ""
    for path in (sent, Path(task.get("brief") or "")):
        try:
            if str(path) and path.is_file():
                brief = path.read_text().strip()
                break
        except OSError:
            pass
    log = "\n".join(f"- {e.get('at')} {e.get('by')}: {clip(' '.join(str(e.get('text') or '').split()), 400)}"
                    for e in (task.get("log") or [])[-8:])
    where = cwd + (tr(f", branch {task['branch']}", f"，分支 {task['branch']}") if task.get("branch") else "")
    text = "[from pm.py reattach] " + tr(
        f"You take over the thread \"{title}\" (task {tid}). Its terminal is gone and its session could not be "
        f"found. Working folder: {where}. Read git status and git log there first to see what is done.",
        f"你来接手线程「{title}」（任务 {tid}）。它原来的终端断开了，会话也找不到了。"
        f"工作目录：{where}。先在那里看 git status 和 git log，弄清已经做了哪些。")
    if brief:
        text += "\n\n" + tr("The brief:", "任务书：") + "\n" + brief
    if log:
        text += "\n\n" + tr("The ledger's latest entries:", "台账最近的记录：") + "\n" + log
    text += "\n\n" + tr("Carry on from there.", "从那里接着做。")
    return text if f"update {tid} --status review" in brief else text + report_section(tid)


def reattach_plan(task, old_cwd=""):
    """How `reattach` brings the task's agent back: {how: resume|fresh, kind, argv, cwd, prompt, session}."""
    kind, model, effort = dispatched_with(task)
    advisor = (task["worker"].get("advisor") or "") if isinstance(task.get("worker"), dict) else ""
    session = find_session(task, old_cwd)
    same = session and session["kind"] == kind
    role = "reviewer" if task.get("review_of") else "worker"
    argv = resume_argv(session["kind"], session["id"], model if same else "", effort if same else "",
                       advisor if same else "", fable_fallback(kind, model, role) if same else "") if session else None
    # A review's brief is in the ledger's sent/; its reviewer reads the reviewed task's brief too.
    reviewed = TASKS / f"{task.get('review_of')}.json"
    of = json.loads(reviewed.read_text()).get("brief") or "" if task.get("review_of") and reviewed.is_file() else ""
    reads = outside_reads(task.get("repo") or "", task.get("brief") or "", of)
    if argv:
        argv += read_settings(session["kind"], reads)
        cwd = session["cwd"] if Path(session["cwd"] or "").is_dir() else ""
        cwd = cwd or next(p for p in session_places(task, old_cwd) + [str(Path.home())] if Path(p).is_dir())
        return {"how": "resume", "kind": session["kind"], "argv": argv, "cwd": cwd, "session": session["id"],
                "prompt": reattach_prompt(task, cwd, True)}
    kind = kind or worker_defaults(argparse.Namespace(kind="", model=model, effort=effort)).kind
    cwd = next((p for p in (task.get("worktree"), task.get("repo"), old_cwd) if p and Path(p).is_dir()),
               str(Path.home()))
    return {"how": "fresh", "kind": kind, "argv": agent_argv(kind, model, effort, advisor=advisor,
                                                            fallback=fable_fallback(kind, model, role))
            + read_settings(kind, reads), "cwd": cwd,
            "session": "", "prompt": reattach_prompt(task, cwd, False)}


def pm_records():
    out = []
    for path in sorted(PMS.glob("*.json")) if PMS.exists() else []:
        with contextlib.suppress(OSError, ValueError):
            rec = json.loads(path.read_text())
            out.append({**rec, "name": rec.get("name") or "", "project": rec.get("project") or "",
                        "repo": rec.get("repo") or ""})
    return out


def owner_of(task, pms):
    """The PM a task belongs to, as the board counts it: the PM of its repository, else of a repository that
    holds it (a project inside another, such as issues/site-a), else of a project of that name. None: no PM."""
    repo = str(Path(task.get("repo") or "/").resolve())
    exact = [p for p in pms if p["repo"] and str(Path(p["repo"]).resolve()) == repo]
    nested = [p for p in pms if p["repo"] and repo.startswith(str(Path(p["repo"]).resolve()) + "/")]
    named = [p for p in pms if p["project"].lower() == str(task.get("project") or "").lower()]
    hit = exact or nested or named
    return hit[0] if hit else None


def start_beside_pm(task, plan, name):
    """Start the plan's program for the task where `dispatch` would: a herdr-core sub-agent of the project's PM
    (so the app lists it under the PM, in the PM's space), a tab in a herdr (TUI) PM's workspace, or a bare
    terminal when the project has no PM. The PM is the one the board shows the task under (owner_of).
    Returns (the new pane: "hc:t9" or a herdr pane id, its herdr workspace or ""), or ("", "")."""
    rec = owner_of(task, pm_records())
    pm = find_pm(repo=rec["repo"]) if rec and Path(rec["repo"]).is_dir() else None
    pane = (pm or {}).get("pane_id") or ""
    if pane and not pane.startswith("hc:"):
        workspace = pm.get("workspace_id") or ((herdr("pane", "get", pane) or {}).get("pane") or {}).get("workspace_id")
        made = re.search(r'"pane_id": "([^"]+)"', json.dumps(
            herdr("tab", "create", "--workspace", workspace, "--cwd", plan["cwd"], "--label", name, "--no-focus")
            or {})) if workspace else None
        if not made:
            return "", ""  # not a bare terminal elsewhere: the PM's workspace or nothing
        herdr("pane", "run", made.group(1), shlex.join(
            plan["argv"] + ([plan["prompt"]] if takes_prompt(plan["kind"]) else [])))
        return made.group(1), workspace
    placement = ["--parent", pane[3:], "--outlive-parent", "--no-notify"] if pane.startswith("hc:") else ["--no-parent"]
    made = (hc("run", "--bg", *placement, "--name", name, "--cwd", plan["cwd"], "--", *plan["argv"]) or {}).get("address")
    return (f"hc:{made}", "") if made else ("", "")


def stale_lock(lock):
    """A reattach lock whose holder is gone: its process has ended, or it is older than five minutes. One
    without a pid yet is being written; it is stale only after a few seconds."""
    try:
        text, age = lock.read_text().split(), time.time() - lock.stat().st_mtime
    except OSError:
        return False
    if age > 300:
        return True
    if not text or not text[0].isdigit():
        return age > 5
    try:
        os.kill(int(text[0]), 0)
    except ProcessLookupError:
        return True
    except OSError:
        pass  # alive, another user's
    return False


def cmd_reattach(a):
    """Bring back the agent of a task whose terminal is gone: resume its session when one is found, else start an
    agent of the same kind with the task's title, brief and latest ledger entries. The new terminal goes where
    `dispatch` puts one and becomes the task's pane; the status is left as it is."""
    task = load(a.id)
    if task["status"] not in ATTACHED:
        sys.exit(tr(f"{a.id} is {task['status']}: only open work (in progress, review, blocked) is reattached",
                    f"{a.id} 的状态是 {task['status']}：只有进行中、待审、阻塞的任务能接回"))
    if not offline_now(task):
        sys.exit(tr(f"{a.id} is not offline: its terminal {task.get('pane') or '(none)'} is still there "
                    "(or cannot be checked)", f"{a.id} 没有断开：它的终端 {task.get('pane') or '（无）'} 还在（或查不到）"))
    lock = STATE / "reattach" / f"{a.id}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if stale_lock(lock):
        with contextlib.suppress(OSError):
            lock.unlink()  # left by a reattach that died (the view's exec timed out and killed it)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        sys.exit(tr(f"{a.id} is being reattached already", f"{a.id} 正在接回"))
    os.write(fd, f"{os.getpid()} {int(time.time())}\n".encode())
    os.close(fd)
    try:
        old = hc_terminal_of(task)
        old_cwd = ((hc("get", old) or {}).get("cwd") or "") if old else ""
        plan = reattach_plan(task, old_cwd)
        name = task.get("agent") or task["id"]
        pane, workspace = start_beside_pm(task, plan, name)
        if not pane:
            sys.exit(tr(f"no terminal could be started for {a.id}; nothing changed",
                        f"没能为 {a.id} 开出终端；什么都没改"))
        made = pane[3:] if pane.startswith("hc:") else ""
        if made:
            hc("label", made, f"task={task['id']}")
        task = load(a.id)
        previous = task.get("pane") or ""
        task["pane"], task["workspace"] = pane, workspace  # as dispatch records it: herdr's workspace, none in hc
        task["worker_pane"] = pane
        if plan["how"] == "resume":
            task["session"] = {"kind": plan["kind"], "id": plan["session"]}
            note(task, tr(f"reattached: resumed {plan['kind']} session {plan['session']} in {pane} "
                          f"({previous} was gone)",
                          f"接回：在 {pane} 恢复了 {plan['kind']} 会话 {plan['session']}（原终端 {previous} 已不在）"))
        else:
            note(task, tr(f"reattached: no session found; started {plan['kind']} in {pane} with the title, brief and "
                          f"latest ledger entries ({previous} was gone)",
                          f"接回：没找到会话，在 {pane} 新开了 {plan['kind']}，交给它标题、任务书和最近的台账记录"
                          f"（原终端 {previous} 已不在）"))
        save(task)
        sent = not made or send_when_ready(made, plan["prompt"], tries=30, pause=2,
                                           strict=plan["kind"] in ("claude", "codex"), trust=plan["cwd"])
        if not sent:
            seen = screen_line(made)
            task = load(a.id)
            note(task, tr(f"reattach prompt not sent; the screen: {seen}", f"接回的提示没送达；屏幕上是：{seen}"))
            save(task)
            sys.exit(tr(f"{pane} is started but the prompt was not sent. Its screen: {seen}",
                        f"{pane} 已经开了，但提示没送达。屏幕上是：{seen}"))
        print(f"{plan['how']} {plan['kind']} pane={pane}" + (f" session={plan['session']}" if plan["session"] else ""))
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


# ---- dash: live board in the browser ----------------------------------------

DASH_HTML = Path(__file__).resolve().parent.parent / "assets" / "dash.html"
TURN_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d) \[([^\]]+)\] (UserPromptSubmit|Stop): turn")


def dash_state():
    """Everything the dashboard draws: PMs, tasks, live agents and recent events."""
    listing = agents()
    by_pane = {x["pane_id"]: x for x in listing}
    agent_map = {x["pane_id"]: {"name": x.get("name") or "", "kind": x.get("agent") or "",
                                "status": x.get("agent_status") or "",
                                "title": x.get("terminal_title_stripped") or ""} for x in listing}
    pms = []
    for path in sorted(PMS.glob("*.json")) if PMS.exists() else []:
        rec = json.loads(path.read_text())
        live = by_pane.get(rec.get("pane") or "", {})
        if rec.get("runtime") == "hc":
            live = hc_pm(rec.get("repo") or "") or {}
        alive = live.get("name") == rec.get("name")
        pms.append({"name": rec["name"], "project": rec.get("project", ""), "repo": rec.get("repo", ""),
                    "pane": rec.get("pane", ""), "status": live.get("agent_status") if alive else "offline",
                    "title": live.get("terminal_title_stripped", "") if alive else "",
                    "agent": rec.get("agent", ""), "archived": rec.get("archived"),
                    # The project's conversation log; read-only here, so its folder is not created.
                    "conversation": str(PROJECTS / project_slug(rec["repo"]) / "conversation.jsonl")
                    if rec.get("repo") else "",
                    # Sessions under either folder work in this project (the project view lists them).
                    "worktrees": str(worktree_home(rec["repo"])) if rec.get("repo") else ""})

    def owner_pm(t):
        hit = owner_of(t, pms)
        return hit["name"] if hit else ""

    # The blocked tasks the user has answered, from each project's conversation log (read only when one of
    # its tasks is blocked): the project view says Answered, and they are not counted as waiting.
    every = all_tasks()
    blocked, asked = {}, {}
    for t in every:
        if t["status"] == "blocked":
            blocked.setdefault(owner_pm(t), {})[t["id"]] = t.get("title") or ""
            asked[t["id"]] = asked_at(t)
    answered = set()
    for p in pms:
        if blocked.get(p["name"]) and p["conversation"]:
            answered |= answered_tasks(conversation_events(p["conversation"]), blocked[p["name"]], asked) & set(blocked[p["name"]])

    day_ago = (datetime.datetime.now() - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    tasks, events = [], []
    # Whose terminal is gone: one look at hc, and only when an open task names an hc terminal.
    hc_live = live_hc_terminals() if any(t["status"] in ATTACHED and (t.get("pane") or "").startswith("hc:")
                                         for t in every) else None
    tui_panes = set(by_pane) if listing else None
    left = []
    for t in every:
        # Closed work stays on the board for a day, until `retire` cleans it up.
        if not (t["status"] in ACTIVE or (t.get("updated", "") >= day_ago and not t.get("retired"))):
            left.append(t)
            continue
        pm = owner_pm(t)
        pm_pane = next((p["pane"] for p in pms if p["name"] == pm), "")
        log = t.get("log") or []
        tasks.append({k: t.get(k) or "" for k in ("id", "title", "project", "status", "owner", "pane", "agent",
                                                   "branch", "updated", "parent")}
                     | ({"paused_from": t["paused_from"]} if t.get("paused_from") else {})
                     | ({"answered": True} if t["id"] in answered else {})
                     # when the ledger last asked the user (asked_at): pm-project's answers to it come after
                     | ({"asked_at": asked[t["id"]]} if asked.get(t["id"]) else {})
                     # a review thread (`pm.py review`): the task it reviews; the views fold it into that task
                     | ({"review_of": t["review_of"]} if t.get("review_of") else {})
                     | {"pm": pm, "latest": (log[-1].get("text", "") if log else ""), "cleanup": needs_cleanup(t),
                        "offline": task_offline(t, hc_live, tui_panes),
                        # what the worker was dispatched with ({profile, kind, model, effort, advisor}; {}: unknown)
                        "engine": t["worker"] if isinstance(t.get("worker"), dict) else {},
                        # a task parked on the PM's own pane has no worker of its own
                        "worker": by_pane.get(t["pane"], {}).get("agent_status", "")
                        if t.get("pane") and t["pane"] != pm_pane else ""})
        for i, e in enumerate(log):
            by = e.get("by", "")
            status = re.search(r"\bstatus=(\w+)", e.get("text", ""))
            events.append({"key": f"{t['id']}#{i}", "at": e.get("at", ""), "by": by, "task": t["id"], "pm": pm,
                           "kind": "dispatch" if by in ("user", pm_pane) else "report",
                           "status": status.group(1) if status else "", "text": e.get("text", "")})
    # Sub-threads that are off the board (retired, or closed a day ago) while the task they were split from is
    # on it: the project view lists them under that task. Apart from `tasks`, which the board and counts read.
    shown = {t["id"] for t in tasks}
    parts = [{k: t.get(k) or "" for k in ("id", "title", "project", "status", "parent", "updated")}
             | {"pm": owner_pm(t), "retired": bool(t.get("retired"))} for t in left if t.get("parent") in shown]
    # Chat turns with a PM, as recorded by the turn hook.
    if TURN_LOG.exists():
        pane_pm = {p["pane"]: p["name"] for p in pms}
        for line in TURN_LOG.read_text(errors="replace").splitlines()[-400:]:
            m = TURN_LINE.match(line)
            if m and m.group(2) in pane_pm:
                events.append({"key": "m:" + line, "at": m.group(1), "by": m.group(2), "task": "",
                               "pm": pane_pm[m.group(2)], "status": "", "text": "",
                               "kind": "prompt" if m.group(3) == "UserPromptSubmit" else "reply"})
    # The numbers on a project's card, counted as the project view counts: waiting is blocked and not answered,
    # and working is work going on: a task in progress whose terminal is gone (offline) is not.
    today = now()[:10]
    for p in pms:
        p["counts"] = {"working": 0, "waiting": 0, "review": 0, "proposed": 0, "merged_today": 0}
    by_name = {p["name"]: p["counts"] for p in pms}
    # A review thread is counted with the task it reviews, while that task is on the board, as the views fold
    # it in (the mods' foldReviews): that task counts as what the open review is, waiting or in review. An open
    # review of a task that is over counts on its own.
    by_id = {t["id"]: t for t in every}
    reviews = {t["review_of"]: t for t in every if t.get("review_of") in shown and t["review_of"] != t["id"]
               and (t["status"] in CLOSED or by_id[t["review_of"]]["status"] not in CLOSED)}

    def folded_status(t):
        r = reviews.get(t["id"])
        if not r or r["status"] in CLOSED + ["paused"] or t["status"] in ("blocked", "paused"):
            return t["status"], t["id"] in answered
        return ("blocked", r["id"] in answered) if r["status"] == "blocked" else ("review", False)

    for t in every:
        if reviews.get(t.get("review_of")) is t:
            continue
        counts = by_name.get(owner_pm(t))
        status, is_answered = folded_status(t)
        working = "" if task_offline(t, hc_live, tui_panes) else "working"
        key = {"in_progress": working, "blocked": "" if is_answered else "waiting", "review": "review",
               "proposed": "proposed"}.get(status) or ("merged_today" if t["status"] == "merged" and t.get("updated", "")[:10] == today else "")
        if counts is not None and key:
            counts[key] += 1
    events = sorted(events, key=lambda e: e["at"])[-120:]
    return {"now": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "pms": pms, "tasks": tasks,
            "agents": agent_map, "events": events, "lang": tr("en", "zh"), "home": str(STATE), "retired_parts": parts}


def cmd_state(a):
    print(json.dumps(dash_state(), ensure_ascii=False))


def cmd_dash(a):
    import http.server
    import threading
    import time
    import webbrowser
    lock, cache = threading.Lock(), {"at": 0.0, "body": b""}

    class Handler(http.server.BaseHTTPRequestHandler):
        # The stdlib default (HTTP/0.9) answers an unparsable request, such as a browser trying
        # https first, with a bare body and no headers, which some browsers save as a file.
        default_request_version = "HTTP/1.0"

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            if self.path.split("?")[0] == "/api/state":
                with lock:  # one herdr call per second however many tabs are open
                    if time.time() - cache["at"] > 1:
                        cache["body"] = json.dumps(dash_state(), ensure_ascii=False).encode()
                        cache["at"] = time.time()
                    body, kind = cache["body"], "application/json; charset=utf-8"
            elif self.path.split("?")[0] in ("/", "/index.html"):
                body, kind = DASH_HTML.read_bytes(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def log_message(self, fmt, *args):
            line = fmt % args
            if '"GET /api/state' in line and '" 200 ' in line:
                return  # the page polls every 3 s; log only page loads and errors
            ua = self.headers.get("User-Agent", "-") if getattr(self, "headers", None) else "-"
            print(f"{self.log_date_time_string()} {self.client_address[0]} {line} [{ua}]", flush=True)

    server = http.server.ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}/"
    print(f"PM dashboard on {url}  (ctrl+c to stop)", flush=True)
    if a.host in ("0.0.0.0", ""):
        import socket
        try:  # the address other devices on the LAN reach this machine at (no packet is sent)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                print(f"on the LAN: http://{s.getsockname()[0]}:{a.port}/", flush=True)
        except OSError:
            pass
    if a.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    p = argparse.ArgumentParser(prog="pm.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("title")
    n.add_argument("--repo", default=".")
    n.add_argument("--status", default="in_progress", choices=ACTIVE + CLOSED)
    for f in ("owner", "workspace", "pane", "agent", "branch", "worktree", "base", "brief", "slug", "note"):
        n.add_argument(f"--{f}")
    n.add_argument("--parent", help="the id of the task this one was split from")
    n.add_argument("--option", action="append", metavar="TEXT",
                   help="an answer the user can pick in the project view (repeat for more; with --status blocked)")
    n.add_argument("--why", action=Why, metavar="TEXT", help="one line that explains the --option right before it")
    n.add_argument("--recommend", action="store_true", help="the first --option is the one you recommend")
    u = sub.add_parser("update")
    u.add_argument("id")
    for f in FIELDS + ["note"]:
        u.add_argument(f"--{f}", choices=ACTIVE + CLOSED if f == "status" else None)
    u.add_argument("--option", action="append", metavar="TEXT",
                   help="an answer the user can pick in the project view (repeat for more; with --status blocked)")
    u.add_argument("--why", action=Why, metavar="TEXT", help="one line that explains the --option right before it")
    u.add_argument("--recommend", action="store_true", help="the first --option is the one you recommend")
    u.add_argument("--keep", action="store_true",
                   help="with --status merged: keep the worker, worktree and branch (no automatic retire)")
    u.add_argument("--ask", action="store_true",
                   help="with --status blocked on a task the user has answered: ask a follow-up (a new question)")
    l = sub.add_parser("log")
    l.add_argument("id")
    l.add_argument("text")
    sub.add_parser("show").add_argument("id")
    sub.add_parser("board")
    sub.add_parser("status").add_argument("--all", action="store_true")
    sub.add_parser("find").add_argument("--repo", default=".")
    c = sub.add_parser("claim")
    c.add_argument("--repo", default=".")
    c.add_argument("--pane", help="register the PM for this pane instead of the current one")
    c.add_argument("--kind", help="which agent this PM is (default: read from its terminal)")
    st = sub.add_parser("start", help="start a PM session for a project, with any coding agent")
    st.add_argument("--repo", default=".")
    st.add_argument("--kind", help="agent program (default: config.json pm.kind, else claude)")
    st.add_argument("--model", help="default: config.json pm.model, else the program's own")
    st.add_argument("--name", help="the project's name, given to its new space (default: the folder's name)")
    st.add_argument("--space", choices=["new", "current"], default="new",
                    help="new (default): a space of its own, called --name. current: a tab in this command's "
                         "space, or a bare terminal outside one; that was what start did before --space existed")
    for verb, about in (("archive", "end a project's PM and pause its open tasks; the record stays"),
                        ("restore", "bring an archived project back and start its PM from the handover")):
        ar = sub.add_parser(verb, help=about)
        ar.add_argument("project", nargs="?", default=".", help="its folder, or its name (default: this folder)")
        if verb == "restore":
            ar.add_argument("--kind", help="agent program (default: the one the PM was)")
            ar.add_argument("--model", help="default: config.json pm.model, else the program's own")
    nt = sub.add_parser("notify")
    nt.add_argument("text")
    nt.add_argument("--repo", default=".")
    d = sub.add_parser("dispatch")
    d.add_argument("title")
    d.add_argument("--repo", default=".")
    d.add_argument("--branch", required=True)
    d.add_argument("--label", required=True)
    d.add_argument("--brief", required=True)
    d.add_argument("--name", required=True)
    d.add_argument("--base")
    d.add_argument("--prep")
    d.add_argument("--parent", help="the id of the task this one was split from")
    d.add_argument("--profile", help="light, standard, hard or deep, or one from config.json profiles "
                                     "(default: config.json worker.profile, else none); --kind/--model/--effort win")
    d.add_argument("--kind", help="worker program (default: the profile's, else config.json, else codex)")
    d.add_argument("--model", help="default: the profile's, else config.json, else the program's own")
    d.add_argument("--effort", help="default: the profile's, else config.json, else the program's own")
    d.add_argument("--advisor", help="advisor model for programs that take one, such as claude (default: the "
                                     "profile's); none: without")
    d.add_argument("--confirmed", action="store_true",
                   help="the user agreed to this profile (deep asks first: without this flag no worker starts)")
    w = sub.add_parser("wait", help="wait for a worker's report in the ledger (exit 2: timeout, 3: stopped unreported)")
    w.add_argument("id")
    w.add_argument("--timeout", type=int, default=3600, help="seconds (default 3600)")
    la = sub.add_parser("land", help="merge a task's branch in the main checkout once the project's checks pass "
                                     "(exit 1: a check failed, 2: refused, 4: conflicts, 5: left mid-merge)")
    la.add_argument("id")
    la.add_argument("--keep", action="store_true", help="keep the worker, worktree and branch (no automatic retire)")
    la.add_argument("--message", help="commit message (default: merge <branch>: <task title>)")
    la.add_argument("--timeout", type=int, default=600, help="seconds for all checks together (default 600)")
    rv = sub.add_parser("review", help="start a read-only reviewer on a task's branch, as thread <id>-review")
    rv.add_argument("id")
    rv.add_argument("--name", help="the reviewer's terminal name (default: <worker>-review)")
    rv.add_argument("--kind", help="reviewer program (default: config.json reviewer, else claude by the review table "
                                    "for the task's profile, else config.json worker, else codex)")
    rv.add_argument("--model", help="default: config.json reviewer, else the review table by the task's profile "
                                     "(config.json review; light/deep: opus, standard/hard: fable, sonnet with "
                                     "\"fable\": false), else config.json "
                                     "worker, else the program's own")
    rv.add_argument("--effort", help="default: config.json, else the program's own")
    es = sub.add_parser("escalate", help="run a task again on a stronger profile: a fresh worker in the same worktree "
                                         "and branch, given the review findings and the brief; the old worker ends")
    es.add_argument("id")
    es.add_argument("--profile", help="the profile to run on (default: one step up: light, standard, hard, deep; "
                                    "with \"fable\": false hard is the top)")
    es.add_argument("--why", help="why it is escalated, a few words for the ledger and the new worker")
    es.add_argument("--advisor", help="advisor model (default: the profile's); none: without")
    es.add_argument("--name", help="the new worker's terminal name (default: <worker>-<profile>)")
    es.add_argument("--confirmed", action="store_true",
                    help="the user agreed (a Fable worker, such as deep's, asks first: without this flag none starts)")
    ra = sub.add_parser("reattach", help="bring back the agent of a task whose terminal is gone: resume its session, "
                                         "else start one with the task's context")
    ra.add_argument("id")
    r = sub.add_parser("retire")
    r.add_argument("id")
    r.add_argument("--force", action="store_true")
    sub.add_parser("state", help="print dashboard state as JSON")
    ds = sub.add_parser("dash", help="serve the live dashboard (routing view of PMs, tasks and agents)")
    ds.add_argument("--port", type=int, default=7317)
    ds.add_argument("--host", default="127.0.0.1")
    ds.add_argument("--open", action="store_true", help="open it in the browser")
    dc = sub.add_parser("decide", help="record a decision the user made, for every later PM session")
    dc.add_argument("text")
    dc.add_argument("--quote", help="the user's own words")
    dc.add_argument("--repo", default=".")
    ho = sub.add_parser("handover", help="print what a fresh PM session needs to take over this project")
    ho.add_argument("--repo", default=".")
    ho.add_argument("--turns", type=int, default=6, help="how many past exchanges with the user to include")
    cv = sub.add_parser("conversation", help="print the end of the project's conversation log")
    cv.add_argument("--repo", default=".")
    cv.add_argument("--last", type=int, default=20, help="how many events (default 20)")
    cv.add_argument("--type", help="only these kinds, comma-separated: user,pm,agent,thread,decision")
    cv.add_argument("--width", type=int, default=300, help="clip each text to this many characters (0: whole text)")
    cxp = sub.add_parser("context", help="context tokens held by this session")
    cxp.add_argument("--transcript")
    ro = sub.add_parser("rotate", help="hand the project to a fresh PM session")
    ro.add_argument("--repo", default=".")
    ro.add_argument("--notes", help="what is in flight that the ledger and decisions do not say")
    ro.add_argument("--model", help="model for the new session (default: the CLI's default)")
    ro.add_argument("--transcript", help="the outgoing session's transcript (default: this session's)")
    sub.add_parser("hook-session-start")
    sub.add_parser("hook-turn")
    sub.add_parser("hook-mirror")  # earlier installs
    a = p.parse_args()
    globals()["cmd_" + a.cmd.replace("-", "_")](a)


if __name__ == "__main__":
    main()
