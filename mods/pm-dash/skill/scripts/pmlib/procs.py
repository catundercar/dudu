"""Processes: where the launcher is, the mark that tells the running code from the code an install puts in its
place, and `Processes` + context builder for `Context.from_env`. Layer 1.

`launcher()` is the one place that knows the path of scripts/pm.py. Everything that runs pm.py again (background
starts, the seat's argv, the command lines in briefs) or finds a file beside it (pm_pi_compact.js, assets/dash.html,
the skill folder) goes through it.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

import pmlib.agents.reads
import pmlib.agents.registry
import pmlib.agents.sessions
import pmlib.config
import pmlib.gitrepo
import pmlib.home
import pmlib.store
from . import context, osutil
from .terminals import events as events_mod, hc as hc_mod, screen as screen_mod, tabs as tabs_mod, tui as tui_mod

def _keep_skill_symlink(path: Path) -> Path:
    """Resolve system symlinks (e.g. macOS /var -> /private/var), but preserve the logical path when the launcher,
    its `scripts/` folder, or the enclosing skill folder is itself a symlink (so replacing a symlinked install with
    a copied directory still changes `code_mark()` and restarts the new install)."""
    logical = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (logical, logical.parent, logical.parent.parent)):
        return logical
    return logical.resolve()


_LAUNCHER = _keep_skill_symlink(Path(os.path.abspath(__file__)).parent.parent / "pm.py")
_PACKAGE = _LAUNCHER.parent / "pmlib"


def launcher() -> Path:
    """The absolute path of scripts/pm.py."""
    return _LAUNCHER


def code_files() -> tuple[Path, ...]:
    """The code files on disk now: pm.py, the pm_*.py modules beside it and every pmlib/**/*.py. Listed fresh each
    time so a newer version that adds or removes a module is seen."""
    scripts = _LAUNCHER.parent
    return (_LAUNCHER, *sorted(scripts.glob("pm_*.py")),
            *sorted(p for p in _PACKAGE.rglob("*.py") if "__pycache__" not in p.relative_to(_PACKAGE).parts))


def code_mark() -> list[tuple[str, int, int, int]] | None:
    """Relative path, inode, size and mtime of each of code_files(): it changes when an install replaces, adds or
    removes any of them. None only when the launcher pm.py itself is missing (the folder was just removed by an
    install in progress)."""
    scripts = _LAUNCHER.parent
    marks = []
    for path in code_files():
        try:
            st = path.stat()
        except OSError:
            if path == _LAUNCHER:
                return None
            continue
        marks.append((path.relative_to(scripts).as_posix(), st.st_ino, st.st_size, st.st_mtime_ns))
    return marks


def pm_script() -> str:
    """How a command line runs this script: the Python that runs it and its path."""
    return f"{osutil.python_command()} {osutil.shell_quote(launcher())}"


def pm_command() -> str:
    """How a worker runs this script: the installed copy, with the ledger home when it is not the default (on
    Windows as `--home`, which every shell there reads the same)."""
    if not os.environ.get("PM_HOME"):
        return pm_script()
    root = pmlib.home.Home.from_env().root
    if osutil.WINDOWS:
        return f"{pm_script()} --home {osutil.shell_quote(root)}"
    return f"PM_HOME={osutil.shell_quote(str(root))} {pm_script()}"


# What a Claude Code session sets for the commands it runs, about that session. `hc run` and `pm.py seat` hand the
# next PM session a clean environment without the outgoing session's own variables.
SESSION_ENV = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
               "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
               "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_PID", "CLAUDE_EFFORT")


_SHELL_PROGS = frozenset({"zsh", "bash", "sh", "dash", "fish", "pwsh", "powershell", "cmd"})
_BG_SIDECAR_RE = re.compile(
    r"(?:"
    r"(?:^|[\s/\\@._-])mcp(?:$|[\s/\\@._-])"
    r"|language_server"
    r"|\bgopls\b"
    r"|\brust-analyzer\b"
    r"|\bpyright\b"
    r"|\btsserver\b"
    r"|\beslint\b"
    r"|watchdog"
    r"|telemetry"
    r"|pm_pi_compact"
    r"|pm\.py\S*\s+wait\b"
    r"|\bhc\s+events\b"
    r")",
    re.I,
)
_SHELL_WRAPPER_RE = re.compile(
    r"^(?:\S*[/\\])?(?:zsh|bash|sh|dash|fish|pwsh|powershell)(?:\.exe)?\s+(?:-[a-zA-Z]*c|-Command)\s+",
    re.I,
)


def _cmd_prog(command: str) -> str:
    tok = (command or "").strip().split(None, 1)
    if not tok:
        return ""
    name = Path(tok[0].strip("\"'")).name.lower().lstrip("-")
    return name[:-4] if name.endswith(".exe") else name


def _is_shell_or_seat_cmd(command: str) -> bool:
    prog = _cmd_prog(command)
    if prog in _SHELL_PROGS:
        return True
    return bool(re.search(r"\bpm\.py\b.*\bseat\b", command or ""))


def _kind_from_cmd(command: str) -> str:
    prog = _cmd_prog(command)
    if prog in ("claude", "claude-code"):
        return "claude"
    if prog in ("agy", "antigravity"):
        return "agy"
    if prog in ("codex", "pi", "gemini", "opencode"):
        return prog
    return ""


def _kind_from_info(info: Mapping[str, Any] | Any) -> str:
    if isinstance(info, Mapping):
        status = info.get("status") if isinstance(info.get("status"), Mapping) else {}
        app = str(status.get("app") or "").lower()
        fg_argv = (info.get("foreground") or {}).get("argv") if isinstance(info.get("foreground"), Mapping) else ()
        argv = info.get("argv") or ()
    else:
        app = ""
        fg_argv = getattr(info, "foreground_argv", ()) or ()
        argv = getattr(info, "argv", ()) or ()
    if app in ("claude", "claude-code"):
        return "claude"
    if app in ("antigravity", "agy"):
        return "agy"
    if app in ("codex", "pi", "gemini", "opencode"):
        return app
    for seq in (fg_argv, argv):
        if seq:
            k = _kind_from_cmd(str(seq[0]))
            if k:
                return k
    return ""


def _process_table() -> tuple[dict[int, tuple[int, int, str]], dict[int, list[int]]]:
    rows: dict[int, tuple[int, int, str]] = {}
    children: dict[int, list[int]] = {}
    if osutil.WINDOWS:
        ps_cmd = (
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            ).stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            return rows, children
        try:
            parsed = json.loads(out) if out.strip() else []
        except ValueError:
            return rows, children
        items = [parsed] if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = item.get("ProcessId")
            ppid = item.get("ParentProcessId")
            cmd = str(item.get("CommandLine") or "")
            if isinstance(pid, int) and isinstance(ppid, int):
                rows[pid] = (ppid, -1, cmd)
                children.setdefault(ppid, []).append(pid)
        return rows, children
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,pgid=,command="],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return rows, children
    for line in out.splitlines():
        parts4 = line.split(None, 3)
        if len(parts4) == 4 and parts4[0].isdigit() and parts4[1].isdigit() and parts4[2].isdigit():
            pid, ppid, pgid, cmd = int(parts4[0]), int(parts4[1]), int(parts4[2]), parts4[3]
            rows[pid] = (ppid, pgid, cmd)
            children.setdefault(ppid, []).append(pid)
            continue
        parts3 = line.split(None, 2)
        if len(parts3) == 3 and parts3[0].isdigit() and parts3[1].isdigit():
            pid, ppid, cmd = int(parts3[0]), int(parts3[1]), parts3[2]
            rows[pid] = (ppid, -1, cmd)
            children.setdefault(ppid, []).append(pid)
    return rows, children


def _resolve_agent_root(
    root: int,
    fg_pid: int | None,
    rows: Mapping[int, tuple[int, int, str]],
    children: Mapping[int, list[int]],
    info: Mapping[str, Any] | Any,
) -> tuple[int, str]:
    cur = int(fg_pid) if fg_pid and int(fg_pid) in rows else int(root)
    visited: set[int] = set()
    while cur in rows and cur not in visited:
        visited.add(cur)
        _, _, cmd = rows[cur]
        if not _is_shell_or_seat_cmd(cmd):
            break
        kids = [c for c in children.get(cur, []) if c not in visited]
        if not kids:
            break
        non_shells = [c for c in kids if c in rows and not _is_shell_or_seat_cmd(rows[c][2])]
        if non_shells:
            cur = non_shells[0]
            break
        if len(kids) == 1:
            cur = kids[0]
        else:
            break
    kind = _kind_from_cmd(rows[cur][2]) if cur in rows else ""
    if not kind:
        kind = _kind_from_info(info)
    return cur, kind


def background_work(info: Mapping[str, Any] | Any) -> list[str]:
    """What a session in this terminal still runs in the background: Claude's Bash tool shells
    (`shell-snapshots/snapshot-`), or direct background child commands of `agy`/`codex`/`pi` (in their own
    process group on POSIX, excluding persistent MCP/LSP/watchdog sidecars and `pm.py wait`)."""
    if info is None:
        return []
    if isinstance(info, Mapping):
        root = info.get("pid")
        fg = info.get("foreground")
        fg_pid = fg.get("pid") if isinstance(fg, Mapping) else None
    else:
        root = getattr(info, "pid", None)
        fg_pid = getattr(info, "foreground_pid", None)
    if not root and not fg_pid:
        return []
    rows, children = _process_table()
    if not rows:
        return []
    start_pid = int(root or fg_pid)
    agent_pid, agent_kind = _resolve_agent_root(start_pid, int(fg_pid) if fg_pid else None, rows, children, info)
    # Claude (or unknown root absent from ps table): scan full subtree for Claude's shell-snapshots pattern.
    if agent_kind == "claude" or (not agent_kind and agent_pid not in rows):
        found, todo, seen = [], [agent_pid], set()
        while todo:
            cur = todo.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for pid in children.get(cur, []):
                todo.append(pid)
                command = rows[pid][2] if pid in rows else ""
                if "shell-snapshots/snapshot-" in command and not re.search(r"pm\.py\S*\s+wait\b", command):
                    said = re.search(r"eval '(.*)' < /dev/null", command)
                    found.append(osutil.clip(said.group(1) if said else command, 200))
        return found
    # Non-Claude (`agy`, `codex`, `pi`, etc.): inspect direct children of `agent_pid`.
    agent_pgid = rows[agent_pid][1] if agent_pid in rows else -1
    found = []
    for child_pid in children.get(agent_pid, []):
        if child_pid not in rows:
            continue
        _, child_pgid, command = rows[child_pid]
        if not command.strip():
            continue
        if not osutil.WINDOWS and agent_pgid > 0 and child_pgid > 0 and child_pgid == agent_pgid:
            continue
        if _BG_SIDECAR_RE.search(command):
            continue
        summary = _SHELL_WRAPPER_RE.sub("", command).strip()
        if summary.startswith(("'", '"')) and summary.endswith(summary[0]) and len(summary) >= 2:
            summary = summary[1:-1].strip()
        found.append(osutil.clip(summary or command, 200))
    return found


class Processes:
    """Port for launching detached `pm.py` subprocesses, computing code marks, and building clean environments."""

    def __init__(
        self,
        home: pmlib.home.Home,
        *,
        env: Mapping[str, str] | None = None,
        launcher_path: Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.home = home
        self._env = env
        self._launcher = _keep_skill_symlink(Path(launcher_path)) if launcher_path is not None else _LAUNCHER
        self._python = python_executable or sys.executable

    @property
    def env(self) -> Mapping[str, str]:
        return os.environ if self._env is None else self._env

    def launcher(self) -> Path:
        return self._launcher

    def code_files(self) -> tuple[Path, ...]:
        scripts = self._launcher.parent
        package = scripts / "pmlib"
        pkg_files = (
            sorted(p for p in package.rglob("*.py") if "__pycache__" not in p.relative_to(package).parts)
            if package.is_dir() else []
        )
        return (self._launcher, *sorted(scripts.glob("pm_*.py")), *pkg_files)

    def code_mark(self) -> list[tuple[str, int, int, int]] | None:
        scripts = self._launcher.parent
        marks = []
        for path in self.code_files():
            try:
                st = path.stat()
            except OSError:
                if path == self._launcher:
                    return None
                continue
            marks.append((path.relative_to(scripts).as_posix(), st.st_ino, st.st_size, st.st_mtime_ns))
        return marks

    def pm_script(self) -> str:
        return f"{osutil.python_command()} {osutil.shell_quote(self._launcher)}"

    def pm_command(self) -> str:
        if not self.env.get("PM_HOME"):
            return self.pm_script()
        if osutil.WINDOWS:
            return f"{self.pm_script()} --home {osutil.shell_quote(self.home.root)}"
        return f"PM_HOME={osutil.shell_quote(str(self.home.root))} {self.pm_script()}"

    def clean_session_env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        cleaned = {k: v for k, v in self.env.items() if k not in SESSION_ENV}
        if extra:
            cleaned.update(extra)
        return cleaned

    def background_work(self, info: Mapping[str, Any] | Any) -> list[str]:
        return background_work(info)

    def spawn_pm(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> subprocess.Popen[Any] | None:
        """Start `pm.py <args>` detached in a background process group; returns None if spawning fails."""
        try:
            return subprocess.Popen(
                [self._python, str(self._launcher), *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=dict(self.env) if env is None else dict(env),
                cwd=str(cwd) if cwd is not None else None,
                **osutil.own_group(background=True),
            )
        except OSError:
            return None

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        input: str | None = None,
        capture_output: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        return subprocess.run(
            list(argv),
            env=dict(self.env) if env is None else dict(env),
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
            input=input,
            capture_output=capture_output,
            text=text,
        )


def _load_hook_module(name: str) -> Any:
    """Return an already-imported upper-layer module, or load it lazily when `Context.from_env()` is called
    without importing `pmlib.cli` first (keeping Layer 1 free of static upward imports)."""
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001
        return None


def _default_claude_dir(env_map: Mapping[str, str]) -> Path:
    return Path(env_map.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _default_codex_dir(env_map: Mapping[str, str]) -> Path:
    return Path(env_map.get("CODEX_HOME") or Path.home() / ".codex")


def _default_agy_dir(env_map: Mapping[str, str]) -> Path:
    return Path(env_map.get("AGY_DATA_DIR") or Path.home() / ".gemini" / "antigravity-cli")


def build_context(
    home_option: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    after_save: tuple[Any, ...] | None = None,
    seat_alive: Any = None,
    caller_projects: Any = None,
    candidate_pruner: Any = None,
    deliver_watchers: tuple[Any, ...] | None = None,
    deliver_holds: tuple[Any, ...] | None = None,
) -> context.Context:
    """Construct a fresh `Context` from `--home` / environment variables."""
    env_map = dict(os.environ if env is None else env)
    home_obj = pmlib.home.Home.from_env(home_option, env=env_map)
    store_obj = pmlib.store.FileStore(home_obj)
    cfg = pmlib.config.Config(home_obj)
    clk = context.SystemClock()
    procs_port = Processes(home_obj, env=env_map)
    hc_port = hc_mod.HcHost(cfg, clock=clk)
    tui_port = tui_mod.TuiHost()
    git_port = pmlib.gitrepo.GitRepo()
    hc_term = env_map.get("HC_TERMINAL_ID", "")
    pane = env_map.get("HERDR_PANE_ID", "") or (f"hc:{hc_term}" if hc_term else "")
    workspace = env_map.get("HERDR_WORKSPACE_ID", "")
    c_dir = _default_claude_dir(env_map)
    c_projects = c_dir / "projects"
    c_sessions = _default_codex_dir(env_map) / "sessions"
    a_dir = _default_agy_dir(env_map)
    h_docs = Path.home() / ".config" / "herdr-app"
    ctx = context.Context(
        home=home_obj,
        store=store_obj,
        config=cfg,
        clock=clk,
        out=context.StdOutput(),
        procs=procs_port,
        hc=hc_port,
        tui=tui_port,
        git=git_port,
        env=env_map,
        pane=pane,
        hc_terminal=hc_term,
        workspace=workspace,
        claude_dir=c_dir,
        claude_projects=c_projects,
        codex_sessions=c_sessions,
        agy_dir=a_dir,
        herdr_docs=h_docs,
        after_save=tuple(after_save) if after_save is not None else (),
        seat_alive=seat_alive,
        caller_projects=caller_projects,
        candidate_pruner=candidate_pruner,
        deliver_watchers=tuple(deliver_watchers) if deliver_watchers is not None else (),
        deliver_holds=tuple(deliver_holds) if deliver_holds is not None else (),
    )
    ctx.agents = pmlib.agents.registry.AgentRegistry.from_context(ctx)
    caller_mod = _load_hook_module("pmlib.caller")
    if caller_mod is not None:
        ctx.caller = caller_mod.Caller(ctx)
        if ctx.caller_projects is None:
            ctx.caller_projects = ctx.caller.caller_projects
    if after_save is None:
        after_hooks: list[Any] = []
        board_mod = _load_hook_module("pmlib.ledger.board")
        if board_mod is not None:
            after_hooks.append(lambda: board_mod.Board(ctx).write())
        discord_mod = _load_hook_module("pmlib.discord")
        if discord_mod is not None:
            after_hooks.append(lambda: discord_mod.DiscordMirror(ctx).post_board())
        ctx.after_save = tuple(after_hooks)
    seat_mod = _load_hook_module("pmlib.manager.seat")
    if seat_alive is None and seat_mod is not None:
        ctx.seat_alive = lambda repo, rec, term=None: seat_mod.seat_alive(repo, rec, term, ctx=ctx)
    if candidate_pruner is None:
        cand_mod = _load_hook_module("pmlib.memory.candidates")
        if cand_mod is not None:
            ctx.candidate_pruner = lambda repo: cand_mod.MemoryCandidates(ctx, repo).prune()
    if deliver_watchers is None:
        helpers_watch_mod = _load_hook_module("pmlib.helpers.watch")
        deps_watch_mod = _load_hook_module("pmlib.events.deps_watch")
        agy_watch_mod = _load_hook_module("pmlib.events.agy_watch")
        watchers: list[Any] = []
        if helpers_watch_mod is not None:
            watchers.append(context.DeliverWatcher(
                name="helpers",
                terminals=lambda repo: helpers_watch_mod.HelperWatcher(ctx).active_terminals(repo),
                look=lambda repo, stops, bases: helpers_watch_mod.HelperWatcher(ctx).look(repo, stops, bases),
            ))
        if deps_watch_mod is not None:
            watchers.append(context.DeliverWatcher(
                name="dependencies",
                look=lambda repo, stops, bases: deps_watch_mod.DependencyWatcher(ctx).look(repo, stops, bases),
            ))
        if agy_watch_mod is not None:
            watchers.append(context.DeliverWatcher(
                name="agy-transcript",
                look=lambda repo, stops, bases: agy_watch_mod.AgyTranscriptWatcher(ctx).look(repo, stops, bases),
            ))
        ctx.deliver_watchers = tuple(watchers)
    if deliver_holds is None and seat_mod is not None:
        ctx.deliver_holds = (lambda repo: seat_mod.next_session_ready(repo, ctx=ctx),)
    return ctx
