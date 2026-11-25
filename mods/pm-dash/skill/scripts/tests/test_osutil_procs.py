"""The command lines pm.py writes for people and agents, and the processes it starts and stops, on Windows (by
osutil.WINDOWS) and on macOS and Linux, where they stay exactly as they were. Moved from test_pm.py's
WindowsCommandLines (Stage 6a): each test builds its own Context with make_ctx and a real `Processes` port; the only
patches left are the platform itself (osutil.WINDOWS, sys.executable, shutil.which) and subprocess, which no port
stands in front of."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path, PureWindowsPath
import shlex
import subprocess
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

from fakes import make_ctx  # noqa: E402
from pmlib import osutil  # noqa: E402
from pmlib.home import Home  # noqa: E402
from pmlib.manager import rotate  # noqa: E402
from pmlib.manager.service import ManagerSessions  # noqa: E402
from pmlib.procs import Processes  # noqa: E402
from pmlib.review import land  # noqa: E402

SPACED = "/Users/Jo Doe/.claude/skills/pm/scripts/pm.py"  # a user name with a space, as on many Windows machines
LAUNCHER = SCRIPTS / "pm.py"


@contextlib.contextmanager
def as_windows(py=True, exe=r"C:\Program Files\Python312\python.exe"):
    """osutil as it behaves on Windows: WINDOWS, the py launcher (or none, and Python at exe)."""
    which = osutil.shutil.which
    with mock.patch.object(osutil, "WINDOWS", True), mock.patch.object(osutil.sys, "executable", exe), \
            mock.patch.object(osutil.shutil, "which", lambda name, *a, **kw: (r"C:\Windows\py.exe" if py else None)
                              if name == "py" else which(name, *a, **kw)):
        yield


class WindowsCommandLines(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="pm-osutil-procs-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def ctx_with_procs(self, *, root=None, env=None, launcher_path=SPACED):
        """A Context whose procs is the real Processes port (the one Context.from_env builds), the launcher at
        launcher_path and the ledger home at root."""
        ctx = make_ctx(self.tmp)
        home = Home(Path(root)) if root is not None else ctx.home
        env = {"PM_HOME": str(home.root)} if env is None else env
        ctx.procs = Processes(home, env=env, launcher_path=Path(launcher_path) if launcher_path else None)
        return ctx

    def test_windows_quotes_like_list2cmdline_and_never_with_single_quotes(self):
        with as_windows():
            self.assertEqual(osutil.shell_quote(PureWindowsPath(r"C:\Users\Jo Doe\.dudu\sent\x.md")),
                             '"C:/Users/Jo Doe/.dudu/sent/x.md"')            # forward slashes, as setup.py writes
            self.assertEqual(osutil.shell_quote(PureWindowsPath(r"C:\tools\pm.py")), "C:/tools/pm.py")
            for arg in ("plain", "a b", 'say "hi" now', "C:\\dir with space\\", 'a\\"b c', ""):
                self.assertEqual(osutil.shell_quote(arg), subprocess.list2cmdline([arg]))
            self.assertEqual(osutil.shell_quote("R&D"), '"R&D"')                  # cmd's metacharacters too
            line = osutil.shell_join(["hc", "send", "t5", "[from hc:t7] 看一下 C:/Users/Jo Doe"])
            self.assertEqual(line, 'hc send t5 "[from hc:t7] 看一下 C:/Users/Jo Doe"')
            self.assertNotIn("'", line)

    def test_powershell_lines_escape_with_backticks_and_call_a_quoted_program_with_ampersand(self):
        with as_windows():
            self.assertEqual(osutil.shell_join(["C:/Program Files/codex/codex.exe", "-c", 'model_provider="x"', "-m",
                                                "gpt"], powershell=True),
                             '& "C:/Program Files/codex/codex.exe" -c "model_provider=`"x`"" -m gpt')
            self.assertEqual(osutil.shell_join(["codex", "-c", "a=$b"], powershell=True), 'codex -c "a=`$b"')

    def test_pm_command_and_handover_line_on_windows(self):
        spaced_resolved = PureWindowsPath(Path(SPACED).resolve()).as_posix() if os.name == "nt" else SPACED
        with as_windows():
            ctx = self.ctx_with_procs(root="/Users/Jo Doe/ledger")
            cmd = ctx.procs.pm_command()
            self.assertEqual(cmd, f'py -3 "{spaced_resolved}" --home "/Users/Jo Doe/ledger"')
            no_home = self.ctx_with_procs(root="/Users/Jo Doe/ledger", env={})   # PM_HOME not set
            self.assertEqual(no_home.procs.pm_command(), f'py -3 "{spaced_resolved}"')
            self.assertNotIn("'", cmd)
            self.assertNotIn("PM_HOME=", cmd)                                 # cmd and PowerShell cannot read it
            self.assertEqual(osutil.file_text(PureWindowsPath(r"C:\Users\Jo Doe\.dudu\sent\t.md")),
                             '"$(cat "C:/Users/Jo Doe/.dudu/sent/t.md")"')
        with as_windows(py=False):                                            # no py launcher: the interpreter
            ctx = self.ctx_with_procs()
            self.assertEqual(ctx.procs.pm_script(), f'"C:/Program Files/Python312/python.exe" "{spaced_resolved}"')

    def test_home_option_sets_the_ledger_home(self):
        home = self.tmp / "a ledger"
        (self.tmp / "user").mkdir()
        (self.tmp / "repo").mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ("PM_HOME", "HERDR_PANE_ID", "HC_TERMINAL_ID")}
        env["HOME"] = str(self.tmp / "user")
        out = subprocess.run([sys.executable, str(LAUNCHER), "--home", str(home), "new", "home option",
                              "--repo", str(self.tmp / "repo"), "--slug", "x"], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(list((home / "tasks").glob("*.json"))), 1)

    @unittest.skipIf(osutil.WINDOWS, "tests native POSIX osutil.WINDOWS=False lines")
    def test_posix_lines_are_unchanged(self):
        script = str(LAUNCHER.resolve())
        self.assertFalse(osutil.WINDOWS)
        ctx = self.ctx_with_procs(launcher_path=None)                      # the real launcher, scripts/pm.py
        self.assertEqual(ctx.procs.launcher(), LAUNCHER.resolve())
        self.assertEqual(ctx.procs.pm_command(),
                         f"PM_HOME={shlex.quote(str(ctx.home.root))} python3 {shlex.quote(script)}")
        no_home = self.ctx_with_procs(env={}, launcher_path=None)
        self.assertEqual(no_home.procs.pm_command(), f"python3 {shlex.quote(script)}")
        self.assertEqual(ctx.procs.pm_script() + " handover", f"python3 {script} handover")
        sent = Path("/tmp/ledger/sent/x.md")
        self.assertEqual(osutil.file_text(sent), '"$(cat /tmp/ledger/sent/x.md)"')
        for args in (["claude", "--", "[from pm.py start] 你是 PM"], ["codex", "-c", 'model_provider="x"']):
            self.assertEqual(osutil.shell_join(args), shlex.join(args))
            self.assertEqual(osutil.shell_join(args, powershell=True), shlex.join(args))
        self.assertEqual(osutil.shell_quote("a b"), "'a b'")
        self.assertEqual(osutil.own_group(), {"start_new_session": True})
        self.assertEqual(osutil.own_group(background=True), {"start_new_session": True})

    def test_windows_stops_a_check_with_taskkill_not_killpg(self):
        class Proc:
            pid, waited, killed, alive = 4242, False, False, True
            def poll(self): return None if self.alive else 0
            def wait(self): self.waited = True
            def kill(self): self.killed = True
        proc, ran = Proc(), []
        def run(argv, **kw):
            ran.append(argv)
            proc.alive = False
        with as_windows(), mock.patch.object(osutil.subprocess, "run", run), \
                mock.patch.object(osutil.os, "killpg", side_effect=AssertionError("killpg on Windows"), create=True):
            osutil.stop_group(proc)
        self.assertEqual(ran, [["taskkill", "/T", "/F", "/PID", "4242"]])
        self.assertEqual((proc.killed, proc.waited), (False, True))
        proc, ran = Proc(), []                                     # taskkill missing: the shell itself is killed
        def missing(argv, **kw):
            raise FileNotFoundError(argv[0])
        with as_windows(), mock.patch.object(osutil.subprocess, "run", missing):
            osutil.stop_group(proc)
        self.assertEqual((proc.killed, proc.waited), (True, True))

    def test_windows_starts_checks_and_background_work_in_new_process_groups(self):
        class Proc:
            pid, returncode = 7, 0
            def communicate(self, timeout=None): return "ok", None
        ctx = self.ctx_with_procs()
        repo = self.tmp / "repo"
        repo.mkdir()
        with as_windows(), mock.patch.object(subprocess, "Popen", return_value=Proc()) as popen:
            self.assertIsNone(land.run_checks(str(repo), ["true"], 60, [], env=ctx.env, tr=ctx.config.tr))
            check = popen.call_args[1]
            rotate.name_later("hc:t7", "pm-x", ctx=ctx)
            named = popen.call_args
            ManagerSessions(ctx)._end_session_later("/w/proj", "t7", agent_pid=123, kill_terminal=False)
            ended = popen.call_args
        self.assertEqual(popen.call_count, 3)
        spaced_resolved = str(Path(SPACED).resolve()) if os.name == "nt" else SPACED
        self.assertEqual(named[0][0][1:], [spaced_resolved, "name-agent", "hc:t7", "pm-x"])
        self.assertEqual(ended[0][0][1:], [spaced_resolved, "end-session", "t7", "--repo", "/w/proj", "--agent-pid", "123"])
        named, ended = named[1], ended[1]
        self.assertNotIn("start_new_session", {**check, **named, **ended})
        self.assertEqual(check["creationflags"], 0x200)                         # CREATE_NEW_PROCESS_GROUP
        self.assertEqual(named["creationflags"], 0x200 | 0x08000000)            # and CREATE_NO_WINDOW
        self.assertEqual(ended["creationflags"], 0x200 | 0x08000000)

    def test_options_inheritance_required_and_unknown_rejection(self):
        class BaseOpt(osutil.Options):
            required = ("id",)
            id: str = ""
            keep: bool = False

        class ChildOpt(BaseOpt):
            note: str | None = None

        with self.assertRaisesRegex(TypeError, "ChildOpt needs id"):
            ChildOpt()
        with self.assertRaisesRegex(TypeError, "ChildOpt has no option bogus"):
            ChildOpt(id="t-1", bogus=1)
        opt = ChildOpt(id="t-1", note="ok")
        self.assertEqual((opt.id, opt.keep, opt.note), ("t-1", False, "ok"))
        self.assertIn("ChildOpt(id='t-1', keep=False, note='ok')", repr(opt))

    def test_background_work_recognizes_agy_background_tasks_and_ignores_mcp(self):
        """Reproduction for Finding P2 (7c live gap): `procs.background_work` only matches Claude's
        `shell-snapshots/snapshot-`, missing `agy` background tasks (both `zsh -c` compound commands and
        tail-exec'd `Python` direct children in their own pgid) while needing to ignore MCP sidecars."""
        ctx = self.ctx_with_procs()
        ps_table = "\n".join([
            # Terminal 1 (pid=90377): agy worker with an active tail-exec'd Python check AND an MCP server child
            "90377   968 90377 agy --dangerously-skip-permissions --model gemini-4-carbon-high",
            "14500 90377 14500 /opt/homebrew/bin/python3 tests/run_checks.py",
            "14501 90377 90377 node /Users/me/.npm/playwright-mcp --browser chromium",
            # Terminal 2 (pid=90400): agy worker with a compound `zsh -c` background task
            "90400   968 90400 agy --dangerously-skip-permissions --model gemini-4-neon-high",
            "14600 90400 14600 zsh -c cargo test && echo done",
            # Terminal 3 (pid=90500): idle agy worker with ONLY MCP / watchdog sidecars
            "90500   968 90500 agy --dangerously-skip-permissions --model gemini-4-carbon-high",
            "14700 90500 90500 npm exec chrome-devtools-mcp@1.11.0 --isolated",
            "14701 14700 14701 node /Users/me/chrome-devtools-mcp/telemetry/watchdog/main.js --parent-pid=14700",
        ]) + "\n"

        def fake_ps(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, stdout=ps_table, stderr="")

        with mock.patch.object(osutil, "WINDOWS", False), mock.patch("pmlib.procs.subprocess.run", side_effect=fake_ps):
            w1 = ctx.procs.background_work({
                "pid": 90377,
                "argv": ["agy", "--dangerously-skip-permissions"],
                "status": {"app": "antigravity", "state": "done"},
            })
            w2 = ctx.procs.background_work({
                "pid": 90400,
                "argv": ["agy", "--dangerously-skip-permissions"],
                "status": {"app": "antigravity", "state": "done"},
            })
            w3 = ctx.procs.background_work({
                "pid": 90500,
                "argv": ["agy", "--dangerously-skip-permissions"],
                "status": {"app": "antigravity", "state": "done"},
            })
        self.assertEqual(len(w1), 1, w1)
        self.assertIn("run_checks.py", w1[0])
        self.assertEqual(len(w2), 1, w2)
        self.assertIn("cargo test", w2[0])
        self.assertEqual(w3, [])

        # Windows PowerShell CIM JSON branch (both multi-row list and single-row dict from ConvertTo-Json)
        cim_rows = [
            {"ProcessId": 90377, "ParentProcessId": 968, "CommandLine": "agy.exe --dangerously-skip-permissions"},
            {"ProcessId": 14500, "ParentProcessId": 90377, "CommandLine": '"C:\\Python312\\python.exe" tests/run_checks.py'},
            {"ProcessId": 14501, "ParentProcessId": 90377, "CommandLine": "node.exe C:\\mcp\\playwright-mcp\\cli.js"},
            {"ProcessId": 14502, "ParentProcessId": 90377, "CommandLine": 'py -3 "C:/skills/pm/scripts/pm.py" wait demo-a'},
            {"ProcessId": 90400, "ParentProcessId": 968, "CommandLine": "agy.exe --dangerously-skip-permissions"},
            {"ProcessId": 14600, "ParentProcessId": 90400, "CommandLine": 'powershell.exe -Command "cargo test"'},
        ]
        with mock.patch.object(osutil, "WINDOWS", True), mock.patch(
            "pmlib.procs.subprocess.run",
            side_effect=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=json.dumps(cim_rows), stderr=""),
        ):
            win_w1 = ctx.procs.background_work({"pid": 90377, "status": {"app": "antigravity", "state": "done"}})
            win_w2 = ctx.procs.background_work({"pid": 90400, "status": {"app": "antigravity", "state": "done"}})
        self.assertEqual(len(win_w1), 1, win_w1)
        self.assertIn("run_checks.py", win_w1[0])
        self.assertEqual(win_w2, ["cargo test"])

        # Single-process PowerShell ConvertTo-Json returns a bare JSON object `{...}`, not `[...]`
        single_cim = {"ProcessId": 90377, "ParentProcessId": 968, "CommandLine": "agy.exe"}
        with mock.patch.object(osutil, "WINDOWS", True), mock.patch(
            "pmlib.procs.subprocess.run",
            side_effect=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=json.dumps(single_cim), stderr=""),
        ):
            self.assertEqual(ctx.procs.background_work({"pid": 90377, "status": {"app": "antigravity"}}), [])

    def test_context_from_env_in_fresh_python_wires_caller_and_watchers(self):
        """Reproduction for Finding P6: `procs.build_context` relies on `sys.modules.get(...)`, so calling
        `Context.from_env()` without importing `pmlib.cli` first leaves `caller` None and `deliver_watchers` empty."""
        code = (
            "import json, sys; "
            f"sys.path.insert(0, {str(SCRIPTS)!r}); "
            "from pmlib.context import Context; "
            "ctx = Context.from_env(); "
            "print(json.dumps({'has_caller': ctx.caller is not None, "
            "'watchers': [w.name for w in ctx.deliver_watchers], "
            "'after_save': len(ctx.after_save), "
            "'has_seat_alive': ctx.seat_alive is not None}))"
        )
        env = {**os.environ, "PM_HOME": str(self.tmp / "fresh-home")}
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
        payload = __import__("json").loads(proc.stdout)
        self.assertTrue(payload["has_caller"], payload)
        self.assertIn("helpers", payload["watchers"], payload)
        self.assertIn("dependencies", payload["watchers"], payload)
        self.assertIn("dream", payload["watchers"], payload)
        self.assertTrue(payload["has_seat_alive"], payload)


if __name__ == "__main__":
    unittest.main()
