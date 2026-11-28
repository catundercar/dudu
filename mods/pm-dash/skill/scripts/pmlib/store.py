"""Ledger store: registrations, tasks, atomic locked writes, and byte-anchored conversation windows.

Paths are fetched from a caller-supplied provider on every call rather than computed
at import time, so tests that redirect pm.STATE/TASKS/PMS/PROJECTS and `--home` flags
parsed after import always take effect. This module never imports `pm`.
"""
from __future__ import annotations

import contextlib
import datetime
import errno
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol

LINE_MAX = 16 << 20        # 16 MiB bound on one JSONL line; longer lines are skipped
BLOCK_SIZE = 64 << 10      # 64 KiB read chunk for forward and reverse line scans

from . import context, home as home_mod  # noqa: E402 - after LINE_MAX/BLOCK_SIZE so transcripts can import them during cycles
from .errors import StoreError, VersionConflict
from .home import project_slug
from .terminals.events import replace_task_file

try:
    import fcntl
except ImportError:  # Windows: file locks go through msvcrt (lock_file below)
    fcntl = None
    import msvcrt

SLUG_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")
JSON_FILE_MAX = 16 << 20   # 16 MiB bound on one registration or task JSON file
WINDOW_MAX = 2000          # maximum events returned in one window
WINDOW_BYTES = 32 << 20    # byte cap on events in one window
SINCE_BYTES = 4 << 20      # byte budget scanned in one incremental `after` call
LOCK_TIMEOUT = 10.0        # default seconds to wait for a per-file ledger lock
DOCUMENT_MAX = 1_000_000   # 1 MB bound on one context document read whole as text
MEMORY_HEAD_MAX = 64 << 10 # 64 KiB cap when inspecting a memory file's frontmatter
DOCUMENTS_MAX = 5000       # maximum entries listed per context root
REPO_FILES_MAX = 20_000    # maximum repository files listed for @ mentions
NON_GIT_FILES_MAX = 2_000  # hard cap on files walked in a single non-Git workspace folder
NON_GIT_SKIP_DIRS = frozenset({
    "node_modules", "dist", "build", "target", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".next", ".nuxt", "coverage", "vendor",
})
# Roots a document is named under (`<root>/<path>`). `project`, `user` and `research` are the old Context
# panel's (`project context`, kept for the UI until it moves); `docs` and `research` are the Library's;
# `memory` (the project's) and `personal` (the user's) are the Memory page's; `repo` is read-only preview of
# the project's linked folders.
DOCUMENT_ROOTS = ("project", "user", "research", "docs", "repo_docs", "instructions", "memory", "personal", "repo")
LIBRARY_ROOTS = ("docs", "research")
RESEARCH_FOLDER = "evidence"
LEDGER_RESEARCH_FOLDER = "research"
RESEARCH_FILENAME = "README.md"
RESEARCH_TITLE_MAX = 200
RESEARCH_SUMMARY_MAX = 280
RENDER_CHECK_MARKER = ".render-check"
ATTACHMENTS_FOLDER = "attachments"
DOCS_FOLDER = "docs"               # projects/<slug>/docs: the project's own documents, editable from the Library
DOCS_RESEARCH = "research"         # projects/<slug>/docs/research: reports' new home (research-reports-home)
PUBLISHED_PREFIX = "published"     # research/published/<rel>: <repo>/docs/research/<rel>, the redacted public copies
HISTORY_FOLDER = ".history"        # what a document said before it was replaced or deleted
DECISIONS_FILE = "decisions.md"    # the decisions log, shown last in the Library as an archive
LIBRARY_STATE_FILE = "library.json"            # {"decisions": {"hidden": true, ...}, "repo_docs": {...}}
RESEARCH_SOURCES_FILE = "research-sources.json"  # {"evidence/<topic>/README.md": "<task id>"}, by collect_research
TASK_SEQ_FILE = "task-seq.json"                  # {"last": N}: per-project monotonic task number counter
INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md",
                     ".claude/CLAUDE.md", ".claude/coordination.md")
INSTRUCTION_RULES = (".claude", "rules")       # .claude/rules/*.md
ADD_MAX = 20 << 20                 # 20 MiB bound on one file dropped into the Library
RESEARCH_DEPTH = 4                 # how deep docs/research is listed
REPO_DOCS_DEPTH = 4                # max relative depth under each repo_docs entry directory
REPO_DOCS_MAX = 200                # hard cap on repo_docs files returned in Library
REPO_DOC_EXTENSIONS = frozenset({".md", ".markdown", ".mdx", ".rst", ".adoc"})
REPO_DOCS_DEFAULT_ROOT_DIRS = ("design", "specs", "adr", "rfcs", "architecture")
REPO_DOCS_DEFAULT_ROOT_FILES = frozenset({"architecture.md", "design.md"})
REPO_DOCS_DESIGN_SEGMENTS = frozenset({
    "design", "specs", "spec", "adr", "decisions", "rfcs", "rfc", "architecture",
})
REPO_DOCS_SKIP_DIRS = frozenset({
    "node_modules", "vendor", "dist", "build", "out", "target",
    "public", "static", "assets", "images", "img", "media", "videos", "fonts",
    "styles", "stylesheets", "scripts", "theme", "themes",
    "versioned_docs", "versioned_sidebars", "i18n", "locales", "translations",
    "fixtures", "testdata",
})
REPO_DOCS_SKIP_FILES = frozenset({
    "changelog.md", "history.md", "releases.md", "contributing.md",
    "code_of_conduct.md", "license.md", "security.md",
    "pull_request_template.md", "issue_template.md",
})
DRAFT_PREFIX_RE = re.compile(r"^(?:draft|wip|rfc|proposal)[-_]+", re.I)
DRAFT_SUFFIX_RE = re.compile(r"[-_]+(?:draft|wip|rfc|proposal|old|bak|v\d+)$", re.I)
GENERIC_DOC_STEMS = frozenset({
    "readme", "index", "notes", "todo", "changelog", "history", "license",
    "contributing", "security",
})
INTERNAL_PROJECT_FILES = frozenset({
    "conversation.jsonl", "receipts.json", "receipts.lock", "delivered.json", "delivered.lock", "deliver.lock",
    "turn-cause.json", "taken-in.json", "takeover.json", "pm-settings.json",
    "schedules.json", "dudu-attachments.json", LIBRARY_STATE_FILE, RESEARCH_SOURCES_FILE,
    TASK_SEQ_FILE, "seat.json", "seat.lock", "next-session.json", "agy-transcript.json",
    "pm-turn.json", "pm-turn.lock", "pm-turn-journal.jsonl", "pm-turn-journal.1.jsonl", "pm-turn.beat",
    "applied-reports.json", "applied-reports.lock", "applied-reports.jsonl", "applied-reports.0001.jsonl",
    "mailboxes",
})
IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif",
})
TEXT_EXTENSIONS = frozenset({
    ".md", ".markdown", ".txt", ".text", ".log", ".json", ".jsonl", ".ndjson",
    ".csv", ".tsv", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml",
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".go", ".rs", ".rb", ".java", ".kt", ".swift", ".c", ".h", ".cc",
    ".cpp", ".hpp", ".cs", ".php", ".lua", ".sh", ".bash", ".zsh", ".fish",
    ".ps1", ".bat", ".sql", ".diff", ".patch", ".tex", ".rst", ".org", ".adoc",
    ".mod", ".sum", ".lock",
})
ADD_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | frozenset({".pdf", ".svg"})
MEMORY_TYPES = ("user", "feedback", "project", "reference", "pitfall")
HISTORY_NAME_RE = re.compile(r"^(?P<name>.+)\.(?P<stamp>\d{8}-\d{6}(?:-\d+)?)\.(?P<why>deleted|replaced)$")
TASK_LINE_RE = re.compile(r"(?:任务|[Tt]ask)\**\s*[：:]\s*\**\s*`([^`\s]+)`")
ISO_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SYMLINK_OPEN_ERRNOS = frozenset(
    code for code in (getattr(errno, "ELOOP", None), getattr(errno, "EMLINK", None), getattr(errno, "EFTYPE", None))
    if code is not None
)


class LockTimeoutError(TimeoutError, StoreError):
    """Could not acquire a ledger lock before its deadline."""


class DamagedFileError(ValueError, StoreError):
    """A ledger file or document exists but is invalid, non-text, too large, or not a regular file."""


class UnreadableFileError(OSError, StoreError):
    """A ledger file, folder, or document exists but could not be read due to an OS error (such as permissions)."""


class LogReplacedError(ValueError):
    """The conversation log is shorter than or incompatible with the byte anchor."""


def lock_file(f, shared: bool = False) -> None:
    """Take a non-blocking lock on the open file f for the life of the handle; OSError when another process holds
    one. Windows has no shared locks and locks bytes, so one byte far past the pid the file holds is locked."""
    if fcntl is not None:
        fcntl.flock(f, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        return
    where = f.tell()
    f.seek(1 << 20)
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    finally:
        f.seek(where)


def unlock_file(f) -> None:
    """Give back lock_file's lock before closing f (Windows frees it at close only eventually)."""
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_UN)
        return
    f.seek(1 << 20)
    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def file_lock(
    lock_path: Path,
    timeout: float = LOCK_TIMEOUT,
    *,
    lock_fn=lock_file,
    unlock_fn=unlock_file,
) -> Iterator[None]:
    """Acquire an exclusive lock on `lock_path` until `timeout` seconds elapse, then release on exit.

    The lock file itself is never unlinked (unlinking while another process holds or awaits the lock
    breaks POSIX flock mutual exclusion by creating a new inode for the next caller).
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+")
    acquired = False
    try:
        deadline = time.monotonic() + max(0.0, float(timeout))
        delay = 0.005
        while True:
            try:
                lock_fn(f)
                acquired = True
                break
            except OSError as err:
                now_m = time.monotonic()
                if now_m >= deadline:
                    raise LockTimeoutError(
                        f"timed out after {timeout:.1f}s waiting for lock {lock_path}"
                    ) from err
                time.sleep(min(delay, max(0.0, deadline - now_m)))
                delay = min(delay * 1.5, 0.05)
        yield
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                unlock_fn(f)
        with contextlib.suppress(OSError):
            f.close()


def _replace_file(source: Path, target: Path) -> None:
    """Atomically replace target with source, retrying transient Windows sharing errors."""
    for attempt in range(6):
        try:
            source.replace(target)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 5:
                raise
            time.sleep(0.02 * (attempt + 1))


def _sync_dir(folder: Path) -> None:
    """Best-effort fsync of a directory so a rename is durable (POSIX only)."""
    if os.name == "nt":
        return
    try:
        dfd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


def write_atomic(path: Path, data: bytes, *, replace_fn=None) -> None:
    """Write `data` to a unique per-process hidden temp file in `path.parent`, fsync, and replace `path`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.{os.getpid()}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if os.name != "nt":
            try:
                mode = stat.S_IMODE(os.stat(path).st_mode)
            except OSError:
                mode = 0o644
            with contextlib.suppress(OSError):
                os.chmod(tmp_path, mode)
        (replace_fn or _replace_file)(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)
    _sync_dir(path.parent)


def valid_slug(slug: object) -> bool:
    return isinstance(slug, str) and bool(SLUG_RE.match(slug))


def valid_task_id(task_id: object) -> bool:
    return (isinstance(task_id, str) and bool(task_id) and not task_id.startswith(".")
            and ".." not in task_id and "/" not in task_id and "\\" not in task_id
            and "\x00" not in task_id)


def valid_task_number(value: object) -> int | None:
    """Return positive integer task number, rejecting booleans and non-positive values."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


FOLDER_ALIAS_MAX_LEN = 64


def normalize_folder_alias(raw: object) -> str:
    """Validate and normalize a workspace folder alias."""
    if not isinstance(raw, str):
        raise ValueError("folder alias must be a string")
    alias = raw.strip()
    if not alias:
        raise ValueError("folder alias cannot be empty")
    if len(alias) > FOLDER_ALIAS_MAX_LEN:
        raise ValueError(f"folder alias is too long (max {FOLDER_ALIAS_MAX_LEN} characters)")
    if alias in (".", "..") or alias.startswith("."):
        raise ValueError(f"folder alias cannot start with '.': {alias!r}")
    if "/" in alias or "\\" in alias or "\x00" in alias or any(ord(ch) < 32 or ord(ch) == 127 for ch in alias):
        raise ValueError(f"invalid folder alias: {alias!r}")
    return alias


def registration_slug(rec: Mapping[str, Any] | None, stem: str = "") -> str:
    """Canonical project slug for a registration record (`slug` -> `project_slug(repo)` -> `pm-<slug>` -> `stem`)."""
    if isinstance(rec, Mapping):
        raw_slug = rec.get("slug")
        if valid_slug(raw_slug):
            return str(raw_slug)
        raw_repo = rec.get("repo")
        if isinstance(raw_repo, str) and raw_repo:
            return project_slug(raw_repo)
        name = str(rec.get("name") or "")
        if name.startswith("pm-") and valid_slug(name[3:]):
            return name[3:]
    return stem if valid_slug(stem) else ""


def project_folders(rec: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Equal-status reader for a project's linked workspace folders (`0..N`), compatible with legacy `repo`."""
    if not isinstance(rec, Mapping):
        return []
    raw_folders = rec.get("folders")
    if "folders" in rec and isinstance(raw_folders, list):
        out: list[dict[str, Any]] = []
        for item in raw_folders:
            if not isinstance(item, Mapping):
                continue
            path_str = str(item.get("path") or "").strip()
            if not path_str:
                continue
            alias = str(item.get("alias") or "").strip() or Path(path_str).name or "folder"
            entry: dict[str, Any] = {"path": path_str, "alias": alias}
            if "git" in item and item["git"] is not None:
                entry["git"] = bool(item["git"])
            if item.get("default_branch"):
                entry["default_branch"] = str(item["default_branch"])
            out.append(entry)
        return out
    raw_repo = str(rec.get("repo") or "").strip()
    if raw_repo:
        return [{"path": raw_repo, "alias": Path(raw_repo).name or "repo"}]
    return []


def sync_registration_folders(
    rec: dict[str, Any],
    folders: list[dict[str, Any]],
    *,
    slug: str = "",
) -> dict[str, Any]:
    """Persist equal-status `folders[]` on a registration dict and mirror `repo` (`folders[0].path` or '')."""
    cleaned: list[dict[str, Any]] = []
    for item in folders:
        if not isinstance(item, Mapping):
            continue
        path_str = str(item.get("path") or "").strip()
        if not path_str:
            continue
        alias = str(item.get("alias") or "").strip() or Path(path_str).name or "folder"
        entry: dict[str, Any] = {"path": path_str, "alias": alias}
        if "git" in item and item["git"] is not None:
            entry["git"] = bool(item["git"])
        if item.get("default_branch"):
            entry["default_branch"] = str(item["default_branch"])
        cleaned.append(entry)
    rec["folders"] = cleaned
    rec["repo"] = cleaned[0]["path"] if cleaned else ""
    if slug and valid_slug(slug):
        rec["slug"] = slug
    return rec


def disambiguate_folder_alias(
    path: Path,
    existing_aliases: Iterable[str],
    explicit_alias: str | None = None,
) -> str:
    """Choose a unique, valid folder alias within a project."""
    taken = {str(a).casefold() for a in existing_aliases if a}
    if explicit_alias is not None:
        alias = normalize_folder_alias(explicit_alias)
        if alias.casefold() in taken:
            raise ValueError(f"folder alias {alias!r} already exists in this project")
        return alias
    raw_base = (path.name or "").strip().replace("/", "-").replace("\\", "-").lstrip(".")
    raw_base = "".join(ch for ch in raw_base if ord(ch) >= 32 and ord(ch) != 127)
    base = (raw_base or "folder")[:FOLDER_ALIAS_MAX_LEN]
    base = normalize_folder_alias(base)
    if base.casefold() not in taken:
        return base
    parent_raw = (path.parent.name if path.parent != path else "").strip().replace("/", "-").replace("\\", "-").lstrip(".")
    parent_raw = "".join(ch for ch in parent_raw if ord(ch) >= 32 and ord(ch) != 127)
    if parent_raw:
        cand = f"{parent_raw}-{base}"[:FOLDER_ALIAS_MAX_LEN]
        try:
            cand = normalize_folder_alias(cand)
        except ValueError:
            cand = ""
        if cand and cand.casefold() not in taken:
            return cand
    n = 2
    while True:
        suffix = f"-{n}"
        cand = base[:FOLDER_ALIAS_MAX_LEN - len(suffix)] + suffix
        if cand.casefold() not in taken:
            return cand
        n += 1


def local_tz_offset(dt: datetime.datetime | None = None) -> str:
    """Format the local UTC offset of `dt` (default: local now) as `+HH:MM` or `-HH:MM`."""
    base = dt if dt is not None else datetime.datetime.now()
    aware = base if base.tzinfo is not None else base.astimezone()
    off = aware.utcoffset()
    if off is None:
        return "+00:00"
    total_sec = int(off.total_seconds())
    sign = "+" if total_sec >= 0 else "-"
    total_min = abs(total_sec) // 60
    return f"{sign}{total_min // 60:02d}:{total_min % 60:02d}"


def _stamp_to_ms(at: object, fallback_ms: int) -> int:
    """Derive UTC epoch milliseconds from a naive host-local `at` stamp, preserving sub-second `fallback_ms` when close."""
    text = str(at or "").strip()
    if text:
        for fmt, cut in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
            if len(text) < cut:
                continue
            try:
                parsed = datetime.datetime.strptime(text[:cut], fmt)
                ms = int(parsed.astimezone().timestamp() * 1000)
                if abs(ms - fallback_ms) <= 2000:
                    return fallback_ms
                return ms
            except (ValueError, OSError, OverflowError):
                continue
    return fallback_ms


def _task_created_sort_key(task: dict, path: Path | None = None) -> str:
    """Best-effort chronological sort key from created, first log entry, updated, or file mtime."""
    candidates: list[object] = [task.get("created")]
    raw_log = task.get("log")
    if isinstance(raw_log, list):
        first = next((e for e in raw_log if isinstance(e, dict) and e.get("at")), None)
        if first is not None:
            candidates.append(first.get("at"))
    candidates.append(task.get("updated"))
    for raw in candidates:
        if isinstance(raw, str):
            text = raw.strip().replace("T", " ")
            if text:
                return text
    if path is not None:
        with contextlib.suppress(OSError):
            return datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return ""


def _read_json_dict(path: Path) -> dict | None:
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size > JSON_FILE_MAX:
                return None
            data = f.read(JSON_FILE_MAX + 1)
    except OSError:
        return None
    if len(data) > JSON_FILE_MAX:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_json_strict(path: Path) -> dict | None:
    """Read a JSON object for locked read-modify-write.

    Returns None ONLY when `path` genuinely does not exist.
    Raises DamagedFileError for non-regular files (symlinks, FIFOs, directories), files larger than
    JSON_FILE_MAX, invalid UTF-8/JSON, or non-object JSON.
    Raises UnreadableFileError for other OS errors (such as permission denied).
    Never silently treats a damaged or unreadable file as empty/absent.
    """
    try:
        lst = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as err:
        raise UnreadableFileError(err.errno, f"cannot stat {path}: {err.strerror or err}", str(path)) from err
    if not stat.S_ISREG(lst.st_mode):
        raise DamagedFileError(f"{path} is not a regular file")
    if lst.st_size > JSON_FILE_MAX:
        raise DamagedFileError(f"{path} exceeds {JSON_FILE_MAX} bytes")
    try:
        with open(path, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                raise DamagedFileError(f"{path} is not a regular file")
            if st.st_size > JSON_FILE_MAX:
                raise DamagedFileError(f"{path} exceeds {JSON_FILE_MAX} bytes")
            data = f.read(JSON_FILE_MAX + 1)
    except FileNotFoundError:
        return None
    except DamagedFileError:
        raise
    except OSError as err:
        raise UnreadableFileError(err.errno, f"cannot read {path}: {err.strerror or err}", str(path)) from err
    if len(data) > JSON_FILE_MAX:
        raise DamagedFileError(f"{path} exceeds {JSON_FILE_MAX} bytes")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as err:
        raise DamagedFileError(f"{path} is not valid JSON: {err}") from err
    if not isinstance(value, dict):
        raise DamagedFileError(f"{path} must hold a JSON object, got {type(value).__name__}")
    return value


def _matching_json_files(folder: Path) -> list[Path]:
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    out = [Path(e.path) for e in entries
           if not e.name.startswith(".") and e.name.endswith(".json") and e.is_file()]
    out.sort(key=lambda p: p.name)
    return out


def _parse_event_line(raw: bytes, end_offset: int) -> dict | None:
    stripped = raw.strip()
    if not (stripped.startswith(b"{") and stripped.endswith(b"}")):
        return None
    try:
        value = json.loads(stripped.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    return {**value, "offset": end_offset}


def _last_whole_end(f, size: int) -> int:
    """Byte offset right after the last newline in [0, size), ignoring any half-written tail."""
    end = size
    while end > 0:
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


def _each_line_back(f, end: int) -> Iterator[tuple[bytes | None, int, int]]:
    """Yield (line_without_nl_or_None_if_too_long, start_byte, end_byte_after_nl) backwards from `end`."""
    block_start = 0
    block_end = 0
    block = b""

    def newline_before(pos: int) -> int:
        nonlocal block_start, block_end, block
        while pos > 0:
            if not (block_start < pos <= block_end):
                n = min(BLOCK_SIZE, pos)
                f.seek(pos - n)
                block = f.read(n)
                if not block:
                    return -1
                block_start = pos - n
                block_end = block_start + len(block)
            idx = block.rfind(b"\n", 0, pos - block_start)
            if idx >= 0:
                return block_start + idx
            pos = block_start
        return -1

    nxt = end
    while nxt > 0:
        nl = newline_before(nxt - 1)
        at = nl + 1
        length = nxt - 1 - at
        if length > LINE_MAX:
            raw: bytes | None = None
        elif block_start <= at and nxt - 1 <= block_end:
            raw = block[at - block_start:nxt - 1 - block_start]
        else:
            f.seek(at)
            raw = f.read(length)
        yield raw, at, nxt
        nxt = at


def _has_event_before(f, pos: int) -> bool:
    for raw, _, nxt in _each_line_back(f, pos):
        if raw is not None and _parse_event_line(raw, nxt) is not None:
            return True
    return False


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _mtime_iso(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scalar(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):
                return parsed
        except ValueError:
            pass
        return text[1:-1]
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def _memory_from_bytes(data: bytes) -> dict | None:
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if not text.startswith("---"):
        return None
    head, closed, _ = text[3:].partition("\n---")
    if not closed:
        return None
    mem = {"type": "", "description": "", "modified": "", "topic": ""}
    inside_meta = False
    for line in head.split("\n"):
        key, colon, value = line.strip().partition(":")
        if not colon or not key or key.startswith("#"):
            continue
        top = line[:1] not in (" ", "\t")
        if top:
            inside_meta = key == "metadata" and not value.strip()
        if not top and not inside_meta:
            continue
        if key == "description" and top:
            mem["description"] = _scalar(value)
        elif key in ("type", "modified", "topic"):
            mem[key] = _scalar(value)
    if mem["type"] not in MEMORY_TYPES:
        mem["type"] = "project"
    if mem["type"] == "project" and mem["topic"] == "pitfalls":
        mem["type"] = "pitfall"
    return mem


def _read_memory_head(path: Path) -> dict | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            data = f.read(MEMORY_HEAD_MAX)
    except OSError:
        return None
    return _memory_from_bytes(data)


def _research_heading_from_bytes(data: bytes) -> str:
    if b"\x00" in data:
        return ""
    text = data.decode("utf-8", errors="replace").lstrip("\ufeff").replace("\r\n", "\n")
    fm_title = ""
    if text.startswith("---\n"):
        head, closed, rest = text[4:].partition("\n---")
        if closed and (not rest or rest.startswith("\n")):
            for line in head.split("\n"):
                key, colon, value = line.strip().partition(":")
                if colon and line[:1] not in (" ", "\t") and key in ("title", "description") and not fm_title:
                    fm_title = _scalar(value)
            text = rest[1:] if rest.startswith("\n") else ""
    fence = ""
    for line in text.split("\n"):
        stripped = line.strip()
        if fence:
            if stripped.startswith(fence):
                fence = ""
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            ch = stripped[0]
            n = len(stripped) - len(stripped.lstrip(ch))
            if n >= 3:
                fence = ch * n
            continue
        m = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", stripped)
        if m:
            cleaned = " ".join(m.group(1).split())
            if cleaned:
                return cleaned[:RESEARCH_TITLE_MAX]
    return " ".join(fm_title.split())[:RESEARCH_TITLE_MAX] if fm_title else ""


def _read_research_heading(path: Path) -> str:
    return _read_doc_meta(path).get("title", "")


def _read_head(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return b""
    try:
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return b""
            return f.read(MEMORY_HEAD_MAX)
    except OSError:
        return b""


def _read_doc_meta(path: Path) -> dict:
    return _doc_meta_from_bytes(_read_head(path))


_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_META_ITEM = re.compile(r"^(?:\*\*[^*]{1,16}\*\*|[^\s*：:]{1,12})\s*[：:]")
_META_PARA = re.compile(r"^(?:任务|分支|日期|父任务|Task|Branch|Date)\b|^(?:任务|分支|日期)[：:\s]", re.I)


def _plain(text: str) -> str:
    """Markdown inline text as plain words: no emphasis, code ticks, link targets or images."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*|__|`", "", text)
    return " ".join(text.split())


def _doc_meta_from_bytes(data: bytes) -> dict:
    """{"title", "summary", "task"} of a Markdown document, from its first 64 KiB: the title is the first heading
    outside code fences (else frontmatter title/description); the summary is frontmatter summary/description, else
    the first prose paragraph after the title, else its first list item that is not a `**label**:` line; the task
    is frontmatter `task:`, else a `任务：`/`Task:` line naming one in backticks. Missing ones are left out."""
    if not data or b"\x00" in data:
        return {}
    text = data.decode("utf-8", errors="replace").lstrip("\ufeff").replace("\r\n", "\n")
    fm: dict = {}
    if text.startswith("---\n"):
        head, closed, rest = text[4:].partition("\n---")
        if closed and (not rest or rest.startswith("\n")):
            for line in head.split("\n"):
                key, colon, value = line.strip().partition(":")
                if colon and line[:1] not in (" ", "\t") and key in ("title", "description", "summary", "task", "superseded_by"):
                    fm.setdefault(key, _scalar(value))
            text = rest[1:] if rest.startswith("\n") else ""
    title, paragraph, first_item, fence, para, seen_title = "", "", "", "", [], False
    for line in text.split("\n"):
        stripped = line.strip()
        if fence:
            if stripped.startswith(fence):
                fence = ""
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            ch = stripped[0]
            n = len(stripped) - len(stripped.lstrip(ch))
            if n >= 3:
                fence = ch * n
            if para:
                break
            continue
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", stripped)
        if heading:
            if not title:
                title = " ".join(heading.group(1).split())
                seen_title = True
                continue
            if para:
                break
            continue
        if not stripped:
            if para:
                break
            continue
        if stripped.startswith(("|", "<", "---", "***", "![", "[!")):
            if para:
                break
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip("> ").strip()
            if not stripped or stripped.startswith("[!"):
                continue
        if not para and _META_PARA.match(_plain(stripped)) and len(stripped) < 160:
            continue  # "任务 x，分支 y" under the title says where it came from, not what it found
        if _LIST_ITEM.match(stripped):
            if para:
                break
            item = _LIST_ITEM.sub("", stripped)
            if not first_item and not _META_ITEM.match(item) and (seen_title or not title):
                first_item = _plain(item)
            continue
        para.append(stripped)
    paragraph = _plain(" ".join(para))
    out: dict = {}
    title = title or " ".join((fm.get("title") or fm.get("description") or "").split())
    if title:
        out["title"] = title[:RESEARCH_TITLE_MAX]
    summary = _plain(fm.get("summary") or (fm.get("description") if fm.get("title") else "") or "") \
        or paragraph or first_item
    if summary:
        out["summary"] = summary if len(summary) <= RESEARCH_SUMMARY_MAX else summary[:RESEARCH_SUMMARY_MAX - 1] + "…"
    task = (fm.get("task") or "").strip()
    if not task:
        found = TASK_LINE_RE.search(text[:8000])
        task = found.group(1) if found else ""
    if task and valid_task_id(task):
        out["task"] = task
    superseded = (fm.get("superseded_by") or "").strip().lstrip("/")
    if superseded.startswith("./"):
        superseded = superseded[2:]
    if superseded and ".." not in superseded and "\\" not in superseded and "\x00" not in superseded:
        out["superseded_by"] = superseded
    return out


def _normalize_doc_stem(name: str) -> str:
    """Lowercase filename stem with one draft/wip/rfc/proposal/old/bak/vN affix stripped."""
    stem = Path(name).stem.lower()
    stem = DRAFT_PREFIX_RE.sub("", stem, count=1)
    stem = DRAFT_SUFFIX_RE.sub("", stem, count=1)
    return stem


def _clean_repo_rel_list(items: object) -> list[str]:
    """Normalize a list of repository-relative paths/prefixes from library.json."""
    if not isinstance(items, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str):
            continue
        rel = raw.strip().replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        rel = rel.strip("/")
        if not rel or "\x00" in rel:
            continue
        parts = tuple(p for p in rel.split("/") if p)
        if not parts or any(p in (".", "..") for p in parts):
            continue
        norm = "/".join(parts)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _version_of(st) -> str:
    """A file's version for optimistic writes: its modification time (ns) and size."""
    return f"{st.st_mtime_ns:x}-{st.st_size:x}"


version_of = _version_of


def _history_stamp(clock=None) -> str:
    now_dt = clock.datetime_now() if clock is not None else datetime.datetime.now()
    return now_dt.strftime("%Y%m%d-%H%M%S")


def _split_rel(path: object) -> tuple[str, ...]:
    """A `/`-separated relative path as its parts; ValueError for anything that could leave its root."""
    if (not isinstance(path, str) or not path or "\x00" in path or "\\" in path
            or path.startswith("/") or path.endswith("/")):
        raise ValueError(f"invalid document path: {path!r}")
    parts = tuple(path.split("/"))
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"invalid document path: {path!r}")
    return parts


def _normalize_memory_modified(raw: str, fallback: str) -> str:
    if ISO_STAMP_RE.match(raw):
        return raw[:19] + "Z"
    if ISO_DATE_RE.match(raw):
        return raw + "T00:00:00Z"
    return fallback


def _show_of(ext: str, size: int) -> str:
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if (ext in TEXT_EXTENSIONS or ext == "") and size <= DOCUMENT_MAX:
        return "text"
    return ""


def is_excluded_research_topic(name: str) -> bool:
    """Test-output topic folders under `evidence/` that must not appear in Context."""
    return name.lower() == "render-check"


def _has_marker(folder: Path, marker: str) -> bool:
    try:
        os.lstat(folder / marker)
        return True
    except OSError:
        return False


HELPERS_FOLDER = "helpers"
MAILBOXES_FOLDER = "mailboxes"


def _is_internal_project_rel(parts: tuple[str, ...]) -> bool:
    if not parts:
        return True
    if parts[-1].lower() == "conversation.jsonl":
        return True
    if parts[0].lower() in (ATTACHMENTS_FOLDER, LEDGER_RESEARCH_FOLDER, HELPERS_FOLDER, MAILBOXES_FOLDER):
        return True
    if len(parts) == 1:
        low = parts[0].lower()
        if low in INTERNAL_PROJECT_FILES or low.startswith("applied-reports.") or low.startswith("pm-turn-journal."):
            return True
    return False


class Store(Protocol):
    def registrations(self) -> list[dict]: ...
    def registration(self, slug: str) -> dict | None: ...
    def change_registration(
        self,
        slug: str,
        change: Callable[[dict | None], dict | None],
        *,
        timeout: float | None = None,
    ) -> dict | None: ...
    def tasks(self, slug: str | None = None) -> list[dict]: ...
    def task(self, task_id: str) -> dict | None: ...
    def change_task(
        self,
        task_id: str,
        change: Callable[[dict | None], dict | None],
        *,
        timeout: float | None = None,
    ) -> dict | None: ...
    def append_event(self, slug: str, event: dict, *, timeout: float | None = None) -> int: ...
    def events(self, slug: str, before: int | None = None, after: int | None = None, limit: int = 200) -> dict: ...
    def all_events(self, slug: str) -> list[dict]: ...
    def receipts(self, slug: str) -> list[dict]: ...
    def documents(self, slug: str) -> list[dict]: ...
    def document(self, slug: str, root: str, path: str) -> str: ...


PathsProvider = Callable[[], tuple[Path, Path, Path, Path]]


class FileStore:
    """Filesystem ledger store backed by live path providers, per-file locks, and atomic writes."""

    def __init__(
        self,
        paths: PathsProvider | Home | Path | str,
        *,
        lock_timeout: float = LOCK_TIMEOUT,
        lock_fn=None,
        unlock_fn=None,
        replace_fn=None,
        clock=None,
    ):
        home_cls = getattr(home_mod, "Home", None)
        if home_cls is not None and isinstance(paths, home_cls):
            self._paths: PathsProvider = paths.store_dirs
        elif callable(paths):
            self._paths = paths
        else:
            self._paths = lambda root=paths: (
                Path(root), Path(root) / "pms", Path(root) / "tasks", Path(root) / "projects"
            )
        self.lock_timeout = lock_timeout
        self._lock_fn = lock_fn or lock_file
        self._unlock_fn = unlock_fn or unlock_file
        self._replace_fn = replace_fn or _replace_file
        self._clock = clock

    def _now_dt(self) -> datetime.datetime:
        return self._clock.datetime_now() if self._clock is not None else datetime.datetime.now()

    def _now_ms(self) -> int:
        if self._clock is not None:
            try:
                return int(self._clock.time() * 1000)
            except (TypeError, ValueError, OverflowError):
                pass
        return int(time.time() * 1000)

    def _dirs(self) -> tuple[Path, Path, Path, Path]:
        state, pms, tasks, projects = self._paths()
        return Path(state), Path(pms), Path(tasks), Path(projects)

    def _locks_dir(self) -> Path:
        state, _, _, _ = self._dirs()
        return state / "locks"

    def _registrations_with_stem(self) -> list[tuple[str, dict]]:
        _, pms_dir, _, _ = self._dirs()
        out: list[tuple[str, dict]] = []
        for path in _matching_json_files(pms_dir):
            rec = _read_json_dict(path)
            if rec is not None:
                out.append((path.stem, rec))
        return out

    def _registration_path(self, slug: str) -> tuple[str, Path]:
        """Resolve `(stem, path)` for `slug`, matching `pms/<slug>.json` first or a legacy file by repo/name."""
        _, pms_dir, _, _ = self._dirs()
        direct = pms_dir / f"{slug}.json"
        try:
            os.lstat(direct)
            return slug, direct
        except FileNotFoundError:
            pass
        except OSError:
            return slug, direct
        for stem, rec in self._registrations_with_stem():
            repo = rec.get("repo")
            if (stem == slug or rec.get("slug") == slug or rec.get("name") == f"pm-{slug}"
                    or (isinstance(repo, str) and repo and project_slug(repo) == slug)):
                return stem, pms_dir / f"{stem}.json"
        return slug, direct

    def registrations(self) -> list[dict]:
        return [rec for _, rec in self._registrations_with_stem()]

    def registration(self, slug: str) -> dict | None:
        if not valid_slug(slug):
            return None
        _, path = self._registration_path(slug)
        return _read_json_dict(path)

    def change_registration(
        self,
        slug: str,
        change: Callable[[dict | None], dict | None],
        *,
        timeout: float | None = None,
    ) -> dict | None:
        """Locked read-modify-write of the registration file for `slug`.

        Locates the same file `registration(slug)` reads (direct `pms/<slug>.json` or a legacy file whose
        repo/name matches `slug`), so renamed repositories never split into duplicate registration files.
        `change` receives the current dict (or None if absent) and returns the updated dict to persist,
        or None to leave the file untouched. Raises DamagedFileError/UnreadableFileError rather than
        overwriting a corrupt or unreadable file.
        """
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        state_dir, _, _, _ = self._dirs()
        target_stem, reg_path = self._registration_path(slug)
        lock_path = state_dir / "locks" / f"pm-{target_stem}.lock"
        wait = self.lock_timeout if timeout is None else timeout
        with file_lock(lock_path, wait, lock_fn=self._lock_fn, unlock_fn=self._unlock_fn):
            current = _read_json_strict(reg_path)
            updated = change(current)
            if updated is None:
                return current
            if not isinstance(updated, dict):
                raise TypeError(f"change_registration callback must return dict or None, got {type(updated).__name__}")
            payload = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            write_atomic(reg_path, payload, replace_fn=self._replace_fn)
            return updated

    def has_project(self, slug: str) -> bool:
        if not valid_slug(slug):
            return False
        _, _, _, projects_dir = self._dirs()
        return self.registration(slug) is not None or (projects_dir / slug).is_dir()

    def task(self, task_id: str, *, strict: bool = False) -> dict | None:
        if not valid_task_id(task_id):
            if strict:
                raise ValueError(f"invalid task id: {task_id!r}")
            return None
        _, _, tasks_dir, _ = self._dirs()
        path = tasks_dir / f"{task_id}.json"
        return _read_json_strict(path) if strict else _read_json_dict(path)

    def change_task(
        self,
        task_id: str,
        change: Callable[[dict | None], dict | None],
        *,
        timeout: float | None = None,
    ) -> dict | None:
        """Locked read-modify-write of tasks/<task_id>.json.

        `change` receives the current dict (or None if absent) and returns the updated dict to persist,
        or None to leave the file untouched. Raises DamagedFileError/UnreadableFileError rather than
        overwriting a corrupt or unreadable file.
        """
        if not valid_task_id(task_id):
            raise ValueError(f"invalid task id: {task_id!r}")
        state_dir, _, tasks_dir, _ = self._dirs()
        lock_path = state_dir / "locks" / f"task-{task_id}.lock"
        task_path = tasks_dir / f"{task_id}.json"
        wait = self.lock_timeout if timeout is None else timeout
        with file_lock(lock_path, wait, lock_fn=self._lock_fn, unlock_fn=self._unlock_fn):
            current = _read_json_strict(task_path)
            updated = change(current)
            if updated is None:
                return current
            if not isinstance(updated, dict):
                raise TypeError(f"change_task callback must return dict or None, got {type(updated).__name__}")
            if "id" in updated and updated["id"] != task_id:
                raise ValueError(f"task id mismatch: expected {task_id!r}, got {updated['id']!r}")
            payload = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            write_atomic(task_path, payload, replace_fn=self._replace_fn)
            return updated

    @staticmethod
    def _next_event_seq(log_path: Path) -> int:
        """Scan up to 64 trailing JSONL lines for the newest `seq` under the project's event lock and return `last_seq + 1`."""
        try:
            with open(log_path, "rb") as rf:
                size = os.fstat(rf.fileno()).st_size
                if size <= 0:
                    return 1
                end = _last_whole_end(rf, size)
                if end <= 0:
                    return 1
                scanned = 0
                for raw, _start, nxt in _each_line_back(rf, end):
                    if raw is None:
                        continue
                    parsed = _parse_event_line(raw, nxt)
                    if parsed is None:
                        continue
                    prev_seq = valid_task_number(parsed.get("seq"))
                    if prev_seq is not None:
                        return prev_seq + 1
                    scanned += 1
                    if scanned >= 64:
                        break
        except OSError:
            return 1
        return 1

    def append_event(self, slug: str, event: dict, *, timeout: float | None = None) -> int:
        """Append one event to projects/<slug>/conversation.jsonl under a per-project lock; return end byte offset."""
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        if not isinstance(event, dict):
            raise TypeError(f"event must be a dict, got {type(event).__name__}")
        state_dir, _, _, projects_dir = self._dirs()
        folder = projects_dir / slug
        folder.mkdir(parents=True, exist_ok=True)
        log_path = folder / "conversation.jsonl"
        lock_path = state_dir / "locks" / f"events-{slug}.lock"
        wait = self.lock_timeout if timeout is None else timeout
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
        enrich_chat = event.get("type") in ("user", "pm", "agent")
        now_ms = self._now_ms() if enrich_chat else 0
        tz_str = local_tz_offset(self._now_dt()) if enrich_chat else ""
        with file_lock(lock_path, wait, lock_fn=self._lock_fn, unlock_fn=self._unlock_fn):
            if enrich_chat:
                stored = dict(event)
                if valid_task_number(stored.get("seq")) is None:
                    stored["seq"] = self._next_event_seq(log_path)
                raw_ms = stored.get("at_ms")
                if not (isinstance(raw_ms, int) and not isinstance(raw_ms, bool) and raw_ms > 0):
                    stored["at_ms"] = _stamp_to_ms(stored.get("at"), now_ms)
                if not isinstance(stored.get("tz"), str) or not stored["tz"]:
                    stored["tz"] = tz_str
            else:
                stored = event
            payload = (json.dumps(stored, ensure_ascii=False) + "\n").encode("utf-8")
            fd = os.open(log_path, flags, 0o644)
            try:
                view = memoryview(payload)
                written = 0
                while written < len(view):
                    n = os.write(fd, view[written:])
                    if n <= 0:
                        raise OSError("short write appending conversation event")
                    written += n
                return os.fstat(fd).st_size
            finally:
                os.close(fd)

    def all_events(self, slug: str) -> list[dict]:
        """All valid JSON object events in projects/<slug>/conversation.jsonl, oldest first."""
        if not valid_slug(slug):
            return []
        _, _, _, projects_dir = self._dirs()
        log_path = projects_dir / slug / "conversation.jsonl"
        try:
            # Split on "\n" only: user words may hold U+2028/U+2029 which splitlines() would split on.
            lines = log_path.read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError:
            return []
        events: list[dict] = []
        for line in lines:
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    def receipts(self, slug: str) -> list[dict]:
        """Recent PM user-message receipts in projects/<slug>/receipts.json, oldest first."""
        if not valid_slug(slug):
            return []
        _, _, _, projects_dir = self._dirs()
        path = projects_dir / slug / "receipts.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = raw.get("receipts") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []
        return [r for r in items if isinstance(r, dict) and r.get("at") and (r.get("text") or r.get("digest"))]

    def tasks(self, slug: str | None = None) -> list[dict]:
        if slug is not None and not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        _, _, tasks_dir, _ = self._dirs()
        every: list[dict] = []
        for path in _matching_json_files(tasks_dir):
            item = _read_json_dict(path)
            if item is not None:
                every.append(item)
        every.sort(key=lambda t: str(t.get("updated") or ""), reverse=True)
        if slug is None:
            return every

        # Follow pm.py's owner_of rule (project_slug, exact folder, nested folder, then project name),
        # falling back to project_slug(repo) when no registration matches.
        f_regs = self._reg_folder_index()

        def belongs(task: dict) -> bool:
            pslug = task.get("project_slug")
            if valid_slug(pslug):
                return pslug == slug
            raw_repo = str(task.get("repo") or "")
            trepo = str(Path(raw_repo).resolve()) if raw_repo else ""
            tproj = str(task.get("project") or "").lower()
            if f_regs:
                exact = [r for r in f_regs if trepo and any(trepo == fp for fp in r[2])]
                nested = [
                    r for r in f_regs
                    if trepo and any(trepo.startswith(fp + "/") or trepo.startswith(fp + os.sep) for fp in r[2])
                ]
                named = [r for r in f_regs if r[3] and r[3] == tproj]
                hit = (exact or nested or named or [None])[0]
                if hit is not None:
                    return slug in (hit[0], hit[1])
            return bool(raw_repo) and project_slug(raw_repo) == slug

        return [t for t in every if belongs(t)]

    def _reg_index(self) -> list[tuple[str, str, str, str]]:
        regs = []
        for stem, rec in self._registrations_with_stem():
            raw_repo = str(rec.get("repo") or "")
            resolved = str(Path(raw_repo).resolve()) if raw_repo else ""
            rslug = registration_slug(rec, stem)
            proj = str(rec.get("project") or "").lower()
            regs.append((stem, rslug, resolved, proj))
        return regs

    def _reg_folder_index(self) -> list[tuple[str, str, tuple[str, ...], str]]:
        regs: list[tuple[str, str, tuple[str, ...], str]] = []
        for stem, rec in self._registrations_with_stem():
            rslug = registration_slug(rec, stem)
            resolved_list: list[str] = []
            for f in project_folders(rec):
                with contextlib.suppress(OSError):
                    resolved_list.append(str(Path(f["path"]).resolve()))
            proj = str(rec.get("project") or "").lower()
            regs.append((stem, rslug, tuple(dict.fromkeys(resolved_list)), proj))
        return regs

    def _task_slug(self, task: dict, regs: list[tuple[str, str, Any, str]] | None = None) -> str:
        """Canonical project slug for a task: `project_slug` -> folder/repo ownership -> project_slug(repo)."""
        pslug = task.get("project_slug")
        if valid_slug(pslug):
            return str(pslug)
        reg_list: list[tuple[str, str, Any, str]] = self._reg_folder_index() if regs is None else regs
        raw_repo = str(task.get("repo") or "")
        trepo = str(Path(raw_repo).resolve()) if raw_repo else ""
        tproj = str(task.get("project") or "").lower()
        if reg_list:
            def _paths_of(val: Any) -> tuple[str, ...]:
                if isinstance(val, (tuple, list)):
                    return tuple(str(x) for x in val if x)
                return (str(val),) if val else ()

            exact = [r for r in reg_list if trepo and any(trepo == fp for fp in _paths_of(r[2]))]
            nested = [
                r for r in reg_list
                if trepo and any(trepo.startswith(fp + "/") or trepo.startswith(fp + os.sep) for fp in _paths_of(r[2]))
            ]
            named = [r for r in reg_list if r[3] and r[3] == tproj]
            hit = (exact or nested or named or [None])[0]
            if hit is not None:
                return hit[1]
        if raw_repo:
            return project_slug(raw_repo)
        if tproj:
            cleaned = re.sub(r"[^a-z0-9_-]+", "-", tproj).strip("-")[:28]
            if valid_slug(cleaned):
                return cleaned
        return "default"

    def task_project_slug(self, task: Mapping[str, Any] | None) -> str:
        """Resolve canonical project slug for `task`: `task['project_slug']` -> folder ownership -> `project_slug(repo)`."""
        if not isinstance(task, Mapping):
            return ""
        return self._task_slug(dict(task))

    def folder_project_slug(self, repo_or_slug: str | Path | None) -> str:
        """Resolve canonical project slug for a workspace folder path or project slug (`''` if empty)."""
        raw = str(repo_or_slug or "").strip()
        if not raw:
            return ""
        if valid_slug(raw) and self._registration_path(raw) is not None:
            return registration_slug(self.registration(raw), raw)
        try:
            resolved = str(Path(raw).resolve())
        except OSError:
            resolved = raw
        try:
            proj_root_resolved = self._dirs()[3].resolve()
            p_res = Path(resolved)
            if p_res.parent == proj_root_resolved and valid_slug(p_res.name) and self._registration_path(p_res.name) is not None:
                return registration_slug(self.registration(p_res.name), p_res.name)
        except OSError:
            pass
        reg_list = self._reg_folder_index()
        if reg_list:
            def _paths_of(val: Any) -> tuple[str, ...]:
                if isinstance(val, (tuple, list)):
                    return tuple(str(x) for x in val if x)
                return (str(val),) if val else ()

            for _stem, rslug, fp_val, _pname in reg_list:
                if any(resolved == fp for fp in _paths_of(fp_val)):
                    return rslug
            for _stem, rslug, fp_val, _pname in reg_list:
                if any(resolved.startswith(fp + "/") or resolved.startswith(fp + os.sep) for fp in _paths_of(fp_val)):
                    return rslug
        return project_slug(raw)

    @staticmethod
    def _read_seq_last(seq_doc: dict | None, seq_path: Path) -> int:
        if seq_doc is None:
            return 0
        raw_last = seq_doc.get("last", 0)
        if isinstance(raw_last, bool) or not isinstance(raw_last, int) or raw_last < 0:
            raise DamagedFileError(f"{seq_path} has invalid 'last' value: {raw_last!r}")
        return raw_last

    def _scan_tasks_by_slug(self) -> dict[str, list[tuple[dict, Path]]]:
        _, _, tasks_dir, _ = self._dirs()
        regs = self._reg_index()
        grouped: dict[str, list[tuple[dict, Path]]] = {}
        for path in _matching_json_files(tasks_dir):
            item = _read_json_dict(path)
            if item is None or not valid_task_id(item.get("id")):
                continue
            tslug = self._task_slug(item, regs)
            grouped.setdefault(tslug, []).append((item, path))
        return grouped

    def _backfill_slug_locked(
        self,
        slug: str,
        *,
        cur_seq: dict | None,
        seq_path: Path,
        dry_run: bool = False,
        before_backfill=None,
        timeout: float | None = None,
        persist_seq: bool = True,
    ) -> dict:
        """Chronologically backfill unnumbered non-review tasks for `slug` while `seq-{slug}.lock` is held."""
        seq_last = self._read_seq_last(cur_seq, seq_path)
        slug_items = self._scan_tasks_by_slug().get(slug, [])
        reviews = [item for item, _ in slug_items if item.get("review_of")]
        non_reviews = [(item, path) for item, path in slug_items if not item.get("review_of")]
        numbered = [item for item, _ in non_reviews if valid_task_number(item.get("number")) is not None]
        unnumbered = [(item, path) for item, path in non_reviews if valid_task_number(item.get("number")) is None]
        max_existing = max(
            (n for item, _ in slug_items if (n := valid_task_number(item.get("number"))) is not None),
            default=0,
        )
        base_last = max(seq_last, max_existing)
        unnumbered.sort(key=lambda pair: (_task_created_sort_key(pair[0], pair[1]), str(pair[0].get("id") or "")))
        assigned = [
            {"id": str(item["id"]), "number": base_last + i}
            for i, (item, _path) in enumerate(unnumbered, 1)
        ]
        final_last = base_last + len(assigned)
        if not dry_run:
            if assigned and before_backfill is not None:
                before_backfill(slug, len(assigned))
            for entry in assigned:
                tid, num = entry["id"], entry["number"]

                def _set_num(cur: dict | None, n: int = num) -> dict | None:
                    if cur is None or valid_task_number(cur.get("number")) is not None:
                        return None
                    return {**cur, "number": n}

                self.change_task(tid, _set_num, timeout=timeout)
            if persist_seq and (assigned or final_last > seq_last or (cur_seq is None and final_last > 0)):
                seq_path.parent.mkdir(parents=True, exist_ok=True)
                seq_doc = dict(cur_seq or {})
                seq_doc["last"] = final_last
                if assigned:
                    seq_doc["backfilled_at"] = self._now_dt().strftime("%Y-%m-%d %H:%M")
                payload = (json.dumps(seq_doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                write_atomic(seq_path, payload, replace_fn=self._replace_fn)
        return {
            "assigned": assigned,
            "already_numbered": len(numbered),
            "skipped_reviews": len(reviews),
            "last": final_last,
        }

    def allocate_task_number(
        self,
        slug: str,
        *,
        before_backfill=None,
        timeout: float | None = None,
    ) -> int:
        """Allocate and persist the next monotonic task number (>= 1) for `slug` under per-project lock.

        When `task-seq.json` does not exist yet for `slug`, pre-existing unnumbered non-review tasks
        in `slug` are backfilled chronologically under the same lock first (calling `before_backfill`
        before any task is mutated) so older tasks stay ahead of the newly allocated number.
        """
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        state_dir, _, _, projects_dir = self._dirs()
        lock_path = state_dir / "locks" / f"seq-{slug}.lock"
        seq_path = projects_dir / slug / TASK_SEQ_FILE
        wait = self.lock_timeout if timeout is None else timeout
        with file_lock(lock_path, wait, lock_fn=self._lock_fn, unlock_fn=self._unlock_fn):
            current = _read_json_strict(seq_path)
            backfilled = False
            if current is None:
                info = self._backfill_slug_locked(
                    slug,
                    cur_seq=None,
                    seq_path=seq_path,
                    dry_run=False,
                    before_backfill=before_backfill,
                    timeout=timeout,
                    persist_seq=False,
                )
                base_last = info["last"]
                backfilled = bool(info["assigned"])
            else:
                seq_last = self._read_seq_last(current, seq_path)
                regs = self._reg_index()
                max_existing = max(
                    (
                        n for t in self.tasks()
                        if self._task_slug(t, regs) == slug and (n := valid_task_number(t.get("number"))) is not None
                    ),
                    default=0,
                )
                base_last = max(seq_last, max_existing)
            next_num = base_last + 1
            seq_path.parent.mkdir(parents=True, exist_ok=True)
            updated = {**(current or {}), "last": next_num}
            if backfilled:
                updated["backfilled_at"] = self._now_dt().strftime("%Y-%m-%d %H:%M")
            payload = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            write_atomic(seq_path, payload, replace_fn=self._replace_fn)
            return next_num

    def backfill_task_numbers(
        self,
        slug: str | None = None,
        *,
        dry_run: bool = False,
        before_backfill=None,
        timeout: float | None = None,
    ) -> dict:
        """One-shot, idempotent, locked backfill of per-project task numbers in chronological order.

        Skips review tasks (`review_of`), preserves existing valid numbers, and writes `number`
        via `change_task` without modifying `updated`.
        """
        if slug is not None and not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        state_dir, _, _, projects_dir = self._dirs()
        wait = self.lock_timeout if timeout is None else timeout
        target_slugs = [slug] if slug is not None else sorted(self._scan_tasks_by_slug())
        per_project: dict[str, dict] = {}
        total_assigned = 0

        for tslug in target_slugs:
            lock_path = state_dir / "locks" / f"seq-{tslug}.lock"
            seq_path = projects_dir / tslug / TASK_SEQ_FILE
            with file_lock(lock_path, wait, lock_fn=self._lock_fn, unlock_fn=self._unlock_fn):
                cur_seq = _read_json_strict(seq_path)
                info = self._backfill_slug_locked(
                    tslug,
                    cur_seq=cur_seq,
                    seq_path=seq_path,
                    dry_run=dry_run,
                    before_backfill=before_backfill,
                    timeout=timeout,
                    persist_seq=True,
                )
                total_assigned += len(info["assigned"])
                per_project[tslug] = info
        return {"dry_run": dry_run, "projects": per_project, "total_assigned": total_assigned}

    def events(self, slug: str, before: int | None = None, after: int | None = None, limit: int = 200) -> dict:
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        if before is not None and after is not None:
            raise ValueError("pass before or after, not both")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 or limit > WINDOW_MAX:
            raise ValueError(f"limit must be between 1 and {WINDOW_MAX}")
        if before is not None and (not isinstance(before, int) or isinstance(before, bool) or before < 0):
            raise ValueError("before must be a non-negative byte offset")
        if after is not None and (not isinstance(after, int) or isinstance(after, bool) or after < 0):
            raise ValueError("after must be a non-negative byte offset")

        _, _, _, projects_dir = self._dirs()
        log_path = projects_dir / slug / "conversation.jsonl"
        try:
            f = open(log_path, "rb")
        except FileNotFoundError:
            if before is not None and before > 0:
                raise LogReplacedError(f"conversation log is shorter than {before}: it was replaced") from None
            if after is not None:
                return {"events": [], "from": 0, "offset": 0, "earlier": False, "more": False, "reset": after > 0}
            return {"events": [], "from": 0, "offset": 0, "earlier": False}
        except OSError as err:
            raise UnreadableFileError(err.errno, f"cannot read {log_path}: {err.strerror or err}", str(log_path)) from err

        with f:
            size = os.fstat(f.fileno()).st_size
            if after is not None:
                return self._events_after(f, size, after, limit)
            return self._events_window(f, size, before, limit)

    def _events_window(self, f, size: int, before: int | None, limit: int) -> dict:
        if before is None:
            end = _last_whole_end(f, size)
        elif before > size:
            raise LogReplacedError(f"conversation log is shorter than {before}: it was replaced")
        elif before == 0:
            return {"events": [], "from": 0, "offset": 0, "earlier": False}
        else:
            f.seek(before - 1)
            if f.read(1) != b"\n":
                raise ValueError(f"no line ends at byte {before}")
            end = before

        kept: list[dict] = []
        held_bytes = 0
        window_from = end
        has_earlier = False
        full = False
        for raw, at, nxt in _each_line_back(f, end):
            if raw is None:
                continue
            event = _parse_event_line(raw, nxt)
            if event is None:
                continue
            if full or (kept and held_bytes + len(raw) > WINDOW_BYTES):
                has_earlier = True
                break
            kept.append(event)
            held_bytes += len(raw)
            window_from = at
            if len(kept) >= limit:
                full = True
        kept.reverse()
        if not kept:
            window_from = 0
        return {
            "events": kept,
            "from": window_from,
            "offset": end,
            "earlier": has_earlier,
        }

    def _events_after(self, f, size: int, after: int, limit: int) -> dict:
        if after > size:
            fresh = self._events_window(f, size, None, limit)
            return {**fresh, "more": False, "reset": True}
        if after > 0:
            f.seek(after - 1)
            if f.read(1) != b"\n":
                fresh = self._events_window(f, size, None, limit)
                return {**fresh, "more": False, "reset": True}

        whole_end = _last_whole_end(f, size)
        if after >= whole_end:
            has_earlier = _has_event_before(f, after) if after > 0 else False
            return {"events": [], "from": after, "offset": after, "earlier": has_earlier, "more": False, "reset": False}

        f.seek(after)
        at = after
        first_at: int | None = None
        events: list[dict] = []
        buf = bytearray()
        too_long = False
        line_len = 0

        while at < whole_end and len(events) < limit and (at - after) < SINCE_BYTES:
            to_read = min(BLOCK_SIZE, whole_end - (at + line_len))
            if to_read <= 0:
                break
            chunk = f.read(to_read)
            if not chunk:
                break
            start = 0
            while True:
                nl = chunk.find(b"\n", start)
                if nl < 0:
                    piece = chunk[start:]
                    line_len += len(piece)
                    if line_len > LINE_MAX:
                        too_long = True
                        buf.clear()
                    elif not too_long:
                        buf.extend(piece)
                    break
                piece = chunk[start:nl]
                total_line_len = line_len + len(piece)
                line_start = at
                line_end = at + total_line_len + 1
                if not too_long and total_line_len <= LINE_MAX:
                    raw = bytes(buf) + piece if buf else piece
                    event = _parse_event_line(raw, line_end)
                    if event is not None:
                        if first_at is None:
                            first_at = line_start
                        events.append(event)
                buf.clear()
                too_long = False
                line_len = 0
                at = line_end
                start = nl + 1
                if len(events) >= limit or (at - after) >= SINCE_BYTES:
                    break

        anchor = first_at if first_at is not None else at
        has_earlier = _has_event_before(f, anchor) if anchor > 0 else False
        more = _has_event_after(f, at, whole_end) if at < whole_end else False
        return {
            "events": events,
            "from": anchor if events else (0 if at == 0 else at),
            "offset": at,
            "earlier": has_earlier,
            "more": more,
            "reset": False,
        }

    def _project_repo(self, slug: str) -> Path | None:
        reg = self.registration(slug)
        if isinstance(reg, dict):
            raw = reg.get("repo")
            if isinstance(raw, str) and raw:
                return Path(raw)
        for task in self.tasks(slug):
            raw = task.get("repo")
            if isinstance(raw, str) and raw:
                return Path(raw)
        return None

    def _safe_subdir(self, parent: Path, child_name: str) -> Path | None:
        base = parent / child_name
        try:
            st = os.lstat(base)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError as err:
            raise UnreadableFileError(err.errno, f"cannot stat {base}: {err.strerror or err}", str(base)) from err
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            return None
        try:
            real_parent = parent.resolve(strict=True)
            real_base = base.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError as err:
            raise UnreadableFileError(err.errno, f"cannot resolve {base}: {err.strerror or err}", str(base)) from err
        if real_base.parent != real_parent:
            return None
        return real_base

    def _context_root_dir(self, slug: str, root: str) -> Path | None:
        """The folder a root's documents are under: projects/<slug> (project, and the decisions archive),
        projects/<slug>/docs (docs), projects/<slug>/memory (memory), the ledger's memory (user, personal), the
        repository (instructions); the first research root for research. None when it is missing or unsafe."""
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        if root not in DOCUMENT_ROOTS:
            raise ValueError(f"invalid document root: {root!r}")
        if root == "research":
            dirs = self._research_root_dirs(slug)
            return dirs[0] if dirs else None
        state_dir, _, _, projects_dir = self._dirs()
        if root in ("user", "personal"):
            return self._safe_subdir(state_dir, "memory")
        if root in ("instructions", "repo"):
            return self._repo_dir(slug)
        proj = self._safe_subdir(projects_dir, slug)
        if proj is None or root == "project":
            return proj
        return self._safe_subdir(proj, DOCS_FOLDER if root == "docs" else "memory")

    def _resolve_dir(self, path_val: str | Path) -> Path | None:
        p = Path(path_val)
        try:
            st = os.stat(p)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError as err:
            raise UnreadableFileError(err.errno, f"cannot stat {p}: {err.strerror or err}", str(p)) from err
        if not stat.S_ISDIR(st.st_mode):
            return None
        try:
            return p.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError as err:
            raise UnreadableFileError(err.errno, f"cannot resolve {p}: {err.strerror or err}", str(p)) from err

    def _repo_dir(self, slug: str) -> Path | None:
        """The project's main checkout, resolved, when it is a directory."""
        repo = self._project_repo(slug)
        if repo is None:
            return None
        return self._resolve_dir(repo)

    def _project_folders(self, slug: str) -> list[tuple[dict[str, Any], Path]]:
        """Equal-status resolved directories linked to `slug`, preserving `folders[]` order."""
        reg = self.registration(slug)
        if isinstance(reg, dict):
            has_explicit = "folders" in reg and isinstance(reg.get("folders"), list)
            out: list[tuple[dict[str, Any], Path]] = []
            seen: set[Path] = set()
            for entry in project_folders(reg):
                resolved = self._resolve_dir(entry["path"])
                if resolved is not None and resolved not in seen:
                    seen.add(resolved)
                    out.append((entry, resolved))
            if has_explicit or out:
                return out
        repo = self._repo_dir(slug)
        if repo is not None:
            return [({"path": str(repo), "alias": repo.name or "repo"}, repo)]
        return []

    def _subdirs(self, base: Path | None, *names: str) -> Path | None:
        """base/names[0]/names[1]/…, each a plain (non-symlink) folder inside the last; None otherwise."""
        cur = base
        for name in names:
            if cur is None:
                return None
            cur = self._safe_subdir(cur, name)
        return cur

    def _research_root_dirs(self, slug: str, *, include_repo: bool = True) -> list[Path]:
        """Research roots: ledger `projects/<slug>/research` (always) and optionally legacy `<repo>/evidence`."""
        roots: list[Path] = []
        if include_repo:
            ev = self._subdirs(self._repo_dir(slug), RESEARCH_FOLDER)
            if ev is not None:
                roots.append(ev)
        proj_dir = self._context_root_dir(slug, "project")
        if proj_dir is not None:
            ledger_res = self._safe_subdir(proj_dir, LEDGER_RESEARCH_FOLDER)
            if ledger_res is not None and ledger_res not in roots:
                roots.append(ledger_res)
        return roots

    def _ledger_research_dir(self, slug: str) -> Path | None:
        """projects/<slug>/docs/research: the project's own home for reports (complete, private)."""
        return self._subdirs(self._context_root_dir(slug, "docs"), DOCS_RESEARCH)

    def _published_research_dir(self, slug: str) -> Path | None:
        """<repo>/docs/research: redacted copies published with the repository. They never stand in for the
        local originals: the Library marks an original that has one, and lists one that has no original."""
        return self._subdirs(self._repo_dir(slug), DOCS_FOLDER, DOCS_RESEARCH)

    def _evidence_reports(
        self, slug: str, *, include_repo: bool = True
    ) -> dict[str, tuple[os.stat_result, Path, str]]:
        """`<topic>/README.md` → (stat, path, source) across ledger research (and legacy `<repo>/evidence` when `include_repo`)."""
        by_path: dict[str, tuple[os.stat_result, Path, str]] = {}
        for real_base in self._research_root_dirs(slug, include_repo=include_repo):
            source = "repo" if real_base.name == RESEARCH_FOLDER else "ledger"
            try:
                with os.scandir(real_base) as it:
                    top_entries = sorted(it, key=lambda e: e.name)
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError as err:
                raise UnreadableFileError(
                    err.errno, f"cannot scan {real_base}: {err.strerror or err}", str(real_base)
                ) from err
            for entry in top_entries:
                if len(by_path) >= DOCUMENTS_MAX:
                    break
                topic = entry.name
                if not topic or topic.startswith(".") or is_excluded_research_topic(topic):
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    tst = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not stat.S_ISDIR(tst.st_mode):
                    continue
                topic_dir = Path(entry.path)
                if _has_marker(topic_dir, RENDER_CHECK_MARKER):
                    continue
                readme = topic_dir / RESEARCH_FILENAME
                try:
                    rst = os.lstat(readme)
                except OSError:
                    continue
                if stat.S_ISLNK(rst.st_mode) or not stat.S_ISREG(rst.st_mode):
                    continue
                rel_posix = f"{topic}/{RESEARCH_FILENAME}"
                prev = by_path.get(rel_posix)
                if prev is not None and rst.st_mtime <= prev[0].st_mtime:
                    continue
                by_path[rel_posix] = (rst, readme, source)
        return by_path

    def _research_documents(self, slug: str) -> list[dict]:
        """The old Context panel's research rows: `<topic>/README.md` under `research`."""
        rows = []
        for rel_posix, (rst, readme, _) in sorted(self._evidence_reports(slug).items()):
            size = rst.st_size
            show = _show_of(".md", size)
            row: dict = {
                "root": "research",
                "path": rel_posix,
                "kind": "md",
                "size": size,
                "modified": _mtime_iso(rst.st_mtime),
            }
            if show:
                row["show"] = show
            if size <= DOCUMENT_MAX:
                desc = _read_research_heading(readme)
                if desc:
                    row["description"] = desc
            rows.append(row)
        return rows

    def _scan_tree(self, real_base: Path, *, max_depth: int = 64, skip_top: frozenset = frozenset(),
                   files_only: bool = False, extensions: frozenset | None = None):
        """(relative parts, DirEntry stat, path) of everything under real_base that is not hidden and not a
        symlink, folders before what is in them, at most DOCUMENTS_MAX entries."""
        count = 0
        stack: list[tuple[Path, tuple[str, ...]]] = [(real_base, ())]
        while stack and count < DOCUMENTS_MAX:
            folder, prefix = stack.pop()
            try:
                with os.scandir(folder) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError as err:
                if folder == real_base:
                    raise UnreadableFileError(
                        err.errno, f"cannot scan {folder}: {err.strerror or err}", str(folder)
                    ) from err
                continue
            subdirs = []
            for entry in entries:
                if count >= DOCUMENTS_MAX:
                    break
                name = entry.name
                if not name or name.startswith("."):
                    continue
                if not prefix and name.lower() in skip_top:
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                parts = (*prefix, name)
                if stat.S_ISDIR(st.st_mode):
                    if len(parts) < max_depth:
                        subdirs.append((Path(entry.path), parts))
                    if files_only:
                        continue
                elif not stat.S_ISREG(st.st_mode):
                    continue
                elif extensions is not None and Path(name).suffix.lower() not in extensions:
                    continue
                count += 1
                yield parts, st, Path(entry.path)
            for sub in reversed(subdirs):
                stack.append(sub)

    def _memory_rows(self, real_base: Path | None, root: str, prefix: tuple[str, ...] = ()) -> list[dict]:
        """Top-level `*.md` memories of a memory folder (no MEMORY.md, candidates, history or folders)."""
        rows: list[dict] = []
        if real_base is None:
            return rows
        try:
            with os.scandir(real_base) as it:
                entries = sorted(it, key=lambda e: e.name)
        except (FileNotFoundError, NotADirectoryError):
            return rows
        except OSError as err:
            raise UnreadableFileError(err.errno, f"cannot scan {real_base}: {err.strerror or err}",
                                      str(real_base)) from err
        for entry in entries:
            name = entry.name
            if name.startswith(".") or not name.endswith(".md") or name == "MEMORY.md":
                continue
            try:
                if entry.is_symlink():
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            modified = _mtime_iso(st.st_mtime)
            row: dict = {"root": root, "path": "/".join((*prefix, name)), "kind": "md", "size": st.st_size,
                         "modified": modified}
            mem = _read_memory_head(Path(entry.path)) if st.st_size <= DOCUMENT_MAX else None
            if mem is not None:
                row.update(kind="memory", type=mem["type"])
                if mem["topic"]:
                    row["topic"] = mem["topic"]
                if mem["description"]:
                    row["description"] = mem["description"]
                row["modified"] = _normalize_memory_modified(mem["modified"], modified)
                row["show"] = "text"
            elif _show_of(".md", st.st_size):
                row["show"] = "text"
            rows.append(row)
        return rows

    def documents(self, slug: str) -> list[dict]:
        """The old Context panel's listing (`project context`), now from the same allow-list as the Library and
        Memory: under `project` only decisions.md, docs/** and memory/*.md; under `user` the personal memories;
        under `research` the evidence reports. Process files (handover.md, verify*, MEMORY.md, candidates,
        anything else in the project folder) are no longer listed."""
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        rows: list[dict] = []
        proj = self._context_root_dir(slug, "project")
        if proj is not None:
            try:
                with os.scandir(proj) as it:
                    top_md = sorted((e for e in it if not e.name.startswith(".")
                                     and e.name.lower().endswith((".md", ".markdown"))
                                     and e.name.lower() != "handover.md"), key=lambda e: e.name)
            except (FileNotFoundError, NotADirectoryError):
                top_md = []
            except OSError as err:
                raise UnreadableFileError(err.errno, f"cannot scan {proj}: {err.strerror or err}", str(proj)) from err
            for entry in top_md:
                try:
                    if entry.is_symlink():
                        continue
                    dst = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(dst.st_mode):
                    rows.append(self._file_row("project", (entry.name,), dst))
            docs = self._safe_subdir(proj, DOCS_FOLDER)
            if docs is not None:
                rows.append({"root": "project", "path": DOCS_FOLDER, "kind": "folder", "size": 0,
                             "modified": _mtime_iso(os.lstat(docs).st_mtime)})
                for parts, st, _ in self._scan_tree(docs):
                    rows.append(self._file_row("project", (DOCS_FOLDER, *parts), st))
            rows.extend(self._memory_rows(self._safe_subdir(proj, "memory"), "project", ("memory",)))
        rows.extend(self._memory_rows(self._context_root_dir(slug, "user"), "user"))
        rows.extend(self._research_documents(slug))
        return rows

    @staticmethod
    def _file_row(root: str, parts: tuple[str, ...], st) -> dict:
        rel = "/".join(parts)
        if stat.S_ISDIR(st.st_mode):
            return {"root": root, "path": rel, "kind": "folder", "size": 0, "modified": _mtime_iso(st.st_mtime)}
        ext = Path(parts[-1]).suffix.lower()
        row = {"root": root, "path": rel, "kind": ext[1:] if ext.startswith(".") and len(ext) > 1 else "file",
               "size": st.st_size, "modified": _mtime_iso(st.st_mtime)}
        show = _show_of(ext, st.st_size)
        if show:
            row["show"] = show
        return row

    # ---- Library: docs (editable), research and instructions (read-only) ------------------------------------

    def library_state(self, slug: str) -> dict:
        proj = self._context_root_dir(slug, "project")
        state = _read_json_dict(proj / LIBRARY_STATE_FILE) if proj is not None else None
        return state or {}

    def set_library_state(self, slug: str, **changes) -> dict:
        """Merge `changes` into projects/<slug>/library.json (e.g. decisions={"hidden": True, "at": …}).
        Keys set to None are removed."""
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        proj = self._project_folder(slug, create=True)
        with file_lock(self._locks_dir() / f"library-{slug}.lock"):
            state = _read_json_strict(proj / LIBRARY_STATE_FILE) or {}
            for k, v in changes.items():
                if v is None:
                    state.pop(k, None)
                else:
                    state[k] = v
            write_atomic(proj / LIBRARY_STATE_FILE, (json.dumps(state, ensure_ascii=False, indent=1) + "\n").encode())
        return state

    def research_sources(self, slug: str) -> dict:
        proj = self._context_root_dir(slug, "project")
        found = _read_json_dict(proj / RESEARCH_SOURCES_FILE) if proj is not None else None
        return {k: v for k, v in (found or {}).items() if isinstance(k, str) and isinstance(v, str)}

    def note_research_source(self, slug: str, path: str, task_id: str) -> None:
        """Remember which task wrote a research report (`evidence/<topic>/README.md`), for the Library's link."""
        if not valid_slug(slug) or not valid_task_id(task_id):
            return
        proj = self._project_folder(slug, create=True)
        with file_lock(self._locks_dir() / f"library-{slug}.lock"):
            try:
                found = _read_json_strict(proj / RESEARCH_SOURCES_FILE) or {}
            except StoreError:
                found = {}
            found[path] = task_id
            write_atomic(proj / RESEARCH_SOURCES_FILE, (json.dumps(found, ensure_ascii=False, indent=1) + "\n").encode())

    def _project_folder(self, slug: str, *, create: bool = False) -> Path:
        projects_dir = self._dirs()[3]
        if create:
            projects_dir.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(FileExistsError):
                os.mkdir(projects_dir / slug)
        proj = self._safe_subdir(projects_dir, slug)
        if proj is None:
            if create:
                raise ValueError(f"projects/{slug} is not a plain folder")
            raise FileNotFoundError(f"no project folder for {slug}")
        return proj

    def _task_for_topic(self, slug: str, topic: str, tasks: list[dict]) -> str:
        """The task that most likely wrote a report on `topic`: `<slug>-<topic>`, else the latest one whose
        worktree is `…-<topic>` or whose branch is `…/<topic>`."""
        if not topic:
            return ""
        ids = {t.get("id") for t in tasks}
        if f"{slug}-{topic}" in ids:
            return f"{slug}-{topic}"
        hits = []
        for t in tasks:
            if t.get("review_of"):
                continue
            wt = Path(str(t.get("worktree") or "")).name
            branch = str(t.get("branch") or "").rsplit("/", 1)[-1]
            if wt in (topic, f"dev-{topic}") or branch == topic:
                hits.append(t)
        hits.sort(key=lambda t: str(t.get("updated") or t.get("created") or ""))
        return str(hits[-1].get("id") or "") if hits else ""

    def _research_row(self, path: str, source: str, st, file: Path, topic: str, slug: str,
                      sources: dict, tasks: list[dict], by_id: dict) -> dict:
        row: dict = {"root": "research", "path": path, "source": source, "kind": "md", "size": st.st_size,
                     "modified": _mtime_iso(st.st_mtime), "version": _version_of(st), "writable": False}
        if _show_of(".md", st.st_size):
            row["show"] = "text"
        meta = _read_doc_meta(file) if st.st_size <= DOCUMENT_MAX else {}
        for key in ("title", "summary"):
            if meta.get(key):
                row[key] = meta[key]
        task = sources.get(path) or ""
        if not task and meta.get("task") in by_id:
            task = meta["task"]
        if source != PUBLISHED_PREFIX:  # a public copy is linked only by what it says itself
            task = task or self._task_for_topic(slug, topic, tasks)
        if task:
            row["task"] = task
            title = (by_id.get(task) or {}).get("title")
            if title:
                row["task_title"] = str(title)
        return row

    def _research_items(self, slug: str) -> list[dict]:
        tasks = self.tasks(slug)
        by_id = {t.get("id"): t for t in tasks if t.get("id")}
        sources = self.research_sources(slug)
        rows: list[dict] = []
        md = frozenset({".md", ".markdown"})
        topic_of = lambda parts: parts[0] if len(parts) > 1 else Path(parts[0]).stem
        by_topic: dict[str, dict] = {}
        ledger = self._ledger_research_dir(slug)
        for parts, st, file in (self._scan_tree(ledger, max_depth=RESEARCH_DEPTH, files_only=True, extensions=md)
                                if ledger is not None else ()):
            row = self._research_row("/".join((DOCS_FOLDER, DOCS_RESEARCH, *parts)), "ledger", st, file,
                                     topic_of(parts), slug, sources, tasks, by_id)
            by_topic.setdefault(topic_of(parts), row)
            rows.append(row)
        for rel, (st, readme, source) in sorted(self._evidence_reports(slug, include_repo=False).items()):
            topic = rel.split("/", 1)[0]
            if topic in by_topic:  # moved to the project's docs/research: that copy is the one shown
                continue
            row = self._research_row(f"{RESEARCH_FOLDER}/{rel}", source, st, readme, topic, slug, sources, tasks, by_id)
            by_topic[topic] = row
            rows.append(row)
        return rows

    def _instruction_paths(self, repo: Path) -> list[tuple[str, ...]]:
        found = [tuple(p.split("/")) for p in INSTRUCTION_FILES]
        rules = self._subdirs(repo, *INSTRUCTION_RULES)
        if rules is not None:
            try:
                with os.scandir(rules) as it:
                    names = sorted(e.name for e in it if e.name.endswith(".md") and not e.name.startswith("."))
            except OSError:
                names = []
            found += [(*INSTRUCTION_RULES, n) for n in names]
        return found

    def _instruction_items(self, slug: str) -> list[dict]:
        repo = self._repo_dir(slug)
        rows: list[dict] = []
        if repo is None:
            return rows
        for parts in self._instruction_paths(repo):
            try:
                file, st = self._walk_file(repo, parts, "/".join(parts))
            except (FileNotFoundError, DamagedFileError, UnreadableFileError):
                continue
            row = self._file_row("instructions", parts, st)
            row.update(version=_version_of(st), writable=False)
            meta = _read_doc_meta(file) if st.st_size <= DOCUMENT_MAX else {}
            if meta.get("title"):
                row["title"] = meta["title"]
            rows.append(row)
        return rows

    def _repo_docs_config(self, slug: str) -> dict:
        """Per-project repo_docs settings from projects/<slug>/library.json."""
        raw = self.library_state(slug).get("repo_docs")
        if not isinstance(raw, dict):
            return {"enabled": True, "include": [], "exclude": [], "custom": False}
        enabled = raw.get("enabled") if isinstance(raw.get("enabled"), bool) else True
        return {
            "enabled": enabled,
            "include": _clean_repo_rel_list(raw.get("include")),
            "exclude": _clean_repo_rel_list(raw.get("exclude")),
            "custom": bool(raw),
        }

    def _repo_docs_entries(self, repo: Path, cfg: dict) -> tuple[list[tuple[str, bool]], set[str]]:
        """Stage 1: resolve scan entries as (rel, is_file) plus the set of explicitly included files."""
        if not cfg["enabled"]:
            return [], set()
        entries: list[tuple[str, bool]] = []
        explicit_files: set[str] = set()
        if cfg["include"]:
            for rel in cfg["include"]:
                parts = tuple(rel.split("/"))
                cur = repo
                ok = True
                st = None
                for i, part in enumerate(parts):
                    cur = cur / part
                    try:
                        st = os.lstat(cur)
                    except OSError:
                        ok = False
                        break
                    if stat.S_ISLNK(st.st_mode):
                        ok = False
                        break
                    if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
                        ok = False
                        break
                if not ok or st is None:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    entries.append((rel, False))
                elif stat.S_ISREG(st.st_mode):
                    entries.append((rel, True))
                    explicit_files.add(rel)
            return entries, explicit_files

        if self._safe_subdir(repo, "docs") is not None:
            entries.append(("docs", False))
        elif self._safe_subdir(repo, "doc") is not None:
            entries.append(("doc", False))
        for d in REPO_DOCS_DEFAULT_ROOT_DIRS:
            if self._safe_subdir(repo, d) is not None:
                entries.append((d, False))
        try:
            with os.scandir(repo) as it:
                names = sorted(e.name for e in it if e.name.lower() in REPO_DOCS_DEFAULT_ROOT_FILES)
        except OSError:
            names = []
        for name in names:
            try:
                st = os.lstat(repo / name)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode):
                entries.append((name, True))
        return entries, explicit_files

    @staticmethod
    def _repo_docs_match_entry(
        parts: tuple[str, ...],
        entries: list[tuple[str, bool]],
        explicit_files: set[str],
        excludes: list[str],
    ) -> tuple[int, int] | None:
        """Stage 3 & tier classification: return (tier, entry_len) if `parts` passes all repo_docs filters, else None."""
        if not parts:
            return None
        rel = "/".join(parts)
        for ex in excludes:
            if rel == ex or rel.startswith(ex + "/"):
                return None
        # Cross-root deduplication: research and instructions already own these.
        if len(parts) >= 2 and parts[0].lower() == "docs" and parts[1].lower() == "research":
            return None
        if parts[0].lower() == "evidence":
            return None
        if rel in INSTRUCTION_FILES:
            return None
        # Reject hidden / framework segments and blacklisted directories.
        if any(seg.startswith((".", "_")) for seg in parts):
            return None
        if any(seg.lower() in REPO_DOCS_SKIP_DIRS for seg in parts[:-1]):
            return None
        is_explicit = rel in explicit_files
        ext = Path(parts[-1]).suffix.lower()
        if is_explicit:
            if ext not in TEXT_EXTENSIONS and ext not in REPO_DOC_EXTENSIONS:
                return None
        else:
            if ext not in REPO_DOC_EXTENSIONS:
                return None
            if parts[-1].lower() in REPO_DOCS_SKIP_FILES:
                return None
        # Match against active entries and enforce depth cap relative to the entry directory.
        matched_entry_len: int | None = None
        for entry_rel, is_file in entries:
            if is_file:
                if rel == entry_rel:
                    matched_entry_len = 0
                    break
            else:
                e_parts = tuple(entry_rel.split("/"))
                if len(parts) > len(e_parts) and parts[:len(e_parts)] == e_parts:
                    rel_depth = len(parts) - len(e_parts)
                    if rel_depth <= REPO_DOCS_DEPTH:
                        matched_entry_len = len(e_parts)
                        break
        if matched_entry_len is None:
            return None
        # Tier 0: explicit single file from library.json
        # Tier 1: design/specs/adr/rfcs/architecture path segment or root ARCHITECTURE.md / DESIGN.md
        # Tier 2: direct child of a scanned entry directory
        # Tier 3: everything else
        if is_explicit:
            tier = 0
        elif (any(seg.lower() in REPO_DOCS_DESIGN_SEGMENTS for seg in parts[:-1])
              or (len(parts) == 1 and parts[0].lower() in REPO_DOCS_DEFAULT_ROOT_FILES)):
            tier = 1
        elif matched_entry_len > 0 and len(parts) == matched_entry_len + 1:
            tier = 2
        else:
            tier = 3
        return tier, matched_entry_len

    @staticmethod
    def _is_git_repo(repo: Path) -> bool:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=5,
            )
            return proc.returncode == 0 and proc.stdout.strip() == b"true"
        except (OSError, subprocess.SubprocessError):
            return False

    def _repo_docs_enumerate(self, repo: Path, entries: list[tuple[str, bool]]) -> list[tuple[str, ...]]:
        """Stage 2: enumerate candidate paths via `git ls-files` (falling back to safe tree walk outside Git)."""
        if not entries:
            return []
        entry_args = [rel for rel, _ in entries]
        try:
            proc = subprocess.run(
                ["git", "--literal-pathspecs", "-C", str(repo), "ls-files", "-z", "--", *entry_args],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            proc = None
        if proc is not None and proc.returncode == 0:
            found: list[tuple[str, ...]] = []
            seen: set[str] = set()
            for chunk in proc.stdout.split(b"\x00"):
                if not chunk:
                    continue
                try:
                    rel = chunk.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if rel.startswith("./"):
                    rel = rel[2:]
                rel = rel.lstrip("/")
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                try:
                    found.append(_split_rel(rel))
                except ValueError:
                    continue
            return found
        # Non-Git fallback: safe directory traversal skipping symlinks and dotfiles.
        found = []
        seen = set()
        for entry_rel, is_file in entries:
            e_parts = tuple(entry_rel.split("/"))
            if is_file:
                if entry_rel not in seen:
                    seen.add(entry_rel)
                    found.append(e_parts)
                continue
            sub = self._subdirs(repo, *e_parts)
            if sub is None:
                continue
            for rel_parts, _st, _file in self._scan_tree(sub, max_depth=REPO_DOCS_DEPTH, files_only=True):
                full_parts = (*e_parts, *rel_parts)
                full_rel = "/".join(full_parts)
                if full_rel not in seen:
                    seen.add(full_rel)
                    found.append(full_parts)
        return found

    def repo_docs_settings(self, slug: str) -> dict:
        """Repository doc scanning has been removed from Library (`deprecated: True`, always disabled)."""
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        return {
            "project": slug,
            "enabled": False,
            "deprecated": True,
            "include": [],
            "exclude": [],
            "custom": False,
            "entries": [],
        }

    def _repo_docs_items(self, slug: str) -> tuple[list[dict], dict]:
        """Discover, filter, bucket, and annotate repository documentation under root `repo_docs`."""
        repo = self._repo_dir(slug)
        meta_out = {"truncated": False, "total": 0}
        if repo is None:
            return [], meta_out
        cfg = self._repo_docs_config(slug)
        entries, explicit_files = self._repo_docs_entries(repo, cfg)
        if not entries:
            return [], meta_out
        raw_candidates = self._repo_docs_enumerate(repo, entries)
        filtered: list[tuple[int, str, tuple[str, ...], os.stat_result, Path, int]] = []
        for parts in raw_candidates:
            matched = self._repo_docs_match_entry(parts, entries, explicit_files, cfg["exclude"])
            if matched is None:
                continue
            tier, entry_len = matched
            rel = "/".join(parts)
            try:
                file, st = self._walk_file(repo, parts, rel)
            except (FileNotFoundError, DamagedFileError, UnreadableFileError):
                continue
            filtered.append((tier, rel.lower(), parts, st, file, entry_len))
        filtered.sort(key=lambda item: (item[0], item[1]))
        total = len(filtered)
        truncated = total > REPO_DOCS_MAX
        kept = filtered[:REPO_DOCS_MAX]
        meta_out = {"truncated": truncated, "total": total}
        if not kept:
            return [], meta_out

        tasks = self.tasks(slug)
        by_id = {t.get("id"): t for t in tasks if t.get("id")}
        folder_rows: dict[tuple[str, ...], dict] = {}
        file_rows: list[dict] = []
        for _tier, _key, parts, st, file, entry_len in kept:
            # Emit folder rows for subdirectories inside each scanned entry (e.g. `docs/design`).
            if entry_len > 0 and len(parts) > entry_len + 1:
                for depth in range(entry_len + 1, len(parts)):
                    fparts = parts[:depth]
                    if fparts not in folder_rows:
                        try:
                            fst = os.lstat(repo.joinpath(*fparts))
                        except OSError:
                            fst = st
                        frow = self._file_row("repo_docs", fparts, fst)
                        frow["kind"] = "folder"
                        frow["size"] = 0
                        frow["writable"] = False
                        folder_rows[fparts] = frow
            row = self._file_row("repo_docs", parts, st)
            row.update(version=_version_of(st), writable=False)
            ext = Path(parts[-1]).suffix.lower()
            if ext in (".md", ".markdown", ".mdx") and st.st_size <= DOCUMENT_MAX:
                meta = _read_doc_meta(file)
                if meta.get("title"):
                    row["title"] = meta["title"]
                if meta.get("summary"):
                    row["summary"] = meta["summary"]
                task = meta.get("task") if meta.get("task") in by_id else ""
                if not task:
                    stem = Path(parts[-1]).stem
                    if len(stem) >= 3 and stem.lower() not in GENERIC_DOC_STEMS:
                        task = self._task_for_topic(slug, stem, tasks)
                if task:
                    row["task"] = task
                    title = (by_id.get(task) or {}).get("title")
                    if title:
                        row["task_title"] = str(title)
            file_rows.append(row)
        rows = [folder_rows[k] for k in sorted(folder_rows)] + file_rows
        return rows, meta_out

    def _docs_items(self, slug: str) -> list[dict]:
        rows: list[dict] = []
        docs = self._context_root_dir(slug, "docs")
        if docs is not None:
            for parts, st, file in self._scan_tree(docs, skip_top=frozenset({DOCS_RESEARCH})):
                row = self._file_row("docs", parts, st)
                row["writable"] = True
                if not stat.S_ISDIR(st.st_mode):
                    row["version"] = _version_of(st)
                    if row["kind"] in ("md", "markdown") and st.st_size <= DOCUMENT_MAX:
                        meta = _read_doc_meta(file)
                        if meta.get("title"):
                            row["title"] = meta["title"]
                rows.append(row)
        proj = self._context_root_dir(slug, "project")
        if proj is not None:
            try:
                file, st = self._walk_file(proj, (DECISIONS_FILE,), DECISIONS_FILE)
            except (FileNotFoundError, DamagedFileError, UnreadableFileError):
                file = None
            if file is not None:
                state = (self.library_state(slug).get("decisions") or {})
                row = self._file_row("docs", (DECISIONS_FILE,), st)
                entries = 0
                if st.st_size <= DOCUMENT_MAX:
                    with contextlib.suppress(OSError):
                        entries = sum(1 for line in file.read_text(encoding="utf-8", errors="replace").splitlines()
                                      if line.startswith("- "))
                row.update(version=_version_of(st), writable=False, archive=True,
                           hidden=bool(state.get("hidden")), entries=entries)
                rows.append(row)
        return rows

    def library(self, slug: str) -> dict:
        """The Library of a project, decoupled from workspace folders:

        docs: projects/<slug>/docs/** (editable, files can be dropped in) and decisions.md as a read-only archive
        row (`archive: true`, `hidden` once its decisions are all in memory); research: project-owned ledger
        reports in `projects/<slug>/docs/research/**.md` and unmigrated `projects/<slug>/research/<topic>/README.md`.
        """
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        return {
            "project": slug,
            "roots": [
                {"id": "docs", "writable": True, "accepts": {
                    "extensions": sorted(ADD_EXTENSIONS), "max_bytes": ADD_MAX, "edit_max_bytes": DOCUMENT_MAX}},
                {"id": "research", "writable": False},
            ],
            "files": self._docs_items(slug) + self._research_items(slug),
        }

    def _is_tracked_repo_file(self, repo: Path, rel: str) -> bool:
        """True iff `rel` is an exact git-tracked path in `repo`."""
        try:
            proc = subprocess.run(
                ["git", "--literal-pathspecs", "-C", str(repo), "ls-files", "-z", "--error-unmatch", "--", rel],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if proc.returncode != 0:
            return False
        return rel.encode("utf-8") in proc.stdout.split(b"\x00")

    @staticmethod
    def _scan_non_git_files(folder: Path, cap: int) -> tuple[list[str], bool]:
        """Safe directory walk for a non-Git folder: skips symlinks, dotfiles, and heavy build directories."""
        hard_cap = max(1, min(int(cap), NON_GIT_FILES_MAX))
        files: list[str] = []
        truncated = False
        stack: list[tuple[Path, tuple[str, ...]]] = [(folder, ())]
        while stack and not truncated:
            cur_dir, prefix = stack.pop()
            try:
                with os.scandir(cur_dir) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            subdirs: list[tuple[Path, tuple[str, ...]]] = []
            for entry in entries:
                name = entry.name
                if not name or name.startswith("."):
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if name.lower() in NON_GIT_SKIP_DIRS:
                        continue
                    subdirs.append((Path(entry.path), (*prefix, name)))
                elif stat.S_ISREG(st.st_mode):
                    if len(files) >= hard_cap:
                        truncated = True
                        break
                    files.append("/".join((*prefix, name)))
            for sub in reversed(subdirs):
                stack.append(sub)
        return files, truncated

    def _list_folder_files(self, folder: Path, cap: int) -> tuple[list[str], bool]:
        """List files inside one workspace folder (`git ls-files -z` for Git repos, else `_scan_non_git_files`)."""
        if not self._is_git_repo(folder):
            return self._scan_non_git_files(folder, cap)
        files: list[str] = []
        truncated = False
        try:
            proc = subprocess.run(
                ["git", "-C", str(folder), "ls-files", "-z"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=15,
            )
            if proc.returncode == 0:
                seen: set[str] = set()
                for chunk in proc.stdout.split(b"\x00"):
                    if not chunk:
                        continue
                    try:
                        rel = chunk.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    if rel.startswith("./"):
                        rel = rel[2:]
                    rel = rel.lstrip("/")
                    if not rel or rel == ".git" or rel.startswith(".git/") or "/.git/" in rel:
                        continue
                    if rel in seen:
                        continue
                    seen.add(rel)
                    if len(files) >= cap:
                        truncated = True
                        break
                    files.append(rel)
        except (OSError, subprocess.SubprocessError):
            pass
        return files, truncated

    def repo_files(self, slug: str, *, limit: int = REPO_FILES_MAX) -> dict:
        """Aggregate files across all linked folders of `slug` (`<alias>/` prefixed when >= 2 folders)."""
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        cap = max(1, min(int(limit), 50_000))
        folders = self._project_folders(slug)
        if not folders:
            return {"project": slug, "files": [], "truncated": False}
        if len(folders) == 1:
            _entry, fdir = folders[0]
            files, truncated = self._list_folder_files(fdir, cap)
            return {"project": slug, "files": files, "truncated": truncated}

        base_quota = max(1, cap // len(folders))
        raw_per_folder: list[tuple[str, list[str], bool]] = []
        any_truncated = False
        # First pass up to cap so folders with fewer files leave room for larger ones.
        for entry, fdir in folders:
            alias = str(entry.get("alias") or fdir.name or "folder")
            items, trunc = self._list_folder_files(fdir, cap)
            raw_per_folder.append((alias, items, trunc))
            if trunc:
                any_truncated = True

        selected: list[list[str]] = [[] for _ in folders]
        used = 0
        # Fair round 1: guarantee each folder up to `base_quota` slots.
        for idx, (_alias, items, _trunc) in enumerate(raw_per_folder):
            take = min(len(items), base_quota, cap - used)
            selected[idx] = items[:take]
            used += take
            if len(items) > take:
                any_truncated = True
        # Round 2: redistribute unused headroom in folder order up to `cap`.
        if used < cap:
            for idx, (_alias, items, _trunc) in enumerate(raw_per_folder):
                if used >= cap:
                    break
                cur = len(selected[idx])
                if len(items) > cur:
                    extra = min(len(items) - cur, cap - used)
                    selected[idx].extend(items[cur:cur + extra])
                    used += extra
                    if len(items) > len(selected[idx]):
                        any_truncated = True
        files_out: list[str] = []
        for idx, (alias, _items, _trunc) in enumerate(raw_per_folder):
            for rel in selected[idx]:
                files_out.append(f"{alias}/{rel}")
        return {"project": slug, "files": files_out, "truncated": any_truncated}

    # ---- reading one document ------------------------------------------------------------------------------

    def _walk_file(self, real_base: Path, parts: tuple[str, ...], label: str) -> tuple[Path, os.stat_result]:
        """base/parts as a regular file reached through plain folders only, resolving inside base."""
        cur = real_base
        st = None
        for i, part in enumerate(parts):
            cur = cur / part
            try:
                st = os.lstat(cur)
            except (FileNotFoundError, NotADirectoryError):
                raise FileNotFoundError(f"no such document: {label}") from None
            except OSError as err:
                raise UnreadableFileError(err.errno, f"cannot stat {label}: {err.strerror or err}", str(cur)) from err
            if stat.S_ISLNK(st.st_mode):
                raise FileNotFoundError(f"no such document: {label}")
            if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
                raise FileNotFoundError(f"no such document: {label}")
        if st is None or stat.S_ISDIR(st.st_mode):
            raise FileNotFoundError(f"no such document: {label}")
        if not stat.S_ISREG(st.st_mode):
            raise DamagedFileError(f"{label} is not a regular file")
        try:
            resolved = cur.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            raise FileNotFoundError(f"no such document: {label}") from None
        except OSError as err:
            raise UnreadableFileError(err.errno, f"cannot resolve {label}: {err.strerror or err}", str(cur)) from err
        if resolved == real_base or not _is_within(resolved, real_base):
            raise FileNotFoundError(f"no such document: {label}")
        return cur, st

    def _newest_of(self, bases: list[Path], parts: tuple[str, ...], label: str,
                   skip_marked: bool = False) -> tuple[Path, os.stat_result]:
        best: tuple[Path, os.stat_result] | None = None
        for base in bases:
            if skip_marked and _has_marker(base / parts[0], RENDER_CHECK_MARKER):
                continue
            try:
                got = self._walk_file(base, parts, label)
            except FileNotFoundError:
                continue
            if best is None or got[1].st_mtime > best[1].st_mtime:
                best = got
        if best is None:
            raise FileNotFoundError(f"no such document: {label}")
        return best

    def _locate(self, slug: str, root: str, parts: tuple[str, ...], label: str) -> tuple[Path, os.stat_result]:
        """The file a `<root>/<path>` names, by the allow-list of each root; FileNotFoundError for anything else."""
        missing = FileNotFoundError(f"no such document: {label}")
        if root not in ("instructions", "repo") and any(p.startswith(".") for p in parts):
            raise missing
        if root == "research":
            if parts[0] == RESEARCH_FOLDER:
                if len(parts) != 3 or parts[2] != RESEARCH_FILENAME or is_excluded_research_topic(parts[1]):
                    raise missing
                return self._newest_of(self._research_root_dirs(slug, include_repo=False), parts[1:], label, skip_marked=True)
            if parts[:2] == (DOCS_FOLDER, DOCS_RESEARCH) and len(parts) >= 3:
                if Path(parts[-1]).suffix.lower() not in (".md", ".markdown"):
                    raise missing
                base = self._ledger_research_dir(slug)
                if base is None:
                    raise missing
                return self._walk_file(base, parts[2:], label)
            if len(parts) != 2 or parts[1] != RESEARCH_FILENAME or is_excluded_research_topic(parts[0]):
                raise missing
            return self._newest_of(self._research_root_dirs(slug), parts, label, skip_marked=True)
        if root in ("instructions", "repo_docs"):
            raise missing
        if root == "repo":
            if any(p == ".git" for p in parts):
                raise missing
            folders = self._project_folders(slug)
            if not folders:
                raise missing
            if len(folders) == 1:
                fdir = folders[0][1]
                sub_parts = parts
            else:
                if len(parts) < 2:
                    raise missing
                alias = parts[0]
                matched = next((fdir for entry, fdir in folders if entry.get("alias") == alias), None)
                if matched is None:
                    raise missing
                fdir = matched
                sub_parts = parts[1:]
            rel = "/".join(sub_parts)
            if self._is_git_repo(fdir):
                if not self._is_tracked_repo_file(fdir, rel):
                    raise missing
            else:
                if any(p.startswith(".") for p in sub_parts):
                    raise missing
                if any(p.lower() in NON_GIT_SKIP_DIRS for p in sub_parts[:-1]):
                    raise missing
            return self._walk_file(fdir, sub_parts, label)
        if root in ("user", "personal", "memory"):
            if len(parts) != 1 or not parts[0].endswith(".md") or parts[0] == "MEMORY.md":
                raise missing
            base = self._context_root_dir(slug, root)
        elif root == "docs":
            if parts == (DECISIONS_FILE,):
                base = self._context_root_dir(slug, "project")
            elif parts[0].lower() == DOCS_RESEARCH:
                raise missing
            else:
                base = self._context_root_dir(slug, "docs")
        else:  # project: the old panel's names for the same allow-list (plus unmigrated top-level *.md docs)
            allowed = ((len(parts) == 1 and parts[0].lower().endswith((".md", ".markdown"))
                        and parts[0].lower() != "handover.md")
                       or (parts[0] == DOCS_FOLDER and len(parts) >= 2)
                       or (parts[0] == "memory" and len(parts) == 2 and parts[1].endswith(".md")
                           and parts[1] != "MEMORY.md"))
            if not allowed:
                raise missing
            base = self._context_root_dir(slug, "project")
        if base is None:
            raise missing
        return self._walk_file(base, parts, label)

    def document_path(self, slug: str, root: str, path: str) -> tuple[Path, os.stat_result]:
        """(file, stat) of a document, with the same checks as `document`."""
        if not valid_slug(slug):
            raise ValueError(f"invalid project slug: {slug!r}")
        if root not in DOCUMENT_ROOTS:
            raise ValueError(f"invalid document root: {root!r}")
        return self._locate(slug, root, _split_rel(path), f"{root}/{path}")

    def document(self, slug: str, root: str, path: str) -> str:
        cur, st = self.document_path(slug, root, path)
        label = f"{root}/{path}"
        ext = Path(cur.name).suffix.lower()
        if ext in IMAGE_EXTENSIONS or ext == ".svg":
            raise DamagedFileError("not a text file")
        if st.st_size > DOCUMENT_MAX:
            raise DamagedFileError("too large to read whole")

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(cur, flags)
        except (FileNotFoundError, NotADirectoryError):
            raise FileNotFoundError(f"no such document: {label}") from None
        except OSError as err:
            if err.errno in _SYMLINK_OPEN_ERRNOS:
                raise FileNotFoundError(f"no such document: {label}") from None
            raise UnreadableFileError(err.errno, f"cannot read {label}: {err.strerror or err}", str(cur)) from err
        try:
            with os.fdopen(fd, "rb") as f:
                opened = os.fstat(f.fileno())
                if not stat.S_ISREG(opened.st_mode):
                    raise DamagedFileError(f"{label} is not a regular file")
                if not os.path.samestat(st, opened):
                    raise FileNotFoundError(f"no such document: {label}")
                if opened.st_size > DOCUMENT_MAX:
                    raise DamagedFileError("too large to read whole")
                data = f.read(DOCUMENT_MAX + 1)
        except (FileNotFoundError, DamagedFileError):
            raise
        except OSError as err:
            raise UnreadableFileError(err.errno, f"cannot read {label}: {err.strerror or err}", str(cur)) from err

        if len(data) > DOCUMENT_MAX:
            raise DamagedFileError("too large to read whole")
        if b"\x00" in data:
            raise DamagedFileError("not a text file")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as err:
            raise DamagedFileError("not a text file") from err

    # ---- writing docs: save, delete (kept in .history), restore, drop a file in ---------------------------------

    def _docs_base(self, slug: str, *, create: bool = False) -> Path:
        proj = self._project_folder(slug, create=create)
        docs = self._safe_subdir(proj, DOCS_FOLDER)
        if docs is None and create:
            with contextlib.suppress(FileExistsError):
                os.mkdir(proj / DOCS_FOLDER)
            docs = self._safe_subdir(proj, DOCS_FOLDER)
            if docs is None:
                raise ValueError("projects/<slug>/docs is not a plain folder")
        if docs is None:
            raise FileNotFoundError("no such document")
        return docs

    @staticmethod
    def _ensure_dirs(base: Path, names: tuple[str, ...]) -> Path:
        cur = base
        for name in names:
            cur = cur / name
            try:
                st = os.lstat(cur)
            except FileNotFoundError:
                os.mkdir(cur)
                st = os.lstat(cur)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise ValueError(f"{cur.name} is not a plain folder")
        return cur

    @staticmethod
    def _writable_doc_parts(path: str) -> tuple[str, ...]:
        parts = _split_rel(path)
        if any(p.startswith(".") for p in parts):
            raise ValueError("names starting with a dot are not kept in docs")
        if any(len(p.encode("utf-8")) > 255 for p in parts):
            raise ValueError("a name in that path is too long")
        if parts[0].lower() == DOCS_RESEARCH:
            raise ValueError("docs/research holds research reports, which are read-only here")
        if parts == (DECISIONS_FILE,):
            raise ValueError("decisions.md is the decisions log (`pm.py decide` writes it); it is not edited here")
        return parts

    @staticmethod
    def _next_history_stamp(hist: Path, name: str, *, clock=None) -> str:
        stamp = base = _history_stamp(clock)
        n = 2
        while any(os.path.lexists(hist / f"{name}.{stamp}.{w}") for w in ("deleted", "replaced")):
            stamp, n = f"{base}-{n:02d}", n + 1
        return stamp

    def _to_history(self, docs: Path, parts: tuple[str, ...], file: Path, why: str) -> str:
        """Move `file` (docs/parts) into docs/.history/<parts>.<stamp>.<why>; returns the stamp."""
        hist = self._ensure_dirs(docs, (HISTORY_FOLDER, *parts[:-1]))
        stamp = self._next_history_stamp(hist, parts[-1], clock=self._clock)
        os.replace(file, hist / f"{parts[-1]}.{stamp}.{why}")
        return stamp

    def _copy_to_history(self, docs: Path, parts: tuple[str, ...], data: bytes) -> str:
        hist = self._ensure_dirs(docs, (HISTORY_FOLDER, *parts[:-1]))
        stamp = self._next_history_stamp(hist, parts[-1], clock=self._clock)
        write_atomic(hist / f"{parts[-1]}.{stamp}.replaced", data)
        return stamp

    @staticmethod
    def _check_version(st, if_version: str | None, label: str) -> None:
        if if_version is None:
            return
        current = _version_of(st) if st is not None else ""
        if if_version == "new" and st is None:
            return
        if if_version != current:
            raise VersionConflict(f"{label} changed since it was read", current)

    @staticmethod
    def _existing(file: Path):
        try:
            st = os.lstat(file)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise ValueError(f"{file.name} is not a regular file")
        return st

    def save_doc(self, slug: str, path: str, data: bytes, *, if_version: str | None = None) -> dict:
        """Create or replace a text document under docs/; what it said before goes to docs/.history.
        if_version: the `version` it was read at ("new": it must not exist yet); VersionConflict otherwise."""
        parts = self._writable_doc_parts(path)
        if Path(parts[-1]).suffix.lower() not in TEXT_EXTENSIONS:
            raise ValueError("only text documents are edited here (Markdown, plain text, …); drop other files in")
        if len(data) > DOCUMENT_MAX:
            raise ValueError(f"too large: a document edited here is at most {DOCUMENT_MAX} bytes")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("not UTF-8 text") from None
        if b"\x00" in data:
            raise ValueError("not a text file")
        with file_lock(self._locks_dir() / f"docs-{slug}.lock"):
            docs = self._docs_base(slug, create=True)
            target = self._ensure_dirs(docs, parts[:-1]) / parts[-1]
            st = self._existing(target)
            self._check_version(st, if_version, f"docs/{path}")
            if st is not None:
                old = target.read_bytes()
                if old == data:
                    return {"root": "docs", "path": path, "version": _version_of(st), "created": False}
                self._copy_to_history(docs, parts, old)
            write_atomic(target, data)
            return {"root": "docs", "path": path, "version": _version_of(os.lstat(target)), "created": st is None}

    def delete_doc(self, slug: str, path: str, *, if_version: str | None = None) -> dict:
        """Move a document under docs/ into docs/.history (restore_doc brings it back); an empty folder is removed."""
        parts = self._writable_doc_parts(path)
        with file_lock(self._locks_dir() / f"docs-{slug}.lock"):
            docs = self._docs_base(slug)
            folder = self._subdirs(docs, *parts)
            if folder is not None:
                try:
                    os.rmdir(folder)
                except OSError:
                    raise ValueError(f"docs/{path} is a folder that is not empty: delete what is in it first") from None
                return {"root": "docs", "path": path, "kind": "folder", "deleted": True}
            file, st = self._walk_file(docs, parts, f"docs/{path}")
            self._check_version(st, if_version, f"docs/{path}")
            stamp = self._to_history(docs, parts, file, "deleted")
            return {"root": "docs", "path": path, "deleted": True, "history": stamp}

    def doc_history(self, slug: str, path: str | None = None) -> list[dict]:
        """What docs/.history holds, newest first: [{"root", "path", "version", "why", "size", "at"}]."""
        want = self._writable_doc_parts(path) if path else None
        try:
            docs = self._docs_base(slug)
        except FileNotFoundError:
            return []
        hist = self._safe_subdir(docs, HISTORY_FOLDER)
        rows: list[dict] = []
        if hist is None:
            return rows
        for parts, st, _ in self._scan_tree(hist, files_only=True):
            m = HISTORY_NAME_RE.match(parts[-1])
            if not m:
                continue
            rel = (*parts[:-1], m.group("name"))
            if want is not None and rel != want:
                continue
            rows.append({"root": "docs", "path": "/".join(rel), "version": m.group("stamp"), "why": m.group("why"),
                         "size": st.st_size, "at": _mtime_iso(st.st_mtime)})
        rows.sort(key=lambda r: (r["version"], r["path"]), reverse=True)
        return rows

    def restore_doc(self, slug: str, path: str, version: str | None = None) -> dict:
        """Bring a document back from docs/.history (the newest kept version, or `version`); what is there now, if
        anything, goes to the history in its place."""
        parts = self._writable_doc_parts(path)
        with file_lock(self._locks_dir() / f"docs-{slug}.lock"):
            kept = [r for r in self.doc_history(slug, path) if version in (None, r["version"])]
            if not kept:
                raise FileNotFoundError(f"nothing kept for docs/{path}" + (f" at {version}" if version else ""))
            pick = kept[0]
            docs = self._docs_base(slug)
            hist = self._subdirs(docs, HISTORY_FOLDER, *parts[:-1])
            source = (hist / f"{parts[-1]}.{pick['version']}.{pick['why']}") if hist is not None else None
            if source is None or self._existing(source) is None:
                raise FileNotFoundError(f"nothing kept for docs/{path}")
            target = self._ensure_dirs(docs, parts[:-1]) / parts[-1]
            if self._existing(target) is not None:
                self._to_history(docs, parts, target, "replaced")
            os.replace(source, target)
            return {"root": "docs", "path": path, "restored": pick["version"],
                    "version": _version_of(os.lstat(target))}

    def add_doc(self, slug: str, source: str | Path, *, folder: str = "", name: str | None = None,
                replace: bool = False) -> dict:
        """Copy a file dropped into the Library into docs/[folder/]: text, Markdown, PDF or an image of at most
        ADD_MAX bytes. A name already taken gets -2, -3, … unless `replace` (the old one goes to the history)."""
        src = Path(source)
        try:
            sst = os.stat(src)
        except OSError as err:
            raise FileNotFoundError(f"cannot read {src}: {err.strerror or err}") from None
        if not stat.S_ISREG(sst.st_mode):
            raise ValueError(f"{src.name} is not a regular file (folders are not taken)")
        if sst.st_size > ADD_MAX:
            raise ValueError(f"{src.name} is {sst.st_size} bytes: at most {ADD_MAX // (1 << 20)} MB is taken")
        name = (name or src.name).strip()
        if not name or "/" in name or "\\" in name or "\x00" in name or name in (".", ".."):
            raise ValueError(f"invalid file name: {name!r}")
        ext = Path(name).suffix.lower()
        if ext not in ADD_EXTENSIONS:
            raise ValueError(f"{ext or 'a file without an extension'}: only text, Markdown, PDF and image files are "
                             "taken")
        prefix = self._writable_doc_parts(folder) if folder else ()
        parts = self._writable_doc_parts("/".join((*prefix, name)))
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        with open(os.open(src, flags), "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ValueError(f"{src.name} is not a regular file")
            data = f.read(ADD_MAX + 1)
        if len(data) > ADD_MAX:
            raise ValueError(f"{src.name}: at most {ADD_MAX // (1 << 20)} MB is taken")
        with file_lock(self._locks_dir() / f"docs-{slug}.lock"):
            docs = self._docs_base(slug, create=True)
            parent = self._ensure_dirs(docs, parts[:-1])
            final, stem, n = parts[-1], Path(parts[-1]).stem, 2
            replaced = False
            if self._existing(parent / final) is not None:
                if replace:
                    self._to_history(docs, parts, parent / final, "replaced")
                    replaced = True
                else:
                    while os.path.lexists(parent / final):
                        final, n = f"{stem}-{n}{Path(parts[-1]).suffix}", n + 1
            write_atomic(parent / final, data)
            rel = "/".join((*parts[:-1], final))
            return {"root": "docs", "path": rel, "size": len(data), "version": _version_of(os.lstat(parent / final)),
                    "renamed": final != parts[-1], "replaced": replaced}


def _has_event_after(f, start: int, whole_end: int) -> bool:
    """Whether [start, whole_end) holds at least one more complete event line."""
    if start >= whole_end:
        return False
    f.seek(start)
    at = start
    buf = bytearray()
    too_long = False
    line_len = 0
    while at + line_len < whole_end:
        chunk = f.read(min(BLOCK_SIZE, whole_end - (at + line_len)))
        if not chunk:
            return False
        pos = 0
        while True:
            nl = chunk.find(b"\n", pos)
            if nl < 0:
                piece = chunk[pos:]
                line_len += len(piece)
                if line_len > LINE_MAX:
                    too_long = True
                    buf.clear()
                elif not too_long:
                    buf.extend(piece)
                break
            piece = chunk[pos:nl]
            total = line_len + len(piece)
            line_end = at + total + 1
            if not too_long and total <= LINE_MAX:
                raw = bytes(buf) + piece if buf else piece
                if _parse_event_line(raw, line_end) is not None:
                    return True
            buf.clear()
            too_long = False
            line_len = 0
            at = line_end
            pos = nl + 1
    return False
