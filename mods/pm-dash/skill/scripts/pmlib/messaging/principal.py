"""Explicit caller identity `Principal` replacing `HC_TERMINAL_ID` spoofing (§8.1). Layer 2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..context import Context
from ..home import project_slug
from ..ledger.task import pm_started

try:
    from typing import Literal
except ImportError:  # pragma: no cover - Python 3.7 fallback
    Literal = Any  # type: ignore[misc,assignment]


RoleKind = Literal["user", "pm", "worker", "reviewer", "helper", "supervisor", "hub", "discord"]
VALID_ROLES = frozenset({"user", "pm", "worker", "reviewer", "helper", "supervisor", "hub", "discord"})


@dataclass(frozen=True)
class Principal:
    """Authenticated or locally-bound caller identity carried on every `Envelope`."""

    role: str
    actor_id: str
    project: str
    machine: str | None = None
    task_id: str = ""
    helper_name: str = ""
    helper_mode: str = ""
    for_task: str = ""
    epoch: int = 1
    credential_id: str = ""

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(f"invalid Principal role: {self.role!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "actor_id": self.actor_id,
            "project": self.project,
            "machine": self.machine,
            "task_id": self.task_id,
            "helper_name": self.helper_name,
            "helper_mode": self.helper_mode,
            "for_task": self.for_task,
            "epoch": int(self.epoch or 1),
            "credential_id": self.credential_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Principal:
        machine_raw = data.get("machine")
        machine = str(machine_raw).strip() if isinstance(machine_raw, str) and machine_raw.strip() else None
        raw_epoch = data.get("epoch")
        epoch = int(raw_epoch) if isinstance(raw_epoch, int) and not isinstance(raw_epoch, bool) and raw_epoch > 0 else 1
        return cls(
            role=str(data.get("role") or "user"),
            actor_id=str(data.get("actor_id") or "user:cli"),
            project=str(data.get("project") or ""),
            machine=machine,
            task_id=str(data.get("task_id") or ""),
            helper_name=str(data.get("helper_name") or ""),
            helper_mode=str(data.get("helper_mode") or ""),
            for_task=str(data.get("for_task") or ""),
            epoch=epoch,
            credential_id=str(data.get("credential_id") or ""),
        )

    @classmethod
    def user(cls, project: str = "", *, actor_id: str = "user:desktop", credential_id: str = "local-uid") -> Principal:
        return cls(role="user", actor_id=actor_id, project=project, credential_id=credential_id)

    @classmethod
    def pm(cls, project: str, *, epoch: int = 1, credential_id: str = "") -> Principal:
        return cls(
            role="pm",
            actor_id=f"pm:{project}",
            project=project,
            epoch=max(1, int(epoch or 1)),
            credential_id=credential_id,
        )

    @classmethod
    def supervisor(cls, project: str, *, actor_id: str = "") -> Principal:
        return cls(
            role="supervisor",
            actor_id=actor_id or f"supervisor:{project}",
            project=project,
        )

    @classmethod
    def worker(
        cls,
        project: str,
        task_id: str,
        *,
        epoch: int = 1,
        machine: str | None = None,
        credential_id: str = "",
    ) -> Principal:
        return cls(
            role="worker",
            actor_id=f"task:{task_id}",
            project=project,
            machine=machine,
            task_id=task_id,
            epoch=max(1, int(epoch or 1)),
            credential_id=credential_id,
        )

    @classmethod
    def reviewer(
        cls,
        project: str,
        task_id: str,
        *,
        epoch: int = 1,
        machine: str | None = None,
        credential_id: str = "",
    ) -> Principal:
        return cls(
            role="reviewer",
            actor_id=f"reviewer:{task_id}",
            project=project,
            machine=machine,
            task_id=task_id,
            epoch=max(1, int(epoch or 1)),
            credential_id=credential_id,
        )

    @classmethod
    def helper(
        cls,
        project: str,
        owner_kind: str,
        owner_id: str,
        helper_name: str,
        *,
        mode: str = "readonly",
        for_task: str = "",
        epoch: int = 1,
        machine: str | None = None,
        credential_id: str = "",
    ) -> Principal:
        return cls(
            role="helper",
            actor_id=f"helper:{owner_kind}:{owner_id}/{helper_name}",
            project=project,
            machine=machine,
            task_id=owner_id if owner_kind == "task" else "",
            helper_name=helper_name,
            helper_mode=mode or "readonly",
            for_task=for_task,
            epoch=max(1, int(epoch or 1)),
            credential_id=credential_id,
        )

    @classmethod
    def discord(cls, project: str, channel_id: str = "") -> Principal:
        return cls(
            role="discord",
            actor_id=f"discord:{project}/{channel_id}" if channel_id else f"discord:{project}",
            project=project,
        )

    @classmethod
    def hub(cls, project: str = "") -> Principal:
        return cls(role="hub", actor_id="hub:local", project=project)


def _helper_mode(ctx: Context, caller: Any, helper: Mapping[str, Any], owner_kind: str, owner_id: str,
                 project: str) -> tuple[str, str]:
    """`(mode, for_task)` of the helper this session is: its terminal's `helper.mode` / `helper.task` labels (what
    `helper start` set), else its entry in the owner's ledger record; a helper never said to be `exec` is
    `readonly`."""
    labels = getattr(caller, "labels", None) if getattr(caller, "terminal", "") else None
    labels = labels if isinstance(labels, Mapping) else {}
    mode = str(helper.get("mode") or labels.get("helper.mode") or "")
    for_task = str(helper.get("for_task") or labels.get("helper.task") or "")
    if not mode or (mode == "exec" and not for_task):
        rec = ctx.store.registration(project) if owner_kind == "pm" else ctx.store.task(owner_id)
        items = rec.get("helpers") if isinstance(rec, Mapping) else None
        mine = [h for h in (items or []) if isinstance(h, Mapping) and h.get("name") == helper.get("name")]
        entry = next((h for h in reversed(mine) if h.get("status") == "running"), mine[-1] if mine else {})
        mode = mode or str(entry.get("mode") or "")
        for_task = for_task or str(entry.get("for_task") or "")
    return (mode if mode in ("readonly", "exec") else "readonly"), for_task


def resolve_local_principal(ctx: Context, project: str = "") -> Principal:
    """Resolve the caller's explicit `Principal` on the coordinator host from `ctx.caller` or token."""
    caller = getattr(ctx, "caller", None)
    if caller is None:
        return Principal.user(project, actor_id="user:cli")

    helper = getattr(caller, "helper", None)
    if isinstance(helper, Mapping) and helper.get("name"):
        h_proj = str(helper.get("project") or project or "")
        h_of = str(helper.get("of") or "")
        owner_kind = "pm" if h_of in ("pm", "", f"pm-{h_proj}") else "task"
        owner_id = h_proj if owner_kind == "pm" else h_of
        mode, for_task = _helper_mode(ctx, caller, helper, owner_kind, owner_id, h_proj)
        return Principal.helper(
            h_proj,
            owner_kind,
            owner_id,
            str(helper.get("name") or ""),
            mode=mode,
            for_task=for_task,
        )

    if project:
        reg = ctx.store.registration(project)
        repo = str((reg or {}).get("repo") or "")
        if reg and repo and caller.pane and caller.manages(repo):
            ep_raw = reg.get("epoch") if isinstance(reg.get("epoch"), int) else 1
            if isinstance(reg.get("endpoint"), Mapping):
                ep_raw = int(reg["endpoint"].get("epoch") or ep_raw or 1)
            return Principal.pm(project, epoch=ep_raw)

    own_task = getattr(caller, "own_task", None)
    # A worker (or reviewer) is the session of a task the PM started (as `Caller.role_in` and
    # `memory_writer` judge it); a session working on a task it registered itself is the user's.
    if isinstance(own_task, Mapping) and own_task.get("id") and pm_started(own_task):
        t_repo = str(own_task.get("repo") or "")
        t_proj = project or (project_slug(t_repo) if t_repo else str(own_task.get("project") or ""))
        tid = str(own_task["id"])
        ep_raw = own_task.get("epoch") if isinstance(own_task.get("epoch"), int) else 1
        if isinstance(own_task.get("endpoint"), Mapping):
            ep_raw = int(own_task["endpoint"].get("epoch") or ep_raw or 1)
        if own_task.get("review_of"):
            return Principal.reviewer(t_proj, tid, epoch=ep_raw)
        return Principal.worker(t_proj, tid, epoch=ep_raw)

    if not getattr(caller, "pane", ""):
        return Principal.user(project, actor_id="user:cli")
    return Principal.user(project, actor_id=f"user:{caller.pane}")
