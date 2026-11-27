"""Single typist for the terminals that are not a PM seat: worker, reviewer and helper endpoints
(`pm-message-routing.md` §1.3, §9.2 wave 3). Layer 2.

Each such endpoint has a mailbox of its own (`<home>/mailboxes/endpoints/<uid>/`, never the PM's: nothing here
writes a PM turn journal) and shares the per-endpoint `typist.lock` lease directory with every other mailbox, so the
PM's `EndpointDriver`, a `pm.py send`, a background drain and a stall watcher's prompt keys never type into one
terminal at the same time. Three things touch a terminal, all through `Transport`:

- `drain_endpoint`: type the endpoint's `accepted` envelopes in `(priority, seq)` order while holding the lease.
  A synchronous sender runs it inline; an asynchronous one (`pm.py send`, `update --send`, approve) enqueues and
  leaves it to a detached `pm.py _drain-endpoint`. Whoever holds the lease types what is queued, so a second sender
  that cannot get the lease waits until its envelope has been typed (by anyone) instead of typing it itself.
- `unblock_endpoint`: press the keys of a known prompt (trust, update dialog) under the lease, never waiting for it.
- `interrupt_endpoint`: a `ctrl.interrupt` envelope (P0) recorded in the endpoint's mailbox, then
  `Transport.interrupt`; control does not wait behind a send.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import os
from typing import Any, Callable, Mapping, Sequence

from ..context import Context
from ..errors import StoreError
from .address import Endpoint, LogicalAddress, safe_endpoint_uid
from .envelope import P0_CONTROL, Envelope, new_env_id
from .mailbox import MailboxItem, MailboxStore
from .principal import Principal
from .transport import DeliverOutcome, InterruptOutcome
from .transports.local_hc import LocalHcTransport
from .transports.tui import LocalTuiTransport

LEASE_POLL_S = 0.5
# How long a waiting sender keeps waiting for the lease while its envelope is still queued: past one hc send's
# longest draft wait (60 s) plus margin, for a few sends ahead of it.
DRAIN_WAIT_S = 300.0
# A queued send older than this was left by a drain that died: it fails (and its sender's reaction runs) rather than
# reaching the terminal long after it was meant to (the PM's own SLA for event batches).
DRAIN_MAX_AGE_S = 900.0
# Bounded auto-retry for transient `started=false` async sends (observed with agy workers): wait + check turn before re-typing.
UNSTARTED_RETRIES = 2
UNSTARTED_BACKOFF_S: tuple[float, ...] = (1.5, 3.0)


def now_ms_of(ctx: Context) -> int:
    return int(float(ctx.clock.time()) * 1000)


def endpoint_mailbox(ctx: Context, ep: Endpoint) -> MailboxStore:
    """The mailbox of a non-PM endpoint (its own folder; the lease directory is the shared one)."""
    return MailboxStore(ctx.home.endpoint_mailbox(safe_endpoint_uid(ep)), clock=ctx.clock, typist_dir=ctx.home.typists)


def transport_for(ctx: Context, ep: Endpoint) -> Any:
    return LocalTuiTransport(ctx) if ep.runtime == "tui" else LocalHcTransport(ctx)


def typed_meta(item: MailboxItem, outcome: DeliverOutcome) -> dict[str, Any]:
    """Facts about the send that typed `item`, kept on the item so a later check can tell whether its turn started."""
    intent = item.intent if isinstance(item.intent, Mapping) else {}
    return {
        "typed_started": outcome.started_turn,
        "typed_pre_turn": int(intent.get("pre_turn") or 0),
        "typed_pre_status_ms": int(intent.get("pre_status_ms") or 0),
        "typed_while_working": bool(intent.get("pre_working")),
        "attempts_preincremented": False,
    }


def close_if_no_reply(mailbox: MailboxStore, item: MailboxItem, outcome: DeliverOutcome, now_ms: int) -> MailboxItem:
    """An envelope that needs no reply (`event.notify`, the seat opening `cmd.send`) has nothing after `typed` that
    would ever end it: close it once typed. Typed with `started=false` (e.g. behind a draft in the terminal) is
    still typed, so it closes too; only an envelope whose sender retries such a send (`cause.retry_unstarted`: the
    seat opening prompt) stays `typed` for that retry to find, whoever typed it (the seat or the driver)."""
    if item.state != "typed" or item.envelope.require_reply:
        return item
    if outcome.started_turn is False and (item.envelope.cause or {}).get("retry_unstarted"):
        return item
    return mailbox.transition(item.envelope.env_id, "answered", now_ms=now_ms,
                              meta={"closed": "no_reply_needed"})


def turn_moved_on(info: Mapping[str, Any] | None, pre_turn: int, pre_status_ms: int) -> bool:
    """True when the terminal moved on since a send: a finished turn more, or `working` with a newer `status_ms`."""
    if not isinstance(info, Mapping):
        return False
    turn = int(info.get("turn") or 0)
    raw_status = info.get("status")
    state = str((raw_status.get("state") if isinstance(raw_status, Mapping) else raw_status) or "").strip().lower()
    sms = int(info.get("status_ms") or 0)
    return turn > pre_turn or (state == "working" and sms > pre_status_ms)


def _live_info(ctx: Context, ep: Endpoint) -> Mapping[str, Any] | None:
    if ep.runtime != "hc" or not ep.hc_target:
        return None
    info = ctx.hc.get_raw(ep.hc_target, errors=True)
    return info if isinstance(info, Mapping) and not info.get("error") else None


class TypistLease:
    """The endpoint's `typist.lock` lease, held by one owner token (never by pid alone, so two callers in one
    process exclude each other too)."""

    def __init__(self, ctx: Context, ep: Endpoint, mailbox: MailboxStore, *, ttl_s: float = 75.0) -> None:
        self.ctx = ctx
        self.ep = ep
        self.mailbox = mailbox
        self.ttl_ms = int(max(1.0, float(ttl_s)) * 1000)
        self.owner_pid = os.getpid()
        self.owner = f"{self.owner_pid}:typist:{os.urandom(4).hex()}"
        self.held = False

    def try_acquire(self, *, ttl_s: float | None = None) -> bool:
        """Take or renew the lease without waiting."""
        ttl_ms = int(float(ttl_s) * 1000) if ttl_s is not None else self.ttl_ms
        self.held = self.mailbox.acquire_typist_lease(
            self.ep.uid, self.owner_pid, ttl_ms=ttl_ms, now_ms=now_ms_of(self.ctx), owner=self.owner,
        )
        return self.held

    def acquire(self, wait_s: float) -> bool:
        """Take the lease, waiting at most `wait_s` seconds for another holder to let go."""
        deadline = self.ctx.clock.monotonic() + max(0.0, float(wait_s))
        while not self.try_acquire():
            if self.ctx.clock.monotonic() >= deadline:
                return False
            self.ctx.clock.sleep(LEASE_POLL_S)
        return True

    def release(self) -> None:
        if self.held:
            self.mailbox.release_typist_lease(self.ep.uid, self.owner_pid, owner=self.owner)
            self.held = False


def enqueue_for_endpoint(ctx: Context, ep: Endpoint, env: Envelope) -> tuple[MailboxStore, MailboxItem]:
    """Idempotently queue `env` for `ep` in the endpoint's own mailbox (`accepted`)."""
    mailbox = endpoint_mailbox(ctx, ep)
    item, _ = mailbox.enqueue(env, initial_state="accepted", now_ms=now_ms_of(ctx), target_endpoint_uid=ep.uid,
                              endpoint_epoch=int(ep.epoch or 1))
    return mailbox, item


def type_item_locked(
    ctx: Context,
    mailbox: MailboxStore,
    ep: Endpoint,
    item: MailboxItem,
    transport: Any,
    *,
    timeout_s: float = 70.0,
    if_idle: bool = False,
    close: bool = True,
) -> tuple[MailboxItem, DeliverOutcome]:
    """Type one `accepted` envelope while the caller holds the lease: the C3 intent first, then `deliver`, then
    `typed` (closed when it needs no reply, unless `close` is False: the caller first checks it took) or back to
    `accepted` with why it was held. Returns the item as it stands afterwards and the transport's outcome."""
    pre = _live_info(ctx, ep)
    pre_turn = int((pre or {}).get("turn") or 0)
    pre_sms = int((pre or {}).get("status_ms") or 0)
    attempt = item.next_attempt()
    cur = mailbox.record_intent(item.envelope.env_id, pre_turn=pre_turn, pre_status_ms=pre_sms, attempt=attempt,
                                endpoint_uid=ep.uid, now_ms=now_ms_of(ctx))
    kw: dict[str, Any] = {"if_idle": bool(if_idle), "timeout_s": float(timeout_s)}
    if isinstance(transport, LocalHcTransport) and pre is not None:
        kw["pre_info"] = pre
    outcome = transport.deliver(ep, cur, **kw)
    done = now_ms_of(ctx)
    after = mailbox.get(cur.envelope.env_id) or cur
    if outcome.status == "typed":
        if after.state == "accepted":
            after = mailbox.transition(cur.envelope.env_id, "typed", now_ms=done, attempts=attempt,
                                       target_endpoint_uid=ep.uid, endpoint_epoch=int(ep.epoch or 1),
                                       hold_reason="", clear_intent=True, meta=typed_meta(cur, outcome))
            if close:
                after = close_if_no_reply(mailbox, after, outcome, done)
        return after, outcome
    if after.state == "accepted":
        after = mailbox.update_hold_reason(cur.envelope.env_id, outcome.detail or outcome.status or "held",
                                           now_ms=done, clear_intent=outcome.status != "timeout_uncertain") or after
    return after, outcome


@dataclass
class DrainResult:
    """What one `drain_endpoint` call did: each envelope it typed or gave up on, with the transport's outcome."""

    typed: list[tuple[MailboxItem, DeliverOutcome]] = field(default_factory=list)
    failed: list[tuple[MailboxItem, DeliverOutcome]] = field(default_factory=list)
    waited_out: bool = False

    def outcome_for(self, env_id: str) -> DeliverOutcome | None:
        for item, out in (*self.typed, *self.failed):
            if item.envelope.env_id == env_id:
                return out
        return None


def is_control(item: MailboxItem) -> bool:
    """A control envelope (`ctrl.interrupt`, ...): carried out by its sender through `Transport.interrupt`, kept in
    the mailbox as a record; never text to type."""
    return item.envelope.kind.startswith("ctrl.")


def _typable(mailbox: MailboxStore, ep: Endpoint, max_age_s: float = 0.0, now_ms: int = 0) -> list[MailboxItem]:
    """The envelopes a drain types, in order: `accepted`, not control. A control envelope its sender left behind
    (it died before closing it) is expired here once it is older than `max_age_s`, so nothing lingers."""
    out = []
    for it in mailbox.pending_for_endpoint(ep.uid):
        if it.state != "accepted":
            continue
        if is_control(it):
            if max_age_s and now_ms - int(it.accepted_ms or it.envelope.created_ms or 0) > max_age_s * 1000:
                with contextlib.suppress(StoreError, KeyError):
                    mailbox.transition(it.envelope.env_id, "expired", now_ms=now_ms, error="expired",
                                       hold_reason="expired", clear_intent=True)
            continue
        out.append(it)
    return out


def _retry_unstarted_item(
    ctx: Context,
    mailbox: MailboxStore,
    ep: Endpoint,
    item: MailboxItem,
    outcome: DeliverOutcome,
    transport: Any,
    lease: TypistLease,
    accept: Callable[[MailboxItem, DeliverOutcome], bool],
    *,
    timeout_s: float,
) -> tuple[MailboxItem, DeliverOutcome, bool]:
    """Retry a typed envelope whose turn did not start (`started=false`) up to `UNSTARTED_RETRIES` times with
    bounded backoff, re-checking terminal turn/status before each retry so an already-started turn is never typed twice."""
    for retry_idx in range(UNSTARTED_RETRIES):
        delay = UNSTARTED_BACKOFF_S[min(retry_idx, len(UNSTARTED_BACKOFF_S) - 1)]
        ctx.clock.sleep(delay)
        lease.try_acquire()
        if ep.runtime == "hc" and ep.hc_target:
            raw = ctx.hc.get_raw(ep.hc_target, errors=True)
            if not isinstance(raw, Mapping) or raw.get("error") or raw.get("state") in ("exited", "finished", "removed"):
                return item, outcome, False
            st_raw = raw.get("status")
            st_name = str((st_raw.get("state") if isinstance(st_raw, Mapping) else st_raw) or "").strip().lower()
            if st_name in ("blocked", "error"):
                return item, outcome, False
            pre_turn = int(item.meta.get("typed_pre_turn") or 0)
            pre_sms = int(item.meta.get("typed_pre_status_ms") or 0)
            if st_name == "working" or turn_moved_on(raw, pre_turn, pre_sms):
                late = DeliverOutcome(
                    status="typed",
                    started_turn=True,
                    observed_turn=int(raw.get("turn") or 0),
                    observed_status_ms=int(raw.get("status_ms") or 0),
                    detail="started_late",
                )
                return item, late, True
        if item.state == "typed":
            item = mailbox.transition(
                item.envelope.env_id,
                "accepted",
                now_ms=now_ms_of(ctx),
                hold_reason="retry_unstarted",
                clear_intent=True,
            )
        item, outcome = type_item_locked(ctx, mailbox, ep, item, transport, timeout_s=timeout_s, close=False)
        if outcome.status == "typed" and accept(item, outcome):
            return item, outcome, True
        if outcome.status != "typed":
            return item, outcome, False
    return item, outcome, False


def _still_waiting(mailbox: MailboxStore, env_ids: Sequence[str]) -> list[str]:
    waiting = []
    for env_id in env_ids:
        cur = mailbox.get(env_id)
        if cur is not None and cur.state == "accepted":
            waiting.append(env_id)
    return waiting


def drain_endpoint(
    ctx: Context,
    ep: Endpoint,
    *,
    wait_for: Sequence[str] = (),
    wait_s: float = DRAIN_WAIT_S,
    timeout_s: float = 70.0,
    transport: Any = None,
    on_typed: Callable[[MailboxItem, DeliverOutcome], None] | None = None,
    on_failed: Callable[[MailboxItem, DeliverOutcome], None] | None = None,
    accept: Callable[[MailboxItem, DeliverOutcome], bool] | None = None,
    max_age_s: float = DRAIN_MAX_AGE_S,
) -> DrainResult:
    """Type `ep`'s queued envelopes while holding its lease, one attempt each: one that does not go in (gone,
    blocked on a prompt, timed out, refused), or that `accept` says did not take (typed, but the turn never
    started), is `failed` and handed to `on_failed`, as the lockless background send this replaces did. Returns once
    nothing is queued, or once every envelope in `wait_for` has left `accepted` (typed by whoever held the lease).
    Waiting for the lease is bounded by `wait_s`; envelopes of `wait_for` still queued then fail with `typist_busy`
    (never silently left behind)."""
    mailbox = endpoint_mailbox(ctx, ep)
    transport = transport if transport is not None else transport_for(ctx, ep)
    lease = TypistLease(ctx, ep, mailbox, ttl_s=float(timeout_s) + 10.0)
    result = DrainResult()
    deadline = ctx.clock.monotonic() + max(0.0, float(wait_s))
    wanted = [str(e) for e in wait_for if e]
    while True:
        if wanted and not _still_waiting(mailbox, wanted):
            return result
        if not _typable(mailbox, ep, max_age_s, now_ms_of(ctx)):
            return result
        if lease.try_acquire():
            try:
                while True:
                    queue = _typable(mailbox, ep)
                    if not queue:
                        break
                    lease.try_acquire()  # renew for this send
                    head = queue[0]
                    age_s = (now_ms_of(ctx) - int(head.accepted_ms or head.envelope.created_ms or 0)) / 1000.0
                    if max_age_s and age_s > float(max_age_s) and head.envelope.env_id not in wanted:
                        stale = mailbox.transition(head.envelope.env_id, "expired", now_ms=now_ms_of(ctx),
                                                   error="expired", hold_reason="expired", clear_intent=True)
                        out_stale = DeliverOutcome(status="rejected", detail="expired")
                        result.failed.append((stale, out_stale))
                        if on_failed is not None:
                            on_failed(stale, out_stale)
                        continue
                    item, outcome = type_item_locked(ctx, mailbox, ep, queue[0], transport, timeout_s=timeout_s,
                                                     close=False)
                    if outcome.status == "typed" and (accept is None or accept(item, outcome)):
                        item = close_if_no_reply(mailbox, item, outcome, now_ms_of(ctx))
                        result.typed.append((item, outcome))
                        if on_typed is not None:
                            on_typed(item, outcome)
                        continue
                    if outcome.status == "typed" and accept is not None:
                        item, outcome, ok_retry = _retry_unstarted_item(
                            ctx, mailbox, ep, item, outcome, transport, lease, accept, timeout_s=timeout_s,
                        )
                        if ok_retry:
                            item = close_if_no_reply(mailbox, item, outcome, now_ms_of(ctx))
                            result.typed.append((item, outcome))
                            if on_typed is not None:
                                on_typed(item, outcome)
                            continue
                    if outcome.status == "typed":
                        # Typed, but it did not take (the turn never started and retries were exhausted).
                        outcome = DeliverOutcome(status="rejected", started_turn=False,
                                                 observed_turn=outcome.observed_turn,
                                                 observed_status_ms=outcome.observed_status_ms,
                                                 detail="started_false")
                        if item.state == "typed":
                            item = mailbox.transition(item.envelope.env_id, "failed", now_ms=now_ms_of(ctx),
                                                      error="started_false", hold_reason="started_false")
                    elif item.state == "accepted":
                        item = mailbox.transition(item.envelope.env_id, "failed", now_ms=now_ms_of(ctx),
                                                  error=outcome.status, hold_reason=outcome.detail or outcome.status,
                                                  clear_intent=True)
                    result.failed.append((item, outcome))
                    if on_failed is not None:
                        on_failed(item, outcome)
            finally:
                lease.release()
            continue  # anything queued just before the release is ours to type now
        if ctx.clock.monotonic() >= deadline:
            result.waited_out = True
            for env_id in _still_waiting(mailbox, wanted):
                cur = mailbox.transition(env_id, "failed", now_ms=now_ms_of(ctx), error="typist_busy",
                                         hold_reason="typist_busy")
                out = DeliverOutcome(status="rejected", detail="typist_busy")
                result.failed.append((cur, out))
                if on_failed is not None:
                    on_failed(cur, out)
            return result
        ctx.clock.sleep(LEASE_POLL_S)


def unblock_endpoint(
    ctx: Context,
    ep: Endpoint,
    keys: Sequence[str],
    *,
    transport: Any = None,
    lease: TypistLease | None = None,
) -> bool | None:
    """Press `keys` on a known prompt of `ep` under its lease: the caller's held `lease`, or one taken here without
    waiting. None: not tried, another typist is busy with this terminal right now (look again later; that is not a
    stuck terminal)."""
    if not keys:
        return False
    transport = transport if transport is not None else transport_for(ctx, ep)
    if lease is not None and lease.held:
        lease.try_acquire()
        return bool(transport.unblock_prompt(ep, list(keys)))
    own = TypistLease(ctx, ep, endpoint_mailbox(ctx, ep), ttl_s=15.0)
    if not own.try_acquire():
        return None
    try:
        return bool(transport.unblock_prompt(ep, list(keys)))
    finally:
        own.release()


def interrupt_endpoint(
    ctx: Context,
    ep: Endpoint,
    *,
    sender: Principal,
    recipient: LogicalAddress,
    project: str = "",
    cause: Mapping[str, Any] | None = None,
    timeout_s: float = 10.0,
    transport: Any = None,
) -> InterruptOutcome:
    """Interrupt `ep`'s current step: a `ctrl.interrupt` envelope (P0) kept in the endpoint's mailbox with the
    outcome, then `Transport.interrupt` (hc: Esc, or ctrl+c where the program reports no status; TUI: esc)."""
    now = now_ms_of(ctx)
    env = Envelope(
        env_id=new_env_id(now),
        idempotency_key="",
        schema_version=1,
        created_ms=now,
        kind="ctrl.interrupt",
        sender=sender,
        recipient=recipient,
        project=project or recipient.project,
        cause=dict(cause or {"kind": "interrupt"}),
        priority=P0_CONTROL,
        body={"text": ""},
    )
    # The record never stands between the interrupt and the terminal: a mailbox that cannot be written (a lock
    # held too long, a closed envelope) is not a reason not to interrupt, nor an error for the caller (escalate).
    mailbox: MailboxStore | None = None
    try:
        mailbox, item = enqueue_for_endpoint(ctx, ep, env)
        mailbox.update_hold_reason(item.envelope.env_id, "interrupting", now_ms=now)
    except (StoreError, OSError):
        mailbox = None
    transport = transport if transport is not None else transport_for(ctx, ep)
    out = transport.interrupt(ep, timeout_s=float(timeout_s))
    if mailbox is not None:
        done = now_ms_of(ctx)
        meta = {"interrupt": {"status": out.status, "key_sent": out.key_sent, "detail": out.detail}}
        to = "failed" if out.status in ("endpoint_gone", "partitioned", "unsupported") else "answered"
        with contextlib.suppress(StoreError, KeyError, OSError):
            cur = mailbox.get(env.env_id)
            if cur is not None and not cur.is_terminal():
                mailbox.transition(env.env_id, to, now_ms=done, meta=meta, hold_reason="",
                                   **({"error": out.status} if to == "failed" else {}))
    return out
