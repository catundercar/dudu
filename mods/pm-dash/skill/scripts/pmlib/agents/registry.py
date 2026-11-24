"""`AgentRegistry`: Layer 1 port owning agent kinds, profile resolution, launch/resume/worker argv, outside-read
settings, and transcript paths without touching process-wide globals."""
from __future__ import annotations

import inspect
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

import pmlib.config
import pmlib.home
from . import base as base_mod, profiles as profiles_mod, reads as reads_mod, sessions as sessions_mod


def _accepts_kwarg(fn: Any, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


class AgentRegistry:
    """Context-scoped registry of agent kinds, profiles, read permissions, and transcript folders.

    When bound to a `Context` (via `from_context(ctx)`), paths and ports are read dynamically from `ctx` on each call
    so mutations to `ctx.herdr_docs`, `ctx.claude_dir`, `ctx.claude_projects`, or `ctx.codex_sessions` take effect
    immediately.
    """

    def __init__(
        self,
        config: pmlib.config.Config | None = None,
        *,
        home: pmlib.home.Home | None = None,
        claude_dir: Path | str | None = None,
        claude_projects: Path | str | None = None,
        codex_sessions: Path | str | None = None,
        herdr_docs: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        ctx: Any = None,
        legacy: bool = False,
    ) -> None:
        self._ctx = ctx
        self._legacy = legacy
        self._config = config
        self._home = home
        self._claude_dir = Path(claude_dir) if claude_dir is not None else None
        self._claude_projects = Path(claude_projects) if claude_projects is not None else None
        self._codex_sessions = Path(codex_sessions) if codex_sessions is not None else None
        self._herdr_docs = Path(herdr_docs) if herdr_docs is not None else None
        self._env = env

    @classmethod
    def from_context(cls, ctx: Any, *, legacy: bool = False) -> AgentRegistry:
        return cls(ctx=ctx, legacy=legacy)

    @property
    def claude_dir(self) -> Path:
        if self._ctx is not None and getattr(self._ctx, "claude_dir", None) is not None:
            return Path(self._ctx.claude_dir)
        if self._claude_dir is not None:
            return self._claude_dir
        return Path.home() / ".claude"

    @property
    def claude_projects(self) -> Path:
        if self._ctx is not None and getattr(self._ctx, "claude_projects", None) is not None:
            return Path(self._ctx.claude_projects)
        if self._claude_projects is not None:
            return self._claude_projects
        return sessions_mod.CLAUDE_PROJECTS

    @property
    def codex_sessions(self) -> Path:
        if self._ctx is not None and getattr(self._ctx, "codex_sessions", None) is not None:
            return Path(self._ctx.codex_sessions)
        if self._codex_sessions is not None:
            return self._codex_sessions
        return sessions_mod.CODEX_SESSIONS

    @property
    def herdr_docs(self) -> Path:
        if self._ctx is not None and getattr(self._ctx, "herdr_docs", None) is not None:
            return Path(self._ctx.herdr_docs)
        if self._herdr_docs is not None:
            return self._herdr_docs
        return reads_mod.HERDR_DOCS

    def _config_obj(self) -> pmlib.config.Config | None:
        if self._ctx is not None and getattr(self._ctx, "config", None) is not None:
            return self._ctx.config
        return self._config

    def _cfg_dict(self) -> dict[str, Any]:
        cfg = self._config_obj()
        return cfg.read() if cfg is not None else pmlib.config.config()

    def _tr(self, en: str, zh: str) -> str:
        cfg = self._config_obj()
        return cfg.tr(en, zh) if cfg is not None else pmlib.config.tr(en, zh)

    def _ledger_home(self) -> pmlib.home.Home:
        if self._ctx is not None and getattr(self._ctx, "home", None) is not None:
            return self._ctx.home
        return self._home if self._home is not None else pmlib.home.current()

    def _env_map(self) -> Mapping[str, str]:
        if self._ctx is not None and getattr(self._ctx, "env", None) is not None:
            return self._ctx.env
        return os.environ if self._env is None else self._env

    def kinds(self) -> dict[str, dict[str, Any]]:
        return base_mod.agent_kinds(self._cfg_dict())

    def has(self, kind: str) -> bool:
        return kind in self.kinds()

    def get(self, kind: str) -> base_mod.GenericAgent:
        return base_mod.build_agent_kind(kind, self.kinds().get(kind))

    def takes_prompt(self, kind: str) -> bool:
        return self.get(kind).takes_prompt

    def start_argv(
        self,
        kind: str,
        model: str = "",
        effort: str = "",
        prompt: str | None = None,
        advisor: str = "",
        fallback: str = "",
    ) -> list[str]:
        return self.get(kind).start_argv(model, effort, prompt=prompt, advisor=advisor, fallback=fallback)

    def resume_argv(
        self,
        kind: str,
        session_id: str,
        model: str = "",
        effort: str = "",
        advisor: str = "",
        fallback: str = "",
    ) -> list[str] | None:
        return self.get(kind).resume_argv(session_id, model, effort, advisor=advisor, fallback=fallback)

    def launch_wrap(self, kind: str, argv: Sequence[str]) -> list[str]:
        return self.get(kind).launch_wrap(argv, cfg=self._cfg_dict())

    def kind_from_argv(self, argv: Sequence[Any] | None) -> str:
        return base_mod.kind_from_argv(argv, kinds=self.kinds())

    def terminal_kind(self, term: Mapping[str, Any]) -> str:
        return base_mod.terminal_kind(term, kinds=self.kinds())

    def fable_on(self) -> bool:
        return profiles_mod.fable_on(self._cfg_dict())

    def builtin_profiles(self) -> dict[str, dict[str, Any]]:
        return profiles_mod.builtin_profiles(self._cfg_dict())

    def profiles(self) -> dict[str, dict[str, Any]]:
        return profiles_mod.profiles(self._cfg_dict())

    def review_models(self) -> dict[str, Any]:
        return profiles_mod.review_models(self._cfg_dict())

    def ladder(self) -> tuple[str, ...]:
        return profiles_mod.ladder(self._cfg_dict())

    def fable_fallback(self, kind: str, model: str, role: str = "worker") -> str:
        return profiles_mod.fable_fallback(kind, model, role=role, cfg=self._cfg_dict())

    def resolve_worker(self, given: Any, role: str = "worker") -> profiles_mod.WorkerSpec:
        cfg = self._cfg_dict()
        return profiles_mod.resolve_worker_spec(
            given, role=role, cfg=cfg, kinds=base_mod.agent_kinds(cfg), tr_fn=self._tr
        )

    def outside_reads(self, repo: str | Path | None, *briefs: str | Path | None) -> list[str]:
        return reads_mod._outside_reads_impl(repo, *briefs, herdr_docs=self.herdr_docs)

    def docs_line(self) -> str:
        return reads_mod.docs_line(herdr_docs=self.herdr_docs, tr_fn=self._tr)

    def read_settings(
        self,
        kind: str,
        paths: Iterable[str | Path],
        extra: Mapping[str, Any] | None = None,
        writes: Iterable[str | Path] = (),
    ) -> list[str]:
        return reads_mod.read_settings(
            kind, paths, extra=extra, writes=writes, home=self._ledger_home(), kinds=self.kinds()
        )

    def worker_argv(
        self,
        spec: profiles_mod.WorkerSpec | Any,
        reads: Iterable[str | Path] = (),
        *,
        extra: Sequence[str] = (),
        wrap: bool = False,
        codex_rec: Mapping[str, Any] | None = None,
        codex_pool_active: bool = False,
        memory_settings: Mapping[str, Any] | None = None,
        writes: Iterable[str | Path] = (),
    ) -> list[str]:
        """Assemble a worker's command line from a `WorkerSpec` (exact flag order matching `workers/dispatch.py`)."""
        cfg_dict = self._cfg_dict()
        kind = spec.kind
        model = spec.model
        codex_cfg_map = base_mod.codex_settings(codex_rec, cfg=cfg_dict) if kind == "codex" else {}
        if model and codex_cfg_map.get("model_prefix") and not model.startswith(codex_cfg_map["model_prefix"]):
            model = codex_cfg_map["model_prefix"] + model
        agent = self.get(kind)
        argv = agent.start_argv(
            model,
            spec.effort,
            advisor=getattr(spec, "advisor", ""),
            fallback=getattr(spec, "fallback", ""),
        )
        if kind == "codex":
            args = [str(x) for x in codex_cfg_map.get("args") or []]
            provider = getattr(spec, "provider", "")
            if codex_pool_active or provider:
                args = base_mod.strip_codex_args(args)
            argv = base_mod.CodexAgent.inject_provider(argv, provider=provider, extra_args=args)
        argv = argv + self.read_settings(kind, list(reads), memory_settings or {}, writes=list(writes)) + list(extra)
        return agent.launch_wrap(argv, cfg=cfg_dict) if wrap else argv

    def sessions_reader(self, cache: bool = False) -> Any:
        return sessions_mod.sessions_reader(
            cache=cache,
            home=self._ledger_home(),
            claude_projects=lambda: self.claude_projects,
        )

    def own_transcript(self) -> str:
        return sessions_mod.own_transcript(env=self._env_map(), claude_projects=self.claude_projects)

    def native_memory_settings(
        self,
        kind: str,
        memory_root: Path | str | None,
        role: str,
        name: str = "",
        *,
        create: bool = True,
    ) -> dict[str, Any]:
        enabled = (self._cfg_dict().get("memory") or {}).get("native", True) is not False
        return self.get(kind).native_memory_settings(memory_root, role, name, enabled=enabled, create=create)

    def reviewer_extra_argv(self, kind: str) -> list[str]:
        return self.get(kind).reviewer_extra_argv()

    def helper_extra_argv(self, kind: str, *, exec_mode: bool = False) -> list[str]:
        return self.get(kind).helper_extra_argv(exec_mode=exec_mode)

    def helper_writes(self, kind: str, result_path: Path | str | None) -> tuple[str, ...]:
        return self.get(kind).helper_writes(result_path)

    def claude_lean_settings(self) -> dict[str, Any]:
        return base_mod.ClaudeAgent.lean_settings(self.claude_dir)


__all__ = ["AgentRegistry"]
