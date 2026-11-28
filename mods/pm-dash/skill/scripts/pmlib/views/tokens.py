"""JSON read model and CLI view for `pm.py tokens`. Layer 4."""
from __future__ import annotations

import contextlib
from collections import defaultdict
import datetime
import json
import os
from pathlib import Path
import re
from typing import Any

from ..context import Context
from ..errors import PmError
from ..home import project_slug
from ..ledger.ledger import Ledger
from ..ledger.task import task_number
from ..project.project import ProjectRegistry
from ..store import project_folders, registration_slug
from .tokens_cache import DEFAULT_PRICING, FALLBACK_PRICING, nonneg_float, sync_token_cache

RANGES = ("today", "7d", "30d", "all")
AGENT_ORDER = ("claude", "agy", "codex", "pi")
AGENT_LABELS = {
    "claude": "Claude Code",
    "agy": "Antigravity (agy)",
    "codex": "Codex CLI",
    "pi": "pi Agent",
}
TOP_MODELS_CAP = 20
TOP_TASKS_CAP = 24
_UUID_TAIL_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", re.I)


def _norm(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path).strip().rstrip("/") or "/"


def _fast_in_scope(norm_child: str, norm_parent: str) -> bool:
    """Prefix check on already-resolved paths (avoids repeated `Path.resolve()` syscalls)."""
    if not norm_child or not norm_parent:
        return False
    if norm_parent == "/":
        return norm_child.startswith("/")
    return norm_child == norm_parent or norm_child.startswith(norm_parent + "/")


def _pricing_for(model: str, custom_pricing: dict[str, Any] | None = None) -> dict[str, float]:
    low = (model or "").lower()
    if isinstance(custom_pricing, dict):
        for pat, rates in custom_pricing.items():
            if isinstance(pat, str) and pat and isinstance(rates, dict) and pat.lower() in low:
                return {
                    "input": nonneg_float(rates.get("input", FALLBACK_PRICING["input"])),
                    "output": nonneg_float(rates.get("output", FALLBACK_PRICING["output"])),
                    "cache_read": nonneg_float(rates.get("cache_read", FALLBACK_PRICING["cache_read"])),
                    "cache_write_5m": nonneg_float(rates.get("cache_write_5m", FALLBACK_PRICING["cache_write_5m"])),
                    "cache_write_1h": nonneg_float(rates.get("cache_write_1h", FALLBACK_PRICING["cache_write_1h"])),
                }
    for pat, rates in DEFAULT_PRICING:
        if pat in low:
            return rates
    return FALLBACK_PRICING


def estimate_cost_and_savings(
    model: str,
    *,
    input_tok: int,
    output_tok: int,
    cache_read_tok: int,
    cache_write_5m_tok: int,
    cache_write_1h_tok: int,
    explicit_usd: float = 0.0,
    custom_pricing: dict[str, Any] | None = None,
) -> tuple[float, float]:
    """Return `(cost_usd, cache_savings_usd)` using explicit cost when present else list-rate table."""
    rates = _pricing_for(model, custom_pricing)
    savings = (cache_read_tok * max(0.0, rates["input"] - rates["cache_read"])) / 1_000_000.0
    if explicit_usd > 0.0:
        return explicit_usd, savings
    cost = (
        input_tok * rates["input"]
        + output_tok * rates["output"]
        + cache_read_tok * rates["cache_read"]
        + cache_write_5m_tok * rates["cache_write_5m"]
        + cache_write_1h_tok * rates["cache_write_1h"]
    ) / 1_000_000.0
    return cost, savings


def _extract_sid_from_path(raw_path: str) -> str:
    """Extract a canonical session/conversation ID from a transcript file path across all 4 runtimes."""
    if not raw_path:
        return ""
    p = Path(raw_path)
    stem = p.stem
    if stem in ("transcript", "transcript_full"):
        # <agy_dir>/brain/<cid>/.system_generated/logs/transcript[_full].jsonl
        parts = p.parts
        for idx, part in enumerate(parts):
            if part == "brain" and idx + 1 < len(parts):
                return parts[idx + 1]
        return ""
    m = _UUID_TAIL_RE.search(stem)
    if m:
        return m.group(1)
    if "_" in stem:
        tail = stem.rsplit("_", 1)[-1]
        if tail:
            return tail
    return stem


def _add_pm_path_and_sid(
    pinfo: dict[str, Any],
    raw_path: Any,
    *,
    agy_cids: set[str],
    all_pm_sids: set[str],
    all_pm_paths: set[str],
    is_agy: bool = False,
) -> None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return
    rp = raw_path.strip()
    np = _norm(rp)
    if np:
        pinfo["pm_paths"].add(np)
        all_pm_paths.add(np)
        if np != rp:
            pinfo["pm_paths"].add(rp)
    sid = _extract_sid_from_path(rp)
    if sid:
        pinfo["pm_sids"].add(sid)
        all_pm_sids.add(sid)
        if is_agy or "/antigravity-cli/" in rp or Path(rp).stem in ("transcript", "transcript_full"):
            agy_cids.add(sid)


def _add_pm_sid(
    pinfo: dict[str, Any],
    raw_sid: Any,
    *,
    agy_cids: set[str],
    all_pm_sids: set[str],
    is_agy: bool = False,
) -> None:
    if not isinstance(raw_sid, str) or not raw_sid.strip():
        return
    sid = raw_sid.strip()
    pinfo["pm_sids"].add(sid)
    all_pm_sids.add(sid)
    if is_agy:
        agy_cids.add(sid)


def _parse_ts(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return 0.0
    text = raw.strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _build_project_index(ctx: Context, regs: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> tuple[
    dict[str, dict[str, Any]], list[str], list[str], set[str], set[str], set[str]
]:
    """Build per-slug project metadata, equal-folder scopes, worktree homes, and all PM/agy session identifiers."""
    projects: dict[str, dict[str, Any]] = {}
    scopes: list[str] = []
    wt_homes: list[str] = []
    agy_cids: set[str] = set()
    all_pm_sids: set[str] = set()
    all_pm_paths: set[str] = set()
    repo_to_slugs: dict[str, list[str]] = defaultdict(list)

    def _add_root(pinfo: dict[str, Any], raw_path: str, *, include_wt: bool = True) -> None:
        raw_s = str(raw_path or "").strip()
        if not raw_s:
            return
        norm_p = _norm(raw_s)
        for cand in (norm_p, raw_s):
            if cand and cand not in scopes:
                scopes.append(cand)
        if norm_p and norm_p not in pinfo["roots"]:
            pinfo["roots"].append(norm_p)
        if include_wt:
            if norm_p and norm_p not in pinfo["repo_roots"]:
                pinfo["repo_roots"].append(norm_p)
            slug_key = pinfo["slug"]
            if norm_p and slug_key not in repo_to_slugs[norm_p]:
                repo_to_slugs[norm_p].append(slug_key)
            wt = _norm(ctx.git.worktree_home(norm_p or raw_s))
            raw_wt = str(ctx.git.worktree_home(raw_s))
            for wt_cand in (wt, raw_wt):
                if wt_cand:
                    if wt_cand not in scopes:
                        scopes.append(wt_cand)
                    if wt_cand not in wt_homes:
                        wt_homes.append(wt_cand)
            if wt and wt not in pinfo["wt_homes"]:
                pinfo["wt_homes"].append(wt)
            if wt and not pinfo["wt_home"]:
                pinfo["wt_home"] = wt

    def _ensure_project(
        slug: str,
        repo: str,
        *,
        pm_name: str,
        project_name: str,
        archived: bool,
        raw_repo: str,
        folders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        norm_repo = _norm(repo) if repo else ""
        if slug not in projects:
            projects[slug] = {
                "slug": slug,
                "pm_name": pm_name,
                "project": project_name,
                "repo": norm_repo,
                "wt_home": "",
                "roots": [],
                "repo_roots": [],
                "wt_homes": [],
                "archived": archived,
                "last_active_ts": 0.0,
                "pm_sids": set(),
                "pm_paths": set(),
            }
        pinfo = projects[slug]
        if norm_repo and not pinfo["repo"]:
            pinfo["repo"] = norm_repo
        if raw_repo or norm_repo:
            _add_root(pinfo, raw_repo or norm_repo, include_wt=True)
        for f in folders or ():
            _add_root(pinfo, str(f.get("path") or ""), include_wt=True)
        if not (folders or raw_repo or norm_repo):
            proj_dir = ctx.home.project(slug).root
            _add_root(pinfo, str(proj_dir), include_wt=False)
        return pinfo

    for rec in regs:
        slug = registration_slug(rec)
        folders = project_folders(rec)
        raw_repo = str(rec.get("repo") or (folders[0]["path"] if folders else "") or "")
        repo = _norm(raw_repo) if raw_repo else ""
        if not slug and not repo:
            continue
        slug = slug or project_slug(repo)
        pinfo = _ensure_project(
            slug,
            repo,
            pm_name=str(rec.get("name") or f"pm-{slug}"),
            project_name=str(rec.get("display_name") or rec.get("space_name") or rec.get("project") or slug),
            archived=bool(rec.get("archived")),
            raw_repo=raw_repo,
            folders=folders,
        )
        for ts_key in ("updated", "rotated_at", "started_at", "created"):
            ts_val = _parse_ts(rec.get(ts_key))
            if ts_val > pinfo["last_active_ts"]:
                pinfo["last_active_ts"] = ts_val
        rec_is_agy = str(rec.get("agent") or "").lower() in ("agy", "antigravity")

        sess = rec.get("agent_session")
        if isinstance(sess, dict):
            sess_agy = str(sess.get("kind") or "").lower() in ("agy", "antigravity") or rec_is_agy
            _add_pm_sid(pinfo, sess.get("id"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=sess_agy)
            _add_pm_path_and_sid(pinfo, sess.get("path"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, all_pm_paths=all_pm_paths, is_agy=sess_agy)
            _add_pm_path_and_sid(pinfo, sess.get("transcript"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, all_pm_paths=all_pm_paths, is_agy=sess_agy)

        for old_sid in rec.get("retired_sessions") or []:
            if isinstance(old_sid, str):
                _add_pm_sid(pinfo, old_sid, agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=rec_is_agy)
            elif isinstance(old_sid, dict):
                old_agy = str(old_sid.get("kind") or "").lower() in ("agy", "antigravity")
                _add_pm_sid(pinfo, old_sid.get("id"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=old_agy)
                _add_pm_path_and_sid(pinfo, old_sid.get("path") or old_sid.get("transcript"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, all_pm_paths=all_pm_paths, is_agy=old_agy)

        prev = rec.get("previous")
        if isinstance(prev, dict):
            prev_agy = str(prev.get("agent") or "").lower() in ("agy", "antigravity")
            _add_pm_path_and_sid(pinfo, prev.get("transcript"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, all_pm_paths=all_pm_paths, is_agy=prev_agy)
            prev_sess = prev.get("agent_session")
            if isinstance(prev_sess, dict):
                ps_agy = str(prev_sess.get("kind") or "").lower() in ("agy", "antigravity") or prev_agy
                _add_pm_sid(pinfo, prev_sess.get("id"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=ps_agy)
                _add_pm_path_and_sid(pinfo, prev_sess.get("path") or prev_sess.get("transcript"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, all_pm_paths=all_pm_paths, is_agy=ps_agy)

        ep = rec.get("endpoint")
        if isinstance(ep, dict):
            ep_agy = str(ep.get("agent_kind") or "").lower() in ("agy", "antigravity")
            _add_pm_sid(pinfo, ep.get("session_id"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=ep_agy)

        proj_files = ctx.home.project(slug)
        with contextlib.suppress(OSError):
            conv_mtime = proj_files.conversation.stat().st_mtime
            if conv_mtime > pinfo["last_active_ts"]:
                pinfo["last_active_ts"] = float(conv_mtime)

        # 1. agy-transcript.json (v2: session.id, retired[], cursors{}; v1: cid, conversation_id)
        agy_mark = proj_files.agy_transcript
        if agy_mark.is_file():
            try:
                data = json.loads(agy_mark.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for legacy_key in ("cid", "conversation_id"):
                        _add_pm_sid(pinfo, data.get(legacy_key), agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=True)
                    sess_obj = data.get("session")
                    if isinstance(sess_obj, dict):
                        _add_pm_sid(pinfo, sess_obj.get("id"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=True)
                    for r_cid in data.get("retired") or []:
                        _add_pm_sid(pinfo, r_cid, agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=True)
                    cursors = data.get("cursors")
                    if isinstance(cursors, dict):
                        for c_cid, c_meta in cursors.items():
                            _add_pm_sid(pinfo, c_cid, agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=True)
                            if isinstance(c_meta, dict):
                                _add_pm_path_and_sid(pinfo, c_meta.get("path"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, all_pm_paths=all_pm_paths, is_agy=True)
            except (OSError, ValueError):
                pass

        # 2. taken-in.json (tracks every Claude/Codex/pi PM transcript ingested into conversation.jsonl)
        taken_in = proj_files.taken_in
        if taken_in.is_file():
            try:
                ti_data = json.loads(taken_in.read_text(encoding="utf-8"))
                files_map = ti_data.get("files") if isinstance(ti_data, dict) else None
                if isinstance(files_map, dict):
                    for tpath in files_map.keys():
                        _add_pm_path_and_sid(pinfo, tpath, agy_cids=agy_cids, all_pm_sids=all_pm_sids, all_pm_paths=all_pm_paths)
            except (OSError, ValueError):
                pass

        # 3. pm-turn.json (current PM session_id)
        pm_turn = proj_files.root / "pm-turn.json"
        if pm_turn.is_file():
            try:
                pt_data = json.loads(pm_turn.read_text(encoding="utf-8"))
                pt_sess = pt_data.get("session") if isinstance(pt_data, dict) else None
                if isinstance(pt_sess, dict):
                    pt_agy = str(pt_sess.get("agent_kind") or "").lower() in ("agy", "antigravity")
                    _add_pm_sid(pinfo, pt_sess.get("session_id"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=pt_agy)
            except (OSError, ValueError):
                pass

        # 4. seat.json (defensive: pick up session_id / --resume sid if recorded)
        seat_path = proj_files.root / "seat.json"
        if seat_path.is_file():
            try:
                s_data = json.loads(seat_path.read_text(encoding="utf-8"))
                if isinstance(s_data, dict):
                    s_agy = str(s_data.get("kind") or "").lower() in ("agy", "antigravity")
                    _add_pm_sid(pinfo, s_data.get("session_id") or s_data.get("sid"), agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=s_agy)
                    s_argv = s_data.get("argv")
                    if isinstance(s_argv, list):
                        for i, tok in enumerate(s_argv):
                            if tok in ("--resume", "-r") and i + 1 < len(s_argv) and isinstance(s_argv[i + 1], str):
                                cand = s_argv[i + 1].strip()
                                if cand and not cand.startswith("-"):
                                    _add_pm_sid(pinfo, cand, agy_cids=agy_cids, all_pm_sids=all_pm_sids, is_agy=s_agy)
            except (OSError, ValueError):
                pass

    for t in tasks:
        if not isinstance(t, dict):
            continue
        t_slug = str(t.get("project_slug") or "").strip()
        repo = _norm(t.get("repo"))
        owners = repo_to_slugs.get(repo, []) if repo else []
        slug = t_slug or (owners[0] if len(owners) == 1 else (project_slug(repo) if repo else ""))
        if slug:
            pinfo = _ensure_project(
                slug,
                repo,
                pm_name=f"pm-{slug}",
                project_name=str(t.get("project") or slug),
                archived=False,
                raw_repo=str(t.get("repo") or ""),
            )
            ts_val = max(_parse_ts(t.get("updated")), _parse_ts(t.get("created")))
            if ts_val > pinfo["last_active_ts"]:
                pinfo["last_active_ts"] = ts_val
        for pkey in ("worktree", "in_place"):
            raw_wp = str(t.get(pkey) or "")
            wp = _norm(raw_wp)
            if wp:
                scopes.append(wp)
            if raw_wp:
                scopes.append(raw_wp)
        sess = t.get("session")
        if isinstance(sess, dict) and sess.get("kind") == "agy" and sess.get("id"):
            agy_cids.add(str(sess["id"]))

    return projects, list(dict.fromkeys(scopes)), list(dict.fromkeys(wt_homes)), agy_cids, all_pm_sids, all_pm_paths


def _attribute_files(
    files_rows: list[dict[str, Any]],
    projects: dict[str, dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Attribute each transcript file to `{slug, pm_name, project, task_id, task_num, task_title, task_status, role, is_review}`.

    Guarantees each file has at most one owner (no PM/worker double counting), prioritizes verified PM
    session registries (`pms/*.json`, `agy-transcript.json`, `taken-in.json`, `pm-turn.json`), honors
    `project_slug` on tasks, breaks shared-folder ties deterministically (`longest root -> non-archived
    -> latest active -> slug`), and never lets main-repo `in_place` tasks hijack PM or ad-hoc sessions.
    """
    by_id: dict[str, dict[str, Any]] = {
        t["id"]: t for t in tasks if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"]
    }
    sid_to_pm: dict[str, dict[str, Any]] = {}
    path_to_pm: dict[str, dict[str, Any]] = {}
    repo_set: set[str] = set()
    wt_home_set: set[str] = set()
    repo_owners: dict[str, list[str]] = defaultdict(list)

    for pinfo in projects.values():
        for rr in pinfo.get("repo_roots") or ():
            repo_set.add(rr)
            if pinfo["slug"] not in repo_owners[rr]:
                repo_owners[rr].append(pinfo["slug"])
        if pinfo["repo"]:
            repo_set.add(pinfo["repo"])
            if pinfo["slug"] not in repo_owners[pinfo["repo"]]:
                repo_owners[pinfo["repo"]].append(pinfo["slug"])
        for wh in pinfo.get("wt_homes") or ():
            wt_home_set.add(wh)
        if pinfo["wt_home"]:
            wt_home_set.add(pinfo["wt_home"])
        for sid in pinfo["pm_sids"]:
            sid_to_pm[sid] = pinfo
        for pm_p in pinfo.get("pm_paths") or ():
            path_to_pm[pm_p] = pinfo

    unambiguous_repo_owner: dict[str, str] = {
        rr: owners[0] for rr, owners in repo_owners.items() if len(owners) == 1
    }

    sid_to_task: dict[str, dict[str, Any]] = {}
    workdir_tasks: list[tuple[str, dict[str, Any]]] = []
    for t in tasks:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        sess = t.get("session")
        if isinstance(sess, dict) and isinstance(sess.get("id"), str) and sess["id"]:
            if sess["id"] not in sid_to_pm:
                sid_to_task[sess["id"]] = t
        for old_sid in t.get("prior_sessions") or []:
            if isinstance(old_sid, str) and old_sid and old_sid not in sid_to_task and old_sid not in sid_to_pm:
                sid_to_task[old_sid] = t
        wt = _norm(t.get("worktree"))
        if wt and wt not in repo_set:
            workdir_tasks.append((wt, t))
        ip = _norm(t.get("in_place"))
        # Only match dedicated subdirs by cwd; main-repo in_place tasks match via session.id or opening_task_hint
        if ip and ip not in repo_set:
            workdir_tasks.append((ip, t))

    def _pm_attr(pinfo: dict[str, Any], agent: str) -> dict[str, Any]:
        return {
            "agent": agent,
            "slug": pinfo["slug"],
            "pm_name": pinfo["pm_name"],
            "project": pinfo["project"],
            "task_id": f"pm:{pinfo['slug']}",
            "task_num": 0,
            "task_title": f"{pinfo['project']} · PM",
            "task_status": "pm",
            "role": "pm",
            "is_review": False,
        }

    def _project_for_cwd(cwd: str) -> dict[str, Any] | None:
        if not cwd:
            return None
        best_rank: tuple[int, int, float, str] | None = None
        best_pinfo: dict[str, Any] | None = None
        for pinfo in projects.values():
            candidates = list(dict.fromkeys([*(pinfo.get("roots") or ()), *(pinfo.get("wt_homes") or ())]))
            if not candidates:
                candidates = [r for r in (pinfo["repo"], pinfo["wt_home"]) if r]
            for root in candidates:
                if root and _fast_in_scope(cwd, root):
                    rank = (
                        -len(root),
                        1 if pinfo["archived"] else 0,
                        -float(pinfo.get("last_active_ts") or 0.0),
                        str(pinfo["slug"]),
                    )
                    if best_rank is None or rank < best_rank:
                        best_rank = rank
                        best_pinfo = pinfo
        return best_pinfo

    def _task_attr(t: dict[str, Any], role: str, agent: str) -> dict[str, Any]:
        rev_of = t.get("review_of")
        is_review = bool(rev_of and rev_of in by_id)
        parent_t = by_id[rev_of] if is_review else t
        explicit_slug = str(parent_t.get("project_slug") or t.get("project_slug") or "").strip()
        repo = _norm(parent_t.get("repo") or t.get("repo"))
        if explicit_slug:
            slug = explicit_slug
        elif repo and repo in unambiguous_repo_owner:
            slug = unambiguous_repo_owner[repo]
        elif repo:
            matched_p = _project_for_cwd(repo)
            slug = matched_p["slug"] if matched_p is not None else project_slug(repo)
        else:
            slug = ""
        pinfo = projects.get(slug)
        return {
            "agent": agent,
            "slug": slug,
            "pm_name": pinfo["pm_name"] if pinfo else (f"pm-{slug}" if slug else ""),
            "project": pinfo["project"] if pinfo else str(parent_t.get("project") or slug),
            "task_id": parent_t["id"],
            "task_num": task_number(parent_t) or 0,
            "task_title": str(parent_t.get("title") or parent_t["id"]),
            "task_status": str(parent_t.get("status") or ""),
            "role": "review" if is_review else (role or "worker"),
            "is_review": is_review,
        }

    def _in_any_worktree(cwd: str) -> bool:
        if not cwd:
            return False
        for wh in wt_home_set:
            if _fast_in_scope(cwd, wh):
                return True
        for wp, _ in workdir_tasks:
            if _fast_in_scope(cwd, wp):
                return True
        return False

    norm_cache: dict[str, str] = {}
    out: dict[str, dict[str, Any]] = {}
    sid_to_attr: dict[str, dict[str, Any]] = {}
    deferred: list[tuple[dict[str, Any], str]] = []

    def _norm_cached(val: str) -> str:
        if val not in norm_cache:
            norm_cache[val] = _norm(val)
        return norm_cache[val]

    def _fallback_attr(pinfo: dict[str, Any], agent: str, role: str) -> dict[str, Any]:
        if role == "pm":
            return _pm_attr(pinfo, agent)
        return {
            "agent": agent,
            "slug": pinfo["slug"],
            "pm_name": pinfo["pm_name"],
            "project": pinfo["project"],
            "task_id": f"other:{pinfo['slug']}",
            "task_num": 0,
            "task_title": f"{pinfo['project']} · Ad-hoc",
            "task_status": "adhoc",
            "role": role or "session",
            "is_review": False,
        }

    # Pass 1: direct attribution (PM registry -> task session -> PM opening -> task hint -> worktree)
    for f in files_rows:
        p_str = f["path"]
        norm_p = _norm_cached(p_str)
        agent = f["agent"]
        sid = f["sid"]
        parent_sid = f["parent_sid"]
        cwd = _norm_cached(f["cwd"])
        role = f["opening_role"]
        hint = f["opening_task_hint"]

        # 1. Exact PM path or PM session id (current, retired, agy-transcript, taken-in, previous, pm-turn)
        matched_pm = (
            path_to_pm.get(norm_p)
            or path_to_pm.get(p_str)
            or sid_to_pm.get(sid)
            or (sid_to_pm.get(parent_sid) if parent_sid else None)
        )
        if matched_pm is not None:
            attr = _pm_attr(matched_pm, agent)
            out[p_str] = attr
            if sid:
                sid_to_attr[sid] = attr
            continue

        # 2. Exact session id / parent session id match on a task
        matched_task = sid_to_task.get(sid) or (sid_to_task.get(parent_sid) if parent_sid else None)
        if matched_task is not None:
            attr = _task_attr(matched_task, role, agent)
            out[p_str] = attr
            if sid:
                sid_to_attr[sid] = attr
            continue

        # 3. Verified PM opening outside any worker worktree (covers rotated PMs beyond retired_sessions cap,
        #    Codex/pi PMs started via pm.py start/rotate/restore, and Claude PMs with SessionStart hook)
        if role == "pm" and not _in_any_worktree(cwd):
            pinfo = _project_for_cwd(cwd)
            if pinfo is not None:
                attr = _pm_attr(pinfo, agent)
                out[p_str] = attr
                if sid:
                    sid_to_attr[sid] = attr
                continue

        # 4. Hint task id directly in ledger (never overrides PM)
        if role != "pm" and hint and hint in by_id:
            attr = _task_attr(by_id[hint], role, agent)
            out[p_str] = attr
            if sid:
                sid_to_attr[sid] = attr
            continue

        # 5. Dedicated worktree / non-repo in_place match
        if cwd and role != "pm":
            wt_hits = [t for wp, t in workdir_tasks if _fast_in_scope(cwd, wp)]
            if wt_hits:
                if role == "reviewer":
                    rev_hits = [t for t in wt_hits if t.get("review_of")]
                    if rev_hits:
                        attr = _task_attr(rev_hits[0], "reviewer", agent)
                        out[p_str] = attr
                        if sid:
                            sid_to_attr[sid] = attr
                        continue
                non_rev = [t for t in wt_hits if not t.get("review_of")]
                chosen = non_rev[-1] if non_rev else wt_hits[-1]
                attr = _task_attr(chosen, role, agent)
                out[p_str] = attr
                if sid:
                    sid_to_attr[sid] = attr
                continue

        # 6. Defer files with parent_sid so subagents / derived-from sessions inherit parent's attribution
        if parent_sid:
            deferred.append((f, cwd))
            continue

        # 7. Project repo / worktree home fallback
        pinfo = _project_for_cwd(cwd)
        if pinfo is not None:
            attr = _fallback_attr(pinfo, agent, role if not _in_any_worktree(cwd) else ("worker" if role == "pm" else role))
            out[p_str] = attr
            if sid:
                sid_to_attr[sid] = attr

    # Pass 2: resolve subagents and derived sessions via their parent chain
    for f, cwd in deferred:
        p_str = f["path"]
        agent = f["agent"]
        sid = f["sid"]
        parent_sid = f["parent_sid"]
        role = f["opening_role"]
        parent_attr = sid_to_attr.get(parent_sid)
        if parent_attr is not None:
            attr = {**parent_attr, "agent": agent}
            out[p_str] = attr
            if sid:
                sid_to_attr[sid] = attr
            continue
        pinfo = _project_for_cwd(cwd)
        if pinfo is not None:
            eff_role = role if not _in_any_worktree(cwd) else ("worker" if role == "pm" else role)
            attr = _fallback_attr(pinfo, agent, eff_role)
            out[p_str] = attr
            if sid:
                sid_to_attr[sid] = attr

    return out


def _empty_agent_map() -> dict[str, int]:
    return {a: 0 for a in AGENT_ORDER}


def _empty_agent_float_map() -> dict[str, float]:
    return {a: 0.0 for a in AGENT_ORDER}


def _bucket_defs(range_name: str, now_dt: datetime.datetime, min_hour_epoch: int) -> tuple[
    int, str, list[tuple[str, str, int, int]]
]:
    """Return `(start_epoch, mode, [(key, label, start_ep, end_ep), ...])` in local time."""
    local_tz = now_dt.astimezone().tzinfo
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=local_tz)
    today_ep = int(today_start.timestamp())

    if range_name == "today":
        defs = []
        for h in range(24):
            s = today_ep + h * 3600
            defs.append((f"{h:02d}:00", f"{h:02d}:00", s, s + 3600))
        return today_ep, "hour", defs

    if range_name in ("7d", "30d"):
        days = 7 if range_name == "7d" else 30
        start_dt = today_start - datetime.timedelta(days=days - 1)
        defs = []
        for i in range(days):
            d = start_dt + datetime.timedelta(days=i)
            s = int(d.timestamp())
            e = int((d + datetime.timedelta(days=1)).timestamp())
            lbl = d.strftime("%m-%d")
            defs.append((d.strftime("%Y-%m-%d"), lbl, s, e))
        return int(start_dt.timestamp()), "day", defs

    # 'all'
    if min_hour_epoch > 0:
        min_dt = datetime.datetime.fromtimestamp(min_hour_epoch, tz=local_tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        min_dt = today_start - datetime.timedelta(days=6)
    span_days = max(1, (today_start.date() - min_dt.date()).days + 1)
    if span_days <= 45:
        defs = []
        for i in range(span_days):
            d = min_dt + datetime.timedelta(days=i)
            s = int(d.timestamp())
            e = int((d + datetime.timedelta(days=1)).timestamp())
            defs.append((d.strftime("%Y-%m-%d"), d.strftime("%m-%d"), s, e))
        return int(min_dt.timestamp()), "day", defs

    # Weekly buckets for long histories (> 45 days)
    defs = []
    cur = min_dt
    while cur <= today_start:
        nxt = min(cur + datetime.timedelta(days=7), today_start + datetime.timedelta(days=1))
        defs.append((cur.strftime("%Y-%m-%d"), cur.strftime("%m-%d"), int(cur.timestamp()), int(nxt.timestamp())))
        cur = nxt
    return int(min_dt.timestamp()), "week", defs


_ROLE_PRIORITY = {"pm": 5, "worker": 4, "helper": 3, "review": 2, "reviewer": 2, "subagent": 1, "session": 0, "": 0}


def _build_slice(
    rows: list[dict[str, Any]],
    *,
    range_name: str,
    now_dt: datetime.datetime,
    custom_pricing: dict[str, Any] | None,
) -> dict[str, Any]:
    min_ep = min((r["hour_epoch"] for r in rows if r["hour_epoch"] > 0), default=0)
    start_ep, bucket_mode, bdefs = _bucket_defs(range_name, now_dt, min_ep)

    filtered = [r for r in rows if r["hour_epoch"] >= start_ep]

    tot_in = tot_out = tot_cr = tot_cw = tot_calls = tot_errs = 0
    tot_cost = tot_save = 0.0
    sessions: set[str] = set()
    task_ids: set[str] = set()
    agent_prompt: dict[str, int] = _empty_agent_map()
    agent_cr: dict[str, int] = _empty_agent_map()

    pm_in = pm_out = pm_cr = pm_cw = pm_calls = pm_errs = 0
    pm_cost = pm_save = 0.0
    pm_sessions: set[str] = set()
    pm_agents: set[str] = set()
    pm_models: set[str] = set()
    pm_by_agent: dict[str, dict[str, Any]] = {}

    buckets_data: list[dict[str, Any]] = [
        {
            "key": k,
            "label": lbl,
            "start_epoch": s,
            "end_epoch": e,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "requests": 0,
            "errors": 0,
            "by_agent_tokens": _empty_agent_map(),
            "by_agent_cost": _empty_agent_float_map(),
            "by_agent_requests": _empty_agent_map(),
            "advisor_tokens": 0,
            "advisor_cost": 0.0,
        }
        for k, lbl, s, e in bdefs
    ]

    model_agg: dict[tuple[str, str, bool], dict[str, Any]] = {}
    task_agg: dict[str, dict[str, Any]] = {}
    agent_agg: dict[str, dict[str, Any]] = {
        a: {
            "agent": a,
            "label": AGENT_LABELS[a],
            "requests": 0,
            "errors": 0,
            "sessions": set(),
            "tasks": set(),
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cache_write_available": a != "agy",
            "cost_usd": 0.0,
            "cache_savings_usd": 0.0,
            "pm_tokens": 0,
            "pm_cost_usd": 0.0,
            "pm_requests": 0,
            "pm_sessions": set(),
        }
        for a in AGENT_ORDER
    }

    # Index bucket lookup by hour_epoch
    def _find_bucket(ep: int) -> dict[str, Any] | None:
        for b in buckets_data:
            if b["start_epoch"] <= ep < b["end_epoch"]:
                return b
        return None

    for r in filtered:
        agent = r["agent"]
        model = r["model"]
        is_adv = r["is_advisor"]
        calls = r["calls"]
        errs = r["errors"]
        in_tok = r["input_tok"]
        out_tok = r["output_tok"]
        cr_tok = r["cache_read_tok"]
        cw5 = r["cache_write_5m_tok"]
        cw1 = r["cache_write_1h_tok"]
        cw_tok = cw5 + cw1
        tok_sum = in_tok + out_tok + cr_tok + cw_tok
        tid = r["task_id"] or f"other:{r['slug']}"
        is_pm_row = r["role"] == "pm" or tid.startswith("pm:")

        cost, save = estimate_cost_and_savings(
            model,
            input_tok=in_tok,
            output_tok=out_tok,
            cache_read_tok=cr_tok,
            cache_write_5m_tok=cw5,
            cache_write_1h_tok=cw1,
            explicit_usd=r["explicit_usd"],
            custom_pricing=custom_pricing,
        )

        tot_in += in_tok
        tot_out += out_tok
        tot_cr += cr_tok
        tot_cw += cw_tok
        tot_calls += calls
        tot_errs += errs
        tot_cost += cost
        tot_save += save
        sessions.add(r["path"])
        if tid and not tid.startswith("pm:") and not tid.startswith("other:"):
            task_ids.add(tid)

        if is_pm_row:
            pm_in += in_tok
            pm_out += out_tok
            pm_cr += cr_tok
            pm_cw += cw_tok
            pm_calls += calls
            pm_errs += errs
            pm_cost += cost
            pm_save += save
            pm_sessions.add(r["path"])
            pm_agents.add(agent)
            pm_models.add(model)
            pba = pm_by_agent.get(agent)
            if pba is None:
                pba = {
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "requests": 0,
                    "errors": 0,
                    "sessions": set(),
                    "cost_usd": 0.0,
                    "cache_savings_usd": 0.0,
                    "models": set(),
                }
                pm_by_agent[agent] = pba
            pba["total_tokens"] += tok_sum
            pba["input_tokens"] += in_tok
            pba["output_tokens"] += out_tok
            pba["cache_read_tokens"] += cr_tok
            pba["cache_write_tokens"] += cw_tok
            pba["requests"] += calls
            pba["errors"] += errs
            pba["sessions"].add(r["path"])
            pba["cost_usd"] += cost
            pba["cache_savings_usd"] += save
            pba["models"].add(model)

        prompt_part = in_tok + cr_tok + cw_tok
        if agent in agent_prompt:
            agent_prompt[agent] += prompt_part
            agent_cr[agent] += cr_tok

        b = _find_bucket(r["hour_epoch"])
        if b is not None:
            b["total_tokens"] += tok_sum
            b["cost_usd"] += cost
            b["requests"] += calls
            b["errors"] += errs
            if agent in b["by_agent_tokens"]:
                b["by_agent_tokens"][agent] += tok_sum
                b["by_agent_cost"][agent] += cost
                b["by_agent_requests"][agent] += calls
            if is_adv:
                b["advisor_tokens"] += tok_sum
                b["advisor_cost"] += cost

        mkey = (model, agent, is_adv)
        ma = model_agg.get(mkey)
        if ma is None:
            ma = {
                "model": model,
                "agent": agent,
                "is_advisor": is_adv,
                "requests": 0,
                "errors": 0,
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cache_write_available": agent != "agy",
                "cost_usd": 0.0,
                "cache_savings_usd": 0.0,
                "pm_tokens": 0,
                "pm_cost_usd": 0.0,
                "pm_requests": 0,
            }
            model_agg[mkey] = ma
        ma["requests"] += calls
        ma["errors"] += errs
        ma["total_tokens"] += tok_sum
        ma["input_tokens"] += in_tok
        ma["output_tokens"] += out_tok
        ma["cache_read_tokens"] += cr_tok
        ma["cache_write_tokens"] += cw_tok
        ma["cost_usd"] += cost
        ma["cache_savings_usd"] += save
        if is_pm_row:
            ma["pm_tokens"] += tok_sum
            ma["pm_cost_usd"] += cost
            ma["pm_requests"] += calls

        ta = task_agg.get(tid)
        if ta is None:
            ta = {
                "id": tid,
                "number": r["task_num"],
                "title": r["task_title"],
                "project": r["project"],
                "pm": r["pm_name"],
                "role": "pm" if is_pm_row else r["role"],
                "status": r["task_status"],
                "agents": set(),
                "models": set(),
                "sessions": set(),
                "requests": 0,
                "errors": 0,
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "work_tokens": 0,
                "review_tokens": 0,
                "cost_usd": 0.0,
                "work_cost_usd": 0.0,
                "review_cost_usd": 0.0,
                "cache_savings_usd": 0.0,
                "by_agent": defaultdict(int),
                "by_agent_cost": defaultdict(float),
                "by_agent_requests": defaultdict(int),
                "by_agent_io": {},
            }
            task_agg[tid] = ta
        else:
            cand_role = "pm" if is_pm_row else r["role"]
            if _ROLE_PRIORITY.get(cand_role, 0) > _ROLE_PRIORITY.get(ta["role"], 0):
                ta["role"] = cand_role
        ta["agents"].add(agent)
        ta["models"].add(model)
        ta["sessions"].add(r["path"])
        ta["requests"] += calls
        ta["errors"] += errs
        ta["total_tokens"] += tok_sum
        ta["input_tokens"] += in_tok
        ta["output_tokens"] += out_tok
        ta["cache_read_tokens"] += cr_tok
        ta["cache_write_tokens"] += cw_tok
        ta["cost_usd"] += cost
        ta["cache_savings_usd"] += save
        if r["is_review"]:
            ta["review_tokens"] += tok_sum
            ta["review_cost_usd"] += cost
        else:
            ta["work_tokens"] += tok_sum
            ta["work_cost_usd"] += cost
        ta["by_agent"][agent] += tok_sum
        ta["by_agent_cost"][agent] += cost
        ta["by_agent_requests"][agent] += calls
        aio = ta["by_agent_io"].get(agent)
        if aio is None:
            aio = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "models": set()}
            ta["by_agent_io"][agent] = aio
        aio["input_tokens"] += in_tok
        aio["output_tokens"] += out_tok
        aio["cache_read_tokens"] += cr_tok
        aio["cache_write_tokens"] += cw_tok
        aio["models"].add(model)

        if agent in agent_agg:
            aa = agent_agg[agent]
            aa["requests"] += calls
            aa["errors"] += errs
            aa["sessions"].add(r["path"])
            if tid and not tid.startswith("pm:") and not tid.startswith("other:"):
                aa["tasks"].add(tid)
            aa["total_tokens"] += tok_sum
            aa["input_tokens"] += in_tok
            aa["output_tokens"] += out_tok
            aa["cache_read_tokens"] += cr_tok
            aa["cache_write_tokens"] += cw_tok
            aa["cost_usd"] += cost
            aa["cache_savings_usd"] += save
            if is_pm_row:
                aa["pm_tokens"] += tok_sum
                aa["pm_cost_usd"] += cost
                aa["pm_requests"] += calls
                aa["pm_sessions"].add(r["path"])

    tot_tok = tot_in + tot_out + tot_cr + tot_cw
    tot_prompt = tot_in + tot_cr + tot_cw
    hit_rate = (tot_cr / tot_prompt) if tot_prompt > 0 else 0.0

    pm_tok = pm_in + pm_out + pm_cr + pm_cw
    pm_prompt = pm_in + pm_cr + pm_cw
    pm_hit_rate = (pm_cr / pm_prompt) if pm_prompt > 0 else 0.0

    by_agent_hit = {
        a: (agent_cr[a] / agent_prompt[a]) if agent_prompt[a] > 0 else 0.0
        for a in AGENT_ORDER
        if agent_prompt[a] > 0
    }

    by_model = []
    for ma in sorted(model_agg.values(), key=lambda x: (x["total_tokens"], x["cost_usd"]), reverse=True)[:TOP_MODELS_CAP]:
        m_prompt = ma["input_tokens"] + ma["cache_read_tokens"] + ma["cache_write_tokens"]
        by_model.append({
            **ma,
            "cache_hit_rate": round(ma["cache_read_tokens"] / m_prompt, 4) if m_prompt > 0 else 0.0,
            "cost_usd": round(ma["cost_usd"], 4),
            "cache_savings_usd": round(ma["cache_savings_usd"], 4),
            "pm_cost_usd": round(ma["pm_cost_usd"], 4),
        })

    sorted_tasks = sorted(task_agg.values(), key=lambda x: (x["total_tokens"], x["cost_usd"]), reverse=True)
    picked_tasks = sorted_tasks[:TOP_TASKS_CAP]
    picked_ids = {ta["id"] for ta in picked_tasks}
    # Always preserve PM rows even when a busy workspace has > TOP_TASKS_CAP tasks
    for ta in sorted_tasks[TOP_TASKS_CAP:]:
        if ta["role"] == "pm" and ta["id"] not in picked_ids:
            picked_tasks.append(ta)
            picked_ids.add(ta["id"])

    by_task = []
    for ta in picked_tasks:
        by_task.append({
            "id": ta["id"],
            "number": ta["number"],
            "title": ta["title"],
            "project": ta["project"],
            "pm": ta["pm"],
            "role": ta["role"],
            "status": ta["status"],
            "agents": sorted(ta["agents"]),
            "models": sorted(ta["models"]),
            "sessions": len(ta["sessions"]),
            "requests": ta["requests"],
            "errors": ta["errors"],
            "total_tokens": ta["total_tokens"],
            "input_tokens": ta["input_tokens"],
            "output_tokens": ta["output_tokens"],
            "cache_read_tokens": ta["cache_read_tokens"],
            "cache_write_tokens": ta["cache_write_tokens"],
            "work_tokens": ta["work_tokens"],
            "review_tokens": ta["review_tokens"],
            "cost_usd": round(ta["cost_usd"], 4),
            "work_cost_usd": round(ta["work_cost_usd"], 4),
            "review_cost_usd": round(ta["review_cost_usd"], 4),
            "cache_savings_usd": round(ta["cache_savings_usd"], 4),
            "share": round(ta["total_tokens"] / tot_tok, 4) if tot_tok > 0 else 0.0,
            "by_agent": {k: v for k, v in ta["by_agent"].items() if v > 0},
            "by_agent_cost": {k: round(v, 4) for k, v in ta["by_agent_cost"].items() if v > 0},
            "by_agent_requests": {k: v for k, v in ta["by_agent_requests"].items() if v > 0},
            "by_agent_io": {
                k: {
                    "input_tokens": v["input_tokens"],
                    "output_tokens": v["output_tokens"],
                    "cache_read_tokens": v["cache_read_tokens"],
                    "cache_write_tokens": v["cache_write_tokens"],
                    "models": sorted(v["models"]),
                }
                for k, v in ta["by_agent_io"].items()
                if (v["input_tokens"] + v["output_tokens"] + v["cache_read_tokens"] + v["cache_write_tokens"]) > 0
            },
        })

    by_agent = []
    for a in AGENT_ORDER:
        aa = agent_agg[a]
        ap = aa["input_tokens"] + aa["cache_read_tokens"] + aa["cache_write_tokens"]
        by_agent.append({
            "agent": a,
            "label": aa["label"],
            "requests": aa["requests"],
            "errors": aa["errors"],
            "sessions": len(aa["sessions"]),
            "tasks": len(aa["tasks"]),
            "total_tokens": aa["total_tokens"],
            "input_tokens": aa["input_tokens"],
            "output_tokens": aa["output_tokens"],
            "cache_read_tokens": aa["cache_read_tokens"],
            "cache_write_tokens": aa["cache_write_tokens"],
            "cache_write_available": aa["cache_write_available"],
            "cache_hit_rate": round(aa["cache_read_tokens"] / ap, 4) if ap > 0 else 0.0,
            "cost_usd": round(aa["cost_usd"], 4),
            "cache_savings_usd": round(aa["cache_savings_usd"], 4),
            "pm_tokens": aa["pm_tokens"],
            "pm_cost_usd": round(aa["pm_cost_usd"], 4),
            "pm_requests": aa["pm_requests"],
            "pm_sessions": len(aa["pm_sessions"]),
        })

    pm_by_agent_out: dict[str, Any] = {}
    for a in AGENT_ORDER:
        pba = pm_by_agent.get(a)
        if pba is None:
            continue
        pp = pba["input_tokens"] + pba["cache_read_tokens"] + pba["cache_write_tokens"]
        pm_by_agent_out[a] = {
            "total_tokens": pba["total_tokens"],
            "input_tokens": pba["input_tokens"],
            "output_tokens": pba["output_tokens"],
            "cache_read_tokens": pba["cache_read_tokens"],
            "cache_write_tokens": pba["cache_write_tokens"],
            "prompt_tokens": pp,
            "requests": pba["requests"],
            "errors": pba["errors"],
            "sessions": len(pba["sessions"]),
            "cost_usd": round(pba["cost_usd"], 4),
            "cache_savings_usd": round(pba["cache_savings_usd"], 4),
            "cache_hit_rate": round(pba["cache_read_tokens"] / pp, 4) if pp > 0 else 0.0,
            "models": sorted(pba["models"]),
        }

    pm_summary = {
        "total_tokens": pm_tok,
        "input_tokens": pm_in,
        "output_tokens": pm_out,
        "cache_read_tokens": pm_cr,
        "cache_write_tokens": pm_cw,
        "prompt_tokens": pm_prompt,
        "requests": pm_calls,
        "errors": pm_errs,
        "sessions": len(pm_sessions),
        "cost_usd": round(pm_cost, 4),
        "cache_savings_usd": round(pm_save, 4),
        "cache_hit_rate": round(pm_hit_rate, 4),
        "share": round(pm_tok / tot_tok, 4) if tot_tok > 0 else 0.0,
        "agents": sorted(pm_agents),
        "models": sorted(pm_models),
        "by_agent": pm_by_agent_out,
    }

    for b in buckets_data:
        b["cost_usd"] = round(b["cost_usd"], 4)
        b["advisor_cost"] = round(b["advisor_cost"], 4)
        b["by_agent_tokens"] = {k: v for k, v in b["by_agent_tokens"].items() if v > 0}
        b["by_agent_cost"] = {k: round(v, 4) for k, v in b["by_agent_cost"].items() if v > 0}
        b["by_agent_requests"] = {k: v for k, v in b["by_agent_requests"].items() if v > 0}

    return {
        "range": range_name,
        "bucket_mode": bucket_mode,
        "kpi": {
            "total_tokens": tot_tok,
            "input_tokens": tot_in,
            "output_tokens": tot_out,
            "cache_read_tokens": tot_cr,
            "cache_write_tokens": tot_cw,
            "prompt_tokens": tot_prompt,
            "requests": tot_calls,
            "errors": tot_errs,
            "tasks": len(task_ids),
            "sessions": len(sessions),
            "cost_usd": round(tot_cost, 4),
            "cache_savings_usd": round(tot_save, 4),
            "cache_hit_rate": round(hit_rate, 4),
            "pm_tokens": pm_tok,
            "pm_cost_usd": round(pm_cost, 4),
            "pm_requests": pm_calls,
            "pm_sessions": len(pm_sessions),
            "by_agent_hit_rate": {k: round(v, 4) for k, v in by_agent_hit.items()},
            "by_agent_requests": {a: agent_agg[a]["requests"] for a in AGENT_ORDER if agent_agg[a]["requests"] > 0},
        },
        "pm": pm_summary,
        "buckets": buckets_data,
        "by_model": by_model,
        "by_task": by_task,
        "by_agent": by_agent,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def token_analytics(
    ctx: Context | None = None,
    *,
    project: str | None = None,
    range_name: str | None = None,
) -> dict[str, Any]:
    """Compute pre-sliced token analytics across all 4 runtimes using the incremental SQLite cache."""
    ctx = Context.from_env() if ctx is None else ctx
    t0 = ctx.clock.monotonic()
    cfg = ctx.config.read() if ctx.config is not None else {}
    custom_pricing = cfg.get("token_pricing") if isinstance(cfg, dict) else None

    reg_mod = ProjectRegistry(ctx)
    regs = reg_mod.pm_records()
    tasks = Ledger(ctx).raw_tasks()
    projects_meta, scopes, wt_homes, agy_cids, pm_sids, pm_paths = _build_project_index(ctx, regs, tasks)

    target_slug = ""
    if project:
        target_slug = reg_mod.resolve_project_slug(project)
        if target_slug not in projects_meta:
            raise PmError(f"unknown project: {project}")

    files_rows, rollup_rows = sync_token_cache(
        ctx,
        scopes=scopes,
        wt_homes=wt_homes,
        known_agy_cids=agy_cids,
        known_pm_sids=pm_sids,
        known_pm_paths=pm_paths,
    )
    file_attrs = _attribute_files(files_rows, projects_meta, tasks)

    enriched: list[dict[str, Any]] = []
    for r in rollup_rows:
        attr = file_attrs.get(r["path"])
        if attr is None:
            continue
        if target_slug and attr["slug"] != target_slug:
            continue
        enriched.append({**r, **attr})

    now_dt = ctx.clock.datetime_now()
    want_ranges = (range_name,) if range_name in RANGES else RANGES

    out_projects: dict[str, Any] = {}
    out_projects["__all__"] = {
        "ranges": {
            rn: _build_slice(enriched, range_name=rn, now_dt=now_dt, custom_pricing=custom_pricing)
            for rn in want_ranges
        }
    }
    slug_list = [target_slug] if target_slug else sorted(projects_meta)
    for slug in slug_list:
        pinfo = projects_meta[slug]
        mine = [r for r in enriched if r["slug"] == slug]
        out_projects[slug] = {
            "slug": slug,
            "pm_name": pinfo["pm_name"],
            "project": pinfo["project"],
            "archived": pinfo["archived"],
            "ranges": {
                rn: _build_slice(mine, range_name=rn, now_dt=now_dt, custom_pricing=custom_pricing)
                for rn in want_ranges
            },
        }

    scan_ms = max(0, int(round((ctx.clock.monotonic() - t0) * 1000.0)))
    payload: dict[str, Any] = {
        "version": 1,
        "generated_at": ctx.clock.now_sec(),
        "scan_ms": scan_ms,
        "scope": target_slug or "all",
        "lang": ctx.config.tr("en", "zh") if ctx.config is not None else "en",
        "projects": out_projects,
    }
    if not target_slug and range_name is None:
        _atomic_write_json(ctx.home.token_analytics_cache, payload)
    return payload


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def cmd_tokens(a: Any, ctx: Context | None = None) -> None:
    ctx = Context.from_env() if ctx is None else ctx
    project_arg = None if getattr(a, "all", False) else getattr(a, "project", None)
    want_range = getattr(a, "range", None)
    if getattr(a, "json", False):
        data = token_analytics(ctx, project=project_arg, range_name=want_range)
        ctx.out.json(data)
        return

    rng = want_range or "today"
    data = token_analytics(ctx, project=project_arg, range_name=rng)
    scope_key = data["scope"] if data["scope"] != "all" else "__all__"
    sl = data["projects"][scope_key]["ranges"][rng]
    kpi = sl["kpi"]
    ctx.out.line(
        f"tokens ({data['scope']}, {rng}): {_fmt_tokens(kpi['total_tokens'])} "
        f"[in {_fmt_tokens(kpi['input_tokens'])}, out {_fmt_tokens(kpi['output_tokens'])}, "
        f"cache {_fmt_tokens(kpi['cache_read_tokens'] + kpi['cache_write_tokens'])}] | "
        f"{kpi['requests']} reqs | ${kpi['cost_usd']:.2f} (saved ${kpi['cache_savings_usd']:.2f}) | "
        f"{kpi['cache_hit_rate'] * 100:.1f}% hit ({data['scan_ms']}ms)"
    )
    pm_info = sl.get("pm") or {}
    if pm_info.get("total_tokens", 0) > 0:
        pm_models_txt = f" | {', '.join(pm_info.get('models', [])[:2])}" if pm_info.get("models") else ""
        ctx.out.line(
            f"  - PM: {_fmt_tokens(pm_info['total_tokens'])} "
            f"[in {_fmt_tokens(pm_info['input_tokens'])}, out {_fmt_tokens(pm_info['output_tokens'])}, "
            f"cache {_fmt_tokens(pm_info['cache_read_tokens'] + pm_info['cache_write_tokens'])}] | "
            f"{pm_info['requests']} reqs ({pm_info['sessions']} sess) | ${pm_info['cost_usd']:.2f} | "
            f"{pm_info['share'] * 100:.1f}% share{pm_models_txt}"
        )
    for row in sl["by_agent"]:
        if row["total_tokens"] > 0 or row["errors"] > 0:
            pm_part = f" (PM {_fmt_tokens(row['pm_tokens'])})" if row.get("pm_tokens", 0) > 0 else ""
            ctx.out.line(
                f"  - {row['label']}: {_fmt_tokens(row['total_tokens'])}{pm_part} | "
                f"{row['requests']} reqs | ${row['cost_usd']:.2f} | {row['cache_hit_rate'] * 100:.1f}% hit"
            )


def register_tokens_view(sub: Any) -> None:
    p = sub.add_parser("tokens", help="show token analytics across agent runtimes")
    p.add_argument("project", nargs="?", default=None, help="project slug, name, or folder")
    p.add_argument("--all", action="store_true", help="aggregate across all registered projects")
    p.add_argument("--range", choices=list(RANGES), default=None, help="time range (today, 7d, 30d, all)")
    p.add_argument("--json", action="store_true", help="print full pre-sliced analytics as JSON")
