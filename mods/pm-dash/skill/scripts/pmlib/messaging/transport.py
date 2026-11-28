"""Transport interface (`Transport`), capabilities, and structured delivery/interrupt/observe outcomes (§5). Layer 2."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from .address import Endpoint
from .envelope import Envelope
from .mailbox import MailboxItem

try:
    from typing import Literal
except ImportError:  # pragma: no cover - Python 3.7 fallback
    Literal = Any  # type: ignore[misc,assignment]


LinkState = Literal["connected", "connecting", "disconnected", "unauthorized"]


@dataclass(frozen=True)
class TransportCapabilities:
    """Explicit capabilities reported by a `Transport` for an `Endpoint` (§1.2, §4.3)."""

    can_report_status: bool
    can_interrupt: bool
    can_unblock_keys: bool
    can_observe_screen: bool
    can_observe_procs: bool
    can_observe_transcript: bool
    delivery_mode: str = "push"
    supports_if_idle: bool = False

    def __post_init__(self) -> None:
        if not self.can_report_status and self.supports_if_idle:
            object.__setattr__(self, "supports_if_idle", False)


@dataclass(frozen=True)
class DeliverOutcome:
    """Outcome of `Transport.deliver` (§1.2, §5.1)."""

    status: str  # typed | status_mismatch | blocked_prompt | endpoint_gone | partitioned | timeout_uncertain | rejected
    started_turn: bool | None = None
    observed_turn: int | None = None
    observed_status_ms: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class InterruptOutcome:
    """Outcome of `Transport.interrupt` aligned with `hc schema` InterruptResult (§1.2, §5.3)."""

    status: str  # stopped | exited | still_working | unknown | unsupported | partitioned | endpoint_gone
    key_sent: str = ""
    detail: str = ""


@dataclass(frozen=True)
class ObserveBatch:
    """Incremental observation batch from `Transport.observe` (§1.2)."""

    link_state: str  # connected | connecting | disconnected | unauthorized
    observations: tuple[dict[str, Any], ...] = ()
    next_cursors: dict[str, int] = field(default_factory=dict)
    inbound_reports: tuple[Envelope, ...] = ()
    terminal_info: dict[str, Any] | None = None
    # One row per pulled outbox line, in order: `{seq, mac, envelope, parsed}` (the MAC is checked by the applier
    # side against the task token; the envelope as written, since the MAC covers exactly those bytes).
    inbound_meta: tuple[dict[str, Any], ...] = ()


class AsyncDeliverHandle(Protocol):
    """Non-blocking handle for an in-progress `Transport.start_deliver_async()` call."""

    @property
    def started_ms(self) -> int: ...

    def poll(self) -> DeliverOutcome | None: ...

    def cancel(self) -> None: ...


class Transport(Protocol):
    """Unified endpoint transport contract implemented per runtime/machine topology (§1.2, §5)."""

    def capabilities(self, endpoint: Endpoint) -> TransportCapabilities: ...

    def deliver(
        self,
        endpoint: Endpoint,
        item: MailboxItem,
        *,
        if_idle: bool,
        timeout_s: float = 70.0,
    ) -> DeliverOutcome: ...

    def observe(
        self,
        endpoint: Endpoint,
        cursors: Mapping[str, int],
        *,
        include_screen: bool = False,
        include_procs: bool = False,
    ) -> ObserveBatch: ...

    def interrupt(self, endpoint: Endpoint, *, timeout_s: float = 5.0) -> InterruptOutcome: ...

    def unblock_prompt(self, endpoint: Endpoint, keys: Sequence[str]) -> bool: ...
