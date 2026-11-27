"""Sync user prompts and final PM replies from an `agy` (Antigravity CLI) PM session transcript into the project's
conversation log (`projects/<slug>/conversation.jsonl`). Layer 3.

`agy` writes each conversation turn in real time to
`<agy_dir>/brain/<conversation-id>/.system_generated/logs/transcript_full.jsonl` (and compact `transcript.jsonl`),
and indexes workspace URIs in `<agy_dir>/conversation_summaries.db`. Unlike Claude Code / Codex, `agy` does not
ship `UserPromptSubmit` / `Stop` hooks wired to `pm.py hook-turn`, so `AgyTranscriptWatcher` runs as a lightweight
`Deliverer` watcher for `kind == "agy"` PMs with zero effect on Claude/Codex/pi PMs.
"""
from __future__ import annotations

import contextlib
import datetime
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping
import urllib.parse
import urllib.request

from ..agents.sessions import HELPER_PROMPT, PM_PROMPT, PM_SESSION_MARK, REVIEW_PROMPT
from ..context import Context
from ..home import project_slug
from ..osutil import unfailing
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..project.turn_state import TurnTracker
from ..store import replace_task_file, write_atomic
from .deliver import Delivery, prompt_kind, row_time
from ..messaging.envelope import extract_env_id
from ..messaging.mailbox import PENDING_TURN

AGY_KINDS = frozenset({"agy", "antigravity"})
AGY_POLL_SECONDS = 1.5          # fallback poll interval while an agy PM is active
AGY_MAX_CURSORS = 8             # tracked conversation cursors retained in agy-transcript.json
AGY_MAX_RETIRED = 16            # retired agy conversation ids remembered across rotations
AGY_READ_CHUNK = 16 << 20       # max bytes read per tick
AGY_SCAN_DIRS = 30              # max newest brain dirs inspected when DB is absent
AGY_OPENING_LINES = 10          # max initial JSONL lines inspected to classify PM vs worker/helper
AGY_OPENING_LINE_MAX = 2 << 20  # max bytes read for a single opening line (real briefs + memory can exceed 30KB)
AGY_CLAIMED_GRACE = 15.0        # seconds of clock/startup buffer before `claimed`
AGY_FRESH_WINDOW = 120.0        # seconds within which a brand-new session replays from offset 0 on first attach

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
    r'^<hc from="[^"]+">\s*#\s*(?:任务书|Task\s+brief|Review\s+\(read-only\))'
    r"|\bReporting \(task #\d+\b"
    r"|汇报（任务 ",
    re.I,
)


def extract_agy_user_text(content: str) -> str:
    """Extract the user prompt from an `agy` `USER_INPUT` content string (stripping `<USER_REQUEST>` and trailing
    `<ADDITIONAL_METADATA>` / `<USER_SETTINGS_CHANGE>` wrappers)."""
    raw = str(content or "")
    m = _USER_REQUEST_RE.search(raw)
    if m:
        return m.group(1).strip()
    if _USER_REQUEST_OPEN_RE.match(raw):
        cleaned = _USER_REQUEST_OPEN_RE.sub("", raw, count=1)
        cleaned = _TRAILING_META_RE.sub("", cleaned)
        return cleaned.strip()
    return raw.strip()


def parse_agy_row(row: Mapping[str, Any]) -> tuple[str, str, str] | None:
    """Classify one JSONL row of an `agy` transcript as `("user_input" | "pm", text, created_at)` or `None`.

    Ignores system injections (`SYSTEM_MESSAGE`), tool results (`GENERIC`), errors (`ERROR_MESSAGE`),
    unfinished rows (`status != "DONE"`), and intermediate `PLANNER_RESPONSE` steps that carry `tool_calls`.
    """
    if not isinstance(row, Mapping):
        return None
    rtype = row.get("type")
    source = row.get("source")
    status = row.get("status")
    created_at = row.get("created_at") if isinstance(row.get("created_at"), str) else ""

    if rtype == "USER_INPUT":
        if source not in ("USER_EXPLICIT", None, ""):
            return None
        if status not in ("DONE", None, ""):
            return None
        content = row.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        text = extract_agy_user_text(content)
        return ("user_input", text, created_at) if text else None

    if rtype == "PLANNER_RESPONSE":
        if source not in ("MODEL", None, ""):
            return None
        if status not in ("DONE", None, ""):
            return None
        if row.get("tool_calls"):
            return None
        content = row.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        return ("pm", content.strip(), created_at)

    return None


def _uri_to_path(uri: str) -> Path | None:
    """Convert a `file://` URI (POSIX or Windows `file:///C:/...`) or raw path into a `Path`."""
    text = str(uri or "").strip()
    if not text:
        return None
    if text.lower().startswith("file://"):
        parsed = urllib.parse.urlparse(text)
        raw_path = urllib.request.url2pathname(parsed.path or "")
        if not raw_path:
            return None
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            raw_path = f"//{parsed.netloc}{raw_path}"
        return Path(raw_path)
    return Path(text)


def _workspace_uris_match(raw_uris: str, repo_resolved: Path) -> bool:
    if not raw_uris:
        return False
    try:
        items = json.loads(raw_uris)
    except ValueError:
        return False
    if not isinstance(items, list):
        return False
    for uri in items:
        p = _uri_to_path(str(uri or ""))
        if p is None:
            continue
        try:
            if p.resolve() == repo_resolved:
                return True
        except OSError:
            if str(p) == str(repo_resolved):
                return True
    return False


def _transcript_file_for_dir(conv_dir: Path) -> Path | None:
    logs = conv_dir / ".system_generated" / "logs"
    full = logs / "transcript_full.jsonl"
    if full.is_file():
        return full
    compact = logs / "transcript.jsonl"
    if compact.is_file():
        return compact
    return None


def _parse_claimed_time(claimed: Any) -> datetime.datetime | None:
    """Parse `rec['claimed']` (`YYYY-MM-DD HH:MM[:SS]` in local time) into a timezone-aware datetime."""
    text = str(claimed or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.datetime.strptime(text, fmt).astimezone()
        except ValueError:
            continue
    return row_time(text)


def _is_non_pm_text(text: str) -> bool:
    return bool(
        HELPER_PROMPT.search(text)
        or _EXEC_HELPER_RE.search(text)
        or REVIEW_PROMPT.search(text)
        or _WORKER_BRIEF_RE.search(text)
    )


def _is_pm_text(text: str) -> bool:
    return bool(
        PM_SESSION_MARK in text
        or PM_PROMPT.search(text)
        or "[from pm.py deliver]" in text
        or "pm.py handover" in text
    )


def _inspect_opening(path: Path) -> tuple[int, datetime.datetime | None, str]:
    """Read the initial complete JSONL lines of `path` (without mid-line truncation) and return
    `(score, first_created_at, opening_user_text)`:
    - score 0: clearly a worker brief, read-only/execution helper, reviewer, or unreadable/empty;
    - score 2: explicitly carries PM startup/takeover/delivery markers;
    - score 1: neutral user conversation (acceptable only when workspace is verified)."""
    first_at: datetime.datetime | None = None
    saw_row = False
    try:
        with open(path, "rb") as f:
            for _ in range(AGY_OPENING_LINES):
                raw = f.readline(AGY_OPENING_LINE_MAX)
                if not raw:
                    break
                if not raw.endswith(b"\n") and len(raw) >= AGY_OPENING_LINE_MAX:
                    # Single opening line exceeded AGY_OPENING_LINE_MAX: inspect prefix safely, never guess PM.
                    prefix = raw.decode("utf-8", errors="replace")
                    if _is_non_pm_text(prefix):
                        return 0, first_at, ""
                    return 0, first_at, ""
                text_line = raw.decode("utf-8", errors="replace").strip()
                if not text_line:
                    continue
                try:
                    row = json.loads(text_line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                saw_row = True
                if first_at is None:
                    first_at = row_time(row.get("created_at"))
                if row.get("type") != "USER_INPUT":
                    continue
                user_text = extract_agy_user_text(str(row.get("content") or ""))
                if not user_text:
                    continue
                if _is_non_pm_text(user_text):
                    return 0, first_at, user_text
                if _is_pm_text(user_text):
                    return 2, first_at, user_text
                return 1, first_at, user_text
    except OSError:
        return 0, None, ""
    return (1 if saw_row else 0), first_at, ""


def _opening_matches_repo(
    path: Path,
    opening_text: str,
    repo_resolved: Path,
    slug: str,
    score: int,
    *,
    repo_raw: str = "",
) -> bool:
    """When `conversation_summaries.db` is unavailable, verify that a candidate transcript explicitly references
    this project (`repo_resolved` or symlinked `repo_raw` path, or for high-confidence PM openings, its project name / `pm-<slug>`)."""
    path_variants = {str(repo_resolved), str(repo_resolved).replace("\\", "/")}
    raw_clean = str(repo_raw or "").strip().rstrip("/\\")
    if raw_clean and (raw_clean.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", raw_clean)):
        path_variants.add(raw_clean)
        path_variants.add(raw_clean.replace("\\", "/"))
    repo_name = repo_resolved.name

    def _text_matches(blob: str) -> bool:
        if not blob:
            return False
        if any(v and v in blob for v in path_variants):
            return True
        if score >= 2:
            if f"pm-{slug}" in blob:
                return True
            if repo_name and (
                f"the {repo_name} project" in blob
                or f"of {repo_name}" in blob
                or f"{repo_name} 项目" in blob
            ):
                return True
        return False

    if _text_matches(opening_text):
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(65536).decode("utf-8", errors="replace")
    except OSError:
        return False
    return _text_matches(head)


def _tail_last_created_at(path: Path) -> datetime.datetime | None:
    """Read the trailing 64 KiB of `path` and return the newest complete row's `created_at`."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size <= 0:
                return None
            start = max(0, size - 65536)
            f.seek(start)
            data = f.read(65536)
    except OSError:
        return None
    nl = data.rfind(b"\n")
    if nl < 0:
        return None
    lines = data[:nl].split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(row, dict):
            dt = row_time(row.get("created_at"))
            if dt is not None:
                return dt
    return None


def _seed_before_claimed(path: Path, claimed_dt: datetime.datetime) -> tuple[int, int | None]:
    """Scan `path` and return `(byte_offset, last_step)` right after the last row older than `claimed_dt`."""
    offset = 0
    max_step: int | None = None
    try:
        with open(path, "rb") as f:
            while True:
                line = f.readline()
                if not line or not line.endswith(b"\n"):
                    break
                try:
                    row = json.loads(line.decode("utf-8", errors="replace"))
                except ValueError:
                    offset += len(line)
                    continue
                if not isinstance(row, dict):
                    offset += len(line)
                    continue
                row_dt = row_time(row.get("created_at"))
                if row_dt is not None and row_dt >= claimed_dt:
                    break
                offset += len(line)
                step_idx = row.get("step_index")
                if isinstance(step_idx, int) and not isinstance(step_idx, bool):
                    if max_step is None or step_idx > max_step:
                        max_step = step_idx
    except OSError:
        return 0, None
    return offset, max_step


def _seed_eof(path: Path) -> tuple[int, int | None]:
    """Scan `path` in streaming fashion and return `(complete_eof_offset, max_step_index)`."""
    offset = 0
    max_step: int | None = None
    try:
        with open(path, "rb") as f:
            while True:
                line = f.readline()
                if not line or not line.endswith(b"\n"):
                    break
                offset += len(line)
                if b'"step_index"' not in line:
                    continue
                try:
                    row = json.loads(line.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(row, dict):
                    step_idx = row.get("step_index")
                    if isinstance(step_idx, int) and not isinstance(step_idx, bool):
                        if max_step is None or step_idx > max_step:
                            max_step = step_idx
    except OSError:
        return 0, None
    return offset, max_step


def _rotations_of(rec: Mapping[str, Any]) -> int:
    raw = rec.get("rotations")
    if isinstance(raw, bool):
        return 0
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


class AgyTranscriptWatcher:
    """Deliverer watcher that incrementally mirrors an `agy` PM session's user prompts and final replies into
    `projects/<slug>/conversation.jsonl`, persisting its read cursor in `projects/<slug>/agy-transcript.json`."""

    def __init__(self, ctx: Context, *, agy_dir: Path | str | None = None) -> None:
        self.ctx = ctx
        self._agy_dir = Path(agy_dir) if agy_dir is not None else None
        self._projects = ProjectRegistry(ctx)

    def _agy_root(self) -> Path:
        if self._agy_dir is not None:
            return self._agy_dir
        if self.ctx.agy_dir is not None:
            return Path(self.ctx.agy_dir)
        return Path.home() / ".gemini" / "antigravity-cli"

    def _is_agy_pm(self, rec: Mapping[str, Any]) -> bool:
        agent = str(rec.get("agent") or "").strip().lower()
        if agent in AGY_KINDS:
            return True
        if agent:
            return False  # fast-path: explicit claude / codex / pi PM never touches hc or agy files
        term = str(rec.get("terminal") or "")
        if not term:
            return False
        info = self.ctx.hc.get_raw(term) or {}
        if not isinstance(info, Mapping):
            return False
        app = str((info.get("status") or {}).get("app") or "").strip().lower()
        if app in AGY_KINDS:
            return True
        kind = str(self.ctx.agents.terminal_kind(info) or "").strip().lower()
        return kind in AGY_KINDS

    def _load_state(self, state_path: Path) -> tuple[dict[str, Any], bool]:
        if not state_path.is_file():
            return {}, False
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}, True
        return (data if isinstance(data, dict) else {}), True

    def _save_state(self, state_path: Path, state: Mapping[str, Any]) -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(
            state_path,
            (json.dumps(state, ensure_ascii=False) + "\n").encode("utf-8"),
            replace_fn=replace_task_file,
        )

    def _meets_claimed_floor(
        self,
        first_at: datetime.datetime | None,
        last_at: datetime.datetime | None,
        mtime: float,
        claimed_dt: datetime.datetime | None,
    ) -> bool:
        if claimed_dt is None:
            return True
        floor = claimed_dt - datetime.timedelta(seconds=AGY_CLAIMED_GRACE)
        effective_at = last_at or first_at
        if effective_at is not None:
            return effective_at >= floor
        return mtime >= floor.timestamp()

    def _db_candidates(
        self,
        root: Path,
        repo_resolved: Path,
        exclude: set[str],
        claimed_dt: datetime.datetime | None,
    ) -> list[tuple[int, float, str, Path, datetime.datetime | None]]:
        db_path = root / "conversation_summaries.db"
        if not db_path.is_file():
            return []
        brain = root / "brain"
        if not brain.is_dir():
            return []
        con: sqlite3.Connection | None = None
        rows: list[tuple[Any, Any]] = []
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.5)
            cur = con.cursor()
            cols = {str(r[1]) for r in cur.execute("PRAGMA table_info(conversation_summaries)")}
            clauses = ["app_data_dir IN ('antigravity-cli', '')"]
            if "nesting_depth" in cols:
                clauses.append("COALESCE(nesting_depth, 0) = 0")
            if "parent_conversation_id" in cols:
                clauses.append("COALESCE(parent_conversation_id, '') = ''")
            sql = (
                "SELECT conversation_id, workspace_uris FROM conversation_summaries "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY last_modified_time DESC LIMIT 50"
            )
            rows = list(cur.execute(sql))
        except sqlite3.Error:
            return []
        finally:
            if con is not None:
                with contextlib.suppress(sqlite3.Error):
                    con.close()
        found: list[tuple[int, float, str, Path, datetime.datetime | None]] = []
        for conv_id, raw_uris in rows:
            cid = str(conv_id or "").strip()
            if not cid or cid in exclude:
                continue
            if not _workspace_uris_match(str(raw_uris or ""), repo_resolved):
                continue
            tp = _transcript_file_for_dir(brain / cid)
            if tp is None:
                continue
            try:
                mtime = tp.stat().st_mtime
            except OSError:
                continue
            score, first_at, _ = _inspect_opening(tp)
            if score <= 0:
                continue
            last_at = _tail_last_created_at(tp) if claimed_dt is not None else None
            if not self._meets_claimed_floor(first_at, last_at, mtime, claimed_dt):
                continue
            found.append((score, mtime, cid, tp, first_at))
        return found

    def _fs_candidates(
        self,
        root: Path,
        repo_resolved: Path,
        slug: str,
        exclude: set[str],
        claimed_dt: datetime.datetime | None,
        *,
        repo_raw: str = "",
    ) -> list[tuple[int, float, str, Path, datetime.datetime | None]]:
        brain = root / "brain"
        if not brain.is_dir():
            return []
        entries: list[tuple[float, str, Path]] = []
        try:
            dirs = list(brain.iterdir())
        except OSError:
            return []
        for d in dirs:
            if not d.is_dir() or d.name in exclude:
                continue
            tp = _transcript_file_for_dir(d)
            if tp is None:
                continue
            try:
                mtime = tp.stat().st_mtime
            except OSError:
                continue
            entries.append((mtime, d.name, tp))
        entries.sort(key=lambda item: item[0], reverse=True)
        found: list[tuple[int, float, str, Path, datetime.datetime | None]] = []
        for mtime, cid, tp in entries[:AGY_SCAN_DIRS]:
            score, first_at, opening_text = _inspect_opening(tp)
            if score <= 0:
                continue
            last_at = _tail_last_created_at(tp) if claimed_dt is not None else None
            if not self._meets_claimed_floor(first_at, last_at, mtime, claimed_dt):
                continue
            if not _opening_matches_repo(tp, opening_text, repo_resolved, slug, score, repo_raw=repo_raw):
                continue
            found.append((score, mtime, cid, tp, first_at))
        return found

    def _discover_transcript(
        self,
        repo: str,
        rec: Mapping[str, Any],
        state: Mapping[str, Any],
    ) -> tuple[str, Path, datetime.datetime | None, list[str]] | None:
        root = self._agy_root()
        pane = str(rec.get("pane") or "")
        claimed = str(rec.get("claimed") or "")
        claimed_dt = _parse_claimed_time(claimed)
        retired = [str(x) for x in (state.get("retired") or []) if isinstance(x, str)]
        exclude: set[str] = set(retired)
        for sid in (rec.get("retired_sessions") or []):
            if isinstance(sid, str) and sid:
                exclude.add(sid)
        prev = rec.get("previous")
        if isinstance(prev, Mapping):
            prev_sess = prev.get("agent_session")
            if isinstance(prev_sess, Mapping) and isinstance(prev_sess.get("id"), str) and prev_sess["id"]:
                exclude.add(prev_sess["id"])

        cached = state.get("session") if isinstance(state.get("session"), Mapping) else {}
        cached_id = str(cached.get("id") or "")
        rotations = _rotations_of(rec)
        same_binding = bool(
            cached_id
            and cached.get("pane") == pane
            and cached.get("claimed") == claimed
            and ("rotations" not in cached or _rotations_of(cached) == rotations)
        )

        # Rotation or re-claim: retire the previously bound session id so discovery picks the successor.
        if cached_id and not same_binding and cached_id not in exclude:
            exclude.add(cached_id)
            retired.append(cached_id)

        # Sticky binding: once bound to a valid PM session for this (pane, claimed), never let global DB
        # changes (e.g. dispatching a helper or worker) hijack the binding. Resolve transcript_full.jsonl vs
        # transcript.jsonl fresh for the same conversation_id so upgrading compact -> full is seamless.
        if same_binding and cached_id not in exclude:
            bound_path = _transcript_file_for_dir(root / "brain" / cached_id)
            if bound_path is None and cached.get("path"):
                fallback = Path(str(cached["path"]))
                if fallback.is_file():
                    bound_path = fallback
            if bound_path is not None:
                return cached_id, bound_path, None, retired[-AGY_MAX_RETIRED:]

        try:
            repo_resolved = Path(repo).resolve()
        except OSError:
            repo_resolved = Path(repo)
        slug = project_slug(repo)

        db_exists = (root / "conversation_summaries.db").is_file()
        candidates = self._db_candidates(root, repo_resolved, exclude, claimed_dt) if db_exists else []
        if not candidates and not db_exists:
            candidates = self._fs_candidates(root, repo_resolved, slug, exclude, claimed_dt, repo_raw=repo)
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, cid, path, first_at = candidates[0]
        return cid, path, first_at, retired[-AGY_MAX_RETIRED:]

    def _conversation_has_recent_turns(self, repo: str, since: datetime.datetime | None) -> bool:
        conv = Conversation(self.ctx, repo)
        events = conv.events()
        if not events:
            return False
        floor = since.astimezone().strftime("%Y-%m-%d %H:%M:%S") if since is not None else ""
        for e in reversed(events[-100:]):
            if e.get("type") not in ("user", "pm"):
                continue
            if not floor or str(e.get("at") or "") >= floor:
                return True
        return False

    def _should_seed_eof(
        self,
        repo: str,
        path: Path,
        first_at: datetime.datetime | None,
        claimed_dt: datetime.datetime | None,
        state_existed: bool,
    ) -> bool:
        """Whether a newly seen conversation_id should start from EOF (avoiding replaying historical turns)
        rather than offset 0. Only brand-new sessions created for this claim/rotation replay from offset 0."""
        grace = datetime.timedelta(seconds=AGY_CLAIMED_GRACE)
        if first_at is not None and claimed_dt is not None and first_at < claimed_dt - grace:
            return True
        if not state_existed:
            now_ts = self.ctx.clock.time()
            try:
                ref_ts = first_at.timestamp() if first_at is not None else path.stat().st_mtime
            except OSError:
                ref_ts = 0.0
            if ref_ts > 0 and (now_ts - ref_ts) > AGY_FRESH_WINDOW:
                return True
            if self._conversation_has_recent_turns(repo, first_at):
                return True
        return False

    def sync(self, repo: str | Path, rec: Mapping[str, Any] | None = None) -> int:
        """Read any new complete lines from the active `agy` PM transcript and record user prompts and final PM
        replies into `conversation.jsonl`. Returns the number of events recorded."""
        repo_str = str(repo)
        if not repo_str:
            return 0
        pm_rec = rec if rec is not None else self._projects.app_pm(repo_str)
        if not pm_rec or not self._is_agy_pm(pm_rec):
            return 0

        proj = self.ctx.home.project_for(repo_str)
        state_path = proj.agy_transcript
        state, state_existed = self._load_state(state_path)
        found = self._discover_transcript(repo_str, pm_rec, state)
        if found is None:
            return 0
        conv_id, path, first_at, retired = found
        path_str = str(path)

        try:
            size = path.stat().st_size
        except OSError:
            return 0

        raw_cursors = state.get("cursors") if isinstance(state.get("cursors"), dict) else {}
        cursors: dict[str, dict[str, Any]] = {
            str(k): dict(v) for k, v in raw_cursors.items() if isinstance(k, str) and isinstance(v, dict)
        }
        # Migrate v1 path-keyed entries if present so upgrades do not lose last_step.
        if conv_id not in cursors and isinstance(state.get("files"), dict):
            legacy = state["files"].get(path_str)
            if isinstance(legacy, dict):
                cursors[conv_id] = {**legacy, "path": path_str}

        claimed_dt = _parse_claimed_time(pm_rec.get("claimed"))
        entry = cursors.get(conv_id)
        recorded = 0

        if entry is None:
            grace = datetime.timedelta(seconds=AGY_CLAIMED_GRACE)
            pre_opened_claim = (
                first_at is not None and claimed_dt is not None and first_at < claimed_dt - grace
            )
            # First time seeing this conversation_id:
            # - If it is an old historical session (> AGY_FRESH_WINDOW since last activity), seed at EOF;
            # - If it was opened minutes before `pm.py claim` and is actively chatting now, skip rows older
            #   than `claimed_dt` and immediately sync any turns sent after `claim`!
            last_row_at = _tail_last_created_at(path)
            now_ts = self.ctx.clock.time()
            last_age = (now_ts - last_row_at.timestamp()) if last_row_at is not None else (AGY_FRESH_WINDOW + 1)
            if pre_opened_claim and claimed_dt is not None and last_age <= AGY_FRESH_WINDOW:
                offset, last_step = _seed_before_claimed(path, claimed_dt)
                turn_cause = None
                pending_system_turn = False
            elif self._should_seed_eof(repo_str, path, first_at, claimed_dt, state_existed):
                eof_offset, max_step = _seed_eof(path)
                cursors.pop(conv_id, None)
                cursors[conv_id] = {
                    "path": path_str,
                    "offset": eof_offset,
                    "last_step": max_step,
                    "turn_cause": None,
                }
                fresh_seed: dict[str, Any] = {
                    "version": 2,
                    "session": {
                        "id": conv_id,
                        "pane": str(pm_rec.get("pane") or ""),
                        "claimed": str(pm_rec.get("claimed") or ""),
                        "rotations": _rotations_of(pm_rec),
                    },
                    "retired": retired[-AGY_MAX_RETIRED:],
                    "cursors": dict(list(cursors.items())[-AGY_MAX_CURSORS:]),
                }
                with contextlib.suppress(OSError):
                    self._save_state(state_path, fresh_seed)
                return 0
            else:
                offset = 0
                last_step = None
                turn_cause = None
                pending_system_turn = False
        else:
            prev_path = str(entry.get("path") or "")
            raw_off = entry.get("offset")
            if prev_path != path_str:
                # Same conversation_id switched between transcript.jsonl and transcript_full.jsonl:
                # reset byte offset to 0 for the new file while preserving last_step and turn_cause.
                offset = 0
            elif not isinstance(raw_off, int) or isinstance(raw_off, bool) or raw_off < 0 or raw_off > size:
                offset = 0
            else:
                offset = raw_off
            raw_step = entry.get("last_step")
            last_step = raw_step if isinstance(raw_step, int) and not isinstance(raw_step, bool) else None
            turn_cause = entry.get("turn_cause") if isinstance(entry.get("turn_cause"), dict) else None
            pending_system_turn = bool(entry.get("pending_system_turn"))

        new_offset = offset
        if size > offset:
            to_read = min(size - offset, AGY_READ_CHUNK)
            try:
                with open(path, "rb") as f:
                    f.seek(offset)
                    data = f.read(to_read)
            except OSError:
                return 0
            nl = data.rfind(b"\n")
            if nl >= 0:
                complete = data[:nl + 1]
                new_offset = offset + len(complete)
                conv = Conversation(self.ctx, repo_str)
                delivery = Delivery(self.ctx, repo_str)
                tracker = TurnTracker(self.ctx, repo_str)
                pane = str(pm_rec.get("pane") or "")
                term = str(pm_rec.get("terminal") or (pane[3:] if pane.startswith("hc:") else ""))
                term_working_cache: tuple[bool, int] | None = None

                def _term_working_state() -> tuple[bool, int]:
                    nonlocal term_working_cache
                    if term_working_cache is not None:
                        return term_working_cache
                    if not term:
                        term_working_cache = (False, 0)
                        return term_working_cache
                    tinfo = self.ctx.hc.get_raw(term)
                    if isinstance(tinfo, Mapping) and tinfo.get("state") == "live":
                        raw_s = tinfo.get("status")
                        s_val = str(raw_s.get("state") or "") if isinstance(raw_s, Mapping) else str(raw_s or "")
                        s_ms = int(tinfo.get("status_ms") or 0)
                        term_working_cache = (s_val == "working", s_ms)
                    else:
                        term_working_cache = (False, 0)
                    return term_working_cache

                for raw_line in complete.split(b"\n")[:-1]:
                    if not raw_line.strip():
                        continue
                    try:
                        row = json.loads(raw_line.decode("utf-8", errors="replace"))
                    except ValueError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    step_idx = row.get("step_index")
                    has_step = isinstance(step_idx, int) and not isinstance(step_idx, bool)
                    if has_step and last_step is not None and step_idx <= last_step:
                        continue
                    rtype = row.get("type")
                    row_dt_meta = row_time(row.get("created_at"))
                    row_ms_meta = int(row_dt_meta.timestamp() * 1000) if row_dt_meta is not None else int(self.ctx.clock.time() * 1000)
                    if rtype == "SYSTEM_MESSAGE":
                        pending_system_turn = True
                        unfailing(
                            lambda rms=row_ms_meta: tracker.append_observation(
                                {"src": "watcher:agy", "kind": "step_system", "t": rms},
                                reduce_now=True,
                            )
                        )
                        if has_step:
                            last_step = step_idx
                        continue
                    if rtype == "PLANNER_RESPONSE" and row.get("source") in ("MODEL", None, "") and pending_system_turn:
                        pending_system_turn = False
                        if tracker.read().get("phase") not in ("working", "stalled"):
                            turn_cause = None
                            unfailing(
                                lambda: tracker.begin_turn(
                                    terminal=pane, agent_kind="agy", cause="self", from_hook=True,
                                )
                            )
                    parsed = parse_agy_row(row)
                    if parsed is not None:
                        role, raw_text, created_at = parsed
                        row_dt = row_time(created_at)
                        at = row_dt.astimezone().strftime("%Y-%m-%d %H:%M:%S") if row_dt is not None else None
                        if role == "user_input":
                            pending_system_turn = False
                            kind, sender, text = prompt_kind(raw_text)
                            if kind == "batch":
                                receipt = delivery.took_delivery(text, late=True)
                                turn_cause = {"after": "deliver", "batch": [receipt.start, receipt.end]}
                                unfailing(
                                    lambda r=receipt: tracker.begin_turn(
                                        terminal=pane, agent_kind="agy", cause="deliver",
                                        batch=[r.start, r.end], from_hook=True,
                                    )
                                )
                            elif kind == "rotate" or kind == "other":
                                turn_cause = None
                            elif kind == "supervisor":
                                turn_cause = None
                                orig_cause = ""
                                orig_mids: list[str] = []
                                orig_batch: list[int] | None = None
                                env_hit = extract_env_id(raw_text)
                                if env_hit and tracker.files.pm_mailbox.is_dir():
                                    it = tracker.pm_mailbox.get(env_hit)
                                    if it is not None:
                                        eb = it.envelope.body if isinstance(it.envelope.body, Mapping) else {}
                                        ec = it.envelope.cause if isinstance(it.envelope.cause, Mapping) else {}
                                        orig_cause = str(eb.get("original_cause") or ec.get("original_cause") or "")
                                        orig_mids = [str(m) for m in (eb.get("msg_ids") or ec.get("msg_ids") or []) if m]
                                        if it.state in ("typed", "accepted"):
                                            tracker.pm_mailbox.transition(
                                                env_hit, "consumed", turn_id=PENDING_TURN, clear_intent=True,
                                            )
                                st_inc = tracker.read().get("incident") if tracker.files.pm_turn.is_file() else None
                                if isinstance(st_inc, Mapping):
                                    if not orig_cause:
                                        orig_cause = str(st_inc.get("cause_kind") or "")
                                    if not orig_mids:
                                        orig_mids = [str(m) for m in (st_inc.get("msg_ids") or []) if m]
                                    if isinstance(st_inc.get("batch"), list) and len(st_inc["batch"]) == 2:
                                        orig_batch = [int(st_inc["batch"][0]), int(st_inc["batch"][1])]
                                eff_cause = orig_cause if orig_cause in ("user", "deliver") else "recovery"
                                if eff_cause == "deliver" and orig_batch:
                                    turn_cause = {"after": "deliver", "batch": orig_batch}
                                elif eff_cause == "user":
                                    turn_cause = {"after": "user"}
                                unfailing(
                                    lambda c=eff_cause, mids=orig_mids or None, b=orig_batch: tracker.begin_turn(
                                        terminal=pane, agent_kind="agy", cause=c, msg_ids=mids, batch=b, from_hook=True,
                                    )
                                )
                            elif kind == "agent":
                                turn_cause = None
                                unfailing(lambda: tracker.begin_turn(terminal=pane, agent_kind="agy", cause="agent", from_hook=True))
                                if text:
                                    conv.record("agent", at=at, by=sender, text=text)
                                    recorded += 1
                            elif kind == "user":
                                turn_cause = None
                                if text:
                                    consumed, matched_ids, remainder = tracker.consume_ui_prompt(text)
                                    unfailing(
                                        lambda m_ids=matched_ids: tracker.begin_turn(
                                            terminal=pane, agent_kind="agy", cause="user",
                                            msg_ids=m_ids, from_hook=True,
                                        )
                                    )
                                    if not consumed and remainder:
                                        conv.record("user", at=at, text=remainder)
                                        recorded += 1
                        elif role == "pm":
                            extra: dict[str, Any] = {}
                            if pane:
                                extra["by"] = pane
                            tracker_cause = tracker.end_turn(has_reply=True)
                            if turn_cause:
                                extra.update(turn_cause)
                            elif tracker_cause:
                                extra.update(tracker_cause)
                            conv.record("pm", at=at, text=raw_text, **extra)
                            recorded += 1
                    elif rtype == "PLANNER_RESPONSE" and row.get("tool_calls"):
                        tcalls = row.get("tool_calls")
                        if isinstance(tcalls, list) and tcalls and isinstance(tcalls[-1], Mapping):
                            tname = str(tcalls[-1].get("name") or "tool")
                            targs = tcalls[-1].get("args") if isinstance(tcalls[-1].get("args"), Mapping) else {}
                            tsum = str(targs.get("toolSummary") or targs.get("CommandLine") or targs.get("Path") or "")
                            preamble = " ".join(str(row.get("thinking") or row.get("content") or "").split())[:120]
                            tw, tms = _term_working_state()
                            unfailing(
                                lambda tn=tname, ts=tsum, w=tw, s=tms, pre=preamble: tracker.note_activity(
                                    kind="tool", tool=tn, summary=ts, terminal_working=w, status_ms=s,
                                    preamble=pre, src="watcher:agy",
                                )
                            )
                    elif rtype == "GENERIC":
                        if tracker.read().get("phase") in ("working", "stalled"):
                            unfailing(lambda: tracker.note_activity(kind="thinking", src="watcher:agy"))
                    elif rtype == "ERROR_MESSAGE":
                        # FS-7: ERROR_MESSAGE does not end the turn (agy retries and continues).
                        err_msg = str(row.get("content") or row.get("error") or row.get("message") or "error")[:200]
                        unfailing(
                            lambda msg=err_msg, rms=row_ms_meta: tracker.append_observation(
                                {"src": "watcher:agy", "kind": "step_error", "t": rms, "message": msg},
                                reduce_now=True,
                            )
                        )
                    if has_step:
                        last_step = step_idx

        cursors.pop(conv_id, None)
        cursor_entry: dict[str, Any] = {
            "path": path_str,
            "offset": new_offset,
            "last_step": last_step,
            "turn_cause": turn_cause,
        }
        if pending_system_turn:
            cursor_entry["pending_system_turn"] = True
        cursors[conv_id] = cursor_entry
        fresh: dict[str, Any] = {
            "version": 2,
            "session": {
                "id": conv_id,
                "pane": str(pm_rec.get("pane") or ""),
                "claimed": str(pm_rec.get("claimed") or ""),
                "rotations": _rotations_of(pm_rec),
            },
            "retired": retired[-AGY_MAX_RETIRED:],
            "cursors": dict(list(cursors.items())[-AGY_MAX_CURSORS:]),
        }
        if fresh != state:
            with contextlib.suppress(OSError):
                self._save_state(state_path, fresh)
        return recorded

    def watched_files(self, repo: str | Path) -> list[Path]:
        """Return the currently bound `agy` transcript path (if any) so `ChangeWaiter` wakes immediately on writes."""
        repo_str = str(repo or "")
        if not repo_str:
            return []
        state_path = self.ctx.home.project_for(repo_str).agy_transcript
        state, existed = self._load_state(state_path)
        if not existed:
            return []
        cid = str((state.get("session") or {}).get("id") or "")
        cursors = state.get("cursors") if isinstance(state.get("cursors"), Mapping) else {}
        cpath = str((cursors.get(cid) or {}).get("path") or "")
        if cpath:
            p = Path(cpath)
            if p.is_file():
                return [p]
        return []

    def look(self, repo: str | Path, stops: Any, bases: Any = None) -> float | None:
        """Called from `Deliverer.look`: sync `agy` PM transcript turns into `conversation.jsonl`.
        Fast-path returns `None` immediately for non-`agy` PMs."""
        if not repo:
            return None
        repo_str = str(repo)
        rec = self._projects.app_pm(repo_str)
        if not rec or not self._is_agy_pm(rec):
            return None
        unfailing(self.sync, repo_str, rec)
        return AGY_POLL_SECONDS
