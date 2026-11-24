"""Stage 7a behavioral tests (docs/design/pm-py-pass-two.md, section 5.3):
1. Moved manager terminals (moved_hc / moved_tui): manages() checks live host facts, own_pm_record() -> None,
   role_in() -> SESSION, guard stays 'uncertain'.
2. Helpers & repo-scoped role_in: single hc.get on Caller, role_in(repo) scopes WORKER/REVIEWER/HELPER to repo,
   wake_rule maps HELPER -> source='helper' (wakes on reports like WORKER), memory_writer maps HELPER ->
   ('helper', 'helper:<name>') with worker-level write rules (pitfalls & references only).
3. wake_rule / is_news alignment on done & proposed + explicit 'wake': False when app_pm exists.
"""
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

from fakes import FakeHc, FakeTui, StubGit, make_ctx  # noqa: E402
from pmlib.caller import Caller, Role  # noqa: E402
from pmlib.errors import IdentityError  # noqa: E402
from pmlib.events import policy  # noqa: E402
from pmlib.ledger.transition import UpdateRequest  # noqa: E402
from pmlib.memory.layer import MemoryLayer, MemoryRefused  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.reactions import Updates  # noqa: E402


class Stage7aCallerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-7a-")
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

    def _seed(self, ctx, *, registration: dict, tasks: list[dict] | None = None):
        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        rec = {"project": "proj", "repo": str(self.repo), "name": "pm-proj", **registration}
        ctx.home.registration("proj").write_text(json.dumps(rec), encoding="utf-8")
        default_tasks = [
            {"id": "w-1", "project": "proj", "repo": str(self.repo), "worktree": str(self.repo),
             "status": "in_progress", "pane": "hc:tW", "dispatched": True, "number": 1, "log": []},
            {"id": "w-1-review", "project": "proj", "repo": str(self.repo),
             "status": "in_progress", "pane": "hc:tR", "review_of": "w-1", "log": []},
            {"id": "w-2-review", "project": "proj", "repo": str(self.repo),
             "status": "done", "pane": "hc:tR2", "review_of": "w-1", "log": []},
            {"id": "p-2", "project": "proj", "repo": str(self.repo),
             "status": "review", "pane": "hc:tPM", "number": 2, "log": []},
            {"id": "prop-3", "project": "proj", "repo": str(self.repo),
             "status": "proposed", "pane": "hc:tPM", "number": 3, "created": "2026-11-22 08:00",
             "log": [{"by": "hc:tPM", "at": "2026-11-22 08:00", "text": "registered (proposed)"}]},
        ]
        for task in (default_tasks if tasks is None else tasks):
            ctx.home.task(task["id"]).write_text(json.dumps(task), encoding="utf-8")

    # ---- 1. Moved manager terminals (moved_hc / moved_tui) ----

    def test_moved_hc_terminal_is_not_manager_and_guard_stays_uncertain(self):
        hc = FakeHc({"tPM": {"state": "live", "labels": {"pm": "other"}, "cwd": str(self.other)}})
        ctx = make_ctx(self.base / "moved-hc", pane="hc:tPM", hc=hc, git=self.git)
        self._seed(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        caller = Caller(ctx)
        with mock.patch.object(hc, "get", wraps=hc.get) as get_spy:
            self.assertFalse(caller.manages(self.repo))
            self.assertIsNone(caller.own_pm_record())
            self.assertFalse(caller.is_pm_caller(repo=self.repo))
            self.assertEqual(caller.role_in(self.repo), Role(Role.SESSION))
            self.assertEqual(caller.memory_writer(self.repo), ("other", "session:hc:tPM"))
            task = json.loads(ctx.home.task("p-2").read_text())
            self.assertEqual(policy.wake_rule(task, "", True, caller), {"source": "session"})
            # Single hc.get across all Caller queries.
            self.assertEqual(get_spy.call_args_list, [mock.call("tPM")])
        # Guard continues returning uncertain and refusing mutations.
        self.assertEqual(caller.check_guard("read", self.repo)["role"], "uncertain")
        with self.assertRaises(IdentityError):
            caller.check_guard("coordinate", self.repo)
        with self.assertRaises(IdentityError):
            caller.check_guard("implement", self.repo)

    def test_moved_tui_terminal_is_not_manager_and_guard_stays_uncertain(self):
        tui = FakeTui(
            sessions=[{"name": "default", "socket_path": "/s/default.sock", "running": True}],
            agents=[{"pane_id": "w1:p1", "workspace_id": "w1", "name": "pm-other", "agent_status": "idle"}],
            panes=[{"pane_id": "w1:p1", "workspace_id": "w1", "agent": "claude"}],
            current_session="default",
        )
        ctx = make_ctx(
            self.base / "moved-tui",
            pane="w1:p1",
            workspace="w1",
            tui=tui,
            git=self.git,
            env={"HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1"},
        )
        self._seed(ctx, registration={"pane": "w1:p1", "workspace": "w1", "session": "default"})
        here = os.getcwd()
        os.chdir(self.other)
        self.addCleanup(os.chdir, here)

        caller = Caller(ctx)
        self.assertFalse(caller.manages(self.repo))
        self.assertIsNone(caller.own_pm_record(self.other))
        self.assertFalse(caller.is_pm_caller(repo=self.repo))
        self.assertEqual(caller.role_in(self.repo), Role(Role.SESSION))
        self.assertEqual(caller.memory_writer(self.repo), ("other", "session:w1:p1"))
        task = json.loads(ctx.home.task("p-2").read_text())
        self.assertEqual(policy.wake_rule(task, "", True, caller), {"source": "session"})
        self.assertEqual(caller.check_guard("read", self.repo)["role"], "uncertain")
        with self.assertRaises(IdentityError):
            caller.check_guard("coordinate", self.repo)

    # ---- 2. Helper identity, repo-scoped role_in, and memory write permissions ----

    def test_role_in_scopes_worker_reviewer_and_helper_to_repo(self):
        hc = FakeHc({
            "tPM": {"state": "live", "labels": {"pm": "proj"}},
            "tW": {"state": "live", "labels": {"task": "w-1"}},
            "tR": {"state": "live", "labels": {"task": "w-1-review"}},
            "tH": {"state": "live", "labels": {"helper": "look", "helper.of": "w-1", "helper.project": "proj"}},
        })
        home = self.base / "scoped"
        ctx_w = make_ctx(home, pane="hc:tW", hc=hc, git=self.git)
        self._seed(ctx_w, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        self.assertEqual(Caller(ctx_w).role_in(self.repo), Role(Role.WORKER, task="w-1"))
        self.assertEqual(Caller(ctx_w).role_in(self.other), Role(Role.SESSION))

        ctx_r = make_ctx(home, pane="hc:tR", hc=hc, git=self.git)
        self.assertEqual(Caller(ctx_r).role_in(self.repo), Role(Role.REVIEWER, task="w-1-review"))
        self.assertEqual(Caller(ctx_r).role_in(self.other), Role(Role.SESSION))

        ctx_h = make_ctx(home, pane="hc:tH", hc=hc, git=self.git)
        self.assertEqual(Caller(ctx_h).role_in(self.repo), Role(Role.HELPER, owner="w-1"))
        self.assertEqual(Caller(ctx_h).role_in(self.other), Role(Role.SESSION))

    def test_helper_wake_rule_is_news_and_single_hc_get(self):
        hc = FakeHc({
            "tPM": {"state": "live", "labels": {"pm": "proj"}},
            "tH": {"state": "live", "labels": {"helper": "look", "helper.of": "w-1", "helper.project": "proj"}},
        })
        ctx = make_ctx(self.base / "helper-wake", pane="hc:tH", hc=hc, git=self.git)
        self._seed(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        caller = Caller(ctx)

        with mock.patch.object(hc, "get", wraps=hc.get) as get_spy:
            self.assertEqual(caller.role_in(self.repo), Role(Role.HELPER, owner="w-1"))
            self.assertEqual(caller.memory_writer(self.repo), ("helper", "helper:look"))
            self.assertEqual(caller.memory_writer(self.other), ("other", "session:hc:tH"))
            for st, wakes in (("review", True), ("blocked", True), ("done", True), ("in_progress", False), ("proposed", False)):
                target = {"id": "p-2", "repo": str(self.repo), "status": st, "pane": "hc:tPM"}
                expected = {"source": "helper", **({"wake": True} if wakes else {})}
                self.assertEqual(policy.wake_rule(target, "", True, caller), expected, st)
            # Helper from proj writing to other project's task is just a session.
            other_task = {"id": "o-1", "repo": str(self.other), "status": "review", "pane": "hc:tOther"}
            self.assertEqual(policy.wake_rule(other_task, "", True, caller), {"source": "session"})
            self.assertEqual(get_spy.call_args_list, [mock.call("tH")])

        # is_news aligns with wake_rule for helper reports.
        pms = {"hc:tPM"}
        task_of = lambda tid: {"id": tid, "status": "review", "created": "2026-11-22 08:00", "log": []}
        base_entry = {"type": "thread", "task": "p-2", "by": "hc:tH", "at": "2026-11-22 10:00:00", "source": "helper"}
        self.assertTrue(policy.is_news({**base_entry, "status": "review", "text": "found the cause"}, pms, task_of))
        self.assertTrue(policy.is_news({**base_entry, "status": "done", "text": "commit=abc1234; fixed"}, pms, task_of))
        self.assertFalse(policy.is_news({**base_entry, "status": "proposed", "text": "a note"}, pms, task_of))

    def test_helper_memory_write_permissions_match_worker(self):
        hc = FakeHc({
            "tPM": {"state": "live", "labels": {"pm": "proj"}},
            "tH": {"state": "live", "labels": {"helper": "scout", "helper.of": "w-1", "helper.project": "proj"}},
        })
        ctx = make_ctx(self.base / "helper-mem", pane="hc:tH", hc=hc, git=self.git)
        self._seed(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        writer = Caller(ctx).memory_writer(self.repo)
        self.assertEqual(writer, ("helper", "helper:scout"))

        layer = MemoryLayer(ctx, self.repo)
        # Can write pitfall (with --verified) and reference.
        m_pit, _ = layer.remember("watch out for race", writer=writer, kind="pitfall", name="race-pitfall",
                                  verified="reproduced in test")
        self.assertEqual((m_pit["type"], m_pit["by"]), ("pitfall", "helper:scout"))
        m_ref, _ = layer.remember("docs live in docs/", writer=writer, kind="reference", name="docs-loc")
        self.assertEqual((m_ref["type"], m_ref["by"]), ("reference", "helper:scout"))

        # Default kind without --type is pitfall (same as worker), and --type project without quote converts to pitfall.
        m_def, notes = layer.remember("another pitfall", writer=writer, kind="project", name="conv-pitfall",
                                      verified="seen in log")
        self.assertEqual(m_def["type"], "pitfall")
        self.assertTrue(notes)

        # Refused: feedback, user, personal layer, and forgetting another writer's memory.
        with self.assertRaises(MemoryRefused):
            layer.remember("always reply short", writer=writer, kind="feedback", name="fb-1", quote="reply short")
        with self.assertRaises(MemoryRefused):
            MemoryLayer(ctx, None).remember("personal ref", writer=writer, kind="reference", name="pers-1")
        pm_m, _ = layer.remember("pm decision", writer=("pm", "pm"), kind="project", name="pm-dec", verified="user")
        with self.assertRaises(MemoryRefused):
            layer.forget(pm_m, writer=writer)
        # Can forget its own memory.
        saved_ref = layer.read(layer.dir / "docs-loc.md")
        self.assertIsNotNone(saved_ref)
        layer.forget(saved_ref, writer=writer)

    # ---- 3. wake_rule / is_news alignment on done & proposed + explicit wake: False ----

    def test_reviewer_followup_note_on_done_wakes_and_starts_deliverer(self):
        hc = FakeHc({
            "tPM": {"state": "live", "labels": {"pm": "proj"}},
            "tR2": {"state": "live", "labels": {"task": "w-2-review"}},
        })
        ctx = make_ctx(self.base / "done-wake", pane="hc:tR2", hc=hc, git=self.git)
        self._seed(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        done = Updates(ctx).update(UpdateRequest(id="w-2-review", note="以这条为准：无阻塞"))
        self.assertTrue(done.transition.entry_fields.get("wake"))
        self.assertEqual(done.transition.entry_fields.get("source"), "worker")
        self.assertTrue(any(s.get("args", [])[:1] == ["deliver"] for s in ctx.procs.spawned))
        events = Conversation(ctx, self.repo).events()
        self.assertTrue(events[-1]["wake"])

    def test_non_moving_note_on_proposed_does_not_wake_and_writes_explicit_wake_false(self):
        hc = FakeHc({
            "tPM": {"state": "live", "labels": {"pm": "proj"}},
            "tW": {"state": "live", "labels": {"task": "w-1"}},
        })
        ctx = make_ctx(self.base / "prop-quiet", pane="hc:tW", hc=hc, git=self.git)
        self._seed(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        done = Updates(ctx).update(UpdateRequest(id="prop-3", note="just a thought"))
        self.assertIs(done.transition.entry_fields.get("wake"), False)
        self.assertFalse(any(s.get("args", [])[:1] == ["deliver"] for s in ctx.procs.spawned))
        events = Conversation(ctx, self.repo).events()
        self.assertIs(events[-1]["wake"], False)
        # is_news also returns False even if wake field were absent (legacy log entry).
        entry_without_wake = {k: v for k, v in events[-1].items() if k != "wake"}
        prop_task = json.loads(ctx.home.task("prop-3").read_text())
        self.assertFalse(policy.is_news(entry_without_wake, {"hc:tPM"}, lambda _: prop_task))

    def test_wake_fields_writes_explicit_wake_false_only_when_app_pm_exists(self):
        hc = FakeHc({"tPM": {"state": "live", "labels": {"pm": "proj"}}})
        ctx = make_ctx(self.base / "explicit-false", pane="hc:tPM", hc=hc, git=self.git)
        self._seed(ctx, registration={"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"})
        caller = Caller(ctx)
        task = json.loads(ctx.home.task("p-2").read_text())
        # With app_pm: non-waking entries carry explicit "wake": False.
        self.assertEqual(policy.wake_fields_for(task, "", True, caller, True), {"source": "pm", "wake": False})
        # Without app_pm (e.g. TUI PM): "wake" key is omitted.
        self.assertEqual(policy.wake_fields_for(task, "", True, caller, False), {"source": "pm"})


class Stage7aReviewFindingsTests(unittest.TestCase):
    """Regression tests for Stage 7a edge-case bugs found in pass-two final review r3."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-7a-r3-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.alpha = self.base / "alpha"
        self.zeta = self.base / "zeta"
        self.alpha.mkdir()
        self.zeta.mkdir()
        self.git = StubGit(roots={
            str(self.alpha): str(self.alpha),
            str(self.zeta): str(self.zeta),
        })

    def test_moved_hc_helper_caller_identity_is_not_old_pm_registered_task(self):
        # Terminal tPM now hosts another project's PM (`labels={"pm": "zeta"}`), while alpha's registration still
        # points at `hc:tPM` and alpha has an open PM-registered (non-dispatched) task `p-2` with `pane="hc:tPM"`.
        # `helper_caller_identity()` must NOT treat `tPM` as the worker of `p-2`.
        hc = FakeHc({"tPM": {"state": "live", "labels": {"pm": "zeta"}, "cwd": str(self.zeta)}})
        ctx = make_ctx(self.base / "h1", pane="hc:tPM", hc=hc, git=self.git)
        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        ctx.home.registration("alpha").write_text(json.dumps({
            "project": "alpha", "repo": str(self.alpha), "name": "pm-alpha",
            "runtime": "hc", "terminal": "tPM", "pane": "hc:tPM",
        }))
        ctx.home.task("p-2").write_text(json.dumps({
            "id": "p-2", "project": "alpha", "repo": str(self.alpha),
            "status": "review", "pane": "hc:tPM", "number": 2, "log": [],
        }))
        kind, payload = Caller(ctx).helper_caller_identity()
        self.assertEqual((kind, payload), ("worker_unknown", None))

    def test_stale_or_archived_registration_on_same_pane_does_not_shadow_live_pm(self):
        # `pms/alpha.json` still records `pane="hc:tPM"` (either archived or stale from before tPM moved to zeta),
        # while `pms/zeta.json` is the active registration for `tPM` (`labels={"pm": "zeta"}`).
        # `own_pm_record()`, `own_registration()`, and `check_guard("coordinate", zeta)` must recognize `pm-zeta`.
        hc = FakeHc({"tPM": {"state": "live", "labels": {"pm": "zeta"}, "cwd": str(self.zeta)}})
        ctx = make_ctx(self.base / "h2", pane="hc:tPM", hc=hc, git=self.git)
        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx.home.registration("alpha").write_text(json.dumps({
            "project": "alpha", "repo": str(self.alpha), "name": "pm-alpha",
            "runtime": "hc", "terminal": "tPM", "pane": "hc:tPM",
        }))
        ctx.home.registration("zeta").write_text(json.dumps({
            "project": "zeta", "repo": str(self.zeta), "name": "pm-zeta",
            "runtime": "hc", "terminal": "tPM", "pane": "hc:tPM",
        }))
        caller = Caller(ctx)
        self.assertEqual((caller.own_pm_record() or {}).get("name"), "pm-zeta")
        self.assertEqual((caller.own_registration() or {}).get("name"), "pm-zeta")
        self.assertEqual(caller.check_guard("coordinate", self.zeta)["role"], "pm")

    def test_reused_pm_terminal_with_worker_label_is_not_manager(self):
        # Old PM terminal `tPM` no longer carries `pm=alpha` and now runs a dispatched worker (`labels={"task": "w-1"}`).
        # `manages()`, `own_pm_record()`, and `role_in()` must treat it as `w-1`'s WORKER, not `alpha`'s MANAGER.
        hc = FakeHc({"tPM": {"state": "live", "labels": {"task": "w-1"}, "cwd": str(self.alpha)}})
        ctx = make_ctx(self.base / "h3", pane="hc:tPM", hc=hc, git=self.git)
        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        ctx.home.registration("alpha").write_text(json.dumps({
            "project": "alpha", "repo": str(self.alpha), "name": "pm-alpha",
            "runtime": "hc", "terminal": "tPM", "pane": "hc:tPM",
        }))
        ctx.home.task("w-1").write_text(json.dumps({
            "id": "w-1", "project": "alpha", "repo": str(self.alpha),
            "status": "in_progress", "pane": "hc:tPM", "dispatched": True, "log": [],
        }))
        caller = Caller(ctx)
        self.assertFalse(caller.manages(self.alpha))
        self.assertIsNone(caller.own_pm_record())
        self.assertEqual(caller.role_in(self.alpha), Role(Role.WORKER, task="w-1"))

    def test_memory_writer_scopes_active_worker_to_repo_and_respects_helper_on_reused_pane(self):
        # 1) Active worker of `alpha` writing to `zeta` must be ("other", "session:..."), matching `role_in(zeta)`.
        # 2) Helper running in a terminal ID previously used by a CLOSED (`merged`) worker task must be identified as
        #    ("helper", "helper:scout"), not the closed worker.
        hc = FakeHc({
            "tW": {"state": "live", "labels": {"task": "alpha-1"}},
            "tReused": {"state": "live", "labels": {"helper": "scout", "helper.of": "alpha-1", "helper.project": "alpha"}},
        })
        home = self.base / "h4"
        ctx_w = make_ctx(home, pane="hc:tW", hc=hc, git=self.git)
        ctx_w.home.tasks.mkdir(parents=True, exist_ok=True)
        ctx_w.home.task("alpha-1").write_text(json.dumps({
            "id": "alpha-1", "project": "alpha", "repo": str(self.alpha),
            "status": "in_progress", "pane": "hc:tW", "dispatched": True, "log": [],
        }))
        ctx_w.home.task("alpha-old").write_text(json.dumps({
            "id": "alpha-old", "project": "alpha", "repo": str(self.alpha),
            "status": "merged", "pane": "hc:tReused", "dispatched": True, "log": [],
        }))
        self.assertEqual(Caller(ctx_w).memory_writer(self.zeta), ("other", "session:hc:tW"))

        ctx_h = make_ctx(home, pane="hc:tReused", hc=hc, git=self.git)
        self.assertEqual(Caller(ctx_h).memory_writer(self.alpha), ("helper", "helper:scout"))


if __name__ == "__main__":
    unittest.main()
