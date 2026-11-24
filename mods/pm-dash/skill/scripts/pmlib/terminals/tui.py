"""The herdr terminal UI's command line (`herdr ...`): `TuiHost`, its panes, agents, sessions, and worktrees. Layer 1."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable

from ..errors import IdentityError


class TuiHost:
    """Port for Herdr TUI (`herdr ...`) sessions, workspaces, panes, agents, and worktrees."""

    def __init__(self, *, runner: Any = None, raw_runner: Any = None, agents_fn: Any = None) -> None:
        self._runner = runner
        self._raw_runner = raw_runner
        self._agents_fn = agents_fn

    def _run_raw(self, argv: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        if self._raw_runner is not None:
            return self._raw_runner(argv, timeout=timeout)
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    def __call__(self, *args: Any, session: str | None = None) -> Any:
        return self.call(*args, session=session)

    def call(self, *args: Any, session: str | None = None) -> Any:
        """Return the `result` object of a herdr CLI call, or None outside herdr or when the call fails."""
        if self._runner is not None:
            if session is None:
                return self._runner(*args)
            kw = {"session": session}
            return self._runner(*args, **kw)
        try:
            argv = ["herdr", *(["--session", session] if session else []), *(str(a) for a in args)]
            out = self._run_raw(argv, timeout=60)
            if out.returncode == 0 and not out.stdout.strip():
                return {"ok": True}  # a command that prints nothing when it succeeds, such as `pane run`
            return json.loads(out.stdout)["result"]
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
            return None

    def strict(self, *args: Any, session: str | None = None) -> dict[str, Any]:
        result = self.call(*args, session=session)
        if not isinstance(result, dict):
            raise IdentityError(f"cannot verify herdr {session or 'current'} {' '.join(str(a) for a in args)}")
        return result

    def agents(self, *, session: str | None = None) -> list[dict[str, Any]]:
        if session is None and self._agents_fn is not None:
            return self._agents_fn()
        return (self.call("agent", "list", session=session) or {}).get("agents", [])

    def panes(self, *, session: str | None = None) -> list[dict[str, Any]] | None:
        res = self.call("pane", "list", session=session)
        return res.get("panes", []) if isinstance(res, dict) else None

    def pane_get(self, pane_id: str, *, session: str | None = None) -> dict[str, Any] | None:
        res = self.call("pane", "get", pane_id, session=session)
        return res.get("pane") if isinstance(res, dict) else None

    def pane_run(self, pane_id: str, cmd: str, *, session: str | None = None) -> Any:
        return self.call("pane", "run", pane_id, cmd, session=session)

    def pane_close(self, pane_id: str, *, session: str | None = None) -> Any:
        return self.call("pane", "close", pane_id, session=session)

    def pane_read(self, pane_id: str, *, lines: int = 12, session: str | None = None) -> str:
        """Read the last `lines` lines from a TUI pane (`herdr pane read`), or "" on failure."""
        argv = ["herdr", *(["--session", session] if session else []), "pane", "read", pane_id, "--lines", str(lines)]
        try:
            return self._run_raw(argv, timeout=30).stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def pane_process_info(self, pane_id: str, *, session: str | None = None) -> dict[str, Any]:
        res = self.call("pane", "process-info", "--pane", pane_id, session=session)
        return (res.get("process_info") or {}) if isinstance(res, dict) else {}

    def workspaces(self, *, session: str | None = None) -> list[dict[str, Any]] | None:
        res = self.call("workspace", "list", session=session)
        return res.get("workspaces", []) if isinstance(res, dict) else None

    def worktrees(self, *, cwd: str | Path | None = None, session: str | None = None) -> list[dict[str, Any]] | None:
        args: list[str] = ["worktree", "list"]
        if cwd is not None:
            args.extend(("--cwd", str(cwd)))
        res = self.call(*args, session=session)
        return res.get("worktrees", []) if isinstance(res, dict) else None

    def worktree_create(self, *args: Any, session: str | None = None) -> Any:
        return self.call("worktree", "create", *args, session=session)

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
        return self.call(*args, session=session)

    def tab_create(self, *args: Any, session: str | None = None) -> Any:
        return self.call("tab", "create", *args, session=session)

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
        return self.call(*args, session=session)

    def agent_send_keys(self, pane_id: str, *keys: str, session: str | None = None) -> Any:
        return self.call("agent", "send-keys", pane_id, *keys, session=session)

    def agent_rename(self, pane_id: str, name: str, *, session: str | None = None) -> Any:
        return self.call("agent", "rename", pane_id, name, session=session)

    def agent_prompt(self, pane_id: str, text: str, *, session: str | None = None) -> Any:
        return self.call("agent", "prompt", pane_id, text, session=session)

    def agent_wait(self, *args: Any, session: str | None = None) -> Any:
        return self.call("agent", "wait", *args, session=session)

    def sessions(self) -> list[dict[str, Any]]:
        """The local herdr sessions ({name, socket_path, running}), checked; IdentityError when unreadable."""
        try:
            out = self._run_raw(["herdr", "session", "list", "--json"], timeout=30)
            sessions = json.loads(out.stdout)["sessions"]
            if out.returncode or not isinstance(sessions, list):
                raise ValueError("invalid session list")
            if any(not isinstance(s, dict) or not s.get("name") or not s.get("socket_path")
                   or not isinstance(s.get("running"), bool) for s in sessions):
                raise ValueError("incomplete session identity")
            if len({s["name"] for s in sessions}) != len(sessions):
                raise ValueError("duplicate session names")
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as e:
            raise IdentityError(f"cannot enumerate herdr sessions: {e}") from e
        return sessions

    def socket_session(self, sessions: list[dict[str, Any]] | None = None) -> str:
        """The running session whose socket this process inherited (`herdr status server`)."""
        known = self.sessions() if sessions is None else sessions
        try:
            out = self._run_raw(["herdr", "status", "server"], timeout=30)
            socket = re.search(r"^socket:\s*(.+)$", out.stdout, re.M)
            matches = [s for s in known if socket and s["running"]
                       and Path(s["socket_path"]).resolve() == Path(socket.group(1)).resolve()]
            if out.returncode or len(matches) != 1:
                raise ValueError("inherited socket is not one known running session")
        except (OSError, subprocess.TimeoutExpired, ValueError) as e:
            raise IdentityError(f"cannot verify caller session: {e}") from e
        return matches[0]["name"]


def herdr(*args, session=None):
    """Return the `result` object of a herdr CLI call, or None outside herdr or when the call fails.
    session: the herdr session to talk to (`herdr --session <name>`), default the one this process runs in."""
    try:
        out = subprocess.run(["herdr", *(["--session", session] if session else []), *args],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0 and not out.stdout.strip():
            return {"ok": True}  # a command that prints nothing when it succeeds, such as `pane run`
        return json.loads(out.stdout)["result"]
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return None


def agents():
    return (herdr("agent", "list") or {}).get("agents", [])
