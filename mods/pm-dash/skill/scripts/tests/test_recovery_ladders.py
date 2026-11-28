"""Phase 4 tests: pure recovery ladder state machine (W1-W7), auto-modes & circuit breakers,
scripted `FakePmAgent` end-to-end supervisor simulations (§5), W7a stale beat kill, and `rotate --profile`.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

if "pmlib.context" not in sys.modules:
    _saved = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = "/nonexistent/pm-home-recovery-tests"
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved

from fakes import FakeChangeWaiter, FakeClock, FakeHc, FakeProcs, make_ctx  # noqa: E402
from pmlib import hooks, osutil  # noqa: E402
from pmlib.caller import Caller  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.deliverer import Deliverer  # noqa: E402
from pmlib.events.supervisor import (  # noqa: E402
    EndpointDriver,
    ProjectSupervisor,
    read_pm_turn_view,
    touch_heartbeat,
)
from pmlib.home import project_slug  # noqa: E402
from pmlib.manager.seat import swap_reason_text, write_seat_state  # noqa: E402
from pmlib.manager.service import ManagerSessions  # noqa: E402
from pmlib.messaging.address import Endpoint, LogicalAddress  # noqa: E402
from pmlib.messaging.envelope import P1_USER, P4_BATCH, Envelope, new_env_id  # noqa: E402
from pmlib.messaging.principal import Principal  # noqa: E402
from pmlib.messaging.transport import DeliverOutcome, InterruptOutcome  # noqa: E402
from pmlib.messaging.transports.fake import FakeTransport  # noqa: E402
from pmlib.project import turn_reducer as tr  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.turn_state import TurnTracker  # noqa: E402


class PureRecoveryLadderTests(unittest.TestCase):
    """Pure, zero-IO reducer contract for W1-W7 ladders, auto policies, and circuit breakers."""

    def _base_state(self, cfg: tr.TurnConfig | None = None) -> tuple[dict, tr.TurnConfig]:
        c = cfg or tr.TurnConfig()
        st = tr.default_state_v2(c)
        return st, c

    def test_auto_off_immediately_notifies_user_for_all_incident_classes(self) -> None:
        cfg = tr.turn_config_from_dict({"pm": {"recovery": {"auto": "off"}}})
        for cls in ("W1", "W2", "W4", "W5", "W6", "W7"):
            st, _ = self._base_state(cfg)
            inc = tr._open_incident(
                st,
                cls=cls,
                turn_id="t1:1",
                turn_seq=1,
                cause_kind="user",
                msg_ids=["m1"],
                batch=None,
                reason="test",
                error="boom" if cls == "W2" else "",
                tool_pid=5000 if cls == "W4" else 0,
                now_ms=10_000,
                cfg=cfg,
            )
            self.assertEqual(inc["step_name"], "notify_user", f"class={cls} under auto=off")
            act = tr.next_recovery_action(st, 10_000, cfg)
            assert act is not None
            self.assertEqual(act["action"], "notify_user")
            self.assertEqual(act["auto"], "off")

    def test_safe_vs_full_mode_for_w2_and_capacity_errors(self) -> None:
        # D1 default `"safe"` runs retry1 (20s), retry2 (90s), then skips switch_profile -> notify_user.
        safe_cfg = tr.turn_config_from_dict({
            "pm": {"recovery": {"auto": "safe", "fallback_profiles": ["backup-profile"]}},
        })
        st, _ = self._base_state(safe_cfg)
        tr._open_incident(
            st, cls="W2", turn_id="t1:1", turn_seq=1, cause_kind="user", msg_ids=["m1"],
            batch=None, reason="errored", error="transient error", now_ms=1_000, cfg=safe_cfg,
        )
        self.assertEqual(st["incident"]["step_name"], "continue_turn")
        self.assertEqual(st["incident"]["next_due_ms"], 1_000 + safe_cfg.w2_retry1_delay_ms)

        # Advance past retry1 -> retry2
        tr._advance_incident(st, 25_000, safe_cfg)
        self.assertEqual(st["incident"]["step_name"], "continue_turn")
        self.assertEqual(st["incident"]["stage"], 1)
        self.assertEqual(st["incident"]["next_due_ms"], 25_000 + safe_cfg.w2_retry2_delay_ms)

        # Under "safe", advancing past retry2 skips switch_profile even if fallback_profiles is set!
        tr._advance_incident(st, 120_000, safe_cfg)
        self.assertEqual(st["incident"]["step_name"], "notify_user")
        self.assertEqual(st["incident"]["suggested_profile"], "backup-profile")

        # Under "full" with fallback_profiles, stage 2 IS switch_profile, and capacity errors jump straight to it.
        full_cfg = tr.turn_config_from_dict({
            "pm": {"recovery": {"auto": "full", "fallback_profiles": ["backup-profile"]}},
        })
        st2, _ = self._base_state(full_cfg)
        inc_cap = tr._open_incident(
            st2, cls="W2", turn_id="t1:2", turn_seq=2, cause_kind="user", msg_ids=["m2"],
            batch=None, reason="errored", error="529 Overloaded / rate limit exceeded", now_ms=10_000, cfg=full_cfg,
        )
        self.assertEqual(inc_cap["step_name"], "switch_profile")
        act = tr.next_recovery_action(st2, 10_000, full_cfg)
        assert act is not None
        self.assertEqual(act["profile"], "backup-profile")

        # Under "safe", capacity errors skip retries straight to notify_user suggesting fallback_profiles[0].
        st3, _ = self._base_state(safe_cfg)
        inc_cap_safe = tr._open_incident(
            st3, cls="W2", turn_id="t1:3", turn_seq=3, cause_kind="user", msg_ids=["m3"],
            batch=None, reason="errored", error="model capacity exceeded", now_ms=10_000, cfg=safe_cfg,
        )
        self.assertEqual(inc_cap_safe["step_name"], "notify_user")
        self.assertEqual(inc_cap_safe["suggested_profile"], "backup-profile")

    def test_w3_never_opens_incident_never_stalls_and_caps_attempts(self) -> None:
        st, cfg = self._base_state()
        t0 = 1_000_000
        st = tr.reduce(st, {"kind": "send_submitted", "t": t0, "cause": "user", "msg_ids": ["u1"]}, cfg=cfg)
        st = tr.reduce(st, {"kind": "hc_state", "t": t0 + 1_000, "state": "live", "status": "blocked", "dialog_kind": "update"}, cfg=cfg)
        self.assertEqual(st["turn"]["phase"], "blocked")
        self.assertIsNone(st.get("incident"))

        # First unblock attempt succeeds and clears pending turn cleanly back to idle.
        act1 = tr.next_recovery_action(st, t0 + 1_000, cfg)
        assert act1 is not None
        self.assertEqual((act1["class"], act1["action"]), ("W3", "unblock_safe_dialog"))

        st = tr.reduce(st, {
            "kind": "recovery_result", "t": t0 + 1_500, "class": "W3", "action": "unblock_safe_dialog", "outcome": "failed",
        }, cfg=cfg)
        self.assertEqual(st["turn"]["w3_attempts"], 1)
        st = tr.reduce(st, {
            "kind": "recovery_result", "t": t0 + 2_000, "class": "W3", "action": "unblock_safe_dialog", "outcome": "failed",
        }, cfg=cfg)
        self.assertEqual(st["turn"]["w3_attempts"], 2)
        # Capped at 2 attempts -> never loops infinitely!
        self.assertIsNone(tr.next_recovery_action(st, t0 + 2_500, cfg))
        st, acts = tr.tick(st, t0 + 600_000, cfg)
        self.assertNotEqual(st["turn"]["health"], "stalled")
        self.assertIsNone(st.get("incident"))
        self.assertEqual(acts, [])

    def test_circuit_breakers_limit_interrupts_per_turn_and_rotations_per_30m(self) -> None:
        cfg = tr.turn_config_from_dict({
            "pm": {"recovery": {"auto": "safe", "max_turn_interrupts": 2, "max_rotations_per_window": 1, "rotation_window_ms": 1_800_000}},
        })
        st, _ = self._base_state(cfg)
        t0 = 100_000
        # 2 turn interrupts allowed for turn "t1:5", 3rd blocked by breaker -> escalates W1 to W2
        self.assertTrue(tr._can_interrupt_turn(st, "t1:5", cfg))
        tr._record_interrupt_breaker(st, "t1:5", t0, cfg)
        tr._record_interrupt_breaker(st, "t1:5", t0, cfg)
        self.assertFalse(tr._can_interrupt_turn(st, "t1:5", cfg))

        inc = tr._open_incident(
            st, cls="W1", turn_id="t1:5", turn_seq=5, cause_kind="user", msg_ids=["u1"],
            batch=None, reason="no_step_timeout", now_ms=t0, cfg=cfg,
        )
        # Because W1 interrupt breaker is exhausted, W1 escalates to W2 directly rather than looping interrupt_turn.
        self.assertEqual(inc["class"], "W2")
        self.assertEqual(inc["step_name"], "continue_turn")

        # 1 rotation per 30m window: after 1 rotation at t0, W7 skips restart_seat -> notify_user until t0 + 30m + 1.
        tr._record_rotation_breaker(st, t0, cfg)
        self.assertFalse(tr._can_rotate_seat(st, t0 + 60_000, cfg))
        st_w7, _ = self._base_state(cfg)
        st_w7["recovery_breakers"] = dict(st["recovery_breakers"])
        inc_w7 = tr._open_incident(
            st_w7, cls="W7", turn_id="t1:6", turn_seq=6, cause_kind="user", msg_ids=["u2"],
            batch=None, reason="exited", now_ms=t0 + 60_000, cfg=cfg,
        )
        self.assertEqual(inc_w7["step_name"], "notify_user")
        self.assertTrue(tr._can_rotate_seat(st_w7, t0 + 1_800_001, cfg))

    def test_unconfirmed_provisional_deliver_turn_does_not_open_false_w2_or_w7(self) -> None:
        st, cfg = self._base_state()
        t0 = 50_000
        st = tr.reduce(st, {"kind": "send_submitted", "t": t0, "cause": "deliver", "batch": [0, 100], "started": True}, cfg=cfg)
        self.assertTrue(st["turn"]["provisional"])
        st_idle = tr.reduce(st, {"kind": "hc_state", "t": t0 + 1_000, "state": "live", "status": "idle"}, cfg=cfg)
        self.assertIsNone(st_idle.get("incident"))

        st_off = tr.reduce(st, {"kind": "hc_state", "t": t0 + 1_000, "state": "finished"}, cfg=cfg)
        self.assertIsNone(st_off.get("incident"))

    def test_unresolved_w2_protects_healthy_new_turn_but_supersedes_when_new_turn_stalls(self) -> None:
        st0, cfg = self._base_state()
        t0 = 100_000
        # Turn 1 (`user`, `u1`) errors -> opens W2 (`status="open"`, waiting 20s).
        s1 = tr.reduce(st0, {"kind": "hook_prompt", "t": t0, "terminal": "t7", "fg_pid": 4100, "hc_turn": 1, "cause": "user", "msg_ids": ["u1"]}, cfg=cfg)
        s1 = tr.reduce(s1, {"kind": "hc_state", "t": t0 + 2_000, "state": "live", "status": "error", "status_ms": t0 + 2_000, "turn": 1}, cfg=cfg)
        self.assertEqual(s1["incident"]["class"], "W2")
        self.assertEqual(s1["incident"]["status"], "open")
        w2_key = s1["incident"]["key"]

        # Subcase A: A new `user` turn (`hc_turn=2`, different `turn_id`) starts at +5s, stays healthy at +25s,
        # then hangs for 390s (`W1`) -> W2 is superseded by W1 for the new turn and emits `interrupt_turn`!
        sa = tr.reduce(s1, {"kind": "hook_prompt", "t": t0 + 5_000, "terminal": "t7", "fg_pid": 4100, "hc_turn": 2, "cause": "user", "msg_ids": ["u2"]}, cfg=cfg)
        sa = tr.reduce(sa, {"kind": "hc_state", "t": t0 + 5_100, "state": "live", "status": "working", "status_ms": t0 + 5_100, "turn": 2, "reported": True}, cfg=cfg)
        self.assertEqual(sa["incident"]["status"], "open")

        # Healthy at +25s -> NOT interrupted!
        sa_ok, acts_ok = tr.tick(sa, t0 + 25_000, cfg)
        self.assertEqual([a for a in acts_ok if a.get("kind") == "recovery_action"], [])
        self.assertEqual(sa_ok["turn"]["phase"], "generating")

        # Hung at +395s (390s > 240s, screen still changing) -> opens W1 for Turn 2 and emits `interrupt_turn`!
        sa_pty = tr.reduce(sa_ok, {"kind": "pty_probe", "t": t0 + 390_000, "changed": True, "digest": "spin1"}, cfg=cfg)
        sa_hung, acts_hung = tr.tick(sa_pty, t0 + 395_000, cfg)
        rec_acts_a = [a for a in acts_hung if a.get("kind") == "recovery_action"]
        self.assertEqual(len(rec_acts_a), 1)
        self.assertEqual((rec_acts_a[0]["class"], rec_acts_a[0]["action"]), ("W1", "interrupt_turn"))
        self.assertEqual(sa_hung["incident"]["class"], "W1")
        self.assertEqual(sa_hung["incident"]["turn_id"], sa_hung["turn"]["id"])
        self.assertEqual(sa_hung["incident"]["key"], w2_key)

        # Subcase B: A `self` turn (`hc_turn=2`, different `turn_id`) starts at +5s while W2 (`status="open"`) waits.
        sb = tr.reduce(s1, {"kind": "hc_state", "t": t0 + 5_000, "state": "live", "status": "working", "status_ms": t0 + 5_000, "turn": 2, "reported": True}, cfg=cfg)
        self.assertEqual(sb["turn"]["cause"]["kind"], "self")
        self.assertEqual(sb["incident"]["class"], "W2")
        self.assertEqual(sb["incident"]["status"], "open")

        # Healthy at +25s (past W2's 20s timer) -> NOT interrupted while `self` turn is healthy!
        sb_ok, acts_sb_ok = tr.tick(sb, t0 + 25_000, cfg)
        self.assertEqual([a for a in acts_sb_ok if a.get("kind") == "recovery_action"], [])

        # B1: If healthy `self` turn finishes cleanly at +30s, W2 for `u1` is NOT erased and immediately fires `continue_turn`!
        sb_done = tr.reduce(sb_ok, {"kind": "step_reply", "t": t0 + 30_000, "close_turn": True}, cfg=cfg)
        self.assertEqual(sb_done["incident"]["class"], "W2")
        self.assertEqual(sb_done["incident"]["status"], "open")
        _, acts_after_self = tr.tick(sb_done, t0 + 30_500, cfg)
        rec_after_self = [a for a in acts_after_self if a.get("kind") == "recovery_action"]
        self.assertEqual(len(rec_after_self), 1)
        self.assertEqual((rec_after_self[0]["class"], rec_after_self[0]["action"]), ("W2", "continue_turn"))

        # B2: If `self` turn instead hangs for 390s (or freezes screen for 45s -> W5 / hangs command -> W4),
        # W2 is superseded by W1 for the hung `self` turn AND preserves `u1` so `continue_turn` still follows `interrupt_turn`!
        sb_pty = tr.reduce(sb_ok, {"kind": "pty_probe", "t": t0 + 390_000, "changed": True, "digest": "spin2"}, cfg=cfg)
        sb_hung, acts_sb_hung = tr.tick(sb_pty, t0 + 395_000, cfg)
        rec_acts_b = [a for a in acts_sb_hung if a.get("kind") == "recovery_action"]
        self.assertEqual(len(rec_acts_b), 1)
        self.assertEqual((rec_acts_b[0]["class"], rec_acts_b[0]["action"]), ("W1", "interrupt_turn"))
        self.assertEqual(sb_hung["incident"]["turn_id"], sb_hung["turn"]["id"])
        self.assertEqual(sb_hung["incident"]["cause_kind"], "user")
        self.assertEqual(sb_hung["incident"]["msg_ids"], ["u1"])

        sb_stopped = tr.reduce(sb_hung, {
            "kind": "recovery_result", "t": t0 + 395_500, "incident_id": sb_hung["incident"]["id"],
            "class": "W1", "stage": 0, "action": "interrupt_turn", "outcome": "stopped",
        }, cfg=cfg)
        _, acts_cont = tr.tick(sb_stopped, t0 + 396_000, cfg)
        rec_cont = [a for a in acts_cont if a.get("kind") == "recovery_action"]
        self.assertEqual(len(rec_cont), 1)
        self.assertEqual((rec_cont[0]["class"], rec_cont[0]["action"]), ("W1", "continue_turn"))
        self.assertEqual(rec_cont[0]["msg_ids"], ["u1"])

        # Subcase C: W4 (tool hard budget 180s) & W5 (screen frozen 45s) on a new turn also supersede W2!
        sc_w5 = tr.reduce(sa, {"kind": "pty_probe", "t": t0 + 20_000, "changed": False, "digest": "freeze"}, cfg=cfg)
        sc_w5_hung, acts_w5 = tr.tick(sc_w5, t0 + 70_000, cfg)
        rec_w5 = [a for a in acts_w5 if a.get("kind") == "recovery_action"]
        self.assertEqual(len(rec_w5), 1)
        self.assertEqual((rec_w5[0]["class"], rec_w5[0]["action"]), ("W5", "classify_screen"))
        self.assertEqual(sc_w5_hung["incident"]["class"], "W5")

        sc_w4 = tr.reduce(sa, {"kind": "step_tool_start", "t": t0 + 10_000, "tool": "Bash", "summary": "sleep 999"}, cfg=cfg)
        sc_w4 = tr.reduce(sc_w4, {"kind": "proc_probe", "t": t0 + 11_000, "tool_pid": 9001, "cmd": "sleep 999", "cpu_ms": 10}, cfg=cfg)
        sc_w4_hung, acts_w4 = tr.tick(sc_w4, t0 + 200_000, cfg)
        rec_w4 = [a for a in acts_w4 if a.get("kind") == "recovery_action"]
        self.assertEqual(len(rec_w4), 1)
        self.assertEqual((rec_w4[0]["class"], rec_w4[0]["action"]), ("W4", "interrupt_tool"))
        self.assertEqual(sc_w4_hung["incident"]["class"], "W4")

    def test_w1_recovery_continuation_stall_escalates_to_w2_and_notifies_without_looping(self) -> None:
        st, cfg = self._base_state()
        t0 = 100_000
        hc_turn = 1
        st = tr.reduce(st, {
            "kind": "hook_prompt", "t": t0, "terminal": "t7", "fg_pid": 4100,
            "hc_turn": hc_turn, "cause": "user", "msg_ids": ["u1"],
        }, cfg=cfg)
        st = tr.reduce(st, {
            "kind": "hc_state", "t": t0 + 100, "state": "live", "status": "working",
            "status_ms": t0 + 100, "turn": hc_turn, "reported": True,
        }, cfg=cfg)

        executed: list[tuple[str, int, str]] = []
        executed_phases: list[tuple[str, int, str, str]] = []
        classes_seen: list[str] = []

        # Simulate 4000s where EVERY delivered continuation turn (`cause="recovery"`)
        # hangs again in `generating` with changing spinner frames (never replying).
        for step_i in range(1, 801):
            now_ms = t0 + step_i * 5_000
            if st["turn"]["phase"] == "generating":
                st = tr.reduce(st, {
                    "kind": "pty_probe", "t": now_ms - 500, "changed": True, "digest": f"spin_{step_i}",
                }, cfg=cfg)
            st, acts = tr.tick(st, now_ms, cfg)
            inc = st.get("incident")
            if isinstance(inc, dict) and inc.get("class"):
                classes_seen.append(str(inc["class"]))
            rec_acts = [a for a in acts if a.get("kind") == "recovery_action"]
            for act in rec_acts:
                cls = str(act["class"])
                stage = int(act["stage"])
                action = str(act["action"])
                inc_id = str(act.get("incident_id") or "")
                phase_before = str(st["turn"]["phase"])
                executed.append((cls, stage, action))
                executed_phases.append((cls, stage, action, phase_before))
                # A queued `cmd.resume_turn` only reaches the PM once it is idle; a still-generating turn keeps it queued.
                pm_idle = phase_before == "idle"
                st = tr.reduce(st, {
                    "kind": "recovery_started", "t": now_ms, "incident_id": inc_id,
                    "class": cls, "stage": stage, "action": action,
                }, cfg=cfg)
                if action == "interrupt_turn":
                    hc_turn += 1
                    st = tr.reduce(st, {
                        "kind": "recovery_result", "t": now_ms + 100, "incident_id": inc_id,
                        "class": cls, "stage": stage, "action": action, "outcome": "stopped",
                    }, cfg=cfg)
                    st = tr.reduce(st, {
                        "kind": "hc_state", "t": now_ms + 200, "state": "live", "status": "idle",
                        "status_ms": now_ms + 200, "turn": hc_turn, "reported": True,
                    }, cfg=cfg)
                elif action == "continue_turn":
                    st = tr.reduce(st, {
                        "kind": "recovery_result", "t": now_ms + 100, "incident_id": inc_id,
                        "class": cls, "stage": stage, "action": action, "outcome": "queued",
                    }, cfg=cfg)
                    if not pm_idle:
                        continue
                    hc_turn += 1
                    st = tr.reduce(st, {
                        "kind": "send_submitted", "t": now_ms + 300, "terminal": "t7", "fg_pid": 4100,
                        "hc_turn": hc_turn, "cause": "recovery", "msg_ids": ["u1"], "started": True,
                    }, cfg=cfg)
                    st = tr.reduce(st, {
                        "kind": "hc_state", "t": now_ms + 400, "state": "live", "status": "working",
                        "status_ms": now_ms + 400, "turn": hc_turn, "reported": True,
                    }, cfg=cfg)
                elif action == "notify_user":
                    st = tr.reduce(st, {
                        "kind": "recovery_result", "t": now_ms + 100, "incident_id": inc_id,
                        "class": cls, "stage": stage, "action": action, "outcome": "notified",
                    }, cfg=cfg)

        # Every `continue_turn` MUST be emitted only when `phase == "idle"` (after `interrupt_turn` stopped the hung turn).
        self.assertTrue(
            all(ph == "idle" for _, _, act_name, ph in executed_phases if act_name == "continue_turn"),
            f"continue_turn emitted while non-idle: {executed_phases}",
        )
        # Must NEVER loop `("W1", 0, "interrupt_turn")`: W1 interrupts & continues once, then each stalled
        # W2 continuation interrupts the active hung turn to idle before running W2 stage 0 / stage 1 `continue_turn`,
        # then escalates to stage 3 `notify_user` and remains `notified` through 4000s!
        self.assertEqual(
            executed,
            [
                ("W1", 0, "interrupt_turn"),
                ("W1", 1, "continue_turn"),
                ("W2", 0, "interrupt_turn"),
                ("W2", 0, "continue_turn"),
                ("W2", 1, "interrupt_turn"),
                ("W2", 1, "continue_turn"),
                ("W2", 3, "notify_user"),
            ],
        )
        self.assertIn("W2", classes_seen)
        self.assertEqual(st["incident"]["class"], "W2")
        self.assertEqual(st["incident"]["status"], "notified")

        # Subcase: if `interrupt_turn` fails (`outcome="still_working"`), W2 skips `continue_turn` straight to
        # `notify_user` (never emitting `continue_turn` while `phase == "generating"`).
        st2, _ = self._base_state(cfg)
        st2 = tr.reduce(st2, {
            "kind": "hook_prompt", "t": t0, "terminal": "t7", "fg_pid": 4100,
            "hc_turn": 1, "cause": "user", "msg_ids": ["u2"],
        }, cfg=cfg)
        st2 = tr.reduce(st2, {
            "kind": "hc_state", "t": t0 + 100, "state": "live", "status": "working",
            "status_ms": t0 + 100, "turn": 1, "reported": True,
        }, cfg=cfg)
        st2 = tr.reduce(st2, {"kind": "pty_probe", "t": t0 + 390_000, "changed": True, "digest": "spin"}, cfg=cfg)
        st2, acts2 = tr.tick(st2, t0 + 395_000, cfg)
        rec2 = [a for a in acts2 if a.get("kind") == "recovery_action"]
        self.assertEqual([(a["class"], a["stage"], a["action"]) for a in rec2], [("W1", 0, "interrupt_turn")])
        inc2_id = rec2[0]["incident_id"]
        st2 = tr.reduce(st2, {
            "kind": "recovery_started", "t": t0 + 395_000, "incident_id": inc2_id,
            "class": "W1", "stage": 0, "action": "interrupt_turn",
        }, cfg=cfg)
        st2 = tr.reduce(st2, {
            "kind": "recovery_result", "t": t0 + 395_100, "incident_id": inc2_id,
            "class": "W1", "stage": 0, "action": "interrupt_turn", "outcome": "still_working",
        }, cfg=cfg)
        st2, acts2_next = tr.tick(st2, t0 + 395_500, cfg)
        rec2_next = [a for a in acts2_next if a.get("kind") == "recovery_action"]
        self.assertEqual([(a["class"], a["stage"], a["action"]) for a in rec2_next], [("W2", 3, "notify_user")])
        self.assertEqual(st2["turn"]["phase"], "generating")


class FakePmAgentHarness:
    """Scriptable `FakePmAgent` E2E harness binding `ProjectSupervisor`, `EndpointDriver`,
    `FakeTransport`, `FakeProcs`, `FakeClock`, `TurnTracker`, and `MailboxStore` (§5)."""

    def __init__(self, root: Path, *, recovery_cfg: dict | None = None) -> None:
        self.root = root
        self.repo = root / "proj"
        self.repo.mkdir(parents=True, exist_ok=True)
        self.clock = FakeClock("2026-11-26 10:00:00")
        self.hc = FakeHc(
            terminals={
                "t7": {
                    "address": "t7",
                    "id": "t7",
                    "state": "live",
                    "status": {"state": "idle", "ms": int(self.clock.time() * 1000)},
                    "turn": 1,
                    "foreground": {"pid": 4100, "argv": ["claude"]},
                    "labels": {"pm": "proj", "pm.seat": "1"},
                },
            },
            clock=self.clock,
        )
        self.procs = FakeProcs(root / "ledger" / "home")
        self.alerts: list[tuple[str, str, dict]] = []
        cfg = {"lang": "en"}
        if recovery_cfg is not None:
            cfg["pm"] = {"recovery": dict(recovery_cfg)}
        self.ctx = make_ctx(
            root / "ledger",
            hc=self.hc,
            procs=self.procs,
            clock=self.clock,
            config=cfg,
        )
        self.ctx.alert_sinks = (lambda slug, repo, payload: self.alerts.append((slug, repo, dict(payload))),)
        self.slug = project_slug(self.repo)
        self.ep = Endpoint(
            runtime="hc",
            machine=None,
            terminal="t7",
            fg_pid=4100,
            epoch=1,
            agent_kind="claude",
        )
        self.reg = {
            "name": f"pm-{self.slug}",
            "project": "proj",
            "repo": str(self.repo),
            "pane": "hc:t7",
            "terminal": "t7",
            "runtime": "hc",
            "agent": "claude",
            "epoch": 1,
            "endpoint": self.ep.to_dict(),
        }
        self.ctx.store.change_registration(self.slug, lambda _c: dict(self.reg))
        self.transport = FakeTransport(clock=self.clock)
        self.transport.configure(self.ep, agent_state="idle", turn=1, status_ms=self.now_ms())
        self.rotations: list[dict[str, str | None]] = []
        self.driver = EndpointDriver(self.ctx, self.repo, transport=self.transport)
        self.supervisor = ProjectSupervisor(
            self.ctx,
            self.repo,
            transport=self.transport,
            rotate_fn=self._on_rotate,
        )

    def _on_rotate(self, *, repo: str, reason: str, profile: str | None = None, force: bool = False) -> bool:
        self.rotations.append({"repo": repo, "reason": reason, "profile": profile, "force": force})
        return True

    def now_ms(self) -> int:
        return int(self.clock.time() * 1000)

    def set_terminal(
        self,
        *,
        state: str = "live",
        agent_status: str = "idle",
        fg_pid: int = 4100,
        epoch: int | None = None,
        screen: str | None = None,
        dialog_kind: str = "",
        has_draft: bool = False,
        turn: int | None = None,
    ) -> None:
        if epoch is not None and epoch != self.reg.get("epoch"):
            self.ep = Endpoint(
                runtime="hc",
                machine=None,
                terminal="t7",
                fg_pid=fg_pid,
                epoch=epoch,
                agent_kind="claude",
            )
            self.reg = {**self.reg, "epoch": epoch, "endpoint": self.ep.to_dict()}
            self.ctx.store.change_registration(self.slug, lambda _c: dict(self.reg))
        t_cur = int(turn if turn is not None else self.hc.terminals["t7"].get("turn") or 1)
        st_obj = None if state != "live" else {"state": agent_status, "ms": self.now_ms(), **({"kind": dialog_kind} if dialog_kind else {})}
        prev_screen = str((self.hc.terminals.get("t7") or {}).get("screen") or "")
        eff_screen = prev_screen if screen is None else screen
        self.hc.terminals["t7"] = {
            "address": "t7",
            "id": "t7",
            "state": state,
            "status": st_obj,
            "turn": t_cur,
            "foreground": {"pid": fg_pid, "argv": ["claude"]} if state == "live" else None,
            "has_draft": has_draft,
            "screen": eff_screen,
            "labels": {"pm": "proj", "pm.seat": "1"},
        }
        if screen is not None:
            self.transport.configure(self.ep, screen=screen)
        self.transport.configure(
            self.ep,
            live=(state == "live"),
            agent_state=agent_status if state == "live" else "",
            turn=t_cur,
            status_ms=self.now_ms(),
        )

    def send_user_message(self, text: str = "Please check the PR", msg_id: str = "u-msg-1") -> str:
        env = Envelope(
            env_id=new_env_id(self.now_ms()),
            idempotency_key=f"chat.user:{msg_id}",
            schema_version=1,
            created_ms=self.now_ms(),
            kind="chat.user",
            sender=Principal.user(),
            recipient=LogicalAddress.pm(self.slug),
            project=self.slug,
            cause={"kind": "user", "msg_id": msg_id},
            priority=P1_USER,
            body={"text": text, "msg_id": msg_id},
            require_reply=True,
        )
        Conversation(self.ctx, self.repo).record("user", msg_id=msg_id, text=text)
        self.supervisor.tracker.ensure_mailbox_migrated()
        self.supervisor.tracker.pm_mailbox.enqueue(
            env, initial_state="accepted", now_ms=self.now_ms(),
            target_endpoint_uid=self.ep.uid, endpoint_epoch=self.ep.epoch,
        )
        return env.env_id

    def run_prompt_hook(self, prompt_text: str, *, session_id: str = "sess-pm") -> None:
        hook_ctx = make_ctx(
            self.root / "ledger",
            pane="hc:t7",
            hc=self.hc,
            clock=self.clock,
            procs=self.procs,
            config=self.ctx.config.read(),
        )
        hook_ctx.caller = Caller(hook_ctx)
        payload = json.dumps({
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "cwd": str(self.repo),
            "prompt": prompt_text,
        })
        with mock.patch.object(sys, "stdin", io.StringIO(payload)), contextlib.redirect_stdout(io.StringIO()):
            hooks.cmd_hook_turn(None, ctx=hook_ctx)

    def pump_delivery(self, *, run_hook: bool = True) -> DeliverOutcome | None:
        info = self.hc.get_raw("t7", errors=True)
        before_n = len(self.transport.deliveries)
        # First pass starts async handle; second pass polls & settles immediately since FakeTransport delay_ms=0.
        out, _ = self.driver.drive_pm_endpoint(self.reg, info)
        if self.driver.has_inflight():
            out, _ = self.driver.drive_pm_endpoint(self.reg, info)
        if run_hook and out is not None and out.status == "typed" and out.started_turn is True:
            for d in self.transport.deliveries[before_n:]:
                self.run_prompt_hook(str(d["text"]))
        return out

    def tick_supervisor(self, dt_s: float = 0.0, *, screen: str | None = None) -> tuple[dict, float | None]:
        if dt_s > 0:
            self.clock.advance(dt_s)
        if screen is not None:
            entry = self.hc.terminals.get("t7")
            if isinstance(entry, dict):
                entry["screen"] = screen
            self.transport.configure(self.ep, screen=screen)
        info = self.hc.get_raw("t7", errors=True) or {}
        if info.get("state") == "live" and isinstance(info.get("status"), dict):
            self.transport.configure(self.ep, agent_state=str(info["status"].get("state") or "idle"))
        return self.supervisor.observe_and_reduce(self.reg, info)

    def incident_events(self) -> list[dict]:
        return [
            e for e in Conversation(self.ctx, self.repo).events()
            if e.get("type") == "event" and e.get("source") == "pm-incident"
        ]


class FakePmAgentE2ETests(unittest.TestCase):
    """Scripted end-to-end tests matching §5 (W1..W7a) and SLO-4 (recovery <= 4m)."""

    def test_w1_upstream_hang_interrupts_continues_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = FakePmAgentHarness(Path(tmp))
            h.send_user_message("Investigate flaky test", msg_id="u1")
            h.pump_delivery()
            h.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_prompt", "t": h.now_ms(), "cause": "user", "msg_ids": ["u1"]}, reduce_now=True)
            h.set_terminal(agent_status="working", screen="Generating frame 1...")
            h.tick_supervisor(5.0)

            # Screen keeps changing (spinner animation only, no growing tokens) -> W1 stall + interrupt_turn + continue_turn
            h.transport.configure(h.ep, next_interrupt=InterruptOutcome(status="stopped", key_sent="Escape", detail="stopped"))
            for i in range(1, 30):
                h.tick_supervisor(10.0, screen=f"Thinking spinner frame {i}...")
                if h.transport.interrupts:
                    # One more pass executes due `continue_turn` right after interrupt_turn verified `stopped`.
                    h.tick_supervisor(0.5, screen="> ")
                    break

            self.assertEqual(len(h.transport.interrupts), 1)
            # Deliver the queued `[from pm.py supervisor ...]` resume prompt on the now-idle terminal.
            h.set_terminal(agent_status="idle", turn=2)
            h.pump_delivery()
            resume_deliveries = [d for d in h.transport.deliveries if "[from pm.py supervisor" in d["text"]]
            self.assertEqual(len(resume_deliveries), 1)
            self.assertIn("pm.py status", resume_deliveries[0]["text"])

            # Turn finishes with reply -> incident resolves and folds within <=4m
            h.supervisor.tracker.append_observation({"src": "claude", "kind": "step_reply", "t": h.now_ms()}, reduce_now=True)
            h.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_stop", "t": h.now_ms(), "has_reply": True}, reduce_now=True)
            st_done, _ = h.tick_supervisor(1.0)
            self.assertEqual(st_done["incident"]["status"], "resolved")
            self.assertTrue(st_done["incident"]["folded"])
            inc_rows = h.incident_events()
            self.assertTrue(inc_rows)
            self.assertEqual(len({r["key"] for r in inc_rows}), 1)
            self.assertEqual(inc_rows[-1]["status"], "resolved")

    def test_w2_dead_turn_retries_at_20s_and_90s_then_safe_notifies_or_full_rotates(self) -> None:
        # 1. Under `"safe"` with fallback_profiles: retry 20s, retry 90s, then notify_user suggesting fallback
        with tempfile.TemporaryDirectory() as tmp1:
            h = FakePmAgentHarness(Path(tmp1), recovery_cfg={"auto": "safe", "fallback_profiles": ["sonnet-fallback"]})
            h.send_user_message("Deploy script", msg_id="u2")
            h.pump_delivery()
            h.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_prompt", "t": h.now_ms(), "cause": "user", "msg_ids": ["u2"]}, reduce_now=True)
            h.set_terminal(agent_status="error")
            h.tick_supervisor(2.0)
            self.assertTrue(any(r["incident_class"] == "W2" for r in h.incident_events()))

            # At +20s -> retry #1 queued; deliver it (hook consumes cmd.resume_turn!) -> errored again
            h.set_terminal(agent_status="idle")
            st1, _ = h.tick_supervisor(21.0)
            self.assertEqual(len(h.transport.deliveries), 1)
            h.pump_delivery()
            resume1 = [d for d in h.transport.deliveries if "[from pm.py supervisor" in d["text"]]
            self.assertEqual(len(resume1), 1)
            self.assertEqual(h.supervisor.tracker.pm_mailbox.get(resume1[0]["env_id"]).state, "consumed")
            h.set_terminal(agent_status="error", turn=2)
            h.tick_supervisor(2.0)

            # G5 must NOT 0s-requeue `cmd.resume_turn` after error: even when idle at +1s, 0 extra deliveries before 90s!
            self.assertEqual(h.supervisor.tracker.pm_mailbox.get(resume1[0]["env_id"]).state, "answered")
            h.set_terminal(agent_status="idle")
            h.pump_delivery()
            self.assertEqual(len([d for d in h.transport.deliveries if "[from pm.py supervisor" in d["text"]]), 1)

            # At +90s -> retry #2 queued; deliver -> errored again -> notifies user (NO auto rotation under safe!)
            h.tick_supervisor(92.0)
            h.pump_delivery()
            self.assertEqual(len([d for d in h.transport.deliveries if "[from pm.py supervisor" in d["text"]]), 2)
            h.set_terminal(agent_status="error", turn=3)
            st_end, _ = h.tick_supervisor(2.0)
            self.assertEqual(h.rotations, [])
            self.assertEqual(st_end["incident"]["status"], "notified")
            self.assertTrue(any(a[2]["suggested_profile"] == "sonnet-fallback" for a in h.alerts))

        # 2. Under `"full"` with fallback_profiles and capacity error: immediately force-rotates to fallback_profiles[0]
        with tempfile.TemporaryDirectory() as tmp2:
            h2 = FakePmAgentHarness(Path(tmp2), recovery_cfg={"auto": "full", "fallback_profiles": ["sonnet-fallback"]})
            h2.send_user_message("Analyze logs", msg_id="u2b")
            h2.pump_delivery()
            h2.supervisor.tracker.append_observation({"src": "claude", "kind": "step_error", "t": h2.now_ms(), "message": "API overloaded 529"}, reduce_now=True)
            h2.set_terminal(agent_status="error")
            h2.tick_supervisor(1.0)
            self.assertEqual(len(h2.rotations), 1)
            self.assertEqual(h2.rotations[0]["profile"], "sonnet-fallback")
            self.assertIs(h2.rotations[0]["force"], True)

    def test_w3_safe_dialog_unblocks_and_unknown_dialog_notifies_without_incident_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = FakePmAgentHarness(Path(tmp))
            # Safe update dialog -> auto-unblocked with ["enter"] (2nd choice or update enter)
            h.set_terminal(
                agent_status="blocked",
                dialog_kind="update",
                screen="Update available! Run update?\n1. Update now\n❯ 2. Skip this time\n",
            )
            st, _ = h.tick_supervisor(1.0)
            self.assertEqual(len(h.transport.unblocks), 1)
            self.assertIsNone(st.get("incident"))
            self.assertEqual(h.incident_events(), [])

            # Unknown / permission dialog -> NOT auto-answered, notifies user instead
            h.set_terminal(
                agent_status="blocked",
                dialog_kind="permission",
                screen="Allow bash command `rm -rf /tmp/x`? (y/n)",
            )
            unblocks_before = len(h.transport.unblocks)
            h.tick_supervisor(1.0)
            self.assertEqual(len(h.transport.unblocks), unblocks_before)
            self.assertTrue(len(h.alerts) >= 1)
            self.assertEqual(h.incident_events(), [])

    def test_w4_command_subtree_signaled_only_and_unkillable_escalates(self) -> None:
        # 1. Hung foreground command that exits on SIGINT -> tool killed cleanly, agent PID NEVER signaled, turn resumes!
        with tempfile.TemporaryDirectory() as tmp1:
            h = FakePmAgentHarness(Path(tmp1))
            h.procs._foreground_tool_stat = lambda _info: {"tool_pid": 8801, "cmd": "sleep 999", "cpu_ms": 0}
            h.procs._tool_alive_fn = lambda _pid, _agent: False  # exited right after SIGINT
            h.send_user_message("Run tests", msg_id="u4")
            h.pump_delivery()
            h.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_prompt", "t": h.now_ms(), "cause": "user", "msg_ids": ["u4"]}, reduce_now=True)
            h.set_terminal(agent_status="working", fg_pid=4100)
            h.supervisor.tracker.append_observation({"src": "claude", "kind": "step_tool_start", "t": h.now_ms(), "tool": "Bash", "summary": "sleep 999"}, reduce_now=True)
            # Probe screen & proc across tool_soft -> suspect -> stalled (waiting input -> SIGINT subtree only)
            st_res: dict = {}
            for _ in range(25):
                st_res, _ = h.tick_supervisor(10.0, screen="Enter password:")
                if h.procs.signaled_tools:
                    break
            self.assertTrue(h.procs.signaled_tools)
            self.assertEqual(h.procs.signaled_tools[0]["tool_pid"], 8801)
            self.assertEqual(h.procs.signaled_tools[0]["agent_pid"], 4100)
            self.assertEqual(h.procs.signaled_tools[0]["sig"], int(signal.SIGINT))
            self.assertEqual(h.transport.interrupts, [])
            self.assertEqual(st_res["turn"]["phase"], "generating")
            self.assertEqual(st_res["turn"]["health"], "ok")

        # 2. Unkillable command (stays alive across SIGINT -> SIGTERM -> SIGKILL) escalates to interrupt_turn + continue_turn with W4 note
        with tempfile.TemporaryDirectory() as tmp2:
            h2 = FakePmAgentHarness(Path(tmp2))
            h2.procs._foreground_tool_stat = lambda _info: {"tool_pid": 8802, "cmd": "yes", "cpu_ms": 500}
            h2.procs._tool_alive_fn = lambda _pid, _agent: True  # unkillable!
            h2.transport.configure(h2.ep, next_interrupt=InterruptOutcome(status="stopped", key_sent="Escape", detail="stopped"))
            h2.send_user_message("Check output", msg_id="u4b")
            h2.pump_delivery()
            h2.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_prompt", "t": h2.now_ms(), "cause": "user", "msg_ids": ["u4b"]}, reduce_now=True)
            h2.set_terminal(agent_status="working", fg_pid=4100)
            h2.supervisor.tracker.append_observation({"src": "claude", "kind": "step_tool_start", "t": h2.now_ms(), "tool": "Bash", "summary": "yes"}, reduce_now=True)
            # Trigger W4 via hard budget (180s)
            for _ in range(42):
                h2.tick_supervisor(5.0, screen="still running...")
            sigs = [s["sig"] for s in h2.procs.signaled_tools]
            self.assertIn(int(signal.SIGINT), sigs)
            self.assertIn(int(signal.SIGTERM), sigs)
            self.assertIn(int(signal.SIGKILL), sigs)
            self.assertTrue(h2.transport.interrupts)
            h2.set_terminal(agent_status="idle", turn=2)
            h2.pump_delivery()
            resumes = [d["text"] for d in h2.transport.deliveries if "[from pm.py supervisor" in d["text"]]
            self.assertTrue(resumes)
            self.assertIn("yes", resumes[-1])
            self.assertIn("180s", resumes[-1])

    def test_w5_frozen_process_classifies_dialog_or_restarts_seat(self) -> None:
        # Case A: screen unchanged 45s actually holds an unreported update dialog -> routes to W3 without Esc!
        with tempfile.TemporaryDirectory() as tmp1:
            h = FakePmAgentHarness(Path(tmp1))
            h.send_user_message("Do work", msg_id="u5a")
            h.pump_delivery()
            h.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_prompt", "t": h.now_ms(), "cause": "user", "msg_ids": ["u5a"]}, reduce_now=True)
            h.set_terminal(agent_status="working", screen="Update available!\n1. Update\n❯ 2. Skip\n")
            for _ in range(16):
                h.tick_supervisor(5.5, screen="Update available!\n1. Update\n❯ 2. Skip\n")
                if any(keys for _uid, keys in h.transport.unblocks):
                    break
            self.assertEqual(h.transport.interrupts, [])
            self.assertTrue(any(keys for _uid, keys in h.transport.unblocks))

        # Case B: truly frozen screen -> interrupt (`still_working`) -> `restart_seat` -> new fg_pid/epoch resolves!
        with tempfile.TemporaryDirectory() as tmp2:
            h2 = FakePmAgentHarness(Path(tmp2))
            h2.transport.configure(h2.ep, next_interrupt=InterruptOutcome(status="still_working", key_sent="Escape", detail="hung"))
            h2.send_user_message("Do work", msg_id="u5b")
            h2.pump_delivery()
            h2.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_prompt", "t": h2.now_ms(), "cause": "user", "msg_ids": ["u5b"]}, reduce_now=True)
            h2.set_terminal(agent_status="working", screen="static frozen frame")
            for _ in range(18):
                h2.tick_supervisor(5.5, screen="static frozen frame")
                if h2.rotations:
                    break
            self.assertTrue(h2.transport.interrupts)
            self.assertTrue(h2.rotations)
            h2.set_terminal(agent_status="idle", fg_pid=4299, epoch=2, turn=1)
            st_after, _ = h2.tick_supervisor(1.0)
            self.assertEqual(st_after["incident"]["status"], "resolved")
            self.assertEqual(st_after["incident"]["resolution"], "session_rotated")
            self.assertEqual(h2.incident_events()[-1]["status"], "resolved")

    def test_w6_unstarted_submitted_nudges_enter_and_retypes_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = FakePmAgentHarness(Path(tmp))
            env_id = h.send_user_message("Ping PM", msg_id="u6")
            # Simulate typed-but-unstarted send (started_turn=False) -> phase enters `submitted`.
            h.transport.configure(
                h.ep,
                next_deliver=DeliverOutcome(status="typed", started_turn=False, observed_turn=1, detail="unstarted"),
            )
            h.pump_delivery()
            h.set_terminal(agent_status="idle", screen="> Ping PM", has_draft=False)
            for _ in range(8):
                h.tick_supervisor(5.0, screen="> Ping PM")
                if any(keys == ("enter",) for _uid, keys in h.transport.unblocks):
                    break
            self.assertIn((h.ep.uid, ("enter",)), h.transport.unblocks)

            # Still unstarted -> escalate to `retype_submitted` using same envelope id (no duplicate user event!)
            for _ in range(5):
                h.tick_supervisor(6.0, screen="> ")
                item = h.supervisor.tracker.pm_mailbox.get(env_id)
                if item and item.state == "accepted":
                    break
            h.pump_delivery()
            deliver_env_ids = [d["env_id"] for d in h.transport.deliveries if "Ping PM" in d["text"]]
            self.assertEqual(deliver_env_ids.count(env_id), 1)
            self.assertEqual(h.supervisor.tracker.pm_mailbox.get(env_id).attempts, 2)
            user_events = [e for e in Conversation(h.ctx, h.repo).events() if e.get("type") == "user"]
            self.assertEqual(len(user_events), 1)

    def test_w7_dead_coordinator_restarts_and_w7a_stale_beat_kills_and_revives(self) -> None:
        # 1. W7: dead/exited coordinator session with unanswered user message -> restart_seat
        with tempfile.TemporaryDirectory() as tmp1:
            h = FakePmAgentHarness(Path(tmp1))
            h.send_user_message("Important question", msg_id="u7")
            h.set_terminal(state="exited")
            h.tick_supervisor(1.0)
            self.assertEqual(len(h.rotations), 1)
            self.assertIn("recovery W7", str(h.rotations[0]["reason"]))

        # 2. W7a: reader detects beat_age > w7_stale_kill_ms (60s) with active deliver.lock -> kills stale beat pid & revives
        with tempfile.TemporaryDirectory() as tmp2:
            h2 = FakePmAgentHarness(Path(tmp2))
            tracker = TurnTracker(h2.ctx, h2.repo)
            # Advance clock past initial 0 -> write heartbeat with stale pid=54321 at t=100, then jump +75s
            touch_heartbeat(tracker.files.pm_turn_beat, h2.clock.time(), pid=54321)
            h2.clock.advance(75.0)
            with mock.patch.object(Delivery, "is_running", side_effect=[True, False]):
                view = read_pm_turn_view(h2.ctx, h2.repo, h2.reg, term_info=h2.hc.get_raw("t7"), revive=True)
            self.assertFalse(view["supervised"])
            self.assertEqual(view["turn2"]["turn"]["health"], "unknown")
            self.assertIn(54321, h2.procs.terminated_pids)
            self.assertTrue(any(s["args"][:2] == ["deliver", str(h2.repo)] for s in h2.procs.spawned))


class SeatRotateProfileTests(unittest.TestCase):
    """Phase 4 `pm.py rotate --reason --profile` preserves epoch bump & unconsumed envelope requeue."""

    def test_rotate_with_reason_and_profile_bumps_epoch_requeues_envelopes_and_writes_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "alpha"
            repo.mkdir()
            repo_s = str(repo.resolve())
            slug = project_slug(repo_s)
            clock = FakeClock("2026-11-26 11:00:00")
            hc = FakeHc(
                terminals={
                    "t7": {
                        "address": "t7",
                        "state": "live",
                        "status": {"state": "idle"},
                        "labels": {"pm": "alpha", "pm.seat": "1"},
                        "argv": ["claude", "--model", "opus"],
                        "foreground": {"pid": 3001, "argv": ["claude"]},
                    },
                },
                clock=clock,
            )
            cfg = {
                "lang": "en",
                "profiles": {
                    "fallback": {"kind": "codex", "model": "gpt-5-codex"},
                },
            }
            ctx = make_ctx(root / "home", hc=hc, clock=clock, config=cfg)
            ep = Endpoint(runtime="hc", machine=None, terminal="t7", fg_pid=3001, epoch=1, agent_kind="claude")
            ctx.store.change_registration(slug, lambda _c: {
                "name": f"pm-{slug}",
                "project": "alpha",
                "repo": repo_s,
                "pane": "hc:t7",
                "terminal": "t7",
                "runtime": "hc",
                "seat": True,
                "agent": "claude",
                "epoch": 1,
                "endpoint": ep.to_dict(),
            })
            tracker = TurnTracker(ctx, repo_s)
            tracker.ensure_mailbox_migrated()
            env = Envelope(
                env_id="env_u99",
                idempotency_key="user:u99",
                schema_version=1,
                created_ms=int(clock.time() * 1000),
                kind="chat.user",
                sender=Principal.user(),
                recipient=LogicalAddress.pm(slug),
                project=slug,
                cause={"kind": "user", "msg_id": "u99"},
                priority=P1_USER,
                body={"text": "Carry me over", "msg_id": "u99"},
                require_reply=True,
            )
            tracker.pm_mailbox.enqueue(env, initial_state="accepted", now_ms=1000, target_endpoint_uid=ep.uid, endpoint_epoch=1)
            tracker.pm_mailbox.transition(env.env_id, "typed", now_ms=1100, target_endpoint_uid=ep.uid, endpoint_epoch=1)

            svc = ManagerSessions(ctx)
            res = svc.rotate(repo_s, reason="recovery W2: overloaded", profile="fallback")
            self.assertEqual(res.mode, "seat")

            next_spec = json.loads((ctx.home.project_for(repo_s).root / "next-session.json").read_text(encoding="utf-8"))
            self.assertEqual(next_spec["kind"], "codex")
            self.assertIn("gpt-5-codex", " ".join(next_spec["argv"]))

            reg_after = ctx.store.registration(slug) or {}
            self.assertEqual(reg_after["epoch"], 2)
            self.assertEqual(reg_after["agent"], "codex")

            # Typed-but-unconsumed envelope from epoch 1 was requeued to accepted!
            requeued = tracker.pm_mailbox.get("env_u99")
            assert requeued is not None
            self.assertEqual(requeued.state, "accepted")

            events = Conversation(ctx, repo_s).events()
            notices = [e for e in events if e.get("type") == "pm" and e.get("notice") and "recovery W2" in str(e.get("text") or "")]
            self.assertTrue(notices)
            self.assertIn("fallback", swap_reason_text(profile="fallback", ctx=ctx))


class CarbonReviewFixesTests(unittest.TestCase):
    """Regression coverage for the 5 fixes requested during carbon independent review."""

    def test_deliverer_and_router_unblock_resume_and_requeued_batch_when_recovering_on_error(self) -> None:
        # Scenario A: W2 dead user turn (`status=error`) -> `Deliverer.look()` opens W2, waits 20s,
        # enqueues `cmd.resume_turn` while `v2_phase == "recovering"`, and delivers WITHOUT `--if idle`.
        with tempfile.TemporaryDirectory() as tmp1:
            repo = Path(tmp1) / "proj"
            repo.mkdir()
            clock = FakeClock("2026-11-26 12:00:00")
            hc = FakeHc(
                terminals={
                    "t7": {
                        "address": "t7",
                        "state": "live",
                        "status": {"state": "working", "ms": int(clock.time() * 1000)},
                        "turn": 1,
                        "foreground": {"pid": 4100, "argv": ["claude"]},
                        "labels": {"pm": "proj", "pm.seat": "1"},
                    },
                },
                clock=clock,
            )
            ctx = make_ctx(Path(tmp1) / "ledger", hc=hc, clock=clock, config={"lang": "en"})
            slug = project_slug(repo)
            ep = Endpoint(runtime="hc", machine=None, terminal="t7", fg_pid=4100, epoch=1, agent_kind="claude")
            ctx.store.change_registration(slug, lambda _c: {
                "name": f"pm-{slug}", "project": "proj", "repo": str(repo), "pane": "hc:t7",
                "terminal": "t7", "runtime": "hc", "agent": "claude", "epoch": 1, "endpoint": ep.to_dict(),
            })
            dlv = Deliverer(ctx, repo, watchers=(), holds=(), settle=0)
            changes = FakeChangeWaiter()
            Conversation(ctx, repo).record("user", msg_id="u10", text="Fix build")
            dlv._supervisor.tracker.begin_turn(terminal="t7", agent_kind="claude", cause="user", msg_ids=["u10"], from_hook=True)
            dlv.look(changes, {}, {})  # observes working

            # Turn crashes to error while status stays `error` (no flip to `idle`).
            clock.advance(2.0)
            hc.terminals["t7"]["status"] = {"state": "error", "ms": int(clock.time() * 1000)}
            dlv.look(changes, {}, {})  # opens W2

            # Advance past w2_retry1_delay_ms (20s): next `Deliverer.look()` queues AND sends `cmd.resume_turn`
            # immediately without `--if idle` even while terminal still reports `error`!
            send_calls: list[tuple] = []
            orig_send = hc.send

            def _rec_send(term, text, **kw):
                send_calls.append((term, text, kw.get("if_state")))
                return orig_send(term, text, **kw)

            hc.send = _rec_send
            clock.advance(21.0)
            dlv.look(changes, {}, {})
            resume_sends = [c for c in send_calls if "[from pm.py supervisor" in c[1]]
            self.assertEqual(len(resume_sends), 1, send_calls)
            self.assertIsNone(resume_sends[0][2], "errored terminal resume must NOT pass --if idle")

        # Scenario B: Requeued `event.batch` during W1/W2 recovery on an `error` terminal is NOT blocked by router.
        with tempfile.TemporaryDirectory() as tmp2:
            repo2 = Path(tmp2) / "proj2"
            repo2.mkdir()
            clock2 = FakeClock("2026-11-26 12:10:00")
            hc2 = FakeHc(
                terminals={
                    "t7": {
                        "address": "t7",
                        "state": "live",
                        "status": {"state": "working", "ms": int(clock2.time() * 1000)},
                        "turn": 1,
                        "foreground": {"pid": 4200, "argv": ["claude"]},
                        "labels": {"pm": "proj2", "pm.seat": "1"},
                    },
                },
                clock=clock2,
            )
            ctx2 = make_ctx(Path(tmp2) / "ledger", hc=hc2, clock=clock2, config={"lang": "en"})
            slug2 = project_slug(repo2)
            ep2 = Endpoint(runtime="hc", machine=None, terminal="t7", fg_pid=4200, epoch=1, agent_kind="claude")
            ctx2.store.change_registration(slug2, lambda _c: {
                "name": f"pm-{slug2}", "project": "proj2", "repo": str(repo2), "pane": "hc:t7",
                "terminal": "t7", "runtime": "hc", "agent": "claude", "epoch": 1, "endpoint": ep2.to_dict(),
            })
            Conversation(ctx2, repo2).record("thread", task="proj2-t1", title="t1", status="review", by="hc:t20", text="status=review", wake=True)
            log_sz = (ctx2.home.project_for(repo2).conversation).stat().st_size
            dlv2 = Deliverer(ctx2, repo2, watchers=(), holds=(), settle=0)
            changes2 = FakeChangeWaiter()
            dlv2._supervisor.tracker.ensure_mailbox_migrated()
            batch_env = Envelope(
                env_id="env_01a218000000_0000b101", idempotency_key=f"batch:{slug2}:0-{log_sz}", schema_version=1,
                created_ms=int(clock2.time() * 1000), kind="event.batch",
                sender=Principal.supervisor(slug2), recipient=LogicalAddress.pm(slug2),
                project=slug2, cause={"kind": "deliver_batch", "start": 0, "end": log_sz},
                priority=P4_BATCH, body={"text": f"[from pm.py deliver] 1 event(s) (0-{log_sz})\n1. done", "start": 0, "end": log_sz},
                require_reply=True,
            )
            dlv2._supervisor.tracker.pm_mailbox.enqueue(
                batch_env, initial_state="accepted", now_ms=int(clock2.time() * 1000),
                target_endpoint_uid=ep2.uid, endpoint_epoch=1,
            )
            dlv2._supervisor.tracker.pm_mailbox.transition(batch_env.env_id, "typed", now_ms=int(clock2.time() * 1000))
            dlv2.advance_delivered(log_sz)
            dlv2._supervisor.tracker.begin_turn(terminal="t7", agent_kind="claude", cause="deliver", batch=[0, log_sz], from_hook=True)
            dlv2.look(changes2, {}, {})
            send_calls2: list[tuple] = []
            orig_send2 = hc2.send

            def _rec_send2(term, text, **kw):
                send_calls2.append((term, text, kw.get("if_state")))
                return orig_send2(term, text, **kw)

            hc2.send = _rec_send2
            clock2.advance(2.0)
            hc2.terminals["t7"]["status"] = {"state": "error", "ms": int(clock2.time() * 1000)}
            dlv2.look(changes2, {}, {})  # opens W2 (deliver)
            clock2.advance(21.0)
            dlv2.look(changes2, {}, {})  # requeues env_b1 AND delivers it on error terminal without `--if idle`!
            batch_sends = [c for c in send_calls2 if "[from pm.py deliver" in c[1]]
            self.assertTrue(batch_sends, send_calls2)
            self.assertIsNone(batch_sends[-1][2])

    def test_self_cause_w1_stall_does_not_queue_fake_continuation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = FakePmAgentHarness(Path(tmp))
            h.supervisor.tracker.begin_turn(terminal="t7", agent_kind="claude", cause="self", from_hook=True)
            h.set_terminal(agent_status="working", screen="Working quietly...")
            h.transport.configure(h.ep, next_interrupt=InterruptOutcome(status="stopped", key_sent="Escape", detail="stopped"))
            for i in range(1, 30):
                st, _ = h.tick_supervisor(10.0, screen=f"Spinner frame {i}")
                if h.transport.interrupts:
                    h.tick_supervisor(0.5, screen="> ")
                    break
            self.assertEqual(len(h.transport.interrupts), 1)
            h.set_terminal(agent_status="idle", turn=2)
            h.pump_delivery()
            self.assertEqual(h.transport.deliveries, [])
            st_after, _ = h.tick_supervisor(0.5)
            self.assertEqual((st_after.get("incident") or {}).get("status"), "resolved")

    def test_force_rotate_and_end_session_force_skip_idle_wait_for_frozen_seat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "beta"
            repo.mkdir()
            repo_s = str(repo.resolve())
            slug = project_slug(repo_s)
            clock = FakeClock("2026-11-26 12:30:00")
            hc = FakeHc(
                terminals={
                    "t7": {
                        "address": "t7", "state": "live", "status": {"state": "working"},
                        "labels": {"pm": "beta", "pm.seat": "1"},
                        "argv": ["claude"], "foreground": {"pid": 5100, "argv": ["claude"]},
                    },
                },
                clock=clock,
            )
            ctx = make_ctx(root / "home", hc=hc, clock=clock)
            ctx.store.change_registration(slug, lambda _c: {
                "name": f"pm-{slug}", "project": "beta", "repo": repo_s, "pane": "hc:t7",
                "terminal": "t7", "runtime": "hc", "seat": True, "agent": "claude",
            })
            write_seat_state(repo_s, {"terminal": "t7", "pid": 5000, "agent_pid": 5100}, ctx=ctx)

            svc = ManagerSessions(ctx)
            svc.rotate(repo_s, reason="recovery W5: frozen", force=True)
            end_spawns = [s for s in ctx.procs.spawned if s["args"][:1] == ["end-session"]]
            self.assertEqual(len(end_spawns), 1)
            self.assertIn("--force", end_spawns[0]["args"])

            # `end_session(..., force=True)` kills the frozen session PID group immediately while working, without sleeping.
            with mock.patch.object(osutil, "pid_alive", return_value=True), \
                    mock.patch.object(osutil, "stop_pid_group") as stop_pg:
                svc.end_session("t7", repo_arg=repo_s, agent_pid=5100, force=True)
            stop_pg.assert_called_once_with(5100)

        # Verify default `spawn_pm` path passes `--force` on W5 `restart_seat`.
        with tempfile.TemporaryDirectory() as tmp2:
            h2 = FakePmAgentHarness(Path(tmp2))
            h2.supervisor._rotate_fn = None
            h2.transport.configure(h2.ep, next_interrupt=InterruptOutcome(status="still_working", key_sent="Escape", detail="hung"))
            h2.send_user_message("Freeze check", msg_id="u_w5f")
            h2.pump_delivery()
            h2.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_prompt", "t": h2.now_ms(), "cause": "user", "msg_ids": ["u_w5f"]}, reduce_now=True)
            h2.set_terminal(agent_status="working", screen="frozen screen")
            for _ in range(18):
                h2.tick_supervisor(5.5, screen="frozen screen")
                if any(s["args"][:1] == ["rotate"] for s in h2.procs.spawned):
                    break
            rot_spawns = [s["args"] for s in h2.procs.spawned if s["args"][:1] == ["rotate"]]
            self.assertEqual(len(rot_spawns), 1)
            self.assertIn("--force", rot_spawns[0])

    def test_w7_dead_seat_while_terminal_live_and_w7a_pid_command_check(self) -> None:
        # 4a: Terminal `state="live"` while `seat_says_alive=False` (seat crashed back to shell) triggers W7 rotate --force.
        with tempfile.TemporaryDirectory() as tmp1:
            repo = Path(tmp1) / "proj"
            repo.mkdir()
            clock = FakeClock("2026-11-26 12:40:00")
            hc = FakeHc(
                terminals={
                    "t7": {
                        "address": "t7", "state": "live", "status": None,
                        "labels": {"pm": "proj", "pm.seat": "1"},
                        "argv": ["zsh"], "foreground": {"pid": 6100, "argv": ["zsh"]},
                    },
                },
                clock=clock,
            )
            ctx = make_ctx(Path(tmp1) / "ledger", hc=hc, clock=clock)
            slug = project_slug(repo)
            ep = Endpoint(runtime="hc", machine=None, terminal="t7", fg_pid=6100, epoch=1, agent_kind="claude")
            ctx.store.change_registration(slug, lambda _c: {
                "name": f"pm-{slug}", "project": "proj", "repo": str(repo), "pane": "hc:t7",
                "terminal": "t7", "runtime": "hc", "seat": True, "agent": "claude", "epoch": 1, "endpoint": ep.to_dict(),
            })
            ctx.seat_alive = lambda _r, _rec, _t=None: False
            dlv = Deliverer(ctx, repo, watchers=(), holds=(), settle=0)
            env = Envelope(
                env_id="env_u7s", idempotency_key="chat.user:u7s", schema_version=1,
                created_ms=int(clock.time() * 1000), kind="chat.user",
                sender=Principal.user(), recipient=LogicalAddress.pm(slug), project=slug,
                cause={"kind": "user", "msg_id": "u7s"}, priority=P1_USER,
                body={"text": "Status?", "msg_id": "u7s"}, require_reply=True,
            )
            dlv._supervisor.tracker.ensure_mailbox_migrated()
            dlv._supervisor.tracker.pm_mailbox.enqueue(env, initial_state="accepted", now_ms=int(clock.time() * 1000))
            due = dlv.look(FakeChangeWaiter(), {}, {})
            self.assertIsNotNone(due)
            rot_spawns = [s["args"] for s in ctx.procs.spawned if s["args"][:1] == ["rotate"]]
            self.assertEqual(len(rot_spawns), 1)
            self.assertIn("--force", rot_spawns[0])

        # 4b: W7a `read_pm_turn_view` checks command line before killing reused beat PID.
        with tempfile.TemporaryDirectory() as tmp2:
            h2 = FakePmAgentHarness(Path(tmp2))
            tracker = TurnTracker(h2.ctx, h2.repo)
            h2.procs.pid_commands[54321] = "/usr/bin/vim /tmp/notes.md"
            touch_heartbeat(tracker.files.pm_turn_beat, h2.clock.time(), pid=54321)
            h2.clock.advance(75.0)
            with mock.patch.object(Delivery, "is_running", side_effect=[True, False]):
                read_pm_turn_view(h2.ctx, h2.repo, h2.reg, term_info=h2.hc.get_raw("t7"), revive=True)
            self.assertNotIn(54321, h2.procs.terminated_pids)
            self.assertEqual(h2.procs.terminated_calls[-1]["pid"], 54321)
            self.assertIn("deliver", h2.procs.terminated_calls[-1]["expected_substrings"])

    def test_supervisor_hook_preserves_original_cause_before_async_send_settles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = FakePmAgentHarness(Path(tmp))
            h.send_user_message("Check failing CI", msg_id="u5a")
            tracker = h.supervisor.tracker
            tracker.ensure_mailbox_migrated()
            sup_env_id = new_env_id(h.now_ms())
            sup_env = Envelope(
                env_id=sup_env_id, idempotency_key="resume:race1", schema_version=1,
                created_ms=h.now_ms(), kind="cmd.resume_turn",
                sender=Principal.supervisor(h.slug), recipient=LogicalAddress.pm(h.slug),
                project=h.slug,
                cause={"kind": "recovery", "original_cause": "user", "msg_ids": ["u5a"]},
                priority=1,
                body={
                    "text": f"[from pm.py supervisor #{sup_env_id}] Continue...",
                    "original_cause": "user",
                    "msg_ids": ["u5a"],
                },
                require_reply=True,
            )
            # Envelope stays in `accepted` (simulating UserPromptSubmit hook arriving before async send settles!).
            tracker.pm_mailbox.enqueue(
                sup_env, initial_state="accepted", now_ms=h.now_ms(),
                target_endpoint_uid=h.ep.uid, endpoint_epoch=1,
            )
            hook_ctx = make_ctx(
                h.root / "ledger", pane="hc:t7", hc=h.hc, clock=h.clock, procs=h.procs,
            )
            hook_ctx.caller = Caller(hook_ctx)
            stdin_payload = json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "session_id": "sess-1",
                "cwd": str(h.repo),
                "prompt": f"[from pm.py supervisor #{sup_env_id}] Continue...",
            })
            with mock.patch.object(sys, "stdin", io.StringIO(stdin_payload)), contextlib.redirect_stdout(io.StringIO()):
                hooks.cmd_hook_turn(None, ctx=hook_ctx)

            consumed_item = tracker.pm_mailbox.get(sup_env_id)
            assert consumed_item is not None
            self.assertEqual(consumed_item.state, "consumed")
            snap = tracker.read()
            self.assertEqual(snap["cause"], "user")
            self.assertEqual((tracker.sync_journal(tick_now=False)[0]["turn"]["cause"] or {}).get("msg_ids"), ["u5a"])

    def test_g5_vs_w2_batch_backoff_and_healthy_new_turn_not_clobbered(self) -> None:
        # 1. Batch turn errors and terminal returns to `idle`: G5 requeues batch to `accepted`,
        #    Router holds it during W2's 20s & 90s backoffs, and retries carry #2 / #3 until resolved!
        with tempfile.TemporaryDirectory() as tmp1:
            repo = Path(tmp1) / "proj"
            repo.mkdir()
            clock = FakeClock("2026-11-26 13:00:00")
            hc = FakeHc(
                terminals={
                    "t7": {
                        "address": "t7", "state": "live", "status": {"state": "idle", "ms": int(clock.time() * 1000)},
                        "turn": 1, "foreground": {"pid": 4300, "argv": ["claude"]},
                        "labels": {"pm": "proj", "pm.seat": "1"},
                    },
                },
                clock=clock,
            )
            ctx = make_ctx(Path(tmp1) / "ledger", hc=hc, clock=clock, config={"lang": "en"})
            slug = project_slug(repo)
            ep = Endpoint(runtime="hc", machine=None, terminal="t7", fg_pid=4300, epoch=1, agent_kind="claude")
            ctx.store.change_registration(slug, lambda _c: {
                "name": f"pm-{slug}", "project": "proj", "repo": str(repo), "pane": "hc:t7",
                "terminal": "t7", "runtime": "hc", "agent": "claude", "epoch": 1, "endpoint": ep.to_dict(),
            })
            Conversation(ctx, repo).record("thread", task="proj-t1", title="t1", status="review", by="hc:t20", text="status=review", wake=True)
            dlv = Deliverer(ctx, repo, watchers=(), holds=(), settle=0)
            changes = FakeChangeWaiter()

            # Initial delivery #1
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 1)
            hook_ctx = make_ctx(Path(tmp1) / "ledger", pane="hc:t7", hc=hc, clock=clock, config={"lang": "en"})
            hook_ctx.caller = Caller(hook_ctx)
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({
                "hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": str(repo), "prompt": hc.sent[-1][1],
            }))), contextlib.redirect_stdout(io.StringIO()):
                hooks.cmd_hook_turn(None, ctx=hook_ctx)

            # Turn 1 errors and immediately goes back to `idle`!
            clock.advance(1.0)
            hc.set_status("t7", "working")
            dlv.look(changes, {}, {})
            clock.advance(1.0)
            dlv._supervisor.tracker.append_observation({"src": "claude", "kind": "step_error", "t": int(clock.time() * 1000), "message": "500 upstream error"}, reduce_now=True)
            hc.set_status("t7", "idle")
            dlv.look(changes, {}, {})  # closes Turn 1 as `errored` -> opens W2 + G5 puts batch back in `accepted`

            # At +1s and +10s (before 20s W2 timer): batch MUST stay held (`recovery_backoff`), NOT 0s-retyped!
            clock.advance(1.0)
            dlv.look(changes, {}, {})
            clock.advance(10.0)
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 1, "G5 must not re-deliver batch at 0s while W2 20s backoff is active")

            # At +21s: W2 stage 0 fires `continue_turn` -> releases batch retry #2!
            clock.advance(10.0)
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 2)
            self.assertIn("retry #2", hc.sent[-1][1])
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({
                "hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": str(repo), "prompt": hc.sent[-1][1],
            }))), contextlib.redirect_stdout(io.StringIO()):
                hooks.cmd_hook_turn(None, ctx=hook_ctx)

            # Retry #2 also errors and returns to `idle`: held for 90s, then retry #3 fires!
            clock.advance(1.0)
            hc.set_status("t7", "working")
            dlv.look(changes, {}, {})
            clock.advance(1.0)
            dlv._supervisor.tracker.append_observation({"src": "claude", "kind": "step_error", "t": int(clock.time() * 1000), "message": "500 again"}, reduce_now=True)
            hc.set_status("t7", "idle")
            dlv.look(changes, {}, {})
            clock.advance(30.0)
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 2, "must hold during 90s W2 stage-1 backoff")
            clock.advance(62.0)
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 3, "W2 stage-1 must still deliver attempt #3 (not exhausted early)")
            self.assertIn("retry #3", hc.sent[-1][1])

        # 2. If a healthy new turn starts while W2 is open (e.g. user follow-up at +5s), W2 at +20s MUST NOT
        #    clobber the healthy active turn to `recovering` or yank a `consumed` batch!
        with tempfile.TemporaryDirectory() as tmp2:
            h = FakePmAgentHarness(Path(tmp2))
            b_env = Envelope(
                env_id="env_b_healthy", idempotency_key="batch:proj:0-50", schema_version=1,
                created_ms=h.now_ms(), kind="event.batch",
                sender=Principal.supervisor(h.slug), recipient=LogicalAddress.pm(h.slug),
                project=h.slug, cause={"kind": "deliver_batch", "start": 0, "end": 50},
                priority=P4_BATCH, body={"text": "[from pm.py deliver] 1 event(s) (0-50) #env_b_healthy\n1. ok", "start": 0, "end": 50},
                require_reply=True,
            )
            h.supervisor.tracker.ensure_mailbox_migrated()
            h.supervisor.tracker.pm_mailbox.enqueue(b_env, initial_state="accepted", now_ms=h.now_ms(), target_endpoint_uid=h.ep.uid, endpoint_epoch=1)
            h.pump_delivery()
            h.set_terminal(agent_status="error", turn=2)
            h.tick_supervisor(1.0)  # opens W2 (`cause_kind="deliver"`, due in 20s)

            # At +5s, a healthy new turn starts and consumes the batch!
            h.clock.advance(5.0)
            h.set_terminal(agent_status="idle")
            h.supervisor.tracker.pm_mailbox.transition("env_b_healthy", "typed", now_ms=h.now_ms(), endpoint_epoch=1)
            h.run_prompt_hook("[from pm.py deliver] 1 event(s) (0-50) #env_b_healthy\n1. ok")
            h.set_terminal(agent_status="working", screen="Healthy turn working frame 1")
            h.tick_supervisor(1.0, screen="Healthy turn working frame 1")
            self.assertEqual(h.supervisor.tracker.pm_mailbox.get("env_b_healthy").state, "consumed")

            # Advance past +20s while healthy turn is actively generating: must stay `generating` and `consumed`!
            st_mid, _ = h.tick_supervisor(20.0, screen="Healthy turn working frame 2")
            self.assertEqual(st_mid["turn"]["phase"], "generating")
            self.assertEqual(h.supervisor.tracker.pm_mailbox.get("env_b_healthy").state, "consumed")

            # Healthy turn replies -> W2 resolves cleanly and batch settles to `answered`!
            h.supervisor.tracker.append_observation({"src": "claude", "kind": "step_reply", "t": h.now_ms()}, reduce_now=True)
            h.supervisor.tracker.append_observation({"src": "hook", "kind": "hook_stop", "t": h.now_ms(), "has_reply": True}, reduce_now=True)
            st_done, _ = h.tick_supervisor(1.0)
            self.assertEqual(st_done["incident"]["status"], "resolved")
            self.assertEqual(h.supervisor.tracker.pm_mailbox.get("env_b_healthy").state, "answered")

    def test_started_false_provisional_submitted_does_not_loop_w6_or_deadlock_w2(self) -> None:
        # 1. W6 when `retype_submitted` ALSO returns `started=False`: must NOT resolve as `turn_started`
        #    or loop `retype_submitted`; must advance to `notify_user` and stop!
        with tempfile.TemporaryDirectory() as tmp1:
            h = FakePmAgentHarness(Path(tmp1))
            env_id = h.send_user_message("Unstarted forever", msg_id="u_w6_loop")
            h.transport.configure(
                h.ep,
                next_deliver=[
                    DeliverOutcome(status="typed", started_turn=False, observed_turn=1, detail="unstarted_1"),
                    DeliverOutcome(status="typed", started_turn=False, observed_turn=1, detail="unstarted_2"),
                ],
            )
            h.pump_delivery()
            h.set_terminal(agent_status="idle", screen="> ", has_draft=False)
            # Advance through W6: 20s stall -> classify_screen -> nudge_enter (5s) -> retype_submitted
            for _ in range(8):
                h.tick_supervisor(5.0, screen="> ")
                it = h.supervisor.tracker.pm_mailbox.get(env_id)
                if it and it.state == "accepted":
                    break
            self.assertEqual(h.supervisor.tracker.pm_mailbox.get(env_id).state, "accepted")

            # Retype ALSO returns `started=False`: W6 must remain recovering (`awaiting_verify="retype_submitted"`), NOT resolved!
            out2 = h.pump_delivery()
            self.assertIs(out2.started_turn, False)
            st_after_retype = h.supervisor.tracker.read()
            self.assertNotEqual((st_after_retype.get("incident") or {}).get("status"), "resolved")
            self.assertEqual((st_after_retype.get("incident") or {}).get("awaiting_verify"), "retype_submitted")

            # After `verify_continue_ms` (15s), W6 advances to `notify_user` and stays `notified` across further ticks!
            st_notified, _ = h.tick_supervisor(16.0, screen="> ")
            self.assertEqual(st_notified["incident"]["class"], "W6")
            self.assertEqual(st_notified["incident"]["status"], "notified")
            st_later, _ = h.tick_supervisor(30.0, screen="> ")
            self.assertEqual(st_later["incident"]["status"], "notified")
            self.assertEqual(h.supervisor.tracker.pm_mailbox.get(env_id).attempts, 2)

        # 2. W2 on a terminal wedged in `status="error"` where `FakeHc.send` returns `started=False`:
        #    must NOT zero `verify_deadline_ms`, must NOT overwrite W2 with W6, and must escalate all the way to `switch_profile --force`!
        with tempfile.TemporaryDirectory() as tmp2:
            repo2 = Path(tmp2) / "proj"
            repo2.mkdir()
            clock2 = FakeClock("2026-11-26 13:20:00")
            hc2 = FakeHc(
                terminals={
                    "t7": {
                        "address": "t7", "state": "live", "status": {"state": "working", "ms": int(clock2.time() * 1000)},
                        "turn": 1, "foreground": {"pid": 4400, "argv": ["claude"]},
                        "labels": {"pm": "proj", "pm.seat": "1"},
                    },
                },
                clock=clock2,
            )
            cfg2 = {"lang": "en", "pm": {"recovery": {"auto": "full", "fallback_profiles": ["backup-prof"]}}}
            ctx2 = make_ctx(Path(tmp2) / "ledger", hc=hc2, clock=clock2, config=cfg2)
            slug2 = project_slug(repo2)
            ep2 = Endpoint(runtime="hc", machine=None, terminal="t7", fg_pid=4400, epoch=1, agent_kind="claude")
            ctx2.store.change_registration(slug2, lambda _c: {
                "name": f"pm-{slug2}", "project": "proj", "repo": str(repo2), "pane": "hc:t7",
                "terminal": "t7", "runtime": "hc", "seat": True, "agent": "claude", "epoch": 1, "endpoint": ep2.to_dict(),
            })
            dlv2 = Deliverer(ctx2, repo2, watchers=(), holds=(), settle=0)
            changes2 = FakeChangeWaiter()
            Conversation(ctx2, repo2).record("user", msg_id="u_err_wedge", text="Check prod")
            dlv2._supervisor.tracker.begin_turn(terminal="t7", agent_kind="claude", cause="user", msg_ids=["u_err_wedge"], from_hook=True)
            dlv2.look(changes2, {}, {})

            # Terminal crashes to `status="error"` and stays wedged in `error` (`FakeHc.send` returns `started=False`!).
            clock2.advance(2.0)
            hc2.set_status("t7", "error")
            dlv2.look(changes2, {}, {})  # opens W2 stage 0

            # +21s: stage 0 `continue_turn` types `cmd.resume_turn` #1 -> `started=False` (`submitted`)
            clock2.advance(21.0)
            dlv2.look(changes2, {}, {})
            st_r1 = dlv2._supervisor.tracker.read()
            self.assertEqual(st_r1["incident"]["class"], "W2")
            self.assertEqual(st_r1["incident"]["awaiting_verify"], "continue_turn")
            self.assertGreater(st_r1["incident"]["verify_deadline_ms"], 0)

            # +16s: `verify_continue_ms` expires -> advances W2 to stage 1 (90s backoff), NOT overwritten by W6!
            clock2.advance(16.0)
            dlv2.look(changes2, {}, {})
            st_s1 = dlv2._supervisor.tracker.read()
            self.assertEqual(st_s1["incident"]["class"], "W2")
            self.assertEqual(st_s1["incident"]["stage"], 1)

            # +91s: stage 1 `continue_turn` types `cmd.resume_turn` #2 -> `started=False` -> +16s expires -> stage 2 `switch_profile --force`!
            clock2.advance(91.0)
            dlv2.look(changes2, {}, {})
            clock2.advance(16.0)
            dlv2.look(changes2, {}, {})
            rot_spawns = [s["args"] for s in ctx2.procs.spawned if s["args"][:1] == ["rotate"]]
            self.assertEqual(len(rot_spawns), 1, ctx2.procs.spawned)
            self.assertIn("--profile", rot_spawns[0])
            self.assertIn("backup-prof", rot_spawns[0])
            self.assertIn("--force", rot_spawns[0])

    def test_w7_idle_exit_before_message_and_exit_during_w2_backoff(self) -> None:
        # 1. Idle PM exits FIRST (caching `_last_hc_sig` with `has_unanswered=False`), THEN user sends a message -> W7 triggers!
        with tempfile.TemporaryDirectory() as tmp1:
            h = FakePmAgentHarness(Path(tmp1))
            h.set_terminal(state="exited")
            st_idle_off, _ = h.tick_supervisor(1.0)
            self.assertIsNone(st_idle_off.get("incident"))
            self.assertEqual(h.rotations, [])

            # Now user message arrives while terminal is still `exited`: next supervisor pass must open W7 & force-rotate!
            h.send_user_message("Wake up!", msg_id="u_after_exit")
            st_w7, _ = h.tick_supervisor(1.0)
            self.assertEqual((st_w7.get("incident") or {}).get("class"), "W7")
            self.assertEqual(len(h.rotations), 1)
            self.assertIs(h.rotations[0]["force"], True)

        # 2. Turn errors -> enters W2 20s wait (`chat.user` already settled in mailbox) -> coordinator exits at +5s -> transitions to W7!
        with tempfile.TemporaryDirectory() as tmp2:
            h2 = FakePmAgentHarness(Path(tmp2))
            h2.send_user_message("Fix deploy", msg_id="u_w2_exit")
            h2.pump_delivery()
            h2.set_terminal(agent_status="error", turn=2)
            st_w2, _ = h2.tick_supervisor(1.0)
            self.assertEqual(st_w2["incident"]["class"], "W2")
            self.assertEqual(h2.supervisor.tracker.pm_mailbox.unanswered_user_items(), [])

            # Coordinator crashes during W2's 20s backoff -> immediately escalates to W7 `restart_seat --force`!
            h2.set_terminal(state="exited")
            st_w7b, _ = h2.tick_supervisor(5.0)
            self.assertEqual(st_w7b["incident"]["class"], "W7")
            self.assertEqual(len(h2.rotations), 1)
            self.assertIn("recovery W7", str(h2.rotations[0]["reason"]))
            self.assertIs(h2.rotations[0]["force"], True)

    def test_failed_interrupt_and_notify_refresh_phase_since_ms_on_recovering_exit(self) -> None:
        st = tr.default_state_v2()
        st["turn"]["id"] = "t1"
        st["turn"]["seq"] = 1
        st["turn"]["phase"] = "recovering"
        st["turn"]["phase_since_ms"] = 1_000
        st["incident"] = {
            "id": "inc:1:W2:1000",
            "key": "t1:W2",
            "class": "W2",
            "turn_id": "t1",
            "turn_seq": 1,
            "cause_kind": "user",
            "stage": 0,
            "step_name": "interrupt_turn",
            "status": "recovering",
            "reason": "stalled",
            "awaiting_action": "interrupt_turn",
            "awaiting_verify": "",
            "actions": [],
        }
        nxt1 = tr.reduce(st, {
            "kind": "recovery_result",
            "t": 25_000,
            "incident_id": "inc:1:W2:1000",
            "class": "W2",
            "stage": 0,
            "action": "interrupt_turn",
            "outcome": "still_working",
        })
        self.assertEqual(nxt1["turn"]["phase"], "generating")
        self.assertEqual(nxt1["turn"]["phase_since_ms"], 25_000)

        st2 = tr.default_state_v2()
        st2["turn"]["id"] = "t2"
        st2["turn"]["seq"] = 2
        st2["turn"]["phase"] = "recovering"
        st2["turn"]["phase_since_ms"] = 2_000
        st2["incident"] = {
            "id": "inc:2:W5:2000",
            "key": "t2:W5",
            "class": "W5",
            "turn_id": "t2",
            "turn_seq": 2,
            "cause_kind": "user",
            "stage": 4,
            "step_name": "notify_user",
            "status": "recovering",
            "reason": "pty_frozen",
            "awaiting_action": "notify_user",
            "awaiting_verify": "",
            "actions": [],
        }
        nxt2 = tr.reduce(st2, {
            "kind": "recovery_result",
            "t": 55_000,
            "incident_id": "inc:2:W5:2000",
            "class": "W5",
            "stage": 4,
            "action": "notify_user",
            "outcome": "notified",
        })
        self.assertEqual(nxt2["turn"]["phase"], "generating")
        self.assertEqual(nxt2["turn"]["phase_since_ms"], 55_000)

    def test_w6_retype_submitted_deliver_batch_retypes_agy_and_resolves_incident(self) -> None:
        # Reproduce 2026-11-28 01:22 real incident: `event.batch` typed to agy returns `started=False`,
        # terminal stays idle (`>`), W6 stage 2 `retype_submitted` requeues the batch, and `Deliverer.look()`
        # must actually re-type `[retry #2]` into the terminal and resolve W6 without escalating to `notify_user`.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "proj"
            repo.mkdir()
            clock = FakeClock("2026-11-28 01:22:20")
            status_obj = {"state": "idle", "ms": int(clock.time() * 1000)}

            class _RetypeFakeHc(FakeHc):
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    super().__init__(*args, **kwargs)
                    self.send_calls = 0

                def send(self, term: str, text: str, *, if_state: str | None = None, timeout: float = 180, errors: bool = False) -> dict[str, Any] | None:
                    self.send_calls += 1
                    if self.send_calls == 1:
                        self.terminals["t1k6"]["send_started"] = False
                        return super().send(term, text, if_state=if_state, timeout=timeout, errors=errors)
                    self.terminals["t1k6"]["send_started"] = True
                    res = super().send(term, text, if_state=if_state, timeout=timeout, errors=errors)
                    self.set_status("t1k6", "working")
                    return res

            hc = _RetypeFakeHc(
                terminals={
                    "t1k6": {
                        "address": "t1k6", "state": "live",
                        "status": status_obj, "reported": True,
                        "turn": 189, "foreground": {"pid": 88489, "argv": ["agy"]},
                        "labels": {"pm": "proj", "pm.seat": "1"},
                        "screen": "done\n> \n? for shortcuts",
                    },
                },
                clock=clock,
            )
            ctx = make_ctx(Path(tmp) / "ledger", hc=hc, clock=clock, config={"lang": "en"})
            slug = project_slug(repo)
            ep = Endpoint(runtime="hc", machine=None, terminal="t1k6", fg_pid=88489, epoch=2, agent_kind="agy")
            ctx.store.change_registration(slug, lambda _c: {
                "name": f"pm-{slug}", "project": "proj", "repo": str(repo), "pane": "hc:t1k6",
                "terminal": "t1k6", "runtime": "hc", "seat": True, "agent": "agy", "epoch": 2,
                "endpoint": ep.to_dict(),
            })
            dlv = Deliverer(ctx, repo, watchers=(), holds=(), settle=0, unknown_wait=0)
            changes = FakeChangeWaiter()

            # Prime idle baseline, then append a waking worker report.
            dlv.look(changes, {}, {})
            clock.advance(5.0)
            Conversation(ctx, repo).record(
                "thread", task="dudu-pm-6b-worker", title="Phase 6b", status="done",
                by="hc:t1qp", text="status=done; landed", number=339, source="worker", wake=True,
            )
            # Initial delivery: sends once (`started=False`), must NOT emit duplicate `started=True` send_submitted.
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 1)
            journal_1 = [
                json.loads(line)
                for line in dlv._supervisor.tracker.files.pm_turn_journal.read_text().splitlines()
                if line.strip()
            ]
            submits_1 = [e for e in journal_1 if e.get("kind") == "send_submitted"]
            self.assertEqual(len(submits_1), 1, f"expected single truthful send_submitted, got {submits_1}")
            self.assertIs(submits_1[0].get("started"), False)
            self.assertEqual(dlv._supervisor.tracker.read()["turn"]["phase"], "submitted")

            # +20s -> W6 opens + stage 0 classify_screen (no_dialog)
            clock.advance(20.5)
            dlv.look(changes, {}, {})
            # +1s -> stage 1 nudge_enter
            clock.advance(1.0)
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 1, "must not retype during nudge_enter")

            # +5.5s -> stage 2 retype_submitted requeues AND immediately re-types `[retry #2]` in the same look!
            clock.advance(5.5)
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 2, f"retype_submitted must re-send batch; sent={hc.sent}")
            self.assertIn("[retry #2]", hc.sent[1][1])

            # Next look: W6 resolved as `turn_started`, never escalated to `notify_user`!
            clock.advance(1.0)
            dlv.look(changes, {}, {})
            st_end = dlv._supervisor.tracker.read()
            inc_end = st_end.get("incident") or {}
            self.assertEqual(inc_end.get("status"), "resolved", st_end)
            self.assertEqual(inc_end.get("resolution"), "turn_started", st_end)
            self.assertNotEqual(inc_end.get("step_name"), "notify_user")
            batch_items = [it for it in dlv._supervisor.tracker.pm_mailbox.active_items(("accepted", "typed", "consumed")) if it.envelope.kind == "event.batch"]
            self.assertEqual(len(batch_items), 1)
            self.assertEqual(batch_items[0].attempts, 2)

        # Tier-2 (no-status terminal, reported=False) variant via FakeTransport:
        # `retype_submitted` must also re-deliver `event.batch` without blocking on `pm_working`/`blackbox_cooldown`.
        with tempfile.TemporaryDirectory() as tmp2:
            repo2 = Path(tmp2) / "proj2"
            repo2.mkdir()
            clock2 = FakeClock("2026-11-28 01:30:00")
            hc2 = FakeHc(
                terminals={
                    "t2": {
                        "address": "t2", "state": "live", "status": None, "reported": False,
                        "turn": 1, "foreground": {"pid": 5500, "argv": ["codex"]},
                        "labels": {"pm": "proj2", "pm.seat": "1"},
                        "screen": "> ",
                    },
                },
                clock=clock2,
            )
            ctx2 = make_ctx(Path(tmp2) / "ledger", hc=hc2, clock=clock2, config={"lang": "en"})
            slug2 = project_slug(repo2)
            ep2 = Endpoint(runtime="hc", machine=None, terminal="t2", fg_pid=5500, epoch=1, agent_kind="codex")
            ctx2.store.change_registration(slug2, lambda _c: {
                "name": f"pm-{slug2}", "project": "proj2", "repo": str(repo2), "pane": "hc:t2",
                "terminal": "t2", "runtime": "hc", "seat": True, "agent": "codex", "epoch": 1,
                "endpoint": ep2.to_dict(),
            })
            dlv2 = Deliverer(ctx2, repo2, watchers=(), holds=(), settle=0, unknown_wait=0)
            tr2 = FakeTransport(clock=clock2)
            tr2.configure(
                ep2,
                next_deliver=[
                    DeliverOutcome(status="typed", started_turn=False, observed_turn=1, detail="unstarted_t2"),
                    DeliverOutcome(status="typed", started_turn=True, observed_turn=2, detail="started_t2"),
                ],
            )
            dlv2._driver._transport = tr2
            dlv2._supervisor._transport = tr2
            # Establish a prior completed turn (Tier 2: `last_turn_stopped=True`).
            dlv2._supervisor.tracker.begin_turn(terminal="t2", agent_kind="codex", cause="user", from_hook=True)
            dlv2._supervisor.tracker.end_turn(has_reply=True)
            changes2 = FakeChangeWaiter()
            Conversation(ctx2, repo2).record(
                "thread", task="t-tier2", title="Tier2 task", status="done",
                by="hc:tw", text="status=done; ok", number=10, source="worker", wake=True,
            )
            dlv2.look(changes2, {}, {})
            b_items2 = [it for it in dlv2._supervisor.tracker.pm_mailbox.active_items(("accepted", "typed")) if it.envelope.kind == "event.batch"]
            self.assertEqual(len(b_items2), 1)
            self.assertEqual(b_items2[0].state, "typed")
            self.assertEqual(b_items2[0].attempts, 1)
            clock2.advance(20.5)
            dlv2.look(changes2, {}, {})  # classify_screen
            clock2.advance(1.0)
            dlv2.look(changes2, {}, {})  # nudge_enter
            clock2.advance(5.5)
            dlv2.look(changes2, {}, {})  # retype_submitted -> must deliver immediately on Tier 2!
            b_after = dlv2._supervisor.tracker.pm_mailbox.get(b_items2[0].envelope.env_id)
            self.assertIsNotNone(b_after)
            self.assertEqual(b_after.state, "typed")
            self.assertEqual(b_after.attempts, 2, f"Tier 2 retype_submitted must re-deliver; item={b_after}")
            st2_end = dlv2._supervisor.tracker.read()
            self.assertEqual((st2_end.get("incident") or {}).get("status"), "resolved")
            self.assertEqual((st2_end.get("incident") or {}).get("resolution"), "turn_started")

    def test_w6_retype_and_retry_dedup_skips_answered_received_and_superseded_batches(self) -> None:
        """P2 retry dedup:
        1) W6 `retype_submitted` skips and supersedes an `event.batch` whose stretch was already answered/received,
           resolving the W6 incident cleanly instead of re-waking the PM or escalating to `notify_user`;
        2) Stale `event.batch` containing a review verdict (`<tid>-review: done`) is superseded before typing when
           the PM has already acted on the parent task (e.g. `approve` -> `in_progress`);
        3) Partial batch with one still-unhandled review verdict is NOT dropped."""
        # Case 1: W6 `retype_submitted` when PM already answered the batch -> superseded, zero re-send!
        with tempfile.TemporaryDirectory() as tmp1:
            repo = Path(tmp1) / "proj1"
            repo.mkdir()
            clock = FakeClock("2026-11-28 02:00:00")
            hc = FakeHc(
                terminals={
                    "t1": {
                        "address": "t1", "state": "live", "status": {"state": "idle"}, "turn": 1,
                        "foreground": {"pid": 6100, "argv": ["agy"]},
                        "labels": {"pm": "proj1", "pm.seat": "1"},
                        "screen": "> ",
                        "send_started": False,
                    },
                },
                clock=clock,
            )
            ctx = make_ctx(Path(tmp1) / "ledger", hc=hc, clock=clock, config={"lang": "en"})
            slug = project_slug(repo)
            ep = Endpoint(runtime="hc", machine=None, terminal="t1", fg_pid=6100, epoch=1, agent_kind="agy")
            ctx.store.change_registration(slug, lambda _c: {
                "name": f"pm-{slug}", "project": "proj1", "repo": str(repo), "pane": "hc:t1",
                "terminal": "t1", "runtime": "hc", "seat": True, "agent": "agy", "epoch": 1,
                "endpoint": ep.to_dict(),
            })
            dlv = Deliverer(ctx, repo, watchers=(), holds=(), settle=0, unknown_wait=0)
            changes = FakeChangeWaiter()
            Conversation(ctx, repo).record(
                "thread", task="p1-a", title="Task A", status="done",
                by="hc:tw", text="status=done; finished", number=1, source="worker", wake=True,
            )
            dlv.look(changes, {}, {})
            self.assertEqual(len(hc.sent), 1)
            b_item = next(it for it in dlv._supervisor.tracker.pm_mailbox.active_items(("typed",)) if it.envelope.kind == "event.batch")
            b_start, b_end = b_item.envelope.body["start"], b_item.envelope.body["end"]

            # Simulate PM having already answered this batch stretch in conversation.jsonl before W6 reaches retype_submitted.
            Conversation(ctx, repo).record(
                "pm", by="hc:t1", text="Task A merged.", after="deliver", batch=[b_start, b_end],
            )
            clock.advance(20.5)
            dlv.look(changes, {}, {})  # classify_screen
            clock.advance(1.0)
            dlv.look(changes, {}, {})  # nudge_enter
            clock.advance(5.5)
            dlv.look(changes, {}, {})  # retype_submitted -> must supersede, NOT re-send!
            self.assertEqual(len(hc.sent), 1, f"already-answered batch must not be re-typed; sent={hc.sent}")
            item_after = dlv._supervisor.tracker.pm_mailbox.get(b_item.envelope.env_id)
            self.assertEqual(item_after.state, "superseded")
            self.assertEqual(item_after.hold_reason, "already_answered")
            inc = dlv._supervisor.tracker.read().get("incident") or {}
            self.assertEqual(inc.get("status"), "resolved")
            self.assertEqual(inc.get("resolution"), "superseded")

        # Case 2 & 3: Stale review-verdict batch superseded once PM approves/handles parent, while partial batch stays live.
        with tempfile.TemporaryDirectory() as tmp2:
            repo2 = Path(tmp2) / "proj2"
            repo2.mkdir()
            clock2 = FakeClock("2026-11-28 02:10:00")
            hc2 = FakeHc(
                terminals={
                    "t2": {
                        "address": "t2", "state": "live", "status": {"state": "idle"}, "turn": 2,
                        "foreground": {"pid": 6200, "argv": ["agy"]},
                        "labels": {"pm": "proj2", "pm.seat": "1"},
                    },
                },
                clock=clock2,
            )
            ctx2 = make_ctx(Path(tmp2) / "ledger", hc=hc2, clock=clock2, config={"lang": "en"})
            slug2 = project_slug(repo2)
            ep2 = Endpoint(runtime="hc", machine=None, terminal="t2", fg_pid=6200, epoch=2, agent_kind="agy")
            ctx2.store.change_registration(slug2, lambda _c: {
                "name": f"pm-{slug2}", "project": "proj2", "repo": str(repo2), "pane": "hc:t2",
                "terminal": "t2", "runtime": "hc", "seat": True, "agent": "agy", "epoch": 2,
                "endpoint": ep2.to_dict(),
            })
            ctx2.home.tasks.mkdir(parents=True, exist_ok=True)
            for tid, rev_of, st in (
                ("p2-a", None, "in_progress"),
                ("p2-a-review", "p2-a", "done"),
                ("p2-b", None, "review"),
                ("p2-b-review", "p2-b", "done"),
            ):
                t_obj = {"id": tid, "title": tid, "project": "proj2", "repo": str(repo2), "status": st}
                if rev_of:
                    t_obj["review_of"] = rev_of
                ctx2.home.task(tid).write_text(json.dumps(t_obj), encoding="utf-8")

            conv2 = Conversation(ctx2, repo2)
            conv2.record(
                "thread", task="p2-a-review", review_of="p2-a", title="p2-a-review", status="done",
                by="hc:tr1", text="status=done; no blockers", source="worker", wake=True,
            )
            end_a = (ctx2.home.project_for(repo2).conversation).stat().st_size
            # PM already acted on parent p2-a (e.g. `pm.py approve p2-a` -> status=in_progress) after rotation/takeover!
            conv2.record(
                "thread", task="p2-a", title="p2-a", status="in_progress",
                by="hc:t2", text="PM approved merge", source="pm",
            )

            dlv2 = Deliverer(ctx2, repo2, watchers=(), holds=(), settle=0)
            mb2 = dlv2._supervisor.tracker.pm_mailbox
            stale_env = Envelope(
                env_id="env_01a2208260c6_55e4abef",
                idempotency_key=f"batch:{slug2}:0-{end_a}",
                schema_version=1,
                created_ms=1000,
                kind="event.batch",
                sender=Principal.supervisor(slug2),
                recipient=LogicalAddress.pm(slug2),
                project=slug2,
                cause={"kind": "deliver_batch", "start": 0, "end": end_a},
                priority=P4_BATCH,
                body={"text": f"[from pm.py deliver] 1 event(s) (0-{end_a}) #env_01a2208260c6_55e4abef", "start": 0, "end": end_a},
                require_reply=True,
            )
            mb2.enqueue(stale_env, initial_state="accepted", now_ms=1000, target_endpoint_uid=ep2.uid, endpoint_epoch=2)
            mb2.transition(stale_env.env_id, "accepted", now_ms=1100, attempts=1, hold_reason="retry_unstarted")

            dlv2.look(FakeChangeWaiter(), {}, {})
            self.assertEqual(hc2.sent, [], "stale review-verdict retry after PM approved parent must be dropped")
            self.assertEqual(mb2.get(stale_env.env_id).state, "superseded")
            self.assertEqual(mb2.get(stale_env.env_id).hold_reason, "events_superseded")

            # Case 3: batch with an unhandled review verdict (`p2-b-review`) still delivers normally!
            start_b = (ctx2.home.project_for(repo2).conversation).stat().st_size
            conv2.record(
                "thread", task="p2-b-review", review_of="p2-b", title="p2-b-review", status="done",
                by="hc:tr2", text="status=done; no blockers", source="worker", wake=True,
            )
            dlv2.look(FakeChangeWaiter(), {}, {})
            self.assertEqual(len(hc2.sent), 1)
            self.assertIn("p2-b-review", hc2.sent[0][1])


if __name__ == "__main__":
    unittest.main()
