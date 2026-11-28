"""`RemoteHcTransport`: `Transport` for a worker terminal on another machine reached through herdr-core's own SSH
bridge (`<machine>/t7`, `pm-message-routing.md` §5.2, §5.3, §7.2, §9.3 phase 6a). Layer 2.

Zero remote daemon by default (MR-D3): status, `status_ms`, `turn`, screen, `send`, `keys` and `interrupt` are
herdr-core's bridged terminal calls; the worker's report outbox (and an optional `obs-journal`) is pulled by `seq`
with `hc file read --on <machine>`.

Invariant I4: before any terminal call the machine's line is checked in `hc machine ls`; anything but `connected`
(connecting, needs_login, unreachable, a machine `hc` does not know, `hc` itself not answering, an `unavailable`
error mid-call, a terminal herdr-core reports as `lost`) is a partition: `deliver` -> `partitioned`, `interrupt`
-> `partitioned`, `observe` -> `link_state != "connected"` with no terminal state at all, so nobody reads it as
stalled, exited or offline. Only positive evidence from a connected machine (`not_found`, `finished`) says a
remote terminal is gone.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ...context import Context
from ..address import Endpoint
from ..envelope import Envelope
from ..mailbox import MailboxItem
from ..outbox import obs_lines, parse_outbox_text
from ..transport import (
    AsyncDeliverHandle,
    DeliverOutcome,
    InterruptOutcome,
    ObserveBatch,
    TransportCapabilities,
)
from .local_hc import LocalHcTransport, _ImmediateDeliverHandle, _error_kind, _status_state_of


PARTITION_ERRORS = frozenset({"unavailable", "machine_unknown", "needs_login", "needs_update"})
MACHINE_TTL_S = 5.0
OUTBOX_PULL_LIMIT = 200


def link_of_machine_state(state: str) -> str:
    """`hc machine ls` state -> `LinkState`."""
    s = str(state or "").strip().lower()
    if s == "connected":
        return "connected"
    if s == "connecting":
        return "connecting"
    if s == "needs_login":
        return "unauthorized"
    return "disconnected"


class RemoteHcTransport:
    """`Transport` for `Endpoint(runtime="hc", machine=<m>, terminal=<t>)`."""

    def __init__(self, ctx: Context, *, machine_ttl_s: float = MACHINE_TTL_S) -> None:
        self.ctx = ctx
        self._local = LocalHcTransport(ctx)
        self._ttl_ms = int(max(0.0, float(machine_ttl_s)) * 1000)
        self._machines: dict[str, tuple[int, dict[str, Any]]] = {}

    # --- the machine's line ------------------------------------------------------------------------------------

    def _now_ms(self) -> int:
        return int(float(self.ctx.clock.time()) * 1000)

    def forget_machine_state(self) -> None:
        self._machines.clear()

    def machine_view(self, machine: str) -> dict[str, Any]:
        """`{state, since_ms, detail}` for `machine` from `hc machine ls` (cached `machine_ttl_s`): `unknown_machine`
        when hc does not list it, `hc_unreachable` when the local core does not answer."""
        now = self._now_ms()
        hit = self._machines.get(machine)
        if hit is not None and now - hit[0] < self._ttl_ms:
            return hit[1]
        lister = getattr(self.ctx.hc, "machines", None)
        rows = lister() if callable(lister) else None
        if rows is None:
            view: dict[str, Any] = {"state": "unreachable", "since_ms": None, "detail": "hc_unreachable"}
        else:
            row = next((m for m in rows if str(m.get("name") or "") == machine), None)
            if row is None:
                view = {"state": "unreachable", "since_ms": None, "detail": "unknown_machine"}
            else:
                view = {"state": str(row.get("state") or "unreachable"), "since_ms": row.get("since_ms"),
                        "detail": str(row.get("state") or "")}
        self._machines[machine] = (now, view)
        return view

    def link_state(self, endpoint: Endpoint) -> str:
        if not endpoint.machine:
            return "disconnected"
        return link_of_machine_state(self.machine_view(endpoint.machine).get("state") or "")

    def _mark_down(self, endpoint: Endpoint, detail: str) -> None:
        """An `unavailable` mid-call outranks a cached `connected`: until the next `machine ls`, it is down."""
        if endpoint.machine:
            self._machines[endpoint.machine] = (self._now_ms(), {"state": "unreachable", "since_ms": self._now_ms(),
                                                                 "detail": detail or "unavailable"})

    def _partition_detail(self, endpoint: Endpoint) -> str:
        view = self.machine_view(endpoint.machine or "")
        return f"machine {endpoint.machine} {view.get('detail') or view.get('state')}"

    # --- Transport -----------------------------------------------------------------------------------------------

    def presence(self, endpoint: Endpoint) -> str:
        """`live`, `gone` (positive evidence from a connected machine) or `unknown` (the line is down: I4, nobody
        may conclude it exited)."""
        _, stop = self._gate(endpoint)
        if stop is None:
            return "live"
        return "gone" if stop.status == "endpoint_gone" else "unknown"

    def capabilities(self, endpoint: Endpoint, *, pre_info: Mapping[str, Any] | None = None) -> TransportCapabilities:
        if pre_info is None and self.link_state(endpoint) == "connected":
            pre_info = self.ctx.hc.get_raw(endpoint.hc_target, errors=True)
        can_report = (
            isinstance(pre_info, Mapping)
            and not _error_kind(pre_info)[0]
            and pre_info.get("reported") is not False
            and bool(_status_state_of(pre_info))
        )
        return TransportCapabilities(
            can_report_status=bool(can_report),
            can_interrupt=True,
            can_unblock_keys=True,
            can_observe_screen=True,
            can_observe_procs=False,       # no remote `ps` without the optional watcher (MR-D3)
            can_observe_transcript=False,  # likewise: the transcript file lives on that machine
            delivery_mode="push",
            supports_if_idle=bool(can_report),
        )

    def _gate(self, endpoint: Endpoint) -> tuple[Mapping[str, Any] | None, DeliverOutcome | None]:
        """Link check + `hc get`: (pre_info, None) to go on, or (None, outcome) to stop here."""
        if not endpoint.hc_target or not endpoint.machine:
            return None, DeliverOutcome(status="rejected", detail="not a remote hc endpoint")
        if self.link_state(endpoint) != "connected":
            return None, DeliverOutcome(status="partitioned", detail=self._partition_detail(endpoint))
        info = self.ctx.hc.get_raw(endpoint.hc_target, errors=True)
        kind, detail = _error_kind(info)
        if kind in PARTITION_ERRORS:
            self._mark_down(endpoint, kind)
            return None, DeliverOutcome(status="partitioned", detail=detail or kind)
        if kind in ("not_found", "finished"):
            return None, DeliverOutcome(status="endpoint_gone", detail=detail or kind)
        if info is None:
            # The bridge did not answer at all: no evidence about the terminal.
            return None, DeliverOutcome(status="partitioned", detail="no answer from hc get")
        state = str(info.get("state") or "").lower()
        if state == "lost":
            return None, DeliverOutcome(status="partitioned", detail="terminal lost by the bridge")
        if state in ("exited", "finished", "removed"):
            return None, DeliverOutcome(status="endpoint_gone", detail=state)
        return info, None

    def deliver(
        self,
        endpoint: Endpoint,
        item: MailboxItem,
        *,
        if_idle: bool = False,
        timeout_s: float = 70.0,
        occupation_hint: str = "",
        retry_note: str = "",
        pre_info: Mapping[str, Any] | None = None,
    ) -> DeliverOutcome:
        info, stop = self._gate(endpoint)
        if stop is not None:
            return stop
        out = self._local.deliver(
            endpoint, item, if_idle=if_idle, timeout_s=timeout_s,
            occupation_hint=occupation_hint, retry_note=retry_note, pre_info=info,
        )
        if out.status == "partitioned":
            self._mark_down(endpoint, out.detail)
        elif out.status == "timeout_uncertain" and self.link_state(endpoint) != "connected":
            # The line dropped under the send: still uncertain (never "typed" on a guess); `reconcile` decides later.
            return DeliverOutcome(status="timeout_uncertain", detail="link dropped during send; reconcile on reconnect")
        return out

    def start_deliver_async(
        self,
        endpoint: Endpoint,
        item: MailboxItem,
        *,
        if_idle: bool = False,
        timeout_s: float = 70.0,
        occupation_hint: str = "",
        retry_note: str = "",
        pre_info: Mapping[str, Any] | None = None,
    ) -> AsyncDeliverHandle:
        info, stop = self._gate(endpoint)
        if stop is not None:
            return _ImmediateDeliverHandle(stop, self._now_ms())
        return self._local.start_deliver_async(
            endpoint, item, if_idle=if_idle, timeout_s=timeout_s,
            occupation_hint=occupation_hint, retry_note=retry_note, pre_info=info,
        )

    def reconcile(self, endpoint: Endpoint, *, pre_turn: int | None, pre_status_ms: int | None) -> DeliverOutcome:
        """After `timeout_uncertain`: compare the terminal's `(turn, status_ms)` now with the intent's anchors. Moved
        on -> `typed` (do not type again); link still down -> `partitioned` (keep waiting); unmoved on a connected
        machine -> `timeout_uncertain` (the caller may retype)."""
        info, stop = self._gate(endpoint)
        if stop is not None:
            return stop
        assert info is not None
        turn = int(info.get("turn") or 0)
        sms = int(info.get("status_ms") or 0)
        working = _status_state_of(info) == "working"
        if (pre_turn is not None and turn > pre_turn) or (working and pre_status_ms is not None and sms > pre_status_ms):
            return DeliverOutcome(status="typed", started_turn=True, observed_turn=turn, observed_status_ms=sms,
                                  detail="reconciled_after_partition")
        return DeliverOutcome(status="timeout_uncertain", observed_turn=turn, observed_status_ms=sms,
                              detail="no progress since the uncertain send")

    def observe(
        self,
        endpoint: Endpoint,
        cursors: Mapping[str, int],
        *,
        include_screen: bool = False,
        include_procs: bool = False,
        outbox_path: str = "",
        obs_journal_path: str = "",
    ) -> ObserveBatch:
        now_ms = self._now_ms()
        link = self.link_state(endpoint)
        if link != "connected":
            return self._unlinked(endpoint, cursors, link, now_ms)
        info, stop = self._gate(endpoint)
        if stop is not None and stop.status == "partitioned":
            return self._unlinked(endpoint, cursors, "disconnected", now_ms, detail=stop.detail)
        base = self._local.observe(endpoint, cursors, include_screen=include_screen and stop is None,
                                   include_procs=False)
        next_cursors = dict(base.next_cursors)
        observations = list(base.observations)
        reports: list[Envelope] = []
        meta: list[dict[str, Any]] = []
        if outbox_path:
            pulled = self._pull_outbox(endpoint, outbox_path, next_cursors)
            if pulled is None:
                return self._unlinked(endpoint, cursors, "disconnected", now_ms, detail="outbox read unavailable")
            for line in pulled:
                try:
                    env = Envelope.from_dict(line.envelope)
                except (ValueError, TypeError):
                    env = None
                meta.append({"seq": line.seq, "mac": line.mac, "envelope": line.envelope, "parsed": env is not None})
                if env is not None:
                    reports.append(env)
        if obs_journal_path:
            pulled_obs = self._pull_obs(endpoint, obs_journal_path, next_cursors)
            if pulled_obs is None:
                return self._unlinked(endpoint, cursors, "disconnected", now_ms, detail="obs-journal read unavailable")
            observations.extend(pulled_obs)
        return ObserveBatch(
            link_state="connected",
            observations=tuple(observations),
            next_cursors=next_cursors,
            inbound_reports=tuple(reports),
            terminal_info=base.terminal_info,
            inbound_meta=tuple(meta),
        )

    def _unlinked(self, endpoint: Endpoint, cursors: Mapping[str, int], link: str, now_ms: int, *,
                  detail: str = "") -> ObserveBatch:
        view = self.machine_view(endpoint.machine or "") if endpoint.machine else {}
        return ObserveBatch(
            link_state=link if link != "connected" else "disconnected",
            observations=({
                "src": "supervisor",
                "kind": "link_state",
                "t": now_ms,
                "link_state": link if link != "connected" else "disconnected",
                "health": "unknown",
                "unknown_reason": "machine_disconnected",
                "since_ms": view.get("since_ms"),
                "detail": detail or str(view.get("detail") or ""),
                "endpoint": endpoint.to_dict(),
            },),
            next_cursors=dict(cursors),
        )

    def _read_remote(self, endpoint: Endpoint, path: str, offset: int) -> tuple[str, bool] | None:
        """(text, exists) of `path` from line `offset` on, or None when the machine did not answer."""
        res = self.ctx.hc.file_read(path, on=endpoint.machine or "", offset=offset, limit=OUTBOX_PULL_LIMIT)
        kind, _ = _error_kind(res)
        if kind in PARTITION_ERRORS or res is None:
            self._mark_down(endpoint, kind or "file read failed")
            return None
        if kind:
            return "", False  # not_found (nothing written yet) or a read refusal: nothing to pull
        return str(res.get("text") or ""), True

    def _pull_outbox(self, endpoint: Endpoint, path: str, cursors: dict[str, int]) -> list[Any] | None:
        after = int(cursors.get("outbox_seq") or 0)
        got = self._read_remote(endpoint, path, after + 1)
        if got is None:
            return None
        rows = parse_outbox_text(got[0], after_seq=after)
        # Only a gap-free run is taken: line N must hold seq N, so a missing or torn line is read again next time.
        taken = []
        expect = after + 1
        for row in rows:
            if row.seq != expect:
                break
            taken.append(row)
            expect += 1
        if taken:
            cursors["outbox_seq"] = taken[-1].seq
        return taken

    def _pull_obs(self, endpoint: Endpoint, path: str, cursors: dict[str, int]) -> list[dict[str, Any]] | None:
        after = int(cursors.get("obs_seq") or 0)
        got = self._read_remote(endpoint, path, after + 1)
        if got is None:
            return None
        rows = obs_lines(got[0], after_seq=after)
        if rows:
            cursors["obs_seq"] = max(int(r["seq"]) for r in rows)
        return [{**r, "src": str(r.get("src") or "remote:obs"), "endpoint": endpoint.to_dict()} for r in rows]

    def interrupt(self, endpoint: Endpoint, *, timeout_s: float = 5.0) -> InterruptOutcome:
        if self.link_state(endpoint) != "connected":
            return InterruptOutcome(status="partitioned", detail=self._partition_detail(endpoint))
        out = self._local.interrupt(endpoint, timeout_s=timeout_s)
        if out.status == "partitioned":
            self._mark_down(endpoint, out.detail)
        return out

    def unblock_prompt(self, endpoint: Endpoint, keys: Sequence[str]) -> bool:
        if self.link_state(endpoint) != "connected":
            return False
        return self._local.unblock_prompt(endpoint, keys)
