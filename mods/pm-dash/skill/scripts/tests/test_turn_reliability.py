"""Regression tests for PM turn & delivery reliability:
- Cross-timezone UTC `at_ms`, `tz`, monotonic `seq`, and `server_now_ms`;
- Idempotent `pm.py project send --msg-id` & `pm.py project interrupt`;
- Multi-message coalescing deduplication across `TurnTracker`, `hooks`, and `AgyTranscriptWatcher`;
- Pre-opened `agy` session discovery after `pm.py claim` & `ERROR_MESSAGE` turn closure;
- Async `Stop` vs next `UserPromptSubmit` `turn_seq` ordering & non-blocking `peek_pending`;
- Live transcript 64 KiB tool-activity probing (Claude, Codex, `agy`), stall detection, and background-work batch readiness;
- `INTERNAL_PROJECT_FILES` parity between Python (`pmlib/store.py`) and JS (`mods/pm-project/model.js`).
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS.parents[3]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = "/nonexistent/pm-home-turn-reliability"
    try:
        from pmlib import cli, hooks  # noqa: E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved
else:
    from pmlib import cli, hooks  # noqa: E402

from pmlib.events.agy_watch import AgyTranscriptWatcher  # noqa: E402
from pmlib.events.deliver import Delivery, prompt_kind  # noqa: E402
from pmlib.events.deliverer import Deliverer  # noqa: E402
from pmlib.events.policy import manager_ready_for_batch  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.turn_state import (  # noqa: E402
    HARD_STALL_MS,
    SOFT_STALL_MS,
    TurnTracker,
    match_coalesced_prompt_prefix,
    probe_transcript_activity,
)
from pmlib.store import INTERNAL_PROJECT_FILES  # noqa: E402
from pmlib.views.state import dash_state  # noqa: E402
from tests.fakes import FakeClock, make_ctx  # noqa: E402


def _utc_iso(base_ts: float, offset_sec: float = 0) -> str:
    dt = datetime.datetime.fromtimestamp(base_ts + offset_sec, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class TurnAndDeliveryReliabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-turn-rel-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "demo"
        self.repo.mkdir(parents=True)
        self.agy_dir = self.root / "agy"
        self.agy_dir.mkdir(parents=True)
        self.clock = FakeClock("2026-11-23 22:30:00")
        self.base_ts = self.clock.time()
        self.ctx = make_ctx(self.root / "ledger", clock=self.clock, agy_dir=self.agy_dir)
        self.slug = project_slug(self.repo)

    def _register_pm(self, *, agent: str = "claude", terminal: str = "t182", claimed: str = "") -> dict:
        stamp = claimed or self.clock.now_sec()
        rec = {
            "name": f"pm-{self.slug}",
            "project": "demo",
            "repo": str(self.repo),
            "pane": f"hc:{terminal}",
            "terminal": terminal,
            "runtime": "hc",
            "agent": agent,
            "claimed": stamp,
            "rotations": 0,
        }
        self.ctx.store.change_registration(self.slug, lambda _cur: rec)
        self.ctx.hc.terminals[terminal] = {
            "address": terminal,
            "id": terminal,
            "state": "live",
            "cwd": str(self.repo),
            "labels": {"pm": "demo"},
            "status": {"state": "idle", "app": agent},
            "turn": 1,
        }
        return rec

    def test_append_event_injects_monotonic_seq_utc_at_ms_and_tz(self) -> None:
        self._register_pm()
        conv = Conversation(self.ctx, self.repo)
        conv.record("user", text="第一条")
        self.clock.advance(2.5)
        conv.record("pm", text="收到", by="hc:t182")

        events = conv.events()
        self.assertEqual([e["seq"] for e in events], [1, 2])
        self.assertEqual(events[0]["at_ms"], int(self.base_ts * 1000))
        self.assertEqual(events[1]["at_ms"], int((self.base_ts + 2.5) * 1000))
        self.assertRegex(events[0]["tz"], r"^[+-]\d\d:\d\d$")

        state = dash_state(self.ctx)
        self.assertEqual(state["server_now_ms"], int((self.base_ts + 2.5) * 1000))
        self.assertRegex(state["server_tz"], r"^[+-]\d\d:\d\d$")
        self.assertEqual(state["pms"][0]["turn"]["phase"], "idle")

    def test_project_send_is_idempotent_logs_immediately_and_queues_when_blocked(self) -> None:
        self._register_pm(agent="agy", terminal="t182")
        sent_calls: list[tuple[str, str]] = []
        orig_send = self.ctx.hc.send

        def spy_send(term: str, text: str, **kw):
            sent_calls.append((term, text))
            return {"ok": True, "started": True}

        self.ctx.hc.send = spy_send  # type: ignore[method-assign]
        try:
            cli.main(
                ["project", "send", self.slug, "--msg-id", "u-msg-1", "--", "t182", "先修跨时区"],
                ctx=self.ctx,
            )
            r1 = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
            self.assertEqual(r1["status"], "delivered")
            self.assertFalse(r1.get("deduped", False))
            self.assertEqual(len(sent_calls), 1)

            # Retry with the exact same msg_id (simulating network timeout / layout reload): zero duplicate hc send!
            self.ctx.out.clear()
            cli.main(
                ["project", "send", self.slug, "--msg-id", "u-msg-1", "--", "t182", "先修跨时区"],
                ctx=self.ctx,
            )
            r2 = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
            self.assertEqual(r2["status"], "delivered")
            self.assertTrue(r2["deduped"])
            self.assertEqual(len(sent_calls), 1)
            events = Conversation(self.ctx, self.repo).events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["msg_id"], "u-msg-1")
            self.assertEqual(events[0]["text"], "先修跨时区")

            # When PM terminal is blocked on a dialog, `project send` queues into outbox and Deliverer drains FIFO on unblock.
            self.ctx.hc.terminals["t182"]["status"] = {"state": "blocked"}
            self.ctx.out.clear()
            cli.main(
                ["project", "send", self.slug, "--msg-id", "u-msg-2", "--", "t182", "恢复后第一句"],
                ctx=self.ctx,
            )
            q1 = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
            self.assertEqual(q1["status"], "queued")
            self.assertEqual(q1["queued_count"], 1)
            self.assertEqual(len(sent_calls), 1)

            # Unblock terminal and run one Deliverer look -> drains outbox FIFO and logs u-msg-2!
            self.ctx.hc.terminals["t182"]["status"] = {"state": "idle"}
            d = Deliverer(self.ctx, self.repo)
            dummy_changes = type("C", (), {"terminals": set(), "files": []})()
            d.look(dummy_changes, {}, {})
            self.assertEqual(len(sent_calls), 2)
            self.assertEqual(sent_calls[1], ("t182", "恢复后第一句"))
            events_after = Conversation(self.ctx, self.repo).events()
            self.assertEqual([e.get("msg_id") for e in events_after], ["u-msg-1", "u-msg-2"])
        finally:
            self.ctx.hc.send = orig_send  # type: ignore[method-assign]

    def test_busy_turn_coalesced_messages_in_agy_do_not_duplicate_and_preopened_session_attaches(self) -> None:
        # 1. Open agy 10 minutes BEFORE `pm.py claim`: pre-claim turns must be skipped, post-claim turns synced!
        t_open = self.base_ts - 600
        tp = self.agy_dir / "brain" / "conv-preopened" / ".system_generated" / "logs" / "transcript_full.jsonl"
        tp.parent.mkdir(parents=True)
        pre_rows = [
            {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "status": "DONE",
             "created_at": _utc_iso(t_open, 0), "content": f"<USER_REQUEST>看看 {self.repo} 目录</USER_REQUEST>"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE",
             "created_at": _utc_iso(t_open, 5), "content": "好的，看完了。"},
        ]
        with open(tp, "w", encoding="utf-8") as f:
            for r in pre_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        # Now at `self.base_ts`, user claims PM in that same agy session!
        self._register_pm(agent="agy", terminal="t182", claimed=self.clock.now_sec())
        self.ctx.hc.send = lambda term, text, **kw: {"ok": True, "started": True}  # type: ignore[method-assign]

        # User sends 2 messages from UI while agy is busy working on a tool step:
        tracker = TurnTracker(self.ctx, self.repo)
        tracker.send_user_message(msg_id="u-busy-1", text="先别动 UI")
        self.clock.advance(1.0)
        tracker.send_user_message(msg_id="u-busy-2", text="顺便把跨时区单测补上")

        # agy finishes its current step and coalesces both queued inputs into ONE `<USER_REQUEST>` joined by `\n`!
        post_rows = [
            {"step_index": 2, "type": "USER_INPUT", "source": "USER_EXPLICIT", "status": "DONE",
             "created_at": _utc_iso(self.base_ts, 2),
             "content": "<USER_REQUEST>\n先别动 UI\n顺便把跨时区单测补上\n</USER_REQUEST>\n<ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>"},
            {"step_index": 3, "type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE",
             "created_at": _utc_iso(self.base_ts, 4),
             "tool_calls": [{"id": "tc1", "name": "run_command", "args": {"toolSummary": "Run unit tests"}}],
             "content": ""},
            {"step_index": 4, "type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE",
             "created_at": _utc_iso(self.base_ts, 8),
             "content": "两件事都收到了，已处理完毕。"},
        ]
        with open(tp, "a", encoding="utf-8") as f:
            for r in post_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        watcher = AgyTranscriptWatcher(self.ctx, agy_dir=self.agy_dir)
        recorded = watcher.sync(self.repo)
        # Only the PM reply is newly appended; pre-claim rows were skipped and the coalesced user row matched [u-busy-1, u-busy-2]!
        self.assertEqual(recorded, 1)
        events = Conversation(self.ctx, self.repo).events()
        self.assertEqual([(e["type"], e.get("msg_id"), e["text"]) for e in events], [
            ("user", "u-busy-1", "先别动 UI"),
            ("user", "u-busy-2", "顺便把跨时区单测补上"),
            ("pm", None, "两件事都收到了，已处理完毕。"),
        ])
        receipts = Conversation(self.ctx, self.repo).receipts()
        self.assertTrue(any(r.get("msg_ids") == ["u-busy-1", "u-busy-2"] for r in receipts))
        self.assertEqual(watcher.watched_files(self.repo), [tp])
        self.assertTrue(TurnTracker(self.ctx, self.repo).is_turn_stopped("t182"))

        # An ERROR_MESSAGE row closes an active turn cleanly so PM never stays stuck in `working`.
        tracker.begin_turn(terminal="t182", agent_kind="agy", cause="user", from_hook=True)
        self.assertEqual(tracker.read()["phase"], "working")
        with open(tp, "a", encoding="utf-8") as f:
            f.write(json.dumps({"step_index": 5, "type": "ERROR_MESSAGE", "created_at": _utc_iso(self.base_ts, 12)}) + "\n")
        watcher.sync(self.repo)
        self.assertEqual(tracker.read()["phase"], "idle")

    def test_coalesced_prompt_prefix_with_terminal_remainder(self) -> None:
        pool = [
            {"msg_id": "u-1", "text": "第一句"},
            {"msg_id": "u-2", "text": "第二句\n带换行"},
        ]
        self.assertEqual(match_coalesced_prompt_prefix("第一句\n\n第二句\n带换行", pool), ([0, 1], ""))
        self.assertEqual(
            match_coalesced_prompt_prefix("第一句\n终端手敲第三句", pool),
            ([0], "终端手敲第三句"),
        )

    def test_async_stop_hook_does_not_clobber_newer_turn_or_batch_cause(self) -> None:
        self._register_pm(agent="claude", terminal="t182")
        tracker = TurnTracker(self.ctx, self.repo)
        seq1 = tracker.begin_turn(terminal="t182", agent_kind="claude", cause="deliver", batch=[10, 90], from_hook=True)
        seq2 = tracker.begin_turn(terminal="t182", agent_kind="claude", cause="user", msg_ids=["u-9"], from_hook=True)
        self.assertEqual((seq1, seq2), (1, 2))

        # Turn 1's late async Stop arrives after Turn 2 already started:
        # Turn 1 still gets its own `after="deliver"` cause, while Turn 2 remains `working`!
        cause1 = tracker.end_turn(expected_seq=seq1)
        self.assertEqual(cause1, {"after": "deliver", "batch": [10, 90]})
        self.assertEqual(tracker.read()["phase"], "working")
        self.assertEqual(tracker.read()["turn_seq"], 2)

        # Turn 2 finishes: has no `after="deliver"` and transitions cleanly to `idle`.
        cause2 = tracker.end_turn(expected_seq=seq2)
        self.assertEqual(cause2, {})
        self.assertEqual(tracker.read()["phase"], "idle")

    def test_prompt_kind_allows_angle_brackets_and_unix_paths_while_filtering_system_tags_and_slash_cmds(self) -> None:
        self.assertEqual(prompt_kind("<div>帮我看下这段 HTML</div>"), ("user", "", "<div>帮我看下这段 HTML</div>"))
        self.assertEqual(prompt_kind("/tmp 磁盘满了帮我清理下"), ("user", "", "/tmp 磁盘满了帮我清理下"))
        self.assertEqual(prompt_kind("/Users/demo/shot.png 看这张图"), ("user", "", "/Users/demo/shot.png 看这张图"))
        self.assertEqual(prompt_kind("/compact")[0], "other")
        self.assertEqual(prompt_kind("<task-notification>done</task-notification>")[0], "other")
        self.assertEqual(prompt_kind("<system-reminder>hi</system-reminder>")[0], "other")

    def test_live_transcript_activity_stall_thresholds_interrupt_and_bg_work_policy(self) -> None:
        rec = self._register_pm(agent="claude", terminal="t182")
        tr_dir = self.ctx.agents.claude_projects / re.sub(r"[^A-Za-z0-9]", "-", str(self.repo))
        tr_dir.mkdir(parents=True)
        tr_path = tr_dir / "sess-1.jsonl"
        rec["agent_session"] = {"kind": "claude", "id": "sess-1", "transcript": str(tr_path)}
        self.ctx.store.change_registration(self.slug, lambda _cur: rec)

        tr_path.write_text(
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "python3 tests/run_checks.py"}}],
                },
            }) + "\n",
            encoding="utf-8",
        )
        # Align file mtime to fake clock start.
        os.utime(tr_path, (self.base_ts, self.base_ts))

        probe = probe_transcript_activity(tr_path, "claude")
        self.assertEqual(probe["activity"]["tool"], "Bash")
        self.assertIn("run_checks.py", probe["activity"]["summary"])

        tracker = TurnTracker(self.ctx, self.repo)
        tracker.begin_turn(terminal="t182", agent_kind="claude", cause="user", from_hook=True)
        self.ctx.hc.terminals["t182"]["status"] = {"state": "working"}

        # Soft slow at 95s
        self.clock.advance(SOFT_STALL_MS / 1000 + 5)
        snap_slow = tracker.live_snapshot(rec, {"agent_status": "working", "name": rec["name"]})
        self.assertTrue(snap_slow["slow"])
        self.assertFalse(snap_slow["stalled"])
        self.assertIn("run_checks.py", snap_slow["activity"]["summary"])

        # Hard stalled at 305s
        self.clock.advance((HARD_STALL_MS - SOFT_STALL_MS) / 1000 + 5)
        snap_stalled = tracker.live_snapshot(rec, {"agent_status": "working", "name": rec["name"]})
        self.assertTrue(snap_stalled["stalled"])
        self.assertEqual(snap_stalled["phase"], "stalled")

        # `pm.py project interrupt` sends hc interrupt and resets stall state to working.
        interrupted: list[str] = []
        self.ctx.hc.interrupt = lambda term, **kw: (interrupted.append(term) or {"ok": True})  # type: ignore[method-assign]
        self.ctx.out.clear()
        cli.main(["project", "interrupt", self.slug], ctx=self.ctx)
        int_res = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertTrue(int_res["ok"])
        self.assertEqual(interrupted, ["t182"])

        # Background child process readiness works even without English "shells still running" text.
        self.assertEqual(
            manager_ready_for_batch({"status": {"state": "working", "msg": ""}}, True, bg_work=True),
            (True, False),
        )
        self.assertEqual(
            manager_ready_for_batch({"status": {"state": "working", "msg": ""}}, False, bg_work=True),
            (False, False),
        )

    def test_internal_project_files_include_pm_turn_in_both_python_and_js(self) -> None:
        self.assertIn("pm-turn.json", INTERNAL_PROJECT_FILES)
        js_src = (REPO_ROOT / "mods" / "pm-project" / "model.js").read_text(encoding="utf-8")
        m = re.search(r"INTERNAL_PROJECT_FILES\s*=\s*new Set\(\[([\s\S]*?)\]\)", js_src)
        self.assertIsNotNone(m)
        assert m is not None
        js_files = set(re.findall(r"'([^']+)'", m.group(1)))
        for shared_internal in (
            "conversation.jsonl", "receipts.json", "delivered.json", "turn-cause.json",
            "taken-in.json", "task-seq.json", "agy-transcript.json", "pm-turn.json",
        ):
            self.assertIn(shared_internal, js_files)


if __name__ == "__main__":
    unittest.main()
