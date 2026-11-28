"""Pure observation reducer, structured `Endpoint`, turn identity, v1/v2 projection, and journal redaction.

Layer 2. Standard library only: zero IO, zero clock calls, zero subprocesses, deterministic given
`(state, observation, now_ms, cfg)` (Invariants I1-I5).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import re
from typing import Any, Mapping


_HC_REMOTE_ADDR_RE = re.compile(r"^([^/:]+)/([tT][0-9a-zA-Z]+)$")
_HOME_USER_POSIX_RE = re.compile(r"(/(?:Users|home))/([A-Za-z0-9._-]+)")
_HOME_USER_WIN_RE = re.compile(r"([A-Za-z]:\\Users\\)([^\\/:*?\"<>|\s]+)")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_TOKEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{12,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.I), r"\1[REDACTED_TOKEN]"),
    (
        re.compile(r"((?:api[_-]?key|token|secret|password|passwd|auth)\s*[=:]\s*['\"]?)([^\s'\",;]{6,})", re.I),
        r"\1[REDACTED]",
    ),
)
_RETRY_HINT_RE = re.compile(r"(?:attempt|retry|retrying)\s*[:#(]?\s*(\d+)|第\s*(\d+)\s*次", re.I)
_RETRY_MSG_RE = re.compile(
    r"\b(?:retrying|retry|attempt\s+\d+|429|503|rate.?limit|overloaded|eof|stream idle timeout|unavailable)\b"
    r"|重试|第\s*\d+\s*次",
    re.I,
)
_CAPACITY_ERR_RE = re.compile(r"\b(?:503|capacity|overloaded|429|rate.?limit)\b|配额|限流", re.I)

V1_PHASES = frozenset({"idle", "working", "stalled", "blocked", "starting", "offline"})
ACTIVE_TURN_PHASES = frozenset({"submitted", "generating", "tool", "waiting_upstream"})
RECOVERY_AUTO_MODES = frozenset({"off", "safe", "full"})
OCCUPATION_HINT_COOLDOWN_MS = 10 * 60_000  # §3.8 O-c: at most once every 10 minutes
INCIDENT_ACTIONS_LIMIT = 16


# Declarative recovery ladders for W1-W7 (`docs/design/pm-stuck-root-fix.md` §3.6).
# Each step is pure metadata interpreted by `next_recovery_action()` and `reduce()`.
RECOVERY_LADDERS: dict[str, tuple[dict[str, Any], ...]] = {
    "W1": (
        {"action": "interrupt_turn", "min_auto": "safe", "breaker": "interrupt", "delay_field": "", "verify_field": "verify_nudge_ms"},
        {"action": "continue_turn", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "verify_continue_ms"},
        {"action": "escalate_w2", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": ""},
    ),
    "W2": (
        {"action": "continue_turn", "min_auto": "safe", "breaker": "", "delay_field": "w2_retry1_delay_ms", "verify_field": "verify_continue_ms", "attempt": 1},
        {"action": "continue_turn", "min_auto": "safe", "breaker": "", "delay_field": "w2_retry2_delay_ms", "verify_field": "verify_continue_ms", "attempt": 2},
        {"action": "switch_profile", "min_auto": "full", "breaker": "rotation", "delay_field": "", "verify_field": "verify_restart_ms"},
        {"action": "notify_user", "min_auto": "off", "breaker": "", "delay_field": "", "verify_field": ""},
    ),
    "W3": (
        {"action": "unblock_safe_dialog", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "verify_nudge_ms"},
        {"action": "notify_user", "min_auto": "off", "breaker": "", "delay_field": "", "verify_field": ""},
    ),
    "W4": (
        {"action": "interrupt_tool", "signal": "SIGINT", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "w4_sigterm_delay_ms"},
        {"action": "interrupt_tool", "signal": "SIGTERM", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "w4_sigkill_delay_ms"},
        {"action": "interrupt_tool", "signal": "SIGKILL", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "w4_verify_delay_ms"},
        {"action": "interrupt_turn", "min_auto": "safe", "breaker": "interrupt", "delay_field": "", "verify_field": "verify_nudge_ms"},
        {"action": "continue_turn", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "verify_continue_ms", "tool_note": True},
        {"action": "notify_user", "min_auto": "off", "breaker": "", "delay_field": "", "verify_field": ""},
    ),
    "W5": (
        {"action": "classify_screen", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "verify_nudge_ms"},
        {"action": "interrupt_turn", "min_auto": "safe", "breaker": "interrupt", "delay_field": "", "verify_field": "verify_nudge_ms"},
        {"action": "continue_turn", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "verify_continue_ms"},
        {"action": "restart_seat", "min_auto": "safe", "breaker": "rotation", "delay_field": "", "verify_field": "verify_restart_ms"},
        {"action": "notify_user", "min_auto": "off", "breaker": "", "delay_field": "", "verify_field": ""},
    ),
    "W6": (
        {"action": "classify_screen", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "verify_nudge_ms"},
        {"action": "nudge_enter", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "verify_nudge_ms"},
        {"action": "retype_submitted", "min_auto": "safe", "breaker": "", "delay_field": "", "verify_field": "verify_continue_ms"},
        {"action": "notify_user", "min_auto": "off", "breaker": "", "delay_field": "", "verify_field": ""},
    ),
    "W7": (
        {"action": "restart_seat", "min_auto": "safe", "breaker": "rotation", "delay_field": "", "verify_field": "verify_restart_ms"},
        {"action": "notify_user", "min_auto": "off", "breaker": "", "delay_field": "", "verify_field": ""},
    ),
}


def _opt_int(val: Any) -> int | None:
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, float) and not isinstance(val, bool):
        return int(val)
    return None


def _opt_pos_int(val: Any) -> int | None:
    iv = _opt_int(val)
    return iv if iv is not None and iv > 0 else None


def _clean_msg_ids(val: Any) -> list[str]:
    if not isinstance(val, (list, tuple)):
        return []
    return [str(m) for m in val if m]


@dataclass(frozen=True)
class Endpoint:
    """Structured cross-machine-safe endpoint address (`pm-message-routing.md` §3.2)."""

    runtime: str
    machine: str | None = None
    terminal: str = ""
    workspace: str = ""
    session_id: str = ""
    agent_kind: str = ""
    fg_pid: int | None = None
    epoch: int = 1

    @property
    def uid(self) -> str:
        host = self.machine or "local"
        rt = "sh" if self.runtime == "self_hosted" else (self.runtime or "hc")
        term = self.terminal or "unknown"
        return f"{rt}:{host}:{term}"

    @property
    def hc_target(self) -> str:
        if self.runtime != "hc" or not self.terminal:
            return ""
        return f"{self.machine}/{self.terminal}" if self.machine else self.terminal

    @property
    def legacy_pane(self) -> str:
        if not self.terminal:
            return ""
        if self.runtime == "hc":
            return f"hc:{self.hc_target}"
        if self.runtime == "self_hosted":
            return f"sh:{self.machine or 'local'}/{self.terminal}"
        if self.runtime == "tui":
            return f"{self.workspace}/{self.terminal}" if self.workspace else self.terminal
        return self.terminal

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "machine": self.machine,
            "terminal": self.terminal,
            "workspace": self.workspace,
            "session_id": self.session_id,
            "agent_kind": self.agent_kind,
            "fg_pid": self.fg_pid,
            "epoch": int(self.epoch or 1),
        }


def endpoint_from_dict(data: Mapping[str, Any] | None) -> Endpoint | None:
    if not isinstance(data, Mapping):
        return None
    terminal = str(data.get("terminal") or "").strip()
    runtime = str(data.get("runtime") or "").strip()
    if not terminal and not runtime:
        return None
    if not runtime:
        runtime = "hc"
    machine_raw = data.get("machine")
    machine = str(machine_raw).strip() if isinstance(machine_raw, str) and machine_raw.strip() else None
    if "/" in terminal and runtime == "hc" and not machine:
        host, _, term_part = terminal.partition("/")
        if host and term_part:
            machine, terminal = host, term_part
    fg_pid = _opt_pos_int(data.get("fg_pid"))
    epoch_raw = _opt_pos_int(data.get("epoch"))
    return Endpoint(
        runtime=runtime,
        machine=machine,
        terminal=terminal,
        workspace=str(data.get("workspace") or "").strip(),
        session_id=str(data.get("session_id") or "").strip(),
        agent_kind=str(data.get("agent_kind") or "").strip().lower(),
        fg_pid=fg_pid,
        epoch=epoch_raw or 1,
    )


def parse_legacy_endpoint(
    raw_pane: str | None,
    raw_ws: str = "",
    agent_kind: str = "",
    *,
    runtime_hint: str = "",
    session_id: str = "",
    fg_pid: int | None = None,
    epoch: int = 1,
) -> Endpoint | None:
    """Parse legacy bare `pane` / `terminal` strings into a structured `Endpoint` (§3.3)."""
    text = str(raw_pane or "").strip()
    ws = str(raw_ws or "").strip()
    kind = str(agent_kind or "").strip().lower()
    sid = str(session_id or "").strip()
    hint = str(runtime_hint or "").strip().lower()
    ep_epoch = _opt_pos_int(epoch) or 1
    pid = _opt_pos_int(fg_pid)
    if not text:
        return None

    if text.startswith("hc:"):
        rest = text[3:].strip()
        if not rest:
            return None
        if "/" in rest:
            machine, _, term = rest.partition("/")
            if machine and term:
                return Endpoint(
                    runtime="hc", machine=machine, terminal=term, workspace=ws,
                    session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
                )
        return Endpoint(
            runtime="hc", machine=None, terminal=rest, workspace=ws,
            session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
        )

    if text.startswith("sh:"):
        rest = text[3:].strip()
        if "/" in rest:
            node, _, slot = rest.partition("/")
            return Endpoint(
                runtime="self_hosted", machine=node or None, terminal=slot, workspace=ws,
                session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
            )
        return Endpoint(
            runtime="self_hosted", machine=None, terminal=rest, workspace=ws,
            session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
        )

    if ":" in text:
        if "/" in text:
            sess, _, pane_id = text.partition("/")
            return Endpoint(
                runtime="tui", machine=None, terminal=pane_id, workspace=sess or ws,
                session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
            )
        return Endpoint(
            runtime="tui", machine=None, terminal=text, workspace=ws,
            session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
        )

    m_remote = _HC_REMOTE_ADDR_RE.match(text)
    if m_remote:
        return Endpoint(
            runtime="hc", machine=m_remote.group(1), terminal=m_remote.group(2), workspace=ws,
            session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
        )

    if "/" in text and hint == "hc":
        machine, _, term = text.partition("/")
        if machine and term:
            return Endpoint(
                runtime="hc", machine=machine, terminal=term, workspace=ws,
                session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
            )

    runtime = "hc" if hint == "hc" else ("self_hosted" if hint == "self_hosted" else "tui")
    return Endpoint(
        runtime=runtime, machine=None, terminal=text, workspace=ws,
        session_id=sid, agent_kind=kind, fg_pid=pid, epoch=ep_epoch,
    )


def record_endpoint(rec: Mapping[str, Any] | None) -> Endpoint | None:
    """Resolve a structured `Endpoint` from a PM registration or task dict, supporting both v2 `endpoint`
    and legacy `pane`/`terminal` fields."""
    if not isinstance(rec, Mapping):
        return None
    sess_meta = rec.get("agent_session") if isinstance(rec.get("agent_session"), Mapping) else {}
    worker_meta = rec.get("worker") if isinstance(rec.get("worker"), Mapping) else {}
    agent_kind = str(rec.get("agent") or worker_meta.get("kind") or sess_meta.get("kind") or "").strip().lower()
    session_id = str(sess_meta.get("id") or rec.get("session") or "").strip()
    fg_pid = _opt_pos_int(rec.get("fg_pid"))
    epoch = _opt_pos_int(rec.get("epoch")) or 1
    ws = str(rec.get("workspace") or "").strip()

    raw_ep = rec.get("endpoint")
    if isinstance(raw_ep, Mapping):
        ep = endpoint_from_dict(raw_ep)
        if ep is not None:
            return Endpoint(
                runtime=ep.runtime,
                machine=ep.machine,
                terminal=ep.terminal,
                workspace=ep.workspace or ws,
                session_id=ep.session_id or session_id,
                agent_kind=ep.agent_kind or agent_kind,
                fg_pid=ep.fg_pid or fg_pid,
                epoch=ep.epoch or epoch,
            )

    runtime_hint = str(rec.get("runtime") or "").strip().lower()
    pane = str(rec.get("pane") or "").strip()
    term = str(rec.get("terminal") or "").strip()
    if pane:
        return parse_legacy_endpoint(
            pane, ws, agent_kind, runtime_hint=runtime_hint, session_id=session_id, fg_pid=fg_pid, epoch=epoch,
        )
    if term:
        return parse_legacy_endpoint(
            term, ws, agent_kind, runtime_hint=runtime_hint or "hc", session_id=session_id, fg_pid=fg_pid, epoch=epoch,
        )
    return None


def format_turn_id(
    endpoint: Endpoint | Mapping[str, Any] | None,
    hc_turn: int,
    *,
    fg_pid: int | None = None,
) -> str:
    """Format turn identity as `<endpoint.uid>:<fg_pid>:<hc_turn + 1>` (§3.4 & §9.1)."""
    ep = endpoint if isinstance(endpoint, Endpoint) else endpoint_from_dict(endpoint)
    uid = ep.uid if ep is not None else "hc:local:unknown"
    pid = _opt_pos_int(fg_pid)
    if pid is None and ep is not None:
        pid = ep.fg_pid
    pid_val = pid if pid is not None else 0
    turn_num = max(0, _opt_int(hc_turn) or 0) + 1
    return f"{uid}:{pid_val}:{turn_num}"


@dataclass(frozen=True)
class TurnConfig:
    """Phase contract, heartbeat & recovery ladder thresholds (`config.json` -> `pm.turn` & `pm.recovery`)."""

    submitted_suspect_ms: int = 8_000
    submitted_stall_ms: int = 20_000
    generating_slow_ms: int = 75_000
    generating_pty_probe_after_ms: int = 10_000
    generating_pty_probe_interval_ms: int = 5_000
    generating_pty_suspect_ms: int = 20_000
    generating_pty_stall_ms: int = 45_000
    generating_no_step_stall_ms: int = 240_000
    tool_soft_ms: int = 30_000
    tool_suspect_ms: int = 60_000
    tool_suspect_stall_ms: int = 120_000
    tool_hard_ms: int = 180_000
    upstream_stall_ms: int = 300_000
    turn_soft_budget_ms: int = 45_000
    turn_hard_budget_ms: int = 120_000
    no_status_esc_idle_ms: int = 30_000
    heartbeat_stale_ms: int = 10_000
    recovery_auto: str = "safe"
    fallback_profiles: tuple[str, ...] = ()
    recovery_allow_trust: bool = True
    max_turn_interrupts: int = 2
    max_rotations_per_window: int = 1
    rotation_window_ms: int = 30 * 60_000
    w2_retry1_delay_ms: int = 20_000
    w2_retry2_delay_ms: int = 90_000
    w4_sigterm_delay_ms: int = 5_000
    w4_sigkill_delay_ms: int = 5_000
    w4_verify_delay_ms: int = 5_000
    verify_continue_ms: int = 15_000
    verify_nudge_ms: int = 5_000
    verify_restart_ms: int = 30_000
    incident_fold_window_ms: int = 60_000
    w7_stale_kill_ms: int = 60_000


def _norm_recovery_auto(val: Any) -> str:
    s = str(val or "").strip().lower()
    return s if s in RECOVERY_AUTO_MODES else "safe"


def _parse_fallback_profiles(val: Any) -> tuple[str, ...]:
    if isinstance(val, (list, tuple)):
        return tuple(str(x).strip() for x in val if str(x or "").strip())
    if isinstance(val, str) and val.strip():
        return tuple(p.strip() for p in val.split(",") if p.strip())
    return ()


DEFAULT_WORKER_TURN_CONFIG = TurnConfig(
    submitted_suspect_ms=10_000,
    submitted_stall_ms=25_000,
    generating_slow_ms=120_000,
    generating_pty_probe_after_ms=30_000,
    generating_pty_probe_interval_ms=10_000,
    generating_pty_suspect_ms=60_000,
    generating_pty_stall_ms=180_000,
    generating_no_step_stall_ms=0,
    tool_soft_ms=120_000,
    tool_suspect_ms=180_000,
    tool_suspect_stall_ms=180_000,
    tool_hard_ms=1_800_000,
    upstream_stall_ms=600_000,
    turn_soft_budget_ms=900_000,
    turn_hard_budget_ms=2_400_000,
    no_status_esc_idle_ms=60_000,
    recovery_auto="off",
)


def _parse_turn_config(
    raw: Mapping[str, Any] | None,
    *,
    section: str = "pm",
    defaults: TurnConfig | None = None,
) -> TurnConfig:
    base = defaults if defaults is not None else TurnConfig()
    if not isinstance(raw, Mapping):
        return base
    if section == "pm":
        sec_cfg = raw.get("pm") if isinstance(raw.get("pm"), Mapping) else raw
    else:
        if isinstance(raw.get(section), Mapping):
            sec_cfg = raw[section]
        elif "pm" in raw or "turn" in raw or "recovery" in raw:
            sec_cfg = {}
        else:
            sec_cfg = raw
    turn_cfg = sec_cfg.get("turn") if isinstance(sec_cfg.get("turn"), Mapping) else sec_cfg
    rec_cfg = sec_cfg.get("recovery") if isinstance(sec_cfg.get("recovery"), Mapping) else {}
    if not isinstance(turn_cfg, Mapping):
        turn_cfg = {}
    pm_rec = (raw.get("pm") or {}).get("recovery") if isinstance(raw.get("pm"), Mapping) else None
    kwargs: dict[str, Any] = {}
    for field_name in TurnConfig.__dataclass_fields__:
        if field_name == "recovery_auto":
            raw_auto = rec_cfg.get("auto") if "auto" in rec_cfg else sec_cfg.get("recovery_auto", turn_cfg.get("recovery_auto"))
            kwargs[field_name] = _norm_recovery_auto(raw_auto) if raw_auto is not None else base.recovery_auto
            continue
        if field_name == "fallback_profiles":
            raw_fp = rec_cfg.get("fallback_profiles") if "fallback_profiles" in rec_cfg else sec_cfg.get(
                "fallback_profiles", turn_cfg.get("fallback_profiles")
            )
            kwargs[field_name] = _parse_fallback_profiles(raw_fp) if raw_fp is not None else base.fallback_profiles
            continue
        if field_name == "recovery_allow_trust":
            raw_trust = rec_cfg.get("allow_trust") if "allow_trust" in rec_cfg else sec_cfg.get(
                "recovery_allow_trust", turn_cfg.get("recovery_allow_trust")
            )
            if raw_trust is None and section != "pm" and isinstance(pm_rec, Mapping) and "allow_trust" in pm_rec:
                raw_trust = pm_rec.get("allow_trust")
            kwargs[field_name] = base.recovery_allow_trust if raw_trust is None else bool(raw_trust)
            continue
        val = rec_cfg.get(field_name) if field_name in rec_cfg else turn_cfg.get(field_name)
        if field_name == "generating_no_step_stall_ms":
            iv0 = _opt_int(val)
            kwargs[field_name] = iv0 if iv0 is not None and iv0 >= 0 else getattr(base, field_name)
            continue
        iv = _opt_pos_int(val)
        kwargs[field_name] = iv if iv is not None else getattr(base, field_name)
    return TurnConfig(**kwargs)


def turn_config_from_dict(raw: Mapping[str, Any] | None) -> TurnConfig:
    return _parse_turn_config(raw, section="pm", defaults=TurnConfig())


def worker_turn_config_from_dict(raw: Mapping[str, Any] | None) -> TurnConfig:
    return _parse_turn_config(raw, section="worker", defaults=DEFAULT_WORKER_TURN_CONFIG)


def _empty_evidence() -> dict[str, Any]:
    return {
        "hc": {"state": "", "status_ms": 0, "obs_ms": 0, "turn": 0, "reported": None},
        "step": {"last_ms": 0, "count": 0, "ended": False, "last_kind": "", "last_error": ""},
        "pty": {"changed_ms": 0, "frozen_since_ms": 0, "digest": "", "hint": "", "dialog": ""},
        "proc": {"tool_pid": 0, "cmd": "", "since_ms": 0, "cpu_ms": 0, "cpu_changed_ms": 0},
    }


def _empty_activity() -> dict[str, Any]:
    return {"kind": "", "tool": "", "summary": "", "since_ms": 0, "preamble": ""}


def _default_session() -> dict[str, Any]:
    return Endpoint(runtime="hc", machine=None, terminal="").to_dict()


def _empty_metrics(phase: str = "idle", anchor_ms: int = 0) -> dict[str, Any]:
    return {
        "generate_ms": 0,
        "tool_ms": 0,
        "other_ms": 0,
        "last_phase": phase,
        "last_transition_ms": anchor_ms,
        "longest_step_ms": 0,
        "longest_step_kind": "",
        "longest_step_summary": "",
        "action_ms": {},
    }


def _default_turn(cfg: TurnConfig | None = None) -> dict[str, Any]:
    c = cfg or TurnConfig()
    return {
        "id": "",
        "seq": 0,
        "hc_turn": 0,
        "phase": "idle",
        "health": "ok",
        "health_reason": "",
        "cause": {"kind": "", "msg_ids": [], "batch": None},
        "started_ms": 0,
        "opened_ms": 0,
        "phase_since_ms": 0,
        "last_progress_ms": 0,
        "suspect_since_ms": 0,
        "evidence": _empty_evidence(),
        "activity": _empty_activity(),
        "metrics": _empty_metrics(),
        "budget": {
            "soft_ms": c.turn_soft_budget_ms,
            "hard_ms": c.turn_hard_budget_ms,
            "over": False,
        },
        "hook_confirmed": False,
        "pending_interrupt_ms": 0,
        "interrupt_outcome": "",
        "provisional": False,
        "w3_attempts": 0,
    }


def _default_recovery_breakers() -> dict[str, Any]:
    return {
        "turn_id": "",
        "turn_interrupts": 0,
        "rotation_times_ms": [],
    }


def default_state_v2(cfg: TurnConfig | None = None) -> dict[str, Any]:
    """Create a fresh `pm-turn.json` v2 snapshot matching §3.4 & §9.1."""
    state: dict[str, Any] = {
        "version": 2,
        "updated_ms": 0,
        "journal_seq": 0,
        "journal_offset": 0,
        "session": _default_session(),
        "turn": _default_turn(cfg),
        "last_turn": None,
        "last_summary_seq": 0,
        "pending_occupation_hint": None,
        "last_occupation_hint_ms": 0,
        "inbox": [],
        "incident": None,
        "link_state": "connected",
        "link_since_ms": 0,
        "recovery_breakers": _default_recovery_breakers(),
        "bg_shells": {"count": 0, "commands": []},
        # v1 compatibility & Phase 3 transition fields:
        "terminal": "",
        "agent_kind": "",
        "turn_seq": 0,
        "terminal_turn": 0,
        "hook_confirmed": False,
        "session_id": "",
        "session_turns": {},
        "phase": "idle",
        "cause": "",
        "batch": None,
        "active_msg_ids": [],
        "started_ms": 0,
        "last_activity_ms": 0,
        "activity": None,
        "interrupted_ms": 0,
        "interrupt_outcome": "",
        "turn_causes": {},
        "inflight": None,
        "outbox": [],
        "unhooked_ui_prompts": [],
        "recent_msg_ids": {},
    }
    return state


def sync_compat_fields(state: dict[str, Any]) -> dict[str, Any]:
    """Keep top-level v1-shaped fields in sync with `session` and `turn` for Phase 0 callers and rollback."""
    sess = state.get("session") if isinstance(state.get("session"), Mapping) else {}
    turn = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
    ev = turn.get("evidence") if isinstance(turn.get("evidence"), Mapping) else {}
    step = ev.get("step") if isinstance(ev.get("step"), Mapping) else {}
    pty = ev.get("pty") if isinstance(ev.get("pty"), Mapping) else {}
    cause = turn.get("cause") if isinstance(turn.get("cause"), Mapping) else {}

    ep = endpoint_from_dict(sess)
    term_val = ep.hc_target if ep and ep.runtime == "hc" else str(sess.get("terminal") or state.get("terminal") or "")
    state["terminal"] = term_val
    state["agent_kind"] = str(sess.get("agent_kind") or state.get("agent_kind") or "")
    state["session_id"] = str(sess.get("session_id") or state.get("session_id") or "")

    seq = _opt_int(turn.get("seq")) or 0
    state["turn_seq"] = seq
    state["terminal_turn"] = _opt_int(turn.get("hc_turn")) or 0
    state["hook_confirmed"] = bool(turn.get("hook_confirmed"))

    v2_phase = str(turn.get("phase") or "idle")
    v2_health = str(turn.get("health") or "ok")
    if v2_phase == "idle":
        v1_phase = "idle"
    elif v2_phase == "blocked":
        v1_phase = "blocked"
    elif v2_phase == "starting":
        v1_phase = "starting"
    elif v2_phase == "offline":
        v1_phase = "offline"
    elif v2_health == "stalled":
        v1_phase = "stalled"
    else:
        v1_phase = "working"
    state["phase"] = v1_phase
    state["cause"] = str(cause.get("kind") or "")
    batch = cause.get("batch")
    state["batch"] = list(batch) if isinstance(batch, list) else None
    msg_ids = cause.get("msg_ids")
    state["active_msg_ids"] = [str(x) for x in msg_ids if x] if isinstance(msg_ids, list) else []
    started_ms = _opt_int(turn.get("started_ms")) or 0
    state["started_ms"] = started_ms
    last_act = max(
        started_ms,
        _opt_int(turn.get("last_progress_ms")) or 0,
        _opt_int(step.get("last_ms")) or 0,
        _opt_int(pty.get("changed_ms")) or 0,
    )
    state["last_activity_ms"] = last_act if v2_phase != "idle" else (_opt_int(state.get("last_activity_ms")) or last_act)

    act = turn.get("activity") if isinstance(turn.get("activity"), Mapping) else {}
    step_count = _opt_int(step.get("count")) or 0
    if v2_phase == "idle":
        state["activity"] = None
    elif v2_phase == "tool" and (act.get("tool") or act.get("summary")):
        state["activity"] = {
            "kind": "tool",
            "tool": str(act.get("tool") or ""),
            "summary": str(act.get("summary") or ""),
            "started_ms": _opt_int(act.get("since_ms")) or started_ms,
            "steps": step_count,
        }
    elif v2_phase == "recovering":
        state["activity"] = {
            "kind": "recovering",
            "tool": "",
            "summary": str(act.get("summary") or ""),
            "started_ms": _opt_int(act.get("since_ms")) or started_ms,
            "steps": step_count,
        }
    elif v2_phase in ACTIVE_TURN_PHASES:
        state["activity"] = {
            "kind": "thinking",
            "tool": "",
            "summary": "",
            "started_ms": _opt_int(turn.get("phase_since_ms")) or started_ms,
            "steps": step_count,
        }
    else:
        state["activity"] = None
    if _opt_int(turn.get("pending_interrupt_ms")):
        state["interrupted_ms"] = _opt_int(turn.get("pending_interrupt_ms")) or 0
    if turn.get("interrupt_outcome"):
        state["interrupt_outcome"] = str(turn.get("interrupt_outcome") or "")
    return state


def upgrade_state_v1_to_v2(raw: Mapping[str, Any] | None, *, cfg: TurnConfig | None = None) -> dict[str, Any]:
    """Idempotently upgrade a v1 `pm-turn.json` dict (or normalize a v2 dict) in place (§4.8)."""
    base = default_state_v2(cfg)
    if not isinstance(raw, Mapping):
        return sync_compat_fields(base)

    is_v2 = _opt_int(raw.get("version")) == 2 and isinstance(raw.get("turn"), Mapping)
    if is_v2:
        out = copy.deepcopy(base)
        for key in (
            "updated_ms", "journal_seq", "journal_offset", "last_turn", "last_summary_seq",
            "pending_occupation_hint", "last_occupation_hint_ms", "incident",
            "link_state", "link_since_ms",
            "inflight", "terminal_turn", "interrupted_ms", "interrupt_outcome",
        ):
            if key in raw:
                out[key] = copy.deepcopy(raw[key])
        if isinstance(raw.get("recovery_breakers"), Mapping):
            rb = raw["recovery_breakers"]
            out["recovery_breakers"] = {
                "turn_id": str(rb.get("turn_id") or ""),
                "turn_interrupts": _opt_int(rb.get("turn_interrupts")) or 0,
                "rotation_times_ms": [
                    int(x) for x in (rb.get("rotation_times_ms") or [])
                    if isinstance(x, (int, float)) and not isinstance(x, bool)
                ][-16:],
            }
        for dict_key in ("session_turns", "turn_causes", "recent_msg_ids"):
            if isinstance(raw.get(dict_key), Mapping):
                out[dict_key] = copy.deepcopy(dict(raw[dict_key]))
        for list_key in ("inbox", "outbox", "unhooked_ui_prompts"):
            if isinstance(raw.get(list_key), list):
                out[list_key] = copy.deepcopy(list(raw[list_key]))
        # The mailbox projection (`TurnTracker.sync_mailbox_projection`): kept, or every read would drop it and
        # every sync would rewrite pm-turn.json (which wakes the deliverer that watches it).
        if isinstance(raw.get("undelivered"), Mapping):
            out["undelivered"] = copy.deepcopy(dict(raw["undelivered"]))
        if isinstance(raw.get("session"), Mapping):
            ep = endpoint_from_dict(raw["session"])
            if ep is not None:
                out["session"] = ep.to_dict()
            else:
                out["session"].update(copy.deepcopy(dict(raw["session"])))
        raw_turn = raw["turn"]
        t = out["turn"]
        for k in (
            "id", "seq", "hc_turn", "phase", "health", "health_reason", "started_ms", "opened_ms", "phase_since_ms",
            "last_progress_ms", "suspect_since_ms", "hook_confirmed", "pending_interrupt_ms",
            "interrupt_outcome", "provisional", "w3_attempts",
        ):
            if k in raw_turn:
                t[k] = copy.deepcopy(raw_turn[k])
        if isinstance(raw_turn.get("cause"), Mapping):
            t["cause"].update(copy.deepcopy(dict(raw_turn["cause"])))
        if isinstance(raw_turn.get("activity"), Mapping):
            t["activity"].update(copy.deepcopy(dict(raw_turn["activity"])))
        if isinstance(raw_turn.get("metrics"), Mapping):
            t["metrics"].update(copy.deepcopy(dict(raw_turn["metrics"])))
            if isinstance(raw_turn["metrics"].get("action_ms"), Mapping):
                t["metrics"]["action_ms"] = dict(raw_turn["metrics"]["action_ms"])
        if isinstance(raw_turn.get("budget"), Mapping):
            t["budget"].update(copy.deepcopy(dict(raw_turn["budget"])))
        if isinstance(raw_turn.get("evidence"), Mapping):
            for ev_k in ("hc", "step", "pty", "proc"):
                if isinstance(raw_turn["evidence"].get(ev_k), Mapping):
                    t["evidence"][ev_k].update(copy.deepcopy(dict(raw_turn["evidence"][ev_k])))
        if isinstance(raw.get("bg_shells"), Mapping):
            bg = raw["bg_shells"]
            out["bg_shells"] = {
                "count": _opt_int(bg.get("count")) or 0,
                "commands": list(bg.get("commands") or []) if isinstance(bg.get("commands"), list) else [],
            }
        return sync_compat_fields(out)

    # Upgrade v1 -> v2
    out = copy.deepcopy(base)
    out["updated_ms"] = _opt_int(raw.get("updated_ms")) or 0
    out["interrupted_ms"] = _opt_int(raw.get("interrupted_ms")) or 0
    out["interrupt_outcome"] = str(raw.get("interrupt_outcome") or "")
    out["inflight"] = copy.deepcopy(raw.get("inflight")) if isinstance(raw.get("inflight"), Mapping) else None
    out["session_turns"] = dict(raw.get("session_turns") or {}) if isinstance(raw.get("session_turns"), Mapping) else {}
    out["turn_causes"] = dict(raw.get("turn_causes") or {}) if isinstance(raw.get("turn_causes"), Mapping) else {}
    out["recent_msg_ids"] = dict(raw.get("recent_msg_ids") or {}) if isinstance(raw.get("recent_msg_ids"), Mapping) else {}
    out["outbox"] = list(raw.get("outbox") or []) if isinstance(raw.get("outbox"), list) else []
    out["unhooked_ui_prompts"] = (
        list(raw.get("unhooked_ui_prompts") or []) if isinstance(raw.get("unhooked_ui_prompts"), list) else []
    )

    raw_term = str(raw.get("terminal") or "").strip()
    agent_kind = str(raw.get("agent_kind") or "").strip().lower()
    sid = str(raw.get("session_id") or "").strip()
    ep = parse_legacy_endpoint(raw_term, "", agent_kind, runtime_hint="hc", session_id=sid) if raw_term else None
    if ep is not None:
        out["session"] = ep.to_dict()
    else:
        out["session"]["agent_kind"] = agent_kind
        out["session"]["session_id"] = sid

    turn_seq = _opt_int(raw.get("turn_seq")) or 0
    hc_turn = _opt_int(raw.get("terminal_turn")) or 0
    v1_phase = str(raw.get("phase") or "idle")
    started_ms = _opt_int(raw.get("started_ms")) or 0
    last_act_ms = _opt_int(raw.get("last_activity_ms")) or started_ms
    raw_act = raw.get("activity") if isinstance(raw.get("activity"), Mapping) else None

    if v1_phase in ("working", "stalled"):
        if raw_act and raw_act.get("kind") == "tool" and (raw_act.get("tool") or raw_act.get("summary")):
            v2_phase = "tool"
        else:
            v2_phase = "generating"
    elif v1_phase in ("idle", "blocked", "starting", "offline"):
        v2_phase = v1_phase
    else:
        v2_phase = "idle"

    t = out["turn"]
    t["seq"] = turn_seq
    t["hc_turn"] = hc_turn
    t["id"] = format_turn_id(ep, hc_turn) if (ep is not None and (turn_seq > 0 or v2_phase != "idle")) else ""
    t["phase"] = v2_phase
    t["health"] = "ok"  # FS-2: never migrate sticky stalled into v2
    t["cause"] = {
        "kind": str(raw.get("cause") or ""),
        "msg_ids": [str(x) for x in (raw.get("active_msg_ids") or []) if x]
        if isinstance(raw.get("active_msg_ids"), list) else [],
        "batch": list(raw["batch"]) if isinstance(raw.get("batch"), list) else None,
    }
    t["started_ms"] = started_ms
    t["phase_since_ms"] = _opt_int((raw_act or {}).get("started_ms")) or started_ms
    t["last_progress_ms"] = last_act_ms
    t["hook_confirmed"] = bool(raw.get("hook_confirmed"))
    t["pending_interrupt_ms"] = out["interrupted_ms"]
    t["interrupt_outcome"] = out["interrupt_outcome"]
    t["evidence"]["step"]["last_ms"] = last_act_ms
    t["evidence"]["step"]["count"] = _opt_int((raw_act or {}).get("steps")) or 0
    if v2_phase == "tool" and raw_act is not None:
        t["activity"] = {
            "kind": "tool",
            "tool": str(raw_act.get("tool") or ""),
            "summary": str(raw_act.get("summary") or ""),
            "since_ms": _opt_int(raw_act.get("started_ms")) or started_ms,
            "preamble": "",
        }
    elif v2_phase == "generating":
        t["activity"] = {
            "kind": "generate",
            "tool": "",
            "summary": "",
            "since_ms": _opt_int((raw_act or {}).get("started_ms")) or started_ms,
            "preamble": "",
        }

    # Copy v1 outbox entries into v2 inbox view (§4.8)
    inbox_items: list[dict[str, Any]] = []
    for item in out["outbox"]:
        if isinstance(item, Mapping) and item.get("msg_id"):
            inbox_items.append({
                "id": str(item["msg_id"]),
                "kind": "user",
                "state": "accepted",
                "accepted_ms": _opt_int(item.get("queued_ms")) or out["updated_ms"],
                "typed_ms": 0,
                "consumed_ms": 0,
                "attempts": 0,
                "reason": str(item.get("reason") or ""),
            })
    out["inbox"] = inbox_items
    return sync_compat_fields(out)


def _session_identity(sess: Mapping[str, Any]) -> tuple[str, str | None, str, int | None, int]:
    return (
        str(sess.get("runtime") or ""),
        str(sess.get("machine")) if sess.get("machine") else None,
        str(sess.get("terminal") or ""),
        _opt_pos_int(sess.get("fg_pid")),
        _opt_pos_int(sess.get("epoch")) or 1,
    )


def _account_phase_segment(turn: dict[str, Any], now_ms: int, next_phase: str | None = None) -> None:
    """Attribute elapsed time since the previous phase transition into `turn['metrics']` (§3.8 O-a)."""
    metrics = turn.get("metrics")
    if not isinstance(metrics, dict):
        metrics = _empty_metrics(str(turn.get("phase") or "idle"), _opt_int(turn.get("started_ms")) or now_ms)
        turn["metrics"] = metrics
    prev_phase = str(metrics.get("last_phase") or turn.get("phase") or "idle")
    last_t = _opt_int(metrics.get("last_transition_ms")) or _opt_int(turn.get("phase_since_ms")) or _opt_int(turn.get("started_ms")) or 0
    if last_t > 0 and now_ms > last_t and prev_phase in ACTIVE_TURN_PHASES:
        delta = now_ms - last_t
        action_ms = metrics.get("action_ms")
        if not isinstance(action_ms, dict):
            action_ms = {}
            metrics["action_ms"] = action_ms
        if prev_phase == "tool":
            metrics["tool_ms"] = (_opt_int(metrics.get("tool_ms")) or 0) + delta
            act = turn.get("activity") if isinstance(turn.get("activity"), Mapping) else {}
            cat = str(act.get("tool") or "tool").strip() or "tool"
            action_ms[cat] = (_opt_int(action_ms.get(cat)) or 0) + delta
            if delta > (_opt_int(metrics.get("longest_step_ms")) or 0):
                metrics["longest_step_ms"] = delta
                metrics["longest_step_kind"] = cat
                metrics["longest_step_summary"] = str(act.get("summary") or "").strip()[:60]
        elif prev_phase in ("generating", "submitted"):
            metrics["generate_ms"] = (_opt_int(metrics.get("generate_ms")) or 0) + delta
            action_ms["generate"] = (_opt_int(action_ms.get("generate")) or 0) + delta
            if delta > (_opt_int(metrics.get("longest_step_ms")) or 0):
                metrics["longest_step_ms"] = delta
                metrics["longest_step_kind"] = "generate"
                metrics["longest_step_summary"] = ""
        else:
            metrics["other_ms"] = (_opt_int(metrics.get("other_ms")) or 0) + delta
            action_ms[prev_phase] = (_opt_int(action_ms.get(prev_phase)) or 0) + delta
    if next_phase is not None:
        metrics["last_phase"] = next_phase
        if now_ms > 0:
            metrics["last_transition_ms"] = max(last_t, now_ms)


def _auto_rank(mode: str) -> int:
    return {"off": 0, "safe": 1, "full": 2}.get(str(mode or "").lower(), 1)


def _ensure_breakers(state: dict[str, Any], turn_id: str, now_ms: int, cfg: TurnConfig) -> dict[str, Any]:
    rb = state.get("recovery_breakers")
    if not isinstance(rb, dict):
        rb = _default_recovery_breakers()
        state["recovery_breakers"] = rb
    if turn_id and rb.get("turn_id") != turn_id:
        rb["turn_id"] = turn_id
        rb["turn_interrupts"] = 0
    cutoff = now_ms - cfg.rotation_window_ms
    times = [
        int(t) for t in (rb.get("rotation_times_ms") or [])
        if isinstance(t, (int, float)) and not isinstance(t, bool) and int(t) > cutoff
    ]
    rb["rotation_times_ms"] = times[-16:]
    return rb


def _can_interrupt_turn(state: Mapping[str, Any], turn_id: str, cfg: TurnConfig) -> bool:
    rb = state.get("recovery_breakers")
    if not isinstance(rb, Mapping):
        return cfg.max_turn_interrupts > 0
    if turn_id and rb.get("turn_id") != turn_id:
        return cfg.max_turn_interrupts > 0
    return (_opt_int(rb.get("turn_interrupts")) or 0) < cfg.max_turn_interrupts


def _can_rotate_seat(state: Mapping[str, Any], now_ms: int, cfg: TurnConfig) -> bool:
    rb = state.get("recovery_breakers")
    if not isinstance(rb, Mapping):
        return cfg.max_rotations_per_window > 0
    cutoff = now_ms - cfg.rotation_window_ms
    recent = [
        t for t in (rb.get("rotation_times_ms") or [])
        if isinstance(t, (int, float)) and not isinstance(t, bool) and int(t) > cutoff
    ]
    return len(recent) < cfg.max_rotations_per_window


def _record_interrupt_breaker(state: dict[str, Any], turn_id: str, now_ms: int, cfg: TurnConfig) -> None:
    rb = _ensure_breakers(state, turn_id, now_ms, cfg)
    rb["turn_interrupts"] = (_opt_int(rb.get("turn_interrupts")) or 0) + 1


def _record_rotation_breaker(state: dict[str, Any], now_ms: int, cfg: TurnConfig) -> None:
    rb = _ensure_breakers(state, "", now_ms, cfg)
    rb["rotation_times_ms"] = [*list(rb.get("rotation_times_ms") or []), int(now_ms)][-16:]


def _select_executable_stage(
    state: Mapping[str, Any],
    cls: str,
    start_stage: int,
    now_ms: int,
    cfg: TurnConfig,
    *,
    turn_id: str = "",
    tool_pid: int = 0,
    cause_kind: str = "",
) -> tuple[str, int, dict[str, Any]]:
    """Resolve the first runnable ladder `(class, stage, step_meta)` respecting `auto`, `fallback_profiles`, and breakers."""
    cur_cls = cls
    stage = max(0, int(start_stage))
    for _ in range(12):
        ladder = RECOVERY_LADDERS.get(cur_cls, ())
        if not ladder:
            return cur_cls, 0, {"action": "notify_user", "min_auto": "off", "breaker": "", "delay_field": "", "verify_field": ""}
        if stage >= len(ladder):
            stage = len(ladder) - 1
        step = ladder[stage]
        action = str(step.get("action") or "notify_user")
        if action == "escalate_w2":
            cur_cls = "W2"
            stage = 0
            continue
        if action == "notify_user":
            return cur_cls, stage, dict(step)
        if cfg.recovery_auto == "off":
            stage = len(ladder) - 1
            continue
        if _auto_rank(cfg.recovery_auto) < _auto_rank(str(step.get("min_auto") or "safe")):
            stage += 1
            continue
        if action == "switch_profile" and not cfg.fallback_profiles:
            stage += 1
            continue
        if action == "interrupt_tool" and tool_pid <= 0:
            stage = 3  # skip to interrupt_turn
            continue
        if action == "continue_turn" and cause_kind not in ("user", "deliver"):
            stage += 1
            continue
        breaker = str(step.get("breaker") or "")
        if breaker == "interrupt" and not _can_interrupt_turn(state, turn_id, cfg):
            if cur_cls == "W1":
                cur_cls = "W2"
                stage = 0
            elif cur_cls == "W4":
                stage = len(ladder) - 1
            else:
                stage += 1
            continue
        if breaker == "rotation" and not _can_rotate_seat(state, now_ms, cfg):
            stage = len(ladder) - 1
            continue
        # Never run `continue_turn` for W1/W4 if `interrupt_turn` was bypassed due to breaker.
        if action == "continue_turn" and cur_cls in ("W1", "W4") and not _can_interrupt_turn(state, turn_id, cfg) and stage > 0:
            prev_step = ladder[stage - 1]
            if prev_step.get("action") == "interrupt_turn":
                stage += 1
                continue
        return cur_cls, stage, dict(step)
    return cur_cls, max(0, len(RECOVERY_LADDERS.get(cur_cls, ())) - 1), {"action": "notify_user", "min_auto": "off"}


def _step_delay_ms(step_meta: Mapping[str, Any], cfg: TurnConfig) -> int:
    delay_field = str(step_meta.get("delay_field") or "")
    if not delay_field or cfg.recovery_auto == "off":
        return 0
    return _opt_int(getattr(cfg, delay_field, 0)) or 0


def _open_incident(
    state: dict[str, Any],
    *,
    cls: str,
    turn_id: str,
    turn_seq: int,
    cause_kind: str,
    msg_ids: list[str],
    batch: list[int] | None,
    reason: str,
    error: str = "",
    tool_pid: int = 0,
    tool_cmd: str = "",
    now_ms: int,
    cfg: TurnConfig,
) -> dict[str, Any]:
    _ensure_breakers(state, turn_id, now_ms, cfg)
    init_stage = 0
    if cls == "W2" and error and _CAPACITY_ERR_RE.search(error):
        init_stage = 2  # §3.6 W2: capacity errors skip straight to switch_profile / notify_user
    elif cls == "W4" and tool_pid <= 0:
        init_stage = 3
    eff_cls, eff_stage, step_meta = _select_executable_stage(
        state, cls, init_stage, now_ms, cfg, turn_id=turn_id, tool_pid=tool_pid, cause_kind=cause_kind,
    )
    delay_ms = _step_delay_ms(step_meta, cfg)
    step_name = str(step_meta.get("action") or "notify_user")
    cur_turn = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
    cur_phase = str(cur_turn.get("phase") or "idle")
    if eff_cls == "W2" and step_name == "continue_turn" and cur_phase in ACTIVE_TURN_PHASES:
        eff_tid = str(cur_turn.get("id") or turn_id or "")
        if _can_interrupt_turn(state, eff_tid, cfg):
            step_name = "interrupt_turn"
            delay_ms = 0
        else:
            eff_cls, eff_stage, step_meta = _select_executable_stage(
                state, "W2", 2, now_ms, cfg, turn_id=eff_tid, tool_pid=tool_pid, cause_kind=cause_kind,
            )
            step_name = str(step_meta.get("action") or "notify_user")
            delay_ms = _step_delay_ms(step_meta, cfg)
    prev_inc = state.get("incident")
    reuse_open = (
        isinstance(prev_inc, Mapping)
        and prev_inc.get("status") in ("open", "recovering")
        and bool(prev_inc.get("key"))
    )
    inc_key = str(prev_inc["key"]) if reuse_open else f"{turn_id or f'seq:{turn_seq}'}:{cls}"
    opened_ms = (_opt_int(prev_inc.get("opened_ms")) or now_ms) if reuse_open else now_ms
    inc = {
        "id": f"inc:{turn_seq}:{cls}:{now_ms}",
        "key": inc_key,
        "class": eff_cls,
        "turn_id": turn_id,
        "turn_seq": int(turn_seq or 0),
        "cause_kind": cause_kind,
        "msg_ids": list(msg_ids),
        "batch": list(batch) if isinstance(batch, list) else None,
        "reason": reason,
        "error": error[:200],
        "tool_pid": int(tool_pid or 0),
        "tool_cmd": tool_cmd[:120],
        "stage": eff_stage,
        "step_name": step_name,
        "status": "open",
        "opened_ms": opened_ms,
        "updated_ms": now_ms,
        "resolved_ms": 0,
        "next_due_ms": now_ms + delay_ms,
        "awaiting_action": "",
        "awaiting_verify": "",
        "verify_deadline_ms": 0,
        "folded": False,
        "resolution": "",
        "suggested_profile": cfg.fallback_profiles[0] if cfg.fallback_profiles else "",
        "actions": [],
    }
    state["incident"] = inc
    return inc


def _advance_incident(
    state: dict[str, Any],
    now_ms: int,
    cfg: TurnConfig,
    *,
    next_stage: int | None = None,
    force_class: str | None = None,
) -> dict[str, Any] | None:
    inc = state.get("incident")
    if not isinstance(inc, dict) or inc.get("status") not in ("open", "recovering"):
        return None
    cls = str(force_class or inc.get("class") or "W2")
    if force_class and force_class != inc.get("class"):
        base_stage = 2 if (cls == "W2" and inc.get("error") and _CAPACITY_ERR_RE.search(str(inc["error"]))) else 0
        start_stage = base_stage if next_stage is None else max(base_stage, int(next_stage))
    else:
        start_stage = int(inc.get("stage") or 0) + 1 if next_stage is None else int(next_stage)
    cur_turn = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
    cur_phase = str(cur_turn.get("phase") or "idle")
    eff_tid = str(cur_turn.get("id") or inc.get("turn_id") or "")
    if cur_phase in ACTIVE_TURN_PHASES and cur_turn.get("id"):
        inc["turn_id"] = str(cur_turn["id"])
    eff_cls, eff_stage, step_meta = _select_executable_stage(
        state,
        cls,
        start_stage,
        now_ms,
        cfg,
        turn_id=eff_tid,
        tool_pid=_opt_int(inc.get("tool_pid")) or 0,
        cause_kind=str(inc.get("cause_kind") or ""),
    )
    action_name = str(step_meta.get("action") or "notify_user")
    delay_ms = _step_delay_ms(step_meta, cfg)
    if eff_cls == "W2" and action_name == "continue_turn" and cur_phase in ACTIVE_TURN_PHASES:
        # Never queue `continue_turn` while a stalled turn is still active: stop it first (or skip
        # `continue_turn` to fallback/notify if the interrupt circuit breaker is exhausted).
        if _can_interrupt_turn(state, eff_tid, cfg):
            action_name = "interrupt_turn"
            delay_ms = 0
        else:
            eff_cls, eff_stage, step_meta = _select_executable_stage(
                state,
                "W2",
                2,
                now_ms,
                cfg,
                turn_id=eff_tid,
                tool_pid=_opt_int(inc.get("tool_pid")) or 0,
                cause_kind=str(inc.get("cause_kind") or ""),
            )
            action_name = str(step_meta.get("action") or "notify_user")
            delay_ms = _step_delay_ms(step_meta, cfg)
    inc["class"] = eff_cls
    inc["stage"] = eff_stage
    inc["step_name"] = action_name
    inc["status"] = "open"
    inc["updated_ms"] = now_ms
    inc["awaiting_action"] = ""
    inc["awaiting_verify"] = ""
    inc["verify_deadline_ms"] = 0
    inc["next_due_ms"] = now_ms + delay_ms
    return inc


def _resolve_incident(
    state: dict[str, Any],
    now_ms: int,
    cfg: TurnConfig,
    *,
    resolution: str = "recovered",
) -> dict[str, Any] | None:
    inc = state.get("incident")
    if not isinstance(inc, dict) or inc.get("status") not in ("open", "recovering", "notified"):
        return None
    opened = _opt_int(inc.get("opened_ms")) or now_ms
    inc["status"] = "resolved"
    inc["resolved_ms"] = now_ms
    inc["updated_ms"] = now_ms
    inc["next_due_ms"] = 0
    inc["awaiting_action"] = ""
    inc["awaiting_verify"] = ""
    inc["verify_deadline_ms"] = 0
    inc["folded"] = max(0, now_ms - opened) <= cfg.incident_fold_window_ms
    inc["resolution"] = resolution
    return inc


def incident_holds_batch(state: Mapping[str, Any] | None) -> bool:
    """True when an active/notified incident owns recovery so `event.batch` must wait for `continue_turn`,
    `retype_submitted`, or resolution."""
    if not isinstance(state, Mapping):
        return False
    inc = state.get("incident")
    if not isinstance(inc, Mapping):
        return False
    st = str(inc.get("status") or "")
    if st not in ("open", "recovering", "notified"):
        return False
    if (
        st in ("open", "recovering")
        and inc.get("cause_kind") == "deliver"
        and inc.get("awaiting_verify") in ("continue_turn", "retype_submitted")
    ):
        return False
    return True


def next_recovery_action(
    state: Mapping[str, Any],
    now_ms: int,
    cfg: TurnConfig | None = None,
) -> dict[str, Any] | None:
    """Pure selector returning the next due recovery action intent for `(state, now_ms, cfg)` (I8)."""
    c = cfg or TurnConfig()
    turn = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
    phase = str(turn.get("phase") or "idle")
    if phase == "blocked":
        if (_opt_int(turn.get("w3_attempts")) or 0) < 2:
            return {
                "kind": "recovery_action",
                "class": "W3",
                "stage": 0,
                "action": "unblock_safe_dialog" if c.recovery_auto != "off" else "notify_user",
                "auto": c.recovery_auto,
                "allow_trust": bool(c.recovery_allow_trust),
                "dialog_kind": str(turn.get("health_reason") or ""),
                "turn_id": str(turn.get("id") or ""),
                "turn_seq": _opt_int(turn.get("seq")) or 0,
            }
        return None

    inc = state.get("incident")
    if not isinstance(inc, Mapping) or inc.get("status") not in ("open", "recovering"):
        return None
    if inc.get("awaiting_action") or inc.get("awaiting_verify"):
        return None
    cur_turn_id = str(turn.get("id") or "")
    inc_turn_id = str(inc.get("turn_id") or "")
    cur_seq = _opt_int(turn.get("seq")) or 0
    inc_seq = _opt_int(inc.get("turn_seq")) or 0
    turn_cause = str(((turn.get("cause") or {}) if isinstance(turn.get("cause"), Mapping) else {}).get("kind") or "")
    diff_turn = (
        turn_cause != "recovery"
        and inc.get("awaiting_verify") != "turn_outcome"
        and (
            (bool(inc_turn_id) and bool(cur_turn_id) and inc_turn_id != cur_turn_id)
            or (inc_seq > 0 and cur_seq > 0 and inc_seq != cur_seq)
        )
    )
    if phase in ACTIVE_TURN_PHASES and diff_turn:
        return None
    if (
        phase in ACTIVE_TURN_PHASES
        and str(turn.get("health") or "ok") != "stalled"
        and str(inc.get("class") or "") in ("W2", "W7")
    ):
        return None
    due_ms = _opt_int(inc.get("next_due_ms")) or 0
    if due_ms > now_ms:
        return None

    cls = str(inc.get("class") or "W2")
    stage = _opt_int(inc.get("stage")) or 0
    ladder = RECOVERY_LADDERS.get(cls, ())
    step = dict(ladder[stage]) if 0 <= stage < len(ladder) else {"action": "notify_user"}
    action = str(step.get("action") or "notify_user")
    if action == "continue_turn" and phase != "idle":
        if phase in ACTIVE_TURN_PHASES and cls == "W2" and c.recovery_auto != "off":
            eff_tid = cur_turn_id or inc_turn_id
            if _can_interrupt_turn(state, eff_tid, c):
                action = "interrupt_turn"
            else:
                cls, stage, step = _select_executable_stage(
                    state,
                    "W2",
                    2,
                    now_ms,
                    c,
                    turn_id=eff_tid,
                    tool_pid=_opt_int(inc.get("tool_pid")) or 0,
                    cause_kind=str(inc.get("cause_kind") or ""),
                )
                action = str(step.get("action") or "notify_user")
        elif c.recovery_auto != "off":
            return None
    if c.recovery_auto == "off" and action != "notify_user":
        action = "notify_user"
    return {
        "kind": "recovery_action",
        "incident_id": str(inc.get("id") or ""),
        "incident_key": str(inc.get("key") or ""),
        "class": cls,
        "stage": stage,
        "action": action,
        "auto": c.recovery_auto,
        "turn_id": str(inc.get("turn_id") or ""),
        "turn_seq": _opt_int(inc.get("turn_seq")) or 0,
        "cause_kind": str(inc.get("cause_kind") or ""),
        "msg_ids": list(inc.get("msg_ids") or []),
        "batch": list(inc["batch"]) if isinstance(inc.get("batch"), list) else None,
        "reason": str(inc.get("reason") or ""),
        "error": str(inc.get("error") or ""),
        "tool_pid": _opt_int(inc.get("tool_pid")) or 0,
        "tool_cmd": str(inc.get("tool_cmd") or ""),
        "signal": str(step.get("signal") or ""),
        "profile": c.fallback_profiles[0] if (action == "switch_profile" and c.fallback_profiles) else "",
        "suggested_profile": str(inc.get("suggested_profile") or ""),
        "tool_note": bool(step.get("tool_note")),
        "attempt": _opt_int(step.get("attempt")) or 1,
    }


def _close_turn(
    state: dict[str, Any],
    *,
    outcome: str,
    now_ms: int,
    cfg: TurnConfig,
    aborted: bool = False,
) -> None:
    turn = state["turn"]
    _account_phase_segment(turn, now_ms, next_phase="idle")
    started = _opt_int(turn.get("started_ms")) or now_ms
    dur = max(0, now_ms - started) if started > 0 else 0
    step_ev = turn["evidence"]["step"]
    steps = _opt_int(step_ev.get("count")) or 0
    metrics = turn.get("metrics") if isinstance(turn.get("metrics"), Mapping) else {}
    gen_ms = _opt_int(metrics.get("generate_ms")) or 0
    tool_ms = _opt_int(metrics.get("tool_ms")) or 0
    other_ms = _opt_int(metrics.get("other_ms")) or 0
    if dur > 0 and (gen_ms + tool_ms + other_ms) == 0:
        gen_ms = dur
    action_ms = dict(metrics.get("action_ms") or {}) if isinstance(metrics.get("action_ms"), Mapping) else {}
    if dur > 0 and not action_ms:
        action_ms = {"generate": gen_ms}
    longest_ms = _opt_int(metrics.get("longest_step_ms")) or (dur if dur > 0 else 0)
    longest_kind = str(metrics.get("longest_step_kind") or ("generate" if dur > 0 else ""))
    longest_summary = str(metrics.get("longest_step_summary") or "")
    cause_obj = turn.get("cause") if isinstance(turn.get("cause"), Mapping) else {}
    cause_kind = str(cause_obj.get("kind") or "")
    msg_ids = [str(m) for m in (cause_obj.get("msg_ids") or []) if m]
    batch = list(cause_obj["batch"]) if isinstance(cause_obj.get("batch"), list) else None
    soft_ms = cfg.turn_soft_budget_ms
    hard_ms = cfg.turn_hard_budget_ms
    over_soft = dur > soft_ms
    over_hard = dur > hard_ms
    turn_id = str(turn.get("id") or "")
    turn_seq = _opt_int(turn.get("seq")) or 0
    turn_confirmed = (not bool(turn.get("provisional"))) or bool(turn.get("hook_confirmed")) or steps > 0
    opened_ms = max(started, _opt_int(turn.get("opened_ms")) or started)
    sess_kind = str(((state.get("session") or {}) if isinstance(state.get("session"), Mapping) else {}).get("agent_kind") or state.get("agent_kind") or "")
    if turn_id or turn_seq:
        summary = {
            "id": turn_id,
            "seq": turn_seq,
            "cause": cause_kind,
            "outcome": outcome,
            "agent_kind": sess_kind,
            "started_ms": started,
            "opened_ms": opened_ms,
            "duration_ms": dur,
            "total_ms": dur,
            "steps": steps,
            "ended_ms": now_ms,
            "confirmed": turn_confirmed,
            "hook_confirmed": bool(turn.get("hook_confirmed")),
            **({"aborted": True} if aborted else {}),
            "split": {
                "generate_ms": gen_ms,
                "tool_ms": tool_ms,
                "steps": steps,
            },
            "longest_step": {
                "ms": longest_ms,
                "kind": longest_kind,
                "summary": longest_summary,
            },
            "action_ms": action_ms,
            "budget": {
                "soft_ms": soft_ms,
                "hard_ms": hard_ms,
                "over_soft": over_soft,
                "over_hard": over_hard,
                "over": over_soft,
            },
        }
        state["last_turn"] = summary
        # §3.8 O-c: queue a one-line occupation hint when a user-initiated turn exceeds soft budget (rate-limited).
        if cause_kind == "user" and over_soft:
            last_hint_ms = _opt_int(state.get("last_occupation_hint_ms")) or 0
            if last_hint_ms == 0 or (now_ms - last_hint_ms) >= OCCUPATION_HINT_COOLDOWN_MS:
                state["pending_occupation_hint"] = {
                    "turn_id": summary["id"],
                    "seq": summary["seq"],
                    "total_ms": dur,
                    "soft_ms": soft_ms,
                    "hard_ms": hard_ms,
                    "generate_ms": gen_ms,
                    "tool_ms": tool_ms,
                    "steps": steps,
                    "action_ms": dict(action_ms),
                    "longest_step": dict(summary["longest_step"]),
                    "ended_ms": now_ms,
                }

    fresh = _default_turn(cfg)
    fresh["seq"] = turn_seq
    fresh["hc_turn"] = _opt_int(turn.get("hc_turn")) or 0
    fresh["interrupt_outcome"] = str(turn.get("interrupt_outcome") or "")
    fresh["pending_interrupt_ms"] = _opt_int(turn.get("pending_interrupt_ms")) or 0
    # Preserve last hc state info for continuity checks (T1 / T4).
    fresh["evidence"]["hc"] = copy.deepcopy(turn["evidence"]["hc"])
    state["turn"] = fresh

    # Incident reconciliation on turn close (W2 dead turn & recovery verification).
    inc = state.get("incident")
    if outcome == "replied":
        if isinstance(inc, dict) and inc.get("status") in ("open", "recovering", "notified"):
            if (
                cause_kind in ("user", "deliver", "recovery")
                or inc.get("cause_kind") not in ("user", "deliver")
                or inc.get("awaiting_verify") == "turn_outcome"
            ):
                _resolve_incident(state, now_ms, cfg, resolution="replied")
    elif outcome in ("errored", "silent"):
        err_text = str(step_ev.get("last_error") or "")
        if isinstance(inc, dict) and inc.get("status") in ("open", "recovering") and inc.get("awaiting_verify") in (
            "continue_turn", "turn_outcome", "retype_submitted",
        ):
            if err_text and not inc.get("error"):
                inc["error"] = err_text[:200]
            if inc.get("class") == "W1":
                _advance_incident(state, now_ms, cfg, force_class="W2")
            else:
                _advance_incident(state, now_ms, cfg)
            if outcome == "silent" and isinstance(state.get("incident"), dict):
                cur_due = _opt_int(state["incident"].get("next_due_ms")) or 0
                if cur_due <= now_ms:
                    state["incident"]["next_due_ms"] = now_ms + 2_000
        elif (
            isinstance(inc, dict)
            and inc.get("status") in ("open", "recovering")
            and inc.get("step_name") == "interrupt_turn"
        ):
            if err_text and not inc.get("error"):
                inc["error"] = err_text[:200]
            if inc.get("class") == "W2":
                st_i = _opt_int(inc.get("stage")) or 0
                w2_ladder = RECOVERY_LADDERS["W2"]
                s_meta = dict(w2_ladder[st_i]) if 0 <= st_i < len(w2_ladder) else {"action": "notify_user"}
                d_ms = _step_delay_ms(s_meta, cfg)
                inc["step_name"] = str(s_meta.get("action") or "continue_turn")
                inc["status"] = "open"
                inc["awaiting_action"] = ""
                inc["awaiting_verify"] = ""
                inc["verify_deadline_ms"] = 0
                inc["next_due_ms"] = now_ms + d_ms
            elif inc.get("class") == "W1":
                _advance_incident(state, now_ms, cfg, force_class="W2")
            else:
                _advance_incident(state, now_ms, cfg)
        elif outcome == "errored" and cause_kind in ("user", "deliver") and (turn_id or turn_seq):
            # I2 & I10: only positive error evidence (`errored`) opens W2 auto-continuation; `silent` means end
            # evidence has not arrived yet (async Stop hook) or the user pressed Esc in the terminal.
            _open_incident(
                state,
                cls="W2",
                turn_id=turn_id,
                turn_seq=turn_seq,
                cause_kind=cause_kind,
                msg_ids=msg_ids,
                batch=batch,
                reason=outcome,
                error=err_text,
                now_ms=now_ms,
                cfg=cfg,
            )


def _amend_silent_last_turn(
    state: dict[str, Any],
    *,
    outcome: str,
    obs_ms: int,
    cfg: TurnConfig,
    error: str = "",
    positive_reply: bool = False,
) -> None:
    """Amend `last_turn.outcome` when late async end evidence (`hook_stop` / `step_reply` / `step_interrupted`)
    arrives after `hc` already transitioned to `idle` and closed the turn as `silent` (B1) or provisional `errored` (R1)."""
    if outcome not in ("replied", "errored", "interrupted"):
        return
    turn = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
    if str(turn.get("phase") or "idle") != "idle":
        return
    cur_seq = _opt_int(turn.get("seq")) or 0
    lt = state.get("last_turn")
    if not isinstance(lt, dict) or (_opt_int(lt.get("seq")) or 0) != cur_seq or cur_seq <= 0:
        return
    prev_outcome = str(lt.get("outcome") or "")
    if prev_outcome != "silent" and not (
        prev_outcome == "errored"
        and (outcome == "interrupted" or (outcome == "replied" and positive_reply))
    ):
        return
    lt["outcome"] = outcome
    inc = state.get("incident")
    if outcome == "replied":
        if isinstance(inc, dict) and inc.get("status") in ("open", "recovering", "notified"):
            if (
                not inc.get("actions")
                and str(inc.get("reason") or "") in ("silent", "errored")
                and (_opt_int(inc.get("turn_seq")) or 0) == cur_seq
            ):
                state["incident"] = None
            elif (
                (_opt_int(inc.get("turn_seq")) or 0) == cur_seq
                or (lt.get("id") and inc.get("turn_id") == lt.get("id"))
                or str(lt.get("cause") or "") in ("user", "deliver", "recovery")
                or inc.get("awaiting_verify") == "turn_outcome"
            ):
                _resolve_incident(state, obs_ms, cfg, resolution="replied")
    elif outcome == "interrupted":
        if (
            isinstance(inc, dict)
            and not inc.get("actions")
            and str(inc.get("reason") or "") in ("silent", "errored")
            and (_opt_int(inc.get("turn_seq")) or 0) == cur_seq
        ):
            state["incident"] = None
    elif outcome == "errored":
        cause_kind = str(lt.get("cause") or "")
        has_open_inc = isinstance(inc, Mapping) and inc.get("status") in ("open", "recovering")
        if not has_open_inc and cause_kind in ("user", "deliver"):
            causes = state.get("turn_causes") if isinstance(state.get("turn_causes"), Mapping) else {}
            c_entry = causes.get(str(cur_seq)) if isinstance(causes.get(str(cur_seq)), Mapping) else {}
            batch_val = list(c_entry["batch"]) if isinstance(c_entry.get("batch"), list) else None
            _open_incident(
                state,
                cls="W2",
                turn_id=str(lt.get("id") or ""),
                turn_seq=cur_seq,
                cause_kind=cause_kind,
                msg_ids=[],
                batch=batch_val,
                reason="errored",
                error=error,
                now_ms=obs_ms,
                cfg=cfg,
            )


def _reset_session(
    state: dict[str, Any],
    new_ep: Endpoint,
    *,
    now_ms: int,
    cfg: TurnConfig,
) -> None:
    """Reset turn state when endpoint identity (terminal / fg_pid / epoch) changes (I1, FS-10)."""
    inc = state.get("incident")
    had_unresolved_incident = (
        isinstance(inc, dict)
        and inc.get("status") in ("open", "recovering", "notified")
    )
    cur_phase = str(state["turn"].get("phase") or "idle")
    if cur_phase != "idle":
        _close_turn(state, outcome="interrupted", now_ms=now_ms, cfg=cfg, aborted=True)
    if had_unresolved_incident:
        _resolve_incident(state, now_ms, cfg, resolution="session_rotated")
    state["session"] = new_ep.to_dict()
    fresh = _default_turn(cfg)
    fresh["seq"] = _opt_int(state["turn"].get("seq")) or 0
    state["turn"] = fresh
    state["bg_shells"] = {"count": 0, "commands": []}


def _on_confirmed_turn_started(
    state: dict[str, Any],
    now_ms: int,
    cfg: TurnConfig,
    *,
    cause_kind: str = "",
) -> None:
    """Reconcile any active incident once a turn has genuinely started (`phase != 'submitted'`)."""
    inc = state.get("incident")
    if not isinstance(inc, dict):
        return
    st_inc = inc.get("status")
    if st_inc == "resolved":
        state["incident"] = None
        return
    if st_inc not in ("open", "recovering"):
        return
    if inc.get("class") == "W6":
        _resolve_incident(state, now_ms, cfg, resolution="turn_started")
        return
    is_recovery_turn = (
        cause_kind == "recovery"
        or inc.get("awaiting_verify") in (
            "continue_turn", "nudge_enter", "retype_submitted", "restart_seat", "switch_profile",
        )
        or inc.get("awaiting_action") in (
            "continue_turn", "nudge_enter", "retype_submitted", "restart_seat", "switch_profile",
        )
    )
    if is_recovery_turn:
        turn = state.get("turn") if isinstance(state.get("turn"), Mapping) else {}
        cur_tid = str(turn.get("id") or "")
        cur_tseq = _opt_int(turn.get("seq")) or 0
        if cur_tid:
            inc["turn_id"] = cur_tid
        if cur_tseq > 0:
            inc["turn_seq"] = cur_tseq
        inc["status"] = "recovering"
        inc["awaiting_action"] = ""
        inc["awaiting_verify"] = "turn_outcome"
        inc["verify_deadline_ms"] = 0
        inc["next_due_ms"] = 0
        inc["updated_ms"] = now_ms


def _open_new_turn(
    state: dict[str, Any],
    *,
    started_ms: int,
    now_ms: int,
    hc_turn: int,
    phase: str,
    cause_kind: str,
    msg_ids: list[str],
    batch: list[int] | None,
    hook_confirmed: bool,
    provisional: bool,
    cfg: TurnConfig,
) -> int:
    prev_seq = _opt_int(state["turn"].get("seq")) or 0
    new_seq = prev_seq + 1
    ep = endpoint_from_dict(state.get("session"))
    fresh = _default_turn(cfg)
    fresh["seq"] = new_seq
    fresh["hc_turn"] = max(0, int(hc_turn or 0))
    fresh["id"] = format_turn_id(ep, fresh["hc_turn"])
    fresh["phase"] = phase
    fresh["health"] = "ok"
    fresh["cause"] = {
        "kind": cause_kind or "self",
        "msg_ids": list(dict.fromkeys(str(m) for m in msg_ids if m)),
        "batch": list(batch) if isinstance(batch, list) and len(batch) == 2 else None,
    }
    anchor = started_ms if started_ms > 0 else now_ms
    fresh["started_ms"] = anchor
    fresh["opened_ms"] = max(anchor, now_ms)
    fresh["phase_since_ms"] = anchor
    fresh["last_progress_ms"] = max(anchor, now_ms)
    fresh["metrics"] = _empty_metrics(phase, anchor)
    fresh["hook_confirmed"] = hook_confirmed
    fresh["provisional"] = provisional
    fresh["evidence"]["hc"] = copy.deepcopy(state["turn"]["evidence"]["hc"])
    fresh["evidence"]["step"]["last_ms"] = anchor
    if phase == "generating":
        fresh["activity"] = {
            "kind": "generate",
            "tool": "",
            "summary": "",
            "since_ms": anchor,
            "preamble": "",
        }
    state["turn"] = fresh
    inc = state.get("incident")
    if phase != "submitted":
        _on_confirmed_turn_started(state, now_ms, cfg, cause_kind=cause_kind)
    elif isinstance(inc, dict):
        if inc.get("status") == "resolved":
            state["incident"] = None
        elif inc.get("class") == "W6" and inc.get("status") in ("open", "recovering"):
            inc["turn_id"] = fresh["id"]
            inc["turn_seq"] = new_seq
    # Preserve `turn_causes` for late async Stop attribution (FS-9).
    causes = dict(state.get("turn_causes") or {})
    if cause_kind == "deliver" and isinstance(batch, list) and len(batch) == 2:
        causes[str(new_seq)] = {"after": "deliver", "batch": list(batch)}
    else:
        causes.pop(str(new_seq), None)
    state["turn_causes"] = causes
    sid = str((state.get("session") or {}).get("session_id") or "")
    if sid:
        s_turns = dict(state.get("session_turns") or {})
        s_turns[sid] = new_seq
        state["session_turns"] = s_turns
    return new_seq


def _merge_turn_cause(
    state: dict[str, Any],
    *,
    cause_kind: str,
    msg_ids: list[str],
    batch: list[int] | None,
    hook_confirmed: bool,
    session_id: str = "",
) -> None:
    turn = state["turn"]
    cause = turn["cause"]
    if cause_kind and (not cause.get("kind") or cause.get("kind") == "self"):
        cause["kind"] = cause_kind
    existing_ids = list(cause.get("msg_ids") or [])
    for mid in msg_ids:
        if mid and mid not in existing_ids:
            existing_ids.append(mid)
    cause["msg_ids"] = existing_ids
    if isinstance(batch, list) and len(batch) == 2 and not cause.get("batch"):
        cause["batch"] = list(batch)
    if hook_confirmed:
        turn["hook_confirmed"] = True
        turn["provisional"] = False
    seq = _opt_int(turn.get("seq")) or 0
    if seq > 0:
        causes = dict(state.get("turn_causes") or {})
        if cause.get("kind") == "deliver" and isinstance(cause.get("batch"), list):
            causes[str(seq)] = {"after": "deliver", "batch": list(cause["batch"])}
        state["turn_causes"] = causes
        if session_id:
            s_turns = dict(state.get("session_turns") or {})
            s_turns[session_id] = seq
            state["session_turns"] = s_turns


def _can_merge_provisional(turn: Mapping[str, Any], *, hc_turn: int, obs_ms: int) -> bool:
    if str(turn.get("phase") or "idle") not in ACTIVE_TURN_PHASES:
        return False
    cur_tt = _opt_int(turn.get("hc_turn")) or 0
    if hc_turn > 0 and cur_tt > 0 and hc_turn != cur_tt:
        return False
    if bool(turn.get("provisional")):
        return True
    started = _opt_int(turn.get("started_ms")) or 0
    # Unconfirmed send_submitted / recent turn anchor within 15s merges instead of double-counting (FS-14).
    if not turn.get("hook_confirmed") and started > 0 and abs(obs_ms - started) <= 15_000:
        return True
    return False


def _clear_pty_freeze(turn: dict[str, Any], at_ms: int) -> None:
    pty = turn["evidence"]["pty"]
    pty["changed_ms"] = max(_opt_int(pty.get("changed_ms")) or 0, at_ms)
    pty["frozen_since_ms"] = 0
    if turn.get("health_reason") in ("pty_frozen", "pty_suspect"):
        turn["health"] = "ok"
        turn["health_reason"] = ""
        turn["suspect_since_ms"] = 0


def _infer_close_outcome(state: Mapping[str, Any], explicit_outcome: str = "") -> str:
    if explicit_outcome in ("replied", "interrupted", "errored", "silent"):
        return explicit_outcome
    turn = state["turn"]
    ev = turn["evidence"]
    step = ev["step"]
    if _opt_int(turn.get("pending_interrupt_ms")) and turn.get("interrupt_outcome") in ("stopped", "exited"):
        return "interrupted"
    if str(step.get("last_kind") or "") == "interrupted":
        return "interrupted"
    if str(step.get("last_kind") or "") == "reply":
        return "replied"
    if (
        str(ev["hc"].get("state") or "") == "error"
        or str(step.get("last_kind") or "") == "error"
    ):
        return "errored"
    if bool(step.get("ended")):
        return "replied"
    return "silent"


def _apply_endpoint_update(state: dict[str, Any], obs: Mapping[str, Any], now_ms: int, cfg: TurnConfig) -> None:
    raw_ep = obs.get("endpoint")
    ep = endpoint_from_dict(raw_ep) if isinstance(raw_ep, Mapping) else None
    if ep is None:
        term = str(obs.get("terminal") or "").strip()
        kind = str(obs.get("agent_kind") or "").strip().lower()
        sid = str(obs.get("session_id") or "").strip()
        fg = _opt_pos_int(obs.get("fg_pid"))
        if not term and not kind and not sid and fg is None:
            return
        cur_ep = endpoint_from_dict(state.get("session"))
        if term:
            ep = parse_legacy_endpoint(
                term,
                cur_ep.workspace if cur_ep else "",
                kind or (cur_ep.agent_kind if cur_ep else ""),
                runtime_hint=(cur_ep.runtime if cur_ep and cur_ep.runtime else "hc"),
                session_id=sid or (cur_ep.session_id if cur_ep else ""),
                fg_pid=fg if fg is not None else (cur_ep.fg_pid if cur_ep else None),
                epoch=cur_ep.epoch if cur_ep else 1,
            )
        elif cur_ep is not None:
            ep = Endpoint(
                runtime=cur_ep.runtime,
                machine=cur_ep.machine,
                terminal=cur_ep.terminal,
                workspace=cur_ep.workspace,
                session_id=sid or cur_ep.session_id,
                agent_kind=kind or cur_ep.agent_kind,
                fg_pid=fg if fg is not None else cur_ep.fg_pid,
                epoch=cur_ep.epoch,
            )
    if ep is None:
        return

    cur_ep = endpoint_from_dict(state.get("session"))
    if cur_ep is not None and cur_ep.terminal:
        term_changed = (ep.runtime, ep.machine, ep.terminal) != (cur_ep.runtime, cur_ep.machine, cur_ep.terminal)
        pid_changed = bool(ep.fg_pid and cur_ep.fg_pid and ep.fg_pid != cur_ep.fg_pid)
        epoch_changed = ep.epoch != cur_ep.epoch
        if term_changed or pid_changed or epoch_changed:
            _reset_session(state, ep, now_ms=now_ms, cfg=cfg)
            return
    merged = Endpoint(
        runtime=ep.runtime,
        machine=ep.machine,
        terminal=ep.terminal or (cur_ep.terminal if cur_ep else ""),
        workspace=ep.workspace or (cur_ep.workspace if cur_ep else ""),
        session_id=ep.session_id or (cur_ep.session_id if cur_ep else ""),
        agent_kind=ep.agent_kind or (cur_ep.agent_kind if cur_ep else ""),
        fg_pid=ep.fg_pid or (cur_ep.fg_pid if cur_ep else None),
        epoch=ep.epoch or (cur_ep.epoch if cur_ep else 1),
    )
    state["session"] = merged.to_dict()
    if state["turn"].get("id"):
        state["turn"]["id"] = format_turn_id(merged, _opt_int(state["turn"].get("hc_turn")) or 0)


def reduce(state: Mapping[str, Any], obs: Mapping[str, Any], cfg: TurnConfig | None = None) -> dict[str, Any]:
    """Pure observation reducer `(state, obs, cfg) -> next_state` (zero IO, zero clock calls, deterministic).

    Implements I1-I5 and anchoring rules T1-T4 (`docs/design/pm-stuck-root-fix.md` §3.3-3.4).
    """
    c = cfg or TurnConfig()
    nxt = upgrade_state_v1_to_v2(state, cfg=c)
    if not isinstance(obs, Mapping):
        return nxt

    obs_seq = _opt_int(obs.get("seq"))
    cur_jseq = _opt_int(nxt.get("journal_seq")) or 0
    if obs_seq is not None and obs_seq > 0:
        if obs_seq <= cur_jseq:
            return nxt  # Idempotent on already-applied observation seq.
        nxt["journal_seq"] = obs_seq

    obs_ms = _opt_int(obs.get("t")) or _opt_int(nxt.get("updated_ms")) or 0
    kind = str(obs.get("kind") or "").strip()

    if kind == "turn_summary":
        nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
        return sync_compat_fields(nxt)

    if kind == "session_reset":
        ep = endpoint_from_dict(obs.get("endpoint") if isinstance(obs.get("endpoint"), Mapping) else None)
        if ep is None:
            cur_ep = endpoint_from_dict(nxt.get("session")) or Endpoint(runtime="hc", terminal="")
            ep = Endpoint(
                runtime=cur_ep.runtime,
                machine=cur_ep.machine,
                terminal=str(obs.get("terminal") or cur_ep.terminal),
                workspace=cur_ep.workspace,
                session_id=str(obs.get("session_id") or ""),
                agent_kind=str(obs.get("agent_kind") or cur_ep.agent_kind),
                fg_pid=_opt_pos_int(obs.get("fg_pid")),
                epoch=(_opt_pos_int(obs.get("epoch")) or (cur_ep.epoch + 1)),
            )
        _reset_session(nxt, ep, now_ms=obs_ms, cfg=c)
        nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
        return sync_compat_fields(nxt)

    _apply_endpoint_update(nxt, obs, obs_ms, c)
    turn = nxt["turn"]
    ev = turn["evidence"]

    if kind == "hc_state":
        term_state = str(obs.get("state") or "live").strip().lower()
        agent_status = str(obs.get("status") or "").strip().lower()
        status_ms = _opt_int(obs.get("status_ms")) or 0
        hc_turn = _opt_int(obs.get("turn"))
        reported = obs.get("reported")
        if reported is None:
            reported = bool(agent_status)
        status_msg = str(obs.get("status_msg") or "").strip()
        dialog_kind = str(obs.get("dialog_kind") or "").strip()

        prev_hc = dict(ev["hc"])
        ev["hc"] = {
            "state": agent_status if term_state == "live" else term_state,
            "status_ms": status_ms,
            "obs_ms": obs_ms,
            "turn": hc_turn if hc_turn is not None else (_opt_int(prev_hc.get("turn")) or 0),
            "reported": bool(reported),
        }

        if term_state in ("exited", "finished", "removed", "offline"):
            prior_inc = copy.deepcopy(nxt.get("incident")) if isinstance(nxt.get("incident"), Mapping) else None
            cur_phase_off = str(turn.get("phase") or "idle")
            cur_cause_obj = turn.get("cause") if isinstance(turn.get("cause"), Mapping) else {}
            cur_cause_kind = str(cur_cause_obj.get("kind") or "")
            cur_msg_ids = [str(m) for m in (cur_cause_obj.get("msg_ids") or []) if m]
            cur_batch = list(cur_cause_obj["batch"]) if isinstance(cur_cause_obj.get("batch"), list) else None
            cur_tid = str(turn.get("id") or "")
            cur_tseq = _opt_int(turn.get("seq")) or 0
            off_steps = _opt_int((turn.get("evidence") or {}).get("step", {}).get("count")) or 0
            off_confirmed = (not bool(turn.get("provisional"))) or bool(turn.get("hook_confirmed")) or off_steps > 0
            was_work = (
                (cur_phase_off in ACTIVE_TURN_PHASES or cur_phase_off == "recovering")
                and cur_cause_kind in ("user", "deliver")
                and (off_confirmed or cur_cause_kind == "user")
            )
            had_open_incident = (
                isinstance(prior_inc, Mapping)
                and prior_inc.get("status") in ("open", "recovering")
                and prior_inc.get("cause_kind") in ("user", "deliver")
            )
            if cur_phase_off not in ("idle", "offline"):
                _close_turn(nxt, outcome="interrupted", now_ms=obs_ms, cfg=c, aborted=True)
                turn = nxt["turn"]
            turn["phase"] = "starting" if bool(obs.get("seat_starting")) else "offline"
            turn["health"] = "ok"
            turn["health_reason"] = ""
            if not bool(obs.get("seat_starting")) and (was_work or had_open_incident or bool(obs.get("has_unanswered"))):
                cur_inc = nxt.get("incident")
                keep_existing = (
                    isinstance(cur_inc, Mapping)
                    and cur_inc.get("status") in ("open", "recovering")
                    and (
                        cur_inc.get("class") == "W7"
                        or cur_inc.get("awaiting_action") in ("restart_seat", "switch_profile")
                        or cur_inc.get("awaiting_verify") in ("restart_seat", "switch_profile")
                    )
                )
                if not keep_existing:
                    eff_tid = cur_tid or str((prior_inc or {}).get("turn_id") or "")
                    eff_tseq = cur_tseq or (_opt_int((prior_inc or {}).get("turn_seq")) or 0)
                    eff_cause = (
                        cur_cause_kind
                        if cur_cause_kind in ("user", "deliver")
                        else str((prior_inc or {}).get("cause_kind") or "user")
                    )
                    eff_mids = cur_msg_ids or [str(m) for m in ((prior_inc or {}).get("msg_ids") or []) if m]
                    eff_batch = cur_batch
                    if eff_batch is None and isinstance(prior_inc, Mapping) and isinstance(prior_inc.get("batch"), list):
                        eff_batch = list(prior_inc["batch"])
                    _open_incident(
                        nxt,
                        cls="W7",
                        turn_id=eff_tid,
                        turn_seq=eff_tseq,
                        cause_kind=eff_cause if eff_cause in ("user", "deliver") else "user",
                        msg_ids=eff_mids,
                        batch=eff_batch,
                        reason=term_state,
                        error=str((prior_inc or {}).get("error") or ""),
                        now_ms=obs_ms,
                        cfg=c,
                    )
            nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
            return sync_compat_fields(nxt)

        # Recover from offline/starting once terminal is live again.
        if turn.get("phase") in ("offline", "starting"):
            turn["phase"] = "idle"
            turn["health"] = "ok"
            turn["health_reason"] = ""

        # Background shells only report working after turn ended (T4).
        if obs.get("bg_only") is True or re.search(r"(?:(\d+)\s+)?shells?\s+still\s+running\b", status_msg, re.I):
            m_bg = re.search(r"(?:(\d+)\s+)?shells?\s+still\s+running\b", status_msg, re.I)
            cnt = _opt_int(obs.get("bg_count")) or (int(m_bg.group(1) or 1) if m_bg else 1)
            nxt["bg_shells"] = {
                "count": max(1, cnt),
                "commands": list(obs.get("bg_commands") or nxt.get("bg_shells", {}).get("commands") or []),
            }
            cur_phase = str(turn.get("phase") or "idle")
            cur_started = _opt_int(turn.get("started_ms")) or 0
            can_close_t4 = (
                not bool(turn.get("provisional"))
                or bool(turn.get("hook_confirmed"))
                or bool(ev["step"].get("ended"))
                or (status_ms > 0 and cur_started > 0 and status_ms > cur_started)
            )
            if cur_phase != "idle" and can_close_t4:
                _close_turn(nxt, outcome=_infer_close_outcome(nxt), now_ms=obs_ms, cfg=c)
            nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
            return sync_compat_fields(nxt)

        if agent_status in ("blocked", "error"):
            if agent_status == "blocked":
                turn["phase"] = "blocked"
                turn["phase_since_ms"] = status_ms or obs_ms
                turn["health"] = "ok"
                turn["health_reason"] = dialog_kind or status_msg
                turn["activity"] = {
                    "kind": "blocked",
                    "tool": "",
                    "summary": dialog_kind or status_msg,
                    "since_ms": status_ms or obs_ms,
                    "preamble": "",
                }
            else:
                cur_phase_err = str(turn.get("phase") or "idle")
                same_stale_error = (
                    str(prev_hc.get("state") or "") == "error"
                    and status_ms == (_opt_int(prev_hc.get("status_ms")) or 0)
                    and ev["hc"]["turn"] == (_opt_int(prev_hc.get("turn")) or 0)
                )
                if same_stale_error and (
                    cur_phase_err == "recovering"
                    or (cur_phase_err == "submitted" and bool(turn.get("provisional")) and not bool(turn.get("hook_confirmed")))
                ):
                    pass
                elif cur_phase_err in ACTIVE_TURN_PHASES or cur_phase_err == "recovering":
                    _close_turn(nxt, outcome="errored", now_ms=obs_ms, cfg=c)
                else:
                    turn["phase"] = "idle"
            nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
            return sync_compat_fields(nxt)

        if agent_status in ("idle", "done"):
            if str(turn.get("phase") or "idle") == "submitted":
                # Keep `submitted` briefly while waiting for terminal to flip to `working`.
                pass
            elif str(turn.get("phase") or "idle") != "idle":
                _close_turn(nxt, outcome=_infer_close_outcome(nxt), now_ms=obs_ms, cfg=c)
            nxt["bg_shells"] = {"count": 0, "commands": []}
            nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
            return sync_compat_fields(nxt)

        if agent_status == "working":
            cur_phase = str(turn.get("phase") or "idle")
            cur_hc_turn = _opt_int(turn.get("hc_turn")) or 0
            cur_started = _opt_int(turn.get("started_ms")) or 0
            new_hc_turn = hc_turn if hc_turn is not None else cur_hc_turn

            # T4: terminal still reports `working` solely due to background shells after turn closed.
            if cur_phase == "idle" and bool(ev["step"].get("ended")) and (nxt["bg_shells"].get("count") or 0) > 0:
                if status_ms <= 0 or status_ms <= (_opt_int(prev_hc.get("status_ms")) or 0):
                    nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
                    return sync_compat_fields(nxt)

            # T2 merge when `submitted` / provisional turn gets confirmed by hc `working`.
            if cur_phase == "submitted":
                _account_phase_segment(turn, status_ms or obs_ms, next_phase="generating")
                turn["phase"] = "generating"
                turn["provisional"] = False
                turn["hc_turn"] = new_hc_turn
                turn["id"] = format_turn_id(endpoint_from_dict(nxt["session"]), new_hc_turn)
                if status_ms > 0:
                    turn["started_ms"] = status_ms
                    turn["phase_since_ms"] = status_ms
                    turn["last_progress_ms"] = max(status_ms, obs_ms)
                else:
                    turn["phase_since_ms"] = obs_ms
                    turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
                turn["opened_ms"] = max(_opt_int(turn.get("opened_ms")) or 0, _opt_int(turn.get("started_ms")) or 0, obs_ms)
                turn["health"] = "ok"
                turn["health_reason"] = ""
                turn["suspect_since_ms"] = 0
                turn["activity"] = {
                    "kind": "generate",
                    "tool": "",
                    "summary": "",
                    "since_ms": turn["phase_since_ms"],
                    "preamble": "",
                }
                _on_confirmed_turn_started(
                    nxt, obs_ms, c, cause_kind=str((turn.get("cause") or {}).get("kind") or ""),
                )
                nxt["bg_shells"] = {"count": 0, "commands": []}
                nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
                return sync_compat_fields(nxt)

            # T1: terminal entered `working`, or `(hc_turn, status_ms)` differs from current turn -> open new turn!
            last_prog = _opt_int(turn.get("last_progress_ms")) or 0
            inc_cur = nxt.get("incident") if isinstance(nxt.get("incident"), Mapping) else {}
            inc_expects_turn = inc_cur.get("status") in ("open", "recovering") and inc_cur.get("awaiting_verify") in (
                "continue_turn", "nudge_enter", "retype_submitted", "restart_seat", "switch_profile",
            )
            boundary_changed = (
                cur_phase in ("idle", "blocked")
                or (cur_phase == "recovering" and inc_expects_turn)
                or (hc_turn is not None and cur_hc_turn > 0 and hc_turn != cur_hc_turn)
                or (status_ms > 0 and cur_started > 0 and status_ms > max(cur_started, last_prog) + 2_000)
            )
            if boundary_changed:
                if cur_phase in ACTIVE_TURN_PHASES:
                    # Wait: only split an already active turn if `hc_turn` actually changed;
                    # if a provisional turn was opened right before `hc_state(working)` arrived, merge instead!
                    if (
                        cur_hc_turn == 0 or hc_turn is None or hc_turn == cur_hc_turn
                    ) and _can_merge_provisional(turn, hc_turn=new_hc_turn, obs_ms=obs_ms):
                        turn["provisional"] = False
                        turn["hc_turn"] = new_hc_turn
                        turn["id"] = format_turn_id(endpoint_from_dict(nxt["session"]), new_hc_turn)
                        if status_ms > 0:
                            turn["started_ms"] = status_ms
                        turn["opened_ms"] = max(_opt_int(turn.get("opened_ms")) or 0, _opt_int(turn.get("started_ms")) or 0, obs_ms)
                        nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
                        return sync_compat_fields(nxt)
                    _close_turn(nxt, outcome=_infer_close_outcome(nxt), now_ms=obs_ms, cfg=c)

                if cur_phase in ACTIVE_TURN_PHASES and _can_merge_provisional(turn, hc_turn=new_hc_turn, obs_ms=obs_ms):
                    turn["provisional"] = False
                    turn["hc_turn"] = new_hc_turn
                    turn["id"] = format_turn_id(endpoint_from_dict(nxt["session"]), new_hc_turn)
                    turn["opened_ms"] = max(_opt_int(turn.get("opened_ms")) or 0, _opt_int(turn.get("started_ms")) or 0, obs_ms)
                else:
                    cause_kind = str(obs.get("cause") or "self")
                    _open_new_turn(
                        nxt,
                        started_ms=status_ms or obs_ms,
                        now_ms=obs_ms,
                        hc_turn=new_hc_turn,
                        phase="generating",
                        cause_kind=cause_kind,
                        msg_ids=_clean_msg_ids(obs.get("msg_ids")),
                        batch=obs.get("batch") if isinstance(obs.get("batch"), list) else None,
                        hook_confirmed=False,
                        provisional=False,
                        cfg=c,
                    )
                    nxt["bg_shells"] = {"count": 0, "commands": []}
            else:
                turn["provisional"] = False
                turn["opened_ms"] = max(_opt_int(turn.get("opened_ms")) or 0, _opt_int(turn.get("started_ms")) or 0)
            nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
            return sync_compat_fields(nxt)

    elif kind == "send_submitted":
        cause_kind = str(obs.get("cause") or "user")
        msg_ids = _clean_msg_ids(obs.get("msg_ids"))
        batch = obs.get("batch") if isinstance(obs.get("batch"), list) else None
        hc_turn = _opt_int(obs.get("hc_turn")) or (_opt_int(ev["hc"].get("turn")) or 0)
        started_flag = obs.get("started")
        cur_phase = str(turn.get("phase") or "idle")

        if cur_phase in ACTIVE_TURN_PHASES and _can_merge_provisional(turn, hc_turn=hc_turn, obs_ms=obs_ms):
            _merge_turn_cause(nxt, cause_kind=cause_kind, msg_ids=msg_ids, batch=batch, hook_confirmed=False)
        elif cur_phase in ("idle", "blocked", "offline", "starting", "recovering"):
            target_phase = "generating" if started_flag is True else "submitted"
            _open_new_turn(
                nxt,
                started_ms=obs_ms,
                now_ms=obs_ms,
                hc_turn=hc_turn,
                phase=target_phase,
                cause_kind=cause_kind,
                msg_ids=msg_ids,
                batch=batch,
                hook_confirmed=False,
                provisional=True,
                cfg=c,
            )
            nxt["bg_shells"] = {"count": 0, "commands": []}
        else:
            # Mid-turn message queued into active turn: attach msg_id without resetting turn clock.
            _merge_turn_cause(nxt, cause_kind=cause_kind, msg_ids=msg_ids, batch=batch, hook_confirmed=False)

    elif kind == "hook_prompt":
        cause_kind = str(obs.get("cause") or "user")
        msg_ids = _clean_msg_ids(obs.get("msg_ids"))
        batch = obs.get("batch") if isinstance(obs.get("batch"), list) else None
        hc_turn = _opt_int(obs.get("hc_turn")) or (_opt_int(ev["hc"].get("turn")) or 0)
        sid = str(obs.get("session_id") or (nxt["session"].get("session_id") or ""))
        cur_phase = str(turn.get("phase") or "idle")

        cur_mids = set(_clean_msg_ids((turn.get("cause") or {}).get("msg_ids")))
        cur_steps = _opt_int(ev["step"].get("count")) or 0
        same_prompt_echo = (
            bool(msg_ids)
            and set(msg_ids).issubset(cur_mids)
            and cur_steps == 0
            and abs(obs_ms - (_opt_int(turn.get("started_ms")) or 0)) <= 15_000
        )
        if cur_phase in ACTIVE_TURN_PHASES and (
            _can_merge_provisional(turn, hc_turn=hc_turn, obs_ms=obs_ms)
            or same_prompt_echo
            or (
                turn.get("cause", {}).get("kind") == "self"
                and (obs_ms - (_opt_int(turn.get("started_ms")) or 0)) <= 15_000
            )
        ):
            # T1/T2 merge: `hc_state(working)` or `send_submitted` already anchored this turn; enrich cause!
            if cur_phase == "submitted":
                _account_phase_segment(turn, obs_ms, next_phase="generating")
                turn["phase"] = "generating"
                turn["phase_since_ms"] = obs_ms
                turn["activity"] = {
                    "kind": "generate",
                    "tool": "",
                    "summary": "",
                    "since_ms": obs_ms,
                    "preamble": "",
                }
            _merge_turn_cause(
                nxt,
                cause_kind=cause_kind,
                msg_ids=msg_ids,
                batch=batch,
                hook_confirmed=True,
                session_id=sid,
            )
            turn["opened_ms"] = max(_opt_int(turn.get("opened_ms")) or 0, _opt_int(turn.get("started_ms")) or 0, obs_ms)
            _on_confirmed_turn_started(nxt, obs_ms, c, cause_kind=cause_kind)
            turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
            ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)
        else:
            if cur_phase in ACTIVE_TURN_PHASES:
                _close_turn(nxt, outcome=_infer_close_outcome(nxt), now_ms=obs_ms, cfg=c)
            _open_new_turn(
                nxt,
                started_ms=obs_ms,
                now_ms=obs_ms,
                hc_turn=hc_turn,
                phase="generating",
                cause_kind=cause_kind,
                msg_ids=msg_ids,
                batch=batch,
                hook_confirmed=True,
                provisional=False,
                cfg=c,
            )
            nxt["bg_shells"] = {"count": 0, "commands": []}

    elif kind == "step_system":
        cur_phase = str(turn.get("phase") or "idle")
        hc_turn = _opt_int(obs.get("hc_turn")) or (_opt_int(ev["hc"].get("turn")) or 0)
        if cur_phase == "idle":
            _open_new_turn(
                nxt,
                started_ms=obs_ms,
                now_ms=obs_ms,
                hc_turn=hc_turn,
                phase="generating",
                cause_kind="self",
                msg_ids=[],
                batch=None,
                hook_confirmed=False,
                provisional=True,
                cfg=c,
            )
        else:
            turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
            ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)

    elif kind == "step_tool_start":
        tool = str(obs.get("tool") or "tool").strip()
        summary = str(obs.get("summary") or "").strip()[:80]
        preamble = str(obs.get("preamble") or "").strip()[:120]
        cur_phase = str(turn.get("phase") or "idle")
        if cur_phase in ("idle", "submitted"):
            if cur_phase == "idle":
                _open_new_turn(
                    nxt,
                    started_ms=obs_ms,
                    now_ms=obs_ms,
                    hc_turn=_opt_int(ev["hc"].get("turn")) or 0,
                    phase="tool",
                    cause_kind=str(obs.get("cause") or "self"),
                    msg_ids=[],
                    batch=None,
                    hook_confirmed=False,
                    provisional=False,
                    cfg=c,
                )
                turn = nxt["turn"]
                ev = turn["evidence"]
            else:
                turn["provisional"] = False
                turn["opened_ms"] = max(_opt_int(turn.get("opened_ms")) or 0, _opt_int(turn.get("started_ms")) or 0, obs_ms)
                _on_confirmed_turn_started(
                    nxt, obs_ms, c, cause_kind=str((turn.get("cause") or {}).get("kind") or ""),
                )
        _account_phase_segment(turn, obs_ms, next_phase="tool")
        turn["phase"] = "tool"
        turn["phase_since_ms"] = obs_ms
        turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
        turn["health"] = "ok"
        turn["health_reason"] = ""
        turn["suspect_since_ms"] = 0
        ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)
        ev["step"]["count"] = (_opt_int(ev["step"].get("count")) or 0) + 1
        ev["step"]["ended"] = False
        ev["step"]["last_kind"] = "tool_start"
        ev["step"]["last_error"] = ""
        ev["pty"]["frozen_since_ms"] = 0
        turn["activity"] = {
            "kind": "tool",
            "tool": tool,
            "summary": summary,
            "since_ms": obs_ms,
            "preamble": preamble,
        }

    elif kind == "step_tool_end":
        cur_phase = str(turn.get("phase") or "idle")
        ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)
        ev["step"]["last_kind"] = "tool_end"
        ev["step"]["last_error"] = ""
        inc_w4 = nxt.get("incident")
        if isinstance(inc_w4, dict) and inc_w4.get("class") == "W4" and inc_w4.get("status") in ("open", "recovering"):
            if inc_w4.get("awaiting_verify") == "interrupt_tool" or any(
                isinstance(a, Mapping) and a.get("action") == "interrupt_tool"
                for a in (inc_w4.get("actions") or ())
            ):
                _resolve_incident(nxt, obs_ms, c, resolution="tool_exited")
        if cur_phase in ACTIVE_TURN_PHASES or cur_phase == "recovering":
            _account_phase_segment(turn, obs_ms, next_phase="generating")
            turn["phase"] = "generating"
            turn["phase_since_ms"] = obs_ms
            turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
            turn["health"] = "ok"
            turn["health_reason"] = ""
            turn["suspect_since_ms"] = 0
            ev["pty"]["frozen_since_ms"] = 0
            ev["proc"] = {"tool_pid": 0, "cmd": "", "since_ms": 0, "cpu_ms": 0, "cpu_changed_ms": 0}
            turn["activity"] = {
                "kind": "generate",
                "tool": "",
                "summary": "",
                "since_ms": obs_ms,
                "preamble": "",
            }

    elif kind == "step_error":
        # FS-7: ERROR_MESSAGE never closes the turn! It records error evidence and transitions to
        # `waiting_upstream` when the error message indicates a retry/upstream backoff.
        msg = str(obs.get("message") or "").strip()
        retrying = bool(obs.get("retrying")) or bool(_RETRY_MSG_RE.search(msg))
        attempt = _opt_int(obs.get("attempt")) or 0
        if not attempt and msg:
            m_att = _RETRY_HINT_RE.search(msg)
            if m_att:
                attempt = int(m_att.group(1) or m_att.group(2))
        ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)
        ev["step"]["last_kind"] = "error"
        ev["step"]["last_error"] = msg[:200]
        if str(turn.get("phase") or "idle") in ACTIVE_TURN_PHASES or str(turn.get("phase") or "") == "recovering":
            turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
            if retrying:
                _account_phase_segment(turn, obs_ms, next_phase="waiting_upstream")
                turn["phase"] = "waiting_upstream"
                turn["phase_since_ms"] = obs_ms
                turn["health"] = "slow"
                turn["health_reason"] = "upstream_retry"
                turn["activity"] = {
                    "kind": "waiting_upstream",
                    "tool": "",
                    "summary": f"retry:{attempt}" if attempt else msg[:80],
                    "since_ms": obs_ms,
                    "preamble": "",
                }

    elif kind == "step_interrupted":
        ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)
        ev["step"]["last_kind"] = "interrupted"
        ev["step"]["ended"] = True
        ev["step"]["last_error"] = ""
        if str(turn.get("phase") or "idle") == "idle":
            _amend_silent_last_turn(nxt, outcome="interrupted", obs_ms=obs_ms, cfg=c)

    elif kind == "step_reply":
        ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)
        ev["step"]["last_kind"] = "reply"
        ev["step"]["ended"] = True
        ev["step"]["last_error"] = ""
        if str(turn.get("phase") or "idle") in ACTIVE_TURN_PHASES or str(turn.get("phase") or "") == "recovering":
            turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
            # If terminal does not report status (or only bg shells remain), step_reply closes the turn cleanly;
            # when `hc` is actively tracking `working` and `close_turn` isn't requested yet, let `hook_stop` or
            # `hc_state(idle/done)` close it (or close immediately if `close_turn=True`).
            if bool(obs.get("close_turn")) or ev["hc"].get("reported") is False:
                _close_turn(nxt, outcome="replied", now_ms=obs_ms, cfg=c)
        elif str(turn.get("phase") or "idle") == "idle":
            lt = nxt.get("last_turn")
            if isinstance(lt, Mapping):
                lt_ended = _opt_int(lt.get("ended_ms")) or 0
                lt_started = _opt_int(lt.get("started_ms")) or max(0, lt_ended - (_opt_int(lt.get("duration_ms")) or 0))
                in_window = (
                    obs_ms <= 0
                    or (
                        obs_ms >= max(0, lt_started - 2_000)
                        and (lt_ended <= 0 or obs_ms <= lt_ended + 30_000)
                    )
                )
                if in_window:
                    _amend_silent_last_turn(nxt, outcome="replied", obs_ms=obs_ms, cfg=c, positive_reply=True)

    elif kind == "hook_stop":
        expected_seq = _opt_int(obs.get("expected_seq"))
        cur_seq = _opt_int(turn.get("seq")) or 0
        # FS-9: drop late Stop belonging to a prior turn!
        if expected_seq is not None and expected_seq > 0 and cur_seq > expected_seq:
            nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
            return sync_compat_fields(nxt)
        has_reply = obs.get("has_reply")
        if has_reply is True:
            ev["step"]["last_kind"] = "reply"
            ev["step"]["ended"] = True
            ev["step"]["last_error"] = ""
        elif str(ev["step"].get("last_kind") or "") != "error" and not obs.get("outcome"):
            ev["step"]["ended"] = True
        outcome = _infer_close_outcome(nxt, str(obs.get("outcome") or ""))
        if str(turn.get("phase") or "idle") != "idle":
            _close_turn(nxt, outcome=outcome, now_ms=obs_ms, cfg=c)
        elif cur_seq > 0:
            _amend_silent_last_turn(
                nxt,
                outcome=outcome,
                obs_ms=obs_ms,
                cfg=c,
                error=str(ev["step"].get("last_error") or ""),
                positive_reply=(has_reply is True),
            )

    elif kind == "pty_probe":
        changed = bool(obs.get("changed"))
        digest = str(obs.get("digest") or "")
        hint = str(obs.get("hint") or "")
        dialog = str(obs.get("dialog_kind") or "")
        pty = ev["pty"]
        if digest:
            pty["digest"] = digest
        if hint is not None:
            pty["hint"] = hint
        if dialog is not None:
            pty["dialog"] = dialog

        # §3.2 (B3): screen hints (`retry:...`, `tokens:...`) are bonus signals only and NEVER flip `phase`
        # to `waiting_upstream`; `waiting_upstream` is entered strictly from `step_error` observations.
        if changed:
            _clear_pty_freeze(turn, obs_ms)
            turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
        else:
            if not _opt_int(pty.get("frozen_since_ms")):
                pty["frozen_since_ms"] = obs_ms
            if dialog and str(turn.get("phase") or "") in ACTIVE_TURN_PHASES:
                turn["health_reason"] = dialog

    elif kind == "proc_probe":
        tool_pid = _opt_int(obs.get("tool_pid")) or 0
        cmd = str(obs.get("cmd") or "")[:80]
        cpu_ms = _opt_int(obs.get("cpu_ms")) or 0
        bg_cmds = obs.get("bg_commands")
        if isinstance(bg_cmds, list):
            nxt["bg_shells"] = {"count": len(bg_cmds), "commands": [str(x)[:120] for x in bg_cmds[:8]]}
            # T4: if turn already saw end evidence and only background shells remain while hc is `working`, go idle.
            if (
                len(bg_cmds) > 0
                and tool_pid == 0
                and str(turn.get("phase") or "") in ACTIVE_TURN_PHASES
                and bool(ev["step"].get("ended"))
            ):
                _close_turn(nxt, outcome=_infer_close_outcome(nxt), now_ms=obs_ms, cfg=c)
                nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
                return sync_compat_fields(nxt)

        proc = ev["proc"]
        prev_pid = _opt_int(proc.get("tool_pid")) or 0
        prev_cpu = _opt_int(proc.get("cpu_ms")) or 0
        if tool_pid > 0:
            if tool_pid != prev_pid:
                proc["tool_pid"] = tool_pid
                proc["cmd"] = cmd
                proc["since_ms"] = obs_ms
                proc["cpu_ms"] = cpu_ms
                proc["cpu_changed_ms"] = obs_ms
            else:
                proc["cmd"] = cmd or proc.get("cmd", "")
                if cpu_ms > prev_cpu:
                    proc["cpu_ms"] = cpu_ms
                    proc["cpu_changed_ms"] = obs_ms
                    turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
                    if turn.get("health_reason") == "tool_waiting_input":
                        turn["health"] = "ok"
                        turn["health_reason"] = ""
                        turn["suspect_since_ms"] = 0
            # Process tree proves a foreground command is running even if transcript has not flushed yet.
            if str(turn.get("phase") or "") == "generating" and cmd:
                _account_phase_segment(turn, obs_ms, next_phase="tool")
                turn["phase"] = "tool"
                turn["phase_since_ms"] = obs_ms
                turn["activity"] = {
                    "kind": "tool",
                    "tool": cmd.split(None, 1)[0][:32],
                    "summary": cmd,
                    "since_ms": obs_ms,
                    "preamble": "",
                }
        else:
            ev["proc"] = {"tool_pid": 0, "cmd": "", "since_ms": 0, "cpu_ms": 0, "cpu_changed_ms": 0}
            inc_w4 = nxt.get("incident")
            w4_resolved = False
            if isinstance(inc_w4, dict) and inc_w4.get("class") == "W4" and inc_w4.get("status") in ("open", "recovering"):
                if inc_w4.get("awaiting_verify") == "interrupt_tool" or any(
                    isinstance(a, Mapping) and a.get("action") == "interrupt_tool"
                    for a in (inc_w4.get("actions") or ())
                ):
                    _resolve_incident(nxt, obs_ms, c, resolution="tool_exited")
                    w4_resolved = True
            proc_only_tool = (
                prev_pid > 0
                and str(turn.get("phase") or "") == "tool"
                and not (_opt_int(ev["step"].get("count")) or 0)
            )
            if (w4_resolved and str(turn.get("phase") or "") == "recovering") or proc_only_tool:
                _account_phase_segment(turn, obs_ms, next_phase="generating")
                turn["phase"] = "generating"
                turn["phase_since_ms"] = obs_ms
                turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
                turn["health"] = "ok"
                turn["health_reason"] = ""
                turn["suspect_since_ms"] = 0
                ev["pty"]["frozen_since_ms"] = 0
                ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)
                turn["activity"] = {
                    "kind": "generate",
                    "tool": "",
                    "summary": "",
                    "since_ms": obs_ms,
                    "preamble": "",
                }

    elif kind == "interrupt_sent":
        outcome = str(obs.get("outcome") or "unknown")
        turn["pending_interrupt_ms"] = obs_ms
        turn["interrupt_outcome"] = outcome
        if outcome in ("stopped", "exited"):
            if str(turn.get("phase") or "idle") != "idle":
                _close_turn(nxt, outcome="interrupted", now_ms=obs_ms, cfg=c, aborted=(outcome == "exited"))
        elif outcome != "still_working":
            turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
            if turn.get("health") == "stalled":
                turn["health"] = "ok"
                turn["health_reason"] = ""

    elif kind == "recovery_started":
        cls_r = str(obs.get("class") or "").strip()
        action_r = str(obs.get("action") or "").strip()
        inc = nxt.get("incident")
        if cls_r != "W3" and isinstance(inc, dict) and inc.get("status") in ("open", "recovering"):
            inc_id = str(obs.get("incident_id") or "")
            if not inc_id or inc_id == inc.get("id"):
                stage_s = _opt_int(obs.get("stage"))
                if stage_s is not None and stage_s >= (_opt_int(inc.get("stage")) or 0):
                    inc["stage"] = stage_s
                inc["status"] = "recovering"
                inc["awaiting_action"] = action_r
                inc["step_name"] = action_r or inc.get("step_name") or ""
                inc["updated_ms"] = obs_ms
                if action_r != "classify_screen":
                    turn["phase"] = "recovering"
                    turn["phase_since_ms"] = obs_ms
                    turn["health"] = "ok"
                    turn["health_reason"] = action_r
                    turn["activity"] = {
                        "kind": "recovering",
                        "tool": "",
                        "summary": action_r,
                        "since_ms": obs_ms,
                        "preamble": "",
                    }

    elif kind == "recovery_result":
        cls_r = str(obs.get("class") or "").strip()
        action_r = str(obs.get("action") or "").strip()
        outcome_r = str(obs.get("outcome") or "").strip().lower()
        detail_r = str(obs.get("detail") or "").strip()[:200]
        if cls_r == "W3":
            turn["w3_attempts"] = (_opt_int(turn.get("w3_attempts")) or 0) + 1
            nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
            return sync_compat_fields(nxt)
        inc = nxt.get("incident")
        inc_id = str(obs.get("incident_id") or "")
        if isinstance(inc, dict) and inc.get("status") in ("open", "recovering") and (not inc_id or inc_id == inc.get("id")):
            stage_r = _opt_int(obs.get("stage"))
            if stage_r is None:
                stage_r = _opt_int(inc.get("stage")) or 0
            elif stage_r >= (_opt_int(inc.get("stage")) or 0):
                inc["stage"] = stage_r
            cur_cls = str(inc.get("class") or cls_r or "W2")
            ladder = RECOVERY_LADDERS.get(cur_cls, ())
            step_meta = dict(ladder[stage_r]) if 0 <= stage_r < len(ladder) else {"action": action_r}
            acts_log = list(inc.get("actions") or [])
            acts_log.append({
                "t": obs_ms,
                "stage": stage_r,
                "action": action_r,
                "outcome": outcome_r,
                "detail": detail_r,
            })
            inc["actions"] = acts_log[-INCIDENT_ACTIONS_LIMIT:]
            inc["awaiting_action"] = ""
            inc["updated_ms"] = obs_ms

            if action_r == "interrupt_turn" and outcome_r not in ("skipped", "breaker_tripped"):
                _record_interrupt_breaker(nxt, str(inc.get("turn_id") or ""), obs_ms, c)
            if action_r in ("restart_seat", "switch_profile") and outcome_r in ("started", "sent", "queued", "restarted"):
                _record_rotation_breaker(nxt, obs_ms, c)

            if action_r == "classify_screen":
                if outcome_r == "dialog":
                    dk = str(obs.get("dialog_kind") or detail_r or "dialog")
                    nxt["incident"] = None
                    turn["phase"] = "blocked"
                    turn["phase_since_ms"] = obs_ms
                    turn["health"] = "ok"
                    turn["health_reason"] = dk
                    turn["w3_attempts"] = 0
                    turn["activity"] = {
                        "kind": "blocked",
                        "tool": "",
                        "summary": dk,
                        "since_ms": obs_ms,
                        "preamble": "",
                    }
                elif outcome_r == "draft":
                    inc["status"] = "open"
                    inc["step_name"] = "waiting_draft"
                    inc["awaiting_verify"] = ""
                    inc["verify_deadline_ms"] = 0
                    inc["next_due_ms"] = obs_ms + 10_000
                else:
                    _advance_incident(nxt, obs_ms, c)
            elif action_r == "interrupt_tool":
                if obs.get("tool_alive") is False or outcome_r == "exited":
                    _resolve_incident(nxt, obs_ms, c, resolution="tool_exited")
                    if str(turn.get("phase") or "") == "recovering":
                        _account_phase_segment(turn, obs_ms, next_phase="generating")
                        turn["phase"] = "generating"
                        turn["phase_since_ms"] = obs_ms
                        turn["last_progress_ms"] = max(_opt_int(turn.get("last_progress_ms")) or 0, obs_ms)
                        turn["health"] = "ok"
                        turn["health_reason"] = ""
                        turn["suspect_since_ms"] = 0
                        ev["pty"]["frozen_since_ms"] = 0
                        ev["step"]["last_ms"] = max(_opt_int(ev["step"].get("last_ms")) or 0, obs_ms)
                        ev["proc"] = {"tool_pid": 0, "cmd": "", "since_ms": 0, "cpu_ms": 0, "cpu_changed_ms": 0}
                        turn["activity"] = {
                            "kind": "generate",
                            "tool": "",
                            "summary": "",
                            "since_ms": obs_ms,
                            "preamble": "",
                        }
                elif outcome_r in ("sent", "ok", "queued"):
                    verify_field = str(step_meta.get("verify_field") or "w4_verify_delay_ms")
                    verify_ms = _opt_int(getattr(c, verify_field, 5_000)) or 5_000
                    inc["awaiting_verify"] = "interrupt_tool"
                    inc["verify_deadline_ms"] = obs_ms + verify_ms
                    inc["next_due_ms"] = obs_ms + verify_ms
                else:
                    _advance_incident(nxt, obs_ms, c)
            elif action_r == "interrupt_turn":
                turn["pending_interrupt_ms"] = obs_ms
                turn["interrupt_outcome"] = outcome_r or "unknown"
                if outcome_r in ("stopped", "exited"):
                    if str(turn.get("phase") or "idle") != "idle":
                        _close_turn(nxt, outcome="interrupted", now_ms=obs_ms, cfg=c, aborted=True)
                        turn = nxt["turn"]
                        turn["pending_interrupt_ms"] = obs_ms
                        turn["interrupt_outcome"] = outcome_r or "unknown"
                    if inc.get("cause_kind") not in ("user", "deliver"):
                        _resolve_incident(nxt, obs_ms, c, resolution="interrupted")
                    elif cur_cls == "W2" and step_meta.get("action") == "continue_turn":
                        delay_ms = _step_delay_ms(step_meta, c)
                        inc["stage"] = stage_r
                        inc["step_name"] = "continue_turn"
                        inc["status"] = "open"
                        inc["awaiting_action"] = ""
                        inc["awaiting_verify"] = ""
                        inc["verify_deadline_ms"] = 0
                        inc["next_due_ms"] = obs_ms + delay_ms
                    else:
                        _advance_incident(nxt, obs_ms, c)
                else:
                    if str(turn.get("phase") or "") == "recovering":
                        turn["phase"] = "generating"
                        turn["phase_since_ms"] = obs_ms
                        turn["health"] = "stalled"
                        turn["health_reason"] = str(inc.get("reason") or "stalled")
                    if cur_cls in ("W1", "W2"):
                        # Active turn did not stop: never issue `continue_turn` into a still-running turn;
                        # skip W2 `continue_turn` stages directly to fallback/notify (stage 2+).
                        _advance_incident(nxt, obs_ms, c, force_class="W2", next_stage=2)
                    elif cur_cls == "W4":
                        _advance_incident(nxt, obs_ms, c, next_stage=len(RECOVERY_LADDERS["W4"]) - 1)
                    elif cur_cls == "W5":
                        _advance_incident(nxt, obs_ms, c, next_stage=3)
                    else:
                        _advance_incident(nxt, obs_ms, c)
            elif action_r in ("continue_turn", "nudge_enter", "retype_submitted", "restart_seat", "switch_profile"):
                if outcome_r == "superseded" and action_r in ("retype_submitted", "continue_turn"):
                    _resolve_incident(nxt, obs_ms, c, resolution="superseded")
                    if str(turn.get("phase") or "") in ("submitted", "recovering"):
                        _close_turn(nxt, outcome="superseded", now_ms=obs_ms, cfg=c, aborted=False)
                elif outcome_r in ("queued", "sent", "requeued", "started"):
                    verify_field = str(step_meta.get("verify_field") or "verify_continue_ms")
                    verify_ms = _opt_int(getattr(c, verify_field, 15_000)) or 15_000
                    inc["awaiting_verify"] = action_r
                    inc["verify_deadline_ms"] = obs_ms + verify_ms
                    inc["next_due_ms"] = obs_ms + verify_ms
                else:
                    _advance_incident(nxt, obs_ms, c)
            elif action_r == "notify_user":
                inc["status"] = "notified"
                inc["next_due_ms"] = 0
                inc["awaiting_action"] = ""
                inc["awaiting_verify"] = ""
                inc["verify_deadline_ms"] = 0
                if str(turn.get("phase") or "") == "recovering":
                    turn["phase"] = "generating"
                    turn["phase_since_ms"] = obs_ms
                    turn["health"] = "stalled"
                    turn["health_reason"] = str(inc.get("reason") or "stalled")

    elif kind == "link_state":
        prev_ls = str(nxt.get("link_state") or "connected").strip().lower()
        prev_ls_since = _opt_int(nxt.get("link_since_ms")) or 0
        new_ls = str(obs.get("link_state") or "connected").strip().lower() or "connected"
        nxt["link_state"] = new_ls
        nxt["link_since_ms"] = obs_ms
        if new_ls != "connected":
            # I4 (§5.2): partitioned or unauthorized endpoint strictly reduces to health="unknown", never stalled.
            turn["health"] = "unknown"
            turn["health_reason"] = str(obs.get("unknown_reason") or "machine_disconnected")
        elif prev_ls != "connected" and new_ls == "connected":
            if str(turn.get("health") or "") == "unknown":
                turn["health"] = "ok"
                turn["health_reason"] = ""
            if prev_ls_since > 0:
                shift_ms = max(0, obs_ms - prev_ls_since)
                if shift_ms > 0 and str(turn.get("phase") or "idle") in ACTIVE_TURN_PHASES:
                    for tk in ("started_ms", "phase_since_ms", "last_progress_ms", "suspect_since_ms"):
                        if _opt_int(turn.get(tk)):
                            turn[tk] = int(turn[tk]) + shift_ms
                    if _opt_int(ev["step"].get("last_ms")):
                        ev["step"]["last_ms"] = int(ev["step"]["last_ms"]) + shift_ms
                    if _opt_int(ev["pty"].get("frozen_since_ms")):
                        ev["pty"]["frozen_since_ms"] = int(ev["pty"]["frozen_since_ms"]) + shift_ms
                    for pk in ("since_ms", "cpu_changed_ms"):
                        if _opt_int(ev["proc"].get(pk)):
                            ev["proc"][pk] = int(ev["proc"][pk]) + shift_ms

    nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, obs_ms)
    return sync_compat_fields(nxt)


def _tick_incident_verify(state: dict[str, Any], now_ms: int, cfg: TurnConfig) -> None:
    inc = state.get("incident")
    if not isinstance(inc, dict) or inc.get("status") not in ("open", "recovering"):
        return
    awaiting_v = str(inc.get("awaiting_verify") or "")
    deadline = _opt_int(inc.get("verify_deadline_ms")) or 0
    if awaiting_v and awaiting_v != "turn_outcome" and deadline > 0 and now_ms >= deadline:
        turn = state.get("turn")
        if (
            awaiting_v in ("continue_turn", "restart_seat", "switch_profile")
            and isinstance(turn, dict)
            and str(turn.get("phase") or "") == "submitted"
            and bool(turn.get("provisional"))
            and not bool(turn.get("hook_confirmed"))
        ):
            fresh = _default_turn(cfg)
            fresh["seq"] = _opt_int(turn.get("seq")) or 0
            fresh["hc_turn"] = _opt_int(turn.get("hc_turn")) or 0
            fresh["evidence"]["hc"] = copy.deepcopy(turn["evidence"]["hc"])
            state["turn"] = fresh
        _advance_incident(state, now_ms, cfg)


def tick(
    state: Mapping[str, Any],
    now_ms: int,
    cfg: TurnConfig | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pure clock advancement `(state, now_ms, cfg) -> (next_state, due_actions)` enforcing §3.5 & §3.6."""
    c = cfg or TurnConfig()
    nxt = upgrade_state_v1_to_v2(state, cfg=c)
    if str(nxt.get("link_state") or "connected") != "connected":
        # I4: pause all turn and incident timers while endpoint connectivity is partitioned.
        nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, now_ms)
        return sync_compat_fields(nxt), []
    turn = nxt["turn"]
    phase = str(turn.get("phase") or "idle")
    actions: list[dict[str, Any]] = []

    _tick_incident_verify(nxt, now_ms, c)

    if phase in ("idle", "offline", "starting"):
        turn["health"] = "ok"
        turn["health_reason"] = ""
        turn["suspect_since_ms"] = 0
        rec_act = next_recovery_action(nxt, now_ms, c)
        if rec_act is not None:
            actions.append(rec_act)
        nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, now_ms)
        return sync_compat_fields(nxt), actions

    if phase == "blocked":
        turn["health"] = "ok"
        rec_act = next_recovery_action(nxt, now_ms, c)
        if rec_act is not None:
            actions.append(rec_act)
        nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, now_ms)
        return sync_compat_fields(nxt), actions

    if phase == "recovering":
        turn["health"] = "ok"
        rec_act = next_recovery_action(nxt, now_ms, c)
        if rec_act is not None:
            actions.append(rec_act)
        nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, now_ms)
        return sync_compat_fields(nxt), actions

    started_ms = _opt_int(turn.get("started_ms")) or now_ms
    phase_since_ms = _opt_int(turn.get("phase_since_ms")) or started_ms
    ev = turn["evidence"]
    hc_ev = ev["hc"]
    step_ev = ev["step"]
    pty_ev = ev["pty"]
    proc_ev = ev["proc"]

    last_step_ms = max(started_ms, _opt_int(step_ev.get("last_ms")) or 0)
    step_quiet_ms = max(0, now_ms - last_step_ms)
    phase_age_ms = max(0, now_ms - phase_since_ms)
    turn_elapsed_ms = max(0, now_ms - started_ms)

    # Budget tracking (over soft/hard budget).
    budget = turn.get("budget") if isinstance(turn.get("budget"), dict) else {}
    budget["soft_ms"] = c.turn_soft_budget_ms
    budget["hard_ms"] = c.turn_hard_budget_ms
    budget["over"] = turn_elapsed_ms >= c.turn_soft_budget_ms
    turn["budget"] = budget

    # §4.3 Level 2 fallback for no-status terminals: auto-close dangling turn only after positive
    # screen-freeze evidence + step/CPU silence >= 30s so Esc-without-Stop never wedges batches (I2).
    reported = hc_ev.get("reported")
    frozen_since = _opt_int(pty_ev.get("frozen_since_ms")) or 0
    if reported is False and phase in ("generating", "tool") and frozen_since > 0:
        pty_ref = max(started_ms, _opt_int(pty_ev.get("changed_ms")) or 0)
        cpu_ref = max(started_ms, _opt_int(proc_ev.get("cpu_changed_ms")) or 0)
        latest_sig = max(last_step_ms, pty_ref, cpu_ref)
        if (
            (now_ms - frozen_since) >= c.no_status_esc_idle_ms
            and (now_ms - latest_sig) >= c.no_status_esc_idle_ms
            and not _opt_int(proc_ev.get("tool_pid"))
        ):
            _close_turn(nxt, outcome="silent", now_ms=now_ms, cfg=c)
            nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, now_ms)
            return sync_compat_fields(nxt), actions

    pty_frozen_ms = max(0, now_ms - frozen_since) if frozen_since > 0 else 0
    hint = str(pty_ev.get("hint") or "")
    has_token_bonus = hint.startswith("tokens:")

    if phase == "submitted":
        if phase_age_ms >= c.submitted_stall_ms:
            turn["health"] = "stalled"
            turn["health_reason"] = "submitted_timeout"
            actions.append({"kind": "stall", "class": "W6", "reason": "submitted_timeout"})
        elif phase_age_ms >= c.submitted_suspect_ms:
            turn["health"] = "suspect"
            turn["health_reason"] = "submitted_wait"
            if not _opt_int(turn.get("suspect_since_ms")):
                turn["suspect_since_ms"] = now_ms
            actions.append({"kind": "probe_screen", "interval_ms": 1_000})
        else:
            turn["health"] = "ok"
            turn["health_reason"] = ""
            turn["suspect_since_ms"] = 0

    elif phase == "generating":
        # Positive evidence first: screen frozen >= 45s -> W5 stalled (I2).
        if pty_frozen_ms >= c.generating_pty_stall_ms:
            turn["health"] = "stalled"
            turn["health_reason"] = "pty_frozen"
            actions.append({"kind": "stall", "class": "W5", "reason": "pty_frozen"})
        elif (
            c.generating_no_step_stall_ms > 0
            and reported is not False
            and step_quiet_ms >= c.generating_no_step_stall_ms
            and not has_token_bonus
        ):
            turn["health"] = "stalled"
            turn["health_reason"] = "no_step_timeout"
            actions.append({"kind": "stall", "class": "W1", "reason": "no_step_timeout"})
        elif pty_frozen_ms >= c.generating_pty_suspect_ms:
            turn["health"] = "suspect"
            turn["health_reason"] = "pty_suspect"
            if not _opt_int(turn.get("suspect_since_ms")):
                turn["suspect_since_ms"] = now_ms
            actions.append({"kind": "probe_screen", "interval_ms": 1_000})
        elif step_quiet_ms >= c.generating_slow_ms:
            turn["health"] = "slow"
            turn["health_reason"] = "long_generation"
            turn["suspect_since_ms"] = 0
            actions.append({"kind": "probe_screen", "interval_ms": c.generating_pty_probe_interval_ms})
        else:
            turn["health"] = "ok"
            turn["health_reason"] = ""
            turn["suspect_since_ms"] = 0
            if step_quiet_ms >= c.generating_pty_probe_after_ms:
                actions.append({"kind": "probe_screen", "interval_ms": c.generating_pty_probe_interval_ms})

    elif phase == "tool":
        cmd_since = _opt_int(proc_ev.get("since_ms")) or phase_since_ms
        cmd_age_ms = max(0, now_ms - cmd_since)
        cpu_changed_ms = _opt_int(proc_ev.get("cpu_changed_ms")) or cmd_since
        cpu_flat_ms = max(0, now_ms - cpu_changed_ms) if _opt_int(proc_ev.get("tool_pid")) else 0
        suspect_since = _opt_int(turn.get("suspect_since_ms")) or 0
        suspect_age_ms = max(0, now_ms - suspect_since) if suspect_since > 0 else 0

        if cmd_age_ms >= c.tool_hard_ms:
            turn["health"] = "stalled"
            turn["health_reason"] = "tool_hard_budget"
            actions.append({"kind": "stall", "class": "W4", "reason": "tool_hard_budget"})
        elif suspect_since > 0 and suspect_age_ms >= c.tool_suspect_stall_ms:
            turn["health"] = "stalled"
            turn["health_reason"] = "tool_waiting_input"
            actions.append({"kind": "stall", "class": "W4", "reason": "tool_waiting_input"})
        elif cpu_flat_ms >= c.tool_suspect_ms and pty_frozen_ms >= c.tool_suspect_ms:
            turn["health"] = "suspect"
            turn["health_reason"] = "tool_waiting_input"
            if not suspect_since:
                turn["suspect_since_ms"] = now_ms
            actions.append({"kind": "probe_screen", "interval_ms": 1_000})
        elif cmd_age_ms >= c.tool_soft_ms:
            turn["health"] = "slow"
            turn["health_reason"] = "tool_soft_budget"
            turn["suspect_since_ms"] = 0
            actions.append({"kind": "probe_proc", "interval_ms": 5_000})
        else:
            turn["health"] = "ok"
            turn["health_reason"] = ""
            turn["suspect_since_ms"] = 0

    elif phase == "waiting_upstream":
        if phase_age_ms >= c.upstream_stall_ms:
            turn["health"] = "stalled"
            turn["health_reason"] = "upstream_timeout"
            actions.append({"kind": "stall", "class": "W1", "reason": "upstream_timeout"})
        else:
            turn["health"] = "slow"
            turn["health_reason"] = turn.get("health_reason") or "upstream_retry"

    stall_act = next((a for a in actions if a.get("kind") == "stall"), None)
    if stall_act is not None:
        cur_inc = nxt.get("incident")
        turn_id = str(turn.get("id") or "")
        turn_seq = _opt_int(turn.get("seq")) or 0
        stall_cls = str(stall_act.get("class") or "W1")
        cause_obj = turn.get("cause") if isinstance(turn.get("cause"), Mapping) else {}
        turn_cause_kind = str(cause_obj.get("kind") or "self")
        inc_seq = (_opt_int(cur_inc.get("turn_seq")) or 0) if isinstance(cur_inc, Mapping) else 0
        raw_diff_turn = isinstance(cur_inc, Mapping) and (
            (bool(cur_inc.get("turn_id")) and bool(turn_id) and cur_inc.get("turn_id") != turn_id)
            or (inc_seq > 0 and turn_seq > 0 and inc_seq != turn_seq)
        )
        is_recovery_continuation = (
            turn_cause_kind == "recovery"
            or (
                isinstance(cur_inc, Mapping)
                and cur_inc.get("status") in ("open", "recovering")
                and cur_inc.get("awaiting_verify") in (
                    "turn_outcome", "continue_turn", "nudge_enter", "retype_submitted", "restart_seat", "switch_profile",
                )
            )
        )
        can_supersede_active = (
            isinstance(cur_inc, Mapping)
            and cur_inc.get("status") == "notified"
            and turn_cause_kind != "recovery"
        ) or (
            isinstance(cur_inc, Mapping)
            and cur_inc.get("status") in ("open", "recovering")
            and cur_inc.get("class") == "W2"
            and not is_recovery_continuation
            and turn_cause_kind in ("user", "self", "deliver")
        )
        need_open = (
            not isinstance(cur_inc, Mapping)
            or cur_inc.get("status") == "resolved"
            or (raw_diff_turn and can_supersede_active)
        )
        if need_open:
            act_obj = turn.get("activity") if isinstance(turn.get("activity"), Mapping) else {}
            eff_cause = turn_cause_kind
            eff_mids = [str(m) for m in (cause_obj.get("msg_ids") or []) if m]
            eff_batch = list(cause_obj["batch"]) if isinstance(cause_obj.get("batch"), list) else None
            if (
                eff_cause not in ("user", "deliver")
                and isinstance(cur_inc, Mapping)
                and cur_inc.get("status") in ("open", "recovering")
                and cur_inc.get("cause_kind") in ("user", "deliver")
            ):
                eff_cause = str(cur_inc["cause_kind"])
                if not eff_mids:
                    eff_mids = [str(m) for m in (cur_inc.get("msg_ids") or []) if m]
                if eff_batch is None and isinstance(cur_inc.get("batch"), list):
                    eff_batch = list(cur_inc["batch"])
            _open_incident(
                nxt,
                cls=stall_cls,
                turn_id=turn_id,
                turn_seq=turn_seq,
                cause_kind=eff_cause,
                msg_ids=eff_mids,
                batch=eff_batch,
                reason=str(stall_act.get("reason") or ""),
                error=str(step_ev.get("last_error") or ""),
                tool_pid=_opt_int(proc_ev.get("tool_pid")) or 0,
                tool_cmd=str(act_obj.get("summary") or proc_ev.get("cmd") or ""),
                now_ms=now_ms,
                cfg=c,
            )
        elif (
            isinstance(cur_inc, dict)
            and cur_inc.get("status") in ("open", "recovering")
            and (cur_inc.get("awaiting_verify") == "turn_outcome" or turn_cause_kind == "recovery")
            and not cur_inc.get("awaiting_action")
            and cur_inc.get("awaiting_verify") in ("turn_outcome", "")
            and ((_opt_int(cur_inc.get("next_due_ms")) or 0) == 0 or cur_inc.get("awaiting_verify") == "turn_outcome")
        ):
            if turn_id:
                cur_inc["turn_id"] = turn_id
            if turn_seq > 0:
                cur_inc["turn_seq"] = turn_seq
            if cur_inc.get("class") == "W1":
                _advance_incident(nxt, now_ms, c, force_class="W2")
            else:
                _advance_incident(nxt, now_ms, c)
        rec_act = next_recovery_action(nxt, now_ms, c)
        if rec_act is not None:
            actions.append(rec_act)
    else:
        rec_act = next_recovery_action(nxt, now_ms, c)
        if rec_act is not None:
            actions.append(rec_act)

    nxt["updated_ms"] = max(_opt_int(nxt.get("updated_ms")) or 0, now_ms)
    return sync_compat_fields(nxt), actions


def project_v1_turn(
    state: Mapping[str, Any],
    now_ms: int,
    *,
    supervised: bool = True,
) -> dict[str, Any]:
    """Project `pm-turn.json` v2 into the v1-shaped `turn` object for older UIs and Phase 0 callers (§4.8)."""
    v2 = upgrade_state_v1_to_v2(state)
    turn = v2["turn"]
    ev = turn["evidence"]
    step = ev["step"]
    pty = ev["pty"]
    bg_count = _opt_int((v2.get("bg_shells") or {}).get("count")) or 0
    queued_count = len(v2.get("outbox") or [])
    turn_seq = _opt_int(turn.get("seq")) or 0
    v2_phase = str(turn.get("phase") or "idle")
    health = str(turn.get("health") or "ok") if supervised else "unknown"

    if v2_phase == "offline":
        return {"phase": "offline", "health": health, "queued_count": queued_count}
    if v2_phase == "starting":
        return {"phase": "starting", "health": health, "turn_seq": turn_seq, "queued_count": queued_count}
    if v2_phase == "blocked":
        return {
            "phase": "blocked",
            "health": health,
            "turn_seq": turn_seq,
            "bg_shells": bg_count,
            "queued_count": queued_count,
        }
    if v2_phase == "idle":
        return {
            "phase": "idle",
            "health": health,
            "turn_seq": turn_seq,
            "bg_shells": bg_count,
            "queued_count": queued_count,
        }

    started_ms = _opt_int(turn.get("started_ms")) or now_ms
    last_activity_ms = max(
        started_ms,
        _opt_int(turn.get("last_progress_ms")) or 0,
        _opt_int(step.get("last_ms")) or 0,
        _opt_int(pty.get("changed_ms")) or 0,
    )
    elapsed_ms = max(0, now_ms - started_ms)
    idle_for_ms = max(0, now_ms - last_activity_ms)

    if not supervised or health == "unknown":
        slow = False
        stalled = False
        v1_phase = "working"
    else:
        stalled = health == "stalled"
        slow = (health == "suspect") or (health == "slow" and turn.get("health_reason") != "tool_soft_budget")
        v1_phase = "stalled" if stalled else "working"

    act = turn.get("activity") if isinstance(turn.get("activity"), Mapping) else {}
    step_count = _opt_int(step.get("count")) or 0
    activity: dict[str, Any] | None = None
    if v2_phase == "tool" and (act.get("tool") or act.get("summary")):
        activity = {
            "kind": "tool",
            "tool": str(act.get("tool") or ""),
            "summary": str(act.get("summary") or ""),
            "steps": step_count,
        }
    elif v2_phase == "recovering":
        activity = {
            "kind": "recovering",
            "tool": "",
            "summary": str(act.get("summary") or ""),
            **({"steps": step_count} if step_count > 0 else {}),
        }
    elif v2_phase in ACTIVE_TURN_PHASES:
        activity = {
            "kind": "thinking",
            "tool": "",
            "summary": "",
            **({"steps": step_count} if step_count > 0 else {}),
        }

    return {
        "phase": v1_phase,
        "health": health,
        "turn_seq": turn_seq,
        "turn_id": str(turn.get("id") or ""),
        "started_ms": started_ms,
        "last_activity_ms": last_activity_ms,
        "elapsed_ms": elapsed_ms,
        "idle_for_ms": idle_for_ms,
        "slow": slow,
        "stalled": stalled,
        "activity": activity,
        "bg_shells": bg_count,
        "queued_count": queued_count,
    }


def build_turn2_payload(
    state: Mapping[str, Any],
    now_ms: int,
    *,
    supervised: bool,
    beat_age_ms: int | None = None,
) -> dict[str, Any]:
    """Build the v2 `turn2` payload returned by `pm.py state` and `pm.py project events` (§3.3, §4.2)."""
    v2 = upgrade_state_v1_to_v2(state)
    turn = copy.deepcopy(v2["turn"])
    if not supervised:
        turn["health"] = "unknown"
        if not turn.get("health_reason"):
            turn["health_reason"] = "supervisor_stale"
    return {
        "version": 2,
        "supervised": bool(supervised),
        "beat_age_ms": beat_age_ms,
        "journal_seq": _opt_int(v2.get("journal_seq")) or 0,
        "session": copy.deepcopy(v2["session"]),
        "turn": turn,
        "last_turn": copy.deepcopy(v2.get("last_turn")),
        "incident": copy.deepcopy(v2.get("incident")),
        "bg_shells": copy.deepcopy(v2.get("bg_shells") or {"count": 0, "commands": []}),
        "queued_count": len(v2.get("outbox") or []),
        # Where each message is in the mailbox (§3.9 bubble states), and the backlog for the banner.
        "inbox": copy.deepcopy(list(v2.get("inbox") or [])),
        "undelivered": _undelivered_view(v2.get("undelivered"), now_ms),
        "server_now_ms": now_ms,
    }


def _undelivered_view(raw: Any, now_ms: int) -> dict[str, Any] | None:
    """The stored backlog (`TurnTracker.sync_mailbox_projection`) with its waiting time as of `now_ms`."""
    if not isinstance(raw, Mapping) or not (_opt_int(raw.get("count")) or 0):
        return None
    out = copy.deepcopy(dict(raw))
    oldest = _opt_int(out.get("oldest_ms")) or 0
    out["waiting_seconds"] = max(0, (now_ms - oldest) // 1000) if oldest > 0 else 0
    return out


def _redact_string(text: str, *, home_dir: str = "", repo: str = "") -> str:
    if not text:
        return text
    out = text
    for prefix, repl in ((repo, "<repo>"), (home_dir, "~")):
        clean = str(prefix or "").strip().rstrip("/\\")
        if clean and len(clean) >= 2:
            out = out.replace(clean, repl)
    out = _HOME_USER_POSIX_RE.sub(r"\1/<user>", out)
    out = _HOME_USER_WIN_RE.sub(r"\1<user>", out)
    out = _EMAIL_RE.sub("<email>", out)
    for pat, repl in _TOKEN_PATTERNS:
        out = pat.sub(repl, out)
    return out


def sanitize_journal_entries(
    entries: list[Mapping[str, Any]],
    *,
    home_dir: str = "",
    repo: str = "",
) -> list[dict[str, Any]]:
    """Redact PII, local usernames, secrets/API keys, and repo/home paths from observation journal entries
    so exported slices are safe to check in as replay test fixtures (§4.2, §5)."""
    session_map: dict[str, str] = {}
    ws_map: dict[str, str] = {}

    def _anon_session(sid: str) -> str:
        if not sid:
            return ""
        if sid not in session_map:
            session_map[sid] = f"sess_{len(session_map) + 1}"
        return session_map[sid]

    def _anon_ws(ws: str) -> str:
        if not ws:
            return ""
        if ws not in ws_map:
            ws_map[ws] = f"ws_{len(ws_map) + 1}"
        return ws_map[ws]

    def _clean(val: Any, key: str = "") -> Any:
        if isinstance(val, str):
            if key == "session_id":
                return _anon_session(val)
            if key == "workspace":
                return _anon_ws(val)
            return _redact_string(val, home_dir=home_dir, repo=repo)
        if isinstance(val, list):
            return [_clean(item, "") for item in val]
        if isinstance(val, Mapping):
            return {str(k): _clean(v, str(k)) for k, v in val.items()}
        return val

    out: list[dict[str, Any]] = []
    for row in entries:
        if isinstance(row, Mapping):
            cleaned = _clean(row)
            if isinstance(cleaned, dict):
                out.append(cleaned)
    return out


def _percentile_ms(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * pct)
    return int(ordered[max(0, min(len(ordered) - 1, idx))])


def summarize_turns(
    entries: list[Mapping[str, Any]],
    *,
    cfg: TurnConfig | None = None,
) -> dict[str, Any]:
    """Aggregate turn duration distribution (p50/p90/max, over-budget counts) and top action categories
    from observation journal entries (§3.8 O-a, D7). Falls back to replaying raw journal observations
    when no explicit `turn_summary` entries exist yet."""
    c = cfg or TurnConfig()
    summaries: list[dict[str, Any]] = []
    for row in entries:
        if isinstance(row, Mapping) and row.get("kind") == "turn_summary":
            total_ms = _opt_int(row.get("total_ms")) or _opt_int(row.get("duration_ms")) or 0
            soft_ms = _opt_int(row.get("budget_soft_ms")) or c.turn_soft_budget_ms
            hard_ms = _opt_int(row.get("budget_hard_ms")) or c.turn_hard_budget_ms
            summaries.append({
                "turn_id": str(row.get("turn_id") or row.get("id") or ""),
                "turn_seq": _opt_int(row.get("turn_seq")) or _opt_int(row.get("seq")) or 0,
                "cause": str(row.get("cause") or "self"),
                "outcome": str(row.get("outcome") or ""),
                "total_ms": total_ms,
                "generate_ms": _opt_int(row.get("generate_ms")) or 0,
                "tool_ms": _opt_int(row.get("tool_ms")) or 0,
                "steps": _opt_int(row.get("steps")) or 0,
                "longest_step": dict(row.get("longest_step") or {}) if isinstance(row.get("longest_step"), Mapping) else {},
                "action_ms": dict(row.get("action_ms") or {}) if isinstance(row.get("action_ms"), Mapping) else {},
                "over_soft": bool(row.get("over_soft")) if "over_soft" in row else (total_ms > soft_ms),
                "over_hard": bool(row.get("over_hard")) if "over_hard" in row else (total_ms > hard_ms),
                "t": _opt_int(row.get("t")) or 0,
            })

    if not summaries and entries:
        # Replay raw journal entries through `reduce()` to collect completed turns cleanly.
        st = default_state_v2(c)
        last_seen_seq = 0
        for row in entries:
            if not isinstance(row, Mapping):
                continue
            st = reduce(st, row, c)
            lt = st.get("last_turn")
            if isinstance(lt, Mapping):
                lt_seq = _opt_int(lt.get("seq")) or 0
                if lt_seq > last_seen_seq:
                    last_seen_seq = lt_seq
                    total_ms = _opt_int(lt.get("total_ms")) or _opt_int(lt.get("duration_ms")) or 0
                    split = lt.get("split") if isinstance(lt.get("split"), Mapping) else {}
                    budget = lt.get("budget") if isinstance(lt.get("budget"), Mapping) else {}
                    summaries.append({
                        "turn_id": str(lt.get("id") or ""),
                        "turn_seq": lt_seq,
                        "cause": str(lt.get("cause") or "self"),
                        "outcome": str(lt.get("outcome") or ""),
                        "total_ms": total_ms,
                        "generate_ms": _opt_int(split.get("generate_ms")) or 0,
                        "tool_ms": _opt_int(split.get("tool_ms")) or 0,
                        "steps": _opt_int(lt.get("steps")) or 0,
                        "longest_step": dict(lt.get("longest_step") or {}) if isinstance(lt.get("longest_step"), Mapping) else {},
                        "action_ms": dict(lt.get("action_ms") or {}) if isinstance(lt.get("action_ms"), Mapping) else {},
                        "over_soft": bool(budget.get("over_soft")) if "over_soft" in budget else (total_ms > c.turn_soft_budget_ms),
                        "over_hard": bool(budget.get("over_hard")) if "over_hard" in budget else (total_ms > c.turn_hard_budget_ms),
                        "t": _opt_int(lt.get("ended_ms")) or 0,
                    })

    def _stats(items: list[dict[str, Any]]) -> dict[str, int]:
        durs = [int(it["total_ms"]) for it in items]
        return {
            "count": len(items),
            "p50_ms": _percentile_ms(durs, 0.50),
            "p90_ms": _percentile_ms(durs, 0.90),
            "max_ms": max(durs, default=0),
            "total_ms": sum(durs),
            "over_soft": sum(1 for it in items if it.get("over_soft")),
            "over_hard": sum(1 for it in items if it.get("over_hard")),
        }

    user_items = [it for it in summaries if it.get("cause") == "user"]
    deliver_items = [it for it in summaries if it.get("cause") == "deliver"]
    other_items = [it for it in summaries if it.get("cause") not in ("user", "deliver")]

    action_totals: dict[str, int] = {}
    for it in summaries:
        amap = it.get("action_ms") if isinstance(it.get("action_ms"), Mapping) else {}
        if amap:
            for k, v in amap.items():
                iv = _opt_int(v) or 0
                if iv > 0:
                    action_totals[str(k)] = action_totals.get(str(k), 0) + iv
        else:
            if it.get("generate_ms"):
                action_totals["generate"] = action_totals.get("generate", 0) + int(it["generate_ms"])
            if it.get("tool_ms"):
                action_totals["tool"] = action_totals.get("tool", 0) + int(it["tool_ms"])

    grand_action_ms = sum(action_totals.values())
    top_actions = [
        {
            "category": cat,
            "total_ms": ms,
            "share": round(ms / grand_action_ms, 3) if grand_action_ms > 0 else 0.0,
        }
        for cat, ms in sorted(action_totals.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    ]
    longest_turns = sorted(summaries, key=lambda it: -int(it.get("total_ms") or 0))[:5]
    return {
        "total_turns": len(summaries),
        "user_turns": len(user_items),
        "deliver_turns": len(deliver_items),
        "other_turns": len(other_items),
        "budget": {
            "soft_ms": c.turn_soft_budget_ms,
            "hard_ms": c.turn_hard_budget_ms,
        },
        "all": _stats(summaries),
        "user": _stats(user_items),
        "deliver": _stats(deliver_items),
        "top_actions": top_actions,
        "longest_turns": longest_turns,
    }
