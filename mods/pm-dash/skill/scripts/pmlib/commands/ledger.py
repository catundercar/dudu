"""Ledger task commands and plan-argument helpers (`new`, `update`, `guard`, `backfill-numbers`, `conversation`). Layer 4."""
import argparse
import datetime
import json
from pathlib import Path
import sys

from ..context import Context
from ..errors import IdentityError, NotFound, PmError, Refused, StoreError
from ..events.deliver import Delivery
from ..events.policy import wake_fields
from ..homemove import (
    HomeMover,
    _default_backfill_backup_dir,
    _format_bytes,
    _is_subpath,
    _unique_path,
)
from ..ledger.board import Board
from ..ledger.deps import dep_key_for, evaluate_depends_on, format_dep_summary, parse_depends_on
from ..ledger.family import parent_of
from ..ledger.ledger import Ledger
from ..ledger.plan import sync_plan_for_status
from ..ledger.question import quick_answers
from ..ledger.task import ACTIVE, CLOSED
from ..ledger.transition import FIELDS, UpdateRequest, plan_input
from ..osutil import clip
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..reactions import Updates
from ..workers.sessions import remember_session_for
from .emit import exit_with, sayer


def cmd_guard(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    role = ctx.caller.check_role(a.action, a.repo)
    if role["pm"]:
        role["pm"] = {k: role["pm"].get(k) for k in
                      ("name", "repo", "session", "workspace", "pane", "registered", "verified", "uncertain")}
    ctx.out.line(json.dumps(role, ensure_ascii=False, indent=2))


def plan_input_from_args(a, *, task=None, is_new=False, ctx=None):
    """Resolve CLI plan flags into (outer_steps, outer_explicit, sub_steps).

    None means flag omitted; [] means explicitly passed empty string (clears field).
    """
    ctx = Context.from_env() if ctx is None else ctx
    try:
        return plan_input(
            getattr(a, "plan", None), getattr(a, "step", None), getattr(a, "outer_plan", None),
            getattr(a, "subplan", None), tr=ctx.config.tr,
            is_worker=lambda: bool(not is_new and ctx.pane and task and task.get("pane") == ctx.pane
                                   and not ctx.caller.is_pm_caller(task)),
        )
    except Refused as err:
        sys.exit(str(err))


def cmd_conversation(a, ctx=None):
    """Print the end of the project's conversation log: how to look further back than a handover does."""
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    events = [e for e in Conversation(ctx, repo).events() if not a.type or e.get("type") in a.type.split(",")]
    for e in events[-a.last:]:
        kind = e.get("type")
        who = {"user": tr("User", "用户"), "pm": "PM", "decision": tr("Decision", "决定"), "agent": e.get("by"),
               "helper": f"[helper {e.get('helper') or '?'}] {e.get('by') or ''}",
               "event": f"[{e.get('source') or 'event'}" + (f" · {e.get('task')}" if e.get("task") else "") + "]",
               "thread": f"[{e.get('task')} · {e.get('status')}] {e.get('by')}"}.get(kind, kind)
        text = str(e.get("text") or "") + (f' — "{e["quote"]}"' if e.get("quote") else "")
        ctx.out.line(f"{e.get('at')} {who}: {clip(' '.join(text.split()), a.width)}")


def cmd_new(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    tr = ctx.config.tr
    outer_steps, outer_explicit, sub_steps = plan_input_from_args(a, is_new=True, ctx=ctx)
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    project = Path(repo).name
    ledger = Ledger(ctx)
    projects = ProjectRegistry(ctx)
    pm = projects.find_pm()
    task = {"id": ledger.new_id(project, a.slug or a.branch or a.title), "title": a.title, "project": project,
            "repo": repo, "status": a.status, "base": a.base or ctx.git.base_branch(repo),
            "owner": a.owner or ("pm" if pm and pm.get("pane_id") == ctx.pane else "self"),
            # An explicit empty --pane/--workspace records work that is not tied to this session.
            "workspace": ctx.workspace if a.workspace is None else a.workspace,
            "pane": ctx.pane if a.pane is None else a.pane, "created": ctx.clock.now()}
    for f in ("agent", "branch", "worktree", "brief", "kind"):
        if getattr(a, f, None):
            task[f] = getattr(a, f)
    try:
        if getattr(a, "parent", None):
            task["parent"] = parent_of(task["id"], a.parent, repo=repo, ledger=ledger, home=ctx.home)
        depends_on = parse_depends_on(getattr(a, "depends_on", None), task_id=task["id"],
                                      home=ctx.home, store=ctx.store, tr_fn=tr)
    except (NotFound, Refused) as err:
        sys.exit(str(err))
    already_ready_note = ""
    if depends_on:
        task["depends_on"] = depends_on
        if task["status"] == "proposed":
            every = ledger.raw_tasks()
            by_id = {t["id"]: t for t in every if isinstance(t, dict) and t.get("id")}
            info = evaluate_depends_on(task, by_id)
            key = dep_key_for(info)
            if key:
                task["deps_notified"] = key
                if info["ready"]:
                    dep_summary = format_dep_summary(info, tr_fn=tr)
                    already_ready_note = tr(
                        f"note: all dependencies of {task['id']} are already met ({dep_summary}); ready to dispatch",
                        f"提示：{task['id']} 的前置依赖均已满足（{dep_summary}），现在即可派发",
                    )
    if outer_steps:
        task["plan"] = outer_steps
    if sub_steps:
        task["subplan"] = sub_steps
    if getattr(a, "no_review", False):
        task["no_review"] = True
    sync_plan_for_status(task, task["status"], explicit_outer=outer_steps is not None,
                         explicit_outer_states=outer_explicit)
    remember_session_for(ctx, task)
    # A question for the user that belongs to no task yet: a blocked entry of its own, with its quick answers.
    try:
        options, asked = quick_answers(a)
    except Refused as err:
        sys.exit(str(err))
    task.update(asked)
    task["number"] = ctx.store.allocate_task_number(
        ctx.store._task_slug(task),
        before_backfill=lambda _slug, _count: HomeMover(ctx).create_backfill_backup(),
        timeout=30.0,
    )
    told = wake_fields(task, task["status"], ctx=ctx)
    entry_text = a.note or f"registered ({task['status']})"
    extra = {**asked, **told}
    entry = {"at": ctx.clock.now(), "by": ctx.pane or "user", "text": entry_text}
    task.setdefault("log", []).append(entry)
    ledger.save(task)
    if task.get("repo"):
        Conversation(ctx, task["repo"]).record(
            "thread", task=task["id"], title=task.get("title", ""), status=task.get("status", ""),
            by=entry["by"], text=entry_text,
            **({"number": task["number"]} if task.get("number") else {}),
            **extra,
        )
    if task.get("parent"):
        ledger.clear_rollup_notified(task["parent"])
    if told.get("wake"):
        Delivery(ctx, task["repo"]).ensure_running()
    if already_ready_note:
        ctx.out.err_line(already_ready_note)
    ctx.out.line(task["id"])
    return task["id"]


def cmd_update(a, ctx=None):
    """`pm.py update`: the request through `Updates` (validation, the locked transition, its reactions), each line
    written as it is said."""
    ctx = Context.from_env() if ctx is None else ctx
    req = UpdateRequest.from_args(a)
    try:
        Updates(ctx).update(req, say=sayer(ctx))
    except (StoreError, IdentityError):
        raise
    except PmError as err:
        exit_with(ctx, err)
    a.id = req.id


def cmd_backfill_numbers(a, ctx=None):
    """Assign chronological sequential task numbers once per project (idempotent, locked, verified backup)."""
    ctx = Context.from_env() if ctx is None else ctx
    slug = ProjectRegistry(ctx).resolve_project_slug(a.project) if getattr(a, "project", None) else None
    dry_run = bool(getattr(a, "dry_run", False))
    plan = ctx.store.backfill_task_numbers(slug, dry_run=True)
    total = plan.get("total_assigned", 0)
    home = ctx.home.root
    backup_dir = (Path(a.backup_dir).expanduser().resolve() if getattr(a, "backup_dir", None)
                  else _default_backfill_backup_dir(home))
    if _is_subpath(backup_dir, home):
        msg = f"Backup directory {backup_dir} must be outside {home}."
        if getattr(a, "json", False):
            ctx.out.line(json.dumps({"ok": False, "error": msg, "reason": "invalid_backup_dir"}, ensure_ascii=False, indent=2))
            sys.exit(1)
        sys.exit(msg)
    backup_info = None
    no_backup = bool(getattr(a, "no_backup", False))
    planned_backup = ""
    if total > 0 and not no_backup:
        stamp = ctx.clock.datetime_now().strftime("%Y%m%d-%H%M%S")
        backup_path = _unique_path(backup_dir / f"pm-{stamp}-before-backfill.tgz", suffix=".tgz")
        planned_backup = str(backup_path)
    if dry_run:
        result = {"ok": True, "home": str(home), "backup": planned_backup or None, **plan}
        if getattr(a, "json", False):
            ctx.out.line(json.dumps(result, ensure_ascii=False, indent=2))
            return
        ctx.out.line(f"Dry-run backfill ({home}): {total} task(s) would be numbered.")
        if planned_backup:
            ctx.out.line(f"  Planned backup archive: {planned_backup}")
        for s, info in sorted(plan.get("projects", {}).items()):
            ctx.out.line(f"  {s}: +{len(info['assigned'])} assigned (already={info['already_numbered']}, "
                         f"reviews={info['skipped_reviews']}, last={info['last']})")
        return

    def _ensure_backup(_slug, _count):
        nonlocal backup_info
        if backup_info is None:
            backup_info = HomeMover(ctx).create_backfill_backup(backup_dir)

    res = ctx.store.backfill_task_numbers(
        slug,
        dry_run=False,
        before_backfill=None if no_backup else _ensure_backup,
    )
    if res.get("total_assigned", 0) > 0:
        Board(ctx).write()
    result = {"ok": True, "home": str(home), "backup": backup_info, **res}
    if getattr(a, "json", False):
        ctx.out.line(json.dumps(result, ensure_ascii=False, indent=2))
        return
    ctx.out.line(f"Backfilled task numbers ({home}): {res['total_assigned']} task(s) numbered.")
    if backup_info:
        ctx.out.line(f"  Backup archive: {backup_info['path']} ({_format_bytes(backup_info['size'])}, "
                     f"{backup_info['entries']} entries)")
    for s, info in sorted(res.get("projects", {}).items()):
        ctx.out.line(f"  {s}: +{len(info['assigned'])} assigned (already={info['already_numbered']}, "
                     f"reviews={info['skipped_reviews']}, last={info['last']})")


class Why(argparse.Action):
    """`--why TEXT` explains the `--option` right before it (kept as {place of that option: text})."""

    def __call__(self, parser, namespace, value, option_string=None):
        given = getattr(namespace, "option", None) or []
        if not given:
            parser.error("--why explains an answer: put it right after that answer's --option")
        namespace.why = {**(getattr(namespace, "why", None) or {}), len(given) - 1: value}


def register_task_commands(sub):
    n = sub.add_parser("new")
    n.add_argument("title")
    n.add_argument("--repo", default=".")
    n.add_argument("--status", default="in_progress", choices=ACTIVE + CLOSED)
    for f in ("owner", "workspace", "pane", "agent", "branch", "worktree", "base", "brief", "slug", "note"):
        n.add_argument(f"--{f}")
    n.add_argument("--parent", help="the id of the task this one was split from")
    n.add_argument("--depends-on", dest="depends_on", action="append", metavar="TASK_IDS",
                   help="prerequisite task IDs before this task is ready (comma-separated or repeated)")
    n.add_argument("--option", action="append", metavar="TEXT",
                   help="an answer the user can pick in the project view (repeat for more; with --status blocked)")
    n.add_argument("--why", action=Why, metavar="TEXT", help="one line that explains the --option right before it")
    n.add_argument("--recommend", action="store_true", help="the first --option is the one you recommend")
    n.add_argument("--plan", action="append", metavar="STEPS",
                   help="task plan steps separated by ';', '；' or newline (prefix [x]/[>]/[ ], optional @work/@review/@merge/@custom)")
    n.add_argument("--step", action="append", metavar="TEXT", help="one plan step (repeat for more)")
    n.add_argument("--outer-plan", action="append", metavar="STEPS", help="explicitly set outer task plan steps")
    n.add_argument("--subplan", action="append", metavar="STEPS", help="explicitly set worker subplan steps")
    n.add_argument("--no-review", action="store_true", help="skip plan-driven automatic review on --status review --commit")
    u = sub.add_parser("update")
    u.add_argument("id")
    for f in FIELDS + ["note"]:
        u.add_argument(f"--{f}", choices=ACTIVE + CLOSED if f == "status" else None)
    u.add_argument("--depends-on", dest="depends_on", action="append", metavar="TASK_IDS",
                   help="replace prerequisites (`a,b`), clear (`\"\"`), or incrementally add/remove (`+c`, `--depends-on=-a`)")
    u.add_argument("--option", action="append", metavar="TEXT",
                   help="an answer the user can pick in the project view (repeat for more; with --status blocked)")
    u.add_argument("--why", action=Why, metavar="TEXT", help="one line that explains the --option right before it")
    u.add_argument("--recommend", action="store_true", help="the first --option is the one you recommend")
    u.add_argument("--keep", action="store_true",
                   help="with --status merged: keep the worker, worktree and branch (no automatic retire); with "
                        "another closed status: keep the worker's terminal")
    u.add_argument("--send", action="store_true",
                   help="also deliver --note to the task's worker terminal ([from <your pane>] <note>); async by "
                        "default from a PM terminal so PM never blocks (pass --wait to block)")
    u.add_argument("--wait", action="store_true",
                   help="with --send: wait synchronously for hc send instead of queuing in the background")
    u.add_argument("--ask", action="store_true",
                   help="with --status blocked on a task the user has answered: ask a follow-up (a new question)")
    u.add_argument("--plan", action="append", metavar="STEPS",
                   help="update outer plan (PM) or inner subplan (task's worker) steps; pure worker subplan writes silently")
    u.add_argument("--step", action="append", metavar="TEXT", help="one plan/subplan step (repeat for more)")
    u.add_argument("--step-done", action="store_true",
                   help="check off the current active outer plan step and activate the next todo step (silent unless --note/--status given)")
    u.add_argument("--outer-plan", action="append", metavar="STEPS", help="explicitly replace outer task plan steps")
    u.add_argument("--subplan", action="append", metavar="STEPS", help="explicitly replace worker subplan steps")
    u.add_argument("--no-review", action="store_true", help="disable plan-driven automatic review on this task")


def register_guard_command(sub):
    g = sub.add_parser("guard", help="verify session/workspace identity and authorize a role action (exit 2: refused)")
    g.add_argument("--repo", default=".")
    g.add_argument("--action", choices=["read", "coordinate", "implement"], default="read")


def register_conversation_command(sub):
    cv = sub.add_parser("conversation", help="print the end of the project's conversation log")
    cv.add_argument("--repo", default=".")
    cv.add_argument("--last", type=int, default=20, help="how many events (default 20)")
    cv.add_argument("--type", help="only these kinds, comma-separated: user,pm,agent,thread,decision")
    cv.add_argument("--width", type=int, default=300, help="clip each text to this many characters (0: whole text)")


def register_backfill_numbers_command(sub):
    bf = sub.add_parser("backfill-numbers", help="backfill per-project chronological task numbers for existing tasks")
    bf.add_argument("--project", help="only this project (slug, PM name, project name or folder)")
    bf.add_argument("--dry-run", action="store_true", help="show planned numbering without modifying files")
    bf.add_argument("--backup-dir", help="directory for pre-backfill backup archive")
    bf.add_argument("--no-backup", action="store_true", help="skip creating pre-backfill backup tarball")
    bf.add_argument("--json", action="store_true", help="print plan or result as JSON")
