"""Per-project observation supervisor, heartbeat, throttled screen/process probing, and unified reader contract.

Layer 3 (`events/`). Implements §3.2 (sampling & throttling), §3.3 (supervisor loop, heartbeat `pm-turn.beat`,
and reader contract), and non-blocking observation reduction into `pm-turn.json` v2.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import signal
from typing import Any, Mapping

from ..agents.turn_adapters import adapter_for
from ..context import Context
from ..home import project_slug
from ..messaging.address import Endpoint, LogicalAddress, parse_legacy_endpoint, safe_endpoint_uid
from ..messaging.envelope import P2_RESUME, P4_BATCH, Envelope, new_env_id
from ..messaging.mailbox import MailboxItem, MailboxStore
from ..messaging.principal import Principal
from ..messaging.router import (
    UNDELIVERED_P1_P3_ALERT_MS,
    UNDELIVERED_P4_ALERT_MS,
    EndpointSnapshot,
    Router,
    RoutingSnapshot,
)
from ..messaging.transport import AsyncDeliverHandle, DeliverOutcome
from ..messaging.transports.local_hc import LocalHcTransport
from ..messaging.transports.remote_hc import RemoteHcTransport
from ..messaging.typist import close_if_no_reply, transport_for, typed_meta
from ..osutil import clip, unfailing
from ..procs import supervisor_env
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..project.turn_reducer import (
    ACTIVE_TURN_PHASES,
    OCCUPATION_HINT_COOLDOWN_MS,
    Endpoint,
    build_turn2_payload,
    default_state_v2,
    incident_holds_batch,
    project_v1_turn,
    record_endpoint,
    reduce as reduce_observation,
    sync_compat_fields,
    tick as tick_state,
    turn_config_from_dict,
)
from ..project.turn_state import TurnTracker
from ..terminals.screen import classify_stuck_screen, known_prompt_action
from .deliver import Delivery

HEARTBEAT_STALE_MS = 10_000
HEARTBEAT_INTERVAL_S = 3.0
_BG_SHELL_MSG_RE = re.compile(r"(?:(\d+)\s+)?shells?\s+still\s+running\b", re.I)


def touch_heartbeat(beat_path: Path, now_s: float, *, pid: int | None = None) -> None:
    """Update `pm-turn.beat` mtime (and pid metadata if missing/changed) without rewriting large files."""
    beat_path.parent.mkdir(parents=True, exist_ok=True)
    cur_pid = int(pid if pid is not None else os.getpid())
    need_write = not beat_path.is_file()
    if not need_write:
        try:
            raw = json.loads(beat_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("pid") != cur_pid:
                need_write = True
        except (OSError, ValueError):
            need_write = True
    if need_write:
        with contextlib.suppress(OSError):
            beat_path.write_text(
                json.dumps({"pid": cur_pid, "t": int(now_s * 1000)}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    with contextlib.suppress(OSError):
        os.utime(beat_path, (now_s, now_s))


def heartbeat_age_ms(beat_path: Path, now_ms: int) -> int | None:
    """Return age in ms of `pm-turn.beat` relative to `now_ms`, or `None` if absent."""
    try:
        st = beat_path.stat()
    except OSError:
        return None
    beat_ms = int(st.st_mtime * 1000)
    return max(0, int(now_ms) - beat_ms)


def _endpoint_with_live(reg: Mapping[str, Any], info: Mapping[str, Any] | None) -> Endpoint | None:
    ep = record_endpoint(reg)
    if ep is None:
        return None
    if not isinstance(info, Mapping):
        return ep
    fg = info.get("foreground")
    fg_pid = fg.get("pid") if isinstance(fg, Mapping) else None
    clean_fg = int(fg_pid) if isinstance(fg_pid, int) and not isinstance(fg_pid, bool) and fg_pid > 0 else ep.fg_pid
    status_raw = info.get("status")
    app = str(status_raw.get("app") or "").strip().lower() if isinstance(status_raw, Mapping) else ""
    kind = ep.agent_kind or app
    if app in ("claude-code",):
        kind = "claude"
    elif app in ("antigravity",):
        kind = "agy"
    return Endpoint(
        runtime=ep.runtime,
        machine=ep.machine,
        terminal=ep.terminal,
        workspace=ep.workspace,
        session_id=ep.session_id,
        agent_kind=kind,
        fg_pid=clean_fg,
        epoch=ep.epoch,
    )


def _status_parts(info: Mapping[str, Any] | None, live_pm: Mapping[str, Any] | None = None) -> tuple[str, str, str, int, int, bool]:
    """Return `(term_state, agent_status, status_msg, status_ms, hc_turn, reported)`."""
    if isinstance(info, Mapping):
        t_state = str(info.get("state") or "live").strip().lower()
        raw_s = info.get("status")
        if isinstance(raw_s, Mapping):
            a_state = str(raw_s.get("state") or "").strip().lower()
            s_msg = str(raw_s.get("msg") or raw_s.get("message") or "").strip()
            reported = bool(a_state)
        elif isinstance(raw_s, str):
            a_state = raw_s.strip().lower()
            s_msg = ""
            reported = bool(a_state)
        else:
            a_state = ""
            s_msg = ""
            reported = False
        if info.get("reported") is False:
            reported = False
        s_ms = int(info.get("status_ms") or 0)
        hc_turn = int(info.get("turn") or 0)
        return t_state, a_state, s_msg, s_ms, hc_turn, reported
    if isinstance(live_pm, Mapping):
        a_state = str(live_pm.get("agent_status") or live_pm.get("status") or "").strip().lower()
        if a_state == "offline":
            return "offline", "", "", 0, 0, False
        return "live", a_state, "", 0, 0, bool(a_state)
    return "offline", "", "", 0, 0, False


def _read_beat_pid(beat_path: Path) -> int:
    try:
        raw = json.loads(beat_path.read_text(encoding="utf-8"))
        pid = raw.get("pid") if isinstance(raw, Mapping) else None
        return int(pid) if isinstance(pid, int) and not isinstance(pid, bool) and pid > 1 else 0
    except (OSError, ValueError):
        return 0


def _incident_reason_text(ctx: Context, inc: Mapping[str, Any]) -> str:
    tr = ctx.config.tr
    cls = str(inc.get("class") or "W2")
    reason = str(inc.get("reason") or "").strip()
    err = str(inc.get("error") or "").strip()
    if err:
        return clip(err, 80)
    mapping = {
        "no_step_timeout": tr("model stream silent for 4m", "模型响应连续 4 分钟无推进"),
        "upstream_timeout": tr("upstream retry timed out", "模型服务重试超时"),
        "errored": tr("turn ended with error", "这一轮因错误中止"),
        "silent": tr("turn ended without reply", "这一轮未回复即结束"),
        "tool_hard_budget": tr("foreground command exceeded hard budget", "前台命令超过硬预算"),
        "tool_waiting_input": tr("foreground command waiting for input", "前台命令可能在等输入"),
        "pty_frozen": tr("terminal screen stopped updating", "终端屏幕持续无变化"),
        "submitted_timeout": tr("submitted prompt did not start turn", "消息发出后未开始执行"),
        "exited": tr("coordinator process exited", "协调者进程已退出"),
        "offline": tr("coordinator session went offline", "协调者会话离线"),
    }
    if reason in mapping:
        return mapping[reason]
    return f"{cls} ({reason or 'stalled'})"


def _step_label_text(ctx: Context, step_name: str, inc: Mapping[str, Any]) -> str:
    tr = ctx.config.tr
    suggested = str(inc.get("suggested_profile") or "").strip()
    mapping = {
        "classify_screen": tr("checking terminal screen", "正在检查终端屏幕"),
        "interrupt_tool": tr("interrupting hung command", "正在中断卡住的命令"),
        "interrupt_turn": tr("interrupting stuck turn", "正在打断卡住的轮次"),
        "continue_turn": tr("resuming interrupted turn", "正在续上未完成的轮次"),
        "nudge_enter": tr("sending Enter to start turn", "正在补按回车触发执行"),
        "retype_submitted": tr("re-sending unstarted message", "正在重新发送未接住的消息"),
        "restart_seat": tr("restarting coordinator session", "正在重启协调者会话接手"),
        "switch_profile": tr("switching to fallback model profile", "正在切换备用档位接手"),
        "waiting_draft": tr("waiting for terminal draft to clear", "等待终端草稿清除"),
        "notify_user": (
            tr(f"needs your attention (suggest profile: {suggested})", f"需要你介入处理（建议切档：{suggested}）")
            if suggested
            else tr("needs your attention", "需要你介入处理")
        ),
    }
    return mapping.get(step_name, step_name or tr("recovering", "自动恢复中"))


def _format_incident_text(ctx: Context, inc: Mapping[str, Any]) -> str:
    tr = ctx.config.tr
    why = _incident_reason_text(ctx, inc)
    status = str(inc.get("status") or "open")
    step_name = str(inc.get("step_name") or "")
    step_txt = _step_label_text(ctx, step_name, inc)
    if status == "resolved":
        if inc.get("folded"):
            return tr(f"Auto-recovered ({why}).", f"已自动恢复（{why}）。")
        return tr(f"Recovered from {why}.", f"已从「{why}」中恢复。")
    if status == "notified":
        return tr(
            f"Recovery stopped ({why}): {step_txt}.",
            f"自动恢复需要人工介入（{why}）：{step_txt}。",
        )
    return tr(
        f"Recovering ({why}): {step_txt}…",
        f"正在自动恢复（{why}）：{step_txt}…",
    )


def _format_continue_prompt(
    ctx: Context,
    tracker: TurnTracker,
    act: Mapping[str, Any],
    cfg: Any,
) -> str:
    tr = ctx.config.tr
    why = _incident_reason_text(ctx, act)
    summary = ""
    if tracker.files.pm_mailbox.is_dir():
        unanswered = tracker.pm_mailbox.unanswered_user_items()
        if unanswered:
            summary = clip(str((unanswered[-1].envelope.body or {}).get("text") or "").strip(), 120)
    if not summary and tracker.repo:
        for ev in reversed(Conversation(ctx, tracker.repo).events()):
            if ev.get("type") == "user" and str(ev.get("text") or "").strip():
                summary = clip(str(ev["text"]).strip(), 120)
                break
    summary_en = summary or "(recent user message)"
    summary_zh = summary or "（最近一条用户消息）"

    tool_note_en = ""
    tool_note_zh = ""
    if act.get("tool_note"):
        cmd = clip(str(act.get("tool_cmd") or "command"), 60)
        hard_s = max(1, int(round(int(getattr(cfg, "tool_hard_ms", 180_000)) / 1000.0)))
        tool_note_en = (
            f" Foreground command `{cmd}` exceeded {hard_s}s and was interrupted; "
            "run long commands in the background or delegate to a helper."
        )
        tool_note_zh = f" 前台命令「{cmd}」超过 {hard_s} 秒已被中断；长命令请放后台或交给 helper。"

    return "[from pm.py supervisor] " + tr(
        f"The previous turn was interrupted before replying (reason: {why}). "
        f"The user's message has not been answered yet: \"{summary_en}\".{tool_note_en} "
        "First run `pm.py status` to check what actions are already done, then continue replying without repeating completed actions.",
        f"上一轮在答复之前中断了（原因：{why}）。"
        f"用户的这条消息还没有得到答复：「{summary_zh}」。{tool_note_zh} "
        "请先用 `pm.py status` 核对已经做完的动作，然后继续答复，不要重复已完成的动作。",
    )


def _stale_batch_reason(ctx: Context, repo: str, item: MailboxItem) -> str:
    """Return a non-empty hold reason when an `event.batch` is already answered, acknowledged, or superseded
    by subsequent PM actions/task transitions, so retries never wake the PM for duplicate confirmation."""
    if not repo or item.envelope.kind != "event.batch":
        return ""
    body = item.envelope.body if isinstance(item.envelope.body, Mapping) else {}
    b_start, b_end = body.get("start"), body.get("end")
    if not (
        isinstance(b_start, int) and not isinstance(b_start, bool)
        and isinstance(b_end, int) and not isinstance(b_end, bool)
        and 0 <= b_start < b_end
    ):
        return ""
    dlv = Delivery(ctx, repo, settle=0)
    if dlv.batch_already_answered(b_start, b_end):
        return "already_answered"
    # W2 retries (`retry_after_interrupted` / `retry_after_silent`) re-send a batch whose turn crashed after
    # `took_delivery` may have recorded `received`; never suppress those purely on `received_ranges`.
    if item.hold_reason not in ("retry_after_interrupted", "retry_after_silent") and dlv.is_received(b_start, b_end):
        return "already_received"
    log_path = ctx.home.project_for(repo).conversation
    try:
        log_grew = log_path.exists() and log_path.stat().st_size > b_end
    except OSError:
        log_grew = False
    if (item.attempts >= 1 or bool(item.hold_reason) or log_grew) and not dlv.batch_has_live_news(b_start, b_end):
        return "events_superseded"
    return ""


class ProjectSupervisor:
    """Co-located per-project observation sampler, heartbeater, journal reducer, and recovery executor (§3.2-3.6)."""

    def __init__(
        self,
        ctx: Context,
        repo: str | Path,
        *,
        transport: Any = None,
        rotate_fn: Any = None,
    ) -> None:
        self.ctx = ctx
        self.repo = str(repo)
        self.slug = project_slug(self.repo) if self.repo else "project"
        self.tracker = TurnTracker(ctx, self.repo or self.slug)
        self._transport = transport
        self._rotate_fn = rotate_fn
        self._lease_owner = f"{os.getpid()}:supervisor:{os.urandom(4).hex()}"
        self._last_hc_sig: tuple[Any, ...] | None = None
        self._transcript_path: str = ""
        self._transcript_offset: int = 0
        self._last_screen_probe_ms: int = 0
        self._last_screen_turn_id: str = ""
        self._last_screen_digest: str | None = None
        self._last_screen_changed: bool | None = None
        self._last_screen_hint: str = ""
        self._last_screen_dialog: str = ""
        self._last_proc_probe_ms: int = 0
        self._last_proc_sig: tuple[Any, ...] | None = None
        self._last_incident_sig: tuple[Any, ...] | None = None
        self._logged_stall_turn_seq: int = 0

    def _transport_for(self, endpoint: Endpoint) -> Any:
        if self._transport is not None:
            return self._transport
        return transport_for(self.ctx, endpoint)

    def _sync_incident_row(self, state: Mapping[str, Any]) -> None:
        inc = state.get("incident")
        if not isinstance(inc, Mapping) or not inc.get("key"):
            return
        sig = (
            str(inc.get("key") or ""),
            str(inc.get("class") or ""),
            str(inc.get("status") or ""),
            int(inc.get("stage") or 0),
            str(inc.get("step_name") or ""),
            bool(inc.get("folded")),
        )
        if sig == self._last_incident_sig:
            return
        self._last_incident_sig = sig
        if not self.repo:
            return
        ep = record_endpoint({"session": state.get("session")}) if isinstance(state.get("session"), Mapping) else None
        term = str((state.get("session") or {}).get("terminal") or state.get("terminal") or "")
        by = f"hc:{term}" if term and (ep is None or ep.runtime == "hc") else term
        Conversation(self.ctx, self.repo).record(
            "event",
            source="pm-incident",
            wake=False,
            by=by,
            key=str(inc.get("key") or ""),
            incident_id=str(inc.get("id") or ""),
            incident_class=str(inc.get("class") or ""),
            status=str(inc.get("status") or "open"),
            stage=int(inc.get("stage") or 0),
            step=str(inc.get("step_name") or ""),
            folded=bool(inc.get("folded")),
            reason=str(inc.get("reason") or ""),
            error=str(inc.get("error") or ""),
            suggested_profile=str(inc.get("suggested_profile") or ""),
            text=_format_incident_text(self.ctx, inc),
        )

    def _emit_incident_alert(self, inc_or_act: Mapping[str, Any], now_ms: int, detail: str = "") -> None:
        alert = {
            "kind": "recovery.notify_user",
            "class": str(inc_or_act.get("class") or ""),
            "incident_id": str(inc_or_act.get("incident_id") or inc_or_act.get("id") or ""),
            "reason": str(inc_or_act.get("reason") or ""),
            "error": str(inc_or_act.get("error") or ""),
            "suggested_profile": str(inc_or_act.get("suggested_profile") or ""),
            "detail": detail,
            "at_ms": now_ms,
        }
        for sink in tuple(getattr(self.ctx, "alert_sinks", ()) or ()):
            unfailing(sink, self.slug, self.repo, alert)

    def _requeue_batch_for_continue(
        self,
        act: Mapping[str, Any],
        state: Mapping[str, Any],
        ep: Endpoint | None,
        now_ms: int,
    ) -> bool:
        if not self.tracker.files.pm_mailbox.is_dir():
            return False
        mailbox = self.tracker.pm_mailbox
        batch_range = act.get("batch")
        cur_turn = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
        cur_phase = str(cur_turn.get("phase") or "idle")
        cur_tid = str(cur_turn.get("id") or "")
        cur_seq = int(cur_turn.get("seq") or 0)
        requeued = False
        for item in mailbox.active_items(("consumed", "typed", "accepted")):
            if item.envelope.kind != "event.batch":
                continue
            body = item.envelope.body if isinstance(item.envelope.body, Mapping) else {}
            if isinstance(batch_range, list) and len(batch_range) == 2:
                b_start, b_end = body.get("start"), body.get("end")
                if not (isinstance(b_start, int) and isinstance(b_end, int) and b_start == batch_range[0] and b_end >= batch_range[1]):
                    continue
            if item.state == "consumed" and cur_phase in ACTIVE_TURN_PHASES:
                active_refs = {r for r in (cur_tid, f"seq:{cur_seq}" if cur_seq > 0 else "") if r}
                if not item.bound_turn_id or item.bound_turn_id in active_refs or item.meta.get("turn_seq") == cur_seq:
                    continue
            if item.state == "accepted":
                requeued = True
                continue
            mailbox.transition(
                item.envelope.env_id,
                "accepted",
                now_ms=now_ms,
                attempts=item.attempts + 1,
                hold_reason="retry_after_interrupted",
                clear_intent=True,
                meta={**item.meta, "attempts_preincremented": True},
            )
            requeued = True
        if not requeued and isinstance(batch_range, list) and len(batch_range) == 2 and self.repo:
            b_start, b_end = int(batch_range[0]), int(batch_range[1])
            dlv = Delivery(self.ctx, self.repo, settle=0)
            _, _, items = dlv.pending_batch(offset=b_start, settle=False)
            items = [it for it in items if int(it.get("offset", b_start)) < b_end] or items
            if items:
                inc_id = str(act.get("incident_id") or "")
                stage = int(act.get("stage") or 0)
                attempt_num = max(2, int(act.get("attempt") or 1) + 1)
                new_id = new_env_id(now_ms)
                payload_text = dlv.batch_text(b_start, b_end, items, env_id=new_id)
                rec_env = Envelope(
                    env_id=new_id,
                    idempotency_key=f"batch:{self.slug}:{b_start}-{b_end}:w2:{inc_id}:{stage}",
                    schema_version=1,
                    created_ms=now_ms,
                    kind="event.batch",
                    sender=Principal.supervisor(self.slug),
                    recipient=LogicalAddress.pm(self.slug),
                    project=self.slug,
                    cause={"kind": "deliver_batch", "start": b_start, "end": b_end},
                    priority=P4_BATCH,
                    body={"text": payload_text, "start": b_start, "end": b_end},
                    require_reply=True,
                )
                enq_item, _ = mailbox.enqueue(
                    rec_env,
                    initial_state="accepted",
                    now_ms=now_ms,
                    target_endpoint_uid=ep.uid if ep is not None else "",
                    endpoint_epoch=int(ep.epoch or 1) if ep is not None else 1,
                )
                if enq_item.attempts < attempt_num:
                    mailbox.transition(
                        enq_item.envelope.env_id,
                        "accepted",
                        now_ms=now_ms,
                        attempts=attempt_num,
                        hold_reason="retry_after_silent",
                        meta={**enq_item.meta, "attempts_preincremented": True},
                    )
                requeued = True
        if requeued:
            self.tracker.sync_mailbox_projection(now_ms)
        return requeued

    def _requeue_submitted_for_retype(self, act: Mapping[str, Any], ep: Endpoint | None, now_ms: int) -> str:
        """Requeue typed-but-unstarted envelopes for W6 retry. Returns `'requeued'`, `'superseded'`, or `'failed'`."""
        if not self.tracker.files.pm_mailbox.is_dir():
            return "failed"
        mailbox = self.tracker.pm_mailbox
        msg_ids = {str(m) for m in (act.get("msg_ids") or []) if m}
        batch_range = act.get("batch")
        candidates = [
            it for it in mailbox.active_items(("typed",))
            if not ep or not it.target_endpoint_uid or it.target_endpoint_uid == ep.uid
        ]
        matched: list[MailboxItem] = []
        for it in candidates:
            body = it.envelope.body if isinstance(it.envelope.body, Mapping) else {}
            mid = str(body.get("msg_id") or "")
            if msg_ids and mid in msg_ids:
                matched.append(it)
            elif isinstance(batch_range, list) and len(batch_range) == 2 and [body.get("start"), body.get("end")] == batch_range:
                matched.append(it)
        if not matched and candidates:
            candidates.sort(key=lambda x: x.seq)
            matched = [candidates[-1]]
        if not matched:
            return "failed"
        requeued_any = False
        superseded_any = False
        for it in matched:
            stale = _stale_batch_reason(self.ctx, self.repo, it)
            if stale:
                mailbox.transition(
                    it.envelope.env_id,
                    "superseded",
                    now_ms=now_ms,
                    hold_reason=stale,
                    clear_intent=True,
                )
                body = it.envelope.body if isinstance(it.envelope.body, Mapping) else {}
                b_end = body.get("end")
                if self.repo and isinstance(b_end, int) and not isinstance(b_end, bool) and b_end > 0:
                    Delivery(self.ctx, self.repo).advance_delivered(b_end)
                superseded_any = True
                continue
            mailbox.transition(
                it.envelope.env_id,
                "accepted",
                now_ms=now_ms,
                hold_reason="retry_unstarted",
                clear_intent=True,
            )
            requeued_any = True
        self.tracker.sync_mailbox_projection(now_ms)
        if requeued_any:
            return "requeued"
        return "superseded" if superseded_any else "failed"

    def _execute_recovery_actions(
        self,
        rec: Mapping[str, Any],
        info: Mapping[str, Any] | None,
        ep: Endpoint | None,
        state: dict[str, Any],
        due_actions: list[dict[str, Any]],
        cfg: Any,
        now_ms: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        rec_actions = [a for a in due_actions if a.get("kind") == "recovery_action"]
        if not rec_actions:
            return state, due_actions
        term = ep.hc_target if ep is not None else str(rec.get("terminal") or "")
        transport = self._transport_for(ep) if ep is not None else None
        self.tracker.ensure_mailbox_migrated()
        mailbox = self.tracker.pm_mailbox
        owner_pid = os.getpid()

        for act in rec_actions:
            cls = str(act.get("class") or "")
            action = str(act.get("action") or "")
            inc_id = str(act.get("incident_id") or "")
            stage = int(act.get("stage") or 0)

            if cls == "W3":
                if action == "notify_user" or act.get("auto") == "off":
                    self.tracker.append_observation(
                        {
                            "src": "supervisor",
                            "kind": "recovery_result",
                            "t": now_ms,
                            "class": "W3",
                            "stage": stage,
                            "action": "notify_user",
                            "outcome": "notified",
                            "detail": str(act.get("dialog_kind") or ""),
                        },
                        reduce_now=True,
                    )
                    self._emit_incident_alert(act, now_ms, detail=str(act.get("dialog_kind") or "blocked"))
                    continue
                screen = self.ctx.hc.read(term) if term else ""
                pkind, keys = known_prompt_action(screen, allow_trust=bool(act.get("allow_trust", True))) if screen else (None, None)
                if keys and ep is not None and transport is not None:
                    if not mailbox.acquire_typist_lease(ep.uid, owner_pid, ttl_ms=10_000, now_ms=now_ms, owner=self._lease_owner):
                        continue
                    try:
                        ok = bool(transport.unblock_prompt(ep, keys))
                    finally:
                        mailbox.release_typist_lease(ep.uid, owner_pid, owner=self._lease_owner)
                    self.tracker.append_observation(
                        {
                            "src": "supervisor",
                            "kind": "recovery_result",
                            "t": now_ms,
                            "class": "W3",
                            "stage": stage,
                            "action": action,
                            "outcome": "unblocked" if ok else "failed",
                            "detail": str(pkind or ""),
                        },
                        reduce_now=True,
                    )
                else:
                    dk = str(act.get("dialog_kind") or (classify_stuck_screen(screen).get("kind") if screen else "unknown"))
                    self.tracker.append_observation(
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
                    )
                    self._emit_incident_alert(act, now_ms, detail=dk)
                continue

            # All incident ladder actions (`W1`, `W2`, `W4`, `W5`, `W6`, `W7`):
            self.tracker.append_observation(
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
                pkind, _ = known_prompt_action(screen, allow_trust=bool(cfg.recovery_allow_trust)) if screen else (None, None)
                dk = str(classified.get("kind") or "unknown")
                has_draft = isinstance(info, Mapping) and bool(info.get("has_draft") or info.get("draft"))
                if dk != "unknown" or pkind:
                    res_obs["outcome"] = "dialog"
                    res_obs["dialog_kind"] = str(pkind or dk)
                    res_obs["detail"] = str(classified.get("summary") or "")
                elif cls == "W6" and has_draft:
                    res_obs["outcome"] = "draft"
                    res_obs["detail"] = "unsent_draft"
                else:
                    res_obs["outcome"] = "no_dialog"
                    res_obs["detail"] = str(classified.get("summary") or "")

            elif action == "interrupt_tool":
                tool_pid = int(act.get("tool_pid") or 0)
                sig_name = str(act.get("signal") or "SIGINT")
                sig_num = int(getattr(signal, sig_name, getattr(signal, "SIGINT", 2)))
                agent_pid = ep.fg_pid if ep is not None else None
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

            elif action == "interrupt_turn":
                if ep is not None and transport is not None:
                    if not mailbox.acquire_typist_lease(ep.uid, owner_pid, ttl_ms=10_000, now_ms=now_ms, owner=self._lease_owner):
                        continue
                    try:
                        int_res = transport.interrupt(ep, timeout_s=2.0)
                    finally:
                        mailbox.release_typist_lease(ep.uid, owner_pid, owner=self._lease_owner)
                    res_obs["outcome"] = str(int_res.status or "unknown")
                    res_obs["detail"] = str(int_res.detail or int_res.key_sent or "")
                else:
                    res_obs["outcome"] = "endpoint_gone"

            elif action == "nudge_enter":
                if ep is not None and transport is not None:
                    if not mailbox.acquire_typist_lease(ep.uid, owner_pid, ttl_ms=10_000, now_ms=now_ms, owner=self._lease_owner):
                        continue
                    try:
                        ok = bool(transport.unblock_prompt(ep, ["enter"]))
                    finally:
                        mailbox.release_typist_lease(ep.uid, owner_pid, owner=self._lease_owner)
                    res_obs["outcome"] = "sent" if ok else "failed"
                    res_obs["detail"] = "enter"
                else:
                    res_obs["outcome"] = "endpoint_gone"

            elif action == "retype_submitted":
                retype_res = self._requeue_submitted_for_retype(act, ep, now_ms)
                res_obs["outcome"] = retype_res
                res_obs["detail"] = "already_handled" if retype_res == "superseded" else "retry_unstarted"

            elif action == "continue_turn":
                cause_kind = str(act.get("cause_kind") or "user")
                if cause_kind == "deliver":
                    if self._requeue_batch_for_continue(act, state, ep, now_ms):
                        res_obs["outcome"] = "queued"
                        res_obs["detail"] = "batch_requeued"
                    else:
                        res_obs["outcome"] = "failed"
                        res_obs["detail"] = "no_pending_batch"
                else:
                    prompt_text = _format_continue_prompt(self.ctx, self.tracker, act, cfg)
                    env = Envelope(
                        env_id=new_env_id(now_ms),
                        idempotency_key=f"resume:{inc_id}:{stage}",
                        schema_version=1,
                        created_ms=now_ms,
                        kind="cmd.resume_turn",
                        sender=Principal.supervisor(self.slug),
                        recipient=LogicalAddress.pm(self.slug),
                        project=self.slug,
                        cause={
                            "kind": "recovery",
                            "original_cause": cause_kind,
                            "msg_ids": list(act.get("msg_ids") or []),
                            "incident_id": inc_id,
                        },
                        priority=P2_RESUME,
                        body={
                            "text": prompt_text,
                            "original_cause": cause_kind,
                            "msg_ids": list(act.get("msg_ids") or []),
                        },
                        require_reply=True,
                    )
                    mailbox.enqueue(
                        env,
                        initial_state="accepted",
                        now_ms=now_ms,
                        target_endpoint_uid=ep.uid if ep is not None else "",
                        endpoint_epoch=int(ep.epoch or 1) if ep is not None else 1,
                    )
                    self.tracker.sync_mailbox_projection(now_ms)
                    res_obs["outcome"] = "queued"
                    res_obs["detail"] = env.env_id

            elif action in ("restart_seat", "switch_profile"):
                profile = str(act.get("profile") or "").strip()
                force_rotate = True
                reason_text = f"recovery {cls}: {_incident_reason_text(self.ctx, act)}"
                ok = False
                if callable(self._rotate_fn):
                    try:
                        sig = inspect.signature(self._rotate_fn)
                        has_force = "force" in sig.parameters or any(
                            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                        )
                        kw_rot: dict[str, Any] = {"repo": self.repo, "reason": reason_text, "profile": profile or None}
                        if has_force:
                            kw_rot["force"] = force_rotate
                        res_rot = self._rotate_fn(**kw_rot)
                        ok = res_rot is not False
                    except Exception as exc:  # noqa: BLE001
                        res_obs["detail"] = str(exc)[:160]
                        ok = False
                else:
                    args = ["rotate", "--repo", self.repo, "--reason", reason_text]
                    if profile:
                        args.extend(["--profile", profile])
                    if force_rotate:
                        args.append("--force")
                    proc = self.ctx.procs.spawn_pm(
                        args,
                        env=supervisor_env(self.ctx.env),
                        cwd=self.ctx.home.root if self.ctx.home.root.is_dir() else None,
                    )
                    ok = proc is not None
                res_obs["outcome"] = "started" if ok else "failed"
                if not res_obs["detail"]:
                    res_obs["detail"] = profile or reason_text

            elif action == "notify_user":
                res_obs["outcome"] = "notified"
                res_obs["detail"] = str(act.get("suggested_profile") or act.get("error") or act.get("reason") or "")
                self._emit_incident_alert(act, now_ms, detail=res_obs["detail"])

            self.tracker.append_observation(res_obs, reduce_now=True)

        state, due_actions = self.tracker.sync_journal(tick_now=True, cfg=cfg)
        self._sync_incident_row(state)
        return state, due_actions

    def observe_and_reduce(
        self,
        rec: Mapping[str, Any],
        info: Mapping[str, Any],
    ) -> tuple[dict[str, Any], float | None]:
        """Sample terminal/transcript/screen/process signals with §3.2 throttling, append journal
        observations, touch `pm-turn.beat`, and return `(reduced_state, next_due_seconds)`."""
        now_s = float(self.ctx.clock.time())
        now_ms = int(now_s * 1000)
        touch_heartbeat(self.tracker.files.pm_turn_beat, now_s)

        ep = _endpoint_with_live(rec, info)
        term = ep.hc_target if ep is not None else str(rec.get("terminal") or "")
        t_state, a_state, s_msg, s_ms, hc_turn, reported = _status_parts(info)
        fg_pid = ep.fg_pid if ep is not None else None
        agent_kind = (ep.agent_kind if ep is not None else "") or str(rec.get("agent") or "").strip().lower()

        seat_starting = self.tracker.files.next_session.is_file()
        has_unanswered = bool(
            t_state in ("exited", "finished", "removed", "offline")
            and self.tracker.files.pm_mailbox.is_dir()
            and self.tracker.pm_mailbox.unanswered_user_items()
        )
        hc_sig = (
            ep.uid if ep else term,
            fg_pid,
            ep.epoch if ep else 1,
            t_state,
            a_state,
            s_msg,
            s_ms,
            hc_turn,
            reported,
            seat_starting,
            has_unanswered,
        )
        if hc_sig != self._last_hc_sig:
            obs_hc: dict[str, Any] = {
                "src": "supervisor",
                "kind": "hc_state",
                "t": now_ms,
                "state": t_state,
                "status": a_state,
                "status_msg": s_msg,
                "status_ms": s_ms,
                "turn": hc_turn,
                "reported": reported,
                "seat_starting": seat_starting,
            }
            if t_state in ("exited", "finished", "removed", "offline"):
                obs_hc["has_unanswered"] = has_unanswered
            if ep is not None:
                obs_hc["endpoint"] = ep.to_dict()
            # T4 pre-check: if terminal reports `working` while snapshot is `idle` (no active turn),
            # check process tree for background shells so T4 does not open a spurious turn.
            if t_state == "live" and a_state == "working":
                cur_snap = self.tracker.read()
                if cur_snap.get("phase") == "idle":
                    bg_cmds = self.ctx.procs.background_work(info)
                    if bg_cmds:
                        obs_hc["bg_only"] = True
                        obs_hc["bg_count"] = len(bg_cmds)
                        obs_hc["bg_commands"] = list(bg_cmds)
            self.tracker.append_observation(obs_hc, reduce_now=False)
            self._last_hc_sig = hc_sig

        # Non-agy adapters: incrementally tail transcript into step observations.
        # (`agy` transcripts are synced by AgyTranscriptWatcher, which also feeds the journal.)
        adapter = adapter_for(agent_kind)
        if adapter.kind != "agy":
            tpath = adapter.transcript_path(
                rec,
                self.tracker.files,
                claude_projects=getattr(self.ctx.agents, "claude_projects", None),
                codex_sessions=getattr(self.ctx, "codex_sessions", None),
            )
            if tpath is not None:
                tpath_str = str(tpath)
                if tpath_str != self._transcript_path:
                    self._transcript_path = tpath_str
                    # Seed at EOF on first attach to an existing transcript so historical turns aren't replayed.
                    try:
                        self._transcript_offset = tpath.stat().st_size
                    except OSError:
                        self._transcript_offset = 0
                step_obs, new_off = adapter.steps(tpath, self._transcript_offset)
                self._transcript_offset = new_off
                for item in step_obs:
                    self.tracker.append_observation(item, reduce_now=False)

        cfg = self.tracker.turn_config()
        state, due_actions = self.tracker.sync_journal(tick_now=True, cfg=cfg)
        turn = state.get("turn") or {}
        phase = str(turn.get("phase") or "idle")
        health = str(turn.get("health") or "ok")
        cur_turn_id = str(turn.get("id") or "")
        started_ms = int(turn.get("started_ms") or 0)
        phase_since_ms = int(turn.get("phase_since_ms") or started_ms)
        step_ev = (turn.get("evidence") or {}).get("step") or {}
        last_step_ms = max(started_ms, int(step_ev.get("last_ms") or 0))
        step_quiet_ms = max(0, now_ms - last_step_ms)
        phase_age_ms = max(0, now_ms - phase_since_ms)

        appended_probe = False
        # §3.2 Throttled screen probe: NEVER probe during the first 10s of normal generation.
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

        if screen_interval_ms > 0 and term and (now_ms - self._last_screen_probe_ms) >= screen_interval_ms:
            self._last_screen_probe_ms = now_ms
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
                first_for_turn = self._last_screen_turn_id != cur_turn_id
                changed = first_for_turn or (digest != self._last_screen_digest)
                should_emit = (
                    first_for_turn
                    or changed
                    or (changed != self._last_screen_changed)
                    or (hint != self._last_screen_hint)
                    or (dialog_kind != self._last_screen_dialog)
                )
                self._last_screen_turn_id = cur_turn_id
                self._last_screen_digest = digest
                self._last_screen_changed = changed
                self._last_screen_hint = hint
                self._last_screen_dialog = dialog_kind
                if should_emit:
                    self.tracker.append_observation(
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
                    )
                    appended_probe = True

        # §3.2 Throttled process probe: active `tool` phase or `hc` working after turn closed (T4).
        need_proc_probe = (
            phase == "tool"
            or (a_state == "working" and (phase == "idle" or bool(step_ev.get("ended"))))
        )
        if need_proc_probe and (now_ms - self._last_proc_probe_ms) >= 5_000:
            self._last_proc_probe_ms = now_ms
            fg_stat = self.ctx.procs.foreground_tool_stat(info)
            bg_cmds = self.ctx.procs.background_work(info)
            tool_pid = int(fg_stat.get("tool_pid") or 0)
            cmd = str(fg_stat.get("cmd") or "")
            cpu_ms = int(fg_stat.get("cpu_ms") or 0)
            sig = (tool_pid, cmd, cpu_ms, tuple(bg_cmds))
            if sig != self._last_proc_sig:
                self._last_proc_sig = sig
                self.tracker.append_observation(
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
                )
                appended_probe = True

        if appended_probe:
            state, due_actions = self.tracker.sync_journal(tick_now=True, cfg=cfg)
            turn = state.get("turn") or {}
            phase = str(turn.get("phase") or "idle")
            health = str(turn.get("health") or "ok")

        if health == "stalled":
            cur_seq = int(turn.get("seq") or 0)
            if cur_seq > 0 and self._logged_stall_turn_seq < cur_seq:
                idle_ms = max(0, now_ms - int(turn.get("last_progress_ms") or turn.get("started_ms") or now_ms))
                detail = str((turn.get("activity") or {}).get("summary") or turn.get("health_reason") or "").strip()
                self.tracker.log_stall_diagnostic(term, cur_seq, idle_ms, detail)
                self._logged_stall_turn_seq = cur_seq

        self._sync_incident_row(state)
        if due_actions:
            state, due_actions = self._execute_recovery_actions(rec, info, ep, state, due_actions, cfg, now_ms)
            turn = state.get("turn") or {}
            phase = str(turn.get("phase") or "idle")
            health = str(turn.get("health") or "ok")

        heartbeat_due = max(0.5, min(HEARTBEAT_INTERVAL_S, (cfg.heartbeat_stale_ms / 1000.0) / 3.0))
        inc_now = state.get("incident")
        inc_due_s: float | None = None
        if isinstance(inc_now, Mapping) and inc_now.get("status") in ("open", "recovering"):
            nd_ms = int(inc_now.get("next_due_ms") or 0)
            if nd_ms > 0:
                inc_due_s = max(0.5, (nd_ms - now_ms) / 1000.0)
        if phase in ACTIVE_TURN_PHASES or phase == "recovering":
            if health == "suspect" or any(a.get("interval_ms") == 1_000 for a in due_actions):
                base_due = min(1.0, heartbeat_due)
                return state, min(base_due, inc_due_s) if inc_due_s is not None else base_due
            active_due = max(0.5, min(5.0, (cfg.heartbeat_stale_ms / 1000.0) / 2.0))
            return state, min(active_due, inc_due_s) if inc_due_s is not None else active_due
        return state, inc_due_s


WAIT_DRAFT_FLAG_MS = 5_000
# A typist lease outlives the longest send it covers (async `hc send` is killed at 70 s) and is renewed on every
# driver pass while that send is in flight; a holder that dies stops renewing and the lease lapses on its own.
TYPIST_LEASE_TTL_MS = 75_000


class EndpointDriver:
    """Single-typist endpoint delivery loop (`typist.lock`, C3 intent reconciliation, non-blocking async send, G4/G5)."""

    def __init__(
        self,
        ctx: Context,
        repo: str | Path,
        *,
        transport: Any = None,
        router: Router | None = None,
    ) -> None:
        self.ctx = ctx
        self.repo = str(repo)
        self.slug = project_slug(self.repo) if self.repo else "project"
        self.tracker = TurnTracker(ctx, self.repo or self.slug)
        self._transport = transport
        self._router = router if router is not None else Router()
        self._active: dict[str, tuple[str, AsyncDeliverHandle, Endpoint, int, int, Any]] = {}
        # Lease owner token of this driver: unique per driver, so an in-process `deliver_under_typist_lock`
        # (same pid) is still excluded while this driver's send is in flight.
        self._lease_owner = f"{os.getpid()}:driver:{os.urandom(4).hex()}"

    def has_inflight(self) -> bool:
        """True while an async send started by this driver has not settled (its lease must keep being renewed)."""
        return bool(self._active)

    def _transport_for(self, endpoint: Endpoint) -> Any:
        if self._transport is not None:
            return self._transport
        return transport_for(self.ctx, endpoint)

    def _settle_deliver_outcome(
        self,
        mailbox: MailboxStore,
        item: MailboxItem,
        endpoint: Endpoint,
        outcome: DeliverOutcome,
        *,
        attempt: int,
        now_ms: int,
        on_typed: Any = None,
    ) -> DeliverOutcome:
        env_id = item.envelope.env_id
        if outcome.status == "typed":
            body = item.envelope.body if isinstance(item.envelope.body, Mapping) else {}
            env_cause = item.envelope.cause if isinstance(item.envelope.cause, Mapping) else {}
            msg_id = str(body.get("msg_id") or "")
            if item.envelope.kind == "chat.user":
                cause = "user"
            elif item.envelope.kind == "cmd.resume_turn":
                cause = str(body.get("original_cause") or env_cause.get("original_cause") or "user")
            else:
                cause = "deliver"
            raw_mids = body.get("msg_ids") or env_cause.get("msg_ids") or []
            all_msg_ids = [str(m) for m in raw_mids if m]
            if msg_id and msg_id not in all_msg_ids:
                all_msg_ids.append(msg_id)
            cur = mailbox.get(env_id)
            if cur is None or cur.state != "accepted":
                # While `hc send` was in flight the hook already took the input (`consumed`/`answered`) or a wider
                # batch superseded it: keep that later state (`consumed -> typed` is illegal), only drop the
                # attempt's intent/hold. The hook already opened the turn, so no `send_submitted` here.
                if cur is not None and not cur.is_terminal():
                    mailbox.update_hold_reason(env_id, "", now_ms=now_ms, clear_intent=True)
                if callable(on_typed) and cur is not None:
                    on_typed(cur, outcome)
                return outcome
            typed_item = mailbox.transition(
                env_id,
                "typed",
                now_ms=now_ms,
                attempts=attempt,
                endpoint_epoch=int(endpoint.epoch or 1),
                target_endpoint_uid=endpoint.uid,
                hold_reason="",
                clear_intent=True,
                meta=typed_meta(cur, outcome),
            )
            typed_item = close_if_no_reply(mailbox, typed_item, outcome, now_ms)
            obs: dict[str, Any] = {
                "src": "supervisor",
                "kind": "send_submitted",
                "t": now_ms,
                "terminal": endpoint.terminal,
                "agent_kind": endpoint.agent_kind,
                "cause": cause,
                "msg_ids": all_msg_ids,
                "hc_turn": int(outcome.observed_turn or 0),
                "started": bool(outcome.started_turn is not False),
                "endpoint": endpoint.to_dict(),
            }
            batch = (int(body["start"]), int(body["end"])) if ("start" in body and "end" in body) else None
            if batch:
                obs["batch"] = list(batch)
            self.tracker.append_observation(obs, reduce_now=True)
            if callable(on_typed):
                on_typed(typed_item, outcome)
            return outcome

        if outcome.status == "timeout_uncertain":
            # Keep C3 intent intact so the next tick checks turn/status_ms progression before retrying.
            mailbox.update_hold_reason(env_id, "timeout_uncertain", now_ms=now_ms, clear_intent=False)
            return outcome

        reason_map = {
            "status_mismatch": "pm_working",
            "blocked_prompt": "blocked_prompt",
            "endpoint_gone": "endpoint_gone",
            "partitioned": "machine_disconnected",
            "rejected": outcome.detail or "rejected",
        }
        reason = reason_map.get(outcome.status, outcome.status)
        mailbox.update_hold_reason(env_id, reason, now_ms=now_ms, clear_intent=True)
        return outcome

    def _reconcile_stale_intents(
        self,
        mailbox: MailboxStore,
        endpoint: Endpoint,
        info: Mapping[str, Any] | None,
        *,
        now_ms: int,
    ) -> None:
        _, a_state, _, cur_sms, cur_turn, _ = _status_parts(info)
        for item in mailbox.active_items(("accepted",)):
            intent = item.intent
            if not isinstance(intent, Mapping):
                continue
            intent_uid = str(intent.get("endpoint_uid") or "")
            if intent_uid and intent_uid != endpoint.uid:
                continue
            pre_turn = int(intent.get("pre_turn") or 0)
            pre_sms = int(intent.get("pre_status_ms") or 0)
            advanced = (pre_turn > 0 and cur_turn > pre_turn) or (
                pre_sms > 0 and cur_sms > pre_sms and a_state == "working"
            )
            if advanced:
                mailbox.transition(
                    item.envelope.env_id,
                    "typed",
                    now_ms=now_ms,
                    attempts=int(intent.get("attempt") or item.next_attempt()),
                    endpoint_epoch=int(endpoint.epoch or 1),
                    target_endpoint_uid=endpoint.uid,
                    hold_reason="",
                    clear_intent=True,
                    meta={**item.meta, "attempts_preincremented": False},
                )
            else:
                mailbox.clear_intent(item.envelope.env_id, now_ms=now_ms)

    def _check_undelivered_alerts(
        self,
        mailbox: MailboxStore,
        now_ms: int,
        on_undelivered_alert: Any = None,
    ) -> None:
        for item in mailbox.active_items(("accepted",)):
            if item.meta.get("undelivered_alerted"):
                continue
            threshold = UNDELIVERED_P1_P3_ALERT_MS if item.envelope.priority <= 3 else UNDELIVERED_P4_ALERT_MS
            age_ms = max(0, now_ms - int(item.accepted_ms or item.envelope.created_ms or now_ms))
            if age_ms < threshold:
                continue
            alert_env = Envelope(
                env_id=new_env_id(now_ms),
                idempotency_key=f"alert_undelivered:{item.envelope.env_id}",
                schema_version=1,
                created_ms=now_ms,
                kind="alert.undelivered",
                sender=Principal.supervisor(self.slug),
                recipient=LogicalAddress.ui(self.slug),
                project=self.slug,
                cause={"kind": "undelivered_sla", "env_id": item.envelope.env_id},
                priority=item.envelope.priority,
                body={
                    "env_id": item.envelope.env_id,
                    "wait_seconds": int(age_ms // 1000),
                    "reason": item.hold_reason or item.last_error or "queued",
                },
            )
            decision = self._router.route(alert_env, RoutingSnapshot(project=self.slug, now_ms=now_ms))
            self.tracker.append_observation(
                {
                    "src": "supervisor",
                    "kind": "undelivered_alert",
                    "t": now_ms,
                    "env_id": item.envelope.env_id,
                    "wait_seconds": int(age_ms // 1000),
                    "targets": list(decision.targets),
                },
                reduce_now=False,
            )
            if callable(on_undelivered_alert):
                # A human channel that fails (Discord down) never keeps this alert from being marked sent.
                unfailing(on_undelivered_alert, item, alert_env, decision)
            new_meta = dict(item.meta)
            new_meta["undelivered_alerted"] = True
            new_meta["undelivered_alert"] = {
                "at_ms": now_ms,
                "wait_seconds": int(age_ms // 1000),
                "reason": item.hold_reason or item.last_error or "queued",
                "targets": list(decision.targets),
            }
            mailbox.transition(item.envelope.env_id, item.state, now_ms=now_ms, meta=new_meta)

    def drive_pm_endpoint(
        self,
        rec: Mapping[str, Any],
        info: Mapping[str, Any] | None,
        *,
        held: bool = False,
        ep_snap_override: EndpointSnapshot | None = None,
        on_typed: Any = None,
        on_undelivered_alert: Any = None,
    ) -> tuple[DeliverOutcome | None, float | None]:
        """Run one non-blocking single-typist pass on the project's PM endpoint."""
        now_ms = int(float(self.ctx.clock.time()) * 1000)
        self.tracker.ensure_mailbox_migrated()
        mailbox = self.tracker.pm_mailbox

        ep = _endpoint_with_live(rec, info)
        if ep is None:
            raw_term = str(rec.get("terminal") or rec.get("pane") or "").strip()
            ep = parse_legacy_endpoint(raw_term, runtime_hint="hc") if raw_term else None
        if ep is None:
            self.tracker.sync_mailbox_projection(now_ms)
            return None, None

        # G4: automatically re-queue any typed-but-unconsumed envelopes from an older session epoch.
        mailbox.requeue_unconsumed_on_epoch_change(int(ep.epoch or 1), now_ms=now_ms, endpoint_uid=ep.uid)

        # Single typist: the lease covers the whole send, from the intent until the async `hc send` settles, not
        # just this pass. Take it, or renew it while our own send is still in flight; release it (in `finally`)
        # only once nothing of ours is in flight, so `deliver_under_typist_lock` (notify, still_running, the seat
        # opening prompt) can never type into the terminal while `hc send` still waits on it.
        owner_pid = os.getpid()
        have_lease = mailbox.acquire_typist_lease(
            ep.uid, owner_pid, ttl_ms=TYPIST_LEASE_TTL_MS, now_ms=now_ms, owner=self._lease_owner
        )
        active_entry = self._active.get(ep.uid)
        if active_entry is None and not have_lease:
            return None, 0.5

        try:
            if active_entry is not None:
                # Our own send is in flight: poll it (even if the lease could not be renewed, settling types nothing).
                act_env_id, handle, act_ep, started_ms, attempt, act_on_typed = active_entry
                outcome = handle.poll()
                if outcome is None:
                    if (now_ms - started_ms) >= WAIT_DRAFT_FLAG_MS:
                        mailbox.update_hold_reason(act_env_id, "waiting_quiet_or_draft", now_ms=now_ms)
                    self.tracker.sync_mailbox_projection(now_ms)
                    return None, 0.5
                self._active.pop(ep.uid, None)
                item = mailbox.get(act_env_id)
                if item is not None:
                    # Report to this pass's caller: the callback stored when the send started belongs to a pass
                    # that already returned (its collector is gone), so the deliverer would never see the typed batch.
                    settled = self._settle_deliver_outcome(
                        mailbox, item, act_ep, outcome, attempt=attempt, now_ms=now_ms,
                        on_typed=on_typed if callable(on_typed) else act_on_typed,
                    )
                    self.tracker.sync_mailbox_projection(now_ms)
                    if settled.status == "typed":
                        return settled, 0
                    return settled, None
                if not have_lease:
                    return None, 0.5

            self._reconcile_stale_intents(mailbox, ep, info, now_ms=now_ms)
            self._check_undelivered_alerts(mailbox, now_ms, on_undelivered_alert=on_undelivered_alert)

            pending = mailbox.pending_for_endpoint(ep.uid)
            if not pending:
                self.tracker.sync_mailbox_projection(now_ms)
                return None, None

            t_state, a_state, s_msg, cur_sms, cur_turn, reported = _status_parts(info)
            st_cur = self.tracker.read()
            phase_cur = str((st_cur.get("turn") or {}).get("phase") or st_cur.get("phase") or "")
            if phase_cur == "working" and isinstance(st_cur.get("activity"), Mapping) and st_cur["activity"].get("kind") == "recovering":
                phase_cur = "recovering"
            last_stopped: bool | None = True if phase_cur == "idle" else (False if phase_cur in ("working", "stalled") else None)
            transport = self._transport_for(ep)
            if ep_snap_override is not None:
                ep_snap = ep_snap_override
            else:
                if isinstance(transport, (LocalHcTransport, RemoteHcTransport)):
                    caps = transport.capabilities(ep, pre_info=info)
                else:
                    caps = transport.capabilities(ep)
                can_report = bool(reported and caps.can_report_status)
                ep_snap = EndpointSnapshot(
                    endpoint=ep,
                    live_state=t_state or "live",
                    agent_state=a_state,
                    status_msg=s_msg,
                    can_report_status=can_report,
                    can_interrupt=caps.can_interrupt,
                    link_state="connected" if t_state == "live" else "disconnected",
                    turn_phase=phase_cur,
                    last_turn_stopped=last_stopped,
                    seat_starting=self.tracker.files.next_session.is_file(),
                    recovery_hold=incident_holds_batch(st_cur),
                    blocking_dialog=(a_state == "blocked"),
                )

            tasks_map = {}
            for raw_t in self.ctx.store.tasks():
                if isinstance(raw_t, dict) and raw_t.get("id"):
                    tasks_map[str(raw_t["id"])] = raw_t

            snap = RoutingSnapshot(
                project=self.slug,
                now_ms=now_ms,
                endpoints={f"pm://{self.slug}": ep},
                endpoint_states={f"pm://{self.slug}": ep_snap},
                tasks=tasks_map,
            )

            for item in pending:
                if item.envelope.kind == "event.batch":
                    stale = _stale_batch_reason(self.ctx, self.repo, item)
                    if stale:
                        mailbox.transition(
                            item.envelope.env_id,
                            "superseded",
                            now_ms=now_ms,
                            hold_reason=stale,
                            clear_intent=True,
                        )
                        sb = item.envelope.body if isinstance(item.envelope.body, Mapping) else {}
                        b_end = sb.get("end")
                        if self.repo and isinstance(b_end, int) and not isinstance(b_end, bool) and b_end > 0:
                            Delivery(self.ctx, self.repo).advance_delivered(b_end)
                        continue
                if held and item.envelope.kind == "event.batch":
                    mailbox.update_hold_reason(item.envelope.env_id, "held", now_ms=now_ms)
                    continue
                dec = self._router.route(item.envelope, snap)
                if dec.action == "drop_duplicate":
                    mailbox.transition(item.envelope.env_id, "superseded", now_ms=now_ms, hold_reason=dec.hold_reason)
                    continue
                if dec.action == "hold":
                    mailbox.update_hold_reason(item.envelope.env_id, dec.hold_reason, now_ms=now_ms)
                    continue
                if dec.action != "deliver":
                    continue

                attempt = item.next_attempt()
                retry_note = f"retry #{attempt}" if attempt > 1 else ""
                occ_hint = ""
                if item.envelope.kind == "event.batch":
                    hint_line = attach_occupation_hint(self.ctx, self.tracker, "")
                    if hint_line:
                        occ_hint = hint_line

                mailbox.record_intent(
                    item.envelope.env_id,
                    pre_turn=cur_turn,
                    pre_status_ms=cur_sms,
                    pre_working=(a_state == "working"),
                    attempt=attempt,
                    endpoint_uid=ep.uid,
                    now_ms=now_ms,
                )

                kw: dict[str, Any] = {
                    "if_idle": bool(dec.if_idle_only and a_state not in ("done", "error")),
                    "timeout_s": 70.0,
                }
                if isinstance(transport, (LocalHcTransport, RemoteHcTransport)):
                    kw["occupation_hint"] = occ_hint
                    kw["retry_note"] = retry_note
                    kw["pre_info"] = info

                start_fn = getattr(transport, "start_deliver_async", None)
                if callable(start_fn):
                    handle = start_fn(ep, item, **kw)
                    outcome = handle.poll()
                    if outcome is None:
                        self._active[ep.uid] = (item.envelope.env_id, handle, ep, now_ms, attempt, on_typed)
                        if item.hold_reason == "":
                            mailbox.update_hold_reason(item.envelope.env_id, "typing", now_ms=now_ms)
                        self.tracker.sync_mailbox_projection(now_ms)
                        return None, 0.5
                else:
                    outcome = transport.deliver(ep, item, **kw)

                settled = self._settle_deliver_outcome(
                    mailbox, item, ep, outcome, attempt=attempt, now_ms=now_ms, on_typed=on_typed
                )
                self.tracker.sync_mailbox_projection(now_ms)
                if settled.status == "typed":
                    return settled, 0
                return settled, None

            self.tracker.sync_mailbox_projection(now_ms)
            return None, None
        finally:
            if have_lease and ep.uid not in self._active:
                mailbox.release_typist_lease(ep.uid, owner_pid, owner=self._lease_owner)


def _registration_endpoint(rec: Mapping[str, Any]) -> Endpoint | None:
    rec_ep = record_endpoint(rec)
    if rec_ep is None and rec.get("terminal"):
        rec_ep = parse_legacy_endpoint(str(rec["terminal"]), runtime_hint="hc")
    elif rec_ep is None and rec.get("pane"):
        pane = str(rec["pane"])
        rec_ep = parse_legacy_endpoint(pane, str(rec.get("session") or ""),
                                       runtime_hint="hc" if pane.startswith("hc:") else "tui")
    return rec_ep


def _endpoint_home(ctx: Context, ep: Endpoint, repo: str | Path = "") -> tuple[str, bool, int]:
    """`(repo, drained, epoch)` for `ep`: the project whose PM `ep` is (the given `repo`, else found by endpoint
    uid); whether that project's deliverer (`EndpointDriver`) drains its PM mailbox into `ep` (only a desktop-app
    PM's is: an envelope left `accepted` anywhere else would never be typed); and the registration's session epoch
    for `ep` (0 when unknown). Callers that only know a terminal (`parse_legacy_endpoint` -> epoch 1) must stamp
    this epoch, or the driver's G4 pass takes what they type for an old session's."""
    projects = ProjectRegistry(ctx)
    found = str(repo or "")
    rec_found: Mapping[str, Any] | None = None
    try:
        if found:
            rec_found = projects.pm_record(found)
        else:
            for rec in projects.pm_records():
                if rec.get("archived") or not rec.get("repo"):
                    continue
                rec_ep = _registration_endpoint(rec)
                if rec_ep is not None and rec_ep.uid == ep.uid:
                    found, rec_found = str(rec["repo"]), rec
                    break
    except Exception:  # noqa: BLE001 - a half-written registration: no epoch, not drained (bounded wait path)
        rec_found = None
    epoch = 0
    if isinstance(rec_found, Mapping):
        reg_ep = _registration_endpoint(rec_found)
        if reg_ep is not None and reg_ep.uid == ep.uid:
            epoch = int(reg_ep.epoch or 1)
    if not found or ep.runtime != "hc":
        return found, False, epoch
    try:
        app = projects.app_pm(found) or {}
    except Exception:  # noqa: BLE001
        app = {}
    return found, str(app.get("terminal") or "") == ep.terminal, epoch


def _turn_started_since(info: Mapping[str, Any] | None, pre_turn: int, pre_status_ms: int) -> bool:
    """True when the terminal moved on since a send (`turn` counts finished turns; `working` with a newer
    `status_ms` is a turn still running)."""
    _, a_state, _, cur_sms, cur_turn, _ = _status_parts(info)
    return cur_turn > pre_turn or (a_state == "working" and cur_sms > pre_status_ms)


def _known_outcome(item: MailboxItem) -> DeliverOutcome:
    """What is already known about an envelope that is past `accepted` (no fake `started_turn=True`)."""
    if item.state == "typed":
        started = item.meta.get("typed_started")
        return DeliverOutcome(status="typed", started_turn=started if isinstance(started, bool) else None,
                              detail="already_typed")
    if item.state in ("consumed", "answered"):
        started = item.meta.get("typed_started")
        return DeliverOutcome(status="typed", started_turn=started if isinstance(started, bool) else True,
                              detail=f"already_{item.state}")
    return DeliverOutcome(status="rejected", detail=f"already_{item.state}")


def deliver_under_typist_lock(
    ctx: Context,
    ep: Endpoint,
    env: Envelope,
    *,
    repo: str | Path = "",
    if_idle: bool = False,
    timeout_s: float = 30.0,
    attempts: int = 1,
    transport: Any | None = None,
    retry_unstarted: bool = False,
) -> DeliverOutcome | None:
    """Enqueue `env` and type it only while holding the endpoint's `typist.lock` (shared by every mailbox).

    Returns None when another typist holds the lease and this endpoint's deliverer drains the mailbox: the envelope
    stays `accepted` for that single typist. Where nothing drains it, waits (bounded) for the lease and, if it never
    frees, fails the envelope and says so (`rejected`/`typist_busy`) instead of leaving it queued forever.
    Records the C3 `intent` before typing and moves the item to `typed`, so `EndpointDriver` never types it again.

    An envelope already past `accepted` (same idempotency key) is not typed again and its real outcome is returned;
    with `retry_unstarted`, one that was typed without its turn starting (and whose terminal has not moved on since)
    goes back to `accepted` and is typed again (the seat opening prompt's retry)."""
    now_ms = int(float(ctx.clock.time()) * 1000)
    found_repo, drained, reg_epoch = _endpoint_home(ctx, ep, repo)
    if reg_epoch and reg_epoch != int(ep.epoch or 1):
        ep = dataclasses.replace(ep, epoch=reg_epoch)
    tracker: TurnTracker | None = None
    if found_repo:
        tracker = TurnTracker(ctx, found_repo)
        tracker.ensure_mailbox_migrated()
        mailbox = tracker.pm_mailbox
    else:
        mailbox = MailboxStore(
            ctx.home.endpoint_mailbox(safe_endpoint_uid(ep)), clock=ctx.clock, typist_dir=ctx.home.typists
        )

    item, _ = mailbox.enqueue(
        env,
        initial_state="accepted",
        now_ms=now_ms,
        target_endpoint_uid=ep.uid,
        endpoint_epoch=int(ep.epoch or 1),
    )
    if item.state == "typed" and retry_unstarted and item.meta.get("typed_started") is False:
        live = ctx.hc.get_raw(ep.hc_target, errors=True) if ep.runtime == "hc" and ep.hc_target else None
        if not isinstance(live, Mapping) or live.get("error"):
            return _known_outcome(item)
        if _turn_started_since(live, int(item.meta.get("typed_pre_turn") or 0),
                               int(item.meta.get("typed_pre_status_ms") or 0)):
            late = mailbox.transition(item.envelope.env_id, "typed", now_ms=now_ms, meta={"typed_started": True})
            out_late = DeliverOutcome(status="typed", started_turn=True, detail="started_late")
            close_if_no_reply(mailbox, late, out_late, now_ms)
            return out_late
        item = mailbox.transition(item.envelope.env_id, "accepted", now_ms=now_ms, hold_reason="retry_unstarted",
                                  clear_intent=True)
    if item.state != "accepted":
        return _known_outcome(item)

    owner_pid = os.getpid()
    owner = f"{owner_pid}:{os.urandom(4).hex()}"
    lease_ttl_ms = int((float(timeout_s) + 10.0) * 1000)
    have_lease = mailbox.acquire_typist_lease(ep.uid, owner_pid, ttl_ms=lease_ttl_ms, now_ms=now_ms, owner=owner)
    if not have_lease and drained:
        mailbox.update_hold_reason(item.envelope.env_id, "typist_busy", now_ms=now_ms)
        if tracker is not None:
            tracker.sync_mailbox_projection(now_ms)
        unfailing(Delivery(ctx, found_repo).ensure_running)
        return None
    if not have_lease:
        # Nobody drains this mailbox: whoever types holds the lease for one short send; wait it out, bounded.
        deadline = ctx.clock.monotonic() + float(timeout_s) + 5.0
        while not have_lease and ctx.clock.monotonic() < deadline:
            ctx.clock.sleep(0.5)
            have_lease = mailbox.acquire_typist_lease(
                ep.uid, owner_pid, ttl_ms=lease_ttl_ms, now_ms=int(float(ctx.clock.time()) * 1000), owner=owner
            )
        if not have_lease:
            gave_up_ms = int(float(ctx.clock.time()) * 1000)
            cur_busy = mailbox.get(item.envelope.env_id)
            if cur_busy is not None and cur_busy.state == "accepted":
                mailbox.transition(item.envelope.env_id, "failed", now_ms=gave_up_ms, error="typist_busy",
                                   hold_reason="typist_busy")
            if tracker is not None:
                tracker.sync_mailbox_projection(gave_up_ms)
            return DeliverOutcome(status="rejected", detail="typist_busy")

    try:
        cur = mailbox.get(item.envelope.env_id)
        if cur is None or cur.state != "accepted":
            return _known_outcome(cur) if cur is not None else DeliverOutcome(status="rejected", detail="gone")

        pre_turn = 0
        pre_sms = 0
        pre_a_state = ""
        pre_info: Mapping[str, Any] | None = None
        if ep.runtime == "hc" and ep.hc_target:
            raw_info = ctx.hc.get_raw(ep.hc_target)
            if isinstance(raw_info, Mapping) and not raw_info.get("error"):
                pre_info = raw_info
                _, pre_a_state, _, pre_sms, pre_turn, _ = _status_parts(raw_info)

        attempt_num = max(int(attempts or 1), cur.next_attempt())
        cur = mailbox.record_intent(
            cur.envelope.env_id,
            pre_turn=pre_turn,
            pre_status_ms=pre_sms,
            pre_working=(pre_a_state == "working"),
            attempt=attempt_num,
            endpoint_uid=ep.uid,
            now_ms=now_ms,
        )

        if transport is None:
            transport = transport_for(ctx, ep)
        kw: dict[str, Any] = {"if_idle": bool(if_idle), "timeout_s": float(timeout_s)}
        if isinstance(transport, (LocalHcTransport, RemoteHcTransport)) and pre_info is not None:
            kw["pre_info"] = pre_info
        outcome = transport.deliver(ep, cur, **kw)

        done_ms = int(float(ctx.clock.time()) * 1000)
        after = mailbox.get(cur.envelope.env_id)
        if outcome.status == "typed":
            if after is not None and after.state == "accepted":
                typed_now = mailbox.transition(
                    cur.envelope.env_id,
                    "typed",
                    now_ms=done_ms,
                    attempts=attempt_num,
                    endpoint_epoch=int(ep.epoch or 1),
                    target_endpoint_uid=ep.uid,
                    hold_reason="",
                    clear_intent=True,
                    meta=typed_meta(cur, outcome),
                )
                close_if_no_reply(mailbox, typed_now, outcome, done_ms)
            elif after is not None and not after.is_terminal():
                mailbox.update_hold_reason(cur.envelope.env_id, "", now_ms=done_ms, clear_intent=True)
            if tracker is not None:
                cause = str((cur.envelope.cause or {}).get("kind") or cur.envelope.kind or "cmd")
                tracker.append_observation(
                    {
                        "src": "deliverer",
                        "kind": "deliver_typed",
                        "t": done_ms,
                        "env_id": cur.envelope.env_id,
                        "terminal": ep.terminal,
                        "agent_kind": ep.agent_kind,
                        "cause": cause,
                        "msg_ids": [],
                        "hc_turn": int(outcome.observed_turn or 0),
                        "started": bool(outcome.started_turn is not False),
                        "endpoint": ep.to_dict(),
                    },
                    reduce_now=True,
                )
        elif outcome.status == "timeout_uncertain":
            mailbox.update_hold_reason(cur.envelope.env_id, "timeout_uncertain", now_ms=done_ms, clear_intent=False)
        else:
            mailbox.update_hold_reason(
                cur.envelope.env_id,
                outcome.detail or outcome.status or "held",
                now_ms=done_ms,
                clear_intent=True,
            )

        if tracker is not None:
            tracker.sync_mailbox_projection(done_ms)
        return outcome
    finally:
        mailbox.release_typist_lease(ep.uid, owner_pid, owner=owner)


def _degraded_state_from_terminal(
    base_state: Mapping[str, Any],
    reg: Mapping[str, Any],
    info: Mapping[str, Any] | None,
    live_pm: Mapping[str, Any] | None,
    now_ms: int,
    files: Any,
    procs: Any,
    cfg: Any,
) -> dict[str, Any]:
    """Build a degraded read-only snapshot when supervisor heartbeat is stale (§3.3, I4)."""
    ep = _endpoint_with_live(reg, info)
    t_state, a_state, s_msg, s_ms, hc_turn, reported = _status_parts(info, live_pm)
    degraded = default_state_v2(cfg)
    degraded["outbox"] = list(base_state.get("outbox") or [])
    # The mailbox projection does not depend on the supervisor: the UI still shows where each message is.
    if isinstance(base_state.get("inbox"), list):
        degraded["inbox"] = list(base_state["inbox"])
    if isinstance(base_state.get("undelivered"), Mapping):
        degraded["undelivered"] = dict(base_state["undelivered"])
    if ep is not None:
        degraded["session"] = ep.to_dict()
    turn = degraded["turn"]
    turn["seq"] = int(base_state.get("turn_seq") or 0)
    turn["hc_turn"] = hc_turn
    turn["health"] = "unknown"
    turn["health_reason"] = "supervisor_stale"

    if t_state in ("offline", "exited", "finished", "removed"):
        turn["phase"] = "starting" if files.next_session.is_file() else "offline"
        return sync_compat_fields(degraded)

    m_bg = _BG_SHELL_MSG_RE.search(s_msg)
    bg_cmds: list[str] = []
    if m_bg:
        bg_count = int(m_bg.group(1) or 1)
    elif a_state == "working" and str(base_state.get("phase") or "idle") == "idle" and isinstance(info, Mapping):
        bg_cmds = list(procs.background_work(info))
        bg_count = len(bg_cmds)
    else:
        bg_count = 0
    degraded["bg_shells"] = {"count": bg_count, "commands": bg_cmds}

    if a_state in ("blocked", "error"):
        turn["phase"] = "blocked"
        turn["started_ms"] = s_ms or now_ms
        turn["phase_since_ms"] = s_ms or now_ms
        return sync_compat_fields(degraded)

    if a_state == "working" and bg_count > 0 and (m_bg or str(base_state.get("phase") or "idle") == "idle"):
        turn["phase"] = "idle"
        return sync_compat_fields(degraded)

    if a_state == "working" or (not a_state and str(base_state.get("phase") or "idle") in ("working", "stalled")):
        obs_start = s_ms if s_ms > 0 else (int(base_state.get("started_ms") or 0) or now_ms)
        turn["phase"] = "generating"
        turn["started_ms"] = obs_start
        turn["phase_since_ms"] = obs_start
        turn["last_progress_ms"] = obs_start
        turn["evidence"]["hc"] = {
            "state": a_state,
            "status_ms": s_ms,
            "obs_ms": now_ms,
            "turn": hc_turn,
            "reported": reported,
        }
        return sync_compat_fields(degraded)

    turn["phase"] = "idle"
    return sync_compat_fields(degraded)


def format_occupation_hint(ctx: Context, hint: Mapping[str, Any]) -> str:
    """Format a one-line occupation feedback hint when a user turn exceeded soft budget (§3.8 O-c, D7)."""
    total_s = max(1, round(int(hint.get("total_ms") or 0) / 1000.0))
    soft_s = max(1, round(int(hint.get("soft_ms") or 45_000) / 1000.0))
    action_ms = hint.get("action_ms") if isinstance(hint.get("action_ms"), Mapping) else {}
    parts_en: list[str] = []
    parts_zh: list[str] = []
    ranked = sorted(
        ((str(k), int(v)) for k, v in action_ms.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and int(v) >= 1000),
        key=lambda kv: (-kv[1], kv[0]),
    )[:3]
    for cat, ms in ranked:
        sec = max(1, round(ms / 1000.0))
        if cat == "generate":
            parts_en.append(f"generating {sec}s")
            parts_zh.append(f"生成 {sec} 秒")
        else:
            parts_en.append(f"{cat} {sec}s")
            parts_zh.append(f"{cat} {sec} 秒")
    detail_en = f": {', '.join(parts_en)}" if parts_en else ""
    detail_zh = f"：{'、'.join(parts_zh)}" if parts_zh else ""
    return ctx.config.tr(
        f"[Occupation hint] Last foreground turn took {total_s}s (budget {soft_s}s){detail_en}. "
        "Use `pm.py dispatch --ask` for delegation and offload investigation to threads.",
        f"〔占用提示〕上一轮前台 {total_s} 秒（预算 {soft_s} 秒）{detail_zh}。"
        "派活用 `pm.py dispatch --ask`，调查交给线程。",
    )


def attach_occupation_hint(
    ctx: Context,
    tracker: TurnTracker,
    payload: str,
    *,
    now_ms: int | None = None,
    cooldown_ms: int = OCCUPATION_HINT_COOLDOWN_MS,
) -> str:
    """Attach a rate-limited one-line occupation hint before the next delivered payload if over budget (§3.8 O-c)."""
    hint = tracker.consume_occupation_hint(now_ms=now_ms, cooldown_ms=cooldown_ms)
    if not hint:
        return payload
    line = format_occupation_hint(ctx, hint)
    return f"{line}\n{payload}" if payload else line


def read_pm_turn_view(
    ctx: Context,
    slug_or_repo: str | Path,
    reg: Mapping[str, Any] | None,
    *,
    term_info: Mapping[str, Any] | None = None,
    live_pm: Mapping[str, Any] | None = None,
    revive: bool = True,
) -> dict[str, Any]:
    """Unified reader contract (§3.3, §4.8) used by BOTH `pm.py state` and `pm.py project events`.

    Returns `{"turn": <v1_projection>, "turn2": <v2_payload>, "supervised": bool}`.
    """
    now_ms = int(ctx.clock.time() * 1000)
    raw_cfg = None
    if ctx.config is not None:
        reader = getattr(ctx.config, "read", None)
        if callable(reader):
            raw_cfg = reader()
        if not isinstance(raw_cfg, Mapping):
            raw_cfg = getattr(ctx.config, "data", None)
    cfg = turn_config_from_dict(raw_cfg if isinstance(raw_cfg, Mapping) else None)
    tracker = TurnTracker(ctx, slug_or_repo)
    if not isinstance(reg, Mapping):
        empty = default_state_v2(cfg)
        empty["turn"]["phase"] = "offline"
        empty["turn"]["health"] = "unknown"
        return {
            "turn": project_v1_turn(empty, now_ms, supervised=False),
            "turn2": build_turn2_payload(empty, now_ms, supervised=False, beat_age_ms=None),
            "supervised": False,
        }

    # 1. Catch up any unreduced journal lines under lock before reading snapshot (§3.3 step 1).
    state, _ = tracker.sync_journal(tick_now=True, cfg=cfg)
    beat_age = heartbeat_age_ms(tracker.files.pm_turn_beat, now_ms)
    supervised = beat_age is not None and beat_age <= cfg.heartbeat_stale_ms

    # 2. Supervised path: return snapshot directly (I3), reconciling basic hc offline/bg edge only if needed.
    if supervised:
        return {
            "turn": project_v1_turn(state, now_ms, supervised=True),
            "turn2": build_turn2_payload(state, now_ms, supervised=True, beat_age_ms=beat_age),
            "supervised": True,
        }

    # 3. Stale/missing heartbeat path: non-blocking supervisor revival + degraded terminal-only view (I4).
    ep = record_endpoint(reg)
    is_hc = bool((ep is not None and ep.runtime == "hc") or reg.get("runtime") == "hc" or str(reg.get("pane") or "").startswith("hc:"))
    term_addr = (ep.hc_target if ep is not None else "") or str(reg.get("terminal") or "")
    info = term_info
    if info is None and is_hc and term_addr:
        raw_info = ctx.hc.get_raw(term_addr, errors=True)
        if isinstance(raw_info, Mapping) and not raw_info.get("error"):
            info = raw_info

    is_offline = (
        (isinstance(info, Mapping) and info.get("state") in ("exited", "finished", "removed"))
        or (isinstance(live_pm, Mapping) and live_pm.get("agent_status") == "offline")
    )
    repo = str(reg.get("repo") or "")
    if revive and is_hc and repo and not reg.get("archived") and not is_offline:
        if beat_age is not None and beat_age > cfg.w7_stale_kill_ms:
            dlv = Delivery(ctx, repo)
            if dlv.is_running():
                beat_pid = _read_beat_pid(tracker.files.pm_turn_beat)
                if beat_pid > 1 and beat_pid != os.getpid():
                    repo_name = Path(repo).name
                    expected_tokens = ("pm.py", "deliver", repo_name) if repo_name else ("pm.py", "deliver")
                    ctx.procs.terminate_pid(beat_pid, expected_substrings=expected_tokens)
        unfailing(Delivery(ctx, repo).ensure_running)

    degraded = _degraded_state_from_terminal(
        state,
        reg,
        info,
        live_pm,
        now_ms,
        tracker.files,
        ctx.procs,
        cfg,
    )
    return {
        "turn": project_v1_turn(degraded, now_ms, supervised=False),
        "turn2": build_turn2_payload(degraded, now_ms, supervised=False, beat_age_ms=beat_age),
        "supervised": False,
    }
