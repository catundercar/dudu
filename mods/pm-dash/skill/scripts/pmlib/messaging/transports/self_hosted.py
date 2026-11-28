"""`SelfHostedPullTransport`: `Transport` for a worker on a self-hosted node that only connects out (behind NAT, no
inbound SSH, no herdr bridge): `pm-message-routing.md` §5.2, §5.3 column 3, §7.2, §9.3 phase 6b. Layer 2.

The coordinator never calls the node. Everything goes through the node's pull queue (`NodeStreams`), which the node
reads on each outbound sync, and the observations it pushes back on that sync:

- `deliver` appends the envelope to the queue (idempotent by `env_id`): `typed` here means "durably handed to the
  node's pull stream", `started_turn=None` (nobody knows yet); the node types it into its local session and reports
  `typed` / `consumed(env_id)` in its observation stream. `if_idle` is checked against the endpoint state the node
  last pushed, and only when its runtime reports states (`can_report_status`).
- `interrupt` / `unblock_prompt` queue a `ctrl` entry; the node runs it locally and pushes the real outcome, so the
  answer here is `unknown` (or `unsupported` when the node said its runtime cannot interrupt).
- `observe` reads what the node pushed; the node's heartbeat is its last sync.

Invariant I4: a node whose last sync is older than `lease_timeout_s` (default 30 s) is a partition: `deliver` ->
`partitioned` (the envelope stays `accepted` in the endpoint mailbox and is handed over on the next sync),
`interrupt` -> `partitioned`, `observe` -> `link_state="disconnected"` with `health: "unknown"` and no terminal state
at all. Only the node's own positive report (`endpoint_state.gone`) makes an endpoint `endpoint_gone`. A revoked or
unknown node is `unauthorized`: nothing is queued for it (`rejected`).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ...context import Context
from ..address import Endpoint
from ..mailbox import MailboxItem
from ..nodes import NodeRegistry, NodeStreams
from ..transport import AsyncDeliverHandle, DeliverOutcome, InterruptOutcome, ObserveBatch, TransportCapabilities
from .local_hc import _ImmediateDeliverHandle


LEASE_TIMEOUT_S = 30.0
DEFAULT_NODE_CAPS = {
    "can_report_status": False, "can_interrupt": False, "can_unblock_keys": False,
    "can_observe_screen": False, "can_observe_procs": False, "can_observe_transcript": False,
}


class SelfHostedPullTransport:
    """`Transport` for `Endpoint(runtime="self_hosted", machine=<node_id>, terminal=<slot>)`."""

    def __init__(self, ctx: Context, *, lease_timeout_s: float = LEASE_TIMEOUT_S) -> None:
        self.ctx = ctx
        self.lease_ms = int(max(1.0, float(lease_timeout_s)) * 1000)
        self.registry = NodeRegistry(ctx.home.tokens, clock=ctx.clock)

    def _now_ms(self) -> int:
        return int(float(self.ctx.clock.time()) * 1000)

    def streams(self, endpoint: Endpoint) -> NodeStreams:
        return NodeStreams(self.ctx.home.nodes, str(endpoint.machine or ""))

    def _node(self, endpoint: Endpoint) -> dict[str, Any] | None:
        if endpoint.runtime != "self_hosted" or not endpoint.machine:
            return None
        return self.registry.get(str(endpoint.machine))

    def link_state(self, endpoint: Endpoint) -> str:
        node = self._node(endpoint)
        if node is None or node.get("revoked_ms"):
            return "unauthorized"
        last = self.streams(endpoint).last_sync_ms()
        if not last or self._now_ms() - last > self.lease_ms:
            return "disconnected"
        return "connected"

    def _slot(self, endpoint: Endpoint) -> dict[str, Any]:
        return self.streams(endpoint).slot(endpoint.terminal)

    def presence(self, endpoint: Endpoint) -> str:
        """`live`, `gone` (the node itself said so) or `unknown` (no line to it: I4)."""
        if self.link_state(endpoint) != "connected":
            return "unknown"
        return "gone" if self._slot(endpoint).get("gone") else "live"

    def capabilities(self, endpoint: Endpoint) -> TransportCapabilities:
        node = self._node(endpoint) or {}
        caps = {**DEFAULT_NODE_CAPS, **dict(node.get("capabilities") or {})}
        slot = self._slot(endpoint)
        connected = self.link_state(endpoint) == "connected"
        can_report = bool(caps.get("can_report_status")) and slot.get("reported") is not False and connected
        return TransportCapabilities(
            can_report_status=can_report,
            can_interrupt=bool(caps.get("can_interrupt")),
            can_unblock_keys=bool(caps.get("can_unblock_keys")),
            can_observe_screen=bool(caps.get("can_observe_screen")),
            can_observe_procs=bool(caps.get("can_observe_procs")),
            can_observe_transcript=bool(caps.get("can_observe_transcript")),
            delivery_mode="pull",
            supports_if_idle=can_report,
        )

    def _queue(self, endpoint: Endpoint, entry: Mapping[str, Any]) -> tuple[int, bool]:
        return self.streams(endpoint).append(endpoint.terminal, entry)

    def queued_count(self, endpoint: Endpoint) -> int:
        """Envelopes (not control entries) in the endpoint's pull queue."""
        return len([e for e in self.streams(endpoint).entries_for(endpoint.terminal) if e.get("envelope")])

    def deliver(
        self,
        endpoint: Endpoint,
        item: MailboxItem,
        *,
        if_idle: bool = False,
        timeout_s: float = 70.0,
        **_ignored: Any,
    ) -> DeliverOutcome:
        link = self.link_state(endpoint)
        if link == "unauthorized":
            return DeliverOutcome(status="rejected", detail="node revoked or unknown: nothing is queued for it")
        if link != "connected":
            return DeliverOutcome(status="partitioned", detail=f"node {endpoint.machine} silent past its lease")
        slot = self._slot(endpoint)
        if slot.get("gone"):
            return DeliverOutcome(status="endpoint_gone", detail="the node reported the session ended")
        state = str(slot.get("status") or "")
        if state == "blocked":
            return DeliverOutcome(status="blocked_prompt", detail="the node reported a prompt waiting")
        if if_idle and self.capabilities(endpoint).supports_if_idle and state != "idle":
            return DeliverOutcome(status="status_mismatch", detail=f"node reported {state or 'unknown'}")
        env = item.envelope
        seq, _new = self._queue(endpoint, {"env_id": env.env_id, "envelope": env.to_dict()})
        return DeliverOutcome(status="typed", started_turn=None, detail=f"queued_for_pull seq={seq}")

    def start_deliver_async(self, endpoint: Endpoint, item: MailboxItem, *, if_idle: bool = False,
                            timeout_s: float = 70.0, **kw: Any) -> AsyncDeliverHandle:
        # Appending to the pull queue never blocks: the handle is complete at once.
        return _ImmediateDeliverHandle(self.deliver(endpoint, item, if_idle=if_idle, timeout_s=timeout_s, **kw),
                                       self._now_ms())

    def observe(
        self,
        endpoint: Endpoint,
        cursors: Mapping[str, int],
        *,
        include_screen: bool = False,
        include_procs: bool = False,
        **_ignored: Any,
    ) -> ObserveBatch:
        now = self._now_ms()
        link = self.link_state(endpoint)
        if link != "connected":
            st = self.streams(endpoint)
            return ObserveBatch(
                link_state=link,
                observations=({
                    "src": "supervisor", "kind": "link_state", "t": now, "link_state": link, "health": "unknown",
                    "unknown_reason": "node_revoked" if link == "unauthorized" else "machine_disconnected",
                    "since_ms": st.last_sync_ms() or None, "endpoint": endpoint.to_dict(),
                },),
                next_cursors=dict(cursors),
            )
        after = int(cursors.get("obs_seq") or 0)
        rows = self.streams(endpoint).obs_after(endpoint.terminal, after)
        nxt = dict(cursors)
        if rows:
            nxt["obs_seq"] = max(after, max(int(r["seq"]) for r in rows))
        slot = self._slot(endpoint)
        info = {
            "address": endpoint.legacy_pane, "state": "exited" if slot.get("gone") else "live",
            "status": {"state": str(slot.get("status") or "")} if slot.get("status") else None,
            "reported": slot.get("reported"),
        }
        return ObserveBatch(
            link_state="connected",
            observations=tuple({**r, "src": str(r.get("src") or "node:obs"), "endpoint": endpoint.to_dict()} for r in rows),
            next_cursors=nxt,
            terminal_info=info,
        )

    def _ctrl(self, endpoint: Endpoint, ctrl: str, **fields: Any) -> int:
        eid = f"ctrl_{ctrl}_{self._now_ms():x}_{len(self.streams(endpoint).entries_for(endpoint.terminal))}"
        seq, _ = self._queue(endpoint, {"env_id": eid, "ctrl": ctrl, **fields})
        return seq

    def interrupt(self, endpoint: Endpoint, *, timeout_s: float = 5.0) -> InterruptOutcome:
        link = self.link_state(endpoint)
        if link != "connected":
            return InterruptOutcome(status="partitioned", detail="node revoked" if link == "unauthorized" else
                                    f"node {endpoint.machine} silent past its lease")
        if self._slot(endpoint).get("gone"):
            return InterruptOutcome(status="endpoint_gone", detail="the node reported the session ended")
        if not self.capabilities(endpoint).can_interrupt:
            return InterruptOutcome(status="unsupported", detail="this node's runtime cannot interrupt a live turn")
        seq = self._ctrl(endpoint, "interrupt")
        return InterruptOutcome(status="unknown", detail=f"ctrl.interrupt queued seq={seq}; the node reports the outcome")

    def unblock_prompt(self, endpoint: Endpoint, keys: Sequence[str]) -> bool:
        if self.link_state(endpoint) != "connected" or self._slot(endpoint).get("gone"):
            return False
        if not self.capabilities(endpoint).can_unblock_keys:
            return False
        self._ctrl(endpoint, "keys", keys=[str(k) for k in keys])
        return True
