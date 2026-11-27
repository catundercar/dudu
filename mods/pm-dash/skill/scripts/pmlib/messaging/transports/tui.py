"""`LocalTuiTransport`: local Herdr TUI (`ctx.tui`) implementation of `Transport` (§5.3, §9.4). Layer 2."""
from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from ...context import Context
from ..address import Endpoint
from ..envelope import format_deliver_text
from ..mailbox import MailboxItem
from ..transport import (
    DeliverOutcome,
    InterruptOutcome,
    ObserveBatch,
    TransportCapabilities,
)


class LocalTuiTransport:
    """`Transport` implementation over `ctx.tui` (maintaining existing Herdr TUI compatibility)."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def capabilities(self, endpoint: Endpoint) -> TransportCapabilities:
        return TransportCapabilities(
            can_report_status=False,
            can_interrupt=True,
            can_unblock_keys=True,
            can_observe_screen=True,
            can_observe_procs=False,
            can_observe_transcript=True,
            delivery_mode="push",
            supports_if_idle=False,
        )

    def deliver(
        self,
        endpoint: Endpoint,
        item: MailboxItem,
        *,
        if_idle: bool = False,
        timeout_s: float = 70.0,
    ) -> DeliverOutcome:
        pane_id = endpoint.terminal
        session = endpoint.workspace or None
        if not pane_id:
            return DeliverOutcome(status="endpoint_gone", detail="empty pane_id")
        payload = format_deliver_text(item.envelope, attempt=item.next_attempt())
        res = self.ctx.tui.agent_prompt(pane_id, payload, session=session)
        if res is None:
            info = self.ctx.tui.pane_get(pane_id, session=session)
            if info is None:
                return DeliverOutcome(status="endpoint_gone", detail=f"pane {pane_id} not found")
            return DeliverOutcome(status="timeout_uncertain", detail="tui agent_prompt returned None")
        return DeliverOutcome(status="typed", started_turn=None, detail="tui_prompt_ok")

    def observe(
        self,
        endpoint: Endpoint,
        cursors: Mapping[str, int],
        *,
        include_screen: bool = False,
        include_procs: bool = False,
    ) -> ObserveBatch:
        pane_id = endpoint.terminal
        session = endpoint.workspace or None
        now_ms = int(float(self.ctx.clock.time()) * 1000)
        info = self.ctx.tui.pane_get(pane_id, session=session) if pane_id else None
        obs: list[dict[str, Any]] = []
        if info is None:
            obs.append({
                "src": "supervisor",
                "kind": "hc_state",
                "t": now_ms,
                "state": "exited",
                "status": "",
                "status_msg": "",
                "status_ms": 0,
                "turn": 0,
                "reported": False,
                "endpoint": endpoint.to_dict(),
            })
        else:
            obs.append({
                "src": "supervisor",
                "kind": "hc_state",
                "t": now_ms,
                "state": "live",
                "status": "",
                "status_msg": "",
                "status_ms": 0,
                "turn": 0,
                "reported": False,
                "endpoint": endpoint.to_dict(),
            })
            if include_screen:
                text = self.ctx.tui.pane_read(pane_id, session=session)
                digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
                obs.append({"src": "probe:pty", "kind": "pty_probe", "t": now_ms, "digest": digest, "text_len": len(text)})
        return ObserveBatch(
            link_state="connected",
            observations=tuple(obs),
            next_cursors=dict(cursors),
            terminal_info=dict(info) if isinstance(info, Mapping) else None,
        )

    def interrupt(self, endpoint: Endpoint, *, timeout_s: float = 5.0) -> InterruptOutcome:
        pane_id = endpoint.terminal
        session = endpoint.workspace or None
        if not pane_id:
            return InterruptOutcome(status="endpoint_gone", detail="empty pane_id")
        # "esc": the key name `herdr agent send-keys` has always been given for this (escalate's interrupt).
        res = self.ctx.tui.agent_send_keys(pane_id, "esc", session=session)
        if res is None:
            return InterruptOutcome(status="endpoint_gone", detail=f"pane {pane_id} unavailable")
        return InterruptOutcome(status="unknown", key_sent="esc", detail="tui_escape_sent")

    def unblock_prompt(self, endpoint: Endpoint, keys: Sequence[str]) -> bool:
        pane_id = endpoint.terminal
        session = endpoint.workspace or None
        if not pane_id or not keys:
            return False
        return self.ctx.tui.agent_send_keys(pane_id, *keys, session=session) is not None
