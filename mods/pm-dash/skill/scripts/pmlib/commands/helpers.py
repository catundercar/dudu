"""Temporary read-only and delegated-execution sub-agent commands (`helper start|done|wait|ls|stop`). Layer 4.

Thin CLI adapter over `Helpers(ctx)` in `pmlib/helpers/service.py`.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from ..context import Context
from ..errors import PmError
from ..helpers.service import HelperStartRequest, Helpers, helper_brief  # noqa: F401
from ..reports import LocalFacts, ReportClient, helper_done_report
from .emit import exit_with


def _emit_helper_error(ctx: Any, err: PmError) -> None:
    exit_with(ctx, err)


def cmd_helper_start(a: Any, ctx: Any = None) -> dict[str, str] | None:
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Helpers(ctx).start(HelperStartRequest.from_args(a))
    except PmError as err:
        _emit_helper_error(ctx, err)
    for line in res.stderr_lines:
        ctx.out.err_line(line)
    if res.dry_run_plan is not None:
        ctx.out.line(json.dumps(res.dry_run_plan, ensure_ascii=False, indent=1))
        return None
    ctx.out.line(res.line)
    return {"name": res.name, "terminal": res.terminal, "result": res.result}


def cmd_helper_done(a: Any, ctx: Any = None) -> None:
    """Mark a helper finished and deliver/notify its owner."""
    ctx = Context.from_env() if ctx is None else ctx
    from_stdin = bool(getattr(a, "stdin", False))
    text = getattr(a, "text", None)
    stdin_text = sys.stdin.read() if (from_stdin and text is None) else None
    try:
        # A `report.helper_done` envelope, applied here (`Helpers.done`: once done, a repeat only says so).
        env = helper_done_report(
            ctx, repo=getattr(a, "repo", None) or ".", task=getattr(a, "task", None),
            name=getattr(a, "name", None), text=text, summary=getattr(a, "summary", None),
            pm=bool(getattr(a, "pm", False)),
        )
        got = ReportClient(ctx).submit(env, local=LocalFacts(stdin_text=stdin_text, from_stdin=from_stdin))
    except PmError as err:
        _emit_helper_error(ctx, err)
    ctx.out.line(str(got.result.get("line") or ""))


def cmd_helper_wait(a: Any, ctx: Any = None) -> None:
    """Wait for one or more helpers (event-driven via ChangeWaiter on owner ledger + hc events)."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Helpers(ctx).wait(
            list(getattr(a, "names", None) or []),
            wait_any=bool(getattr(a, "any", False)),
            timeout=getattr(a, "timeout", None),
            keep=bool(getattr(a, "keep", False)),
            as_json=bool(getattr(a, "json", False)),
            task=getattr(a, "task", None),
            pm=bool(getattr(a, "pm", False)),
            repo=getattr(a, "repo", None) or ".",
        )
    except PmError as err:
        _emit_helper_error(ctx, err)
    for line in res.lines:
        ctx.out.line(line)
    if res.stderr_line:
        ctx.out.err_line(res.stderr_line)
    if res.exit_code:
        sys.exit(res.exit_code)


def cmd_helper_ls(a: Any, ctx: Any = None) -> None:
    """List helpers for the caller or the whole project, reconciling timeouts/exited terminals first."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Helpers(ctx).ls(
            show_all=bool(getattr(a, "all", False)),
            active_only=bool(getattr(a, "active", False)),
            task=getattr(a, "task", None),
            pm=bool(getattr(a, "pm", False)),
            repo=getattr(a, "repo", None) or ".",
        )
    except PmError as err:
        _emit_helper_error(ctx, err)
    if getattr(a, "json", False):
        ctx.out.line(json.dumps(res.entries, ensure_ascii=False, indent=2))
        return
    for line in res.lines:
        ctx.out.line(line)


def cmd_helper_stop(a: Any, ctx: Any = None) -> None:
    """Stop one, several, or all running helpers."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = Helpers(ctx).stop(
            list(getattr(a, "names", None) or []),
            stop_all=bool(getattr(a, "all", False)),
            remove=bool(getattr(a, "rm", False)),
            task=getattr(a, "task", None),
            pm=bool(getattr(a, "pm", False)),
            repo=getattr(a, "repo", None) or ".",
        )
    except PmError as err:
        _emit_helper_error(ctx, err)
    for line in res.lines:
        ctx.out.line(line)


def cmd_helper(a: Any, ctx: Any = None) -> Any:
    dispatch = {
        "start": cmd_helper_start,
        "done": cmd_helper_done,
        "wait": cmd_helper_wait,
        "ls": cmd_helper_ls,
        "stop": cmd_helper_stop,
    }
    fn = dispatch.get(a.helper_cmd)
    if not fn:
        sys.exit(f"unknown helper command: {a.helper_cmd}")
    return fn(a, ctx=ctx)


def register_helper_commands(sub: Any) -> None:
    hl = sub.add_parser("helper", help="start, monitor and collect temporary read-only helper sub-agents")
    helper_cmds = hl.add_subparsers(dest="helper_cmd", required=True)
    hs = helper_cmds.add_parser("start", help="start a temporary read-only helper under this terminal")
    hs.add_argument("prompt", nargs="?", help="the question or read-only task for the helper")
    hs.add_argument("--name", help="short helper name (default: derived from the prompt)")
    hs.add_argument("--brief", help="read instructions from this file (combined with positional prompt if both given)")
    hs.add_argument("--profile", help="profile name (default: config helpers.profile, else opus/neon if configured, else light)")
    hs.add_argument("--kind", help="agent program (overrides profile)")
    hs.add_argument("--model", help="model (overrides profile)")
    hs.add_argument("--effort", help="effort (overrides profile)")
    hs.add_argument("--advisor", help="advisor model (overrides profile; none: omit)")
    hs.add_argument("--codex-profile", help="codex profile for a codex helper (config.json codex.profiles)")
    hs.add_argument("--timeout", type=int, help="timeout in seconds (default: config helpers.timeout, else 1800)")
    hs.add_argument("--cwd", help="working directory for the helper (default: caller's cwd or task worktree)")
    hs.add_argument("--task", help="record under this active task id (for workers without a task= label)")
    hs.add_argument("--repo", default=".", help="project folder (default: .)")
    hs.add_argument("--confirmed", action="store_true", help="user confirmed a Fable/deep helper")
    hs.add_argument("--exec", dest="exec_mode", action="store_true",
                    help="PM-only execution helper (install, approved land, triage); workers may start read-only helpers only")
    hs.add_argument("--async", dest="async_", action="store_true",
                    help="return immediately after starting the helper terminal and deliver its brief in the background")
    hs.add_argument("--for-task", dest="for_task", help="associate this helper with a task id (e.g. for approve/triage)")
    hs.add_argument("--dry-run", action="store_true", help="print plan as JSON; start and record nothing")
    hd = helper_cmds.add_parser("done", help="mark a helper complete and deliver/notify its owner")
    hd.add_argument("name", nargs="?", help="helper name (default: inferred from this helper terminal)")
    hd.add_argument("--text", help="write this conclusion text to the result file")
    hd.add_argument("--stdin", action="store_true", help="read conclusion text from stdin and write to the result file")
    hd.add_argument("--summary", help="short one-line summary for notification and log")
    hd.add_argument("--task", help="explicit task owner (when finalizing externally)")
    hd.add_argument("--pm", action="store_true", help="explicit PM owner (when finalizing externally)")
    hd.add_argument("--repo", default=".", help="project folder (default: .)")
    hw = helper_cmds.add_parser("wait", help="wait for helper(s) to finish and print their conclusions "
                                             "(exit 2: wait timeout, 3: helper timed out/exited/blocked)")
    hw.add_argument("names", nargs="*", help="helper name(s) to wait on (default: all running helpers of caller)")
    hw_mode = hw.add_mutually_exclusive_group()
    hw_mode.add_argument("--all", action="store_true", help="wait until all target helpers finish (default)")
    hw_mode.add_argument("--any", action="store_true", help="return as soon as any target helper finishes or blocks")
    hw.add_argument("--timeout", type=int, help="wait timeout in seconds")
    hw.add_argument("--keep", action="store_true", help="leave finished helper terminals running instead of hc kill")
    hw.add_argument("--json", action="store_true", help="print results as JSON")
    hw.add_argument("--task", help="wait on this task's helpers")
    hw.add_argument("--pm", action="store_true", help="wait on this project PM's helpers")
    hw.add_argument("--repo", default=".", help="project folder (default: .)")
    hls = helper_cmds.add_parser("ls", help="list helpers and concurrency quota")
    hls.add_argument("--all", action="store_true", help="list helpers across the entire project (PM + all tasks)")
    hls.add_argument("--active", action="store_true", help="show only running helpers")
    hls.add_argument("--task", help="list helpers of this task")
    hls.add_argument("--pm", action="store_true", help="list PM's own helpers")
    hls.add_argument("--repo", default=".", help="project folder (default: .)")
    hls.add_argument("--json", action="store_true", help="output as JSON")
    hst = helper_cmds.add_parser("stop", help="stop running helper(s)")
    hst.add_argument("names", nargs="*", help="helper name(s) or hc terminal address(es) to stop")
    hst.add_argument("--all", action="store_true", help="stop all running helpers of this owner")
    hst.add_argument("--rm", action="store_true", help="also remove the hc terminal (hc rm)")
    hst.add_argument("--task", help="stop helpers of this task")
    hst.add_argument("--pm", action="store_true", help="stop PM's helpers")
    hst.add_argument("--repo", default=".", help="project folder (default: .)")
