"""Who a `pm.py notify` goes to (`Notifier.target` / `notify_target`): the PM of the named project, of this
terminal's task, of the current folder or one above it, or of this pane's workspace. Layer 3.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..context import Context
from ..project.project import ProjectRegistry


class Notifier:
    """Resolves the target PM for `pm.py notify` over an explicit `Context`."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._projects = ProjectRegistry(ctx)

    def target(self, repo: str | Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
        """(PM agent or None, registration, how found) of the PM a notify goes to."""
        def registered(where: str | Path) -> dict[str, Any]:
            rec = self._projects.pm_record(where) or {}
            return {} if rec.get("archived") else rec

        def of_task() -> tuple[dict[str, Any] | None, dict[str, Any], str] | None:
            task = self.ctx.caller.own_task
            if task and task.get("repo"):
                pm = self._projects.find_pm(repo=task["repo"])
                rec = registered(task["repo"])
                if pm or rec.get("name"):
                    return pm, rec, f"task {task['id']}"
            return None

        named = bool(repo)
        found = None if named else of_task()
        if found:
            return found
        target_repo = str(repo) if repo else "."
        pm, rec = self._projects.find_pm(repo=target_repo), registered(target_repo)
        if pm or rec.get("name"):
            return pm, rec, "project"
        home = Path.home().resolve()
        for folder in Path(target_repo).resolve().parents:
            if folder == home or folder == Path(folder.anchor):
                break
            rec = registered(str(folder))
            # Registrations are named by folder name: this one must be for this folder, not a namesake elsewhere.
            root = self.ctx.git.project_root(str(folder))
            if rec.get("name") and root and Path(rec.get("repo") or "").resolve() == Path(root).resolve():
                return self._projects.find_pm(repo=str(folder)), rec, str(folder)
        if named:
            return None, {}, ""
        # Working in a folder no PM is registered for, inside a PM's workspace: that PM is the one to tell.
        rec = self.ctx.caller.workspace_registration() or {}
        pm = next((x for x in self.ctx.tui.agents() if rec.get("name") and x.get("name") == rec["name"]
                   and x.get("pane_id") == rec.get("pane")), None)
        return pm, rec, "workspace"


# ── Legacy module-level wrapper (Stages 1-5 compatibility bridge) ──────────────────────────────────────────────

def notify_target(repo: str | Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    return Notifier(Context.from_env()).target(repo)
