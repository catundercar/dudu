"""Table-driven and property-based tests for `pmlib/project/turn_reducer.py` (Invariants I1-I5, T1-T4, §3.5, §4.8)."""
from __future__ import annotations

import os
from pathlib import Path
import random
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = "/nonexistent/pm-home-turn-reducer"
    try:
        from pmlib.project import turn_reducer as tr  # noqa: E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved
else:
    from pmlib.project import turn_reducer as tr  # noqa: E402


T0 = 1_795_600_000_000


class EndpointAndIdentityTests(unittest.TestCase):
    def test_parse_legacy_endpoint_variants_and_uids(self) -> None:
        self.assertIsNone(tr.parse_legacy_endpoint(""))
        self.assertIsNone(tr.parse_legacy_endpoint(None))

        ep_local = tr.parse_legacy_endpoint("hc:t12", agent_kind="agy", fg_pid=48291)
        assert ep_local is not None
        self.assertEqual(ep_local.runtime, "hc")
        self.assertIsNone(ep_local.machine)
        self.assertEqual(ep_local.terminal, "t12")
        self.assertEqual(ep_local.uid, "hc:local:t12")
        self.assertEqual(ep_local.hc_target, "t12")
        self.assertEqual(tr.format_turn_id(ep_local, 454), "hc:local:t12:48291:455")

        ep_remote_prefixed = tr.parse_legacy_endpoint("hc:gpu-box/t7", agent_kind="claude", fg_pid=19022)
        assert ep_remote_prefixed is not None
        self.assertEqual(ep_remote_prefixed.runtime, "hc")
        self.assertEqual(ep_remote_prefixed.machine, "gpu-box")
        self.assertEqual(ep_remote_prefixed.terminal, "t7")
        self.assertEqual(ep_remote_prefixed.uid, "hc:gpu-box:t7")
        self.assertEqual(ep_remote_prefixed.hc_target, "gpu-box/t7")
        self.assertEqual(tr.format_turn_id(ep_remote_prefixed, 11), "hc:gpu-box:t7:19022:12")

        ep_remote_bare = tr.parse_legacy_endpoint("gpu-box/t7")
        assert ep_remote_bare is not None
        self.assertEqual(ep_remote_bare.runtime, "hc")
        self.assertEqual(ep_remote_bare.machine, "gpu-box")
        self.assertEqual(ep_remote_bare.terminal, "t7")

        # TUI pane with slash ("sess/w1:p1") must NOT be misparsed as a remote machine!
        ep_tui = tr.parse_legacy_endpoint("main/w1:p2")
        assert ep_tui is not None
        self.assertEqual(ep_tui.runtime, "tui")
        self.assertIsNone(ep_tui.machine)
        self.assertEqual(ep_tui.workspace, "main")
        self.assertEqual(ep_tui.terminal, "w1:p2")
        self.assertEqual(ep_tui.hc_target, "")

        ep_sh = tr.parse_legacy_endpoint("sh:node-1/slot-0")
        assert ep_sh is not None
        self.assertEqual(ep_sh.runtime, "self_hosted")
        self.assertEqual(ep_sh.uid, "sh:node-1:slot-0")

    def test_record_endpoint_prefers_structured_endpoint_and_enriches_metadata(self) -> None:
        rec = {
            "pane": "hc:legacy",
            "runtime": "hc",
            "agent": "codex",
            "epoch": 2,
            "endpoint": {
                "runtime": "hc",
                "machine": "mac-mini",
                "terminal": "t9",
                "workspace": "ws_1",
                "fg_pid": 7711,
                "epoch": 2,
            },
        }
        ep = tr.record_endpoint(rec)
        assert ep is not None
        self.assertEqual(ep.uid, "hc:mac-mini:t9")
        self.assertEqual(ep.agent_kind, "codex")
        self.assertEqual(ep.fg_pid, 7711)
        self.assertEqual(ep.epoch, 2)


class ReducerTableTests(unittest.TestCase):
    def _state(self, *, terminal: str = "t12", agent_kind: str = "agy", fg_pid: int = 4200) -> dict:
        s = tr.default_state_v2()
        s["session"] = tr.Endpoint(
            runtime="hc", terminal=terminal, agent_kind=agent_kind, fg_pid=fg_pid, epoch=1,
        ).to_dict()
        return tr.sync_compat_fields(s)

    def test_t1_t2_t3_t4_anchor_rules(self) -> None:
        cfg = tr.TurnConfig()
        s = self._state()

        # T2: send_submitted opens `submitted`, then hc_state(working) + hook_prompt merge without double-counting seq.
        s = tr.reduce(s, {"seq": 1, "t": T0, "kind": "send_submitted", "cause": "user", "msg_ids": ["u-1"], "started": False}, cfg)
        self.assertEqual(s["turn"]["phase"], "submitted")
        self.assertEqual(s["turn"]["seq"], 1)

        s = tr.reduce(s, {"seq": 2, "t": T0 + 500, "kind": "hc_state", "state": "live", "status": "working", "status_ms": T0 + 500, "turn": 5, "reported": True}, cfg)
        self.assertEqual(s["turn"]["phase"], "generating")
        self.assertEqual(s["turn"]["seq"], 1)
        self.assertEqual(s["turn"]["id"], "hc:local:t12:4200:6")

        s = tr.reduce(s, {"seq": 3, "t": T0 + 2000, "kind": "hook_prompt", "cause": "user", "msg_ids": ["u-1"], "hc_turn": 5}, cfg)
        self.assertEqual(s["turn"]["seq"], 1)
        self.assertTrue(s["turn"]["hook_confirmed"])

        # T3 + FS-9: Turn 2 opens before Turn 1's late Stop -> late Stop(expected_seq=1) is dropped!
        s = tr.reduce(s, {"seq": 4, "t": T0 + 10_000, "kind": "hook_prompt", "cause": "deliver", "batch": [0, 50], "hc_turn": 6}, cfg)
        self.assertEqual(s["turn"]["seq"], 2)
        s = tr.reduce(s, {"seq": 5, "t": T0 + 10_500, "kind": "hook_stop", "expected_seq": 1, "has_reply": True}, cfg)
        self.assertEqual(s["turn"]["seq"], 2)
        self.assertEqual(s["turn"]["phase"], "generating")

        # T3: Turn 2 closes cleanly with reply.
        s = tr.reduce(s, {"seq": 6, "t": T0 + 15_000, "kind": "hook_stop", "expected_seq": 2, "has_reply": True}, cfg)
        self.assertEqual(s["turn"]["phase"], "idle")
        self.assertEqual(s["last_turn"]["outcome"], "replied")

        # T1: Direct terminal working after 600s idle re-anchors started_ms to status_ms (never uses old turn!).
        s = tr.reduce(s, {"seq": 7, "t": T0 + 615_000, "kind": "hc_state", "state": "live", "status": "working", "status_ms": T0 + 615_000, "turn": 7, "reported": True}, cfg)
        self.assertEqual(s["turn"]["phase"], "generating")
        self.assertEqual(s["turn"]["seq"], 3)
        self.assertEqual(s["turn"]["started_ms"], T0 + 615_000)
        s, _ = tr.tick(s, T0 + 618_000, cfg)
        self.assertEqual(s["turn"]["health"], "ok")

        # T4: step_reply + bg_only working -> phase returns to `idle` with `bg_shells.count == 1`.
        s = tr.reduce(s, {"seq": 8, "t": T0 + 620_000, "kind": "step_reply"}, cfg)
        s = tr.reduce(s, {"seq": 9, "t": T0 + 621_000, "kind": "hc_state", "state": "live", "status": "working", "status_msg": "1 shell still running", "reported": True}, cfg)
        self.assertEqual(s["turn"]["phase"], "idle")
        self.assertEqual(s["bg_shells"]["count"], 1)

    def test_phase_contract_table_thresholds(self) -> None:
        cfg = tr.TurnConfig()

        # 1. `submitted`: 8s suspect, 20s W6 stalled.
        s = tr.reduce(self._state(), {"seq": 1, "t": T0, "kind": "send_submitted", "started": False}, cfg)
        s, acts = tr.tick(s, T0 + 8_000, cfg)
        self.assertEqual((s["turn"]["phase"], s["turn"]["health"]), ("submitted", "suspect"))
        self.assertTrue(any(a["kind"] == "probe_screen" for a in acts))
        s, acts = tr.tick(s, T0 + 20_000, cfg)
        self.assertEqual(s["turn"]["health"], "stalled")
        self.assertEqual(acts[0]["class"], "W6")

        # 2. `generating`: 75s slow (no stall), pty frozen 20s suspect / 45s W5 stalled,
        #    and `pty_probe(changed=True)` clears freeze non-stickily (I2).
        s = tr.reduce(self._state(), {"seq": 1, "t": T0, "kind": "hc_state", "state": "live", "status": "working", "status_ms": T0, "turn": 1, "reported": True}, cfg)
        s, _ = tr.tick(s, T0 + 75_000, cfg)
        self.assertEqual((s["turn"]["phase"], s["turn"]["health"]), ("generating", "slow"))
        s = tr.reduce(s, {"seq": 2, "t": T0 + 76_000, "kind": "pty_probe", "changed": False, "digest": "aaa"}, cfg)
        s, _ = tr.tick(s, T0 + 96_000, cfg)
        self.assertEqual(s["turn"]["health"], "suspect")
        # Screen changes -> clears suspect/frozen non-stickily!
        s = tr.reduce(s, {"seq": 3, "t": T0 + 97_000, "kind": "pty_probe", "changed": True, "digest": "bbb", "hint": "tokens:5000"}, cfg)
        s, _ = tr.tick(s, T0 + 98_000, cfg)
        self.assertEqual(s["turn"]["health"], "slow")  # >75s without step, NOT suspect/stalled
        # With `tokens:` bonus, even 240s without step does NOT trigger W1!
        s, _ = tr.tick(s, T0 + 250_000, cfg)
        self.assertNotEqual(s["turn"]["health"], "stalled")

        # Without token bonus: pty frozen 45s -> W5 stalled.
        s2 = tr.reduce(self._state(), {"seq": 1, "t": T0, "kind": "hc_state", "state": "live", "status": "working", "status_ms": T0, "turn": 1, "reported": True}, cfg)
        s2 = tr.reduce(s2, {"seq": 2, "t": T0 + 10_000, "kind": "pty_probe", "changed": False, "digest": "same"}, cfg)
        s2, acts2 = tr.tick(s2, T0 + 55_000, cfg)
        self.assertEqual((s2["turn"]["health"], acts2[0]["class"]), ("stalled", "W5"))

        # Without pty freeze, missing step >= 240s -> W1 stalled.
        s3 = tr.reduce(self._state(), {"seq": 1, "t": T0, "kind": "hc_state", "state": "live", "status": "working", "status_ms": T0, "turn": 1, "reported": True}, cfg)
        s3 = tr.reduce(s3, {"seq": 2, "t": T0 + 230_000, "kind": "pty_probe", "changed": True, "digest": "spin"}, cfg)
        s3, acts3 = tr.tick(s3, T0 + 240_000, cfg)
        self.assertEqual((s3["turn"]["health"], acts3[0]["class"]), ("stalled", "W1"))

        # 3. `tool`: 30s slow, 60s CPU-flat + pty-frozen suspect, 120s suspect -> W4, 180s hard -> W4.
        st = tr.reduce(self._state(), {"seq": 1, "t": T0, "kind": "hc_state", "state": "live", "status": "working", "status_ms": T0, "turn": 1, "reported": True}, cfg)
        st = tr.reduce(st, {"seq": 2, "t": T0 + 1_000, "kind": "step_tool_start", "tool": "Bash", "summary": "ssh prod"}, cfg)
        st = tr.reduce(st, {"seq": 3, "t": T0 + 1_000, "kind": "proc_probe", "tool_pid": 999, "cmd": "ssh prod", "cpu_ms": 10}, cfg)
        st, _ = tr.tick(st, T0 + 31_000, cfg)
        self.assertEqual((st["turn"]["phase"], st["turn"]["health"]), ("tool", "slow"))
        st = tr.reduce(st, {"seq": 4, "t": T0 + 1_000, "kind": "pty_probe", "changed": False, "digest": "prompt"}, cfg)
        st, _ = tr.tick(st, T0 + 62_000, cfg)
        self.assertEqual(st["turn"]["health"], "suspect")
        st, acts_t = tr.tick(st, T0 + 182_000, cfg)
        self.assertEqual((st["turn"]["health"], acts_t[0]["class"]), ("stalled", "W4"))
        # `step_tool_end` clears tool name immediately (FS-6).
        st = tr.reduce(st, {"seq": 5, "t": T0 + 183_000, "kind": "step_tool_end"}, cfg)
        self.assertEqual((st["turn"]["phase"], st["turn"]["activity"]["tool"]), ("generating", ""))

        # 4. `waiting_upstream`: `step_error` never closes turn; 300s -> W1.
        su = tr.reduce(self._state(), {"seq": 1, "t": T0, "kind": "hc_state", "state": "live", "status": "working", "status_ms": T0, "turn": 1, "reported": True}, cfg)
        su = tr.reduce(su, {"seq": 2, "t": T0 + 5_000, "kind": "step_error", "message": "503 overloaded, retrying attempt 1"}, cfg)
        self.assertEqual((su["turn"]["phase"], su["turn"]["health"]), ("waiting_upstream", "slow"))
        su, acts_u = tr.tick(su, T0 + 305_000, cfg)
        self.assertEqual((su["turn"]["health"], acts_u[0]["class"]), ("stalled", "W1"))

    def test_no_status_terminal_and_session_reset_and_v1_upgrade(self) -> None:
        cfg = tr.TurnConfig()
        # No-status terminal never hits W1 from missing status, and auto-closes only after 30s positive pty freeze.
        s = self._state()
        s = tr.reduce(s, {"seq": 1, "t": T0, "kind": "hc_state", "state": "live", "status": "", "reported": False}, cfg)
        s = tr.reduce(s, {"seq": 2, "t": T0, "kind": "hook_prompt", "cause": "user"}, cfg)
        s, _ = tr.tick(s, T0 + 40_000, cfg)
        self.assertEqual(s["turn"]["phase"], "generating")  # No positive freeze probe yet -> stays generating
        s = tr.reduce(s, {"seq": 3, "t": T0 + 41_000, "kind": "pty_probe", "changed": False, "digest": "x"}, cfg)
        s, _ = tr.tick(s, T0 + 71_000, cfg)
        self.assertEqual(s["turn"]["phase"], "idle")
        self.assertEqual(s["last_turn"]["outcome"], "silent")

        # Session identity reset when fg_pid changes (FS-10).
        s_pid = tr.reduce(self._state(fg_pid=100), {"seq": 1, "t": T0, "kind": "hc_state", "state": "live", "status": "working", "status_ms": T0, "turn": 1, "reported": True}, cfg)
        self.assertEqual(s_pid["turn"]["phase"], "generating")
        s_pid = tr.reduce(s_pid, {"seq": 2, "t": T0 + 5_000, "kind": "hc_state", "state": "live", "status": "idle", "fg_pid": 200, "reported": True}, cfg)
        self.assertEqual(s_pid["session"]["fg_pid"], 200)
        self.assertEqual(s_pid["turn"]["phase"], "idle")

        # v1 -> v2 upgrade: clears sticky stalled and moves outbox into inbox.
        v1 = {
            "version": 1,
            "terminal": "t12",
            "agent_kind": "claude",
            "phase": "stalled",
            "turn_seq": 4,
            "terminal_turn": 9,
            "started_ms": T0,
            "last_activity_ms": T0 + 1000,
            "outbox": [{"msg_id": "m-1", "text": "hello", "queued_ms": T0, "reason": "blocked"}],
        }
        v2 = tr.upgrade_state_v1_to_v2(v1)
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v2["turn"]["phase"], "generating")
        self.assertEqual(v2["turn"]["health"], "ok")
        self.assertEqual(v2["turn"]["id"], "hc:local:t12:0:10")
        self.assertEqual(len(v2["inbox"]), 1)
        self.assertEqual(v2["inbox"][0]["id"], "m-1")
        # Idempotent upgrade:
        self.assertEqual(tr.upgrade_state_v1_to_v2(v2), v2)
        # Unsupervised v1 projection NEVER reports stalled or slow:
        v1_unsup = tr.project_v1_turn(v2, T0 + 500_000, supervised=False)
        self.assertEqual(v1_unsup["health"], "unknown")
        self.assertFalse(v1_unsup["stalled"])
        self.assertFalse(v1_unsup["slow"])


class ReducerPropertyTests(unittest.TestCase):
    def test_healthy_interleaved_out_of_order_sequences_never_suspect_or_stalled(self) -> None:
        cfg = tr.TurnConfig()
        rng = random.Random(20261125)
        for trial in range(40):
            s = tr.default_state_v2(cfg)
            s["session"] = tr.Endpoint(runtime="hc", terminal="t12", agent_kind="claude", fg_pid=5000 + trial).to_dict()
            now = T0 + trial * 1_000_000
            seq = 1
            s = tr.reduce(s, {"seq": seq, "t": now, "kind": "hc_state", "state": "live", "status": "working", "status_ms": now, "turn": 1, "reported": True}, cfg)
            seq += 1
            for _step in range(15):
                dt = rng.randint(1_000, 12_000)
                now += dt
                # Interleave tool start, pty progress, tool end, and slightly stale/out-of-order timestamps.
                events = [
                    {"t": now, "kind": "step_tool_start", "tool": "Bash", "summary": "pytest"},
                    {"t": now - rng.randint(0, 500), "kind": "pty_probe", "changed": True, "digest": f"d{seq}"},
                    {"t": now + 1000, "kind": "step_tool_end"},
                ]
                rng.shuffle(events)
                for ev in events:
                    ev["seq"] = seq
                    seq += 1
                    s_before = tr.reduce(s, ev, cfg)
                    # Determinism & seq idempotency:
                    self.assertEqual(tr.reduce(s_before, ev, cfg), s_before)
                    s = s_before
                    s, _ = tr.tick(s, max(now + 1000, s["updated_ms"]), cfg)
                    self.assertNotIn(s["turn"]["health"], ("suspect", "stalled"), f"trial={trial}")

    def test_missing_evidence_only_never_stalls_before_threshold(self) -> None:
        cfg = tr.TurnConfig()
        rng = random.Random(9911)
        for trial in range(25):
            now = T0
            s = tr.default_state_v2(cfg)
            s["session"] = tr.Endpoint(runtime="hc", terminal="t7", agent_kind="agy", fg_pid=900 + trial).to_dict()
            s = tr.reduce(s, {"seq": 1, "t": now, "kind": "hc_state", "state": "live", "status": "working", "status_ms": now, "turn": 1, "reported": True}, cfg)
            # Advance up to 239s with no pty_probe freeze -> must never report `stalled`.
            cur_t = now
            while cur_t < now + cfg.generating_no_step_stall_ms - 1_000:
                cur_t = min(now + cfg.generating_no_step_stall_ms - 1_000, cur_t + rng.randint(2_000, 30_000))
                s, _ = tr.tick(s, cur_t, cfg)
                self.assertNotEqual(s["turn"]["health"], "stalled")
                v1 = tr.project_v1_turn(s, cur_t, supervised=True)
                self.assertIn(v1["phase"], tr.V1_PHASES)


class TurnDurationMetricsAndBudgetTests(unittest.TestCase):
    """Phase 2 (`O-a`, `O-c`, D7): turn duration breakdown in `last_turn`, budget flags, and `summarize_turns`."""

    def _state(self) -> dict:
        s = tr.default_state_v2()
        s["session"] = tr.Endpoint(runtime="hc", terminal="t12", agent_kind="claude", fg_pid=4200, epoch=1).to_dict()
        return tr.sync_compat_fields(s)

    def test_close_turn_records_generation_vs_tool_split_longest_step_and_budget_hint(self) -> None:
        cfg = tr.TurnConfig()  # soft=45s, hard=120s
        s = self._state()
        # User turn: 0..20s generating, 20..56s Write (36s), 56..66s generating (10s), 66..81s Read (15s), 81..91s generating (10s) => total 91s.
        s = tr.reduce(s, {"seq": 1, "t": T0, "kind": "hook_prompt", "cause": "user", "msg_ids": ["u-1"], "hc_turn": 1}, cfg)
        s = tr.reduce(s, {"seq": 2, "t": T0 + 20_000, "kind": "step_tool_start", "tool": "Write", "summary": "briefs/big.md"}, cfg)
        s = tr.reduce(s, {"seq": 3, "t": T0 + 56_000, "kind": "step_tool_end"}, cfg)
        s = tr.reduce(s, {"seq": 4, "t": T0 + 66_000, "kind": "step_tool_start", "tool": "Read", "summary": "model.js"}, cfg)
        s = tr.reduce(s, {"seq": 5, "t": T0 + 81_000, "kind": "step_tool_end"}, cfg)
        s = tr.reduce(s, {"seq": 6, "t": T0 + 91_000, "kind": "hook_stop", "expected_seq": 1, "has_reply": True}, cfg)

        lt = s["last_turn"]
        self.assertEqual(lt["cause"], "user")
        self.assertEqual(lt["total_ms"], 91_000)
        self.assertEqual(lt["split"], {"generate_ms": 40_000, "tool_ms": 51_000, "steps": 2})
        self.assertEqual(lt["longest_step"], {"ms": 36_000, "kind": "Write", "summary": "briefs/big.md"})
        self.assertEqual(lt["action_ms"], {"generate": 40_000, "Write": 36_000, "Read": 15_000})
        self.assertTrue(lt["budget"]["over_soft"])
        self.assertFalse(lt["budget"]["over_hard"])
        self.assertIsNotNone(s["pending_occupation_hint"])
        self.assertEqual(s["pending_occupation_hint"]["total_ms"], 91_000)

    def test_deliver_turn_or_under_budget_user_turn_does_not_queue_occupation_hint(self) -> None:
        cfg = tr.TurnConfig()
        # Deliver turn >45s -> no occupation hint (O-c applies to user-initiated turns).
        s = self._state()
        s = tr.reduce(s, {"seq": 1, "t": T0, "kind": "hook_prompt", "cause": "deliver", "batch": [0, 20], "hc_turn": 1}, cfg)
        s = tr.reduce(s, {"seq": 2, "t": T0 + 60_000, "kind": "hook_stop", "expected_seq": 1, "has_reply": True}, cfg)
        self.assertIsNone(s["pending_occupation_hint"])

        # User turn <=45s -> no occupation hint.
        s = tr.reduce(s, {"seq": 3, "t": T0 + 70_000, "kind": "hook_prompt", "cause": "user", "hc_turn": 2}, cfg)
        s = tr.reduce(s, {"seq": 4, "t": T0 + 100_000, "kind": "hook_stop", "expected_seq": 2, "has_reply": True}, cfg)
        self.assertFalse(s["last_turn"]["budget"]["over_soft"])
        self.assertIsNone(s["pending_occupation_hint"])

    def test_summarize_turns_computes_percentiles_over_budget_and_top_actions(self) -> None:
        entries = [
            {"seq": 1, "t": T0 + 10_000, "kind": "turn_summary", "turn_id": "t:1", "cause": "user", "total_ms": 10_000, "action_ms": {"generate": 10_000}, "over_soft": False, "over_hard": False},
            {"seq": 2, "t": T0 + 80_000, "kind": "turn_summary", "turn_id": "t:2", "cause": "user", "total_ms": 60_000, "action_ms": {"generate": 20_000, "Write": 40_000}, "over_soft": True, "over_hard": False},
            {"seq": 3, "t": T0 + 220_000, "kind": "turn_summary", "turn_id": "t:3", "cause": "user", "total_ms": 135_000, "action_ms": {"generate": 55_000, "Write": 50_000, "Read": 30_000}, "over_soft": True, "over_hard": True},
            {"seq": 4, "t": T0 + 250_000, "kind": "turn_summary", "turn_id": "t:4", "cause": "deliver", "total_ms": 18_000, "action_ms": {"generate": 18_000}, "over_soft": False, "over_hard": False},
        ]
        rep = tr.summarize_turns(entries)
        self.assertEqual(rep["total_turns"], 4)
        self.assertEqual(rep["user"]["count"], 3)
        self.assertEqual(rep["user"]["p50_ms"], 60_000)
        self.assertEqual(rep["user"]["max_ms"], 135_000)
        self.assertEqual(rep["user"]["over_soft"], 2)
        self.assertEqual(rep["user"]["over_hard"], 1)
        self.assertEqual(rep["top_actions"][0]["category"], "generate")
        self.assertEqual(rep["top_actions"][1]["category"], "Write")
        self.assertEqual(rep["top_actions"][1]["total_ms"], 90_000)

    def test_w6_retype_submitted_releases_incident_holds_batch_and_replays_real_journal_1591_1604(self) -> None:
        from pmlib.messaging.router import EndpointSnapshot, evaluate_batch_readiness

        cfg = tr.TurnConfig()
        ep_dict = {
            "runtime": "hc", "machine": None, "terminal": "t1k6", "workspace": "",
            "session_id": "", "agent_kind": "agy", "fg_pid": 88489, "epoch": 2,
        }
        s = tr.default_state_v2()
        # Real 2026-11-28 01:22:23–01:22:54 journal excerpt (seq 1591–1601)
        real_obs = [
            {"seq": 1591, "t": 1795846943128, "src": "supervisor", "kind": "hc_state", "state": "live", "status": "idle", "status_msg": "", "status_ms": 1795846942479, "turn": 189, "reported": True, "seat_starting": False, "endpoint": ep_dict},
            {"seq": 1592, "t": 1795846948179, "src": "supervisor", "kind": "send_submitted", "terminal": "t1k6", "agent_kind": "agy", "cause": "deliver", "msg_ids": [], "hc_turn": 189, "started": False, "endpoint": ep_dict, "batch": [3334330, 3335281]},
            {"seq": 1594, "t": 1795846956996, "src": "probe:pty", "kind": "pty_probe", "changed": True, "digest": "0d221b7bd325b355", "hint": "tokens:229", "dialog_kind": ""},
            {"seq": 1595, "t": 1795846957999, "src": "probe:pty", "kind": "pty_probe", "changed": False, "digest": "0d221b7bd325b355", "hint": "tokens:229", "dialog_kind": ""},
        ]
        for obs in real_obs:
            s = tr.reduce(s, obs, cfg)
        self.assertEqual(s["turn"]["phase"], "submitted")
        self.assertEqual(s["turn"]["cause"]["kind"], "deliver")
        self.assertEqual(s["turn"]["cause"]["batch"], [3334330, 3335281])

        # +20s -> W6 opens at seq 1596
        s, acts = tr.tick(s, 1795846968350, cfg)
        self.assertEqual(s["incident"]["class"], "W6")
        self.assertTrue(tr.incident_holds_batch(s))
        inc_id = s["incident"]["id"]
        self.assertEqual(acts[-1]["action"], "classify_screen")

        # Stage 0 classify_screen -> no_dialog, Stage 1 nudge_enter -> sent (batch still held)
        for obs in (
            {"seq": 1596, "t": 1795846968350, "src": "supervisor", "kind": "recovery_started", "incident_id": inc_id, "class": "W6", "stage": 0, "action": "classify_screen"},
            {"seq": 1597, "t": 1795846968350, "src": "supervisor", "kind": "recovery_result", "incident_id": inc_id, "class": "W6", "stage": 0, "action": "classify_screen", "outcome": "no_dialog", "detail": "> "},
            {"seq": 1598, "t": 1795846969350, "src": "supervisor", "kind": "recovery_started", "incident_id": inc_id, "class": "W6", "stage": 1, "action": "nudge_enter"},
            {"seq": 1599, "t": 1795846969350, "src": "supervisor", "kind": "recovery_result", "incident_id": inc_id, "class": "W6", "stage": 1, "action": "nudge_enter", "outcome": "sent", "detail": "enter"},
        ):
            s = tr.reduce(s, obs, cfg)
        self.assertTrue(tr.incident_holds_batch(s), "batch must remain held while awaiting nudge_enter")

        # +5s -> Stage 2 retype_submitted -> requeued (retry_unstarted)
        s, acts = tr.tick(s, 1795846974783, cfg)
        self.assertEqual(acts[-1]["action"], "retype_submitted")
        for obs in (
            {"seq": 1600, "t": 1795846974783, "src": "supervisor", "kind": "recovery_started", "incident_id": inc_id, "class": "W6", "stage": 2, "action": "retype_submitted"},
            {"seq": 1601, "t": 1795846974783, "src": "supervisor", "kind": "recovery_result", "incident_id": inc_id, "class": "W6", "stage": 2, "action": "retype_submitted", "outcome": "requeued", "detail": "retry_unstarted"},
        ):
            s = tr.reduce(s, obs, cfg)
        self.assertEqual(s["incident"]["awaiting_verify"], "retype_submitted")
        self.assertFalse(tr.incident_holds_batch(s), "retype_submitted for deliver must release incident_holds_batch")

        # Both Tier-1 (status-reporting idle) and Tier-2/3 (no-status recovering) must be ready to deliver the retry!
        ready_t1, _, reason_t1 = evaluate_batch_readiness(EndpointSnapshot(
            live_state="live", agent_state="idle", can_report_status=True,
            turn_phase="recovering", last_turn_stopped=False, recovery_hold=tr.incident_holds_batch(s),
        ))
        self.assertTrue(ready_t1, reason_t1)
        ready_t2, _, reason_t2 = evaluate_batch_readiness(EndpointSnapshot(
            live_state="live", agent_state="", can_report_status=False,
            turn_phase="recovering", last_turn_stopped=False, recovery_hold=tr.incident_holds_batch(s),
        ))
        self.assertTrue(ready_t2, reason_t2)

        # Once the retried send starts the turn, W6 resolves cleanly.
        s = tr.reduce(s, {
            "seq": 1602, "t": 1795846975500, "src": "supervisor", "kind": "send_submitted",
            "terminal": "t1k6", "agent_kind": "agy", "cause": "deliver", "msg_ids": [],
            "hc_turn": 190, "started": True, "endpoint": ep_dict, "batch": [3334330, 3335281],
        }, cfg)
        self.assertEqual(s["incident"]["status"], "resolved")
        self.assertEqual(s["incident"]["resolution"], "turn_started")
        self.assertEqual(s["turn"]["phase"], "generating")

        # User-caused W6 or notified incident must still hold unrelated event batches.
        s_user = tr.default_state_v2()
        s_user["incident"] = {"status": "recovering", "cause_kind": "user", "awaiting_verify": "retype_submitted"}
        self.assertTrue(tr.incident_holds_batch(s_user))
        s_notified = tr.default_state_v2()
        s_notified["incident"] = {"status": "notified", "cause_kind": "deliver", "awaiting_verify": ""}
        self.assertTrue(tr.incident_holds_batch(s_notified))


if __name__ == "__main__":
    unittest.main()
