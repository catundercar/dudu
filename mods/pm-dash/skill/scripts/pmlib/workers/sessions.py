"""Sessions and tasks: recording a worker's or a PM's session on its record, the folders a task's agent runs in,
which session is a task's (recorded, or found among the transcripts and claimed by no other task), and the session
descriptors `state` shows. Layer 3; reading the transcripts themselves is agents/sessions.py."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
import urllib.parse
import urllib.request

from ..agents.sessions import claude_folder, first_cwd, pm_sessions, session_score
from ..caller import Caller
from ..context import Context
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..ledger.task import ACTIVE, ATTACHED, Task, created_at
from ..project.project import in_scope
from ..store import registration_slug


def _worker_raw_task(task: Any) -> dict[str, Any]:
    return task.raw if isinstance(task, Task) else task


def _worker_caller(ctx: Context) -> Caller:
    return ctx.caller if ctx.caller is not None else Caller(ctx)


def remember_pm_session_for(ctx: Context, rec: dict[str, Any], transcript: str = "", session_id: str = "") -> None:
    """Record the current Claude Code or Codex PM session on pms/<slug>.json when it is missing or changed."""
    repo = rec.get("repo")
    agent = rec.get("agent")
    if not repo or agent not in ("", "claude", "codex", None):
        return
    if agent == "codex":
        sid = session_id or ""
        path = str(Path(transcript)) if transcript else ""
        if not sid and path and Path(path).is_file():
            try:
                meta = (json.loads(Path(path).read_text(errors="replace").split("\n", 1)[0]) or {}).get("payload") or {}
                sid = str(meta.get("id") or "")
            except (OSError, ValueError, AttributeError):
                sid = ""
        if not sid:
            return
        wanted: dict[str, Any] = {"kind": "codex", "id": sid, **({"path": path} if path else {})}
    else:
        env_sid = ctx.env.get("CLAUDE_CODE_SESSION_ID", "")
        sid = session_id or env_sid
        path = ""
        if transcript:
            p = Path(transcript)
            if not sid and p.suffix == ".jsonl":
                sid = p.stem
            path = str(p)
        if not sid and not path:
            return
        if not env_sid and agent != "claude":
            # Without explicit Claude markers, only accept transcripts inside Claude's projects folder.
            try:
                if not path or not Path(path).resolve().is_relative_to(ctx.agents.claude_projects.resolve()):
                    return
            except (OSError, ValueError):
                return
        wanted = {"kind": "claude"}
        if sid:
            wanted["id"] = sid
        if path:
            wanted["path"] = path
    if rec.get("agent_session") == wanted:
        return

    def _set_pm_session(cur: dict[str, Any] | None) -> dict[str, Any] | None:
        if cur is None or cur.get("pane") != rec.get("pane") or cur.get("agent_session") == wanted:
            return None
        if sid and sid in (cur.get("retired_sessions") or []):
            return None  # async Stop hook from a rotated-out session in the same seat terminal
        cur["agent_session"] = wanted
        return cur

    ctx.store.change_registration(project_slug(repo), _set_pm_session)


def clear_task_session_for(ctx: Context, task: Any) -> None:
    """Detach any previous worker's session when a task starts a fresh worker."""
    raw = _worker_raw_task(task)
    old = raw.pop("session", None)
    if isinstance(old, dict) and old.get("id"):
        prior = [s for s in (raw.get("prior_sessions") or []) if isinstance(s, str)]
        if old["id"] not in prior:
            prior.append(old["id"])
        raw["prior_sessions"] = prior[-8:]
    raw["session_since"] = ctx.clock.time()


def clear_task_session(task: Any) -> None:
    """Detach any previous worker's session when a task starts a fresh worker."""
    clear_task_session_for(Context.from_env(), task)


def task_workdirs_for(ctx: Context, task: Any) -> list[str]:
    """Folders this task's agent actually runs in, most specific first: worktree, in_place,
    the reviewed task's worktree/in_place for `*-review`, and repo."""
    raw = _worker_raw_task(task)
    places = [raw.get("worktree"), raw.get("in_place")]
    rev_of = raw.get("review_of")
    if (isinstance(rev_of, str) and rev_of and rev_of != raw.get("id")
            and re.fullmatch(r"[^/\\\s.][^/\\\s]*", rev_of) and ".." not in rev_of):
        parent_path = ctx.home.task(rev_of)
        if parent_path.is_file():
            try:
                parent = json.loads(parent_path.read_text())
                if isinstance(parent, dict):
                    places.extend((parent.get("worktree"), parent.get("in_place")))
            except (OSError, ValueError):
                pass
    places.append(raw.get("repo"))
    return list(dict.fromkeys(str(Path(p)) for p in places if p))


def valid_recorded_session(task: Any) -> dict[str, Any] | None:
    """The task's recorded session if well-formed and consistent with the current worker's kind, else None."""
    raw = _worker_raw_task(task)
    kept = raw.get("session")
    if not isinstance(kept, dict) or not kept.get("kind") or not kept.get("id"):
        return None
    dispatched_kind = dispatched_with(raw)[0]
    if dispatched_kind and kept["kind"] != dispatched_kind:
        return None
    return kept


def _cwd_matches_task_for(ctx: Context, task: Any, cwd: str) -> bool:
    """True when `cwd` (or current directory) is inside one of the task's working directories."""
    try:
        here = str(Path(cwd or os.getcwd()).resolve())
    except OSError:
        return False
    dirs = task_workdirs_for(ctx, task)
    if not dirs:
        return False
    for w in dirs:
        try:
            target = str(Path(w).resolve())
        except OSError:
            continue
        if in_scope(here, target) or in_scope(target, here):
            return True
    return False


def pm_session_info_for(ctx: Context, rec: dict[str, Any]) -> dict[str, Any] | None:
    """Session descriptor for a PM registration, read-only and O(1) (no transcript crawling)."""
    if rec.get("archived"):
        return None
    agent = rec.get("agent") or ""
    if agent and agent != "claude":
        return None
    repo = rec.get("repo") or ""
    pslug = registration_slug(rec) or (ctx.store.folder_project_slug(repo) if repo else "")
    hints = [repo] if repo else []
    if "agent_session" in rec:
        recorded = rec.get("agent_session")
        if isinstance(recorded, dict) and recorded.get("kind"):
            return {**recorded, "hints": hints}
        # Explicitly cleared (start / rotate / external claim / archive): do not fall back to stale taken-in.json.
        return None
    # Legacy fallback for already-running PMs before agent_session existed: taken-in.json tracks the latest transcript.
    if not repo and not pslug:
        return None
    mark_path = ctx.home.project_for(pslug or repo).taken_in
    if not mark_path.is_file():
        return None
    try:
        mark = json.loads(mark_path.read_text())
    except (OSError, ValueError):
        return None
    files = mark.get("files") if isinstance(mark, dict) else None
    if not isinstance(files, dict) or not files:
        return None
    last_path = next(reversed(files))
    prev_path = (rec.get("previous") or {}).get("transcript") or ""
    if not isinstance(last_path, str) or not last_path or last_path == prev_path:
        return None
    return {"kind": "claude", "id": Path(last_path).stem, "path": last_path, "hints": hints}


def task_session_info_for(
    ctx: Context,
    task: Any,
    sessions: Any = None,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Session descriptor for a task in `state`: kind-verified recorded session first, else bounded
    head-only discovery across task_workdirs for active Claude tasks."""
    raw = _worker_raw_task(task)
    hints = task_workdirs_for(ctx, raw)
    kept = valid_recorded_session(raw)
    if kept is not None:
        return {**kept, "hints": hints}
    if sessions is None or raw.get("status") not in ATTACHED:
        return None
    if dispatched_with(raw)[0] != "claude":
        return None
    tid = raw["id"]
    since = raw.get("session_since") if isinstance(raw.get("session_since"), (int, float)) else (created_at(raw) - 600)
    exclude = frozenset(s for s in (raw.get("prior_sessions") or []) if isinstance(s, str)) | claimed_sessions_for(ctx, raw, tasks)
    for place in hints:
        found = sessions.discover_claude_task(
            tid, place, since, lambda head: session_score(head, tid) == 2, exclude_ids=exclude
        )
        if found is not None:
            return found
    return None


def session_places_for(ctx: Context, task: Any, old_cwd: str = "") -> list[str]:
    """Folders the task's agent may have been started in."""
    raw = _worker_raw_task(task)
    places = [*task_workdirs_for(ctx, raw), *([old_cwd] if old_cwd else [])]
    home = Path.home()
    parent = Path(raw["repo"]).parent if raw.get("repo") else None
    while parent and parent != home and len(parent.parts) > 2:
        places.append(str(parent))
        parent = parent.parent
    return list(dict.fromkeys(str(Path(p)) for p in places))


def claimed_sessions_for(
    ctx: Context,
    task: Any,
    tasks: list[dict[str, Any]] | None = None,
) -> frozenset[str]:
    """Session ids recorded on tasks other than this one."""
    raw = _worker_raw_task(task)
    out: set[str] = set()
    try:
        pool = Ledger(ctx).raw_tasks() if tasks is None else tasks
    except (OSError, ValueError, AttributeError):
        return frozenset()
    for other in pool:
        other_raw = _worker_raw_task(other)
        if not isinstance(other_raw, dict) or other_raw.get("id") == raw.get("id"):
            continue
        kept = other_raw.get("session")
        if isinstance(kept, dict) and isinstance(kept.get("id"), str):
            out.add(kept["id"])
        out.update(s for s in (other_raw.get("prior_sessions") or []) if isinstance(s, str))
    return frozenset(out)


def claude_sessions_for(
    ctx: Context,
    task: Any,
    places: list[str],
    others: frozenset[str] = frozenset(),
) -> Iterator[dict[str, Any]]:
    raw = _worker_raw_task(task)
    since = raw.get("session_since") if isinstance(raw.get("session_since"), (int, float)) else (created_at(raw) - 600)
    exclude = set(s for s in (raw.get("prior_sessions") or []) if isinstance(s, str)) | set(others)
    c_projects = ctx.agents.claude_projects
    for place in places:
        folder = c_projects / claude_folder(place)
        for path in folder.glob("*.jsonl") if folder.is_dir() else []:
            if path.stem in exclude:
                continue
            try:
                if path.stat().st_mtime < since:
                    continue
                score = session_score(path.read_text(errors="replace"), raw["id"])
            except OSError:
                continue
            if score:
                yield {"kind": "claude", "id": path.stem, "path": str(path), "cwd": first_cwd(path) or place,
                       "score": score, "mtime": path.stat().st_mtime}


def codex_sessions_for(
    ctx: Context,
    task: Any,
    places: list[str],
    others: frozenset[str] = frozenset(),
) -> Iterator[dict[str, Any]]:
    raw = _worker_raw_task(task)
    since = created_at(raw) - 600
    c_sessions = ctx.agents.codex_sessions
    for path in c_sessions.rglob("rollout-*.jsonl") if c_sessions.is_dir() else []:
        try:
            if path.stat().st_mtime < since:
                continue
            text = path.read_text(errors="replace")
            meta = (json.loads(text.split("\n", 1)[0]) or {}).get("payload") or {}
        except (OSError, ValueError, AttributeError):
            continue
        cwd = str(meta.get("cwd") or "")
        if not meta.get("id") or not any(cwd == p or cwd.startswith(p + "/") for p in places):
            continue
        if str(meta["id"]) in others:
            continue
        score = session_score(text, raw["id"])
        if score:
            yield {"kind": "codex", "id": str(meta["id"]), "path": str(path), "cwd": cwd, "score": score,
                   "mtime": path.stat().st_mtime}


def _agy_uri_to_path(uri: str) -> str:
    text = str(uri or "").strip()
    if not text:
        return ""
    if text.lower().startswith("file://"):
        parsed = urllib.parse.urlparse(text)
        raw_path = urllib.request.url2pathname(parsed.path or "")
        if not raw_path:
            return ""
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            raw_path = f"//{parsed.netloc}{raw_path}"
        return raw_path
    return text


def _agy_read_summary_workspaces(agy_dir: Path) -> dict[str, list[str]]:
    db_path = agy_dir / "conversation_summaries.db"
    if not db_path.is_file():
        return {}
    out: dict[str, list[str]] = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.5)
        try:
            for cid, raw_uris in con.execute("SELECT conversation_id, workspace_uris FROM conversation_summaries"):
                if not cid:
                    continue
                paths: list[str] = []
                try:
                    items = json.loads(raw_uris or "[]")
                except ValueError:
                    items = []
                if isinstance(items, list):
                    for uri in items:
                        p = _agy_uri_to_path(str(uri or ""))
                        if p:
                            paths.append(p)
                out[str(cid)] = paths
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    return out


def _agy_opening_blob(path: Path, max_bytes: int = 256 << 10) -> str:
    """Read the opening of an agy transcript and append decoded USER_INPUT contents so session_score
    can match task ids and `update <id>` cleanly even across JSON escapes."""
    try:
        with open(path, "rb") as f:
            head = f.read(max_bytes).decode("utf-8", "replace")
    except OSError:
        return ""
    decoded_users: list[str] = []
    for line in head.split("\n")[:20]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("type") == "PLANNER_RESPONSE":
            break
        if row.get("type") == "USER_INPUT" and isinstance(row.get("content"), str):
            decoded_users.append(row["content"])
    if decoded_users:
        return "\n".join(decoded_users) + "\n" + head
    return head


def agy_sessions_for(
    ctx: Context,
    task: Any,
    places: list[str],
    others: frozenset[str] = frozenset(),
) -> Iterator[dict[str, Any]]:
    raw = _worker_raw_task(task)
    since = raw.get("session_since") if isinstance(raw.get("session_since"), (int, float)) else (created_at(raw) - 600)
    exclude = set(s for s in (raw.get("prior_sessions") or []) if isinstance(s, str)) | set(others)
    agy_dir = getattr(ctx, "agy_dir", None)
    if agy_dir is None:
        env_dir = (ctx.env or {}).get("AGY_DATA_DIR") if hasattr(ctx, "env") else ""
        agy_dir = Path(env_dir) if env_dir else (Path.home() / ".gemini" / "antigravity-cli")
    else:
        agy_dir = Path(agy_dir)
    brain = agy_dir / "brain"
    if not brain.is_dir():
        return
    norm_places: list[str] = []
    for p in places:
        if not p:
            continue
        norm_places.append(str(Path(p)))
        try:
            rp = str(Path(p).resolve())
            if rp not in norm_places:
                norm_places.append(rp)
        except OSError:
            pass

    summaries = _agy_read_summary_workspaces(agy_dir)
    matched_cwd: dict[str, str] = {}
    excluded_by_ws: set[str] = set()
    for cid, ws_paths in summaries.items():
        if not ws_paths:
            continue
        hit = ""
        for wp in ws_paths:
            candidates = [wp]
            try:
                rwp = str(Path(wp).resolve())
                if rwp not in candidates:
                    candidates.append(rwp)
            except OSError:
                pass
            if any(c == p or c.startswith(p + "/") for c in candidates for p in norm_places):
                hit = wp
                break
        if hit:
            matched_cwd[cid] = hit
        elif norm_places:
            excluded_by_ws.add(cid)

    candidates: list[tuple[int, float, str, Path]] = []
    try:
        entries = list(brain.iterdir())
    except OSError:
        return
    for conv_dir in entries:
        cid = conv_dir.name
        if cid in exclude or cid in excluded_by_ws or not conv_dir.is_dir():
            continue
        logs = conv_dir / ".system_generated" / "logs"
        tr_path = logs / "transcript_full.jsonl"
        if not tr_path.is_file():
            tr_path = logs / "transcript.jsonl"
            if not tr_path.is_file():
                continue
        try:
            mtime = tr_path.stat().st_mtime
        except OSError:
            continue
        if mtime < since:
            continue
        priority = 1 if cid in matched_cwd else 0
        candidates.append((priority, mtime, cid, tr_path))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _, mtime, cid, tr_path in candidates[:60]:
        blob = _agy_opening_blob(tr_path)
        if not blob:
            continue
        score = session_score(blob, raw["id"])
        if score:
            yield {
                "kind": "agy",
                "id": cid,
                "path": str(tr_path),
                "cwd": matched_cwd.get(cid, ""),
                "score": score,
                "mtime": mtime,
            }


def find_session_for(ctx: Context, task: Any, old_cwd: str = "") -> dict[str, Any] | None:
    """The session of the task's agent: the one the ledger recorded, else transcript discovery."""
    if getattr(ctx, "_legacy", False) and find_session is not _DEFAULT_FIND_SESSION:
        return find_session(task, old_cwd)
    return _find_session_impl(ctx, task, old_cwd)


def _find_session_impl(ctx: Context, task: Any, old_cwd: str = "") -> dict[str, Any] | None:
    raw = _worker_raw_task(task)
    kind = dispatched_with(raw)[0]
    if kind and kind not in ("claude", "codex", "agy"):
        return None
    kept = raw.get("session") or {}
    if kept.get("kind") == "claude" and kept.get("id") and kind in ("", "claude"):
        hints = [*task_workdirs_for(ctx, raw), *([old_cwd] if old_cwd else [])]
        reader = ctx.agents.sessions_reader()
        path = reader.transcript({**kept, "hints": hints}) if reader is not None else None
        if path is None and reader is None:
            sid = kept["id"]
            c_projects = ctx.agents.claude_projects
            if (isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", sid)
                    and ".." not in sid and c_projects.is_dir()):
                hits = [f / f"{sid}.jsonl" for f in c_projects.iterdir() if (f / f"{sid}.jsonl").is_file()]
                path = max(hits, key=lambda p: p.stat().st_mtime) if hits else None
        if path:
            return {"kind": "claude", "id": kept["id"], "path": str(path), "cwd": first_cwd(path)}
    if kept.get("kind") == "agy" and kept.get("id") and kind in ("", "agy"):
        reader = ctx.agents.sessions_reader()
        path = reader.transcript(kept) if reader is not None else None
        if path:
            return {"kind": "agy", "id": kept["id"], "path": str(path), "cwd": ""}
    places = session_places_for(ctx, raw, old_cwd)
    others = claimed_sessions_for(ctx, raw)
    found = (list(claude_sessions_for(ctx, raw, places, others)) if kind in ("", "claude") else []) \
        + (list(codex_sessions_for(ctx, raw, places, others)) if kind in ("", "codex") else []) \
        + (list(agy_sessions_for(ctx, raw, places, others)) if kind in ("", "agy") else [])
    found.sort(key=lambda s: (s["score"], s["mtime"]), reverse=True)
    return found[0] if found else None


def dispatched_with(task: Any) -> tuple[str, str, str]:
    """kind, model and effort the task's worker was dispatched with."""
    raw = _worker_raw_task(task)
    record = raw.get("worker")
    if isinstance(record, dict) and record.get("kind"):
        return record["kind"], record.get("model") or "", record.get("effort") or ""
    for entry in raw.get("log") or []:
        found = re.match(r"dispatched to \S+ \(([^()]*)\)$", entry.get("text") or "")
        if found:
            parts = found.group(1).split() + ["", "", ""]
            return parts[0], parts[1], parts[2]
    return raw.get("kind") or "", "", ""


def remember_session_for(ctx: Context, task: Any) -> None:
    """A Claude Code session that writes to the ledger from the task's own terminal is the task's agent."""
    raw = _worker_raw_task(task)
    sid = ctx.env.get("CLAUDE_CODE_SESSION_ID", "")
    if sid and ctx.pane and raw.get("pane") == ctx.pane and not _worker_caller(ctx).pm_record_for_pane(ctx.pane):
        raw["session"] = {"kind": "claude", "id": sid}


def worker_task_for_hook_for(ctx: Context, cwd: str = "") -> tuple[dict[str, Any] | None, bool]:
    """The open task this hook process belongs to, verified strictly (never by bare pane == PANE)."""
    caller = _worker_caller(ctx)
    if not ctx.pane or caller.pm_record_for_pane(ctx.pane):
        return None, False
    if ctx.hc_terminal:
        info = ctx.hc.get_raw(ctx.hc_terminal) or {}
        labels = info.get("labels") or {}
        if labels.get("pm"):
            return None, False
        tid = str(labels.get("task") or "")
        if not tid or not re.fullmatch(r"[^/\\\s.][^/\\\s]*", tid) or ".." in tid:
            return None, False
        path = ctx.home.task(tid)
        if not path.is_file():
            return None, False
        try:
            task = json.loads(path.read_text())
        except (OSError, ValueError):
            return None, False
        if task.get("status") not in ACTIVE or task.get("pane") != ctx.pane:
            return None, False
        if not _cwd_matches_task_for(ctx, task, cwd or info.get("cwd") or ""):
            return None, False
        return task, True
    if caller.in_tui():
        live = {x.get("pane_id"): x.get("name") for x in ctx.tui.agents()}
        live_name = live.get(ctx.pane)
        if not live_name:
            return None, False
        matches = [
            t for t in Ledger(ctx).raw_tasks()
            if t.get("status") in ACTIVE and t.get("pane") == ctx.pane
            and t.get("worker_pane") == ctx.pane and t.get("agent") == live_name
            and _cwd_matches_task_for(ctx, t, cwd)
        ]
        if len(matches) != 1:
            return None, False
        return matches[0], False
    return None, False


def remember_worker_session_for(ctx: Context, transcript: str = "", session_id: str = "", cwd: str = "") -> None:
    """Record a running Claude Code worker's session on tasks/<id>.json at turn start / startup."""
    task, hc_verified = worker_task_for_hook_for(ctx, cwd)
    if not task:
        return
    dispatched_kind = dispatched_with(task)[0]
    if dispatched_kind and dispatched_kind != "claude":
        return
    env_sid = ctx.env.get("CLAUDE_CODE_SESSION_ID", "")
    sid = session_id or env_sid
    path_in_claude = False
    if transcript:
        p = Path(transcript)
        try:
            path_in_claude = p.suffix == ".jsonl" and p.resolve().is_relative_to(ctx.agents.claude_projects.resolve())
        except (OSError, ValueError):
            path_in_claude = False
        if not sid and path_in_claude:
            sid = p.stem
    if not sid:
        return
    valid = (pm_sessions.valid_session_id(sid) if pm_sessions is not None
             else bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", sid) and ".." not in sid))
    if not valid:
        return
    if not env_sid and dispatched_kind != "claude" and not path_in_claude:
        return
    if sid in (task.get("prior_sessions") or []):
        return
    wanted = {"kind": "claude", "id": sid}
    existing = valid_recorded_session(task)
    if existing == wanted:
        return
    if existing and not hc_verified:
        return  # in TUI, never overwrite an already-recorded session with a different one

    def _set_worker_session(cur: dict[str, Any] | None) -> dict[str, Any] | None:
        if cur is None:
            return None
        if (cur.get("pane") != ctx.pane or cur.get("status") not in ACTIVE
                or (dispatched_with(cur)[0] not in ("", "claude"))
                or sid in (cur.get("prior_sessions") or [])):
            return None
        cur_existing = valid_recorded_session(cur)
        if cur_existing == wanted or (cur_existing and not hc_verified):
            return None
        cur["session"] = wanted
        return cur

    ctx.store.change_task(task["id"], _set_worker_session)


# --- Legacy module-level shims (Stages 1-5 compatibility) ---


def remember_pm_session(rec: dict[str, Any], transcript: str = "", session_id: str = "") -> None:
    remember_pm_session_for(Context.from_env(), rec, transcript=transcript, session_id=session_id)


def task_workdirs(task: Any) -> list[str]:
    return task_workdirs_for(Context.from_env(), task)


def _cwd_matches_task(task: Any, cwd: str) -> bool:
    return _cwd_matches_task_for(Context.from_env(), task, cwd)


def pm_session_info(rec: dict[str, Any]) -> dict[str, Any] | None:
    return pm_session_info_for(Context.from_env(), rec)


def task_session_info(task: Any, sessions: Any = None, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    return task_session_info_for(Context.from_env(), task, sessions=sessions, tasks=tasks)


def session_places(task: Any, old_cwd: str = "") -> list[str]:
    return session_places_for(Context.from_env(), task, old_cwd=old_cwd)


def claimed_sessions(task: Any, tasks: list[dict[str, Any]] | None = None) -> frozenset[str]:
    return claimed_sessions_for(Context.from_env(), task, tasks=tasks)


def claude_sessions(task: Any, places: list[str], others: frozenset[str] = frozenset()) -> Iterator[dict[str, Any]]:
    return claude_sessions_for(Context.from_env(), task, places, others)


def codex_sessions(task: Any, places: list[str], others: frozenset[str] = frozenset()) -> Iterator[dict[str, Any]]:
    return codex_sessions_for(Context.from_env(), task, places, others)


def find_session(task: Any, old_cwd: str = "") -> dict[str, Any] | None:
    return _find_session_impl(Context.from_env(), task, old_cwd=old_cwd)


_DEFAULT_FIND_SESSION = find_session


def remember_session(task: Any) -> None:
    remember_session_for(Context.from_env(), task)


def worker_task_for_hook(cwd: str = "") -> tuple[dict[str, Any] | None, bool]:
    return worker_task_for_hook_for(Context.from_env(), cwd=cwd)


def remember_worker_session(transcript: str = "", session_id: str = "", cwd: str = "") -> None:
    remember_worker_session_for(Context.from_env(), transcript=transcript, session_id=session_id, cwd=cwd)
