"""`pm.py update` as data: the request (`UpdateRequest`), what it resolves to before the task lock
(`TransitionPlan`), the hooks the locked change needs from above the ledger (`TransitionHooks`), the locked change
itself (`apply_transition`, run by `Ledger.transition`) and its outcome (`Transition`). Layer 2.

Who the caller is, wake policy, auto-review gating and session bookkeeping live above this layer; the locked change
receives them as hooks so the task lock is held only for in-memory work plus the hooks' own reads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ..errors import Refused
from ..osutil import Options
from .plan import activate_first_todo, advance_outer_plan_step, parse_plan_steps, plan_progress, sync_plan_for_status
from .question import QUESTION_FIELDS
from .task import hc_terminal_of

# The task fields `pm.py update --<field>` sets as given.
FIELDS = ["title", "status", "owner", "workspace", "pane", "agent", "branch", "worktree",
          "base", "brief", "commit", "release", "parent"]


class UpdateRequest(Options):
    """Typed input of `pm.py update` (every flag; None: not given)."""

    required = ('id',)

    id: str = ""
    title: str | None = None
    status: str | None = None
    owner: str | None = None
    workspace: str | None = None
    pane: str | None = None
    agent: str | None = None
    branch: str | None = None
    worktree: str | None = None
    base: str | None = None
    brief: str | None = None
    commit: str | None = None
    release: str | None = None
    parent: str | None = None
    note: str | None = None
    depends_on: list[str] | None = None
    option: list[str] | None = None
    why: dict[int, str] | None = None
    recommend: bool = False
    keep: bool = False
    send: bool = False
    wait: bool = False
    ask: bool = False
    plan: list[str] | None = None
    step: list[str] | None = None
    step_done: bool = False
    outer_plan: list[str] | None = None
    subplan: list[str] | None = None
    no_review: bool = False

    @classmethod
    def from_args(cls, a: Any) -> UpdateRequest:
        values = {f: getattr(a, f, None) for f in FIELDS}
        return cls(
            id=a.id,
            **values,
            note=getattr(a, "note", None),
            depends_on=getattr(a, "depends_on", None),
            option=getattr(a, "option", None),
            why=getattr(a, "why", None),
            recommend=bool(getattr(a, "recommend", False)),
            keep=bool(getattr(a, "keep", False)),
            send=bool(getattr(a, "send", False)),
            wait=bool(getattr(a, "wait", False)),
            ask=bool(getattr(a, "ask", False)),
            plan=getattr(a, "plan", None),
            step=getattr(a, "step", None),
            step_done=bool(getattr(a, "step_done", False)),
            outer_plan=getattr(a, "outer_plan", None),
            subplan=getattr(a, "subplan", None),
            no_review=bool(getattr(a, "no_review", False)),
        )

    def field_values(self) -> dict[str, str | None]:
        return {f: getattr(self, f) for f in FIELDS}


def plan_input(plan: Any, step: Any, outer_plan: Any, subplan: Any, *, is_worker: Callable[[], bool],
               tr: Callable[[str, str], str] = lambda en, zh: en) -> tuple[list[dict[str, Any]] | None, bool, list[dict[str, Any]] | None]:
    """Resolve the plan flags into `(outer_steps, outer_explicit, sub_steps)`. None means the flag was not given;
    [] means it was given empty (clears the field). `--plan`/`--step` from the task's own worker set its subplan,
    from anyone else the outer plan (`is_worker` is asked only then). Raises `Refused` when --plan/--step are mixed with --outer-plan/--subplan."""
    has_shared = plan is not None or step is not None
    has_explicit = outer_plan is not None or subplan is not None
    if has_shared and has_explicit:
        raise Refused(tr("do not mix --plan/--step with --outer-plan/--subplan",
                         "不要把 --plan/--step 和 --outer-plan/--subplan 混用"))
    outer_steps, outer_explicit, sub_steps = None, False, None
    if outer_plan is not None:
        outer_steps, outer_explicit = parse_plan_steps(outer_plan, None, outer=True)
    if subplan is not None:
        sub_steps, _ = parse_plan_steps(subplan, None, outer=False)
    if has_shared:
        if is_worker():
            sub_steps, _ = parse_plan_steps(plan, step, outer=False)
        else:
            outer_steps, outer_explicit = parse_plan_steps(plan, step, outer=True)
    return outer_steps, outer_explicit, sub_steps


@dataclass(repr=False, eq=False)
class TransitionPlan:
    """An `UpdateRequest` validated and resolved before the task lock (Phase A of `cmd_update`)."""

    request: UpdateRequest
    fields: dict[str, str | None]
    outer_steps: list[dict[str, Any]] | None = None
    outer_explicit: bool = False
    sub_steps: list[dict[str, Any]] | None = None
    deps_val: list[str] | None = None
    options: list[str] = field(default_factory=list)
    asked: dict[str, Any] = field(default_factory=dict)
    review_extra: dict[str, Any] = field(default_factory=dict)
    auto_resume_blocked: bool = False
    pre_term: str = ""
    pre_turn: int | None = None
    idem_key: str = ""
    env_id: str = ""


@dataclass(repr=False, eq=False)
class TransitionHooks:
    """What the locked change asks of the layers above the ledger, called on the locked task record.

    blocked_by_worker(task): the latest blocking entry was written by a worker.
    is_pm_caller(task): this process runs in the project's PM terminal.
    wake_fields(task, moved, reported): the entry's `source`/`wake` fields.
    decide_review(task, changes): `(will_auto_review, resolved_sha, skip_reason)`.
    round_starts(task, term, turn): a new round of work for the worker in herdr-core terminal `term`.
    remember_session(task): record the writing session as the task's agent where it applies.
    """

    blocked_by_worker: Callable[[dict[str, Any]], bool]
    is_pm_caller: Callable[[dict[str, Any]], bool]
    wake_fields: Callable[[dict[str, Any], str, bool], dict[str, Any]]
    decide_review: Callable[[dict[str, Any], Sequence[str]], tuple[bool, str, str]]
    round_starts: Callable[[dict[str, Any], str, int | None], None]
    remember_session: Callable[[dict[str, Any]], None]
    tr: Callable[[str, str], str] = lambda en, zh: en


@dataclass(repr=False, eq=False)
class Transition:
    """What `Ledger.transition` did: the saved task, the field changes (`status=…` first among status changes),
    the status it moved to ("" when none), the entry's event fields, and the auto-review decision."""

    plan: TransitionPlan
    after: dict[str, Any] = field(default_factory=dict)
    changes: list[str] = field(default_factory=list)
    entry_fields: dict[str, Any] = field(default_factory=dict)
    will_auto_review: bool = False
    resolved_sha: str = ""
    old_parent: str = ""
    already_applied: bool = False

    @property
    def request(self) -> UpdateRequest:
        return self.plan.request

    @property
    def moved_status(self) -> str:
        return next((c[len("status="):] for c in self.changes if c.startswith("status=")), "")

    @property
    def status_changed(self) -> bool:
        return any(c.startswith("status=") for c in self.changes)


APPLIED_KEYS_KEPT = 64


def record_applied_key(task: dict[str, Any], idem_key: str, *, env_id: str, now: str, **meta: Any) -> None:
    """Keep report `idem_key` in the task record itself (C6a): written with the change it made, in the same file
    under the same lock, so a replay of that report finds it whatever happened after the write."""
    applied_map = dict(task.get("applied_reports") or {}) if isinstance(task.get("applied_reports"), dict) else {}
    keys_order = [str(k) for k in (task.get("last_applied_keys") or []) if isinstance(k, str) and k != idem_key]
    keys_order.append(idem_key)
    while len(keys_order) > APPLIED_KEYS_KEPT:
        applied_map.pop(keys_order.pop(0), None)
    applied_map[idem_key] = {"env_id": env_id, "at": now, **meta}
    task["applied_reports"] = applied_map
    task["last_applied_keys"] = keys_order


def apply_transition(task: dict[str, Any], plan: TransitionPlan, hooks: TransitionHooks, note: Callable[..., Any],
                     now: str, result: Transition) -> dict[str, Any] | None:
    """The locked change of `pm.py update` on the task record `task` (Phase B). Fills `result` and returns `task`."""
    if plan.idem_key:
        applied_map = task.get("applied_reports")
        if isinstance(applied_map, dict) and plan.idem_key in applied_map:
            rec = applied_map[plan.idem_key]
            if isinstance(rec, dict):
                result.after = task
                result.already_applied = True
                result.changes = list(rec.get("changes") or ())
                result.entry_fields = dict(rec.get("entry_fields") or {})
                result.will_auto_review = bool(rec.get("will_auto_review"))
                result.resolved_sha = str(rec.get("resolved_sha") or "")
                result.old_parent = str(rec.get("old_parent") or "")
                return None
    req = plan.request
    changes: list[str] = []
    told: dict[str, Any] = {}
    will_auto_review, resolved_sha = False, ""
    prev_status = task.get("status") or ""
    prev_parent = str(task.get("parent") or "")
    was_blocked_by_worker = (prev_status == "blocked") and hooks.blocked_by_worker(task)
    prev_no_review = bool(task.get("no_review"))
    for f, value in plan.fields.items():
        if f == "parent" and value == "" and "parent" in task:
            changes.append("parent=")
            task.pop("parent")
        elif value is not None and task.get(f, "" if f == "parent" else None) != value:
            changes.append(f"{f}={value}")
            task[f] = value
            if f == "pane":
                task.pop("closed", None)
        elif f == "status" and value == "blocked":
            # Blocked again while blocked: a new question (asks_again), even with the status unchanged.
            changes.append("status=blocked")
    if plan.auto_resume_blocked and task.get("status") == "blocked" and was_blocked_by_worker:
        changes.append("status=in_progress")
        task["status"] = "in_progress"
    deps_val = plan.deps_val
    if deps_val is not None:
        if not deps_val and "depends_on" in task:
            changes.append("depends_on=")
            task.pop("depends_on", None)
            task.pop("deps_notified", None)
        elif deps_val and list(task.get("depends_on") or []) != deps_val:
            changes.append(f"depends_on={','.join(deps_val)}")
            task["depends_on"] = list(deps_val)
            task.pop("deps_notified", None)
    outer_steps, sub_steps = plan.outer_steps, plan.sub_steps
    if outer_steps is not None:
        if outer_steps:
            task["plan"] = [dict(s) for s in outer_steps]
        else:
            task.pop("plan", None)
    if sub_steps is not None:
        if sub_steps:
            task["subplan"] = [dict(s) for s in sub_steps]
        else:
            task.pop("subplan", None)
    if req.no_review:
        task["no_review"] = True
    if req.step_done and outer_steps is None:
        advance_outer_plan_step(task)
    moved = next((c[len("status="):] for c in changes if c.startswith("status=")), "")
    if moved:
        if moved != "proposed":
            task.pop("deps_notified", None)
        sync_plan_for_status(task, moved, prev_status=prev_status,
                             explicit_outer=outer_steps is not None,
                             explicit_outer_states=plan.outer_explicit)
    elif outer_steps:
        if task.get("status") == "in_progress":
            activate_first_todo(task["plan"])
    options, asked = plan.options, plan.asked
    offered = bool(options) and {f: task.get(f) for f in QUESTION_FIELDS if f in task} != asked
    if any(c.startswith("status=") for c in changes):
        task.pop("paused_from", None)  # set by an archive; a status given by hand replaces it
        task.pop("escalating", None)  # an escalation's question is over once the task moves on (declined, or not)
        task.pop("adopting", None)  # an adopt question is over once the task moves on
    if "status=in_progress" in changes and hc_terminal_of(task) and "/" not in hc_terminal_of(task):
        # Sent back with findings, or an answer recorded: a new round of work for its worker from here.
        term = hc_terminal_of(task)
        hooks.round_starts(task, term, plan.pre_turn if term == plan.pre_term else None)
    if options or any(c.startswith("status=") for c in changes):
        for f in QUESTION_FIELDS:
            task.pop(f, None)
        task.update(asked)
    will_auto_review, resolved_sha, skip_reason = hooks.decide_review(task, changes)
    plan_changed = (outer_steps is not None) or (req.no_review and not prev_no_review)
    note_text = req.note
    if note_text or changes or offered or plan_changed:
        text = "; ".join(x for x in [", ".join(changes), note_text] if x) or " / ".join(options)
        if not text and plan_changed:
            if outer_steps:
                done_n, total_n, _ = plan_progress(task.get("plan"))
                text = f"plan updated ({done_n}/{total_n})"
            elif outer_steps == []:
                text = "plan cleared"
            elif req.no_review:
                text = "no_review enabled"
        if skip_reason == "round limit reached" and text:
            text += hooks.tr(" (auto-review skipped: round limit reached)", "（已达自动审查轮次上限，转交 PM）")
        reported = bool(note_text or req.commit)
        told = hooks.wake_fields(task, moved, reported)
        if will_auto_review:
            told = {**told, "wake": False}
            task["auto_review"] = {
                "status": "starting",
                "commit": req.commit or "",
                "resolved": resolved_sha,
                "note": note_text or "",
                "at": now,
            }
        elif skip_reason == "duplicate running commit":
            told = {**told, "wake": False}
        handled_extra = (
            {"handled_by": "pm"}
            if prev_status == "blocked" and moved and moved != "blocked" and hooks.is_pm_caller(task)
            and was_blocked_by_worker
            else {}
        )
        note(task, text, **asked, **told, **plan.review_extra, **handled_extra)
    if plan.idem_key:
        record_applied_key(task, plan.idem_key, env_id=plan.env_id, now=now, changes=list(changes),
                           entry_fields=dict(told), will_auto_review=bool(will_auto_review),
                           resolved_sha=resolved_sha, old_parent=prev_parent)
    hooks.remember_session(task)
    result.after = task
    result.changes = changes
    result.entry_fields = told
    result.will_auto_review = will_auto_review
    result.resolved_sha = resolved_sha
    result.old_parent = prev_parent
    return task
