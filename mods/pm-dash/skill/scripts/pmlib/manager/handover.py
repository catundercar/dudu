"""What a handover builds: the compact text after a compaction, the standard shortened handover, and the full one for
a new PM session, with the user's words nobody answered yet and the last exchanges of the outgoing session. Layer 3."""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from ..agents.sessions import transcript_rows
from ..context import Context
from ..home import project_slug
from ..ledger.deps import evaluate_depends_on, format_dep_summary
from ..ledger.family import format_children_summary, task_children_map
from ..ledger.ledger import Ledger
from ..ledger.plan import plan_progress
from ..ledger.task import ACTIVE, CLOSED
from ..memory.candidates import MemoryCandidates
from ..memory.decisions import QUOTED, Decisions
from ..memory.layer import MemoryLayer
from ..osutil import clip
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry, pm_name, project_display_name
from ..project.turn_state import TurnTracker
from ..store import project_folders, registration_slug
from ..workers.wait import waited_tasks_for


def conversation_tail(path: str | Path, turns: int = 6, width: int = 700) -> list[dict[str, str]]:
    """The last exchanges of a session: what the user typed and the PM's final text of that turn."""
    out: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for row in transcript_rows(path):
        content = (row.get("message") or {}).get("content")
        if (row.get("type") == "user" and not row.get("isMeta")
                and not row.get("isCompactSummary") and not row.get("isVisibleInTranscriptOnly")):
            text = content if isinstance(content, str) else "\n".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            text = text.strip()
            if text and not text.startswith("<"):  # tool results and system notices are not the user speaking
                current = {"user": text, "pm": ""}
                out.append(current)
        elif row.get("type") == "assistant" and current is not None and isinstance(content, list):
            texts = [b["text"] for b in content if b.get("type") == "text" and b.get("text", "").strip()]
            if texts:
                current["pm"] = "\n".join(texts)  # later rows overwrite: the final message wins
    return [{"user": clip(t["user"], width), "pm": clip(t["pm"], width)} for t in out[-turns:]]


# What a handover prints (`--full`: everything; `--compact`: post-compaction live disk sync).
HANDOVER_DECISIONS = 15  # the latest decisions; `pm.py decisions` prints them all, with the user's words
HANDOVER_COMPACT_DECISIONS = 5  # recent one-off / unremembered decisions included in `handover --compact`
HANDOVER_LOG = 2         # the latest ledger entries per open task
HANDOVER_WIDTH = 100     # characters per older ledger entry
HANDOVER_DECISION_WIDTH = 200  # characters per decision line in handover
HANDOVER_LATEST = 600    # characters of the newest ledger entry per open task
HANDOVER_USER = 400      # characters of each thing the user said in the last exchanges
HANDOVER_REPLY = 400     # characters of each PM reply there


def _merge_unanswered_with_mailbox(c: Context, repo: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    waiting = unanswered(events)
    seen_ids = {str(e.get("msg_id") or "") for e in waiting if e.get("msg_id")}
    seen_texts = {str(e.get("text") or "").strip() for e in waiting if e.get("text")}
    tracker = TurnTracker(c, repo)
    if tracker.files.pm_mailbox.is_dir():
        for it in tracker.pm_mailbox.unanswered_user_items():
            b = it.envelope.body if isinstance(it.envelope.body, dict) else {}
            txt = str(b.get("text") or "").strip()
            mid = str(b.get("msg_id") or "")
            if not txt or (mid and mid in seen_ids) or txt in seen_texts:
                continue
            waiting.append({"type": "user", "at": c.clock.now(), "msg_id": mid, "text": txt, "state": it.state})
            if mid:
                seen_ids.add(mid)
            seen_texts.add(txt)
    return waiting


def unanswered(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the user said after the PM's latest reply, oldest first: words a rotation came between and their answer.
    [] when the PM spoke last. A notice `rotate` posts (a `pm` event marked notice) answers nothing."""
    out: list[dict[str, Any]] = []
    for e in reversed(events):
        if e.get("type") == "pm" and not e.get("notice"):
            break
        if e.get("type") == "user":
            out.insert(0, e)
    return out


def _handover_dep_context(tasks: list[dict[str, Any]], *, ctx: Context | None = None) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Evaluate dependencies and child counts for a project's handover sections."""
    c = Context.from_env() if ctx is None else ctx
    every = Ledger(c).raw_tasks()
    by_id = {t["id"]: t for t in every if isinstance(t, dict) and t.get("id")}
    for t in tasks:
        if isinstance(t, dict) and t.get("id"):
            by_id.setdefault(t["id"], t)
    dep_by_id = {t["id"]: evaluate_depends_on(t, by_id) for t in tasks if isinstance(t, dict) and t.get("id")}
    children_map = task_children_map(tasks)
    return dep_by_id, children_map


def _handover_ready_lines(active: list[dict[str, Any]], dep_by_id: dict[str, Any], *, ctx: Context | None = None) -> list[str]:
    """Pinned top section for ready-to-dispatch `proposed` tasks (empty when none are ready)."""
    c = Context.from_env() if ctx is None else ctx
    tr = c.config.tr
    ready = [t for t in active if t["status"] == "proposed" and dep_by_id.get(t["id"], {}).get("ready")]
    if not ready:
        return []
    out = ["", tr(f"## Ready to dispatch ({len(ready)})", f"## 可以派了（{len(ready)}）")]
    for t in ready:
        info = dep_by_id[t["id"]]
        meta = [format_dep_summary(info, include_empty=True, tr_fn=tr)]
        if t.get("parent"):
            meta.append(f"parent={t['parent']}")
        if t.get("brief"):
            meta.append(f"brief={t['brief']}")
        out.append(f"- {t['id']}: {t['title']} ({'; '.join(meta)})")
        log = t.get("log") or []
        if log:
            e = log[-1]
            out.append("    " + clip(" ".join(f"{e.get('at', '')} {e.get('by', '')}: {e.get('text', '')}".split()),
                                     HANDOVER_WIDTH))
    return out


def _handover_task_where(
    t: dict[str, Any],
    dep_by_id: dict[str, Any],
    children_map: dict[str, list[dict[str, Any]]],
    *,
    ctx: Context | None = None,
) -> str:
    c = Context.from_env() if ctx is None else ctx
    tr = c.config.tr
    parts = [f"{k}={t[k]}" for k in ("pane", "branch") if t.get(k)]
    if t.get("folder_alias"):
        parts.append(f"folder={t['folder_alias']}")
    if t.get("parent"):
        parts.append(f"parent={t['parent']}")
    if isinstance(t.get("plan"), list) and t["plan"]:
        pdone, ptotal, pnext = plan_progress(t["plan"])
        parts.append(f"plan={pdone}/{ptotal}" + (f" · {clip(pnext, 30)}" if t.get("landed") and pnext else ""))
    if isinstance(t.get("land_approved"), dict):
        ex = t["land_approved"].get("executor") or "worker"
        parts.append(f"merge_approved={ex}")
    kids = children_map.get(t["id"])
    if kids:
        parts.append(format_children_summary(kids, dep_by_id, tr_fn=tr))
    info = dep_by_id.get(t["id"])
    if info and info["depends_on"]:
        if info["ready"]:
            parts.append(tr("ready", "可以派了") + f" ({format_dep_summary(info, tr_fn=tr)})")
        else:
            parts.append(format_dep_summary(info, tr_fn=tr))
    return ", ".join(parts)


def handover_compact_text(repo: str, *, ctx: Context | None = None) -> str:
    """Live disk snapshot injected after compaction (`SessionStart[compact]` and `handover --compact`):
    ready-to-dispatch proposed tasks pinned at top, open work with the latest report up to 600 chars,
    unretired merged tasks, recent one-off or unremembered decisions, unanswered user messages, and herdr TUI waits."""
    c = Context.from_env() if ctx is None else ctx
    tr = c.config.tr
    rec = ProjectRegistry(c).pm_record(repo) or {}
    slug = registration_slug(rec) or project_slug(repo)
    proj_ref = repo if (repo and project_slug(repo) == slug) else str(c.home.project(slug).root)
    name = project_display_name(rec, repo)
    ledger = Ledger(c)
    out = [f"[pm post-compact live disk sync] PM of {name} ({repo}). Trust these current ledger records on disk "
           "over any older status in the compaction summary:"]
    out += _workspace_folders_section(rec, ctx=c)
    tasks = [t.raw for t in ledger.project_tasks(proj_ref)]
    active = [t for t in tasks if t["status"] in ACTIVE]
    dep_by_id, children_map = _handover_dep_context(tasks, ctx=c)
    out += _handover_ready_lines(active, dep_by_id, ctx=c)
    out += ["", "## Open work (`pm.py show <id>` for more)"] + ([] if active else ["(none)"])
    for t in active:
        where = _handover_task_where(t, dep_by_id, children_map, ctx=c)
        out.append(f"- [{t['status']}] {ledger.task_ref(t)}: {t['title']}" + (f" ({where})" if where else ""))
        log = t.get("log") or []
        if log:
            e = log[-1]
            out.append("    " + clip(" ".join(f"{e.get('at', '')} {e.get('by', '')}: {e.get('text', '')}".split()),
                                     HANDOVER_LATEST))
    loose = [ledger.task_ref(t) for t in tasks if t["status"] in ("merged", "released") and not t.get("retired")]
    if loose:
        out.append(f"Merged, not retired yet (`pm.py retire <id>`): {', '.join(loose)}")
    decisions = Decisions(c, proj_ref).unremembered()
    if decisions:
        shown = decisions[-HANDOVER_COMPACT_DECISIONS:]
        out += ["", f"## Recent one-off / unremembered decisions ({len(shown)} of {len(decisions)})"]
        out += [clip(QUOTED.sub("", line), HANDOVER_DECISION_WIDTH) for line in shown]
    waiting = _merge_unanswered_with_mailbox(c, proj_ref, Conversation(c, proj_ref, slug=slug).events())
    if waiting:
        out += ["", "## Not answered yet: the user said this after the PM's latest reply (Unanswered user messages)",
                *[f"{e.get('at', '')} {tr('User', '用户')}: {clip(str(e.get('text') or ''), 2000)}" for e in waiting]]
    out += handover_waits(tasks, rec, ctx=c)
    return "\n".join(out)


def handover_talk(
    repo: str,
    rec: dict[str, Any],
    turns: int,
    width: int,
    reply_width: int | None = None,
    *,
    ctx: Context | None = None,
) -> list[str]:
    """The last exchanges with the user, then what the user said that no reply has answered yet. With
    reply_width, each one is a line of its own: what the user said clipped to width, the reply to reply_width."""
    c = Context.from_env() if ctx is None else ctx
    tr = c.config.tr
    conv = Conversation(c, repo)
    out: list[str] = []
    # The conversation log is the source; a project whose log is still empty falls back to the last transcript.
    tail = conv.tail(turns=turns, width=0) or conversation_tail(
        (rec.get("previous") or {}).get("transcript") or "", turns=turns, width=0)
    if reply_width:
        line = lambda text, w: clip(" ".join(text.split()), w)
        tail = [{"user": line(t["user"], width), "pm": line(t["pm"], reply_width)} for t in tail]
    else:
        tail = [{"user": clip(t["user"], width), "pm": clip(t["pm"], width)} for t in tail]
    if tail:
        out += ["", "## The last exchanges with the user (shortened; `pm.py conversation --last 40` shows more)"]
        for t in tail:
            out += [f"{tr('User', '用户')}: {t['user']}", f"PM: {t['pm'] or '(no final text)'}"] + ([] if reply_width else [""])
    waiting = _merge_unanswered_with_mailbox(c, repo, conv.events())
    if waiting:
        out += ["", "## Not answered yet: the user said this after the PM's latest reply (Unanswered user messages)",
                *[f"{e.get('at', '')} {tr('User', '用户')}: {clip(str(e.get('text') or ''), 2000)}" for e in waiting],
                "Answer it once you have taken over, as the previous PM would have."]
    return out


def handover_waits(tasks: list[dict[str, Any]], rec: dict[str, Any], *, ctx: Context | None = None) -> list[str]:
    if rec.get("runtime") == "hc":
        return []  # reports are delivered to whichever session is the PM (cmd_deliver)
    c = Context.from_env() if ctx is None else ctx
    waited = waited_tasks_for(c, tasks, rec)
    if not waited:
        return []
    return ["", f"## Waits to start again, each in the background (run_in_background); pm.py is `{c.procs.pm_command()}`",
            *[f"pm.py wait {t['id']} --timeout 3600" for t in waited]]


def _workspace_folders_section(rec: dict[str, Any], *, ctx: Context | None = None) -> list[str]:
    folders = project_folders(rec)
    if len(folders) < 2:
        return []
    c = Context.from_env() if ctx is None else ctx
    lines = ["", f"## Workspace folders ({len(folders)})"]
    for f in folders:
        tag = "git" if f.get("git") else ("non-git" if "git" in f else "folder")
        lines.append(f"- {f['alias']}: {f['path']} ({tag})")
    git_count = sum(1 for f in folders if f.get("git"))
    if git_count >= 2:
        lines.append(c.config.tr(
            "Multiple Git repositories are linked; pass `--folder <alias>` explicitly when running `pm.py dispatch`.",
            "关联了多个 Git 仓库；运行 `pm.py dispatch` 时请显式传 `--folder <alias>`。",
        ))
    return lines


def handover_full_text(repo: str, turns: int = 6, *, ctx: Context | None = None) -> str:
    """The whole record, as `handover` printed it before it was shortened: every decision with the user's words,
    three ledger entries per task, the tasks closed in the last 48 h, longer exchanges."""
    c = Context.from_env() if ctx is None else ctx
    tr = c.config.tr
    rec = ProjectRegistry(c).pm_record(repo) or {}
    slug = registration_slug(rec) or project_slug(repo)
    proj_ref = repo if (repo and project_slug(repo) == slug) else str(c.home.project(slug).root)
    d = c.home.project(slug).ensure()
    name = Path(repo).name
    display_name = project_display_name(rec, repo)
    ledger = Ledger(c)
    folders = project_folders(rec)
    where_line = f"Repository: {repo}." if len(folders) <= 1 else f"Workspace folders: {len(folders)} linked (see below)."
    out = [f"# Handover: PM of {display_name}", "",
           f"You are {pm_name(repo)}. {where_line} This text is the project's record; trust it over anything "
           "you think you remember, and do not read the previous session's transcript.",
           "Then read `references/pm-playbook.md` of the pm skill."]
    out += _workspace_folders_section(rec, ctx=c)
    profile = Path(repo) / ".claude" / "coordination.md"
    if profile.exists():
        out.append(f"Project profile (read it): {profile}")
    tasks = [t.raw for t in ledger.project_tasks(proj_ref)]
    active = [t for t in tasks if t["status"] in ACTIVE or (t["status"] in ("merged", "released") and not t.get("retired"))]
    dep_by_id, children_map = _handover_dep_context(tasks, ctx=c)
    out += _handover_ready_lines(active, dep_by_id, ctx=c)
    for title, path in (("Decisions the user has made", d / "decisions.md"),
                        ("Notes from the previous PM", d / "handover.md")):
        if path.exists() and path.read_text().strip():
            out += ["", f"## {title}", path.read_text().strip()]
    by_id = {x["id"]: x for x in tasks}
    out += ["", "## Open work"] + ([] if active else ["(none)"])
    for t in active:
        where_parts = [f"{k}={t[k]}" for k in ("pane", "agent", "branch", "worktree", "brief", "parent") if t.get(k)]
        if t.get("folder_alias"):
            where_parts.append(f"folder={t['folder_alias']}")
        kids = children_map.get(t["id"])
        if kids:
            where_parts.append(format_children_summary(kids, dep_by_id, tr_fn=tr))
        info = dep_by_id.get(t["id"])
        if info and info["depends_on"]:
            if info["ready"]:
                where_parts.append(tr("ready", "可以派了") + f" ({format_dep_summary(info, tr_fn=tr)})")
            else:
                where_parts.append(format_dep_summary(info, tr_fn=tr))
        where = " ".join(where_parts)
        out.append(f"- [{t['status']}] {ledger.task_ref(t, by_id)}: {t['title']} (owner {t.get('owner')}; {where})")
        out += [f"    {e['at']} {e['by']}: {e['text'][:400]}" for e in (t.get("log") or [])[-3:]]
    day_ago = (c.clock.datetime_now() - datetime.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")
    closed = [t for t in tasks if t not in active and t.get("updated", "") >= day_ago]
    if closed:
        out += ["", "## Closed in the last 48 h"] + [f"- [{t['status']}] {ledger.task_ref(t, by_id)}: {t['title']}" for t in closed]
    out += handover_talk(proj_ref, rec, turns, 700, ctx=c)
    out += handover_waits(tasks, rec, ctx=c)
    return "\n".join(out)


def handover_text(
    repo: str,
    turns: int = 6,
    *,
    full: bool = False,
    compact: bool = False,
    ctx: Context | None = None,
) -> str:
    """Build the handover text for `repo` (`--compact`, `--full`, or standard shortened form)."""
    c = Context.from_env() if ctx is None else ctx
    if compact:
        return handover_compact_text(repo, ctx=c)
    if full:
        return handover_full_text(repo, turns=turns, ctx=c)
    tr = c.config.tr
    rec = ProjectRegistry(c).pm_record(repo) or {}
    slug = registration_slug(rec) or project_slug(repo)
    proj_ref = repo if (repo and project_slug(repo) == slug) else str(c.home.project(slug).root)
    d = c.home.project(slug).ensure()
    name = Path(repo).name
    display_name = project_display_name(rec, repo)
    ledger = Ledger(c)
    folders = project_folders(rec)
    where_line = f"Repository: {repo}." if len(folders) <= 1 else f"Workspace folders: {len(folders)} linked (see below)."
    out = [f"# Handover: PM of {display_name}", "",
           f"You are {pm_name(repo)}. {where_line} This is the project's record; trust it over anything you "
           "think you remember, and do not read the previous session's transcript. "
           "The playbook is `references/pm-playbook.md` of the pm skill."]
    out += _workspace_folders_section(rec, ctx=c)
    profile = Path(repo) / ".claude" / "coordination.md"
    if profile.exists():
        out.append(f"Project profile (read it): {profile}")
    tasks = [t.raw for t in ledger.project_tasks(proj_ref)]
    active = [t for t in tasks if t["status"] in ACTIVE]
    dep_by_id, children_map = _handover_dep_context(tasks, ctx=c)
    out += _handover_ready_lines(active, dep_by_id, ctx=c)
    mem_layer = MemoryLayer(c, proj_ref)
    dec_svc = Decisions(c, proj_ref)
    remembered = mem_layer.memory_block()
    has_memories = bool(mem_layer.memories())
    decisions = dec_svc.unremembered() if has_memories else dec_svc.lines()
    if remembered:
        out += ["", remembered]
        waiting = MemoryCandidates(c, proj_ref).list()
        if waiting:
            out.append(tr(f"{len(waiting)} candidate(s) saved by workers wait to be adopted or dropped: "
                          "`pm.py memory --candidates`.",
                          f"有 {len(waiting)} 条 worker 存下的候选等你收编或丢弃：`pm.py memory --candidates`。"))
    if decisions:
        shown = decisions[-HANDOVER_DECISIONS:]
        if has_memories:
            out += ["", f"## Recent one-off / unremembered decisions ({len(shown)} of {len(decisions)}; "
                        "`pm.py decisions` prints all)"]
            out += [clip(QUOTED.sub("", line), HANDOVER_DECISION_WIDTH) for line in shown]
        else:
            out += ["", f"## Decisions the user has made (the latest {len(shown)} of {len(decisions)}; "
                        "`pm.py decisions` prints all of them with the user's words)"]
            out += [clip(QUOTED.sub("", line), HANDOVER_WIDTH) for line in shown]
    notes = d / "handover.md"
    if notes.exists() and notes.read_text().strip():  # whole: what is in flight is not cut short
        out += ["", "## Notes from the previous PM", notes.read_text().strip()]
    by_id = {x["id"]: x for x in tasks}
    out += ["", "## Open work (`pm.py show <id>` for more)"] + ([] if active else ["(none)"])
    for t in active:
        where = _handover_task_where(t, dep_by_id, children_map, ctx=c)
        out.append(f"- [{t['status']}] {ledger.task_ref(t, by_id)}: {t['title']}" + (f" ({where})" if where else ""))
        entries = (t.get("log") or [])[-HANDOVER_LOG:]
        for idx, e in enumerate(entries):
            limit = HANDOVER_LATEST if idx == len(entries) - 1 else HANDOVER_WIDTH
            out.append("    " + clip(" ".join(f"{e.get('at', '')} {e.get('by', '')}: {e.get('text', '')}".split()),
                                     limit))
    loose = [ledger.task_ref(t, by_id) for t in tasks if t["status"] in ("merged", "released") and not t.get("retired")]
    if loose:
        out.append(f"Merged, not retired yet (`pm.py retire <id>`): {', '.join(loose)}")
    day_ago = (c.clock.datetime_now() - datetime.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")
    closed = [t for t in tasks if t["status"] in CLOSED and t["id"] not in loose and t.get("updated", "") >= day_ago]
    if closed:
        out.append(f"Closed in the last 48 h: {len(closed)} (`pm.py status --all` lists them)")
    out += handover_talk(proj_ref, rec, turns, HANDOVER_USER, HANDOVER_REPLY, ctx=c)
    out += handover_waits(tasks, rec, ctx=c)
    return "\n".join(out)


def handover_full(a: Any, repo: str, *, ctx: Context | None = None) -> str:
    """Legacy wrapper returning the full handover text (callers in Layer 4 write it to `ctx.out`)."""
    return handover_full_text(repo, turns=a.turns, ctx=ctx)
