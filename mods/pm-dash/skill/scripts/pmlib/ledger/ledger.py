"""The task ledger: `Change`, `Ledger`, reading a task (by id or by number), the locked read-modify-write that changes
one, instance-scoped pending notes flushed after unlock, and injected `after_save` hooks. Layer 2.
"""
from __future__ import annotations

import contextvars
from pathlib import Path
from typing import Any, Callable, Iterable

from ..context import Context
from ..errors import NotFound, PmError, Refused
from ..home import project_slug
from ..osutil import slugify
from ..project import conversation as conversation_mod
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..store import valid_task_id
from .plan import advance_outer_plan_step
from .task import Task, parse_task_num_ref, task_number
from .transition import Transition, TransitionHooks, TransitionPlan, apply_transition


def _no_caller_projects(reg_idx: Any) -> Iterable[str]:
    return ()


# Scoped only to legacy `mutate_task` -> `note` calls during Stages 3-5 (never used by `Ledger.change` directly).
_ACTIVE_CHANGE: contextvars.ContextVar[Change | None] = contextvars.ContextVar("_active_change", default=None)


class Change:
    """Instance-scoped mutation context passed to `Ledger.change` callbacks; buffers notes until after unlock."""

    def __init__(self, task: Task | None, *, clock: Any, actor: str) -> None:
        self.task = task
        self._clock = clock
        self._actor = actor
        self._pending_notes: list[tuple[str, dict[str, Any]]] = []

    @property
    def pending_notes(self) -> list[tuple[str, dict[str, Any]]]:
        return self._pending_notes

    def note(self, text: str, **extra: Any) -> dict[str, Any]:
        """Log text on `self.task` and queue its conversation `thread` event until after the task file unlocks."""
        if self.task is None:
            raise Refused("cannot note on missing task")
        return self.note_on(self.task.raw, text, **extra)

    def note_on(self, task: dict[str, Any] | Task, text: str, **extra: Any) -> dict[str, Any]:
        """Log text on `task` and queue its conversation `thread` event until after the task file unlocks."""
        raw = task.raw if isinstance(task, Task) else task
        entry = {"at": self._clock.now(), "by": self._actor, "text": text}
        raw.setdefault("log", []).append(entry)
        if raw.get("repo"):  # every ledger entry is also an event in the project's conversation
            num = task_number(raw)
            fields = {
                "task": raw.get("id"),
                "title": raw.get("title"),
                "status": raw.get("status"),
                "by": self._actor,
                "text": text,
                **({"number": num} if num else {}),
                **extra,
            }
            self._pending_notes.append((raw["repo"], fields))
        return entry


class Ledger:
    """Task ledger operations over an explicit `Context` (zero module globals, zero `sys.exit`)."""

    def __init__(
        self,
        ctx: Context,
        *,
        after_save: Iterable[Callable[[], Any]] | None = None,
        caller_projects: Callable[[Any], Iterable[str]] | None = None,
        _save_fn: Callable[[dict[str, Any]], Any] | None = None,
        _record_fn: Callable[..., Any] | None = None,
        _all_tasks_fn: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.ctx = ctx
        self._after_save: tuple[Callable[[], Any], ...] = (
            tuple(after_save) if after_save is not None else tuple(ctx.after_save)
        )
        self._caller_projects = (
            caller_projects if caller_projects is not None else (ctx.caller_projects or _no_caller_projects)
        )
        self._save_fn = _save_fn
        self._record_fn = _record_fn
        self._all_tasks_fn = _all_tasks_fn
        self._projects = ProjectRegistry(ctx)

    def raw_tasks(self) -> list[dict[str, Any]]:
        if self._all_tasks_fn is not None:
            return self._all_tasks_fn()
        return self.ctx.store.tasks()

    def all_tasks(self) -> list[Task]:
        return [Task(t) for t in self.raw_tasks()]

    def project_tasks(self, repo: str | Path) -> list[Task]:
        repo_s = str(repo)
        name = Path(repo_s).name
        return [
            Task(t) for t in self.raw_tasks()
            if t.get("project") == name and str(Path(t["repo"]).resolve()) == repo_s
        ]

    def new_id(self, project: str, hint: str) -> str:
        base = f"{project}-{slugify(hint) or self.ctx.clock.datetime_now().strftime('%m%d-%H%M')}"
        candidate, n = base, 2
        while self.ctx.home.task(candidate).exists():
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def task_num_label(self, task: dict[str, Any] | Task, all_by_id: dict[str, Any] | None = None) -> str:
        """Display tag for a task (`#42`, or `#42-review` for a review thread whose parent is numbered)."""
        raw = task.raw if isinstance(task, Task) else task
        if not isinstance(raw, dict):
            return ""
        num = task_number(raw)
        if num:
            return f"#{num}"
        rev_of = raw.get("review_of")
        if isinstance(rev_of, str) and rev_of:
            parent = all_by_id.get(rev_of) if all_by_id is not None else self.ctx.store.task(rev_of)
            pnum = task_number(parent)
            if pnum:
                return f"#{pnum}-review"
        return ""

    def task_ref(self, task: dict[str, Any] | Task, all_by_id: dict[str, Any] | None = None) -> str:
        """Human+ID label (`#42 <id>` or `#42-review <id>`), falling back to `<id>` when unnumbered."""
        raw = task.raw if isinstance(task, Task) else task
        if not isinstance(raw, dict):
            return ""
        tid = str(raw.get("id") or "")
        label = self.task_num_label(raw, all_by_id)
        return f"{label} {tid}" if label and tid else (label or tid)

    def _current_project_scope(self, tasks: list[dict[str, Any]], reg_idx: Any, repo: str | Path | None = None) -> str | None:
        """Infer the active project slug when resolving bare `#N`, or None when ledger-wide."""
        if repo is not None:
            r = self.ctx.git.project_root(repo)
            if r:
                return project_slug(r)
        known = {self.ctx.store._task_slug(t, reg_idx) for t in tasks}
        for _stem, rslug, _resolved, _proj in reg_idx:
            if rslug:
                known.add(rslug)
        if self.ctx.pane:
            for s in self._caller_projects(reg_idx):
                if s in known:
                    return s
        cwd_root = self.ctx.git.project_root(".")
        if cwd_root:
            s = project_slug(cwd_root)
            if s in known:
                return s
        return None

    def _resolve_num_ref(
        self,
        ref: str,
        parsed: tuple[str, int, bool],
        *,
        repo: str | Path | None = None,
        required: bool = True,
    ) -> str | None:
        proj_raw, number, want_review = parsed
        tasks = self.raw_tasks()
        reg_idx = self.ctx.store._reg_index()
        if proj_raw:
            proj_slug = self._projects.resolve_project_slug(proj_raw)
            candidates = [
                t for t in tasks
                if task_number(t) == number and (
                    self.ctx.store._task_slug(t, reg_idx) == proj_slug
                    or str(t.get("project") or "").lower() == proj_raw.lower()
                )
            ]
            scope_label = proj_slug or proj_raw
        else:
            scope = self._current_project_scope(tasks, reg_idx, repo=repo)
            if scope:
                candidates = [
                    t for t in tasks
                    if task_number(t) == number and self.ctx.store._task_slug(t, reg_idx) == scope
                ]
                scope_label = scope
            else:
                candidates = [t for t in tasks if task_number(t) == number]
                scope_label = ""
        if want_review:
            parent_ids = {c["id"] for c in candidates}
            by_parent = [t for t in tasks if t.get("review_of") in parent_ids]
            if not by_parent:
                if not required:
                    return None
                if len(candidates) == 1:
                    raise NotFound(f"no review task for #{number} ({candidates[0]['id']})")
                where = f" in project {scope_label}" if scope_label else ""
                raise NotFound(f"no task #{number}-review{where}")
            if len(by_parent) > 1:
                desc = ", ".join(f"{self.ctx.store._task_slug(t, reg_idx)}#{number}-review ({t['id']})" for t in by_parent)
                raise Refused(f"ambiguous task reference {ref}: matches {desc}; use <project>#{number}-review or full task id")
            return by_parent[0]["id"]
        if not candidates:
            if not required:
                return None
            where = f" in project {scope_label}" if scope_label else ""
            raise NotFound(f"no task #{number}{where}")
        if len(candidates) > 1:
            desc = ", ".join(f"{self.ctx.store._task_slug(t, reg_idx)}#{number} ({t['id']})" for t in candidates)
            raise Refused(f"ambiguous task reference {ref}: matches {desc}; use <project>#{number} or full task id")
        return candidates[0]["id"]

    def resolve_id(self, ref: Any, *, repo: str | Path | None = None) -> Any:
        """Resolve a task slug id or `#N` / `N` / `#N-review` / `<proj>#N` reference to canonical task slug id."""
        if not isinstance(ref, str) or not ref:
            return ref
        if "#" not in ref and valid_task_id(ref) and self.ctx.home.task(ref).is_file():
            return ref
        parsed = parse_task_num_ref(ref)
        if parsed is not None:
            return self._resolve_num_ref(ref, parsed, repo=repo, required=True)
        return ref

    def try_resolve_id(self, ref: Any, *, repo: str | Path | None = None) -> str | None:
        """Resolve `ref` if it names an existing task slug or task number (`#N` raises on miss; bare digits return None)."""
        if not isinstance(ref, str) or not ref or ref.startswith("hc:"):
            return None
        if "#" not in ref and valid_task_id(ref) and self.ctx.home.task(ref).is_file():
            return ref
        parsed = parse_task_num_ref(ref)
        if parsed is not None:
            return self._resolve_num_ref(ref, parsed, repo=repo, required=("#" in ref))
        return None

    def _load_impl(self, task_id: str, *, repo: str | Path | None = None) -> Task:
        tid = self.resolve_id(task_id, repo=repo)
        if not valid_task_id(tid):
            raise NotFound(f"no task {task_id}")
        task = self.ctx.store.task(tid, strict=True)
        if task is None:
            raise NotFound(f"no task {task_id}")
        return Task(task)

    def load(self, task_id: str, *, repo: str | Path | None = None) -> Task:
        if getattr(self.ctx, "_legacy", False) and load is not _DEFAULT_LOAD:
            res = load(task_id) if repo is None else load(task_id, repo=repo)
            return Task.from_dict(res)
        return self._load_impl(task_id, repo=repo)

    def run_after_save(self) -> None:
        """Run injected `after_save` hooks in order."""
        for then in self._after_save:
            then()

    def _emit_thread(self, repo: str, fields: dict[str, Any]) -> None:
        if self._record_fn is not None:
            self._record_fn(repo, "thread", **fields)
        else:
            Conversation(self.ctx, repo).record("thread", **fields)

    def _save_impl(self, task: Task | dict[str, Any]) -> Task:
        raw = task.raw if isinstance(task, Task) else task
        raw["updated"] = self.ctx.clock.now()
        self.ctx.store.change_task(raw["id"], lambda _cur: raw)
        self.run_after_save()
        return Task(raw)

    def save(self, task: Task | dict[str, Any]) -> Task:
        raw = task.raw if isinstance(task, Task) else task
        if self._save_fn is not None:
            self._save_fn(raw)
            return Task(raw)
        if getattr(self.ctx, "_legacy", False) and save is not _DEFAULT_SAVE:
            save(raw)
            return Task(raw)
        return self._save_impl(raw)

    def change(
        self,
        task_id: str,
        fn: Callable[[Task | None, Change], Task | dict[str, Any] | None],
        *,
        create: bool = False,
        board: bool = True,
    ) -> Task | None:
        """Locked read-modify-write of a task through `ctx.store.change_task`.

        Notes appended via `change.note(...)` inside `fn` are written to `conversation.jsonl` only after
        the task file is atomically saved and unlocked; `after_save` hooks also run after unlock.
        """
        if not create:
            task_id = self.resolve_id(task_id)
        pending: list[tuple[str, dict[str, Any]]] = []
        wrote = False
        actor = self.ctx.pane or "user"

        def _run(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal wrote
            cur_task = Task(cur) if isinstance(cur, dict) else None
            ch = Change(cur_task, clock=self.ctx.clock, actor=actor)
            result = fn(cur_task, ch)
            if result is None:
                return None
            raw = result.raw if isinstance(result, Task) else result
            raw["updated"] = self.ctx.clock.now()
            pending.extend(ch.pending_notes)
            wrote = True
            return raw

        save_hook = self._save_fn
        if save_hook is None and getattr(self.ctx, "_legacy", False) and save is not _DEFAULT_SAVE:
            save_hook = save
        if save_hook is not None:
            cur = self.ctx.store.task(task_id, strict=True) if create else self._load_impl(task_id).raw
            result = _run(cur)
            if result is None:
                return Task(cur) if isinstance(cur, dict) else None
            if board:
                save_hook(result)
            else:
                self.ctx.store.change_task(task_id, lambda _cur: result)
            for repo, fields in pending:
                self._emit_thread(repo, fields)
            return Task(result)

        def _apply(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            if cur is None and not create:
                raise NotFound(f"no task {task_id}")
            return _run(cur)

        result = self.ctx.store.change_task(task_id, _apply)
        if wrote:
            for repo, fields in pending:
                self._emit_thread(repo, fields)
            if board:
                self.run_after_save()
        return Task(result) if isinstance(result, dict) else None

    def create(
        self,
        task: Task | dict[str, Any],
        *,
        note_text: str | None = None,
        note_extra: dict[str, Any] | None = None,
        board: bool = True,
    ) -> Task:
        """Create a new task record atomically, optionally logging its initial note after unlock."""
        raw = task.raw if isinstance(task, Task) else dict(task)
        tid = raw["id"]

        def _init(_cur: Task | None, ch: Change) -> dict[str, Any]:
            if note_text is not None:
                ch.note_on(raw, note_text, **(note_extra or {}))
            return raw

        created = self.change(tid, _init, create=True, board=board)
        assert created is not None
        if raw.get("parent"):
            self.clear_rollup_notified(raw.get("parent"))
        return created

    def clear_rollup_notified(self, parent_id: str | None) -> None:
        """Drop `rollup_notified` on `parent_id` when a child task is added or reopened."""
        if not parent_id or not valid_task_id(parent_id):
            return
        snap = self.ctx.store.task(parent_id)
        if not isinstance(snap, dict) or "rollup_notified" not in snap:
            return

        def _drop(cur: Task | None, _ch: Change) -> dict[str, Any] | None:
            if cur is None or "rollup_notified" not in cur.raw:
                return None
            cur.raw.pop("rollup_notified", None)
            return cur.raw

        try:
            self.change(parent_id, _drop, board=False)
        except (PmError, OSError):
            return

    def advance_step(
        self,
        task_id: str,
        *,
        on_task: Callable[[dict[str, Any]], Any] | None = None,
    ) -> tuple[Task, bool, int, int, str]:
        """Silent fast-path (`--step-done` alone): check off the active outer plan step under `board=False`."""
        step_res: dict[str, Any] = {"changed": False, "done": 0, "total": 0, "next": ""}

        def _apply(cur: Task | None, _ch: Change) -> dict[str, Any] | None:
            assert cur is not None
            raw = cur.raw
            changed, d, t, nxt = advance_outer_plan_step(raw)
            step_res.update({"changed": changed, "done": d, "total": t, "next": nxt})
            if on_task is not None:
                on_task(raw)
            return raw if changed else None

        task = self.change(task_id, _apply, board=False)
        assert task is not None
        return task, bool(step_res["changed"]), int(step_res["done"]), int(step_res["total"]), str(step_res["next"])

    def update_subplan(
        self,
        task_id: str,
        sub_steps: list[dict[str, Any]],
        *,
        on_task: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Task:
        """Silent fast-path (`--subplan` or worker `--plan` alone): update or clear `subplan` under `board=False`."""
        def _apply(cur: Task | None, _ch: Change) -> dict[str, Any]:
            assert cur is not None
            raw = cur.raw
            if sub_steps:
                raw["subplan"] = [dict(s) for s in sub_steps]
            else:
                raw.pop("subplan", None)
            if on_task is not None:
                on_task(raw)
            return raw

        task = self.change(task_id, _apply, board=False)
        assert task is not None
        return task

    def transition(self, task_id: str, plan: TransitionPlan, hooks: TransitionHooks) -> Transition:
        """The logged change of `pm.py update` (Phase B) inside one task lock: fields, status, dependencies, plans,
        question card, auto-review mark and the ledger entry; the entry's conversation event and `after_save`
        follow once the file is saved and unlocked."""
        result = Transition(plan=plan)

        def _apply(cur: Task | None, ch: Change) -> dict[str, Any]:
            assert cur is not None
            return apply_transition(cur.raw, plan, hooks, ch.note_on, self.ctx.clock.now(), result)

        self.change(task_id, _apply)
        return result

    def append_note(self, task: Task | dict[str, Any], text: str, **extra: Any) -> dict[str, Any]:
        """Append a log entry to `task` and immediately record its `thread` event (outside `change`)."""
        raw = task.raw if isinstance(task, Task) else task
        ch = Change(Task(raw), clock=self.ctx.clock, actor=self.ctx.pane or "user")
        entry = ch.note_on(raw, text, **extra)
        for repo, fields in ch.pending_notes:
            self._emit_thread(repo, fields)
        return entry


def task_num_label(task: Any, all_by_id: dict[str, Any] | None = None) -> str:
    """Display tag for a task (`#42`, or `#42-review` for a review thread whose parent is numbered)."""
    return Ledger(Context.from_env()).task_num_label(task, all_by_id)


def task_ref(task: Any, all_by_id: dict[str, Any] | None = None) -> str:
    """Human+ID label (`#42 <id>` or `#42-review <id>`), falling back to `<id>` when unnumbered."""
    return Ledger(Context.from_env()).task_ref(task, all_by_id)


def resolve_task_id(ref: Any, *, repo: str | Path | None = None) -> Any:
    """Resolve a task slug id or `#N` / `N` / `#N-review` / `<proj>#N` reference to canonical task slug id."""
    return Ledger(Context.from_env()).resolve_id(ref, repo=repo)


def try_resolve_task_id(ref: Any, *, repo: str | Path | None = None) -> str | None:
    """Resolve `ref` if it names an existing task slug or task number (`#N` raises on miss; bare digits return None)."""
    return Ledger(Context.from_env()).try_resolve_id(ref, repo=repo)


def load(task_id: str, *, repo: str | Path | None = None) -> dict[str, Any]:
    return Ledger(Context.from_env())._load_impl(task_id, repo=repo).raw


_DEFAULT_LOAD = load


def after_save() -> None:
    """Run what follows a saved task (`ctx.after_save`), in order."""
    Ledger(Context.from_env()).run_after_save()


def save(task: dict[str, Any]) -> None:
    Ledger(Context.from_env())._save_impl(task)


_DEFAULT_SAVE = save


def mutate_task(
    task_id: str,
    change: Callable[[dict[str, Any] | None], dict[str, Any] | None],
    *,
    create: bool = False,
    board: bool = True,
) -> dict[str, Any] | None:
    """Locked read-modify-write of a task through `Ledger.change`.

    Notes appended via `note(...)` inside `change` are buffered on the active `Change` instance until
    the task file is atomically saved and unlocked; `after_save` hooks also run after unlock. If a test
    replaced `pm.save`, the replacement is invoked so existing spies/mocks keep working.
    """
    def _bridge(cur: Task | None, ch: Change) -> dict[str, Any] | None:
        tok = _ACTIVE_CHANGE.set(ch)
        try:
            return change(cur.raw if cur is not None else None)
        finally:
            _ACTIVE_CHANGE.reset(tok)

    result = Ledger(Context.from_env()).change(task_id, _bridge, create=create, board=board)
    return result.raw if result is not None else None


def all_tasks() -> list[dict[str, Any]]:
    return Context.from_env().store.tasks()


_DEFAULT_ALL_TASKS = all_tasks


def note(task: dict[str, Any], text: str, **extra: Any) -> None:
    """Log text on the task. extra (such as `options`, the quick answers a blocked task offers) joins the
    conversation event."""
    ch = _ACTIVE_CHANGE.get()
    if ch is not None:
        ch.note_on(task, text, **extra)
    else:
        Ledger(Context.from_env()).append_note(task, text, **extra)


def new_id(project: str, hint: str) -> str:
    return Ledger(Context.from_env()).new_id(project, hint)


def project_tasks(repo: str | Path) -> list[dict[str, Any]]:
    return [t.raw for t in Ledger(Context.from_env()).project_tasks(repo)]
