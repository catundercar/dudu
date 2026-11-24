"""What is news for a project's PM: which ledger entries wake it, judged by the writer when it writes them
(wake_rule) and by the reader for entries any pm.py version wrote (is_news), and which entries after the delivered
mark a batch carries (pending_items). These rules take what was already read (records, the caller's facts) and do
no IO of their own; wake_fields is the one function here that gathers its inputs (Caller.current(), app_pm). Layer 2.

The deliverer that reads the log, words the batch and moves the delivered mark is events code above this layer.
"""
import datetime
import re

from ..caller import Caller
from ..home import project_slug
from ..ledger.task import pm_started
from ..project.project import ProjectRegistry, app_pm, in_scope


WAKING = ("review", "blocked", "done", "proposed")  # a ledger entry that moves a task here is news for the PM
REPORT_WAKING = ("review", "blocked", "done")       # a non-moving worker/reviewer/helper report wakes on these only
MOVED_ON = ("merged", "released", "abandoned")     # a task here needs no word about an earlier entry any more


# How `update` words an entry: its field changes ("status=review, commit=abc1234"), then "; " and the note, if any.
STATUS_SET = re.compile(r"^(?:[a-z_]+=[^,;]*, )*status=([a-z_]+)")  # it moved the task
COMMIT_SET = re.compile(r"^(?:[a-z_]+=[^,;]*, )*commit=")          # it set a commit
FIELDS_ONLY = re.compile(r"^[a-z_]+=[^,;]*(?:, [a-z_]+=[^,;]*)*$")  # field changes and no note
_BG_SHELL_MSG = re.compile(r"\bshells?\s+still\s+running\b", re.I)


def manager_ready_for_batch(term_info, last_turn_stopped, *, bg_work=False):
    """Pure delivery readiness policy for a manager terminal: returns `(ready, if_idle_flag)`.

    Ready when `agent_state` is `"idle"` (with `--if idle`) or `"done"` (without `--if idle`), OR when
    `agent_state == "working"` solely because background shell commands / child processes are still running
    (`shell(s) still running` or `bg_work=True`) and the manager's foreground turn has already stopped
    (without `--if idle`)."""
    if term_info is None:
        return False, False
    if hasattr(term_info, "agent_state") and not isinstance(term_info, dict):
        state = str(getattr(term_info, "agent_state", "") or "")
        msg = str(getattr(term_info, "status_msg", "") or "")
    elif isinstance(term_info, dict):
        status = term_info.get("status") if isinstance(term_info.get("status"), dict) else {}
        state = str(status.get("state") or "")
        msg = str(status.get("msg") or status.get("message") or "")
    else:
        return False, False
    if state == "idle":
        return True, True
    if state == "done":
        return True, False
    if state == "working" and bool(last_turn_stopped) and (bool(_BG_SHELL_MSG.search(msg)) or bool(bg_work)):
        return True, False
    return False, False


def wake_fields_for(task, status, reported, caller, has_app_pm):
    """Apply `wake_rule` and attach explicit `wake` (True or False) whenever a desktop-app PM exists (`has_app_pm`)."""
    fields = wake_rule(task, status, reported, caller)
    should_wake = bool(fields.pop("wake", False))
    if fields and has_app_pm:
        fields["wake"] = should_wake
    return fields


def wake_fields(task, status, reported=False, *, ctx=None):
    """Event fields of a ledger entry that sets `status` ("" when it sets none): who wrote it (`source`), and `wake`
    when it is news for the project's PM: someone else moved the task to review, blocked, done or proposed, or a
    dispatched worker/reviewer/helper writes a report (`--note` or `--commit`) while the task is in review, blocked,
    or done. Progress notes and the PM's own entries wake nobody.

    The rule is wake_rule; `wake` (True or False) is written whenever a desktop-app PM exists (`app_pm`)."""
    caller = ctx.caller if ctx is not None else Caller.current()
    has_app_pm = bool(ProjectRegistry(ctx).app_pm(task.get("repo")) if ctx is not None else app_pm(task.get("repo")))
    return wake_fields_for(task, status, reported, caller, has_app_pm)


def wake_rule(task, status, reported, caller):
    """wake_fields' rule over what the caller knows: `source` (pm, worker, helper or session), `from_task` when a
    worker writes to a task other than its own, and `wake` when the entry is news for the PM, whether or not the PM
    can be woken. task: the task record written to; caller: a Caller, or anything with its `pane`, `own_task`,
    `helper` and `manages(repo)`. It asks the caller only what it needs, in this order: whether it manages the
    project, then its own task / helper only when the target is not its own by its pane (the in-place worker costs
    no look at the terminal)."""
    repo = task.get("repo")
    if not repo:
        return {}
    if caller.pane and caller.manages(repo):
        return {"source": "pm"}
    worker = bool(caller.pane) and task.get("pane") == caller.pane and pm_started(task)
    mine = None
    if not worker and caller.pane:
        mine = caller.own_task
        if mine and pm_started(mine):
            mine_repo = mine.get("repo")
            worker = (not mine_repo) or in_scope(mine_repo, repo) or in_scope(repo, mine_repo)
    is_helper = False
    if not worker and caller.pane:
        helper = getattr(caller, "helper", None)
        if helper:
            hproj = helper.get("project") or ""
            is_helper = (not hproj) or hproj == project_slug(repo)
    if worker:
        source = "worker"
    elif is_helper:
        source = "helper"
    else:
        source = "session"
    fields = {"source": source}
    if worker and mine and mine.get("id") and mine["id"] != task.get("id"):
        fields["from_task"] = mine["id"]
    if status in WAKING or ((worker or is_helper) and reported and task.get("status") in REPORT_WAKING):
        fields["wake"] = True
    return fields


def is_news(e, pms, task_of):
    """Whether a log event is news for the PM. The reader decides, by what the entry did, not by a mark its writer
    may or may not have set, so entries that earlier pm.py versions wrote are judged the same way. News is what
    needs the PM and only someone else can have caused:

    - an event its writer marked `wake`: a notify, an event, a stall (and the entries of `new` and `update` that
      the current pm.py marks by this same rule);
    - a ledger entry by someone other than the PM (pms: its terminals) on a task that is in review, blocked, done
      or proposed after it, which moved the task there (`status=` among its field changes), registered it there
      (the task's first entry, written when it was made), or is its own worker's report: an `update` (only `new`
      and `update` record a `source`) that sets a commit or carries a note.

    Not news: progress notes (`log`), notes no command of the worker's reports with (a tab renamed, a terminal to
    be closed, retire, archive, reattach), an `update` that changes other fields only, another session's comment
    on a task that is already there, and the PM's own entries. An entry from before `source` was recorded counts
    when it moved or registered the task, or set a commit; a note alone from it is not told from a progress note.
    task_of(task id): that task's file, or {}."""
    if e.get("wake") is False:
        return False
    if e.get("wake") is True:
        return True
    if e.get("type") != "thread":
        return False
    if e.get("source") == "pm" or e.get("by") in pms:
        return False
    text = str(e.get("text") or "")
    moved = STATUS_SET.match(text)
    if e.get("status") == "merged":
        # Only an explicit worker/helper delegated land wakes the PM; entries without `source` stay silent.
        return bool(moved and moved.group(1) == "merged" and e.get("source") in ("worker", "helper"))
    if e.get("status") not in WAKING:
        return False
    if moved and moved.group(1) == e.get("status"):
        return True
    task = task_of(e.get("task"))
    log = [x for x in task.get("log") or [] if isinstance(x, dict)]
    if log and log[0].get("text") == text and near(task.get("created"), e.get("at")):
        return True  # it registered the task: its first entry, written when the task was made
    if e.get("status") not in REPORT_WAKING:
        return False
    if COMMIT_SET.match(text):
        return e.get("source") in ("worker", "helper", None)
    return e.get("source") in ("worker", "helper") and bool(text.strip()) and not FIELDS_ONLY.match(text)


def near(one, other, seconds=90):
    """Whether two ledger times ("YYYY-MM-DD HH:MM[:SS]") are at most `seconds` apart."""
    try:
        when = [datetime.datetime.strptime(str(t)[:16], "%Y-%m-%d %H:%M") for t in (one, other)]
    except ValueError:
        return False
    return abs((when[0] - when[1]).total_seconds()) <= seconds


def pending_items(events, pms, tasks, end, now=None, settle=0):
    """(end, items): which of `events` ((offset, event) after the delivered mark, as events_after gives them, the
    log ending at `end`) reach the PM, and where the stretch they cover ends. pms: the PM's terminals; tasks: task
    id -> that task's file ({} when it cannot be read; an id it lacks counts as {}). Each item is {"event",
    "earlier"}. A task's entries count as its latest one (`earlier`: how many came before it), and an entry says
    nothing new once the PM itself has moved that task to another status, or the task is merged, released or
    abandoned. With `settle` seconds and the time `now`, lines written in the last `settle` s end the stretch: they
    are judged on the next look."""
    items, latest = [], {}

    def task_of(task):
        return tasks.get(task) or {} if task else {}
    # A line written in the last SETTLE s is judged on the next look: `note` appends it before the task file it is
    # about is saved, and what is news (a registration) and what the message says (its commit) come from that file.
    young = (now - datetime.timedelta(seconds=settle)).strftime("%Y-%m-%d %H:%M:%S") if settle and now else None
    soon = (now + datetime.timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S") if now else None
    for at, e in events:
        if young and young <= str(e.get("at") or "") <= soon:
            end = at
            break
        task = e.get("task") if e.get("type") in ("thread", "stall") else None
        if task and e.get("type") == "thread" and e.get("by") in pms:
            old = latest.get(task)
            if old and e.get("status") != old["event"].get("status"):
                items.remove(latest.pop(task))
            continue
        if not is_news(e, pms, task_of):
            continue
        item = {"event": e, "earlier": 0}
        if task:
            dedup_key = task
        elif e.get("type") == "event" and e.get("source") in ("deps", "rollup") and e.get("task"):
            dedup_key = (e.get("source"), e.get("task"))
        else:
            dedup_key = None
        if dedup_key:
            old = latest.pop(dedup_key, None)
            if old:
                items.remove(old)
                item["earlier"] = old["earlier"] + 1
            latest[dedup_key] = item
        items.append(item)

    def moved_on(item):
        e = item["event"]
        task_id = e.get("task")
        if not task_id:
            return False
        # Delegated merge completion itself (`status=merged` from a worker/helper) is the event to deliver.
        if e.get("status") == "merged" and (
                e.get("wake") is True or (e.get("source") in ("worker", "helper") and e.get("by") not in pms)):
            return False
        st = task_of(task_id).get("status")
        if e.get("type") == "event" and e.get("source") == "deps":
            return st != "proposed"
        if e.get("type") == "event" and e.get("source") == "rollup":
            return st == "done" or st in MOVED_ON
        return st in MOVED_ON
    return end, [i for i in items if not moved_on(i)]
