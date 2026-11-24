"""Waiting for a worker to report in the ledger, and tracking active waits across PM rotations. Layer 3."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
import json
import os
from typing import Any, Iterator

from ..context import Context
from ..errors import WaitOutcome
from ..events.deliver import REPORT_WIDTH
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..ledger.task import Task, hc_terminal_of
from ..osutil import clip, shell_quote
from ..store import lock_file, unlock_file
from ..terminals.events import WAIT_POLL


def _land_lock_active(ctx: Context, repo: str) -> bool:
    """True when `pm.py land` holds the project's merge lock (`locks/land-<slug>.lock`)."""
    if not repo:
        return False
    path = ctx.home.lock(f"land-{project_slug(repo)}")
    if not path.exists():
        return False
    try:
        with open(path, "a+") as f:
            try:
                lock_file(f)
            except OSError:
                return True
            with contextlib.suppress(OSError):
                unlock_file(f)
            return False
    except OSError:
        return False


@dataclass(frozen=True)
class WaitResult:
    """Structured report returned when a worker reports in the ledger."""

    task_id: str
    status: str
    commit: str
    summary_line: str
    ahead: int | None
    dirty: int | None
    lines: tuple[str, ...]


def wait_for_report_for(ctx: Context, task_id: str, *, timeout: float = 3600) -> WaitResult:
    """Wait until `task_id`'s worker reports in the ledger; raises `WaitOutcome` (code 2 or 3) on timeout/stop."""
    task = Ledger(ctx).load(task_id).raw
    term = hc_terminal_of(task)
    # A file notification also observes direct/older writers, not just cmd_update.
    with ctx.hc.change_waiter(
        [ctx.home.tasks],
        ["--terminal", term] if term else None,
        files=[ctx.home.task(task_id)],
    ) as changes:
        return wait_for_report_events_for(ctx, task_id, changes, task, timeout=timeout)


def wait_for_report_events_for(
    ctx: Context,
    task_id: str,
    changes: Any,
    task: Any,
    *,
    timeout: float = 3600,
) -> WaitResult:
    """Wait until the worker reports in the ledger; returns `WaitResult` or raises `WaitOutcome` (code 2 or 3)."""
    raw_initial = task.raw if isinstance(task, Task) else task
    ledger = Ledger(ctx)
    deadline = ctx.clock.monotonic() + timeout
    stopped_at: float | None = None
    last: tuple[str, str] = ("", "")
    seen = len(raw_initial.get("log") or []) if raw_initial["status"] != "in_progress" else None
    while True:
        try:
            cur = ledger.load(task_id).raw
        except (OSError, ValueError):
            # A Windows rename can briefly deny reads; direct/older writers may
            # still be writing JSON when the notification arrives.
            if ctx.clock.monotonic() >= deadline:
                raise WaitOutcome(f"{task_id}: task could not be read before the wait timeout.", code=2, stream="stdout")
            changes.wait(min(.1, max(0, deadline - ctx.clock.monotonic())))
            continue
        if cur["status"] != "in_progress" and (seen is None or len(cur.get("log") or []) > seen):
            latest = (cur.get("log") or [{}])[-1]
            ahead, dirty = ctx.git.git_state(cur.get("worktree") or cur["repo"], cur.get("branch"), cur["base"])
            header = f"{cur['id']}: {cur['status']}" + (f" (commit {cur['commit']})" if cur.get("commit") else "")
            summary = clip(f"{latest.get('at', '')} {latest.get('by', '')}: {latest.get('text', '')}", REPORT_WIDTH)
            state_line = f"ahead={ahead} dirty={dirty}"
            return WaitResult(
                task_id=cur["id"],
                status=cur["status"],
                commit=str(cur.get("commit") or ""),
                summary_line=summary,
                ahead=ahead,
                dirty=dirty,
                lines=(header, summary, state_line),
            )
        # A duplicate snapshot/file event is not a second observation five
        # seconds later. Give a report on its way the full grace period.
        term = hc_terminal_of(cur)
        if hasattr(changes, "follow"):
            changes.follow(["--terminal", term] if term else None)  # reattached or escalated: the new terminal
        land_approved = cur.get("land_approved")
        land_executor = land_approved.get("executor") if isinstance(land_approved, dict) else ""
        if land_approved and land_executor in ("helper", "manual"):
            state = ""
        else:
            state = ctx.hc.worker_state(term)
            if state in ("idle", "done"):
                info = getattr(ctx.hc, "last_worker_info", None)
                if info is None and term:
                    info = ctx.hc.get_raw(term)
                if (info and ctx.procs.background_work(info)) or (
                    land_approved and _land_lock_active(ctx, cur.get("repo") or "")
                ):
                    state = ""
        at = ctx.clock.monotonic()
        if not state:
            stopped_at, last = None, ("", "")
        elif (term, state) != last:
            stopped_at, last = at, (term, state)
        if state and stopped_at is not None and at - stopped_at >= WAIT_POLL:
            if state in ("exited", "removed"):
                msg = ctx.config.tr(
                    f"{task_id}: the worker's terminal hc:{term} has {state} without reporting.",
                    f"{task_id}：worker 的终端 hc:{term} 已{'退出' if state == 'exited' else '被移除'}，没有汇报。",
                )
            elif state in ("blocked", "error"):
                msg = ctx.config.tr(
                    f"{task_id}: the worker is {state} (a prompt it waits on, or an error) and has not reported. "
                    f"It cannot report from there: read its screen (`hc read {term} | tail -40`).",
                    f"{task_id}：worker 处于 {state}（在等一个提示，或出错了），没有汇报。它在那里没法汇报："
                    f"看一下它的屏幕（`hc read {term} | tail -40`）。",
                )
            else:
                cmd = ctx.procs.pm_command()
                remind = ctx.config.tr(
                    f"[from {ctx.pane or 'the PM'}] Report in the ledger as your brief says: "
                    f"`{cmd} update {task_id} --status review|blocked --note \"...\"`",
                    f"[from {ctx.pane or 'PM'}] 请按任务书末尾的说明在台账里汇报：`{cmd} update {task_id} "
                    "--status review|blocked --note \"...\"`",
                )
                msg = (
                    ctx.config.tr(
                        f"{task_id}: the worker stopped ({state}) without reporting. Remind it:",
                        f"{task_id}：worker 停了（{state}）但没有汇报。提醒它：",
                    )
                    + f"\nhc send {term} {shell_quote(remind)}"
                )
            raise WaitOutcome(msg, code=3, stream="stdout")
        if ctx.clock.monotonic() >= deadline:
            raise WaitOutcome(
                ctx.config.tr(
                    f"{task_id}: no new report after {timeout} s; wait again.",
                    f"{task_id}：{timeout} 秒后仍没有新的汇报，接着等。",
                ),
                code=2,
                stream="stdout",
            )
        remaining = max(0, deadline - ctx.clock.monotonic())
        grace = max(0, WAIT_POLL - (ctx.clock.monotonic() - stopped_at)) if stopped_at is not None else remaining
        changes.wait(min(remaining, grace))


@contextlib.contextmanager
def waiting_on_for(ctx: Context, task_id: str) -> Iterator[None]:
    """While `pm.py wait` runs, waits/<task>.json says so."""
    path = ctx.home.waits / f"{task_id}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"task": task_id, "by": ctx.pane, "pid": os.getpid(), "since": ctx.clock.now()}) + "\n")
    except OSError:
        pass
    try:
        yield
    finally:
        try:
            if json.loads(path.read_text()).get("pid") == os.getpid():
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass


def waited_tasks_for(ctx: Context, tasks: list[dict[str, Any]], rec: dict[str, Any]) -> list[dict[str, Any]]:
    """The tasks a PM taking over waits on in the background."""
    own = {rec.get("pane"), (rec.get("previous") or {}).get("pane")} - {None, ""}
    waits = ctx.home.waits
    left = {p.stem for p in waits.glob("*.json")} if waits.is_dir() else set()
    return [
        t for t in tasks if t["status"] in ("in_progress", "review", "blocked") and (
            (t["status"] == "in_progress" and t.get("pane") and t.get("agent") and t["pane"] not in own)
            or t["id"] in left
        )
    ]


# --- Legacy module-level shims (Stages 1-5 compatibility) ---


@contextlib.contextmanager
def waiting_on(task_id: str) -> Iterator[None]:
    with waiting_on_for(Context.from_env(), task_id):
        yield


def waited_tasks(tasks: list[dict[str, Any]], rec: dict[str, Any]) -> list[dict[str, Any]]:
    return waited_tasks_for(Context.from_env(), tasks, rec)
