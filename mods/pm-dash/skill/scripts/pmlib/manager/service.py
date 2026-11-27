"""`ManagerSessions` service: project PM lifecycle (`launch`, `claim`, `start`, `archive`, `restore`, `rotate`,
`seat`, `end_session`, `name_agent`, `handover`) over an explicit `Context`. Layer 3."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import signal
import sys
import types
from typing import Any, Callable, Sequence

try:
    import termios
except ImportError:
    termios = None

from .. import discord as discord_mod, osutil
from ..agents.sessions import context_tokens
from ..caller import Caller
from ..context import Context
from ..errors import NotFound, PmError, Refused
from ..events import deliver as deliver_mod
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..messaging.address import parse_legacy_endpoint
from ..osutil import shell_join
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry, pm_name
from ..project.turn_reducer import record_endpoint
from ..project.turn_state import TurnTracker
from ..store import lock_file, replace_task_file, unlock_file, write_atomic
from ..terminals.hc import is_shell_terminal
from ..terminals.tabs import pm_tab_name
from . import launch as launch_mod, rotate as rotate_mod, seat as seat_mod
from .claim import end_pm, move_pm_tasks_to_pane
from .handover import handover_text
from .launch import build_pm_seat_command, build_pm_seat_parts, pm_argv, pm_model, seat_argv, successor_argv
from .rotate import (
    NAME_WAIT,
    RETIRE_LOOK,
    build_fallback_spec,
    name_agent as _name_agent,
    restore_cancelled_rotation,
    still_running,
    successor_env,
    takeover_prompt,
)
from .seat import (
    RETIRE_WAIT,
    SEAT_NEXT_MAX_AGE,
    _close_win_job,
    _create_win_kill_job,
    _hand_tty_to_child,
    _is_real_hc,
    _reclaim_tty,
    _reset_seat_tty,
    _seat_prompt_sender,
    _spawn_seat_child,
    _wait_seat_session,
    in_seat,
    is_seat_terminal,
    outgoing_agent_args,
    pop_next_session,
    read_seat_state,
    record_swap_notice,
    seat_running,
    swap_reason_text,
    write_seat_state,
)


# Statuses of open work that an archive pauses; a restore puts each back.
ARCHIVE_PAUSES = ("proposed", "in_progress", "review", "blocked")


@dataclass
class ClaimResult:
    pane: str
    name: str
    project: str
    lines: list[str] = field(default_factory=list)
    exec_argv: list[str] | None = None


@dataclass
class StartResult:
    terminal: str
    lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)


@dataclass
class ArchiveResult:
    project: str
    paused: int
    already_archived: str | None = None
    lines: list[str] = field(default_factory=list)


@dataclass
class RestoreResult:
    project: str
    restored: int
    terminal: str = ""
    not_archived: bool = False
    lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)


@dataclass
class RotateResult:
    mode: str
    lines: list[str] = field(default_factory=list)


@dataclass
class SeatResult:
    exit_code: int = 0
    exec_shell: bool = False


class ManagerSessions:
    """Layer 3 service coordinating a project's PM session lifecycle over an explicit `Context`."""

    def __init__(
        self,
        ctx: Context,
        *,
        _claim_hook: Callable[[str, str, str, bool], Any] | None = None,
    ) -> None:
        self.ctx = ctx
        self.projects = ProjectRegistry(ctx)
        self.ledger = Ledger(ctx)
        self._claim_hook = _claim_hook

    def _caller(self) -> Caller:
        if self.ctx.caller is not None:
            return self.ctx.caller
        return Caller(self.ctx)

    def _start_pm_terminal_result(
        self,
        repo: str,
        argv: Sequence[str],
        space: str | None = None,
        new_space: str = "",
    ) -> launch_mod.StartTerminalResult:
        if getattr(self.ctx, "_legacy", False) and launch_mod.start_pm_terminal is not launch_mod._DEFAULT_START_PM_TERMINAL:
            return launch_mod.StartTerminalResult(
                terminal=launch_mod.start_pm_terminal(repo, argv, space, new_space),
                has_tab=True,
            )
        return launch_mod._start_pm_terminal_result(repo, argv, space, new_space, ctx=self.ctx)

    def _start_pm_terminal(
        self,
        repo: str,
        argv: Sequence[str],
        space: str | None = None,
        new_space: str = "",
    ) -> str | None:
        return self._start_pm_terminal_result(repo, argv, space, new_space).terminal

    def _end_session_later(
        self,
        repo: str,
        term: str,
        *,
        agent_pid: int | None = None,
        kill_terminal: bool = False,
        force: bool = False,
    ) -> str | None:
        if getattr(self.ctx, "_legacy", False) and rotate_mod.end_session_later is not rotate_mod._DEFAULT_END_SESSION_LATER:
            return rotate_mod.end_session_later(repo, term, agent_pid=agent_pid, kill_terminal=kill_terminal)
        return rotate_mod._end_session_later_impl(
            repo, term, agent_pid=agent_pid, kill_terminal=kill_terminal, force=force, ctx=self.ctx
        )

    def _background_work(self, info: dict[str, Any]) -> list[str]:
        if rotate_mod.background_work is not rotate_mod._DEFAULT_BACKGROUND_WORK:
            return rotate_mod.background_work(info)
        return self.ctx.procs.background_work(info)

    def _discord(self) -> discord_mod.DiscordMirror:
        if getattr(self.ctx, "_legacy", False):
            home_override = (
                discord_mod.DISCORD_HOME
                if discord_mod.DISCORD_HOME != discord_mod._DEFAULT_DISCORD_HOME else None
            )
            plugin_override = (
                discord_mod.DISCORD_PLUGIN_ROOT
                if discord_mod.DISCORD_PLUGIN_ROOT != discord_mod._DEFAULT_DISCORD_PLUGIN_ROOT else None
            )
            return discord_mod.DiscordMirror(
                self.ctx, discord_home=home_override, plugin_root_dir=plugin_override
            )
        return discord_mod.DiscordMirror(self.ctx)

    def launch_command(self, repo: str | Path, *, resume: str | None = None) -> str:
        """The command that starts this project's PM in Claude Code: with its Discord channel when `claim
        --discord-channel` wrote its MCP config, else a plain one."""
        # A manually configured server only counts as a channel through the development-channels flag.
        # Do not also pass --channels for it: the first matching entry wins and that one is not marked dev.
        dm = self._discord()
        mcp_path = dm.mcp_config_path(repo)
        discord = (
            f"--mcp-config {mcp_path} --dangerously-load-development-channels server:{discord_mod.MCP_SERVER} "
            if dm.is_on() and mcp_path.exists() else ""
        )
        return f"claude {discord}" + (f"--resume {resume} " if resume else "") + "<your usual flags>"

    def launch(self, repo_arg: str | Path, *, resume: str | None = None) -> str:
        repo = self.ctx.git.project_root(repo_arg)
        if not repo:
            raise Refused(f"{repo_arg} is not a directory")
        return self.launch_command(repo, resume=resume)

    def claim(
        self,
        repo_arg: str | Path,
        *,
        pane: str | None = None,
        kind: str | None = None,
        from_start: bool = False,
        discord_channel: str | None = None,
        discord_users: str | None = None,
    ) -> ClaimResult:
        eff_pane = pane or self.ctx.pane
        if not eff_pane:
            raise Refused("not running inside a herdr pane; pass --pane")
        repo = self.ctx.git.project_root(repo_arg)
        if not repo:
            raise Refused(f"{repo_arg} is not a directory")
        pm = self.projects.find_pm(repo=repo)
        if pm and pm["pane_id"] != eff_pane:
            raise Refused(f"PM for {Path(repo).name} already exists at {pm['pane_id']}; ask the user before replacing it")
        name = pm_name(repo)
        eff_kind = kind or ""
        channel = discord_channel
        dm = self._discord() if channel else None
        if dm is not None:
            dm.require_on()
        if dm is not None and not dm.token():
            raise Refused(f"no bot token: put DISCORD_BOT_TOKEN=... in {dm.token_file}")
        start_seat_in_pane = False
        seated = False
        if eff_pane.startswith("hc:"):
            workspace = ""
            term = eff_pane[3:]
            info = self.ctx.hc.get_raw(term) or {}
            cfg = self.ctx.config.read().get("pm") or {}
            if from_start or is_seat_terminal(info) or seat_running(repo, ctx=self.ctx):
                seated = True
            elif is_shell_terminal(info):
                seated = True
                start_seat_in_pane = True
                eff_kind = eff_kind or cfg.get("kind") or "claude"
            else:
                # External claim on a bare/mocked terminal without an active agent uses seat mode; an already-running
                # non-seat session claiming itself (`pane == PANE` inside Claude) rotates into a seat on its next rotate.
                seated = eff_pane != self.ctx.pane and not (info.get("foreground") or {}).get("argv")
            labels = [f"pm={Path(repo).name}", *(["pm.seat=1"] if seated else [])]
            if self.ctx.hc.label(term, *labels) is None:
                raise Refused(f"hc label {term} failed")
            if seated:
                self.ctx.hc.keep(term)
            self.ctx.hc.name_tab(term, pm_tab_name(repo))
            eff_kind = eff_kind or self.ctx.agents.terminal_kind(info)
        elif eff_pane == self.ctx.pane:
            workspace = self.ctx.workspace
            if not self.ctx.tui.agent_rename(self.ctx.pane, name):
                raise Refused(f"herdr agent rename {self.ctx.pane} {name} failed")
        else:
            # A shell pane has no agent to rename yet: start it with `herdr agent start <name>`.
            pane_info = self.ctx.tui.pane_get(eff_pane) or {}
            workspace = pane_info.get("workspace_id") or ""
            if not workspace:
                raise Refused(f"no herdr pane {eff_pane}")
        # Which herdr session the pane is in: pane ids repeat between sessions (see identity_inventory).
        session = self._caller().herdr_session() if not eff_pane.startswith("hc:") else ""
        sdir, discord_entry = None, None
        if channel and dm is not None:
            users = discord_users.split(",") if discord_users else dm.default_users()
            sdir = dm.write_state(repo, channel, users)
            discord_entry = {"channel_id": str(channel), "state_dir": str(sdir), "users": users}
        was_app = False
        prev_panes: set[str] = set()

        def _claim(cur: dict[str, Any] | None) -> dict[str, Any]:
            nonlocal was_app
            rec = dict(cur) if cur is not None else {}
            old_pane = rec.get("pane")
            if old_pane:
                prev_panes.add(old_pane)
            prev_prev = (rec.get("previous") or {}).get("pane") if isinstance(rec.get("previous"), dict) else ""
            if prev_prev:
                prev_panes.add(prev_prev)
            rec.update({"project": Path(repo).name, "repo": repo, "name": name, "pane": eff_pane, "workspace": workspace,
                        "claimed": self.ctx.clock.now()})
            effective_kind = eff_kind or rec.get("agent") or ""
            if (eff_pane == self.ctx.pane and not start_seat_in_pane and self.ctx.env.get("CLAUDE_CODE_SESSION_ID")
                    and effective_kind in ("", "claude")):
                rec["agent_session"] = {"kind": "claude", "id": self.ctx.env["CLAUDE_CODE_SESSION_ID"]}
            elif eff_pane != self.ctx.pane or old_pane != eff_pane or start_seat_in_pane or effective_kind not in ("", "claude"):
                # External claim (including `start` restarting an offline PM) or pane/agent change: clear any stale
                # session so `state` does not misattribute an older session or fall back to stale taken-in.json.
                rec["agent_session"] = None
            if session:
                rec["session"] = session
            else:
                rec.pop("session", None)
            if discord_entry is not None:
                rec["discord"] = discord_entry
            if eff_kind:
                rec["agent"] = eff_kind  # which program this PM is: its successor is started the same way
            was_app = rec.get("runtime") == "hc"
            for key in ("runtime", "terminal", "seat"):
                rec.pop(key, None)
            if eff_pane.startswith("hc:"):
                rec.update({"runtime": "hc", "terminal": eff_pane[3:]})
                if seated:
                    rec["seat"] = True
            return rec

        self.ctx.store.change_registration(project_slug(repo), _claim)
        if eff_pane.startswith("hc:") and prev_panes:
            move_pm_tasks_to_pane(repo, prev_panes, eff_pane, ctx=self.ctx)
        lines = [f"{eff_pane} is now {name} (PM for {Path(repo).name})"]
        exec_argv: list[str] | None = None
        if eff_pane.startswith("hc:"):
            if not was_app:
                # A new desktop-app PM (or one that ran in the herdr TUI, which had its inbox): what the log already
                # holds is for the handover, not a delivery.
                log = self.ctx.home.project_for(repo).ensure() / "conversation.jsonl"
                deliver_mod.Delivery(self.ctx, repo).advance_delivered(log.stat().st_size if log.exists() else 0)
            if start_seat_in_pane:
                s_argv, _ = build_pm_seat_command(repo, eff_kind, "", ctx=self.ctx)
                if eff_pane == self.ctx.pane and _is_real_hc(self.ctx) and sys.stdin.isatty() and sys.stdout.isatty():
                    deliver_mod.Delivery(self.ctx, repo).ensure_running()
                    return ClaimResult(pane=eff_pane, name=name, project=Path(repo).name, lines=lines, exec_argv=s_argv)
                self.ctx.hc.bootstrap_shell_exec(eff_pane[3:], "exec " + shell_join(s_argv))
            deliver_mod.Delivery(self.ctx, repo).ensure_running()
        if sdir and eff_pane == self.ctx.pane and self.ctx.env.get("DISCORD_STATE_DIR") != str(sdir):
            lines.append("restart to connect Discord:\n  " + self.launch_command(repo, resume="<session id>"))
        if eff_pane != self.ctx.pane and not eff_pane.startswith("hc:"):
            flags = self.launch_command(repo)[len("claude "):] if channel else "<your usual flags>"
            lines.append(f"start it: herdr agent start {name} --kind {eff_kind or 'claude'} --pane {eff_pane} -- {flags}")
        return ClaimResult(pane=eff_pane, name=name, project=Path(repo).name, lines=lines, exec_argv=exec_argv)

    def handover(self, repo_arg: str | Path, *, turns: int = 6, full: bool = False, compact: bool = False) -> str:
        repo = self.ctx.git.project_root(repo_arg)
        if not repo:
            raise Refused(f"{repo_arg} is not a directory")
        return handover_text(repo, turns=turns, full=full, compact=compact, ctx=self.ctx)

    def start(
        self,
        repo_arg: str | Path,
        *,
        kind: str | None = None,
        model: str | None = None,
        name: str | None = None,
        space: str | None = "new",
        prompt: str | None = None,
    ) -> StartResult:
        """Start a PM session of any agent kind for a project in a fixed PM seat (`pm.py seat`) and hand it the
        project's record."""
        tr = self.ctx.config.tr
        if not Path(repo_arg).is_dir():
            raise Refused(f"{repo_arg} is not a directory")
        repo = self.ctx.git.project_root(repo_arg)
        if not repo:
            raise Refused(f"{repo_arg} is not a directory")
        rec = self.projects.pm_record(repo) or {}
        if rec.get("archived"):
            raise Refused(tr(
                f"{Path(repo).name} is archived ({rec['archived']}); bring it back with `pm.py restore`",
                f"{Path(repo).name} 已归档（{rec['archived']}）；用 `pm.py restore` 恢复",
            ))
        pm = self.projects.find_pm(repo=repo)
        if pm:
            raise Refused(f"PM for {Path(repo).name} already exists at {pm['pane_id']}; use `pm.py rotate` to replace it")
        was_existing = bool(rec and Conversation(self.ctx, repo).events())
        cfg = self.ctx.config.read().get("pm") or {}
        eff_kind = kind or cfg.get("kind") or "claude"
        eff_name = (name or "").strip() or rec.get("space_name") or Path(repo).name
        own = (self.ctx.hc.get_raw(self.ctx.hc_terminal) or {}) if self.ctx.hc_terminal else {}
        current = (space or "new") == "current"
        stderr_lines: list[str] = []
        if current and (name or "").strip():
            stderr_lines.append(tr(
                f"--name names a new space; with --space current it is not used (the tab is called {pm_tab_name(repo)})",
                f"--name 用来给新 space 命名；--space current 时不用它（标签页叫 {pm_tab_name(repo)}）",
            ))
        explicit_prompt = bool(prompt)  # restore passes prompt=...
        s_argv, _, _ = build_pm_seat_parts(repo, eff_kind, model, prompt=prompt, ctx=self.ctx)
        made: str | None = None
        # If a previous seat exited to a recovery shell in the fixed PM terminal, revive `pm.py seat` in that same terminal.
        old_term = rec.get("terminal") if rec.get("runtime") == "hc" and rec.get("seat") else ""
        if old_term and not seat_running(repo, ctx=self.ctx):
            old_info = self.ctx.hc.get_raw(old_term) or {}
            if ((old_info.get("labels") or {}).get("pm") == Path(repo).name and is_shell_terminal(old_info)
                    and self.ctx.hc.bootstrap_shell_exec(old_term, "exec " + shell_join(s_argv)) is not None):
                made = old_term
                self.ctx.hc.keep(made)
                self.ctx.hc.label(made, f"pm={Path(repo).name}", "pm.seat=1")
        started_tab = True
        if not made:
            started = self._start_pm_terminal_result(
                repo,
                s_argv,
                (own.get("labels") or {}).get("herdr.space"),
                "" if current else eff_name,
            )
            made = started.terminal
            started_tab = started.has_tab
        if not made:
            raise Refused("could not start the PM session (is herdr-core running?)")
        claim_lines: list[str] = []
        try:
            if self._claim_hook is not None:
                self._claim_hook(repo, f"hc:{made}", eff_kind, True)
            else:
                claim_res = self.claim(repo, pane=f"hc:{made}", kind=eff_kind, from_start=True)
                claim_lines.extend(claim_res.lines)
        except (SystemExit, PmError):
            if made != old_term:
                self.ctx.hc.kill(made)
                self.ctx.hc.remove(made)
            raise
        if not started_tab:
            claim_lines.append(launch_mod.no_tab_warning(made, ctx=self.ctx))
        if was_existing and not explicit_prompt:
            record_swap_notice(repo, tr("session recovery", "重启恢复"), by=f"hc:{made}", ctx=self.ctx)
        if not current:
            # The name the user gave the project: a restore opens its space under it again.
            def _set_space_name(cur: dict[str, Any] | None) -> dict[str, Any] | None:
                if cur is None:
                    return None
                cur["space_name"] = eff_name
                return cur

            self.ctx.store.change_registration(project_slug(repo), _set_space_name)
        return StartResult(terminal=made, lines=claim_lines, stderr_lines=stderr_lines)

    def archive(self, project: str | Path) -> ArchiveResult:
        """Put a project away: its PM's session ends and its open tasks are paused. The ledger, the conversation
        log, the decisions and the handover notes stay; `pm.py restore` brings it back."""
        tr = self.ctx.config.tr
        repo = self.projects.registered_repo(project)
        rec = self.projects.pm_record(repo) if repo else None
        if not rec or not repo:
            raise NotFound(f"no PM registered for {project}")
        name = Path(repo).name
        already_archived: str | None = None

        def _archive_reg(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal already_archived
            if cur is None:
                return None
            if cur.get("archived"):
                already_archived = cur["archived"]
                return None
            cur["agent_session"] = None
            cur["archived"] = self.ctx.clock.now()[:10]
            return cur

        rec = self.ctx.store.change_registration(project_slug(repo), _archive_reg)
        if already_archived:
            return ArchiveResult(
                project=name,
                paused=0,
                already_archived=already_archived,
                lines=[tr(f"{name} is already archived ({already_archived})", f"{name} 已经归档（{already_archived}）")],
            )
        if not rec:
            raise NotFound(f"no PM registered for {project}")
        paused = 0
        for task in self.ledger.project_tasks(repo):
            if task.status in ARCHIVE_PAUSES:
                did_pause = False

                def _pause_task(cur: Any, ch: Any) -> dict[str, Any] | None:
                    nonlocal did_pause
                    if cur is None:
                        return None
                    raw = cur.raw
                    if raw["status"] not in ARCHIVE_PAUSES:
                        return None
                    raw["paused_from"], raw["status"] = raw["status"], "paused"
                    ch.note(tr("project archived", "项目归档"))
                    did_pause = True
                    return raw

                self.ledger.change(task.id, _pause_task)
                if did_pause:
                    paused += 1
        lines = [tr(f"{name} archived: {paused} tasks paused", f"{name} 已归档：{paused} 个任务暂停")]
        lines.append(end_pm(rec, name, ctx=self.ctx))  # last: the PM may be the session running this command
        return ArchiveResult(project=name, paused=paused, lines=lines)

    def restore(
        self,
        project: str | Path,
        *,
        kind: str | None = None,
        model: str | None = None,
    ) -> RestoreResult:
        """Bring an archived project back: its paused tasks return to where they were and a fresh PM starts from
        the handover. Either all of that happens or nothing does."""
        tr = self.ctx.config.tr
        repo = self.projects.registered_repo(project)
        rec = self.projects.pm_record(repo) if repo else None
        if not rec or not repo:
            raise NotFound(f"no PM registered for {project}")
        name, archived = Path(repo).name, rec.get("archived")
        if not archived:
            return RestoreResult(
                project=name,
                restored=0,
                not_archived=True,
                lines=[tr(f"{name} is not archived", f"{name} 没有归档")],
            )
        # What would make the start fail, checked before anything changes.
        if not Path(repo).is_dir():
            raise Refused(tr(f"{repo} is gone; {name} stays archived", f"{repo} 不存在了；{name} 仍是归档状态"))
        live = self.projects.find_pm(repo=repo)
        if live:
            raise Refused(tr(
                f"the old PM of {name} still runs at {live['pane_id']}; end it first. {name} stays archived",
                f"{name} 的旧 PM 还在 {live['pane_id']} 运行，先把它关掉；{name} 仍是归档状态",
            ))
        if self.ctx.hc.server_status() is None:
            raise Refused(tr(f"herdr-core is not reachable; {name} stays archived",
                             f"herdr-core 连不上；{name} 仍是归档状态"))
        slug = project_slug(repo)

        def _unarchive(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            if cur is None:
                return None
            cur.pop("archived", None)
            return cur

        self.ctx.store.change_registration(slug, _unarchive)
        restored: dict[str, str] = {}
        for task in self.ledger.project_tasks(repo):
            if task.status == "paused" and task.get("paused_from"):
                prev_status: str | None = None

                def _restore_task(cur: Any, ch: Any) -> dict[str, Any] | None:
                    nonlocal prev_status
                    if cur is None:
                        return None
                    raw = cur.raw
                    if raw["status"] != "paused" or not raw.get("paused_from"):
                        return None
                    prev_status = raw.pop("paused_from")
                    raw["status"] = prev_status
                    ch.note(tr("project restored", "项目恢复"))
                    return raw

                self.ledger.change(task.id, _restore_task)
                if prev_status is not None:
                    restored[task.id] = prev_status
        handover = f"{self.ctx.procs.pm_script()} handover"
        prompt = "[from pm.py restore] " + tr(
            f"You are the PM of the {name} project (pm skill); the project was archived and has just been restored. "
            f"First run `{handover}` and take over from what it prints, nothing else. Then tell the user in three or "
            "four sentences what you took over and what is waiting for them.",
            f"你是 {name} 项目的 PM（pm skill），这个项目刚从归档中恢复。"
            f"先运行 `{handover}`，只按它给出的内容接手，"
            "然后用三四句话告诉用户：你接手了哪些在办的事、哪些事在等他。")
        try:
            started = self.start(repo, kind=kind or rec.get("agent"), model=model, name="", space="new", prompt=prompt)
        except (SystemExit, PmError) as stop:
            # Put it back as it was: archived, with the same tasks paused.
            self.ctx.store.change_registration(slug, lambda cur: {**(cur or rec), "archived": archived})
            for task_id, status in restored.items():
                def _repause(cur: Any, ch: Any, _st: str = status) -> dict[str, Any] | None:
                    if cur is None:
                        return None
                    raw = cur.raw
                    raw["status"], raw["paused_from"] = "paused", _st
                    ch.note(tr("restore failed; paused again", "恢复失败，重新暂停"))
                    return raw

                self.ledger.change(task_id, _repause)
            raise Refused(tr(f"{name} was not restored ({stop}); it stays archived",
                             f"{name} 没有恢复（{stop}）；仍是归档状态")) from stop
        lines = [*started.lines, tr(f"{name} restored: {len(restored)} tasks back",
                                    f"{name} 已恢复：{len(restored)} 个任务恢复原状态")]
        return RestoreResult(
            project=name,
            restored=len(restored),
            terminal=started.terminal,
            lines=lines,
            stderr_lines=started.stderr_lines,
        )

    def rotate(
        self,
        repo_arg: str | Path,
        *,
        notes: str | None = None,
        reason: str | None = None,
        model: str | None = None,
        profile: str | None = None,
        transcript: str | None = None,
        force: bool = False,
    ) -> RotateResult:
        """Replace the PM session of a project with a fresh one that starts from `handover`."""
        tr = self.ctx.config.tr
        repo = self.ctx.git.project_root(repo_arg)
        rec = self.projects.pm_record(repo) if repo else None
        if not rec or not repo:
            raise NotFound("no PM registered for this project")
        d = self.ctx.home.project_for(repo).ensure()
        is_self = rec.get("pane") == self.ctx.pane
        eff_transcript = transcript or (self.ctx.agents.own_transcript() if is_self else "")
        notes_text = f"Written {self.ctx.clock.now()} by the outgoing PM ({rec.get('pane')}).\n\n{notes.strip()}\n" if notes else ""
        (d / "handover.md").write_text(notes_text)
        previous: dict[str, Any] = {
            "pane": rec.get("pane"),
            "transcript": eff_transcript,
            "at": self.ctx.clock.now(),
            "tokens": context_tokens(eff_transcript) if eff_transcript else 0,
        }
        if isinstance(rec.get("agent_session"), dict):
            previous["agent_session"] = rec["agent_session"]
        name, handover = Path(repo).name, f"{self.ctx.procs.pm_script()} handover"
        eff_reason = swap_reason_text(reason=reason, model=model, profile=profile, ctx=self.ctx)
        if rec.get("runtime") != "hc":
            # The herdr TUI: the new PM opens in a tab of its own, so it says what it took over, as before.
            prompt = "[from pm.py rotate] " + tr(
                f"You are the PM of the {name} project (pm skill), replacing the session that was just rotated "
                "out. If the startup notice says another PM exists, that is the one you replace; the registration is "
                f"about to move to you. First run `{handover}` and take over from what it prints, nothing else. Then tell "
                "the user in three or four sentences what you took over and what is waiting for them.",
                f"你是 {name} 项目的 PM（pm skill），接替刚轮换下去的上一任会话。"
                "启动提示里如果说另有一个 PM，那就是你要接替的那一个，登记马上会转到你名下。"
                f"先运行 `{handover}`，只按它给出的内容接手，"
                "然后用三四句话告诉用户：你接手了哪些在办的事、哪些事在等他。")
            args_bag = types.SimpleNamespace(repo=repo, notes=notes, reason=reason, model=model, profile=profile, transcript=transcript)
            if getattr(self.ctx, "_legacy", False) and rotate_mod.rotate_herdr is not rotate_mod._DEFAULT_ROTATE_HERDR:
                res = rotate_mod.rotate_herdr(args_bag, repo, rec, previous, prompt, is_self)
                return RotateResult(mode="tui", lines=list(res) if isinstance(res, list) else [])
            lines = rotate_mod._rotate_herdr_impl(args_bag, repo, rec, previous, prompt, is_self, ctx=self.ctx)
            return RotateResult(mode="tui", lines=lines)

        prompt = "[from pm.py rotate] " + takeover_prompt(name, handover, eff_reason, ctx=self.ctx)
        term = rec["terminal"]
        old = self.ctx.hc.get_raw(term) or {}
        prev_kind = rec.get("agent") or self.ctx.agents.terminal_kind(old) or "claude"
        kind, target_model, target_effort = rotate_mod.resolve_rotate_target(profile, model, prev_kind, ctx=self.ctx)
        eff_model = pm_model(kind, target_model or None, ctx=self.ctx)
        if kind != prev_kind:
            old_args = []
            argv = launch_mod.pm_start_argv(repo, kind, eff_model, prompt, ctx=self.ctx)
        else:
            old_args = outgoing_agent_args(repo, old, kind, ctx=self.ctx)
            argv = pm_argv(
                kind,
                successor_argv(kind, old_args, eff_model, prompt, ctx=self.ctx),
                repo,
                ctx=self.ctx,
            )
        if target_effort and kind == "claude":
            argv = rotate_mod._apply_claude_effort(argv, target_effort)
        prev_sid = (rec.get("agent_session") or {}).get("id") if isinstance(rec.get("agent_session"), dict) else ""

        if in_seat(repo, rec, old, ctx=self.ctx):
            seat = read_seat_state(repo, ctx=self.ctx)
            agent_pid = seat.get("agent_pid") if isinstance(seat.get("agent_pid"), int) else None
            spec = {
                "argv": argv,
                "kind": kind,
                "prompt": "" if self.ctx.agents.takes_prompt(kind) else prompt,
                "at": self.ctx.clock.now(),
                "created_ts": self.ctx.clock.time(),
                "previous": {**previous, "terminal": term, "agent": rec.get("agent") or kind, "args": old_args},
            }
            write_atomic(
                self.ctx.home.project_for(repo).ensure() / "next-session.json",
                (json.dumps(spec, ensure_ascii=False) + "\n").encode("utf-8"),
                replace_fn=replace_task_file,
            )

            def _rotate_seat(cur: dict[str, Any] | None) -> dict[str, Any]:
                fresh = dict(cur) if cur is not None else dict(rec)
                if prev_sid:
                    retired_ids = [s for s in (fresh.get("retired_sessions") or []) if isinstance(s, str) and s != prev_sid]
                    retired_ids.append(prev_sid)
                    fresh["retired_sessions"] = retired_ids[-8:]
                fresh["agent_session"] = None
                cur_ep = record_endpoint(fresh) or parse_legacy_endpoint(f"hc:{term}", runtime_hint="hc")
                next_epoch = int((cur_ep.epoch if cur_ep else 1) or 1) + 1
                if cur_ep is not None:
                    ep_dict = {**cur_ep.to_dict(), "epoch": next_epoch, "agent_kind": kind}
                else:
                    ep_dict = {"runtime": "hc", "machine": None, "terminal": term, "epoch": next_epoch, "agent_kind": kind}
                fresh.update({"pane": f"hc:{term}", "terminal": term, "seat": True, "claimed": self.ctx.clock.now(),
                              "agent": kind, "endpoint": ep_dict, "epoch": next_epoch,
                              "previous": {**previous, "terminal": term},
                              "rotations": fresh.get("rotations", 0) + 1})
                return fresh

            self.ctx.store.change_registration(project_slug(repo), _rotate_seat)
            rotated_ep = parse_legacy_endpoint(f"hc:{term}", runtime_hint="hc")
            new_reg_after = self.ctx.store.registration(project_slug(repo)) or {}
            new_epoch_val = int(new_reg_after.get("epoch") or 1)
            TurnTracker(self.ctx, repo).pm_mailbox.requeue_unconsumed_on_epoch_change(
                new_epoch_val, endpoint_uid=rotated_ep.uid if rotated_ep else ""
            )
            old_pm_panes = {rec.get("pane"), (rec.get("previous") or {}).get("pane")
                            if isinstance(rec.get("previous"), dict) else ""}
            move_pm_tasks_to_pane(repo, old_pm_panes, f"hc:{term}", ctx=self.ctx)
            record_swap_notice(repo, eff_reason, by=f"hc:{term}", ctx=self.ctx)
            deliver_mod.Delivery(self.ctx, repo).ensure_running()
            # End the outgoing session's process group once its turn and background work finish (or immediately when force=True).
            warn = self._end_session_later(repo, term, agent_pid=agent_pid, kill_terminal=False, force=force)
            lines = [*([] if not warn else [warn]), tr(
                f"next PM session queued in seat hc:{term} (in the same terminal); the outgoing session ends once its turn "
                "is over" + (". End this turn briefly (one short line); the new session takes over next." if is_self else "."),
                f"下一任 PM 会话已排入座位 hc:{term}（同一个终端）；当前会话在这一轮结束后退出并交棒"
                + ("。简短结束这一轮即可（一句话收尾），下一任会话马上接手。" if is_self else "。"))]
            return RotateResult(mode="seat", lines=lines)

        # Legacy non-seat PM: perform one last terminal rotation so the PM enters a fixed `pm.py seat` terminal.
        s_argv = seat_argv(repo, argv, kind=kind, prompt="" if self.ctx.agents.takes_prompt(kind) else prompt, ctx=self.ctx)
        started = self._start_pm_terminal_result(repo, s_argv, (old.get("labels") or {}).get("herdr.space"))
        made = started.terminal
        if not made:
            raise Refused("could not start the new PM seat; the old PM stays registered")
        retired = term
        self.ctx.hc.keep(made)
        self.ctx.hc.label(made, f"pm={name}", "pm.seat=1")
        self.ctx.hc.label(retired, "pm=")

        def _rotate_legacy_into_seat(cur: dict[str, Any] | None) -> dict[str, Any]:
            fresh = dict(cur) if cur is not None else dict(rec)
            fresh["agent_session"] = None
            cur_ep = record_endpoint(fresh) or parse_legacy_endpoint(f"hc:{made}", runtime_hint="hc")
            next_epoch = int((cur_ep.epoch if cur_ep else 1) or 1) + 1
            ep_dict = {**(cur_ep.to_dict() if cur_ep else {"runtime": "hc", "machine": None}), "terminal": made, "epoch": next_epoch, "agent_kind": kind}
            fresh.update({"pane": f"hc:{made}", "terminal": made, "seat": True, "claimed": self.ctx.clock.now(),
                          "agent": kind, "endpoint": ep_dict, "epoch": next_epoch,
                          "previous": {**previous, "terminal": retired},
                          "rotations": fresh.get("rotations", 0) + 1})
            return fresh

        self.ctx.store.change_registration(project_slug(repo), _rotate_legacy_into_seat)
        rotated_ep = parse_legacy_endpoint(f"hc:{made}", runtime_hint="hc")
        new_reg_after = self.ctx.store.registration(project_slug(repo)) or {}
        TurnTracker(self.ctx, repo).pm_mailbox.requeue_unconsumed_on_epoch_change(
            int(new_reg_after.get("epoch") or 1), endpoint_uid=rotated_ep.uid if rotated_ep else ""
        )
        old_pm_panes = {rec.get("pane"), f"hc:{retired}", (rec.get("previous") or {}).get("pane")
                        if isinstance(rec.get("previous"), dict) else ""}
        move_pm_tasks_to_pane(repo, old_pm_panes, f"hc:{made}", ctx=self.ctx)
        record_swap_notice(repo, eff_reason, by=f"hc:{made}", ctx=self.ctx)
        deliver_mod.Delivery(self.ctx, repo).ensure_running()
        self.ctx.hc.name_tab(made, pm_tab_name(repo))
        self.ctx.hc.name_tab(retired, "", only_if=pm_tab_name(repo))
        warn = self._end_session_later(repo, retired, kill_terminal=True, force=force)
        no_tab = [] if started.has_tab else [launch_mod.no_tab_warning(made, ctx=self.ctx)]
        lines = [*([] if not warn else [warn]), *no_tab, tr(
            f"new PM seat started in hc:{made} (migrated from legacy PM hc:{retired}); hc:{retired} ends once its "
            "turn is over"
            + (". End this turn briefly (one short line); the new session takes over next." if is_self else "."),
            f"新 PM 座位已在 hc:{made} 启动（从旧式 PM hc:{retired} 迁入座位）；hc:{retired} 在这一轮结束后自动关掉"
            + ("。简短结束这一轮即可（一句话收尾），下一任会话马上接手。" if is_self else "。"))]
        return RotateResult(mode="legacy_to_seat", lines=lines)

    def seat(
        self,
        repo_arg: str | Path,
        argv_raw: Sequence[str],
        *,
        kind: str = "",
        prompt: str = "",
        no_shell: bool = False,
    ) -> SeatResult:
        """Run inside the project's fixed PM terminal and host one PM session after another across rotations."""
        tr = self.ctx.config.tr
        repo = self.ctx.git.project_root(repo_arg)
        if not repo:
            raise Refused(f"{repo_arg} is not a directory")
        argv = list(argv_raw[1:] if list(argv_raw[:1]) == ["--"] else argv_raw)
        if not argv:
            raise Refused("pm.py seat requires an agent command after `--`")
        proj_files = self.ctx.home.project_for(repo)
        lock_path = proj_files.ensure() / "seat.lock"
        lock_fh = open(lock_path, "a+")
        try:
            lock_file(lock_fh)
        except OSError:
            holder = read_seat_state(repo, ctx=self.ctx)
            lock_fh.close()
            where = f" in hc:{holder['terminal']}" if holder.get("terminal") else ""
            raise Refused(f"PM seat for {Path(repo).name} is already running{where} (pid {holder.get('pid') or '?'})")
        if not osutil.WINDOWS:
            with contextlib.suppress(OSError):
                os.set_inheritable(lock_fh.fileno(), False)
        live = self.projects.find_pm(repo=repo)
        if live and self.ctx.pane and live["pane_id"] != self.ctx.pane:
            unlock_file(lock_fh)
            lock_fh.close()
            raise Refused(f"PM for {Path(repo).name} already exists at {live['pane_id']}; refusing second seat")
        # Discard any leftover next-session.json from before this seat process started.
        proj_files.next_session.unlink(missing_ok=True)

        tty_fd, saved_termios = None, None
        if not osutil.WINDOWS and sys.stdin.isatty() and sys.stdout.isatty():
            try:
                tty_fd = os.dup(sys.stdin.fileno())
                os.set_inheritable(tty_fd, False)
                if termios is not None:
                    saved_termios = termios.tcgetattr(tty_fd)
            except OSError:
                if tty_fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(tty_fd)
                tty_fd, saved_termios = None, None

        stopping, active_proc = [False], [None]
        saved_signals: dict[Any, Any] = {}

        def _on_stop(signum: int, _frame: Any) -> None:
            stopping[0] = True
            proc = active_proc[0]
            if proc is not None and proc.poll() is None:
                if osutil.WINDOWS:
                    osutil.stop_pid_group(proc.pid)
                else:
                    with contextlib.suppress(OSError):
                        os.killpg(proc.pid, signum)

        if osutil.WINDOWS:
            for sig_name in ("SIGTERM", "SIGBREAK"):
                sig = getattr(signal, sig_name, None)
                if sig is not None:
                    with contextlib.suppress(OSError, ValueError):
                        saved_signals[sig] = signal.getsignal(sig)
                        signal.signal(sig, _on_stop)
        else:
            for sig_name, handler in (("SIGINT", signal.SIG_IGN), ("SIGTTOU", signal.SIG_IGN),
                                      ("SIGTTIN", signal.SIG_IGN), ("SIGTERM", _on_stop), ("SIGHUP", _on_stop)):
                sig = getattr(signal, sig_name, None)
                if sig is not None:
                    with contextlib.suppress(OSError, ValueError):
                        saved_signals[sig] = signal.getsignal(sig)
                        signal.signal(sig, handler)

        win_job = _create_win_kill_job() if osutil.WINDOWS else None
        had_tty = tty_fd is not None
        last_rc = 0
        hc_term = self.ctx.hc_terminal
        try:
            spec: dict[str, Any] | None = {
                "argv": argv,
                "kind": kind or self.ctx.agents.kind_from_argv(argv) or "claude",
                "prompt": prompt or "",
                "rotated_in": False,
                "is_fallback": False,
            }
            seq = 0
            while spec is not None and not stopping[0]:
                seq += 1
                _reclaim_tty(tty_fd)
                _reset_seat_tty(tty_fd, saved_termios, flush_input=(seq > 1))
                cur_kind = spec.get("kind") or self.ctx.agents.kind_from_argv(spec["argv"]) or "claude"
                base_turn = ((self.ctx.hc.get_raw(hc_term) or {}).get("turn") or 0) if hc_term else 0
                if spec.get("rotated_in") and hc_term:
                    self.ctx.hc.label(hc_term, f"pm={Path(repo).name}", "pm.seat=1")
                proc = _spawn_seat_child(spec["argv"], repo, successor_env(ctx=self.ctx), win_job=win_job)
                active_proc[0] = proc
                _hand_tty_to_child(tty_fd, proc.pid)
                write_seat_state(repo, {"pid": os.getpid(), "terminal": hc_term, "agent_pid": proc.pid,
                                        "kind": cur_kind, "argv": spec["argv"], "started_at": self.ctx.clock.now(),
                                        "session_seq": seq}, ctx=self.ctx)
                if spec.get("prompt") and hc_term:
                    _seat_prompt_sender(proc, hc_term, cur_kind, spec["prompt"], repo=repo, ctx=self.ctx)
                started_ok, fail_reason = _wait_seat_session(
                    repo, proc, cur_kind, base_turn,
                    rotated_in=bool(spec.get("rotated_in") and not spec.get("is_fallback")),
                    stopping=stopping,
                    ctx=self.ctx,
                )
                last_rc = proc.wait()
                active_proc[0] = None
                _reclaim_tty(tty_fd)
                write_seat_state(repo, {"pid": os.getpid(), "terminal": hc_term, "agent_pid": None,
                                        "kind": cur_kind, "argv": spec["argv"], "started_at": self.ctx.clock.now(),
                                        "session_seq": seq}, ctx=self.ctx)
                if stopping[0]:
                    break
                nxt, expired_nxt = pop_next_session(repo, ctx=self.ctx)
                if nxt is not None:
                    spec = {**nxt, "rotated_in": True, "is_fallback": False}
                    continue
                if expired_nxt is not None:
                    why = tr(f"queued rotation expired after {SEAT_NEXT_MAX_AGE}s",
                             f"排队的轮换已超过 {SEAT_NEXT_MAX_AGE} 秒过期")
                    spec = build_fallback_spec(repo, expired_nxt, why, ctx=self.ctx)
                    continue
                if spec.get("rotated_in") and not spec.get("is_fallback") and not started_ok:
                    spec = build_fallback_spec(repo, spec, fail_reason, ctx=self.ctx)
                    continue
                spec = None
        finally:
            _reclaim_tty(tty_fd)
            _reset_seat_tty(tty_fd, saved_termios, flush_input=False)
            if tty_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(tty_fd)
            _close_win_job(win_job)
            proj_files.seat_state.unlink(missing_ok=True)
            if stopping[0]:
                proj_files.next_session.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                unlock_file(lock_fh)
            lock_fh.close()
            for sig, prev_handler in saved_signals.items():
                with contextlib.suppress(OSError, ValueError):
                    signal.signal(sig, prev_handler)

        exec_shell = not stopping[0] and not osutil.WINDOWS and not no_shell and had_tty
        return SeatResult(exit_code=last_rc, exec_shell=exec_shell)

    def end_session(
        self,
        terminal: str,
        *,
        repo_arg: str | Path | None = None,
        agent_pid: int | None = None,
        kill_terminal: bool = False,
        timeout: float = RETIRE_WAIT,
        force: bool = False,
    ) -> None:
        """Wait until the outgoing PM session finishes its turn and any non-wait background commands (two quiet looks in
        a row), then end its process group (or stop immediately without waiting when `force=True`)."""
        tr = self.ctx.config.tr
        repo = self.ctx.git.project_root(repo_arg) if repo_arg else ""
        target_pid = agent_pid
        if force:
            info = self.ctx.hc.get_raw(terminal) or {}
            if info.get("state") != "live":
                return
            if kill_terminal:
                if not (info.get("labels") or {}).get("pm"):
                    self.ctx.hc.kill(terminal)
                return
            seat = read_seat_state(repo, ctx=self.ctx) if repo else {}
            cur_pid = seat.get("agent_pid")
            pid = target_pid or cur_pid
            if not pid:
                return
            if target_pid and cur_pid is not None and cur_pid != target_pid:
                return
            if osutil.pid_alive(pid):
                osutil.stop_pid_group(pid)
            return
        deadline, quiet = self.ctx.clock.time() + timeout, 0
        while self.ctx.clock.time() < deadline:
            info = self.ctx.hc.get_raw(terminal) or {}
            if info.get("state") != "live":
                return
            if kill_terminal:
                if (info.get("labels") or {}).get("pm"):
                    return
                busy = (info.get("status") or {}).get("state") == "working" or bool(self._background_work(info))
                quiet = 0 if busy else quiet + 1
                if quiet >= 2:
                    self.ctx.hc.kill(terminal)
                    return
            else:
                seat = read_seat_state(repo, ctx=self.ctx) if repo else {}
                cur_pid = seat.get("agent_pid")
                pid = target_pid or cur_pid
                if not pid:
                    return
                if target_pid and cur_pid is not None and cur_pid != target_pid:
                    return  # `seat` has already started the next session
                if not osutil.pid_alive(pid):
                    return
                busy = ((info.get("status") or {}).get("state") == "working"
                        or bool(self._background_work({"pid": pid})))
                quiet = 0 if busy else quiet + 1
                if quiet >= 2:
                    seat_now = read_seat_state(repo, ctx=self.ctx) if repo else {}
                    if target_pid and seat_now.get("agent_pid") not in (None, target_pid):
                        return
                    osutil.stop_pid_group(pid)
                    return
            self.ctx.clock.sleep(RETIRE_LOOK)
        if kill_terminal:
            still_running(terminal, self._background_work(self.ctx.hc.get_raw(terminal) or {}), ctx=self.ctx)
            return
        if repo:
            seat_now = read_seat_state(repo, ctx=self.ctx)
            if target_pid and seat_now.get("agent_pid") not in (None, target_pid):
                return  # already rotated into a newer session
            restore_cancelled_rotation(repo, terminal, ctx=self.ctx)
            work = self._background_work({"pid": target_pid or (seat_now.get("agent_pid") or 0)})
            what = "; ".join(work) or tr("its turn", "它这一轮")
            said = tr(
                f"The outgoing PM session in hc:{terminal} still ran ({what}) {int(timeout) // 60} min after "
                "rotate, so the rotation was cancelled and the current session stays.",
                f"座位 hc:{terminal} 里的当前 PM 会话在轮换 {int(timeout) // 60} 分钟后还在跑（{what}），"
                "已取消这次轮换，保留当前会话继续工作。",
            )
            Conversation(self.ctx, repo).record("pm", text=said, by=f"hc:{terminal}", notice=True)

    def name_agent(self, pane: str, name: str, *, wait: float = NAME_WAIT) -> bool:
        return _name_agent(pane, name, wait=wait, ctx=self.ctx)
