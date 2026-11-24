"""The agent programs: declarative `AgentSpec`, `GenericAgent` and the three behaviorally distinct subclasses
(`ClaudeAgent`, `CodexAgent`, `PiAgent`), command-line assembly, `pm.py seat` unwrapping, and launcher wrapping.
Layer 1."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex
from typing import Any, Mapping, Sequence

from .. import config as config_mod
from ..osutil import shell_join, slugify


HOOKED_KINDS = ("claude", "codex")  # their Stop hook reports a worker that stops unreported (worker_stopped)


# How each coding agent is started, as a PM or as a worker. "{}" stands for the value. `prompt_arg`: the program
# takes its first prompt as a trailing argument; without it the prompt is typed in once the program is ready.
# config.json adds or overrides kinds: {"agents": {"mine": {"argv": ["mine", "--yes"], "model": ["--model", "{}"]}}}.
AGENT_KINDS = {
    # --advisor is not in `claude --help`; a Fable advisor needs the account to have agreed to Fable's billing once.
    "claude": {"argv": ["claude"], "model": ["--model", "{}"], "effort": ["--effort", "{}"],
               "advisor": ["--advisor", "{}"], "fallback": ["--fallback-model", "{}"], "prompt_arg": True},
    # No update prompt at startup: it would take the place of the input and the brief could not be delivered.
    "codex": {"argv": ["codex", "-c", "check_for_update_on_startup=false"], "model": ["-m", "{}"],
              "effort": ["-c", 'model_reasoning_effort="{}"'], "prompt_arg": True},
    "pi": {"argv": ["pi"], "model": ["--model", "{}"], "effort": ["--thinking", "{}"], "prompt_arg": True},
    "gemini": {"argv": ["gemini"], "model": ["-m", "{}"], "effort": []},
    "opencode": {"argv": ["opencode"], "model": ["-m", "{}"], "effort": []},
}


# What herdr-core calls a program where that differs from the kind's name.
APP_KINDS = {"claude-code": "claude"}

# What a program's screen shows once its input is ready, for a terminal herdr-core reports no status for (a program
# started through a shell launcher, `zsh -ic '…'`, can show as zsh).
READY_MARKS = {"claude": ("bypass permissions", "? for shortcuts"), "codex": ("Ask Codex",)}


@dataclass(frozen=True)
class AgentSpec:
    """Declarative CLI specification for an agent program."""

    name: str
    argv: tuple[str, ...]
    model: tuple[str, ...] = ()
    effort: tuple[str, ...] = ()
    advisor: tuple[str, ...] = ()
    fallback: tuple[str, ...] = ()
    prompt_arg: bool = False
    ready_marks: tuple[str, ...] = ()
    has_stop_hook: bool = False

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> AgentSpec:
        return cls(
            name=name,
            argv=tuple(str(x) for x in (data.get("argv") or ())),
            model=tuple(str(x) for x in (data.get("model") or ())),
            effort=tuple(str(x) for x in (data.get("effort") or ())),
            advisor=tuple(str(x) for x in (data.get("advisor") or ())),
            fallback=tuple(str(x) for x in (data.get("fallback") or ())),
            prompt_arg=bool(data.get("prompt_arg")),
            ready_marks=tuple(READY_MARKS.get(name, ())),
            has_stop_hook=name in HOOKED_KINDS,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"argv": list(self.argv)}
        if self.model:
            out["model"] = list(self.model)
        if self.effort:
            out["effort"] = list(self.effort)
        if self.advisor:
            out["advisor"] = list(self.advisor)
        if self.fallback:
            out["fallback"] = list(self.fallback)
        if self.prompt_arg:
            out["prompt_arg"] = True
        return out


def _fill_flags(flags: Sequence[str], value: str) -> list[str]:
    return [f.replace("{}", value) for f in flags] if value and flags else []


class GenericAgent:
    """Spec-driven agent kind handling flag substitution, prompt delivery mode, and default behavior."""

    has_stop_hook: bool = False

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self.has_stop_hook = spec.has_stop_hook or self.__class__.has_stop_hook

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def program(self) -> str:
        return Path(self.spec.argv[0]).name if self.spec.argv else ""

    @property
    def takes_prompt(self) -> bool:
        return self.spec.prompt_arg

    @property
    def ready_marks(self) -> tuple[str, ...]:
        return self.spec.ready_marks

    @property
    def supports_advisor(self) -> bool:
        return bool(self.spec.advisor)

    @property
    def supports_fallback(self) -> bool:
        return bool(self.spec.fallback)

    def start_argv(
        self,
        model: str = "",
        effort: str = "",
        prompt: str | None = None,
        advisor: str = "",
        fallback: str = "",
    ) -> list[str]:
        return (
            list(self.spec.argv)
            + _fill_flags(self.spec.model, model)
            + _fill_flags(self.spec.effort, effort)
            + _fill_flags(self.spec.advisor, advisor)
            + _fill_flags(self.spec.fallback, fallback)
            + ([prompt] if prompt and self.spec.prompt_arg else [])
        )

    def resume_argv(
        self,
        session_id: str,
        model: str = "",
        effort: str = "",
        advisor: str = "",
        fallback: str = "",
    ) -> list[str] | None:
        return None

    def launch_wrap(self, argv: Sequence[str], *, cfg: Mapping[str, Any] | None = None) -> list[str]:
        return list(argv)

    def successor_argv(self, old_args: Sequence[str], model: str, prompt: str) -> list[str]:
        return self.start_argv(model, prompt=prompt)

    def pm_start_argv(self, model: str, prompt: str) -> list[str]:
        return self.start_argv(model, prompt=prompt)

    def native_memory_settings(
        self,
        memory_root: Path | str | None,
        role: str,
        name: str = "",
        *,
        enabled: bool = True,
        create: bool = True,
    ) -> dict[str, Any]:
        if self.program != "claude" or not enabled or not memory_root:
            return {}
        root = Path(memory_root)
        if not root.is_dir():
            return {}
        where = root if role == "pm" else root / "candidates" / (slugify(name) or "worker")
        if create:
            where.mkdir(parents=True, exist_ok=True)
        return {"autoMemoryEnabled": True, "autoMemoryDirectory": str(where)}

    def reviewer_extra_argv(self) -> list[str]:
        return []

    def helper_extra_argv(self, *, exec_mode: bool = False) -> list[str]:
        return []

    def helper_writes(self, result_path: Path | str | None) -> tuple[str, ...]:
        return ()


def _apply_launcher(kind: str, argv: Sequence[str], cfg: Mapping[str, Any] | None) -> list[str]:
    cfg_map = config_mod.config() if cfg is None else cfg
    spec = (cfg_map.get(kind) or {}).get("launcher") if kind in ("claude", "codex") else None
    argv_list = list(argv)
    if not isinstance(spec, list) or not spec:
        return argv_list
    spec_str = [str(x) for x in spec]
    if any("{args}" in x for x in spec_str):
        rest = shell_join(argv_list[1:])
        return [x.replace("{args}", rest) for x in spec_str]
    return spec_str + argv_list[1:]


class ClaudeAgent(GenericAgent):
    """Claude Code: --advisor, --fallback-model, --resume, narrow/lean PM flags, Stop-hook block, transcripts."""

    has_stop_hook: bool = True
    NARROW: tuple[str, ...] = ("--disallowedTools", "Edit,NotebookEdit")
    REVIEWER_DISALLOWED: tuple[str, ...] = ()
    HELPER_READONLY_DISALLOWED: tuple[str, ...] = ("--disallowedTools", "Edit,NotebookEdit")
    LEAN: tuple[str, ...] = ("--strict-mcp-config", "--no-chrome")
    KEEP_VALUE: tuple[str, ...] = (
        "--mcp-config", "--permission-mode", "--settings", "--add-dir", "--plugin-dir",
        "--allowed-tools", "--allowedTools", "--disallowed-tools", "--disallowedTools",
        "--append-system-prompt", "--agents", "--effort", "--setting-sources",
    )

    def resume_argv(
        self,
        session_id: str,
        model: str = "",
        effort: str = "",
        advisor: str = "",
        fallback: str = "",
    ) -> list[str]:
        return self.start_argv(model, effort, advisor=advisor, fallback=fallback) + ["--resume", session_id]

    def launch_wrap(self, argv: Sequence[str], *, cfg: Mapping[str, Any] | None = None) -> list[str]:
        return _apply_launcher("claude", argv, cfg)

    def pm_start_argv(self, model: str, prompt: str) -> list[str]:
        return self.start_argv(model) + (["--", prompt] if self.takes_prompt else [])

    def successor_argv(self, old_args: Sequence[str], model: str, prompt: str) -> list[str]:
        argv = list(self.spec.argv) or ["claude"]
        args = list(old_args)
        extra_prefix = argv[1:]
        if extra_prefix and args[:len(extra_prefix)] == extra_prefix:
            args = args[len(extra_prefix):]
        for i, arg in enumerate(args):
            if arg == "--":
                break
            if not arg.startswith("-") or arg in ("--resume", "-r", "--continue", "-c", "--model", "--fork-session"):
                continue
            argv.append(arg)
            if arg in self.KEEP_VALUE and i + 1 < len(args):
                argv.append(args[i + 1])
        return argv + (["--model", model] if model else []) + ["--", prompt]

    def narrow_pm_argv(self, argv: Sequence[str], *, narrow_tools: bool = True) -> list[str]:
        argv_list = list(argv)
        cut = argv_list.index("--") if "--" in argv_list else len(argv_list)
        head: list[str] = []
        i = 0
        narrow_pair = list(self.NARROW)
        while i < cut:
            if argv_list[i:i + 2] == narrow_pair:
                i += 2
                continue
            head.append(argv_list[i])
            i += 1
        if narrow_tools:
            head += narrow_pair
        return head + argv_list[cut:]

    @staticmethod
    def lean_settings(claude_dir: Path | str) -> dict[str, Any]:
        """Settings for a lean Claude Code PM, read from `claude_dir` without touching process globals."""
        home = Path(claude_dir)
        try:
            enabled = json.loads((home / "settings.json").read_text()).get("enabledPlugins") or {}
        except (OSError, ValueError, AttributeError):
            enabled = {}
        names = {skill.parent.name for skill in (home / "skills").glob("*/SKILL.md")}
        for manifest in (home / "skills" / "synced").glob("*/manifest.json"):
            try:
                names |= {
                    f"anthropic-skills:{s['name']}"
                    for s in json.loads(manifest.read_text()).get("skills") or []
                    if isinstance(s, dict) and s.get("name")
                }
            except (OSError, ValueError, AttributeError):
                pass
        names.discard("pm")
        return {
            "enabledPlugins": {p: False for p, on in (enabled.items() if isinstance(enabled, dict) else []) if on},
            "skillOverrides": {n: "user-invocable-only" for n in sorted(names)},
        }

    @staticmethod
    def stop_block_payload(reason: str) -> dict[str, str]:
        return {"decision": "block", "reason": reason}

    def reviewer_extra_argv(self) -> list[str]:
        return list(self.REVIEWER_DISALLOWED)

    def helper_extra_argv(self, *, exec_mode: bool = False) -> list[str]:
        return [] if exec_mode else list(self.HELPER_READONLY_DISALLOWED)

    def helper_writes(self, result_path: Path | str | None) -> tuple[str, ...]:
        return (str(result_path),) if result_path else ()


class CodexAgent(GenericAgent):
    """Codex CLI: `codex resume`, `-p <provider>` pool injection, PM compaction flags, Stop hook."""

    has_stop_hook: bool = True

    def resume_argv(
        self,
        session_id: str,
        model: str = "",
        effort: str = "",
        advisor: str = "",
        fallback: str = "",
    ) -> list[str]:
        argv = self.start_argv(model, effort, advisor=advisor, fallback=fallback)
        return [argv[0], "resume", *argv[1:], session_id]

    def launch_wrap(self, argv: Sequence[str], *, cfg: Mapping[str, Any] | None = None) -> list[str]:
        return _apply_launcher("codex", argv, cfg)

    @staticmethod
    def inject_provider(argv: Sequence[str], provider: str = "", extra_args: Sequence[str] = ()) -> list[str]:
        out = list(argv)
        prefix = (["-p", provider] if provider else []) + [str(x) for x in extra_args]
        if prefix:
            out[1:1] = prefix
        return out

    @staticmethod
    def compact_pm_argv(
        argv: Sequence[str],
        *,
        limit: int,
        post_turn_percent: int,
        compact_prompt: str,
    ) -> list[str]:
        argv_list = list(argv)
        if not argv_list or not limit:
            return argv_list
        limit = max(100_000, limit)
        cleaned = [argv_list[0]]
        i = 1
        while i < len(argv_list):
            if argv_list[i] == "-c" and i + 1 < len(argv_list) and str(argv_list[i + 1]).startswith((
                "model_auto_compact_token_limit=",
                "model_post_turn_compact_threshold_percent=",
                "compact_prompt=",
            )):
                i += 2
                continue
            cleaned.append(argv_list[i])
            i += 1
        flags = [
            "-c", f"model_auto_compact_token_limit={limit}",
            "-c", f"model_post_turn_compact_threshold_percent={post_turn_percent}",
            "-c", f"compact_prompt={json.dumps(compact_prompt, ensure_ascii=False)}",
        ]
        cleaned[1:1] = flags
        return cleaned


class PiAgent(GenericAgent):
    """pi agent: attaches `pm_pi_compact.js` extension for PM compaction."""

    @staticmethod
    def compact_pm_argv(
        argv: Sequence[str],
        *,
        ext_path: Path | str,
        compact_enabled: bool = True,
    ) -> list[str]:
        argv_list = list(argv)
        ext = Path(ext_path)
        if not argv_list or not compact_enabled or not ext.is_file():
            return argv_list
        cleaned = [argv_list[0]]
        i = 1
        while i < len(argv_list):
            if argv_list[i] in ("-e", "--extension") and i + 1 < len(argv_list) and Path(str(argv_list[i + 1])).name == ext.name:
                i += 2
                continue
            cleaned.append(argv_list[i])
            i += 1
        cleaned[1:1] = ["-e", str(ext)]
        return cleaned


_AGENT_CLASSES: dict[str, type[GenericAgent]] = {
    "claude": ClaudeAgent,
    "codex": CodexAgent,
    "pi": PiAgent,
}


def build_agent_kind(name: str, spec_data: Mapping[str, Any] | None) -> GenericAgent:
    """Instantiate the concrete `GenericAgent` subclass for `name` (or an ad-hoc command string when unknown)."""
    if spec_data is None:
        return GenericAgent(AgentSpec(name=name, argv=tuple(shlex.split(name))))
    spec = AgentSpec.from_dict(name, spec_data)
    cls = _AGENT_CLASSES.get(name, GenericAgent)
    return cls(spec)


def agent_kinds(cfg: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    cfg_map = config_mod.config() if cfg is None else cfg
    kinds = {k: dict(v) for k, v in AGENT_KINDS.items()}
    for name, spec in (cfg_map.get("agents") or {}).items():
        if isinstance(spec, dict) and spec.get("argv"):
            kinds[name] = {**kinds.get(name, {}), **spec}
    return kinds


def agent_argv(kind: str, model: str = "", effort: str = "", prompt: str | None = None,
               advisor: str = "", fallback: str = "") -> list[str]:
    """The command that starts an agent of this kind. An unknown kind is run as written ("myagent --flag").
    fallback: the model to switch to when `model` cannot be used, for programs that take one (see fable_fallback)."""
    return build_agent_kind(kind, agent_kinds().get(kind)).start_argv(
        model, effort, prompt=prompt, advisor=advisor, fallback=fallback
    )


def takes_prompt(kind: str) -> bool:
    return bool((agent_kinds().get(kind) or {}).get("prompt_arg"))


def is_seat_argv(argv: Sequence[Any] | None) -> bool:
    """Whether `argv` is a `pm.py seat ...` command line."""
    for i, arg in enumerate(argv or ()):
        if Path(str(arg)).name == "pm.py":
            rest = list(argv[i + 1:])
            if rest[:1] == ["--home"] and len(rest) > 2:
                rest = rest[2:]
            return rest[:1] == ["seat"]
    return False


def unwrap_seat_argv(argv: Sequence[Any] | None) -> tuple[str, list[Any]]:
    """(explicit_kind, inner_argv) of a `pm.py seat ... -- <inner>` command line, or ("", argv)."""
    if not is_seat_argv(argv):
        return "", list(argv or ())
    explicit = ""
    for i, arg in enumerate(argv or ()):
        if arg == "--":
            return explicit, list((argv or ())[i + 1:])
        if arg == "--kind" and i + 1 < len(argv or ()):
            explicit = str((argv or ())[i + 1])
    return explicit, []


def kind_from_argv(argv: Sequence[Any] | None, *, kinds: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    explicit, inner = unwrap_seat_argv(argv)
    if explicit:
        return explicit
    program = Path(inner[0]).name if inner else ""
    table = agent_kinds() if kinds is None else kinds
    for kind, spec in table.items():
        if program and program == Path(spec["argv"][0]).name:
            return kind
    return program


def terminal_kind(term: Mapping[str, Any], *, kinds: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    """The kind of the agent running in a herdr-core terminal, from its program."""
    table = agent_kinds() if kinds is None else kinds
    fg = (term.get("foreground") or {}).get("argv") or []
    found = kind_from_argv(fg, kinds=table) if fg else ""
    if not found:
        found = kind_from_argv(term.get("argv") or [], kinds=table)
    if found in table:
        return found
    app = (term.get("status") or {}).get("app") or ""
    return APP_KINDS.get(app, app) or found


def launch_wrap(kind: str, argv: Sequence[str], *, cfg: Mapping[str, Any] | None = None) -> list[str]:
    """argv as config.json's launcher for the kind starts it (claude.launcher, codex.launcher), for example
    ["zsh", "-ic", "my-claude {args}"]: {args} is what follows the program, quoted as shell_join quotes it; without
    {args} those are added at the end. No launcher: argv as it is."""
    return _apply_launcher(kind, argv, cfg)


def codex_settings(rec: Mapping[str, Any] | None = None, *, cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg_map = config_mod.config() if cfg is None else cfg
    got = (rec or {}).get("codex") or cfg_map.get("codex") or {}
    return got if isinstance(got, dict) else {}


def strip_codex_args(args: Sequence[str], provider: bool = True) -> list[str]:
    """The PM's codex args without service_tier (fast is a profile's `fast`, sent as /fast) and model_provider (it
    would override the profile's provider; the default provider is codex's own config, not the PM's args)."""
    drop = ("service_tier",) + (("model_provider",) if provider else ())
    out: list[str] = []
    skip = False
    for i, x in enumerate(args):
        if skip:
            skip = False
            continue
        value = args[i + 1] if x in ("-c", "--config") and i + 1 < len(args) else x
        if any(re.match(rf"(?:--config=|-c)?\s*{k}\s*=", value) for k in drop):
            skip = value is not x
            continue
        out.append(x)
    return out
