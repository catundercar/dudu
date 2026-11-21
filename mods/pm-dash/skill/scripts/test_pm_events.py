"""Run: python -m unittest discover -s mods/pm-dash/skill/scripts -p test_pm_events.py"""
import argparse
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

sys.path.insert(0, str(Path(__file__).parent))
import pm_events
import pm


class NativeEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "native supported platforms")
    def test_append_atomic_replace_and_no_busy_wait(self):
        with pm_events.ChangeWaiter([self.root]) as waiter:
            self.assertTrue(waiter.files.active)
            self.assertFalse(waiter.wait(.03))
            target = self.root / "inbox.log"
            target.write_text("first\n", encoding="utf-8")
            self.assertTrue(waiter.wait(2))
            # Drain any coalesced open/write notifications, then observe replace.
            while waiter.wait(.03):
                pass
            temp = self.root / ".new"
            temp.write_text("second\n", encoding="utf-8")
            pm_events.replace_task_file(temp, target)
            self.assertTrue(waiter.wait(2))
            thread = waiter.files.thread
        self.assertFalse(thread.is_alive())

    def test_hints_queued_before_wait_are_not_lost_and_are_coalesced(self):
        with pm_events.ChangeWaiter([self.root]) as waiter:
            for _ in range(100):
                waiter.wake()
            self.assertEqual(waiter.queue.qsize(), 1)
            self.assertTrue(waiter.wait(.1))
            self.assertFalse(waiter.wait(.01))

    @unittest.skipUnless(os.name == "nt", "Windows sharing conflicts")
    def test_task_replacement_retries_transient_but_not_permanent_denial(self):
        source = mock.Mock()
        source.replace.side_effect = [PermissionError(), PermissionError(), None]
        with mock.patch.object(pm_events.time, "sleep") as sleep:
            pm_events.replace_task_file(source, self.root / "task.json")
            self.assertEqual(source.replace.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            source.replace.side_effect = PermissionError()
            with self.assertRaises(PermissionError):
                pm_events.replace_task_file(source, self.root / "task.json")
            self.assertEqual(source.replace.call_count, 9)

    def test_fallback_is_explicit_and_bounded(self):
        with mock.patch.object(pm_events, "DirectoryEvents", side_effect=OSError("unsupported")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            with pm_events.ChangeWaiter([self.root]) as waiter:
                self.assertIsNone(waiter.files)
                with mock.patch.object(waiter.queue, "get", side_effect=pm_events.queue.Empty) as get:
                    self.assertFalse(waiter.wait(3600))
                    get.assert_called_once_with(timeout=60)
        self.assertIn("reconciling every 60s", err.getvalue())

    def test_only_relevant_facts_wake_the_pm(self):
        for message in ({"terminals": []}, {"method": "missed"},
                        {"method": "event", "params": {"type": "status"}},
                        {"method": "event", "params": {"type": "lost"}}):
            self.assertTrue(pm_events.relevant_fact(message))
        for message in (None, [], {}, {"method": "heartbeat"},
                        {"method": "event", "params": {"type": "title"}},
                        {"method": "event", "params": {"type": "output"}}):
            self.assertFalse(pm_events.relevant_fact(message))

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
        with mock.patch.object(pm_events.subprocess, "Popen", side_effect=child):
            with pm_events.ChangeWaiter([self.root], ["--terminal", "test-only"]) as waiter:
                self.assertTrue(waiter.wait(4))
                self.assertGreaterEqual(len(children), 2)
                reader = waiter.thread
            self.assertFalse(reader.is_alive())
        self.assertTrue(all(p.poll() is not None for p in children))

    def test_shutdown_escalates_before_join_and_always_closes_files(self):
        waiter = pm_events.ChangeWaiter([self.root])
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("test-child", 3), 0]
        waiter.process, waiter.thread = process, mock.Mock()
        waiter.__exit__()
        process.kill.assert_called_once()
        waiter.thread.join.assert_called_once_with(timeout=4)
        self.assertFalse(waiter.files.active)


class PMNotifications(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tasks, self.inbox = self.root / "tasks", self.root / "inbox"
        self.tasks.mkdir()
        self.inbox.mkdir()
        for name, value in (("TASKS", self.tasks), ("INBOX", self.inbox)):
            patch = mock.patch.object(pm, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(pm, "config", return_value={})
        patch.start()
        self.addCleanup(patch.stop)
        self.task = {"id": "test", "repo": str(self.root), "base": "main",
                     "status": "in_progress", "log": []}
        self.write_task(self.task)

    def write_task(self, task):
        temp = self.tasks / ".test.tmp"
        temp.write_text(json.dumps(task), encoding="utf-8")
        pm_events.replace_task_file(temp, self.tasks / "test.json")

    def test_report_wakes_without_polling_or_a_notify_command(self):
        reported = {**self.task, "status": "review", "log": [{"text": "verified event report"}]}
        timer = threading.Timer(.15, self.write_task, [reported])
        out = io.StringIO()
        with mock.patch.object(pm, "worker_state", return_value="") as state, \
                mock.patch.object(pm, "git_state", return_value=(1, False)), \
                contextlib.redirect_stdout(out):
            timer.start()
            try:
                pm.wait_for_report(argparse.Namespace(id="test", timeout=3))
            finally:
                timer.join()
        self.assertIn("verified event report", out.getvalue())
        self.assertLessEqual(state.call_count, 3)

    def test_duplicate_events_do_not_shorten_unreported_worker_grace(self):
        class Pulses:
            at = 0
            calls = 0
            def wait(self, timeout):
                self.calls += 1
                self.at += min(.05 if self.calls < 10 else timeout, timeout)
        pulses = Pulses()
        with mock.patch.object(pm.time, "monotonic", lambda: pulses.at), \
                mock.patch.object(pm, "worker_state", return_value="idle"), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
            pm.wait_for_report_events(argparse.Namespace(id="test", timeout=30), pulses, self.task)
        self.assertEqual(stop.exception.code, 3)
        self.assertGreaterEqual(pulses.at, 5)
        self.assertGreaterEqual(pulses.calls, 10)

    def test_reattached_terminal_gets_its_own_grace_period(self):
        self.task["pane"] = "hc:old"
        self.write_task(self.task)
        owner = self
        class Replacement:
            at = 0
            def wait(self, timeout):
                if self.at == 0:
                    self.at = 4.9
                    owner.write_task({**owner.task, "pane": "hc:new"})
                else:
                    self.at += timeout
        changes = Replacement()
        with mock.patch.object(pm.time, "monotonic", lambda: changes.at), \
                mock.patch.object(pm, "worker_state", return_value="idle"), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
            pm.wait_for_report_events(argparse.Namespace(id="test", timeout=30), changes, self.task)
        self.assertEqual(stop.exception.code, 3)
        self.assertGreaterEqual(changes.at, 9.9)

    def test_removed_worker_wakes_desktop_watch_from_a_persisted_snapshot(self):
        rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "repo": str(self.root)}
        args = argparse.Namespace(timeout=1, interval=10)
        (self.inbox / "pm-test.watch-states.json").write_text('{"hc:old":"working"}')
        real_waiter = pm_events.ChangeWaiter
        out = io.StringIO()
        with mock.patch.object(pm, "ChangeWaiter", side_effect=lambda paths, _: real_waiter(paths)), \
                mock.patch.object(pm, "watched_hc_agents", return_value={}), contextlib.redirect_stdout(out):
            pm.watch_notifications(args, rec)
        self.assertEqual(out.getvalue(), "hc:old working->removed\n")

    def test_new_worker_that_exits_before_the_next_snapshot_is_reported(self):
        rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "repo": str(self.root)}
        args = argparse.Namespace(timeout=1, interval=10)
        (self.inbox / "pm-test.watch-states.json").write_text('{}')
        real_waiter = pm_events.ChangeWaiter
        out = io.StringIO()
        with mock.patch.object(pm, "ChangeWaiter", side_effect=lambda paths, _: real_waiter(paths)), \
                mock.patch.object(pm, "watched_hc_agents", return_value={"hc:fast": "exited"}), \
                contextlib.redirect_stdout(out):
            pm.watch_notifications(args, rec)
        self.assertEqual(out.getvalue(), "hc:fast new:exited\n")

    def test_watch_first_run_keeps_old_unread_lines_then_delivers_between_runs(self):
        rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "repo": str(self.root)}
        args = argparse.Namespace(pm=None, repo=str(self.root), workspace=None, timeout=.05, interval=10)
        pm.append_inbox("pm-test", "worker", "first report")
        # No hc process in this test: exercise actual file notifications and locks.
        real_waiter = pm_events.ChangeWaiter
        with mock.patch.object(pm, "check_role"), mock.patch.object(pm, "current_pm_record", return_value=rec), \
                mock.patch.object(pm, "ChangeWaiter", side_effect=lambda paths, _: real_waiter(paths)), \
                mock.patch.object(pm, "watched_hc_agents", return_value={}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                pm.cmd_watch(args)
            self.assertIn("first report", out.getvalue())
            self.assertIsNone(pm.watcher_pid("pm-test"))
            pm.append_inbox("pm-test", "worker", "between runs")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                pm.cmd_watch(args)
            self.assertIn("between runs", out.getvalue())
            self.assertNotIn("first report", out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                pm.cmd_watch(args)
            self.assertEqual(out.getvalue(), "watch timeout\n")

    def test_desktop_snapshot_excludes_other_projects_and_the_pm(self):
        rec = {"name": "pm-test", "pane": "hc:t1", "repo": "mine"}
        terms = [
            {"address": "t1", "state": "live", "status": {"state": "working"}},
            {"address": "t2", "parent": "t1", "state": "live", "status": {"state": "blocked"}},
            {"address": "t3", "parent": "another", "state": "live", "status": {"state": "done"}},
            {"address": "t4", "state": "exited", "status": None},
        ]
        with mock.patch.object(pm, "hc", return_value={"terminals": terms}), \
                mock.patch.object(pm, "all_tasks", return_value=[{"pane": "hc:t4", "repo": "mine"}]):
            self.assertEqual(pm.watched_hc_agents(rec), {"hc:t2": "blocked", "hc:t4": "exited"})

    def test_compact_hc_ls_rows_are_expanded_before_reading_status(self):
        rec = {"name": "pm-test", "pane": "hc:t1", "repo": "mine"}
        def hc(*args, **kwargs):
            if args[0] == "ls":
                return {"terminals": [{"address": "t2", "state": "live", "agent": "claude"},
                                      {"address": "other", "state": "live"}]}
            self.assertEqual(args, ("get", "t2"))
            return {"address": "t2", "state": "live", "status": {"state": "working"}}
        with mock.patch.object(pm, "hc", side_effect=hc) as calls, \
                mock.patch.object(pm, "all_tasks", return_value=[{"pane": "hc:t2", "repo": "mine"}]):
            self.assertEqual(pm.watched_hc_agents(rec), {"hc:t2": "working"})
            self.assertEqual(calls.call_count, 2)

    def test_flat_status_from_an_older_core_is_supported(self):
        with mock.patch.object(pm, "hc", return_value={"terminals": [
                {"address": "t2", "state": "live", "status": "working"}]}), \
                mock.patch.object(pm, "all_tasks", return_value=[{"pane": "hc:t2", "repo": "mine"}]):
            self.assertEqual(pm.watched_hc_agents({"pane": "hc:t1", "repo": "mine"}), {"hc:t2": "working"})


if __name__ == "__main__":
    unittest.main()
