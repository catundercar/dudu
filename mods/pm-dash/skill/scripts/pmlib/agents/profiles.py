"""Profiles and `WorkerSpec`: the words a dispatch picks a worker by (light, standard, hard, deep, and config.json's
own), who reviews each, what Fable falls back to, and the ladder escalate climbs. Layer 1."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .. import config as config_mod
from ..errors import Refused
from . import base as base_mod


def is_fable(model: str | None) -> bool:
    return "fable" in (model or "").lower()


# Profiles: a PM picks a word (`dispatch --profile hard`), not a model ID. config.json's `profiles` replaces or adds
# whole entries ({"profiles": {"hard": {"kind": "codex", "effort": "xhigh"}}}); a profile without a kind is Claude's.
PROFILES = {
    "light": {"kind": "claude", "model": "sonnet", "effort": "medium"},
    "standard": {"kind": "claude", "model": "opus"},
    "hard": {"kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"},
    "deep": {"kind": "claude", "model": "fable", "effort": "high"},
}


# The user decides before these start, as before any Fable worker (asks_first): dispatch only asks, until --confirmed.
ASK_FIRST = ("deep",)


# Who reviews a profile's work, a model other than the one that wrote it; config.json's `review` changes entries.
# A value is a Claude model, or {"kind": ..., "model": ..., "effort": ...}.
REVIEW_MODELS = {"light": "opus", "standard": "fable", "hard": "fable", "deep": "opus"}


# Without Fable (config.json {"fable": false}: Bedrock, Vertex, a gateway, an account without it): hard runs without
# its Fable advisor, deep is not offered, and a review the table gave to Fable goes to this model, not Opus, so the
# model that wrote the code does not review it. Profiles and review entries the user wrote still win.
NO_FABLE_REVIEWER = "sonnet"


# What a Claude process that runs on Fable falls back to when Fable cannot be used (`--fallback-model`).
FABLE_FALLBACK = {"worker": "opus", "reviewer": "sonnet"}


# One step at a time, light to deep. Deep asks the user first, as any Fable worker does (asks_first).
LADDER = ("light", "standard", "hard", "deep")


@dataclass
class WorkerSpec:
    """Typed worker configuration replacing mutated `argparse.Namespace` bags."""

    profile: str = ""
    kind: str = ""
    model: str = ""
    effort: str = ""
    advisor: str = ""
    advisor_dropped: str = ""
    fallback: str = ""
    codex_profile: str = ""
    provider: str = ""
    pool_said: str = ""
    preapproved: bool = False
    pool_before: int = 0
    name: str = ""
    branch: str = ""
    dry_run: bool = False
    fast: bool = False

    @classmethod
    def from_args(cls, a: Any) -> WorkerSpec:
        if isinstance(a, cls):
            return cls(
                profile=a.profile,
                kind=a.kind,
                model=a.model,
                effort=a.effort,
                advisor=a.advisor,
                advisor_dropped=a.advisor_dropped,
                fallback=a.fallback,
                codex_profile=a.codex_profile,
                provider=a.provider,
                pool_said=a.pool_said,
                preapproved=a.preapproved,
                pool_before=a.pool_before,
                name=a.name,
                branch=a.branch,
                dry_run=a.dry_run,
                fast=a.fast,
            )
        return cls(
            profile=getattr(a, "profile", None) or "",
            kind=getattr(a, "kind", None) or "",
            model=getattr(a, "model", None) or "",
            effort=getattr(a, "effort", None) or "",
            advisor=getattr(a, "advisor", None) or "",
            advisor_dropped=getattr(a, "advisor_dropped", None) or "",
            fallback=getattr(a, "fallback", None) or "",
            codex_profile=getattr(a, "codex_profile", None) or "",
            provider=getattr(a, "provider", None) or "",
            pool_said=getattr(a, "pool_said", None) or "",
            preapproved=bool(getattr(a, "preapproved", False)),
            pool_before=int(getattr(a, "pool_before", 0) or 0),
            name=getattr(a, "name", None) or "",
            branch=getattr(a, "branch", None) or "",
            dry_run=bool(getattr(a, "dry_run", False)),
            fast=bool(getattr(a, "fast", False)),
        )

    def apply_to(self, a: Any) -> Any:
        """Write resolved fields back onto a legacy Namespace or duck-typed object."""
        a.profile = self.profile
        a.kind = self.kind
        a.model = self.model
        a.effort = self.effort
        a.advisor = self.advisor
        a.advisor_dropped = self.advisor_dropped
        a.fallback = self.fallback
        return a

    def asks_first(self) -> bool:
        return self.profile in ASK_FIRST or is_fable(self.model)

    def to_record(self) -> dict[str, str]:
        record = {
            "profile": self.profile,
            "kind": self.kind,
            "model": self.model,
            "effort": self.effort,
            "advisor": self.advisor,
        }
        if self.provider:
            record["provider"] = self.provider
        return record

    def summary(self) -> str:
        kind = f"{self.kind} -p {self.provider}" if self.provider else self.kind
        said = " ".join(x for x in (kind, self.model, self.effort) if x) + (
            f", advisor {self.advisor}" if self.advisor else ""
        )
        return f"{self.profile}: {said}" if self.profile else said

    def engine_label(self) -> str:
        model = self.model or self.kind
        return "·".join(x for x in (model[:1].upper() + model[1:], self.effort) if x)

    def fallback_said(self, tr_fn: Callable[[str, str], str] | None = None) -> str:
        if not self.fallback:
            return ""
        translate = config_mod.tr if tr_fn is None else tr_fn
        return translate(
            f"; falls back to {self.fallback} if Fable cannot be used",
            f"；Fable 不可用时会退到 {self.fallback}",
        )


def asks_first(a: Any) -> bool:
    """The user decides before a Fable worker starts (the user's words: "deep 档先问我"): a profile in ASK_FIRST,
    or any Fable model, however it was named. A Fable advisor is hard's, which the PM picks on its own."""
    return getattr(a, "profile", "") in ASK_FIRST or is_fable(getattr(a, "model", ""))


def fable_on(cfg: Mapping[str, Any] | None = None) -> bool:
    """Fable can be used here: true unless config.json says {"fable": false}."""
    cfg_map = config_mod.config() if cfg is None else cfg
    return cfg_map.get("fable", True) is not False


def builtin_profiles(cfg: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    if fable_on(cfg):
        return PROFILES
    return {
        k: {f: x for f, x in v.items() if not (f == "advisor" and is_fable(x))}
        for k, v in PROFILES.items()
        if not is_fable(v.get("model"))
    }


def profiles(cfg: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    cfg_map = config_mod.config() if cfg is None else cfg
    mine = cfg_map.get("profiles") or {}
    return {**builtin_profiles(cfg_map), **{k: v for k, v in mine.items() if isinstance(v, dict)}}


def review_models(cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg_map = config_mod.config() if cfg is None else cfg
    table = REVIEW_MODELS if fable_on(cfg_map) else {
        k: NO_FABLE_REVIEWER if is_fable(v) else v for k, v in REVIEW_MODELS.items()
    }
    return {**table, **(cfg_map.get("review") or {})}


def fable_fallback(kind: str, model: str, role: str = "worker", *, cfg: Mapping[str, Any] | None = None) -> str:
    """The --fallback-model for a Claude process that runs on Fable, else "". Claude switches without a word (only
    its session log says so), so the dispatch and review notes name it. A Fable advisor is not covered: an advisor
    that cannot be used makes Claude exit at once whatever the fallback (see hold_exited). config.json
    claude.fable_fallback: one model for every role instead."""
    cfg_map = config_mod.config() if cfg is None else cfg
    mine = (cfg_map.get("claude") or {}).get("fable_fallback") or ""
    return (mine or FABLE_FALLBACK[role]) if kind == "claude" and is_fable(model) else ""


def fallback_said(a: Any, *, tr_fn: Callable[[str, str], str] | None = None) -> str:
    fallback = getattr(a, "fallback", "")
    if not fallback:
        return ""
    translate = config_mod.tr if tr_fn is None else tr_fn
    return translate(
        f"; falls back to {fallback} if Fable cannot be used",
        f"；Fable 不可用时会退到 {fallback}",
    )


def resolve_worker_spec(
    given: Any,
    role: str = "worker",
    *,
    cfg: Mapping[str, Any] | None = None,
    kinds: Mapping[str, Mapping[str, Any]] | None = None,
    tr_fn: Callable[[str, str], str] | None = None,
) -> WorkerSpec:
    """Resolve a `WorkerSpec` from CLI flags/spec, profile table, config.json, and agent capabilities.
    Raises `Refused` when an unknown profile is requested."""
    cfg_map = config_mod.config() if cfg is None else cfg
    kinds_map = base_mod.agent_kinds(cfg_map) if kinds is None else kinds
    translate = config_mod.tr if tr_fn is None else tr_fn

    spec = WorkerSpec.from_args(given)
    role_cfg = cfg_map.get(role) or cfg_map.get("worker") or {}
    explicit_profile = getattr(given, "profile", None) or ""
    name = explicit_profile or role_cfg.get("profile") or ""
    base: dict[str, Any] = dict(role_cfg) if isinstance(role_cfg, Mapping) else {}
    if name:
        table = profiles(cfg_map)
        if name not in table:
            off = name in PROFILES and not fable_on(cfg_map)
            raise Refused(translate(
                f"no profile {name}; known: {', '.join(table)}"
                + (' (config.json has "fable": false: no Fable here)' if off else ""),
                f"没有档位 {name}；已有：{', '.join(table)}"
                + ('（config.json 里设了 "fable": false，这里用不了 Fable）' if off else ""),
            ))
        base = {"kind": "claude", **table[name]}
        if not explicit_profile:
            extra = {k: v for k, v in role_cfg.items() if k != "profile"}
            if extra.get("kind") and extra["kind"] != base["kind"]:
                base = {}  # the profile's model, effort and advisor are its program's, not this one's
            base.update(extra)

    default = base.get("kind") or "codex"
    spec.kind = spec.kind or default
    # A configured model or effort belongs to the configured program, not to another one named on the command line.
    mine = base if spec.kind == default else {}
    spec.model = spec.model or mine.get("model") or ""
    spec.effort = spec.effort or mine.get("effort") or ""
    given_advisor = getattr(given, "advisor", None)
    spec.advisor = "" if given_advisor == "none" else given_advisor or mine.get("advisor") or ""
    # Only some programs take an advisor; for the others it is left out, and the dispatch note says so.
    spec.advisor_dropped = spec.advisor if spec.advisor and not (kinds_map.get(spec.kind) or {}).get("advisor") else ""
    if spec.advisor_dropped:
        spec.advisor = ""
    spec.fallback = fable_fallback(spec.kind, spec.model, "reviewer" if role == "reviewer" else "worker", cfg=cfg_map)
    spec.profile = name
    return spec


def worker_defaults(a: Any, role: str = "worker") -> Any:
    """Fill the worker's profile, kind, model, effort and advisor. The command line wins; then the profile it names;
    else config.json (the role's key, a reviewer falling back to "worker"; that key may name a profile, its other
    keys then change that profile); then the program's own defaults. Nothing configured: as before profiles."""
    spec = resolve_worker_spec(a, role=role)
    if isinstance(a, WorkerSpec):
        return spec
    return spec.apply_to(a)


def worker_record(a: Any) -> dict[str, str]:
    """The task's `worker` field: what the worker was actually started with."""
    if isinstance(a, WorkerSpec):
        return a.to_record()
    record = {"profile": a.profile, "kind": a.kind, "model": a.model, "effort": a.effort, "advisor": a.advisor}
    if getattr(a, "provider", ""):
        record["provider"] = a.provider  # the codex profile (`codex -p <name>`) it runs on
    return record


def worker_summary(a: Any) -> str:
    """"hard: claude opus xhigh, advisor fable", or "codex" without a profile, as the dispatch note says it."""
    if isinstance(a, WorkerSpec):
        return a.summary()
    kind = f"{a.kind} -p {a.provider}" if getattr(a, "provider", "") else a.kind
    said = " ".join(x for x in (kind, a.model, a.effort) if x) + (f", advisor {a.advisor}" if a.advisor else "")
    return f"{a.profile}: {said}" if a.profile else said


def ladder(cfg: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """The steps there are here: without Fable ({"fable": false}) it ends at hard, unless config.json's `profiles`
    brings deep back."""
    known = profiles(cfg)
    return tuple(p for p in LADDER if p in known)


def engine_label(b: Any) -> str:
    """"Opus·xhigh": the model (else the program) and effort a worker runs with, as the task log says it."""
    if isinstance(b, WorkerSpec):
        return b.engine_label()
    model = b.model or b.kind
    return "·".join(x for x in (model[:1].upper() + model[1:], b.effort) if x)
