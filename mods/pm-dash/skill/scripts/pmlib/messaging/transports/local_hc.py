"""`LocalHcTransport`: local `hc` CLI/host implementation of `Transport` (§5.1, §5.3). Layer 2."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from ...context import Context
from ...terminals.hc import _exec_bin, send_succeeded
from ..address import Endpoint
from ..envelope import format_deliver_text
from ..mailbox import MailboxItem
from ..transport import (
    AsyncDeliverHandle,
    DeliverOutcome,
    InterruptOutcome,
    ObserveBatch,
    TransportCapabilities,
)


def _error_kind(res: Mapping[str, Any] | None) -> tuple[str, str]:
    if not isinstance(res, Mapping):
        return "", ""
    err = res.get("error")
    if isinstance(err, Mapping):
        kind = str(err.get("kind") or "").strip().lower()
        msg = str(err.get("message") or kind).strip()
        return kind, msg
    if isinstance(err, str) and err.strip():
        return err.strip().lower(), err.strip()
    return "", ""


def _status_state_of(info: Mapping[str, Any] | None) -> str:
    if not isinstance(info, Mapping):
        return ""
    raw = info.get("status")
    if isinstance(raw, Mapping):
        return str(raw.get("state") or "").strip().lower()
    if isinstance(raw, str):
        return raw.strip().lower()
    return ""


def _can_report_status(info: Mapping[str, Any] | None) -> bool:
    if not isinstance(info, Mapping):
        return False
    if info.get("reported") is False:
        return False
    return bool(_status_state_of(info))


def _map_send_reply(
    sent: Mapping[str, Any] | None,
    pre_info: Mapping[str, Any] | None,
    post_info: Mapping[str, Any] | None,
    *,
    pre_turn: int | None = None,
    pre_status_ms: int | None = None,
    timed_out: bool = False,
) -> DeliverOutcome:
    """Translate an `hc send --json` reply (including `started=false` & timeouts) into `DeliverOutcome`."""
    kind, detail = _error_kind(sent)
    if kind:
        if kind == "blocked":
            return DeliverOutcome(status="blocked_prompt", detail=detail or "blocked")
        if kind == "status_mismatch":
            return DeliverOutcome(status="status_mismatch", detail=detail or "status_mismatch")
        if kind in ("not_found", "finished"):
            return DeliverOutcome(status="endpoint_gone", detail=detail or kind)
        if kind in ("unavailable", "machine_unknown"):
            return DeliverOutcome(status="partitioned", detail=detail or kind)
        if kind in ("invalid_params", "config", "cancelled"):
            return DeliverOutcome(status="rejected", detail=detail or kind)
        return DeliverOutcome(status="rejected", detail=detail or kind)

    if timed_out or sent is None:
        # Check post_info for turn/status_ms advancement before declaring timeout_uncertain.
        if isinstance(post_info, Mapping):
            post_turn = int(post_info.get("turn") or 0)
            post_sms = int(post_info.get("status_ms") or 0)
            post_state = _status_state_of(post_info)
            if (pre_turn is not None and post_turn > pre_turn) or (
                post_state == "working" and pre_status_ms is not None and post_sms > pre_status_ms
            ):
                return DeliverOutcome(
                    status="typed",
                    started_turn=True,
                    observed_turn=post_turn,
                    observed_status_ms=post_sms,
                    detail="reconciled_after_timeout",
                )
        return DeliverOutcome(status="timeout_uncertain", detail="hc send timed out or returned no reply")

    post_ref = post_info if isinstance(post_info, Mapping) else pre_info
    obs_turn = int(post_ref.get("turn") or 0) if isinstance(post_ref, Mapping) else None
    obs_sms = int(post_ref.get("status_ms") or 0) if isinstance(post_ref, Mapping) else None
    has_status = bool(_status_state_of(pre_info)) and (pre_info or {}).get("reported") is not False

    if send_succeeded(sent, pre_info):
        started_val = sent.get("started")
        if not has_status and sent.get("status") is None:
            started_flag: bool | None = None
        else:
            started_flag = bool(started_val) if started_val is not None else True
        return DeliverOutcome(
            status="typed",
            started_turn=started_flag,
            observed_turn=obs_turn,
            observed_status_ms=obs_sms,
            detail="ok",
        )

    # `started=false` / `started=null`: reconcile via `pre_turn` / `pre_status_ms` / live terminal info.
    if "started" in sent and not sent.get("error"):
        if isinstance(post_info, Mapping):
            post_turn = int(post_info.get("turn") or 0)
            post_sms = int(post_info.get("status_ms") or 0)
            post_state = _status_state_of(post_info)
            if post_info.get("state") in ("exited", "finished", "removed"):
                return DeliverOutcome(status="endpoint_gone", detail=str(post_info.get("state") or "exited"))
            if (pre_turn is not None and post_turn > pre_turn) or (
                post_state == "working" and (pre_status_ms is None or post_sms > pre_status_ms)
            ):
                return DeliverOutcome(
                    status="typed",
                    started_turn=True,
                    observed_turn=post_turn,
                    observed_status_ms=post_sms,
                    detail="reconciled_started_false",
                )
            # Stateless terminal (`reported == False` or `status is None`): bytes went to PTY without status change.
            if (
                post_info.get("reported") is False
                or post_info.get("status") is None
                or ("status" in sent and sent.get("status") is None)
            ):
                return DeliverOutcome(
                    status="typed",
                    started_turn=None,
                    observed_turn=post_turn,
                    observed_status_ms=post_sms,
                    detail="stateless_typed",
                )
        # Even when status-reporting terminal returned started=false (e.g. entered mid-turn or queued by agent),
        # `hc send` wrote to PTY without error: treat as typed(started_turn=False) so caller reconciles with hooks/W6
        # rather than misreporting "Not sent: hc send could not deliver right now"!
        return DeliverOutcome(
            status="typed",
            started_turn=False,
            observed_turn=obs_turn,
            observed_status_ms=obs_sms,
            detail="started_false_typed",
        )

    return DeliverOutcome(status="timeout_uncertain", detail="unrecognized hc send reply")


class _ImmediateDeliverHandle:
    """Completed `AsyncDeliverHandle` used when `ctx.hc` is mocked/synchronous."""

    def __init__(self, outcome: DeliverOutcome, started_ms: int) -> None:
        self._outcome = outcome
        self._started_ms = started_ms

    @property
    def started_ms(self) -> int:
        return self._started_ms

    def poll(self) -> DeliverOutcome | None:
        return self._outcome

    def cancel(self) -> None:
        return None


class _SubprocessDeliverHandle:
    """Non-blocking subprocess `AsyncDeliverHandle` for real `hc send` (never stalls supervisor loop, RS-4)."""

    def __init__(
        self,
        proc: subprocess.Popen[str],
        *,
        ctx: Context,
        term: str,
        pre_info: Mapping[str, Any] | None,
        pre_turn: int | None,
        pre_status_ms: int | None,
        started_ms: int,
        timeout_s: float,
    ) -> None:
        self._proc = proc
        self._ctx = ctx
        self._term = term
        self._pre_info = pre_info
        self._pre_turn = pre_turn
        self._pre_status_ms = pre_status_ms
        self._started_ms = started_ms
        self._timeout_ms = int(max(1.0, float(timeout_s)) * 1000)
        self._done: DeliverOutcome | None = None

    @property
    def started_ms(self) -> int:
        return self._started_ms

    def poll(self) -> DeliverOutcome | None:
        if self._done is not None:
            return self._done
        rc = self._proc.poll()
        now_ms = int(float(self._ctx.clock.time()) * 1000)
        if rc is None:
            if (now_ms - self._started_ms) < self._timeout_ms:
                return None
            with contextlib.suppress(OSError):
                self._proc.kill()
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                self._proc.wait(timeout=1.0)
            post_info = self._ctx.hc.get_raw(self._term, errors=True)
            self._done = _map_send_reply(
                None,
                self._pre_info,
                post_info,
                pre_turn=self._pre_turn,
                pre_status_ms=self._pre_status_ms,
                timed_out=True,
            )
            return self._done

        stdout, stderr = "", ""
        with contextlib.suppress(OSError, ValueError):
            stdout, stderr = self._proc.communicate(timeout=0.5)
        parsed: dict[str, Any] | None = None
        raw = (stderr if rc != 0 else stdout) or stdout or stderr or ""
        with contextlib.suppress(ValueError):
            obj = json.loads(raw)
            if isinstance(obj, dict):
                parsed = obj
        post_info = None
        if parsed is None or (not send_succeeded(parsed, self._pre_info) and not parsed.get("error")):
            post_info = self._ctx.hc.get_raw(self._term, errors=True)
        self._done = _map_send_reply(
            parsed,
            self._pre_info,
            post_info,
            pre_turn=self._pre_turn,
            pre_status_ms=self._pre_status_ms,
            timed_out=(parsed is None and rc != 0),
        )
        return self._done

    def cancel(self) -> None:
        if self._proc.poll() is None:
            with contextlib.suppress(OSError):
                self._proc.terminate()


class LocalHcTransport:
    """`Transport` implementation for local `herdr-core` (`hc`) terminals (§5.1, §5.3)."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    @staticmethod
    def _term_addr(endpoint: Endpoint) -> str:
        return endpoint.hc_target or endpoint.terminal

    def capabilities(self, endpoint: Endpoint, *, pre_info: Mapping[str, Any] | None = None) -> TransportCapabilities:
        if pre_info is None:
            term = self._term_addr(endpoint)
            pre_info = self.ctx.hc.get_raw(term, errors=True) if term else None
        can_report = _can_report_status(pre_info)
        return TransportCapabilities(
            can_report_status=can_report,
            can_interrupt=True,
            can_unblock_keys=True,
            can_observe_screen=True,
            can_observe_procs=True,
            can_observe_transcript=True,
            delivery_mode="push",
            supports_if_idle=can_report,
        )

    def _build_payload(self, item: MailboxItem, *, occupation_hint: str = "", retry_note: str = "") -> str:
        return format_deliver_text(
            item.envelope,
            attempt=item.next_attempt(),
            occupation_hint=occupation_hint,
            retry_note=retry_note,
        )

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
        term = self._term_addr(endpoint)
        if not term:
            return DeliverOutcome(status="endpoint_gone", detail="empty terminal address")

        if pre_info is None:
            pre_info = self.ctx.hc.get_raw(term, errors=True)
        ek, ed = _error_kind(pre_info)
        if ek in ("not_found", "finished"):
            return DeliverOutcome(status="endpoint_gone", detail=ed)
        if ek in ("unavailable", "machine_unknown"):
            return DeliverOutcome(status="partitioned", detail=ed)
        if isinstance(pre_info, Mapping) and pre_info.get("state") in ("exited", "finished", "removed"):
            return DeliverOutcome(status="endpoint_gone", detail=str(pre_info.get("state")))

        pre_turn = int(pre_info.get("turn") or 0) if (isinstance(pre_info, Mapping) and pre_info.get("turn") is not None) else None
        pre_sms = int(pre_info.get("status_ms") or 0) if (isinstance(pre_info, Mapping) and pre_info.get("status_ms") is not None) else None
        can_report = _can_report_status(pre_info)
        use_if_idle = bool(if_idle and can_report)

        payload = self._build_payload(item, occupation_hint=occupation_hint, retry_note=retry_note)
        sent = self.ctx.hc.send(
            term,
            payload,
            if_state="idle" if use_if_idle else None,
            timeout=timeout_s,
            errors=True,
        )
        post_info = None
        can_reconcile = (pre_turn is not None) or (pre_sms is not None)
        if can_reconcile and (
            sent is None or (not send_succeeded(sent, pre_info) and not (isinstance(sent, Mapping) and sent.get("error")))
        ):
            post_info = self.ctx.hc.get_raw(term, errors=True)
        return _map_send_reply(
            sent,
            pre_info,
            post_info,
            pre_turn=pre_turn,
            pre_status_ms=pre_sms,
            timed_out=(sent is None),
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
        pre_info: Mapping[str, Any] | None = None,
    ) -> AsyncDeliverHandle:
        """Launch non-blocking async `hc send` subprocess (or immediate handle when `ctx.hc` is mocked)."""
        now_ms = int(float(self.ctx.clock.time()) * 1000)
        runner = getattr(self.ctx.hc, "_runner", None)
        if runner is not None or type(self.ctx.hc).__name__ != "HcHost":
            outcome = self.deliver(
                endpoint,
                item,
                if_idle=if_idle,
                timeout_s=timeout_s,
                occupation_hint=occupation_hint,
                retry_note=retry_note,
                pre_info=pre_info,
            )
            return _ImmediateDeliverHandle(outcome, now_ms)

        term = self._term_addr(endpoint)
        if not term:
            return _ImmediateDeliverHandle(DeliverOutcome(status="endpoint_gone", detail="empty terminal"), now_ms)
        if pre_info is None:
            pre_info = self.ctx.hc.get_raw(term, errors=True)
        ek, ed = _error_kind(pre_info)
        if ek in ("not_found", "finished"):
            return _ImmediateDeliverHandle(DeliverOutcome(status="endpoint_gone", detail=ed), now_ms)
        if ek in ("unavailable", "machine_unknown"):
            return _ImmediateDeliverHandle(DeliverOutcome(status="partitioned", detail=ed), now_ms)
        if isinstance(pre_info, Mapping) and pre_info.get("state") in ("exited", "finished", "removed"):
            return _ImmediateDeliverHandle(
                DeliverOutcome(status="endpoint_gone", detail=str(pre_info.get("state"))),
                now_ms,
            )

        pre_turn = int(pre_info.get("turn") or 0) if (isinstance(pre_info, Mapping) and pre_info.get("turn") is not None) else None
        pre_sms = int(pre_info.get("status_ms") or 0) if (isinstance(pre_info, Mapping) and pre_info.get("status_ms") is not None) else None
        use_if_idle = bool(if_idle and _can_report_status(pre_info))
        payload = self._build_payload(item, occupation_hint=occupation_hint, retry_note=retry_note)
        hc_bin = self.ctx.hc.bin() if hasattr(self.ctx.hc, "bin") else "hc"
        argv = [_exec_bin(hc_bin, env=self.ctx.env), "send"]
        if use_if_idle:
            argv.extend(("--if", "idle"))
        argv.extend(("--json", "--", term, payload))
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=dict(self.ctx.env) if self.ctx.env else None,
            )
        except OSError as err:
            return _ImmediateDeliverHandle(DeliverOutcome(status="rejected", detail=str(err)), now_ms)
        return _SubprocessDeliverHandle(
            proc,
            ctx=self.ctx,
            term=term,
            pre_info=pre_info,
            pre_turn=pre_turn,
            pre_status_ms=pre_sms,
            started_ms=now_ms,
            timeout_s=timeout_s,
        )

    def observe(
        self,
        endpoint: Endpoint,
        cursors: Mapping[str, int],
        *,
        include_screen: bool = False,
        include_procs: bool = False,
    ) -> ObserveBatch:
        term = self._term_addr(endpoint)
        now_ms = int(float(self.ctx.clock.time()) * 1000)
        info = self.ctx.hc.get_raw(term, errors=True) if term else None
        ek, _ = _error_kind(info)
        if ek in ("unavailable", "machine_unknown"):
            return ObserveBatch(
                link_state="disconnected",
                observations=({"src": "transport", "kind": "link_state", "link_state": "disconnected", "t": now_ms},),
                next_cursors=dict(cursors),
                terminal_info=dict(info) if isinstance(info, Mapping) else None,
            )
        if ek == "unauthorized":
            return ObserveBatch(
                link_state="unauthorized",
                observations=(),
                next_cursors=dict(cursors),
                terminal_info=dict(info) if isinstance(info, Mapping) else None,
            )

        obs: list[dict[str, Any]] = []
        if ek in ("not_found", "finished"):
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
        elif isinstance(info, Mapping):
            t_state = str(info.get("state") or "live").strip().lower()
            a_state = _status_state_of(info)
            raw_s = info.get("status")
            s_msg = str(raw_s.get("msg") or raw_s.get("message") or "").strip() if isinstance(raw_s, Mapping) else ""
            reported = _can_report_status(info)
            obs.append({
                "src": "supervisor",
                "kind": "hc_state",
                "t": now_ms,
                "state": t_state,
                "status": a_state,
                "status_msg": s_msg,
                "status_ms": int(info.get("status_ms") or 0),
                "turn": int(info.get("turn") or 0),
                "reported": reported,
                "endpoint": endpoint.to_dict(),
            })
            if include_screen and t_state == "live":
                text = self.ctx.hc.read(term)
                if isinstance(text, str):
                    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
                    obs.append({
                        "src": "probe:pty",
                        "kind": "pty_probe",
                        "t": now_ms,
                        "digest": digest,
                        "text_len": len(text),
                    })
            if include_procs and t_state == "live":
                fg = self.ctx.procs.foreground_tool_stat(info)
                bg = self.ctx.procs.background_work(info)
                obs.append({
                    "src": "probe:proc",
                    "kind": "proc_probe",
                    "t": now_ms,
                    "tool_pid": int(fg.get("tool_pid") or 0),
                    "cmd": str(fg.get("cmd") or ""),
                    "cpu_ms": int(fg.get("cpu_ms") or 0),
                    "bg_commands": list(bg),
                })

        return ObserveBatch(
            link_state="connected",
            observations=tuple(obs),
            next_cursors=dict(cursors),
            terminal_info=dict(info) if isinstance(info, Mapping) else None,
        )

    def interrupt(self, endpoint: Endpoint, *, timeout_s: float = 5.0) -> InterruptOutcome:
        term = self._term_addr(endpoint)
        if not term:
            return InterruptOutcome(status="endpoint_gone", detail="empty terminal")
        info = self.ctx.hc.get_raw(term, errors=True)
        ek, ed = _error_kind(info)
        if ek in ("not_found", "finished"):
            return InterruptOutcome(status="endpoint_gone", detail=ed)
        if ek in ("unavailable", "machine_unknown"):
            return InterruptOutcome(status="partitioned", detail=ed)
        if isinstance(info, Mapping) and info.get("state") in ("exited", "finished", "removed"):
            return InterruptOutcome(status="endpoint_gone", detail=str(info.get("state")))

        res = self.ctx.hc.interrupt(term, timeout=timeout_s, errors=True)
        rk, rd = _error_kind(res)
        if rk in ("not_found", "finished"):
            return InterruptOutcome(status="endpoint_gone", detail=rd)
        if rk in ("unavailable", "machine_unknown"):
            return InterruptOutcome(status="partitioned", detail=rd)
        if rk:
            return InterruptOutcome(status="unknown", detail=rd)
        if not isinstance(res, Mapping):
            return InterruptOutcome(status="unknown", detail="no interrupt response")

        outcome = str(res.get("outcome") or res.get("status") or "unknown").strip().lower()
        if outcome not in ("stopped", "exited", "still_working", "unknown"):
            outcome = "unknown"
        key_sent = str(res.get("key") or ("esc" if _can_report_status(info) else "ctrl+c"))
        return InterruptOutcome(status=outcome, key_sent=key_sent, detail=str(res.get("detail") or ""))

    def unblock_prompt(self, endpoint: Endpoint, keys: Sequence[str]) -> bool:
        term = self._term_addr(endpoint)
        if not term or not keys:
            return False
        res = self.ctx.hc.keys(term, *keys)
        return res is not None and not (isinstance(res, Mapping) and res.get("error"))
