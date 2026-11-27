"""The rules of pmlib/messaging/router.py (once events/policy.py) on literal records: who wrote an entry and whether it wakes the PM (wake_rule),
whether an entry in the log is news (is_news), and which entries a batch carries (pending_items). No ledger, no
terminal: these rules take what was already read (docs/design/pm-py-refactor.md, sections 5.2-5.3)."""
import datetime
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pmlib.messaging import router as policy  # noqa: E402

REPO = "/p"
PMS = {"hc:tPM", "hc:tOLD"}  # the PM's terminal and the one it took over from


class Facts:
    """What wake_rule asks of a Caller, as literals; it records whether the caller's own task was asked."""

    def __init__(self, pane="", own_task=None, manages=False, helper=None):
        self.pane, self._own_task, self._manages, self.helper = pane, own_task, manages, helper
        self.asked_own_task = False

    def manages(self, repo):
        return self._manages and repo == REPO

    @property
    def own_task(self):
        self.asked_own_task = True
        return self._own_task


# writer -> (the caller, the source it writes, from_task, whether its own task is asked), on a target task in hc:tW
# that the PM dispatched (its own worker writes from there) unless the writer says otherwise.
WRITERS = {
    "manager": (lambda: Facts("hc:tPM", manages=True), "pm", None, False),
    "in-place worker": (lambda: Facts("hc:tW"), "worker", None, False),
    "worker of another task": (lambda: Facts("hc:tV", {"id": "w-9", "dispatched": True}), "worker", "w-9", True),
    "reviewer": (lambda: Facts("hc:tR", {"id": "w-9-review", "review_of": "w-9"}), "worker", "w-9-review", True),
    "worker of this task elsewhere": (lambda: Facts("hc:tV", {"id": "t", "dispatched": True}), "worker", None, True),
    "helper": (lambda: Facts("hc:tH", helper={"of": "w-9", "name": "look", "project": "p"}), "helper", None, True),
    "session with its own task": (lambda: Facts("hc:tS", {"id": "s-1"}), "session", None, True),
    "session": (lambda: Facts("hc:tX"), "session", None, True),
    "shell": (lambda: Facts(""), "session", None, False),
}
# kind -> (status the entry sets, reported: it carries --note or --commit)
KINDS = {"moves to review": ("review", True), "moves to in_progress": ("in_progress", True),
         "commit or note": ("", True), "fields only": ("", False)}
# (written by a worker/helper, kind, task status) -> wake. Moving to a waking status is news from anyone but the PM;
# a report is news from a worker/reviewer/helper while the task is in review, blocked, or done (not proposed).
WAKE = {
    (True, "moves to review", "in_progress"): True, (True, "moves to review", "review"): True,
    (True, "moves to review", "blocked"): True, (True, "moves to review", "done"): True,
    (True, "moves to review", "proposed"): True,
    (True, "moves to in_progress", "in_progress"): False, (True, "moves to in_progress", "review"): True,
    (True, "moves to in_progress", "blocked"): True, (True, "moves to in_progress", "done"): True,
    (True, "moves to in_progress", "proposed"): False,
    (True, "commit or note", "in_progress"): False, (True, "commit or note", "review"): True,
    (True, "commit or note", "blocked"): True, (True, "commit or note", "done"): True,
    (True, "commit or note", "proposed"): False,
    (True, "fields only", "in_progress"): False, (True, "fields only", "review"): False,
    (True, "fields only", "blocked"): False, (True, "fields only", "done"): False,
    (True, "fields only", "proposed"): False,
    (False, "moves to review", "in_progress"): True, (False, "moves to review", "review"): True,
    (False, "moves to review", "blocked"): True, (False, "moves to review", "done"): True,
    (False, "moves to review", "proposed"): True,
    (False, "moves to in_progress", "in_progress"): False, (False, "moves to in_progress", "review"): False,
    (False, "moves to in_progress", "blocked"): False, (False, "moves to in_progress", "done"): False,
    (False, "moves to in_progress", "proposed"): False,
    (False, "commit or note", "in_progress"): False, (False, "commit or note", "review"): False,
    (False, "commit or note", "blocked"): False, (False, "commit or note", "done"): False,
    (False, "commit or note", "proposed"): False,
    (False, "fields only", "in_progress"): False, (False, "fields only", "review"): False,
    (False, "fields only", "blocked"): False, (False, "fields only", "done"): False,
    (False, "fields only", "proposed"): False,
}


class WakeRule(unittest.TestCase):
    def test_writer_by_entry_kind_by_task_status(self):
        for status in ("in_progress", "review", "blocked", "done", "proposed"):
            target = {"id": "t", "repo": REPO, "status": status, "pane": "hc:tW", "dispatched": True}
            for writer, (make, source, from_task, asks) in WRITERS.items():
                for kind, (sets, reported) in KINDS.items():
                    with self.subTest(writer=writer, kind=kind, status=status):
                        caller = make()
                        got = policy.wake_rule(target, sets, reported, caller)
                        self.assertEqual(caller.asked_own_task, asks)
                        if source == "pm":
                            self.assertEqual(got, {"source": "pm"})
                            continue
                        expected = {"source": source}
                        if from_task:
                            expected["from_task"] = from_task
                        if WAKE[(source in ("worker", "helper"), kind, status)]:
                            expected["wake"] = True
                        self.assertEqual(got, expected)

    def test_a_task_the_pm_registered_is_reported_on_by_the_worker_of_another(self):
        # Design 5.1: the PM registered `book` itself (its pane is the PM's, not dispatched); the worker of `own`
        # reports a commit on it while it is in review, without moving it.
        book = {"id": "book", "repo": REPO, "status": "review", "pane": "hc:tPM"}
        worker = Facts("hc:t16", {"id": "own", "dispatched": True})
        self.assertEqual(policy.wake_rule(book, "", True, worker), {"source": "worker", "from_task": "own",
                                                                     "wake": True})
        # Not from a task the PM started: a session's comment stays quiet.
        self.assertEqual(policy.wake_rule(book, "", True, Facts("hc:t40", {"id": "solo"})), {"source": "session"})

    def test_no_project_no_fields(self):
        self.assertEqual(policy.wake_rule({"id": "t", "status": "review"}, "review", True, Facts("hc:tW")), {})

    def test_cross_repo_worker_and_helper_count_as_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            proj_a = root / "proj-a"
            proj_a_sub = proj_a / "sub"
            proj_b = root / "proj-b"
            for d in (proj_a, proj_a_sub, proj_b):
                d.mkdir(parents=True)
            target = {"id": "t-a", "repo": str(proj_a), "status": "review", "pane": "hc:tPM"}
            # Worker of another repo -> session, no from_task, non-moving report is quiet.
            other_worker = Facts("hc:tB", {"id": "w-b", "dispatched": True, "repo": str(proj_b)})
            self.assertEqual(policy.wake_rule(target, "", True, other_worker), {"source": "session"})
            # Worker of a subdirectory inside proj-a -> worker of proj-a, wakes with from_task.
            sub_worker = Facts("hc:tSub", {"id": "w-sub", "dispatched": True, "repo": str(proj_a_sub)})
            self.assertEqual(
                policy.wake_rule(target, "", True, sub_worker),
                {"source": "worker", "from_task": "w-sub", "wake": True},
            )
            # Helper of another project -> session, quiet on non-moving report.
            other_helper = Facts("hc:tHB", helper={"of": "w-b", "name": "look", "project": "proj-b"})
            self.assertEqual(policy.wake_rule(target, "", True, other_helper), {"source": "session"})

    def test_paused_and_closed_task_statuses(self):
        for status in ("paused", "merged", "released", "abandoned"):
            target = {"id": "t", "repo": REPO, "status": status, "pane": "hc:tW", "dispatched": True}
            # Non-moving worker/helper reports on paused or closed (other than done) tasks do not wake.
            self.assertEqual(policy.wake_rule(target, "", True, Facts("hc:tW")), {"source": "worker"})
            helper = Facts("hc:tH", helper={"of": "t", "name": "look", "project": "p"})
            self.assertEqual(policy.wake_rule(target, "", True, helper), {"source": "helper"})
            # Moving into a waking status from paused/closed still wakes.
            self.assertEqual(policy.wake_rule(target, "review", True, Facts("hc:tW")),
                             {"source": "worker", "wake": True})


AT = "2026-11-22 10:00:00"


def entry(source="worker", text="fixed it", status="review", by="hc:tW", **more):
    e = {"type": "thread", "task": "t", "status": status, "by": by, "at": AT, "text": text, **more}
    if source is not None:
        e["source"] = source
    return e


def task_of(status="review", first="", created="2026-11-22 08:00"):
    record = {"id": "t", "status": status, "created": created, "log": [{"text": first}] if first else []}
    return lambda task: record if task == "t" else {}


# (source, text, status after the entry) -> news. The task exists, and was made long before the entry.
NEWS = [
    # Moving a task to review, blocked, done or proposed is news from anyone but the PM.
    ("worker", "status=review; done", "review", True),
    ("helper", "status=blocked; which way?", "blocked", True),
    ("session", "status=done; finished", "done", True),
    (None, "status=proposed; idea", "proposed", True),
    ("pm", "status=review; sent", "review", False),
    ("worker", "status=in_progress; again", "in_progress", False),
    # A commit on a waiting task: news from its worker, and from an entry older than `source`.
    ("worker", "commit=abc1234; fixed", "review", True),
    ("worker", "commit=abc1234", "blocked", True),
    (None, "commit=abc1234; fixed", "review", True),
    ("session", "commit=abc1234; another session's comment", "review", False),
    ("helper", "commit=abc1234; found it", "review", True),
    # A note alone: news from a worker or helper; fields alone are not a report.
    ("worker", "fixed the review comments", "review", True),
    ("worker", "branch=dev/x", "review", False),
    ("worker", "", "review", False),
    (None, "fixed the review comments", "review", False),
    ("session", "looks fine to me", "blocked", False),
    ("helper", "found the cause", "review", True),
    # A task in progress or proposed: non-moving report is not news; done is (e.g. amended review report).
    ("worker", "commit=abc1234; fixed", "in_progress", False),
    ("worker", "fixed", "done", True),
    ("helper", "amended", "done", True),
    (None, "commit=abc1234; legacy done commit", "done", True),
    (None, "legacy done note without source", "done", False),
    ("session", "commit=abc1234; session comment", "done", False),
    ("session", "session note on done", "done", False),
    ("worker", "commit=abc1234", "proposed", False),
    ("helper", "note on proposed", "proposed", False),
    (None, "commit=abc1234", "proposed", False),
    ("worker", "commit=abc1234; paused note", "paused", False),
    (None, "status=review; paused now", "paused", False),
    # Merged: only a worker's or helper's delegated land, which moved the task there itself.
    ("worker", "status=merged; landed", "merged", True),
    ("helper", "status=merged, commit=abc1234; landed", "merged", True),
    ("session", "status=merged; landed", "merged", False),
    (None, "status=merged; landed", "merged", False),
    ("worker", "landed", "merged", False),
]


class IsNews(unittest.TestCase):
    def test_writer_by_entry_kind_by_task_status(self):
        for source, text, status, news in NEWS:
            with self.subTest(source=source, text=text, status=status):
                self.assertEqual(policy.is_news(entry(source, text, status), PMS, task_of(status)), news)

    def test_an_older_entry_is_judged_as_before(self):
        # Written before `from_task` existed, by a session: a commit on a task in review is another session's
        # comment, not news; the same entry from before `source` was recorded counts (a commit).
        old = entry("session", "commit=abc1234; another session's comment", "review", by="hc:t30")
        self.assertNotIn("from_task", old)
        self.assertFalse(policy.is_news(old, PMS, task_of()))
        self.assertTrue(policy.is_news({k: v for k, v in old.items() if k != "source"}, PMS, task_of()))
        # from_task changes nothing for the reader: the writer already chose `source`.
        new = entry("worker", "commit=a27dc32; follow-up", "review", by="hc:t16", from_task="own")
        self.assertTrue(policy.is_news(new, PMS, task_of()))
        self.assertTrue(policy.is_news({k: v for k, v in new.items() if k != "from_task"}, PMS, task_of()))

    def test_the_pm_and_its_earlier_terminal_never_wake_it(self):
        for by in sorted(PMS):
            self.assertFalse(policy.is_news(entry("worker", "status=review; x", by=by), PMS, task_of()))

    def test_the_writers_mark_decides_when_there_is_one(self):
        self.assertTrue(policy.is_news({"type": "event", "wake": True, "text": "x"}, PMS, task_of()))
        self.assertFalse(policy.is_news(entry(wake=False, text="status=review; x"), PMS, task_of()))
        self.assertFalse(policy.is_news({"type": "user", "text": "hi"}, PMS, task_of()))

    def test_the_entry_that_registered_a_task_is_news(self):
        first = "status=review; a task registered straight into review"
        made = task_of("review", first=first, created=AT[:16])
        self.assertTrue(policy.is_news(entry("session", first, "review"), PMS, made))
        long_ago = task_of("review", first=first, created="2026-11-21 10:00")
        self.assertTrue(policy.is_news(entry("session", first, "review"), PMS, long_ago))  # it moved it, too
        quiet = "a note when it was made"
        self.assertTrue(policy.is_news(entry("session", quiet, "review"), PMS, task_of("review", quiet, AT[:16])))
        self.assertFalse(policy.is_news(entry("session", quiet, "review"), PMS,
                                        task_of("review", quiet, "2026-11-21 10:00")))

    def test_near(self):
        self.assertTrue(policy.near("2026-11-22 10:00", "2026-11-22 10:01:30"))
        self.assertFalse(policy.near("2026-11-22 10:00", "2026-11-22 10:02"))
        self.assertFalse(policy.near("", AT))


class PendingItems(unittest.TestCase):
    def batch(self, events, tasks, end=None, now=None, settle=0):
        offsets = [(i * 100, e) for i, e in enumerate(events)]
        return policy.pending_items(offsets, PMS, tasks, len(events) * 100 if end is None else end, now, settle)

    def test_a_tasks_entries_count_as_its_latest(self):
        events = [entry(text="status=review; first"), entry(text="commit=abc1234; second")]
        end, items = self.batch(events, {"t": {"status": "review"}})
        self.assertEqual(end, 200)
        self.assertEqual([(i["event"]["text"], i["earlier"]) for i in items], [("commit=abc1234; second", 1)])

    def test_the_pm_moving_the_task_on_drops_the_earlier_entry(self):
        events = [entry(text="status=review; done"), entry("pm", "status=in_progress; again", "in_progress",
                                                           by="hc:tPM")]
        self.assertEqual(self.batch(events, {"t": {"status": "in_progress"}})[1], [])
        # The PM's entry that keeps the status (a note) leaves the report there.
        events[1] = entry("pm", "looking", "review", by="hc:tPM")
        self.assertEqual(len(self.batch(events, {"t": {"status": "review"}})[1]), 1)

    def test_a_task_merged_released_or_abandoned_needs_no_word(self):
        for status in ("merged", "released", "abandoned"):
            self.assertEqual(self.batch([entry(text="status=review; x")], {"t": {"status": status}})[1], [])
        # A delegated land is itself the event.
        landed = entry("helper", "status=merged; landed", "merged")
        self.assertEqual(len(self.batch([landed], {"t": {"status": "merged"}})[1]), 1)

    def test_dependency_events_count_while_the_task_waits(self):
        deps = {"type": "event", "source": "deps", "task": "t", "wake": True, "text": "ready", "at": AT}
        end, items = self.batch([deps, dict(deps, text="ready again")], {"t": {"status": "proposed"}})
        self.assertEqual([(i["event"]["text"], i["earlier"]) for i in items], [("ready again", 1)])
        self.assertEqual(self.batch([deps], {"t": {"status": "in_progress"}})[1], [])

    def test_a_task_without_a_file_is_judged_as_empty(self):
        stall = {"type": "stall", "task": "gone", "wake": True, "text": "stopped", "at": AT}
        self.assertEqual(len(self.batch([stall], {})[1]), 1)

    def test_lines_written_just_now_wait_for_the_next_look(self):
        now = datetime.datetime(2026, 11, 22, 10, 0, 1)
        events = [entry(text="status=review; old", at="2026-11-22 09:59:00"),
                  dict(entry(text="status=review; new"), task="u", at="2026-11-22 10:00:00")]
        end, items = self.batch(events, {"t": {"status": "review"}, "u": {"status": "review"}}, now=now, settle=2)
        self.assertEqual(end, 100)  # the young line's own offset: it is judged next time
        self.assertEqual([i["event"]["text"] for i in items], ["status=review; old"])
        end, items = self.batch(events, {"t": {"status": "review"}, "u": {"status": "review"}}, now=now)
        self.assertEqual((end, len(items)), (200, 2))  # no settling: everything


if __name__ == "__main__":
    unittest.main()
