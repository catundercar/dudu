"""The process's runtime context and ports (`Clock`, `Output`, `Context`). Layer 1."""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import io
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Protocol


def default_home(env: Mapping[str, str] | None = None) -> Path:
    """The ledger home: PM_HOME, else ~/.claude/pm where an earlier install keeps it (unless it links to ~/.dudu),
    else ~/.dudu."""
    env_map = os.environ if env is None else env
    val = env_map.get("PM_HOME")
    if val:
        return Path(val)
    canonical = Path.home() / ".dudu"
    earlier = Path.home() / ".claude" / "pm"
    if earlier.exists():
        try:
            if canonical.exists() and earlier.samefile(canonical):
                return canonical
        except OSError:
            pass
        return earlier
    return canonical


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def now_sec() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def seconds_since(at: Any) -> float:
    """Seconds since a ledger time ("YYYY-MM-DD HH:MM[:SS]"); a large number when it cannot be read."""
    try:
        when = datetime.datetime.strptime(str(at)[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return float("inf")
    return (datetime.datetime.now() - when).total_seconds()


class Clock(Protocol):
    """Time port for timestamps, monotonic timing, and sleep."""

    def datetime_now(self) -> datetime.datetime: ...
    def now(self) -> str: ...
    def now_sec(self) -> str: ...
    def time(self) -> float: ...
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...
    def seconds_since(self, at: Any) -> float: ...


class SystemClock:
    """Real wall and monotonic clock backed by `datetime` and `time`."""

    def datetime_now(self) -> datetime.datetime:
        return datetime.datetime.now()

    def now(self) -> str:
        return self.datetime_now().strftime("%Y-%m-%d %H:%M")

    def now_sec(self) -> str:
        return self.datetime_now().strftime("%Y-%m-%d %H:%M:%S")

    def time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def seconds_since(self, at: Any) -> float:
        try:
            when = datetime.datetime.strptime(str(at)[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return float("inf")
        return (self.datetime_now() - when).total_seconds()


class Output(Protocol):
    """Interface-layer output port for stdout/stderr lines and JSON."""

    def write(self, text: str) -> None: ...
    def line(self, text: str = "") -> None: ...
    def err(self, text: str) -> None: ...
    def err_line(self, text: str = "") -> None: ...
    def json(self, data: Any, *, indent: int | None = None, stream: str = "stdout") -> None: ...


class StdOutput:
    """Output port writing to `sys.stdout` / `sys.stderr` (resolved at call time unless bound)."""

    def __init__(self, stdout: Any = None, stderr: Any = None) -> None:
        self._stdout = stdout
        self._stderr = stderr

    def _out(self) -> Any:
        return sys.stdout if self._stdout is None else self._stdout

    def _err(self) -> Any:
        return sys.stderr if self._stderr is None else self._stderr

    def write(self, text: str) -> None:
        self._out().write(text)

    def line(self, text: str = "") -> None:
        self._out().write(f"{text}\n")

    def err(self, text: str) -> None:
        self._err().write(text)

    def err_line(self, text: str = "") -> None:
        self._err().write(f"{text}\n")

    def json(self, data: Any, *, indent: int | None = None, stream: str = "stdout") -> None:
        text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
        if stream == "stderr":
            self.err(text)
        else:
            self.write(text)


class BufferOutput:
    """In-memory Output port capturing stdout and stderr for unit tests."""

    def __init__(self) -> None:
        self._stdout = io.StringIO()
        self._stderr = io.StringIO()

    @property
    def stdout(self) -> str:
        return self._stdout.getvalue()

    @property
    def stderr(self) -> str:
        return self._stderr.getvalue()

    def clear(self) -> None:
        self._stdout = io.StringIO()
        self._stderr = io.StringIO()

    def write(self, text: str) -> None:
        self._stdout.write(text)

    def line(self, text: str = "") -> None:
        self._stdout.write(f"{text}\n")

    def err(self, text: str) -> None:
        self._stderr.write(text)

    def err_line(self, text: str = "") -> None:
        self._stderr.write(f"{text}\n")

    def json(self, data: Any, *, indent: int | None = None, stream: str = "stdout") -> None:
        text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
        if stream == "stderr":
            self.err(text)
        else:
            self.write(text)


@dataclass(frozen=True)
class DeliverWatcher:
    """A watcher entry injected into `Deliverer` via `ctx.deliver_watchers` or constructor."""

    name: str
    terminals: Any = None
    look: Any = None


@dataclass
class Context:
    """Explicit dependency container passed across pmlib layers."""

    home: Any
    store: Any = None
    config: Any = None
    clock: Any = field(default_factory=SystemClock)
    out: Any = field(default_factory=StdOutput)
    procs: Any = None
    hc: Any = None
    tui: Any = None
    git: Any = None
    agents: Any = None
    caller: Any = None
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    pane: str = ""
    hc_terminal: str = ""
    workspace: str = ""
    claude_dir: Path | None = None
    claude_projects: Path | None = None
    codex_sessions: Path | None = None
    agy_dir: Path | None = None
    herdr_docs: Path | None = None
    after_save: tuple[Any, ...] = ()
    seat_alive: Any = None
    caller_projects: Any = None
    candidate_pruner: Any = None
    deliver_watchers: tuple[Any, ...] = ()
    deliver_holds: tuple[Any, ...] = ()
    # Injected from above layer 3 by `build_context` (events may not import landing or discord):
    # `land_handoff(task_id, land_approved, principal)` hands a stalled worker merge to an exec helper as the
    # supervisor; each `alert_sinks` entry `(slug, repo, alert)` takes an `alert.undelivered` to a human channel.
    land_handoff: Any = None
    alert_sinks: tuple[Any, ...] = ()

    @classmethod
    def from_env(
        cls,
        home_option: str | Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        after_save: tuple[Any, ...] | None = None,
        seat_alive: Any = None,
        caller_projects: Any = None,
        candidate_pruner: Any = None,
        deliver_watchers: tuple[Any, ...] | None = None,
        deliver_holds: tuple[Any, ...] | None = None,
    ) -> Context:
        """Build a live `Context` from `home_option` and environment variables."""
        return pmlib.procs.build_context(
            home_option,
            env=env,
            after_save=after_save,
            seat_alive=seat_alive,
            caller_projects=caller_projects,
            candidate_pruner=candidate_pruner,
            deliver_watchers=deliver_watchers,
            deliver_holds=deliver_holds,
        )


import pmlib.procs  # noqa: E402 - import after Context definition so procs sees it
