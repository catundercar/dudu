"""Unit tests for Stage 2a host and git ports (`TerminalInfo`, `HcHost`, desktop tab methods, `TuiHost`, `GitRepo`)."""
from __future__ import annotations

import json
import os
from pathlib import Path
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
    _init_tmp = tempfile.mkdtemp(prefix="pm-ports-init-")
    os.environ["PM_HOME"] = _init_tmp
    try:
        from pmlib import context, errors, gitrepo, home, procs  # noqa: E402
    finally:
        if _saved_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_home
else:
    from pmlib import context, errors, gitrepo, home, procs  # noqa: E402

from pmlib import osutil  # noqa: E402
from pmlib.config import Config  # noqa: E402
from pmlib.terminals import hc as hc_mod, screen as screen_mod, tabs as tabs_mod, tui as tui_mod  # noqa: E402
from fakes import FakeClock, FakeHc, FakeTui, StubGit, make_ctx  # noqa: E402


def _git_init(repo: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True, capture_output=True, text=True,
        )

    repo.mkdir(parents=True, exist_ok=True)
    run("init", "-q", "-b", "main")
    run("config", "user.name", "Test")
    run("config", "user.email", "test@example.com")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "initial")


class TerminalInfoAndHcHostTest(unittest.TestCase):
    def test_terminal_info_from_dict_and_properties(self):
        row = {
            "address": "t7",
            "name": "worker-1",
            "state": "live",
            "status": {"state": "working", "msg": "1 shell still running"},
            "turn": 4,
            "labels": {"pm": "demo", "herdr.space": "sp-1"},
            "argv": ["claude", "--model", "opus"],
            "foreground": {"pid": 4321, "argv": ["/bin/zsh"]},
            "cwd": "/tmp/demo",
            "pid": 1234,
            "status_ms": 1700000000000,
            "reported": True,
        }
        info = hc_mod.TerminalInfo.from_dict(row)
        self.assertEqual(info.address, "t7")
        self.assertEqual(info.name, "worker-1")
        self.assertTrue(info.is_live)
        self.assertTrue(info.has_status)
        self.assertEqual(info.agent_state, "working")
        self.assertEqual(info.status_msg, "1 shell still running")
        self.assertEqual(info.turn, 4)
        self.assertEqual(info.label("pm"), "demo")
        self.assertEqual(info.label("missing", "fallback"), "fallback")
        self.assertEqual(info.argv, ("claude", "--model", "opus"))
        self.assertEqual(info.foreground_argv, ("/bin/zsh",))
        self.assertEqual(info.foreground_pid, 4321)
        self.assertEqual(info.cwd, "/tmp/demo")
        self.assertEqual(info.pid, 1234)
        self.assertEqual(info.status_ms, 1700000000000)
        self.assertTrue(info.reported)
        self.assertTrue(info.is_shell)
        self.assertTrue(hc_mod.is_shell_terminal(info))

        # Seat argv is never considered a plain interactive shell.
        seat_row = {
            "address": "t8",
            "state": "live",
            "argv": ["python3", "/x/pm.py", "seat", "--repo", "/tmp/demo", "--", "claude"],
            "foreground": {"argv": ["/bin/zsh"]},
        }
        seat_info = hc_mod.TerminalInfo.from_dict(seat_row)
        self.assertFalse(seat_info.is_shell)
        self.assertFalse(seat_info.has_status)

        # Extra fields (reason, created_ms, finished_ms, seat_dead) and omitted state -> is_live True
        omitted_state = hc_mod.TerminalInfo.from_dict({
            "address": "t9",
            "created_ms": 1000,
            "finished_ms": 2000,
            "reason": "killed",
            "seat_dead": True,
        })
        self.assertEqual(omitted_state.state, "live")
        self.assertTrue(omitted_state.is_live)
        self.assertEqual(omitted_state.created_ms, 1000)
        self.assertEqual(omitted_state.finished_ms, 2000)
        self.assertEqual(omitted_state.reason, "killed")
        self.assertTrue(omitted_state.seat_dead)

        # Windows shell detection reads osutil.WINDOWS dynamically and uses PureWindowsPath
        win_cmd = {"address": "t12", "state": "live", "foreground": {"argv": [r"C:\Windows\System32\cmd.exe"]}}
        win_pwsh = {"address": "t13", "state": "live", "foreground": {"argv": [r"C:\Program Files\PowerShell\7\pwsh.exe"]}}
        with mock.patch.object(osutil, "WINDOWS", True):
            self.assertTrue(hc_mod.is_shell_terminal(win_cmd))
            self.assertTrue(hc_mod.is_shell_terminal(win_pwsh))
            self.assertTrue(hc_mod.TerminalInfo.from_dict(win_cmd).is_shell)
        with mock.patch.object(osutil, "WINDOWS", False):
            self.assertFalse(hc_mod.is_shell_terminal(win_cmd))

    def test_hc_host_queries_mutations_and_screen(self):
        fake = FakeHc({
            "t10": {
                "state": "live",
                "status": {"state": "idle"},
                "labels": {"pm": "demo", "herdr.space": "sp-9"},
                "screen": "line 1\nline 2\nline 3",
            },
            "t11": {"state": "exited", "status": {"state": "done"}},
        })
        host = hc_mod.HcHost(
            {"hc": "/custom/hc", "tabs": {"new_tab": True}},
            runner=fake,
        )
        self.assertEqual(host.bin(), "/custom/hc")
        info = host.get("t10")
        self.assertIsNotNone(info)
        self.assertEqual(info.address, "t10")
        self.assertEqual(info.agent_state, "idle")
        self.assertIsNone(host.get("t99"))

        live_list = host.ls(all=False)
        self.assertEqual([t.address for t in live_list], ["t10"])
        all_list = host.ls(all=True)
        self.assertEqual([t.address for t in all_list], ["t10", "t11"])

        live_rows, ended_rows = host.all_rows()
        self.assertEqual(set(live_rows), {"t10"})
        self.assertEqual(set(ended_rows), {"t11"})
        self.assertEqual(host.live_terminals(), {"t10"})

        self.assertEqual(host.worker_state("t10"), "idle")
        self.assertEqual(host.worker_state("t11"), "exited")
        self.assertEqual(host.worker_state("t99"), "removed")
        self.assertEqual(host.worker_state(""), "")

        # Mutations
        addr = host.start_terminal("w-1", "/tmp/wt", ["claude"], ["--parent", "t10"], labels=["task=d-1"])
        self.assertTrue(addr)
        self.assertEqual(host.send(addr, "go", if_state="idle"), {"ok": True, "started": True})
        self.assertEqual(host.keys(addr, "enter"), {"ok": True})
        self.assertEqual(host.keep(addr), {"ok": True})
        self.assertEqual(host.interrupt(addr, timeout=10), {"ok": True})
        self.assertIn(("interrupt", addr, "--timeout", "10"), fake.calls)
        self.assertEqual(host.read("t10"), "line 1\nline 2\nline 3")
        self.assertEqual(screen_mod.screen_of("t10", host=host), "line 1\nline 2\nline 3")
        self.assertEqual(screen_mod.screen_line("t10", host=host), "line 1 / line 2 / line 3")
        self.assertEqual(host.kill(addr), {"ok": True})
        self.assertEqual(host.remove(addr), {"ok": True})
        self.assertIsNone(host.get(addr))
        self.assertEqual(host.server_status(), {"running": True})

    def test_hc_host_desktop_tabs_and_rename_via_core(self):
        clk = FakeClock("2026-11-22 12:00:00")
        app_calls: list[tuple[str, ...]] = []

        def app_runner(*args: str, timeout: float = 30):
            app_calls.append(args)
            if args == ("ls",):
                payload = {"spaces": [{"id": "s1", "tabs": [
                    {"id": "tab-1", "name": "PM-demo", "terminals": [{"terminal": "t1"}]},
                ]}]}
                return subprocess.CompletedProcess(["herdr-app", *args], 0, json.dumps(payload), "")
            return subprocess.CompletedProcess(["herdr-app", *args], 0, '{"ok": true}', "")

        host = hc_mod.HcHost(
            {"tabs": {"new_tab": True}},
            clock=clk,
            app_runner=app_runner,
        )
        self.assertEqual(len(host.app_spaces()), 1)
        self.assertFalse(host.name_tab("t1", "new-name", only_if="other"))
        self.assertTrue(host.name_tab("t1", "new-name", only_if="PM-demo"))
        self.assertEqual(app_calls[-1][0], "do")
        self.assertEqual(app_calls[-1][1], "tab.rename")
        self.assertEqual(json.loads(app_calls[-1][2]), {"id": "tab-1", "name": "new-name"})

        # Fallback to doc.get / doc.set when herdr-app is absent and tabs.rename_via_core is True.
        doc_state = {
            "version": 3,
            "value": {
                "spaces": [{
                    "tabs": [{
                        "id": "tb-2",
                        "name": "old",
                        "root": {"children": [{"content": {"terminal": "t2"}}]},
                    }],
                }],
            },
        }
        rpc_calls: list[tuple[str, object]] = []

        def rpc_runner(method: str, params):
            rpc_calls.append((method, params))
            if method == "doc.get":
                return {"id": 1, "result": {"value": doc_state["value"], "version": doc_state["version"]}}
            if method == "doc.set":
                doc_state["value"] = params["value"]
                doc_state["version"] += 1
                return {"id": 1, "result": {"ok": True}}
            return None

        def missing_app(*_args: str, timeout: float = 30):
            raise FileNotFoundError("herdr-app")

        core_host = hc_mod.HcHost(
            {"tabs": {"rename_via_core": True}},
            clock=clk,
            app_runner=missing_app,
            rpc_runner=rpc_runner,
        )
        self.assertTrue(core_host.name_tab("t2", "t2-fix", wait=0))
        self.assertEqual(doc_state["value"]["spaces"][0]["tabs"][0]["name"], "t2-fix")
        self.assertEqual([m for m, _ in rpc_calls], ["doc.get", "doc.set"])

        # worker_tab labels terminal and renames its tab using caller_pane's space.
        fake = FakeHc({"tPM": {"state": "live", "labels": {"herdr.space": "sp-5"}}, "tW": {"state": "live"}})
        w_host = hc_mod.HcHost(
            {"tabs": {"new_tab": True}},
            clock=clk,
            runner=fake,
            app_runner=lambda *args, timeout=30: subprocess.CompletedProcess(
                ["herdr-app", *args], 0,
                json.dumps({"spaces": [{"tabs": [{"id": "tb-w", "name": "", "terminals": [{"terminal": "tW"}]}]}]}),
                "",
            ),
        )
        self.assertTrue(w_host.worker_tab("tW", "demo-1", "tW-fix", parent="demo-0", caller_pane="hc:tPM"))
        w_info = w_host.get("tW")
        self.assertEqual(w_info.label("task"), "demo-1")
        self.assertEqual(w_info.label("parent"), "demo-0")
        self.assertEqual(w_info.label("herdr.space"), "sp-5")
        self.assertTrue(w_info.label("herdr.tab").startswith("tb"))

    def test_tabs_module_has_no_context_globals_and_accepts_explicit_cfg(self):
        with tempfile.TemporaryDirectory() as td:
            h = home.Home(Path(td) / "ledger")
            h.root.mkdir(parents=True)
            h.config.write_text(json.dumps({"tabs": {"new_tab": True, "bug_pattern": r"BUG-(\d+)", "max": 10}}), encoding="utf-8")
            cfg = Config(h)
            self.assertTrue(tabs_mod.new_tabs(cfg=cfg, pane="hc:t1"))
            self.assertFalse(tabs_mod.new_tabs(cfg=cfg, pane="w1:p1"))
            self.assertEqual(tabs_mod.bug_of("", "fix BUG-4242 now", cfg=cfg), "4242")
            self.assertEqual(tabs_mod.tab_title("very-long-tab-name", "4242", "t5g", cfg=cfg), "t5g-4242-very-long")


class TuiHostTest(unittest.TestCase):
    def test_tui_host_calls_strict_and_session_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            sock = Path(td) / "default.sock"
            sock.write_text("", encoding="utf-8")
            calls: list[list[str]] = []

            def raw_runner(argv: list[str], *, timeout: float = 30):
                calls.append(argv)
                if argv == ["herdr", "session", "list", "--json"]:
                    return subprocess.CompletedProcess(
                        argv, 0,
                        json.dumps({"sessions": [{"name": "default", "socket_path": str(sock), "running": True}]}),
                        "",
                    )
                if argv == ["herdr", "status", "server"]:
                    return subprocess.CompletedProcess(argv, 0, f"socket: {sock}\n", "")
                if argv[:3] == ["herdr", "pane", "read"]:
                    return subprocess.CompletedProcess(argv, 0, "Running 1 shell\n", "")
                if argv[-2:] == ["agent", "list"]:
                    return subprocess.CompletedProcess(
                        argv, 0, json.dumps({"result": {"agents": [{"pane_id": "w1:p1", "name": "pm-demo"}]}}), ""
                    )
                if argv[-2:] == ["pane", "run"] or "run" in argv:
                    return subprocess.CompletedProcess(argv, 0, "", "")
                return subprocess.CompletedProcess(argv, 1, "", "err")

            tui = tui_mod.TuiHost(raw_runner=raw_runner)
            self.assertEqual(tui.agents(), [{"pane_id": "w1:p1", "name": "pm-demo"}])
            self.assertEqual(tui.pane_run("w1:p1", "echo hi"), {"ok": True})
            self.assertEqual(tui.pane_read("w1:p1", lines=12), "Running 1 shell\n")
            sessions = tui.sessions()
            self.assertEqual(len(sessions), 1)
            self.assertEqual(tui.socket_session(sessions), "default")
            self.assertEqual(tui.strict("agent", "list"), {"agents": [{"pane_id": "w1:p1", "name": "pm-demo"}]})

            with self.assertRaises(errors.IdentityError):
                tui.strict("unknown", "cmd")

            # Verify TuiHost methods emit expected CLI args (worktree_remove --workspace/--force, worktrees --cwd, agent_start, agent_send_keys)
            recorded: list[tuple[str | None, tuple[object, ...]]] = []
            rec_tui = tui_mod.TuiHost(runner=lambda *a, session=None: recorded.append((session, a)) or {"worktrees": []})
            rec_tui.worktrees(cwd="/tmp/repo", session="s1")
            rec_tui.worktree_remove(workspace="w3", force=True, session="s1")
            rec_tui.agent_start("w-1", kind="claude", pane="w3:p1", argv=["--model", "opus"], session="s1")
            rec_tui.agent_send_keys("w3:p1", "esc", "enter", session="s1")
            self.assertEqual(recorded, [
                ("s1", ("worktree", "list", "--cwd", "/tmp/repo")),
                ("s1", ("worktree", "remove", "--workspace", "w3", "--force")),
                ("s1", ("agent", "start", "w-1", "--kind", "claude", "--pane", "w3:p1", "--", "--model", "opus")),
                ("s1", ("agent", "send-keys", "w3:p1", "esc", "enter")),
            ])


class GitRepoTest(unittest.TestCase):
    def test_git_repo_full_lifecycle_on_temp_repo(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "demo"
            wt_root = base / "worktrees"
            _git_init(repo)
            g = gitrepo.GitRepo(worktree_base=wt_root)

            self.assertEqual(Path(g.main_root(repo)).resolve(), repo.resolve())
            self.assertEqual(Path(g.project_root(repo)).resolve(), repo.resolve())
            plain = base / "plain"
            plain.mkdir()
            self.assertEqual(Path(g.project_root(plain)).resolve(), plain.resolve())
            self.assertEqual(g.base_branch(repo), "main")
            self.assertEqual(g.merge_target(repo, "missing"), "main")
            self.assertEqual(g.current_branch(repo), "main")
            self.assertTrue(g.branch_exists(repo, "main"))
            self.assertFalse(g.has_tracked_changes(repo))

            # Worktree creation and ownership checks
            wt = g.worktree_home(repo) / "feat"
            wt.parent.mkdir(parents=True, exist_ok=True)
            self.assertTrue(g.worktree_add(repo, wt, "dev/feat", "main"))
            self.assertTrue(g.is_owned_worktree(wt))
            self.assertFalse(g.is_owned_worktree(repo))
            self.assertEqual(Path(g.checkout_of(repo, "dev/feat")).resolve(), wt.resolve())
            self.assertEqual(Path(g.main_root(wt)).resolve(), repo.resolve())

            # Commit on branch and check git_state
            (wt / "feat.txt").write_text("feature\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "feat.txt"], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "feat"], check=True)
            self.assertEqual(g.git_state(wt, "dev/feat", "main"), (1, 0))

            # Tracked / ignored / porcelain_status_z
            (repo / ".gitignore").write_text("evidence/\n", encoding="utf-8")
            self.assertTrue(g.is_ignored(repo, "evidence/__probe__"))
            self.assertFalse(g.is_ignored(repo, "README.md"))
            self.assertEqual(g.tracked_files(repo, "README.md"), {"README.md"})
            (wt / "untracked.txt").write_text("x\n", encoding="utf-8")
            self.assertIn("?? untracked.txt\0", g.porcelain_status_z(wt) or "")
            (wt / "untracked.txt").unlink()

            # Clean merge --no-commit + commit
            (repo / ".gitignore").unlink()
            merged = g.merge_no_commit(repo, "dev/feat")
            self.assertTrue(merged.ok)
            self.assertEqual(g.conflicts(repo), [])
            committed = g.commit(repo, "merge dev/feat")
            self.assertTrue(committed.ok)
            self.assertTrue(g.is_ancestor(repo, "dev/feat", "HEAD"))

            # Cleanup worktree and branch
            self.assertTrue(g.worktree_remove(repo, wt, force=True))
            self.assertTrue(g.delete_branch(repo, "dev/feat", force=True))
            self.assertFalse(g.branch_exists(repo, "dev/feat"))

    def test_git_repo_conflicts_and_undo_merge(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "demo"
            _git_init(repo)
            g = gitrepo.GitRepo()

            subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "dev/c"], check=True)
            (repo / "README.md").write_text("from branch\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-am", "branch edit"], check=True)

            subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"], check=True)
            (repo / "README.md").write_text("from main\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-am", "main edit"], check=True)

            merged = g.merge_no_commit(repo, "dev/c")
            self.assertFalse(merged.ok)
            self.assertEqual(g.conflicts(repo), ["README.md"])
            self.assertTrue(g.undo_merge(repo))
            self.assertFalse(g.has_tracked_changes(repo))


class ContextPortWiringTest(unittest.TestCase):
    def test_context_from_env_wires_real_ports(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = context.Context.from_env(home_option=td, env={"PM_HOME": td})
            self.assertIsInstance(ctx.hc, hc_mod.HcHost)
            self.assertIsInstance(ctx.tui, tui_mod.TuiHost)
            self.assertIsInstance(ctx.git, gitrepo.GitRepo)

            fake_hc = FakeHc({"t42": {"state": "live", "status": {"state": "idle"}}})
            fake_herdr = mock.MagicMock(return_value={"agents": [{"pane_id": "w1:p2"}]})
            host_hc = hc_mod.HcHost(runner=fake_hc)
            host_tui = tui_mod.TuiHost(runner=fake_herdr)
            info = host_hc.get("t42")
            self.assertIsNotNone(info)
            self.assertEqual(info.address, "t42")
            self.assertEqual(host_tui.agents(), [{"pane_id": "w1:p2"}])

    def test_screen_line_uses_explicit_host(self):
        self.assertEqual(screen_mod.screen_line("t1", host=FakeHc({"t1": {"screen": "x\ny"}})), "x / y")

    def test_make_ctx_fakes_match_port_contracts(self):
        with tempfile.TemporaryDirectory() as td:
            hc = FakeHc({
                "t10": {"state": "live", "status": {"state": "idle"}, "screen": "a\nb\nc"},
                "t11": {"state": "exited"},
            })
            tui = FakeTui(
                agents=[{"pane_id": "w1:p1", "workspace_id": "w1", "name": "pm-demo", "session": "s1"}],
                panes=[{"pane_id": "w1:p1", "workspace_id": "w1", "session": "s1"}],
                workspaces=[{"workspace_id": "w1", "label": "pm-demo", "session": "s1"}],
                process_info={"w1:p1": {"pid": 555}},
            )
            ctx = make_ctx(td, hc=hc, tui=tui)
            # FakeHc port contract
            info = ctx.hc.get("t10")
            self.assertIsInstance(info, hc_mod.TerminalInfo)
            self.assertEqual(info.address, "t10")
            self.assertEqual([t.address for t in ctx.hc.ls()], ["t10"])
            self.assertEqual([t.address for t in ctx.hc.ls(all=True)], ["t10", "t11"])
            # FakeHc._ls_raw projects string `status` and omits get-only keys (`pid`, `argv`, `foreground`, `screen`)
            ls_raw_t10 = hc._ls_raw()["terminals"][0]
            self.assertEqual(ls_raw_t10.get("status"), "idle")
            for get_only_key in ("pid", "argv", "foreground", "screen", "status_ms"):
                self.assertNotIn(get_only_key, ls_raw_t10)
            strict_hc = FakeHc({"t10": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "working"}}}, strict_ls=True)
            self.assertNotIn("labels", strict_hc._ls_raw()["terminals"][0])
            self.assertEqual(strict_hc._ls_raw()["terminals"][0]["status"], "working")
            live_rows, ended_rows = ctx.hc.all_rows()
            self.assertEqual(set(live_rows), {"t10"})
            self.assertEqual(set(ended_rows), {"t11"})
            self.assertEqual(ctx.hc.live_terminals(), {"t10"})
            self.assertEqual(ctx.hc.worker_state("t10"), "idle")
            self.assertEqual(ctx.hc.worker_state("t11"), "exited")
            self.assertEqual(ctx.hc.worker_state("missing"), "removed")
            self.assertEqual(ctx.hc.read("t10", lines=2), "b\nc")
            self.assertEqual(ctx.hc.screen_line("t10"), "a / b / c")

            # FakeHc.run / start_terminal honor placement (--parent, --keep), and make_ctx passes config for new_tabs/worker_tab
            ctx_tabs = make_ctx(
                td,
                pane="hc:tPM",
                hc=FakeHc({"tPM": {"state": "live", "labels": {"herdr.space": "sp-7"}}, "tW": {"state": "live"}}),
                config={"tabs": {"new_tab": True}},
            )
            self.assertTrue(ctx_tabs.hc.new_tabs(caller_pane="hc:tPM"))
            self.assertFalse(ctx_tabs.hc.new_tabs(caller_pane="w1:p1"))
            made = ctx_tabs.hc.start_terminal("w-1", "/wt", ["claude"], placement=("--parent", "tPM", "--keep"))
            made_info = ctx_tabs.hc.get(made)
            self.assertEqual(made_info.raw.get("parent"), "tPM")
            self.assertTrue(made_info.raw.get("keep"))
            detached = ctx_tabs.hc("run", "--bg", "--parent", "tPM", "--no-parent", "--", "claude")
            self.assertNotIn("parent", detached)
            self.assertTrue(ctx_tabs.hc.worker_tab("tW", "demo-1", "tW-fix", parent="demo-0", caller_pane="hc:tPM"))
            self.assertEqual(ctx_tabs.hc.tab_names.get("tW"), "tW-fix")
            self.assertEqual(ctx_tabs.hc.get("tW").label("herdr.space"), "sp-7")
            hc_core_rename = FakeHc({"t2": {"state": "live"}}, app_available=False, config={"tabs": {"rename_via_core": True}})
            self.assertTrue(hc_core_rename.name_tab("t2", "t2-via-core"))
            self.assertEqual(hc_core_rename.tab_names.get("t2"), "t2-via-core")

            # FakeTui port contract + TuiHost None semantics when server is unavailable
            self.assertEqual(ctx.tui.pane_get("w1:p1", session="s1")["pane_id"], "w1:p1")
            self.assertEqual(ctx.tui.pane_process_info("w1:p1", session="s1"), {"pid": 555})
            self.assertEqual(ctx.tui.strict("agent", "list", session="s1")["agents"][0]["name"], "pm-demo")
            self.assertEqual(ctx.tui.agent_send_keys("w1:p1", "esc", session="s1"), {"ok": True})
            self.assertEqual(ctx.tui.agent_start("w-2", kind="claude", pane="w1:p2", argv=["--model", "opus"], session="s1")["ok"], True)
            with self.assertRaises(errors.IdentityError):
                ctx.tui.strict("unknown", "cmd")
            down_tui = tui_mod.TuiHost(runner=lambda *a, session=None: None)
            self.assertIsNone(down_tui.panes())
            self.assertIsNone(down_tui.workspaces())
            self.assertIsNone(down_tui.worktrees())

            # make_ctx wires StubGit with honest stateful booleans and rev_parse/merge ancestry
            self.assertIsInstance(ctx.git, StubGit)
            self.assertFalse(ctx.git.branch_exists("/repo", "dev/b"))
            self.assertIsNone(ctx.git.rev_parse("/repo", "dev/b", quiet=True))
            self.assertEqual(len(ctx.git.rev_parse("/repo", "HEAD") or ""), 40)
            self.assertEqual(len(ctx.git.rev_parse("/repo", "HEAD", short=True) or ""), 7)
            self.assertTrue(ctx.git.is_ancestor("/repo", "HEAD", "HEAD"))
            self.assertFalse(ctx.git.is_ancestor("/repo", "dev/b", "main"))
            self.assertFalse(ctx.git.is_ignored("/repo", "evidence/__probe__"))
            self.assertFalse(ctx.git.has_tracked_changes("/repo"))
            self.assertTrue(ctx.git.worktree_add("/repo", Path(td) / "worktrees" / "repo" / "b", "dev/b", "main"))
            self.assertTrue(ctx.git.branch_exists("/repo", "dev/b"))
            self.assertIsNotNone(ctx.git.rev_parse("/repo", "dev/b^{commit}", quiet=True))
            self.assertTrue(ctx.git.is_owned_worktree(Path(td) / "worktrees" / "repo" / "b"))
            self.assertEqual(ctx.git.merge_no_commit("/repo", "dev/b").ok, True)
            self.assertEqual(ctx.git.commit("/repo", "msg").ok, True)
            self.assertTrue(ctx.git.is_ancestor("/repo", "dev/b", "main"))
            self.assertTrue(ctx.git.is_ancestor("/repo", "dev/b", "HEAD"))
            self.assertTrue(ctx.git.delete_branch("/repo", "dev/b"))
            self.assertFalse(ctx.git.branch_exists("/repo", "dev/b"))
            self.assertIsNone(ctx.git.rev_parse("/repo", "dev/b", quiet=True))
            self.assertFalse(ctx.git.delete_branch("/repo", "dev/b"))

    def test_terminal_info_from_hc_ls_string_status(self):
        """Finding P5: real `hc ls --json` emits `status` as a string (e.g. `'working'`),
        not a dict, so `TerminalInfo.from_dict` populates `agent_state` and `has_status`."""
        ls_row = {"address": "t182", "agent": "agy", "cwd": "/tmp/demo", "state": "live", "status": "working", "turn": 3}
        info = hc_mod.TerminalInfo.from_dict(ls_row)
        self.assertEqual(info.agent_state, "working")
        self.assertTrue(info.has_status)


if __name__ == "__main__":
    unittest.main()
