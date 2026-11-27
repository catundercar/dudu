"""Project, Library/Memory editing, and ledger-home migration commands (`project`, `home`). Layer 4."""
from __future__ import annotations

import contextlib
import datetime
import json
import os
from pathlib import Path
import shutil
import sys

from ..context import Context
from ..errors import IdentityError, NotFound, Refused
from ..events.deliver import Delivery
from ..events.supervisor import read_pm_turn_view
from ..homemove import (
    HomeMover,
    _format_bytes,
    _is_subpath,
    _move_ledger_dir,
    _unique_path,
    create_verified_backup,
    find_generated_path_updates,
    rewrite_generated_paths,
    sessions_to_restart,
)
from ..ledger.ledger import Ledger
from ..library import (
    WRITABLE_ROOTS,
    LibraryService,
    memory_target,
    memory_version,
    split_context_path,
)
from ..memory.layer import (
    MEMORY_TYPES,
    TOPICS,
    MemoryLayer,
    MemoryRefused,
    read_memory,
)
from ..osutil import WINDOWS, unfailing
from ..project.project import ProjectRegistry
from ..project.readmodel import NotFoundError, Projects
from ..project.turn_reducer import sanitize_journal_entries, summarize_turns
from ..project.turn_state import TurnTracker
from ..store import (
    DOCUMENT_ROOTS,
    SLUG_RE,
    StoreError,
    VersionConflict,
    file_lock,
    local_tz_offset,
    lock_file,
    unlock_file,
    version_of,
)
from ..views import project as views_project


def cmd_project_edit(a, slug, ctx=None):
    """The editing commands of `pm.py project`: JSON out; exit 4 with {"error": "conflict"} on a stale version."""
    ctx = Context.from_env() if ctx is None else ctx
    lib = LibraryService(ctx)
    repo = lib.slug_repo(slug)
    cmd = a.project_cmd
    if cmd == "library":
        return ctx.store.library(slug)
    if cmd == "memory":
        return lib.memory_page(repo)
    if cmd == "repo-docs":
        mutating = bool(a.include or a.exclude or a.on or a.off or a.reset)
        if not mutating:
            return ctx.store.repo_docs_settings(slug)
        if a.on and a.off:
            raise ValueError("cannot pass both --on and --off")
        if a.reset and (a.include or a.exclude or a.on or a.off):
            raise ValueError("--reset cannot be combined with --include, --exclude, --on, or --off")
        lib.project_write_check(ctx.caller.memory_writer(repo))
        if a.reset:
            ctx.store.set_library_state(slug, repo_docs=None)
        else:
            cur = dict(ctx.store.library_state(slug).get("repo_docs") or {})
            if a.on:
                cur["enabled"] = True
            elif a.off:
                cur["enabled"] = False
            if a.include is not None:
                cur["include"] = list(a.include)
            if a.exclude is not None:
                cur["exclude"] = list(a.exclude)
            ctx.store.set_library_state(slug, repo_docs=cur)
        return ctx.store.repo_docs_settings(slug)
    if cmd == "research-migrate":
        return lib.migrate_research(slug, tuple(a.topic or ()), apply=a.apply)
    if cmd == "history":
        root, path = a.root, a.path or ""
        head, slash, tail = path.partition("/")
        if slash and head in WRITABLE_ROOTS:
            root, path = head, tail
        if root == "docs":
            return {"root": root, "items": ctx.store.doc_history(slug, path or None)}
        rows = MemoryLayer(ctx, None if root == "personal" else repo).history(memory_target(path) if path else None)
        return {"root": root, "items": [{"root": root, "path": f"{r['name']}.md", **{k: v for k, v in r.items()
                                                                                    if k != "file"}} for r in rows]}
    lib.project_write_check(ctx.caller.memory_writer(repo))
    if cmd == "archive-decisions":
        state = ctx.store.set_library_state(slug, decisions={"hidden": not a.show, "at": ctx.clock.now()})
        return {"project": slug, "decisions": state["decisions"]}
    if cmd == "add":
        return ctx.store.add_doc(slug, a.source, folder=a.folder or "", name=a.name, replace=a.replace)
    if cmd == "retopic":
        m, _ = lib.retopic_memory(repo, a.personal, a.name, writer=ctx.caller.memory_writer(repo), topic=a.topic, kind=a.type)
        return lib.memory_row(m, "personal" if a.personal else "project")
    root, rel = split_context_path(a.path, a.root)
    if root not in WRITABLE_ROOTS:
        raise ValueError(f"{root} is read-only here: only {', '.join(WRITABLE_ROOTS)} are edited")
    if cmd == "save":
        if (a.text is None) == (a.from_file is None):
            raise ValueError("give the new text with --text or --from <file> (- for stdin)")
        text = a.text if a.text is not None else (sys.stdin.read() if a.from_file == "-" else
                                                  Path(a.from_file).read_text(encoding="utf-8"))
        if root == "docs":
            return ctx.store.save_doc(slug, rel, text.encode("utf-8"), if_version=a.if_version)
        m, created = lib.save_memory_file(
            repo, root == "personal", memory_target(rel), text,
            writer=ctx.caller.memory_writer(repo), if_version=a.if_version,
        )
        return {**lib.memory_row(m, "personal" if root == "personal" else "project"), "created": created}
    if cmd == "delete":
        if root == "docs":
            return ctx.store.delete_doc(slug, rel, if_version=a.if_version)
        layer = None if root == "personal" else repo
        m = read_memory(ctx.home.memory_dir(layer) / f"{memory_target(rel)}.md")
        if not m:
            raise FileNotFoundError(f"no memory called {memory_target(rel)}")
        if a.if_version is not None and a.if_version != memory_version(m):
            raise VersionConflict(f"{m['name']} changed since it was read", memory_version(m))
        MemoryLayer(ctx, layer).forget(m, writer=ctx.caller.memory_writer(repo), why=a.why or "")
        return {"root": root, "path": f"{m['name']}.md", "deleted": True}
    if cmd == "restore":
        if root == "docs":
            return ctx.store.restore_doc(slug, rel, a.version)
        m = MemoryLayer(ctx, None if root == "personal" else repo).restore(
            memory_target(rel), version=a.version, writer=ctx.caller.memory_writer(repo),
        )
        return {**lib.memory_row(m, "personal" if root == "personal" else "project"), "restored": True}
    raise ValueError(f"unknown project command: {cmd}")


def _print_home_status(info, mover, out):
    for line in mover.format_status(info):
        out.line(line)


def cmd_home(a, ctx=None):
    """Show ledger home status, or safely migrate a legacy ~/.claude/pm ledger to ~/.dudu."""
    ctx = Context.from_env() if ctx is None else ctx
    mover = HomeMover(ctx)
    if not a.migrate:
        if a.dry_run or a.backup_dir:
            sys.exit("--dry-run and --backup-dir require --migrate")
        info = mover.inspect()
        if a.json:
            ctx.out.line(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            _print_home_status(info, mover, ctx.out)
        return

    pm_home_val = ctx.env.get("PM_HOME")
    if pm_home_val:
        msg = (f"$PM_HOME is set ({pm_home_val}); unset PM_HOME to migrate the default ledger "
               "from ~/.claude/pm to ~/.dudu.")
        if a.json:
            ctx.out.line(json.dumps({"ok": False, "error": msg, "reason": "pm_home_set"}, ensure_ascii=False, indent=2))
        else:
            ctx.out.err_line(f"Refused: {msg}")
        sys.exit(2)

    user_home = ctx.env.get("HOME") or ctx.env.get("USERPROFILE")
    home = Path(user_home) if user_home else Path.home()
    info = mover.inspect(home)
    source, target = Path(info["source"]), Path(info["target"])

    if info["status"] in ("migrated", "canonical", "canonical_with_legacy_target"):
        already = {
            "migrated": f"Already migrated: ledger is at {target} (compatibility symlink {source} -> {info['source_link']}).",
            "canonical": f"Nothing to migrate: no legacy ledger at {source} (ledger home is {target}).",
            "canonical_with_legacy_target": f"Nothing to migrate: no legacy ledger at {source} "
                                            f"(note: {target} currently holds non-ledger files).",
        }[info["status"]]
        if a.json:
            ctx.out.line(json.dumps({"ok": True, "changed": False, "status": info["status"], "message": already,
                                     "home": info["home"]}, ensure_ascii=False, indent=2))
        else:
            ctx.out.line(already)
        return

    if info["status"] == "conflict":
        msg = (f"Both {source} ({', '.join(info['source_ledger_markers'])}) and "
               f"{target} ({', '.join(info['target_ledger_markers'])}) contain ledger data. "
               "Auto-merge is refused to prevent data loss; inspect both, move one aside, then re-run.")
        if a.json:
            ctx.out.line(json.dumps({"ok": False, "error": msg, "reason": "target_is_ledger", **info},
                                    ensure_ascii=False, indent=2))
        else:
            ctx.out.err_line(f"Refused: {msg}")
        sys.exit(1)

    if info["status"] != "legacy":
        detail = (f"{source} is a symlink to {info['source_link']}" if info["source_kind"] == "symlink_other"
                  else f"{target} is a symlink to {info['target_link']}" if info["target_kind"] == "symlink"
                  else f"unsupported layout ({source}: {info['source_kind']}, {target}: {info['target_kind']})")
        msg = f"Cannot migrate automatically: {detail}."
        if a.json:
            ctx.out.line(json.dumps({"ok": False, "error": msg, "reason": "unsupported", **info},
                                    ensure_ascii=False, indent=2))
        else:
            ctx.out.err_line(f"Refused: {msg}")
        sys.exit(1)

    backup_dir = Path(a.backup_dir).expanduser().resolve() if a.backup_dir else (home / ".claude" / "pm-backups")
    if _is_subpath(backup_dir, source) or (target.exists() and _is_subpath(backup_dir, target)):
        msg = f"Backup directory {backup_dir} must be outside {source} and {target}."
        if a.json:
            ctx.out.line(json.dumps({"ok": False, "error": msg, "reason": "invalid_backup_dir"}, ensure_ascii=False, indent=2))
        else:
            ctx.out.err_line(f"Refused: {msg}")
        sys.exit(2)

    stamp = ctx.clock.datetime_now().strftime("%Y%m%d-%H%M%S")
    day = stamp[:8]
    backup_path = _unique_path(backup_dir / f"pm-{stamp}-before-migrate.tgz", suffix=".tgz")
    relocate_path = None
    if info["target_kind"] == "legacy_service_dir":
        relocate_path = _unique_path(home / f".dudu-legacy-service-{day}")
    elif info["target_kind"] in ("other_dir", "file"):
        relocate_path = _unique_path(home / f".dudu-legacy-{day}")

    blockers = mover.active_writers(source, target if info["target_kind"] != "absent" else None)
    planned_updates = [str(p) for p, _ in find_generated_path_updates(source, source, target)]
    restart = sessions_to_restart(source)

    if a.dry_run:
        plan = {
            "ok": not blockers,
            "dry_run": True,
            "source": str(source),
            "target": str(target),
            "backup": str(backup_path),
            "target_kind": info["target_kind"],
            "relocate_target": str(relocate_path) if relocate_path else None,
            "remove_empty_target": info["target_kind"] == "empty_dir",
            "symlink": f"{source} -> {target}",
            "generated_path_updates": planned_updates,
            "blockers": blockers,
            "sessions_to_restart": restart,
        }
        if a.json:
            ctx.out.line(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            ctx.out.line(f"Dry run: migrate ledger {source} -> {target}")
            ctx.out.line(f"  1. Back up {source} to {backup_path} (verified gzip tarball)")
            if relocate_path is not None:
                ctx.out.line(f"  2. Move existing non-ledger {target} aside to {relocate_path} (nothing deleted)")
            elif info["target_kind"] == "empty_dir":
                ctx.out.line(f"  2. Remove empty directory {target}")
            else:
                ctx.out.line(f"  2. Target {target} is absent (ready)")
            ctx.out.line(f"  3. Move {source} -> {target}")
            ctx.out.line(f"  4. Create compatibility symlink {source} -> {target}")
            if planned_updates:
                ctx.out.line(f"  5. Update generated paths in {len(planned_updates)} file(s) (autoMemoryDirectory / BOARD.md)")
            if blockers:
                ctx.out.line("Blockers (migration would be refused until stopped):")
                for b in blockers:
                    ctx.out.line(f"  - {b['detail']}")
            else:
                ctx.out.line("Checks: no active ledger locks or live PM/worker/helper sessions detected.")
                ctx.out.line("Dry run complete; no files changed.")
        if blockers:
            sys.exit(2)
        return

    if blockers:
        if a.json:
            ctx.out.line(json.dumps({"ok": False, "reason": "active_writers", "blockers": blockers},
                                    ensure_ascii=False, indent=2))
        else:
            ctx.out.err_line("Refused: active ledger processes or sessions are running. Stop/close them first:")
            for b in blockers:
                ctx.out.err_line(f"  - {b['detail']}")
        sys.exit(2)

    backup_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(backup_dir / ".migrate.lock", timeout=10.0, lock_fn=lock_file, unlock_fn=unlock_file):
        info = mover.inspect(home)
        if info["status"] == "migrated":
            msg = f"Already migrated: ledger is at {target}."
            if a.json:
                ctx.out.line(json.dumps({"ok": True, "changed": False, "status": "migrated", "message": msg,
                                         "home": str(target)}, ensure_ascii=False, indent=2))
            else:
                ctx.out.line(msg)
            return
        if info["status"] != "legacy":
            sys.exit(f"Refused: ledger state changed before migration ({info['status']}).")
        blockers = mover.active_writers(source, target if info["target_kind"] != "absent" else None)
        if blockers:
            if a.json:
                ctx.out.line(json.dumps({"ok": False, "reason": "active_writers", "blockers": blockers},
                                        ensure_ascii=False, indent=2))
            else:
                ctx.out.err_line("Refused: active ledger processes or sessions started before migration:")
                for b in blockers:
                    ctx.out.err_line(f"  - {b['detail']}")
            sys.exit(2)

        backup_path = _unique_path(backup_dir / f"pm-{stamp}-before-migrate.tgz", suffix=".tgz")
        backup_info = create_verified_backup(source, backup_path)

        relocated = None
        removed_empty = False
        if info["target_kind"] == "empty_dir":
            target.rmdir()
            removed_empty = True
        elif info["target_kind"] in ("legacy_service_dir", "other_dir", "file"):
            prefix = f".dudu-legacy-service-{day}" if info["target_kind"] == "legacy_service_dir" else f".dudu-legacy-{day}"
            relocate_path = _unique_path(home / prefix)
            os.rename(target, relocate_path)
            relocated = relocate_path

        displaced = None
        symlink_created = False
        symlink_warning = ""
        try:
            displaced = _move_ledger_dir(source, target)
            try:
                os.symlink(str(target), str(source), target_is_directory=True)
                symlink_created = True
            except OSError as err:
                if WINDOWS:
                    symlink_warning = f"could not create compatibility symlink {source} -> {target}: {err}"
                else:
                    raise
        except BaseException:
            if not os.path.lexists(source) and os.path.lexists(target) and displaced is None:
                with contextlib.suppress(OSError):
                    os.rename(target, source)
            elif displaced is not None and os.path.lexists(displaced) and not os.path.lexists(source):
                with contextlib.suppress(OSError):
                    os.rename(displaced, source)
                with contextlib.suppress(OSError):
                    shutil.rmtree(target)
            if relocated is not None and not os.path.lexists(target):
                with contextlib.suppress(OSError):
                    os.rename(relocated, target)
            elif removed_empty and not os.path.lexists(target):
                with contextlib.suppress(OSError):
                    target.mkdir()
            raise

        if displaced is not None:
            with contextlib.suppress(OSError):
                shutil.rmtree(displaced)

        updated_files = rewrite_generated_paths(target, source, target)
        restart = sessions_to_restart(target)
        post = mover.inspect(home)

    result = {
        "ok": True,
        "changed": True,
        "source": str(source),
        "target": str(target),
        "home": post["home"],
        "backup": backup_info,
        "relocated_target": str(relocated) if relocated else None,
        "symlink_created": symlink_created,
        "symlink_warning": symlink_warning,
        "updated_files": updated_files,
        "sessions_to_restart": restart,
    }
    if a.json:
        ctx.out.line(json.dumps(result, ensure_ascii=False, indent=2))
        return

    ctx.out.line(f"Migrated ledger: {source} -> {target}")
    ctx.out.line(f"  Backup archive: {backup_info['path']} ({_format_bytes(backup_info['size'])}, {backup_info['entries']} entries)")
    if backup_info["skipped"]:
        ctx.out.line(f"  Skipped non-regular entries in backup: {', '.join(backup_info['skipped'])}")
    if relocated:
        ctx.out.line(f"  Moved previous {target} aside to: {relocated} (kept intact)")
    if symlink_created:
        ctx.out.line(f"  Compatibility symlink: {source} -> {target}")
    elif symlink_warning:
        ctx.out.line(f"  Warning: {symlink_warning}")
    if updated_files:
        ctx.out.line(f"  Updated generated paths in {len(updated_files)} file(s).")
    ctx.out.line(f"  Resolved ledger home: {post['home']}")
    ctx.out.line("Sessions to restart:")
    for rec in restart["pms"]:
        where = rec["pane"] or rec["repo"] or rec["project"]
        ctx.out.line(f"  - PM {rec['name']} ({rec['project']}, {where}) — restart or rotate to pick up {target}")
    for task in restart["active_tasks"]:
        where = f", {task['pane']}" if task["pane"] else ""
        ctx.out.line(f"  - Open task {task['id']} ({task['status']}{where})")
    ctx.out.line("  - Restart any running coding agent sessions (Claude Code, Codex, pi) so hooks and autoMemoryDirectory "
                 f"use {target}. Desktop mods switch automatically on their next refresh.")


def cmd_project(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    if a.project_cmd == "session":
        return views_project.cmd_project_session(a, ctx=ctx)
    projects = Projects(ctx.store)
    reg = ProjectRegistry(ctx)
    ledger = Ledger(ctx)
    try:
        if a.project_cmd == "events":
            slug = reg.resolve_project_slug(a.slug)
            out = projects.events(slug, before=a.before, after=a.after, limit=a.limit)
            out["server_now_ms"] = int(ctx.clock.time() * 1000)
            out["server_tz"] = local_tz_offset(ctx.clock.datetime_now())
            if a.before is None:
                pm_reg = ctx.store.registration(slug)
                if pm_reg is not None:
                    pane_val = str(pm_reg.get("pane") or "")
                    term_addr = str(pm_reg.get("terminal") or (pane_val[3:] if pane_val.startswith("hc:") else ""))
                    term_info = None
                    live_pm = None
                    if term_addr and (pm_reg.get("runtime") == "hc" or pane_val.startswith("hc:")):
                        raw_info = ctx.hc.get_raw(term_addr, errors=True)
                        if isinstance(raw_info, dict) and not raw_info.get("error") and raw_info.get("state") == "live":
                            term_info = raw_info
                            raw_s = raw_info.get("status")
                            st_str = str(raw_s.get("state") or "") if isinstance(raw_s, dict) else str(raw_s or "")
                            live_pm = {"agent_status": st_str, "name": pm_reg.get("name")}
                        elif isinstance(raw_info, dict) and (
                            raw_info.get("state") in ("exited", "finished", "removed")
                            or (isinstance(raw_info.get("error"), dict) and raw_info["error"].get("kind") == "not_found")
                        ):
                            live_pm = {"agent_status": "offline", "name": pm_reg.get("name")}
                    turn_view = read_pm_turn_view(
                        ctx,
                        slug,
                        pm_reg,
                        term_info=term_info,
                        live_pm=live_pm,
                        revive=True,
                    )
                    out["turn"] = turn_view["turn"]
                    out["turn2"] = turn_view["turn2"]
                    out["supervised"] = turn_view["supervised"]
        elif a.project_cmd == "send":
            slug = reg.resolve_project_slug(a.slug)
            pm_reg = ctx.store.registration(slug)
            if pm_reg is None:
                raise NotFoundError(f"no project {a.slug}")
            repo = str(pm_reg.get("repo") or "")
            if repo:
                unfailing(Delivery(ctx, repo).ensure_running)
            pos = list(a.words or ())
            expected_target = ""
            if a.from_file is not None:
                send_text = sys.stdin.read() if a.from_file == "-" else Path(a.from_file).read_text(encoding="utf-8")
                if pos:
                    expected_target = pos[0]
            elif a.text is not None:
                send_text = a.text
                if pos:
                    expected_target = pos[0]
            elif len(pos) >= 2:
                expected_target, send_text = pos[0], pos[1]
            elif len(pos) == 1:
                send_text = pos[0]
            else:
                raise ValueError("give the message text positionally or with --text / --from")
            out = TurnTracker(ctx, slug).send_user_message(
                msg_id=a.msg_id,
                text=send_text,
                question=a.question or "",
                expected_target=expected_target,
            )
        elif a.project_cmd == "interrupt":
            slug = reg.resolve_project_slug(a.slug)
            out = TurnTracker(ctx, slug).interrupt_pm()
        elif a.project_cmd == "log":
            out = projects.thread_log(ledger.resolve_id(a.id), before=a.before, limit=a.limit)
        elif a.project_cmd == "tasks":
            out = projects.tasks(
                reg.resolve_project_slug(a.slug),
                status=a.status,
                query=a.q or "",
                offset=a.offset,
                limit=a.limit,
            )
        elif a.project_cmd == "context":
            out = {"files": projects.context(reg.resolve_project_slug(a.slug))}
        elif a.project_cmd == "files":
            out = projects.repo_files(reg.resolve_project_slug(a.slug), limit=a.limit)
        elif a.project_cmd == "change":
            out = projects.change(
                reg.resolve_project_slug(a.slug),
                a.task,
                commit=a.commit,
                file=a.file,
                offset=a.offset,
                limit=a.limit,
                commits_limit=a.commits_limit,
            )
        elif a.project_cmd == "file":
            root, rel = split_context_path(a.path, a.root)
            slug = reg.resolve_project_slug(a.slug)
            text = projects.document(slug, root, rel)
            out = {"root": root, "path": rel, "text": text, "size": len(text.encode("utf-8"))}
            with contextlib.suppress(OSError, ValueError, StoreError):
                out["version"] = version_of(ctx.store.document_path(slug, root, rel)[1])
        else:
            slug = reg.resolve_project_slug(a.slug)
            if not SLUG_RE.match(slug) or not projects._project_known(slug):
                raise NotFoundError(f"no project {a.slug}")
            out = cmd_project_edit(a, slug, ctx=ctx)
    except VersionConflict as e:
        ctx.out.line(json.dumps({"error": "conflict", "message": str(e), "current": e.current}, ensure_ascii=False))
        sys.exit(4)
    except (StoreError, IdentityError):
        raise
    except (NotFound, Refused, NotFoundError, ValueError, MemoryRefused, FileNotFoundError) as e:
        sys.exit(str(e).strip("'\""))
    if a.project_cmd == "files":
        ctx.out.line(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    else:
        ctx.out.line(json.dumps(out, ensure_ascii=False))


def register_project_command(sub):
    pr = sub.add_parser("project", help="read project conversation, thread, session and context records as JSON")
    within = pr.add_subparsers(dest="project_cmd", required=True)
    pe = within.add_parser("events", help="a window of a project's conversation log as JSON")
    pe.add_argument("slug", help="project slug, PM name or folder")
    pe.add_argument("--before", type=int, help="byte offset the window ends at (a previous window's `from`)")
    pe.add_argument("--after", type=int, help="byte offset to read new events after (a previous answer's `offset`)")
    pe.add_argument("--limit", type=int, default=200, help="at most this many events (default 200)")
    pl = within.add_parser("log", help="a page of a thread's ledger log as JSON")
    pl.add_argument("id", help="task id")
    pl.add_argument("--before", type=int, help="entry index `n` the page ends before (a previous page's `earlier`)")
    pl.add_argument("--limit", type=int, default=50, help="at most this many entries (default 50)")
    pt = within.add_parser("tasks", help="paginated and searchable list of a project's tasks as JSON")
    pt.add_argument("slug", help="project slug, PM name or folder")
    pt.add_argument("--status", choices=["finished", "open", "all"], default="finished",
                    help="which tasks to list: finished (default), open, or all")
    pt.add_argument("--q", default="", help="filter by #number, task id, title or branch (case-insensitive)")
    pt.add_argument("--offset", type=int, default=0, help="0-based result offset (default 0)")
    pt.add_argument("--limit", type=int, default=30, help="max tasks per page (default 30, max 100)")
    views_project.register_project_session_view(within)
    pch = within.add_parser("change", help="branch commits, changed files and paginated single-file diff as JSON")
    pch.add_argument("slug", help="project slug, PM name or folder")
    pch.add_argument("task", help="task id")
    pch.add_argument("--commit", help="inspect one commit (files or single-file diff)")
    pch.add_argument("--file", help="inspect one changed file's diff (paginated)")
    pch.add_argument("--offset", type=int, default=0, help="0-based diff line offset (default 0)")
    pch.add_argument("--limit", type=int, default=400, help="max diff lines per page (default 400)")
    pch.add_argument("--commits-limit", type=int, default=200, help="max branch commits listed (default 200)")
    pc = within.add_parser("context", help="(the old Context panel) a project's decisions, docs, memories and research "
                                           "as JSON")
    pc.add_argument("slug", help="project slug, PM name or folder")
    pf = within.add_parser("file", help="one text document from a project's context as JSON")
    pf.add_argument("slug", help="project slug, PM name or folder")
    pf.add_argument("path", help="path as <root>/<path> (project/decisions.md, user/foo.md, research/topic/README.md) "
                                 "or relative to --root")
    pf.add_argument("--root", choices=list(DOCUMENT_ROOTS), help="document root: docs, repo_docs, research, "
                                                                  "instructions, memory, personal (Library and Memory "
                                                                  "pages), repo (repository file preview), or project, "
                                                                  "user (the old Context panel)")
    pfi = within.add_parser("files", help="a project's repository files (from git ls-files) as JSON")
    pfi.add_argument("slug", help="project slug, PM name or folder")
    pfi.add_argument("--limit", type=int, default=20000, help="at most this many files (default 20000)")
    pli = within.add_parser("library", help="a project's Library as JSON: docs (editable), repo_docs, research and "
                                            "instructions (read-only)")
    pli.add_argument("slug", help="project slug, PM name or folder")
    prd = within.add_parser("repo-docs", help="inspect or configure which repository docs appear in Library")
    prd.add_argument("slug", help="project slug, PM name or folder")
    prd.add_argument("--include", action="append", help="repository-relative dir or file to scan (replaces defaults; repeat for more)")
    prd.add_argument("--exclude", action="append", help="repository-relative path prefix to exclude (repeat for more)")
    prd.add_argument("--on", action="store_true", help="enable repository docs scanning for this project")
    prd.add_argument("--off", action="store_true", help="disable repository docs scanning for this project")
    prd.add_argument("--reset", action="store_true", help="clear custom repo_docs settings and restore defaults")
    pme = within.add_parser("memory", help="a project's Memory page as JSON: topics, types, both layers' memories "
                                           "and candidates")
    pme.add_argument("slug", help="project slug, PM name or folder")
    for verb, about in (("save", "create or replace a document (docs) or a memory (memory, personal)"),
                        ("delete", "delete a document or a memory (kept in .history: `restore` brings it back)"),
                        ("restore", "bring back a deleted or replaced document or memory from .history"),
                        ("history", "list what .history keeps for a root (or one path in it)")):
        pw = within.add_parser(verb, help=about)
        pw.add_argument("slug", help="project slug, PM name or folder")
        pw.add_argument("path", nargs="?" if verb == "history" else None,
                        help="<root>/<path> (docs/notes.md, memory/<name>.md, personal/<name>.md) or relative to --root")
        pw.add_argument("--root", choices=list(WRITABLE_ROOTS), default="docs" if verb == "history" else None)
        if verb == "save":
            pw.add_argument("--text", help="the new text (a memory: the whole file, or only its body)")
            pw.add_argument("--from", dest="from_file", help="a file with the new text (- for stdin)")
        if verb in ("save", "delete"):
            pw.add_argument("--if-version", help="the version it was read at (`new`: must not exist); exit 4 if it "
                                                 "changed")
        if verb == "delete":
            pw.add_argument("--why", help="why (kept with a forgotten memory)")
        if verb == "restore":
            pw.add_argument("--version", help="which kept version (default: the newest)")
    pad = within.add_parser("add", help="copy a file dropped into the Library into the project's docs")
    pad.add_argument("slug", help="project slug, PM name or folder")
    pad.add_argument("source", help="the file to copy (text, Markdown, PDF or an image, at most 20 MB)")
    pad.add_argument("--folder", help="a folder under docs to put it in")
    pad.add_argument("--name", help="the name to give it (default: the file's)")
    pad.add_argument("--replace", action="store_true", help="replace a document of that name (default: name-2.ext)")
    prt = within.add_parser("retopic", help="move a memory to another topic (and/or type)")
    prt.add_argument("slug", help="project slug, PM name or folder")
    prt.add_argument("name", help="the memory's name")
    prt.add_argument("--topic", choices=TOPICS)
    prt.add_argument("--type", choices=MEMORY_TYPES)
    prt.add_argument("--personal", action="store_true")
    pad2 = within.add_parser("archive-decisions", help="hide decisions.md from the Library's list once its decisions "
                                                       "are in memory (--show: list it again)")
    pad2.add_argument("slug", help="project slug, PM name or folder")
    pad2.add_argument("--show", action="store_true")
    prm = within.add_parser("research-migrate", help="copy evidence/<topic>/README.md reports to the project's own "
                                                     "docs/research in the ledger (dry run unless --apply)")
    prm.add_argument("slug", help="project slug, PM name or folder")
    prm.add_argument("--topic", action="append", help="only this topic (repeat for more)")
    prm.add_argument("--apply", action="store_true", help="copy them (default: print what would be done)")
    psend = within.add_parser("send", help="idempotently deliver a UI user message to the project's PM and log it")
    psend.add_argument("slug", help="project slug, PM name or folder")
    psend.add_argument("--msg-id", required=True, help="client-generated unique message id for idempotency")
    psend.add_argument("--question", default="", help="question key this message answers, if any")
    psend.add_argument("--text", help="message text")
    psend.add_argument("--from", dest="from_file", help="file containing message text (- for stdin)")
    psend.add_argument("words", nargs="*", help="[target_terminal] text")
    pint = within.add_parser("interrupt", help="interrupt the PM terminal's current foreground step without killing it")
    pint.add_argument("slug", help="project slug, PM name or folder")


def register_home_command(sub):
    hm = sub.add_parser("home", help="show the ledger home, or migrate a legacy ~/.claude/pm ledger to ~/.dudu")
    hm.add_argument("--migrate", action="store_true",
                    help="back up ~/.claude/pm, move it to ~/.dudu, and leave a compatibility symlink")
    hm.add_argument("--dry-run", action="store_true",
                    help="with --migrate: list planned steps and blockers without changing any files")
    hm.add_argument("--backup-dir", help="with --migrate: where to save the pre-migration backup archive "
                                         "(default: ~/.claude/pm-backups)")
    hm.add_argument("--json", action="store_true", help="print status or migration plan/result as JSON")


def _parse_since_ms(raw: str | None, now_ms: int) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.isdigit():
        val = int(text)
        return val * 1000 if val < 10_000_000_000 else val
    unit_mult = {"s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}
    if len(text) >= 2 and text[-1].lower() in unit_mult and text[:-1].replace(".", "", 1).isdigit():
        return max(0, now_ms - int(float(text[:-1]) * unit_mult[text[-1].lower()]))
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return int(dt.timestamp() * 1000)
    except ValueError as err:
        raise ValueError(f"invalid --since value: {raw!r}") from err


def cmd_turn_journal(a, ctx=None):
    """Export sanitized observation journal slices usable as replay test fixtures (`pm.py turn-journal export`)."""
    ctx = Context.from_env() if ctx is None else ctx
    reg = ProjectRegistry(ctx)
    try:
        if a.turn_journal_cmd != "export":
            raise ValueError(f"unknown turn-journal command: {a.turn_journal_cmd}")
        slug = reg.resolve_project_slug(a.slug)
        if not SLUG_RE.match(slug):
            raise NotFoundError(f"no project {a.slug}")
        pm_reg = ctx.store.registration(slug) or {}
        repo = str(pm_reg.get("repo") or "")
        now_ms = int(ctx.clock.time() * 1000)
        since_ms = _parse_since_ms(a.since, now_ms)
        tracker = TurnTracker(ctx, slug)
        raw_entries = tracker.read_journal_entries(since_ms=since_ms, limit=max(1, int(a.limit or 2000)))
        sanitized = sanitize_journal_entries(
            raw_entries,
            home_dir=str(Path.home()),
            repo=repo,
        )
        lines = [json.dumps(row, ensure_ascii=False) for row in sanitized]
        if a.out:
            out_path = Path(a.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
            ctx.out.line(json.dumps({"ok": True, "slug": slug, "count": len(lines), "out": str(out_path)}, ensure_ascii=False))
            return
        for line in lines:
            ctx.out.line(line)
    except (NotFound, Refused, NotFoundError, ValueError, FileNotFoundError) as e:
        sys.exit(str(e).strip("'\""))


def register_turn_journal_command(sub):
    tj = sub.add_parser("turn-journal", help="inspect and export sanitized PM turn observation journal slices")
    within = tj.add_subparsers(dest="turn_journal_cmd", required=True)
    ex = within.add_parser("export", help="export a redacted observation journal slice as JSONL for replay tests")
    ex.add_argument("slug", help="project slug, PM name or folder")
    ex.add_argument("--since", help="duration (30m, 2h, 1d), ISO timestamp, or epoch ms")
    ex.add_argument("--limit", type=int, default=2000, help="max entries to export (default 2000)")
    ex.add_argument("--out", help="optional output .jsonl file path (default: stdout)")


def _fmt_dur_s(ms: int) -> str:
    sec = max(0.0, float(ms) / 1000.0)
    if sec < 60.0:
        return f"{sec:.1f}s" if sec < 10.0 and sec != int(sec) else f"{round(sec)}s"
    mins = int(sec // 60)
    rem = round(sec % 60)
    if rem == 60:
        mins += 1
        rem = 0
    return f"{mins}m {rem}s" if rem else f"{mins}m"


def cmd_turns(a, ctx=None):
    """Show coordinator turn duration distribution and top time-consuming actions (`pm.py turns <slug>`)."""
    ctx = Context.from_env() if ctx is None else ctx
    reg = ProjectRegistry(ctx)
    try:
        slug = reg.resolve_project_slug(a.slug)
        if not SLUG_RE.match(slug):
            raise NotFoundError(f"no project {a.slug}")
        pm_reg = ctx.store.registration(slug) or {}
        repo = str(pm_reg.get("repo") or "")
        now_ms = int(ctx.clock.time() * 1000)
        since_raw = a.since if a.since is not None else "24h"
        since_ms = _parse_since_ms(since_raw, now_ms)
        tracker = TurnTracker(ctx, slug)
        raw_entries = tracker.read_journal_entries(since_ms=since_ms, limit=10_000)
        sanitized = sanitize_journal_entries(
            raw_entries,
            home_dir=str(Path.home()),
            repo=repo,
        )
        cfg = tracker.turn_config()
        report = summarize_turns(sanitized, cfg=cfg)
        report["slug"] = slug
        report["since"] = since_raw
        if a.json:
            ctx.out.line(json.dumps(report, ensure_ascii=False, indent=2))
            return
        tr = ctx.config.tr
        if report["total_turns"] == 0:
            ctx.out.line(tr(
                f"{slug} (since {since_raw}): no completed turns recorded.",
                f"{slug}（最近 {since_raw}）：暂无已完成的轮次记录。",
            ))
            return
        soft_s = round(report["budget"]["soft_ms"] / 1000)
        hard_s = round(report["budget"]["hard_ms"] / 1000)
        u = report["user"]
        all_s = report["all"]
        ctx.out.line(tr(
            f"Coordinator turns for {slug} (since {since_raw}; budget soft={soft_s}s / over={hard_s}s):",
            f"{slug} 协调者轮次耗时统计（最近 {since_raw}；软预算 {soft_s}s / 越界 {hard_s}s）：",
        ))
        ctx.out.line(tr(
            f"  All turns ({all_s['count']}): p50={_fmt_dur_s(all_s['p50_ms'])}  p90={_fmt_dur_s(all_s['p90_ms'])}  "
            f"max={_fmt_dur_s(all_s['max_ms'])}  over_soft={all_s['over_soft']}  over_hard={all_s['over_hard']}",
            f"  全部轮次（{all_s['count']} 轮）：p50={_fmt_dur_s(all_s['p50_ms'])}  p90={_fmt_dur_s(all_s['p90_ms'])}  "
            f"max={_fmt_dur_s(all_s['max_ms'])}  超软预算={all_s['over_soft']}  越界={all_s['over_hard']}",
        ))
        if u["count"] > 0:
            ctx.out.line(tr(
                f"  User turns ({u['count']}): p50={_fmt_dur_s(u['p50_ms'])}  p90={_fmt_dur_s(u['p90_ms'])}  "
                f"max={_fmt_dur_s(u['max_ms'])}  over_soft={u['over_soft']}  over_hard={u['over_hard']}",
                f"  用户轮次（{u['count']} 轮）：p50={_fmt_dur_s(u['p50_ms'])}  p90={_fmt_dur_s(u['p90_ms'])}  "
                f"max={_fmt_dur_s(u['max_ms'])}  超软预算={u['over_soft']}  越界={u['over_hard']}",
            ))
        if report["top_actions"]:
            ctx.out.line(tr("  Top time-consuming categories:", "  最耗时动作类别："))
            for act in report["top_actions"][:5]:
                pct = round(float(act["share"]) * 100)
                ctx.out.line(f"    - {act['category']}: {_fmt_dur_s(act['total_ms'])} ({pct}%)")
    except (NotFound, Refused, NotFoundError, ValueError, FileNotFoundError) as e:
        sys.exit(str(e).strip("'\""))


def register_turns_command(sub):
    t = sub.add_parser("turns", help="show coordinator turn duration distribution and top time-consuming actions")
    t.add_argument("slug", help="project slug, PM name or folder")
    t.add_argument("--since", default="24h", help="window duration (e.g. 24h, 7d, 30m), ISO timestamp, or epoch ms (default: 24h)")
    t.add_argument("--json", action="store_true", help="print turn metrics summary as JSON")
