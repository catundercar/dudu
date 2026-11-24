"""Command-line assembly, startup registrations and entry point (`build_parser`, `main`, `COMMANDS`). Layer 4.

Every command, view and hook module is imported eagerly at startup so a long-running process (deliverer, seat) stays
on one version from start to end rather than importing new modules after an install replaces files under it.
"""
import argparse

from . import caller, context, discord, hooks
from .commands import (
    dispatch as dispatch_cmd,
    events as events_cmd,
    helpers as helpers_cmd,
    ledger as ledger_cmd,
    manager as manager_cmd,
    memory as memory_cmd,
    project as project_cmd,
    review as review_cmd,
    workers as workers_cmd,
)
from .errors import IdentityError, PmError, StoreError
from .events import agy_watch, deliver as events_deliver, deps_watch  # noqa: F401
from .helpers import watch as helpers_watch  # noqa: F401
from .ledger import board as ledger_board, ledger as ledger_mod  # noqa: F401
from .manager import seat as manager_seat  # noqa: F401
from .project import project as project_mod  # noqa: F401
from .views import (
    dash as dash_view,
    project as project_view,  # noqa: F401
    state as state_view,
    status as status_view,
)


COMMANDS = {
    "new": (ledger_cmd, "cmd_new"),
    "update": (ledger_cmd, "cmd_update"),
    "log": (status_view, "cmd_log"),
    "show": (status_view, "cmd_show"),
    "board": (status_view, "cmd_board"),
    "status": (status_view, "cmd_status"),
    "diff": (status_view, "cmd_diff"),
    "find": (status_view, "cmd_find"),
    "claim": (manager_cmd, "cmd_claim"),
    "guard": (ledger_cmd, "cmd_guard"),
    "launch": (manager_cmd, "cmd_launch"),
    "start": (manager_cmd, "cmd_start"),
    "archive": (manager_cmd, "cmd_archive"),
    "restore": (manager_cmd, "cmd_restore"),
    "deliver": (events_cmd, "cmd_deliver"),
    "event": (events_cmd, "cmd_event"),
    "notify": (events_cmd, "cmd_notify"),
    "watch": (events_cmd, "cmd_watch"),
    "codex-cmd": (workers_cmd, "cmd_codex_cmd"),
    "dispatch": (dispatch_cmd, "cmd_dispatch"),
    "wait": (workers_cmd, "cmd_wait"),
    "approve": (review_cmd, "cmd_approve"),
    "triage": (review_cmd, "cmd_triage"),
    "send": (workers_cmd, "cmd_send"),
    "_deliver-send": (workers_cmd, "cmd__deliver_send"),
    "_deliver-ready": (workers_cmd, "cmd__deliver_ready"),
    "land": (review_cmd, "cmd_land"),
    "review": (review_cmd, "cmd_review"),
    "escalate": (workers_cmd, "cmd_escalate"),
    "reattach": (workers_cmd, "cmd_reattach"),
    "retab": (workers_cmd, "cmd_retab"),
    "retire": (workers_cmd, "cmd_retire"),
    "idle-workers": (workers_cmd, "cmd_idle_workers"),
    "close-worker": (workers_cmd, "cmd_close_worker"),
    "state": (state_view, "cmd_state"),
    "project": (project_cmd, "cmd_project"),
    "helper": (helpers_cmd, "cmd_helper"),
    "dash": (dash_view, "cmd_dash"),
    "decide": (memory_cmd, "cmd_decide"),
    "remember": (memory_cmd, "cmd_remember"),
    "recall": (memory_cmd, "cmd_recall"),
    "forget": (memory_cmd, "cmd_forget"),
    "adopt": (memory_cmd, "cmd_adopt"),
    "memory": (memory_cmd, "cmd_memory"),
    "handover": (manager_cmd, "cmd_handover"),
    "decisions": (memory_cmd, "cmd_decisions"),
    "conversation": (ledger_cmd, "cmd_conversation"),
    "context": (memory_cmd, "cmd_context"),
    "rotate": (manager_cmd, "cmd_rotate"),
    "seat": (manager_cmd, "cmd_seat"),
    "end-session": (manager_cmd, "cmd_end_session"),
    "name-agent": (manager_cmd, "cmd_name_agent"),
    "home": (project_cmd, "cmd_home"),
    "backfill-numbers": (ledger_cmd, "cmd_backfill_numbers"),
    "hook-session-start": (hooks, "cmd_hook_session_start"),
    "hook-pre-compact": (hooks, "cmd_hook_pre_compact"),
    "hook-pre-tool": (hooks, "cmd_hook_pre_tool"),
    "hook-turn": (hooks, "cmd_hook_turn"),
    "hook-mirror": (hooks, "cmd_hook_mirror"),
}


def build_parser():
    p = argparse.ArgumentParser(prog="pm.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    ledger_cmd.register_task_commands(sub)
    status_view.register_status_views(sub)
    manager_cmd.register_claim_command(sub)
    ledger_cmd.register_guard_command(sub)
    manager_cmd.register_manager_lifecycle_commands(sub)
    events_cmd.register_event_commands(sub)
    workers_cmd.register_codex_cmd_command(sub)
    dispatch_cmd.register_dispatch_command(sub)
    workers_cmd.register_wait_command(sub)
    review_cmd.register_approve_triage_commands(sub)
    workers_cmd.register_send_commands(sub)
    review_cmd.register_land_review_commands(sub)
    workers_cmd.register_worker_lifecycle_commands(sub)
    state_view.register_state_view(sub)
    project_cmd.register_project_command(sub)
    helpers_cmd.register_helper_commands(sub)
    dash_view.register_dash_view(sub)
    memory_cmd.register_memory_commands(sub)
    manager_cmd.register_handover_command(sub)
    memory_cmd.register_decisions_command(sub)
    ledger_cmd.register_conversation_command(sub)
    memory_cmd.register_context_command(sub)
    manager_cmd.register_manager_session_commands(sub)
    project_cmd.register_home_command(sub)
    ledger_cmd.register_backfill_numbers_command(sub)
    hooks.register_hook_commands(sub)
    return p


def main(argv=None, ctx=None):
    p = build_parser()
    a = p.parse_args(argv)
    run_ctx = context.Context.from_env() if ctx is None else ctx
    try:
        mod, fn_name = COMMANDS[a.cmd]
        getattr(mod, fn_name)(a, ctx=run_ctx)
    except IdentityError as e:
        run_ctx.out.err_line(f"PM identity check failed: {e}")
        p.exit(2)
    except StoreError as e:
        run_ctx.out.err_line(f"ledger store error: {e}")
        p.exit(1)
    except PmError as e:
        if e.payload is not None:
            run_ctx.out.json(e.payload, stream="stdout" if e.stream == "stdout" else "stderr")
            p.exit(e.code)
        elif e.stream == "stdout":
            if str(e):
                run_ctx.out.line(str(e))
            p.exit(e.code)
        else:
            if str(e):
                run_ctx.out.err_line(str(e))
            p.exit(e.code)
