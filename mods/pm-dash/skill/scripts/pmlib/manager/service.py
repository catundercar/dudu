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
from typing import Any, Callable, Mapping, Sequence

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
from ..ledger.task import ACTIVE
from ..messaging.address import parse_legacy_endpoint
from ..osutil import shell_join, slugify
from ..project.conversation import Conversation
from ..project.project import (
    ProjectRegistry,
    backfill_space_id,
    pm_name,
    project_display_name,
    validate_project_display_name,
)
from ..project.turn_reducer import record_endpoint
from ..project.turn_state import TurnTracker
from ..store import (
    disambiguate_folder_alias,
    lock_file,
    normalize_folder_alias,
    project_folders,
    registration_slug,
    replace_task_file,
    sync_registration_folders,
    unlock_file,
    valid_slug,
    write_atomic,
)
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
    slug: str = ""
    name: str = ""
    display_name: str = ""
    cwd: str = ""
    space_id: str = ""
    space_name: str = ""
    folders: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ArchiveResult:
    project: str
    paused: int
    already_archived: str | None = None
    lines: list[str] = field(default_factory=list)
    slug: str = ""
    space_id: str = ""
    terminal: str = ""
    space_closed: bool = False
    space_kept: bool = False


@dataclass
class RestoreResult:
    project: str
    restored: int
    terminal: str = ""
    not_archived: bool = False
    lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    slug: str = ""
    name: str = ""
    display_name: str = ""
    cwd: str = ""
    space_id: str = ""
    space_name: str = ""
    space_reused: bool = False


@dataclass
class RotateResult:
    mode: str
    lines: list[str] = field(default_factory=list)


@dataclass
class SeatResult:
    exit_code: int = 0
    exec_shell: bool = False


@dataclass
class RenameResult:
    slug: str
    name: str
    project: str
    display_name: str
    previous_name: str
    tab_renamed: bool = False
    space_renamed: bool = False


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
        *,
        display_name: str | None = None,
        no_app_space: bool = False,
    ) -> launch_mod.StartTerminalResult:
        if getattr(self.ctx, "_legacy", False) and launch_mod.start_pm_terminal is not launch_mod._DEFAULT_START_PM_TERMINAL:
            return launch_mod.StartTerminalResult(
                terminal=launch_mod.start_pm_terminal(repo, argv, space, new_space),
                has_tab=True,
            )
        return launch_mod._start_pm_terminal_result(
            repo,
            argv,
            space,
            new_space,
            display_name=display_name,
            no_app_space=no_app_space,
            ctx=self.ctx,
        )

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

    def _allocate_slug(self, base_name: str, *, existing_slug: str = "") -> str:
        if existing_slug and valid_slug(existing_slug):
            return existing_slug
        raw = slugify(base_name)[:28].strip("-")
        if not raw or not valid_slug(raw):
            raw = "project"
        cand = raw
        n = 2
        while (
            self.ctx.store.has_project(cand)
            or (self.ctx.home.registrations / f"{cand}.json").exists()
        ):
            suffix = f"-{n}"
            cand = f"{raw[:28 - len(suffix)].strip('-') or 'project'}{suffix}"
            n += 1
        return cand

    def _build_folder_entries(self, raw_folders: Sequence[str | Path]) -> list[dict[str, Any]]:
        tr = self.ctx.config.tr
        entries: list[dict[str, Any]] = []
        seen_resolved: set[str] = set()
        for raw in raw_folders:
            raw_str = str(raw or "").strip()
            if not raw_str:
                continue
            expanded = Path(raw_str).expanduser()
            if not expanded.is_dir():
                raise Refused(tr(f"{raw_str} is not a directory", f"{raw_str} 不是有效目录"))
            resolved = str(expanded.resolve())
            if resolved in seen_resolved:
                continue
            seen_resolved.add(resolved)
            is_git, default_branch = self._folder_git_info(Path(resolved))
            alias = disambiguate_folder_alias(Path(resolved), [f["alias"] for f in entries])
            item: dict[str, Any] = {"path": resolved, "alias": alias, "git": is_git}
            if default_branch:
                item["default_branch"] = default_branch
            entries.append(item)
        return entries

    def claim(
        self,
        repo_arg: str | Path,
        *,
        pane: str | None = None,
        kind: str | None = None,
        from_start: bool = False,
        display_name: str | None = None,
        discord_channel: str | None = None,
        discord_users: str | None = None,
        slug: str | None = None,
        folders: list[dict[str, Any]] | None = None,
        space_id: str | None = None,
    ) -> ClaimResult:
        eff_pane = pane or self.ctx.pane
        if not eff_pane:
            raise Refused("not running inside a herdr pane; pass --pane")
        repo = self.ctx.git.project_root(repo_arg)
        if not repo:
            raise Refused(f"{repo_arg} is not a directory")
        eff_slug = str(slug or "").strip() if (slug and valid_slug(slug)) else ""
        existing_rec = (self.ctx.store.registration(eff_slug) if eff_slug else None) or self.projects.pm_record(repo) or {}
        if not eff_slug:
            eff_slug = registration_slug(existing_rec) or project_slug(repo)
        explicit_display = str(display_name or "").strip()
        is_zero_folder = folders is not None and len(folders) == 0
        eff_display = explicit_display or project_display_name(existing_rec, "" if is_zero_folder else repo) or eff_slug
        pm = self.projects.find_pm(repo=eff_slug if is_zero_folder else repo)
        if pm and pm["pane_id"] != eff_pane:
            raise Refused(f"PM for {eff_display} already exists at {pm['pane_id']}; ask the user before replacing it")
        name = f"pm-{eff_slug}" if slug else pm_name(repo)
        eff_kind = kind or ""
        channel = discord_channel
        dm = self._discord() if channel else None
        if dm is not None:
            dm.require_on()
        if dm is not None and not dm.token():
            raise Refused(f"no bot token: put DISCORD_BOT_TOKEN=... in {dm.token_file}")
        start_seat_in_pane = False
        seated = False
        info: dict[str, Any] = {}
        pm_label = eff_slug if folders is not None else Path(repo).name
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
            labels = [f"pm={pm_label}", *(["pm.seat=1"] if seated else [])]
            if self.ctx.hc.label(term, *labels) is None:
                raise Refused(f"hc label {term} failed")
            if seated:
                self.ctx.hc.keep(term)
            self.ctx.hc.name_tab(term, pm_tab_name(repo, eff_display))
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
        detected_space_id = str(space_id or "").strip()
        if not detected_space_id and eff_pane.startswith("hc:"):
            detected_space_id = str((info.get("labels") or {}).get("herdr.space") or "").strip()

        def _claim(cur: dict[str, Any] | None) -> dict[str, Any]:
            nonlocal was_app
            rec = dict(cur) if cur is not None else {}
            old_pane = rec.get("pane")
            if old_pane:
                prev_panes.add(old_pane)
            prev_prev = (rec.get("previous") or {}).get("pane") if isinstance(rec.get("previous"), dict) else ""
            if prev_prev:
                prev_panes.add(prev_prev)
            proj_field = eff_slug if is_zero_folder else Path(repo).name
            rec.update({"project": proj_field, "repo": "" if is_zero_folder else repo, "name": name,
                        "pane": eff_pane, "workspace": workspace, "claimed": self.ctx.clock.now()})
            if folders is not None:
                sync_registration_folders(rec, folders, slug=eff_slug)
            elif slug:
                rec["slug"] = eff_slug
            if explicit_display:
                rec["display_name"] = explicit_display
            if detected_space_id and (space_id or not rec.get("space_id")):
                rec["space_id"] = detected_space_id
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

        self.ctx.store.change_registration(eff_slug, _claim)
        if eff_pane.startswith("hc:") and prev_panes:
            move_pm_tasks_to_pane(repo, prev_panes, eff_pane, slug=eff_slug, ctx=self.ctx)
        lines = [f"{eff_pane} is now {name} (PM for {eff_display})"]
        exec_argv: list[str] | None = None
        if eff_pane.startswith("hc:"):
            if not was_app:
                # A new desktop-app PM (or one that ran in the herdr TUI, which had its inbox): what the log already
                # holds is for the handover, not a delivery.
                log = self.ctx.home.project(eff_slug).ensure() / "conversation.jsonl"
                deliver_mod.Delivery(self.ctx, repo, slug=eff_slug).advance_delivered(log.stat().st_size if log.exists() else 0)
            if start_seat_in_pane:
                s_argv, _ = build_pm_seat_command(repo, eff_kind, "", display_name=eff_display, ctx=self.ctx)
                if eff_pane == self.ctx.pane and _is_real_hc(self.ctx) and sys.stdin.isatty() and sys.stdout.isatty():
                    deliver_mod.Delivery(self.ctx, repo, slug=eff_slug).ensure_running()
                    return ClaimResult(pane=eff_pane, name=name, project=eff_slug if is_zero_folder else Path(repo).name, lines=lines, exec_argv=s_argv)
                self.ctx.hc.bootstrap_shell_exec(eff_pane[3:], "exec " + shell_join(s_argv))
            deliver_mod.Delivery(self.ctx, repo, slug=eff_slug).ensure_running()
        if sdir and eff_pane == self.ctx.pane and self.ctx.env.get("DISCORD_STATE_DIR") != str(sdir):
            lines.append("restart to connect Discord:\n  " + self.launch_command(repo, resume="<session id>"))
        if eff_pane != self.ctx.pane and not eff_pane.startswith("hc:"):
            flags = self.launch_command(repo)[len("claude "):] if channel else "<your usual flags>"
            lines.append(f"start it: herdr agent start {name} --kind {eff_kind or 'claude'} --pane {eff_pane} -- {flags}")
        return ClaimResult(pane=eff_pane, name=name, project=eff_slug if is_zero_folder else Path(repo).name, lines=lines, exec_argv=exec_argv)

    def handover(self, repo_arg: str | Path, *, turns: int = 6, full: bool = False, compact: bool = False) -> str:
        repo = self.ctx.git.project_root(repo_arg)
        if not repo:
            raise Refused(f"{repo_arg} is not a directory")
        return handover_text(repo, turns=turns, full=full, compact=compact, ctx=self.ctx)

    def start(
        self,
        repo_arg: str | Path | None = None,
        *,
        folders: Sequence[str | Path] | None = None,
        kind: str | None = None,
        model: str | None = None,
        name: str | None = None,
        space: str | None = "new",
        space_id: str | None = None,
        prompt: str | None = None,
        no_app_space: bool = False,
        slug: str | None = None,
    ) -> StartResult:
        """Start a PM session of any agent kind for a project (0..N equal folders) in a fixed PM seat (`pm.py seat`)
        and hand it the project's record."""
        tr = self.ctx.config.tr
        if slug is not None and str(slug).strip() and not valid_slug(str(slug).strip()):
            raise Refused(tr(f"invalid project slug: {slug}", f"无效的项目标识：{slug}"))
        explicit_name = (name or "").strip()
        if explicit_name:
            try:
                explicit_name = validate_project_display_name(explicit_name, tr=tr)
            except ValueError as err:
                raise Refused(str(err)) from err

        folder_inputs: list[str | Path] = list(folders) if folders is not None else []
        if repo_arg is not None and str(repo_arg).strip():
            folder_inputs.append(repo_arg)

        folder_entries: list[dict[str, Any]] | None = None
        if folders is not None:
            folder_entries = self._build_folder_entries(folder_inputs)
            if folder_entries:
                first_repo = folder_entries[0]["path"]
                existing_rec = (self.ctx.store.registration(slug) if slug else None) or self.projects.pm_record(first_repo) or {}
                target_slug = (
                    str(slug).strip()
                    if (slug and valid_slug(slug))
                    else (registration_slug(existing_rec) if isinstance(existing_rec, dict) and registration_slug(existing_rec)
                          else self._allocate_slug(explicit_name or Path(first_repo).name))
                )
                work_dir = first_repo
            else:
                if not explicit_name and not (slug and valid_slug(slug)):
                    raise Refused(tr("a 0-folder project requires --name", "零文件夹项目必须指定 --name 项目名称"))
                target_slug = (
                    str(slug).strip()
                    if (slug and valid_slug(slug))
                    else self._allocate_slug(explicit_name)
                )
                existing_rec = self.ctx.store.registration(target_slug) or {}
                work_dir = str(self.ctx.home.project(target_slug).ensure())
        else:
            if not folder_inputs:
                if explicit_name or (slug and valid_slug(slug)):
                    target_slug = (
                        str(slug).strip()
                        if (slug and valid_slug(slug))
                        else self._allocate_slug(explicit_name)
                    )
                    existing_rec = self.ctx.store.registration(target_slug) or {}
                    existing_folders = project_folders(existing_rec) if isinstance(existing_rec, dict) else []
                    if existing_folders:
                        folder_entries = existing_folders
                        work_dir = existing_folders[0]["path"]
                    else:
                        folder_entries = []
                        work_dir = str(self.ctx.home.project(target_slug).ensure())
                else:
                    raise Refused("missing --repo or --name")
            else:
                raw_repo = folder_inputs[0]
                if not Path(raw_repo).is_dir():
                    raise Refused(f"{raw_repo} is not a directory")
                repo = self.ctx.git.project_root(raw_repo)
                if not repo:
                    raise Refused(f"{raw_repo} is not a directory")
                existing_rec = (self.ctx.store.registration(slug) if slug else None) or self.projects.pm_record(repo) or {}
                target_slug = (
                    str(slug).strip()
                    if (slug and valid_slug(slug))
                    else (registration_slug(existing_rec) if isinstance(existing_rec, dict) and registration_slug(existing_rec)
                          else project_slug(repo))
                )
                work_dir = repo
                if isinstance(existing_rec, dict) and "folders" in existing_rec:
                    folder_entries = project_folders(existing_rec)

        rec = existing_rec if isinstance(existing_rec, dict) else {}
        existing_display = project_display_name(rec, "" if (folder_entries == []) else work_dir) or target_slug
        if rec.get("archived"):
            raise Refused(tr(
                f"{existing_display} is archived ({rec['archived']}); bring it back with `pm.py restore`",
                f"{existing_display} 已归档（{rec['archived']}）；用 `pm.py restore` 恢复",
            ))
        pm = self.projects.find_pm(repo=target_slug if folder_entries == [] else work_dir)
        if pm:
            raise Refused(f"PM for {existing_display} already exists at {pm['pane_id']}; use `pm.py rotate` to replace it")
        was_existing = bool(rec and Conversation(self.ctx, work_dir, slug=target_slug).events())
        cfg = self.ctx.config.read().get("pm") or {}
        eff_kind = kind or cfg.get("kind") or "claude"
        if explicit_name and self.projects.find_display_name_conflict(explicit_name, exclude_slug=target_slug):
            raise Refused(tr(
                f'a project named "{explicit_name}" already exists',
                f'已存在名为「{explicit_name}」的项目',
            ))
        eff_name = explicit_name or existing_display
        own = (self.ctx.hc.get_raw(self.ctx.hc_terminal) or {}) if self.ctx.hc_terminal else {}
        current = (space or "new") == "current"
        stderr_lines: list[str] = []
        explicit_prompt = bool(prompt)  # restore passes prompt=...
        s_argv, _, _ = build_pm_seat_parts(work_dir, eff_kind, model, prompt=prompt, display_name=eff_name, ctx=self.ctx)
        made: str | None = None
        # If a previous seat exited to a recovery shell in the fixed PM terminal, revive `pm.py seat` in that same terminal.
        old_term = rec.get("terminal") if rec.get("runtime") == "hc" and rec.get("seat") else ""
        pm_label_expected = {
            x for x in (target_slug, Path(work_dir).name, str(rec.get("project") or "")) if x
        }
        if old_term and not seat_running(work_dir, ctx=self.ctx):
            old_info = self.ctx.hc.get_raw(old_term) or {}
            if ((old_info.get("labels") or {}).get("pm") in pm_label_expected and is_shell_terminal(old_info)
                    and self.ctx.hc.bootstrap_shell_exec(old_term, "exec " + shell_join(s_argv)) is not None):
                made = old_term
                self.ctx.hc.keep(made)
                self.ctx.hc.label(made, f"pm={target_slug if folder_entries is not None else Path(work_dir).name}", "pm.seat=1")
        started_tab = True
        resolved_space_id = str(space_id or "").strip()
        if not made:
            req_space = resolved_space_id or (own.get("labels") or {}).get("herdr.space")
            req_new_space = "" if (current or resolved_space_id) else eff_name
            started = self._start_pm_terminal_result(
                work_dir,
                s_argv,
                req_space,
                req_new_space,
                display_name=eff_name,
                no_app_space=no_app_space,
            )
            made = started.terminal
            started_tab = started.has_tab
            if started.space_id:
                resolved_space_id = started.space_id
        if not made:
            raise Refused("could not start the PM session (is herdr-core running?)")
        if not resolved_space_id and not no_app_space:
            made_info = self.ctx.hc.get_raw(made) or {}
            resolved_space_id = str((made_info.get("labels") or {}).get("herdr.space") or "").strip()
        claim_lines: list[str] = []
        try:
            if self._claim_hook is not None:
                self._claim_hook(work_dir, f"hc:{made}", eff_kind, True)
            else:
                claim_kw: dict[str, Any] = {
                    "pane": f"hc:{made}",
                    "kind": eff_kind,
                    "from_start": True,
                    "display_name": explicit_name or None,
                }
                if folder_entries is not None:
                    claim_kw["folders"] = folder_entries
                    claim_kw["slug"] = target_slug
                elif slug:
                    claim_kw["slug"] = target_slug
                if resolved_space_id:
                    claim_kw["space_id"] = resolved_space_id
                claim_res = self.claim(work_dir, **claim_kw)
                claim_lines.extend(claim_res.lines)
        except (SystemExit, PmError):
            if made != old_term:
                self.ctx.hc.kill(made)
                self.ctx.hc.remove(made)
            raise
        if not started_tab and not no_app_space:
            claim_lines.append(launch_mod.no_tab_warning(made, ctx=self.ctx))
        if was_existing and not explicit_prompt:
            record_swap_notice(work_dir, tr("session recovery", "重启恢复"), by=f"hc:{made}", slug=target_slug, ctx=self.ctx)

        def _finalize_start(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            if cur is None:
                return None
            if explicit_name:
                cur["display_name"] = explicit_name
            elif folder_entries is not None and not cur.get("display_name"):
                cur["display_name"] = eff_name
            if (not current or resolved_space_id) and not no_app_space:
                cur["space_name"] = cur.get("space_name") or eff_name if (current and resolved_space_id) else eff_name
            elif no_app_space and explicit_name:
                cur["space_name"] = explicit_name
            if resolved_space_id:
                cur["space_id"] = resolved_space_id
            if folder_entries is not None:
                sync_registration_folders(cur, folder_entries, slug=target_slug)
            elif target_slug:
                cur["slug"] = target_slug
            return cur

        final_rec = self.ctx.store.change_registration(target_slug, _finalize_start) or {}
        if isinstance(final_rec, dict) and final_rec:
            launch_mod.sync_pm_folder_settings(self.ctx, target_slug, final_rec)
        return StartResult(
            terminal=made,
            lines=claim_lines,
            stderr_lines=stderr_lines,
            slug=target_slug,
            name=str(final_rec.get("name") or f"pm-{target_slug}"),
            display_name=project_display_name(final_rec, "" if folder_entries == [] else work_dir) or eff_name,
            cwd=work_dir,
            space_id=str(final_rec.get("space_id") or resolved_space_id or ""),
            space_name=str(final_rec.get("space_name") or ""),
            folders=project_folders(final_rec),
        )

    def set_space(
        self,
        project: str | Path,
        space_id: str,
        *,
        space_name: str | None = None,
    ) -> dict[str, Any]:
        """Bind `space_id` (and optional `space_name`) to a project registration (`pms/<slug>.json`)."""
        tr = self.ctx.config.tr
        slug = self.projects.resolve_project_slug(str(project))
        rec = self.ctx.store.registration(slug) if slug else None
        if not isinstance(rec, dict):
            raise NotFound(f"no project {project}")
        repo_hint = str(rec.get("repo") or slug)
        role, _ = self._caller().memory_writer(repo_hint)
        if role not in ("user", "pm"):
            raise Refused(tr(
                "project space bindings are managed by the user (or the PM), not by a worker",
                "项目空间绑定只能由用户（或 PM）修改，worker 不能改",
            ))
        clean_id = str(space_id or "").strip()
        if not clean_id:
            raise Refused(tr("space_id cannot be empty", "space_id 不能为空"))
        clean_name = ""
        if space_name is not None and str(space_name).strip():
            try:
                clean_name = validate_project_display_name(space_name, tr=tr)
            except ValueError as err:
                raise Refused(str(err)) from err

        def _apply(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            if cur is None:
                return None
            cur["space_id"] = clean_id
            if clean_name:
                cur["space_name"] = clean_name
            return cur

        updated = self.ctx.store.change_registration(slug, _apply)
        if not isinstance(updated, dict):
            raise NotFound(f"no project {project}")
        return {
            "ok": True,
            "slug": slug,
            "space_id": str(updated.get("space_id") or clean_id),
            "space_name": str(updated.get("space_name") or ""),
        }

    def rename(self, project: str | Path, new_name: str) -> RenameResult:
        """Rename a project's user-facing display name without changing its slug, tasks, or history."""
        tr = self.ctx.config.tr
        slug = self.projects.resolve_project_slug(str(project))
        rec = self.ctx.store.registration(slug) if slug else None
        if not isinstance(rec, dict):
            raise NotFound(f"no project {project}")
        repo = str(rec.get("repo") or "")
        role, _ = self._caller().memory_writer(repo or ".")
        if role not in ("user", "pm"):
            raise Refused(tr(
                "projects are renamed by the user (or the PM), not by a worker",
                "项目只能由用户（或 PM）重命名，worker 不能改",
            ))
        try:
            clean_name = validate_project_display_name(new_name, tr=tr)
        except ValueError as err:
            raise Refused(str(err)) from err
        if self.projects.find_display_name_conflict(clean_name, exclude_slug=slug):
            raise Refused(tr(
                f'a project named "{clean_name}" already exists',
                f'已存在名为「{clean_name}」的项目',
            ))
        previous_name = ""
        old_space_name = ""

        def _apply_rename(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal previous_name, old_space_name
            if cur is None:
                return None
            previous_name = project_display_name(cur, cur.get("repo"))
            old_space_name = str(cur.get("space_name") or "").strip()
            cur["display_name"] = clean_name
            if "space_name" in cur:
                cur["space_name"] = clean_name
            return cur

        updated = self.ctx.store.change_registration(slug, _apply_rename)
        if not isinstance(updated, dict):
            raise NotFound(f"no project {project}")
        tab_renamed = False
        space_renamed = False
        if updated.get("runtime") == "hc" and updated.get("terminal") and not updated.get("archived"):
            term = str(updated["terminal"])
            tab_renamed = bool(self.ctx.hc.name_tab(term, pm_tab_name(repo or slug, clean_name), wait=0))
            if clean_name != previous_name:
                old_candidates = {n for n in (previous_name, old_space_name, Path(repo).name if repo else "") if n}
                try:
                    open_spaces = self.ctx.hc.app_spaces()
                except Exception:
                    open_spaces = []
                want_repo = launch_mod._norm_dir(repo) if repo else ""
                for sp in open_spaces:
                    if not isinstance(sp, dict) or not sp.get("id") or sp.get("machine"):
                        continue
                    has_term = any(
                        t.get("terminal") == term
                        for tab in (sp.get("tabs") or [])
                        for t in (tab.get("terminals") or [])
                    )
                    if not has_term:
                        continue
                    sp_name = str(sp.get("name") or "").strip()
                    same_folder = bool(want_repo and launch_mod._norm_dir(sp.get("folder")) == want_repo)
                    if sp_name in old_candidates and (same_folder or (old_space_name and sp_name == old_space_name)):
                        if sp_name != clean_name:
                            try:
                                res_sp = self.ctx.hc.app_do("space.rename", {"id": sp["id"], "name": clean_name}, timeout=5)
                                space_renamed = res_sp.returncode == 0
                            except Exception:
                                space_renamed = False
                        break
        return RenameResult(
            slug=slug,
            name=str(updated.get("name") or f"pm-{slug}"),
            project=str(updated.get("project") or ""),
            display_name=clean_name,
            previous_name=previous_name,
            tab_renamed=tab_renamed,
            space_renamed=space_renamed,
        )

    def _folder_git_info(self, folder_path: Path) -> tuple[bool, str]:
        if not folder_path.is_dir():
            return False, ""
        is_git = bool(self.ctx.git.main_root(folder_path))
        default_branch = str(self.ctx.git.base_branch(folder_path) or "") if is_git else ""
        return is_git, default_branch

    def _notify_workspace_change(self, slug: str, rec: dict[str, Any], text: str) -> None:
        launch_mod.sync_pm_folder_settings(self.ctx, slug, rec)
        is_live_hc = bool(rec.get("runtime") == "hc" and rec.get("terminal") and not rec.get("archived"))
        repo = str(rec.get("repo") or "")
        Conversation(self.ctx, repo, slug=slug).record(
            "event",
            source="workspace",
            text=text,
            **({"wake": True} if is_live_hc else {}),
        )
        if is_live_hc:
            deliver_mod.Delivery(self.ctx, repo, slug=slug).ensure_running()

    def list_folders(self, project: str | Path) -> dict[str, Any]:
        """List all equal-status workspace folders linked to `project` with live directory/git status."""
        slug = self.projects.resolve_project_slug(str(project))
        rec = self.ctx.store.registration(slug) if slug else None
        if not isinstance(rec, dict):
            raise NotFound(f"no project {project}")
        enriched: list[dict[str, Any]] = []
        for entry in project_folders(rec):
            p = Path(entry["path"])
            exists = p.is_dir()
            if "git" in entry:
                is_git = bool(entry["git"])
                default_branch = str(entry.get("default_branch") or "")
                if is_git and not default_branch and exists:
                    default_branch = str(self.ctx.git.base_branch(p) or "")
            else:
                is_git, default_branch = self._folder_git_info(p)
            row: dict[str, Any] = {
                "path": entry["path"],
                "alias": entry["alias"],
                "git": is_git,
                "exists": exists,
            }
            if default_branch:
                row["default_branch"] = default_branch
            enriched.append(row)
        return {"project": slug, "folders": enriched}

    def add_folder(self, project: str | Path, folder_path: str, *, alias: str | None = None) -> dict[str, Any]:
        """Link an additional equal-status workspace folder to `project`."""
        tr = self.ctx.config.tr
        slug = self.projects.resolve_project_slug(str(project))
        rec = self.ctx.store.registration(slug) if slug else None
        if not isinstance(rec, dict):
            raise NotFound(f"no project {project}")
        repo_hint = str(rec.get("repo") or slug)
        role, _ = self._caller().memory_writer(repo_hint)
        if role not in ("user", "pm"):
            raise Refused(tr(
                "workspace folders are managed by the user (or the PM), not by a worker",
                "关联文件夹只能由用户（或 PM）增删，worker 不能改",
            ))
        raw_path = Path(str(folder_path or "").strip()).expanduser()
        if not str(folder_path or "").strip() or not raw_path.is_dir():
            raise Refused(tr(f"{folder_path} is not a directory", f"{folder_path} 不是有效目录"))
        resolved = raw_path.resolve()
        resolved_str = str(resolved)
        is_git, default_branch = self._folder_git_info(resolved)
        added_entry: dict[str, Any] = {}

        def _apply(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal added_entry
            if cur is None:
                return None
            folders: list[dict[str, Any]] = []
            for f in project_folders(cur):
                item = dict(f)
                if "git" not in item:
                    fg, fb = self._folder_git_info(Path(item["path"]))
                    item["git"] = fg
                    if fb:
                        item["default_branch"] = fb
                folders.append(item)
            for f in folders:
                with contextlib.suppress(OSError):
                    if str(Path(f["path"]).resolve()) == resolved_str:
                        raise Refused(tr(
                            f"{resolved_str} is already linked to {slug} as {f['alias']}",
                            f"{resolved_str} 已关联到 {slug}（别名 {f['alias']}）",
                        ))
            try:
                clean_alias = disambiguate_folder_alias(
                    resolved, [f["alias"] for f in folders], explicit_alias=alias
                )
            except ValueError as err:
                raise Refused(str(err)) from err
            added_entry = {"path": resolved_str, "alias": clean_alias, "git": is_git}
            if default_branch:
                added_entry["default_branch"] = default_branch
            folders.append(added_entry)
            return sync_registration_folders(cur, folders, slug=slug)

        updated = self.ctx.store.change_registration(slug, _apply)
        if not isinstance(updated, dict):
            raise NotFound(f"no project {project}")
        self._notify_workspace_change(slug, updated, f"[workspace] added folder {added_entry['alias']}: {resolved_str}")
        return {"ok": True, "project": slug, "added": added_entry, "folders": list(updated.get("folders") or [])}

    def remove_folder(self, project: str | Path, target: str, *, force: bool = False) -> dict[str, Any]:
        """Unlink a folder (by alias or path) from `project` without deleting files on disk."""
        tr = self.ctx.config.tr
        slug = self.projects.resolve_project_slug(str(project))
        rec = self.ctx.store.registration(slug) if slug else None
        if not isinstance(rec, dict):
            raise NotFound(f"no project {project}")
        repo_hint = str(rec.get("repo") or slug)
        role, _ = self._caller().memory_writer(repo_hint)
        if role not in ("user", "pm"):
            raise Refused(tr(
                "workspace folders are managed by the user (or the PM), not by a worker",
                "关联文件夹只能由用户（或 PM）增删，worker 不能改",
            ))

        def _match_idx(folders: list[dict[str, Any]]) -> int:
            for idx, f in enumerate(folders):
                if f.get("alias") == target:
                    return idx
            target_path = Path(target).expanduser()
            target_res = ""
            with contextlib.suppress(OSError):
                target_res = str(target_path.resolve())
            for idx, f in enumerate(folders):
                if f.get("path") == target:
                    return idx
                if target_res:
                    with contextlib.suppress(OSError):
                        if str(Path(f["path"]).resolve()) == target_res:
                            return idx
            return -1

        cur_folders = project_folders(rec)
        idx = _match_idx(cur_folders)
        if idx < 0:
            raise NotFound(tr(f"folder {target!r} is not linked to {slug}", f"项目 {slug} 未关联文件夹 {target!r}"))
        matched = cur_folders[idx]
        matched_res = ""
        with contextlib.suppress(OSError):
            matched_res = str(Path(matched["path"]).resolve())
        active_here: list[str] = []
        for t in self.ledger.project_tasks(slug):
            if t.status not in ACTIVE:
                continue
            t_repo = ""
            if t.repo:
                with contextlib.suppress(OSError):
                    t_repo = str(Path(t.repo).resolve())
            if (matched_res and t_repo == matched_res) or (matched.get("alias") and t.folder_alias == matched["alias"]):
                active_here.append(t.id)
        if active_here and not force:
            raise Refused(tr(
                f"{len(active_here)} active thread(s) still run in {matched['alias']} ({', '.join(active_here[:5])}); pass --force to unlink anyway",
                f"「{matched['alias']}」下仍有 {len(active_here)} 个进行中线程（{', '.join(active_here[:5])}），加 --force 可强制解除关联",
            ))

        removed_entry: dict[str, Any] = {}

        def _apply(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal removed_entry
            if cur is None:
                return None
            folders = project_folders(cur)
            hit = _match_idx(folders)
            if hit < 0:
                raise NotFound(tr(f"folder {target!r} is not linked to {slug}", f"项目 {slug} 未关联文件夹 {target!r}"))
            removed_entry = folders.pop(hit)
            return sync_registration_folders(cur, folders, slug=slug)

        updated = self.ctx.store.change_registration(slug, _apply)
        if not isinstance(updated, dict):
            raise NotFound(f"no project {project}")
        self._notify_workspace_change(
            slug, updated, f"[workspace] removed folder {removed_entry['alias']}: {removed_entry['path']}"
        )
        return {"ok": True, "project": slug, "removed": removed_entry, "folders": list(updated.get("folders") or [])}

    def rename_folder_alias(self, project: str | Path, target: str, new_alias: str) -> dict[str, Any]:
        """Rename a linked workspace folder's alias within `project`."""
        tr = self.ctx.config.tr
        slug = self.projects.resolve_project_slug(str(project))
        rec = self.ctx.store.registration(slug) if slug else None
        if not isinstance(rec, dict):
            raise NotFound(f"no project {project}")
        repo_hint = str(rec.get("repo") or slug)
        role, _ = self._caller().memory_writer(repo_hint)
        if role not in ("user", "pm"):
            raise Refused(tr(
                "workspace folders are managed by the user (or the PM), not by a worker",
                "关联文件夹只能由用户（或 PM）增删，worker 不能改",
            ))
        try:
            clean_alias = normalize_folder_alias(new_alias)
        except ValueError as err:
            raise Refused(str(err)) from err

        previous_alias = ""
        updated_entry: dict[str, Any] = {}

        def _apply(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal previous_alias, updated_entry
            if cur is None:
                return None
            folders = project_folders(cur)
            hit = -1
            for idx, f in enumerate(folders):
                if f.get("alias") == target:
                    hit = idx
                    break
            if hit < 0:
                target_res = ""
                with contextlib.suppress(OSError):
                    target_res = str(Path(target).expanduser().resolve())
                for idx, f in enumerate(folders):
                    if f.get("path") == target:
                        hit = idx
                        break
                    if target_res:
                        with contextlib.suppress(OSError):
                            if str(Path(f["path"]).resolve()) == target_res:
                                hit = idx
                                break
            if hit < 0:
                raise NotFound(tr(f"folder {target!r} is not linked to {slug}", f"项目 {slug} 未关联文件夹 {target!r}"))
            for idx, f in enumerate(folders):
                if idx != hit and str(f.get("alias") or "").casefold() == clean_alias.casefold():
                    raise Refused(tr(
                        f"folder alias {clean_alias!r} already exists in {slug}",
                        f"项目 {slug} 中已存在别名 {clean_alias!r}",
                    ))
            previous_alias = str(folders[hit].get("alias") or "")
            folders[hit] = {**folders[hit], "alias": clean_alias}
            updated_entry = dict(folders[hit])
            return sync_registration_folders(cur, folders, slug=slug)

        updated = self.ctx.store.change_registration(slug, _apply)
        if not isinstance(updated, dict):
            raise NotFound(f"no project {project}")
        return {
            "ok": True,
            "project": slug,
            "previous_alias": previous_alias,
            "alias": clean_alias,
            "folder": updated_entry,
            "folders": list(updated.get("folders") or []),
        }

    def _resolve_project_record(self, project: str | Path) -> tuple[str, dict[str, Any], str]:
        """Resolve `(slug, reg_dict, work_dir)` for a project given as folder, slug, PM name, or display name."""
        raw = str(project)
        slug = self.projects.resolve_project_slug(raw)
        rec = self.ctx.store.registration(slug) if (slug and valid_slug(slug)) else None
        if isinstance(rec, dict):
            rslug = registration_slug(rec) or slug
            folders = project_folders(rec)
            repo_val = str(rec.get("repo") or (folders[0]["path"] if folders else "") or "")
            work_dir = repo_val or str(self.ctx.home.project(rslug).root)
            return rslug, rec, work_dir
        repo = self.projects.registered_repo(project)
        rec2 = self.projects.pm_record(repo) if repo else None
        if isinstance(rec2, dict) and repo:
            rslug = registration_slug(rec2) or project_slug(repo)
            return rslug, rec2, repo
        raise NotFound(f"no PM registered for {project}")

    def _find_local_space_for_pm(
        self,
        open_spaces: Sequence[Mapping[str, Any]],
        *,
        space_id: str = "",
        terminal: str = "",
    ) -> Mapping[str, Any] | None:
        local = [s for s in open_spaces if isinstance(s, Mapping) and s.get("id") and not s.get("machine")]
        if space_id:
            for sp in local:
                if str(sp.get("id") or "") == space_id:
                    return sp
        if terminal:
            for sp in local:
                for tab in sp.get("tabs") or ():
                    for term in tab.get("terminals") or ():
                        if term.get("terminal") == terminal:
                            return sp
        return None

    def _close_idle_project_space(self, sp: Mapping[str, Any], pm_term: str) -> tuple[bool, bool]:
        """D1 smart close: fail-closed unless every non-PM terminal is confirmed finished or an idle default shell."""
        sp_id = str(sp.get("id") or "").strip()
        if not sp_id:
            return False, False
        tabs = sp.get("tabs")
        if not isinstance(tabs, Sequence) or isinstance(tabs, (str, bytes)):
            return False, True
        for tab in tabs:
            if not isinstance(tab, Mapping):
                return False, True
            raw_terms = tab.get("terminals")
            if not isinstance(raw_terms, Sequence) or isinstance(raw_terms, (str, bytes)):
                return False, True
            terms = [t for t in raw_terms if isinstance(t, Mapping)]
            if len(terms) != len(raw_terms):
                return False, True
            panes_count = tab.get("panes")
            if isinstance(panes_count, int) and panes_count > len(terms):
                return False, True
            for t in terms:
                addr = str(t.get("terminal") or "").strip()
                if not addr:
                    return False, True
                if pm_term and addr == pm_term:
                    continue
                try:
                    t_info = self.ctx.hc.get_raw(addr)
                except Exception:
                    return False, True
                if not isinstance(t_info, Mapping) or not t_info:
                    return False, True
                state = str(t_info.get("state") or "").strip()
                if state == "finished":
                    continue
                if state != "live":
                    return False, True
                if not is_shell_terminal(t_info) or bool(self._background_work(t_info)):
                    return False, True
        try:
            res = self.ctx.hc.app_do("space.close", {"id": sp_id, "confirmed": True}, timeout=10)
        except OSError:
            return False, True
        err_msg = launch_mod._app_reply_error(res)
        if res.returncode == 0 and not err_msg:
            return True, False
        return False, True

    def archive(self, project: str | Path) -> ArchiveResult:
        """Put a project away: its PM's session ends, its open tasks are paused, and its dedicated Space closes
        automatically when only the PM or idle shells remain (D1). The ledger, conversation, and handover stay."""
        tr = self.ctx.config.tr
        slug, rec, work_dir = self._resolve_project_record(project)
        repo_str = str(rec.get("repo") or "")
        label_name = Path(repo_str).name if repo_str else slug
        display_name = Path(repo_str).name if repo_str else (project_display_name(rec, "") or slug)
        pm_term = str(rec.get("terminal") or "").strip()
        if rec.get("archived"):
            already_archived = rec["archived"]
            return ArchiveResult(
                project=display_name,
                paused=0,
                already_archived=already_archived,
                lines=[tr(
                    f"{display_name} is already archived ({already_archived})",
                    f"{display_name} 已经归档（{already_archived}）",
                )],
                slug=slug,
                space_id=str(rec.get("space_id") or "").strip(),
                terminal=pm_term,
            )
        pm_info = (self.ctx.hc.get_raw(pm_term) or {}) if (rec.get("runtime") == "hc" and pm_term) else {}
        captured_space_id = str(
            rec.get("space_id") or (pm_info.get("labels") or {}).get("herdr.space") or ""
        ).strip()
        open_spaces = self.ctx.hc.app_spaces() if rec.get("runtime") == "hc" else []
        matched_space = self._find_local_space_for_pm(
            open_spaces, space_id=captured_space_id, terminal=pm_term
        ) if open_spaces else None
        if matched_space and not captured_space_id:
            captured_space_id = str(matched_space.get("id") or "").strip()
        already_archived = None

        def _archive_reg(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            nonlocal already_archived
            if cur is None:
                return None
            if cur.get("archived"):
                already_archived = cur["archived"]
                return None
            cur["agent_session"] = None
            cur["archived"] = self.ctx.clock.now()[:10]
            if captured_space_id and not cur.get("space_id"):
                cur["space_id"] = captured_space_id
            return cur

        rec = self.ctx.store.change_registration(slug, _archive_reg)
        if already_archived:
            return ArchiveResult(
                project=display_name,
                paused=0,
                already_archived=already_archived,
                lines=[tr(
                    f"{display_name} is already archived ({already_archived})",
                    f"{display_name} 已经归档（{already_archived}）",
                )],
                slug=slug,
                space_id=captured_space_id,
                terminal=pm_term,
            )
        if not rec:
            raise NotFound(f"no PM registered for {project}")
        paused = 0
        for task in self.ledger.project_tasks(slug):
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
        lines = [tr(f"{display_name} archived: {paused} tasks paused", f"{display_name} 已归档：{paused} 个任务暂停")]
        lines.append(end_pm(rec, label_name, ctx=self.ctx))  # last: the PM may be the session running this command
        space_closed, space_kept = (
            self._close_idle_project_space(matched_space, pm_term)
            if matched_space is not None
            else (False, False)
        )
        return ArchiveResult(
            project=display_name,
            paused=paused,
            lines=lines,
            slug=slug,
            space_id=captured_space_id,
            terminal=pm_term,
            space_closed=space_closed,
            space_kept=space_kept,
        )

    def _space_used_by_other_active(self, space_id: str, exclude_slug: str) -> bool:
        for other in self.ctx.store.registrations():
            if not isinstance(other, Mapping):
                continue
            oslug = registration_slug(other)
            if oslug == exclude_slug or other.get("archived"):
                continue
            if str(other.get("space_id") or "").strip() == space_id:
                return True
        return False

    def restore(
        self,
        project: str | Path,
        *,
        kind: str | None = None,
        model: str | None = None,
        no_app_space: bool = False,
    ) -> RestoreResult:
        """Bring an archived project back: its paused tasks return to where they were and a fresh PM starts from
        the handover, reusing its dedicated Space when still open or recreating it by original name."""
        tr = self.ctx.config.tr
        slug, rec, work_dir = self._resolve_project_record(project)
        folders_list = project_folders(rec)
        has_explicit = ("folders" in rec) or bool(rec.get("slug"))
        repo = str(rec.get("repo") or (folders_list[0]["path"] if folders_list else "") or "")
        display_name = project_display_name(rec, "" if not repo else repo) or slug
        archived = rec.get("archived")
        if not archived:
            return RestoreResult(
                project=display_name,
                restored=0,
                not_archived=True,
                lines=[tr(f"{display_name} is not archived", f"{display_name} 没有归档")],
                slug=slug,
            )
        # What would make the start fail, checked before anything changes.
        if folders_list:
            if not any(Path(f["path"]).is_dir() for f in folders_list):
                missing = folders_list[0]["path"]
                raise Refused(tr(f"{missing} is gone; {display_name} stays archived",
                                 f"{missing} 不存在了；{display_name} 仍是归档状态"))
        elif has_explicit:
            self.ctx.home.project(slug).ensure()
        else:
            if not repo or not Path(repo).is_dir():
                raise Refused(tr(f"{repo or slug} is gone; {display_name} stays archived",
                                 f"{repo or slug} 不存在了；{display_name} 仍是归档状态"))
        live = self.projects.find_pm(repo=slug if (has_explicit and not folders_list) else (repo or slug))
        if live:
            raise Refused(tr(
                f"the old PM of {display_name} still runs at {live['pane_id']}; end it first. {display_name} stays archived",
                f"{display_name} 的旧 PM 还在 {live['pane_id']} 运行，先把它关掉；{display_name} 仍是归档状态",
            ))
        if self.ctx.hc.server_status() is None:
            raise Refused(tr(f"herdr-core is not reachable; {display_name} stays archived",
                             f"herdr-core 连不上；{display_name} 仍是归档状态"))

        saved_space_id = str(rec.get("space_id") or "").strip()
        reuse_space_id = ""
        if not no_app_space and saved_space_id and not self._space_used_by_other_active(saved_space_id, slug):
            open_spaces = self.ctx.hc.app_spaces()
            if any(isinstance(s, Mapping) and not s.get("machine") and str(s.get("id") or "") == saved_space_id
                   for s in open_spaces):
                reuse_space_id = saved_space_id

        def _unarchive(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            if cur is None:
                return None
            cur.pop("archived", None)
            return cur

        self.ctx.store.change_registration(slug, _unarchive)
        restored: dict[str, str] = {}
        for task in self.ledger.project_tasks(slug):
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
            f"You are the PM of the {display_name} project (pm skill); the project was archived and has just been restored. "
            f"First run `{handover}` and take over from what it prints, nothing else. Then tell the user in three or "
            "four sentences what you took over and what is waiting for them.",
            f"你是 {display_name} 项目的 PM（pm skill），这个项目刚从归档中恢复。"
            f"先运行 `{handover}`，只按它给出的内容接手，"
            "然后用三四句话告诉用户：你接手了哪些在办的事、哪些事在等他。")
        start_folders: list[str] | None = [f["path"] for f in folders_list] if ("folders" in rec or not repo) else None
        start_repo: str | None = None if start_folders is not None else repo
        try:
            started = self.start(
                start_repo,
                folders=start_folders,
                kind=kind or rec.get("agent"),
                model=model,
                name="",
                space="current" if reuse_space_id else "new",
                space_id=reuse_space_id or None,
                prompt=prompt,
                no_app_space=no_app_space,
                slug=slug,
            )
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
            raise Refused(tr(f"{display_name} was not restored ({stop}); it stays archived",
                             f"{display_name} 没有恢复（{stop}）；仍是归档状态")) from stop
        lines = [*started.lines, tr(f"{display_name} restored: {len(restored)} tasks back",
                                    f"{display_name} 已恢复：{len(restored)} 个任务恢复原状态")]
        return RestoreResult(
            project=display_name,
            restored=len(restored),
            terminal=started.terminal,
            lines=lines,
            stderr_lines=started.stderr_lines,
            slug=started.slug or slug,
            name=started.name,
            display_name=started.display_name or display_name,
            cwd=started.cwd or work_dir,
            space_id=started.space_id or reuse_space_id or saved_space_id,
            space_name=started.space_name or str(rec.get("space_name") or display_name),
            space_reused=bool(reuse_space_id),
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
        if not rec and isinstance(repo_arg, str) and valid_slug(repo_arg):
            rec = self.ctx.store.registration(repo_arg)
        if not rec:
            raise NotFound("no PM registered for this project")
        slug = registration_slug(rec) or (project_slug(repo) if repo else str(repo_arg))
        if not repo:
            repo = str(rec.get("repo") or self.ctx.home.project(slug).ensure())
        d = self.ctx.home.project(slug).ensure()
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
        display_name = project_display_name(rec, repo)
        eff_reason = swap_reason_text(reason=reason, model=model, profile=profile, ctx=self.ctx)
        if rec.get("runtime") != "hc":
            # The herdr TUI: the new PM opens in a tab of its own, so it says what it took over, as before.
            prompt = "[from pm.py rotate] " + tr(
                f"You are the PM of the {display_name} project (pm skill), replacing the session that was just rotated "
                "out. If the startup notice says another PM exists, that is the one you replace; the registration is "
                f"about to move to you. First run `{handover}` and take over from what it prints, nothing else. Then tell "
                "the user in three or four sentences what you took over and what is waiting for them.",
                f"你是 {display_name} 项目的 PM（pm skill），接替刚轮换下去的上一任会话。"
                "启动提示里如果说另有一个 PM，那就是你要接替的那一个，登记马上会转到你名下。"
                f"先运行 `{handover}`，只按它给出的内容接手，"
                "然后用三四句话告诉用户：你接手了哪些在办的事、哪些事在等他。")
            args_bag = types.SimpleNamespace(repo=repo, notes=notes, reason=reason, model=model, profile=profile, transcript=transcript)
            if getattr(self.ctx, "_legacy", False) and rotate_mod.rotate_herdr is not rotate_mod._DEFAULT_ROTATE_HERDR:
                res = rotate_mod.rotate_herdr(args_bag, repo, rec, previous, prompt, is_self)
                return RotateResult(mode="tui", lines=list(res) if isinstance(res, list) else [])
            lines = rotate_mod._rotate_herdr_impl(args_bag, repo, rec, previous, prompt, is_self, ctx=self.ctx)
            return RotateResult(mode="tui", lines=lines)

        prompt = "[from pm.py rotate] " + takeover_prompt(display_name, handover, eff_reason, ctx=self.ctx)
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
                sp_id = str((old.get("labels") or {}).get("herdr.space") or "").strip()
                if sp_id and not fresh.get("space_id"):
                    fresh["space_id"] = sp_id
                fresh.update({"pane": f"hc:{term}", "terminal": term, "seat": True, "claimed": self.ctx.clock.now(),
                              "agent": kind, "endpoint": ep_dict, "epoch": next_epoch,
                              "previous": {**previous, "terminal": term},
                              "rotations": fresh.get("rotations", 0) + 1})
                return fresh

            self.ctx.store.change_registration(slug, _rotate_seat)
            rotated_ep = parse_legacy_endpoint(f"hc:{term}", runtime_hint="hc")
            new_reg_after = self.ctx.store.registration(slug) or {}
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
        started = self._start_pm_terminal_result(repo, s_argv, (old.get("labels") or {}).get("herdr.space"), display_name=display_name)
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
            sp_id = str(
                started.space_id
                or ((self.ctx.hc.get_raw(made) or {}).get("labels") or {}).get("herdr.space")
                or (old.get("labels") or {}).get("herdr.space")
                or ""
            ).strip()
            if sp_id and not fresh.get("space_id"):
                fresh["space_id"] = sp_id
            fresh.update({"pane": f"hc:{made}", "terminal": made, "seat": True, "claimed": self.ctx.clock.now(),
                          "agent": kind, "endpoint": ep_dict, "epoch": next_epoch,
                          "previous": {**previous, "terminal": retired},
                          "rotations": fresh.get("rotations", 0) + 1})
            return fresh

        self.ctx.store.change_registration(slug, _rotate_legacy_into_seat)
        rotated_ep = parse_legacy_endpoint(f"hc:{made}", runtime_hint="hc")
        new_reg_after = self.ctx.store.registration(slug) or {}
        TurnTracker(self.ctx, repo).pm_mailbox.requeue_unconsumed_on_epoch_change(
            int(new_reg_after.get("epoch") or 1), endpoint_uid=rotated_ep.uid if rotated_ep else ""
        )
        old_pm_panes = {rec.get("pane"), f"hc:{retired}", (rec.get("previous") or {}).get("pane")
                        if isinstance(rec.get("previous"), dict) else ""}
        move_pm_tasks_to_pane(repo, old_pm_panes, f"hc:{made}", ctx=self.ctx)
        record_swap_notice(repo, eff_reason, by=f"hc:{made}", ctx=self.ctx)
        deliver_mod.Delivery(self.ctx, repo).ensure_running()
        self.ctx.hc.name_tab(made, pm_tab_name(repo, display_name))
        self.ctx.hc.name_tab(retired, "", only_if=pm_tab_name(repo, display_name))
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
                proc = _spawn_seat_child(
                    spec["argv"], repo, successor_env(kind=cur_kind, argv=spec["argv"], ctx=self.ctx), win_job=win_job
                )
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
