"""Pure zero-IO role-based authorization (`authorize_envelope`) over explicit `Principal` (§8.2). Layer 2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .envelope import Envelope
from .principal import Principal

if TYPE_CHECKING:
    from .router import RoutingSnapshot


@dataclass(frozen=True)
class AuthzDecision:
    """Result of `authorize_envelope`: pure permission decision with explicit reason code."""

    allowed: bool
    reason: str = ""
    code: str = ""


def _deny(reason: str, code: str = "authz_denied") -> AuthzDecision:
    return AuthzDecision(allowed=False, reason=reason, code=code)


def _allow() -> AuthzDecision:
    return AuthzDecision(allowed=True, reason="", code="")


def _memory_type(envelope: Envelope) -> str:
    """The memory type a `report.memory_write` asks for (`type`; `kind` in envelopes written before it was named so);
    none given: a worker's note is a pitfall."""
    body = envelope.body if isinstance(envelope.body, dict) else {}
    return str(body.get("type") or body.get("kind") or "pitfall")


def _worker_may_report_on(principal: Principal, tid: str, snapshot: RoutingSnapshot | None) -> bool:
    """A worker reports on its own task, and on a task of its project that no agent was started for (one the PM
    registered to track this work: the report reaches the PM as `from_task`); never on another worker's or a
    reviewer's task."""
    if not principal.task_id or not tid or tid == principal.task_id:
        return True
    rec = snapshot.tasks.get(tid) if snapshot is not None else None
    if not isinstance(rec, dict):
        return False
    return not (rec.get("dispatched") or rec.get("review_of"))


def authorize_envelope(
    principal: Principal,
    envelope: Envelope,
    snapshot: RoutingSnapshot | None = None,
) -> AuthzDecision:
    """Validate whether `principal` is authorized to emit `envelope` against `snapshot` (§8.2)."""
    role = principal.role
    kind = envelope.kind
    rec = envelope.recipient

    if role == "user":
        return _allow()

    if role == "discord":
        if kind == "chat.user" and rec.kind == "pm" and (not principal.project or rec.target == principal.project):
            return _allow()
        return _deny("discord bridge may only send chat.user to its bound pm://<slug>")

    if role == "supervisor":
        allowed_prefixes = ("cmd.resume_turn", "ctrl.", "event.", "alert.")
        if any(kind == p or kind.startswith(p) for p in allowed_prefixes):
            return _allow()
        return _deny(f"supervisor cannot send envelope kind {kind!r}")

    if role == "hub":
        if kind in ("chat.user", "event.notify", "alert.undelivered") and rec.kind in ("pm", "ui", "hub"):
            return _allow()
        return _deny(f"hub cannot send envelope kind {kind!r} to {rec.kind}")

    if role == "pm":
        if principal.project and envelope.project and envelope.project != principal.project:
            return _deny(f"pm:{principal.project} cannot act on project {envelope.project!r}")
        if kind == "cmd.approve_land" and snapshot is not None:
            pm_ep = snapshot.endpoints.get(f"pm://{principal.project}")
            if pm_ep is not None and principal.epoch < pm_ep.epoch:
                return _deny(
                    f"retired PM epoch {principal.epoch} < current {pm_ep.epoch} cannot approve land",
                    code="stale_epoch",
                )
        if kind in ("cmd.brief", "cmd.send", "cmd.approve_land", "ctrl.interrupt", "ctrl.cancel", "chat.user"):
            return _allow()
        if kind.startswith("report.") or kind.startswith("event."):
            return _allow()
        return _deny(f"pm cannot send envelope kind {kind!r}")

    if role == "worker":
        if kind.startswith("cmd.") or kind == "chat.user":
            return _deny(f"worker cannot issue {kind!r}")
        if kind == "report.task_update":
            tid = str(envelope.body.get("task_id") or "")
            if not _worker_may_report_on(principal, tid, snapshot):
                return _deny(f"worker {principal.task_id} cannot modify task {tid}")
            status = str(envelope.body.get("status") or "")
            if status in ("merged", "done") and (not tid or tid == principal.task_id):
                # Only once the PM approved the merge with this worker as its executor (or it has landed): then
                # `merged`, and `done` after the post-merge steps the approval handed it.
                task_rec = snapshot.tasks.get(tid) if snapshot is not None else None
                land_approved = task_rec.get("land_approved") if isinstance(task_rec, dict) else None
                allowed_by_land = bool(
                    (isinstance(land_approved, dict) and land_approved.get("executor", "worker") == "worker")
                    or (isinstance(task_rec, dict) and task_rec.get("landed"))
                )
                if not allowed_by_land:
                    return _deny(f"worker cannot set status={status} without matching land_approved")
            return _allow()
        if kind == "report.task_log":
            tid = str(envelope.body.get("task_id") or "")
            if not _worker_may_report_on(principal, tid, snapshot):
                return _deny(f"worker {principal.task_id} cannot log on task {tid}")
            return _allow()
        if kind == "report.memory_write":
            mtype = _memory_type(envelope)
            if mtype in ("decision", "user", "feedback"):
                return _deny(f"worker cannot write memory type {mtype!r}")
            return _allow()
        if kind in ("report.helper_done", "report.helper_started", "event.helper_done", "event.task_updated"):
            return _allow()
        return _deny(f"worker cannot send envelope kind {kind!r}")

    if role == "reviewer":
        if kind == "report.task_update":
            tid = str(envelope.body.get("task_id") or "")
            if principal.task_id and tid and tid != principal.task_id:
                return _deny(f"reviewer {principal.task_id} cannot update task {tid}")
            status = str(envelope.body.get("status") or "")
            if status and status not in ("done", "blocked", "in_progress"):
                return _deny(f"reviewer cannot set status={status!r}")
            return _allow()
        if kind == "report.task_log":
            tid = str(envelope.body.get("task_id") or "")
            if principal.task_id and tid and tid != principal.task_id:
                return _deny(f"reviewer {principal.task_id} cannot log on task {tid}")
            return _allow()
        if kind == "report.memory_write":
            mtype = _memory_type(envelope)
            if mtype not in ("pitfall", "reference", "project"):
                return _deny(f"reviewer cannot write memory type {mtype!r}")
            return _allow()
        if kind in ("report.helper_done", "report.helper_started", "event.helper_done"):
            return _allow()  # a review thread's own read-only helpers, as a worker's
        return _deny(f"reviewer cannot send envelope kind {kind!r}")

    if role == "helper":
        if kind in ("report.helper_done", "event.helper_done"):
            hname = str(envelope.body.get("name") or "")
            if principal.helper_name and hname and hname != principal.helper_name:
                return _deny(f"helper {principal.helper_name} cannot mark helper {hname} done")
            return _allow()
        if principal.helper_mode == "exec" and kind in ("report.task_update", "report.task_log"):
            tid = str(envelope.body.get("task_id") or "")
            if not principal.for_task or tid != principal.for_task:
                return _deny(f"exec helper {principal.helper_name} is only scoped to {principal.for_task!r}, got {tid!r}")
            if kind == "report.task_update" and snapshot is not None:
                # The merge the PM approved to this helper, and once it landed (land drops `land_approved`), the
                # post-merge steps it was handed: `--step-done`, then `--status done`.
                task_rec = snapshot.tasks.get(tid)
                la = task_rec.get("land_approved") if isinstance(task_rec, dict) else None
                landed = task_rec.get("landed") if isinstance(task_rec, dict) else None
                if not ((isinstance(la, dict) and la.get("helper_name") == principal.helper_name)
                        or (isinstance(landed, dict) and landed.get("by") == "helper")):
                    return _deny(f"exec helper {principal.helper_name} lacks matching land_approved on {tid}")
            return _allow()
        return _deny(f"helper ({principal.helper_mode or 'readonly'}) cannot send {kind!r}")

    return _deny(f"unknown role {role!r}")
