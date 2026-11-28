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
        started = svc.start(self.repo_s, kind="claude", space="current", name="Alpha Custom")
        self.assertEqual(started.terminal, "t7")
        self.assertEqual(started.stderr_lines, [])
        revived_rec = ProjectRegistry(ctx).pm_record(self.repo_s)
        assert revived_rec is not None
        self.assertEqual(revived_rec.get("display_name"), "Alpha Custom")
        self.assertEqual(revived_rec.get("project"), "alpha")
        self.assertNotIn("space_name", revived_rec)
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

    def test_start_name_and_project_rename_end_to_end(self) -> None:
        from pmlib.project.project import project_display_name
        from pmlib.project.readmodel import Projects
        from pmlib.views.state import dash_state
        from tests.fakes import run_main

        hc = FakeHc(app_available=True)
        orig_app_do = hc.app_do

        def fake_app_do(command: str, payload, *, timeout: float = 30):
            res = orig_app_do(command, payload, timeout=timeout)
            if command == "space.new":
                hc.terminals["t50"] = {
                    "state": "live", "labels": {"pm": "alpha", "pm.seat": "1"},
                    "argv": list(payload.get("argv") or ["claude"]),
                }
                return mock.Mock(returncode=0, stdout=json.dumps({"ok": True, "terminal": "t50"}), stderr="")
            return res

        hc.app_do = fake_app_do  # type: ignore[method-assign]
        ctx = self._ctx(hc=hc)
        svc = ManagerSessions(ctx)

        # 1. Start in a new space with a custom Chinese display name distinct from folder basename "alpha".
        started = svc.start(self.repo_s, kind="claude", space="new", name="我的前端项目")
        rec = ProjectRegistry(ctx).pm_record(self.repo_s)
        assert rec is not None
        self.assertEqual(rec["project"], "alpha")
        self.assertEqual(rec["name"], f"pm-{self.slug}")
        self.assertEqual(rec["display_name"], "我的前端项目")
        self.assertEqual(rec["space_name"], "我的前端项目")
        self.assertEqual(hc.tab_names.get(started.terminal), "PM-我的前端项目")
        self.assertEqual(ProjectRegistry(ctx).resolve_project_slug("我的前端项目"), self.slug)
        self.assertEqual(ProjectRegistry(ctx).registered_repo("我的前端项目"), self.repo_s)

        # Views & handover reflect display_name while keeping project/slug/tasks intact.
        Ledger(ctx).create({"id": "alpha-keep", "project": "alpha", "repo": self.repo_s, "title": "Keep task", "status": "in_progress"})
        Conversation(ctx, self.repo_s).record("user", text="hello before rename")
        state = dash_state(ctx)
        pm_state = next(p for p in state["pms"] if p["name"] == f"pm-{self.slug}")
        self.assertEqual(pm_state["display_name"], "我的前端项目")
        self.assertEqual(pm_state["project"], "alpha")
        listed = Projects(ctx.store).list()
        self.assertEqual(listed[0]["display_name"], "我的前端项目")
        self.assertIn("# Handover: PM of 我的前端项目", svc.handover(self.repo_s))

        # 2. Seed a second project with legacy space_name only (no display_name) to verify fallback & dedupe.
        repo2 = self.tmp / "beta"
        repo2.mkdir()
        repo2_s = str(repo2.resolve())
        slug2 = project_slug(repo2_s)
        ctx.store.change_registration(slug2, lambda _: {
            "project": "beta", "repo": repo2_s, "name": f"pm-{slug2}", "space_name": "Legacy Beta",
            "pane": "hc:t99", "runtime": "hc", "terminal": "t99",
        })
        self.assertEqual(project_display_name(ProjectRegistry(ctx).pm_record(repo2_s)), "Legacy Beta")
        state2 = dash_state(ctx)
        pm_beta = next(p for p in state2["pms"] if p["name"] == f"pm-{slug2}")
        self.assertEqual(pm_beta["display_name"], "Legacy Beta")

        # 3. CLI `pm.py project rename` updates display_name, space_name, live PM tab, and dedicated space.
        spaces_stub = [
            {"id": "sp-alpha", "name": "我的前端项目", "folder": self.repo_s,
             "tabs": [{"id": "tab-1", "terminals": [{"terminal": started.terminal}]}]},
            {"id": "sp-shared", "name": "General", "folder": "/tmp/other", "tabs": []},
        ]
        with mock.patch.object(hc, "app_spaces", return_value=spaces_stub):
            rc, out, err = run_main(ctx, "project", "rename", f"pm-{self.slug}", "Frontend Core")
        self.assertEqual(rc, 0, err)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["slug"], self.slug)
        self.assertEqual(payload["project"], "alpha")
        self.assertEqual(payload["previous_name"], "我的前端项目")
        self.assertEqual(payload["display_name"], "Frontend Core")
        self.assertTrue(payload["tab_renamed"])
        self.assertTrue(payload["space_renamed"])
        self.assertEqual(hc.tab_names.get(started.terminal), "PM-Frontend Core")
        self.assertTrue(any(
            c.get("fn") == "app_do" and c.get("command") == "space.rename"
            and c.get("payload") == {"id": "sp-alpha", "name": "Frontend Core"}
            for c in hc.tab_calls
        ), hc.tab_calls)
        # Task and conversation history remain untouched.
        self.assertEqual(Ledger(ctx).load("alpha-keep").title, "Keep task")
        self.assertTrue(any(e.get("text") == "hello before rename" for e in Conversation(ctx, self.repo_s).events()))

        # Case-only rename on the same project is allowed; shared unrelated space is NOT renamed.
        hc.tab_calls.clear()
        with mock.patch.object(hc, "app_spaces", return_value=[{"id": "sp-shared", "name": "General", "folder": "/tmp/other", "tabs": []}]):
            res_case = svc.rename(self.slug, "frontend core")
        self.assertEqual(res_case.display_name, "frontend core")
        self.assertFalse(res_case.space_renamed)
        self.assertFalse(any(c.get("command") == "space.rename" for c in hc.tab_calls))

        # 4. Validation: empty, control chars, >80 chars, duplicate (case-insensitive), and worker caller.
        for bad in ("   ", "Bad\nName", "x" * 81, "legacy beta"):
            with self.assertRaises(Refused, msg=f"should reject {bad!r}"):
                svc.rename(self.slug, bad)
        with self.assertRaises(Refused):
            svc.start(str(self.tmp / "gamma"), kind="claude", space="current", name="Legacy Beta")
        worker_ctx = self._ctx(pane="hc:t-worker", hc=FakeHc(terminals={
            "t-worker": {"state": "live", "labels": {"pm.task": "alpha-keep", "pm.role": "worker"}},
        }))
        with self.assertRaises(Refused):
            ManagerSessions(worker_ctx).rename(self.slug, "Sneaky Rename")

    def test_start_zero_and_multi_folders_and_json_cli(self) -> None:
        from pmlib.views.state import dash_state
        from tests.fakes import run_main

        repo_b = self.tmp / "beta"
        repo_b.mkdir()
        repo_b_s = str(repo_b.resolve())

        hc = FakeHc(app_available=True)
        orig_app_do = hc.app_do

        def fake_app_do(command: str, payload, *, timeout: float = 30):
            res = orig_app_do(command, payload, timeout=timeout)
            if command == "space.new":
                term = "t51" if "Zero" in str(payload.get("name")) else "t52"
                hc.terminals[term] = {
                    "state": "live",
                    "labels": {"pm": "notes-planning" if term == "t51" else "multi-proj",
                               "pm.seat": "1", "herdr.space": f"sp-{term}"},
                    "argv": list(payload.get("argv") or ["agy"]),
                }
                return mock.Mock(returncode=0, stdout=json.dumps({"ok": True, "terminal": term, "space": f"sp-{term}"}), stderr="")
            return res

        hc.app_do = fake_app_do  # type: ignore[method-assign]
        ctx = self._ctx(hc=hc)

        # 1. 0-folder project via CLI `start --name ... --kind agy --json`
        rc, out, err = run_main(ctx, "start", "--name", "Notes Zero", "--kind", "agy", "--json")
        self.assertEqual(rc, 0, err)
        res0 = json.loads(out)
        self.assertTrue(res0["ok"])
        self.assertEqual(res0["slug"], "notes-zero")
        self.assertEqual(res0["folders"], [])
        self.assertEqual(res0["space_id"], "sp-t51")
        self.assertEqual(Path(res0["cwd"]).resolve(), ctx.home.project("notes-zero").root.resolve())
        rec0 = ctx.store.registration("notes-zero")
        assert rec0 is not None
        self.assertEqual(rec0["folders"], [])
        self.assertEqual(rec0["repo"], "")
        self.assertEqual(rec0["agent"], "agy")
        self.assertEqual(rec0["space_id"], "sp-t51")

        # 2. Multi-folder equal project via CLI `start --folder A --folder B --name ... --no-app-space --json`
        rc2, out2, err2 = run_main(
            ctx, "start", "--folder", self.repo_s, "--folder", repo_b_s,
            "--name", "Multi Proj", "--kind", "claude", "--no-app-space", "--json",
        )
        self.assertEqual(rc2, 0, err2)
        res2 = json.loads(out2)
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["slug"], "multi-proj")
        self.assertEqual([f["alias"] for f in res2["folders"]], ["alpha", "beta"])
        self.assertEqual(res2["space_id"], "")
        rec2 = ctx.store.registration("multi-proj")
        assert rec2 is not None
        self.assertEqual(rec2["repo"], self.repo_s)
        self.assertEqual(len(rec2["folders"]), 2)
        pm_settings = json.loads(ctx.home.project("multi-proj").pm_settings.read_text(encoding="utf-8"))
        allow = pm_settings.get("permissions", {}).get("allow", [])
        self.assertTrue(any("alpha" in r for r in allow) and any("beta" in r for r in allow), allow)

        # `project set-space` binds space_id cleanly
        rc3, out3, err3 = run_main(ctx, "project", "set-space", "multi-proj", "sp-remote-9", "--space-name", "Multi Proj")
        self.assertEqual(rc3, 0, err3)
        self.assertEqual(json.loads(out3)["space_id"], "sp-remote-9")
        st = dash_state(ctx)
        p_zero = next(p for p in st["pms"] if p["slug"] == "notes-zero")
        self.assertTrue(p_zero["repo_ok"])
        self.assertEqual(p_zero["space_id"], "sp-t51")

        # 3. Restarting an offline 0-folder project via `--slug` (used by pm-project `startPmArgs`)
        hc.terminals.pop(res0["terminal"], None)
        rc_z2, out_z2, err_z2 = run_main(ctx, "start", "--slug", "notes-zero", "--kind", "agy", "--json")
        self.assertEqual(rc_z2, 0, err_z2)
        res_z2 = json.loads(out_z2)
        self.assertEqual(res_z2["slug"], "notes-zero")
        self.assertEqual(res_z2["display_name"], "Notes Zero")
        self.assertEqual(res_z2["folders"], [])
        self.assertIsNone(ctx.store.registration("notes-zero-2"))

        # Invalid `--slug` refuses cleanly
        rc_bad, _out_bad, _err_bad = run_main(ctx, "start", "--slug", "Bad Slug!", "--json")
        self.assertNotEqual(rc_bad, 0)

    def test_lazy_space_id_backfill_on_state_claim_and_rotate(self) -> None:
        from pmlib.views.state import dash_state

        # 1. Backfill during `pm.py state`
        hc = FakeHc(terminals={
            "t11": {"state": "live", "labels": {"pm": "alpha", "pm.seat": "1", "herdr.space": "sp-backfill-state"}},
        })
        ctx = self._ctx(hc=hc)
        ctx.store.change_registration(self.slug, lambda _: {
            "project": "alpha", "repo": self.repo_s, "name": f"pm-{self.slug}",
            "pane": "hc:t11", "runtime": "hc", "terminal": "t11", "seat": True,
        })
        st = dash_state(ctx)
        pm_row = next(p for p in st["pms"] if p["name"] == f"pm-{self.slug}")
        self.assertEqual(pm_row.get("space_id"), "sp-backfill-state")
        self.assertEqual((ctx.store.registration(self.slug) or {}).get("space_id"), "sp-backfill-state")

        # 2. Backfill during `claim` and `rotate`
        repo2 = self.tmp / "gamma"
        repo2.mkdir()
        repo2_s = str(repo2.resolve())
        slug2 = project_slug(repo2_s)
        hc2 = FakeHc(terminals={
            "t22": {"state": "live", "labels": {"pm": "gamma", "pm.seat": "1", "herdr.space": "sp-claim-22"}, "argv": ["claude"]},
        })
        ctx2 = self._ctx(pane="hc:t22", hc=hc2, procs=FakeProcs(Home(self.home_dir)))
        svc2 = ManagerSessions(ctx2)
        svc2.claim(repo2_s, pane="hc:t22", kind="claude")
        self.assertEqual((ctx2.store.registration(slug2) or {}).get("space_id"), "sp-claim-22")

        # Clear space_id and verify `rotate` also backfills from live terminal's `herdr.space`
        ctx2.store.change_registration(slug2, lambda cur: {**cur, "space_id": ""} if cur else None)
        write_seat_state(repo2_s, {"pid": 222, "terminal": "t22", "agent_pid": 888, "kind": "claude"}, ctx=ctx2)
        svc2.rotate(repo2_s, reason="test")
        self.assertEqual((ctx2.store.registration(slug2) or {}).get("space_id"), "sp-claim-22")

    def test_archive_d1_smart_close_and_restore_space_reuse(self) -> None:
        from tests.fakes import run_main

        # Case A: Space has only PM + idle default shell -> archive closes Space via `space.close`
        hc = FakeHc(
            terminals={
                "t1": {"state": "live", "labels": {"pm": "alpha", "pm.seat": "1", "herdr.space": "sp-alpha"}},
                "t2": {"state": "live", "labels": {"herdr.space": "sp-alpha"}, "argv": ["zsh"], "foreground": {"argv": ["zsh"]}},
            },
            app_available=True,
        )
        app_calls: list[tuple[str, dict]] = []
        spaces_state = [
            {"id": "sp-alpha", "name": "Alpha", "folder": self.repo_s, "tabs": [
                {"id": "tab-pm", "panes": 1, "terminals": [{"terminal": "t1"}]},
                {"id": "tab-sh", "panes": 1, "terminals": [{"terminal": "t2"}]},
            ]},
        ]
        hc.app_spaces = lambda: list(spaces_state)  # type: ignore[method-assign]

        def track_app_do(command: str, payload, *, timeout: float = 30):
            app_calls.append((command, dict(payload)))
            if command == "space.close":
                spaces_state[:] = [s for s in spaces_state if s["id"] != payload.get("id")]
                return mock.Mock(returncode=0, stdout='{"ok":true}', stderr="")
            if command == "space.new":
                hc.terminals["t3"] = {"state": "live", "labels": {"pm": "alpha", "pm.seat": "1", "herdr.space": "sp-new"}}
                spaces_state.append({"id": "sp-new", "name": payload.get("name"), "tabs": [{"id": "tab-n", "terminals": [{"terminal": "t3"}]}]})
                return mock.Mock(returncode=0, stdout=json.dumps({"ok": True, "terminal": "t3", "space": "sp-new"}), stderr="")
            if command == "tab.new":
                hc.terminals["t4"] = {"state": "live", "labels": {"pm": "alpha", "pm.seat": "1", "herdr.space": payload.get("space")}}
                return mock.Mock(returncode=0, stdout=json.dumps({"ok": True, "terminal": "t4", "space": payload.get("space")}), stderr="")
            return mock.Mock(returncode=0, stdout='{"ok":true}', stderr="")

        hc.app_do = track_app_do  # type: ignore[method-assign]
        ctx = self._ctx(hc=hc)
        ctx.store.change_registration(self.slug, lambda _: {
            "slug": self.slug, "project": "alpha", "display_name": "Alpha", "space_name": "Alpha",
            "space_id": "sp-alpha", "repo": self.repo_s, "folders": [{"path": self.repo_s, "alias": "alpha", "git": False}],
            "name": f"pm-{self.slug}", "pane": "hc:t1", "runtime": "hc", "terminal": "t1", "seat": True, "agent": "claude",
        })
        svc = ManagerSessions(ctx)
        arch = svc.archive(self.repo_s)
        self.assertTrue(arch.space_closed)
        self.assertFalse(arch.space_kept)
        self.assertIn(("space.close", {"id": "sp-alpha", "confirmed": True}), app_calls)

        # Space was closed -> restore recreates by original name & updates space_id
        app_calls.clear()
        rest = svc.restore(self.repo_s)
        self.assertFalse(rest.space_reused)
        self.assertEqual(rest.space_id, "sp-new")
        self.assertTrue(any(c == "space.new" and p.get("name") == "Alpha" and p.get("focus") is False for c, p in app_calls))

        # Case B: Space has an active user process (nvim) -> archive keeps Space; restore reuses same space_id via tab.new
        app_calls.clear()
        hc.terminals["t5"] = {"state": "live", "labels": {"herdr.space": "sp-new"}, "argv": ["nvim"], "foreground": {"argv": ["nvim", "main.py"]}}
        spaces_state[:] = [
            {"id": "sp-new", "name": "Alpha", "folder": self.repo_s, "tabs": [
                {"id": "tab-n", "panes": 1, "terminals": [{"terminal": "t3"}]},
                {"id": "tab-nvim", "panes": 1, "terminals": [{"terminal": "t5"}]},
            ]},
        ]
        arch2 = svc.archive(self.repo_s)
        self.assertFalse(arch2.space_closed)
        self.assertTrue(arch2.space_kept)
        self.assertFalse(any(c == "space.close" for c, _ in app_calls))

        app_calls.clear()
        rest2 = svc.restore(self.repo_s)
        self.assertTrue(rest2.space_reused)
        self.assertEqual(rest2.space_id, "sp-new")
        self.assertTrue(any(c == "tab.new" and p.get("space") == "sp-new" and p.get("focus") is False for c, p in app_calls))

        # Case C: 0-folder project archive + restore roundtrip via CLI --json
        rc, out_z, err_z = run_main(ctx, "start", "--name", "Zero Roundtrip", "--kind", "agy", "--json")
        self.assertEqual(rc, 0, err_z)
        z_slug = json.loads(out_z)["slug"]
        Ledger(ctx).save({"id": "zero-1", "project": z_slug, "project_slug": z_slug, "repo": "", "title": "Plan", "status": "in_progress", "created": ctx.clock.now()})
        rc_a, out_a, err_a = run_main(ctx, "archive", z_slug, "--json")
        self.assertEqual(rc_a, 0, err_a)
        self.assertEqual(json.loads(out_a)["paused"], 1)
        rc_r, out_r, err_r = run_main(ctx, "restore", z_slug, "--json")
        self.assertEqual(rc_r, 0, err_r)
        self.assertEqual(json.loads(out_r)["restored"], 1)
        self.assertEqual(Ledger(ctx).load("zero-1").status, "in_progress")

    def test_archive_d1_fail_closed_on_missing_or_failed_terminal_probe(self) -> None:
        # 1) get_raw returns None / {} -> keep Space (do not close)
        # 2) get_raw raises an error -> keep Space (do not close)
        # 3) get_raw returns unknown state (neither live nor finished) -> keep Space
        # 4) get_raw confirms non-PM terminal state == 'finished' -> close Space
        for probe_mode, expect_close in [
            ("none", False),
            ("error", False),
            ("unknown_state", False),
            ("finished", True),
        ]:
            with self.subTest(probe_mode=probe_mode):
                hc = FakeHc(
                    terminals={
                        "t1": {"state": "live", "labels": {"pm": "alpha", "pm.seat": "1", "herdr.space": "sp-fc"}},
                    },
                    app_available=True,
                )
                orig_get_raw = hc.get_raw
                app_calls: list[tuple[str, dict]] = []

                def custom_get_raw(addr: str, *, _orig=orig_get_raw, _mode=probe_mode):
                    if addr == "t_other":
                        if _mode == "none":
                            return None
                        if _mode == "error":
                            raise RuntimeError("hc timeout")
                        if _mode == "unknown_state":
                            return {"address": "t_other", "state": "starting"}
                        if _mode == "finished":
                            return {"address": "t_other", "state": "finished"}
                    return _orig(addr)

                hc.get_raw = custom_get_raw  # type: ignore[method-assign]
                hc.app_spaces = lambda: [  # type: ignore[method-assign]
                    {"id": "sp-fc", "name": "Alpha", "folder": self.repo_s, "tabs": [
                        {"id": "tab-pm", "panes": 1, "terminals": [{"terminal": "t1"}]},
                        {"id": "tab-other", "panes": 1, "terminals": [{"terminal": "t_other"}]},
                    ]},
                ]

                def track_app_do(command: str, payload, *, timeout: float = 30):
                    app_calls.append((command, dict(payload)))
                    return mock.Mock(returncode=0, stdout='{"ok":true}', stderr="")

                hc.app_do = track_app_do  # type: ignore[method-assign]
                ctx = self._ctx(hc=hc)
                ctx.store.change_registration(self.slug, lambda _: {
                    "slug": self.slug, "project": "alpha", "display_name": "Alpha", "space_name": "Alpha",
                    "space_id": "sp-fc", "repo": self.repo_s, "folders": [{"path": self.repo_s, "alias": "alpha", "git": False}],
                    "name": f"pm-{self.slug}", "pane": "hc:t1", "runtime": "hc", "terminal": "t1", "seat": True, "agent": "claude",
                })
                arch = ManagerSessions(ctx).archive(self.repo_s)
                if expect_close:
                    self.assertTrue(arch.space_closed)
                    self.assertFalse(arch.space_kept)
                    self.assertIn(("space.close", {"id": "sp-fc", "confirmed": True}), app_calls)
                else:
                    self.assertFalse(arch.space_closed)
                    self.assertTrue(arch.space_kept)
                    self.assertFalse(any(c == "space.close" for c, _ in app_calls))


if __name__ == "__main__":
    unittest.main()
