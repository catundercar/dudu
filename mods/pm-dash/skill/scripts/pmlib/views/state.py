"""JSON read model for `pm.py state` (`dash_state`), read directly by the mods (pm-dash, pm-project, pm-nav, pm-list).
Layer 4."""
import datetime
import json
from pathlib import Path
import re

from ..agents.sessions import sessions_reader
from ..context import Context
from ..helpers.records import helper_entries
from ..ledger.deps import evaluate_depends_on
from ..ledger.ledger import Ledger
from ..ledger.task import ACTIVE, CLOSED, needs_cleanup, task_number
from ..manager.launch import pm_compact_tokens
from ..osutil import stale_lock
from ..project.conversation import conversation_events, read_receipts
from ..project.project import ProjectRegistry
from ..project.readmodel import (
    LiveSnapshot,
    Projects,
    answered_tasks,
    asked_at,
    owner_of,
    project_lost,
    task_closed,
    task_offline,
)
from ..project.turn_state import TurnTracker
from ..store import local_tz_offset
from ..workers.lifecycle import term_status
from ..workers.sessions import ATTACHED, pm_session_info_for, task_session_info_for


TURN_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d) \[([^\]]+)\] (UserPromptSubmit|Stop): turn")


# How many ended threads off the board per PM get their worker's label in the state: a few more than the project
# view lists (pm-project's FINISHED_LIMIT), as it orders them by the conversation log, not by the ledger.
ENDED_ENGINES = 10


def engine_mark(task):
    """What a task's worker ran as, as the thread list labels it: the worker record's set fields
    ({profile, kind, model, effort, advisor}) and how many times it was escalated (`escalated`, left out at 0);
    {} when the ledger does not say."""
    worker = task.get("worker") if isinstance(task.get("worker"), dict) else {}
    mark = {k: worker[k] for k in ("profile", "kind", "model", "effort", "advisor") if worker.get(k)}
    ups = len(task["escalations"]) if isinstance(task.get("escalations"), list) else 0
    return mark | ({"escalated": ups} if mark and ups else {})


def _helper_term_for_task(term, name, live_rows, ended_rows):
    if not term:
        return ""
    row = None
    if isinstance(live_rows, dict) and term in live_rows:
        row = live_rows.get(term)
    elif isinstance(ended_rows, dict) and term in ended_rows:
        row = ended_rows.get(term)
    if not isinstance(row, dict):
        return ""
    labels = row.get("labels")
    if not isinstance(labels, dict):
        return ""
    lbl_helper = str(labels.get("helper") or "")
    if lbl_helper and name and lbl_helper != name:
        return ""
    return str(labels.get("helper.task") or "")


def state_helpers(record, hc_live=None, live_rows=None, ended_rows=None):
    """Helper entries of a task or PM as `pm.py state` exposes them: compact, read-only, enriched with live hc
    status when `hc_live`/`live_rows` were fetched. Keeps ledger order (oldest first, matching `helper ls`)."""
    out = []
    for h in helper_entries(record):
        name = str(h.get("name") or "")
        term = str(h.get("terminal") or "")
        status = str(h.get("status") or "")
        is_running = status == "running"
        offline = bool(is_running and term and hc_live is not None and term not in hc_live)
        live_state = ""
        if is_running and term:
            if live_rows is not None:
                row = live_rows.get(term)
                live_state = (term_status(row) or "live") if isinstance(row, dict) else "offline"
            elif offline:
                live_state = "offline"
        for_task = str(h.get("for_task") or "") or _helper_term_for_task(term, name, live_rows, ended_rows)
        item = {
            "name": name,
            "terminal": term,
            "pane": f"hc:{term}" if term else "",
            "parent": str(h.get("parent") or ""),
            "owner": str(h.get("owner") or ""),
            "status": status,
            "profile": str(h.get("profile") or ""),
            "kind": str(h.get("kind") or ""),
            "model": str(h.get("model") or ""),
            "effort": str(h.get("effort") or ""),
            "result": str(h.get("result") or ""),
            "summary": str(h.get("summary") or ""),
            "prompt": str(h.get("prompt") or ""),
            "started": str(h.get("started") or ""),
            "ended": str(h.get("ended") or ""),
            "offline": offline,
        }
        if live_state:
            item["live_state"] = live_state
        if h.get("provider"):
            item["provider"] = str(h["provider"])
        if h.get("fallback"):
            item["fallback"] = str(h["fallback"])
        if for_task:
            item["for_task"] = for_task
        out.append(item)
    return out


def dash_state(ctx=None):
    """Everything the dashboard draws: PMs, tasks, live agents and recent events."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    home = ctx.home
    projects_reg = ProjectRegistry(ctx)
    ledger = Ledger(ctx)
    listing = ctx.tui.agents()
    by_pane = {x["pane_id"]: x for x in listing}
    agent_map = {x["pane_id"]: {"name": x.get("name") or "", "kind": x.get("agent") or "",
                                "status": x.get("agent_status") or "",
                                "title": x.get("terminal_title_stripped") or ""} for x in listing}
    sessions = sessions_reader(cache=True, home=home, claude_projects=ctx.agents.claude_projects)
    pms = []
    pm_sources = []
    for path in sorted(home.registrations.glob("*.json")) if home.registrations.exists() else []:
        rec = json.loads(path.read_text())
        live = by_pane.get(rec.get("pane") or "", {})
        if rec.get("runtime") == "hc":
            live = projects_reg.hc_pm(rec.get("repo") or "") or {}
        alive = live.get("name") == rec.get("name")
        ctx_tokens = sessions.context_tokens(pm_session_info_for(ctx, rec)) if sessions else 0
        repo = rec.get("repo", "")
        pane_val = rec.get("pane", "")
        runtime = rec.get("runtime") or ("tui" if pane_val and not pane_val.startswith("hc:") else "")
        repo_ok = bool(repo and Path(repo).is_dir())
        pm_agent = rec.get("agent", "")
        receipts = read_receipts(home.project_for(repo).receipts)[-20:] if repo else []
        pm_entry = {"name": rec["name"], "project": rec.get("project", ""), "repo": repo,
                    "pane": pane_val, "runtime": runtime, "repo_ok": repo_ok,
                    "status": live.get("agent_status") if alive else "offline",
                    "title": live.get("terminal_title_stripped", "") if alive else "",
                    "agent": pm_agent, "archived": rec.get("archived"),
                    "compact_tokens": pm_compact_tokens(pm_agent, ctx=ctx),
                    # The project's conversation log; read-only here, so its folder is not created.
                    "conversation": str(home.project_for(repo).conversation)
                    if repo else "",
                    # Sessions under either folder work in this project (the project view lists them).
                    "worktrees": str(ctx.git.worktree_home(repo)) if repo else ""} | (
                        {"context_tokens": ctx_tokens} if ctx_tokens > 0 else {}) | (
                        {"receipts": receipts} if receipts else {})
        pms.append(pm_entry)
        pm_sources.append((rec, pm_entry, alive, repo_ok))

    def owner_pm(t):
        hit = owner_of(t, pms)
        return hit["name"] if hit else ""

    # The blocked tasks the user has answered, from each project's conversation log (read only when one of
    # its tasks is blocked): the project view says Answered, and they are not counted as waiting.
    every = ledger.raw_tasks()
    blocked, asked = {}, {}
    for t in every:
        if t["status"] == "blocked":
            blocked.setdefault(owner_pm(t), {})[t["id"]] = t.get("title") or ""
            asked[t["id"]] = asked_at(t)
    answered = set()
    for p in pms:
        if blocked.get(p["name"]) and p["conversation"]:
            answered |= answered_tasks(conversation_events(p["conversation"]), blocked[p["name"]], asked) & set(blocked[p["name"]])

    day_ago = (ctx.clock.datetime_now() - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    tasks, events = [], []
    # Whose terminal is gone or did not come back: one `hc ls --all` look when an open hc task, non-archived hc PM,
    # or running helper exists.
    needs_hc = (
        any(not rec.get("archived") and rec.get("runtime") == "hc" for rec, _, _, _ in pm_sources)
        or any(t["status"] in ATTACHED and (t.get("pane") or "").startswith("hc:") for t in every)
        or any(h.get("status") == "running" and h.get("terminal") for t in every for h in helper_entries(t))
        or any(h.get("status") == "running" and h.get("terminal") for rec, _, _, _ in pm_sources for h in helper_entries(rec))
    )
    live_rows = None
    if needs_hc:
        raw_live, raw_ended = ctx.hc.all_rows()
        live_rows = None if raw_live is None else {k: v.raw for k, v in raw_live.items()}
        hc_ended = None if raw_ended is None else {k: v.raw for k, v in raw_ended.items()}
        hc_live = None if live_rows is None else set(live_rows)
    else:
        hc_live, hc_ended = None, None
    for rec, p, alive, _ in pm_sources:
        pm_helpers = state_helpers(rec, hc_live, live_rows, hc_ended)
        if pm_helpers:
            p["helpers"] = pm_helpers
        repo = rec.get("repo") or ""
        if repo:
            term_addr = str(rec.get("terminal") or (p["pane"][3:] if str(p.get("pane") or "").startswith("hc:") else ""))
            term_row = (live_rows or {}).get(term_addr) if term_addr and isinstance(live_rows, dict) else None
            p["turn"] = TurnTracker(ctx, repo).live_snapshot(
                rec,
                {"agent_status": p.get("status") if alive else "offline", "name": p.get("name")},
                term_info=term_row,
            )
    tui_panes = set(by_pane) if listing else None
    by_id_all = {t["id"]: t for t in every if isinstance(t, dict) and t.get("id")}
    left = []
    for t in every:
        # Closed work stays on the board for a day, until `retire` cleans it up.
        if not (t["status"] in ACTIVE or (t.get("updated", "") >= day_ago and not t.get("retired"))):
            left.append(t)
            continue
        pm = owner_pm(t)
        pm_pane = next((p["pane"] for p in pms if p["name"] == pm), "")
        log = t.get("log") or []
        ctx_tokens = sessions.context_tokens(task_session_info_for(ctx, t, sessions, every)) if sessions else 0
        is_offline = task_offline(t, hc_live, tui_panes)
        closed_rec = task_closed(t, hc_ended) if is_offline else None
        task_helpers = state_helpers(t, hc_live, live_rows, hc_ended)
        dep_info = evaluate_depends_on(t, by_id_all) if (t["status"] == "proposed" or t.get("depends_on")) else None
        dep_fields = {}
        if dep_info is not None:
            if t["status"] == "proposed":
                dep_fields["ready"] = dep_info["ready"]
            if dep_info["depends_on"]:
                dep_fields["depends_on"] = dep_info["depends_on"]
                dep_fields["deps"] = dep_info["items"]
                dep_fields["waiting_on"] = [d["id"] for d in dep_info["waiting"] + dep_info["broken"]]
            if dep_info["broken"]:
                dep_fields["deps_broken"] = True
        tasks.append({k: t.get(k) or "" for k in ("id", "title", "project", "status", "owner", "pane", "agent",
                                                   "branch", "updated", "parent")}
                     | ({"number": task_number(t)} if task_number(t) else {})
                     | ({"brief": t["brief"]} if t.get("brief") else {})
                     | ({"paused_from": t["paused_from"]} if t.get("paused_from") else {})
                     | ({"answered": True} if t["id"] in answered else {})
                     # when the ledger last asked the user (asked_at): pm-project's answers to it come after
                     | ({"asked_at": asked[t["id"]]} if asked.get(t["id"]) else {})
                     # a review thread (`pm.py review`): the task it reviews; the views fold it into that task
                     | ({"review_of": t["review_of"]} if t.get("review_of") else {})
                     # how its worker got there and how many reviews it has been through: the thread list's tip
                     | ({"escalations": t["escalations"]} if isinstance(t.get("escalations"), list) and t["escalations"] else {})
                     | ({"rounds": t["rounds"]} if isinstance(t.get("rounds"), int) else {})
                     | ({"helpers": task_helpers} if task_helpers else {})
                     | ({"context_tokens": ctx_tokens} if ctx_tokens > 0 else {})
                     | ({"closed": closed_rec} if closed_rec else {})
                     | ({"plan": t["plan"]} if isinstance(t.get("plan"), list) and t["plan"] else {})
                     | ({"subplan": t["subplan"]} if isinstance(t.get("subplan"), list) and t["subplan"] else {})
                     | ({"no_review": True} if t.get("no_review") else {})
                     | ({"landed": t["landed"]} if isinstance(t.get("landed"), dict) and t["landed"] else {})
                     | ({"commit": t["commit"]} if t.get("commit") else {})
                     | dep_fields
                     | {"pm": pm, "latest": (log[-1].get("text", "") if log else ""), "cleanup": needs_cleanup(t),
                        "offline": is_offline,
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
             | ({"number": task_number(t)} if task_number(t) else {})
             | {"pm": owner_pm(t), "retired": bool(t.get("retired"))} for t in left if t.get("parent") in shown]
    # What the workers of the threads that ended last and are off the board ran as: the project view's ended rows
    # label them as they do a task on the board (its `engine`). Only the newest ENDED_ENGINES of each PM, and only
    # the label's fields: the state is read every few seconds.
    ended = {}
    for t in sorted(left, key=lambda t: t.get("updated") or "", reverse=True):
        if t["status"] not in CLOSED or t["status"] == "abandoned" or t.get("review_of"):
            continue
        mark = engine_mark(t)
        pm = owner_pm(t)
        if mark and pm and len(ended.setdefault(pm, {})) < ENDED_ENGINES:
            ended[pm][t["id"]] = mark
    # Chat turns with a PM, as recorded by the turn hook.
    if home.turn_log.exists():
        pane_pm = {p["pane"]: p["name"] for p in pms}
        for line in home.turn_log.read_text(errors="replace").splitlines()[-400:]:
            m = TURN_LINE.match(line)
            if m and m.group(2) in pane_pm:
                events.append({"key": "m:" + line, "at": m.group(1), "by": m.group(2), "task": "",
                               "pm": pane_pm[m.group(2)], "status": "", "text": "",
                               "kind": "prompt" if m.group(3) == "UserPromptSubmit" else "reply"})
    # The numbers on a project's card and the ledger overview, computed via Projects (pm_project.py):
    # waiting is claimed blocked (not answered), working is in progress with terminal not offline,
    # and unclaimed_blocked tracks blocked tasks with no registered PM separately.
    today = ctx.clock.now()[:10]
    live_snap = LiveSnapshot(
        hc_live=frozenset(hc_live) if hc_live is not None else None,
        tui_panes=frozenset(tui_panes) if tui_panes is not None else None,
    )
    counted = Projects(ctx.store, sessions=sessions, live=live_snap).counts(
        today=today, pms=pms, tasks=every, answered=answered, shown=shown
    )
    for p in pms:
        p["counts"] = counted["by_pm"][p["name"]]
    if hc_live is not None and pm_sources:
        reattach_dir = home.reattach
        reattaching = {
            lp.stem for lp in (reattach_dir.glob("*.lock") if reattach_dir.is_dir() else ())
            if not stale_lock(lp)
        }
        for rec, p, alive, repo_ok in pm_sources:
            lost = project_lost(
                rec,
                every,
                pms=pms,
                pm_alive=alive,
                hc_live=hc_live,
                tui_panes=tui_panes,
                ended=hc_ended,
                repo_exists=repo_ok,
                reattaching=reattaching,
            )
            if lost:
                p["lost"] = lost
    if sessions:
        sessions.flush()
    events = sorted(events, key=lambda e: e["at"])[-120:]
    task_numbers = {t["id"]: task_number(t) for t in every if task_number(t)}
    default_compact = pm_compact_tokens("claude", ctx=ctx)
    return {"now": ctx.clock.now_sec(),
            "server_now_ms": int(ctx.clock.time() * 1000),
            "server_tz": local_tz_offset(ctx.clock.datetime_now()),
            "pms": pms, "tasks": tasks,
            "ready_tasks": [t["id"] for t in tasks if t["status"] == "proposed" and t.get("ready")],
            "counts": counted["totals"],
            "agents": agent_map, "events": events, "lang": tr("en", "zh"), "home": str(home.root), "retired_parts": parts,
            "task_numbers": task_numbers,
            "ended_engines": {k: v for of_pm in ended.values() for k, v in of_pm.items()},
            "compact_tokens": default_compact,
            "rotate_tokens": default_compact}


def cmd_state(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    ctx.out.line(json.dumps(dash_state(ctx=ctx), ensure_ascii=False))


def register_state_view(sub):
    sub.add_parser("state", help="print dashboard state as JSON")
