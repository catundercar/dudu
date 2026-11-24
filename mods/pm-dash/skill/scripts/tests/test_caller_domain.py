"""Context-isolated unit tests for Stage 3b `Caller` inversion: single-read `terminal_info`/`labels`,
instance-cached TUI multi-session inventory, role/guard resolution, and zero module-global coupling."""
from __future__ import annotations

import json
import os
from pathlib import Path
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
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-caller-3b")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

from fakes import FakeHc, FakeTui, StubGit, make_ctx  # noqa: E402
from pmlib import caller as caller_mod  # noqa: E402
from pmlib.caller import Caller, Role  # noqa: E402
from pmlib.context import Context  # noqa: E402
from pmlib.errors import IdentityError  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.project.project import ProjectRegistry  # noqa: E402


class CallerDomainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / "proj"
        self.other = self.base / "other"
        self.repo.mkdir()
        self.other.mkdir()
        self.git = StubGit(roots={
            str(self.repo): str(self.repo),
            str(self.other): str(self.other),
        })

    def _seed_ledger(self, ctx, *, registration: dict, tasks: list[dict] | None = None):
        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        rec = {"project": "proj", "repo": str(self.repo), "name": "pm-proj", **registration}
        ctx.home.registration("proj").write_text(json.dumps(rec), encoding="utf-8")
        default_tasks = [
            {"id": "w-1", "project": "proj", "repo": str(self.repo), "worktree": str(self.repo),
             "status": "in_progress", "pane": "hc:tW", "dispatched": True, "number": 1, "log": []},
            {"id": "w-1-review", "project": "proj", "repo": str(self.repo),
             "status": "in_progress", "pane": "hc:tR", "review_of": "w-1", "log": []},
            {"id": "b-3", "project": "proj", "repo": str(self.repo), "status": "blocked",
             "pane": "hc:tW", "number": 3, "log": [{"by": "hc:tW", "text": "status=blocked; which way?"}]},
        ]
        for task in (default_tasks if tasks is None else tasks):
            ctx.home.task(task["id"]).write_text(json.dumps(task), encoding="utf-8")

    def test_single_read_terminal_info_shared_across_labels_own_task_helper_and_role(self):
        hc = FakeHc({
            "tPM": {"state": "live", "labels": {"pm": "proj"}, "cwd": str(self.repo)},
            "tW": {"state": "live", "labels": {"task": "w-1"}, "cwd": str(self.repo)},
        })
        ctx = make_ctx(self.base, pane="hc:tW", hc=hc, git=self.git)
        self._seed_ledger(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        caller = Caller.from_context(ctx)
        self.assertIs(caller, ctx.caller)
        with mock.patch.object(hc, "get", wraps=hc.get) as get_spy:
            self.assertEqual(caller.terminal_info.address, "tW")
            self.assertEqual(caller.labels, {"task": "w-1"})
            self.assertEqual(caller.own_task["id"], "w-1")
            self.assertIsNone(caller.helper)
            self.assertEqual(caller.helper_caller_identity()[0], "task")
            self.assertEqual(caller.role_in(self.repo), Role(Role.WORKER, task="w-1"))
            # Only one `hc.get("tW")` across all five queries.
            self.assertEqual(get_spy.call_args_list, [mock.call("tW")])

    def test_helper_terminal_labels_and_env_fallback(self):
        hc = FakeHc({
            "tPM": {"state": "live", "labels": {"pm": "proj"}},
            "tH": {"state": "live", "labels": {"helper": "look", "helper.of": "w-1", "helper.project": "proj"}},
        })
        ctx = make_ctx(self.base, pane="hc:tH", hc=hc, git=self.git)
        self._seed_ledger(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        caller = Caller(ctx)
        with mock.patch.object(hc, "get", wraps=hc.get) as get_spy:
            self.assertEqual(
                caller.helper,
                {"of": "w-1", "name": "look", "project": "proj", "terminal": "tH"},
            )
            self.assertEqual(caller.helper_caller_identity(), ("helper", caller.helper))
            self.assertEqual(caller.role_in(self.repo), Role(Role.HELPER, owner="w-1"))
            self.assertEqual(get_spy.call_args_list, [mock.call("tH")])

        # Fallback to PM_HELPER_* env vars when terminal has no labels.
        hc_empty = FakeHc({"tH2": {"state": "live", "labels": {}}})
        ctx_env = make_ctx(
            self.base / "env_case",
            pane="hc:tH2",
            hc=hc_empty,
            git=self.git,
            env={"PM_HELPER_OF": "w-1", "PM_HELPER_NAME": "scout", "PM_HELPER_PROJECT": "proj"},
        )
        self.assertEqual(
            Caller(ctx_env).helper_self_info(),
            {"of": "w-1", "name": "scout", "project": "proj", "terminal": "tH2"},
        )

    def test_own_task_falls_back_to_claude_session_id_without_hc_label(self):
        hc = FakeHc({"tS": {"state": "live", "labels": {}}})
        ctx = make_ctx(
            self.base,
            pane="hc:tS",
            hc=hc,
            git=self.git,
            env={"CLAUDE_CODE_SESSION_ID": "sid-123"},
        )
        self._seed_ledger(
            ctx,
            registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"},
            tasks=[{
                "id": "s-1",
                "project": "proj",
                "repo": str(self.repo),
                "status": "in_progress",
                "pane": "hc:tS",
                "dispatched": True,
                "session": {"kind": "claude", "id": "sid-123"},
                "log": [],
            }],
        )
        caller = Caller(ctx)
        self.assertEqual(caller.own_task["id"], "s-1")
        self.assertEqual(caller.role_in(self.repo), Role(Role.WORKER, task="s-1"))

    def test_tui_inventory_is_instance_cached_and_does_not_touch_module_globals(self):
        tui = FakeTui(
            sessions=[{"name": "default", "socket_path": "/s/default.sock", "running": True}],
            agents=[{"pane_id": "w1:p1", "workspace_id": "w1", "name": "pm-proj", "session": "default"}],
            panes=[{"pane_id": "w1:p1", "workspace_id": "w1", "agent": "claude", "session": "default"}],
            current_session="default",
        )
        ctx = make_ctx(
            self.base,
            pane="w1:p1",
            workspace="w1",
            tui=tui,
            git=self.git,
            env={"HERDR_ENV": "1"},
        )
        self._seed_ledger(ctx, registration={"pane": "w1:p1", "workspace": "w1", "session": "default"})

        here = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, here)

        self.assertFalse(hasattr(caller_mod, "_IDENTITY"))
        self.assertFalse(hasattr(caller_mod, "_SESSION"))
        c1 = Caller(ctx)
        inv1 = c1.identity_inventory()
        calls_after_first = len(tui.calls)
        self.assertIs(c1.identity_inventory(), inv1)
        self.assertEqual(len(tui.calls), calls_after_first)
        guard = c1.check_guard("coordinate", self.repo)
        self.assertEqual(guard["role"], "pm")
        self.assertEqual(guard["caller"], {"session": "default", "workspace": "w1", "pane": "w1:p1"})
        self.assertEqual(c1.own_pm_record(self.repo)["name"], "pm-proj")
        self.assertEqual(c1.workspace_registration()["name"], "pm-proj")
        self.assertEqual(c1.memory_writer(self.repo), ("pm", "pm"))
        self.assertEqual(list(c1.caller_projects([])), ["proj"])

        # A second Caller instance builds its own fresh inventory.
        c2 = Caller(ctx)
        inv2 = c2.identity_inventory()
        self.assertIsNot(inv2, inv1)

    def test_tui_server_down_raises_identity_error(self):
        tui = FakeTui(server_ok=False)
        ctx = make_ctx(self.base, pane="w1:p1", workspace="w1", tui=tui, git=self.git, env={"HERDR_ENV": "1"})
        caller = Caller(ctx)
        with self.assertRaises(IdentityError):
            caller.herdr_sessions()
        with self.assertRaises(IdentityError):
            caller.socket_session()
        self.assertEqual(caller.herdr_session(), "")

    def test_shell_observer_and_guard_authorization(self):
        tui = FakeTui(
            sessions=[{"name": "default", "socket_path": "/s/default.sock", "running": False}],
            current_session="default",
        )
        ctx = make_ctx(self.base, pane="", tui=tui, git=self.git)
        self._seed_ledger(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        caller = Caller(ctx)
        self.assertFalse(caller.app_caller())
        self.assertFalse(caller.in_tui())
        self.assertEqual(caller.role_in(self.repo), Role(Role.USER))
        self.assertEqual(caller.memory_writer(self.repo), ("user", "user"))
        self.assertEqual(caller.helper_caller_identity(), ("cli", None))
        self.assertEqual(caller.check_guard("read", self.repo)["role"], "observer")
        with self.assertRaises(IdentityError):
            caller.check_guard("coordinate", self.repo)

    def test_desktop_pm_and_moved_hc_guard_and_blocked_by_worker(self):
        hc = FakeHc({"tPM": {"state": "live", "labels": {"pm": "proj"}, "cwd": str(self.repo)}})
        ctx_pm = make_ctx(self.base, pane="hc:tPM", hc=hc, git=self.git)
        self._seed_ledger(ctx_pm, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        pm_caller = Caller(ctx_pm)
        self.assertTrue(pm_caller.app_caller())
        self.assertTrue(pm_caller.is_pm_caller(repo=self.repo))
        self.assertEqual(pm_caller.check_guard("coordinate", self.repo)["role"], "pm")
        with self.assertRaises(IdentityError):
            pm_caller.check_guard("implement", self.repo)
        b3 = json.loads(ctx_pm.home.task("b-3").read_text())
        self.assertTrue(pm_caller.blocked_by_worker(b3))

        # Worker that blocked b-3 sees blocked_by_worker == False.
        ctx_w = make_ctx(self.base, pane="hc:tW", hc=hc, git=self.git)
        self.assertFalse(Caller(ctx_w).blocked_by_worker(b3))

        # Moved desktop PM terminal (labelled pm=other) is uncertain under check_guard.
        hc_moved = FakeHc({"tPM": {"state": "live", "labels": {"pm": "other"}, "cwd": str(self.other)}})
        ctx_moved = make_ctx(self.base, pane="hc:tPM", hc=hc_moved, git=self.git)
        self.assertEqual(Caller(ctx_moved).check_guard("read", self.repo)["role"], "uncertain")
        with self.assertRaises(IdentityError):
            Caller(ctx_moved).check_guard("coordinate", self.repo)

    def test_from_env_wires_ctx_caller_and_caches_from_context(self):
        env_ctx = Context.from_env(self.base / "env_home", env={"HC_TERMINAL_ID": "t7"})
        self.assertIsInstance(env_ctx.caller, Caller)
        self.assertEqual((env_ctx.caller.pane, env_ctx.caller.terminal, env_ctx.caller.herdr_pane), ("hc:t7", "t7", ""))
        self.assertIs(Caller.from_context(env_ctx), env_ctx.caller)

        # Clearing ctx.caller causes from_context() to rebuild and cache back onto ctx.caller.
        env_ctx.caller = None
        rebuilt = Caller.from_context(env_ctx)
        self.assertIs(env_ctx.caller, rebuilt)
        self.assertIs(Caller.from_context(env_ctx), rebuilt)

    def test_fake_tui_server_down_and_socket_session_validation_match_tui_host(self):
        down = FakeTui(server_ok=False)
        ctx_down = make_ctx(self.base, pane="", tui=down, git=self.git)
        self.assertEqual(down.agents(), [])
        self.assertEqual(down.pane_read("w1:p1"), "")
        self.assertIsNone(ProjectRegistry(ctx_down).find_pm(repo=self.repo))
        with self.assertRaises(IdentityError):
            down.sessions()
        with self.assertRaises(IdentityError):
            down.socket_session()

        # socket_session(None) must validate self._sessions (running + matching current_session).
        stopped = FakeTui(
            sessions=[{"name": "default", "socket_path": "/s/default.sock", "running": False}],
            current_session="default",
        )
        with self.assertRaises(IdentityError):
            stopped.socket_session()
        missing = FakeTui(
            sessions=[{"name": "other", "socket_path": "/s/other.sock", "running": True}],
            current_session="default",
        )
        with self.assertRaises(IdentityError):
            missing.socket_session()
        ok = FakeTui(
            sessions=[{"name": "default", "socket_path": "/s/default.sock", "running": True}],
            current_session="default",
        )
        self.assertEqual(ok.socket_session(), "default")

    def test_caller_pane_override_derives_terminal_and_herdr_pane(self):
        ctx_hc = make_ctx(self.base, pane="hc:t1", git=self.git)
        c_hc = Caller(ctx_hc, pane="hc:t9")
        self.assertEqual((c_hc.pane, c_hc.terminal, c_hc.herdr_pane), ("hc:t9", "t9", ""))
        c_tui = Caller(ctx_hc, pane="w2:p3")
        self.assertEqual((c_tui.pane, c_tui.terminal, c_tui.herdr_pane), ("w2:p3", "", "w2:p3"))
        c_shell = Caller(ctx_hc, pane="")
        self.assertEqual((c_shell.pane, c_shell.terminal, c_shell.herdr_pane), ("", "", ""))
        c_explicit = Caller(ctx_hc, pane="hc:t9", terminal="custom", herdr_pane="w9:p9")
        self.assertEqual((c_explicit.pane, c_explicit.terminal, c_explicit.herdr_pane), ("hc:t9", "custom", "w9:p9"))

    def test_load_bare_number_disambiguates_via_from_env_and_make_ctx_caller_projects(self):
        repo_a = self.base / "alpha"
        repo_b = self.base / "beta"
        repo_a.mkdir()
        repo_b.mkdir()
        git = StubGit(roots={str(repo_a): str(repo_a), str(repo_b): str(repo_b)})

        # 1. make_ctx automatically wires ctx.caller_projects from ctx.caller.
        ctx_mc = make_ctx(self.base / "mc", pane="hc:tPM-a", git=git)
        self.assertIsNotNone(ctx_mc.caller_projects)
        ctx_mc.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx_mc.home.registration("alpha").write_text(json.dumps({
            "project": "alpha", "repo": str(repo_a), "name": "pm-alpha",
            "runtime": "hc", "terminal": "tPM-a", "pane": "hc:tPM-a",
        }), encoding="utf-8")
        ledger_mc = Ledger(ctx_mc)
        ledger_mc.create({"id": "alpha-1", "title": "A1", "project": "alpha", "repo": str(repo_a), "status": "proposed", "number": 1})
        ledger_mc.create({"id": "beta-1", "title": "B1", "project": "beta", "repo": str(repo_b), "status": "proposed", "number": 1})
        self.assertEqual(ledger_mc.load("#1").id, "alpha-1")

        # 2. Context.from_env automatically wires ctx.caller_projects from ctx.caller.
        env_home = self.base / "env_disambig"
        ctx_env = Context.from_env(env_home, env={"HC_TERMINAL_ID": "tPM-b"})
        self.assertIsNotNone(ctx_env.caller_projects)
        ctx_env.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx_env.home.registration("beta").write_text(json.dumps({
            "project": "beta", "repo": str(repo_b), "name": "pm-beta",
            "runtime": "hc", "terminal": "tPM-b", "pane": "hc:tPM-b",
        }), encoding="utf-8")
        ledger_env = Ledger(ctx_env)
        ledger_env.create({"id": "alpha-1", "title": "A1", "project": "alpha", "repo": str(repo_a), "status": "proposed", "number": 1})
        ledger_env.create({"id": "beta-1", "title": "B1", "project": "beta", "repo": str(repo_b), "status": "proposed", "number": 1})
        self.assertEqual(ledger_env.load("#1").id, "beta-1")


if __name__ == "__main__":
    unittest.main()
