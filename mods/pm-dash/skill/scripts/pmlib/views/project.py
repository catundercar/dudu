"""Project session transcript view (`pm.py project session`). Layer 4; the sibling `pm_project.py` stays beside pm.py."""
import json
import re
import sys

from ..agents.sessions import pm_sessions, sessions_reader
from ..commands.emit import exit_with
from ..context import Context
from ..errors import IdentityError, PmError, StoreError
from ..ledger.ledger import Ledger
from ..ledger.task import parse_task_num_ref
from ..workers.sessions import dispatched_with, find_session_for, task_workdirs_for, valid_recorded_session


def cmd_project_session(a, ctx=None):
    """Print one window of a task agent's conversation transcript as JSON (SessionAnswer shape)."""
    ctx = Context.from_env() if ctx is None else ctx
    if pm_sessions is None:
        sys.exit("pm_sessions.py is missing beside pm.py; reinstall the pm skill")
    ledger = Ledger(ctx)
    try:
        if parse_task_num_ref(a.id) is not None:
            a.id = ledger.resolve_id(a.id)
        if not a.id or not re.fullmatch(r"[^/\\\s.][^/\\\s]*", a.id) or ".." in a.id:
            sys.exit(f"not a task id: {a.id}")
        task = ledger.load(a.id).raw
    except (StoreError, IdentityError):
        raise
    except PmError as exc:
        exit_with(ctx, exc)
    reader = sessions_reader(
        home=ctx.home,
        claude_projects=ctx.agents.claude_projects,
        agy_dir=ctx.agents.agy_dir,
    )
    supported = reader.supported_kinds
    hints = task_workdirs_for(ctx, task)
    # Check dispatched_with first: a stale recorded session of another kind never overrides the current worker.
    dispatched_kind = dispatched_with(task)[0]
    if dispatched_kind and dispatched_kind not in supported:
        sys.exit(f"session kind {dispatched_kind!r} is not supported")
    kept = valid_recorded_session(task)
    if kept is not None:
        # Recorded session: never fall back to scanning other transcripts when its file is missing.
        kind = kept["kind"]
        if kind not in supported:
            sys.exit(f"session kind {kind!r} is not supported")
        sid = kept["id"]
        path = reader.transcript({"kind": kind, "id": sid, "hints": hints})
        if path is None:
            sys.exit(f"transcript not found for task {a.id} (session {sid})")
        session = {"kind": kind, "id": sid, "path": str(path), "hints": hints}
    else:
        # No recorded session for the current worker: scan via find_session, requiring unambiguous match.
        found = find_session_for(ctx, task)
        if found is None:
            sys.exit(f"no session found for task {a.id}")
        kind = found.get("kind") or ""
        if kind not in supported:
            sys.exit(f"session kind {kind!r} is not supported")
        if found.get("score", 0) < 2:
            sys.exit(f"no unambiguous {kind} session found for task {a.id}")
        session = {"kind": kind, "id": found["id"], "path": found["path"], "hints": hints}
    try:
        turns = reader.turns(session, before=a.before, limit=a.limit, after=a.after)
    except pm_sessions.SessionError as exc:
        sys.exit(str(exc))
    ctx.out.line(json.dumps(turns.to_dict(), ensure_ascii=False))


def register_project_session_view(within):
    ps = within.add_parser("session", help="a thread agent's conversation transcript as JSON")
    ps.add_argument("id", help="task id")
    ps.add_argument("--before", type=int, help="byte offset to read the window before (previous answer's `from`)")
    ps.add_argument("--after", type=int, help="byte offset to read what came after (previous answer's `offset`)")
    ps.add_argument("--limit", type=int, default=200, help="max items in one window (default 200)")
