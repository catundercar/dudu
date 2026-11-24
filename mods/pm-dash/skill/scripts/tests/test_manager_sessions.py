"""Unit tests for `ManagerSessions` (Stage 4d) over isolated `Context` and `tests/fakes.py` doubles."""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pmlib.errors import NotFound, Refused
from pmlib.home import Home, project_slug
from pmlib.ledger.ledger import Ledger
from pmlib.manager.rotate import _end_session_later_impl
from pmlib.manager.seat import pop_next_session, read_seat_state, write_seat_state
from pmlib.manager.service import ManagerSessions
from pmlib.project.conversation import Conversation
from pmlib.project.project import ProjectRegistry
from pmlib.store import lock_file, unlock_file
from tests.fakes import FakeClock, FakeHc, FakeProcs, FakeTui, make_ctx


class ManagerSessionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="pm-mgr-svc-")
        self.tmp = Path(self._tmp.name)
        self.home_dir = self.tmp / "home"
        self.repo = self.tmp / "alpha"
        self.repo.mkdir()
        self.repo_s = str(self.repo.resolve())
        self.slug = project_slug(self.repo_s)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _ctx(self, *, pane: str = "", hc: FakeHc | None = None, tui: FakeTui | None = None,
             procs: FakeProcs | None = None, clock: FakeClock | None = None,
             config: dict | None = None):
        return make_ctx(
            self.home_dir,
            pane=pane,
            hc=hc or FakeHc(),
            tui=tui or FakeTui(),
            procs=procs,
            clock=clock or FakeClock(datetime.datetime.now().replace(microsecond=0)),
            config=config,
        )

    def test_launch_and_invalid_repo(self) -> None:
        ctx = self._ctx()
        svc = ManagerSessions(ctx)
        cmd = svc.launch(self.repo_s, resume="sid-1")
        self.assertIn("--resume sid-1", cmd)
        with self.assertRaises(Refused):
            svc.launch(str(self.tmp / "does-not-exist"))

    def test_claim_hc_bare_and_repoint_tasks(self) -> None:
        hc = FakeHc(terminals={"t10": {"state": "live", "labels": {}, "argv": ["claude"]}})
        ctx = self._ctx(hc=hc)
        # Seed a previous PM registration and an open task parked on the old PM pane.
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "hc:t1", "runtime": "hc", "terminal": "t1",
        })
        Ledger(ctx).create({
            "id": "alpha-epic", "project": "alpha", "repo": self.repo_s,
            "title": "Epic", "status": "proposed", "pane": "hc:t1",
        })
        svc = ManagerSessions(ctx)
        res = svc.claim(self.repo_s, pane="hc:t10", kind="claude")
        self.assertEqual(res.pane, "hc:t10")
        self.assertIn("hc:t10 is now", res.lines[0])
        self.assertIsNone(res.exec_argv)
        self.assertTrue(any(s["args"][:2] == ["deliver", self.repo_s] for s in ctx.procs.spawned), ctx.procs.spawned)
        rec = ProjectRegistry(ctx).pm_record(self.repo_s)
        assert rec is not None
        self.assertEqual(rec["terminal"], "t10")
        self.assertTrue(rec.get("seat"))
        self.assertEqual(Ledger(ctx).load("alpha-epic").pane, "hc:t10")

    def test_claim_shell_terminal_starts_seat_via_hc_send(self) -> None:
        hc = FakeHc(terminals={
            "t20": {"state": "live", "labels": {}, "argv": ["zsh"], "foreground": {"argv": ["zsh"]}}
        })
        ctx = self._ctx(pane="hc:t20", hc=hc)
        svc = ManagerSessions(ctx)
        res = svc.claim(self.repo_s, kind="claude")
        self.assertIsNone(res.exec_argv)
        self.assertTrue(any(term == "t20" and "exec " in text and "seat" in text for term, text in hc.sent))
        self.assertTrue(any(s["args"][:2] == ["deliver", self.repo_s] for s in ctx.procs.spawned))

    def test_claim_refuses_without_pane_or_when_other_pm_live(self) -> None:
        hc = FakeHc(terminals={"t1": {"state": "live", "labels": {"pm": "alpha"}}})
        ctx = self._ctx(hc=hc)
        svc = ManagerSessions(ctx)
        with self.assertRaises(Refused):
            svc.claim(self.repo_s)
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "hc:t1", "runtime": "hc", "terminal": "t1",
        })
        with self.assertRaises(Refused):
            svc.claim(self.repo_s, pane="hc:t2")

    def test_start_revives_shell_seat_and_rolls_back_on_claim_failure(self) -> None:
        # 1. Revive exited seat shell in the same terminal without creating a new space.
        hc = FakeHc(terminals={
            "t7": {"state": "live", "seat_dead": True, "labels": {"pm": "alpha"}, "argv": ["zsh"], "foreground": {"argv": ["zsh"]}},
        })
        ctx = self._ctx(hc=hc)
        ctx.seat_alive = lambda repo, rec, term=None: not bool((term or {}).get("seat_dead"))
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "seat": True,
        })
        Conversation(ctx, self.repo_s).record("user", text="hello")
        svc = ManagerSessions(ctx)
        started = svc.start(self.repo_s, kind="claude", space="current", name="ignored")
        self.assertEqual(started.terminal, "t7")
        self.assertEqual(len(started.stderr_lines), 1)
        self.assertIn("--name", started.stderr_lines[0])
        # Recovery swap notice written because project had prior conversation.
        events = Conversation(ctx, self.repo_s).events()
        self.assertTrue(events[-1].get("notice"))
        self.assertIn("session recovery", events[-1]["text"])

        # 2. If claim fails after spawning a new terminal, kill + rm the newly spawned terminal.
        repo2 = self.tmp / "beta"
        repo2.mkdir()
        hc2 = FakeHc()
        ctx2 = self._ctx(hc=hc2)
        svc2 = ManagerSessions(ctx2)
        with mock.patch.object(svc2, "claim", side_effect=Refused("boom")):
            with self.assertRaises(Refused):
                svc2.start(str(repo2), kind="claude", space="current")
        self.assertEqual(hc2.terminals, {})

    def test_archive_and_restore_happy_and_rollback(self) -> None:
        hc = FakeHc(terminals={"t1": {"state": "live", "labels": {"pm": "alpha", "pm.seat": "1"}}}, app_available=False)
        ctx = self._ctx(hc=hc)
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "hc:t1", "runtime": "hc", "terminal": "t1", "seat": True, "agent": "claude",
        })
        ledger = Ledger(ctx)
        ledger.create({"id": "alpha-a", "project": "alpha", "repo": self.repo_s, "title": "A", "status": "in_progress"})
        ledger.create({"id": "alpha-b", "project": "alpha", "repo": self.repo_s, "title": "B", "status": "done"})
        svc = ManagerSessions(ctx)

        arch = svc.archive(self.repo_s)
        self.assertEqual(arch.paused, 1)
        self.assertIn("1 tasks paused", arch.lines[0])
        self.assertIn("PM hc:t1 ended", arch.lines[1])
        self.assertEqual(ledger.load("alpha-a").status, "paused")
        self.assertEqual(ledger.load("alpha-a").get("paused_from"), "in_progress")
        self.assertEqual(ledger.load("alpha-b").status, "done")

        # Archiving again is idempotent.
        again = svc.archive(self.repo_s)
        self.assertIsNotNone(again.already_archived)

        # Rollback when start fails during restore: project stays archived and tasks re-paused.
        with mock.patch.object(svc, "start", side_effect=Refused("no app")):
            with self.assertRaises(Refused) as cm:
                svc.restore(self.repo_s)
        self.assertIn("stays archived", str(cm.exception))
        rec_after_fail = ProjectRegistry(ctx).pm_record(self.repo_s)
        assert rec_after_fail is not None
        self.assertTrue(rec_after_fail.get("archived"))
        self.assertEqual(ledger.load("alpha-a").status, "paused")
        self.assertEqual(ledger.load("alpha-a").get("paused_from"), "in_progress")

        # Happy restore: unarchives, restores task status, starts new PM.
        rest = svc.restore(self.repo_s)
        self.assertEqual(rest.restored, 1)
        self.assertFalse(rest.not_archived)
        self.assertTrue(rest.terminal)
        self.assertEqual(ledger.load("alpha-a").status, "in_progress")
        rec_after_ok = ProjectRegistry(ctx).pm_record(self.repo_s)
        assert rec_after_ok is not None
        self.assertFalse(rec_after_ok.get("archived"))

    def test_rotate_in_seat_and_legacy_to_seat(self) -> None:
        hc = FakeHc(terminals={
            "t7": {"state": "live", "labels": {"pm": "alpha", "pm.seat": "1"}, "argv": ["claude"]},
        })
        procs = FakeProcs(Home(self.home_dir))
        ctx = self._ctx(pane="hc:t7", hc=hc, procs=procs)
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "seat": True, "agent": "claude",
            "agent_session": {"kind": "claude", "id": "sess-old"},
        })
        write_seat_state(self.repo_s, {"pid": 111, "terminal": "t7", "agent_pid": 4242, "kind": "claude",
                                       "argv": ["claude", "--model", "opus"]}, ctx=ctx)
        svc = ManagerSessions(ctx)
        res = svc.rotate(self.repo_s, notes="in flight", reason="test swap")
        self.assertEqual(res.mode, "seat")
        self.assertTrue(any("queued in seat hc:t7" in line for line in res.lines))
        nxt, expired = pop_next_session(self.repo_s, ctx=ctx)
        self.assertIsNotNone(nxt)
        self.assertIsNone(expired)
        self.assertTrue(any(s["args"][:2] == ["end-session", "t7"] and "--agent-pid" in s["args"] for s in procs.spawned))

    def test_rotate_tui_and_rollback(self) -> None:
        tui = FakeTui(
            panes=[{"pane_id": "w1:p1", "workspace_id": "w1"}],
            agents=[{"pane_id": "w1:p1", "name": f"pm-{self.slug}", "workspace_id": "w1"}],
        )
        ctx = self._ctx(pane="w1:p1", tui=tui)
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "w1:p1", "workspace": "w1", "agent": "claude",
        })
        svc = ManagerSessions(ctx)
        res = svc.rotate(self.repo_s, notes="tui note", reason="refresh")
        self.assertEqual(res.mode, "tui")
        self.assertTrue(any("new PM session started" in line for line in res.lines))

    def test_seat_runs_child_rotates_and_cleans_up(self) -> None:
        ctx = self._ctx(pane="hc:t9", hc=FakeHc(terminals={"t9": {"state": "live", "turn": 1}}))
        svc = ManagerSessions(ctx)
        with self.assertRaises(Refused):
            svc.seat(self.repo_s, [])
        # Run a tiny Python child that exits 0, with no_shell=True.
        res = svc.seat(self.repo_s, ["--", sys.executable, "-c", "pass"], kind="claude", no_shell=True)
        self.assertEqual(res.exit_code, 0)
        self.assertFalse(res.exec_shell)
        self.assertEqual(read_seat_state(self.repo_s, ctx=ctx), {})

        # Lock contention refuses a second seat.
        lock_path = ctx.home.project_for(self.repo_s).ensure() / "seat.lock"
        with open(lock_path, "a+") as fh:
            lock_file(fh)
            try:
                with self.assertRaises(Refused):
                    svc.seat(self.repo_s, ["--", sys.executable, "-c", "pass"], no_shell=True)
            finally:
                unlock_file(fh)

    def test_end_session_timeout_cancels_rotation(self) -> None:
        hc = FakeHc(terminals={"t7": {"state": "live", "pid": 100, "status": {"state": "working"}}})
        clock = FakeClock("2026-11-23 10:00:00")
        procs = FakeProcs(Home(self.home_dir), background_work=lambda info: ["long-cmd"])
        ctx = self._ctx(hc=hc, clock=clock, procs=procs)
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "seat": True, "agent": "claude",
            "agent_session": None,
            "retired_sessions": ["sid-1"],
            "previous": {"agent": "claude", "agent_session": {"kind": "claude", "id": "sid-1"}},
        })
        write_seat_state(self.repo_s, {"pid": 100, "terminal": "t7", "agent_pid": 555}, ctx=ctx)
        (ctx.home.project_for(self.repo_s).ensure() / "next-session.json").write_text(json.dumps({
            "argv": ["claude"], "previous": {"agent": "claude", "agent_session": {"kind": "claude", "id": "sid-1"}},
        }))
        svc = ManagerSessions(ctx)
        with mock.patch("pmlib.osutil.pid_alive", return_value=True):
            svc.end_session("t7", repo_arg=self.repo_s, agent_pid=555, kill_terminal=False, timeout=10)
        self.assertFalse(ctx.home.project_for(self.repo_s).next_session.exists())
        rec = ProjectRegistry(ctx).pm_record(self.repo_s)
        assert rec is not None
        self.assertEqual((rec.get("agent_session") or {}).get("id"), "sid-1")
        self.assertTrue(Conversation(ctx, self.repo_s).events()[-1].get("notice"))

    def test_handover_variants(self) -> None:
        ctx = self._ctx()
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "hc:t1", "runtime": "hc", "terminal": "t1",
        })
        Ledger(ctx).create({"id": "alpha-t1", "project": "alpha", "repo": self.repo_s, "title": "First", "status": "in_progress"})
        svc = ManagerSessions(ctx)
        std = svc.handover(self.repo_s)
        self.assertIn("# Handover: PM of alpha", std)
        self.assertIn("alpha-t1", std)
        compact = svc.handover(self.repo_s, compact=True)
        self.assertIn("[pm post-compact live disk sync]", compact)
        full = svc.handover(self.repo_s, full=True)
        self.assertIn("## Open work", full)

    def test_end_session_later_spawn_failure_returns_warning(self) -> None:
        procs = FakeProcs(Home(self.home_dir), spawn_ok=False)
        ctx = self._ctx(procs=procs)
        msg = _end_session_later_impl(self.repo_s, "t7", agent_pid=123, kill_terminal=False, ctx=ctx)
        self.assertIsNotNone(msg)
        self.assertIn("t7", msg or "")


if __name__ == "__main__":
    unittest.main()
