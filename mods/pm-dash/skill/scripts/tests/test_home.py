"""pmlib.home.Home and ProjectFiles: the ledger home's layout, paths only. No temporary folder and no patching
needed for path assertions: Home and ProjectFiles are built from literal paths and touch nothing on disk."""
import os
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# pmlib works out the ledger home when it is first imported. Name one that does not exist, so that import never looks
# at a real ledger; a test file that imported pmlib earlier keeps its own.
if "pmlib.context" not in sys.modules:
    _saved = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = "/nonexistent/pm-home-for-test_home"
    try:
        from pmlib import context, home  # noqa: E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved
else:
    from pmlib import context, home  # noqa: E402

ROOT = Path("/nonexistent/ledger")


class HomeTest(unittest.TestCase):
    def test_the_usual_layout_under_root(self):
        h = home.Home(ROOT)
        self.assertEqual(h.root, ROOT)
        self.assertEqual(h.tasks, ROOT / "tasks")
        self.assertEqual(h.registrations, ROOT / "pms")
        self.assertEqual(h.projects, ROOT / "projects")
        self.assertEqual(h.inbox, ROOT / "inbox")
        self.assertEqual(h.board, ROOT / "BOARD.md")
        self.assertEqual(h.config, ROOT / "config.json")
        self.assertEqual(h.memory, ROOT / "memory")
        self.assertEqual(h.memory_history, ROOT / "memory" / ".history")
        self.assertEqual(h.sent_dir, ROOT / "sent")
        self.assertEqual(h.waits, ROOT / "waits")
        self.assertEqual(h.locks, ROOT / "locks")
        self.assertEqual(h.tmp, ROOT / "tmp")
        self.assertEqual(h.reads, ROOT / "reads")
        self.assertEqual(h.reattach, ROOT / "reattach")
        self.assertEqual(h.cache, ROOT / "cache")
        self.assertEqual(h.context_tokens_cache, ROOT / "cache" / "context-tokens.json")
        self.assertEqual(h.turn_log, ROOT / "turns.log")
        self.assertEqual(h.pm_settings, ROOT / "pm-settings.json")
        self.assertEqual(h.discord_config, ROOT / "discord.json")
        self.assertEqual(h.discord_log, ROOT / "discord.log")
        self.assertEqual(h.mcp, ROOT / "mcp")
        self.assertEqual(h.store_dirs(), (ROOT, ROOT / "pms", ROOT / "tasks", ROOT / "projects"))

    def test_one_file_or_folder_by_name(self):
        h = home.Home(ROOT)
        self.assertEqual(h.task("dudu-login-fix"), ROOT / "tasks" / "dudu-login-fix.json")
        self.assertEqual(h.registration("dudu"), ROOT / "pms" / "dudu.json")
        proj = h.project("dudu")
        self.assertIsInstance(proj, home.ProjectFiles)
        self.assertEqual(proj.root, ROOT / "projects" / "dudu")
        self.assertEqual(os.fspath(proj), str(ROOT / "projects" / "dudu"))
        self.assertEqual(proj / "custom.txt", ROOT / "projects" / "dudu" / "custom.txt")
        self.assertEqual(proj.conversation, ROOT / "projects" / "dudu" / "conversation.jsonl")
        self.assertEqual(proj.delivered, ROOT / "projects" / "dudu" / "delivered.json")
        self.assertEqual(proj.delivered_lock, ROOT / "projects" / "dudu" / "delivered.lock")
        self.assertEqual(proj.deliver_lock, ROOT / "projects" / "dudu" / "deliver.lock")
        self.assertEqual(proj.seat_state, ROOT / "projects" / "dudu" / "seat.json")
        self.assertEqual(proj.seat_lock, ROOT / "projects" / "dudu" / "seat.lock")
        self.assertEqual(proj.next_session, ROOT / "projects" / "dudu" / "next-session.json")
        self.assertEqual(proj.turn_cause, ROOT / "projects" / "dudu" / "turn-cause.json")
        self.assertEqual(proj.taken_in, ROOT / "projects" / "dudu" / "taken-in.json")
        self.assertEqual(proj.task_seq, ROOT / "projects" / "dudu" / "task-seq.json")
        self.assertEqual(proj.handover, ROOT / "projects" / "dudu" / "handover.md")
        self.assertEqual(proj.verify, ROOT / "projects" / "dudu" / "verify")
        self.assertEqual(proj.pm_settings, ROOT / "projects" / "dudu" / "pm-settings.json")
        self.assertEqual(proj.decisions, ROOT / "projects" / "dudu" / "decisions.md")
        self.assertEqual(proj.library_state, ROOT / "projects" / "dudu" / "library.json")
        self.assertEqual(proj.research_sources, ROOT / "projects" / "dudu" / "research-sources.json")
        self.assertEqual(proj.docs, ROOT / "projects" / "dudu" / "docs")
        self.assertEqual(proj.docs_research, ROOT / "projects" / "dudu" / "docs" / "research")
        self.assertEqual(proj.research, ROOT / "projects" / "dudu" / "research")
        self.assertEqual(proj.attachments, ROOT / "projects" / "dudu" / "attachments")
        self.assertEqual(proj.memory, ROOT / "projects" / "dudu" / "memory")
        self.assertEqual(proj.memory_candidates, ROOT / "projects" / "dudu" / "memory" / "candidates")
        self.assertEqual(proj.memory_history, ROOT / "projects" / "dudu" / "memory" / ".history")
        self.assertEqual(proj.helpers, ROOT / "projects" / "dudu" / "helpers")
        self.assertEqual(proj.helper_dir("dudu-1"), ROOT / "projects" / "dudu" / "helpers" / "dudu-1")
        self.assertEqual(h.sent("dudu-1"), ROOT / "sent" / "dudu-1.md")
        self.assertEqual(h.sent_escalated("dudu-1"), ROOT / "sent" / "dudu-1.escalated.md")
        self.assertEqual(h.wait_file("dudu-1"), ROOT / "waits" / "dudu-1.json")
        self.assertEqual(h.lock("task-dudu-1"), ROOT / "locks" / "task-dudu-1.lock")
        self.assertEqual(h.reattach_lock("dudu-1"), ROOT / "reattach" / "dudu-1.lock")
        self.assertEqual(h.inbox_log("pm-dudu"), ROOT / "inbox" / "pm-dudu.log")
        self.assertEqual(h.inbox_offset("pm-dudu"), ROOT / "inbox" / "pm-dudu.offset")
        self.assertEqual(h.inbox_watch_lock("pm-dudu"), ROOT / "inbox" / "pm-dudu.watch.lock")
        self.assertEqual(h.inbox_watch_states("pm-dudu"), ROOT / "inbox" / "pm-dudu.watch-states.json")
        self.assertEqual(h.memory_dir(), ROOT / "memory")

    def test_folders_given_one_by_one_are_not_derived_from_root(self):
        # Tests point TASKS, PMS or PROJECTS somewhere of their own; each folder keeps what it was given.
        h = home.Home("/a", tasks="/b/tasks", registrations="/c/pms", projects="/d/projects", inbox="/e/inbox",
                      board="/f/BOARD.md")
        self.assertEqual(h.root, Path("/a"))
        self.assertEqual(h.task("x"), Path("/b/tasks/x.json"))
        self.assertEqual(h.registration("p"), Path("/c/pms/p.json"))
        self.assertEqual(h.project("p").root, Path("/d/projects/p"))
        self.assertEqual(h.inbox, Path("/e/inbox"))
        self.assertEqual(h.board, Path("/f/BOARD.md"))
        self.assertEqual(h.config, Path("/a/config.json"))  # config.json is always the root's
        self.assertEqual(h.store_dirs(), (Path("/a"), Path("/c/pms"), Path("/b/tasks"), Path("/d/projects")))

    def test_from_env_uses_home_option_else_env_without_touching_disk(self):
        h1 = home.Home.from_env("/nonexistent/explicit", env={"PM_HOME": "/nonexistent/ignored"})
        self.assertEqual(h1.root, Path("/nonexistent/explicit"))
        h2 = home.Home.from_env(None, env={"PM_HOME": "/nonexistent/from-env"})
        self.assertEqual(h2.root, Path("/nonexistent/from-env"))

    def test_paths_only(self):
        h = home.Home(ROOT)
        p = h.project("p")
        for path in (h.tasks, h.registrations, h.projects, h.inbox, h.board, h.config, h.task("t"),
                     h.registration("p"), p.root, p.conversation, p.memory, p.helpers, h.sent("t"), h.wait_file("t")):
            self.assertIsInstance(path, Path)
        self.assertFalse(ROOT.exists())  # asking made nothing

    def test_current_is_built_from_the_process_values(self):
        h = home.current()
        expected = home.Home.from_env()
        self.assertEqual((h.root, h.tasks, h.registrations, h.projects, h.inbox, h.board),
                         (expected.root, expected.tasks, expected.registrations, expected.projects,
                          expected.inbox, expected.board))
        self.assertIsNot(home.current(), h)


if __name__ == "__main__":
    unittest.main()
