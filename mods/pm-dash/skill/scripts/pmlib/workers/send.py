"""Sending messages to workers: waiting until a herdr-core terminal's input is ready, queued sends a detached drain
types so the PM never blocks, and `update --send` back into a worker. Every keystroke into a worker terminal goes
through its own mailbox and typist lease (`messaging.typist`). Layer 3."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..agents.base import READY_MARKS
from ..caller import Caller
from ..context import Context
from ..errors import Refused
from ..events.deliver import Delivery, deliver_later, deliverer_env
from ..events.stalls import REPORTED_STATUSES, StallWatcher
from ..events.supervisor import supervisor_env
from ..home import project_slug
from ..ledger.ledger import Change, Ledger
from ..ledger.task import Task, hc_terminal_of
from ..osutil import shell_quote
from ..messaging.address import Endpoint, LogicalAddress, parse_legacy_endpoint
from ..messaging.envelope import P3_DIRECT, Envelope, new_env_id
from ..messaging.mailbox import MailboxItem
from ..messaging.principal import Principal, resolve_local_principal
from ..messaging.transport import DeliverOutcome
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..messaging.typist import (
    DRAIN_WAIT_S,
    TypistLease,
    drain_endpoint,
    endpoint_mailbox,
    enqueue_for_endpoint,
    now_ms_of,
    transport_for,
    turn_moved_on,
    type_item_locked,
    unblock_endpoint,
)
from ..terminals.screen import classify_stuck_screen, known_prompt_action
from .sessions import _worker_caller


@dataclass(frozen=True)
class SendBackResult:
    """Structured outcome of `Workers.send_back` (`update --send`)."""

    queued: bool
    message: str


def send_failure_reason(sent: Mapping[str, Any] | None, info: Mapping[str, Any] | None, term: str) -> str:
    """Human-readable reason why `hc send` to `term` did not start a turn."""
    err = sent.get("error") if isinstance(sent, Mapping) else None
    if isinstance(err, Mapping):
        why = err.get("message") or err.get("kind")
        if why:
            return str(why)
    state = info.get("state") if isinstance(info, Mapping) else None
    if state != "live":
        return f"hc:{term} is {state or 'gone'}" if term else "no herdr-core terminal of this machine"
    if isinstance(sent, Mapping) and "started" in sent and not sent.get("started"):
        return "turn did not start (started=false)"
    return "hc send failed or timed out"


def deliver_failure_reason(ctx: Context, out: DeliverOutcome | None, term: str) -> str:
    """Human-readable reason why a send to `term` did not go in, from the transport's outcome."""
    if out is None:
        return "hc send failed or timed out"
    if out.detail == "started_false" or (out.status == "typed" and out.started_turn is False):
        return "turn did not start (started=false)"
    if out.detail == "expired":
        return ctx.config.tr("it waited too long to be typed (the send that queued it stopped)",
                             "排队太久仍未打入（排它的发送进程已停止）")
    if out.detail == "typist_busy":
        return ctx.config.tr(f"another sender kept typing into hc:{term}", f"另一个发送方一直占着 hc:{term} 在打字")
    if out.status == "endpoint_gone":
        return f"hc:{term} is {out.detail or 'gone'}" if term else "no herdr-core terminal of this machine"
    if out.status == "blocked_prompt":
        return out.detail or f"hc:{term} is blocked on a prompt"
    if out.status == "timeout_uncertain":
        return "hc send failed or timed out"
    return out.detail or out.status or "hc send failed or timed out"


def worker_endpoint(term: str, *, kind: str = "") -> Endpoint | None:
    """The endpoint of herdr-core terminal `term` (`t5`, `hc:t5`, `<machine>/t5`)."""
    t = str(term or "").strip()
    if not t:
        return None
    return parse_legacy_endpoint(t if t.startswith("hc:") else f"hc:{t}", agent_kind=kind, runtime_hint="hc")


def terminal_envelope(
    ctx: Context,
    text: str,
    *,
    kind: str = "cmd.send",
    task_id: str = "",
    repo: str = "",
    target: str = "",
    priority: int = P3_DIRECT,
    idempotency_key: str = "",
    cause: Mapping[str, Any] | None = None,
    sender: Principal | None = None,
) -> Envelope:
    """An envelope for a worker / reviewer / helper terminal: `text` as the body, who sends it, and the task and
    project it is about (`cause`, read by whoever types it to run that send's reactions)."""
    now = now_ms_of(ctx)
    project = project_slug(repo) if repo else ""
    who = sender if sender is not None else resolve_local_principal(ctx, project)
    why = {"kind": kind.split(".", 1)[-1], "task_id": task_id, "repo": repo, **dict(cause or {})}
    return Envelope(
        env_id=new_env_id(now),
        idempotency_key=idempotency_key,
        schema_version=1,
        created_ms=now,
        kind=kind,
        sender=who,
        recipient=LogicalAddress.worker(task_id or target or "terminal", project),
        project=project,
        cause=why,
        priority=priority,
        body={"text": text},
    )


def took_in(ctx: Context, ep: Endpoint, item: MailboxItem, out: DeliverOutcome) -> bool:
    """Whether a typed send went in: its turn started, the program reports no status, or the terminal moved on
    since (a later turn, or working: the agent queued it mid-turn). An idle terminal whose turn did not start
    dropped it (agy can): that is not delivered, as the lockless send this replaces judged."""
    if out.started_turn is not False:
        return True
    info = ctx.hc.get_raw(ep.hc_target, errors=True) if ep.runtime == "hc" and ep.hc_target else None
    if not isinstance(info, Mapping) or info.get("error") or info.get("state") != "live":
        return False
    pre_turn = int(item.meta.get("typed_pre_turn") or 0)
    status = info.get("status") if isinstance(info.get("status"), Mapping) else {}
    return int(info.get("turn") or 0) > pre_turn or status.get("state") == "working"


def _deliver_later_for(ctx: Context, repo: str) -> None:
    """Start the project's deliverer when its PM is a desktop-app one (as `Workers._deliver_later`)."""
    if not repo:
        return
    if getattr(ctx, "_legacy", False):
        deliver_later(str(repo))
    elif ProjectRegistry(ctx).app_pm(repo):
        Delivery(ctx, repo).ensure_running()


def send_failed_for(ctx: Context, term: str, why: str, *, task_id: str = "", repo: str = "",
                    quiet: bool = False) -> None:
    """A queued send into `term` did not go in: tell whoever has to know, as the lockless background send did. A
    worker-executed merge approval falls back to an exec helper; else the task (or the project) records why and wakes
    a desktop-app PM. `quiet` (the user's own words from the app): only a note on the task, where they look."""
    resolved_repo = repo or ""
    task = ctx.store.task(task_id) if task_id else None
    if quiet:
        if isinstance(task, dict) and task:
            msg = ctx.config.tr(f"your message to hc:{term} was not delivered ({why})",
                                f"你发给 hc:{term} 的消息没送到（{why}）")
            Ledger(ctx).change(task_id, lambda cur, ch: (ch.note_on(cur.raw, msg, source="harness"), cur.raw)[1])
        return
    if isinstance(task, dict) and task:
        resolved_repo = resolved_repo or task.get("repo") or ""
        la = task.get("land_approved")
        if (isinstance(la, dict) and la.get("executor") == "worker"
                and not task.get("landed") and task.get("status") not in REPORTED_STATUSES):
            if StallWatcher(ctx).fallback_land_to_helper(task, reason=f"approve send to hc:{term} failed ({why})",
                                                         term=term):
                return
        wake = bool(resolved_repo and ProjectRegistry(ctx).app_pm(resolved_repo))
        msg = ctx.config.tr(
            f"async send to hc:{term} failed ({why}); check or triage with `pm.py triage {task_id}`",
            f"异步发送到 hc:{term} 失败（{why}）；可用 `pm.py triage {task_id}` 交给 helper 排查",
        )
        Ledger(ctx).change(
            task_id,
            lambda cur, ch: (
                ch.note_on(cur.raw, msg, by="harness", source="harness", **({"wake": True} if wake else {})),
                cur.raw,
            )[1],
        )
        if wake:
            _deliver_later_for(ctx, resolved_repo)
    elif resolved_repo:
        wake = bool(ProjectRegistry(ctx).app_pm(resolved_repo))
        msg = ctx.config.tr(f"async send to hc:{term} failed ({why})", f"异步发送到 hc:{term} 失败（{why}）")
        Conversation(ctx, resolved_repo).record(
            "event", by=f"hc:{term}", source="harness", text=msg, **({"wake": True} if wake else {}),
        )
        if wake:
            _deliver_later_for(ctx, resolved_repo)


def send_reactions_for(
    ctx: Context, term: str, *, skip: Sequence[str] = (),
) -> tuple[Callable[[MailboxItem, DeliverOutcome], None], Callable[[MailboxItem, DeliverOutcome], None]]:
    """`(on_typed, on_failed)` for a drain of `term`: each send's own reactions, read from its envelope's `cause`,
    whoever types it (the drain it queued, another one, or a synchronous sender ahead of it). `skip`: the caller's
    own envelopes (a synchronous sender reports those itself)."""
    own = set(skip)

    def _cause(item: MailboxItem) -> dict[str, Any]:
        return dict(item.envelope.cause) if isinstance(item.envelope.cause, Mapping) else {}

    def on_typed(item: MailboxItem, _out: DeliverOutcome) -> None:
        why = _cause(item)
        task_id = str(why.get("task_id") or "")
        if item.envelope.env_id in own or not (why.get("round") and task_id):
            return
        with contextlib.suppress(Exception, SystemExit):
            if (ctx.store.task(task_id) or {}).get("status") == "in_progress":
                StallWatcher(ctx).round_handed(task_id, term, int(item.meta.get("typed_pre_turn") or 0))

    def on_failed(item: MailboxItem, out: DeliverOutcome) -> None:
        why = _cause(item)
        if item.envelope.env_id in own or not why.get("react"):
            return
        send_failed_for(ctx, term, deliver_failure_reason(ctx, out, term),
                        task_id=str(why.get("task_id") or ""), repo=str(why.get("repo") or ""),
                        quiet=bool(why.get("quiet")))

    return on_typed, on_failed


def deliver_now_for(
    ctx: Context,
    ep: Endpoint,
    env: Envelope,
    *,
    timeout_s: float = 70.0,
    wait_s: float = DRAIN_WAIT_S,
    accept: Any = None,
    transport: Any = None,
) -> DeliverOutcome:
    """Queue `env` for `ep` and type it now under the endpoint's lease (with whatever was queued before it),
    waiting for another typist at most `wait_s`. Returns the outcome of `env`'s own send."""
    enqueue_for_endpoint(ctx, ep, env)
    on_typed, on_failed = send_reactions_for(ctx, ep.hc_target or ep.terminal, skip=[env.env_id])
    res = drain_endpoint(ctx, ep, wait_for=[env.env_id], wait_s=wait_s, timeout_s=timeout_s, accept=accept,
                         transport=transport, on_typed=on_typed, on_failed=on_failed)
    out = res.outcome_for(env.env_id)
    if out is not None:
        return out
    cur = endpoint_mailbox(ctx, ep).get(env.env_id)
    if cur is not None and cur.state in ("typed", "consumed", "answered"):
        started = cur.meta.get("typed_started")
        return DeliverOutcome(status="typed", started_turn=started if isinstance(started, bool) else None,
                              detail=f"already_{cur.state}")
    return DeliverOutcome(status="rejected", detail=(cur.last_error if cur is not None else "") or "not_sent")


def _round_handed_for(ctx: Context, task_id: str, term: str, turn: int | None = None) -> None:
    if turn is None:
        info = ctx.hc.get_raw(term) or {}
        turn = info.get("turn") or 0

    def _set_round(cur: Task | None, _ch: Change) -> dict[str, Any]:
        assert cur is not None
        raw = cur.raw
        raw["round"] = {"terminal": term, "at": ctx.clock.now(), "turn": turn}
        return raw

    Ledger(ctx).change(task_id, _set_round)


def send_when_ready_for(
    ctx: Context,
    term: str,
    text: str,
    *,
    tries: int = 8,
    pause: float = 3,
    strict: bool = False,
    trust: str | Path | None = None,
    stop_on_exit: bool = False,
    kind: str = "",
    seen: dict[str, Any] | None = None,
) -> bool:
    """Type text into an agent once its input is ready; a send that comes too early is refused."""
    if getattr(ctx, "_legacy", False) and send_when_ready is not _DEFAULT_SEND_WHEN_READY:
        return bool(send_when_ready(
            term, text, tries=tries, pause=pause, strict=strict, trust=trust,
            stop_on_exit=stop_on_exit, kind=kind, seen=seen,
        ))
    return _send_when_ready_impl(
        ctx, term, text, tries=tries, pause=pause, strict=strict, trust=trust,
        stop_on_exit=stop_on_exit, kind=kind, seen=seen,
    )


def _send_when_ready_impl(
    ctx: Context,
    term: str,
    text: str,
    *,
    tries: int = 8,
    pause: float = 3,
    strict: bool = False,
    trust: str | Path | None = None,
    stop_on_exit: bool = False,
    kind: str = "",
    seen: dict[str, Any] | None = None,
) -> bool:
    """The brief goes in as a `cmd.brief` envelope of the terminal's own mailbox, and the prompt keys and the
    send happen only while this holds the terminal's typist lease (a look where another typist has it is skipped;
    once taken, it is kept until this returns, so what others queue meanwhile goes in after the brief). The brief
    is queued only when it is typed: no other drain of the terminal can type it before the terminal is ready.
    A send that typed without starting a turn is checked on the next look: taken once the terminal moved on, else
    typed again (the same envelope, as the seat's opening prompt does)."""
    ep = worker_endpoint(term, kind=kind)
    if ep is None:
        return False
    allow_trust = ctx.git.is_owned_worktree(trust)
    handled_counts = {"trust": 0, "update": 0}
    env = terminal_envelope(ctx, text, kind="cmd.brief", target=term, cause={"retry_unstarted": True})
    mailbox = endpoint_mailbox(ctx, ep)
    env_id = env.env_id
    transport = transport_for(ctx, ep)
    lease = TypistLease(ctx, ep, mailbox, ttl_s=float(pause) * 2 + 80.0)

    def _done(info: Mapping[str, Any]) -> bool:
        cur = mailbox.get(env_id)
        if cur is not None and cur.state == "typed":
            mailbox.transition(env_id, "answered", now_ms=now_ms_of(ctx), meta={"closed": "taken"})
        if seen is not None:
            seen["turn"] = info.get("turn") or 0
        return True

    try:
        for attempt in range(tries):
            ctx.clock.sleep(pause)
            info = ctx.hc.get_raw(term) or {}
            if stop_on_exit and info.get("state") not in (None, "live"):
                break
            cur = mailbox.get(env_id)  # None until the first look that types it
            if cur is not None and cur.is_terminal():
                return cur.state == "answered"
            if cur is not None and cur.state == "typed" and turn_moved_on(
                    info, int(cur.meta.get("typed_pre_turn") or 0), int(cur.meta.get("typed_pre_status_ms") or 0)):
                return _done(info)
            status = info.get("status")
            screen = ""
            if not status or (status or {}).get("state") in ("blocked", "error") or allow_trust:
                screen = ctx.hc.read(term)
            if screen:
                pkind, keys = known_prompt_action(screen, allow_trust=allow_trust)
                if keys and handled_counts.get(pkind, 0) < 2:
                    if lease.try_acquire() and unblock_endpoint(ctx, ep, keys, transport=transport, lease=lease):
                        handled_counts[pkind] = handled_counts.get(pkind, 0) + 1
                    continue
            # Never blindly type into a blocking startup dialog or error screen even when strict=False (e.g. agy).
            blocking_dialog = bool(screen and classify_stuck_screen(screen)["kind"] in (
                "trust", "update", "hook_review", "mcp", "permission", "quota", "auth"))
            # Without strict, a program that reports no status at all gets the text after a short wait.
            ready = status.get("state") in ("idle", "done") if status else (not strict and not blocking_dialog and attempt >= 2)
            marked = False
            if not ready and not blocking_dialog and kind and not (status or {}).get("state"):
                if not screen:
                    screen = ctx.hc.read(term)
                marked = any(m in screen for m in READY_MARKS.get(kind, ()))
            if not (ready or marked) or not lease.try_acquire():
                continue
            if cur is None:
                _mailbox, cur = enqueue_for_endpoint(ctx, ep, env)
            elif cur.state == "typed":  # typed earlier without its turn starting, and nothing moved since
                cur = mailbox.transition(env_id, "accepted", now_ms=now_ms_of(ctx), hold_reason="retry_unstarted",
                                         clear_intent=True)
            if cur.state != "accepted":
                continue
            cur, out = type_item_locked(ctx, mailbox, ep, cur, transport, timeout_s=70.0, close=False)
            if out.status != "typed":
                continue
            # A program that reports no status cannot say a turn started: the text went in, it is not typed again.
            if out.started_turn is not False or marked:
                return _done(info)
        # Given up: the brief fails while the lease is still held, so no other drain types it later.
        cur = mailbox.get(env_id)
        if cur is not None and cur.state in ("accepted", "typed"):
            mailbox.transition(cur.envelope.env_id, "failed", now_ms=now_ms_of(ctx), error="not_ready",
                               hold_reason="not_ready", clear_intent=True)
        return False
    finally:
        lease.release()


def send_async_later_for(
    ctx: Context,
    term: str,
    message: str,
    *,
    task_id: str = "",
    repo: str = "",
    pre_turn: int | None = None,
    timeout: int = 180,
    kind: str = "cmd.send",
    idempotency_key: str = "",
) -> bool:
    """Queue `message` for herdr-core terminal `term` and leave typing it to a detached drain of that terminal's
    mailbox, so the PM never blocks."""
    if getattr(ctx, "_legacy", False) and send_async_later is not _DEFAULT_SEND_ASYNC_LATER:
        return bool(send_async_later(
            term, message, task_id=task_id, repo=repo, pre_turn=pre_turn, timeout=timeout,
        ))
    return _send_async_later_impl(
        ctx, term, message, task_id=task_id, repo=repo, pre_turn=pre_turn, timeout=timeout, kind=kind,
        idempotency_key=idempotency_key,
    )


def queue_send_for(
    ctx: Context,
    term: str,
    env: Envelope,
    *,
    timeout: int = 180,
) -> Envelope:
    """Queue `env` for herdr-core terminal `term` and start a detached `pm.py _drain-endpoint` that types it under
    the terminal's lease (and runs that send's reactions: the round handed, or the PM told it failed)."""
    ep = worker_endpoint(term)
    if ep is None:
        raise Refused(ctx.config.tr(f"no herdr-core terminal {term!r}", f"没有 herdr-core 终端 {term!r}"))
    _mailbox, item = enqueue_for_endpoint(ctx, ep, env)
    args = ["_drain-endpoint", term, "--env", item.envelope.env_id, "--timeout", str(int(timeout))]
    env_vars = deliverer_env() if getattr(ctx, "_legacy", False) else supervisor_env(ctx.procs.clean_session_env())
    ctx.procs.spawn_pm(args, env=env_vars, cwd=ctx.home.root)
    return item.envelope


def _send_async_later_impl(
    ctx: Context,
    term: str,
    message: str,
    *,
    task_id: str = "",
    repo: str = "",
    pre_turn: int | None = None,
    timeout: int = 180,
    kind: str = "cmd.send",
    idempotency_key: str = "",
) -> bool:
    del pre_turn  # the drain records the terminal's turn right before it types (the C3 intent)
    env = terminal_envelope(ctx, str(message), kind=kind, task_id=task_id, repo=repo, target=term,
                            idempotency_key=idempotency_key, cause={"round": bool(task_id), "react": True})
    queue_send_for(ctx, term, env, timeout=timeout)
    return True


def send_ready_later_for(
    ctx: Context,
    term: str,
    message_file: str | Path,
    *,
    kind: str = "",
    trust: str = "",
    strict: bool = False,
    stop_on_exit: bool = False,
    task_id: str = "",
    repo: str = "",
    unlink: bool = False,
    helper_owner_kind: str = "",
    helper_owner_id: str = "",
    helper_slug: str = "",
    helper_name: str = "",
) -> bool:
    """Run `send_when_ready` in a detached background process so PM startup commands return immediately."""
    if getattr(ctx, "_legacy", False) and send_ready_later is not _DEFAULT_SEND_READY_LATER:
        return bool(send_ready_later(
            term, message_file, kind=kind, trust=trust, strict=strict, stop_on_exit=stop_on_exit,
            task_id=task_id, repo=repo, unlink=unlink, helper_owner_kind=helper_owner_kind,
            helper_owner_id=helper_owner_id, helper_slug=helper_slug, helper_name=helper_name,
        ))
    return _send_ready_later_impl(
        ctx, term, message_file, kind=kind, trust=trust, strict=strict, stop_on_exit=stop_on_exit,
        task_id=task_id, repo=repo, unlink=unlink, helper_owner_kind=helper_owner_kind,
        helper_owner_id=helper_owner_id, helper_slug=helper_slug, helper_name=helper_name,
    )


def _send_ready_later_impl(
    ctx: Context,
    term: str,
    message_file: str | Path,
    *,
    kind: str = "",
    trust: str = "",
    strict: bool = False,
    stop_on_exit: bool = False,
    task_id: str = "",
    repo: str = "",
    unlink: bool = False,
    helper_owner_kind: str = "",
    helper_owner_id: str = "",
    helper_slug: str = "",
    helper_name: str = "",
) -> bool:
    args = ["_deliver-ready", term, "--file", str(message_file)]
    if kind:
        args += ["--kind", kind]
    if trust:
        args += ["--trust", str(trust)]
    if strict:
        args.append("--strict")
    if stop_on_exit:
        args.append("--stop-on-exit")
    if unlink:
        args.append("--unlink")
    if task_id:
        args += ["--task", task_id]
    if repo:
        args += ["--repo", repo]
    if helper_owner_kind:
        args += ["--helper-owner-kind", helper_owner_kind, "--helper-owner-id", helper_owner_id,
                 "--helper-slug", helper_slug, "--helper-name", helper_name]
    env = deliverer_env() if getattr(ctx, "_legacy", False) else supervisor_env(ctx.procs.clean_session_env())
    ctx.procs.spawn_pm(args, env=env, cwd=ctx.home.root)
    return True


def send_back_for(ctx: Context, task: Any, text: str, *, wait: bool = False) -> SendBackResult:
    """`update --send`: deliver the note into the task's worker, as `[from <this pane>] <note>`, once the entry is
    written. From a PM terminal this runs asynchronously by default; pass `wait=True` to wait synchronously.
    Raises `Refused(..., code=1, stream="stdout")` when the worker is gone or send fails."""
    raw = task.raw if isinstance(task, Task) else task
    term = hc_terminal_of(raw)
    message = f"[from {ctx.pane or 'pm.py'}] {text}"
    info = (ctx.hc.get_raw(term) or {}) if term and "/" not in term else {}
    if info.get("state") == "live" and not wait and _worker_caller(ctx).is_pm_caller(raw):
        send_async_later_for(
            ctx, term, message, task_id=raw["id"], repo=raw.get("repo") or "",
            pre_turn=info.get("turn") or 0, timeout=180,
        )
        return SendBackResult(
            queued=True,
            message=ctx.config.tr(f"{raw['id']}: queued async send to hc:{term}", f"{raw['id']}：已异步发送给 hc:{term}"),
        )
    out: DeliverOutcome | None = None
    ep = worker_endpoint(term) if term else None
    if info.get("state") == "live" and ep is not None:
        env = terminal_envelope(ctx, message, task_id=raw["id"], repo=raw.get("repo") or "", target=term)
        out = deliver_now_for(ctx, ep, env, timeout_s=180, accept=lambda it, o: took_in(ctx, ep, it, o))
    if out is not None and out.status == "typed":
        if Ledger(ctx).load(raw["id"]).get("status") == "in_progress":
            _round_handed_for(ctx, raw["id"], term, info.get("turn") or 0)
        return SendBackResult(
            queued=False,
            message=ctx.config.tr(f"{raw['id']}: sent to hc:{term}", f"{raw['id']}：已发给 hc:{term}"),
        )
    why = deliver_failure_reason(ctx, out, term) if out is not None else send_failure_reason({}, info, term)
    target = term or raw.get("pane") or "<terminal>"
    raise Refused(
        ctx.config.tr(
            f"{raw['id']}: the note was recorded but not sent ({why}). Send it by hand: pm.py send {target} "
            f"{shell_quote(message)}",
            f"{raw['id']}：已记入台账，但没发出去（{why}）。手动发送：pm.py send {target} {shell_quote(message)}",
        ),
        code=1,
        stream="stdout",
    )


# --- Legacy module-level shims (Stages 1-5 compatibility) ---


def send_when_ready(
    term: str,
    text: str,
    tries: int = 8,
    pause: float = 3,
    strict: bool = False,
    trust: str | Path | None = None,
    stop_on_exit: bool = False,
    kind: str = "",
    seen: dict[str, Any] | None = None,
) -> bool:
    return _send_when_ready_impl(
        Context.from_env(), term, text, tries=tries, pause=pause, strict=strict,
        trust=trust, stop_on_exit=stop_on_exit, kind=kind, seen=seen,
    )


_DEFAULT_SEND_WHEN_READY = send_when_ready


def send_async_later(
    term: str,
    message: str,
    *,
    task_id: str = "",
    repo: str = "",
    pre_turn: int | None = None,
    timeout: int = 180,
) -> bool:
    return _send_async_later_impl(
        Context.from_env(), term, message, task_id=task_id, repo=repo, pre_turn=pre_turn, timeout=timeout,
    )


_DEFAULT_SEND_ASYNC_LATER = send_async_later


def send_ready_later(
    term: str,
    message_file: str | Path,
    *,
    kind: str = "",
    trust: str = "",
    strict: bool = False,
    stop_on_exit: bool = False,
    task_id: str = "",
    repo: str = "",
    unlink: bool = False,
    helper_owner_kind: str = "",
    helper_owner_id: str = "",
    helper_slug: str = "",
    helper_name: str = "",
) -> bool:
    return _send_ready_later_impl(
        Context.from_env(), term, message_file, kind=kind, trust=trust, strict=strict,
        stop_on_exit=stop_on_exit, task_id=task_id, repo=repo, unlink=unlink,
        helper_owner_kind=helper_owner_kind, helper_owner_id=helper_owner_id,
        helper_slug=helper_slug, helper_name=helper_name,
    )


_DEFAULT_SEND_READY_LATER = send_ready_later
