"""Sending messages to workers: waiting until a herdr-core terminal's input is ready, detached background sends
so the PM never blocks, and `update --send` back into a worker. Layer 3."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Any, Mapping

from ..agents.base import READY_MARKS
from ..caller import Caller
from ..context import Context
from ..errors import Refused
from ..events.deliver import deliverer_env
from ..ledger.ledger import Change, Ledger
from ..ledger.task import Task, hc_terminal_of
from ..osutil import shell_quote
from ..store import replace_task_file, write_atomic
from ..terminals.screen import classify_stuck_screen, known_prompt_action
from .sessions import _worker_caller


@dataclass(frozen=True)
class SendBackResult:
    """Structured outcome of `Workers.send_back` (`update --send`)."""

    queued: bool
    message: str


def send_succeeded(sent: Mapping[str, Any] | None, info: Mapping[str, Any] | None = None) -> bool:
    """Whether an `hc send` reply means the target accepted the message.

    A terminal that reports `status` (claude, codex, agy, ...) must report `started: True`;
    only a terminal with no status at all accepts `started` present with `status is None` and no error.
    """
    if not isinstance(sent, Mapping) or sent.get("error"):
        return False
    if sent.get("started"):
        return True
    has_status = bool((info or {}).get("status"))
    return (not has_status) and ("started" in sent) and (sent.get("status") is None)


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
    allow_trust = ctx.git.is_owned_worktree(trust)
    handled_counts = {"trust": 0, "update": 0}
    for attempt in range(tries):
        ctx.clock.sleep(pause)
        info = ctx.hc.get_raw(term) or {}
        if stop_on_exit and info.get("state") not in (None, "live"):
            return False
        status = info.get("status")
        screen = ""
        if not status or (status or {}).get("state") in ("blocked", "error") or allow_trust:
            screen = ctx.hc.read(term)
        if screen:
            pkind, keys = known_prompt_action(screen, allow_trust=allow_trust)
            if keys and handled_counts.get(pkind, 0) < 2:
                if ctx.hc.keys(term, *keys) is not None:
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
        sent = (ctx.hc.send(term, text) or {}) if ready or marked else {}
        # A program that reports no status cannot say a turn started: the text went in, it is not typed again.
        if sent.get("started") or (not status and "started" in sent and sent.get("status") is None) or \
                (marked and sent and not sent.get("error")):
            if seen is not None:
                seen["turn"] = info.get("turn") or 0
            return True
    return False


def send_async_later_for(
    ctx: Context,
    term: str,
    message: str,
    *,
    task_id: str = "",
    repo: str = "",
    pre_turn: int | None = None,
    timeout: int = 180,
) -> bool:
    """Deliver `message` to herdr-core terminal `term` in a detached background process so the PM never blocks."""
    if getattr(ctx, "_legacy", False) and send_async_later is not _DEFAULT_SEND_ASYNC_LATER:
        return bool(send_async_later(
            term, message, task_id=task_id, repo=repo, pre_turn=pre_turn, timeout=timeout,
        ))
    return _send_async_later_impl(
        ctx, term, message, task_id=task_id, repo=repo, pre_turn=pre_turn, timeout=timeout,
    )


def _send_async_later_impl(
    ctx: Context,
    term: str,
    message: str,
    *,
    task_id: str = "",
    repo: str = "",
    pre_turn: int | None = None,
    timeout: int = 180,
) -> bool:
    tmp_dir = ctx.home.tmp
    tmp_dir.mkdir(parents=True, exist_ok=True)
    msg_file = tmp_dir / f"send-{os.getpid()}-{time.time_ns()}.txt"
    write_atomic(msg_file, str(message).encode("utf-8"), replace_fn=replace_task_file)
    args = ["_deliver-send", term, "--file", str(msg_file), "--unlink", "--timeout", str(int(timeout))]
    if task_id:
        args += ["--task", task_id]
    if repo:
        args += ["--repo", repo]
    if pre_turn is not None:
        args += ["--pre-turn", str(int(pre_turn))]
    env = deliverer_env() if getattr(ctx, "_legacy", False) else ctx.procs.clean_session_env()
    ctx.procs.spawn_pm(args, env=env, cwd=ctx.home.root)
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
    env = deliverer_env() if getattr(ctx, "_legacy", False) else ctx.procs.clean_session_env()
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
    sent = (ctx.hc.send(term, message, timeout=180, errors=True) or {}) if info.get("state") == "live" else {}
    if send_succeeded(sent, info):
        if Ledger(ctx).load(raw["id"]).get("status") == "in_progress":
            _round_handed_for(ctx, raw["id"], term, info.get("turn") or 0)
        return SendBackResult(
            queued=False,
            message=ctx.config.tr(f"{raw['id']}: sent to hc:{term}", f"{raw['id']}：已发给 hc:{term}"),
        )
    why = send_failure_reason(sent, info, term)
    target = term or raw.get("pane") or "<terminal>"
    raise Refused(
        ctx.config.tr(
            f"{raw['id']}: the note was recorded but not sent ({why}). Send it by hand: hc send {target} "
            f"{shell_quote(message)}",
            f"{raw['id']}：已记入台账，但没发出去（{why}）。手动发送：hc send {target} {shell_quote(message)}",
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
