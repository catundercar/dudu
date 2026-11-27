"""The codex profile pool a dispatch starts a codex worker on: the projects a pool covers (project_names, from the
managers' registrations), the profiles in it and how many workers each runs now, the per-project lock a dispatch
holds while it picks one, falling back when every profile is full, turning on fast, and deep.confirmed (also kept by
project name). The settings and command-line helpers it uses are agents/codex_pool.py. Layer 3.

Instance-scoped locks live on `Workers` / `CodexPool`; `_POOL_LOCK` remains only for legacy Stage 1-5 shims."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import re
from typing import Any

from ..agents.codex_pool import CODEX_STATUS, codex_profile_of, shows_fast
from ..agents.profiles import PROFILES, WorkerSpec
from ..context import Context
from ..errors import Refused
from ..home import project_slug
from ..project.project import ProjectRegistry
from ..project.readmodel import owner_of
from ..store import lock_file, unlock_file


POOL_LOCK_WAIT = 120  # seconds a dispatch waits for another one that is picking a codex profile of the same project
_POOL_LOCK: Any = None  # legacy shim only (Stages 1-5); deleted in Stage 6


def _codex_cfg_for(ctx: Context) -> dict[str, Any]:
    cfg = ctx.config.read().get("codex")
    return cfg if isinstance(cfg, dict) else {}


def _claude_defaults_for(ctx: Context, spec: Any) -> None:
    if spec.kind == "claude" and not spec.effort:
        spec.effort = (ctx.config.read().get("claude") or {}).get("effort") or ""


def _pool_fallback_for(ctx: Context, role: str) -> dict[str, Any]:
    entry = (_codex_cfg_for(ctx).get("fallback") or {}).get(role)
    if isinstance(entry, dict) and (entry.get("kind") or entry.get("model")):
        return {"kind": "claude", **entry}
    if role == "reviewer":
        table = ctx.agents.review_models().get("standard")
        return {"kind": "claude", **(table if isinstance(table, dict) else {"model": table})}
    return dict(PROFILES["standard"])


def _codex_status_line_for(ctx: Context, term: str) -> str:
    lines = [s.strip() for s in ctx.hc.read(term).splitlines() if CODEX_STATUS.search(s)]
    return lines[-1] if lines else ""


def project_names_for(ctx: Context, repo: str | Path | None) -> set[str]:
    """The names a project goes by in config.json's lists (codex.projects, deep.confirmed): its folder's name, and
    the folder name of the PM project it sits in when it is a repository inside one (owner_of)."""
    if not repo:
        return set()
    names = {Path(repo).name}
    rec = owner_of({"repo": str(repo), "project": Path(repo).name}, ProjectRegistry(ctx).pm_records())
    if rec and rec.get("repo"):
        names.add(Path(rec["repo"]).name)
    return names


def codex_pool_for(ctx: Context, repo: str | Path | None = None) -> list[dict[str, Any]]:
    """The codex profiles workers run on, in the order they are tried: [{"name", "max", "fast", "match"}]."""
    cfg = _codex_cfg_for(ctx)
    scope = cfg.get("projects")
    if repo and isinstance(scope, list) and not project_names_for(ctx, repo) & {str(x) for x in scope}:
        return []
    out: list[dict[str, Any]] = []
    for p in cfg.get("profiles") or []:
        p = {"name": p} if isinstance(p, str) else p
        if isinstance(p, dict) and p.get("name"):
            out.append({
                "name": str(p["name"]),
                "max": max(int(p.get("max") or 1), 0),
                "fast": bool(p.get("fast")),
                "match": [str(x) for x in p.get("providers") or [p["name"]]],
            })
    return out


def allow_default_codex_for(ctx: Context, repo: str | Path | None = None) -> bool:
    """Codex may run on its default provider (no -p): once profiles are listed, only when config.json says so."""
    return _codex_cfg_for(ctx).get("allow_default", not codex_pool_for(ctx, repo)) is True


def project_places_for(ctx: Context, repo: str | Path) -> set[Path]:
    """The folders that are this project's: its checkout, git's worktrees of it, the app's worktree folder, and the
    folder of the PM project it sits in."""
    places = {Path(repo).resolve(), ctx.git.worktree_home(repo).resolve()}
    rec = owner_of({"repo": str(repo), "project": Path(repo).name}, ProjectRegistry(ctx).pm_records())
    if rec and rec.get("repo") and Path(rec["repo"]).is_dir():
        places.add(Path(rec["repo"]).resolve())
    for block in (ctx.git.run(repo, "worktree", "list", "--porcelain") or "").split("\n\n"):
        found = re.search(r"^worktree (.+)$", block, re.M)
        if found:
            places.add(Path(found.group(1)).resolve())
    return places


def live_codex_for(ctx: Context, repo: str | Path) -> list[dict[str, Any]] | None:
    """The codex sessions running in this project's folders, whatever terminal or PM started them."""
    if getattr(ctx, "_legacy", False) and live_codex is not _DEFAULT_LIVE_CODEX:
        return live_codex(repo)
    return _live_codex_impl(ctx, repo)


def _live_codex_impl(ctx: Context, repo: str | Path) -> list[dict[str, Any]] | None:
    try:
        procs = [p for p in Path("/proc").iterdir() if p.name.isdigit()]
    except OSError:
        return None
    places, out = project_places_for(ctx, repo), []
    for proc in procs:
        try:
            if (proc / "comm").read_text().strip() != "codex":
                continue
            ppid = (proc / "stat").read_text().rsplit(")", 1)[1].split()[1]
            if Path(f"/proc/{ppid}/comm").read_text().strip() == "codex":
                continue
            cwd = Path(os.readlink(proc / "cwd")).resolve()
            argv = (proc / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except (OSError, IndexError):
            continue
        if any(cwd == p or p in cwd.parents for p in places):
            out.append({"pid": int(proc.name), "profile": codex_profile_of(argv), "cwd": str(cwd)})
    return out


def codex_usage_for(
    ctx: Context,
    repo: str | Path,
    pool: list[dict[str, Any]] | None = None,
) -> dict[str, int] | None:
    """{profile: sessions running in this project on it} for the pool's profiles; None when it cannot be counted."""
    pool = codex_pool_for(ctx, repo) if pool is None else pool
    seen = live_codex_for(ctx, repo)
    if seen is None:
        return None
    return {p["name"]: sum(1 for s in seen if s["profile"] in p["match"]) for p in pool}


def acquire_pool_lock(ctx: Context, repo: str | Path) -> Any:
    """Acquire the per-project codex pool lock file and return its open file handle. Raises `Refused` on timeout."""
    path = ctx.home.locks / f"codex-pool-{project_slug(repo)}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    deadline = ctx.clock.time() + POOL_LOCK_WAIT
    while True:
        try:
            lock_file(f)
            return f
        except OSError:
            if ctx.clock.time() > deadline:
                f.close()
                raise Refused(ctx.config.tr(
                    f"another dispatch of this project has held {path} for {POOL_LOCK_WAIT}s",
                    f"本项目另一个派发占着 {path} 已超过 {POOL_LOCK_WAIT} 秒",
                ))
            ctx.clock.sleep(1)


def release_pool_lock(ctx: Context, lock_fh: Any, spec: Any, repo: str | Path, *, tries: int = 10) -> None:
    """Wait until the newly started codex session is counted, then unlock and close `lock_fh`."""
    if not lock_fh:
        return
    if getattr(spec, "provider", ""):
        for _ in range(tries):
            usage = codex_usage_for(ctx, repo)
            if usage is None or usage.get(spec.provider, 0) > getattr(spec, "pool_before", 0):
                break
            ctx.clock.sleep(1)
    with contextlib.suppress(OSError):
        unlock_file(lock_fh)
    with contextlib.suppress(OSError):
        lock_fh.close()


def apply_codex_pool_for(
    ctx: Context,
    spec: Any,
    repo: str | Path,
    role: str = "worker",
    *,
    hold: bool = True,
    on_hold: Any = None,
    on_release: Any = None,
) -> tuple[Any, str, Any]:
    """Pick the codex profile a codex worker runs on (`spec.provider`), from config.json `codex.profiles`.

    Returns `(spec, warning_line, lock_fh)` where `warning_line` is a stderr notice (or "") and `lock_fh` is the
    acquired lock handle (or None). Raises `Refused` when default provider is disallowed or profile is unknown.
    """
    spec.provider, spec.pool_said, spec.pool_before = "", "", 0
    wanted = getattr(spec, "codex_profile", None) or ""
    cfg = _codex_cfg_for(ctx)
    pool = codex_pool_for(ctx, repo)
    if spec.kind != "codex" or not pool:
        spec.provider = wanted if spec.kind == "codex" and wanted not in ("", "default") else ""
        _claude_defaults_for(ctx, spec)
        return spec, "", None
    spec.model = spec.model or (cfg.get("review_model") if role == "reviewer" else "") or cfg.get("model") or ""
    spec.effort = spec.effort or cfg.get("effort") or ""
    lock_fh = None
    if hold:
        if on_hold is not None:
            on_hold(repo)
        elif getattr(ctx, "_legacy", False) and hold_pool_lock is not _DEFAULT_HOLD_POOL_LOCK:
            hold_pool_lock(repo)
        else:
            lock_fh = acquire_pool_lock(ctx, repo)
    try:
        usage = codex_usage_for(ctx, repo, pool)
        counted = usage is not None
        usage = usage or {p["name"]: 0 for p in pool}
        said = ", ".join(f"{p['name']} {usage[p['name']]}/{p['max']}" for p in pool) + (
            "" if counted else ctx.config.tr("; sessions are not counted here (no /proc)", "；这台机器数不了会话（没有 /proc）")
        )
        names = [p["name"] for p in pool]
        warning = ""
        if wanted == "default" or (not wanted and allow_default_codex_for(ctx, repo)
                                   and all(usage[p["name"]] >= p["max"] for p in pool)):
            if not allow_default_codex_for(ctx, repo):
                raise Refused(ctx.config.tr(
                    f"codex's default provider is not allowed (config.json codex.allow_default); profiles: {', '.join(names)}",
                    f"不允许用 codex 默认 provider（config.json codex.allow_default）；可用 profile：{', '.join(names)}",
                ))
            spec.pool_said = ctx.config.tr(f"codex default provider ({said})", f"codex 默认 provider（{said}）")
            return spec, warning, lock_fh
        if wanted:
            p = next((p for p in pool if p["name"] == wanted), None)
            if not p:
                raise Refused(ctx.config.tr(
                    f"no codex profile {wanted} in config.json codex.profiles: {', '.join(names)}",
                    f"config.json codex.profiles 里没有 {wanted}：{', '.join(names)}",
                ))
            if usage[wanted] >= p["max"]:
                warning = ctx.config.tr(
                    f"warning: codex -p {wanted} is full ({said}); started anyway, as --codex-profile says",
                    f"注意：codex -p {wanted} 已满（{said}），按 --codex-profile 照起",
                )
            spec.provider = wanted
        else:
            free = next((p for p in pool if usage[p["name"]] < p["max"]), None)
            if not free:
                fb = _pool_fallback_for(ctx, role)
                spec.kind = fb.get("kind") or "claude"
                spec.model = fb.get("model") or ""
                spec.effort = fb.get("effort") or ""
                spec.advisor = ""
                spec.fallback = ctx.agents.fable_fallback(spec.kind, spec.model, role)
                _claude_defaults_for(ctx, spec)
                spec.pool_said = ctx.config.tr(
                    f"codex profiles full ({said}), no default provider: {spec.kind} {spec.model} instead",
                    f"codex 并发已满（{said}），不用默认 provider，改派 {spec.kind} {spec.model}",
                )
                if lock_fh is not None:
                    release_pool_lock(ctx, lock_fh, spec, repo, tries=0)
                    lock_fh = None
                elif on_release is not None:
                    on_release(spec, repo)
                elif getattr(ctx, "_legacy", False):
                    pool_started(spec, repo)
                return spec, warning, lock_fh
            spec.provider = free["name"]
        spec.pool_before = usage[spec.provider]
        spec.pool_said = ctx.config.tr(f"codex -p {spec.provider} ({said} before)", f"codex -p {spec.provider}（派发前 {said}）")
        return spec, warning, lock_fh
    except BaseException:
        if lock_fh is not None:
            release_pool_lock(ctx, lock_fh, spec, repo, tries=0)
            lock_fh = None
        elif on_release is not None:
            on_release(spec, repo)
        elif getattr(ctx, "_legacy", False):
            pool_started(spec, repo)
        raise


def codex_fast_for(ctx: Context, term: str, spec: Any, *, tries: int = 20) -> str:
    """For a profile with "fast": true: once the session shows its status line, /fast is sent once."""
    if getattr(ctx, "_legacy", False) and codex_fast is not _DEFAULT_CODEX_FAST:
        return codex_fast(term, spec) if tries == 20 else codex_fast(term, spec, tries=tries)
    return _codex_fast_impl(ctx, term, spec, tries=tries)


def _codex_fast_impl(ctx: Context, term: str, spec: Any, *, tries: int = 20) -> str:
    p = next((p for p in codex_pool_for(ctx) if p["name"] == getattr(spec, "provider", "")), None)
    if spec.kind != "codex" or not p or not p["fast"]:
        return ""
    line = ""
    for _ in range(tries):
        line = _codex_status_line_for(ctx, term)
        if line:
            break
        ctx.clock.sleep(2)
    if shows_fast(line):
        return ctx.config.tr(f"fast already on: {line}", f"fast 已开：{line}")
    if not line:
        return ctx.config.tr("warning: no codex status line came up; /fast not sent", "注意：没等到 codex 状态栏，没发 /fast")
    ctx.hc.init_session_flag(term, "/fast")
    for _ in range(6):
        ctx.clock.sleep(2)
        line = _codex_status_line_for(ctx, term)
        if shows_fast(line):
            return ctx.config.tr(f"/fast sent; status line: {line}", f"已发 /fast；状态栏：{line}")
    return ctx.config.tr(
        f"warning: /fast sent, the status line does not show fast: {line}",
        f"注意：已发 /fast，但状态栏没显示 fast：{line}",
    )


def deep_confirmed_for(ctx: Context, repo: str | Path) -> bool:
    """The user agreed to Fable workers for good: config.json {"deep": {"confirmed": true}} or list of project names."""
    deep = ctx.config.read().get("deep")
    said = deep.get("confirmed") if isinstance(deep, dict) else None
    if isinstance(said, list):
        return bool(project_names_for(ctx, repo) & {str(x) for x in said})
    return said is True


# --- Legacy module-level shims (Stages 1-5 compatibility) ---


def project_names(repo: str | Path | None) -> set[str]:
    return project_names_for(Context.from_env(), repo)


def codex_pool(repo: str | Path | None = None) -> list[dict[str, Any]]:
    return codex_pool_for(Context.from_env(), repo)


def allow_default_codex(repo: str | Path | None = None) -> bool:
    return allow_default_codex_for(Context.from_env(), repo)


def project_places(repo: str | Path) -> set[Path]:
    return project_places_for(Context.from_env(), repo)


def live_codex(repo: str | Path) -> list[dict[str, Any]] | None:
    return _live_codex_impl(Context.from_env(), repo)


_DEFAULT_LIVE_CODEX = live_codex


def codex_usage(repo: str | Path, pool: list[dict[str, Any]] | None = None) -> dict[str, int] | None:
    return codex_usage_for(Context.from_env(), repo, pool)


def hold_pool_lock(repo: str | Path) -> None:
    global _POOL_LOCK
    if _POOL_LOCK:
        return
    _POOL_LOCK = acquire_pool_lock(Context.from_env(), repo)


_DEFAULT_HOLD_POOL_LOCK = hold_pool_lock


def pool_started(a: Any, repo: str | Path, tries: int = 10) -> None:
    global _POOL_LOCK
    if not _POOL_LOCK:
        return
    fh = _POOL_LOCK
    _POOL_LOCK = None
    release_pool_lock(Context.from_env(), fh, a, repo, tries=tries)


_DEFAULT_POOL_STARTED = pool_started


def codex_fast(term: str, a: Any, tries: int = 20) -> str:
    return _codex_fast_impl(Context.from_env(), term, a, tries=tries)


_DEFAULT_CODEX_FAST = codex_fast


def deep_confirmed(repo: str | Path) -> bool:
    return deep_confirmed_for(Context.from_env(), repo)
