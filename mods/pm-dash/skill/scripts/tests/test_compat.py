"""Tests for the minimal static `pm` facade (`pmlib/compat.py`) and `procs.code_mark()`."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pmlib import cli, compat, context, home, osutil  # noqa: E402


TERMINAL_VARIABLES = {
    "HC_TERMINAL_ID", "HERDR_PANE_ID", "HERDR_WORKSPACE_ID", "HERDR_ENV", "HC_SESSION",
    "CLAUDE_CODE_SESSION_ID", "PM_HELPER_OF", "PM_HELPER_NAME", "PM_HELPER_PROJECT",
}


class MinimalCompatFacade(unittest.TestCase):
    """`compat.install(facade)` exposes only the small static public surface (section 4.4)."""

    def setUp(self):
        self.facade = types.ModuleType("pm_facade_test")
        compat.install(self.facade)

    def test_exposes_minimal_public_surface(self):
        self.assertIs(self.facade.main, cli.main)
        self.assertIs(self.facade.build_parser, cli.build_parser)
        self.assertIs(self.facade.Context, context.Context)
        self.assertIs(self.facade.Home, home.Home)
        self.assertEqual(self.facade.WINDOWS, osutil.WINDOWS)
        self.assertTrue(callable(self.facade.python_command))

    def test_no_setattr_fanout_or_private_symbols(self):
        self.assertIs(type(self.facade), types.ModuleType)
        self.assertFalse(hasattr(self.facade, "install"))
        self.assertFalse(hasattr(self.facade, "legacy_context"))
        self.assertFalse(hasattr(self.facade, "STATE"))
        self.assertFalse(hasattr(self.facade, "STORE"))

    def test_windows_patch_drives_python_command_without_fanout(self):
        with mock.patch.object(self.facade, "WINDOWS", True), \
                mock.patch.object(shutil, "which", lambda name: r"C:\Windows\py.exe" if name == "py" else None):
            self.assertEqual(self.facade.python_command(), "py -3")
        with mock.patch.object(self.facade, "WINDOWS", False):
            self.assertEqual(self.facade.python_command(), "python3")

    def test_import_pm_exposes_facade_and_sibling_reexports(self):
        with tempfile.TemporaryDirectory() as home_dir:
            code = (
                "import sys; sys.path.insert(0, sys.argv[1]);"
                "import pm, pm_store, pm_project, pm_sessions, pm_events;"
                "import pmlib.cli as cli, pmlib.context as ctx, pmlib.home as h, pmlib.osutil as ou;"
                "import pmlib.store as st, pmlib.project.readmodel as rm;"
                "import pmlib.agents.transcripts as tr, pmlib.terminals.events as ev;"
                "assert pm.main is cli.main and pm.build_parser is cli.build_parser;"
                "assert pm.Context is ctx.Context and pm.Home is h.Home;"
                "assert pm.WINDOWS == ou.WINDOWS and callable(pm.python_command);"
                "assert pm_store.FileStore is st.FileStore and pm_store.DamagedFileError is st.DamagedFileError;"
                "assert pm_project.Projects is rm.Projects;"
                "assert pm_sessions.default_sessions is tr.default_sessions;"
                "assert pm_events.ChangeWaiter is ev.ChangeWaiter and pm_events.TimedLooks is ev.TimedLooks;"
                "assert not hasattr(pm, 'install') and not hasattr(pm, 'legacy_context');"
                "assert not hasattr(ctx, 'STATE') and not hasattr(pm_store, 'STORE')"
            )
            env = {k: v for k, v in os.environ.items() if k not in TERMINAL_VARIABLES}
            env["PM_HOME"] = home_dir
            out = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)


class CodeMark(unittest.TestCase):
    """procs.code_mark() on a copy of the scripts folder: it changes when any code file is touched, added or removed,
    and is None only while the launcher pm.py itself is missing."""

    def test_a_touched_added_or_removed_module_changes_the_mark_and_missing_launcher_is_none(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / "scripts"
            shutil.copytree(SCRIPTS, copy, ignore=shutil.ignore_patterns("tests", "test_*.py", "__pycache__"))
            code = textwrap.dedent("""
                import os, sys, time
                from pathlib import Path
                sys.path.insert(0, sys.argv[1])
                from pmlib import procs
                scripts = Path(sys.argv[1])
                assert procs.launcher() == (scripts / "pm.py").resolve(), procs.launcher()
                names = {p.relative_to(scripts.resolve()).as_posix() for p in procs.code_files()}
                assert {"pm.py", "pm_events.py", "pm_store.py", "pmlib/cli.py", "pmlib/procs.py"} <= names, names
                first = procs.code_mark()
                assert first is not None and first == procs.code_mark()
                later = time.time() + 5
                os.utime(scripts / "pmlib" / "compat.py", (later, later))
                touched = procs.code_mark()
                assert touched is not None and touched != first
                (scripts / "pmlib" / "x.py").write_text("X = 1\\n")
                added = procs.code_mark()
                assert added is not None and added != touched
                (scripts / "pmlib" / "compat.py").rename(scripts / "pmlib" / "compat.bak")
                removed = procs.code_mark()
                assert removed is not None and removed != added
                (scripts / "pm.py").rename(scripts / "pm.bak")
                assert procs.code_mark() is None
            """)
            out = subprocess.run([sys.executable, "-c", code, str(copy)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
