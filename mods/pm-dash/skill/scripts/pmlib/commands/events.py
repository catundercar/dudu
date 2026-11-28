"""Event, notification, inbox watch and deliverer commands (`notify`, `watch`, `deliver`, `event`). Layer 4."""
from __future__ import annotations

import contextlib
from pathlib import Path
import sys

from ..caller import tui_registration
from ..context import Context
from ..errors import Refused
from ..events.deliver import Delivery
from ..events.deliverer import Deliverer
from ..events.inbox import (
    WATCH_START,
    InboxWatcher,
    adopted,
    output_nowhere,
)
from ..events.notify import Notifier
from ..events.supervisor import deliver_under_typist_lock
from ..messaging.address import LogicalAddress, parse_legacy_endpoint
from ..messaging.envelope import P4_BATCH, Envelope, new_env_id
from ..messaging.principal import Principal
from ..project.conversation import Conversation
from ..project.project import ProjectRegistry
from ..store import lock_file, registration_slug, unlock_file


def cmd_notify(a, ctx=None):
    """Tell the PM something. A desktop-app PM: an event in its project's log, which `deliver` brings it. A herdr
    TUI PM: append the line to its inbox, then type it into its input only when no `pm.py watch` runs for it: a
    watcher wakes the PM without typing where the user may be writing."""
    ctx = Context.from_env() if ctx is None else ctx
    projects = ProjectRegistry(ctx)
    inbox = InboxWatcher(ctx)
    pm, rec, _ = Notifier(ctx).target(a.repo)
    name = (pm or {}).get("name") or rec.get("name")
    if not name and a.repo:
        sys.exit(f"no PM for {Path(a.repo).resolve()} (its project, or a folder above it up to {Path.home()}); "
                 f"nothing was delivered, and not to another PM either. A project without a PM needs no notify: "
                 f"the ledger entry stands.")
    if not name:
        sys.exit(f"no PM found for {Path('.').resolve()} (not its project, the task this terminal works "
                 f"on, or a folder above it up to {Path.home()}); nothing was delivered. A PM's inbox is "
                 f"{ctx.home.inbox / '<pm name>.log'}: if the project has a PM, run notify with --repo <the project's "
                 f"folder>; a project without a PM needs no notify, the ledger entry stands.")
    if pm and pm["pane_id"] == ctx.pane:
        ctx.out.line("this session is the PM")
        return
    session = ctx.caller.herdr_session() if ctx.caller.in_tui() else ""
    me = f"{session}/{ctx.pane}" if session else (ctx.pane or "a session")
    told = projects.app_pm(registration_slug(rec) or rec.get("repo"))
    if told:
        pslug = registration_slug(told) or registration_slug(rec)
        # A desktop-app PM: the message is an event in its project's log, delivered once the PM is idle.
        Conversation(ctx, told.get("repo") or "", slug=pslug or None).record(
            "agent", by=me, text=a.text, source="session", wake=True
        )
        Delivery(ctx, told.get("repo") or "", slug=pslug or None).ensure_running()
        ctx.out.line(f"recorded for {name}; it is told once it is idle")
        return
    inbox.append_inbox(name, me, a.text)
    ctx.out.line(f"appended to {ctx.home.inbox_log(name)}")
    if inbox.watcher_pid(name):
        ctx.out.line(f"{name} has a watcher; not typing into its pane")
        return
    text = f"[from {me}] {a.text}"
    now_ms = int(float(ctx.clock.time()) * 1000)
    proj_slug = rec.get("name", "")[3:] if isinstance(rec.get("name"), str) and rec["name"].startswith("pm-") else "project"
    env = Envelope(
        env_id=new_env_id(now_ms),
        idempotency_key="",
        schema_version=1,
        created_ms=now_ms,
        kind="event.notify",
        sender=Principal.supervisor(proj_slug),
        recipient=LogicalAddress.pm(proj_slug),
        project=proj_slug,
        cause={"kind": "notify", "by": me},
        priority=P4_BATCH,
        body={"text": text},
    )
    repo_hint = str(rec.get("repo") or (pm or {}).get("repo") or "")
    out = None
    if pm:
        target = pm["pane_id"]
        ep = parse_legacy_endpoint(target, runtime_hint="hc" if target.startswith("hc:") else "tui")
        if ep is not None:
            out = deliver_under_typist_lock(ctx, ep, env, repo=repo_hint, if_idle=False)
            result = bool(out is not None and out.status == "typed")
        else:
            result = False
    elif rec.get("session") and rec.get("pane") and tui_registration(rec):
        # The PM runs in another herdr session than this one: its registration says which.
        target = f"{rec['session']}/{rec['pane']}"
        ep = parse_legacy_endpoint(rec["pane"], str(rec["session"]), runtime_hint="tui")
        if ep is not None:
            out = deliver_under_typist_lock(ctx, ep, env, repo=repo_hint, if_idle=False)
            result = bool(out is not None and out.status == "typed")
        else:
            result = False
    else:
        ctx.out.line(f"{name} is not running here; the inbox line still records it")
        return
    if result:
        ctx.out.line(f"notified PM at {target}")
    elif out is None and repo_hint and ep is not None:
        ctx.out.line(f"queued notify for PM at {target}")
    elif out is not None and out.detail == "typist_busy":
        ctx.out.line(f"notify failed: another sender kept typing into {target}; the inbox line still records it")
    else:
        ctx.out.line("notify failed; the inbox line still records it")


def cmd_watch(a, ctx=None):
    ctx = Context.from_env() if ctx is None else ctx
    inbox = InboxWatcher(ctx)
    ctx.caller.check_role("coordinate", a.repo)
    rec = ctx.caller.current_pm_record(a.pm, a.repo)
    if not rec:
        sys.exit("no PM registration found; pass --pm <name> or run it from the PM pane")
    rec = {**rec, "workspace": a.workspace or rec.get("workspace")}
    name = rec["name"]
    # A watcher whose output reaches no one would hold the lock and take the inbox's lines with it.
    if output_nowhere():
        sys.exit(f"watch: its output goes to /dev/null, so nothing it prints would wake you; {WATCH_START}.")
    if adopted():
        sys.exit(f"watch: what started it has already gone (a `&` from a shell that exited, nohup, disown), "
                 f"so nothing it prints would wake you; {WATCH_START}.")
    lock = inbox.watch_lock(name)
    if not lock:
        sys.exit(inbox.watcher_report(name, inbox.watcher_pid(name)))
    # Release even when called in-process, interrupted, or a read fails.
    with contextlib.closing(lock):
        try:
            res = inbox.watch(rec, timeout=a.timeout, interval=a.interval)
        except Refused as exc:
            sys.exit(str(exc))
        try:
            if res.kind == "inbox":
                ctx.out.write(res.text)
            else:
                ctx.out.line(res.text)
            out_fn = getattr(ctx.out, "_out", None)
            if callable(out_fn):
                out_fn().flush()
        except BrokenPipeError:
            sys.exit(1)
        res.commit()


def cmd_deliver(a, ctx=None):
    """The project's deliverer: send its undelivered events to its PM, one batch per turn, and watch its workers,
    for as long as the PM runs (`Deliverer.run`). One per project; a second one leaves at once."""
    ctx = Context.from_env() if ctx is None else ctx
    projects = ProjectRegistry(ctx)
    slug = projects.resolve_project_slug(a.project)
    rec = ctx.store.registration(slug) if slug else None
    repo = str((rec or {}).get("repo") or "") or (projects.registered_repo(a.project) or "")
    if not rec and not repo:
        sys.exit(f"no project {a.project}")
    deliverer = Deliverer(ctx, repo, slug=slug or None)
    if a.dry_run:
        start, end, items = deliverer.pending_batch(a.since)
        ctx.out.line(deliverer.batch_text(start, end, items) if items else f"nothing to deliver ({start}-{end})")
        return
    lock = open(deliverer._project_files().ensure() / "deliver.lock", "a+")
    try:
        lock_file(lock)
    except OSError:
        lock.close()
        return
    try:
        replaced = deliverer.run()
    finally:
        unlock_file(lock)
        lock.close()
    if replaced:
        deliverer.ensure_running()  # an install replaced this script: the new one takes over


def cmd_event(a, ctx=None):
    """`pm.py event`: the way in for anything outside the ledger that should wake the PM (a schedule, CI, a
    webhook). With --key, an event whose key is the same as the latest one from that source is not recorded."""
    ctx = Context.from_env() if ctx is None else ctx
    repo = ctx.git.project_root(a.repo)
    if not repo:
        sys.exit(f"{a.repo} is not a directory")
    pslug = ctx.store.folder_project_slug(repo)
    source = f"external:{a.source}"
    conv = Conversation(ctx, repo, slug=pslug or None)
    if a.key:
        last = next((e for e in reversed(conv.events()) if e.get("type") == "event" and e.get("source") == source), {})
        if last.get("key") == a.key:
            ctx.out.line(f"same key as the latest event from {a.source}; not recorded")
            return
    wake = bool(ProjectRegistry(ctx).app_pm(pslug or repo))
    conv.record("event", by=ctx.pane or a.source, text=a.text, source=source,
                **({"key": a.key} if a.key else {}), **({"wake": True} if wake else {}))
    Delivery(ctx, repo, slug=pslug or None).ensure_running()
    ctx.out.line("recorded; the PM will be told" if wake else "recorded; this project has no desktop-app PM to tell")


def register_event_commands(sub):
    dl = sub.add_parser("deliver", help="(started by whoever writes an event) send the project's undelivered "
                                        "events to its desktop-app PM once it is idle")
    dl.add_argument("project", help="the project's folder, or its name")
    dl.add_argument("--dry-run", action="store_true", help="print the batch that would be sent; send nothing")
    dl.add_argument("--since", type=int, help="with --dry-run: from this byte of the log, not the delivered mark")
    ev = sub.add_parser("event", help="record something from outside the ledger that the PM should hear about")
    ev.add_argument("text")
    ev.add_argument("--source", required=True, help="who says so: a short name such as ci or schedule")
    ev.add_argument("--key", help="an event with the same key as the latest one from this source is not recorded")
    ev.add_argument("--repo", default=".")
    nt = sub.add_parser("notify", help="tell the PM: an event for a desktop-app PM, an inbox line for a herdr TUI one")
    nt.add_argument("text")
    nt.add_argument("--repo", help="the project's folder (default: the project of this terminal's task, else of "
                                   "the current folder)")
    wa = sub.add_parser("watch", help="wait for a new inbox line or an agent state change, print it and exit")
    wa.add_argument("--pm", help="PM or project name (default: the PM registered for this pane, else for --repo)")
    wa.add_argument("--repo", default=".")
    wa.add_argument("--workspace", help="the PM's main workspace (default: from its registration)")
    wa.add_argument("--timeout", type=int, default=4 * 3600, help="seconds before printing 'watch timeout'")
    wa.add_argument("--interval", type=int, default=10,
                    help="legacy TUI state-check fallback seconds; desktop uses file/hc events (60s reconciliation)")
