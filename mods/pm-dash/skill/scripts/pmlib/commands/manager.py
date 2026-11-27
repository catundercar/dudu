"""Manager session lifecycle commands (`launch`, `claim`, `start`, `archive`, `restore`, `rotate`, `seat`,
`end-session`, `name-agent`, `handover`). Layer 4."""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
import types
from typing import Any

from ..context import Context
from ..errors import PmError
from ..manager.rotate import RETIRE_LOOK
from ..manager.seat import RETIRE_WAIT
from ..manager.service import ARCHIVE_PAUSES, ManagerSessions


def _exit_on_error(err: PmError) -> None:
    msg = str(err)
    sys.exit(msg if msg else err.code)


def launch_command(repo: str, resume: str | None = None, *, ctx: Context | None = None) -> str:
    """The command that starts this project's PM in Claude Code: with its Discord channel when `claim
    --discord-channel` wrote its MCP config, else a plain one."""
    c = Context.from_env() if ctx is None else ctx
    return ManagerSessions(c).launch_command(repo, resume=resume)


def cmd_launch(a: Any, ctx: Context | None = None) -> None:
    ctx = Context.from_env() if ctx is None else ctx
    try:
        line = ManagerSessions(ctx).launch(a.repo, resume=a.resume)
    except PmError as err:
        _exit_on_error(err)
    ctx.out.line(line)


def cmd_claim(a: Any, ctx: Context | None = None) -> None:
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = ManagerSessions(ctx).claim(
            a.repo,
            pane=getattr(a, "pane", None),
            kind=getattr(a, "kind", None),
            from_start=bool(getattr(a, "from_start", False)),
            discord_channel=getattr(a, "discord_channel", None),
            discord_users=getattr(a, "discord_users", None),
        )
    except PmError as err:
        _exit_on_error(err)
    for line in res.lines:
        ctx.out.line(line)
    if res.exec_argv:
        out_stream = getattr(ctx.out, "_out", lambda: None)()
        for stream in (out_stream, sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "flush"):
                with contextlib.suppress(OSError, ValueError):
                    stream.flush()
        try:
            os.execvp(res.exec_argv[0], res.exec_argv)
        except OSError as err:
            sys.exit(f"failed to exec {res.exec_argv[0]}: {err}")


_DEFAULT_CMD_CLAIM = cmd_claim


def cmd_handover(a: Any, ctx: Context | None = None) -> None:
    """What a fresh PM session needs, from the project's record on disk: ready-to-dispatch tasks (pinned at top),
    memory, one-off/unremembered decisions, previous PM's notes, open work, the last exchanges and waits.
    --full prints everything; --compact prints a short live disk sync after compaction."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        text = ManagerSessions(ctx).handover(
            a.repo,
            turns=getattr(a, "turns", 6),
            full=bool(getattr(a, "full", False)),
            compact=bool(getattr(a, "compact", False)),
        )
    except PmError as err:
        _exit_on_error(err)
    ctx.out.line(text)


def cmd_name_agent(a: Any, ctx: Context | None = None) -> None:
    ctx = Context.from_env() if ctx is None else ctx
    ManagerSessions(ctx).name_agent(a.pane, a.name, wait=a.wait)


def cmd_start(a: Any, prompt: str | None = None, *, ctx: Context | None = None) -> str:
    """Start a PM session of any agent kind for a project in a fixed PM seat (`pm.py seat`) and hand it the
    project's record.

    --space new (the default) gives the PM a space of its own, called --name (default: the folder's name);
    --space current puts it in a tab of the space this command runs in, as before."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = ManagerSessions(ctx).start(
            a.repo,
            kind=getattr(a, "kind", None),
            model=getattr(a, "model", None),
            name=getattr(a, "name", None),
            space=getattr(a, "space", None) or "new",
            prompt=prompt,
        )
    except PmError as err:
        _exit_on_error(err)
    for line in res.stderr_lines:
        ctx.out.err_line(line)
    for line in res.lines:
        ctx.out.line(line)
    return res.terminal


def cmd_archive(a: Any, ctx: Context | None = None) -> None:
    """Put a project away: its PM's session ends and its open tasks are paused. The ledger, the conversation
    log, the decisions and the handover notes stay; `pm.py restore` brings it back."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = ManagerSessions(ctx).archive(a.project)
    except PmError as err:
        _exit_on_error(err)
    for line in res.lines:
        ctx.out.line(line)


def cmd_restore(a: Any, ctx: Context | None = None) -> None:
    """Bring an archived project back: its paused tasks return to where they were and a fresh PM starts from
    the handover. Either all of that happens or nothing does."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = ManagerSessions(ctx).restore(
            a.project,
            kind=getattr(a, "kind", None),
            model=getattr(a, "model", None),
        )
    except PmError as err:
        _exit_on_error(err)
    for line in res.stderr_lines:
        ctx.out.err_line(line)
    for line in res.lines:
        ctx.out.line(line)


def cmd_rotate(a: Any, ctx: Context | None = None) -> None:
    """Replace the PM session of a project with a fresh one that starts from `handover`."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = ManagerSessions(ctx).rotate(
            a.repo,
            notes=getattr(a, "notes", None),
            reason=getattr(a, "reason", None),
            model=getattr(a, "model", None),
            profile=getattr(a, "profile", None),
            transcript=getattr(a, "transcript", None),
            force=bool(getattr(a, "force", False)),
        )
    except PmError as err:
        _exit_on_error(err)
    for line in res.lines:
        ctx.out.line(line)


def cmd_seat(a: Any, ctx: Context | None = None) -> None:
    """Run inside the project's fixed PM terminal and host one PM session after another across rotations."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        res = ManagerSessions(ctx).seat(
            a.repo,
            a.argv,
            kind=getattr(a, "kind", None) or "",
            prompt=getattr(a, "prompt", None) or "",
            no_shell=bool(getattr(a, "no_shell", False)),
        )
    except PmError as err:
        _exit_on_error(err)
    if res.exec_shell:
        candidates: list[str] = []
        for sh in (ctx.env.get("SHELL"), "/bin/zsh", "/bin/sh"):
            if sh and sh not in candidates:
                candidates.append(sh)
        for shell in candidates:
            with contextlib.suppress(OSError):
                os.execvp(shell, [shell, "-li"])
    if res.exit_code:
        sys.exit(res.exit_code)


def cmd_end_session(a: Any, ctx: Context | None = None) -> None:
    """Wait until the outgoing PM session finishes its turn and any non-wait background commands (two quiet looks in
    a row), then end its process group (or, with `--kill-terminal` for legacy non-seat PMs, kill the old terminal)."""
    ctx = Context.from_env() if ctx is None else ctx
    try:
        ManagerSessions(ctx).end_session(
            a.terminal,
            repo_arg=getattr(a, "repo", None),
            agent_pid=getattr(a, "agent_pid", None),
            kill_terminal=bool(getattr(a, "kill_terminal", False)),
            timeout=a.timeout,
            force=bool(getattr(a, "force", False)),
        )
    except PmError as err:
        _exit_on_error(err)


def register_claim_command(sub):
    c = sub.add_parser("claim")
    c.add_argument("--repo", default=".")
    c.add_argument("--pane", help="register the PM for this pane instead of the current one")
    c.add_argument("--kind", help="which agent this PM is (default: read from its terminal)")
    c.add_argument("--discord-channel", help="optional: guild channel ID this PM listens to (needs the bot token)")
    c.add_argument("--discord-users", help="comma-separated user IDs allowed to talk there (default: paired users)")


def register_manager_lifecycle_commands(sub):
    la = sub.add_parser("launch", help="print the command that starts this project's PM in Claude Code "
                                       "(with its Discord channel when one is bound)")
    la.add_argument("--repo", default=".")
    la.add_argument("--resume")
    st = sub.add_parser("start", help="start a PM session for a project, with any coding agent")
    st.add_argument("--repo", default=".")
    st.add_argument("--kind", help="agent program (default: config.json pm.kind, else claude)")
    st.add_argument("--model", help="default: config.json pm.model, else opus for Claude Code, else the program's own")
    st.add_argument("--name", help="the project's name, given to its new space (default: the folder's name)")
    st.add_argument("--space", choices=["new", "current"], default="new",
                    help="new (default): a space of its own, called --name. current: a tab in this command's "
                         "space, or a bare terminal outside one; that was what start did before --space existed")
    for verb, about in (("archive", "end a project's PM and pause its open tasks; the record stays"),
                        ("restore", "bring an archived project back and start its PM from the handover")):
        ar = sub.add_parser(verb, help=about)
        ar.add_argument("project", nargs="?", default=".", help="its folder, or its name (default: this folder)")
        if verb == "restore":
            ar.add_argument("--kind", help="agent program (default: the one the PM was)")
            ar.add_argument("--model", help="default: config.json pm.model, else opus for Claude Code, else the "
                                            "program's own")


def register_handover_command(sub):
    ho = sub.add_parser("handover", help="print what a fresh PM session needs to take over this project")
    ho.add_argument("--repo", default=".")
    ho.add_argument("--turns", type=int, default=6, help="how many past exchanges with the user to include")
    ho.add_argument("--full", action="store_true", help="everything, as before it was shortened: every decision "
                                                         "with the user's words, more log per task, closed tasks")
    ho.add_argument("--compact", action="store_true", help="short live disk sync for post-compaction injection")


def register_manager_session_commands(sub):
    ro = sub.add_parser("rotate", help="hand the project to a fresh PM session")
    ro.add_argument("--repo", default=".")
    ro.add_argument("--notes", help="what is in flight that the ledger and decisions do not say")
    ro.add_argument("--reason", help="why the PM session is swapped (logged transparently in the conversation)")
    ro.add_argument("--model", help="model for the new session (default: config.json pm.model, else opus for "
                                    "Claude Code; never the outgoing session's; other agents: the CLI's default)")
    ro.add_argument("--profile", help="profile name from profiles / config.json for the new session (recovery ladder)")
    ro.add_argument("--transcript", help="the outgoing session's transcript (default: this session's)")
    ro.add_argument("--force", action="store_true", help="immediately end the outgoing session without waiting for idle (recovery)")
    se = sub.add_parser("seat", help="run inside the project's fixed PM terminal and swap agent sessions across rotations")
    se.add_argument("--repo", default=".")
    se.add_argument("--kind", default="", help="agent kind for the initial session")
    se.add_argument("--prompt", default="", help="initial prompt for an agent that takes no CLI prompt argument")
    se.add_argument("--no-shell", action="store_true", help="exit instead of exec'ing a login shell when done")
    se.add_argument("argv", nargs=argparse.REMAINDER, help="`--` followed by the initial PM agent command")
    es_cmd = sub.add_parser("end-session", help="(run by rotate) end the outgoing PM session once its turn is over")
    es_cmd.add_argument("terminal")
    es_cmd.add_argument("--repo", default=".")
    es_cmd.add_argument("--agent-pid", type=int, default=None, help="PID of the outgoing agent session in `seat`")
    es_cmd.add_argument("--kill-terminal", action="store_true", help="end a legacy non-seat PM terminal")
    es_cmd.add_argument("--timeout", type=int, default=RETIRE_WAIT)
    es_cmd.add_argument("--force", action="store_true", help="stop the outgoing session immediately without waiting for idle")
    na = sub.add_parser("name-agent", help="(run by the session-start hook) name a PM in a herdr TUI pane once it shows")
    na.add_argument("pane")
    na.add_argument("name")
    na.add_argument("--wait", type=int, default=60)
