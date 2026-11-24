"""`Workers(ctx)` service: dispatch, messaging, wait, escalation, reattach, adopt, retab, retire, idle-workers,
and worker session/pool helpers over an explicit `Context`. Zero globals, zero `sys.exit`, zero `print`. Layer 3."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Sequence

from ..agents.codex_pool import codex_args
from ..agents.profiles import LADDER, WorkerSpec, asks_first, engine_label, fallback_said, worker_record
from ..caller import Caller
from ..context import Context
from ..errors import NotFound, PmError, Refused, WaitOutcome
from ..events.deliver import deliver_later
from ..events.policy import wake_fields_for
from ..ledger.deps import evaluate_depends_on, format_dep_summary
from ..ledger.family import parent_of
from ..ledger.ledger import Change, Ledger
from ..ledger.plan import parse_plan_steps, sync_plan_for_status
from ..ledger.question import QUESTION_FIELDS
from ..ledger.task import ACTIVE, ATTACHED, CLOSED, Task, hc_terminal_of
from ..memory.layer import MemoryLayer
from ..osutil import file_text, shell_join, slugify, stale_lock
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..terminals.screen import classify_stuck_screen
from ..terminals.tabs import TERM_HEAD, bug_of, hc_name, not_renamed, tab_short, tab_title, task_bug
from .brief import keep_sent_for, report_section_for, sent_repo_for
from . import codex_pool as _codex_pool_mod
from .codex_pool import (
    apply_codex_pool_for,
    codex_fast_for,
    codex_pool_for,
    codex_usage_for,
    deep_confirmed_for,
    release_pool_lock,
)
from .dispatch import (
    PREAPPROVED,
    ask_rule_for,
    dispatch_note_for,
    held_task_for,
    hold_exited_for,
    review_placement_for,
    tui_agent_gone_for,
    worker_argv_for,
    worker_placement_for,
)
from .escalate import (
    ask_escalation_for,
    escalated_name,
    escalation_brief_for,
    own_worker_for,
    quiet_old_worker_for,
    start_escalated_for,
    unmark_switching_for,
)
from .lifecycle import (
    RetireResult,
    active_review_of_for,
    close_later_for,
    close_reported_for,
    close_review_for,
    close_worker_for,
    end_terminal_for,
    end_worker_for,
    idle_minutes_for,
    is_pane_live_for,
    live_worker_for,
    project_workers_for,
    retire_review_for,
    retire_workspace_for,
    term_status,
)
from .reattach import (
    AdoptWorkerResult,
    adopt_task_for,
    offline_now_for,
    reattach_plan_for,
    start_beside_pm_for,
)
from .research import collect_research_for, retire_dirty_for
from .send import (
    SendBackResult,
    send_async_later_for,
    send_back_for,
    send_ready_later_for,
    send_when_ready_for,
)
from .sessions import (
    clear_task_session_for,
    find_session_for,
    pm_session_info_for,
    remember_pm_session_for,
    remember_session_for,
    remember_worker_session_for,
    task_session_info_for,
)
from .wait import WaitResult, wait_for_report_for, waited_tasks_for, waiting_on_for


REPORTED = ("review", *CLOSED)  # idle-workers --close without names ends only these tasks' workers


@dataclass
class DispatchRequest:
    """Typed input for `Workers.dispatch`."""

    title: str | None = None
    repo: str = "."
    branch: str | None = None
    label: str | None = None
    path: str | None = None
    brief: str | None = None
    name: str | None = None
    task: str | None = None
    here: bool = False
    tab: str | None = None
    bug: str = ""
    codex_profile: str | None = None
    dry_run: bool = False
    base: str | None = None
    prep: str | None = None
    parent: str | None = None
    profile: str | None = None
    kind: str | None = None
    model: str | None = None
    effort: str | None = None
    advisor: str | None = None
    confirmed: bool = False
    plan: list[str] | None = None
    step: list[str] | None = None
    outer_plan: list[str] | None = None
    subplan: list[str] | None = None
    no_review: bool = False
    async_: bool = False


@dataclass(frozen=True)
class DispatchResult:
    """Structured outcome of `Workers.dispatch`."""

    task_id: str = ""
    pane: str = ""
    workspace: str = ""
    worktree: str = ""
    lines: tuple[str, ...] = ()
    stderr_lines: tuple[str, ...] = ()
    dry_run_plan: dict[str, Any] | None = None
    asked: bool = False


@dataclass(frozen=True)
class SendResult:
    """Structured outcome of `Workers.send`."""

    queued: bool
    terminal: str
    task_id: str
    message: str


@dataclass
class EscalateRequest:
    """Typed input for `Workers.escalate`."""

    task_id: str
    profile: str | None = None
    why: str | None = None
    advisor: str | None = None
    name: str | None = None
    confirmed: bool = False
    tab: str | None = None
    bug: str = ""
    codex_profile: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class EscalateResult:
    """Structured outcome of `Workers.escalate`."""

    task_id: str
    pane: str = ""
    lines: tuple[str, ...] = ()
    stderr_lines: tuple[str, ...] = ()
    dry_run_plan: dict[str, Any] | None = None
    asked: bool = False
    unsent_error: str = ""


@dataclass(frozen=True)
class ReattachResult:
    """Structured outcome of `Workers.reattach`."""

    task_id: str
    how: str
    kind: str
    pane: str
    session: str = ""
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetabResult:
    """Structured outcome of `Workers.retab`."""

    terminal: str
    name: str
    task_id: str | None = None
    bug: str = ""
    named: bool = False
    dry_run_payload: dict[str, Any] | None = None
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdleWorkersResult:
    """Structured outcome of `Workers.idle_workers`."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    minutes: int = 30
    closed_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodexCmdResult:
    """Structured outcome of `Workers.codex_cmd`."""

    command: str
    stderr_lines: tuple[str, ...] = ()
    fell_back: bool = False


def _parse_new_plan(
    ctx: Context,
    plan: list[str] | None,
    step: list[str] | None,
    outer_plan: list[str] | None,
    subplan: list[str] | None,
) -> tuple[list[dict[str, Any]] | None, bool, list[dict[str, Any]] | None]:
    has_shared = plan is not None or step is not None
    has_explicit = outer_plan is not None or subplan is not None
    if has_shared and has_explicit:
        raise Refused(ctx.config.tr(
            "do not mix --plan/--step with --outer-plan/--subplan",
            "不要把 --plan/--step 和 --outer-plan/--subplan 混用",
        ))
    outer_steps, outer_explicit, sub_steps = None, False, None
    if outer_plan is not None:
        outer_steps, outer_explicit = parse_plan_steps(outer_plan, None, outer=True)
    if subplan is not None:
        sub_steps, _ = parse_plan_steps(subplan, None, outer=False)
    if has_shared:
        outer_steps, outer_explicit = parse_plan_steps(plan, step, outer=True)
    return outer_steps, outer_explicit, sub_steps


class Workers:
    """Layer 3 service owning worker dispatch, messaging, wait, escalation, reattach, adopt, retab, and retirement."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ledger = Ledger(ctx)
        self._projects = ProjectRegistry(ctx)
        self._pool_lock: Any = None

    @property
    def _caller(self) -> Caller:
        return self.ctx.caller if self.ctx.caller is not None else Caller(self.ctx)

    def _deliver_later(self, repo: str | Path | None) -> None:
        if not repo:
            return
        if getattr(self.ctx, "_legacy", False):
            deliver_later(str(repo))
        elif self._projects.app_pm(repo):
            self.ctx.procs.spawn_pm(
                ["deliver", str(repo)],
                env=self.ctx.procs.clean_session_env(),
                cwd=self.ctx.home.root,
            )

    def _round_starts(self, raw_task: dict[str, Any], term: str, *, handed: bool = True, turn: int | None = None) -> None:
        if handed and turn is None:
            turn = (self.ctx.hc.get_raw(term) or {}).get("turn") or 0
        raw_task["round"] = {"terminal": term, "at": self.ctx.clock.now(), "turn": turn if handed else None}

    def _round_handed(self, task_id: str, term: str, turn: int | None = None) -> None:
        if turn is None:
            turn = (self.ctx.hc.get_raw(term) or {}).get("turn") or 0
        self._ledger.change(
            task_id,
            lambda cur, _ch: (self._round_starts(cur.raw, term, turn=turn), cur.raw)[1],
        )

    def _round_sent(self, task_id: str, term: str, sent: bool, seen: dict[str, Any]) -> bool:
        self._round_handed(task_id, term, seen.get("turn") if sent else None)
        return sent

    # --- Codex pool & brief & session & placement helpers (shared with Helpers 4b and Reviews/Landing 5) ---

    def codex_pool(self, repo: str | Path | None = None) -> list[dict[str, Any]]:
        return codex_pool_for(self.ctx, repo)

    def codex_usage(self, repo: str | Path, pool: list[dict[str, Any]] | None = None) -> dict[str, int] | None:
        return codex_usage_for(self.ctx, repo, pool)

    def deep_confirmed(self, repo: str | Path) -> bool:
        return deep_confirmed_for(self.ctx, repo)

    def apply_codex_pool(
        self,
        spec: Any,
        repo: str | Path,
        role: str = "worker",
        *,
        hold: bool = True,
    ) -> tuple[Any, str]:
        """Pick codex profile for `spec` and hold an instance-scoped pool lock when `hold=True`.

        Returns `(spec, stderr_warning)`. Call `pool_started(spec, repo)` after starting the worker.
        """
        spec, warning, lock_fh = apply_codex_pool_for(
            self.ctx, spec, repo, role=role, hold=hold,
        )
        if lock_fh is not None:
            self._pool_lock = lock_fh
        return spec, warning

    def pool_started(self, spec: Any, repo: str | Path, *, tries: int = 10) -> None:
        """Release the instance-scoped codex pool lock (or legacy lock when running under `legacy_context`)."""
        if self._pool_lock is not None:
            fh = self._pool_lock
            self._pool_lock = None
            release_pool_lock(self.ctx, fh, spec, repo, tries=tries)
        elif getattr(self.ctx, "_legacy", False):
            _codex_pool_mod.pool_started(spec, repo, tries=tries)

    def codex_fast(self, term: str, spec: Any, *, tries: int = 20) -> str:
        return codex_fast_for(self.ctx, term, spec, tries=tries)

    def worker_argv(
        self,
        spec: Any,
        reads: Iterable[str | Path] = (),
        repo: str | Path | None = None,
        extra: Sequence[str] = (),
        wrap: bool = False,
        memory: bool = True,
        writes: Iterable[str | Path] = (),
    ) -> list[str]:
        return worker_argv_for(self.ctx, spec, reads=reads, repo=repo, extra=extra, wrap=wrap, memory=memory, writes=writes)

    def worker_placement(self) -> list[str]:
        return worker_placement_for(self.ctx)

    def review_placement(self, task: Any, fallback_pane: str = "") -> list[str]:
        return review_placement_for(self.ctx, task, fallback_pane=fallback_pane)

    def keep_sent(self, task_id: str, brief: str) -> Path:
        return keep_sent_for(self.ctx, task_id, brief)

    def report_section(self, task_id: str) -> str:
        return report_section_for(self.ctx, task_id)

    def sent_repo(self, task_id: str) -> str | None:
        return sent_repo_for(self.ctx, task_id)

    def collect_research(self, task: Any, worktree: str | Path | None = None, *, report_saved: bool = False) -> Any:
        return collect_research_for(self.ctx, task, worktree=worktree, report_saved=report_saved)

    def retire_dirty(self, worktree: str | Path, ignore_untracked: Iterable[str] = ()) -> int | None:
        return retire_dirty_for(self.ctx, worktree, ignore_untracked=ignore_untracked)

    def live_worker(self, task: Any) -> str:
        return live_worker_for(self.ctx, task)

    def is_pane_live(self, pane: str) -> bool:
        return is_pane_live_for(self.ctx, pane)

    def end_terminal(self, term: str, *, why: str = "", task_id: str = "") -> bool:
        return end_terminal_for(self.ctx, term, why=why, task_id=task_id)

    def end_worker(self, task: Any, *, why: str = "") -> str:
        return end_worker_for(self.ctx, task, why=why)

    def close_review(self, review: Any, text: str) -> list[str]:
        return close_review_for(self.ctx, review, text)

    def retire_review(self, task: Any, text: str | None = None) -> list[str]:
        return retire_review_for(self.ctx, task, text=text)

    def active_review_of(self, task_id: str, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        return active_review_of_for(self.ctx, task_id, tasks=tasks)

    def close_worker(self, task: Any, *, forced: bool = False) -> str:
        return close_worker_for(self.ctx, task, forced=forced)

    def close_reported(self, task: Any) -> str:
        return close_reported_for(self.ctx, task)

    def find_session(self, task: Any, old_cwd: str = "") -> dict[str, Any] | None:
        return find_session_for(self.ctx, task, old_cwd=old_cwd)

    def remember_session(self, task: Any) -> None:
        remember_session_for(self.ctx, task)

    def remember_pm_session(self, rec: dict[str, Any], transcript: str = "", session_id: str = "") -> None:
        remember_pm_session_for(self.ctx, rec, transcript=transcript, session_id=session_id)

    def remember_worker_session(self, transcript: str = "", session_id: str = "", cwd: str = "") -> None:
        remember_worker_session_for(self.ctx, transcript=transcript, session_id=session_id, cwd=cwd)

    def pm_session_info(self, rec: dict[str, Any]) -> dict[str, Any] | None:
        return pm_session_info_for(self.ctx, rec)

    def task_session_info(self, task: Any, sessions: Any = None, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        return task_session_info_for(self.ctx, task, sessions=sessions, tasks=tasks)

    def waited_tasks(self, tasks: list[dict[str, Any]], rec: dict[str, Any]) -> list[dict[str, Any]]:
        return waited_tasks_for(self.ctx, tasks, rec)

    def offline_now(self, task: Any) -> bool:
        return offline_now_for(self.ctx, task)

    def reattach_plan(self, task: Any, old_cwd: str = "") -> dict[str, Any]:
        return reattach_plan_for(self.ctx, task, old_cwd=old_cwd)

    def start_beside_pm(self, task: Any, plan: dict[str, Any], name: str) -> tuple[str, str]:
        return start_beside_pm_for(self.ctx, task, plan, name)

    # --- Dry-run plan builder (shared by dispatch, escalate, review) ---

    def build_dry_run_plan(
        self,
        spec: Any,
        repo: str | Path,
        what: str,
        task_id: str | None,
        cwd: str | Path,
        tab: str,
        *,
        parent: str = "",
        reads: Iterable[str | Path] = (),
        extra: Sequence[str] = (),
        asks: bool = False,
        outer_steps: list[dict[str, Any]] | None = None,
        no_review: bool = False,
    ) -> dict[str, Any]:
        argv = self.worker_argv(spec, reads, repo, extra, wrap=self.ctx.pane.startswith("hc:"))
        pool = self.codex_pool(repo)
        plan: dict[str, Any] = {
            "what": what,
            "task": task_id or self.ctx.config.tr("(new)", "（新建）"),
            "profile": getattr(spec, "profile", "") or None,
            "kind": spec.kind,
            "model": spec.model,
            "effort": spec.effort,
            "codex_profile": getattr(spec, "provider", "") or None,
            "pool": getattr(spec, "pool_said", ""),
            "usage": (self.codex_usage(repo, pool) or {}) if pool else {},
            "cwd": str(cwd),
            "name": getattr(spec, "name", ""),
            "tab": tab,
            "parent": parent or "",
            "fast": any(p["fast"] for p in pool if p["name"] == getattr(spec, "provider", "")),
            "asks_user_first": asks,
            "argv": argv,
        }
        if outer_steps:
            plan["plan"] = outer_steps
        if no_review:
            plan["no_review"] = True
        return plan

    # --- Internal task creation (replaces ledger.cmd_new(Namespace(...))) ---

    def _create_dispatched_task(
        self,
        *,
        repo: str,
        title: str,
        status: str,
        base: str | None,
        slug: str,
        branch: str | None,
        brief_path: str,
        note_text: str,
        parent: str | None,
        outer_steps: list[dict[str, Any]] | None,
        outer_explicit: bool,
        sub_steps: list[dict[str, Any]] | None,
        no_review: bool,
        workspace: str | None,
        pane: str | None,
        agent: str | None = None,
        worktree: str | None = None,
        kind: str | None = None,
        options: list[str] | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = Path(repo).name
        task: dict[str, Any] = {
            "id": self._ledger.new_id(project, slug or branch or title),
            "title": title,
            "project": project,
            "repo": repo,
            "status": status,
            "base": base or self.ctx.git.base_branch(repo),
            "owner": "pm",
            "workspace": self.ctx.workspace if workspace is None else workspace,
            "pane": self.ctx.pane if pane is None else pane,
            "created": self.ctx.clock.now(),
        }
        for key, val in (("agent", agent), ("branch", branch), ("worktree", worktree), ("brief", brief_path), ("kind", kind)):
            if val:
                task[key] = val
        if parent:
            task["parent"] = parent_of(task["id"], parent, repo=repo, ledger=self._ledger, home=self.ctx.home)
        if outer_steps:
            task["plan"] = [dict(s) for s in outer_steps]
        if sub_steps:
            task["subplan"] = [dict(s) for s in sub_steps]
        if no_review:
            task["no_review"] = True
        sync_plan_for_status(
            task, task["status"],
            explicit_outer=outer_steps is not None,
            explicit_outer_states=outer_explicit,
        )
        self.remember_session(task)
        asked: dict[str, Any] = {"options": options} if options else {}
        task.update(asked)
        if extra_fields:
            task.update(extra_fields)
        task["number"] = self.ctx.store.allocate_task_number(
            self.ctx.store._task_slug(task),
            timeout=30.0,
        )
        told = wake_fields_for(task, task["status"], False, self._caller, bool(self._projects.app_pm(task.get("repo"))))
        created = self._ledger.create(task, note_text=note_text, note_extra={**asked, **told})
        if told.get("wake"):
            self._deliver_later(task["repo"])
        return created.raw

    # --- Dispatch ---

    def _register_worker(
        self,
        req: DispatchRequest,
        spec: WorkerSpec,
        repo: str,
        held: dict[str, Any] | None,
        *,
        outer_steps: list[dict[str, Any]] | None,
        outer_explicit: bool,
        sub_steps: list[dict[str, Any]] | None,
        workspace: str,
        pane: str,
        worktree: str,
    ) -> dict[str, Any]:
        worker_info = worker_record(spec)
        brief_resolved = str(Path(req.brief or "").resolve())
        if held:
            base_fallback = self.ctx.git.base_branch(repo) if not (req.base or held.get("base")) else None

            def _take_up(cur: Task | None, ch: Change) -> dict[str, Any]:
                assert cur is not None
                task = cur.raw
                clear_task_session_for(self.ctx, task)
                for f in (*QUESTION_FIELDS, "held", "held_in", "held_here", "closed", "deps_notified"):
                    task.pop(f, None)
                was_blocked = task.get("status") == "blocked" and self._caller.blocked_by_worker(task)
                task.update(
                    status="in_progress",
                    title=req.title,
                    agent=spec.name,
                    brief=brief_resolved,
                    base=req.base or task.get("base") or base_fallback or self.ctx.git.base_branch(repo),
                    kind=spec.kind,
                    workspace=workspace,
                    pane=pane,
                    worktree=worktree,
                )
                if req.parent:
                    task["parent"] = req.parent
                if req.branch:
                    task["branch"] = req.branch
                if outer_steps is not None:
                    if outer_steps:
                        task["plan"] = [dict(s) for s in outer_steps]
                    else:
                        task.pop("plan", None)
                if req.no_review:
                    task["no_review"] = True
                sync_plan_for_status(
                    task, "in_progress",
                    explicit_outer=outer_steps is not None,
                    explicit_outer_states=outer_explicit,
                )
                ch.note_on(task, dispatch_note_for(self.ctx, spec), **({"handled_by": "pm"} if was_blocked else {}))
                task["worker"] = worker_info
                task["worker_pane"] = pane
                task["dispatched"] = True
                task.setdefault("escalations", [])
                task.setdefault("rounds", 0)
                return task

            updated = self._ledger.change(held["id"], _take_up)
            assert updated is not None
            if updated.raw.get("parent"):
                self._ledger.clear_rollup_notified(updated.raw["parent"])
            return updated.raw

        return self._create_dispatched_task(
            repo=repo,
            title=req.title or "",
            status="in_progress",
            base=req.base,
            slug=req.label or "",
            branch=req.branch,
            brief_path=brief_resolved,
            note_text=dispatch_note_for(self.ctx, spec),
            parent=req.parent,
            outer_steps=outer_steps,
            outer_explicit=outer_explicit,
            sub_steps=sub_steps,
            no_review=req.no_review,
            workspace=workspace,
            pane=pane,
            agent=spec.name,
            worktree=worktree,
            kind=spec.kind,
            extra_fields={
                "worker": worker_info,
                "worker_pane": pane,
                "dispatched": True,
                "escalations": [],
                "rounds": 0,
            },
        )

    def _ask_first(
        self,
        req: DispatchRequest,
        spec: WorkerSpec,
        repo: str,
        held: dict[str, Any] | None,
        *,
        outer_steps: list[dict[str, Any]] | None,
        outer_explicit: bool,
        sub_steps: list[dict[str, Any]] | None,
        stderr_lines: list[str],
    ) -> DispatchResult:
        model = " ".join(x for x in (spec.kind, spec.model, spec.effort) if x)
        what = self.ctx.config.tr(f"profile {spec.profile} ({model})", f"{spec.profile} 档（{model}）") if spec.profile else model
        again = self.ctx.config.tr(
            "Once the user agrees, run the same dispatch with --confirmed; for hard, with --profile hard.",
            "用户同意后，加 --confirmed 再运行同一条 dispatch；改用 hard 就把 --profile 换成 hard 再运行。",
        ) + " " + ask_rule_for(self.ctx)
        if held and held.get("held") == "ask":
            msg = self.ctx.config.tr(
                f"{held['id']}: still waiting for the user's answer on {what}. {again}",
                f"{held['id']}：还在等用户回答是否用 {what}。{again}",
            )
            return DispatchResult(task_id=held["id"], lines=(msg,), stderr_lines=tuple(stderr_lines), asked=True)
        asked = self.ctx.config.tr(
            f"This task would run on {what}; the user decides before it starts. Agree?",
            f"这个任务要用 {what}，派发前先问你：同意吗？",
        )
        options = [
            self.ctx.config.tr(f"Agree: {what}", f"同意，用 {what}"),
            self.ctx.config.tr("Use hard instead", "改用 hard"),
        ]
        lines: list[str] = []
        if held:
            def _ask_held(cur: Task | None, ch: Change) -> dict[str, Any]:
                assert cur is not None
                task = cur.raw
                for f in QUESTION_FIELDS:
                    task.pop(f, None)
                task.update(options=options, status="blocked", held="ask")
                if req.here:
                    task["held_here"] = True
                if outer_steps is not None:
                    if outer_steps:
                        task["plan"] = [dict(s) for s in outer_steps]
                    else:
                        task.pop("plan", None)
                if req.no_review:
                    task["no_review"] = True
                ch.note_on(task, asked, options=options)
                return task

            updated = self._ledger.change(held["id"], _ask_held)
            assert updated is not None
            task_id = updated.raw["id"]
        else:
            extra = {"held": "ask", **({"held_here": True} if req.here else {})}
            created = self._create_dispatched_task(
                repo=repo,
                title=req.title or "",
                status="blocked",
                base=req.base,
                slug=req.label or "",
                branch=req.branch,
                brief_path=str(Path(req.brief or "").resolve()),
                note_text=asked,
                parent=req.parent,
                outer_steps=outer_steps,
                outer_explicit=outer_explicit,
                sub_steps=sub_steps,
                no_review=req.no_review,
                workspace=None,
                pane=None,
                options=options,
                extra_fields=extra,
            )
            task_id = created["id"]
            lines.append(task_id)
        lines.append(self.ctx.config.tr(
            f"{task_id}: blocked, no worker started: {what} needs the user's yes. {again}",
            f"{task_id}：已登记为 blocked，没有起 worker：{what} 要先等用户同意。{again}",
        ))
        return DispatchResult(task_id=task_id, lines=tuple(lines), stderr_lines=tuple(stderr_lines), asked=True)

    def _dispatch_hc(
        self,
        req: DispatchRequest,
        spec: WorkerSpec,
        repo: str,
        brief: str,
        held: dict[str, Any] | None,
        *,
        outer_steps: list[dict[str, Any]] | None,
        outer_explicit: bool,
        sub_steps: list[dict[str, Any]] | None,
        stderr_lines: list[str],
    ) -> DispatchResult:
        base = req.base or self.ctx.git.base_branch(repo)
        if req.here:
            path = Path(req.path).expanduser().resolve() if req.path else Path(repo)
            if not path.is_dir():
                raise Refused(f"{path} is not a directory")
        else:
            assert req.branch
            path = Path(req.path).expanduser().resolve() if req.path else self.ctx.git.worktree_home(repo) / req.branch.replace("/", "-")
        if not req.here and not (held and held.get("worktree") == str(path) and path.is_dir()):
            if path.exists():
                raise Refused(f"{path} already exists")
            path.parent.mkdir(parents=True, exist_ok=True)
            assert req.branch
            if not self.ctx.git.worktree_add(repo, path, req.branch, base):
                raise Refused(f"git worktree add {path} -b {req.branch} {base} failed")
            if req.prep:
                res = self.ctx.procs.run(
                    ["zsh", "-c", req.prep],
                    cwd=str(path),
                    env={**dict(self.ctx.env), "MAIN": repo},
                    capture_output=False,
                )
                if res.returncode != 0:
                    raise Refused(f"prep command failed with exit code {res.returncode}")
        reads = self.ctx.agents.outside_reads(repo, req.brief or "")
        made = self.ctx.hc.start_terminal(
            spec.name, path, self.worker_argv(spec, reads, repo, wrap=True), self.worker_placement()
        )
        self.pool_started(spec, repo)
        if not made:
            raise Refused(f"hc run failed; {path} is ready, start the worker by hand")
        task = self._register_worker(
            req, spec, repo, held,
            outer_steps=outer_steps, outer_explicit=outer_explicit, sub_steps=sub_steps,
            workspace="", pane=f"hc:{made}", worktree="" if req.here else str(path),
        )
        task_id = task["id"]
        lines: list[str] = [task_id]
        bug = req.bug or ""
        short = tab_short(req.tab or req.title or "", bug)
        tab = tab_title(short, bug, made, cfg=self.ctx.config) if self.ctx.hc.new_tabs(caller_pane=self.ctx.pane) else ""

        def _set_hc_fields(cur: Task | None, _ch: Change) -> dict[str, Any]:
            assert cur is not None
            r = cur.raw
            r["tab"] = short
            if bug:
                r["bug"] = bug
            if req.here:
                r["in_place"] = str(path)
            if tab:
                r["agent"] = tab
            self._round_starts(r, made, handed=False)
            return r

        self._ledger.change(task_id, _set_hc_fields)
        named = self.ctx.hc.worker_tab(made, task_id, tab, parent=req.parent or "", caller_pane=self.ctx.pane)
        fast = self.codex_fast(made, spec)
        said = "; ".join(
            x for x in ((f"tab={tab}" + ("" if named else not_renamed(cfg=self.ctx.config))) if tab else "", fast) if x
        )
        if said:
            self._ledger.change(task_id, lambda cur, ch: (ch.note_on(cur.raw, said), cur.raw)[1])
        if spec.pool_said:
            lines.append(spec.pool_said)
        sent = self.keep_sent(task_id, brief)
        if req.async_:
            self.send_ready_later(
                made, sent, kind=spec.kind, trust=str(path),
                strict=spec.kind in ("claude", "codex"),
                stop_on_exit=bool(spec.advisor), task_id=task_id, repo=repo,
            )
            lines.append(
                f"pane=hc:{made} " + (f"cwd={path}" if req.here else f"worktree={path}")
                + (f" tab={tab}" if tab else "") + (f" ({fast})" if fast else "") + " (async)"
            )
            self._deliver_later(repo)
            return DispatchResult(
                task_id=task_id, pane=f"hc:{made}", worktree="" if req.here else str(path),
                lines=tuple(lines), stderr_lines=tuple(stderr_lines),
            )
        seen: dict[str, Any] = {}
        handed = self.send_when_ready(
            made, sent.read_text(), tries=30, pause=2,
            strict=spec.kind in ("claude", "codex"),
            trust=path, stop_on_exit=bool(spec.advisor), kind=spec.kind, seen=seen,
        )
        self._round_sent(task_id, made, handed, seen)
        if not handed:
            seen_text = self.ctx.hc.screen_line(made, width=300)
            if spec.advisor and self.ctx.hc.worker_state(made) in ("exited", "removed"):
                self.end_terminal(made, why="dispatch", task_id=task_id)
                hold_exited_for(self.ctx, task_id, spec, seen_text, emitted_lines=lines)
            msg = self.ctx.config.tr(f"brief not sent; the worker's screen: {seen_text}", f"任务书没送达；worker 屏幕上是：{seen_text}")
            self._ledger.change(task_id, lambda cur, ch: (ch.note_on(cur.raw, msg), cur.raw)[1])
            raise Refused(
                f"the brief was not sent: the worker in hc:{made} is not ready. Its screen: {seen_text}\n"
                f"Read it (hc read {made}); once it is ready, send the brief by hand: "
                f"hc send {made} {file_text(sent)}",
                payload={"emitted_lines": lines},
            )
        lines.append(
            f"pane=hc:{made} " + (f"cwd={path}" if req.here else f"worktree={path}")
            + (f" tab={tab}" if tab else "") + (f" ({fast})" if fast else "")
        )
        self._deliver_later(repo)
        return DispatchResult(
            task_id=task_id, pane=f"hc:{made}", worktree="" if req.here else str(path),
            lines=tuple(lines), stderr_lines=tuple(stderr_lines),
        )

    def dispatch(self, req: DispatchRequest) -> DispatchResult:
        """Dispatch a worker (hc desktop or herdr TUI) for a new or existing open task."""
        repo = self.ctx.git.project_root(req.repo) if req.here else self.ctx.git.main_root(req.repo)
        if not repo:
            raise Refused(f"{req.repo} is not a directory" if req.here else f"{req.repo} is not in a git repository")
        outer_steps, outer_explicit, sub_steps = _parse_new_plan(self.ctx, req.plan, req.step, req.outer_plan, req.subplan)
        stderr_lines: list[str] = []
        given = self._ledger.load(req.task, repo=repo).raw if req.task else None
        if given:
            req.task = given["id"]
            if given.get("review_of") or given["status"] in CLOSED:
                raise Refused(self.ctx.config.tr(
                    f"{req.task} is {given['status']}" + (" (a review thread)" if given.get("review_of") else "")
                    + ": dispatch takes up an open task",
                    f"{req.task} 状态是 {given['status']}"
                    + ("（审查线程）" if given.get("review_of") else "") + "：dispatch 只接手未关闭的任务",
                ))
            if given.get("repo") != repo:
                raise Refused(self.ctx.config.tr(
                    f"{req.task} belongs to {given.get('repo') or 'another project'}, not {repo}: dispatch it from "
                    f"that project (--repo {given.get('repo')})",
                    f"{req.task} 属于 {given.get('repo') or '别的项目'}，不是 {repo}：到那个项目里派（--repo {given.get('repo')}）",
                ))
            busy = self.live_worker(given)
            if busy:
                raise Refused(self.ctx.config.tr(
                    f"{req.task} already has a worker running in {busy}: send it the work (hc send), or end it "
                    "first; no second worker was started",
                    f"{req.task} 已经有 worker 在 {busy} 里跑着：把活发给它（hc send），或者先结束它；没有再起第二个",
                ))
            req.title = req.title or given.get("title")
            req.parent = req.parent or given.get("parent")
            req.branch = req.branch or (given.get("branch") if not req.here else None)
            if not req.brief and given.get("brief"):
                req.brief = given["brief"]
            if given.get("depends_on") and not req.dry_run:
                every = self._ledger.raw_tasks()
                by_id = {t["id"]: t for t in every if isinstance(t, dict) and t.get("id")}
                dep_info = evaluate_depends_on(given, by_id)
                if not dep_info["all_met"]:
                    dep_summary = format_dep_summary(dep_info, tr_fn=self.ctx.config.tr)
                    stderr_lines.append(self.ctx.config.tr(
                        f"warning: {given['id']} still has unmet dependencies ({dep_summary})",
                        f"警告：{given['id']} 仍有未满足的前置依赖（{dep_summary}）",
                    ))
        if not req.brief:
            raise Refused(self.ctx.config.tr(
                "dispatch needs --brief <file> (or a --task that already records one)",
                "dispatch 需要 --brief <文件>（或用 --task 接手已登记任务书的任务）",
            ))
        brief = Path(req.brief).read_text(encoding="utf-8")
        if not req.title:
            raise Refused(self.ctx.config.tr("dispatch needs a title, or --task <id>", "dispatch 要给标题，或用 --task <id> 接手已有任务"))
        if not req.here and not req.branch:
            raise Refused(self.ctx.config.tr(
                "dispatch needs --branch (a worktree of its own), or --here (the worker works in the project's checkout)",
                "dispatch 要给 --branch（新开工作树），或用 --here（在项目目录里干活）",
            ))
        if req.here and not self.ctx.pane.startswith("hc:") and not req.dry_run:
            raise Refused(self.ctx.config.tr("--here is for a PM in the desktop app (herdr-core)", "--here 只用于桌面版（herdr-core）里的 PM"))
        req.bug = bug_of(req.bug, req.tab, req.title, cfg=self.ctx.config) or (given or {}).get("bug") or ""
        req.label = req.label or slugify((given or {}).get("id") or req.title) or "worker"
        req.name = req.name or hc_name(req.label)
        req.parent = parent_of("", req.parent, repo=repo, ledger=self._ledger, home=self.ctx.home)
        spec = self.ctx.agents.resolve_worker(WorkerSpec(
            profile=req.profile or "",
            kind=req.kind or "",
            model=req.model or "",
            effort=req.effort or "",
            advisor=req.advisor or "",
            codex_profile=req.codex_profile or "",
            name=req.name,
            branch=req.branch or "",
            dry_run=req.dry_run,
        ))
        spec, pool_warn = self.apply_codex_pool(spec, repo, "worker", hold=not req.dry_run)
        try:
            if pool_warn:
                stderr_lines.append(pool_warn)
            held = given or held_task_for(self.ctx, repo, req.branch, req.title if req.here else None)
            spec.preapproved = asks_first(spec) and not req.confirmed and self.deep_confirmed(repo)
            asks = asks_first(spec) and not req.confirmed and not spec.preapproved
            if req.dry_run:
                assert req.here or req.branch
                cwd = req.path or repo if req.here else req.path or self.ctx.git.worktree_home(repo) / (req.branch or "").replace("/", "-")
                tab = (
                    tab_title(tab_short(req.tab or req.title), req.bug, dry=True, cfg=self.ctx.config)
                    if self.ctx.hc.new_tabs(caller_pane=self.ctx.pane) else ""
                )
                plan = self.build_dry_run_plan(
                    spec, repo, "dispatch", given and given["id"], cwd, tab,
                    parent=req.parent or "", reads=self.ctx.agents.outside_reads(repo, req.brief),
                    asks=asks, outer_steps=outer_steps, no_review=req.no_review,
                )
                return DispatchResult(dry_run_plan=plan, stderr_lines=tuple(stderr_lines))
            if asks:
                return self._ask_first(
                    req, spec, repo, held,
                    outer_steps=outer_steps, outer_explicit=outer_explicit, sub_steps=sub_steps,
                    stderr_lines=stderr_lines,
                )
            if self.ctx.pane.startswith("hc:"):
                return self._dispatch_hc(
                    req, spec, repo, brief, held,
                    outer_steps=outer_steps, outer_explicit=outer_explicit, sub_steps=sub_steps,
                    stderr_lines=stderr_lines,
                )
            # Herdr TUI dispatch
            place = (held or {}).get("held_in") or {}
            if place.get("pane") and held and Path(held.get("worktree") or "").is_dir():
                workspace, pane, path_str = place.get("workspace") or "", place["pane"], held["worktree"]
            else:
                wt_args: list[str] = [
                    "--cwd", repo, "--branch", req.branch or "",
                    "--base", req.base or self.ctx.git.base_branch(repo),
                    "--label", req.label, "--no-focus",
                ]
                if req.path:
                    wt_args += ["--path", req.path]
                created = self.ctx.tui.worktree_create(*wt_args)
                if not created:
                    raise Refused("herdr worktree create failed")
                flat = json.dumps(created)
                found = [re.search(rf'"{k}": "([^"]+)"', flat) for k in ("workspace_id", "pane_id", "path")]
                if not all(found):
                    raise Refused(f"unexpected worktree create result: {flat[:600]}")
                workspace, pane, path_str = (m.group(1) for m in found if m is not None)
                if req.prep:
                    res = self.ctx.procs.run(
                        ["zsh", "-c", req.prep],
                        cwd=path_str,
                        env={**dict(self.ctx.env), "MAIN": repo},
                        capture_output=False,
                    )
                    if res.returncode != 0:
                        raise Refused(f"prep command failed with exit code {res.returncode}")
            argv = self.worker_argv(spec, self.ctx.agents.outside_reads(repo, req.brief), repo)
            if not self.ctx.tui.agent_start(spec.name, kind=spec.kind, pane=pane, argv=argv[1:]):
                raise Refused(f"agent start failed in {pane}")
            self.pool_started(spec, repo)
        finally:
            self.pool_started(spec, repo, tries=0)
        task = self._register_worker(
            req, spec, repo, held,
            outer_steps=outer_steps, outer_explicit=outer_explicit, sub_steps=sub_steps,
            workspace=workspace, pane=pane, worktree=path_str,
        )
        task_id = task["id"]
        lines = [task_id]
        sent = self.keep_sent(task_id, brief)

        def _gone() -> bool:
            return bool(spec.advisor and tui_agent_gone_for(self.ctx, pane))

        if not self.ctx.tui.agent_prompt(spec.name, sent.read_text()):
            if _gone():
                hold_exited_for(
                    self.ctx, task_id, spec,
                    self.ctx.config.tr("(no agent in the pane)", "（窗格里已经没有 agent）"),
                    {"workspace": workspace, "pane": pane},
                    emitted_lines=lines,
                )
            raise Refused(
                f"prompt failed; the agent is running. Send the brief by hand: "
                f"herdr agent prompt {spec.name} {file_text(sent)}",
                payload={"emitted_lines": lines},
            )
        if not self.ctx.tui.agent_wait(spec.name, "--until", "working", "--timeout", "20000"):
            if _gone():
                hold_exited_for(
                    self.ctx, task_id, spec,
                    self.ctx.config.tr("(no agent in the pane)", "（窗格里已经没有 agent）"),
                    {"workspace": workspace, "pane": pane},
                    emitted_lines=lines,
                )
            stderr_lines.append(f"warning: {spec.name} did not start working; read its screen and resend the brief from {sent}")
        lines.append(f"workspace={workspace} pane={pane} worktree={path_str}")
        return DispatchResult(
            task_id=task_id, pane=pane, workspace=workspace, worktree=path_str,
            lines=tuple(lines), stderr_lines=tuple(stderr_lines),
        )

    # --- Messaging ---

    def send_when_ready(
        self,
        term: str,
        text: str,
        *,
        tries: int = 8,
        pause: float = 3,
        strict: bool = False,
        trust: str | Path | None = None,
        stop_on_exit: bool = False,
        kind: str = "",
        seen: dict[str, Any] | None = None,
    ) -> bool:
        return send_when_ready_for(
            self.ctx, term, text, tries=tries, pause=pause, strict=strict,
            trust=trust, stop_on_exit=stop_on_exit, kind=kind, seen=seen,
        )

    def send_async_later(
        self,
        term: str,
        message: str,
        *,
        task_id: str = "",
        repo: str = "",
        pre_turn: int | None = None,
        timeout: int = 180,
    ) -> bool:
        return send_async_later_for(
            self.ctx, term, message, task_id=task_id, repo=repo, pre_turn=pre_turn, timeout=timeout,
        )

    def send_ready_later(
        self,
        term: str,
        message_file: str | Path,
        *,
        kind: str = "",
        trust: str = "",
        strict: bool = False,
        stop_on_exit: bool = False,
        task_id: str = "",
        repo: str = "",
        unlink: bool = False,
        helper_owner_kind: str = "",
        helper_owner_id: str = "",
        helper_slug: str = "",
        helper_name: str = "",
    ) -> bool:
        return send_ready_later_for(
            self.ctx, term, message_file, kind=kind, trust=trust, strict=strict,
            stop_on_exit=stop_on_exit, task_id=task_id, repo=repo, unlink=unlink,
            helper_owner_kind=helper_owner_kind, helper_owner_id=helper_owner_id,
            helper_slug=helper_slug, helper_name=helper_name,
        )

    def send_back(self, task: Any, text: str, *, wait: bool = False) -> SendBackResult:
        return send_back_for(self.ctx, task, text, wait=wait)

    def send(
        self,
        target: str,
        message_text: str | None = None,
        *,
        file_path: str | Path | None = None,
        task_id: str | None = None,
        repo: str = ".",
        timeout: int = 180,
        wait: bool = False,
    ) -> SendResult:
        """Send a message to a task's worker or an hc terminal asynchronously by default."""
        resolved = self._ledger.try_resolve_id(target)
        task: dict[str, Any] | None = None
        if resolved and self.ctx.home.task(resolved).is_file():
            task = self._ledger.load(resolved).raw
            term = hc_terminal_of(task)
            if not term or "/" in term:
                raise Refused(self.ctx.config.tr(
                    f"{task['id']} has no local herdr-core terminal",
                    f"{task['id']} 没有本机 herdr-core 终端",
                ))
        else:
            term = target[3:] if target.startswith("hc:") else target
            if task_id:
                task = self._ledger.load(task_id).raw
            else:
                pm_rec = self._caller.own_pm_record()
                if pm_rec:
                    pane_ref = f"hc:{term}"
                    matches = [
                        t for t in self._ledger.raw_tasks()
                        if t.get("status") in ACTIVE and t.get("pane") == pane_ref
                        and (not pm_rec.get("repo") or t.get("repo") == pm_rec.get("repo"))
                    ]
                    if matches:
                        matches.sort(key=lambda t: (t.get("status") == "blocked", str(t.get("updated") or "")), reverse=True)
                        task = matches[0]
        if file_path:
            body = Path(file_path).read_text(encoding="utf-8")
        elif message_text:
            body = message_text
        else:
            raise Refused(self.ctx.config.tr("send needs a message or --file <path>", "send 需要提供消息正文或 --file <路径>"))
        message = body if body.startswith("[from ") else f"[from {self.ctx.pane or 'pm.py'}] {body}"
        info = self.ctx.hc.get_raw(term, errors=True) or {}
        if info.get("state") != "live":
            why = (info.get("error") or {}).get("message") or info.get("state") or "gone"
            raise Refused(self.ctx.config.tr(f"hc:{term} is not live ({why})", f"hc:{term} 未在运行（{why}）"))
        if task and task.get("status") == "blocked" and self._caller.is_pm_caller(task) and self._caller.blocked_by_worker(task):
            flat = " ".join(body.split())
            snippet = flat[:120] + ("…" if len(flat) > 120 else "")
            pre_turn = info.get("turn") or 0

            def _unblock_on_send(cur: Task | None, ch: Change) -> dict[str, Any]:
                assert cur is not None
                r = cur.raw
                if r.get("status") != "blocked" or not self._caller.blocked_by_worker(r):
                    return r
                r["status"] = "in_progress"
                for f in (*QUESTION_FIELDS, "paused_from", "escalating", "adopting"):
                    r.pop(f, None)
                sync_plan_for_status(r, "in_progress", prev_status="blocked")
                self._round_starts(r, term, turn=pre_turn)
                label = self.ctx.config.tr("PM handled (sent to worker)", "PM 已处理（已发消息给 worker）")
                ch.note_on(
                    r,
                    f"status=in_progress; {label}: {snippet}" if snippet else f"status=in_progress; {label}",
                    handled_by="pm",
                )
                return r

            updated = self._ledger.change(task["id"], _unblock_on_send)
            assert updated is not None
            task = updated.raw
        resolved_repo = (task.get("repo") if task else None) or self.ctx.git.project_root(repo or ".") or ""
        if not wait:
            self.send_async_later(
                term, message,
                task_id=task["id"] if task else "",
                repo=resolved_repo,
                pre_turn=info.get("turn") or 0,
                timeout=timeout,
            )
            msg = self.ctx.config.tr(
                f"queued async send to hc:{term}" + (f" (task {task['id']})" if task else ""),
                f"已异步排队发送到 hc:{term}" + (f"（任务 {task['id']}）" if task else ""),
            )
            return SendResult(queued=True, terminal=term, task_id=task["id"] if task else "", message=msg)
        sent = self.ctx.hc.send(term, message, timeout=timeout, errors=True) or {}
        if sent.get("started") or ("started" in sent and not sent.get("error")):
            if task and (self.ctx.store.task(task["id"]) or {}).get("status") == "in_progress":
                self._round_handed(task["id"], term, info.get("turn") or 0)
            msg = self.ctx.config.tr(f"sent to hc:{term}", f"已发送到 hc:{term}")
            return SendResult(queued=False, terminal=term, task_id=task["id"] if task else "", message=msg)
        why = (sent.get("error") or {}).get("message") or (sent.get("error") or {}).get("kind") or "send failed"
        raise Refused(self.ctx.config.tr(f"failed to send to hc:{term}: {why}", f"发送到 hc:{term} 失败：{why}"))

    def deliver_send(
        self,
        term: str,
        file_path: str | Path,
        *,
        unlink: bool = False,
        task_id: str = "",
        repo: str = "",
        pre_turn: int | None = None,
        timeout: int = 180,
    ) -> None:
        """Internal background worker for async `hc send`: delivers message, updates round_handed, wakes PM on failure."""
        path = Path(file_path)
        try:
            message = path.read_text(encoding="utf-8")
        except OSError:
            return
        finally:
            if unlink:
                path.unlink(missing_ok=True)
        info = self.ctx.hc.get_raw(term, errors=True) or {}
        if info.get("state") == "live":
            turn = info.get("turn") if info.get("turn") is not None else (pre_turn or 0)
            sent = self.ctx.hc.send(term, message, timeout=timeout, errors=True) or {}
            if sent.get("started") or ("started" in sent and not sent.get("error")):
                if task_id:
                    with contextlib.suppress(Exception, SystemExit):
                        if (self.ctx.store.task(task_id) or {}).get("status") == "in_progress":
                            self._round_handed(task_id, term, turn)
                return
        else:
            sent = {}
        why = (
            (sent.get("error") or {}).get("message")
            or (sent.get("error") or {}).get("kind")
            or f"hc:{term} is {info.get('state') or 'gone'}"
        )
        resolved_repo = repo or ""
        if task_id and (self.ctx.store.task(task_id) or {}):
            t = self.ctx.store.task(task_id) or {}
            resolved_repo = resolved_repo or t.get("repo") or ""
            wake = bool(resolved_repo and self._projects.app_pm(resolved_repo))
            msg = self.ctx.config.tr(
                f"async send to hc:{term} failed ({why}); check or triage with `pm.py triage {task_id}`",
                f"异步发送到 hc:{term} 失败（{why}）；可用 `pm.py triage {task_id}` 交给 helper 排查",
            )
            self._ledger.change(
                task_id,
                lambda cur, ch: (ch.note_on(cur.raw, msg, source="harness", **({"wake": True} if wake else {})), cur.raw)[1],
            )
            if wake:
                self._deliver_later(resolved_repo)
        elif resolved_repo:
            wake = bool(self._projects.app_pm(resolved_repo))
            msg = self.ctx.config.tr(f"async send to hc:{term} failed ({why})", f"异步发送到 hc:{term} 失败（{why}）")
            Conversation(self.ctx, resolved_repo).record(
                "event", by=f"hc:{term}", source="harness", text=msg, **({"wake": True} if wake else {}),
            )
            if wake:
                self._deliver_later(resolved_repo)

    def deliver_ready_for_task(
        self,
        term: str,
        text: str,
        *,
        kind: str = "",
        trust: str = "",
        strict: bool = False,
        stop_on_exit: bool = False,
        task_id: str = "",
        repo: str = "",
    ) -> bool:
        """Internal background worker for async `send_when_ready` on a task worker."""
        seen: dict[str, Any] = {}
        handed = self.send_when_ready(
            term, text, tries=30, pause=2, strict=strict,
            trust=trust or None, stop_on_exit=stop_on_exit, kind=kind, seen=seen,
        )
        if task_id:
            self._round_sent(task_id, term, handed, seen)
            if not handed:
                diag = classify_stuck_screen(self.ctx.hc.read(term))
                summary = diag["summary"] or self.ctx.hc.screen_line(term, width=200)
                t = self.ctx.store.task(task_id) or {}
                resolved_repo = repo or t.get("repo") or ""
                wake = bool(resolved_repo and self._projects.app_pm(resolved_repo))
                msg = self.ctx.config.tr(
                    f"brief not delivered to hc:{term} ({diag['kind']}): {summary}; "
                    f"delegate unblocking with `pm.py triage {task_id}`",
                    f"任务书未送达 hc:{term}（{diag['kind']}）：{summary}；"
                    f"可用 `pm.py triage {task_id}` 交给 helper 处理",
                )
                self._ledger.change(
                    task_id,
                    lambda cur, ch: (ch.note_on(cur.raw, msg, source="harness", **({"wake": True} if wake else {})), cur.raw)[1],
                )
                if wake:
                    self._deliver_later(resolved_repo)
            elif repo:
                self._deliver_later(repo)
        return handed

    # --- Wait ---

    def wait(self, task_id: str, *, timeout: float = 3600) -> WaitResult:
        """Wait for a worker's report in the ledger. Raises `WaitOutcome` with code 2 (timeout), 3 (stopped), or 4 (app PM)."""
        task = self._ledger.load(task_id).raw
        tid = task["id"]
        rec = self._projects.app_pm(task.get("repo")) if task.get("repo") else None
        if self.ctx.pane and rec and rec.get("pane") == self.ctx.pane:
            raise WaitOutcome(
                self.ctx.config.tr(
                    f"{tid}: not waited for. In the desktop app the worker's report, or word that it stopped, is "
                    "delivered to you as a message of its own once you are idle; there is nothing to wait for.",
                    f"{tid}：不用等。在桌面 app 里，worker 的汇报（或它停了的消息）会在你空闲时作为一条消息送到；没有要等的。",
                ),
                code=4,
                stream="stdout",
            )
        with waiting_on_for(self.ctx, tid):
            return wait_for_report_for(self.ctx, tid, timeout=timeout)

    # --- Escalate ---

    def escalate(self, req: EscalateRequest) -> EscalateResult:
        """Run a task again on a stronger profile in the same worktree and branch."""
        task = self._ledger.load(req.task_id).raw
        tid = task["id"]
        if task.get("review_of"):
            raise Refused(self.ctx.config.tr(f"{tid} is a review thread: escalate the task it reviews", f"{tid} 是审查线程：升级它审查的那个任务"))
        if task["status"] not in ATTACHED:
            raise Refused(self.ctx.config.tr(
                f"{tid} is {task['status']}: only open work (in progress, review, blocked) is escalated",
                f"{tid} 的状态是 {task['status']}：只有进行中、待审、阻塞的任务能升级",
            ))
        worktree = task.get("worktree") or (self.ctx.git.checkout_of(task["repo"], task["branch"]) if task.get("branch") else None)
        if not task.get("branch") or not worktree or not Path(worktree).is_dir():
            raise Refused(self.ctx.config.tr(
                f"{tid} has no branch checked out in a worktree to carry on from",
                f"{tid} 没有检出在工作树里的分支，新 worker 没处接着做",
            ))
        current = (task.get("worker") or {}).get("profile") or "" if isinstance(task.get("worker"), dict) else ""
        steps = self.ctx.agents.ladder()
        target = req.profile or (steps[steps.index(current) + 1] if current in steps[:-1] else "")
        if not target and current and current == steps[-1] and steps[-1] != LADDER[-1]:
            raise Refused(self.ctx.config.tr(
                f"{tid} runs on {current}: without Fable (config.json \"fable\": false) that is the top profile, "
                "so nothing was escalated and no worker started",
                f"{tid} 现在是 {current}：没有 Fable（config.json 里 \"fable\": false），这已经是最高一档；没有升级，也没有起 worker",
            ))
        if not target:
            raise Refused(self.ctx.config.tr(
                f"{tid} runs on {current or 'no profile'}: there is no step up from it; name one with --profile ({', '.join(steps)})",
                f"{tid} 现在是 {current or '无档位'}：没有上一档可升；用 --profile 指定（{', '.join(steps)}）",
            ))
        spec = self.ctx.agents.resolve_worker(WorkerSpec(
            profile=target,
            advisor=req.advisor or "",
            codex_profile=req.codex_profile or "",
            dry_run=req.dry_run,
        ))
        stderr_lines: list[str] = []
        spec, pool_warn = self.apply_codex_pool(spec, task["repo"], "worker", hold=not req.dry_run)
        try:
            if pool_warn:
                stderr_lines.append(pool_warn)
            pending = task.get("escalating") or {}
            asked = task["status"] == "blocked" and pending.get("to") == target
            why = (req.why or "").strip() or (pending.get("why") or "" if asked else "")
            spec.preapproved = asks_first(spec) and not req.confirmed and self.deep_confirmed(task["repo"])
            asks = asks_first(spec) and not req.confirmed and not spec.preapproved
            old, old_agent = task.get("pane") or "", task.get("agent") or ""
            name = req.name or escalated_name(old_agent or tid, target)
            held_names = {old_agent, (self.ctx.hc.get_raw(old[3:]) or {}).get("name") if old.startswith("hc:") and not asks else ""}
            if name in held_names:
                name = f"{name[:30]}-2"
            bug = bug_of(req.bug, req.tab or "", cfg=self.ctx.config) or ("" if req.tab else task_bug(task, cfg=self.ctx.config))
            t_short = tab_short(req.tab or tab_short(task.get("tab") or task["title"], task_bug(task, cfg=self.ctx.config)), bug)
            want_tab = self.ctx.hc.new_tabs(caller_pane=self.ctx.pane)
            dry_tab = tab_title(t_short, bug, dry=True, cfg=self.ctx.config) if want_tab else ""
            if req.dry_run:
                plan = self.build_dry_run_plan(
                    spec, task["repo"], "escalate", tid, worktree, dry_tab,
                    parent=task.get("parent") or "",
                    reads=self.ctx.agents.outside_reads(task["repo"], task.get("brief") or ""),
                    asks=asks,
                )
                return EscalateResult(task_id=tid, dry_run_plan=plan, stderr_lines=tuple(stderr_lines))
            if asks:
                _, ask_msg = ask_escalation_for(self.ctx, task, spec, current, why)
                return EscalateResult(task_id=tid, lines=(ask_msg,), stderr_lines=tuple(stderr_lines), asked=True)
            ours = own_worker_for(self.ctx, task, old)
            mem = MemoryLayer(self.ctx, task.get("repo")).memory_part() if task.get("repo") else ""
            text = escalation_brief_for(self.ctx, task, spec, worktree, why) + mem
            sent_path = self.ctx.home.sent_dir / f"{tid}.escalated.md"
            sent_path.parent.mkdir(parents=True, exist_ok=True)
            sent_path.write_text(text)
            updated_sw = self._ledger.change(tid, lambda cur, _ch: {**cur.raw, "switching": self.ctx.clock.now()})
            assert updated_sw is not None
            task = updated_sw.raw
            try:
                interrupted = quiet_old_worker_for(self.ctx, task, old, ours, worktree)
            except (PmError, SystemExit):
                unmark_switching_for(self.ctx, tid)
                raise
            pool_fh = self._pool_lock
            self._pool_lock = None
        finally:
            self.pool_started(spec, task["repo"], tries=0)
        try:
            pane, workspace, unsent, start_warns, resolved_tab, fast_said, handed_turn = start_escalated_for(
                self.ctx, task, spec, name, worktree, text, why,
                tab_short_val=t_short, bug=bug, want_tab=want_tab, pool_lock=pool_fh,
            )
            stderr_lines.extend(start_warns)
        except (PmError, SystemExit) as stop:
            unmark_switching_for(self.ctx, tid)
            if not interrupted:
                raise
            said = self.ctx.config.tr(
                f"The previous worker {old} was interrupted for this escalation and is idle now: tell it to carry "
                "on, or escalate again.",
                f"前一个 worker {old} 为这次升级被中断了，现在空着：让它接着做，或者再升级一次。",
            )
            self._ledger.change(tid, lambda cur, ch: (ch.note_on(cur.raw, said), cur.raw)[1])
            base_msg = str(stop.code) if isinstance(stop, SystemExit) else str(stop)
            raise Refused(f"{base_msg}\n{said}")
        if pane.startswith("hc:") and handed_turn is None:
            handed_turn = (self.ctx.hc.get_raw(pane[3:]) or {}).get("turn") or 0
        w_rec = worker_record(spec)
        esc_note = (
            self.ctx.config.tr(
                f"escalated to {target} ({engine_label(spec)})" + (f": {why}" if why else ""),
                f"升级到 {target}（{engine_label(spec)}）" + (f"：{why}" if why else ""),
            )
            + fallback_said(spec, tr_fn=self.ctx.config.tr)
            + "".join(
                f"; {x}" for x in (spec.pool_said, fast_said, self.ctx.config.tr(*PREAPPROVED) if spec.preapproved else "") if x
            )
        )

        def _apply_escalation(cur: Task | None, ch: Change) -> dict[str, Any]:
            assert cur is not None
            r = cur.raw
            was_blocked = r.get("status") == "blocked" and self._caller.blocked_by_worker(r)
            clear_task_session_for(self.ctx, r)
            for f in (*QUESTION_FIELDS, "escalating", "switching", "closed", "auto_review", "auto_reviewed_commit"):
                r.pop(f, None)
            r.update(
                status="in_progress", pane=pane, workspace=workspace, kind=spec.kind, worker=w_rec,
                agent=resolved_tab if resolved_tab and pane.startswith("hc:") else name,
                worker_pane=pane, rounds=0,
            )
            sync_plan_for_status(r, "in_progress", prev_status="review")
            if pane.startswith("hc:"):
                self._round_starts(r, pane[3:], turn=handed_turn)
            r["tab"] = t_short
            if bug:
                r["bug"] = bug
            if not isinstance(r.get("escalations"), list):
                r["escalations"] = []
            r["escalations"].append({"from": current, "to": target, "why": why, "at": self.ctx.clock.now()})
            ch.note_on(r, esc_note, **({"handled_by": "pm"} if was_blocked else {}))
            return r

        updated = self._ledger.change(tid, _apply_escalation)
        assert updated is not None
        task = updated.raw
        self.retire_review(
            task,
            self.ctx.config.tr(f"closed: {tid} was escalated to {target}", f"{tid} 已升到 {target}，这轮审查收起"),
        )
        ended = bool(
            ours and old != pane and (
                self.end_terminal(old[3:], why="escalate", task_id=tid)
                if old.startswith("hc:")
                else self.ctx.tui.pane_close(old) is not None
            )
        )
        kept = self.ctx.config.tr(
            f"; {old} kept: not a worker terminal of this task",
            f"；{old} 没关：不是这个任务的 worker 终端",
        ) if old and old != pane and not ended else ""
        line = (
            self.ctx.config.tr(
                f"{tid}: escalated {current or '-'} -> {target}; worker {task['agent']} in {pane}",
                f"{tid}：已从 {current or '-'} 升到 {target}；worker {task['agent']} 在 {pane}",
            )
            + (self.ctx.config.tr(f"; ended {old}", f"；已结束 {old}") if ended else kept)
            + (self.ctx.config.tr(" (it was interrupted first)", "（先中断了它）") if interrupted else "")
        )
        self._deliver_later(task["repo"])
        unsent_error = ""
        if unsent:
            unsent_msg = self.ctx.config.tr(f"brief not sent; the worker's screen: {unsent}", f"任务书没送达；worker 屏幕上是：{unsent}")
            self._ledger.change(tid, lambda cur, ch: (ch.note_on(cur.raw, unsent_msg), cur.raw)[1])
            resend = (
                f"hc send {pane[3:]} {file_text(sent_path)}"
                if pane.startswith("hc:")
                else f"herdr agent prompt {name} {file_text(sent_path)}"
            )
            unsent_error = self.ctx.config.tr(
                f"the brief was not sent to {pane}. Its screen: {unsent}\nOnce it is ready, send it by hand: {resend}",
                f"任务书没送到 {pane}。屏幕上是：{unsent}\n等它就绪后手动发送：{resend}",
            )
        return EscalateResult(
            task_id=tid, pane=pane, lines=(line,), stderr_lines=tuple(stderr_lines), unsent_error=unsent_error,
        )

    # --- Reattach & Adopt ---

    def reattach(self, task_id: str) -> ReattachResult:
        """Bring back the agent of a task whose terminal is gone."""
        task = self._ledger.load(task_id).raw
        tid = task["id"]
        if task["status"] not in ATTACHED:
            raise Refused(self.ctx.config.tr(
                f"{tid} is {task['status']}: only open work (in progress, review, blocked) is reattached",
                f"{tid} 的状态是 {task['status']}：只有进行中、待审、阻塞的任务能接回",
            ))
        if not self.offline_now(task):
            raise Refused(self.ctx.config.tr(
                f"{tid} is not offline: its terminal {task.get('pane') or '(none)'} is still there (or cannot be checked)",
                f"{tid} 没有断开：它的终端 {task.get('pane') or '（无）'} 还在（或查不到）",
            ))
        lock = self.ctx.home.reattach / f"{tid}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        if stale_lock(lock):
            with contextlib.suppress(OSError):
                lock.unlink()
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise Refused(self.ctx.config.tr(f"{tid} is being reattached already", f"{tid} 正在接回"))
        os.write(fd, f"{os.getpid()} {int(self.ctx.clock.time())}\n".encode())
        os.close(fd)
        try:
            old = hc_terminal_of(task)
            old_cwd = ((self.ctx.hc.get_raw(old) or {}).get("cwd") or "") if old else ""
            plan = self.reattach_plan(task, old_cwd)
            name = task.get("agent") or tid
            pane, workspace = self.start_beside_pm(task, plan, name)
            if not pane:
                raise Refused(self.ctx.config.tr(
                    f"no terminal could be started for {tid}; nothing changed",
                    f"没能为 {tid} 开出终端；什么都没改",
                ))
            made = pane[3:] if pane.startswith("hc:") else ""
            tab = (
                tab_title(task.get("tab") or task["title"], task_bug(task, cfg=self.ctx.config), made, cfg=self.ctx.config)
                if made and self.ctx.hc.new_tabs(caller_pane=self.ctx.pane) else ""
            )
            named = bool(made and self.ctx.hc.worker_tab(made, tid, tab, parent=task.get("parent") or "", caller_pane=self.ctx.pane))

            def _apply_reattach(cur: Task | None, ch: Change) -> dict[str, Any]:
                assert cur is not None
                r = cur.raw
                previous = r.get("pane") or ""
                r.pop("closed", None)
                r["pane"], r["workspace"] = pane, workspace
                r["worker_pane"] = pane
                if tab:
                    r["agent"] = tab
                    ch.note_on(r, f"tab={tab}" + ("" if named else not_renamed(cfg=self.ctx.config)))
                if plan["how"] == "resume":
                    r["session"] = {"kind": plan["kind"], "id": plan["session"]}
                    ch.note_on(r, self.ctx.config.tr(
                        f"reattached: resumed {plan['kind']} session {plan['session']} in {pane} ({previous} was gone)",
                        f"接回：在 {pane} 恢复了 {plan['kind']} 会话 {plan['session']}（原终端 {previous} 已不在）",
                    ))
                else:
                    clear_task_session_for(self.ctx, r)
                    ch.note_on(r, self.ctx.config.tr(
                        f"reattached: no session found; started {plan['kind']} in {pane} with the title, brief and "
                        f"latest ledger entries ({previous} was gone)",
                        f"接回：没找到会话，在 {pane} 新开了 {plan['kind']}，交给它标题、任务书和最近的台账记录"
                        f"（原终端 {previous} 已不在）",
                    ))
                if made:
                    self._round_starts(r, made, handed=False)
                return r

            updated = self._ledger.change(tid, _apply_reattach)
            assert updated is not None
            seen: dict[str, Any] = {}
            sent = not made or self._round_sent(
                tid, made,
                self.send_when_ready(
                    made, plan["prompt"], tries=30, pause=2,
                    strict=plan["kind"] in ("claude", "codex"),
                    trust=plan["cwd"], kind=plan["kind"], seen=seen,
                ),
                seen,
            )
            if not sent:
                seen_line = self.ctx.hc.screen_line(made)
                msg = self.ctx.config.tr(f"reattach prompt not sent; the screen: {seen_line}", f"接回的提示没送达；屏幕上是：{seen_line}")
                self._ledger.change(tid, lambda cur, ch: (ch.note_on(cur.raw, msg), cur.raw)[1])
                raise Refused(self.ctx.config.tr(
                    f"{pane} is started but the prompt was not sent. Its screen: {seen_line}",
                    f"{pane} 已经开了，但提示没送达。屏幕上是：{seen_line}",
                ))
            line = f"{plan['how']} {plan['kind']} pane={pane}" + (f" session={plan['session']}" if plan["session"] else "")
            self._deliver_later(updated.raw["repo"])
            return ReattachResult(
                task_id=tid, how=plan["how"], kind=plan["kind"], pane=pane,
                session=plan["session"], lines=(line,),
            )
        finally:
            with contextlib.suppress(OSError):
                lock.unlink()

    def adopt(self, candidate: str, *, confirmed: bool = False) -> AdoptWorkerResult:
        """End an idle orphan worker terminal and reattach the task's agent under the current PM seat."""
        return adopt_task_for(self.ctx, candidate, confirmed=confirmed)

    # --- Retab ---

    def retab(self, target: str, *, tab: str | None = None, bug: str = "", dry_run: bool = False) -> RetabResult:
        """Rename a worker's tab to `<terminal>-<BUG>-<short>` and record it as its task's agent."""
        raw_target = target[3:] if target.startswith("hc:") else target
        resolved = None if target.startswith("hc:") else self._ledger.try_resolve_id(raw_target)
        task = (
            self._ledger.load(resolved).raw
            if resolved and self.ctx.home.task(resolved).is_file()
            else next((t for t in self._ledger.raw_tasks() if t.get("pane") == f"hc:{raw_target}" and t["status"] not in CLOSED), None)
        )
        term = hc_terminal_of(task) if task else (raw_target if TERM_HEAD.match(raw_target + "-") else "")
        if not term:
            raise Refused(self.ctx.config.tr(
                f"{target}: neither a task with a herdr-core terminal nor a terminal",
                f"{target}：不是有 herdr-core 终端的任务，也不是终端",
            ))
        resolved_bug = bug_of(bug, tab, cfg=self.ctx.config) or ("" if tab or not task else task_bug(task, cfg=self.ctx.config))
        short = tab_short(
            tab or tab_short((task or {}).get("tab") or (task or {}).get("title") or "", task_bug(task, cfg=self.ctx.config) if task else ""),
            resolved_bug,
        )
        name = tab_title(short, resolved_bug, term, cfg=self.ctx.config)
        if dry_run:
            return RetabResult(
                terminal=term, name=name, task_id=(task or {}).get("id"), bug=resolved_bug,
                dry_run_payload={"task": (task or {}).get("id"), "terminal": term, "tab": name, "agent": name, "bug": resolved_bug},
            )
        named = self.ctx.hc.name_tab(term, name, wait=5)
        if task:
            def _retab(cur: Task | None, ch: Change) -> dict[str, Any]:
                assert cur is not None
                r = cur.raw
                old = r.get("agent") or ""
                r.update(agent=name, tab=short)
                if resolved_bug:
                    r["bug"] = resolved_bug
                else:
                    r.pop("bug", None)
                ch.note_on(
                    r,
                    self.ctx.config.tr(f"tab renamed {old or '-'} -> {name}", f"标签改名 {old or '-'} → {name}")
                    + ("" if named else not_renamed(cfg=self.ctx.config) + self.ctx.config.tr(": ledger only", "：只改了台账")),
                )
                return r

            updated = self._ledger.change(task["id"], _retab)
            assert updated is not None
            task = updated.raw
        line = (
            f"{term}: {name}"
            + ("" if named else not_renamed(cfg=self.ctx.config))
            + (f" task={task['id']}" if task else "")
        )
        return RetabResult(terminal=term, name=name, task_id=(task or {}).get("id"), bug=resolved_bug, named=named, lines=(line,))

    # --- Retire, Close Worker Loop, Idle Workers ---

    def retire(self, task_id: str, *, force: bool = False, keep_active: bool = False) -> RetireResult:
        """Retire a task's review, worker terminal, worktree and branch."""
        return retire_workspace_for(self.ctx, task_id, force=force, keep_active=keep_active)

    def close_worker_loop(
        self,
        terminal: str,
        task_id: str,
        *,
        quiet: int | float,
        timeout: int | float,
        statuses: Sequence[str],
        retire: bool = False,
    ) -> None:
        """Wait until `terminal` has been idle for `quiet` seconds while `task_id` stays in `statuses`, then end it."""
        tid = self._ledger.resolve_id(task_id)
        deadline = self.ctx.clock.time() + timeout
        quiet_since: float | None = None
        while self.ctx.clock.time() < deadline:
            if statuses:
                try:
                    status = json.loads(self.ctx.home.task(tid).read_text()).get("status")
                except (OSError, ValueError):
                    return
                if status not in statuses:
                    return
            info = self.ctx.hc.get_raw(terminal, errors=True) or {}
            labels = info.get("labels") or {}
            if info.get("error") or labels.get("pm") or labels.get("task") != tid:
                return
            if self.active_review_of(tid):
                quiet_since = None
            elif info.get("state") != "live" or term_status(info) in ("idle", "done"):
                quiet_since = quiet_since or self.ctx.clock.time()
                if self.ctx.clock.time() - quiet_since >= quiet:
                    why = "workers.close_reported" if list(statuses) == ["review"] else "workers.close_on_close"
                    self.end_terminal(terminal, why=why, task_id=tid)
                    if retire:
                        with contextlib.suppress(Exception, SystemExit):
                            t = self.ctx.store.task(tid) or {}
                            if t and not t.get("retired") and t.get("status") in CLOSED:
                                self.retire(tid)
                    return
            else:
                quiet_since = None
            self.ctx.clock.sleep(5 if quiet < 300 else 30)

    def idle_workers(
        self,
        repo: str = ".",
        *,
        minutes: int | None = None,
        exited: bool = False,
        close: Sequence[str] | None = None,
    ) -> IdleWorkersResult:
        """List (and optionally close) this project's idle/done worker terminals."""
        resolved_repo = self.ctx.git.project_root(repo) or repo
        threshold = minutes if minutes is not None else idle_minutes_for(self.ctx)
        stamp = self.ctx.clock.time() * 1000
        tasks = self._ledger.raw_tasks()
        found: list[dict[str, Any]] = []
        for address, info, task in project_workers_for(self.ctx, resolved_repo, tasks=tasks):
            state, live = term_status(info), info.get("state") == "live"
            since = (info.get("status_ms") if live else info.get("finished_ms")) or info.get("created_ms") or stamp
            idle = int((stamp - since) / 60000)
            quiet = state in ("idle", "done") or (not state and idle >= threshold)
            if (live and not (quiet and idle >= threshold)) or (not live and not exited):
                continue
            rev = self.active_review_of(task["id"], tasks) or next(
                (r for t in tasks if hc_terminal_of(t) == address for r in (self.active_review_of(t["id"], tasks),) if r),
                None,
            )
            row: dict[str, Any] = {
                "terminal": address,
                "state": (state or "no-status") if live else "exited",
                "idle_minutes": idle,
                "task": task["id"],
                "task_status": task["status"],
                "name": str((info.get("labels") or {}).get("where") or info.get("name") or task.get("agent") or ""),
            }
            if rev:
                row["active_review"] = rev["id"]
            found.append(row)

        closed_lines: list[str] = []
        if close is not None:
            named = {x[3:] if x.startswith("hc:") else x for x in close}
            for w in found:
                if named and w["terminal"] not in named:
                    continue
                if w.get("active_review"):
                    if named:
                        closed_lines.append(
                            f"{w['terminal']}: " + self.ctx.config.tr(
                                f"kept (active review {w['active_review']})",
                                f"保留（审查 {w['active_review']} 还在进行）",
                            )
                        )
                    continue
                if not named and (w["state"] == "no-status" or w["task_status"] not in REPORTED):
                    continue
                ended_term = self.end_terminal(w["terminal"], why="idle-workers --close", task_id=w["task"])
                closed_lines.append(
                    f"{w['terminal']}: " + (self.ctx.config.tr("ended", "已关闭") if ended_term else self.ctx.config.tr("left", "未动"))
                )
        return IdleWorkersResult(rows=found, minutes=threshold, closed_lines=tuple(closed_lines))

    # --- Codex Command ---

    def codex_cmd(
        self,
        *,
        project: str | None = None,
        repo: str = ".",
        model: str | None = None,
        effort: str = "high",
        codex_profile: str | None = None,
    ) -> CodexCmdResult:
        """Compute the codex launch command from the PM's codex settings or codex profile pool."""
        resolved_repo = self.ctx.git.project_root(repo) or repo
        if not self.codex_pool(resolved_repo):
            rec = self._caller.current_pm_record(project, repo)
            codex_block = self.ctx.config.read().get("codex")
            cfg = codex_block if isinstance(codex_block, dict) else {}
            cmd = shell_join(["codex", *codex_args(model or "gpt-6-astra", effort, rec, cfg=cfg)], powershell=True)
            return CodexCmdResult(command=cmd)
        spec = WorkerSpec(kind="codex", model=model or "", effort=effort or "", codex_profile=codex_profile or "")
        stderr_lines: list[str] = []
        spec, warn = self.apply_codex_pool(spec, resolved_repo, "worker", hold=False)
        if warn:
            stderr_lines.append(warn)
        stderr_lines.append(spec.pool_said)
        cmd = shell_join(self.worker_argv(spec, (), resolved_repo, wrap=True), powershell=True)
        return CodexCmdResult(command=cmd, stderr_lines=tuple(stderr_lines), fell_back=spec.kind != "codex")
