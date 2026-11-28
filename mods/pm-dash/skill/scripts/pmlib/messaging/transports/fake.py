"""`FakeTransport`: programmable deterministic `Transport` test double (§10.3). Layer 2."""
from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from ..address import Endpoint
from ..envelope import Envelope, format_deliver_text
from ..mailbox import MailboxItem
from ..transport import (
    AsyncDeliverHandle,
    DeliverOutcome,
    InterruptOutcome,
    ObserveBatch,
    TransportCapabilities,
)


class _FakeAsyncHandle:
    def __init__(
        self,
        transport: FakeTransport,
        endpoint: Endpoint,
        item: MailboxItem,
        *,
        if_idle: bool,
        delay_ms: int,
        started_ms: int,
    ) -> None:
        self._transport = transport
        self._endpoint = endpoint
        self._item = item
        self._if_idle = if_idle
        self._ready_at_ms = started_ms + max(0, int(delay_ms))
        self._started_ms = started_ms
        self._outcome: DeliverOutcome | None = None

    @property
    def started_ms(self) -> int:
        return self._started_ms

    def poll(self) -> DeliverOutcome | None:
        if self._outcome is not None:
            return self._outcome
        now_ms = self._transport._now_ms()
        if now_ms < self._ready_at_ms:
            return None
        self._outcome = self._transport.deliver(self._endpoint, self._item, if_idle=self._if_idle)
        return self._outcome

    def cancel(self) -> None:
        return None


class FakeTransport:
    """Scriptable in-memory `Transport` supporting stateless endpoints, drafts, timeouts, partitions, and interrupts."""

    def __init__(self, clock: Any = None) -> None:
        self._clock = clock
        self.endpoints: dict[str, dict[str, Any]] = {}
        self.deliveries: list[dict[str, Any]] = []
        self.interrupts: list[dict[str, Any]] = []
        self.unblocks: list[tuple[str, tuple[str, ...]]] = []
        self._step = 0

    def _now_ms(self) -> int:
        if self._clock is not None:
            return int(float(self._clock.time()) * 1000)
        self._step += 1
        return 1_700_000_000_000 + self._step * 100

    def configure(self, endpoint: Endpoint | str, **attrs: Any) -> None:
        uid = endpoint.uid if isinstance(endpoint, Endpoint) else str(endpoint)
        state = self.endpoints.setdefault(uid, {
            "live": True,
            "agent_state": "idle",
            "can_report_status": True,
            "can_interrupt": True,
            "can_unblock_keys": True,
            "link_state": "connected",
            "turn": 1,
            "status_ms": 0,
            "screen": "",
            "draft_delay_ms": 0,
            "next_deliver": None,          # optional scripted DeliverOutcome or list of outcomes
            "next_interrupt": None,        # optional scripted InterruptOutcome
            "advance_turn_on_timeout": False,
            "inbound_reports": [],
        })
        state.update(attrs)

    def _ep(self, endpoint: Endpoint) -> dict[str, Any]:
        return self.endpoints.setdefault(endpoint.uid, {
            "live": True,
            "agent_state": "idle",
            "can_report_status": True,
            "can_interrupt": True,
            "can_unblock_keys": True,
            "link_state": "connected",
            "turn": 1,
            "status_ms": 0,
            "screen": "",
            "draft_delay_ms": 0,
            "next_deliver": None,
            "next_interrupt": None,
            "advance_turn_on_timeout": False,
            "inbound_reports": [],
        })

    def capabilities(self, endpoint: Endpoint) -> TransportCapabilities:
        st = self._ep(endpoint)
        can_report = bool(st.get("can_report_status", True))
        return TransportCapabilities(
            can_report_status=can_report,
            can_interrupt=bool(st.get("can_interrupt", True)),
            can_unblock_keys=bool(st.get("can_unblock_keys", True)),
            can_observe_screen=True,
            can_observe_procs=True,
            can_observe_transcript=True,
            delivery_mode="push",
            supports_if_idle=can_report,
        )

    def deliver(
        self,
        endpoint: Endpoint,
        item: MailboxItem,
        *,
        if_idle: bool = False,
        timeout_s: float = 70.0,
    ) -> DeliverOutcome:
        st = self._ep(endpoint)
        if st.get("link_state", "connected") != "connected":
            return DeliverOutcome(status="partitioned", detail=str(st.get("link_state")))
        if not st.get("live", True):
            return DeliverOutcome(status="endpoint_gone", detail="exited")

        scripted = st.get("next_deliver")
        if isinstance(scripted, list) and scripted:
            out = scripted.pop(0)
            if isinstance(out, DeliverOutcome):
                if out.status == "timeout_uncertain" and st.get("advance_turn_on_timeout"):
                    st["turn"] = int(st.get("turn") or 0) + 1
                    st["status_ms"] = self._now_ms()
                    st["agent_state"] = "working"
                return out
        elif isinstance(scripted, DeliverOutcome):
            st["next_deliver"] = None
            if scripted.status == "timeout_uncertain" and st.get("advance_turn_on_timeout"):
                st["turn"] = int(st.get("turn") or 0) + 1
                st["status_ms"] = self._now_ms()
                st["agent_state"] = "working"
            return scripted

        agent_state = str(st.get("agent_state") or "")
        if agent_state == "blocked":
            return DeliverOutcome(status="blocked_prompt", detail="confirmation dialog")
        if if_idle and st.get("can_report_status", True) and agent_state != "idle":
            return DeliverOutcome(status="status_mismatch", detail=f"state={agent_state}")

        payload = format_deliver_text(item.envelope, attempt=item.next_attempt())
        self.deliveries.append({
            "uid": endpoint.uid,
            "env_id": item.envelope.env_id,
            "if_idle": bool(if_idle),
            "text": payload,
            "t": self._now_ms(),
        })
        now_ms = self._now_ms()
        if st.get("can_report_status", True):
            if agent_state == "error" and not st.get("start_on_error", False):
                started_turn: bool | None = False
            else:
                st["agent_state"] = "working"
                st["status_ms"] = now_ms
                started_turn = True
        else:
            started_turn = None
        return DeliverOutcome(
            status="typed",
            started_turn=started_turn,
            observed_turn=int(st.get("turn") or 0),
            observed_status_ms=now_ms,
            detail="fake_typed",
        )

    def start_deliver_async(
        self,
        endpoint: Endpoint,
        item: MailboxItem,
        *,
        if_idle: bool = False,
        timeout_s: float = 70.0,
        occupation_hint: str = "",
        retry_note: str = "",
    ) -> AsyncDeliverHandle:
        st = self._ep(endpoint)
        return _FakeAsyncHandle(
            self,
            endpoint,
            item,
            if_idle=if_idle,
            delay_ms=int(st.get("draft_delay_ms") or 0),
            started_ms=self._now_ms(),
        )

    def observe(
        self,
        endpoint: Endpoint,
        cursors: Mapping[str, int],
        *,
        include_screen: bool = False,
        include_procs: bool = False,
    ) -> ObserveBatch:
        st = self._ep(endpoint)
        now_ms = self._now_ms()
        link = str(st.get("link_state") or "connected")
        if link != "connected":
            return ObserveBatch(
                link_state=link,
                observations=({"src": "transport", "kind": "link_state", "link_state": link, "t": now_ms},),
                next_cursors=dict(cursors),
            )
        live = bool(st.get("live", True))
        can_report = bool(st.get("can_report_status", True))
        a_state = str(st.get("agent_state") or "") if can_report else ""
        obs: list[dict[str, Any]] = [{
            "src": "supervisor",
            "kind": "hc_state",
            "t": now_ms,
            "state": "live" if live else "exited",
            "status": a_state,
            "status_msg": str(st.get("status_msg") or ""),
            "status_ms": int(st.get("status_ms") or 0),
            "turn": int(st.get("turn") or 0),
            "reported": can_report,
            "endpoint": endpoint.to_dict(),
        }]
        if include_screen and live:
            scr = str(st.get("screen") or "")
            obs.append({
                "src": "probe:pty",
                "kind": "pty_probe",
                "t": now_ms,
                "digest": hashlib.sha256(scr.encode("utf-8")).hexdigest()[:16],
            })
        reports = tuple(st.get("inbound_reports") or ())
        st["inbound_reports"] = []
        next_c = dict(cursors)
        next_c["obs_seq"] = int(cursors.get("obs_seq") or 0) + len(obs)
        return ObserveBatch(
            link_state="connected",
            observations=tuple(obs),
            next_cursors=next_c,
            inbound_reports=reports,
        )

    def interrupt(self, endpoint: Endpoint, *, timeout_s: float = 5.0) -> InterruptOutcome:
        st = self._ep(endpoint)
        self.interrupts.append({"uid": endpoint.uid, "t": self._now_ms()})
        if st.get("link_state", "connected") != "connected":
            return InterruptOutcome(status="partitioned", detail=str(st.get("link_state")))
        if not st.get("live", True):
            return InterruptOutcome(status="endpoint_gone", detail="exited")
        if not st.get("can_interrupt", True):
            return InterruptOutcome(status="unsupported", detail="transport does not support live turn interruption")
        scripted = st.get("next_interrupt")
        if isinstance(scripted, InterruptOutcome):
            st["next_interrupt"] = None
            return scripted
        if not st.get("can_report_status", True):
            return InterruptOutcome(status="unknown", key_sent="ctrl+c")
        if st.get("agent_state") == "working":
            st["agent_state"] = "idle"
            st["turn"] = int(st.get("turn") or 0) + 1
            st["status_ms"] = self._now_ms()
        return InterruptOutcome(status="stopped", key_sent="esc")

    def unblock_prompt(self, endpoint: Endpoint, keys: Sequence[str]) -> bool:
        st = self._ep(endpoint)
        if st.get("link_state", "connected") != "connected":
            return False
        if not st.get("can_unblock_keys", True) or not st.get("live", True) or not keys:
            return False
        self.unblocks.append((endpoint.uid, tuple(keys)))
        if st.get("agent_state") == "blocked":
            st["agent_state"] = "idle"
        return True
