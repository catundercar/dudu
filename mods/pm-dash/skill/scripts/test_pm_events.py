"""Run: python -m unittest discover -s mods/pm-dash/skill/scripts -p test_pm_events.py"""
import argparse
import contextlib
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
REAL_PM_HOME = os.environ.get("PM_HOME", "") if "pm" not in sys.modules else os.environ.get("PM_REAL_HOME", "")
if "pm" not in sys.modules:
    # As test_pm.py does: pm reads its ledger home and this session's terminal when it loads, and test_pm.py's
    # tests, run after these in one process, delete every task and registration in that ledger.
    os.environ.setdefault("PM_REAL_HOME", REAL_PM_HOME)
    os.environ["PM_HOME"] = tempfile.mkdtemp()
    os.environ.pop("HERDR_PANE_ID", None)
    os.environ.pop("HC_TERMINAL_ID", None)
import pm_events
import pm


def real_ledgers():
    """The ledgers of the person running the tests: ~/.claude/pm and ~/.dudu of the account's home, not of $HOME
    (which a run may have changed), and a PM_HOME they set before the run."""
    try:
        import pwd
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError, AttributeError):
        home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    found = [home / ".claude" / "pm", home / ".dudu"] + ([Path(REAL_PM_HOME)] if REAL_PM_HOME else [])
    return [p.resolve() for p in found]


def assert_temporary_ledger():
    """Stop before any test when pm's ledger is a real one: its tests delete every task and registration in it."""
    state, tmp = Path(pm.STATE).resolve(), Path(tempfile.gettempdir()).resolve()
    paths = [state] + [Path(getattr(pm, name)).resolve() for name in ("TASKS", "PMS", "INBOX", "PROJECTS")]
    near = [r for r in real_ledgers() for p in paths if p == r or r in p.parents or p in r.parents]
    if near or not all(p.is_relative_to(tmp) for p in paths) or pm.PANE:
        raise RuntimeError(f"{Path(__file__).name} would run against {state} (terminal {pm.PANE or 'none'}), "
                           "not a temporary ledger of its own; nothing was run")


# Never against a real ledger, whatever PM_HOME says and whichever test file loaded pm first.
assert_temporary_ledger()


def setUpModule():
    assert_temporary_ledger()
    # Nor start a deliverer (a ledger entry for a desktop-app PM does), which would type into this machine's real
    # terminals. Patched for this module's tests only, so test_pm.py still finds the real one, in either order.
    patch = mock.patch.object(pm, "deliver_later", lambda repo: None)
    patch.start()
    unittest.addModuleCleanup(patch.stop)

NATIVE = os.name == "nt" or sys.platform.startswith("linux") or hasattr(pm_events.select, "kqueue")


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
        with pm_events.ChangeWaiter([self.root], files=[target]) as waiter:
            self.assertTrue(waiter.files.active)
            self.assertFalse(waiter.wait(.03))
            target.write_text("first\n", encoding="utf-8")
            self.assertTrue(waiter.wait(2))
            # Drain any coalesced open/write notifications, then observe replace.
            drain(waiter)
            temp = self.root / ".new"
            temp.write_text("second\n", encoding="utf-8")
            pm_events.replace_task_file(temp, target)
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
        with pm_events.ChangeWaiter([self.root], files=[target]) as waiter:
            drain(waiter)
            with open(target, "a", encoding="utf-8") as f:
                f.write("new\n")
            self.assertTrue(waiter.wait(2))

    @unittest.skipUnless(NATIVE, "native supported platforms")
    def test_wakes_for_its_files_not_for_other_files_in_the_folder(self):
        mine, other = self.root / "mine.json", self.root / "other.json"
        mine.write_text("{}", encoding="utf-8")
        with pm_events.ChangeWaiter([self.root], files=[mine]) as waiter:
            drain(waiter)
            # Another task saved (tmp + rename), an offset rewritten in place: not this wait's business.
            temp = self.root / ".other.tmp"
            temp.write_text("{}", encoding="utf-8")
            pm_events.replace_task_file(temp, other)
            (self.root / "pm-a.offset").write_text("12", encoding="utf-8")
            self.assertFalse(waiter.wait(.3))
            temp = self.root / ".mine.tmp"
            temp.write_text('{"status": "review"}', encoding="utf-8")
            pm_events.replace_task_file(temp, mine)
            self.assertTrue(waiter.wait(2))

    @unittest.skipUnless(NATIVE, "native supported platforms")
    def test_sees_a_file_created_after_the_wait_began(self):
        log = self.root / "pm-new.log"
        with pm_events.ChangeWaiter([self.root], files=[log]) as waiter:
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
        events = pm_events.DirectoryEvents.__new__(pm_events.DirectoryEvents)
        events.files = [str(mine)]
        events.marks = {str(mine): pm_events.mark(mine)}
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
        events = pm_events.DirectoryEvents.__new__(pm_events.DirectoryEvents)
        events.files, events.marks = [str(mine)], {str(mine): pm_events.mark(mine)}
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

    def test_the_reader_runs_the_hc_it_was_given(self):
        started = []
        def child(argv, **kwargs):
            started.append(argv)
            raise OSError("not started in this test")
        with mock.patch.object(pm_events.subprocess, "Popen", side_effect=child):
            with pm_events.ChangeWaiter([self.root], ["--terminal", "test-only"], hc="/opt/tools/hc") as waiter:
                waiter.wait(0.5)
        self.assertTrue(started)
        self.assertEqual(started[0][:2], ["/opt/tools/hc", "events"])

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

    def test_a_desktop_watch_is_its_inbox_alone(self):
        # Worker states wake a watch only in the herdr TUI; on the desktop `wait` sees a worker stop, and a watch
        # woken by the same worker would wake the PM twice. It asks neither hc nor herdr about its workers.
        rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "repo": str(self.root)}
        (self.inbox / "pm-test.watch-states.json").write_text('{"hc:old":"working"}')
        real_waiter = pm_events.ChangeWaiter
        made = []
        def waiter(paths, hc_args, **kw):
            made.append(hc_args)
            return real_waiter(paths, hc_args, **kw)
        out = io.StringIO()
        with mock.patch.object(pm, "ChangeWaiter", side_effect=waiter), \
                mock.patch.object(pm, "hc", side_effect=AssertionError("hc asked")), \
                mock.patch.object(pm, "watched_agents", side_effect=AssertionError("agents asked")), \
                contextlib.redirect_stdout(out):
            pm.watch_notifications(argparse.Namespace(timeout=.3, interval=10), rec)
        self.assertEqual(out.getvalue(), "watch timeout\n")
        self.assertEqual(made, [None])
        pm.append_inbox("pm-test", "worker", "reported")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            pm.watch_notifications(argparse.Namespace(timeout=2, interval=10), rec)
        self.assertIn("reported", out.getvalue())

    def test_watch_first_run_keeps_old_unread_lines_then_delivers_between_runs(self):
        rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "repo": str(self.root)}
        args = argparse.Namespace(pm=None, repo=str(self.root), workspace=None, timeout=.05, interval=10)
        pm.append_inbox("pm-test", "worker", "first report")
        # No hc process in this test: exercise actual file notifications and locks.
        real_waiter = pm_events.ChangeWaiter
        with mock.patch.object(pm, "check_role"), mock.patch.object(pm, "current_pm_record", return_value=rec), \
                mock.patch.object(pm, "ChangeWaiter", side_effect=lambda paths, _, **kw: real_waiter(paths, **kw)):
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


    def test_wait_follows_a_replaced_worker_terminal(self):
        calls = []
        popen = subprocess.Popen
        def child(argv, **kwargs):
            calls.append(argv)
            return popen([sys.executable, "-u", "-c",
                          "import time; print('{\"terminals\": []}', flush=True); time.sleep(30)"], **kwargs)
        with mock.patch.object(pm_events.subprocess, "Popen", side_effect=child):
            with pm_events.ChangeWaiter([self.root], ["--terminal", "old"]) as waiter:
                self.assertTrue(waiter.wait(4))
                waiter.follow(["--terminal", "old"])  # the same terminal: nothing changes
                waiter.follow(["--terminal", "new"])
                self.assertTrue(waiter.wait(6))
        self.assertEqual([argv[-1] for argv in calls], ["old", "new"])

    def test_follow_starts_a_reader_again_after_it_ended(self):
        calls = []
        popen = subprocess.Popen
        def child(argv, **kwargs):
            calls.append(argv)
            return popen([sys.executable, "-u", "-c",
                          "import time; print('{\"terminals\": []}', flush=True); time.sleep(30)"], **kwargs)
        with mock.patch.object(pm_events.subprocess, "Popen", side_effect=child):
            with pm_events.ChangeWaiter([self.root], ["--terminal", "a"]) as waiter:
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
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.tasks, self.inbox, self.pms = self.root / "tasks", self.root / "inbox", self.root / "pms"
        for folder in (self.tasks, self.inbox, self.pms):
            folder.mkdir()
        for name, value in (("TASKS", self.tasks), ("INBOX", self.inbox), ("PMS", self.pms)):
            patch = mock.patch.object(pm, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.rec = {"name": "pm-test", "pane": "hc:test", "terminal": "test", "repo": str(self.root)}

    def watch(self, timeout=.2):
        real = pm_events.ChangeWaiter
        out = io.StringIO()
        with mock.patch.object(pm, "ChangeWaiter", side_effect=lambda paths, _, **kw: real(paths, **kw)), \
                contextlib.redirect_stdout(out):
            pm.watch_notifications(argparse.Namespace(timeout=timeout, interval=10), self.rec)
        return out.getvalue()

    def test_first_watch_delivers_only_the_newest_unread_lines(self):
        for n in range(1, 31):
            pm.append_inbox("pm-test", "worker", f"report {n}")
        out = self.watch()
        self.assertIn("report 30", out)
        self.assertIn("report 11", out)
        self.assertNotIn("report 10\n", out)
        self.assertIn("10 earlier lines are not shown", out)
        self.assertEqual(self.watch(), "watch timeout\n")

    def test_a_watcher_whose_starter_is_gone_stops_and_leaves_the_inbox_unread(self):
        pm.append_inbox("pm-test", "worker", "keep me")
        (self.inbox / "pm-test.offset").write_text("0")
        with mock.patch.object(pm.os, "getppid", side_effect=[100] + [1] * 20), self.assertRaises(SystemExit) as stop:
            self.watch(timeout=5)
        self.assertIn("what started it has gone", str(stop.exception.code))
        self.assertEqual((self.inbox / "pm-test.offset").read_text(), "0")
        self.assertIn("keep me", self.watch())

    def test_a_watch_that_prints_to_dev_null_is_noticed(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import pm; "
                "sys.exit(0 if pm.output_nowhere() else 1)")
        argv = [sys.executable, "-c", code, str(Path(pm.__file__).parent)]
        env = {**os.environ, "PM_HOME": str(self.root)}
        if os.name != "nt":
            self.assertEqual(subprocess.run(argv, stdout=subprocess.DEVNULL, env=env).returncode, 0)
        self.assertEqual(subprocess.run(argv, stdout=subprocess.PIPE, env=env).returncode, 1)
        with open(self.root / "out.txt", "w") as out:
            self.assertEqual(subprocess.run(argv, stdout=out, env=env).returncode, 1)

    @unittest.skipIf(os.name == "nt", "POSIX parents")
    def test_left_behind_is_told_by_who_adopted_the_process(self):
        with mock.patch.object(pm.sys, "platform", "darwin"):
            self.assertTrue(pm.adopted(1))
            self.assertFalse(pm.adopted(os.getpid()))
        names = {1: "claude", 7: "systemd", 8: "claude", 9: ""}
        with mock.patch.object(pm.sys, "platform", "linux"), \
                mock.patch.object(pm, "process_name", side_effect=lambda pid: names[pid]):
            self.assertTrue(pm.adopted(7))
            self.assertFalse(pm.adopted(8))
            self.assertFalse(pm.adopted(1))  # an agent running as a container's process 1
            names[1] = "init"
            self.assertTrue(pm.adopted(1))
            self.assertFalse(pm.adopted(9))

    def test_a_refused_second_watcher_says_what_holds_the_lock(self):
        for n in range(3):
            pm.append_inbox("pm-test", "worker", f"line {n}")
        (self.inbox / "pm-test.offset").write_text("0")
        report = pm.watcher_report("pm-test", os.getpid())
        self.assertIn(f"already running (pid {os.getpid()})", report)
        self.assertIn("unread lines in", report)
        self.assertIn(": 3", report)
        if os.name != "nt":
            self.assertIn("command:", report)
            self.assertIn("started by: pid", report)

    def test_without_pm_events_waits_fall_back_to_timed_looks(self):
        with mock.patch.object(pm, "ChangeWaiter", None), mock.patch.object(pm.time, "sleep") as sleep:
            with pm.change_waiter([self.inbox], None, files=[]) as waiter:
                self.assertTrue(waiter.wait(3600))
        sleep.assert_called_once_with(pm.WAIT_POLL)

    def registered(self, folder, repo=None):
        folder.mkdir(parents=True, exist_ok=True)
        rec = {"name": f"pm-{folder.name}", "repo": str(repo or folder), "pane": "w1:p1"}
        (self.pms / f"{pm.project_slug(str(folder))}.json").write_text(json.dumps(rec))
        return rec

    def notify(self, repo, pane="", labels=None, session=""):
        """cmd_notify from this pane; labels: what `hc get` says this terminal carries (in this core session)."""
        out = io.StringIO()
        def hc(*args, **kw):
            return {"labels": labels} if labels and args[:2] == ("get", pane[3:]) else None
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        with mock.patch.object(pm, "agents", return_value=[]), mock.patch.object(pm, "hc", side_effect=hc), \
                mock.patch.object(pm, "PANE", pane), \
                mock.patch.object(pm, "HC_TERMINAL", pane[3:] if pane.startswith("hc:") else ""), \
                mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(pm.Path, "home", return_value=self.root / "home"), contextlib.redirect_stdout(out):
            pm.cmd_notify(argparse.Namespace(text="done", repo=str(repo) if repo else None))
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
        self.assertIn("] done", (self.inbox / "pm-suite.log").read_text())

    def test_notify_goes_to_the_pm_of_the_task_this_terminal_works_on(self):
        project, elsewhere = self.root / "home/p/app", self.root / "home/scratch/x"
        self.registered(project)
        elsewhere.mkdir(parents=True)
        (self.tasks / "app-fix.json").write_text(json.dumps(
            {"id": "app-fix", "repo": str(project), "pane": "hc:t9", "status": "in_progress", "updated": "1"}))
        here = os.getcwd()
        os.chdir(elsewhere)  # no --repo: run in a folder that is in no PM's project
        self.addCleanup(os.chdir, here)
        # This terminal's own label in this core names the task.
        self.notify(None, pane="hc:t9", labels={"task": "app-fix"})
        self.assertEqual((self.inbox / "pm-app.log").read_text().count("] done"), 1)
        # The task recorded this Claude Code session as its agent (herdr TUI: no label to read).
        (self.tasks / "app-fix.json").write_text(json.dumps(
            {"id": "app-fix", "repo": str(project), "pane": "w1:p3", "status": "in_progress", "updated": "1",
             "session": {"kind": "claude", "id": "s-1"}}))
        self.notify(None, pane="w1:p3", session="s-1")
        self.assertEqual((self.inbox / "pm-app.log").read_text().count("] done"), 2)
        # --repo names a project: one without a PM is an error, never this task's PM.
        with self.assertRaises(SystemExit) as stop:
            self.notify(elsewhere, pane="w1:p3", session="s-1")
        self.assertIn("nothing was delivered, and not to another PM either", str(stop.exception.code))
        self.assertEqual((self.inbox / "pm-app.log").read_text().count("] done"), 2)

    def test_notify_does_not_trust_a_pane_number_alone(self):
        # herdr TUI sessions repeat pane ids: a task of another session's w1:p3 is not this one's.
        project, mine = self.root / "home/p/app", self.root / "home/p/mine"
        self.registered(project)
        self.registered(mine)
        (self.tasks / "app-fix.json").write_text(json.dumps(
            {"id": "app-fix", "repo": str(project), "pane": "w1:p3", "status": "in_progress", "updated": "1",
             "session": {"kind": "claude", "id": "someone-else"}}))
        here = os.getcwd()
        os.chdir(mine)
        self.addCleanup(os.chdir, here)
        self.notify(None, pane="w1:p3", session="s-2")  # no --repo, so the task would come first if it matched
        self.assertFalse((self.inbox / "pm-app.log").exists())
        self.assertIn("] done", (self.inbox / "pm-mine.log").read_text())
        # Nor a hc terminal number whose own labels name no task (an address reused after removal).
        (self.tasks / "app-fix.json").write_text(json.dumps(
            {"id": "app-fix", "repo": str(project), "pane": "hc:t9", "status": "in_progress", "updated": "1"}))
        self.notify(None, pane="hc:t9", labels={"pm": "other"})
        self.assertFalse((self.inbox / "pm-app.log").exists())
        self.assertEqual((self.inbox / "pm-mine.log").read_text().count("] done"), 2)

    @unittest.skipUnless(shutil.which("git"), "git makes the nested repository")
    def test_notify_from_a_nested_repository_with_a_pm_of_its_own_goes_to_its_tasks_pm(self):
        project = self.root / "home/work/suite"
        self.registered(project)
        nested = project / "service"
        self.registered(nested)  # the nested repository has a PM of its own
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        (self.tasks / "suite-fix.json").write_text(json.dumps(
            {"id": "suite-fix", "repo": str(project), "pane": "hc:t9", "status": "in_progress", "updated": "1"}))
        here = os.getcwd()
        os.chdir(nested)
        self.addCleanup(os.chdir, here)
        self.notify(None, pane="hc:t9", labels={"task": "suite-fix"})  # no --repo: the task's PM
        self.assertIn("] done", (self.inbox / "pm-suite.log").read_text())
        self.notify(nested, pane="hc:t9", labels={"task": "suite-fix"})  # --repo names the project
        self.assertIn("] done", (self.inbox / "pm-service.log").read_text())

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
        self.assertEqual(list(self.inbox.glob("*.log")), [])


if __name__ == "__main__":
    unittest.main()
