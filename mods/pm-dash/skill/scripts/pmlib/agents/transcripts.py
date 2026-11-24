"""Agent session transcript reading and context-token measurement. Standard library only.

Implements the Sessions interface (transcript, context_tokens, turns) for Claude Code
transcripts (~/.claude/projects/<folder>/<id>.jsonl). Other agent kinds (Codex, agy, pi)
are not guessed: unknown kinds return None / 0 / UnsupportedSessionError.

All transcript reads are bounded:
- context_tokens scans backwards from EOF in 64 KiB blocks (capped at CONTEXT_SCAN_MAX),
  stopping at the first non-sidechain assistant row with usage, and caches results by
  (inode, size, mtime_ns) in memory and optionally in a small JSON cache file on disk.
- turns reads one byte-offset window at a time (before / after / newest end), never
  loading an entire multi-hundred-MB transcript into memory.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Protocol


def claude_folder(path: str | Path) -> str:
    """Folder name under ~/.claude/projects where Claude Code stores sessions for path."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


from ..store import BLOCK_SIZE, LINE_MAX  # noqa: E402 - after claude_folder so sessions can import it during cycles

# Window and scan bounds (matching app:service/session.go & scan.go).
DEFAULT_LIMIT = 200          # default max items per turns window
MAX_LIMIT = 2000             # upper bound on --limit
SESSION_BACK = 8 << 20       # max raw bytes walked back for one turns window
SESSION_HEAD = 1 << 20       # max raw bytes scanned from start for `started`
SESSION_TAIL = LINE_MAX      # max bytes searched back from EOF for the last newline
SINCE_MAX = 4 << 20          # max raw bytes scanned forward for `after`
CONTEXT_SCAN_MAX = 8 << 20   # max raw bytes walked back for context_tokens
SUMMARY_MAX = 300            # max chars for tool input/output one-line summary
BODY_MAX = 20_000            # max chars for user/assistant text body
KINDS_MOST = 8               # max unknown row types reported
CACHE_MAX_ENTRIES = 256      # max cached transcript entries kept on disk

# Claude Code housekeeping row types that say nothing to a reader.
QUIET_ROWS = frozenset({
    "summary", "file-history-snapshot", "system", "queue-operation", "progress", "attachment",
})

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
REFUSAL_WORD_RE = re.compile(r"^[A-Za-z0-9_ .-]{1,60}$")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:/")
ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")

# Tool input fields summarized as a single line; other tools fall back to compact JSON.
INPUT_FIELDS = {
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


class SessionError(Exception):
    """Base error for session transcript operations."""
    code = "error"


class SessionNotFoundError(SessionError):
    code = "not_found"


class UnsupportedSessionError(SessionError):
    code = "unsupported"


class SessionChangedError(SessionError):
    code = "changed"


class InvalidOffsetError(SessionError):
    code = "invalid"


@dataclass
class Turns:
    """One window of an agent's session conversation (SessionAnswer-compatible JSON)."""
    kind: str
    id: str
    started: str
    ended: str
    items: list[dict[str, Any]]
    from_: int
    offset: int
    earlier: bool
    more: bool = False
    reset: bool = False
    context: int = 0
    unknown: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "started": self.started,
            "ended": self.ended,
            "items": self.items,
            "from": self.from_,
            "offset": self.offset,
            "earlier": self.earlier,
            "more": self.more,
            "reset": self.reset,
        }
        if self.context > 0:
            out["context"] = self.context
        if self.unknown:
            out["unknown"] = list(self.unknown)
        return out


class Sessions(Protocol):
    def transcript(self, session: dict[str, Any] | Path | str | None) -> Path | None: ...
    def context_tokens(self, session: dict[str, Any] | Path | str | None) -> int: ...
    def turns(self, session: dict[str, Any] | Path | str | None, before: int | None = None,
              limit: int = DEFAULT_LIMIT, after: int | None = None) -> Turns: ...


def valid_session_id(sid: Any) -> bool:
    """True when sid is a safe single-segment filename stem (no separators, globs or '..')."""
    return isinstance(sid, str) and bool(SESSION_ID_RE.fullmatch(sid)) and ".." not in sid


def default_claude_projects() -> Path:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    return base / "projects"


# ---- text tidying (home path shortening and length bounds) ------------------

def home_spellings(home: str, is_windows: bool) -> list[str]:
    seps = "\\/" if is_windows else "/"
    home = home.rstrip(seps)
    if not home:
        return []
    if not is_windows:
        return [home]
    slashed = home.replace("\\", "/")
    out = [home.replace("\\", "\\\\"), home, slashed]
    if WINDOWS_DRIVE_RE.match(slashed):
        out.append("/" + slashed[0].lower() + slashed[2:])
    return out


class Tidier:
    """Shorten the user's home directory to ~ and bound body/summary lengths."""

    def __init__(self, home: str | None = None, is_windows: bool | None = None):
        self.fold = (os.name == "nt") if is_windows is None else bool(is_windows)
        if home is None:
            try:
                home = str(Path.home())
            except RuntimeError:
                home = ""
        self.homes = home_spellings(home, self.fold)

    def short(self, text: str) -> str:
        if not self.homes or not text:
            return text
        # ASCII-only case folding keeps character indices 1:1 with `text`.
        look = text.translate(ASCII_LOWER) if self.fold else text
        wants = [h.translate(ASCII_LOWER) if self.fold else h for h in self.homes]
        out: list[str] = []
        pos = 0
        at = 0
        length = len(text)
        while at < length:
            hit = -1
            size = 0
            for want in wants:
                idx = look.find(want, at)
                if idx >= 0 and (hit < 0 or idx < hit or (idx == hit and len(want) > size)):
                    hit = idx
                    size = len(want)
            if hit < 0:
                break
            after = hit + size
            if after < length:
                nxt = text[after]
                if nxt.isalnum() or nxt in "_-.":
                    at = after
                    continue
            out.append(text[pos:hit])
            out.append("~")
            pos = at = after
        out.append(text[pos:])
        return "".join(out)

    def body(self, text: str) -> str:
        shortened = self.short(text)
        if len(shortened) > BODY_MAX:
            return shortened[:BODY_MAX] + "…"
        return shortened

    def line(self, text: str) -> str:
        squashed = self.short(" ".join(text.split()))
        return squashed[:SUMMARY_MAX] if len(squashed) > SUMMARY_MAX else squashed


# ---- bounded low-level file scanning ----------------------------------------

def line_start(f: Any, at: int) -> bool:
    """True when byte offset `at` is 0 or immediately follows a '\\n' byte."""
    if at == 0:
        return True
    if at < 0:
        return False
    f.seek(at - 1)
    return f.read(1) == b"\n"


def last_line_end(f: Any, size: int, max_tail: int = SESSION_TAIL) -> int:
    """Byte offset immediately after the last '\\n' in the final `max_tail` bytes of f, or 0."""
    end = size
    while end > 0 and size - end <= max_tail:
        n = min(BLOCK_SIZE, end)
        f.seek(end - n)
        chunk = f.read(n)
        if not chunk:
            return 0
        idx = chunk.rfind(b"\n")
        if idx >= 0:
            return end - n + idx + 1
        end -= n
    return 0


def each_line_back(f: Any, end: int, include_partial: bool = False) -> Iterator[tuple[bytes | None, int, int]]:
    """Yield (raw_line_or_None, start_offset, next_offset) walking backwards from `end` to 0.

    Holds at most one BLOCK_SIZE buffer and one line in memory. A line longer than LINE_MAX
    yields raw=None so callers can advance past it without allocating memory for it.
    """
    if end <= 0:
        return
    block = b""
    bstart = 0
    bend = 0

    def newline_before(pos: int) -> int:
        nonlocal block, bstart, bend
        while pos > 0:
            if not (bstart < pos <= bend):
                n = min(BLOCK_SIZE, pos)
                f.seek(pos - n)
                block = f.read(n)
                bstart = pos - len(block)
                bend = pos
                if not block:
                    return -1
            idx = block.rfind(b"\n", 0, pos - bstart)
            if idx >= 0:
                return bstart + idx
            pos = bstart
        return -1

    next_off = end
    # Optional trailing line without '\n' (e.g., synthetic fixtures or active write).
    if include_partial:
        f.seek(end - 1)
        if f.read(1) != b"\n":
            nl = newline_before(end)
            at = nl + 1
            length = end - at
            if length > LINE_MAX:
                raw: bytes | None = None
            elif bstart <= at and end <= bend:
                raw = block[at - bstart:end - bstart]
            else:
                f.seek(at)
                raw = f.read(length)
            yield raw, at, end
            next_off = at

    while next_off > 0:
        nl = newline_before(next_off - 1)
        at = nl + 1
        length = next_off - 1 - at
        if length > LINE_MAX:
            raw = None
        elif bstart <= at and next_off - 1 <= bend:
            raw = block[at - bstart:next_off - 1 - bstart]
        else:
            f.seek(at)
            raw = f.read(length)
        yield raw, at, next_off
        next_off = at


def read_lines_forward(f: Any, start: int, size: int, budget: int) -> tuple[list[tuple[bytes | None, int]], int, bool]:
    """Read complete '\\n'-terminated lines from `start` up to `budget` bytes (negative: to EOF).

    Returns ([(raw_or_None, end_offset), ...], final_offset, more_remaining).
    """
    f.seek(start)
    at = start
    lines: list[tuple[bytes | None, int]] = []
    more = False
    while at < size:
        if budget >= 0 and at - start >= budget:
            more = True
            break
        # Read line in bounded chunks so a 100 MB line never consumes 100 MB RAM.
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
            # Unterminated final line (still being written): stop before it.
            break
        at += total
        lines.append((None if too_long else bytes(buf), at))
    return lines, at, more


# ---- Claude Code transcript parsing -----------------------------------------

def _int_token(val: Any) -> int:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return 0
    return int(val) if val > 0 else 0


def _usage_tokens(usage: Any) -> int:
    if not isinstance(usage, dict) or not usage:
        return 0
    return (_int_token(usage.get("input_tokens"))
            + _int_token(usage.get("cache_read_input_tokens"))
            + _int_token(usage.get("cache_creation_input_tokens")))


def context_tokens_file(path: str | Path, max_scan: int = CONTEXT_SCAN_MAX) -> int:
    """Context tokens held by a Claude Code transcript: input side of its latest non-sidechain
    assistant call with usage, stopping at any compact_boundary (where postTokens holds the compacted
    context size). Scans backwards from EOF, bounded by `max_scan` bytes."""
    if not path:
        return 0
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size <= 0:
                return 0
            for raw, at, _ in each_line_back(f, size, include_partial=True):
                if raw is not None and (b'"usage"' in raw or b'"compact_boundary"' in raw or b"\\u" in raw):
                    try:
                        row = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        row = None
                    if isinstance(row, dict) and not row.get("isSidechain"):
                        if row.get("type") == "system" and row.get("subtype") == "compact_boundary":
                            meta = row.get("compactMetadata")
                            return _int_token(meta.get("postTokens")) if isinstance(meta, dict) else 0
                        if row.get("type") == "assistant":
                            msg = row.get("message")
                            if isinstance(msg, dict):
                                tokens = _usage_tokens(msg.get("usage"))
                                if tokens > 0:
                                    return tokens
                if max_scan >= 0 and size - at >= max_scan:
                    break
    except (OSError, TypeError, ValueError):
        return 0
    return 0


def _block_text(blocks: list[Any]) -> str:
    parts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"
             and isinstance(b.get("text"), str) and b["text"]]
    return "\n".join(parts)


def _input_summary(name: str, inp: Any) -> str:
    if isinstance(inp, dict):
        for key in INPUT_FIELDS.get(name, ()):
            val = inp.get(key)
            if isinstance(val, str) and val.strip():
                return val
    if inp is None:
        return ""
    try:
        return json.dumps(inp, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(inp)


@dataclass
class _ParsedLine:
    talk: bool = False
    at: str = ""
    items: list[dict[str, Any]] = None  # type: ignore[assignment]
    results: list[dict[str, Any]] = None  # type: ignore[assignment]
    kind: str = ""
    understood: bool = False
    context: int = 0
    compact_boundary: bool = False

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = []
        if self.results is None:
            self.results = []


def _parse_transcript_line(raw: bytes | None, end: int, tidy: Tidier) -> _ParsedLine:
    out = _ParsedLine()
    if raw is None or not raw.strip():
        return out
    try:
        row = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        out.kind = "?"
        return out
    if not isinstance(row, dict):
        out.kind = "?"
        return out
    rtype = row.get("type")
    if not isinstance(rtype, str) or not rtype:
        out.kind = "?"
        return out
    out.kind = rtype
    if (row.get("isMeta") or row.get("isSidechain")
            or row.get("isCompactSummary") or row.get("isVisibleInTranscriptOnly")):
        out.understood = True
        return out
    if rtype == "system" and row.get("subtype") == "compact_boundary":
        out.understood = True
        out.compact_boundary = True
        meta = row.get("compactMetadata")
        if isinstance(meta, dict):
            out.context = _int_token(meta.get("postTokens"))
        return out

    at = row.get("timestamp") if isinstance(row.get("timestamp"), str) else ""

    def add_said(kind: str, body: str) -> None:
        if body.strip():
            out.items.append({"type": kind, "at": at, "text": tidy.body(body), "offset": end})

    # Words typed while the agent worked are recorded as a queued_command attachment.
    if rtype == "attachment":
        att = row.get("attachment")
        if isinstance(att, dict) and att.get("type") == "queued_command":
            out.understood = True
            prompt = att.get("prompt")
            if isinstance(prompt, str):
                add_said("user", prompt)
            return out
        return out

    if rtype not in ("user", "assistant"):
        return out

    out.talk = True
    out.at = at
    msg = row.get("message")
    if not isinstance(msg, dict):
        return out
    content = msg.get("content")
    out.understood = isinstance(content, (str, list))
    if rtype == "assistant":
        out.context = _usage_tokens(msg.get("usage"))

    whole = content if isinstance(content, str) else ""
    blocks = content if isinstance(content, list) else []

    if rtype == "user":
        for blk in blocks:
            if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                continue
            call_id = blk.get("tool_use_id")
            if not isinstance(call_id, str) or not call_id:
                continue
            rc = blk.get("content")
            if isinstance(rc, str):
                result_text = rc
            elif isinstance(rc, list):
                result_text = _block_text(rc)
            else:
                result_text = ""
            out.results.append({
                "type": "result",
                "at": at,
                "id": call_id,
                "output": tidy.line(result_text),
                "error": bool(blk.get("is_error")),
                "offset": end,
            })
        add_said("user", whole + _block_text(blocks))
        return out

    # Assistant row
    if whole:
        add_said("text", whole)
    for blk in blocks:
        if not isinstance(blk, dict):
            continue
        btype = blk.get("type")
        if btype == "text" and isinstance(blk.get("text"), str):
            add_said("text", blk["text"])
        elif btype == "tool_use":
            name = blk.get("name") if isinstance(blk.get("name"), str) else ""
            call_id = blk.get("id") if isinstance(blk.get("id"), str) else ""
            item: dict[str, Any] = {
                "type": "tool",
                "at": at,
                "name": name,
                "input": tidy.line(_input_summary(name, blk.get("input"))),
                "output": "",
                "error": False,
                "offset": end,
            }
            if call_id:
                item["id"] = call_id
            out.items.append(item)
    return out


def _unknown_kinds(lines: list[_ParsedLine]) -> list[str] | None:
    kinds: list[str] = []
    seen: set[str] = set()
    strange = False
    for line in lines:
        if line.understood:
            return None
        kind = line.kind
        if not kind:
            continue
        if not REFUSAL_WORD_RE.fullmatch(kind):
            kind = "?"
        if kind not in QUIET_ROWS:
            strange = True
        if kind not in seen and len(kinds) < KINDS_MOST:
            seen.add(kind)
            kinds.append(kind)
    return kinds if strange else None


def _context_of(lines: list[_ParsedLine]) -> int:
    for line in reversed(lines):
        if line.context > 0 or line.compact_boundary:
            return line.context
    return 0


def _join_lines(lines: list[_ParsedLine], orphans: bool) -> tuple[list[dict[str, Any]], str]:
    items: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    ended = ""
    for line in lines:
        for res in line.results:
            call = calls.pop(res["id"], None)
            if call is not None:
                call["output"] = res["output"]
                call["error"] = res["error"]
            elif orphans:
                items.append(res)
        for item in line.items:
            items.append(item)
            if item.get("type") == "tool" and item.get("id"):
                calls[item["id"]] = item
        if line.talk and line.at:
            ended = line.at
    return items, ended


def _session_started(f: Any, size: int) -> str:
    """Timestamp of the first non-meta, non-sidechain user/assistant row in the first SESSION_HEAD bytes."""
    lines, _, _ = read_lines_forward(f, 0, size, SESSION_HEAD)
    for raw, _ in lines:
        if raw is None or not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if (isinstance(row, dict)
                and not row.get("isMeta")
                and not row.get("isSidechain")
                and not row.get("isCompactSummary")
                and not row.get("isVisibleInTranscriptOnly")
                and row.get("type") in ("user", "assistant")):
            ts = row.get("timestamp")
            if isinstance(ts, str) and ts:
                return ts
    return ""


# ---- stat-keyed cache (in-memory + optional atomic JSON file) ---------------

class _ContextCache:
    """Cache transcript context_tokens by (ino, size, mtime_ns), plus id->path hints."""

    def __init__(self, cache_path: Path | Callable[[], Path | None] | None = None):
        self._path_source = cache_path
        self._loaded = False
        self._dirty = False
        self._entries: dict[str, list[int]] = {}     # path -> [ino, size, mtime_ns, tokens]
        self._by_id: dict[str, str] = {}             # session_id -> path
        self._by_task: dict[str, list[Any]] = {}     # task_id -> [folder, dir_mtime_ns, max_file_mtime_ns, sid_or_empty]

    def _resolve_path(self) -> Path | None:
        if self._path_source is None:
            return None
        return self._path_source() if callable(self._path_source) else self._path_source

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = self._resolve_path()
        if not path:
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        raw_entries = data.get("entries") if data.get("version") == 2 else None
        if isinstance(raw_entries, dict):
            for k, v in raw_entries.items():
                if (isinstance(k, str) and isinstance(v, list) and len(v) == 4
                        and all(isinstance(x, int) and not isinstance(x, bool) for x in v)):
                    self._entries[k] = v
        raw_ids = data.get("by_id")
        if isinstance(raw_ids, dict):
            for k, v in raw_ids.items():
                if isinstance(k, str) and isinstance(v, str):
                    self._by_id[k] = v
        raw_tasks = data.get("by_task")
        if isinstance(raw_tasks, dict):
            for k, v in raw_tasks.items():
                if (isinstance(k, str) and isinstance(v, list) and len(v) == 4
                        and isinstance(v[0], str)
                        and isinstance(v[1], int) and not isinstance(v[1], bool)
                        and isinstance(v[2], int) and not isinstance(v[2], bool)
                        and isinstance(v[3], str)):
                    self._by_task[k] = v

    def cached_task(self, task_id: str, folder: str, dir_mtime_ns: int, max_file_mtime_ns: int) -> tuple[bool, str]:
        self._load()
        hit = self._by_task.get(task_id)
        if hit is not None and hit[0] == folder and hit[1] == dir_mtime_ns and hit[2] == max_file_mtime_ns:
            return True, hit[3]
        return False, ""

    def remember_task(self, task_id: str, folder: str, dir_mtime_ns: int, max_file_mtime_ns: int, sid: str) -> None:
        self._load()
        val = [folder, dir_mtime_ns, max_file_mtime_ns, sid]
        if self._by_task.get(task_id) != val:
            self._by_task.pop(task_id, None)
            self._by_task[task_id] = val
            self._dirty = True

    def cached_path(self, sid: str) -> Path | None:
        self._load()
        hit = self._by_id.get(sid)
        if not hit:
            return None
        p = Path(hit)
        try:
            if p.is_file():
                return p
        except OSError:
            pass
        self._by_id.pop(sid, None)
        self._dirty = True
        return None

    def remember_path(self, sid: str, path: Path) -> None:
        self._load()
        s = str(path)
        if self._by_id.get(sid) != s:
            self._by_id.pop(sid, None)
            self._by_id[sid] = s
            self._dirty = True

    def get_tokens(self, path: Path) -> int:
        self._load()
        key = str(path)
        try:
            st = os.stat(path)
        except OSError:
            return 0
        mark = [st.st_ino, st.st_size, st.st_mtime_ns]
        hit = self._entries.get(key)
        if hit is not None and hit[:3] == mark:
            return hit[3]
        tokens = context_tokens_file(path)
        self._entries.pop(key, None)
        self._entries[key] = [*mark, tokens]
        self._dirty = True
        return tokens

    def flush(self) -> None:
        if not self._dirty:
            return
        path = self._resolve_path()
        if not path:
            self._dirty = False
            return
        # Trim oldest entries to keep the cache tiny.
        if len(self._entries) > CACHE_MAX_ENTRIES:
            items = list(self._entries.items())[-CACHE_MAX_ENTRIES:]
            self._entries = dict(items)
        if len(self._by_id) > CACHE_MAX_ENTRIES:
            items = list(self._by_id.items())[-CACHE_MAX_ENTRIES:]
            self._by_id = dict(items)
        if len(self._by_task) > CACHE_MAX_ENTRIES:
            items = list(self._by_task.items())[-CACHE_MAX_ENTRIES:]
            self._by_task = dict(items)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
            payload = {"version": 2, "entries": self._entries, "by_id": self._by_id, "by_task": self._by_task}
            tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
        self._dirty = False


# ---- Claude Code Sessions implementation ------------------------------------

class ClaudeSessions:
    """Sessions implementation for Claude Code JSONL transcripts."""

    kind = "claude"

    def __init__(
        self,
        projects_dir: Path | Callable[[], Path] | None = None,
        home: str | Path | Callable[[], str] | None = None,
        cache_path: Path | Callable[[], Path | None] | None = None,
        is_windows: bool | None = None,
    ):
        self._projects_source = projects_dir
        self._home_source = home
        self._is_windows = is_windows
        self._cache = _ContextCache(cache_path)

    def _projects_dir(self) -> Path:
        if self._projects_source is None:
            return default_claude_projects()
        return Path(self._projects_source() if callable(self._projects_source) else self._projects_source)

    def _tidier(self) -> Tidier:
        if self._home_source is None:
            return Tidier(is_windows=self._is_windows)
        home = self._home_source() if callable(self._home_source) else str(self._home_source)
        return Tidier(home=str(home), is_windows=self._is_windows)

    def _extract_id(self, session: dict[str, Any] | Path | str | None) -> str:
        if isinstance(session, dict):
            sid = session.get("id")
            return sid if isinstance(sid, str) else ""
        if isinstance(session, (Path, str)) and str(session):
            return Path(session).stem
        return ""

    def _validated_path(self, candidate: Path, resolved_pdir: Path, sid: str) -> Path | None:
        """Accept `candidate` only when it resolves to a regular file `<projects_dir>/<folder>/<sid>.jsonl`."""
        if candidate.name != f"{sid}.jsonl":
            return None
        try:
            rp = candidate.resolve()
            if not rp.is_relative_to(resolved_pdir) or rp.parent == resolved_pdir or not rp.is_file():
                return None
            return rp
        except OSError:
            return None

    def transcript(self, session: dict[str, Any] | Path | str | None) -> Path | None:
        if session is None:
            return None
        pdir = self._projects_dir()
        try:
            resolved_pdir = pdir.resolve()
        except OSError:
            return None
        if not resolved_pdir.is_dir():
            return None
        if isinstance(session, (Path, str)):
            if not str(session):
                return None
            p = Path(session)
            if p.suffix != ".jsonl" or not valid_session_id(p.stem):
                return None
            return self._validated_path(p, resolved_pdir, p.stem)
        if not isinstance(session, dict):
            return None
        kind = session.get("kind")
        if kind and kind != self.kind:
            return None
        # Validate id FIRST before touching any path hint or cache entry.
        sid = session.get("id")
        if not valid_session_id(sid):
            return None
        explicit = session.get("path")
        if isinstance(explicit, (Path, str)) and str(explicit):
            ok = self._validated_path(Path(explicit), resolved_pdir, sid)
            if ok is not None:
                return ok
        cached = self._cache.cached_path(sid)
        if cached is not None:
            ok = self._validated_path(cached, resolved_pdir, sid)
            if ok is not None:
                return ok
        # Check hinted worktree/repo folders first (O(1) stat instead of scanning all project dirs).
        hints = session.get("hints") or ()
        if isinstance(hints, (str, Path)):
            hints = (hints,)
        for hint in hints:
            if not hint:
                continue
            cand = pdir / claude_folder(hint) / f"{sid}.jsonl"
            ok = self._validated_path(cand, resolved_pdir, sid)
            if ok is not None:
                self._cache.remember_path(sid, ok)
                return ok
        # Fallback: scan every project folder under ~/.claude/projects, newest mtime wins.
        best: Path | None = None
        best_mtime = -1
        try:
            entries = list(pdir.iterdir())
        except OSError:
            return None
        for folder in entries:
            cand = folder / f"{sid}.jsonl"
            ok = self._validated_path(cand, resolved_pdir, sid)
            if ok is None:
                continue
            try:
                st = ok.stat()
            except OSError:
                continue
            if best is None or st.st_mtime_ns > best_mtime:
                best = ok
                best_mtime = st.st_mtime_ns
        if best is not None:
            self._cache.remember_path(sid, best)
        return best

    def discover_task_session(
        self,
        task_id: str,
        folder_hint: str,
        since_ts: float,
        matcher: Callable[[str], bool],
        head_bytes: int = 128 << 10,
        exclude_ids: set[str] | frozenset[str] = frozenset(),
    ) -> dict[str, Any] | None:
        """Bounded head-only lookup for an active Claude task whose session was not recorded yet.

        Checks only the task's own project folder under projects_dir, reads at most `head_bytes`
        per recent .jsonl file, and caches the result by (folder, dir_mtime_ns, max_file_mtime_ns).
        """
        if not task_id or not folder_hint:
            return None
        pdir = self._projects_dir()
        try:
            resolved_pdir = pdir.resolve()
        except OSError:
            return None
        folder = pdir / claude_folder(folder_hint)
        try:
            dir_st = folder.stat()
        except OSError:
            return None
        if not folder.is_dir():
            return None
        candidates: list[tuple[int, float, Path]] = []
        max_file_mtime = 0
        try:
            for cand in folder.iterdir():
                if cand.suffix != ".jsonl" or not valid_session_id(cand.stem) or cand.stem in exclude_ids:
                    continue
                try:
                    st = cand.stat()
                except OSError:
                    continue
                if st.st_mtime_ns > max_file_mtime:
                    max_file_mtime = st.st_mtime_ns
                if st.st_mtime >= since_ts:
                    candidates.append((st.st_mtime_ns, st.st_mtime, cand))
        except OSError:
            return None
        folder_key = str(folder)
        hit, cached_sid = self._cache.cached_task(task_id, folder_key, dir_st.st_mtime_ns, max_file_mtime)
        if hit:
            if not cached_sid:
                return None
            if cached_sid not in exclude_ids:
                ok = self._validated_path(folder / f"{cached_sid}.jsonl", resolved_pdir, cached_sid)
                if ok is not None:
                    try:
                        if ok.stat().st_mtime >= since_ts:
                            return {"kind": self.kind, "id": cached_sid, "path": str(ok), "hints": [folder_hint]}
                    except OSError:
                        pass
        candidates.sort(key=lambda item: item[0], reverse=True)
        for _, _, cand in candidates:
            ok = self._validated_path(cand, resolved_pdir, cand.stem)
            if ok is None:
                continue
            try:
                with open(ok, "rb") as f:
                    head = f.read(head_bytes).decode("utf-8", "replace")
            except OSError:
                continue
            if matcher(head):
                self._cache.remember_task(task_id, folder_key, dir_st.st_mtime_ns, max_file_mtime, ok.stem)
                self._cache.remember_path(ok.stem, ok)
                return {"kind": self.kind, "id": ok.stem, "path": str(ok), "hints": [folder_hint]}
        self._cache.remember_task(task_id, folder_key, dir_st.st_mtime_ns, max_file_mtime, "")
        return None

    def context_tokens(self, session: dict[str, Any] | Path | str | None) -> int:
        path = self.transcript(session)
        if path is None:
            return 0
        return self._cache.get_tokens(path)

    def flush(self) -> None:
        self._cache.flush()

    def turns(
        self,
        session: dict[str, Any] | Path | str | None,
        before: int | None = None,
        limit: int = DEFAULT_LIMIT,
        after: int | None = None,
    ) -> Turns:
        if isinstance(session, dict) and session.get("kind") and session.get("kind") != self.kind:
            raise UnsupportedSessionError(f"session kind {session.get('kind')!r} is not supported")
        if before is not None and after is not None:
            raise InvalidOffsetError("cannot specify both before and after")
        if limit is None:
            limit = DEFAULT_LIMIT
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > MAX_LIMIT:
            raise InvalidOffsetError(f"limit must be between 1 and {MAX_LIMIT}")
        if before is not None and (isinstance(before, bool) or not isinstance(before, int) or before < 0):
            raise InvalidOffsetError("before must be a non-negative byte offset")
        if after is not None and (isinstance(after, bool) or not isinstance(after, int) or after < 0):
            raise InvalidOffsetError("after must be a non-negative byte offset")

        path = self.transcript(session)
        if path is None:
            raise SessionNotFoundError("session transcript not found")
        sid = self._extract_id(session)
        tidy = self._tidier()

        try:
            with open(path, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                if before is not None:
                    if before > size:
                        raise SessionChangedError("the transcript is shorter than that: it was replaced")
                    if not line_start(f, before):
                        raise InvalidOffsetError(f"no line of the transcript starts at byte {before}")
                    return self._window(f, sid, before, limit, tidy, fresh=False, reset=False)
                if after is not None and after <= size and line_start(f, after):
                    return self._since(f, sid, size, after, tidy)
                end = last_line_end(f, size)
                out = self._window(f, sid, end, limit, tidy, fresh=True, reset=(after is not None))
                out.started = _session_started(f, size)
                if out.context == 0 and out.from_ > 0:
                    out.context = self._cache.get_tokens(path)
                return out
        except SessionError:
            raise
        except OSError as exc:
            raise SessionNotFoundError(f"the transcript could not be read: {exc}") from exc

    def _window(
        self,
        f: Any,
        sid: str,
        end: int,
        limit: int,
        tidy: Tidier,
        *,
        fresh: bool,
        reset: bool,
    ) -> Turns:
        lines: list[_ParsedLine] = []
        count = 0
        from_off = end
        for raw, at, nxt in each_line_back(f, end, include_partial=False):
            parsed = _parse_transcript_line(raw, nxt, tidy)
            lines.append(parsed)
            count += len(parsed.items)
            from_off = at
            if count >= limit or end - at >= SESSION_BACK:
                break
        lines.reverse()
        items, ended = _join_lines(lines, orphans=(from_off > 0))
        ctx = _context_of(lines)
        unknown = _unknown_kinds(lines) if (fresh and not items) else None
        return Turns(
            kind=self.kind,
            id=sid,
            started="",
            ended=ended,
            items=items,
            from_=from_off,
            offset=end,
            earlier=(from_off > 0),
            more=False,
            reset=reset,
            context=ctx,
            unknown=unknown,
        )

    def _since(self, f: Any, sid: str, size: int, after: int, tidy: Tidier) -> Turns:
        raw_lines, at, more = read_lines_forward(f, after, size, SINCE_MAX)
        lines = [_parse_transcript_line(raw, end, tidy) for raw, end in raw_lines]
        items, ended = _join_lines(lines, orphans=(after > 0))
        return Turns(
            kind=self.kind,
            id=sid,
            started="",
            ended=ended,
            items=items,
            from_=after,
            offset=at,
            earlier=(after > 0),
            more=more,
            reset=False,
            context=_context_of(lines),
            unknown=None,
        )


# ---- Multi-agent registry (Claude Code implemented; others unsupported) -----

class SessionRegistry:
    """Dispatch Sessions calls by session['kind']; unknown kinds degrade safely."""

    def __init__(self, backends: dict[str, Any]):
        self.backends = dict(backends)

    def _backend(self, session: dict[str, Any] | Path | str | None) -> tuple[str, Any | None]:
        if isinstance(session, dict):
            kind = str(session.get("kind") or "")
            return kind, self.backends.get(kind)
        if isinstance(session, (Path, str)) and str(session):
            return "claude", self.backends.get("claude")
        return "", None

    def transcript(self, session: dict[str, Any] | Path | str | None) -> Path | None:
        _, backend = self._backend(session)
        return backend.transcript(session) if backend is not None else None

    def context_tokens(self, session: dict[str, Any] | Path | str | None) -> int:
        _, backend = self._backend(session)
        return backend.context_tokens(session) if backend is not None else 0

    def turns(
        self,
        session: dict[str, Any] | Path | str | None,
        before: int | None = None,
        limit: int = DEFAULT_LIMIT,
        after: int | None = None,
    ) -> Turns:
        kind, backend = self._backend(session)
        if backend is None:
            if kind:
                raise UnsupportedSessionError(f"session kind {kind!r} is not supported")
            raise SessionNotFoundError("no session recorded")
        return backend.turns(session, before=before, limit=limit, after=after)

    def flush(self) -> None:
        for backend in self.backends.values():
            flush = getattr(backend, "flush", None)
            if callable(flush):
                flush()

    def discover_claude_task(
        self,
        task_id: str,
        folder_hint: str,
        since_ts: float,
        matcher: Callable[[str], bool],
        exclude_ids: set[str] | frozenset[str] = frozenset(),
    ) -> dict[str, Any] | None:
        backend = self.backends.get("claude")
        if backend is None or not hasattr(backend, "discover_task_session"):
            return None
        return backend.discover_task_session(task_id, folder_hint, since_ts, matcher, exclude_ids=exclude_ids)


def default_sessions(
    projects_dir: Path | Callable[[], Path] | None = None,
    home: str | Path | Callable[[], str] | None = None,
    cache_path: Path | Callable[[], Path | None] | None = None,
) -> SessionRegistry:
    """Default Sessions registry: Claude Code enabled; Codex/agy/pi unsupported."""
    return SessionRegistry({
        "claude": ClaudeSessions(projects_dir=projects_dir, home=home, cache_path=cache_path),
    })
