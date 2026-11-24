"""Worker dispatch commands (`dispatch`, `register_worker`, `ask_first`, `dispatch_hc`). Layer 4."""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from ..agents.profiles import WorkerSpec
from ..context import Context
from ..errors import IdentityError, PmError, StoreError
from ..workers.service import DispatchRequest, Workers, _parse_new_plan
from .emit import exit_with


def _accepts_kwarg(fn: Any, name: str) -> bool:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return (
        name in sig.parameters
        or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    )


def _request_from_args(a: Any) -> DispatchRequest:
    return DispatchRequest(
        title=getattr(a, "title", None),
        repo=getattr(a, "repo", ".") or ".",
        branch=getattr(a, "branch", None),
        label=getattr(a, "label", None),
        path=getattr(a, "path", None),
        brief=getattr(a, "brief", None),
        name=getattr(a, "name", None),
        task=getattr(a, "task", None),
        here=bool(getattr(a, "here", False)),
        tab=getattr(a, "tab", None),
        bug=getattr(a, "bug", "") or "",
        codex_profile=getattr(a, "codex_profile", None),
        dry_run=bool(getattr(a, "dry_run", False)),
        base=getattr(a, "base", None),
        prep=getattr(a, "prep", None),
        parent=getattr(a, "parent", None),
        profile=getattr(a, "profile", None),
        kind=getattr(a, "kind", None),
        model=getattr(a, "model", None),
        effort=getattr(a, "effort", None),
        advisor=getattr(a, "advisor", None),
        confirmed=bool(getattr(a, "confirmed", False)),
        plan=getattr(a, "plan", None),
        step=getattr(a, "step", None),
        outer_plan=getattr(a, "outer_plan", None),
        subplan=getattr(a, "subplan", None),
        no_review=bool(getattr(a, "no_review", False)),
        async_=bool(getattr(a, "async_", False)),
    )


def dispatch_hc(a: Any, repo: str, brief: str, held: dict[str, Any] | None = None, *, ctx: Any = None) -> None:
    """Layer 4 wrapper over `Workers._dispatch_hc`."""
    ctx = Context.from_env() if ctx is None else ctx
    req = _request_from_args(a)
    spec = WorkerSpec.from_args(a)
    try:
        outer_steps, outer_explicit, sub_steps = _parse_new_plan(ctx, req.plan, req.step, req.outer_plan, req.subplan)
        res = Workers(ctx)._dispatch_hc(
            req, spec, repo, brief, held,
            outer_steps=outer_steps, outer_explicit=outer_explicit, sub_steps=sub_steps,
            stderr_lines=[],
        )
    except (StoreError, IdentityError):
        raise
    except PmError as err:
        if isinstance(err.payload, dict):
            for line in err.payload.get("emitted_lines") or ():
                ctx.out.line(line)
        exit_with(ctx, err)
    for line in res.stderr_lines:
        ctx.out.err_line(line)
    for line in res.lines:
        ctx.out.line(line)


_DEFAULT_DISPATCH_HC = dispatch_hc


def cmd_dispatch(a: Any, ctx: Any = None) -> Any:
    ctx = Context.from_env() if ctx is None else ctx
    req = _request_from_args(a)
    svc = Workers(ctx)
    if dispatch_hc is not _DEFAULT_DISPATCH_HC and ctx.pane.startswith("hc:") and not req.dry_run:
        # Honor test patches on `pm.dispatch_hc` (e.g. test_pm.py:10049) while running the exact validation path.
        orig_dispatch_hc = svc._dispatch_hc

        def _patched_hc(r, spec, repo, brief, held, *, stderr_lines, **_kw):
            for line in stderr_lines:
                ctx.out.err_line(line)
            a.title, a.parent, a.branch, a.brief = r.title, r.parent, r.branch, r.brief
            a.bug, a.label, a.name = r.bug, r.label, r.name
            spec.apply_to(a)
            a.provider, a.pool_said, a.pool_before, a.preapproved = (
                spec.provider, spec.pool_said, spec.pool_before, spec.preapproved
            )
            if _accepts_kwarg(dispatch_hc, "ctx"):
                dispatch_hc(a, repo, brief, held, ctx=ctx)
            else:
                dispatch_hc(a, repo, brief, held)
            return None

        svc._dispatch_hc = _patched_hc  # type: ignore[method-assign]
        try:
            res = svc.dispatch(req)
        except (StoreError, IdentityError):
            raise
        except PmError as err:
            exit_with(ctx, err)
        finally:
            svc._dispatch_hc = orig_dispatch_hc  # type: ignore[method-assign]
        if res is None:
            return None
        for line in res.stderr_lines:
            ctx.out.err_line(line)
        for line in res.lines:
            ctx.out.line(line)
        return res.task_id if res.asked else None

    try:
        res = svc.dispatch(req)
    except (StoreError, IdentityError):
        raise
    except PmError as err:
        if isinstance(err.payload, dict):
            for line in err.payload.get("emitted_lines") or ():
                ctx.out.line(line)
        exit_with(ctx, err)
    for line in res.stderr_lines:
        ctx.out.err_line(line)
    if res.dry_run_plan is not None:
        ctx.out.json(res.dry_run_plan, indent=1)
        return None
    for line in res.lines:
        ctx.out.line(line)
    if res.asked:
        return res.task_id
    return None


def register_dispatch_command(sub):
    d = sub.add_parser("dispatch")
    d.add_argument("title", nargs="?", help="the task's title (default with --task: that task's)")
    d.add_argument("--repo", default=".")
    d.add_argument("--branch", help="the worktree's new branch (not with --here)")
    d.add_argument("--label", help="the worktree's label (default: from the task id or title)")
    d.add_argument("--path", help="worktree path (default: herdr's choice; in the desktop app ~/.herdr/worktrees/…); "
                                  "with --here: the folder to work in (default: the project's checkout)")
    d.add_argument("--brief", help="brief file (optional with --task when the ledger task already records one)")
    d.add_argument("--name", help="the terminal's name, 1-32 of a-z 0-9 - _ (default: from --label)")
    d.add_argument("--task", help="take up this open ledger task (registered with `new`) instead of a new one")
    d.add_argument("--here", action="store_true", help="no worktree: the worker works in the project's checkout "
                                                       "(desktop app)")
    d.add_argument("--tab", help="the tab's short name, with config.json tabs.new_tab (default: the title)")
    d.add_argument("--bug", help="the BUG number the tab shows (default: config.json tabs.bug_pattern in --tab, "
                                 "else in the title)")
    d.add_argument("--codex-profile", help="codex profile to run on (config.json codex.profiles; default: the "
                                           "first one under its max; all full: codex.fallback)")
    d.add_argument("--dry-run", action="store_true", help="print what would start as JSON; start, make and "
                                                          "register nothing")
    d.add_argument("--base")
    d.add_argument("--prep")
    d.add_argument("--parent", help="the id of the task this one was split from")
    d.add_argument("--profile", help="light, standard, hard or deep, or one from config.json profiles "
                                     "(default: config.json worker.profile, else none); --kind/--model/--effort win")
    d.add_argument("--kind", help="worker program (default: the profile's, else config.json, else codex)")
    d.add_argument("--model", help="default: the profile's, else config.json, else the program's own")
    d.add_argument("--effort", help="default: the profile's, else config.json, else the program's own")
    d.add_argument("--advisor", help="advisor model for programs that take one, such as claude (default: the "
                                     "profile's); none: without")
    d.add_argument("--confirmed", action="store_true",
                   help="the user agreed to this profile (deep asks first: without this flag no worker starts)")
    d.add_argument("--plan", action="append", metavar="STEPS",
                   help="outer task plan steps tailored to the user's request (separated by ';', '；' or newline)")
    d.add_argument("--step", action="append", metavar="TEXT", help="one outer plan step (repeat for more)")
    d.add_argument("--outer-plan", action="append", metavar="STEPS", help="explicitly set outer task plan steps")
    d.add_argument("--no-review", action="store_true", help="skip plan-driven automatic review when worker reports --commit")
    d.add_argument("--async", dest="async_", action="store_true",
                   help="return immediately after starting the worker terminal and deliver its brief in the background")
