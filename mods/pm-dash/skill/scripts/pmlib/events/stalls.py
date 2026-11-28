"""Work rounds and worker stall detection: tracking when a round starts, recognizing stopped or gone workers, and
recording stall events for the PM. Layer 3.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime
import hashlib
from pathlib import Path
import signal
from typing import Any, Mapping

from ..agents.base import HOOKED_KINDS, terminal_kind
from ..agents.turn_adapters import adapter_for
from ..context import Context
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..ledger.task import hc_terminal_of, pm_started, task_endpoint
from ..messaging.address import Endpoint, parse_legacy_endpoint
from ..messaging.principal import Principal
from ..messaging.transport import Transport
from ..messaging.transports.local_hc import LocalHcTransport
from ..messaging.typist import transport_for, unblock_endpoint
from ..osutil import clip
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..project.turn_reducer import ACTIVE_TURN_PHASES, TurnConfig, worker_turn_config_from_dict
from ..project.turn_state import EndpointTurnStore
from ..store import lock_file, unlock_file
from ..terminals.events import RECONCILE
from ..terminals.screen import classify_stuck_screen, known_prompt_action
from .deliver import Delivery, deliver_later  # noqa: F401 - kept bound for test_deliver_guard patch propagation

STALL_GRACE = 5        # seconds a worker stays stopped before that counts (a report may be on its way)
ROUND_START = 180  # seconds a worker may take to start up before it is watched though its work was never handed over
LAND_APPROVE_TIMEOUT = 300  # seconds a worker-delegated land_approved may sit unmerged before falling back to helper
REPORTED_STATUSES = frozenset({"review", "blocked", "done", "merged", "released", "abandoned"})


def _seconds_since_ts(clock: Any, at: Any) -> float:
    """Seconds since a ledger timestamp ('YYYY-MM-DD HH:MM[:SS]'); inf when unreadable."""
    text = str(at or "").strip()
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
        try:
            when = datetime.datetime.strptime(text[:n], fmt)
            return (clock.datetime_now() - when).total_seconds()
        except ValueError:
            continue
    return float("inf")


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

    def __init__(
        self,
        ctx: Context,
        *,
        stall_grace: float | None = None,
        land_approve_timeout: float | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.ctx = ctx
        self._stall_grace = STALL_GRACE if stall_grace is None else stall_grace
        self._land_approve_timeout_override = land_approve_timeout
        self._injected_transport = transport is not None
        self._transport: Transport = transport if transport is not None else LocalHcTransport(ctx)
        self._ledger = Ledger(ctx)
        self._projects = ProjectRegistry(ctx)
        self._worker_hc_sigs: dict[str, tuple[Any, ...]] = {}
        self._worker_link_sigs: dict[str, str] = {}
        self._worker_screen_state: dict[str, dict[str, Any]] = {}
        self._worker_proc_state: dict[str, dict[str, Any]] = {}


    def _unblock(self, term: str, keys: Any) -> bool | None:
        """Press a known prompt's keys in worker terminal `term`, only while holding its typist lease. None: another
        sender is typing into it right now, so nothing was pressed (look again; that is not a stuck worker)."""
        ep = parse_legacy_endpoint(f"hc:{term}", runtime_hint="hc")
        return False if ep is None else unblock_endpoint(self.ctx, ep, list(keys))
    def _land_approve_timeout(self) -> float:
        if self._land_approve_timeout_override is not None:
            return float(self._land_approve_timeout_override)
        raw = self.ctx.config.get("land_approve_timeout")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
            return float(raw)
        return float(LAND_APPROVE_TIMEOUT)

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

    def _transport_of(self, ep: Any) -> Any:
        """The injected transport (tests), else the endpoint's own: a remote `<machine>/t7` worker goes through
        `RemoteHcTransport`, whose partition answers are `unknown`, never a stall (I4)."""
        if self._injected_transport or not getattr(ep, "machine", None):
            return self._transport
        return transport_for(self.ctx, ep)

    def _land_approved(self, task: dict[str, Any] | None) -> dict[str, Any] | None:
        la = (task or {}).get("land_approved")
        return la if isinstance(la, dict) else None

    def _land_delegated_away(self, task: dict[str, Any] | None) -> bool:
        la = self._land_approved(task)
        return bool(la and (la.get("executor") in ("helper", "manual") or la.get("fallback_at")))

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

    def fallback_land_to_helper(self, task: dict[str, Any], *, reason: str, term: str = "") -> bool:
        """Atomically claim fallback for a stalled/failed worker-delegated `land_approved`, hand it to an exec helper
        as the supervisor (`ctx.land_handoff`: `approve <id> --via helper` in process, preserving the approval
        options), and alert the PM.
        On helper handoff failure, preserves the original `land_approved` (clearing `fallback_at`) and
        reports the concrete error to the PM. Idempotent per `land_approved`."""
        tid = task.get("id") or ""
        if not tid:
            return False
        orig_la = self._land_approved(task)
        if not orig_la or orig_la.get("executor") != "worker" or orig_la.get("fallback_at") or orig_la.get("fallback_failed_at"):
            return False
        expected_at = orig_la.get("at")
        claimed = False
        orig_snapshot: dict[str, Any] = {}
        claimed_la: dict[str, Any] = {}

        def _claim(cur: Any, _ch: Any) -> Any:
            nonlocal claimed, orig_snapshot, claimed_la
            claimed = False
            raw = cur.raw
            if raw.get("status") in REPORTED_STATUSES or raw.get("landed"):
                return cur
            la = self._land_approved(raw)
            if not la or la.get("executor") != "worker" or la.get("fallback_at") or la.get("fallback_failed_at"):
                return cur
            if expected_at and la.get("at") != expected_at:
                return cur
            if self._land_lock_active(raw.get("repo")):
                return cur
            orig_snapshot = dict(la)
            la["fallback_at"] = self.ctx.clock.now_sec()
            la["fallback_reason"] = reason
            claimed_la = dict(la)
            claimed = True
            return cur

        try:
            fresh_task = self._ledger.change(tid, _claim, board=False)
        except Exception:  # noqa: BLE001
            return False
        if not claimed or fresh_task is None:
            return False
        fresh = fresh_task.raw
        repo = fresh.get("repo") or task.get("repo") or ""
        target_term = term or hc_terminal_of(fresh)
        who = f"hc:{target_term}" if target_term else (fresh.get("pane") or "worker")
        rec = self._projects.app_pm(repo) if repo else None
        pm_term = (rec or {}).get("terminal") or ""
        handoff = getattr(self.ctx, "land_handoff", None)
        if pm_term:
            # The supervisor itself hands the approved merge to an exec helper (an explicit Principal, in a context
            # of its own: never a subprocess posing as the PM's terminal through HC_TERMINAL_ID).
            if not callable(handoff):
                handoff_ok, err_detail = False, "no land hand-off wired in this process"
            else:
                try:
                    handoff(tid, dict(claimed_la), Principal.supervisor(project_slug(repo)))
                    handoff_ok, err_detail = True, ""
                except (Exception, SystemExit) as exc:  # noqa: BLE001 - any refusal keeps the original approval
                    handoff_ok, err_detail = False, clip(str(exc), 300)
            if handoff_ok:
                msg = self.ctx.config.tr(
                    f"merge approval for {tid} was not completed by {who} ({reason}); "
                    f"automatically handed off to exec helper (`pm.py approve {tid} --via helper`).",
                    f"{tid} 的合并批准未由 {who} 执行（{reason}）；"
                    f"已自动改交执行 helper（`pm.py approve {tid} --via helper`）。",
                )
            else:
                why_fail = err_detail or "approve --via helper exited non-zero"

                def _restore_on_fail(cur: Any, _ch: Any) -> Any:
                    raw = cur.raw
                    if raw.get("status") in REPORTED_STATUSES or raw.get("landed"):
                        return cur
                    cur_la = self._land_approved(raw)
                    if cur_la and cur_la.get("executor") == "helper":
                        return cur
                    restored = dict(orig_snapshot)
                    restored.pop("fallback_at", None)
                    restored.pop("fallback_reason", None)
                    restored["fallback_failed_at"] = self.ctx.clock.now_sec()
                    restored["fallback_error"] = why_fail
                    raw["land_approved"] = restored
                    return cur

                with contextlib.suppress(Exception):
                    self._ledger.change(tid, _restore_on_fail, board=False)
                msg = self.ctx.config.tr(
                    f"merge approval for {tid} was not completed by {who} ({reason}); "
                    f"automatic helper handoff failed ({why_fail}) — original approval kept; "
                    f"run `pm.py approve {tid} --via helper` or `pm.py land {tid}`.",
                    f"{tid} 的合并批准未由 {who} 执行（{reason}）；"
                    f"自动改交 helper 失败（{why_fail}），已保留原合并授权；"
                    f"请处理后运行 `pm.py approve {tid} --via helper` 或 `pm.py land {tid}`。",
                )
        else:
            msg = self.ctx.config.tr(
                f"merge approval for {tid} was not completed by {who} ({reason}); "
                f"no desktop-app PM terminal available for automatic helper handoff — run `pm.py land {tid}` "
                f"or `pm.py approve {tid} --via helper`.",
                f"{tid} 的合并批准未由 {who} 执行（{reason}）；"
                f"当前没有桌面版 PM 终端可自动转交 helper，请手动运行 `pm.py land {tid}` 或 `pm.py approve {tid} --via helper`。",
            )
        pslug = self.ctx.store.task_project_slug(fresh)
        if repo or pslug:
            key = f"land-approve-stall:{claimed_la.get('at') or ''}"
            conv = Conversation(self.ctx, repo or "", slug=pslug or None)
            last = next((e for e in reversed(conv.events()) if e.get("task") == tid and e.get("type") == "stall"), {})
            if last.get("key") != key:
                conv.record(
                    "stall", task=tid, title=fresh.get("title"), status=fresh.get("status"),
                    by=who, text=msg, source="harness", wake=True, key=key,
                )
            Delivery(self.ctx, repo or "", slug=pslug or None).ensure_running()
        return True

    def watched_worker(self, task: dict[str, Any]) -> bool:
        """A task whose worker the deliverer watches."""
        term = hc_terminal_of(task)
        since = (self.ctx.clock.datetime_now() - datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
        landed = task.get("landed")
        landed_done_worker = bool(landed) and not (isinstance(landed, dict) and landed.get("by_worker"))
        la = self._land_approved(task)
        worker_land = bool(la and la.get("executor") == "worker" and not la.get("fallback_at"))
        return bool(term) and "/" not in term and (pm_started(task) or worker_land) \
            and task.get("status") == "in_progress" \
            and not task.get("retired") and not landed_done_worker and not self._land_delegated_away(task) \
            and not str(task.get("switching") or "") > since

    def _worker_cfg(self, store: EndpointTurnStore, task: Mapping[str, Any]) -> TurnConfig:
        cfg = store.turn_config()
        wt = task.get("worktree")
        allow_trust = bool(cfg.recovery_allow_trust) and bool(wt and self.ctx.git.is_owned_worktree(wt))
        if allow_trust == cfg.recovery_allow_trust:
            return cfg
        return dataclasses.replace(cfg, recovery_allow_trust=allow_trust)

    def _record_auto_unblocked(self, fresh: dict[str, Any], term: str, pkind: str) -> None:
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

    def _worker_task_active_for_term(self, task_id: str, term: str) -> dict[str, Any] | None:
        try:
            fresh = self._ledger.load(task_id).raw
        except Exception:  # noqa: BLE001
            return None
        if (
            fresh.get("status") != "in_progress"
            or hc_terminal_of(fresh) != term
            or self._land_delegated_away(fresh)
            or (self._land_approved(fresh) and self._land_lock_active(fresh.get("repo")))
        ):
            return None
        return fresh

    def _probe_worker_signals(
        self,
        ep: Endpoint,
        store: EndpointTurnStore,
        task: Mapping[str, Any],
        info: Mapping[str, Any] | None,
        state: dict[str, Any],
        cfg: TurnConfig,
        now_ms: int,
    ) -> tuple[bool, list[dict[str, Any]]]:
        term = ep.hc_target or ep.terminal
        turn = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
        phase = str(turn.get("phase") or "idle")
        health = str(turn.get("health") or "ok")
        cur_turn_id = str(turn.get("id") or "")
        started_ms = int(turn.get("started_ms") or 0)
        phase_since_ms = int(turn.get("phase_since_ms") or started_ms)
        step_ev = (turn.get("evidence") or {}).get("step") or {}
        last_step_ms = max(started_ms, int(step_ev.get("last_ms") or 0))
        step_quiet_ms = max(0, now_ms - last_step_ms)
        phase_age_ms = max(0, now_ms - phase_since_ms)
        a_state = str(((info or {}).get("status") or {}).get("state") or "").strip().lower()
        t_state = str((info or {}).get("state") or "").strip().lower()
        worker_obj = task.get("worker") if isinstance(task.get("worker"), Mapping) else {}
        worker_kind = str(worker_obj.get("kind") or task.get("kind") or terminal_kind(dict(info or {})) or "")
        adapter = adapter_for(worker_kind)

        appended = False
        sc_state = self._worker_screen_state.setdefault(
            ep.uid, {"last_ms": 0, "turn_id": "", "digest": "", "changed": None, "hint": "", "dialog": ""}
        )
        screen_interval_ms = 0
        if phase in ACTIVE_TURN_PHASES:
            if health == "suspect" or (phase == "submitted" and phase_age_ms >= cfg.submitted_suspect_ms):
                screen_interval_ms = 1_000
            elif phase == "generating" and step_quiet_ms >= cfg.generating_pty_probe_after_ms:
                screen_interval_ms = cfg.generating_pty_probe_interval_ms
            elif phase == "tool" and phase_age_ms >= cfg.tool_soft_ms:
                screen_interval_ms = 5_000
            elif phase == "waiting_upstream":
                screen_interval_ms = 5_000

        if screen_interval_ms > 0 and t_state == "live" and term and (now_ms - int(sc_state["last_ms"])) >= screen_interval_ms:
            sc_state["last_ms"] = now_ms
            screen_text = self.ctx.hc.read(term)
            if isinstance(screen_text, str):
                digest = hashlib.sha256(screen_text.encode("utf-8", errors="replace")).hexdigest()[:16]
                hint = adapter.screen_hint(screen_text)
                dialog_kind = ""
                if phase == "submitted" or health == "suspect":
                    classified = classify_stuck_screen(screen_text)
                    dk = str(classified.get("kind") or "")
                    if dk and dk != "unknown":
                        dialog_kind = dk
                first_for_turn = sc_state["turn_id"] != cur_turn_id
                changed = first_for_turn or (digest != sc_state["digest"])
                should_emit = (
                    first_for_turn
                    or changed
                    or (changed != sc_state["changed"])
                    or (hint != sc_state["hint"])
                    or (dialog_kind != sc_state["dialog"])
                )
                sc_state["turn_id"] = cur_turn_id
                sc_state["digest"] = digest
                sc_state["changed"] = changed
                sc_state["hint"] = hint
                sc_state["dialog"] = dialog_kind
                if should_emit:
                    store.append_observation(
                        {
                            "src": "probe:pty",
                            "kind": "pty_probe",
                            "t": now_ms,
                            "changed": changed,
                            "digest": digest,
                            "hint": hint,
                            "dialog_kind": dialog_kind,
                        },
                        reduce_now=False,
                        cfg=cfg,
                    )
                    appended = True

        pr_state = self._worker_proc_state.setdefault(ep.uid, {"last_ms": 0, "sig": None})
        need_proc_probe = (
            t_state == "live"
            and info is not None
            and (phase in ("tool", "generating") or (a_state == "working" and (phase == "idle" or bool(step_ev.get("ended")))))
        )
        if need_proc_probe and (now_ms - int(pr_state["last_ms"])) >= 5_000:
            pr_state["last_ms"] = now_ms
            fg_stat = self.ctx.procs.foreground_tool_stat(dict(info))
            bg_cmds = self.ctx.procs.background_work(dict(info))
            tool_pid = int(fg_stat.get("tool_pid") or 0)
            cmd = str(fg_stat.get("cmd") or "")
            cpu_ms = int(fg_stat.get("cpu_ms") or 0)
            sig = (tool_pid, cmd, cpu_ms, tuple(bg_cmds))
            if sig != pr_state["sig"]:
                pr_state["sig"] = sig
                store.append_observation(
                    {
                        "src": "probe:proc",
                        "kind": "proc_probe",
                        "t": now_ms,
                        "tool_pid": tool_pid,
                        "cmd": cmd,
                        "cpu_ms": cpu_ms,
                        "bg_commands": list(bg_cmds),
                    },
                    reduce_now=False,
                    cfg=cfg,
                )
                appended = True

        if not appended:
            return False, []
        new_state, due_actions = store.sync_journal(tick_now=True, now_ms=now_ms, cfg=cfg)
        state.clear()
        state.update(new_state)
        return True, due_actions

    def _try_unblock_safe_prompt(
        self,
        fresh: dict[str, Any],
        term: str,
        stops: dict[Any, Any],
        cfg: TurnConfig,
    ) -> str | None:
        """Auto-press safe confirmation keys (trust in owned worktree / CLI update) if present on screen.
        Returns the prompt kind when unblocked, `\"busy\"` if another typist holds the lease, or None."""
        screen = self.ctx.hc.read(term) if term else ""
        if not screen:
            return None
        allow_trust = self.ctx.git.is_owned_worktree(fresh.get("worktree")) and bool(cfg.recovery_allow_trust)
        pkind, keys = known_prompt_action(screen, allow_trust=allow_trust)
        if not (pkind and keys):
            return None
        auto_key = ("auto", fresh["id"], term, pkind)
        if stops.get(auto_key, 0) >= 2:
            return None
        pressed = self._unblock(term, keys)
        if pressed is None:
            return "busy"
        if not pressed:
            return None
        stops[auto_key] = stops.get(auto_key, 0) + 1
        stops.pop(fresh["id"], None)
        self._record_auto_unblocked(fresh, term, str(pkind))
        return str(pkind)

    def _execute_worker_actions(
        self,
        ep: Endpoint,
        store: EndpointTurnStore,
        task: dict[str, Any],
        info: dict[str, Any] | None,
        state: dict[str, Any],
        due_actions: list[dict[str, Any]],
        stops: dict[Any, Any],
        cfg: TurnConfig,
        now_ms: int,
        *,
        defer_w3: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        term = ep.hc_target or ep.terminal
        actions = [
            a for a in due_actions
            if isinstance(a, Mapping)
            and a.get("kind") == "recovery_action"
            and a.get("action")
            and a.get("action") != "none"
        ]
        if not actions:
            return state, due_actions

        fresh = self._worker_task_active_for_term(task["id"], term)
        if fresh is None:
            return state, due_actions

        for act in actions:
            cls = str(act.get("class") or "")
            action = str(act.get("action") or "")
            inc_id = str(act.get("incident_id") or "")
            stage = int(act.get("stage") or 0)

            if cls == "W3":
                if defer_w3:
                    continue
                if action == "notify_user" or act.get("auto") == "off":
                    unblocked = self._try_unblock_safe_prompt(fresh, term, stops, cfg)
                    if unblocked == "busy":
                        continue
                    if unblocked:
                        store.append_observation(
                            {
                                "src": "supervisor",
                                "kind": "recovery_result",
                                "t": now_ms,
                                "class": "W3",
                                "stage": stage,
                                "action": "unblock_safe_dialog",
                                "outcome": "unblocked",
                                "detail": unblocked,
                            },
                            reduce_now=True,
                            cfg=cfg,
                        )
                        continue
                    screen = self.ctx.hc.read(term) if term else ""
                    diag = classify_stuck_screen(screen) if screen else None
                    dk = str(act.get("dialog_kind") or (diag or {}).get("kind") or "blocked")
                    store.append_observation(
                        {
                            "src": "supervisor",
                            "kind": "recovery_result",
                            "t": now_ms,
                            "class": "W3",
                            "stage": stage,
                            "action": "notify_user",
                            "outcome": "notified",
                            "detail": dk,
                        },
                        reduce_now=True,
                        cfg=cfg,
                    )
                    self.stalled(
                        fresh,
                        self.stall_text(term, "blocked", task_id=fresh["id"], diag=diag),
                        key=f"{term}:w3:{dk}",
                    )
                    continue
                screen = self.ctx.hc.read(term) if term else ""
                allow_trust = self.ctx.git.is_owned_worktree(fresh.get("worktree")) and bool(cfg.recovery_allow_trust)
                pkind, keys = known_prompt_action(screen, allow_trust=allow_trust) if screen else (None, None)
                auto_key = ("auto", fresh["id"], term, pkind)
                if keys and stops.get(auto_key, 0) < 2:
                    pressed = self._unblock(term, keys)
                    if pressed is None:
                        continue
                    store.append_observation(
                        {
                            "src": "supervisor",
                            "kind": "recovery_result",
                            "t": now_ms,
                            "class": "W3",
                            "stage": stage,
                            "action": action,
                            "outcome": "unblocked" if pressed else "failed",
                            "detail": str(pkind or ""),
                        },
                        reduce_now=True,
                        cfg=cfg,
                    )
                    if pressed:
                        stops[auto_key] = stops.get(auto_key, 0) + 1
                        stops.pop(fresh["id"], None)
                        self._record_auto_unblocked(fresh, term, str(pkind))
                else:
                    diag = classify_stuck_screen(screen) if screen else None
                    dk = str(act.get("dialog_kind") or (diag or {}).get("kind") or "unknown")
                    store.append_observation(
                        {
                            "src": "supervisor",
                            "kind": "recovery_result",
                            "t": now_ms,
                            "class": "W3",
                            "stage": stage,
                            "action": action,
                            "outcome": "unsafe_dialog",
                            "detail": dk,
                        },
                        reduce_now=True,
                        cfg=cfg,
                    )
                    self.stalled(
                        fresh,
                        self.stall_text(term, "blocked", task_id=fresh["id"], diag=diag),
                        key=f"{term}:w3:{dk}",
                    )
                continue

            # Worker recovery actions never restart/rotate autonomously; escalate to PM on notify/rotate steps.
            store.append_observation(
                {
                    "src": "supervisor",
                    "kind": "recovery_started",
                    "t": now_ms,
                    "incident_id": inc_id,
                    "class": cls,
                    "stage": stage,
                    "action": action,
                },
                reduce_now=True,
                cfg=cfg,
            )
            res_obs: dict[str, Any] = {
                "src": "supervisor",
                "kind": "recovery_result",
                "t": now_ms,
                "incident_id": inc_id,
                "class": cls,
                "stage": stage,
                "action": action,
                "outcome": "unknown",
                "detail": "",
            }

            if action == "classify_screen":
                screen = self.ctx.hc.read(term) if term else ""
                classified = classify_stuck_screen(screen) if screen else {"kind": "unknown", "summary": ""}
                allow_trust = self.ctx.git.is_owned_worktree(fresh.get("worktree")) and bool(cfg.recovery_allow_trust)
                pkind, keys = known_prompt_action(screen, allow_trust=allow_trust) if screen else (None, None)
                dk = str(classified.get("kind") or "unknown")
                if dk != "unknown" or pkind:
                    res_obs["outcome"] = "dialog"
                    res_obs["dialog_kind"] = str(pkind or dk)
                    res_obs["detail"] = str(classified.get("summary") or "")
                    store.append_observation(res_obs, reduce_now=True, cfg=cfg)
                    if keys:
                        auto_key = ("auto", fresh["id"], term, pkind)
                        if stops.get(auto_key, 0) < 2:
                            pressed = self._unblock(term, keys)
                            if pressed:
                                stops[auto_key] = stops.get(auto_key, 0) + 1
                                stops.pop(fresh["id"], None)
                                self._record_auto_unblocked(fresh, term, str(pkind))
                                store.append_observation(
                                    {
                                        "src": "supervisor",
                                        "kind": "recovery_result",
                                        "t": now_ms,
                                        "class": "W3",
                                        "stage": 0,
                                        "action": "unblock_prompt",
                                        "outcome": "unblocked",
                                        "detail": str(pkind or ""),
                                    },
                                    reduce_now=True,
                                    cfg=cfg,
                                )
                    else:
                        self.stalled(
                            fresh,
                            self.stall_text(term, "blocked", task_id=fresh["id"], diag=classified),
                            key=f"{term}:{inc_id}:{dk}",
                        )
                        store.append_observation(
                            {
                                "src": "supervisor",
                                "kind": "recovery_result",
                                "t": now_ms,
                                "class": "W3",
                                "stage": 0,
                                "action": "notify_user",
                                "outcome": "notified",
                                "detail": dk,
                            },
                            reduce_now=True,
                            cfg=cfg,
                        )
                    continue
                res_obs["outcome"] = "no_dialog"
                res_obs["detail"] = str(classified.get("summary") or "")

            elif action == "interrupt_tool":
                tool_pid = int(act.get("tool_pid") or 0)
                sig_name = str(act.get("signal") or "SIGINT")
                sig_num = int(getattr(signal, sig_name, getattr(signal, "SIGINT", 2)))
                agent_pid = ep.fg_pid
                if tool_pid > 1:
                    self.ctx.procs.signal_foreground_tool(tool_pid, sig_num, agent_pid=agent_pid)
                    alive = self.ctx.procs.is_tool_alive(tool_pid, agent_pid=agent_pid)
                    res_obs["outcome"] = "exited" if not alive else "sent"
                    res_obs["tool_alive"] = alive
                    res_obs["detail"] = sig_name
                else:
                    res_obs["outcome"] = "failed"
                    res_obs["tool_alive"] = False
                    res_obs["detail"] = "no_tool_pid"

            elif action == "nudge_enter":
                ok = bool(self._transport_of(ep).unblock_prompt(ep, ["enter"]))
                res_obs["outcome"] = "sent" if ok else "failed"
                res_obs["detail"] = "enter"

            elif action == "interrupt_turn":
                if cfg.recovery_auto == "full":
                    int_res = self._transport_of(ep).interrupt(ep, timeout_s=2.0)
                    res_obs["outcome"] = str(int_res.status or "unknown")
                    res_obs["detail"] = str(int_res.detail or int_res.key_sent or "")
                else:
                    # Workers default to safe escalation rather than interrupting active turns blindly.
                    res_obs["outcome"] = "skipped"
                    res_obs["detail"] = "worker_escalate"
                    store.append_observation(res_obs, reduce_now=True, cfg=cfg)
                    screen = self.ctx.hc.read(term) if term else ""
                    diag = classify_stuck_screen(screen) if screen else None
                    turn_now = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
                    reason_tag = str(act.get("reason") or turn_now.get("health_reason") or "stalled")
                    self.stalled(
                        fresh,
                        self.stall_text(term, reason_tag, task_id=fresh["id"], diag=diag),
                        key=f"{term}:{inc_id}:{reason_tag}",
                    )
                    store.append_observation(
                        {
                            "src": "supervisor",
                            "kind": "recovery_result",
                            "t": now_ms,
                            "incident_id": inc_id,
                            "class": cls,
                            "stage": stage,
                            "action": "notify_user",
                            "outcome": "notified",
                            "detail": reason_tag,
                        },
                        reduce_now=True,
                        cfg=cfg,
                    )
                    continue

            elif action in ("notify_user", "restart_seat", "switch_profile"):
                if cls == "W5":
                    unblocked = self._try_unblock_safe_prompt(fresh, term, stops, cfg)
                    if unblocked == "busy":
                        continue
                    if unblocked:
                        store.append_observation(
                            {
                                "src": "supervisor",
                                "kind": "recovery_result",
                                "t": now_ms,
                                "incident_id": inc_id,
                                "class": cls,
                                "stage": stage,
                                "action": "classify_screen",
                                "outcome": "dialog",
                                "dialog_kind": unblocked,
                                "detail": unblocked,
                            },
                            reduce_now=True,
                            cfg=cfg,
                        )
                        store.append_observation(
                            {
                                "src": "supervisor",
                                "kind": "recovery_result",
                                "t": now_ms,
                                "class": "W3",
                                "stage": 0,
                                "action": "unblock_safe_dialog",
                                "outcome": "unblocked",
                                "detail": unblocked,
                            },
                            reduce_now=True,
                            cfg=cfg,
                        )
                        continue
                res_obs["action"] = "notify_user"
                res_obs["outcome"] = "notified"
                screen = self.ctx.hc.read(term) if term else ""
                diag = classify_stuck_screen(screen) if screen else None
                turn_now = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
                reason_tag = str(act.get("reason") or turn_now.get("health_reason") or act.get("error") or "stalled")
                res_obs["detail"] = reason_tag
                self.stalled(
                    fresh,
                    self.stall_text(term, reason_tag, task_id=fresh["id"], diag=diag),
                    key=f"{term}:{inc_id or 'inc'}:{reason_tag}",
                )

            else:
                res_obs["outcome"] = "failed"
                res_obs["detail"] = f"worker_unsupported:{action}"

            store.append_observation(res_obs, reduce_now=True, cfg=cfg)

        return store.sync_journal(tick_now=True, now_ms=now_ms, cfg=cfg)

    def watch_workers(
        self,
        tasks: list[dict[str, Any]],
        stops: dict[Any, Any],
        bases: dict[Any, Any] | None = None,
    ) -> float:
        """Observe watched worker endpoints through `Transport` + `turn_reducer`, run safe recovery ladders, and
        report stalls when a worker stops without reporting or exceeds worker budgets."""
        now_ = self.ctx.clock.monotonic()
        now_ms = int(float(self.ctx.clock.time()) * 1000)
        due, seen = float(RECONCILE), set()
        bases = {} if bases is None else bases
        active_ids = {t["id"] for t in tasks}
        for key in [k for k in bases if k[0] not in active_ids]:
            del bases[key]  # no longer watched: a new round, when it comes back, counts from then
        for task in tasks:
            try:
                due = self._watch_one_worker(task, stops, bases, seen, now_, now_ms, due)
            except Exception:  # noqa: BLE001 - N4: one broken worker endpoint never aborts coordinator delivery
                continue
        for task_id in list(stops):
            if not isinstance(task_id, tuple):
                if task_id not in seen:
                    del stops[task_id]
            elif len(task_id) == 4 and task_id[0] == "auto" and task_id[1] not in active_ids:
                del stops[task_id]
        return due

    def _watch_one_worker(
        self,
        task: dict[str, Any],
        stops: dict[Any, Any],
        bases: dict[Any, Any],
        seen: set[Any],
        now_: float,
        now_ms: int,
        due: float,
    ) -> float:
        if task.get("status") in REPORTED_STATUSES:
            return due
        if self._land_delegated_away(task):
            return due
        la = self._land_approved(task)
        if la and self._land_lock_active(task.get("repo")):
            return due
        term = hc_terminal_of(task)
        ep = parse_legacy_endpoint(f"hc:{term}", runtime_hint="hc") if term else task_endpoint(task)
        if ep is None:
            return due
        if not term:
            term = ep.legacy_pane
        batch = self._transport_of(ep).observe(ep, {})
        store = EndpointTurnStore(self.ctx, ep, repo=task.get("repo") or None)
        cfg = self._worker_cfg(store, task)
        if batch.link_state != "connected":
            if self._worker_link_sigs.get(ep.uid) != batch.link_state:
                for item in batch.observations:
                    store.append_observation(item, reduce_now=False, cfg=cfg)
                self._worker_link_sigs[ep.uid] = batch.link_state
            store.sync_journal(tick_now=True, now_ms=now_ms, cfg=cfg)
            return due
        if self._worker_link_sigs.get(ep.uid) not in (None, "connected"):
            store.append_observation(
                {"src": "transport", "kind": "link_state", "link_state": "connected", "t": now_ms},
                reduce_now=False,
                cfg=cfg,
            )
        self._worker_link_sigs[ep.uid] = "connected"

        if ep.runtime == "self_hosted":
            for item in batch.observations:
                store.append_observation(item, reduce_now=False, cfg=cfg)
            store.sync_journal(tick_now=True, now_ms=now_ms, cfg=cfg)
            return due

        info = batch.terminal_info
        base = self.round_base(task, term, info, bases)
        bg = (
            bool(self.ctx.procs.background_work(info))
            if info and (info.get("status") or {}).get("state") in ("idle", "done")
            else False
        )
        if (la and la.get("executor") == "worker"
                and not la.get("fallback_at") and not la.get("fallback_failed_at")
                and not task.get("landed")):
            land_timeout = self._land_approve_timeout()
            if land_timeout > 0:
                elapsed = _seconds_since_ts(self.ctx.clock, la.get("at"))
                if elapsed < land_timeout:
                    due = min(due, max(1.0, land_timeout - elapsed))
                else:
                    transient_err = (
                        not info
                        or bool(info.get("error") and (info.get("error") or {}).get("kind") != "not_found")
                    )
                    if not transient_err:
                        gone = (
                            (info.get("error") or {}).get("kind") == "not_found"
                            or info.get("state") != "live"
                            or (info.get("reported") and not info.get("status"))
                        )
                        agent_state = "" if gone else str((info.get("status") or {}).get("state") or "")
                        cur_turn = (info or {}).get("turn") or 0
                        turn_stalled = (base is not None) and (cur_turn <= base)
                        worker_idle = (agent_state in ("idle", "done")) and not bg
                        if gone or worker_idle or (turn_stalled and agent_state != "working" and not bg):
                            mins = max(1, int(elapsed // 60))
                            why_state = "exited/gone" if gone else (agent_state or "no-turn")
                            reason = f"timed out after {mins}m, worker {why_state} (turn={cur_turn}, base={base})"
                            if self.fallback_land_to_helper(task, reason=reason, term=term):
                                return due

        for obs in batch.observations:
            if obs.get("kind") == "hc_state":
                hc_sig = (
                    obs.get("state"),
                    obs.get("status"),
                    obs.get("status_msg"),
                    obs.get("status_ms"),
                    obs.get("turn"),
                    obs.get("reported"),
                )
                if hc_sig != self._worker_hc_sigs.get(ep.uid):
                    obs_hc = dict(obs)
                    if (
                        obs_hc.get("state") == "live"
                        and obs_hc.get("status") == "working"
                        and store.read().get("turn", {}).get("phase") == "idle"
                        and info is not None
                    ):
                        bg_cmds = self.ctx.procs.background_work(info)
                        if bg_cmds:
                            obs_hc["bg_only"] = True
                            obs_hc["bg_count"] = len(bg_cmds)
                            obs_hc["bg_commands"] = list(bg_cmds)
                    store.append_observation(obs_hc, reduce_now=False, cfg=cfg)
                    self._worker_hc_sigs[ep.uid] = hc_sig

        w_state, due_actions = store.sync_journal(tick_now=True, now_ms=now_ms, cfg=cfg)
        probed, probed_due = self._probe_worker_signals(ep, store, task, info, w_state, cfg, now_ms)
        if probed:
            due_actions = probed_due

        state = "" if base is None else stop_state(info, worker_hooked(task, info), base, background_active=bg)
        if base is not None and due_actions:
            w_state, _ = self._execute_worker_actions(
                ep,
                store,
                task,
                info,
                w_state,
                due_actions,
                stops,
                cfg,
                now_ms,
                defer_w3=(state in ("blocked", "error")),
            )

        w_turn = w_state.get("turn") if isinstance(w_state.get("turn"), Mapping) else {}
        w_phase = str(w_turn.get("phase") or "idle")
        w_health = str(w_turn.get("health") or "ok")
        if w_phase in ACTIVE_TURN_PHASES or w_phase == "recovering":
            due = min(due, 1.0 if w_health == "suspect" else 5.0)
        inc_now = w_state.get("incident")
        if isinstance(inc_now, Mapping) and inc_now.get("status") in ("open", "recovering"):
            nd_ms = int(inc_now.get("next_due_ms") or 0)
            if nd_ms > 0:
                due = min(due, max(0.5, (nd_ms - now_ms) / 1000.0))

        if not state:
            return due
        seen.add(task["id"])
        # A new key is a new stop: another terminal, another state, or a turn since the last one.
        key = f"{term}:gone" if state == "gone" else f"{term}:{state}:{(info or {}).get('turn') or 0}"
        known = stops.get(task["id"])
        if not known or known[0] != key:
            stops[task["id"]] = (key, now_, False)
            due = min(due, self._stall_grace)
            return due
        if known[2]:
            return due
        if now_ - known[1] < self._stall_grace:
            due = min(due, self._stall_grace - (now_ - known[1]))
            return due
        fresh = self._worker_task_active_for_term(task["id"], term)  # may have reported in grace or changed round
        if fresh is not None:
            base = self.round_base(fresh, term, info, bases)
            if base is not None and (state != "idle" or ((info or {}).get("turn") or 0) > base):
                screen = self.ctx.hc.read(term) if state != "gone" else ""
                if state in ("blocked", "error") and screen:
                    pkind, keys = known_prompt_action(
                        screen, allow_trust=self.ctx.git.is_owned_worktree(fresh.get("worktree"))
                    )
                    auto_key = ("auto", fresh["id"], term, pkind)
                    pressed = self._unblock(term, keys) if keys and stops.get(auto_key, 0) < 2 else False
                    if pressed is None:  # another typist on this terminal right now: look again, not stuck yet
                        due = min(due, self._stall_grace)
                        return due
                    if pressed:
                        stops[auto_key] = stops.get(auto_key, 0) + 1
                        stops.pop(task["id"], None)
                        self._record_auto_unblocked(fresh, term, str(pkind))
                        due = min(due, self._stall_grace)
                        return due
                diag = classify_stuck_screen(screen) if screen else None
                self.stalled(fresh, self.stall_text(term, state, task_id=fresh["id"], diag=diag), key=key)
        stops[task["id"]] = (key, known[1], True)
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
        if state in ("pty_frozen", "no_step_timeout", "upstream_timeout", "tool_waiting_input", "tool_hard_budget", "submit_unstarted"):
            return tr(f"the worker in hc:{term} appears stuck ({state}){tail}. "
                      f"Delegate inspection/unblocking with `pm.py triage {tid}` (helper).",
                      f"hc:{term} 的 worker 疑似卡住（{state}）{tail_zh}。用 `pm.py triage {tid}` 交 helper 排查处理。")
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
        if not task or not self._projects.app_pm(self.ctx.store.task_project_slug(task) or task.get("repo")):
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
        src_task = cur if isinstance(cur, dict) else task
        pslug = self.ctx.store.task_project_slug(src_task)
        repo_val = str(src_task.get("repo") or "")
        conv = Conversation(self.ctx, repo_val, slug=pslug or None)
        last = next((e for e in reversed(conv.events()) if e.get("task") == task["id"]), {})
        if last.get("type") == "stall" and last.get("key") == key:
            return
        conv.record("stall", task=task["id"], title=src_task.get("title"), status=src_task.get("status"),
                    by=src_task.get("pane") or "", text=text, source="harness", wake=True,
                    **({"key": key} if key else {}))
        Delivery(self.ctx, repo_val, slug=pslug or None).ensure_running()

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
