"""herdr-core, the desktop app's terminal host: `TerminalInfo`, `HcHost`, its command line (`hc ... --json`),
its protocol (`hc connect`), desktop tab renaming (`herdr-app`), and legacy module-level wrappers. Layer 1."""
from __future__ import annotations

import base64
import contextlib
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import time
from typing import Any, Iterable, Mapping

from .. import config as config_mod, osutil
from ..agents import base as agents_base
from . import events as events_mod


SHELL_NAMES = frozenset({"zsh", "bash", "sh", "fish", "-zsh", "-bash", "-sh", "-fish", "pwsh", "powershell", "cmd"})


def _exec_bin(prog: str, env: Mapping[str, str] | None = None) -> str:
    """Resolve `.cmd`/`.bat` shims on Windows so `subprocess.run([prog, ...])` can invoke them without shell=True."""
    if osutil.WINDOWS and not os.path.isabs(prog):
        path = env.get("PATH") if env is not None else None
        found = shutil.which(prog, path=path)
        if found and found.lower().endswith((".cmd", ".bat")):
            return found
    return prog


def _b64_text(val: Any) -> str:
    """`hc exec` gives what a program wrote as base64; a runner (tests) may already give text."""
    if not isinstance(val, str) or not val:
        return ""
    try:
        return base64.b64decode(val.encode("ascii"), validate=True).decode("utf-8", errors="replace")
    except (ValueError, UnicodeEncodeError):
        return val


def _opt_int(val: Any) -> int | None:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return int(val)
    return None


def is_shell_terminal(info: TerminalInfo | Mapping[str, Any] | None) -> bool:
    """Whether a herdr-core terminal's foreground program is a plain interactive shell (no agent running)."""
    if isinstance(info, TerminalInfo):
        return info.is_shell
    if not isinstance(info, Mapping) or info.get("state") != "live":
        return False
    fg = (info.get("foreground") or {}).get("argv") or []
    argv = fg or info.get("argv") or []
    if not argv:
        return False
    prog = PureWindowsPath(str(argv[0])).stem.lower() if osutil.WINDOWS else Path(str(argv[0])).name
    return prog in SHELL_NAMES and not agents_base.is_seat_argv(info.get("argv") or [])


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


@dataclass(frozen=True)
class TerminalInfo:
    """Typed view over an `hc get` or `hc ls` terminal row."""

    address: str
    state: str = "live"
    agent_state: str = ""
    status_msg: str = ""
    turn: int = 0
    labels: Mapping[str, str] = field(default_factory=dict)
    argv: tuple[str, ...] = ()
    foreground_argv: tuple[str, ...] = ()
    cwd: str = ""
    pid: int | None = None
    status_ms: int | None = None
    created_ms: int | None = None
    finished_ms: int | None = None
    reason: str = ""
    seat_dead: bool = False
    reported: bool = False
    is_shell: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_live(self) -> bool:
        return self.state == "live"

    @property
    def has_status(self) -> bool:
        status = self.raw.get("status")
        if isinstance(status, str):
            return bool(status.strip())
        return isinstance(status, Mapping) and bool(status)

    @property
    def foreground_pid(self) -> int | None:
        fg = self.raw.get("foreground")
        if isinstance(fg, Mapping):
            pid = fg.get("pid")
            return pid if isinstance(pid, int) and not isinstance(pid, bool) else None
        return None

    @property
    def name(self) -> str:
        return str(self.raw.get("name") or "")

    def label(self, key: str, default: str = "") -> str:
        val = self.labels.get(key)
        return str(val) if val is not None else default

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> TerminalInfo:
        raw_status = row.get("status")
        if isinstance(raw_status, Mapping):
            agent_state = str(raw_status.get("state") or "")
            status_msg = str(raw_status.get("msg") or raw_status.get("message") or "")
        elif isinstance(raw_status, str):
            agent_state = raw_status.strip()
            status_msg = ""
        else:
            agent_state = ""
            status_msg = ""
        labels_raw = row.get("labels")
        labels = {str(k): str(v) for k, v in labels_raw.items()} if isinstance(labels_raw, Mapping) else {}
        argv_raw = row.get("argv")
        argv = tuple(str(x) for x in argv_raw) if isinstance(argv_raw, (list, tuple)) else ()
        fg = row.get("foreground") if isinstance(row.get("foreground"), Mapping) else {}
        fg_raw = fg.get("argv")
        fg_argv = tuple(str(x) for x in fg_raw) if isinstance(fg_raw, (list, tuple)) else ()
        pid_raw = row.get("pid")
        pid = pid_raw if isinstance(pid_raw, int) and not isinstance(pid_raw, bool) else None
        turn_raw = row.get("turn")
        try:
            turn = int(turn_raw or 0)
        except (TypeError, ValueError):
            turn = 0
        state = str(row["state"]) if "state" in row and row["state"] is not None else "live"
        return cls(
            address=str(row.get("address") or row.get("id") or ""),
            state=state,
            agent_state=agent_state,
            status_msg=status_msg,
            turn=turn,
            labels=labels,
            argv=argv,
            foreground_argv=fg_argv,
            cwd=str(row.get("cwd") or ""),
            pid=pid,
            status_ms=_opt_int(row.get("status_ms")),
            created_ms=_opt_int(row.get("created_ms")),
            finished_ms=_opt_int(row.get("finished_ms")),
            reason=str(row.get("reason") or ""),
            seat_dead=bool(row.get("seat_dead")),
            reported=bool(row.get("reported")),
            is_shell=is_shell_terminal(row),
            raw=dict(row),
        )


def _doc_tabs(value: Any) -> Iterable[tuple[dict[str, Any], list[str]]]:
    """(tab, its terminals) for every tab in the app's document ("herdr-app": spaces, tabs, a tree of blocks)."""
    def terms(node: Any):
        if isinstance(node, dict):
            if (node.get("content") or {}).get("terminal"):
                yield node["content"]["terminal"]
            for child in node.get("children") or []:
                yield from terms(child)
    for space in (value or {}).get("spaces") or []:
        for tab in space.get("tabs") or []:
            yield tab, list(terms(tab.get("root")))


class HcHost:
    """Port for herdr-core (`hc`, `hc connect`, `herdr-app` desktop tabs, and `ChangeWaiter`)."""

    def __init__(
        self,
        config_port: Any = None,
        *,
        clock: Any = None,
        runner: Any = None,
        rpc_runner: Any = None,
        app_runner: Any = None,
        waiter_factory: Any = None,
        name_tab_fn: Any = None,
        rename_tab_fn: Any = None,
        worker_tab_fn: Any = None,
        worker_state_fn: Any = None,
        live_terminals_fn: Any = None,
        live_terminals_patched_fn: Any = None,
        screen_of_fn: Any = None,
        screen_line_fn: Any = None,
    ) -> None:
        self._config = config_port
        self._clock = clock
        self._runner = runner
        self._rpc_runner = rpc_runner
        self._app_runner = app_runner
        self._waiter_factory = waiter_factory
        self._name_tab_fn = name_tab_fn
        self._rename_tab_fn = rename_tab_fn
        self._worker_tab_fn = worker_tab_fn
        self._worker_state_fn = worker_state_fn
        self._live_terminals_fn = live_terminals_fn
        self._live_terminals_patched_fn = live_terminals_patched_fn
        self._screen_of_fn = screen_of_fn
        self._screen_line_fn = screen_line_fn
        self.last_worker_info: dict[str, Any] | None = None

    def _cfg_dict(self) -> dict[str, Any]:
        if self._config is None:
            return {}
        if callable(self._config):
            data = self._config()
            return data if isinstance(data, dict) else {}
        read = getattr(self._config, "read", None)
        if callable(read):
            data = read()
            return data if isinstance(data, dict) else {}
        return self._config if isinstance(self._config, dict) else {}

    def _tabs_cfg(self) -> dict[str, Any]:
        cfg = self._cfg_dict().get("tabs")
        return cfg if isinstance(cfg, dict) else {}

    def _now_ts(self) -> float:
        return self._clock.time() if self._clock is not None else time.time()

    def _sleep(self, seconds: float) -> None:
        if self._clock is not None:
            self._clock.sleep(seconds)
        else:
            time.sleep(seconds)

    def bin(self) -> str:
        """The herdr-core CLI path from config, else `hc` from PATH."""
        return str(self._cfg_dict().get("hc") or "hc")

    def __call__(self, *args: Any, errors: bool = False, env: Any = None, timeout: float = 60) -> Any:
        return self.call(*args, errors=errors, env=env, timeout=timeout)

    def call(self, *args: Any, errors: bool = False, env: Any = None, timeout: float = 60,
             input: str | None = None) -> Any:
        """Parsed JSON of a herdr-core CLI call, or None when hc is missing or fails. `input`: text piped to hc's
        stdin (`hc file write`, `hc exec -i`)."""
        if self._runner is not None:
            kw: dict[str, Any] = {}
            if errors:
                kw["errors"] = errors
            if env is not None:
                kw["env"] = env
            if timeout != 60:
                kw["timeout"] = timeout
            if input is not None:
                kw["input"] = input
            return self._runner(*args, **kw) if kw else self._runner(*args)
        try:
            cut = args.index("--") if "--" in args else len(args)
            out = subprocess.run(
                [_exec_bin(self.bin(), env=env), *args[:cut], "--json", *args[cut:]],
                capture_output=True, text=True, timeout=timeout, env=env, input=input,
            )
            if out.returncode != 0:
                return json.loads(out.stderr or "null") if errors else None
            return json.loads(out.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None

    def rpc(self, method: str, params: Any = None) -> dict[str, Any] | None:
        """One call of herdr-core's protocol (`hc connect`, JSON-RPC over stdin and stdout)."""
        if self._rpc_runner is not None:
            return self._rpc_runner(method, params)
        try:
            out = subprocess.run(
                [_exec_bin(self.bin()), "connect"],
                capture_output=True, text=True, timeout=20,
                input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n",
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        for line in out.stdout.splitlines():
            with contextlib.suppress(ValueError):
                reply = json.loads(line)
                if isinstance(reply, dict) and reply.get("id") == 1:
                    return reply
        return None

    def get_raw(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        if not term:
            return None
        res = self.call("get", term, errors=errors)
        return res if isinstance(res, dict) else None

    def get(self, term: str) -> TerminalInfo | None:
        """Query a single terminal and return a typed `TerminalInfo`, or None if missing/unavailable."""
        raw = self.get_raw(term)
        if not raw or raw.get("error"):
            return None
        return TerminalInfo.from_dict(raw)

    def ls(self, *, all: bool = False) -> list[TerminalInfo] | None:
        """List terminals as `TerminalInfo` objects, or None when hc cannot answer."""
        listing = self.call("ls", "--all") if all else self.call("ls")
        if not isinstance(listing, dict) or not isinstance(listing.get("terminals"), list):
            return None
        rows = []
        for t in listing["terminals"]:
            if not isinstance(t, dict) or not t.get("address"):
                continue
            if not all and t.get("state", "live") != "live":
                continue
            rows.append(TerminalInfo.from_dict(t))
        return rows

    def all_rows(self) -> tuple[dict[str, TerminalInfo] | None, dict[str, TerminalInfo] | None]:
        """Every herdr-core terminal (`hc ls --all`) as `({live}, {ended})` by address, or `(None, None)`."""
        if self._live_terminals_patched_fn is not None and self._live_terminals_patched_fn():
            addrs = self._live_terminals_fn()
            if addrs is None:
                return None, None
            return {addr: TerminalInfo(address=addr, state="live") for addr in addrs}, {}
        listing = self.call("ls", "--all")
        if not isinstance(listing, dict) or not isinstance(listing.get("terminals"), list):
            return None, None
        live: dict[str, TerminalInfo] = {}
        ended: dict[str, TerminalInfo] = {}
        for t in listing["terminals"]:
            if not isinstance(t, dict):
                continue
            addr = t.get("address")
            if not addr:
                continue
            info = TerminalInfo.from_dict(t)
            if info.is_live:
                live[addr] = info
            else:
                ended[addr] = info
        return live, ended

    def live_rows(self) -> dict[str, TerminalInfo] | None:
        """Live herdr-core terminals `{address: TerminalInfo}`, or None when hc cannot answer."""
        if self._live_terminals_patched_fn is not None and self._live_terminals_patched_fn():
            addrs = self._live_terminals_fn()
            if addrs is None:
                return None
            return {addr: TerminalInfo(address=addr, state="live") for addr in addrs}
        listing = self.call("ls")
        if not isinstance(listing, dict) or not isinstance(listing.get("terminals"), list):
            return None
        return {
            t.get("address"): TerminalInfo.from_dict(t)
            for t in listing["terminals"]
            if isinstance(t, dict) and t.get("address") and t.get("state", "live") == "live"
        }

    def live_terminals(self) -> set[str] | None:
        """Addresses of live herdr-core terminals, or None when hc cannot answer."""
        if self._live_terminals_fn is not None:
            return self._live_terminals_fn()
        rows = self.live_rows()
        return None if rows is None else set(rows)

    def worker_state(self, term: str) -> str:
        """Why the worker in a herdr-core terminal is not working: idle, done, blocked, error, exited or removed."""
        self.last_worker_info = None
        if self._worker_state_fn is not None:
            return self._worker_state_fn(term)
        info = self.get_raw(term, errors=True) if term else None
        self.last_worker_info = info
        if not info:
            return ""
        if (info.get("error") or {}).get("kind") == "not_found":
            return "removed"
        if info.get("error"):
            return ""
        if info.get("state") != "live":
            return "exited"
        state = (info.get("status") or {}).get("state")
        return state if state in ("idle", "done", "blocked", "error") else ""

    def run(
        self,
        argv: Iterable[str],
        *,
        name: str = "",
        cwd: str | Path = "",
        labels: Iterable[str] = (),
        bg: bool = True,
        placement: Iterable[str] = (),
        keep: bool = False,
        no_parent: bool = False,
        env: Any = None,
        on: str = "",
    ) -> dict[str, Any] | None:
        args: list[str] = ["run"]
        if on:
            args.extend(("--on", on))
        if bg:
            args.append("--bg")
        if keep:
            args.append("--keep")
        if no_parent:
            args.append("--no-parent")
        args.extend(placement)
        for kv in labels:
            args.extend(("--label", kv))
        if name:
            args.extend(("--name", name))
        if cwd:
            args.extend(("--cwd", str(cwd)))
        args.append("--")
        args.extend(argv)
        kwargs = {"env": env} if env is not None else {}
        res = self.call(*args, **kwargs)
        return res if isinstance(res, dict) else None

    def start_terminal(
        self,
        name: str,
        cwd: str | Path,
        argv: Iterable[str],
        placement: Iterable[str] = (),
        labels: Iterable[str] = (),
        env: Any = None,
        on: str = "",
    ) -> str | None:
        """Start an agent in a herdr-core terminal (`hc run --bg`) and return its address (`<machine>/t7` with
        `on`)."""
        kw: dict[str, Any] = {"on": on} if on else {}
        res = self.run(argv, name=name, cwd=cwd, labels=labels, bg=True, placement=placement, env=env, **kw)
        return res.get("address") if isinstance(res, dict) else None

    def send(
        self,
        term: str,
        text: str,
        *,
        if_state: str | None = None,
        timeout: float = 60,
        errors: bool = False,
    ) -> dict[str, Any] | None:
        args: list[str] = ["send"]
        if if_state:
            args.extend(("--if", if_state))
        # `hc send [OPTIONS] <TERMINAL> <TEXT>`: the positionals after `--`, so a text that starts with "-" (a
        # Markdown list item, "--x") is the text and not an unknown option (`call` puts `--json` before the `--`).
        args.extend(("--", term, text))
        res = self.call(*args, timeout=timeout, errors=errors)
        return res if isinstance(res, dict) else None

    def bootstrap_shell_exec(
        self,
        term: str,
        cmd: str,
        *,
        timeout: float = 60,
    ) -> dict[str, Any] | None:
        """Wave 1 shell-bootstrap primitive: type `exec ...` into an existing interactive shell terminal."""
        return self.send(term, cmd, timeout=timeout)

    def init_session_flag(
        self,
        term: str,
        flag_cmd: str,
        *,
        timeout: float = 60,
    ) -> dict[str, Any] | None:
        """Wave 1 session-init primitive: send a slash toggle (e.g. `/fast`) immediately after spawn."""
        return self.send(term, flag_cmd, timeout=timeout)

    def keys(self, term: str, *keys: str) -> dict[str, Any] | None:
        res = self.call("keys", term, *keys)
        return res if isinstance(res, dict) else None

    def read(self, term: str, *, lines: int | None = None) -> str:
        if lines is None and self._screen_of_fn is not None:
            return str(self._screen_of_fn(term) or "")
        args: list[str] = ["read", term]
        if lines is not None:
            args.extend(("--lines", str(lines)))
        res = self.call(*args)
        return str((res or {}).get("text") or "") if isinstance(res, dict) else ""

    def screen_line(self, term: str, width: int = 160) -> str:
        """What a terminal shows, as one line for the task log."""
        if self._screen_line_fn is not None:
            if width == 160:
                res = self._screen_line_fn(term)
            else:
                kw = {"width": width}
                res = self._screen_line_fn(term, **kw)
            return str(res or "")
        raw = self.read(term)
        lines = [s.strip() for s in raw.splitlines() if s.strip().strip("─━│╭╮╰╯ ")]
        return osutil.clip(" / ".join(lines[:3]), width) or "(empty screen)"

    def label(self, term: str, *pairs: str) -> dict[str, Any] | None:
        res = self.call("label", term, *pairs)
        return res if isinstance(res, dict) else None

    def keep(self, term: str) -> dict[str, Any] | None:
        res = self.call("keep", term)
        return res if isinstance(res, dict) else None

    def kill(self, term: str) -> dict[str, Any] | None:
        res = self.call("kill", term)
        return res if isinstance(res, dict) else None

    def remove(self, term: str) -> dict[str, Any] | None:
        res = self.call("rm", term)
        return res if isinstance(res, dict) else None

    def interrupt(self, term: str, *, timeout: float | None = None, errors: bool = False) -> dict[str, Any] | None:
        args: list[str] = ["interrupt", term]
        if timeout is not None:
            t_val = int(timeout) if float(timeout).is_integer() else timeout
            args.extend(("--timeout", str(t_val)))
        res = self.call(*args, errors=errors)
        return res if isinstance(res, dict) else None

    def server_status(self) -> dict[str, Any] | None:
        res = self.call("server", "status")
        return res if isinstance(res, dict) else None

    # --- Other machines (`hc machine ls`, `hc file read|write --on`, `hc exec --on`): the read/exec ports of the
    # remote-terminal transport (pm-message-routing.md §5.2, §7.2). Nothing here adds, logs in or removes a machine.

    def machines(self) -> list[dict[str, Any]] | None:
        """`hc machine ls`: each machine's `name`, `state` (connecting | connected | needs_login | unreachable) and
        `since_ms`; None when the local core cannot be asked (that is not evidence about any machine)."""
        res = self.call("machine", "ls", errors=True)
        if isinstance(res, dict) and isinstance(res.get("machines"), list):
            return [m for m in res["machines"] if isinstance(m, dict)]
        if isinstance(res, list):
            return [m for m in res if isinstance(m, dict)]
        return None

    def file_read(
        self, path: str, *, on: str = "", offset: int | None = None, limit: int | None = None,
        timeout: float = 60,
    ) -> dict[str, Any] | None:
        """`hc file read [--on M] [--offset N] [--limit K] PATH`: `{text, first, last, lines}` or `{error: {kind}}`."""
        args: list[str] = ["file", "read"]
        if on:
            args.extend(("--on", on))
        if offset is not None:
            args.extend(("--offset", str(max(1, int(offset)))))
        if limit is not None:
            args.extend(("--limit", str(max(1, int(limit)))))
        args.extend(("--", path))
        res = self.call(*args, errors=True, timeout=timeout)
        return res if isinstance(res, dict) else None

    def file_write(self, path: str, text: str, *, on: str = "", timeout: float = 60) -> dict[str, Any] | None:
        """`hc file write [--on M] PATH` with `text` piped in (missing folders are made): `{path, bytes}` or error."""
        args: list[str] = ["file", "write"]
        if on:
            args.extend(("--on", on))
        args.extend(("--", path))
        res = self.call(*args, errors=True, timeout=timeout, input=text)
        return res if isinstance(res, dict) else None

    def exec(
        self, argv: Iterable[str], *, on: str = "", cwd: str = "", timeout: float = 60, stdin: str | None = None,
    ) -> dict[str, Any] | None:
        """`hc exec [--on M] [--cwd D] [--timeout S] [-i] -- ARGV`: `{code, stdout, stderr, timed_out, ...}` with
        stdout/stderr decoded from base64 to text, or `{error: {kind}}` (`unavailable`: the machine is not reachable)."""
        args: list[str] = ["exec"]
        if on:
            args.extend(("--on", on))
        if cwd:
            args.extend(("--cwd", str(cwd)))
        t_val = max(1, min(600, int(timeout)))
        args.extend(("--timeout", str(t_val)))
        if stdin is not None:
            args.append("--stdin")
        args.append("--")
        args.extend(argv)
        res = self.call(*args, errors=True, timeout=t_val + 15, input=stdin)
        if not isinstance(res, dict):
            return None
        if res.get("error"):
            return res
        out = dict(res)
        for key in ("stdout", "stderr"):
            out[key] = _b64_text(res.get(key))
        return out

    def app_bin(self) -> str:
        """The herdr-app CLI: config.json's "herdr_app", else `herdr-app` on PATH, else `~/.local/bin/herdr-app`."""
        configured = str(self._cfg_dict().get("herdr_app") or "").strip()
        if configured:
            return _exec_bin(configured)
        if shutil.which("herdr-app"):
            return _exec_bin("herdr-app")
        if not osutil.WINDOWS:
            candidate = Path.home() / ".local" / "bin" / "herdr-app"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return "herdr-app"

    def _run_app(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        if self._app_runner is not None:
            return self._app_runner(*args, timeout=timeout)
        return subprocess.run([self.app_bin(), *args], capture_output=True, text=True, timeout=timeout)

    def app_spaces(self) -> list[dict[str, Any]]:
        """The spaces of the open desktop window (`herdr-app ls`), or [] without one."""
        try:
            out = self._run_app("ls", timeout=30)
            return (json.loads(out.stdout).get("spaces") or []) if out.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
            return []

    def app_do(self, command: str, payload: Mapping[str, Any], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        """Run `herdr-app do <command> <json>` (raises OSError/TimeoutExpired like subprocess.run)."""
        return self._run_app("do", command, json.dumps(payload), timeout=timeout)

    def rename_tab(self, terminal: str, name: str, *, wait: float = 15, only_if: str | None = None) -> bool:
        """Rename the desktop tab showing `terminal` in the `herdr-app` document stored in herdr-core."""
        if self._rename_tab_fn is not None:
            return bool(self._rename_tab_fn(terminal, name, wait=wait, only_if=only_if))
        deadline = self._now_ts() + wait
        while True:
            got = (self.rpc("doc.get", {"name": "herdr-app"}) or {}).get("result") or {}
            value, version = got.get("value"), got.get("version")
            tab = next((t for t, terms in _doc_tabs(value) if terminal in terms), None)
            if tab is not None:
                if only_if is not None and tab.get("name") != only_if:
                    return False
                if tab.get("name") == name:
                    return True
                tab["name"] = name
                if "result" in (self.rpc("doc.set", {"name": "herdr-app", "value": value, "version": version}) or {}):
                    return True
            if self._now_ts() >= deadline:
                return False
            self._sleep(1)

    def name_tab(self, terminal: str, name: str, *, only_if: str | None = None, wait: float = 0) -> bool:
        """Rename the desktop tab showing `terminal` via `herdr-app`, falling back to `rename_tab` when configured."""
        if self._name_tab_fn is not None:
            kw: dict[str, Any] = {}
            if only_if is not None:
                kw["only_if"] = only_if
            if wait != 0:
                kw["wait"] = wait
            return bool(self._name_tab_fn(terminal, name, **kw) if kw else self._name_tab_fn(terminal, name))
        deadline = self._now_ts() + wait
        while True:
            try:
                out = self._run_app("ls", timeout=30)
            except FileNotFoundError:
                if self._tabs_cfg().get("rename_via_core") is True:
                    rem = max(0, deadline - self._now_ts())
                    return self.rename_tab(terminal, name, wait=rem, only_if=only_if)
                return False
            except (OSError, subprocess.TimeoutExpired):
                return False
            try:
                spaces = (json.loads(out.stdout).get("spaces") or []) if out.returncode == 0 else []
                for tab in (tab for space in spaces for tab in space.get("tabs") or []):
                    if any(t.get("terminal") == terminal for t in tab.get("terminals") or []):
                        if only_if is not None and tab.get("name") != only_if:
                            return False
                        if tab.get("name") == name:
                            return True
                        self._run_app("do", "tab.rename", json.dumps({"id": tab["id"], "name": name}), timeout=30)
                        return True
            except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
                return False
            if self._now_ts() >= deadline:
                return False
            self._sleep(1)

    def new_tabs(self, *, caller_pane: str = "") -> bool:
        """Whether each worker gets a desktop tab of its own (`tabs.new_tab` and caller is in hc)."""
        return self._tabs_cfg().get("new_tab") is True and caller_pane.startswith("hc:")

    def worker_tab(
        self,
        made: str,
        task_id: str,
        name: str,
        *,
        parent: str = "",
        caller_pane: str = "",
    ) -> bool:
        """Label a new worker terminal and, with `tabs.new_tab`, give it its own tab in the caller's space."""
        if self._worker_tab_fn is not None:
            return bool(self._worker_tab_fn(made, task_id, name, parent) if parent else self._worker_tab_fn(made, task_id, name))
        labels = [f"task={task_id}"] + ([f"parent={parent}", f"category={parent}"] if parent else [])
        space = ""
        if self.new_tabs(caller_pane=caller_pane):
            pm_info = self.get(caller_pane[3:])
            space = pm_info.label("herdr.space") if pm_info is not None else ""
            if space:
                labels += [f"herdr.space={space}", f"herdr.tab=tb{os.urandom(16).hex()}"]
        self.label(made, *labels)
        return bool(space and name) and self.name_tab(made, name, wait=15)

    def change_waiter(
        self,
        paths: Any = (),
        hc_args: Any = None,
        files: Any = (),
        terminals: Iterable[str] | None = None,
        folders: Any = (),
    ) -> Any:
        if self._waiter_factory is not None:
            kw: dict[str, Any] = {}
            if files:
                kw["files"] = files
            if terminals is not None:
                kw["terminals"] = terminals
            if folders:
                kw["folders"] = folders
            if hc_args is not None:
                return self._waiter_factory(paths, hc_args, **kw) if kw else self._waiter_factory(paths, hc_args)
            return self._waiter_factory(paths, **kw) if kw else self._waiter_factory(paths)
        if events_mod.ChangeWaiter is None:
            return events_mod.TimedLooks()
        more = {**({"terminals": terminals} if terminals is not None else {}), **({"folders": folders} if folders else {})}
        return events_mod.ChangeWaiter(paths, hc_args, files=files, hc=self.bin(), **more)


def hc_bin():
    """The herdr-core CLI: config.json's "hc" (its path, for a machine where hc is on an interactive shell's PATH
    only, so a hook or a script started from elsewhere does not find it), else `hc` from PATH."""
    return str(config_mod.config().get("hc") or "hc")


def hc(*args, errors=False, env=None, timeout=60):
    """Parsed JSON of a herdr-core CLI call, or None when hc is missing or the call fails.
    With errors, a failed call returns hc's error object instead ({"error": {"kind": "not_found", ...}}).
    env: the environment of the call, which `hc run` hands to the terminal it starts (default: this one's).
    timeout: seconds; a send that hc holds back for the user's draft, or a wait, needs more than the default."""
    try:
        # --json goes before a "--": what follows that belongs to the program being started.
        cut = args.index("--") if "--" in args else len(args)
        out = subprocess.run([_exec_bin(hc_bin(), env=env), *args[:cut], "--json", *args[cut:]], capture_output=True, text=True,
                             timeout=timeout, env=env)
        if out.returncode != 0:
            return json.loads(out.stderr or "null") if errors else None
        return json.loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


_DEFAULT_HC = hc


def hc_rpc(method, params):
    """One call of herdr-core's protocol (`hc connect`, JSON-RPC over stdin and stdout): the reply, or None."""
    try:
        out = subprocess.run([_exec_bin(hc_bin()), "connect"], capture_output=True, text=True, timeout=20,
                             input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n")
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.stdout.splitlines():
        with contextlib.suppress(ValueError):
            reply = json.loads(line)
            if isinstance(reply, dict) and reply.get("id") == 1:
                return reply
    return None


def start_hc_terminal(name, cwd, argv, placement, labels=(), env=None):
    """Start an agent in a herdr-core terminal (`hc run --bg`). Shared by dispatch and helper start."""
    label_args = [x for kv in labels for x in ("--label", kv)]
    kwargs = {"env": env} if env is not None else {}
    return (hc("run", "--bg", *placement, *label_args, "--name", name, "--cwd", str(cwd), "--", *argv, **kwargs)
            or {}).get("address")


def all_hc_rows():
    """Every herdr-core terminal on this computer (`hc ls --all`), ({live}, {ended}) by address,
    or (None, None) when hc cannot say."""
    listing = hc("ls", "--all")
    if not isinstance(listing, dict) or not isinstance(listing.get("terminals"), list):
        return None, None
    live, ended = {}, {}
    for t in listing["terminals"]:
        addr = t.get("address")
        if not addr:
            continue
        if t.get("state", "live") == "live":
            live[addr] = t
        else:
            ended[addr] = t
    return live, ended


def live_hc_rows():
    """The live herdr-core terminals on this computer, {address: its `hc ls` row}, or None when hc cannot say."""
    listing = hc("ls")
    if not isinstance(listing, dict) or not isinstance(listing.get("terminals"), list):
        return None
    return {t.get("address"): t for t in listing["terminals"] if t.get("state", "live") == "live"}


def live_hc_terminals():
    """Addresses of the live herdr-core terminals on this computer, or None when hc cannot say."""
    rows = live_hc_rows()
    return None if rows is None else set(rows)


_DEFAULT_LIVE_HC_TERMINALS = live_hc_terminals


def worker_state(term):
    """Why the worker in a herdr-core terminal is not working: idle, done, blocked, error, exited or removed.
    "" while it works, and when nothing is known (no hc terminal, hc unavailable)."""
    info = hc("get", term, errors=True) if term else None
    if not info:
        return ""
    if (info.get("error") or {}).get("kind") == "not_found":
        return "removed"
    if info.get("error"):
        return ""
    if info.get("state") != "live":
        return "exited"
    state = (info.get("status") or {}).get("state")
    return state if state in ("idle", "done", "blocked", "error") else ""
