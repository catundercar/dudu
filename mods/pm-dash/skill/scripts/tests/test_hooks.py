"""The agent hooks pm.py installs, and the herdr TUI paths they and the commands take (Stage 6a, wave 6a3).

Moved from test_pm.py's TakenIn (the turn hook records words a turn took in while it worked), TerminalUI (a PM in
the herdr terminal UI: reviewers in tabs, rotate, hooks that must not take another project's session for the PM)
and PmQuestionCardsAndStaleBlockedTest (the PreToolUse hook turning AskUserQuestion into a question card, and how
`send` / `update --send` unblock a worker's blocked task). Every test builds its own Context with make_ctx: FakeHc,
a FakeTui (or a subclass of it here), FakeProcs recording the background pm.py it would start, its own ledger home;
hooks and commands run on that Context through legacy_ctx.bound / run_main, so no module global of pm survives a
test. TakenIn's standalone failure (a CLAUDE_CODE_SESSION_ID in the environment of whoever ran the tests made the turn
hook write the registration lock) cannot happen here: the Context's environment is the test's own.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import io
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

from fakes import FakeHc, FakeTui, make_ctx  # noqa: E402
from fakes import run_main  # noqa: E402
from pmlib import cli, hooks  # noqa: E402
from pmlib.caller import Caller  # noqa: E402
from pmlib.context import StdOutput, SystemClock  # noqa: E402
from pmlib.discord import replied_on_discord  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.question import QUESTION_FIELDS  # noqa: E402
from pmlib.manager.handover import conversation_tail, handover_talk, unanswered  # noqa: E402
from pmlib.manager.rotate import retire_name  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import ProjectRegistry, pm_name  # noqa: E402
from pmlib.project.readmodel import answered_tasks  # noqa: E402
from pmlib.terminals.tui import TuiHost  # noqa: E402
from pmlib.workers.lifecycle import end_worker_for  # noqa: E402


def command(ctx, *argv):
    """Run `pm.py <argv>`'s command function on ctx, as test_pm.py called pm.cmd_<x>(parsed args) directly: its
    return value, SystemExit propagates. Its stdout is dropped."""
    a = cli.build_parser().parse_args(list(argv))
    mod, fn_name = cli.COMMANDS[a.cmd]
    with contextlib.redirect_stdout(io.StringIO()):
        return getattr(mod, fn_name)(a, ctx=ctx)


class TakenIn(unittest.TestCase):
    """Words that came in while a turn worked: Claude Code takes them into the turn as queued_command rows of its
    transcript, which no hook sees. The turn hook records them when the turn ends, before the reply, once each."""

    BASE = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0) - datetime.timedelta(hours=2)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="pm-hooks-taken-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.git = GitRepo(worktree_base=self.base / "worktrees")
        self.repo = self.git.project_root(tempfile.mkdtemp(dir=self.base))
        self.dir = Path(tempfile.mkdtemp(dir=self.base))
        self.pane = "hc:t7"
        self.hc_terminal = ""
        self.hc = FakeHc()
        self.tail = mock.patch.multiple(hooks, TAKEN_IN_TAIL=hooks.TAKEN_IN_TAIL, TAKEN_IN_MORE=hooks.TAKEN_IN_MORE)
        self.tail.start()
        self.addCleanup(self.tail.stop)
        self.ctx = self.make()
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.reg = self.ctx.home.registration(project_slug(self.repo))
        self.reg.write_text(json.dumps({"name": pm_name(self.repo), "pane": "hc:t7",
                                        "project": Path(self.repo).name, "repo": self.repo}))
        self.n = 0

    def make(self, pane=None):
        """A Context for one hook process: terminal self.pane (no herdr-core terminal id unless self.hc_terminal),
        the real clock (the rows are timed from now), the test's ledger home."""
        ctx = make_ctx(self.base, pane=pane or self.pane, hc=self.hc, git=self.git, clock=SystemClock(),
                       out=StdOutput())
        ctx.hc_terminal = self.hc_terminal
        ctx.caller = Caller(ctx)
        return ctx

    def at(self, minute):
        return (self.BASE + datetime.timedelta(minutes=minute)).isoformat().replace("+00:00", ".123Z")

    def local(self, minute):
        return (self.BASE + datetime.timedelta(minutes=minute)).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    def prompt(self, minute, text):
        self.n += 1
        return {"type": "user", "uuid": f"u{self.n}", "timestamp": self.at(minute), "isSidechain": False,
                "message": {"role": "user", "content": text}}

    def reply(self, minute, text="…"):
        self.n += 1
        return {"type": "assistant", "uuid": f"a{self.n}", "timestamp": self.at(minute), "isSidechain": False,
                "message": {"content": [{"type": "text", "text": text}]}}

    def queued(self, minute, prompt, uuid=None, kind="human", mode="prompt", **extra):
        self.n += 1
        attachment = {"type": "queued_command", "prompt": prompt, "commandMode": mode, "origin": {"kind": kind},
                      "source_uuid": f"s{self.n}", "timestamp": self.at(minute), **extra}
        return {"type": "attachment", "uuid": uuid or f"q{self.n}", "parentUuid": None, "timestamp": self.at(minute),
                "sessionId": "x", "isSidechain": False, "attachment": attachment}

    def write(self, rows, name="session.jsonl", append=False):
        path = self.dir / name
        with open(path, "a" if append else "w") as f:
            f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        return str(path)

    def hook_raw(self, stdin, pane=None):
        """The turn hook, in a process of its own (a fresh Context), with stdin as Claude Code gives it."""
        out = io.StringIO()
        with mock.patch.object(sys, 'stdin', io.StringIO(stdin)), contextlib.redirect_stdout(out):
            hooks.cmd_hook_turn(None, ctx=self.make(pane))
        return out.getvalue()

    def hook(self, event, pane=None, **payload):
        return self.hook_raw(json.dumps({"hook_event_name": event, **payload}), pane=pane)

    def conversation(self, repo=None):
        return Conversation(self.ctx, repo or self.repo).events()

    def record(self, kind, at=None, **fields):
        return Conversation(self.ctx, self.repo).record(kind, at=at, **fields)

    def said(self):
        return [(e["type"], e.get("text")) for e in self.conversation() if e.get("type") in ("user", "agent", "pm")]

    def project_dir(self):
        return self.ctx.home.project_for(self.repo).ensure()

    def test_what_came_in_mid_turn_stands_before_the_reply_as_the_prompt_rule_says(self):
        path = self.write([self.prompt(0, "先做看板")])
        self.hook("UserPromptSubmit", prompt="先做看板", transcript_path=path)
        self.write([self.reply(1),
                    self.queued(2, "先别合并"),
                    self.queued(3, '<hc from="t9">[from hc:t9] 做完了</hc>', kind="peer", isMeta=True),
                    self.queued(4, "[from hc:t3] task x is ready", kind="peer"),
                    self.queued(5, "能帮我看下吗", kind="peer"),           # another agent's, naming no sender
                    self.queued(6, "[from pm.py rotate] 接手"),
                    self.queued(7, "<task-notification>done</task-notification>", kind="task-notification",
                                mode="task-notification"),
                    self.queued(8, "/compact"),
                    self.queued(9, "<system-reminder>x</system-reminder>"),
                    self.queued(10, "ls", mode="bash"),
                    self.reply(11, "好的")], append=True)
        self.hook("Stop", last_assistant_message="好的，先不合并。", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先做看板"), ("user", "先别合并"), ("agent", "做完了"),
                                       ("agent", "task x is ready"), ("agent", "能帮我看下吗"), ("pm", "好的，先不合并。")])
        events = self.conversation()
        self.assertEqual([e.get("by") for e in events[2:5]], ["hc:t9", "hc:t3", "peer"])
        # When the words were said, in this machine's time as every other `at`.
        self.assertEqual([e["at"] for e in events[1:5]], [self.local(2), self.local(3), self.local(4), self.local(5)])
        self.assertEqual(unanswered(events), [])  # the reply of the turn that took the words in answers them

    def test_each_row_is_recorded_once_however_often_the_turn_ends(self):
        path = self.write([self.prompt(0, "先做看板"), self.queued(1, "先别合并")])
        self.hook("Stop", last_assistant_message="一", transcript_path=path)
        self.hook("Stop", last_assistant_message="", transcript_path=path)       # a Stop hook made it go on
        self.write([self.reply(2), self.queued(3, "还有颜色")], append=True)
        self.hook("Stop", last_assistant_message="二", transcript_path=path)
        self.hook("UserPromptSubmit", prompt="下一个", transcript_path=path)
        self.hook("Stop", last_assistant_message="三", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先别合并"), ("pm", "一"), ("user", "还有颜色"), ("pm", "二"),
                                       ("user", "下一个"), ("pm", "三")])

    def test_rows_of_turns_before_this_was_installed_are_not_replayed(self):
        old = [self.prompt(0, "旧的"), self.queued(1, "旧的插话"), self.reply(2), self.queued(3, "更旧的插话")]
        # The first hook after the change is a prompt: it only notes where the transcript stands.
        path = self.write(old + [self.prompt(10, "新的")])
        self.hook("UserPromptSubmit", prompt="新的", transcript_path=path)
        self.write([self.queued(11, "新的插话")], append=True)
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "新的"), ("user", "新的插话"), ("pm", "好")])

    def test_without_a_mark_a_stop_takes_the_turn_ending_now_only(self):
        path = self.write([self.prompt(0, "旧的"), self.queued(1, "旧的插话"), self.reply(2),
                           self.prompt(10, "新的"), self.queued(11, "新的插话")])
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "新的插话"), ("pm", "好")])
        # A broken mark is no mark: still not the whole transcript again.
        mark = self.project_dir() / "taken-in.json"
        for broken in ("not json", "[]", '{"at": "yesterday", "keys": 3, "offset": "x"}'):
            mark.write_text(broken)
            self.hook("Stop", last_assistant_message="", transcript_path=path)
        self.assertEqual(self.said(), [("user", "新的插话"), ("pm", "好")])

    def test_a_resumed_compacted_or_rotated_session_replays_nothing(self):
        first = [self.prompt(0, "先做看板"), self.queued(1, "先别合并")]
        path = self.write(first)
        self.hook("Stop", last_assistant_message="一", transcript_path=path)
        # The same session in a file of its own (resumed, compacted): the old rows again, with their ids or new ones.
        copied = [dict(r) for r in first] + [{**first[1], "uuid": "another-id"}]
        later = self.write(copied + [self.prompt(5, "继续"), self.queued(6, "加个图例")], name="resumed.jsonl")
        self.hook("Stop", last_assistant_message="二", transcript_path=later)
        # A rotation: a new session, a new transcript; the old one is finished.
        new = self.write([self.prompt(10, "[from pm.py rotate] 接手")], name="new.jsonl")
        self.hook("UserPromptSubmit", prompt="[from pm.py rotate] 接手", transcript_path=new)
        self.write([self.queued(11, "现在谁在做？")], name="new.jsonl", append=True)
        self.hook("Stop", last_assistant_message="三", transcript_path=new)
        self.hook("Stop", last_assistant_message="", transcript_path=path)  # the old session ends late: nothing new
        self.assertEqual(self.said(), [("user", "先别合并"), ("pm", "一"), ("user", "加个图例"), ("pm", "二"),
                                       ("user", "现在谁在做？"), ("pm", "三")])

    def test_words_a_hook_recorded_already_are_not_recorded_again(self):
        # Should Claude Code fire UserPromptSubmit for such words, with the row already written: the hook's own.
        path = self.write([self.prompt(0, "先做看板")])
        self.hook("UserPromptSubmit", prompt="先做看板", transcript_path=path)
        self.write([self.queued(self.ago(0), "先别合并")], append=True)
        self.hook("UserPromptSubmit", prompt="先别合并", transcript_path=path)
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先做看板"), ("user", "先别合并"), ("pm", "好")])
        # Or the row written after the hook recorded them: the line in the log is theirs.
        self.hook("UserPromptSubmit", prompt="还有颜色", transcript_path=path)
        self.hook("UserPromptSubmit", prompt='<hc from="t9">[from hc:t9] 做完了</hc>', transcript_path=path)
        self.write([self.queued(self.ago(0), "还有颜色"),
                    self.queued(self.ago(1), '<hc from="t9">[from hc:t9] 做完了</hc>', kind="peer")], append=True)
        self.hook("Stop", last_assistant_message="好的", transcript_path=path)
        self.assertEqual(self.said()[3:], [("user", "还有颜色"), ("agent", "做完了"), ("pm", "好的")])
        # Another agent's words that name no sender: the hook took them for the user's; still the same words.
        self.hook("UserPromptSubmit", prompt="能帮我看下吗", transcript_path=path)
        self.write([self.queued(self.ago(0), "能帮我看下吗", kind="peer")], append=True)
        self.hook("Stop", last_assistant_message="看了", transcript_path=path)
        self.assertEqual(self.said()[6:], [("user", "能帮我看下吗"), ("pm", "看了")])

    def test_a_long_turn_is_read_on_from_the_mark(self):
        # A turn that wrote more than the tail since the mark: its early words are not lost.
        hooks.TAKEN_IN_TAIL, hooks.TAKEN_IN_MORE = 2000, 1 << 20
        path = self.write([self.prompt(0, "先做看板")])
        self.hook("UserPromptSubmit", prompt="先做看板", transcript_path=path)
        self.write([self.queued(1, "先别合并")] + [self.reply(2, "x" * 200) for _ in range(30)], append=True)
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先做看板"), ("user", "先别合并"), ("pm", "好")])

    def test_a_turn_stopped_by_the_user_is_caught_up_at_the_next_prompt(self):
        path = self.write([self.prompt(0, "先做看板")])
        self.hook("UserPromptSubmit", prompt="先做看板", transcript_path=path)
        self.write([self.queued(1, "先别合并"), self.prompt(2, "停一下")], append=True)  # no Stop hook: interrupted
        self.hook("UserPromptSubmit", prompt="停一下", transcript_path=path)
        self.hook("Stop", last_assistant_message="停了", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先做看板"), ("user", "先别合并"), ("user", "停一下"), ("pm", "停了")])

    def test_a_quick_answer_mid_turn_answers_the_question(self):
        name = Path(self.repo).name
        task = {"id": f"{name}-db", "title": "选数据库", "project": name, "repo": self.repo, "status": "blocked",
                "owner": "pm", "base": "main", "created": self.ctx.clock.now(), "log": []}
        Ledger(self.ctx).save(task)
        self.record("thread", task=task["id"], title="选数据库", status="blocked", text="status=blocked; 用哪个？",
                    options=["SQLite", "Postgres"])
        path = self.write([self.prompt(0, "看下状态"), self.queued(1, "【选数据库】SQLite")])
        self.assertEqual(answered_tasks(self.conversation()), set())
        # A turn a delivered batch started, which the user spoke into: its reply answers the user too.
        (self.project_dir() / "turn-cause.json").write_text(json.dumps({"after": "deliver", "batch": [0, 9]}))
        self.hook("Stop", last_assistant_message="好，用 SQLite。", transcript_path=path)
        self.assertEqual(answered_tasks(self.conversation()), {task["id"]})
        self.assertEqual(unanswered(self.conversation()), [])
        self.assertNotIn("after", self.conversation()[-1])
        self.assertEqual(Conversation(self.ctx, self.repo).tail()[-1],
                         {"user": "【选数据库】SQLite", "pm": "好，用 SQLite。"})

    def test_words_typed_during_swap_and_compact_summary_rows_are_handled_cleanly(self):
        self.hc_terminal = "t7"
        self.hc = FakeHc({"t7": {"state": "live", "labels": {}}})
        path = self.write([
            self.prompt(0, "[from pm.py rotate] 接手"),
            {"type": "user", "timestamp": self.at(0), "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
             "message": {"role": "user", "content": "This session is being continued from a previous conversation."}},
        ])
        self.hook("UserPromptSubmit", prompt="[from pm.py rotate] 接手", transcript_path=path)
        self.write([self.queued(1, "先别合并")], append=True)
        self.hook("Stop", last_assistant_message="好，先不合并。", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先别合并"), ("pm", "好，先不合并。")])
        self.assertFalse(any("pm.quiet" in str(c) for c in self.hc.calls))
        self.assertNotIn("pm.quiet", self.hc.terminals["t7"]["labels"])  # nor through the port's label()
        compact_row = {"type": "user", "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
                       "message": {"role": "user", "content": "Compacted summary"}}
        self.assertFalse(hooks.prompt_row(compact_row))
        summary_path = self.write([compact_row, self.prompt(2, "真实问题"), self.reply(3, "真实回答")],
                                  name="compact-tail.jsonl")
        self.assertEqual(conversation_tail(summary_path), [{"user": "真实问题", "pm": "真实回答"}])
        discord_rows = [
            {"type": "user", "message": {"role": "user", "content": "真实提问"}},
            {"type": "user", "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
             "message": {"role": "user", "content": "Compacted summary"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__discord__reply", "input": {}}]}},
        ]
        dpath = self.write(discord_rows, name="discord-compact.jsonl")
        self.assertTrue(replied_on_discord(dpath))

    def test_words_with_pictures(self):
        image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}
        path = self.write([self.prompt(0, "先做看板"),
                           self.queued(1, [{"type": "text", "text": "这里不对"}, image]),
                           self.queued(2, [{"type": "text", "text": "[Image #2] 还有这里"}, image]),
                           self.queued(3, [image, image]),
                           self.queued(4, [{"type": "text", "text": "  "}])])
        self.hook("Stop", last_assistant_message="看到了", transcript_path=path)
        self.assertEqual(self.said(), [("user", "[Image #1] 这里不对"), ("user", "[Image #2] 还有这里"),
                                       ("user", "[Image #1] [Image #2]"), ("pm", "看到了")])

    def delivery(self):
        return Delivery(self.ctx, self.repo)

    def test_a_batch_that_came_mid_turn_moves_the_delivered_mark_only(self):
        self.delivery().advance_delivered(0)
        path = self.write([self.prompt(0, "先做看板"),
                           self.queued(1, '<hc from="t9">[from pm.py deliver] 1 event(s) (0-120)\n1. x</hc>', kind="peer")])
        self.hook("Stop", last_assistant_message="收到", transcript_path=path)
        self.assertEqual(self.said(), [("pm", "收到")])
        self.assertEqual(self.delivery().delivered_offset(), 120)
        self.assertNotIn("after", self.conversation()[-1])  # the user's turn, not the batch's

    def test_a_batch_without_an_hc_tag_that_came_mid_turn_is_still_a_batch(self):
        # The deliverer runs without a terminal of its own, so hc types its batch in untagged.
        self.delivery().advance_delivered(0)
        path = self.write([self.prompt(0, "先做看板"),
                           self.queued(1, "[from pm.py deliver] 1 event(s) (0-140)\n1. x")])
        self.hook("Stop", last_assistant_message="收到", transcript_path=path)
        self.assertEqual(self.said(), [("pm", "收到")])                # not recorded as the user's words
        self.assertEqual(self.delivery().delivered_offset(), 140)
        self.assertEqual(self.delivery().received_ranges(), [[0, 140]])

    def test_a_pasted_batch_that_came_mid_turn_is_recognized_and_acked(self):
        self.delivery().advance_delivered(0)
        # Real Claude Code pasted_content tags carry attributes on BOTH open and close tags (e.g. id="898f").
        pasted = '\n\n<pasted_content id="898f">\n[from pm.py deliver] 1 event(s) (0-180)\n1. long report\n</pasted_content id="898f">\n'
        path = self.write([self.prompt(0, "先做看板"), self.queued(1, pasted)])
        self.hook("Stop", last_assistant_message="收到", transcript_path=path)
        self.assertEqual(self.said(), [("pm", "收到")])
        self.assertEqual(self.delivery().delivered_offset(), 180)
        self.assertEqual(self.delivery().received_ranges(), [[0, 180]])
        # A subsequent duplicate of the same batch in UserPromptSubmit is caught as a repeat.
        out = self.hook("UserPromptSubmit", prompt=pasted)
        self.assertIn("repeat", out)

    def test_nothing_fails_and_nothing_is_read_twice(self):
        # No transcript, an unreadable one, another agent's: the reply is recorded all the same.
        for transcript in ("", str(self.dir / "missing.jsonl"), str(self.dir)):
            self.hook("Stop", last_assistant_message="一", transcript_path=transcript)
        codex = self.write([{"type": "response_item", "payload": {"type": "message", "role": "user"}}, "[]"], "c.jsonl")
        self.hook("Stop", last_assistant_message="二", transcript_path=codex)
        self.assertEqual(self.said(), [("pm", "一")] * 3 + [("pm", "二")])
        # A long transcript: only its end is read, and only what came after the mark.
        hooks.TAKEN_IN_TAIL = 2000
        rows = [self.prompt(0, "先做看板")] + [self.reply(1, "x" * 200) for _ in range(30)] + [self.queued(2, "先别合并")]
        path = self.write(rows, "long.jsonl")
        reads = []
        real = open

        def counting(file, mode="r", *args, **kw):
            f = real(file, mode, *args, **kw)
            if str(file) == path:
                seek = f.seek
                f.seek = lambda n, *a: reads.append(n) or seek(n, *a)
            return f
        with mock.patch("builtins.open", counting):
            self.hook("Stop", last_assistant_message="三", transcript_path=path)
            self.hook("Stop", last_assistant_message="", transcript_path=path)
        size = Path(path).stat().st_size
        self.assertEqual(reads, [size - 2000, size])
        self.assertEqual(self.said()[-1:], [("pm", "三")])  # the turn's prompt is out of view: nothing is guessed
        # The mark stays small however many rows came in.
        path = self.write([self.prompt(0, "先做看板")] + [self.queued(3, "x") for _ in range(300)], "many.jsonl")
        hooks.TAKEN_IN_TAIL = 4 << 20
        self.hook("Stop", last_assistant_message="", transcript_path=path)
        mark = json.loads((self.project_dir() / "taken-in.json").read_text())
        self.assertEqual(len(mark["keys"]), hooks.TAKEN_IN_KEYS)
        self.assertEqual(len([e for e in self.conversation() if e.get("text") == "x"]), 300)

    # ---- attacks: each one a way the record could go wrong ----

    def ago(self, seconds):
        """The minute (from BASE) of `seconds` before now, in whole seconds: rows said just now."""
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        return (now - datetime.timedelta(seconds=seconds) - self.BASE).total_seconds() / 60

    def mark(self):
        return self.project_dir() / "taken-in.json"

    def test_a_stop_a_prompt_with_nothing_new_and_a_stop_again_add_nothing(self):
        path = self.write([self.prompt(0, "先做看板"), self.queued(1, "先别合并")])
        self.hook("Stop", last_assistant_message="一", transcript_path=path)
        self.hook("UserPromptSubmit", prompt="二", transcript_path=path)
        self.hook("Stop", last_assistant_message="", transcript_path=path)
        self.hook("Stop", last_assistant_message="", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先别合并"), ("pm", "一"), ("user", "二")])

    def test_the_same_words_said_again_are_recorded_again(self):
        # The user really said "继续" twice while the turn worked, after saying it as the turn's prompt.
        self.record("user", at=self.local(self.ago(120)), text="继续")
        path = self.write([self.prompt(self.ago(120), "继续"), self.queued(self.ago(60), "继续"),
                           self.queued(self.ago(58), "继续")])
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "继续")] * 3 + [("pm", "好")])

    def test_words_taken_into_a_stopped_turn_and_said_again_as_the_next_prompt(self):
        path = self.write([self.prompt(self.ago(300), "先做看板")])
        self.hook("UserPromptSubmit", prompt="先做看板", transcript_path=path)
        # Taken in a minute ago; the user stopped that turn (no Stop hook) and now says the same as a prompt.
        self.write([self.queued(self.ago(60), "继续"), self.prompt(self.ago(0), "继续")], append=True)
        self.hook("UserPromptSubmit", prompt="继续", transcript_path=path)
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先做看板"), ("user", "继续"), ("user", "继续"), ("pm", "好")])

    def test_a_rotation_whose_two_sessions_end_turns_close_together(self):
        old = self.write([self.prompt(self.ago(300), "先做看板")], name="old.jsonl")
        self.hook("UserPromptSubmit", prompt="先做看板", transcript_path=old)
        # The old session's last turn takes words in; the new session starts, takes words in and ends its turn first.
        self.write([self.queued(self.ago(100), "旧会话收下的话")], name="old.jsonl", append=True)
        new = self.write([self.prompt(self.ago(90), "[from pm.py rotate] 接手")], name="new.jsonl")
        self.hook("UserPromptSubmit", prompt="[from pm.py rotate] 接手", transcript_path=new)
        self.write([self.queued(self.ago(80), "新会话收下的话"), self.reply(self.ago(70))], name="new.jsonl", append=True)
        self.hook("Stop", last_assistant_message="新的回复", transcript_path=new)
        # The user says it again to the new PM: its own line, not the old session's.
        self.record("user", at=self.local(self.ago(60)), text="旧会话收下的话")
        self.hook("Stop", last_assistant_message="旧的回复", transcript_path=old)
        self.assertEqual(self.said(), [("user", "先做看板"), ("user", "新会话收下的话"), ("pm", "新的回复"),
                                       ("user", "旧会话收下的话"), ("user", "旧会话收下的话"), ("pm", "旧的回复")])
        # Each again: nothing new.
        self.hook("Stop", last_assistant_message="", transcript_path=new)
        self.hook("Stop", last_assistant_message="", transcript_path=old)
        self.assertEqual(len(self.said()), 6)

    def test_a_mark_or_a_row_from_the_future_does_not_silence_the_log(self):
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=400)).isoformat()
        path = self.write([self.prompt(0, "先做看板"), self.queued(1, "先别合并")])
        self.mark().write_text(json.dumps({"transcript": path, "offset": 0, "at": future, "keys": ["not-there"]}))
        self.hook("Stop", last_assistant_message="一", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先别合并"), ("pm", "一")])
        # A row written while the clock was a year ahead: words said after it, with the clock right again, count.
        self.write([self.prompt(2, "再看看"), self.queued(400 * 24 * 60, "钟快了"), self.queued(3, "颜色")], append=True)
        self.hook("Stop", last_assistant_message="二", transcript_path=path)
        self.write([self.prompt(self.ago(-2), "然后"), self.queued(self.ago(-3), "还有图例")], append=True)
        self.hook("Stop", last_assistant_message="三", transcript_path=path)
        self.assertEqual(self.said()[2:], [("user", "钟快了"), ("user", "颜色"), ("pm", "二"), ("user", "还有图例"),
                                           ("pm", "三")])
        self.assertLessEqual(self.conversation()[2]["at"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def test_a_lost_or_broken_mark_replays_nothing(self):
        # Hundreds of rows of turns before this was installed, a turn recorded since; then the mark goes bad.
        old = [r for i in range(300) for r in (self.prompt(0, f"旧{i}"), self.queued(0, f"旧插话{i}"))]
        path = self.write(old)
        self.hook("UserPromptSubmit", prompt="新的", transcript_path=path)
        self.write([self.prompt(10, "新的"), self.queued(11, "继续"), self.queued(12, "继续")], append=True)
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "新的"), ("user", "继续"), ("user", "继续"), ("pm", "好")])
        other = self.write([self.prompt(0, "别的会话")], name="other.jsonl")
        for broken in (None, "", "garbage", "null", '{"keys": [1, null], "files": 7, "at": 5}',
                       json.dumps({"transcript": other, "offset": 3, "at": self.at(0), "keys": ["x"]}),
                       json.dumps({"transcript": path, "offset": 10 ** 12, "at": "9999-12-31T00:00:00Z"})):
            if broken is None:
                self.mark().unlink()
            else:
                self.mark().write_text(broken)
            self.hook("Stop", last_assistant_message="", transcript_path=path)
            self.assertEqual(len(self.said()), 4, broken)

    def test_a_transcript_cut_short_rewritten_or_continued_in_another_file(self):
        rows = [self.prompt(0, "先做看板"), self.queued(1, "先别合并"), self.reply(2)]
        path = self.write(rows)
        self.hook("Stop", last_assistant_message="一", transcript_path=path)
        self.write(rows[:1], name="session.jsonl")                                 # cut short
        self.hook("Stop", last_assistant_message="", transcript_path=path)
        self.write(rows + [self.prompt(3, "再看"), self.queued(4, "加图例")])        # written again, longer
        self.hook("Stop", last_assistant_message="二", transcript_path=path)
        # Compacted or resumed into a file of its own: copies with new ids and none of their own, then new words.
        copies = [{**r, "uuid": f"copy-{i}", "attachment": {**r["attachment"], "source_uuid": None}}
                  if r["type"] == "attachment" else {**r, "uuid": f"copy-{i}"} for i, r in enumerate(rows)]
        later = self.write(copies + [self.prompt(5, "继续"), self.queued(6, "换个颜色")], name="compacted.jsonl")
        self.hook("Stop", last_assistant_message="三", transcript_path=later)
        self.assertEqual(self.said(), [("user", "先别合并"), ("pm", "一"), ("user", "加图例"), ("pm", "二"),
                                       ("user", "换个颜色"), ("pm", "三")])

    def test_two_projects_keep_their_own_record(self):
        repo2 = self.git.project_root(tempfile.mkdtemp(dir=self.base))
        reg2 = self.ctx.home.registration(project_slug(repo2))
        reg2.write_text(json.dumps({"name": pm_name(repo2), "pane": "hc:t8", "project": Path(repo2).name,
                                    "repo": repo2}))
        one = self.write([self.prompt(0, "一号"), self.queued(1, "给一号的话")], name="one.jsonl")
        two = self.write([self.prompt(0, "二号"), self.queued(1, "给二号的话")], name="two.jsonl")
        self.hook("Stop", last_assistant_message="一", transcript_path=one)
        self.hook("Stop", pane="hc:t8", last_assistant_message="二", transcript_path=two)
        self.hook("Stop", pane="hc:t7", last_assistant_message="", transcript_path=one)
        self.assertEqual(self.said(), [("user", "给一号的话"), ("pm", "一")])
        self.assertEqual([(e["type"], e["text"]) for e in self.conversation(repo2)], [("user", "给二号的话"), ("pm", "二")])

    def test_a_worker_session_records_nothing(self):
        path = self.write([self.prompt(0, "做任务"), self.queued(1, "先别合并")])
        # hc:t99: no PM registration names this terminal. (test_pm.py replaced worker_stopped with a no-op; here it
        # runs, on the Context's FakeHc, which knows no t99.)
        self.hook("UserPromptSubmit", pane="hc:t99", prompt="做任务", transcript_path=path)
        self.hook("Stop", pane="hc:t99", last_assistant_message="做完了", transcript_path=path)
        self.assertEqual(self.said(), [])
        self.assertFalse(self.mark().exists())

    def test_words_that_are_not_the_users_or_need_care(self):
        image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}
        odd = "第一行\n第二行\t\"引号\" \\反斜杠  分隔 段 \x85 \x0c 😀 </hc> <b>"
        long = "长" * 100000
        side = self.queued(9, "旁支里的话")
        side["isSidechain"] = True
        path = self.write([self.prompt(0, "先做看板"),
                           self.queued(1, ""), self.queued(1, "   \n "), self.queued(1, {"text": "字典"}),
                           self.queued(1, 7), self.queued(1, None), self.queued(1, [image, "x", 3, None]),
                           self.queued(2, "<system-reminder>x</system-reminder>", kind="peer", isMeta=True),
                           self.queued(2, "/model opus", kind="peer"),
                           self.queued(3, odd), self.queued(4, long), side,
                           self.queued(5, '<hc from="t9">\n  [from hc:t9]  做完了\n</hc>', kind="peer", isMeta=True),
                           self.queued(6, "[from hc:t3]   ")])
        with open(path, "a") as f:  # lines that are no rows, and a last one still being written
            f.write('not json at all\n{"type": "attachment", "attachment": [1]}\n[]\n\n\x00\xff\n'
                    '{"type": "attachment", "uuid": "half", "attachment": {"type": "queued_command", "prompt": "半')
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "[Image #1]"), ("user", odd.strip()), ("user", long),
                                       ("agent", "做完了"), ("pm", "好")])

    def test_an_answer_taken_in_mid_turn_then_the_question_asked_again(self):
        name = Path(self.repo).name
        task = {"id": f"{name}-db", "title": "选数据库", "project": name, "repo": self.repo, "status": "blocked",
                "owner": "pm", "base": "main", "created": self.ctx.clock.now(), "log": []}
        Ledger(self.ctx).save(task)
        ask = lambda: self.record("thread", task=task["id"], title="选数据库", status="blocked",
                                  text="status=blocked; 用哪个？", options=["SQLite", "Postgres"])
        ask()
        path = self.write([self.prompt(self.ago(120), "看下状态")])
        self.hook("UserPromptSubmit", prompt="看下状态", transcript_path=path)
        self.assertEqual(answered_tasks(self.conversation()), set())
        self.write([self.queued(self.ago(60), "【选数据库】SQLite")], append=True)
        self.assertEqual(answered_tasks(self.conversation()), set())   # not before the turn ends
        self.hook("Stop", last_assistant_message="好，用 SQLite。", transcript_path=path)
        self.assertEqual(answered_tasks(self.conversation()), {task["id"]})
        self.assertEqual(unanswered(self.conversation()), [])
        ask()  # asked again: a new question, open until the user answers it
        self.assertEqual(answered_tasks(self.conversation()), set())
        self.assertEqual(unanswered(self.conversation()), [])
        self.write([self.prompt(self.ago(0), "【选数据库】Postgres")], append=True)
        self.hook("UserPromptSubmit", prompt="【选数据库】Postgres", transcript_path=path)
        self.assertEqual(answered_tasks(self.conversation()), {task["id"]})
        self.assertEqual([e["text"] for e in unanswered(self.conversation())], ["【选数据库】Postgres"])

    def test_the_order_and_time_of_a_turn_that_took_words_in(self):
        path = self.write([self.prompt(self.ago(300), "先做看板")])
        self.hook("UserPromptSubmit", prompt="先做看板", transcript_path=path)
        self.record("thread", task="t-1", title="看板", status="in_progress", text="dispatched to w1")
        said = self.ago(30)
        self.write([self.queued(said, "先别合并")], append=True)
        self.hook("Stop", last_assistant_message="好，先不合并。", transcript_path=path)
        events = self.conversation()
        self.assertEqual([e["type"] for e in events], ["user", "thread", "user", "pm"])
        self.assertEqual(events[2]["at"], self.local(said))  # when it was said: before the thread entry
        self.assertLessEqual(events[2]["at"], events[1]["at"])
        self.assertEqual(unanswered(events), [])
        # One reply answers both: the handover does not show the turn's prompt as unanswered.
        conv = Conversation(self.ctx, self.repo)
        self.assertEqual(conv.tail(), [{"user": "先做看板\n先别合并", "pm": "好，先不合并。"}])
        handover = "\n".join(handover_talk(self.repo, {}, 6, 700, ctx=self.ctx))
        self.assertNotIn("(no final text)", handover)
        self.assertNotIn("Not answered yet", handover)
        code, out, _ = run_main(self.make(), "conversation", "--repo", self.repo, "--last", "10", "--width", "100")
        self.assertEqual(code, 0)
        self.assertEqual([line.split(" ", 2)[2] for line in out.splitlines()],
                         ["User: 先做看板", "[t-1 · in_progress] None: dispatched to w1", "User: 先别合并",
                          "PM: 好，先不合并。"])
        self.assertEqual(conv.turn_cause(), {})

    def test_hook_input_of_any_shape_never_fails_nor_writes_elsewhere(self):
        state = self.ctx.home.root
        # The ledger has its projects folder (test_pm.py's shared ledger always had one): only what is in it is new.
        self.ctx.home.projects.mkdir(parents=True, exist_ok=True)
        before = {p for p in state.rglob("*")}
        unreadable = self.write([self.prompt(0, "x"), self.queued(1, "y")], name="locked.jsonl")
        os.chmod(unreadable, 0)
        self.addCleanup(os.chmod, unreadable, 0o644)
        inputs = ["", "[]", '"Stop"', "null", "{}", '{"hook_event_name": "Stop"}',
                  json.dumps({"hook_event_name": "Stop", "transcript_path": 5, "last_assistant_message": ["x"]}),
                  json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": ["a", 1], "transcript_path": ["p"]}),
                  json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": 3, "cwd": 4}),
                  json.dumps({"hook_event_name": "Stop", "transcript_path": unreadable}),
                  json.dumps({"hook_event_name": "Stop", "transcript_path": str(self.dir)}),
                  json.dumps({"hook_event_name": "Stop", "transcript_path": "\x00"})]
        for stdin in inputs:
            self.hook_raw(stdin)
        written = {p for p in state.rglob("*")} - before
        allowed = self.project_dir()
        turn_log = self.ctx.home.turn_log
        self.assertEqual({p for p in written if allowed not in p.parents and p != allowed and p != turn_log
                          and p != turn_log.parent}, set())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["locked.jsonl"])

    def test_a_turn_that_wrote_more_than_can_be_read_on_is_read_from_its_end(self):
        hooks.TAKEN_IN_TAIL, hooks.TAKEN_IN_MORE = 3000, 6000
        path = self.write([self.prompt(0, "先做看板")])
        self.hook("UserPromptSubmit", prompt="先做看板", transcript_path=path)
        self.write([self.queued(1, "早早说的")] + [self.reply(2, "x" * 200) for _ in range(40)]
                   + [self.queued(3, "最后说的")], append=True)
        self.hook("Stop", last_assistant_message="好", transcript_path=path)
        self.assertEqual(self.said(), [("user", "先做看板"), ("user", "最后说的"), ("pm", "好")])


def make_repo(base):
    """A throwaway repository with a main branch and a task branch dev/x that adds new.txt."""
    repo = Path(tempfile.mkdtemp(prefix="land-", dir=base)).resolve()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    git = lambda *args: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                       check=True, capture_output=True, text=True, env=env).stdout
    git("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "init")
    git("checkout", "-q", "-b", "dev/x")
    (repo / "new.txt").write_text("hello\n")
    git("add", "new.txt")
    git("commit", "-q", "-m", "add new.txt")
    git("checkout", "-q", "main")
    return repo, git


class RunningTui(FakeTui):
    """The herdr TUI as test_pm.py's TerminalUI faked it: `running` (pane -> agent name) is every live agent; a tab
    opens as w2:t3 with root pane w2:p3; `agent rename` keeps herdr's rules (at most 32 characters, unique among
    live agents); commands in `refuse` fail. `calls` holds each call's arguments (sessions are not used here)."""

    def __init__(self, running):
        super().__init__()
        self.running = running
        self.refuse = set()
        self.herdr_calls = []
        self.answer = None  # (args) -> a result, or None to answer as above

    def herdr(self, *args, session=None):
        args = tuple(str(a) for a in args)
        self.herdr_calls.append(args)
        if self.answer is not None:
            res = self.answer(args)
            if res is not None:
                return res
        if args[:2] in self.refuse:
            return None
        if args[:2] == ("tab", "create"):
            return {"tab": {"tab_id": "w2:t3"}, "root_pane": {"pane_id": "w2:p3"}}
        if args[:2] == ("agent", "start"):
            self.running[args[args.index("--pane") + 1]] = args[2]
        if args[:2] == ("agent", "list"):
            return {"agents": [{"pane_id": p, "name": n, "agent_status": "idle"} for p, n in self.running.items()]}
        if args[:2] == ("agent", "rename"):
            if args[2] not in self.running and args[2] not in self.running.values():
                return None
            pane = args[2] if args[2] in self.running else next(p for p, n in self.running.items() if n == args[2])
            if len(args[3]) > 32 or any(n == args[3] and p != pane for p, n in self.running.items()):
                return None  # herdr: at most 32 characters, unique among live agents
            self.running[pane] = args[3]
        if args[:2] == ("pane", "close"):
            self.running.pop(args[2], None)
        return {"ok": True}

    def agents(self, *, session=None):
        return self.herdr("agent", "list")["agents"]

    def panes(self, *, session=None):
        res = self.herdr("pane", "list")
        return res.get("panes", []) if isinstance(res, dict) else None


class RecordingHc(FakeHc):
    """FakeHc that answers every call, as TerminalUI's hc did ({"address": "t99", "state": "live"}), and records
    each one, the port's methods too: TerminalUI asserts herdr-core is never used."""

    def __init__(self):
        super().__init__({"t99": {"state": "live"}})

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if callable(attr) and not name.startswith("_") and name not in ("calls",):
            def recorded(*args, **kw):
                object.__getattribute__(self, "used").append((name, args))
                return attr(*args, **kw)
            return recorded
        return attr

    @property
    def used(self):
        d = object.__getattribute__(self, "__dict__")
        return d.setdefault("_used", [])


class TerminalUI(unittest.TestCase):
    """A PM in the herdr terminal UI ($HERDR_PANE_ID): its workers and reviewers are herdr agents in tabs; herdr-core
    is never used, even on a computer where `hc` is installed."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="pm-hooks-tui-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.tui = RunningTui({"w1:p0": "pm-x"})  # pane: agent name
        self.hc = RecordingHc()
        self.git = GitRepo(worktree_base=self.base / "worktrees")
        self.ctx = self.make()

    @property
    def running(self):
        return self.tui.running

    @running.setter
    def running(self, value):
        self.tui.running = value

    @property
    def herdr_calls(self):
        return self.tui.herdr_calls

    @property
    def hc_calls(self):
        return self.hc.used

    def make(self, *, extra_env=None):
        """A Context in the PM's TUI pane w1:p0 (workspace w1); the same ledger home, hosts and spawn log."""
        procs = getattr(self, "procs", None)
        env = {"HERDR_PANE_ID": "w1:p0", "HERDR_WORKSPACE_ID": "w1", **(extra_env or {})}
        ctx = make_ctx(self.base, pane="w1:p0", workspace="w1", hc=self.hc, tui=self.tui, git=self.git,
                       out=StdOutput(), procs=procs, env=env)
        self.procs = ctx.procs
        return ctx

    def run_cmd(self, name, a, *, extra_env=None):
        out = io.StringIO()
        ctx = self.make(extra_env=extra_env)
        mod = cli.COMMANDS[name][0]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                getattr(mod, cli.COMMANDS[name][1])(a, ctx=ctx)
            except SystemExit as stop:
                out.write(f"\nexit: {stop.code}")
        return out.getvalue()

    def test_a_herdr_command_that_prints_nothing_has_succeeded(self):
        # The herdr port itself (TuiHost, which Context.from_env builds), not a fake: herdr's answers replaced.
        done = lambda code, out="", err="": subprocess.CompletedProcess([], code, out, err)
        answers = iter([done(0), done(1, err='{"error":{"code":"pane_not_found"}}'),
                        done(0, '{"id":"cli:pane:get","result":{"pane":{"workspace_id":"w1"}}}')])
        argvs = []
        host = TuiHost(raw_runner=lambda argv, timeout=30: argvs.append(argv) or next(answers))
        self.assertTrue(host("pane", "run", "w1:p4", "claude"))  # `pane run` answers nothing
        self.assertIsNone(host("pane", "run", "w9:p9", "claude"))
        self.assertEqual(host("pane", "get", "w1:p1"), {"pane": {"workspace_id": "w1"}})
        self.assertEqual(argvs[0], ["herdr", "pane", "run", "w1:p4", "claude"])

    def test_review_opens_a_tab_beside_the_worker_and_never_uses_herdr_core(self):
        repo, git = make_repo(self.base)
        git("branch", "-D", "dev/x")
        tree = Path(tempfile.mkdtemp(dir=self.base)).resolve() / "tree"
        git("worktree", "add", "-q", str(tree), "-b", "dev/x")
        Ledger(self.ctx).save({"id": "tui-r", "title": "加一行", "project": repo.name, "repo": str(repo),
                               "status": "review", "owner": "pm", "base": "main", "branch": "dev/x",
                               "worktree": str(tree), "workspace": "w2", "pane": "w2:p1",
                               "agent": "a-worker-with-a-rather-long-name", "worker_pane": "w2:p1",
                               "dispatched": True, "created": self.ctx.clock.now()})
        review = argparse.Namespace(id="tui-r", name=None, kind="claude", model="sonnet", effort=None)
        out = self.run_cmd("review", review)
        self.assertNotIn("exit:", out)
        self.assertEqual(self.hc_calls, [])
        tab = next(c for c in self.herdr_calls if c[:2] == ("tab", "create"))
        self.assertEqual((tab[tab.index("--workspace") + 1], tab[tab.index("--cwd") + 1]), ("w2", str(tree)))
        start = next(c for c in self.herdr_calls if c[:2] == ("agent", "start"))
        name = start[2]
        self.assertTrue(len(name) <= 32 and name.endswith("-review"), name)  # herdr's limit for agent names
        self.assertEqual(start[start.index("--", 3) + 1:],
                         ("--model", "sonnet", "--disallowedTools", "Edit,Write,NotebookEdit"))
        prompt = next(c for c in self.herdr_calls if c[:2] == ("agent", "prompt"))
        self.assertEqual(prompt[2], name)
        self.assertIn("update tui-r-review --status done", prompt[3])
        record = Ledger(self.ctx).load("tui-r-review")
        self.assertEqual((record["pane"], record["worker_pane"], record["workspace"]), ("w2:p3", "w2:p3", "w2"))
        self.assertIn("w2:p3", out)
        # Run again: the previous reviewer's pane is closed first, so its name is free for the new one.
        self.herdr_calls.clear()
        self.run_cmd("review", review)
        closes = [c for c in self.herdr_calls if c[:2] == ("pane", "close")]
        self.assertEqual(closes, [("pane", "close", "w2:p3")])
        self.assertLess(self.herdr_calls.index(closes[0]),
                        self.herdr_calls.index(next(c for c in self.herdr_calls if c[:2] == ("agent", "start"))))
        # Retiring the task closes its review, and that closes the reviewer's pane; never the PM's own.
        git("merge", "-q", "--no-ff", "-m", "m", "dev/x")
        self.herdr_calls.clear()
        self.run_cmd("retire", argparse.Namespace(id="tui-r", force=False))
        self.assertIn(("pane", "close", "w2:p3"), self.herdr_calls)
        self.assertNotIn(("pane", "close", "w1:p0"), self.herdr_calls)
        self.assertTrue(Ledger(self.ctx).load("tui-r-review").get("retired"))
        self.assertEqual(self.hc_calls, [])

    def register(self, pane="w1:p0", repo=None):
        repo = repo or self.git.project_root(tempfile.mkdtemp(dir=self.base))
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.ctx.home.registration(project_slug(repo)).write_text(json.dumps(
            {"name": pm_name(repo), "project": Path(repo).name, "repo": repo, "pane": pane, "workspace": "w1",
             "agent": "claude"}))
        return repo

    def test_rotate_names_the_new_pm_once_herdr_sees_it(self):
        repo = self.register()
        name = pm_name(repo)
        self.running = {"w1:p0": name, "w1:p9": f"ex-{name}"}  # w1:p9: the PM before, retired and still open
        argv_seen, looks = [], []

        def answer(args):
            if args[:2] == ("pane", "process-info"):
                return {"process_info": {"foreground_processes": [{"argv": ["claude", "--model", "opus"]}]}}
            if args[:2] == ("pane", "get"):
                return {"pane": {"workspace_id": "w1"}}
            if args[:2] == ("pane", "run"):
                argv_seen.append(args[3])
            if args[:2] == ("agent", "list") and argv_seen:
                looks.append(args)
                if len(looks) >= 3:  # herdr sees the new agent in its pane only after a few looks
                    self.running.setdefault("w2:p3", "")
            return None
        self.tui.answer = answer
        rotate = argparse.Namespace(repo=repo, notes="n", model=None, transcript="/nonexistent/t.jsonl")
        out = self.run_cmd("rotate", rotate)
        self.assertNotIn("exit:", out)
        self.assertEqual(self.running, {"w1:p0": f"ex2-{name}", "w1:p9": f"ex-{name}", "w2:p3": name})
        rec = ProjectRegistry(self.ctx).pm_record(repo)
        self.assertEqual((rec["pane"], rec["previous"]["pane"]), ("w2:p3", "w1:p0"))
        self.assertNotIn("startup dialog", out)
        # The words the outgoing PM gets agree: tell the user to continue in the new tab.
        self.assertIn("tell the user to continue there", out)
        self.assertIn("three or four sentences", argv_seen[0])  # the new PM says what it took over
        self.assertEqual(retire_name("w2:p3", "pm-" + "x" * 29, ctx=self.make()), True)  # clipped to 32 characters
        self.assertEqual(self.running["w2:p3"], "ex-pm-" + "x" * 26)
        self.running["w2:p4"] = "pm-x_"  # a name may end in _ (project_slug keeps it): no other name comes of it
        self.assertTrue(retire_name("w2:p4", "pm-x_", ctx=self.make()))
        self.assertEqual(self.running["w2:p4"], "ex-pm-x_")

    def test_a_rotate_whose_new_pm_cannot_start_changes_nothing(self):
        repo = self.register()
        name = pm_name(repo)
        self.running = {"w1:p0": name}
        self.tui.answer = lambda args: {"pane": {"workspace_id": "w1"}} if args[:2] == ("pane", "get") else None
        self.tui.refuse.add(("pane", "run"))
        out = self.run_cmd("rotate", argparse.Namespace(repo=repo, notes="what is in flight", model=None,
                                                        transcript="/nonexistent/t.jsonl"))
        self.assertIn("exit:", out)
        self.assertIn("stays the PM", out)
        self.assertEqual(self.running, {"w1:p0": name})  # its name back; the new tab closed
        rec = ProjectRegistry(self.ctx).pm_record(repo)
        self.assertEqual(rec["pane"], "w1:p0")
        self.assertNotIn("rotations", rec)
        self.assertIn("what is in flight", (self.ctx.home.project_for(repo).ensure() / "handover.md").read_text())

    def hook(self, name, cwd, stdin=""):
        """Run a hook as Claude Code does: in the session's folder, with the event on stdin."""
        here = os.getcwd()
        os.chdir(cwd)
        try:
            with mock.patch.object(sys, "stdin", io.StringIO(stdin)):
                return self.run_cmd(name, argparse.Namespace(), extra_env={"HERDR_ENV": "1"})
        finally:
            os.chdir(here)

    def test_in_herdr_session_ignores_host_os_environ_when_ctx_env_omits_herdr_env(self):
        isolated = make_ctx(self.base, pane="w1:p0", env={"HERDR_PANE_ID": "w1:p0"})
        isolated.env.pop("HERDR_ENV", None)
        with mock.patch.dict(os.environ, {"HERDR_ENV": "1"}, clear=False):
            self.assertFalse(hooks.in_herdr_session(isolated))

    def named_later(self):
        """The `pm.py name-agent <pane> <name>` processes the hooks started (name_later), as (pane, name)."""
        return [tuple(s["args"][1:3]) for s in self.procs.spawned if s["args"][:1] == ["name-agent"]]

    def conversation(self, repo):
        return Conversation(self.ctx, repo).events()

    def test_hooks_ignore_a_registration_whose_pane_now_holds_another_project(self):
        repo = self.register(pane="w1:p0")
        name = pm_name(repo)
        elsewhere = self.git.project_root(tempfile.mkdtemp(dir=self.base))
        self.running = {"w1:p0": ""}  # a session of another project, in a pane id the server gave out again
        turn = lambda prompt, cwd: json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": cwd})
        self.assertEqual(self.hook("hook-session-start", elsewhere), "")
        self.hook("hook-turn", elsewhere, turn("你好", elsewhere))
        self.assertEqual(self.conversation(repo), [])
        self.assertEqual(self.running, {"w1:p0": ""})
        self.assertEqual(self.named_later(), [])
        # In its own project the same session is the PM: it is told so, and named once herdr sees it.
        self.tui.refuse.add(("agent", "rename"))  # too early: herdr does not see the agent yet
        out = self.hook("hook-session-start", repo)
        self.assertIn(f"You are {name}", out)
        self.assertEqual(self.named_later(), [("w1:p0", name)])
        self.hook("hook-turn", repo, turn("你好", repo))
        self.assertEqual([(e["type"], e["text"]) for e in self.conversation(repo)], [("user", "你好")])
        # A PM claimed with --repo from a folder above the project (pm-issues: ~ for ~/Desktop/…/issues): its log
        # goes on, and when it restarts it is told it is the PM and gets its name back.
        above = str(Path(repo).parent)
        self.hook("hook-turn", above, turn("上面", above))
        self.assertEqual(self.conversation(repo)[-1]["text"], "上面")
        self.tui.refuse.clear()
        out = self.hook("hook-session-start", above)
        self.assertIn(f"You are {name}", out)
        self.assertEqual(self.running, {"w1:p0": name})

    def test_hooks_skip_quietly_without_a_folder_or_a_repo(self):
        repo = self.register(pane="w1:p0")
        self.running = {"w1:p0": ""}
        gone = str(Path(tempfile.mkdtemp(dir=self.base)) / "removed")  # the session's folder no longer exists
        event = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "你好", "cwd": gone})
        self.assertEqual(self.hook("hook-turn", repo, event), "")
        path = self.ctx.home.registration(project_slug(repo))
        rec = json.loads(path.read_text())
        rec.pop("repo")  # a registration without its repo
        path.write_text(json.dumps(rec))
        event = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "你好", "cwd": repo})
        self.assertEqual(self.hook("hook-turn", repo, event), "")
        self.assertEqual(self.hook("hook-session-start", repo), "")
        self.assertEqual(self.conversation(repo), [])
        self.assertEqual(self.running, {"w1:p0": ""})

    def test_a_reviewer_pane_that_holds_another_agent_now_is_not_closed(self):
        review = {"id": "t-review", "pane": "w2:p3", "worker_pane": "w2:p3", "agent": "w-review"}
        for now in ({"w2:p3": "someone-else"}, {}):  # another agent came in; the reviewer exited, a shell is left
            self.running = {"w1:p0": "pm-x", **now}
            self.assertEqual(end_worker_for(self.make(), review), "")
            self.assertNotIn(("pane", "close", "w2:p3"), self.herdr_calls)
        self.running["w2:p3"] = "w-review"
        self.assertEqual(end_worker_for(self.make(), review), "pane w2:p3")


class PmQuestionCardsAndStaleBlockedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = str((self.root / "repo").resolve())
        Path(self.repo).mkdir(parents=True)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.hc = FakeHc()
        self.git = GitRepo(worktree_base=self.root / "worktrees")
        self.ctx = self.make()
        self.state = self.ctx.home.root
        slug = project_slug(self.repo)
        self.pm_rec = {"name": f"pm-{slug}", "project": "repo", "repo": self.repo, "pane": "hc:t160", "runtime": "hc"}
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.ctx.home.registration(slug).write_text(json.dumps(self.pm_rec))

    def make(self, pane="hc:t160", hc_term="t160"):
        """A Context for one pm.py process in terminal `pane`; the same ledger home, herdr-core and spawn log."""
        procs = getattr(self, "procs", None)
        ctx = make_ctx(self.root, pane=pane, hc_terminal=hc_term, hc=self.hc, git=self.git, procs=procs,
                       out=StdOutput())
        self.procs = ctx.procs
        return ctx

    def run_pre_tool(self, payload, *, pane="hc:t160", hc_term="t160", lang="en"):
        (self.state / "config.json").write_text(json.dumps({"lang": lang}))
        out = io.StringIO()
        with mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(out):
            hooks.cmd_hook_pre_tool(argparse.Namespace(), ctx=self.make(pane, hc_term))
        return out.getvalue().strip()

    def test_pre_tool_hook_denies_ask_user_question_in_pm_and_generates_card_command(self):
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "cwd": self.repo,
            "tool_input": {
                "questions": [{
                    "header": "autoDream 设计稿",
                    "question": "那份未入台账的 autoDream 设计稿怎么处理？",
                    "options": [
                        {"label": "建任务继续做（推荐）", "description": "在台账新建任务并派 worker 实现"},
                        {"label": "先留在暂存", "description": "暂不处理，等之后再说"},
                    ],
                }],
            },
        }
        raw = self.run_pre_tool(payload, lang="zh")
        resp = json.loads(raw)
        hso = resp["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        reason = hso["permissionDecisionReason"]
        self.assertIn("AskUserQuestion", reason)
        self.assertIn("--status blocked", reason)
        self.assertIn("autoDream 设计稿", reason)
        self.assertIn("建任务继续做", reason)
        self.assertIn("--why", reason)
        self.assertIn("--recommend", reason)
        self.assertNotIn("（推荐）", reason.split("--option")[1].split("--why")[0])

        # Codex request_user_input with a non-first recommended option uses the same schema.
        codex_payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "request_user_input",
            "cwd": self.repo,
            "tool_input": {
                "questions": [{
                    "header": "Cache backend",
                    "question": "Which cache backend should we use?",
                    "options": [
                        {"label": "SQLite", "description": "single process"},
                        {"label": "Redis (Recommended)", "description": "shared across instances"},
                    ],
                }],
            },
        }
        codex_resp = json.loads(self.run_pre_tool(codex_payload, lang="en"))
        self.assertEqual(codex_resp["hookSpecificOutput"]["permissionDecision"], "deny")
        codex_reason = codex_resp["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("request_user_input", codex_reason)
        self.assertIn("Redis (Recommended)", codex_reason)

    def test_pre_tool_hook_ignores_workers_and_non_question_tools(self):
        ask = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "cwd": self.repo,
            "tool_input": {"questions": [{"header": "Q", "question": "Proceed?", "options": [{"label": "Yes"}]}]},
        }
        # Worker terminal is not the registered PM: hook stays silent and allows through.
        self.assertEqual(self.run_pre_tool(ask, pane="hc:t22", hc_term="t22"), "")
        # Non-question tool in PM session: hook stays silent.
        self.assertEqual(self.run_pre_tool({
            "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.repo, "tool_input": {"command": "ls"},
        }), "")

    def load(self, tid):
        return Ledger(self.ctx).load(tid)

    def conversation(self):
        return Conversation(self.ctx, self.repo).events()

    def test_inline_recommend_marker_on_any_option_and_cleanup(self):
        tid = "repo-rec"
        Ledger(self.ctx).save({"id": tid, "title": "选方案", "project": "repo", "repo": self.repo,
                               "status": "in_progress", "owner": "pm", "base": "main", "created": self.ctx.clock.now()})
        command(self.make(), "update", tid, "--status", "blocked", "--note", "选哪个？",
                "--option", "方案 A", "--why", "快",
                "--option", "方案 B（推荐）", "--why", "更稳")
        task = self.load(tid)
        ev = self.conversation()[-1]
        for rec in (task, ev):
            self.assertEqual(rec["options"], ["方案 A", "方案 B"])
            self.assertEqual(rec["option_notes"], ["快", "更稳"])
            self.assertIs(rec["recommended"], True)
            self.assertEqual(rec["recommended_index"], 1)
        # First option inline marker keeps exact legacy shape (no recommended_index key).
        command(self.make(), "update", tid, "--status", "blocked", "--note", "再问一次？",
                "--option", "First (Recommended)", "--option", "Second")
        task0 = self.load(tid)
        self.assertEqual(task0["options"], ["First", "Second"])
        self.assertIs(task0["recommended"], True)
        self.assertNotIn("recommended_index", task0)
        # Moving on clears all question fields including recommended_index.
        command(self.make(), "update", tid, "--status", "in_progress", "--note", "ok")
        done = self.load(tid)
        for gone in QUESTION_FIELDS:
            self.assertNotIn(gone, done)

    def sends(self):
        """How many background sends (send_async_later: `pm.py _deliver-send ...`) were started so far."""
        return len([s for s in self.procs.spawned if s["args"][:1] == ["_deliver-send"]])

    def test_pm_send_and_update_send_unblock_worker_blocked_task_and_mark_handled_by_pm(self):
        tid = "repo-at"
        Ledger(self.ctx).save({"id": tid, "title": "项目输入框 @", "project": "repo", "repo": self.repo,
                               "status": "in_progress", "owner": "pm", "pane": "hc:t22", "base": "main",
                               "created": self.ctx.clock.now(),
                               "log": [{"at": self.ctx.clock.now(), "by": "hc:t160", "text": "dispatched"}]})
        worker = lambda: self.make("hc:t22", "t22")
        manager = lambda: self.make("hc:t160", "t160")
        # Worker reports blocked (land blocked by dirty main checkout).
        command(worker(), "update", tid, "--status", "blocked", "--note", "land exit 2: 主检出有未提交改动")
        self.assertEqual(self.load(tid)["status"], "blocked")

        # 1. PM runs `pm.py send <task_id> "..."` -> task immediately moves to in_progress with handled_by="pm".
        self.hc.terminals["t22"] = {"state": "live", "turn": 3}
        command(manager(), "send", tid, "主检出已清理，重新 pm.py land")
        self.assertEqual(self.sends(), 1)
        self.assertEqual(self.load(tid)["status"], "in_progress")
        ev = self.conversation()[-1]
        self.assertEqual(ev["status"], "in_progress")
        self.assertEqual(ev.get("handled_by"), "pm")

        # 2. Worker blocks again; PM runs `pm.py send t22 "..."` (by terminal address) -> still resolves task & unblocks.
        command(worker(), "update", tid, "--status", "blocked", "--note", "blocked again")
        self.hc.terminals["t22"] = {"state": "live", "turn": 4}
        command(manager(), "send", "t22", "retry now")
        self.assertEqual(self.load(tid)["status"], "in_progress")
        self.assertEqual(self.conversation()[-1].get("handled_by"), "pm")

        # 3. Worker blocks again; PM runs `pm.py update <id> --note "..." --send` (without --status) -> auto-resumes!
        command(worker(), "update", tid, "--status", "blocked", "--note", "blocked 3")
        self.hc.terminals["t22"] = {"state": "live", "turn": 5}
        command(manager(), "update", tid, "--note", "继续合并", "--send")
        self.assertEqual(self.load(tid)["status"], "in_progress")
        self.assertEqual(self.conversation()[-1].get("handled_by"), "pm")

        # 4. PM-asked question ON a worker task must NOT be auto-unblocked by PM's subsequent `send` or `update --send`.
        command(manager(), "update", tid, "--status", "blocked", "--note", "选方案 A 还是 B？",
                "--option", "方案 A", "--option", "方案 B", "--recommend")
        self.assertFalse(Caller(manager()).blocked_by_worker(self.load(tid)))
        self.hc.terminals["t22"] = {"state": "live", "turn": 6}
        before = self.sends()
        command(manager(), "send", tid, "先别动，等用户拍板")
        command(manager(), "send", "t22", "继续等一下")
        command(manager(), "update", tid, "--note", "提醒 worker 暂缓", "--send")
        self.assertEqual(self.sends() - before, 3)
        kept = self.load(tid)
        self.assertEqual(kept["status"], "blocked")
        self.assertEqual(kept["options"], ["方案 A", "方案 B"])
        self.assertIs(kept["recommended"], True)
        self.assertNotIn("handled_by", self.conversation()[-1])

        # 5. PM-asked standalone question closed by PM after user answers does NOT spuriously tag handled_by="pm".
        qid = command(manager(), "new", "推送确认", "--repo", self.repo, "--status", "blocked", "--note", "推吗？",
                      "--option", "推", "--option", "先不", "--recommend")
        command(manager(), "update", qid, "--status", "done", "--note", "用户说先不")
        self.assertNotIn("handled_by", self.conversation()[-1])


if __name__ == "__main__":
    unittest.main()
