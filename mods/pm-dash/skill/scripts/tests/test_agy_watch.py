"""Unit tests for `AgyTranscriptWatcher` (syncing `agy` PM user prompts and final replies to `conversation.jsonl`)."""
from __future__ import annotations

import datetime
import json
import nturl2path
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SCRIPTS / "tests") not in sys.path:
    sys.path.insert(0, str(SCRIPTS / "tests"))

from fakes import FakeChangeWaiter, FakeClock, FakeHc, make_ctx  # noqa: E402
from pmlib.context import Context, DeliverWatcher  # noqa: E402
from pmlib.events.agy_watch import (  # noqa: E402
    AGY_POLL_SECONDS,
    AgyTranscriptWatcher,
    _inspect_opening,
    _uri_to_path,
    extract_agy_user_text,
    parse_agy_row,
)
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.deliverer import Deliverer  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402


# Base UTC timestamp used by tests; local claimed & FakeClock derive from it so tests pass in any timezone.
BASE_UTC = datetime.datetime(2026, 11, 23, 16, 14, 0, tzinfo=datetime.timezone.utc)


def _utc_iso(offset_sec: int = 0) -> str:
    return (BASE_UTC + datetime.timedelta(seconds=offset_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_dt(offset_sec: int = 0) -> datetime.datetime:
    return (BASE_UTC + datetime.timedelta(seconds=offset_sec)).astimezone().replace(tzinfo=None)


def _local_claimed(offset_sec: int = 0) -> str:
    return _local_dt(offset_sec).strftime("%Y-%m-%d %H:%M")


def _clock_at(offset_sec: int = 30) -> FakeClock:
    return FakeClock(now=_local_dt(offset_sec))


def _register_pm(
    ctx,
    repo: str,
    *,
    agent: str = "agy",
    terminal: str = "t182",
    claimed: str | None = None,
    rotations: int | None = None,
) -> dict:
    slug = project_slug(repo)
    rec = {
        "name": f"pm-{slug}",
        "project": Path(repo).name,
        "repo": repo,
        "runtime": "hc",
        "terminal": terminal,
        "pane": f"hc:{terminal}",
        "agent": agent,
        "claimed": _local_claimed(0) if claimed is None else claimed,
    }
    if rotations is not None:
        rec["rotations"] = rotations
    ctx.home.registrations.mkdir(parents=True, exist_ok=True)
    ctx.home.registration(slug).write_text(json.dumps(rec), encoding="utf-8")
    return rec


def _user_row(step: int, text: str, at: str | None = None, *, wrapped: bool = True) -> dict:
    ts = _utc_iso(10 + step) if at is None else at
    body = (
        f"<USER_REQUEST>\n{text}\n</USER_REQUEST>\n"
        f"<ADDITIONAL_METADATA>\nThe current local time is: {ts}.\n</ADDITIONAL_METADATA>"
        if wrapped else text
    )
    return {
        "step_index": step,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": ts,
        "content": body,
    }


def _pm_row(
    step: int,
    text: str,
    at: str | None = None,
    *,
    tool_calls: list | None = None,
    status: str = "DONE",
) -> dict:
    ts = _utc_iso(10 + step) if at is None else at
    row = {
        "step_index": step,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "status": status,
        "created_at": ts,
        "model": "claude-opus-5-5-medium",
        "content": text,
    }
    if tool_calls is not None:
        row["tool_calls"] = tool_calls
    return row


def _append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_summary_db(
    agy_dir: Path,
    entries: list[tuple[str, list[str], str] | tuple[str, list[str], str, int, str]],
) -> None:
    agy_dir.mkdir(parents=True, exist_ok=True)
    db = agy_dir / "conversation_summaries.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE IF NOT EXISTS conversation_summaries ("
        "conversation_id TEXT PRIMARY KEY, "
        "workspace_uris TEXT NOT NULL, "
        "last_modified_time TEXT NOT NULL, "
        "app_data_dir TEXT NOT NULL DEFAULT 'antigravity-cli', "
        "nesting_depth INTEGER NOT NULL DEFAULT 0, "
        "parent_conversation_id TEXT NOT NULL DEFAULT '')"
    )
    for item in entries:
        if len(item) == 5:
            cid, uris, mtime, depth, parent = item
        else:
            cid, uris, mtime = item
            depth, parent = 0, ""
        con.execute(
            "INSERT OR REPLACE INTO conversation_summaries "
            "(conversation_id, workspace_uris, last_modified_time, app_data_dir, nesting_depth, parent_conversation_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, json.dumps(uris), mtime, "antigravity-cli", depth, parent),
        )
    con.commit()
    con.close()


class AgyTranscriptWatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())
        self.agy_dir = Path(self.tmp.name) / "agy"

    def _transcript_path(self, conv_id: str, *, full: bool = False) -> Path:
        name = "transcript_full.jsonl" if full else "transcript.jsonl"
        return self.agy_dir / "brain" / conv_id / ".system_generated" / "logs" / name

    def test_extract_and_parse_rows(self):
        self.assertEqual(
            extract_agy_user_text("<USER_REQUEST>\n换好了吗？\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nx\n</ADDITIONAL_METADATA>"),
            "换好了吗？",
        )
        # Unclosed <USER_REQUEST> (truncated compact transcript) still strips metadata cleanly.
        self.assertEqual(
            extract_agy_user_text("<USER_REQUEST>\n长问题正文\n<ADDITIONAL_METADATA>\ntime\n</ADDITIONAL_METADATA>"),
            "长问题正文",
        )
        self.assertEqual(parse_agy_row(_user_row(1, "你好", at="2026-11-23T16:14:26Z")), ("user_input", "你好", "2026-11-23T16:14:26Z"))
        self.assertEqual(parse_agy_row(_pm_row(2, "收到", at="2026-11-23T16:14:30Z")), ("pm", "收到", "2026-11-23T16:14:30Z"))
        # Intermediate tool-calling PLANNER_RESPONSE, SYSTEM_MESSAGE, GENERIC, and RUNNING rows are ignored.
        self.assertIsNone(parse_agy_row(_pm_row(3, "thinking...", tool_calls=[{"name": "run_command"}])))
        self.assertIsNone(parse_agy_row(_pm_row(4, "draft", status="RUNNING")))
        self.assertIsNone(parse_agy_row({"step_index": 5, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE", "content": "sys"}))
        self.assertIsNone(parse_agy_row({"step_index": 6, "source": "MODEL", "type": "GENERIC", "status": "DONE", "content": "tool out"}))

    def test_incremental_append_and_filter_rotate_deliver_and_dedup(self):
        ctx = make_ctx(self.tmp.name, clock=_clock_at(30), agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")
        conv_id = "conv-pm-1"
        tp = self._transcript_path(conv_id)
        _write_summary_db(self.agy_dir, [(conv_id, [f"file://{self.repo}"], "2026-11-23 16:15:00+00:00")])

        _append_rows(tp, [
            _user_row(0, "[from pm.py rotate] You are the PM of demo, taking over."),
            _pm_row(1, "Checking tools...", tool_calls=[{"name": "run_command"}]),
            {"step_index": 2, "source": "MODEL", "type": "GENERIC", "status": "DONE", "content": "tool output"},
            {"step_index": 3, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE", "content": "reminder"},
            _pm_row(4, "已接手 PM。"),
            _user_row(5, "换好了吗？"),
            _pm_row(6, "换好了，现在是 agy 当 PM。"),
            _user_row(7, "/compact"),
            _user_row(8, '<hc from="t10">worker ping</hc>'),
        ])

        watcher = AgyTranscriptWatcher(ctx)
        self.assertEqual(watcher.sync(self.repo), 4)

        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e.get("text")) for e in events], [
            ("pm", "已接手 PM。"),
            ("user", "换好了吗？"),
            ("pm", "换好了，现在是 agy 当 PM。"),
            ("agent", "worker ping"),
        ])
        self.assertEqual(events[0].get("by"), "hc:t182")
        self.assertEqual(events[3].get("by"), "hc:t10")

        # Syncing again with no new data writes nothing.
        self.assertEqual(watcher.sync(self.repo), 0)
        self.assertEqual(len(Conversation(ctx, self.repo).events()), 4)

        # Append a [from pm.py deliver] batch + PM reply, followed by a user turn.
        _append_rows(tp, [
            _user_row(9, "[from pm.py deliver] 1 event(s) (10-80)\n1. [worker hc:t9] #1 demo-fix: review\n   done"),
            _pm_row(10, "已收到审查汇报，正在处理。"),
            _user_row(11, "还有哪些活？"),
            _pm_row(12, "目前还剩 2 项。"),
        ])

        self.assertEqual(watcher.sync(self.repo), 3)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual(len(events), 7)
        # Deliver batch prompt is not logged; its PM reply carries after="deliver" & batch=[10, 80].
        self.assertEqual(events[4]["type"], "pm")
        self.assertEqual(events[4]["text"], "已收到审查汇报，正在处理。")
        self.assertEqual(events[4].get("after"), "deliver")
        self.assertEqual(events[4].get("batch"), [10, 80])
        self.assertEqual(Delivery(ctx, self.repo).received_ranges(), [[10, 80]])
        # Subsequent user turn clears turn_cause so its PM reply has no after="deliver".
        self.assertEqual(events[5]["type"], "user")
        self.assertEqual(events[5]["text"], "还有哪些活？")
        self.assertEqual(events[6]["type"], "pm")
        self.assertEqual(events[6]["text"], "目前还剩 2 项。")
        self.assertNotIn("after", events[6])

    def test_restart_resumes_from_persisted_cursor_and_waits_for_complete_line(self):
        ctx = make_ctx(self.tmp.name, clock=_clock_at(30), agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")
        tp = self._transcript_path("conv-restart")
        _append_rows(tp, [
            _user_row(0, f"[from pm.py rotate] You are the PM of the demo project ({self.repo})"),
            _user_row(1, "第一句"),
            _pm_row(2, "第一句回复"),
        ])

        # First watcher instance syncs and persists cursor.
        w1 = AgyTranscriptWatcher(ctx)
        self.assertEqual(w1.sync(self.repo), 2)
        self.assertTrue(ctx.home.project_for(self.repo).agy_transcript.is_file())

        # Write a half-written line (no trailing newline): must be ignored until complete.
        partial = json.dumps(_user_row(3, "第二句"), ensure_ascii=False)
        with open(tp, "a", encoding="utf-8") as f:
            f.write(partial[:20])

        # Simulate Deliverer restart with a brand-new watcher instance.
        w2 = AgyTranscriptWatcher(ctx)
        self.assertEqual(w2.sync(self.repo), 0)
        self.assertEqual(len(Conversation(ctx, self.repo).events()), 2)

        # Finish writing the line and append PM reply.
        with open(tp, "a", encoding="utf-8") as f:
            f.write(partial[20:] + "\n")
        _append_rows(tp, [_pm_row(4, "第二句回复")])

        self.assertEqual(w2.sync(self.repo), 2)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "第一句"),
            ("pm", "第一句回复"),
            ("user", "第二句"),
            ("pm", "第二句回复"),
        ])

    def test_rotation_switches_to_new_session_without_duplicating_old(self):
        clk = _clock_at(30)
        ctx = make_ctx(self.tmp.name, clock=clk, agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182", claimed=_local_claimed(0))
        tp1 = self._transcript_path("conv-old")
        _append_rows(tp1, [
            _user_row(0, "[from pm.py rotate] first", at=_utc_iso(5)),
            _user_row(1, "旧会话问题", at=_utc_iso(10)),
            _pm_row(2, "旧会话回复", at=_utc_iso(15)),
        ])
        _write_summary_db(self.agy_dir, [
            ("conv-old", [f"file://{self.repo}"], "2026-11-23 16:14:15+00:00"),
        ])

        w = AgyTranscriptWatcher(ctx)
        self.assertEqual(w.sync(self.repo), 2)

        # Rotate PM 1 hour later: during startup gap before conv-new exists, old sessions must NOT be bound.
        clk.advance(3600)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182", claimed=_local_claimed(3600))
        # Even if another old session exists in the same repo from 30 min ago, claimed floor rejects it.
        tp_stale = self._transcript_path("conv-stale-same-repo")
        _append_rows(tp_stale, [
            _user_row(0, "半小时前的旧会话", at=_utc_iso(1800)),
            _pm_row(1, "半小时前的回复", at=_utc_iso(1805)),
        ])
        _write_summary_db(self.agy_dir, [
            ("conv-old", [f"file://{self.repo}"], "2026-11-23 16:14:15+00:00"),
            ("conv-stale-same-repo", [f"file://{self.repo}"], "2026-11-23 16:44:05+00:00"),
        ])
        self.assertEqual(w.sync(self.repo), 0)
        self.assertEqual(len(Conversation(ctx, self.repo).events()), 2)

        # New agy session starts after claimed -> discovered and synced from step 0.
        tp2 = self._transcript_path("conv-new", full=True)
        _append_rows(tp2, [
            _user_row(0, "[from pm.py rotate] second", at=_utc_iso(3605)),
            _user_row(1, "新会话问题", at=_utc_iso(3610)),
            _pm_row(2, "新会话回复", at=_utc_iso(3615)),
        ])
        _write_summary_db(self.agy_dir, [
            ("conv-old", [f"file://{self.repo}"], "2026-11-23 16:14:15+00:00"),
            ("conv-stale-same-repo", [f"file://{self.repo}"], "2026-11-23 16:44:05+00:00"),
            ("conv-new", [f"file://{self.repo}"], "2026-11-23 17:14:15+00:00"),
        ])

        self.assertEqual(w.sync(self.repo), 2)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "旧会话问题"),
            ("pm", "旧会话回复"),
            ("user", "新会话问题"),
            ("pm", "新会话回复"),
        ])

    def test_large_opening_line_helpers_and_subagents_are_excluded(self):
        ctx = make_ctx(self.tmp.name, clock=_clock_at(30), agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")

        # 35KB worker/helper step-0 line (exceeds old 16KB cap) must NOT fall back to score=1.
        huge_memory = "memory entry " * 3000  # ~39KB
        tp_huge_worker = self._transcript_path("conv-huge-worker")
        _append_rows(tp_huge_worker, [
            _user_row(0, f'<hc from="t182"># 任务书：实现某功能\n## Memory\n{huge_memory}', at=_utc_iso(5)),
        ])
        self.assertEqual(_inspect_opening(tp_huge_worker)[0], 0)

        tp_exec_helper_en = self._transcript_path("conv-exec-en")
        _append_rows(tp_exec_helper_en, [
            _user_row(0, f"[Execution Helper merge-1 for pm-demo]\n\n{huge_memory}", at=_utc_iso(6)),
        ])
        self.assertEqual(_inspect_opening(tp_exec_helper_en)[0], 0)

        tp_exec_helper_zh = self._transcript_path("conv-exec-zh")
        _append_rows(tp_exec_helper_zh, [
            _user_row(0, f"【执行 helper merge-2，归属 pm-demo】\n\n{huge_memory}", at=_utc_iso(7)),
        ])
        self.assertEqual(_inspect_opening(tp_exec_helper_zh)[0], 0)

        # Chinese reporting footer without a standard `# 任务书` header must still be classified as worker brief.
        tp_zh_worker_footer = self._transcript_path("conv-zh-footer")
        _append_rows(tp_zh_worker_footer, [
            _user_row(0, '<hc from="t182">请帮我修一个小 bug。\n\n汇报（任务 #99 demo-zh）：\n- 做完时报 review</hc>', at=_utc_iso(7)),
        ])
        self.assertEqual(_inspect_opening(tp_zh_worker_footer)[0], 0)

        # Subagent in DB (nesting_depth=1, parent_conversation_id set) must be excluded even with normal text.
        tp_subagent = self._transcript_path("conv-subagent")
        _append_rows(tp_subagent, [
            _user_row(0, "subagent prompt", at=_utc_iso(8)),
            _pm_row(1, "subagent reply", at=_utc_iso(9)),
        ])

        tp_pm = self._transcript_path("conv-real-pm", full=True)
        _append_rows(tp_pm, [
            _user_row(0, "真 PM 的第一句", at=_utc_iso(2)),
            _pm_row(1, "真 PM 的回复", at=_utc_iso(3)),
        ])

        _write_summary_db(self.agy_dir, [
            ("conv-huge-worker", [f"file://{self.repo}"], "2026-11-23 16:14:20+00:00", 0, ""),
            ("conv-exec-en", [f"file://{self.repo}"], "2026-11-23 16:14:19+00:00", 0, ""),
            ("conv-exec-zh", [f"file://{self.repo}"], "2026-11-23 16:14:18+00:00", 0, ""),
            ("conv-subagent", [f"file://{self.repo}"], "2026-11-23 16:14:17+00:00", 1, "conv-real-pm"),
            ("conv-real-pm", [f"file://{self.repo}"], "2026-11-23 16:14:03+00:00", 0, ""),
        ])

        w = AgyTranscriptWatcher(ctx)
        self.assertEqual(w.sync(self.repo), 2)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "真 PM 的第一句"),
            ("pm", "真 PM 的回复"),
        ])

    def test_sticky_binding_not_hijacked_by_newer_session_in_same_repo(self):
        ctx = make_ctx(self.tmp.name, clock=_clock_at(30), agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")
        tp_pm = self._transcript_path("conv-pm-sticky", full=True)
        _append_rows(tp_pm, [
            _user_row(0, "[from pm.py rotate] takeover", at=_utc_iso(2)),
            _user_row(1, "第一句", at=_utc_iso(5)),
            _pm_row(2, "第一句回复", at=_utc_iso(8)),
        ])
        _write_summary_db(self.agy_dir, [
            ("conv-pm-sticky", [f"file://{self.repo}"], "2026-11-23 16:14:08+00:00"),
        ])

        w = AgyTranscriptWatcher(ctx)
        self.assertEqual(w.sync(self.repo), 2)

        # A newer neutral agy session opens in the same repo while PM binding (pane, claimed) has not changed.
        tp_other = self._transcript_path("conv-side-session", full=True)
        _append_rows(tp_other, [
            _user_row(0, "旁路会话的话", at=_utc_iso(15)),
            _pm_row(1, "旁路会话的回复", at=_utc_iso(18)),
        ])
        _write_summary_db(self.agy_dir, [
            ("conv-pm-sticky", [f"file://{self.repo}"], "2026-11-23 16:14:08+00:00"),
            ("conv-side-session", [f"file://{self.repo}"], "2026-11-23 16:14:18+00:00"),
        ])

        # Append a new turn to the bound PM session; watcher must stay on conv-pm-sticky.
        _append_rows(tp_pm, [
            _user_row(3, "第二句", at=_utc_iso(20)),
            _pm_row(4, "第二句回复", at=_utc_iso(22)),
        ])
        self.assertEqual(w.sync(self.repo), 2)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "第一句"),
            ("pm", "第一句回复"),
            ("user", "第二句"),
            ("pm", "第二句回复"),
        ])

    def test_fs_fallback_without_db_requires_repo_verification(self):
        ctx = make_ctx(self.tmp.name, clock=_clock_at(30), agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")

        # No conversation_summaries.db: a session from another project must NOT be bound.
        tp_other = self._transcript_path("conv-other-proj")
        _append_rows(tp_other, [
            _user_row(0, "[from pm.py rotate] You are the PM of the otherproj project", at=_utc_iso(5)),
            _user_row(1, "别的项目的话", at=_utc_iso(8)),
        ])
        w = AgyTranscriptWatcher(ctx)
        self.assertEqual(w.sync(self.repo), 0)
        self.assertEqual(Conversation(ctx, self.repo).events(), [])

        # A session whose opening references this repo/project IS bound cleanly.
        tp_mine = self._transcript_path("conv-this-proj")
        _append_rows(tp_mine, [
            _user_row(0, f"[from pm.py rotate] You are the PM of the demo project ({self.repo})", at=_utc_iso(10)),
            _user_row(1, "本项目的话", at=_utc_iso(12)),
            _pm_row(2, "本项目的回复", at=_utc_iso(14)),
        ])
        self.assertEqual(w.sync(self.repo), 2)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "本项目的话"),
            ("pm", "本项目的回复"),
        ])

    def test_first_attach_to_historical_session_seeds_at_eof_without_replaying(self):
        # Simulate upgrading dudu onto an agy PM that has already been running for 3 hours (no agy-transcript.json yet).
        clk = _clock_at(3 * 3600)
        ctx = make_ctx(self.tmp.name, clock=clk, agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182", claimed=_local_claimed(0))
        tp = self._transcript_path("conv-long-running", full=True)
        _append_rows(tp, [
            _user_row(0, "[from pm.py rotate] old takeover", at=_utc_iso(5)),
            _user_row(1, "三小时前的旧问题", at=_utc_iso(60)),
            _pm_row(2, "三小时前的旧回复", at=_utc_iso(65)),
        ])
        _write_summary_db(self.agy_dir, [
            ("conv-long-running", [f"file://{self.repo}"], "2026-11-23 19:14:00+00:00"),
        ])

        w = AgyTranscriptWatcher(ctx)
        # First sync seeds at EOF (step 2) without replaying historical turns or writing legacy receipts.
        self.assertEqual(w.sync(self.repo), 0)
        self.assertEqual(Conversation(ctx, self.repo).events(), [])
        self.assertFalse(ctx.home.project_for(self.repo).receipts.exists())

        # New turns appended afterwards ARE recorded incrementally without creating legacy receipts.json.
        _append_rows(tp, [
            _user_row(3, "升级后的新问题", at=_utc_iso(3 * 3600 + 5)),
            _pm_row(4, "升级后的新回复", at=_utc_iso(3 * 3600 + 10)),
        ])
        self.assertEqual(w.sync(self.repo), 2)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "升级后的新问题"),
            ("pm", "升级后的新回复"),
        ])
        self.assertFalse(ctx.home.project_for(self.repo).receipts.exists())

    def test_switching_compact_to_full_transcript_preserves_last_step(self):
        ctx = make_ctx(self.tmp.name, clock=_clock_at(30), agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")
        conv_id = "conv-upgrade-full"
        tp_compact = self._transcript_path(conv_id, full=False)
        initial_rows = [
            _user_row(0, "[from pm.py rotate] takeover", at=_utc_iso(2)),
            _user_row(1, "第一句", at=_utc_iso(5)),
            _pm_row(2, "第一句回复", at=_utc_iso(8)),
        ]
        _append_rows(tp_compact, initial_rows)
        _write_summary_db(self.agy_dir, [
            (conv_id, [f"file://{self.repo}"], "2026-11-23 16:14:08+00:00"),
        ])

        w = AgyTranscriptWatcher(ctx)
        self.assertEqual(w.sync(self.repo), 2)

        # Now transcript_full.jsonl appears for the exact same conversation_id with steps 0..4.
        tp_full = self._transcript_path(conv_id, full=True)
        _append_rows(tp_full, [
            *initial_rows,
            _user_row(3, "第二句", at=_utc_iso(12)),
            _pm_row(4, "第二句回复", at=_utc_iso(15)),
        ])

        # Cursor is keyed by conversation_id -> preserves last_step=2, records only steps 3..4 (zero duplicates).
        self.assertEqual(w.sync(self.repo), 2)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "第一句"),
            ("pm", "第一句回复"),
            ("user", "第二句"),
            ("pm", "第二句回复"),
        ])

    def test_uri_to_path_handles_windows_drive_uris(self):
        # POSIX URI
        self.assertEqual(_uri_to_path("file:///Users/me/my%20repo"), Path("/Users/me/my repo"))
        # Windows file:///C:/... URI via nturl2path.url2pathname (no leading slash before drive letter)
        with mock.patch("urllib.request.url2pathname", side_effect=nturl2path.url2pathname):
            got = _uri_to_path("file:///C:/Users/me/my%20repo")
            self.assertEqual(str(got), "C:\\Users\\me\\my repo")

    def test_claude_pm_is_unaffected(self):
        hc = FakeHc(terminals={"t7": {"state": "live", "status": {"state": "idle"}}})
        ctx = make_ctx(self.tmp.name, hc=hc, clock=_clock_at(30), agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="claude", terminal="t7")
        _append_rows(self._transcript_path("conv-any"), [_user_row(0, "should not be synced")])

        w = AgyTranscriptWatcher(ctx)
        self.assertIsNone(w.look(self.repo, {}, {}))
        self.assertEqual(hc.calls, [])  # fast-path: zero hc calls for non-agy PM
        self.assertEqual(Conversation(ctx, self.repo).events(), [])

    def test_deliverer_look_runs_agy_watcher_without_false_redelivery(self):
        clk = _clock_at(30)
        hc = FakeHc(terminals={"t182": {"state": "live", "status": {"state": "idle", "app": "antigravity"}}}, clock=clk)
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk, agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")
        _append_rows(self._transcript_path("conv-deliver"), [
            _user_row(0, f"[from pm.py rotate] You are the PM of the demo project ({self.repo})", at=_utc_iso(2)),
            _user_row(1, "进展如何？", at=_utc_iso(5)),
            _pm_row(2, "一切顺利。", at=_utc_iso(8)),
        ])

        watcher = DeliverWatcher(
            name="agy-transcript",
            look=lambda r, s, b: AgyTranscriptWatcher(ctx).look(r, s, b),
        )
        deliverer = Deliverer(ctx, self.repo, watchers=(watcher,), holds=(), settle=0)
        due = deliverer.look(FakeChangeWaiter(), {}, {})

        self.assertLessEqual(due, AGY_POLL_SECONDS)
        self.assertEqual(hc.sent, [])  # user/pm events must not trigger a delivery batch back to PM
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "进展如何？"),
            ("pm", "一切顺利。"),
        ])

    def test_user_input_records_receipt_and_poll_interval(self):
        self.assertEqual(AGY_POLL_SECONDS, 1.5)
        ctx = make_ctx(self.tmp.name, clock=_clock_at(30), agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")
        conv_id = "conv-receipt"
        tp = self._transcript_path(conv_id, full=True)
        user_ts = _utc_iso(15)
        _write_summary_db(self.agy_dir, [(conv_id, [f"file://{self.repo}"], "2026-11-23 16:15:00+00:00")])
        _append_rows(tp, [
            _user_row(0, "[from pm.py rotate] takeover", at=_utc_iso(5)),
            _user_row(1, "/compact", at=_utc_iso(8)),
            _user_row(2, '<hc from="t10">worker ping</hc>', at=_utc_iso(10)),
            _user_row(3, "[from pm.py deliver] 1 event(s) (1-20)\n1. [worker hc:t9] #1 fix: review\n   ok", at=_utc_iso(12)),
            _user_row(4, "帮我看看进度", at=user_ts),
            _pm_row(5, "一切正常。", at=_utc_iso(18)),
        ])

        w = AgyTranscriptWatcher(ctx)
        self.assertEqual(w.look(self.repo, {}, {}), 1.5)

        self.assertFalse(ctx.home.project_for(self.repo).receipts.exists())
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("agent", "worker ping"),
            ("user", "帮我看看进度"),
            ("pm", "一切正常。"),
        ])

    def test_same_minute_rotation_switches_session_via_rotations_counter(self):
        clk = _clock_at(30)
        ctx = make_ctx(self.tmp.name, clock=clk, agy_dir=self.agy_dir)
        same_claimed = _local_claimed(0)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182", claimed=same_claimed, rotations=1)
        tp1 = self._transcript_path("conv-rot-1", full=True)
        _append_rows(tp1, [
            _user_row(0, "[from pm.py rotate] seat 1", at=_utc_iso(5)),
            _user_row(1, "第一轮问题", at=_utc_iso(10)),
            _pm_row(2, "第一轮回复", at=_utc_iso(12)),
        ])
        _write_summary_db(self.agy_dir, [
            ("conv-rot-1", [f"file://{self.repo}"], "2026-11-23 16:14:12+00:00"),
        ])

        w = AgyTranscriptWatcher(ctx)
        self.assertEqual(w.sync(self.repo), 2)

        # Second seat rotation within the exact same minute: pane & claimed unchanged, only rotations increments.
        _register_pm(ctx, self.repo, agent="agy", terminal="t182", claimed=same_claimed, rotations=2)
        tp2 = self._transcript_path("conv-rot-2", full=True)
        _append_rows(tp2, [
            _user_row(0, "[from pm.py rotate] seat 2", at=_utc_iso(20)),
            _user_row(1, "第二轮问题", at=_utc_iso(22)),
            _pm_row(2, "第二轮回复", at=_utc_iso(24)),
        ])
        _write_summary_db(self.agy_dir, [
            ("conv-rot-1", [f"file://{self.repo}"], "2026-11-23 16:14:12+00:00"),
            ("conv-rot-2", [f"file://{self.repo}"], "2026-11-23 16:14:24+00:00"),
        ])

        self.assertEqual(w.sync(self.repo), 2)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "第一轮问题"),
            ("pm", "第一轮回复"),
            ("user", "第二轮问题"),
            ("pm", "第二轮回复"),
        ])
        state = json.loads(ctx.home.project_for(self.repo).agy_transcript.read_text(encoding="utf-8"))
        self.assertEqual(state["session"]["id"], "conv-rot-2")
        self.assertEqual(state["session"]["rotations"], 2)
        self.assertIn("conv-rot-1", state["retired"])

    def test_legacy_cursor_without_rotations_keeps_active_session_and_backfills(self):
        ctx = make_ctx(self.tmp.name, clock=_clock_at(30), agy_dir=self.agy_dir)
        claimed = _local_claimed(0)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182", claimed=claimed, rotations=5)

        conv_id = "conv-legacy-active"
        tp = self._transcript_path(conv_id, full=True)
        _append_rows(tp, [
            _user_row(0, "[from pm.py rotate] seat 5", at=_utc_iso(5)),
            _user_row(1, "升级前的问题", at=_utc_iso(10)),
            _pm_row(2, "升级前的回复", at=_utc_iso(12)),
        ])
        _write_summary_db(self.agy_dir, [
            (conv_id, [f"file://{self.repo}"], "2026-11-23 16:14:12+00:00"),
        ])

        # Pre-populate a legacy agy-transcript.json whose session object lacks the "rotations" field.
        state_path = ctx.home.project_for(self.repo).agy_transcript
        state_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_state = {
            "version": 2,
            "session": {
                "id": conv_id,
                "pane": "hc:t182",
                "claimed": claimed,
            },
            "retired": [],
            "cursors": {
                conv_id: {
                    "path": str(tp),
                    "offset": tp.stat().st_size,
                    "last_step": 2,
                    "turn_cause": None,
                },
            },
        }
        state_path.write_text(json.dumps(legacy_state, ensure_ascii=False) + "\n", encoding="utf-8")

        # Append a new turn after upgrade: watcher must keep conv_id active, sync incrementally, and backfill rotations.
        _append_rows(tp, [
            _user_row(3, "升级后的问题", at=_utc_iso(20)),
            _pm_row(4, "升级后的回复", at=_utc_iso(22)),
        ])
        w = AgyTranscriptWatcher(ctx)
        self.assertEqual(w.sync(self.repo), 2)

        events = Conversation(ctx, self.repo).events()
        self.assertEqual([(e["type"], e["text"]) for e in events], [
            ("user", "升级后的问题"),
            ("pm", "升级后的回复"),
        ])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["session"]["id"], conv_id)
        self.assertEqual(state["session"]["rotations"], 5)
        self.assertNotIn(conv_id, state["retired"])

    def test_context_from_env_registers_agy_watcher(self):
        env = {"PM_HOME": str(Path(self.tmp.name) / "ledger"), "AGY_DATA_DIR": str(self.agy_dir)}
        ctx = Context.from_env(env=env)
        names = [getattr(w, "name", "") for w in ctx.deliver_watchers]
        self.assertIn("agy-transcript", names)
        self.assertEqual(ctx.agy_dir, self.agy_dir)
        self.assertTrue(callable(ctx.compact_sync))

    def test_checkpoint_triggers_one_shot_compact_sync_on_next_deliver_batch(self):
        from pmlib.events.agy_watch import agy_compact_sync_pending

        clock = _clock_at(30)
        hc = FakeHc(
            terminals={
                "t182": {
                    "address": "t182",
                    "state": "live",
                    "status": {"state": "idle"},
                    "turn": 1,
                    "labels": {"pm": "demo", "pm.seat": "1"},
                },
            },
            clock=clock,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clock, agy_dir=self.agy_dir)
        _register_pm(ctx, self.repo, agent="agy", terminal="t182")
        conv_id = "conv-compact-sync"
        tp = self._transcript_path(conv_id)
        _write_summary_db(self.agy_dir, [(conv_id, [f"file://{self.repo}"], "2026-11-23 16:15:00+00:00")])

        # Initial PM turn + running CHECKPOINT (ignored) + completed CHECKPOINT (sets pending_compact_sync).
        _append_rows(tp, [
            _user_row(0, "[from pm.py start] You are the PM of the demo project.", at=_utc_iso(5)),
            _pm_row(1, "已接手。", at=_utc_iso(8)),
            {"step_index": 2, "source": "SYSTEM", "type": "CHECKPOINT", "status": "RUNNING", "created_at": _utc_iso(12)},
        ])
        w = AgyTranscriptWatcher(ctx)
        w.sync(self.repo)
        self.assertFalse(agy_compact_sync_pending(ctx, self.repo))

        _append_rows(tp, [
            {
                "step_index": 3,
                "source": "SYSTEM",
                "type": "CHECKPOINT",
                "status": "DONE",
                "created_at": _utc_iso(15),
                "input_tokens": 2000,
                "cache_read_tokens": 198000,
                "output_tokens": 4000,
                "content": "# Resuming from a compaction\nSummary",
            },
        ])
        # Syncing CHECKPOINT records no spurious PM/user event and wakes nothing by itself.
        self.assertEqual(w.sync(self.repo), 0)
        self.assertTrue(agy_compact_sync_pending(ctx, self.repo))
        self.assertEqual(hc.sent, [])

        # Add an active task and record a worker event: next Deliverer batch must attach live ledger sync once.
        ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        ctx.home.task("demo-t1").write_text(json.dumps({
            "id": "demo-t1",
            "number": 7,
            "title": "Fix widget",
            "project": "demo",
            "repo": self.repo,
            "status": "review",
            "log": [{"at": "2026-11-23 11:15", "by": "hc:tw", "text": "status=review; ready"}],
        }), encoding="utf-8")
        Conversation(ctx, self.repo).record(
            "thread", task="demo-t1", title="Fix widget", status="review",
            by="hc:tw", text="status=review; ready", number=7, source="worker", wake=True,
        )
        dlv = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)
        dlv.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(len(hc.sent), 1)
        first_payload = hc.sent[0][1]
        self.assertTrue(first_payload.splitlines()[0].startswith("[from pm.py deliver]"))
        self.assertIn("[pm post-compact live disk sync]", first_payload)
        self.assertIn("#7 demo-t1: Fix widget", first_payload)
        self.assertFalse(agy_compact_sync_pending(ctx, self.repo))

        # Subsequent event batch must NOT repeat the compact sync block.
        Conversation(ctx, self.repo).record(
            "thread", task="demo-t1", title="Fix widget", status="done",
            by="hc:tw", text="status=done; merged", number=7, source="worker", wake=True,
        )
        dlv.look(FakeChangeWaiter(), {}, {})
        self.assertEqual(len(hc.sent), 2)
        self.assertNotIn("[pm post-compact live disk sync]", hc.sent[1][1])


if __name__ == "__main__":
    unittest.main()
