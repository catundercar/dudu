"""Incremental byte-offset SQLite rollup cache and 4-runtime transcript parsers. Layer 4.

Strictly read-only on agent transcript directories (`~/.claude`, `~/.gemini/antigravity-cli`,
`~/.codex`, `~/.pi`). Writes only to `<ledger_home>/cache/token-usage-v1.db`.
"""
from __future__ import annotations

from collections import defaultdict
import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse

from ..agents.sessions import HELPER_PROMPT, PM_PROMPT, PM_SESSION_MARK, REVIEW_PROMPT, claude_folder
from ..home import project_slug
from ..project.project import in_scope
from ..store import BLOCK_SIZE, LINE_MAX, file_lock

SCHEMA_VERSION = "4"
TAIL_SEEN_CAP = 512
HEAD_BYTES_META = 256 << 10

_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
_USER_REQUEST_OPEN_RE = re.compile(r"^\s*<USER_REQUEST>\s*", re.S)
_TRAILING_META_RE = re.compile(r"\n<(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)\b.*$", re.S)
_EXEC_HELPER_RE = re.compile(
    r"\[Execution Helper\b[^\]]*\]"
    r"|【执行 helper\b[^】]*】"
    r"|You are execution helper \S+ for \S+"
    r"|你是 \S+ 的执行 helper \S+",
    re.I,
)
_WORKER_BRIEF_RE = re.compile(
    r'(?:^|\n)(?:<hc from="[^"]+">\s*)?(?:#\s*(?:任务书|Task\s+brief)|\[Task:\s[^\]]+\])'
    r"|\bReporting \(task (?:#\d+\s+)?[^\s)]+"
    r"|汇报（任务 (?:#\d+\s+)?[^\s）]+",
    re.I,
)
_PM_OPENING_EXTRA_RE = re.compile(
    r"\[from pm\.py deliver\]"
    r"|You are the PM(?:\s*\(project manager\))?\s+of\s+(?:the\s+)?\S+\s+project"
    r"|你是\s+\S+\s+项目的\s*PM",
    re.I,
)
REPORT_HINT_RE = re.compile(
    r"(?:pm\.py\s+(?:update|log)\s+|Reporting \(task (?:#\d+\s+)?|汇报（任务 (?:#\d+\s+)?)([^\s`'\"()（）：:]+)"
)

DEFAULT_PRICING: list[tuple[str, dict[str, float]]] = [
    ("claude-fable", {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write_5m": 18.75, "cache_write_1h": 30.0}),
    ("claude-opus", {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write_5m": 6.25, "cache_write_1h": 10.0}),
    ("claude-sonnet", {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write_5m": 3.75, "cache_write_1h": 6.0}),
    ("claude-haiku", {"input": 0.80, "output": 4.0, "cache_read": 0.08, "cache_write_5m": 1.0, "cache_write_1h": 1.60}),
    ("flash", {"input": 0.30, "output": 2.50, "cache_read": 0.03, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
    ("gemini", {"input": 2.0, "output": 12.0, "cache_read": 0.20, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
    ("agy", {"input": 2.0, "output": 12.0, "cache_read": 0.20, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
    ("gpt-", {"input": 2.50, "output": 10.0, "cache_read": 0.25, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
    ("o3", {"input": 2.50, "output": 10.0, "cache_read": 0.25, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
    ("o4", {"input": 2.50, "output": 10.0, "cache_read": 0.25, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
    ("codex", {"input": 2.50, "output": 10.0, "cache_read": 0.25, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
    ("deepseek", {"input": 0.28, "output": 0.42, "cache_read": 0.028, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
    ("grok", {"input": 2.0, "output": 10.0, "cache_read": 0.50, "cache_write_5m": 0.0, "cache_write_1h": 0.0}),
]
FALLBACK_PRICING: dict[str, float] = {
    "input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write_5m": 3.75, "cache_write_1h": 6.0,
}


def nonneg_int(val: Any) -> int:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return 0
    return int(val) if val > 0 else 0


def nonneg_float(val: Any) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return 0.0
    return float(val) if val > 0.0 else 0.0


def parse_hour_epoch(ts: Any, fallback_epoch: int = 0) -> int:
    """Parse an ISO-8601 timestamp (including trailing Z on Python 3.9) or epoch into floor hour_epoch."""
    epoch = 0.0
    if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0:
        epoch = float(ts) / 1000.0 if ts > 1e12 else float(ts)
    elif isinstance(ts, str):
        raw = ts.strip()
        if raw:
            norm = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            # Python 3.9 handles up to 6 fractional digits; trim excess precision if present.
            norm = re.sub(r"\.(\d{6})\d+", r".\1", norm)
            try:
                dt = datetime.datetime.fromisoformat(norm)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.datetime.now().astimezone().tzinfo)
                epoch = dt.timestamp()
            except ValueError:
                epoch = 0.0
    if epoch <= 0.0:
        epoch = float(fallback_epoch) if fallback_epoch > 0 else 0.0
    if epoch <= 0.0:
        return 0
    return (int(epoch) // 3600) * 3600


def _norm_path(path: Any) -> str:
    if not isinstance(path, str) or not path.strip():
        return ""
    try:
        return str(Path(path).resolve())
    except OSError:
        return path.strip().rstrip("/") or "/"


def _uri_to_path(uri: Any) -> str:
    if not isinstance(uri, str) or not uri.strip():
        return ""
    s = uri.strip()
    if s.startswith("file://"):
        parsed = urlparse(s)
        return _norm_path(unquote(parsed.path))
    return _norm_path(s)


def _fast_in_norm_scopes(norm_candidate: str, norm_scopes: list[str]) -> bool:
    if not norm_candidate:
        return False
    for sc in norm_scopes:
        if not sc:
            continue
        if sc == "/":
            if norm_candidate.startswith("/"):
                return True
        elif norm_candidate == sc or norm_candidate.startswith(sc + "/"):
            return True
    return False


def _in_any_scope(candidate: str, scopes: Iterable[str]) -> bool:
    if not candidate:
        return False
    norm_cand = _norm_path(candidate)
    for sc in scopes:
        if not sc:
            continue
        norm_sc = _norm_path(sc)
        if not norm_sc:
            continue
        if norm_sc == "/":
            if norm_cand.startswith("/"):
                return True
        elif norm_cand == norm_sc or norm_cand.startswith(norm_sc + "/"):
            return True
    return False


def _extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                txt = item.get("text")
                if isinstance(txt, str):
                    parts.append(txt)
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(parts)
    return ""


def _extract_agy_user_text(raw: Any) -> str:
    text = str(raw or "")
    m = _USER_REQUEST_RE.search(text)
    if m:
        return m.group(1).strip()
    if _USER_REQUEST_OPEN_RE.match(text):
        cleaned = _USER_REQUEST_OPEN_RE.sub("", text, count=1)
        cleaned = _TRAILING_META_RE.sub("", cleaned)
        return cleaned.strip()
    return text.strip()


def _detect_opening_meta(text: str) -> tuple[str, str]:
    """Detect `(opening_role, opening_task_hint)` from decoded opening prompt text (before first model reply).

    Checks non-PM worker/helper/reviewer markers before PM markers so worker briefs mentioning PM concepts
    are never misclassified as PM sessions, and never extracts task hints from PM openings.
    """
    if not text:
        return "", ""
    role = ""
    if HELPER_PROMPT.search(text) or _EXEC_HELPER_RE.search(text):
        role = "helper"
    elif REVIEW_PROMPT.search(text):
        role = "reviewer"
    elif _WORKER_BRIEF_RE.search(text):
        role = "worker"
    elif PM_SESSION_MARK in text or PM_PROMPT.search(text) or _PM_OPENING_EXTRA_RE.search(text):
        role = "pm"

    if role == "pm":
        return "pm", ""

    hint = ""
    for m in REPORT_HINT_RE.finditer(text):
        cand = m.group(1).strip()
        if cand and not cand.startswith(("-", "<", "{", "[")):
            hint = cand
            break
    if not role and hint:
        role = "worker"
    return role, hint


def _push_seen(seen_list: list[str], seen_set: set[str], key: str) -> bool:
    """Return True if key is new and recorded; False if already seen."""
    if not key:
        return True
    if key in seen_set:
        return False
    seen_set.add(key)
    seen_list.append(key)
    if len(seen_list) > TAIL_SEEN_CAP:
        drop = seen_list.pop(0)
        seen_set.discard(drop)
    return True


def _add_delta(
    deltas: dict[tuple[int, str, int], list[Any]],
    hour_epoch: int,
    model: str,
    is_advisor: int,
    *,
    calls: int = 0,
    errors: int = 0,
    input_tok: int = 0,
    output_tok: int = 0,
    cache_read_tok: int = 0,
    cache_write_5m_tok: int = 0,
    cache_write_1h_tok: int = 0,
    explicit_usd: float = 0.0,
) -> None:
    key = (int(hour_epoch), str(model or "unknown"), 1 if is_advisor else 0)
    bucket = deltas.get(key)
    if bucket is None:
        bucket = [0, 0, 0, 0, 0, 0, 0, 0.0]
        deltas[key] = bucket
    bucket[0] += calls
    bucket[1] += errors
    bucket[2] += input_tok
    bucket[3] += output_tok
    bucket[4] += cache_read_tok
    bucket[5] += cache_write_5m_tok
    bucket[6] += cache_write_1h_tok
    bucket[7] += explicit_usd


def _claude_cache_write(usage: dict[str, Any]) -> tuple[int, int]:
    cc = usage.get("cache_creation")
    w5 = nonneg_int(cc.get("ephemeral_5m_input_tokens")) if isinstance(cc, dict) else 0
    w1 = nonneg_int(cc.get("ephemeral_1h_input_tokens")) if isinstance(cc, dict) else 0
    if w5 == 0 and w1 == 0:
        w5 = nonneg_int(usage.get("cache_creation_input_tokens"))
    return w5, w1


def parse_claude_line(
    row: dict[str, Any],
    *,
    line_end: int,
    seen_list: list[str],
    seen_set: set[str],
    deltas: dict[tuple[int, str, int], list[Any]],
    meta: dict[str, str],
    fallback_epoch: int = 0,
    global_seen: set[str] | None = None,
    new_global_seen: list[str] | None = None,
    claim_global_seen: Callable[[str], bool] | None = None,
) -> None:
    """Parse one Claude Code JSONL row into `deltas` and `meta`."""
    if not meta.get("cwd") and isinstance(row.get("cwd"), str) and row["cwd"]:
        meta["cwd"] = row["cwd"]
    if not meta.get("sid") and isinstance(row.get("sessionId"), str) and row["sessionId"]:
        meta["sid"] = row["sessionId"]

    rtype = row.get("type")
    hour_epoch = parse_hour_epoch(row.get("timestamp"), fallback_epoch=fallback_epoch)
    if rtype == "system" and row.get("subtype") in ("api_error", "error"):
        err_key = str(row.get("uuid") or row.get("requestId") or f"err:{line_end}")
        if _push_seen(seen_list, seen_set, f"cl_err:{err_key}"):
            _add_delta(deltas, hour_epoch, meta.get("last_model") or "claude", 0, errors=1)
        return

    if rtype != "assistant":
        return
    msg = row.get("message")
    if not isinstance(msg, dict):
        return
    usage = msg.get("usage")
    if not isinstance(usage, dict) or not usage:
        return
    base_model = str(msg.get("model") or meta.get("last_model") or "claude")
    if base_model and base_model != "<synthetic>":
        meta["last_model"] = base_model

    cross_id = msg.get("id") or row.get("requestId")
    cross_key = str(cross_id) if isinstance(cross_id, str) and cross_id else ""
    dedup_raw = cross_key or row.get("uuid") or f"off:{line_end}"
    dedup_key = f"cl:{dedup_raw}"
    if not _push_seen(seen_list, seen_set, dedup_key):
        return
    if cross_key:
        if claim_global_seen is not None:
            if not claim_global_seen(cross_key):
                return
        elif global_seen is not None:
            if cross_key in global_seen:
                return
            global_seen.add(cross_key)
            if new_global_seen is not None:
                new_global_seen.append(cross_key)

    iterations = usage.get("iterations")
    if isinstance(iterations, list) and iterations:
        recorded_any = False
        for it in iterations:
            if not isinstance(it, dict):
                continue
            itype = str(it.get("type") or "message")
            is_adv = 1 if itype == "advisor_message" else 0
            it_model = str(it.get("model") or base_model or "claude")
            if it_model == "<synthetic>":
                continue
            in_tok = nonneg_int(it.get("input_tokens"))
            out_tok = nonneg_int(it.get("output_tokens"))
            cr_tok = nonneg_int(it.get("cache_read_input_tokens"))
            w5, w1 = _claude_cache_write(it)
            if in_tok + out_tok + cr_tok + w5 + w1 == 0:
                continue
            recorded_any = True
            _add_delta(
                deltas,
                hour_epoch,
                it_model,
                is_adv,
                calls=1,
                input_tok=in_tok,
                output_tok=out_tok,
                cache_read_tok=cr_tok,
                cache_write_5m_tok=w5,
                cache_write_1h_tok=w1,
            )
        if recorded_any:
            return

    if base_model == "<synthetic>":
        return
    in_tok = nonneg_int(usage.get("input_tokens"))
    out_tok = nonneg_int(usage.get("output_tokens"))
    cr_tok = nonneg_int(usage.get("cache_read_input_tokens"))
    w5, w1 = _claude_cache_write(usage)
    if in_tok + out_tok + cr_tok + w5 + w1 == 0:
        return
    _add_delta(
        deltas,
        hour_epoch,
        base_model,
        0,
        calls=1,
        input_tok=in_tok,
        output_tok=out_tok,
        cache_read_tok=cr_tok,
        cache_write_5m_tok=w5,
        cache_write_1h_tok=w1,
    )


def parse_agy_line(
    row: dict[str, Any],
    *,
    line_end: int,
    seen_list: list[str],
    seen_set: set[str],
    deltas: dict[tuple[int, str, int], list[Any]],
    meta: dict[str, str],
    fallback_epoch: int = 0,
) -> None:
    """Parse one agy transcript JSONL row into `deltas` and `meta`. Never fabricates cache_write."""
    rtype = row.get("type")
    hour_epoch = parse_hour_epoch(row.get("created_at") or row.get("timestamp"), fallback_epoch=fallback_epoch)
    if rtype == "ERROR_MESSAGE":
        step = row.get("step_index")
        err_key = f"agy_err:{step}" if step is not None else f"agy_err:off:{line_end}"
        if _push_seen(seen_list, seen_set, err_key):
            _add_delta(deltas, hour_epoch, meta.get("last_model") or "agy", 0, errors=1)
        return
    if rtype not in ("PLANNER_RESPONSE", "CHECKPOINT"):
        return
    status = str(row.get("status") or "")
    if status and status != "DONE":
        return
    in_tok = nonneg_int(row.get("input_tokens"))
    out_tok = nonneg_int(row.get("output_tokens"))
    cr_tok = nonneg_int(row.get("cache_read_tokens"))
    if in_tok + out_tok + cr_tok == 0:
        return
    model = str(row.get("model") or meta.get("last_model") or "agy")
    meta["last_model"] = model
    step = row.get("step_index")
    prefix = "agy_cp" if rtype == "CHECKPOINT" else "agy"
    dedup_key = f"{prefix}:{step}" if step is not None else f"{prefix}:off:{line_end}"
    if not _push_seen(seen_list, seen_set, dedup_key):
        return
    _add_delta(
        deltas,
        hour_epoch,
        model,
        0,
        calls=1,
        input_tok=in_tok,
        output_tok=out_tok,
        cache_read_tok=cr_tok,
        cache_write_5m_tok=0,
        cache_write_1h_tok=0,
    )


def _extract_codex_usage(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Return (usage_dict, total_sig) for Codex `token_usage_record` or `token_count` payloads."""
    if isinstance(payload.get("usage"), dict):
        return payload["usage"], ""
    if any(k in payload for k in ("input_tokens", "output_tokens", "cached_input_tokens")):
        return payload, ""
    info = payload.get("info")
    if isinstance(info, dict):
        last_u = info.get("last_token_usage")
        tot_u = info.get("total_token_usage")
        sig = ""
        if isinstance(tot_u, dict):
            sig = f"{nonneg_int(tot_u.get('input_tokens'))}:{nonneg_int(tot_u.get('output_tokens'))}:{nonneg_int(tot_u.get('cached_input_tokens'))}"
        if isinstance(last_u, dict):
            return last_u, sig
    return None, ""


def parse_codex_line(
    row: dict[str, Any],
    *,
    line_end: int,
    seen_list: list[str],
    seen_set: set[str],
    deltas: dict[tuple[int, str, int], list[Any]],
    meta: dict[str, str],
    fallback_epoch: int = 0,
) -> None:
    """Parse one Codex rollout JSONL row into `deltas` and `meta`."""
    rtype = row.get("type")
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    hour_epoch = parse_hour_epoch(row.get("timestamp") or payload.get("timestamp"), fallback_epoch=fallback_epoch)

    if rtype == "session_meta":
        if not meta.get("cwd") and isinstance(payload.get("cwd"), str) and payload["cwd"]:
            meta["cwd"] = payload["cwd"]
        sid = payload.get("id") or payload.get("session_id")
        if not meta.get("sid") and isinstance(sid, str) and sid:
            meta["sid"] = sid
        return
    if rtype == "turn_context":
        model = payload.get("model")
        if isinstance(model, str) and model:
            meta["last_model"] = model
        if not meta.get("cwd") and isinstance(payload.get("cwd"), str) and payload["cwd"]:
            meta["cwd"] = payload["cwd"]
        return

    is_tur = rtype == "token_usage_record"
    is_tc = rtype == "event_msg" and payload.get("type") == "token_count"
    if rtype == "event_msg" and payload.get("type") in ("error", "stream_error"):
        err_key = str(payload.get("id") or payload.get("turn_id") or row.get("ordinal") or f"off:{line_end}")
        if _push_seen(seen_list, seen_set, f"cx_err:{err_key}"):
            _add_delta(deltas, hour_epoch, meta.get("last_model") or "codex", 0, errors=1)
        return
    if not (is_tur or is_tc):
        return

    usage, tot_sig = _extract_codex_usage(payload)
    if not isinstance(usage, dict):
        return
    raw_in = nonneg_int(usage.get("input_tokens"))
    out_tok = nonneg_int(usage.get("output_tokens"))
    cr_tok = nonneg_int(usage.get("cached_input_tokens"))
    cw_tok = nonneg_int(usage.get("cache_write_input_tokens"))
    uncached_in = max(0, raw_in - cr_tok - cw_tok)
    if uncached_in + out_tok + cr_tok + cw_tok == 0:
        return

    resp_id = payload.get("response_id") or row.get("response_id")
    if isinstance(resp_id, str) and resp_id:
        dedup_key = f"cx:{resp_id}"
    elif is_tc and tot_sig:
        dedup_key = f"cx_tc:{tot_sig}"
    else:
        dedup_key = f"cx:off:{line_end}"
    if not _push_seen(seen_list, seen_set, dedup_key):
        return

    model = str(payload.get("model") or meta.get("last_model") or "codex")
    meta["last_model"] = model
    _add_delta(
        deltas,
        hour_epoch,
        model,
        0,
        calls=1,
        input_tok=uncached_in,
        output_tok=out_tok,
        cache_read_tok=cr_tok,
        cache_write_5m_tok=cw_tok,
        cache_write_1h_tok=0,
    )


def parse_pi_line(
    row: dict[str, Any],
    *,
    line_end: int,
    seen_list: list[str],
    seen_set: set[str],
    deltas: dict[tuple[int, str, int], list[Any]],
    meta: dict[str, str],
    fallback_epoch: int = 0,
) -> None:
    """Parse one pi session JSONL row into `deltas` and `meta`."""
    rtype = row.get("type")
    if rtype == "session":
        if not meta.get("cwd") and isinstance(row.get("cwd"), str) and row["cwd"]:
            meta["cwd"] = row["cwd"]
        if not meta.get("sid") and isinstance(row.get("id"), str) and row["id"]:
            meta["sid"] = row["id"]
        return
    if rtype != "message":
        return
    msg = row.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return

    hour_epoch = parse_hour_epoch(row.get("timestamp") or msg.get("timestamp"), fallback_epoch=fallback_epoch)
    model = str(msg.get("model") or meta.get("last_model") or "pi")
    if model:
        meta["last_model"] = model

    dedup_raw = row.get("id") or f"off:{line_end}"
    if not _push_seen(seen_list, seen_set, f"pi:{dedup_raw}"):
        return

    is_err = bool(msg.get("errorMessage")) or msg.get("stopReason") == "error"
    usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
    in_tok = nonneg_int(usage.get("input"))
    out_tok = nonneg_int(usage.get("output"))
    cr_tok = nonneg_int(usage.get("cacheRead"))
    cw_tok = nonneg_int(usage.get("cacheWrite"))
    cost_obj = usage.get("cost") if isinstance(usage.get("cost"), dict) else {}
    usd = nonneg_float(cost_obj.get("total"))

    has_tok = (in_tok + out_tok + cr_tok + cw_tok) > 0
    if not has_tok and not is_err:
        return
    _add_delta(
        deltas,
        hour_epoch,
        model,
        0,
        calls=1 if has_tok else 0,
        errors=1 if is_err else 0,
        input_tok=in_tok,
        output_tok=out_tok,
        cache_read_tok=cr_tok,
        cache_write_5m_tok=cw_tok,
        cache_write_1h_tok=0,
        explicit_usd=usd,
    )


def _open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=30.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            ino INTEGER NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            byte_offset INTEGER NOT NULL,
            cwd TEXT NOT NULL DEFAULT '',
            sid TEXT NOT NULL DEFAULT '',
            parent_sid TEXT NOT NULL DEFAULT '',
            opening_role TEXT NOT NULL DEFAULT '',
            opening_task_hint TEXT NOT NULL DEFAULT '',
            last_model TEXT NOT NULL DEFAULT '',
            tail_seen_ids_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS hourly_rollups (
            path TEXT NOT NULL,
            hour_epoch INTEGER NOT NULL,
            model TEXT NOT NULL,
            is_advisor INTEGER NOT NULL DEFAULT 0,
            calls INTEGER NOT NULL DEFAULT 0,
            errors INTEGER NOT NULL DEFAULT 0,
            input_tok INTEGER NOT NULL DEFAULT 0,
            output_tok INTEGER NOT NULL DEFAULT 0,
            cache_read_tok INTEGER NOT NULL DEFAULT 0,
            cache_write_5m_tok INTEGER NOT NULL DEFAULT 0,
            cache_write_1h_tok INTEGER NOT NULL DEFAULT 0,
            explicit_usd REAL NOT NULL DEFAULT 0.0,
            PRIMARY KEY (path, hour_epoch, model, is_advisor)
        );
        CREATE INDEX IF NOT EXISTS idx_rollups_hour ON hourly_rollups(hour_epoch);
        CREATE TABLE IF NOT EXISTS seen_claude_msgs (
            msg_id TEXT PRIMARY KEY,
            owner_path TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_seen_claude_owner ON seen_claude_msgs(owner_path);
        """
    )
    row = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None or row[0] != SCHEMA_VERSION:
        con.execute("DELETE FROM hourly_rollups")
        con.execute("DELETE FROM files")
        con.execute("DELETE FROM seen_claude_msgs")
        con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,))
    return con


def _read_agy_summaries(agy_dir: Path) -> dict[str, tuple[list[str], str]]:
    """Read-only lookup of agy conversation_id -> (workspace_paths, parent_conversation_id)."""
    db_path = agy_dir / "conversation_summaries.db"
    if not db_path.is_file():
        return {}
    out: dict[str, tuple[list[str], str]] = {}
    con = None
    try:
        uri = f"file:{db_path.resolve()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2.0)
        for cid, raw_uris, parent_id in con.execute(
            "SELECT conversation_id, workspace_uris, parent_conversation_id FROM conversation_summaries"
        ):
            if not isinstance(cid, str) or not cid:
                continue
            paths: list[str] = []
            try:
                parsed = json.loads(raw_uris) if isinstance(raw_uris, str) and raw_uris else []
            except ValueError:
                parsed = []
            if isinstance(parsed, list):
                for u in parsed:
                    p = _uri_to_path(u)
                    if p:
                        paths.append(p)
            out[cid] = (paths, str(parent_id or ""))
    except sqlite3.Error:
        return {}
    finally:
        if con is not None:
            try:
                con.close()
            except sqlite3.Error:
                pass
    return out


def _read_opening_meta(agent: str, path: Path) -> tuple[str, str, str]:
    """Read opening rows strictly before the first model reply and return `(role, task_hint, derived_parent_sid)`."""
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            lines, _ = _read_lines_forward(f, 0, min(HEAD_BYTES_META, size))
            if not lines and size > 0:
                f.seek(0)
                raw_one = f.readline(LINE_MAX)
                if raw_one:
                    lines = [(raw_one.rstrip(b"\r\n"), len(raw_one))]
    except OSError:
        return "", "", ""

    parts: list[str] = []
    derived_parent = ""
    for raw, _ in lines:
        if not raw or not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue

        rtype = row.get("type")
        if agent == "claude":
            if rtype == "derived-from" and not derived_parent:
                for s in row.get("sessions") or []:
                    if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]:
                        derived_parent = s["id"]
                        break
                continue
            if row.get("isSidechain"):
                continue
            msg = row.get("message") if isinstance(row.get("message"), dict) else {}
            if rtype == "assistant" or msg.get("role") == "assistant":
                break
            if rtype == "user":
                txt = _extract_content_text(msg.get("content"))
                if txt:
                    parts.append(txt)
            elif rtype == "attachment":
                att = row.get("attachment")
                if isinstance(att, dict) and isinstance(att.get("content"), str) and att["content"]:
                    parts.append(att["content"])
            elif rtype == "system" and isinstance(row.get("content"), str) and row["content"]:
                parts.append(row["content"])
        elif agent == "agy":
            if rtype == "PLANNER_RESPONSE":
                break
            if rtype == "USER_INPUT":
                txt = _extract_agy_user_text(row.get("content") or "")
                if txt:
                    parts.append(txt)
        elif agent == "codex":
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if rtype == "token_usage_record":
                break
            if rtype == "response_item":
                if payload.get("role") == "assistant" or payload.get("type") in (
                    "function_call", "custom_tool_call", "local_shell_call"
                ):
                    break
                if payload.get("role") == "user":
                    txt = _extract_content_text(payload.get("content"))
                    if txt:
                        parts.append(txt)
            elif rtype == "event_msg" and payload.get("type") == "user_message":
                txt = str(payload.get("message") or payload.get("content") or "")
                if txt:
                    parts.append(txt)
        elif agent == "pi":
            msg = row.get("message") if isinstance(row.get("message"), dict) else {}
            if rtype == "message":
                if msg.get("role") == "assistant":
                    break
                if msg.get("role") == "user":
                    txt = _extract_content_text(msg.get("content"))
                    if txt:
                        parts.append(txt)
        else:
            break

    role, hint = _detect_opening_meta("\n".join(parts))
    return role, hint, derived_parent


def _read_lines_forward(f: Any, start: int, size: int) -> tuple[list[tuple[bytes | None, int]], int]:
    """Read complete '\\n'-terminated lines from `start` to `size` without loading oversized lines."""
    f.seek(start)
    at = start
    lines: list[tuple[bytes | None, int]] = []
    while at < size:
        buf = bytearray()
        total = 0
        too_long = False
        found_nl = False
        while at + total < size:
            chunk = f.readline(min(BLOCK_SIZE, size - (at + total)))
            if not chunk:
                break
            total += len(chunk)
            if chunk.endswith(b"\n"):
                found_nl = True
                if not too_long:
                    buf.extend(chunk[:-1])
                    if len(buf) > LINE_MAX:
                        too_long = True
                        buf.clear()
                break
            if not too_long:
                if len(buf) + len(chunk) > LINE_MAX:
                    too_long = True
                    buf.clear()
                else:
                    buf.extend(chunk)
        if not found_nl:
            break
        at += total
        lines.append((None if too_long else bytes(buf), at))
    return lines, at


def _read_head_meta(agent: str, path: Path) -> tuple[str, str]:
    """Read opening lines of Codex/pi JSONL to quickly check cwd/sid without scanning whole file."""
    cwd = ""
    sid = ""
    try:
        with open(path, "rb") as f:
            lines, _ = _read_lines_forward(f, 0, min(HEAD_BYTES_META, os.fstat(f.fileno()).st_size))
        for raw, _ in lines[:12]:
            if not raw:
                continue
            try:
                row = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if agent == "codex" and row.get("type") == "session_meta":
                payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                cwd = str(payload.get("cwd") or "")
                sid = str(payload.get("id") or payload.get("session_id") or "")
                break
            if agent == "pi" and row.get("type") == "session":
                cwd = str(row.get("cwd") or "")
                sid = str(row.get("id") or "")
                break
    except OSError:
        pass
    return cwd, sid


def _claude_folder_in_scope(folder_name: str, exact_folders: set[str], wt_prefixes: list[str]) -> bool:
    if folder_name in exact_folders:
        return True
    for pref in wt_prefixes:
        if folder_name == pref or folder_name.startswith(pref + "-"):
            return True
    return False


def _infer_agent_for_path(path: Path, ctx: Any) -> str:
    norm = _norm_path(str(path))
    roots = [
        ("claude", getattr(ctx.agents, "claude_projects", None) or getattr(ctx, "claude_projects", None)),
        ("agy", getattr(ctx, "agy_dir", None)),
        ("codex", getattr(ctx.agents, "codex_sessions", None) or getattr(ctx, "codex_sessions", None)),
        ("pi", getattr(ctx, "pi_sessions", None)),
    ]
    for kind, root in roots:
        if root is not None:
            rn = _norm_path(str(root))
            if rn and (norm == rn or norm.startswith(rn + "/")):
                return kind
    if "/.claude/" in norm:
        return "claude"
    if "/antigravity-cli/" in norm:
        return "agy"
    if "/.codex/" in norm:
        return "codex"
    if "/.pi/" in norm:
        return "pi"
    return ""


def _discover_candidates(
    ctx: Any,
    scopes: list[str],
    wt_homes: list[str],
    known_agy_cids: set[str],
    known_pm_paths: set[str] | None = None,
    norm_scopes: list[str] | None = None,
) -> list[dict[str, str]]:
    """Enumerate transcript candidates pruned to registered projects & worktrees."""
    candidates: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    exact_folders = {claude_folder(p) for p in scopes if p}
    wt_prefixes = [claude_folder(w) for w in wt_homes if w]
    n_scopes = norm_scopes if norm_scopes is not None else list(dict.fromkeys(_norm_path(s) for s in scopes if s))

    def _add_cand(item: dict[str, str]) -> None:
        raw_p = item["path"]
        if not raw_p or raw_p in seen_paths:
            return
        seen_paths.add(raw_p)
        candidates.append(item)

    # 1. Claude Code
    c_root = getattr(ctx.agents, "claude_projects", None) or getattr(ctx, "claude_projects", None)
    if c_root is not None:
        c_path = Path(c_root)
        if c_path.is_dir():
            try:
                dirs = sorted(c_path.iterdir())
            except OSError:
                dirs = []
            for folder in dirs:
                if not folder.is_dir():
                    continue
                if scopes and not _claude_folder_in_scope(folder.name, exact_folders, wt_prefixes):
                    continue
                try:
                    for p in sorted(folder.glob("*.jsonl")):
                        if p.is_file():
                            _add_cand({"agent": "claude", "path": str(p), "sid": p.stem, "parent_sid": ""})
                    for p in sorted(folder.glob("*/subagents/agent-*.jsonl")):
                        if p.is_file():
                            _add_cand({
                                "agent": "claude",
                                "path": str(p),
                                "sid": p.stem,
                                "parent_sid": p.parent.parent.name,
                                "opening_role": "subagent",
                            })
                except OSError:
                    continue

    # 2. agy
    a_root = getattr(ctx, "agy_dir", None)
    if a_root is not None:
        a_path = Path(a_root)
        brain = a_path / "brain"
        if brain.is_dir():
            summaries = _read_agy_summaries(a_path)

            def _resolve_agy_scope(cid: str) -> tuple[bool, str, str]:
                ws_paths, parent_cid = summaries.get(cid, ([], ""))
                cur = cid
                visited: set[str] = set()
                in_sc = False
                matched_cwd = ""
                for _ in range(8):
                    if not cur or cur in visited:
                        break
                    visited.add(cur)
                    if cur in known_agy_cids:
                        in_sc = True
                    cur_ws, cur_parent = summaries.get(cur, ([], ""))
                    for wp in cur_ws:
                        if not n_scopes or _fast_in_norm_scopes(wp, n_scopes):
                            in_sc = True
                            if not matched_cwd:
                                matched_cwd = wp
                            break
                    if in_sc and matched_cwd:
                        break
                    cur = cur_parent
                fallback_cwd = matched_cwd or (ws_paths[0] if ws_paths else "")
                return in_sc, fallback_cwd, parent_cid

            try:
                cids = sorted(brain.iterdir())
            except OSError:
                cids = []
            for cid_dir in cids:
                logs_dir = cid_dir / ".system_generated" / "logs"
                tr_path = logs_dir / "transcript.jsonl"
                if not tr_path.is_file():
                    tr_path = logs_dir / "transcript_full.jsonl"
                    if not tr_path.is_file():
                        continue
                cid = cid_dir.name
                in_sc, cwd_val, parent_cid = _resolve_agy_scope(cid)
                if not in_sc and scopes:
                    continue
                _add_cand({
                    "agent": "agy",
                    "path": str(tr_path),
                    "sid": cid,
                    "parent_sid": parent_cid,
                    "cwd": cwd_val,
                })

    # 3. Codex
    cx_root = getattr(ctx.agents, "codex_sessions", None) or getattr(ctx, "codex_sessions", None)
    if cx_root is not None:
        cx_path = Path(cx_root)
        if cx_path.is_dir():
            try:
                for p in sorted(cx_path.rglob("*.jsonl")):
                    if p.is_file():
                        _add_cand({"agent": "codex", "path": str(p)})
            except OSError:
                pass

    # 4. pi
    pi_root = getattr(ctx, "pi_sessions", None)
    if pi_root is not None:
        pi_path = Path(pi_root)
        if pi_path.is_dir():
            try:
                for p in sorted(pi_path.rglob("*.jsonl")):
                    if p.is_file():
                        _add_cand({"agent": "pi", "path": str(p)})
            except OSError:
                pass

    # 5. Explicitly known PM transcript paths (handles symlinked repos or custom paths without double-counting)
    if known_pm_paths:
        seen_norm = {_norm_path(p) for p in seen_paths} if len(seen_paths) < 2000 else set(seen_paths)
        for raw_pm_path in sorted(known_pm_paths):
            if not raw_pm_path:
                continue
            p = Path(raw_pm_path)
            if not p.is_file():
                continue
            agent = _infer_agent_for_path(p, ctx)
            if not agent:
                continue
            if agent == "agy":
                compact = p.parent / "transcript.jsonl"
                if p.name == "transcript_full.jsonl" and compact.is_file():
                    p = compact
                np = _norm_path(str(p))
                if str(p) in seen_paths or np in seen_norm:
                    continue
                seen_norm.add(np)
                cid = p.parent.parent.parent.name if p.parent.name == "logs" else p.stem
                _add_cand({"agent": "agy", "path": str(p), "sid": cid, "parent_sid": ""})
            elif agent == "claude":
                np = _norm_path(str(p))
                if str(p) in seen_paths or np in seen_norm:
                    continue
                seen_norm.add(np)
                _add_cand({"agent": "claude", "path": str(p), "sid": p.stem, "parent_sid": ""})
            else:
                np = _norm_path(str(p))
                if str(p) in seen_paths or np in seen_norm:
                    continue
                seen_norm.add(np)
                _add_cand({"agent": agent, "path": str(p)})

    return candidates


def sync_token_cache(
    ctx: Any,
    *,
    scopes: list[str],
    wt_homes: list[str],
    known_agy_cids: set[str] | None = None,
    known_pm_sids: set[str] | None = None,
    known_pm_paths: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Incrementally update SQLite rollups and return `(files_rows, rollup_rows)` for all in-scope files."""
    db_path = ctx.home.token_usage_db
    pm_sids_set = known_pm_sids or set()
    pm_paths_norm = {_norm_path(x) for x in (known_pm_paths or ()) if x}
    norm_scopes = list(dict.fromkeys(_norm_path(s) for s in scopes if s))
    candidates = _discover_candidates(
        ctx, scopes, wt_homes, known_agy_cids or set(), known_pm_paths=known_pm_paths, norm_scopes=norm_scopes
    )
    with file_lock(ctx.home.token_usage_lock, timeout=30.0):
        con = _open_db(db_path)
        try:
            stored: dict[str, tuple[Any, ...]] = {}
            for row in con.execute(
                "SELECT path, agent, ino, size, mtime_ns, byte_offset, cwd, sid, parent_sid, "
                "opening_role, opening_task_hint, last_model, tail_seen_ids_json FROM files"
            ):
                stored[row[0]] = row

            parsers = {
                "claude": parse_claude_line,
                "agy": parse_agy_line,
                "codex": parse_codex_line,
                "pi": parse_pi_line,
            }

            for cand in candidates:
                p_str = cand["path"]
                agent = cand["agent"]
                p = Path(p_str)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                ino, size, mtime_ns = int(st.st_ino), int(st.st_size), int(st.st_mtime_ns)
                prev = stored.get(p_str)
                if prev is not None and prev[2] == ino and prev[3] == size and prev[4] == mtime_ns:
                    if int(prev[5]) >= 0:
                        continue  # 0 bytes read for unchanged parsed files
                    prev_cwd = str(prev[6] or "")
                    prev_sid = str(prev[7] or "")
                    is_known_pm = prev_sid in pm_sids_set or _norm_path(p_str) in pm_paths_norm
                    if not is_known_pm and norm_scopes and prev_cwd and not _fast_in_norm_scopes(_norm_path(prev_cwd), norm_scopes):
                        continue  # still out of scope for any registered project

                reset = prev is None or prev[2] != ino or int(prev[5]) < 0 or size < int(prev[5])
                if reset:
                    con.execute("DELETE FROM hourly_rollups WHERE path = ?", (p_str,))
                    if agent == "claude":
                        con.execute("DELETE FROM seen_claude_msgs WHERE owner_path = ?", (p_str,))
                    offset = 0
                    cwd = cand.get("cwd", "")
                    sid = cand.get("sid", "")
                    parent_sid = cand.get("parent_sid", "")
                    opening_role = cand.get("opening_role", "")
                    opening_task_hint = ""
                    last_model = ""
                    seen_list: list[str] = []
                else:
                    assert prev is not None
                    offset = int(prev[5])
                    cwd = str(prev[6] or cand.get("cwd", ""))
                    sid = str(prev[7] or cand.get("sid", ""))
                    parent_sid = str(prev[8] or cand.get("parent_sid", ""))
                    opening_role = str(prev[9] or cand.get("opening_role", ""))
                    opening_task_hint = str(prev[10] or "")
                    last_model = str(prev[11] or "")
                    try:
                        loaded_seen = json.loads(prev[12] or "[]")
                        seen_list = [str(x) for x in loaded_seen] if isinstance(loaded_seen, list) else []
                    except ValueError:
                        seen_list = []

                # For Codex/pi, peek head metadata to skip parsing out-of-scope files with sentinel byte_offset = -1
                if reset and agent in ("codex", "pi") and norm_scopes:
                    head_cwd, head_sid = _read_head_meta(agent, p)
                    if head_cwd:
                        cwd = head_cwd
                    if head_sid:
                        sid = head_sid
                    is_known_pm = sid in pm_sids_set or _norm_path(p_str) in pm_paths_norm
                    if not is_known_pm and cwd and not _fast_in_norm_scopes(_norm_path(cwd), norm_scopes):
                        con.execute(
                            "INSERT OR REPLACE INTO files(path, agent, ino, size, mtime_ns, byte_offset, cwd, sid, "
                            "parent_sid, opening_role, opening_task_hint, last_model, tail_seen_ids_json) "
                            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (p_str, agent, ino, size, mtime_ns, -1, cwd, sid, parent_sid, opening_role, opening_task_hint, last_model, "[]"),
                        )
                        continue

                if reset and not opening_task_hint and opening_role != "subagent":
                    det_role, det_hint, det_parent = _read_opening_meta(agent, p)
                    if not opening_role and det_role:
                        opening_role = det_role
                    if det_hint:
                        opening_task_hint = det_hint
                    if not parent_sid and det_parent:
                        parent_sid = det_parent

                seen_set = set(seen_list)
                deltas: dict[tuple[int, str, int], list[Any]] = {}
                meta = {"cwd": cwd, "sid": sid, "last_model": last_model}
                parser = parsers[agent]
                fallback_epoch = int(mtime_ns // 1_000_000_000)

                def _claim_claude_msg(mid: str, _owner: str = p_str) -> bool:
                    cur = con.execute(
                        "INSERT OR IGNORE INTO seen_claude_msgs(msg_id, owner_path) VALUES(?, ?)",
                        (mid, _owner),
                    )
                    return cur.rowcount > 0

                new_offset = offset
                if size > offset:
                    try:
                        with open(p, "rb") as f:
                            lines, new_offset = _read_lines_forward(f, offset, size)
                    except OSError:
                        continue
                    for raw, line_end in lines:
                        if raw is None or not raw.strip():
                            continue
                        try:
                            row = json.loads(raw.decode("utf-8", "replace"))
                        except ValueError:
                            continue
                        if not isinstance(row, dict):
                            continue
                        if agent == "claude":
                            parse_claude_line(
                                row,
                                line_end=line_end,
                                seen_list=seen_list,
                                seen_set=seen_set,
                                deltas=deltas,
                                meta=meta,
                                fallback_epoch=fallback_epoch,
                                claim_global_seen=_claim_claude_msg,
                            )
                        else:
                            parser(
                                row,
                                line_end=line_end,
                                seen_list=seen_list,
                                seen_set=seen_set,
                                deltas=deltas,
                                meta=meta,
                                fallback_epoch=fallback_epoch,
                            )

                for (hour_epoch, model, is_adv), vals in deltas.items():
                    con.execute(
                        """
                        INSERT INTO hourly_rollups(
                            path, hour_epoch, model, is_advisor, calls, errors,
                            input_tok, output_tok, cache_read_tok, cache_write_5m_tok, cache_write_1h_tok, explicit_usd
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(path, hour_epoch, model, is_advisor) DO UPDATE SET
                            calls = calls + excluded.calls,
                            errors = errors + excluded.errors,
                            input_tok = input_tok + excluded.input_tok,
                            output_tok = output_tok + excluded.output_tok,
                            cache_read_tok = cache_read_tok + excluded.cache_read_tok,
                            cache_write_5m_tok = cache_write_5m_tok + excluded.cache_write_5m_tok,
                            cache_write_1h_tok = cache_write_1h_tok + excluded.cache_write_1h_tok,
                            explicit_usd = explicit_usd + excluded.explicit_usd
                        """,
                        (p_str, hour_epoch, model, is_adv, *vals),
                    )

                con.execute(
                    "INSERT OR REPLACE INTO files(path, agent, ino, size, mtime_ns, byte_offset, cwd, sid, "
                    "parent_sid, opening_role, opening_task_hint, last_model, tail_seen_ids_json) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        p_str,
                        agent,
                        ino,
                        size,
                        mtime_ns,
                        new_offset,
                        meta["cwd"],
                        meta["sid"],
                        parent_sid,
                        opening_role,
                        opening_task_hint,
                        meta["last_model"],
                        json.dumps(seen_list[-TAIL_SEEN_CAP:], ensure_ascii=False),
                    ),
                )

            con.commit()

            files_rows: list[dict[str, Any]] = []
            for r in con.execute(
                "SELECT path, agent, cwd, sid, parent_sid, opening_role, opening_task_hint "
                "FROM files WHERE byte_offset >= 0"
            ):
                files_rows.append({
                    "path": r[0],
                    "agent": r[1],
                    "cwd": r[2],
                    "sid": r[3],
                    "parent_sid": r[4],
                    "opening_role": r[5],
                    "opening_task_hint": r[6],
                })

            rollup_rows: list[dict[str, Any]] = []
            for r in con.execute(
                "SELECT path, hour_epoch, model, is_advisor, calls, errors, "
                "input_tok, output_tok, cache_read_tok, cache_write_5m_tok, cache_write_1h_tok, explicit_usd "
                "FROM hourly_rollups"
            ):
                rollup_rows.append({
                    "path": r[0],
                    "hour_epoch": int(r[1]),
                    "model": r[2],
                    "is_advisor": bool(r[3]),
                    "calls": int(r[4]),
                    "errors": int(r[5]),
                    "input_tok": int(r[6]),
                    "output_tok": int(r[7]),
                    "cache_read_tok": int(r[8]),
                    "cache_write_5m_tok": int(r[9]),
                    "cache_write_1h_tok": int(r[10]),
                    "explicit_usd": float(r[11]),
                })
            return files_rows, rollup_rows
        finally:
            con.close()
