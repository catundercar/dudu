"""The manager's command: the PM's start and rotation argv (narrow, lean, compaction per agent kind), the seat
around it, and starting it in a terminal. Layer 3."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence

from .. import osutil
from ..agents.base import ClaudeAgent, CodexAgent, PiAgent, is_seat_argv
from ..agents.reads import _rule_path, wide_folder
from ..context import Context
from ..errors import Refused
from ..home import project_slug
from ..procs import launcher
from ..project.project import ProjectRegistry
from ..store import project_folders, registration_slug, write_atomic
from ..terminals.tabs import pm_tab_name


# Target working-set compaction window for a PM session (200k by default; PM_COMPACT_TOKENS overrides,
# with PM_ROTATE_TOKENS kept as an env fallback for existing configurations).
COMPACT_TOKENS = int(os.environ.get("PM_COMPACT_TOKENS") or os.environ.get("PM_ROTATE_TOKENS") or "200000")
ROTATE_TOKENS = COMPACT_TOKENS  # legacy alias
CLAUDE_IDLE_COMPACT_MIN_TOKENS = 150_000
CODEX_COMPACT_TOKENS = 220_000
CODEX_POST_TURN_COMPACT_PERCENT = 80
PI_COMPACT_TOKENS = 220_000
PI_COMPACT_EXT = launcher().parent / "pm_pi_compact.js"
AGY_COMPACT_ENV = "AGY_CLI_AUTO_COMPACT_OVERRIDE"
AGY_KINDS = frozenset({"agy", "antigravity"})


def pm_compact_instructions() -> str:
    """Preservation checklist for PM context compaction (`PreCompact` and manual `/compact`)."""
    return "\n".join([
        "Compact Instructions for PM Coordinator:",
        "1. Preserve ALL unrecorded verbal user constraints, temporary red lines, freeze windows, forbidden "
        "commands/scripts, and external action boundaries verbatim with exact times and names.",
        "2. Preserve rejected technical alternatives along with the exact failure reasons and measured numbers "
        "(memory, latency, limits) so they are not re-proposed.",
        "3. Preserve cross-thread conditional promises and sequencing (e.g., after X merges, dispatch Y with Z; "
        "temporary dual-write or compatibility windows), and keep deferred tasks in the ledger "
        "(`pm.py new ... --status proposed --depends-on ...`) rather than only in notes.",
        "4. Preserve user interaction and formatting preferences along with their reasons, plus exact step-by-step "
        "plans, commands, or flags approved via short replies (\"同意\", \"按这三步来\").",
        "5. Omit verbose tool/log dumps and raw diffs; active task statuses and latest reports will be refreshed "
        "from the ledger on disk right after compaction.",
    ])


# Flags of the outgoing PM whose value is carried over to its successor.
KEEP_VALUE = ClaudeAgent.KEEP_VALUE


def successor_argv(kind: str, args: Sequence[str], model: str, prompt: str, *, ctx: Context | None = None) -> list[str]:
    """The command of the next PM. Claude Code keeps the outgoing session's flags, minus anything that would
    resume it; other kinds start from their registry entry. The prompt follows `--`: a kept flag such as
    `--allowed-tools` takes any number of values and would take the prompt as one more."""
    c = Context.from_env() if ctx is None else ctx
    return c.agents.get(kind).successor_argv(args, model, prompt)


# A Claude Code PM edits no files itself: workers do. Write stays, for briefs. One value, so a rotation that carries
# the outgoing session's flags over keeps it whole.
NARROW = list(ClaudeAgent.NARROW)


def narrow_pm(kind: str, argv: Sequence[str], *, ctx: Context | None = None) -> list[str]:
    """The PM's command with Edit and NotebookEdit denied (Claude Code only), unless config.json says
    {"pm": {"narrow_tools": false}}; then a denial carried over from the outgoing session is dropped too."""
    if kind != "claude":
        return list(argv)
    c = Context.from_env() if ctx is None else ctx
    narrow_tools = (c.config.read().get("pm") or {}).get("narrow_tools", True) is not False
    agent = c.agents.get("claude")
    assert isinstance(agent, ClaudeAgent)
    return agent.narrow_pm_argv(argv, narrow_tools=narrow_tools)


# A Claude Code PM starts lean. Every turn, and every wake-up by a background notice, reads the whole context again,
# so what a session loads before its first word is paid for again and again. A PM needs Bash, Read, Write, Agent,
# Skill and ToolSearch; not the MCP servers (browser tools, the claude.ai connectors), not the Chrome integration,
# not the plugins, and not the descriptions of the user's other skills. Measured on Claude Code 2.1.325, the first
# turn of an empty session held 51 k tokens, 35 k started lean. Flags without a value, so a
# rotation carries them over as they are.
LEAN = list(ClaudeAgent.LEAN)
# The bundled skills (code-review, loop, ...) stay: turning them off ("disableBundledSkills") made the first turn
# bigger, not smaller.


def claude_dir() -> Path:
    """Claude Code's own folder: CLAUDE_CONFIG_DIR, else ~/.claude."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def lean_settings() -> dict[str, Any]:
    """Settings for a lean Claude Code PM, layered over the user's for this session only: the plugins the user's
    settings enable are turned off, and every skill of the user's but pm, and every skill synced from the claude.ai
    account, is listed to the user (still typed as /name) and no longer to the model."""
    return ClaudeAgent.lean_settings(claude_dir())


def _same_path(a: str | Path, b: str | Path) -> bool:
    if a == b:
        return True
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _env_compact_tokens(env: Mapping[str, str], default: int) -> int:
    raw = env.get("PM_COMPACT_TOKENS") or env.get("PM_ROTATE_TOKENS")
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def pm_compact_tokens(kind: str = "", *, ctx: Context | None = None) -> int:
    """Auto-compaction token threshold configured for a PM of `kind` (0 when disabled).
    Matches the values applied to Claude (`pm-settings.json`), Codex (`model_auto_compact_token_limit`),
    pi (`pm_pi_compact.js`), and agy (`AGY_CLI_AUTO_COMPACT_OVERRIDE`)."""
    c = Context.from_env() if ctx is None else ctx
    cfg = c.config.read().get("pm") or {}
    if cfg.get("compact", True) is False:
        return 0
    k = (kind or "claude").strip().lower()
    cfg_limit = cfg.get("compact_tokens")
    has_cfg = isinstance(cfg_limit, int) and not isinstance(cfg_limit, bool) and cfg_limit >= 100_000
    if k == "pi":
        raw = c.env.get("PM_PI_COMPACT_TOKENS") or c.env.get("PM_COMPACT_TOKENS") or ""
        try:
            env_n = int(raw)
        except ValueError:
            env_n = 0
        return env_n if env_n >= 50_000 else PI_COMPACT_TOKENS
    if k == "codex":
        if has_cfg:
            return cfg_limit
        if c.env.get("PM_COMPACT_TOKENS") or c.env.get("PM_ROTATE_TOKENS"):
            env_val = _env_compact_tokens(c.env, COMPACT_TOKENS)
            return max(100_000, env_val) if env_val > 0 else 0
        return CODEX_COMPACT_TOKENS
    if k in ("claude", *AGY_KINDS):
        if has_cfg:
            return cfg_limit
        env_val = _env_compact_tokens(c.env, COMPACT_TOKENS)
        return max(100_000, env_val) if env_val > 0 else 0
    return cfg_limit if has_cfg else _env_compact_tokens(c.env, COMPACT_TOKENS)


def is_agy_kind(kind: str = "", argv: Sequence[str] = ()) -> bool:
    """Whether `kind` or `argv[0]` runs the `agy` (Antigravity) CLI."""
    if str(kind or "").strip().lower() in AGY_KINDS:
        return True
    if argv:
        return Path(str(argv[0])).name.lower() in AGY_KINDS
    return False


def pm_compact_env(kind: str = "", argv: Sequence[str] = (), *, ctx: Context | None = None) -> dict[str, str]:
    """Environment overrides enabling working-set auto-compaction for a PM session (`agy`: `AGY_CLI_AUTO_COMPACT_OVERRIDE`)."""
    if not is_agy_kind(kind, argv):
        return {}
    limit = pm_compact_tokens("agy", ctx=ctx)
    if limit <= 0:
        return {}
    return {AGY_COMPACT_ENV: str(limit)}


def claude_compact_settings(*, ctx: Context | None = None) -> dict[str, Any]:
    """Claude Code PM compaction settings: ~200k auto-compact window + idle pre-compaction at 150k."""
    c = Context.from_env() if ctx is None else ctx
    window = pm_compact_tokens("claude", ctx=c)
    if not window:
        return {}
    window = max(100_000, window)
    cfg = c.config.read().get("pm") or {}
    idle_min = cfg.get("idle_compact_min_tokens")
    if not isinstance(idle_min, int) or isinstance(idle_min, bool) or idle_min < 100_000:
        idle_min = min(CLAUDE_IDLE_COMPACT_MIN_TOKENS, window)
    return {
        "autoCompactWindow": window,
        "idleCompaction": True,
        "env": {"CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS": str(idle_min)},
    }


def _folder_read_permissions(rec: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build read-only `permissions` rules for all linked `folders[]` on explicit multi/zero-folder registrations."""
    if not isinstance(rec, Mapping) or "folders" not in rec or not isinstance(rec.get("folders"), list):
        return {}
    r_paths: list[str] = []
    for f in project_folders(rec):
        raw_p = f.get("path") or ""
        if not raw_p:
            continue
        p = Path(raw_p)
        if not p.is_dir() or wide_folder(p):
            continue
        for s in dict.fromkeys((str(p.absolute()), str(p.resolve()))):
            if s not in r_paths:
                r_paths.append(s)
    if not r_paths:
        return {}
    allow = [f"Read({_rule_path(p)}/**)" for p in r_paths]
    return {"permissions": {"allow": allow, "blockReadsExemptPaths": r_paths}}


def _build_pm_settings(
    c: Context,
    kind: str,
    slug: str,
    rec: Mapping[str, Any] | None,
    *,
    repo: str | Path | None = None,
) -> tuple[dict[str, Any], str]:
    mem_root = c.home.project(slug).memory if (slug and (repo or isinstance(rec, Mapping))) else None
    mine = c.agents.native_memory_settings(kind, mem_root, "pm") if mem_root is not None else {}
    perms = _folder_read_permissions(rec)
    compact = claude_compact_settings(ctx=c)
    lean = (c.config.read().get("pm") or {}).get("lean", True) is not False
    shared = str(c.home.pm_settings)
    path = str(c.home.project(slug).ensure() / "pm-settings.json") if (slug and (mine or perms)) else shared
    if not (lean or compact or mine or perms):
        return {}, path
    settings = {**(c.agents.claude_lean_settings() if lean else {}), **compact, **mine, **perms}
    return settings, path


def sync_pm_folder_settings(ctx: Context, slug: str, rec: Mapping[str, Any]) -> Path | None:
    """Rewrite `projects/<slug>/pm-settings.json` when linked folders change dynamically."""
    kind = str(rec.get("agent") or "claude")
    own_path = ctx.home.project(slug).pm_settings
    if kind != "claude" and not own_path.is_file():
        return None
    settings, path = _build_pm_settings(ctx, kind, slug, rec, repo=rec.get("repo") or None)
    if not settings:
        return None
    out_path = Path(path)
    write_atomic(out_path, (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return out_path


def lean_pm(kind: str, argv: Sequence[str], repo: str | Path | None = None, *, ctx: Context | None = None) -> list[str]:
    """The PM's command started lean and compaction-configured (Claude Code only): no MCP servers, no Chrome,
    and the settings of `lean_settings` + `claude_compact_settings` (written to pm-settings.json in the ledger
    home, again at each start and swap). config.json {"pm": {"lean": false}} drops MCP/plugin hiding while
    keeping compaction settings ({"pm": {"compact": false}} disables those). A --settings of the user's own
    is kept: Claude Code reads one --settings."""
    if kind != "claude":
        return list(argv)
    c = Context.from_env() if ctx is None else ctx
    rec = ProjectRegistry(c).pm_record(repo) if repo else None
    slug = registration_slug(rec) if isinstance(rec, dict) else (project_slug(repo) if repo else "")
    settings, path = _build_pm_settings(c, kind, slug, rec, repo=repo)
    shared = str(c.home.pm_settings)
    argv_list = list(argv)
    cut = argv_list.index("--") if "--" in argv_list else len(argv_list)
    head: list[str] = []
    i = 0
    while i < cut:
        if argv_list[i] in LEAN:
            i += 1
            continue
        if argv_list[i] == "--settings" and i + 1 < cut and any(_same_path(argv_list[i + 1], own) for own in (path, shared)):
            i += 2
            continue
        head.append(argv_list[i])
        i += 1
    lean = (c.config.read().get("pm") or {}).get("lean", True) is not False
    if lean:
        head += LEAN
    if settings and "--settings" not in head:
        c.home.root.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
        head += ["--settings", path]
    return head + argv_list[cut:]


def codex_compact_prompt() -> str:
    """Compaction prompt passed via Codex `-c compact_prompt=...`: combines checkpoint goals with PM checklist."""
    return (
        "You are performing a CONTEXT CHECKPOINT COMPACTION for a PM coordinator. Create a handoff summary "
        "covering current progress, key decisions, constraints, next steps, and references.\n"
        + pm_compact_instructions()
    )


def codex_pm_compact(kind: str, argv: Sequence[str], *, ctx: Context | None = None) -> list[str]:
    """Add working-set auto-compaction settings to a Codex PM command (idempotent across swaps)."""
    if kind != "codex" or not argv:
        return list(argv)
    c = Context.from_env() if ctx is None else ctx
    limit = pm_compact_tokens("codex", ctx=c)
    return CodexAgent.compact_pm_argv(
        argv,
        limit=limit,
        post_turn_percent=CODEX_POST_TURN_COMPACT_PERCENT,
        compact_prompt=codex_compact_prompt(),
    )


def pi_pm_compact(kind: str, argv: Sequence[str], *, ctx: Context | None = None) -> list[str]:
    """Attach the bundled pi working-set compaction extension to a pi PM command (idempotent across swaps)."""
    if kind != "pi" or not argv:
        return list(argv)
    c = Context.from_env() if ctx is None else ctx
    cfg = c.config.read().get("pm") or {}
    return PiAgent.compact_pm_argv(
        argv,
        ext_path=PI_COMPACT_EXT,
        compact_enabled=cfg.get("compact", True) is not False,
    )


def pm_argv(kind: str, argv: Sequence[str], repo: str | Path | None = None, *, ctx: Context | None = None) -> list[str]:
    """The command a PM session is started with: narrowed, lean and compact-configured for Claude,
    working-set compaction flags for Codex, and compaction extension for pi."""
    c = Context.from_env() if ctx is None else ctx
    out = lean_pm(kind, narrow_pm(kind, argv, ctx=c), repo, ctx=c)
    out = codex_pm_compact(kind, out, ctx=c)
    return pi_pm_compact(kind, out, ctx=c)


# A Claude Code PM runs on Opus unless the user says otherwise (--model, or config.json pm.model): a rotation does
# not carry over the model of the outgoing session, Fable included.
PM_MODEL = "opus"


def pm_model(kind: str, model: str | None = None, *, ctx: Context | None = None) -> str:
    """The model of a rotated-in PM: --model, else config.json pm.model when pm.kind (default claude) is this kind,
    else Opus for Claude Code; other kinds get none (their program's own), as before."""
    if model or kind != "claude":
        return model or ""
    c = Context.from_env() if ctx is None else ctx
    cfg = c.config.read().get("pm") or {}
    return (cfg.get("model") if (cfg.get("kind") or "claude") == kind else None) or PM_MODEL


def app_spaces(*, ctx: Context | None = None) -> list[dict[str, Any]]:
    """The spaces of the open desktop window (`herdr-app ls`), or [] without one."""
    c = Context.from_env() if ctx is None else ctx
    return c.hc.app_spaces()


def seat_python() -> list[str]:
    """The Python argv prefix that runs `pm.py seat` inside a terminal."""
    if not osutil.WINDOWS:
        return ["python3"]
    if shutil.which("py"):
        return ["py", "-3"]
    return [PureWindowsPath(sys.executable).as_posix()]


def seat_script_path(*, ctx: Context | None = None) -> str:
    resolved = ctx.procs.launcher() if ctx is not None else launcher()
    return PureWindowsPath(resolved).as_posix() if osutil.WINDOWS else str(resolved)


def seat_argv(
    repo: str,
    argv: Sequence[str],
    kind: str = "",
    prompt: str = "",
    *,
    ctx: Context | None = None,
) -> list[str]:
    """Wrap a PM agent command in `pm.py seat`, keeping `argv` at the end after `--`."""
    c = Context.from_env() if ctx is None else ctx
    home_arg = (
        [PureWindowsPath(c.home.root).as_posix() if osutil.WINDOWS else str(c.home.root)]
        if c.env.get("PM_HOME") else []
    )
    prefix = [*seat_python(), seat_script_path(ctx=c), *(["--home", *home_arg] if home_arg else []),
              "seat", "--repo", repo]
    if kind:
        prefix += ["--kind", kind]
    if prompt:
        prefix += ["--prompt", prompt]
    return [*prefix, "--", *argv]


def default_start_prompt(repo: str, *, display_name: str | None = None, ctx: Context | None = None) -> str:
    c = Context.from_env() if ctx is None else ctx
    skill = c.procs.launcher().parent.parent
    handover = f"{c.procs.pm_script()} handover"
    label = str(display_name or "").strip() or Path(repo).name
    return "[from pm.py start] " + c.config.tr(
        f"You are the PM (project manager) of the {label} project. Read {skill}/SKILL.md and "
        f"{skill}/references/pm-playbook.md, then run `{handover}` and work from what it prints. Then tell the "
        "user in three or four sentences what is open and what is waiting for them.",
        f"你是 {label} 项目的 PM（项目协调者）。先读 {skill}/SKILL.md 和 "
        f"{skill}/references/pm-playbook.md，再运行 `{handover}`，按它给出的内容开始工作，"
        "然后用三四句话告诉用户：有哪些在办的事、哪些事在等他。")


def pm_start_argv(repo: str, kind: str, model: str, prompt: str, *, ctx: Context | None = None) -> list[str]:
    """The inner agent argv for a fresh PM session started by `start`, `claim`, or fallback."""
    c = Context.from_env() if ctx is None else ctx
    argv = c.agents.get(kind).pm_start_argv(model, prompt)
    return pm_argv(kind, argv, repo, ctx=c)


def build_pm_seat_parts(
    repo: str,
    kind: str | None,
    model: str | None = "",
    prompt: str | None = None,
    *,
    display_name: str | None = None,
    ctx: Context | None = None,
) -> tuple[list[str], list[str], str]:
    c = Context.from_env() if ctx is None else ctx
    cfg = c.config.read().get("pm") or {}
    eff_kind = kind or cfg.get("kind") or "claude"
    effective_model = (
        model
        or (cfg.get("model") if (cfg.get("kind") or "claude") == eff_kind else None)
        or (PM_MODEL if eff_kind == "claude" else "")
    )
    eff_prompt = prompt or default_start_prompt(repo, display_name=display_name, ctx=c)
    inner = pm_start_argv(repo, eff_kind, effective_model, eff_prompt, ctx=c)
    s_argv = seat_argv(repo, inner, kind=eff_kind, prompt="" if c.agents.takes_prompt(eff_kind) else eff_prompt, ctx=c)
    return s_argv, inner, eff_prompt


def build_pm_seat_command(
    repo: str,
    kind: str | None,
    model: str | None = "",
    prompt: str | None = None,
    *,
    display_name: str | None = None,
    ctx: Context | None = None,
) -> tuple[list[str], str]:
    s_argv, _, eff_prompt = build_pm_seat_parts(repo, kind, model, prompt=prompt, display_name=display_name, ctx=ctx)
    return s_argv, eff_prompt


@dataclass(frozen=True)
class StartTerminalResult:
    """Outcome of starting a PM terminal: its address, desktop tab status, and bound space id."""

    terminal: str | None
    has_tab: bool = True
    no_tab_reason: str = ""
    space_id: str = ""


def _app_reply_error(out: subprocess.CompletedProcess[str]) -> str:
    """Extract an error message from a `herdr-app do` reply, or '' when it succeeded."""
    raw = (out.stdout or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    if out.returncode != 0:
        return (out.stderr or raw or f"exit {out.returncode}").strip()
    return ""


def no_tab_warning(terminal: str, *, ctx: Context) -> str:
    """Actionable notice printed when a PM terminal started without a desktop window/tab."""
    keep_cmd = f"herdr-app do terminal.keep '{{\"terminal\":\"{terminal}\",\"place\":\"tab\"}}'"
    return ctx.config.tr(
        f"note: PM hc:{terminal} started without a desktop tab (herdr-app unavailable); "
        f"to put it in a tab later, run: {keep_cmd} (or click Open PM in the project view)",
        f"提示：PM hc:{terminal} 启动时没有桌面标签页（连不上 herdr-app）；"
        f"要放回标签页请运行：{keep_cmd}（或在项目视图点「打开 PM」）",
    )


def _norm_dir(path: str | Path | None) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    norm = os.path.normpath(raw)
    try:
        return str(Path(norm).resolve())
    except OSError:
        return norm


def _find_project_space(
    spaces: Sequence[Mapping[str, Any]],
    repo: str,
    *,
    space: str | None = None,
    new_space: str = "",
) -> str | None:
    """Find an open local space belonging to `repo` (or matching explicit `space` id), else None."""
    local = [s for s in spaces if isinstance(s, Mapping) and s.get("id") and not s.get("machine")]
    if not local:
        return None
    if space:
        hit = next((str(s["id"]) for s in local if str(s["id"]) == str(space)), None)
        if hit:
            return hit
    want_repo = _norm_dir(repo)
    if want_repo:
        for s in local:
            if _norm_dir(s.get("folder")) == want_repo:
                return str(s["id"])
    names = {n for n in (new_space.strip(), Path(repo).name) if n}
    if names:
        for s in local:
            s_folder = _norm_dir(s.get("folder"))
            if str(s.get("name") or "").strip() in names and (not s_folder or not want_repo or s_folder == want_repo):
                return str(s["id"])
    return None


def _keep_terminal_in_app(ctx: Context, terminal: str) -> tuple[bool, str]:
    """Attach a freshly started bare terminal via `terminal.keep`, retrying briefly if herdr-app has not
    yet synced the terminal creation event from herdr-core."""
    last_err = ""
    for attempt in range(10):
        try:
            kept = ctx.hc.app_do("terminal.keep", {"terminal": terminal, "place": "tab"}, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as err:
            return False, str(err)
        err_msg = _app_reply_error(kept)
        if kept.returncode == 0 and not err_msg:
            return True, ""
        last_err = err_msg or f"terminal.keep exited {kept.returncode}"
        if "no running terminal" in last_err.lower() and attempt < 9:
            ctx.clock.sleep(0.25)
            continue
        return False, last_err
    return False, last_err


def _space_id_for_terminal(ctx: Context, terminal: str, *, fallback: str = "") -> str:
    """Resolve `herdr.space` for `terminal` from `hc get`, then `herdr-app ls`, else `fallback`."""
    if terminal:
        info = ctx.hc.get_raw(terminal) or {}
        sp_id = str((info.get("labels") or {}).get("herdr.space") or "").strip()
        if sp_id:
            return sp_id
        for sp in ctx.hc.app_spaces():
            if not isinstance(sp, Mapping) or sp.get("machine") or not sp.get("id"):
                continue
            for tab in sp.get("tabs") or ():
                for term in tab.get("terminals") or ():
                    if term.get("terminal") == terminal:
                        return str(sp["id"])
    return str(fallback or "").strip()


def _start_pm_terminal_result(
    repo: str,
    argv: Sequence[str],
    space: str | None = None,
    new_space: str = "",
    *,
    display_name: str | None = None,
    no_app_space: bool = False,
    ctx: Context,
) -> StartTerminalResult:
    """Start a PM's program in the desktop app: in a new space called new_space, or a tab in the given space,
    else a bare terminal attached to this project's space when `herdr-app` is reachable.

    When `no_app_space` is True (used for remote two-phase creation), skip `herdr-app` calls and start only the
    guarded `hc run` seat terminal.

    A space.new that times out or answers without a terminal may still have made the space: that space's
    terminal is the PM, found by its name among the spaces that were not there before. None found: stop,
    so a second PM is not started in a bare terminal."""
    made: str | None = None
    seated = is_seat_argv(argv)
    if no_app_space:
        res = ctx.hc.run(argv, bg=True, keep=seated, no_parent=True, labels=("pm.seat=1",) if seated else (), cwd=repo)
        made = (res or {}).get("address")
        return StartTerminalResult(terminal=made, has_tab=False, no_tab_reason="no_app_space", space_id="")
    app_missing = False
    fallback_reason = ""
    resolved_space_id = ""
    tab_label = pm_tab_name(repo, (display_name or new_space or "").strip() or None)
    if new_space or space:
        command = ("space.new", {"name": new_space, "folder": repo, "argv": list(argv), "focus": False}) if new_space else (
            "tab.new", {"space": space, "folder": repo, "argv": list(argv), "focus": False})
        before = {s.get("id") for s in ctx.hc.app_spaces()} if new_space else set()
        unclear = False
        try:
            out = ctx.hc.app_do(command[0], command[1], timeout=30)
            if out.returncode == 0:
                try:
                    data = json.loads(out.stdout)
                except (ValueError, AttributeError):
                    data = None
                if isinstance(data, Mapping):
                    made = data.get("terminal")
                    resolved_space_id = str(data.get("space") or "").strip()
                else:
                    made = None
                unclear = not made
            else:
                fallback_reason = _app_reply_error(out) or f"{command[0]} exited {out.returncode}"
        except subprocess.TimeoutExpired:
            unclear = True
            fallback_reason = f"{command[0]} timed out"
        except OSError as err:
            made = None  # no app here: a bare terminal below
            app_missing = True
            fallback_reason = str(err)
        if unclear and new_space:
            for s in ctx.hc.app_spaces():
                if s.get("name") != new_space or s.get("id") in before:
                    continue
                found_t = next((t.get("terminal") for tab in s.get("tabs") or []
                                for t in tab.get("terminals") or [] if t.get("terminal")), None)
                if found_t:
                    made = found_t
                    resolved_space_id = str(s.get("id") or "").strip()
                    break
            if not made:
                raise Refused(ctx.config.tr(
                    f"space.new gave no terminal and no new space \"{new_space}\" is open; no PM was "
                    "started. Look at the window (herdr-app ls) before trying again.",
                    f"space.new 没有给出终端，也没找到新建的 space「{new_space}」；没有启动 PM。"
                    "先看一下窗口（herdr-app ls）再重试。",
                ))
    if made:
        if seated:
            ctx.hc.keep(made)
            ctx.hc.label(made, "pm.seat=1")
        if not resolved_space_id:
            resolved_space_id = _space_id_for_terminal(ctx, made, fallback=space or "")
        return StartTerminalResult(terminal=made, has_tab=True, space_id=resolved_space_id)
    res = ctx.hc.run(argv, bg=True, keep=seated, no_parent=True, labels=("pm.seat=1",) if seated else (), cwd=repo)
    made = (res or {}).get("address")
    if not made:
        return StartTerminalResult(terminal=None, has_tab=False, no_tab_reason=fallback_reason)
    has_tab = False
    no_tab_reason = fallback_reason
    if not app_missing:
        open_spaces = ctx.hc.app_spaces()
        target_space = _find_project_space(open_spaces, repo, space=space, new_space=new_space)
        if target_space:
            # Bare terminal.keep lands in the currently active space; select this project's space first.
            try:
                ctx.hc.app_do("space.select", {"id": target_space}, timeout=30)
            except (OSError, subprocess.TimeoutExpired) as err:
                no_tab_reason = str(err)
            else:
                kept_ok, keep_err = _keep_terminal_in_app(ctx, made)
                if kept_ok:
                    has_tab = True
                    no_tab_reason = ""
                    resolved_space_id = str(target_space)
                    ctx.hc.name_tab(made, tab_label, wait=5)
                else:
                    no_tab_reason = keep_err
        elif open_spaces:
            # Other projects' spaces are open, but none belongs to this project: adopt into a dedicated
            # new space via herdr.space/herdr.tab labels instead of dropping into an unrelated active space.
            sp_id = f"sp{os.urandom(16).hex()}"
            tb_id = f"tb{os.urandom(16).hex()}"
            ctx.hc.label(made, f"herdr.space={sp_id}", f"herdr.tab={tb_id}")
            if ctx.hc.name_tab(made, tab_label, wait=5):
                has_tab = True
                no_tab_reason = ""
                resolved_space_id = sp_id
                if new_space:
                    try:
                        ctx.hc.app_do("space.rename", {"id": sp_id, "name": new_space}, timeout=30)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
        else:
            kept_ok, keep_err = _keep_terminal_in_app(ctx, made)
            if kept_ok:
                has_tab = True
                no_tab_reason = ""
                ctx.hc.name_tab(made, tab_label, wait=5)
                resolved_space_id = _space_id_for_terminal(ctx, made)
            else:
                no_tab_reason = keep_err
    return StartTerminalResult(terminal=made, has_tab=has_tab, no_tab_reason=no_tab_reason, space_id=resolved_space_id)


def _start_pm_terminal_impl(
    repo: str,
    argv: Sequence[str],
    space: str | None = None,
    new_space: str = "",
    *,
    ctx: Context,
) -> str | None:
    """Start a PM's program in the desktop app, returning its terminal address."""
    return _start_pm_terminal_result(repo, argv, space, new_space, ctx=ctx).terminal


def start_pm_terminal(
    repo: str,
    argv: Sequence[str],
    space: str | None = None,
    new_space: str = "",
) -> str | None:
    """Legacy wrapper for `start_pm_terminal` using `Context.from_env()`."""
    return _start_pm_terminal_impl(repo, argv, space, new_space, ctx=Context.from_env())


_DEFAULT_START_PM_TERMINAL = start_pm_terminal
