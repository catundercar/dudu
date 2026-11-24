"""BOARD.md, the ledger as a table per project, rewritten after every save. Layer 2."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..context import Context
from ..store import replace_task_file, write_atomic
from .ledger import Ledger, all_tasks
from .task import ACTIVE, CLOSED


class Board:
    """Renders and writes `BOARD.md` over an explicit `Context`."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def write(self, tasks: list[dict[str, Any]] | None = None) -> Path:
        rows = self.ctx.store.tasks() if tasks is None else tasks
        ledger = Ledger(self.ctx)
        lines = ["# PM Board", "", f"Updated {self.ctx.clock.now()}. Ledger: `{self.ctx.home.tasks}`.", ""]
        for project in sorted({t["project"] for t in rows}):
            mine = [t for t in rows if t["project"] == project]
            active = [t for t in mine if t["status"] in ACTIVE]
            closed = [t for t in mine if t["status"] in CLOSED][:8]
            lines += [f"## {project}", "", "| Task | Status | Owner | Where | Branch | Updated | Latest |",
                      "| --- | --- | --- | --- | --- | --- | --- |"]
            all_by_id = {x["id"]: x for x in active + closed}
            for t in active + closed:
                latest = (t.get("log") or [{}])[-1].get("text", "").replace("|", "/")[:80]
                where = " ".join(x for x in (t.get("pane"), t.get("agent")) if x)
                tag = ledger.task_num_label(t, all_by_id)
                prefix = f"{tag} " if tag else ""
                lines.append(f"| {prefix}{t['title']} (`{t['id']}`) | {t['status']} | {t.get('owner', '')} | {where} "
                             f"| {t.get('branch') or ''} | {t['updated'][5:]} | {latest} |")
            lines.append("")
        self.ctx.home.root.mkdir(parents=True, exist_ok=True)
        write_atomic(self.ctx.home.board, "\n".join(lines).encode("utf-8"), replace_fn=replace_task_file)
        return self.ctx.home.board


def write_board() -> None:
    Board(Context.from_env()).write(tasks=all_tasks())
