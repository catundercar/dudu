"""Context-isolated unit tests for `Helpers(ctx)`, `HelperWatcher(ctx)`, and `helpers/config.py` (Stage 4b).

Zero `pm.*` monkeypatches, zero global state, zero real filesystem touches outside `TemporaryDirectory`.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pmlib.agents.profiles import WorkerSpec
from pmlib.errors import NotFound, Refused
from pmlib.events.deliver import Delivery
from pmlib.helpers.config import helper_placement_for, resolve_helper_spec
from pmlib.helpers.records import (
    finalize_helper_for,
    helper_entries,
    helper_wait_guard_for,
    kill_helper_terminal_for,
)
from pmlib.helpers.service import HelperStartRequest, Helpers
from pmlib.helpers.watch import HelperWatcher
from pmlib.home import project_slug
from pmlib.project.conversation import Conversation
from pmlib.store import lock_file, unlock_file
from tests.fakes import FakeClock, FakeHc, FakeProcs, make_ctx


class HelpersServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home_dir = self.root / "ledger"
        self.repo = self.root / "demo"
        self.repo.mkdir(parents=True)
        self.slug = project_slug(str(self.repo))
        self.cfg = {
            "helpers": {"profile": "neon-medium"},
            "profiles": {
                "neon-medium": {"kind": "agy", "model": "gemini-4-neon-medium"},
                "opus": {"kind": "agy", "model": "claude-opus-5-5-medium"},
                "neon": {"kind": "agy", "model": "gemini-4-neon-high"},
            },
            "agents": {
                "agy": {"argv": ["agy", "--dangerously-skip-permissions"], "model": ["--model", "{}"], "effort": []},
            },
        }
        self.clock = FakeClock("2026-11-23 10:00:00", mono=100.0)
        self.hc = FakeHc(clock=self.clock)
        self.procs = FakeProcs(self.home_dir)
        self.pm_term = "t1"
        self.worker_term = "t2"
        self.task_id = f"{self.slug}-work"
        self.hc.terminals[self.pm_term] = {
            "address": self.pm_term, "name": f"pm-{self.slug}", "state": "live",
            "labels": {"pm": self.repo.name}, "status": {"state": "idle"}, "turn": 1,
        }
        self.hc.terminals[self.worker_term] = {
            "address": self.worker_term, "name": "worker-1", "state": "live",
            "labels": {"task": self.task_id}, "status": {"state": "working"}, "turn": 1,
        }
        self.ctx = self._ctx_for(self.pm_term)
        self.ctx.store.change_registration(self.slug, lambda _: {
            "name": f"pm-{self.slug}", "project": self.repo.name, "repo": str(self.repo),
            "runtime": "hc", "terminal": self.pm_term, "pane": f"hc:{self.pm_term}", "claimed": self.clock.now(),
        })
        self.ctx.store.change_task(self.task_id, lambda _: {
            "id": self.task_id, "title": "Feature work", "project": self.repo.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "pane": f"hc:{self.worker_term}",
            "worktree": str(self.repo), "created": self.clock.now(), "updated": self.clock.now(),
            "log": [], "dispatched": True,
        })

    def _ctx_for(self, term: str, *, env: dict[str, str] | None = None):
        return make_ctx(
            self.home_dir,
            pane=f"hc:{term}" if term else "",
            hc_terminal=term,
            hc=self.hc,
            clock=self.clock,
            procs=self.procs,
            config=self.cfg,
            env=env or {},
        )

    def test_resolve_helper_spec_honors_helpers_profile_and_refuses_unknown(self) -> None:
        # Config helpers.profile ("neon-medium") takes priority over opus/neon/light.
        spec = resolve_helper_spec(self.ctx, HelperStartRequest())
        self.assertEqual((spec.profile, spec.kind, spec.model), ("neon-medium", "agy", "gemini-4-neon-medium"))

        # Explicit --profile overrides helpers.profile.
        spec2 = resolve_helper_spec(self.ctx, HelperStartRequest(profile="opus"))
        self.assertEqual((spec2.profile, spec2.kind, spec2.model), ("opus", "agy", "claude-opus-5-5-medium"))

        # Explicit --kind without --profile respects that kind without forcing default profile's model.
        spec3 = resolve_helper_spec(self.ctx, HelperStartRequest(kind="claude", model="sonnet"))
        self.assertEqual((spec3.profile, spec3.kind, spec3.model), ("", "claude", "sonnet"))

        # Unknown profile raises Refused (never sys.exit).
        with self.assertRaises(Refused) as cm:
            resolve_helper_spec(self.ctx, HelperStartRequest(profile="nonexistent"))
        self.assertIn("no profile nonexistent", str(cm.exception))

    def test_start_dry_run_and_sync_releases_start_lock_before_send_when_ready(self) -> None:
        svc = Helpers(self.ctx)
        dry = svc.start(HelperStartRequest(
            prompt="Inspect module", name="inspect", kind="claude", model="sonnet",
            dry_run=True, repo=str(self.repo),
        ))
        self.assertIsNotNone(dry.dry_run_plan)
        assert dry.dry_run_plan is not None
        self.assertEqual(dry.dry_run_plan["what"], "helper")
        self.assertIn("--disallowedTools", dry.dry_run_plan["argv"])
        self.assertEqual(helper_entries(self.ctx.store.registration(self.slug)), [])

        # Verify helper-start-<slug>.lock is NOT held during send_when_ready.
        start_lock = self.ctx.home.locks / f"helper-start-{self.slug}.lock"
        lock_free_during_send: list[bool] = []
        orig_send = self.hc.send

        def _probe_send(term: str, text: str, **kw):
            if start_lock.exists():
                with open(start_lock, "a+") as f:
                    try:
                        lock_file(f, shared=False)
                        lock_free_during_send.append(True)
                        unlock_file(f)
                    except OSError:
                        lock_free_during_send.append(False)
            else:
                lock_free_during_send.append(True)
            return orig_send(term, text, **kw)

        self.hc.send = _probe_send  # type: ignore[method-assign]
        res = svc.start(HelperStartRequest(prompt="Check lock", name="lockchk", repo=str(self.repo)))
        self.assertEqual(res.name, "lockchk")
        self.assertTrue(res.terminal)
        self.assertEqual(lock_free_during_send, [True])
        entries = helper_entries(self.ctx.store.registration(self.slug))
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["handed"])

    def test_async_start_spawns_deliver_ready_and_deliver(self) -> None:
        svc = Helpers(self.ctx)
        res = svc.start(HelperStartRequest(
            prompt="Run triage", name="tr1", exec_mode=True, async_=True,
            for_task=self.task_id, repo=str(self.repo),
        ))
        self.assertTrue(res.is_async)
        self.assertIn("(async)", res.line)
        cmds = [call["args"][0] for call in self.procs.spawned]
        self.assertIn("_deliver-ready", cmds)
        self.assertIn("deliver", cmds)

    def test_depth_guard_exec_guard_and_limits(self) -> None:
        wctx = self._ctx_for(self.worker_term)
        wsvc = Helpers(wctx)
        # Worker cannot start --exec helper.
        with self.assertRaises(Refused):
            wsvc.start(HelperStartRequest(prompt="Deploy", exec_mode=True, repo=str(self.repo)))

        # Start 3 helpers for worker; 4th is refused.
        for i in range(1, 4):
            wsvc.start(HelperStartRequest(prompt=f"Read {i}", name=f"r{i}", repo=str(self.repo)))
        with self.assertRaises(Refused) as cm:
            wsvc.start(HelperStartRequest(prompt="Read 4", name="r4", repo=str(self.repo)))
        self.assertIn("3/3", str(cm.exception))

        # Helper cannot start nested helper.
        hterm = helper_entries(self.ctx.store.task(self.task_id))[0]["terminal"]
        hsvc = Helpers(self._ctx_for(hterm))
        with self.assertRaises(Refused) as cm2:
            hsvc.start(HelperStartRequest(prompt="Nested", repo=str(self.repo)))
        self.assertIn("depth", str(cm2.exception))

    def test_done_hooks_ls_stop_and_watcher(self) -> None:
        svc = Helpers(self.ctx)
        res = svc.start(HelperStartRequest(prompt="Check api", name="api", repo=str(self.repo)))
        hterm = res.terminal

        # SessionStart hook returns reminder string without printing.
        hctx = self._ctx_for(hterm, env={"CLAUDE_CODE_SESSION_ID": "sess-1"})
        hsvc = Helpers(hctx)
        msg = hsvc.session_start_message()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("helper api", msg)

        # First Stop hook returns block_payload; second harvests last_assistant_message.
        stop1 = hsvc.handle_stop_hook({"hook_event_name": "Stop", "stop_hook_active": False})
        self.assertIsNotNone(stop1.block_payload)
        assert stop1.block_payload is not None
        self.assertEqual(stop1.block_payload["decision"], "block")

        stop2 = hsvc.handle_stop_hook({
            "hook_event_name": "Stop", "stop_hook_active": True,
            "last_assistant_message": "API looks good.",
        })
        self.assertTrue(stop2.finalized)
        self.assertIn("API looks good.", Path(res.result).read_text(encoding="utf-8"))
        _, all_events = Conversation(self.ctx, str(self.repo)).events_after(0)
        events = [e for _, e in all_events if e.get("type") == "helper"]
        self.assertEqual(len(events), 1)

        # HelperWatcher cleans up cleanup_term terminal once idle.
        watcher = HelperWatcher(self.ctx)
        self.assertEqual(watcher.active_terminals(str(self.repo)), {hterm})
        watcher.look(str(self.repo), {})
        self.assertEqual(watcher.active_terminals(str(self.repo)), set())

        # kill_helper_terminal_for never kills PM terminal.
        self.assertFalse(kill_helper_terminal_for(self.ctx, self.pm_term))

        # Starting another helper and advancing clock past timeout -> ls reconciles it as timeout.
        res2 = svc.start(HelperStartRequest(prompt="Slow", name="slow", timeout=10, repo=str(self.repo)))
        self.clock.advance(20)
        ls_res = svc.ls(repo=str(self.repo))
        slow_row = next(e for e in ls_res.entries if e["name"] == "slow")
        self.assertEqual(slow_row["status"], "timeout")

        # Stop unknown helper raises NotFound.
        with self.assertRaises(NotFound):
            svc.stop(["no-such-helper"], repo=str(self.repo))

    def test_ls_projects_running_helper_live_state_as_string(self) -> None:
        svc = Helpers(self.ctx)
        res = svc.start(HelperStartRequest(prompt="Inspect", name="insp", repo=str(self.repo)))
        self.hc.terminals[res.terminal]["status"] = {"state": "working"}
        ls_working = svc.ls(repo=str(self.repo))
        row_working = next(e for e in ls_working.entries if e["name"] == "insp")
        self.assertEqual(row_working["live_state"], "working")
        self.assertTrue(any("[running (working)] insp" in ln for ln in ls_working.lines), ls_working.lines)

        del self.hc.terminals[res.terminal]
        ls_offline = svc.ls(active_only=True, repo=str(self.repo))
        # Reconcile reaps disappeared running terminal as exited, so active_only is now empty.
        self.assertEqual(ls_offline.entries, [])

    def test_pm_helper_wait_watches_registrations_dir_without_attribute_error(self) -> None:
        """Finding P1: `Helpers.wait` on a PM-owned running helper watches `ctx.home.registrations`
        and `HelperWatcher.look` honors PM helper-wait lock."""
        svc = Helpers(self.ctx)
        res = svc.start(HelperStartRequest(prompt="PM scan", name="pmscan", repo=str(self.repo)))
        Path(res.result).write_text("PM scan conclusion.\n", encoding="utf-8")
        self.hc.terminals[res.terminal]["turn"] = 1
        self.hc.terminals[res.terminal]["status"] = {"state": "done"}

        # While PM helper wait guard is active, HelperWatcher.look must not harvest/kill the PM helper.
        stops: dict = {}
        watcher = HelperWatcher(self.ctx)
        with helper_wait_guard_for(self.ctx, f"pm-{self.slug}"):
            watcher.look(str(self.repo), stops)
            self.clock.advance(10.0)
            watcher.look(str(self.repo), stops)
            h_guarded = next(h for h in helper_entries(self.ctx.store.registration(self.slug)) if h["name"] == "pmscan")
            self.assertEqual(h_guarded["status"], "running")
            self.assertEqual(self.hc.terminals[res.terminal]["state"], "live")

        wait_res = svc.wait(["pmscan"], timeout=20, repo=str(self.repo))
        self.assertEqual(wait_res.exit_code, 0)
        self.assertEqual(len(wait_res.items), 1)
        self.assertEqual(wait_res.items[0]["status"], "done")
        self.assertIn("PM scan conclusion.", wait_res.items[0]["content"])

    def test_helper_wait_and_watcher_do_not_kill_helper_with_background_work(self) -> None:
        """Finding P3: `Helpers.wait` and `HelperWatcher.look` preserve helpers with active
        `ctx.procs.background_work(info)` (and `Helpers.wait` does not prematurely kill hooked helpers)."""
        wctx = self._ctx_for(self.worker_term)
        wsvc = Helpers(wctx)
        res = wsvc.start(HelperStartRequest(prompt="Run checks in bg", name="bgcheck", repo=str(self.repo)))
        hterm = res.terminal
        self.hc.terminals[hterm]["pid"] = 7777
        self.hc.terminals[hterm]["turn"] = 1
        self.hc.terminals[hterm]["status"] = {"state": "done"}
        self.hc.terminals[hterm]["screen"] = "Running background checks...\n"
        self.procs._background_work = {7777: ["python3 tests/run_checks.py"]}

        # 1. HelperWatcher.look must keep the helper running and its terminal live while background_work is non-empty.
        stops: dict = {}
        watcher = HelperWatcher(self.ctx)
        watcher.look(str(self.repo), stops)
        self.clock.advance(10.0)
        watcher.look(str(self.repo), stops)
        h_after = next(h for h in helper_entries(self.ctx.store.task(self.task_id)) if h["name"] == "bgcheck")
        self.assertEqual(h_after["status"], "running")
        self.assertEqual(self.hc.terminals[hterm]["state"], "live")

        # 2. Helpers.wait with short timeout must time out (exit_code=2) rather than killing the active bg helper.
        wait_res = wsvc.wait(["bgcheck"], timeout=6, repo=str(self.repo))
        self.assertEqual(wait_res.exit_code, 2)
        self.assertEqual(self.hc.terminals[hterm]["state"], "live")

        # 3. HelperWatcher.look must also defer cleanup_term kill while background_work is active.
        def _mark_done_cleanup(cur):
            for h in cur.get("helpers") or []:
                if h.get("name") == "bgcheck":
                    h["status"] = "done"
                    h["cleanup_term"] = True
            return cur
        self.ctx.store.change_task(self.task_id, _mark_done_cleanup)
        watcher.look(str(self.repo), stops)
        self.assertEqual(self.hc.terminals[hterm]["state"], "live")

        # Once background work finishes, cleanup_term proceeds.
        self.procs._background_work = {}
        watcher.look(str(self.repo), stops)
        self.assertNotEqual(self.hc.terminals[hterm]["state"], "live")

        # 4. Hooked Claude helper in idle/done must not be killed by Helpers.wait on unreported-stop heuristic.
        cres = wsvc.start(HelperStartRequest(prompt="Claude check", name="clcheck", kind="claude", model="sonnet", repo=str(self.repo)))
        self.hc.terminals[cres.terminal]["turn"] = 1
        self.hc.terminals[cres.terminal]["status"] = {"state": "done"}
        cwait = wsvc.wait(["clcheck"], timeout=6, repo=str(self.repo))
        self.assertEqual(cwait.exit_code, 2)
        self.assertEqual(self.hc.terminals[cres.terminal]["state"], "live")

    def test_quiet_helper_never_wakes_pm_across_done_timeout_exited_stopped_and_blocked(self) -> None:
        svc = Helpers(self.ctx)
        watcher = HelperWatcher(self.ctx)
        delivery = Delivery(self.ctx, str(self.repo))

        # 1. Done path (helper calls `helper done` itself)
        r_done = svc.start(HelperStartRequest(
            prompt="Quiet done", name="q-done", quiet=True, repo=str(self.repo),
        ))
        self.procs.spawned.clear()
        hsvc = Helpers(self._ctx_for(r_done.terminal))
        hsvc.done(text="Quietly finished.")
        entry_done = next(h for h in helper_entries(self.ctx.store.registration(self.slug)) if h["name"] == "q-done")
        self.assertTrue(entry_done.get("quiet"))
        self.assertEqual(entry_done["status"], "done")

        # 2. Timeout path (HelperWatcher sweeps timed-out quiet helper)
        r_to = svc.start(HelperStartRequest(
            prompt="Quiet timeout", name="q-to", timeout=10, quiet=True, repo=str(self.repo),
        ))
        self.procs.spawned.clear()
        self.clock.advance(20)
        watcher.look(str(self.repo), {})
        entry_to = next(h for h in helper_entries(self.ctx.store.registration(self.slug)) if h["name"] == "q-to")
        self.assertEqual(entry_to["status"], "timeout")
        # Quiet timeout notification must not spawn deliver.
        self.assertEqual([c for c in self.procs.spawned if c["args"][0] == "deliver"], [])

        # 3. Exited (gone) path
        r_exit = svc.start(HelperStartRequest(
            prompt="Quiet exit", name="q-exit", quiet=True, repo=str(self.repo),
        ))
        self.procs.spawned.clear()
        del self.hc.terminals[r_exit.terminal]
        watcher.look(str(self.repo), {})
        entry_exit = next(h for h in helper_entries(self.ctx.store.registration(self.slug)) if h["name"] == "q-exit")
        self.assertEqual(entry_exit["status"], "exited")
        self.assertEqual([c for c in self.procs.spawned if c["args"][0] == "deliver"], [])

        # 4. Stopped path (both via Helpers.stop and via finalize_helper_for with notify=True)
        r_stop = svc.start(HelperStartRequest(
            prompt="Quiet stop", name="q-stop", quiet=True, repo=str(self.repo),
        ))
        svc.stop(["q-stop"], repo=str(self.repo))
        r_stop_n = svc.start(HelperStartRequest(
            prompt="Quiet stop notify", name="q-stop-n", quiet=True, repo=str(self.repo),
        ))
        finalize_helper_for(
            self.ctx, "pm", f"pm-{self.slug}", self.slug, str(self.repo),
            term=r_stop_n.terminal, name="q-stop-n", status="stopped", kill_term=True, notify=True,
        )

        # 5. Blocked path in HelperWatcher
        r_blk = svc.start(HelperStartRequest(
            prompt="Quiet blocked", name="q-blk", quiet=True, repo=str(self.repo),
        ))
        self.hc.terminals[r_blk.terminal]["status"] = {"state": "blocked"}
        self.hc.terminals[r_blk.terminal]["screen"] = "Waiting for input..."
        stops: dict = {}
        watcher.look(str(self.repo), stops)
        self.clock.advance(10.0)
        watcher.look(str(self.repo), stops)

        # Every recorded helper event must have wake=False, and Delivery.pending_batch() must be empty.
        events = [e for e in Conversation(self.ctx, str(self.repo)).events() if e.get("type") == "helper"]
        statuses = {e.get("status") for e in events}
        self.assertTrue({"done", "timeout", "exited", "stopped", "blocked"}.issubset(statuses), statuses)
        self.assertTrue(all(e.get("wake") is False for e in events), events)
        _, _, pending = delivery.pending_batch()
        self.assertEqual(pending, [])

    def test_parent_pm_placement_offline_refusal_and_hc_pane_ignored(self) -> None:
        # Direct helper_placement_for with explicit parent
        cli_ctx = self._ctx_for("")
        self.assertEqual(helper_placement_for(cli_ctx), ["--no-parent"])
        self.assertEqual(helper_placement_for(cli_ctx, parent="t99"), ["--parent", "t99", "--no-notify"])

        # Without parent_pm, empty ctx.pane is still refused
        with self.assertRaises(Refused):
            Helpers(cli_ctx).start(HelperStartRequest(prompt="No parent_pm", pm=True, repo=str(self.repo)))

        # With parent_pm=True and empty ctx.pane, placement is ["--parent", pm_term, "--no-notify"]
        placements: list[list[str]] = []
        orig_start = self.hc.start_terminal

        def _spy_start(name, cwd, argv, placement=(), labels=(), env=None):
            placements.append(list(placement))
            return orig_start(name, cwd, argv, placement=placement, labels=labels, env=env)

        self.hc.start_terminal = _spy_start  # type: ignore[method-assign]
        res = Helpers(cli_ctx).start(HelperStartRequest(
            prompt="From deliverer", name="bg-job", pm=True, parent_pm=True, repo=str(self.repo),
        ))
        self.assertEqual(placements[-1], ["--parent", self.pm_term, "--no-notify"])
        entry = next(h for h in helper_entries(self.ctx.store.registration(self.slug)) if h["name"] == "bg-job")
        self.assertEqual(entry["parent"], self.pm_term)
        self.assertEqual(self.hc.terminals[res.terminal]["parent"], self.pm_term)

        # When ctx.pane is an hc terminal (e.g. worker terminal), parent_pm is ignored
        wctx = self._ctx_for(self.worker_term)
        wres = Helpers(wctx).start(HelperStartRequest(
            prompt="From worker", name="w-job", parent_pm=True, repo=str(self.repo),
        ))
        self.assertEqual(placements[-1], ["--parent", self.worker_term, "--no-notify"])
        wentry = next(h for h in helper_entries(self.ctx.store.task(self.task_id)) if h["name"] == "w-job")
        self.assertEqual(wentry["parent"], self.worker_term)
        self.assertEqual(self.hc.terminals[wres.terminal]["parent"], self.worker_term)

        # When PM terminal is offline in hc, parent_pm=True raises Refused
        self.hc.terminals[self.pm_term]["state"] = "exited"
        with self.assertRaises(Refused):
            Helpers(cli_ctx).start(HelperStartRequest(
                prompt="Offline PM", name="bg-job-2", pm=True, parent_pm=True, repo=str(self.repo),
            ))


if __name__ == "__main__":
    unittest.main()
