"""Ledger home inspection and migration (~/.claude/pm -> ~/.dudu): `HomeMover` over explicit `Context`, plus legacy
wrappers. Layer 3."""
from __future__ import annotations

import contextlib
import errno
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
from typing import Any

from .context import Context
from .ledger.task import ACTIVE
from .osutil import WINDOWS, stale_lock
from .store import file_lock, lock_file, replace_task_file, unlock_file, write_atomic

LEDGER_DIR_MARKERS = ("tasks", "pms", "projects", "memory", "sent", "inbox", "install")
LEDGER_FILE_MARKERS = ("BOARD.md", "config.json", "turns.log", "pm-settings.json")
LEGACY_SERVICE_MARKERS = ("dudu.db", "dudu.db-wal", "dudu.db-shm", "d.sock", "service.lock")


def _samefile(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        return child.resolve().is_relative_to(parent.resolve())
    except (OSError, ValueError):
        return False


def _unique_path(base: Path, suffix: str = "") -> Path:
    candidate = base
    n = 2
    while os.path.lexists(candidate):
        if suffix and base.name.endswith(suffix):
            stem = base.name[:-len(suffix)]
            candidate = base.with_name(f"{stem}-{n}{suffix}")
        else:
            candidate = base.with_name(f"{base.name}-{n}")
        n += 1
    return candidate


def _format_bytes(size: int | float) -> str:
    val = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024 or unit == "GB":
            return f"{int(val)} B" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{int(size)} B"


def _is_flock_held(path: Path) -> bool:
    """Probe whether another process currently holds an exclusive flock on an existing file without modifying it."""
    if not path.is_file() or path.is_symlink():
        return False
    mode = "r+b" if WINDOWS else "rb"
    try:
        with open(path, mode) as f:
            try:
                lock_file(f, shared=True)
            except OSError:
                return True
            unlock_file(f)
    except OSError:
        return False
    return False


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    if WINDOWS:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def ledger_markers(path: Path) -> list[str]:
    """Ledger marker folders/files present inside directory `path`."""
    if not path.is_dir() or path.is_symlink():
        return []
    found = [name for name in LEDGER_DIR_MARKERS if (path / name).is_dir()]
    found += [name for name in LEDGER_FILE_MARKERS if (path / name).is_file()]
    return sorted(found)


def legacy_service_markers(path: Path) -> list[str]:
    """Non-ledger markers of the old standalone dudu service inside directory `path`."""
    if not path.is_dir() or path.is_symlink():
        return []
    found = [name for name in LEGACY_SERVICE_MARKERS if os.path.lexists(path / name)]
    if not ledger_markers(path) and (path / "hc").is_dir() and ((path / "agents").is_dir() or (path / "bin").is_dir()):
        for name in ("agents", "bin", "hc"):
            if (path / name).is_dir() and name not in found:
                found.append(name)
    return sorted(found)


def _read_json_safe(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _rewrite_prefix(value: str, old_prefix: str, new_prefix: str) -> str | None:
    if value == old_prefix:
        return new_prefix
    if value.startswith(old_prefix + os.sep):
        return new_prefix + value[len(old_prefix):]
    if value.startswith(old_prefix + "/"):
        return new_prefix + value[len(old_prefix):]
    return None


def _move_ledger_dir(source: Path, target: Path) -> Path | None:
    """Move `source` to `target` (atomic rename on same fs; safe staging copy on EXDEV). Returns leftover source path if EXDEV."""
    try:
        os.rename(source, target)
        return None
    except OSError as err:
        if err.errno != errno.EXDEV:
            raise
    staging = _unique_path(target.parent / f".dudu.migrating.{os.getpid()}")
    displaced = _unique_path(source.parent / f".pm.migrated.{os.getpid()}")
    try:
        shutil.copytree(source, staging, symlinks=True)
        os.rename(staging, target)
        staging = None
        os.rename(source, displaced)
        return displaced
    except BaseException:
        if staging is not None:
            with contextlib.suppress(OSError):
                shutil.rmtree(staging)
        if not os.path.lexists(source) and os.path.lexists(displaced):
            with contextlib.suppress(OSError):
                os.rename(displaced, source)
        if os.path.lexists(target) and not os.path.lexists(displaced):
            with contextlib.suppress(OSError):
                shutil.rmtree(target)
        raise


def _default_backfill_backup_dir(state: str | Path) -> Path:
    default_home = Path.home().resolve()
    state_res = Path(state).resolve()
    if state_res in ((default_home / ".claude" / "pm").resolve(), (default_home / ".dudu").resolve()):
        return default_home / ".claude" / "pm-backups"
    return state_res.parent / "pm-backups"


def create_verified_backup(source: Path, backup_path: Path) -> dict[str, Any]:
    """Create a gzip tarball of `source` atomically, verify every archive member, and move into place."""
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = backup_path.parent / f".{backup_path.name}.{os.getpid()}.tmp"
    added = 0
    skipped: list[str] = []
    try:
        with open(tmp_path, "wb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz") as tf:
                tf.add(source, arcname="pm", recursive=False)
                added += 1
                for root, dirs, files in os.walk(source, followlinks=False):
                    dirs.sort()
                    files.sort()
                    root_path = Path(root)
                    for name in list(dirs) + list(files):
                        full = root_path / name
                        rel = full.relative_to(source).as_posix()
                        try:
                            st = os.lstat(full)
                        except OSError as err:
                            skipped.append(f"{rel} ({err})")
                            continue
                        mode = st.st_mode
                        if stat.S_ISSOCK(mode) or stat.S_ISFIFO(mode) or stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
                            skipped.append(rel)
                            continue
                        if stat.S_ISREG(mode) and ((rel.startswith("locks/") and name.endswith(".lock"))
                                                   or (name.startswith(".") and name.endswith(".tmp"))):
                            skipped.append(rel)
                            continue
                        tf.add(full, arcname=f"pm/{rel}", recursive=False)
                        added += 1
            raw.flush()
            os.fsync(raw.fileno())
        with tarfile.open(tmp_path, "r:gz") as check:
            members = check.getmembers()
        if len(members) != added or added < 1:
            raise OSError(f"backup verification failed: expected {added} entries, read {len(members)}")
        os.replace(tmp_path, backup_path)
        tmp_path = None
        if not WINDOWS:
            try:
                dfd = os.open(backup_path.parent, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)
    return {"path": str(backup_path), "size": backup_path.stat().st_size, "entries": added, "skipped": skipped}


def find_generated_path_updates(ledger_dir: Path, old_source: Path, new_target: Path) -> list[tuple[Path, str]]:
    """Find generated settings files and BOARD.md inside `ledger_dir` whose paths still point at `old_source`."""
    old_str, new_str = str(old_source), str(new_target)
    updates: list[tuple[Path, str]] = []
    if not ledger_dir.is_dir():
        return updates
    candidates: list[Path] = []
    projects_dir = ledger_dir / "projects"
    if projects_dir.is_dir():
        candidates.extend(sorted(projects_dir.glob("*/pm-settings.json")))
    reads_dir = ledger_dir / "reads"
    if reads_dir.is_dir():
        candidates.extend(sorted(reads_dir.glob("*.json")))
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        data = _read_json_safe(path)
        if not data:
            continue
        val = data.get("autoMemoryDirectory")
        if isinstance(val, str) and _rewrite_prefix(val, old_str, new_str) is not None:
            updates.append((path, "autoMemoryDirectory"))
    board = ledger_dir / "BOARD.md"
    if board.is_file() and not board.is_symlink():
        try:
            text = board.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if f"`{old_source / 'tasks'}`" in text:
            updates.append((board, "BOARD.md"))
    return updates


def rewrite_generated_paths(ledger_dir: Path, old_source: Path, new_target: Path) -> list[str]:
    """Atomically update generated autoMemoryDirectory settings and BOARD.md header after moving the ledger."""
    old_str, new_str = str(old_source), str(new_target)
    updated: list[str] = []
    for path, kind in find_generated_path_updates(ledger_dir, old_source, new_target):
        if kind == "autoMemoryDirectory":
            data = _read_json_safe(path)
            if not data or not isinstance(data.get("autoMemoryDirectory"), str):
                continue
            replaced = _rewrite_prefix(data["autoMemoryDirectory"], old_str, new_str)
            if replaced is None:
                continue
            data["autoMemoryDirectory"] = replaced
            indent = 1 if path.parent.name == "reads" else 2
            payload = (json.dumps(data, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")
            write_atomic(path, payload, replace_fn=replace_task_file)
            updated.append(str(path))
        elif kind == "BOARD.md":
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            new_text = text.replace(f"`{old_source / 'tasks'}`", f"`{new_target / 'tasks'}`", 1)
            if new_text != text:
                write_atomic(path, new_text.encode("utf-8"), replace_fn=replace_task_file)
                updated.append(str(path))
    return updated


def sessions_to_restart(ledger_dir: Path) -> dict[str, list[dict[str, str]]]:
    """Registered PMs and open tasks in `ledger_dir` whose running sessions should be restarted after migration."""
    pms_dir = ledger_dir / "pms"
    pms: list[dict[str, str]] = []
    if pms_dir.is_dir():
        for p in sorted(pms_dir.glob("*.json")):
            rec = _read_json_safe(p)
            if rec:
                pms.append({
                    "name": rec.get("name") or p.stem,
                    "project": rec.get("project") or p.stem,
                    "pane": rec.get("pane") or "",
                    "repo": rec.get("repo") or "",
                })
    tasks_dir = ledger_dir / "tasks"
    active: list[dict[str, str]] = []
    if tasks_dir.is_dir():
        for p in sorted(tasks_dir.glob("*.json")):
            t = _read_json_safe(p)
            if t and t.get("status") in ACTIVE:
                active.append({
                    "id": t.get("id") or p.stem,
                    "title": t.get("title") or "",
                    "status": t.get("status") or "",
                    "pane": t.get("pane") or "",
                    "agent": t.get("agent") or "",
                })
    return {"pms": pms, "active_tasks": active}


class HomeMover:
    """Ledger home inspection, active-writer detection, backup, and status formatting over explicit `Context`."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def inspect(self, home_dir: str | Path | None = None) -> dict[str, Any]:
        """Read-only inspection of the effective ledger home, ~/.claude/pm, and ~/.dudu."""
        home = Path(home_dir) if home_dir is not None else Path.home()
        source = home / ".claude" / "pm"
        target = home / ".dudu"
        env_pm_home = self.ctx.env.get("PM_HOME") or ""

        if not os.path.lexists(source):
            source_kind, source_link = "absent", ""
        elif source.is_symlink():
            try:
                source_link = os.readlink(source)
            except OSError:
                source_link = ""
            if target.is_dir() and not target.is_symlink() and _samefile(source, target):
                source_kind = "symlink_to_target"
            else:
                source_kind = "symlink_other"
        elif source.is_dir():
            source_kind, source_link = "dir", ""
        else:
            source_kind, source_link = "file", ""

        target_ledger: list[str] = []
        target_service: list[str] = []
        if not os.path.lexists(target):
            target_kind, target_link = "absent", ""
        elif target.is_symlink():
            try:
                target_link = os.readlink(target)
            except OSError:
                target_link = ""
            target_kind = "symlink"
        elif target.is_dir():
            target_link = ""
            target_ledger = ledger_markers(target)
            target_service = legacy_service_markers(target)
            try:
                empty = not any(target.iterdir())
            except OSError:
                empty = False
            if target_ledger:
                target_kind = "ledger_dir"
            elif empty:
                target_kind = "empty_dir"
            elif target_service:
                target_kind = "legacy_service_dir"
            else:
                target_kind = "other_dir"
        else:
            target_kind, target_link = "file", ""

        if env_pm_home:
            effective = Path(env_pm_home)
        elif source.exists() and not (target.exists() and _samefile(source, target)):
            effective = source
        else:
            effective = target

        if source_kind == "symlink_to_target":
            status = "migrated"
        elif source_kind == "absent":
            status = "canonical" if target_kind in ("absent", "empty_dir", "ledger_dir") else "canonical_with_legacy_target"
        elif source_kind == "dir" and target_kind == "ledger_dir":
            status = "conflict"
        elif source_kind == "dir" and target_kind in ("absent", "empty_dir", "legacy_service_dir", "other_dir", "file"):
            status = "legacy"
        else:
            status = "unsupported"

        return {
            "home": str(effective),
            "pm_home_env": env_pm_home,
            "source": str(source),
            "source_kind": source_kind,
            "source_link": source_link,
            "source_ledger_markers": ledger_markers(source) if source_kind == "dir" else [],
            "target": str(target),
            "target_kind": target_kind,
            "target_link": target_link,
            "target_ledger_markers": target_ledger,
            "target_service_markers": target_service,
            "status": status,
        }

    def active_writers(self, source: Path, target: Path | None = None) -> list[dict[str, str]]:
        """Detect active locks, wait/reattach processes, or live PM/worker/helper sessions touching `source`."""
        blockers: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(kind: str, detail: str, path: Path | str = "") -> None:
            key = (kind, detail)
            if key not in seen:
                seen.add(key)
                blockers.append({"kind": kind, "detail": detail, "path": str(path) if path else ""})

        if source.is_dir():
            projects_dir = source / "projects"
            if projects_dir.is_dir():
                for proj in sorted(projects_dir.iterdir()):
                    if not proj.is_dir() or proj.is_symlink():
                        continue
                    slug = proj.name
                    if _is_flock_held(proj / "deliver.lock"):
                        add("deliver", f"deliver ({slug})", proj / "deliver.lock")
                    if _is_flock_held(proj / "seat.lock"):
                        add("seat", f"seat ({slug})", proj / "seat.lock")
                    if _is_flock_held(proj / "delivered.lock"):
                        add("delivered", f"delivered write ({slug})", proj / "delivered.lock")
                    if _is_flock_held(proj / "memory" / ".lock"):
                        add("memory", f"memory write ({slug})", proj / "memory" / ".lock")
            if _is_flock_held(source / "memory" / ".lock"):
                add("memory", "personal memory write", source / "memory" / ".lock")
            inbox_dir = source / "inbox"
            if inbox_dir.is_dir():
                for lp in sorted(inbox_dir.glob("*.watch.lock")):
                    if _is_flock_held(lp):
                        try:
                            pid = lp.read_text(encoding="utf-8", errors="replace").strip() or "?"
                        except OSError:
                            pid = "?"
                        pm_name = lp.name[:-len(".watch.lock")]
                        add("watch", f"watch ({pm_name}, pid {pid})", lp)
            locks_dir = source / "locks"
            if locks_dir.is_dir():
                for lp in sorted(locks_dir.glob("*.lock")):
                    if _is_flock_held(lp):
                        add("lock", f"ledger lock ({lp.stem})", lp)
            reattach_dir = source / "reattach"
            if reattach_dir.is_dir():
                for lp in sorted(reattach_dir.glob("*.lock")):
                    if lp.is_file() and not stale_lock(lp):
                        add("reattach", f"reattach ({lp.stem})", lp)
            waits_path = source / "waits"
            if waits_path.is_dir():
                for wp in sorted(waits_path.glob("*.json")):
                    info = _read_json_safe(wp) or {}
                    pid = info.get("pid")
                    if isinstance(pid, int) and _pid_alive(pid):
                        add("wait", f"wait ({info.get('task') or wp.stem}, pid {pid})", wp)

            pms_dir = source / "pms"
            pms = [_read_json_safe(p) for p in sorted(pms_dir.glob("*.json"))] if pms_dir.is_dir() else []
            pms = [r for r in pms if r]
            tasks_dir = source / "tasks"
            tasks = [_read_json_safe(p) for p in sorted(tasks_dir.glob("*.json"))] if tasks_dir.is_dir() else []
            active_tasks = [t for t in tasks if t and t.get("status") in ACTIVE]

            pm_panes = {r.get("pane"): r for r in pms if r.get("pane")}
            pm_projects = {r.get("project"): r for r in pms if r.get("project")}
            pm_names = {r.get("name"): r for r in pms if r.get("name")}
            task_panes = {t.get("pane"): t for t in active_tasks if t.get("pane")}
            task_ids = {t.get("id"): t for t in active_tasks if t.get("id")}
            helper_panes = {
                f"hc:{h['terminal']}": h
                for owner in (*pms, *active_tasks)
                for h in (owner.get("helpers") or [])
                if isinstance(h, dict) and h.get("status") == "running" and h.get("terminal")
            }

            if pms or active_tasks:
                hc_rows = self.ctx.hc.live_rows() if self.ctx.hc is not None else None
                if hc_rows:
                    for addr, row in sorted(hc_rows.items()):
                        pane = f"hc:{addr}"
                        labels = dict(row.labels) if hasattr(row, "labels") else dict(row.get("labels") or {})
                        if not labels:
                            detail = self.ctx.hc.get(addr)
                            if detail is not None:
                                labels = dict(detail.labels)
                        if labels.get("pm.retired"):
                            continue
                        if pane in pm_panes:
                            rec = pm_panes[pane]
                            add("pm_terminal", f"live PM terminal {rec.get('name') or rec.get('project')} ({pane})")
                        elif labels.get("pm") and labels.get("pm") in pm_projects:
                            rec = pm_projects[labels["pm"]]
                            add("pm_terminal", f"live PM terminal {rec.get('name') or labels['pm']} ({pane})")
                        elif pane in task_panes:
                            task = task_panes[pane]
                            add("worker_terminal", f"live worker terminal {task.get('id')} ({pane})")
                        elif labels.get("task") and labels.get("task") in task_ids:
                            add("worker_terminal", f"live worker terminal {labels['task']} ({pane})")
                        elif pane in helper_panes:
                            hname = helper_panes[pane].get("name") or labels.get("helper") or addr
                            add("helper_terminal", f"live helper terminal {hname} ({pane})")
                        elif labels.get("helper.of") and (labels["helper.of"] in pm_names or labels["helper.of"] in task_ids):
                            hname = labels.get("helper") or addr
                            add("helper_terminal", f"live helper terminal {hname} ({pane})")

                tui_needed = any(p and not str(p).startswith("hc:") for p in (*pm_panes, *task_panes))
                if tui_needed:
                    tui_agents = (self.ctx.tui.agents() or []) if self.ctx.tui is not None else []
                    tui_live = {x.get("pane_id") for x in tui_agents if x.get("pane_id")}
                    for pane, rec in sorted(pm_panes.items()):
                        if not str(pane).startswith("hc:") and pane in tui_live:
                            add("pm_terminal", f"live PM pane {rec.get('name') or rec.get('project')} ({pane})")
                    for pane, task in sorted(task_panes.items()):
                        if not str(pane).startswith("hc:") and pane in tui_live:
                            add("worker_terminal", f"live worker pane {task.get('id')} ({pane})")

        if target is not None and target.is_dir() and not target.is_symlink():
            svc_lock = target / "service.lock"
            if _is_flock_held(svc_lock):
                add("service", "legacy dudu service (service.lock)", svc_lock)

        return blockers

    def format_status(self, info: dict[str, Any]) -> list[str]:
        """Format human-readable status lines for `pm.py home`."""
        lines = [f"Ledger home: {info['home']}" + (" (from $PM_HOME)" if info["pm_home_env"] else "")]
        if info["source_kind"] == "symlink_to_target":
            lines.append(f"  Legacy path: {info['source']} -> {info['source_link']} (compatibility symlink)")
        elif info["source_kind"] == "symlink_other":
            lines.append(f"  Legacy path: {info['source']} -> {info['source_link']} (custom symlink)")
        elif info["source_kind"] == "dir":
            lines.append(f"  Legacy path: {info['source']} (directory)")
        elif info["source_kind"] == "absent":
            lines.append(f"  Legacy path: {info['source']} (absent)")
        else:
            lines.append(f"  Legacy path: {info['source']} ({info['source_kind']})")

        if info["target_kind"] == "ledger_dir":
            lines.append(f"  Default path: {info['target']} (ledger)")
        elif info["target_kind"] == "legacy_service_dir":
            markers = ", ".join(info["target_service_markers"])
            lines.append(f"  Default path: {info['target']} (legacy service files: {markers})")
        elif info["target_kind"] == "symlink":
            lines.append(f"  Default path: {info['target']} -> {info['target_link']} (symlink)")
        elif info["target_kind"] == "empty_dir":
            lines.append(f"  Default path: {info['target']} (empty directory)")
        elif info["target_kind"] == "absent":
            lines.append(f"  Default path: {info['target']} (absent)")
        else:
            lines.append(f"  Default path: {info['target']} ({info['target_kind']})")

        if info["status"] == "migrated":
            lines.append("Status: migrated to ~/.dudu (compatibility symlink in place).")
        elif info["status"] == "canonical":
            lines.append("Status: using ~/.dudu.")
        elif info["status"] == "canonical_with_legacy_target":
            lines.append("Status: no legacy ~/.claude/pm; ~/.dudu currently holds non-ledger files.")
        elif info["status"] == "legacy":
            script = self.ctx.procs.pm_script()
            lines.append(f"Status: legacy ledger at {info['source']}. Migrate with:")
            lines.append(f"  {script} home --migrate --dry-run")
            lines.append(f"  {script} home --migrate")
        elif info["status"] == "conflict":
            lines.append(f"Status: conflict — both {info['source']} and {info['target']} contain ledger data.")
        else:
            lines.append(f"Status: unsupported layout ({info['source_kind']} / {info['target_kind']}).")
        return lines

    def create_backfill_backup(self, backup_dir: str | Path | None = None) -> dict[str, Any]:
        """Create a verified tarball of the ledger home before `backfill-numbers`."""
        state = self.ctx.home.root
        target_dir = Path(backup_dir).expanduser().resolve() if backup_dir else _default_backfill_backup_dir(state)
        if _is_subpath(target_dir, state):
            raise ValueError(f"Backup directory {target_dir} must be outside {state}.")
        target_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(target_dir / ".backfill.lock", timeout=30.0, lock_fn=lock_file, unlock_fn=unlock_file):
            stamp = self.ctx.clock.datetime_now().strftime("%Y%m%d-%H%M%S")
            backup_path = _unique_path(target_dir / f"pm-{stamp}-before-backfill.tgz", suffix=".tgz")
            return create_verified_backup(state, backup_path)


# ── Legacy module-level wrappers (Stages 1-5 compatibility bridge) ─────────────────────────────────────────────

def inspect_ledger_home(home_dir: str | Path | None = None) -> dict[str, Any]:
    return HomeMover(Context.from_env()).inspect(home_dir=home_dir)


def active_ledger_writers(source: Path, target: Path | None = None) -> list[dict[str, str]]:
    return HomeMover(Context.from_env()).active_writers(source, target=target)


def format_home_status(info: dict[str, Any]) -> list[str]:
    return HomeMover(Context.from_env()).format_status(info)


def _create_backfill_backup(backup_dir: str | Path | None = None) -> dict[str, Any]:
    return HomeMover(Context.from_env()).create_backfill_backup(backup_dir=backup_dir)
