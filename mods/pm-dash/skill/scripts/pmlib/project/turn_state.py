"""Storage & external facade for per-project PM turn state (`pm-turn.json` v2) and observation journal
(`pm-turn-journal.jsonl`). Pure turn state logic lives in `turn_reducer.py` (I1-I5). Layer 2.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from ..agents.turn_adapters import adapter_for, summarize_tool_input
from ..context import Context
from ..errors import NotFound, Refused
from ..home import project_slug
from ..messaging.address import Endpoint, LogicalAddress, parse_legacy_endpoint, safe_endpoint_uid
from ..messaging.envelope import P1_USER, Envelope, extract_env_id, new_env_id
from ..messaging.mailbox import PENDING_TURN, MailboxStore, merge_receipts_compat
from ..messaging.principal import Principal
from ..messaging.transports.local_hc import LocalHcTransport
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
from .conversation import Conversation, read_receipts
from .project import ProjectRegistry
from .turn_reducer import (
    OCCUPATION_HINT_COOLDOWN_MS,
    TurnConfig,
    default_state_v2,
    project_v1_turn,
    record_endpoint,
    reduce as reduce_observation,
    sync_compat_fields,
    tick as tick_state,
    turn_config_from_dict,
    upgrade_state_v1_to_v2,
    worker_turn_config_from_dict,
)

SOFT_STALL_MS = 90_000          # legacy v1 constant kept for Phase 0 callers/tests
HARD_STALL_MS = 300_000         # legacy v1 constant kept for Phase 0 callers/tests
RECENT_MSG_LIMIT = 64           # bounded idempotency table size in pm-turn.json
UNHOOKED_UI_LIMIT = 24          # bounded list of UI-logged prompts awaiting hook/transcript consumption
UNHOOKED_TTL_MS = 15 * 60_000   # 15 min TTL on unconsumed UI prompt markers
OUTBOX_LIMIT = 40               # max queued user messages per project
TURN_CAUSE_LIMIT = 8            # recent turn_seq -> deliver-batch cause map
TRANSCRIPT_TAIL_BYTES = 65_536  # 64 KiB tail probe for live tool-call observability
JOURNAL_ROTATE_BYTES = 1 << 20  # 1 MiB rotation threshold for pm-turn-journal.jsonl (§3.3)

MSG_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_IMAGE_MARK_RE = re.compile(r"\[Image #\d+\]\s*")
_BG_SHELL_MSG_RE = re.compile(r"(?:(\d+)\s+)?shells?\s+still\s+running\b", re.I)
_FILES_HEADER_SET = frozenset({"Attachments:", "附件："})
_OCCUPATION_HINT_RE = re.compile(r"^(?:〔占用提示〕|\[Occupation hint\])[^\n]*(?:\n+|$)")


def _strip_occupation_hint(text: str) -> str:
    s = str(text or "")
    while True:
        nxt = _OCCUPATION_HINT_RE.sub("", s, count=1)
        if nxt == s:
            return s
        s = nxt

# In-process cache `(path_str, size, mtime_ns) -> dict` so repeated probes in one process skip unchanged tails.
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
    logged_clean = _strip_occupation_hint(logged_text)
    sent_clean = _strip_occupation_hint(sent_text)
    a, b = _squash(logged_clean), _squash(sent_clean)
    if not a or not b:
        return False
    if a == b:
        return True
    words_a, _ = _words_of_prompt(logged_clean)
    words_b, sent_files = _words_of_prompt(sent_clean)
    if sent_files and words_a == words_b:
        return True
    if _squash(_IMAGE_MARK_RE.sub("", logged_clean)) == _squash(_IMAGE_MARK_RE.sub("", sent_clean)):
        return True
    return False


def match_coalesced_prompt_prefix(
    raw_text: str,
    candidates: list[dict[str, Any]],
) -> tuple[list[int], str] | None:
    """Match `raw_text` against an ordered subsequence of `candidates` (`[{"msg_id", "text", ...}]`)."""
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


def probe_transcript_activity(path: Path | None, agent_kind: str = "", *, home_str: str = "") -> dict[str, Any]:
    """Read at most the trailing 64 KiB of a PM transcript (`claude`, `codex`, `agy`) to extract live progress."""
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
        return {"mtime_ms": mtime_ms, "size": size, "activity": None, "ended": False}
    chunk = raw[:nl]
    if start > 0:
        first_nl = chunk.find(b"\n")
        chunk = chunk[first_nl + 1:] if first_nl >= 0 else b""

    kind_low = (agent_kind or "").strip().lower()
    open_tools: dict[str, tuple[str, str]] = {}
    tool_steps = 0
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
        if rtype in ("USER_INPUT", "PLANNER_RESPONSE", "GENERIC", "ERROR_MESSAGE") or kind_low in ("agy", "antigravity"):
            if rtype == "USER_INPUT":
                open_tools.clear()
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
                        summary = summarize_tool_input(tname, targs, home_str)
                        tool_steps += 1
                        tid = str(tc.get("id") or tool_steps)
                        open_tools[tid] = (tname, summary)
                elif str(row.get("status") or "DONE") == "DONE" and str(row.get("content") or "").strip():
                    open_tools.clear()
                    ended = True
            elif rtype in ("GENERIC", "ERROR_MESSAGE"):
                open_tools.clear()
            continue

        payload = row.get("payload")
        if rtype in ("response_item", "event_msg") and isinstance(payload, Mapping):
            ptype = str(payload.get("type") or "")
            if ptype in ("user_message", "turn_started"):
                open_tools.clear()
                ended = False
            elif ptype in ("function_call", "custom_tool_call", "local_shell_call"):
                ended = False
                tname = str(payload.get("name") or ("Bash" if ptype == "local_shell_call" else "tool"))
                raw_args = payload.get("arguments") or payload.get("action") or payload.get("input") or {}
                if isinstance(raw_args, str):
                    with contextlib.suppress(ValueError):
                        raw_args = json.loads(raw_args)
                summary = summarize_tool_input(tname, raw_args, home_str)
                tool_steps += 1
                cid = str(payload.get("call_id") or tool_steps)
                open_tools[cid] = (tname, summary)
            elif ptype in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                cid = str(payload.get("call_id") or "")
                if cid:
                    open_tools.pop(cid, None)
                else:
                    open_tools.clear()
            elif ptype in ("task_complete", "turn_complete"):
                open_tools.clear()
                ended = True
            continue

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
                        summary = summarize_tool_input(tname, blk.get("input"), home_str)
                        tool_steps += 1
                        tu_id = str(blk.get("id") or tool_steps)
                        open_tools[tu_id] = (tname, summary)
            if saw_tool_use:
                ended = False
            elif stop_reason == "end_turn":
                open_tools.clear()
                ended = True

    activity: dict[str, Any] | None = None
    if not ended:
        if open_tools:
            tname, summary = next(reversed(open_tools.values()))
            activity = {"kind": "tool", "tool": tname, "summary": summary, "steps": tool_steps}
        elif tool_steps > 0:
            activity = {"kind": "thinking", "tool": "", "summary": "", "steps": tool_steps}

    result = {"mtime_ms": mtime_ms, "size": size, "activity": activity, "ended": ended}
    if len(_PROBE_CACHE) >= 128:
        _PROBE_CACHE.pop(next(iter(_PROBE_CACHE)), None)
    _PROBE_CACHE[key] = (size, mtime_ns, result)
    return dict(result)


def _read_jsonl_lines_from(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    try:
        size = path.stat().st_size
    except OSError:
        return [], 0
    if size == 0:
        return [], 0
    if offset < 0 or offset > size:
        offset = 0
    if size == offset:
        return [], offset
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            raw = f.read()
    except OSError:
        return [], offset
    nl = raw.rfind(b"\n")
    if nl < 0:
        return [], offset
    complete = raw[:nl + 1]
    new_offset = offset + len(complete)
    rows: list[dict[str, Any]] = []
    for line in complete.split(b"\n")[:-1]:
        if not line.strip():
            continue
        try:
            obj = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows, new_offset


def _last_journal_seq(path: Path) -> int:
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size <= 0:
        return 0
    start = max(0, size - 32_768)
    try:
        with open(path, "rb") as f:
            f.seek(start)
            raw = f.read(32_768)
    except OSError:
        return 0
    for line in reversed(raw.splitlines()):
        if not line.strip():
            continue
        try:
            obj = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(obj, Mapping) and isinstance(obj.get("seq"), int) and not isinstance(obj["seq"], bool):
            return int(obj["seq"])
    return 0


def stored_undelivered(summary: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The mailbox backlog as kept in `pm-turn.json`: only what changes when the mailbox does. `waiting_seconds`
    ticks every second; a reader derives it from `oldest_ms`, else each sync would rewrite the file."""
    if not isinstance(summary, Mapping):
        return None
    return {k: v for k, v in summary.items() if k != "waiting_seconds"}


class TurnTracker:
    """Storage & facade for per-project PM turn snapshots (`pm-turn.json` v2) and observation journal."""

    def __init__(self, ctx: Context, repo_or_slug: str | Path, *, slug: str | None = None) -> None:
        self.ctx = ctx
        raw = str(repo_or_slug or "").strip()
        if slug and valid_slug(slug):
            self.slug = slug
            reg = ctx.store.registration(slug) or {}
            self.repo = str(reg.get("repo") or (raw if raw != slug else "") or "")
        elif valid_slug(raw) and (ctx.store.registration(raw) is not None or ctx.home.project(raw).root.is_dir()):
            self.slug = raw
            reg = ctx.store.registration(raw) or {}
            self.repo = str(reg.get("repo") or "")
        else:
            self.repo = raw
            self.slug = (ctx.store.folder_project_slug(raw) or project_slug(raw)) if raw else "project"
        self.files = ctx.home.project(self.slug)
        self.lock_path = self.files.pm_turn_lock
        self.pm_mailbox = MailboxStore(self.files.pm_mailbox, clock=ctx.clock, typist_dir=ctx.home.typists)
        self._logged_stall_seqs: set[int] = set()

    def _legacy_inbox_path(self) -> Path | None:
        reg = self.ctx.store.registration(self.slug)
        name = str((reg or {}).get("name") or f"pm-{self.slug}")
        cand = self.ctx.home.root / "inbox" / f"{name}.jsonl"
        return cand if cand.is_file() else None

    def ensure_mailbox_migrated(self) -> int:
        if self.pm_mailbox.state_path.is_file():
            try:
                snap = json.loads(self.pm_mailbox.state_path.read_text(encoding="utf-8"))
                if isinstance(snap, dict) and snap.get("legacy_migrated"):
                    return 0
            except (OSError, ValueError):
                pass
        return self.pm_mailbox.migrate_legacy_pm_state(
            self.files.pm_turn,
            self._legacy_inbox_path(),
            project=self.slug,
            now_ms=self._now_ms(),
        )

    def sync_mailbox_projection(self, now_ms: int | None = None) -> None:
        ts = self._now_ms() if now_ms is None else int(now_ms)
        inbox = self.pm_mailbox.inbox_projection(limit=32)
        undelivered = stored_undelivered(self.pm_mailbox.undelivered_summary(now_ms=ts))

        def _sync(st: dict[str, Any]) -> dict[str, Any] | None:
            if st.get("inbox") == inbox and st.get("undelivered") == undelivered:
                return None
            st["inbox"] = inbox
            st["undelivered"] = undelivered
            return st

        self._mutate(_sync)

    def receipts_projection(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """1-version compat receipts projection from `pm_mailbox`, merging read-only fallback from `receipts.json`."""
        primary = self.pm_mailbox.receipts_projection(limit=limit) if self.files.pm_mailbox.is_dir() else []
        legacy = read_receipts(self.files.receipts)[-max(1, int(limit)):]
        return merge_receipts_compat(primary, legacy, limit=limit)

    def _now_ms(self) -> int:
        return int(self.ctx.clock.time() * 1000)

    def turn_config(self) -> TurnConfig:
        raw_cfg = None
        if self.ctx.config is not None:
            reader = getattr(self.ctx.config, "read", None)
            if callable(reader):
                raw_cfg = reader()
            if not isinstance(raw_cfg, Mapping):
                raw_cfg = getattr(self.ctx.config, "data", None)
        if isinstance(raw_cfg, Mapping):
            return turn_config_from_dict(raw_cfg)
        return TurnConfig()

    def _default_state(self) -> dict[str, Any]:
        return sync_compat_fields(default_state_v2(self.turn_config()))

    def _read_raw_unlocked(self) -> tuple[dict[str, Any], bool]:
        """Read `pm-turn.json` and normalize/upgrade to v2 in memory, returning `(state, needs_write)`."""
        path = self.files.pm_turn
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._default_state(), False
        if not isinstance(raw, dict):
            return self._default_state(), False
        needs_upgrade = raw.get("version") != 2
        return upgrade_state_v1_to_v2(raw, cfg=self.turn_config()), needs_upgrade

    def _bound_collections(self, nxt: dict[str, Any], now_ms: int) -> dict[str, Any]:
        if isinstance(nxt.get("recent_msg_ids"), dict) and len(nxt["recent_msg_ids"]) > RECENT_MSG_LIMIT:
            nxt["recent_msg_ids"] = dict(list(nxt["recent_msg_ids"].items())[-RECENT_MSG_LIMIT:])
        if isinstance(nxt.get("unhooked_ui_prompts"), list):
            cutoff = now_ms - UNHOOKED_TTL_MS
            nxt["unhooked_ui_prompts"] = [
                p for p in nxt["unhooked_ui_prompts"]
                if isinstance(p, dict) and int(p.get("at_ms") or 0) >= cutoff
            ][-UNHOOKED_UI_LIMIT:]
        if isinstance(nxt.get("outbox"), list) and len(nxt["outbox"]) > OUTBOX_LIMIT:
            nxt["outbox"] = nxt["outbox"][-OUTBOX_LIMIT:]
        if isinstance(nxt.get("turn_causes"), dict) and len(nxt["turn_causes"]) > TURN_CAUSE_LIMIT:
            nxt["turn_causes"] = dict(list(nxt["turn_causes"].items())[-TURN_CAUSE_LIMIT:])
        if isinstance(nxt.get("session_turns"), dict) and len(nxt["session_turns"]) > TURN_CAUSE_LIMIT:
            nxt["session_turns"] = dict(list(nxt["session_turns"].items())[-TURN_CAUSE_LIMIT:])
        return nxt

    def _write_state_unlocked(self, st: dict[str, Any], now_ms: int) -> dict[str, Any]:
        st["updated_ms"] = max(int(st.get("updated_ms") or 0), now_ms)
        self._bound_collections(st, now_ms)
        sync_compat_fields(st)
        payload = (json.dumps(st, ensure_ascii=False) + "\n").encode("utf-8")
        write_atomic(self.files.pm_turn, payload, replace_fn=replace_task_file)
        return st

    def _append_summary_if_new_unlocked(self, st: dict[str, Any], now_ms: int) -> bool:
        """Write one `turn_summary` line into `pm-turn-journal.jsonl` whenever a new turn completes (§3.8 O-a)."""
        lt = st.get("last_turn")
        if not isinstance(lt, dict):
            return False
        lt_seq = int(lt.get("seq") or 0)
        if lt_seq <= 0 or lt_seq <= int(st.get("last_summary_seq") or 0):
            return False
        self.files.ensure()
        jpath = self.files.pm_turn_journal
        last_jseq = max(int(st.get("journal_seq") or 0), _last_journal_seq(jpath))
        next_seq = last_jseq + 1
        split = lt.get("split") if isinstance(lt.get("split"), Mapping) else {}
        budget = lt.get("budget") if isinstance(lt.get("budget"), Mapping) else {}
        total_ms = int(lt.get("total_ms") if lt.get("total_ms") is not None else (lt.get("duration_ms") or 0))
        record: dict[str, Any] = {
            "seq": next_seq,
            "t": int(lt.get("ended_ms") or now_ms),
            "src": "supervisor",
            "kind": "turn_summary",
            "turn_id": str(lt.get("id") or ""),
            "turn_seq": lt_seq,
            "cause": str(lt.get("cause") or ""),
            "outcome": str(lt.get("outcome") or ""),
            "total_ms": total_ms,
            "generate_ms": int(split.get("generate_ms") or 0),
            "tool_ms": int(split.get("tool_ms") or 0),
            "steps": int(lt.get("steps") or 0),
            "longest_step": dict(lt.get("longest_step") or {}) if isinstance(lt.get("longest_step"), Mapping) else {},
            "action_ms": dict(lt.get("action_ms") or {}) if isinstance(lt.get("action_ms"), Mapping) else {},
            "over_soft": bool(budget.get("over_soft")),
            "over_hard": bool(budget.get("over_hard")),
            "budget_soft_ms": int(budget.get("soft_ms") or 0),
            "budget_hard_ms": int(budget.get("hard_ms") or 0),
        }
        line_bytes = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        with open(jpath, "ab") as f:
            f.write(line_bytes)
        st["journal_seq"] = next_seq
        try:
            st["journal_offset"] = jpath.stat().st_size
        except OSError:
            st["journal_offset"] = int(st.get("journal_offset") or 0) + len(line_bytes)
        st["last_summary_seq"] = lt_seq
        if self._settle_closed_turn(lt, now_ms):
            self._refresh_mailbox_projection_in_state(st, now_ms)
        return True

    def _refresh_mailbox_projection_in_state(self, st: dict[str, Any], now_ms: int) -> None:
        if not self.files.pm_mailbox.is_dir():
            return
        with contextlib.suppress(Exception):
            st["inbox"] = self.pm_mailbox.inbox_projection(limit=32)
            st["undelivered"] = stored_undelivered(self.pm_mailbox.undelivered_summary(now_ms=now_ms))

    def _lacks_prompt_receipt(self, agent_kind: str, hook_confirmed: bool) -> bool:
        eff_kind = str(agent_kind or "").strip().lower()
        if not eff_kind:
            reg = self.ctx.store.registration(self.slug) or {}
            eff_kind = str(reg.get("agent") or "").strip().lower()
        return (not adapter_for(eff_kind).consumes_prompts) or (not bool(hook_confirmed))

    def _mark_typed_turn_opened(self, turn: Mapping[str, Any] | None, agent_kind: str, now_ms: int) -> bool:
        if not isinstance(turn, Mapping) or not self.files.pm_mailbox.is_dir():
            return False
        phase = str(turn.get("phase") or "idle")
        if phase not in ("generating", "tool", "waiting_upstream") or bool(turn.get("provisional")):
            return False
        if not self._lacks_prompt_receipt(agent_kind, bool(turn.get("hook_confirmed"))):
            return False
        seq = int(turn.get("seq") or 0)
        if seq <= 0:
            return False
        started_ms = int(turn.get("started_ms") or 0)
        opened_ms = max(started_ms, int(turn.get("opened_ms") or started_ms))
        try:
            changed = self.pm_mailbox.mark_typed_turn_opened(
                seq,
                turn_started_ms=started_ms,
                turn_opened_ms=opened_ms,
                now_ms=now_ms,
            )
            return bool(changed)
        except Exception:  # noqa: BLE001
            return False

    def settle_turn_if_closed(self, turn_seq: int | None) -> None:
        """Settle what turn `turn_seq` read when that turn has already closed: its summary settled the mailbox before
        a Stop hook caught up with the words it took in mid-turn (`record_taken_in`), or the supervisor closed it on
        hc idle before the Stop hook came. No-op while the turn is still open (its own closure settles it)."""
        seq = int(turn_seq or 0)
        if seq <= 0 or not self.files.pm_mailbox.is_dir():
            return
        st = self.read()
        if int(st.get("last_summary_seq") or 0) < seq:
            return
        lt = st.get("last_turn") if isinstance(st.get("last_turn"), Mapping) else {}
        now_ms = self._now_ms()
        if int(lt.get("seq") or 0) == seq:
            if self._settle_closed_turn(lt, now_ms):
                self.sync_mailbox_projection(now_ms)
        else:  # a newer turn already closed too: this one's outcome is gone, settle without a guess
            if self._settle_closed_turn({"seq": seq, "id": "", "outcome": "closed", "ended_ms": now_ms}, now_ms):
                self.sync_mailbox_projection(now_ms)

    def _settle_closed_turn(self, lt: Mapping[str, Any], now_ms: int) -> bool:
        """G5 for the turn that just closed, on every closing path (Stop hook, agy transcript, hc idle, Esc): its
        consumed messages become answered (a batch whose turn did not reply goes back for another attempt), and on
        clean live-session closures (`replied`, `silent`, or Esc `interrupted`, not `errored` or crash/reset `aborted`)
        any pre-turn `typed` items on unhooked/pi sessions also settle as `answered` (B4)."""
        if not self.files.pm_mailbox.is_dir():
            return False
        try:
            seq = int(lt.get("seq") or 0)
            started_ms = int(lt.get("started_ms") or 0)
            opened_ms = max(started_ms, int(lt.get("opened_ms") or started_ms))
            fallback_typed = (
                bool(lt.get("confirmed"))
                and not bool(lt.get("aborted"))
                and self._lacks_prompt_receipt(
                    str(lt.get("agent_kind") or ""),
                    bool(lt.get("hook_confirmed")),
                )
            )
            if fallback_typed and seq > 0 and (started_ms > 0 or opened_ms > 0):
                self.pm_mailbox.mark_typed_turn_opened(
                    seq,
                    turn_started_ms=started_ms,
                    turn_opened_ms=opened_ms,
                    now_ms=now_ms,
                )
            changed = self.pm_mailbox.settle_closed_turn(
                seq,
                str(lt.get("id") or ""),
                str(lt.get("outcome") or "silent"),
                ended_ms=int(lt.get("ended_ms") or now_ms),
                turn_started_ms=started_ms if fallback_typed else 0,
                turn_opened_ms=opened_ms if fallback_typed else 0,
                settle_typed_on_reply=fallback_typed,
                now_ms=now_ms,
            )
            return bool(changed)
        except Exception:  # noqa: BLE001 - settling is retried by the next closure's catch-all; never fail the turn
            return False

    def _catch_up_journal_unlocked(self, st: dict[str, Any], cfg: TurnConfig) -> tuple[dict[str, Any], bool]:
        jpath = self.files.pm_turn_journal
        if not jpath.is_file():
            return st, False
        offset = int(st.get("journal_offset") or 0)
        rows, new_offset = _read_jsonl_lines_from(jpath, offset)
        if not rows and new_offset == offset:
            return st, False
        prev_lt = st.get("last_turn") if isinstance(st.get("last_turn"), Mapping) else {}
        prev_lt_seq = int(prev_lt.get("seq") or 0)
        prev_lt_outcome = str(prev_lt.get("outcome") or "")
        cur = st
        now_ms = self._now_ms()
        for row in rows:
            cur = reduce_observation(cur, row, cfg)
            cur_kind = str(((cur.get("session") or {}) if isinstance(cur.get("session"), Mapping) else {}).get("agent_kind") or cur.get("agent_kind") or "")
            self._mark_typed_turn_opened(cur.get("turn"), cur_kind, now_ms)
        cur["journal_offset"] = new_offset
        summary_added = self._append_summary_if_new_unlocked(cur, now_ms)
        cur_lt = cur.get("last_turn") if isinstance(cur.get("last_turn"), Mapping) else {}
        cur_lt_seq = int(cur_lt.get("seq") or 0)
        cur_lt_outcome = str(cur_lt.get("outcome") or "")
        if not summary_added and cur_lt_seq > 0 and cur_lt_seq == prev_lt_seq and cur_lt_outcome != prev_lt_outcome:
            if self._settle_closed_turn(cur_lt, now_ms):
                self._refresh_mailbox_projection_in_state(cur, now_ms)
        return cur, True

    def read(self) -> dict[str, Any]:
        """Read `pm-turn.json` (auto-upgrading v1->v2 and catching up unreduced journal lines if present)."""
        st, _ = self._read_raw_unlocked()
        jpath = self.files.pm_turn_journal
        if jpath.is_file():
            try:
                jsize = jpath.stat().st_size
            except OSError:
                jsize = 0
            if jsize != int(st.get("journal_offset") or 0):
                st, _ = self.sync_journal(tick_now=False)
        return st

    def _mutate(self, fn: Callable[[dict[str, Any]], dict[str, Any] | None], *, timeout: float = 5.0) -> dict[str, Any]:
        self.files.ensure()
        cfg = self.turn_config()
        with file_lock(self.lock_path, timeout=timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            cur, upgraded = self._read_raw_unlocked()
            cur, caught_up = self._catch_up_journal_unlocked(cur, cfg)
            nxt = fn(cur)
            if nxt is None:
                if upgraded or caught_up:
                    return self._write_state_unlocked(cur, self._now_ms())
                return cur
            return self._write_state_unlocked(nxt, self._now_ms())

    def append_observation(
        self,
        obs: Mapping[str, Any],
        *,
        reduce_now: bool = True,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Append one observation line with a strictly monotonic `seq` to `pm-turn-journal.jsonl`."""
        self.files.ensure()
        cfg = self.turn_config()
        now_ms = int(obs.get("t") or self._now_ms())
        with file_lock(self.lock_path, timeout=timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            cur, upgraded = self._read_raw_unlocked()
            cur, caught_up = self._catch_up_journal_unlocked(cur, cfg)

            jpath = self.files.pm_turn_journal
            last_seq = max(int(cur.get("journal_seq") or 0), _last_journal_seq(jpath))
            # Rotate journal at 1 MiB after draining all unread lines so no observation is lost (§3.3).
            if jpath.is_file():
                try:
                    jsize = jpath.stat().st_size
                except OSError:
                    jsize = 0
                if jsize >= JOURNAL_ROTATE_BYTES:
                    replace_task_file(jpath, self.files.pm_turn_journal_prev)
                    cur["journal_offset"] = 0
                    caught_up = True

            next_seq = last_seq + 1
            record: dict[str, Any] = {
                "seq": next_seq,
                "t": now_ms,
                "src": str(obs.get("src") or "pm"),
            }
            for k, v in obs.items():
                if k not in ("seq", "t", "src"):
                    record[k] = v

            line_bytes = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
            with open(jpath, "ab") as f:
                f.write(line_bytes)

            if reduce_now:
                cur, _ = self._catch_up_journal_unlocked(cur, cfg)
                self._write_state_unlocked(cur, now_ms)
            elif upgraded or caught_up:
                self._write_state_unlocked(cur, now_ms)
            return record

    def sync_journal(
        self,
        *,
        tick_now: bool = True,
        cfg: TurnConfig | None = None,
        timeout: float = 5.0,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Catch up any unreduced lines in `pm-turn-journal.jsonl` and optionally advance `tick()`."""
        c = cfg or self.turn_config()
        if not self.files.pm_turn.is_file() and not self.files.pm_turn_journal.is_file():
            return self._default_state(), []
        now_ms = self._now_ms()
        with file_lock(self.lock_path, timeout=timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            cur, upgraded = self._read_raw_unlocked()
            cur, caught_up = self._catch_up_journal_unlocked(cur, c)
            due_actions: list[dict[str, Any]] = []
            tick_changed = False
            if tick_now:
                prev_health = (cur.get("turn") or {}).get("health")
                prev_reason = (cur.get("turn") or {}).get("health_reason")
                prev_phase = (cur.get("turn") or {}).get("phase")
                prev_over = ((cur.get("turn") or {}).get("budget") or {}).get("over")
                prev_inc = cur.get("incident")
                cur, due_actions = tick_state(cur, now_ms, c)
                t_after = cur.get("turn") or {}
                tick_changed = (
                    t_after.get("health") != prev_health
                    or t_after.get("health_reason") != prev_reason
                    or t_after.get("phase") != prev_phase
                    or (t_after.get("budget") or {}).get("over") != prev_over
                    or cur.get("incident") != prev_inc
                )
                if self._append_summary_if_new_unlocked(cur, now_ms):
                    tick_changed = True
            if upgraded or caught_up or tick_changed:
                cur = self._write_state_unlocked(cur, now_ms)
            return cur, due_actions

    def consume_occupation_hint(self, *, now_ms: int | None = None, cooldown_ms: int = OCCUPATION_HINT_COOLDOWN_MS) -> dict[str, Any] | None:
        """Atomically pop a pending over-budget occupation hint if not rate-limited (§3.8 O-c)."""
        if not self.files.pm_turn.is_file() and not self.files.pm_turn_journal.is_file():
            return None
        ts = self._now_ms() if now_ms is None else int(now_ms)
        popped: dict[str, Any] | None = None

        def _take(st: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal popped
            pending = st.get("pending_occupation_hint")
            if not isinstance(pending, dict):
                return None
            last_ms = int(st.get("last_occupation_hint_ms") or 0)
            st["pending_occupation_hint"] = None
            if last_ms > 0 and (ts - last_ms) < cooldown_ms:
                return st
            st["last_occupation_hint_ms"] = ts
            popped = dict(pending)
            return st

        self._mutate(_take)
        return popped

    def read_journal_entries(
        self,
        *,
        since_ms: int | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Read journal entries across rotated `.1.jsonl` + active `.jsonl`, filtered by `since_ms`."""
        entries: list[dict[str, Any]] = []
        seen_seq: set[int] = set()
        for path in (self.files.pm_turn_journal_prev, self.files.pm_turn_journal):
            rows, _ = _read_jsonl_lines_from(path, 0)
            for row in rows:
                seq = row.get("seq")
                if isinstance(seq, int) and not isinstance(seq, bool):
                    if seq in seen_seq:
                        continue
                    seen_seq.add(seq)
                if since_ms is not None:
                    t_val = row.get("t")
                    if isinstance(t_val, (int, float)) and not isinstance(t_val, bool) and int(t_val) < since_ms:
                        continue
                entries.append(row)
        entries.sort(key=lambda r: (int(r.get("seq") or 0), int(r.get("t") or 0)))
        if limit > 0 and len(entries) > limit:
            entries = entries[-limit:]
        return entries

    def begin_turn(
        self,
        *,
        terminal: str = "",
        agent_kind: str = "",
        cause: str = "user",
        batch: list[int] | None = None,
        msg_ids: list[str] | tuple[str, ...] = (),
        terminal_turn: int = 0,
        session_id: str = "",
        from_hook: bool = False,
        fg_pid: int | None = None,
    ) -> int:
        """Emit a turn-start observation (`hook_prompt` or `send_submitted`) and return `turn.seq`."""
        clean_term = terminal[3:] if terminal.startswith("hc:") else terminal
        obs: dict[str, Any] = {
            "src": "hook" if from_hook else "pm",
            "kind": "hook_prompt" if from_hook else "send_submitted",
            "terminal": clean_term,
            "agent_kind": str(agent_kind or ""),
            "cause": str(cause or "user"),
            "msg_ids": [str(m) for m in msg_ids if m],
            "hc_turn": int(terminal_turn or 0),
            "session_id": str(session_id or ""),
        }
        if fg_pid is not None:
            obs["fg_pid"] = int(fg_pid)
        if batch:
            obs["batch"] = list(batch)
        if not from_hook:
            obs["started"] = True
        self.append_observation(obs, reduce_now=True)
        st = self.read()
        tseq = max(1, int(st.get("turn_seq") or 0))
        # What a hook read for this turn (consumed, `PENDING_TURN`) now belongs to it, whichever agent or path
        # started it (Claude/Codex hooks, the agy transcript, a typed batch), so its closure settles it (G5).
        try:
            self.bind_turn_to_consumed(f"seq:{tseq}", turn_seq=tseq)
        except Exception:  # noqa: BLE001 - a mailbox hiccup never fails the turn record
            pass
        return tseq

    def note_activity(
        self,
        *,
        kind: str = "tool",
        tool: str = "",
        summary: str = "",
        terminal_working: bool = False,
        status_ms: int = 0,
        preamble: str = "",
        src: str = "watcher",
    ) -> None:
        """Emit a step-level activity observation into the journal."""
        now_ms = self._now_ms()
        if terminal_working:
            cur = self.read()
            if cur.get("phase") == "idle":
                self.append_observation(
                    {
                        "src": src,
                        "kind": "hc_state",
                        "state": "live",
                        "status": "working",
                        "status_ms": int(status_ms or now_ms),
                        "reported": True,
                        "t": now_ms,
                    },
                    reduce_now=True,
                )
        is_tool = kind == "tool" and bool(str(tool or "").strip() or str(summary or "").strip())
        if is_tool:
            obs: dict[str, Any] = {
                "src": src,
                "kind": "step_tool_start",
                "tool": str(tool or ""),
                "summary": str(summary or "").strip()[:80],
                "t": now_ms,
            }
            if preamble:
                obs["preamble"] = str(preamble).strip()[:120]
        else:
            obs = {"src": src, "kind": "step_tool_end", "t": now_ms}
        self.append_observation(obs, reduce_now=True)

    def end_turn(self, *, expected_seq: int | None = None, has_reply: bool | None = None) -> dict[str, Any]:
        """Close the active turn (unless a newer `turn_seq` already started) and return any `after`/`batch` cause."""
        if not self.files.pm_turn.is_file() and not self.files.pm_turn_journal.is_file():
            return {}
        cause_out: dict[str, Any] = {}

        def _pop_cause(st: dict[str, Any]) -> dict[str, Any]:
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
            return st

        self._mutate(_pop_cause)
        obs: dict[str, Any] = {"src": "hook", "kind": "hook_stop"}
        if expected_seq is not None:
            obs["expected_seq"] = int(expected_seq)
        if has_reply is not None:
            obs["has_reply"] = bool(has_reply)
        self.append_observation(obs, reduce_now=True)
        return cause_out

    def turn_state(self, term: str) -> tuple[str, int]:
        """Return `("stopped"|"working"|"", turn_seq)` for `term` from `pm-turn.json`."""
        if not self.files.pm_turn.is_file() and not self.files.pm_turn_journal.is_file():
            return "", 0
        st = self.read()
        clean_term = term[3:] if term.startswith("hc:") else term
        if "/" in clean_term:
            clean_term = clean_term.rsplit("/", 1)[-1]
        sess_term = str((st.get("session") or {}).get("terminal") or st.get("terminal") or "")
        if "/" in sess_term:
            sess_term = sess_term.rsplit("/", 1)[-1]
        if sess_term and clean_term and sess_term != clean_term:
            return "", 0
        seq = int(st.get("turn_seq") or 0)
        if st.get("inflight"):
            return "working", seq
        if seq <= 0:
            return "", 0
        if st.get("phase") == "idle":
            return "stopped", seq
        if st.get("phase") in ("working", "stalled"):
            return "working", seq
        return "", seq

    def is_turn_stopped(self, term: str) -> bool:
        """True when `pm-turn.json` has explicitly observed at least one completed turn for `term` and is now `idle`."""
        return self.turn_state(term)[0] == "stopped"

    def consume_ui_prompt(self, raw_text: str, *, turn_id: str = "") -> tuple[bool, list[str], str]:
        """Deduplicate a hook/transcript user prompt against prompts already logged by `pm.py project send`."""
        text = str(raw_text or "").strip()
        if not text:
            return False, [], text

        fully_consumed = False
        matched_ids: list[str] = []
        remainder_out = text
        now_ms = self._now_ms()

        if self.files.pm_turn.is_file():
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

        env_hit = extract_env_id(text)
        id_set = set(matched_ids)
        norm_in = _squash(text)
        if self.files.pm_mailbox.is_dir():
            # Only input that may be on the terminal: `typed`, or `accepted` with a send `intent` (an async
            # `hc send` still in flight, or one that came back `timeout_uncertain` and is not reconciled yet).
            # An `accepted` item with no intent was never sent and must never be consumed (it would be lost).
            typed_items = [
                item for item in self.pm_mailbox.active_items(("typed", "accepted"))
                if item.envelope.kind == "chat.user" and (item.state == "typed" or item.intent is not None)
            ]
            direct_hits: list[tuple[Any, str]] = []
            for item in typed_items:
                body = item.envelope.body if isinstance(item.envelope.body, Mapping) else {}
                mid = str(body.get("msg_id") or "")
                raw_btxt = str(body.get("text") or "")
                btxt = _squash(raw_btxt)
                if (
                    (env_hit and item.envelope.env_id == env_hit)
                    or (mid and mid in id_set)
                    or (btxt and (btxt == norm_in or same_user_prompt(text, raw_btxt)))
                ):
                    direct_hits.append((item, raw_btxt))

            if direct_hits:
                for item, raw_btxt in direct_hits:
                    body = item.envelope.body if isinstance(item.envelope.body, Mapping) else {}
                    mid = str(body.get("msg_id") or "")
                    self.pm_mailbox.transition(
                        item.envelope.env_id,
                        "consumed",
                        now_ms=now_ms,
                        turn_id=turn_id or PENDING_TURN,
                        clear_intent=True,
                    )
                    if mid and mid not in id_set:
                        matched_ids.append(mid)
                        id_set.add(mid)
                    if _squash(raw_btxt) == norm_in or same_user_prompt(text, raw_btxt):
                        fully_consumed = True
                        remainder_out = ""
            else:
                typed_pool = [
                    {
                        "env_id": it.envelope.env_id,
                        "msg_id": str((it.envelope.body or {}).get("msg_id") or ""),
                        "text": str((it.envelope.body or {}).get("text") or ""),
                    }
                    for it in typed_items
                ]
                chit = match_coalesced_prompt_prefix(text, typed_pool)
                if chit is not None:
                    indices, remainder = chit
                    for idx in indices:
                        entry = typed_pool[idx]
                        self.pm_mailbox.transition(
                            entry["env_id"],
                            "consumed",
                            now_ms=now_ms,
                            turn_id=turn_id or PENDING_TURN,
                            clear_intent=True,
                        )
                        mid = entry["msg_id"]
                        if mid and mid not in id_set:
                            matched_ids.append(mid)
                            id_set.add(mid)
                    fully_consumed = not bool(remainder)
                    remainder_out = remainder
        return fully_consumed, matched_ids, remainder_out

    def bind_turn_to_consumed(self, turn_id: str, *, turn_seq: int = 0) -> None:
        """Bind `turn_id` onto any recently `consumed` mailbox items lacking a `bound_turn_id`."""
        if not self.files.pm_mailbox.is_dir():
            return
        now_ms = self._now_ms()
        for item in self.pm_mailbox.active_items(("consumed",)):
            if item.bound_turn_id and item.bound_turn_id != PENDING_TURN:
                continue
            self.pm_mailbox.transition(
                item.envelope.env_id,
                "consumed",
                now_ms=now_ms,
                turn_id=turn_id,
                meta={**item.meta, **({"turn_seq": int(turn_seq)} if turn_seq > 0 else {})},
            )

    def send_user_message(
        self,
        *,
        msg_id: str,
        text: str,
        question: str = "",
        expected_target: str = "",
    ) -> dict[str, Any]:
        """G1 lock-and-enqueue a UI user message into `pm://<slug>` `MailboxStore` and return immediately."""
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
        ep = record_endpoint(reg)
        pane = str(reg.get("pane") or "")
        term = str((ep.hc_target if ep else "") or reg.get("terminal") or (pane[3:] if pane.startswith("hc:") else ""))
        if expected_target and not term:
            term = expected_target[3:] if expected_target.startswith("hc:") else expected_target
        if ep is None and term:
            ep = parse_legacy_endpoint(term, runtime_hint="hc")

        now_ms = self._now_ms()
        self.ensure_mailbox_migrated()

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
        elif live_state == "blocked":
            should_queue_reason = "blocked_prompt"
        elif live_state == "error":
            should_queue_reason = "pm is error"

        idem_key = f"ui:{self.slug}:{clean_id}"
        env = Envelope(
            env_id=new_env_id(now_ms),
            idempotency_key=idem_key,
            schema_version=1,
            created_ms=now_ms,
            kind="chat.user",
            sender=Principal.user(self.slug),
            recipient=LogicalAddress.pm(self.slug),
            project=self.slug,
            cause={"kind": "ui_composer", "msg_id": clean_id, "question": question},
            priority=P1_USER,
            body={"text": body, "msg_id": clean_id, "question": question},
            require_reply=True,
        )
        item, created = self.pm_mailbox.enqueue(
            env,
            initial_state="accepted",
            now_ms=now_ms,
            hold_reason=should_queue_reason,
            target_endpoint_uid=ep.uid if ep is not None else "",
            endpoint_epoch=int(ep.epoch or 1) if ep is not None else 1,
        )
        queued_count = len(self.pm_mailbox.active_items(("accepted",)))

        if not created:
            cur_st = self.read()
            recent_meta = (cur_st.get("recent_msg_ids") or {}).get(clean_id)
            meta_dict = dict(recent_meta) if isinstance(recent_meta, Mapping) else {}
            return {
                "ok": True,
                "status": "queued" if item.hold_reason else ("delivered" if item.state in ("typed", "consumed", "answered") else "accepted"),
                "state": item.state,
                "deduped": True,
                "env_id": item.envelope.env_id,
                "mailbox_seq": item.seq,
                "msg_id": clean_id,
                "reason": item.hold_reason or item.last_error,
                "queued_count": queued_count,
                **meta_dict,
                "server_now_ms": now_ms,
            }

        stamp = self.ctx.clock.now_sec()
        event_fields: dict[str, Any] = {
            "at": stamp,
            "at_ms": now_ms,
            "tz": local_tz_offset(self.ctx.clock.datetime_now()),
            "type": "user",
            "msg_id": clean_id,
            "env_id": item.envelope.env_id,
            "source": "ui",
            "text": body,
        }
        if question:
            event_fields["question"] = question
        offset = self.ctx.store.append_event(self.slug, event_fields)
        last_events = self.ctx.store.events(self.slug, limit=1).get("events") or []
        seq = valid_task_number(last_events[-1].get("seq")) if last_events else None
        if repo:
            # No receipt here: a receipt says the PM read it (its UserPromptSubmit hook / transcript writes it).
            # Written at accept, a message that never reached the terminal looked delivered in the project view.
            self.files.turn_cause.unlink(missing_ok=True)

        rec_meta = {"seq": seq or 1, "offset": offset, "at_ms": now_ms}
        inbox = self.pm_mailbox.inbox_projection(limit=32)
        undelivered = stored_undelivered(self.pm_mailbox.undelivered_summary(now_ms=now_ms))

        def _commit_enqueue(st: dict[str, Any]) -> dict[str, Any]:
            recent = dict(st.get("recent_msg_ids") or {})
            recent[clean_id] = rec_meta
            st["recent_msg_ids"] = recent
            st["inbox"] = inbox
            st["undelivered"] = undelivered
            return st

        self._mutate(_commit_enqueue)
        status_val = "queued" if should_queue_reason else "accepted"
        return {
            "ok": True,
            "status": status_val,
            "state": "accepted",
            "env_id": item.envelope.env_id,
            "mailbox_seq": item.seq,
            "msg_id": clean_id,
            **rec_meta,
            "reason": should_queue_reason,
            "queued_count": queued_count,
            "server_now_ms": now_ms,
        }

    def interrupt_pm(self) -> dict[str, Any]:
        """Send an interrupt (`SIGINT` via `LocalHcTransport.interrupt`) to the active PM terminal."""
        reg = self.ctx.store.registration(self.slug)
        if reg is None:
            raise NotFound(f"no project {self.slug}")
        ep = record_endpoint(reg)
        pane = str(reg.get("pane") or "")
        term = str((ep.hc_target if ep else "") or reg.get("terminal") or (pane[3:] if pane.startswith("hc:") else ""))
        if not term:
            raise Refused("PM has no desktop terminal to interrupt")
        target_ep = ep or parse_legacy_endpoint(term, runtime_hint="hc")
        if target_ep is None:
            raise Refused("PM has no desktop terminal to interrupt")
        res = LocalHcTransport(self.ctx).interrupt(target_ep, timeout_s=5.0)
        if res.status == "endpoint_gone":
            raise Refused(f"hc:{term} is offline")
        if res.status in ("partitioned", "rejected"):
            raise Refused(res.detail or f"could not interrupt hc:{term}")
        outcome = res.status or "unknown"
        now_ms = self._now_ms()
        self.append_observation(
            {
                "src": "ui",
                "kind": "interrupt_sent",
                "t": now_ms,
                "terminal": term,
                "outcome": outcome,
            },
            reduce_now=True,
        )
        return {
            "ok": True,
            "terminal": term,
            "outcome": outcome,
            "key_sent": res.key_sent,
            "interrupted_ms": now_ms,
            "server_now_ms": now_ms,
        }

    def log_stall_diagnostic(self, term: str, cur_seq: int, idle_ms: int, detail: str = "") -> None:
        """Append a diagnostic stall line to `pm-stall.log` (never `conversation.jsonl`)."""
        stamp = self.ctx.clock.now_sec()
        mins = max(1, int(idle_ms // 60_000))
        extra = f" detail={detail}" if detail else ""
        line = f"{stamp} [{self.slug}] hc:{term} turn_seq={cur_seq} idle_min={mins}{extra}\n"
        with contextlib.suppress(OSError):
            self.ctx.home.pm_stall_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ctx.home.pm_stall_log, "a", encoding="utf-8") as f:
                f.write(line)

    def drain_outbox_and_check_stall(self, term: str, info: Mapping[str, Any]) -> float | None:
        """Migrate legacy outbox entries into `pm_mailbox`, sync UI projection, and advance stall clock via `tick()`."""
        if not self.files.pm_turn.is_file() and not self.files.pm_turn_journal.is_file() and not self.repo and not self.files.pm_mailbox.is_dir():
            return None
        now_ms = self._now_ms()
        self.ensure_mailbox_migrated()
        self.sync_mailbox_projection(now_ms)
        st = self.read()
        cur_term_turn = int(info.get("turn") or 0) if isinstance(info, Mapping) else 0
        raw_status = info.get("status") if isinstance(info, Mapping) else None
        live_state = str(raw_status.get("state") or "") if isinstance(raw_status, Mapping) else str(raw_status or "")

        # Feed current hc status into journal if it changed since last observation, then tick.
        st_cur = st
        hc_ev = ((st_cur.get("turn") or {}).get("evidence") or {}).get("hc") or {}
        term_status_ms = int(info.get("status_ms") or 0) if isinstance(info, Mapping) else 0
        if (
            live_state
            and (
                str(hc_ev.get("state") or "") != live_state
                or int(hc_ev.get("status_ms") or 0) != term_status_ms
                or int(hc_ev.get("turn") or 0) != cur_term_turn
            )
            and (st_cur.get("phase") != "idle" or live_state != "working")
        ):
            self.append_observation(
                {
                    "src": "supervisor",
                    "kind": "hc_state",
                    "t": now_ms,
                    "state": str(info.get("state") or "live") if isinstance(info, Mapping) else "live",
                    "status": live_state,
                    "status_ms": term_status_ms,
                    "turn": cur_term_turn,
                    "reported": bool(raw_status),
                },
                reduce_now=True,
            )

        st_after, due_actions = self.sync_journal(tick_now=True)
        turn_v2 = st_after.get("turn") or {}
        cur_seq = int(turn_v2.get("seq") or 0)
        if turn_v2.get("health") == "stalled" and self.repo:
            if cur_seq > 0 and cur_seq not in self._logged_stall_seqs:
                idle_ms = max(0, now_ms - int(turn_v2.get("last_progress_ms") or turn_v2.get("started_ms") or now_ms))
                act_sum = str((turn_v2.get("activity") or {}).get("summary") or turn_v2.get("health_reason") or "").strip()
                self.log_stall_diagnostic(term, cur_seq, idle_ms, act_sum)
                self._logged_stall_seqs.add(cur_seq)
        elif str(turn_v2.get("phase") or "idle") != "idle":
            if any(a.get("kind") == "probe_screen" and a.get("interval_ms") == 1_000 for a in due_actions):
                return 1.0
            return 5.0
        if any(it.envelope.priority < 4 for it in self.pm_mailbox.pending_for_endpoint()):
            return 0.5
        return None

    def _resolve_pm_transcript(self, reg: Mapping[str, Any]) -> tuple[Path | None, str]:
        agent_kind = str(reg.get("agent") or "").strip().lower()
        adapter = adapter_for(agent_kind)
        tpath = adapter.transcript_path(
            reg,
            self.files,
            claude_projects=self.ctx.agents.claude_projects,
            codex_sessions=getattr(self.ctx, "codex_sessions", None),
        )
        if tpath is not None:
            return tpath, adapter.kind if adapter.kind != "other" else agent_kind
        # Fallback when `agent` is unset on registration: check `agent_session.path` directly.
        sess = reg.get("agent_session") if isinstance(reg.get("agent_session"), Mapping) else {}
        raw_p = str(sess.get("path") or sess.get("transcript") or "").strip()
        if raw_p and Path(raw_p).is_file():
            return Path(raw_p), str(sess.get("kind") or agent_kind or "claude")
        return None, agent_kind

    def live_snapshot(
        self,
        reg: Mapping[str, Any] | None,
        live_pm: Mapping[str, Any] | None = None,
        *,
        term_info: Mapping[str, Any] | None = None,
        supervised: bool = True,
    ) -> dict[str, Any]:
        """Compute a read-only v1-shaped live PM turn snapshot (compatibility wrapper over reducer + v1 projection)."""
        now_ms = self._now_ms()
        st = self.read() if (self.files.pm_turn.is_file() or self.files.pm_turn_journal.is_file()) else self._default_state()
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
            bg_cmds = self.ctx.procs.background_work(term_info)
            if bg_cmds:
                bg_shells = len(bg_cmds)

        if live_status in ("blocked", "error"):
            return {
                "phase": "blocked",
                "turn_seq": int(st.get("turn_seq") or 0),
                "bg_shells": bg_shells,
                "queued_count": outbox_len,
            }

        if live_status in ("idle", "done"):
            started_ms = int(st.get("started_ms") or 0)
            if st.get("phase") == "working" and started_ms > 0 and (now_ms - started_ms) < 2500:
                v1 = project_v1_turn(st, now_ms, supervised=supervised)
                v1["bg_shells"] = bg_shells
                return v1
            return {
                "phase": "idle",
                "turn_seq": int(st.get("turn_seq") or 0),
                "bg_shells": bg_shells,
                "queued_count": outbox_len,
            }

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

        # Reconcile with live transcript tail & term status_ms in memory, then project v1.
        tpath, detected_kind = self._resolve_pm_transcript(reg)
        probe = probe_transcript_activity(tpath, detected_kind)
        term_status_ms = int(term_info.get("status_ms") or 0) if isinstance(term_info, Mapping) else 0
        term_turn = int(term_info.get("turn") or 0) if isinstance(term_info, Mapping) else 0

        sim = upgrade_state_v1_to_v2(st, cfg=self.turn_config())
        if live_status == "working":
            sim = reduce_observation(
                sim,
                {
                    "kind": "hc_state",
                    "t": term_status_ms or now_ms,
                    "state": "live",
                    "status": "working",
                    "status_ms": term_status_ms,
                    "turn": term_turn,
                    "reported": True,
                },
                self.turn_config(),
            )
        if probe["ended"] and bg_shells > 0 and probe["mtime_ms"] >= int((sim.get("turn") or {}).get("started_ms") or 0):
            return {
                "phase": "idle",
                "turn_seq": int(sim.get("turn_seq") or 0),
                "bg_shells": bg_shells,
                "queued_count": outbox_len,
            }
        started_ms = int((sim.get("turn") or {}).get("started_ms") or 0)
        if probe["mtime_ms"] >= max(0, started_ms - 2000):
            raw_act = probe["activity"]
            if isinstance(raw_act, Mapping) and raw_act.get("kind") == "tool":
                sim = reduce_observation(
                    sim,
                    {
                        "kind": "step_tool_start",
                        "t": probe["mtime_ms"],
                        "tool": str(raw_act.get("tool") or ""),
                        "summary": str(raw_act.get("summary") or ""),
                    },
                    self.turn_config(),
                )
            elif isinstance(raw_act, Mapping):
                sim = reduce_observation(
                    sim,
                    {"kind": "step_tool_end", "t": probe["mtime_ms"]},
                    self.turn_config(),
                )
        sim, _ = tick_state(sim, now_ms, self.turn_config())
        v1 = project_v1_turn(sim, now_ms, supervised=supervised)
        v1["bg_shells"] = bg_shells
        return v1


class EndpointTurnStore:
    """Per-endpoint turn observation journal (`obs-journal.jsonl`) and snapshot (`turn.state.json`) for
    worker terminals and remote endpoints (§4.6, §7 of pm-message-routing.md). Layer 2."""

    def __init__(
        self,
        ctx: Context,
        endpoint: Endpoint | str,
        *,
        repo: str | Path | None = None,
    ) -> None:
        self.ctx = ctx
        if isinstance(endpoint, Endpoint):
            self.endpoint = endpoint
        else:
            parsed = parse_legacy_endpoint(str(endpoint or ""), runtime_hint="hc")
            self.endpoint = parsed if parsed is not None else Endpoint(runtime="hc", machine=None, terminal=str(endpoint or ""))
        self.repo = str(repo or "")
        safe_uid = safe_endpoint_uid(self.endpoint)
        if self.repo:
            self.endpoint_dir = ctx.home.project_for(self.repo).endpoint_mailbox(safe_uid)
        else:
            self.endpoint_dir = ctx.home.endpoint_mailbox(safe_uid)
        self.state_path = self.endpoint_dir / "turn.state.json"
        self.journal_path = self.endpoint_dir / "obs-journal.jsonl"
        self.journal_prev_path = self.endpoint_dir / "obs-journal.0001.jsonl"
        self.lock_path = self.endpoint_dir / "turn.lock"

    def _now_ms(self) -> int:
        return int(self.ctx.clock.time() * 1000)

    def turn_config(self) -> TurnConfig:
        raw_cfg = None
        if self.ctx.config is not None:
            reader = getattr(self.ctx.config, "read", None)
            if callable(reader):
                raw_cfg = reader()
            if not isinstance(raw_cfg, Mapping):
                raw_cfg = getattr(self.ctx.config, "data", None)
        if isinstance(raw_cfg, Mapping):
            return worker_turn_config_from_dict(raw_cfg)
        return worker_turn_config_from_dict(None)

    def _default_state(self) -> dict[str, Any]:
        st = sync_compat_fields(default_state_v2(self.turn_config()))
        st["session"] = self.endpoint.to_dict()
        return st

    def _read_raw_unlocked(self, cfg: TurnConfig) -> tuple[dict[str, Any], bool]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._default_state(), False
        if not isinstance(raw, dict):
            return self._default_state(), False
        needs_upgrade = raw.get("version") != 2
        st = upgrade_state_v1_to_v2(raw, cfg=cfg)
        sess = st.get("session")
        if not (isinstance(sess, Mapping) and sess.get("terminal")):
            st["session"] = self.endpoint.to_dict()
        return st, needs_upgrade

    def _write_state_unlocked(self, st: dict[str, Any], now_ms: int) -> dict[str, Any]:
        st["updated_ms"] = max(int(st.get("updated_ms") or 0), now_ms)
        sync_compat_fields(st)
        self.endpoint_dir.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(st, ensure_ascii=False) + "\n").encode("utf-8")
        write_atomic(self.state_path, payload, replace_fn=replace_task_file)
        return st

    def _catch_up_journal_unlocked(self, st: dict[str, Any], cfg: TurnConfig) -> tuple[dict[str, Any], bool]:
        if not self.journal_path.is_file():
            return st, False
        offset = int(st.get("journal_offset") or 0)
        rows, new_offset = _read_jsonl_lines_from(self.journal_path, offset)
        if not rows and new_offset == offset:
            return st, False
        cur = st
        for row in rows:
            cur = reduce_observation(cur, row, cfg)
        cur["journal_offset"] = new_offset
        return cur, True

    def read(self) -> dict[str, Any]:
        cfg = self.turn_config()
        st, _ = self._read_raw_unlocked(cfg)
        if self.journal_path.is_file():
            try:
                jsize = self.journal_path.stat().st_size
            except OSError:
                jsize = 0
            if jsize != int(st.get("journal_offset") or 0):
                st, _ = self.sync_journal(tick_now=False, cfg=cfg)
        return st

    def append_observation(
        self,
        obs: Mapping[str, Any],
        *,
        reduce_now: bool = False,
        cfg: TurnConfig | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        self.endpoint_dir.mkdir(parents=True, exist_ok=True)
        c = cfg or self.turn_config()
        now_ms = int(obs.get("t") or self._now_ms())
        with file_lock(self.lock_path, timeout=timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            cur, upgraded = self._read_raw_unlocked(c)
            cur, caught_up = self._catch_up_journal_unlocked(cur, c)
            last_seq = max(int(cur.get("journal_seq") or 0), _last_journal_seq(self.journal_path))
            if self.journal_path.is_file():
                try:
                    jsize = self.journal_path.stat().st_size
                except OSError:
                    jsize = 0
                if jsize >= JOURNAL_ROTATE_BYTES:
                    replace_task_file(self.journal_path, self.journal_prev_path)
                    cur["journal_offset"] = 0
                    caught_up = True
            next_seq = last_seq + 1
            record: dict[str, Any] = {
                "seq": next_seq,
                "t": now_ms,
                "src": str(obs.get("src") or "supervisor"),
            }
            for k, v in obs.items():
                if k not in ("seq", "t", "src"):
                    record[k] = v
            line_bytes = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
            with open(self.journal_path, "ab") as f:
                f.write(line_bytes)
            if reduce_now:
                cur, _ = self._catch_up_journal_unlocked(cur, c)
                self._write_state_unlocked(cur, now_ms)
            elif upgraded or caught_up:
                self._write_state_unlocked(cur, now_ms)
            return record

    def sync_journal(
        self,
        *,
        tick_now: bool = True,
        now_ms: int | None = None,
        cfg: TurnConfig | None = None,
        timeout: float = 5.0,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        c = cfg or self.turn_config()
        if not self.state_path.is_file() and not self.journal_path.is_file():
            return self._default_state(), []
        ts = self._now_ms() if now_ms is None else int(now_ms)
        self.endpoint_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(self.lock_path, timeout=timeout, lock_fn=lock_file, unlock_fn=unlock_file):
            cur, upgraded = self._read_raw_unlocked(c)
            cur, caught_up = self._catch_up_journal_unlocked(cur, c)
            due_actions: list[dict[str, Any]] = []
            tick_changed = False
            if tick_now:
                t_before = cur.get("turn") or {}
                prev_sig = (
                    t_before.get("health"),
                    t_before.get("health_reason"),
                    t_before.get("phase"),
                    (t_before.get("budget") or {}).get("over"),
                    cur.get("incident"),
                )
                cur, due_actions = tick_state(cur, ts, c)
                t_after = cur.get("turn") or {}
                after_sig = (
                    t_after.get("health"),
                    t_after.get("health_reason"),
                    t_after.get("phase"),
                    (t_after.get("budget") or {}).get("over"),
                    cur.get("incident"),
                )
                tick_changed = after_sig != prev_sig
            if upgraded or caught_up or tick_changed:
                cur = self._write_state_unlocked(cur, ts)
            return cur, due_actions

    def read_journal_entries(
        self,
        *,
        since_ms: int | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen_seq: set[int] = set()
        for path in (self.journal_prev_path, self.journal_path):
            rows, _ = _read_jsonl_lines_from(path, 0)
            for row in rows:
                seq = row.get("seq")
                if isinstance(seq, int) and not isinstance(seq, bool):
                    if seq in seen_seq:
                        continue
                    seen_seq.add(seq)
                if since_ms is not None:
                    t_val = row.get("t")
                    if isinstance(t_val, (int, float)) and not isinstance(t_val, bool) and int(t_val) < since_ms:
                        continue
                entries.append(row)
        entries.sort(key=lambda r: (int(r.get("seq") or 0), int(r.get("t") or 0)))
        if limit > 0 and len(entries) > limit:
            entries = entries[-limit:]
        return entries
