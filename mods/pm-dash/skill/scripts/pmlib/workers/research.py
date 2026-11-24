"""Collecting untracked research reports (`evidence/<topic>/README.md`) from worker worktrees and checking
worktree cleanliness during retire. Layer 3."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import stat
from typing import Any, Iterable

from ..context import Context
from ..home import project_slug
from ..ledger.task import Task
from ..store import (
    DOCUMENT_MAX,
    LEDGER_RESEARCH_FOLDER,
    RENDER_CHECK_MARKER,
    RESEARCH_FILENAME,
    RESEARCH_FOLDER,
    StoreError,
    is_excluded_research_topic,
    write_atomic,
)


def _git_tracked_research_for(ctx: Context, folder: str | Path) -> set[str]:
    """POSIX paths tracked by git under `<folder>/evidence`, or set() when not in git / on error."""
    return ctx.git.tracked_files(folder, RESEARCH_FOLDER)


def evidence_is_ignored_for(ctx: Context, repo: str | Path) -> bool:
    """Whether git ignores `evidence/` in `repo` (checks .gitignore, .git/info/exclude and global excludes)."""
    return ctx.git.is_ignored(repo, f"{RESEARCH_FOLDER}/__probe__")


def retire_dirty_for(ctx: Context, worktree: str | Path, ignore_untracked: Iterable[str] = ()) -> int | None:
    """Count uncommitted changes in `worktree`, excluding `.tools` and already-collected untracked reports.

    Uses `-uall -z` so untracked directories are expanded per file and non-ASCII names are never octal-escaped.
    Only untracked (`??`) paths matching `evidence/<rel>` in `ignore_untracked` are excluded; modified, staged
    or uncollected untracked files still count as dirty.
    """
    if getattr(ctx, "_legacy", False) and retire_dirty is not _DEFAULT_RETIRE_DIRTY:
        return retire_dirty(worktree, ignore_untracked=ignore_untracked)
    return _retire_dirty_impl(ctx, worktree, ignore_untracked)


def _retire_dirty_impl(ctx: Context, worktree: str | Path, ignore_untracked: Iterable[str] = ()) -> int | None:
    raw = ctx.git.porcelain_status_z(worktree)
    if raw is None:
        return None
    ignored = {f"{RESEARCH_FOLDER}/{p}" for p in ignore_untracked}
    items = raw.split("\0")
    dirty, i = 0, 0
    while i < len(items):
        entry = items[i]
        i += 1
        if not entry:
            continue
        xy, path = entry[:2], entry[3:]
        if xy[0] in ("R", "C") or xy[1] in ("R", "C"):
            i += 1  # consume the old path emitted after a rename/copy entry in `-z` output
        if path == ".tools" or (xy == "??" and path in ignored):
            continue
        dirty += 1
    return dirty


def collect_research_for(
    ctx: Context,
    task: Any,
    worktree: str | Path | None = None,
    *,
    report_saved: bool = False,
) -> Any:
    if getattr(ctx, "_legacy", False) and collect_research is not _DEFAULT_COLLECT_RESEARCH:
        return collect_research(task, worktree=worktree, report_saved=report_saved)
    return _collect_research_impl(ctx, task, worktree=worktree, report_saved=report_saved)


def _collect_research_impl(
    ctx: Context,
    task: Any,
    worktree: str | Path | None = None,
    *,
    report_saved: bool = False,
) -> Any:
    """Collect untracked `evidence/<topic>/README.md` reports from a worker worktree.

    Destination:
    - When git ignores `evidence/` in the main checkout: `<repo>/evidence/<topic>/README.md`.
    - When git does NOT ignore `evidence/` (e.g. external repos): `<PM_HOME>/projects/<slug>/research/<topic>/README.md`,
      keeping the main checkout git-clean so private reports cannot be accidentally committed by `git add`.

    Skips test-output folders (`render-check` or folders carrying `.render-check`), symlinks, git-tracked files
    (so `git merge` is never blocked and tracked files in the main checkout are never overwritten), and never
    clobbers a strictly newer edit at the destination.
    When `report_saved` is True, returns `(collected, saved)` where `saved` lists every worktree report safely
    present at the destination (newly collected, already identical, or superseded by a newer destination edit).
    """
    empty: Any = ([], []) if report_saved else []
    raw_task = task.raw if isinstance(task, Task) else task
    if not isinstance(raw_task, dict) or raw_task.get("review_of"):
        return empty
    repo = raw_task.get("repo") or ""
    wt = worktree if worktree is not None else (raw_task.get("worktree") or "")
    if not wt and repo and raw_task.get("branch") and raw_task.get("branch") != raw_task.get("base") and Path(repo).is_dir():
        wt = ctx.git.checkout_of(repo, raw_task["branch"]) or ""
    if not repo or not wt:
        return empty
    try:
        real_repo = Path(repo).resolve(strict=True)
        real_wt = Path(wt).resolve(strict=True)
    except OSError:
        return empty
    if real_wt == real_repo or not real_repo.is_dir() or not real_wt.is_dir():
        return empty

    src_ev = real_wt / RESEARCH_FOLDER
    try:
        ev_st = os.lstat(src_ev)
        if stat.S_ISLNK(ev_st.st_mode) or not stat.S_ISDIR(ev_st.st_mode):
            return empty
        real_src_ev = src_ev.resolve(strict=True)
    except OSError:
        return empty
    if real_src_ev.parent != real_wt:
        return empty

    candidates = []
    try:
        with os.scandir(real_src_ev) as it:
            top_entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return empty

    for entry in top_entries:
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
        try:
            os.lstat(topic_dir / RENDER_CHECK_MARKER)
            continue
        except OSError:
            pass
        readme = topic_dir / RESEARCH_FILENAME
        try:
            rst = os.lstat(readme)
        except OSError:
            continue
        if not stat.S_ISLNK(rst.st_mode) and stat.S_ISREG(rst.st_mode) and rst.st_size <= DOCUMENT_MAX:
            candidates.append((f"{topic}/{RESEARCH_FILENAME}", readme))

    if not candidates:
        return empty

    use_repo_ev = evidence_is_ignored_for(ctx, real_repo)
    tracked = _git_tracked_research_for(ctx, real_wt) | (_git_tracked_research_for(ctx, real_repo) if use_repo_ev else set())
    candidates = [(rel, p) for rel, p in candidates if f"{RESEARCH_FOLDER}/{rel}" not in tracked]
    if not candidates:
        return empty

    dst_parent = real_repo if use_repo_ev else ctx.home.project_for(str(real_repo)).root
    dst_root = dst_parent / (RESEARCH_FOLDER if use_repo_ev else LEDGER_RESEARCH_FOLDER)
    try:
        dst_root_st = os.lstat(dst_root)
    except FileNotFoundError:
        dst_root_st = None
    except OSError:
        return empty
    if dst_root_st is not None:
        if stat.S_ISLNK(dst_root_st.st_mode) or not stat.S_ISDIR(dst_root_st.st_mode):
            return empty
        try:
            if dst_root.resolve(strict=True).parent != dst_parent.resolve(strict=True):
                return empty
        except OSError:
            return empty

    open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    collected: list[str] = []
    saved: list[str] = []
    real_dst_root = None

    for rel, src_path in candidates:
        try:
            fd = os.open(src_path, open_flags)
            with os.fdopen(fd, "rb") as f:
                src_st = os.fstat(f.fileno())
                if not stat.S_ISREG(src_st.st_mode) or src_st.st_size > DOCUMENT_MAX:
                    continue
                data = f.read(DOCUMENT_MAX + 1)
        except OSError:
            continue
        if len(data) > DOCUMENT_MAX or b"\x00" in data:
            continue

        dst_path = dst_root / rel
        parent_dir = dst_path.parent
        try:
            pst = os.lstat(parent_dir)
            if stat.S_ISLNK(pst.st_mode) or not stat.S_ISDIR(pst.st_mode):
                continue
        except FileNotFoundError:
            pass
        except OSError:
            continue

        try:
            dst_st = os.lstat(dst_path)
        except FileNotFoundError:
            dst_st = None
        except OSError:
            continue
        if dst_st is not None:
            if stat.S_ISLNK(dst_st.st_mode) or not stat.S_ISREG(dst_st.st_mode):
                continue
            try:
                dfd = os.open(dst_path, open_flags)
                with os.fdopen(dfd, "rb") as df:
                    opened_dst = os.fstat(df.fileno())
                    if not stat.S_ISREG(opened_dst.st_mode):
                        continue
                    existing = df.read(DOCUMENT_MAX + 1)
            except OSError:
                continue
            if existing == data or opened_dst.st_mtime > src_st.st_mtime + 1e-6:
                saved.append(rel)
                continue

        try:
            if real_dst_root is None:
                if not use_repo_ev:
                    dst_parent.mkdir(parents=True, exist_ok=True)
                    p_after = os.lstat(dst_parent)
                    if stat.S_ISLNK(p_after.st_mode) or not stat.S_ISDIR(p_after.st_mode):
                        return (collected, saved) if report_saved else collected
                dst_root.mkdir(exist_ok=True)
                r_after = os.lstat(dst_root)
                if stat.S_ISLNK(r_after.st_mode) or not stat.S_ISDIR(r_after.st_mode):
                    return (collected, saved) if report_saved else collected
                real_dst_root = dst_root.resolve(strict=True)
                if real_dst_root.parent != dst_parent.resolve(strict=True):
                    return (collected, saved) if report_saved else collected
            dst_path.parent.mkdir(exist_ok=True)
            pst = os.lstat(dst_path.parent)
            if stat.S_ISLNK(pst.st_mode) or not stat.S_ISDIR(pst.st_mode):
                continue
            if dst_path.parent.resolve(strict=True).parent != real_dst_root:
                continue
            write_atomic(dst_path, data)
            with contextlib.suppress(OSError):
                os.utime(dst_path, (src_st.st_atime, src_st.st_mtime))
            with contextlib.suppress(OSError, StoreError, ValueError):
                ctx.store.note_research_source(project_slug(str(real_repo)), f"{RESEARCH_FOLDER}/{rel}", raw_task.get("id") or "")
            collected.append(rel)
            saved.append(rel)
        except OSError:
            continue

    return (collected, saved) if report_saved else collected


def _git_tracked_research(folder: str | Path) -> set[str]:
    return _git_tracked_research_for(Context.from_env(), folder)


def evidence_is_ignored(repo: str | Path) -> bool:
    return evidence_is_ignored_for(Context.from_env(), repo)


def retire_dirty(worktree: str | Path, ignore_untracked: Iterable[str] = ()) -> int | None:
    return _retire_dirty_impl(Context.from_env(), worktree, ignore_untracked)


_DEFAULT_RETIRE_DIRTY = retire_dirty


def collect_research(task: Any, worktree: str | Path | None = None, *, report_saved: bool = False) -> Any:
    return _collect_research_impl(Context.from_env(), task, worktree=worktree, report_saved=report_saved)


_DEFAULT_COLLECT_RESEARCH = collect_research
