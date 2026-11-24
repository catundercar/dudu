"""Claiming a project for a PM session, and ending an archived project's PM: re-pointing the PM's open tasks to its
new terminal. Layer 3."""
from __future__ import annotations

from typing import Any, Iterable

from ..context import Context
from ..ledger.ledger import Ledger
from ..ledger.task import ACTIVE, pm_started
from ..project.project import ProjectRegistry, in_scope
from ..project.readmodel import owner_of


def move_pm_tasks_to_pane(
    repo: str,
    old_panes: Iterable[str | None],
    new_pane: str,
    *,
    ctx: Context | None = None,
) -> None:
    """When a desktop-app PM moves to a new terminal (legacy-to-seat rotation, crash recovery rotate, start, restore
    or claim), re-point open tasks parked on the old PM terminal (epics, parent tasks, proposed tasks, question cards)
    to `new_pane` so they do not appear offline/Disconnected."""
    olds = {p for p in (old_panes or ()) if isinstance(p, str) and p and p != new_pane}
    if not new_pane or not olds:
        return
    c = Context.from_env() if ctx is None else ctx
    pms = ProjectRegistry(c).pm_records()
    ledger = Ledger(c)
    for task in ledger.raw_tasks():
        if task.get("status") not in ACTIVE or task.get("pane") not in olds:
            continue
        if task.get("worker_pane") in olds or pm_started(task):
            continue
        if not (in_scope(task.get("repo"), repo) or in_scope((owner_of(task, pms) or {}).get("repo"), repo)):
            continue

        def _repoint(cur: Any, _ch: Any, _olds: set[str] = olds) -> dict[str, Any] | None:
            if cur is None:
                return None
            raw = cur.raw
            if raw.get("status") not in ACTIVE or raw.get("pane") not in _olds:
                return None
            if raw.get("worker_pane") in _olds or pm_started(raw):
                return None
            raw.pop("closed", None)
            raw["pane"] = new_pane
            return raw

        ledger.change(task["id"], _repoint)


def end_pm(rec: dict[str, Any], name: str, *, ctx: Context | None = None) -> str:
    """End an archived project's PM session: the registered one only, and only while it is still this
    project's PM. It first stops being findable as the PM (label or name), so a restore does not take it
    for a live one even when it cannot be ended. Returns the status line for the caller to display."""
    c = Context.from_env() if ctx is None else ctx
    tr = c.config.tr
    if rec.get("runtime") == "hc":
        term = rec.get("terminal") or ""
        info = (c.hc.get_raw(term) or {}) if term else {}
        if not info or (info.get("labels") or {}).get("pm") != name:
            return tr(f"PM hc:{term} is not running", f"PM hc:{term} 不在运行")
        c.hc.label(term, "pm=", "pm.seat=")
        if (info.get("state") != "live" or c.hc.kill(term) is not None) and c.hc.remove(term) is not None:
            return tr(f"PM hc:{term} ended", f"PM hc:{term} 已结束")
        return tr(
            f"PM hc:{term} could not be ended; close it by hand. It no longer counts as the PM.",
            f"PM hc:{term} 结束不了，请手动关掉；它已不再算作 PM。",
        )
    # A PM in the herdr terminal UI: the agent registered under the PM's name in that pane.
    pane = rec.get("pane") or ""
    listing = c.tui.call("agent", "list")
    if listing is None:
        return tr(
            f"herdr is not reachable, so PM {pane} could not be ended; close it by hand.",
            f"herdr 连不上，没法结束 PM {pane}；请手动关掉。",
        )
    if not any(x.get("pane_id") == pane and x.get("name") == rec.get("name") for x in listing.get("agents") or []):
        return tr(f"PM {pane} is not running", f"PM {pane} 不在运行")
    c.tui.agent_rename(pane, f"ex-{rec['name']}")
    if c.tui.pane_close(pane) is not None:
        return tr(f"PM {pane} ended", f"PM {pane} 已结束")
    return tr(
        f"PM {pane} could not be ended; close it by hand. It is renamed ex-{rec['name']} and no longer "
        "counts as the PM.",
        f"PM {pane} 结束不了，请手动关掉；它已改名 ex-{rec['name']}，不再算作 PM。",
    )
