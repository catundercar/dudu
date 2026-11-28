"""Tests for 4-runtime transcript token parsers, SQLite incremental byte-offset cache, and `pm.py tokens`.

Strictly uses temporary directories injected via `Context`; never reads or touches real `~/.claude`, `~/.gemini`,
`~/.codex`, or `~/.pi` transcripts.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import FakeClock, make_ctx, run_main  # noqa: E402
from pmlib.agents.sessions import claude_folder  # noqa: E402
from pmlib.views.tokens import token_analytics  # noqa: E402
from pmlib.views.tokens_cache import (  # noqa: E402
    parse_agy_line,
    parse_claude_line,
    parse_codex_line,
    parse_pi_line,
)


def _iso_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


class ParserUnitTests(unittest.TestCase):
    def test_claude_dedup_and_advisor_iterations(self):
        seen_list, seen_set, deltas = [], set(), {}
        meta = {"cwd": "", "sid": "", "last_model": ""}
        ts = "2026-11-27T15:10:00.000Z"

        # Repeated msg.id rows (streaming blocks) must be deduplicated cleanly.
        row1 = {
            "type": "assistant",
            "timestamp": ts,
            "cwd": "/repo/app",
            "sessionId": "sid-1",
            "requestId": "req-1",
            "message": {
                "id": "msg-dup",
                "model": "claude-opus-5-5",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 1000,
                    "cache_creation_input_tokens": 200,
                    "cache_creation": {"ephemeral_5m_input_tokens": 50, "ephemeral_1h_input_tokens": 150},
                    "iterations": [
                        {
                            "type": "message",
                            "input_tokens": 6,
                            "output_tokens": 20,
                            "cache_read_input_tokens": 400,
                            "cache_creation": {"ephemeral_5m_input_tokens": 50, "ephemeral_1h_input_tokens": 0},
                        },
                        {
                            "type": "advisor_message",
                            "model": "claude-fable-5-2",
                            "input_tokens": 4,
                            "output_tokens": 30,
                            "cache_read_input_tokens": 600,
                            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 150},
                        },
                    ],
                },
            },
        }
        parse_claude_line(row1, line_end=100, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_claude_line(row1, line_end=200, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_claude_line(
            {"type": "system", "subtype": "api_error", "timestamp": ts, "uuid": "err-1"},
            line_end=300,
            seen_list=seen_list,
            seen_set=seen_set,
            deltas=deltas,
            meta=meta,
        )

        self.assertEqual(len(deltas), 2)
        opus_vals = next(v for k, v in deltas.items() if k[1] == "claude-opus-5-5" and k[2] == 0)
        fable_vals = next(v for k, v in deltas.items() if k[1] == "claude-fable-5-2" and k[2] == 1)
        # calls, errors, input, output, cr, cw5, cw1, usd
        self.assertEqual(opus_vals[:7], [1, 1, 6, 20, 400, 50, 0])
        self.assertEqual(fable_vals[:7], [1, 0, 4, 30, 600, 0, 150])

    def test_agy_no_fabricated_cache_write_and_dedup(self):
        seen_list, seen_set, deltas = [], set(), {}
        meta = {"cwd": "", "sid": "", "last_model": ""}
        ts = "2026-11-27T15:10:00Z"
        row = {
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "step_index": 7,
            "created_at": ts,
            "model": "gemini-4-neon-high",
            "input_tokens": 5000,
            "output_tokens": 300,
            "cache_read_tokens": 12000,
        }
        parse_agy_line(row, line_end=100, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_agy_line(row, line_end=200, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_agy_line({"type": "PLANNER_RESPONSE", "status": "RUNNING", "step_index": 8, "input_tokens": 999},
                       line_end=250, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_agy_line({"type": "ERROR_MESSAGE", "step_index": 9, "created_at": ts},
                       line_end=300, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        # Completed CHECKPOINT row (compaction request, no model field -> inherits last_model) MUST be counted & deduped.
        cp_row = {
            "type": "CHECKPOINT",
            "status": "DONE",
            "step_index": 10,
            "created_at": ts,
            "input_tokens": 2300,
            "output_tokens": 4100,
            "cache_read_tokens": 180000,
        }
        parse_agy_line(cp_row, line_end=400, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_agy_line(cp_row, line_end=450, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        # Non-DONE CHECKPOINT or zero-token CHECKPOINT is ignored.
        parse_agy_line({"type": "CHECKPOINT", "status": "RUNNING", "step_index": 11, "created_at": ts, "input_tokens": 500},
                       line_end=500, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_agy_line({"type": "CHECKPOINT", "status": "DONE", "step_index": 12, "created_at": ts},
                       line_end=550, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)

        vals = list(deltas.values())[0]
        # calls=2 (1 PLANNER_RESPONSE + 1 CHECKPOINT), errors=1, input=7300, output=4400, cache_read=192000
        self.assertEqual(vals[:7], [2, 1, 7300, 4400, 192000, 0, 0])

    def test_codex_subtracts_cached_without_double_counting(self):
        seen_list, seen_set, deltas = [], set(), {}
        meta = {"cwd": "", "sid": "", "last_model": ""}
        ts = "2026-11-27T15:10:00Z"
        parse_codex_line({"type": "session_meta", "payload": {"id": "cx-1", "cwd": "/repo/app"}},
                         line_end=50, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_codex_line({"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
                         line_end=80, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        # input_tokens (10000) INCLUDES cached_input_tokens (7500) + cache_write_input_tokens (500) -> uncached = 2000
        tur = {
            "type": "token_usage_record",
            "timestamp": ts,
            "payload": {
                "response_id": "resp-1",
                "input_tokens": 10000,
                "cached_input_tokens": 7500,
                "cache_write_input_tokens": 500,
                "output_tokens": 400,
            },
        }
        parse_codex_line(tur, line_end=150, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        # Duplicate token_count snapshot with same response_id must not double-count
        tc_dup = {
            "type": "event_msg",
            "timestamp": ts,
            "payload": {
                "type": "token_count",
                "response_id": "resp-1",
                "info": {"last_token_usage": {"input_tokens": 10000, "cached_input_tokens": 7500, "output_tokens": 400}},
            },
        }
        parse_codex_line(tc_dup, line_end=220, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        # Distinct fallback token_count snapshot without response_id
        tc_new = {
            "type": "event_msg",
            "timestamp": ts,
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {"input_tokens": 1200, "cached_input_tokens": 1000, "output_tokens": 100},
                    "total_token_usage": {"input_tokens": 11200, "cached_input_tokens": 8500, "output_tokens": 500},
                },
            },
        }
        parse_codex_line(tc_new, line_end=300, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_codex_line(tc_new, line_end=360, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_codex_line({"type": "event_msg", "timestamp": ts, "payload": {"type": "stream_error", "id": "se-1"}},
                         line_end=400, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)

        vals = next(v for k, v in deltas.items() if k[1] == "gpt-6.1-sol")
        # calls=2, errors=1, uncached_in=(2000+200)=2200, out=(400+100)=500, cr=(7500+1000)=8500, cw5=500
        self.assertEqual(vals[:7], [2, 1, 2200, 500, 8500, 500, 0])

    def test_pi_native_usage_and_cost(self):
        seen_list, seen_set, deltas = [], set(), {}
        meta = {"cwd": "", "sid": "", "last_model": ""}
        ts = "2026-11-27T15:10:00Z"
        parse_pi_line({"type": "session", "id": "pi-1", "cwd": "/repo/app"},
                      line_end=50, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        msg = {
            "type": "message",
            "id": "m-1",
            "timestamp": ts,
            "message": {
                "role": "assistant",
                "model": "deepseek/deepseek-flash",
                "usage": {
                    "input": 7500,
                    "output": 200,
                    "cacheRead": 9000,
                    "cacheWrite": 0,
                    "reasoning": 50,
                    "cost": {"total": 0.0125},
                },
            },
        }
        parse_pi_line(msg, line_end=150, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)
        parse_pi_line({
            "type": "message",
            "id": "m-err",
            "timestamp": ts,
            "message": {
                "role": "assistant",
                "model": "deepseek/deepseek-flash",
                "errorMessage": "Connection error.",
                "stopReason": "error",
                "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0}},
            },
        }, line_end=250, seen_list=seen_list, seen_set=seen_set, deltas=deltas, meta=meta)

        vals = next(v for k, v in deltas.items() if k[1] == "deepseek/deepseek-flash")
        self.assertEqual(vals[:7], [1, 1, 7500, 200, 9000, 0, 0])
        self.assertAlmostEqual(vals[7], 0.0125, places=6)


class TokenAnalyticsIntegrationTests(unittest.TestCase):
    def _seed_project(self, tmp: Path, now_dt: datetime.datetime):
        clk = FakeClock(now_dt)
        ctx = make_ctx(tmp, clock=clk, config={"lang": "en", "token_pricing": {"custom-pro": {"input": 10.0, "output": 20.0, "cache_read": 1.0}}})
        repo = tmp / "repos" / "alpha"
        repo.mkdir(parents=True, exist_ok=True)
        wt = tmp / "worktrees" / "alpha" / "feat-1"
        wt.mkdir(parents=True, exist_ok=True)

        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx.home.registration("alpha").write_text(json.dumps({
            "name": "pm-alpha",
            "project": "alpha",
            "repo": str(repo),
            "agent": "claude",
            "agent_session": {"kind": "claude", "id": "pm-sid-1"},
        }), encoding="utf-8")

        ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        ctx.home.task("alpha-feat-1").write_text(json.dumps({
            "id": "alpha-feat-1",
            "number": 12,
            "title": "Build feature one",
            "project": "alpha",
            "repo": str(repo),
            "worktree": str(wt),
            "status": "in_progress",
            "session": {"kind": "claude", "id": "work-sid-1"},
        }), encoding="utf-8")
        ctx.home.task("alpha-feat-1-review").write_text(json.dumps({
            "id": "alpha-feat-1-review",
            "review_of": "alpha-feat-1",
            "title": "Review feature one",
            "project": "alpha",
            "repo": str(repo),
            "worktree": str(wt),
            "status": "done",
            "session": {"kind": "agy", "id": "rev-cid-1"},
        }), encoding="utf-8")
        return ctx, repo, wt

    def test_incremental_byte_offset_and_folding_and_cli(self):
        now_dt = datetime.datetime(2026, 11, 27, 14, 30, 0)
        ts_today = _iso_utc(now_dt - datetime.timedelta(minutes=20))
        ts_3d = _iso_utc(now_dt - datetime.timedelta(days=3))

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctx, repo, wt = self._seed_project(tmp, now_dt)

            # Claude worker + subagent + PM
            c_wt = ctx.claude_projects / claude_folder(wt)
            worker_file = c_wt / "work-sid-1.jsonl"
            _write_jsonl(worker_file, [
                {
                    "type": "assistant",
                    "timestamp": ts_today,
                    "cwd": str(wt),
                    "sessionId": "work-sid-1",
                    "message": {
                        "id": "w-msg-1",
                        "model": "claude-opus-5-5",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 200,
                            "cache_read_input_tokens": 5000,
                            "cache_creation_input_tokens": 500,
                            "iterations": [
                                {"type": "message", "input_tokens": 80, "output_tokens": 150, "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 500},
                                {"type": "advisor_message", "model": "claude-fable-5-2", "input_tokens": 20, "output_tokens": 50, "cache_read_input_tokens": 2000, "cache_creation_input_tokens": 0},
                            ],
                        },
                    },
                },
            ])
            sub_file = c_wt / "work-sid-1" / "subagents" / "agent-sub1.jsonl"
            _write_jsonl(sub_file, [{
                "type": "assistant",
                "timestamp": ts_today,
                "cwd": str(wt),
                "message": {
                    "id": "sub-1",
                    "model": "claude-sonnet-4-5",
                    "usage": {"input_tokens": 50, "output_tokens": 100, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0},
                },
            }])

            c_pm = ctx.claude_projects / claude_folder(repo)
            _write_jsonl(c_pm / "pm-sid-1.jsonl", [{
                "type": "assistant",
                "timestamp": ts_3d,
                "cwd": str(repo),
                "sessionId": "pm-sid-1",
                "message": {
                    "id": "pm-1",
                    "model": "claude-opus-5-5",
                    "usage": {"input_tokens": 40, "output_tokens": 60, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0},
                },
            }])

            # agy reviewer (linked by rev-cid-1 + conversation_summaries.db)
            agy_db = ctx.agy_dir / "conversation_summaries.db"
            agy_db.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(str(agy_db))
            con.execute("CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, workspace_uris TEXT, parent_conversation_id TEXT)")
            con.execute("INSERT INTO conversation_summaries VALUES (?, ?, ?)", ("rev-cid-1", json.dumps([f"file://{wt}"]), ""))
            con.commit()
            con.close()
            _write_jsonl(ctx.agy_dir / "brain" / "rev-cid-1" / ".system_generated" / "logs" / "transcript.jsonl", [{
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "step_index": 1,
                "created_at": ts_today,
                "model": "gemini-4-carbon-high",
                "input_tokens": 1000,
                "output_tokens": 250,
                "cache_read_tokens": 4000,
            }])

            # Codex in-scope + out-of-scope
            _write_jsonl(ctx.codex_sessions / "2026" / "11" / "27" / "rollout-1.jsonl", [
                {"type": "session_meta", "timestamp": ts_today, "payload": {"id": "cx-1", "cwd": str(repo)}},
                {"type": "turn_context", "timestamp": ts_today, "payload": {"model": "gpt-6.1-sol"}},
                {"type": "token_usage_record", "timestamp": ts_today, "payload": {"response_id": "r1", "input_tokens": 500, "cached_input_tokens": 300, "output_tokens": 50}},
            ])
            _write_jsonl(ctx.codex_sessions / "2026" / "11" / "27" / "rollout-outside.jsonl", [
                {"type": "session_meta", "timestamp": ts_today, "payload": {"id": "cx-out", "cwd": "/tmp/unrelated"}},
                {"type": "token_usage_record", "timestamp": ts_today, "payload": {"response_id": "r2", "input_tokens": 999999, "cached_input_tokens": 0, "output_tokens": 1}},
            ])

            # pi session
            _write_jsonl(ctx.pi_sessions / "--alpha--" / "s1.jsonl", [
                {"type": "session", "id": "pi-1", "timestamp": ts_today, "cwd": str(repo)},
                {"type": "message", "id": "p1", "timestamp": ts_today, "message": {
                    "role": "assistant",
                    "model": "deepseek/deepseek-flash",
                    "usage": {"input": 300, "output": 40, "cacheRead": 600, "cacheWrite": 0, "cost": {"total": 0.005}},
                }},
            ])

            data1 = token_analytics(ctx)
            today_kpi = data1["projects"]["alpha"]["ranges"]["today"]["kpi"]
            # Worker (3730 + 2070 = 5800) + Subagent (1150) + Agy review (5250) + Codex (550) + pi (940) = 13690
            self.assertEqual(today_kpi["total_tokens"], 13690)
            self.assertEqual(today_kpi["requests"], 6)

            # Verify review folding into #12 alpha-feat-1
            by_task = data1["projects"]["alpha"]["ranges"]["today"]["by_task"]
            feat1 = next(t for t in by_task if t["id"] == "alpha-feat-1")
            self.assertEqual(feat1["number"], 12)
            self.assertEqual(feat1["work_tokens"], 5800 + 1150)
            self.assertEqual(feat1["review_tokens"], 5250)

            # Verify agy marks cache_write_available == False
            by_agent = {a["agent"]: a for a in data1["projects"]["alpha"]["ranges"]["today"]["by_agent"]}
            self.assertFalse(by_agent["agy"]["cache_write_available"])
            self.assertTrue(by_agent["claude"]["cache_write_available"])

            # Verify 7d range includes the 3-days-ago PM session (+1000 tokens)
            k7 = data1["projects"]["alpha"]["ranges"]["7d"]["kpi"]
            self.assertEqual(k7["total_tokens"], 14690)

            # Warm re-scan: identical stats
            data2 = token_analytics(ctx)
            self.assertEqual(data2["projects"]["alpha"]["ranges"]["today"]["kpi"]["total_tokens"], 13690)

            # Incremental append: includes a duplicate w-msg-1 (must be ignored via tail_seen_ids) + a new w-msg-2,
            # plus an unterminated line that must wait for '\n'
            _append_jsonl(worker_file, [
                {
                    "type": "assistant",
                    "timestamp": ts_today,
                    "cwd": str(wt),
                    "message": {"id": "w-msg-1", "model": "claude-opus-5-5", "usage": {"input_tokens": 9999, "output_tokens": 9999}},
                },
                {
                    "type": "assistant",
                    "timestamp": ts_today,
                    "cwd": str(wt),
                    "message": {"id": "w-msg-2", "model": "claude-opus-5-5", "usage": {"input_tokens": 100, "output_tokens": 200, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}},
                },
            ])
            with open(worker_file, "a", encoding="utf-8") as fh:
                fh.write('{"type":"assistant","partial":true')  # no newline yet

            data3 = token_analytics(ctx)
            self.assertEqual(data3["projects"]["alpha"]["ranges"]["today"]["kpi"]["total_tokens"], 13690 + 300)

            # Complete the partial line
            with open(worker_file, "a", encoding="utf-8") as fh:
                fh.write(',"timestamp":"' + ts_today + '","message":{"id":"w-msg-3","model":"claude-opus-5-5","usage":{"input_tokens":10,"output_tokens":20}}}\n')

            data4 = token_analytics(ctx)
            self.assertEqual(data4["projects"]["alpha"]["ranges"]["today"]["kpi"]["total_tokens"], 13690 + 330)

            # Verify CLI `pm.py tokens alpha --json` and cache/token-analytics.json output
            self.assertTrue(ctx.home.token_analytics_cache.is_file())
            code, out, err = run_main(ctx, "tokens", "alpha", "--json")
            self.assertEqual(code, 0, err)
            parsed = json.loads(out)
            self.assertEqual(parsed["scope"], "alpha")
            self.assertEqual(parsed["projects"]["alpha"]["ranges"]["today"]["kpi"]["total_tokens"], 13690 + 330)

            code_txt, out_txt, _ = run_main(ctx, "tokens", "--all", "--range", "today")
            self.assertEqual(code_txt, 0)
            self.assertIn("tokens (all, today):", out_txt)

            # Truncating/replacing worker file resets offset & rebuilds its rollups cleanly,
            # and custom token_pricing overrides list-rate cost calculation.
            _write_jsonl(worker_file, [{
                "type": "assistant",
                "timestamp": ts_today,
                "cwd": str(wt),
                "message": {
                    "id": "w-reset-1",
                    "model": "custom-pro-1",
                    "usage": {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_write_5m": 0},
                },
            }])
            data_reset = token_analytics(ctx)
            models_reset = {m["model"]: m for m in data_reset["projects"]["alpha"]["ranges"]["today"]["by_model"]}
            self.assertIn("custom-pro-1", models_reset)
            self.assertAlmostEqual(models_reset["custom-pro-1"]["cost_usd"], 10.0, places=3)
            self.assertNotIn("claude-fable-5-2", models_reset)

    def test_claude_cross_session_resume_dedup(self):
        now_dt = datetime.datetime(2026, 11, 27, 14, 30, 0)
        ts_today = _iso_utc(now_dt - datetime.timedelta(minutes=10))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctx, repo, wt = self._seed_project(tmp, now_dt)
            c_wt = ctx.claude_projects / claude_folder(wt)
            _write_jsonl(c_wt / "work-sid-1.jsonl", [{
                "type": "assistant",
                "timestamp": ts_today,
                "cwd": str(wt),
                "sessionId": "work-sid-1",
                "message": {"id": "msg-shared-1", "model": "claude-opus-5-5", "usage": {"input_tokens": 100, "output_tokens": 50}},
            }])
            # Resumed session replays msg-shared-1 and adds msg-new-2
            _write_jsonl(c_wt / "work-sid-2.jsonl", [
                {
                    "type": "assistant",
                    "timestamp": ts_today,
                    "cwd": str(wt),
                    "sessionId": "work-sid-2",
                    "message": {"id": "msg-shared-1", "model": "claude-opus-5-5", "usage": {"input_tokens": 100, "output_tokens": 50}},
                },
                {
                    "type": "assistant",
                    "timestamp": ts_today,
                    "cwd": str(wt),
                    "sessionId": "work-sid-2",
                    "message": {"id": "msg-new-2", "model": "claude-opus-5-5", "usage": {"input_tokens": 200, "output_tokens": 100}},
                },
            ])
            data = token_analytics(ctx)
            kpi = data["projects"]["alpha"]["ranges"]["today"]["kpi"]
            self.assertEqual(kpi["total_tokens"], 450)
            self.assertEqual(kpi["requests"], 2)

    def test_codex_pi_newly_registered_project_not_permanently_skipped(self):
        now_dt = datetime.datetime(2026, 11, 27, 14, 30, 0)
        ts_today = _iso_utc(now_dt - datetime.timedelta(minutes=10))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctx, _, _ = self._seed_project(tmp, now_dt)
            beta_repo = tmp / "repos" / "beta"
            beta_repo.mkdir(parents=True, exist_ok=True)
            _write_jsonl(ctx.codex_sessions / "2026" / "11" / "27" / "rollout-beta.jsonl", [
                {"type": "session_meta", "timestamp": ts_today, "payload": {"id": "cx-beta", "cwd": str(beta_repo)}},
                {"type": "turn_context", "timestamp": ts_today, "payload": {"model": "gpt-6.1-sol"}},
                {"type": "token_usage_record", "timestamp": ts_today, "payload": {"response_id": "rb-1", "input_tokens": 400, "cached_input_tokens": 100, "output_tokens": 50}},
            ])
            _write_jsonl(ctx.pi_sessions / "--beta--" / "s-beta.jsonl", [
                {"type": "session", "id": "pi-beta", "timestamp": ts_today, "cwd": str(beta_repo)},
                {"type": "message", "id": "pb-1", "timestamp": ts_today, "message": {
                    "role": "assistant", "model": "deepseek/deepseek-flash",
                    "usage": {"input": 120, "output": 30, "cacheRead": 50, "cacheWrite": 0, "cost": {"total": 0.002}},
                }},
            ])

            # First scan before beta is registered: beta transcripts are out of scope
            d1 = token_analytics(ctx)
            self.assertEqual(d1["projects"]["__all__"]["ranges"]["today"]["kpi"]["total_tokens"], 0)

            # Now register beta WITHOUT modifying the Codex/pi files on disk
            ctx.home.registration("beta").write_text(json.dumps({
                "name": "pm-beta", "project": "beta", "repo": str(beta_repo), "agent": "codex",
            }), encoding="utf-8")
            d2 = token_analytics(ctx)
            self.assertIn("beta", d2["projects"])
            self.assertEqual(d2["projects"]["beta"]["ranges"]["today"]["kpi"]["total_tokens"], 650)

    def test_concurrent_sync_no_duplicate_counting_and_no_lock_crash(self):
        now_dt = datetime.datetime.now()
        ts_today = _iso_utc(now_dt - datetime.timedelta(minutes=5))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctx, _, wt = self._seed_project(tmp, now_dt)
            c_wt = ctx.claude_projects / claude_folder(wt)
            worker_file = c_wt / "work-sid-1.jsonl"
            _write_jsonl(worker_file, [{
                "type": "assistant",
                "timestamp": ts_today,
                "cwd": str(wt),
                "sessionId": "work-sid-1",
                "message": {"id": "c-1", "model": "claude-opus-5-5", "usage": {"input_tokens": 70, "output_tokens": 30}},
            }])

            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(tmp / "home"),
                "PM_HOME": str(ctx.home.root),
                "CLAUDE_CONFIG_DIR": str(ctx.claude_dir),
                "CODEX_HOME": str(tmp / "codex_home"),
                "AGY_DATA_DIR": str(ctx.agy_dir),
                "PI_CODING_AGENT_DIR": str(tmp / "pi_home"),
            }
            pm_py = str(SCRIPTS / "pm.py")

            # Seed initial 100 tokens
            r0 = subprocess.run([sys.executable, pm_py, "tokens", "--json"], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(r0.returncode, 0, r0.stderr)
            self.assertEqual(json.loads(r0.stdout)["projects"]["alpha"]["ranges"]["all"]["kpi"]["total_tokens"], 100)

            # Append another 100 tokens, then run 3 concurrent processes simultaneously
            _append_jsonl(worker_file, [{
                "type": "assistant",
                "timestamp": ts_today,
                "cwd": str(wt),
                "sessionId": "work-sid-1",
                "message": {"id": "c-2", "model": "claude-opus-5-5", "usage": {"input_tokens": 60, "output_tokens": 40}},
            }])
            procs = [
                subprocess.Popen([sys.executable, pm_py, "tokens", "--json"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for _ in range(3)
            ]
            for p in procs:
                out, err = p.communicate(timeout=30)
                self.assertEqual(p.returncode, 0, err)
                self.assertNotIn("database is locked", err.lower())
                tot = json.loads(out)["projects"]["alpha"]["ranges"]["all"]["kpi"]["total_tokens"]
                self.assertEqual(tot, 200)

    def test_concurrent_sync_forced_overlap_counts_once(self):
        """Deterministic race: hold sync A inside the tail read while sync B starts.

        The subprocess test above may never overlap in practice; this one pins A mid-read
        so an unlocked B would read the same stale byte_offset and double-count c-2.
        """
        import threading
        from unittest import mock

        from pmlib.views import tokens_cache as tc

        now_dt = datetime.datetime(2026, 11, 27, 14, 30, 0)
        ts_today = _iso_utc(now_dt - datetime.timedelta(minutes=5))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctx, _, wt = self._seed_project(tmp, now_dt)
            worker_file = ctx.claude_projects / claude_folder(wt) / "work-sid-1.jsonl"
            row = {"type": "assistant", "timestamp": ts_today, "cwd": str(wt), "sessionId": "work-sid-1"}
            _write_jsonl(worker_file, [{**row, "message": {"id": "c-1", "model": "claude-opus-5-5", "usage": {"input_tokens": 70, "output_tokens": 30}}}])
            self.assertEqual(token_analytics(ctx)["projects"]["alpha"]["ranges"]["today"]["kpi"]["total_tokens"], 100)
            _append_jsonl(worker_file, [{**row, "message": {"id": "c-2", "model": "claude-opus-5-5", "usage": {"input_tokens": 60, "output_tokens": 40}}}])

            real_read = tc._read_lines_forward
            entered, release = threading.Event(), threading.Event()
            holder: list[str] = []

            def gated_read(f, start, size):
                if not holder:
                    holder.append(threading.current_thread().name)
                    entered.set()
                    release.wait(5)
                return real_read(f, start, size)

            results: dict[str, int] = {}
            errors: list[BaseException] = []

            def run(name: str) -> None:
                try:
                    d = token_analytics(ctx)
                    results[name] = d["projects"]["alpha"]["ranges"]["today"]["kpi"]["total_tokens"]
                except BaseException as exc:  # noqa: BLE001 - surfaced via assertion below
                    errors.append(exc)

            with mock.patch.object(tc, "_read_lines_forward", gated_read):
                a = threading.Thread(target=run, args=("a",), name="a")
                a.start()
                self.assertTrue(entered.wait(5))
                b = threading.Thread(target=run, args=("b",), name="b")
                b.start()
                b.join(0.5)  # B must be parked on the lock, not racing ahead
                release.set()
                a.join(10)
                b.join(10)

            self.assertEqual(errors, [])
            self.assertEqual(results, {"a": 200, "b": 200})
            self.assertEqual(token_analytics(ctx)["projects"]["alpha"]["ranges"]["today"]["kpi"]["total_tokens"], 200)

    def test_pm_attribution_all_four_runtimes_and_rotations_no_double_count(self):
        """PM sessions across Claude/agy/Codex/pi (active, retired, subagents, Chinese/English prompts)
        are attributed to pm:<slug>, never hijacked by task hints or main-repo in_place tasks,
        and worker transcripts quoting PM markers stay attributed to their task without double-counting."""
        now_dt = datetime.datetime(2026, 11, 28, 14, 30, 0)
        ts_today = _iso_utc(now_dt - datetime.timedelta(minutes=15))

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctx, repo, wt = self._seed_project(tmp, now_dt)

            # Register main-repo in_place task + an old task that accidentally recorded a PM session id
            ctx.home.task("alpha-inplace").write_text(json.dumps({
                "id": "alpha-inplace",
                "number": 13,
                "title": "Main repo in-place task",
                "project": "alpha",
                "repo": str(repo),
                "in_place": str(repo),
                "status": "done",
            }), encoding="utf-8")
            ctx.home.task("alpha-legacy-bug").write_text(json.dumps({
                "id": "alpha-legacy-bug",
                "number": 14,
                "title": "Legacy task with stale PM sid",
                "project": "alpha",
                "repo": str(repo),
                "status": "done",
                "session": {"kind": "claude", "id": "cl-pm-prev"},
            }), encoding="utf-8")

            c_pm_dir = ctx.claude_projects / claude_folder(repo)
            cl_prev_path = c_pm_dir / "cl-pm-prev.jsonl"
            cl_taken_path = c_pm_dir / "cl-pm-taken.jsonl"

            # Update alpha registration with previous.transcript & current agy agent
            ctx.home.registration("alpha").write_text(json.dumps({
                "name": "pm-alpha",
                "project": "alpha",
                "repo": str(repo),
                "agent": "agy",
                "agent_session": None,
                "previous": {"pane": "hc:t1", "transcript": str(cl_prev_path)},
                "retired_sessions": ["pm-sid-1"],
            }), encoding="utf-8")

            # agy-transcript.json v2 (current + retired + cursors)
            proj_dir = ctx.home.project("alpha").ensure()
            agy_cur_path = ctx.agy_dir / "brain" / "agy-pm-cur" / ".system_generated" / "logs" / "transcript.jsonl"
            agy_old_path = ctx.agy_dir / "brain" / "agy-pm-old" / ".system_generated" / "logs" / "transcript.jsonl"
            agy_sub_path = ctx.agy_dir / "brain" / "agy-pm-sub" / ".system_generated" / "logs" / "transcript.jsonl"
            agy_wrk_path = ctx.agy_dir / "brain" / "agy-wrk-1" / ".system_generated" / "logs" / "transcript.jsonl"
            ctx.home.project("alpha").agy_transcript.write_text(json.dumps({
                "version": 2,
                "session": {"id": "agy-pm-cur", "pane": "hc:t1k6"},
                "retired": ["agy-pm-old"],
                "cursors": {
                    "agy-pm-old": {"path": str(agy_old_path.with_name("transcript_full.jsonl")), "offset": 100},
                    "agy-pm-cur": {"path": str(agy_cur_path.with_name("transcript_full.jsonl")), "offset": 100},
                },
            }), encoding="utf-8")

            # taken-in.json recording historical Claude PM session
            (proj_dir / "taken-in.json").write_text(json.dumps({
                "files": {str(cl_taken_path): {"offset": 100}},
            }), encoding="utf-8")

            # agy conversation_summaries.db (note: agy-pm-sub has empty workspace_uris, only parent_conversation_id!)
            agy_db = ctx.agy_dir / "conversation_summaries.db"
            agy_db.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(str(agy_db))
            con.execute("CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, workspace_uris TEXT, parent_conversation_id TEXT)")
            con.execute("INSERT INTO conversation_summaries VALUES (?, ?, ?)", ("agy-pm-cur", json.dumps([f"file://{repo}"]), ""))
            con.execute("INSERT INTO conversation_summaries VALUES (?, ?, ?)", ("agy-pm-old", json.dumps([f"file://{repo}"]), ""))
            con.execute("INSERT INTO conversation_summaries VALUES (?, ?, ?)", ("agy-pm-sub", "[]", "agy-pm-cur"))
            con.execute("INSERT INTO conversation_summaries VALUES (?, ?, ?)", ("agy-wrk-1", json.dumps([f"file://{wt}"]), ""))
            con.commit()
            con.close()

            # 1a. Current agy PM: opening is [from pm.py rotate], later tool output mentions `pm.py update alpha-feat-1`
            _write_jsonl(agy_cur_path, [
                {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": ts_today,
                 "content": "<USER_REQUEST>\n[from pm.py rotate] You are the PM of the alpha project (pm skill).\n</USER_REQUEST>"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": ts_today,
                 "model": "gemini-4-neon-medium", "input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 3000},
                {"step_index": 2, "type": "GENERIC", "status": "DONE", "created_at": ts_today,
                 "content": "Handover output: pm.py update alpha-feat-1 --status review"},
            ])  # 4200 tokens
            # 1b. Retired agy PM
            _write_jsonl(agy_old_path, [
                {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": ts_today,
                 "content": "<USER_REQUEST>\n[from pm.py start] You are the PM (project manager) of the alpha project.\n</USER_REQUEST>"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": ts_today,
                 "model": "gemini-4-neon-medium", "input_tokens": 500, "output_tokens": 100, "cache_read_tokens": 1400},
            ])  # 2000 tokens
            # 1c. agy PM subagent (no workspace_uris, resolved via parent_conversation_id)
            _write_jsonl(agy_sub_path, [
                {"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": ts_today,
                 "model": "gemini-4-neon-high", "input_tokens": 300, "output_tokens": 50, "cache_read_tokens": 450},
            ])  # 800 tokens
            # 1d. agy worker whose later tool output quotes PM_SESSION_MARK & [from pm.py start]
            _write_jsonl(agy_wrk_path, [
                {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": ts_today,
                 "content": "<USER_REQUEST>\n[Task: Build feature one. From the PM]\nReporting (task #12 alpha-feat-1):\n`pm.py update alpha-feat-1`\n</USER_REQUEST>"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": ts_today,
                 "model": "gemini-4-neon-high", "input_tokens": 2000, "output_tokens": 400, "cache_read_tokens": 7600},
                {"step_index": 2, "type": "GENERIC", "status": "DONE", "created_at": ts_today,
                 "content": 'PM_SESSION_MARK = "the PM for this project (pm skill)"\n[from pm.py start]'},
            ])  # 10000 tokens -> MUST go to alpha-feat-1, NOT pm:alpha!

            # 2a. Claude PM (taken-in.json) + Claude PM subagent
            _write_jsonl(cl_taken_path, [{
                "type": "assistant", "timestamp": ts_today, "cwd": str(repo), "sessionId": "cl-pm-taken",
                "message": {"id": "cl-pm-m1", "model": "claude-opus-5-5",
                            "usage": {"input_tokens": 100, "output_tokens": 100, "cache_read_input_tokens": 1800, "cache_creation_input_tokens": 200}},
            }])  # 2200 tokens
            _write_jsonl(c_pm_dir / "cl-pm-taken" / "subagents" / "agent-p1.jsonl", [{
                "type": "assistant", "timestamp": ts_today, "cwd": str(repo),
                "message": {"id": "cl-pm-sub1", "model": "claude-haiku-4-5",
                            "usage": {"input_tokens": 50, "output_tokens": 50, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 0}},
            }])  # 500 tokens
            # 2b. Previous Claude PM (previous.transcript beats stale task session id)
            _write_jsonl(cl_prev_path, [{
                "type": "assistant", "timestamp": ts_today, "cwd": str(repo), "sessionId": "cl-pm-prev",
                "message": {"id": "cl-pm-m2", "model": "claude-opus-5-5",
                            "usage": {"input_tokens": 80, "output_tokens": 120, "cache_read_input_tokens": 1100, "cache_creation_input_tokens": 0}},
            }])  # 1300 tokens
            # 2c. Ad-hoc Claude session in main repo (must NOT be hijacked by alpha-inplace or pm:alpha)
            _write_jsonl(c_pm_dir / "adhoc-1.jsonl", [
                {"type": "user", "timestamp": ts_today, "cwd": str(repo), "sessionId": "adhoc-1",
                 "message": {"role": "user", "content": "Please update a README section for me."}},
                {"type": "assistant", "timestamp": ts_today, "cwd": str(repo), "sessionId": "adhoc-1",
                 "message": {"id": "adhoc-m1", "model": "claude-sonnet-4-5",
                             "usage": {"input_tokens": 200, "output_tokens": 100, "cache_read_input_tokens": 700, "cache_creation_input_tokens": 0}}},
            ])  # 1000 tokens -> other:alpha

            # 3. Codex PM (discovered via opening user prompt in repo)
            _write_jsonl(ctx.codex_sessions / "2026" / "11" / "28" / "rollout-pm.jsonl", [
                {"type": "session_meta", "timestamp": ts_today, "payload": {"id": "cx-pm-1", "cwd": str(repo)}},
                {"type": "response_item", "timestamp": ts_today, "payload": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "[from pm.py start] You are the PM (project manager) of the alpha project."}],
                }},
                {"type": "turn_context", "timestamp": ts_today, "payload": {"model": "gpt-6.1-sol"}},
                {"type": "token_usage_record", "timestamp": ts_today, "payload": {
                    "response_id": "cx-pm-r1", "input_tokens": 1500, "cached_input_tokens": 1000, "output_tokens": 100,
                }},
            ])  # 1600 tokens (500 uncached + 1000 cached + 100 out)

            # 4. pi PM (discovered via Chinese PM opening prompt in repo)
            _write_jsonl(ctx.pi_sessions / "--alpha--" / "pm-pi.jsonl", [
                {"type": "session", "id": "pi-pm-1", "timestamp": ts_today, "cwd": str(repo)},
                {"type": "message", "id": "u1", "timestamp": ts_today, "message": {
                    "role": "user", "content": [{"type": "text", "text": "[from pm.py rotate] 你是 alpha 项目的 PM（pm skill），接手上一任。"}],
                }},
                {"type": "message", "id": "a1", "timestamp": ts_today, "message": {
                    "role": "assistant", "model": "deepseek/deepseek-flash",
                    "usage": {"input": 400, "output": 100, "cacheRead": 500, "cacheWrite": 0, "cost": {"total": 0.004}},
                }},
            ])  # 1000 tokens

            data = token_analytics(ctx)
            sl = data["projects"]["alpha"]["ranges"]["today"]
            expected_pm = 4200 + 2000 + 800 + 2200 + 500 + 1300 + 1600 + 1000  # 13600
            expected_total = expected_pm + 10000 + 1000  # 24600

            # Strict conservation: KPI total == sum of all by_task rows (zero double-counting)
            self.assertEqual(sl["kpi"]["total_tokens"], expected_total)
            self.assertEqual(sum(t["total_tokens"] for t in sl["by_task"]), expected_total)
            self.assertEqual(sl["kpi"]["pm_tokens"], expected_pm)

            pm = sl["pm"]
            self.assertEqual(pm["total_tokens"], expected_pm)
            self.assertEqual(pm["agents"], ["agy", "claude", "codex", "pi"])
            self.assertEqual(pm["sessions"], 8)
            self.assertEqual(pm["by_agent"]["agy"]["total_tokens"], 7000)
            self.assertEqual(pm["by_agent"]["claude"]["total_tokens"], 4000)
            self.assertEqual(pm["by_agent"]["codex"]["total_tokens"], 1600)
            self.assertEqual(pm["by_agent"]["pi"]["total_tokens"], 1000)

            tasks_map = {t["id"]: t for t in sl["by_task"]}
            self.assertIn("pm:alpha", tasks_map)
            self.assertEqual(tasks_map["pm:alpha"]["total_tokens"], expected_pm)
            self.assertEqual(tasks_map["pm:alpha"]["role"], "pm")
            self.assertEqual(tasks_map["alpha-feat-1"]["total_tokens"], 10000)
            self.assertEqual(tasks_map["alpha-feat-1"]["role"], "worker")
            self.assertEqual(tasks_map["other:alpha"]["total_tokens"], 1000)
            self.assertNotIn("alpha-inplace", tasks_map)
            self.assertNotIn("alpha-legacy-bug", tasks_map)

            by_agent = {a["agent"]: a for a in sl["by_agent"]}
            self.assertEqual(by_agent["agy"]["pm_tokens"], 7000)
            self.assertEqual(by_agent["claude"]["pm_tokens"], 4000)
            self.assertEqual(by_agent["codex"]["pm_tokens"], 1600)
            self.assertEqual(by_agent["pi"]["pm_tokens"], 1000)

            # CLI text view shows PM summary line
            code, out, err = run_main(ctx, "tokens", "alpha", "--range", "today")
            self.assertEqual(code, 0, err)
            self.assertIn("- PM:", out)

    def test_pm_row_preserved_when_tasks_exceed_top_cap(self):
        now_dt = datetime.datetime(2026, 11, 28, 14, 30, 0)
        ts_today = _iso_utc(now_dt - datetime.timedelta(minutes=5))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctx, repo, _ = self._seed_project(tmp, now_dt)
            c_pm = ctx.claude_projects / claude_folder(repo)
            _write_jsonl(c_pm / "pm-sid-1.jsonl", [{
                "type": "assistant", "timestamp": ts_today, "cwd": str(repo), "sessionId": "pm-sid-1",
                "message": {"id": "pm-small", "model": "claude-opus-5-5", "usage": {"input_tokens": 50, "output_tokens": 50}},
            }])
            for i in range(28):
                tid = f"alpha-big-{i}"
                t_wt = tmp / "worktrees" / "alpha" / f"big-{i}"
                t_wt.mkdir(parents=True, exist_ok=True)
                ctx.home.task(tid).write_text(json.dumps({
                    "id": tid, "number": 100 + i, "title": f"Big task {i}",
                    "project": "alpha", "repo": str(repo), "worktree": str(t_wt),
                    "status": "done", "session": {"kind": "claude", "id": f"big-sid-{i}"},
                }), encoding="utf-8")
                _write_jsonl(ctx.claude_projects / claude_folder(t_wt) / f"big-sid-{i}.jsonl", [{
                    "type": "assistant", "timestamp": ts_today, "cwd": str(t_wt), "sessionId": f"big-sid-{i}",
                    "message": {"id": f"big-m-{i}", "model": "claude-opus-5-5", "usage": {"input_tokens": 5000 + i, "output_tokens": 500}},
                }])
            sl = token_analytics(ctx)["projects"]["alpha"]["ranges"]["today"]
            by_task_ids = [t["id"] for t in sl["by_task"]]
            self.assertIn("pm:alpha", by_task_ids)
            self.assertEqual(sl["pm"]["total_tokens"], 100)

    def test_agy_checkpoint_counted_and_schema_version_upgrade_rebuilds(self):
        from pmlib.views.tokens_cache import SCHEMA_VERSION

        now_dt = datetime.datetime(2026, 11, 28, 14, 30, 0)
        ts_today = _iso_utc(now_dt - datetime.timedelta(minutes=5))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ctx, repo, _ = self._seed_project(tmp, now_dt)
            ctx.home.registration("alpha").write_text(json.dumps({
                "name": "pm-alpha",
                "project": "alpha",
                "repo": str(repo),
                "agent": "agy",
                "agent_session": {"kind": "agy", "id": "agy-cp-sid"},
            }), encoding="utf-8")
            agy_tr = ctx.agy_dir / "brain" / "agy-cp-sid" / ".system_generated" / "logs" / "transcript.jsonl"
            _write_jsonl(agy_tr, [
                {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "created_at": ts_today,
                 "content": "<USER_REQUEST>\n[from pm.py start] You are the PM of alpha.\n</USER_REQUEST>"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "status": "DONE", "created_at": ts_today,
                 "model": "gemini-4-neon-medium", "input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 9000},
                {"step_index": 2, "type": "CHECKPOINT", "status": "DONE", "created_at": ts_today,
                 "input_tokens": 2000, "output_tokens": 3000, "cache_read_tokens": 150000},
            ])
            # Seed a stale v3 DB (from before CHECKPOINT support) to verify SCHEMA_VERSION bump forces clean rebuild.
            db_path = ctx.home.token_usage_db
            db_path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(str(db_path))
            con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            con.execute("INSERT INTO meta(key, value) VALUES('schema_version', '3')")
            con.commit()
            con.close()

            self.assertEqual(SCHEMA_VERSION, "4")
            sl = token_analytics(ctx)["projects"]["alpha"]["ranges"]["today"]
            # Total = (1000+200+9000) + (2000+3000+150000) = 10200 + 155000 = 165200
            self.assertEqual(sl["pm"]["total_tokens"], 165200)
            self.assertEqual(sl["pm"]["requests"], 2)

    def test_multifolder_zerofolder_shared_folder_dedup_and_total_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clk = FakeClock("2026-11-28 12:00:00")
            ctx = make_ctx(root / "ledger", clock=clk)
            ts_today = "2026-11-28T16:30:00Z"

            repo_a = root / "repos/app-a"
            repo_b = root / "repos/app-b"
            shared_repo = root / "repos/shared-core"
            for r in (repo_a, repo_b, shared_repo):
                r.mkdir(parents=True)

            ctx.home.registrations.mkdir(parents=True, exist_ok=True)
            ctx.home.tasks.mkdir(parents=True, exist_ok=True)
            # Multi-folder project `multi` owns repo_a + repo_b + shared_repo (newer & non-archived)
            ctx.home.registration("multi").write_text(json.dumps({
                "name": "pm-multi", "slug": "multi", "project": "Multi",
                "folders": [
                    {"path": str(repo_a), "alias": "app-a", "git": True},
                    {"path": str(repo_b), "alias": "app-b", "git": True},
                    {"path": str(shared_repo), "alias": "shared", "git": True},
                ],
                "repo": str(repo_a), "agent": "claude", "updated": "2026-11-28 11:00",
            }), encoding="utf-8")
            # Archived project also shares `shared_repo` -> must lose tie-breaker to non-archived `multi`
            ctx.home.registration("old-shared").write_text(json.dumps({
                "name": "pm-old-shared", "slug": "old-shared", "project": "Old Shared",
                "archived": "2026-11-01",
                "folders": [{"path": str(shared_repo), "alias": "shared", "git": True}],
                "repo": str(shared_repo), "agent": "claude",
            }), encoding="utf-8")
            # 0-folder project `notes` lives cleanly in ledger projects/notes/
            notes_dir = ctx.home.project("notes").root
            notes_dir.mkdir(parents=True, exist_ok=True)
            ctx.home.registration("notes").write_text(json.dumps({
                "name": "pm-notes", "slug": "notes", "project": "Notes Only",
                "folders": [], "repo": "", "agent": "claude",
            }), encoding="utf-8")

            # Worker task in secondary folder (`repo_b`) anchored by `project_slug="multi"`
            ctx.home.task("multi-fix-b").write_text(json.dumps({
                "id": "multi-fix-b", "title": "Fix B", "project": "Multi",
                "project_slug": "multi", "folder_alias": "app-b", "repo": str(repo_b),
                "status": "in_progress", "session": {"kind": "claude", "id": "sid-worker-b"},
            }), encoding="utf-8")

            # Transcripts:
            # 1) Worker in repo_b (1000 tokens -> attributed strictly to `multi`)
            _write_jsonl(ctx.claude_projects / claude_folder(repo_b.resolve()) / "sid-worker-b.jsonl", [
                {"type": "user", "sessionId": "sid-worker-b", "cwd": str(repo_b.resolve()), "timestamp": ts_today,
                 "message": {"role": "user", "content": "fix repo b"}},
                {"type": "assistant", "sessionId": "sid-worker-b", "cwd": str(repo_b.resolve()), "timestamp": ts_today,
                 "message": {"id": "msg-wb", "role": "assistant", "model": "claude-sonnet-4-6",
                             "usage": {"input_tokens": 700, "output_tokens": 300}, "content": []}},
            ])
            # 2) Ad-hoc session in shared_repo (2000 tokens -> uniquely won by active `multi`, zero double-count)
            _write_jsonl(ctx.claude_projects / claude_folder(shared_repo.resolve()) / "sid-shared.jsonl", [
                {"type": "user", "sessionId": "sid-shared", "cwd": str(shared_repo.resolve()), "timestamp": ts_today,
                 "message": {"role": "user", "content": "check shared core"}},
                {"type": "assistant", "sessionId": "sid-shared", "cwd": str(shared_repo.resolve()), "timestamp": ts_today,
                 "message": {"id": "msg-sh", "role": "assistant", "model": "claude-sonnet-4-6",
                             "usage": {"input_tokens": 1200, "output_tokens": 800}, "content": []}},
            ])
            # 3) PM session in 0-folder project dir (`projects/notes`) (500 tokens -> attributed to `notes`)
            _write_jsonl(ctx.claude_projects / claude_folder(notes_dir.resolve()) / "sid-notes.jsonl", [
                {"type": "user", "sessionId": "sid-notes", "cwd": str(notes_dir.resolve()), "timestamp": ts_today,
                 "message": {"role": "user", "content": "[from pm.py start] organize docs"}},
                {"type": "assistant", "sessionId": "sid-notes", "cwd": str(notes_dir.resolve()), "timestamp": ts_today,
                 "message": {"id": "msg-notes", "role": "assistant", "model": "claude-sonnet-4-6",
                             "usage": {"input_tokens": 300, "output_tokens": 200}, "content": []}},
            ])

            res = token_analytics(ctx)
            projs = res["projects"]
            self.assertEqual(projs["multi"]["ranges"]["all"]["kpi"]["total_tokens"], 3000)
            self.assertEqual(projs["old-shared"]["ranges"]["all"]["kpi"]["total_tokens"], 0)
            self.assertEqual(projs["notes"]["ranges"]["all"]["kpi"]["total_tokens"], 500)
            # 100% total / per-project closure with zero double counting across shared folders
            proj_sum = sum(
                p["ranges"]["all"]["kpi"]["total_tokens"]
                for k, p in projs.items()
                if k != "__all__"
            )
            self.assertEqual(projs["__all__"]["ranges"]["all"]["kpi"]["total_tokens"], proj_sum)
            self.assertEqual(projs["__all__"]["ranges"]["all"]["kpi"]["total_tokens"], 3500)


if __name__ == "__main__":
    unittest.main()
