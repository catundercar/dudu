"""Worker lifecycle: checking live and owned terminals, scheduling idle close, ending terminals and TUI panes,
retiring review threads, and retiring worktrees and branches. Layer 3."""
from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Iterator

from ..caller import Caller
from ..context import Context
from ..errors import Refused
from ..events.deliver import deliverer_env
from ..ledger.ledger import Change, Ledger
from ..ledger.plan import has_unfinished_plan, sync_plan_for_status
from ..ledger.task import ACTIVE, CLOSED, Task, hc_terminal_of, started_by_pm
from ..memory.candidates import MemoryCandidates, candidate_names_of
from ..project.project import in_scope
from ..store import valid_task_id
from .research import collect_research_for, retire_dirty_for
from .sessions import _worker_caller, _worker_raw_task


# Scoped only to legacy `with ending(...):` -> `end_terminal`/`end_worker` calls during Stages 1-5.
_LEGACY_ENDING: contextvars.ContextVar[tuple[str, str]] = contextvars.ContextVar("_legacy_ending", default=("", ""))


@dataclass(frozen=True)
class RetireResult:
    """Structured outcome of `Workers.retire` (`retire_workspace`)."""

    task_id: str
    summary: str
    lines: tuple[str, ...]
    collected_research: tuple[str, ...] = ()


def live_worker_for(ctx: Context, task: Any) -> str:
    """The pane of an agent that still runs for this task, or ""."""
    raw = _worker_raw_task(task)
    pane = raw.get("pane") or ""
    if not pane or pane == ctx.pane or (raw.get("status") == "proposed" and not started_by_pm(raw)):
        return ""
    if "/" in pane:
        return pane
    if pane.startswith("hc:"):
        info = ctx.hc.get(pane[3:])
        return pane if info is not None and info.is_live else ""
    return pane if any(x.get("pane_id") == pane for x in ctx.tui.agents()) else ""


def is_pane_live_for(ctx: Context, pane: str) -> bool:
    """Whether `pane` (local `hc:<t>`, remote `machine/t`, or TUI pane) currently holds a live terminal/agent."""
    if not pane:
        return False
    if "/" in pane:
        return True
    if pane.startswith("hc:"):
        info = ctx.hc.get(pane[3:])
        return info is not None and info.is_live
    return any(x.get("pane_id") == pane for x in ctx.tui.agents())


def owned_terminal_for(ctx: Context, task: Any) -> dict[str, Any] | None:
    """hc get of the worker terminal pm.py started for this task: labelled task=<id>, no PM's, not this session's."""
    raw = _worker_raw_task(task)
    term = hc_terminal_of(raw)
    if not term or f"hc:{term}" == ctx.pane or not started_by_pm(raw):
        return None
    info = ctx.hc.get_raw(term) or {}
    labels = info.get("labels") or {}
    if not info or labels.get("pm") or labels.get("task") != raw["id"]:
        return None
    return info


def term_status(info: dict[str, Any]) -> str:
    status = info.get("status")
    return (status.get("state") or "") if isinstance(status, dict) else str(status or "")


def close_later_for(
    ctx: Context,
    term: str,
    task_id: str,
    quiet: int | float,
    timeout: int | float,
    statuses: Iterable[str],
    *,
    retire: bool = False,
) -> None:
    """Start close-worker in the background."""
    if getattr(ctx, "_legacy", False) and close_later is not _DEFAULT_CLOSE_LATER:
        if retire:
            close_later(term, task_id, quiet, timeout, statuses, retire=True)
        else:
            close_later(term, task_id, quiet, timeout, statuses)
        return
    _close_later_impl(ctx, term, task_id, quiet, timeout, statuses, retire=retire)


def _close_later_impl(
    ctx: Context,
    term: str,
    task_id: str,
    quiet: int | float,
    timeout: int | float,
    statuses: Iterable[str],
    *,
    retire: bool = False,
) -> None:
    args = [
        "close-worker", term, "--task", task_id,
        "--quiet", str(quiet), "--timeout", str(timeout), "--while", ",".join(statuses),
    ]
    if retire:
        args.append("--retire")
    env = deliverer_env() if getattr(ctx, "_legacy", False) else ctx.procs.clean_session_env()
    ctx.procs.spawn_pm(args, env=env, cwd=ctx.home.root)


def workers_cfg_for(ctx: Context) -> dict[str, Any]:
    cfg = ctx.config.read().get("workers")
    return cfg if isinstance(cfg, dict) else {}


def idle_minutes_for(ctx: Context) -> int:
    return int(workers_cfg_for(ctx).get("idle_minutes") or 30)


def active_review_of_for(
    ctx: Context,
    task_id: str,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """An active (unclosed, unretired, non-proposed) review task of `task_id`, or None."""
    if not task_id:
        return None
    pool = tasks if tasks is not None else Ledger(ctx).raw_tasks()
    for r in pool:
        raw = _worker_raw_task(r)
        if (isinstance(raw, dict) and raw.get("review_of") == task_id and raw.get("id") != task_id
                and not raw.get("retired") and raw.get("status") in ACTIVE and raw.get("status") != "proposed"):
            return raw
    return None


def close_worker_for(ctx: Context, task: Any, *, forced: bool = False) -> str:
    """End a closed task's worker terminal when `workers.close_on_close` is true (or `forced=True`)."""
    raw = _worker_raw_task(task)
    if not forced and workers_cfg_for(ctx).get("close_on_close") is not True:
        return ""
    term = hc_terminal_of(raw)
    if not term or not started_by_pm(raw):
        return ""
    tasks = Ledger(ctx).raw_tasks()
    if any(t["id"] != raw["id"] and hc_terminal_of(t) == term and t["status"] in ACTIVE and not t.get("retired")
           for t in tasks):
        return ctx.config.tr(f"hc:{term} kept: another open task uses it", f"hc:{term} 保留：还有未关闭的任务在用")
    if not forced:
        rev = active_review_of_for(ctx, raw["id"], tasks)
        if rev:
            return ctx.config.tr(
                f"hc:{term} kept: active review {rev['id']} is running",
                f"hc:{term} 保留：审查 {rev['id']} 还在进行",
            )
    if f"hc:{term}" == ctx.pane:
        labels = (ctx.hc.get_raw(term) or {}).get("labels") or {}
        if labels.get("pm") or labels.get("task") != raw["id"]:
            return ""
        close_later_for(ctx, term, raw["id"], 20, 7200, CLOSED)
        return ctx.config.tr(f"hc:{term} ends once this turn is over", f"hc:{term} 本轮结束后关闭")
    info = owned_terminal_for(ctx, raw)
    if not info:
        return ""
    if info.get("state") == "live" and term_status(info) == "working":
        return ctx.config.tr(
            f"hc:{term} kept: still working (pm.py idle-workers --close ends it once idle)",
            f"hc:{term} 保留：还在干活（空闲后用 pm.py idle-workers --close 关）",
        )
    why = "retire" if forced else "workers.close_on_close"
    return f"terminal hc:{term}" if end_terminal_for(ctx, term, why=why, task_id=raw.get("id") or "") else ""


def close_reported_for(ctx: Context, task: Any) -> str:
    """Schedule idle close for a reported worker when `workers.close_reported` is enabled."""
    raw = _worker_raw_task(task)
    term = hc_terminal_of(raw)
    if workers_cfg_for(ctx).get("close_reported") is not True or not term or f"hc:{term}" != ctx.pane or not started_by_pm(raw):
        return ""
    labels = (ctx.hc.get_raw(term) or {}).get("labels") or {}
    if labels.get("pm") or labels.get("task") != raw["id"]:
        return ""
    minutes = idle_minutes_for(ctx)
    close_later_for(ctx, term, raw["id"], minutes * 60, minutes * 60 + 4 * 3600, ["review"])
    return ctx.config.tr(
        f"hc:{term} ends after {minutes} idle minutes (workers.close_reported); `pm.py reattach {raw['id']}` resumes its session",
        f"hc:{term} 空闲 {minutes} 分钟后关闭（workers.close_reported）；要再找它，用 `pm.py reattach {raw['id']}` 恢复会话",
    )


def project_workers_for(
    ctx: Context,
    repo: str | Path,
    tasks: list[dict[str, Any]] | None = None,
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """This project's worker terminals, finished ones too: `[(address, hc_get_raw, task)]`."""
    pool = tasks if tasks is not None else Ledger(ctx).raw_tasks()
    scoped = [t for t in pool if in_scope(t.get("repo"), repo) and started_by_pm(t) and hc_terminal_of(t)]
    scoped_ids = {t["id"] for t in scoped}
    out: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for task in scoped:
        address = hc_terminal_of(task)
        if address in seen or f"hc:{address}" == ctx.pane:
            continue
        seen.add(address)
        info = ctx.hc.get_raw(address) or {}
        labels = info.get("labels") or {}
        if info and not labels.get("pm") and labels.get("task") in scoped_ids:
            out.append((address, info, next(t for t in scoped if t["id"] == labels["task"])))
    return out


def mark_closed_for(ctx: Context, pane: str, task_id: str, *, why: str = "") -> None:
    """Record on the task that pm.py is ending its terminal `pane` on purpose: `{pane, at, why}` under `closed`."""
    if not pane or not task_id or not valid_task_id(task_id) or not ctx.home.task(task_id).is_file():
        return
    reason = why or (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "pm.py")

    def _mark(cur: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(cur, dict) or (cur.get("pane") or "") != pane:
            return None
        cur["closed"] = {"pane": pane, "at": ctx.clock.now(), "why": reason}
        return cur

    with contextlib.suppress(Exception):
        ctx.store.change_task(task_id, _mark)


def end_terminal_for(ctx: Context, term: str, *, why: str = "", task_id: str = "") -> bool:
    """End and remove a worker's herdr-core terminal; never a PM's. True when there was one to remove."""
    if getattr(ctx, "_legacy", False) and end_terminal is not _DEFAULT_END_TERMINAL:
        return bool(end_terminal(term))
    return _end_terminal_impl(ctx, term, why=why, task_id=task_id)


def _end_terminal_impl(ctx: Context, term: str, *, why: str = "", task_id: str = "") -> bool:
    info = (ctx.hc.get_raw(term) or {}) if term else {}
    if not info or (info.get("labels") or {}).get("pm"):
        return False
    mark_closed_for(ctx, f"hc:{term}", (info.get("labels") or {}).get("task") or task_id, why=why)
    if info.get("state") == "live":
        ctx.hc.kill(term)
    ctx.hc.remove(term)
    return True


def end_worker_for(ctx: Context, task: Any, *, why: str = "") -> str:
    """End the terminal (hc) or pane (herdr TUI) that pm.py started this task's worker or reviewer in."""
    if getattr(ctx, "_legacy", False) and end_worker is not _DEFAULT_END_WORKER:
        return str(end_worker(task) or "")
    return _end_worker_impl(ctx, task, why=why)


def _end_worker_impl(ctx: Context, task: Any, *, why: str = "") -> str:
    raw = _worker_raw_task(task)
    pane = raw.get("pane") or ""
    if pane.startswith("hc:"):
        return f"terminal {pane}" if end_terminal_for(ctx, pane[3:], why=why, task_id=raw.get("id") or "") else ""
    if not pane or pane == ctx.pane or pane != raw.get("worker_pane") or _worker_caller(ctx).pm_record_for_pane(pane):
        return ""
    if not any(x.get("pane_id") == pane and x.get("name") == raw.get("agent") for x in ctx.tui.agents()):
        return ""  # another agent came into the pane since, or none runs there: left as it is
    mark_closed_for(ctx, pane, raw.get("id") or "", why=why)
    return f"pane {pane}" if ctx.tui.pane_close(pane) is not None else ""


def close_review_for(ctx: Context, review: Any, text: str) -> list[str]:
    """Retire a review thread (`pm.py review`) and end its reviewer's terminal or pane."""
    raw = _worker_raw_task(review)
    ended = end_worker_for(ctx, raw, why="retire")
    done = [ended] if ended else []

    def _close(cur: Task | None, ch: Change) -> dict[str, Any]:
        assert cur is not None
        r = cur.raw
        r["retired"] = ctx.clock.now()
        if r["status"] in ACTIVE:
            r["status"] = "done"
        ch.note_on(r, text)
        return r

    Ledger(ctx).change(raw["id"], _close)
    return [f"{raw['id']}"] + done


def retire_review_for(ctx: Context, task: Any, text: str | None = None) -> list[str]:
    """Close the review thread of a task, if it has one that is still open."""
    if getattr(ctx, "_legacy", False) and retire_review is not _DEFAULT_RETIRE_REVIEW:
        return list(retire_review(task) if text is None else retire_review(task, text))
    return _retire_review_impl(ctx, task, text=text)


def _retire_review_impl(ctx: Context, task: Any, text: str | None = None) -> list[str]:
    raw = _worker_raw_task(task)
    path = ctx.home.task(f"{raw['id']}-review")
    review = json.loads(path.read_text()) if path.exists() else None
    if not review or review.get("retired") or review.get("review_of") != raw["id"]:
        return []
    return close_review_for(ctx, review, text or ctx.config.tr(f"retired with {raw['id']}", f"随 {raw['id']} 一起回收"))


def retire_workspace_for(
    ctx: Context,
    task_id: str,
    *,
    force: bool = False,
    keep_active: bool = False,
) -> RetireResult:
    """Retire a task's review, worker terminal, worktree and branch; keep task in_progress when post-merge steps remain.

    Raises `Refused` when unmerged (without `force`), dirty (without `force`), or live session sits in a found worktree.
    """
    ledger = Ledger(ctx)
    task = ledger.load(task_id).raw
    if task.get("review_of"):  # a review thread: only its reviewer's terminal goes
        done = close_review_for(ctx, task, "retired")[1:]
        summary = "retired: removed " + (", ".join(done) or "nothing")
        return RetireResult(task_id=task["id"], summary=summary, lines=(f"{task['id']} {summary}",))

    repo, branch, base = task["repo"], task.get("branch"), task["base"]
    worktree = task.get("worktree")
    found = False
    if not worktree and branch and branch != base:
        worktree = ctx.git.checkout_of(repo, branch)
        found = bool(worktree)
    done: list[str] = []
    lines: list[str] = []
    collected_all: list[str] = []
    target = ctx.git.merge_target(repo, base)
    gone = ctx.config.tr(f" ({base} no longer exists)", f"（{base} 已不存在）") if target != base else ""
    branch_exists = bool(branch and ctx.git.branch_exists(repo, branch))
    if branch and not (task.get("landed") and not branch_exists):
        if not ctx.git.is_ancestor(repo, branch, target) and not force:
            raise Refused(ctx.config.tr(
                f"{branch} is not merged into {target}{gone}; pass --force to discard it",
                f"{branch} 没合并进 {target}{gone}；要丢弃它就加 --force",
            ))
    done += retire_review_for(ctx, task)
    others = [
        t for t in ledger.raw_tasks()
        if t["id"] != task["id"] and not t.get("retired") and t["status"] not in ("done", "abandoned")
    ]

    def shares(t: dict[str, Any]) -> bool:
        if t.get("worktree"):
            return Path(t["worktree"]).resolve() == Path(worktree).resolve()
        return bool(branch) and t["repo"] == repo and t.get("branch") == branch

    if worktree and any(shares(t) for t in others):
        lines.append(f"{worktree} is kept: another task still uses it")
        worktree = None
    if worktree and Path(worktree).is_dir() and Path(worktree).resolve() != Path(repo).resolve():
        saved: list[str] = []
        if not force and task.get("status") != "abandoned":
            collected, saved = collect_research_for(ctx, task, worktree=worktree, report_saved=True)
            if collected:
                collected_all.extend(collected)
                lines.append(f"{task['id']}: collected research: {', '.join(collected)}")
        dirty = retire_dirty_for(ctx, worktree, ignore_untracked=saved) if not force else 0
        if dirty and not force:
            raise Refused(f"{worktree} has {dirty} uncommitted changes")
        term = hc_terminal_of(task)
        info = (ctx.hc.get_raw(term) or {}) if term and (found or f"hc:{term}" != ctx.pane) else {}
        if found:
            cwd = Path(info.get("cwd") or "/").resolve()
            if info.get("state") == "live" and Path(worktree).resolve() in (cwd, *cwd.parents):
                raise Refused(f"worktree {worktree} is kept: hc:{term} still works in it")
        elif (info and not (info.get("labels") or {}).get("pm")
                and Path(info.get("cwd") or "/").resolve() == Path(worktree).resolve()):
            if end_terminal_for(ctx, term, why="retire", task_id=task["id"]):
                done.append(f"terminal hc:{term}")
        wts = ctx.tui.worktrees(cwd=repo) or []
        owned = [
            w for w in wts
            if Path(w.get("path", "")).resolve() == Path(worktree).resolve() and w.get("open_workspace_id")
        ]
        tools = Path(worktree) / ".tools"
        if tools.is_symlink():
            tools.unlink()
        if owned and owned[0]["open_workspace_id"] != ctx.workspace:
            ctx.tui.worktree_remove(workspace=owned[0]["open_workspace_id"], force=True)
        else:
            ctx.git.worktree_remove(repo, worktree, force=True)
        if not Path(worktree).is_dir():
            done.append(f"worktree {worktree}")
    kept = ""
    if branch and branch != base:
        if ctx.git.delete_branch(repo, branch, force=True):
            done.append(f"branch {branch}")
        elif ctx.git.branch_exists(repo, branch):
            where = ctx.git.checkout_of(repo, branch)
            kept = f"; branch {branch} is kept: " + (f"checked out in {where}" if where else "git refused to delete it")
    if task.get("in_place") and not any(x.startswith("terminal ") for x in done):
        ended = close_worker_for(ctx, {**task, "status": "merged"}, forced=True)
        if ended.startswith("terminal "):
            done.append(ended)
        elif ended:
            kept += f"; {ended}"
    summary = "retired: removed " + (", ".join(done) or "nothing") + kept
    if gone and branch and not force:
        summary += ctx.config.tr(f"; checked as merged into {target}{gone}", f"；按已合并进 {target} 判断{gone}")

    def _finish_retire(cur: Task | None, ch: Change) -> dict[str, Any]:
        assert cur is not None
        r = cur.raw
        stay_active = keep_active or (bool(r.get("landed")) and has_unfinished_plan(r) and not force)
        if stay_active:
            r["status"] = "in_progress"
            if any(x.startswith("terminal ") for x in done):
                r["pane"] = ""
                r["workspace"] = ""
                r.pop("worker_pane", None)
            elif not r.get("worktree") or not Path(r["worktree"]).is_dir():
                if r.get("dispatched") and r.get("pane") and not live_worker_for(ctx, r):
                    r["pane"] = ""
                    r["workspace"] = ""
                    r.pop("worker_pane", None)
            if any(x.startswith("worktree ") for x in done) or (
                    r.get("worktree") and not Path(r["worktree"]).is_dir()):
                r["worktree"] = ""
        else:
            r["retired"] = ctx.clock.now()
            if r["status"] in ACTIVE:
                r["status"] = "abandoned" if force else "merged"
            sync_plan_for_status(r, r["status"])
        for h in r.get("helpers") or []:
            if isinstance(h, dict) and h.get("status") == "running":
                h["status"] = "exited"
                h["ended"] = ctx.clock.now_sec()
        ch.note_on(r, summary)
        return r

    updated_task = ledger.change(task_id, _finish_retire)
    assert updated_task is not None
    final_raw = updated_task.raw
    if repo and not (keep_active or (bool(final_raw.get("landed")) and has_unfinished_plan(final_raw) and not force)):
        MemoryCandidates(ctx, repo).prune(finished=candidate_names_of(final_raw))
    lines.append(f"{final_raw['id']} {summary}")
    return RetireResult(
        task_id=final_raw["id"],
        summary=summary,
        lines=tuple(lines),
        collected_research=tuple(collected_all),
    )


# --- Legacy module-level shims (Stages 1-5 compatibility) ---


def live_worker(task: Any) -> str:
    return live_worker_for(Context.from_env(), task)


def owned_terminal(task: Any) -> dict[str, Any] | None:
    return owned_terminal_for(Context.from_env(), task)


def close_later(
    term: str,
    task_id: str,
    quiet: int | float,
    timeout: int | float,
    statuses: Iterable[str],
    *,
    retire: bool = False,
) -> None:
    _close_later_impl(Context.from_env(), term, task_id, quiet, timeout, statuses, retire=retire)


_DEFAULT_CLOSE_LATER = close_later


def workers_cfg() -> dict[str, Any]:
    return workers_cfg_for(Context.from_env())


def idle_minutes() -> int:
    return idle_minutes_for(Context.from_env())


def active_review_of(task_id: str, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    return active_review_of_for(Context.from_env(), task_id, tasks=tasks)


def close_worker(task: Any, forced: bool = False) -> str:
    return close_worker_for(Context.from_env(), task, forced=forced)


def close_reported(task: Any) -> str:
    return close_reported_for(Context.from_env(), task)


def project_workers(repo: str | Path, tasks: list[dict[str, Any]] | None = None) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    return project_workers_for(Context.from_env(), repo, tasks=tasks)


@contextlib.contextmanager
def ending(why: str, task: str = "") -> Iterator[None]:
    prev_why, prev_task = _LEGACY_ENDING.get()
    tok = _LEGACY_ENDING.set((why, task or prev_task))
    try:
        yield
    finally:
        _LEGACY_ENDING.reset(tok)


def mark_closed(pane: str, task_id: str) -> None:
    why, _ = _LEGACY_ENDING.get()
    mark_closed_for(Context.from_env(), pane, task_id, why=why)


def end_terminal(term: str) -> bool:
    why, task_id = _LEGACY_ENDING.get()
    return _end_terminal_impl(Context.from_env(), term, why=why, task_id=task_id)


_DEFAULT_END_TERMINAL = end_terminal


def end_worker(task: Any) -> str:
    why, _ = _LEGACY_ENDING.get()
    return _end_worker_impl(Context.from_env(), task, why=why)


_DEFAULT_END_WORKER = end_worker


def close_review(review: Any, text: str) -> list[str]:
    return close_review_for(Context.from_env(), review, text)


def retire_review(task: Any, text: str | None = None) -> list[str]:
    return _retire_review_impl(Context.from_env(), task, text=text)


_DEFAULT_RETIRE_REVIEW = retire_review
