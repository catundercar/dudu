"""Targeted tests for the rotation and dispatch helpers. Run: python3 -m unittest skill/pm/scripts/test_pm.py"""
import contextlib
import io
import json
import os
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
                         ["claude", "--mcp-config", "/x/mcp.json", "--chrome", "--model", "new", "接手"])
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
        try:
            for who, prompt in (("hc:t9", "hello"), ("hc:t9", "[from hc:t3] done"), ("hc:t8", "hello")):
                pm.PANE = who
                pm.sys.stdin = io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}))
                pm.cmd_hook_mirror(None)  # the earlier name still works
        finally:
            pm.PANE, pm.sys.stdin = pane, stdin
            (pm.PMS / "t.json").unlink()
        lines = pm.TURN_LOG.read_text().splitlines()
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


if __name__ == "__main__":
    unittest.main()
