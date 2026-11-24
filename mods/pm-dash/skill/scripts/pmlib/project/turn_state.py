"""Single source of truth for a project manager's live turn lifecycle, idempotent inbound user sends,
multi-message coalescing deduplication, live tool-activity extraction, and stall detection (`pm-turn.json`).
Layer 2.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from ..context import Context
from ..errors import NotFound, Refused
from ..home import project_slug
from ..osutil import clip
from ..procs import background_work
from ..store import (
    file_lock,
    local_tz_offset,
    lock_file,
    replace_task_file,
    unlock_file,
    valid_slug,
    valid_task_number,
    write_atomic,
)
from .conversation import Conversation
from .project import ProjectRegistry

_INPUT_FIELDS: dict[str, tuple[str, ...]] = {
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


def _claude_folder(path: str | Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _tidy_line(value: str, home_str: str = "") -> str:
    compact = " ".join(str(value or "").split())
    if home_str:
        clean_home = home_str.rstrip("/\\")
        if clean_home and compact.startswith(clean_home):
            rest = compact[len(clean_home):]
            if not rest or rest[0] in ("/", "\\"):
                compact = "~" + rest
    return compact

SOFT_STALL_MS = 90_000          # 90s without turn/transcript progress surfaces a quiet slow-step hint + interrupt icon
HARD_STALL_MS = 300_000         # 300s without turn/transcript progress marks the turn stalled + interrupt/rotate icons
INFLIGHT_LEASE_MS = 50_000      # single-writer lease guarding an active `hc send` call
RECENT_MSG_LIMIT = 64           # bounded idempotency table size in pm-turn.json
UNHOOKED_UI_LIMIT = 24          # bounded list of UI-logged prompts awaiting hook/transcript consumption
UNHOOKED_TTL_MS = 15 * 60_000   # 15 min TTL on unconsumed UI prompt markers
OUTBOX_LIMIT = 40               # max queued user messages per project
TURN_CAUSE_LIMIT = 8            # recent turn_seq -> deliver-batch cause map
TRANSCRIPT_TAIL_BYTES = 65_536  # 64 KiB tail probe for live tool-call observability

MSG_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_IMAGE_MARK_RE = re.compile(r"\[Image #\d+\]\s*")
_BG_SHELL_MSG_RE = re.compile(r"(?:(\d+)\s+)?shells?\s+still\s+running\b", re.I)
_DIALOG_OR_DRAFT_ERR_RE = re.compile(
    r"\bis blocked\b|\bunsent draft\b|\bhas a draft\b|\bwaiting for\b.*\bdraft\b"
    r"|\btimed out\b|\btimeout\b|\bstill_working\b|\bunavailable\b",
    re.I,
)
_FILES_HEADER_SET = frozenset({"Attachments:", "附件："})

# In-process cache `(path_str, size, mtime_ns) -> dict` so repeated `pm.py state` calls in one process
# or tests never re-parse unchanged transcript tails.
_PROBE_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


def _squash(text: str) -> str:
    return " ".join(str(text or "").split())


def _is_path_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return s.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", s)) or s.startswith("\\\\")


def _words_of_prompt(text: str) -> tuple[str, bool]:
    """Return `(normalized_words, had_trailing_files)` matching `pm-project/model.js`'s `wordsOf`."""
    cleaned = _IMAGE_MARK_RE.sub("", str(text or ""))
    lines = cleaned.replace("\r\n", "\n").split("\n")
    had_files = False
    while lines and (not lines[-1].strip() or _is_path_line(lines[-1])):
        if _is_path_line(lines[-1]):
            had_files = True
        lines.pop()
    if lines and lines[-1].strip() in _FILES_HEADER_SET:
        had_files = True
        lines.pop()
    words = _squash("\n".join(lines))
    return ("" if words in _FILES_HEADER_SET else words), had_files


def same_user_prompt(logged_text: str, sent_text: str) -> bool:
    """True when `logged_text` observed by an agent hook/transcript represents `sent_text` from the UI."""
    a, b = _squash(logged_text), _squash(sent_text)
    if not a or not b:
        return False
    if a == b:
        return True
    words_a, _ = _words_of_prompt(logged_text)
    words_b, sent_files = _words_of_prompt(sent_text)
    if sent_files and words_a == words_b:
        return True
    # Stripping `[Image #N]` marks alone (when paths stayed inline).
    if _squash(_IMAGE_MARK_RE.sub("", logged_text)) == _squash(_IMAGE_MARK_RE.sub("", sent_text)):
        return True
    return False


def match_coalesced_prompt_prefix(
    raw_text: str,
    candidates: list[dict[str, Any]],
) -> tuple[list[int], str] | None:
    """Match `raw_text` against an ordered subsequence of `candidates` (`[{"msg_id", "text", ...}]`).

    Handles both:
    - 1-to-1 match (`([idx], "")`);
    - N-to-1 coalesced match when an agent (`agy`, Claude `queued_command`, PTY buffer) joins 2+ queued
      user inputs with `\\n` or `\\n\\n` into a single prompt (`([i1, i2, ...], "")`), or when UI prompts are
      followed by an unlogged terminal-typed remainder (`([i1, ...], remainder)`).
    """
    if not raw_text or not candidates:
        return None
    for idx, item in enumerate(candidates):
        if same_user_prompt(raw_text, str(item.get("text") or "")):
            return [idx], ""

    norm_lines = [ln for ln in raw_text.replace("\r\n", "\n").split("\n")]
    while norm_lines and not norm_lines[0].strip():
        norm_lines.pop(0)
    while norm_lines and not norm_lines[-1].strip():
        norm_lines.pop()
    n = len(norm_lines)
    if n < 2 or n > 240:
        return None

    memo: dict[tuple[int, int], list[int] | None] = {}

    def solve_exact(line_idx: int, cand_start: int) -> list[int] | None:
        while line_idx < n and not norm_lines[line_idx].strip():
            line_idx += 1
        if line_idx >= n:
            return []
        state = (line_idx, cand_start)
        if state in memo:
            return memo[state]
        for end_line in range(line_idx + 1, n + 1):
            seg = "\n".join(norm_lines[line_idx:end_line]).strip()
            if not seg:
                continue
            for ci in range(cand_start, len(candidates)):
                if same_user_prompt(seg, str(candidates[ci].get("text") or "")):
                    rest = solve_exact(end_line, ci + 1)
                    if rest is not None:
                        ans = [ci, *rest]
                        memo[state] = ans
                        return ans
        memo[state] = None
        return None

    exact = solve_exact(0, 0)
    if exact and len(exact) >= 1:
        return exact, ""

    # Prefix consumption: leading UI prompt(s) coalesced with a trailing terminal-typed line.
    best_indices: list[int] = []
    best_end_line = 0
    cur_line = 0
    cand_from = 0
    while cur_line < n and cand_from < len(candidates):
        while cur_line < n and not norm_lines[cur_line].strip():
            cur_line += 1
        if cur_line >= n:
            break
        matched_here = False
        for end_line in range(n, cur_line, -1):
            seg = "\n".join(norm_lines[cur_line:end_line]).strip()
            if not seg:
                continue
            hit_ci = next(
                (ci for ci in range(cand_from, len(candidates))
                 if same_user_prompt(seg, str(candidates[ci].get("text") or ""))),
                None,
            )
            if hit_ci is not None:
                best_indices.append(hit_ci)
                best_end_line = end_line
                cur_line = end_line
                cand_from = hit_ci + 1
                matched_here = True
                break
        if not matched_here:
            break

    if best_indices and best_end_line < n:
        remainder = "\n".join(norm_lines[best_end_line:]).strip()
        if remainder:
            return best_indices, remainder
    return None


def _summarize_tool_input(tool_name: str, tool_input: Any, home_str: str = "") -> str:
    if isinstance(tool_input, str):
        return _tidy_line(tool_input, home_str)[:72]
    if not isinstance(tool_input, Mapping):
        return ""
    fields = _INPUT_FIELDS.get(tool_name) or (
        "toolSummary", "command", "CommandLine", "file_path", "Path", "path", "pattern", "Query", "query", "description", "prompt",
    )
    for key in fields:
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            return _tidy_line(val, home_str)[:72]
    return ""


def probe_transcript_activity(path: Path | None, agent_kind: str = "", *, home_str: str = "") -> dict[str, Any]:
    """Read at most the trailing 64 KiB of a PM transcript (`claude`, `codex`, `agy`) to extract live progress.

    Cached by `(path, size, mtime_ns)` so unchanged transcripts incur zero parsing overhead.
    Returns `{"mtime_ms": int, "size": int, "activity": dict | None, "ended": bool}`.
    """
    if path is None:
        return {"mtime_ms": 0, "size": 0, "activity": None, "ended": False}
    try:
        st = path.stat()
    except OSError:
        return {"mtime_ms": 0, "size": 0, "activity": None, "ended": False}
    size = st.st_size
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
    mtime_ms = int(mtime_ns // 1_000_000)
    key = str(path)
    cached = _PROBE_CACHE.get(key)
    if cached is not None and cached[0] == size and cached[1] == mtime_ns:
        return dict(cached[2])

    start = max(0, size - TRANSCRIPT_TAIL_BYTES)
    try:
        with open(path, "rb") as f:
            f.seek(start)
            raw = f.read(TRANSCRIPT_TAIL_BYTES)
    except OSError:
        return {"mtime_ms": mtime_ms, "size": size, "activity": None, "ended": False}

    nl = raw.rfind(b"\n")
    if nl < 0:
        out = {"mtime_ms": mtime_ms, "size": size, "activity": None, "ended": False}
        return out
    chunk = raw[:nl]
    if start > 0:
        first_nl = chunk.find(b"\n")
        chunk = chunk[first_nl + 1:] if first_nl >= 0 else b""

    kind_low = (agent_kind or "").strip().lower()
    open_tools: dict[str, tuple[str, str]] = {}
    tool_steps = 0
    last_tool: tuple[str, str] | None = None
    ended = False

    for line in chunk.split(b"\n"):
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if not isinstance(row, Mapping):
            continue

        rtype = str(row.get("type") or "")
        # 1. Antigravity (`agy`) transcript rows
        if rtype in ("USER_INPUT", "PLANNER_RESPONSE", "GENERIC", "ERROR_MESSAGE") or kind_low in ("agy", "antigravity"):
            if rtype == "USER_INPUT":
                open_tools.clear()
                last_tool = None
                ended = False
            elif rtype == "PLANNER_RESPONSE":
                tcalls = row.get("tool_calls")
                if isinstance(tcalls, list) and tcalls:
                    ended = False
                    for tc in tcalls:
                        if not isinstance(tc, Mapping):
                            continue
                        tname = str(tc.get("name") or tc.get("tool_name") or "tool")
                        targs = tc.get("args") if isinstance(tc.get("args"), Mapping) else tc.get("arguments")
                        if isinstance(targs, str):
                            with contextlib.suppress(ValueError):
                                targs = json.loads(targs)
                        summary = _summarize_tool_input(tname, targs, home_str)
                        tool_steps += 1
                        last_tool = (tname, summary)
                        tid = str(tc.get("id") or tool_steps)
                        open_tools[tid] = (tname, summary)
                elif str(row.get("status") or "DONE") == "DONE" and str(row.get("content") or "").strip():
                    open_tools.clear()
                    ended = True
            elif rtype == "GENERIC":
                open_tools.clear()
            elif rtype == "ERROR_MESSAGE":
                open_tools.clear()
                ended = True
            continue

        # 2. Codex rollout transcript rows (`response_item` / `event_msg`)
        payload = row.get("payload")
        if rtype in ("response_item", "event_msg") and isinstance(payload, Mapping):
            ptype = str(payload.get("type") or "")
            if ptype in ("user_message", "turn_started"):
                open_tools.clear()
                last_tool = None
                ended = False
            elif ptype in ("function_call", "custom_tool_call", "local_shell_call"):
                ended = False
                tname = str(payload.get("name") or ("Bash" if ptype == "local_shell_call" else "tool"))
                raw_args = payload.get("arguments") or payload.get("action") or payload.get("input") or {}
                if isinstance(raw_args, str):
                    with contextlib.suppress(ValueError):
                        raw_args = json.loads(raw_args)
                summary = _summarize_tool_input(tname, raw_args, home_str)
                tool_steps += 1
                last_tool = (tname, summary)
                cid = str(payload.get("call_id") or tool_steps)
                open_tools[cid] = (tname, summary)
            elif ptype in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                cid = str(payload.get("call_id") or "")
                if cid:
                    open_tools.pop(cid, None)
                else:
                    open_tools.clear()
            elif ptype in ("task_complete", "turn_complete", "agent_message"):
                if ptype in ("task_complete", "turn_complete"):
                    open_tools.clear()
                    ended = True
            continue

        # 3. Claude Code JSONL rows (`user` / `assistant` / `system`)
        if row.get("isSidechain"):
            continue
        if rtype == "user":
            msg = row.get("message")
            content = msg.get("content") if isinstance(msg, Mapping) else None
            if isinstance(content, list):
                has_user_text = False
                for blk in content:
                    if isinstance(blk, Mapping) and blk.get("type") == "tool_result":
                        tu_id = str(blk.get("tool_use_id") or "")
                        if tu_id:
                            open_tools.pop(tu_id, None)
                    elif isinstance(blk, Mapping) and blk.get("type") == "text" and str(blk.get("text") or "").strip():
                        has_user_text = True
                if has_user_text:
                    ended = False
            elif isinstance(content, str) and content.strip():
                open_tools.clear()
                last_tool = None
                ended = False
        elif rtype == "assistant":
            msg = row.get("message")
            content = msg.get("content") if isinstance(msg, Mapping) else None
            stop_reason = str(msg.get("stop_reason") or "") if isinstance(msg, Mapping) else ""
            saw_tool_use = False
            if isinstance(content, list):
                for blk in content:
                    if isinstance(blk, Mapping) and blk.get("type") == "tool_use":
                        saw_tool_use = True
                        tname = str(blk.get("name") or "tool")
                        summary = _summarize_tool_input(tname, blk.get("input"), home_str)
                        tool_steps += 1
                        last_tool = (tname, summary)
                        tu_id = str(blk.get("id") or tool_steps)
                        open_tools[tu_id] = (tname, summary)
            if saw_tool_use:
                ended = False
            elif stop_reason == "end_turn":
                open_tools.clear()
                ended = True

    active_pair = next(reversed(open_tools.values()), None) or last_tool
    activity: dict[str, Any] | None = None
    if active_pair is not None and not ended:
        tname, summary = active_pair
        activity = {
            "kind": "tool" if open_tools else "thinking",
            "tool": tname,
            "summary": summary,
            "steps": tool_steps,
        }

    result = {"mtime_ms": mtime_ms, "size": size, "activity": activity, "ended": ended}
    if len(_PROBE_CACHE) >= 128:
        _PROBE_CACHE.pop(next(iter(_PROBE_CACHE)), None)
    _PROBE_CACHE[key] = (size, mtime_ns, result)
    return dict(result)


def _send_accepted(sent: Mapping[str, Any] | None, info: Mapping[str, Any] | None) -> bool:
    if not isinstance(sent, Mapping) or sent.get("error"):
        return False
    if sent.get("started") or sent.get("ok"):
        return True
    has_status = bool((info or {}).get("status"))
    return (not has_status) and ("started" in sent) and (sent.get("status") is None)


def _send_err_text(sent: Mapping[str, Any] | None, info: Mapping[str, Any] | None, term: str) -> str:
    err = sent.get("error") if isinstance(sent, Mapping) else None
    if isinstance(err, Mapping):
        why = err.get("message") or err.get("kind")
        if why:
            return str(why)
    if isinstance(info, Mapping) and info.get("state") != "live":
        return f"hc:{term} is {info.get('state') or 'offline'}"
    return "hc send could not deliver right now"


class TurnTracker:
    """Per-project coordinator turn state & idempotent outbox persisted in `projects/<slug>/pm-turn.json`."""

    def __init__(self, ctx: Context, repo_or_slug: str | Path) -> None:
        self.ctx = ctx
        raw = str(repo_or_slug or "").strip()
        if valid_slug(raw) and (ctx.store.registration(raw) is not None or ctx.home.project(raw).root.is_dir()):
            self.slug = raw
            reg = ctx.store.registration(raw) or {}
            self.repo = str(reg.get("repo") or "")
        else:
            self.repo = raw
            self.slug = project_slug(raw) if raw else "project"
        self.files = ctx.home.project(self.slug)
        self.lock_path = self.files.pm_turn_lock

    def _now_ms(self) -> int:
        return int(self.ctx.clock.time() * 1000)

    def _default_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "updated_ms": 0,
            "terminal": "",
            "agent_kind": "",
            "turn_seq": 0,
            "phase": "idle",
            "cause": "",
            "batch": None,
            "active_msg_ids": [],
            "started_ms": 0,
            "last_activity_ms": 0,
            "activity": None,
            "interrupted_ms": 0,
            "stall_logged_seq": 0,
            "turn_causes": {},
            "inflight": None,
            "outbox": [],
            "unhooked_ui_prompts": [],
            "recent_msg_ids": {},
        }

    def read(self) -> dict[str, Any]:
        path = self.files.pm_turn
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._default_state()
        if not isinstance(raw, dict):
            return self._default_state()
        base = self._default_state()
        base.update(raw)
        if not isinstance(base.get("outbox"), list):
            base["outbox"] = []
        if not isinstance(base.get("unhooked_ui_prompts"), list):
            base["unhooked_ui_prompts"] = []
        if not isinstance(base.get("recent_msg_ids"), dict):
            base["recent_msg_ids"] = {}
        if not isinstance(base.get("turn_causes"), dict):
            base["turn_causes"] = {}
        if not isinstance(base.get("active_msg_ids"), list):
            base["active_msg_ids"] = []
        return base

    def _mutate(self, fn: Callable[[dict[str, Any]], dict[str, Any] | None], *, timeout: float = 5.0) -> dict[str, Any]:
        self.files.ensure()
        with file_lock(self.lock_path, timeout=timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            cur = self.read()
            nxt = fn(cur)
            if nxt is None:
                return cur
            nxt["updated_ms"] = self._now_ms()
            # Keep bounded collections compact.
            if isinstance(nxt.get("recent_msg_ids"), dict) and len(nxt["recent_msg_ids"]) > RECENT_MSG_LIMIT:
                items = list(nxt["recent_msg_ids"].items())[-RECENT_MSG_LIMIT:]
                nxt["recent_msg_ids"] = dict(items)
            if isinstance(nxt.get("unhooked_ui_prompts"), list):
                cutoff = nxt["updated_ms"] - UNHOOKED_TTL_MS
                kept = [
                    p for p in nxt["unhooked_ui_prompts"]
                    if isinstance(p, dict) and int(p.get("at_ms") or 0) >= cutoff
                ][-UNHOOKED_UI_LIMIT:]
                nxt["unhooked_ui_prompts"] = kept
            if isinstance(nxt.get("outbox"), list) and len(nxt["outbox"]) > OUTBOX_LIMIT:
                nxt["outbox"] = nxt["outbox"][-OUTBOX_LIMIT:]
            if isinstance(nxt.get("turn_causes"), dict) and len(nxt["turn_causes"]) > TURN_CAUSE_LIMIT:
                nxt["turn_causes"] = dict(list(nxt["turn_causes"].items())[-TURN_CAUSE_LIMIT:])
            payload = (json.dumps(nxt, ensure_ascii=False) + "\n").encode("utf-8")
            write_atomic(self.files.pm_turn, payload, replace_fn=replace_task_file)
            return nxt

    def begin_turn(
        self,
        *,
        terminal: str = "",
        agent_kind: str = "",
        cause: str = "user",
        batch: list[int] | None = None,
        msg_ids: list[str] | tuple[str, ...] = (),
        from_hook: bool = False,
    ) -> int:
        """Mark a foreground PM turn active and return its monotonic `turn_seq`."""
        now_ms = self._now_ms()
        assigned_seq = 0

        def _apply(st: dict[str, Any]) -> dict[str, Any]:
            nonlocal assigned_seq
            already_working = st.get("phase") in ("working", "stalled")
            if from_hook or not already_working:
                seq = int(st.get("turn_seq") or 0) + 1
                st["turn_seq"] = seq
                st["started_ms"] = now_ms
                st["activity"] = None
                st["interrupted_ms"] = 0
                st["active_msg_ids"] = [str(m) for m in msg_ids if m]
            else:
                seq = max(1, int(st.get("turn_seq") or 0))
                st["turn_seq"] = seq
                for m in msg_ids:
                    if m and m not in st["active_msg_ids"]:
                        st["active_msg_ids"].append(str(m))
            assigned_seq = seq
            st["phase"] = "working"
            st["last_activity_ms"] = now_ms
            if terminal:
                st["terminal"] = terminal[3:] if terminal.startswith("hc:") else terminal
            if agent_kind:
                st["agent_kind"] = agent_kind
            st["cause"] = cause
            st["batch"] = list(batch) if batch else None
            causes = dict(st.get("turn_causes") or {})
            if cause == "deliver" and batch:
                causes[str(seq)] = {"after": "deliver", "batch": list(batch)}
            else:
                causes.pop(str(seq), None)
            st["turn_causes"] = causes
            return st

        self._mutate(_apply)
        return assigned_seq

    def note_activity(self, *, kind: str = "tool", tool: str = "", summary: str = "") -> None:
        now_ms = self._now_ms()

        def _apply(st: dict[str, Any]) -> dict[str, Any]:
            st["last_activity_ms"] = now_ms
            if st.get("phase") == "stalled":
                st["phase"] = "working"
            prev_steps = int((st.get("activity") or {}).get("steps") or 0)
            st["activity"] = {
                "kind": kind,
                "tool": str(tool or ""),
                "summary": clip(str(summary or "").strip(), 80),
                "started_ms": now_ms,
                "steps": prev_steps + (1 if kind == "tool" else 0),
            }
            return st

        self._mutate(_apply)

    def end_turn(self, *, expected_seq: int | None = None) -> dict[str, Any]:
        """Close the active turn (unless a newer `turn_seq` already started) and return any `after`/`batch` cause."""
        if not self.files.pm_turn.is_file():
            return {}
        cause_out: dict[str, Any] = {}

        def _apply(st: dict[str, Any]) -> dict[str, Any]:
            nonlocal cause_out
            cur_seq = int(st.get("turn_seq") or 0)
            target_seq = cur_seq if expected_seq is None else int(expected_seq)
            causes = dict(st.get("turn_causes") or {})
            popped = causes.pop(str(target_seq), None)
            if isinstance(popped, dict):
                cause_out = {k: popped[k] for k in ("after", "batch") if k in popped}
            elif expected_seq is None and st.get("cause") == "deliver" and st.get("batch"):
                cause_out = {"after": "deliver", "batch": list(st["batch"])}
            st["turn_causes"] = causes
            if expected_seq is None or cur_seq <= target_seq:
                st["phase"] = "idle"
                st["cause"] = ""
                st["batch"] = None
                st["activity"] = None
                st["active_msg_ids"] = []
                st["last_activity_ms"] = self._now_ms()
            return st

        self._mutate(_apply)
        return cause_out

    def is_turn_stopped(self, term: str) -> bool:
        """True when `pm-turn.json` has explicitly observed at least one completed turn for `term` and is now `idle`."""
        if not self.files.pm_turn.is_file():
            return False
        st = self.read()
        clean_term = term[3:] if term.startswith("hc:") else term
        if st.get("terminal") and clean_term and st.get("terminal") != clean_term:
            return False
        return int(st.get("turn_seq") or 0) > 0 and st.get("phase") == "idle" and not st.get("inflight")

    def consume_ui_prompt(self, raw_text: str) -> tuple[bool, list[str], str]:
        """Deduplicate a hook/transcript user prompt against prompts already logged by `pm.py project send`.

        Returns `(fully_consumed, matched_msg_ids, unlogged_remainder_text)`.
        """
        text = str(raw_text or "").strip()
        if not text or not self.files.pm_turn.is_file():
            return False, [], text

        fully_consumed = False
        matched_ids: list[str] = []
        remainder_out = text
        now_ms = self._now_ms()

        def _apply(st: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal fully_consumed, matched_ids, remainder_out
            cutoff = now_ms - UNHOOKED_TTL_MS
            pool = [
                p for p in (st.get("unhooked_ui_prompts") or [])
                if isinstance(p, dict) and int(p.get("at_ms") or 0) >= cutoff
            ]
            if not pool:
                return None
            hit = match_coalesced_prompt_prefix(text, pool)
            if hit is None:
                return None
            indices, remainder = hit
            idx_set = set(indices)
            matched_ids = [str(pool[i].get("msg_id") or "") for i in indices if pool[i].get("msg_id")]
            st["unhooked_ui_prompts"] = [p for i, p in enumerate(pool) if i not in idx_set]
            fully_consumed = not bool(remainder)
            remainder_out = remainder
            return st

        self._mutate(_apply)
        return fully_consumed, matched_ids, remainder_out

    def _record_delivered_message(
        self,
        *,
        msg_id: str,
        text: str,
        question: str,
        term: str,
        agent_kind: str,
    ) -> dict[str, Any]:
        """Append the user message to `conversation.jsonl` + `receipts.json` and update `pm-turn.json`."""
        repo = self.repo or str((self.ctx.store.registration(self.slug) or {}).get("repo") or "")
        now_ms = self._now_ms()
        stamp = self.ctx.clock.now_sec()
        event_fields: dict[str, Any] = {
            "at": stamp,
            "at_ms": now_ms,
            "tz": local_tz_offset(self.ctx.clock.datetime_now()),
            "type": "user",
            "msg_id": msg_id,
            "source": "ui",
            "text": text,
        }
        if question:
            event_fields["question"] = question
        offset = self.ctx.store.append_event(self.slug, event_fields)
        # Read back `seq` from the appended tail (or compute 0 fallback).
        last_events = self.ctx.store.events(self.slug, limit=1).get("events") or []
        seq = valid_task_number(last_events[-1].get("seq")) if last_events else None
        if repo:
            conv = Conversation(self.ctx, repo)
            conv.record_receipt(text, at=stamp, at_ms=now_ms, pane=f"hc:{term}" if term else "", msg_id=msg_id)
            (self.files.turn_cause).unlink(missing_ok=True)

        rec_meta = {"seq": seq or 1, "offset": offset, "at_ms": now_ms}

        def _commit(st: dict[str, Any]) -> dict[str, Any]:
            inflight = st.get("inflight")
            if isinstance(inflight, dict) and inflight.get("msg_id") == msg_id:
                st["inflight"] = None
            recent = dict(st.get("recent_msg_ids") or {})
            recent[msg_id] = rec_meta
            st["recent_msg_ids"] = recent
            unhooked = list(st.get("unhooked_ui_prompts") or [])
            unhooked.append({"msg_id": msg_id, "text": text, "at_ms": now_ms})
            st["unhooked_ui_prompts"] = unhooked
            if st.get("phase") not in ("working", "stalled"):
                st["turn_seq"] = int(st.get("turn_seq") or 0) + 1
                st["started_ms"] = now_ms
                st["activity"] = None
                st["interrupted_ms"] = 0
                st["active_msg_ids"] = [msg_id]
            else:
                if msg_id not in st["active_msg_ids"]:
                    st["active_msg_ids"].append(msg_id)
            st["phase"] = "working"
            st["cause"] = "user"
            st["batch"] = None
            st["last_activity_ms"] = now_ms
            if term:
                st["terminal"] = term
            if agent_kind:
                st["agent_kind"] = agent_kind
            return st

        self._mutate(_commit)
        return {
            "ok": True,
            "status": "delivered",
            "msg_id": msg_id,
            **rec_meta,
            "server_now_ms": now_ms,
        }

    def send_user_message(
        self,
        *,
        msg_id: str,
        text: str,
        question: str = "",
        expected_target: str = "",
    ) -> dict[str, Any]:
        """Idempotently inject a UI user message into the PM terminal (or queue in `outbox`) and log it immediately."""
        clean_id = str(msg_id or "").strip()
        if not MSG_ID_RE.match(clean_id):
            raise ValueError(f"invalid msg_id: {msg_id!r}")
        body = str(text or "").strip()
        if not body:
            raise ValueError("message text must not be empty")

        reg = self.ctx.store.registration(self.slug)
        if reg is None:
            raise NotFound(f"no project {self.slug}")
        if reg.get("archived"):
            raise Refused(f"project {self.slug} is archived")
        repo = str(reg.get("repo") or self.repo or "")
        self.repo = repo
        agent_kind = str(reg.get("agent") or "")
        pane = str(reg.get("pane") or "")
        term = str(reg.get("terminal") or (pane[3:] if pane.startswith("hc:") else ""))
        if expected_target and not term:
            term = expected_target[3:] if expected_target.startswith("hc:") else expected_target

        now_ms = self._now_ms()
        # Step 1: check idempotency / outbox / inflight serialization under lock.
        early_reply: dict[str, Any] | None = None
        should_queue_reason = ""
        info = self.ctx.hc.get_raw(term, errors=True) if term else None
        term_live = isinstance(info, Mapping) and info.get("state") == "live"
        raw_status = info.get("status") if isinstance(info, Mapping) else None
        live_state = str(raw_status.get("state") or "") if isinstance(raw_status, Mapping) else str(raw_status or "")
        seat_busy = self.files.next_session.is_file()

        if not term_live:
            if seat_busy or (term and self.files.seat_state.is_file()):
                should_queue_reason = "starting"
            else:
                raise Refused("PM session is offline")
        elif live_state in ("blocked", "error"):
            should_queue_reason = f"pm is {live_state}"

        pre_turn = int(info.get("turn") or 0) if isinstance(info, Mapping) else 0

        def _reserve(st: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal early_reply
            recent = st.get("recent_msg_ids") or {}
            if clean_id in recent and isinstance(recent[clean_id], dict):
                early_reply = {
                    "ok": True,
                    "status": "delivered",
                    "deduped": True,
                    "msg_id": clean_id,
                    **recent[clean_id],
                    "server_now_ms": now_ms,
                }
                return None
            outbox = list(st.get("outbox") or [])
            if any(isinstance(item, dict) and item.get("msg_id") == clean_id for item in outbox):
                early_reply = {
                    "ok": True,
                    "status": "queued",
                    "deduped": True,
                    "msg_id": clean_id,
                    "queued_count": len(outbox),
                    "server_now_ms": now_ms,
                }
                return None
            inflight = st.get("inflight")
            inflight_active = isinstance(inflight, dict) and now_ms < int(inflight.get("lease_until_ms") or 0)
            if should_queue_reason or outbox or inflight_active:
                reason = should_queue_reason or ("inflight" if inflight_active else "fifo")
                outbox.append({
                    "msg_id": clean_id,
                    "text": body,
                    "question": question,
                    "queued_ms": now_ms,
                    "reason": reason,
                })
                st["outbox"] = outbox
                early_reply = {
                    "ok": True,
                    "status": "queued",
                    "msg_id": clean_id,
                    "reason": reason,
                    "queued_count": len(outbox),
                    "server_now_ms": now_ms,
                }
                return st
            st["inflight"] = {
                "msg_id": clean_id,
                "text": body,
                "question": question,
                "term": term,
                "pre_turn": pre_turn,
                "at_ms": now_ms,
                "lease_until_ms": now_ms + INFLIGHT_LEASE_MS,
            }
            return st

        self._mutate(_reserve)
        if early_reply is not None:
            return early_reply

        # Step 2: perform `hc send` outside the file lock.
        sent = self.ctx.hc.send(term, body, timeout=35, errors=True)
        if _send_accepted(sent, info):
            return self._record_delivered_message(
                msg_id=clean_id, text=body, question=question, term=term, agent_kind=agent_kind,
            )

        # Check whether `hc send` timed out AFTER delivering to the PTY (`turn` incremented).
        after_info = self.ctx.hc.get_raw(term, errors=True) if term else None
        after_turn = int(after_info.get("turn") or 0) if isinstance(after_info, Mapping) else 0
        if after_turn > pre_turn and pre_turn > 0:
            return self._record_delivered_message(
                msg_id=clean_id, text=body, question=question, term=term, agent_kind=agent_kind,
            )

        err_msg = _send_err_text(sent, after_info or info, term)
        if _DIALOG_OR_DRAFT_ERR_RE.search(err_msg):
            queued_count = 0

            def _requeue(st: dict[str, Any]) -> dict[str, Any]:
                nonlocal queued_count
                if isinstance(st.get("inflight"), dict) and st["inflight"].get("msg_id") == clean_id:
                    st["inflight"] = None
                outbox = list(st.get("outbox") or [])
                if not any(isinstance(x, dict) and x.get("msg_id") == clean_id for x in outbox):
                    outbox.insert(0, {
                        "msg_id": clean_id,
                        "text": body,
                        "question": question,
                        "queued_ms": self._now_ms(),
                        "reason": err_msg,
                    })
                st["outbox"] = outbox
                queued_count = len(outbox)
                return st

            self._mutate(_requeue)
            return {
                "ok": True,
                "status": "queued",
                "msg_id": clean_id,
                "reason": err_msg,
                "queued_count": queued_count,
                "server_now_ms": self._now_ms(),
            }

        def _clear_failed(st: dict[str, Any]) -> dict[str, Any]:
            if isinstance(st.get("inflight"), dict) and st["inflight"].get("msg_id") == clean_id:
                st["inflight"] = None
            return st

        self._mutate(_clear_failed)
        raise Refused(err_msg)

    def interrupt_pm(self) -> dict[str, Any]:
        """Send an interrupt (`SIGINT` via `hc interrupt`) to the active PM terminal without killing its session."""
        reg = self.ctx.store.registration(self.slug)
        if reg is None:
            raise NotFound(f"no project {self.slug}")
        pane = str(reg.get("pane") or "")
        term = str(reg.get("terminal") or (pane[3:] if pane.startswith("hc:") else ""))
        if not term:
            raise Refused("PM has no desktop terminal to interrupt")
        info = self.ctx.hc.get_raw(term, errors=True)
        if not isinstance(info, Mapping) or info.get("state") != "live":
            raise Refused(f"hc:{term} is offline")
        self.ctx.hc.interrupt(term, timeout=5)
        now_ms = self._now_ms()

        def _mark(st: dict[str, Any]) -> dict[str, Any]:
            st["interrupted_ms"] = now_ms
            st["last_activity_ms"] = now_ms
            if st.get("phase") == "stalled":
                st["phase"] = "working"
            return st

        self._mutate(_mark)
        return {"ok": True, "terminal": term, "interrupted_ms": now_ms, "server_now_ms": now_ms}

    def drain_outbox_and_check_stall(self, term: str, info: Mapping[str, Any]) -> float | None:
        """Called from `Deliverer.look`: recover expired inflight leases, drain FIFO `outbox`, and log hard stalls."""
        if not self.files.pm_turn.is_file() and not self.repo:
            return None
        now_ms = self._now_ms()
        st = self.read()
        reg = self.ctx.store.registration(self.slug) or {}
        agent_kind = str(reg.get("agent") or st.get("agent_kind") or "")

        # 1. Recover expired `inflight` lease if a `project send` crashed mid-call.
        inflight = st.get("inflight")
        if isinstance(inflight, dict) and now_ms >= int(inflight.get("lease_until_ms") or 0):
            cur_turn = int(info.get("turn") or 0)
            pre_turn = int(inflight.get("pre_turn") or 0)
            msg_id = str(inflight.get("msg_id") or "")
            body = str(inflight.get("text") or "")
            question = str(inflight.get("question") or "")
            if msg_id and body and cur_turn > pre_turn and pre_turn > 0:
                self._record_delivered_message(
                    msg_id=msg_id, text=body, question=question, term=term, agent_kind=agent_kind,
                )
            else:
                def _recover_to_outbox(cur_st: dict[str, Any]) -> dict[str, Any]:
                    cur_in = cur_st.get("inflight")
                    if isinstance(cur_in, dict) and cur_in.get("msg_id") == msg_id:
                        cur_st["inflight"] = None
                        outbox = list(cur_st.get("outbox") or [])
                        if msg_id and body and not any(x.get("msg_id") == msg_id for x in outbox if isinstance(x, dict)):
                            outbox.insert(0, {
                                "msg_id": msg_id,
                                "text": body,
                                "question": question,
                                "queued_ms": now_ms,
                                "reason": "recovered",
                            })
                        cur_st["outbox"] = outbox
                    return cur_st

                st = self._mutate(_recover_to_outbox)

        # 2. Drain `outbox` FIFO when terminal can receive (`idle`, `done`, or `working` without dialog).
        raw_status = info.get("status")
        live_state = str(raw_status.get("state") or "") if isinstance(raw_status, Mapping) else str(raw_status or "")
        outbox = st.get("outbox") or []
        if outbox and live_state not in ("blocked", "error") and not self.files.next_session.is_file():
            head = outbox[0] if isinstance(outbox[0], dict) else None
            if head and head.get("msg_id") and head.get("text"):
                sent = self.ctx.hc.send(term, str(head["text"]), timeout=35, errors=True)
                if _send_accepted(sent, info):
                    msg_id = str(head["msg_id"])

                    def _pop_head(cur_st: dict[str, Any]) -> dict[str, Any]:
                        cur_st["outbox"] = [
                            x for x in (cur_st.get("outbox") or [])
                            if isinstance(x, dict) and x.get("msg_id") != msg_id
                        ]
                        return cur_st

                    self._mutate(_pop_head)
                    self._record_delivered_message(
                        msg_id=msg_id,
                        text=str(head["text"]),
                        question=str(head.get("question") or ""),
                        term=term,
                        agent_kind=agent_kind,
                    )
                    return 0.2
                return 2.0

        # 3. Check live PM turn stall and log a one-shot diagnostic event when hard-stalled (>= 300s).
        snap = self.live_snapshot(reg, {"agent_status": live_state, "name": reg.get("name")}, term_info=info)
        if snap.get("stalled") and self.repo:
            cur_seq = int(snap.get("turn_seq") or 0)
            logged_seq = int(st.get("stall_logged_seq") or 0)
            if cur_seq > 0 and logged_seq < cur_seq:
                mins = max(5, int((snap.get("idle_for_ms") or HARD_STALL_MS) // 60_000))
                act_sum = str((snap.get("activity") or {}).get("summary") or "").strip()
                detail_en = f" (on `{act_sum}`)" if act_sum else ""
                detail_zh = f"（停在 `{act_sum}`）" if act_sum else ""
                msg = self.ctx.config.tr(
                    f"PM hc:{term} has made no progress for {mins} min{detail_en}; you can interrupt or start a fresh session.",
                    f"协调者 hc:{term} 已连续 {mins} 分钟无进展{detail_zh}，可在对话底部一键打断或换新会话接手。",
                )
                Conversation(self.ctx, self.repo).record(
                    "event", by=f"hc:{term}", source="pm-stall", wake=False, text=msg,
                )

                def _mark_stall(cur_st: dict[str, Any]) -> dict[str, Any]:
                    cur_st["phase"] = "stalled"
                    cur_st["stall_logged_seq"] = cur_seq
                    return cur_st

                self._mutate(_mark_stall)
        elif snap.get("phase") == "working":
            idle_ms = int(snap.get("idle_for_ms") or 0)
            if idle_ms < HARD_STALL_MS:
                return max(2.0, (HARD_STALL_MS - idle_ms) / 1000.0)
        return None

    def _resolve_pm_transcript(self, reg: Mapping[str, Any]) -> tuple[Path | None, str]:
        agent_kind = str(reg.get("agent") or "").strip().lower()
        repo = str(reg.get("repo") or self.repo or "")
        # 1. Antigravity (`agy`) bound transcript
        if agent_kind in ("agy", "antigravity") or self.files.agy_transcript.is_file():
            try:
                agy_st = json.loads(self.files.agy_transcript.read_text(encoding="utf-8"))
                cid = str((agy_st.get("session") or {}).get("id") or "")
                cursors = agy_st.get("cursors") or {}
                cpath = str((cursors.get(cid) or {}).get("path") or "")
                if cpath and Path(cpath).is_file():
                    return Path(cpath), "agy"
            except (OSError, ValueError, AttributeError):
                pass
        # 2. Recorded `agent_session` or `session` on registration (`pms/<slug>.json`)
        sess = reg.get("agent_session") if isinstance(reg.get("agent_session"), Mapping) else {}
        tpath = str(sess.get("transcript") or "")
        skind = str(sess.get("kind") or agent_kind or "claude")
        if tpath and Path(tpath).is_file():
            return Path(tpath), skind
        sid = str(sess.get("id") or reg.get("session") or "")
        if sid and repo and skind in ("claude", ""):
            proj_dir = self.ctx.agents.claude_projects / _claude_folder(repo)
            cand = proj_dir / f"{sid}.jsonl"
            if cand.is_file():
                return cand, "claude"
        return None, agent_kind

    def live_snapshot(
        self,
        reg: Mapping[str, Any] | None,
        live_pm: Mapping[str, Any] | None = None,
        *,
        term_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute a read-only live PM turn snapshot for `pm.py state` and `pm.py project events`."""
        now_ms = self._now_ms()
        st = self.read() if self.files.pm_turn.is_file() else self._default_state()
        outbox_len = len(st.get("outbox") or [])
        if not isinstance(reg, Mapping):
            return {"phase": "offline", "queued_count": outbox_len}

        live_status = ""
        status_msg = ""
        if isinstance(term_info, Mapping):
            raw_s = term_info.get("status")
            if isinstance(raw_s, Mapping):
                live_status = str(raw_s.get("state") or "")
                status_msg = str(raw_s.get("msg") or raw_s.get("message") or "")
            elif isinstance(raw_s, str):
                live_status = raw_s
        elif isinstance(live_pm, Mapping):
            live_status = str(live_pm.get("agent_status") or live_pm.get("status") or "")

        if live_status == "offline":
            return {
                "phase": "starting" if self.files.next_session.is_file() else "offline",
                "turn_seq": int(st.get("turn_seq") or 0),
                "queued_count": outbox_len,
            }

        bg_shells = 0
        m_bg = _BG_SHELL_MSG_RE.search(status_msg)
        if m_bg:
            bg_shells = int(m_bg.group(1) or 1)
        elif live_status == "working" and st.get("phase") == "idle" and isinstance(term_info, Mapping):
            fg_pid = int((term_info.get("foreground") or {}).get("pid") or term_info.get("pid") or 0)
            if fg_pid > 0:
                bg_cmds = background_work(fg_pid)
                if bg_cmds:
                    bg_shells = len(bg_cmds)

        # Reconcile foreground working vs idle/blocked.
        if live_status in ("blocked", "error"):
            return {
                "phase": "blocked",
                "turn_seq": int(st.get("turn_seq") or 0),
                "bg_shells": bg_shells,
                "queued_count": outbox_len,
            }

        if live_status in ("idle", "done"):
            started_ms = int(st.get("started_ms") or 0)
            # Keep `working` briefly (<2.5s) right after `project send` while the PTY wakes up.
            if st.get("phase") == "working" and started_ms > 0 and (now_ms - started_ms) < 2500:
                return {
                    "phase": "working",
                    "turn_seq": int(st.get("turn_seq") or 0),
                    "started_ms": started_ms,
                    "last_activity_ms": int(st.get("last_activity_ms") or started_ms),
                    "elapsed_ms": max(0, now_ms - started_ms),
                    "idle_for_ms": max(0, now_ms - int(st.get("last_activity_ms") or started_ms)),
                    "slow": False,
                    "stalled": False,
                    "activity": st.get("activity"),
                    "bg_shells": bg_shells,
                    "queued_count": outbox_len,
                }
            return {
                "phase": "idle",
                "turn_seq": int(st.get("turn_seq") or 0),
                "bg_shells": bg_shells,
                "queued_count": outbox_len,
            }

        # When terminal reports `working` solely due to background shells after turn stopped:
        if live_status == "working" and bg_shells > 0 and (m_bg or st.get("phase") == "idle"):
            return {
                "phase": "idle",
                "turn_seq": int(st.get("turn_seq") or 0),
                "bg_shells": bg_shells,
                "queued_count": outbox_len,
            }

        if live_status != "working" and st.get("phase") not in ("working", "stalled"):
            return {
                "phase": "idle",
                "turn_seq": int(st.get("turn_seq") or 0),
                "bg_shells": bg_shells,
                "queued_count": outbox_len,
            }

        tpath, detected_kind = self._resolve_pm_transcript(reg)
        probe = probe_transcript_activity(tpath, detected_kind)
        started_ms = int(st.get("started_ms") or 0) or (int(term_info.get("status_ms") or 0) if isinstance(term_info, Mapping) else 0) or probe["mtime_ms"] or now_ms
        last_act_ms = max(
            int(st.get("last_activity_ms") or 0),
            probe["mtime_ms"] if probe["mtime_ms"] >= started_ms - 2000 else 0,
            started_ms,
        )
        # If an unhooked agent (`agy`) finished its final PLANNER_RESPONSE while `hc` only keeps a bg shell:
        if probe["ended"] and bg_shells > 0 and probe["mtime_ms"] >= int(st.get("started_ms") or 0):
            return {
                "phase": "idle",
                "turn_seq": int(st.get("turn_seq") or 0),
                "bg_shells": bg_shells,
                "queued_count": outbox_len,
            }

        elapsed_ms = max(0, now_ms - started_ms)
        idle_for_ms = max(0, now_ms - last_act_ms)
        slow = idle_for_ms >= SOFT_STALL_MS
        stalled = idle_for_ms >= HARD_STALL_MS or st.get("phase") == "stalled"
        activity = probe["activity"] or st.get("activity")
        return {
            "phase": "stalled" if stalled else "working",
            "turn_seq": int(st.get("turn_seq") or 0),
            "started_ms": started_ms,
            "last_activity_ms": last_act_ms,
            "elapsed_ms": elapsed_ms,
            "idle_for_ms": idle_for_ms,
            "slow": slow,
            "stalled": stalled,
            "activity": activity,
            "bg_shells": bg_shells,
            "queued_count": outbox_len,
        }
