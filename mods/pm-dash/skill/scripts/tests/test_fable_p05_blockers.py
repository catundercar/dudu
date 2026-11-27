"""Regression suite converting all Fable Phase 0-5 final review blocker repros (B1-B4)
and adjacent non-blocking hardening items (N1, N4, F2) into permanent unit tests."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
FIXTURES = TESTS_DIR / "fixtures" / "turn_journals"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

if "pmlib.context" not in sys.modules:
    _saved = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = "/nonexistent/pm-home-fable-blockers"
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved

from fakes import make_ctx  # noqa: E402
from pmlib import hooks, osutil  # noqa: E402
from pmlib.agents.turn_adapters import adapter_for  # noqa: E402
from pmlib.caller import Caller  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.events.supervisor import EndpointDriver, ProjectSupervisor  # noqa: E402
from pmlib.messaging.address import LogicalAddress  # noqa: E402
from pmlib.messaging.envelope import P1_USER, P4_BATCH, Envelope, new_env_id  # noqa: E402
from pmlib.messaging.mailbox import MailboxStore  # noqa: E402
from pmlib.messaging.principal import Principal  # noqa: E402
from pmlib.procs import Processes  # noqa: E402
from pmlib.project import turn_reducer as tr  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.turn_state import TurnTracker  # noqa: E402
from test_messaging_replay import TestMessagingReplay  # noqa: E402
from test_worker_supervision import WorkerSupervisionTests  # noqa: E402


class B1SilentTurnAndLateStopTests(unittest.TestCase):
    """B1: late async Stop / step_reply amends `silent` to `replied` and withdraws recovery;
    terminal Esc (`silent` / `interrupted`) emits zero recovery actions within 120s."""

    def test_b1_late_stop_real_journal_and_synthetic_user_turn(self) -> None:
        cfg = tr.TurnConfig()

        # Part 1: real sanitized journal slice (`journal-late-stop-2026-11-26.jsonl`)
        rows = [
            json.loads(line)
            for line in (FIXTURES / "journal-late-stop-2026-11-26.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        st = tr.default_state_v2(cfg)
        by_seq: dict[int, dict] = {}
        for row in rows:
            if row.get("kind") == "turn_summary":
                continue
            st = tr.reduce(st, row, cfg)
            by_seq[int(row["seq"])] = st

        self.assertEqual(by_seq[93]["last_turn"]["outcome"], "silent")
        self.assertIsNone(by_seq[93]["incident"])
        self.assertEqual(by_seq[95]["last_turn"]["outcome"], "replied")
        self.assertIsNone(by_seq[95]["incident"])
        self.assertEqual(by_seq[96]["last_turn"]["outcome"], "replied")
        t95 = [r["t"] for r in rows if r["seq"] == 95][0]
        for dt_s in range(1, 121):
            st, acts = tr.tick(st, t95 + dt_s * 1_000, cfg)
            self.assertEqual([a for a in acts if a.get("kind") == "recovery_action"], [])

        # Part 2: synthetic user-caused Claude Code turn where Stop arrives 49ms after hc `done`
        t0 = 1_795_000_000_000
        ep = {"runtime": "hc", "machine": None, "terminal": "t1", "agent_kind": "claude", "fg_pid": 100, "epoch": 1}
        st2 = tr.default_state_v2(cfg)
        st2 = tr.reduce(st2, {"src": "supervisor", "kind": "hc_state", "t": t0 - 60_000, "state": "live", "status": "idle", "status_ms": t0 - 60_000, "turn": 6, "reported": True, "endpoint": ep}, cfg)
        st2 = tr.reduce(st2, {"src": "hook", "kind": "hook_prompt", "t": t0, "terminal": "t1", "agent_kind": "claude", "cause": "user", "msg_ids": ["u-1"], "hc_turn": 0, "session_id": "s"}, cfg)
        st2 = tr.reduce(st2, {"src": "supervisor", "kind": "hc_state", "t": t0 + 500, "state": "live", "status": "working", "status_ms": t0 + 100, "turn": 6, "reported": True, "endpoint": ep}, cfg)
        st2 = tr.reduce(st2, {"src": "supervisor", "kind": "hc_state", "t": t0 + 15_000, "state": "live", "status": "done", "status_ms": t0 + 14_990, "turn": 7, "reported": True, "endpoint": ep}, cfg)
        self.assertEqual(st2["last_turn"]["outcome"], "silent")
        self.assertIsNone(st2["incident"])
        st2 = tr.reduce(st2, {"src": "hook", "kind": "hook_stop", "t": t0 + 15_049, "expected_seq": st2["turn"]["seq"], "has_reply": True}, cfg)
        self.assertEqual(st2["last_turn"]["outcome"], "replied")
        self.assertIsNone(st2["incident"])
        for dt_s in range(1, 121):
            st2, acts2 = tr.tick(st2, t0 + 15_049 + dt_s * 1_000, cfg)
            self.assertEqual([a for a in acts2 if a.get("kind") == "recovery_action"], [])

        # Part 3: pre-existing `silent` W2 incident with zero actions is withdrawn if late `step_reply` arrives
        st3 = tr.default_state_v2(cfg)
        st3["turn"]["seq"] = 3
        st3["last_turn"] = {"id": "hc:local:t1:100:3", "seq": 3, "cause": "deliver", "outcome": "silent", "started_ms": t0, "ended_ms": t0 + 5_000, "duration_ms": 5_000}
        tr._open_incident(st3, cls="W2", turn_id="hc:local:t1:100:3", turn_seq=3, cause_kind="deliver", msg_ids=[], batch=[0, 50], reason="silent", now_ms=t0 + 5_000, cfg=cfg)
        st3 = tr.reduce(st3, {"src": "transcript:claude", "kind": "step_reply", "t": t0 + 4_950}, cfg)
        self.assertEqual(st3["last_turn"]["outcome"], "replied")
        self.assertIsNone(st3["incident"])

    def test_b1_terminal_esc_emits_zero_recovery_actions_within_120s(self) -> None:
        cfg = tr.TurnConfig()
        t0 = 1_795_000_000_000
        ep = {"runtime": "hc", "machine": None, "terminal": "t1", "agent_kind": "agy", "fg_pid": 100, "epoch": 1}
        hc = lambda t, status, turn, sms: {
            "src": "supervisor", "kind": "hc_state", "t": t, "state": "live",
            "status": status, "status_ms": sms, "turn": turn, "reported": True, "endpoint": ep,
        }
        st = tr.default_state_v2(cfg)
        st = tr.reduce(st, hc(t0 - 60_000, "idle", 6, t0 - 60_000), cfg)
        st = tr.reduce(st, {"src": "hook", "kind": "hook_prompt", "t": t0, "terminal": "t1", "agent_kind": "agy", "cause": "user", "msg_ids": ["u-1"], "hc_turn": 0, "session_id": "s"}, cfg)
        st = tr.reduce(st, hc(t0 + 500, "working", 6, t0 + 100), cfg)
        st = tr.reduce(st, {"src": "watcher:agy", "kind": "step_tool_start", "t": t0 + 4_000, "tool": "run_command", "summary": "rm -rf build"}, cfg)
        st = tr.reduce(st, {"src": "watcher:agy", "kind": "step_tool_end", "t": t0 + 6_000}, cfg)
        st = tr.reduce(st, hc(t0 + 9_000, "idle", 7, t0 + 8_990), cfg)
        self.assertEqual(st["last_turn"]["outcome"], "silent")
        self.assertIsNone(st.get("incident"))
        for dt_s in range(1, 121):
            st, acts = tr.tick(st, t0 + 9_000 + dt_s * 1_000, cfg)
            self.assertEqual([a for a in acts if a.get("kind") == "recovery_action"], [], f"unexpected recovery at +{dt_s}s")

        # Claude transcript `[Request interrupted by user]` maps to `step_interrupted` -> `outcome == "interrupted"`
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "claude.jsonl"
            p.write_text(
                json.dumps({
                    "type": "user",
                    "timestamp": "2026-11-26T23:00:09Z",
                    "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]},
                }) + "\n",
                encoding="utf-8",
            )
            obs, _ = adapter_for("claude").steps(p, 0)
            self.assertEqual([o["kind"] for o in obs], ["step_interrupted"])
            st_int = tr.reduce(st, {**obs[0], "t": t0 + 9_020}, cfg)
            self.assertEqual(st_int["last_turn"]["outcome"], "interrupted")

        # Positive error evidence (`step_error`) closing via `hc idle` STILL opens W2 and schedules `continue_turn` at +20s!
        st_err = tr.default_state_v2(cfg)
        st_err = tr.reduce(st_err, hc(t0 - 10_000, "idle", 1, t0 - 10_000), cfg)
        st_err = tr.reduce(st_err, {"src": "hook", "kind": "hook_prompt", "t": t0, "terminal": "t1", "agent_kind": "agy", "cause": "user", "msg_ids": ["u-err"], "hc_turn": 1}, cfg)
        st_err = tr.reduce(st_err, hc(t0 + 100, "working", 1, t0 + 100), cfg)
        st_err = tr.reduce(st_err, {"src": "transcript:agy", "kind": "step_error", "t": t0 + 2_000, "message": "upstream stream reset"}, cfg)
        st_err = tr.reduce(st_err, hc(t0 + 3_000, "idle", 2, t0 + 3_000), cfg)
        self.assertEqual(st_err["last_turn"]["outcome"], "errored")
        self.assertEqual(st_err["incident"]["class"], "W2")
        _, acts_err = tr.tick(st_err, t0 + 24_000, cfg)
        rec_err = [a for a in acts_err if a.get("kind") == "recovery_action"]
        self.assertEqual([(a["class"], a["action"]) for a in rec_err], [("W2", "continue_turn")])


class B1BatchLateStopSupervisorTests(TestMessagingReplay):
    """End-to-end supervisor + driver regression: batch turn closed on hc idle 49ms before Stop hook is NOT re-queued at +25s."""

    def test_batch_closed_silent_before_late_stop_never_redelivers_after_25s(self) -> None:
        tracker = TurnTracker(self.ctx, self.repo_dir)
        Conversation(self.ctx, self.repo_dir).record("event", by="worker-1", text="review passed", source="worker", wake=True)
        dlv = Delivery(self.ctx, self.repo_dir, settle=0)
        start, end, items = dlv.pending_batch()
        now_ms = int(self.clock.time() * 1000)
        batch_env_id = new_env_id(now_ms)
        tracker.pm_mailbox.enqueue(
            Envelope(
                env_id=batch_env_id,
                idempotency_key=f"batch:{self.slug}:{start}-{end}",
                schema_version=1,
                created_ms=now_ms,
                kind="event.batch",
                sender=Principal.supervisor(self.slug),
                recipient=LogicalAddress.pm(self.slug),
                project=self.slug,
                cause={"kind": "deliver_batch", "start": start, "end": end},
                priority=P4_BATCH,
                body={"text": dlv.batch_text(start, end, items, env_id=batch_env_id), "start": start, "end": end},
                require_reply=True,
            ),
            initial_state="accepted",
        )
        reg = self.ctx.store.registration(self.slug) or {}
        driver = EndpointDriver(self.ctx, self.repo_dir)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 1)

        dlv.took_delivery(self.hc.sent[0][1])
        tseq = tracker.begin_turn(terminal="hc:t1", agent_kind="claude", cause="deliver", batch=[start, end], from_hook=True)
        row = self.hc._mutable_dict("t1")
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self.clock.advance(1.0)
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))

        # Supervisor sees hc `done` BEFORE async Stop hook arrives
        self.clock.advance(5.0)
        row.update({"status": {"state": "done"}, "turn": 2, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))

        # 49ms later, Stop hook arrives
        self.clock.advance(0.05)
        tracker.end_turn(expected_seq=tseq, has_reply=True)

        # Advance 35s past W2's 20s retry1 window -> zero re-deliveries!
        for _ in range(7):
            self.clock.advance(5.0)
            sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
            driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 1)
        self.assertEqual(tracker.read()["last_turn"]["outcome"], "replied")
        self.assertIsNone(tracker.read().get("incident"))

    def _run_transient_error_late_stop_batch(self, error_msg: str) -> None:
        tracker = TurnTracker(self.ctx, self.repo_dir)
        Conversation(self.ctx, self.repo_dir).record("event", by="worker-1", text="review passed", source="worker", wake=True)
        dlv = Delivery(self.ctx, self.repo_dir, settle=0)
        start, end, items = dlv.pending_batch()
        now_ms = int(self.clock.time() * 1000)
        batch_env_id = new_env_id(now_ms)
        tracker.pm_mailbox.enqueue(
            Envelope(
                env_id=batch_env_id,
                idempotency_key=f"batch:{self.slug}:{start}-{end}",
                schema_version=1,
                created_ms=now_ms,
                kind="event.batch",
                sender=Principal.supervisor(self.slug),
                recipient=LogicalAddress.pm(self.slug),
                project=self.slug,
                cause={"kind": "deliver_batch", "start": start, "end": end},
                priority=P4_BATCH,
                body={"text": dlv.batch_text(start, end, items, env_id=batch_env_id), "start": start, "end": end},
                require_reply=True,
            ),
            initial_state="accepted",
        )
        reg = self.ctx.store.registration(self.slug) or {}
        driver = EndpointDriver(self.ctx, self.repo_dir)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 1)

        dlv.took_delivery(self.hc.sent[0][1])
        tseq = tracker.begin_turn(terminal="hc:t1", agent_kind="claude", cause="deliver", batch=[start, end], from_hook=True)
        row = self.hc._mutable_dict("t1")
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self.clock.advance(1.0)
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))

        # Transient upstream error followed by healthy tool execution (R1 repro: rv1_sticky_error_batch_redelivered.py)
        tracker.append_observation({
            "src": "transcript:claude",
            "kind": "step_error",
            "message": error_msg,
            "t": int(self.clock.time() * 1000),
        })
        self.clock.advance(1.0)
        tracker.append_observation({
            "src": "transcript:claude",
            "kind": "step_tool_start",
            "tool": "Bash",
            "summary": "git log",
            "call_id": "c1",
            "t": int(self.clock.time() * 1000),
        })
        self.clock.advance(1.0)
        tracker.append_observation({
            "src": "transcript:claude",
            "kind": "step_tool_end",
            "call_id": "c1",
            "t": int(self.clock.time() * 1000),
        })

        # Supervisor sees hc `done` BEFORE async Stop hook arrives
        self.clock.advance(5.0)
        row.update({"status": {"state": "done"}, "turn": 2, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))

        # 50ms later, Stop hook arrives
        self.clock.advance(0.05)
        tracker.end_turn(expected_seq=tseq, has_reply=True)

        # Advance 45s past W2's retry window -> zero re-deliveries, no W2 incident, batch answered in 1 attempt
        for _ in range(9):
            self.clock.advance(5.0)
            sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
            driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))

        st = tracker.read()
        item = tracker.pm_mailbox.get(batch_env_id)
        self.assertEqual(len(self.hc.sent), 1)
        self.assertEqual(st["last_turn"]["outcome"], "replied")
        self.assertIsNone(st.get("incident"))
        self.assertIsNotNone(item)
        self.assertEqual(item.state, "answered")
        self.assertEqual(item.attempts, 1)

    def test_r1_transient_connection_error_before_healthy_step_never_redelivers_batch(self) -> None:
        self._run_transient_error_late_stop_batch(
            "{'message': 'Connection error.', 'formatted': 'Connection dropped (ECONNRESET)'}"
        )

    def test_r1_transient_529_overloaded_before_healthy_step_never_redelivers_batch(self) -> None:
        self._run_transient_error_late_stop_batch("API Error: 529 Overloaded")

    def test_r1_pure_reducer_transient_error_late_stop_and_esc_and_direct_reply(self) -> None:
        cfg = tr.TurnConfig()
        t0 = 1_795_000_000_000
        ep = {"runtime": "hc", "machine": None, "terminal": "t1", "agent_kind": "claude", "fg_pid": 100, "epoch": 1}

        def open_turn(cause: str, extra: dict) -> dict:
            st = tr.default_state_v2(cfg)
            st = tr.reduce(st, {"src": "supervisor", "kind": "hc_state", "t": t0 - 60_000, "state": "live", "status": "idle", "status_ms": t0 - 60_000, "turn": 6, "reported": True, "endpoint": ep}, cfg)
            st = tr.reduce(st, {"src": "hook", "kind": "hook_prompt", "t": t0, "terminal": "t1", "agent_kind": "claude", "cause": cause, "hc_turn": 0, "session_id": "s", **extra}, cfg)
            st = tr.reduce(st, {"src": "supervisor", "kind": "hc_state", "t": t0 + 500, "state": "live", "status": "working", "status_ms": t0 + 100, "turn": 6, "reported": True, "endpoint": ep}, cfg)
            return st

        # A: transient 529 -> tool -> hc done -> late Stop hook (49ms) -> replied, zero W2 actions
        st_a = open_turn("deliver", {"msg_ids": [], "batch": [277086, 280232]})
        st_a = tr.reduce(st_a, {"src": "transcript:claude", "kind": "step_error", "t": t0 + 3_000, "message": "API Error: 529 Overloaded. Retrying (attempt 1/10)"}, cfg)
        self.assertEqual(st_a["turn"]["evidence"]["step"]["last_kind"], "error")
        self.assertTrue(st_a["turn"]["evidence"]["step"]["last_error"])
        st_a = tr.reduce(st_a, {"src": "transcript:claude", "kind": "step_tool_start", "t": t0 + 9_000, "tool": "Bash", "summary": "ls", "call_id": "c1"}, cfg)
        self.assertEqual(st_a["turn"]["evidence"]["step"]["last_error"], "")
        st_a = tr.reduce(st_a, {"src": "transcript:claude", "kind": "step_tool_end", "t": t0 + 11_000, "call_id": "c1"}, cfg)
        st_a = tr.reduce(st_a, {"src": "supervisor", "kind": "hc_state", "t": t0 + 15_000, "state": "live", "status": "done", "status_ms": t0 + 14_990, "turn": 7, "reported": True, "endpoint": ep}, cfg)
        self.assertEqual(st_a["last_turn"]["outcome"], "silent")
        self.assertIsNone(st_a.get("incident"))
        st_a = tr.reduce(st_a, {"src": "hook", "kind": "hook_stop", "t": t0 + 15_049, "expected_seq": st_a["turn"]["seq"], "has_reply": True}, cfg)
        self.assertEqual(st_a["last_turn"]["outcome"], "replied")
        self.assertIsNone(st_a.get("incident"))
        for dt_s in (5, 10, 15, 20, 21, 25):
            st_a, acts_a = tr.tick(st_a, t0 + 15_100 + dt_s * 1_000, cfg)
            self.assertEqual([a for a in acts_a if a.get("kind") == "recovery_action"], [])

        # B: transient 529 -> tool -> user presses Esc -> hc idle -> late step_interrupted -> interrupted, zero W2 actions
        st_b = open_turn("user", {"msg_ids": ["u-1"]})
        st_b = tr.reduce(st_b, {"src": "transcript:claude", "kind": "step_error", "t": t0 + 3_000, "message": "API Error: 529 Overloaded. Retrying (attempt 1/10)"}, cfg)
        st_b = tr.reduce(st_b, {"src": "transcript:claude", "kind": "step_tool_start", "t": t0 + 9_000, "tool": "Bash", "summary": "ls", "call_id": "c1"}, cfg)
        st_b = tr.reduce(st_b, {"src": "transcript:claude", "kind": "step_tool_end", "t": t0 + 11_000, "call_id": "c1"}, cfg)
        st_b = tr.reduce(st_b, {"src": "supervisor", "kind": "hc_state", "t": t0 + 15_000, "state": "live", "status": "idle", "status_ms": t0 + 14_990, "turn": 7, "reported": True, "endpoint": ep}, cfg)
        self.assertEqual(st_b["last_turn"]["outcome"], "silent")
        self.assertIsNone(st_b.get("incident"))
        st_b = tr.reduce(st_b, {"src": "transcript:claude", "kind": "step_interrupted", "t": t0 + 15_100}, cfg)
        self.assertEqual(st_b["last_turn"]["outcome"], "interrupted")
        self.assertIsNone(st_b.get("incident"))
        for dt_s in (5, 10, 15, 20, 21, 25):
            st_b, acts_b = tr.tick(st_b, t0 + 15_100 + dt_s * 1_000, cfg)
            self.assertEqual([a for a in acts_b if a.get("kind") == "recovery_action"], [])

        # C: transient 529 -> direct reply (no tool step) -> hc done -> late Stop(has_reply=True) amends errored to replied
        st_c = open_turn("user", {"msg_ids": ["u-2"]})
        st_c = tr.reduce(st_c, {"src": "transcript:claude", "kind": "step_error", "t": t0 + 3_000, "message": "API Error: 529 Overloaded. Retrying (attempt 1/10)"}, cfg)
        st_c = tr.reduce(st_c, {"src": "supervisor", "kind": "hc_state", "t": t0 + 15_000, "state": "live", "status": "done", "status_ms": t0 + 14_990, "turn": 7, "reported": True, "endpoint": ep}, cfg)
        self.assertEqual(st_c["last_turn"]["outcome"], "errored")
        self.assertEqual(st_c["incident"]["class"], "W2")
        st_c = tr.reduce(st_c, {"src": "hook", "kind": "hook_stop", "t": t0 + 15_049, "expected_seq": st_c["turn"]["seq"], "has_reply": True}, cfg)
        self.assertEqual(st_c["last_turn"]["outcome"], "replied")
        self.assertIsNone(st_c.get("incident"))
        for dt_s in (5, 10, 15, 20, 21, 25):
            st_c, acts_c = tr.tick(st_c, t0 + 15_100 + dt_s * 1_000, cfg)
            self.assertEqual([a for a in acts_c if a.get("kind") == "recovery_action"], [])

        # D: real fatal error -> late Stop(has_reply=False) must NOT falsely amend errored to replied
        st_d = open_turn("user", {"msg_ids": ["u-3"]})
        st_d = tr.reduce(st_d, {"src": "transcript:claude", "kind": "step_error", "t": t0 + 3_000, "message": "upstream stream reset"}, cfg)
        st_d = tr.reduce(st_d, {"src": "supervisor", "kind": "hc_state", "t": t0 + 15_000, "state": "live", "status": "idle", "status_ms": t0 + 14_990, "turn": 7, "reported": True, "endpoint": ep}, cfg)
        self.assertEqual(st_d["last_turn"]["outcome"], "errored")
        self.assertEqual(st_d["incident"]["class"], "W2")
        st_d = tr.reduce(st_d, {"src": "hook", "kind": "hook_stop", "t": t0 + 15_049, "expected_seq": st_d["turn"]["seq"], "has_reply": False}, cfg)
        self.assertEqual(st_d["last_turn"]["outcome"], "errored")
        self.assertEqual(st_d["incident"]["class"], "W2")

        # E: tool-only turn (no closing prose) -> Stop(has_reply=False) while still working -> ended=True, replied
        # (main behaviour; a silent close here would escalate a W2 continue_turn verification instead of resolving it)
        st_e = open_turn("user", {"msg_ids": ["u-4"]})
        st_e = tr.reduce(st_e, {"src": "transcript:claude", "kind": "step_tool_start", "t": t0 + 3_000, "tool": "Bash", "summary": "ls", "call_id": "c1"}, cfg)
        st_e = tr.reduce(st_e, {"src": "transcript:claude", "kind": "step_tool_end", "t": t0 + 5_000, "call_id": "c1"}, cfg)
        st_e = tr.reduce(st_e, {"src": "hook", "kind": "hook_stop", "t": t0 + 6_000, "expected_seq": st_e["turn"]["seq"], "has_reply": False}, cfg)
        self.assertEqual(st_e["last_turn"]["outcome"], "replied")
        self.assertIsNone(st_e.get("incident"))


class B2AndB3ReducerAndWorkerWatchTests(WorkerSupervisionTests):
    """B2 & B3: worker without step evidence never triggers `no_step_timeout` while screen changes;
    prose like '第 5 期' / 'attempt 2 of 3' / 'retry 3 times' never flips phase to `waiting_upstream`."""

    def _run_worker_watch(self, screen_fn, seconds: int = 700):
        ctx, hc, task = self._setup_worker(worker_kind="agy", screen=screen_fn(0))
        watcher = StallWatcher(ctx, stall_grace=0)
        stops, bases = {}, {}
        first = None
        phases = []
        for i in range(seconds // 10):
            hc.terminals["t20"]["screen"] = screen_fn(i)
            watcher.watch_workers([task], stops, bases)
            st = self._store_for(ctx).read()["turn"]
            phases.append((st["phase"], st["health"], st.get("health_reason")))
            stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
            if stalls and first is None:
                first = (i * 10, stalls[-1])
            self.clk.advance(10.0)
        return first, phases

    def test_b2a_healthy_agy_worker_without_shell_commands_for_11_min_never_stalls(self) -> None:
        first, phases = self._run_worker_watch(lambda i: f"Editing file_{i}.py\nspinner {i}\n", 700)
        self.assertIsNone(first, "a worker whose screen kept changing was reported stalled")
        self.assertTrue(all(ph == "generating" for ph, _, _ in phases))

    def test_b2b_zh_and_english_prose_on_worker_screen_never_enters_waiting_upstream(self) -> None:
        first, phases = self._run_worker_watch(
            lambda i: f"正在实现第 5 期的清理\ntest_x ... ok (attempt 2 of 3)\nretry 3 times\nEditing file_{i}.py\n",
            700,
        )
        self.assertIsNone(first)
        self.assertNotIn("waiting_upstream", {ph for ph, _, _ in phases})

    def test_b2_b3_six_reducer_scenarios_and_hint_clearing(self) -> None:
        def run_sim(cfg: tr.TurnConfig, screen_lines: list[str], *, minutes: int = 13, kind: str = "agy"):
            t0 = 1_795_000_000_000
            st = tr.default_state_v2(cfg)
            ep = {"runtime": "hc", "machine": None, "terminal": "t9", "workspace": "", "session_id": "", "agent_kind": kind, "fg_pid": None, "epoch": 1}
            st = tr.reduce(st, {"src": "supervisor", "kind": "hc_state", "t": t0, "state": "live", "status": "working", "status_ms": t0, "turn": 3, "reported": True, "endpoint": ep}, cfg)
            adapter = adapter_for(kind)
            first = None
            phases_seen = set()
            for s in range(5, minutes * 60, 5):
                now = t0 + s * 1_000
                if s % 10 == 0 and s >= 30:
                    text = "\n".join(screen_lines) + f"\nspinner frame {s}"
                    st = tr.reduce(
                        st,
                        {"src": "probe:pty", "kind": "pty_probe", "t": now, "changed": True, "digest": f"d{s}", "hint": adapter.screen_hint(text), "dialog_kind": ""},
                        cfg,
                    )
                st, acts = tr.tick(st, now, cfg)
                phases_seen.add(st["turn"]["phase"])
                stall = [a for a in acts if a.get("kind") == "stall"]
                rec = [a for a in acts if a.get("kind") == "recovery_action"]
                if (stall or rec) and first is None:
                    first = (s, st["turn"]["phase"], st["turn"]["health_reason"])
            return st, first, phases_seen

        wcfg = tr.DEFAULT_WORKER_TURN_CONFIG
        pcfg = tr.TurnConfig()

        # A, B, C: Worker 13 min with plain screen, '第 5 期', 'attempt 2 of 3', 'retry 3 times' -> zero stalls, generating
        for lines in (
            ["Reading file a.py", "Editing b.py"],
            ["正在实现第 5 期的清理", "Editing b.py"],
            ["test_x ... ok (attempt 2 of 3)", "retry 3 times", "Editing"],
        ):
            st_w, first_w, phases_w = run_sim(wcfg, lines)
            self.assertIsNone(first_w)
            self.assertEqual(phases_w, {"generating"})
            self.assertEqual(st_w["turn"]["phase"], "generating")

        # D: PM with '第 3 步' stays in `generating` (never `waiting_upstream`); hits `no_step_timeout` at 240s, NOT 300s `upstream_timeout`
        _, first_d, phases_d = run_sim(pcfg, ["下面是第 3 步的说明", "…"], minutes=7, kind="agy")
        self.assertEqual(phases_d, {"generating"})
        self.assertEqual(first_d, (240, "generating", "no_step_timeout"))

        # E & F: PM with token counter ('↓ 12,345 tokens') AND '第 3 步' / 'attempt 2 of 3' / 'retry 3 times' NEVER stalls!
        for lines_pm in (
            ["↓ 12,345 tokens"],
            ["下面是第 3 步的说明", "attempt 2 of 3", "retry 3 times", "↓ 12,345 tokens"],
        ):
            _, first_ef, phases_ef = run_sim(pcfg, lines_pm, minutes=7, kind="claude")
            self.assertIsNone(first_ef)
            self.assertEqual(phases_ef, {"generating"})

        # Adapter screen_hint precision + hint reset on subsequent non-matching probe
        for kind in ("claude", "codex", "agy", "pi"):
            ad = adapter_for(kind)
            for prose in ("第 5 期", "第 3 步", "test_x ... ok (attempt 2 of 3)", "retry 3 times"):
                self.assertEqual(ad.screen_hint(prose), "", f"{kind} false-matched {prose!r}")
        self.assertEqual(adapter_for("claude").screen_hint("Retrying in 4s… (attempt 3/10)"), "retry:3")
        self.assertEqual(adapter_for("codex").screen_hint("stream error: EOF; retrying 2/5 in 1s"), "retry:2")
        self.assertEqual(adapter_for("agy").screen_hint("正在第 2 次重试"), "retry:2")

        # Historical journal replay containing `pty_probe` with `hint: "retry:5"` / `"retry:0"` never enters `waiting_upstream`
        t0 = 1_795_000_000_000
        st_hist = tr.default_state_v2(pcfg)
        st_hist = tr.reduce(st_hist, {"seq": 1, "t": t0, "kind": "hc_state", "state": "live", "status": "working", "status_ms": t0, "turn": 1, "reported": True}, pcfg)
        st_hist = tr.reduce(st_hist, {"seq": 2, "t": t0 + 15_000, "kind": "pty_probe", "changed": True, "digest": "d1", "hint": "retry:5"}, pcfg)
        self.assertEqual(st_hist["turn"]["phase"], "generating")
        self.assertEqual(st_hist["turn"]["evidence"]["pty"]["hint"], "retry:5")
        st_hist = tr.reduce(st_hist, {"seq": 3, "t": t0 + 20_000, "kind": "pty_probe", "changed": True, "digest": "d2", "hint": ""}, pcfg)
        self.assertEqual(st_hist["turn"]["evidence"]["pty"]["hint"], "")


class B4UnconsumedTypedMessageLifecycleTests(TestMessagingReplay):
    """B4: `pi` and unhooked coordinators settle pre-turn `typed` messages on `replied`,
    while an unanswered `typed` message whose turn crashed/rotated before replying goes back to `accepted`."""

    def _hook(self, payload: dict) -> None:
        self.ctx.caller = Caller(self.ctx)
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), mock.patch("sys.stdout", io.StringIO()):
            hooks.cmd_hook_turn(None, ctx=self.ctx)

    def test_b4_pi_opened_and_replied_never_retypes_on_rotate(self) -> None:
        from pmlib.manager.service import ManagerSessions

        reg = dict(self.ctx.store.registration(self.slug) or {})
        reg["agent"] = "pi"
        reg["seat"] = True
        self.ctx.store.change_registration(self.slug, lambda _: reg)
        self.ctx.hc_terminal = "t1"
        self.ctx.caller = Caller(self.ctx)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        driver = EndpointDriver(self.ctx, self.repo_dir)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        row = self.hc._mutable_dict("t1")
        row["labels"] = {**dict(row.get("labels") or {}), "pm.seat": "1"}

        env_ids = []
        for n in range(3):
            res = tracker.send_user_message(msg_id=f"u-pi-{n}", text=f"question number {n}")
            env_ids.append(res["env_id"])
            out, _ = driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
            self.assertEqual(out.status, "typed")
            row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
            self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-s1"})
            sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
            self.clock.advance(8.0)
            self._hook({"hook_event_name": "Stop", "cwd": str(self.repo_dir), "last_assistant_message": f"answer {n}"})
            row.update({"status": {"state": "idle"}, "turn": int(row.get("turn") or 1) + 1, "status_ms": int(self.clock.time() * 1000)})
            sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
            self.clock.advance(30.0)
            driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))

        states = [tracker.pm_mailbox.get(e).state for e in env_ids]
        self.assertEqual(states, ["answered"] * 3)
        self.assertEqual(tracker.pm_mailbox.unanswered_user_items(), [])

        # Rotate session (bumps epoch 1 -> 2 and runs G4): answered turns MUST NEVER be retyped!
        sent_before = len(self.hc.sent)
        ManagerSessions(self.ctx).rotate(self.repo_dir, reason="routine swap")
        (self.ctx.home.project_for(self.repo_dir).next_session).unlink(missing_ok=True)
        reg_after = self.ctx.store.registration(self.slug) or {}
        self.assertEqual(reg_after["epoch"], 2)
        for _ in range(4):
            driver.drive_pm_endpoint(reg_after, self.hc.get_raw("t1"))
            self.clock.advance(5.0)
        self.assertEqual(self.hc.sent[sent_before:], [])
        self.assertEqual([tracker.pm_mailbox.get(e).state for e in env_ids], ["answered"] * 3)

    def test_b4_pi_opened_unanswered_crash_on_rotate_returns_to_accepted_and_retypes(self) -> None:
        from pmlib.manager.service import ManagerSessions

        reg = dict(self.ctx.store.registration(self.slug) or {})
        reg["agent"] = "pi"
        reg["seat"] = True
        self.ctx.store.change_registration(self.slug, lambda _: reg)
        self.ctx.hc_terminal = "t1"
        self.ctx.caller = Caller(self.ctx)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        driver = EndpointDriver(self.ctx, self.repo_dir)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        row = self.hc._mutable_dict("t1")
        row["labels"] = {**dict(row.get("labels") or {}), "pm.seat": "1"}

        # 1) User sends a message; pi opens the turn (`AgentStart` + `working`) so `turn_opened_seq > 0` is stamped.
        res = tracker.send_user_message(msg_id="u-pi-crash", text="deploy v0.2.0 after checks")
        env_id = res["env_id"]
        out, _ = driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(out.status, "typed")
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-s1"})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.assertGreater(int(tracker.pm_mailbox.get(env_id).meta.get("turn_opened_seq") or 0), 0)

        # 2) pi crashes BEFORE replying (`no Stop`, not `answered`), and `rotate` swaps to epoch 2!
        self.clock.advance(4.0)
        row.update({"state": "exited", "status": None})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        ManagerSessions(self.ctx).rotate(self.repo_dir, reason="pi crashed before replying", force=True)

        # G4 MUST return the unanswered `typed` `chat.user` back to `accepted` (never `expired`) with cleared `turn_opened_seq`!
        after_rot = tracker.pm_mailbox.get(env_id)
        assert after_rot is not None
        self.assertEqual(after_rot.state, "accepted")
        self.assertEqual(after_rot.endpoint_epoch, 2)
        self.assertEqual(after_rot.typed_ms, 0)
        self.assertNotIn("turn_opened_seq", after_rot.meta)
        self.assertEqual([it.envelope.env_id for it in tracker.pm_mailbox.unanswered_user_items()], [env_id])

        # 3) New pi session comes online on epoch 2 -> retypes the message -> replies -> settles to `answered`!
        (self.ctx.home.project_for(self.repo_dir).next_session).unlink(missing_ok=True)
        reg2 = self.ctx.store.registration(self.slug) or {}
        new_term = str(reg2.get("terminal") or "t1")
        self.ctx.pane = f"hc:{new_term}"
        self.ctx.hc_terminal = new_term
        row2 = self.hc._mutable_dict(new_term)
        row2.update({"state": "live", "status": {"state": "idle"}, "turn": 1, "status_ms": int(self.clock.time() * 1000)})
        sent_before = len(self.hc.sent)
        out2, _ = driver.drive_pm_endpoint(reg2, self.hc.get_raw(new_term))
        self.assertEqual(out2.status, "typed")
        retyped = [s[1] for s in self.hc.sent[sent_before:] if s[0] == new_term]
        self.assertEqual(len(retyped), 1, retyped)
        self.assertIn("deploy v0.2.0 after checks", retyped[0])

        self.clock.advance(1.0)
        row2.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-s2"})
        sup.observe_and_reduce(reg2, self.hc.get_raw(new_term))
        self.clock.advance(3.0)
        self._hook({"hook_event_name": "Stop", "cwd": str(self.repo_dir), "last_assistant_message": "v0.2.0 deployed"})
        row2.update({"status": {"state": "idle"}, "turn": 2, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg2, self.hc.get_raw(new_term))
        self.assertEqual(tracker.pm_mailbox.get(env_id).state, "answered")
        self.assertEqual(tracker.pm_mailbox.unanswered_user_items(), [])

    def test_b4_pi_opened_unanswered_in_seat_rotate_returns_to_accepted_and_retypes(self) -> None:
        from pmlib.manager.service import ManagerSessions

        reg = dict(self.ctx.store.registration(self.slug) or {})
        reg["agent"] = "pi"
        reg["seat"] = True
        self.ctx.store.change_registration(self.slug, lambda _: reg)
        self.ctx.hc_terminal = "t1"
        self.ctx.caller = Caller(self.ctx)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        driver = EndpointDriver(self.ctx, self.repo_dir)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        row = self.hc._mutable_dict("t1")
        row["labels"] = {**dict(row.get("labels") or {}), "pm.seat": "1"}

        # 1) User sends message; pi opens turn (`turn_opened_seq > 0`), then hangs/dies in-seat before replying.
        res = tracker.send_user_message(msg_id="u-pi-seat-crash", text="check staging logs")
        env_id = res["env_id"]
        out, _ = driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(out.status, "typed")
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-seat-1"})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.assertGreater(int(tracker.pm_mailbox.get(env_id).meta.get("turn_opened_seq") or 0), 0)

        # 2) In-seat rotate (same terminal `hc:t1`, epoch 1 -> 2) before any reply (`Stop` never ran):
        self.clock.advance(4.0)
        rot_res = ManagerSessions(self.ctx).rotate(self.repo_dir, reason="pi died mid-turn", force=True)
        self.assertEqual(rot_res.mode, "seat")
        after_rot = tracker.pm_mailbox.get(env_id)
        assert after_rot is not None
        self.assertEqual(after_rot.state, "accepted")
        self.assertEqual(after_rot.endpoint_epoch, 2)
        self.assertEqual(after_rot.typed_ms, 0)
        self.assertNotIn("turn_opened_seq", after_rot.meta)

        # 3) Seat starts new pi session in `hc:t1` -> retypes message -> replies -> settles to `answered`!
        (self.ctx.home.project_for(self.repo_dir).next_session).unlink(missing_ok=True)
        row.update({"status": {"state": "idle"}, "turn": 2, "status_ms": int(self.clock.time() * 1000)})
        reg2 = self.ctx.store.registration(self.slug) or {}
        sup.observe_and_reduce(reg2, self.hc.get_raw("t1"))
        sent_before = len(self.hc.sent)
        out2, _ = driver.drive_pm_endpoint(reg2, self.hc.get_raw("t1"))
        self.assertEqual(out2.status, "typed")
        self.assertEqual(len(self.hc.sent[sent_before:]), 1)
        self.assertIn("check staging logs", self.hc.sent[-1][1])

        self.clock.advance(1.0)
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-seat-2"})
        sup.observe_and_reduce(reg2, self.hc.get_raw("t1"))
        self.clock.advance(2.0)
        self._hook({"hook_event_name": "Stop", "cwd": str(self.repo_dir), "last_assistant_message": "staging looks clean"})
        row.update({"status": {"state": "idle"}, "turn": 3, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg2, self.hc.get_raw("t1"))
        self.assertEqual(tracker.pm_mailbox.get(env_id).state, "answered")
        self.assertEqual(tracker.pm_mailbox.unanswered_user_items(), [])

    def test_b4_mid_turn_queued_message_not_settled_by_current_turn_and_unhooked_claude_settles_on_reply(self) -> None:
        reg = dict(self.ctx.store.registration(self.slug) or {})
        reg["agent"] = "pi"
        self.ctx.store.change_registration(self.slug, lambda _: reg)
        self.ctx.hc_terminal = "t1"
        self.ctx.caller = Caller(self.ctx)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        driver = EndpointDriver(self.ctx, self.repo_dir)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        row = self.hc._mutable_dict("t1")

        # Turn 1 starts on `u-first`; `u-mid` is typed while Turn 1 is already `working` (`steers_mid_turn == False`).
        res1 = tracker.send_user_message(msg_id="u-first", text="first")
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-s1"})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.clock.advance(3.0)
        res_mid = tracker.send_user_message(msg_id="u-mid", text="queued for turn 2")
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))

        # Turn 1 replies -> settles `u-first` to `answered`, leaves `u-mid` as `typed` for Turn 2!
        self.clock.advance(2.0)
        self._hook({"hook_event_name": "Stop", "cwd": str(self.repo_dir), "last_assistant_message": "answered first"})
        row.update({"status": {"state": "idle"}, "turn": int(row.get("turn") or 1) + 1, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.assertEqual(tracker.pm_mailbox.get(res1["env_id"]).state, "answered")
        self.assertEqual(tracker.pm_mailbox.get(res_mid["env_id"]).state, "typed")

        # Also verify unhooked Claude Code coordinator (`agent == "claude"`, hooks untrusted/absent -> `hook_confirmed == False`):
        reg_claude = {**reg, "agent": "claude", "epoch": 2, "endpoint": {"runtime": "hc", "machine": None, "terminal": "t1", "epoch": 2}}
        self.ctx.store.change_registration(self.slug, lambda _: reg_claude)
        driver.drive_pm_endpoint(reg_claude, self.hc.get_raw("t1"))  # retypes `u-mid` into epoch 2
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg_claude, self.hc.get_raw("t1"))
        self.clock.advance(2.0)
        tracker.append_observation({"src": "transcript:claude", "kind": "step_reply", "t": int(self.clock.time() * 1000)}, reduce_now=True)
        row.update({"status": {"state": "done"}, "turn": int(row.get("turn") or 1) + 1, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg_claude, self.hc.get_raw("t1"))
        self.assertEqual(tracker.pm_mailbox.get(res_mid["env_id"]).state, "answered")

    def test_b4_unhooked_claude_silent_close_never_retypes_on_rotate(self) -> None:
        from pmlib.manager.service import ManagerSessions

        # 1) Completely unhooked Claude (neither UserPromptSubmit nor Stop runs -> closes on hc idle as `silent`):
        reg = dict(self.ctx.store.registration(self.slug) or {})
        reg["agent"] = "claude"
        reg["seat"] = True
        self.ctx.store.change_registration(self.slug, lambda _: reg)
        self.ctx.hc_terminal = "t1"
        self.ctx.caller = Caller(self.ctx)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        driver = EndpointDriver(self.ctx, self.repo_dir)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        row = self.hc._mutable_dict("t1")
        row["labels"] = {**dict(row.get("labels") or {}), "pm.seat": "1"}

        res1 = tracker.send_user_message(msg_id="u-claude-nohook-1", text="status of v0.2.0?")
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.clock.advance(5.0)
        row.update({"status": {"state": "idle"}, "turn": 2, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.assertEqual(tracker.read()["last_turn"]["outcome"], "silent")
        self.assertEqual(tracker.pm_mailbox.get(res1["env_id"]).state, "answered")

        # 2) Claude with UserPromptSubmit working, Stop hook broken (`silent` close on hc idle):
        res2 = tracker.send_user_message(msg_id="u-claude-nostop-2", text="any blockers left?")
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.clock.advance(1.0)
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "UserPromptSubmit", "cwd": str(self.repo_dir), "prompt": "any blockers left?", "session_id": "cl-1"})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.clock.advance(4.0)
        row.update({"status": {"state": "idle"}, "turn": 3, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.assertEqual(tracker.read()["last_turn"]["outcome"], "silent")
        self.assertEqual(tracker.pm_mailbox.get(res2["env_id"]).state, "answered")
        self.assertEqual(tracker.pm_mailbox.unanswered_user_items(), [])

        # Rotate session -> neither `silent`-closed message may be retyped!
        sent_before = len(self.hc.sent)
        ManagerSessions(self.ctx).rotate(self.repo_dir, reason="routine swap")
        (self.ctx.home.project_for(self.repo_dir).next_session).unlink(missing_ok=True)
        reg2 = self.ctx.store.registration(self.slug) or {}
        self.assertEqual(reg2["epoch"], 2)
        for _ in range(4):
            driver.drive_pm_endpoint(reg2, self.hc.get_raw("t1"))
            self.clock.advance(5.0)
        self.assertEqual(self.hc.sent[sent_before:], [])

    def test_b4_pi_esc_interrupted_or_silent_close_never_retypes_on_rotate(self) -> None:
        from pmlib.manager.service import ManagerSessions

        reg = dict(self.ctx.store.registration(self.slug) or {})
        reg["agent"] = "pi"
        reg["seat"] = True
        self.ctx.store.change_registration(self.slug, lambda _: reg)
        self.ctx.hc_terminal = "t1"
        self.ctx.caller = Caller(self.ctx)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        driver = EndpointDriver(self.ctx, self.repo_dir)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        row = self.hc._mutable_dict("t1")
        row["labels"] = {**dict(row.get("labels") or {}), "pm.seat": "1"}

        # 1) User presses Esc in terminal on pi -> hc goes `working -> idle` without Stop (`outcome == "silent"`):
        res_esc1 = tracker.send_user_message(msg_id="u-pi-esc-1", text="cancel this draft")
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-esc"})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.clock.advance(3.0)
        row.update({"status": {"state": "idle"}, "turn": 2, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.assertEqual(tracker.read()["last_turn"]["outcome"], "silent")
        self.assertEqual(tracker.pm_mailbox.get(res_esc1["env_id"]).state, "answered")

        # 2) Explicit Esc / Stop interrupt on pi (`interrupt_sent(outcome="stopped")` -> `outcome == "interrupted"`):
        self.clock.advance(2.0)
        res_esc2 = tracker.send_user_message(msg_id="u-pi-esc-2", text="stop this turn too")
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.clock.advance(1.0)
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-esc"})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.clock.advance(2.0)
        tracker.append_observation({"src": "pm", "kind": "interrupt_sent", "outcome": "stopped", "t": int(self.clock.time() * 1000)}, reduce_now=True)
        row.update({"status": {"state": "idle"}, "turn": 3, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.assertEqual(tracker.read()["last_turn"]["outcome"], "interrupted")
        self.assertEqual(tracker.pm_mailbox.get(res_esc2["env_id"]).state, "answered")
        self.assertEqual(tracker.pm_mailbox.unanswered_user_items(), [])

        # Rotate session -> Esc-cancelled messages MUST NOT be retyped!
        sent_before = len(self.hc.sent)
        ManagerSessions(self.ctx).rotate(self.repo_dir, reason="swap after esc")
        (self.ctx.home.project_for(self.repo_dir).next_session).unlink(missing_ok=True)
        reg2 = self.ctx.store.registration(self.slug) or {}
        for _ in range(4):
            driver.drive_pm_endpoint(reg2, self.hc.get_raw("t1"))
            self.clock.advance(5.0)
        self.assertEqual(self.hc.sent[sent_before:], [])

        # 3) Contrast: if a pi turn closes with `errored` (`status: error`) and rotates, it DOES return to `accepted` and retype!
        res_err = tracker.send_user_message(msg_id="u-pi-err-3", text="retry after model crash")
        driver.drive_pm_endpoint(reg2, self.hc.get_raw("t1"))
        self.clock.advance(1.0)
        row.update({"status": {"state": "working"}, "status_ms": int(self.clock.time() * 1000)})
        self._hook({"hook_event_name": "AgentStart", "cwd": str(self.repo_dir), "session_id": "pi-err"})
        sup.observe_and_reduce(reg2, self.hc.get_raw("t1"))
        self.clock.advance(2.0)
        row.update({"status": {"state": "error", "msg": "500 upstream crash"}, "status_ms": int(self.clock.time() * 1000)})
        sup.observe_and_reduce(reg2, self.hc.get_raw("t1"))
        self.assertEqual(tracker.read()["last_turn"]["outcome"], "errored")
        self.assertEqual(tracker.pm_mailbox.get(res_err["env_id"]).state, "typed")
        ManagerSessions(self.ctx).rotate(self.repo_dir, reason="recover from error", force=True)
        (self.ctx.home.project_for(self.repo_dir).next_session).unlink(missing_ok=True)
        self.assertEqual(tracker.pm_mailbox.get(res_err["env_id"]).state, "accepted")

    @unittest.skipUnless(shutil.which("node"), "node required for pm_pi_compact.js test")
    def test_b4_pm_pi_compact_bridges_before_agent_start_prompt_without_duplicate_agent_start(self) -> None:
        ext_path = (SCRIPTS / "pm_pi_compact.js").resolve().as_posix()
        script = f"""
import assert from 'node:assert/strict';
const piExt = await import({json.dumps(f"file://{ext_path}")});
const spawned = [];
const handlers = new Map();
piExt.default(
  {{ on(ev, fn) {{ handlers.set(ev, fn); }}, sendMessage() {{}} }},
  {{
    instructions: 'rules',
    spawnHook(cmd, args) {{
      let written = '';
      spawned.push({{ cmd, args, get stdin() {{ return written; }} }});
      return {{ stdin: {{ on() {{}}, end(s) {{ written = s; }} }}, unref() {{}} }};
    }},
  }},
);
handlers.get('before_agent_start')?.({{ prompt: 'hello from pi', sessionId: 'pi-s1' }}, {{ cwd: '/tmp/p' }});
handlers.get('agent_start')?.({{ sessionId: 'pi-s1' }}, {{ cwd: '/tmp/p' }});
handlers.get('agent_end')?.({{ last_assistant_message: 'hi!' }}, {{ cwd: '/tmp/p' }});
handlers.get('agent_start')?.({{ sessionId: 'pi-s1' }}, {{ cwd: '/tmp/p' }});
const events = spawned.map(s => JSON.parse(s.stdin));
assert.deepEqual(events.map(e => e.hook_event_name), ['UserPromptSubmit', 'Stop', 'AgentStart']);
assert.equal(events[0].prompt, 'hello from pi');
"""
        proc = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class AdjacentHardeningTests(WorkerSupervisionTests):
    """Tests for safe adjacent fixes in the touched files: N1 (`caffeinate`), N4 (`msg_ids` + worker isolation), F2 (`inbox_projection`)."""

    def test_n1_caffeinate_sidecar_is_never_treated_as_foreground_tool(self) -> None:
        ps_out = "\n".join([
            "4100    1 4100 00:02.10 claude --dangerously-skip-permissions",
            "4105 4100 4100 00:00.01 caffeinate -i -t 300",
        ]) + "\n"
        procs = Processes(make_ctx(self.tmp.name).home)
        with mock.patch.object(osutil, "WINDOWS", False), mock.patch(
            "pmlib.procs.subprocess.run",
            return_value=subprocess.CompletedProcess(["ps"], 0, stdout=ps_out, stderr=""),
        ):
            stat = procs.foreground_tool_stat({"pid": 4100, "status": {"app": "claude-code", "state": "working"}})
        self.assertEqual(stat, {"tool_pid": 0, "cmd": "", "cpu_ms": 0})

    def test_n4_non_list_msg_ids_and_broken_worker_isolation(self) -> None:
        # Malformed `msg_ids` (int/bool/dict) in journal observations never raises in `reduce()`.
        st = tr.default_state_v2()
        for bad in (123, True, {"x": 1}, "raw-str"):
            st = tr.reduce(st, {"kind": "send_submitted", "t": 1_000, "msg_ids": bad})
            st = tr.reduce(st, {"kind": "hook_prompt", "t": 2_000, "msg_ids": bad})
            st = tr.reduce(st, {"kind": "hc_state", "t": 3_000, "state": "live", "status": "working", "msg_ids": bad})
        self.assertEqual(st["turn"]["cause"]["msg_ids"], [])

        # Broken first worker task in `watch_workers` does not prevent watching healthy/stopped second worker.
        ctx, hc, good_task = self._setup_worker(term="t20", task_id="demo-good", worker_kind="agy")
        hc.terminals["t20"]["status"] = {"state": "idle"}
        hc.terminals["t20"]["turn"] = 3
        bad_task = {**good_task, "id": "demo-bad", "pane": "hc:t99"}

        orig_observe = LocalHcTransport_observe = None
        watcher = StallWatcher(ctx, stall_grace=0)
        real_obs = watcher._transport.observe

        def flaky_observe(ep, cursors, **kw):
            if ep.terminal == "t99":
                raise RuntimeError("corrupted endpoint state")
            return real_obs(ep, cursors, **kw)

        watcher._transport.observe = flaky_observe  # type: ignore[method-assign]
        stops: dict = {}
        bases: dict = {}
        watcher.watch_workers([bad_task, good_task], stops, bases)
        watcher.watch_workers([bad_task, good_task], stops, bases)
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertEqual(len(stalls), 1)
        self.assertEqual(stalls[0]["task"], "demo-good")
        _ = orig_observe, LocalHcTransport_observe

    def test_f2_inbox_projection_retains_unsettled_and_failed_user_messages_past_32_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mb = MailboxStore(Path(tmp) / "mb")
            u_queued, _ = mb.enqueue(
                Envelope(
                    env_id="env_u_q", idempotency_key="ui:p:uq", schema_version=1, created_ms=100,
                    kind="chat.user", sender=Principal.user("p"), recipient=LogicalAddress.pm("p"),
                    project="p", cause={"kind": "ui"}, priority=P1_USER, body={"text": "wait", "msg_id": "uq"},
                    require_reply=True,
                ),
                initial_state="accepted",
                hold_reason="blocked_prompt",
                now_ms=100,
            )
            u_failed, _ = mb.enqueue(
                Envelope(
                    env_id="env_u_f", idempotency_key="ui:p:uf", schema_version=1, created_ms=200,
                    kind="chat.user", sender=Principal.user("p"), recipient=LogicalAddress.pm("p"),
                    project="p", cause={"kind": "ui"}, priority=P1_USER, body={"text": "err", "msg_id": "uf"},
                    require_reply=True,
                ),
                initial_state="accepted",
                now_ms=200,
            )
            mb.transition(u_failed.envelope.env_id, "failed", error="send_failed", now_ms=210)
            for i in range(40):
                b_it, _ = mb.enqueue(
                    Envelope(
                        env_id=f"env_b_{i}", idempotency_key=f"batch:p:{i}", schema_version=1, created_ms=1000 + i,
                        kind="event.batch", sender=Principal.supervisor("p"), recipient=LogicalAddress.pm("p"),
                        project="p", cause={"kind": "deliver_batch"}, priority=P4_BATCH,
                        body={"text": f"batch {i}", "start": i, "end": i + 1}, require_reply=True,
                    ),
                    initial_state="accepted",
                    now_ms=1000 + i,
                )
                mb.transition(b_it.envelope.env_id, "answered", now_ms=1000 + i)
            proj = mb.inbox_projection(limit=32)
            ids = {row["id"]: row["state"] for row in proj}
            self.assertEqual(ids.get("uq"), "accepted")
            self.assertEqual(ids.get("uf"), "failed")
            self.assertEqual(len(proj), 32)
            _ = u_queued


if __name__ == "__main__":
    unittest.main()
