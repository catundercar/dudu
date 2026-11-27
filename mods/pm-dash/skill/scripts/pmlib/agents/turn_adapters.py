"""Runtime-specific turn adapters (`claude`, `codex`, `agy`, `pi`, and fallback) for incremental
transcript step observation, transcript path resolution, and optional screen hint parsing.

Layer 1 (`agents/`). Imports only stdlib, Layer 0 (`osutil`), and sibling `transcripts`.
"""
from __future__ import annotations

import contextlib
import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from ..osutil import clip

try:
    from .transcripts import INPUT_FIELDS, claude_folder
except ImportError:
    # Missing transcripts.py: degrade quietly with local fallbacks (matching agents/sessions.py)
    # so `pm.py state` stays healthy while `project session` surfaces the explicit missing-module error.
    INPUT_FIELDS: dict[str, tuple[str, ...]] = {
        "Bash": ("command",),
        "Read": ("file_path",),
        "Edit": ("file_path",),
        "Write": ("file_path",),
        "NotebookEdit": ("file_path", "notebook_path"),
        "Grep": ("pattern",),
        "Glob": ("pattern",),
        "Agent": ("description", "prompt"),
        "Task": ("description", "prompt"),
    }

    def claude_folder(path: str | Path) -> str:
        return re.sub(r"[^A-Za-z0-9]", "-", str(path))


_CLAUDE_RETRY_RE = re.compile(
    r"\bretrying\b[^\n]*?\(\s*attempt\s+(\d+)(?:\s*/\s*\d+)?\s*\)"
    r"|(\bretrying\b[^\n]*\b(?:503|529|429|eof|timeout|overloaded|rate.?limit)\b)",
    re.I,
)
_CODEX_RETRY_RE = re.compile(
    r"\b(?:retrying|reconnecting)\b(?:\.+|\s+)(\d+)\s*/\s*\d+"
    r"|\bretrying\b[^\n]*?\(\s*attempt\s+(\d+)(?:\s*/\s*\d+)?\s*\)",
    re.I,
)
_AGY_RETRY_RE = re.compile(
    r"\bretrying\b[^\n]*?\(\s*attempt\s+(\d+)(?:\s*/\s*\d+)?\s*\)"
    r"|(?:正在)?第\s*(\d+)\s*次重试",
    re.I,
)
_PI_RETRY_RE = re.compile(
    r"\bretrying\b[^\n]*?\(\s*attempt\s+(\d+)(?:\s*/\s*\d+)?\s*\)",
    re.I,
)
_TOKENS_HINT_RE = re.compile(r"(\d[\d,]*)\s*(?:tokens?|toks)\b|tokens?\s*[:=]\s*(\d[\d,]*)", re.I)
_ISO_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?")
_CLAUDE_USER_INTERRUPT_RE = re.compile(r"^\[Request interrupted by user\b", re.I)

STEP_READ_MAX = 4 << 20


def tidy_line(value: str, home_str: str = "") -> str:
    compact = " ".join(str(value or "").split())
    if home_str:
        clean_home = home_str.rstrip("/\\")
        if clean_home and compact.startswith(clean_home):
            rest = compact[len(clean_home):]
            if not rest or rest[0] in ("/", "\\"):
                compact = "~" + rest
    return compact


def summarize_tool_input(tool_name: str, tool_input: Any, home_str: str = "") -> str:
    if isinstance(tool_input, str):
        return tidy_line(tool_input, home_str)[:72]
    if not isinstance(tool_input, Mapping):
        return ""
    fields = INPUT_FIELDS.get(tool_name) or (
        "toolSummary", "command", "CommandLine", "file_path", "Path", "path",
        "pattern", "Query", "query", "description", "prompt",
    )
    for key in fields:
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            return tidy_line(val, home_str)[:72]
    return ""


def _parse_ts_ms(stamp: Any) -> int | None:
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        return int(stamp if stamp > 1e11 else stamp * 1000)
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    m = _ISO_TS_RE.fullmatch(stamp.strip())
    if not m:
        return None
    try:
        dt = datetime.datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    zone = m.group(4) or "Z"
    tz = datetime.timezone.utc
    if zone != "Z":
        minutes = int(zone[1:3]) * 60 + int(zone[-2:])
        tz = datetime.timezone(datetime.timedelta(minutes=-minutes if zone[0] == "-" else minutes))
    micro = int(((m.group(3) or "") + "000000")[:6])
    return int(dt.replace(microsecond=micro, tzinfo=tz).timestamp() * 1000)


def _read_complete_lines(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    try:
        size = path.stat().st_size
    except OSError:
        return [], offset
    if offset < 0 or offset > size:
        offset = 0
    if size <= offset:
        return [], offset
    to_read = min(size - offset, STEP_READ_MAX)
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(to_read)
    except OSError:
        return [], offset
    nl = data.rfind(b"\n")
    if nl < 0:
        return [], offset
    complete = data[:nl + 1]
    new_offset = offset + len(complete)
    rows: list[dict[str, Any]] = []
    for raw_line in complete.split(b"\n")[:-1]:
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, new_offset


def _screen_hint_with_retry(text: str, retry_re: re.Pattern[str]) -> str:
    if not text:
        return ""
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    tail = "\n".join(lines[-12:])
    m_tok = _TOKENS_HINT_RE.search(tail)
    if m_tok:
        raw_num = (m_tok.group(1) or m_tok.group(2) or "").replace(",", "")
        if raw_num.isdigit():
            return f"tokens:{raw_num}"
    m_retry = retry_re.search(tail)
    if m_retry:
        num = next((g for g in m_retry.groups() if g and g.isdigit()), "1")
        return f"retry:{num}"
    return ""


class TurnAdapter(Protocol):
    """Runtime adapter turning runtime-specific transcripts and screens into uniform observations."""

    kind: str
    steers_mid_turn: bool
    consumes_prompts: bool
    stream_idle_budget_s: int

    def transcript_path(
        self,
        reg: Mapping[str, Any],
        files: Any,
        *,
        claude_projects: Path | None = None,
        codex_sessions: Path | None = None,
    ) -> Path | None: ...

    def steps(self, path: Path, offset: int, *, home_str: str = "") -> tuple[list[dict[str, Any]], int]: ...

    def screen_hint(self, text: str) -> str: ...


class ClaudeTurnAdapter:
    kind = "claude"
    steers_mid_turn = True
    consumes_prompts = True
    stream_idle_budget_s = 300

    def transcript_path(
        self,
        reg: Mapping[str, Any],
        files: Any,
        *,
        claude_projects: Path | None = None,
        codex_sessions: Path | None = None,
    ) -> Path | None:
        sess = reg.get("agent_session") if isinstance(reg.get("agent_session"), Mapping) else {}
        tpath = str(sess.get("path") or sess.get("transcript") or "").strip()
        if tpath:
            p = Path(tpath)
            if p.is_file():
                return p
        sid = str(sess.get("id") or reg.get("session") or "").strip()
        repo = str(reg.get("repo") or "").strip()
        if sid and repo and claude_projects is not None:
            cand = Path(claude_projects) / claude_folder(repo) / f"{sid}.jsonl"
            if cand.is_file():
                return cand
        return None

    def steps(self, path: Path, offset: int, *, home_str: str = "") -> tuple[list[dict[str, Any]], int]:
        rows, new_offset = _read_complete_lines(path, offset)
        obs: list[dict[str, Any]] = []
        for row in rows:
            if row.get("isSidechain"):
                continue
            ts = _parse_ts_ms(row.get("timestamp"))
            rtype = str(row.get("type") or "")
            if rtype == "user":
                msg = row.get("message") if isinstance(row.get("message"), Mapping) else {}
                content = msg.get("content")
                if isinstance(content, str) and _CLAUDE_USER_INTERRUPT_RE.match(content.strip()):
                    item_int: dict[str, Any] = {"src": "transcript:claude", "kind": "step_interrupted"}
                    if ts is not None:
                        item_int["t"] = ts
                    obs.append(item_int)
                elif isinstance(content, list):
                    for blk in content:
                        if not isinstance(blk, Mapping):
                            continue
                        if blk.get("type") == "tool_result":
                            item: dict[str, Any] = {
                                "src": "transcript:claude",
                                "kind": "step_tool_end",
                                "call_id": str(blk.get("tool_use_id") or ""),
                            }
                            if ts is not None:
                                item["t"] = ts
                            obs.append(item)
                        elif blk.get("type") == "text" and _CLAUDE_USER_INTERRUPT_RE.match(str(blk.get("text") or "").strip()):
                            item_int = {"src": "transcript:claude", "kind": "step_interrupted"}
                            if ts is not None:
                                item_int["t"] = ts
                            obs.append(item_int)
            elif rtype == "assistant":
                msg = row.get("message") if isinstance(row.get("message"), Mapping) else {}
                content = msg.get("content")
                stop_reason = str(msg.get("stop_reason") or "")
                preamble = ""
                saw_tool = False
                if isinstance(content, list):
                    for blk in content:
                        if not isinstance(blk, Mapping):
                            continue
                        btype = blk.get("type")
                        if btype == "text" and str(blk.get("text") or "").strip():
                            preamble = clip(" ".join(str(blk["text"]).split()), 120)
                        elif btype == "tool_use":
                            saw_tool = True
                            tname = str(blk.get("name") or "tool")
                            item = {
                                "src": "transcript:claude",
                                "kind": "step_tool_start",
                                "tool": tname,
                                "summary": summarize_tool_input(tname, blk.get("input"), home_str),
                                "call_id": str(blk.get("id") or ""),
                            }
                            if preamble:
                                item["preamble"] = preamble
                                preamble = ""
                            if ts is not None:
                                item["t"] = ts
                            obs.append(item)
                if not saw_tool and stop_reason == "end_turn":
                    item = {"src": "transcript:claude", "kind": "step_reply"}
                    if ts is not None:
                        item["t"] = ts
                    obs.append(item)
            elif rtype == "system" and str(row.get("subtype") or "") in ("api_error", "error"):
                err_txt = str(row.get("error") or row.get("message") or row.get("content") or "")
                item = {"src": "transcript:claude", "kind": "step_error", "message": clip(err_txt, 200)}
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
        return obs, new_offset

    def screen_hint(self, text: str) -> str:
        return _screen_hint_with_retry(text, _CLAUDE_RETRY_RE)


class CodexTurnAdapter:
    kind = "codex"
    steers_mid_turn = True
    consumes_prompts = True
    stream_idle_budget_s = 300

    def transcript_path(
        self,
        reg: Mapping[str, Any],
        files: Any,
        *,
        claude_projects: Path | None = None,
        codex_sessions: Path | None = None,
    ) -> Path | None:
        sess = reg.get("agent_session") if isinstance(reg.get("agent_session"), Mapping) else {}
        tpath = str(sess.get("path") or sess.get("transcript") or "").strip()
        if tpath:
            p = Path(tpath)
            if p.is_file():
                return p
        return None

    def steps(self, path: Path, offset: int, *, home_str: str = "") -> tuple[list[dict[str, Any]], int]:
        rows, new_offset = _read_complete_lines(path, offset)
        obs: list[dict[str, Any]] = []
        for row in rows:
            ts = _parse_ts_ms(row.get("timestamp"))
            rtype = str(row.get("type") or "")
            payload = row.get("payload")
            if rtype not in ("response_item", "event_msg") or not isinstance(payload, Mapping):
                continue
            ptype = str(payload.get("type") or "")
            if ptype in ("function_call", "custom_tool_call", "local_shell_call"):
                tname = str(payload.get("name") or ("Bash" if ptype == "local_shell_call" else "tool"))
                raw_args = payload.get("arguments") or payload.get("action") or payload.get("input") or {}
                if isinstance(raw_args, str):
                    with contextlib.suppress(ValueError):
                        raw_args = json.loads(raw_args)
                item: dict[str, Any] = {
                    "src": "transcript:codex",
                    "kind": "step_tool_start",
                    "tool": tname,
                    "summary": summarize_tool_input(tname, raw_args, home_str),
                    "call_id": str(payload.get("call_id") or ""),
                }
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
            elif ptype in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                item = {
                    "src": "transcript:codex",
                    "kind": "step_tool_end",
                    "call_id": str(payload.get("call_id") or ""),
                }
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
            elif ptype in ("task_complete", "turn_complete"):
                item = {"src": "transcript:codex", "kind": "step_reply"}
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
            elif ptype == "turn_aborted":
                item = {"src": "transcript:codex", "kind": "step_interrupted"}
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
            elif ptype in ("error", "stream_error"):
                msg = str(payload.get("message") or payload.get("error") or "")
                item = {"src": "transcript:codex", "kind": "step_error", "message": clip(msg, 200)}
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
        return obs, new_offset

    def screen_hint(self, text: str) -> str:
        return _screen_hint_with_retry(text, _CODEX_RETRY_RE)


class AgyTurnAdapter:
    kind = "agy"
    steers_mid_turn = False
    consumes_prompts = True
    stream_idle_budget_s = 600

    def transcript_path(
        self,
        reg: Mapping[str, Any],
        files: Any,
        *,
        claude_projects: Path | None = None,
        codex_sessions: Path | None = None,
    ) -> Path | None:
        agy_state_path = getattr(files, "agy_transcript", None) if files is not None else None
        if isinstance(agy_state_path, Path) and agy_state_path.is_file():
            with contextlib.suppress(OSError, ValueError, AttributeError):
                agy_st = json.loads(agy_state_path.read_text(encoding="utf-8"))
                cid = str((agy_st.get("session") or {}).get("id") or "")
                cursors = agy_st.get("cursors") or {}
                cpath = str((cursors.get(cid) or {}).get("path") or "")
                if cpath and Path(cpath).is_file():
                    return Path(cpath)
        sess = reg.get("agent_session") if isinstance(reg.get("agent_session"), Mapping) else {}
        tpath = str(sess.get("path") or sess.get("transcript") or "").strip()
        if tpath:
            p = Path(tpath)
            if p.is_file():
                return p
        return None

    def steps(self, path: Path, offset: int, *, home_str: str = "") -> tuple[list[dict[str, Any]], int]:
        rows, new_offset = _read_complete_lines(path, offset)
        obs: list[dict[str, Any]] = []
        for row in rows:
            ts = _parse_ts_ms(row.get("created_at"))
            rtype = str(row.get("type") or "")
            if rtype == "SYSTEM_MESSAGE":
                item: dict[str, Any] = {"src": "transcript:agy", "kind": "step_system"}
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
            elif rtype == "PLANNER_RESPONSE":
                tcalls = row.get("tool_calls")
                if isinstance(tcalls, list) and tcalls:
                    preamble = clip(" ".join(str(row.get("thinking") or row.get("content") or "").split()), 120)
                    for tc in tcalls:
                        if not isinstance(tc, Mapping):
                            continue
                        tname = str(tc.get("name") or tc.get("tool_name") or "tool")
                        targs = tc.get("args") if isinstance(tc.get("args"), Mapping) else tc.get("arguments")
                        if isinstance(targs, str):
                            with contextlib.suppress(ValueError):
                                targs = json.loads(targs)
                        item = {
                            "src": "transcript:agy",
                            "kind": "step_tool_start",
                            "tool": tname,
                            "summary": summarize_tool_input(tname, targs, home_str),
                            "call_id": str(tc.get("id") or ""),
                        }
                        if preamble:
                            item["preamble"] = preamble
                            preamble = ""
                        if ts is not None:
                            item["t"] = ts
                        obs.append(item)
                elif str(row.get("status") or "DONE") == "DONE" and str(row.get("content") or "").strip():
                    item = {"src": "transcript:agy", "kind": "step_reply"}
                    if ts is not None:
                        item["t"] = ts
                    obs.append(item)
            elif rtype == "GENERIC":
                item = {"src": "transcript:agy", "kind": "step_tool_end"}
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
            elif rtype == "ERROR_MESSAGE":
                msg = str(row.get("content") or row.get("error") or row.get("message") or "error")
                item = {"src": "transcript:agy", "kind": "step_error", "message": clip(msg, 200)}
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
        return obs, new_offset

    def screen_hint(self, text: str) -> str:
        return _screen_hint_with_retry(text, _AGY_RETRY_RE)


class PiTurnAdapter:
    kind = "pi"
    steers_mid_turn = False
    consumes_prompts = False
    stream_idle_budget_s = 300

    def transcript_path(
        self,
        reg: Mapping[str, Any],
        files: Any,
        *,
        claude_projects: Path | None = None,
        codex_sessions: Path | None = None,
    ) -> Path | None:
        sess = reg.get("agent_session") if isinstance(reg.get("agent_session"), Mapping) else {}
        tpath = str(sess.get("path") or sess.get("transcript") or "").strip()
        if tpath:
            p = Path(tpath)
            if p.is_file():
                return p
        return None

    def steps(self, path: Path, offset: int, *, home_str: str = "") -> tuple[list[dict[str, Any]], int]:
        rows, new_offset = _read_complete_lines(path, offset)
        obs: list[dict[str, Any]] = []
        for row in rows:
            ts = _parse_ts_ms(row.get("timestamp"))
            rtype = str(row.get("type") or row.get("role") or "")
            if rtype in ("tool_call", "toolCall"):
                tname = str(row.get("toolName") or row.get("name") or "tool")
                item: dict[str, Any] = {
                    "src": "transcript:pi",
                    "kind": "step_tool_start",
                    "tool": tname,
                    "summary": summarize_tool_input(tname, row.get("args") or row.get("input"), home_str),
                    "call_id": str(row.get("id") or row.get("toolCallId") or ""),
                }
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
            elif rtype in ("tool_result", "toolResult"):
                item = {
                    "src": "transcript:pi",
                    "kind": "step_tool_end",
                    "call_id": str(row.get("toolCallId") or row.get("id") or ""),
                }
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
            elif rtype == "assistant" and str(row.get("stopReason") or "") == "stop":
                item = {"src": "transcript:pi", "kind": "step_reply"}
                if ts is not None:
                    item["t"] = ts
                obs.append(item)
        return obs, new_offset

    def screen_hint(self, text: str) -> str:
        return _screen_hint_with_retry(text, _PI_RETRY_RE)


class FallbackTurnAdapter:
    kind = "other"
    steers_mid_turn = False
    consumes_prompts = False
    stream_idle_budget_s = 300

    def transcript_path(
        self,
        reg: Mapping[str, Any],
        files: Any,
        *,
        claude_projects: Path | None = None,
        codex_sessions: Path | None = None,
    ) -> Path | None:
        return None

    def steps(self, path: Path, offset: int, *, home_str: str = "") -> tuple[list[dict[str, Any]], int]:
        return [], offset

    def screen_hint(self, text: str) -> str:
        return ""


_ADAPTERS: dict[str, TurnAdapter] = {
    "claude": ClaudeTurnAdapter(),
    "codex": CodexTurnAdapter(),
    "agy": AgyTurnAdapter(),
    "pi": PiTurnAdapter(),
    "other": FallbackTurnAdapter(),
}


def adapter_for(kind: str) -> TurnAdapter:
    """Return the `TurnAdapter` for `kind` (`claude`, `codex`, `agy`, `pi`, or fallback)."""
    norm = str(kind or "").strip().lower()
    if norm in ("claude", "claude-code"):
        return _ADAPTERS["claude"]
    if norm in ("codex",):
        return _ADAPTERS["codex"]
    if norm in ("agy", "antigravity"):
        return _ADAPTERS["agy"]
    if norm in ("pi",):
        return _ADAPTERS["pi"]
    return _ADAPTERS["other"]
