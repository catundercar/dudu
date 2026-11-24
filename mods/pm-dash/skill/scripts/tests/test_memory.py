"""Two layers of memory files in the ledger home: the index goes to every session, a body is read on demand.

Moved from test_pm.py `Memory` (Stage 6a): every test runs on its own `make_ctx` Context and temporary ledger.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-memory")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

import pmlib.cli  # noqa: F401, E402 - wires every pmlib module, as the command line does
from pmlib.context import StdOutput  # noqa: E402
from pmlib.commands import manager as manager_cmds, memory as memory_cmds  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.manager.handover import handover_compact_text  # noqa: E402
from pmlib.manager.launch import pm_argv  # noqa: E402
from pmlib.manager.service import ManagerSessions  # noqa: E402
from pmlib.memory import layer as layer_mod  # noqa: E402
from pmlib.memory.candidates import CANDIDATE_GRACE, MemoryCandidates  # noqa: E402
from pmlib.memory.layer import MemoryLayer, MemoryRefused, memory_text, read_memory  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import pm_name  # noqa: E402
from pmlib.workers.service import Workers  # noqa: E402
from tests.fakes import FakeClock, FakeHc, make_ctx  # noqa: E402


class MemoryTest(unittest.TestCase):
    """Two layers of memory files in the ledger home: the index goes to every session, a body is read on demand."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.clock = FakeClock()
        self.hc = FakeHc(clock=self.clock)
        self.config = None
        self.ctx = self.session("")
        self.repo = self.new_repo("proj")
        self.name = Path(self.repo).name

    # --- this test's sessions over the one temporary ledger ---

    def session(self, pane):
        """A Context for the session in `pane` ("" for the user's own shell), over this test's ledger."""
        ctx = make_ctx(self.base, pane=pane, hc=self.hc, clock=self.clock, out=StdOutput(), config=self.config)
        ctx.candidate_pruner = lambda repo: MemoryCandidates(ctx, repo).prune()
        return ctx

    def be(self, pane):
        self.ctx = self.session(pane)

    def set_config(self, value):
        self.config = value
        self.ctx.home.config.write_text(json.dumps(value))

    def new_repo(self, name):
        path = self.base / "repos" / name
        path.mkdir(parents=True)
        return self.ctx.git.project_root(path)

    def pm_is(self, pane="hc:t7"):
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        (self.ctx.home.registrations / f"{project_slug(self.repo)}.json").write_text(json.dumps(
            {"name": pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": pane,
             "runtime": "hc", "terminal": pane[3:], "agent": "claude"}))

    def worker(self, slug, pane):
        task = {"id": f"{self.name}-{slug}", "title": slug, "project": self.name, "repo": self.repo,
                "status": "in_progress", "owner": "pm", "base": "main", "pane": pane, "dispatched": True,
                "created": self.clock.now(), "log": []}
        Ledger(self.ctx).save(task)
        return task["id"]

    # --- what test_pm.py reached through pm.* ---

    def layer(self, repo="", **kw):
        return MemoryLayer(self.ctx, self.repo if repo == "" else repo, **kw)

    def remember(self, text, *, repo=None, personal=False, index_lines_cap=None, **kw):
        """`pm.remember(repo, text, ...)`: written as the calling session, into the project or the personal layer."""
        repo = self.repo if repo is None else repo
        layer = MemoryLayer(self.ctx, None if personal else repo, index_lines_cap=index_lines_cap)
        return layer.remember(text, writer=self.ctx.caller.memory_writer(repo), project_repo=repo, **kw)

    def memory_dir(self, repo=None):
        return self.ctx.home.memory_dir(self.repo if repo is None else repo)

    def index(self, repo=""):
        path = self.memory_dir(self.repo if repo == "" else repo) / "MEMORY.md"
        return path.read_text() if path.exists() else ""

    def record(self, kind, **fields):
        return Conversation(self.ctx, self.repo).record(kind, **fields)

    def conversation(self, repo=None):
        path = Conversation(self.ctx, self.repo if repo is None else repo).path
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def project_dir(self, repo=None):
        return self.ctx.home.project_for(self.repo if repo is None else repo).ensure()

    def run_cmd(self, command, **fields):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            command(argparse.Namespace(repo=self.repo, **fields), ctx=self.ctx)
        return out.getvalue()

    def handover(self, repo=None):
        """What `pm.py handover` prints."""
        return ManagerSessions(self.ctx).handover(self.repo if repo is None else repo, turns=6) + "\n"

    def keep_sent(self, task_id, brief):
        """`pm.keep_sent` on this test's Context."""
        return Workers(self.ctx).keep_sent(task_id, brief)

    # --- the tests ---

    def test_a_memory_is_one_file_in_claude_codes_format_and_the_index_lists_it(self):
        self.record("user", text="最后 我们的实现里面不要有直角线")
        m, notes = self.remember("看板连线只用直线和曲线，不要直角线", kind="feedback",
                                 name="no-right-angle-wires", quote="我们的实现里面，不要有直角线")
        self.assertEqual(notes, [])
        path = self.memory_dir() / "no-right-angle-wires.md"
        text = path.read_text()
        self.assertTrue(text.startswith('---\nname: no-right-angle-wires\ndescription: "看板连线只用直线和曲线，不要直角线"\n'
                                        "metadata:\n  node_type: memory\n  type: feedback\n  topic: workflow\n"
                                        "  modified: "), text)
        back = read_memory(path)
        self.assertEqual((back["type"], back["by"], back["quote"], back["quote_checked"], back["body"]),
                         ("feedback", "user", "我们的实现里面，不要有直角线", "true", "看板连线只用直线和曲线，不要直角线"))
        self.assertEqual(self.index(), "### Collaboration & dispatch\n- [no-right-angle-wires](no-right-angle-wires.md) — "
                                       "看板连线只用直线和曲线，不要直角线 (feedback)\n")
        event = self.conversation()[-1]
        self.assertEqual((event["type"], event["layer"], event["action"], event["name"], event["by"]),
                         ("memory", "project", "remember", "no-right-angle-wires", "user"))

    def test_a_memory_brought_in_from_an_older_record_keeps_its_date_and_logs_no_event(self):
        self.remember("只有正在工作的线流动", name="only-working-wires-flow", quote="同意",
                      by="migration", when="2026-11-10", quiet=True)
        self.remember("Esc 统一表示退一层", name="esc-goes-back", quote="按这个来", quiet=True,
                      when="2026-11-15T03:04:05.000Z")
        old, new = (read_memory(self.memory_dir() / f"{n}.md") for n in ("only-working-wires-flow", "esc-goes-back"))
        self.assertEqual((old["modified"], old["by"]), ("2026-11-10T00:00:00.000Z", "migration"))
        self.assertEqual(new["modified"], "2026-11-15T03:04:05.000Z")
        self.assertEqual([line.split("]")[0] for line in self.index().splitlines()],
                         ["### Product & architecture", "- [esc-goes-back", "- [only-working-wires-flow"])  # newest first
        self.assertEqual(self.conversation(), [])

    def test_a_quote_the_user_never_typed_is_written_and_marked(self):
        self.record("user", text="侧栏入口叫 Projects。先出设计稿")
        ok, _ = self.remember("侧栏入口叫 Projects", kind="feedback", name="entry-is-projects",
                              quote="侧栏入口叫Projects … 先出设计稿")  # pieces, spacing and punctuation aside
        bad, notes = self.remember("默认深色主题", kind="feedback", name="dark-by-default", quote="用深色")
        self.assertEqual((ok["quote_checked"], bad["quote_checked"]), ("true", "false"))
        self.assertIn("not found among the user's words", notes[0])
        self.assertIn("(feedback; quote not found in the log)", self.index())
        self.assertIn("(not found in the log)",
                      self.layer().recall_text(read_memory(self.memory_dir() / "dark-by-default.md")))

    def test_a_worker_writes_what_it_found_out_and_nothing_else(self):
        self.pm_is()
        mine, other = self.worker("a", "hc:t20"), self.worker("b", "hc:t21")
        self.be("hc:t20")
        for wrong in ({"kind": "feedback", "quote": "x"}, {"kind": "reference", "personal": True}, {"kind": "project"}):
            with self.assertRaises(MemoryRefused):
                self.remember("渲染检查要开着显示器", name="render-check-needs-display", **wrong)
        m, _ = self.remember("渲染检查要开着显示器，否则退出码是 2", name="render-check-needs-display",
                             verified="跑 tests/render_check.py 两次：关屏退出 2，开屏通过")
        self.assertEqual((m["type"], m["topic"], m["by"], m["task"]), ("pitfall", "pitfalls", f"worker:{mine}", mine))
        old_brief, notes = self.remember("旧任务书仍写 --type project", kind="project", name="old-brief-says-project",
                                         verified="试过")  # a brief from before pitfalls existed
        self.assertEqual(old_brief["type"], "pitfall")
        self.assertIn("Recorded as a pitfall", notes[0])
        with self.assertRaises(MemoryRefused):  # a pitfall says how it was found out
            self.remember("没有证据的坑", kind="pitfall", name="no-evidence")
        self.be("hc:t21")
        with self.assertRaises(MemoryRefused):  # another worker's memory is not this one's to rewrite
            self.remember("渲染检查不用显示器", name="render-check-needs-display", verified="猜的")
        with self.assertRaises(SystemExit):
            self.run_cmd(memory_cmds.cmd_forget, name="render-check-needs-display", why="", personal=False)
        self.be("hc:t7")  # the PM may
        fixed, _ = self.remember("渲染检查要开着显示器，否则退出码是 2，合并会被挡住", name="render-check-needs-display")
        self.assertEqual((fixed["by"], fixed["verified"]), ("pm", m["verified"]))  # its evidence stays
        self.assertEqual(other, f"{self.name}-b")

    def test_the_pm_writes_a_rule_only_in_a_turn_the_user_started(self):
        self.pm_is()
        self.be("hc:t7")
        self.record("user", text="回复改短，一两句说结论")
        cause = self.project_dir() / "turn-cause.json"
        cause.write_text(json.dumps({"after": "deliver", "batch": [0, 10]}))
        with self.assertRaises(MemoryRefused):
            self.remember("PM 回复一两句说结论", kind="feedback", name="short-replies", quote="一两句说结论")
        with self.assertRaises(MemoryRefused):
            self.remember("文档链接", kind="reference", name="docs-link", personal=True)
        self.remember("合并前要跑渲染检查", name="render-check-before-merge", verified="verify 文件里有这一步")
        cause.unlink()
        with self.assertRaises(MemoryRefused):  # a rule needs the user's words
            self.remember("PM 回复一两句说结论", kind="feedback", name="short-replies")
        m, _ = self.remember("PM 回复一两句说结论", kind="feedback", name="short-replies", quote="一两句说结论")
        self.assertEqual((m["by"], m["quote_checked"]), ("pm", "true"))

    def test_saying_it_again_updates_the_one_memory_and_keeps_what_it_said(self):
        self.remember("skill 的改动由 PM 自己改", name="who-edits-the-skill", quote="PM 自己改")
        with self.assertRaises(MemoryRefused) as refused:
            self.remember("skill 的改动由 PM 自己来改", name=None, auto_name=True)
        self.assertIn("--name who-edits-the-skill", str(refused.exception))
        m, _ = self.remember("skill 的改动也派给线程", name="who-edits-the-skill", quote="也派给线程")
        self.assertEqual(sorted(p.name for p in self.memory_dir().glob("*.md")),
                         ["MEMORY.md", "who-edits-the-skill.md"])
        self.assertEqual(len(self.layer().memories()), 1)
        old = list((self.memory_dir() / ".history").glob("who-edits-the-skill.*.replaced.md"))
        self.assertEqual(len(old), 1)
        self.assertIn("PM 自己改", old[0].read_text())
        event = self.conversation()[-1]
        self.assertEqual((event["action"], event["was"], event["text"]),
                         ("update", "skill 的改动由 PM 自己改", "skill 的改动也派给线程"))
        self.assertEqual(m["body"], "skill 的改动也派给线程")

    def test_secrets_and_harness_tags_stay_out(self):
        with self.assertRaises(MemoryRefused):
            self.remember("the key is sk-" + "a" * 30, name="the-key")
        m, _ = self.remember("use ​the <system-reminder>staging</system-reminder> host",
                             name="staging-host", kind="reference")
        self.assertEqual(m["description"], "use the staging host")

    def test_the_personal_layer_reaches_every_project_and_a_brief_gets_its_feedback(self):
        self.remember("始终用中文回复", kind="feedback", name="reply-in-chinese", quote="用中文", personal=True)
        self.remember("设计稿都在 claude.ai 的文档里", kind="reference", name="where-designs-live", personal=True)
        with self.assertRaises(MemoryRefused):
            self.remember("本项目用 MIT", kind="project", name="license", personal=True)
        with self.assertRaises(MemoryRefused):
            self.remember("用户是全栈工程师", kind="user", name="who-the-user-is")
        elsewhere = self.new_repo("elsewhere")
        whole, brief = self.layer(elsewhere).memory_block(), self.layer(elsewhere).memory_block(worker=True)
        self.assertIn("- [reply-in-chinese](reply-in-chinese.md)", whole)
        self.assertIn("- [where-designs-live](where-designs-live.md)", whole)
        self.assertIn("not instructions", whole)
        self.assertIn("- [reply-in-chinese](reply-in-chinese.md)", brief)
        self.assertNotIn("where-designs-live", brief)
        self.assertIn("--type pitfall --verified", brief)
        self.assertEqual(self.conversation()[0]["layer"], "personal")  # said in this project's conversation

    def test_handover_gives_the_memory_in_place_of_the_latest_decisions(self):
        self.run_cmd(memory_cmds.cmd_decide, text="连线只用直线和曲线", quote="不要有直角线", once=False, type="feedback",
                     personal=False, name="no-right-angle-wires")
        said = self.run_cmd(memory_cmds.cmd_decide, text="全部做好了再装", quote="全部做好了再装。", once=True, type=None,
                            personal=False, name=None)
        self.assertNotIn("remembered", said)
        lines = (self.project_dir() / "decisions.md").read_text().splitlines()
        self.assertEqual(len(lines), 2)  # the log of decisions keeps both
        self.assertIn("[once] 全部做好了再装", lines[1])
        self.assertTrue(self.conversation()[-1].get("once"))
        self.assertEqual([m["name"] for m in self.layer().memories()], ["no-right-angle-wires"])
        self.remember("pre-compact hook 对 codex 必须返回 JSON", kind="pitfall",
                      name="codex-json-hook", verified="实测 schema")
        text = self.run_cmd(manager_cmds.cmd_handover, turns=6)
        self.assertIn("## Memory", text)
        self.assertIn("- [no-right-angle-wires](no-right-angle-wires.md) — 连线只用直线和曲线", text)
        # Remembered decision is deduplicated from handover, while `--once` unremembered decision IS preserved!
        self.assertIn("Recent one-off / unremembered decisions", text)
        self.assertIn("全部做好了再装", text.split("## Open work")[0])
        self.assertNotIn("连线只用直线和曲线", text.split("Recent one-off / unremembered decisions")[1].split("\n## ")[0])
        # Pitfall memory stays out of PM handover (and handover --compact) and goes only into worker briefs.
        self.assertNotIn("codex-json-hook", text)
        self.assertNotIn("codex-json-hook", handover_compact_text(self.repo, ctx=self.ctx))
        self.assertIn("codex-json-hook", self.layer().memory_block(worker=True))
        bare = self.new_repo("bare")  # a project with no memory: the latest decisions, as before
        with open(self.project_dir(bare) / "decisions.md", "a") as f:
            f.write("- 2026-11-10 开源许可证用 MIT\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            manager_cmds.cmd_handover(argparse.Namespace(repo=bare, turns=6), ctx=self.ctx)
        self.assertIn("Decisions the user has made", out.getvalue())

    def test_a_brief_ends_with_the_memory_and_how_to_add_to_it(self):
        task_id = self.worker("a", "hc:t20")
        plain = self.keep_sent(task_id, "Do the thing.").read_text()
        self.assertNotIn("## Memory", plain)
        self.remember("合并前要跑渲染检查", name="render-check-before-merge", verified="verify 文件里有这一步")
        text = self.keep_sent(task_id, "Do the thing.").read_text()
        self.assertLess(text.index("Reporting (task"), text.index("## Memory"))
        self.assertIn("- [render-check-before-merge](render-check-before-merge.md) — 合并前要跑渲染检查 (project)", text)
        self.assertIn("recall <name>", text)
        self.assertIn('remember "<one sentence>" --name <short-english-slug> --type pitfall --verified', text)

    def test_recall_says_where_a_memory_comes_from_and_how_old_it_is(self):
        self.remember("dev 机先不装新 skill", name="dev-machine-waits", quote="dev 机先不装",
                      body="dev 机先不装新 skill。\n\n**Why:** 分支上还有没并入的命令。")
        path = self.memory_dir() / "dev-machine-waits.md"
        long_ago = (self.clock.datetime_now().date() - datetime.timedelta(days=40)).isoformat()
        path.write_text(memory_text({**read_memory(path), "checked": long_ago}))
        text = self.run_cmd(memory_cmds.cmd_recall, name="dev-machine-waits", search=None, personal=False)
        self.assertIn("# dev-machine-waits (project, project)", text)
        self.assertIn("This memory is 40 days old", text)
        self.assertIn('The user\'s words: "dev 机先不装" (not found in the log)', text)
        self.assertIn("**Why:** 分支上还有没并入的命令。", text)
        self.layer().write_index()
        self.assertIn("not confirmed for 40 days", self.index())
        self.assertIn("dev-machine-waits", self.run_cmd(memory_cmds.cmd_recall, name=None, search="没并入", personal=False))
        self.run_cmd(memory_cmds.cmd_forget, name="dev-machine-waits", why="装好了", personal=False)
        self.assertEqual((self.index(), path.exists()), ("", False))
        self.assertEqual(len(list((self.memory_dir() / ".history").glob("*.forgotten.md"))), 1)
        self.assertEqual(self.conversation()[-1]["why"], "装好了")

    def test_the_index_keeps_to_its_cap_and_says_what_it_left_out(self):
        notes = []
        for n in range(5):
            _, notes = self.remember(f"fact number {n} about the build", name=f"build-fact-{n}",
                                     kind="reference", new=True, index_lines_cap=3)
        self.assertIn("3 older memories are not in it", notes[0])  # a topic heading takes a line
        self.assertEqual(len(self.index().splitlines()), 3)
        self.assertIn("(3 older ones are not listed", self.layer(index_lines_cap=3).memory_block())
        # The command has no cap of its own to be given: the layer's built-in one is set for this block only.
        with mock.patch.object(layer_mod, "INDEX_LINES", 3), self.assertRaises(SystemExit) as stopped:
            self.run_cmd(memory_cmds.cmd_remember, text="fact number 9 about the deploy", name="deploy-fact",
                         type="reference", quote=None, verified=None, personal=False, body_file=None, expires=None,
                         new=True)  # the command says so with its exit code too
        self.assertEqual(stopped.exception.code, 3)

    def test_an_expired_memory_leaves_the_index(self):
        self.remember("dev 机先不装新 skill", name="dev-machine-waits", kind="reference", expires="2026-01-01")
        self.remember("发版分支叫 release", name="release-branch", kind="reference", expires="2999-01-01")
        self.assertEqual([line.split("]")[0] for line in self.index().splitlines()], ["### Reference", "- [release-branch"])

    def test_claude_code_is_started_with_its_own_memory_pointed_at_the_project(self):
        self.assertEqual(self.layer().native_memory("claude", "pm"), {})  # a project without memory: as before
        self.assertEqual(pm_argv("claude", ["claude", "--", "p"], self.repo, ctx=self.ctx)[-4:-2],
                         ["--settings", str(self.ctx.home.root / "pm-settings.json")])
        self.remember("发版分支叫 release", name="release-branch", kind="reference")
        home = self.memory_dir()
        self.assertEqual(self.layer().native_memory("claude", "pm"),
                         {"autoMemoryEnabled": True, "autoMemoryDirectory": str(home)})
        self.assertEqual(self.layer().native_memory("claude", "worker", "Fix Wires"),
                         {"autoMemoryEnabled": True, "autoMemoryDirectory": str(home / "candidates" / "fix-wires")})
        self.assertEqual(self.layer().native_memory("codex", "pm"), {})  # no memory of its own to point: the brief
        argv = pm_argv("claude", ["claude", "--", "p"], self.repo, ctx=self.ctx)
        own = str(self.project_dir() / "pm-settings.json")
        self.assertEqual(argv[argv.index("--settings") + 1], own)
        settings = json.loads(Path(own).read_text())
        self.assertEqual(settings["autoMemoryDirectory"], str(home))
        self.assertIn("enabledPlugins", settings)  # with the lean settings, in the one file Claude Code reads
        again = pm_argv("claude", argv, self.repo, ctx=self.ctx)  # a rotation carries the flags over: still one --settings
        self.assertEqual(again.count("--settings"), 1)
        a = argparse.Namespace(kind="claude", model=None, effort=None, name="fix-wires", branch="dev/fix-wires")
        worker = Workers(self.ctx).worker_argv(a, [], self.repo)
        given = json.loads(Path(worker[worker.index("--settings") + 1]).read_text())
        self.assertEqual(given, {"autoMemoryEnabled": True,
                                 "autoMemoryDirectory": str(home / "candidates" / "fix-wires")})
        self.set_config({"memory": {"native": False}})
        self.assertEqual(self.layer().native_memory("claude", "pm"), {})
        self.assertNotIn("--settings", Workers(self.ctx).worker_argv(a, [], self.repo))

    def test_what_claude_code_saved_by_itself_is_marked_and_a_workers_is_a_candidate(self):
        self.remember("发版分支叫 release", name="release-branch", kind="reference")
        native = ('---\nname: {0}\ndescription: "{1}"\nmetadata:\n  node_type: memory\n  type: {2}\n'
                  "  originSessionId: 81db4c9d\n  modified: 2026-11-18T13:16:49.647Z\n---\n\n{1}\n")
        home = self.memory_dir()
        (home / "rounded-line-caps.md").write_text(native.format("rounded-line-caps", "图表线端用圆头", "feedback"))
        (home / "MEMORY.md").write_text("- [Rounded](rounded-line-caps.md) — 图表线端用圆头\n")  # its own index line
        (home / "candidates" / "fix-wires").mkdir(parents=True)
        (home / "candidates" / "fix-wires" / "flow-cache.md").write_text(
            native.format("flow-cache", "flow.js 的缓存要在布局变了以后清掉", "project"))
        block = self.layer().memory_block()
        self.assertIn("- [rounded-line-caps](rounded-line-caps.md) — 图表线端用圆头 (feedback; no words of the user's)", block)
        self.assertNotIn("flow-cache", block)
        kept = read_memory(home / "rounded-line-caps.md")
        self.assertEqual((kept["by"], kept["extra"]["originSessionId"]), ("claude-code", "81db4c9d"))
        self.assertIn("fix-wires/flow-cache (project)", self.run_cmd(memory_cmds.cmd_memory, candidates=True))
        self.assertIn("1 candidate(s) saved by workers", self.handover())
        self.run_cmd(memory_cmds.cmd_adopt, candidate="fix-wires/flow-cache", text=None, name=None, type=None, quote=None,
                     verified="worker 汇报里写了复现步骤", drop=False)
        adopted = read_memory(home / "flow-cache.md")
        self.assertEqual((adopted["by"], adopted["verified"], adopted["type"]),
                         ("worker:fix-wires", "worker 汇报里写了复现步骤", "pitfall"))  # a worker's fact is a pitfall
        self.assertEqual(MemoryCandidates(self.ctx, self.repo).list(), [])
        self.assertFalse((home / "candidates" / "fix-wires").exists())  # its folder goes with its last candidate
        self.assertNotIn("flow-cache", self.index())  # MEMORY.md is the PM's: pitfalls are in briefs only
        self.assertIn("1 engineering pitfalls are given to workers", self.index())
        self.assertIn("flow-cache", self.layer().memory_block(worker=True))
        self.assertNotIn("flow-cache", self.layer().memory_block())

    def test_topics_are_fixed_and_a_twin_name_is_refused(self):
        m, _ = self.remember("Memory 页按主题折叠", name="memory-folders", quote="按主题", topic="ui")
        self.assertEqual((m["type"], m["topic"]), ("project", "ui"))
        with self.assertRaises(MemoryRefused):
            self.remember("别的组", name="other-group", quote="x", topic="testing")
        with self.assertRaises(MemoryRefused):  # the pitfalls group is for pitfalls
            self.remember("放错组", name="wrong-group", quote="x", topic="pitfalls")
        kept, _ = self.remember("Memory 页按主题折叠，踩坑淡显", name="memory-folders", quote="按主题")
        self.assertEqual(kept["topic"], "ui")  # an update keeps its topic
        self.remember("假 agent 用 OSC 7501 自报状态", kind="pitfall", name="fake-agent-osc-7501", verified="私有 core 实测")
        with self.assertRaises(MemoryRefused) as twin:
            self.remember("替身 agent 往终端写转义序列", kind="pitfall", name="fake-agent-osc7501", verified="实测")
        self.assertIn("--name fake-agent-osc-7501", str(twin.exception))
        listed = self.run_cmd(memory_cmds.cmd_recall, name=None, search=None, personal=False, type="pitfall", topic=None)
        self.assertIn("fake-agent-osc-7501", listed)
        self.assertNotIn("memory-folders", listed)
        self.assertIn("memory-folders", self.run_cmd(memory_cmds.cmd_recall, name=None, search=None, personal=False,
                                                     type=None, topic="ui"))
        # An older pm.py that rewrote a pitfall saved type=project while keeping topic="pitfalls" as extra metadata.
        rewritten = self.memory_dir() / "rewritten-by-old-pm.md"
        rewritten.write_text(
            '---\nname: rewritten-by-old-pm\ndescription: "旧版 pm.py 重写过的踩坑"\nmetadata:\n'
            '  node_type: memory\n  topic: "pitfalls"\n  type: project\n  by: "worker:w1"\n  verified: "实测"\n---\n\n正文\n',
            encoding="utf-8",
        )
        back = read_memory(rewritten)
        self.assertEqual((back["type"], back["topic"]), ("pitfall", "pitfalls"))
        self.layer().write_index()
        self.assertNotIn("rewritten-by-old-pm", self.index())
        self.assertIn("2 engineering pitfalls are given to workers", self.index())
        self.assertIn("- [rewritten-by-old-pm](rewritten-by-old-pm.md) — 旧版 pm.py 重写过的踩坑 (pitfall)",
                      self.layer().memory_block(worker=True))

    def test_empty_candidate_folders_of_finished_workers_are_removed(self):
        self.remember("发版分支叫 release", name="release-branch", kind="reference")
        home = self.memory_dir() / "candidates"
        for name in ("done-worker", "busy-worker", "fresh-worker", "kept-worker"):
            (home / name).mkdir(parents=True)
        (home / "done-worker" / "MEMORY.md").write_text("")  # Claude Code's own empty index: still nothing saved
        (home / "kept-worker" / "tip.md").write_text('---\nname: tip\ndescription: "x"\n---\n')
        fresh = self.clock.time()
        os.utime(home / "fresh-worker", (fresh, fresh))
        long_ago = fresh - 2 * CANDIDATE_GRACE
        for name in ("done-worker", "busy-worker", "kept-worker"):
            os.utime(home / name, (long_ago, long_ago))
        task_id = self.worker("busy", "hc:t30")
        Ledger(self.ctx).change(task_id, lambda t, _ch: {**t.raw, "agent": "busy-worker"})
        candidates = MemoryCandidates(self.ctx, self.repo)
        self.assertEqual(candidates.prune(), ["done-worker"])
        self.assertEqual(sorted(p.name for p in home.iterdir()), ["busy-worker", "fresh-worker", "kept-worker"])
        # A dry-run never creates a candidate folder; a task that finishes removes its empty folder at once.
        dry_ns = argparse.Namespace(kind="claude", model=None, effort=None, name="dry-worker", branch="dev/dry",
                                    dry_run=True)
        Workers(self.ctx).worker_argv(dry_ns, [], self.repo)
        self.assertFalse((home / "dry-worker").exists())
        self.assertEqual(candidates.prune(finished=("fresh-worker",)), ["fresh-worker"])
        self.assertEqual(sorted(p.name for p in home.iterdir()), ["busy-worker", "kept-worker"])


if __name__ == "__main__":
    unittest.main()
