"""`cmd_update(..., ctx=ctx)` executes through `Updates(ctx)` and runs reactions against `ctx`."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
for p in (SCRIPTS, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fakes import make_ctx  # noqa: E402
from pmlib.commands import ledger as ledger_cmd  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402


class CommandPatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = (self.base / "repo").resolve()
        self.repo.mkdir(parents=True)

    def test_cmd_update_runs_on_explicit_context(self):
        wt = (self.base / "wt").resolve()
        ev_readme = wt / "evidence" / "topic-a" / "README.md"
        ev_readme.parent.mkdir(parents=True)
        ev_readme.write_text("# Topic A Research\n\nFindings.\n", encoding="utf-8")

        after_calls = []
        ctx = make_ctx(self.base / "home")
        ctx.after_save = (lambda: after_calls.append("saved"),)
        ctx.store.change_task("t-patch", lambda _: {
            "id": "t-patch",
            "title": "context update test",
            "project": "repo",
            "repo": str(self.repo),
            "worktree": str(wt),
            "status": "review",
            "pane": "hc:t2",
            "updated": "2026-11-22 20:00",
            "log": [],
        })
        ledger_cmd.cmd_update(
            argparse.Namespace(id="t-patch", status="merged", note="landed", keep=True),
            ctx=ctx,
        )
        updated = Ledger(ctx).load("t-patch").raw
        self.assertEqual(updated["status"], "merged")
        self.assertIn("t-patch: merged", ctx.out.stdout)
        self.assertIn("collected research: topic-a/README.md", ctx.out.stdout)
        self.assertTrue((ctx.home.project_for(self.repo).root / "research" / "topic-a" / "README.md").is_file())
        self.assertGreaterEqual(len(after_calls), 1)


if __name__ == "__main__":
    unittest.main()
