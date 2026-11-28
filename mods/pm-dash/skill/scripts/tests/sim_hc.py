"""`SimHc`: an in-process stand-in for herdr-core's CLI, as `HcHost(runner=...)` calls it, covering this machine's
terminals and other machines' (`<machine>/t7`): `get`, `send`, `keys`, `interrupt`, `read`, `run`, `label`,
`machine ls`, `file read|write --on`, `exec --on`. A machine is a folder under the test's temp dir standing in for
that machine's home; `exec --on` runs the argv there for real (git included), so worktree and bundle code paths run
against isolated local repositories. No SSH, no real `hc`, no other machine is ever touched.

A disconnected machine behaves as hc does (`hc schema` 0.1.22): `machine ls` says so; `send`, `keys`,
`interrupt`, `exec` and `file read|write` fail with `unavailable`; `get` keeps answering the last mirrored state (it
has no `unavailable` error), which is exactly what a transport must not take at its word. Standard library only.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import subprocess
from typing import Any


def _err(kind: str, message: str = "") -> dict[str, Any]:
    return {"error": {"kind": kind, "message": message or kind}}


def _opts(args: list[str], with_value: set[str]) -> tuple[dict[str, Any], list[str]]:
    opts: dict[str, Any] = {}
    rest = list(args)
    out: list[str] = []
    while rest:
        a = rest.pop(0)
        if a == "--":
            out.extend(rest)
            break
        if a.startswith("--") and a in with_value and rest:
            opts[a] = rest.pop(0)
        elif a.startswith("--"):
            opts[a] = True
        else:
            out.append(a)
    return opts, out


class SimHc:
    def __init__(self, root: Path | str, *, clock: Any = None) -> None:
        self.root = Path(root)
        self.clock = clock
        self.machines: dict[str, dict[str, Any]] = {}
        self.terms: dict[str, dict[str, Any]] = {}
        self.sent: list[tuple[str, str]] = []
        self.keys_sent: list[tuple[str, tuple[str, ...]]] = []
        self.interrupts: list[str] = []
        self.calls: list[tuple[str, ...]] = []
        self.send_hook: Any = None  # callable(addr, text) -> reply | None, to script a reply (e.g. a timeout)
        self._next = 7

    # --- setup ---------------------------------------------------------------------------------------------------

    def add_machine(self, name: str, state: str = "connected") -> Path:
        home = self.root / "machines" / name
        home.mkdir(parents=True, exist_ok=True)
        self.machines[name] = {"name": name, "state": state, "since_ms": None, "home": home}
        return home

    def set_machine(self, name: str, state: str) -> None:
        self.machines[name]["state"] = state
        self.machines[name]["since_ms"] = None if state == "connected" else self._now_ms()

    def add_term(self, addr: str, *, status: str | None = "idle", reported: bool = True, turn: int = 1,
                 state: str = "live", screen: str = "prompt> ") -> dict[str, Any]:
        self.terms[addr] = {"address": addr, "state": state, "status": status, "reported": reported, "turn": turn,
                            "status_ms": self._now_ms(), "screen": screen, "labels": {}}
        return self.terms[addr]

    def typed_to(self, addr: str) -> list[str]:
        return [t for a, t in self.sent if a == addr]

    # --- helpers -------------------------------------------------------------------------------------------------

    def _now_ms(self) -> int:
        return int(float(self.clock.time()) * 1000) if self.clock is not None else 0

    def _machine_of(self, addr: str) -> str:
        return addr.split("/", 1)[0] if "/" in addr else ""

    def _down(self, machine: str) -> bool:
        return bool(machine) and self.machines.get(machine, {}).get("state") != "connected"

    def _home(self, machine: str) -> Path:
        if machine not in self.machines:
            raise KeyError(machine)
        return Path(self.machines[machine]["home"])

    def _path(self, machine: str, path: str, cwd: str = "") -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        base = Path(cwd) if cwd else self._home(machine)
        return base / p

    def _info(self, addr: str) -> dict[str, Any]:
        t = self.terms[addr]
        info = {k: v for k, v in t.items() if k not in ("screen",)}
        info["status"] = {"state": t["status"]} if t["status"] else None
        return info

    # --- the runner ------------------------------------------------------------------------------------------------

    def __call__(self, *argv: str, errors: bool = False, env: Any = None, timeout: float = 60,
                 input: str | None = None) -> Any:
        self.calls.append(tuple(argv))
        args = list(argv)
        cmd = args.pop(0) if args else ""
        if cmd == "machine" and args[:1] == ["ls"]:
            return {"machines": [{k: v for k, v in m.items() if k != "home"} for m in self.machines.values()]}
        if cmd == "get":
            addr = args[0]
            m = self._machine_of(addr)
            if m and m not in self.machines:
                return _err("machine_unknown")
            if addr not in self.terms:
                return _err("not_found")
            return self._info(addr)  # a down machine: the last mirrored state, as hc does
        if cmd == "send":
            opts, rest = _opts(args, {"--if"})
            addr, text = rest[0], rest[1]
            m = self._machine_of(addr)
            if self._down(m):
                return _err("unavailable", f"machine {m} is not connected")
            t = self.terms.get(addr)
            if t is None or t["state"] != "live":
                return _err("not_found")
            if self.send_hook is not None:
                scripted = self.send_hook(addr, text)
                if scripted != "pass":
                    return scripted
            if t["status"] == "blocked":
                return _err("blocked", "confirmation dialog")
            if opts.get("--if") == "idle" and t["reported"] and t["status"] != "idle":
                return _err("status_mismatch", f"status is {t['status']}")
            self.sent.append((addr, text))
            if not t["reported"] or not t["status"]:
                return {"started": None, "status": None}
            t["turn"] += 1
            t["status"] = "working"
            t["status_ms"] = self._now_ms()
            return {"started": True, "turn": t["turn"], "status": {"state": "working"}}
        if cmd == "keys":
            addr = args[0]
            if self._down(self._machine_of(addr)):
                return _err("unavailable")
            if addr not in self.terms:
                return _err("not_found")
            self.keys_sent.append((addr, tuple(args[1:])))
            if self.terms[addr]["status"] == "blocked":
                self.terms[addr]["status"] = "idle"
            return {"ok": True}
        if cmd == "interrupt":
            opts, rest = _opts(args, {"--timeout"})
            addr = rest[0]
            if self._down(self._machine_of(addr)):
                return _err("unavailable")
            t = self.terms.get(addr)
            if t is None or t["state"] != "live":
                return _err("not_found")
            self.interrupts.append(addr)
            if not t["reported"] or not t["status"]:
                return {"key": "ctrl+c", "outcome": "unknown"}
            if t["status"] == "working":
                t["status"] = "idle"
                t["status_ms"] = self._now_ms()
            return {"key": "esc", "outcome": "stopped"}
        if cmd == "read":
            addr = args[0]
            t = self.terms.get(addr)
            return {"text": t["screen"]} if t else _err("not_found")
        if cmd == "label":
            addr = args[0]
            if addr in self.terms:
                for kv in args[1:]:
                    k, _, v = kv.partition("=")
                    if v:
                        self.terms[addr]["labels"][k] = v
                    else:
                        self.terms[addr]["labels"].pop(k, None)
            return {"ok": True}
        if cmd == "keep":
            addr = args[0]
            if addr in self.terms:
                self.terms[addr]["keep"] = True
                return {"ok": True}
            return _err("not_found")
        if cmd == "kill":
            addr = args[0]
            t = self.terms.get(addr)
            if t is None:
                return _err("not_found")
            t["state"] = "exited"
            return {"ok": True}
        if cmd == "rm":
            addr = args[0]
            if addr in self.terms:
                self.terms.pop(addr, None)
                return {"ok": True}
            return _err("not_found")
        if cmd == "ls":
            opts, _ = _opts(args, set())
            show_all = bool(opts.get("--all"))
            rows = []
            for addr, t in self.terms.items():
                if not show_all and t.get("state") != "live":
                    continue
                rows.append(self._info(addr))
            return {"terminals": rows}
        if cmd == "server" and args[:1] == ["status"]:
            return {"running": True}
        if cmd == "run":
            opts, rest = _opts(args, {"--on", "--name", "--cwd", "--label", "--parent", "--timeout"})
            m = str(opts.get("--on") or "")
            if self._down(m):
                return _err("unavailable")
            addr = f"{m}/t{self._next}" if m else f"t{self._next}"
            self._next += 1
            self.add_term(addr, status="idle")
            self.terms[addr]["argv"] = rest
            self.terms[addr]["cwd"] = opts.get("--cwd") or ""
            return {"address": addr}
        if cmd == "file":
            sub = args.pop(0)
            opts, rest = _opts(args, {"--on", "--offset", "--limit", "--cwd"})
            m = str(opts.get("--on") or "")
            if self._down(m):
                return _err("unavailable")
            path = self._path(m, rest[0]) if m else Path(rest[0])
            if sub == "read":
                if not path.is_file():
                    return _err("not_found", str(path))
                lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
                first = int(opts.get("--offset") or 1)
                if first > len(lines) and not (first == 1 and not lines):
                    # As hc 0.1.22 does: an offset past the last line is an error, not an empty chunk (an outbox
                    # pull from cursor+1 hits this every time nothing new was written).
                    return _err("invalid_params", f"offset {first}: the file has {len(lines)} lines")
                limit = int(opts.get("--limit") or len(lines) or 1)
                chunk = lines[first - 1:first - 1 + limit]
                return {"text": "".join(chunk), "first": first, "last": first + len(chunk) - 1, "lines": len(lines)}
            if sub == "write":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(input or "", encoding="utf-8")
                return {"path": str(path), "bytes": len((input or "").encode("utf-8"))}
            return _err("invalid_params")
        if cmd == "exec":
            opts, rest = _opts(args, {"--on", "--cwd", "--timeout", "--env"})
            m = str(opts.get("--on") or "")
            if self._down(m):
                return _err("unavailable")
            home = self._home(m) if m else self.root
            cwd = self._path(m, str(opts["--cwd"])) if opts.get("--cwd") and m else (Path(opts["--cwd"]) if opts.get("--cwd") else home)
            run_env = {**os.environ, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@x"}
            try:
                r = subprocess.run(rest, cwd=str(cwd), input=(input if opts.get("--stdin") else None),
                                   capture_output=True, text=True, env=run_env, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as err:
                return _err("spawn_failed", str(err))
            return {"code": r.returncode, "stdout": base64.b64encode(r.stdout.encode()).decode(),
                    "stderr": base64.b64encode(r.stderr.encode()).decode(), "timed_out": False, "truncated": False,
                    "ms": 1}
        return None
