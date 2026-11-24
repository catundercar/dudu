"""`ctx.agents.claude_lean_settings()` reads from `ctx.claude_dir` rather than the machine's real `~/.claude`."""
import json
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
from pmlib.manager import launch  # noqa: E402


class ClaudeDirGuard(unittest.TestCase):
    def test_ctx_claude_dir_isolates_lean_settings(self):
        with tempfile.TemporaryDirectory(prefix="pm-claude-dir-") as tmp:
            ctx = make_ctx(Path(tmp))
            fake = ctx.claude_dir
            (fake / "skills" / "only-here").mkdir(parents=True)
            (fake / "skills" / "only-here" / "SKILL.md").write_text("x")
            (fake / "settings.json").write_text(json.dumps({"enabledPlugins": {"plug@here": True}}))

            got = ctx.agents.claude_lean_settings()
            self.assertEqual(got, {
                "enabledPlugins": {"plug@here": False},
                "skillOverrides": {"only-here": "user-invocable-only"},
            })
            self.assertIn("only-here", got["skillOverrides"])


if __name__ == "__main__":
    unittest.main()
