"""What one task record says by itself: the status sets, its number and how a number is written, its worker terminal,
whether the PM started it, whether it still needs cleaning up, and the dict-preserving `Task` view.
Nothing here reads another task or the disk. Layer 2."""
from __future__ import annotations

from collections.abc import MutableMapping
import datetime
import re
from typing import Any, Iterator

from ..project.turn_reducer import Endpoint, record_endpoint
from ..store import valid_task_number


ACTIVE = ["proposed", "in_progress", "review", "blocked", "paused"]
CLOSED = ["merged", "released", "done", "abandoned"]
# Open work whose terminal is looked at: a task in one of these that names a terminal that is gone is offline.
ATTACHED = ("in_progress", "review", "blocked")
TASK_NUM_RE = re.compile(r"^(?:([A-Za-z0-9][A-Za-z0-9._-]*)#)?#?([1-9][0-9]*)(-review)?$")


def _raw_dict(task: Any) -> dict[str, Any] | None:
    if isinstance(task, Task):
        return task._data
    if isinstance(task, dict):
        return task
    return None


class Task(MutableMapping):
    """Dict-preserving domain view over one on-disk task JSON record."""

    def __init__(self, data: dict[str, Any] | Task) -> None:
        if isinstance(data, Task):
            self._data = data._data
        elif isinstance(data, dict):
            self._data = data
        else:
            raise TypeError(f"Task requires a dict or Task, got {type(data).__name__}")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Task) -> Task:
        return data if isinstance(data, cls) else cls(data)

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    # Dict-preserving accessors so callers can read/preserve arbitrary extra fields without loss.
    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def pop(self, key: str, *default: Any) -> Any:
        return self._data.pop(key, *default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        return self._data.setdefault(key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._data.update(*args, **kwargs)

    def keys(self) -> Any:
        return self._data.keys()

    def items(self) -> Any:
        return self._data.items()

    def values(self) -> Any:
        return self._data.values()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Task):
            return self._data == other._data
        return NotImplemented

    def __repr__(self) -> str:
        return f"Task(id={self.id!r}, status={self.status!r})"

    @property
    def id(self) -> str:
        return str(self._data.get("id") or "")

    @property
    def title(self) -> str:
        return str(self._data.get("title") or "")

    @property
    def project(self) -> str:
        return str(self._data.get("project") or "")

    @property
    def repo(self) -> str:
        return str(self._data.get("repo") or "")

    @property
    def status(self) -> str:
        return str(self._data.get("status") or "")

    @property
    def pane(self) -> str:
        return str(self._data.get("pane") or "")

    @property
    def agent(self) -> str:
        return str(self._data.get("agent") or "")

    @property
    def branch(self) -> str:
        return str(self._data.get("branch") or "")

    @property
    def worktree(self) -> str:
        return str(self._data.get("worktree") or "")

    @property
    def owner(self) -> str:
        return str(self._data.get("owner") or "")

    @property
    def parent(self) -> str:
        return str(self._data.get("parent") or "")

    @property
    def review_of(self) -> str:
        return str(self._data.get("review_of") or "")

    @property
    def number(self) -> int | None:
        return valid_task_number(self._data.get("number"))

    @property
    def depends_on(self) -> list[str]:
        raw = self._data.get("depends_on")
        return [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []

    @property
    def plan(self) -> list[dict[str, Any]]:
        raw = self._data.get("plan")
        return raw if isinstance(raw, list) else []

    @property
    def subplan(self) -> list[dict[str, Any]]:
        raw = self._data.get("subplan")
        return raw if isinstance(raw, list) else []

    @property
    def log(self) -> list[dict[str, Any]]:
        raw = self._data.get("log")
        return raw if isinstance(raw, list) else []

    @property
    def created(self) -> str:
        return str(self._data.get("created") or "")

    @property
    def updated(self) -> str:
        return str(self._data.get("updated") or "")

    @property
    def retired(self) -> bool:
        return bool(self._data.get("retired"))

    @property
    def landed(self) -> Any:
        return self._data.get("landed")

    @property
    def dispatched(self) -> Any:
        return self._data.get("dispatched")

    @property
    def created_ts(self) -> float:
        return created_at(self._data)

    @property
    def hc_terminal(self) -> str:
        return hc_terminal_of(self._data)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE

    @property
    def is_closed(self) -> bool:
        return self.status in CLOSED

    @property
    def is_attached(self) -> bool:
        return self.status in ATTACHED

    @property
    def pm_started(self) -> bool:
        return pm_started(self._data)

    @property
    def started_by_pm(self) -> bool:
        return started_by_pm(self._data)

    @property
    def needs_cleanup(self) -> bool:
        return needs_cleanup(self._data)


def task_number(task: Any) -> int | None:
    """Positive integer project task number, or None when absent/invalid (e.g. review or old peer tasks)."""
    raw = _raw_dict(task)
    return valid_task_number(raw.get("number")) if raw is not None else None


def parse_task_num_ref(ref: Any) -> tuple[str, int, bool] | None:
    """Parse `#42`, `42`, `#42-review`, `42-review`, `<project>#42` -> `(proj, number, is_review)` or None."""
    if not isinstance(ref, str):
        return None
    m = TASK_NUM_RE.fullmatch(ref.strip())
    if not m:
        return None
    return (m.group(1) or ""), int(m.group(2)), bool(m.group(3))


def needs_cleanup(task: Any) -> bool:
    """Merged or released, but its worker terminal, worktree or branch has not been removed with `retire`."""
    raw = _raw_dict(task)
    if raw is None:
        return False
    return raw.get("status") in ("merged", "released") and not raw.get("retired") and bool(
        raw.get("branch") or raw.get("worktree"))


def pm_started(task: Any) -> bool:
    """Whether the PM started this task's worker (`dispatch`, or `review` for a reviewer), which reports in the
    ledger; a session that registered its own work is no such worker."""
    raw = _raw_dict(task)
    return bool(raw and (raw.get("dispatched") or raw.get("review_of")))


def started_by_pm(task: Any) -> bool:
    """pm.py started this task's worker or reviewer (dispatch, review, escalate): never a session that registered
    its own work, or one taken over with `pm.py new --pane`, whose terminal is a conversation of the user's."""
    raw = _raw_dict(task)
    return bool(raw and (raw.get("dispatched") or raw.get("review_of") or raw.get("escalations")))


def task_endpoint(task: Any) -> Endpoint | None:
    """Resolve the structured `Endpoint` for a task record (reading `endpoint` or legacy `pane`)."""
    return record_endpoint(_raw_dict(task))


def hc_terminal_of(task: Any) -> str:
    ep = task_endpoint(task)
    return ep.hc_target if ep is not None else ""


def created_at(task: Any) -> float:
    raw = _raw_dict(task)
    if raw is None:
        return 0
    try:
        return datetime.datetime.strptime(raw.get("created") or "", "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        return 0
