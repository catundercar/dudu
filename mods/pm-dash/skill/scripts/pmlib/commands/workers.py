"""Worker messaging, wait, escalation, reattach, tab and retirement commands (`send`, `_drain-endpoint`,
`_deliver-ready`, `wait`, `escalate`, `reattach`, `retab`, `retire`, `idle-workers`, `close-worker`, `codex-cmd`,
`print_plan`). Layer 4."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from ..context import Context
from ..errors import IdentityError, PmError, StoreError, WaitOutcome
from ..helpers.service import Helpers
from ..workers.codex_pool import apply_codex_pool_for, hold_pool_lock, pool_started
from ..workers.service import EscalateRequest, REPORTED, Workers
from ..workers.wait import wait_for_report_events_for, wait_for_report_for, waiting_on_for
from . import ledger
from .emit import exit_with


def _emit_pm_error(ctx: Any, err: PmError) -> None:
    if isinstance(err, (StoreError, IdentityError)):
        raise err
    if isinstance(err, WaitOutcome) or err.stream == "stdout":
        if str(err):
            ctx.out.line(str(err))
        sys.exit(err.code)
    exit_with(ctx, err)


# --- Layer 4 legacy shims for Stage 1-5 callers & test_pm*.py ---


def apply_codex_pool(a: Any, repo: str | Path, role: str = "worker", hold: bool = True, *, ctx: Context | None = None) -> Any:
    """Layer 4 wrapper over `apply_codex_pool_for`: prints stderr warnings and exits on `PmError`."""
    ctx = ctx or Context.from_env()
    try:
        spec, warning, _ = apply_codex_pool_for(
            ctx, a, repo, role=role, hold=hold,
            on_hold=hold_pool_lock if hold else None,
            on_release=pool_started,
        )
    except PmError as err:
        _emit_pm_error(ctx, err)
    if warning:
        ctx.out.err_line(warning)
    return spec


def send_back(task: Any, text: str, *, wait: bool = False) -> None:
    """Legacy Layer 4 wrapper over `Workers.send_back`."""
    ctx = Context.from_env()
    try:
        res = Workers(ctx).send_back(task, text, wait=wait)
    except PmError as err:
        _emit_pm_error(ctx, err)
    ctx.out.line(res.message)


def retire_workspace(task_id: str, *, force: bool = False, keep_active: bool = False, ctx: Any = None) -> None:
    """Layer 4 wrapper over `Workers.retire`."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Workers(ctx).retire(task_id, force=force, keep_active=keep_active)
    except PmError as err:
        _emit_pm_error(ctx, err)
    for line in res.lines:
        ctx.out.line(line)


def adopt_task(a: Any, *, ctx: Any = None) -> Any:
    """Layer 4 wrapper over `Workers.adopt`."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Workers(ctx).adopt(a.candidate, confirmed=bool(getattr(a, "confirmed", False)))
    except PmError as err:
        _emit_pm_error(ctx, err)
    a.candidate = res.task_id
    for line in res.lines:
        ctx.out.line(line)
    if res.asked:
        return res.task_id
    return None


def wait_for_report(a: Any) -> None:
    """Legacy Layer 4 wrapper over `wait_for_report_for`."""
    ctx = Context.from_env()
    try:
        res = wait_for_report_for(ctx, a.id, timeout=a.timeout)
    except PmError as err:
        _emit_pm_error(ctx, err)
    for line in res.lines:
        ctx.out.line(line)


_DEFAULT_WAIT_FOR_REPORT = wait_for_report


def wait_for_report_events(a: Any, changes: Any, task: Any) -> None:
    """Legacy Layer 4 wrapper over `wait_for_report_events_for`."""
    ctx = Context.from_env()
    try:
        res = wait_for_report_events_for(ctx, a.id, changes, task, timeout=a.timeout)
    except PmError as err:
        _emit_pm_error(ctx, err)
    for line in res.lines:
        ctx.out.line(line)


# --- CLI Command Handlers ---


def cmd__drain_endpoint(a: Any, ctx: Any = None) -> None:
    """Internal detached drain of a herdr-core terminal's mailbox: types its queued sends under the terminal's typist
    lease and runs each send's reactions (round handed; or the fallback / failure note that wakes the PM)."""
    ctx = Context.from_env() if ctx is None else ctx
    Workers(ctx).drain_sends(a.term, list(getattr(a, "env", None) or []), timeout=a.timeout)


def cmd__deliver_ready(a: Any, ctx: Any = None) -> None:
    """Internal background worker for async `send_when_ready` (dispatch --async / helper start --async)."""
    path = Path(a.file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    finally:
        if getattr(a, "unlink", False):
            path.unlink(missing_ok=True)
    ctx = Context.from_env() if ctx is None else ctx
    svc = Workers(ctx)
    repo = a.repo or ""
    if a.helper_owner_kind and a.helper_owner_id and a.helper_slug:
        Helpers(ctx).deliver_ready(
            a.term, text,
            kind=a.kind or "",
            trust=a.trust or "",
            strict=bool(a.strict),
            stop_on_exit=bool(a.stop_on_exit),
            repo=repo,
            owner_kind=a.helper_owner_kind,
            owner_id=a.helper_owner_id,
            slug=a.helper_slug,
            name=a.helper_name or "",
        )
        return
    svc.deliver_ready_for_task(
        a.term, text,
        kind=a.kind or "",
        trust=a.trust or "",
        strict=bool(a.strict),
        stop_on_exit=bool(a.stop_on_exit),
        task_id=a.task or "",
        repo=repo,
    )


def cmd_send(a: Any, ctx: Any = None) -> None:
    """Send a message to a task's worker or an hc terminal asynchronously by default (never blocks PM)."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Workers(ctx).send(
            a.target,
            getattr(a, "message", None),
            file_path=getattr(a, "file", None),
            task_id=getattr(a, "task", None),
            repo=getattr(a, "repo", ".") or ".",
            timeout=a.timeout,
            wait=bool(getattr(a, "wait", False)),
            as_user=bool(getattr(a, "as_user", False)),
            idempotency_key=getattr(a, "idempotency_key", None) or "",
        )
    except PmError as err:
        _emit_pm_error(ctx, err)
    ctx.out.line(res.message)


def cmd_codex_cmd(a: Any, ctx: Any = None) -> None:
    """Print the codex launch command from the PM's codex settings or codex profile pool."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Workers(ctx).codex_cmd(
            project=a.project,
            repo=a.repo,
            model=a.model,
            effort=a.effort,
            codex_profile=a.codex_profile,
        )
    except PmError as err:
        _emit_pm_error(ctx, err)
    for line in res.stderr_lines:
        ctx.out.err_line(line)
    ctx.out.line(res.command)
    if res.fell_back:
        sys.exit(3)


def print_plan(
    a: Any,
    repo: str | Path,
    what: str,
    task_id: str | None,
    cwd: str | Path,
    tab: str,
    parent: str = "",
    reads: Any = (),
    extra: Any = (),
    asks: bool = False,
    *,
    ctx: Any = None,
) -> None:
    """--dry-run: what would be started; nothing is started, made or written to the ledger."""
    ctx = Context.from_env() if ctx is None else ctx
    outer_steps, _, _ = ledger.plan_input_from_args(a, is_new=True, ctx=ctx)
    plan = Workers(ctx).build_dry_run_plan(
        a, repo, what, task_id, cwd, tab,
        parent=parent or "",
        reads=reads,
        extra=extra,
        asks=asks,
        outer_steps=outer_steps,
        no_review=bool(getattr(a, "no_review", False)),
    )
    ctx.out.json(plan, indent=1)


def cmd_close_worker(a: Any, ctx: Any = None) -> None:
    """(started by update) end a worker's terminal once it has been idle for a.quiet seconds."""
    ctx = Context.from_env() if ctx is None else ctx
    statuses = [x for x in (getattr(a, "while_", None) or "").split(",") if x]
    try:
        Workers(ctx).close_worker_loop(
            a.terminal, a.task,
            quiet=a.quiet,
            timeout=a.timeout,
            statuses=statuses,
            retire=bool(getattr(a, "retire", False)),
        )
    except PmError as err:
        _emit_pm_error(ctx, err)


def cmd_idle_workers(a: Any, ctx: Any = None) -> None:
    """List (and optionally close) this project's idle/done worker terminals."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Workers(ctx).idle_workers(
            repo=a.repo,
            minutes=a.minutes,
            exited=bool(a.exited),
            close=a.close,
        )
    except PmError as err:
        _emit_pm_error(ctx, err)
    if a.json:
        ctx.out.json(res.rows, indent=1)
    else:
        for w in res.rows:
            rev_mark = f"  (review: {w['active_review']})" if w.get("active_review") else ""
            ctx.out.line(
                f"{w['terminal']:6} {w['state']:9} {w['idle_minutes']:>4}m  {w['task']} [{w['task_status']}]  "
                f"{w['name']}{rev_mark}"
            )
        if not res.rows:
            ctx.out.line(ctx.config.tr(
                f"no worker idle for {res.minutes} minutes or more",
                f"没有空闲超过 {res.minutes} 分钟的 worker",
            ))
    for line in res.closed_lines:
        ctx.out.line(line)


def cmd_wait(a: Any, ctx: Any = None) -> None:
    """`pm.py wait`: wait for a worker's report in the ledger."""
    ctx = Context.from_env() if ctx is None else ctx
    svc = Workers(ctx)
    if wait_for_report is not _DEFAULT_WAIT_FOR_REPORT:
        try:
            task = svc._ledger.load(a.id).raw
            a.id = task["id"]
            pm_target = svc.ctx.store.task_project_slug(task) or task.get("repo")
            rec = svc._projects.app_pm(pm_target) if pm_target else None
            if ctx.pane and rec and rec.get("pane") == ctx.pane:
                raise WaitOutcome(
                    ctx.config.tr(
                        f"{a.id}: not waited for. In the desktop app the worker's report, or word that it stopped, is "
                        "delivered to you as a message of its own once you are idle; there is nothing to wait for.",
                        f"{a.id}：不用等。在桌面 app 里，worker 的汇报（或它停了的消息）会在你空闲时作为一条消息送到；没有要等的。",
                    ),
                    code=4,
                    stream="stdout",
                )
            with waiting_on_for(ctx, a.id):
                wait_for_report(a)
        except PmError as err:
            _emit_pm_error(ctx, err)
        return
    try:
        res = svc.wait(a.id, timeout=a.timeout)
    except PmError as err:
        _emit_pm_error(ctx, err)
    a.id = res.task_id
    for line in res.lines:
        ctx.out.line(line)


def cmd_retab(a: Any, ctx: Any = None) -> None:
    """Rename a worker's tab to <terminal>-<BUG>-<short> and record that name as its task's agent."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Workers(ctx).retab(a.target, tab=a.tab, bug=a.bug or "", dry_run=bool(a.dry_run))
    except PmError as err:
        _emit_pm_error(ctx, err)
    if res.dry_run_payload is not None:
        ctx.out.json(res.dry_run_payload)
        return
    for line in res.lines:
        ctx.out.line(line)


def cmd_retire(a: Any, ctx: Any = None) -> None:
    retire_workspace(a.id, force=bool(getattr(a, "force", False)), ctx=ctx)


def cmd_escalate(a: Any, ctx: Any = None) -> Any:
    """Run a task again on a stronger profile in the same worktree and branch."""
    ctx = Context.from_env() if ctx is None else ctx
    req = EscalateRequest(
        task_id=a.id,
        profile=a.profile,
        why=a.why,
        advisor=a.advisor,
        name=a.name,
        confirmed=bool(a.confirmed),
        tab=getattr(a, "tab", None),
        bug=getattr(a, "bug", "") or "",
        codex_profile=getattr(a, "codex_profile", None),
        dry_run=bool(getattr(a, "dry_run", False)),
    )
    try:
        res = Workers(ctx).escalate(req)
    except PmError as err:
        _emit_pm_error(ctx, err)
    a.id = res.task_id
    for line in res.stderr_lines:
        ctx.out.err_line(line)
    if res.dry_run_plan is not None:
        ctx.out.json(res.dry_run_plan, indent=1)
        return None
    for line in res.lines:
        ctx.out.line(line)
    if res.asked:
        return res.task_id
    if res.unsent_error:
        sys.exit(res.unsent_error)
    return None


def cmd_reattach(a: Any, ctx: Any = None) -> None:
    """Bring back the agent of a task whose terminal is gone."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Workers(ctx).reattach(a.id)
    except PmError as err:
        _emit_pm_error(ctx, err)
    a.id = res.task_id
    for line in res.lines:
        ctx.out.line(line)


def register_codex_cmd_command(sub):
    cc = sub.add_parser("codex-cmd", help="print the codex launch command from the PM's codex settings, else config.json")
    cc.add_argument("--project", help="PM whose settings to use (default: this pane's PM, else the one for --repo)")
    cc.add_argument("--repo", default=".")
    cc.add_argument("--model", help="default: config.json codex.model with codex.profiles, else gpt-6-astra")
    cc.add_argument("--effort", default="high")
    cc.add_argument("--codex-profile", help="a profile of config.json codex.profiles (default: the pool's pick)")


def register_wait_command(sub):
    w = sub.add_parser("wait", help="wait for a worker's report in the ledger (exit 2: timeout, 3: stopped unreported)")
    w.add_argument("id")
    w.add_argument("--timeout", type=int, default=3600, help="seconds (default 3600)")


def register_send_commands(sub):
    sn = sub.add_parser("send", help="deliver a message to a task's worker or hc terminal asynchronously (never blocks PM)")
    sn.add_argument("target", help="task id or herdr-core terminal (t20, hc:t20)")
    sn.add_argument("message", nargs="?", help="message text (or pass --file)")
    sn.add_argument("--file", help="read message text from this file")
    sn.add_argument("--task", help="associate delivery with this task id (when target is a terminal)")
    sn.add_argument("--repo", default=".", help="project folder (default: .)")
    sn.add_argument("--timeout", type=int, default=180, help="hc send timeout in seconds (default 180)")
    sn.add_argument("--wait", action="store_true", help="wait synchronously instead of queuing in the background")
    sn.add_argument("--as-user", action="store_true",
                    help="the user's own words (the app's thread box / agent window): typed as written, no [from ...]")
    sn.add_argument("--idempotency-key", help="a retry of the same send passes the same key: it is typed once")
    de_int = sub.add_parser("_drain-endpoint", help=argparse.SUPPRESS)
    de_int.add_argument("term")
    de_int.add_argument("--env", action="append", default=[])
    de_int.add_argument("--timeout", type=int, default=180)
    dr_int = sub.add_parser("_deliver-ready", help=argparse.SUPPRESS)
    dr_int.add_argument("term")
    dr_int.add_argument("--file", required=True)
    dr_int.add_argument("--unlink", action="store_true")
    dr_int.add_argument("--kind", default="")
    dr_int.add_argument("--trust", default="")
    dr_int.add_argument("--strict", action="store_true")
    dr_int.add_argument("--stop-on-exit", action="store_true")
    dr_int.add_argument("--task", default="")
    dr_int.add_argument("--repo", default="")
    dr_int.add_argument("--helper-owner-kind", default="")
    dr_int.add_argument("--helper-owner-id", default="")
    dr_int.add_argument("--helper-slug", default="")
    dr_int.add_argument("--helper-name", default="")


def register_worker_lifecycle_commands(sub):
    es = sub.add_parser("escalate", help="run a task again on a stronger profile: a fresh worker in the same worktree "
                                         "and branch, given the review findings and the brief; the old worker ends")
    es.add_argument("id")
    es.add_argument("--profile", help="the profile to run on (default: one step up: light, standard, hard, deep; "
                                    "with \"fable\": false hard is the top)")
    es.add_argument("--why", help="why it is escalated, a few words for the ledger and the new worker")
    es.add_argument("--advisor", help="advisor model (default: the profile's); none: without")
    es.add_argument("--name", help="the new worker's terminal name (default: <worker>-<profile>)")
    es.add_argument("--confirmed", action="store_true",
                    help="the user agreed (a Fable worker, such as deep's, asks first: without this flag none starts)")
    es.add_argument("--tab", help="the tab's short name, with tabs.new_tab (default: the task's)")
    es.add_argument("--bug", help="the BUG number the tab shows (default: in --tab, else the task's)")
    es.add_argument("--codex-profile", help="codex profile, when the profile runs codex (default: the pool's pick)")
    es.add_argument("--dry-run", action="store_true", help="print what would start as JSON; stop and start nothing")
    ra = sub.add_parser("reattach", help="bring back the agent of a task whose terminal is gone: resume its session, "
                                         "else start one with the task's context")
    ra.add_argument("id")
    rt = sub.add_parser("retab", help="rename a worker's tab, and its ledger agent, to <terminal>-<BUG>-<short>: "
                                      "a reviewer given another task to review, a task renamed")
    rt.add_argument("target", help="a task id, or a herdr-core terminal (t5m, hc:t5m)")
    rt.add_argument("--tab", help="the new short name (default: the task's); a BUG number in it is used")
    rt.add_argument("--bug", help="the BUG number (default: in --tab; without --tab, the task's)")
    rt.add_argument("--dry-run", action="store_true", help="print the new name; rename and write nothing")
    r = sub.add_parser("retire")
    r.add_argument("id")
    r.add_argument("--force", action="store_true")
    iw = sub.add_parser("idle-workers", help="this project's worker terminals idle or done for --minutes; "
                                             "--close ends them")
    iw.add_argument("--repo", default=".")
    iw.add_argument("--minutes", type=int, help="default: config.json workers.idle_minutes, else 30")
    iw.add_argument("--close", nargs="*", metavar="TERMINAL", help="end the listed terminals (or only those named)")
    iw.add_argument("--exited", action="store_true", help="finished terminals too (hc keeps them hidden)")
    iw.add_argument("--json", action="store_true")
    cw = sub.add_parser("close-worker", help="(started by update) end a worker terminal once it has been idle")
    cw.add_argument("terminal")
    cw.add_argument("--task", required=True)
    cw.add_argument("--quiet", type=int, default=20, help="seconds idle before it is ended")
    cw.add_argument("--timeout", type=int, default=7200)
    cw.add_argument("--while", dest="while_", default="",
                    help="statuses the task must still be in, comma-separated (default: any)")
    cw.add_argument("--retire", action="store_true",
                    help="also run retire_workspace after ending the terminal (for self-landing workers)")
