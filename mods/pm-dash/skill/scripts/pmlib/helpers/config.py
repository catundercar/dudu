"""Helper settings: limits, timeouts and defaults from config.json, and where and how a helper terminal starts.
Layer 3.
"""
from __future__ import annotations

import os
from typing import Any

from ..agents.base import agent_kinds
from ..agents.profiles import PROFILES, WorkerSpec, fable_fallback, fable_on, profiles
from ..context import Context
from ..errors import Refused
from ..procs import SESSION_ENV
from ..terminals.tabs import hc_name


HELPER_MAX = 3           # default concurrent helpers per agent (PM or worker); config.json helpers.max
HELPER_PROJECT_MAX = 10  # default concurrent active threads + helpers per project; config.json helpers.project_max
HELPER_TIMEOUT = 1800    # default helper timeout in seconds (30 min); config.json helpers.timeout
HELPER_SCREEN_LINES = 60 # lines captured from terminal screen when a helper stops without writing its result file
HELPER_WAIT_MAX_PRINT = 4000

HELPER_DEFAULT_PROFILES = ("opus", "neon", "light")


def _positive_int(value: Any, default: int) -> int:
    try:
        n = int(value)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def helpers_cfg_for(ctx: Context) -> dict[str, Any]:
    cfg = ctx.config.read().get("helpers")
    return cfg if isinstance(cfg, dict) else {}


def helpers_max_for(ctx: Context) -> int:
    return _positive_int(helpers_cfg_for(ctx).get("max"), HELPER_MAX)


def helpers_project_max_for(ctx: Context) -> int:
    return _positive_int(helpers_cfg_for(ctx).get("project_max"), HELPER_PROJECT_MAX)


def helpers_timeout_for(ctx: Context) -> int:
    return _positive_int(helpers_cfg_for(ctx).get("timeout"), HELPER_TIMEOUT)


def resolve_helper_spec(ctx: Context, spec_or_args: Any) -> WorkerSpec:
    """Resolve a helper's profile, kind, model, effort and advisor into a `WorkerSpec`.

    Priority: CLI flags > explicit --profile > config helpers.profile (or helper.profile) > first configured among
    ("opus", "neon", "light"). Passing --kind without --profile respects that kind without forcing the default
    profile's model. Raises `Refused` on an unknown profile.
    """
    cfg = ctx.config.read()
    hcfg = cfg.get("helpers") if isinstance(cfg.get("helpers"), dict) else {}
    legacy = cfg.get("helper") if isinstance(cfg.get("helper"), dict) else {}
    table = profiles(cfg)
    spec = WorkerSpec.from_args(spec_or_args)
    given_profile = spec.profile or ""
    given_kind = spec.kind or ""
    if given_profile:
        name = given_profile
    elif given_kind:
        name = ""
    else:
        name = (hcfg.get("profile") or legacy.get("profile")
                or next((p for p in HELPER_DEFAULT_PROFILES if p in table), "light"))
    base: dict[str, Any] = {}
    if name:
        if name not in table:
            off = name in PROFILES and not fable_on(cfg)
            raise Refused(ctx.config.tr(
                f"no profile {name}; known: {', '.join(table)}"
                + (' (config.json has "fable": false: no Fable here)' if off else ""),
                f"没有档位 {name}；已有：{', '.join(table)}"
                + ("（config.json 里设了 \"fable\": false，这里用不了 Fable）" if off else ""),
            ))
        base = {"kind": "claude", **table[name]}
    elif legacy:
        base = {k: v for k, v in legacy.items() if k != "profile"}
    default_kind = base.get("kind") or "claude"
    spec.kind = given_kind or default_kind
    mine = base if spec.kind == default_kind else {}
    spec.model = spec.model or mine.get("model") or ""
    spec.effort = spec.effort or mine.get("effort") or ""
    given_adv = getattr(spec_or_args, "advisor", None)
    spec.advisor = "" if given_adv == "none" else (given_adv or mine.get("advisor") or "")
    kinds = agent_kinds(cfg)
    spec.advisor_dropped = spec.advisor if spec.advisor and not (kinds.get(spec.kind) or {}).get("advisor") else ""
    if spec.advisor_dropped:
        spec.advisor = ""
    spec.fallback = fable_fallback(spec.kind, spec.model, "worker", cfg=cfg)
    spec.profile = name
    return spec


def helper_placement_for(ctx: Context, parent: str | None = None) -> list[str]:
    """How `hc run` places a helper: as a normal sub-agent of its caller's terminal (ends when its caller ends;
    no --outlive-parent), with --no-notify so results flow through the conclusion file and ledger/deliver."""
    if parent:
        return ["--parent", parent, "--no-notify"]
    return ["--parent", ctx.pane[3:], "--no-notify"] if ctx.pane.startswith("hc:") else ["--no-parent"]


def helper_env_for(ctx: Context, owner_id: str, name: str, slug: str) -> dict[str, str]:
    """Environment handed to a helper's hc run: inherits HC_SESSION and PM_HOME, drops parent session IDs so hooks
    and tools never confuse the helper with its caller, and sets PM_HELPER_* as belt-and-suspenders identity."""
    env = {k: v for k, v in ctx.env.items()
           if k not in ("HERDR_PANE_ID", "HERDR_WORKSPACE_ID", *SESSION_ENV)}
    env["PM_HELPER_OF"] = owner_id
    env["PM_HELPER_NAME"] = name
    env["PM_HELPER_PROJECT"] = slug
    return env


def helper_hc_name_for(ctx: Context, owner_dir: str, name: str) -> str:
    """A live-unique hc terminal name (1-32 of a-z 0-9 - _) for a helper."""
    prefix = hc_name(f"h-{name}", 24)
    if prefix == "worker":
        prefix = hc_name(f"h-{owner_dir}-{name}", 24)
    rows = ctx.hc.live_rows() or {}
    taken = {str(r.name if hasattr(r, "name") else (r.get("name") or "")) for r in rows.values()}
    if prefix not in taken:
        return prefix
    for i in range(2, 100):
        cand = f"{prefix[:28].rstrip('-')}-{i}"
        if cand not in taken:
            return cand
    return f"{prefix[:27].rstrip('-')}-{os.urandom(2).hex()}"


# ── Legacy module-level shims (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────


def helpers_cfg() -> dict[str, Any]:
    return helpers_cfg_for(Context.from_env())


def helpers_max() -> int:
    return helpers_max_for(Context.from_env())


def helpers_project_max() -> int:
    return helpers_project_max_for(Context.from_env())


def helpers_timeout() -> int:
    return helpers_timeout_for(Context.from_env())


def helper_defaults(a: Any) -> Any:
    spec = resolve_helper_spec(Context.from_env(), a)
    return spec.apply_to(a)


def helper_placement() -> list[str]:
    return helper_placement_for(Context.from_env())


def helper_env(owner_id: str, name: str, slug: str) -> dict[str, str]:
    return helper_env_for(Context.from_env(), owner_id, name, slug)


def helper_hc_name(owner_dir: str, name: str) -> str:
    return helper_hc_name_for(Context.from_env(), owner_dir, name)
