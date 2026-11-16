"""Targeted tests for the rotation and dispatch helpers. Run: python3 -m unittest skill/pm/scripts/test_pm.py"""
import argparse
import contextlib
import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HOME = tempfile.mkdtemp()
os.environ["PM_HOME"] = HOME
os.environ.pop("HERDR_PANE_ID", None)
os.environ.pop("HC_TERMINAL_ID", None)
import sys
sys.path.insert(0, str(Path(__file__).parent))
import pm  # noqa: E402
pm.HERDR_DOCS = Path(HOME) / "no-herdr-app"  # the tests do not see this machine's Herdr docs
pm.claude_dir = lambda: Path(HOME) / "claude"  # nor its Claude Code skills and plugins


def row(kind, content, usage=None, side=False):
    message = {"content": content}
    if usage:
        message["usage"] = usage
    return json.dumps({"type": kind, "message": message, "isSidechain": side})


class Rotation(unittest.TestCase):
    def transcript(self):
        path = Path(HOME) / "session.jsonl"
        path.write_text("\n".join([
            row("user", "先做看板"),
            row("assistant", [{"type": "text", "text": "好，开始。"}], {"input_tokens": 10, "cache_read_input_tokens": 1000}),
            row("user", [{"type": "tool_result", "content": "ok"}]),
            row("assistant", [{"type": "text", "text": "看板做完了。"}],
                {"input_tokens": 5, "cache_read_input_tokens": 250000, "cache_creation_input_tokens": 20}),
            row("assistant", [{"type": "text", "text": "side"}], {"input_tokens": 999999}, side=True),
            row("user", "<system-reminder>notice</system-reminder>"),
            row("user", "不要直角线"),
        ]))
        return str(path)

    def test_context_is_the_input_side_of_the_latest_main_call(self):
        self.assertEqual(pm.context_tokens(self.transcript()), 250025)
        self.assertEqual(pm.context_tokens("/nonexistent"), 0)

    def test_tail_pairs_what_the_user_typed_with_the_final_reply(self):
        tail = pm.conversation_tail(self.transcript())
        self.assertEqual([t["user"] for t in tail], ["先做看板", "不要直角线"])
        self.assertEqual(tail[0]["pm"], "看板做完了。")  # the later text of the turn wins; tool results are skipped
        self.assertEqual(tail[1]["pm"], "")

    def test_handover_carries_decisions_notes_and_open_work(self):
        repo = tempfile.mkdtemp()
        root, name = pm.project_root(repo), Path(pm.project_root(repo)).name
        pm.cmd_decide(type("A", (), {"repo": repo, "text": "连线不用直角", "quote": "不要有直角线"}))
        (pm.project_dir(root) / "handover.md").write_text("用户正要验证点击跳转\n")
        task = {"id": f"{name}-a", "title": "做看板", "project": name, "repo": root, "status": "in_progress",
                "owner": "pm", "base": "main", "pane": "hc:t9", "created": pm.now()}
        pm.note(task, "dispatched")
        pm.save(task)
        for full in (False, True):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                pm.cmd_handover(type("A", (), {"repo": repo, "turns": 6, "full": full}))
            text = out.getvalue()
            for part in ("连线不用直角", "用户正要验证点击跳转", f"{name}-a", "dispatched"):
                self.assertIn(part, text)
            # The user's words are in the whole record (and `pm.py decisions`), not in the short handover.
            self.assertEqual('the user\'s words: "不要有直角线"' in text, full)

    def test_builtin_text_is_english_unless_configured(self):
        self.assertEqual(pm.tr("User", "用户"), "User")
        (Path(HOME) / "config.json").write_text(json.dumps({"lang": "zh"}))
        try:
            self.assertEqual(pm.tr("User", "用户"), "用户")
            self.assertEqual(pm.dash_state()["lang"], "zh")
        finally:
            (Path(HOME) / "config.json").unlink()

    def test_successor_keeps_flags_but_not_the_old_session(self):
        args = ["--resume", "abc-123", "--mcp-config", "/x/mcp.json", "--model", "old", "--chrome", "earlier prompt"]
        self.assertEqual(pm.successor_argv("claude", args, "new", "接手"),
                         ["claude", "--mcp-config", "/x/mcp.json", "--chrome", "--model", "new", "--", "接手"])
        # A flag that takes a value keeps it. `--allowed-tools` takes any number of values, so the prompt comes
        # after `--`; without it claude reads the prompt as one more tool name and starts with nothing to do.
        args = ["--plugin-dir", "/p", "--allowed-tools", "a", "--allowed-tools", "b", "--resume", "abc"]
        self.assertEqual(pm.successor_argv("claude", args, "", "接手"),
                         ["claude", "--plugin-dir", "/p", "--allowed-tools", "a", "--allowed-tools", "b", "--", "接手"])
        # The outgoing session was itself started this way: its `--` and first prompt are not carried over.
        args = ["--allowed-tools", "a", "--", "上一任的接手提示"]
        self.assertEqual(pm.successor_argv("claude", args, "", "接手"), ["claude", "--allowed-tools", "a", "--", "接手"])
        args = ["--resume", "abc-123", "--mcp-config", "/x/mcp.json", "--model", "old", "--chrome", "earlier prompt"]
        # Other agents start from their registry entry; the outgoing session's flags are not theirs to carry.
        self.assertEqual(pm.successor_argv("codex", args, "new", "接手"),
                         ["codex", "-c", "check_for_update_on_startup=false", "-m", "new", "接手"])
        self.assertEqual(pm.successor_argv("gemini", args, "", "接手"), ["gemini"])  # prompt is typed in afterwards


class Commands(unittest.TestCase):
    def test_every_subcommand_has_its_function(self):
        import re
        names = re.findall(r'sub\.add_parser\("([\w-]+)"', Path(pm.__file__).read_text())
        names += re.findall(r'\("(archive|restore)", "', Path(pm.__file__).read_text())
        self.assertIn("rotate", names)
        self.assertEqual([n for n in names if not hasattr(pm, "cmd_" + n.replace("-", "_"))], [])

    def test_hc_json_flag_stays_out_of_the_started_program(self):
        seen = []
        run = pm.subprocess.run
        pm.subprocess.run = lambda argv, **kw: seen.append(argv) or type("R", (), {"returncode": 0, "stdout": "{}"})()
        try:
            pm.hc("run", "--bg", "--", "codex", "-m", "x")
            pm.hc("get", "t1")
        finally:
            pm.subprocess.run = run
        self.assertEqual(seen, [["hc", "run", "--bg", "--json", "--", "codex", "-m", "x"], ["hc", "get", "t1", "--json"]])

    def test_the_pm_tab_is_named_after_the_project(self):
        listing = {"spaces": [{"tabs": [{"id": "tb1", "name": "PM-app", "terminals": [{"terminal": "t1"}]},
                                        {"id": "tb2", "name": "3", "terminals": [{"terminal": "t2"}]}]}]}
        seen = []
        run = pm.subprocess.run
        pm.subprocess.run = lambda argv, **kw: seen.append(argv[1:]) or type(
            "R", (), {"returncode": 0, "stdout": json.dumps(listing)})()
        try:
            pm.name_tab("t2", pm.pm_tab_name("/x/app"))   # the new PM's tab
            pm.name_tab("t1", "", only_if="PM-app")        # the old PM's tab gets its number back
            pm.name_tab("t2", "", only_if="PM-app")        # a tab the user named otherwise is left alone
            pm.name_tab("t9", "PM-app")                    # no tab (a sub-agent): nothing
        finally:
            pm.subprocess.run = run
        renames = [json.loads(a[2]) for a in seen if a[0] == "do"]
        self.assertEqual(renames, [{"id": "tb2", "name": "PM-app"}, {"id": "tb1", "name": ""}])

    def test_worker_is_a_sub_agent_that_outlives_the_pm(self):
        pane = pm.PANE
        try:
            pm.PANE = "hc:t9"
            self.assertEqual(pm.worker_placement(), ["--parent", "t9", "--outlive-parent", "--no-notify"])
        finally:
            pm.PANE = pane

    def test_merging_a_dispatched_task_retires_it(self):
        repo = tempfile.mkdtemp()
        base = {"project": "p", "repo": repo, "status": "in_progress", "owner": "pm", "base": "main",
                "created": pm.now(), "title": "t"}
        pm.save({**base, "id": "p-auto", "dispatched": True})
        pm.save({**base, "id": "p-kept", "dispatched": True, "branch": "dev/x"})
        pm.save({**base, "id": "p-own", "branch": "dev/y"})
        args = lambda id, keep=False: type("A", (), {"id": id, "status": "merged", "note": None, "keep": keep})
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_update(args("p-auto"))
            pm.cmd_update(args("p-kept", keep=True))
            pm.cmd_update(args("p-own"))
        self.assertTrue(pm.load("p-auto").get("retired"))
        self.assertFalse(pm.load("p-kept").get("retired"))
        self.assertFalse(pm.load("p-own").get("retired"))  # not dispatched by the PM: never retired automatically
        self.assertTrue(pm.needs_cleanup(pm.load("p-kept")))
        self.assertFalse(pm.needs_cleanup(pm.load("p-auto")))

    def test_retire_removes_the_worktree_a_worker_made_itself(self):
        # `pm.py new --branch` records no worktree: retire finds the checkout that has the branch.
        repo = Path(tempfile.mkdtemp()).resolve() / "app"
        tree = repo.parent / "tree"
        git = lambda *args: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                           check=True, capture_output=True, text=True).stdout
        repo.mkdir()
        git("init", "-q", "-b", "main")
        git("commit", "-q", "--allow-empty", "-m", "init")
        git("worktree", "add", "-q", "-b", "dev/own", str(tree), "main")
        git("branch", "dev/here")
        base = {"project": "app", "repo": str(repo), "status": "merged", "owner": "self", "base": "main",
                "created": pm.now(), "title": "t"}
        pm.save({**base, "id": "app-own", "branch": "dev/own", "pane": "hc:t7"})
        pm.save({**base, "id": "app-own-2", "branch": "dev/own", "pane": "hc:t7"})
        pm.save({**base, "id": "app-here", "branch": "dev/here"})
        hc, herdr = pm.hc, pm.herdr
        calls, terminal = [], {"state": "live", "cwd": str(tree / "src")}

        def fake_hc(*args, **kw):
            calls.append(args[0])
            return dict(terminal) if args[0] == "get" else None
        pm.hc, pm.herdr = fake_hc, lambda *args, **kw: None

        def retire(task_id):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                try:
                    pm.cmd_retire(type("A", (), {"id": task_id, "force": False}))
                except SystemExit as stop:
                    return f"refused: {stop}"
            return out.getvalue()
        try:
            self.assertIn("another task still uses it", retire("app-own"))  # the last task on the branch removes it
            self.assertTrue(tree.is_dir())
            # The session that owns the task still sits in the worktree: its directory and its terminal both stay.
            self.assertEqual(retire("app-own-2"), f"refused: worktree {tree} is kept: hc:t7 still works in it")
            self.assertTrue(tree.is_dir())
            self.assertFalse(pm.load("app-own-2").get("retired"))
            terminal["cwd"] = str(repo)  # the session has left the worktree
            said = retire("app-own-2")
            self.assertIn(f"removed worktree {tree}, branch dev/own", said)
            self.assertFalse(tree.exists())
            self.assertEqual(git("branch", "--list", "dev/own"), "")
            self.assertEqual(set(calls), {"get"})  # no terminal was ended or removed
            # A branch that is checked out in the main checkout stays, and retire says where.
            git("checkout", "-q", "dev/here")
            self.assertIn(f"removed nothing; branch dev/here is kept: checked out in {repo}", retire("app-here"))
            self.assertTrue(repo.is_dir())
            self.assertNotEqual(git("branch", "--list", "dev/here"), "")
        finally:
            pm.hc, pm.herdr = hc, herdr

    def test_retire_checks_main_once_the_base_branch_is_deleted(self):
        repo, git = make_repo()
        git("branch", "dev/old")
        git("merge", "-q", "--no-ff", "dev/x", "-m", "merge dev/x")
        git("branch", "-q", "dev/y", "dev/old")
        git("checkout", "-q", "dev/y")
        (repo / "y.txt").write_text("y\n")
        git("add", "y.txt")
        git("commit", "-q", "-m", "add y.txt")
        git("checkout", "-q", "main")
        git("branch", "-D", "dev/old")  # the base, merged and deleted
        task = {"project": repo.name, "repo": str(repo), "status": "merged", "owner": "pm", "base": "dev/old",
                "created": pm.now(), "title": "t"}
        pm.save({**task, "id": "gone-in", "branch": "dev/x"})
        pm.save({**task, "id": "gone-out", "branch": "dev/y"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pm.cmd_retire(argparse.Namespace(id="gone-in", force=False))
        self.assertIn("merged into main (dev/old no longer exists)", out.getvalue())
        self.assertEqual(git("branch", "--list", "dev/x"), "")
        with self.assertRaises(SystemExit) as stop:
            pm.cmd_retire(argparse.Namespace(id="gone-out", force=False))
        self.assertEqual(str(stop.exception.code),
                         "dev/y is not merged into main (dev/old no longer exists); pass --force to discard it")
        self.assertFalse(pm.load("gone-out").get("retired"))

    def test_worker_command(self):
        a = type("A", (), {"kind": "codex", "model": "m", "effort": "high"})
        self.assertEqual(pm.worker_argv(a), ["codex", "-c", "check_for_update_on_startup=false", "-m", "m", "-c", 'model_reasoning_effort="high"'])
        a.kind, a.effort = "claude", "xhigh"
        self.assertEqual(pm.worker_argv(a), ["claude", "--model", "m", "--effort", "xhigh"])
        a.effort = ""
        self.assertEqual(pm.worker_argv(a), ["claude", "--model", "m"])  # no effort given: no --effort
        a.effort = "high"
        a.kind = "pi"
        self.assertEqual(pm.worker_argv(a), ["pi", "--model", "m", "--thinking", "high"])
        a.kind = "mine --yes"  # not in the registry: run as written
        self.assertEqual(pm.worker_argv(a), ["mine", "--yes"])

    def test_agent_kinds_can_be_added_in_config(self):
        (Path(HOME) / "config.json").write_text(json.dumps(
            {"agents": {"mine": {"argv": ["mine", "run"], "model": ["--m={}"], "prompt_arg": True}}}))
        try:
            self.assertEqual(pm.agent_argv("mine", "x", prompt="go"), ["mine", "run", "--m=x", "go"])
            self.assertTrue(pm.takes_prompt("mine"))
            self.assertFalse(pm.takes_prompt("gemini"))
        finally:
            (Path(HOME) / "config.json").unlink()

    def test_the_kind_of_a_terminal_comes_from_its_program(self):
        self.assertEqual(pm.terminal_kind({"foreground": {"argv": ["/opt/bin/codex", "-m", "x"]}}), "codex")
        self.assertEqual(pm.terminal_kind({"argv": ["zsh"], "status": {"app": "claude-code"}}), "claude")
        self.assertEqual(pm.terminal_kind({"foreground": {"argv": ["other"]}}), "other")

    def test_turn_hook_notes_pm_turns_only(self):
        (pm.PMS).mkdir(parents=True, exist_ok=True)
        (pm.PMS / "t.json").write_text(json.dumps({"name": "pm-t", "pane": "hc:t9", "project": "t", "repo": "/x"}))
        pane, stdin = pm.PANE, pm.sys.stdin
        before = len(pm.TURN_LOG.read_text().splitlines()) if pm.TURN_LOG.exists() else 0
        try:
            for who, prompt in (("hc:t9", "hello"), ("hc:t9", "[from hc:t3] done"), ("hc:t8", "hello")):
                pm.PANE = who
                pm.sys.stdin = io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}))
                pm.cmd_hook_mirror(None)  # the earlier name still works
        finally:
            pm.PANE, pm.sys.stdin = pane, stdin
            (pm.PMS / "t.json").unlink()
        lines = pm.TURN_LOG.read_text().splitlines()[before:]
        self.assertEqual(len(lines), 1)
        self.assertTrue(pm.TURN_LINE.match(lines[0]))

    def test_worker_defaults_come_from_config_unless_given(self):
        (Path(HOME) / "config.json").write_text(json.dumps({"worker": {"model": "m1", "effort": "high"}}))
        a = pm.worker_defaults(type("A", (), {"kind": None, "model": None, "effort": "low"}))
        self.assertEqual((a.kind, a.model, a.effort), ("codex", "m1", "low"))
        a = pm.worker_defaults(type("A", (), {"kind": "claude", "model": None, "effort": None}))
        self.assertEqual((a.kind, a.model, a.effort), ("claude", "", ""))  # codex's model is not claude's
        (Path(HOME) / "config.json").unlink()
        a = pm.worker_defaults(type("A", (), {"kind": None, "model": None, "effort": None}))
        self.assertEqual(pm.worker_argv(a), ["codex", "-c", "check_for_update_on_startup=false"])


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


class SendBrief(unittest.TestCase):
    """dispatch types the brief only into a worker whose input is ready, answering a trust dialog for its own worktree."""

    def fake_terminal(self, frames):
        """A fake hc: frames are (status, screen), one per look; the last repeats. Returns the keys and sends seen."""
        seen, look = [], [0]
        saved = pm.hc, pm.herdr, pm.time.sleep

        def frame():
            return frames[min(look[0], len(frames) - 1)]

        def fake_hc(*args, **kw):
            if args[0] == "get":
                return {"state": "live", "status": frame()[0]}
            if args[0] == "read":
                return {"text": frame()[1]}
            if args[0] in ("keys", "send"):
                seen.append(list(args[2:]) if args[0] == "keys" else "sent")
                return {"started": True} if args[0] == "send" else {"status": None}
            if args[0] == "run":
                return {"address": "t9"}
            return {}
        pm.hc, pm.herdr = fake_hc, lambda *a, **kw: None
        pm.time.sleep = lambda _: look.__setitem__(0, look[0] + 1)
        self.addCleanup(lambda: setattr(pm, "hc", saved[0]) or setattr(pm, "herdr", saved[1])
                        or setattr(pm.time, "sleep", saved[2]))
        return seen

    tree = str(Path.home() / ".herdr" / "worktrees" / "app" / "dev-x")
    idle = {"app": "claude-code", "state": "idle"}

    def test_trust_keys_follow_the_dialogs_own_options(self):
        self.assertEqual(pm.trust_keys(CLAUDE_TRUST), ["down", "enter"])
        self.assertEqual(pm.trust_keys(CODEX_TRUST), ["enter"])
        self.assertIsNone(pm.trust_keys(OTHER_DIALOG))
        self.assertIsNone(pm.trust_keys("❯ Try \"fix typecheck errors\""))

    def test_nothing_is_sent_while_the_agent_has_no_status(self):
        seen = self.fake_terminal([(None, "")])
        self.assertFalse(pm.send_when_ready("t9", "brief", tries=30, pause=2, strict=True, trust=self.tree))
        self.assertEqual(seen, [])

    def test_a_program_without_status_gets_the_text_once(self):
        seen, saved = [], (pm.hc, pm.time.sleep)
        pm.hc = lambda *args, **kw: (seen.append("sent") or {"started": None, "status": None, "turn": 0}
                                     if args[0] == "send" else {"state": "live"})
        pm.time.sleep = lambda _: None
        try:
            self.assertTrue(pm.send_when_ready("t9", "brief", tries=8))
        finally:
            pm.hc, pm.time.sleep = saved
        self.assertEqual(seen, ["sent"])

    def test_a_trust_dialog_for_its_own_worktree_is_confirmed_then_the_brief_sent(self):
        seen = self.fake_terminal([(None, CLAUDE_TRUST), (None, CLAUDE_TRUST), (None, ""), (self.idle, "❯ ")])
        self.assertTrue(pm.send_when_ready("t9", "brief", tries=30, pause=2, strict=True, trust=self.tree))
        self.assertEqual(seen, [["down", "enter"], "sent"])

    def test_other_dialogs_and_other_folders_are_left_alone(self):
        seen = self.fake_terminal([(None, OTHER_DIALOG)])
        self.assertFalse(pm.send_when_ready("t9", "brief", tries=30, pause=2, strict=True, trust=self.tree))
        seen += self.fake_terminal([(None, CLAUDE_TRUST)])
        self.assertFalse(pm.send_when_ready("t9", "brief", tries=30, pause=2, strict=True, trust=tempfile.mkdtemp()))
        self.assertEqual(seen, [])

    def test_dispatch_that_could_not_send_logs_the_screen_and_prints_the_resend(self):
        repo = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "init"], check=True)
        brief = Path(repo) / "brief.md"
        brief.write_text("Write one line.")
        self.fake_terminal([(None, OTHER_DIALOG)])
        home = pm.worktree_home
        pm.worktree_home = lambda r: Path(tempfile.mkdtemp()) / "app"
        self.addCleanup(setattr, pm, "worktree_home", home)
        a = pm.worker_defaults(argparse.Namespace(repo=repo, brief=str(brief), branch="dev/x", base="main", prep=None,
                                                  name="x", kind="claude", model="", effort="", title="x", label="x"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            pm.dispatch_hc(a, repo, brief.read_text())
        task_id = out.getvalue().split()[0]
        self.assertIn("New MCP server found", str(stop.exception.code))
        self.assertIn(f"hc send t9 \"$(cat {pm.STATE / 'sent' / task_id}.md)\"", str(stop.exception.code))
        self.assertIn("New MCP server found", pm.load(task_id)["log"][-1]["text"])


class Profiles(unittest.TestCase):
    """dispatch --profile: a word for kind, model, effort and advisor; deep asks the user first; reviews by table."""

    def setUp(self):
        self.cfg = Path(HOME) / "config.json"
        self.addCleanup(lambda: self.cfg.unlink(missing_ok=True))
        # The commands here are compared whole; what a worker may read outside its worktree is OutsideReads' test.
        reads = pm.outside_reads
        pm.outside_reads = lambda repo, brief="": []
        self.addCleanup(setattr, pm, "outside_reads", reads)

    def config(self, **values):
        self.cfg.write_text(json.dumps(values))

    def worker(self, **given):
        a = type("A", (), {"kind": None, "model": None, "effort": None, **given})
        return pm.worker_defaults(a)

    def test_without_a_profile_the_command_is_as_before(self):
        a = self.worker()
        self.assertEqual(pm.worker_argv(a), ["codex", "-c", "check_for_update_on_startup=false"])
        self.assertEqual(pm.worker_record(a), {"profile": "", "kind": "codex", "model": "", "effort": "", "advisor": ""})
        self.config(worker={"kind": "claude", "model": "opus"})
        self.assertEqual(pm.worker_argv(self.worker()), ["claude", "--model", "opus"])
        self.assertEqual(pm.dispatch_note(type("A", (), {**vars(self.worker()), "name": "w"})),
                         "dispatched to w (claude opus)")

    def test_a_profile_fills_the_command_and_the_command_line_wins(self):
        self.assertEqual(pm.worker_argv(self.worker(profile="hard")),
                         ["claude", "--model", "opus", "--effort", "xhigh", "--advisor", "fable"])
        self.assertEqual(pm.worker_argv(self.worker(profile="light")), ["claude", "--model", "sonnet", "--effort", "medium"])
        self.assertEqual(pm.worker_argv(self.worker(profile="standard")), ["claude", "--model", "opus"])
        self.assertEqual(pm.worker_argv(self.worker(profile="hard", effort="high", model="sonnet")),
                         ["claude", "--model", "sonnet", "--effort", "high", "--advisor", "fable"])
        self.assertEqual(pm.worker_argv(self.worker(profile="hard", advisor="none")),
                         ["claude", "--model", "opus", "--effort", "xhigh"])
        # The profile's values belong to its program, not to another one named on the command line.
        a = self.worker(profile="hard", kind="codex")
        self.assertEqual(pm.worker_argv(a), ["codex", "-c", "check_for_update_on_startup=false"])
        self.assertEqual(pm.worker_record(a)["profile"], "hard")
        with self.assertRaises(SystemExit):
            self.worker(profile="nope")

    def test_config_profiles_replace_or_add_and_worker_can_name_one(self):
        self.config(profiles={"hard": {"kind": "claude", "model": "opus", "effort": "high"}, "ui": {"model": "sonnet"},
                              "cx": {"kind": "codex", "model": "gpt", "advisor": "fable"}},
                    worker={"profile": "standard", "effort": "high"})
        self.assertEqual(pm.worker_argv(self.worker(profile="hard")), ["claude", "--model", "opus", "--effort", "high"])
        self.assertEqual(pm.worker_argv(self.worker(profile="ui")), ["claude", "--model", "sonnet"])
        self.assertEqual(pm.worker_argv(self.worker(profile="deep")),
                         ["claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus"])
        a = self.worker()  # config's worker names standard and changes its effort
        self.assertEqual((a.profile, pm.worker_argv(a)), ("standard", ["claude", "--model", "opus", "--effort", "high"]))
        # A program without an advisor flag: left out, and the dispatch note says so.
        a = self.worker(profile="cx")
        self.assertEqual((pm.worker_argv(a), a.advisor, a.advisor_dropped), (["codex", "-c", "check_for_update_on_startup=false", "-m", "gpt"], "", "fable"))
        self.assertIn("advisor fable left out", pm.dispatch_note(type("A", (), {**vars(a), "name": "w"})))
        # config's worker names a profile but another program: the profile's Claude values are not given to it.
        self.config(worker={"profile": "hard", "kind": "codex"})
        a = self.worker()
        self.assertEqual((a.profile, pm.worker_argv(a)), ("hard", ["codex", "-c", "check_for_update_on_startup=false"]))
        self.config(worker={"profile": "hard", "kind": "codex", "effort": "high"})
        self.assertEqual(pm.worker_argv(self.worker())[-2:], ["-c", 'model_reasoning_effort="high"'])

    def dispatching(self, screens=None):
        """A git repository, a fake hc and a PM pane; returns (dispatch(**args) -> printed text, calls, terminals).
        terminals[address] is its state ("live" unless set); screens[address] what it shows."""
        repo = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "init"], check=True)
        brief = Path(repo) / "brief.md"
        brief.write_text("Write one line.")
        trees, calls, terminals, screens, labels = Path(tempfile.mkdtemp()), [], {}, screens or {}, {}

        def fake_hc(*args, **kw):
            calls.append(args)
            if args[0] == "run":
                address = f"t{sum(c[0] == 'run' for c in calls)}"
                terminals.setdefault(address, "live")
                return {"address": address}
            if args[0] == "label":  # kept, so `get` shows a terminal's task label as hc does
                labels.setdefault(args[1], {}).update(x.split("=", 1) for x in args[2:])
                return {}
            state = terminals.get(args[1] if len(args) > 1 else "", "live")
            live = state in ("live", "working")  # working: in the middle of a turn, until it is interrupted
            if args[0] == "interrupt" and state == "working":
                terminals[args[1]] = "live"
            if args[0] == "get":  # an exited program reports no status, and takes no text
                return ({"state": "live", "status": {"state": "working" if state == "working" else "idle"}} if live
                        else {"state": state}) | {"labels": labels.get(args[1], {})}
            if args[0] == "read":
                return {"text": screens.get(args[1], "❯ ")}
            return {"started": live} if args[0] == "send" else {}
        saved = pm.hc, pm.herdr, pm.time.sleep, pm.worktree_home, pm.PANE
        pm.hc, pm.herdr, pm.time.sleep = fake_hc, (lambda *a, **kw: None), (lambda _: None)
        pm.worktree_home, pm.PANE = (lambda r: trees / "app"), "hc:t48"
        self.addCleanup(lambda: [setattr(pm, k, v) for k, v in zip(("hc", "herdr", "worktree_home", "PANE"),
                                                                     (saved[0], saved[1], saved[3], saved[4]))]
                        and setattr(pm.time, "sleep", saved[2]))

        def dispatch(**given):
            a = argparse.Namespace(**{"repo": repo, "brief": str(brief), "branch": "dev/p", "base": None, "prep": None,
                                      "name": "w", "title": "做一件事", "label": "p", "kind": None, "model": None,
                                      "effort": None, "profile": None, "advisor": None, "confirmed": False, **given})
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    pm.cmd_dispatch(a)
                except SystemExit as stop:
                    out.write(f"\nexit: {stop.code}")
            return out.getvalue()
        return dispatch, calls, terminals

    def started(self, calls):
        return [c[c.index("--") + 1:] for c in calls if c[0] == "run"]

    def test_deep_registers_a_question_and_starts_a_worker_only_once_confirmed(self):
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(profile="deep").split()[0]
        task = pm.load(task_id)
        self.assertEqual((task["status"], task["held"], task["pane"]), ("blocked", "ask", "hc:t48"))
        self.assertEqual(len(task["options"]), 2)
        self.assertIn("fable", task["log"][-1]["text"])
        self.assertEqual(self.started(calls), [])  # no worker, and no worktree either
        self.assertFalse((pm.worktree_home("") / "dev-p").exists())
        self.assertNotIn("worker", task)
        self.assertIn("still waiting", dispatch(profile="deep"))  # asked again: the same question, no second task
        self.assertEqual(len([t for t in pm.all_tasks() if t.get("branch") == "dev/p" and t["repo"] == task["repo"]]), 1)
        out = dispatch(profile="deep", confirmed=True)
        self.assertEqual(out.split()[0], task_id)  # the held task is taken up
        self.assertEqual(self.started(calls), [("claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus")])
        task = pm.load(task_id)
        self.assertEqual((task["status"], task["pane"], task.get("held"), task.get("options")),
                         ("in_progress", "hc:t1", None, None))
        self.assertEqual(task["worker"], {"profile": "deep", "kind": "claude", "model": "fable", "effort": "high",
                                          "advisor": ""})
        self.assertEqual((task["escalations"], task["rounds"], task["dispatched"]), ([], 0, True))
        self.assertIn("dispatched to w (deep: claude fable high)", task["log"][-1]["text"])

    def test_the_user_can_pick_hard_instead_of_deep(self):
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(profile="deep").split()[0]
        self.assertEqual(dispatch(profile="hard").split()[0], task_id)  # hard asks nobody
        self.assertEqual(self.started(calls), [("claude", "--model", "opus", "--effort", "xhigh", "--advisor", "fable")])
        self.assertEqual(pm.load(task_id)["worker"]["advisor"], "fable")

    def test_a_worker_that_exits_with_its_advisor_is_blocked_not_restarted(self):
        dispatch, calls, terminals = self.dispatching(screens={"t1": "Run /model fable to enable Fable"})
        terminals["t1"] = "finished"
        out = dispatch(profile="hard")
        task_id = out.split()[0]
        task = pm.load(task_id)
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
        task = pm.load(task_id)
        self.assertEqual((task["status"], task["pane"], task["worker"]["advisor"], task.get("held")),
                         ("in_progress", "hc:t2", "", None))

    def test_any_fable_worker_asks_first_but_a_fable_advisor_does_not(self):
        self.config(profiles={"big": {"model": "claude-fable-5-2"}})
        for given in ({"model": "fable"}, {"kind": "claude", "model": "Fable"}, {"profile": "big"},
                      {"profile": "standard", "model": "fable"}):
            dispatch, calls, _ = self.dispatching()
            task = pm.load(dispatch(**given).split()[0])
            self.assertEqual((task["status"], task["held"], self.started(calls)), ("blocked", "ask", []), given)
        dispatch, calls, _ = self.dispatching()
        dispatch(profile="deep", model="opus")  # deep's name alone still asks
        self.assertEqual(self.started(calls), [])
        dispatch, calls, _ = self.dispatching()
        dispatch(profile="hard")  # hard's Fable advisor is the PM's to pick
        self.assertEqual(len(self.started(calls)), 1)
        dispatch, calls, _ = self.dispatching()
        dispatch(model="fable", confirmed=True)
        self.assertEqual(self.started(calls), [("codex", "-c", "check_for_update_on_startup=false", "-m", "fable")])

    def test_in_the_terminal_ui_a_worker_gone_with_its_advisor_is_blocked_too(self):
        repo = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "init"], check=True)
        brief, tree = Path(repo) / "brief.md", tempfile.mkdtemp()
        brief.write_text("Write one line.")
        calls, running = [], {"w1:p0"}  # panes with an agent in them; the PM's own is w1:p0

        def fake_herdr(*args):
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
        saved = pm.herdr, pm.PANE
        pm.herdr, pm.PANE = fake_herdr, "w1:p0"
        self.addCleanup(lambda: setattr(pm, "herdr", saved[0]) or setattr(pm, "PANE", saved[1]))

        def dispatch(**given):
            a = argparse.Namespace(**{"repo": repo, "brief": str(brief), "branch": "dev/t", "base": None, "prep": None,
                                      "name": "w", "title": "做一件事", "label": "t", "kind": None, "model": None,
                                      "effort": None, "profile": "hard", "advisor": None, "confirmed": False, **given})
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    pm.cmd_dispatch(a)
                except SystemExit as stop:
                    out.write(f"\nexit: {stop.code}")
            return out.getvalue()
        out = dispatch()  # claude exits at once: no agent in w2:p1
        task = pm.load(out.split()[0])
        self.assertIn("/model fable", out)
        self.assertEqual((task["status"], task["held"], task["pane"], task["held_in"]),
                         ("blocked", "advisor", "w1:p0", {"workspace": "w2", "pane": "w2:p1"}))
        start = [c for c in calls if c[:2] == ("agent", "start")]
        self.assertEqual(start[-1][start[-1].index("--") + 1:], ("--model", "opus", "--effort", "xhigh", "--advisor", "fable"))
        running.add("w2:p1")
        out = dispatch(advisor="none")  # again, without the advisor: the same task, worktree and pane
        self.assertEqual(out.split()[0], task["id"])
        self.assertEqual(sum(c[:2] == ("worktree", "create") for c in calls), 1)
        start = [c for c in calls if c[:2] == ("agent", "start")]
        self.assertEqual((len(start), start[-1][start[-1].index("--pane") + 1]), (2, "w2:p1"))
        task = pm.load(task["id"])
        self.assertEqual((task["status"], task["pane"], task.get("held_in"), task["worktree"], task["worker_pane"]),
                         ("in_progress", "w2:p1", None, tree, "w2:p1"))

    def test_reattach_uses_the_worker_record(self):
        task = {"worker": {"profile": "hard", "kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"},
                "log": [{"text": "dispatched to w (hard: claude opus xhigh, advisor fable)"}]}
        self.assertEqual(pm.dispatched_with(task), ("claude", "opus", "xhigh"))
        self.assertEqual(pm.dispatched_with({"log": [{"text": "dispatched to w (codex gpt-5 high)"}]}),
                         ("codex", "gpt-5", "high"))  # a task from before the record
        self.assertEqual(pm.resume_argv("claude", "s1", "opus", "xhigh", "fable"),
                         ["claude", "--model", "opus", "--effort", "xhigh", "--advisor", "fable", "--resume", "s1"])

    def test_a_worker_without_an_advisor_is_waited_for_as_before(self):
        dispatch, calls, terminals = self.dispatching()
        terminals["t1"] = "finished"
        out = dispatch()
        self.assertIn("the brief was not sent", out)
        self.assertEqual(sum(c[0] == "get" and c[1] == "t1" for c in calls), 30)  # every try, as before
        self.assertEqual(pm.load(out.split()[0])["status"], "in_progress")

    def test_review_model_comes_from_the_table_by_the_workers_profile(self):
        review = lambda task, **given: pm.reviewer_defaults(
            argparse.Namespace(**{"kind": None, "model": None, "effort": None, **given}), task)
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
        review = lambda profile: pm.reviewer_defaults(
            argparse.Namespace(kind=None, model=None, effort=None), {"worker": {"profile": profile}})
        pick = lambda a: (a.model, a.fallback)
        # Not set, or true: as before.
        for values in ({}, {"fable": True}):
            self.config(**values)
            self.assertEqual(pm.ladder(), ("light", "standard", "hard", "deep"))
            self.assertEqual(pm.worker_argv(self.worker(profile="hard"))[-2:], ["--advisor", "fable"])
            self.assertEqual([pick(review(p)) for p in pm.LADDER],
                             [("opus", ""), ("fable", "sonnet"), ("fable", "sonnet"), ("opus", "")])
        self.config(fable=False)
        self.assertEqual(pm.ladder(), ("light", "standard", "hard"))
        a = self.worker(profile="hard")
        self.assertEqual((pm.worker_argv(a), a.advisor), (["claude", "--model", "opus", "--effort", "xhigh"], ""))
        self.assertEqual(pm.worker_argv(self.worker(profile="light")), ["claude", "--model", "sonnet", "--effort", "medium"])
        with self.assertRaises(SystemExit) as stop:
            self.worker(profile="deep")
        self.assertIn('"fable": false', str(stop.exception.code))
        # A review the table gave to Fable goes to Sonnet, never to Opus, which wrote the code.
        self.assertEqual([pick(review(p)) for p in pm.LADDER],
                         [("opus", ""), ("sonnet", ""), ("sonnet", ""), ("opus", "")])
        # What the user wrote still wins: their deep is back on the ladder, their Fable reviewer falls back to Sonnet.
        self.config(fable=False, profiles={"deep": {"model": "fable", "effort": "high"},
                                           "hard": {"model": "opus", "advisor": "fable"}}, review={"hard": "fable"})
        self.assertEqual(pm.ladder(), pm.LADDER)
        self.assertEqual(pm.worker_argv(self.worker(profile="hard")), ["claude", "--model", "opus", "--advisor", "fable"])
        self.assertEqual(pick(review("hard")), ("fable", "sonnet"))
        self.assertEqual(pick(review("standard")), ("sonnet", ""))

    def test_a_fable_worker_or_reviewer_falls_back_and_its_note_says_so(self):
        self.config(lang="zh")
        a = self.worker(profile="deep")
        self.assertEqual(a.fallback, "opus")
        self.assertEqual(pm.dispatch_note(type("A", (), {**vars(a), "name": "w"})),
                         "dispatched to w (deep: claude fable high)；Fable 不可用时会退到 opus")
        # The advisor is not covered: an advisor that cannot be used makes Claude exit whatever the fallback.
        for profile in ("light", "standard", "hard"):
            self.assertNotIn("--fallback-model", pm.worker_argv(self.worker(profile=profile)))
        self.assertNotIn("不可用", pm.dispatch_note(type("A", (), {**vars(self.worker(profile="hard")), "name": "w"})))
        r = pm.reviewer_defaults(argparse.Namespace(kind=None, model=None, effort=None), {"worker": {"profile": "standard"}})
        self.assertEqual(pm.worker_argv(r), ["claude", "--model", "fable", "--fallback-model", "sonnet"])
        r = pm.reviewer_defaults(argparse.Namespace(kind=None, model="claude-fable-5-2", effort=None), {})
        self.assertEqual(pm.worker_argv(r)[-2:], ["-m", "claude-fable-5-2"])  # codex, the configured default: none
        # Another program is not given Claude's flag.
        self.assertEqual(pm.agent_argv("codex", "fable", fallback="opus"),
                         ["codex", "-c", "check_for_update_on_startup=false", "-m", "fable"])
        self.assertEqual(pm.resume_argv("claude", "s1", "fable", "high", "", "opus"),
                         ["claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus", "--resume", "s1"])

    def test_without_fable_escalating_from_hard_stops_at_the_top(self):
        self.config(fable=False, lang="zh")
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(profile="hard").split()[0]
        self.assertEqual(self.started(calls), [("claude", "--model", "opus", "--effort", "xhigh")])
        before = pm.load(task_id)
        out = self.escalate(task_id, why="hard 也没做成")
        self.assertIn("没有 Fable", out)
        self.assertIn("最高一档", out)
        self.assertEqual(len(self.started(calls)), 1)  # no worker started
        self.assertNotIn(("kill", "t1"), calls)
        task = pm.load(task_id)
        self.assertEqual((task["status"], task["pane"], task["escalations"], task.get("escalating")),
                         ("in_progress", "hc:t1", [], None))
        self.assertEqual(len(task["log"]), len(before["log"]))
        self.assertIn("没有档位 deep", self.escalate(task_id, profile="deep"))
        self.assertEqual(len(self.started(calls)), 1)
        # One step below the top still goes up.
        self.config(fable=False)
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(branch="dev/s", label="s", profile="standard").split()[0]
        self.assertNotIn("exit:", self.escalate(task_id))
        self.assertEqual(pm.load(task_id)["worker"]["profile"], "hard")

    def test_dispatch_parent_names_the_task_it_was_split_from(self):
        dispatch, calls, _ = self.dispatching()
        repo = pm.project_root(tempfile.mkdtemp())
        name = Path(repo).name
        pm.save({"id": f"{name}-whole", "title": "总任务", "project": name, "repo": repo, "status": "in_progress",
                 "owner": "pm", "base": "main", "created": pm.now()})
        out = dispatch(parent="nope")  # no such task: nothing is made
        self.assertIn("no task nope", out)
        self.assertEqual(self.started(calls), [])
        task = pm.load(dispatch(parent=f"{name}-whole").split()[0])
        self.assertEqual((task["parent"], task["status"]), (f"{name}-whole", "in_progress"))
        # One that asks the user first keeps its parent too, through to the dispatch the user agreed to.
        asked = pm.load(dispatch(branch="dev/q", label="q", profile="deep", parent=f"{name}-whole").split()[0])
        self.assertEqual((asked["status"], asked["parent"]), ("blocked", f"{name}-whole"))
        dispatch(branch="dev/q", label="q", profile="deep", confirmed=True, parent=f"{name}-whole")
        self.assertEqual(pm.load(asked["id"])["parent"], f"{name}-whole")

    def test_state_is_json_with_old_and_new_tasks(self):
        repo = pm.project_root(tempfile.mkdtemp())
        name = Path(repo).name
        pm.save({"id": f"{name}-old", "title": "old", "project": name, "repo": repo, "status": "in_progress",
                 "owner": "pm", "base": "main", "created": pm.now()})
        pm.save({"id": f"{name}-new", "title": "new", "project": name, "repo": repo, "status": "in_progress",
                 "owner": "pm", "base": "main", "created": pm.now(), "escalations": [], "rounds": 0,
                 "worker": {"profile": "hard", "kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pm.cmd_state(None)
        tasks = {t["id"]: t for t in json.loads(out.getvalue())["tasks"]}
        # In the state, `worker` stays the live agent's status (pm-dash counts on it); `engine` is the task's record.
        self.assertEqual((tasks[f"{name}-old"]["worker"], tasks[f"{name}-new"]["worker"]), ("", ""))
        self.assertEqual(tasks[f"{name}-old"]["engine"], {})
        self.assertEqual(tasks[f"{name}-new"]["engine"]["effort"], "xhigh")

    def escalate(self, task_id, **given):
        a = argparse.Namespace(**{"id": task_id, "profile": None, "why": None, "advisor": None, "name": None,
                                  "confirmed": False, **given})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                pm.cmd_escalate(a)
            except SystemExit as stop:
                out.write(f"\nexit: {stop.code}")
        return out.getvalue()

    def run_of(self, calls, address):
        """The `hc run` call that made terminal t<n>."""
        return [c for c in calls if c[0] == "run"][int(address[1:]) - 1]

    def test_escalate_goes_one_step_up_in_the_same_worktree_and_ends_the_old_worker(self):
        self.config(lang="zh")
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(profile="standard").split()[0]
        task = pm.load(task_id)
        first = (pm.STATE / "sent" / f"{task_id}.md").read_text()
        pm.save({"id": f"{task_id}-review", "title": "审查：做一件事", "project": task["project"], "repo": task["repo"],
                 "status": "done", "owner": "pm", "base": "main", "review_of": task_id, "created": pm.now(),
                 "log": [{"at": "2026-11-15 10:00", "by": "hc:t9", "text": "开始审查（claude fable）"},
                         {"at": "2026-11-15 10:20", "by": "hc:t9", "text": "status=done; 1. 缺一个测试\n2. 名字拼错"}]})
        pm.note(task, "第二轮评审：测试还是没补")
        task["session"] = {"kind": "claude", "id": "s-old"}  # the old worker's: reattach must not resume it now
        task["rounds"] = 1
        pm.save(task)
        out = self.escalate(task_id, why="两轮评审未过")
        self.assertNotIn("exit:", out)
        run = self.run_of(calls, "t2")
        self.assertEqual(run[run.index("--") + 1:], ("claude", "--model", "opus", "--effort", "xhigh", "--advisor", "fable"))
        self.assertEqual((run[run.index("--cwd") + 1], run[run.index("--name") + 1]), (task["worktree"], "w-hard"))
        self.assertEqual([p.name for p in pm.worktree_home("").iterdir()], ["dev-p"])  # no second worktree
        self.assertIn(("kill", "t1"), calls)
        self.assertIn(("rm", "t1"), calls)
        task = pm.load(task_id)
        self.assertEqual((task["id"], task["branch"], task["worktree"], task["status"], task["pane"], task["agent"]),
                         (task_id, "dev/p", run[run.index("--cwd") + 1], "in_progress", "hc:t2", "w-hard"))
        self.assertEqual(task["worker"], {"profile": "hard", "kind": "claude", "model": "opus", "effort": "xhigh",
                                          "advisor": "fable"})
        self.assertNotIn("session", task)
        # The new worker's rounds start from nothing, and the review thread is closed: its next review is no rework.
        self.assertEqual((task["rounds"], task["worker_pane"]), (0, "hc:t2"))
        self.assertTrue(pm.load(f"{task_id}-review").get("retired"))
        self.assertEqual([(e["from"], e["to"], e["why"]) for e in task["escalations"]], [("standard", "hard", "两轮评审未过")])
        self.assertTrue(task["escalations"][0]["at"])
        self.assertEqual(task["log"][-1]["text"], "升级到 hard（Opus·xhigh）：两轮评审未过")
        sent = next(c[2] for c in calls if c[:2] == ("send", "t2"))
        for part in ("1. 缺一个测试\n  2. 名字拼错", "第二轮评审：测试还是没补", "Write one line.", "dev/p", "git log main..HEAD",
                     "两轮评审未过", "前一个 worker 的提交已经在分支"):
            self.assertIn(part, sent)
        self.assertEqual(sent.count(f"update {task_id} --status review"), 1)  # the report section, once
        self.assertEqual((pm.STATE / "sent" / f"{task_id}.escalated.md").read_text(), sent)
        self.assertEqual((pm.STATE / "sent" / f"{task_id}.md").read_text(), first)  # what reattach sends: the first

    def test_escalate_to_deep_only_asks_until_confirmed(self):
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(profile="hard").split()[0]
        out = self.escalate(task_id, why="hard 也没做成")
        task = pm.load(task_id)
        self.assertIn("--confirmed", out)
        self.assertEqual(len(self.started(calls)), 1)  # no worker started
        self.assertNotIn(("kill", "t1"), calls)
        self.assertEqual((task["status"], len(task["options"]), task["pane"], task["worker"]["profile"],
                          task["escalations"]), ("blocked", 2, "hc:t1", "hard", []))
        self.assertIn("fable", task["log"][-1]["text"])
        self.assertIn("still waiting", self.escalate(task_id))  # asked again: no second card
        self.assertEqual(len(pm.load(task_id)["log"]), len(task["log"]))
        self.escalate(task_id, confirmed=True)
        self.assertEqual(self.started(calls)[-1], ("claude", "--model", "fable", "--effort", "high", "--fallback-model", "opus"))
        task = pm.load(task_id)
        self.assertEqual((task["status"], task["pane"], task.get("options"), task.get("escalating")),
                         ("in_progress", "hc:t2", None, None))
        self.assertEqual([(e["from"], e["to"], e["why"]) for e in task["escalations"]], [("hard", "deep", "hard 也没做成")])
        self.assertIn(("rm", "t1"), calls)
        # Deep is the top: without --profile there is nothing to go to, and nothing starts.
        self.assertIn("--profile", self.escalate(task_id))
        self.assertEqual(len(self.started(calls)), 2)
        # Any Fable worker asks, whatever the profile is called; hard (a Fable advisor) does not.
        self.config(profiles={"big": {"model": "claude-fable-5-2"}})
        self.assertEqual((self.escalate(task_id, profile="big").count("--confirmed"), len(self.started(calls))), (1, 2))

    def test_an_escalation_question_on_an_answered_task_is_a_new_one(self):
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(profile="hard").split()[0]
        task = pm.load(task_id)
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_update(argparse.Namespace(id=task_id, status="blocked", note="先问个事", option=["好"], keep=False,
                                             **{f: None for f in pm.FIELDS if f != "status"}))
        pm.record(task["repo"], "user", text=f"【{task['title']}】好")
        self.assertIn(task_id, pm.answered_tasks(pm.conversation(task["repo"])))
        self.escalate(task_id, why="hard 也没做成")  # to deep: the user is asked anew
        self.assertNotIn(task_id, pm.answered_tasks(pm.conversation(task["repo"])))

    def test_a_declined_escalation_leaves_no_reason_behind(self):
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(profile="hard").split()[0]
        self.escalate(task_id, why="旧理由")
        with contextlib.redirect_stdout(io.StringIO()):  # the user said no: the PM moves the task on
            pm.cmd_update(argparse.Namespace(id=task_id, status="in_progress", note="先不升级", keep=False,
                                             **{f: None for f in pm.FIELDS if f != "status"}))
        self.assertNotIn("escalating", pm.load(task_id))
        self.escalate(task_id, profile="deep", confirmed=True)
        self.assertEqual(pm.load(task_id)["escalations"][-1]["why"], "")

    def test_a_named_profile_and_terminals_that_are_not_the_tasks_worker(self):
        dispatch, calls, _ = self.dispatching()
        task_id = dispatch(profile="light").split()[0]
        task = pm.load(task_id)
        task["pane"] = "hc:t77"  # an adopted session: no task label, so it may be the user's own
        pm.save(task)
        out = self.escalate(task_id, profile="hard")
        self.assertIn("hc:t77", out)
        self.assertFalse(any(c[0] in ("kill", "rm") and c[1] == "t77" for c in calls))
        task = pm.load(task_id)
        self.assertEqual(([(e["from"], e["to"]) for e in task["escalations"]], task["pane"]), ([("light", "hard")], "hc:t2"))
        task["pane"] = "hc:t48"  # parked on the PM's own pane
        pm.save(task)
        self.escalate(task_id, profile="standard")
        self.assertFalse(any(c[0] in ("kill", "rm") and c[1] == "t48" for c in calls))
        self.assertEqual(len(pm.load(task_id)["escalations"]), 2)
        # A task without a profile names one; a review thread and closed work are not escalated.
        task = pm.load(task_id)
        task["worker"] = {}
        pm.save(task)
        self.assertIn("--profile", self.escalate(task_id))
        task.update(status="merged")
        pm.save(task)
        self.assertIn("exit:", self.escalate(task_id, profile="hard"))
        self.assertEqual(len(self.started(calls)), 3)

    def test_an_escalated_worker_that_exits_with_its_advisor_keeps_the_old_one(self):
        dispatch, calls, terminals = self.dispatching(screens={"t2": "Run /model fable to enable Fable"})
        terminals["t2"] = "finished"
        task_id = dispatch(profile="standard").split()[0]
        out = self.escalate(task_id)
        self.assertIn("/model fable", out)
        self.assertIn("escalate", out.split("exit:")[1])
        task = pm.load(task_id)
        self.assertEqual((task["status"], task["pane"], task["worker"]["profile"], task["escalations"], len(task["options"])),
                         ("blocked", "hc:t1", "standard", [], 2))
        self.assertIn(("rm", "t2"), calls)
        self.assertNotIn(("kill", "t1"), calls)
        self.escalate(task_id, advisor="none")  # the question's other answer
        self.assertEqual(self.started(calls)[-1], ("claude", "--model", "opus", "--effort", "xhigh"))
        task = pm.load(task_id)
        self.assertEqual((task["status"], task["pane"], task["worker"]["advisor"]), ("in_progress", "hc:t3", ""))
        self.assertIn(("rm", "t1"), calls)

    def test_an_escalated_worker_that_exits_without_an_advisor_changes_nothing(self):
        dispatch, calls, terminals = self.dispatching(screens={"t2": "fable is not available"})
        terminals["t2"] = "finished"
        task_id = dispatch(profile="hard").split()[0]
        before = pm.load(task_id)
        terminals["t1"] = "working"  # stopped for the new one, which then exits: the PM is told the old one waits
        out = self.escalate(task_id, profile="deep", confirmed=True)
        self.assertIn("exit:", out)
        self.assertIn("hc:t1 was interrupted", out)
        task = pm.load(task_id)
        self.assertEqual((task["status"], task["pane"], task["worker"], task["escalations"]),
                         (before["status"], "hc:t1", before["worker"], []))
        self.assertIn("fable is not available", task["log"][-2]["text"])
        self.assertIn("interrupted", task["log"][-1]["text"])
        self.assertIn(("rm", "t2"), calls)
        self.assertNotIn(("kill", "t1"), calls)
        self.assertLess(sum(c[:2] == ("get", "t2") for c in calls), 10)  # not waited out: it stops once it exits
        # Again on the profile it runs on: a name the old, live terminal does not hold.
        terminals["t3"] = "live"
        self.escalate(task_id, profile="hard")
        run = self.run_of(calls, "t3")
        self.assertEqual(run[run.index("--name") + 1], "w-hard")
        self.escalate(task_id, profile="hard")
        run = self.run_of(calls, "t4")
        self.assertEqual(run[run.index("--name") + 1], "w-hard-2")

    def test_the_old_worker_stops_before_the_new_one_starts(self):
        dispatch, calls, terminals = self.dispatching()
        task_id = dispatch(profile="standard").split()[0]
        terminals["t1"] = "working"
        out = self.escalate(task_id)
        self.assertIn("interrupted", out)
        order = [c[:2] for c in calls if c[0] in ("interrupt", "run", "kill")]
        self.assertEqual(order[-3:], [("interrupt", "t1"), ("run", "--bg"), ("kill", "t1")])
        # Not this task's worker, and working: never interrupted, and nothing starts.
        task = pm.load(task_id)
        task["pane"] = "hc:t77"
        pm.save(task)
        terminals["t77"] = "working"
        runs = len(self.started(calls))
        out = self.escalate(task_id, profile="hard")
        self.assertIn("exit:", out)
        self.assertNotIn(("interrupt", "t77"), [c[:2] for c in calls])
        self.assertEqual((len(self.started(calls)), pm.load(task_id)["pane"]), (runs, "hc:t77"))
        # git busy in the worktree (index.lock): nothing starts either.
        terminals["t77"] = "live"
        lock = Path(subprocess.run(["git", "-C", task["worktree"], "rev-parse", "--absolute-git-dir"], check=True,
                                   capture_output=True, text=True).stdout.strip()) / "index.lock"
        lock.write_text("")
        self.addCleanup(lock.unlink, missing_ok=True)
        out = self.escalate(task_id, profile="hard")
        self.assertIn("index.lock", out)
        self.assertEqual(len(self.started(calls)), runs)
        lock.unlink()
        self.assertNotIn("exit:", self.escalate(task_id, profile="hard"))
        self.assertEqual(len(self.started(calls)), runs + 1)

    def test_escalate_in_the_terminal_ui_opens_a_tab_in_the_tasks_workspace(self):
        tree, calls = tempfile.mkdtemp(), []
        running = {"w2:p1": "w", "w2:p5": "u"}

        def fake_herdr(*args):
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
        saved = pm.herdr, pm.PANE
        pm.herdr, pm.PANE = fake_herdr, "w1:p0"
        self.addCleanup(lambda: setattr(pm, "herdr", saved[0]) or setattr(pm, "PANE", saved[1]))
        repo = pm.project_root(tempfile.mkdtemp())
        pm.save({"id": "tui-e", "title": "t", "project": Path(repo).name, "repo": repo, "status": "review", "owner": "pm",
                 "base": "main", "branch": "dev/t", "worktree": tree, "workspace": "w2", "pane": "w2:p1", "agent": "w",
                 "worker_pane": "w2:p1", "created": pm.now(),
                 "worker": {"profile": "standard", "kind": "claude", "model": "opus"}})
        out = self.escalate("tui-e", why="卡在能力上")
        self.assertNotIn("exit:", out)
        tab = next(c for c in calls if c[:2] == ("tab", "create"))
        self.assertEqual((tab[tab.index("--workspace") + 1], tab[tab.index("--cwd") + 1]), ("w2", tree))
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        self.assertEqual(start[2:start.index("--", 3)], ("w-hard", "--kind", "claude", "--pane", "w2:p3"))
        self.assertEqual(start[start.index("--", 3) + 1:], ("--model", "opus", "--effort", "xhigh", "--advisor", "fable"))
        self.assertTrue(any(c[:3] == ("agent", "prompt", "w-hard") for c in calls))
        self.assertIn(("pane", "close", "w2:p1"), calls)
        task = pm.load("tui-e")
        self.assertEqual((task["pane"], task["workspace"], task["status"], task["escalations"][0]["to"]),
                         ("w2:p3", "w2", "in_progress", "hard"))
        # A session taken over with `pm.py new --pane --agent` (no worker_pane): never closed, even by its name.
        with contextlib.redirect_stdout(io.StringIO()):
            adopted = pm.cmd_new(argparse.Namespace(repo=repo, title="u", status="in_progress", owner="pm", base="main",
                                                    workspace="w2", pane="w2:p5", agent="u", branch="dev/u",
                                                    worktree=tree, brief=None, slug="tui-u", note=None))
        task = pm.load(adopted)
        task["worker"] = {"profile": "light", "kind": "claude", "model": "sonnet"}
        pm.save(task)
        out = self.escalate(adopted)
        self.assertNotIn("exit:", out)
        self.assertIn("w2:p5", out)
        self.assertNotIn(("pane", "close", "w2:p5"), calls)
        self.assertEqual(pm.load(adopted)["escalations"][0]["to"], "standard")


class SubThreads(unittest.TestCase):
    """A task split into others: each part names it as `parent`, set by new, dispatch or update."""

    def run_pm(self, *argv):
        out, saved = io.StringIO(), sys.argv
        sys.argv = ["pm.py", *argv]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    pm.main()
                except SystemExit as stop:
                    out.write(f"\nexit: {stop.code}")
        finally:
            sys.argv = saved
        return out.getvalue()

    def test_new_and_update_set_the_parent_and_state_shows_it(self):
        repo = pm.project_root(tempfile.mkdtemp())
        whole = self.run_pm("new", "派发时选模型", "--repo", repo, "--pane", "", "--workspace", "").split()[0]
        part = self.run_pm("new", "档位标签", "--repo", repo, "--parent", whole).split()[0]
        old = self.run_pm("new", "老线程", "--repo", repo).split()[0]
        self.assertEqual(pm.load(part)["parent"], whole)
        self.assertNotIn("parent", pm.load(old))  # none given: no field, as in an older ledger
        self.assertIn("no task nope", self.run_pm("new", "x", "--repo", repo, "--parent", "nope"))
        # An existing task gets its parent afterwards; the log says so.
        self.assertIn(f"{old}: in_progress", self.run_pm("update", old, "--parent", whole))
        task = pm.load(old)
        self.assertEqual((task["parent"], task["log"][-1]["text"]), (whole, f"parent={whole}"))
        self.assertIn("loop", self.run_pm("update", old, "--parent", old))       # not its own parent
        self.assertIn("no task", self.run_pm("update", old, "--parent", "nope"))
        self.assertEqual(pm.load(old)["parent"], whole)
        n = len(pm.load(old)["log"])
        self.run_pm("update", old, "--parent", "")  # an empty value takes it away; on a task without one: nothing
        self.assertNotIn("parent", pm.load(old))
        self.run_pm("update", old, "--parent", "")
        self.assertEqual(len(pm.load(old)["log"]), n + 1)
        tasks = {t["id"]: t for t in json.loads(self.run_pm("state"))["tasks"]}
        self.assertEqual((tasks[part]["parent"], tasks[old]["parent"], tasks[whole]["parent"]), (whole, "", ""))
        self.assertEqual(tasks[whole]["pane"], "")

    def test_parent_refuses_a_loop_and_anything_but_a_task_id(self):
        repo = pm.project_root(tempfile.mkdtemp())
        a = self.run_pm("new", "A", "--repo", repo, "--slug", "loop-a").split()[0]
        b = self.run_pm("new", "B", "--repo", repo, "--slug", "loop-b", "--parent", a).split()[0]
        c = self.run_pm("new", "C", "--repo", repo, "--slug", "loop-c", "--parent", b).split()[0]
        self.assertIn("loop", self.run_pm("update", a, "--parent", b))   # A→B→A
        self.assertIn("loop", self.run_pm("update", a, "--parent", c))   # A→C→B→A
        self.assertNotIn("parent", pm.load(a))
        for bad in ("../x", "a/b", ".hidden", "x..y", "a b"):
            self.assertIn("not a task id", self.run_pm("update", c, "--parent", bad), bad)
            self.assertIn("not a task id", self.run_pm("new", "D", "--repo", repo, "--parent", bad), bad)
        self.assertEqual(pm.load(c)["parent"], b)
        self.assertIn(f"{c}: in_progress", self.run_pm("update", c, "--parent", a))  # no loop: fine

    def test_state_keeps_the_retired_parts_of_a_task_on_the_board_apart(self):
        repo = pm.project_root(tempfile.mkdtemp())
        name = Path(repo).name
        base = {"project": name, "repo": repo, "owner": "pm", "base": "main", "created": pm.now()}
        pm.save({**base, "id": f"{name}-whole", "title": "总任务", "status": "in_progress"})
        pm.save({**base, "id": f"{name}-done", "title": "合并了", "status": "merged", "parent": f"{name}-whole",
                 "retired": "2026-11-15 01:00"})
        pm.save({**base, "id": f"{name}-live", "title": "进行中", "status": "in_progress", "parent": f"{name}-whole"})
        pm.save({**base, "id": f"{name}-gone", "title": "父任务已结束", "status": "merged", "retired": "x"})
        pm.save({**base, "id": f"{name}-orphan", "title": "孤儿", "status": "merged", "retired": "x",
                 "parent": f"{name}-gone"})  # its parent is off the board: not kept
        state = json.loads(self.run_pm("state"))
        ids = {t["id"] for t in state["tasks"]}
        self.assertNotIn(f"{name}-done", ids)  # the board and its counts see what they saw before
        parts = {t["id"]: t for t in state["retired_parts"]}
        self.assertNotIn(f"{name}-orphan", parts)
        self.assertNotIn(f"{name}-live", parts)  # on the board already
        self.assertEqual({k: parts[f"{name}-done"][k] for k in ("title", "status", "parent", "retired")},
                         {"title": "合并了", "status": "merged", "parent": f"{name}-whole", "retired": True})


class ReportAndWait(unittest.TestCase):
    """The worker reports in the ledger; the PM waits for that report instead of reading the screen."""

    def test_the_report_section_names_the_task_and_both_commands(self):
        for lang, word in (("en", "Reporting"), ("zh", "汇报")):
            (Path(HOME) / "config.json").write_text(json.dumps({"lang": lang}))
            try:
                text = pm.report_section("p-x")
            finally:
                (Path(HOME) / "config.json").unlink()
            self.assertIn(word, text)
            self.assertIn("update p-x --status review --commit <sha> --note", text)
            self.assertIn("update p-x --status blocked --note", text)
            self.assertIn("600", text)
        # What was sent is kept, report section included, for a resend by hand.
        sent = pm.keep_sent("p-x", "Do the thing.")
        self.assertTrue(sent.read_text().startswith("Do the thing.\n\nReporting (task p-x)"))

    def run_wait(self, task_id, terminal_states, update_after=None, timeout=60):
        """Run `wait` against a fake hc whose terminal reports the given states in turn."""
        states = iter(terminal_states)
        hc, sleep = pm.hc, pm.time.sleep
        looks = []

        def fake_sleep(_):
            looks.append(1)
            if update_after is not None and len(looks) == update_after:
                with contextlib.redirect_stdout(io.StringIO()):
                    pm.cmd_update(type("A", (), {"id": task_id, "status": "review", "commit": "abc123", "keep": False,
                                                 "note": "wrote one line; tests pass; UI not checked"}))
        pm.hc = lambda *args, **kw: next(states, None) if args[0] == "get" else None
        pm.time.sleep = fake_sleep
        out, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(out):
                pm.cmd_wait(type("A", (), {"id": task_id, "timeout": timeout}))
        except SystemExit as stop:
            code = stop.code
        finally:
            pm.hc, pm.time.sleep = hc, sleep
        return code, out.getvalue()

    def make_task(self, task_id):
        pm.save({"id": task_id, "title": "t", "project": "p", "repo": tempfile.mkdtemp(), "status": "in_progress",
                 "owner": "pm", "base": "main", "pane": "hc:t5", "created": pm.now()})

    def test_wait_returns_the_report_once_the_status_leaves_in_progress(self):
        self.make_task("p-done")
        working = {"state": "live", "status": {"state": "working"}}
        code, out = self.run_wait("p-done", [working] * 5, update_after=2)
        self.assertEqual(code, 0)
        self.assertIn("p-done: review (commit abc123)", out)
        self.assertIn("wrote one line; tests pass; UI not checked", out)
        self.assertIn("ahead=", out)

    def test_wait_times_out_with_exit_2(self):
        self.make_task("p-slow")
        code, out = self.run_wait("p-slow", [{"state": "live", "status": {"state": "working"}}] * 3, timeout=0)
        self.assertEqual(code, 2)
        self.assertIn("no new report", out)

    def test_a_worker_idle_without_a_report_exits_3_with_a_reminder(self):
        self.make_task("p-quiet")
        idle = {"state": "live", "status": {"state": "idle"}}
        code, out = self.run_wait("p-quiet", [idle, idle, idle])
        self.assertEqual(code, 3)
        self.assertIn("stopped (idle) without reporting", out)
        self.assertIn("hc send t5 ", out)
        self.assertIn("update p-quiet --status review|blocked", out)
        # An exited terminal counts too; a single idle look between turns does not.
        self.make_task("p-gone")
        code, _ = self.run_wait("p-gone", [idle, {"state": "live", "status": {"state": "working"}},
                                           {"state": "exited"}, {"state": "exited"}])
        self.assertEqual(code, 3)

    def test_blocked_errored_or_removed_workers_end_the_wait(self):
        self.make_task("p-ask")
        blocked = {"state": "live", "status": {"state": "blocked"}}
        code, out = self.run_wait("p-ask", [blocked, blocked])
        self.assertEqual((code, "blocked" in out, "hc read t5" in out), (3, True, True))
        self.make_task("p-err")
        code, out = self.run_wait("p-err", [{"state": "live", "status": {"state": "error"}}] * 2)
        self.assertEqual((code, "error" in out), (3, True))
        self.make_task("p-rm")
        gone = {"error": {"kind": "not_found", "message": "no terminal"}}
        code, out = self.run_wait("p-rm", [gone, gone])
        self.assertEqual((code, "removed" in out, "hc send" in out), (3, True, False))  # nobody left to remind
        self.make_task("p-nohc")  # hc unavailable: nothing is known, so wait runs to its timeout
        code, _ = self.run_wait("p-nohc", [None, None, None], timeout=0)
        self.assertEqual(code, 2)

    def test_an_old_report_is_not_returned_again(self):
        self.make_task("p-again")
        with contextlib.redirect_stdout(io.StringIO()):  # first report; the PM then sends review findings
            pm.cmd_update(type("A", (), {"id": "p-again", "status": "review", "commit": "c1", "keep": False,
                                         "note": "first report"}))
        working = {"state": "live", "status": {"state": "working"}}
        code, out = self.run_wait("p-again", [working] * 3, timeout=0)
        self.assertEqual(code, 2)                       # the old report does not end the wait
        code, out = self.run_wait("p-again", [working] * 5, update_after=2)
        self.assertEqual(code, 0)
        self.assertIn("wrote one line", out)            # the new one does
        self.assertNotIn("first report", out)


class LightOutput(unittest.TestCase):
    """What the PM reads stays short: wait prints the whole report, show and status a summary, diff only numbers."""

    def run_pm(self, *argv):
        return SubThreads.run_pm(self, *argv)

    def test_wait_prints_a_long_report_whole(self):
        ReportAndWait.make_task(self, "p-long")
        long = "改动说明。" * 300  # 1500 characters, more than the old 600 cut
        working = {"state": "live", "status": {"state": "working"}}
        states, hc, sleep = iter([working] * 5), pm.hc, pm.time.sleep
        looks = []

        def fake_sleep(_):
            looks.append(1)
            if len(looks) == 2:
                with contextlib.redirect_stdout(io.StringIO()):
                    pm.cmd_update(type("A", (), {"id": "p-long", "status": "review", "commit": "abc", "keep": False,
                                                 "note": long}))
        pm.hc = lambda *args, **kw: next(states, None) if args[0] == "get" else None
        pm.time.sleep = fake_sleep
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                pm.cmd_wait(type("A", (), {"id": "p-long", "timeout": 60}))
        finally:
            pm.hc, pm.time.sleep = hc, sleep
        self.assertIn(long, out.getvalue())
        self.assertNotIn(" …", out.getvalue())

    def test_show_is_short_and_json_is_the_whole_record(self):
        repo = pm.project_root(tempfile.mkdtemp())
        pm.save({"id": "s-show", "title": "精简", "project": "s", "repo": repo, "status": "review", "owner": "pm",
                 "base": "main", "branch": "dev/s", "commit": "c0ffee", "created": pm.now(),
                 "log": [{"at": f"11-15 0{i}", "by": "hc:t1", "text": f"entry {i}"} for i in range(5)]})
        out = self.run_pm("show", "s-show")
        self.assertIn("s-show  [review]  精简", out)
        self.assertIn("branch=dev/s", out)
        self.assertIn("commit=c0ffee", out)
        self.assertEqual([n for n in range(5) if f"entry {n}" in out], [2, 3, 4])  # the last three only
        self.assertNotIn("{", out)
        whole = json.loads(self.run_pm("show", "s-show", "--json"))
        self.assertEqual((len(whole["log"]), whole["commit"], set(whole["live"])), (5, "c0ffee", {"ahead", "dirty"}))

    def run_status(self, *argv, panes=()):
        saved = pm.agents, pm.herdr, pm.hc
        pm.agents, pm.herdr, pm.hc = (lambda: list(panes)), (lambda *a, **kw: None), (lambda *a, **kw: None)
        try:
            return self.run_pm("status", *argv)
        finally:
            pm.agents, pm.herdr, pm.hc = saved

    def test_status_lists_this_project_unless_all(self):
        here, there = (pm.project_root(tempfile.mkdtemp(prefix=n)) for n in ("here-", "there-"))
        for repo, tid, status in ((here, "here-task", "in_progress"), (there, "there-task", "in_progress"),
                                  (here, "here-old", "done")):
            pm.save({"id": tid, "title": tid, "project": Path(repo).name, "repo": repo, "status": status,
                     "owner": "pm", "base": "main", "created": pm.now()})
        mine = self.run_status("--repo", here)
        every = self.run_status("--repo", here, "--all")
        nowhere = self.run_status("--repo", tempfile.mkdtemp())  # no project there: everything, as before
        self.assertIn("here-task", mine)
        self.assertNotIn("there-task", mine)
        self.assertTrue(all(t in out for out in (every, nowhere) for t in ("here-task", "there-task")))
        # --all widens the projects only; closed tasks need --closed, as the old --all gave them
        self.assertFalse(any("here-old" in out for out in (mine, every, nowhere)))
        self.assertIn("here-old", self.run_status("--repo", here, "--closed"))
        self.assertNotIn("there-task", self.run_status("--repo", here, "--closed"))

    def test_status_in_the_hub_lists_every_project(self):
        """The hub is registered (pms/hub.json) for a folder in the ledger home: it is no project to narrow to."""
        hub = Path(pm.STATE) / "hub"
        hub.mkdir(parents=True, exist_ok=True)
        pm.PMS.mkdir(parents=True, exist_ok=True)
        (pm.PMS / "hub.json").write_text(json.dumps({"project": "hub", "repo": str(hub), "name": "pm-hub"}))
        repo = pm.project_root(tempfile.mkdtemp(prefix="proj-"))
        pm.save({"id": "proj-task", "title": "proj-task", "project": Path(repo).name, "repo": repo,
                 "status": "in_progress", "owner": "pm", "base": "main", "created": pm.now()})
        try:
            out = self.run_status("--repo", str(hub))
        finally:
            (pm.PMS / "hub.json").unlink()
        self.assertIn("proj-task", out)
        self.assertNotIn("(--all", out)
        # a registration whose repo is another folder (the same slug by chance) does not narrow status either
        other = Path(tempfile.mkdtemp()) / Path(repo).name
        other.mkdir()
        (pm.PMS / f"{pm.project_slug(repo)}.json").write_text(json.dumps({"repo": repo}))
        try:
            self.assertIn("proj-task", self.run_status("--repo", str(other)))
        finally:
            (pm.PMS / f"{pm.project_slug(repo)}.json").unlink()

    def test_status_lists_the_folders_under_this_project(self):
        """A PM of a plain folder (issues) owns the projects inside it (issues/site-a), as the board counts them;
        a sibling that only starts with its name does not belong to it."""
        here = Path(pm.project_root(tempfile.mkdtemp(prefix="nest-")))
        (here / "site-a").mkdir()
        sibling = Path(f"{here}-old")
        sibling.mkdir()
        elsewhere = pm.project_root(tempfile.mkdtemp())
        for repo, tid, project in ((here / "site-a", "nest-sub", "site-a"), (sibling, "nest-sibling", sibling.name),
                                   (elsewhere, "nest-named", "nestp")):
            pm.save({"id": tid, "title": tid, "project": project, "repo": str(repo), "status": "in_progress",
                     "owner": "pm", "base": "main", "created": pm.now()})
        pm.PMS.mkdir(parents=True, exist_ok=True)
        registration = pm.PMS / f"{pm.project_slug(here)}.json"
        registration.write_text(json.dumps({"project": "nestp", "repo": str(here), "name": "pm-nestp"}))
        try:
            mine = self.run_status("--repo", str(here))
        finally:
            registration.unlink()
        self.assertIn(pm.tr(f"Tasks of {here.name}", f"{here.name} 的任务"), mine)
        self.assertIn("nest-sub", mine)
        self.assertIn("nest-named", mine)  # elsewhere, but the board gives it to this PM by its project name
        self.assertNotIn("nest-sibling", mine)

    def test_status_unregistered_work_under_this_project(self):
        here = Path(pm.project_root(tempfile.mkdtemp(prefix="scope-")))
        pm.save({"id": "scope-task", "title": "scope-task", "project": here.name, "repo": str(here),
                 "status": "in_progress", "owner": "pm", "base": "main", "created": pm.now()})
        inner, outer = here / "inner", Path(tempfile.mkdtemp(prefix="outer-")).resolve()
        for repo in (inner, outer):
            repo.mkdir(exist_ok=True)
            run = lambda *args: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                                                *args], check=True, capture_output=True)
            run("init", "-q", "-b", "main")
            (repo / "a.txt").write_text("one\n")
            run("add", "a.txt")
            run("commit", "-q", "-m", "init")
            (repo / "a.txt").write_text("two\n")  # uncommitted: unregistered work
        panes = [{"pane_id": f"w-{repo.name[:5]}", "cwd": str(repo), "agent_status": "idle", "agent": "claude",
                  "name": repo.name, "workspace_id": ""} for repo in (inner, outer)]
        mine = self.run_status("--repo", str(here), panes=panes)
        every = self.run_status("--repo", str(here), "--all", panes=panes)
        self.assertIn("pane w-inner", mine)
        self.assertNotIn("pane w-outer", mine)
        self.assertTrue("pane w-inner" in every and "pane w-outer" in every)

    def diff_task(self, repo, tid, branch, worktree=None):
        pm.save({"id": tid, "title": "d", "project": repo.name, "repo": str(repo), "status": "review", "owner": "pm",
                 "base": "main", "branch": branch, "created": pm.now(), **({"worktree": worktree} if worktree else {})})
        return self.run_pm("diff", tid)

    def test_diff_prints_the_stat_and_line_totals(self):
        repo, git = make_repo()
        git("checkout", "-q", "dev/x")
        (repo / "a.txt").write_text("one\ntwo\nthree\n")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text("x = 1\ny = 2\n")
        (repo / "evidence" / "截图").mkdir(parents=True)
        (repo / "evidence" / "截图" / "说明.md").write_text("看过了\n")
        git("add", "a.txt", "tests/test_a.py", "evidence")
        git("rm", "-q", "new.txt")  # added and deleted on the branch: not in the diff against main
        git("commit", "-q", "-m", "more")
        git("checkout", "-q", "main")
        out = self.diff_task(repo, "d-diff", "dev/x", worktree=str(repo / "gone"))  # its worktree was removed
        self.assertIn("git diff --stat main...dev/x", out)
        self.assertIn("evidence/截图/说明.md", out)  # the name as it is, not quoted escapes
        self.assertIn("total: 3 files, +5 -0 (5 lines)", out)
        self.assertIn("source (without tests and evidence): 1 files, +2 -0 (2 lines)", out)
        self.assertIn("worktree gone", out)
        self.assertIn("small (§4): yes", out)
        self.assertNotIn("+two", out)  # no diff text
        self.assertNotIn("deleted:", out)
        self.assertNotIn("exit:", out)

    def test_diff_says_what_is_not_small(self):
        repo, git = make_repo()
        git("checkout", "-q", "-b", "dev/y")
        git("rm", "-q", "a.txt")
        (repo / "mods" / "pm-x").mkdir(parents=True)
        (repo / "mods" / "pm-x" / "main.js").write_text("view();\n")
        (repo / "icon.png").write_bytes(b"\x89PNG\x00\x01")
        git("add", "mods", "icon.png")
        git("commit", "-q", "-m", "ui")
        git("checkout", "-q", "-b", "dev/big", "main")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_big.py").write_text("x = 1\n" * 160)  # tests only, but past the total cap
        git("add", "tests")
        git("commit", "-q", "-m", "big")
        git("checkout", "-q", "-b", "dev/swift", "main")
        for path, text in (("Sources/App/Panel.swift", "import Foundation\nimport SwiftUI\n"),
                           ("Sources/Core/Model.swift", "import Foundation\nstruct Model {}\n")):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text)
        git("add", "Sources")
        git("commit", "-q", "-m", "swift")
        git("checkout", "-q", "main")
        out = self.diff_task(repo, "d-swift", "dev/swift")  # a SwiftUI view shows on screen; a model does not
        self.assertIn("UI (visual result): Sources/App/Panel.swift\n", out)
        self.assertIn("small (§4): no, UI files", out)
        out = self.diff_task(repo, "d-ui", "dev/y")
        self.assertIn("deleted: a.txt", out)
        self.assertIn("binary: icon.png", out)
        self.assertIn("UI (visual result): icon.png, mods/pm-x/main.js", out)
        self.assertNotIn("worktree gone", out)  # it never had one
        self.assertIn("small (§4): no, deletes files; binary files; UI files", out)
        out = self.diff_task(repo, "d-big", "dev/big")
        self.assertIn("small (§4): no, 160 lines in all > 150", out)
        self.assertEqual((pm.ui_file("mods/pm-dash/skill/scripts/pm.py"), pm.ui_file("mods/pm-x/model.test.mjs"),
                          pm.ui_file("mods/pm-dash/skill/assets/dash.html")), (False, False, True))
        self.assertEqual((pm.ui_file("App/Base.lproj/Main.storyboard"), pm.ui_file("App/Assets.xcassets/a/Contents.json"),
                          pm.ui_file("App/Remote.swift", "import AppKit\n")), (True, True, False))
        self.assertFalse(pm.ui_file("Tests/AppTests/PanelTests.swift", "import SwiftUI\n"))  # a test, not a view
        self.assertTrue(pm.side_file("Tests/AppTests/PanelTests.swift"))


class ConversationLog(unittest.TestCase):
    """The conversation belongs to the project: a session appends to it, a fresh one reads it."""

    def test_turn_hook_keeps_what_was_said_in_a_pm_session(self):
        repo = pm.project_root(tempfile.mkdtemp())
        pm.PMS.mkdir(parents=True, exist_ok=True)
        (pm.PMS / "c.json").write_text(json.dumps({"name": "pm-c", "pane": "hc:t7", "project": "c", "repo": repo}))
        turns = [("hc:t7", "UserPromptSubmit", {"prompt": "先做看板"}),
                 ("hc:t7", "Stop", {"last_assistant_message": "好，已派出。"}),
                 ("hc:t7", "UserPromptSubmit", {"prompt": "[Image #1] 这里不对"}),       # the user's, despite the bracket
                 ("hc:t7", "UserPromptSubmit", {"prompt": "[from hc:t3] task x is ready"}),  # another agent typed it
                 ("hc:t7", "UserPromptSubmit", {"prompt": '<hc from="t5">[from hc:t5] 要不要兼容旧版？</hc>'}),  # via hc send
                 ("hc:t7", "UserPromptSubmit", {"prompt": "/compact"}),
                 ("hc:t7", "UserPromptSubmit", {"prompt": "<task-notification>done</task-notification>"}),
                 ("hc:t7", "UserPromptSubmit", {"prompt": "/Users/me/a.png 看下"}),      # a path, not a slash command
                 ("hc:t7", "Stop", {"last_assistant_message": ""}),                      # the turn ended on a tool call
                 ("hc:t8", "UserPromptSubmit", {"prompt": "not a PM session"})]
        pane, stdin = pm.PANE, pm.sys.stdin
        try:
            for who, event, payload in turns:
                pm.PANE = who
                pm.sys.stdin = io.StringIO(json.dumps({"hook_event_name": event, **payload}))
                with contextlib.redirect_stdout(io.StringIO()):
                    pm.cmd_hook_turn(None)
        finally:
            pm.PANE, pm.sys.stdin = pane, stdin
            (pm.PMS / "c.json").unlink()
        events = pm.conversation(repo)
        self.assertEqual([(e["type"], e["text"]) for e in events],
                         [("user", "先做看板"), ("pm", "好，已派出。"), ("user", "[Image #1] 这里不对"),
                          ("agent", "task x is ready"), ("agent", "要不要兼容旧版？"), ("user", "/Users/me/a.png 看下")])
        self.assertEqual([e["by"] for e in events[3:5]], ["hc:t3", "hc:t5"])
        self.assertEqual(events[1]["by"], "hc:t7")                      # which session spoke

    def test_ledger_entries_and_decisions_join_the_log_and_a_handover_reads_it(self):
        repo = pm.project_root(tempfile.mkdtemp())
        name = Path(repo).name
        pm.record(repo, "user", text="连线别用直角")
        pm.record(repo, "pm", text="记下了，已派给 worker。")
        pm.record(repo, "agent", by="hc:t3", text="task wires is ready")
        pm.record(repo, "pm", text="收到，开始审查。")  # answers the worker, not the user
        with open(pm.project_dir(repo) / "conversation.jsonl", "a") as f:
            f.write('null\n[]\nnot json\n{"type": "pm", "text": null}\n')  # stray lines must not break a handover
        task = {"id": f"{name}-wires", "title": "改连线", "project": name, "repo": repo, "status": "in_progress",
                "owner": "pm", "base": "main", "created": pm.now()}
        pm.note(task, "dispatched to w1")
        pm.save(task)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pm.cmd_decide(type("A", (), {"repo": repo, "text": "连线不用直角", "quote": "别用直角"}))
            pm.cmd_handover(type("A", (), {"repo": repo, "turns": 6}))
            pm.cmd_conversation(type("A", (), {"repo": repo, "last": 20, "type": "thread,decision", "width": 300}))
        events = pm.conversation(repo)
        self.assertEqual([e["type"] for e in events], ["user", "pm", "agent", "pm", "pm", "thread", "decision"])
        self.assertEqual((events[5]["task"], events[5]["status"], events[5]["text"]),
                         (f"{name}-wires", "in_progress", "dispatched to w1"))
        text = out.getvalue()
        self.assertIn("User: 连线别用直角\nPM: 记下了，已派给 worker。", text)  # the handover, with no transcript at all
        self.assertNotIn("收到，开始审查。", text)
        self.assertIn(f"[{name}-wires · in_progress]", text)                    # the conversation command
        self.assertIn('连线不用直角 — "别用直角"', text)

    def test_a_user_turn_is_paired_with_its_own_reply_only(self):
        repo = pm.project_root(tempfile.mkdtemp())
        for kind, text in (("user", "A"), ("pm", "reply to A"), ("pm", "a background wait finished"),
                           ("user", "B"), ("agent", "a worker reports"), ("pm", "answers the worker"),
                           ("user", "C")):
            pm.record(repo, kind, text=text)
        self.assertEqual(pm.log_tail(repo), [{"user": "A", "pm": "reply to A"}, {"user": "B", "pm": ""},
                                             {"user": "C", "pm": ""}])


class ProjectView(unittest.TestCase):
    """What the desktop project view reads: quick answers on a blocked task, and where the log is."""

    def test_a_question_of_its_own_is_a_blocked_entry_with_quick_answers(self):
        repo = pm.project_root(tempfile.mkdtemp())
        blank = {f: None for f in ("owner", "workspace", "pane", "agent", "branch", "worktree", "base", "brief", "slug")}
        args = type("A", (), {**blank, "title": "推到 GitHub 并装到 MBP", "repo": repo, "status": "blocked",
                              "note": "这一轮的改动还没推，现在做吗？", "option": ["推并装", " 先不 "]})
        with contextlib.redirect_stdout(io.StringIO()):
            task_id = pm.cmd_new(args)
        self.assertEqual(pm.load(task_id)["options"], ["推并装", "先不"])
        event = pm.conversation(repo)[-1]
        self.assertEqual((event["status"], event["text"], event["options"]),
                         ("blocked", "这一轮的改动还没推，现在做吗？", ["推并装", "先不"]))

    def test_options_are_kept_on_the_task_and_its_conversation_event(self):
        repo = pm.project_root(tempfile.mkdtemp())
        name = Path(repo).name
        pm.save({"id": f"{name}-q", "title": "去手", "project": name, "repo": repo, "status": "in_progress",
                 "owner": "pm", "base": "main", "created": pm.now()})
        args = lambda **kw: type("A", (), {"id": f"{name}-q", "note": None, "keep": False, "option": None, **kw})
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_update(args(status="blocked", note="技能改动也交给线程吗？", option=["交给线程", " 仍由 PM 改 ", ""]))
        self.assertEqual(pm.load(f"{name}-q")["options"], ["交给线程", "仍由 PM 改"])
        event = pm.conversation(repo)[-1]
        self.assertEqual((event["type"], event["status"], event["options"]), ("thread", "blocked", ["交给线程", "仍由 PM 改"]))
        self.assertEqual(event["text"], "status=blocked; 技能改动也交给线程吗？")
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_update(args(note="still waiting"))                      # a note alone keeps the question's answers
            self.assertEqual(pm.load(f"{name}-q")["options"], ["交给线程", "仍由 PM 改"])
            pm.cmd_update(args(status="in_progress", note="用户选了交给线程"))  # answered: they go
        self.assertNotIn("options", pm.load(f"{name}-q"))
        self.assertNotIn("options", pm.conversation(repo)[-1])
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_update(args(option=["是", "否"]))                       # answers alone still reach the log
        self.assertEqual(pm.conversation(repo)[-1]["options"], ["是", "否"])
        self.assertNotIn("option_notes", pm.conversation(repo)[-1])       # plain answers carry nothing more
        self.assertNotIn("recommended", pm.conversation(repo)[-1])

    def test_an_answer_can_say_why_and_the_first_can_be_recommended(self):
        repo = pm.project_root(tempfile.mkdtemp())
        name = Path(repo).name
        pm.save({"id": f"{name}-q", "title": "限流", "project": name, "repo": repo, "status": "in_progress",
                 "owner": "pm", "base": "main", "created": pm.now()})
        args = lambda **kw: type("A", (), {"id": f"{name}-q", "note": None, "keep": False, "option": None, **kw})
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_update(args(status="blocked", note="计数放在哪？", recommend=True, option=["Redis", "git log | head", " 先不做 "],
                               why={0: " 一份共享的计数，用你已经在跑的 Redis ", 1: "每个实例各数各的"}))
        task, event = pm.load(f"{name}-q"), pm.conversation(repo)[-1]
        for kept in (task, event):                                         # an answer is kept as written, `|` included
            self.assertEqual(kept["options"], ["Redis", "git log | head", "先不做"])
            self.assertEqual(kept["option_notes"], ["一份共享的计数，用你已经在跑的 Redis", "每个实例各数各的", ""])
            self.assertIs(kept["recommended"], True)
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_update(args(status="in_progress", note="用户选了 Redis"))   # answered: all of it goes
        task = pm.load(f"{name}-q")
        for gone in ("options", "option_notes", "recommended"):
            self.assertNotIn(gone, task)
            self.assertNotIn(gone, pm.conversation(repo)[-1])
        # A recommendation or a reason without its answer is an error, and nothing is written.
        before = (pm.load(f"{name}-q"), len(pm.conversation(repo)))
        for bad in (dict(recommend=True), dict(recommend=True, option=["", "B"]), dict(option=["", "B"], why={0: "why"})):
            with self.assertRaises(SystemExit):
                pm.cmd_update(args(status="blocked", note="?", **bad))
        self.assertEqual((pm.load(f"{name}-q"), len(pm.conversation(repo))), before)

    def test_why_explains_the_option_before_it(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--option", action="append")
        parser.add_argument("--why", action=pm.Why)
        a = parser.parse_args(["--option", "A", "--why", "because", "--option", "B", "--option", "C", "--why", "c"])
        self.assertEqual((a.option, a.why), (["A", "B", "C"], {0: "because", 2: "c"}))
        self.assertIsNone(parser.parse_args(["--option", "A"]).why)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            parser.parse_args(["--why", "no answer before it", "--option", "A"])

    def test_state_names_each_pms_conversation_log_and_worktree_folder(self):
        repo = pm.project_root(tempfile.mkdtemp())
        pm.PMS.mkdir(parents=True, exist_ok=True)
        (pm.PMS / "view.json").write_text(json.dumps({"name": "pm-view", "pane": "hc:t7", "project": "view", "repo": repo}))
        (pm.PMS / "norepo.json").write_text(json.dumps({"name": "pm-norepo", "pane": ""}))
        listing, pm.agents = pm.agents, lambda: []
        try:
            pms = {p["name"]: p for p in pm.dash_state()["pms"]}
        finally:
            pm.agents = listing
            (pm.PMS / "view.json").unlink()
            (pm.PMS / "norepo.json").unlink()
        path = Path(pms["pm-view"]["conversation"])
        self.assertEqual(path, pm.PROJECTS / pm.project_slug(repo) / "conversation.jsonl")
        self.assertFalse(path.parent.exists())  # reading state creates nothing
        self.assertEqual(pms["pm-norepo"]["conversation"], "")
        # Where dispatch makes this project's worktrees: the project view lists the sessions inside.
        self.assertEqual(Path(pms["pm-view"]["worktrees"]), Path.home() / ".herdr" / "worktrees" / Path(repo).name)
        self.assertEqual(pms["pm-norepo"]["worktrees"], "")


class ProjectLifecycle(unittest.TestCase):
    """archive, restore and start's --name/--space, with a fake hc and herdr-app."""

    def setUp(self):
        self.repo = pm.project_root(tempfile.mkdtemp())
        self.name = Path(self.repo).name
        self.calls, self.terms = [], {}
        self.saved = (pm.hc, pm.subprocess.run, pm.agents)

        def hc(*args, errors=False):
            self.calls.append(("hc",) + args)
            if args[0] == "get":
                return self.terms.get(args[1])
            if args[0] == "run":
                return {"address": "t50"}
            return {}

        real = pm.subprocess.run

        # The desktop app: `do` answers with self.reply (an exception is raised), `ls` lists self.spaces.
        self.reply, self.spaces = {"terminal": "t60"}, []

        def run(argv, **kw):
            if argv[0] != "herdr-app":
                return real(argv, **kw)  # git
            self.calls.append(tuple(argv))
            if argv[1] == "do" and isinstance(self.reply, Exception):
                raise self.reply
            out = json.dumps(self.reply if argv[1] == "do" else {"spaces": self.spaces})
            return type("R", (), {"returncode": 0, "stdout": out, "stderr": ""})()
        # The herdr TUI: self.tui is its agent list, None when herdr is not reachable.
        self.tui, self.close_ok = {"agents": []}, True

        def herdr(*args):
            self.calls.append(("herdr",) + args)
            if args[:2] == ("agent", "list"):
                return self.tui
            if args[:2] == ("agent", "rename"):
                for x in (self.tui or {}).get("agents", []):
                    if x["pane_id"] == args[2]:
                        x["name"] = args[3]
            if args[:2] == ("pane", "close"):
                return {} if self.close_ok else None
            return {}
        self.saved += (pm.herdr,)
        pm.hc, pm.subprocess.run, pm.herdr = hc, run, herdr
        pm.agents = lambda: (self.tui or {}).get("agents", [])

    def tearDown(self):
        pm.hc, pm.subprocess.run, pm.agents, pm.herdr = self.saved
        for path in pm.PMS.glob("*.json"):
            path.unlink()
        for path in pm.TASKS.glob(f"{self.name}-*.json"):
            path.unlink()

    def register(self, terminal="t7"):
        pm.PMS.mkdir(parents=True, exist_ok=True)
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(
            {"name": pm.pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": f"hc:{terminal}",
             "runtime": "hc", "terminal": terminal, "agent": "claude"}))
        self.terms[terminal] = {"state": "live", "labels": {"pm": self.name}, "cwd": self.repo}

    def task(self, slug, status):
        pm.save({"id": f"{self.name}-{slug}", "title": slug, "project": self.name, "repo": self.repo,
                 "status": status, "owner": "pm", "base": "main", "created": pm.now()})

    def quiet(self, fn, *args, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*args, **kw)

    def test_archive_pauses_open_tasks_ends_only_the_pm_terminal_and_runs_once(self):
        self.register()
        self.terms["t8"] = {"state": "live", "labels": {"task": f"{self.name}-a"}}  # a worker: left alone
        for slug, status in (("a", "in_progress"), ("b", "blocked"), ("c", "merged"), ("d", "paused")):
            self.task(slug, status)
        self.quiet(pm.cmd_archive, argparse.Namespace(project=self.repo))
        rec = pm.pm_record(self.repo)
        self.assertEqual(rec["archived"], pm.now()[:10])
        got = {t["id"][len(self.name) + 1:]: (t["status"], t.get("paused_from")) for t in pm.project_tasks(self.repo)}
        self.assertEqual(got, {"a": ("paused", "in_progress"), "b": ("paused", "blocked"), "c": ("merged", None),
                               "d": ("paused", None)})
        self.assertIn("project archived", pm.load(f"{self.name}-a")["log"][-1]["text"])
        self.assertEqual([c for c in self.calls if c[:2] in (("hc", "label"), ("hc", "kill"), ("hc", "rm"))],
                         [("hc", "label", "t7", "pm=", f"pm.retired={self.name}"), ("hc", "kill", "t7"),
                          ("hc", "rm", "t7")])
        # Again: nothing changes, nothing is ended.
        self.calls.clear()
        before = [pm.load(f"{self.name}-{s}") for s in "abcd"]
        self.quiet(pm.cmd_archive, argparse.Namespace(project=self.name))  # by its name this time
        self.assertEqual([pm.load(f"{self.name}-{s}") for s in "abcd"], before)
        self.assertEqual(self.calls, [])

    def test_archive_leaves_a_terminal_without_the_pm_label(self):
        self.register()
        self.terms["t7"]["labels"] = {}
        self.quiet(pm.cmd_archive, argparse.Namespace(project=self.repo))
        self.assertFalse([c for c in self.calls if c[:2] in (("hc", "kill"), ("hc", "rm"))])
        self.assertTrue(pm.pm_record(self.repo)["archived"])

    def test_restore_puts_tasks_back_and_starts_a_pm_from_the_handover(self):
        self.register()
        self.task("a", "review")
        self.task("d", "paused")
        self.quiet(pm.cmd_archive, argparse.Namespace(project=self.repo))
        self.terms.pop("t7")  # ended by the archive
        self.quiet(pm.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        self.assertEqual(pm.load(f"{self.name}-a")["status"], "review")
        self.assertNotIn("paused_from", pm.load(f"{self.name}-a"))
        self.assertEqual(pm.load(f"{self.name}-d")["status"], "paused")  # paused by hand: stays
        rec = pm.pm_record(self.repo)
        self.assertNotIn("archived", rec)
        self.assertEqual((rec["terminal"], rec["pane"]), ("t60", "hc:t60"))
        made = [json.loads(c[3]) for c in self.calls if c[:3] == ("herdr-app", "do", "space.new")]
        self.assertEqual([(m["name"], m["folder"]) for m in made], [(self.name, self.repo)])
        self.assertIn("[from pm.py restore]", made[0]["argv"][-1])
        self.assertIn("handover", made[0]["argv"][-1])

    def test_start_name_and_space(self):
        self.quiet(pm.cmd_start, argparse.Namespace(repo=self.repo, kind="codex", model=None, name="家里网络",
                                                    space="new"))
        made = [(c[2], json.loads(c[3])) for c in self.calls if c[:2] == ("herdr-app", "do")]
        self.assertEqual([(cmd, m["name"], m["argv"][0]) for cmd, m in made], [("space.new", "家里网络", "codex")])
        rec = pm.pm_record(self.repo)
        self.assertEqual((rec["terminal"], rec["agent"], rec["space_name"]), ("t60", "codex", "家里网络"))
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").unlink()
        # current, from a terminal without a space: a bare terminal, as start did before --space.
        self.calls.clear()
        self.quiet(pm.cmd_start, argparse.Namespace(repo=self.repo, kind="pi", model=None, name=None,
                                                    space="current"))
        self.assertFalse([c for c in self.calls if c[:2] == ("herdr-app", "do")])
        self.assertEqual(pm.pm_record(self.repo)["terminal"], "t50")
        self.assertNotIn("space_name", pm.pm_record(self.repo))

    def test_start_refuses_a_missing_folder_or_a_file(self):
        missing = str(Path(self.repo) / "nope")
        (Path(self.repo) / "file").write_text("x")
        for repo in (missing, str(Path(self.repo) / "file")):
            with self.assertRaises(SystemExit):
                pm.cmd_start(argparse.Namespace(repo=repo, kind=None, model=None, name=None, space="new"))
        self.assertFalse(self.calls)

    def archived_with_two_paused(self):
        self.register()
        self.task("a", "review")
        self.task("b", "blocked")
        self.quiet(pm.cmd_archive, argparse.Namespace(project=self.repo))
        self.terms.pop("t7")
        return pm.pm_record(self.repo)["archived"]

    def assert_still_archived(self, date):
        self.assertEqual(pm.pm_record(self.repo)["archived"], date)
        got = {t["id"][len(self.name) + 1:]: (t["status"], t.get("paused_from")) for t in pm.project_tasks(self.repo)}
        self.assertEqual(got, {"a": ("paused", "review"), "b": ("paused", "blocked")})

    def test_restore_checks_first_and_changes_nothing_when_it_cannot_start(self):
        date = self.archived_with_two_paused()
        hc = pm.hc
        pm.hc = lambda *args, **kw: None if args[0] == "server" else hc(*args, **kw)  # herdr-core not reachable
        try:
            with self.assertRaises(SystemExit):
                self.quiet(pm.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        finally:
            pm.hc = hc
        self.assert_still_archived(date)
        self.terms["t7"] = {"state": "live", "labels": {"pm": self.name}}  # an old PM still runs
        with self.assertRaises(SystemExit):
            self.quiet(pm.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        self.assert_still_archived(date)
        self.assertFalse([c for c in self.calls if c[:3] == ("herdr-app", "do", "space.new")])

    def test_a_restore_whose_start_fails_is_rolled_back_and_exits_non_zero(self):
        date = self.archived_with_two_paused()
        self.reply = {}  # space.new answers without a terminal, and no new space is open
        with self.assertRaises(SystemExit) as stop:
            self.quiet(pm.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        self.assertNotIn(stop.exception.code, (0, None))
        self.assert_still_archived(date)
        self.assertNotIn(("hc", "run"), [c[:2] for c in self.calls])  # no bare-terminal PM either

    def test_archive_ends_a_herdr_tui_pm_and_restore_is_not_stuck_on_it(self):
        pm.PMS.mkdir(parents=True, exist_ok=True)
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(
            {"name": pm.pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "wT:p1"}))
        for close_ok in (True, False):
            self.tui = {"agents": [{"pane_id": "wT:p1", "name": pm.pm_name(self.repo), "cwd": self.repo},
                                   {"pane_id": "wT:p2", "name": "worker"}]}
            self.close_ok, self.calls[:] = close_ok, []
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                pm.cmd_archive(argparse.Namespace(project=self.repo))
            self.assertEqual([c for c in self.calls if c[:2] in (("agent", "rename"), ("pane", "close"))
                              or c[1:3] in (("agent", "rename"), ("pane", "close"))],
                             [("herdr", "agent", "rename", "wT:p1", f"ex-{pm.pm_name(self.repo)}"),
                              ("herdr", "pane", "close", "wT:p1")])
            if not close_ok:
                self.assertIn("close it by hand", out.getvalue())  # the pane is still there, renamed
            self.assertIsNone(pm.find_pm(repo=self.repo))
            self.quiet(pm.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
            self.assertEqual(pm.pm_record(self.repo)["terminal"], "t60")
            self.terms.pop("t60", None)
            (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(
                {"name": pm.pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "wT:p1"}))
        self.tui = None  # herdr not reachable: said, not silently skipped
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pm.cmd_archive(argparse.Namespace(project=self.repo))
        self.assertIn("not reachable", out.getvalue())

    def test_a_space_new_that_times_out_reuses_the_space_it_made(self):
        old = {"id": "sp-old", "name": "家里网络", "tabs": [{"id": "tb1", "terminals": [{"terminal": "t1"}]}]}
        made = {"id": "sp-new", "name": "家里网络", "tabs": [{"id": "tb2", "terminals": [{"terminal": "t61"}]}]}
        self.spaces = [old]  # an older space of the same name is not the one this start made
        self.reply = subprocess.TimeoutExpired("herdr-app", 30)
        fake = pm.subprocess.run

        def run(argv, **kw):
            if argv[:3] == ["herdr-app", "do", "space.new"]:
                self.spaces = [old, made]  # the app made the space, but its answer came too late
            return fake(argv, **kw)
        pm.subprocess.run = run
        try:
            self.quiet(pm.cmd_start, argparse.Namespace(repo=self.repo, kind="codex", model=None, name="家里网络",
                                                        space="new"))
        finally:
            pm.subprocess.run = fake
        self.assertEqual(pm.pm_record(self.repo)["terminal"], "t61")
        self.assertNotIn(("hc", "run"), [c[:2] for c in self.calls])
        # Timed out and no new space under that name: an error, and no bare-terminal PM.
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").unlink()
        self.spaces, self.calls[:] = [old], []
        with self.assertRaises(SystemExit):
            self.quiet(pm.cmd_start, argparse.Namespace(repo=self.repo, kind="codex", model=None, name="家里网络",
                                                        space="new"))
        self.assertNotIn(("hc", "run"), [c[:2] for c in self.calls])
        self.assertIsNone(pm.pm_record(self.repo))

    def test_name_with_space_current_is_said_not_ignored(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.quiet(pm.cmd_start, argparse.Namespace(repo=self.repo, kind="pi", model=None, name="别名",
                                                        space="current"))
        self.assertIn("--space current", err.getvalue())

    def test_state_has_archived_and_card_counts(self):
        self.register()
        for slug, status in (("a", "in_progress"), ("b", "blocked"), ("c", "review"), ("d", "proposed"),
                             ("e", "merged"), ("f", "paused")):
            self.task(slug, status)
        row = next(p for p in pm.dash_state()["pms"] if p["repo"] == self.repo)
        self.assertIsNone(row["archived"])
        self.assertEqual(row["counts"], {"working": 1, "waiting": 1, "review": 1, "proposed": 1, "merged_today": 1})
        self.quiet(pm.cmd_archive, argparse.Namespace(project=self.repo))
        state = pm.dash_state()
        row = next(p for p in state["pms"] if p["repo"] == self.repo)
        self.assertEqual(row["archived"], pm.now()[:10])
        self.assertEqual(row["counts"], {"working": 0, "waiting": 0, "review": 0, "proposed": 0, "merged_today": 1})
        a = next(t for t in state["tasks"] if t["id"] == f"{self.name}-a")
        self.assertEqual((a["status"], a["paused_from"]), ("paused", "in_progress"))

    def test_a_review_thread_names_its_task_and_counts_with_it(self):
        self.register()
        self.task("w", "review")
        pm.save({"id": f"{self.name}-w-review", "title": "审查：w", "project": self.name, "repo": self.repo,
                 "status": "in_progress", "owner": "pm", "base": "main", "review_of": f"{self.name}-w",
                 "created": pm.now()})
        state = pm.dash_state()
        tasks = {t["id"]: t for t in state["tasks"]}
        self.assertEqual(tasks[f"{self.name}-w-review"]["review_of"], f"{self.name}-w")
        self.assertNotIn("review_of", tasks[f"{self.name}-w"])
        row = next(p for p in state["pms"] if p["repo"] == self.repo)
        self.assertEqual((row["counts"]["working"], row["counts"]["review"]), (0, 1))
        # The task counts as the views show it: in review while the review is open, waiting when the review asks,
        # its own status when either is paused.
        counts = lambda: next(p for p in pm.dash_state()["pms"] if p["repo"] == self.repo)["counts"]
        mine = lambda c: (c["working"], c["waiting"], c["review"])
        rid, wid = f"{self.name}-w-review", f"{self.name}-w"
        set_status = lambda tid, s: pm.save({**json.loads((pm.TASKS / f"{tid}.json").read_text()), "status": s})
        set_status(wid, "in_progress")
        self.assertEqual(mine(counts()), (0, 0, 1))
        set_status(rid, "blocked")
        self.assertEqual(mine(counts()), (0, 1, 0))
        set_status(wid, "paused")
        set_status(rid, "paused")
        self.assertEqual(mine(counts()), (0, 0, 0))
        # The task over while its review is open: the review counts on its own.
        set_status(wid, "abandoned")
        set_status(rid, "in_progress")
        self.assertEqual(mine(counts()), (1, 0, 0))
        set_status(wid, "review")
        # The task it reviews gone from the ledger: the review counts on its own again.
        os.remove(pm.TASKS / f"{self.name}-w.json")
        row = next(p for p in pm.dash_state()["pms"] if p["repo"] == self.repo)
        self.assertEqual((row["counts"]["working"], row["counts"]["review"]), (1, 0))

    def test_waiting_counts_each_blocked_task_once_by_repo_then_name(self):
        self.register()
        self.task("own", "blocked")
        # Another project's name, but in this PM's repo: the repo decides, it counts here.
        pm.save({"id": f"{self.name}-side", "title": "side", "project": "side-project", "repo": self.repo,
                 "status": "blocked", "owner": "pm", "base": "main", "created": pm.now()})
        # No PM for this repo or name: in no project's count, so not in the sidebar's total either.
        pm.save({"id": f"{self.name}-orphan", "title": "orphan", "project": f"{self.name}-nobody",
                 "repo": tempfile.mkdtemp(prefix="nobody-"), "status": "blocked", "owner": "pm", "base": "main",
                 "created": pm.now()})
        state = pm.dash_state()
        row = next(p for p in state["pms"] if p["repo"] == self.repo)
        self.assertEqual(row["counts"]["waiting"], 2)
        mine = {t["id"]: t["pm"] for t in state["tasks"] if t["id"].startswith(f"{self.name}-")}
        self.assertEqual(mine, {f"{self.name}-own": row["name"], f"{self.name}-side": row["name"],
                                f"{self.name}-orphan": ""})
        self.assertEqual(sum(p["counts"]["waiting"] for p in state["pms"] if not p["archived"]), 2)

    def test_an_answered_question_is_not_waiting(self):
        """A blocked task whose question the user answered (the card's 【title】option) waits for the PM, not the user."""
        self.register()
        self.task("ask", "blocked")
        self.task("other", "blocked")
        tid = f"{self.name}-ask"
        pm.record(self.repo, "thread", task=tid, title="ask", status="blocked", text="A or B?", options=["A", "B"])
        state = lambda: pm.dash_state()
        row = lambda s: next(p for p in s["pms"] if p["repo"] == self.repo)
        task = lambda s: next(t for t in s["tasks"] if t["id"] == tid)
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], "answered" in task(s)), (2, False))
        pm.record(self.repo, "user", text="【ask】A")
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], task(s).get("answered")), (1, True))
        self.assertNotIn("answered", next(t for t in s["tasks"] if t["id"] == f"{self.name}-other"))
        # A reply in between changes nothing; the task asking again is a new question, unanswered.
        pm.record(self.repo, "pm", text="收到")
        self.assertEqual(row(state())["counts"]["waiting"], 1)
        # The PM asks again while the task is still blocked: update --status blocked --ask says so in the log.
        pm.record(self.repo, "user", text="【ask】B")
        self.assertEqual(row(state())["counts"]["waiting"], 1)
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_update(argparse.Namespace(id=tid, status="blocked", note="B 的哪一种？", option=None, why=None,
                                             recommend=False, keep=False, ask=True,
                                             **{f: None for f in pm.FIELDS if f != "status"}))
        self.assertTrue(pm.conversation(self.repo)[-1]["text"].startswith("status=blocked; "))
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], "answered" in task(s)), (2, False))
        pm.record(self.repo, "user", text="【ask】B1")
        self.assertEqual(row(state())["counts"]["waiting"], 1)
        pm.record(self.repo, "thread", task=tid, title="ask", status="in_progress", text="doing A")
        pm.record(self.repo, "thread", task=tid, title="ask", status="blocked", text="C or D?", options=["C", "D"])
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], "answered" in task(s)), (2, False))

    def test_a_blocked_task_the_log_never_shows_is_answered_by_its_ledger_title(self):
        """Blocked before the conversation log began (no thread event; under the project's old name, owned by repo):
        it waits, and words that start with its 【title】 in the ledger answer it, as a card's would."""
        self.register()
        tid = f"{self.name}-ax"
        pm.save({"id": tid, "title": "辅助功能授权", "project": "OldName", "repo": self.repo, "status": "blocked",
                 "owner": "pm", "base": "main", "created": "2026-10-25 10:00", "log": [
                     {"at": "2026-10-25 10:00", "by": "hc:t9", "text": "registered (in_progress)"},
                     {"at": "2026-10-25 10:30", "by": "hc:t9", "text": "status=blocked; 要不要开辅助功能权限？"}]})
        self.task("other", "blocked")
        pm.record(self.repo, "thread", task=f"{self.name}-other", title="other", status="blocked", text="A or B?")
        row = lambda s: next(p for p in s["pms"] if p["repo"] == self.repo)
        task = lambda s: next(t for t in s["tasks"] if t["id"] == tid)
        s = pm.dash_state()
        self.assertEqual((row(s)["counts"]["waiting"], task(s)["pm"], "answered" in task(s)), (2, row(s)["name"], False))
        pm.record(self.repo, "user", text="现在开")                          # names no question
        self.assertEqual(row(pm.dash_state())["counts"]["waiting"], 2)
        pm.record(self.repo, "user", text="【辅助功能授权】现在开")
        s = pm.dash_state()
        self.assertEqual((row(s)["counts"]["waiting"], task(s).get("answered"), task(s)["asked_at"]), (1, True, "2026-10-25 10:30"))
        # A note on it afterwards (pm.py log) asks nothing: the answer stands, as on a task with a card.
        self.quiet(pm.cmd_log, argparse.Namespace(id=tid, text="等用户回家再开"))
        s = pm.dash_state()
        self.assertEqual((row(s)["counts"]["waiting"], task(s).get("answered")), (1, True))
        # Recording that answer with --status blocked again is refused, as for a task with a card.
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.quiet(pm.cmd_update, argparse.Namespace(**{"id": tid, "option": None, "why": None, "recommend": False,
                       "keep": False, "ask": False, "note": "用户：现在开", **{f: None for f in pm.FIELDS}, "status": "blocked"}))

    def test_blocked_again_on_an_answered_task_needs_ask(self):
        """Recording an answer with --status blocked would open a new question: refused unless --ask."""
        self.task("q", "in_progress")
        tid = f"{self.name}-q"
        update = lambda **kw: self.quiet(pm.cmd_update, argparse.Namespace(**{
            "id": tid, "option": None, "why": None, "recommend": False, "keep": False, "ask": False, "note": None,
            **{f: None for f in pm.FIELDS}, **kw}))
        answered = lambda: tid in pm.answered_tasks(pm.conversation(self.repo))
        update(status="blocked", note="现在装还是做完再装？")  # the first question: no --ask needed
        update(status="blocked", note="补一句")              # not answered yet: blocked again as before
        self.assertEqual(pm.load(tid)["status"], "blocked")
        pm.record(self.repo, "user", text="【q】全部做好了再装")
        self.assertTrue(answered())
        before, events = pm.load(tid), len(pm.conversation(self.repo))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            update(status="blocked", note="用户：全部做好了再装")
        self.assertIn("--ask", str(stop.exception.code))
        self.assertEqual((pm.load(tid), len(pm.conversation(self.repo))), (before, events))  # nothing written
        self.assertTrue(answered())
        with self.assertRaises(SystemExit):
            update(status="in_progress", ask=True)          # --ask is only for asking
        update(status="blocked", note="装到哪台机器？", ask=True)  # a follow-up: a new question
        self.assertFalse(answered())
        pm.record(self.repo, "user", text="【q】dev")
        update(status="in_progress", note="用户：装到 dev")       # recording the answer: moves on
        self.assertEqual(pm.load(tid)["status"], "in_progress")
        self.assertFalse(answered())

    def test_answered_tasks_follow_the_question_cards_rule(self):
        ev = lambda kind, **f: {"type": kind, **f}
        asked = [ev("thread", task="k", title="old", status="in_progress"), ev("thread", task="k", status="blocked")]
        titles = {"k": "限流"}
        self.assertEqual(pm.answered_tasks(asked, titles), set())
        self.assertEqual(pm.answered_tasks(asked + [ev("user", text=" 【限流】 Redis ")], titles), {"k"})
        self.assertEqual(pm.answered_tasks(asked + [ev("user", text="用 Redis 吧")], titles), set())   # names no question
        # The card's "own words" row: the box's words after the 【title】, with the files it carried.
        own = "【限流】都不要，先不限流\n\n附件：\n/tmp/a.png"
        self.assertEqual(pm.answered_tasks(asked + [ev("user", text=own)], titles), {"k"})
        # With a pasted screenshot the log has its image mark first: still the card's answer, as in pm-project.
        for marked in ("[Image #1]【限流】都不要", "[Image #2] [Image #3]【限流】都不要", "[Image #1]\n【限流】都不要"):
            self.assertEqual(pm.answered_tasks(asked + [ev("user", text=marked)], titles), {"k"}, marked)
        self.assertEqual(pm.answered_tasks(asked + [ev("user", text="[Image #1]都不要")], titles), set())
        self.assertEqual(pm.answered_tasks(asked + [ev("user", text="【old】Redis")]), {"k"})            # the log's title
        # Said before the question, or the task moved on: not answered.
        self.assertEqual(pm.answered_tasks([asked[0], ev("user", text="【限流】Redis"), asked[1]], titles), set())
        self.assertEqual(pm.answered_tasks(asked + [ev("user", text="【限流】Redis"),
                                                    ev("thread", task="k", status="in_progress")], titles), set())
        # Asked again while blocked (update --status blocked, or new options): unanswered; a plain note is not asking.
        answered = asked + [ev("user", text="【限流】Redis")]
        for again in (ev("thread", task="k", status="blocked", text="status=blocked; 哪个实例？"),
                      ev("thread", task="k", status="blocked", text="哪个实例？", options=["本机", "集群"])):
            self.assertEqual(pm.answered_tasks(answered + [again], titles), set())
            self.assertEqual(pm.answered_tasks(answered + [again, ev("user", text="【限流】集群")], titles), {"k"})
        self.assertEqual(pm.answered_tasks(answered + [ev("thread", task="k", status="blocked", text="已转给 worker")], titles), {"k"})
        # Blocked in the ledger, never in the log (asked before it began): its ledger 【title】 anywhere answers it,
        # whatever its old entries say; nothing else does.
        older = [ev("thread", task="w", title="旧名", status="in_progress"), ev("user", text="好")]
        self.assertEqual(pm.answered_tasks(older, {"w": "窗口"}), set())
        self.assertEqual(pm.answered_tasks(older + [ev("user", text="【窗口】先不做")], {"w": "窗口"}), {"w"})
        self.assertEqual(pm.answered_tasks([ev("user", text="【窗口】先不做")], {"w": "窗口"}), {"w"})
        self.assertEqual(pm.answered_tasks([ev("user", text="【窗口】先不做")]), set())   # not blocked in the ledger
        self.assertEqual(pm.answered_tasks(asked + [ev("user", text="【窗口】x")], {**titles, "w": "窗口"}), {"w"})
        # When the ledger asked (asked_at): words before it answered an older question, not this one; a note in
        # the log after it asks nothing, a new status=blocked does.
        when = {"w": "2026-11-15 10:00"}
        before = ev("user", at="2026-11-15 09:00:00", text="【窗口】先不做")
        after = ev("user", at="2026-11-15 10:05:00", text="【窗口】先不做")
        self.assertEqual(pm.answered_tasks([before], {"w": "窗口"}, when), set())
        self.assertEqual(pm.answered_tasks([before, after], {"w": "窗口"}, when), {"w"})
        noted = ev("thread", task="w", title="窗口", status="blocked", at="2026-11-15 10:10:00", text="等用户回家")
        self.assertEqual(pm.answered_tasks([after, noted], {"w": "窗口"}, when), {"w"})
        again = ev("thread", task="w", title="窗口", status="blocked", at="2026-11-15 10:10:00", text="status=blocked; 还有一件")
        self.assertEqual(pm.answered_tasks([after, again], {"w": "窗口"}, {"w": "2026-11-15 10:10"}), set())
        # Two open questions of one title: the words answer the newest.
        two = asked + [ev("thread", task="j", status="blocked"), ev("user", text="【限流】Redis")]
        self.assertEqual(pm.answered_tasks(two, {"k": "限流", "j": "限流"}), {"j"})


def make_repo():
    """A throwaway repository with a main branch and a task branch dev/x that adds new.txt."""
    repo = Path(tempfile.mkdtemp(prefix="land-")).resolve()  # a project of its own, with its own verify file
    git = lambda *args: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                       check=True, capture_output=True, text=True).stdout
    git("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "init")
    git("checkout", "-q", "-b", "dev/x")
    (repo / "new.txt").write_text("hello\n")
    git("add", "new.txt")
    git("commit", "-q", "-m", "add new.txt")
    git("checkout", "-q", "main")
    os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return repo, git


class LandAndReview(unittest.TestCase):
    def task(self, repo, task_id, **extra):
        pm.save({"id": task_id, "title": "加一行", "project": repo.name, "repo": str(repo), "status": "review",
                 "owner": "pm", "base": "main", "branch": "dev/x", "dispatched": True, "created": pm.now(), **extra})

    def land(self, task_id, keep=False, timeout=600):
        out, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                pm.cmd_land(argparse.Namespace(id=task_id, keep=keep, message=None, timeout=timeout))
        except SystemExit as stop:
            code = stop.code
        return code, out.getvalue()

    def verify(self, repo, text):
        path = pm.verify_file(str(repo))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def clean(self, git):
        self.assertEqual(git("status", "--porcelain", "--untracked-files=no"), "")
        self.assertNotEqual(subprocess.run(["git", "-C", git("rev-parse", "--show-toplevel").strip(), "rev-parse",
                                            "-q", "--verify", "MERGE_HEAD"], capture_output=True).returncode, 0)

    def test_land_refuses_with_exit_2_and_changes_nothing(self):
        repo, git = make_repo()
        self.task(repo, "l-none")
        code, out = self.land("l-none")
        self.assertEqual(code, 2)
        self.assertIn(str(pm.verify_file(str(repo))), out)
        self.verify(repo, "# only a comment\n\n")  # counts as no checks
        self.assertEqual(self.land("l-none")[0], 2)
        self.verify(repo, "true\n")
        (repo / "a.txt").write_text("dirty\n")
        self.assertEqual(self.land("l-none"), (2, f"{repo} has uncommitted changes; land merges only into a clean checkout\n"))
        git("checkout", "a.txt")
        git("checkout", "-q", "-b", "other")
        self.assertEqual(self.land("l-none")[0], 2)  # not on the base branch
        git("checkout", "-q", "main")
        (repo / "new.txt").write_text("untracked, in the way\n")
        code, out = self.land("l-none")
        self.assertEqual(code, 2)
        self.assertIn("untracked", out)
        self.clean(git)
        self.assertEqual(pm.load("l-none")["status"], "review")

    def test_a_failing_check_aborts_and_leaves_the_checkout_clean(self):
        repo, git = make_repo()
        self.task(repo, "l-fail")
        self.verify(repo, "# the checks\ntrue\necho broken; false\n")
        code, out = self.land("l-fail")
        self.assertEqual(code, 1)
        self.assertIn("echo broken; false", out)
        self.assertIn("broken", out)
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertFalse((repo / "new.txt").exists())
        self.assertEqual(pm.load("l-fail")["status"], "review")
        self.assertIn("echo broken; false", pm.load("l-fail")["log"][-1]["text"])

    def test_a_merge_that_cannot_be_undone_is_said_with_exit_5(self):
        # The check changes a file the merge brought in: git refuses both `merge --abort` and `reset --merge`.
        repo, git = make_repo()
        self.task(repo, "l-stuck")
        self.verify(repo, "echo changed >> new.txt; false\n")
        code, out = self.land("l-stuck")
        self.assertEqual(code, 5)
        self.assertIn("could not be undone", out)
        self.assertIn("MERGE_HEAD", out)
        self.assertIn("new.txt", out)
        self.assertNotIn("the merge is aborted", out)

    def test_checks_have_a_time_limit(self):
        repo, git = make_repo()
        self.task(repo, "l-slow")
        self.verify(repo, "echo started; sleep 30\n")
        began = pm.time.time()
        code, out = self.land("l-slow", timeout=1)
        self.assertLess(pm.time.time() - began, 10)
        self.assertEqual(code, 1)
        self.assertIn("timed out", out)
        self.assertIn("started", out)
        self.clean(git)

    def test_land_stopped_by_a_signal_undoes_the_merge(self):
        repo, git = make_repo()
        self.task(repo, "l-killed")
        self.verify(repo, "sleep 30\n")
        proc = subprocess.Popen([sys.executable, str(Path(pm.__file__)), "land", "l-killed"],
                                env={**os.environ, "PM_HOME": HOME}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(100):  # until the merge has started and the check is running
            if (repo / ".git" / "MERGE_HEAD").exists():
                break
            pm.time.sleep(0.05)
        pm.time.sleep(0.5)
        proc.terminate()
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 128 + 15, out)
        self.assertIn("aborted", out)
        self.clean(git)
        self.assertFalse((repo / "new.txt").exists())

    def test_conflicts_abort_with_exit_4(self):
        repo, git = make_repo()
        (repo / "new.txt").write_text("other\n")
        git("add", "new.txt")
        git("commit", "-q", "-m", "conflicting new.txt")
        self.task(repo, "l-conflict")
        self.verify(repo, "true\n")
        code, out = self.land("l-conflict")
        self.assertEqual(code, 4)
        self.assertIn("  new.txt\n", out)
        self.assertEqual(git("status", "--porcelain"), "")

    def test_passing_checks_commit_mark_merged_and_retire(self):
        repo, git = make_repo()
        self.task(repo, "l-pass")
        self.verify(repo, "true\ntest -f new.txt\n")
        code, out = self.land("l-pass")
        self.assertEqual(code, 0, out)
        task = pm.load("l-pass")
        self.assertEqual((task["status"], task["commit"]), ("merged", git("rev-parse", "--short", "HEAD").strip()))
        self.assertTrue(task.get("retired"))
        self.assertIn("2", out.splitlines()[0])
        self.assertIn("branch dev/x", out)
        self.assertEqual(git("log", "-1", "--format=%s").strip(), "merge dev/x: 加一行")

    def test_review_is_a_thread_with_a_generated_brief(self):
        repo, git = make_repo()
        git("branch", "-D", "dev/x")  # the task's branch lives in its worktree here
        tree = Path(tempfile.mkdtemp()).resolve() / "tree"
        git("worktree", "add", "-q", str(tree), "-b", "dev/x")
        self.task(repo, "r-a", worktree=str(tree), brief="/briefs/a.md", agent="w-a")
        self.verify(repo, "make test\n")
        (Path(HOME) / "config.json").write_text(json.dumps({"lang": "zh", "worker": {"kind": "codex"},
                                                              "reviewer": {"kind": "claude", "model": "opus"}}))
        calls, hc, sleep = [], pm.hc, pm.time.sleep

        def fake_hc(*args, **kw):
            calls.append(args)
            if args[0] == "run":
                return {"address": f"t4{sum(c[0] == 'run' for c in calls)}"}
            if args[0] == "get":
                return {"state": "live", "status": {"state": "idle"}, "labels": {"task": "r-a-review"}}
            return {"started": True} if args[0] == "send" else {}
        pm.hc, pm.time.sleep = fake_hc, lambda _: None
        review = lambda: pm.cmd_review(argparse.Namespace(id="r-a", name=None, kind=None, model=None, effort=None))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                review()
            task = pm.load("r-a-review")
            brief = Path(task["brief"]).read_text()
            run = next(c for c in calls if c[0] == "run")
            # The reviewer key wins over worker, and a Claude Code reviewer has no tool that writes files.
            self.assertEqual(run[run.index("--") + 1:],
                             ("claude", "--model", "opus", "--disallowedTools", "Edit,Write,NotebookEdit"))
            self.assertEqual(run[run.index("--cwd") + 1], str(tree))
            self.assertEqual((task["title"], task["pane"], task["status"]), ("审查：加一行", "hc:t41", "in_progress"))
            for part in ("/briefs/a.md", "main...dev/x", "检查清单", "make test", "不提交",
                         "update r-a-review --status done --note", "无阻塞"):
                self.assertIn(part, brief)
            self.assertIn(("send", "t41", brief), calls)
            # Retiring the review itself ends its reviewer.
            with contextlib.redirect_stdout(io.StringIO()):
                pm.cmd_retire(argparse.Namespace(id="r-a-review", force=False))
            self.assertIn(("kill", "t41"), calls)
            self.assertTrue(pm.load("r-a-review").get("retired"))
            self.assertTrue(tree.exists())  # the task's worktree is not the review's to remove
            # Run again, then retiring the task closes its review and ends the new reviewer's terminal.
            with contextlib.redirect_stdout(io.StringIO()):
                review()
            self.assertFalse(pm.load("r-a-review").get("retired"))
            git("merge", "-q", "--no-ff", "-m", "m", "dev/x")
            with contextlib.redirect_stdout(io.StringIO()):
                pm.cmd_retire(argparse.Namespace(id="r-a", force=False))
            task = pm.load("r-a-review")
            self.assertTrue(task.get("retired"))
            self.assertEqual(task["status"], "done")
            self.assertIn(("kill", "t42"), calls)
            self.assertFalse(tree.exists())
        finally:
            pm.hc, pm.time.sleep = hc, sleep
            (Path(HOME) / "config.json").unlink()

    def test_a_review_run_again_after_a_report_counts_a_round(self):
        repo, git = make_repo()
        git("branch", "-D", "dev/x")
        tree = Path(tempfile.mkdtemp()).resolve() / "tree"
        git("worktree", "add", "-q", str(tree), "-b", "dev/x")
        self.task(repo, "r-n", worktree=str(tree), status="in_progress")  # a task from before rounds: no field
        hc, sleep = pm.hc, pm.time.sleep
        pm.hc = lambda *args, **kw: ({"address": "t60"} if args[0] == "run" else {"started": True}
                                     if args[0] == "send" else {"state": "live", "status": {"state": "idle"}})
        pm.time.sleep = lambda _: None
        self.addCleanup(lambda: setattr(pm, "hc", hc) or setattr(pm.time, "sleep", sleep))

        def review(report=False):
            with contextlib.redirect_stdout(io.StringIO()):
                pm.cmd_review(argparse.Namespace(id="r-n", name=None, kind="claude", model="opus", effort=None))
                if report:
                    pm.cmd_update(argparse.Namespace(id="r-n-review", status="done", keep=False,
                                                     note=report if isinstance(report, str) else "1. 少一个测试",
                                                     **{f: None for f in pm.FIELDS if f != "status"}))
            return pm.load("r-n").get("rounds")
        self.assertIsNone(review(report=True))  # the first review is no round of rework
        self.assertEqual(review(), 1)  # the first one reported: this is the second review
        self.assertEqual(review(report=True), 1)  # the one before never reported (restarted): not counted
        self.assertEqual(review(), 2)
        self.assertEqual(review(report="无阻塞。检查都过了"), 2)  # the one before never reported
        self.assertEqual(review(), 2)  # the one before passed: a re-review is no rework
        self.assertEqual(review(report=True), 2)
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_retire(argparse.Namespace(id="r-n-review", force=False))
        self.assertEqual(review(), 2)  # the thread was closed (as an escalation closes it): a fresh start

    def test_a_claude_pm_is_started_without_edit_tools(self):
        repo = pm.project_root(tempfile.mkdtemp())
        seen, start, claim = [], pm.start_pm_terminal, pm.cmd_claim
        pm.start_pm_terminal = lambda repo, argv, space=None, new_space="": seen.append(argv) or "t50"
        pm.cmd_claim = lambda a: None
        try:
            pm.cmd_start(argparse.Namespace(repo=repo, kind="claude", model=""))
            self.assertEqual(seen[-1][:5], ["claude", "--model", "opus", "--disallowedTools", "Edit,NotebookEdit"])
            self.assertEqual(seen[-1][-2], "--")  # the prompt cannot be read as one more tool name
            # A rotation carries the denial over once, and config can turn it off.
            old = seen[-1][1:]
            self.assertEqual(pm.narrow_pm("claude", pm.successor_argv("claude", old, "", "接手")).count("--disallowedTools"), 1)
            (Path(HOME) / "config.json").write_text(json.dumps({"pm": {"narrow_tools": False}}))
            pm.cmd_start(argparse.Namespace(repo=repo, kind="claude", model=""))
            self.assertNotIn("--disallowedTools", seen[-1])
            self.assertNotIn("--disallowedTools", pm.narrow_pm("claude", pm.successor_argv("claude", old, "", "接手")))
            # The configured command of a kind is used, narrowed.
            (Path(HOME) / "config.json").write_text(json.dumps({"agents": {"claude": {"argv": ["/opt/claude", "--x"]}}}))
            pm.cmd_start(argparse.Namespace(repo=repo, kind="claude", model="m"))
            self.assertEqual(seen[-1][:6], ["/opt/claude", "--x", "--model", "m", "--disallowedTools", "Edit,NotebookEdit"])
            (Path(HOME) / "config.json").unlink()
            pm.cmd_start(argparse.Namespace(repo=repo, kind="codex", model=""))
            self.assertNotIn("--disallowedTools", seen[-1])  # other agents are started as before
        finally:
            pm.start_pm_terminal, pm.cmd_claim = start, claim
            (Path(HOME) / "config.json").unlink(missing_ok=True)

    def test_a_claude_pm_starts_lean_on_opus(self):
        repo = pm.project_root(tempfile.mkdtemp())
        claude = Path(HOME) / "claude"
        for name in ("pm", "wecom", "other-skill"):
            (claude / "skills" / name).mkdir(parents=True, exist_ok=True)
            (claude / "skills" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
        (claude / "skills" / "synced" / "b1").mkdir(parents=True, exist_ok=True)
        (claude / "skills" / "synced" / "b1" / "manifest.json").write_text(json.dumps({"skills": [{"name": "docs"}]}))
        (claude / "settings.json").write_text(json.dumps({"enabledPlugins": {"playwright@x": True, "off@x": False}}))
        settings = str(Path(HOME) / "pm-settings.json")
        seen, start, claim = [], pm.start_pm_terminal, pm.cmd_claim
        pm.start_pm_terminal = lambda repo, argv, space=None, new_space="": seen.append(argv) or "t50"
        pm.cmd_claim = lambda a: None
        try:
            pm.cmd_start(argparse.Namespace(repo=repo, kind="claude", model=None))
            argv = seen[-1]
            head = argv[:argv.index("--")]
            self.assertEqual(head, ["claude", "--model", "opus", "--disallowedTools", "Edit,NotebookEdit",
                                    "--strict-mcp-config", "--no-chrome", "--settings", settings])
            # Plugins off and the other skills hidden from the model, for this session only; pm stays listed.
            self.assertEqual(json.loads(Path(settings).read_text()), {
                "enabledPlugins": {"playwright@x": False},
                "skillOverrides": {"anthropic-skills:docs": "user-invocable-only", "wecom": "user-invocable-only",
                                   "other-skill": "user-invocable-only"}})
            # A rotation: no flag twice, the outgoing model (Fable) is not carried over, an explicit one wins.
            old = ["--model", "fable"] + argv[3:]
            rotated = pm.pm_argv("claude", pm.successor_argv("claude", old, pm.pm_model("claude"), "接手"))
            self.assertEqual(rotated, head + ["--", "接手"])
            self.assertNotIn("fable", rotated)
            self.assertEqual(pm.pm_model("claude", "sonnet"), "sonnet")
            pm.cmd_start(argparse.Namespace(repo=repo, kind="claude", model="sonnet"))
            self.assertEqual(seen[-1][1:3], ["--model", "sonnet"])
            # config.json's pm.model is the default; for another kind it is not used by a rotation.
            (Path(HOME) / "config.json").write_text(json.dumps({"pm": {"model": "opus[1m]"}}))
            self.assertEqual(pm.pm_model("claude"), "opus[1m]")
            pm.cmd_start(argparse.Namespace(repo=repo, kind="claude", model=None))
            self.assertEqual(seen[-1][1:3], ["--model", "opus[1m]"])
            (Path(HOME) / "config.json").write_text(json.dumps({"pm": {"kind": "codex", "model": "gpt"}}))
            self.assertEqual(pm.pm_model("claude"), "opus")
            pm.cmd_start(argparse.Namespace(repo=repo, kind=None, model=None))
            self.assertEqual(seen[-1][seen[-1].index("-m") + 1], "gpt")  # pm.kind's own model
            pm.cmd_start(argparse.Namespace(repo=repo, kind="claude", model=None))
            self.assertEqual(seen[-1][1:3], ["--model", "opus"])  # not codex's
            # The README's example: pm.model belongs to claude, so `start --kind codex` (and restore) runs codex's own.
            (Path(HOME) / "config.json").write_text(json.dumps({"pm": {"kind": "claude", "model": "opus"}}))
            pm.cmd_start(argparse.Namespace(repo=repo, kind="codex", model=None))
            self.assertNotIn("opus", seen[-1])
            self.assertNotIn("-m", seen[-1][:-1])
            self.assertEqual(pm.pm_model("codex"), "")  # a rotated codex PM: the program's own model, as before
            # A --settings of the user's own is kept, and not doubled.
            mine = pm.pm_argv("claude", ["claude", "--settings", "/me.json", "--", "p"])
            self.assertEqual(mine.count("--settings"), 1)
            self.assertIn("/me.json", mine)
            # {"pm": {"lean": false}}: as before, and what a lean session carried over is dropped.
            (Path(HOME) / "config.json").write_text(json.dumps({"pm": {"lean": False}}))
            plain = pm.pm_argv("claude", pm.successor_argv("claude", old, "", "接手"))
            for flag in ("--strict-mcp-config", "--no-chrome", "--settings"):
                self.assertNotIn(flag, plain)
            self.assertIn("--disallowedTools", plain)
            # Other agents are started as before: no lean flags, no default model.
            (Path(HOME) / "config.json").unlink()
            pm.cmd_start(argparse.Namespace(repo=repo, kind="codex", model=None))
            self.assertFalse({"--strict-mcp-config", "--no-chrome", "--settings", "--model"} & set(seen[-1]))
            self.assertEqual(pm.pm_argv("pi", ["pi", "x"]), ["pi", "x"])
        finally:
            pm.start_pm_terminal, pm.cmd_claim = start, claim
            (Path(HOME) / "config.json").unlink(missing_ok=True)


class Offline(unittest.TestCase):
    """A task whose terminal is gone is marked offline in `state`, and `reattach` brings its agent back."""

    def setUp(self):
        self.repo = pm.project_root(tempfile.mkdtemp())
        self.name = Path(self.repo).name
        self.claude, self.codex = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        self.live = {"t1", "tpm"}          # what `hc ls` lists as live; None: hc is not reachable
        self.calls, self.tui = [], []
        saved = (pm.hc, pm.herdr, pm.agents, pm.time.sleep, pm.CLAUDE_PROJECTS, pm.CODEX_SESSIONS)

        def hc(*args, errors=False):
            self.calls.append(args)
            if args[0] == "ls":
                return None if self.live is None else {"terminals": [{"address": a, "state": "live"} for a in self.live]}
            if args[0] == "get":
                if args[1] == "tpm":
                    return {"state": "live", "labels": {"pm": self.name}, "cwd": self.repo}
                if args[1] in self.live:
                    return {"state": "live", "status": {"state": "idle"}}
                return {"state": "finished", "cwd": self.repo}
            if args[0] == "run":
                self.live.add("t70")
                return {"address": "t70"}
            if args[0] == "send":
                return {"started": True}
            return {}
        pm.hc, pm.herdr, pm.agents = hc, lambda *a, **kw: None, lambda: self.tui
        pm.time.sleep = lambda _: None
        pm.CLAUDE_PROJECTS, pm.CODEX_SESSIONS = self.claude, self.codex
        pm.PMS.mkdir(parents=True, exist_ok=True)
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(
            {"name": pm.pm_name(self.repo), "project": self.name, "repo": self.repo, "runtime": "hc",
             "terminal": "tpm", "pane": "hc:tpm"}))

        def restore():
            (pm.hc, pm.herdr, pm.agents, pm.time.sleep, pm.CLAUDE_PROJECTS, pm.CODEX_SESSIONS) = saved
            (pm.PMS / f"{pm.project_slug(self.repo)}.json").unlink(missing_ok=True)
            for path in pm.TASKS.glob(f"{self.name}-*.json"):
                path.unlink()
        self.addCleanup(restore)

    def task(self, slug, status="in_progress", pane="hc:t2", **extra):
        task = {"id": f"{self.name}-{slug}", "title": f"线程 {slug}", "project": self.name, "repo": self.repo,
                "status": status, "owner": "pm", "base": "main", "pane": pane, "created": "2026-11-14 01:00", **extra}
        pm.save(task)
        return task["id"]

    def session(self, folder, sid, *texts, cwd=None):
        path = self.claude / pm.claude_folder(folder) / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [json.dumps({"type": "user", "cwd": cwd or folder, "message": {"content": t}}) for t in texts]
        path.write_text("\n".join(rows) + "\n")
        return path

    def reattach(self, task_id):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pm.cmd_reattach(argparse.Namespace(id=task_id))
        return out.getvalue()

    def started(self):
        run = [c for c in self.calls if c[0] == "run"]
        self.assertEqual(len(run), 1)
        return list(run[0])

    def sent(self):
        return [c[2] for c in self.calls if c[0] == "send"]

    def offline_ids(self):
        return {t["id"] for t in pm.dash_state()["tasks"] if t["offline"] and t["id"].startswith(self.name)}

    def test_state_marks_open_work_whose_terminal_is_gone(self):
        ids = {k: self.task(k, status, pane) for k, status, pane in (
            ("live", "in_progress", "hc:t1"), ("gone", "in_progress", "hc:t2"), ("review", "review", "hc:t3"),
            ("asks", "blocked", "hc:t4"), ("paused", "paused", "hc:t5"), ("merged", "merged", "hc:t6"),
            ("nopane", "in_progress", ""), ("remote", "in_progress", "hc:mbp/t7"), ("tui", "in_progress", "w1:p2"))}
        self.tui = [{"pane_id": "w9:p1", "name": "x"}]  # herdr answers, and no agent runs in w1:p2
        self.assertEqual(self.offline_ids(), {ids["gone"], ids["review"], ids["asks"], ids["tui"]})
        state = pm.dash_state()
        gone = next(t for t in state["tasks"] if t["id"] == ids["gone"])
        self.assertEqual(gone["status"], "in_progress")  # the status is not changed for the PM
        self.tui = []                                       # herdr says nothing: the TUI pane is not judged
        self.assertNotIn(ids["tui"], self.offline_ids())
        self.live = None                                    # hc says nothing: no hc terminal is judged
        self.assertEqual(self.offline_ids(), set())

    def working(self):
        return next(p for p in pm.dash_state()["pms"] if p["repo"] == self.repo)["counts"]["working"]

    def test_a_project_whose_only_work_is_offline_is_not_working(self):
        gone = self.task("gone", "in_progress", "hc:t2")
        self.assertEqual(self.working(), 0)
        self.assertEqual(pm.load(gone)["status"], "in_progress")  # the ledger is left as it is
        self.task("live", "in_progress", "hc:t1")
        self.assertEqual(self.working(), 1)
        self.live = None                                    # hc says nothing: in progress counts as before
        self.assertEqual(self.working(), 2)

    def test_reattach_resumes_the_session_that_reports_on_the_task(self):
        tid = self.task("a", branch="dev/a")
        worker = self.session(self.repo, "s-worker", f"brief… pm.py update {tid} --status review --commit <sha>")
        # Newer, and naming the task, but not its agent: the PM, and a reviewer of the task.
        self.session(self.repo, "s-pm", f"You are pm-x, {pm.PM_SESSION_MARK}. dispatched {tid}")
        self.session(self.repo, "s-review", f"Review of task {tid}: pm.py update {tid}-review --status done")
        old = Path(self.claude / pm.claude_folder(self.repo) / "s-worker.jsonl")
        os.utime(old, (1, pm.created_at(pm.load(tid)) + 60))  # older than the others, still after the task began
        self.assertTrue(worker.exists())
        out = self.reattach(tid)
        run = self.started()
        self.assertEqual(run[run.index("--") + 1:], ["claude", "--resume", "s-worker"])
        self.assertEqual(run[run.index("--parent") + 1], "tpm")       # under the PM, as dispatch places a worker
        self.assertEqual(run[run.index("--cwd") + 1], self.repo)
        task = pm.load(tid)
        self.assertEqual((task["pane"], task["status"], task["session"]),
                         ("hc:t70", "in_progress", {"kind": "claude", "id": "s-worker"}))
        self.assertIn(("label", "t70", f"task={tid}"), self.calls)
        self.assertIn("s-worker", task["log"][-1]["text"])
        self.assertEqual(len(self.sent()), 1)
        self.assertIn(f"show {tid}", self.sent()[0])
        self.assertIn("resume claude pane=hc:t70", out)
        self.assertNotIn(tid, self.offline_ids())                      # the new terminal is the task's now

    def test_a_session_started_in_a_folder_above_the_repo_is_found(self):
        tid = self.task("up", owner="self")
        self.session(str(Path(self.repo).parent), "s-up", f"pm.py log {tid} 定位中", cwd=str(Path(self.repo).parent))
        plan = pm.reattach_plan(pm.load(tid))
        self.assertEqual((plan["how"], plan["argv"][-2:], plan["cwd"]),
                         ("resume", ["--resume", "s-up"], str(Path(self.repo).parent)))

    def test_reattach_resumes_a_codex_session(self):
        tid = self.task("cx", log=[{"at": "2026-11-14 01:00", "by": "hc:tpm",
                                     "text": "dispatched to w-cx (codex gpt-x high)"}])
        path = self.codex / "2026" / "11" / "14" / "rollout-1.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": "c-123", "cwd": self.repo}}) + "\n"
                        + json.dumps({"type": "message", "text": f"pm.py update {tid} --status review"}) + "\n")
        self.reattach(tid)
        run = self.started()
        cmd = run[run.index("--") + 1:]
        self.assertEqual(cmd[:2], ["codex", "resume"])
        self.assertEqual(cmd[-1], "c-123")
        self.assertIn("gpt-x", cmd)
        self.assertEqual(run[run.index("--name") + 1], f"{self.name}-cx")

    def test_without_a_session_a_fresh_agent_gets_the_tasks_context(self):
        brief = Path(tempfile.mkdtemp()) / "brief.md"
        brief.write_text("把断开的线程标出来")
        tid = self.task("new", brief=str(brief), agent="w-new", log=[
            {"at": "2026-11-14 01:00", "by": "hc:tpm", "text": "dispatched to w-new (codex gpt-x high)"},
            {"at": "2026-11-14 02:00", "by": "hc:t2", "text": "做了一半：state 已加字段"}])
        self.session(self.repo, "s-other", "an unrelated session")
        out = self.reattach(tid)
        run = self.started()
        self.assertEqual(run[run.index("--") + 1:], pm.agent_argv("codex", "gpt-x", "high"))
        self.assertEqual(run[run.index("--name") + 1], "w-new")
        text = self.sent()[0]
        for part in (f"线程 new", tid, "把断开的线程标出来", "做了一半：state 已加字段", f"update {tid} --status review"):
            self.assertIn(part, text)
        task = pm.load(tid)
        self.assertEqual((task["pane"], task["status"]), ("hc:t70", "in_progress"))
        self.assertNotIn("session", task)
        self.assertIn("fresh codex", out)

    def test_reattach_refuses_live_or_closed_work(self):
        live, merged = self.task("live", pane="hc:t1"), self.task("done", status="merged")
        for tid in (live, merged):
            with self.assertRaises(SystemExit):
                self.reattach(tid)
        self.assertFalse([c for c in self.calls if c[0] == "run"])
        self.assertEqual(pm.load(live)["pane"], "hc:t1")

    def nested(self, slug, **extra):
        """A task of a project inside this PM's repository (issues/site-a under pm-issues)."""
        sub = Path(self.repo) / "site-a"
        sub.mkdir(exist_ok=True)
        return self.task(slug, repo=str(sub), project="site-a", **extra)

    def test_a_project_inside_the_pms_repo_reattaches_under_that_pm(self):
        tid = self.nested("hc")
        self.reattach(tid)
        run = self.started()
        self.assertEqual(run[run.index("--parent") + 1], "tpm")  # not a bare terminal (--no-parent)
        self.assertEqual(pm.load(tid)["workspace"], "")

    def test_a_herdr_tui_pm_gets_the_agent_in_a_tab_of_its_workspace(self):
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(
            {"name": pm.pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "wS:p1",
             "workspace": "wS"}))
        self.tui = [{"pane_id": "wS:p1", "name": pm.pm_name(self.repo), "workspace_id": "wS"}]
        seen = []

        def herdr(*args):
            seen.append(args)
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "wS:t9"}, "root_pane": {"pane_id": "wS:p9"}}
            return {}
        pm.herdr = herdr
        tid = self.nested("tui", pane="wS:p3", workspace="wS")  # its old pane: no agent runs there
        self.session(self.repo, "s-tui", f"pm.py update {tid} --note 定位中")
        self.assertIn(tid, self.offline_ids())
        out = self.reattach(tid)
        create = next(c for c in seen if c[:2] == ("tab", "create"))
        self.assertEqual(create[create.index("--workspace") + 1], "wS")
        self.assertEqual(create[create.index("--cwd") + 1], self.repo)   # where the session was started
        run = next(c for c in seen if c[:2] == ("pane", "run"))
        self.assertEqual(run[2], "wS:p9")
        argv = pm.shlex.split(run[3])
        self.assertEqual(argv[:3], ["claude", "--resume", "s-tui"])
        self.assertIn(f"show {tid}", argv[3])                            # the prompt goes on its command line
        self.assertFalse([c for c in self.calls if c[0] == "run"])       # no hc terminal anywhere
        task = pm.load(tid)
        self.assertEqual((task["pane"], task["workspace"], task["status"]), ("wS:p9", "wS", "in_progress"))
        self.assertIn("pane=wS:p9", out)

    def test_no_tab_in_the_tui_pms_workspace_means_nothing_changes(self):
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(
            {"name": pm.pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "wS:p1"}))
        self.tui = [{"pane_id": "wS:p1", "name": pm.pm_name(self.repo), "workspace_id": "wS"}]
        pm.herdr = lambda *args: None
        tid = self.task("notab", pane="wS:p3")
        with self.assertRaises(SystemExit):
            self.reattach(tid)
        self.assertFalse([c for c in self.calls if c[0] == "run"])
        self.assertEqual(pm.load(tid)["pane"], "wS:p3")

    def test_only_a_sessions_opening_makes_it_a_pms(self):
        reply = json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "ok"}})
        hook = json.dumps({"attachment": {"type": "hook_success", "content": f"You are pm-x, {pm.PM_SESSION_MARK}."}})
        self.assertTrue(pm.pm_session(hook + "\n" + reply))
        self.assertTrue(pm.pm_session(json.dumps({"type": "user", "message": {"content": "[from pm.py rotate] 你是"}})))
        # A worker that later reads or quotes the PM's words is still the worker.
        worker = "\n".join([json.dumps({"type": "user", "message": {"content": "brief: update x-1 --status review"}}),
                             reply, json.dumps({"type": "user", "message": {"content": f"cat: {pm.PM_SESSION_MARK}"}})])
        self.assertFalse(pm.pm_session(worker))
        self.assertEqual(pm.session_score(worker, "x-1"), 2)

    def test_a_lock_left_by_a_killed_reattach_does_not_hold(self):
        tid = self.task("lock")
        lock = pm.STATE / "reattach" / f"{tid}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        dead = subprocess.Popen(["true"])
        dead.wait()
        lock.write_text(f"{dead.pid} 0\n")                     # its process is gone: taken over at once
        self.reattach(tid)
        self.assertFalse(lock.exists())
        self.assertEqual(pm.load(tid)["pane"], "hc:t70")
        tid = self.task("held")
        lock = pm.STATE / "reattach" / f"{tid}.lock"
        lock.write_text(f"{os.getpid()} 0\n")                  # a reattach that still runs
        with self.assertRaises(SystemExit):
            self.reattach(tid)
        os.utime(lock, (1, 1))                                  # unless it has run for more than five minutes
        self.assertTrue(pm.stale_lock(lock))
        lock.unlink()

    def test_the_agents_own_ledger_writes_record_its_session(self):
        tid = self.task("own", pane="hc:t1")
        pane = pm.PANE
        os.environ["CLAUDE_CODE_SESSION_ID"] = "s-own"
        try:
            pm.PANE = "hc:t1"
            with contextlib.redirect_stdout(io.StringIO()):
                pm.cmd_update(argparse.Namespace(id=tid, note="进展", keep=False, option=None,
                                                 **{f: None for f in pm.FIELDS}))
            self.assertEqual(pm.load(tid)["session"], {"kind": "claude", "id": "s-own"})
            pm.PANE = "hc:tpm"                                 # the PM writing on its parked task: not its agent
            other = self.task("parked", pane="hc:tpm")
            with contextlib.redirect_stdout(io.StringIO()):
                pm.cmd_update(argparse.Namespace(id=other, note="进展", keep=False, option=None,
                                                 **{f: None for f in pm.FIELDS}))
            self.assertNotIn("session", pm.load(other))
        finally:
            pm.PANE = pane
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)


class OutsideReads(unittest.TestCase):
    """A Claude Code worker or reviewer reads the brief, the project's briefs/ and Herdr's API docs outside its
    worktree without being asked: --settings <file> with Read allow rules (and blockReadsExemptPaths for the user who
    blocks such reads), which grant no write."""

    def setUp(self):
        self.repo, self.git = make_repo()
        (self.repo / "briefs" / "projects").mkdir(parents=True)
        self.brief = self.repo / "briefs" / "projects" / "x.md"
        self.brief.write_text("Read briefs/shot.png.")
        self.docs = Path(tempfile.mkdtemp()).resolve() / "herdr-app"
        self.docs.mkdir()
        old = pm.HERDR_DOCS
        pm.HERDR_DOCS = self.docs
        self.addCleanup(setattr, pm, "HERDR_DOCS", old)
        self.calls, hc, sleep = [], pm.hc, pm.time.sleep

        def fake_hc(*args, **kw):
            self.calls.append(args)
            if args[0] == "run":
                return {"address": "t5"}
            if args[0] == "get":
                return {"state": "live", "status": {"state": "idle"}}
            return {"started": True} if args[0] == "send" else {}
        pm.hc, pm.time.sleep = fake_hc, lambda _: None
        self.addCleanup(setattr, pm, "hc", hc)
        self.addCleanup(setattr, pm.time, "sleep", sleep)
        self.wanted = [str(self.brief.parent), str(self.repo / "briefs"), str(self.docs)]

    def started(self):
        run = next(c for c in self.calls if c[0] == "run")
        return list(run[run.index("--") + 1:])

    def exempt(self, argv):
        """The folders the worker may read, from its --settings file, which allows nothing else."""
        self.assertEqual(argv.count("--settings"), 1)
        self.assertNotIn("--add-dir", argv)  # --add-dir would let the worker write there too
        given = argv[argv.index("--settings") + 1]
        permissions = json.loads(Path(given).read_text())["permissions"]
        self.assertEqual(set(permissions), {"allow", "blockReadsExemptPaths"})
        # A folder with all below it, a single file as it is; "//" starts an absolute path in a rule.
        self.assertEqual(permissions["allow"], [f"Read(/{p}/**)" if Path(p).is_dir() else f"Read(/{p})"
                                                for p in permissions["blockReadsExemptPaths"]])
        self.assertTrue(all(rule.startswith("Read(//") for rule in permissions["allow"]))
        return permissions["blockReadsExemptPaths"]

    def test_dispatch_lets_a_claude_worker_read_the_brief_and_the_docs(self):
        home = pm.worktree_home
        pm.worktree_home = lambda r: Path(tempfile.mkdtemp()) / "app"
        self.addCleanup(setattr, pm, "worktree_home", home)
        a = pm.worker_defaults(argparse.Namespace(repo=str(self.repo), brief=str(self.brief), branch="dev/y",
                                                  base="main", prep=None, name="y", kind="claude", model="",
                                                  effort="", title="y", label="y"))
        with contextlib.redirect_stdout(io.StringIO()):
            pm.dispatch_hc(a, str(self.repo), self.brief.read_text())
        argv = self.started()
        self.assertEqual(argv[0], "claude")
        self.assertEqual(self.exempt(argv), self.wanted)
        # What the worker is sent says the docs are for reading only.
        sent = next(c[2] for c in self.calls if c[0] == "send")
        self.assertIn(str(self.docs), pm.docs_line())
        self.assertTrue(sent.startswith("Read briefs/shot.png.") and sent.endswith(pm.docs_line()))
        # Other programs have no such block: started as before.
        codex = pm.worker_defaults(argparse.Namespace(kind="codex", model="", effort=""))
        self.assertEqual(pm.worker_argv(codex, pm.outside_reads(str(self.repo), str(self.brief))),
                         pm.worker_argv(codex))
        # A path is listed in every spelling a read may arrive by, since Claude Code follows no link in it.
        link = Path(tempfile.mkdtemp()).resolve() / "link"
        link.symlink_to(self.repo)
        self.assertEqual(pm.outside_reads(str(link)), [str(link / "briefs"), str(self.repo / "briefs"), str(self.docs)])
        pm.HERDR_DOCS = self.docs / "gone"
        self.assertEqual((pm.outside_reads(str(self.repo), "/nowhere/b.md"), pm.docs_line()),
                         ([str(self.repo / "briefs")], ""))

    def test_review_lets_the_reviewer_read_the_brief_and_the_docs(self):
        self.git("branch", "-D", "dev/x")  # the task's branch lives in its worktree here
        tree = Path(tempfile.mkdtemp()).resolve() / "tree"
        self.git("worktree", "add", "-q", str(tree), "-b", "dev/x")
        pm.save({"id": "o-r", "title": "读外面", "project": self.repo.name, "repo": str(self.repo), "status": "review",
                 "owner": "pm", "base": "main", "branch": "dev/x", "worktree": str(tree), "brief": str(self.brief),
                 "created": pm.now()})
        with contextlib.redirect_stdout(io.StringIO()):
            pm.cmd_review(argparse.Namespace(id="o-r", name=None, kind="claude", model="opus", effort=None))
        argv = self.started()
        self.assertEqual(self.exempt(argv), self.wanted)
        self.assertEqual(argv[-2:], ["--disallowedTools", "Edit,Write,NotebookEdit"])
        self.assertTrue(Path(pm.load("o-r-review")["brief"]).read_text().endswith(pm.docs_line()))

    def test_the_terminal_ui_gets_a_settings_path_it_can_type(self):
        tree, calls = tempfile.mkdtemp(), []

        def fake_herdr(*args):
            calls.append(args)
            if args[:2] == ("worktree", "create"):
                return {"workspace": {"workspace_id": "w2"}, "pane": {"pane_id": "w2:p1"}, "path": tree}
            return {"ok": True}
        saved = pm.herdr, pm.PANE
        pm.herdr, pm.PANE = fake_herdr, "w1:p0"
        self.addCleanup(lambda: setattr(pm, "herdr", saved[0]) or setattr(pm, "PANE", saved[1]))
        a = argparse.Namespace(repo=str(self.repo), brief=str(self.brief), branch="dev/t", base=None, prep=None,
                               name="w", title="t", label="t", kind="claude", model="opus", effort=None, profile=None,
                               advisor=None, confirmed=False)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            pm.cmd_dispatch(a)
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        args = list(start[start.index("--") + 1:])
        self.assertEqual(args[:2], ["--model", "opus"])
        self.assertEqual(self.exempt(args), self.wanted)

    def test_a_ledger_path_with_spaces_reaches_the_terminal_ui_whole(self):
        """herdr agent start quotes each argument as it types the command into the pane's shell (seen in a herdr
        session of its own: `--settings '/…/led ger/reads/a b.json'`), so pm.py hands it the path as it is."""
        state = pm.STATE
        pm.STATE = Path(tempfile.mkdtemp()) / "led ger"
        self.addCleanup(setattr, pm, "STATE", state)
        args = pm.read_settings("claude", pm.outside_reads(str(self.repo), str(self.brief)))
        self.assertEqual(args[0], "--settings")
        self.assertTrue(args[1].startswith(str(pm.STATE / "reads")) and "'" not in args[1])  # not quoted twice
        self.assertEqual(self.exempt(args), self.wanted)
        self.assertEqual(shlex.split(shlex.join(["claude", *args])), ["claude", *args])  # the line herdr types

    def test_a_brief_in_a_wide_folder_is_let_through_alone(self):
        home = Path(tempfile.mkdtemp()).resolve() / "users" / "me"
        home.mkdir(parents=True)
        patch = mock.patch.object(Path, "home", lambda *_: home)
        patch.start()
        self.addCleanup(patch.stop)
        for wide in (Path("/"), home, home.parent, Path("/tmp"), Path("/private/tmp"), Path(tempfile.gettempdir())):
            self.assertTrue(pm.wide_folder(wide), wide)
        self.assertFalse(pm.wide_folder(self.brief.parent))
        for folder in (home, home.parent, Path("/tmp"), Path(tempfile.gettempdir())):
            handle, name = tempfile.mkstemp(suffix=".md", dir=folder)
            os.close(handle)
            self.addCleanup(os.unlink, name)
            brief = Path(name)
            reads = pm.outside_reads(str(self.repo), name)
            self.assertIn(str(brief.resolve()), reads)  # the brief itself
            self.assertFalse({str(folder), str(folder.resolve())} & set(reads), folder)  # not all beside it
            self.assertIn(f"Read(/{brief.resolve()})", json.loads(Path(pm.read_settings("claude", reads)[1])
                                                                  .read_text())["permissions"]["allow"])
        # A brief in a folder of its own: that folder, with the screenshots beside it.
        self.assertEqual(pm.outside_reads(str(self.repo), str(self.brief))[0], str(self.brief.parent))

    def test_reattach_brings_the_worker_back_with_the_same_reads(self):
        tree = Path(tempfile.mkdtemp()).resolve()
        task = {"id": "o-t", "title": "t", "repo": str(self.repo), "worktree": str(tree), "brief": str(self.brief),
                "worker": {"kind": "claude", "model": "opus"}}
        found = pm.find_session
        self.addCleanup(setattr, pm, "find_session", found)
        pm.find_session = lambda task, old_cwd="": None
        fresh = pm.reattach_plan(task)
        self.assertEqual((fresh["how"], fresh["argv"][:3]), ("fresh", ["claude", "--model", "opus"]))
        self.assertEqual(self.exempt(fresh["argv"]), self.wanted)
        pm.find_session = lambda task, old_cwd="": {"kind": "claude", "id": "s1", "cwd": str(tree)}
        resumed = pm.reattach_plan(task)
        self.assertEqual((resumed["how"], resumed["argv"][-4:-2]), ("resume", ["--resume", "s1"]))
        self.assertEqual(self.exempt(resumed["argv"]), self.wanted)
        # A review thread: its own brief in the ledger's sent/, and the brief of the task it reviews.
        pm.save({**task, "status": "review", "owner": "pm", "project": "p", "created": pm.now()})
        sent = pm.STATE / "sent" / "o-t-review.md"
        sent.parent.mkdir(parents=True, exist_ok=True)
        sent.write_text("审查")
        review = {"id": "o-t-review", "title": "审查", "repo": str(self.repo), "brief": str(sent), "review_of": "o-t",
                  "worker": {"kind": "claude", "model": "sonnet"}}
        self.assertEqual(self.exempt(pm.reattach_plan(review)["argv"]),
                         [str(sent.parent), *([str(sent.parent.resolve())] if sent.parent.resolve() != sent.parent
                                              else []), *self.wanted])


class SeamlessRotation(unittest.TestCase):
    """A rotation the user does not notice: a short handover, the waits started again, the same tab, no greeting."""

    def setUp(self):
        self.repo = pm.project_root(tempfile.mkdtemp())
        self.name = Path(self.repo).name
        self.saved = (pm.hc, pm.subprocess.run, pm.end_retired_later, pm.PANE, pm.HC_TERMINAL)
        self.calls, self.terms, self.spaces, self.envs = [], {}, [], []

        def hc(*args, errors=False, env=None):
            self.calls.append(("hc",) + args)
            if args[0] == "run":
                self.envs.append(env)
            if args[0] == "get":
                return self.terms.get(args[1])
            if args[0] == "run":
                return {"address": "t50"}
            return {}
        real = pm.subprocess.run

        def run(argv, **kw):
            if argv[0] != "herdr-app":
                return real(argv, **kw)
            self.calls.append(tuple(argv))
            out = json.dumps({"ok": True} if argv[1] == "do" else {"spaces": self.spaces})
            return type("R", (), {"returncode": 0, "stdout": out, "stderr": ""})()
        pm.hc, pm.subprocess.run = hc, run
        pm.end_retired_later = lambda term, successor="", place=False, kind="", started=False: self.calls.append(
            ("end-retired", term, successor, place, started))

    def tearDown(self):
        pm.hc, pm.subprocess.run, pm.end_retired_later, pm.PANE, pm.HC_TERMINAL = self.saved
        for path in [*pm.PMS.glob("*.json"), *pm.TASKS.glob(f"{self.name}-*.json"), *pm.waits_dir().glob("*.json")]:
            path.unlink()

    def out(self, fn, *args):
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            fn(*args)
        return text.getvalue()

    def task(self, slug, status, log=1, **fields):
        task = {"id": f"{self.name}-{slug}", "title": slug, "project": self.name, "repo": self.repo,
                "status": status, "owner": "pm", "base": "main", "created": pm.now(), **fields}
        task["log"] = [{"at": pm.now(), "by": "hc:t9", "text": f"{slug} entry {i} " + "long " * 100} for i in range(log)]
        pm.save(task)
        return task["id"]

    def register(self, **labels):
        pm.PMS.mkdir(parents=True, exist_ok=True)
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(
            {"name": pm.pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "hc:t7",
             "runtime": "hc", "terminal": "t7", "agent": "claude"}))
        wrapper = ["/bin/zsh", "-lic", '"$@"; exec "$0" -li', "/bin/zsh"]
        claude = ["claude", "--permission-mode", "bypassPermissions", "--", "[from pm.py start] 旧的提示"]
        self.terms["t7"] = {"state": "live", "argv": wrapper + claude, "foreground": {"argv": claude},
                            "labels": {"pm": self.name, **labels}, "status": {"state": "working"}}
        self.terms["t50"] = {"state": "live", "turn": 1, "status": {"state": "working"}}  # the new PM, at work
        return wrapper

    def test_handover_is_short_and_says_where_the_rest_is(self):
        self.register()
        d = pm.project_dir(self.repo)
        (d / "decisions.md").write_text("".join(f"- 2026-11-{i % 28 + 1:02d} 决定{i} " + "细" * 40
                                                + f" — 用户原话：「原话{i}」\n" for i in range(40)))
        (d / "handover.md").write_text("In flight: " + "a note " * 500)
        for i in range(4):
            self.task(f"open{i}", "in_progress", log=10, pane=f"hc:t{20 + i}", agent=f"w{i}", branch=f"dev/o{i}")
        for i in range(30):
            self.task(f"closed{i}", "merged", retired="2026-11-15")
        for i in range(20):
            pm.record(self.repo, "user", text=f"第{i}句 " + "said " * 100)
            pm.record(self.repo, "pm", text=f"回答{i}\n\n" + "a reply " * 100)
        args = argparse.Namespace(repo=self.repo, turns=6, full=False)
        text = self.out(pm.cmd_handover, args)
        notes = (d / "handover.md").read_text().strip()
        self.assertIn(notes, text)                                # the notes whole: what is in flight is not cut
        self.assertLessEqual(len(text.encode()) - len(notes.encode()), 8192)
        decisions = text.split("## Decisions")[1].split("\n## ")[0]
        self.assertIn("the latest 15 of 40; `pm.py decisions`", decisions)
        self.assertEqual([line[:5] for line in decisions.splitlines()[1:] if line].count("- 202"), 15)
        self.assertIn("决定39", decisions)
        self.assertNotIn("决定24 ", decisions)
        self.assertNotIn("原话", decisions)                     # the user's words: `pm.py decisions`
        self.assertIn("open3 entry 9", text)
        self.assertIn("open3 entry 8", text)
        self.assertNotIn("open3 entry 7", text)                   # two entries per open task
        self.assertIn("Closed in the last 48 h: 30 (", text)
        self.assertNotIn(f"{self.name}-closed1", text)            # a count, not a list
        self.assertEqual(text.count("\n用户: ") + text.count("\nUser: "), 6)
        self.assertNotIn("第13句", text)
        full = self.out(pm.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=True))
        self.assertIn("— 用户原话：「原话0」", full)
        self.assertIn(f"- [merged] {self.name}-closed1: closed1", full)
        self.assertIn("open3 entry 7", full)
        every = self.out(pm.cmd_decisions, argparse.Namespace(repo=self.repo, last=0))
        self.assertEqual(len(every.splitlines()), 40)
        self.assertEqual(self.out(pm.cmd_decisions, argparse.Namespace(repo=self.repo, last=2)).count("— 用户原话"), 2)

    def test_handover_lists_the_waits_to_start_again(self):
        self.register()
        worker = self.task("worker", "in_progress", pane="hc:t20", agent="w1")
        self.task("own", "in_progress", pane="hc:t7")                          # the PM works on it itself
        self.task("nopane", "in_progress", agent="w2")
        reviewed = self.task("reviewed", "review", pane="hc:t21", agent="w3")  # findings sent, the wait was running
        self.task("ready", "review", pane="hc:t22", agent="w4")                # reported: the PM reviews, no wait
        merged = self.task("merged", "merged", pane="hc:t23", agent="w5")
        pm.waits_dir().mkdir(parents=True, exist_ok=True)
        for task_id in (reviewed, merged):  # left behind by waits that ended with the previous session
            (pm.waits_dir() / f"{task_id}.json").write_text(json.dumps({"task": task_id, "pid": 1}))
        text = self.out(pm.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=False))
        waits = text.split("## Waits to start again")[1]
        self.assertIn(f"pm.py is `{pm.pm_command()}`", waits)
        self.assertEqual(sorted(line for line in waits.splitlines() if line.startswith("pm.py wait")),
                         [f"pm.py wait {reviewed} --timeout 3600", f"pm.py wait {worker} --timeout 3600"])
        self.assertIn("## Waits to start again", self.out(pm.cmd_handover, argparse.Namespace(
            repo=self.repo, turns=6, full=True)))

    def test_a_wait_says_so_while_it_runs_and_not_after(self):
        task_id = self.task("w", "in_progress", pane="hc:t20", agent="w1")
        seen = []
        real = pm.wait_for_report

        def look(a):
            seen.append(json.loads((pm.waits_dir() / f"{task_id}.json").read_text()))
            sys.exit(2)
        pm.wait_for_report = look
        try:
            with self.assertRaises(SystemExit):
                pm.cmd_wait(argparse.Namespace(id=task_id, timeout=1))
        finally:
            pm.wait_for_report = real
        self.assertEqual((seen[0]["task"], seen[0]["pid"]), (task_id, os.getpid()))
        self.assertFalse((pm.waits_dir() / f"{task_id}.json").exists())

    def test_what_the_user_said_after_the_last_reply_is_handed_over_whole(self):
        self.register()
        pm.record(self.repo, "user", text="先做看板")
        pm.record(self.repo, "pm", text="好")
        self.assertEqual(pm.unanswered(pm.conversation(self.repo)), [])
        pm.record(self.repo, "user", text="再把连线改成曲线" + "。" * 500)
        pm.record(self.repo, "thread", task="x", text="ledger entry")
        pm.record(self.repo, "user", text="还有颜色")
        self.assertEqual([e["text"][:4] for e in pm.unanswered(pm.conversation(self.repo))], ["再把连线", "还有颜色"])
        text = self.out(pm.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=False))
        self.assertIn("## Not answered yet", text)
        self.assertIn("再把连线改成曲线" + "。" * 500, text)
        self.assertIn("还有颜色", text.split("## Not answered yet")[1])

    def hook(self, event, **payload):
        pm.sys.stdin = io.StringIO(json.dumps({"hook_event_name": event, **payload}))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                pm.cmd_hook_turn(None)
        finally:
            pm.sys.stdin = sys.__stdin__

    def test_the_takeover_turn_says_nothing_to_the_user(self):
        self.register()
        rec = json.loads((pm.PMS / f"{pm.project_slug(self.repo)}.json").read_text())
        rec.update(pane="hc:t50", terminal="t50")
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(rec))
        pm.PANE, pm.HC_TERMINAL = "hc:t50", "t50"
        pm.record(self.repo, "user", text="看下状态")
        pm.record(self.repo, "pm", text="都在跑")
        mark = pm.takeover_mark(self.repo)
        mark.write_text(json.dumps({"terminal": "t50", "at": pm.now()}))
        self.hook("UserPromptSubmit", prompt="[from pm.py rotate] 你是 PM，接手")
        self.hook("Stop", last_assistant_message="已接手，三个线程在跑。")
        self.assertEqual([e["text"] for e in pm.conversation(self.repo)], ["看下状态", "都在跑"])
        self.assertTrue(json.loads(mark.read_text()).get("ended"))
        self.assertNotIn(("hc", "label", "t50", "pm.quiet="), self.calls)  # pm-toast keeps quiet about that turn
        self.hook("UserPromptSubmit", prompt="<task-notification>wait done</task-notification>")
        self.assertFalse(mark.exists())
        self.assertIn(("hc", "label", "t50", "pm.quiet="), self.calls)
        self.hook("Stop", last_assistant_message="看板做好了")
        self.assertEqual(pm.conversation(self.repo)[-1]["text"], "看板做好了")

    def test_a_takeover_answers_what_the_user_asked_meanwhile(self):
        self.register()
        pm.PANE, pm.HC_TERMINAL = "hc:t50", "t50"
        rec = json.loads((pm.PMS / f"{pm.project_slug(self.repo)}.json").read_text())
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps({**rec, "pane": "hc:t50",
                                                                                "terminal": "t50"}))
        pm.record(self.repo, "user", text="连线为什么是直角")
        pm.takeover_mark(self.repo).write_text(json.dumps({"terminal": "t50", "at": pm.now()}))
        self.hook("Stop", last_assistant_message="直角是旧版的画法，已经派人改。")
        self.assertEqual(pm.conversation(self.repo)[-1]["text"], "直角是旧版的画法，已经派人改。")
        self.assertFalse(pm.takeover_mark(self.repo).exists())
        self.assertIn(("hc", "label", "t50", "pm.quiet="), self.calls)
        # A mark of another terminal, or a stale one, silences nothing.
        pm.takeover_mark(self.repo).write_text(json.dumps({"terminal": "t51", "at": pm.now()}))
        self.hook("Stop", last_assistant_message="第二句")
        pm.takeover_mark(self.repo).write_text(json.dumps({"terminal": "t50", "at": "2020-01-01 00:00"}))
        self.hook("Stop", last_assistant_message="第三句")
        self.assertEqual([e["text"] for e in pm.conversation(self.repo)][-2:], ["第二句", "第三句"])

    def takeover(self):
        self.register()
        pm.PANE, pm.HC_TERMINAL = "hc:t50", "t50"
        rec = json.loads((pm.PMS / f"{pm.project_slug(self.repo)}.json").read_text())
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps({**rec, "pane": "hc:t50",
                                                                                "terminal": "t50"}))
        pm.takeover_mark(self.repo).write_text(json.dumps({"terminal": "t50", "at": pm.now()}))
        return Path(self.repo) / "t.jsonl"

    def test_only_the_takeover_prompt_alone_makes_a_quiet_turn(self):
        transcript = self.takeover()
        human = lambda text, **kw: json.dumps({"type": "user", "message": {"content": text},
                                               "origin": {"kind": "human"}, **kw})
        rows = [human("[from pm.py rotate] 接手"),
                human("[Your previous response had no visible output.]", isMeta=True),
                json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})]
        transcript.write_text("\n".join(rows) + "\n")
        self.assertFalse(pm.came_in(str(transcript)))
        # Anything else that came in during that turn is news: the user's words, typed in on their own or taken
        # into the turn while it worked (a queued command), a finished background wait, a worker's message.
        for extra in (human("先别合并"),
                      json.dumps({"type": "attachment", "attachment": {"type": "queued_command", "prompt": "先别合并",
                                                                       "origin": {"kind": "human"}}}),
                      json.dumps({"type": "user", "message": {"content": "<task-notification>x</task-notification>"},
                                  "origin": {"kind": "task-notification"}}),
                      json.dumps({"type": "attachment", "attachment": {
                          "type": "queued_command", "prompt": '<hc from="t9">[from hc:t9] 做完了</hc>'}})):
            transcript.write_text("\n".join(rows + [extra]) + "\n")
            self.assertTrue(pm.came_in(str(transcript)), extra)
        # No hook saw it (a background wait that came back mid-turn): the reply is still recorded.
        self.hook("Stop", last_assistant_message="demo-readme 做完了，等你看。", transcript_path=str(transcript))
        self.assertEqual(pm.conversation(self.repo)[-1]["text"], "demo-readme 做完了，等你看。")
        self.assertFalse(pm.takeover_mark(self.repo).exists())
        self.assertIn(("hc", "label", "t50", "pm.quiet="), self.calls)

    def test_a_worker_message_during_the_takeover_turn_gets_its_reply_recorded(self):
        transcript = self.takeover()
        transcript.write_text(json.dumps({"type": "user", "message": {"content": "[from pm.py rotate] 接手"}}) + "\n")
        self.hook("UserPromptSubmit", prompt='<hc from="t9">[from hc:t9] demo-readme 做完了</hc>')
        self.assertIn(("hc", "label", "t50", "pm.quiet="), self.calls)   # its notice shows, and so does the reply
        self.assertTrue(json.loads(pm.takeover_mark(self.repo).read_text())["busy"])
        self.hook("Stop", last_assistant_message="demo-readme 做完了，我看一下。", transcript_path=str(transcript))
        self.assertEqual(pm.conversation(self.repo)[-1]["text"], "demo-readme 做完了，我看一下。")
        self.assertFalse(pm.takeover_mark(self.repo).exists())

    def test_words_typed_in_during_the_takeover_turn_get_their_answer(self):
        transcript = self.takeover()
        transcript.write_text(json.dumps({"type": "user", "message": {"content": "[from pm.py rotate] 接手"}}) + "\n")
        self.hook("UserPromptSubmit", prompt="先别合并")                  # typed while the takeover still runs
        self.assertIn(("hc", "label", "t50", "pm.quiet="), self.calls)    # its answer's notice shows
        self.assertTrue(pm.takeover_mark(self.repo).exists())
        self.hook("Stop", last_assistant_message="好，先不合并。", transcript_path=str(transcript))
        self.assertEqual(pm.conversation(self.repo)[-1]["text"], "好，先不合并。")
        self.assertFalse(pm.takeover_mark(self.repo).exists())

    def test_the_context_reminder_hands_over_only_what_the_user_said(self):
        self.register()
        pm.PANE = "hc:t7"
        transcript = Path(self.repo) / "big.jsonl"
        transcript.write_text(row("assistant", [{"type": "text", "text": "x"}], {"input_tokens": 999999}) + "\n")
        said = {}
        for prompt in ("README 写了吗", "[from hc:t3] task x is ready", "<task-notification>x</task-notification>"):
            pm.sys.stdin = io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                                                   "transcript_path": str(transcript)}))
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    pm.cmd_hook_turn(None)
            finally:
                pm.sys.stdin = sys.__stdin__
            said[prompt] = out.getvalue()
        self.assertIn("Do not answer this prompt: your successor answers", said["README 写了吗"])
        for prompt in ("[from hc:t3] task x is ready", "<task-notification>x</task-notification>"):
            self.assertIn("not handed over: deal with it first", said[prompt])
            self.assertNotIn("Do not answer", said[prompt])
        for text in said.values():
            self.assertIn("end the turn without a word", text)
        tui = pm.rotate_reminder(300000, True, False)       # the herdr TUI: the new PM opens a tab of its own
        self.assertIn("tell the user to continue there", tui)
        self.assertNotIn("without a word", tui)

    def test_rotate_starts_the_successor_in_the_same_tab_and_ends_the_old_one(self):
        wrapper = self.register(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        self.spaces = [{"id": "sp1", "tabs": [{"id": "tb1", "name": f"PM-{self.name}", "terminals": [
            {"terminal": "t7", "pane": "p7"}, {"terminal": "t50", "pane": "p50"}]}]}]
        pm.PANE, pm.HC_TERMINAL = "hc:t7", "t7"
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "old", "PM_HOME": HOME}):
            text = self.out(pm.cmd_rotate, argparse.Namespace(repo=self.repo, notes="等 worker 汇报", model=None,
                                                              transcript="/nonexistent"))
        # Started from the old session: not with that session's own variables.
        self.assertEqual((self.envs[0].get("CLAUDECODE"), self.envs[0].get("CLAUDE_CODE_SESSION_ID"),
                          self.envs[0].get("PM_HOME")), (None, None, HOME))
        run = next(c for c in self.calls if c[:2] == ("hc", "run"))
        cut = run.index("--")
        self.assertIn("--no-parent", run[:cut])
        for label in ("herdr.space=sp1", "herdr.tab=tb1", f"pm={self.name}", "pm.quiet=1"):
            self.assertIn(label, run[:cut])
        self.assertEqual(list(run[cut + 1:cut + 6]), wrapper + ["claude"])   # in the same login shell
        prompt = run[-1]
        self.assertTrue(prompt.startswith("[from pm.py rotate] "))
        self.assertIn("handover", prompt)
        self.assertIn("in the background", prompt)
        self.assertNotIn("three or four sentences", prompt)
        self.assertFalse([c for c in self.calls if c[:2] == ("herdr-app", "do")])  # end-retired moves the panes
        self.assertIn(("hc", "label", "t7", "pm=", f"pm.retired={self.name}"), self.calls)
        # Last: the old session may be this one. It leaves the tab once t50 works.
        self.assertEqual(self.calls[-1], ("end-retired", "t7", "t50", True, True))
        rec = pm.pm_record(self.repo)
        self.assertEqual((rec["terminal"], rec["previous"]["terminal"], rec["rotations"]), ("t50", "t7", 1))
        self.assertEqual(json.loads(pm.takeover_mark(self.repo).read_text())["terminal"], "t50")
        self.assertIn("等 worker 汇报", (pm.project_dir(self.repo) / "handover.md").read_text())
        self.assertIn("same tab", text)
        self.assertIn("End this turn now, without a word to the user", text)

    def test_no_quiet_label_while_the_user_waits_for_an_answer(self):
        self.register(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        pm.record(self.repo, "user", text="连线为什么是直角")
        self.out(pm.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        run = next(c for c in self.calls if c[:2] == ("hc", "run"))
        self.assertIn("herdr.tab=tb1", run)
        self.assertNotIn("pm.quiet=1", run)          # the first turn answers it: its notice and dots show
        self.assertIn(("hc", "label", "t50", f"pm={self.name}"), self.calls)

    def test_a_codex_pm_rotates_in_place_without_the_quiet_label(self):
        wrapper = self.register(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        rec = json.loads((pm.PMS / f"{pm.project_slug(self.repo)}.json").read_text())
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps({**rec, "agent": "codex"}))
        self.terms["t7"]["argv"] = wrapper + ["codex", "-c", "check_for_update_on_startup=false"]
        self.terms["t7"]["foreground"] = {"argv": ["codex", "-c", "check_for_update_on_startup=false"]}
        self.out(pm.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        run = next(c for c in self.calls if c[:2] == ("hc", "run"))
        cut = run.index("--")
        self.assertIn("herdr.tab=tb1", run[:cut])
        self.assertNotIn("pm.quiet=1", " ".join(run))   # its hooks are not known to take the label away again
        self.assertEqual(list(run[cut + 1:cut + 6]), wrapper + ["codex"])
        self.assertTrue(run[-1].startswith("[from pm.py rotate] "))
        self.assertIn(("hc", "label", "t50", f"pm={self.name}"), self.calls)
        self.assertEqual(self.calls[-1], ("end-retired", "t7", "t50", True, True))

    def test_a_new_pm_that_does_not_start_is_reported_and_the_old_one_stays(self):
        self.register(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        self.terms["t50"] = {"state": "live", "turn": 0, "status": None}   # at a startup dialog: no status
        pm.PANE, pm.HC_TERMINAL = "hc:t7", "t7"
        pm.record(self.repo, "user", text="连线为什么是直角")                 # the prompt the rotation came with
        with mock.patch.object(pm, "START_WAIT", 0), mock.patch.object(pm, "screen_line", lambda t: "Trust this folder?"):
            text = self.out(pm.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        self.assertIn("has not started work", text)
        self.assertNotIn("without a word", text)
        told = pm.conversation(self.repo)[-1]
        self.assertEqual((told["type"], told["by"]), ("pm", "hc:t7"))   # the user reads it in the project view
        self.assertIn("Trust this folder?", told["text"])
        self.assertIn(f"PM-{self.name}", told["text"])
        self.assertFalse([c for c in self.calls if c[:2] == ("herdr-app", "do")])  # nothing parked
        self.assertEqual(self.calls[-1], ("end-retired", "t7", "t50", True, False))  # it waits for t50 to work
        # The notice answers nothing: what the user said is still handed over, and the takeover answers it.
        self.assertEqual([e["text"] for e in pm.unanswered(pm.conversation(self.repo))], ["连线为什么是直角"])
        self.assertEqual(pm.log_tail(self.repo)[-1], {"user": "连线为什么是直角", "pm": ""})
        handover = self.out(pm.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=False))
        self.assertIn("连线为什么是直角", handover.split("## Not answered yet")[1])

    def test_a_new_pm_that_never_starts_hands_the_project_back_or_says_how(self):
        self.register()
        rec = json.loads((pm.PMS / f"{pm.project_slug(self.repo)}.json").read_text())
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps({**rec, "pane": "hc:t50",
                                                                                "terminal": "t50"}))
        pm.takeover_mark(self.repo).write_text(json.dumps({"terminal": "t50", "at": pm.now()}))
        self.terms["t50"] = {"state": "live", "turn": 0, "status": None}   # still at its dialog
        pm.never_started("t7", "t50")
        self.assertEqual(pm.pm_record(self.repo)["terminal"], "t50")
        told = pm.conversation(self.repo)[-1]
        self.assertTrue(told["notice"])
        self.assertIn("hc kill t50", told["text"])
        self.assertIn("pm.py claim --pane hc:t7", told["text"])
        self.terms["t50"] = {"state": "finished"}                          # it exited: back to the old session
        pm.never_started("t7", "t50")
        rec = pm.pm_record(self.repo)
        self.assertEqual((rec["terminal"], rec["pane"]), ("t7", "hc:t7"))
        self.assertIn(("hc", "label", "t7", f"pm={self.name}", "pm.retired="), self.calls)
        self.assertTrue(any(c[:3] == ("hc", "send", "t7") and "PM of" in c[3] for c in self.calls))
        self.assertFalse(pm.takeover_mark(self.repo).exists())
        self.assertIn("carries on", pm.conversation(self.repo)[-1]["text"])
        self.calls.clear()
        pm.never_started("t7", "t99")                                      # not the registered PM: nothing
        self.assertFalse(self.calls)

    def test_rotate_outside_a_tab_starts_a_terminal_as_before(self):
        self.register()  # no herdr.space/herdr.tab: a bare terminal
        pm.PANE = "hc:t9"
        text = self.out(pm.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        run = next(c for c in self.calls if c[:2] == ("hc", "run"))
        self.assertNotIn("herdr.tab", " ".join(run))
        self.assertEqual(run[run.index("--") + 1], "claude")
        self.assertIn(("hc", "label", "t50", f"pm={self.name}", "pm.quiet=1"), self.calls)
        self.assertFalse([c for c in self.calls if c[:3] == ("herdr-app", "do", "terminal.park")])
        self.assertEqual(self.calls[-1], ("end-retired", "t7", "t50", False, True))
        self.assertIn("new tab", text)
        self.assertNotIn("End this turn", text)  # not run by the old PM

    def test_rotate_in_the_herdr_tui_still_announces_the_takeover(self):
        self.register()
        rec = json.loads((pm.PMS / f"{pm.project_slug(self.repo)}.json").read_text())
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps({**rec, "runtime": "", "pane": "w1:p1"}))
        got = []
        real, pm.rotate_herdr = pm.rotate_herdr, lambda a, repo, rec, previous, prompt, is_self: got.append(prompt)
        try:
            self.out(pm.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        finally:
            pm.rotate_herdr = real
        self.assertIn("three or four sentences", got[0])
        self.assertFalse(pm.takeover_mark(self.repo).exists())

    def test_end_retired_waits_for_the_turn_to_end_then_ends_the_program(self):
        looks = iter([{"state": "live", "status": {"state": "working"}}, {"state": "live", "status": {"state": "done"}},
                      {"state": "live", "status": {"state": "working"}}, {"state": "live", "status": {"state": "idle"}},
                      {"state": "live", "status": {"state": "idle"}}])
        sleep, pm.time.sleep = pm.time.sleep, lambda _: None
        try:
            pm.hc = lambda *args, **kw: (self.calls.append(args), next(looks) if args[0] == "get" else {})[1]
            pm.cmd_end_retired(argparse.Namespace(terminal="t7", successor="", kind="", place=False, started=False,
                                                  timeout=60))
            self.assertEqual([c for c in self.calls if c[0] == "kill"], [("kill", "t7")])
            self.assertEqual(len([c for c in self.calls if c[0] == "get"]), 5)
            for info in ({"state": "finished"}, {"state": "live", "labels": {"pm": "x"}}, None):
                self.calls.clear()
                pm.hc = lambda *args, **kw: (self.calls.append(args), info if args[0] == "get" else {})[1]
                pm.cmd_end_retired(argparse.Namespace(terminal="t7", successor="", kind="", place=False, started=False,
                                                      timeout=60))
                self.assertFalse([c for c in self.calls if c[0] == "kill"], info)
        finally:
            pm.time.sleep = sleep

    def test_end_retired_waits_for_background_work_and_never_cuts_it_off(self):
        self.register()
        rec = json.loads((pm.PMS / f"{pm.project_slug(self.repo)}.json").read_text())
        (pm.PMS / f"{pm.project_slug(self.repo)}.json").write_text(json.dumps(
            {**rec, "pane": "hc:t50", "terminal": "t50", "previous": {"pane": "hc:t7", "terminal": "t7"}}))
        idle = {"state": "live", "pid": 100, "status": {"state": "idle"}}
        work = iter([["until pm.py land demo-x; do sleep 60; done"]] * 3 + [[], []])
        sleep, pm.time.sleep = pm.time.sleep, lambda _: None
        hc = pm.hc
        try:
            pm.hc = lambda *args, **kw: (self.calls.append(("hc",) + args), idle if args[0] == "get" else {})[1]
            with mock.patch.object(pm, "background_work", lambda info: next(work)):
                pm.cmd_end_retired(argparse.Namespace(terminal="t7", successor="", kind="", place=False,
                                                      started=False, timeout=60))
            self.assertEqual(self.calls[-1], ("hc", "kill", "t7"))   # only once the land was over, two looks in a row
            self.assertEqual(len([c for c in self.calls if c[1] == "get"]), 5)
            # Still busy at the end of the wait: left running, and the PM in charge is told.
            self.calls.clear()
            with mock.patch.object(pm, "background_work", lambda info: ["until pm.py land demo-x; do sleep 60; done"]), \
                    mock.patch.object(pm.time, "time", side_effect=[0, 0, 0, 100, 100]):
                pm.cmd_end_retired(argparse.Namespace(terminal="t7", successor="", kind="", place=False,
                                                      started=False, timeout=60))
            self.assertFalse([c for c in self.calls if c[1] == "kill"])
            sent = [c for c in self.calls if c[:3] == ("hc", "send", "t50")]
            self.assertEqual(len(sent), 1)
            self.assertIn("pm.py land demo-x", sent[0][3])
            self.assertIn("hc kill t7", sent[0][3])
        finally:
            pm.time.sleep, pm.hc = sleep, hc

    def test_background_work_is_read_from_the_shells_under_the_terminal(self):
        snap = "/bin/zsh -c source /Users/me/.claude/shell-snapshots/snapshot-zsh-1.sh 2>/dev/null || true && eval "
        ps = "\n".join([
            "  100     1 /bin/zsh -lic claude",
            "  101   100 claude --model opus",
            f"  102   101 {snap}'python3 /x/pm.py wait demo-a --timeout 3600' < /dev/null && pwd -P >| /tmp/cwd",
            "  103   102 python3 /x/pm.py wait demo-a --timeout 3600",
            f"  104   101 {snap}'until python3 /x/pm.py land demo-b; do sleep 60; done' < /dev/null && pwd -P >| /tmp/cwd",
            "  105   104 python3 /x/pm.py land demo-b",
            "  106   101 node mcp-server.js",
            f"  200     1 {snap}'git merge other' < /dev/null && pwd -P >| /tmp/cwd"])  # another session's
        run = lambda argv, **kw: type("R", (), {"returncode": 0, "stdout": ps, "stderr": ""})()
        with mock.patch.object(pm.subprocess, "run", run):
            self.assertEqual(pm.background_work({"pid": 100}), ["until python3 /x/pm.py land demo-b; do sleep 60; done"])
            self.assertEqual(pm.background_work({}), [])

    def test_end_retired_moves_the_panes_only_once_the_new_pm_works(self):
        self.spaces = [{"id": "sp1", "tabs": [{"id": "tb1", "terminals": [{"terminal": "t7", "pane": "p7"},
                                                                          {"terminal": "t50", "pane": "p50"}]}]}]
        new = iter([{"state": "live", "turn": 0, "status": None}, {"state": "live", "turn": 1,
                                                                    "status": {"state": "working"}}])
        old = {"state": "live", "status": {"state": "idle"}}
        sleep, pm.time.sleep = pm.time.sleep, lambda _: None
        hc = pm.hc
        try:
            pm.hc = lambda *args, **kw: (self.calls.append(("hc",) + args), (next(new) if args[1] == "t50" else old)
                                         if args[0] == "get" else {})[1]
            pm.cmd_end_retired(argparse.Namespace(terminal="t7", successor="t50", kind="claude", place=True,
                                                  started=False, timeout=60))
            do = [(c[2], json.loads(c[3])) for c in self.calls if c[:2] == ("herdr-app", "do")]
            self.assertEqual(do, [("pane.swap", {"pane": "p50", "target": "p7"}),
                                  ("terminal.park", {"terminal": "t7"})])
            self.assertEqual(self.calls[-1], ("hc", "kill", "t7"))
            # A new PM that never works (it exited, or waits at a dialog past the wait): both stay as they are.
            self.calls.clear()
            for gone in ({"state": "exited"}, {"state": "live", "turn": 0, "status": None}):
                pm.hc = lambda *args, **kw: (self.calls.append(("hc",) + args), gone if args[0] == "get" else {})[1]
                with mock.patch.object(pm, "STARTED_WAIT", 0), mock.patch.object(pm, "never_started") as said:
                    pm.cmd_end_retired(argparse.Namespace(terminal="t7", successor="t50", kind="claude", place=True,
                                                          started=False, timeout=60))
                said.assert_called_once_with("t7", "t50")
            self.assertFalse([c for c in self.calls if c[:2] in (("hc", "kill"), ("herdr-app", "do"))])
            # rotate saw a codex PM start (a program that may report no state): no second wait here.
            self.calls.clear()
            pm.hc = lambda *args, **kw: (self.calls.append(("hc",) + args), old if args[1] == "t7" else {}
                                         if args[0] == "get" else {})[1]
            pm.cmd_end_retired(argparse.Namespace(terminal="t7", successor="t50", kind="codex", place=False,
                                                  started=True, timeout=60))
            self.assertEqual([c for c in self.calls if c[1] == "get"], [("hc", "get", "t7")] * 2)
            self.assertEqual(self.calls[-1], ("hc", "kill", "t7"))
        finally:
            pm.time.sleep, pm.hc = sleep, hc

    def test_the_old_program_is_ended_from_a_process_of_its_own(self):
        with mock.patch.object(pm.subprocess, "Popen") as popen:
            self.saved[2]("t7", "t50", True, "claude", True)
        argv, kw = popen.call_args
        self.assertEqual(argv[0][1:], [str(Path(pm.__file__).resolve()), "end-retired", "t7", "--successor", "t50",
                                       "--kind", "claude", "--place", "--started"])
        self.assertTrue(kw["start_new_session"])  # it outlives the session that ran rotate

    def test_shell_prefix_is_what_runs_the_agent(self):
        wrapper = ["/bin/zsh", "-lic", '"$@"; exec "$0" -li', "/bin/zsh"]
        self.assertEqual(pm.shell_prefix({"argv": wrapper + ["claude", "-c"]}, "claude"), wrapper)
        self.assertEqual(pm.shell_prefix({"argv": ["/usr/local/bin/claude", "-c"]}, "claude"), [])
        self.assertEqual(pm.shell_prefix({"argv": wrapper + ["codex", "-c", "x"]}, "codex"), wrapper)
        self.assertEqual(pm.shell_prefix({}, "claude"), [])


if __name__ == "__main__":
    unittest.main()
