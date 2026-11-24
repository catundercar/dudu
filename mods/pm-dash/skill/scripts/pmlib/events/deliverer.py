"""The deliverer itself (`pm.py deliver`, one per project): `Deliverer(ctx, repo)` runs the loop that looks at the PM,
its workers, and injected watchers/holds, and sends the batch once the PM is idle. Layer 3.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable, Iterable

from ..context import Context
from ..home import project_slug
from ..ledger.task import hc_terminal_of
from ..procs import background_work, code_mark
from ..project.conversation import Conversation
from ..project.turn_state import TurnTracker
from .deliver import Delivery
from .policy import manager_ready_for_batch
from .stalls import StallWatcher

DELIVER_PAUSE = 5      # seconds between looks at a PM that is neither working nor ready
DELIVER_GONE = 30      # seconds the PM may be gone (a claim being written, hc restarting) before the deliverer leaves
DELIVER_GAP = 1        # seconds at least between two looks: an agent busy with tools reports its status often
DELIVER_WARN_SECONDS = 900  # seconds an undelivered batch may wait before a one-shot deliver-stall event is logged

_TURN_LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d \[([^\]]+)\] (UserPromptSubmit|Stop):")


def script_mark() -> list[tuple[str, int, int, int]] | None:
    """What tells this code from the code an install puts in its place (`procs.code_mark`); the name tests patch."""
    return code_mark()


_DEFAULT_SCRIPT_MARK = script_mark


class Deliverer(Delivery):
    """Per-project desktop-app event deliverer over an explicit `Context`, with injected `watchers` and `holds`."""

    def __init__(
        self,
        ctx: Context,
        repo: str | Path,
        *,
        watchers: Iterable[Any] | None = None,
        holds: Iterable[Any] | None = None,
        settle: float | None = None,
        pause: float | None = None,
        gone: float | None = None,
        gap: float | None = None,
        warn_seconds: float | None = None,
        script_mark_fn: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(ctx, repo, watchers=watchers, holds=holds, settle=settle)
        self._pause = DELIVER_PAUSE if pause is None else pause
        self._gone = DELIVER_GONE if gone is None else gone
        self._gap = DELIVER_GAP if gap is None else gap
        self._warn_seconds_override = warn_seconds
        self._script_mark_fn = script_mark_fn
        self._stalls = StallWatcher(ctx)
        self._waiting_since: float | None = None
        self._stall_warned: bool = False
        self._bg_sent_stop_offset: int | None = None

    def _warn_seconds(self) -> float:
        if self._warn_seconds_override is not None:
            return float(self._warn_seconds_override)
        raw = self.ctx.config.get("deliver_warn_seconds")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
            return float(raw)
        return float(DELIVER_WARN_SECONDS)

    def _last_turn_stopped(self, term: str) -> tuple[bool, int]:
        """Return `(stopped, stop_offset)` for `hc:{term}` from `turns.log`.
        `stopped` is True iff the most recent hook turn event for this pane is `Stop`."""
        path = self.ctx.home.turn_log
        try:
            size = path.stat().st_size
        except OSError:
            return False, 0
        if size <= 0:
            return False, 0
        if self._bg_sent_stop_offset is not None and size < self._bg_sent_stop_offset:
            self._bg_sent_stop_offset = None  # turns.log was truncated/replaced
        read_from = max(0, size - 65536)
        try:
            with open(path, "rb") as f:
                f.seek(read_from)
                raw = f.read()
        except OSError:
            return False, 0
        pane = f"hc:{term}"
        pos = read_from
        if read_from > 0:
            nl = raw.find(b"\n")
            if nl < 0:
                return False, 0
            pos += nl + 1
            raw = raw[nl + 1:]
        last_event = ""
        last_offset = 0
        for chunk in raw.splitlines(keepends=True):
            pos += len(chunk)
            line = chunk.decode("utf-8", errors="replace").strip()
            m = _TURN_LOG_LINE.match(line)
            if m and m.group(1) == pane:
                last_event = m.group(2)
                last_offset = pos
        return last_event == "Stop", last_offset

    def _note_undelivered(self, term: str, info: dict[str, Any], count: int, due: float, *, held: bool) -> float:
        """Track how long a non-empty batch has waited undelivered and log a one-shot `deliver-stall` event
        once `deliver_warn_seconds` elapses."""
        now_mono = self.ctx.clock.monotonic()
        if self._waiting_since is None:
            self._waiting_since = now_mono
        warn_after = self._warn_seconds()
        if warn_after > 0 and not self._stall_warned:
            elapsed = now_mono - self._waiting_since
            if elapsed >= warn_after:
                self._record_deliver_stall(term, info, count, elapsed, held=held)
                self._stall_warned = True
            else:
                due = min(due, warn_after - elapsed)
        return due

    def _record_deliver_stall(
        self,
        term: str,
        info: dict[str, Any],
        count: int,
        elapsed: float,
        *,
        held: bool,
    ) -> None:
        status = info.get("status") if isinstance(info.get("status"), dict) else {}
        state = str(status.get("state") or "unknown")
        msg = str(status.get("msg") or status.get("message") or "").strip()
        if held:
            detail_en = f"held back (state={state}" + (f", {msg}" if msg else "") + ")"
            detail_zh = f"被扣住（状态={state}" + (f"，{msg}" if msg else "") + "）"
        elif msg:
            detail_en = f"state={state} ({msg})"
            detail_zh = f"状态={state}（{msg}）"
        else:
            detail_en = f"state={state}"
            detail_zh = f"状态={state}"
        mins = max(1, int(elapsed // 60))
        text = self.ctx.config.tr(
            f"{count} pending event(s) undelivered to hc:{term} for {mins} min ({detail_en}).",
            f"有 {count} 条待投递事件已等待 {mins} 分钟未能送达 hc:{term}（{detail_zh}）。",
        )
        Conversation(self.ctx, self.repo).record(
            "event",
            by=f"hc:{term}",
            source="deliver-stall",
            wake=False,
            text=text,
        )

    def current_script_mark(self) -> Any:
        if self._script_mark_fn is not None:
            return self._script_mark_fn()
        if getattr(self.ctx, "_legacy", False) and script_mark is not _DEFAULT_SCRIPT_MARK:
            return script_mark()
        return self.ctx.procs.code_mark()

    def run(self) -> bool:
        """Deliver and watch until the PM is gone (returns False) or an install replaced this script (True).

        It wakes on what can change the answer: a line appended to the log, the registration rewritten (a rotation,
        a claim, an archive), and hc facts about the PM's terminal and the open tasks' workers; a reconciliation
        every RECONCILE s covers missed notifications. While the PM works it waits for its turn to end; hc holds a
        send back while the user has an unsent draft in that terminal."""
        script, seen, d = self.current_script_mark(), None, self._project_dir()
        rec_path = self.ctx.home.registration(project_slug(self.repo))
        self.start_mark(self._projects.app_pm(self.repo))
        stops: dict[Any, Any] = {}
        bases: dict[Any, Any] = {}
        gone: float | None = None
        failed = 0
        looked = 0.0
        # tasks/: a task file saved after its log line (a commit, a new worker to watch) wakes it too.
        with self.ctx.hc.change_waiter(
            [d, self.ctx.home.registrations, self.ctx.home.root],
            [],
            files=[d / "conversation.jsonl", rec_path, self.ctx.home.turn_log],
            terminals=set(),
            folders=[self.ctx.home.tasks],
        ) as changes:
            while True:
                pause = max(0.0, self._gap - (self.ctx.clock.monotonic() - looked))
                if pause:
                    self.ctx.clock.sleep(pause)
                looked = self.ctx.clock.monotonic()
                now_mark = self.current_script_mark()
                if script and now_mark and now_mark != script:
                    if now_mark == seen:
                        return True
                    seen = now_mark
                    changes.wait(min(self._gap, 1.0) if self._gap > 0 else 1.0)
                    continue
                else:
                    seen = None
                if not self.ctx.home.root.is_dir():
                    return False  # the ledger home is gone
                try:
                    timeout = self.look(changes, stops, bases)
                    failed = 0
                except Exception:  # noqa: BLE001 - a half-written file, a removed task (PmError/NotFound), or
                    # an hc that does not answer costs one look
                    failed += 1
                    if failed >= 12:
                        return False
                    timeout = self._pause
                if timeout is None:  # no PM to deliver to now
                    gone = gone or self.ctx.clock.monotonic()
                    if self.ctx.clock.monotonic() - gone >= self._gone:
                        return False
                    timeout = self._pause
                else:
                    gone = None
                changes.wait(timeout)

    def look(self, changes: Any, stops: dict[Any, Any], bases: dict[Any, Any] | None = None) -> float | None:
        """One look: the PM, the workers, then the batch. Returns how long to wait for a change before the next
        look, or None when there is no PM to deliver to (no registration, archived, not a desktop-app terminal,
        not live)."""
        rec = self._projects.app_pm(self.repo)
        if not rec:
            return None
        term = rec["terminal"]
        tasks = [t.raw for t in self._ledger.project_tasks(self.repo) if self._stalls.watched_worker(t.raw)]
        # Follow the terminals before looking at them: a change between the look and the follow would wake nobody.
        changes.terminals = {term, *(hc_terminal_of(t) for t in tasks), *self.watched_terminals()}
        extra_files = self.watched_files()
        if extra_files and hasattr(changes, "files") and isinstance(getattr(changes, "files", None), (list, set)):
            d = self._project_dir()
            rec_path = self.ctx.home.registration(project_slug(self.repo))
            base_files = [d / "conversation.jsonl", d / "pm-turn.json", rec_path, self.ctx.home.turn_log, *extra_files]
            changes.files = list(dict.fromkeys(base_files))
        info = self.ctx.hc.get_raw(term, errors=True)
        if not info or info.get("state") != "live" or not self._projects.seat_says_alive(self.repo, rec, info):
            return None
        tracker = TurnTracker(self.ctx, self.repo)
        due = self._stalls.watch_workers(tasks, stops, {} if bases is None else bases)
        due = self.watchers_look(stops, bases, due)  # helpers, agy transcript, then dependencies (injected watchers)
        outbox_due = tracker.drain_outbox_and_check_stall(term, info)
        if outbox_due is not None:
            due = min(due, outbox_due)
        start, end, items = self.pending_batch(settle=True)
        log = self._project_dir() / "conversation.jsonl"
        if log.exists() and log.stat().st_size > end:
            due = min(due, self._settle or self._pause)  # lines written just now: judged once they settle
        if not items:
            self._waiting_since = None
            self._stall_warned = False
            self.advance_delivered(end)
            return due
        state = (info.get("status") or {}).get("state")
        if state in ("idle", "done"):
            self._bg_sent_stop_offset = None
        stopped, stop_offset = self._last_turn_stopped(term)
        turn_state_stopped = tracker.is_turn_stopped(term)
        if not stopped and turn_state_stopped:
            stopped = True
            stop_offset = int(tracker.read().get("turn_seq") or 0)
        if self._bg_sent_stop_offset is not None and stop_offset <= self._bg_sent_stop_offset:
            stopped = False  # working-mode started:true is immediate; wait for a fresh Stop before sending again
        has_bg_work = False
        if state == "working" and stopped:
            fg_pid = int((info.get("foreground") or {}).get("pid") or info.get("pid") or 0)
            if fg_pid > 0:
                has_bg_work = bool(background_work(fg_pid))
        ready, if_idle = manager_ready_for_batch(info, stopped, bg_work=has_bg_work)
        held = self.is_held_back()
        if not ready or held:
            return self._note_undelivered(term, info, len(items), due, held=held)
        # hc holds a send back while the user has an unsent draft there. `--if idle`: if the user sends that draft
        # meanwhile, these events ride with the user's turn (bring_pending) and nothing is typed into the working PM.
        # A PM that is `done` (its turn ended while nobody looked at it; hc's --if knows idle and working only) or
        # `working` solely due to background shells after its Stop hook has fired gets the send without `--if idle`.
        sent = self.ctx.hc.send(
            term,
            self.batch_text(start, end, items),
            if_state="idle" if if_idle else None,
            timeout=180,
        ) or {}
        # Sent to the PM that is still the project's (a rotation may have moved it while the send waited for a draft).
        # Only the outbound cursor moves here; the PM's hook records receipt separately so a fast send never looks like a repeat.
        if sent.get("started") and (self._projects.app_pm(self.repo) or {}).get("terminal") == term:
            self._waiting_since = None
            self._stall_warned = False
            _, post_stop_offset = self._last_turn_stopped(term)
            if not if_idle:
                self._bg_sent_stop_offset = max(stop_offset, post_stop_offset)
            self.advance_delivered(end)
            return 0
        self._note_undelivered(term, info, len(items), self._pause, held=False)
        return self._pause


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def deliver_batches(repo: str | Path) -> bool:
    return Deliverer(Context.from_env(), repo).run()


def deliver_look(repo: str | Path, changes: Any, stops: dict[Any, Any], bases: dict[Any, Any] | None = None) -> float | None:
    return Deliverer(Context.from_env(), repo).look(changes, stops, bases)
