"""Project read model: unified counts, review folding, paginated conversation windows, and thread logs.

Built on top of Store (pm_store.py) without importing `pm`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Mapping

from ..errors import NotFound
from ..home import project_slug
from ..store import REPO_FILES_MAX, Store, valid_slug, valid_task_id, valid_task_number

LOG_LIMIT_DEFAULT = 50
LOG_LIMIT_MAX = 2000
TASKS_LIMIT_DEFAULT = 30
TASKS_LIMIT_MAX = 100
TASKS_STATUSES = ("finished", "open", "all")
_WORK_STATUSES = ("in_progress", "review")
COMMITS_MAX = 200
COMMITS_LIMIT_MAX = 500
DIFF_LINES_DEFAULT = 400
DIFF_LINES_MAX = 2000
DIFF_READ_MAX_BYTES = 2 * 1024 * 1024
DIFF_LINE_MAX_CHARS = 2000
STATUS_MAX_BYTES = 1 * 1024 * 1024
GIT_TIMEOUT = 15

ACTIVE_STATUSES = ("proposed", "in_progress", "review", "blocked", "paused")
CLOSED_STATUSES = ("merged", "released", "done", "abandoned")
ATTACHED_STATUSES = ("in_progress", "review", "blocked")

IMAGE_MARK = re.compile(r"\[Image #\d+\][ \t]*")  # as pm-project's model.js IMAGE_MARK
_REF_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/+-]*$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_FULL_HASH_RE = re.compile(r"^[0-9a-f]{40}$")
_SHORTSTAT_RE = re.compile(r"(\d+) (files? changed|insertions?\(\+\)|deletions?\(-\))")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_STRIP_GIT_ENV = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE", "GIT_PREFIX", "GIT_EXTERNAL_DIFF",
})


class NotFoundError(NotFound):
    """The requested project or task does not exist in the ledger."""


@dataclass(frozen=True)
class LiveSnapshot:
    """Point-in-time terminal liveness collected by pm.py (hc and Herdr TUI).

    `hc_live` / `tui_panes` are None when that runtime could not be queried (nothing in that
    runtime is judged offline when unknown).
    """

    hc_live: frozenset[str] | None = None
    tui_panes: frozenset[str] | None = None
    agents_by_pane: dict[str, dict] = field(default_factory=dict)
    hc_pms: dict[str, dict] = field(default_factory=dict)


def _extract_live(live) -> tuple[frozenset[str] | set[str] | None, frozenset[str] | set[str] | None]:
    if live is None:
        return None, None
    if isinstance(live, LiveSnapshot):
        return live.hc_live, live.tui_panes
    if isinstance(live, dict):
        return live.get("hc_live"), live.get("tui_panes")
    return getattr(live, "hc_live", None), getattr(live, "tui_panes", None)


def owner_of(task: dict, pms: list[dict]) -> dict | None:
    """The PM a task belongs to, as the board counts it: the PM of its repository, else of a repository
    that holds it (a project inside another, such as issues/site-a), else of a project of that name.
    None: no PM (unclaimed)."""
    raw_repo = task.get("repo") or "/"
    repo = str(Path(raw_repo).resolve())
    tproj = str(task.get("project") or "").lower()
    exact, nested, named = [], [], []
    for p in pms:
        prepo_raw = p.get("repo") or ""
        if prepo_raw:
            prepo = str(Path(prepo_raw).resolve())
            if prepo == repo:
                exact.append(p)
                continue
            if repo.startswith(prepo + "/") or repo.startswith(prepo + os.sep):
                nested.append(p)
                continue
        pproj = str(p.get("project") or "").lower()
        if pproj and pproj == tproj:
            named.append(p)
    hit = exact or nested or named
    return hit[0] if hit else None


def task_offline(task: dict, hc_live, tui_panes) -> bool:
    """The task is open and the terminal it names is gone: hc lists no live terminal at that address,
    or, in the herdr terminal UI, no agent runs in that pane. hc_live / tui_panes: what is live,
    None when it is not known (then nothing is offline)."""
    pane = task.get("pane") or ""
    if task.get("status") not in ATTACHED_STATUSES or not pane or "/" in pane:  # "/": a terminal on another machine
        return False
    if pane.startswith("hc:"):
        return hc_live is not None and pane[3:] not in hc_live
    return tui_panes is not None and pane not in tui_panes


# How herdr-core says a terminal's program was ended by someone: the user closing its tab or pane in Herdr (which
# also ends the sub-agents of a closed PM), or an `hc kill`. An agent ended so is not one that "did not come back".
KILLED_REASONS = ("killed",)

# Reasons in herdr-core (or a vanished terminal record, "gone") that mean a restart or host/server shutdown took the
# terminal away rather than the program exiting on its own. Mirrors app:service/agents.go restartHows.
RESTART_REASONS = ("gone", "server_stop", "host_shutdown", "stopped_by_restart", "holder_lost")


def _ms_local(ms) -> str:
    """herdr-core's milliseconds as the ledger writes a time ("YYYY-MM-DD HH:MM"); "" when it gives none."""
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M") if ms else ""
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def task_closed(task: dict, ended=None) -> dict | None:
    """How the terminal the open task names was ended on purpose, or None.

    `closed` on the task, written by pm.py when it ended that terminal itself (end_terminal: retire, idle-workers
    --close, close-worker, a review closed), counts while it names the task's pane now (a reattach gives the task a
    new pane, so an older record says nothing more). Else herdr-core's own word for that terminal, among `ended`
    ({address: `hc ls --all` row} of the finished ones): `killed` is the user closing it (its tab, its pane, its
    PM's tab). {pane, at, why}: why is the pm.py command that ended it, or "killed"."""
    pane = task.get("pane") or ""
    if not pane or "/" in pane:
        return None
    rec = task.get("closed")
    if isinstance(rec, dict) and rec.get("pane") == pane:
        return {"pane": pane, "at": str(rec.get("at") or ""), "why": str(rec.get("why") or "")}
    row = (ended or {}).get(pane[3:]) if pane.startswith("hc:") else None
    if isinstance(row, dict) and row.get("reason") in KILLED_REASONS:
        return {"pane": pane, "at": _ms_local(row.get("finished_ms")), "why": "killed"}
    return None


def task_lost(task: dict, hc_live, tui_panes, ended=None) -> bool:
    """Open work whose terminal is gone and was not ended on purpose: what "bring them all back" starts again."""
    return task_offline(task, hc_live, tui_panes) and task_closed(task, ended) is None


def _ended_how(ended, addr: str) -> tuple[str, str]:
    row = (ended or {}).get(addr)
    if not isinstance(row, dict):
        return "gone", ""
    return str(row.get("reason") or "exited"), _ms_local(row.get("finished_ms"))


def project_lost(
    reg: dict,
    tasks: list[dict],
    *,
    pms: list[dict] | None = None,
    pm_alive: bool = False,
    hc_live=None,
    tui_panes=None,
    ended=None,
    repo_exists: bool | None = None,
    reattaching: set[str] | frozenset[str] = frozenset(),
) -> dict | None:
    """Agents of one non-archived project whose local herdr-core terminals disappeared without being closed on purpose.

    Returns `{"pm": {...}|None, "threads": [...], "restart": bool, "key": str}` or `None` when nothing is lost
    (or when `hc_live is None`, i.e. herdr-core could not be queried).
    """
    if not isinstance(reg, dict) or reg.get("archived") or hc_live is None:
        return None
    pm_name = reg.get("name") or ""
    repo = reg.get("repo") or ""
    has_repo = bool(repo and Path(repo).is_dir()) if repo_exists is None else bool(repo_exists)
    pm_pane = reg.get("pane") or ""
    prev = reg.get("previous")
    prev_pm_pane = (prev.get("pane") or "") if isinstance(prev, dict) else ""

    lost_pm = None
    if (reg.get("runtime") == "hc" and pm_pane.startswith("hc:") and "/" not in pm_pane
            and not pm_alive and has_repo):
        pm_addr = pm_pane[3:]
        if pm_addr and pm_addr not in hc_live:
            how, at = _ended_how(ended, pm_addr)
            pm_closed = reg.get("closed")
            closed_by_pm = isinstance(pm_closed, dict) and pm_closed.get("pane") == pm_pane
            if how not in KILLED_REASONS and not closed_by_pm:
                lost_pm = {"address": pm_addr, "how": how, **({"at": at} if at else {})}

    all_pms = pms if pms is not None else [reg]
    lost_threads: list[dict] = []
    for t in tasks or []:
        if not isinstance(t, Mapping):
            continue
        tid = t.get("id") or ""
        pane = t.get("pane") or ""
        if not tid or tid in reattaching or t.get("held"):
            continue
        # Only local herdr-core worker terminals can be brought back in the desktop app, and never a task
        # that was merely parked on the PM's own terminal (`cmd_new` without `--pane ""`).
        if not pane.startswith("hc:") or "/" in pane or pane in (pm_pane, prev_pm_pane):
            continue
        owner = owner_of(t, all_pms)
        if not owner or (owner.get("name") or "") != pm_name:
            continue
        if not task_lost(t, hc_live, tui_panes, ended):
            continue
        addr = pane[3:]
        ended_row = (ended or {}).get(addr)
        labels = (ended_row.get("labels") or {}) if isinstance(ended_row, dict) else {}
        if labels.get("pm"):
            continue
        how, at = _ended_how(ended, addr)
        num = valid_task_number(t.get("number"))
        lost_threads.append({
            "id": tid,
            **({"number": num} if num is not None else {}),
            "title": t.get("title") or tid,
            "address": addr,
            "how": how,
            **({"at": at} if at else {}),
        })

    lost_threads.sort(key=lambda x: x["id"])
    if not lost_pm and not lost_threads:
        return None
    restart = bool(
        (lost_pm and lost_pm["how"] in RESTART_REASONS)
        or any(x["how"] in RESTART_REASONS for x in lost_threads)
    )
    parts = ([f"pm@{lost_pm['address']}"] if lost_pm else []) + [f"{x['id']}@{x['address']}" for x in lost_threads]
    return {"pm": lost_pm, "threads": lost_threads, "restart": restart, "key": ";".join(parts)}


def asks_again(event: dict) -> bool:
    """A ledger entry that asks the user a question: `update --status blocked` (its text says status=blocked,
    also while the task already was blocked) or one that offers quick answers (--option).
    Entering blocked from another status asks too. The same rule as pm-project's asksAgain."""
    return bool(re.search(r"\bstatus=blocked\b", str(event.get("text") or ""))) or any(
        str(o or "").strip() for o in (event.get("options") if isinstance(event.get("options"), list) else [])
    )


def asked_at(task: dict) -> str:
    """When the ledger last asked the user about `task` ("YYYY-MM-DD HH:MM"): its latest entry that made it
    blocked (status=blocked), else its first entry (a task registered blocked); "" without a log."""
    log = [e for e in task.get("log") or [] if isinstance(e, dict)]
    asking = [e for e in log if re.search(r"\bstatus\s*=\s*blocked\b", str(e.get("text") or ""))]
    return str((asking or log or [{}])[-1 if asking else 0].get("at") or "")


def answered_tasks(events, titles=None, asked=None) -> set[str]:
    """The blocked tasks the user has answered: after the task last asked (entered blocked, or see asks_again),
    the user said something that starts with its 【title】, as a quick answer on the question card does
    (`【<title>】<option>`). Such a task waits for the PM, not for the user, until the PM moves it on; asking
    again is a new question, unanswered. The same rule as pm-project's answeredTasks."""
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
            hit = next((t for t in reversed(opened) if status.get(t) == "blocked"
                        and not (t in unlogged and at(e) < when.get(t, ""))
                        and said.startswith(squash(f"【{named.get(t, t)}】"))), None)
            if hit:
                answered.add(hit)
    return {t for t in answered if status.get(t) == "blocked"}


def review_map(tasks: list[dict], shown: set[str] | frozenset[str] | None = None) -> dict[str, dict]:
    """Map `reviewed_task_id -> review_task` for reviews that fold into the task they review.

    A review thread (`review_of`) folds into its task while that task is eligible (in `shown`, or in
    `tasks` when `shown` is None), except that an open review of a closed task stays on its own.
    When multiple review tasks exist for one target, prefer an open review over a closed one, and the
    newer task (earlier in `tasks`, which is newest-first) over an older one.
    """
    by_id = {t["id"]: t for t in tasks if isinstance(t, Mapping) and t.get("id")}
    eligible = set(by_id) if shown is None else (set(shown) & set(by_id))
    reviews: dict[str, dict] = {}
    for t in reversed(tasks):
        if not isinstance(t, Mapping):
            continue
        tid = t.get("id")
        target = t.get("review_of")
        if not tid or not target or target == tid or target not in eligible:
            continue
        t_closed = t.get("status") in CLOSED_STATUSES
        target_closed = by_id[target].get("status") in CLOSED_STATUSES
        if not (t_closed or not target_closed):
            continue
        existing = reviews.get(target)
        if existing is not None and existing.get("status") not in CLOSED_STATUSES and t_closed:
            continue
        reviews[target] = t
    return reviews


def folded_status(
    task: dict,
    reviews: dict[str, dict],
    answered: set[str] | frozenset[str] = frozenset(),
) -> tuple[str, bool]:
    """Effective `(status, is_answered)` of `task` after folding in its open review thread, if any.

    Matches pm.py and the mods' `foldReviews`:
    - No folded review, a closed/paused review, or a task that is itself blocked/paused: task's own status.
    - Open review that is blocked: ("blocked", review_id in answered).
    - Any other open review: ("review", False).
    """
    tid = task.get("id") or ""
    t_status = task.get("status") or ""
    r = reviews.get(tid)
    if not r or r.get("status") in CLOSED_STATUSES or r.get("status") == "paused" or t_status in ("blocked", "paused"):
        return t_status, tid in answered
    if r.get("status") == "blocked":
        return "blocked", (r.get("id") or "") in answered
    return "review", False


def _empty_pm_counts() -> dict[str, int]:
    return {"working": 0, "waiting": 0, "review": 0, "proposed": 0, "merged_today": 0}


def compute_counts(
    pms: list[dict],
    tasks: list[dict],
    *,
    answered: set[str] | frozenset[str] = frozenset(),
    hc_live=None,
    tui_panes=None,
    today: str = "",
    shown: set[str] | frozenset[str] | None = None,
) -> dict:
    """Compute canonical per-PM counts and overview totals using pm.py's unified rules.

    - waiting ("等你"): claimed by a PM, folded status == "blocked", not answered (review does not count).
    - unclaimed_blocked ("没人认领的阻塞"): no registered PM owns it, folded status == "blocked", not answered.
    - working ("在干活"): claimed by a PM, folded status == "in_progress", terminal not offline.
    - Overview `totals` sums only non-archived PMs, plus `unclaimed_blocked`.
    """
    by_pm: dict[str, dict[str, int]] = {}
    for p in pms:
        name = p.get("name")
        if name:
            by_pm[name] = _empty_pm_counts()

    reviews = review_map(tasks, shown=shown)
    unclaimed_blocked = 0

    for t in tasks:
        if not isinstance(t, Mapping):
            continue
        if reviews.get(t.get("review_of")) is t:
            continue
        owner = owner_of(t, pms)
        pm_name = owner["name"] if owner else ""
        status, is_answered = folded_status(t, reviews, answered)
        counts = by_pm.get(pm_name)
        if counts is not None:
            working = "" if task_offline(t, hc_live, tui_panes) else "working"
            key = {
                "in_progress": working,
                "blocked": "" if is_answered else "waiting",
                "review": "review",
                "proposed": "proposed",
            }.get(status) or (
                "merged_today"
                if t.get("status") == "merged" and bool(today) and str(t.get("updated") or "")[:10] == today
                else ""
            )
            if key:
                counts[key] += 1
        elif status == "blocked" and not is_answered:
            unclaimed_blocked += 1

    active_pms = [p for p in pms if p.get("name") in by_pm and not p.get("archived")]
    totals = {
        "projects": len(active_pms),
        "working": sum(by_pm[p["name"]]["working"] for p in active_pms),
        "waiting": sum(by_pm[p["name"]]["waiting"] for p in active_pms),
        "review": sum(by_pm[p["name"]]["review"] for p in active_pms),
        "proposed": sum(by_pm[p["name"]]["proposed"] for p in active_pms),
        "merged_today": sum(by_pm[p["name"]]["merged_today"] for p in active_pms),
        "unclaimed_blocked": unclaimed_blocked,
    }
    return {"by_pm": by_pm, "totals": totals}


def question_only_tasks(events) -> set[str]:
    """Tasks in conversation events that are only a question (first status is blocked and never entered work)."""
    first: dict[str, str] = {}
    worked: set[str] = set()
    for e in events or ():
        if not isinstance(e, Mapping) or e.get("type") != "thread":
            continue
        tid = e.get("task")
        if not tid:
            continue
        status = str(e.get("status") or "")
        if tid not in first:
            first[tid] = status
        if status in _WORK_STATUSES:
            worked.add(tid)
    return {tid for tid, st in first.items() if st == "blocked" and tid not in worked}


def _task_log_question_only(task: Mapping) -> bool:
    """Fallback question-only check from a closed task's own ledger log when conversation events are absent."""
    if task.get("status") not in CLOSED_STATUSES:
        return False
    if task.get("branch") or task.get("commit") or task.get("worker") or task.get("dispatched"):
        return False
    raw_log = task.get("log")
    if not isinstance(raw_log, list) or not raw_log:
        return False
    first_text = str((raw_log[0] if isinstance(raw_log[0], Mapping) else {}).get("text") or "")
    if not re.search(r"(?:\bregistered\s*\(\s*blocked\s*\)|\bstatus\s*=\s*blocked\b)", first_text):
        return False
    for entry in raw_log:
        text = str((entry if isinstance(entry, Mapping) else {}).get("text") or "")
        if re.search(r"(?:\bstatus\s*=\s*(?:in_progress|review)\b|\bregistered\s*\(\s*(?:in_progress|review)\s*\))", text):
            return False
    return True


def _task_matches_query(task: Mapping, query: str) -> bool:
    """Case-insensitive match against #number / number, task id, title, and branch."""
    q = str(query or "").strip().lower()
    if not q:
        return True
    tid = str(task.get("id") or "").lower()
    title = str(task.get("title") or "").lower()
    branch = str(task.get("branch") or "").lower()
    num = valid_task_number(task.get("number"))
    num_str = str(num) if num is not None else ""
    hash_num = f"#{num_str}" if num_str else ""
    haystack = f"{hash_num} {tid} {title} {branch}"
    tokens = q.split()
    for tok in tokens:
        if tok.startswith("#") and tok[1:].isdigit():
            want = int(tok[1:])
            if num == want or tok in title or tok in tid:
                continue
            return False
        if tok.isdigit():
            want = int(tok)
            if num == want or tok in tid or tok in title or tok in branch:
                continue
            return False
        if tok not in haystack:
            return False
    return True


def _task_summary(task: Mapping) -> dict:
    """Lightweight task row for paginated history and search in the Threads panel."""
    num = valid_task_number(task.get("number"))
    tid = str(task.get("id") or "")
    item: dict = {
        "id": tid,
        "title": str(task.get("title") or tid),
        "status": str(task.get("status") or ""),
        "branch": str(task.get("branch") or ""),
        "updated": str(task.get("updated") or ""),
        "parent": str(task.get("parent") or ""),
    }
    if num is not None:
        item["number"] = num
    if task.get("commit"):
        item["commit"] = str(task["commit"])
    if isinstance(task.get("landed"), dict) and task["landed"]:
        item["landed"] = task["landed"]
    if task.get("retired"):
        item["retired"] = True
    return item


def _pm_slug(pm: dict) -> str:
    repo = pm.get("repo") or ""
    if repo:
        return project_slug(repo)
    name = str(pm.get("name") or "")
    stripped = name[3:] if name.startswith("pm-") else name
    return stripped if valid_slug(stripped) else ""


class Projects:
    def __init__(self, store: Store, sessions=None, live=None):
        self.store = store
        self.sessions = sessions
        self.live = live

    def _project_known(self, slug: str) -> bool:
        has_project = getattr(self.store, "has_project", None)
        if callable(has_project) and has_project(slug):
            return True
        if self.store.registration(slug) is not None:
            return True
        return bool(self.store.tasks(slug))

    def _answered_for(self, pms: list[dict], tasks: list[dict]) -> set[str]:
        blocked: dict[str, dict[str, str]] = {}
        asked: dict[str, str] = {}
        for t in tasks:
            if not isinstance(t, Mapping) or t.get("status") != "blocked" or not t.get("id"):
                continue
            owner = owner_of(t, pms)
            pm_name = owner["name"] if owner else ""
            blocked.setdefault(pm_name, {})[t["id"]] = t.get("title") or ""
            asked[t["id"]] = asked_at(t)
        answered: set[str] = set()
        for p in pms:
            pm_name = p.get("name") or ""
            if not blocked.get(pm_name):
                continue
            slug = _pm_slug(p)
            if not slug:
                continue
            events = self.store.all_events(slug)
            answered |= answered_tasks(events, blocked[pm_name], asked) & set(blocked[pm_name])
        return answered

    def counts(
        self,
        *,
        live=None,
        today: str | None = None,
        pms: list[dict] | None = None,
        tasks: list[dict] | None = None,
        answered: set[str] | frozenset[str] | None = None,
        shown: set[str] | frozenset[str] | None = None,
    ) -> dict:
        """Return `{"by_pm": {pm_name: {...}}, "totals": {...}}` using the unified count rules."""
        regs = self.store.registrations() if pms is None else pms
        every = self.store.tasks() if tasks is None else tasks
        ans = self._answered_for(regs, every) if answered is None else answered
        day = datetime.datetime.now().strftime("%Y-%m-%d") if today is None else today
        hc_live, tui_panes = _extract_live(self.live if live is None else live)
        return compute_counts(
            regs,
            every,
            answered=ans,
            hc_live=hc_live,
            tui_panes=tui_panes,
            today=day,
            shown=shown,
        )

    def list(self, *, live=None, today: str | None = None) -> list[dict]:
        """List projects with Project and Coordinator fields separated and unified counts attached."""
        regs = self.store.registrations()
        every = self.store.tasks()
        snap = self.live if live is None else live
        counted = self.counts(live=snap, today=today, pms=regs, tasks=every)
        by_pane = snap.agents_by_pane if isinstance(snap, LiveSnapshot) else {}
        hc_pms = snap.hc_pms if isinstance(snap, LiveSnapshot) else {}
        out: list[dict] = []
        for rec in regs:
            name = rec.get("name") or ""
            repo = rec.get("repo") or ""
            pane = rec.get("pane") or ""
            runtime = rec.get("runtime") or ""
            live_row = (hc_pms.get(repo) or hc_pms.get(name) or {}) if runtime == "hc" else (by_pane.get(pane) or {})
            alive = bool(name) and live_row.get("name") == name
            out.append({
                "slug": _pm_slug(rec),
                "name": name,
                "project": rec.get("project") or "",
                "repo": repo,
                "archived": rec.get("archived"),
                "coordinator": {
                    "pane": pane,
                    "agent": rec.get("agent") or "",
                    "runtime": runtime,
                    "status": (live_row.get("agent_status") or "") if alive else "offline",
                    "session": rec.get("session") or "",
                    "rotations": int(rec.get("rotations") or 0),
                },
                "counts": counted["by_pm"].get(name, _empty_pm_counts()),
            })
        return out

    def events(self, slug: str, before: int | None = None, limit: int = 200, *, after: int | None = None) -> dict:
        if not valid_slug(slug) or not self._project_known(slug):
            raise NotFoundError(f"no project {slug}")
        out = self.store.events(slug, before=before, after=after, limit=limit)
        if before is None:
            receipts = self.store.receipts(slug)
            if receipts:
                out["receipts"] = receipts
        return out

    def tasks(
        self,
        slug: str,
        *,
        status: str = "finished",
        query: str = "",
        offset: int = 0,
        limit: int = TASKS_LIMIT_DEFAULT,
    ) -> dict:
        if not valid_slug(slug) or not self._project_known(slug):
            raise NotFoundError(f"no project {slug}")
        if status not in TASKS_STATUSES:
            raise ValueError(f"status must be one of {', '.join(TASKS_STATUSES)}")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > TASKS_LIMIT_MAX:
            raise ValueError(f"limit must be between 1 and {TASKS_LIMIT_MAX}")

        raw_tasks = self.store.tasks(slug)
        q_only = question_only_tasks(self.store.all_events(slug))
        if status == "finished":
            allowed = set(CLOSED_STATUSES) - {"abandoned"}
        elif status == "open":
            allowed = set(ACTIVE_STATUSES)
        else:
            allowed = set(ACTIVE_STATUSES) | (set(CLOSED_STATUSES) - {"abandoned"})

        matched: list[dict] = []
        for t in raw_tasks:
            if not isinstance(t, Mapping):
                continue
            tid = str(t.get("id") or "")
            if not tid:
                continue
            st = str(t.get("status") or "")
            if st == "abandoned" or st not in allowed:
                continue
            if t.get("review_of"):
                continue
            if tid in q_only or _task_log_question_only(t):
                continue
            if query and not _task_matches_query(t, query):
                continue
            matched.append(dict(t))

        matched.sort(key=lambda t: (str(t.get("updated") or ""), str(t.get("id") or "")), reverse=True)
        total = len(matched)
        page = matched[offset : offset + limit]
        return {
            "tasks": [_task_summary(t) for t in page],
            "total": total,
            "offset": offset,
            "limit": limit,
            "more": (offset + len(page)) < total,
        }

    def thread_log(self, task_id: str, before: int | None = None, limit: int = LOG_LIMIT_DEFAULT) -> dict:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 or limit > LOG_LIMIT_MAX:
            raise ValueError(f"limit must be between 1 and {LOG_LIMIT_MAX}")
        if before is not None and (not isinstance(before, int) or isinstance(before, bool) or before < 0):
            raise ValueError("before must be a non-negative entry index")
        task = self.store.task(task_id)
        if task is None:
            raise NotFoundError(f"no task {task_id}")
        raw_log = task.get("log")
        items = raw_log if isinstance(raw_log, list) else []
        total = len(items)
        end = total if before is None else min(before, total)
        start = max(0, end - limit)
        entries = []
        for i in range(start, end):
            entry = items[i] if isinstance(items[i], dict) else {}
            entries.append({
                "n": i,
                "at": str(entry.get("at") or ""),
                "by": str(entry.get("by") or ""),
                "text": str(entry.get("text") or ""),
            })
        return {
            "entries": entries,
            "earlier": start,
            "total": total,
        }

    def context(self, slug: str) -> list[dict]:
        if not valid_slug(slug) or not self._project_known(slug):
            raise NotFoundError(f"no project {slug}")
        return self.store.documents(slug)

    def document(self, slug: str, root: str, path: str) -> str:
        if not valid_slug(slug) or not self._project_known(slug):
            raise NotFoundError(f"no project {slug}")
        try:
            return self.store.document(slug, root, path)
        except FileNotFoundError as e:
            raise NotFoundError(str(e) or "no such document") from None

    def repo_files(self, slug: str, *, limit: int = REPO_FILES_MAX) -> dict:
        if not valid_slug(slug) or not self._project_known(slug):
            raise NotFoundError(f"no project {slug}")
        return self.store.repo_files(slug, limit=limit)

    def change(
        self,
        slug: str,
        task_id: str,
        *,
        commit: str | None = None,
        file: str | None = None,
        offset: int = 0,
        limit: int = DIFF_LINES_DEFAULT,
        commits_limit: int = COMMITS_MAX,
    ) -> dict:
        if not valid_slug(slug) or not self._project_known(slug):
            raise NotFoundError(f"no project {slug}")
        if not valid_task_id(task_id):
            raise ValueError(f"invalid task id: {task_id!r}")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > DIFF_LINES_MAX:
            raise ValueError(f"limit must be between 1 and {DIFF_LINES_MAX}")
        if (isinstance(commits_limit, bool) or not isinstance(commits_limit, int)
                or commits_limit <= 0 or commits_limit > COMMITS_LIMIT_MAX):
            raise ValueError(f"commits_limit must be between 1 and {COMMITS_LIMIT_MAX}")
        if commit is not None:
            if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
                raise ValueError(f"invalid commit hash: {commit!r}")
        if file is not None:
            if not isinstance(file, str) or not file or "\x00" in file:
                raise ValueError("file path must be a non-empty string")

        task = self.store.task(task_id)
        if task is None:
            raise NotFoundError(f"no task {task_id}")
        if not any(t.get("id") == task_id for t in self.store.tasks(slug)):
            raise NotFoundError(f"task {task_id} does not belong to project {slug}")

        branch = str(task.get("branch") or "").strip()
        base_pref = str(task.get("base") or "").strip()
        reg = self.store.registration(slug) or {}
        raw_repo = str(task.get("repo") or reg.get("repo") or task.get("worktree") or "").strip()
        repo_path = Path(raw_repo) if raw_repo else None
        if repo_path is None or not repo_path.is_absolute() or not repo_path.is_dir():
            if commit is not None or file is not None:
                raise NotFoundError("the project's repository is not on this machine")
            return _change_state_payload(
                "no_repo",
                "Project repository is not found on this machine.",
                slug=slug,
                task_id=task_id,
                branch=branch,
                base=base_pref,
            )

        try:
            _, _, gd_rc = _git_run(repo_path, ["rev-parse", "--git-dir"], max_bytes=4096)
        except FileNotFoundError:
            if commit is not None or file is not None:
                raise NotFoundError("git is not installed on this machine") from None
            return _change_state_payload(
                "no_git",
                "git is not installed on this machine.",
                slug=slug,
                task_id=task_id,
                branch=branch,
                base=base_pref,
            )
        if gd_rc != 0:
            if commit is not None or file is not None:
                raise NotFoundError("the project folder is not a git repository")
            return _change_state_payload(
                "not_git",
                "Project folder is not a git repository.",
                slug=slug,
                task_id=task_id,
                branch=branch,
                base=base_pref,
            )

        rec_raw = str(task.get("commit") or "").strip()
        rec_hash = _git_resolve(repo_path, rec_raw) if _COMMIT_RE.match(rec_raw) else ""

        tip = _git_resolve(repo_path, f"refs/heads/{branch}") if _plain_ref(branch) else ""
        base_name, base_hash = _resolve_base(repo_path, base_pref)
        recorded_commit = _commit_head(repo_path, rec_hash, base_hash) if rec_hash else None
        uncommitted = _uncommitted_count(repo_path, str(task.get("worktree") or "").strip())

        if commit is not None:
            target_hash = _git_resolve(repo_path, commit)
            if not target_hash:
                raise NotFoundError(f"commit {commit} is not in the project's repository")
            in_branch = bool(
                tip and base_hash
                and _git_is_ancestor(repo_path, target_hash, tip)
                and not _git_is_ancestor(repo_path, target_hash, base_hash)
            )
            if not in_branch and not (rec_hash and target_hash == rec_hash):
                raise NotFoundError(f"commit {commit} does not belong to task {task_id}")
            head = _commit_head(repo_path, target_hash, base_hash)
            if head is None:
                raise NotFoundError(f"could not read commit {commit}")
            files, ins, dels = _commit_files(repo_path, target_hash)
            if file is None:
                return {
                    "state": "ok",
                    "project": slug,
                    "task": task_id,
                    "branch": branch,
                    "base": base_name,
                    "commit": head,
                    "files": files,
                    "insertions": ins,
                    "deletions": dels,
                }
            file_entry = next((f for f in files if f["path"] == file), None)
            if file_entry is None:
                raise NotFoundError(f"file {file!r} was not changed in commit {target_hash[:7]}")
            return _single_file_diff_response(
                repo_path,
                slug=slug,
                task_id=task_id,
                branch=branch,
                base=base_name,
                commit_head=head,
                file_entry=file_entry,
                git_args_prefix=["show", "--no-color", "--no-ext-diff", "--no-textconv",
                                 "--diff-merges=first-parent", "--format=", "--patch", "-M", f"{target_hash}^{{commit}}"],
                offset=offset,
                limit=limit,
            )

        if file is not None:
            if not branch or not _plain_ref(branch):
                raise NotFoundError("this thread has no branch recorded")
            if not tip:
                raise NotFoundError(f"branch {branch} is no longer in the repository")
            if not base_hash:
                raise NotFoundError(f"the base of branch {branch} is not in the repository")
            files, _, _ = _range_files(repo_path, base_hash, tip)
            file_entry = next((f for f in files if f["path"] == file), None)
            if file_entry is None:
                raise NotFoundError(f"file {file!r} was not changed on branch {branch}")
            return _single_file_diff_response(
                repo_path,
                slug=slug,
                task_id=task_id,
                branch=branch,
                base=base_name,
                commit_head=None,
                file_entry=file_entry,
                git_args_prefix=["diff", "--no-color", "--no-ext-diff", "--no-textconv",
                                 "--patch", "-M", f"{base_hash}...{tip}"],
                offset=offset,
                limit=limit,
            )

        if not branch or not _plain_ref(branch):
            return _change_state_payload(
                "no_branch",
                "This thread has no branch recorded.",
                slug=slug,
                task_id=task_id,
                branch="",
                base=base_name or base_pref,
                uncommitted=uncommitted,
                recorded_commit=recorded_commit,
            )
        if not tip:
            return _change_state_payload(
                "branch_deleted",
                f"Branch {branch} is no longer in the repository.",
                slug=slug,
                task_id=task_id,
                branch=branch,
                base=base_name or base_pref,
                uncommitted=uncommitted,
                recorded_commit=recorded_commit,
            )
        if not base_hash:
            return _change_state_payload(
                "base_missing",
                f"Base branch for {branch} is not in the repository.",
                slug=slug,
                task_id=task_id,
                branch=branch,
                base=base_pref,
                uncommitted=uncommitted,
                recorded_commit=recorded_commit,
            )

        commits, more_commits = _branch_commits(repo_path, base_hash, tip, commits_limit)
        files, ins, dels = _range_files(repo_path, base_hash, tip)
        state = "ok" if (commits or files) else "empty"
        message = "" if state == "ok" else f"Branch {branch} has no commits ahead of {base_name}."
        return {
            "state": state,
            "message": message,
            "project": slug,
            "task": task_id,
            "branch": branch,
            "base": base_name,
            "commits": commits,
            "more_commits": more_commits,
            "files": files,
            "insertions": ins,
            "deletions": dels,
            "uncommitted": uncommitted,
            "recorded_commit": recorded_commit,
        }


def _plain_ref(name: object) -> bool:
    return (
        isinstance(name, str)
        and bool(_REF_RE.match(name))
        and ".." not in name
        and "//" not in name
        and not name.endswith("/")
        and not name.endswith(".lock")
        and len(name) <= 255
    )


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() not in _STRIP_GIT_ENV}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    return env


def _git_run(
    repo: Path,
    args: list[str],
    *,
    max_bytes: int = DIFF_READ_MAX_BYTES,
    timeout: float = GIT_TIMEOUT,
    literal_pathspecs: bool = False,
) -> tuple[bytes, bool, int | None]:
    cmd = [
        "git",
        *(["--literal-pathspecs"] if literal_pathspecs else []),
        "-C",
        str(repo),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.quotepath=false",
        *args,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env=_git_env(),
    )
    assert proc.stdout is not None
    timed_out = False

    def _on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        try:
            proc.kill()
        except OSError:
            pass

    timer = threading.Timer(timeout, _on_timeout)
    timer.daemon = True
    timer.start()
    buf = bytearray()
    truncated = False
    try:
        while True:
            need = (max_bytes + 1) - len(buf)
            if need <= 0:
                truncated = True
                try:
                    proc.terminate()
                except OSError:
                    pass
                break
            chunk = proc.stdout.read(min(65536, need))
            if not chunk:
                break
            buf.extend(chunk)
        if len(buf) > max_bytes:
            truncated = True
            del buf[max_bytes:]
            try:
                proc.terminate()
            except OSError:
                pass
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait()
        timer.cancel()
    if timed_out:
        return bytes(buf), truncated, None
    return bytes(buf), truncated, (0 if truncated else proc.returncode)


def _git_resolve(repo: Path, ref: str) -> str:
    data, _, rc = _git_run(repo, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], max_bytes=4096)
    if rc != 0:
        return ""
    h = data.decode("utf-8", errors="replace").strip().lower()
    return h if _FULL_HASH_RE.match(h) else ""


def _resolve_base(repo: Path, base_pref: str) -> tuple[str, str]:
    for name in (base_pref, "main", "master", "HEAD"):
        if not _plain_ref(name):
            continue
        h = _git_resolve(repo, name)
        if h:
            return name, h
    return "", ""


def _git_is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    _, _, rc = _git_run(repo, ["merge-base", "--is-ancestor", ancestor, descendant], max_bytes=1024)
    return rc == 0


def _git_common_dir(folder: Path) -> Path | None:
    try:
        data, _, rc = _git_run(folder, ["rev-parse", "--git-common-dir"], max_bytes=4096)
    except FileNotFoundError:
        return None
    if rc != 0:
        return None
    raw = data.decode("utf-8", errors="replace").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = folder / p
    try:
        return p.resolve()
    except OSError:
        return None


def _uncommitted_count(repo: Path, worktree: str) -> int:
    if not worktree:
        return -1
    wt = Path(worktree)
    if not wt.is_absolute() or not wt.is_dir():
        return -1
    wt_common = _git_common_dir(wt)
    repo_common = _git_common_dir(repo)
    if wt_common is None or wt_common != repo_common:
        return -1
    data, trunc, rc = _git_run(wt, ["status", "--porcelain"], max_bytes=STATUS_MAX_BYTES)
    if rc != 0 or trunc:
        return -1
    return sum(1 for line in data.split(b"\n") if line and not line.endswith(b" .tools"))


def _shortstat(text: str) -> tuple[int, int, int]:
    files = ins = dels = 0
    for m in _SHORTSTAT_RE.finditer(text):
        n = int(m.group(1))
        ch = m.group(2)[0]
        if ch == "f":
            files = n
        elif ch == "i":
            ins = n
        elif ch == "d":
            dels = n
    return files, ins, dels


def _commit_head(repo: Path, resolved_hash: str, base_hash: str = "") -> dict | None:
    data, _, rc = _git_run(
        repo,
        [
            "show", "--no-color", "--no-ext-diff", "--no-textconv", "--diff-merges=first-parent",
            "--format=%H%x00%s%x00%an%x00%aI%x00%P", "--shortstat", f"{resolved_hash}^{{commit}}",
        ],
        max_bytes=65536,
    )
    if rc != 0:
        return None
    text = data.decode("utf-8", errors="replace")
    head_line, _, rest = text.partition("\n")
    fields = head_line.split("\x00")
    if len(fields) < 4 or not _FULL_HASH_RE.match(fields[0]):
        return None
    parents = [p for p in (fields[4].split() if len(fields) > 4 else []) if _FULL_HASH_RE.match(p)]
    is_merge = len(parents) > 1
    merges_base = bool(
        is_merge
        and base_hash
        and not _git_is_ancestor(repo, fields[0], base_hash)
        and any(_git_is_ancestor(repo, p, base_hash) for p in parents[1:])
    )
    files, ins, dels = _shortstat(rest)
    return {
        "hash": fields[0],
        "short": fields[0][:7],
        "subject": fields[1],
        "author": fields[2],
        "date": fields[3],
        "files": files,
        "insertions": ins,
        "deletions": dels,
        "merge": is_merge,
        "merges_base": merges_base,
    }


def _branch_commits(repo: Path, base_hash: str, tip_hash: str, limit: int) -> tuple[list[dict], bool]:
    data, _, rc = _git_run(
        repo,
        [
            "log", "--no-color", "--no-ext-diff", "--no-textconv", "--diff-merges=first-parent",
            "--format=%x1e%H%x00%s%x00%an%x00%aI%x00%P", "--shortstat",
            f"--max-count={limit + 1}", f"{base_hash}..{tip_hash}",
        ],
    )
    if rc != 0:
        return [], False
    text = data.decode("utf-8", errors="replace")
    out: list[dict] = []
    for record in text.split("\x1e"):
        if not record:
            continue
        head_line, _, rest = record.partition("\n")
        fields = head_line.split("\x00")
        if len(fields) < 4 or not _FULL_HASH_RE.match(fields[0]):
            continue
        parents = [p for p in (fields[4].split() if len(fields) > 4 else []) if _FULL_HASH_RE.match(p)]
        is_merge = len(parents) > 1
        merges_base = bool(is_merge and base_hash and any(_git_is_ancestor(repo, p, base_hash) for p in parents[1:]))
        files, ins, dels = _shortstat(rest)
        out.append({
            "hash": fields[0],
            "short": fields[0][:7],
            "subject": fields[1],
            "author": fields[2],
            "date": fields[3],
            "files": files,
            "insertions": ins,
            "deletions": dels,
            "merge": is_merge,
            "merges_base": merges_base,
        })
    more = len(out) > limit
    if more:
        out = out[:limit]
    return out, more


def _parse_numstat_z(data: bytes) -> list[dict]:
    if not data:
        return []
    tokens = data.decode("utf-8", errors="replace").split("\x00")
    out: list[dict] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if i == 0:
            tok = tok.lstrip("\r\n")
        i += 1
        if not tok:
            continue
        parts = tok.split("\t", 2)
        if len(parts) != 3:
            continue
        added_s, deleted_s, path = parts
        old_path: str | None = None
        if not path:
            if i + 1 < len(tokens):
                old_path = tokens[i]
                path = tokens[i + 1]
                i += 2
            else:
                break
        binary = added_s == "-" or deleted_s == "-"
        out.append({
            "path": path,
            "old_path": old_path,
            "insertions": 0 if binary else int(added_s or 0),
            "deletions": 0 if binary else int(deleted_s or 0),
            "binary": binary,
        })
    return out


def _parse_name_status_z(data: bytes) -> dict[str, tuple[str, str | None]]:
    if not data:
        return {}
    tokens = data.decode("utf-8", errors="replace").split("\x00")
    out: dict[str, tuple[str, str | None]] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if i == 0:
            tok = tok.lstrip("\r\n")
        i += 1
        if not tok:
            continue
        code = tok[0]
        if code in ("R", "C"):
            if i + 1 >= len(tokens):
                break
            old_path = tokens[i]
            new_path = tokens[i + 1]
            i += 2
            out[new_path] = (code, old_path)
        else:
            if i >= len(tokens):
                break
            path = tokens[i]
            i += 1
            out[path] = (code, None)
    return out


def _merge_file_stats(num_bytes: bytes, status_bytes: bytes) -> tuple[list[dict], int, int]:
    num_rows = _parse_numstat_z(num_bytes)
    status_map = _parse_name_status_z(status_bytes)
    files: list[dict] = []
    seen_idx: dict[str, int] = {}
    total_ins = total_dels = 0
    for row in num_rows:
        path = row["path"]
        status, old_from_ns = status_map.get(path, ("M", None))
        old_path = row["old_path"] if row["old_path"] is not None else old_from_ns
        if row["old_path"] is not None and status not in ("R", "C"):
            status = "R"
        total_ins += row["insertions"]
        total_dels += row["deletions"]
        if path in seen_idx:
            prev = files[seen_idx[path]]
            prev["insertions"] += row["insertions"]
            prev["deletions"] += row["deletions"]
            prev["binary"] = prev["binary"] or row["binary"]
            continue
        seen_idx[path] = len(files)
        files.append({
            "path": path,
            "old_path": old_path,
            "status": status,
            "insertions": row["insertions"],
            "deletions": row["deletions"],
            "binary": row["binary"],
        })
    return files, total_ins, total_dels


def _range_files(repo: Path, base_hash: str, tip_hash: str) -> tuple[list[dict], int, int]:
    span = f"{base_hash}...{tip_hash}"
    num_b, _, rc1 = _git_run(
        repo, ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "--numstat", "-z", "-M", span]
    )
    ns_b, _, rc2 = _git_run(
        repo, ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "--name-status", "-z", "-M", span]
    )
    if rc1 != 0 or rc2 != 0:
        return [], 0, 0
    return _merge_file_stats(num_b, ns_b)


def _commit_files(repo: Path, commit_hash: str) -> tuple[list[dict], int, int]:
    ref = f"{commit_hash}^{{commit}}"
    num_b, _, rc1 = _git_run(
        repo,
        ["show", "--no-color", "--no-ext-diff", "--no-textconv", "--diff-merges=first-parent",
         "--format=", "--numstat", "-z", "-M", ref],
    )
    ns_b, _, rc2 = _git_run(
        repo,
        ["show", "--no-color", "--no-ext-diff", "--no-textconv", "--diff-merges=first-parent",
         "--format=", "--name-status", "-z", "-M", ref],
    )
    if rc1 != 0 or rc2 != 0:
        return [], 0, 0
    return _merge_file_stats(num_b, ns_b)


def _clip_diff_text(text: str) -> tuple[str, bool]:
    if len(text) <= DIFF_LINE_MAX_CHARS:
        return text, False
    return text[:DIFF_LINE_MAX_CHARS] + "…", True


def _parse_single_file_diff(raw_text: str, *, byte_truncated: bool = False) -> tuple[list[dict], bool]:
    if not raw_text:
        return [], False
    if byte_truncated and not raw_text.endswith("\n"):
        lines_raw = raw_text.split("\n")[:-1]
    elif raw_text.endswith("\n"):
        lines_raw = raw_text[:-1].split("\n")
    else:
        lines_raw = raw_text.split("\n")

    out: list[dict] = []
    in_hunk = False
    old_n = new_n = 0
    any_clipped = False
    for raw_line in lines_raw:
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if line.startswith("diff --git "):
            in_hunk = False
            continue
        m = _HUNK_RE.match(line)
        if m:
            in_hunk = True
            old_n = int(m.group(1))
            new_n = int(m.group(2))
            clipped_txt, was_clipped = _clip_diff_text(line)
            if was_clipped:
                any_clipped = True
            entry = {"kind": "hunk", "text": clipped_txt}
            if was_clipped:
                entry["clipped"] = True
            out.append(entry)
            continue
        if not in_hunk:
            if line.startswith((
                "new file", "deleted file", "old mode", "new mode",
                "rename from", "rename to", "copy from", "copy to",
                "similarity index", "Binary files",
            )):
                clipped_txt, was_clipped = _clip_diff_text(line)
                if was_clipped:
                    any_clipped = True
                entry = {"kind": "meta", "text": clipped_txt}
                if was_clipped:
                    entry["clipped"] = True
                out.append(entry)
            continue
        if line.startswith("+"):
            clipped_txt, was_clipped = _clip_diff_text(line[1:])
            if was_clipped:
                any_clipped = True
            entry = {"kind": "add", "text": clipped_txt, "new_line": new_n}
            if was_clipped:
                entry["clipped"] = True
            out.append(entry)
            new_n += 1
        elif line.startswith("-"):
            clipped_txt, was_clipped = _clip_diff_text(line[1:])
            if was_clipped:
                any_clipped = True
            entry = {"kind": "del", "text": clipped_txt, "old_line": old_n}
            if was_clipped:
                entry["clipped"] = True
            out.append(entry)
            old_n += 1
        elif line.startswith("\\"):
            raw_meta = line[2:] if line.startswith("\\ ") else line[1:]
            clipped_txt, was_clipped = _clip_diff_text(raw_meta)
            if was_clipped:
                any_clipped = True
            entry = {"kind": "meta", "text": clipped_txt}
            if was_clipped:
                entry["clipped"] = True
            out.append(entry)
        else:
            raw_ctx = line[1:] if line.startswith(" ") else line
            clipped_txt, was_clipped = _clip_diff_text(raw_ctx)
            if was_clipped:
                any_clipped = True
            entry = {"kind": "ctx", "text": clipped_txt, "old_line": old_n, "new_line": new_n}
            if was_clipped:
                entry["clipped"] = True
            out.append(entry)
            old_n += 1
            new_n += 1
    return out, any_clipped


def _single_file_diff_response(
    repo: Path,
    *,
    slug: str,
    task_id: str,
    branch: str,
    base: str,
    commit_head: dict | None,
    file_entry: dict,
    git_args_prefix: list[str],
    offset: int,
    limit: int,
) -> dict:
    if file_entry.get("binary"):
        return {
            "state": "ok",
            "project": slug,
            "task": task_id,
            "branch": branch,
            "base": base,
            "commit": commit_head,
            "file": file_entry,
            "binary": True,
            "lines": [],
            "offset": 0,
            "limit": limit,
            "total_lines": 0,
            "has_more": False,
            "next_offset": None,
            "truncated": False,
            "truncated_lines": False,
        }
    paths = [file_entry["old_path"], file_entry["path"]] if file_entry.get("old_path") else [file_entry["path"]]
    raw_b, byte_trunc, rc = _git_run(
        repo, [*git_args_prefix, "--", *paths], max_bytes=DIFF_READ_MAX_BYTES, literal_pathspecs=True
    )
    if rc != 0:
        raise NotFoundError(f"could not read diff for {file_entry['path']}")
    parsed, any_clipped = _parse_single_file_diff(
        raw_b.decode("utf-8", errors="replace"), byte_truncated=byte_trunc
    )
    total = len(parsed)
    page = parsed[offset : offset + limit]
    next_off = offset + len(page)
    has_more = next_off < total
    return {
        "state": "ok",
        "project": slug,
        "task": task_id,
        "branch": branch,
        "base": base,
        "commit": commit_head,
        "file": file_entry,
        "binary": False,
        "lines": page,
        "offset": offset,
        "limit": limit,
        "total_lines": total,
        "has_more": has_more,
        "next_offset": next_off if has_more else None,
        "truncated": byte_trunc,
        "truncated_lines": any_clipped,
    }


def _change_state_payload(
    state: str,
    message: str,
    *,
    slug: str,
    task_id: str,
    branch: str,
    base: str,
    uncommitted: int = -1,
    recorded_commit: dict | None = None,
) -> dict:
    return {
        "state": state,
        "message": message,
        "project": slug,
        "task": task_id,
        "branch": branch,
        "base": base,
        "commits": [],
        "more_commits": False,
        "files": [],
        "insertions": 0,
        "deletions": 0,
        "uncommitted": uncommitted,
        "recorded_commit": recorded_commit,
    }
