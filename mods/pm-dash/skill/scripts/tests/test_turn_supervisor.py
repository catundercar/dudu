"""Tests for Phase 1 runtime adapters, supervisor throttling, heartbeat stale -> `unknown` + auto-revive,
harmonized `hc` detection in `views/state.py`, producer journal writes, and `pm.py turn-journal export`.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
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
    os.environ["PM_HOME"] = "/nonexistent/pm-home-turn-sup"
    try:
        from pmlib import cli, hooks  # noqa: E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved
else:
    from pmlib import cli, hooks  # noqa: E402

from fakes import FakeClock, FakeHc, make_ctx  # noqa: E402
from pmlib.agents.turn_adapters import adapter_for  # noqa: E402
from pmlib.caller import Caller  # noqa: E402
from pmlib.events.supervisor import ProjectSupervisor, heartbeat_age_ms, touch_heartbeat  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.project import turn_reducer as tr  # noqa: E402
from pmlib.project.turn_state import TurnTracker  # noqa: E402
from pmlib.views.state import dash_state  # noqa: E402


class RuntimeAdaptersTests(unittest.TestCase):
    def test_adapters_cover_claude_codex_agy_pi_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 1. Claude adapter: reads tool_use, tool_result, end_turn, screen hints; ignores agy-transcript.json.
            c_path = root / "claude.jsonl"
            c_path.write_text(
                "\n".join([
                    json.dumps({
                        "type": "assistant",
                        "timestamp": "2026-11-25T12:00:01Z",
                        "message": {"content": [
                            {"type": "text", "text": "Checking files"},
                            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/tmp/x.py"}},
                        ]},
                    }),
                    json.dumps({
                        "type": "user",
                        "timestamp": "2026-11-25T12:00:02Z",
                        "message": {"content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok"}]},
                    }),
                    json.dumps({
                        "type": "assistant",
                        "timestamp": "2026-11-25T12:00:05Z",
                        "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Done"}]},
                    }),
                ]) + "\n",
                encoding="utf-8",
            )
            claude = adapter_for("claude-code")
            self.assertEqual(claude.kind, "claude")
            self.assertTrue(claude.steers_mid_turn)
            obs, off = claude.steps(c_path, 0)
            self.assertEqual([o["kind"] for o in obs], ["step_tool_start", "step_tool_end", "step_reply"])
            self.assertEqual(obs[0]["preamble"], "Checking files")
            self.assertEqual(claude.steps(c_path, off)[0], [])
            self.assertEqual(claude.screen_hint("12,400 tokens\n"), "tokens:12400")
            self.assertEqual(claude.screen_hint("Retrying (attempt 3)..."), "retry:3")

            # 2. Codex adapter
            x_path = root / "codex.jsonl"
            x_path.write_text(
                "\n".join([
                    json.dumps({"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "shell", "arguments": '{"command":"ls"}'}}),
                    json.dumps({"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "ok"}}),
                    json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}),
                ]) + "\n",
                encoding="utf-8",
            )
            codex = adapter_for("codex")
            x_obs, _ = codex.steps(x_path, 0)
            self.assertEqual([o["kind"] for o in x_obs], ["step_tool_start", "step_tool_end", "step_reply"])

            # 3. Agy adapter
            a_path = root / "agy.jsonl"
            a_path.write_text(
                "\n".join([
                    json.dumps({"type": "SYSTEM_MESSAGE", "content": "wake"}),
                    json.dumps({"type": "PLANNER_RESPONSE", "tool_calls": [{"id": "t1", "name": "grep_search", "args": {"Query": "foo"}}]}),
                    json.dumps({"type": "GENERIC"}),
                    json.dumps({"type": "ERROR_MESSAGE", "content": "503 retry attempt 2"}),
                    json.dumps({"type": "PLANNER_RESPONSE", "status": "DONE", "content": "All set."}),
                ]) + "\n",
                encoding="utf-8",
            )
            agy = adapter_for("antigravity")
            self.assertFalse(agy.steers_mid_turn)
            a_obs, _ = agy.steps(a_path, 0)
            self.assertEqual([o["kind"] for o in a_obs], ["step_system", "step_tool_start", "step_tool_end", "step_error", "step_reply"])

            # 4. Pi + fallback adapters
            pi = adapter_for("pi")
            self.assertEqual(pi.kind, "pi")
            fb = adapter_for("unknown-cli")
            self.assertEqual(fb.kind, "other")
            self.assertIsNone(fb.transcript_path({}, None))
            self.assertEqual(fb.steps(c_path, 0), ([], 0))
            self.assertEqual(fb.screen_hint("12,400 tokens"), "")


class SupervisorAndReaderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-turn-sup-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "demo"
        self.repo.mkdir()
        self.clock = FakeClock("2026-11-25 14:00:00")
        self.ctx = make_ctx(self.root / "ledger", clock=self.clock)
        self.slug = project_slug(self.repo)

    def _register_pm(self, *, runtime: str = "hc", terminal: str = "t12", agent: str = "claude") -> dict:
        rec = {
            "name": f"pm-{self.slug}",
            "project": "demo",
            "repo": str(self.repo),
            "pane": f"hc:{terminal}",
            "terminal": terminal,
            "runtime": runtime,
            "agent": agent,
        }
        self.ctx.store.change_registration(self.slug, lambda _cur: rec)
        self.ctx.hc.terminals[terminal] = {
            "address": terminal,
            "id": terminal,
            "state": "live",
            "cwd": str(self.repo),
            "labels": {"pm": "demo"},
            "status": {"state": "idle", "app": agent},
            "foreground": {"pid": 48291, "argv": [agent]},
            "turn": 454,
            "screen": "Thinking...",
        }
        return rec

    def test_screen_probe_throttling_and_dedup(self) -> None:
        rec = self._register_pm()
        read_calls: list[str] = []
        screens = ["spin 1"]

        def spy_read(term: str, **kw) -> str:
            read_calls.append(term)
            return screens[0]

        self.ctx.hc.read = spy_read  # type: ignore[method-assign]
        sup = ProjectSupervisor(self.ctx, self.repo)

        # Enter `working` at t=0 -> first 10s must NEVER call hc.read().
        self.ctx.hc.set_status("t12", "working", status_ms=int(self.clock.time() * 1000))
        info = self.ctx.hc.get_raw("t12")
        sup.observe_and_reduce(rec, info)
        self.clock.advance(4)
        sup.observe_and_reduce(rec, info)
        self.clock.advance(4)
        sup.observe_and_reduce(rec, info)
        self.assertEqual(read_calls, [])

        # At t=11s (>=10s quiet) -> 1st screen probe runs.
        self.clock.advance(3)
        sup.observe_and_reduce(rec, info)
        self.assertEqual(len(read_calls), 1)
        # 2s later (<5s interval) -> throttled.
        self.clock.advance(2)
        sup.observe_and_reduce(rec, info)
        self.assertEqual(len(read_calls), 1)
        # 3s later (>=5s interval), screen still identical -> 2nd probe runs, logs freeze transition (`changed=False`).
        self.clock.advance(3)
        sup.observe_and_reduce(rec, info)
        self.assertEqual(len(read_calls), 2)
        entries_before = TurnTracker(self.ctx, self.slug).read_journal_entries()
        pty_entries = [e for e in entries_before if e.get("kind") == "pty_probe"]
        self.assertEqual([e["changed"] for e in pty_entries], [True, False])

        # 5s later, still identical -> 3rd probe runs, deduped (still 2 pty_probe entries, no spam).
        self.clock.advance(5)
        sup.observe_and_reduce(rec, info)
        self.assertEqual(len(read_calls), 3)
        entries_dedup = TurnTracker(self.ctx, self.slug).read_journal_entries()
        self.assertEqual(len([e for e in entries_dedup if e.get("kind") == "pty_probe"]), 2)

        # Advance 15s -> enters `suspect` (frozen >= 20s), probe interval tightens to 1s.
        self.clock.advance(15)
        st, due = sup.observe_and_reduce(rec, info)
        self.assertEqual(st["turn"]["health"], "suspect")
        self.assertEqual(due, 1.0)

    def test_heartbeat_stale_returns_unknown_and_auto_revives_on_both_readers(self) -> None:
        rec = self._register_pm()
        sup = ProjectSupervisor(self.ctx, self.repo)
        self.ctx.hc.set_status("t12", "working", status_ms=int(self.clock.time() * 1000))
        sup.observe_and_reduce(rec, self.ctx.hc.get_raw("t12"))

        # Fresh heartbeat (<= 10s): both `state` and `project events` return `supervised: True`, health != unknown.
        self.clock.advance(5)
        st_fresh = dash_state(self.ctx)
        self.ctx.out.clear()
        cli.main(["project", "events", self.slug], ctx=self.ctx)
        ev_fresh = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertTrue(st_fresh["pms"][0]["supervised"])
        self.assertTrue(ev_fresh["supervised"])
        self.assertEqual(st_fresh["pms"][0]["turn2"]["turn"]["id"], "hc:local:t12:48291:455")
        self.assertEqual(ev_fresh["turn2"]["turn"]["id"], "hc:local:t12:48291:455")
        self.assertEqual(self.ctx.procs.spawned, [])

        # Advance past 10s without touching heartbeat -> stale!
        self.clock.advance(12)
        beat_path = self.ctx.home.project(self.slug).pm_turn_beat
        self.assertGreater(heartbeat_age_ms(beat_path, int(self.clock.time() * 1000)) or 0, 10_000)

        st_stale = dash_state(self.ctx)
        self.assertFalse(st_stale["pms"][0]["supervised"])
        self.assertEqual(st_stale["pms"][0]["turn"]["health"], "unknown")
        self.assertFalse(st_stale["pms"][0]["turn"]["stalled"])
        self.assertEqual(st_stale["pms"][0]["turn2"]["turn"]["health"], "unknown")
        # Auto-revival triggered on `pm.py state` read!
        self.assertEqual([s["args"][0] for s in self.ctx.procs.spawned], ["deliver"])

        self.ctx.procs.spawned.clear()
        self.ctx.out.clear()
        cli.main(["project", "events", self.slug], ctx=self.ctx)
        ev_stale = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertFalse(ev_stale["supervised"])
        self.assertEqual(ev_stale["turn"]["health"], "unknown")
        self.assertEqual(ev_stale["turn2"]["turn"]["health"], "unknown")
        # Auto-revival triggered on `pm.py project events` read!
        self.assertEqual([s["args"][0] for s in self.ctx.procs.spawned], ["deliver"])

    def test_harmonized_hc_detection_when_runtime_omitted_but_pane_starts_with_hc(self) -> None:
        # P0 note: `runtime` omitted on registration, only `pane: "hc:t12"` set -> both readers behave identically.
        self._register_pm(runtime="", terminal="t12")
        self.ctx.hc.set_status("t12", "working", msg="typing", status_ms=int(self.clock.time() * 1000))
        touch_heartbeat(self.ctx.home.project(self.slug).pm_turn_beat, self.clock.time())
        TurnTracker(self.ctx, self.slug).append_observation(
            {
                "src": "supervisor",
                "kind": "hc_state",
                "state": "live",
                "status": "working",
                "status_ms": int(self.clock.time() * 1000),
                "turn": 454,
                "reported": True,
                "endpoint": {"runtime": "hc", "machine": None, "terminal": "t12", "fg_pid": 48291, "epoch": 1},
            },
            reduce_now=True,
        )
        st = dash_state(self.ctx)
        self.ctx.out.clear()
        cli.main(["project", "events", self.slug], ctx=self.ctx)
        ev = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertEqual(st["pms"][0]["turn"]["phase"], "working")
        self.assertEqual(ev["turn"]["phase"], "working")
        self.assertEqual(st["pms"][0]["turn2"]["turn"]["id"], ev["turn2"]["turn"]["id"])

    def test_pi_hook_events_and_turn_journal_export_redaction(self) -> None:
        self._register_pm(agent="pi", terminal="t12")
        self.ctx.pane = "hc:t12"
        self.ctx.hc_terminal = "t12"
        self.ctx.caller = Caller(self.ctx)

        for payload in (
            {"hook_event_name": "AgentStart", "cwd": str(self.repo), "session_id": "pi-secret-sid-999"},
            {"hook_event_name": "ToolStart", "cwd": str(self.repo), "tool_name": "bash", "tool_summary": "curl -H 'Authorization: Bearer sk-ant-secret12345678' /Users/alice/work/app"},
            {"hook_event_name": "ToolEnd", "cwd": str(self.repo), "tool_name": "bash"},
            {"hook_event_name": "Stop", "cwd": str(self.repo), "last_assistant_message": "contact bob@example.com"},
        ):
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
                hooks.cmd_hook_turn(None, ctx=self.ctx)

        # Also check monotonic seq on journal file:
        entries = TurnTracker(self.ctx, self.slug).read_journal_entries()
        seqs = [e["seq"] for e in entries]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))

        # Export sanitized journal slice via CLI and replay it cleanly!
        out_file = self.root / "exported.jsonl"
        self.ctx.out.clear()
        cli.main(
            ["turn-journal", "export", self.slug, "--since", "1h", "--out", str(out_file)],
            ctx=self.ctx,
        )
        meta = json.loads(self.ctx.out.stdout.strip().splitlines()[-1])
        self.assertTrue(meta["ok"])
        exported_text = out_file.read_text(encoding="utf-8")
        self.assertNotIn("alice", exported_text)
        self.assertNotIn("sk-ant-secret12345678", exported_text)
        self.assertNotIn("pi-secret-sid-999", exported_text)
        self.assertIn("sess_1", exported_text)
        self.assertIn("[REDACTED", exported_text)

        # Replay exported JSONL directly through pure reducer:
        replayed = tr.default_state_v2()
        for line in exported_text.splitlines():
            replayed = tr.reduce(replayed, json.loads(line))
        self.assertEqual(replayed["turn"]["phase"], "idle")
        self.assertEqual(replayed["last_turn"]["outcome"], "replied")


class IdleHeartbeatReproTests(unittest.TestCase):
    """Phase 5 idle heartbeat decoupling: `look()` sleeps up to RECONCILE (60s) when PM is idle, while
    `_wait_with_heartbeat` refreshes `pm-turn.beat` every ~3s with ZERO `hc get` calls or journal bloat."""

    def test_idle_pm_with_live_deliverer_stays_supervised_without_hc_get_polling(self) -> None:
        from pmlib.events.deliverer import Deliverer
        from pmlib.terminals.events import RECONCILE

        class _ClockAdvancingWaiter:
            def __init__(self, clock: FakeClock, *, wake_on_call: int | None = None) -> None:
                self.clock = clock
                self.wake_on_call = wake_on_call
                self.waits: list[float] = []

            def wait(self, timeout: float) -> bool:
                self.waits.append(float(timeout))
                self.clock.advance(float(timeout))
                return self.wake_on_call is not None and len(self.waits) >= self.wake_on_call

        with tempfile.TemporaryDirectory() as tmp:
            repo_p = Path(tmp) / "demo"
            repo_p.mkdir()
            repo = str(repo_p.resolve())
            clk = FakeClock("2026-11-25 14:00:00")
            hc = FakeHc(terminals={"t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}}}, clock=clk)
            ctx = make_ctx(tmp, hc=hc, clock=clk)
            slug = project_slug(repo)
            rec = {"name": f"pm-{slug}", "project": "demo", "repo": repo, "runtime": "hc",
                   "terminal": "t7", "pane": "hc:t7", "agent": "claude"}
            ctx.home.registrations.mkdir(parents=True, exist_ok=True)
            ctx.home.registration(slug).write_text(json.dumps(rec), encoding="utf-8")
            dlv = Deliverer(ctx, repo, watchers=(), holds=(), settle=0)
            waiter = _ClockAdvancingWaiter(clk)
            due = dlv.look(waiter, {}, {})
            self.assertEqual(due, float(RECONCILE))

            hc_calls_before = sum(1 for c in hc.calls if c[0] == "get")
            woke = dlv._wait_with_heartbeat(waiter, due)
            self.assertFalse(woke)
            hc_calls_after = sum(1 for c in hc.calls if c[0] == "get")
            # Zero `hc get` calls during the entire 60s idle wait, yet `supervised` stays True!
            self.assertEqual(hc_calls_after, hc_calls_before)
            self.assertGreater(len(waiter.waits), 10)
            pm = dash_state(ctx)["pms"][0]
            self.assertTrue(pm["supervised"], (due, pm["turn2"]["turn"]["health"]))
            self.assertEqual(ctx.procs.spawned, [])

            # Real file/hc wakeup returns True immediately without waiting the full 60s.
            wake_waiter = _ClockAdvancingWaiter(clk, wake_on_call=1)
            self.assertTrue(dlv._wait_with_heartbeat(wake_waiter, 60.0))
            self.assertEqual(len(wake_waiter.waits), 1)

    def test_idle_heartbeat_refresh_cycles_without_journal_bloat(self) -> None:
        from pmlib.events.deliverer import Deliverer
        from pmlib.terminals.events import RECONCILE

        class _ClockAdvancingWaiter:
            def __init__(self, clock: FakeClock) -> None:
                self.clock = clock

            def wait(self, timeout: float) -> bool:
                self.clock.advance(float(timeout))
                return False

        with tempfile.TemporaryDirectory() as tmp:
            repo_p = Path(tmp) / "demo"
            repo_p.mkdir()
            repo = str(repo_p.resolve())
            clk = FakeClock("2026-11-25 14:00:00")
            hc = FakeHc(terminals={"t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}}}, clock=clk)
            ctx = make_ctx(tmp, hc=hc, clock=clk)
            slug = project_slug(repo)
            rec = {"name": f"pm-{slug}", "project": "demo", "repo": repo, "runtime": "hc",
                   "terminal": "t7", "pane": "hc:t7", "agent": "claude"}
            ctx.home.registrations.mkdir(parents=True, exist_ok=True)
            ctx.home.registration(slug).write_text(json.dumps(rec), encoding="utf-8")
            dlv = Deliverer(ctx, repo, watchers=(), holds=(), settle=0)
            waiter = _ClockAdvancingWaiter(clk)
            journal_path = ctx.home.project_for(repo).pm_turn_journal
            initial_lines = None
            total_waited = 0.0
            for _ in range(3):
                due = dlv.look(waiter, {}, {})
                self.assertEqual(due, float(RECONCILE))
                if initial_lines is None:
                    initial_lines = len(journal_path.read_text(encoding="utf-8").splitlines())
                else:
                    self.assertEqual(len(journal_path.read_text(encoding="utf-8").splitlines()), initial_lines)
                hc_before = sum(1 for c in hc.calls if c[0] == "get")
                t_before = clk.monotonic()
                dlv._wait_with_heartbeat(waiter, due)
                total_waited += clk.monotonic() - t_before
                self.assertEqual(sum(1 for c in hc.calls if c[0] == "get"), hc_before)
                self.assertEqual(len(journal_path.read_text(encoding="utf-8").splitlines()), initial_lines)
                pm = dash_state(ctx)["pms"][0]
                self.assertTrue(pm["supervised"], (due, pm["turn2"]["turn"]["health"]))
                self.assertEqual(pm["turn2"]["turn"]["health"], "ok")
                self.assertEqual(ctx.procs.spawned, [])
            self.assertGreater(total_waited, 150.0)


class Phase2TurnsCliAndOccupationFeedbackTests(unittest.TestCase):
    """Phase 2 (`O-a`, `O-c`, D7): `turn_summary` journal writes, `pm.py turns <slug>`, and 10-min rate-limited budget hints."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-turn-p2-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "demo"
        self.repo.mkdir()
        self.clock = FakeClock("2026-11-26 10:00:00")
        self.hc = FakeHc(
            terminals={"t12": {"address": "t12", "state": "live", "status": {"state": "idle"}, "turn": 1, "foreground": {"pid": 4200}}},
            clock=self.clock,
        )
        self.ctx = make_ctx(self.root / "ledger", hc=self.hc, clock=self.clock)
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

    def test_turn_completion_writes_turn_summary_to_journal_and_pm_turns_cli_redacts(self) -> None:
        tracker = TurnTracker(self.ctx, self.slug)
        # Turn 1: user turn taking 70s with a secret in tool summary
        tracker.begin_turn(terminal="hc:t12", agent_kind="claude", cause="user", from_hook=True)
        self.clock.advance(20.0)
        tracker.note_activity(kind="tool", tool="Write", summary=f"{self.repo}/brief.md sk-ant-secretkey1234567890")
        self.clock.advance(40.0)
        tracker.note_activity(kind="thinking")
        self.clock.advance(10.0)
        tracker.end_turn(has_reply=True)

        # Turn 2: fast user turn taking 12s
        self.clock.advance(5.0)
        tracker.begin_turn(terminal="hc:t12", agent_kind="claude", cause="user", from_hook=True)
        self.clock.advance(12.0)
        tracker.end_turn(has_reply=True)

        entries = tracker.read_journal_entries()
        summaries = [e for e in entries if e.get("kind") == "turn_summary"]
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["total_ms"], 70_000)
        self.assertEqual(summaries[0]["generate_ms"], 30_000)
        self.assertEqual(summaries[0]["tool_ms"], 40_000)
        self.assertTrue(summaries[0]["over_soft"])
        self.assertEqual(summaries[1]["total_ms"], 12_000)
        self.assertFalse(summaries[1]["over_soft"])

        # CLI `pm.py turns <slug> --since 24h --json`
        out_json = io.StringIO()
        a_json = cli.build_parser().parse_args(["turns", self.slug, "--since", "24h", "--json"])
        with mock.patch.object(self.ctx.out, "line", side_effect=lambda s: out_json.write(s + "\n")):
            cli.COMMANDS["turns"][0].cmd_turns(a_json, ctx=self.ctx)
        raw_text = out_json.getvalue()
        self.assertNotIn("sk-ant-secretkey1234567890", raw_text)
        self.assertNotIn(str(self.repo), raw_text)
        data = json.loads(raw_text)
        self.assertEqual(data["total_turns"], 2)
        self.assertEqual(data["user"]["over_soft"], 1)
        self.assertEqual(data["user"]["max_ms"], 70_000)
        self.assertEqual(data["top_actions"][0]["category"], "generate")
        self.assertEqual(data["top_actions"][1]["category"], "Write")
        self.assertEqual(data["top_actions"][1]["total_ms"], 40_000)

        # Human-readable output
        out_txt = io.StringIO()
        a_txt = cli.build_parser().parse_args(["turns", self.slug, "--since", "24h"])
        with mock.patch.object(self.ctx.out, "line", side_effect=lambda s: out_txt.write(s + "\n")):
            cli.COMMANDS["turns"][0].cmd_turns(a_txt, ctx=self.ctx)
        txt = out_txt.getvalue()
        self.assertIn("p50=", txt)
        self.assertIn("p90=", txt)
        self.assertIn("Write", txt)

    def test_occupation_hint_attaches_before_next_delivered_payload_and_rate_limits_10m(self) -> None:
        from pmlib.events.deliver import batch_stretch, prompt_kind
        from pmlib.events.supervisor import attach_occupation_hint

        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({"lang": "zh"}), encoding="utf-8")
        tracker = TurnTracker(self.ctx, self.slug)

        # Turn 1: user turn 65s (>45s soft budget)
        tracker.begin_turn(terminal="hc:t12", agent_kind="claude", cause="user", from_hook=True)
        self.clock.advance(25.0)
        tracker.note_activity(kind="tool", tool="Write", summary="briefs/x.md")
        self.clock.advance(40.0)
        tracker.end_turn(has_reply=True)

        raw_batch = "[from pm.py deliver] 1 条事件 (0-100)\n1. [worker t2] task-1: review"
        delivered = attach_occupation_hint(self.ctx, tracker, raw_batch)
        self.assertTrue(delivered.startswith("〔占用提示〕"))
        self.assertIn("65 秒", delivered)
        self.assertIn("dispatch --ask", delivered)
        # Hint must NOT break batch recognition or byte-stretch parsing!
        self.assertEqual(prompt_kind(delivered)[0], "batch")
        self.assertEqual(batch_stretch(delivered), (0, 100))

        # Second over-budget user turn 2 minutes later -> suppressed by 10-minute rate limit!
        self.clock.advance(120.0)
        tracker.begin_turn(terminal="hc:t12", agent_kind="claude", cause="user", from_hook=True)
        self.clock.advance(75.0)
        tracker.end_turn(has_reply=True)
        self.assertEqual(attach_occupation_hint(self.ctx, tracker, raw_batch), raw_batch)

        # Third over-budget user turn >10 minutes after the first hint -> attaches again!
        self.clock.advance(605.0)
        tracker.begin_turn(terminal="hc:t12", agent_kind="claude", cause="user", from_hook=True)
        self.clock.advance(55.0)
        tracker.end_turn(has_reply=True)
        delivered2 = attach_occupation_hint(self.ctx, tracker, raw_batch)
        self.assertTrue(delivered2.startswith("〔占用提示〕"))
        self.assertIn("55 秒", delivered2)


if __name__ == "__main__":
    unittest.main()
