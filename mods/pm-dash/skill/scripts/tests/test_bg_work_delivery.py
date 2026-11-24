"""Stage 7c tests: background work in procs/wait/stalls, stall-after-report guard,
PM delivery policy (`manager_ready_for_batch`) with probe boundaries, and 15-min delivery-delay notice."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SCRIPTS / "tests") not in sys.path:
    sys.path.insert(0, str(SCRIPTS / "tests"))

from fakes import FakeChangeWaiter, FakeClock, FakeHc, FakeProcs, make_ctx  # noqa: E402
from pmlib import procs as procs_mod  # noqa: E402
from pmlib.errors import WaitOutcome  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.deliverer import Deliverer  # noqa: E402
from pmlib.events.policy import manager_ready_for_batch  # noqa: E402
from pmlib.events.stalls import StallWatcher, stop_state  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.terminals.hc import TerminalInfo  # noqa: E402
from pmlib.workers.wait import wait_for_report_events_for  # noqa: E402


def _register_hc_pm(ctx, repo: str, terminal: str = "t7") -> dict:
    slug = project_slug(repo)
    rec = {
        "name": f"pm-{slug}",
        "project": Path(repo).name,
        "repo": repo,
        "runtime": "hc",
        "terminal": terminal,
        "pane": f"hc:{terminal}",
        "agent": "claude",
    }
    ctx.home.registrations.mkdir(parents=True, exist_ok=True)
    ctx.home.registration(slug).write_text(json.dumps(rec), encoding="utf-8")
    return rec


def _write_task(ctx, task: dict) -> dict:
    ctx.home.tasks.mkdir(parents=True, exist_ok=True)
    ctx.home.task(task["id"]).write_text(json.dumps(task), encoding="utf-8")
    return task


def _append_turn_log(ctx, pane: str, event: str, at: str = "2026-11-23 08:00") -> None:
    ctx.home.root.mkdir(parents=True, exist_ok=True)
    with open(ctx.home.turn_log, "a", encoding="utf-8") as f:
        f.write(f"{at} [{pane}] {event}: turn\n")


class BackgroundWorkProcsTests(unittest.TestCase):
    def test_background_work_lives_in_procs_layer1_and_accepts_dict_or_terminal_info(self):
        snap = "/bin/zsh -c source /Users/me/.claude/shell-snapshots/snapshot-zsh-1.sh 2>/dev/null || true && eval "
        ps_out = "\n".join([
            "  100     1 /bin/zsh -lic claude",
            "  101   100 claude --model opus",
            f"  102   101 {snap}'python3 /x/pm.py wait demo-a --timeout 3600' < /dev/null && pwd -P >| /tmp/cwd",
            f"  104   101 {snap}'python3 tests/run_checks.py' < /dev/null && pwd -P >| /tmp/cwd",
            "  106   101 node mcp-server.js",
            f"  200     1 {snap}'git merge other' < /dev/null && pwd -P >| /tmp/cwd",
        ])
        fake_run = lambda argv, **kw: type("R", (), {"returncode": 0, "stdout": ps_out, "stderr": ""})()
        with mock.patch.object(procs_mod.osutil, "WINDOWS", False), mock.patch.object(subprocess, "run", fake_run):
            self.assertEqual(procs_mod.background_work({"pid": 100}), ["python3 tests/run_checks.py"])
            self.assertEqual(
                procs_mod.background_work(TerminalInfo(address="t1", pid=100)),
                ["python3 tests/run_checks.py"],
            )
            self.assertEqual(procs_mod.background_work({}), [])
            self.assertEqual(procs_mod.background_work(None), [])
            self.assertEqual(procs_mod.background_work(TerminalInfo(address="t1", pid=None)), [])

    def test_processes_port_exposes_background_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_ctx(tmp)
            real_procs = procs_mod.Processes(ctx.home)
            with mock.patch.object(procs_mod, "background_work", return_value=["sleep 30"]) as spy:
                self.assertEqual(real_procs.background_work({"pid": 42}), ["sleep 30"])
            spy.assert_called_once_with({"pid": 42})


class WorkerBackgroundWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def test_wait_treats_idle_and_done_with_background_work_as_still_working(self):
        for term_state in ("idle", "done"):
            with self.subTest(term_state=term_state):
                clk = FakeClock(mono=0.0)
                bg_running = [True]
                hc = FakeHc(
                    terminals={"t20": {"state": "live", "pid": 100, "status": {"state": term_state}}},
                    clock=clk,
                )
                ctx = make_ctx(self.tmp.name + f"-{term_state}", hc=hc, clock=clk)
                ctx.procs = FakeProcs(
                    ctx.home,
                    env=ctx.env,
                    background_work=lambda info: ["pytest -q"] if bg_running[0] else [],
                )
                task = _write_task(ctx, {
                    "id": "demo-w",
                    "title": "work",
                    "repo": self.repo,
                    "base": "main",
                    "branch": "dev/w",
                    "status": "in_progress",
                    "pane": "hc:t20",
                    "dispatched": True,
                    "log": [],
                })

                ticks = [0]

                class _Stepper:
                    def wait(self, timeout):
                        ticks[0] += 1
                        clk.advance(3.0)
                        if ticks[0] == 4:
                            # 12s elapsed (> WAIT_POLL=5s) while bg command ran; now worker reports review.
                            _write_task(ctx, {
                                **task,
                                "status": "review",
                                "commit": "abc1234",
                                "log": [{"at": "2026-11-23 08:01", "by": "hc:t20", "text": "status=review; done"}],
                            })

                res = wait_for_report_events_for(ctx, "demo-w", _Stepper(), task, timeout=30)
                self.assertEqual(res.status, "review")
                self.assertGreaterEqual(ticks[0], 4)

                # Once background work stops, WAIT_POLL without report raises WaitOutcome(code=3).
                bg_running[0] = False
                _write_task(ctx, task)

                class _ClockAdvancer:
                    def wait(self, timeout):
                        clk.advance(max(timeout, 1.0))

                with self.assertRaises(WaitOutcome) as exc:
                    wait_for_report_events_for(ctx, "demo-w", _ClockAdvancer(), task, timeout=30)
                self.assertEqual(exc.exception.code, 3)

    def test_stop_state_treats_idle_and_done_with_background_work_as_working(self):
        idle_info = {"state": "live", "pid": 100, "turn": 2, "status": {"state": "idle"}}
        done_info = {"state": "live", "pid": 100, "turn": 2, "status": {"state": "done"}}
        blocked_info = {"state": "live", "pid": 100, "turn": 2, "status": {"state": "blocked"}}
        gone_info = {"state": "exited", "pid": 100, "turn": 2}
        self.assertEqual(stop_state(idle_info, hooked=False, base=1, background_active=True), "")
        self.assertEqual(stop_state(done_info, hooked=False, base=1, background_active=True), "")
        self.assertEqual(stop_state(idle_info, hooked=False, base=1, background_active=False), "idle")
        self.assertEqual(stop_state(done_info, hooked=False, base=1, background_active=False), "idle")
        self.assertEqual(stop_state(blocked_info, hooked=False, base=1, background_active=True), "blocked")
        self.assertEqual(stop_state(gone_info, hooked=False, base=1, background_active=True), "gone")

    def test_watch_workers_does_not_stall_unhooked_worker_while_background_work_runs(self):
        clk = FakeClock(mono=0.0)
        bg = [True]
        hc = FakeHc(
            terminals={"t20": {"state": "live", "pid": 100, "turn": 2, "status": {"state": "idle"}}},
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        ctx.procs = FakeProcs(
            ctx.home,
            env=ctx.env,
            background_work=lambda info: ["npm test"] if bg[0] else [],
        )
        _register_hc_pm(ctx, self.repo, "t7")
        task = _write_task(ctx, {
            "id": "demo-agy",
            "title": "agy task",
            "repo": self.repo,
            "project": "demo",
            "status": "in_progress",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t20", "at": "2026-11-23 08:00", "turn": 1},
        })
        watcher = StallWatcher(ctx, stall_grace=5)
        stops, bases = {}, {}
        watcher.watch_workers([task], stops, bases)
        clk.advance(10.0)
        watcher.watch_workers([task], stops, bases)
        self.assertEqual(Conversation(ctx, self.repo).events(), [])
        self.assertEqual(stops, {})

        # Once background work finishes, grace period starts and stall fires after 5s.
        bg[0] = False
        watcher.watch_workers([task], stops, bases)
        self.assertEqual(Conversation(ctx, self.repo).events(), [])
        clk.advance(6.0)
        watcher.watch_workers([task], stops, bases)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "stall")


class StallAfterReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def test_stalled_skips_when_task_status_is_review_blocked_or_done(self):
        for status in ("review", "blocked", "done"):
            with self.subTest(status=status):
                ctx = make_ctx(self.tmp.name + f"-{status}")
                _register_hc_pm(ctx, self.repo, "t7")
                task = _write_task(ctx, {
                    "id": f"demo-{status}",
                    "title": status,
                    "repo": self.repo,
                    "project": "demo",
                    "status": status,
                    "pane": "hc:t20",
                    "dispatched": True,
                })
                StallWatcher(ctx).stalled(task, "the worker stopped without reporting", key="t20:idle:2")
                self.assertEqual(Conversation(ctx, self.repo).events(), [])
                self.assertEqual(ctx.procs.spawned, [])

    def test_stalled_skips_when_disk_task_already_moved_to_review_blocked_or_done(self):
        for status in ("review", "blocked", "done"):
            with self.subTest(status=status):
                ctx = make_ctx(self.tmp.name + f"-disk-{status}")
                _register_hc_pm(ctx, self.repo, "t7")
                stale_snapshot = {
                    "id": f"demo-disk-{status}",
                    "title": status,
                    "repo": self.repo,
                    "project": "demo",
                    "status": "in_progress",
                    "pane": "hc:t20",
                    "dispatched": True,
                }
                _write_task(ctx, {**stale_snapshot, "status": status})
                StallWatcher(ctx).stalled(stale_snapshot, "the worker stopped without reporting", key="t20:idle:2")
                self.assertEqual(Conversation(ctx, self.repo).events(), [])
                self.assertEqual(ctx.procs.spawned, [])

    def test_watch_workers_skips_tasks_in_review_blocked_or_done_and_mid_read_report(self):
        clk = FakeClock(mono=0.0)
        hc = FakeHc(
            terminals={"t20": {"state": "live", "turn": 2, "status": {"state": "idle"}, "screen": "done"}},
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        for status in ("review", "blocked", "done"):
            task = _write_task(ctx, {
                "id": f"demo-agy-{status}",
                "title": status,
                "repo": self.repo,
                "project": "demo",
                "status": status,
                "pane": "hc:t20",
                "dispatched": True,
                "worker": {"kind": "agy"},
                "round": {"terminal": "t20", "at": "2026-11-23 08:00", "turn": 1},
            })
            stops, bases = {}, {}
            watcher = StallWatcher(ctx, stall_grace=5)
            watcher.watch_workers([task], stops, bases)
            clk.advance(10.0)
            watcher.watch_workers([task], stops, bases)
        self.assertEqual(Conversation(ctx, self.repo).events(), [])

        # Race: task is in_progress at grace expiry, then worker writes status=review while hc.read(term) runs.
        race_task = _write_task(ctx, {
            "id": "demo-race",
            "title": "race",
            "repo": self.repo,
            "project": "demo",
            "status": "in_progress",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t20", "at": "2026-11-23 08:00", "turn": 1},
        })
        orig_read = hc.read

        def _read_and_report(term, **kw):
            _write_task(ctx, {**race_task, "status": "review"})
            return orig_read(term, **kw)

        hc.read = _read_and_report
        stops, bases = {}, {}
        watcher = StallWatcher(ctx, stall_grace=5)
        watcher.watch_workers([race_task], stops, bases)
        clk.advance(6.0)
        watcher.watch_workers([race_task], stops, bases)
        self.assertEqual(Conversation(ctx, self.repo).events(), [])


class ManagerReadyForBatchPolicyTests(unittest.TestCase):
    def test_pure_policy_table(self):
        cases = [
            # (term_info, last_turn_stopped, expected)
            (TerminalInfo(address="t7", agent_state="idle"), False, (True, True)),
            (TerminalInfo(address="t7", agent_state="idle"), True, (True, True)),
            (TerminalInfo(address="t7", agent_state="done"), False, (True, False)),
            (TerminalInfo(address="t7", agent_state="done"), True, (True, False)),
            (TerminalInfo(address="t7", agent_state="working", status_msg="1 shell still running"), True, (True, False)),
            (TerminalInfo(address="t7", agent_state="working", status_msg="2 shells still running"), True, (True, False)),
            (TerminalInfo(address="t7", agent_state="working", status_msg="1 shell still running"), False, (False, False)),
            (TerminalInfo(address="t7", agent_state="working", status_msg=""), True, (False, False)),
            (TerminalInfo(address="t7", agent_state="working", status_msg="thinking"), True, (False, False)),
            (TerminalInfo(address="t7", agent_state="blocked", status_msg="confirm?"), True, (False, False)),
            (TerminalInfo(address="t7", agent_state="error", status_msg="boom"), True, (False, False)),
            (TerminalInfo(address="t7", agent_state=""), True, (False, False)),
            # Dict form also supported
            ({"state": "live", "status": {"state": "working", "msg": "1 shell still running"}}, True, (True, False)),
            ({"state": "live", "status": {"state": "working", "msg": "1 shell still running"}}, False, (False, False)),
            ({"state": "live", "status": {"state": "idle"}}, False, (True, True)),
            (None, True, (False, False)),
        ]
        for info, stopped, expected in cases:
            with self.subTest(info=info, stopped=stopped):
                self.assertEqual(manager_ready_for_batch(info, stopped), expected)


class DelivererBackgroundShellAndBoundariesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def test_delivers_without_if_idle_when_bg_shell_working_and_stop_fired(self):
        clk = FakeClock(mono=0.0)
        hc = FakeHc(
            terminals={"t7": {"state": "live", "status": {"state": "working", "msg": "1 shell still running"}}},
            clock=clk,
        )
        send_if_flags = []
        orig_send = hc.send

        def _spy_send(term, text, *, if_state=None, timeout=180, errors=False):
            send_if_flags.append(if_state)
            return orig_send(term, text, if_state=if_state, timeout=timeout, errors=errors)

        hc.send = _spy_send
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        _append_turn_log(ctx, "hc:t7", "UserPromptSubmit")
        _append_turn_log(ctx, "hc:t7", "Stop")
        Conversation(ctx, self.repo).record("event", by="ci", text="worker ready", source="external:ci", wake=True)

        d = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)
        due = d.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(due, 0)
        self.assertEqual(send_if_flags, [None])
        self.assertEqual(len(hc.sent), 1)
        self.assertIn("worker ready", hc.sent[0][1])

    def test_holds_when_bg_shell_working_but_stop_not_fired_after_last_prompt(self):
        clk = FakeClock(mono=0.0)
        hc = FakeHc(
            terminals={"t7": {"state": "live", "status": {"state": "working", "msg": "1 shell still running"}}},
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        Conversation(ctx, self.repo).record("event", by="ci", text="worker ready", source="external:ci", wake=True)
        d = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)

        # No turns.log yet -> hold
        d.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(hc.sent, [])

        # Another pane stopped -> still hold
        _append_turn_log(ctx, "hc:t99", "Stop")
        d.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(hc.sent, [])

        # PM Stop then PM UserPromptSubmit -> still hold
        _append_turn_log(ctx, "hc:t7", "Stop")
        _append_turn_log(ctx, "hc:t7", "UserPromptSubmit")
        d.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(hc.sent, [])

    def test_boundary1_working_started_true_blocks_second_send_until_new_stop(self):
        clk = FakeClock(mono=0.0)
        hc = FakeHc(
            terminals={"t7": {"state": "live", "status": {"state": "working", "msg": "1 shell still running"}}},
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        _append_turn_log(ctx, "hc:t7", "UserPromptSubmit")
        _append_turn_log(ctx, "hc:t7", "Stop")
        Conversation(ctx, self.repo).record("event", by="ci", text="first event", source="external:ci", wake=True)

        d = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)
        self.assertEqual(d.look(FakeChangeWaiter(), {}, {}), 0)
        self.assertEqual(len(hc.sent), 1)

        # Second event arrives while terminal is still working (started:true returned immediately in working mode,
        # and no new Stop hook has fired yet). Deliverer must NOT send a second batch yet.
        Conversation(ctx, self.repo).record("event", by="ci", text="second event", source="external:ci", wake=True)
        d.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(len(hc.sent), 1)

        # Even if another PM logs Stop, our PM still has no new Stop.
        _append_turn_log(ctx, "hc:t99", "Stop")
        d.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(len(hc.sent), 1)

        # Once our PM's new Stop fires, the second batch is delivered.
        _append_turn_log(ctx, "hc:t7", "Stop", at="2026-11-23 08:02")
        self.assertEqual(d.look(FakeChangeWaiter(), {}, {}), 0)
        self.assertEqual(len(hc.sent), 2)
        self.assertIn("second event", hc.sent[1][1])

    def test_boundary2_draft_submitted_during_working_send_race_with_bring_pending(self):
        clk = FakeClock(mono=0.0)
        hc = FakeHc(
            terminals={"t7": {"state": "live", "status": {"state": "working", "msg": "1 shell still running"}}},
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        _append_turn_log(ctx, "hc:t7", "UserPromptSubmit")
        _append_turn_log(ctx, "hc:t7", "Stop")
        Conversation(ctx, self.repo).record("event", by="ci", text="race event", source="external:ci", wake=True)

        brought_texts = []
        orig_send = hc.send

        def _send_while_user_submits_draft(term, text, *, if_state=None, timeout=180, errors=False):
            # User hits Enter while hc send is holding for draft -> UserPromptSubmit runs bring_pending() first.
            brought = Delivery(ctx, self.repo, settle=0).bring_pending()
            brought_texts.append(brought)
            # ~0.2s later, hc send (without --if idle) pastes the same batch and returns started:true.
            return orig_send(term, text, if_state=if_state, timeout=timeout, errors=errors)

        hc.send = _send_while_user_submits_draft
        d = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)
        self.assertEqual(d.look(FakeChangeWaiter(), {}, {}), 0)

        self.assertEqual(len(brought_texts), 1)
        self.assertIn("race event", brought_texts[0])
        self.assertEqual(len(hc.sent), 1)
        sent_batch = hc.sent[0][1]
        end = ctx.home.project_for(self.repo).conversation.stat().st_size
        self.assertEqual(d.delivered_offset(), end)
        self.assertEqual(d.received_ranges(), [[0, end]])

        # Subcase A: Claude Code takes pasted batch in mid-turn (late=True) -> idempotent, no repeat warning.
        r_late = Delivery(ctx, self.repo, settle=0).took_delivery(sent_batch, late=True)
        self.assertFalse(r_late.repeated)
        self.assertIsNone(r_late.warning)

        # Subcase B: Claude Code fires a separate UserPromptSubmit for the pasted batch -> repeat warning emitted.
        r_dup = Delivery(ctx, self.repo, settle=0).took_delivery(sent_batch)
        self.assertTrue(r_dup.repeated)
        self.assertIn("repeat", r_dup.warning or "")


class DeliveryDelayNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def test_records_one_shot_deliver_stall_event_after_warn_seconds_and_resets_after_delivery(self):
        clk = FakeClock(mono=100.0)
        hc = FakeHc(
            terminals={"t7": {"state": "live", "status": {"state": "working", "msg": "running tests"}}},
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        Conversation(ctx, self.repo).record("event", by="ci", text="build failed", source="external:ci", wake=True)

        d = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)
        changes = FakeChangeWaiter()

        # t=100: starts waiting_since, no stall notice yet.
        d.look(changes, {}, {})
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("source") == "deliver-stall"]
        self.assertEqual(stalls, [])

        # t=999 (899s elapsed): still no stall notice.
        clk.advance(899.0)
        due = d.look(changes, {}, {})
        self.assertLessEqual(due, 1.0)
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("source") == "deliver-stall"]
        self.assertEqual(stalls, [])

        # t=1000 (900s elapsed): records one-shot deliver-stall event with wake=False and terminal state/msg.
        clk.advance(1.0)
        d.look(changes, {}, {})
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("source") == "deliver-stall"]
        self.assertEqual(len(stalls), 1)
        self.assertEqual(stalls[0]["type"], "event")
        self.assertFalse(stalls[0]["wake"])
        self.assertIn("working", stalls[0]["text"])
        self.assertIn("running tests", stalls[0]["text"])

        # t=1500: still one-shot (no duplicate).
        clk.advance(500.0)
        d.look(changes, {}, {})
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("source") == "deliver-stall"]
        self.assertEqual(len(stalls), 1)

        # PM becomes idle: batch is delivered, and deliver-stall (wake=False) is NOT sent as news.
        hc.terminals["t7"]["status"] = {"state": "idle"}
        self.assertEqual(d.look(changes, {}, {}), 0)
        self.assertEqual(len(hc.sent), 1)
        self.assertIn("build failed", hc.sent[0][1])
        self.assertNotIn("deliver-stall", hc.sent[0][1])

        # A subsequent 900s stall on a new batch records a fresh notice.
        hc.terminals["t7"]["status"] = {"state": "blocked", "msg": "permission dialog"}
        Conversation(ctx, self.repo).record("event", by="ci", text="second alert", source="external:ci", wake=True)
        d.look(changes, {}, {})
        clk.advance(900.0)
        d.look(changes, {}, {})
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("source") == "deliver-stall"]
        self.assertEqual(len(stalls), 2)
        self.assertIn("blocked", stalls[1]["text"])
        self.assertIn("permission dialog", stalls[1]["text"])

    def test_deliver_warn_seconds_config_and_held_back_notice(self):
        clk = FakeClock(mono=0.0)
        hc = FakeHc(
            terminals={"t7": {"state": "live", "status": {"state": "idle"}}},
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk, config={"deliver_warn_seconds": 120})
        _register_hc_pm(ctx, self.repo, "t7")
        Conversation(ctx, self.repo).record("event", by="ci", text="held alert", source="external:ci", wake=True)

        d = Deliverer(ctx, self.repo, watchers=(), holds=(lambda r: True,), settle=0)
        d.look(FakeChangeWaiter(), {}, {})
        clk.advance(120.0)
        d.look(FakeChangeWaiter(), {}, {})
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("source") == "deliver-stall"]
        self.assertEqual(len(stalls), 1)
        self.assertFalse(stalls[0]["wake"])
        self.assertIn("held back", stalls[0]["text"])
        self.assertIn("idle", stalls[0]["text"])


class FinalReviewR2StallAndRaceRegressions(unittest.TestCase):
    """Reproduction tests for Pass-2 final-review r2 findings (Focus 3 `land_approved` stalls & Focus 4 draft race)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def test_approve_via_helper_when_worker_exited_does_not_emit_false_stall(self):
        from pmlib.landing import ApproveRequest, Landing
        from pmlib.ledger.ledger import Ledger

        clk = FakeClock("2026-11-23 09:00:00", mono=10.0)
        hc = FakeHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "exited"},
            },
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, pane="hc:t7", hc=hc, clock=clk)
        ctx.git.branches.update({"main", "dev/feat"})
        ctx.git.checkouts[(self.repo, "dev/feat")] = str(self.repo_path)
        _register_hc_pm(ctx, self.repo, "t7")
        Ledger(ctx).create({
            "id": "demo-feat",
            "title": "Feature",
            "project": "demo",
            "repo": self.repo,
            "status": "review",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "branch": "dev/feat",
            "base": "main",
            "commit": ctx.git.rev_parse(self.repo, "dev/feat", short=True),
            "worker": {"kind": "claude"},
            "round": {"terminal": "t20", "at": "2026-11-23 08:50", "turn": 1},
        })

        Landing(ctx).approve(ApproveRequest(id="demo-feat"))
        self.assertEqual((ctx.store.task("demo-feat").get("land_approved") or {}).get("executor"), "helper")

        sw = StallWatcher(ctx, stall_grace=0)
        sw.sweep_exited(self.repo)
        watched = [t.raw for t in Ledger(ctx).project_tasks(self.repo) if sw.watched_worker(t.raw)]
        sw.watch_workers(watched, {}, {})

        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertEqual(stalls, [])

    def test_approved_merge_in_unhooked_worker_with_active_land_lock_does_not_stall(self):
        from pmlib.store import lock_file, unlock_file

        clk = FakeClock("2026-11-23 09:00:00", mono=10.0)
        hc = FakeHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "live", "pid": 500, "turn": 2, "status": {"state": "idle"}},
            },
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        task = _write_task(ctx, {
            "id": "demo-agy-merge",
            "title": "Merge task",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t20", "at": "2026-11-23 08:55", "turn": 1},
            "land_approved": {"commit": "abc1234", "at": "2026-11-23 08:59", "by": "hc:t7", "executor": "worker"},
        })
        lock_path = ctx.home.lock(f"land-{project_slug(self.repo)}")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock_fh:
            lock_file(lock_fh)
            try:
                sw = StallWatcher(ctx, stall_grace=5)
                stops: dict = {}
                bases: dict = {}
                sw.watch_workers([task], stops, bases)
                clk.advance(6.0)
                sw.watch_workers([task], stops, bases)
            finally:
                unlock_file(lock_fh)

        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertEqual(stalls, [])

    def test_approved_merge_claude_worker_stop_hook_does_not_ask_for_review_status(self):
        hc = FakeHc(terminals={
            "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
            "t20": {"state": "live", "turn": 3, "status": {"state": "working"}},
        })
        ctx = make_ctx(
            self.tmp.name,
            pane="hc:t20",
            hc_terminal="t20",
            hc=hc,
            env={"CLAUDE_CODE_SESSION_ID": "sid-w20"},
        )
        _register_hc_pm(ctx, self.repo, "t7")
        _write_task(ctx, {
            "id": "demo-claude-merge",
            "title": "Claude merge",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "claude"},
            "land_approved": {"commit": "abc1234", "at": "2026-11-23 08:59", "by": "hc:t7", "executor": "worker"},
        })
        block = StallWatcher(ctx).worker_stopped({})
        self.assertFalse(block and "--status review|blocked" in block.get("reason", ""), block)

    def test_draft_enter_race_on_done_pm_records_stop_offset_so_next_batch_waits_for_turn_end(self):
        class _DraftRaceHc(FakeHc):
            def __init__(self, *args, on_send=None, **kwargs):
                super().__init__(*args, **kwargs)
                self._on_send = on_send

            def send(self, address: str, text: str, **kwargs):
                res = super().send(address, text, **kwargs)
                if self._on_send is not None:
                    self._on_send(address, text, kwargs)
                return res

        clk = FakeClock("2026-11-23 09:00:00", mono=10.0)
        ctx_holder: list = []

        def _during_draft_wait(addr: str, text: str, kw: dict) -> None:
            # While `hc send` (without --if idle because state=='done') waited on the user's draft:
            # 1. User hit Enter -> UserPromptSubmit ran bring_pending() (already consuming batch 1),
            # 2. User's quick turn started a background shell and logged Stop, leaving hc status 'working' (bg shell),
            # 3. ~200ms later hc send pasted batch 1 into t7 and returned started=True (batch 1's turn is now running!).
            c = ctx_holder[0]
            _append_turn_log(c, "hc:t7", "UserPromptSubmit", "2026-11-23 09:00")
            c.delivery.bring_pending()
            _append_turn_log(c, "hc:t7", "Stop", "2026-11-23 09:00")
            c.hc.terminals["t7"]["status"] = {"state": "working", "msg": "1 shell still running"}
            self._on_send_ran = True

        self._on_send_ran = False
        hc = _DraftRaceHc(
            terminals={"t7": {"state": "live", "status": {"state": "done"}}},
            clock=clk,
            on_send=_during_draft_wait,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        ctx.delivery = Delivery(ctx, self.repo, settle=0)
        ctx_holder.append(ctx)
        _register_hc_pm(ctx, self.repo, "t7")
        _append_turn_log(ctx, "hc:t7", "Stop", "2026-11-23 08:55")

        conv = Conversation(ctx, self.repo)
        conv.record("event", by="ci", text="batch-1", source="external:ci", wake=True)
        d = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)
        changes = FakeChangeWaiter()

        self.assertEqual(d.look(changes, {}, {}), 0)
        self.assertTrue(self._on_send_ran)
        self.assertEqual(len(hc.sent), 1)
        # Clear hook callback for subsequent sends; batch-1's turn has NOT logged its own Stop yet!
        hc._on_send = None
        conv.record("event", by="ci", text="batch-2", source="external:ci", wake=True)
        d.look(changes, {}, {})
        self.assertEqual(len(hc.sent), 1, "batch-2 was sent while batch-1's turn was still running!")


class LandApproveStallAndFallbackTests(unittest.TestCase):
    """Tests for #249: approve send failure fallback and land_approved timeout monitoring -> auto helper handoff."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    @staticmethod
    def _approve_runs(ctx):
        return [r for r in ctx.procs.ran if len(r["argv"]) >= 3 and r["argv"][2] == "approve"]

    def test_deliver_send_started_false_on_agy_approve_falls_back_to_helper_and_wakes_pm(self):
        from pmlib.workers.service import Workers

        class _SilentNoStartHc(FakeHc):
            def send(self, term: str, text: str, **kwargs):
                return {"ok": True, "started": False, "status": {"state": "idle"}}

        clk = FakeClock("2026-11-23 09:00:00", mono=10.0)
        hc = _SilentNoStartHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "live", "turn": 5, "status": {"state": "idle"}},
            },
            clock=clk,
        )
        ctx = make_ctx(
            self.tmp.name, hc=hc, clock=clk,
            env={"PM_HELPER_NAME": "stale-helper", "PM_HELPER_OWNER": "pm"},
        )
        _register_hc_pm(ctx, self.repo, "t7")
        _write_task(ctx, {
            "id": "demo-agy-send-fail",
            "title": "Agy merge send fail",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t20", "at": "2026-11-23 09:00", "turn": 5},
            "land_approved": {
                "commit": "abc1234",
                "at": "2026-11-23 09:00:00",
                "by": "hc:t7",
                "executor": "worker",
                "message": "- merge feat",
                "keep": True,
                "timeout": 420,
                "note": "- deploy after merge",
            },
        })
        msg_file = Path(self.tmp.name) / "approve-msg.txt"
        msg_file.write_text("[from hc:t7] PM approved merging task demo-agy-send-fail", encoding="utf-8")

        Workers(ctx).deliver_send(
            "t20", msg_file, unlink=True, task_id="demo-agy-send-fail", repo=self.repo, pre_turn=5, timeout=30
        )

        # Must alert PM via waking stall event
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertEqual(len(stalls), 1, stalls)
        self.assertTrue(stalls[0].get("wake"))
        self.assertIn("started=false", stalls[0]["text"])
        self.assertIn("--via helper", stalls[0]["text"])

        # Must synchronously run `pm.py approve <id> --via helper` with --flag=val and stripped PM_HELPER_*
        approve_runs = self._approve_runs(ctx)
        self.assertEqual(len(approve_runs), 1, ctx.procs.ran)
        args = approve_runs[0]["argv"][2:]
        self.assertEqual(args[:4], ["approve", "demo-agy-send-fail", "--via", "helper"])
        self.assertIn("--commit=abc1234", args)
        self.assertIn("--message=- merge feat", args)
        self.assertIn("--keep", args)
        self.assertIn("--timeout=420", args)
        self.assertIn("--note=- deploy after merge", args)
        env = approve_runs[0]["env"]
        self.assertEqual(env.get("HC_TERMINAL_ID"), "t7")
        self.assertFalse(any(k.startswith("PM_HELPER_") for k in env), env)

        # Ledger marks fallback_at for deduplication
        saved = ctx.store.task("demo-agy-send-fail")
        self.assertTrue((saved.get("land_approved") or {}).get("fallback_at"))

    def test_helper_handoff_failure_preserves_approval_and_reports_error_to_pm(self):
        import subprocess
        from fakes import FakeProcs

        clk = FakeClock("2026-11-23 09:10:00", mono=10.0)
        hc = FakeHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "live", "turn": 5, "status": {"state": "idle"}},
            },
            clock=clk,
        )
        base_ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        failing_procs = FakeProcs(
            base_ctx.home,
            env=base_ctx.env,
            runner=lambda entry: subprocess.CompletedProcess(
                entry["argv"], 1, "", "refused: helpers.max (3) reached"
            ),
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk, procs=failing_procs)
        _register_hc_pm(ctx, self.repo, "t7")
        task = _write_task(ctx, {
            "id": "demo-helper-fail",
            "title": "Helper start refused",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t20", "at": "2026-11-23 09:00", "turn": 5},
            "land_approved": {
                "commit": "abc1234",
                "at": "2026-11-23 09:00:00",
                "by": "hc:t7",
                "executor": "worker",
            },
        })

        sw = StallWatcher(ctx, stall_grace=0, land_approve_timeout=300)
        sw.watch_workers([task], {}, {})

        # Concrete error reported to PM (and does NOT falsely claim handed off)
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertEqual(len(stalls), 1, stalls)
        self.assertIn("helpers.max (3) reached", stalls[0]["text"])
        self.assertNotIn("automatically handed off", stalls[0]["text"])

        # Original land_approved is preserved, fallback_at cleared, task remains watched
        saved = ctx.store.task("demo-helper-fail")
        la = saved.get("land_approved") or {}
        self.assertEqual(la.get("executor"), "worker")
        self.assertEqual(la.get("commit"), "abc1234")
        self.assertNotIn("fallback_at", la)
        self.assertTrue(la.get("fallback_failed_at"))
        self.assertIn("helpers.max (3) reached", la.get("fallback_error", ""))
        self.assertTrue(sw.watched_worker(saved))

        # Repeated watch_workers does not spam approve --via helper
        sw.watch_workers([saved], {}, {})
        self.assertEqual(len(self._approve_runs(ctx)), 1)

    def test_landing_approve_via_helper_rollback_restores_prior_approval(self):
        from pmlib.errors import Refused
        from pmlib.landing import ApproveRequest, Landing
        from pmlib.ledger.ledger import Ledger
        from unittest import mock

        clk = FakeClock("2026-11-23 09:00:00", mono=10.0)
        hc = FakeHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "live", "turn": 5, "status": {"state": "idle"}},
            },
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, pane="hc:t7", hc=hc, clock=clk)
        ctx.git.branches.update({"main", "dev/feat"})
        ctx.git.checkouts[(self.repo, "dev/feat")] = str(self.repo_path)
        _register_hc_pm(ctx, self.repo, "t7")
        sha = ctx.git.rev_parse(self.repo, "dev/feat", short=True)
        prior_la = {"commit": sha, "at": "2026-11-23 08:55:00", "by": "hc:t7", "executor": "worker"}
        Ledger(ctx).create({
            "id": "demo-rollback",
            "title": "Rollback test",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "branch": "dev/feat",
            "base": "main",
            "commit": sha,
            "land_approved": dict(prior_la),
        })

        landing = Landing(ctx)
        with mock.patch.object(landing, "_start", side_effect=Refused("helpers.max reached")):
            with self.assertRaises(Refused):
                landing.approve(ApproveRequest(id="demo-rollback", via="helper"))

        saved = ctx.store.task("demo-rollback")
        self.assertEqual(saved.get("land_approved"), prior_la)

    def test_deliver_send_does_not_swallow_failure_when_fallback_returns_false(self):
        from pmlib.store import lock_file, unlock_file
        from pmlib.workers.service import Workers

        class _SilentNoStartHc(FakeHc):
            def send(self, term: str, text: str, **kwargs):
                return {"ok": True, "started": False, "status": {"state": "idle"}}

        clk = FakeClock("2026-11-23 09:00:00", mono=10.0)
        hc = _SilentNoStartHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "live", "turn": 5, "status": {"state": "idle"}},
            },
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        _write_task(ctx, {
            "id": "demo-lock-conflict",
            "title": "Send fail while sibling holds land lock",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "land_approved": {
                "commit": "abc1234",
                "at": "2026-11-23 09:00:00",
                "by": "hc:t7",
                "executor": "worker",
            },
        })
        msg_file = Path(self.tmp.name) / "approve-msg2.txt"
        msg_file.write_text("[from hc:t7] PM approved merging task demo-lock-conflict", encoding="utf-8")

        lock_path = ctx.home.lock(f"land-{project_slug(self.repo)}")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock_fh:
            lock_file(lock_fh)
            try:
                Workers(ctx).deliver_send(
                    "t20", msg_file, unlink=True, task_id="demo-lock-conflict", repo=self.repo, pre_turn=5, timeout=30
                )
            finally:
                unlock_file(lock_fh)

        # Fallback returned False (land lock held), so deliver_send MUST record failure note & wake PM
        self.assertEqual(self._approve_runs(ctx), [])
        _, _, items = Delivery(ctx, self.repo, settle=0).pending_batch()
        self.assertEqual(len(items), 1, items)
        self.assertIn("started=false", items[0]["event"]["text"])

    def test_land_approved_timeout_idle_worker_triggers_alert_and_helper_without_duplicates(self):
        clk = FakeClock("2026-11-23 09:00:00", mono=10.0)
        hc = FakeHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "live", "turn": 5, "status": {"state": "idle"}},
            },
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk, config={"land_approve_timeout": 300})
        _register_hc_pm(ctx, self.repo, "t7")
        task = _write_task(ctx, {
            "id": "demo-timeout",
            "title": "Timeout merge",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t20", "at": "2026-11-23 09:00", "turn": 5},
            "land_approved": {
                "commit": "def5678",
                "at": "2026-11-23 09:00:00",
                "by": "hc:t7",
                "executor": "worker",
            },
        })

        d = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)
        changes = FakeChangeWaiter()
        stops: dict = {}
        bases: dict = {}

        # Before timeout (4 minutes elapsed): no alert, no helper run, due respects remaining timeout
        clk.advance(240.0)
        due = d.look(changes, stops, bases)
        self.assertIsNotNone(due)
        self.assertLessEqual(due, 60.0)
        self.assertEqual(self._approve_runs(ctx), [])
        self.assertEqual([e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"], [])

        # Past timeout (5m10s elapsed): worker still idle at turn=5 -> triggers alert + helper handoff
        clk.advance(70.0)
        d.look(changes, stops, bases)
        approve_runs = self._approve_runs(ctx)
        self.assertEqual(len(approve_runs), 1, ctx.procs.ran)
        self.assertEqual(approve_runs[0]["argv"][2:6], ["approve", "demo-timeout", "--via", "helper"])
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertEqual(len(stalls), 1, stalls)
        self.assertTrue(stalls[0].get("wake"))
        # Deliverer also delivers the waking stall batch to the idle PM
        self.assertTrue(any("demo-timeout" in text for _, text in hc.sent), hc.sent)

        # Deduplication: repeated looks and direct watch_workers with stale task snapshot must NOT re-trigger
        clk.advance(120.0)
        d.look(changes, stops, bases)
        StallWatcher(ctx, stall_grace=0, land_approve_timeout=300).watch_workers([task], stops, bases)
        self.assertEqual(len(self._approve_runs(ctx)), 1)
        self.assertEqual(len([e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]), 1)

    def test_land_approved_timeout_does_not_trigger_when_land_lock_active(self):
        from pmlib.store import lock_file, unlock_file

        clk = FakeClock("2026-11-23 09:10:00", mono=10.0)
        hc = FakeHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "live", "turn": 5, "status": {"state": "idle"}},
            },
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        task = _write_task(ctx, {
            "id": "demo-locked",
            "title": "Active merge lock",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t20", "at": "2026-11-23 09:00", "turn": 5},
            "land_approved": {
                "commit": "abc1234",
                "at": "2026-11-23 09:00:00",
                "by": "hc:t7",
                "executor": "worker",
            },
        })
        lock_path = ctx.home.lock(f"land-{project_slug(self.repo)}")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock_fh:
            lock_file(lock_fh)
            try:
                StallWatcher(ctx, stall_grace=0, land_approve_timeout=300).watch_workers([task], {}, {})
            finally:
                unlock_file(lock_fh)

        self.assertEqual(self._approve_runs(ctx), [])
        self.assertEqual([e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"], [])
        self.assertFalse((ctx.store.task("demo-locked").get("land_approved") or {}).get("fallback_at"))

    def test_land_approved_timeout_exited_worker_triggers_helper_and_working_or_hc_down_does_not(self):
        clk = FakeClock("2026-11-23 09:10:00", mono=10.0)
        hc = FakeHc(
            terminals={
                "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
                "t20": {"state": "live", "turn": 5, "status": {"state": "working"}},
                "t21": {"state": "exited"},
            },
            clock=clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        working_task = _write_task(ctx, {
            "id": "demo-working",
            "title": "Still working on conflicts",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t20",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t20", "at": "2026-11-23 09:00", "turn": 5},
            "land_approved": {"commit": "aaa1111", "at": "2026-11-23 09:00:00", "by": "hc:t7", "executor": "worker"},
        })
        exited_task = _write_task(ctx, {
            "id": "demo-exited",
            "title": "Worker exited",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "owner": "pm",
            "pane": "hc:t21",
            "dispatched": True,
            "worker": {"kind": "agy"},
            "round": {"terminal": "t21", "at": "2026-11-23 09:00", "turn": 5},
            "land_approved": {"commit": "bbb2222", "at": "2026-11-23 09:00:00", "by": "hc:t7", "executor": "worker"},
        })

        StallWatcher(ctx, stall_grace=0, land_approve_timeout=300).watch_workers([working_task, exited_task], {}, {})

        approve_runs = self._approve_runs(ctx)
        self.assertEqual([r["argv"][3] for r in approve_runs], ["demo-exited"])
        self.assertFalse((ctx.store.task("demo-working").get("land_approved") or {}).get("fallback_at"))
        self.assertTrue((ctx.store.task("demo-exited").get("land_approved") or {}).get("fallback_at"))

        # When hc is unreachable (get_raw returns None), treat as transient error and do NOT trigger fallback
        hc.server_running = False
        StallWatcher(ctx, stall_grace=0, land_approve_timeout=300).watch_workers([working_task], {}, {})
        self.assertEqual(len(self._approve_runs(ctx)), 1)
        self.assertFalse((ctx.store.task("demo-working").get("land_approved") or {}).get("fallback_at"))


if __name__ == "__main__":
    unittest.main()
