"""Unit tests for `pm.py project tasks <slug>` (Projects.tasks readmodel & CLI)."""
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

if "pmlib.context" not in sys.modules:
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-project-tasks")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ.pop("PM_HOME", None)
            os.environ["PM_HOME"] = _saved_pm_home

from fakes import FakeClock, StubGit, make_ctx  # noqa: E402
from pmlib import cli  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.project.readmodel import NotFoundError, Projects  # noqa: E402


class ProjectTasksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "demo"
        self.repo.mkdir()
        self.repo_str = str(self.repo.resolve())
        self.clock = FakeClock("2026-11-24 10:00:00")
        self.git = StubGit(roots={str(self.repo): self.repo_str})
        self.ctx = make_ctx(self.base, pane="hc:t1", clock=self.clock, git=self.git)
        # Register project demo
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        (self.ctx.home.registrations / "pm-demo.json").write_text(
            json.dumps({
                "name": "pm-demo",
                "project": "demo",
                "repo": self.repo_str,
                "pane": "hc:t1",
                "runtime": "hc",
            }),
            encoding="utf-8",
        )
        self.ledger = Ledger(self.ctx)
        self.projects = Projects(self.ctx.store)

    def _add_task(self, tid: str, *, number: int | None = None, title: str = "", status: str = "merged",
                  branch: str = "", updated: str = "2026-11-20 10:00", parent: str = "",
                  review_of: str = "", commit: str = "", landed: dict | None = None,
                  retired: bool = False, log: list | None = None):
        doc = {
            "id": tid,
            "title": title or tid,
            "project": "demo",
            "repo": self.repo_str,
            "status": status,
            "branch": branch,
            "updated": updated,
            "parent": parent,
        }
        if number is not None:
            doc["number"] = number
        if review_of:
            doc["review_of"] = review_of
        if commit:
            doc["commit"] = commit
        if landed:
            doc["landed"] = landed
        if retired:
            doc["retired"] = True
        if log is not None:
            doc["log"] = log
        self.ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        (self.ctx.home.tasks / f"{tid}.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_pagination_order_and_boundary_offsets(self):
        for i in range(1, 8):
            self._add_task(
                f"demo-task-{i}",
                number=100 + i,
                title=f"Finished task {i}",
                status="merged" if i % 2 else "done",
                branch=f"dev/task-{i}",
                updated=f"2026-11-2{i} 12:00",
                commit=f"abc000{i}",
                landed={"commit": f"def000{i}", "at": f"2026-11-2{i} 12:00"},
                retired=True,
            )

        p1 = self.projects.tasks("demo", status="finished", offset=0, limit=3)
        self.assertEqual(p1["total"], 7)
        self.assertEqual(p1["offset"], 0)
        self.assertEqual(p1["limit"], 3)
        self.assertTrue(p1["more"])
        self.assertEqual([t["id"] for t in p1["tasks"]], ["demo-task-7", "demo-task-6", "demo-task-5"])
        first = p1["tasks"][0]
        self.assertEqual(first["number"], 107)
        self.assertEqual(first["branch"], "dev/task-7")
        self.assertEqual(first["commit"], "abc0007")
        self.assertEqual(first["landed"]["commit"], "def0007")
        self.assertTrue(first["retired"])

        p2 = self.projects.tasks("demo", status="finished", offset=3, limit=3)
        self.assertTrue(p2["more"])
        self.assertEqual([t["id"] for t in p2["tasks"]], ["demo-task-4", "demo-task-3", "demo-task-2"])

        p3 = self.projects.tasks("demo", status="finished", offset=6, limit=3)
        self.assertFalse(p3["more"])
        self.assertEqual([t["id"] for t in p3["tasks"]], ["demo-task-1"])

        # Boundary offset >= total returns empty page with more=False
        beyond = self.projects.tasks("demo", status="finished", offset=7, limit=3)
        self.assertEqual(beyond["tasks"], [])
        self.assertEqual(beyond["total"], 7)
        self.assertFalse(beyond["more"])

        far = self.projects.tasks("demo", status="finished", offset=999, limit=10)
        self.assertEqual(far["tasks"], [])
        self.assertFalse(far["more"])

    def test_skips_abandoned_review_and_question_only_tasks(self):
        self._add_task("demo-ok", number=10, title="Real finished work", status="merged", updated="2026-11-20 10:00")
        self._add_task("demo-open", number=11, title="Active work", status="in_progress", updated="2026-11-21 10:00")
        self._add_task("demo-abandoned", number=12, title="Dropped idea", status="abandoned", updated="2026-11-22 10:00")
        self._add_task("demo-ok-review", number=13, title="Review of #10", status="done", review_of="demo-ok", updated="2026-11-22 11:00")
        # Pure question recorded in conversation.jsonl (blocked -> done, never in_progress/review)
        self._add_task("demo-q-conv", number=14, title="Quick question", status="done", updated="2026-11-22 12:00")
        conv_path = self.ctx.home.project_for(self.repo_str).conversation
        conv_path.parent.mkdir(parents=True, exist_ok=True)
        conv_path.write_text(
            "\n".join([
                json.dumps({"type": "thread", "task": "demo-q-conv", "status": "blocked", "title": "Quick question", "at": "2026-11-22 11:50"}),
                json.dumps({"type": "thread", "task": "demo-q-conv", "status": "done", "title": "Quick question", "at": "2026-11-22 12:00"}),
            ]) + "\n",
            encoding="utf-8",
        )
        # Pure question only in task log (no branch/commit/worker, registered blocked, never worked)
        self._add_task(
            "demo-q-log",
            number=15,
            title="Log-only question",
            status="done",
            updated="2026-11-22 13:00",
            log=[
                {"at": "2026-11-22 12:50", "by": "pm", "text": "registered (blocked)"},
                {"at": "2026-11-22 13:00", "by": "pm", "text": "status=done"},
            ],
        )

        fin = self.projects.tasks("demo", status="finished")
        self.assertEqual([t["id"] for t in fin["tasks"]], ["demo-ok"])

        opn = self.projects.tasks("demo", status="open")
        self.assertEqual([t["id"] for t in opn["tasks"]], ["demo-open"])

        both = self.projects.tasks("demo", status="all")
        self.assertEqual([t["id"] for t in both["tasks"]], ["demo-open", "demo-ok"])

    def test_search_by_number_title_id_and_branch_case_insensitive(self):
        self._add_task("dudu-alpha", number=218, title="Fix Search Pagination", status="merged",
                       branch="dev/threads-search", updated="2026-11-20 10:00")
        self._add_task("dudu-beta", number=198, title="Memory Dream Pipeline", status="done",
                       branch="dev/memory-dream", updated="2026-11-21 10:00")
        self._add_task("dudu-gamma", number=301, title="Board Wire Polish", status="in_progress",
                       branch="feat/WIRE-curve", updated="2026-11-22 10:00")

        # Exact #number match
        r_hash = self.projects.tasks("demo", status="all", query="#218")
        self.assertEqual([t["id"] for t in r_hash["tasks"]], ["dudu-alpha"])

        # Bare number match
        r_num = self.projects.tasks("demo", status="all", query="198")
        self.assertEqual([t["id"] for t in r_num["tasks"]], ["dudu-beta"])

        # Title case-insensitive + multi-token
        r_title = self.projects.tasks("demo", status="all", query="search pagination")
        self.assertEqual([t["id"] for t in r_title["tasks"]], ["dudu-alpha"])

        # Branch case-insensitive
        r_branch = self.projects.tasks("demo", status="all", query="wire-curve")
        self.assertEqual([t["id"] for t in r_branch["tasks"]], ["dudu-gamma"])

        # Task id match
        r_id = self.projects.tasks("demo", status="all", query="dudu-beta")
        self.assertEqual([t["id"] for t in r_id["tasks"]], ["dudu-beta"])

    def test_validation_and_cli_invocation(self):
        self._add_task("demo-cli-1", number=42, title="CLI Task", status="merged",
                       branch="dev/cli-42", updated="2026-11-23 09:00", parent="demo-epic")

        with self.assertRaises(NotFoundError):
            self.projects.tasks("no-such-project")
        with self.assertRaises(ValueError):
            self.projects.tasks("demo", offset=-1)
        with self.assertRaises(ValueError):
            self.projects.tasks("demo", limit=0)
        with self.assertRaises(ValueError):
            self.projects.tasks("demo", limit=101)
        with self.assertRaises(ValueError):
            self.projects.tasks("demo", status="invalid")

        cli.main(["project", "tasks", "demo", "--status", "all", "--q", "#42", "--offset", "0", "--limit", "10"], ctx=self.ctx)
        payload = json.loads(self.ctx.out.stdout.strip())
        self.assertEqual(payload["total"], 1)
        self.assertFalse(payload["more"])
        self.assertEqual(payload["tasks"][0]["id"], "demo-cli-1")
        self.assertEqual(payload["tasks"][0]["number"], 42)
        self.assertEqual(payload["tasks"][0]["parent"], "demo-epic")


if __name__ == "__main__":
    unittest.main()
