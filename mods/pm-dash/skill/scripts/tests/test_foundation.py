"""Unit tests for Stage 1 foundation objects (`PmError`, `Context`, `Config`, `Clock`, `Output`, `Processes`,
sibling module re-exports, `legacy_context()`, and `tests/fakes.py`)."""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import re
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

if "pmlib.context" not in sys.modules:
    _saved_home = os.environ.get("PM_HOME")
    _init_tmp = tempfile.mkdtemp(prefix="pm-foundation-init-")
    os.environ["PM_HOME"] = _init_tmp
    try:
        from pmlib import caller, cli, config, context, errors, home, osutil, procs, store  # noqa: E402
    finally:
        if _saved_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_home
else:
    from pmlib import caller, cli, config, context, errors, home, osutil, procs, store  # noqa: E402

from pmlib.project import readmodel as readmodel_mod  # noqa: E402
from fakes import FakeChangeWaiter, FakeClock, FakeHc, FakeProcs, FakeTui, StubGit, make_ctx  # noqa: E402


class ErrorsAndCliMappingTest(unittest.TestCase):
    def test_error_hierarchy_and_defaults(self):
        self.assertTrue(issubclass(errors.IdentityError, errors.PmError))
        self.assertTrue(issubclass(errors.StoreError, errors.PmError))
        self.assertTrue(issubclass(errors.VersionConflict, (errors.PmError, ValueError)))
        self.assertTrue(issubclass(errors.NotFound, (errors.PmError, LookupError)))
        self.assertTrue(issubclass(readmodel_mod.NotFoundError, (errors.NotFound, LookupError)))
        self.assertTrue(issubclass(store.LockTimeoutError, (errors.StoreError, TimeoutError)))
        self.assertTrue(issubclass(store.DamagedFileError, (errors.StoreError, ValueError)))
        self.assertTrue(issubclass(store.UnreadableFileError, (errors.StoreError, OSError)))

        vc = errors.VersionConflict("stale", "v2")
        self.assertEqual((vc.code, vc.current, str(vc)), (4, "v2", "stale"))
        u = store.UnreadableFileError(13, "denied", "/x")
        self.assertEqual((u.code, u.payload, u.stream), (1, None, "stderr"))

    def test_cli_main_maps_pm_errors_in_child(self):
        cases = [
            ("Refused('bad arg', code=2)", 2, "", "bad arg"),
            ("NotFound('no task demo-1')", 1, "", "no task demo-1"),
            ("WaitOutcome('timed out', code=2, stream='stdout')", 2, "timed out", ""),
            ("Refused('', code=4, payload={'error': 'conflict'}, stream='stdout')", 4, '{"error": "conflict"}', ""),
            ("IdentityError('wrong pane')", 2, "", "PM identity check failed: wrong pane"),
            ("StoreError('bad file')", 1, "", "ledger store error: bad file"),
        ]
        for expr, want_code, want_out, want_err in cases:
            code = (
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from pmlib import cli; "
                "from pmlib.errors import IdentityError, NotFound, Refused, StoreError, WaitOutcome; "
                f"cli.COMMANDS['status'] = (type('M', (), {{'boom': staticmethod(lambda _a, ctx=None: (_ for _ in ()).throw({expr}))}}), 'boom'); "
                "sys.argv = ['pm.py', 'status']; cli.main()"
            )
            with tempfile.TemporaryDirectory() as td:
                env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "HC_TERMINAL_ID")}
                env["PM_HOME"] = td
                res = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, want_code, (expr, res.stdout, res.stderr))
            self.assertEqual(res.stdout.strip(), want_out, expr)
            self.assertEqual(res.stderr.strip(), want_err, expr)


class ConfigClockOutputProcessesTest(unittest.TestCase):
    def test_config_reads_fresh_on_every_call_without_caching(self):
        with tempfile.TemporaryDirectory() as td:
            h = home.Home(Path(td) / "ledger")
            cfg = config.Config(h)
            self.assertEqual(cfg.read(), {})
            self.assertEqual(cfg.lang(), "en")
            self.assertEqual(cfg.tr("yes", "是"), "yes")

            h.root.mkdir(parents=True)
            h.config.write_text(json.dumps({"lang": "zh", "extra": 42}), encoding="utf-8")
            self.assertEqual(cfg.get("extra"), 42)
            self.assertEqual(cfg.lang(), "zh")
            self.assertEqual(cfg.tr("yes", "是"), "是")

            h.config.write_text("{broken json", encoding="utf-8")
            self.assertEqual(cfg.read(), {})
            self.assertEqual(cfg.lang(), "en")

    def test_std_output_resolves_streams_dynamically_and_buffer_output_captures(self):
        std = context.StdOutput()
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            std.line("hello")
            std.err_line("oops")
            std.json({"k": "中"})
        self.assertEqual(out_buf.getvalue(), 'hello\n{"k": "中"}\n')
        self.assertEqual(err_buf.getvalue(), "oops\n")

        buf = context.BufferOutput()
        buf.write("a")
        buf.line("b")
        buf.err("e")
        buf.err_line("f")
        buf.json({"x": 1}, stream="stderr")
        self.assertEqual(buf.stdout, "ab\n")
        self.assertEqual(buf.stderr, 'ef\n{"x": 1}\n')
        buf.clear()
        self.assertEqual((buf.stdout, buf.stderr), ("", ""))

    def test_system_clock_and_fake_clock(self):
        sys_clk = context.SystemClock()
        self.assertRegex(sys_clk.now(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertRegex(sys_clk.now_sec(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertGreater(sys_clk.monotonic(), 0.0)
        self.assertEqual(sys_clk.seconds_since("invalid"), float("inf"))

        clk = FakeClock("2026-11-22 10:00:00", mono=5.0)
        self.assertEqual(clk.now(), "2026-11-22 10:00")
        self.assertEqual(clk.now_sec(), "2026-11-22 10:00:00")
        clk.sleep(90)
        self.assertEqual(clk.sleeps, [90.0])
        self.assertEqual(clk.monotonic(), 95.0)
        self.assertEqual(clk.now_sec(), "2026-11-22 10:01:30")
        self.assertEqual(clk.seconds_since("2026-11-22 10:00"), 90.0)

    def test_processes_and_context_from_env(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ledger"
            env = {
                "PM_HOME": str(root),
                "HC_TERMINAL_ID": "t9",
                "HERDR_WORKSPACE_ID": "ws-1",
                "CLAUDECODE": "1",
                "PATH": os.environ.get("PATH", ""),
            }
            ctx = context.Context.from_env(env=env)
            self.assertEqual(ctx.home.root, root)
            self.assertEqual(ctx.pane, "hc:t9")
            self.assertEqual(ctx.hc_terminal, "t9")
            self.assertEqual(ctx.workspace, "ws-1")
            self.assertIsInstance(ctx.store, store.FileStore)
            self.assertIsInstance(ctx.config, config.Config)
            self.assertIsInstance(ctx.procs, procs.Processes)
            self.assertNotIn("CLAUDECODE", ctx.procs.clean_session_env())
            self.assertIn(str(root), ctx.procs.pm_command())

            ctx.store.change_task("demo-t1", lambda _c: {"id": "demo-t1", "status": "proposed"})
            self.assertEqual(ctx.store.task("demo-t1")["status"], "proposed")


class FakesAndIsolationTest(unittest.TestCase):
    def test_make_ctx_is_isolated_and_fakes_work(self):
        with tempfile.TemporaryDirectory() as td:
            clk = FakeClock("2026-11-22 14:00:00")
            hc = FakeHc(
                {"t7": [{"state": "live", "status": {"state": "working"}}, {"state": "live", "status": {"state": "idle"}, "labels": {"pm": "demo"}}]},
                clock=clk,
                waiter_results=[True, False],
            )
            tui = FakeTui(
                agents=[{"pane_id": "w1:p1", "workspace_id": "w1", "name": "pm-demo"}],
                panes=[{"pane_id": "w1:p1", "workspace_id": "w1"}],
                workspaces=[{"workspace_id": "w1", "label": "pm-demo"}],
            )
            ctx = make_ctx(td, pane="hc:t7", hc=hc, tui=tui, clock=clk, config={"lang": "zh"})
            real_homes = (Path.home() / ".dudu", Path.home() / ".claude" / "pm")
            for real in real_homes:
                self.assertFalse(ctx.home.root == real or real in ctx.home.root.parents)
            self.assertEqual(ctx.config.tr("en", "zh"), "zh")

            # Scripted multi-look queue on FakeHc + --if idle checking
            first = hc("get", "t7")
            self.assertEqual(first["status"]["state"], "working")
            rejected = hc("send", "--if", "idle", "t7", "hi")
            self.assertEqual(rejected, {"ok": True, "started": False})
            second = hc("get", "t7")
            self.assertEqual(second["status"]["state"], "idle")
            sent = hc("send", "--if", "idle", "t7", "hi")
            self.assertEqual(sent, {"ok": True, "started": True})
            self.assertEqual(hc.sent, [("t7", "hi")])

            with hc.change_waiter(terminals={"t7"}) as waiter:
                self.assertTrue(waiter.wait(5))
                self.assertFalse(waiter.wait(5))
            self.assertTrue(waiter.closed)

            # FakeTui & FakeProcs
            self.assertEqual(tui("agent", "list")["agents"][0]["name"], "pm-demo")
            ctx.procs.spawn_pm(["deliver", "/repo"])
            ran = ctx.procs.run_spawned(lambda e: e["args"])
            self.assertEqual(ran, [["deliver", "/repo"]])
            self.assertEqual(ctx.procs.spawned, [])

            # StubGit
            git = StubGit(states={("/wt", "dev/x", "main"): (2, 1)})
            self.assertEqual(git.git_state("/wt", "dev/x", "main"), (2, 1))

    def test_from_env_reads_pm_home_and_runtime_env_vars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "alt"
            root.mkdir()
            (root / "config.json").write_text(json.dumps({"lang": "zh"}), encoding="utf-8")
            env = {
                "PM_HOME": str(root),
                "HC_TERMINAL_ID": "t55",
                "HERDR_WORKSPACE_ID": "w9",
            }
            ctx = context.Context.from_env(env=env)
            self.assertEqual(ctx.home.root, root)
            self.assertEqual(ctx.pane, "hc:t55")
            self.assertEqual(ctx.hc_terminal, "t55")
            self.assertEqual(ctx.workspace, "w9")
            self.assertEqual(ctx.config.lang(), "zh")

    def test_sibling_imports_alias_pmlib_without_loading_pm(self):
        code = (
            "import os, sys\n"
            "from unittest import mock\n"
            "os.environ['PM_HOME'] = '/nonexistent-sibling-test'\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import pm_store, pm_events, pm_sessions, pm_project\n"
            "import pmlib.store, pmlib.terminals.events, pmlib.agents.transcripts, pmlib.project.readmodel\n"
            "assert 'pm' not in sys.modules\n"
            "assert pm_store is pmlib.store\n"
            "assert pm_events is pmlib.terminals.events\n"
            "assert pm_sessions is pmlib.agents.transcripts\n"
            "assert pm_project is pmlib.project.readmodel\n"
            "with mock.patch.object(pm_store, 'LOCK_TIMEOUT', 99.0):\n"
            "    assert pmlib.store.LOCK_TIMEOUT == 99.0\n"
            "print('ok')\n"
        )
        res = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout.strip(), "ok")

    def test_fake_hc_cli_option_parsing_matches_real_call_sites(self):
        hc = FakeHc({"t1": {"state": "live", "status": {"state": "idle"}, "screen": "l1\nl2\nl3\nl4"}})

        # helpers/records.py:92 -> hc("read", term, "--lines", str(lines))
        self.assertEqual(hc("read", "t1", "--lines", "2"), {"text": "l3\nl4"})
        self.assertEqual(hc("read", "--lines", "2", "t1"), {"text": "l3\nl4"})
        self.assertEqual(hc("read", "t1", "--lines=2"), {"text": "l3\nl4"})
        self.assertEqual(hc("read", "t1", "--lines", "0"), {"text": ""})
        self.assertEqual(hc("read", "t1"), {"text": "l1\nl2\nl3\nl4"})

        # `--` separator and options after positional args on send / interrupt
        self.assertEqual(hc("send", "--", "t1", "--literal"), {"ok": True, "started": True})
        self.assertEqual(hc("send", "--if", "idle", "--", "t1", "--if"), {"ok": True, "started": True})
        self.assertEqual(hc("send", "t1", "--if", "idle", "hello"), {"ok": True, "started": True})
        self.assertEqual(hc("send", "t1", "--", "-dash"), {"ok": True, "started": True})
        self.assertEqual(
            hc.sent,
            [("t1", "--literal"), ("t1", "--if"), ("t1", "hello"), ("t1", "-dash")],
        )

        # workers/escalate.py:274 -> hc("interrupt", pane[3:], "--timeout", "10")
        self.assertEqual(hc("interrupt", "t1", "--timeout", "10"), {"ok": True})
        self.assertTrue(hc("get", "t1")["interrupted"])

        # terminals/hc.py:58 + workers/dispatch.py:132 -> placement bool flags before --, child flags after --
        started = hc(
            "run", "--bg", "--parent", "t0", "--outlive-parent", "--no-notify",
            "--label", "task=demo-1", "--name", "w1", "--cwd", "/repo",
            "--", "claude", "--name", "inner", "--model", "opus",
        )
        self.assertEqual(started["name"], "w1")
        self.assertEqual(started["cwd"], "/repo")
        self.assertEqual(started["labels"], {"task": "demo-1"})
        self.assertEqual(started["parent"], "t0")
        self.assertEqual(started["argv"], ["claude", "--name", "inner", "--model", "opus"])

    def test_fake_tui_workspaces_worktree_and_agent_start_contract(self):
        with tempfile.TemporaryDirectory() as td:
            pms_dir = Path(td) / "pms"
            pms_dir.mkdir()
            tui = FakeTui(
                workspaces=[{"workspace_id": "w0", "label": "pm-demo"}],
                sessions=[{"name": "s1", "running": True}],
            )
            self.assertEqual(tui("workspace", "list")["workspaces"], [{"workspace_id": "w0", "label": "pm-demo"}])
            self.assertEqual(tui.workspaces(), [{"workspace_id": "w0", "label": "pm-demo"}])

            # commands/dispatch.py:117-126 -> worktree create returns workspace_id, pane_id, path
            created = tui(
                "worktree", "create", "--cwd", "/tmp/repo", "--branch", "dev/feat",
                "--base", "main", "--label", "feat", "--no-focus",
            )
            flat = json.dumps(created)
            found = [re.search(rf'"{k}": "([^"]+)"', flat) for k in ("workspace_id", "pane_id", "path")]
            self.assertTrue(all(found), flat)
            ws, pane, wt_path = (m.group(1) for m in found if m is not None)
            self.assertNotEqual(wt_path, "--cwd")
            self.assertTrue(wt_path.endswith("repo-dev-feat"), wt_path)

            self.assertIn(ws, [w["workspace_id"] for w in tui("workspace", "list")["workspaces"]])
            self.assertIn(ws, [w["workspace_id"] for w in tui.workspaces()])
            listed_wt = tui("worktree", "list", "--cwd", "/tmp/repo")["worktrees"]
            self.assertEqual(len(listed_wt), 1)
            self.assertEqual(listed_wt[0]["open_workspace_id"], ws)

            # commands/dispatch.py:129-133 -> agent start registers agent visible in agent list & pane list
            started = tui("agent", "start", "w-feat", "--kind", "claude", "--pane", pane, "--", "--model", "opus")
            self.assertTrue(started["ok"])
            agents_rows = tui("agent", "list")["agents"]
            self.assertEqual(len(agents_rows), 1)
            self.assertEqual(agents_rows[0]["pane_id"], pane)
            self.assertEqual(agents_rows[0]["workspace_id"], ws)
            self.assertEqual(agents_rows[0]["name"], "w-feat")
            self.assertEqual(agents_rows[0]["kind"], "claude")
            self.assertEqual(agents_rows[0]["argv"], ["--model", "opus"])

            # Verify Caller(ctx).identity_inventory() invariant (pane_id & workspace_id on every agent/pane row)
            inv_ctx = make_ctx(td, tui=tui)
            inv = caller.Caller(inv_ctx).identity_inventory()
            self.assertEqual(len(inv["agents"]), 1)
            self.assertEqual(inv["agents"][0]["pane_id"], pane)
            self.assertEqual(inv["agents"][0]["workspace_id"], ws)
            self.assertEqual(len(inv["panes"]), 1)
            self.assertEqual(inv["panes"][0]["workspace_id"], ws)

            # workers/escalate.py:276 -> agent send-keys
            self.assertEqual(tui("agent", "send-keys", pane, "esc"), {"ok": True})
            self.assertEqual(tui.sent_keys, [(pane, ["esc"])])

            # Custom --path override + workers/lifecycle.py:328 worktree remove --workspace
            custom = tui(
                "worktree", "create", "--cwd", "/tmp/repo", "--branch", "dev/b",
                "--base", "main", "--label", "b", "--no-focus", "--path", "/tmp/custom-wt",
            )
            self.assertEqual(custom["path"], "/tmp/custom-wt")
            self.assertEqual(tui("worktree", "remove", "--workspace", custom["workspace_id"], "--force"), {"ok": True})

            self.assertEqual(tui("worktree", "remove", "--workspace", ws, "--force"), {"ok": True})
            self.assertEqual(tui("worktree", "list")["worktrees"], [])
            self.assertEqual(tui("agent", "list")["agents"], [])
            self.assertEqual(tui("pane", "list")["panes"], [])
            self.assertEqual([w["workspace_id"] for w in tui("workspace", "list")["workspaces"]], ["w0"])

    def test_procs_and_fake_procs_read_osutil_windows_dynamically(self):
        root = Path("/Users/Jo Doe/ledger")
        launcher_path = Path("/Users/Jo Doe/pm.py")
        h = home.Home(root)
        real_procs = procs.Processes(h, env={"PM_HOME": str(root)}, launcher_path=launcher_path)
        fake_procs = FakeProcs(h, env={"PM_HOME": str(root)}, launcher_path=launcher_path)

        with mock.patch.object(osutil, "WINDOWS", True), \
                mock.patch.object(osutil.shutil, "which", return_value=r"C:\Windows\py.exe"), \
                mock.patch.object(home, "current", return_value=h), \
                mock.patch.object(procs, "launcher", return_value=launcher_path):
            want = 'py -3 "/Users/Jo Doe/pm.py" --home "/Users/Jo Doe/ledger"'
            self.assertEqual(real_procs.pm_command(), want)
            self.assertEqual(fake_procs.pm_command(), want)
            with mock.patch.dict(os.environ, {"PM_HOME": str(root)}):
                self.assertEqual(procs.pm_command(), want)

            no_home_real = procs.Processes(h, env={}, launcher_path=launcher_path)
            no_home_fake = FakeProcs(h, env={}, launcher_path=launcher_path)
            self.assertEqual(no_home_real.pm_command(), 'py -3 "/Users/Jo Doe/pm.py"')
            self.assertEqual(no_home_fake.pm_command(), 'py -3 "/Users/Jo Doe/pm.py"')
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PM_HOME", None)
                self.assertEqual(procs.pm_command(), 'py -3 "/Users/Jo Doe/pm.py"')

        with mock.patch.object(osutil, "WINDOWS", False):
            posix_want = "PM_HOME='/Users/Jo Doe/ledger' python3 '/Users/Jo Doe/pm.py'"
            self.assertEqual(real_procs.pm_command(), posix_want)
            self.assertEqual(fake_procs.pm_command(), posix_want)

    def test_fake_hc_name_tab_rename_tab_queue_reassignment_and_server_down(self):
        hc = FakeHc({"t1": ["working", "idle"]})

        # First queue progression + reassigning hc.terminals["t1"] to a new list starts from element 0 again
        self.assertEqual(hc("get", "t1")["status"]["state"], "working")
        self.assertEqual(hc("get", "t1")["status"]["state"], "idle")
        hc.terminals["t1"] = ["working", "done"]
        self.assertEqual(hc("get", "t1")["status"]["state"], "working")
        self.assertEqual(hc("get", "t1")["status"]["state"], "done")

        # hc.run never overwrites pre-seeded t1
        launched = hc("run", "--bg", "--", "echo", "hi")
        self.assertEqual(launched["address"], "t2")
        self.assertIn("t1", hc.terminals)

        # name_tab & rename_tab signatures (only_if, wait) and bool return matching terminals/tabs.py
        self.assertIs(hc.name_tab("t1", "PM-demo"), True)
        self.assertIs(hc.name_tab("t1", "", only_if="PM-other"), False)
        self.assertEqual(hc.tab_names["t1"], "PM-demo")
        self.assertIs(hc.name_tab("t1", "", only_if="PM-demo"), True)
        self.assertEqual(hc.tab_names["t1"], "")
        self.assertIs(hc.name_tab("t1", "w1", wait=5), True)
        self.assertIs(hc.name_tab("missing", "x", wait=15), False)
        self.assertIs(hc.rename_tab("t1", "t1-fix", wait=15, only_if="w1"), True)
        self.assertEqual(hc.tab_names["t1"], "t1-fix")

        hc.app_available = False
        self.assertIs(hc.name_tab("t1", "nope"), False)
        hc.app_available = True

        # errors=True on label / keep / keys / read / kill / rm / interrupt when missing
        for op in (
            ("label", "missing", "k=v"),
            ("keep", "missing"),
            ("keys", "missing", "enter"),
            ("read", "missing", "--lines", "5"),
            ("kill", "missing"),
            ("rm", "missing"),
            ("interrupt", "missing", "--timeout", "10"),
        ):
            self.assertEqual(hc(*op, errors=True)["error"]["kind"], "not_found", op)
            self.assertIsNone(hc(*op, errors=False), op)

        # server_running=False returns None across CLI and direct methods (manager.py:454)
        hc.server_running = False
        self.assertIsNone(hc("server", "status"))
        self.assertIsNone(hc("get", "t1"))
        self.assertIsNone(hc("get", "t1", errors=True))
        self.assertIsNone(hc("ls"))
        self.assertIsNone(hc("ls", "--all"))
        self.assertIsNone(hc("send", "t1", "hi"))
        self.assertIsNone(hc("run", "--bg", "--", "echo"))
        self.assertIsNone(hc.get("t1"))
        self.assertIsNone(hc.ls())
        self.assertIsNone(hc.rpc("doc.get", {"name": "herdr-app"}))
        self.assertIs(hc.rename_tab("t1", "down"), False)

    def test_fake_tui_server_ok_session_filtering_and_pane_read(self):
        tui = FakeTui(
            sessions=[
                {"name": "s1", "socket_path": "/tmp/s1.sock", "running": True},
                {"name": "s2", "socket_path": "/tmp/s2.sock", "running": True},
            ],
            workspaces=[
                {"workspace_id": "w1", "label": "pm-a", "session": "s1"},
                {"workspace_id": "w2", "label": "pm-b", "session": "s2"},
            ],
            panes=[
                {"pane_id": "w1:p1", "workspace_id": "w1", "agent": "claude", "agent_status": "idle", "session": "s1"},
                {"pane_id": "w2:p1", "workspace_id": "w2", "agent": "codex", "agent_status": "working", "session": "s2"},
            ],
            agents=[
                {"pane_id": "w1:p1", "workspace_id": "w1", "name": "pm-a", "session": "s1"},
                {"pane_id": "w2:p1", "workspace_id": "w2", "name": "pm-b", "session": "s2"},
            ],
            worktrees=[
                {"path": "/wt/a", "open_workspace_id": "w1", "cwd": "/repo/a", "session": "s1"},
                {"path": "/wt/b", "open_workspace_id": "w2", "cwd": "/repo/b", "session": "s2"},
            ],
            pane_screens={"w1:p1": "line1\nRunning 1 shell\nesc to interrupt"},
            current_session="s1",
            wait_results=[True, False],
        )

        # session-scoped direct query methods + socket_session
        self.assertEqual([a["name"] for a in tui.agents(session="s1")], ["pm-a"])
        self.assertEqual([p["pane_id"] for p in tui.panes(session="s2")], ["w2:p1"])
        self.assertEqual([w["workspace_id"] for w in tui.workspaces(session="s1")], ["w1"])
        self.assertEqual([w["path"] for w in tui.worktrees(session="s1")], ["/wt/a"])
        self.assertEqual(tui.socket_session(tui.sessions()), "s1")

        # pane read via events/inbox.py:81 shape + direct helper
        self.assertEqual(tui("pane", "read", "w1:p1", "--lines", "2", session="s1"), {"text": "Running 1 shell\nesc to interrupt"})
        self.assertEqual(tui("pane", "read", "w1:p1", "--lines", "0", session="s1"), {"text": ""})
        self.assertIsNone(tui("pane", "read", "w2:p1", "--lines", "5", session="s1"))
        self.assertEqual(tui.pane_read("w1:p1", lines=1, session="s1"), "esc to interrupt")

        # agent wait recording + scripted results; unknown command returns None
        self.assertEqual(tui("agent", "wait", "pm-a", "--until", "working", "--until", "idle", "--timeout", "30000"), {"ok": True})
        self.assertIsNone(tui("agent", "wait", "pm-a", "--until", "working", "--timeout", "1000"))
        self.assertEqual(tui.waits[0], ("pm-a", ["working", "idle"], "30000"))
        self.assertIsNone(tui("unknown", "subcmd"))

        # server_ok=False matches TuiHost contract: herdr()/panes/workspaces/worktrees return None,
        # agents() returns [], pane_read() returns "", sessions()/socket_session() raise IdentityError.
        tui.server_ok = False
        self.assertIsNone(tui("workspace", "list", session="s1"))
        self.assertIsNone(tui("pane", "list", session="s1"))
        self.assertIsNone(tui("pane", "read", "w1:p1", "--lines", "12", session="s1"))
        self.assertEqual(tui.agents(), [])
        self.assertEqual(tui.agents(session="s1"), [])
        self.assertIsNone(tui.panes())
        self.assertIsNone(tui.panes(session="s1"))
        self.assertIsNone(tui.workspaces())
        self.assertIsNone(tui.worktrees())
        with self.assertRaises(errors.IdentityError):
            tui.sessions()
        with self.assertRaises(errors.IdentityError):
            tui.socket_session()
        self.assertEqual(tui.pane_read("w1:p1"), "")

    def test_fake_procs_run_completed_process_and_stub_git_surface(self):
        with tempfile.TemporaryDirectory() as td:
            h = home.Home(Path(td) / "ledger")
            fp = FakeProcs(h, env={"PM_HOME": str(h.root)})
            res = fp.run(["git", "status"], cwd=td)
            self.assertIsInstance(res, subprocess.CompletedProcess)
            self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""))

            fp.spawn_ok = False
            self.assertIsNone(fp.spawn_pm(["deliver", td]))

            lock_file = Path(td) / "wt" / ".git" / "index.lock"
            git = StubGit(
                roots={"/repo": "/repo"},
                git_results={("/repo", "rev-parse", "HEAD"): "abc123"},
                checkouts={("/repo", "dev/x"): "/wt/x"},
                owned_worktrees=["/wt/x"],
                worktree_base=Path(td) / "worktrees",
                index_locks={"/wt/x": lock_file},
                undo_ok=True,
            )
            self.assertEqual(git.git("/repo", "rev-parse", "HEAD"), "abc123")
            self.assertEqual(git.main_root("/repo"), "/repo")
            self.assertTrue(git.is_owned_worktree("/wt/x"))
            self.assertFalse(git.is_owned_worktree("/elsewhere"))
            self.assertEqual(git.checkout_of("/repo", "dev/x"), "/wt/x")
            self.assertEqual(git.index_lock("/wt/x"), lock_file)
            self.assertTrue(git.undo_merge("/repo"))

    def test_from_env_is_import_order_independent(self):
        with tempfile.TemporaryDirectory() as td:
            env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "HC_TERMINAL_ID", "HERDR_WORKSPACE_ID")}
            env["PM_HOME"] = str(Path(td) / "ledger")

            # 1) Calling Context.from_env() directly without importing procs or cli first
            code_direct = (
                "import sys\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "from pmlib import context\n"
                "fctx = context.Context.from_env(env={'PM_HOME': sys.argv[2]})\n"
                "assert str(fctx.home.root) == sys.argv[2]\n"
                "assert fctx.store is not None and fctx.procs is not None and fctx.config is not None\n"
                "assert not hasattr(context, 'legacy_context')\n"
                "print('ok')\n"
            )
            res = subprocess.run([sys.executable, "-c", code_direct, str(SCRIPTS), env["PM_HOME"]], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertEqual(res.stdout.strip(), "ok")

            # 2) Every Layer-1 and sibling entry point can be imported FIRST without circular ImportError
            first_mods = (
                "pmlib.context",
                "pmlib.config",
                "pmlib.home",
                "pmlib.store",
                "pmlib.procs",
                "pmlib.terminals.hc",
                "pmlib.terminals.events",
                "pmlib.agents.base",
                "pmlib.agents.sessions",
                "pm_store",
                "pm_events",
            )
            for mod_name in first_mods:
                code_first = (
                    f"import importlib, sys; sys.path.insert(0, sys.argv[1]); "
                    f"importlib.import_module({mod_name!r}); "
                    f"from pmlib import context; "
                    f"assert context.Context.from_env().home.root; print('ok')"
                )
                r = subprocess.run([sys.executable, "-c", code_first, str(SCRIPTS)], capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, f"first={mod_name}: {r.stdout + r.stderr}")
                self.assertEqual(r.stdout.strip(), "ok", mod_name)


if __name__ == "__main__":
    unittest.main()
