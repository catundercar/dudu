"""Context-isolated unit tests for Stage 3a domain objects: Task, Ledger, Change, Board, PlanInput, QuestionCard,
deps/family validation, Project, Coordinator, ProjectRegistry, and Conversation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
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
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-domain-3a")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

from fakes import FakeClock, FakeHc, FakeTui, StubGit, make_ctx  # noqa: E402
from pmlib.context import Context  # noqa: E402
from pmlib.errors import NotFound, Refused  # noqa: E402
from pmlib.ledger.board import Board  # noqa: E402
from pmlib.ledger.deps import parse_depends_on  # noqa: E402
from pmlib.ledger.family import Family, parent_of  # noqa: E402
from pmlib.ledger.ledger import Change, Ledger  # noqa: E402
from pmlib.ledger.plan import (  # noqa: E402
    PlanInput,
    auto_review_max_rounds,
    has_pending_review_step,
    has_unfinished_plan,
)
from pmlib.ledger.question import QuestionCard  # noqa: E402
from pmlib.ledger.task import ACTIVE, ATTACHED, CLOSED, Task  # noqa: E402
from pmlib.project import conversation as conversation_mod, project as project_mod  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import Coordinator, Project, ProjectRegistry  # noqa: E402
from pmlib.terminals.hc import TerminalInfo  # noqa: E402


class TaskViewTests(unittest.TestCase):
    def test_task_view_preserves_unknown_fields_and_exposes_properties(self):
        raw = {
            "id": "demo-feat",
            "title": "Add feature",
            "project": "demo",
            "repo": "/tmp/demo",
            "status": "in_progress",
            "pane": "hc:t42",
            "branch": "dev/feat",
            "number": 7,
            "dispatched": "2026-11-22 10:00",
            "custom_extra": {"keep": True},
        }
        task = Task(raw)
        self.assertEqual(task.id, "demo-feat")
        self.assertEqual(task.number, 7)
        self.assertEqual(task.hc_terminal, "t42")
        self.assertTrue(task.is_active)
        self.assertFalse(task.is_closed)
        self.assertTrue(task.is_attached)
        self.assertTrue(task.pm_started)
        self.assertTrue(task.started_by_pm)
        self.assertFalse(task.needs_cleanup)
        self.assertEqual(task["custom_extra"], {"keep": True})
        self.assertEqual(task.to_dict()["custom_extra"], {"keep": True})
        self.assertEqual(ATTACHED, ("in_progress", "review", "blocked"))
        self.assertIn("in_progress", ACTIVE)
        self.assertIn("merged", CLOSED)

        task["status"] = "merged"
        self.assertTrue(task.is_closed)
        self.assertFalse(task.is_attached)
        self.assertTrue(task.needs_cleanup)


class LedgerAndChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "demo"
        self.repo.mkdir()
        self.clock = FakeClock("2026-11-23 09:30:00")
        self.git = StubGit(roots={str(self.repo): str(self.repo.resolve())})
        self.ctx = make_ctx(self.base, pane="hc:t1", clock=self.clock, git=self.git)

    def test_create_load_change_flushes_notes_and_after_save_after_unlock(self):
        events_seen: list[str] = []
        self.ctx.after_save = (
            lambda: events_seen.append("board"),
            lambda: events_seen.append("discord"),
        )
        ledger = Ledger(self.ctx)
        created = ledger.create(
            {
                "id": "demo-one",
                "title": "First task",
                "project": "demo",
                "repo": str(self.repo.resolve()),
                "status": "in_progress",
                "number": 1,
                "created": self.clock.now(),
            },
            note_text="registered (in_progress)",
        )
        self.assertIsInstance(created, Task)
        self.assertEqual(created.updated, "2026-11-23 09:30")
        self.assertEqual(events_seen, ["board", "discord"])

        conv = Conversation(self.ctx, self.repo)
        evs = conv.events()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["type"], "thread")
        self.assertEqual(evs[0]["text"], "registered (in_progress)")
        self.assertEqual(evs[0]["number"], 1)

        events_seen.clear()
        self.clock.advance(60)

        def _edit(cur: Task | None, ch: Change):
            assert cur is not None
            cur["status"] = "review"
            ch.note("ready for review", wake=True)
            # Conversation log must not have the new event while inside the lock!
            self.assertEqual(len(conv.events()), 1)
            return cur

        updated = ledger.change("demo-one", _edit)
        assert updated is not None
        self.assertEqual(updated.status, "review")
        self.assertEqual(updated.updated, "2026-11-23 09:31")
        self.assertEqual(events_seen, ["board", "discord"])
        evs = conv.events()
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[1]["text"], "ready for review")
        self.assertTrue(evs[1]["wake"])

    def test_change_returning_none_skips_save_and_hooks(self):
        hooks: list[str] = []
        self.ctx.after_save = (lambda: hooks.append("ran"),)
        ledger = Ledger(self.ctx)
        ledger.create({"id": "demo-noop", "title": "Noop", "project": "demo", "repo": str(self.repo.resolve()), "status": "proposed"})
        hooks.clear()
        res = ledger.change("demo-noop", lambda cur, ch: None)
        self.assertIsNotNone(res)
        self.assertEqual(hooks, [])

    def test_advance_step_and_update_subplan_are_silent(self):
        hooks: list[str] = []
        self.ctx.after_save = (lambda: hooks.append("ran"),)
        ledger = Ledger(self.ctx)
        ledger.create({
            "id": "demo-plan",
            "title": "Planned",
            "project": "demo",
            "repo": str(self.repo.resolve()),
            "status": "in_progress",
            "plan": [
                {"text": "Step 1", "state": "doing", "anchor": "work"},
                {"text": "Step 2", "state": "todo", "anchor": "review"},
            ],
        })
        hooks.clear()

        task, changed, done_n, total_n, nxt = ledger.advance_step("demo-plan")
        self.assertTrue(changed)
        self.assertEqual((done_n, total_n, nxt), (1, 2, "Step 2"))
        self.assertEqual(hooks, [])
        self.assertEqual(Conversation(self.ctx, self.repo).events(), [])

        task = ledger.update_subplan("demo-plan", [{"text": "Sub 1", "state": "doing"}])
        self.assertEqual(task.subplan, [{"text": "Sub 1", "state": "doing"}])
        self.assertEqual(hooks, [])

        task = ledger.update_subplan("demo-plan", [])
        self.assertNotIn("subplan", task)

    def test_resolve_id_scoping_and_errors(self):
        repo_a = self.base / "alpha"
        repo_b = self.base / "beta"
        repo_a.mkdir()
        repo_b.mkdir()
        self.git.roots[str(repo_a)] = str(repo_a.resolve())
        self.git.roots[str(repo_b)] = str(repo_b.resolve())
        self.ctx.caller_projects = lambda _reg_idx: iter(["alpha"])
        ledger = Ledger(self.ctx)
        ledger.create({"id": "alpha-1", "title": "A1", "project": "alpha", "repo": str(repo_a.resolve()), "status": "proposed", "number": 1})
        ledger.create({"id": "alpha-1-review", "title": "R1", "project": "alpha", "repo": str(repo_a.resolve()), "status": "in_progress", "review_of": "alpha-1"})
        ledger.create({"id": "beta-1", "title": "B1", "project": "beta", "repo": str(repo_b.resolve()), "status": "proposed", "number": 1})

        # caller_projects scopes bare #1 to alpha
        self.assertEqual(ledger.resolve_id("#1"), "alpha-1")
        self.assertEqual(ledger.resolve_id("#1-review"), "alpha-1-review")
        self.assertEqual(ledger.resolve_id("beta#1"), "beta-1")
        self.assertIsNone(ledger.try_resolve_id("99"))
        with self.assertRaises(NotFound):
            ledger.load("no-such-task")
        with self.assertRaises(NotFound):
            ledger.resolve_id("#99")

        # Without caller_projects and outside repos, #1 is ambiguous
        self.ctx.caller_projects = None
        self.ctx.pane = ""
        with self.assertRaises(Refused):
            Ledger(self.ctx).resolve_id("#1")

    def test_board_write_and_two_isolated_contexts(self):
        ledger = Ledger(self.ctx)
        ledger.create({"id": "demo-a", "title": "Alpha", "project": "demo", "repo": str(self.repo.resolve()), "status": "in_progress", "number": 1}, note_text="hi")
        board_path = Board(self.ctx).write()
        text = board_path.read_text(encoding="utf-8")
        self.assertIn("Updated 2026-11-23 09:30.", text)
        self.assertIn("#1 Alpha (`demo-a`)", text)

        with tempfile.TemporaryDirectory() as other_tmp:
            other_ctx = make_ctx(other_tmp)
            self.assertEqual(Ledger(other_ctx).all_tasks(), [])


class PureValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env_patch = mock.patch.dict(os.environ, {"PM_HOME": self.tmp.name})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.ctx = make_ctx(self.tmp.name)
        self.ledger = Ledger(self.ctx)
        self.ledger.create({"id": "t-a", "title": "A", "project": "demo", "repo": "/r", "status": "in_progress", "number": 1})
        self.ledger.create({"id": "t-b", "title": "B", "project": "demo", "repo": "/r", "status": "proposed", "depends_on": ["t-a"], "parent": "t-a"})

    def test_depends_on_and_parent_of_raise_domain_errors(self):
        self.assertEqual(parse_depends_on("t-a", task_id="t-c", home=self.ctx.home), ["t-a"])
        with self.assertRaises(NotFound):
            parse_depends_on("ghost", task_id="t-c", home=self.ctx.home)
        with self.assertRaises(Refused):
            parse_depends_on("t-b", task_id="t-a", home=self.ctx.home)

        self.assertEqual(parent_of("t-c", "#1", ledger=self.ledger), "t-a")
        with self.assertRaises(NotFound):
            parent_of("t-c", "ghost", ledger=self.ledger)
        with self.assertRaises(Refused):
            parent_of("t-a", "t-b", ledger=self.ledger)

    def test_plan_input_and_question_card(self):
        pi = PlanInput(outer_steps=[{"text": "Do", "state": "todo", "anchor": "work"}], outer_explicit_states=False)
        self.assertEqual(len(pi.outer_steps or []), 1)
        self.assertEqual(auto_review_max_rounds({"auto_review": {"max_rounds": 4}}), 4)

        card = QuestionCard.from_inputs(["Keep", "Ship (Recommended)"], why={1: "ready"})
        self.assertEqual(card.options, ("Keep", "Ship"))
        self.assertEqual(card.to_fields(), {
            "options": ["Keep", "Ship"],
            "option_notes": ["", "ready"],
            "recommended": True,
            "recommended_index": 1,
        })
        with self.assertRaises(Refused):
            QuestionCard.from_inputs([], recommend=True)


class ProjectRegistryAndConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "demo"
        self.repo.mkdir()
        self.repo_s = str(self.repo.resolve())
        self.clock = FakeClock("2026-11-23 10:00:00")
        self.hc = FakeHc({
            "t10": {
                "address": "t10",
                "state": "live",
                "labels": {"pm": "demo"},
                "cwd": self.repo_s,
                "status": {"state": "idle"},
            }
        })
        self.tui = FakeTui(agents=[
            {"name": "pm-demo", "pane_id": "w2:p1", "workspace_id": "w2"},
            {"name": "pm-demo", "pane_id": "w1:p1", "workspace_id": "w1"},
        ])
        self.git = StubGit(roots={str(self.repo): self.repo_s, self.repo_s: self.repo_s})
        self.ctx = make_ctx(self.base, workspace="w1", hc=self.hc, tui=self.tui, git=self.git, clock=self.clock)
        self.ctx.store.change_registration("demo", lambda _cur: {
            "name": "pm-demo",
            "project": "demo",
            "repo": self.repo_s,
            "runtime": "hc",
            "terminal": "t10",
            "pane": "hc:t10",
            "previous": {"pane": "hc:t9"},
        })

    def test_project_coordinator_and_registry_with_injected_seat_alive(self):
        reg = ProjectRegistry(self.ctx, seat_alive=lambda repo, rec, term=None: True)
        proj = reg.get("demo")
        assert proj is not None
        self.assertIsInstance(proj, Project)
        self.assertIsInstance(proj.coordinator, Coordinator)
        self.assertEqual(proj.name, "demo")
        self.assertTrue(proj.coordinator.is_app_pm)
        self.assertEqual(proj.coordinator.panes, {"hc:t10", "hc:t9"})

        live = reg.hc_pm(self.repo_s)
        assert live is not None
        self.assertEqual(live["pane_id"], "hc:t10")
        self.assertEqual(live["agent_status"], "idle")

        # Dead seat suppresses hc_pm and lets find_pm fall back to TUI agent in current workspace
        dead_reg = ProjectRegistry(self.ctx, seat_alive=lambda repo, rec, term=None: False)
        self.assertIsNone(dead_reg.hc_pm(self.repo_s))
        tui_pm = dead_reg.find_pm(repo=self.repo_s)
        assert tui_pm is not None
        self.assertEqual(tui_pm["pane_id"], "w1:p1")

        self.assertEqual(reg.registered_repo("demo"), self.repo_s)
        self.assertEqual(reg.resolve_project_slug("pm-demo"), "demo")
        self.assertEqual(reg.status_scope([], self.repo_s), self.repo_s)

    def test_conversation_record_offset_tail_and_turn_cause(self):
        conv = Conversation(self.ctx, self.repo)
        conv.record("user", text="hello")
        self.clock.advance(5)
        conv.record("user", text="and more")
        self.clock.advance(5)
        conv.record("pm", text="delivered reply", after="deliver")
        conv.record("pm", text="real answer")

        end, rows = conv.events_after(0)
        self.assertEqual(len(rows), 4)
        self.assertGreater(end, 0)
        self.assertEqual(conv.events_after(end), (end, []))
        self.assertEqual(conv.tail(), [{"user": "hello\nand more", "pm": "real answer"}])

        conv.files.ensure()
        conv.files.turn_cause.write_text(json.dumps({"after": "deliver", "batch": [0, end], "extra": 1}))
        self.assertEqual(conv.turn_cause(), {"after": "deliver", "batch": [0, end]})

    def test_hc_pm_preserves_cwd_when_terminal_info_raw_is_empty(self):
        class _EmptyRawHc:
            def get(self, _term):
                return TerminalInfo(
                    address="t10",
                    state="live",
                    agent_state="idle",
                    labels={"pm": "demo"},
                    cwd="/explicit/cwd",
                    raw={},
                )

        self.ctx.hc = _EmptyRawHc()
        reg = ProjectRegistry(self.ctx, seat_alive=lambda repo, rec, term=None: True)
        live = reg.hc_pm(self.repo_s)
        assert live is not None
        self.assertEqual(live["cwd"], "/explicit/cwd")


class ReviewRegressionTests(unittest.TestCase):
    def test_task_instance_accepted_by_family_and_plan_helpers(self):
        parent = Task({
            "id": "epic",
            "status": "in_progress",
            "plan": [
                {"text": "Work", "state": "done", "anchor": "work"},
                {"text": "Review", "state": "todo", "anchor": "review"},
            ],
        })
        c1 = Task({"id": "c1", "status": "merged", "parent": "epic"})
        c2 = Task({"id": "c2", "status": "done", "parent": "epic"})

        self.assertTrue(has_pending_review_step(parent))
        self.assertTrue(has_unfinished_plan(parent))
        self.assertFalse(has_unfinished_plan(c1))

        fam = Family(parent, [c1, c2])
        self.assertEqual(fam.counts, {"merged": 1, "done": 1})
        res = fam.rollup(ACTIVE, CLOSED)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.action, "notify")
        self.assertEqual(res.reason, "parent_has_work")

        fam2 = Family.from_tasks(parent, [parent, c1, c2])
        self.assertEqual([c["id"] for c in fam2.children], ["c1", "c2"])

    def test_from_env_forwards_after_save_seat_alive_and_caller_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook = lambda: None
            seat_fn = lambda r, rec, t=None: False
            cp_fn = lambda idx: iter(["demo"])
            ctx = Context.from_env(
                tmp,
                env={"PM_HOME": tmp},
                after_save=(hook,),
                seat_alive=seat_fn,
                caller_projects=cp_fn,
            )
            self.assertEqual(ctx.after_save, (hook,))
            self.assertIs(ctx.seat_alive, seat_fn)
            self.assertIs(ctx.caller_projects, cp_fn)
            self.assertFalse(hasattr(ctx, "_legacy"))

    def test_import_only_pmlib_ledger_writes_board_on_save_and_mutate_task(self):
        script = textwrap.dedent("""
            import sys
            from pathlib import Path
            sys.path.insert(0, sys.argv[1])
            from pmlib.ledger import ledger
            home = Path(sys.argv[2])
            ledger.save({"id": "t-1", "title": "One", "project": "p", "repo": str(home), "status": "proposed", "log": []})
            board = home / "BOARD.md"
            assert board.is_file(), "BOARD.md missing after save"
            assert "t-1" in board.read_text(encoding="utf-8")
            board.unlink()
            ledger.mutate_task("t-1", lambda cur: {**cur, "status": "in_progress"})
            assert board.is_file(), "BOARD.md missing after mutate_task"
            assert "in_progress" in board.read_text(encoding="utf-8")
            print("ok")
        """)
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "HC_TERMINAL_ID", "HERDR_WORKSPACE_ID")}
            env.update(PM_HOME=tmp, PM_NO_DISCORD="1", PYTHONDONTWRITEBYTECODE="1")
            out = subprocess.run([sys.executable, "-c", script, str(SCRIPTS), tmp], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertEqual(out.stdout.strip(), "ok")

    def test_context_scoped_ledger_registry_and_conversation_are_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            ctx_a = make_ctx(Path(td) / "a")
            ctx_b = make_ctx(Path(td) / "b")
            repo = Path(td) / "repo"
            repo.mkdir()
            Ledger(ctx_a).save({"id": "x-1", "title": "In A", "project": "repo", "repo": str(repo), "status": "proposed"})
            Conversation(ctx_a, repo).record("user", text="hi")
            self.assertEqual([t.id for t in Ledger(ctx_a).all_tasks()], ["x-1"])
            self.assertEqual(Ledger(ctx_b).all_tasks(), [])
            self.assertEqual(len(Conversation(ctx_a, repo).events()), 1)
            self.assertEqual(Conversation(ctx_b, repo).events(), [])


if __name__ == "__main__":
    unittest.main()
