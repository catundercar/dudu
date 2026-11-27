"""Replay tests over sanitized observation journal fixtures (`tests/fixtures/turn_journals/*.jsonl`)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "turn_journals"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = "/nonexistent/pm-home-turn-replay"
    try:
        from pmlib.project import turn_reducer as tr  # noqa: E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved
else:
    from pmlib.project import turn_reducer as tr  # noqa: E402


def _replay(fixture_name: str, cfg: tr.TurnConfig | None = None) -> tuple[list[dict], dict]:
    c = cfg or tr.TurnConfig()
    rows = [
        json.loads(line)
        for line in (FIXTURES / fixture_name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    state = tr.default_state_v2(c)
    timeline: list[dict] = []
    for row in rows:
        state = tr.reduce(state, row, c)
        state, actions = tr.tick(state, int(row["t"]), c)
        timeline.append({
            "seq": row["seq"],
            "t": row["t"],
            "phase": state["turn"]["phase"],
            "health": state["turn"]["health"],
            "turn_seq": state["turn"]["seq"],
            "turn_id": state["turn"]["id"],
            "cause": state["turn"]["cause"]["kind"],
            "tool": state["turn"]["activity"]["tool"],
            "bg_count": state["bg_shells"]["count"],
            "actions": actions,
        })
    return timeline, state


class TurnReplaySuiteTests(unittest.TestCase):
    def test_01_false_stall_deliver_lag_produces_zero_stalls(self) -> None:
        timeline, final_st = _replay("01_false_stall_deliver_lag.jsonl")
        self.assertTrue(all(step["health"] != "stalled" for step in timeline))
        # Deliver send + hc working + delayed USER_INPUT (5s) all merge into seq 1:
        self.assertEqual([step["turn_seq"] for step in timeline[1:4]], [1, 1, 1])
        self.assertEqual(timeline[2]["phase"], "generating")
        self.assertEqual(timeline[4]["tool"], "read_file")
        self.assertEqual(timeline[5]["tool"], "")  # cleared on step_tool_end
        self.assertEqual(final_st["turn"]["phase"], "idle")
        self.assertEqual(final_st["last_turn"]["outcome"], "replied")

    def test_02_agy_long_generation_stays_ok_or_slow_never_stalled(self) -> None:
        timeline, final_st = _replay("02_agy_long_generation.jsonl")
        self.assertTrue(all(step["health"] != "stalled" for step in timeline))
        self.assertEqual(timeline[3]["tool"], "write_file")
        # 120s mark has tokens bonus + pty changed -> slow, never stalled
        self.assertEqual(timeline[5]["health"], "slow")
        self.assertEqual(final_st["turn"]["phase"], "idle")

    def test_03_error_retry_transitions_to_waiting_upstream_and_recovers(self) -> None:
        timeline, final_st = _replay("03_error_retry_and_continue.jsonl")
        self.assertTrue(all(step["health"] != "stalled" for step in timeline))
        self.assertEqual(timeline[2]["phase"], "waiting_upstream")
        self.assertEqual(timeline[2]["health"], "slow")
        self.assertEqual(timeline[3]["phase"], "tool")
        self.assertEqual(timeline[3]["tool"], "grep_search")
        self.assertEqual(final_st["last_turn"]["outcome"], "replied")

    def test_04_self_wake_system_message_opens_self_turn(self) -> None:
        timeline, final_st = _replay("04_self_wake_system.jsonl")
        self.assertTrue(all(step["health"] != "stalled" for step in timeline))
        self.assertEqual(timeline[1]["phase"], "generating")
        self.assertEqual(timeline[1]["cause"], "self")
        self.assertEqual(timeline[2]["turn_seq"], 1)  # merged with hc_state(working)
        self.assertEqual(timeline[3]["tool"], "run_command")
        self.assertEqual(final_st["last_turn"]["outcome"], "replied")

    def test_05_late_stop_ignored_and_bg_shells_keep_idle(self) -> None:
        timeline, final_st = _replay("05_late_stop_and_bg_shells.jsonl")
        # Seq 3 is late Stop(expected_seq=1) after Turn 2 started -> Turn 2 stays active!
        self.assertEqual((timeline[2]["turn_seq"], timeline[2]["phase"]), (2, "generating"))
        # Seq 4 closes Turn 2, and Seq 5 (`working` + "1 shell still running") preserves `idle` + bg_count=1 (T4).
        self.assertEqual(final_st["turn"]["phase"], "idle")
        self.assertEqual(final_st["bg_shells"]["count"], 1)

    def test_06_upstream_hang_triggers_w1_then_503_enters_waiting_upstream(self) -> None:
        timeline, final_st = _replay("06_upstream_hang_503.jsonl")
        # At t=+240s with no step progress and no token bonus -> W1 stall!
        self.assertEqual(timeline[3]["health"], "stalled")
        self.assertEqual(timeline[3]["actions"][0]["class"], "W1")
        # Subsequent 503 retry error moves to waiting_upstream:
        self.assertEqual(final_st["turn"]["phase"], "waiting_upstream")

    def test_07_esc_interrupt_and_session_swap_resets_identity(self) -> None:
        timeline, final_st = _replay("07_esc_interrupt_and_session_swap.jsonl")
        self.assertEqual(timeline[1]["phase"], "idle")
        self.assertEqual(final_st["session"]["fg_pid"], 59900)
        self.assertEqual(final_st["session"]["epoch"], 2)
        self.assertEqual(final_st["turn"]["id"], "hc:local:t12:59900:2")
        self.assertEqual(final_st["turn"]["phase"], "generating")

    def test_08_late_stop_journal_amends_silent_and_emits_zero_recovery_actions(self) -> None:
        timeline, final_st = _replay("journal-late-stop-2026-11-26.jsonl")
        self.assertEqual(final_st["turn"]["phase"], "idle")
        self.assertEqual(final_st["last_turn"]["outcome"], "replied")
        self.assertIsNone(final_st["incident"])
        for step in timeline:
            self.assertEqual([a for a in step["actions"] if a.get("kind") == "recovery_action"], [])
        t_end = int(timeline[-1]["t"])
        st_tick = final_st
        for dt_s in range(5, 125, 5):
            st_tick, acts = tr.tick(st_tick, t_end + dt_s * 1_000)
            self.assertEqual([a for a in acts if a.get("kind") == "recovery_action"], [])


if __name__ == "__main__":
    unittest.main()
