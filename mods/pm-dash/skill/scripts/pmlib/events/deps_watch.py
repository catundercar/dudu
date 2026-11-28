"""Task dependencies as the deliverer watches them: a `proposed` task whose `depends_on` tasks are all met (or
abandoned) gets one `deps` event per dependency state, and the project's PM is woken. It reads every task and writes
the ledger, so it is not a rule (`ledger/deps.py` has those); the deliverer asks it each look as an injected watcher
(`DependencyWatcher.look` / `look_at_dependencies`), and a status change asks it for the tasks that depend on the
changed one (`reconcile_dependents_of`). Layer 3.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..context import Context
from ..errors import PmError
from ..ledger.deps import _dep_event_message, dep_key_for, evaluate_depends_on
from ..ledger.ledger import Ledger
from ..osutil import unfailing
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry, in_scope
from .deliver import Delivery


class DependencyWatcher:
    """Reconciles `proposed` tasks whose `depends_on` tasks are met or abandoned, over an explicit `Context`."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ledger = Ledger(ctx)
        self._projects = ProjectRegistry(ctx)

    def reconcile(
        self,
        repo: str | Path | None = None,
        *,
        only_tasks: Iterable[str] | None = None,
    ) -> list[tuple[dict[str, Any], str, str]]:
        """Detect `proposed` tasks whose `depends_on` tasks just became all met (or abandoned), record a `deps`
        event once per dependency state, and wake the project's desktop-app PM.

        Idempotent and race-safe: claims `deps_notified` under the task's exclusive file lock before recording
        the event."""
        every = self._ledger.raw_tasks()
        only_set = set(only_tasks) if only_tasks is not None else None
        scope_slug = self.ctx.store.folder_project_slug(repo) if repo else ""
        candidates = [
            t for t in every
            if isinstance(t, dict) and t.get("status") == "proposed" and t.get("depends_on")
            and (t.get("repo") or t.get("project_slug"))
            and (
                not repo
                or (t.get("repo") and in_scope(t["repo"], repo))
                or (scope_slug and self.ctx.store.task_project_slug(t) == scope_slug)
            )
            and (only_set is None or t.get("id") in only_set)
        ]
        if not candidates:
            return []
        by_id = {t["id"]: t for t in every if isinstance(t, dict) and t.get("id")}
        emitted: list[tuple[dict[str, Any], str, str]] = []
        for t in candidates:
            info = evaluate_depends_on(t, by_id)
            key = dep_key_for(info)
            if not key or t.get("deps_notified") == key:
                continue
            expected_deps = list(info["depends_on"])
            claimed = False

            def _claim(cur: Any, _ch: Any) -> Any:
                nonlocal claimed
                claimed = False
                raw = cur.raw
                if raw.get("status") != "proposed" or list(raw.get("depends_on") or []) != expected_deps:
                    return cur
                if raw.get("deps_notified") == key:
                    return cur
                raw["deps_notified"] = key
                claimed = True
                return cur

            try:
                fresh_task = self._ledger.change(t["id"], _claim, board=False)
            except (PmError, OSError):
                continue
            if not claimed or fresh_task is None:
                continue
            fresh = fresh_task.raw
            pslug = self.ctx.store.task_project_slug(fresh)
            t_repo = str(fresh.get("repo") or "")
            msg = _dep_event_message(fresh, info, key, tr_fn=self.ctx.config.tr)
            wake = bool(self._projects.app_pm(pslug or t_repo))
            Conversation(self.ctx, t_repo, slug=pslug or None).record(
                "event", task=fresh["id"], title=fresh.get("title") or "",
                brief=fresh.get("brief") or "", depends_on=expected_deps,
                source="deps", by="pm.py", key=key, text=msg, wake=wake,
            )
            if wake:
                Delivery(self.ctx, t_repo, slug=pslug or None).ensure_running()
            emitted.append((fresh, key, msg))
        return emitted

    def reconcile_dependents_of(
        self,
        task_id: str,
        primary_repo: str | Path | None = None,
    ) -> list[tuple[dict[str, Any], str, str]]:
        """Reconcile any `proposed` task (in the same or another project) whose `depends_on` includes `task_id`."""
        if not task_id:
            return []
        every = self._ledger.raw_tasks()
        affected = [
            t for t in every
            if isinstance(t, dict) and t.get("status") == "proposed"
            and (t.get("repo") or t.get("project_slug"))
            and any(isinstance(d, str) and d.strip() == task_id for d in (t.get("depends_on") or []))
        ]
        if not affected:
            return []
        out: list[tuple[dict[str, Any], str, str]] = []
        repos = list(dict.fromkeys(
            ([primary_repo] if primary_repo else [])
            + [t.get("project_slug") or t.get("repo") for t in affected]
        ))
        ids = {t["id"] for t in affected}
        for r in repos:
            if r:
                out.extend(self.reconcile(r, only_tasks=ids))
        return out

    def look(self, repo: str | Path, stops: Any, bases: Any) -> None:
        """The deliverer's look at task dependencies (a watcher): reconcile them, never failing the look, and ask
        for no earlier look."""
        unfailing(self.reconcile, repo)


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def reconcile_dependencies(repo: str | Path | None = None, *, only_tasks: Iterable[str] | None = None) -> list[tuple[dict[str, Any], str, str]]:
    return DependencyWatcher(Context.from_env()).reconcile(repo, only_tasks=only_tasks)


def reconcile_dependents_of(task_id: str, primary_repo: str | Path | None = None) -> list[tuple[dict[str, Any], str, str]]:
    return DependencyWatcher(Context.from_env()).reconcile_dependents_of(task_id, primary_repo=primary_repo)


def look_at_dependencies(repo: str | Path, stops: Any, bases: Any) -> None:
    DependencyWatcher(Context.from_env()).look(repo, stops, bases)
