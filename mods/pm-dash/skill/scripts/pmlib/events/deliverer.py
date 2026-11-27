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
from ..messaging.address import LogicalAddress, parse_legacy_endpoint
from ..messaging.envelope import P4_BATCH, Envelope, extract_env_id, new_env_id
from ..messaging.principal import Principal
from ..messaging.router import DELIVER_UNKNOWN_WAIT, EndpointSnapshot, evaluate_batch_readiness
from ..osutil import unfailing
from ..procs import code_mark
from ..project.conversation import Conversation
from ..project.turn_reducer import incident_holds_batch, record_endpoint
from ..project.turn_state import TurnTracker
from ..terminals.screen import classify_stuck_screen
from .deliver import Delivery
from .stalls import StallWatcher
from .supervisor import HEARTBEAT_INTERVAL_S, EndpointDriver, ProjectSupervisor, _status_parts, touch_heartbeat

DELIVER_PAUSE = 5      # seconds between looks at a PM that is neither working nor ready
DELIVER_GONE = 30      # seconds the PM may be gone (a claim being written, hc restarting) before the deliverer leaves
DELIVER_GAP = 1        # seconds at least between two looks: an agent busy with tools reports its status often
DELIVER_WARN_SECONDS = 900  # seconds an undelivered batch may wait before a one-shot deliver-stall event is logged

_TURN_LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d \[([^\]]+)\] (UserPromptSubmit|Stop):")
_BLOCKING_DIALOG_KINDS = frozenset({"trust", "update", "hook_review", "mcp", "permission", "quota", "auth"})


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
        unknown_wait: float | None = None,
        script_mark_fn: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(ctx, repo, watchers=watchers, holds=holds, settle=settle)
        self._pause = DELIVER_PAUSE if pause is None else pause
        self._gone = DELIVER_GONE if gone is None else gone
        self._gap = DELIVER_GAP if gap is None else gap
        self._warn_seconds_override = warn_seconds
        self._unknown_wait_override = unknown_wait
        self._script_mark_fn = script_mark_fn
        self._stalls = StallWatcher(ctx)
        self._supervisor = ProjectSupervisor(ctx, repo)
        self._driver = EndpointDriver(ctx, repo)
        self._waiting_since: float | None = None
        self._stall_warned: bool = False
        self._bg_sent_stop_offset: int | None = None
        self._bg_sent_stop_seq: int | None = None

    def _warn_seconds(self) -> float:
        if self._warn_seconds_override is not None:
            return float(self._warn_seconds_override)
        raw = self.ctx.config.get("deliver_warn_seconds")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
            return float(raw)
        return float(DELIVER_WARN_SECONDS)

    def _unknown_wait(self) -> float:
        if self._unknown_wait_override is not None:
            return max(0.0, float(self._unknown_wait_override))
        raw = self.ctx.config.get("deliver_unknown_wait")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
            return float(raw)
        return float(DELIVER_UNKNOWN_WAIT)

    def _turn_log_state(self, term: str) -> tuple[str, int]:
        """Return `("stopped"|"working"|"", offset)` for `hc:{term}` from `turns.log`."""
        path = self.ctx.home.turn_log
        try:
            size = path.stat().st_size
        except OSError:
            return "", 0
        if size <= 0:
            return "", 0
        if self._bg_sent_stop_offset is not None and size < self._bg_sent_stop_offset:
            self._bg_sent_stop_offset = None  # turns.log was truncated/replaced
        read_from = max(0, size - 65536)
        try:
            with open(path, "rb") as f:
                f.seek(read_from)
                raw = f.read()
        except OSError:
            return "", 0
        pane = f"hc:{term}"
        pos = read_from
        if read_from > 0:
            nl = raw.find(b"\n")
            if nl < 0:
                return "", 0
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
        if last_event == "Stop":
            return "stopped", last_offset
        if last_event == "UserPromptSubmit":
            return "working", last_offset
        return "", 0

    def _last_turn_stopped(self, term: str) -> tuple[bool, int]:
        """Return `(stopped, stop_offset)` for `hc:{term}` from `turns.log`.
        `stopped` is True iff the most recent hook turn event for this pane is `Stop`."""
        state, offset = self._turn_log_state(term)
        return state == "stopped", offset

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

    def _undelivered_alert(self, item: Any, alert_env: Any, decision: Any) -> None:
        """`alert.undelivered` to the human channels its route names besides the project view and `pm.py status`
        / `state` (which read the mailbox, the hub's board through `state` too): each `ctx.alert_sinks` entry
        (Discord, when configured), none of which may fail the loop."""
        alert = {**dict(alert_env.body or {}), "targets": list(getattr(decision, "targets", ()) or ()),
                 "kind": item.envelope.kind}
        slug = project_slug(self.repo)
        for sink in tuple(getattr(self.ctx, "alert_sinks", ()) or ()):
            unfailing(sink, slug, self.repo, alert)

    def current_script_mark(self) -> Any:
        if self._script_mark_fn is not None:
            return self._script_mark_fn()
        if getattr(self.ctx, "_legacy", False) and script_mark is not _DEFAULT_SCRIPT_MARK:
            return script_mark()
        return self.ctx.procs.code_mark()

    def _heartbeat_interval(self) -> float:
        cfg = self._supervisor.tracker.turn_config()
        return max(0.5, min(HEARTBEAT_INTERVAL_S, (cfg.heartbeat_stale_ms / 1000.0) / 3.0))

    def _wait_with_heartbeat(self, changes: Any, timeout: float) -> bool:
        """Sleep inside `changes.wait` in short chunks so `pm-turn.beat` stays fresh while idle without polling `hc get`."""
        remaining = max(0.0, float(timeout))
        if remaining <= 0:
            return bool(changes.wait(0))
        deadline = self.ctx.clock.monotonic() + remaining
        while remaining > 0:
            chunk = min(remaining, self._heartbeat_interval())
            if changes.wait(chunk):
                return True
            touch_heartbeat(self._supervisor.tracker.files.pm_turn_beat, float(self.ctx.clock.time()))
            remaining = deadline - self.ctx.clock.monotonic()
        return False

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
            files=[d / "conversation.jsonl", d / "pm-turn.json", d / "pm-turn-journal.jsonl", rec_path],
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
                if timeout > 0:
                    self._wait_with_heartbeat(changes, timeout)
                else:
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
            base_files = [d / "conversation.jsonl", d / "pm-turn.json", d / "pm-turn-journal.jsonl", rec_path, *extra_files]
            changes.files = list(dict.fromkeys(base_files))
        info = self.ctx.hc.get_raw(term, errors=True)
        if not info:
            return None
        seat_dead = info.get("state") == "live" and not self._projects.seat_says_alive(self.repo, rec, info)
        if info.get("state") != "live" or seat_dead:
            eff_info = {**info, "state": "exited"} if seat_dead else info
            st_off, sup_due = self._supervisor.observe_and_reduce(rec, eff_info)
            if (st_off.get("incident") or {}).get("status") in ("open", "recovering"):
                return sup_due or self._pause
            return None
        tracker = TurnTracker(self.ctx, self.repo)
        due = self._stalls.watch_workers(tasks, stops, {} if bases is None else bases)
        due = self.watchers_look(stops, bases, due)  # helpers, agy transcript, then dependencies (injected watchers)
        st_sup, sup_due = self._supervisor.observe_and_reduce(rec, info)
        if sup_due is not None:
            due = min(due, sup_due)
        outbox_due = tracker.drain_outbox_and_check_stall(term, info)
        if outbox_due is not None:
            due = min(due, outbox_due)
        start, end, items = self.pending_batch(settle=True)
        log = self._project_dir() / "conversation.jsonl"
        if log.exists() and log.stat().st_size > end:
            due = min(due, self._settle or self._pause)  # lines written just now: judged once they settle
        # An in-flight send must still be polled (and its typist lease renewed) even when the hook already
        # consumed its envelope and nothing else is pending.
        if not items and not self._driver.has_inflight() and not (
            tracker.files.pm_mailbox.is_dir() and tracker.pm_mailbox.pending_for_endpoint()
        ):
            self._waiting_since = None
            self._stall_warned = False
            self.advance_delivered(end)
            return due

        state = str((info.get("status") or {}).get("state") or "")
        if state in ("idle", "done"):
            self._bg_sent_stop_offset = None
            self._bg_sent_stop_seq = None
        tr_state, tr_seq = tracker.turn_state(term)
        if self._bg_sent_stop_seq is not None and tr_seq < self._bg_sent_stop_seq:
            self._bg_sent_stop_seq = None  # pm-turn.json was reset/replaced
        # 1-version read-only fallback to turns.log only when pm-turn.json has no hook-confirmed turn state (§4.8).
        st_cur = tracker.read() if tr_state == "working" else {}
        use_turn_log_fallback = (not tr_state) or (tr_state == "working" and not st_cur.get("hook_confirmed"))
        log_state, log_offset = self._turn_log_state(term) if use_turn_log_fallback else ("", 0)
        fresh_log_after_send = (
            log_state == "stopped"
            and self._bg_sent_stop_offset is not None
            and log_offset > self._bg_sent_stop_offset
        )
        provisional_deliver = False
        if tr_state == "working" and fresh_log_after_send:
            provisional_deliver = (not st_cur.get("hook_confirmed")) and st_cur.get("cause") == "deliver"
        if log_state == "working" or (tr_state == "working" and not provisional_deliver):
            turn_stopped: bool | None = False
        elif log_state == "stopped" or tr_state == "stopped":
            if self._bg_sent_stop_offset is not None or self._bg_sent_stop_seq is not None:
                fresh_log = log_state == "stopped" and (
                    self._bg_sent_stop_offset is None or log_offset > self._bg_sent_stop_offset
                )
                fresh_tr = tr_state == "stopped" and (
                    self._bg_sent_stop_seq is None or tr_seq > self._bg_sent_stop_seq
                )
                turn_stopped = True if (fresh_log or fresh_tr) else False
            else:
                turn_stopped = True
        else:
            turn_stopped = None
        has_bg_work = False
        if state == "working" and turn_stopped is True:
            has_bg_work = bool(self.ctx.procs.background_work(info))
        unknown_wait = self._unknown_wait()
        waited = 0.0
        blocking_dialog = False
        if state == "" and turn_stopped is None:
            now_mono = self.ctx.clock.monotonic()
            waited = 0.0 if self._waiting_since is None else max(0.0, now_mono - self._waiting_since)
            if waited >= unknown_wait:
                screen = self.ctx.hc.read(term)
                blocking_dialog = bool(
                    screen and classify_stuck_screen(screen)["kind"] in _BLOCKING_DIALOG_KINDS
                )

        t_state, a_state, s_msg, _, _, reported = _status_parts(info)
        v2_phase = str(((st_sup or {}).get("turn") or {}).get("phase") or "")
        ep = record_endpoint(rec) or parse_legacy_endpoint(term, runtime_hint="hc")
        ep_snap = EndpointSnapshot(
            endpoint=ep,
            live_state=t_state or "live",
            agent_state=a_state,
            status_msg=s_msg,
            can_report_status=bool(reported),
            can_interrupt=True,
            link_state="connected",
            turn_phase=(
                "recovering"
                if v2_phase == "recovering"
                else ("idle" if turn_stopped is True else ("generating" if turn_stopped is False else ""))
            ),
            last_turn_stopped=turn_stopped,
            bg_work=has_bg_work,
            blocking_dialog=bool(blocking_dialog or a_state == "blocked"),
            seat_starting=tracker.files.next_session.is_file(),
            recovery_hold=incident_holds_batch(st_sup),
            waited_ms=int(waited * 1000),
        )
        ready, _if_idle, _reason = evaluate_batch_readiness(ep_snap, unknown_wait_ms=int(unknown_wait * 1000))
        held = self.is_held_back()
        if not ready and not held and items and state == "" and turn_stopped is None:
            if waited < unknown_wait:
                due = min(due, max(0.0, unknown_wait - waited))
            elif blocking_dialog:
                due = min(due, self._pause)

        now_ms = int(float(self.ctx.clock.time()) * 1000)
        slug = self._driver.slug
        batch_env_id = ""
        if items:
            queued_batches = [
                it for it in tracker.pm_mailbox.active_items(("accepted",)) if it.envelope.kind == "event.batch"
            ]
            # A batch whose send is in flight or came back uncertain (`intent` set) may already be on the terminal:
            # neither supersede it nor stack a wider batch over it until it settles, or its events are typed twice.
            unsettled = next((it for it in queued_batches if it.intent), None)
            idem_key = f"batch:{slug}:{start}-{end}"
            existing_batch = unsettled if unsettled is not None else tracker.pm_mailbox.get_by_key(idem_key)
            if existing_batch is not None:
                batch_env_id = existing_batch.envelope.env_id
            else:
                # Supersede any older queued batch at the same start offset before enqueueing the wider stretch.
                for old_it in queued_batches:
                    ob = old_it.envelope.body if isinstance(old_it.envelope.body, dict) else {}
                    if int(ob.get("start") or 0) == start and int(ob.get("end") or 0) < end:
                        tracker.pm_mailbox.transition(
                            old_it.envelope.env_id, "superseded", now_ms=now_ms, hold_reason="widened_batch"
                        )
                batch_env_id = new_env_id(now_ms)
                payload_text = self.batch_text(start, end, items, env_id=batch_env_id)
                batch_env = Envelope(
                    env_id=batch_env_id,
                    idempotency_key=idem_key,
                    schema_version=1,
                    created_ms=now_ms,
                    kind="event.batch",
                    sender=Principal.supervisor(slug),
                    recipient=LogicalAddress.pm(slug),
                    project=slug,
                    cause={"kind": "deliver_batch", "start": start, "end": end},
                    priority=P4_BATCH,
                    body={"text": payload_text, "start": start, "end": end},
                    require_reply=True,
                )
                tracker.pm_mailbox.enqueue(
                    batch_env,
                    initial_state="accepted",
                    now_ms=now_ms,
                    target_endpoint_uid=ep.uid if ep is not None else "",
                    endpoint_epoch=int(ep.epoch or 1) if ep is not None else 1,
                )

        typed_events: list[tuple[Any, Any]] = []
        outcome, drv_due = self._driver.drive_pm_endpoint(
            rec,
            info,
            held=held,
            ep_snap_override=ep_snap,
            on_typed=lambda it, out: typed_events.append((it, out)),
            on_undelivered_alert=self._undelivered_alert,
        )
        if items and typed_events and (self._projects.app_pm(self.repo) or {}).get("terminal") == term:
            typed_item, _ = typed_events[0]
            if typed_item.envelope.kind == "event.batch" or (
                batch_env_id and typed_item.envelope.env_id == batch_env_id
            ):
                self._waiting_since = None
                self._stall_warned = False
                # An async send settles on a later look, when `end` may have grown: the cursor moves to the end of
                # the batch that was typed, never past events it did not carry.
                tb = typed_item.envelope.body if isinstance(typed_item.envelope.body, dict) else {}
                t_start = int(tb["start"]) if "start" in tb else start
                t_end = int(tb["end"]) if "end" in tb else end
                if not _if_idle:
                    _, post_tr_seq = tracker.turn_state(term)
                    post_log_offset = self._turn_log_state(term)[1] if use_turn_log_fallback else 0
                    best_log = max(log_offset, post_log_offset)
                    best_seq = max(tr_seq, post_tr_seq)
                    if best_log > 0 or best_seq > 0:
                        self._bg_sent_stop_offset = best_log if best_log > 0 else None
                        self._bg_sent_stop_seq = best_seq if best_seq > 0 else None
                if typed_item.state == "typed":
                    # Not when the hook took the batch while `hc send` was still in flight: it opened the turn.
                    tracker.begin_turn(
                        terminal=term,
                        agent_kind=str(rec.get("agent") or ""),
                        cause="deliver",
                        batch=[t_start, t_end],
                        terminal_turn=int(info.get("turn") or 0),
                        from_hook=False,
                    )
                self.advance_delivered(t_end)
                return 0
            return 0 if drv_due == 0 else min(due, drv_due or due)

        if not items:
            self._waiting_since = None
            self._stall_warned = False
            self.advance_delivered(end)
            return min(due, drv_due) if drv_due is not None else due

        pause_due = drv_due if drv_due is not None else (due if (not ready or held) else self._pause)
        return self._note_undelivered(term, info, len(items), pause_due, held=held)


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def deliver_batches(repo: str | Path) -> bool:
    return Deliverer(Context.from_env(), repo).run()


def deliver_look(repo: str | Path, changes: Any, stops: dict[Any, Any], bases: dict[Any, Any] | None = None) -> float | None:
    return Deliverer(Context.from_env(), repo).look(changes, stops, bases)
