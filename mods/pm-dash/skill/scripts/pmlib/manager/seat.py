"""The seat process and its state: `pm.py seat` hosts one PM session after another in the project's fixed PM
terminal; seat.json and next-session.json are what it shares with `rotate`, `end-session` and an older seat
still running. Layer 3."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
from typing import Any, Mapping

try:
    import termios
except ImportError:
    termios = None

try:
    import ctypes
    from ctypes import wintypes as _wintypes
except ImportError:
    ctypes = None
    _wintypes = None

from .. import osutil
from ..agents.base import READY_MARKS, is_seat_argv, unwrap_seat_argv
from ..context import Context
from ..events.supervisor import deliver_under_typist_lock
from ..home import project_slug
from ..messaging.address import LogicalAddress, parse_legacy_endpoint
from ..messaging.envelope import P0_CONTROL, Envelope, new_env_id
from ..messaging.principal import Principal
from ..project.conversation import Conversation
from ..store import lock_file, replace_task_file, unlock_file, write_atomic
from ..terminals import hc as hc_mod
from ..terminals.hc import TerminalInfo


def _is_real_hc(ctx: Context) -> bool:
    """Whether `ctx.hc` talks to the real `hc` binary (as opposed to a mocked `pm.hc` or `FakeHc`)."""
    if getattr(ctx, "_legacy", False):
        return hc_mod.hc is hc_mod._DEFAULT_HC
    return isinstance(ctx.hc, hc_mod.HcHost) and ctx.hc._runner is None


def seat_running(repo: str | Path, *, ctx: Context | None = None) -> bool:
    """Whether a live `pm.py seat` process currently holds projects/<slug>/seat.lock."""
    c = Context.from_env() if ctx is None else ctx
    path = c.home.project_for(repo).seat_lock
    if not path.exists():
        return False
    try:
        with open(path, "a+") as f:
            lock_file(f)
            unlock_file(f)
    except OSError:
        return True
    return False


def seat_alive(repo: str | Path, rec: Mapping[str, Any] | None, term: Mapping[str, Any] | None = None,
               *, ctx: Context | None = None) -> bool:
    """Whether a seated PM registration has a live seat process (or is mocked in tests)."""
    if not (rec or {}).get("seat"):
        return True
    c = Context.from_env() if ctx is None else ctx
    if seat_running(repo, ctx=c):
        return True
    if _is_real_hc(c):
        return False
    return not bool((term or {}).get("seat_dead"))


START_WAIT = 60          # seconds seat waits for a rotated-in PM session to start work before falling back
SEAT_START_WAIT = START_WAIT
SEAT_POLL = 0.2          # seconds between `seat` child/startup polls
RETIRE_WAIT = 3600       # seconds `end-session` waits for the outgoing PM to finish its turn and background work
SEAT_NEXT_MAX_AGE = RETIRE_WAIT  # aligned with RETIRE_WAIT so next-session.json never expires while end-session waits


# ANSI reset sequences emitted between sessions in `pm.py seat`: turn off bracketed paste, X10/button/any-event/SGR
# mouse tracking, focus reporting and kitty keyboard protocol, and show the cursor.
SEAT_ANSI_RESET = b"\033[?2004l\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1004l\033[<u\033[?25h"


def is_seat_terminal(info: TerminalInfo | Mapping[str, Any] | None) -> bool:
    if isinstance(info, TerminalInfo):
        return info.labels.get("pm.seat") == "1" or is_seat_argv(info.argv)
    if not isinstance(info, Mapping):
        return False
    return (info.get("labels") or {}).get("pm.seat") == "1" or is_seat_argv(info.get("argv") or [])


def in_seat(repo: str | Path, rec: Mapping[str, Any] | None, info: TerminalInfo | Mapping[str, Any] | None,
            *, ctx: Context | None = None) -> bool:
    """Whether the project's PM currently runs inside `pm.py seat` (so `rotate` swaps only the session)."""
    if not ((rec or {}).get("seat") or is_seat_terminal(info)):
        return False
    state = info.state if isinstance(info, TerminalInfo) else (info or {}).get("state")
    if state != "live":
        return False
    c = Context.from_env() if ctx is None else ctx
    if seat_running(repo, ctx=c):
        return True
    return not _is_real_hc(c)


def read_seat_state(repo: str | Path, *, ctx: Context | None = None) -> dict[str, Any]:
    c = Context.from_env() if ctx is None else ctx
    path = c.home.project_for(repo).seat_state
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_seat_state(repo: str | Path, data: Mapping[str, Any], *, ctx: Context | None = None) -> None:
    c = Context.from_env() if ctx is None else ctx
    path = c.home.project_for(repo).ensure() / "seat.json"
    with contextlib.suppress(OSError):
        write_atomic(path, (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"),
                     replace_fn=replace_task_file)


def outgoing_agent_args(repo: str | Path, term: Mapping[str, Any], kind: str, *, ctx: Context | None = None) -> list[str]:
    """Flags of the outgoing PM session (after argv[0]), whether read from seat.json or `hc get`."""
    c = Context.from_env() if ctx is None else ctx
    program = Path(c.agents.start_argv(kind)[0]).name
    seat = read_seat_state(repo, ctx=c)
    if seat.get("terminal") == (term.get("address") or "") or seat.get("argv"):
        s_argv = seat.get("argv") or []
        if s_argv and Path(str(s_argv[0])).name == program:
            return list(s_argv[1:])
    fg = (term.get("foreground") or {}).get("argv") or []
    _, fg_inner = unwrap_seat_argv(fg)
    if fg_inner and Path(str(fg_inner[0])).name == program:
        return list(fg_inner[1:])
    _, raw_inner = unwrap_seat_argv(term.get("argv") or [])
    for i, arg in enumerate(raw_inner):
        if Path(str(arg)).name == program:
            return list(raw_inner[i + 1:])
    return []


def swap_reason_text(a: Any = None, *, reason: str | None = None, model: str | None = None,
                     profile: str | None = None, ctx: Context | None = None) -> str:
    """Human-readable reason for replacing the PM session (recorded in the project conversation)."""
    c = Context.from_env() if ctx is None else ctx
    tr = c.config.tr
    explicit = (reason if reason is not None else (getattr(a, "reason", None) or "")).strip()
    if explicit:
        return explicit
    eff_profile = (profile if profile is not None else (getattr(a, "profile", None) or "")).strip()
    if eff_profile:
        return tr(f"switch profile to {eff_profile}", f"切换档位至 {eff_profile}")
    eff_model = (model if model is not None else (getattr(a, "model", None) or "")).strip()
    if eff_model:
        return tr(f"switch model to {eff_model}", f"切换模型至 {eff_model}")
    return tr("manual session swap", "手动换会话")


def record_swap_notice(repo: str | Path, reason: str, by: str = "", *, ctx: Context | None = None) -> None:
    """Append a transparent one-line notice to conversation.jsonl explaining why the PM session swapped."""
    c = Context.from_env() if ctx is None else ctx
    text = c.config.tr(
        f"PM session swapped ({reason}); taken over from the ledger.",
        f"PM 会话已切换（原因：{reason}），已从台账接手。",
    )
    Conversation(c, repo).record("pm", text=text, **({"by": by} if by else {}), notice=True)


def _next_session_ready_impl(repo: str | Path, *, ctx: Context) -> bool:
    """Whether a fresh (non-expired) `next-session.json` is waiting for `pm.py seat`."""
    path = ctx.home.project_for(repo).next_session
    try:
        return path.exists() and ctx.clock.time() - path.stat().st_mtime <= SEAT_NEXT_MAX_AGE
    except OSError:
        return False


def next_session_ready(repo: str | Path, *, ctx: Context | None = None) -> bool:
    """Whether a fresh (non-expired) `next-session.json` is waiting for `pm.py seat`."""
    return _next_session_ready_impl(repo, ctx=Context.from_env() if ctx is None else ctx)


_DEFAULT_NEXT_SESSION_READY = next_session_ready


def pop_next_session(repo: str | Path, *, ctx: Context | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Atomically consume `next-session.json`. Returns `(fresh_spec, expired_spec)`:
    - `(dict, None)` when fresh and valid;
    - `(None, dict)` when present on disk past `SEAT_NEXT_MAX_AGE` (so `seat` runs fallback instead of dropping to shell);
    - `(None, None)` when no `next-session.json` exists."""
    c = Context.from_env() if ctx is None else ctx
    path = c.home.project_for(repo).next_session
    try:
        if not path.exists():
            return None, None
        mtime = path.stat().st_mtime
        raw = path.read_text()
        path.unlink(missing_ok=True)
    except OSError:
        return None, None
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    now_ts = c.clock.time()
    created = data.get("created_ts")
    age = max(now_ts - mtime, (now_ts - created) if isinstance(created, (int, float)) else 0)
    if age > SEAT_NEXT_MAX_AGE:
        return None, data
    if not isinstance(data.get("argv"), list) or not data["argv"]:
        return None, data
    return data, None


def session_started_work(term: str, base_turn: int, start_ms: int, *, ctx: Context | None = None) -> bool:
    """Whether the newly spawned PM session in `term` has started or completed its first turn."""
    c = Context.from_env() if ctx is None else ctx
    info = c.hc.get_raw(term) or {}
    if info and info.get("state") != "live":
        return False
    if (info.get("turn") or 0) > base_turn:
        return True
    status = info.get("status") or {}
    if status.get("state") == "working":
        status_ms = info.get("status_ms") or 0
        return status_ms == 0 or status_ms >= start_ms - 500
    return False


def _reclaim_tty(tty_fd: int | None) -> None:
    if tty_fd is not None and not osutil.WINDOWS:
        with contextlib.suppress(OSError):
            os.tcsetpgrp(tty_fd, os.getpgrp())


def _hand_tty_to_child(tty_fd: int | None, child_pid: int) -> None:
    if tty_fd is not None and not osutil.WINDOWS and child_pid > 0:
        with contextlib.suppress(OSError):
            os.setpgid(child_pid, child_pid)
        with contextlib.suppress(OSError):
            os.tcsetpgrp(tty_fd, child_pid)
        sig_cont = getattr(signal, "SIGCONT", None)
        if sig_cont is not None:
            with contextlib.suppress(OSError):
                os.killpg(child_pid, sig_cont)


def _reset_seat_tty(tty_fd: int | None, saved_attrs: Any, flush_input: bool = False) -> None:
    """Restore cooked terminal modes, turn off residual TUI mouse/paste/focus/kitty modes, and when rotating between
    sessions (`flush_input=True`), discard unread PTY input bytes typed during the handoff gap (TCIFLUSH)."""
    if tty_fd is None or osutil.WINDOWS:
        return
    sig_ttou = getattr(signal, "SIGTTOU", None)
    prev_ttou = None
    if sig_ttou is not None:
        with contextlib.suppress(OSError, ValueError):
            prev_ttou = signal.getsignal(sig_ttou)
            signal.signal(sig_ttou, signal.SIG_IGN)
    try:
        if saved_attrs is not None and termios is not None:
            with contextlib.suppress(termios.error, OSError):
                termios.tcsetattr(tty_fd, termios.TCSANOW, saved_attrs)
        with contextlib.suppress(OSError):
            os.write(tty_fd, SEAT_ANSI_RESET)
        if flush_input and termios is not None:
            with contextlib.suppress(termios.error, OSError):
                termios.tcflush(tty_fd, termios.TCIFLUSH)
    finally:
        if sig_ttou is not None and prev_ttou is not None:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig_ttou, prev_ttou)


def _seat_child_preexec() -> None:
    os.setpgid(0, 0)
    with contextlib.suppress(OSError):
        os.tcsetpgrp(0, os.getpid())
    for sig_name in ("SIGINT", "SIGTTOU", "SIGTTIN", "SIGHUP", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig, signal.SIG_DFL)


def _create_win_kill_job() -> int | None:
    """Create a Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so child processes never outlive `seat`."""
    if not osutil.WINDOWS or ctypes is None or _wintypes is None:
        return None
    try:
        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", _wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", _wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", _wintypes.DWORD),
                ("SchedulingClass", _wintypes.DWORD),
            ]

        class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, _wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = _wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [_wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, _wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = _wintypes.BOOL
        kernel32.CloseHandle.argtypes = [_wintypes.HANDLE]
        kernel32.CloseHandle.restype = _wintypes.BOOL

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        return int(job)
    except Exception:
        return None


def _assign_win_job(job: int | None, proc: subprocess.Popen[Any]) -> None:
    if not job or not osutil.WINDOWS or ctypes is None or _wintypes is None:
        return
    with contextlib.suppress(Exception):
        kernel32 = ctypes.windll.kernel32
        kernel32.AssignProcessToJobObject.argtypes = [_wintypes.HANDLE, _wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = _wintypes.BOOL
        handle = getattr(proc, "_handle", None)
        if handle:
            kernel32.AssignProcessToJobObject(_wintypes.HANDLE(job), _wintypes.HANDLE(int(handle)))


def _close_win_job(job: int | None) -> None:
    if not job or not osutil.WINDOWS or ctypes is None or _wintypes is None:
        return
    with contextlib.suppress(Exception):
        kernel32 = ctypes.windll.kernel32
        kernel32.CloseHandle.argtypes = [_wintypes.HANDLE]
        kernel32.CloseHandle.restype = _wintypes.BOOL
        kernel32.CloseHandle(_wintypes.HANDLE(job))


def _spawn_seat_child(argv: list[str], cwd: str, env: Mapping[str, str],
                      win_job: int | None = None) -> subprocess.Popen[Any]:
    if osutil.WINDOWS:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, **osutil.own_group(background=False))
        _assign_win_job(win_job, proc)
        return proc
    return subprocess.Popen(argv, cwd=cwd, env=env, preexec_fn=_seat_child_preexec)


def _seat_prompt_sender(
    proc: subprocess.Popen[Any],
    term: str,
    kind: str,
    prompt: str,
    *,
    repo: str | Path = "",
    ctx: Context | None = None,
) -> threading.Thread:
    """Type `prompt` into `term` once the child agent is ready, aborting immediately if `proc` exits."""
    c = Context.from_env() if ctx is None else ctx
    prompt_key = f"seat_opening:{term}:{new_env_id(int(float(c.clock.time()) * 1000))}"

    def _run() -> None:
        for attempt in range(20):
            if proc.poll() is not None:
                return
            c.clock.sleep(2)
            if proc.poll() is not None:
                return
            info = c.hc.get_raw(term) or {}
            if info.get("state") not in (None, "live"):
                return
            status = info.get("status")
            ready = status.get("state") in ("idle", "done") if status else attempt >= 1
            marked = False
            if not ready and kind and not (status or {}).get("state"):
                marked = any(m in c.hc.read(term) for m in READY_MARKS.get(kind, ()))
            if ready or marked:
                now_ms = int(float(c.clock.time()) * 1000)
                ep = parse_legacy_endpoint(term, runtime_hint="hc")
                if ep is not None:
                    proj = project_slug(repo) if repo else "seat"
                    env = Envelope(
                        env_id=new_env_id(now_ms),
                        idempotency_key=prompt_key,
                        schema_version=1,
                        created_ms=now_ms,
                        kind="cmd.send",
                        sender=Principal.supervisor(proj),
                        recipient=LogicalAddress.pm(proj),
                        project=proj,
                        # Its sender retries a send whose turn never started: keep it typed for that (not closed).
                        cause={"kind": "seat_opening_prompt", "retry_unstarted": True},
                        priority=P0_CONTROL,
                        body={"text": prompt},
                    )
                    # The same envelope on every attempt: typed but its turn never started (and the terminal has
                    # not moved on since) is typed again, as before mailboxes; a late start is not retyped.
                    out = deliver_under_typist_lock(
                        c, ep, env, repo=repo, if_idle=False, attempts=attempt + 1, retry_unstarted=True
                    )
                    if out is not None and out.status == "typed" and (out.started_turn is True or not status or marked):
                        return

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def _check_next_session_ready(repo: str | Path, ctx: Context) -> bool:
    if getattr(ctx, "_legacy", False) and next_session_ready is not _DEFAULT_NEXT_SESSION_READY:
        return bool(next_session_ready(repo))
    return _next_session_ready_impl(repo, ctx=ctx)


def _wait_seat_session(
    repo: str | Path,
    proc: subprocess.Popen[Any],
    kind: str,
    base_turn: int,
    rotated_in: bool,
    stopping: list[bool],
    *,
    ctx: Context | None = None,
) -> tuple[bool, str]:
    """Wait for `proc` while verifying startup if `rotated_in`. Returns (started_ok, failure_reason)."""
    c = Context.from_env() if ctx is None else ctx
    if not rotated_in:
        while proc.poll() is None and not stopping[0]:
            c.clock.sleep(SEAT_POLL)
        return True, ""
    start_mono = c.clock.monotonic()
    start_ms = int(c.clock.time() * 1000)
    started = False
    hc_term = c.hc_terminal
    tr = c.config.tr
    while True:
        if stopping[0]:
            return True, ""
        if not started and _check_next_session_ready(repo, c):
            started = True
        rc = proc.poll()
        if rc is not None:
            if started:
                return True, ""
            if hc_term and session_started_work(hc_term, base_turn, start_ms, ctx=c):
                return True, ""
            if not hc_term and rc == 0:
                return True, ""
            screen = c.hc.screen_line(hc_term) if hc_term else ""
            why = tr(f"exited with code {rc}" + (f" (screen: {screen})" if screen else ""),
                     f"退出码 {rc}" + (f"（屏幕：{screen}）" if screen else ""))
            return False, why
        if not started:
            if hc_term and session_started_work(hc_term, base_turn, start_ms, ctx=c):
                started = True
            elif c.clock.monotonic() - start_mono >= SEAT_START_WAIT:
                if kind != "claude" and (not hc_term or (c.hc.get_raw(hc_term) or {}).get("state") == "live"):
                    started = True
                else:
                    screen = c.hc.screen_line(hc_term) if hc_term else ""
                    osutil.stop_pid_group(proc.pid)
                    why = tr(f"did not start work within {SEAT_START_WAIT}s"
                             + (f" (screen: {screen})" if screen else ""),
                             f"{SEAT_START_WAIT} 秒内没有开始工作" + (f"（屏幕：{screen}）" if screen else ""))
                    return False, why
        c.clock.sleep(SEAT_POLL)
