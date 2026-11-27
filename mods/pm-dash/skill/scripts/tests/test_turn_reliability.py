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
from pmlib.messaging.router import manager_ready_for_batch  # noqa: E402
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
            self.assertEqual(r1["status"], "accepted")
            self.assertEqual(r1["state"], "accepted")
            self.assertTrue(r1["env_id"])
            self.assertFalse(r1.get("deduped", False))
            self.assertEqual(len(sent_calls), 0)

            # Retry with the exact same msg_id (simulating network timeout / layout reload): idempotent dedupe!
            self.ctx.out.clear()
            cli.main(
                ["project", "send", self.slug, "--msg-id", "u-msg-1", "--", "t182", "先修跨时区"],
                ctx=self.ctx,
            )
            r2 = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
            self.assertEqual(r2["status"], "accepted")
            self.assertTrue(r2["deduped"])
            events = Conversation(self.ctx, self.repo).events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["msg_id"], "u-msg-1")
            self.assertEqual(events[0]["text"], "先修跨时区")

            # Single-typist Deliverer types u-msg-1 cleanly into PM terminal.
            d = Deliverer(self.ctx, self.repo)
            dummy_changes = type("C", (), {"terminals": set(), "files": []})()
            d.look(dummy_changes, {}, {})
            self.assertEqual(len(sent_calls), 1)
            self.assertEqual(sent_calls[0], ("t182", "先修跨时区"))

            # When PM terminal is blocked on a dialog, `project send` queues with blocked_prompt reason.
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

            # Unblock terminal and run one Deliverer look -> drains mailbox FIFO and logs u-msg-2!
            self.ctx.hc.terminals["t182"]["status"] = {"state": "idle"}
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

        # User sends 2 messages from UI and single-typist Deliverer types them to agy:
        tracker = TurnTracker(self.ctx, self.repo)
        tracker.send_user_message(msg_id="u-busy-1", text="先别动 UI")
        self.clock.advance(1.0)
        tracker.send_user_message(msg_id="u-busy-2", text="顺便把跨时区单测补上")
        d = Deliverer(self.ctx, self.repo)
        dummy_changes = type("C", (), {"terminals": set(), "files": []})()
        d.look(dummy_changes, {}, {})
        d.look(dummy_changes, {}, {})

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
        self.assertFalse(self.ctx.home.project_for(self.repo).receipts.exists())
        inbox_states = {r["id"]: r["state"] for r in tracker.pm_mailbox.inbox_projection() if r.get("kind") == "user"}
        self.assertEqual(inbox_states.get("u-busy-1"), "answered")
        self.assertEqual(inbox_states.get("u-busy-2"), "answered")
        self.assertEqual(watcher.watched_files(self.repo), [tp])
        self.assertTrue(TurnTracker(self.ctx, self.repo).is_turn_stopped("t182"))

        # FS-7: ERROR_MESSAGE no longer directly ends an active turn (agy retries and continues).
        tracker.begin_turn(terminal="t182", agent_kind="agy", cause="user", from_hook=True)
        self.assertEqual(tracker.read()["phase"], "working")
        with open(tp, "a", encoding="utf-8") as f:
            f.write(json.dumps({"step_index": 5, "type": "ERROR_MESSAGE", "created_at": _utc_iso(self.base_ts, 12)}) + "\n")
        watcher.sync(self.repo)
        self.assertEqual(tracker.read()["phase"], "working")

        # FS-8: SYSTEM_MESSAGE followed by a model line opens a new turn with cause `self`,
        # and tool activity while terminal is `working` transitions `idle` back to `working`.
        tracker.end_turn()
        self.assertEqual(tracker.read()["phase"], "idle")
        self.ctx.hc.set_status("t182", "working", status_ms=int((self.base_ts + 20) * 1000))
        with open(tp, "a", encoding="utf-8") as f:
            f.write(json.dumps({"step_index": 6, "type": "SYSTEM_MESSAGE", "source": "SYSTEM", "status": "DONE",
                                "created_at": _utc_iso(self.base_ts, 20), "content": "timer fired"}) + "\n")
            f.write(json.dumps({"step_index": 7, "type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE",
                                "created_at": _utc_iso(self.base_ts, 21),
                                "tool_calls": [{"id": "tc2", "name": "read_file", "args": {"Path": "/tmp/a"}}],
                                "content": ""}) + "\n")
        watcher.sync(self.repo)
        st_self = tracker.read()
        self.assertEqual(st_self["phase"], "working")
        self.assertEqual(st_self["cause"], "self")
        self.assertEqual(st_self["activity"]["tool"], "read_file")

        # Even if file phase fell back to `idle` while terminal is still `working`, a new tool call restores `working`.
        tracker.end_turn()
        self.assertEqual(tracker.read()["phase"], "idle")
        with open(tp, "a", encoding="utf-8") as f:
            f.write(json.dumps({"step_index": 8, "type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE",
                                "created_at": _utc_iso(self.base_ts, 25),
                                "tool_calls": [{"id": "tc3", "name": "run_command", "args": {"toolSummary": "pytest"}}],
                                "content": ""}) + "\n")
        watcher.sync(self.repo)
        self.assertEqual(tracker.read()["phase"], "working")
        self.assertEqual(tracker.read()["activity"]["tool"], "run_command")

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

    def test_live_transcript_activity_interrupt_outcome_and_bg_work_policy(self) -> None:
        rec = self._register_pm(agent="claude", terminal="t182")
        tr_dir = self.ctx.agents.claude_projects / re.sub(r"[^A-Za-z0-9]", "-", str(self.repo))
        tr_dir.mkdir(parents=True)
        tr_path = tr_dir / "sess-1.jsonl"
        # FS-11: write `agent_session.path` (real production key) AND plant a stale `agy-transcript.json`
        # to prove Claude never reads a leftover agy transcript.
        stale_agy = self.agy_dir / "brain" / "stale-agy" / ".system_generated" / "logs" / "transcript_full.jsonl"
        stale_agy.parent.mkdir(parents=True)
        stale_agy.write_text(json.dumps({"type": "USER_INPUT", "content": "old agy"}) + "\n", encoding="utf-8")
        proj_dir = self.ctx.home.project(self.slug).ensure()
        (proj_dir / "agy-transcript.json").write_text(
            json.dumps({"session": {"id": "stale-agy"}, "cursors": {"stale-agy": {"path": str(stale_agy)}}}),
            encoding="utf-8",
        )
        rec["agent_session"] = {"kind": "claude", "id": "sess-1", "path": str(tr_path)}
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
        self.assertEqual(probe["activity"]["kind"], "tool")
        self.assertEqual(probe["activity"]["tool"], "Bash")
        self.assertIn("run_checks.py", probe["activity"]["summary"])

        tracker = TurnTracker(self.ctx, self.repo)
        tracker.begin_turn(terminal="t182", agent_kind="claude", cause="user", from_hook=True)
        self.ctx.hc.set_status("t182", "working", status_ms=int(self.base_ts * 1000))

        # While the long command is actively updating or progressing (step finishes -> tool_result written),
        # FS-6 ensures finished tools are NOT shown as the active tool, and fresh transcript progress is not stalled.
        self.clock.advance(40)
        snap_active = tracker.live_snapshot(rec, term_info=self.ctx.hc.get_raw("t182"))
        self.assertEqual(snap_active["phase"], "working")
        self.assertFalse(snap_active["slow"])
        self.assertFalse(snap_active["stalled"])
        self.assertIn("run_checks.py", snap_active["activity"]["summary"])

        # Tool finishes -> tool_result arrives; activity drops the finished tool name (FS-6).
        self.clock.advance(60)
        with open(tr_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"}]},
            }) + "\n")
        os.utime(tr_path, (self.clock.time(), self.clock.time()))
        probe_after = probe_transcript_activity(tr_path, "claude")
        self.assertEqual(probe_after["activity"]["kind"], "thinking")
        self.assertEqual(probe_after["activity"]["tool"], "")
        self.assertEqual(probe_after["activity"]["summary"], "")
        snap_after = tracker.live_snapshot(rec, term_info=self.ctx.hc.get_raw("t182"))
        self.assertFalse(snap_after["slow"])
        self.assertFalse(snap_after["stalled"])
        self.assertEqual(snap_after["activity"]["tool"], "")

        # RS-1: `pm.py project interrupt` returns and records `hc interrupt`'s `outcome` (still_working vs stopped).
        interrupted: list[str] = []
        self.ctx.hc.interrupt = lambda term, **kw: (interrupted.append(term) or {"ok": True, "outcome": "still_working"})  # type: ignore[method-assign]
        self.ctx.out.clear()
        cli.main(["project", "interrupt", self.slug], ctx=self.ctx)
        int_res = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertTrue(int_res["ok"])
        self.assertEqual(int_res["outcome"], "still_working")
        self.assertEqual(interrupted, ["t182"])
        self.assertEqual(tracker.read()["interrupt_outcome"], "still_working")
        self.assertEqual(tracker.read()["phase"], "working")

        self.ctx.hc.interrupt = lambda term, **kw: (interrupted.append(term) or {"ok": True, "outcome": "stopped"})  # type: ignore[method-assign]
        self.ctx.out.clear()
        cli.main(["project", "interrupt", self.slug], ctx=self.ctx)
        int_res2 = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertEqual(int_res2["outcome"], "stopped")
        self.assertEqual(tracker.read()["interrupt_outcome"], "stopped")
        self.assertEqual(tracker.read()["phase"], "idle")

        # Background child process readiness works even without English "shells still running" text.
        self.assertEqual(
            manager_ready_for_batch({"status": {"state": "working", "msg": ""}}, True, bg_work=True),
            (True, False),
        )
        self.assertEqual(
            manager_ready_for_batch({"status": {"state": "working", "msg": ""}}, False, bg_work=True),
            (False, False),
        )

    def test_section_1_4_idle_10_min_deliver_batch_delayed_user_input_never_stalls(self) -> None:
        """§1.4 regression: idle 10 min -> deliver batch -> terminal working -> USER_INPUT appears 5s later.
        Must produce zero `stalled` transitions and zero `pm-stall` conversation events."""
        rec = self._register_pm(agent="agy", terminal="t182")
        tp = self.agy_dir / "brain" / "conv-14" / ".system_generated" / "logs" / "transcript_full.jsonl"
        tp.parent.mkdir(parents=True)
        with open(tp, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT", "status": "DONE",
                "created_at": _utc_iso(self.base_ts, 0),
                "content": f"<USER_REQUEST>先看一下 {self.repo}</USER_REQUEST>",
            }, ensure_ascii=False) + "\n")
            f.write(json.dumps({
                "step_index": 1, "type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE",
                "created_at": _utc_iso(self.base_ts, 5),
                "content": "看完了。",
            }, ensure_ascii=False) + "\n")
        os.utime(tp, (self.base_ts + 5, self.base_ts + 5))

        watcher = AgyTranscriptWatcher(self.ctx, agy_dir=self.agy_dir)
        self.clock.advance(5)
        watcher.sync(self.repo)
        self.ctx.hc.set_status("t182", "idle", status_ms=int(self.clock.time() * 1000))
        tracker = TurnTracker(self.ctx, self.repo)
        self.assertEqual(tracker.read()["phase"], "idle")

        # Idle for 10 minutes (> HARD_STALL_MS = 300s).
        self.clock.advance(600)

        # Worker report arrives (wake=True) and Deliverer sends batch to PM.
        Conversation(self.ctx, self.repo).record(
            "event", by="hc:t9", source="session", wake=True, text="task #99 ready for review",
        )
        orig_send = self.ctx.hc.send

        def _send_and_start_working(term: str, text: str, **kw):
            res = orig_send(term, text, **kw)
            # Terminal immediately reports `working` with status_ms = now.
            self.ctx.hc.set_status(term, "working", status_ms=int(self.clock.time() * 1000))
            return res

        self.ctx.hc.send = _send_and_start_working  # type: ignore[method-assign]
        d = Deliverer(self.ctx, self.repo, watchers=(watcher,), holds=(), settle=0)
        changes = type("C", (), {"terminals": set(), "files": []})()
        self.assertEqual(d.look(changes, {}, {}), 0)

        # Immediately after batch send, a provisional deliver turn is registered.
        st_after_send = tracker.read()
        self.assertEqual(st_after_send["phase"], "working")
        self.assertEqual(st_after_send["cause"], "deliver")
        seq_after_send = st_after_send["turn_seq"]

        # 2s and 4s later (before agy flushes USER_INPUT at +5s): look & live_snapshot must NOT report stalled!
        for dt in (2, 2):
            self.clock.advance(dt)
            d.look(changes, {}, {})
            snap = tracker.live_snapshot(rec, term_info=self.ctx.hc.get_raw("t182"))
            self.assertEqual(snap["phase"], "working")
            self.assertFalse(snap["stalled"])
            self.assertFalse(snap["slow"])
            self.assertLess(snap["idle_for_ms"], 10_000)

        # Also verify the direct-terminal-typing variant (file phase idle while terminal transitions to working):
        # even if file phase were still idle after 10 min, re-anchoring to status_ms prevents false stall!
        self.clock.advance(1)
        batch_text = self.ctx.hc.sent[-1][1]
        with open(tp, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 2, "type": "USER_INPUT", "source": "USER_EXPLICIT", "status": "DONE",
                "created_at": _utc_iso(self.clock.time(), 0),
                "content": f"<USER_REQUEST>{batch_text}</USER_REQUEST>",
            }, ensure_ascii=False) + "\n")
        os.utime(tp, (self.clock.time(), self.clock.time()))
        d.look(changes, {}, {})

        # FS-14: watcher's USER_INPUT merges into the provisional deliver turn instead of double-incrementing turn_seq.
        self.assertEqual(tracker.read()["turn_seq"], seq_after_send)
        snap_post = tracker.live_snapshot(rec, term_info=self.ctx.hc.get_raw("t182"))
        self.assertEqual(snap_post["phase"], "working")
        self.assertFalse(snap_post["stalled"])

        # Zero pm-stall events in conversation.jsonl!
        events = Conversation(self.ctx, self.repo).events()
        self.assertEqual([e for e in events if e.get("source") == "pm-stall"], [])

    def test_reanchor_from_idle_and_non_sticky_stalled_and_paused_conversation_stall(self) -> None:
        """FS-1 & FS-2: direct terminal working while file is idle re-anchors to status_ms;
        `phase == 'stalled'` is no longer sticky; hard stalls log to pm-stall.log, not conversation.jsonl."""
        rec = self._register_pm(agent="agy", terminal="t182")
        tracker = TurnTracker(self.ctx, self.repo)
        tracker.begin_turn(terminal="t182", agent_kind="agy", cause="user", from_hook=True)
        tracker.end_turn()
        self.assertEqual(tracker.read()["phase"], "idle")

        # 10 minutes pass; user types directly into terminal -> terminal becomes working with fresh status_ms.
        self.clock.advance(600)
        work_ms = int(self.clock.time() * 1000)
        self.ctx.hc.set_status("t182", "working", status_ms=work_ms)
        self.clock.advance(3)
        snap = tracker.live_snapshot(rec, term_info=self.ctx.hc.get_raw("t182"))
        self.assertEqual(snap["phase"], "working")
        self.assertFalse(snap["stalled"])
        self.assertEqual(snap["started_ms"], work_ms)
        self.assertEqual(snap["idle_for_ms"], 3000)

        # Even if `drain_outbox_and_check_stall` runs while file phase is `idle`, it must NOT record a stall.
        tracker.drain_outbox_and_check_stall("t182", self.ctx.hc.get_raw("t182"))
        self.assertEqual(tracker.read()["phase"], "idle")
        self.assertFalse(self.ctx.home.pm_stall_log.exists())

        # Now start a legitimate working turn and let HARD_STALL_MS elapse with zero progress:
        # internal state marks stalled + writes pm-stall.log, NEVER writes pm-stall to conversation.jsonl!
        tracker.begin_turn(terminal="t182", agent_kind="agy", cause="user", terminal_turn=1, from_hook=True)
        self.ctx.hc.set_status("t182", "working", status_ms=int(self.clock.time() * 1000))
        self.clock.advance(HARD_STALL_MS / 1000 + 10)
        tracker.drain_outbox_and_check_stall("t182", self.ctx.hc.get_raw("t182"))
        self.assertEqual(tracker.read()["phase"], "stalled")
        self.assertTrue(self.ctx.home.pm_stall_log.is_file())
        self.assertIn("hc:t182", self.ctx.home.pm_stall_log.read_text(encoding="utf-8"))
        self.assertEqual([e for e in Conversation(self.ctx, self.repo).events() if e.get("source") == "pm-stall"], [])

        # FS-2: Non-sticky stalled — when a new turn's status_ms advances, live_snapshot immediately clears stalled!
        self.clock.advance(5)
        self.ctx.hc.set_status("t182", "working", status_ms=int(self.clock.time() * 1000))
        snap_recovered = tracker.live_snapshot(rec, term_info=self.ctx.hc.get_raw("t182"))
        self.assertEqual(snap_recovered["phase"], "working")
        self.assertFalse(snap_recovered["stalled"])

    def test_background_work_call_sites_pass_terminal_info_dict_not_int(self) -> None:
        """FS-12: Both `TurnTracker.live_snapshot` and `Deliverer.look` must pass the terminal info dict to `background_work`."""
        rec = self._register_pm(agent="agy", terminal="t182")
        self.ctx.hc.terminals["t182"]["pid"] = 4200
        self.ctx.hc.terminals["t182"]["foreground"] = {"pid": 4201, "argv": ["agy"]}
        self.ctx.hc.set_status("t182", "working", status_ms=int(self.base_ts * 1000))

        seen_args: list[object] = []

        def spy_bg(info):
            seen_args.append(info)
            return ["sleep 60"] if isinstance(info, dict) and (info.get("pid") or info.get("foreground")) else []

        self.ctx.procs._background_work = spy_bg

        # 1) TurnTracker.live_snapshot passes full term_info dict -> detects bg_shells=1 -> phase=idle.
        tracker = TurnTracker(self.ctx, self.repo)
        snap = tracker.live_snapshot(rec, term_info=self.ctx.hc.get_raw("t182"))
        self.assertEqual(snap["phase"], "idle")
        self.assertEqual(snap["bg_shells"], 1)
        self.assertTrue(seen_args and isinstance(seen_args[-1], dict))
        self.assertEqual(seen_args[-1].get("pid"), 4200)

        # 2) Deliverer.look passes full info dict -> recognizes background work and delivers batch without --if idle.
        tracker.begin_turn(terminal="t182", agent_kind="agy", cause="user", from_hook=True)
        tracker.end_turn()
        seen_args.clear()
        Conversation(self.ctx, self.repo).record("event", by="ci", source="external:ci", wake=True, text="bg wake")
        d = Deliverer(self.ctx, self.repo, watchers=(), holds=(), settle=0)
        self.assertEqual(d.look(type("C", (), {"terminals": set(), "files": []})(), {}, {}), 0)
        self.assertTrue(seen_args and all(isinstance(x, dict) for x in seen_args))
        self.assertEqual(len(self.ctx.hc.sent), 1)

    def test_project_events_and_state_share_identical_turn_snapshot_and_missing_term_info_path(self) -> None:
        """FS-3: `project events` and `pm.py state` both use `hc get` and report the exact same phase;
        missing terminal info path degrades cleanly without crashing or falsely stalling."""
        rec = self._register_pm(agent="claude", terminal="t182")
        self.ctx.hc.terminals["t182"]["pid"] = 5100
        self.ctx.hc.set_status("t182", "working", msg="1 shell still running", status_ms=int(self.base_ts * 1000))

        # Both endpoints see `status.msg == "1 shell still running"` via `hc get` -> both report phase="idle", bg_shells=1!
        state_out = dash_state(self.ctx)
        self.ctx.out.clear()
        cli.main(["project", "events", self.slug], ctx=self.ctx)
        ev_out = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertEqual(state_out["pms"][0]["turn"]["phase"], "idle")
        self.assertEqual(state_out["pms"][0]["turn"]["bg_shells"], 1)
        self.assertEqual(ev_out["turn"]["phase"], state_out["pms"][0]["turn"]["phase"])
        self.assertEqual(ev_out["turn"]["bg_shells"], state_out["pms"][0]["turn"]["bg_shells"])

        # Switch terminal to active foreground working with fresh status_ms after 10 min idle:
        self.clock.advance(600)
        work_ms = int(self.clock.time() * 1000)
        self.ctx.hc.set_status("t182", "working", msg="", status_ms=work_ms)
        state_out2 = dash_state(self.ctx)
        self.ctx.out.clear()
        cli.main(["project", "events", self.slug], ctx=self.ctx)
        ev_out2 = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertEqual(state_out2["pms"][0]["turn"]["phase"], "working")
        self.assertEqual(ev_out2["turn"]["phase"], "working")
        self.assertEqual(ev_out2["turn"]["started_ms"], work_ms)
        self.assertEqual(state_out2["pms"][0]["turn"]["started_ms"], work_ms)

        # Missing terminal info path (`term_info=None, live_pm=None`) returns idle cleanly with no crash.
        tracker = TurnTracker(self.ctx, self.repo)
        missing_snap = tracker.live_snapshot(rec, None, term_info=None)
        self.assertEqual(missing_snap["phase"], "idle")

    def test_hook_to_pm_turn_mapping_and_late_stop_turn_number_matching(self) -> None:
        """FS-9 & FS-14: hooks map UserPromptSubmit/Stop to pm-turn.json and match turn number on Stop so a late Stop
        cannot close a newer turn or steal its cause."""
        import io
        from unittest import mock
        from pmlib.caller import Caller

        rec = self._register_pm(agent="claude", terminal="t182")
        self.ctx.pane = "hc:t182"
        self.ctx.hc_terminal = "t182"
        self.ctx.caller = Caller(self.ctx)
        tr_path = self.root / "claude-sess.jsonl"
        tr_path.write_text("", encoding="utf-8")

        def run_hook(payload: dict) -> None:
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                hooks.cmd_hook_turn(None, ctx=self.ctx)

        tracker = TurnTracker(self.ctx, self.repo)
        # 1) Deliverer opens provisional deliver turn, then UserPromptSubmit(batch) merges into same turn_seq (FS-14).
        Conversation(self.ctx, self.repo).record("event", by="hc:t9", source="session", wake=True, text="worker done")
        ev_size = self.ctx.home.project(self.slug).conversation.stat().st_size
        seq_prov = tracker.begin_turn(terminal="t182", agent_kind="claude", cause="deliver", batch=[0, ev_size], from_hook=False)
        run_hook({
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.repo),
            "session_id": "sess-A",
            "transcript_path": str(tr_path),
            "prompt": f"[from pm.py deliver] 1 event(s) (0-{ev_size})\n1. worker done",
        })
        st1 = tracker.read()
        self.assertEqual(st1["turn_seq"], seq_prov)
        self.assertEqual(st1["phase"], "working")
        self.assertEqual(st1["cause"], "deliver")
        self.assertTrue(st1["hook_confirmed"])
        self.assertEqual(st1["session_turns"].get("sess-A"), seq_prov)

        # 2) Turn 2 (user) starts in transcript & hook BEFORE Turn 1's late async Stop arrives!
        with open(tr_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "batch"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "handled batch"}]}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"content": "新问题"}}) + "\n")
        run_hook({
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.repo),
            "session_id": "sess-A",
            "transcript_path": str(tr_path),
            "prompt": "新问题",
        })
        st2 = tracker.read()
        self.assertEqual(st2["turn_seq"], seq_prov + 1)
        self.assertEqual(st2["cause"], "user")

        # Turn 1's late Stop runs now: detects newer prompt in transcript -> closes seq_prov (Turn 1) only,
        # preserves Turn 2 as working, and attaches after="deliver" to Turn 1's reply!
        run_hook({
            "hook_event_name": "Stop",
            "cwd": str(self.repo),
            "session_id": "sess-A",
            "transcript_path": str(tr_path),
            "last_assistant_message": "已处理完这批汇报。",
        })
        self.assertEqual(tracker.read()["phase"], "working")
        self.assertEqual(tracker.read()["turn_seq"], seq_prov + 1)
        pm_replies = [e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "pm"]
        self.assertEqual(pm_replies[-1]["text"], "已处理完这批汇报。")
        self.assertEqual(pm_replies[-1].get("after"), "deliver")

        # Turn 2 finishes in transcript -> Stop closes Turn 2 cleanly to idle with no after="deliver".
        with open(tr_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "回答新问题"}]}}) + "\n")
        run_hook({
            "hook_event_name": "Stop",
            "cwd": str(self.repo),
            "session_id": "sess-A",
            "transcript_path": str(tr_path),
            "last_assistant_message": "回答新问题",
        })
        self.assertEqual(tracker.read()["phase"], "idle")
        pm_replies2 = [e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "pm"]
        self.assertEqual(pm_replies2[-1]["text"], "回答新问题")
        self.assertNotIn("after", pm_replies2[-1])

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
            "pm-turn-journal.jsonl", "pm-turn-journal.1.jsonl", "pm-turn.beat",
        ):
            self.assertIn(shared_internal, INTERNAL_PROJECT_FILES)
            self.assertIn(shared_internal, js_files)


class Phase5LegacyCleanupCompatTests(unittest.TestCase):
    """Phase 5 (§4.6 & §4.8): legacy artifact removal with 1-version read-only compatibility."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-p5-legacy-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "demo"
        self.repo.mkdir()
        self.clock = FakeClock("2026-11-26 15:00:00")
        self.ctx = make_ctx(self.root / "ledger", clock=self.clock)
        self.slug = project_slug(self.repo)
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.ctx.home.registration(self.slug).write_text(json.dumps({
            "name": f"pm-{self.slug}",
            "project": "demo",
            "repo": str(self.repo),
            "runtime": "hc",
            "terminal": "t12",
            "pane": "hc:t12",
            "agent": "claude",
        }), encoding="utf-8")

    def test_v1_pm_turn_upgrade_and_v1_projection_drop_stall_logged_seq(self) -> None:
        from pmlib.project.turn_reducer import project_v1_turn, upgrade_state_v1_to_v2

        now_ms = int(self.clock.time() * 1000)
        v1 = {
            "version": 1,
            "terminal": "t12",
            "agent_kind": "claude",
            "turn_seq": 7,
            "terminal_turn": 4,
            "phase": "stalled",
            "cause": "user",
            "started_ms": now_ms - 12_000,
            "last_activity_ms": now_ms - 5_000,
            "stall_logged_seq": 7,
            "outbox": [{"msg_id": "m-old", "text": "hello", "queued_ms": now_ms - 3_000}],
        }
        v2 = upgrade_state_v1_to_v2(v1)
        self.assertEqual(v2["version"], 2)
        self.assertNotIn("stall_logged_seq", v2)
        self.assertEqual(v2["turn"]["phase"], "generating")
        self.assertEqual(v2["turn"]["health"], "ok")
        self.assertEqual(v2["inbox"][0]["id"], "m-old")

        proj = project_v1_turn(v2, now_ms, supervised=True)
        self.assertEqual(proj["phase"], "working")
        self.assertEqual(proj["turn_seq"], 7)
        self.assertEqual(proj["queued_count"], 1)

    def test_deliver_and_hooks_never_write_legacy_turn_cause_receipts_or_turns_log(self) -> None:
        from pmlib import hooks
        import io
        from unittest import mock

        Conversation(self.ctx, self.repo).record("event", by="hc:t20", source="worker", text="status=review", wake=True)
        dlv = Delivery(self.ctx, self.repo, settle=0)
        start, end, items = dlv.pending_batch()
        batch_text = dlv.batch_text(start, end, items)
        dlv.took_delivery(batch_text)

        proj = self.ctx.home.project_for(self.repo)
        self.assertFalse(proj.turn_cause.exists())
        self.assertFalse(proj.receipts.exists())
        self.assertFalse(self.ctx.home.turn_log.exists())

        ctx_hook = make_ctx(self.root / "ledger", pane="hc:t12", clock=self.clock)
        ctx_hook.hc_terminal = "t12"
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.repo),
            "session_id": "s-1",
            "prompt": batch_text,
        }))):
            hooks.cmd_hook_turn(None, ctx=ctx_hook)
        self.assertFalse(proj.turn_cause.exists())
        self.assertFalse(proj.receipts.exists())
        self.assertFalse(self.ctx.home.turn_log.exists())
        # Conversation.turn_cause() reads the active deliver cause from pm-turn.json without turn-cause.json.
        self.assertEqual(Conversation(self.ctx, self.repo).turn_cause(), {"after": "deliver", "batch": [start, end]})

    def test_turn_cause_falls_back_read_only_when_pm_turn_absent_and_deliverer_ignores_turns_log_when_v2_present(self) -> None:
        proj = self.ctx.home.project_for(self.repo)
        proj.ensure()
        proj.turn_cause.write_text(json.dumps({"after": "deliver", "batch": [0, 42]}), encoding="utf-8")
        self.assertEqual(Conversation(self.ctx, self.repo).turn_cause(), {"after": "deliver", "batch": [0, 42]})

        # When pm-turn.json has an active turn (`working`), Deliverer does NOT fall back to turns.log.
        tracker = TurnTracker(self.ctx, self.repo)
        tracker.begin_turn(terminal="t12", agent_kind="claude", cause="user", from_hook=True)
        self.ctx.home.turn_log.write_text("2026-11-26 15:00 [hc:t12] Stop: turn\n", encoding="utf-8")
        self.ctx.hc.set_status("t12", "working", msg="1 shell still running")
        Conversation(self.ctx, self.repo).record("event", by="ci", text="done", source="external:ci", wake=True)
        from fakes import FakeChangeWaiter
        dlv = Deliverer(self.ctx, self.repo, watchers=(), holds=(), settle=0)
        dlv.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(self.ctx.hc.sent, [])

    def test_state_and_events_project_compat_receipts_from_pm_mailbox_without_receipts_json(self) -> None:
        from pmlib.messaging.envelope import P1_USER, Envelope
        from pmlib.messaging.principal import Principal
        from pmlib.messaging.address import LogicalAddress
        from pmlib.project.readmodel import Projects
        from pmlib.views.state import dash_state

        tracker = TurnTracker(self.ctx, self.repo)
        now_ms = int(self.clock.time() * 1000)
        env = Envelope(
            env_id="env_u501",
            idempotency_key="user:u501",
            schema_version=1,
            created_ms=now_ms,
            kind="chat.user",
            sender=Principal.user(),
            recipient=LogicalAddress.pm(self.slug),
            project=self.slug,
            cause={"kind": "user", "msg_id": "u501"},
            priority=P1_USER,
            body={"text": "confirm via mailbox", "msg_id": "u501"},
            require_reply=True,
        )
        tracker.pm_mailbox.enqueue(env, initial_state="accepted", now_ms=now_ms, target_endpoint_uid="hc:local:t12")
        tracker.pm_mailbox.transition(env.env_id, "typed", now_ms=now_ms + 50, target_endpoint_uid="hc:local:t12")
        tracker.pm_mailbox.transition(env.env_id, "consumed", now_ms=now_ms + 100, turn_id="t:1")

        # No legacy receipts.json exists on disk, yet 1-version compat projection exposes it for unupgraded clients.
        self.assertFalse(self.ctx.home.project_for(self.repo).receipts.exists())
        st = dash_state(self.ctx)
        self.assertEqual(st["pms"][0]["receipts"][0]["msg_id"], "u501")
        ev_out = Projects(self.ctx.store).events(self.slug)
        self.assertEqual(ev_out["receipts"][0]["msg_id"], "u501")


if __name__ == "__main__":
    unittest.main()
