"""Herdr TUI inbox and watch helpers: appending/reading inbox files, watcher lock, watched workspaces and agents,
and liveness/orphan detection; the watch loop itself (`InboxWatcher.watch` / `watch_notifications`). Layer 3.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any

from ..caller import tui_registration
from ..context import Context
from ..errors import Refused
from ..ledger.ledger import Ledger
from ..ledger.task import ACTIVE
from ..osutil import process_name
from ..store import lock_file, unlock_file
from ..terminals.events import RECONCILE

# herdr reports a claude session in a long thinking or shell step as done/idle; its screen still shows these.
BUSY = re.compile(r"…\s*\(\d+[hms]|esc to interrupt|Waiting for API response|Running \d+ shell|shells? still running")

WATCH_START = ("start it with your agent's own background tool, which tells you when it exits (Claude Code: "
               "the Bash tool with run_in_background: true), as one command of its own; not with &, nohup, "
               "disown or setsid, a redirect to /dev/null, or after && or ;")
# What adopts a process whose starter went away: init/launchd, or a Linux subreaper.
ADOPTERS = {"launchd", "systemd", "init", "tini", "dumb-init", "docker-init"}
LIVENESS = 5  # seconds between looks at whether the watcher's starter is still there (one syscall)
FIRST_WATCH_LINES = 20  # a first watch delivers at most these unread lines


@dataclass(frozen=True)
class WatchResult:
    """Structured outcome of `InboxWatcher.watch`: caller prints `text` and then calls `commit()`."""

    kind: str  # "inbox" | "alerts" | "timeout"
    text: str
    new_offset: int | None = None
    offset_file: Path | None = None

    def commit(self) -> None:
        """Persist the advanced inbox offset after the caller has successfully written `text`."""
        if self.offset_file is not None and self.new_offset is not None:
            self.offset_file.write_text(str(self.new_offset))


def read_inbox(path: Path, offset: int) -> tuple[int, str]:
    """(new offset, complete new lines) of the inbox file since offset."""
    size = path.stat().st_size if path.exists() else 0
    if size < offset:  # truncated or replaced: read it again from the start
        offset = 0
    if size == offset:
        return offset, ""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(size - offset)
    end = data.rfind(b"\n") + 1  # a half-written last line waits for the next round
    return offset + end, data[:end].decode(errors="replace")


def state_changes(prev: dict[str, Any], cur: dict[str, Any]) -> list[str]:
    finished = [f"{p} {prev[p]}->{s}" for p, s in cur.items()
                if prev.get(p) == "working" and s not in ("working", "blocked")]
    blocked = [f"{p} ->blocked" for p, s in cur.items() if p in prev and prev[p] != "blocked" and s == "blocked"]
    new = [f"{p} new:{s}" for p, s in cur.items() if p not in prev and s in ("blocked", "done")]
    return finished + blocked + new


def output_nowhere() -> bool:
    """stdout is /dev/null: nothing watch prints reaches anyone."""
    if os.name == "nt":
        return False
    try:
        out, null = os.fstat(sys.stdout.fileno()), os.stat(os.devnull)
    except (OSError, ValueError, AttributeError):
        return False
    return stat.S_ISCHR(out.st_mode) and out.st_rdev == null.st_rdev


def process_line(pid: int) -> tuple[int | None, str]:
    """(parent pid, command line) of a process (POSIX): /proc where there is one (minimal Linux has no ps), else ps.
    (None, "") when it cannot be read."""
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        stat_line = Path(f"/proc/{pid}/stat").read_text()
        return int(stat_line[stat_line.rindex(")") + 2:].split()[1]), command
    except (OSError, ValueError, IndexError):
        pass
    try:
        out = subprocess.run(["ps", "-o", "ppid=,command=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
        ppid, _, command = out.stdout.strip().partition(" ")
        return (int(ppid), command.strip()) if out.returncode == 0 and ppid.isdigit() else (None, "")
    except (OSError, subprocess.TimeoutExpired):
        return None, ""


def adopted(ppid: int | None = None) -> bool:
    """This process was left behind by what started it (a shell that ran `watch &` and exited, nohup, disown) and
    init or a subreaper took it in: what it prints reaches no agent. False where that cannot be told (Windows)."""
    if os.name == "nt":
        return False
    ppid = os.getppid() if ppid is None else ppid
    if sys.platform == "darwin":
        return ppid == 1  # launchd; macOS has no subreapers
    # By name: a container may run the agent itself as process 1.
    name = process_name(ppid)
    return name in ADOPTERS if name else ppid == 1


def first_watch_offset(inbox: Path) -> tuple[int, int]:
    """(offset, lines left out) for a PM's first watch: its unread lines, at most FIRST_WATCH_LINES of them. Without
    a watcher notify typed each line into the PM's input already, so a long log is history, not news."""
    try:
        data = inbox.read_bytes()
    except OSError:
        return 0, 0
    end = data.rfind(b"\n") + 1
    total = data.count(b"\n", 0, end)
    if total <= FIRST_WATCH_LINES:
        return 0, 0
    at = end - 1
    for _ in range(FIRST_WATCH_LINES):
        at = data.rfind(b"\n", 0, at)
    return at + 1, total - FIRST_WATCH_LINES


class InboxWatcher:
    """Herdr TUI inbox and watch service over an explicit `Context` (zero globals, zero prints, zero sys.exit)."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ledger = Ledger(ctx)

    def append_inbox(self, name: str, sender: str, text: str) -> None:
        self.ctx.home.inbox.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.ctx.home.inbox_log(name), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(f"[from {sender} {self.ctx.clock.datetime_now():%H:%M}] {text}\n")

    def watch_lock(self, name: str) -> Any:
        """Hold the watcher lock of PM name for the life of this process, or return None when another watcher holds it."""
        self.ctx.home.inbox.mkdir(parents=True, exist_ok=True)
        f = open(self.ctx.home.inbox_watch_lock(name), "a+")
        try:
            lock_file(f)
        except OSError:
            f.close()
            return None
        f.truncate(0)
        f.write(str(os.getpid()))
        f.flush()
        return f

    def watcher_pid(self, name: str) -> str | None:
        """PID of the running watcher of PM name, or None."""
        path = self.ctx.home.inbox_watch_lock(name)
        if not path.exists():
            return None
        with open(path) as f:
            try:
                lock_file(f, shared=True)
            except OSError:
                return f.read().strip() or "?"
            unlock_file(f)
        return None

    def pane_busy(self, pane: str, session: str | None = None) -> bool:
        out = self.ctx.tui.pane_read(pane, lines=12, session=session)
        return bool(BUSY.search(out or ""))

    def watched_workspaces(self, rec: dict[str, Any], workspaces: list[dict[str, Any]]) -> set[str]:
        """The PM's workspace, the workspaces labelled `pm-<project>…`, and those of the project's open tasks that
        `dispatch` started."""
        ids = [rec.get("workspace")] + [w.get("workspace_id") for w in workspaces
                                        if str(w.get("label", "")).startswith(rec["name"])]
        ids += [t.get("workspace") for t in self._ledger.raw_tasks() if t.get("dispatched")
                and t.get("repo") == rec.get("repo")
                and t.get("status") in ACTIVE and not str(t.get("pane") or "").startswith("hc:")]
        return set(filter(None, ids))

    def _watched_agents_impl(self, rec: dict[str, Any]) -> dict[str, Any] | None:
        session = rec.get("session")
        workspaces = self.ctx.tui.workspaces(session=session)
        panes = self.ctx.tui.panes(session=session) if workspaces is not None else None
        if workspaces is None or panes is None:
            return None
        ids = self.watched_workspaces(rec, workspaces)
        states: dict[str, Any] = {}
        for p in panes:
            if p.get("workspace_id") not in ids or p["pane_id"] == rec.get("pane") or not p.get("agent"):
                continue
            status = p.get("agent_status")
            if status in ("done", "idle") and self.pane_busy(p["pane_id"], session=session):
                status = "working"
            states[p["pane_id"]] = status
        return states

    def watched_agents(self, rec: dict[str, Any]) -> dict[str, Any] | None:
        """pane -> agent status in the watched workspaces, the PM excluded; None when herdr did not answer."""
        if getattr(self.ctx, "_legacy", False) and watched_agents is not _DEFAULT_WATCHED_AGENTS:
            return watched_agents(rec)
        return self._watched_agents_impl(rec)

    def watcher_report(self, name: str, pid: Any) -> str:
        """Why a second watcher was refused: the running one, what started it, and the unread inbox lines."""
        lines = [f"a watcher for {name} is already running (pid {pid})"]
        starter = None
        if os.name != "nt" and str(pid).isdigit():
            starter, command = process_line(int(pid))
            if starter is not None:
                lines.append(f"  command: {command}")
                lines.append(f"  started by: pid {starter} ({process_name(starter) or '?'})")
        inbox = self.ctx.home.inbox_log(name)
        try:
            offset = int(self.ctx.home.inbox_offset(name).read_text())
            with open(inbox, "rb") as f:
                f.seek(offset)
                unread = f.read().count(b"\n")
            lines.append(f"  unread lines in {inbox}: {unread}")
        except (OSError, ValueError):
            pass
        if starter is not None and adopted(starter):
            lines.append(f"  Its starter is gone, so what it prints reaches no one. A watcher of this version stops "
                         f"by itself within {LIVENESS} s without reading the inbox; an older one does not: kill {pid}. "
                         f"Then {WATCH_START}.")
        else:
            lines.append("  If that is not your own background task, stop it and start one that is: " + WATCH_START + ".")
        return "\n".join(lines)

    def watch(self, rec: dict[str, Any], *, timeout: float = 4 * 3600, interval: float = 10) -> WatchResult:
        """Wait for a new inbox line or a TUI agent state change and return a `WatchResult`. Raises `Refused`
        when the starter process has gone (leaving the inbox unread)."""
        name = rec["name"]
        inbox = self.ctx.home.inbox_log(name)
        offset_file = self.ctx.home.inbox_offset(name)
        state_file = self.ctx.home.inbox_watch_states(name)
        tui = tui_registration(rec)
        deadline = self.ctx.clock.monotonic() + timeout
        starter = os.getppid()
        every = max(0.1, interval) if tui else RECONCILE
        # Subscribe before reading: a write between the read and wait stays queued.
        with self.ctx.hc.change_waiter([self.ctx.home.inbox], None, files=[inbox]) as changes:
            skipped = 0
            try:
                offset = max(0, int(offset_file.read_text()))
            except (OSError, ValueError):
                # Existing unread reports must not disappear on the first watcher.
                offset, skipped = first_watch_offset(inbox)
                offset_file.write_text(str(offset))
            try:
                prev = json.loads(state_file.read_text())
                if not isinstance(prev, dict):
                    prev = None
            except (OSError, ValueError):
                prev = None
            woke, look_at = True, 0.0
            while self.ctx.clock.monotonic() < deadline:
                if os.name != "nt" and os.getppid() != starter:
                    # The agent that started this watcher (or the shell of a `&`) is gone: leave the inbox unread
                    # and the lock free for a watcher whose output someone reads.
                    raise Refused(
                        f"watch: what started it has gone; stopping without reading the inbox. {WATCH_START}."
                    )
                if woke or self.ctx.clock.monotonic() >= look_at:
                    look_at = self.ctx.clock.monotonic() + every
                    new_offset, text = read_inbox(inbox, offset)
                    if text:
                        note = (f"(first watch for {name}: {skipped} earlier lines are not shown; they are in {inbox})\n"
                                if skipped else "")
                        return WatchResult(
                            kind="inbox",
                            text="INBOX:\n" + text + note,
                            new_offset=new_offset,
                            offset_file=offset_file,
                        )
                    if new_offset != offset:
                        offset = new_offset
                        offset_file.write_text(str(offset))
                    cur = self.watched_agents(rec) if tui else None
                    if cur is not None:
                        alerts = state_changes(prev, cur) if prev is not None else []
                        if prev != cur:
                            state_file.write_text(json.dumps(cur))
                        prev = cur
                        if alerts:
                            return WatchResult(kind="alerts", text="\n".join(alerts))
                now_ = self.ctx.clock.monotonic()
                woke = changes.wait(max(0, min(deadline - now_, look_at - now_, LIVENESS)))
        return WatchResult(kind="timeout", text="watch timeout")


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def append_inbox(name: str, sender: str, text: str) -> None:
    InboxWatcher(Context.from_env()).append_inbox(name, sender, text)


def watch_lock(name: str) -> Any:
    return InboxWatcher(Context.from_env()).watch_lock(name)


def watcher_pid(name: str) -> str | None:
    return InboxWatcher(Context.from_env()).watcher_pid(name)


def pane_busy(pane: str, session: str | None = None) -> bool:
    return InboxWatcher(Context.from_env()).pane_busy(pane, session=session)


def watched_workspaces(rec: dict[str, Any], workspaces: list[dict[str, Any]]) -> set[str]:
    return InboxWatcher(Context.from_env()).watched_workspaces(rec, workspaces)


def watched_agents(rec: dict[str, Any]) -> dict[str, Any] | None:
    return InboxWatcher(Context.from_env())._watched_agents_impl(rec)


_DEFAULT_WATCHED_AGENTS = watched_agents


def watcher_report(name: str, pid: Any) -> str:
    return InboxWatcher(Context.from_env()).watcher_report(name, pid)


def watch_notifications(a: Any, rec: dict[str, Any]) -> None:
    ctx = Context.from_env()
    try:
        res = InboxWatcher(ctx).watch(rec, timeout=a.timeout, interval=a.interval)
    except Refused as exc:
        raise SystemExit(str(exc)) from None
    try:
        if res.kind == "inbox":
            ctx.out.write(res.text)
        else:
            ctx.out.line(res.text)
        out_fn = getattr(ctx.out, "_out", None)
        if callable(out_fn):
            out_fn().flush()
    except BrokenPipeError:
        raise SystemExit(1) from None
    res.commit()
