"""Pure zero-IO declarative `Router`, §4.2.1 reaction table, §4.2.2 routing table, §4.3 3-tier readiness,
and the wake / news rules that were `events/policy.py` (removed in Phase 3b). Layer 2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import re
from typing import Any, Mapping, Sequence

from ..caller import Caller
from ..home import project_slug
from ..ledger.task import pm_started
from ..project.project import ProjectRegistry, app_pm, in_scope
from .address import Endpoint, LogicalAddress
from .envelope import (
    P0_CONTROL,
    P1_USER,
    P2_RESUME,
    P3_DIRECT,
    P4_BATCH,
    Envelope,
)

try:
    from typing import Literal
except ImportError:  # pragma: no cover - Python 3.7 fallback
    Literal = Any  # type: ignore[misc,assignment]


ActionKind = Literal["deliver", "hold", "coalesce", "drop_duplicate", "apply_report", "mirror_only", "reject"]

WAKING = ("review", "blocked", "done", "proposed")
REPORT_WAKING = ("review", "blocked", "done")
MOVED_ON = ("merged", "released", "abandoned")

STATUS_SET = re.compile(r"^(?:[a-z_]+=[^,;]*, )*status=([a-z_]+)")
COMMIT_SET = re.compile(r"^(?:[a-z_]+=[^,;]*, )*commit=")
FIELDS_ONLY = re.compile(r"^[a-z_]+=[^,;]*(?:, [a-z_]+=[^,;]*)*$")
_BG_SHELL_MSG = re.compile(r"\bshells?\s+still\s+running\b", re.I)

DELIVER_UNKNOWN_WAIT = 15
UNDELIVERED_P1_P3_ALERT_MS = 120_000
UNDELIVERED_P4_ALERT_MS = 900_000


@dataclass(frozen=True)
class EndpointSnapshot:
    """Read-only endpoint runtime state fed into pure `Router.route()` and `evaluate_batch_readiness()`."""

    endpoint: Endpoint | None = None
    live_state: str = "live"          # live | offline | exited | finished | removed
    agent_state: str = ""             # idle | working | done | blocked | error | ""
    status_msg: str = ""
    can_report_status: bool = True
    can_interrupt: bool = True
    steers_mid_turn: bool = True
    link_state: str = "connected"     # connected | connecting | disconnected | unauthorized
    turn_phase: str = ""              # "" | idle | submitted | generating | tool | waiting_upstream | blocked | recovering | starting | offline
    last_turn_stopped: bool | None = None
    bg_work: bool = False
    blocking_dialog: bool = False
    seat_starting: bool = False
    recovery_hold: bool = False
    helper_wait_active: bool = False
    waited_ms: int = 0
    screen_quiet_ms: int = 0
    since_last_type_ms: int = 999_999
    step_quiet_ms: int = 0
    cpu_quiet_ms: int = 0


@dataclass(frozen=True)
class RoutingSnapshot:
    """Immutable read-only world snapshot evaluated by `Router.route()` and `authorize_envelope()`."""

    project: str
    now_ms: int = 0
    endpoints: Mapping[str, Endpoint] = field(default_factory=dict)
    endpoint_states: Mapping[str, EndpointSnapshot] = field(default_factory=dict)
    tasks: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    active_coalesce_keys: Mapping[str, str] = field(default_factory=dict)  # coalesce_key -> existing env_id
    known_idempotency_keys: frozenset[str] = field(default_factory=frozenset)
    active_turn_interrupts: frozenset[str] = field(default_factory=frozenset)
    pm_panes: frozenset[str] = field(default_factory=frozenset)
    unknown_wait_ms: int = DELIVER_UNKNOWN_WAIT * 1000
    screen_quiet_ms: int = 10_000
    type_cooldown_ms: int = 15_000
    esc_idle_ms: int = 30_000


@dataclass(frozen=True)
class RouteDecision:
    """Pure routing output returned by `Router.route()`."""

    action: str
    endpoint: Endpoint | None
    priority: int
    wake: bool
    if_idle_only: bool
    hold_reason: str = ""
    settle_until_ms: int = 0
    coalesce_into_env_id: str = ""
    supersede_task_id: str = ""
    targets: tuple[str, ...] = ()
    rule_id: str = ""


@dataclass(frozen=True)
class ReactionPlanItem:
    """One deterministic entry in the §4.2.1 ordered ledger reaction table."""

    row: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)


def evaluate_batch_readiness(
    ep_snap: EndpointSnapshot | None,
    *,
    unknown_wait_ms: int = 15_000,
    screen_quiet_ms: int = 10_000,
    type_cooldown_ms: int = 15_000,
    esc_idle_ms: int = 30_000,
) -> tuple[bool, bool, str]:
    """§4.3 3-tier readiness evaluation for `if_idle_only=True` envelopes.

    Returns `(ready, pass_if_idle_flag, hold_reason)`:
    - Tier 1 (`can_report_status` with non-empty `agent_state`): `idle` -> `(True, True)`, `done` -> `(True, False)`,
      `working` + `last_turn_stopped` + bg_work -> `(True, False)`.
    - Tier 2 (`can_report_status == False` or empty `agent_state`, with hook/transcript evidence):
      `last_turn_stopped is True` -> `(True, False)`; dangling turn after Esc where screen/step/CPU quiet >= 30s -> `(True, False)`.
    - Tier 3 (black-box endpoint with neither status nor turn evidence):
      screen quiet >= 10s AND cooldown >= 15s (or legacy waited >= unknown_wait_ms) -> `(True, False)`.
    """
    if ep_snap is None:
        return False, False, "no_endpoint"
    if ep_snap.link_state != "connected":
        return False, False, "machine_disconnected"
    if ep_snap.seat_starting or ep_snap.turn_phase == "starting":
        return False, False, "starting"
    if ep_snap.live_state != "live":
        return False, False, f"endpoint_{ep_snap.live_state or 'offline'}"
    if ep_snap.blocking_dialog or ep_snap.agent_state == "blocked" or ep_snap.turn_phase == "blocked":
        return False, False, "blocked_prompt"
    if ep_snap.recovery_hold:
        return False, False, "recovery_backoff"
    if ep_snap.agent_state == "error":
        if ep_snap.turn_phase == "recovering":
            return True, False, ""
        return False, False, "blocked_prompt"

    state = str(ep_snap.agent_state or "").strip().lower()
    if ep_snap.can_report_status and state:
        if state == "idle":
            return True, True, ""
        if state == "done":
            return True, False, ""
        if state == "working" and bool(ep_snap.last_turn_stopped) and (
            bool(_BG_SHELL_MSG.search(ep_snap.status_msg)) or bool(ep_snap.bg_work)
        ):
            return True, False, ""
        return False, False, "pm_working"

    # Tier 2: no terminal status word, but hook/transcript turn evidence exists.
    if ep_snap.last_turn_stopped is True or (ep_snap.last_turn_stopped is None and ep_snap.turn_phase == "idle"):
        return True, False, ""
    if ep_snap.last_turn_stopped is False:
        # Esc without Stop fallback: if screen + step + CPU all silent >= 30s, close dangling turn & release.
        if (
            ep_snap.screen_quiet_ms >= esc_idle_ms
            and ep_snap.step_quiet_ms >= esc_idle_ms
            and ep_snap.cpu_quiet_ms >= esc_idle_ms
        ):
            return True, False, ""
        return False, False, "pm_working"

    # Tier 3: black-box endpoint (no status word, no hook/transcript turn evidence).
    if screen_quiet_ms > 0 and ep_snap.screen_quiet_ms >= screen_quiet_ms and ep_snap.since_last_type_ms >= type_cooldown_ms:
        return True, False, ""
    if ep_snap.waited_ms >= unknown_wait_ms and ep_snap.since_last_type_ms >= type_cooldown_ms:
        return True, False, ""
    return False, False, "blackbox_cooldown"


def plan_task_reactions(
    *,
    task: Mapping[str, Any],
    changes: Sequence[str],
    entry_fields: Mapping[str, Any],
    will_auto_review: bool = False,
    skip_reason: str = "",
    auto_review_failed: bool = False,
    resolved_sha: str = "",
    commit: str = "",
    note: str = "",
    is_pm_caller: bool = False,
    send_back: bool = False,
    keep: bool = False,
    self_pane: str = "",
    has_deps: bool = False,
    moved_status: str = "",
    old_parent: str = "",
    idem_key: str = "",
) -> list[ReactionPlanItem]:
    """Declarative §4.2.1 ordered reaction table (Rows 1-10) with E-04/E-05 & duplicate-commit handling."""
    plan: list[ReactionPlanItem] = []
    tid = str(task.get("id") or "")
    status = str(task.get("status") or "")
    wake = bool(entry_fields.get("wake"))
    source = str(entry_fields.get("source") or "")
    if not is_pm_caller and status == "merged" and source in ("worker", "helper"):
        wake = True
    if skip_reason == "duplicate running commit":
        wake = False

    if wake and not will_auto_review:
        plan.append(ReactionPlanItem(
            row="1",
            action="emit_task_updated",
            params={"task_id": tid, "idempotency_key": f"react:wake:{idem_key or tid}", "coalesce_key": f"task:{tid}"},
        ))
    if status in ("review", "blocked", "done", "merged", "released") and (
        any(c.startswith("status=") for c in changes) or bool(note) or bool(commit)
    ):
        plan.append(ReactionPlanItem(row="2", action="collect_research", params={"task_id": tid}))
    if will_auto_review:
        plan.append(ReactionPlanItem(
            row="3",
            action="run_auto_review",
            params={"task_id": tid, "commit": commit, "resolved_sha": resolved_sha, "note": note},
        ))
        if auto_review_failed:
            plan.append(ReactionPlanItem(
                row="3_fallback",
                action="emit_task_updated",
                params={"task_id": tid, "wake": True, "idempotency_key": f"react:wake_fail:{idem_key or tid}"},
            ))
        return plan

    if send_back:
        plan.append(ReactionPlanItem(row="4", action="send_back", params={"task_id": tid, "note": note}))

    auto = "status=merged" in changes and bool(task.get("dispatched")) and not keep
    landed_done = (
        "status=done" in changes and bool(task.get("landed")) and bool(task.get("dispatched"))
        and not task.get("retired") and not keep
    )
    if "status=merged" in changes and not auto:
        plan.append(ReactionPlanItem(row="5a", action="retire_review", params={"task_id": tid}))
    if auto or landed_done:
        plan.append(ReactionPlanItem(
            row="5b",
            action="retire_workspace",
            params={"task_id": tid, "self_close": bool(self_pane and task.get("pane") == self_pane)},
        ))
    elif any(c == f"status={s}" for c in changes for s in ("done", "merged", "released", "abandoned")) and not keep:
        plan.append(ReactionPlanItem(row="6", action="close_worker_and_prune", params={"task_id": tid}))
    elif "status=review" in changes:
        plan.append(ReactionPlanItem(row="7", action="close_reported_worker", params={"task_id": tid}))

    if task.get("review_of") and "status=done" in changes:
        plan.append(ReactionPlanItem(row="8", action="sync_review_done", params={"task_id": tid, "review_of": task["review_of"]}))
    if has_deps and status == "proposed":
        plan.append(ReactionPlanItem(row="9a", action="check_initial_deps", params={"task_id": tid}))
    if moved_status in ("merged", "released", "done", "abandoned"):
        plan.append(ReactionPlanItem(row="9b", action="reconcile_dependents", params={"task_id": tid}))
    parent_id = str(task.get("parent") or "")
    if parent_id or old_parent:
        plan.append(ReactionPlanItem(row="10", action="rollup_ancestors", params={"task_id": tid, "parent": parent_id, "old_parent": old_parent}))
    return plan


def _moved_on_superseded(env: Envelope, snapshot: RoutingSnapshot) -> bool:
    """§4.2.2 R-BATCH-PM: check if an event envelope is obsolete against current disk task status."""
    body = env.body if isinstance(env.body, Mapping) else {}
    task_id = str(body.get("task_id") or body.get("task") or "")
    if not task_id:
        return False
    task_rec = snapshot.tasks.get(task_id)
    if not isinstance(task_rec, Mapping):
        return False
    st = str(task_rec.get("status") or "")
    # Delegated merge completion (`status=merged` from worker/helper) is itself the news to deliver.
    if str(body.get("status") or "") == "merged" and env.sender.role in ("worker", "helper"):
        return False
    if env.kind == "event.deps_ready" or body.get("source") == "deps":
        return st != "proposed"
    if env.kind == "event.rollup" or body.get("source") == "rollup":
        return st == "done" or st in MOVED_ON
    return st in MOVED_ON


class Router:
    """Pure zero-IO declarative router implementing §4.2.2 rules top-down."""

    def route(self, env: Envelope, snapshot: RoutingSnapshot) -> RouteDecision:
        rec = env.recipient
        rec_uri = rec.to_uri()
        ep = snapshot.endpoints.get(rec_uri)
        ep_snap = snapshot.endpoint_states.get(rec_uri)
        if ep is None and ep_snap is not None:
            ep = ep_snap.endpoint

        # R-REPORT: report.* -> ledger://<slug>
        if env.kind.startswith("report.") or rec.kind == "ledger":
            return RouteDecision(
                action="apply_report",
                endpoint=ep,
                priority=P0_CONTROL,
                wake=False,
                if_idle_only=False,
                rule_id="R-REPORT",
            )

        # R-REPORT-REJECTED: offline report rejection feedback -> worker or PM + UI
        if env.kind == "event.report_rejected":
            body = env.body if isinstance(env.body, Mapping) else {}
            tid = str(body.get("task_id") or "")
            authz_denied = bool(body.get("authz_denied"))
            wk_uri = f"worker://{tid}" if tid else ""
            wk_snap = snapshot.endpoint_states.get(wk_uri) if wk_uri else None
            wk_ep = snapshot.endpoints.get(wk_uri) if wk_uri else None
            req_epoch = int(body.get("sender_epoch") or 0)
            wk_alive = (
                not authz_denied
                and wk_snap is not None
                and wk_snap.live_state == "live"
                and (wk_ep is None or req_epoch <= 0 or wk_ep.epoch == req_epoch)
            )
            if wk_alive and rec.kind == "worker":
                return RouteDecision(
                    action="deliver",
                    endpoint=wk_ep or ep,
                    priority=P3_DIRECT,
                    wake=True,
                    if_idle_only=False,
                    rule_id="R-REPORT-REJECTED",
                )
            pm_ep = snapshot.endpoints.get(f"pm://{env.project}")
            return RouteDecision(
                action="deliver",
                endpoint=pm_ep or ep,
                priority=P4_BATCH,
                wake=True,
                if_idle_only=False,
                targets=(f"ui://{env.project}", f"pm://{env.project}"),
                rule_id="R-REPORT-REJECTED",
            )

        # R-UNDELIVERED-ALERT: alert.undelivered -> human channels only (ui + hub + discord)
        if env.kind == "alert.undelivered":
            return RouteDecision(
                action="mirror_only",
                endpoint=None,
                priority=P1_USER,
                wake=True,
                if_idle_only=False,
                targets=(f"ui://{env.project}", "hub://local", f"discord://{env.project}"),
                rule_id="R-UNDELIVERED-ALERT",
            )

        # R-CTRL: ctrl.interrupt / ctrl.cancel
        if env.kind.startswith("ctrl."):
            turn_id = str((env.cause or {}).get("turn_id") or "")
            if turn_id and turn_id in snapshot.active_turn_interrupts:
                return RouteDecision(
                    action="drop_duplicate",
                    endpoint=ep,
                    priority=P0_CONTROL,
                    wake=False,
                    if_idle_only=False,
                    rule_id="R-CTRL",
                )
            if ep_snap is not None and not ep_snap.can_interrupt and env.kind == "ctrl.interrupt":
                return RouteDecision(
                    action="reject",
                    endpoint=ep,
                    priority=P0_CONTROL,
                    wake=False,
                    if_idle_only=False,
                    hold_reason="unsupported",
                    rule_id="R-CTRL",
                )
            return RouteDecision(
                action="deliver",
                endpoint=ep,
                priority=P0_CONTROL,
                wake=True,
                if_idle_only=False,
                rule_id="R-CTRL",
            )

        # Global idempotency duplicate suppression
        if env.idempotency_key and env.idempotency_key in snapshot.known_idempotency_keys:
            return RouteDecision(
                action="drop_duplicate",
                endpoint=ep,
                priority=env.priority,
                wake=False,
                if_idle_only=False,
                rule_id="R-DEDUPE",
            )

        # R-USER-PM: chat.user -> pm://<slug>
        if env.kind == "chat.user" and rec.kind == "pm":
            if ep_snap is not None:
                if ep_snap.link_state != "connected":
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P1_USER, wake=True, if_idle_only=False,
                        hold_reason="machine_disconnected", rule_id="R-USER-PM",
                    )
                if ep_snap.seat_starting or ep_snap.turn_phase == "starting":
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P1_USER, wake=True, if_idle_only=False,
                        hold_reason="starting", rule_id="R-USER-PM",
                    )
                if ep_snap.blocking_dialog or ep_snap.agent_state in ("blocked", "error") or ep_snap.turn_phase == "blocked":
                    reason = "pm is error" if ep_snap.agent_state == "error" else "blocked_prompt"
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P1_USER, wake=True, if_idle_only=False,
                        hold_reason=reason, rule_id="R-USER-PM",
                    )
                if not ep_snap.steers_mid_turn and ep_snap.turn_phase in ("generating", "tool", "waiting_upstream"):
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P1_USER, wake=True, if_idle_only=False,
                        hold_reason="mid_turn_buffered", rule_id="R-USER-PM",
                    )
            return RouteDecision(
                action="deliver", endpoint=ep, priority=P1_USER, wake=True, if_idle_only=False,
                rule_id="R-USER-PM",
            )

        # R-USER-WK: chat.user -> worker://<tid> or helper://...
        if env.kind == "chat.user" and rec.kind in ("worker", "reviewer", "helper"):
            if ep_snap is not None:
                if ep_snap.link_state != "connected":
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P1_USER, wake=True, if_idle_only=False,
                        hold_reason="machine_disconnected", rule_id="R-USER-WK",
                    )
                if ep_snap.blocking_dialog or ep_snap.agent_state in ("blocked", "error") or ep_snap.turn_phase == "blocked":
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P1_USER, wake=True, if_idle_only=False,
                        hold_reason="blocked_prompt", rule_id="R-USER-WK",
                    )
            return RouteDecision(
                action="deliver", endpoint=ep, priority=P1_USER, wake=True, if_idle_only=False,
                rule_id="R-USER-WK",
            )

        # R-RESUME: cmd.resume_turn
        if env.kind == "cmd.resume_turn":
            if ep_snap is not None:
                if ep_snap.link_state != "connected":
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P2_RESUME, wake=True, if_idle_only=False,
                        hold_reason="machine_disconnected", rule_id="R-RESUME",
                    )
                if ep_snap.seat_starting or ep_snap.turn_phase == "starting":
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P2_RESUME, wake=True, if_idle_only=False,
                        hold_reason="starting", rule_id="R-RESUME",
                    )
                if ep_snap.blocking_dialog or ep_snap.agent_state == "blocked" or ep_snap.turn_phase == "blocked":
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P2_RESUME, wake=True, if_idle_only=False,
                        hold_reason="blocked_prompt", rule_id="R-RESUME",
                    )
                state = str(ep_snap.agent_state or "").strip().lower()
                working_active = (
                    ep_snap.turn_phase in ("generating", "tool", "waiting_upstream")
                    or (
                        ep_snap.can_report_status
                        and state == "working"
                        and ep_snap.turn_phase != "recovering"
                        and not (
                            bool(ep_snap.last_turn_stopped)
                            and (bool(_BG_SHELL_MSG.search(ep_snap.status_msg)) or bool(ep_snap.bg_work))
                        )
                    )
                )
                if working_active:
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P2_RESUME, wake=True, if_idle_only=True,
                        hold_reason="waiting_turn_leave_working", rule_id="R-RESUME",
                    )
                want_if_idle = bool(ep_snap.can_report_status and state == "idle")
                return RouteDecision(
                    action="deliver", endpoint=ep, priority=P2_RESUME, wake=True, if_idle_only=want_if_idle,
                    rule_id="R-RESUME",
                )
            return RouteDecision(
                action="deliver", endpoint=ep, priority=P2_RESUME, wake=True, if_idle_only=True,
                rule_id="R-RESUME",
            )

        # R-DIRECT: cmd.brief / cmd.send / cmd.approve_land
        if env.kind in ("cmd.brief", "cmd.send", "cmd.approve_land"):
            body = env.body if isinstance(env.body, Mapping) else {}
            tid = str(body.get("task_id") or "")
            supersede = tid if (env.sender.role == "pm" and tid) else ""
            if ep_snap is not None and ep_snap.link_state != "connected":
                return RouteDecision(
                    action="hold", endpoint=ep, priority=P3_DIRECT, wake=True, if_idle_only=False,
                    hold_reason="machine_disconnected", supersede_task_id=supersede, rule_id="R-DIRECT",
                )
            return RouteDecision(
                action="deliver", endpoint=ep, priority=P3_DIRECT, wake=True, if_idle_only=False,
                supersede_task_id=supersede, rule_id="R-DIRECT",
            )

        # R-SELF-SUPPRESS: event.* where sender and recipient belong to same logical principal (e.g. PM's own edit)
        if env.kind.startswith("event.") and rec.kind == "pm" and env.sender.role == "pm" and (
            not env.sender.project or env.sender.project == rec.target
        ):
            return RouteDecision(
                action="mirror_only", endpoint=None, priority=P4_BATCH, wake=False, if_idle_only=False,
                targets=(f"ui://{env.project}",), rule_id="R-SELF-SUPPRESS",
            )

        # R-QUIET: quiet events / pure logs / unready proposed
        body = env.body if isinstance(env.body, Mapping) else {}
        if env.kind.startswith("event.") and (
            body.get("quiet") is True or body.get("wake") is False
        ):
            return RouteDecision(
                action="mirror_only", endpoint=None, priority=P4_BATCH, wake=False, if_idle_only=False,
                targets=(f"ui://{env.project}",), rule_id="R-QUIET",
            )

        # R-NOTIFY-WK: event.helper_done -> worker://<tid>
        if env.kind == "event.helper_done" and rec.kind == "worker":
            tid = rec.target
            task_rec = snapshot.tasks.get(tid) if tid else None
            st = str(task_rec.get("status") or "") if isinstance(task_rec, Mapping) else ""
            if (ep_snap is not None and ep_snap.helper_wait_active) or (st and st != "in_progress"):
                return RouteDecision(
                    action="mirror_only", endpoint=ep, priority=P4_BATCH, wake=False, if_idle_only=False,
                    targets=(f"ui://{env.project}",), rule_id="R-NOTIFY-WK",
                )
            return RouteDecision(
                action="deliver", endpoint=ep, priority=P4_BATCH, wake=True, if_idle_only=False,
                rule_id="R-NOTIFY-WK",
            )

        # R-BATCH-PM: event.* -> pm://<slug>
        if env.kind.startswith("event.") and rec.kind == "pm":
            if _moved_on_superseded(env, snapshot):
                return RouteDecision(
                    action="drop_duplicate", endpoint=ep, priority=P4_BATCH, wake=False, if_idle_only=True,
                    hold_reason="moved_on", rule_id="R-BATCH-PM",
                )
            if env.coalesce_key and env.coalesce_key in snapshot.active_coalesce_keys:
                existing_id = snapshot.active_coalesce_keys[env.coalesce_key]
                if existing_id != env.env_id:
                    return RouteDecision(
                        action="coalesce", endpoint=ep, priority=P4_BATCH, wake=True, if_idle_only=True,
                        coalesce_into_env_id=existing_id, rule_id="R-BATCH-PM",
                    )
            if ep_snap is not None:
                ready, if_idle, hold_reason = evaluate_batch_readiness(
                    ep_snap,
                    unknown_wait_ms=snapshot.unknown_wait_ms,
                    screen_quiet_ms=snapshot.screen_quiet_ms,
                    type_cooldown_ms=snapshot.type_cooldown_ms,
                    esc_idle_ms=snapshot.esc_idle_ms,
                )
                if not ready:
                    return RouteDecision(
                        action="hold", endpoint=ep, priority=P4_BATCH, wake=True, if_idle_only=True,
                        hold_reason=hold_reason, rule_id="R-BATCH-PM",
                    )
                return RouteDecision(
                    action="deliver", endpoint=ep, priority=P4_BATCH, wake=True, if_idle_only=if_idle,
                    rule_id="R-BATCH-PM",
                )
            return RouteDecision(
                action="deliver", endpoint=ep, priority=P4_BATCH, wake=True, if_idle_only=True,
                rule_id="R-BATCH-PM",
            )

        # Virtual UI / Discord endpoints
        if rec.kind in ("ui", "discord"):
            return RouteDecision(
                action="mirror_only", endpoint=ep, priority=env.priority, wake=False, if_idle_only=False,
                targets=(rec_uri,), rule_id="R-MIRROR",
            )

        return RouteDecision(
            action="deliver", endpoint=ep, priority=env.priority, wake=True, if_idle_only=False,
            rule_id="R-DEFAULT",
        )


# ── Wake / news rules (once `events/policy.py`) ─────────────────────────────────────────────────────────────────


def manager_ready_for_batch(
    term_info: Any,
    last_turn_stopped: bool | None,
    *,
    bg_work: bool = False,
    waited: float = 0.0,
    unknown_wait: float = DELIVER_UNKNOWN_WAIT,
    blocking_dialog: bool = False,
    screen_quiet_s: float | None = None,
    since_last_type_s: float | None = None,
) -> tuple[bool, bool]:
    """Compatibility wrapper mapping `term_info` into `evaluate_batch_readiness()`."""
    if term_info is None:
        return False, False
    if hasattr(term_info, "agent_state") and not isinstance(term_info, Mapping):
        state = str(getattr(term_info, "agent_state", "") or "")
        msg = str(getattr(term_info, "status_msg", "") or "")
        raw = getattr(term_info, "raw", None)
        reported = bool(state) and not (isinstance(raw, Mapping) and raw.get("reported") is False)
    elif isinstance(term_info, Mapping):
        status = term_info.get("status") if isinstance(term_info.get("status"), Mapping) else {}
        state = str(status.get("state") or "")
        msg = str(status.get("msg") or status.get("message") or "")
        reported = bool(state) and term_info.get("reported") is not False
    else:
        return False, False

    ep_snap = EndpointSnapshot(
        live_state="live",
        agent_state=state,
        status_msg=msg,
        can_report_status=reported,
        turn_phase="idle" if last_turn_stopped is True else ("generating" if last_turn_stopped is False else ""),
        last_turn_stopped=last_turn_stopped,
        bg_work=bool(bg_work),
        blocking_dialog=bool(blocking_dialog),
        waited_ms=int(float(waited) * 1000),
        screen_quiet_ms=int(float(screen_quiet_s) * 1000) if screen_quiet_s is not None else 0,
        since_last_type_ms=int(float(since_last_type_s) * 1000) if since_last_type_s is not None else 999_999,
    )
    ready, if_idle, _ = evaluate_batch_readiness(ep_snap, unknown_wait_ms=int(float(unknown_wait) * 1000))
    return ready, if_idle


def wake_fields_for(
    task: Mapping[str, Any],
    status: str,
    reported: bool,
    caller: Any,
    has_app_pm: bool,
) -> dict[str, Any]:
    """Apply `wake_rule` and attach explicit `wake` (True or False) whenever a desktop-app PM exists (`has_app_pm`)."""
    fields = wake_rule(task, status, reported, caller)
    should_wake = bool(fields.pop("wake", False))
    if fields and has_app_pm:
        fields["wake"] = should_wake
    return fields


def wake_fields(task: Mapping[str, Any], status: str, reported: bool = False, *, ctx: Any = None) -> dict[str, Any]:
    caller = ctx.caller if ctx is not None else Caller.current()
    has_app_pm = bool(ProjectRegistry(ctx).app_pm(task.get("repo")) if ctx is not None else app_pm(task.get("repo")))
    return wake_fields_for(task, status, reported, caller, has_app_pm)


def wake_rule(task: Mapping[str, Any], status: str, reported: bool, caller: Any) -> dict[str, Any]:
    """Pure wake attribution rule (including E-04/E-05 fix: delegated `status='merged'` by worker/helper wakes PM)."""
    repo = task.get("repo")
    if not repo:
        return {}
    if caller.pane and caller.manages(repo):
        return {"source": "pm"}
    worker = bool(caller.pane) and task.get("pane") == caller.pane and pm_started(task)
    mine = None
    if not worker and caller.pane:
        mine = caller.own_task
        if mine and pm_started(mine):
            mine_repo = mine.get("repo")
            worker = (not mine_repo) or in_scope(mine_repo, repo) or in_scope(repo, mine_repo)
    is_helper = False
    if not worker and caller.pane:
        helper = getattr(caller, "helper", None)
        if helper:
            hproj = helper.get("project") or ""
            is_helper = (not hproj) or hproj == project_slug(repo)
    if worker:
        source = "worker"
    elif is_helper:
        source = "helper"
    else:
        source = "session"
    fields: dict[str, Any] = {"source": source}
    if worker and mine and mine.get("id") and mine["id"] != task.get("id"):
        fields["from_task"] = mine["id"]
    delegated_merge = status == "merged" and (worker or is_helper)
    if status in WAKING or delegated_merge or ((worker or is_helper) and reported and task.get("status") in REPORT_WAKING):
        fields["wake"] = True
    return fields


def is_news(e: Mapping[str, Any], pms: set[str] | frozenset[str], task_of: Any) -> bool:
    """Whether a log event is news for the PM (preserving backward-compat for historical log entries)."""
    if e.get("wake") is False:
        return False
    if e.get("wake") is True:
        return True
    if e.get("type") != "thread":
        return False
    if e.get("source") == "pm" or e.get("by") in pms:
        return False
    text = str(e.get("text") or "")
    moved = STATUS_SET.match(text)
    if e.get("status") == "merged":
        return bool(moved and moved.group(1) == "merged" and e.get("source") in ("worker", "helper"))
    if e.get("status") not in WAKING:
        return False
    if moved and moved.group(1) == e.get("status"):
        return True
    task = task_of(e.get("task"))
    log = [x for x in task.get("log") or [] if isinstance(x, dict)]
    if log and log[0].get("text") == text and near(task.get("created"), e.get("at")):
        return True
    if e.get("status") not in REPORT_WAKING:
        return False
    if COMMIT_SET.match(text):
        return e.get("source") in ("worker", "helper", None)
    return e.get("source") in ("worker", "helper") and bool(text.strip()) and not FIELDS_ONLY.match(text)


def near(one: Any, other: Any, seconds: int = 90) -> bool:
    try:
        when = [datetime.datetime.strptime(str(t)[:16], "%Y-%m-%d %H:%M") for t in (one, other)]
    except ValueError:
        return False
    return abs((when[0] - when[1]).total_seconds()) <= seconds


def pending_items(
    events: Sequence[tuple[int, dict[str, Any]]],
    pms: set[str] | frozenset[str],
    tasks: Mapping[str, dict[str, Any]],
    end: int,
    now: datetime.datetime | None = None,
    settle: float = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Filter, PM-supersede, dedupe, and `moved_on`-prune events into batch items (E-08)."""
    items: list[dict[str, Any]] = []
    latest: dict[Any, dict[str, Any]] = {}

    def task_of(task: Any) -> dict[str, Any]:
        return tasks.get(task) or {} if task else {}

    young = (now - datetime.timedelta(seconds=settle)).strftime("%Y-%m-%d %H:%M:%S") if settle and now else None
    soon = (now + datetime.timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S") if now else None
    for at, e in events:
        if young and young <= str(e.get("at") or "") <= soon:
            end = at
            break
        task = e.get("task") if e.get("type") in ("thread", "stall") else None
        if task and e.get("type") == "thread" and e.get("by") in pms and not (
            e.get("wake") is True and e.get("source") == "harness"
        ):
            old = latest.get(task)
            if old and e.get("status") != old["event"].get("status"):
                items.remove(latest.pop(task))
            continue
        if not is_news(e, pms, task_of):
            continue
        item: dict[str, Any] = {"event": e, "earlier": 0}
        if task:
            dedup_key: Any = task
        elif e.get("type") == "event" and e.get("source") in ("deps", "rollup") and e.get("task"):
            dedup_key = (e.get("source"), e.get("task"))
        else:
            dedup_key = None
        if dedup_key:
            old = latest.pop(dedup_key, None)
            if old:
                items.remove(old)
                item["earlier"] = old["earlier"] + 1
            latest[dedup_key] = item
        items.append(item)

    def moved_on(item: Mapping[str, Any]) -> bool:
        e = item["event"]
        task_id = e.get("task")
        if not task_id:
            return False
        if e.get("status") == "merged" and (
            e.get("wake") is True or (e.get("source") in ("worker", "helper") and e.get("by") not in pms)
        ):
            return False
        st = task_of(task_id).get("status")
        if e.get("type") == "event" and e.get("source") == "deps":
            return st != "proposed"
        if e.get("type") == "event" and e.get("source") == "rollup":
            return st == "done" or st in MOVED_ON
        return st in MOVED_ON

    return end, [i for i in items if not moved_on(i)]
