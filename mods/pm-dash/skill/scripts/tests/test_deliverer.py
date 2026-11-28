"""Event delivery, worker stalls, task dependencies, and inbox/watch notifications (Stage 6c, wave 6c1).

Moved from test_pm.py (`Events`, 39 tests; `TaskDependencies`, 7 tests) and test_pm_events.py (`PMNotifications`,
7 tests; `Watchers`, 11 tests) — 64 tests total. Every test builds its own isolated `Context` via `make_ctx` with
`FakeHc`, `FakeTui`, `FakeProcs`, `FakeClock`, and `legacy_ctx.bound` around Layer 4 `cmd_*` calls, without
mutating module-level `pm.*` globals.
"""
from __future__ import annotations

import argparse
import re
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

if "pmlib.context" not in sys.modules:
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-deliverer")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

from fakes import FakeChangeWaiter, FakeClock, FakeHc, FakeProcs, FakeTui, StubGit, make_ctx, queued_sends  # noqa: E402
from pmlib import cli, hooks  # noqa: E402
from pmlib.caller import Caller  # noqa: E402
from pmlib.commands import (  # noqa: E402
    dispatch as dispatch_cmds,
    events as events_cmds,
    ledger as ledger_cmds,
    manager as manager_cmds,
    memory as memory_cmds,
    review as review_cmds,
    workers as workers_cmds,
)
from pmlib.context import DeliverWatcher, StdOutput  # noqa: E402
from pmlib.errors import Refused, WaitOutcome  # noqa: E402
from pmlib.events import inbox as inbox_mod  # noqa: E402
from pmlib.messaging import router as policy_mod  # noqa: E402
from pmlib.events.deliver import (  # noqa: E402
    MAX_RECEIVED_RANGES,
    SETTLE,
    Delivery,
    _add_range,
    _is_covered,
    batch_stretch,
    unwrap_pasted,
)
from pmlib.events.deliverer import Deliverer  # noqa: E402
from pmlib.events.deps_watch import DependencyWatcher  # noqa: E402
from pmlib.events.inbox import InboxWatcher  # noqa: E402
from pmlib.messaging.router import is_news  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.transition import FIELDS  # noqa: E402
from pmlib.manager import handover as handover_mod, seat as seat_mod  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import pm_name  # noqa: E402
from pmlib.store import lock_file, replace_task_file, unlock_file  # noqa: E402
from pmlib.terminals import events as term_events_mod  # noqa: E402
from pmlib.views import state as state_view, status as status_view  # noqa: E402
from pmlib.workers.send import send_when_ready_for  # noqa: E402
from pmlib.workers.wait import wait_for_report_events_for, wait_for_report_for  # noqa: E402


def _unless(args: tuple) -> tuple:
    """An `hc send` call without its `--if <status>` (the deliverer types only while the PM is as it saw it)."""
    items = list(args)
    if "--if" in items:
        idx = items.index("--if")
        del items[idx:idx + 2]
    return tuple(items)


class _EventsFakeHc(FakeHc):
    """FakeHc tailored for deliverer tests: scripted `pm_states` queue for `t7`, pop-on-read `terms` queues,
    customizable `send_reply` (dict or callable), `on_get` hook, and virtual-clock-advancing `FakeChangeWaiter`."""

    def __init__(self, project_name: str, *, clock: FakeClock) -> None:
        super().__init__(clock=clock)
        self.project_name = project_name
        self.pm_states: list[str] = []
        self.terms: dict[str, object] = {"t20": {"state": "live", "status": {"state": "working"}}}
        self.send_reply: object = {"started": True}
        self.hc_calls: list[tuple] = []
        self.on_get = None
        self.waiter_override = None

    def get_raw(self, term: str, *, errors: bool = False):
        key = term[3:] if term.startswith("hc:") else term
        self.hc_calls.append(("get", key))
        if self.on_get is not None:
            self.on_get(("get", key))
        if key == "t7":
            if self.pm_states:
                state = self.pm_states.pop(0) if len(self.pm_states) > 1 else self.pm_states[0]
            else:
                state = "idle"
            if state == "gone":
                return {"state": "finished", "labels": {"pm": self.project_name}, "status": None}
            return {"state": "live", "labels": {"pm": self.project_name}, "status": {"state": state}}
        seen = self.terms.get(key)
        if isinstance(seen, list):
            if not seen:
                return None
            return seen.pop(0) if len(seen) > 1 else seen[0]
        if seen is not None:
            return seen
        return super().get_raw(term, errors=errors)

    def send(self, term: str, text: str, *, if_state: str | None = None, timeout: float = 180, errors: bool = False):
        key = term[3:] if term.startswith("hc:") else term
        raw_call = ("send", "--if", if_state, key, text) if if_state is not None else ("send", key, text)
        self.hc_calls.append(raw_call)
        if callable(self.send_reply):
            return self.send_reply(_unless(raw_call))
        return self.send_reply

    def label(self, term: str, *pairs: str, errors: bool = False):
        key = term[3:] if term.startswith("hc:") else term
        self.hc_calls.append(("label", key, *pairs))
        entry = self.terms.get(key)
        if isinstance(entry, dict):
            labels = entry.setdefault("labels", {})
            for kv in pairs:
                k, _, v = kv.partition("=")
                if v:
                    labels[k] = v
                else:
                    labels.pop(k, None)
            return dict(entry)
        return super().label(term, *pairs, errors=errors)

    def name_tab(self, terminal: str, name: str, only_if: str | None = None, wait: float = 0) -> bool:
        key = terminal[3:] if terminal.startswith("hc:") else terminal
        self.tab_calls.append({"fn": "name_tab", "terminal": key, "name": name, "only_if": only_if, "wait": wait})
        self.tab_names[key] = name
        return True

    def change_waiter(self, paths=(), hc_args=None, files=(), terminals=None, folders=(), *, hc=None, warn=None):
        if self.waiter_override is not None:
            waiter = self.waiter_override
        else:
            clk = self._clock
            waiter = FakeChangeWaiter(
                paths=paths,
                hc_args=hc_args,
                files=files,
                terminals=terminals,
                folders=folders,
                on_wait=(lambda dt: clk.advance(min(max(float(dt), 0.0), 5.0))) if clk is not None else None,
            )
        self.waiters.append(waiter)
        return waiter


class _MarkFakeProcs(FakeProcs):
    """FakeProcs whose `code_mark()` can be scripted to test deliverer handover after an install."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.mark_fn = None

    def code_mark(self):
        if self.mark_fn is not None:
            return self.mark_fn()
        return super().code_mark()


class Events(unittest.TestCase):
    """One way into a desktop-app PM: whoever writes an event has it delivered; the PM waits on nothing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-events-ctx-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo_dir = self.base / "repo"
        self.repo_dir.mkdir()
        self.git = GitRepo(worktree_base=self.base / "worktrees")
        self.repo = self.git.project_root(str(self.repo_dir))
        self.name = Path(self.repo).name
        self.clock = FakeClock()
        self.hc = _EventsFakeHc(self.name, clock=self.clock)
        self.tui = FakeTui(agents=[])
        self.procs = _MarkFakeProcs(make_ctx(self.base).home, env={"PM_HOME": str(self.base / "ledger")})
        self.pane = "hc:t20"
        self.extra_env: dict[str, str] = {}
        self.holds: tuple = ()
        self.register()
        self.be("hc:t20")

    def ctx(self, pane: str | None = None, *, env: dict[str, str] | None = None):
        use_pane = self.pane if pane is None else pane
        env_map = {**self.extra_env, **(env or {})}
        c = make_ctx(
            self.base,
            pane=use_pane,
            hc=self.hc,
            tui=self.tui,
            git=self.git,
            procs=self.procs,
            clock=self.clock,
            out=StdOutput(),
            env=env_map,
        )
        c.deliver_holds = self.holds
        c.caller = Caller(c)
        return c

    def register(self, **fields):
        c = self.ctx()
        c.home.registrations.mkdir(parents=True, exist_ok=True)
        c.home.registration(project_slug(self.repo)).write_text(json.dumps(
            {"name": pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "hc:t7",
             "runtime": "hc", "terminal": "t7", "agent": "claude", **fields}))

    def be(self, pane: str):
        self.pane = pane

    def task(self, slug: str, pane: str = "hc:t20", status: str = "in_progress", **fields) -> str:
        c = self.ctx()
        task = {"id": f"{self.name}-{slug}", "title": slug, "project": self.name, "repo": self.repo, "status": status,
                "owner": "pm", "base": "main", "pane": pane, "dispatched": True, "created": self.clock.now(),
                "log": [], **fields}
        Ledger(c).save(task)
        return task["id"]

    def load(self, task_id: str) -> dict:
        return Ledger(self.ctx()).load(task_id).raw

    def save(self, task: dict) -> None:
        Ledger(self.ctx()).save(task)

    def update(self, task_id: str, *, settle: bool = True, **fields):
        c = self.ctx()
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_update(argparse.Namespace(id=task_id, keep=False, **{"note": None, **fields}), ctx=c)
        if settle:
            self.clock.advance(SETTLE + 1)

    def events(self, kind: str | None = None) -> list[dict]:
        return [e for e in Conversation(self.ctx(), self.repo).events() if kind in (None, e.get("type"))]

    def size(self) -> int:
        return (self.ctx().home.project_for(self.repo).conversation).stat().st_size

    def started(self) -> list[str]:
        return [s["args"][1] for s in self.procs.spawned if s["args"][:1] == ["deliver"]]

    def hook(self, event: str, **payload) -> str:
        c = self.ctx()
        out = io.StringIO()
        stdin = io.StringIO(json.dumps({"hook_event_name": event, **payload}))
        with mock.patch.object(sys, 'stdin', stdin), contextlib.redirect_stdout(out):
            hooks.cmd_hook_turn(None, ctx=c)
        return out.getvalue()

    def sends(self) -> list[tuple]:
        """("send", terminal, text) of each send, without its `--if <status>`."""
        return [_unless(c) for c in self.hc.hc_calls if c[0] == "send"]

    def deliver(self, *pm_states: str):
        """Run the project's deliverer through these looks at the PM (t7); then its terminal has exited."""
        self.hc.pm_states[:] = [*pm_states, "gone"]
        c = self.ctx()
        events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=False, since=None), ctx=c)

    def entry(self, task_id: str, text: str, by: str, status: str | None = None, **fields):
        """A ledger entry as any pm.py version writes one: the log line, then the task file."""
        c = self.ctx()
        task = Ledger(c).load(task_id).raw
        task["status"] = status or task["status"]
        task["log"].append({"at": self.clock.now(), "by": by, "text": text})
        Conversation(c, self.repo).record(
            "thread", task=task_id, title=task["title"], status=task["status"], by=by, text=text, **fields
        )
        Ledger(c).save(task)

    def delivered_offset(self) -> int:
        return Delivery(self.ctx(), self.repo).delivered_offset()

    def received_ranges(self) -> list[list[int]]:
        return Delivery(self.ctx(), self.repo).received_ranges()

    def pending_batch(self, offset: int | None = None, settle: bool = False):
        return Delivery(self.ctx(), self.repo).pending_batch(offset=offset, settle=settle)

    def batch_text(self, start: int, end: int, items: list[dict]) -> str:
        return Delivery(self.ctx(), self.repo).batch_text(start, end, items)

    def test_only_a_status_someone_else_sets_wakes_the_pm(self):
        task = self.task("a")
        with contextlib.redirect_stdout(io.StringIO()):
            status_view.cmd_log(argparse.Namespace(id=task, text="half way"), ctx=self.ctx())
        self.update(task, note="still going")
        self.assertEqual([e.get("wake") for e in self.events("thread")], [None, False])
        self.assertEqual(self.started(), [])
        self.update(task, status="review", commit="abc123", note="done; tests pass")
        last = self.events("thread")[-1]
        self.assertEqual((last["wake"], last["source"], last["by"]), (True, "worker", "hc:t20"))
        self.assertEqual(self.started(), [self.repo])
        self.be("hc:t7")  # the PM sends it back: its own entry wakes nobody
        self.update(task, status="in_progress", note="fix the empty page")
        last = self.events("thread")[-1]
        self.assertEqual((last.get("wake"), last["source"]), (False, "pm"))
        self.assertEqual(self.started(), [self.repo])
        self.be("hc:t30")  # another session hands the PM a task
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_new(argparse.Namespace(
                repo=self.repo, title="new idea", status="proposed", base="main", owner=None,
                workspace=None, pane=None, slug="idea", branch=None, note="handed to PM",
            ), ctx=self.ctx())
        last = self.events("thread")[-1]
        self.assertEqual((last["wake"], last["source"]), (True, "session"))

    def test_worker_follow_up_report_in_review_or_blocked_wakes_the_pm(self):
        task = self.task("a", status="review")
        self.update(task, commit="def456", note="fixed review comments")
        last = self.events("thread")[-1]
        self.assertEqual((last.get("wake"), last["source"], last["by"]), (True, "worker", "hc:t20"))
        self.assertEqual(self.started(), [self.repo])
        self.update(task, commit="ghi789")
        last = self.events("thread")[-1]
        self.assertEqual((last.get("wake"), last["source"]), (True, "worker"))
        self.assertEqual(self.started(), [self.repo, self.repo])
        blocked = self.task("b", status="blocked")
        self.update(blocked, note="more detail on the blocker")
        last = self.events("thread")[-1]
        self.assertEqual((last.get("wake"), last["source"]), (True, "worker"))
        self.assertEqual(self.started(), [self.repo] * 3)
        self.update(task, branch="dev/a")  # neither --note nor --commit: not a report
        self.assertIs(self.events("thread")[-1].get("wake"), False)
        self.be("hc:t30")  # another session is not the task's worker
        self.update(task, commit="jkl012", note="outside comment")
        last = self.events("thread")[-1]
        self.assertEqual((last.get("wake"), last["source"]), (False, "session"))
        self.assertEqual(self.started(), [self.repo] * 3)

    def test_pm_follow_up_report_in_review_or_blocked_wakes_nobody(self):
        task = self.task("a", status="review")
        blocked = self.task("b", status="blocked")
        self.be("hc:t7")
        self.update(task, commit="def456", note="sent back for fixes")
        self.update(blocked, note="noted")
        self.assertEqual([(e.get("wake"), e["source"]) for e in self.events("thread")], [(False, "pm"), (False, "pm")])
        self.assertEqual(self.started(), [])

    def test_a_worker_reporting_on_a_task_the_pm_registered_reaches_the_pm(self):
        own = self.task("own", pane="hc:t16", branch="dev/own")
        book = self.task("book", pane="hc:t7", dispatched=False)
        self.hc.terms["t16"] = {"state": "live", "labels": {"task": own}}
        self.be("hc:t16")
        self.update(book, status="blocked", note="which base?")
        self.update(book, status="review", commit="63ce17c", note="first pass")
        self.update(book, commit="a27dc32", note="follow-up after review")
        entries = [e for e in self.events("thread") if e.get("task") == book][-3:]
        self.assertEqual([(e.get("wake"), e.get("source"), e.get("from_task")) for e in entries],
                         [(True, "worker", own)] * 3)
        start, end, items = self.pending_batch(offset=0)
        mine = [i for i in items if i["event"].get("task") == book]
        self.assertEqual(len(mine), 1)
        self.assertIn("commit=a27dc32", mine[0]["event"]["text"])
        self.assertEqual(mine[0]["earlier"], 2)
        own_ref = Ledger(self.ctx()).task_ref(self.load(own))
        cfg_path = self.ctx().home.config
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        for lang, said, hint in (("en", "reported by the worker of", "pm.py diff"), ("zh", "的 worker 汇报", "pm.py diff")):
            cfg_path.write_text(json.dumps({"lang": lang}), encoding="utf-8")
            text = self.batch_text(start, end, mine)
            self.assertIn(said, text)
            self.assertIn(own_ref, text)
            self.assertIn("dev/own", text)
            # The target has no branch: the hints point at the worker's own task, which has one.
            self.assertIn(f"{hint} {own}", text)
            self.assertIn(f"pm.py approve {own}", text)
            self.assertNotIn(f"pm.py approve {book}", text)

    def test_who_writes_decides_whether_an_entry_wakes_the_pm(self):
        own = self.task("mine", pane="hc:t16")
        unstarted = self.task("solo", pane="hc:t40", dispatched=False)
        self.hc.terms["t16"] = {"state": "live", "labels": {"task": own}}
        self.hc.terms["t40"] = {"state": "live", "labels": {"task": unstarted}}
        writers = {  # terminal -> (source, from_task) the entry should carry on a task that is not its own
            "hc:t7": ("pm", None),
            "hc:t20": ("worker", None),     # the target's own dispatched worker: its pane
            "hc:t16": ("worker", own),      # a worker of another task, known by its terminal's label
            "hc:t40": ("session", None),    # its own task was not started by the PM
            "hc:t30": ("session", None),    # no task of its own
        }
        kinds = {"move to review": ("review", True), "commit or note": ("", True), "fields only": ("", False)}
        for status in ("in_progress", "review", "blocked"):
            target = self.load(self.task(f"t-{status}", status=status))
            for pane, (source, from_task) in writers.items():
                self.be(pane)
                for kind, (moved, reported) in kinds.items():
                    with self.subTest(status=status, writer=pane, kind=kind):
                        before = len(self.hc.hc_calls)
                        got = policy_mod.wake_fields(target, moved, reported=reported, ctx=self.ctx())
                        if pane == "hc:t20":  # the in-place worker costs no hc call
                            self.assertEqual(self.hc.hc_calls[before:], [])
                        if source == "pm":
                            self.assertEqual(got, {"source": "pm", "wake": False})
                            continue
                        self.assertEqual(got.get("source"), source)
                        self.assertEqual(got.get("from_task"), from_task)
                        waking = bool(moved) or (source == "worker" and reported and status in ("review", "blocked"))
                        self.assertIs(got.get("wake"), waking)

    def test_entries_of_older_versions_are_judged_as_before(self):
        task = self.task("old", status="review")
        loaded = {task: self.load(task)}.get
        old = {"type": "thread", "task": task, "status": "review", "by": "hc:t30", "at": self.clock.now(),
               "text": "commit=abc1234; another session's comment"}
        self.assertFalse(is_news({**old, "source": "session"}, {"hc:t7"}, lambda t: loaded(t) or {}))
        self.assertTrue(is_news(old, {"hc:t7"}, lambda t: loaded(t) or {}))  # before `source`: a commit counts
        self.assertFalse(is_news({**old, "text": "a note", "source": "session"}, {"hc:t7"}, lambda t: loaded(t) or {}))
        self.assertTrue(is_news({**old, "source": "worker"}, {"hc:t7"}, lambda t: loaded(t) or {}))

    def test_a_herdr_tui_pm_keeps_its_inbox_and_waits(self):
        self.register(runtime="", terminal="")
        task = self.task("a")
        self.update(task, status="review", note="done")
        self.assertIsNone(self.events("thread")[-1].get("wake"))
        self.assertEqual(self.started(), [])

    def test_a_batch_is_the_latest_word_on_each_task_the_pm_has_not_dealt_with(self):
        a, b, c, d = (self.task(slug, pane=f"hc:t2{n}") for n, slug in enumerate("abcd"))
        for n, task in enumerate((a, b, c, d)):
            self.be(f"hc:t2{n}")
            self.update(task, status="blocked", note=f"question from {task}")
        self.be("hc:t20")
        self.update(a, status="review", note="answered it myself; done")
        self.be("hc:t7")
        self.update(b, status="in_progress", note="use the old format")       # the PM answered b
        with contextlib.redirect_stdout(io.StringIO()):
            status_view.cmd_log(argparse.Namespace(id=c, text="standard: a small change"), ctx=self.ctx())  # a note of the PM's settles nothing
        task = self.load(d)
        task["status"] = "abandoned"
        self.save(task)
        start, end, items = self.pending_batch()
        self.assertEqual((start, end), (0, self.size()))
        self.assertEqual([(i["event"]["task"], i["event"]["status"], i["earlier"]) for i in items],
                         [(c, "blocked", 0), (a, "review", 1)])
        text = self.batch_text(start, end, items)
        self.assertTrue(text.startswith(f"[from pm.py deliver] 2 event(s) (0-{end})\n"))
        self.assertIn(f"[worker hc:t20] {a}: review", text)
        self.assertIn("answered it myself; done", text)
        self.assertIn("(1 earlier entries not shown)", text)
        self.assertNotIn("use the old format", text)

    def test_deliver_waits_for_an_idle_pm_and_sends_one_batch(self):
        task = self.task("a")
        self.update(task, status="review", commit="abc123", note="done; tests pass")
        self.hc.pm_states[:] = ["working", "idle", "gone"]  # it waits out the PM's turn on hc facts, not `hc wait`
        events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=False, since=None), ctx=self.ctx())
        self.assertEqual([c[0] for c in self.hc.hc_calls if c[0] != "get"], ["send"])
        self.assertEqual([c[1:3] for c in self.hc.hc_calls if c[0] == "send"], [("--if", "idle")])  # not while it works
        (_, term, text), = self.sends()
        self.assertEqual(term, "t7")
        self.assertIn("(commit abc123)", text)
        self.assertIn("done; tests pass", text)
        self.assertEqual(self.delivered_offset(), self.size())
        self.hc.pm_states[:] = ["idle", "gone"]
        events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=False, since=None), ctx=self.ctx())
        self.assertEqual(len(self.sends()), 1)                       # nothing new: nothing sent
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=True, since=0), ctx=self.ctx())
        self.assertIn("done; tests pass", out.getvalue())            # a dry run prints the batch from any byte
        self.assertEqual(len(self.sends()), 1)

    def test_a_send_that_starts_no_turn_does_not_move_the_mark(self):
        self.update(self.task("a"), status="review", note="done")
        self.hc.send_reply = {}
        self.hc.pm_states[:] = ["idle", "idle", "gone"]  # it tries again while the PM runs, not 600 s
        events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=False, since=None), ctx=self.ctx())
        self.assertEqual(len(self.sends()), 2)
        self.assertEqual(self.delivered_offset(), 0)

    def test_no_pm_running_and_a_second_deliverer_send_nothing(self):
        self.update(self.task("a"), status="review", note="done")
        self.hc.hc_calls.clear()  # what the report itself looked up (who sent it); the deliverers are checked below
        lock_path = self.ctx().home.project_for(self.repo).ensure() / "deliver.lock"
        with open(lock_path, "a+") as held:
            lock_file(held)
            events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=False, since=None), ctx=self.ctx())
            unlock_file(held)
        self.assertEqual(self.hc.hc_calls, [])
        self.hc.pm_states[:] = ["gone"]
        events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=False, since=None), ctx=self.ctx())
        self.assertEqual(self.sends(), [])
        self.assertEqual(self.delivered_offset(), 0)          # it waits in the log for the PM that starts

    def test_the_pm_hook_takes_a_batch_once_and_brings_what_waits_with_the_users_words(self):
        task = self.task("a")
        self.update(task, status="blocked", note="which format?")
        start, end, items = self.pending_batch()
        batch = self.batch_text(start, end, items)
        self.be("hc:t7")
        self.assertEqual(self.hook("UserPromptSubmit", prompt=f'<hc from="t20">{batch}</hc>'), "")
        self.assertEqual(self.delivered_offset(), end)
        self.assertEqual(self.events("agent"), [])                   # the events are in the log already
        self.hook("Stop", last_assistant_message="问了用户")
        reply = self.events("pm")[-1]
        self.assertEqual((reply["after"], reply["batch"]), ("deliver", [start, end]))
        self.assertIn("repeat", self.hook("UserPromptSubmit", prompt=batch))  # the same batch again
        self.be("hc:t20")
        self.update(task, status="review", note="done after all")
        self.be("hc:t7")
        brought = self.hook("UserPromptSubmit", prompt="进展如何")
        self.assertIn("done after all", brought)                      # it rides with the user's turn
        self.assertEqual(self.delivered_offset(), self.size() - len(json.dumps(self.events()[-1], ensure_ascii=False).encode()) - 1)
        self.hook("Stop", last_assistant_message="a 做完了")
        self.assertNotIn("after", self.events("pm")[-1])
        self.assertEqual(self.pending_batch()[2], [])

    def test_a_worker_that_stops_unreported_is_reminded_then_reported_as_stalled(self):
        task = self.task("a")
        self.extra_env["CLAUDE_CODE_SESSION_ID"] = "s1"
        self.assertEqual(self.hook("Stop", background_tasks=[{"id": "b1"}]), "")   # it waits on its own work
        said = json.loads(self.hook("Stop", stop_hook_active=False))
        self.assertEqual(said["decision"], "block")
        self.assertIn(f"update {task} --status review|blocked", said["reason"])
        self.assertEqual(self.events("stall"), [])
        self.assertEqual(self.hook("Stop", stop_hook_active=True), "")
        stall, = self.events("stall")
        self.assertEqual((stall["task"], stall["wake"], stall["source"], stall["by"]), (task, True, "harness", "hc:t20"))
        self.assertEqual(self.started(), [self.repo])
        self.hook("Stop", stop_hook_active=True)
        self.assertEqual(len(self.events("stall")), 1)                # once per stall
        self.update(task, status="review", note="done")
        self.assertEqual(self.hook("Stop", stop_hook_active=False), "")  # reported: nothing to say
        self.extra_env.pop("CLAUDE_CODE_SESSION_ID", None)
        other = self.task("b", pane="hc:t21")
        self.be("hc:t21")
        self.assertEqual(self.hook("Stop"), "")                       # an agent a hook cannot continue
        self.assertEqual([e["task"] for e in self.events("stall")], [task, other])

    def test_the_pm_notices_a_worker_whose_terminal_is_gone(self):
        task = self.task("a")
        self.hc.terms["t20"] = {"state": "exited"}
        self.be("hc:t7")
        self.hook("Stop", last_assistant_message="好")
        self.hook("Stop", last_assistant_message="好")
        stall, = self.events("stall")
        self.assertEqual((stall["task"], stall["wake"]), (task, True))

    def test_notify_and_event_reach_an_app_pm_through_the_log(self):
        with contextlib.redirect_stdout(io.StringIO()):
            events_cmds.cmd_notify(argparse.Namespace(repo=self.repo, text="提问：旧版配置要不要兼容？"), ctx=self.ctx())
            for key in ("sha1:pass", "sha1:pass", "sha2:fail"):
                events_cmds.cmd_event(argparse.Namespace(repo=self.repo, text=f"CI {key}", source="ci", key=key), ctx=self.ctx())
        said, = self.events("agent")
        self.assertEqual((said["by"], said["wake"], said["text"]), ("hc:t20", True, "提问：旧版配置要不要兼容？"))
        self.assertEqual([(e["key"], e["source"], e["wake"]) for e in self.events("event")],
                         [("sha1:pass", "external:ci", True), ("sha2:fail", "external:ci", True)])
        self.assertEqual(self.sends(), [])                            # nothing is typed by the sender itself
        self.assertEqual(self.started(), [self.repo] * 3)
        text = self.batch_text(*self.pending_batch())
        self.assertIn("[session hc:t20] 提问：旧版配置要不要兼容？", text)
        self.assertIn("[external:ci hc:t20] CI sha2:fail", text)

    def test_a_message_not_yet_read_does_not_come_between_the_user_and_the_reply(self):
        conv = Conversation(self.ctx(), self.repo)
        conv.record("user", text="进展如何")
        conv.record("agent", by="hc:t20", text="ready", wake=True)
        conv.record("pm", text="a 在跑")
        conv.record("pm", text="收到 ready", after="deliver")
        self.assertEqual(Conversation(self.ctx(), self.repo).tail(), [{"user": "进展如何", "pm": "a 在跑"}])

    def test_review_without_subplan_adds_lightweight_pm_note(self):
        no_sub = self.task("nosub", branch="dev/nosub")
        self.update(no_sub, status="review", commit="aaa111", note="done; checks pass")
        has_sub = self.task("hassub", pane="hc:t21", branch="dev/hassub",
                            subplan=[{"text": "impl", "state": "done"}])
        self.be("hc:t21")
        self.update(has_sub, status="review", commit="bbb222", note="done with plan")
        manual = self.task("manual", pane="hc:t22", dispatched=False, branch="dev/manual")
        self.be("hc:t22")
        self.update(manual, status="review", commit="ccc333", note="manual session done")
        start, end, items = self.pending_batch()
        text = self.batch_text(start, end, items)
        self.assertIn("note: no subplan recorded", text)
        # Only the dispatched task without subplan gets the note (not the one with subplan or manual task).
        self.assertEqual(text.count("note: no subplan recorded"), 1)
        # Reporting itself is not blocked: all tasks reached review status.
        self.assertEqual(self.load(no_sub)["status"], "review")
        self.assertEqual(self.load(has_sub)["status"], "review")
        self.assertEqual(self.load(manual)["status"], "review")

    def test_review_with_auto_review_combined_batch_notes_missing_subplan(self):
        parent = self.task("par", branch="dev/par", commit="ccc333")
        rev = self.task("par-review", pane="hc:t25", review_of=parent, status="in_progress")
        self.entry(
            rev,
            "status=done; no blockers",
            by="hc:t25",
            status="done",
            source="worker",
            wake=True,
            review_of=parent,
            worker_commit="ccc333",
            worker_note="implemented feature",
        )
        self.clock.advance(SETTLE + 1)
        text = self.batch_text(*self.pending_batch())
        self.assertIn("note: no subplan recorded", text)
        # Once the parent has a subplan, the combined delivery omits the note.
        p = self.load(parent)
        p["subplan"] = [{"text": "step 1", "state": "done"}]
        self.save(p)
        text_with = self.batch_text(*self.pending_batch())
        self.assertNotIn("note: no subplan recorded", text_with)

    def test_a_deliverer_starts_only_for_an_app_pm(self):
        Delivery(self.ctx(), self.repo).ensure_running()
        self.register(archived=True)
        Delivery(self.ctx(), self.repo).ensure_running()
        self.assertEqual([s["args"] for s in self.procs.spawned], [["deliver", self.repo]])

    def test_what_is_news_is_decided_by_what_an_entry_did_whichever_version_wrote_it(self):
        news = {}
        for n, (slug, status) in enumerate([("moved", "in_progress"), ("followup", "review"), ("commit", "review"),
                                             ("blocked", "blocked"), ("reviewed", "done"), ("quiet", "review")]):
            news[slug] = self.task(slug, pane=f"hc:t2{n}", status=status,  # registered by the PM's dispatch
                                   log=[{"at": self.clock.now(), "by": "hc:t7", "text": f"dispatched to w{n}"}])
        t = lambda slug: f"hc:t2{list(news).index(slug)}"
        self.entry(news["moved"], "status=review; done", t("moved"), "review")                  # before 59ed668
        self.entry(news["followup"], "commit=def4567; fixed the findings", t("followup"), source="worker")  # 72f6951^
        self.entry(news["commit"], "commit=abc1234", t("commit"))                                # no source: a commit
        self.entry(news["blocked"], "more detail on the blocker", t("blocked"), source="worker")
        self.entry(news["reviewed"], "以这条为准：1. 缺测试", t("reviewed"), source="worker")      # a reviewer, again
        # An earlier `new --pane ""` from outside herdr: by "user", no pane, no source; its first entry registers it.
        handed = f"{self.name}-handed"
        self.save({"id": handed, "title": "handed", "project": self.name, "repo": self.repo, "status": "proposed",
                   "owner": "self", "base": "main", "pane": "", "created": self.clock.now(), "log": []})
        self.entry(handed, "handed to PM", "user")
        # Not news: progress and housekeeping notes (no source), an update of other fields, another session's
        # comment, the PM's entry, and a note alone from a pm.py that records no source.
        q = news["quiet"]
        self.entry(q, "half way through the second pass", t("quiet"))                           # `log`
        self.entry(q, "tab renamed t24-x -> t24-y", t("quiet"))                                 # retab
        self.entry(q, "branch=dev/quiet", t("quiet"), source="worker")                          # fields only
        self.entry(q, "a comment", "hc:t30", source="session")
        self.entry(q, "status=review; mine", "hc:t7")
        self.entry(q, "one more thing", t("quiet"))
        # A task made without a first entry: a note long after is not its registration.
        bare = self.task("bare", pane="hc:t29", status="review", created="2026-11-01 09:00")
        self.entry(bare, "a note on a task with no first entry", "hc:t29")
        self.clock.advance(SETTLE + 1)
        start, end, items = self.pending_batch()
        self.assertEqual(sorted(i["event"]["task"] for i in items),
                         sorted([news[k] for k in ("moved", "followup", "commit", "blocked", "reviewed")] + [handed]))
        self.deliver("idle")
        (_, term, text), = self.sends()
        self.assertIn("fixed the findings", text)
        self.assertIn("handed to PM", text)
        self.assertEqual(self.delivered_offset(), end)

    def test_a_note_after_a_report_does_not_take_its_place(self):
        task = self.task("a")
        self.update(task, status="review", commit="abc1234", note="做完了：测试全过")
        self.entry(task, "hc:t20 ends after 5 idle minutes (workers.close_reported)", "hc:t20")  # close_reported
        with contextlib.redirect_stdout(io.StringIO()):
            status_view.cmd_log(argparse.Namespace(id=task, text="cleaning up"), ctx=self.ctx())
        self.update(task, branch="dev/a")                                                 # no note, no commit
        (item,) = self.pending_batch()[2]
        self.assertEqual((item["event"]["text"], item["earlier"]), ("status=review, commit=abc1234; 做完了：测试全过", 0))

    def test_a_line_just_written_is_judged_once_its_task_file_is_saved(self):
        task = self.task("a")
        self.update(task, status="review", note="done", settle=False)
        start, end, items = self.pending_batch(settle=True)
        self.assertEqual((end, items), (0, []))                                       # held, not passed over
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=True, since=None), ctx=self.ctx())
        self.assertIn("done", out.getvalue())                                         # a dry run shows it
        self.be("hc:t7")
        self.assertNotIn("done", self.hook("UserPromptSubmit", prompt="进展如何"))     # nor taken into a turn
        self.assertEqual(self.delivered_offset(), 0)
        self.clock.advance(SETTLE + 1)
        start, end, items = self.pending_batch(settle=True)
        self.assertEqual([i["event"]["task"] for i in items], [task])

    def test_a_worker_without_hooks_that_stops_unreported_is_a_stall_once_per_stop(self):
        task = self.task("a", worker={"kind": "agy", "profile": "neon"})
        working = {"state": "live", "status": {"state": "working"}, "turn": 0}
        stopped = {"state": "live", "status": {"state": "idle"}, "turn": 1}
        self.hc.terms["t20"] = [working, stopped, stopped, stopped]
        self.deliver("working", "working", "working", "working")
        stall, = self.events("stall")
        self.assertEqual((stall["task"], stall["key"], stall["wake"]), (task, "t20:idle:1", True))
        self.assertIn("without hooks", stall["text"])
        self.assertEqual(self.sends(), [])                           # the PM was working all along
        self.hc.terms["t20"] = [stopped, stopped]                    # a deliverer started again: no repeat
        self.deliver("working", "working", "working")
        self.assertEqual(len(self.events("stall")), 1)
        self.hc.terms["t20"] = [{**working, "turn": 1}, {**stopped, "turn": 2}, {**stopped, "turn": 2}]
        self.deliver("working", "working", "working", "working")     # sent on, it stopped again
        self.assertEqual([e["key"] for e in self.events("stall")], ["t20:idle:1", "t20:idle:2"])
        self.hc.terms["t20"] = [{**stopped, "turn": 3}]
        self.update(task, status="review", note="done after all")    # reported: no stall any more
        self.deliver("working", "working", "working")
        self.assertEqual(len(self.events("stall")), 2)

    def test_a_stall_is_a_stop_after_this_rounds_work_was_handed_over(self):
        idle = lambda turn: {"state": "live", "status": {"state": "idle"}, "turn": turn}
        working = lambda turn: {"state": "live", "status": {"state": "working"}, "turn": turn}
        task = self.task("a", status="review", worker={"kind": "agy"})
        self.hc.terms["t20"] = [idle(3)]                                   # it reported after its third turn
        self.be("hc:t7")
        self.update(task, status="in_progress", note="审查发回：1. 补测试")  # the PM sends it back, as §4 says
        self.assertEqual(self.load(task)["round"]["turn"], 3)
        self.be("hc:t20")
        self.deliver("working", "working", "working", "working")           # the findings have not reached it yet
        self.assertEqual(self.events("stall"), [])
        self.hc.terms["t20"] = [working(3), idle(4), idle(4)]              # it worked on them, and stopped unreported
        self.deliver("working", "working", "working", "working")
        stall, = self.events("stall")
        self.assertEqual(stall["key"], "t20:idle:4")

    def test_a_worker_starting_up_is_not_judged_until_its_brief_is_handed_over(self):
        task = self.task("a", worker={"kind": "agy"})
        stalls = StallWatcher(self.ctx())
        start = self.load(task)
        stalls.round_starts(start, "t20", handed=False)                    # as dispatch saves it before the brief
        self.save(start)
        for state in ({"state": "live", "status": {"state": "idle"}, "turn": 1},       # a startup turn
                      {"state": "live", "status": {"state": "blocked"}, "turn": 1}):   # a startup dialog
            self.hc.terms["t20"] = [state]
            self.deliver("working", "working", "working")
        self.assertEqual(self.events("stall"), [])
        self.hc.terms["t20"] = [{"state": "live", "status": {"state": "idle"}, "turn": 1}]
        stalls.round_handed(task, "t20")                                   # the brief is sent: base 1
        self.deliver("working", "working", "working")
        self.assertEqual(self.events("stall"), [])
        self.hc.terms["t20"] = [{"state": "live", "status": {"state": "idle"}, "turn": 2}]
        self.deliver("working", "working", "working")
        self.assertEqual([e["key"] for e in self.events("stall")], ["t20:idle:2"])
        # A start that never handed its work over is watched after ROUND_START, counting from what it saw.
        late = self.load(task)
        late["round"] = {"terminal": "t20", "at": "2026-01-01 00:00", "turn": None}
        self.save(late)
        self.assertEqual(stalls.round_base(late, "t20", {"turn": 5}, {}), 5)
        self.assertIsNone(stalls.round_base(start, "t20", {"turn": 5}, {}))
        self.assertEqual(stalls.round_base(start, "t99", {"turn": 7}, {}), 7)  # a round of another terminal

    def test_the_deliverer_follows_the_pm_before_it_looks_at_it_and_sends_by_its_status(self):
        self.update(self.task("a"), status="review", note="done")
        looks = FakeChangeWaiter(on_wait=lambda dt: self.clock.advance(min(max(float(dt), 0.0), 5.0)))
        seen: list[set[str]] = []
        self.hc.waiter_override = looks

        def _on_get(call):
            if call[:2] == ("get", "t7"):
                seen.append(set(looks.terminals or ()))

        self.hc.on_get = _on_get
        # A PM whose turn ended while nobody looked (done): hc's --if knows idle and working only; sent as it is.
        self.deliver("done")
        self.assertIn("t7", seen[0])                                      # followed already at the first look
        self.assertEqual([c[1] for c in self.hc.hc_calls if c[0] == "send"], ["t7"])
        self.assertEqual(self.delivered_offset(), self.size())
        # An idle PM: --if idle. The user sent a draft meanwhile (status_mismatch, nothing typed): not delivered.
        self.update(self.task("b"), status="review", note="done too")
        self.hc.hc_calls.clear()
        self.hc.send_reply = lambda args: None
        self.deliver("idle", "idle")
        self.assertEqual([c[1:3] for c in self.hc.hc_calls if c[0] == "send"], [("--if", "idle")] * 2)
        self.assertLess(self.delivered_offset(), self.size())

    def test_a_worker_that_fails_at_once_on_its_brief_counts_from_before_the_brief(self):
        self.hc.terms["t20"] = [{"state": "live", "status": {"state": "idle"}, "turn": 0}]
        self.hc.send_reply = lambda args: (
            self.hc.terms.update(t20=[{"state": "live", "status": {"state": "idle"}, "turn": 1}])
            or {"started": True}
        )
        task, seen = self.task("a", worker={"kind": "agy"}), {}
        self.assertTrue(send_when_ready_for(self.ctx(), "t20", "the brief", tries=3, pause=0, seen=seen))
        self.assertEqual(seen, {"turn": 0})
        stalls = StallWatcher(self.ctx())
        stalls.round_sent(task, "t20", True, seen)
        self.assertEqual(self.load(task)["round"]["turn"], 0)
        stalls.round_sent(task, "t20", False, {"turn": 0})                # given up: the count now
        self.assertEqual(self.load(task)["round"]["turn"], 1)
        stalls.round_sent(task, "t20", True, seen)
        self.deliver("working", "working", "working")
        self.assertEqual([e["key"] for e in self.events("stall")], ["t20:idle:1"])

    def test_findings_are_sent_back_in_one_step_and_the_round_counts_from_before_them(self):
        task = self.task("a", status="review", worker={"kind": "agy"})
        self.hc.terms["t20"] = [{"state": "live", "status": {"state": "idle"}, "turn": 3}]
        self.be("hc:t7")
        # From a PM terminal, --send queues asynchronously by default so PM never blocks.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger_cmds.cmd_update(argparse.Namespace(id=task, keep=False, status="in_progress", note="1. 补测试", send=True), ctx=self.ctx())
        async_spawns = [s for s in self.procs.spawned if s["args"][:1] == ["_drain-endpoint"]]
        self.assertEqual(len(async_spawns), 1)
        self.assertEqual(async_spawns[0]["args"][1], "t20")
        self.assertEqual(queued_sends(self.ctx()), [("t20", "[from hc:t7] 1. 补测试")])
        self.assertEqual((self.load(task)["status"], self.load(task)["round"]["turn"]), ("in_progress", 3))
        self.assertIn("queued async send to hc:t20", out.getvalue())
        # With --wait, it delivers synchronously and updates round_handed.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger_cmds.cmd_update(argparse.Namespace(
                id=task, keep=False, status="in_progress", note="1b. 同步测试", send=True, wait=True,
            ), ctx=self.ctx())
        # One typist per terminal: the note queued above goes in first, then this one; each carries its envelope
        # anchor (`[from hc:t7 #env_…]`).
        unanchored = [(k, t, re.sub(r" #env_[0-9a-f]+_[0-9a-f]+\]", "]", m)) for k, t, m in self.sends()]
        self.assertEqual(unanchored[-2:], [("send", "t20", "[from hc:t7] 1. 补测试"),
                                           ("send", "t20", "[from hc:t7] 1b. 同步测试")])
        self.assertIn("sent to hc:t20", out.getvalue())
        # It cannot take it now (a prompt holds it) with --wait: recorded, not sent, and how to send it by hand.
        self.hc.send_reply = lambda args: {"error": {"kind": "blocked", "message": "t20 is blocked"}}
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            ledger_cmds.cmd_update(argparse.Namespace(id=task, keep=False, note="2. 再看一下", send=True, wait=True), ctx=self.ctx())
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("pm.py send t20", out.getvalue())
        self.assertEqual(self.load(task)["log"][-1]["text"], "2. 再看一下")
        with self.assertRaises(SystemExit):
            ledger_cmds.cmd_update(argparse.Namespace(id=task, keep=False, note=None, status="in_progress", send=True), ctx=self.ctx())

    def test_hooked_workers_are_left_to_their_hook_until_their_terminal_goes_or_a_prompt_holds_them(self):
        a = self.task("a", worker={"kind": "claude"})
        b = self.task("b", pane="hc:t21", worker={"kind": "codex"})
        idle = {"state": "live", "status": {"state": "idle"}, "turn": 3}
        self.hc.terms.update(t20=[idle], t21=[idle])
        self.deliver("working", "working", "working")
        self.assertEqual(self.events("stall"), [])                    # Claude waiting on its own background work
        self.hc.terms.update(t20=[{"error": {"kind": "not_found"}}],
                             t21=[{"state": "live", "status": {"state": "blocked", "kind": "permission"}, "turn": 3}])
        self.deliver("working", "working", "working")
        self.assertEqual(sorted((e["task"], e["key"]) for e in self.events("stall")),
                         [(a, "t20:gone"), (b, "t21:blocked:3")])
        # Under a launcher shell an agent that exits leaves its terminal live: it reported a status and has none.
        c = self.task("c", pane="hc:t22", worker={"kind": "claude"})
        self.hc.terms["t22"] = [{"state": "live", "status": None, "reported": True, "turn": 4}]
        self.deliver("working", "working", "working")
        self.assertIn((c, "t22:gone"), [(e["task"], e["key"]) for e in self.events("stall")])
        stall_b = next(e["text"] for e in self.events("stall") if e["task"] == b)
        self.assertIn(f"pm.py triage {b}", stall_b)
        self.assertNotIn("hc read t21", stall_b)

    def test_a_report_during_a_rotation_reaches_the_new_pm_once_its_first_turn_is_over(self):
        task = self.task("a")
        self.update(task, status="review", note="done while the PM rotated")
        self.register(pane="hc:t8", terminal="t8", previous={"pane": "hc:t7", "terminal": "t7"})
        next_path = self.ctx().home.project_for(self.repo).ensure() / "next-session.json"
        next_path.write_text(json.dumps({"at": self.clock.now()}))
        self.hc.terms["t8"] = [{"state": "live", "status": {"state": "idle"}, "turn": 0},     # swap queued in next-session.json
                               {"state": "live", "status": {"state": "working"}, "turn": 0},  # new session starting
                               {"state": "live", "status": {"state": "idle"}, "turn": 1},     # ready to deliver
                               {"state": "finished"}]
        left: list[int] = []
        self.hc.send_reply = lambda args: left.append(len(self.hc.terms["t8"])) or {"started": True}

        def on_get(call):
            if call == ("get", "t8") and len(self.hc.terms["t8"]) == 3:
                next_path.unlink(missing_ok=True)  # seat popped next-session.json as the new session started

        self.hc.on_get = on_get
        c = self.ctx()
        c.deliver_holds = (lambda repo: seat_mod._next_session_ready_impl(repo, ctx=c),)
        events_cmds.cmd_deliver(argparse.Namespace(project=self.repo, dry_run=False, since=None), ctx=c)
        self.assertFalse(next_path.exists())
        self.assertEqual(left, [1])                                    # sent after the swap finished, not before
        (_, term, text), = self.sends()
        self.assertEqual(term, "t8")
        self.assertIn("done while the PM rotated", text)
        self.assertEqual(self.delivered_offset(), self.size())

    def test_a_batch_sent_to_a_pm_that_was_rotated_out_meanwhile_is_sent_again(self):
        self.update(self.task("a"), status="review", note="done")

        def send(args):
            if args[1] == "t7":  # the send waited for a draft; the PM rotated in the meantime
                self.register(pane="hc:t8", terminal="t8", previous={"pane": "hc:t7", "terminal": "t7"})
            return {"started": True}

        self.hc.send_reply = send
        self.hc.terms["t8"] = [{"state": "live", "status": {"state": "idle"}, "turn": 2}, {"state": "finished"}]
        self.deliver("idle")
        self.assertEqual([c[1] for c in self.sends()], ["t7", "t8"])
        self.assertEqual(self.delivered_offset(), self.size())

    def test_a_pm_without_a_mark_gets_what_came_since_it_was_claimed(self):
        old = self.task("old", status="review")
        Conversation(self.ctx(), self.repo).record(
            "thread", task=old, title="old", status="review", by="hc:t20",
            text="status=review; long ago", at="2026-01-01 10:00:00",
        )
        claimed = self.clock.datetime_now() - datetime.timedelta(minutes=1)
        self.register(claimed=claimed.strftime("%Y-%m-%d %H:%M"))
        self.update(self.task("new"), status="review", note="since the claim")
        self.deliver("idle")
        (_, _, text), = self.sends()
        self.assertIn("since the claim", text)
        self.assertNotIn("long ago", text)

    def test_a_new_desktop_pm_starts_its_mark_at_the_end_of_the_log_and_its_deliverer(self):
        self.update(self.task("a"), status="review", note="from before this PM")
        self.ctx().home.registration(project_slug(self.repo)).unlink()
        self.hc.terms["t9"] = {"state": "live", "labels": {}, "status": {"state": "idle"}}
        with contextlib.redirect_stdout(io.StringIO()):
            manager_cmds.cmd_claim(argparse.Namespace(repo=self.repo, pane="hc:t9", kind="claude"), ctx=self.ctx())
        self.assertEqual(self.delivered_offset(), self.size())
        self.assertEqual(self.started()[-1], self.repo)

    def test_the_deliverer_leaves_when_the_pm_is_gone_and_hands_over_after_an_install(self):
        self.update(self.task("a"), status="review", note="done")
        self.register(archived="2026-11-21")
        self.procs.spawned.clear()
        self.deliver("idle", "idle")
        self.assertEqual(self.sends(), [])                                 # archived: no PM to tell
        self.register()
        marks = iter([("old",), ("old",), ("new",)])
        self.procs.mark_fn = lambda: next(marks, ("new",))
        try:
            self.deliver("working", "working", "working")
        finally:
            self.procs.mark_fn = None
        self.assertEqual(self.started(), [self.repo])                      # the new copy takes over
        self.assertEqual(self.sends(), [])

    def test_a_running_deliverer_is_not_started_twice(self):
        self.procs.env["HC_TERMINAL_ID"] = "t20"
        lock_path = self.ctx().home.project_for(self.repo).ensure() / "deliver.lock"
        with open(lock_path, "a+") as held:
            lock_file(held)
            Delivery(self.ctx(), self.repo).ensure_running()
            unlock_file(held)
        Delivery(self.ctx(), self.repo).ensure_running()
        spawn, = self.procs.spawned
        self.assertEqual(spawn["args"], ["deliver", self.repo])
        self.assertEqual(spawn["cwd"], str(self.ctx().home.root))          # no worktree stays in use
        self.assertNotIn("HC_TERMINAL_ID", spawn["env"])

    def test_the_pm_hook_starts_a_deliverer_and_a_desktop_pm_does_not_wait(self):
        task = self.task("a")
        self.be("hc:t7")
        self.hook("Stop", last_assistant_message="好")
        self.assertIn(self.repo, self.started())
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            workers_cmds.cmd_wait(argparse.Namespace(id=task, timeout=60), ctx=self.ctx())
        self.assertEqual(stop.exception.code, 4)
        self.assertIn("nothing to wait for", out.getvalue())
        self.assertFalse((self.ctx().home.waits / f"{task}.json").exists())

    def test_deliverer_advancing_cursor_before_hook_does_not_false_repeat(self):
        task = self.task("a")
        self.update(task, status="review", commit="abc123", note="done; tests pass")
        self.deliver("idle")
        (_, _, batch), = self.sends()
        end = self.size()
        self.assertEqual(self.delivered_offset(), end)
        self.assertEqual(self.received_ranges(), [])

        # Even if a non-news log line advances the outbound cursor further before the hook runs, still no false repeat.
        with contextlib.redirect_stdout(io.StringIO()):
            status_view.cmd_log(argparse.Namespace(id=task, text="housekeeping note"), ctx=self.ctx())
        self.clock.advance(SETTLE + 1)
        self.deliver("idle")
        self.assertGreater(self.delivered_offset(), end)
        self.assertEqual(self.received_ranges(), [])

        # First arrival at the PM hook: no repeat warning, receipt recorded, turn-cause set.
        self.be("hc:t7")
        self.assertEqual(self.hook("UserPromptSubmit", prompt=batch), "")
        self.assertEqual(self.received_ranges(), [[0, end]])
        self.assertEqual(Conversation(self.ctx(), self.repo).turn_cause(), {"after": "deliver", "batch": [0, end]})
        self.hook("Stop", last_assistant_message="开始审查")
        reply = self.events("pm")[-1]
        self.assertEqual((reply["after"], reply["batch"]), ("deliver", [0, end]))

        # Second arrival of the exact same batch: genuine repeat IS reported, and turn-cause stays deliver.
        self.assertIn("repeat", self.hook("UserPromptSubmit", prompt=batch))
        self.assertEqual(Conversation(self.ctx(), self.repo).turn_cause(), {"after": "deliver", "batch": [0, end]})

    def test_bring_pending_and_deliver_race_no_false_repeat_and_real_repeat_caught(self):
        a, b = self.task("a", pane="hc:t20"), self.task("b", pane="hc:t21")
        self.be("hc:t20")
        self.update(a, status="review", note="a done")
        self.deliver("idle")
        (_, _, batch1), = self.sends()
        end1 = self.size()
        self.assertEqual(self.delivered_offset(), end1)

        # User prompt with no new events yet: bring_pending must not mark [0, end1) received.
        self.be("hc:t7")
        self.assertEqual(self.hook("UserPromptSubmit", prompt="先看看"), "")
        self.assertEqual(self.received_ranges(), [])

        # Another event arrives and rides with the user's next turn via bring_pending: only [end1, end2) is acked.
        self.be("hc:t21")
        self.update(b, status="blocked", note="need input")
        end2 = self.size()
        self.be("hc:t7")
        brought = self.hook("UserPromptSubmit", prompt="现在呢")
        self.assertIn("need input", brought)
        self.assertEqual(len(self.received_ranges()), 1)
        self.assertEqual(self.received_ranges()[0][1], end2)
        self.assertGreaterEqual(self.received_ranges()[0][0], end1)

        # Now batch1 [0, end1) finally reaches UserPromptSubmit: first receipt, no false repeat.
        self.assertEqual(self.hook("UserPromptSubmit", prompt=batch1), "")
        self.assertIn("repeat", self.hook("UserPromptSubmit", prompt=batch1))

        # Case 2: a batch whose events were ALREADY delivered via bring_pending arrives late via hc send -> repeat.
        c = self.task("c", pane="hc:t22")
        self.be("hc:t22")
        self.update(c, status="review", note="c done")
        start_c, end_c, items_c = self.pending_batch()
        late_batch_c = self.batch_text(start_c, end_c, items_c)
        self.be("hc:t7")
        self.assertIn("c done", self.hook("UserPromptSubmit", prompt="c 好了吗"))
        self.assertIn("repeat", self.hook("UserPromptSubmit", prompt=late_batch_c))

    def test_superset_retry_batch_is_not_suppressed_but_covered_subrange_is_repeat(self):
        a, b = self.task("a", pane="hc:t20"), self.task("b", pane="hc:t21")
        self.be("hc:t20")
        self.update(a, status="review", note="first")
        s1, e1, items1 = self.pending_batch(offset=0)
        b1 = self.batch_text(s1, e1, items1)
        self.be("hc:t21")
        self.update(b, status="review", note="second")
        s2, e2, items2 = self.pending_batch(offset=0)
        b2 = self.batch_text(s2, e2, items2)

        self.be("hc:t7")
        self.assertEqual(self.hook("UserPromptSubmit", prompt=b1), "")
        self.assertEqual(self.hook("UserPromptSubmit", prompt=b2), "")  # carries new event b
        self.assertEqual(self.received_ranges(), [[0, e2]])
        # Now both b1 (subrange) and b2 (exact) are repeats.
        self.assertIn("repeat", self.hook("UserPromptSubmit", prompt=b1))
        self.assertIn("repeat", self.hook("UserPromptSubmit", prompt=b2))

    def test_pasted_content_wrapped_batches_are_recognized_and_deduplicated(self):
        task = self.task("a")
        self.update(task, status="review", note="fixed <pasted_content>x</pasted_content> and (999-1000) bug")
        self.deliver("idle")
        (_, _, batch), = self.sends()
        end = self.size()
        self.be("hc:t7")

        wrapped = f'\n\n<pasted_content id="898f">\n{batch}\n</pasted_content id="898f">\n'
        self.assertEqual(self.hook("UserPromptSubmit", prompt=wrapped), "")
        self.assertEqual(self.received_ranges(), [[0, end]])
        self.assertEqual(Conversation(self.ctx(), self.repo).turn_cause(), {"after": "deliver", "batch": [0, end]})
        self.assertEqual(self.events("user"), [])
        self.assertEqual(self.events("agent"), [])

        for dup in (
            f'\n\n<pasted_content id="aef2">\n<hc from="t13q dev-pm-skill">{batch}</hc>\n</pasted_content id="aef2">\n',
            f'<hc from="t20"><pasted_content id="4cb2">\n{batch}\n</pasted_content id="4cb2"></hc>',
            f'<pasted_content>\n{batch}\n</pasted_content>',
            f'[Pasted text #1 +25 lines]\n<pasted_content id="898f">\n{batch}\n</pasted_content id="898f">',
        ):
            self.assertIn("repeat", self.hook("UserPromptSubmit", prompt=dup), dup)

        self.assertEqual(
            batch_stretch('\n\n<pasted_content id="898f">\n1 条事件 (1879333-1879811)\nbody (99-100)\n</pasted_content id="898f">\n'),
            (1879333, 1879811))
        self.assertIsNone(batch_stretch("header without range\nbody has (10-20)"))
        for two in (
            "<pasted_content>first</pasted_content> and <pasted_content>second</pasted_content>",
            '<pasted_content id="a1">first</pasted_content id="a1"> and <pasted_content id="b2">second</pasted_content id="b2">',
        ):
            self.assertEqual(unwrap_pasted(two), two)

    def test_received_ranges_cap_and_log_replacement_reset(self):
        ranges: list[list[int]] = []
        for i in range(MAX_RECEIVED_RANGES + 20):
            ranges = _add_range(ranges, i * 10, i * 10 + 5)
        self.assertEqual(len(ranges), MAX_RECEIVED_RANGES)
        self.assertEqual(ranges[0][0], 0)
        self.assertTrue(_is_covered(ranges, 0, 5))
        self.assertTrue(_is_covered(ranges, (MAX_RECEIVED_RANGES + 19) * 10, (MAX_RECEIVED_RANGES + 19) * 10 + 5))

        task = self.task("a")
        self.update(task, status="review", note="before log reset " + "x" * 200)
        s1, e1, items1 = self.pending_batch(offset=0)
        self.be("hc:t7")
        self.assertEqual(self.hook("UserPromptSubmit", prompt=self.batch_text(s1, e1, items1)), "")
        self.assertEqual(self.received_ranges(), [[0, e1]])
        log_path = self.ctx().home.project_for(self.repo).conversation
        log_path.write_text("", encoding="utf-8")
        self.be("hc:t20")
        self.update(task, status="blocked", note="after reset")
        s2, e2, items2 = self.pending_batch()
        self.assertLess(e2, e1)
        self.be("hc:t7")
        self.assertEqual(self.hook("UserPromptSubmit", prompt=self.batch_text(s2, e2, items2)), "")
        self.assertEqual(self.received_ranges(), [[0, e2]])


class TaskDependencies(unittest.TestCase):
    """Task dependencies (--depends-on), derived readiness, PM reminder events, and handover/status/state visibility."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-dep-home-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo_dir = self.base / "pm-dep-repo"
        self.repo_dir.mkdir()
        self.git = GitRepo(worktree_base=self.base / "worktrees")
        self.repo = self.git.project_root(str(self.repo_dir))
        for cmd in (["init", "-q", "-b", "main"],
                    ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", "-C", self.repo, *cmd], check=True)
        self.name = Path(self.repo).name
        self.slug = project_slug(self.repo)
        self.clock = FakeClock()
        self.hc = FakeHc(clock=self.clock)
        self.tui = FakeTui(agents=[], server_ok=False)
        self.procs = FakeProcs(make_ctx(self.base).home, env={"PM_HOME": str(self.base / "ledger")})
        self.ctx = self._make_ctx()
        self.cfg_path = self.ctx.home.config

    def _make_ctx(self, *, pane: str = "", hc: FakeHc | None = None):
        c = make_ctx(
            self.base,
            pane=pane,
            hc=hc if hc is not None else self.hc,
            tui=self.tui,
            git=self.git,
            procs=self.procs,
            clock=self.clock,
            out=StdOutput(),
        )
        c.seat_alive = lambda repo, rec, info: True
        c.deliver_watchers = (
            DeliverWatcher(name="deps", terminals=None, look=DependencyWatcher(c).look),
        )
        c.caller = Caller(c)
        return c

    def register_hc_pm(self, term: str = "t1"):
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        rec = {"name": pm_name(self.repo), "project": self.name, "repo": self.repo,
               "pane": f"hc:{term}", "runtime": "hc", "terminal": term, "agent": "claude"}
        self.ctx.home.registration(self.slug).write_text(json.dumps(rec))
        return rec

    def new_task(self, title: str, **kw):
        args = argparse.Namespace(
            title=title, repo=self.repo, status=kw.pop("status", "in_progress"),
            owner=kw.pop("owner", "pm"), workspace=kw.pop("workspace", ""), pane=kw.pop("pane", ""),
            agent=kw.pop("agent", None), branch=kw.pop("branch", None), worktree=kw.pop("worktree", None),
            base=kw.pop("base", "main"), brief=kw.pop("brief", None), slug=kw.pop("slug", None),
            note=kw.pop("note", None), parent=kw.pop("parent", None), depends_on=kw.pop("depends_on", None),
            option=kw.pop("option", None), why=kw.pop("why", None), recommend=kw.pop("recommend", False),
            plan=kw.pop("plan", None), step=kw.pop("step", None), outer_plan=kw.pop("outer_plan", None),
            subplan=kw.pop("subplan", None), no_review=kw.pop("no_review", False),
        )
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            tid = ledger_cmds.cmd_new(args, ctx=self.ctx)
        return tid, err.getvalue()

    def update_task(self, tid: str, **kw):
        ns = {f: None for f in FIELDS + ["note"]}
        ns.update(id=tid, depends_on=None, option=None, why=None, recommend=False, keep=False,
                  send=False, ask=False, plan=None, step=None, outer_plan=None, subplan=None, no_review=False)
        ns.update(kw)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ledger_cmds.cmd_update(argparse.Namespace(**ns), ctx=self.ctx)
        return out.getvalue(), err.getvalue()

    def load(self, tid: str) -> dict:
        return Ledger(self.ctx).load(tid).raw

    def test_new_update_incremental_edit_and_cycle_validation(self):
        a_id, _ = self.new_task("Task A", slug="a")
        b_id, _ = self.new_task("Task B", slug="b")
        c_id, _ = self.new_task("Task C", slug="c")

        # Comma-separated + repeated --depends-on + deduplication
        x_id, err = self.new_task("Task X", status="proposed", slug="x", depends_on=[f"{a_id}, {b_id}", a_id])
        self.assertEqual(err, "")
        self.assertEqual(self.load(x_id)["depends_on"], [a_id, b_id])

        # Incremental +add / -remove and full replace / clear
        self.update_task(x_id, depends_on=[f"+{c_id},-{a_id}"])
        self.assertEqual(self.load(x_id)["depends_on"], [b_id, c_id])
        self.update_task(x_id, depends_on=[a_id])
        self.assertEqual(self.load(x_id)["depends_on"], [a_id])
        self.update_task(x_id, depends_on=[""])
        self.assertNotIn("depends_on", self.load(x_id))

        # Validation errors: nonexistent task, invalid id, mixing +/- with plain ids, self-dep, 2- and 3-node cycles
        with self.assertRaises(SystemExit):
            self.new_task("Bad1", status="proposed", depends_on=["no-such-task"])
        with self.assertRaises(SystemExit):
            self.new_task("Bad2", status="proposed", depends_on=["../evil"])
        with self.assertRaises(SystemExit):
            self.update_task(x_id, depends_on=[f"+{a_id},{b_id}"])
        with self.assertRaises(SystemExit):
            self.update_task(a_id, depends_on=[a_id])
        self.update_task(b_id, depends_on=[a_id])
        with self.assertRaises(SystemExit):
            self.update_task(a_id, depends_on=[b_id])
        self.update_task(c_id, depends_on=[b_id])
        with self.assertRaises(SystemExit):
            self.update_task(a_id, depends_on=[c_id])

        # Already-met dependencies print a stderr hint on creation without polluting stdout
        self.update_task(a_id, status="done")
        d_id, d_err = self.new_task("Task D", status="proposed", slug="d", depends_on=[a_id])
        self.assertIn("already met", d_err)
        self.assertEqual(self.load(d_id)["deps_notified"], f"ready:{a_id}")

    def test_ready_event_on_done_and_multi_dep_gate_and_dedup(self):
        self.register_hc_pm("t1")
        a_id, _ = self.new_task("Feature A", slug="a")
        b_id, _ = self.new_task("Feature B", slug="b")
        x_id, _ = self.new_task("Followup X", status="proposed", slug="x",
                                brief="/tmp/brief-x.md", depends_on=[f"{a_id},{b_id}"])

        # Completing only A does not fire ready event yet
        self.update_task(a_id, status="done", note="A done")
        deps_evs = [e for e in Conversation(self.ctx, self.repo).events()
                    if e.get("type") == "event" and e.get("source") == "deps"]
        self.assertEqual(deps_evs, [])

        # Completing B unlocks X and emits exactly one waking deps event naming X and its brief
        self.update_task(b_id, status="merged", note="B merged")
        deps_evs = [e for e in Conversation(self.ctx, self.repo).events()
                    if e.get("type") == "event" and e.get("source") == "deps"]
        self.assertEqual(len(deps_evs), 1)
        ev = deps_evs[0]
        self.assertEqual(ev["task"], x_id)
        self.assertTrue(ev["wake"])
        self.assertIn("Followup X", ev["text"])
        self.assertIn("/tmp/brief-x.md", ev["text"])
        self.assertEqual(ev["brief"], "/tmp/brief-x.md")

        # Re-running reconcile is idempotent (no duplicate event)
        self.assertEqual(DependencyWatcher(self.ctx).reconcile(self.repo), [])
        deps_evs2 = [e for e in Conversation(self.ctx, self.repo).events()
                     if e.get("type") == "event" and e.get("source") == "deps"]
        self.assertEqual(len(deps_evs2), 1)

        # Delivered batch includes the deps event; once X is dispatched (in_progress), pending_batch drops stale event
        d = Delivery(self.ctx, self.repo, settle=0)
        _, _, items = d.pending_batch(offset=0)
        self.assertTrue(any(i["event"].get("source") == "deps" and i["event"].get("task") == x_id for i in items))
        self.update_task(x_id, status="in_progress")
        _, _, items_after = d.pending_batch(offset=0)
        self.assertFalse(any(i["event"].get("source") == "deps" and i["event"].get("task") == x_id for i in items_after))

    def test_ready_event_on_land_with_post_merge_steps_and_no_dup_on_done(self):
        self.register_hc_pm("t1")
        wt = self.base / "pm-dep-wt"
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", "-b", "dev/feat", str(wt), "main"], check=True)
        (wt / "feat.txt").write_text("hi\n")
        subprocess.run(["git", "-C", str(wt), "add", "feat.txt"], check=True)
        subprocess.run(["git", "-C", str(wt), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "feat"], check=True)
        vfile = self.ctx.home.project_for(self.repo).verify
        vfile.parent.mkdir(parents=True, exist_ok=True)
        vfile.write_text(f'"{sys.executable}" -c "pass"\n' if os.name == "nt" else "true\n")

        a_id, _ = self.new_task(
            "Landable A", status="review", slug="land-a", branch="dev/feat", worktree=str(wt),
            plan=["Implement @work", "Merge into main @merge", "Install on MBP @custom"],
        )
        x_id, _ = self.new_task("After Land X", status="proposed", slug="after-x",
                                brief="/tmp/after-x.md", depends_on=[a_id])

        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_land(argparse.Namespace(id=a_id, keep=True, message=None, timeout=60), ctx=self.ctx)
        a_rec = self.load(a_id)
        self.assertEqual(a_rec["status"], "in_progress")
        self.assertTrue(a_rec.get("landed"))
        deps_evs = [e for e in Conversation(self.ctx, self.repo).events()
                    if e.get("type") == "event" and e.get("source") == "deps"]
        self.assertEqual(len(deps_evs), 1)
        self.assertEqual(deps_evs[0]["task"], x_id)
        self.assertIn("landed", deps_evs[0]["text"])

        # Finishing post-merge steps (status=done) must NOT fire a duplicate event
        self.update_task(a_id, status="done", note="installed on MBP")
        deps_evs2 = [e for e in Conversation(self.ctx, self.repo).events()
                     if e.get("type") == "event" and e.get("source") == "deps"]
        self.assertEqual(len(deps_evs2), 1)

    def test_abandoned_dependency_warns_pm_and_marks_broken(self):
        self.register_hc_pm("t1")
        a_id, _ = self.new_task("Spike A", slug="spike-a")
        x_id, _ = self.new_task("Build on A", status="proposed", slug="build-a", depends_on=[a_id])

        self.update_task(a_id, status="abandoned", note="not needed")
        deps_evs = [e for e in Conversation(self.ctx, self.repo).events()
                    if e.get("type") == "event" and e.get("source") == "deps"]
        self.assertEqual(len(deps_evs), 1)
        self.assertEqual(deps_evs[0]["task"], x_id)
        self.assertIn("abandoned", deps_evs[0]["text"].lower())

        st = state_view.dash_state(ctx=self.ctx)
        by_id = {t["id"]: t for t in st["tasks"]}
        self.assertFalse(by_id[x_id]["ready"])
        self.assertTrue(by_id[x_id]["deps_broken"])
        self.assertNotIn(x_id, st["ready_tasks"])

    def test_visibility_in_status_handover_show_and_state_bilingual(self):
        self.register_hc_pm("t1")
        parent_id, _ = self.new_task("Project Interfaces Plan", slug="plan-parent")
        done_id, _ = self.new_task("at-mention", slug="at-mention", parent=parent_id)
        ready_id, _ = self.new_task("H: Change View", status="proposed", slug="proj-h",
                                    parent=parent_id, brief="/tmp/h.md", depends_on=[done_id])
        wait_id, _ = self.new_task("I: Project Search", status="proposed", slug="proj-i",
                                   parent=parent_id, brief="/tmp/i.md", depends_on=[ready_id])
        self.update_task(done_id, status="merged")
        # Dependency-free `proposed` task: ordinary Todo, NOT pinned in "Ready to dispatch" and NOT ready=True
        todo_id, _ = self.new_task("Plain Todo Item", status="proposed", slug="plain-todo")
        # Legacy task without `depends_on`
        legacy_id = f"{self.name}-legacy-run"
        Ledger(self.ctx).save({"id": legacy_id, "title": "Legacy Active", "project": self.name, "repo": self.repo,
                               "status": "in_progress", "owner": "pm", "base": "main",
                               "created": self.clock.now(), "log": []})

        with contextlib.redirect_stdout(io.StringIO()):
            memory_cmds.cmd_decide(type("A", (), {"repo": self.repo, "text": "Keep list clean", "quote": "Keep list clean"}), ctx=self.ctx)
        (self.ctx.home.project_for(self.repo).ensure() / "handover.md").write_text("User is checking the board.\n")

        # 1. Handover (English): "Ready to dispatch" pinned BEFORE Notes / Open work, listing ONLY dep-met proposed
        ho_out = io.StringIO()
        with contextlib.redirect_stdout(ho_out):
            manager_cmds.cmd_handover(argparse.Namespace(repo=self.repo, turns=4, full=False, compact=False), ctx=self.ctx)
        ho = ho_out.getvalue()
        self.assertIn("## Ready to dispatch (1)", ho)
        ready_sec = ho[ho.index("## Ready to dispatch"):ho.index("## ", ho.index("## Ready to dispatch") + 1)]
        self.assertIn(ready_id, ready_sec)
        self.assertNotIn(todo_id, ready_sec)  # plain Todo is NOT pinned in Ready to dispatch
        self.assertIn(todo_id, ho[ho.index("## Open work"):])  # still listed as ordinary proposed in Open work
        self.assertLess(ho.index("## Ready to dispatch"), ho.index("## Open work"))
        self.assertLess(ho.index("## Ready to dispatch"), ho.index("## Notes from the previous PM"))
        self.assertIn("brief=/tmp/h.md", ho)
        self.assertIn(f"waiting on: {ready_id}", ho)
        self.assertIn("subtasks=1/3", ho)

        # 2. Handover (--compact) and (--full) also pin Ready to dispatch at the top
        ho_compact = handover_mod.handover_compact_text(self.repo, ctx=self.ctx)
        self.assertIn("## Ready to dispatch (1)", ho_compact)
        self.assertLess(ho_compact.index("## Ready to dispatch"), ho_compact.index("## Open work"))

        ho_full_out = io.StringIO()
        with contextlib.redirect_stdout(ho_full_out):
            manager_cmds.cmd_handover(argparse.Namespace(repo=self.repo, turns=4, full=True, compact=False), ctx=self.ctx)
        ho_full = ho_full_out.getvalue()
        self.assertLess(ho_full.index("## Ready to dispatch"), ho_full.index("## Open work"))

        # 3. Chinese localization ("可以派了" / "等 X")
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text(json.dumps({"lang": "zh"}))
        ho_zh = io.StringIO()
        with contextlib.redirect_stdout(ho_zh):
            manager_cmds.cmd_handover(argparse.Namespace(repo=self.repo, turns=4, full=False, compact=False), ctx=self.ctx)
        self.assertIn("## 可以派了（1）", ho_zh.getvalue())
        self.assertIn(f"等 {ready_id}", ho_zh.getvalue())

        st_zh = io.StringIO()
        with contextlib.redirect_stdout(st_zh):
            status_view.cmd_status(argparse.Namespace(repo=self.repo, all=False, closed=False), ctx=self.ctx)
        st_text = st_zh.getvalue()
        self.assertIn("可以派了（1）：", st_text)
        self.assertIn(ready_id, st_text)
        self.assertIn(f"等 {ready_id}", st_text)
        self.cfg_path.unlink(missing_ok=True)

        # 4. show (text + --json) exposes depends_on and parent subtasks
        sh_parent = io.StringIO()
        with contextlib.redirect_stdout(sh_parent):
            status_view.cmd_show(argparse.Namespace(id=parent_id, json=False), ctx=self.ctx)
        self.assertIn("subtasks=1/3", sh_parent.getvalue())
        self.assertIn(ready_id, sh_parent.getvalue())

        sh_wait = io.StringIO()
        with contextlib.redirect_stdout(sh_wait):
            status_view.cmd_show(argparse.Namespace(id=wait_id, json=True), ctx=self.ctx)
        sh_data = json.loads(sh_wait.getvalue())
        self.assertFalse(sh_data["live"]["ready"])
        self.assertEqual(sh_data["live"]["deps"][0]["id"], ready_id)

        # 5. dash_state exposes ready/depends_on/deps cleanly without polluting legacy active tasks
        ds = state_view.dash_state(ctx=self.ctx)
        by_id = {t["id"]: t for t in ds["tasks"]}
        self.assertTrue(by_id[ready_id]["ready"])
        self.assertEqual(by_id[ready_id]["depends_on"], [done_id])
        self.assertEqual(by_id[ready_id]["waiting_on"], [])
        self.assertEqual(by_id[ready_id]["brief"], "/tmp/h.md")
        self.assertFalse(by_id[wait_id]["ready"])
        self.assertEqual(by_id[wait_id]["waiting_on"], [ready_id])
        self.assertFalse(by_id[todo_id]["ready"])  # plain Todo without depends_on is not "ready to dispatch"
        self.assertNotIn("depends_on", by_id[todo_id])
        self.assertEqual(ds["ready_tasks"], [ready_id])
        for absent in ("ready", "depends_on", "deps", "waiting_on", "deps_broken"):
            self.assertNotIn(absent, by_id[legacy_id])

    def test_old_pm_py_compatibility_via_deliver_look(self):
        """Even if an older pm.py writes a task's status=done directly without calling reconcile_dependencies,
        the desktop deliverer (`Deliverer.look`) detects the unlocked dependent and delivers the event."""
        self.register_hc_pm("t1")
        a_id, _ = self.new_task("Old Writer Task", slug="old-a")
        x_id, _ = self.new_task("Queued X", status="proposed", slug="queued-x",
                                brief="/tmp/qx.md", depends_on=[a_id])

        rec_a = self.load(a_id)
        rec_a["status"] = "done"
        Ledger(self.ctx).save(rec_a)

        hc = FakeHc(
            terminals={"t1": {"state": "live", "labels": {"pm": self.name}, "status": {"state": "idle"}}},
            clock=self.clock,
        )
        c = self._make_ctx(hc=hc)
        Deliverer(c, self.repo, settle=0).look(FakeChangeWaiter(), {})

        self.assertEqual(len(hc.sent), 1)
        self.assertIn("[deps pm.py]", hc.sent[0][1])
        self.assertIn(x_id, hc.sent[0][1])
        self.assertIn("/tmp/qx.md", hc.sent[0][1])

    def test_dispatch_task_reuses_recorded_brief_and_warns_unmet_deps(self):
        brief_file = Path(self.repo) / "x-brief.md"
        brief_file.write_text("# Brief\nDo X\n")
        a_id, _ = self.new_task("Prereq A", slug="pre-a")
        x_id, _ = self.new_task("Queued X", status="proposed", slug="qx-disp",
                                brief=str(brief_file), depends_on=[a_id])

        args = cli.build_parser().parse_args([
            "dispatch", "--task", x_id, "--repo", self.repo, "--branch", "dev/qx", "--dry-run",
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dispatch_cmds.cmd_dispatch(args, ctx=self.ctx)
        self.assertIn(x_id, out.getvalue())

        args_live = cli.build_parser().parse_args([
            "dispatch", "--task", x_id, "--repo", self.repo, "--branch", "dev/qx",
        ])
        hc = FakeHc(
            terminals={"t1": {"state": "live", "labels": {"pm": self.name}, "status": {"state": "idle"}}},
            clock=self.clock,
        )
        c = self._make_ctx(pane="hc:t1", hc=hc)
        out_live, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out_live), contextlib.redirect_stderr(err):
            dispatch_cmds.cmd_dispatch(args_live, ctx=c)
        self.assertIn("unmet dependencies", err.getvalue())
        self.assertEqual(self.load(x_id)["status"], "in_progress")
        self.assertTrue(any(k != "t1" for k in hc.terminals))


class _RealWaiterFakeHc(FakeHc):
    """FakeHc that delegates `change_waiter` to the real `pmlib.terminals.events.ChangeWaiter` (file events)."""

    def __init__(self, *args, worker_state_fn=None, fail_on_hc: bool = False, strip_hc_args: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._worker_state_fn = worker_state_fn
        self._fail_on_hc = fail_on_hc
        self._strip_hc_args = strip_hc_args
        self.worker_state_calls = 0
        self.waiter_hc_args: list[object] = []

    def hc(self, *args, **kwargs):
        if self._fail_on_hc:
            raise AssertionError("hc asked")
        return super().hc(*args, **kwargs)

    def worker_state(self, term: str) -> str:
        self.worker_state_calls += 1
        if self._worker_state_fn is not None:
            return self._worker_state_fn(term)
        return super().worker_state(term)

    def change_waiter(self, paths=(), hc_args=None, files=(), terminals=None, folders=(), *, hc=None, warn=None):
        self.waiter_hc_args.append(hc_args)
        use_hc_args = None if self._strip_hc_args else hc_args
        more = {**({"terminals": terminals} if terminals is not None else {}), **({"folders": folders} if folders else {})}
        return term_events_mod.ChangeWaiter(paths, use_hc_args, files=files, **more)


class _RefusingFakeTui(FakeTui):
    """FakeTui that fails the test if any TUI query is made."""

    def herdr(self, *args, session=None):
        raise AssertionError("agents asked")

    def agents(self, *, session=None):
        raise AssertionError("agents asked")

    def workspaces(self, *, session=None):
        raise AssertionError("agents asked")

    def panes(self, *, session=None):
        raise AssertionError("agents asked")


class PMNotifications(unittest.TestCase):
    """Real file-event waits, grace periods, desktop watch isolation, and ChangeWaiter.follow."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-notif-ctx-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.ctx = make_ctx(self.root, out=StdOutput())
        self.ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        self.ctx.home.inbox.mkdir(parents=True, exist_ok=True)
        self.task = {"id": "test", "repo": str(self.root), "base": "main",
                     "status": "in_progress", "log": []}
        self.write_task(self.task)

    def write_task(self, task: dict):
        temp = self.ctx.home.tasks / ".test.tmp"
        temp.write_text(json.dumps(task), encoding="utf-8")
        replace_task_file(temp, self.ctx.home.task("test"))

    def test_report_wakes_without_polling_or_a_notify_command(self):
        reported = {**self.task, "status": "review", "log": [{"text": "verified event report"}]}
        hc = _RealWaiterFakeHc(worker_state_fn=lambda term: "")
        git = StubGit(states={(str(self.root), "", "main"): (1, False)})
        ctx = make_ctx(self.root, hc=hc, git=git, out=StdOutput())
        timer = threading.Timer(.15, self.write_task, [reported])
        timer.start()
        try:
            res = wait_for_report_for(ctx, "test", timeout=3)
        finally:
            timer.join()
        self.assertIn("verified event report", "\n".join(res.lines))
        self.assertLessEqual(hc.worker_state_calls, 3)

    def test_duplicate_events_do_not_shorten_unreported_worker_grace(self):
        clk = FakeClock(mono=0.0)
        hc = _RealWaiterFakeHc(worker_state_fn=lambda term: "idle", clock=clk)
        ctx = make_ctx(self.root, hc=hc, clock=clk, out=StdOutput())

        class Pulses:
            at = 0.0
            calls = 0

            def wait(self, timeout):
                self.calls += 1
                step = min(.05 if self.calls < 10 else timeout, timeout)
                self.at += step
                clk.advance(step)

        pulses = Pulses()
        with self.assertRaises(WaitOutcome) as stop:
            wait_for_report_events_for(ctx, "test", pulses, self.task, timeout=30)
        self.assertEqual(stop.exception.code, 3)
        self.assertGreaterEqual(pulses.at, 5)
        self.assertGreaterEqual(pulses.calls, 10)

    def test_reattached_terminal_gets_its_own_grace_period(self):
        self.task["pane"] = "hc:old"
        self.write_task(self.task)
        clk = FakeClock(mono=0.0)
        hc = _RealWaiterFakeHc(worker_state_fn=lambda term: "idle", clock=clk)
        ctx = make_ctx(self.root, hc=hc, clock=clk, out=StdOutput())
        owner = self

        class Replacement:
            at = 0.0

            def wait(self, timeout):
                if self.at == 0:
                    self.at = 4.9
                    clk.advance(4.9)
                    owner.write_task({**owner.task, "pane": "hc:new"})
                else:
                    self.at += timeout
                    clk.advance(timeout)

        changes = Replacement()
        with self.assertRaises(WaitOutcome) as stop:
            wait_for_report_events_for(ctx, "test", changes, self.task, timeout=30)
        self.assertEqual(stop.exception.code, 3)
        self.assertGreaterEqual(changes.at, 9.9)

    def test_a_desktop_watch_is_its_inbox_alone(self):
        rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "runtime": "hc", "repo": str(self.root)}
        (self.ctx.home.inbox / "pm-test.watch-states.json").write_text('{"hc:old":"working"}')
        hc = _RealWaiterFakeHc(fail_on_hc=True)
        tui = _RefusingFakeTui()
        from pmlib.context import SystemClock
        ctx = make_ctx(self.root, hc=hc, tui=tui, clock=SystemClock(), out=StdOutput())
        watcher = InboxWatcher(ctx)
        res = watcher.watch(rec, timeout=.3, interval=10)
        self.assertEqual(res.kind, "timeout")
        self.assertEqual(res.text, "watch timeout")
        self.assertEqual(hc.waiter_hc_args, [None])
        watcher.append_inbox("pm-test", "worker", "reported")
        res2 = watcher.watch(rec, timeout=2, interval=10)
        self.assertIn("reported", res2.text)

    def test_watch_first_run_keeps_old_unread_lines_then_delivers_between_runs(self):
        from pmlib.context import SystemClock
        hc = _RealWaiterFakeHc(
            terminals={"test": {"state": "live", "labels": {"pm": project_slug(str(self.root))}}},
            strip_hc_args=True,
        )
        ctx = make_ctx(self.root, pane="hc:test", hc=hc, clock=SystemClock(), out=StdOutput())
        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "runtime": "hc", "repo": str(self.root)}
        ctx.home.registration(project_slug(str(self.root))).write_text(json.dumps(rec))
        args = argparse.Namespace(pm=None, repo=str(self.root), workspace=None, timeout=.05, interval=10)
        watcher = InboxWatcher(ctx)
        watcher.append_inbox("pm-test", "worker", "first report")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            events_cmds.cmd_watch(args, ctx=ctx)
        self.assertIn("first report", out.getvalue())
        self.assertIsNone(watcher.watcher_pid("pm-test"))
        watcher.append_inbox("pm-test", "worker", "between runs")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            events_cmds.cmd_watch(args, ctx=ctx)
        self.assertIn("between runs", out.getvalue())
        self.assertNotIn("first report", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            events_cmds.cmd_watch(args, ctx=ctx)
        self.assertEqual(out.getvalue(), "watch timeout\n")

    def test_wait_follows_a_replaced_worker_terminal(self):
        calls: list[list[str]] = []
        popen = subprocess.Popen

        def child(argv, **kwargs):
            calls.append(argv)
            return popen([sys.executable, "-u", "-c",
                          "import time; print('{\"terminals\": []}', flush=True); time.sleep(30)"], **kwargs)

        with mock.patch.object(term_events_mod.subprocess, "Popen", side_effect=child):
            with term_events_mod.ChangeWaiter([self.root], ["--terminal", "old"]) as waiter:
                self.assertTrue(waiter.wait(4))
                waiter.follow(["--terminal", "old"])  # the same terminal: nothing changes
                waiter.follow(["--terminal", "new"])
                self.assertTrue(waiter.wait(6))
        self.assertEqual([argv[-1] for argv in calls], ["old", "new"])

    def test_follow_starts_a_reader_again_after_it_ended(self):
        calls: list[list[str]] = []
        popen = subprocess.Popen

        def child(argv, **kwargs):
            calls.append(argv)
            return popen([sys.executable, "-u", "-c",
                          "import time; print('{\"terminals\": []}', flush=True); time.sleep(30)"], **kwargs)

        with mock.patch.object(term_events_mod.subprocess, "Popen", side_effect=child):
            with term_events_mod.ChangeWaiter([self.root], ["--terminal", "a"]) as waiter:
                self.assertTrue(waiter.wait(4))
                waiter.follow(None)  # the task lost its terminal: the reader ends
                waiter.thread.join(timeout=8)
                self.assertFalse(waiter.thread.is_alive())
                waiter.follow(["--terminal", "b"])
                self.assertTrue(waiter.wait(6))
        self.assertEqual([argv[-1] for argv in calls], ["a", "b"])


class Watchers(unittest.TestCase):
    """What watch does when nothing would read what it prints, and on its first run; where notify goes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-watchers-ctx-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.git = GitRepo(worktree_base=self.root / "worktrees")
        from pmlib.context import SystemClock
        self.hc = _RealWaiterFakeHc(strip_hc_args=True)
        self.ctx = make_ctx(self.root, hc=self.hc, tui=FakeTui(agents=[]), git=self.git,
                            clock=SystemClock(), out=StdOutput())
        for folder in (self.ctx.home.tasks, self.ctx.home.inbox, self.ctx.home.registrations):
            folder.mkdir(parents=True, exist_ok=True)
        self.rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "repo": str(self.root)}

    def watch(self, timeout: float = .2) -> str:
        res = InboxWatcher(self.ctx).watch(self.rec, timeout=timeout, interval=10)
        res.commit()
        return res.text if res.kind == "inbox" else f"{res.text}\n"

    def test_first_watch_delivers_only_the_newest_unread_lines(self):
        watcher = InboxWatcher(self.ctx)
        for n in range(1, 31):
            watcher.append_inbox("pm-test", "worker", f"report {n}")
        out = self.watch()
        self.assertIn("report 30", out)
        self.assertIn("report 11", out)
        self.assertNotIn("report 10\n", out)
        self.assertIn("10 earlier lines are not shown", out)
        self.assertEqual(self.watch(), "watch timeout\n")

    @unittest.skipIf(os.name == "nt", "POSIX parents")
    def test_a_watcher_whose_starter_is_gone_stops_and_leaves_the_inbox_unread(self):
        InboxWatcher(self.ctx).append_inbox("pm-test", "worker", "keep me")
        self.ctx.home.inbox_offset("pm-test").write_text("0")
        with mock.patch.object(os, "getppid", side_effect=[100] + [1] * 20), self.assertRaises(Refused) as stop:
            self.watch(timeout=5)
        self.assertIn("what started it has gone", str(stop.exception))
        self.assertEqual(self.ctx.home.inbox_offset("pm-test").read_text(), "0")
        self.assertIn("keep me", self.watch())

    def test_a_watch_that_prints_to_dev_null_is_noticed(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from pmlib.events.inbox import output_nowhere; "
                "sys.exit(0 if output_nowhere() else 1)")
        argv = [sys.executable, "-c", code, str(SCRIPTS)]
        env = {**os.environ, "PM_HOME": str(self.ctx.home.root)}
        if os.name != "nt":
            self.assertEqual(subprocess.run(argv, stdout=subprocess.DEVNULL, env=env).returncode, 0)
        self.assertEqual(subprocess.run(argv, stdout=subprocess.PIPE, env=env).returncode, 1)
        with open(self.root / "out.txt", "w") as out:
            self.assertEqual(subprocess.run(argv, stdout=out, env=env).returncode, 1)

    @unittest.skipIf(os.name == "nt", "POSIX parents")
    def test_left_behind_is_told_by_who_adopted_the_process(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertTrue(inbox_mod.adopted(1))
            self.assertFalse(inbox_mod.adopted(os.getpid()))
        names = {1: "claude", 7: "systemd", 8: "claude", 9: ""}
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(inbox_mod, "process_name", side_effect=lambda pid: names[pid]):
            self.assertTrue(inbox_mod.adopted(7))
            self.assertFalse(inbox_mod.adopted(8))
            self.assertFalse(inbox_mod.adopted(1))  # an agent running as a container's process 1
            names[1] = "init"
            self.assertTrue(inbox_mod.adopted(1))
            self.assertFalse(inbox_mod.adopted(9))

    def test_a_refused_second_watcher_says_what_holds_the_lock(self):
        watcher = InboxWatcher(self.ctx)
        for n in range(3):
            watcher.append_inbox("pm-test", "worker", f"line {n}")
        self.ctx.home.inbox_offset("pm-test").write_text("0")
        report = watcher.watcher_report("pm-test", os.getpid())
        self.assertIn(f"already running (pid {os.getpid()})", report)
        self.assertIn("unread lines in", report)
        self.assertIn(": 3", report)
        if os.name != "nt":
            self.assertIn("command:", report)
            self.assertIn("started by: pid", report)

    def test_without_pm_events_waits_fall_back_to_timed_looks(self):
        with mock.patch.object(term_events_mod, "ChangeWaiter", None), \
                mock.patch.object(term_events_mod.time, "sleep") as sleep:
            with term_events_mod.change_waiter([self.ctx.home.inbox], None, files=[]) as waiter:
                self.assertTrue(waiter.wait(3600))
        sleep.assert_called_once_with(term_events_mod.WAIT_POLL)

    def registered(self, folder: Path, repo: Path | None = None) -> dict:
        folder.mkdir(parents=True, exist_ok=True)
        rec = {"name": f"pm-{folder.name}", "repo": str(repo or folder), "pane": "w1:p1"}
        self.ctx.home.registration(project_slug(str(folder))).write_text(json.dumps(rec))
        return rec

    def notify(self, repo: Path | None, pane: str = "", labels: dict | None = None, session: str = "") -> str:
        """cmd_notify from this pane; labels: what `hc get` says this terminal carries (in this core session)."""
        terminals = {}
        if labels and pane.startswith("hc:"):
            terminals[pane[3:]] = {"state": "live", "labels": dict(labels)}
        hc = FakeHc(terminals=terminals)
        env = {"CLAUDE_CODE_SESSION_ID": session} if session else {}
        c = make_ctx(self.root, pane=pane, hc=hc, tui=FakeTui(agents=[]), git=self.git, env=env, out=StdOutput())
        out = io.StringIO()
        with mock.patch.object(Path, 'home', return_value=self.root / 'home'), contextlib.redirect_stdout(out):
            events_cmds.cmd_notify(argparse.Namespace(text="done", repo=str(repo) if repo else None), ctx=c)
        return out.getvalue()

    @unittest.skipUnless(shutil.which("git"), "git makes the nested repository")
    def test_notify_from_a_repository_nested_in_the_project_folder_reaches_its_pm(self):
        project = self.root / "home/work/suite"
        self.registered(project)
        nested = project / "service-wt"
        nested.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        out = self.notify(nested)
        self.assertIn("appended to", out)
        self.assertIn("] done", self.ctx.home.inbox_log("pm-suite").read_text())

    def test_notify_goes_to_the_pm_of_the_task_this_terminal_works_on(self):
        project, elsewhere = self.root / "home/p/app", self.root / "home/scratch/x"
        self.registered(project)
        elsewhere.mkdir(parents=True)
        self.ctx.home.task("app-fix").write_text(json.dumps(
            {"id": "app-fix", "repo": str(project), "pane": "hc:t9", "status": "in_progress", "updated": "1"}))
        here = os.getcwd()
        os.chdir(elsewhere)  # no --repo: run in a folder that is in no PM's project
        self.addCleanup(os.chdir, here)
        # This terminal's own label in this core names the task.
        self.notify(None, pane="hc:t9", labels={"task": "app-fix"})
        self.assertEqual(self.ctx.home.inbox_log("pm-app").read_text().count("] done"), 1)
        # The task recorded this Claude Code session as its agent (herdr TUI: no label to read).
        self.ctx.home.task("app-fix").write_text(json.dumps(
            {"id": "app-fix", "repo": str(project), "pane": "w1:p3", "status": "in_progress", "updated": "1",
             "session": {"kind": "claude", "id": "s-1"}}))
        self.notify(None, pane="w1:p3", session="s-1")
        self.assertEqual(self.ctx.home.inbox_log("pm-app").read_text().count("] done"), 2)
        # --repo names a project: one without a PM is an error, never this task's PM.
        with self.assertRaises(SystemExit) as stop:
            self.notify(elsewhere, pane="w1:p3", session="s-1")
        self.assertIn("nothing was delivered, and not to another PM either", str(stop.exception.code))
        self.assertEqual(self.ctx.home.inbox_log("pm-app").read_text().count("] done"), 2)

    def test_notify_does_not_trust_a_pane_number_alone(self):
        project, mine = self.root / "home/p/app", self.root / "home/p/mine"
        self.registered(project)
        self.registered(mine)
        self.ctx.home.task("app-fix").write_text(json.dumps(
            {"id": "app-fix", "repo": str(project), "pane": "w1:p3", "status": "in_progress", "updated": "1",
             "session": {"kind": "claude", "id": "someone-else"}}))
        here = os.getcwd()
        os.chdir(mine)
        self.addCleanup(os.chdir, here)
        self.notify(None, pane="w1:p3", session="s-2")  # no --repo, so the task would come first if it matched
        self.assertFalse(self.ctx.home.inbox_log("pm-app").exists())
        self.assertIn("] done", self.ctx.home.inbox_log("pm-mine").read_text())
        # Nor a hc terminal number whose own labels name no task (an address reused after removal).
        self.ctx.home.task("app-fix").write_text(json.dumps(
            {"id": "app-fix", "repo": str(project), "pane": "hc:t9", "status": "in_progress", "updated": "1"}))
        self.notify(None, pane="hc:t9", labels={"pm": "other"})
        self.assertFalse(self.ctx.home.inbox_log("pm-app").exists())
        self.assertEqual(self.ctx.home.inbox_log("pm-mine").read_text().count("] done"), 2)

    @unittest.skipUnless(shutil.which("git"), "git makes the nested repository")
    def test_notify_from_a_nested_repository_with_a_pm_of_its_own_goes_to_its_tasks_pm(self):
        project = self.root / "home/work/suite"
        self.registered(project)
        nested = project / "service"
        self.registered(nested)  # the nested repository has a PM of its own
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        self.ctx.home.task("suite-fix").write_text(json.dumps(
            {"id": "suite-fix", "repo": str(project), "pane": "hc:t9", "status": "in_progress", "updated": "1"}))
        here = os.getcwd()
        os.chdir(nested)
        self.addCleanup(os.chdir, here)
        self.notify(None, pane="hc:t9", labels={"task": "suite-fix"})  # no --repo: the task's PM
        self.assertIn("] done", self.ctx.home.inbox_log("pm-suite").read_text())
        self.notify(nested, pane="hc:t9", labels={"task": "suite-fix"})  # --repo names the project
        self.assertIn("] done", self.ctx.home.inbox_log("pm-service").read_text())

    def test_notify_without_a_pm_fails_and_says_so(self):
        lonely = self.root / "home/work/other/repo"
        lonely.mkdir(parents=True)
        # A PM registered for a namesake folder elsewhere is not this folder's PM.
        self.registered(self.root / "home/work/other-place/other", repo=self.root / "elsewhere/other")
        with self.assertRaises(SystemExit) as stop:
            self.notify(lonely)
        self.assertIn("no PM for", str(stop.exception.code))
        self.assertIn("nothing was delivered", str(stop.exception.code))
        here = os.getcwd()
        os.chdir(lonely)
        self.addCleanup(os.chdir, here)
        with self.assertRaises(SystemExit) as stop:
            self.notify(None)
        self.assertIn("no PM found", str(stop.exception.code))
        self.assertEqual(list(self.ctx.home.inbox.glob("*.log")), [])


class NonHomonymousProjectSlugRoutingTests(unittest.TestCase):
    """Tasks belonging to non-homonymous folders (project_slug != folder basename) must anchor Conversation,
    Delivery, StallWatcher, DependencyWatcher, parent rollups, and async send failures to projects/<project_slug>/."""

    def test_stall_deps_rollup_send_failed_and_delivery_anchor_to_project_slug(self):
        from pmlib.commands.ledger import UpdateRequest
        from pmlib.reactions import Updates
        from pmlib.workers.send import send_failed_for

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = make_ctx(root / "ledger")
            dudu_repo = root / "work/dudu"
            web_repo = root / "other/web"
            dudu_repo.mkdir(parents=True)
            web_repo.mkdir(parents=True)
            ctx.git.roots[str(dudu_repo.resolve())] = str(dudu_repo.resolve())
            ctx.git.roots[str(web_repo.resolve())] = str(web_repo.resolve())

            ctx.home.registrations.mkdir(parents=True, exist_ok=True)
            ctx.home.project("dudu").root.mkdir(parents=True, exist_ok=True)
            ctx.home.registration("dudu").write_text(json.dumps({
                "name": "pm-dudu",
                "slug": "dudu",
                "project": "Dudu",
                "runtime": "hc",
                "terminal": "pm1",
                "pane": "hc:pm1",
                "folders": [
                    {"path": str(dudu_repo.resolve()), "alias": "dudu", "git": True},
                    {"path": str(web_repo.resolve()), "alias": "web", "git": True},
                ],
                "repo": str(dudu_repo.resolve()),
            }), encoding="utf-8")
            ctx.hc.terminals["pm1"] = {"id": "pm1", "state": "live"}
            ctx.hc.terminals["w2"] = {"id": "w2", "state": "live"}
            ctx.hc.terminals["w4"] = {"id": "w4", "state": "live"}
            ctx.home.tasks.mkdir(parents=True, exist_ok=True)

            for tid, fields in (
                ("dudu-1", {"title": "Parent", "status": "in_progress"}),
                ("dudu-2", {"title": "Web Child", "status": "in_progress", "parent": "dudu-1", "pane": "hc:w2"}),
                ("dudu-3", {"title": "Web Followup", "status": "proposed", "depends_on": ["dudu-2"],
                            "brief": "/tmp/web-followup.md"}),
                ("dudu-4", {"title": "Web Staller", "status": "in_progress", "pane": "hc:w4"}),
            ):
                ctx.home.task(tid).write_text(json.dumps({
                    "id": tid,
                    "project": "Dudu",
                    "project_slug": "dudu",
                    "folder_alias": "web",
                    "repo": str(web_repo.resolve()),
                    "updated": "2026-11-28 06:00",
                    **fields,
                }), encoding="utf-8")

            # 1) Stall notification -> projects/dudu/conversation.jsonl & spawn deliver "dudu"
            stall_task = ctx.store.task("dudu-4")
            assert stall_task is not None
            StallWatcher(ctx).stalled(stall_task, "worker stopped without reporting", key="w4:stop:1")
            # 2) Failed async send (task-bound AND repo-only fallback) -> projects/dudu/conversation.jsonl
            send_failed_for(ctx, "w2", "timeout", task_id="dudu-2", repo=str(web_repo))
            send_failed_for(ctx, "w9", "timeout", repo=str(web_repo))

            # 3) Child done -> parent rollup close & ready-dependency notification -> projects/dudu/conversation.jsonl
            ctx.pane = "hc:w2"
            Updates(ctx).update(UpdateRequest(id="dudu-2", status="done", note="web child done"))
            ctx.pane = ""
            DependencyWatcher(ctx).reconcile(str(web_repo))

            # Assert everything landed in projects/dudu/conversation.jsonl and projects/web/ never existed.
            self.assertFalse((ctx.home.projects / "web").exists())
            dudu_conv = Conversation(ctx, str(web_repo), slug="dudu")
            events = dudu_conv.events()
            self.assertTrue(any(e.get("type") == "stall" and e.get("task") == "dudu-4" for e in events))
            self.assertTrue(any(e.get("source") == "harness" and e.get("by") == "hc:w9" for e in events))
            self.assertTrue(any(e.get("source") == "deps" and e.get("task") == "dudu-3" for e in events))
            self.assertTrue(any(e.get("task") == "dudu-1" and e.get("status") == "done" for e in events))
            self.assertEqual(ctx.store.task("dudu-1")["status"], "done")
            self.assertTrue(any(e.get("task") == "dudu-2" and e.get("source") == "harness" and e.get("by") == "harness" for e in events))
            self.assertTrue(any(s["args"][:2] == ["deliver", "dudu"] for s in ctx.procs.spawned))

            d = Delivery(ctx, str(web_repo), slug="dudu", settle=0)
            _, _, items = d.pending_batch(offset=0)
            self.assertTrue(any(i["event"].get("task") == "dudu-4" for i in items))


if __name__ == "__main__":
    unittest.main()
