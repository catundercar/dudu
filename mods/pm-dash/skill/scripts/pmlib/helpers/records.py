"""One helper's record: where it is kept, its result, its screen and terminal, finishing it once, the wait lock, and
reconciling the helpers of an owner or a project. Layer 3.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterator

from ..context import Clock, Context, seconds_since
from ..events.deliver import Delivery
from ..home import project_slug
from ..ledger.ledger import Change, Ledger, slugify
from ..ledger.task import Task, hc_terminal_of
from ..osutil import clip
from ..project.conversation import Conversation
from ..store import fcntl, lock_file, replace_task_file, unlock_file, write_atomic
from .config import HELPER_SCREEN_LINES, HELPER_TIMEOUT, HELPER_WAIT_MAX_PRINT, _positive_int


def helper_elapsed(entry: dict[str, Any], *, clock: Clock | None = None) -> float:
    """Seconds since this helper was started."""
    ts = entry.get("started_ts")
    if isinstance(ts, (int, float)) and ts > 0:
        now_t = clock.time() if clock is not None else time.time()
        return max(0.0, now_t - float(ts))
    if clock is not None:
        return clock.seconds_since(entry.get("started"))
    return seconds_since(entry.get("started"))


def helper_timed_out(entry: dict[str, Any], *, clock: Clock | None = None) -> bool:
    if entry.get("status") != "running":
        return False
    limit = _positive_int(entry.get("timeout"), HELPER_TIMEOUT)
    return helper_elapsed(entry, clock=clock) >= limit


def helper_remaining(entry: dict[str, Any], *, clock: Clock | None = None) -> float:
    limit = _positive_int(entry.get("timeout"), HELPER_TIMEOUT)
    return max(0.0, limit - helper_elapsed(entry, clock=clock))


def helper_entries(record_dict: Any) -> list[dict[str, Any]]:
    raw = record_dict.raw if isinstance(record_dict, Task) else record_dict
    items = (raw or {}).get("helpers")
    return [h for h in items if isinstance(h, dict)] if isinstance(items, list) else []


def helper_result_path_for(ctx: Context, slug: str, owner_dir: str, name: str) -> Path:
    """Pick `<ledger>/projects/<slug>/helpers/<owner_dir>/<name>.md` (suffixing -2, -3 if an earlier non-empty
    result file already occupies that path so prior conclusions are never overwritten)."""
    folder = ctx.home.project(slug).helper_dir(owner_dir)
    base = folder / f"{name}.md"
    if not base.exists() or not helper_result_text(base):
        return base
    for i in range(2, 1000):
        cand = folder / f"{name}-{i}.md"
        if not cand.exists() or not helper_result_text(cand):
            return cand
    return folder / f"{name}-{os.urandom(3).hex()}.md"


def helper_result_text(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def helper_excerpt(path_or_text: Any, width: int = 280) -> str:
    """Short single-line summary from a helper's conclusion file or raw text."""
    text = helper_result_text(path_or_text) if isinstance(path_or_text, Path) else str(path_or_text or "").strip()
    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or (s.startswith("<!--") and s.endswith("-->")):
            continue
        s = re.sub(r"^#+\s*", "", s)
        if s:
            lines.append(s)
        if len(" ".join(lines)) >= width:
            break
    return clip(" ".join(lines), width) if lines else ""


def capture_helper_screen_for(
    ctx: Context,
    term: str,
    result_path: str | Path,
    reason: str = "unreported",
    lines: int = HELPER_SCREEN_LINES,
) -> str:
    """Fallback when a helper finishes or times out without writing its result file: capture the last lines of its
    terminal screen and write them atomically to result_path. Returns the captured text, or "" if empty/unavailable."""
    if not term:
        return ""
    raw = ctx.hc.read(term, lines=lines)
    if not raw:
        return ""
    cleaned = [ln.rstrip() for ln in str(raw).splitlines()]
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    tail = "\n".join(cleaned[-lines:]).strip()
    if not tail:
        return ""
    note_en = ("timeout" if reason == "timeout" else "helper stopped without writing the result file")
    note_zh = ("超时" if reason == "timeout" else "helper 停止时未写入结果文件")
    header = ctx.config.tr(
        f"<!-- Captured from terminal screen ({note_en}). -->\n\n",
        f"<!-- 从终端屏幕截取（{note_zh}）。 -->\n\n",
    )
    write_atomic(Path(result_path), (header + tail + "\n").encode("utf-8"), replace_fn=replace_task_file)
    return tail


def kill_helper_terminal_for(ctx: Context, term: str, remove: bool = False) -> bool:
    """End a helper terminal (hc kill; optional hc rm). Never kills a PM terminal. True when killed/removed."""
    if not term:
        return False
    info = ctx.hc.get_raw(term, errors=True) or {}
    if not info or info.get("error"):
        return False
    labels = info.get("labels") or {}
    if labels.get("pm"):
        return False
    if info.get("state") == "live":
        ctx.hc.kill(term)
    if remove:
        ctx.hc.remove(term)
    return True


def _helper_wait_lock_path_for(ctx: Context, owner_id: str) -> Path:
    return ctx.home.locks / f"helper-wait-{slugify(owner_id) or 'owner'}.lock"


@contextlib.contextmanager
def helper_wait_guard_for(ctx: Context, owner_id: str) -> Iterator[None]:
    """Hold a shared lock while `pm.py helper wait` blocks for this owner, so `helper done` knows not to also
    type an `hc send` notification into the waiting terminal."""
    path = _helper_wait_lock_path_for(ctx, owner_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    locked = False
    try:
        if fcntl is not None:
            with contextlib.suppress(OSError):
                lock_file(f, shared=True)
                locked = True
        yield
    finally:
        if locked:
            with contextlib.suppress(OSError):
                unlock_file(f)
        with contextlib.suppress(OSError):
            f.close()


def helper_wait_active_for(ctx: Context, owner_id: str) -> bool:
    """True when a `pm.py helper wait` process is currently waiting on this owner's helpers."""
    if fcntl is None:
        return False
    path = _helper_wait_lock_path_for(ctx, owner_id)
    if not path.exists():
        return False
    try:
        with open(path, "a+") as f:
            try:
                lock_file(f, shared=False)
            except OSError:
                return True
            with contextlib.suppress(OSError):
                unlock_file(f)
            return False
    except OSError:
        return False


def update_helper_owner_for(
    ctx: Context,
    owner_kind: str,
    owner_id: str,
    slug: str,
    mutate_fn: Callable[[list[dict[str, Any]]], Any],
    task_note: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Atomically mutate the `helpers` list on a PM registration (`ctx.store.change_registration`) or task
    (`Ledger(ctx).change`). `mutate_fn(helpers_list)` returns True to persist (or False/None to skip)."""
    if owner_kind == "pm":
        changed_box = [False]

        def _reg(cur: dict[str, Any] | None) -> dict[str, Any] | None:
            if cur is None:
                return None
            rec = dict(cur)
            items = [dict(h) for h in helper_entries(rec)]
            if not mutate_fn(items):
                return None
            rec["helpers"] = items
            changed_box[0] = True
            return rec

        updated = ctx.store.change_registration(slug, _reg)
        return updated, changed_box[0]

    changed_box = [False]

    def _task(cur: Task | None, ch: Change) -> dict[str, Any] | None:
        if cur is None:
            return None
        task = cur.raw
        items = [dict(h) for h in helper_entries(task)]
        if not mutate_fn(items):
            return None
        task["helpers"] = items
        if task_note:
            ch.note(task_note)
        changed_box[0] = True
        return task

    updated_task = Ledger(ctx).change(owner_id, _task)
    updated_raw = updated_task.raw if isinstance(updated_task, Task) else updated_task
    return updated_raw, changed_box[0]


def _match_helper(items: list[dict[str, Any]], term: str = "", name: str = "", running_only: bool = False) -> int:
    """Find the index of a helper entry matching `term` (exact) or `name` (latest matching).
    When `term` is given, only that exact terminal matches (no fallback to `name`), so a stale
    harvest, Stop hook, or duplicate `done` for an old terminal can never touch a newer helper of the same name."""
    if term:
        for i in range(len(items) - 1, -1, -1):
            if items[i].get("terminal") == term and (not running_only or items[i].get("status") == "running"):
                return i
        return -1
    if name:
        for i in range(len(items) - 1, -1, -1):
            if items[i].get("name") == name and (not running_only or items[i].get("status") == "running"):
                return i
    return -1


def finalize_helper_for(
    ctx: Context,
    owner_kind: str,
    owner_id: str,
    slug: str,
    repo: str,
    *,
    term: str = "",
    name: str = "",
    status: str = "done",
    summary: str = "",
    fallback: str = "",
    kill_term: bool = False,
    remove_term: bool = False,
    notify: bool = True,
    cleanup_term: bool = False,
    note_text: str = "",
) -> tuple[dict[str, Any] | None, bool]:
    """Transition a running helper to a terminal state atomically via `ctx.store`, optionally kill its terminal and
    deliver/notify its owner. Idempotent: only emits a notification on the first transition out of `running`.
    Returns `(entry_or_None, transitioned)`."""
    captured: list[dict[str, Any] | None] = [None]
    transitioned = [False]

    def _apply(items: list[dict[str, Any]]) -> bool:
        idx = _match_helper(items, term=term, name=name, running_only=True)
        if idx < 0:
            idx = _match_helper(items, term=term, name=name, running_only=False)
            if idx < 0:
                return False
            captured[0] = dict(items[idx])
            if summary and items[idx].get("status") == status and not items[idx].get("summary"):
                items[idx]["summary"] = summary
                captured[0] = dict(items[idx])
                return True
            return False
        h = items[idx]
        h["status"] = status
        h["ended"] = ctx.clock.now_sec()
        if summary:
            h["summary"] = summary
        if fallback:
            h["fallback"] = fallback
        if cleanup_term:
            h["cleanup_term"] = True
        else:
            h.pop("cleanup_term", None)
        captured[0] = dict(h)
        transitioned[0] = True
        return True

    h_preview_name = name or term
    log_msg = note_text
    if owner_kind == "task" and not log_msg:
        if status == "done":
            fb = ctx.config.tr(" (from screen)", "（从屏幕截取）") if fallback == "screen" else ""
            log_msg = ctx.config.tr(
                f"helper {h_preview_name} done{fb}: {summary}" if summary else f"helper {h_preview_name} done{fb}",
                f"helper {h_preview_name} 完成{fb}：{summary}" if summary else f"helper {h_preview_name} 完成{fb}",
            )
        elif status == "timeout":
            log_msg = ctx.config.tr(f"helper {h_preview_name} timed out", f"helper {h_preview_name} 超时已结束")
        elif status == "stopped":
            log_msg = ctx.config.tr(f"stopped helper {h_preview_name}", f"已停止 helper {h_preview_name}")
        else:
            log_msg = ctx.config.tr(f"helper {h_preview_name} {status}", f"helper {h_preview_name} 状态={status}")

    update_helper_owner_for(ctx, owner_kind, owner_id, slug, _apply, task_note=log_msg if owner_kind == "task" else None)
    entry = captured[0]
    if not entry:
        return None, False
    hterm = entry.get("terminal") or term
    if kill_term and hterm and transitioned[0]:
        kill_helper_terminal_for(ctx, hterm, remove=remove_term)
    if notify and transitioned[0]:
        _notify_helper_owner_for(ctx, owner_kind, owner_id, repo, entry)
    return entry, transitioned[0]


def _send_to_worker_if_active_for(ctx: Context, owner_id: str, entry: dict[str, Any], msg: str) -> bool:
    """Send a helper message to a worker terminal only while its task is still `in_progress`, not retired,
    still on the same terminal that spawned the helper, live in hc, and not blocked inside `pm.py helper wait`."""
    if helper_wait_active_for(ctx, owner_id):
        return False
    task = ctx.store.task(owner_id)
    if not task or task.get("status") != "in_progress" or task.get("retired"):
        return False
    current_term = hc_terminal_of(task)
    parent = entry.get("parent") or ""
    if not current_term or (parent and current_term != parent):
        return False
    info = ctx.hc.get_raw(current_term) or {}
    if info.get("state") != "live":
        return False
    return bool(ctx.hc.send(current_term, msg))


def _notify_helper_owner_for(
    ctx: Context,
    owner_kind: str,
    owner_id: str,
    repo: str,
    entry: dict[str, Any],
) -> None:
    """Deliver a helper's conclusion/status to its owner: PM via project conversation log + deliver, worker via
    hc send (only while its task is still `in_progress` on the same terminal and not in `pm.py helper wait`)."""
    name = entry.get("name") or "?"
    term = entry.get("terminal") or ""
    status = entry.get("status") or "done"
    result = entry.get("result") or ""
    summary = entry.get("summary") or (helper_excerpt(Path(result)) if result else "")
    fb = ctx.config.tr(" (captured from screen)", "（从屏幕截取）") if entry.get("fallback") == "screen" else ""
    if status == "done":
        text = ctx.config.tr(
            f"helper {name} done{fb} ({result})" + (f": {summary}" if summary else ""),
            f"helper {name} 完成{fb}（{result}）" + (f"：{summary}" if summary else ""),
        )
    elif status == "timeout":
        text = ctx.config.tr(
            f"helper {name} timed out ({result})" + (f": {summary}" if summary else ""),
            f"helper {name} 超时已结束（{result}）" + (f"：{summary}" if summary else ""),
        )
    else:
        text = ctx.config.tr(
            f"helper {name} {status}" + (f" ({result})" if result else "") + (f": {summary}" if summary else ""),
            f"helper {name} {status}" + (f"（{result}）" if result else "") + (f"：{summary}" if summary else ""),
        )
    if owner_kind == "pm":
        if repo:
            Conversation(ctx, repo).record(
                "helper", by=f"hc:{term}" if term else "helper", source="helper", helper=name,
                status=status, result=result, text=text, wake=True,
            )
            Delivery(ctx, repo).ensure_running()
        return
    _send_to_worker_if_active_for(ctx, owner_id, entry, f"[from helper {name}] {text}")


def _harvest_entry_for(
    ctx: Context,
    owner_kind: str,
    owner_id: str,
    slug: str,
    repo: str,
    entry: dict[str, Any],
    *,
    reason: str = "done",
    kill_term: bool = False,
    notify: bool = True,
) -> tuple[dict[str, Any] | None, bool]:
    """Harvest a finished/exited/timed-out helper: read its result file if present, else capture its screen."""
    term = entry.get("terminal") or ""
    name = entry.get("name") or ""
    result = Path(entry.get("result") or "")
    file_text_val = helper_result_text(result) if entry.get("result") else ""
    text = file_text_val
    fallback = ""
    if not text and entry.get("result") and term:
        captured = capture_helper_screen_for(ctx, term, result, reason=reason)
        if captured:
            text = captured
            fallback = "screen"
    summary = helper_excerpt(text) if text else ""
    if reason == "timeout":
        status = "timeout"
    elif reason == "gone" and not file_text_val:
        status = "exited"
    else:
        status = "done"
    return finalize_helper_for(
        ctx, owner_kind, owner_id, slug, repo, term=term, name=name, status=status, summary=summary,
        fallback=fallback, kill_term=kill_term, notify=notify,
    )


def reconcile_owner_helpers_for(
    ctx: Context,
    owner_kind: str,
    owner_id: str,
    slug: str,
    repo: str,
    live_rows: dict[str, Any] | None = None,
    notify: bool = True,
) -> list[dict[str, Any]]:
    """Reconcile running helpers of one owner: sweep timeouts and mark exited/removed terminals.
    Fast-path: does zero hc calls when the owner has no running helpers."""
    rec = ctx.store.registration(slug) if owner_kind == "pm" else ctx.store.task(owner_id)
    running = [h for h in helper_entries(rec) if h.get("status") == "running"]
    if not running:
        return []
    out: list[dict[str, Any]] = []
    for h in running:
        term = h.get("terminal") or ""
        if helper_timed_out(h, clock=ctx.clock):
            entry, _ = _harvest_entry_for(
                ctx, owner_kind, owner_id, slug, repo, h, reason="timeout", kill_term=True, notify=notify,
            )
            if entry:
                out.append(entry)
            continue
        if not term:
            continue
        if live_rows is not None:
            alive = term in live_rows
            if alive:
                continue
            info = ctx.hc.get_raw(term, errors=True) or {}
        else:
            info = ctx.hc.get_raw(term, errors=True) or {}
        gone = ((info.get("error") or {}).get("kind") == "not_found"
                or (not info.get("error") and info.get("state") != "live")
                or (info.get("reported") and not info.get("status")))
        if gone:
            entry, _ = _harvest_entry_for(
                ctx, owner_kind, owner_id, slug, repo, h, reason="gone", kill_term=False, notify=notify,
            )
            if entry:
                out.append(entry)
    return out


def reconcile_project_helpers_for(ctx: Context, repo: str | Path, notify: bool = True) -> list[dict[str, Any]]:
    """Reconcile all running helpers across a project's PM registration and tasks.
    Fast-path: does zero hc calls when no running helper exists anywhere in the project."""
    if not repo:
        return []
    repo_str = str(repo)
    slug = project_slug(repo_str)
    reg = ctx.store.registration(slug)
    tasks = Ledger(ctx).project_tasks(repo_str)
    pm_has = any(h.get("status") == "running" for h in helper_entries(reg))
    task_owners = [t for t in tasks if any(h.get("status") == "running" for h in helper_entries(t))]
    if not pm_has and not task_owners:
        return []
    live_rows = ctx.hc.live_rows()
    out: list[dict[str, Any]] = []
    if pm_has:
        out += reconcile_owner_helpers_for(ctx, "pm", f"pm-{slug}", slug, repo_str, live_rows=live_rows, notify=notify)
    for t in task_owners:
        out += reconcile_owner_helpers_for(
            ctx, "task", t["id"], slug, t.get("repo") or repo_str, live_rows=live_rows, notify=notify,
        )
    return out


def project_running_helpers_for(ctx: Context, repo: str | Path) -> list[dict[str, Any]]:
    """All helpers currently marked `running` across this project's PM registration and tasks (no hc calls)."""
    if not repo:
        return []
    repo_str = str(repo)
    slug = project_slug(repo_str)
    out = [h for h in helper_entries(ctx.store.registration(slug)) if h.get("status") == "running"]
    for t in Ledger(ctx).project_tasks(repo_str):
        out += [h for h in helper_entries(t) if h.get("status") == "running"]
    return out


def project_active_counts_for(ctx: Context, repo: str | Path) -> tuple[int, list[dict[str, Any]]]:
    """(active_threads_count, running_helpers_list) for enforcing `helpers.project_max`."""
    repo_str = str(repo)
    tasks = Ledger(ctx).project_tasks(repo_str)
    in_prog = [t for t in tasks if t.get("status") == "in_progress" and not t.get("retired")]
    hc_needed = any(hc_terminal_of(t) for t in in_prog)
    live = ctx.hc.live_terminals() if hc_needed else None
    active_threads = 0
    for t in in_prog:
        term = hc_terminal_of(t)
        if not term or live is None or term in live:
            active_threads += 1
    return active_threads, project_running_helpers_for(ctx, repo_str)


def _clear_helper_cleanup_for(ctx: Context, owner_kind: str, owner_id: str, slug: str, term: str) -> None:
    def _clear(items: list[dict[str, Any]]) -> bool:
        idx = _match_helper(items, term=term, running_only=False)
        if idx < 0 or not items[idx].get("cleanup_term"):
            return False
        items[idx].pop("cleanup_term", None)
        return True
    update_helper_owner_for(ctx, owner_kind, owner_id, slug, _clear)


def _helper_owner_ledger_paths_for(ctx: Context, owner_kind: str, owner_id: str, slug: str) -> tuple[list[Path], list[Path]]:
    if owner_kind == "pm":
        return [ctx.home.registrations], [ctx.home.registration(slug)]
    return [ctx.home.tasks], [ctx.home.task(owner_id)]


def _format_helper_wait_results(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in entries:
        result_path = h.get("result") or ""
        text = helper_result_text(Path(result_path)) if result_path else ""
        item: dict[str, Any] = {
            "name": h.get("name") or "",
            "terminal": f"hc:{h['terminal']}" if h.get("terminal") else "",
            "status": h.get("status") or "",
            "result": result_path,
            "summary": h.get("summary") or "",
            "content": text,
        }
        if h.get("fallback"):
            item["fallback"] = h["fallback"]
        if h.get("alert"):
            item["alert"] = h["alert"]
        out.append(item)
    return out


def format_helper_wait_lines(ctx: Context, items: list[dict[str, Any]], as_json: bool = False) -> list[str]:
    """Render formatted helper wait results as stdout lines (no printing in Layer 3)."""
    if as_json:
        return [json.dumps(items, ensure_ascii=False, indent=2)]
    lines: list[str] = []
    for item in items:
        lines.append(f"=== helper {item['name']} [{item['status']}] {item['terminal']} ===")
        if item.get("result"):
            lines.append(f"result: {item['result']}")
        if item.get("alert"):
            lines.append(item["alert"])
        content = item.get("content") or ""
        if content:
            if len(content) > HELPER_WAIT_MAX_PRINT:
                lines.append(content[:HELPER_WAIT_MAX_PRINT] + ctx.config.tr(
                    f"\n... (clipped; read full file: {item['result']})",
                    f"\n...（已截断；完整内容见：{item['result']}）",
                ))
            else:
                lines.append(content)
        elif item.get("summary"):
            lines.append(item["summary"])
    return lines


# ── Legacy module-level shims (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────


def helper_result_path(slug: str, owner_dir: str, name: str) -> Path:
    return helper_result_path_for(Context.from_env(), slug, owner_dir, name)


def capture_helper_screen(
    term: str,
    result_path: str | Path,
    reason: str = "unreported",
    lines: int = HELPER_SCREEN_LINES,
) -> str:
    return capture_helper_screen_for(Context.from_env(), term, result_path, reason=reason, lines=lines)


def kill_helper_terminal(term: str, remove: bool = False) -> bool:
    return kill_helper_terminal_for(Context.from_env(), term, remove=remove)


def _helper_wait_lock_path(owner_id: str) -> Path:
    return _helper_wait_lock_path_for(Context.from_env(), owner_id)


@contextlib.contextmanager
def helper_wait_guard(owner_id: str) -> Iterator[None]:
    with helper_wait_guard_for(Context.from_env(), owner_id):
        yield


def helper_wait_active(owner_id: str) -> bool:
    return helper_wait_active_for(Context.from_env(), owner_id)


def update_helper_owner(
    owner_kind: str,
    owner_id: str,
    slug: str,
    mutate_fn: Callable[[list[dict[str, Any]]], Any],
    task_note: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    return update_helper_owner_for(Context.from_env(), owner_kind, owner_id, slug, mutate_fn, task_note=task_note)


def finalize_helper(
    owner_kind: str,
    owner_id: str,
    slug: str,
    repo: str,
    *,
    term: str = "",
    name: str = "",
    status: str = "done",
    summary: str = "",
    fallback: str = "",
    kill_term: bool = False,
    remove_term: bool = False,
    notify: bool = True,
    cleanup_term: bool = False,
    note_text: str = "",
) -> tuple[dict[str, Any] | None, bool]:
    return finalize_helper_for(
        Context.from_env(), owner_kind, owner_id, slug, repo,
        term=term, name=name, status=status, summary=summary, fallback=fallback,
        kill_term=kill_term, remove_term=remove_term, notify=notify,
        cleanup_term=cleanup_term, note_text=note_text,
    )


def _send_to_worker_if_active(owner_id: str, entry: dict[str, Any], msg: str) -> bool:
    return _send_to_worker_if_active_for(Context.from_env(), owner_id, entry, msg)


def _notify_helper_owner(owner_kind: str, owner_id: str, repo: str, entry: dict[str, Any]) -> None:
    _notify_helper_owner_for(Context.from_env(), owner_kind, owner_id, repo, entry)


def _harvest_entry(
    owner_kind: str,
    owner_id: str,
    slug: str,
    repo: str,
    entry: dict[str, Any],
    *,
    reason: str = "done",
    kill_term: bool = False,
    notify: bool = True,
) -> tuple[dict[str, Any] | None, bool]:
    return _harvest_entry_for(
        Context.from_env(), owner_kind, owner_id, slug, repo, entry,
        reason=reason, kill_term=kill_term, notify=notify,
    )


def reconcile_owner_helpers(
    owner_kind: str,
    owner_id: str,
    slug: str,
    repo: str,
    live_rows: dict[str, Any] | None = None,
    notify: bool = True,
) -> list[dict[str, Any]]:
    return reconcile_owner_helpers_for(
        Context.from_env(), owner_kind, owner_id, slug, repo, live_rows=live_rows, notify=notify,
    )


def reconcile_project_helpers(repo: str | Path, notify: bool = True) -> list[dict[str, Any]]:
    return reconcile_project_helpers_for(Context.from_env(), repo, notify=notify)


def project_running_helpers(repo: str | Path) -> list[dict[str, Any]]:
    return project_running_helpers_for(Context.from_env(), repo)


def project_active_counts(repo: str | Path) -> tuple[int, list[dict[str, Any]]]:
    return project_active_counts_for(Context.from_env(), repo)


def _clear_helper_cleanup(owner_kind: str, owner_id: str, slug: str, term: str) -> None:
    _clear_helper_cleanup_for(Context.from_env(), owner_kind, owner_id, slug, term)


def _helper_owner_ledger_paths(owner_kind: str, owner_id: str, slug: str) -> tuple[list[Path], list[Path]]:
    return _helper_owner_ledger_paths_for(Context.from_env(), owner_kind, owner_id, slug)
