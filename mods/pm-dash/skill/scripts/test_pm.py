"""Targeted tests for the rotation and dispatch helpers. Run: python3 -m unittest skill/pm/scripts/test_pm.py"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOME = tempfile.mkdtemp()
os.environ["PM_HOME"] = HOME
os.environ.pop("HERDR_PANE_ID", None)
os.environ.pop("HC_TERMINAL_ID", None)
import sys
sys.path.insert(0, str(Path(__file__).parent))
import pm  # noqa: E402


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
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pm.cmd_handover(type("A", (), {"repo": repo, "turns": 6}))
        text = out.getvalue()
        for part in ("连线不用直角", 'the user\'s words: "不要有直角线"', "用户正要验证点击跳转", f"{name}-a", "dispatched"):
            self.assertIn(part, text)

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

    def test_worker_command(self):
        a = type("A", (), {"kind": "codex", "model": "m", "effort": "high"})
        self.assertEqual(pm.worker_argv(a), ["codex", "-c", "check_for_update_on_startup=false", "-m", "m", "-c", 'model_reasoning_effort="high"'])
        a.kind = "claude"
        self.assertEqual(pm.worker_argv(a), ["claude", "--model", "m"])  # no effort flag for this program
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

    def test_state_names_each_pms_conversation_log(self):
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


if __name__ == "__main__":
    unittest.main()
