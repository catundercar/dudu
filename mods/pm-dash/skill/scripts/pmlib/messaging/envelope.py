"""Unified `Envelope` schema, priorities, lifecycle states, and terminal anchor formatting. Layer 2."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import time
from typing import Any, Mapping

from .address import LogicalAddress
from .principal import Principal

try:
    from typing import Literal
except ImportError:  # pragma: no cover - Python 3.7 fallback
    Literal = Any  # type: ignore[misc,assignment]


P0_CONTROL = 0
P1_USER = 1
P2_RESUME = 2
P3_DIRECT = 3
P4_BATCH = 4

Priority = Literal[0, 1, 2, 3, 4]
DeliveryState = Literal["accepted", "typed", "consumed", "answered", "failed", "expired", "superseded"]
ReportState = Literal["queued", "accepted", "applied", "rejected"]

TERMINAL_DELIVERY_STATES = frozenset({"answered", "failed", "expired", "superseded"})
TERMINAL_REPORT_STATES = frozenset({"applied", "rejected"})

_ENV_ID_RE = re.compile(r"\benv_[0-9a-f]{6,16}_[0-9a-f]{6,16}\b")


def new_env_id(now_ms: int | None = None) -> str:
    """Generate a lexicographically roughly-ordered unique envelope ID `env_<48-bit-ms-hex>_<32-bit-rand-hex>`."""
    ms = int(now_ms if now_ms is not None else time.time() * 1000)
    ms_clamped = max(0, ms) & 0xFFFFFFFFFFFF
    rand_hex = os.urandom(4).hex()
    return f"env_{ms_clamped:012x}_{rand_hex}"


def extract_env_id(text: str | None) -> str:
    """Extract an embedded `env_<hex>_<hex>` anchor from terminal input / transcript text, or ''."""
    if not text:
        return ""
    m = _ENV_ID_RE.search(str(text))
    return m.group(0) if m else ""


def format_deliver_text(
    env: Envelope,
    *,
    attempt: int = 1,
    occupation_hint: str = "",
    retry_note: str = "",
) -> str:
    """Render an outbound `Envelope` payload for terminal injection, embedding `#env_id` for non-user inputs."""
    body = env.body if isinstance(env.body, Mapping) else {}
    text = str(body.get("text") or "").strip()
    if not text and env.kind == "cmd.resume_turn":
        text = str(body.get("prompt") or "").strip()

    if env.kind == "cmd.brief":
        # A worker's brief is its opening prompt: it goes in exactly as written (not even trimmed).
        base = str(body.get("text") or "")
    elif env.kind == "chat.user":
        # User messages stay clean in the agent's prompt so `prompt_kind` == `"user"` and `same_user_prompt` match.
        base = text
    elif env.kind == "event.batch":
        lines = text.splitlines() if text else []
        if lines:
            first = lines[0]
            if f"#{env.env_id}" not in first:
                if first.startswith("[from pm.py deliver]"):
                    first = f"{first} #{env.env_id}"
                else:
                    first = f"[from pm.py deliver] {first} #{env.env_id}"
            if attempt > 1 and retry_note:
                first = f"{first} [{retry_note}]"
            lines[0] = first
            base = "\n".join(lines)
        else:
            base = f"[from pm.py deliver] #{env.env_id}"
    else:
        if f"#{env.env_id}" in text:
            base = text
        elif text.startswith("[from "):
            if env.kind == "event.notify":
                base = text
            else:
                end_bracket = text.find("]")
                if end_bracket > 0:
                    base = f"{text[:end_bracket]} #{env.env_id}{text[end_bracket:]}"
                else:
                    base = f"[from pm.py #{env.env_id}] {text}"
        else:
            sender_tag = env.kind.split(".", 1)[0]
            base = f"[from pm.py {sender_tag} #{env.env_id}] {text}" if text else f"[from pm.py {sender_tag} #{env.env_id}]"

    if occupation_hint:
        return f"{occupation_hint.strip()}\n{base}" if base else occupation_hint.strip()
    return base


@dataclass(frozen=True)
class Envelope:
    """Unified immutable message envelope shared across all directions (§2.1)."""

    env_id: str
    idempotency_key: str
    schema_version: int
    created_ms: int
    kind: str
    sender: Principal
    recipient: LogicalAddress
    project: str
    cause: dict[str, Any]
    priority: int
    body: dict[str, Any]
    attachments: tuple[str, ...] = field(default_factory=tuple)
    coalesce_key: str = ""
    require_reply: bool = False
    max_attempts: int = 3
    ttl_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "env_id": self.env_id,
            "idempotency_key": self.idempotency_key,
            "schema_version": int(self.schema_version),
            "created_ms": int(self.created_ms),
            "kind": self.kind,
            "sender": self.sender.to_dict(),
            "recipient": self.recipient.to_uri(),
            "project": self.project,
            "cause": dict(self.cause),
            "priority": int(self.priority),
            "body": dict(self.body),
            "attachments": list(self.attachments),
            "coalesce_key": self.coalesce_key,
            "require_reply": bool(self.require_reply),
            "max_attempts": int(self.max_attempts),
            "ttl_ms": int(self.ttl_ms),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Envelope:
        sender_raw = data.get("sender")
        sender = (
            sender_raw
            if isinstance(sender_raw, Principal)
            else Principal.from_dict(sender_raw if isinstance(sender_raw, Mapping) else {})
        )
        rec_raw = data.get("recipient")
        proj = str(data.get("project") or "")
        recipient = (
            rec_raw
            if isinstance(rec_raw, LogicalAddress)
            else LogicalAddress.parse(str(rec_raw or ""), project=proj)
        )
        atts = data.get("attachments")
        att_tuple = tuple(str(x) for x in atts) if isinstance(atts, (list, tuple)) else ()
        cause_raw = data.get("cause")
        body_raw = data.get("body")
        return cls(
            env_id=str(data.get("env_id") or new_env_id()),
            idempotency_key=str(data.get("idempotency_key") or ""),
            schema_version=int(data.get("schema_version") or 1),
            created_ms=int(data.get("created_ms") or 0),
            kind=str(data.get("kind") or ""),
            sender=sender,
            recipient=recipient,
            project=proj or recipient.project,
            cause=dict(cause_raw) if isinstance(cause_raw, Mapping) else {},
            priority=int(data.get("priority") if data.get("priority") is not None else P3_DIRECT),
            body=dict(body_raw) if isinstance(body_raw, Mapping) else {},
            attachments=att_tuple,
            coalesce_key=str(data.get("coalesce_key") or ""),
            require_reply=bool(data.get("require_reply")),
            max_attempts=max(1, int(data.get("max_attempts") or 3)),
            ttl_ms=max(0, int(data.get("ttl_ms") or 0)),
        )
