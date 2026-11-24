"""Who is calling pm.py, and what the commands that depend on it do (Stage 6a, wave 6a3).

Moved from test_pm.py's DevMachine (guard, watch, notify, launch and codex-cmd from the earlier pm.py, with several
herdr TUI sessions repeating pane ids) and from tests/test_caller_table.py (one table per identity function over the
same situations). Every test builds its own Context with make_ctx: FakeHc for herdr-core, a FakeTui for the herdr
TUI sessions, a FakeClock; the commands run through cli.main on that Context (legacy_ctx.run_main), so no module
global of pm survives a test.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import FakeHc, FakeTui, make_ctx, run_main  # noqa: E402
from pmlib import caller as caller_mod, cli, hooks  # noqa: E402
from pmlib.caller import Caller  # noqa: E402
from pmlib.context import StdOutput  # noqa: E402
from pmlib.discord import DiscordMirror  # noqa: E402
from pmlib.errors import IdentityError  # noqa: E402
from pmlib.events.inbox import InboxWatcher  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.events.policy import wake_fields_for  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.project.project import ProjectRegistry  # noqa: E402
from pmlib.workers.dispatch import worker_argv_for  # noqa: E402
from pmlib.workers.sessions import worker_task_for_hook_for  # noqa: E402
from pmlib import compat, procs as procs_mod  # noqa: E402

def no_host_commands(real_run=subprocess.run):
    """subprocess.run that refuses herdr, hc and herdr-app (every host call goes through the fakes) and runs git."""
    def run(argv, **kw):
        if argv and argv[0] in ("herdr", "hc", "herdr-app"):
            raise AssertionError(f"unexpected command {argv}")
        return real_run(argv, **kw)
    return mock.patch.object(subprocess, "run", run)


class SessionTui(FakeTui):
    """The herdr TUI of several sessions that repeat pane ids: `rows()` gives session -> pane -> (workspace, agent
    name, status), read at each call as the earlier fake did. A call without a session goes to `unscoped` (the
    earlier fake's "default"); agent prompts are read back with their session, as (session, pane, text). Everything
    else is FakeTui's."""

    def __init__(self, rows, *, unscoped="default", **kw):
        super().__init__(**kw)
        self.rows, self.unscoped = rows, unscoped

    def herdr(self, *args, session=None):
        session = session or self.unscoped
        rows = self.rows().get(session, {})
        if tuple(args[:2]) == ("agent", "list"):
            self.calls.append((session, args))
            return {"agents": [{"pane_id": p, "workspace_id": w, "name": n, "agent_status": s}
                               for p, (w, n, s) in rows.items() if n]}
        if tuple(args[:2]) == ("pane", "list"):
            self.calls.append((session, args))
            return {"panes": [{"pane_id": p, "workspace_id": w, "agent": "claude" if n else None,
                               "agent_status": s} for p, (w, n, s) in rows.items()]}
        return super().herdr(*args, session=session)

    def agents(self, *, session=None):
        return self.herdr("agent", "list", session=session)["agents"]

    def panes(self, *, session=None):
        return self.herdr("pane", "list", session=session)["panes"]

    def workspaces(self, *, session=None):
        return self.herdr("workspace", "list", session=session)["workspaces"]

    @property
    def session_prompts(self):
        return [(s, a[2], a[3]) for s, a in self.calls if tuple(a[:2]) == ("agent", "prompt")]


class DevMachine(unittest.TestCase):
    """guard, watch, launch and codex-cmd, merged from an earlier pm.py: there several herdr TUI sessions run
    at once (default, ci) and repeat pane ids, PMs keep `pm.py watch` running on their inbox, and the PMs' prompts
    call these commands as they did before the merge."""

    # What earlier PMs, briefs and hub ran with the old pm.py: every line must still parse.
    OLD_COMMAND_LINES = [
        "guard --action read", "guard --action coordinate", "guard --action implement",
        "guard --action read --repo /p", "watch", "watch --pm pm-x --timeout 5 --interval 1 --workspace w1",
        "launch --resume abc", "launch --repo /p",
        "codex-cmd --project demo-app --model gpt-6.1-sol --effort high", "codex-cmd --repo /p",
        "notify --repo /p text", "claim --repo /p --pane w1:p1 --discord-channel 1 --discord-users 2,3",
        "board", "board --post", "board --channel 1", "status", "status --all", "find --repo /p",
        "dispatch t --repo /p --branch dev/x --label l --path /w --brief b --name n --base main --prep true "
        "--kind codex --model m --effort high",
        "new t --repo /p --status proposed --owner o --workspace w --pane p --agent a --branch b --worktree w "
        "--base m --brief b --slug s --note n",
        "update i --title t --status review --owner o --workspace w --pane p --agent a --branch b --worktree w "
        "--base m --brief b --commit c --release r --note n",
        "log i text", "show i", "retire i --force", "hook-session-start", "hook-mirror",
    ]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="pm-caller-dev-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.repo = self.folder("proj")  # a plain folder: its own project
        # session -> pane -> (workspace, agent name, status); w1:p1 exists in both sessions
        self.panes = {"default": {"w1:p1": ("w1", "pm-proj", "idle"), "w2:p1": ("w2", "w-a", "working")},
                      "ci": {"w1:p1": ("w1", "someone", "idle")}}
        self.socket = "default"  # the session this process inherited
        self.hc = FakeHc()
        guard = no_host_commands()
        guard.start()
        self.addCleanup(guard.stop)
        env = mock.patch.dict(os.environ, {"HERDR_ENV": "1"})  # hooks read it from the process environment
        env.start()
        self.addCleanup(env.stop)
        self.ctx = self.make(pane="w1:p1", workspace="w1")
        self.register("proj", pane="w1:p1", workspace="w1", session="default")

    def folder(self, name):
        path = Path(tempfile.mkdtemp(dir=self.base)).resolve() / name
        path.mkdir()
        return str(path)

    def tui(self):
        """The herdr TUI over self.panes, with the socket this process inherited."""
        return SessionTui(
            lambda: self.panes,
            workspaces=[{"workspace_id": "w1", "label": "proj"}, {"workspace_id": "w2", "label": "x"}],
            sessions=[{"name": n, "socket_path": f"/s/{n}.sock", "running": True} for n in ("default", "ci")],
            current_session=self.socket)

    def make(self, *, pane="", workspace="", hc_terminal="", herdr_env="1", tui=None):
        env = {"HERDR_ENV": herdr_env}
        if pane and not pane.startswith("hc:"):
            env["HERDR_PANE_ID"] = pane
        ctx = make_ctx(self.base, pane=pane, workspace=workspace, hc_terminal=hc_terminal, hc=self.hc,
                       tui=tui or self.tui(), out=StdOutput(), env=env)
        self.ctx = ctx
        return ctx

    def again(self, **kw):
        """A fresh Context for the next command, in the same terminal unless kw says otherwise (the TUI as now)."""
        old = self.ctx
        args = {"pane": old.pane, "workspace": old.workspace, "hc_terminal": old.hc_terminal,
                "herdr_env": old.env.get("HERDR_ENV", ""), **kw}
        return self.make(**args)

    def register(self, slug, repo=None, **fields):
        home = self.ctx.home
        home.registrations.mkdir(parents=True, exist_ok=True)
        rec = {"project": slug, "repo": repo or self.repo, "name": f"pm-{slug}", **fields}
        home.registration(slug).write_text(json.dumps(rec))  # the folder is named as the project
        return rec

    def run_main(self, *argv):
        return run_main(self.again(), *argv)

    def test_the_old_command_lines_still_parse(self):
        parser = cli.build_parser()
        for line in self.OLD_COMMAND_LINES:
            with self.subTest(line=line):
                parser.parse_args(shlex.split(line))

    def test_guard_names_the_pm_and_refuses_what_its_role_may_not_do(self):
        code, out, _ = self.run_main("guard", "--action", "coordinate", "--repo", self.repo)
        self.assertEqual(code, 0)
        role = json.loads(out)
        self.assertEqual((role["role"], role["caller"]), ("pm", {"session": "default", "workspace": "w1",
                                                                 "pane": "w1:p1"}))
        self.assertEqual(set(role["pm"]), {"name", "repo", "session", "workspace", "pane", "registered", "verified",
                                           "uncertain"})
        code, out, err = self.run_main("guard", "--action", "implement", "--repo", self.repo)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("PM identity check failed: PM cannot implement"))

    def test_the_same_pane_id_in_another_session_is_a_worker(self):
        self.socket = "ci"
        code, out, _ = self.run_main("guard", "--action", "implement", "--repo", self.repo)
        role = json.loads(out)
        self.assertEqual((code, role["role"], role["pm"]["name"], role["pm"]["session"]), (0, "worker", "pm-proj",
                                                                                         "default"))
        code, _, err = self.run_main("guard", "--action", "coordinate", "--repo", self.repo)
        self.assertEqual(code, 2)
        self.assertIn("only the registered PM may coordinate", err)

    def test_outside_herdr_guard_only_reads(self):
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}):
            self.again(pane="", workspace="", herdr_env="")
            code, out, _ = run_main(self.ctx, "guard", "--repo", self.repo)
            self.assertEqual((code, json.loads(out)["role"]), (0, "observer"))
            self.assertEqual(run_main(self.again(), "guard", "--action", "coordinate")[0], 2)

    def test_a_registration_of_a_session_that_is_gone_is_uncertain(self):
        self.register("proj", pane="w1:p1", workspace="w1", session="gone")
        self.panes["default"]["w1:p1"] = ("w1", "", "idle")  # a pm-proj agent here would be a second PM: refused
        code, out, _ = self.run_main("guard", "--repo", self.repo)
        self.assertEqual((code, json.loads(out)["role"]), (0, "uncertain"))
        self.assertEqual(self.run_main("guard", "--action", "implement", "--repo", self.repo)[0], 2)

    def test_desktop_app_and_archived_registrations_do_not_stop_a_tui_guard(self):
        # Neither carries a herdr workspace; the earlier inventory refused any registration without one.
        self.register("app", repo=self.folder("app"), pane="hc:t1", workspace="", runtime="hc", terminal="t1")
        self.register("old", repo=self.folder("old"), pane="w9:p1", archived="2026-11-15")
        code, out, _ = self.run_main("guard", "--action", "coordinate", "--repo", self.repo)
        self.assertEqual((code, json.loads(out)["role"]), (0, "pm"))

    def test_guard_in_the_desktop_app_asks_herdr_core(self):
        repo = self.repo
        self.register("proj", pane="hc:t1", workspace="", runtime="hc", terminal="t1")
        self.hc = FakeHc({"t1": {"state": "live", "labels": {"pm": Path(repo).name}}})
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}):
            for pane, role in (("hc:t1", "pm"), ("hc:t2", "worker")):
                ctx = self.again(pane=pane, workspace="", hc_terminal="t1", herdr_env="")
                code, out, _ = run_main(ctx, "guard", "--repo", repo)
                self.assertEqual((code, json.loads(out)["role"], json.loads(out)["pm"]["pane"]), (0, role, "hc:t1"))
                # no herdr TUI needed
                self.assertFalse([c for c in ctx.tui.calls if tuple(c[1][:2]) == ("session", "list")])
                self.assertEqual(ctx.tui.calls, [])

    def test_notify_writes_the_inbox_and_types_only_without_a_watcher(self):
        ctx = self.again(pane="w2:p1", workspace="w2")
        inbox = InboxWatcher(ctx)
        lock = inbox.watch_lock("pm-proj")
        try:
            code, out, _ = run_main(ctx, "notify", "--repo", self.repo, "done: dev/x")
        finally:
            lock.close()
        self.assertEqual(code, 0)
        self.assertIn("pm-proj has a watcher; not typing into its pane", out)
        self.assertEqual(ctx.tui.session_prompts, [])
        line = ctx.home.inbox_log("pm-proj").read_text()
        self.assertRegex(line, r"^\[from default/w2:p1 \d\d:\d\d\] done: dev/x\n$")
        ctx = self.again()
        run_main(ctx, "notify", "--repo", self.repo, "again")
        self.assertEqual(ctx.tui.session_prompts, [("default", "w1:p1", "[from default/w2:p1] again")])

    def test_notify_reaches_a_pm_in_another_session(self):
        self.socket = "ci"
        self.panes["ci"] = {"w3:p1": ("w3", "w-b", "working")}
        ctx = self.again(pane="w3:p1", workspace="w3")
        tui = ctx.tui
        # this session has no pm-proj agent (the earlier test replaced pm.agents, TuiHost.agents() without a session)
        tui.agents = lambda *, session=None: [] if session is None else SessionTui.agents(tui, session=session)
        run_main(ctx, "notify", "--repo", self.repo, "ready")
        self.assertEqual(ctx.tui.session_prompts, [("default", "w1:p1", "[from ci/w3:p1] ready")])

    def test_notify_from_another_folder_in_the_pms_workspace_reaches_that_pm(self):
        # A worker in the PM's workspace whose folder is another repository (no PM registered for it).
        self.panes["default"]["w1:p3"] = ("w1", "w-gukvm", "working")
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        gukvm = self.folder("gukvm")
        os.chdir(gukvm)  # run in that folder, without --repo
        ctx = self.again(pane="w1:p3")
        code, out, _ = run_main(ctx, "notify", "merged")
        self.assertEqual(code, 0)
        self.assertIn(f"appended to {ctx.home.inbox_log('pm-proj')}", out)
        self.assertEqual(ctx.tui.session_prompts, [("default", "w1:p1", "[from default/w1:p3] merged")])
        # --repo names a project: one without a PM is an error, never the PM of the workspace the caller runs in.
        ctx = self.again()
        code, _, _ = run_main(ctx, "notify", "--repo", gukvm, "merged")
        self.assertTrue(str(code).startswith(f"no PM for {Path(gukvm).resolve()} "), code)
        self.assertIn("not to another PM either", code)
        self.assertEqual(ctx.tui.session_prompts, [])
        self.socket = "ci"  # the same workspace id in another session is not that PM's
        self.panes["ci"]["w1:p3"] = ("w1", "w-c", "working")
        # No PM found: nothing was delivered, and notify says so (it used to exit 0, "the ledger entry is enough").
        other = self.folder("other")
        os.chdir(other)
        ctx = self.again()
        code, _, err = run_main(ctx, "notify", "x")
        self.assertTrue(str(code).startswith(f"no PM found for {Path(other).resolve()} "), code)
        self.assertIn("nothing was delivered", code)
        self.assertIn("the ledger entry stands", code)
        self.assertEqual(ctx.tui.session_prompts, [])

    def watch(self, ctx=None, **kw):
        ctx = ctx or self.again()
        a = argparse.Namespace(**{"pm": None, "repo": self.repo, "workspace": None, "timeout": 30, "interval": 0,
                                  **kw})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cli.COMMANDS["watch"][0].cmd_watch(a, ctx=ctx)
            except SystemExit as stop:
                out.write(f"exit: {stop.code}")
        return out.getvalue()

    def test_watch_wakes_on_an_inbox_line_and_keeps_its_offset(self):
        inbox = InboxWatcher(self.ctx)
        inbox.append_inbox("pm-proj", "w-old", "before the first watch")
        offset_file = self.ctx.home.inbox / "pm-proj.offset"
        offset_file.write_text(str(self.ctx.home.inbox_log("pm-proj").stat().st_size))
        inbox.append_inbox("pm-proj", "w-a", "finished")
        out = self.watch()
        self.assertRegex(out, r"^INBOX:\n\[from w-a \d\d:\d\d\] finished\r?\n$")
        self.assertEqual(offset_file.read_text(), str(self.ctx.home.inbox_log("pm-proj").stat().st_size))
        self.assertEqual(self.watch(timeout=0), "watch timeout\n")

    def test_watch_sees_a_worker_this_dispatch_started_finish(self):
        # This version's dispatch labels the worker's workspace without the pm-<project> prefix: the task names it.
        Ledger(self.ctx).save({"id": "proj-x", "title": "x", "project": "proj", "repo": self.repo,
                               "status": "in_progress", "base": "main", "workspace": "w2", "pane": "w2:p1",
                               "dispatched": True})
        ctx = self.again()
        states = iter(["working", "working", "done"])
        ctx.caller.identity_inventory()  # read before the worker's state starts to change
        herdr = ctx.tui.herdr

        def changing(*args, session=None):
            if args[:2] == ("pane", "list"):
                self.panes["default"]["w2:p1"] = ("w2", "w-a", next(states, "done"))
            return herdr(*args, session=session)
        ctx.tui.herdr = changing
        self.assertEqual(self.watch(ctx), "w2:p1 working->done\n")

    def test_a_second_watcher_is_refused(self):
        lock = InboxWatcher(self.ctx).watch_lock("pm-proj")
        try:
            self.assertIn("a watcher for pm-proj is already running", self.watch())
        finally:
            lock.close()

    def test_watch_needs_the_pm(self):
        ctx = self.again(pane="w2:p1", workspace="w2")
        with self.assertRaises(IdentityError):
            self.watch(ctx)

    def test_codex_cmd_prints_what_the_old_one_did(self):
        from pmlib import osutil
        self.register("demo-app", repo=self.folder("demo-app"), pane="w5:p1", workspace="w5", session="ci",
                      codex={"args": ["--no-daemon", "-c", 'model_provider="demo-app"'], "model_prefix": "codex/"})
        code, out, _ = self.run_main("codex-cmd", "--project", "demo-app", "--model", "gpt-6.1-sol", "--effort", "high")
        want1 = osutil.shell_join([
            "codex", "--no-daemon", "-c", 'model_provider="demo-app"', "-m", "codex/gpt-6.1-sol",
            "-c", 'model_reasoning_effort="high"',
        ], powershell=True) + "\n"
        self.assertEqual((code, out), (0, want1))
        self.ctx.home.config.write_text(json.dumps({"codex": {"args": ["-c", 'service_tier="priority"']}}))
        code, out, _ = self.run_main("codex-cmd", "--project", "proj")  # no codex block of its own
        want2 = osutil.shell_join([
            "codex", "-c", 'service_tier="priority"', "-m", "gpt-6-astra", "-c", 'model_reasoning_effort="high"',
        ], powershell=True) + "\n"
        self.assertEqual(out, want2)

    def test_codex_workers_get_the_pms_provider_settings(self):
        self.register("proj", pane="w1:p1", workspace="w1", session="default",
                      codex={"args": ["--no-daemon", "-c", 'model_provider="demo-app"'], "model_prefix": "codex/"})
        a = argparse.Namespace(kind="codex", model="gpt-6.1-sol", effort="high", advisor="", fallback="")
        ctx = self.again()
        argv = worker_argv_for(ctx, a, repo=self.repo)
        self.assertEqual(argv[:4], ["codex", "--no-daemon", "-c", 'model_provider="demo-app"'])
        self.assertIn("codex/gpt-6.1-sol", argv)
        self.assertNotIn("--no-daemon", worker_argv_for(ctx, argparse.Namespace(**{**vars(a), "kind": "claude"}),
                                                       repo=self.repo))

    def test_launch_is_plain_until_discord_is_switched_on(self):
        mcp = DiscordMirror(self.ctx).mcp_config_path(self.repo)
        mcp.parent.mkdir(parents=True, exist_ok=True)
        mcp.write_text("{}")  # left by an earlier install
        self.assertEqual(self.run_main("launch", "--repo", self.repo, "--resume", "s1")[1],
                         "claude --resume s1 <your usual flags>\n")
        self.ctx.home.config.write_text(json.dumps({"discord": True}))
        self.assertEqual(self.run_main("launch", "--repo", self.repo)[1],
                         f"claude --mcp-config {mcp} --dangerously-load-development-channels server:discord-pm "
                         "<your usual flags>\n")

    def test_without_the_switch_nothing_reaches_discord(self):
        # Configured by an earlier install, as by an earlier install: a board channel, a bound PM and a token.
        self.ctx.home.discord_config.write_text(json.dumps({"board_channel": "1"}))
        self.register("proj", pane="w1:p1", workspace="w1", session="default", discord={"channel_id": "2"})
        with mock.patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "x"}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")) as net:
            Ledger(self.ctx).save({"id": "proj-y", "title": "y", "project": "proj", "repo": self.repo,
                                   "status": "proposed", "base": "main"})
            for event in ({"hook_event_name": "UserPromptSubmit", "prompt": "你好", "cwd": self.repo},
                          {"hook_event_name": "Stop", "last_assistant_message": "好的", "cwd": self.repo}):
                ctx = self.again()
                # herdr_session "default", not in the TUI: as the earlier test pinned them
                ctx.caller = Caller(ctx, _herdr_session_fn=lambda: "default", _in_tui_fn=lambda: False)
                with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))), \
                        contextlib.redirect_stdout(io.StringIO()):
                    hooks.cmd_hook_turn(None, ctx=ctx)
            self.assertEqual(self.run_main("board", "--post")[0], 'Discord is off: set "discord": true in '
                                                                    'config.json in the ledger home to use it')
            net.assert_not_called()
        # the log still works
        self.assertEqual([e["type"] for e in Conversation(self.ctx, self.repo).events()][-2:], ["user", "pm"])

    def test_a_registration_from_another_session_is_not_this_sessions_in_hooks(self):
        def caller(session):
            return Caller(self.again(), _herdr_session_fn=lambda: session)
        self.assertIsNone(caller("ci").own_pm_record(self.repo))
        self.assertEqual(caller("default").own_pm_record(self.repo)["name"], "pm-proj")
        self.assertEqual(caller("").own_pm_record(self.repo)["name"], "pm-proj")  # unknown: as before


# ==== the identity table (from tests/test_caller_table.py) =====================================================
# Who is calling, as each of pm.py's identity answers it today: one table per function over the same situations
# (docs/design/pm-py-refactor.md, section 1.4 item 3; stage 3c). The table is the specification of today's
# behaviour, including where two functions disagree about one situation: it records what they return, not what they
# should. A change to any cell here is a change of who pm.py thinks is calling, which decides who an event reaches.
#
# Each situation is its own Context (make_ctx): its ledger (registrations and tasks), its terminal ids and
# environment, a counting FakeHc for herdr-core and a FakeTui for the herdr TUI. The functions are asked of a
# Caller built on that Context (the ones the legacy module-level wrappers forward to), wake_fields of
# events.policy.wake_rule with the project registry's app_pm (as reactions asks it), worker_task_for_hook of
# workers.sessions.worker_task_for_hook_for. Run: python3 -m unittest discover -s mods/pm-dash/skill/scripts/tests
# -p test_caller.py

# ---- the situations ---------------------------------------------------------------------------------------------
# One project, "proj" (a plain folder of that name), with a desktop-app PM in terminal tPM, unless the situation
# registers it otherwise. Tasks, the same in every situation:
#   w-1         dispatched worker's task, in progress, its worker in hc:tW (label task=w-1)
#   w-1-review  the reviewer's task of w-1, in hc:tR (label task=w-1-review)
#   p-2         a task the PM registered itself (its pane is the PM's terminal, not dispatched), in review
#   b-3         a task a worker (hc:tW) blocked
DESKTOP_PM = {"runtime": "hc", "terminal": "tPM", "pane": "hc:tPM"}
TUI_PM = {"pane": "w1:p1", "workspace": "w1", "session": "default"}

SITUATIONS = {
    # The PM's own terminal in the desktop app: live, labelled pm=proj.
    "pm": dict(env={"HC_TERMINAL": "tPM"}, registration=DESKTOP_PM,
               terminals={"tPM": {"labels": {"pm": "proj"}}}),
    # A worker the PM dispatched for w-1.
    "worker": dict(env={"HC_TERMINAL": "tW"}, registration=DESKTOP_PM,
                   terminals={"tPM": {"labels": {"pm": "proj"}}, "tW": {"labels": {"task": "w-1"}}}),
    # The reviewer the PM started for w-1.
    "reviewer": dict(env={"HC_TERMINAL": "tR"}, registration=DESKTOP_PM,
                     terminals={"tPM": {"labels": {"pm": "proj"}}, "tR": {"labels": {"task": "w-1-review"}}}),
    # A helper of w-1's worker.
    "helper": dict(env={"HC_TERMINAL": "tH"}, registration=DESKTOP_PM,
                   terminals={"tPM": {"labels": {"pm": "proj"}},
                              "tH": {"labels": {"helper": "look", "helper.of": "w-1", "helper.project": "proj"}}}),
    # A desktop-app session nobody registered: no labels, no task, no registration.
    "session": dict(env={"HC_TERMINAL": "tX"}, registration=DESKTOP_PM,
                    terminals={"tPM": {"labels": {"pm": "proj"}}, "tX": {"labels": {}}}),
    # A person at a shell: no terminal at all.
    "shell": dict(env={}, registration=DESKTOP_PM, terminals={"tPM": {"labels": {"pm": "proj"}}}),
    # The PM in a pane of the herdr terminal UI (session "default", pane w1:p1), its agent named pm-proj.
    "tui": dict(env={"HERDR_PANE": "w1:p1", "WORKSPACE": "w1", "HERDR_ENV": "1"}, registration=TUI_PM,
                agents={"w1:p1": ("w1", "pm-proj")}),
    # The registered PM terminal now holds another project's PM (herdr-core labels it pm=other).
    "moved_hc": dict(env={"HC_TERMINAL": "tPM"}, registration=DESKTOP_PM,
                     terminals={"tPM": {"labels": {"pm": "other"}}}),
    # The registered TUI pane now runs another project's agent, from another project's folder.
    "moved_tui": dict(env={"HERDR_PANE": "w1:p1", "WORKSPACE": "w1", "HERDR_ENV": "1"}, registration=TUI_PM,
                      agents={"w1:p1": ("w1", "pm-other")}, cwd="other"),
}

# ---- what each function returns today ---------------------------------------------------------------------------
# A value is (what the function returned, reduced to what tells the situations apart: a registration by its name, a
# task by its id; how many times it called hc).
#
# Behavior notes (updated in Stage 7a, section 5.3):
# - moved_hc, moved_tui: guard (check_role) says "uncertain", while manages, is_pm_caller, own_pm_record,
#   own_registration, role_in ("session"), memory_writer ("other"), _helper_caller_identity ("worker_unknown")
#   and wake_fields (source "session") no longer mistake the moved terminal for proj's PM; pm_record_for_pane
#   and workspace_registration remain raw record lookups.
# - helper: guard says "worker", role_in says "helper", memory_writer says ("helper", "helper:<name>"), wake_fields
#   writes source "helper" (waking on reports like a worker), and _helper_caller_identity says "helper".
# - reviewer: own_task, memory_writer and wake_fields call it the worker of w-1-review; guard calls it "worker".
# - session (an unregistered desktop-app terminal): guard "worker", memory_writer "other", _helper_caller_identity
#   "worker_unknown", wake_fields "session".
# - shell: guard "observer", hc_role "worker", memory_writer "user", wake_fields "session".
# - tui: hc_role (asked directly) "uncertain" where check_role says "pm".
# - blocked_by_worker is relative to the caller: the worker that blocked b-3 itself gets False, everyone else True.
EXPECTED = {
    'check_role': {'pm': (('pm', 'pm-proj'), 1),
                   'worker': (('worker', 'pm-proj'), 1),
                   'reviewer': (('worker', 'pm-proj'), 1),
                   'helper': (('worker', 'pm-proj'), 1),
                   'session': (('worker', 'pm-proj'), 1),
                   'shell': (('observer', None), 0),
                   'tui': (('pm', 'pm-proj'), 0),
                   'moved_hc': (('uncertain', 'pm-proj'), 2),
                   'moved_tui': (('uncertain', 'pm-proj'), 0)},
    'hc_role': {'pm': (('pm', 'pm-proj'), 1),
                'worker': (('worker', 'pm-proj'), 1),
                'reviewer': (('worker', 'pm-proj'), 1),
                'helper': (('worker', 'pm-proj'), 1),
                'session': (('worker', 'pm-proj'), 1),
                'shell': (('worker', 'pm-proj'), 1),
                'tui': (('uncertain', 'pm-proj'), 0),
                'moved_hc': (('uncertain', 'pm-proj'), 2),
                'moved_tui': (('uncertain', 'pm-proj'), 0)},
    'app_caller': {'pm': (True, 0),
                   'worker': (True, 0),
                   'reviewer': (True, 0),
                   'helper': (True, 0),
                   'session': (True, 0),
                   'shell': (False, 0),
                   'tui': (False, 0),
                   'moved_hc': (True, 0),
                   'moved_tui': (False, 0)},
    'in_tui': {'pm': (False, 0),
               'worker': (False, 0),
               'reviewer': (False, 0),
               'helper': (False, 0),
               'session': (False, 0),
               'shell': (False, 0),
               'tui': (True, 0),
               'moved_hc': (False, 0),
               'moved_tui': (True, 0)},
    'is_pm_caller': {'pm': (True, 1),
                     'worker': (False, 0),
                     'reviewer': (False, 0),
                     'helper': (False, 0),
                     'session': (False, 0),
                     'shell': (False, 0),
                     'tui': (True, 0),
                     'moved_hc': (False, 1),
                     'moved_tui': (False, 0)},
    'pm_record_for_pane': {'pm': ('pm-proj', 0),
                           'worker': (None, 0),
                           'reviewer': (None, 0),
                           'helper': (None, 0),
                           'session': (None, 0),
                           'shell': (None, 0),
                           'tui': ('pm-proj', 0),
                           'moved_hc': ('pm-proj', 0),
                           'moved_tui': ('pm-proj', 0)},
    'own_pm_record': {'pm': ('pm-proj', 1),
                      'worker': (None, 0),
                      'reviewer': (None, 0),
                      'helper': (None, 0),
                      'session': (None, 0),
                      'shell': (None, 0),
                      'tui': ('pm-proj', 0),
                      'moved_hc': (None, 1),
                      'moved_tui': (None, 0)},
    'own_registration': {'pm': ('pm-proj', 1),
                         'worker': (None, 0),
                         'reviewer': (None, 0),
                         'helper': (None, 0),
                         'session': (None, 0),
                         'shell': (None, 0),
                         'tui': ('pm-proj', 0),
                         'moved_hc': (None, 1),
                         'moved_tui': (None, 0)},
    'current_pm_record': {'pm': ('pm-proj', 1),
                          'worker': ('pm-proj', 0),
                          'reviewer': ('pm-proj', 0),
                          'helper': ('pm-proj', 0),
                          'session': ('pm-proj', 0),
                          'shell': ('pm-proj', 0),
                          'tui': ('pm-proj', 0),
                          'moved_hc': ('pm-proj', 1),
                          'moved_tui': ('pm-proj', 0)},
    'workspace_registration': {'pm': (None, 0),
                               'worker': (None, 0),
                               'reviewer': (None, 0),
                               'helper': (None, 0),
                               'session': (None, 0),
                               'shell': (None, 0),
                               'tui': ('pm-proj', 0),
                               'moved_hc': (None, 0),
                               'moved_tui': ('pm-proj', 0)},
    'own_task': {'pm': (None, 1),
                 'worker': ('w-1', 1),
                 'reviewer': ('w-1-review', 1),
                 'helper': (None, 1),
                 'session': (None, 1),
                 'shell': (None, 0),
                 'tui': (None, 0),
                 'moved_hc': (None, 1),
                 'moved_tui': (None, 0)},
    'caller_projects': {'pm': (['proj'], 1),
                        'worker': (['proj'], 1),
                        'reviewer': (['proj'], 1),
                        'helper': ([], 1),
                        'session': ([], 1),
                        'shell': ([], 0),
                        'tui': (['proj'], 0),
                        'moved_hc': ([], 1),
                        'moved_tui': ([], 0)},
    'caller_projects:first': {'pm': ('proj', 1),
                              'worker': ('proj', 1),
                              'reviewer': ('proj', 1),
                              'helper': (None, 1),
                              'session': (None, 1),
                              'shell': (None, 0),
                              'tui': ('proj', 0),
                              'moved_hc': (None, 1),
                              'moved_tui': (None, 0)},
    'worker_task_for_hook': {'pm': ((None, False), 0),
                             'worker': (('w-1', True), 1),
                             'reviewer': (('w-1-review', True), 1),
                             'helper': ((None, False), 1),
                             'session': ((None, False), 1),
                             'shell': ((None, False), 0),
                             'tui': ((None, False), 0),
                             'moved_hc': ((None, False), 0),
                             'moved_tui': ((None, False), 0)},
    'memory_writer': {'pm': (('pm', 'pm'), 1),
                      'worker': (('worker', 'worker:w-1'), 1),
                      'reviewer': (('worker', 'worker:w-1-review'), 1),
                      'helper': (('helper', 'helper:look'), 1),
                      'session': (('other', 'session:hc:tX'), 1),
                      'shell': (('user', 'user'), 0),
                      'tui': (('pm', 'pm'), 0),
                      'moved_hc': (('other', 'session:hc:tPM'), 1),
                      'moved_tui': (('other', 'session:w1:p1'), 0)},
    'helper_self_info': {'pm': (None, 1),
                         'worker': (None, 1),
                         'reviewer': (None, 1),
                         'helper': ({'of': 'w-1', 'name': 'look', 'project': 'proj', 'terminal': 'tH'}, 1),
                         'session': (None, 1),
                         'shell': (None, 0),
                         'tui': (None, 0),
                         'moved_hc': (None, 1),
                         'moved_tui': (None, 0)},
    '_helper_caller_identity': {'pm': (('pm', 'pm-proj'), 1),
                                'worker': (('task', 'w-1'), 1),
                                'reviewer': (('task', 'w-1-review'), 1),
                                'helper': (('helper', 'look'), 1),
                                'session': (('worker_unknown', None), 1),
                                'shell': (('cli', None), 0),
                                'tui': (('pm', 'pm-proj'), 0),
                                'moved_hc': (('worker_unknown', None), 1),
                                'moved_tui': (('worker_unknown', None), 0)},
    'blocked_by_worker': {'pm': (True, 0),
                          'worker': (False, 0),
                          'reviewer': (True, 0),
                          'helper': (True, 0),
                          'session': (True, 0),
                          'shell': (True, 0),
                          'tui': (True, 0),
                          'moved_hc': (True, 0),
                          'moved_tui': (True, 0)},
    'wake_fields:own': {'pm': ({'source': 'pm', 'wake': False}, 1),
                        'worker': ({'source': 'worker', 'wake': True}, 0),
                        'reviewer': ({'source': 'worker', 'from_task': 'w-1-review', 'wake': True}, 1),
                        'helper': ({'source': 'helper', 'wake': True}, 1),
                        'session': ({'source': 'session', 'wake': True}, 1),
                        'shell': ({'source': 'session', 'wake': True}, 0),
                        'tui': ({'source': 'pm'}, 0),
                        'moved_hc': ({'source': 'session', 'wake': True}, 1),
                        'moved_tui': ({'source': 'session'}, 0)},
    'wake_fields:registered': {'pm': ({'source': 'pm', 'wake': False}, 1),
                               'worker': ({'source': 'worker', 'from_task': 'w-1', 'wake': True}, 1),
                               'reviewer': ({'source': 'worker', 'from_task': 'w-1-review', 'wake': True}, 1),
                               'helper': ({'source': 'helper', 'wake': True}, 1),
                               'session': ({'source': 'session', 'wake': False}, 1),
                               'shell': ({'source': 'session', 'wake': False}, 0),
                               'tui': ({'source': 'pm'}, 0),
                               'moved_hc': ({'source': 'session', 'wake': False}, 1),
                               'moved_tui': ({'source': 'session'}, 0)},
}




class CountingHc(FakeHc):
    """FakeHc that counts every look at herdr-core, whichever port method makes it (`looks`)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.looks = []

    def hc(self, *args, **kw):
        if args[:1] not in (("get",), ("ls",)):
            self.looks.append(args)
        return super().hc(*args, **kw)

    def get_raw(self, term, **kw):
        self.looks.append(("get", term))
        return super().get_raw(term, **kw)

    def _ls_raw(self, **kw):
        self.looks.append(("ls",))
        return super()._ls_raw(**kw)


class CallerTable(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="pm-caller-table-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "proj"
        self.other = self.root / "other"
        self.repo.mkdir()
        self.other.mkdir()
        guard = no_host_commands()
        guard.start()
        self.addCleanup(guard.stop)
        self.n = 0

    def enter(self, name):
        """Build situation `name`: its own Context (ledger, terminal, environment, fake hosts) as self.ctx."""
        s = SITUATIONS[name]
        repo = str(self.repo)
        self.n += 1
        env = s["env"]
        hc_terminal = env.get("HC_TERMINAL", "")
        herdr_pane = env.get("HERDR_PANE", "")
        pane = herdr_pane or (f"hc:{hc_terminal}" if hc_terminal else "")
        ctx_env = {}
        if env.get("HERDR_ENV"):
            ctx_env["HERDR_ENV"] = env["HERDR_ENV"]
        if herdr_pane:
            ctx_env["HERDR_PANE_ID"] = herdr_pane
        terminals = {t: {"state": "live", "cwd": repo, **rec} for t, rec in s.get("terminals", {}).items()}
        self.hc = CountingHc(terminals)
        agents = s.get("agents", {})
        tui = FakeTui(
            agents=[{"pane_id": p, "workspace_id": w, "name": n, "agent_status": "idle"} for p, (w, n) in agents.items()],
            panes=[{"pane_id": p, "workspace_id": w, "agent": "claude"} for p, (w, n) in agents.items()],
            sessions=[{"name": "default", "socket_path": "/s/default.sock", "running": bool(agents)}],
            current_session="default")
        self.ctx = make_ctx(self.root / f"situation-{self.n}-{name}", pane=pane, hc_terminal=hc_terminal,
                            workspace=env.get("WORKSPACE", ""), hc=self.hc, tui=tui, env=ctx_env,
                            git=GitRepo(worktree_base=self.root / "worktrees"))
        home = self.ctx.home
        home.registrations.mkdir(parents=True, exist_ok=True)
        home.tasks.mkdir(parents=True, exist_ok=True)
        home.registration("proj").write_text(json.dumps({"project": "proj", "repo": repo, "name": "pm-proj",
                                                         **s["registration"]}))
        tasks = [
            {"id": "w-1", "project": "proj", "repo": repo, "worktree": repo, "status": "in_progress",
             "pane": "hc:tW", "dispatched": True, "number": 1, "log": []},
            {"id": "w-1-review", "project": "proj", "repo": repo, "status": "in_progress", "pane": "hc:tR",
             "review_of": "w-1", "log": []},
            {"id": "p-2", "project": "proj", "repo": repo, "status": "review", "pane": "hc:tPM", "number": 2,
             "log": []},
            {"id": "b-3", "project": "proj", "repo": repo, "status": "blocked", "pane": "hc:tW", "number": 3,
             "log": [{"by": "hc:tW", "text": "status=blocked; which way?"}]},
        ]
        for task in tasks:
            home.task(task["id"]).write_text(json.dumps(task))
        # Hooks read HERDR_ENV from the process environment: the situation's only.
        environ = {k: v for k, v in os.environ.items() if k != "HERDR_ENV"}
        environ.update({k: v for k, v in ctx_env.items() if k == "HERDR_ENV"})
        patch = mock.patch.dict(os.environ, environ, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        # The process runs from the situation's folder too: some functions look at the current folder.
        self.cwd = str(self.other if s.get("cwd") == "other" else self.repo)
        here = os.getcwd()
        os.chdir(self.cwd)
        self.addCleanup(os.chdir, here)
        return self.ctx

    # ---- one call per function, reduced to a comparable value ----

    @staticmethod
    def name(rec):
        return rec.get("name") if isinstance(rec, dict) else rec

    @staticmethod
    def tid(task):
        return task.get("id") if isinstance(task, dict) else task

    def observe(self, call):
        # Each function is asked by a Caller of its own, as each legacy wrapper built one: nothing it cached
        # (the terminal it read) is shared with the next function.
        self.ctx.caller = Caller(self.ctx)
        before = len(self.hc.looks)
        try:
            value = call()
        except IdentityError:
            value = "IdentityError"
        return value, len(self.hc.looks) - before

    def calls(self):
        """function -> zero-argument call returning the reduced value. Called inside a situation."""
        repo = str(self.repo)
        ctx = self.ctx

        def c():
            return ctx.caller

        def task(tid):
            return json.loads(ctx.home.task(tid).read_text())

        def role(result):
            return (result["role"], (result.get("pm") or {}).get("name"))

        def wake_fields(t, status, reported):
            return wake_fields_for(t, status, reported, c(), bool(ProjectRegistry(ctx).app_pm(t.get("repo"))))

        return {
            # pm.check_role forwards to Caller.check_guard
            "check_role": lambda: role(c().check_guard("read", repo)),
            "hc_role": lambda: role(c().hc_role("read", repo)),
            "app_caller": lambda: c().app_caller(),
            "in_tui": lambda: c().in_tui(),
            "is_pm_caller": lambda: c().is_pm_caller(repo=repo),
            "pm_record_for_pane": lambda: self.name(c().pm_record_for_pane(ctx.pane)),
            "own_pm_record": lambda: self.name(c().own_pm_record(self.cwd)),
            "own_registration": lambda: self.name(c().own_registration()),
            "current_pm_record": lambda: self.name(c().current_pm_record(repo=repo)),
            "workspace_registration": lambda: self.name(c().workspace_registration()),
            "own_task": lambda: self.tid(c().own_task),
            "caller_projects": lambda: list(c().caller_projects([])),
            # Read only as far as needed: the first project, as a bare `#N` asks it (it decides an hc call).
            "caller_projects:first": lambda: next(iter(c().caller_projects([])), None),
            "worker_task_for_hook": lambda: (lambda r: (self.tid(r[0]), r[1]))(
                worker_task_for_hook_for(ctx, cwd=self.cwd)),
            "memory_writer": lambda: c().memory_writer(repo),
            "helper_self_info": lambda: c().helper_self_info(),
            "_helper_caller_identity": lambda: (lambda r: (r[0], self.tid(r[1]) if r[0] == "task" else
                                                           self.name(r[1]) if r[0] == "pm" else
                                                           (r[1] or {}).get("name")))(c().helper_caller_identity()),
            "blocked_by_worker": lambda: c().blocked_by_worker(task("b-3")),
            # A report on the worker's own task, and a commit on the task the PM registered (section 5.1).
            "wake_fields:own": lambda: wake_fields(task("w-1"), "review", True),
            "wake_fields:registered": lambda: wake_fields(task("p-2"), "", True),
        }

    def observed(self):
        """situation -> function -> (value, hc looks)."""
        table = {}
        for name in SITUATIONS:
            self.enter(name)
            table[name] = {fn: self.observe(call) for fn, call in self.calls().items()}
        return table

    def test_the_table_covers_every_function_and_situation(self):
        self.enter("pm")
        self.assertEqual(set(EXPECTED), set(self.calls()))
        for fn, row in EXPECTED.items():
            self.assertEqual(set(row), set(SITUATIONS), fn)

    def test_caller_caches_identity_inventory_per_instance(self):
        # A Caller of a Context keeps its own: it reads the inventory once, a new Caller reads it again.
        ctx = self.enter("tui")
        caller = Caller(ctx)
        first = caller.identity_inventory()
        self.assertIs(caller.identity_inventory(), first)
        self.assertEqual(caller.caller_identity(first)["session"], "default")
        self.assertIsNot(Caller(ctx).identity_inventory(), first)

    def test_caller_role_in_each_situation(self):
        # Stage 7a: role_in asks manages() (which verifies live host facts), then repo-scoped own_task / helper,
        # so moved_hc and moved_tui resolve to "session" while guard says "uncertain".
        roles = {
            "pm": ("manager", None, None), "worker": ("worker", "w-1", None),
            "reviewer": ("reviewer", "w-1-review", None), "helper": ("helper", None, "w-1"),
            "session": ("session", None, None), "shell": ("user", None, None), "tui": ("manager", None, None),
            "moved_hc": ("session", None, None), "moved_tui": ("session", None, None),
        }
        for situation, expected in roles.items():
            with self.subTest(situation=situation):
                ctx = self.enter(situation)
                caller = Caller(ctx)
                self.assertEqual(self.hc.looks, [])  # building one looks at nothing
                env = SITUATIONS[situation]["env"]
                pane = env.get("HERDR_PANE") or (f"hc:{env['HC_TERMINAL']}" if env.get("HC_TERMINAL") else "")
                self.assertEqual((caller.pane, caller.terminal, caller.workspace),
                                 (pane, env.get("HC_TERMINAL", ""), env.get("WORKSPACE", "")))
                role = caller.role_in(str(self.repo))
                self.assertEqual((role.kind, role.task, role.owner), expected)
                self.assertEqual(role.kind, caller.role_in(str(self.repo)).kind)

    def test_caller_reads_the_terminal_once(self):
        ctx = self.enter("worker")
        caller = Caller(ctx)
        self.assertEqual(caller.labels, {"task": "w-1"})
        self.assertEqual(caller.own_task["id"], "w-1")
        self.assertEqual(len(self.hc.looks), 1)  # single hc get shared by labels, own_task, and helper
        caller.labels, caller.own_task, caller.helper
        self.assertEqual(len(self.hc.looks), 1)
        caller.labels, caller.own_task, caller.helper
        self.assertEqual(len(self.hc.looks), 1)
        ctx = self.enter("shell")
        caller = Caller(ctx)
        self.assertEqual((caller.labels, caller.own_task, caller.helper), ({}, None, None))
        self.assertEqual(self.hc.looks, [])
        # A Caller follows its Context: no Caller is kept for the process.
        ctx = self.enter("pm")
        self.assertEqual(Caller(ctx).terminal, "tPM")
        self.assertEqual(Caller.from_context(ctx).terminal, "tPM")

    def test_a_bare_number_asks_caller_projects_by_name_and_lazily(self):
        # The ledger asks the Context's caller_projects when it runs, and reads it only as far as needed: the PM's
        # own project verifies its live hc label with at most one hc.get call.
        ctx = self.enter("pm")
        asked = ctx.caller_projects([])
        self.assertEqual((next(asked), self.hc.looks), ("proj", [("get", "tPM")]))

    def test_each_function_answers_each_situation_as_recorded(self):
        table = self.observed()
        if os.environ.get("PRINT_CALLER_TABLE"):
            import pprint
            pprint.pprint({fn: {s: table[s][fn] for s in SITUATIONS} for fn in table["pm"]}, width=118,
                          sort_dicts=False)
        for fn, expected in EXPECTED.items():
            for situation, (value, hc_calls) in expected.items():
                with self.subTest(function=fn, situation=situation):
                    self.assertEqual(table[situation][fn], (value, hc_calls))


if __name__ == "__main__":
    unittest.main()
