"""Work rounds and worker stall detection: tracking when a round starts, recognizing stopped or gone workers, and
recording stall events for the PM. Layer 3.
"""
from __future__ import annotations

import contextlib
import datetime
from pathlib import Path
from typing import Any

from ..agents.base import HOOKED_KINDS, terminal_kind
from ..context import Context
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..ledger.task import hc_terminal_of, pm_started
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..store import lock_file, unlock_file
from ..terminals.events import RECONCILE
from ..terminals.screen import classify_stuck_screen, known_prompt_action
from .deliver import Delivery, deliver_later  # noqa: F401 - kept bound for test_deliver_guard patch propagation

STALL_GRACE = 5        # seconds a worker stays stopped before that counts (a report may be on its way)
ROUND_START = 180  # seconds a worker may take to start up before it is watched though its work was never handed over
REPORTED_STATUSES = frozenset({"review", "blocked", "done", "merged", "released", "abandoned"})


def worker_hooked(task: dict[str, Any], info: dict[str, Any] | None) -> bool:
    """Whether the worker's agent has a Stop hook that reports it stopping unreported (`worker_stopped`)."""
    kind = (task.get("worker") or {}).get("kind") if isinstance(task.get("worker"), dict) else None
    return (kind or task.get("kind") or terminal_kind(info or {})) in HOOKED_KINDS


def stop_state(
    info: dict[str, Any] | None,
    hooked: bool,
    base: int = 0,
    *,
    background_active: bool = False,
) -> str:
    """Why a worker in a herdr-core terminal cannot report, from `hc get`: "gone" (exited or removed, or an agent
    that reported a status and has none now: it exited and the shell it was started from is back, as under a
    launcher), "blocked" or "error" (a prompt it waits on), "idle" (an agent without hooks that ended a turn after
    this round's work was handed over at turn count `base`, and stopped); "" while it works (including when an
    idle/done terminal still has background child commands), and when nothing is known."""
    if not info:
        return ""
    if (info.get("error") or {}).get("kind") == "not_found" or (not info.get("error") and info.get("state") != "live"):
        return "gone"
    if info.get("error"):
        return ""
    if info.get("reported") and not info.get("status"):
        return "gone"
    state = (info.get("status") or {}).get("state")
    if state in ("blocked", "error"):
        return state
    if state in ("idle", "done") and not hooked and (info.get("turn") or 0) > base:
        return "" if bool(background_active) else "idle"
    return ""


class StallWatcher:
    """Work-round tracking and worker stall detection over an explicit `Context` (zero globals, zero prints)."""

    def __init__(self, ctx: Context, *, stall_grace: float | None = None) -> None:
        self.ctx = ctx
        self._stall_grace = STALL_GRACE if stall_grace is None else stall_grace
        self._ledger = Ledger(ctx)
        self._projects = ProjectRegistry(ctx)

    def round_starts(self, task: dict[str, Any], term: str, handed: bool = True, turn: int | None = None) -> None:
        """A round of work begins for the task's worker in herdr-core terminal `term`."""
        if handed and turn is None:
            turn = (self.ctx.hc.get_raw(term) or {}).get("turn") or 0
        task["round"] = {"terminal": term, "at": self.ctx.clock.now(), "turn": turn if handed else None}

    def round_sent(self, task_id: str, term: str, sent: Any, seen: dict[str, Any]) -> Any:
        """`round_handed` after a send, whatever came of it; returns what the send returned."""
        self.round_handed(task_id, term, seen.get("turn") if sent else None)
        return sent

    def round_handed(self, task_id: str, term: str, turn: int | None = None) -> None:
        """The work was handed over (`turn`: the count seen right before it went in), or the attempt is over."""
        if turn is None:
            turn = (self.ctx.hc.get_raw(term) or {}).get("turn") or 0

        def _set_round(cur: Any, _ch: Any) -> Any:
            self.round_starts(cur.raw, term, turn=turn)
            return cur

        self._ledger.change(task_id, _set_round)

    def round_base(
        self,
        task: dict[str, Any],
        term: str,
        info: dict[str, Any] | None,
        bases: dict[tuple[str, str], int],
    ) -> int | None:
        """The turn count this round's work was handed over at, or None while the worker starts up."""
        r = task.get("round") if isinstance(task.get("round"), dict) else {}
        if r.get("terminal") == term:
            if r.get("turn") is not None:
                return r["turn"]
            if self.ctx.clock.seconds_since(r.get("at")) < ROUND_START:
                return None
        return bases.setdefault((task["id"], term), (info or {}).get("turn") or 0)

    def _land_approved(self, task: dict[str, Any] | None) -> dict[str, Any] | None:
        la = (task or {}).get("land_approved")
        return la if isinstance(la, dict) else None

    def _land_delegated_away(self, task: dict[str, Any] | None) -> bool:
        la = self._land_approved(task)
        return bool(la and la.get("executor") in ("helper", "manual"))

    def _land_lock_active(self, repo: str | Path | None) -> bool:
        if not repo:
            return False
        path = self.ctx.home.lock(f"land-{project_slug(repo)}")
        if not path.exists():
            return False
        try:
            with open(path, "a+") as f:
                lock_file(f)
                unlock_file(f)
        except OSError:
            return True
        return False

    def watched_worker(self, task: dict[str, Any]) -> bool:
        """A task whose worker the deliverer watches."""
        term = hc_terminal_of(task)
        since = (self.ctx.clock.datetime_now() - datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
        landed = task.get("landed")
        landed_done_worker = bool(landed) and not (isinstance(landed, dict) and landed.get("by_worker"))
        return bool(term) and "/" not in term and pm_started(task) and task.get("status") == "in_progress" \
            and not task.get("retired") and not landed_done_worker and not self._land_delegated_away(task) \
            and not str(task.get("switching") or "") > since

    def watch_workers(
        self,
        tasks: list[dict[str, Any]],
        stops: dict[Any, Any],
        bases: dict[Any, Any] | None = None,
    ) -> float:
        """Record a stall for each watched worker that stopped after it was handed this round's work and has stayed
        stopped for STALL_GRACE s without a report. Returns the seconds until the next of them is due."""
        now_, due, seen = self.ctx.clock.monotonic(), float(RECONCILE), set()
        bases = {} if bases is None else bases
        active_ids = {t["id"] for t in tasks}
        for key in [k for k in bases if k[0] not in active_ids]:
            del bases[key]  # no longer watched: a new round, when it comes back, counts from then
        for task in tasks:
            if task.get("status") in REPORTED_STATUSES:
                continue
            if self._land_delegated_away(task):
                continue
            if self._land_approved(task) and self._land_lock_active(task.get("repo")):
                continue
            term = hc_terminal_of(task)
            info = self.ctx.hc.get_raw(term, errors=True)
            base = self.round_base(task, term, info, bases)
            bg = (
                bool(self.ctx.procs.background_work(info))
                if info and (info.get("status") or {}).get("state") in ("idle", "done")
                else False
            )
            state = "" if base is None else stop_state(info, worker_hooked(task, info), base, background_active=bg)
            if not state:
                continue
            seen.add(task["id"])
            # A new key is a new stop: another terminal, another state, or a turn since the last one.
            key = f"{term}:gone" if state == "gone" else f"{term}:{state}:{(info or {}).get('turn') or 0}"
            known = stops.get(task["id"])
            if not known or known[0] != key:
                stops[task["id"]] = (key, now_, False)
                due = min(due, self._stall_grace)
                continue
            if known[2]:
                continue
            if now_ - known[1] < self._stall_grace:
                due = min(due, self._stall_grace - (now_ - known[1]))
                continue
            fresh = self._ledger.load(task["id"]).raw  # it may have reported in the grace, or been handed new work
            base = self.round_base(fresh, term, info, bases)
            if (fresh.get("status") == "in_progress" and hc_terminal_of(fresh) == term and base is not None
                    and not self._land_delegated_away(fresh)
                    and not (self._land_approved(fresh) and self._land_lock_active(fresh.get("repo")))
                    and (state != "idle" or ((info or {}).get("turn") or 0) > base)):
                screen = self.ctx.hc.read(term) if state != "gone" else ""
                if state in ("blocked", "error") and screen:
                    pkind, keys = known_prompt_action(
                        screen, allow_trust=self.ctx.git.is_owned_worktree(fresh.get("worktree"))
                    )
                    auto_key = ("auto", fresh["id"], term, pkind)
                    if keys and stops.get(auto_key, 0) < 2 and self.ctx.hc.keys(term, *keys) is not None:
                        stops[auto_key] = stops.get(auto_key, 0) + 1
                        stops.pop(task["id"], None)
                        msg = self.ctx.config.tr(
                            f"harness auto-handled {pkind} prompt in hc:{term}",
                            f"harness 自动处理了 hc:{term} 的 {pkind} 提示",
                        )
                        with contextlib.suppress(Exception):
                            self._ledger.change(
                                fresh["id"],
                                lambda cur, ch, m=msg: (ch.note(m, source="harness", wake=False), cur)[1],
                                board=False,
                            )
                        due = min(due, self._stall_grace)
                        continue
                diag = classify_stuck_screen(screen) if screen else None
                self.stalled(fresh, self.stall_text(term, state, task_id=fresh["id"], diag=diag), key=key)
            stops[task["id"]] = (key, known[1], True)
        for task_id in list(stops):
            if not isinstance(task_id, tuple):
                if task_id not in seen:
                    del stops[task_id]
            elif len(task_id) == 4 and task_id[0] == "auto" and task_id[1] not in active_ids:
                del stops[task_id]
        return due

    def stall_text(self, term: str, state: str, task_id: str = "", diag: dict[str, Any] | None = None) -> str:
        tr = self.ctx.config.tr
        tid = task_id or "<id>"
        if state == "gone":
            return tr(f"the worker's terminal hc:{term} is gone; it did not report. "
                      f"Reattach (`pm.py reattach {tid}`) or dispatch again.",
                      f"worker 的终端 hc:{term} 已经不在了，没有汇报。用 `pm.py reattach {tid}` 恢复或重新派发。")
        kind = (diag or {}).get("kind") or ""
        excerpt = (diag or {}).get("summary") or ""
        tail = f" ({excerpt})" if excerpt else ""
        tail_zh = f"（{excerpt}）" if excerpt else ""
        if kind == "quota":
            return tr(f"the worker in hc:{term} hit a quota/rate limit{tail}. "
                      f"Switch profile/model (`pm.py escalate {tid} --profile <p>`) or ask the user.",
                      f"hc:{term} 的 worker 遇到配额/限流错误{tail_zh}。用 `pm.py escalate {tid} --profile <档位>` 换模型，或问用户。")
        if kind == "auth":
            return tr(f"the worker in hc:{term} needs re-authentication{tail}. Ask the user to log in.",
                      f"hc:{term} 的 worker 需要重新登录/鉴权{tail_zh}。请用户登录。")
        if kind in ("hook_review", "mcp", "permission", "trust", "update"):
            return tr(f"the worker in hc:{term} is waiting on a {kind} prompt{tail}. "
                      f"Delegate inspection/unblocking with `pm.py triage {tid}` (helper) or ask the user.",
                      f"hc:{term} 的 worker 卡在 {kind} 提示{tail_zh}。用 `pm.py triage {tid}` 交 helper 处理，或问用户。")
        if state == "idle":
            return tr(f"the worker in hc:{term} stopped without reporting (an agent without hooks){tail}. "
                      f"Nudge async with `pm.py update {tid} --status in_progress --note \"...\" --send` or delegate inspection with `pm.py triage {tid}`.",
                      f"hc:{term} 的 worker 停了且没有汇报（无钩子 agent）{tail_zh}。"
                      f"用 `pm.py update {tid} --status in_progress --note \"...\" --send` 异步催它，或用 `pm.py triage {tid}` 交 helper 排查。")
        return tr(f"the worker in hc:{term} is {state}{tail} and cannot report from there. "
                  f"Delegate inspection/unblocking with `pm.py triage {tid}` (helper).",
                  f"hc:{term} 的 worker 处于 {state}{tail_zh}，无法自行汇报。用 `pm.py triage {tid}` 交 helper 排查处理。")

    def worker_stopped(self, data: dict[str, Any]) -> dict[str, str] | None:
        """Stop hook of a session that is no PM. Returns a Claude Code Stop-hook JSON block payload when the
        worker should be nudged to report before stopping, or None (never prints directly)."""
        if not self.ctx.hc_terminal or data.get("background_tasks"):
            return None
        task = next((t for t in self._ledger.raw_tasks() if t.get("pane") == self.ctx.pane and pm_started(t)
                     and t.get("status") == "in_progress"), None)
        if not task or not self._projects.app_pm(task.get("repo")):
            return None
        if self._land_approved(task):
            return None
        if self.ctx.env.get("CLAUDE_CODE_SESSION_ID") and not data.get("stop_hook_active"):
            cmd = self.ctx.procs.pm_command()
            return {"decision": "block", "reason": self.ctx.config.tr(
                f"Report in the ledger as your brief says before you stop: `{cmd} update {task['id']} "
                "--status review|blocked --note \"...\"`",
                f"停下之前请按任务书末尾的说明在台账里汇报：`{cmd} update {task['id']} "
                "--status review|blocked --note \"...\"`",
            )}
        turn = (self.ctx.hc.get_raw(self.ctx.hc_terminal) or {}).get("turn") or 0
        self.stalled(task, self.ctx.config.tr("the worker stopped without reporting", "worker 停了，没有汇报"),
                     key=f"{self.ctx.hc_terminal}:stop:{turn}")
        return None

    def stalled(self, task: dict[str, Any], text: str, key: str | None = None) -> None:
        """Record that the worker of `task` cannot report (a `stall` event) and have the PM told; once per stall.
        Never records a stall for a task that has already reported (review/blocked/done or closed)."""
        if task.get("status") in REPORTED_STATUSES or self._land_delegated_away(task):
            return
        cur = self.ctx.store.task(task["id"]) if task.get("id") else None
        if isinstance(cur, dict) and (cur.get("status") in REPORTED_STATUSES or self._land_delegated_away(cur)):
            return
        conv = Conversation(self.ctx, task["repo"])
        last = next((e for e in reversed(conv.events()) if e.get("task") == task["id"]), {})
        if last.get("type") == "stall" and last.get("key") == key:
            return
        conv.record("stall", task=task["id"], title=task.get("title"), status=task.get("status"),
                    by=task.get("pane") or "", text=text, source="harness", wake=True,
                    **({"key": key} if key else {}))
        Delivery(self.ctx, task["repo"]).ensure_running()

    def sweep_exited(self, repo: str | Path) -> None:
        """At the end of a PM's turn: a dispatched worker whose terminal is gone while its task is still
        in_progress will never report, and no hook of its own says so."""
        for task in self._ledger.project_tasks(repo):
            term = hc_terminal_of(task.raw)
            if term and pm_started(task.raw) and task.get("status") == "in_progress" \
                    and not self._land_delegated_away(task.raw) \
                    and self.ctx.hc.worker_state(term) in ("exited", "removed"):
                self.stalled(task.raw, self.stall_text(term, "gone", task_id=task["id"]), key=f"{term}:gone")


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def round_starts(task: dict[str, Any], term: str, handed: bool = True, turn: int | None = None) -> None:
    StallWatcher(Context.from_env()).round_starts(task, term, handed=handed, turn=turn)


def round_sent(task_id: str, term: str, sent: Any, seen: dict[str, Any]) -> Any:
    return StallWatcher(Context.from_env()).round_sent(task_id, term, sent, seen)


def round_handed(task_id: str, term: str, turn: int | None = None) -> None:
    StallWatcher(Context.from_env()).round_handed(task_id, term, turn=turn)


def round_base(task: dict[str, Any], term: str, info: dict[str, Any] | None, bases: dict[Any, Any]) -> int | None:
    return StallWatcher(Context.from_env()).round_base(task, term, info, bases)


def watched_worker(task: dict[str, Any]) -> bool:
    return StallWatcher(Context.from_env()).watched_worker(task)


def watch_workers(tasks: list[dict[str, Any]], stops: dict[Any, Any], bases: dict[Any, Any] | None = None) -> float:
    return StallWatcher(Context.from_env()).watch_workers(tasks, stops, bases)


def stall_text(term: str, state: str, task_id: str = "", diag: dict[str, Any] | None = None) -> str:
    return StallWatcher(Context.from_env()).stall_text(term, state, task_id=task_id, diag=diag)


def worker_stopped(data: dict[str, Any]) -> dict[str, str] | None:
    ctx = Context.from_env()
    block = StallWatcher(ctx).worker_stopped(data)
    if block is not None:
        ctx.out.json(block)
    return block


def stalled(task: dict[str, Any], text: str, key: str | None = None) -> None:
    StallWatcher(Context.from_env()).stalled(task, text, key=key)


def sweep_exited(repo: str | Path) -> None:
    StallWatcher(Context.from_env()).sweep_exited(repo)
