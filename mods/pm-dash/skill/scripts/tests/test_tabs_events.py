"""Desktop tab names and renames (pmlib.terminals.tabs, HcHost) and the change waiter behind every event wait
(pmlib.terminals.events). Moved from test_pm.py's TabText, TabWithoutApp and EventWaitHc and from test_pm_events.py's
NativeEvents (Stage 6a). The tab tests build their own Context with make_ctx (config.json under its own ledger) and
pass ctx.config, or a real HcHost over it whose herdr-app and herdr-core calls are injected, where test_pm.py patched
pm.*; the waiter tests run the real ChangeWaiter on a temporary folder of their own."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import make_ctx  # noqa: E402
from pmlib.agents.codex_pool import shows_fast  # noqa: E402
from pmlib.terminals import events as events_mod, tabs  # noqa: E402
from pmlib.terminals.hc import HcHost  # noqa: E402

POLICY = {
    "codex": {"projects": ["proj"],
              "profiles": [{"name": "team-a", "max": 2, "fast": True}, {"name": "team-b", "max": 3, "fast": True}],
              "allow_default": False, "model": "codex-model", "review_model": "review-model", "effort": "high",
              "fallback": {"worker": {"kind": "claude", "model": "opus", "effort": "high"},
                           "reviewer": {"kind": "claude", "model": "fable", "effort": "high"}}},
    "claude": {"launcher": ["zsh", "-ic", "my-claude --yes {args}"], "effort": "high", "fable_fallback": "opus"},
    "tabs": {"max": 20, "review": "审查", "bug_pattern": r"(?<![0-9])#?([0-9]{5})(?![0-9])"},
}


class WithConfig(unittest.TestCase):
    """A Context of its own per test, its config.json holding CONFIG (test_pm.py's Policy wrote the shared one)."""
    CONFIG = POLICY

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="pm-tabs-events-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = make_ctx(self.tmp, config=self.CONFIG)

    def config(self, value):
        """Replace this test's config.json (Config reads it afresh on every call)."""
        self.ctx.home.config.write_text(json.dumps(value), encoding="utf-8")


class EventWaitHc(WithConfig):
    CONFIG = {"hc": "/opt/tools/hc"}

    def test_event_waits_run_the_configured_hc(self):
        host = HcHost(self.ctx.config, clock=self.ctx.clock)          # what Context.from_env builds
        with mock.patch.object(events_mod, "ChangeWaiter") as waiter:
            host.change_waiter([self.ctx.home.tasks], ["--terminal", "t1"], files=[])
        self.assertEqual(waiter.call_args.kwargs["hc"], "/opt/tools/hc")


class TabText(WithConfig):
    def test_tab_title(self):
        cfg = self.ctx.config
        # <terminal>-<BUG>-<short>; the BUG number is taken out of the short name and put after the address.
        self.assertEqual(tabs.tab_title("12345-登录修复", "12345", "t5g", cfg=cfg), "t5g-12345-登录修复")
        self.assertEqual(tabs.tab_title("12345第5项状态", "12345", "t5g", cfg=cfg), "t5g-12345-第5项状态")
        self.assertEqual(tabs.tab_title("#12345 登录修复", "12345", "t5g", cfg=cfg), "t5g-12345-登录修复")
        self.assertEqual(tabs.tab_title("A004-循环", "", "t4r", cfg=cfg), "t4r-A004-循环")  # no BUG number: <terminal>-<use>
        self.assertEqual(tabs.tab_title("审查-demo1", "", "t5m", cfg=cfg), "t5m-审查-demo1")
        # a short that starts with an address already: not doubled; the real address takes its place
        self.assertEqual(tabs.tab_title("t5g-12345-登录修复", "12345", "t5g", cfg=cfg), "t5g-12345-登录修复")
        self.assertEqual(tabs.tab_title("t5g-12345-登录修复", "12345", "t6a", cfg=cfg), "t6a-12345-登录修复")
        self.assertEqual(tabs.tab_title("t5g-12345-登录修复", "12345", dry=True, cfg=cfg), "t5g-12345-登录修复")
        self.assertEqual(tabs.tab_title("test-修复", "", dry=True, cfg=cfg), "t?-test-修复")  # "test-" is no address
        self.assertEqual(tabs.tab_title("方案", "", "", cfg=cfg), "方案")  # no terminal (herdr TUI): no address
        self.assertEqual(tabs.tab_title("", "12345", "t5g", cfg=cfg), "t5g-12345")
        self.assertEqual(tabs.tab_title("一二三四五六七八九十一二三四五六七八九十多", "", "t5g", cfg=cfg),
                         "t5g-一二三四五六七八九十一二三四五六七八九十")  # tabs.max: 20
        self.config({"tabs": {"max": 5}})                              # tabs.max is read from this Context
        self.assertEqual(tabs.tab_title("一二三四五六七", "", "t5g", cfg=cfg), "t5g-一二三四五")

    def test_bug_of(self):
        cfg = self.ctx.config
        self.assertEqual(tabs.bug_of("54321", "12345-登录", "#11111 x", cfg=cfg), "54321")  # --bug first
        self.assertEqual(tabs.bug_of("", "12345-登录", "#11111 x", cfg=cfg), "12345")  # then --tab
        self.assertEqual(tabs.bug_of("", "", "修复 #11111 登录", cfg=cfg), "11111")  # then the title
        self.assertEqual(tabs.bug_of("", "A004-循环", "demo-1118-1239 20261119", cfg=cfg), "")
        self.assertEqual(tabs.bug_of("#12345", cfg=cfg), "12345")
        self.assertEqual(tabs.task_bug({"title": "审查：demo1"}, cfg=cfg), "")
        self.assertEqual(tabs.task_bug({"title": "12345 登录", "bug": "10001"}, cfg=cfg), "10001")
        self.assertEqual(tabs.task_bug({"title": "12345 登录"}, cfg=cfg), "12345")  # from the title, by bug_pattern

    def test_no_bug_pattern_by_default(self):
        self.config({})
        cfg = self.ctx.config
        self.assertEqual(tabs.bug_of("", "12345-登录", "#11111 x", cfg=cfg), "")  # only --bug says it
        self.assertEqual(tabs.bug_of("777", cfg=cfg), "777")

    def test_tab_short_and_hc_name(self):
        self.assertEqual(tabs.tab_short("t5g-12345 登录修复"), "12345登录修复")
        self.assertEqual(tabs.hc_name("t5g-12345-登录修复"), "t5g-12345")
        self.assertEqual(tabs.hc_name("登录"), "worker")

    def test_fast_line(self):
        self.assertTrue(shows_fast("Model-X high fast · Context 21% used"))
        self.assertFalse(shows_fast("Model-X high ultrafast · Context 21% used"))
        self.assertFalse(shows_fast("Model-X high · Context 3% used · fast mode tips"))


class TabWithoutApp(WithConfig):
    """No herdr-app on this machine: a tab is renamed in the app's document in herdr-core only when
    tabs.rename_via_core says so. The HcHost is the real one; its herdr-app runs and herdr-core calls are injected."""
    CONFIG = {}

    @staticmethod
    def missing(*args, **kw):
        raise FileNotFoundError("herdr-app")

    def test_off_by_default_nothing_is_renamed_and_the_log_says_why(self):
        rpc = mock.Mock()
        host = HcHost(self.ctx.config, clock=self.ctx.clock, app_runner=self.missing, rpc_runner=rpc)
        self.assertFalse(host.name_tab("t2", "PM-app"))
        rpc.assert_not_called()
        with mock.patch.object(tabs.shutil, "which", return_value=None):
            self.assertIn("tabs.rename_via_core", tabs.not_renamed(cfg=self.ctx.config))

    def test_switched_on_it_goes_through_herdr_core(self):
        self.config({"tabs": {"rename_via_core": True}})
        doc = {"spaces": [{"tabs": [{"name": "3", "root": {"children": [{"content": {"terminal": "t2"}}]}},
                                    {"name": "PM-app", "root": {"children": [{"content": {"terminal": "t1"}}]}}]}]}
        def rpc(method, params):
            return {"result": {"value": json.loads(json.dumps(doc)), "version": 4}} if method == "doc.get" else \
                {"result": {"version": 5}}
        fake = mock.Mock(side_effect=rpc)
        host = HcHost(self.ctx.config, clock=self.ctx.clock, app_runner=self.missing, rpc_runner=fake)
        self.assertTrue(host.name_tab("t2", "PM-app"))
        self.assertTrue(host.name_tab("t1", "", only_if="PM-app"))
        self.assertFalse(host.name_tab("t1", "x", only_if="other"))   # only_if reaches herdr-core's rename
        written = [c[0][1]["value"]["spaces"][0]["tabs"] for c in fake.call_args_list if c[0][0] == "doc.set"]
        self.assertEqual([[t["name"] for t in w] for w in written], [["PM-app", "PM-app"], ["3", ""]])
        with mock.patch.object(tabs.shutil, "which", return_value=None):
            self.assertIn("no tab found", tabs.not_renamed(cfg=self.ctx.config))

    def test_rename_tab_writes_the_apps_document(self):
        doc = {"spaces": [{"tabs": [{"name": "3", "root": {"children": [{"content": {"terminal": "t2"}}]}}]}]}
        def rpc(method, params):
            return {"result": {"value": json.loads(json.dumps(doc)), "version": 4}} if method == "doc.get" else \
                {"result": {"version": 5}}
        fake = mock.Mock(side_effect=rpc)
        host = HcHost(self.ctx.config, clock=self.ctx.clock, rpc_runner=fake)
        self.assertTrue(host.rename_tab("t2", "t2-登录", wait=0))
        self.assertFalse(host.rename_tab("t2", "x", wait=0, only_if="PM-app"))  # a tab named otherwise: left
        self.assertFalse(host.rename_tab("t9", "x", wait=0))  # no tab shows it
        written = [c for c in fake.call_args_list if c[0][0] == "doc.set"]
        self.assertEqual(len(written), 1)
        self.assertEqual((written[0][0][1]["version"], written[0][0][1]["value"]["spaces"][0]["tabs"][0]["name"]),
                         (4, "t2-登录"))


# ---- the change waiter (moved from test_pm_events.py NativeEvents) ---------------------------------------------

NATIVE = os.name == "nt" or sys.platform.startswith("linux") or hasattr(events_mod.select, "kqueue")


def drain(waiter):
    while waiter.wait(.05):
        pass


class NativeEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    @unittest.skipUnless(NATIVE, "native supported platforms")
    def test_append_atomic_replace_and_no_busy_wait(self):
        target = self.root / "inbox.log"
        with events_mod.ChangeWaiter([self.root], files=[target]) as waiter:
            self.assertTrue(waiter.files.active)
            self.assertFalse(waiter.wait(.03))
            target.write_text("first\n", encoding="utf-8")
            self.assertTrue(waiter.wait(2))
            # Drain any coalesced open/write notifications, then observe replace.
            drain(waiter)
            temp = self.root / ".new"
            temp.write_text("second\n", encoding="utf-8")
            events_mod.replace_task_file(temp, target)
            self.assertTrue(waiter.wait(2))
            drain(waiter)
            # An append to the file that replaced the first (`notify` appends to a log that stays).
            with open(target, "a", encoding="utf-8") as f:
                f.write("third\n")
            self.assertTrue(waiter.wait(2))
            thread = waiter.files.thread
        self.assertFalse(thread.is_alive())

    @unittest.skipUnless(NATIVE, "native supported platforms")
    def test_append_to_a_file_that_was_there_before_the_wait(self):
        target = self.root / "pm-a.log"
        target.write_text("old\n", encoding="utf-8")
        with events_mod.ChangeWaiter([self.root], files=[target]) as waiter:
            drain(waiter)
            with open(target, "a", encoding="utf-8") as f:
                f.write("new\n")
            self.assertTrue(waiter.wait(2))

    @unittest.skipUnless(NATIVE, "native supported platforms")
    def test_wakes_for_its_files_not_for_other_files_in_the_folder(self):
        mine, other = self.root / "mine.json", self.root / "other.json"
        mine.write_text("{}", encoding="utf-8")
        with events_mod.ChangeWaiter([self.root], files=[mine]) as waiter:
            drain(waiter)
            # Another task saved (tmp + rename), an offset rewritten in place: not this wait's business.
            temp = self.root / ".other.tmp"
            temp.write_text("{}", encoding="utf-8")
            events_mod.replace_task_file(temp, other)
            (self.root / "pm-a.offset").write_text("12", encoding="utf-8")
            self.assertFalse(waiter.wait(.3))
            temp = self.root / ".mine.tmp"
            temp.write_text('{"status": "review"}', encoding="utf-8")
            events_mod.replace_task_file(temp, mine)
            self.assertTrue(waiter.wait(2))

    @unittest.skipUnless(NATIVE, "native supported platforms")
    def test_sees_a_file_created_after_the_wait_began(self):
        log = self.root / "pm-new.log"
        with events_mod.ChangeWaiter([self.root], files=[log]) as waiter:
            drain(waiter)
            with open(log, "a", encoding="utf-8") as f:  # the first `notify` creates the inbox
                f.write("first\n")
            self.assertTrue(waiter.wait(2))
            drain(waiter)
            with open(log, "a", encoding="utf-8") as f:
                f.write("second\n")
            self.assertTrue(waiter.wait(2))

    def test_another_pms_log_or_an_offset_does_not_wake_a_watcher(self):
        # The folder backends of Windows and Linux report every change in the inbox folder.
        mine, other = self.root / "pm-a.log", self.root / "pm-b.log"
        mine.write_text("old\n", encoding="utf-8")
        events = events_mod.DirectoryEvents.__new__(events_mod.DirectoryEvents)
        events.files = [str(mine)]
        events.marks = {str(mine): events_mod.mark(mine)}
        other.write_text("for b\n", encoding="utf-8")
        (self.root / "pm-a.offset").write_text("4", encoding="utf-8")
        self.assertFalse(events.moved())
        with open(mine, "a", encoding="utf-8") as f:
            f.write("for a\n")
        self.assertTrue(events.moved())
        self.assertFalse(events.moved())
        mine.unlink()  # gone (rotated): a change too
        self.assertTrue(events.moved())
        events.files = []
        self.assertTrue(events.moved())  # no files named: every folder event wakes

    @unittest.skipIf(os.name == "nt", "pipes in select")
    def test_the_linux_loop_wakes_only_when_its_files_changed(self):
        # inotify itself needs Linux; its loop runs anywhere on a pipe standing in for the inotify descriptor.
        mine = self.root / "pm-a.log"
        mine.write_text("", encoding="utf-8")
        woke = threading.Event()
        events = events_mod.DirectoryEvents.__new__(events_mod.DirectoryEvents)
        events.files, events.marks = [str(mine)], {str(mine): events_mod.mark(mine)}
        events.changed, events.active = woke.set, True
        fake, events.pipe = os.pipe(), os.pipe()
        events.fd = fake[0]
        thread = threading.Thread(target=events._linux, daemon=True)
        thread.start()
        try:
            (self.root / "pm-b.log").write_text("x\n", encoding="utf-8")
            os.write(fake[1], b"event")
            self.assertFalse(woke.wait(.3))
            with open(mine, "a", encoding="utf-8") as f:
                f.write("report\n")
            os.write(fake[1], b"event")
            self.assertTrue(woke.wait(2))
        finally:
            os.write(events.pipe[1], b"x")
            thread.join(2)
            for fd in (*fake, *events.pipe):
                os.close(fd)
        self.assertFalse(thread.is_alive())

    def test_hints_queued_before_wait_are_not_lost_and_are_coalesced(self):
        with events_mod.ChangeWaiter([self.root]) as waiter:
            for _ in range(100):
                waiter.wake()
            self.assertEqual(waiter.queue.qsize(), 1)
            self.assertTrue(waiter.wait(.1))
            self.assertFalse(waiter.wait(.01))

    @unittest.skipUnless(os.name == "nt", "Windows sharing conflicts")
    def test_task_replacement_retries_transient_but_not_permanent_denial(self):
        source = mock.Mock()
        source.replace.side_effect = [PermissionError(), PermissionError(), None]
        with mock.patch.object(events_mod.time, "sleep") as sleep:
            events_mod.replace_task_file(source, self.root / "task.json")
            self.assertEqual(source.replace.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            source.replace.side_effect = PermissionError()
            with self.assertRaises(PermissionError):
                events_mod.replace_task_file(source, self.root / "task.json")
            self.assertEqual(source.replace.call_count, 9)

    def test_fallback_is_explicit_and_bounded(self):
        with mock.patch.object(events_mod, "DirectoryEvents", side_effect=OSError("unsupported")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            with events_mod.ChangeWaiter([self.root]) as waiter:
                self.assertIsNone(waiter.files)
                with mock.patch.object(waiter.queue, "get", side_effect=events_mod.queue.Empty) as get:
                    self.assertFalse(waiter.wait(3600))
                    get.assert_called_once_with(timeout=60)
        self.assertIn("reconciling every 60s", err.getvalue())

    def test_only_relevant_facts_wake_the_pm(self):
        for message in ({"terminals": []}, {"method": "missed"},
                        {"method": "event", "params": {"type": "status"}},
                        {"method": "event", "params": {"type": "lost"}}):
            self.assertTrue(events_mod.relevant_fact(message))
        for message in (None, [], {}, {"method": "heartbeat"},
                        {"method": "event", "params": {"type": "title"}},
                        {"method": "event", "params": {"type": "output"}}):
            self.assertFalse(events_mod.relevant_fact(message))

    def test_an_unfiltered_stream_wakes_only_for_the_terminals_followed(self):
        fact = lambda term: {"method": "event", "params": {"type": "status", "terminal": term}}
        self.assertTrue(events_mod.relevant_fact(fact("t7"), {"t7", "t20"}))
        self.assertFalse(events_mod.relevant_fact(fact("t9"), {"t7", "t20"}))
        self.assertTrue(events_mod.relevant_fact({"terminals": []}, set()))  # a fresh snapshot: look again
        popen = subprocess.Popen
        lines = [json.dumps({"terminals": []}), json.dumps(fact("t9")), json.dumps(fact("t20"))]
        code = ("import sys, time\n"
                "for line in sys.argv[1:]:\n"
                "    print(line, flush=True); time.sleep(0.4)\n"
                "time.sleep(30)")
        with mock.patch.object(events_mod.subprocess, "Popen",
                               lambda argv, **kw: popen([sys.executable, "-u", "-c", code, *lines], **kw)):
            with events_mod.ChangeWaiter([self.root], [], terminals={"t7"}) as waiter:
                self.assertTrue(waiter.wait(4))          # the snapshot
                waiter.terminals = {"t7", "t20"}          # a worker to follow from now on
                self.assertTrue(waiter.wait(4))          # t20's fact, not t9's
                started = time.monotonic()
                self.assertFalse(waiter.wait(0.6))
                self.assertGreaterEqual(time.monotonic() - started, 0.5)

    def test_a_status_fact_that_keeps_the_state_wakes_no_one(self):
        fact = lambda term, state, msg="": {"method": "event", "params": {"type": "status", "terminal": term, "data": {
            "reported": True, "status": {"app": "x", "state": state, "msg": msg} if state else None}}}
        states = {}
        said = [events_mod.same_status(fact(*f), states) for f in (
            ("t7", "working"), ("t7", "working", "Bash"), ("t7", "working", "Edit"), ("t20", "working"),
            ("t7", "idle"), ("t7", None), ("t7", None))]
        self.assertEqual(said, [False, True, True, False, False, False, True])
        self.assertFalse(events_mod.same_status({"method": "event", "params": {"type": "finished", "terminal": "t7"}},
                                               states))

    def test_the_status_cache_follows_every_terminal_and_starts_again_after_a_gap(self):
        fact = lambda term, state: {"method": "event", "params": {"type": "status", "terminal": term, "data": {
            "reported": True, "status": {"app": "x", "state": state}}}}
        with events_mod.ChangeWaiter([self.root], terminals={"t7", "t20"}) as waiter:
            states = {}
            self.assertTrue(waiter.hint(fact("t20", "idle"), states))
            waiter.terminals = {"t7"}                                  # not followed for a while
            self.assertFalse(waiter.hint(fact("t20", "working"), states))
            waiter.terminals = {"t7", "t20"}
            self.assertTrue(waiter.hint(fact("t20", "idle"), states))  # it went working meanwhile: news
            for gap in ({"terminals": []}, {"method": "missed"}):      # a snapshot, events dropped
                self.assertTrue(waiter.hint(gap, states))
                self.assertEqual(states, {})
                self.assertTrue(waiter.hint(fact("t20", "idle"), states))
            self.assertFalse(waiter.hint(fact("t20", "idle"), states))
            waiter.hint({"method": "event", "params": {"type": "removed", "terminal": "t20"}}, states)
            self.assertNotIn("t20", states)

    @unittest.skipUnless(NATIVE, "native file notifications unavailable")
    def test_a_folder_given_as_folders_wakes_on_any_change(self):
        tasks = self.root / "tasks"
        tasks.mkdir()
        log = self.root / "log.jsonl"
        log.write_text("")
        with events_mod.ChangeWaiter([self.root], files=[log], folders=[tasks]) as waiter:
            drain(waiter)
            tmp = tasks / ".t.json.tmp"
            tmp.write_text("{}")
            tmp.replace(tasks / "t.json")                              # a task file saved after its log line
            self.assertTrue(waiter.wait(3))

    def test_stream_reconnects_and_cleanup_ends_only_its_child(self):
        popen = subprocess.Popen
        children = []
        def child(*args, **kwargs):
            # First connection closes. The replacement emits a fresh snapshot.
            code = ("pass" if not children else
                    "import time; print('{\"terminals\": []}', flush=True); time.sleep(30)")
            process = popen([sys.executable, "-u", "-c", code], **kwargs)
            children.append(process)
            return process
        with mock.patch.object(events_mod.subprocess, "Popen", side_effect=child):
            with events_mod.ChangeWaiter([self.root], ["--terminal", "test-only"]) as waiter:
                self.assertTrue(waiter.wait(4))
                self.assertGreaterEqual(len(children), 2)
                reader = waiter.thread
            self.assertFalse(reader.is_alive())
        self.assertTrue(all(p.poll() is not None for p in children))

    def test_the_reader_runs_the_hc_it_was_given(self):
        started = []
        def child(argv, **kwargs):
            started.append(argv)
            raise OSError("not started in this test")
        with mock.patch.object(events_mod.subprocess, "Popen", side_effect=child):
            with events_mod.ChangeWaiter([self.root], ["--terminal", "test-only"], hc="/opt/tools/hc") as waiter:
                waiter.wait(0.5)
        self.assertTrue(started)
        self.assertEqual(started[0][:2], ["/opt/tools/hc", "events"])

    def test_shutdown_escalates_before_join_and_always_closes_files(self):
        waiter = events_mod.ChangeWaiter([self.root])
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("test-child", 3), 0]
        waiter.process, waiter.thread = process, mock.Mock()
        waiter.__exit__()
        process.kill.assert_called_once()
        waiter.thread.join.assert_called_once_with(timeout=4)
        self.assertFalse(waiter.files.active)




if __name__ == "__main__":
    unittest.main()
