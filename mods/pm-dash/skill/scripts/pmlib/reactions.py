"""`pm.py update` over an explicit `Context`: validate and resolve the request (Phase A), the two silent fast paths,
the locked `Ledger.transition` (Phase B), and the ordered reactions to a saved transition (pm-py-pass-two.md,
section 3.2). Layer 3: never prints; what a reaction has to say goes to the `say(text, err=False)` callback in the
order it happens, so a later reaction that raises leaves the earlier lines said.

Reaction rows, in order:
   1  the entry wakes the PM: start the project's deliverer
   -  `<id>: <status>` is said here, after row 1 and before the rest
   2  review/blocked/done/merged/released with a status change, --note or --commit: collect research reports
   3  auto-review: start the reviewer and stop (rows 4-9b do not run)
   4  --send: type the note into the worker (raises when a synchronous --wait send fails)
  5a  merged, not auto-retired: close the review thread
  5b  merged and dispatched, or done after a land with post-merge steps: retire the workspace (self: once the turn
      ends); 5b, 6 and 7 exclude one another, in that order
   6  a closed status without --keep: end the worker terminal (workers.close_on_close), prune memory candidates
   7  review: end a reported worker once idle (workers.close_reported) and note it on the task
   8  a review thread done: sync the parent's @review step and auto_review
  9a  --depends-on on a proposed task: remember what was seen; say (stderr) when all prerequisites are met
  9b  merged/released/done/abandoned: reconcile the tasks that depend on this one
  10  closed child with parent: lock parent, re-read, roll up (auto-close done or notify PM, cascade up to 5 levels)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .caller import Caller
from .context import Context
from .errors import PmError, Refused
from .events.deliver import PASSED, Delivery
from .events.deps_watch import DependencyWatcher
from .events.policy import wake_fields_for
from .events.stalls import StallWatcher
from .ledger.deps import DEP_MET_STATUSES, dep_key_for, evaluate_depends_on, format_dep_summary, parse_depends_on
from .ledger.family import Family, Rollup, parent_of
from .ledger.ledger import Change, Ledger
from .ledger.plan import plan_progress, sync_plan_for_status
from .ledger.question import quick_answers
from .ledger.task import ACTIVE, CLOSED, Task, hc_terminal_of
from .ledger.transition import Transition, TransitionHooks, TransitionPlan, UpdateRequest, plan_input
from .memory.candidates import MemoryCandidates, candidate_names_of
from .project.project import ProjectRegistry
from .project.readmodel import answered_tasks, asked_at
from .project.conversation import Conversation, conversation_events
from .review.review import Reviews
from .store import valid_task_id
from .workers.lifecycle import close_later_for, close_reported_for, close_worker_for
from .workers.service import Workers
from .workers.sessions import remember_session_for

RESEARCH_COLLECT_STATUSES = ("review", "blocked", "done", "merged", "released")
MAX_ROLLUP_DEPTH = 5

Say = Callable[..., None]  # say(text, err=False)


def _quiet(text: str, err: bool = False) -> None:
    return None


@dataclass(repr=False, eq=False)
class UpdateDone:
    """The outcome of `Updates.update`: the transition (None for a fast path) and the saved task."""

    task: dict[str, Any]
    transition: Transition | None = None


class Updates:
    """`pm.py update` as a Layer 3 service."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._ledger = Ledger(ctx)
        self._projects = ProjectRegistry(ctx)

    @property
    def _caller(self) -> Caller:
        return self.ctx.caller if self.ctx.caller is not None else Caller(self.ctx)

    def _tr(self, en: str, zh: str) -> str:
        return self.ctx.config.tr(en, zh)

    def hooks(self, commit: str | None) -> TransitionHooks:
        """What the locked change asks of the caller, wake policy, reviews, stalls and sessions; `commit`: the
        reported commit the auto-review decision is about."""
        caller = self._caller
        reviews = Reviews(self.ctx)
        stalls = StallWatcher(self.ctx)

        def wake_fields(task: dict[str, Any], status: str, reported: bool) -> dict[str, Any]:
            return wake_fields_for(task, status, reported, caller, bool(self._projects.app_pm(task.get("repo"))))

        return TransitionHooks(
            blocked_by_worker=caller.blocked_by_worker,
            is_pm_caller=lambda task: caller.is_pm_caller(task),
            wake_fields=wake_fields,
            decide_review=lambda task, changes: reviews.should_auto_review(task, commit, changes),
            round_starts=lambda task, term, turn: stalls.round_starts(task, term, turn=turn),
            remember_session=lambda task: remember_session_for(self.ctx, task),
            tr=self._tr,
        )

    def prepare(self, req: UpdateRequest, snapshot: dict[str, Any]) -> TransitionPlan:
        """Phase A: validate the request against the task as it was read, and resolve it. Raises `Refused` or
        `NotFound` with the message the command prints."""
        tr = self._tr
        caller = self._caller
        tid = snapshot["id"]
        outer_steps, outer_explicit, sub_steps = plan_input(
            req.plan, req.step, req.outer_plan, req.subplan, tr=tr,
            is_worker=lambda: bool(self.ctx.pane and snapshot.get("pane") == self.ctx.pane
                                   and not caller.is_pm_caller(snapshot)),
        )
        if req.send and not req.note:
            raise Refused(tr("--send types --note into the worker: give the note",
                             "--send 是把 --note 发给 worker：要给出 --note"))
        if req.ask and req.status != "blocked":
            raise Refused(tr("--ask goes with --status blocked: it asks the user a follow-up",
                             "--ask 要和 --status blocked 一起用：它是向用户追问"))
        # Blocked again once the user has answered is a new question (asks_again): only with --ask. Recording the
        # answer is moving the task on; blocked means waiting for the user.
        log = self.ctx.home.project_for(snapshot["repo"]).conversation if snapshot.get("repo") else None
        if req.status == "blocked" and snapshot["status"] == "blocked" and not req.ask and log and \
                tid in answered_tasks(conversation_events(log), {tid: snapshot.get("title") or ""},
                                      {tid: asked_at(snapshot)}):
            raise Refused(tr(f"{tid}: the user has already answered. To record the answer, use --status in_progress "
                             "or --status done with --note; to ask a follow-up, add --ask.",
                             f"{tid}：用户已经回答了。要记下回答，用 --status in_progress 或 --status done 加 --note；"
                             "确实要追问，加 --ask。"))
        fields = req.field_values()
        if req.parent is not None:
            fields["parent"] = parent_of(tid, req.parent, repo=snapshot.get("repo"), ledger=self._ledger,
                                         home=self.ctx.home)
        deps_val = parse_depends_on(req.depends_on, task_id=tid, existing=snapshot.get("depends_on"),
                                    home=self.ctx.home, store=self.ctx.store, tr_fn=tr)
        # Quick answers the user can pick in the project view; validated outside the lock.
        options, asked = quick_answers(req)
        return TransitionPlan(request=req, fields=fields, outer_steps=outer_steps, outer_explicit=outer_explicit,
                              sub_steps=sub_steps, deps_val=deps_val, options=options, asked=asked)

    def update(self, req: UpdateRequest, say: Say = _quiet) -> UpdateDone:
        """`pm.py update`: Phase A, a silent fast path or the locked transition, then the reactions."""
        snapshot = self._ledger.load(req.id).raw
        req.id = snapshot["id"]
        tid = req.id
        plan = self.prepare(req, snapshot)
        has_field_change = any(v is not None for v in plan.fields.values()) or plan.deps_val is not None
        quiet = (not req.no_review and not req.note and not plan.options and not req.send and not has_field_change)
        remember = lambda cur: remember_session_for(self.ctx, cur)  # noqa: E731
        if req.step_done and plan.outer_steps is None and plan.sub_steps is None and quiet:
            task, changed, d, t, nxt = self._ledger.advance_step(tid, on_task=remember)
            raw = task.raw
            if not t:
                say(f"{raw['id']}: {raw['status']} (no outer plan)")
            elif not changed:
                say(f"{raw['id']}: {raw['status']} (plan {d}/{t}, all done)")
            else:
                tail = f", next: {nxt}" if nxt else ", all done"
                say(f"{raw['id']}: {raw['status']} (plan {d}/{t}{tail})")
            return UpdateDone(task=raw)
        if plan.sub_steps is not None and plan.outer_steps is None and not req.step_done and quiet:
            raw = self._ledger.update_subplan(tid, plan.sub_steps, on_task=remember).raw
            done_n, total_n, _ = plan_progress(raw.get("subplan"))
            suffix = f"subplan {done_n}/{total_n}" if total_n else "subplan cleared"
            say(f"{raw['id']}: {raw['status']} ({suffix})")
            return UpdateDone(task=raw)
        self.probe(plan, snapshot)
        tr = self.transition(tid, plan)
        wake(self.ctx, tr)
        say(f"{tr.after['id']}: {tr.after['status']}")
        after(self.ctx, tr, say)
        return UpdateDone(task=tr.after, transition=tr)

    def probe(self, plan: TransitionPlan, snapshot: dict[str, Any]) -> None:
        """What is read before the lock: the auto-review a review thread reports to, whether a PM's --send resumes a
        worker-blocked task, and the worker terminal's turn count when the task goes back to work."""
        req = plan.request
        rev_parent_id = snapshot.get("review_of")
        if rev_parent_id and req.status == "done" and valid_task_id(rev_parent_id):
            parent_snap = self.ctx.store.task(rev_parent_id) or {}
            ar = parent_snap.get("auto_review") if isinstance(parent_snap, dict) else None
            if isinstance(ar, dict) and ar.get("status") in ("starting", "running") and (
                    ar.get("review_id") in (None, "", snapshot["id"])):
                plan.review_extra = {
                    "review_of": rev_parent_id,
                    "worker_commit": ar.get("commit") or parent_snap.get("commit") or "",
                    "worker_note": ar.get("note") or "",
                }
        # Sending instructions from the PM to a worker-blocked task unblocks it back to in_progress automatically
        # unless an explicit --status was given. Never auto-unblock a question card posted by the PM itself!
        caller = self._caller
        plan.auto_resume_blocked = bool(
            req.send
            and req.status is None
            and snapshot.get("status") == "blocked"
            and caller.is_pm_caller(snapshot)
            and caller.blocked_by_worker(snapshot)
        )
        # The hc turn count is read outside the lock when the task goes (back) to in_progress.
        if (req.status == "in_progress" or plan.auto_resume_blocked) and snapshot.get("status") != "in_progress":
            probe = {**snapshot, **({"pane": req.pane} if req.pane is not None else {})}
            term = hc_terminal_of(probe)
            if term and "/" not in term:
                plan.pre_term = term
                plan.pre_turn = (self.ctx.hc.get_raw(term) or {}).get("turn") or 0

    def transition(self, task_id: str, plan: TransitionPlan) -> Transition:
        return self._ledger.transition(task_id, plan, self.hooks(plan.request.commit))


def wake(ctx: Context, tr: Transition) -> None:
    """Row 1: the entry is news for a PM that can be woken: its deliverer runs."""
    if tr.entry_fields.get("wake"):
        Workers(ctx)._deliver_later(tr.after["repo"])


def after(ctx: Context, tr: Transition, say: Say = _quiet) -> None:
    """Rows 2-9b, in order (see the module docstring)."""
    task, changes, req = tr.after, tr.changes, tr.request
    tid = task["id"]
    workers = Workers(ctx)
    tt = ctx.config.tr
    if task["status"] in RESEARCH_COLLECT_STATUSES and (tr.status_changed or req.note or req.commit):
        collected = workers.collect_research(task)
        if collected:
            say(f"{tid}: collected research: {', '.join(collected)}")
    if tr.will_auto_review:
        say(Reviews(ctx).run_auto_review(tid, req.commit or "", tr.resolved_sha, req.note or ""))
        return
    if req.send:
        say(workers.send_back(task, req.note or "", wait=req.wait).message)
    # A merged task that the PM dispatched is cleaned up at once; its worker, worktree and branch have no further use.
    # Its review has done its job in any case, even when the worker is kept (retire closes it otherwise).
    auto = "status=merged" in changes and task.get("dispatched") and not req.keep
    landed_done = ("status=done" in changes and bool(task.get("landed")) and task.get("dispatched")
                   and not task.get("retired") and not req.keep)
    closed = workers.retire_review(task) if "status=merged" in changes and not auto else []
    if closed:
        say(f"{tid}: closed {', '.join(closed)}")
    if auto or landed_done:
        term = hc_terminal_of(task)
        if term and f"hc:{term}" == ctx.pane:
            # Self-closing worker: background close + retire once this turn ends, so its cwd stays intact.
            close_later_for(ctx, term, tid, 10, 7200, CLOSED, retire=True)
            say(tt(f"{tid}: hc:{term} and workspace will retire once this turn ends",
                   f"{tid}：hc:{term} 和工作树将在本轮结束后自动回收"))
        else:
            try:
                for line in workers.retire(tid, force=False).lines:
                    say(line)
            except PmError as stop:
                say(f"not retired: {stop}. Fix that, then run `pm.py retire {tid}`.")
    elif any(c == f"status={s}" for c in changes for s in CLOSED) and not req.keep:
        # Done with: its worker terminal (a reviewer's too) is not left idle (close_worker).
        ended = close_worker_for(ctx, task)
        if ended:
            say(f"{tid}: {ended}")
        if task.get("repo"):
            MemoryCandidates(ctx, task["repo"]).prune(finished=candidate_names_of(task))
    elif "status=review" in changes:
        ended = close_reported_for(ctx, task)  # a reported worker's terminal ends once idle
        if ended:
            Ledger(ctx).change(tid, lambda cur, ch: _noted(cur, ch, ended))
    if task.get("review_of") and "status=done" in changes:
        rev_note = (req.note or "").strip()
        Reviews(ctx).sync_on_done(task["review_of"], tid, rev_note, passed=bool(rev_note and PASSED.match(rev_note)))
    if tr.plan.deps_val and task.get("status") == "proposed":
        ledger = Ledger(ctx)
        by_id = {t["id"]: t for t in ledger.raw_tasks() if isinstance(t, dict) and t.get("id")}
        info = evaluate_depends_on(task, by_id)
        key = dep_key_for(info)
        if key:
            ledger.change(tid, lambda cur, _ch: (cur.raw.update(deps_notified=key), cur.raw)[1], board=False)
            if info["ready"]:
                say(tt(f"note: all dependencies of {tid} are already met ({format_dep_summary(info, tr_fn=tt)}); "
                       "ready to dispatch",
                       f"提示：{tid} 的前置依赖均已满足（{format_dep_summary(info, tr_fn=tt)}），现在即可派发"), err=True)
    if tr.moved_status in (*DEP_MET_STATUSES, "abandoned"):
        DependencyWatcher(ctx).reconcile_dependents_of(tid, primary_repo=task.get("repo"))
    parent_id = str(task.get("parent") or "")
    old_parent = str(tr.old_parent or "")
    parent_changed = old_parent != parent_id
    if parent_id and (tr.moved_status in ACTIVE or parent_changed):
        Ledger(ctx).clear_rollup_notified(parent_id)
    if parent_changed and old_parent:
        _rollup_ancestors(ctx, old_parent, child_id=tid)
    if parent_id and (tr.moved_status in CLOSED or (parent_changed and task.get("status") in CLOSED)):
        _rollup_ancestors(ctx, parent_id, child_id=tid)


def _parent_own_session_live(
    ctx: Context,
    parent: dict[str, Any],
    projects: ProjectRegistry,
    workers: Workers,
) -> bool:
    """Whether `parent` has a live session of its own (non-empty pane, not the PM's terminal, and live)."""
    pane = str(parent.get("pane") or "")
    if not pane:
        return False
    repo = parent.get("repo")
    if repo and pane in projects.pm_panes(repo):
        return False
    return workers.is_pane_live(pane)


def _rollup_ancestors(ctx: Context, start_parent_id: str, *, child_id: str | None = None) -> None:
    """Row 10: lock `parent_id`, re-read tasks, evaluate `Family.rollup`, and cascade up to `MAX_ROLLUP_DEPTH`."""
    ledger = Ledger(ctx)
    projects = ProjectRegistry(ctx)
    workers = Workers(ctx)
    deps_watcher = DependencyWatcher(ctx)
    seen: set[str] = {child_id} if child_id else set()
    parent_id: str | None = start_parent_id

    for _ in range(MAX_ROLLUP_DEPTH):
        if not parent_id or parent_id in seen or not valid_task_id(parent_id):
            break
        seen.add(parent_id)
        snap = ctx.store.task(parent_id)
        if not isinstance(snap, dict) or snap.get("status") in CLOSED:
            break
        pre_pane = str(snap.get("pane") or "")
        pre_live = _parent_own_session_live(ctx, snap, projects, workers)

        outcome: str | None = None
        chosen_rollup: Rollup | None = None
        chosen_key = ""
        target_repo = ""
        target_title = ""
        should_wake = False
        next_parent = ""

        def _apply(cur: Task | None, ch: Change) -> dict[str, Any] | None:
            nonlocal outcome, chosen_rollup, chosen_key, target_repo, target_title, should_wake, next_parent
            if cur is None:
                return None
            raw = cur.raw
            if raw.get("status") in CLOSED:
                return None
            tasks = ledger.raw_tasks()
            live = pre_live if str(raw.get("pane") or "") == pre_pane else _parent_own_session_live(
                ctx, raw, projects, workers
            )
            fam = Family.from_tasks(raw, tasks)
            res = fam.rollup(ACTIVE, CLOSED, own_session_live=live, tr_fn=ctx.config.tr)
            if res is None:
                return None
            key = fam.rollup_key
            repo = str(raw.get("repo") or "")
            if res.action == "notify":
                if raw.get("rollup_notified") == key:
                    return None
                raw["rollup_notified"] = key
                outcome = "notify"
                chosen_rollup = res
                chosen_key = key
                target_repo = repo
                target_title = str(raw.get("title") or "")
                return raw
            if res.action == "close":
                prev_status = str(raw.get("status") or "")
                raw["status"] = "done"
                raw.pop("deps_notified", None)
                raw.pop("paused_from", None)
                raw.pop("escalating", None)
                raw.pop("adopting", None)
                raw.pop("rollup_notified", None)
                sync_plan_for_status(raw, "done", prev_status=prev_status)
                wake_pm = bool(repo and projects.app_pm(repo))
                ch.note_on(
                    raw,
                    f"status=done; {res.summary}",
                    source="rollup",
                    by="pm.py",
                    **({"wake": True} if wake_pm else {}),
                )
                outcome = "close"
                chosen_rollup = res
                chosen_key = key
                target_repo = repo
                should_wake = wake_pm
                next_parent = str(raw.get("parent") or "")
                return raw
            return None

        try:
            ledger.change(parent_id, _apply, board=False)
        except (PmError, OSError):
            break

        if outcome == "close":
            ledger.run_after_save()
            if should_wake and target_repo:
                Delivery(ctx, target_repo).ensure_running()
            deps_watcher.reconcile_dependents_of(parent_id, primary_repo=target_repo or None)
            parent_id = next_parent
        elif outcome == "notify":
            if target_repo and chosen_rollup is not None:
                wake_pm = bool(projects.app_pm(target_repo))
                Conversation(ctx, target_repo).record(
                    "event",
                    task=parent_id,
                    title=target_title,
                    source="rollup",
                    by="pm.py",
                    reason=chosen_rollup.reason,
                    key=chosen_key,
                    text=chosen_rollup.summary,
                    wake=wake_pm,
                )
                if wake_pm:
                    Delivery(ctx, target_repo).ensure_running()
            break
        else:
            break


def _noted(cur: Task | None, ch: Change, text: str) -> dict[str, Any]:
    assert cur is not None
    ch.note_on(cur.raw, text)
    return cur.raw
