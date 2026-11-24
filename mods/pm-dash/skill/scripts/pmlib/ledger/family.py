"""Parent and child tasks: grouping children by parent, progress summaries, and pure rollup rules. Layer 2."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .. import home as home_mod
from ..config import tr
from ..errors import NotFound, Refused
from .deps import DEP_MET_STATUSES, _dep_status_label
from .ledger import resolve_task_id
from .plan import has_unfinished_plan
from .task import _raw_dict, parse_task_num_ref

_ROLLUP_STATUS_ORDER = ("merged", "released", "done", "abandoned")


def task_children_map(tasks):
    """Map `parent_id -> list[child_task]` for all tasks that specify `parent`."""
    out = {}
    for t in tasks:
        p = t.get("parent")
        if p:
            out.setdefault(p, []).append(t)
    return out


def format_children_summary(children, dep_by_id=None, *, tr_fn=None):
    """Concise progress summary of a planning parent task's child tasks."""
    if not children:
        return ""
    t = tr_fn or tr
    total = len(children)
    done = sum(1 for c in children if c.get("status") in DEP_MET_STATUSES)
    ready = sum(1 for c in children if c.get("status") == "proposed"
                and dep_by_id and c["id"] in dep_by_id and dep_by_id[c["id"]]["ready"])
    waiting = sum(1 for c in children if c.get("status") == "proposed" and c.get("depends_on")
                  and (not dep_by_id or c["id"] not in dep_by_id or not dep_by_id[c["id"]]["ready"]))
    todo = sum(1 for c in children if c.get("status") == "proposed" and not c.get("depends_on"))
    extra = []
    if ready:
        extra.append(t(f"{ready} ready", f"{ready} 可以派了"))
    if waiting:
        extra.append(t(f"{waiting} waiting", f"{waiting} 等前置"))
    if todo:
        extra.append(t(f"{todo} todo", f"{todo} 待做"))
    tail = f" ({', '.join(extra)})" if extra else ""
    return t(f"subtasks={done}/{total}{tail}", f"子任务={done}/{total}{tail}")


@dataclass(frozen=True)
class Rollup:
    """What closed children mean for their parent: pure proposal, never writes the ledger.

    `action` is `'close'` (the parent can be moved to `done`) or `'notify'` (inform the manager and
    leave the parent's status alone). `reason` names which rule fired.
    """
    action: str
    reason: str
    summary: str
    counts: dict


def _parent_has_own_work(parent, *, own_session_live: bool = False):
    """Whether the parent task carries work of its own (a live own session, review status, running helpers,
    a live worker, a branch, or unfinished plan steps)."""
    has_worker = bool(
        not parent.get("retired")
        and (parent.get("dispatched") or parent.get("worker") or parent.get("worker_pane") or parent.get("agent"))
    )
    has_running_helper = any(
        isinstance(h, dict) and h.get("status") == "running"
        for h in (parent.get("helpers") or [])
    )
    return (
        bool(own_session_live)
        or parent.get("status") == "review"
        or has_running_helper
        or has_worker
        or bool(parent.get("branch"))
        or has_unfinished_plan(parent)
    )


def rollup_key_for(children) -> str:
    """Deterministic state key over sorted `(child_id, child_status)` pairs for rollup deduplication."""
    pairs = sorted(
        (str(c.get("id") or ""), str(c.get("status") or ""))
        for c in (children or [])
        if isinstance(c, dict)
    )
    return ",".join(f"{cid}={st}" for cid, st in pairs)


def _format_rollup_summary(total, counts, *, all_abandoned, tr_fn=None):
    t = tr_fn or tr
    if all_abandoned:
        if total == 1:
            return t("1 child task abandoned", "1 个子任务已放弃")
        return t(f"all {total} child tasks abandoned", f"全部 {total} 个子任务已放弃")
    ordered = [s for s in _ROLLUP_STATUS_ORDER if counts.get(s)]
    ordered.extend(sorted(s for s in counts if s not in _ROLLUP_STATUS_ORDER and counts[s]))
    sep = t(", ", "、")
    detail = sep.join(t(f"{counts[s]} {s}", f"{counts[s]} {_dep_status_label(s, tr_fn=t)}") for s in ordered)
    if total == 1:
        return t(f"1 child task finished ({detail})", f"1 个子任务已结束（{detail}）")
    return t(f"all {total} child tasks finished ({detail})", f"全部 {total} 个子任务已结束（{detail}）")


class Family:
    """A parent task paired with its child tasks (`parent` on the child, as on disk)."""

    def __init__(self, parent, children):
        self.parent = _raw_dict(parent) or {}
        self.children = [d for c in (children or []) if (d := _raw_dict(c)) is not None]

    @classmethod
    def from_tasks(cls, parent, tasks):
        """Build a Family by selecting `parent`'s children from `tasks` using `task_children_map`."""
        p = _raw_dict(parent)
        pid = p.get("id") if p is not None else None
        children = task_children_map(tasks).get(pid, []) if pid else []
        return cls(parent, children)

    @property
    def counts(self):
        """Status -> count mapping across `children`."""
        out = {}
        for child in self.children:
            st = str(child.get("status") or "")
            out[st] = out.get(st, 0) + 1
        return out

    def summary(self, dep_by_id=None, *, tr_fn=None):
        """Existing concise children progress summary (`format_children_summary`)."""
        return format_children_summary(self.children, dep_by_id=dep_by_id, tr_fn=tr_fn)

    @property
    def rollup_key(self) -> str:
        """Canonical state key over sorted `(child_id, child_status)` pairs."""
        return rollup_key_for(self.children)

    def rollup(self, active, closed, *, own_session_live: bool = False, tr_fn=None):
        """Return a `Rollup` proposal for `parent`, or `None` when nothing should happen.

        `active` and `closed` are the caller-supplied status collections (from `ACTIVE` and `CLOSED`),
        keeping this module independent of `_legacy` until `ledger/task.py` lands.
        """
        if not self.children:
            return None
        active_set = set(active)
        closed_set = set(closed)
        parent_status = str(self.parent.get("status") or "")
        if parent_status in closed_set:
            return None
        statuses = [str(c.get("status") or "") for c in self.children]
        if any(s in active_set or s not in closed_set for s in statuses):
            return None
        counts = self.counts
        total = len(self.children)
        if all(s == "abandoned" for s in statuses):
            return Rollup(
                action="notify",
                reason="all_abandoned",
                summary=_format_rollup_summary(total, counts, all_abandoned=True, tr_fn=tr_fn),
                counts=counts,
            )
        summary = _format_rollup_summary(total, counts, all_abandoned=False, tr_fn=tr_fn)
        if parent_status == "blocked":
            return Rollup(action="notify", reason="parent_blocked", summary=summary, counts=counts)
        if _parent_has_own_work(self.parent, own_session_live=own_session_live):
            return Rollup(action="notify", reason="parent_has_work", summary=summary, counts=counts)
        return Rollup(action="close", reason="children_finished", summary=summary, counts=counts)


def parent_of(task_id: str, parent: str, *, repo: str | None = None, ledger: Any = None, home: Any = None) -> str:
    """`--parent`: the id (or `#N`) of the task this one was split from (the project view lists it under that task).
    Checked against the ledger: a task id that exists, and no loop (the task itself, or one split from it,
    as its parent); '' removes it."""
    if not parent:
        return parent
    if parse_task_num_ref(parent) is not None:
        parent = ledger.resolve_id(parent, repo=repo) if ledger is not None else resolve_task_id(parent, repo=repo)
    if not re.fullmatch(r"[^/\\\s.][^/\\\s]*", parent) or ".." in parent:  # a file name in tasks/, nothing more
        raise Refused(f"not a task id: {parent}")
    h = home if home is not None else (ledger.ctx.home if ledger is not None else home_mod.current())
    use_store = ledger is not None and (home is None or home == ledger.ctx.home)
    if not h.task(parent).exists():
        raise NotFound(f"no task {parent} to be the parent of {task_id or 'this task'}")
    seen, up = set(), parent
    while up and up not in seen:
        if up == task_id:
            raise Refused(f"{parent} cannot be the parent of {task_id}: that would make a loop")
        seen.add(up)
        if use_store:
            data = ledger.ctx.store.task(up)
            up = data.get("parent") if isinstance(data, dict) else None
        else:
            path = h.task(up)
            up = json.loads(path.read_text(encoding="utf-8")).get("parent") if path.exists() else None
    return parent
