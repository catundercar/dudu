"""Shared in-memory test doubles and isolated Context factory for `pmlib` unit tests."""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Iterable, Mapping

from pmlib import osutil, procs as procs_mod
from pmlib.agents.registry import AgentRegistry
from pmlib.caller import Caller
from pmlib.config import Config
from pmlib.context import BufferOutput, Context
from pmlib.errors import IdentityError
from pmlib.gitrepo import GitResult
from pmlib.home import Home
from pmlib.store import FileStore
from pmlib.terminals.hc import TerminalInfo


class FakeClock:
    """Deterministic wall and monotonic clock for tests (sleep advances virtual time without waiting)."""

    def __init__(
        self,
        now: datetime.datetime | str | None = None,
        *,
        mono: float = 0.0,
    ) -> None:
        self._now = self._parse(now) if now is not None else datetime.datetime(2026, 11, 22, 12, 0, 0)
        self._mono = float(mono)
        self.sleeps: list[float] = []

    @staticmethod
    def _parse(value: datetime.datetime | str) -> datetime.datetime:
        if isinstance(value, datetime.datetime):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.datetime.strptime(text, fmt)
            except ValueError:
                continue
        raise ValueError(f"unsupported time string: {value!r}")

    def set(self, now: datetime.datetime | str) -> None:
        self._now = self._parse(now)

    def advance(self, seconds: float) -> None:
        dt = max(0.0, float(seconds))
        self._mono += dt
        self._now += datetime.timedelta(seconds=dt)

    def datetime_now(self) -> datetime.datetime:
        return self._now

    def now(self) -> str:
        return self._now.strftime("%Y-%m-%d %H:%M")

    def now_sec(self) -> str:
        return self._now.strftime("%Y-%m-%d %H:%M:%S")

    def time(self) -> float:
        return self._now.timestamp()

    def monotonic(self) -> float:
        return self._mono

    def sleep(self, seconds: float) -> None:
        dt = max(0.0, float(seconds))
        self.sleeps.append(dt)
        self.advance(dt)

    def seconds_since(self, at: Any) -> float:
        try:
            when = datetime.datetime.strptime(str(at)[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return float("inf")
        return (self._now - when).total_seconds()


class FakeChangeWaiter:
    """Deterministic ChangeWaiter stand-in tracking subscribed terminals and wait calls."""

    def __init__(
        self,
        results: Iterable[bool] | None = None,
        *,
        paths: Any = (),
        hc_args: Any = None,
        files: Any = (),
        terminals: Iterable[str] | None = None,
        folders: Any = (),
        on_wait: Callable[[float], Any] | None = None,
        clock: FakeClock | None = None,
    ) -> None:
        self.paths = list(paths)
        self.hc_args = hc_args
        self.files = list(files)
        self.terminals: set[str] | None = set(terminals) if terminals is not None else None
        self.folders = list(folders)
        self._results = list(results) if results is not None else None
        self._on_wait = on_wait
        self._clock = clock
        self.waits: list[float] = []
        self.follow_calls: list[Any] = []
        self.wakes = 0
        self.closed = False

    def __enter__(self) -> FakeChangeWaiter:
        return self

    def __exit__(self, *_: Any) -> None:
        self.closed = True

    def wake(self) -> None:
        self.wakes += 1

    def follow(self, hc_args: Any) -> None:
        self.follow_calls.append(hc_args)

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        if self._on_wait is not None:
            self._on_wait(timeout)
        elif self._clock is not None:
            self._clock.advance(min(float(timeout), 1.0))
        if self._results is not None:
            return bool(self._results.pop(0)) if self._results else False
        return True


def _strip_hc_prefix(address: str) -> str:
    return address[3:] if address.startswith("hc:") else address


def _normalize_term_entry(address: str, item: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(item, str):
        if item in ("exited", "gone", "removed"):
            return {"address": address, "id": address, "state": "exited"}
        return {"address": address, "id": address, "state": "live", "status": {"state": item}}
    row = copy.deepcopy(item)
    row.setdefault("address", address)
    row.setdefault("id", address)
    row.setdefault("state", "live")
    return row


def _take_cli_opts(
    args: list[str],
    value_flags: set[str] | frozenset[str],
    bool_flags: set[str] | frozenset[str] = frozenset(),
) -> tuple[dict[str, list[str] | bool], list[str], list[str]]:
    """Scan known CLI flags anywhere before `--`, keeping positionals and literal `--` tail."""
    opts: dict[str, list[str] | bool] = {}
    pos: list[str] = []
    after_dd: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            after_dd = list(args[i + 1:])
            break
        if tok in value_flags:
            if i + 1 < len(args):
                bucket = opts.setdefault(tok, [])
                if isinstance(bucket, list):
                    bucket.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        if tok.startswith("--") and "=" in tok:
            flag, val = tok.split("=", 1)
            if flag in value_flags:
                bucket = opts.setdefault(flag, [])
                if isinstance(bucket, list):
                    bucket.append(val)
                i += 1
                continue
        if tok in bool_flags:
            opts[tok] = True
            i += 1
            continue
        pos.append(tok)
        i += 1
    return opts, pos, after_dd


def _opt_first(opts: Mapping[str, list[str] | bool], flag: str, default: str = "") -> str:
    val = opts.get(flag)
    return val[0] if isinstance(val, list) and val else default


class FakeHc:
    """In-memory fake for herdr-core (`hc`, `hc_rpc`, tabs, and `ChangeWaiter`)."""

    def __init__(
        self,
        terminals: Mapping[str, dict[str, Any] | list[dict[str, Any] | str]] | None = None,
        *,
        rpc_handler: Callable[[str, Any], Any] | None = None,
        server_running: bool = True,
        app_available: bool = True,
        tab_names: Mapping[str, str] | None = None,
        clock: FakeClock | None = None,
        waiter_results: Iterable[bool] | None = None,
        config: Any = None,
        strict_ls: bool = False,
    ) -> None:
        self.terminals: dict[str, dict[str, Any] | list[dict[str, Any] | str]] = {
            _strip_hc_prefix(k): copy.deepcopy(v) for k, v in (terminals or {}).items()
        }
        self._queue_started: dict[str, list[Any]] = {}
        self.calls: list[tuple[Any, ...]] = []
        self.sent: list[tuple[str, str]] = []
        self.rpc_calls: list[tuple[str, Any]] = []
        self.tab_calls: list[dict[str, Any]] = []
        self.waiters: list[FakeChangeWaiter] = []
        self.tab_names: dict[str, str] = {_strip_hc_prefix(k): str(v) for k, v in (tab_names or {}).items()}
        self._next_id = 1
        self._rpc_handler = rpc_handler
        self.server_running: bool = bool(server_running)
        self.app_available: bool = bool(app_available)
        self._clock = clock
        self._config = config
        self.strict_ls: bool = bool(strict_ls)
        self._waiter_results = list(waiter_results) if waiter_results is not None else None
        self.last_worker_info: dict[str, Any] | None = None

    @property
    def _server_running(self) -> bool:
        return self.server_running

    @_server_running.setter
    def _server_running(self, value: bool) -> None:
        self.server_running = bool(value)

    def _get_entry(self, address: str, *, consume: bool) -> dict[str, Any] | None:
        key = _strip_hc_prefix(address)
        entry = self.terminals.get(key)
        if entry is None:
            self._queue_started.pop(key, None)
            return None
        if isinstance(entry, list):
            if not entry:
                return None
            if consume:
                if self._queue_started.get(key) is not entry:
                    self._queue_started[key] = entry
                elif len(entry) > 1:
                    entry.pop(0)
            return _normalize_term_entry(key, entry[0])
        self._queue_started.pop(key, None)
        return _normalize_term_entry(key, entry)

    def _mutable_dict(self, address: str) -> dict[str, Any] | None:
        key = _strip_hc_prefix(address)
        entry = self.terminals.get(key)
        if entry is None:
            return None
        if isinstance(entry, list):
            if not entry:
                return None
            if isinstance(entry[0], str):
                entry[0] = _normalize_term_entry(key, entry[0])
            else:
                entry[0].setdefault("address", key)
                entry[0].setdefault("id", key)
                entry[0].setdefault("state", "live")
            return entry[0]
        entry.setdefault("address", key)
        entry.setdefault("id", key)
        entry.setdefault("state", "live")
        return entry

    def __call__(self, *args: Any, errors: bool = False, env: Any = None, timeout: float = 60) -> Any:
        return self.hc(*args, errors=errors, env=env, timeout=timeout)

    def hc(self, *args: Any, errors: bool = False, env: Any = None, timeout: float = 60) -> Any:
        self.calls.append(args)
        if not self.server_running:
            return None
        if not args:
            return {"error": {"kind": "usage", "message": "no command"}} if errors else None
        cmd, rest = str(args[0]), [str(a) for a in args[1:]]
        if cmd == "get":
            _, pos, after_dd = _take_cli_opts(rest, set())
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "get missing terminal"}} if errors else None
            return self.get_raw(args_all[0], errors=errors)
        if cmd == "ls":
            opts, _, _ = _take_cli_opts(rest, set(), {"--all"})
            return self._ls_raw(all=bool(opts.get("--all")))
        if cmd == "run":
            opts, pos, after_dd = _take_cli_opts(
                rest,
                {"--name", "--cwd", "--label", "--parent", "--tab", "--space"},
                {"--bg", "--keep", "--no-parent", "--outlive-parent", "--no-notify"},
            )
            argv = pos + after_dd
            labels = opts.get("--label")
            return self.run(
                argv,
                name=_opt_first(opts, "--name"),
                cwd=_opt_first(opts, "--cwd"),
                labels=labels if isinstance(labels, list) else (),
                bg=bool(opts.get("--bg")),
                parent=_opt_first(opts, "--parent"),
                keep=bool(opts.get("--keep")),
                no_parent=bool(opts.get("--no-parent")),
                env=env,
            )
        if cmd == "send":
            opts, pos, after_dd = _take_cli_opts(rest, {"--if", "--timeout"}, {"--no-enter"})
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "send missing terminal"}} if errors else None
            if_state = _opt_first(opts, "--if") or None
            timeout_raw = _opt_first(opts, "--timeout")
            send_timeout = float(timeout_raw) if timeout_raw else timeout
            return self.send(
                args_all[0],
                args_all[1] if len(args_all) > 1 else "",
                if_state=if_state,
                timeout=send_timeout,
                errors=errors,
            )
        if cmd == "label":
            _, pos, after_dd = _take_cli_opts(rest, set())
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "label missing terminal"}} if errors else None
            return self.label(args_all[0], *args_all[1:], errors=errors)
        if cmd == "keep":
            _, pos, after_dd = _take_cli_opts(rest, set())
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "keep missing terminal"}} if errors else None
            return self.keep(args_all[0], errors=errors)
        if cmd == "keys":
            _, pos, after_dd = _take_cli_opts(rest, set())
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "keys missing terminal"}} if errors else None
            return self.keys(args_all[0], *args_all[1:], errors=errors)
        if cmd == "read":
            opts, pos, after_dd = _take_cli_opts(rest, {"--lines"})
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "read missing terminal"}} if errors else None
            lines_raw = _opt_first(opts, "--lines")
            lines = int(lines_raw) if lines_raw else None
            return self._read_raw(args_all[0], lines=lines, errors=errors)
        if cmd == "kill":
            _, pos, after_dd = _take_cli_opts(rest, set(), {"--force"})
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "kill missing terminal"}} if errors else None
            return self.kill(args_all[0], errors=errors)
        if cmd == "rm":
            _, pos, after_dd = _take_cli_opts(rest, set(), {"--force"})
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "rm missing terminal"}} if errors else None
            return self.remove(args_all[0], errors=errors)
        if cmd == "interrupt":
            opts, pos, after_dd = _take_cli_opts(rest, {"--timeout"})
            args_all = pos + after_dd
            if not args_all:
                return {"error": {"kind": "usage", "message": "interrupt missing terminal"}} if errors else None
            t_raw = _opt_first(opts, "--timeout")
            int_timeout = float(t_raw) if t_raw else None
            return self.interrupt(args_all[0], timeout=int_timeout, errors=errors)
        if cmd == "server" and rest[:1] == ["status"]:
            return {"running": True}
        return {"error": {"kind": "unknown_command", "message": f"fake hc has no {cmd}"}} if errors else None

    def bin(self) -> str:
        return "hc"

    def call(self, *args: Any, errors: bool = False, env: Any = None, timeout: float = 60) -> Any:
        return self.hc(*args, errors=errors, env=env, timeout=timeout)

    def get_raw(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        row = self._get_entry(term, consume=True)
        if row is None:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        return row

    def get(self, term: str) -> TerminalInfo | None:
        raw = self.get_raw(term)
        if not raw or raw.get("error"):
            return None
        return TerminalInfo.from_dict(raw)

    @staticmethod
    def _project_ls_row(row: dict[str, Any], *, strict_ls: bool) -> dict[str, Any]:
        """Project a full `hc get` dict into `hc ls --json` shape (string `status`, no `pid`/`argv`/`screen`).

        Real `hc ls --all --json` emits only summary keys (`address`, `agent`, `cwd`, `exit_code`, `name`,
        `parent`, `reason`, `signal`, `state`, `status` as `str`, `turn`, `where`) and omits `labels`;
        `strict_ls=True` also omits `labels` (kept when False until `homemove.py` stops reading `labels` from `ls`).
        """
        out: dict[str, Any] = {}
        get_only = {
            "pid", "argv", "foreground", "status_ms", "created_ms", "finished_ms",
            "screen", "reported", "keep", "received", "keys", "interrupted", "interrupt_timeout",
        }
        if strict_ls:
            get_only.add("labels")
        for k, v in row.items():
            if k in get_only:
                continue
            if k == "status":
                state_str = str(v.get("state") or "") if isinstance(v, Mapping) else str(v or "")
                if state_str:
                    out["status"] = state_str
                continue
            out[k] = v
        return out

    def _ls_raw(self, *, all: bool = False) -> dict[str, list[dict[str, Any]]] | None:
        if not self.server_running:
            return None
        rows = []
        for addr in sorted(self.terminals):
            row = self._get_entry(addr, consume=False)
            if row is not None and (all or row.get("state", "live") == "live"):
                rows.append(self._project_ls_row(row, strict_ls=self.strict_ls))
        return {"terminals": rows}

    def ls(self, *, all: bool = False) -> list[TerminalInfo] | None:
        raw = self._ls_raw(all=all)
        if raw is None:
            return None
        return [TerminalInfo.from_dict(r) for r in raw["terminals"]]

    def all_rows(self) -> tuple[dict[str, TerminalInfo] | None, dict[str, TerminalInfo] | None]:
        rows = self.ls(all=True)
        if rows is None:
            return None, None
        live = {info.address: info for info in rows if info.is_live}
        ended = {info.address: info for info in rows if not info.is_live}
        return live, ended

    def live_rows(self) -> dict[str, TerminalInfo] | None:
        rows = self.ls(all=False)
        if rows is None:
            return None
        return {info.address: info for info in rows}

    def live_terminals(self) -> set[str] | None:
        rows = self.live_rows()
        return None if rows is None else set(rows)

    def worker_state(self, term: str) -> str:
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
        parent: str = "",
        keep: bool = False,
        no_parent: bool = False,
        placement: Iterable[str] = (),
        env: Any = None,
    ) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        p_opts, _, _ = _take_cli_opts(
            [str(x) for x in placement],
            {"--parent", "--tab", "--space"},
            {"--keep", "--no-parent", "--outlive-parent", "--no-notify"},
        )
        parent = parent or _opt_first(p_opts, "--parent")
        keep = bool(keep or p_opts.get("--keep"))
        no_parent = bool(no_parent or p_opts.get("--no-parent"))
        while f"t{self._next_id}" in self.terminals:
            self._next_id += 1
        addr = f"t{self._next_id}"
        self._next_id += 1
        parsed_labels = dict(kv.split("=", 1) for kv in labels if "=" in kv)
        row: dict[str, Any] = {
            "address": addr,
            "id": addr,
            "state": "live",
            "name": name or addr,
            "cwd": str(cwd),
            "argv": list(argv),
            "labels": parsed_labels,
            "status": {"state": "idle"},
            "foreground": {"argv": list(argv)},
        }
        if parent and not no_parent:
            row["parent"] = parent
        if keep:
            row["keep"] = True
        self.terminals[addr] = row
        return copy.deepcopy(row)

    def start_terminal(
        self,
        name: str,
        cwd: str | Path,
        argv: Iterable[str],
        placement: Iterable[str] = (),
        labels: Iterable[str] = (),
        env: Any = None,
    ) -> str | None:
        res = self.run(argv, name=name, cwd=cwd, labels=labels, bg=True, placement=placement, env=env)
        return res.get("address") if isinstance(res, dict) else None

    def server_status(self) -> dict[str, Any] | None:
        return {"running": True} if self.server_running else None

    def send(
        self,
        term: str,
        text: str,
        *,
        if_state: str | None = None,
        timeout: float = 180,
        errors: bool = False,
    ) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        key = _strip_hc_prefix(term)
        row = self._mutable_dict(key)
        if row is None:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        if row.get("state") != "live":
            return {"error": {"kind": "not_live", "message": f"terminal {key} is not live"}} if errors else None
        cur_status = (row.get("status") or {}).get("state")
        if if_state is not None and cur_status != if_state:
            return {"ok": True, "started": False}
        row.setdefault("received", []).append(text)
        self.sent.append((key, text))
        return {"ok": True, "started": True}

    def label(self, term: str, *pairs: str, errors: bool = False) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        row = self._mutable_dict(term)
        if row is None:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        labels = row.setdefault("labels", {})
        for kv in pairs:
            key, _, val = kv.partition("=")
            if val:
                labels[key] = val
            else:
                labels.pop(key, None)
        return copy.deepcopy(row)

    def keep(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        row = self._mutable_dict(term)
        if row is None:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        row["keep"] = True
        return {"ok": True}

    def keys(self, term: str, *keys: str, errors: bool = False) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        row = self._mutable_dict(term)
        if row is None:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        row.setdefault("keys", []).append(list(keys))
        return {"ok": True}

    def _read_raw(self, term: str, *, lines: int | None = None, errors: bool = False) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        row = self._get_entry(term, consume=False)
        if row is None:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        text = str(row.get("screen") or "")
        if lines is not None and text:
            text = "\n".join(text.splitlines()[-lines:]) if lines > 0 else ""
        return {"text": text}

    def read(self, term: str, *, lines: int | None = None) -> str:
        raw = self._read_raw(term, lines=lines)
        return str((raw or {}).get("text") or "") if isinstance(raw, dict) else ""

    def screen_line(self, term: str, width: int = 160) -> str:
        raw = self.read(term)
        lines = [s.strip() for s in raw.splitlines() if s.strip().strip("─━│╭╮╰╯ ")]
        return osutil.clip(" / ".join(lines[:3]), width) or "(empty screen)"

    def kill(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        row = self._mutable_dict(term)
        if row is None:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        row["state"] = "exited"
        return {"ok": True}

    def remove(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        key = _strip_hc_prefix(term)
        if key not in self.terminals:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        del self.terminals[key]
        self._queue_started.pop(key, None)
        return {"ok": True}

    def interrupt(self, term: str, *, timeout: float | None = None, errors: bool = False) -> dict[str, Any] | None:
        if not self.server_running:
            return None
        row = self._mutable_dict(term)
        if row is None:
            return {"error": {"kind": "not_found", "message": f"no terminal {term}"}} if errors else None
        row["interrupted"] = True
        if timeout is not None:
            row["interrupt_timeout"] = timeout
        return {"ok": True}

    def rpc(self, method: str, params: Any = None) -> Any:
        self.rpc_calls.append((method, params))
        if not self.server_running:
            return None
        if self._rpc_handler is not None:
            return self._rpc_handler(method, params)
        return None

    def name_tab(self, terminal: str, name: str, only_if: str | None = None, wait: float = 0) -> bool:
        key = _strip_hc_prefix(terminal)
        self.tab_calls.append({"fn": "name_tab", "terminal": key, "name": name, "only_if": only_if, "wait": wait})
        if not self.app_available:
            if self._tabs_cfg().get("rename_via_core") is True:
                return self.rename_tab(terminal, name, wait=wait, only_if=only_if)
            return False
        if key not in self.terminals and key not in self.tab_names:
            return False
        if only_if is not None and self.tab_names.get(key, "") != only_if:
            return False
        self.tab_names[key] = name
        return True

    def rename_tab(self, terminal: str, name: str, wait: float = 15, only_if: str | None = None) -> bool:
        key = _strip_hc_prefix(terminal)
        self.tab_calls.append({"fn": "rename_tab", "terminal": key, "name": name, "only_if": only_if, "wait": wait})
        if not self.server_running:
            return False
        if key not in self.terminals and key not in self.tab_names:
            return False
        if only_if is not None and self.tab_names.get(key, "") != only_if:
            return False
        self.tab_names[key] = name
        return True

    def app_spaces(self) -> list[dict[str, Any]]:
        if not self.app_available:
            return []
        tabs = [
            {"id": f"tab-{addr}", "name": name, "terminals": [{"terminal": addr}]}
            for addr, name in sorted(self.tab_names.items())
        ]
        return [{"id": "s1", "tabs": tabs}] if tabs else []

    def app_do(self, command: str, payload: Mapping[str, Any], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        self.tab_calls.append({"fn": "app_do", "command": command, "payload": dict(payload), "timeout": timeout})
        if not self.app_available:
            raise FileNotFoundError("herdr-app")
        return subprocess.CompletedProcess(["herdr-app", "do", command, json.dumps(payload)], 0, '{"ok": true}', "")

    def _tabs_cfg(self) -> dict[str, Any]:
        if self._config is None:
            return {}
        if callable(self._config):
            data = self._config()
        else:
            read = getattr(self._config, "read", None)
            data = read() if callable(read) else self._config
        tabs = data.get("tabs") if isinstance(data, dict) else None
        return tabs if isinstance(tabs, dict) else {}

    def new_tabs(self, *, caller_pane: str = "") -> bool:
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
        *,
        hc: Any = None,
        warn: Any = None,
    ) -> FakeChangeWaiter:
        results = list(self._waiter_results) if self._waiter_results is not None else None
        waiter = FakeChangeWaiter(
            results,
            paths=paths,
            hc_args=hc_args,
            files=files,
            terminals=terminals,
            folders=folders,
            clock=self._clock,
        )
        self.waiters.append(waiter)
        return waiter


class FakeTui:
    """In-memory fake for Herdr TUI (`herdr ...`) sessions, workspaces, panes, agents, and worktrees."""

    def __init__(
        self,
        *,
        agents: list[dict[str, Any]] | None = None,
        panes: list[dict[str, Any]] | None = None,
        workspaces: list[dict[str, Any]] | None = None,
        sessions: list[dict[str, Any]] | None = None,
        worktrees: list[dict[str, Any]] | None = None,
        process_info: Mapping[str, dict[str, Any]] | None = None,
        pane_screens: Mapping[str, str] | None = None,
        wait_results: Iterable[bool] | None = None,
        prompt_results: Iterable[bool] | None = None,
        current_session: str = "default",
        server_ok: bool = True,
    ) -> None:
        self._agents: list[dict[str, Any]] = copy.deepcopy(agents or [])
        self._panes: dict[str, dict[str, Any]] = {
            p["pane_id"]: copy.deepcopy(p) for p in (panes or []) if p.get("pane_id")
        }
        self._workspaces: list[dict[str, Any]] = copy.deepcopy(workspaces or [])
        self._sessions: list[dict[str, Any]] = copy.deepcopy(sessions or [])
        self._worktrees: list[dict[str, Any]] = copy.deepcopy(worktrees or [])
        self._process_info: dict[str, dict[str, Any]] = copy.deepcopy(dict(process_info or {}))
        self._pane_screens: dict[str, str] = {str(k): str(v) for k, v in (pane_screens or {}).items()}
        self._wait_results = list(wait_results) if wait_results is not None else None
        self._prompt_results = list(prompt_results) if prompt_results is not None else None
        self.current_session = current_session
        self.server_ok = server_ok
        self.calls: list[tuple[str | None, tuple[Any, ...]]] = []
        self.prompts: list[tuple[str, str]] = []
        self.ran: list[tuple[str, str]] = []
        self.sent_keys: list[tuple[str, list[str]]] = []
        self.waits: list[tuple[str, list[str], str]] = []
        self._next_pane = 100
        self._next_ws = 1

    @staticmethod
    def _filter_session(items: list[dict[str, Any]], session: str | None) -> list[dict[str, Any]]:
        if session is None:
            return items
        return [x for x in items if x.get("session") in (None, session)]

    @staticmethod
    def _same_path(a: str, b: str) -> bool:
        if not a or not b:
            return False
        if a == b:
            return True
        try:
            return Path(a).resolve() == Path(b).resolve()
        except OSError:
            return False

    def _alloc_workspace_id(self) -> str:
        used: set[str] = {str(w.get("workspace_id") or "") for w in self._workspaces}
        used.update(str(p.get("workspace_id") or "") for p in self._panes.values())
        used.update(
            str(w.get("open_workspace_id") or w.get("workspace_id") or "")
            for w in self._worktrees
        )
        while f"w{self._next_ws}" in used:
            self._next_ws += 1
        ws_id = f"w{self._next_ws}"
        self._next_ws += 1
        return ws_id

    def __call__(self, *args: Any, session: str | None = None) -> Any:
        return self.herdr(*args, session=session)

    def call(self, *args: Any, session: str | None = None) -> Any:
        return self.herdr(*args, session=session)

    def strict(self, *args: Any, session: str | None = None) -> dict[str, Any]:
        result = self.herdr(*args, session=session)
        if not isinstance(result, dict):
            raise IdentityError(f"cannot verify herdr {session or 'current'} {' '.join(str(a) for a in args)}")
        return result

    def herdr(self, *args: Any, session: str | None = None) -> Any:
        self.calls.append((session, args))
        if not self.server_ok:
            return None
        parts = [str(a) for a in args]
        if parts[:2] == ["agent", "list"]:
            return {"agents": copy.deepcopy(self._filter_session(self._agents, session))}
        if parts[:2] == ["agent", "start"]:
            opts, pos, after_dd = _take_cli_opts(parts[2:], {"--kind", "--pane"})
            name = pos[0] if pos else ""
            pane = _opt_first(opts, "--pane")
            if not name or not pane:
                return None
            kind = _opt_first(opts, "--kind")
            pane_row = self._panes.get(pane)
            if pane_row is not None:
                ws_id = str(pane_row.get("workspace_id") or (pane.split(":", 1)[0] if ":" in pane else "w1"))
                pane_row["workspace_id"] = ws_id
            else:
                ws_id = pane.split(":", 1)[0] if ":" in pane else "w1"
                pane_row = {"pane_id": pane, "workspace_id": ws_id}
                if session:
                    pane_row["session"] = session
                self._panes[pane] = pane_row
            pane_row["agent"] = kind or name
            pane_row["agent_name"] = name
            pane_row["agent_status"] = "idle"
            agent_row: dict[str, Any] = {
                "name": name,
                "pane_id": pane,
                "workspace_id": ws_id,
                "kind": kind,
                "agent": kind or name,
                "agent_status": "idle",
                "argv": list(after_dd),
            }
            if session:
                agent_row["session"] = session
            self._agents = [
                a for a in self._agents
                if not (a.get("pane_id") == pane and (session is None or a.get("session") in (None, session)))
            ]
            self._agents.append(agent_row)
            return {"ok": True, "name": name, "pane_id": pane, "workspace_id": ws_id}
        if parts[:2] == ["agent", "send-keys"]:
            if len(parts) < 3:
                return None
            self.sent_keys.append((parts[2], parts[3:]))
            return {"ok": True}
        if parts[:2] == ["agent", "rename"] and len(parts) >= 4:
            pane, new_name = parts[2], parts[3]
            scoped = self._filter_session(self._agents, session)
            if any(a.get("name") == new_name and a.get("pane_id") != pane for a in scoped):
                return None
            for agent in scoped:
                if agent.get("pane_id") == pane:
                    agent["name"] = new_name
                    pane_row = self._panes.get(pane)
                    if pane_row is not None and (session is None or pane_row.get("session") in (None, session)):
                        pane_row["agent_name"] = new_name
                    return {"ok": True}
            return None
        if parts[:2] == ["agent", "prompt"] and len(parts) >= 4:
            self.prompts.append((parts[2], parts[3]))
            if self._prompt_results is not None:
                ok = bool(self._prompt_results.pop(0)) if self._prompt_results else False
                return {"ok": True} if ok else None
            return {"ok": True}
        if parts[:2] == ["agent", "wait"]:
            opts, pos, _ = _take_cli_opts(parts[2:], {"--until", "--timeout"})
            target = pos[0] if pos else ""
            until_raw = opts.get("--until")
            until_list = [str(x) for x in until_raw] if isinstance(until_raw, list) else []
            self.waits.append((target, until_list, _opt_first(opts, "--timeout")))
            if self._wait_results is not None:
                ok = bool(self._wait_results.pop(0)) if self._wait_results else False
                return {"ok": True} if ok else None
            return {"ok": True}
        if parts[:2] == ["workspace", "list"]:
            return {"workspaces": copy.deepcopy(self._filter_session(self._workspaces, session))}
        if parts[:2] == ["pane", "list"]:
            return {"panes": copy.deepcopy(self._filter_session(list(self._panes.values()), session))}
        if parts[:2] == ["pane", "get"] and len(parts) >= 3:
            pane = self._panes.get(parts[2])
            if pane is not None and session is not None and pane.get("session") not in (None, session):
                return None
            return {"pane": copy.deepcopy(pane)} if pane is not None else None
        if parts[:2] == ["pane", "read"]:
            opts, pos, after_dd = _take_cli_opts(parts[2:], {"--lines"})
            args_all = pos + after_dd
            if not args_all:
                return None
            pane_id = args_all[0]
            pane_row = self._panes.get(pane_id)
            if session is not None and pane_row is not None and pane_row.get("session") not in (None, session):
                return None
            if pane_id not in self._pane_screens and pane_row is None:
                return None
            lines_raw = _opt_first(opts, "--lines")
            lines = int(lines_raw) if lines_raw else None
            text = self.pane_read(pane_id, lines=lines, session=session)
            return {"text": text}
        if parts[:2] == ["pane", "run"] and len(parts) >= 4:
            self.ran.append((parts[2], parts[3]))
            return {"ok": True}
        if parts[:2] == ["pane", "close"] and len(parts) >= 3:
            pid = parts[2]
            self._panes.pop(pid, None)
            self._pane_screens.pop(pid, None)
            self._agents = [a for a in self._agents if a.get("pane_id") != pid]
            return {"ok": True}
        if parts[:2] == ["pane", "process-info"]:
            opts, pos, _ = _take_cli_opts(parts[2:], {"--pane"})
            pid = _opt_first(opts, "--pane") or (pos[0] if pos else "")
            return {"process_info": copy.deepcopy(self._process_info.get(pid, {}))}
        if parts[:2] == ["tab", "create"]:
            opts, _, _ = _take_cli_opts(parts[2:], {"--workspace", "--cwd", "--label"}, {"--no-focus"})
            self._next_pane += 1
            ws = _opt_first(opts, "--workspace", "w1")
            cwd = _opt_first(opts, "--cwd")
            label = _opt_first(opts, "--label")
            pid = f"{ws}:p{self._next_pane}"
            pane_row = {"pane_id": pid, "workspace_id": ws}
            if cwd:
                pane_row["cwd"] = cwd
            if label:
                pane_row["label"] = label
            if session:
                pane_row["session"] = session
            self._panes[pid] = pane_row
            return {"pane_id": pid, "workspace_id": ws}
        if parts[:2] == ["worktree", "list"]:
            opts, _, _ = _take_cli_opts(parts[2:], {"--cwd"})
            cwd = _opt_first(opts, "--cwd")
            return {"worktrees": self.worktrees(cwd=cwd or None, session=session)}
        if parts[:2] == ["worktree", "create"]:
            opts, pos, after_dd = _take_cli_opts(
                parts[2:],
                {"--cwd", "--branch", "--base", "--label", "--path"},
                {"--no-focus"},
            )
            cwd = _opt_first(opts, "--cwd")
            branch = _opt_first(opts, "--branch")
            base = _opt_first(opts, "--base")
            label = _opt_first(opts, "--label")
            args_all = pos + after_dd
            explicit_path = _opt_first(opts, "--path") or (args_all[0] if args_all else "")
            ws_id = self._alloc_workspace_id()
            self._next_pane += 1
            pane_id = f"{ws_id}:p{self._next_pane}"
            if explicit_path:
                path = explicit_path
            elif cwd and branch:
                path = str(Path(cwd).parent / f"{Path(cwd).name}-{branch.replace('/', '-')}")
            elif cwd:
                path = str(Path(cwd).parent / f"{Path(cwd).name}-{ws_id}")
            else:
                path = f"/worktrees/{ws_id}"
            ws_row: dict[str, Any] = {"workspace_id": ws_id, "label": label, "cwd": path}
            pane_row = {"pane_id": pane_id, "workspace_id": ws_id, "cwd": path, "label": label}
            wt_row: dict[str, Any] = {
                "path": path,
                "branch": branch,
                "base": base,
                "cwd": cwd,
                "label": label,
                "open_workspace_id": ws_id,
                "workspace_id": ws_id,
                "pane_id": pane_id,
            }
            if session:
                ws_row["session"] = session
                pane_row["session"] = session
                wt_row["session"] = session
            self._workspaces.append(ws_row)
            self._panes[pane_id] = pane_row
            self._worktrees.append(wt_row)
            return {"ok": True, "workspace_id": ws_id, "pane_id": pane_id, "path": path}
        if parts[:2] == ["worktree", "remove"]:
            opts, pos, after_dd = _take_cli_opts(parts[2:], {"--workspace", "--path"}, {"--force"})
            ws_id = _opt_first(opts, "--workspace")
            args_all = pos + after_dd
            target_path = _opt_first(opts, "--path") or (args_all[0] if args_all else "")
            if not ws_id and not target_path:
                return None
            matched = [
                w for w in self._worktrees
                if (ws_id and (w.get("open_workspace_id") == ws_id or w.get("workspace_id") == ws_id))
                or (target_path and self._same_path(str(w.get("path") or ""), target_path))
            ]
            matched_ids = {id(w) for w in matched}
            affected_ws = {ws_id} if ws_id else set()
            for w in matched:
                for key in ("open_workspace_id", "workspace_id"):
                    val = str(w.get(key) or "")
                    if val:
                        affected_ws.add(val)
            self._worktrees = [w for w in self._worktrees if id(w) not in matched_ids]
            if affected_ws:
                self._workspaces = [w for w in self._workspaces if w.get("workspace_id") not in affected_ws]
                removed_panes = {pid for pid, p in self._panes.items() if p.get("workspace_id") in affected_ws}
                for pid in removed_panes:
                    self._panes.pop(pid, None)
                    self._pane_screens.pop(pid, None)
                self._agents = [
                    a for a in self._agents
                    if a.get("workspace_id") not in affected_ws and a.get("pane_id") not in removed_panes
                ]
            return {"ok": True}
        return None

    def agents(self, *, session: str | None = None) -> list[dict[str, Any]]:
        if not self.server_ok:
            return []
        return copy.deepcopy(self._filter_session(self._agents, session))

    def panes(self, *, session: str | None = None) -> list[dict[str, Any]] | None:
        if not self.server_ok:
            return None
        return copy.deepcopy(self._filter_session(list(self._panes.values()), session))

    def workspaces(self, *, session: str | None = None) -> list[dict[str, Any]] | None:
        if not self.server_ok:
            return None
        return copy.deepcopy(self._filter_session(self._workspaces, session))

    def sessions(self) -> list[dict[str, Any]]:
        if not self.server_ok:
            raise IdentityError("cannot enumerate herdr sessions: server unavailable")
        return copy.deepcopy(self._sessions)

    def worktrees(self, *, cwd: str | Path | None = None, session: str | None = None) -> list[dict[str, Any]] | None:
        if not self.server_ok:
            return None
        rows = self._filter_session(self._worktrees, session)
        if cwd is not None:
            cwd_str = str(cwd)
            rows = [
                w for w in rows
                if not w.get("cwd") or self._same_path(str(w.get("cwd") or ""), cwd_str)
            ]
        return copy.deepcopy(rows)

    def pane_read(self, pane: str, *, lines: int | None = None, session: str | None = None) -> str:
        if not self.server_ok:
            return ""
        pane_row = self._panes.get(pane)
        if session is not None and pane_row is not None and pane_row.get("session") not in (None, session):
            return ""
        if pane in self._pane_screens:
            text = self._pane_screens[pane]
        elif pane_row is not None:
            text = str(pane_row.get("screen") or "")
        else:
            return ""
        if lines is not None and text:
            text = "\n".join(text.splitlines()[-lines:]) if lines > 0 else ""
        return text

    def socket_session(self, sessions: list[dict[str, Any]] | None = None) -> str:
        if not self.server_ok:
            raise IdentityError("cannot verify caller session: server unavailable")
        known = self.sessions() if sessions is None else sessions
        matches = [s for s in known if s.get("name") == self.current_session and s.get("running")]
        if len(matches) != 1:
            raise IdentityError("cannot verify caller session: inherited socket is not one known running session")
        return self.current_session

    def pane_get(self, pane_id: str, *, session: str | None = None) -> dict[str, Any] | None:
        res = self.herdr("pane", "get", pane_id, session=session)
        return res.get("pane") if isinstance(res, dict) else None

    def pane_run(self, pane_id: str, cmd: str, *, session: str | None = None) -> Any:
        return self.herdr("pane", "run", pane_id, cmd, session=session)

    def pane_close(self, pane_id: str, *, session: str | None = None) -> Any:
        return self.herdr("pane", "close", pane_id, session=session)

    def pane_process_info(self, pane_id: str, *, session: str | None = None) -> dict[str, Any]:
        res = self.herdr("pane", "process-info", "--pane", pane_id, session=session)
        return (res.get("process_info") or {}) if isinstance(res, dict) else {}

    def tab_create(self, *args: Any, session: str | None = None) -> Any:
        return self.herdr("tab", "create", *args, session=session)

    def worktree_create(self, *args: Any, session: str | None = None) -> Any:
        return self.herdr("worktree", "create", *args, session=session)

    def worktree_remove(
        self,
        path: str | Path = "",
        *,
        workspace: str = "",
        force: bool = False,
        session: str | None = None,
    ) -> Any:
        args: list[str] = ["worktree", "remove"]
        if workspace:
            args.extend(("--workspace", workspace))
        if path:
            args.append(str(path))
        if force:
            args.append("--force")
        return self.herdr(*args, session=session)

    def agent_start(
        self,
        name: str,
        *,
        kind: str = "",
        pane: str = "",
        argv: Iterable[str] = (),
        session: str | None = None,
    ) -> Any:
        args: list[str] = ["agent", "start", name]
        if kind:
            args.extend(("--kind", kind))
        if pane:
            args.extend(("--pane", pane))
        argv_list = list(argv)
        if argv_list:
            args.append("--")
            args.extend(argv_list)
        return self.herdr(*args, session=session)

    def agent_send_keys(self, pane_id: str, *keys: str, session: str | None = None) -> Any:
        return self.herdr("agent", "send-keys", pane_id, *keys, session=session)

    def agent_rename(self, pane_id: str, name: str, *, session: str | None = None) -> Any:
        return self.herdr("agent", "rename", pane_id, name, session=session)

    def agent_prompt(self, pane_id: str, text: str, *, session: str | None = None) -> Any:
        return self.herdr("agent", "prompt", pane_id, text, session=session)

    def agent_wait(self, *args: Any, session: str | None = None) -> Any:
        return self.herdr("agent", "wait", *args, session=session)


class _FakePopen:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


class FakeProcs:
    """In-memory Processes port recording detached background `pm.py` spawns."""

    def __init__(
        self,
        home: Home,
        *,
        env: Mapping[str, str] | None = None,
        launcher_path: Path | None = None,
        mark: list[tuple[str, int, int, int]] | None = None,
        runner: Callable[[dict[str, Any]], Any] | None = None,
        spawn_ok: bool = True,
        background_work: Mapping[int, Iterable[str]] | Callable[[Any], Iterable[str]] | None = None,
    ) -> None:
        self.home = home
        self.env: dict[str, str] = dict(env or {})
        self._launcher = Path(launcher_path) if launcher_path is not None else procs_mod.launcher()
        self._mark = list(mark) if mark is not None else [("pm.py", 1, 100, 1)]
        self._runner = runner
        self.spawn_ok = bool(spawn_ok)
        self._background_work = background_work
        self.spawned: list[dict[str, Any]] = []
        self.ran: list[dict[str, Any]] = []
        self._next_pid = 10_000

    def launcher(self) -> Path:
        return self._launcher

    def code_files(self) -> tuple[Path, ...]:
        return (self._launcher,)

    def code_mark(self) -> list[tuple[str, int, int, int]] | None:
        return list(self._mark) if self._mark is not None else None

    def pm_script(self) -> str:
        return f"{osutil.python_command()} {osutil.shell_quote(self._launcher)}"

    def pm_command(self) -> str:
        if not self.env.get("PM_HOME"):
            return self.pm_script()
        if osutil.WINDOWS:
            return f"{self.pm_script()} --home {osutil.shell_quote(self.home.root)}"
        return f"PM_HOME={osutil.shell_quote(str(self.home.root))} {self.pm_script()}"

    def clean_session_env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        cleaned = {k: v for k, v in self.env.items() if k not in procs_mod.SESSION_ENV}
        if extra:
            cleaned.update(extra)
        return cleaned

    def background_work(self, info: Any) -> list[str]:
        if callable(self._background_work):
            return list(self._background_work(info))
        if isinstance(self._background_work, Mapping) and info is not None:
            pid = info.get("pid") if isinstance(info, Mapping) else getattr(info, "pid", None)
            if pid is not None and pid in self._background_work:
                return list(self._background_work[pid])
        return []

    def spawn_pm(
        self,
        args: Iterable[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> _FakePopen | None:
        self._next_pid += 1
        entry = {
            "pid": self._next_pid,
            "args": list(args),
            "env": dict(self.env) if env is None else dict(env),
            "cwd": str(cwd) if cwd is not None else None,
        }
        self.spawned.append(entry)
        if not self.spawn_ok:
            return None
        return _FakePopen(self._next_pid)

    def run(
        self,
        argv: Iterable[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        input: str | None = None,
        capture_output: bool = True,
        text: bool = True,
    ) -> Any:
        argv_list = list(argv)
        entry = {
            "argv": argv_list,
            "env": dict(self.env) if env is None else dict(env),
            "cwd": str(cwd) if cwd is not None else None,
            "timeout": timeout,
            "input": input,
            "capture_output": capture_output,
            "text": text,
        }
        self.ran.append(entry)
        if self._runner is not None:
            return self._runner(entry)
        return subprocess.CompletedProcess(argv_list, 0, "" if text else b"", "" if text else b"")

    def run_spawned(self, runner: Callable[[dict[str, Any]], Any] | None = None) -> list[Any]:
        """Drain and execute recorded spawns inline on demand."""
        fn = runner or self._runner
        batch = list(self.spawned)
        self.spawned.clear()
        if fn is None:
            return batch
        return [fn(item) for item in batch]


class StubGit:
    """In-memory Git stub covering the `pmlib/gitrepo.py` surface without running git."""

    def __init__(
        self,
        *,
        roots: Mapping[str, str] | None = None,
        states: Mapping[tuple[str, str, str], tuple[int | None, int | None]] | None = None,
        worktree_base: Path | None = None,
        base: str = "main",
        git_results: Mapping[tuple[str, ...], str | None] | None = None,
        checkouts: Mapping[tuple[str, str], str] | None = None,
        owned_worktrees: Iterable[str | Path] = (),
        index_locks: Mapping[str, Path | None] | None = None,
        undo_ok: bool = True,
        branches: Iterable[str] | None = None,
        ancestors: Iterable[tuple[str, str]] = (),
        ignored: Iterable[str] = (),
        dirty_files: Mapping[str, str] | None = None,
        merge_conflicts: Mapping[str, list[str]] | None = None,
    ) -> None:
        self.roots = dict(roots or {})
        self.states = dict(states or {})
        self.worktree_base = worktree_base
        self.base = base
        self.git_results = dict(git_results or {})
        self.checkouts = dict(checkouts or {})
        self.owned_worktrees = {str(p) for p in owned_worktrees}
        self.index_locks = dict(index_locks or {})
        self.undo_ok = bool(undo_ok)
        self.branches: set[str] = set(branches) if branches is not None else {base}
        self.branches.update(branch for _, branch in self.checkouts)
        self.ancestors: set[tuple[str, str]] = {(str(a), str(d)) for a, d in ancestors}
        self.ignored: set[str] = {str(p) for p in ignored}
        self.dirty_files: dict[str, str] = {str(k): str(v) for k, v in (dirty_files or {}).items()}
        self.merge_conflicts: dict[str, list[str]] = {str(k): list(v) for k, v in (merge_conflicts or {}).items()}
        self._last_conflicts: dict[str, list[str]] = {}
        self._pending_merge: dict[str, str] = {}
        self.calls: list[tuple[Any, ...]] = []

    def git(self, path: str | Path, *args: str) -> str | None:
        cmd = (str(path), *(str(a) for a in args))
        self.calls.append(("git", *cmd))
        if cmd in self.git_results:
            return self.git_results[cmd]
        key_args = tuple(str(a) for a in args)
        if key_args in self.git_results:
            return self.git_results[key_args]
        return ""

    def main_root(self, path: str | Path) -> str | None:
        key = str(Path(path).resolve())
        return self.roots.get(key)

    def project_root(self, path: str | Path) -> str | None:
        key = str(Path(path).resolve())
        return self.roots.get(key, key if Path(path).is_dir() else None)

    def base_branch(self, repo: str | Path) -> str:
        return self.base

    def merge_target(self, repo: str | Path, base: str) -> str:
        return base or self.base

    def git_state(self, path: str | Path, branch: str | None, base: str) -> tuple[int | None, int | None]:
        return self.states.get((str(path), str(branch or ""), str(base)), (0, 0))

    def is_owned_worktree(self, path: str | Path) -> bool:
        if not path:
            return False
        raw = str(path)
        if raw in self.owned_worktrees:
            return True
        if self.worktree_base is not None:
            try:
                return Path(raw).resolve().is_relative_to(Path(self.worktree_base).resolve())
            except OSError:
                return False
        return False

    def worktree_home(self, repo: str | Path) -> Path:
        base = self.worktree_base or Path("/nonexistent/worktrees")
        return base / Path(repo).name

    def checkout_of(self, repo: str | Path, branch: str) -> str | None:
        return self.checkouts.get((str(repo), str(branch)))

    def undo_merge(self, repo: str | Path) -> bool:
        self.calls.append(("undo_merge", str(repo)))
        if self.undo_ok:
            self._pending_merge.pop(str(repo), None)
            self._last_conflicts.pop(str(repo), None)
        return self.undo_ok

    def index_lock(self, worktree: str | Path) -> Path | None:
        raw = str(worktree)
        if raw in self.index_locks:
            return self.index_locks[raw]
        return None

    def run(self, path: str | Path, *args: str, timeout: float | None = 30) -> str | None:
        return self.git(path, *args)

    def run_raw(self, path: str | Path, *args: str, timeout: float | None = 30) -> GitResult | None:
        out = self.git(path, *args)
        if out is None:
            return GitResult(returncode=1, stdout="", stderr="")
        return GitResult(returncode=0, stdout=out, stderr="")

    def _explicit_git_result(self, path: str | Path, *args: str) -> tuple[bool, str | None]:
        cmd = (str(path), *(str(a) for a in args))
        if cmd in self.git_results:
            return True, self.git_results[cmd]
        key_args = tuple(str(a) for a in args)
        if key_args in self.git_results:
            return True, self.git_results[key_args]
        return False, None

    def worktree_add(self, repo: str | Path, path: str | Path, branch: str, base: str) -> bool:
        self.calls.append(("worktree_add", str(repo), str(path), branch, base))
        self.branches.add(branch)
        self.checkouts[(str(repo), branch)] = str(path)
        self.owned_worktrees.add(str(path))
        return True

    def worktree_remove(self, repo: str | Path, worktree: str | Path, *, force: bool = True) -> bool:
        self.calls.append(("worktree_remove", str(repo), str(worktree), force))
        self.owned_worktrees.discard(str(worktree))
        self.checkouts = {k: v for k, v in self.checkouts.items() if v != str(worktree)}
        return True

    def delete_branch(self, repo: str | Path, branch: str, *, force: bool = True) -> bool:
        self.calls.append(("delete_branch", str(repo), branch, force))
        if branch not in self.branches:
            return False
        self.branches.discard(branch)
        return True

    def current_branch(self, repo: str | Path) -> str | None:
        hit, val = self._explicit_git_result(repo, "branch", "--show-current")
        return val if hit else self.base

    def branch_exists(self, repo: str | Path, branch: str) -> bool:
        hit, val = self._explicit_git_result(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if hit:
            return val is not None
        return branch in self.branches

    def is_ancestor(self, repo: str | Path, ancestor: str, descendant: str = "HEAD") -> bool:
        hit, val = self._explicit_git_result(repo, "merge-base", "--is-ancestor", ancestor, descendant)
        if hit:
            return val is not None
        cur = self.current_branch(repo)
        anc_norm = cur if ancestor == "HEAD" and cur else ancestor
        desc_norm = cur if descendant == "HEAD" and cur else descendant
        if anc_norm == desc_norm and (anc_norm == "HEAD" or anc_norm in self.branches):
            return True
        candidates = {(ancestor, descendant), (anc_norm, desc_norm)}
        if descendant == "HEAD" and cur:
            candidates.add((ancestor, cur))
        if cur and descendant == cur:
            candidates.add((ancestor, "HEAD"))
        return any(pair in self.ancestors for pair in candidates)

    def rev_parse(self, repo: str | Path, ref: str, *, short: bool = False, quiet: bool = False) -> str | None:
        args: list[str] = ["rev-parse", "--short" if short else "--verify"]
        if quiet:
            args.append("--quiet")
        args.append(ref)
        self.calls.append(("git", str(repo), *args))
        hit, val = self._explicit_git_result(repo, *args)
        if hit:
            return val
        hit_short, val_short = self._explicit_git_result(repo, "rev-parse", ref)
        if hit_short:
            return val_short[:7] if (short and val_short) else val_short
        target = ref[:-9] if ref.endswith("^{commit}") else ref
        branch_cand = target[11:] if target.startswith("refs/heads/") else target
        if target == "HEAD":
            seed = self.current_branch(repo) or "HEAD"
            digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
            return digest[:7] if short else digest
        if branch_cand in self.branches:
            digest = hashlib.sha1(branch_cand.encode("utf-8")).hexdigest()
            return digest[:7] if short else digest
        return None

    def has_tracked_changes(self, repo: str | Path) -> bool:
        hit, val = self._explicit_git_result(repo, "status", "--porcelain", "--untracked-files=no")
        if hit:
            return bool(val)
        return bool(self.dirty_files.get(str(repo), ""))

    def merge_no_commit(self, repo: str | Path, branch: str) -> GitResult:
        self.calls.append(("merge_no_commit", str(repo), branch))
        if branch in self.merge_conflicts and self.merge_conflicts[branch]:
            self._pending_merge.pop(str(repo), None)
            self._last_conflicts[str(repo)] = list(self.merge_conflicts[branch])
            return GitResult(returncode=1, stdout="", stderr="CONFLICT")
        self._pending_merge[str(repo)] = branch
        self._last_conflicts[str(repo)] = []
        return GitResult(returncode=0, stdout="", stderr="")

    def conflicts(self, repo: str | Path) -> list[str]:
        hit, val = self._explicit_git_result(repo, "diff", "--name-only", "--diff-filter=U", "-z")
        if hit:
            return [f for f in (val or "").split("\0") if f]
        return list(self._last_conflicts.get(str(repo), []))

    def commit(self, repo: str | Path, message: str) -> GitResult:
        res = self.run_raw(repo, "commit", "-q", "-m", message, timeout=None)
        out = res if res is not None else GitResult(returncode=1, stdout="", stderr="git commit failed")
        merged_branch = self._pending_merge.pop(str(repo), None)
        if out.ok and merged_branch:
            cur = self.current_branch(repo)
            self.ancestors.add((merged_branch, "HEAD"))
            if cur:
                self.ancestors.add((merged_branch, cur))
        return out

    def tracked_files(self, folder: str | Path, subpath: str, *, timeout: float = 15) -> set[str]:
        hit, val = self._explicit_git_result(folder, "ls-files", "-z", "--", subpath)
        if hit:
            return {p for p in (val or "").split("\0") if p}
        return set()

    def is_ignored(self, repo: str | Path, relpath: str, *, timeout: float = 15) -> bool:
        hit, val = self._explicit_git_result(repo, "check-ignore", "-q", "--", relpath)
        if hit:
            return val is not None
        return any(relpath == pat or (pat.endswith("/") and relpath.startswith(pat)) for pat in self.ignored)

    def porcelain_status_z(self, worktree: str | Path, *, untracked_all: bool = True, timeout: float = 30) -> str | None:
        args = ("status", "--porcelain", "-uall", "-z") if untracked_all else ("status", "--porcelain", "-z")
        hit, val = self._explicit_git_result(worktree, *args)
        if hit:
            return val
        return self.dirty_files.get(str(worktree), "")


def make_ctx(
    tmp_dir: Path | str,
    *,
    pane: str = "",
    hc_terminal: str = "",
    workspace: str = "",
    hc: FakeHc | None = None,
    tui: FakeTui | None = None,
    git: Any = None,
    agents: Any = None,
    caller: Any = None,
    procs: FakeProcs | None = None,
    clock: FakeClock | None = None,
    out: BufferOutput | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    home_kwargs: Mapping[str, Any] | None = None,
    candidate_pruner: Any = None,
) -> Context:
    """Build a structurally isolated `Context` under `tmp_dir` with `Home` + `FileStore` + test fakes."""
    base = Path(tmp_dir)
    root = base / "ledger"
    home = Home(root, **dict(home_kwargs or {}))
    if config is not None:
        home.config.parent.mkdir(parents=True, exist_ok=True)
        home.config.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    clk = clock if clock is not None else FakeClock()
    output = out if out is not None else BufferOutput()
    env_map = {"PM_HOME": str(root), **(dict(env) if env is not None else {})}
    if pane and not pane.startswith("hc:"):
        env_map.setdefault("HERDR_PANE_ID", pane)
    resolved_hc_term = hc_terminal or (pane[3:] if pane.startswith("hc:") else "")
    if resolved_hc_term:
        env_map.setdefault("HC_TERMINAL_ID", resolved_hc_term)
    if workspace:
        env_map.setdefault("HERDR_WORKSPACE_ID", workspace)
    cfg = Config(home)
    if hc is None:
        hc_port = FakeHc(clock=clk, config=cfg)
    else:
        hc_port = hc
        if hc_port._config is None:
            hc_port._config = cfg
    tui_port = tui if tui is not None else FakeTui()
    git_port = git if git is not None else StubGit(worktree_base=base / "worktrees")
    procs_port = procs if procs is not None else FakeProcs(home, env=env_map)
    claude_dir = base / "claude"
    ctx = Context(
        home=home,
        store=FileStore(home),
        config=cfg,
        clock=clk,
        out=output,
        procs=procs_port,
        hc=hc_port,
        tui=tui_port,
        git=git_port,
        env=env_map,
        pane=pane,
        hc_terminal=resolved_hc_term,
        workspace=workspace,
        claude_dir=claude_dir,
        claude_projects=claude_dir / "projects",
        codex_sessions=base / "codex" / "sessions",
        herdr_docs=base / "herdr-app",
        candidate_pruner=candidate_pruner,
    )
    ctx.agents = agents if agents is not None else AgentRegistry.from_context(ctx)
    ctx.caller = caller if caller is not None else Caller(ctx)
    if ctx.caller_projects is None and hasattr(ctx.caller, "caller_projects"):
        ctx.caller_projects = ctx.caller.caller_projects
    return ctx


def run_main(ctx: Any, *argv: str, stdin: str | None = None) -> tuple[Any, str, str]:
    """Run `pmlib.cli.main(argv, ctx=ctx)` and return `(exit_code, stdout, stderr)`.

    Works with both `StdOutput` and `BufferOutput` on `ctx.out`.
    """
    import contextlib
    import io
    import sys
    from unittest import mock
    from pmlib import cli
    from pmlib.context import BufferOutput

    out, err = io.StringIO(), io.StringIO()
    if isinstance(ctx.out, BufferOutput):
        prev_out, prev_err = len(ctx.out.stdout), len(ctx.out.stderr)
    else:
        prev_out = prev_err = None
    stdin_cm = mock.patch.object(sys, "stdin", io.StringIO(stdin)) if stdin is not None else contextlib.nullcontext()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), stdin_cm:
        try:
            cli.main(list(argv), ctx=ctx)
            code: Any = 0
        except SystemExit as stop:
            code = stop.code
    stdout_text = out.getvalue()
    stderr_text = err.getvalue()
    if prev_out is not None and isinstance(ctx.out, BufferOutput):
        stdout_text = ctx.out.stdout[prev_out:] + stdout_text
        stderr_text = ctx.out.stderr[prev_err:] + stderr_text
    return code, stdout_text, stderr_text
