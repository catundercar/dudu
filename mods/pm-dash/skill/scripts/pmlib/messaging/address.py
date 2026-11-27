"""Logical addresses, structured `Endpoint`, legacy compatibility parsing, and `EndpointRegistry`. Layer 2."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Protocol
from urllib.parse import quote, unquote

from ..context import Context
from ..home import project_slug
from ..project.turn_reducer import (
    Endpoint,
    endpoint_from_dict,
    parse_legacy_endpoint,
    record_endpoint,
)

try:
    from typing import Literal
except ImportError:  # pragma: no cover - Python 3.7 fallback
    Literal = Any  # type: ignore[misc,assignment]


AddressKind = Literal["pm", "worker", "reviewer", "helper", "ui", "discord", "hub", "ledger"]
RuntimeKind = Literal["hc", "tui", "self_hosted", "virtual"]

VALID_ADDRESS_KINDS = frozenset({"pm", "worker", "reviewer", "helper", "ui", "discord", "hub", "ledger"})
_SAFE_UID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_endpoint_uid(endpoint: Endpoint | str) -> str:
    """Return a filesystem-safe directory name for an `Endpoint` or its `uid` string."""
    raw = endpoint.uid if isinstance(endpoint, Endpoint) else str(endpoint or "unknown")
    cleaned = _SAFE_UID_RE.sub("_", raw).strip("._")
    return cleaned or "unknown"


def is_remote_endpoint(endpoint: Endpoint | None) -> bool:
    """True when `endpoint` lives on a non-local machine (remote `hc` or `self_hosted`)."""
    if endpoint is None:
        return False
    return bool(endpoint.machine) or endpoint.runtime == "self_hosted"


def is_remote_pane(raw_pane: str | None, *, runtime_hint: str = "") -> bool:
    """Resolve `raw_pane` via `parse_legacy_endpoint` so TUI `'sess/w1:p1'` is never mistaken for remote."""
    ep = parse_legacy_endpoint(raw_pane, runtime_hint=runtime_hint)
    return is_remote_endpoint(ep)


@dataclass(frozen=True)
class LogicalAddress:
    """Transport-agnostic logical recipient/sender address (`pm://dudu`, `worker://<tid>`, etc.)."""

    kind: str
    project: str
    target: str

    def __post_init__(self) -> None:
        if self.kind not in VALID_ADDRESS_KINDS:
            raise ValueError(f"invalid LogicalAddress kind: {self.kind!r}")
        if not self.target and self.kind != "hub":
            raise ValueError(f"LogicalAddress kind {self.kind!r} requires non-empty target")

    def to_uri(self) -> str:
        if self.kind == "discord" and self.project:
            return f"discord://{quote(self.project, safe='')}/{quote(self.target, safe='/:_-')}"
        if self.kind == "hub":
            return f"hub://{self.target or 'local'}"
        return f"{self.kind}://{self.target}"

    @classmethod
    def pm(cls, slug: str) -> LogicalAddress:
        return cls(kind="pm", project=slug, target=slug)

    @classmethod
    def worker(cls, task_id: str, project: str = "") -> LogicalAddress:
        return cls(kind="worker", project=project, target=task_id)

    @classmethod
    def reviewer(cls, task_id: str, project: str = "") -> LogicalAddress:
        return cls(kind="reviewer", project=project, target=task_id)

    @classmethod
    def helper(cls, owner_kind: str, owner_id: str, name: str, project: str = "") -> LogicalAddress:
        return cls(kind="helper", project=project, target=f"{owner_kind}:{owner_id}/{name}")

    @classmethod
    def ui(cls, slug: str) -> LogicalAddress:
        return cls(kind="ui", project=slug, target=slug)

    @classmethod
    def discord(cls, slug: str, channel_id: str = "default") -> LogicalAddress:
        return cls(kind="discord", project=slug, target=channel_id or "default")

    @classmethod
    def hub(cls, target: str = "local") -> LogicalAddress:
        return cls(kind="hub", project="", target=target or "local")

    @classmethod
    def ledger(cls, slug: str) -> LogicalAddress:
        return cls(kind="ledger", project=slug, target=slug)

    @classmethod
    def parse(cls, uri: str, *, project: str = "") -> LogicalAddress:
        raw = str(uri or "").strip()
        if "://" not in raw:
            raise ValueError(f"invalid LogicalAddress URI: {uri!r}")
        scheme, _, rest = raw.partition("://")
        kind = scheme.strip().lower()
        if kind not in VALID_ADDRESS_KINDS:
            raise ValueError(f"unsupported LogicalAddress scheme: {scheme!r}")
        body = rest.strip().rstrip("/")
        if kind == "hub":
            return cls(kind="hub", project="", target=body or "local")
        if not body:
            raise ValueError(f"missing target in LogicalAddress URI: {uri!r}")
        if kind in ("pm", "ui", "ledger"):
            slug = body.split("/", 1)[0]
            return cls(kind=kind, project=project or slug, target=slug)
        if kind == "discord":
            proj_part, slash, ch = body.partition("/")
            if slash:
                return cls(kind="discord", project=unquote(proj_part), target=unquote(ch) or "default")
            return cls(kind="discord", project=project, target=unquote(proj_part))
        if kind == "helper":
            # helper://<owner_kind>:<owner_id>/<name>
            return cls(kind="helper", project=project, target=body)
        return cls(kind=kind, project=project, target=body)


class EndpointRegistry(Protocol):
    """Protocol mapping `LogicalAddress` <-> physical/virtual `Endpoint`."""

    def resolve(self, addr: LogicalAddress | str) -> Endpoint | None: ...
    def reverse_lookup(self, endpoint: Endpoint) -> list[LogicalAddress]: ...


def _helper_endpoint(rec: Mapping[str, Any], name: str) -> Endpoint | None:
    helpers = rec.get("helpers")
    if not isinstance(helpers, list):
        return None
    for item in reversed(helpers):
        if not isinstance(item, Mapping):
            continue
        if str(item.get("name") or "") != name:
            continue
        if isinstance(item.get("endpoint"), Mapping):
            ep = endpoint_from_dict(item["endpoint"])
            if ep is not None:
                return ep
        term = str(item.get("terminal") or "").strip()
        pane = str(item.get("pane") or "").strip()
        if pane:
            return parse_legacy_endpoint(pane, agent_kind=str(item.get("agent") or ""))
        if term:
            return parse_legacy_endpoint(term, runtime_hint="hc", agent_kind=str(item.get("agent") or ""))
    return None


class StoreEndpointRegistry:
    """`EndpointRegistry` backed by `Context.store` (`pms/<slug>.json`, `tasks/<tid>.json`)."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def _slug_for_task(self, task: Mapping[str, Any]) -> str:
        repo = str(task.get("repo") or "").strip()
        if repo:
            return project_slug(repo)
        return str(task.get("project") or "").strip().lower()

    def resolve(self, addr: LogicalAddress | str) -> Endpoint | None:
        parsed = LogicalAddress.parse(addr) if isinstance(addr, str) else addr
        kind = parsed.kind
        if kind == "pm":
            rec = self.ctx.store.registration(parsed.target)
            return record_endpoint(rec)
        if kind in ("worker", "reviewer"):
            task = self.ctx.store.task(parsed.target)
            return record_endpoint(task)
        if kind == "helper":
            owner_part, slash, hname = parsed.target.partition("/")
            if not slash or not hname:
                return None
            owner_kind, _, owner_id = owner_part.partition(":")
            if owner_kind == "pm":
                rec = self.ctx.store.registration(owner_id)
                return _helper_endpoint(rec, hname) if isinstance(rec, Mapping) else None
            if owner_kind == "task":
                task = self.ctx.store.task(owner_id)
                return _helper_endpoint(task, hname) if isinstance(task, Mapping) else None
            return None
        if kind == "hub":
            rec = self.ctx.store.registration("_hub") if self.ctx.home.registration("_hub").is_file() else None
            return record_endpoint(rec)
        if kind == "ui":
            return Endpoint(runtime="virtual", machine=None, terminal=f"ui:{parsed.target}")
        if kind == "discord":
            proj = parsed.project or "default"
            return Endpoint(runtime="virtual", machine=None, terminal=f"discord:{proj}/{parsed.target}")
        if kind == "ledger":
            return Endpoint(runtime="virtual", machine=None, terminal=f"ledger:{parsed.target}")
        return None

    def reverse_lookup(self, endpoint: Endpoint) -> list[LogicalAddress]:
        out: list[LogicalAddress] = []
        if endpoint.runtime == "virtual":
            if endpoint.terminal.startswith("ui:"):
                out.append(LogicalAddress.ui(endpoint.terminal[3:]))
            elif endpoint.terminal.startswith("ledger:"):
                out.append(LogicalAddress.ledger(endpoint.terminal[7:]))
            elif endpoint.terminal.startswith("discord:"):
                proj, _, ch = endpoint.terminal[8:].partition("/")
                out.append(LogicalAddress.discord(proj, ch or "default"))
            return out

        target_uid = endpoint.uid
        for reg in self.ctx.store.registrations():
            if not isinstance(reg, Mapping):
                continue
            repo = str(reg.get("repo") or "").strip()
            slug = project_slug(repo) if repo else str(reg.get("project") or "").strip().lower()
            if not slug:
                continue
            pm_ep = record_endpoint(reg)
            if pm_ep is not None and pm_ep.uid == target_uid:
                out.append(LogicalAddress.pm(slug))
            for item in reg.get("helpers") or ():
                if not isinstance(item, Mapping):
                    continue
                hname = str(item.get("name") or "")
                hep = _helper_endpoint(reg, hname) if hname else None
                if hep is not None and hep.uid == target_uid:
                    out.append(LogicalAddress.helper("pm", slug, hname, project=slug))

        for task in self.ctx.store.tasks():
            if not isinstance(task, Mapping):
                continue
            tid = str(task.get("id") or "")
            if not tid:
                continue
            slug = self._slug_for_task(task)
            tep = record_endpoint(task)
            if tep is not None and tep.uid == target_uid:
                if task.get("review_of"):
                    out.append(LogicalAddress.reviewer(tid, project=slug))
                else:
                    out.append(LogicalAddress.worker(tid, project=slug))
            for item in task.get("helpers") or ():
                if not isinstance(item, Mapping):
                    continue
                hname = str(item.get("name") or "")
                hep = _helper_endpoint(task, hname) if hname else None
                if hep is not None and hep.uid == target_uid:
                    out.append(LogicalAddress.helper("task", tid, hname, project=slug))
        return out
