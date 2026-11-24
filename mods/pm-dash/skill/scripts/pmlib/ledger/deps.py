"""Task dependencies (--depends-on): parsing, cycle checks, evaluation, and display. Layer 2."""
from __future__ import annotations

import json
import re
from typing import Any

from .. import home as home_mod
from ..config import tr
from ..errors import NotFound, Refused

DEP_MET_STATUSES = ("merged", "released", "done")
_DEP_STATUS_ZH = {
    "proposed": "待做", "in_progress": "进行中", "review": "审查中", "blocked": "等用户",
    "paused": "已暂停", "merged": "已合并", "released": "已发布", "done": "已完成",
    "abandoned": "已放弃", "landed": "已合并", "missing": "不存在",
}


def _read_dep_task(task_id: str, *, home: Any = None, store: Any = None) -> dict[str, Any] | None:
    if store is not None:
        return store.task(task_id)
    h = home if home is not None else home_mod.current()
    path = h.task(task_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _dep_task_exists(task_id: str, *, home: Any = None, store: Any = None) -> bool:
    if home is not None:
        return home.task(task_id).exists()
    if store is not None:
        return store.task(task_id) is not None
    return home_mod.current().task(task_id).exists()


def _check_dep_cycle(task_id: str, dep_id: str, *, home: Any = None, store: Any = None, tr_fn=None) -> None:
    """Reject a dependency edge `task_id -> dep_id` that would create a cycle in `depends_on`."""
    if not task_id or not dep_id:
        return
    t = tr_fn or tr
    if dep_id == task_id:
        raise Refused(t(f"{task_id} cannot depend on itself", f"{task_id} 不能依赖自己"))
    seen, stack = set(), [dep_id]
    while stack:
        cur = stack.pop()
        if cur == task_id:
            raise Refused(t(f"{task_id} cannot depend on {dep_id}: that would make a dependency cycle",
                            f"{task_id} 不能依赖 {dep_id}：会形成循环依赖"))
        if cur in seen:
            continue
        seen.add(cur)
        data = _read_dep_task(cur, home=home, store=store)
        if not data:
            continue
        for nxt in data.get("depends_on") or []:
            if isinstance(nxt, str) and nxt and nxt not in seen:
                stack.append(nxt)


def _validate_dep_id(tok: str, task_id: str = "", *, home: Any = None, store: Any = None, tr_fn=None) -> str:
    t = tr_fn or tr
    if not re.fullmatch(r"[^/\\\s.][^/\\\s]*", tok) or ".." in tok:
        raise Refused(t(f"not a task id: {tok}", f"不是有效的任务 ID：{tok}"))
    if not _dep_task_exists(tok, home=home, store=store):
        raise NotFound(t(f"no task {tok} to depend on", f"找不到依赖的任务：{tok}"))
    _check_dep_cycle(task_id, tok, home=home, store=store, tr_fn=t)
    return tok


def parse_depends_on(values: Any, task_id: str = "", existing: Any = None, *, home: Any = None, store: Any = None, tr_fn=None) -> list[str] | None:
    """Parse `--depends-on` values into a normalized list of task IDs, or None if not provided.

    Supports comma-separated values and repeated flags:
    - `a,b`: replace with `["a", "b"]`
    - `""`: clear all dependencies (`[]`)
    - `+c` / `-a` (incremental add/remove on `existing` when every token is prefixed with `+` or `-`):
      e.g. `--depends-on +c`, `--depends-on=-a`, or `--depends-on "+c,-a"`.
    """
    if values is None:
        return None
    t = tr_fn or tr
    raw_list = [values] if isinstance(values, str) else list(values)
    tokens = []
    for item in raw_list:
        if item is None:
            continue
        for part in str(item).split(","):
            tok = part.strip()
            if tok:
                tokens.append(tok)
    if not tokens:
        return []
    if all(tok[0] in ("+", "-") and len(tok) > 1 for tok in tokens):
        cur = [x for x in (existing or []) if isinstance(x, str) and x.strip()]
        for tok in tokens:
            op, ref = tok[0], tok[1:].strip()
            if op == "-":
                cur = [x for x in cur if x != ref]
            else:
                _validate_dep_id(ref, task_id, home=home, store=store, tr_fn=t)
                if ref not in cur:
                    cur.append(ref)
        return cur
    out = []
    for tok in tokens:
        if tok[0] in ("+", "-"):
            raise Refused(t("do not mix +/- incremental edits with full task IDs in --depends-on",
                            "--depends-on 不能同时混用 +/- 增删和全量任务 ID"))
        _validate_dep_id(tok, task_id, home=home, store=store, tr_fn=t)
        if tok not in out:
            out.append(tok)
    return out


def evaluate_depends_on(task: Any, tasks_by_id: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a task's `depends_on` list against current ledger state.

    Returns `{depends_on, items, ready, all_met, waiting, met, abandoned, missing, broken}`:
    - A dependency is met when its task is `merged`, `done`, `released`, or has `landed` set.
    - `ready` is True when `task` is `proposed` and all dependencies are met (including when `depends_on` is empty).
    """
    raw_deps = [x for x in (task.get("depends_on") or []) if isinstance(x, str) and x.strip()]
    items = []
    for dep_id in raw_deps:
        target = tasks_by_id.get(dep_id)
        if target is not None:
            st = str(target.get("status") or "")
            title = str(target.get("title") or dep_id)
            if st in DEP_MET_STATUSES or bool(target.get("landed")):
                state = "met"
                reason = st if st in DEP_MET_STATUSES else "landed"
            elif st == "abandoned":
                state, reason = "abandoned", "abandoned"
            else:
                state, reason = "waiting", st
            items.append({"id": dep_id, "title": title, "state": state, "status": st, "reason": reason})
        else:
            items.append({"id": dep_id, "title": dep_id, "state": "missing", "status": "missing", "reason": "missing"})
    met = [d for d in items if d["state"] == "met"]
    waiting = [d for d in items if d["state"] == "waiting"]
    abandoned = [d for d in items if d["state"] == "abandoned"]
    missing = [d for d in items if d["state"] == "missing"]
    broken = abandoned + missing
    all_met = len(waiting) == 0 and len(broken) == 0
    # Only `proposed` tasks WITH `depends_on` whose prerequisites are all met are "ready to dispatch" (可以派了);
    # dependency-free `proposed` tasks remain ordinary Todo items and are neither pinned nor prompted.
    ready = bool(task.get("status") == "proposed" and raw_deps and all_met)
    return {
        "depends_on": raw_deps, "items": items, "ready": ready, "all_met": all_met,
        "waiting": waiting, "met": met, "abandoned": abandoned, "missing": missing, "broken": broken,
    }


def dep_key_for(info: dict[str, Any]) -> str:
    """Canonical deduplication key for dependency wake notifications, or '' when no notification is due."""
    if not info.get("depends_on"):
        return ""
    if info.get("abandoned"):
        return "abandoned:" + ",".join(sorted(d["id"] for d in info["abandoned"]))
    if info.get("ready"):
        return "ready:" + ",".join(info["depends_on"])
    return ""


def _dep_status_label(word: str, tr_fn=None) -> str:
    t = tr_fn or tr
    return t(word, _DEP_STATUS_ZH.get(word, word))


def format_dep_item(item: dict[str, Any], *, tr_fn=None) -> str:
    """Compact human-readable description of one evaluated dependency item."""
    t = tr_fn or tr
    dep_id, state = item["id"], item["state"]
    if state == "met":
        r = _dep_status_label(item["reason"], tr_fn=t)
        return t(f"{dep_id} ({r})", f"{dep_id}（{r}）")
    if state == "abandoned":
        return t(f"{dep_id} (abandoned!)", f"{dep_id}（已放弃！）")
    if state == "missing":
        return t(f"{dep_id} (missing!)", f"{dep_id}（不存在！）")
    st = _dep_status_label(item["status"], tr_fn=t)
    return t(f"{dep_id} ({st})", f"{dep_id}（{st}）")


def format_dep_summary(info: dict[str, Any], *, include_empty: bool = False, tr_fn=None) -> str:
    """One-line summary of a task's dependency state, or '' if empty and `include_empty` is False."""
    t = tr_fn or tr
    if not info["depends_on"]:
        return t("no dependencies", "无前置依赖") if include_empty else ""
    sep = t(", ", "、")
    if info["broken"]:
        parts = [format_dep_item(d, tr_fn=t) for d in info["broken"] + info["waiting"]]
        return t("blocked by broken dep: ", "前置异常：") + sep.join(parts)
    if info["waiting"]:
        return t("waiting on: ", "等 ") + sep.join(format_dep_item(d, tr_fn=t) for d in info["waiting"])
    return t("all deps met: ", "前置已满足：") + sep.join(format_dep_item(d, tr_fn=t) for d in info["met"])


def _dep_event_message(task: Any, info: dict[str, Any], key: str, *, tr_fn=None) -> str:
    t = tr_fn or tr
    sep = t(", ", "、")
    title = task.get("title") or task["id"]
    brief = task.get("brief") or t("(none)", "（未登记）")
    parent = task.get("parent") or ""
    if key.startswith("abandoned:"):
        ab = sep.join(format_dep_item(d, tr_fn=t) for d in info["abandoned"])
        return t(
            f"Dependency abandoned ({title}): {ab}; update --depends-on, dispatch anyway, or abandon this task",
            f"前置依赖已放弃（{title}）：{ab}；请决定修改依赖（--depends-on）、继续派发或放弃该任务",
        )
    met = sep.join(format_dep_item(d, tr_fn=t) for d in info["met"])
    parent_tail = t(f"; parent: {parent}", f"；父任务：{parent}") if parent else ""
    return t(
        f"Dependencies met, ready to dispatch ({title}); met: {met}; brief: {brief}{parent_tail}",
        f"前置依赖已满足，可以派了（{title}）；已满足：{met}；任务书：{brief}{parent_tail}",
    )
