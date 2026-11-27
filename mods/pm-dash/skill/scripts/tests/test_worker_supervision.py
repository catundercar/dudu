"""Tests for Phase 5 worker supervision via `turn_reducer`, `EndpointTurnStore`, worker budgets, W3/W4/W5 ladders,
and I4 partition safety."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import FakeClock, FakeHc, FakeProcs, make_ctx  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.messaging.address import parse_legacy_endpoint, safe_endpoint_uid  # noqa: E402
from pmlib.messaging.transport import ObserveBatch  # noqa: E402
from pmlib.messaging.transports.local_hc import LocalHcTransport  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.turn_reducer import DEFAULT_WORKER_TURN_CONFIG, worker_turn_config_from_dict  # noqa: E402
from pmlib.project.turn_state import EndpointTurnStore  # noqa: E402


AGY_TRUST_SCREEN = (
    "Workspace Trust Required\n"
    "Do you trust this workspace?\n"
    "/Users/dev/.herdr/worktrees/dudu/dev-worker-sup-wt\n\n"
    "  ▸ 1. Trust this workspace\n"
    "    2. Cancel\n"
)

QUOTA_SCREEN = (
    "Error: RateLimitError 429 quota exceeded for current model.\n"
    "Please retry later or switch profile.\n"
)


class _PartitioningTransport:
    """Test `Transport` delegating to `LocalHcTransport` unless `disconnected` is toggled on."""

    def __init__(self, inner: LocalHcTransport) -> None:
        self.inner = inner
        self.disconnected = False

    def observe(self, endpoint, cursors, *, include_screen: bool = False, include_procs: bool = False):
        if self.disconnected:
            now_ms = int(float(self.inner.ctx.clock.time()) * 1000)
            return ObserveBatch(
                link_state="disconnected",
                observations=({"src": "transport", "kind": "link_state", "link_state": "disconnected", "t": now_ms},),
                next_cursors=dict(cursors),
                terminal_info=None,
            )
        return self.inner.observe(endpoint, cursors, include_screen=include_screen, include_procs=include_procs)

    def interrupt(self, endpoint, *, timeout_s: float = 5.0):
        return self.inner.interrupt(endpoint, timeout_s=timeout_s)

    def unblock_prompt(self, endpoint, keys):
        return self.inner.unblock_prompt(endpoint, keys)


class WorkerSupervisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir(parents=True)
        self.repo = str(self.repo_path.resolve())
        self.slug = project_slug(self.repo)
        self.clk = FakeClock("2026-11-26 10:00:00")

    def _setup_worker(
        self,
        *,
        term: str = "t20",
        task_id: str = "demo-w1",
        worker_kind: str = "agy",
        screen: str = "working...",
        foreground_tool_stat=None,
        tool_alive_fn=None,
        worktree: str = "",
        extra_config: dict | None = None,
    ):
        hc = FakeHc(
            terminals={
                term: {
                    "state": "live",
                    "pid": 2000,
                    "turn": 1,
                    "status": {"state": "working"},
                    "status_ms": int(self.clk.time() * 1000),
                    "screen": screen,
                }
            },
            clock=self.clk,
        )
        ctx = make_ctx(self.tmp.name, hc=hc, clock=self.clk, config=extra_config)
        if foreground_tool_stat is not None:
            procs = FakeProcs(ctx.home, env=ctx.env, foreground_tool_stat=foreground_tool_stat)
            if tool_alive_fn is not None:
                procs._tool_alive_fn = tool_alive_fn
            ctx.procs = procs
        if worktree:
            ctx.git.owned_worktrees.add(worktree)

        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx.home.registration(self.slug).write_text(
            json.dumps({
                "name": f"pm-{self.slug}",
                "project": "demo",
                "repo": self.repo,
                "runtime": "hc",
                "terminal": "t7",
                "pane": "hc:t7",
            }),
            encoding="utf-8",
        )
        ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        task = {
            "id": task_id,
            "title": "worker supervision test",
            "repo": self.repo,
            "project": "demo",
            "status": "in_progress",
            "pane": f"hc:{term}",
            "dispatched": True,
            "worktree": worktree,
            "worker": {"kind": worker_kind},
            "round": {"terminal": term, "at": self.clk.now(), "turn": 1},
            "created": self.clk.now(),
            "log": [],
        }
        ctx.home.task(task_id).write_text(json.dumps(task), encoding="utf-8")
        return ctx, hc, task

    def _store_for(self, ctx, term: str = "t20") -> EndpointTurnStore:
        ep = parse_legacy_endpoint(f"hc:{term}", runtime_hint="hc")
        return EndpointTurnStore(ctx, ep, repo=self.repo)

    def test_worker_turn_config_defaults_and_overrides(self) -> None:
        pm_only = {"pm": {"turn": {"tool_hard_ms": 120_000, "generating_pty_stall_ms": 30_000}, "recovery": {"allow_trust": False}}}
        w_cfg = worker_turn_config_from_dict(pm_only)
        # Worker defaults to safe `recovery_auto="off"` (never kills worker commands automatically) & longer budgets.
        self.assertEqual(DEFAULT_WORKER_TURN_CONFIG.recovery_auto, "off")
        self.assertEqual(DEFAULT_WORKER_TURN_CONFIG.generating_no_step_stall_ms, 0)
        self.assertEqual(w_cfg.recovery_auto, "off")
        self.assertEqual(w_cfg.generating_no_step_stall_ms, 0)
        self.assertEqual(w_cfg.tool_hard_ms, DEFAULT_WORKER_TURN_CONFIG.tool_hard_ms)
        self.assertEqual(w_cfg.generating_pty_stall_ms, DEFAULT_WORKER_TURN_CONFIG.generating_pty_stall_ms)
        # But inherits allow_trust fallback from pm.recovery if worker.recovery omits it.
        self.assertFalse(w_cfg.recovery_allow_trust)

        custom = {
            "pm": {"turn": {"tool_hard_ms": 180_000}},
            "worker": {
                "turn": {"tool_hard_ms": 3_600_000, "generating_pty_stall_ms": 240_000},
                "recovery": {"auto": "full", "allow_trust": False},
            },
        }
        w_custom = worker_turn_config_from_dict(custom)
        self.assertEqual(w_custom.tool_hard_ms, 3_600_000)
        self.assertEqual(w_custom.generating_pty_stall_ms, 240_000)
        self.assertEqual(w_custom.recovery_auto, "full")
        self.assertFalse(w_custom.recovery_allow_trust)

    def test_long_running_worker_command_and_generation_do_not_false_stall(self) -> None:
        cpu = [100]
        ctx, hc, task = self._setup_worker(
            foreground_tool_stat=lambda _info: {"tool_pid": 4242, "cmd": "pytest -q", "cpu_ms": cpu[0]}
        )
        watcher = StallWatcher(ctx, stall_grace=0)
        stops, bases = {}, {}

        # Step through 250s with active CPU tool progress (exceeds PM's 180s tool_hard_ms).
        for step in range(25):
            watcher.watch_workers([task], stops, bases)
            self.clk.advance(10.0)
            cpu[0] += 500
        self.assertEqual(Conversation(ctx, self.repo).events(), [])
        st = self._store_for(ctx).read()
        self.assertEqual(st["turn"]["phase"], "tool")
        self.assertIn(st["turn"]["health"], ("ok", "slow"))

        # Transition back to generating with advancing PTY output for 300s (exceeds PM's 45s pty stall).
        ctx.procs = FakeProcs(ctx.home, env=ctx.env)
        for i in range(30):
            hc.terminals["t20"]["screen"] = f"generating chunk {i}\n"
            watcher.watch_workers([task], stops, bases)
            self.clk.advance(10.0)
        self.assertEqual(Conversation(ctx, self.repo).events(), [])
        st = self._store_for(ctx).read()
        self.assertEqual(st["turn"]["phase"], "generating")
        self.assertIn(st["turn"]["health"], ("ok", "slow"))

    def test_worker_frozen_screen_auto_unblocks_safe_trust_dialog(self) -> None:
        wt = str(Path.home() / ".herdr" / "worktrees" / "dudu" / "dev-worker-sup-wt")
        ctx, hc, task = self._setup_worker(screen=AGY_TRUST_SCREEN, worktree=wt)
        watcher = StallWatcher(ctx, stall_grace=0)
        stops, bases = {}, {}

        # Freeze past worker generating_pty_probe_after_ms (30s) + generating_pty_stall_ms (180s).
        for _ in range(25):
            watcher.watch_workers([task], stops, bases)
            self.clk.advance(10.0)

        self.assertIn(["enter"], hc.terminals["t20"].get("keys") or [])
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertEqual(stalls, [])

    def test_worker_frozen_screen_escalates_quota_and_unknown_hang_with_hints(self) -> None:
        ctx, hc, task = self._setup_worker(screen=QUOTA_SCREEN)
        watcher = StallWatcher(ctx, stall_grace=0)
        stops, bases = {}, {}

        for _ in range(25):
            watcher.watch_workers([task], stops, bases)
            self.clk.advance(10.0)

        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertTrue(stalls)
        self.assertIn("quota/rate limit", stalls[-1]["text"])
        self.assertIn("escalate", stalls[-1]["text"])

        # Now test an unknown frozen screen (no dialog) -> W5 escalates to PM with triage hint, never rotates.
        ctx2, _, task2 = self._setup_worker(term="t21", task_id="demo-w2", screen="Thinking forever...\n")
        watcher2 = StallWatcher(ctx2, stall_grace=0)
        stops2, bases2 = {}, {}
        for _ in range(30):
            watcher2.watch_workers([task2], stops2, bases2)
            self.clk.advance(10.0)
        stalls2 = [e for e in Conversation(ctx2, self.repo).events() if e.get("type") == "stall"]
        self.assertTrue(stalls2)
        self.assertIn("triage demo-w2", stalls2[-1]["text"])
        self.assertEqual([s for s in ctx2.procs.spawned if "rotate" in (s.get("args") or [])], [])

    def test_worker_default_recovery_off_escalates_w4_without_killing_tool(self) -> None:
        ctx, _, task = self._setup_worker(
            foreground_tool_stat=lambda _info: {"tool_pid": 5252, "cmd": "npm test", "cpu_ms": 100},
            tool_alive_fn=lambda _pid, _agent: True,
        )
        watcher = StallWatcher(ctx, stall_grace=0)
        stops, bases = {}, {}

        # Advance past W4 threshold under default `worker.recovery.auto == "off"`.
        for _ in range(55):
            watcher.watch_workers([task], stops, bases)
            self.clk.advance(10.0)

        # Must NEVER signal/kill the foreground tool by default; instead emits a stall alert to the PM.
        self.assertEqual(ctx.procs.signaled_tools, [])
        stalls = [e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"]
        self.assertTrue(stalls)
        self.assertIn("tool_waiting_input", stalls[-1]["text"])
        self.assertIn("triage demo-w1", stalls[-1]["text"])

    def test_worker_flat_cpu_command_triggers_w4_interrupt_tool_when_opted_in(self) -> None:
        alive = [True]
        ctx, _, task = self._setup_worker(
            foreground_tool_stat=lambda _info: {"tool_pid": 5151, "cmd": "npm test", "cpu_ms": 100} if alive[0] else {"tool_pid": 0, "cmd": "", "cpu_ms": 0},
            tool_alive_fn=lambda _pid, _agent: alive[0],
            extra_config={"worker": {"recovery": {"auto": "safe"}}},
        )
        watcher = StallWatcher(ctx, stall_grace=0)
        stops, bases = {}, {}

        # Advance until W4 signals tool_pid=5151 (do not outrun SIGINT->SIGTERM->SIGKILL escalation before exit).
        for _ in range(55):
            watcher.watch_workers([task], stops, bases)
            if ctx.procs.signaled_tools:
                break
            self.clk.advance(10.0)

        self.assertTrue(ctx.procs.signaled_tools)
        self.assertEqual(ctx.procs.signaled_tools[0]["tool_pid"], 5151)

        # Tool exits -> W4 resolves back to ok generating without stalling PM.
        alive[0] = False
        self.clk.advance(6.0)
        watcher.watch_workers([task], stops, bases)
        st = self._store_for(ctx).read()
        self.assertEqual(st["turn"]["phase"], "generating")
        self.assertIn(st["turn"]["health"], ("ok", "slow"))
        self.assertEqual([e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"], [])

    def test_obs_journal_monotonic_and_i4_partition_pauses_timers(self) -> None:
        ctx, _, task = self._setup_worker(
            foreground_tool_stat=lambda _info: {"tool_pid": 6161, "cmd": "cargo build", "cpu_ms": 100},
        )
        transport = _PartitioningTransport(LocalHcTransport(ctx))
        watcher = StallWatcher(ctx, stall_grace=0, transport=transport)
        stops, bases = {}, {}

        # Observe active tool first.
        watcher.watch_workers([task], stops, bases)
        self.clk.advance(10.0)
        watcher.watch_workers([task], stops, bases)

        ep = parse_legacy_endpoint("hc:t20", runtime_hint="hc")
        ep_dir = ctx.home.project_for(self.repo).endpoint_mailbox(safe_endpoint_uid(ep))
        self.assertTrue((ep_dir / "obs-journal.jsonl").is_file())
        self.assertTrue((ep_dir / "turn.state.json").is_file())
        entries = self._store_for(ctx).read_journal_entries()
        seqs = [e["seq"] for e in entries]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))

        # Now partition the transport (`link_state == "disconnected"`) and jump past 2000s (> tool_hard_ms).
        transport.disconnected = True
        for _ in range(5):
            self.clk.advance(500.0)
            watcher.watch_workers([task], stops, bases)

        st = self._store_for(ctx).read()
        self.assertEqual(st["link_state"], "disconnected")
        self.assertEqual([e for e in Conversation(ctx, self.repo).events() if e.get("type") == "stall"], [])


if __name__ == "__main__":
    unittest.main()
