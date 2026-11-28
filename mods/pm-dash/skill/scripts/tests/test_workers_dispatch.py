"""Worker dispatch, brief delivery, profiles, outside reads, tabs, take-up and deep pre-approval tests
migrated from `test_pm.py` onto per-test `make_ctx` + `fakes.py` (Stage 6b1)."""
from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import json
import os
from pathlib import Path
import re
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

from fakes import FakeClock, FakeHc, FakeProcs, FakeTui, make_ctx  # noqa: E402
from pmlib import cli, hooks as hooks_mod  # noqa: E402
from pmlib.agents import base as agents_base, profiles as profiles_mod, reads as reads_mod  # noqa: E402
from pmlib.agents.registry import AgentRegistry  # noqa: E402
from pmlib.commands import dispatch as dispatch_cmd, ledger as ledger_cmd, review as review_cmd, workers as workers_cmd  # noqa: E402
from pmlib.context import StdOutput  # noqa: E402
from pmlib.errors import Refused  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.task import Task  # noqa: E402
from pmlib.ledger.transition import FIELDS  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import project_slug  # noqa: E402
from pmlib.project.readmodel import answered_tasks  # noqa: E402
from pmlib.review.review import Reviews  # noqa: E402
from pmlib.store import FileStore  # noqa: E402
from pmlib.terminals import hc as hc_mod, screen as screen_mod, tabs as tabs_mod  # noqa: E402
from pmlib.terminals.hc import HcHost  # noqa: E402
from pmlib.views import state as state_view  # noqa: E402
from pmlib.workers import (  # noqa: E402
    codex_pool,
    dispatch as workers_dispatch,
    escalate as workers_escalate,
    reattach as workers_reattach,
    sessions as workers_sessions,
)
from pmlib.workers.service import Workers  # noqa: E402


CLAUDE_TRUST = """ Accessing workspace:

 /Users/me/.herdr/worktrees/app/dev-x

 Quick safety check: Is this a project you created or one you trust?

 ❯ No, exit
   Yes, I trust this folder

 Enter to confirm · Esc to cancel"""
CODEX_TRUST = """> You are in ~/.herdr/worktrees/app/dev-x

  Do you trust the contents of this directory?

› 1. Yes, continue
  2. No, quit"""
OTHER_DIALOG = """ New MCP server found in .mcp.json: tools

 ❯ 1. Use this and all future MCP servers in this project
   2. Continue without using this MCP server"""

POLICY = {
    "codex": {
        "projects": ["proj"],
        "profiles": [{"name": "team-a", "max": 2, "fast": True}, {"name": "team-b", "max": 3, "fast": True}],
        "allow_default": False,
        "model": "codex-model",
        "review_model": "review-model",
        "effort": "high",
        "fallback": {
            "worker": {"kind": "claude", "model": "opus", "effort": "high"},
            "reviewer": {"kind": "claude", "model": "fable", "effort": "high"},
        },
    },
    "claude": {"launcher": ["zsh", "-ic", "my-claude --yes {args}"], "effort": "high", "fable_fallback": "opus"},
    "tabs": {"max": 20, "review": "审查", "bug_pattern": r"(?<![0-9])#?([0-9]{5})(?![0-9])"},
}


def make_repo(parent: Path | None = None):
    """A real git repository with one commit on main and one commit on dev/x."""
    if parent is None:
        repo = Path(tempfile.mkdtemp()).resolve() / "app"
    else:
        repo = parent.resolve() / "app"
    repo.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
        ).stdout

    git("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("base\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "dev/x")
    (repo / "x.txt").write_text("feature\n")
    git("add", "x.txt")
    git("commit", "-q", "-m", "add x.txt")
    git("checkout", "-q", "main")
    return repo, git


def init_empty_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
    )
    return path


class _FrameHc(FakeHc):
    """FakeHc whose terminal frames advance on each clock sleep, recording keys and sends."""

    def __init__(self, frames, *, clock: FakeClock, config=None):
        super().__init__(clock=clock, config=config)
        self._frames = frames
        self.seen: list = []
        self._look = 0

    def advance_frame(self):
        self._look += 1

    def _frame(self):
        return self._frames[min(self._look, len(self._frames) - 1)]

    def get_raw(self, term: str, *, errors: bool = False):
        return {"address": term, "id": term, "state": "live", "status": self._frame()[0]}

    def _read_raw(self, term: str, *, lines=None, errors: bool = False):
        return {"text": self._frame()[1]}

    def keys(self, term: str, *keys: str, errors: bool = False):
        self.seen.append(list(keys))
        return {"status": None}

    def send(self, term: str, text: str, *, if_state=None, timeout: float = 180, errors: bool = False):
        self.seen.append("sent")
        return {"started": True}

    def run(self, argv, *, name="", cwd="", labels=(), bg=True, parent="", keep=False, no_parent=False, placement=(), env=None):
        return {"address": "t9", "id": "t9", "state": "live"}


class _ScriptedDispatchHc(FakeHc):
    """FakeHc matching Profiles.dispatching: sequential t1/t2/... addresses, mutable terminal states,
    interrupt transitions working->live, and full hc call recording."""

    def __init__(self, *, terminals=None, screens=None, clock=None, config=None):
        super().__init__(clock=clock, config=config)
        self.states: dict[str, str] = dict(terminals or {})
        self.screens: dict[str, str] = dict(screens or {})
        self.labels_map: dict[str, dict[str, str]] = {}
        self.raw_calls: list[tuple] = []
        self._run_count = 0

    def _record(self, *args):
        self.raw_calls.append(tuple(args))

    def hc(self, *args, errors: bool = False, env=None, timeout: float = 60):
        self._record(*args)
        return self._dispatch_raw(*args)

    def _dispatch_raw(self, *args):
        if args[0] == "run":
            self._run_count += 1
            addr = f"t{self._run_count}"
            self.states.setdefault(addr, "live")
            return {"address": addr}
        if args[0] == "label":
            self.labels_map.setdefault(args[1], {}).update(x.split("=", 1) for x in args[2:])
            return {}
        addr = args[1] if len(args) > 1 else ""
        state = self.states.get(addr, "live")
        live = state in ("live", "working")
        if args[0] == "interrupt" and state == "working":
            self.states[addr] = "live"
        if args[0] == "get":
            base = {"state": "live", "status": {"state": "working" if state == "working" else "idle"}} if live else {"state": state}
            return {**base, "labels": dict(self.labels_map.get(addr, {})), "address": addr}
        if args[0] == "read":
            return {"text": self.screens.get(addr, "❯ ")}
        if args[0] == "send":
            return {"started": live}
        return {}

    def run(self, argv, *, name="", cwd="", labels=(), bg=True, parent="", keep=False, no_parent=False, placement=(), env=None):
        cmd = ["run"]
        if bg:
            cmd.append("--bg")
        if name:
            cmd.extend(["--name", name])
        if cwd:
            cmd.extend(["--cwd", str(cwd)])
        for p in placement:
            cmd.append(str(p))
        if parent and not no_parent:
            cmd.extend(["--parent", parent])
        if no_parent:
            cmd.append("--no-parent")
        if keep:
            cmd.append("--keep")
        for lbl in labels:
            cmd.extend(["--label", lbl])
        cmd.append("--")
        cmd.extend(str(x) for x in argv)
        self._record(*cmd)
        return self._dispatch_raw(*cmd)

    def get_raw(self, term: str, *, errors: bool = False):
        self._record("get", term)
        return self._dispatch_raw("get", term)

    def _read_raw(self, term: str, *, lines=None, errors: bool = False):
        self._record("read", term)
        return self._dispatch_raw("read", term)

    def send(self, term: str, text: str, *, if_state=None, timeout: float = 180, errors: bool = False):
        self._record("send", term, text)
        return self._dispatch_raw("send", term, text)

    def label(self, term: str, *pairs: str, errors: bool = False):
        self._record("label", term, *pairs)
        return self._dispatch_raw("label", term, *pairs)

    def interrupt(self, term: str, *, timeout=None, errors: bool = False):
        self._record("interrupt", term)
        return self._dispatch_raw("interrupt", term)

    def kill(self, term: str, *, errors: bool = False):
        self._record("kill", term)
        return self._dispatch_raw("kill", term)

    def remove(self, term: str, *, errors: bool = False):
        self._record("rm", term)
        return self._dispatch_raw("rm", term)


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-commands-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _ctx(self, *, pane: str = "", hc=None, tui=None, config=None, git=None):
        return make_ctx(
            self.root / "ctx",
            pane=pane,
            hc=hc,
            tui=tui,
            config=config,
            git=git if git is not None else GitRepo(),
            out=StdOutput(),
        )

    def test_every_subcommand_has_its_function(self):
        source = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted(Path(inspect.getsourcefile(cli.build_parser)).parent.rglob("*.py"))
        )
        names = re.findall(r'\bsub\.add_parser\("([\w-]+)"', source)
        names += re.findall(r'\("(archive|restore)", "', source)
        self.assertIn("rotate", names)
        missing = [
            n for n in names
            if n not in cli.COMMANDS or not hasattr(cli.COMMANDS[n][0], cli.COMMANDS[n][1])
        ]
        self.assertEqual(missing, [])

    def test_hc_json_flag_stays_out_of_the_started_program(self):
        ctx = self._ctx()
        seen = []
        host = HcHost(ctx.config)
        with mock.patch.object(
            hc_mod.subprocess, "run",
            side_effect=lambda argv, **kw: seen.append(argv) or type("R", (), {"returncode": 0, "stdout": "{}"})(),
        ):
            host.call("run", "--bg", "--", "codex", "-m", "x")
            host.call("get", "t1")
        self.assertEqual(
            seen,
            [["hc", "run", "--bg", "--json", "--", "codex", "-m", "x"], ["hc", "get", "t1", "--json"]],
        )

    def test_the_pm_tab_is_named_after_the_project(self):
        ctx = self._ctx()
        listing = {
            "spaces": [
                {
                    "tabs": [
                        {"id": "tb1", "name": "PM-app", "terminals": [{"terminal": "t1"}]},
                        {"id": "tb2", "name": "3", "terminals": [{"terminal": "t2"}]},
                    ]
                }
            ]
        }
        seen = []
        host = HcHost(
            ctx.config,
            app_runner=lambda *args, **kw: seen.append(list(args)) or type(
                "R", (), {"returncode": 0, "stdout": json.dumps(listing)}
            )(),
        )
        host.name_tab("t2", tabs_mod.pm_tab_name("/x/app"))   # the new PM's tab
        host.name_tab("t1", "", only_if="PM-app")             # the old PM's tab gets its number back
        host.name_tab("t2", "", only_if="PM-app")             # a tab the user named otherwise is left alone
        host.name_tab("t9", "PM-app")                         # no tab (a sub-agent): nothing
        renames = [json.loads(a[2]) for a in seen if a[0] == "do"]
        self.assertEqual(renames, [{"id": "tb2", "name": "PM-app"}, {"id": "tb1", "name": ""}])

    def test_worker_is_a_sub_agent_that_outlives_the_pm(self):
        ctx = self._ctx(pane="hc:t9")
        self.assertEqual(
            workers_dispatch.worker_placement_for(ctx),
            ["--parent", "t9", "--outlive-parent", "--no-notify"],
        )

    def test_merging_a_dispatched_task_retires_it(self):
        repo = str(self.root / "repo-auto")
        Path(repo).mkdir()
        ctx = self._ctx()
        ledger = Ledger(ctx)
        base = {
            "project": "p", "repo": repo, "status": "in_progress", "owner": "pm",
            "base": "main", "created": ctx.clock.now(), "title": "t",
        }
        ledger.save({**base, "id": "p-auto", "dispatched": True})
        ledger.save({**base, "id": "p-kept", "dispatched": True, "branch": "dev/x"})
        ledger.save({**base, "id": "p-own", "branch": "dev/y"})
        args = lambda id, keep=False: type("A", (), {"id": id, "status": "merged", "note": None, "keep": keep})
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmd.cmd_update(args("p-auto"), ctx=ctx)
            ledger_cmd.cmd_update(args("p-kept", keep=True), ctx=ctx)
            ledger_cmd.cmd_update(args("p-own"), ctx=ctx)
        self.assertTrue(ledger.load("p-auto").get("retired"))
        self.assertFalse(ledger.load("p-kept").get("retired"))
        self.assertFalse(ledger.load("p-own").get("retired"))  # not dispatched by the PM: never retired automatically
        self.assertTrue(ledger.load("p-kept").needs_cleanup)
        self.assertFalse(ledger.load("p-auto").needs_cleanup)

    def test_retire_removes_the_worktree_a_worker_made_itself(self):
        # `pm.py new --branch` records no worktree: retire finds the checkout that has the branch.
        repo = (self.root / "app-own").resolve()
        tree = self.root.resolve() / "tree"
        git = lambda *args: subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True, capture_output=True, text=True,
        ).stdout
        repo.mkdir()
        git("init", "-q", "-b", "main")
        git("commit", "-q", "--allow-empty", "-m", "init")
        git("worktree", "add", "-q", "-b", "dev/own", str(tree), "main")
        git("branch", "dev/here")
        calls = []
        terminal = {"state": "live", "cwd": str(tree / "src")}

        class _OwnHc(FakeHc):
            def get_raw(self, term, *, errors=False):
                calls.append("get")
                return {**terminal, "address": term}

            def kill(self, term, *, errors=False):
                calls.append("kill")
                return None

            def remove(self, term, *, errors=False):
                calls.append("rm")
                return None

        ctx = self._ctx(hc=_OwnHc(), tui=FakeTui(server_ok=False))
        ledger = Ledger(ctx)
        base = {
            "project": "app", "repo": str(repo), "status": "merged", "owner": "self",
            "base": "main", "created": ctx.clock.now(), "title": "t",
        }
        ledger.save({**base, "id": "app-own", "branch": "dev/own", "pane": "hc:t7"})
        ledger.save({**base, "id": "app-own-2", "branch": "dev/own", "pane": "hc:t7"})
        ledger.save({**base, "id": "app-here", "branch": "dev/here"})

        def retire(task_id):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                try:
                    workers_cmd.cmd_retire(type("A", (), {"id": task_id, "force": False}), ctx=ctx)
                except SystemExit as stop:
                    return f"refused: {stop}"
            return out.getvalue()

        self.assertIn("another task still uses it", retire("app-own"))  # the last task on the branch removes it
        self.assertTrue(tree.is_dir())
        # The session that owns the task still sits in the worktree: its directory and its terminal both stay.
        self.assertEqual(
            retire("app-own-2").replace("/", os.sep),
            f"refused: worktree {tree} is kept: hc:t7 still works in it",
        )
        self.assertTrue(tree.is_dir())
        self.assertFalse(ledger.load("app-own-2").get("retired"))
        terminal["cwd"] = str(repo)  # the session has left the worktree
        said = retire("app-own-2")
        self.assertIn(f"removed worktree {tree}, branch dev/own", said.replace(tree.as_posix(), str(tree)))
        self.assertFalse(tree.exists())
        self.assertEqual(git("branch", "--list", "dev/own"), "")
        self.assertEqual(set(calls), {"get"})  # no terminal was ended or removed
        # A branch that is checked out in the main checkout stays, and retire says where.
        git("checkout", "-q", "dev/here")
        self.assertIn(
            f"removed nothing; branch dev/here is kept: checked out in {repo}",
            retire("app-here").replace(repo.as_posix(), str(repo)),
        )
        self.assertTrue(repo.is_dir())
        self.assertNotEqual(git("branch", "--list", "dev/here"), "")

    def test_retire_checks_main_once_the_base_branch_is_deleted(self):
        repo, git = make_repo(self.root / "repo-del-base")
        git("branch", "dev/old")
        git("merge", "-q", "--no-ff", "dev/x", "-m", "merge dev/x")
        git("branch", "-q", "dev/y", "dev/old")
        git("checkout", "-q", "dev/y")
        (repo / "y.txt").write_text("y\n")
        git("add", "y.txt")
        git("commit", "-q", "-m", "add y.txt")
        git("checkout", "-q", "main")
        git("branch", "-D", "dev/old")  # the base, merged and deleted
        ctx = self._ctx()
        ledger = Ledger(ctx)
        task = {
            "project": repo.name, "repo": str(repo), "status": "merged", "owner": "pm",
            "base": "dev/old", "created": ctx.clock.now(), "title": "t",
        }
        ledger.save({**task, "id": "gone-in", "branch": "dev/x"})
        ledger.save({**task, "id": "gone-out", "branch": "dev/y"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            workers_cmd.cmd_retire(argparse.Namespace(id="gone-in", force=False), ctx=ctx)
        self.assertIn("merged into main (dev/old no longer exists)", out.getvalue())
        self.assertEqual(git("branch", "--list", "dev/x"), "")
        with self.assertRaises(SystemExit) as stop:
            workers_cmd.cmd_retire(argparse.Namespace(id="gone-out", force=False), ctx=ctx)
        self.assertEqual(
            str(stop.exception.code),
            "dev/y is not merged into main (dev/old no longer exists); pass --force to discard it",
        )
        self.assertFalse(ledger.load("gone-out").get("retired"))

    def test_worker_command(self):
        ctx = self._ctx()
        w = Workers(ctx)
        a = type("A", (), {"kind": "codex", "model": "m", "effort": "high"})
        self.assertEqual(
            w.worker_argv(a),
            ["codex", "-c", "check_for_update_on_startup=false", "-m", "m", "-c", 'model_reasoning_effort="high"'],
        )
        a.kind, a.effort = "claude", "xhigh"
        self.assertEqual(w.worker_argv(a), ["claude", "--model", "m", "--effort", "xhigh"])
        a.effort = ""
        self.assertEqual(w.worker_argv(a), ["claude", "--model", "m"])  # no effort given: no --effort
        a.effort = "high"
        a.kind = "pi"
        self.assertEqual(w.worker_argv(a), ["pi", "--model", "m", "--thinking", "high"])
        a.kind = "mine --yes"  # not in the registry: run as written
        self.assertEqual(w.worker_argv(a), ["mine", "--yes"])

    def test_agent_kinds_can_be_added_in_config(self):
        ctx = self._ctx(config={"agents": {"mine": {"argv": ["mine", "run"], "model": ["--m={}"], "prompt_arg": True}}})
        self.assertEqual(ctx.agents.start_argv("mine", "x", prompt="go"), ["mine", "run", "--m=x", "go"])
        self.assertTrue(ctx.agents.takes_prompt("mine"))
        self.assertFalse(ctx.agents.takes_prompt("gemini"))

    def test_the_kind_of_a_terminal_comes_from_its_program(self):
        self.assertEqual(agents_base.terminal_kind({"foreground": {"argv": ["/opt/bin/codex", "-m", "x"]}}), "codex")
        self.assertEqual(agents_base.terminal_kind({"argv": ["zsh"], "status": {"app": "claude-code"}}), "claude")
        self.assertEqual(agents_base.terminal_kind({"foreground": {"argv": ["other"]}}), "other")

    def test_turn_hook_notes_pm_turns_only(self):
        from pmlib.project.turn_state import TurnTracker

        ctx_base = self._ctx()
        repo_dir = self.root / "proj-t"
        repo_dir.mkdir(parents=True, exist_ok=True)
        ctx_base.home.registrations.mkdir(parents=True, exist_ok=True)
        (ctx_base.home.registrations / "t.json").write_text(
            json.dumps({"name": "pm-t", "pane": "hc:t9", "project": "t", "repo": str(repo_dir)})
        )
        for who, prompt in (("hc:t9", "hello"), ("hc:t9", "[from hc:t3] done"), ("hc:t8", "hello")):
            ctx = make_ctx(self.root / "ctx", pane=who, out=StdOutput())
            with mock.patch.object(sys, 'stdin', io.StringIO(json.dumps({'hook_event_name': 'UserPromptSubmit', 'prompt': prompt}))):
                hooks_mod.cmd_hook_mirror(None, ctx=ctx)  # the earlier name still works
        self.assertFalse(ctx_base.home.turn_log.exists())
        entries = TurnTracker(ctx_base, str(repo_dir)).read_journal_entries()
        user_prompts = [e for e in entries if e.get("kind") == "hook_prompt" and e.get("cause") == "user"]
        self.assertEqual(len(user_prompts), 1)

    def test_worker_defaults_come_from_config_unless_given(self):
        ctx1 = make_ctx(self.root / "wd1", config={"worker": {"model": "m1", "effort": "high"}})
        a = ctx1.agents.resolve_worker(type("A", (), {"kind": None, "model": None, "effort": "low"}))
        self.assertEqual((a.kind, a.model, a.effort), ("codex", "m1", "low"))
        a = ctx1.agents.resolve_worker(type("A", (), {"kind": "claude", "model": None, "effort": None}))
        self.assertEqual((a.kind, a.model, a.effort), ("claude", "", ""))  # codex's model is not claude's
        ctx2 = make_ctx(self.root / "wd2", config={})
        a = ctx2.agents.resolve_worker(type("A", (), {"kind": None, "model": None, "effort": None}))
        self.assertEqual(Workers(ctx2).worker_argv(a), ["codex", "-c", "check_for_update_on_startup=false"])


class SendBrief(unittest.TestCase):
    """dispatch types the brief only into a worker whose input is ready, answering a trust dialog for its own worktree."""

    tree = str(Path.home() / ".herdr" / "worktrees" / "app" / "dev-x")
    idle = {"app": "claude-code", "state": "idle"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-send-brief-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _frame_ctx(self, frames, *, git=None):
        hc_ref = []

        class _StepClock(FakeClock):
            def sleep(self, seconds: float) -> None:
                super().sleep(seconds)
                if hc_ref:
                    hc_ref[0].advance_frame()

        clock = _StepClock()
        hc = _FrameHc(frames, clock=clock)
        hc_ref.append(hc)
        ctx = make_ctx(
            self.root / f"ctx-{id(hc)}",
            hc=hc,
            tui=FakeTui(server_ok=False),
            clock=clock,
            git=git if git is not None else GitRepo(),
            out=StdOutput(),
        )
        return ctx, hc.seen

    def test_trust_keys_follow_the_dialogs_own_options(self):
        self.assertEqual(screen_mod.trust_keys(CLAUDE_TRUST), ["down", "enter"])
        self.assertEqual(screen_mod.trust_keys(CODEX_TRUST), ["enter"])
        self.assertIsNone(screen_mod.trust_keys(OTHER_DIALOG))
        self.assertIsNone(screen_mod.trust_keys('❯ Try "fix typecheck errors"'))

    def test_nothing_is_sent_while_the_agent_has_no_status(self):
        ctx, seen = self._frame_ctx([(None, "")])
        self.assertFalse(Workers(ctx).send_when_ready("t9", "brief", tries=30, pause=2, strict=True, trust=self.tree))
        self.assertEqual(seen, [])

    def test_a_program_without_status_gets_the_text_once(self):
        seen = []

        class _NoStatusHc(FakeHc):
            def get_raw(self, term, *, errors=False):
                return {"address": term, "state": "live"}

            def send(self, term, text, *, if_state=None, timeout=180, errors=False):
                seen.append("sent")
                return {"started": None, "status": None, "turn": 0}

        ctx = make_ctx(self.root / "nostatus", hc=_NoStatusHc(), clock=FakeClock())
        self.assertTrue(Workers(ctx).send_when_ready("t9", "brief", tries=8))
        self.assertEqual(seen, ["sent"])

    def test_a_trust_dialog_for_its_own_worktree_is_confirmed_then_the_brief_sent(self):
        ctx, seen = self._frame_ctx([(None, CLAUDE_TRUST), (None, CLAUDE_TRUST), (None, ""), (self.idle, "❯ ")])
        self.assertTrue(Workers(ctx).send_when_ready("t9", "brief", tries=30, pause=2, strict=True, trust=self.tree))
        self.assertEqual(seen, [["down", "enter"], "sent"])

    def test_other_dialogs_and_other_folders_are_left_alone(self):
        ctx1, seen1 = self._frame_ctx([(None, OTHER_DIALOG)])
        self.assertFalse(Workers(ctx1).send_when_ready("t9", "brief", tries=30, pause=2, strict=True, trust=self.tree))
        ctx2, seen2 = self._frame_ctx([(None, CLAUDE_TRUST)])
        other_tree = str(self.root / "other-tree")
        Path(other_tree).mkdir()
        self.assertFalse(Workers(ctx2).send_when_ready("t9", "brief", tries=30, pause=2, strict=True, trust=other_tree))
        self.assertEqual(seen1 + seen2, [])

    def test_dispatch_that_could_not_send_logs_the_screen_and_prints_the_resend(self):
        repo = init_empty_repo(self.root / "repo-nosend")
        brief = repo / "brief.md"
        brief.write_text("Write one line.")
        wt_home = self.root / "wt-home"
        ctx, _ = self._frame_ctx(
            [(None, OTHER_DIALOG)],
            git=GitRepo(worktree_home_fn=lambda _r: wt_home / "app"),
        )
        a = argparse.Namespace(
            repo=str(repo), brief=str(brief), branch="dev/x", base="main", prep=None,
            name="x", kind="claude", model="", effort="", title="x", label="x",
        )
        ctx.agents.resolve_worker(a).apply_to(a)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            dispatch_cmd.dispatch_hc(a, str(repo), brief.read_text(), ctx=ctx)
        task_id = out.getvalue().split()[0]
        self.assertIn("New MCP server found", str(stop.exception.code))
        from pmlib import osutil as _osutil
        self.assertIn(f"hc send t9 {_osutil.file_text(ctx.home.root / 'sent' / f'{task_id}.md')}", str(stop.exception.code))
        self.assertIn("New MCP server found", Ledger(ctx).load(task_id)["log"][-1]["text"])


class Profiles(unittest.TestCase):
    """dispatch --profile: a word for kind, model, effort and advisor; deep asks the user first; reviews by table."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-profiles-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self._cfg: dict = {}
        self._seq = 0
        self._cur_ctx = None

    def config(self, **values):
        self._cfg = dict(values)
        if self._cur_ctx is not None:
            self._cur_ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
            self._cur_ctx.home.config.write_text(json.dumps(self._cfg))

    def _fresh_ctx(self, *, pane: str = "hc:t48", hc=None, tui=None, git=None, store_cls=None):
        self._seq += 1
        ctx = make_ctx(
            self.root / f"ledger-{self._seq}",
            pane=pane,
            hc=hc,
            tui=tui,
            config=self._cfg,
            git=git if git is not None else GitRepo(),
            clock=FakeClock(),
            out=StdOutput(),
        )
        # The commands here are compared whole; what a worker may read outside its worktree is OutsideReads' test.
        ctx.agents.outside_reads = lambda *a, **kw: []
        if store_cls is not None:
            ctx.store = store_cls(ctx.home)
        self._cur_ctx = ctx
        return ctx

    def worker(self, **given):
        ctx = self._fresh_ctx()
        a = type("A", (), {"kind": None, "model": None, "effort": None, **given})
        return ctx.agents.resolve_worker(a)

    def _worker_argv(self, a):
        ctx = self._cur_ctx or self._fresh_ctx()
        return Workers(ctx).worker_argv(a)

    def test_without_a_profile_the_command_is_as_before(self):
        a = self.worker()
        self.assertEqual(self._worker_argv(a), ["codex", "-c", "check_for_update_on_startup=false"])
        self.assertEqual(profiles_mod.worker_record(a), {"profile": "", "kind": "codex", "model": "", "effort": "", "advisor": ""})
        self.config(worker={"kind": "claude", "model": "opus"})
        w = self.worker()
        self.assertEqual(self._worker_argv(w), ["claude", "--model", "opus"])
        self.assertEqual(
            workers_dispatch.dispatch_note_for(self._cur_ctx, type("A", (), {**vars(w), "name": "w"})),
            "dispatched to w (claude opus)",
        )

    def test_a_profile_fills_the_command_and_the_command_line_wins(self):
        self.assertEqual(
            self._worker_argv(self.worker(profile="hard")),
            ["claude", "--model", "opus", "--effort", "xhigh", "--advisor", "fable"],
        )
        self.assertEqual(self._worker_argv(self.worker(profile="light")), ["claude", "--model", "sonnet", "--effort", "medium"])
        self.assertEqual(self._worker_argv(self.worker(profile="standard")), ["claude", "--model", "opus"])
        self.assertEqual(
            self._worker_argv(self.worker(profile="hard", effort="high", model="sonnet")),
            ["claude", "--model", "sonnet", "--effort", "high", "--advisor", "fable"],
        )
        self.assertEqual(
            self._worker_argv(self.worker(profile="hard", advisor="none")),
            ["claude", "--model", "opus", "--effort", "xhigh"],
        )
        # The profile's values belong to its program, not to another one named on the command line.
        a = self.worker(profile="hard", kind="codex")
        self.assertEqual(self._worker_argv(a), ["codex", "-c", "check_for_update_on_startup=false"])
        self.assertEqual(profiles_mod.worker_record(a)["profile"], "hard")
        with self.assertRaises((SystemExit, Refused)):
            self.worker(profile="nope")

    def test_config_profiles_replace_or_add_and_worker_can_name_one(self):
        self.config(
            profiles={
                "hard": {"kind": "claude", "model": "opus", "effort": "high"},
                "ui": {"model": "sonnet"},
                "cx": {"kind": "codex", "model": "gpt", "advisor": "fable"},
            },
            worker={"profile": "standard", "effort": "high"},
        )
        self.assertEqual(self._worker_argv(self.worker(profile="hard")), ["claude", "--model", "opus", "--effort", "high"])
        self.assertEqual(self._worker_argv(self.worker(profile="ui")), ["claude", "--model", "sonnet"])
        self.assertEqual(
            self._worker_argv(self.worker(profile="deep")),
            ["claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus"],
        )
        a = self.worker()  # config's worker names standard and changes its effort
        self.assertEqual((a.profile, self._worker_argv(a)), ("standard", ["claude", "--model", "opus", "--effort", "high"]))
        # A program without an advisor flag: left out, and the dispatch note says so.
        a = self.worker(profile="cx")
        self.assertEqual(
            (self._worker_argv(a), a.advisor, a.advisor_dropped),
            (["codex", "-c", "check_for_update_on_startup=false", "-m", "gpt"], "", "fable"),
        )
        self.assertIn(
            "advisor fable left out",
            workers_dispatch.dispatch_note_for(self._cur_ctx, type("A", (), {**vars(a), "name": "w"})),
        )
        # config's worker names a profile but another program: the profile's Claude values are not given to it.
        self.config(worker={"profile": "hard", "kind": "codex"})
        a = self.worker()
        self.assertEqual((a.profile, self._worker_argv(a)), ("hard", ["codex", "-c", "check_for_update_on_startup=false"]))
        self.config(worker={"profile": "hard", "kind": "codex", "effort": "high"})
        self.assertEqual(self._worker_argv(self.worker())[-2:], ["-c", 'model_reasoning_effort="high"'])

    def dispatching(self, screens=None, *, store_cls=None):
        """A git repository, a fake hc and a PM pane; returns (dispatch(**args) -> printed text, calls, terminals, ctx, trees)."""
        self._seq += 1
        repo = init_empty_repo(self.root / f"repo-{self._seq}")
        brief = repo / "brief.md"
        brief.write_text("Write one line.")
        trees = self.root / f"trees-{self._seq}"
        trees.mkdir()
        hc = _ScriptedDispatchHc(screens=screens, clock=FakeClock())
        ctx = self._fresh_ctx(
            pane="hc:t48",
            hc=hc,
            tui=FakeTui(server_ok=False),
            git=GitRepo(worktree_home_fn=lambda _r: trees / "app"),
            store_cls=store_cls,
        )

        def dispatch(**given):
            a = argparse.Namespace(**{
                "repo": str(repo), "brief": str(brief), "branch": "dev/p", "base": None, "prep": None,
                "name": "w", "title": "做一件事", "label": "p", "kind": None, "model": None,
                "effort": None, "profile": None, "advisor": None, "confirmed": False, **given,
            })
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    dispatch_cmd.cmd_dispatch(a, ctx=ctx)
                except SystemExit as stop:
                    out.write(f"\nexit: {stop.code}")
            return out.getvalue()

        return dispatch, hc.raw_calls, hc.states, ctx, trees

    def started(self, calls):
        return [c[c.index("--") + 1:] for c in calls if c[0] == "run"]

    def escalate(self, ctx, task_id, **given):
        a = argparse.Namespace(**{
            "id": task_id, "profile": None, "why": None, "advisor": None, "name": None,
            "confirmed": False, **given,
        })
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                workers_cmd.cmd_escalate(a, ctx=ctx)
            except SystemExit as stop:
                out.write(f"\nexit: {stop.code}")
        return out.getvalue()

    def run_of(self, calls, address):
        """The `hc run` call that made terminal t<n>."""
        return [c for c in calls if c[0] == "run"][int(address[1:]) - 1]

    def test_deep_registers_a_question_and_starts_a_worker_only_once_confirmed(self):
        dispatch, calls, _, ctx, trees = self.dispatching()
        ledger = Ledger(ctx)
        task_id = dispatch(profile="deep").split()[0]
        task = ledger.load(task_id)
        self.assertEqual((task["status"], task["held"], task["pane"]), ("blocked", "ask", "hc:t48"))
        self.assertEqual(len(task["options"]), 2)
        self.assertIn("fable", task["log"][-1]["text"])
        self.assertEqual(self.started(calls), [])  # no worker, and no worktree either
        self.assertFalse((trees / "app" / "dev-p").exists())
        self.assertNotIn("worker", task)
        self.assertIn("still waiting", dispatch(profile="deep"))  # asked again: the same question, no second task
        self.assertEqual(len([t for t in ledger.all_tasks() if t.get("branch") == "dev/p" and t["repo"] == task["repo"]]), 1)
        out = dispatch(profile="deep", confirmed=True)
        self.assertEqual(out.split()[0], task_id)  # the held task is taken up
        self.assertEqual(self.started(calls), [("claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus")])
        task = ledger.load(task_id)
        self.assertEqual((task["status"], task["pane"], task.get("held"), task.get("options")), ("in_progress", "hc:t1", None, None))
        self.assertEqual(task["worker"], {"profile": "deep", "kind": "claude", "model": "fable", "effort": "high", "advisor": ""})
        self.assertEqual((task["escalations"], task["rounds"], task["dispatched"]), ([], 0, True))
        self.assertIn("dispatched to w (deep: claude fable high)", task["log"][-1]["text"])

    def test_the_user_can_pick_hard_instead_of_deep(self):
        dispatch, calls, _, ctx, _ = self.dispatching()
        task_id = dispatch(profile="deep").split()[0]
        self.assertEqual(dispatch(profile="hard").split()[0], task_id)  # hard asks nobody
        self.assertEqual(self.started(calls), [("claude", "--model", "opus", "--effort", "xhigh", "--advisor", "fable")])
        self.assertEqual(Ledger(ctx).load(task_id)["worker"]["advisor"], "fable")

    def test_a_worker_that_exits_with_its_advisor_is_blocked_not_restarted(self):
        dispatch, calls, terminals, ctx, _ = self.dispatching(screens={"t1": "Run /model fable to enable Fable"})
        ledger = Ledger(ctx)
        terminals["t1"] = "finished"
        out = dispatch(profile="hard")
        task_id = out.split()[0]
        task = ledger.load(task_id)
        self.assertIn("exit:", out)
        self.assertIn("/model fable", out)
        self.assertEqual((task["status"], task["held"], len(task["options"])), ("blocked", "advisor", 2))
        self.assertIn("/model fable", task["log"][-1]["text"])
        self.assertIn("Run /model fable to enable Fable", task["log"][-1]["text"])  # its screen, as seen
        self.assertEqual(task["worker"]["advisor"], "fable")
        self.assertEqual(len(self.started(calls)), 1)  # not started again by itself
        self.assertFalse(any(c[0] == "send" for c in calls))
        # Its terminal is removed and the question is parked on the PM's pane: not an offline thread to reattach.
        self.assertIn(("rm", "t1"), calls)
        self.assertEqual(task["pane"], "hc:t48")
        # The second answer is one a user without Fable at all can take (Bedrock, Vertex, a gateway).
        self.assertEqual(task["options"][1], 'No Fable: use hard without the advisor, and set "fable": false in config.json')
        self.assertIn('"fable": false', out)
        # Dispatched again without the advisor: the same task and worktree.
        out = dispatch(profile="hard", advisor="none")
        self.assertEqual(out.split()[0], task_id)
        self.assertEqual(self.started(calls)[-1], ("claude", "--model", "opus", "--effort", "xhigh"))
        task = ledger.load(task_id)
        self.assertEqual((task["status"], task["pane"], task["worker"]["advisor"], task.get("held")), ("in_progress", "hc:t2", "", None))

    def test_any_fable_worker_asks_first_but_a_fable_advisor_does_not(self):
        self.config(profiles={"big": {"model": "claude-fable-5-2"}})
        for given in (
            {"model": "fable"},
            {"kind": "claude", "model": "Fable"},
            {"profile": "big"},
            {"profile": "standard", "model": "fable"},
        ):
            dispatch, calls, _, ctx, _ = self.dispatching()
            task = Ledger(ctx).load(dispatch(**given).split()[0])
            self.assertEqual((task["status"], task["held"], self.started(calls)), ("blocked", "ask", []), given)
        dispatch, calls, _, _, _ = self.dispatching()
        dispatch(profile="deep", model="opus")  # deep's name alone still asks
        self.assertEqual(self.started(calls), [])
        dispatch, calls, _, _, _ = self.dispatching()
        dispatch(profile="hard")  # hard's Fable advisor is the PM's to pick
        self.assertEqual(len(self.started(calls)), 1)
        dispatch, calls, _, _, _ = self.dispatching()
        dispatch(model="fable", confirmed=True)
        self.assertEqual(self.started(calls), [("codex", "-c", "check_for_update_on_startup=false", "-m", "fable")])

    def test_in_the_terminal_ui_a_worker_gone_with_its_advisor_is_blocked_too(self):
        repo = init_empty_repo(self.root / "repo-tui-adv")
        brief = repo / "brief.md"
        brief.write_text("Write one line.")
        tree = str(self.root / "tui-tree")
        Path(tree).mkdir()
        calls, running = [], {"w1:p0"}  # panes with an agent in them; the PM's own is w1:p0

        class _TuiAdv(FakeTui):
            def herdr(self, *args, session=None):
                calls.append(args)
                if args[:2] == ("worktree", "create"):
                    return {"workspace": {"workspace_id": "w2"}, "pane": {"pane_id": "w2:p1"}, "path": tree}
                if args[:2] == ("agent", "start"):
                    return {"started": True}
                if args[:2] == ("agent", "list"):
                    return {"agents": [{"pane_id": p} for p in running]}
                if args[:2] in (("agent", "prompt"), ("agent", "wait")):
                    return {"ok": True} if "w2:p1" in running else None
                return None

            def agents(self, *, session=None):
                res = self.herdr("agent", "list", session=session)
                return list((res or {}).get("agents") or [])

        ctx = self._fresh_ctx(pane="w1:p0", tui=_TuiAdv())
        ledger = Ledger(ctx)

        def dispatch(**given):
            a = argparse.Namespace(**{
                "repo": str(repo), "brief": str(brief), "branch": "dev/t", "base": None, "prep": None,
                "name": "w", "title": "做一件事", "label": "t", "kind": None, "model": None,
                "effort": None, "profile": "hard", "advisor": None, "confirmed": False, **given,
            })
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    dispatch_cmd.cmd_dispatch(a, ctx=ctx)
                except SystemExit as stop:
                    out.write(f"\nexit: {stop.code}")
            return out.getvalue()

        out = dispatch()  # claude exits at once: no agent in w2:p1
        task = ledger.load(out.split()[0])
        self.assertIn("/model fable", out)
        self.assertEqual(
            (task["status"], task["held"], task["pane"], task["held_in"]),
            ("blocked", "advisor", "w1:p0", {"workspace": "w2", "pane": "w2:p1"}),
        )
        start = [c for c in calls if c[:2] == ("agent", "start")]
        self.assertEqual(start[-1][start[-1].index("--") + 1:], ("--model", "opus", "--effort", "xhigh", "--advisor", "fable"))
        running.add("w2:p1")
        out = dispatch(advisor="none")  # again, without the advisor: the same task, worktree and pane
        self.assertEqual(out.split()[0], task["id"])
        self.assertEqual(sum(c[:2] == ("worktree", "create") for c in calls), 1)
        start = [c for c in calls if c[:2] == ("agent", "start")]
        self.assertEqual((len(start), start[-1][start[-1].index("--pane") + 1]), (2, "w2:p1"))
        task = ledger.load(task["id"])
        self.assertEqual(
            (task["status"], task["pane"], task.get("held_in"), task["worktree"], task["worker_pane"]),
            ("in_progress", "w2:p1", None, tree, "w2:p1"),
        )
        self.assertTrue(task["dispatched"])  # so `land` (update --status merged) retires it, as in the desktop app

    def test_reattach_uses_the_worker_record(self):
        ctx = self._fresh_ctx()
        task = {
            "worker": {"profile": "hard", "kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"},
            "log": [{"text": "dispatched to w (hard: claude opus xhigh, advisor fable)"}],
        }
        self.assertEqual(workers_sessions.dispatched_with(task), ("claude", "opus", "xhigh"))
        self.assertEqual(
            workers_sessions.dispatched_with({"log": [{"text": "dispatched to w (codex gpt-5 high)"}]}),
            ("codex", "gpt-5", "high"),  # a task from before the record
        )
        self.assertEqual(
            ctx.agents.resume_argv("claude", "s1", "opus", "xhigh", "fable"),
            ["claude", "--model", "opus", "--effort", "xhigh", "--advisor", "fable", "--resume", "s1"],
        )

    def test_a_worker_without_an_advisor_is_waited_for_as_before(self):
        dispatch, calls, terminals, ctx, _ = self.dispatching()
        terminals["t1"] = "finished"
        out = dispatch()
        self.assertIn("the brief was not sent", out)
        # Every try, as before, and one more look for the turn count the round's work counts from.
        self.assertEqual(sum(c[0] == "get" and c[1] == "t1" for c in calls), 31)
        self.assertEqual(Ledger(ctx).load(out.split()[0])["status"], "in_progress")

    def test_review_model_comes_from_the_table_by_the_workers_profile(self):
        def review(task, **given):
            ctx = self._fresh_ctx()
            spec, _ = Reviews(ctx).reviewer_spec(
                profiles_mod.WorkerSpec.from_args(argparse.Namespace(**{"kind": None, "model": None, "effort": None, **given})),
                task,
            )
            return spec

        pick = lambda a: (a.kind, a.model, a.effort)
        hard, light = {"worker": {"profile": "hard"}}, {"worker": {"profile": "light"}}
        self.assertEqual(pick(review(hard)), ("claude", "fable", ""))
        self.assertEqual(pick(review(light)), ("claude", "opus", ""))
        self.assertEqual(pick(review({"worker": {"profile": "deep"}})), ("claude", "opus", ""))
        self.assertEqual(pick(review(hard, model="sonnet")), ("codex", "sonnet", ""))  # a --model: as before
        self.assertEqual(pick(review({})), ("codex", "", ""))  # an old task, without a worker field: as before
        self.assertEqual(review(hard).advisor, "")
        self.config(worker={"kind": "claude", "model": "opus"}, review={"standard": "sonnet", "light": {"kind": "codex", "model": "gpt"}})
        self.assertEqual(pick(review({"worker": {"profile": "standard"}})), ("claude", "sonnet", ""))
        self.assertEqual(pick(review(light)), ("codex", "gpt", ""))
        self.assertEqual(pick(review({"worker": {"profile": "ui"}})), ("claude", "opus", ""))  # not in the table
        self.config(reviewer={"kind": "codex", "model": "gpt"})  # a configured reviewer: as before
        self.assertEqual(pick(review(hard)), ("codex", "gpt", ""))

    def test_without_fable_hard_has_no_advisor_deep_is_gone_and_reviews_go_to_sonnet(self):
        def review(profile):
            ctx = self._fresh_ctx()
            spec, _ = Reviews(ctx).reviewer_spec(
                profiles_mod.WorkerSpec.from_args(argparse.Namespace(kind=None, model=None, effort=None)),
                {"worker": {"profile": profile}},
            )
            return spec

        pick = lambda a: (a.model, a.fallback)
        # Not set, or true: as before.
        for values in ({}, {"fable": True}):
            self.config(**values)
            ctx = self._fresh_ctx()
            self.assertEqual(ctx.agents.ladder(), ("light", "standard", "hard", "deep"))
            self.assertEqual(self._worker_argv(self.worker(profile="hard"))[-2:], ["--advisor", "fable"])
            self.assertEqual(
                [pick(review(p)) for p in profiles_mod.LADDER],
                [("opus", ""), ("fable", "sonnet"), ("fable", "sonnet"), ("opus", "")],
            )
        self.config(fable=False)
        ctx = self._fresh_ctx()
        self.assertEqual(ctx.agents.ladder(), ("light", "standard", "hard"))
        a = self.worker(profile="hard")
        self.assertEqual((self._worker_argv(a), a.advisor), (["claude", "--model", "opus", "--effort", "xhigh"], ""))
        self.assertEqual(self._worker_argv(self.worker(profile="light")), ["claude", "--model", "sonnet", "--effort", "medium"])
        with self.assertRaises((SystemExit, Refused)) as stop:
            self.worker(profile="deep")
        self.assertIn('"fable": false', str(stop.exception.code if isinstance(stop.exception, SystemExit) else stop.exception))
        # A review the table gave to Fable goes to Sonnet, never to Opus, which wrote the code.
        self.assertEqual(
            [pick(review(p)) for p in profiles_mod.LADDER],
            [("opus", ""), ("sonnet", ""), ("sonnet", ""), ("opus", "")],
        )
        # What the user wrote still wins: their deep is back on the ladder, their Fable reviewer falls back to Sonnet.
        self.config(
            fable=False,
            profiles={"deep": {"model": "fable", "effort": "high"}, "hard": {"model": "opus", "advisor": "fable"}},
            review={"hard": "fable"},
        )
        ctx = self._fresh_ctx()
        self.assertEqual(ctx.agents.ladder(), profiles_mod.LADDER)
        self.assertEqual(self._worker_argv(self.worker(profile="hard")), ["claude", "--model", "opus", "--advisor", "fable"])
        self.assertEqual(pick(review("hard")), ("fable", "sonnet"))
        self.assertEqual(pick(review("standard")), ("sonnet", ""))

    def test_a_fable_worker_or_reviewer_falls_back_and_its_note_says_so(self):
        self.config(lang="zh")
        a = self.worker(profile="deep")
        ctx = self._cur_ctx
        self.assertEqual(a.fallback, "opus")
        self.assertEqual(
            workers_dispatch.dispatch_note_for(ctx, type("A", (), {**vars(a), "name": "w"})),
            "dispatched to w (deep: claude fable high)；Fable 不可用时会退到 opus",
        )
        # The advisor is not covered: an advisor that cannot be used makes Claude exit whatever the fallback.
        for profile in ("light", "standard", "hard"):
            self.assertNotIn("--fallback-model", self._worker_argv(self.worker(profile=profile)))
        self.assertNotIn(
            "不可用",
            workers_dispatch.dispatch_note_for(self._cur_ctx, type("A", (), {**vars(self.worker(profile="hard")), "name": "w"})),
        )
        r, _ = Reviews(ctx).reviewer_spec(
            profiles_mod.WorkerSpec.from_args(argparse.Namespace(kind=None, model=None, effort=None)),
            {"worker": {"profile": "standard"}},
        )
        self.assertEqual(Workers(ctx).worker_argv(r), ["claude", "--model", "fable", "--fallback-model", "sonnet"])
        r, _ = Reviews(ctx).reviewer_spec(
            profiles_mod.WorkerSpec.from_args(argparse.Namespace(kind=None, model="claude-fable-5-2", effort=None)),
            {},
        )
        self.assertEqual(Workers(ctx).worker_argv(r)[-2:], ["-m", "claude-fable-5-2"])  # codex, the configured default: none
        # Another program is not given Claude's flag.
        self.assertEqual(
            ctx.agents.start_argv("codex", "fable", fallback="opus"),
            ["codex", "-c", "check_for_update_on_startup=false", "-m", "fable"],
        )
        self.assertEqual(
            ctx.agents.resume_argv("claude", "s1", "fable", "high", "", "opus"),
            ["claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus", "--resume", "s1"],
        )

    def test_without_fable_escalating_from_hard_stops_at_the_top(self):
        self.config(fable=False, lang="zh")
        dispatch, calls, _, ctx, _ = self.dispatching()
        ledger = Ledger(ctx)
        task_id = dispatch(profile="hard").split()[0]
        self.assertEqual(self.started(calls), [("claude", "--model", "opus", "--effort", "xhigh")])
        before = ledger.load(task_id)
        out = self.escalate(ctx, task_id, why="hard 也没做成")
        self.assertIn("没有 Fable", out)
        self.assertIn("最高一档", out)
        self.assertEqual(len(self.started(calls)), 1)  # no worker started
        self.assertNotIn(("kill", "t1"), calls)
        task = ledger.load(task_id)
        self.assertEqual((task["status"], task["pane"], task["escalations"], task.get("escalating")), ("in_progress", "hc:t1", [], None))
        self.assertEqual(len(task["log"]), len(before["log"]))
        self.assertIn("没有档位 deep", self.escalate(ctx, task_id, profile="deep"))
        self.assertEqual(len(self.started(calls)), 1)
        # One step below the top still goes up.
        self.config(fable=False)
        dispatch, calls, _, ctx2, _ = self.dispatching()
        task_id = dispatch(branch="dev/s", label="s", profile="standard").split()[0]
        self.assertNotIn("exit:", self.escalate(ctx2, task_id))
        self.assertEqual(Ledger(ctx2).load(task_id)["worker"]["profile"], "hard")

    def test_dispatch_parent_names_the_task_it_was_split_from(self):
        dispatch, calls, _, ctx, _ = self.dispatching()
        ledger = Ledger(ctx)
        repo_dir = self.root / "parent-repo"
        repo_dir.mkdir()
        repo = ctx.git.project_root(repo_dir)
        name = Path(repo).name
        ledger.save({
            "id": f"{name}-whole", "title": "总任务", "project": name, "repo": repo,
            "status": "in_progress", "owner": "pm", "base": "main", "created": ctx.clock.now(),
        })
        out = dispatch(parent="nope")  # no such task: nothing is made
        self.assertIn("no task nope", out)
        self.assertEqual(self.started(calls), [])
        task = ledger.load(dispatch(parent=f"{name}-whole").split()[0])
        self.assertEqual((task["parent"], task["status"]), (f"{name}-whole", "in_progress"))
        # One that asks the user first keeps its parent too, through to the dispatch the user agreed to.
        asked = ledger.load(dispatch(branch="dev/q", label="q", profile="deep", parent=f"{name}-whole").split()[0])
        self.assertEqual((asked["status"], asked["parent"]), ("blocked", f"{name}-whole"))
        dispatch(branch="dev/q", label="q", profile="deep", confirmed=True, parent=f"{name}-whole")
        self.assertEqual(ledger.load(asked["id"])["parent"], f"{name}-whole")

    def test_state_is_json_with_old_and_new_tasks(self):
        ctx = self._fresh_ctx()
        ledger = Ledger(ctx)
        repo_dir = self.root / "state-repo"
        repo_dir.mkdir()
        repo = ctx.git.project_root(repo_dir)
        name = Path(repo).name
        ledger.save({
            "id": f"{name}-old", "title": "old", "project": name, "repo": repo,
            "status": "in_progress", "owner": "pm", "base": "main", "created": ctx.clock.now(),
        })
        ledger.save({
            "id": f"{name}-new", "title": "new", "project": name, "repo": repo,
            "status": "in_progress", "owner": "pm", "base": "main", "created": ctx.clock.now(),
            "escalations": [], "rounds": 0,
            "worker": {"profile": "hard", "kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"},
        })
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            state_view.cmd_state(None, ctx=ctx)
        tasks = {t["id"]: t for t in json.loads(out.getvalue())["tasks"]}
        # In the state, `worker` stays the live agent's status (pm-dash counts on it); `engine` is the task's record.
        self.assertEqual((tasks[f"{name}-old"]["worker"], tasks[f"{name}-new"]["worker"]), ("", ""))
        self.assertEqual(tasks[f"{name}-old"]["engine"], {})
        self.assertEqual(tasks[f"{name}-new"]["engine"]["effort"], "xhigh")
        # Escalations and review rounds ride along for the thread list's tip; a task without them has neither.
        self.assertEqual((tasks[f"{name}-new"].get("escalations"), tasks[f"{name}-new"]["rounds"]), (None, 0))
        self.assertNotIn("rounds", tasks[f"{name}-old"])

    def test_escalate_goes_one_step_up_in_the_same_worktree_and_ends_the_old_worker(self):
        self.config(lang="zh")
        dispatch, calls, _, ctx, trees = self.dispatching()
        ledger = Ledger(ctx)
        task_id = dispatch(profile="standard").split()[0]
        task = ledger.load(task_id).raw
        first = (ctx.home.root / "sent" / f"{task_id}.md").read_text()
        ledger.save({
            "id": f"{task_id}-review", "title": "审查：做一件事", "project": task["project"], "repo": task["repo"],
            "status": "done", "owner": "pm", "base": "main", "review_of": task_id, "created": ctx.clock.now(),
            "log": [
                {"at": "2026-11-15 10:00", "by": "hc:t9", "text": "开始审查（claude fable）"},
                {"at": "2026-11-15 10:20", "by": "hc:t9", "text": "status=done; 1. 缺一个测试\n2. 名字拼错"},
            ],
        })
        ledger.append_note(task, "第二轮评审：测试还是没补")
        task["session"] = {"kind": "claude", "id": "s-old"}  # the old worker's: reattach must not resume it now
        task["rounds"] = 1
        ledger.save(task)
        out = self.escalate(ctx, task_id, why="两轮评审未过")
        self.assertNotIn("exit:", out)
        run = self.run_of(calls, "t2")
        self.assertEqual(run[run.index("--") + 1:], ("claude", "--model", "opus", "--effort", "xhigh", "--advisor", "fable"))
        self.assertEqual((run[run.index("--cwd") + 1], run[run.index("--name") + 1]), (task["worktree"], "w-hard"))
        self.assertEqual([p.name for p in (trees / "app").iterdir()], ["dev-p"])  # no second worktree
        self.assertIn(("kill", "t1"), calls)
        self.assertIn(("rm", "t1"), calls)
        task = ledger.load(task_id)
        self.assertEqual(
            (task["id"], task["branch"], task["worktree"], task["status"], task["pane"], task["agent"]),
            (task_id, "dev/p", run[run.index("--cwd") + 1], "in_progress", "hc:t2", "w-hard"),
        )
        self.assertEqual(
            task["worker"],
            {"profile": "hard", "kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"},
        )
        self.assertNotIn("session", task)
        # The new worker's rounds start from nothing, and the review thread is closed: its next review is no rework.
        self.assertEqual((task["rounds"], task["worker_pane"]), (0, "hc:t2"))
        self.assertTrue(ledger.load(f"{task_id}-review").get("retired"))
        self.assertEqual([(e["from"], e["to"], e["why"]) for e in task["escalations"]], [("standard", "hard", "两轮评审未过")])
        self.assertTrue(task["escalations"][0]["at"])
        self.assertEqual(task["log"][-1]["text"], "升级到 hard（Opus·xhigh）：两轮评审未过")
        sent = next(c[2] for c in calls if c[:2] == ("send", "t2"))
        for part in (
            "1. 缺一个测试\n  2. 名字拼错", "第二轮评审：测试还是没补", "Write one line.", "dev/p",
            "git log main..HEAD", "两轮评审未过", "前一个 worker 的提交已经在分支",
        ):
            self.assertIn(part, sent)
        self.assertEqual(sent.count(f"update {task_id} --status review"), 1)  # the report section, once
        self.assertEqual((ctx.home.root / "sent" / f"{task_id}.escalated.md").read_text(), sent)
        self.assertEqual((ctx.home.root / "sent" / f"{task_id}.md").read_text(), first)  # what reattach sends: the first

    def test_dispatch_hands_the_brief_over_and_the_round_counts_from_then(self):
        saved = []

        class _SpyStore(FileStore):
            def write_task(self, task_id, data):
                saved.append(dict(data.get("round") or {}))
                return super().write_task(task_id, data)

            def change_task(self, task_id, fn):
                def wrapped(cur):
                    res = fn(cur)
                    if res is not None:
                        saved.append(dict(res.get("round") or {}))
                    return res

                return super().change_task(task_id, wrapped)

        dispatch, _, _, ctx, _ = self.dispatching(store_cls=_SpyStore)
        task_id = dispatch(profile="standard").split()[0]
        self.assertIn(None, [r.get("turn", "absent") for r in saved])     # saved starting up, before the brief
        handed = Ledger(ctx).load(task_id)["round"]
        self.assertEqual((handed["terminal"], handed["turn"]), ("t1", 0))  # handed over at turn 0

    def test_while_escalate_replaces_the_worker_its_stop_is_no_stall(self):
        dispatch, _, _, ctx, _ = self.dispatching()
        ledger = Ledger(ctx)
        watcher = StallWatcher(ctx)
        task_id = dispatch(profile="standard").split()[0]
        repo = ledger.load(task_id)["repo"]
        ctx.store.change_registration(
            project_slug(repo),
            lambda _cur: {"name": f"pm-{Path(repo).name}", "project": Path(repo).name, "repo": repo, "runtime": "hc", "terminal": "t48", "pane": "hc:t48"},
        )
        self.assertTrue(watcher.watched_worker(ledger.load(task_id)))
        ctx.procs.spawned.clear()
        seen = []
        real_quiet = workers_escalate._quiet_old_worker_impl

        def quiet(c, task, *args):
            seen.append(watcher.watched_worker(ledger.load(task_id)))  # the deliverer looks while the old one is stopped
            return real_quiet(c, task, *args)

        with mock.patch.object(workers_escalate, "_quiet_old_worker_impl", quiet):
            self.assertNotIn("exit:", self.escalate(ctx, task_id, why="x"))
        task = ledger.load(task_id)
        self.assertEqual(seen, [False])
        self.assertNotIn("switching", task)
        self.assertTrue(watcher.watched_worker(task))  # the new worker is watched
        delivered = [s["args"][1] for s in ctx.procs.spawned if s["args"][:1] == ["deliver"]]
        self.assertEqual(delivered, [task["repo"]])    # and a deliverer runs to watch it
        # An escalation that stops before the switch (the old worker is still busy) leaves no mark behind.
        with mock.patch.object(workers_escalate, "_quiet_old_worker_impl", lambda *args: (_ for _ in ()).throw(Refused("still working"))):
            self.assertIn("exit:", self.escalate(ctx, task_id, why="y", profile="deep", confirmed=True))
        self.assertNotIn("switching", ledger.load(task_id))

    def test_escalate_to_deep_only_asks_until_confirmed(self):
        dispatch, calls, _, ctx, _ = self.dispatching()
        ledger = Ledger(ctx)
        task_id = dispatch(profile="hard").split()[0]
        out = self.escalate(ctx, task_id, why="hard 也没做成")
        task = ledger.load(task_id)
        self.assertIn("--confirmed", out)
        self.assertEqual(len(self.started(calls)), 1)  # no worker started
        self.assertNotIn(("kill", "t1"), calls)
        self.assertEqual(
            (task["status"], len(task["options"]), task["pane"], task["worker"]["profile"], task["escalations"]),
            ("blocked", 2, "hc:t1", "hard", []),
        )
        self.assertIn("fable", task["log"][-1]["text"])
        self.assertIn("still waiting", self.escalate(ctx, task_id))  # asked again: no second card
        self.assertEqual(len(ledger.load(task_id)["log"]), len(task["log"]))
        self.escalate(ctx, task_id, confirmed=True)
        self.assertEqual(self.started(calls)[-1], ("claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus"))
        task = ledger.load(task_id)
        self.assertEqual((task["status"], task["pane"], task.get("options"), task.get("escalating")), ("in_progress", "hc:t2", None, None))
        self.assertEqual([(e["from"], e["to"], e["why"]) for e in task["escalations"]], [("hard", "deep", "hard 也没做成")])
        self.assertIn(("rm", "t1"), calls)
        # Deep is the top: without --profile there is nothing to go to, and nothing starts.
        self.assertIn("--profile", self.escalate(ctx, task_id))
        self.assertEqual(len(self.started(calls)), 2)
        # Any Fable worker asks, whatever the profile is called; hard (a Fable advisor) does not.
        self.config(profiles={"big": {"model": "claude-fable-5-2"}})
        self.assertEqual((self.escalate(ctx, task_id, profile="big").count("--confirmed"), len(self.started(calls))), (1, 2))

    def test_an_escalation_question_on_an_answered_task_is_a_new_one(self):
        dispatch, _, _, ctx, _ = self.dispatching()
        ledger = Ledger(ctx)
        task_id = dispatch(profile="hard").split()[0]
        task = ledger.load(task_id)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmd.cmd_update(argparse.Namespace(
                id=task_id, status="blocked", note="先问个事", option=["好"], keep=False,
                **{f: None for f in FIELDS if f != "status"},
            ), ctx=ctx)
        conv = Conversation(ctx, task["repo"])
        conv.record("user", text=f"【{task['title']}】好")
        self.assertIn(task_id, answered_tasks(conv.events()))
        self.escalate(ctx, task_id, why="hard 也没做成")  # to deep: the user is asked anew
        self.assertNotIn(task_id, answered_tasks(conv.events()))

    def test_a_declined_escalation_leaves_no_reason_behind(self):
        dispatch, _, _, ctx, _ = self.dispatching()
        ledger = Ledger(ctx)
        task_id = dispatch(profile="hard").split()[0]
        self.escalate(ctx, task_id, why="旧理由")
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmd.cmd_update(argparse.Namespace(
                id=task_id, status="in_progress", note="先不升级", keep=False,
                **{f: None for f in FIELDS if f != "status"},
            ), ctx=ctx)
        self.assertNotIn("escalating", ledger.load(task_id))
        self.escalate(ctx, task_id, profile="deep", confirmed=True)
        self.assertEqual(ledger.load(task_id)["escalations"][-1]["why"], "")

    def test_a_named_profile_and_terminals_that_are_not_the_tasks_worker(self):
        dispatch, calls, _, ctx, _ = self.dispatching()
        ledger = Ledger(ctx)
        task_id = dispatch(profile="light").split()[0]
        task = ledger.load(task_id).raw
        task["pane"] = "hc:t77"  # an adopted session: no task label, so it may be the user's own
        ledger.save(task)
        out = self.escalate(ctx, task_id, profile="hard")
        self.assertIn("hc:t77", out)
        self.assertFalse(any(c[0] in ("kill", "rm") and c[1] == "t77" for c in calls))
        task = ledger.load(task_id).raw
        self.assertEqual(([(e["from"], e["to"]) for e in task["escalations"]], task["pane"]), ([("light", "hard")], "hc:t2"))
        task["pane"] = "hc:t48"  # parked on the PM's own pane
        ledger.save(task)
        self.escalate(ctx, task_id, profile="standard")
        self.assertFalse(any(c[0] in ("kill", "rm") and c[1] == "t48" for c in calls))
        self.assertEqual(len(ledger.load(task_id)["escalations"]), 2)
        # A task without a profile names one; a review thread and closed work are not escalated.
        task = ledger.load(task_id).raw
        task["worker"] = {}
        ledger.save(task)
        self.assertIn("--profile", self.escalate(ctx, task_id))
        task.update(status="merged")
        ledger.save(task)
        self.assertIn("exit:", self.escalate(ctx, task_id, profile="hard"))
        self.assertEqual(len(self.started(calls)), 3)

    def test_an_escalated_worker_that_exits_with_its_advisor_keeps_the_old_one(self):
        dispatch, calls, terminals, ctx, _ = self.dispatching(screens={"t2": "Run /model fable to enable Fable"})
        ledger = Ledger(ctx)
        terminals["t2"] = "finished"
        task_id = dispatch(profile="standard").split()[0]
        out = self.escalate(ctx, task_id)
        self.assertIn("/model fable", out)
        self.assertIn("escalate", out.split("exit:")[1])
        task = ledger.load(task_id)
        self.assertEqual(
            (task["status"], task["pane"], task["worker"]["profile"], task["escalations"], len(task["options"])),
            ("blocked", "hc:t1", "standard", [], 2),
        )
        self.assertIn(("rm", "t2"), calls)
        self.assertNotIn(("kill", "t1"), calls)
        self.escalate(ctx, task_id, advisor="none")  # the question's other answer
        self.assertEqual(self.started(calls)[-1], ("claude", "--model", "opus", "--effort", "xhigh"))
        task = ledger.load(task_id)
        self.assertEqual((task["status"], task["pane"], task["worker"]["advisor"]), ("in_progress", "hc:t3", ""))
        self.assertIn(("rm", "t1"), calls)

    def test_an_escalated_worker_that_exits_without_an_advisor_changes_nothing(self):
        dispatch, calls, terminals, ctx, _ = self.dispatching(screens={"t2": "fable is not available"})
        ledger = Ledger(ctx)
        terminals["t2"] = "finished"
        task_id = dispatch(profile="hard").split()[0]
        before = ledger.load(task_id)
        terminals["t1"] = "working"  # stopped for the new one, which then exits: the PM is told the old one waits
        out = self.escalate(ctx, task_id, profile="deep", confirmed=True)
        self.assertIn("exit:", out)
        self.assertIn("hc:t1 was interrupted", out)
        task = ledger.load(task_id)
        self.assertEqual(
            (task["status"], task["pane"], task["worker"], task["escalations"]),
            (before["status"], "hc:t1", before["worker"], []),
        )
        self.assertIn("fable is not available", task["log"][-2]["text"])
        self.assertIn("interrupted", task["log"][-1]["text"])
        self.assertIn(("rm", "t2"), calls)
        self.assertNotIn(("kill", "t1"), calls)
        self.assertLess(sum(c[:2] == ("get", "t2") for c in calls), 10)  # not waited out: it stops once it exits
        # Again on the profile it runs on: a name the old, live terminal does not hold.
        terminals["t3"] = "live"
        self.escalate(ctx, task_id, profile="hard")
        run = self.run_of(calls, "t3")
        self.assertEqual(run[run.index("--name") + 1], "w-hard")
        self.escalate(ctx, task_id, profile="hard")
        run = self.run_of(calls, "t4")
        self.assertEqual(run[run.index("--name") + 1], "w-hard-2")

    def test_the_old_worker_stops_before_the_new_one_starts(self):
        dispatch, calls, terminals, ctx, _ = self.dispatching()
        ledger = Ledger(ctx)
        task_id = dispatch(profile="standard").split()[0]
        terminals["t1"] = "working"
        out = self.escalate(ctx, task_id)
        self.assertIn("interrupted", out)
        order = [c[:2] for c in calls if c[0] in ("interrupt", "run", "kill")]
        self.assertEqual(order[-3:], [("interrupt", "t1"), ("run", "--bg"), ("kill", "t1")])
        # Not this task's worker, and working: never interrupted, and nothing starts.
        task = ledger.load(task_id).raw
        task["pane"] = "hc:t77"
        ledger.save(task)
        terminals["t77"] = "working"
        runs = len(self.started(calls))
        out = self.escalate(ctx, task_id, profile="hard")
        self.assertIn("exit:", out)
        self.assertNotIn(("interrupt", "t77"), [c[:2] for c in calls])
        self.assertEqual((len(self.started(calls)), ledger.load(task_id)["pane"]), (runs, "hc:t77"))
        # git busy in the worktree (index.lock): nothing starts either.
        terminals["t77"] = "live"
        lock = Path(subprocess.run(
            ["git", "-C", task["worktree"], "rev-parse", "--absolute-git-dir"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()) / "index.lock"
        lock.write_text("")
        self.addCleanup(lock.unlink, missing_ok=True)
        out = self.escalate(ctx, task_id, profile="hard")
        self.assertIn("index.lock", out)
        self.assertEqual(len(self.started(calls)), runs)
        lock.unlink()
        self.assertNotIn("exit:", self.escalate(ctx, task_id, profile="hard"))
        self.assertEqual(len(self.started(calls)), runs + 1)

    def test_escalate_in_the_terminal_ui_opens_a_tab_in_the_tasks_workspace(self):
        tree = str(self.root / "tui-esc-tree")
        Path(tree).mkdir()
        calls = []
        running = {"w2:p1": "w", "w2:p5": "u"}

        class _TuiEsc(FakeTui):
            def herdr(self, *args, session=None):
                calls.append(args)
                if args[:2] == ("tab", "create"):
                    return {"tab": {"tab_id": "w2:t2"}, "pane": {"pane_id": "w2:p3"}}
                if args[:2] == ("agent", "start"):
                    running[args[args.index("--pane") + 1]] = args[2]
                    return {"started": True}
                if args[:2] == ("agent", "list"):
                    return {"agents": [{"pane_id": p, "name": n, "agent_status": "idle"} for p, n in running.items()]}
                if args[:2] == ("pane", "close"):
                    running.pop(args[2], None)
                return {"ok": True}

            def agents(self, *, session=None):
                res = self.herdr("agent", "list", session=session)
                return list((res or {}).get("agents") or [])

        ctx = self._fresh_ctx(pane="w1:p0", tui=_TuiEsc())
        ledger = Ledger(ctx)
        repo_dir = self.root / "tui-esc-repo"
        repo_dir.mkdir()
        repo = ctx.git.project_root(repo_dir)
        ledger.save({
            "id": "tui-e", "title": "t", "project": Path(repo).name, "repo": repo, "status": "review", "owner": "pm",
            "base": "main", "branch": "dev/t", "worktree": tree, "workspace": "w2", "pane": "w2:p1", "agent": "w",
            "worker_pane": "w2:p1", "created": ctx.clock.now(),
            "worker": {"profile": "standard", "kind": "claude", "model": "opus"},
        })
        out = self.escalate(ctx, "tui-e", why="卡在能力上")
        self.assertNotIn("exit:", out)
        tab = next(c for c in calls if c[:2] == ("tab", "create"))
        self.assertEqual((tab[tab.index("--workspace") + 1], tab[tab.index("--cwd") + 1]), ("w2", tree))
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        self.assertEqual(start[2:start.index("--", 3)], ("w-hard", "--kind", "claude", "--pane", "w2:p3"))
        self.assertEqual(start[start.index("--", 3) + 1:], ("--model", "opus", "--effort", "xhigh", "--advisor", "fable"))
        self.assertTrue(any(c[:3] == ("agent", "prompt", "w-hard") for c in calls))
        self.assertIn(("pane", "close", "w2:p1"), calls)
        task = ledger.load("tui-e")
        self.assertEqual((task["pane"], task["workspace"], task["status"], task["escalations"][0]["to"]), ("w2:p3", "w2", "in_progress", "hard"))
        # A session taken over with `pm.py new --pane --agent` (no worker_pane): never closed, even by its name.
        with contextlib.redirect_stdout(io.StringIO()):
            adopted = ledger_cmd.cmd_new(argparse.Namespace(
                repo=repo, title="u", status="in_progress", owner="pm", base="main",
                workspace="w2", pane="w2:p5", agent="u", branch="dev/u",
                worktree=tree, brief=None, slug="tui-u", note=None,
            ), ctx=ctx)
        task = ledger.load(adopted).raw
        task["worker"] = {"profile": "light", "kind": "claude", "model": "sonnet"}
        ledger.save(task)
        out = self.escalate(ctx, adopted)
        self.assertNotIn("exit:", out)
        self.assertIn("w2:p5", out)
        self.assertNotIn(("pane", "close", "w2:p5"), calls)
        self.assertEqual(ledger.load(adopted)["escalations"][0]["to"], "standard")


class OutsideReads(unittest.TestCase):
    """A Claude Code worker or reviewer reads the brief, the project's briefs/ and Herdr's API docs outside its
    worktree without being asked: --settings <file> with Read allow rules (and blockReadsExemptPaths for the user who
    blocks such reads), which grant no write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-outside-reads-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo, self.git = make_repo(self.root / "repo")
        (self.repo / "briefs" / "projects").mkdir(parents=True)
        self.brief = self.repo / "briefs" / "projects" / "x.md"
        self.brief.write_text("Read briefs/shot.png.")
        self.docs = self.root / "herdr-app"
        self.docs.mkdir()
        self.hc = _ScriptedDispatchHc(clock=FakeClock())
        self.ctx = make_ctx(
            self.root / "ctx",
            hc=self.hc,
            tui=FakeTui(server_ok=False),
            git=GitRepo(worktree_home_fn=lambda _r: self.root / "wt" / "app"),
            clock=FakeClock(),
            out=StdOutput(),
        )
        self.ctx.herdr_docs = self.docs
        self.ctx.agents = AgentRegistry.from_context(self.ctx)
        self.wanted = [str(self.brief.parent), str(self.repo / "briefs"), str(self.docs)]

    def started(self):
        run = next(c for c in self.hc.raw_calls if c[0] == "run")
        return list(run[run.index("--") + 1:])

    def exempt(self, argv):
        """The folders the worker may read, from its --settings file, which allows nothing else."""
        self.assertEqual(argv.count("--settings"), 1)
        self.assertNotIn("--add-dir", argv)  # --add-dir would let the worker write there too
        given = argv[argv.index("--settings") + 1]
        permissions = json.loads(Path(given).read_text())["permissions"]
        self.assertEqual(set(permissions), {"allow", "blockReadsExemptPaths"})
        # A folder with all below it, a single file as it is; "//" starts an absolute path in a rule (never `\`).
        self.assertEqual(
            permissions["allow"],
            [f"Read(//{Path(p).as_posix().lstrip('/')}/**)" if Path(p).is_dir()
             else f"Read(//{Path(p).as_posix().lstrip('/')})"
             for p in permissions["blockReadsExemptPaths"]],
        )
        self.assertTrue(all(rule.startswith("Read(//") and "\\" not in rule for rule in permissions["allow"]))
        return permissions["blockReadsExemptPaths"]

    def test_dispatch_lets_a_claude_worker_read_the_brief_and_the_docs(self):
        a = argparse.Namespace(
            repo=str(self.repo), brief=str(self.brief), branch="dev/y", base="main",
            prep=None, name="y", kind="claude", model="", effort="", title="y", label="y",
        )
        self.ctx.agents.resolve_worker(a).apply_to(a)
        with contextlib.redirect_stdout(io.StringIO()):
            dispatch_cmd.dispatch_hc(a, str(self.repo), self.brief.read_text(), ctx=self.ctx)
        argv = self.started()
        self.assertEqual(argv[0], "claude")
        self.assertEqual(self.exempt(argv), self.wanted)
        # What the worker is sent says the docs are for reading only.
        sent = next(c[2] for c in self.hc.raw_calls if c[0] == "send")
        docs_line = self.ctx.agents.docs_line()
        self.assertIn(str(self.docs), docs_line)
        self.assertTrue(sent.startswith("Read briefs/shot.png.") and sent.endswith(docs_line))
        # Other programs have no such block: started as before.
        codex = self.ctx.agents.resolve_worker(argparse.Namespace(kind="codex", model="", effort=""))
        w = Workers(self.ctx)
        self.assertEqual(
            w.worker_argv(codex, self.ctx.agents.outside_reads(str(self.repo), str(self.brief))),
            w.worker_argv(codex),
        )
        # A path is listed in every spelling a read may arrive by, since Claude Code follows no link in it.
        link = self.root / "link-parent" / "link"
        link.parent.mkdir()
        link.symlink_to(self.repo)
        self.assertEqual(
            self.ctx.agents.outside_reads(str(link)),
            [str(link / "briefs"), str(self.repo / "briefs"), str(self.docs)],
        )
        self.ctx.herdr_docs = self.docs / "gone"
        self.ctx.agents = AgentRegistry.from_context(self.ctx)
        self.assertEqual(
            (self.ctx.agents.outside_reads(str(self.repo), "/nowhere/b.md"), self.ctx.agents.docs_line()),
            ([str(self.repo / "briefs")], ""),
        )

    def test_review_lets_the_reviewer_read_the_brief_and_the_docs(self):
        self.git("branch", "-D", "dev/x")  # the task's branch lives in its worktree here
        tree = self.root / "rev-tree"
        self.git("worktree", "add", "-q", str(tree), "-b", "dev/x")
        ledger = Ledger(self.ctx)
        ledger.save({
            "id": "o-r", "title": "读外面", "project": self.repo.name, "repo": str(self.repo),
            "status": "review", "owner": "pm", "base": "main", "branch": "dev/x", "worktree": str(tree),
            "brief": str(self.brief), "created": self.ctx.clock.now(),
        })
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmd.cmd_review(argparse.Namespace(id="o-r", name=None, kind="claude", model="opus", effort=None), ctx=self.ctx)
        argv = self.started()
        self.assertEqual(self.exempt(argv), self.wanted)
        self.assertNotIn("--disallowedTools", argv)
        self.assertTrue(Path(ledger.load("o-r-review")["brief"]).read_text().endswith(self.ctx.agents.docs_line()))

    def test_the_terminal_ui_gets_a_settings_path_it_can_type(self):
        tree = str(self.root / "tui-reads-tree")
        Path(tree).mkdir()
        calls = []

        class _TuiReads(FakeTui):
            def herdr(self, *args, session=None):
                calls.append(args)
                if args[:2] == ("worktree", "create"):
                    return {"workspace": {"workspace_id": "w2"}, "pane": {"pane_id": "w2:p1"}, "path": tree}
                return {"ok": True}

        ctx = make_ctx(self.root / "tui-ctx", pane="w1:p0", tui=_TuiReads(), git=GitRepo(), clock=FakeClock(), out=StdOutput())
        ctx.herdr_docs = self.docs
        ctx.agents = AgentRegistry.from_context(ctx)
        a = argparse.Namespace(
            repo=str(self.repo), brief=str(self.brief), branch="dev/t", base=None, prep=None,
            name="w", title="t", label="t", kind="claude", model="opus", effort=None, profile=None,
            advisor=None, confirmed=False,
        )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            dispatch_cmd.cmd_dispatch(a, ctx=ctx)
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        args = list(start[start.index("--") + 1:])
        self.assertEqual(args[:2], ["--model", "opus"])
        self.assertEqual(self.exempt(args), self.wanted)

    def test_a_ledger_path_with_spaces_reaches_the_terminal_ui_whole(self):
        """herdr agent start quotes each argument as it types the command into the pane's shell (seen in a herdr
        session of its own: `--settings '/…/led ger/reads/a b.json'`), so pm.py hands it the path as it is."""
        ctx = make_ctx(self.root / "led ger")
        ctx.herdr_docs = self.docs
        ctx.agents = AgentRegistry.from_context(ctx)
        args = ctx.agents.read_settings("claude", ctx.agents.outside_reads(str(self.repo), str(self.brief)))
        self.assertEqual(args[0], "--settings")
        self.assertTrue(args[1].startswith(str(ctx.home.root / "reads")) and "'" not in args[1])  # not quoted twice
        self.assertEqual(self.exempt(args), self.wanted)
        self.assertEqual(shlex.split(shlex.join(["claude", *args])), ["claude", *args])  # the line herdr types

    def test_a_brief_in_a_wide_folder_is_let_through_alone(self):
        home = self.root / "users" / "me"
        home.mkdir(parents=True)
        with mock.patch.object(Path, "home", lambda *_: home):
            wide_cases = [Path("/"), home, home.parent, Path("/tmp"), Path(tempfile.gettempdir())]
            if os.name != "nt":
                wide_cases.append(Path("/private/tmp"))
            for wide in wide_cases:
                self.assertTrue(reads_mod.wide_folder(wide), wide)
            self.assertFalse(reads_mod.wide_folder(self.brief.parent))
            folders = [home, home.parent, Path(tempfile.gettempdir())]
            if Path("/tmp").is_dir():
                folders.insert(2, Path("/tmp"))
            for folder in folders:
                handle, name = tempfile.mkstemp(suffix=".md", dir=folder)
                os.close(handle)
                self.addCleanup(os.unlink, name)
                brief = Path(name)
                reads = self.ctx.agents.outside_reads(str(self.repo), name)
                self.assertIn(str(brief.resolve()), reads)  # the brief itself
                self.assertFalse({str(folder), str(folder.resolve())} & set(reads), folder)  # not all beside it
                self.assertIn(
                    f"Read(//{brief.resolve().as_posix().lstrip('/')})",
                    json.loads(Path(self.ctx.agents.read_settings("claude", reads)[1]).read_text())["permissions"]["allow"],
                )
            # A brief in a folder of its own: that folder, with the screenshots beside it.
            self.assertEqual(self.ctx.agents.outside_reads(str(self.repo), str(self.brief))[0], str(self.brief.parent))

    def test_reattach_brings_the_worker_back_with_the_same_reads(self):
        tree = self.root / "reattach-tree"
        tree.mkdir()
        task = {
            "id": "o-t", "title": "t", "repo": str(self.repo), "worktree": str(tree),
            "brief": str(self.brief), "worker": {"kind": "claude", "model": "opus"},
        }
        with mock.patch.object(workers_sessions, "_find_session_impl", lambda ctx, task, old_cwd="": None):
            fresh = workers_reattach.reattach_plan_for(self.ctx, task)
        self.assertEqual((fresh["how"], fresh["argv"][:3]), ("fresh", ["claude", "--model", "opus"]))
        self.assertEqual(self.exempt(fresh["argv"]), self.wanted)
        with mock.patch.object(
            workers_sessions, "_find_session_impl",
            lambda ctx, task, old_cwd="": {"kind": "claude", "id": "s1", "cwd": str(tree)},
        ):
            resumed = workers_reattach.reattach_plan_for(self.ctx, task)
        self.assertEqual((resumed["how"], resumed["argv"][-4:-2]), ("resume", ["--resume", "s1"]))
        self.assertEqual(self.exempt(resumed["argv"]), self.wanted)
        # A review thread: its own brief in the ledger's sent/, and the brief of the task it reviews.
        Ledger(self.ctx).save({**task, "status": "review", "owner": "pm", "project": "p", "created": self.ctx.clock.now()})
        sent = self.ctx.home.root / "sent" / "o-t-review.md"
        sent.parent.mkdir(parents=True, exist_ok=True)
        sent.write_text("审查")
        review = {
            "id": "o-t-review", "title": "审查", "repo": str(self.repo), "brief": str(sent),
            "review_of": "o-t", "worker": {"kind": "claude", "model": "sonnet"},
        }
        with mock.patch.object(workers_sessions, "_find_session_impl", lambda ctx, task, old_cwd="": None):
            rev_plan = workers_reattach.reattach_plan_for(self.ctx, review)
        self.assertEqual(
            self.exempt(rev_plan["argv"]),
            [str(sent.parent), *([str(sent.parent.resolve())] if sent.parent.resolve() != sent.parent else []), *self.wanted],
        )


class _HcDispatchBase(unittest.TestCase):
    """dispatch from a PM in herdr-core, with FakeHc: what it starts, labels and names."""
    CONFIG = POLICY

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-hc-dispatch-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = str(init_empty_repo(self.root / "pm-repo"))
        self.brief = Path(self.repo) / "brief.md"
        self.brief.write_text("brief")
        self.tabs: list[tuple[str, str]] = []
        self.names: list[str] = []
        self.labels: list[tuple[str, ...]] = []
        self.extra_terms: dict[str, dict] = {}
        self.hc = self._make_hc()
        self.ctx = make_ctx(
            self.root / "ctx",
            pane="hc:t1",
            hc=self.hc,
            tui=FakeTui(server_ok=False),
            config=self.CONFIG,
            git=GitRepo(worktree_home_fn=lambda _r: self.root / "wt" / "app"),
            clock=FakeClock(),
            out=StdOutput(),
        )
        self.ledger = Ledger(self.ctx)

    def _make_hc(self):
        parent = self

        class _DispatchHc(FakeHc):
            def run(self, argv, *, name="", cwd="", labels=(), bg=True, parent="", keep=False, no_parent=False, placement=(), env=None):
                test_case = self._owner
                test_case.names.append(name)
                addr = "t5g" if len(test_case.names) == 1 else "t5m"
                row = {
                    "address": addr, "id": addr, "state": "live", "name": name,
                    "cwd": str(cwd), "argv": list(argv), "labels": {}, "status": {"state": "idle"},
                }
                self.terminals[addr] = row
                return dict(row)

            def get_raw(self, term, *, errors=False):
                test_case = self._owner
                if term in test_case.extra_terms:
                    return dict(test_case.extra_terms[term])
                if term == "t1":
                    return {"address": "t1", "state": "live", "labels": {"herdr.space": "sp1", "pm": "proj"}}
                return super().get_raw(term, errors=errors)

            def label(self, term, *pairs, errors=False):
                self._owner.labels.append((term, *pairs))
                return super().label(term, *pairs, errors=errors)

            def name_tab(self, terminal, name, only_if=None, wait=0):
                self._owner.tabs.append((terminal, name))
                return True

        hc = _DispatchHc(clock=FakeClock())
        hc._owner = parent
        return hc

    def config(self, value):
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps(value))

    def dispatch(self, *argv):
        a = cli.build_parser().parse_args([
            "dispatch", *argv, "--repo", self.repo, "--here", "--brief",
            str(self.brief), "--kind", "claude", "--model", "opus",
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)
        return out.getvalue().splitlines()[0]


class WorkerTabs(_HcDispatchBase):
    """dispatch, review and reattach in herdr-core: labels always; a tab of its own only with tabs.new_tab."""
    CONFIG = {**POLICY, "tabs": {**POLICY["tabs"], "new_tab": True}}

    def test_bug_from_title(self):
        task = self.ledger.load(self.dispatch("修复 #12345 登录"))
        self.assertEqual(self.tabs[-1], ("t5g", "t5g-12345-修复登录"))
        self.assertEqual((task["agent"], task["bug"], task["tab"]), ("t5g-12345-修复登录", "12345", "修复登录"))
        self.assertEqual(task["in_place"], str(Path(self.repo).resolve()))  # --here: no worktree of its own
        self.assertFalse(task.get("worktree"))
        self.assertIn("herdr.space=sp1", self.labels[-1])
        self.assertFalse(any(x.startswith("herdr.seen") for x in self.labels[-1]))

    def test_no_bug_and_a_given_address(self):
        self.assertEqual(self.ledger.load(self.dispatch("A004 的循环", "--tab", "A004-循环"))["agent"], "t5g-A004-循环")
        tid = self.dispatch("登录", "--tab", "t9z-12345-登录修复")  # an address given: the real one takes its place
        self.assertEqual(self.ledger.load(tid)["agent"], "t5m-12345-登录修复")

    def test_bug_flag_wins(self):
        self.assertEqual(
            self.ledger.load(self.dispatch("修复 #12345 登录", "--bug", "54321", "--tab", "12345-登录"))["agent"],
            "t5g-54321-12345-登录",
        )

    def test_here_allows_plain_non_git_directory_while_branch_requires_git(self):
        plain = self.root / "plain-folder"
        plain.mkdir()
        a_here = cli.build_parser().parse_args([
            "dispatch", "plain smoke", "--repo", str(plain), "--here",
            "--brief", str(self.brief), "--kind", "claude", "--model", "opus",
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dispatch_cmd.cmd_dispatch(a_here, ctx=self.ctx)
        tid = out.getvalue().splitlines()[0]
        task = self.ledger.load(tid)
        self.assertEqual(task["repo"], str(plain.resolve()))
        self.assertEqual(task["in_place"], str(plain.resolve()))
        self.assertFalse(task.get("worktree"))

        a_branch = cli.build_parser().parse_args([
            "dispatch", "needs git", "--repo", str(plain), "--branch", "dev/x",
            "--brief", str(self.brief), "--kind", "claude",
        ])
        with self.assertRaises(SystemExit) as err:
            dispatch_cmd.cmd_dispatch(a_branch, ctx=self.ctx)
        self.assertIn("is not in a git repository", str(err.exception))

    def test_review(self):
        tid = self.dispatch("修复 #12345 登录")
        task = self.ledger.load(tid).raw
        task.update(branch="main", worktree=self.repo, status="review")
        self.ledger.save(task)
        a = cli.build_parser().parse_args(["review", tid, "--kind", "claude", "--model", "fable"])
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmd.cmd_review(a, ctx=self.ctx)
        review = self.ledger.load(f"{tid}-review")
        self.assertEqual(self.names[-1], "t5g-12345-review")  # the hc name: a-z 0-9 - _ only
        self.assertEqual(
            (review["agent"], review["tab"], review["bug"]),
            ("t5m-12345-审查-修复登录", "审查-修复登录", "12345"),
        )

    def test_off_by_default_the_worker_stays_under_the_pm(self):
        self.config(POLICY)
        task = self.ledger.load(self.dispatch("修复 #12345 登录", "--name", "login-fix"))
        self.assertEqual(self.tabs, [])
        self.assertEqual(task["agent"], "login-fix")
        self.assertEqual(self.labels[-1], ("t5g", f"task={task['id']}"))  # no herdr.space / herdr.tab

    def test_dry_run_registers_nothing(self):
        before = {p.name for p in self.ctx.home.tasks.glob("*.json")} if self.ctx.home.tasks.exists() else set()
        a = cli.build_parser().parse_args([
            "dispatch", "看一下", "--repo", self.repo, "--branch", "dev/x", "--brief",
            str(self.brief), "--profile", "deep", "--dry-run",
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)
        plan = json.loads(out.getvalue())
        self.assertEqual((plan["what"], plan["kind"], plan["asks_user_first"]), ("dispatch", "claude", True))
        self.assertEqual(plan["argv"][:2], ["zsh", "-ic"])  # through claude.launcher
        after = {p.name for p in self.ctx.home.tasks.glob("*.json")} if self.ctx.home.tasks.exists() else set()
        self.assertEqual(after, before)
        self.assertEqual(self.names, [])

    def test_task_takes_up_a_registered_one(self):
        with contextlib.redirect_stdout(io.StringIO()):
            tid = ledger_cmd.cmd_new(argparse.Namespace(
                repo=self.repo, title="先登记的", status="proposed", owner="pm",
                base=None, workspace=None, pane=None, agent=None, branch=None,
                worktree=None, brief=None, slug=None, note="handed to PM",
                parent=None, kind=None,
            ), ctx=self.ctx)
        a = cli.build_parser().parse_args([
            "dispatch", "--task", tid, "--repo", self.repo, "--here", "--brief",
            str(self.brief), "--kind", "claude", "--model", "opus",
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)
        task = self.ledger.load(tid)
        self.assertEqual((task["status"], task["title"], task["pane"]), ("in_progress", "先登记的", "hc:t5g"))
        self.assertTrue(task["dispatched"])


class TakeUp(_HcDispatchBase):
    CONFIG = POLICY

    def register(self, title, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            tid = ledger_cmd.cmd_new(argparse.Namespace(
                repo=self.repo, title=title, status="proposed", owner="pm", base=None,
                workspace=None, pane=None, agent=None, branch=None, worktree=None,
                brief=None, slug=None, note="handed to PM", parent=None, kind=None,
            ), ctx=self.ctx)
        task = self.ledger.load(tid).raw
        task.update(kw)
        self.ledger.save(task)
        return tid

    def take_up(self, tid, repo=None):
        a = cli.build_parser().parse_args([
            "dispatch", "--task", tid, "--repo", repo or self.repo, "--here",
            "--brief", str(self.brief), "--kind", "claude", "--model", "opus",
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)

    def test_a_task_with_a_live_worker_is_refused(self):
        tid = self.register("已有人在做", status="in_progress", pane="hc:t8", dispatched=True)
        self.extra_terms["t8"] = {"address": "t8", "state": "live"}
        with self.assertRaises(SystemExit) as stop:
            self.take_up(tid)
        self.assertIn("hc:t8", str(stop.exception))
        self.assertEqual(self.names, [])  # no second worker
        self.assertEqual(self.ledger.load(tid)["status"], "in_progress")

    def test_a_hand_off_from_a_live_session_is_taken_up(self):
        tid = self.register("交给 PM 的", pane="hc:t8")  # proposed by a session that is still open
        self.extra_terms["t8"] = {"address": "t8", "state": "live"}
        self.take_up(tid)
        self.assertEqual(self.ledger.load(tid)["pane"], "hc:t5g")

    def test_another_projects_task_is_refused(self):
        tid = self.register("别的项目的")
        other = str(init_empty_repo(self.root / "pm-other"))
        with self.assertRaises(SystemExit) as stop:
            self.take_up(tid, repo=other)
        self.assertIn("--repo", str(stop.exception))
        self.assertEqual(self.names, [])

    def test_here_asked_first_then_confirmed_takes_up_the_same_task(self):
        def run(*more):
            a = cli.build_parser().parse_args([
                "dispatch", "设计方案", "--repo", self.repo, "--here", "--brief",
                str(self.brief), "--profile", "deep", *more,
            ])
            with contextlib.redirect_stdout(io.StringIO()):
                dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)

        before = {t["id"] for t in self.ledger.all_tasks()}
        run()
        asked = [t for t in self.ledger.all_tasks() if t["id"] not in before]
        self.assertEqual([t["status"] for t in asked], ["blocked"])
        run()  # asked again before the user answered: still the same question
        run("--confirmed")
        after = [t for t in self.ledger.all_tasks() if t["id"] not in before]
        self.assertEqual([(t["id"], t["status"]) for t in after], [(asked[0]["id"], "in_progress")])
        self.assertFalse(self.ledger.load(asked[0]["id"]).get("held"))


class DeepPreapproval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-deep-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = str(init_empty_repo(self.root / "pm-deep-repo"))
        self.brief = Path(self.repo) / "brief.md"
        self.brief.write_text("brief")
        self.ctx = make_ctx(
            self.root / "ctx",
            pane="hc:t1",
            hc=FakeHc(clock=FakeClock()),
            tui=FakeTui(server_ok=False),
            config={},
            git=GitRepo(worktree_home_fn=lambda _r: self.root / "wt" / "app"),
            clock=FakeClock(),
            out=StdOutput(),
        )

    def config(self, value):
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps(value))

    def plan(self, *more):
        a = cli.build_parser().parse_args([
            "dispatch", "设计", "--repo", self.repo, "--branch", "dev/d", "--brief",
            str(self.brief), "--profile", "deep", "--dry-run", *more,
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)
        return json.loads(out.getvalue())

    def test_default_asks(self):
        self.assertTrue(self.plan()["asks_user_first"])
        self.assertFalse(self.plan("--confirmed")["asks_user_first"])

    def test_config_preapproves(self):
        self.config({"deep": {"confirmed": True}})
        self.assertFalse(self.plan()["asks_user_first"])
        self.config({"deep": {"confirmed": ["another-project"]}})
        self.assertTrue(self.plan()["asks_user_first"])  # scoped to the projects it names
        self.config({"deep": {"confirmed": [Path(self.repo).name]}})
        self.assertFalse(self.plan()["asks_user_first"])

    def test_a_repository_inside_a_project_folder_goes_by_that_project(self):
        folder = (self.root / "pm-folder").resolve()
        inner = init_empty_repo(folder / "service")
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        record = self.ctx.home.registrations / f"{project_slug(folder)}.json"
        record.write_text(json.dumps({"name": f"pm-{folder.name}", "project": folder.name, "repo": str(folder)}))
        self.assertEqual(codex_pool.project_names_for(self.ctx, str(inner)), {"service", folder.name})
        self.config({"deep": {"confirmed": [folder.name]}, "codex": {"projects": [folder.name], "profiles": ["acct"]}})
        self.assertTrue(codex_pool.deep_confirmed_for(self.ctx, str(inner)))
        self.assertEqual([p["name"] for p in codex_pool.codex_pool_for(self.ctx, str(inner))], ["acct"])
        self.assertIn(folder, codex_pool.project_places_for(self.ctx, str(inner)))  # its sessions count with the project folder's
        self.config({"deep": {"confirmed": ["elsewhere"]}})
        self.assertFalse(codex_pool.deep_confirmed_for(self.ctx, str(inner)))

    def test_the_question_says_how_past_it(self):
        out = io.StringIO()
        a = cli.build_parser().parse_args([
            "dispatch", "设计", "--repo", self.repo, "--branch", "dev/q", "--brief",
            str(self.brief), "--profile", "deep",
        ])
        with contextlib.redirect_stdout(out):
            tid = dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)
        self.assertEqual(Ledger(self.ctx).load(tid)["status"], "blocked")
        self.assertIn("--confirmed", out.getvalue())
        self.assertIn('"deep": {"confirmed": true}', out.getvalue())
        self.assertIn("Do not switch to another profile or model", out.getvalue())

    def test_a_preapproved_dispatch_says_so(self):
        self.config({"deep": {"confirmed": True}})
        a = cli.build_parser().parse_args([
            "dispatch", "设计", "--repo", self.repo, "--branch", "dev/p", "--brief",
            str(self.brief), "--profile", "deep",
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)
        task = next(
            t for t in Ledger(self.ctx).all_tasks()
            if t.get("branch") == "dev/p" and t["repo"] == self.ctx.git.main_root(self.repo)
        )
        self.assertEqual(task["status"], "in_progress")
        self.assertIn("deep.confirmed", task["log"][0]["text"])


class ThinDispatchAskTests(unittest.TestCase):
    """Phase 2 (`O-b`, D4): `pm.py dispatch --ask` thin dispatch brief assembly and `--dry-run`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-thin-ask-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        raw_repo = make_repo(self.root)
        self.repo = str(raw_repo[0] if isinstance(raw_repo, tuple) else raw_repo)
        self.clock = FakeClock("2026-11-26 09:00:00")
        self.hc = FakeHc(clock=self.clock)
        self.ctx = make_ctx(self.root / "ledger", pane="hc:t1", hc=self.hc, clock=self.clock, out=StdOutput())
        self.ctx.git = GitRepo(worktree_base=self.root / "worktrees")
        # Record a project memory and recent conversation so thin brief includes pointers + memory.
        Conversation(self.ctx, self.repo).record("user", text="这个 @ 弹层找不到历史线程")
        Conversation(self.ctx, self.repo).record("pm", text="我派一个线程排查 @ 弹层的来源。")
        mem_dir = self.ctx.home.memory_dir(self.repo)
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / "sample-rule.md").write_text(
            "---\nname: sample-rule\ndescription: Always verify thin briefs\ntype: project\ntopic: architecture\n---\nBody\n",
            encoding="utf-8",
        )

    def test_thin_dispatch_dry_run_assembles_brief_with_verbatim_words_attachments_note_and_pointers(self):
        att_file = self.root / "screenshot-evidence.png"
        att_file.write_bytes(b"\x89PNG\r\n")
        a = cli.build_parser().parse_args([
            "dispatch", "Fix @ mention lookup",
            "--repo", self.repo,
            "--branch", "dev/mention-fix",
            "--ask", "这个 @ 的时候找不到 {history} 线程",
            "--attach", str(att_file),
            "--note", "Focus on model.js mention indexing.",
            "--dry-run",
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)
        plan = json.loads(out.getvalue())
        self.assertTrue(plan["thin_brief"])
        preview = plan["brief_preview"]
        self.assertIn("这个 @ 的时候找不到 {history} 线程", preview)
        self.assertIn(str(att_file.resolve()), preview)
        self.assertIn("Focus on model.js mention indexing.", preview)
        self.assertIn("conversation.jsonl", preview)
        self.assertIn("这个 @ 弹层找不到历史线程", preview)
        self.assertIn("Investigate the codebase", preview)
        self.assertIn("report `blocked`", preview)
        # Dry run writes no thin-*.md file into sent/.
        self.assertEqual(list(self.ctx.home.sent_dir.glob("thin-*.md")), [])

    def test_thin_dispatch_real_run_appends_report_and_memory_sections_and_supports_zh(self):
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({"lang": "zh"}), encoding="utf-8")
        att_file = self.root / "trace.log"
        att_file.write_text("trace line\n", encoding="utf-8")
        a = cli.build_parser().parse_args([
            "dispatch",
            "--repo", self.repo,
            "--branch", "dev/zh-thin",
            "--ask", "修一下活动行计时不刷新",
            "--attach", str(att_file),
            "--note", "先查 main.js 的 1 秒定时器",
            "--async",
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dispatch_cmd.cmd_dispatch(a, ctx=self.ctx)
        task_id = out.getvalue().strip().splitlines()[0]
        task = Ledger(self.ctx).load(task_id).raw
        self.assertEqual(task["title"], "修一下活动行计时不刷新")
        self.assertTrue(Path(task["brief"]).is_file())
        sent_text = self.ctx.home.sent(task_id).read_text(encoding="utf-8")
        self.assertIn("修一下活动行计时不刷新", sent_text)
        self.assertIn(str(att_file.resolve()), sent_text)
        self.assertIn("先查 main.js 的 1 秒定时器", sent_text)
        self.assertIn("先从第一性原理查清代码与现场", sent_text)
        self.assertIn("汇报（任务", sent_text)
        self.assertIn("sample-rule", sent_text)

    def test_thin_dispatch_rejects_mixing_brief_and_ask_or_orphan_note(self):
        brief = self.root / "b.md"
        brief.write_text("existing brief\n", encoding="utf-8")
        with self.assertRaises(Refused):
            Workers(self.ctx).dispatch(
                dispatch_cmd._request_from_args(
                    cli.build_parser().parse_args([
                        "dispatch", "Mix", "--repo", self.repo, "--branch", "dev/m",
                        "--brief", str(brief), "--ask", "do thing", "--dry-run",
                    ])
                )
            )
        with self.assertRaises(Refused):
            Workers(self.ctx).dispatch(
                dispatch_cmd._request_from_args(
                    cli.build_parser().parse_args([
                        "dispatch", "NoAsk", "--repo", self.repo, "--branch", "dev/n",
                        "--brief", str(brief), "--note", "orphan note", "--dry-run",
                    ])
                )
            )

    def test_multifolder_dispatch_selection_outside_reads_and_verify_alias(self):
        from pmlib.review.land import verify_commands_for

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = make_ctx(root / "ledger")
            ctx.pane = "hc:pm1"
            repo_a = root / "repos/backend"
            repo_b = root / "repos/frontend"
            docs_only = root / "repos/specs"
            for d in (repo_a, repo_b, docs_only):
                d.mkdir(parents=True)
            ctx.git.roots[str(repo_a.resolve())] = str(repo_a.resolve())
            ctx.git.roots[str(repo_b.resolve())] = str(repo_b.resolve())
            # `docs_only` is a non-Git folder (no entry in `ctx.git.roots`)
            ctx.home.registrations.mkdir(parents=True, exist_ok=True)
            ctx.home.project("single-git").root.mkdir(parents=True, exist_ok=True)
            ctx.home.registration("single-git").write_text(json.dumps({
                "name": "pm-single-git", "slug": "single-git", "project": "Single Git",
                "folders": [
                    {"path": str(docs_only), "alias": "specs", "git": False},
                    {"path": str(repo_a), "alias": "backend", "git": True},
                ],
                "repo": str(docs_only),
            }), encoding="utf-8")

            # 1) 1 Git + 1 non-Git folder: `--branch` auto-selects the single Git repo & adds sibling to reads.
            plan1 = Workers(ctx).dispatch(
                dispatch_cmd._request_from_args(
                    cli.build_parser().parse_args([
                        "dispatch", "Auto Git", "--repo", str(docs_only), "--branch", "feat/a",
                        "--kind", "claude", "--ask", "build endpoint", "--dry-run",
                    ])
                )
            ).dry_run_plan
            assert plan1 is not None
            self.assertEqual(plan1["project_slug"], "single-git")
            self.assertEqual(plan1["folder"], "backend")
            settings_idx = plan1["argv"].index("--settings") + 1
            settings_text = Path(plan1["argv"][settings_idx]).read_text(encoding="utf-8")
            self.assertIn(str(docs_only.resolve()), settings_text)

            # 2) >=2 folders: `--here` without `--folder` via slug or `.` refuses with folder choices.
            with self.assertRaises(Refused) as err_here:
                Workers(ctx).dispatch(
                    dispatch_cmd._request_from_args(
                        cli.build_parser().parse_args([
                            "dispatch", "Ambig Here", "--repo", "single-git", "--here",
                            "--ask", "inspect", "--dry-run",
                        ])
                    )
                )
            self.assertIn("--folder backend", str(err_here.exception))
            self.assertIn("--folder specs", str(err_here.exception))

            # 3) >=2 Git repos: `--branch` with slug or `.` without `--folder` refuses and lists both Git aliases.
            ctx.home.registration("two-git").write_text(json.dumps({
                "name": "pm-two-git", "slug": "two-git", "project": "Two Git",
                "folders": [
                    {"path": str(repo_a), "alias": "backend", "git": True},
                    {"path": str(repo_b), "alias": "frontend", "git": True},
                    {"path": str(docs_only), "alias": "specs", "git": False},
                ],
                "repo": str(repo_a),
            }), encoding="utf-8")
            with self.assertRaises(Refused) as err_two:
                Workers(ctx).dispatch(
                    dispatch_cmd._request_from_args(
                        cli.build_parser().parse_args([
                            "dispatch", "Pick Repo", "--repo", "two-git", "--branch", "feat/b",
                            "--ask", "update ui", "--dry-run",
                        ])
                    )
                )
            self.assertIn("--folder backend", str(err_two.exception))
            self.assertIn("--folder frontend", str(err_two.exception))
            self.assertNotIn("--folder specs", str(err_two.exception))

            # 3b) Explicit `--repo` matching an exact linked folder path auto-selects it without `--folder`,
            # while cwd `--repo .` without `--folder` still refuses.
            plan_exact = Workers(ctx).dispatch(
                dispatch_cmd._request_from_args(
                    cli.build_parser().parse_args([
                        "dispatch", "Direct Repo B", "--repo", str(repo_b), "--branch", "feat/direct",
                        "--kind", "claude", "--ask", "update ui", "--dry-run",
                    ])
                )
            ).dry_run_plan
            assert plan_exact is not None
            self.assertEqual(plan_exact["project_slug"], "two-git")
            self.assertEqual(plan_exact["folder"], "frontend")
            settings_exact = Path(plan_exact["argv"][plan_exact["argv"].index("--settings") + 1]).read_text(encoding="utf-8")
            self.assertIn(str(repo_a.resolve()), settings_exact)
            self.assertIn(str(docs_only.resolve()), settings_exact)
            old_cwd = os.getcwd()
            os.chdir(repo_b)
            try:
                with self.assertRaises(Refused) as err_dot:
                    Workers(ctx).dispatch(
                        dispatch_cmd._request_from_args(
                            cli.build_parser().parse_args([
                                "dispatch", "Dot Ambig", "--repo", ".", "--branch", "feat/dot",
                                "--ask", "update ui", "--dry-run",
                            ])
                        )
                    )
                self.assertIn("--folder backend", str(err_dot.exception))
                self.assertIn("--folder frontend", str(err_dot.exception))
            finally:
                os.chdir(old_cwd)

            # 4) Explicit `--folder frontend` succeeds, persists `project_slug` & `folder_alias`, includes siblings.
            res_b = Workers(ctx).dispatch(
                dispatch_cmd._request_from_args(
                    cli.build_parser().parse_args([
                        "dispatch", "Frontend Feature", "--repo", "two-git", "--folder", "frontend",
                        "--branch", "feat/ui", "--ask", "build ui", "--async",
                    ])
                )
            )
            saved = ctx.store.task(res_b.task_id)
            assert saved is not None
            self.assertEqual((saved["project_slug"], saved["folder_alias"], saved["repo"]),
                             ("two-git", "frontend", str(repo_b.resolve())))
            sent_text = ctx.home.sent(res_b.task_id).read_text(encoding="utf-8")
            self.assertIn("backend", sent_text)
            self.assertIn("specs", sent_text)

            # 5) 0-folder project `--here` runs in `projects/<slug>/` without requiring a repo folder.
            ctx.home.registration("empty-proj").write_text(json.dumps({
                "name": "pm-empty-proj", "slug": "empty-proj", "project": "Empty",
                "folders": [], "repo": "",
            }), encoding="utf-8")
            plan0 = Workers(ctx).dispatch(
                dispatch_cmd._request_from_args(
                    cli.build_parser().parse_args([
                        "dispatch", "Zero Here", "--repo", "empty-proj", "--here",
                        "--ask", "organize notes", "--dry-run",
                    ])
                )
            ).dry_run_plan
            assert plan0 is not None
            self.assertEqual(plan0["project_slug"], "empty-proj")
            self.assertEqual(Path(plan0["cwd"]), ctx.home.project("empty-proj").root)

            # 6) `verify.<alias>` takes precedence over `verify`.
            pdir = ctx.home.project("two-git").root
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "verify").write_text("pytest default\n", encoding="utf-8")
            (pdir / "verify.frontend").write_text("npm test\n", encoding="utf-8")
            self.assertEqual(
                verify_commands_for(ctx, repo_b, project_slug_val="two-git", folder_alias="frontend"),
                ["npm test"],
            )
            self.assertEqual(
                verify_commands_for(ctx, repo_a, project_slug_val="two-git", folder_alias="backend"),
                ["pytest default"],
            )


if __name__ == "__main__":
    unittest.main()
