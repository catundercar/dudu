"""Ledger transitions through the commands: sub-threads (`parent`), the project conversation, per-project task
numbers, two-layer plans with plan-driven auto-review, and post-merge land.

Moved from test_pm.py `SubThreads`, `ConversationLog`, `TaskNumbersTests` and `TwoLayerPlanAndAutoReview`
(Stage 6a). Every test runs on its own `make_ctx` Context: its own temporary ledger, a `FakeHc` in place of
herdr-core, a `FakeTui`, `FakeProcs` (which records the deliverer spawns `pm.deliver_later` used to start) and a
real `GitRepo` over throwaway repositories. Commands still reach their services through `legacy_context()`, which
`tests.legacy_bind.bound` points at the test's Context for the call.
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
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-ledger-transitions")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

from pmlib import cli  # noqa: E402
from pmlib import hooks  # noqa: E402
from pmlib.commands import dispatch as dispatch_cmds, ledger as ledger_cmds  # noqa: E402
from pmlib.commands import manager as manager_cmds, memory as memory_cmds  # noqa: E402
from pmlib.commands import review as review_cmds, workers as workers_cmds  # noqa: E402
from pmlib.context import StdOutput  # noqa: E402
from pmlib.errors import NotFound, Refused  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import Home, project_slug  # noqa: E402
from pmlib.ledger.board import Board  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.plan import PLAN_ANCHORS, has_pending_review_step, parse_plan_steps, step_anchor  # noqa: E402
from pmlib.project.conversation import Conversation, log_tail  # noqa: E402
from pmlib.project.project import pm_name  # noqa: E402
from pmlib.project.readmodel import project_lost, task_offline  # noqa: E402
from pmlib.review.land import LAND_REFUSED  # noqa: E402
from pmlib.views import state as state_view, status as status_view  # noqa: E402
from pmlib.workers.service import Workers  # noqa: E402
from tests.fakes import FakeClock, FakeHc, FakeProcs, FakeTui, make_ctx  # noqa: E402

PM_SCRIPT = SCRIPTS / "pm.py"
GIT_IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t"}


class ReviewFailingHc(FakeHc):
    """FakeHc whose `hc run` of a reviewer (a terminal named or labelled for `<id>-review`) fails while
    `review_should_fail` is set; `runs` counts the terminals it did start."""

    review_should_fail = False
    runs = 0

    def run(self, argv, *, name="", cwd="", labels=(), **kw):
        labels = list(labels)
        if self.review_should_fail and any(str(x).endswith("-review") for x in [name, *labels, *argv]):
            return None
        row = super().run(argv, name=name, cwd=cwd, labels=labels, **kw)
        if row is not None:
            self.runs += 1
        return row


class LedgerCase(unittest.TestCase):
    """One temporary ledger, fake terminals and real git per test; `be(pane)` switches the calling session."""

    TERMINALS: dict = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        env_patch = mock.patch.dict(os.environ, GIT_IDENTITY)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.clock = FakeClock(datetime.datetime.now().replace(microsecond=0))
        self.hc = ReviewFailingHc(self.TERMINALS, clock=self.clock)
        self.tui = FakeTui()
        self.wt_root = self.base / "worktrees"
        self.git = GitRepo(worktree_home_fn=lambda repo: self.wt_root / Path(repo).name)
        self.home = Home(self.base / "ledger")
        self.procs = FakeProcs(self.home, env={"PM_HOME": str(self.home.root)})
        self.ctx = self.session("")

    def session(self, pane):
        return make_ctx(self.base, pane=pane, hc=self.hc, tui=self.tui, git=self.git, procs=self.procs,
                        clock=self.clock, out=StdOutput())

    def be(self, pane):
        self.ctx = self.session(pane)

    def plain_dir(self, name="proj"):
        path = self.base / "dirs" / name
        path.mkdir(parents=True)
        return self.git.project_root(path)

    # --- the ledger, as pm.load / pm.save / pm.mutate_task gave it ---

    def load(self, task_id):
        return Ledger(self.ctx).load(task_id)

    def save(self, task):
        Ledger(self.ctx).save(task)

    def change(self, task_id, fn, *, create=False):
        return Ledger(self.ctx).change(task_id, lambda cur, _ch: fn(cur.raw if cur is not None else None),
                                       create=create)

    def started(self):
        """The projects whose deliverer was started (what `pm.deliver_later` was called with)."""
        return [s["args"][1] for s in self.procs.spawned if s["args"][:1] == ["deliver"]]

    def clear_started(self):
        self.procs.spawned[:] = [s for s in self.procs.spawned if s["args"][:1] != ["deliver"]]

    def conversation(self, repo):
        path = Conversation(self.ctx, repo).path
        if not path.exists():
            return []
        events = []
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    # --- commands, on this test's Context ---

    def cmd(self, command, *args, **fields):
        """Run `command(Namespace(**fields))` (or `command(*args)`) on this test's Context; its return value."""
        return command(*args, ctx=self.ctx) if args else command(argparse.Namespace(**fields), ctx=self.ctx)

    def cmd_quiet(self, command, **fields):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.cmd(command, **fields)

    def cmd_out(self, command, **fields):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.cmd(command, **fields)
        return out.getvalue()

    def run_pm(self, *argv):
        """`pm.py <argv>` through the command line's own parser and error handling; stdout and stderr, and
        `exit: <code>` when it exits."""
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['pm.py', *argv]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                cli.main(ctx=self.ctx)
            except SystemExit as stop:
                out.write(f"\nexit: {stop.code}")
        return out.getvalue()


class SubThreads(LedgerCase):
    """A task split into others: each part names it as `parent`, set by new, dispatch or update."""

    def test_new_and_update_set_the_parent_and_state_shows_it(self):
        repo = self.plain_dir()
        whole = self.run_pm("new", "派发时选模型", "--repo", repo, "--pane", "", "--workspace", "").split()[0]
        part = self.run_pm("new", "档位标签", "--repo", repo, "--parent", whole).split()[0]
        old = self.run_pm("new", "老线程", "--repo", repo).split()[0]
        self.assertEqual(self.load(part)["parent"], whole)
        self.assertNotIn("parent", self.load(old))  # none given: no field, as in an older ledger
        self.assertIn("no task nope", self.run_pm("new", "x", "--repo", repo, "--parent", "nope"))
        # An existing task gets its parent afterwards; the log says so.
        self.assertIn(f"{old}: in_progress", self.run_pm("update", old, "--parent", whole))
        task = self.load(old)
        self.assertEqual((task["parent"], task["log"][-1]["text"]), (whole, f"parent={whole}"))
        self.assertIn("loop", self.run_pm("update", old, "--parent", old))       # not its own parent
        self.assertIn("no task", self.run_pm("update", old, "--parent", "nope"))
        self.assertEqual(self.load(old)["parent"], whole)
        n = len(self.load(old)["log"])
        self.run_pm("update", old, "--parent", "")  # an empty value takes it away; on a task without one: nothing
        self.assertNotIn("parent", self.load(old))
        self.run_pm("update", old, "--parent", "")
        self.assertEqual(len(self.load(old)["log"]), n + 1)
        tasks = {t["id"]: t for t in json.loads(self.run_pm("state"))["tasks"]}
        self.assertEqual((tasks[part]["parent"], tasks[old]["parent"], tasks[whole]["parent"]), (whole, "", ""))
        self.assertEqual(tasks[whole]["pane"], "")

    def test_parent_refuses_a_loop_and_anything_but_a_task_id(self):
        repo = self.plain_dir()
        a = self.run_pm("new", "A", "--repo", repo, "--slug", "loop-a").split()[0]
        b = self.run_pm("new", "B", "--repo", repo, "--slug", "loop-b", "--parent", a).split()[0]
        c = self.run_pm("new", "C", "--repo", repo, "--slug", "loop-c", "--parent", b).split()[0]
        self.assertIn("loop", self.run_pm("update", a, "--parent", b))   # A→B→A
        self.assertIn("loop", self.run_pm("update", a, "--parent", c))   # A→C→B→A
        self.assertNotIn("parent", self.load(a))
        for bad in ("../x", "a/b", ".hidden", "x..y", "a b"):
            self.assertIn("not a task id", self.run_pm("update", c, "--parent", bad), bad)
            self.assertIn("not a task id", self.run_pm("new", "D", "--repo", repo, "--parent", bad), bad)
        self.assertEqual(self.load(c)["parent"], b)
        self.assertIn(f"{c}: in_progress", self.run_pm("update", c, "--parent", a))  # no loop: fine

    def test_state_keeps_the_retired_parts_of_a_task_on_the_board_apart(self):
        repo = self.plain_dir()
        name = Path(repo).name
        base = {"project": name, "repo": repo, "owner": "pm", "base": "main", "created": self.clock.now()}
        self.save({**base, "id": f"{name}-whole", "title": "总任务", "status": "in_progress"})
        self.save({**base, "id": f"{name}-done", "title": "合并了", "status": "merged", "parent": f"{name}-whole",
                   "retired": "2026-11-15 01:00"})
        self.save({**base, "id": f"{name}-live", "title": "进行中", "status": "in_progress", "parent": f"{name}-whole"})
        self.save({**base, "id": f"{name}-gone", "title": "父任务已结束", "status": "merged", "retired": "x"})
        self.save({**base, "id": f"{name}-orphan", "title": "孤儿", "status": "merged", "retired": "x",
                   "parent": f"{name}-gone"})  # its parent is off the board: not kept
        state = json.loads(self.run_pm("state"))
        ids = {t["id"] for t in state["tasks"]}
        self.assertNotIn(f"{name}-done", ids)  # the board and its counts see what they saw before
        parts = {t["id"]: t for t in state["retired_parts"]}
        self.assertNotIn(f"{name}-orphan", parts)
        self.assertNotIn(f"{name}-live", parts)  # on the board already
        self.assertEqual({k: parts[f"{name}-done"][k] for k in ("title", "status", "parent", "retired")},
                         {"title": "合并了", "status": "merged", "parent": f"{name}-whole", "retired": True})

    def test_state_keeps_the_worker_marks_of_the_newest_ended_tasks_off_the_board(self):
        repo = self.plain_dir()
        name = Path(repo).name
        pms, tasks_dir = self.ctx.home.registrations, self.ctx.home.tasks
        pms.mkdir(parents=True, exist_ok=True)
        (pms / f"pm-{name}.json").write_text(json.dumps({"name": f"pm-{name}", "project": name, "repo": repo}))
        tasks_dir.mkdir(parents=True, exist_ok=True)
        # written as the ledger has them (a save would stamp them updated now)
        put = lambda t: (tasks_dir / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False))
        base = {"project": name, "repo": repo, "owner": "pm", "base": "main", "created": self.clock.now(),
                "retired": "x"}
        hard = {"profile": "hard", "kind": "claude", "model": "opus", "effort": "xhigh", "advisor": "fable"}
        put({**base, "id": f"{name}-up", "title": "升级过", "status": "merged", "updated": "2026-11-15 09:00",
             "worker": hard, "escalations": [{"from": "standard", "to": "hard", "why": "x", "at": "x"}]})
        put({**base, "id": f"{name}-plain", "title": "默认", "status": "merged", "updated": "2026-11-15 08:00",
             "worker": {"profile": "standard", "kind": "claude", "model": "opus", "effort": "", "advisor": ""}})
        put({**base, "id": f"{name}-dropped", "title": "放弃了", "status": "abandoned", "updated": "2026-11-15 10:00",
             "worker": hard})
        put({**base, "id": f"{name}-byhand", "title": "手登记", "status": "done", "updated": "2026-11-15 10:00"})
        for i in range(state_view.ENDED_ENGINES):
            put({**base, "id": f"{name}-old{i}", "title": "早的", "status": "merged",
                 "updated": f"2026-11-0{i % 9 + 1} 08:00", "worker": {"kind": "codex"}})
        marks = json.loads(self.run_pm("state"))["ended_engines"]
        self.assertEqual(marks[f"{name}-up"], {**hard, "escalated": 1})
        self.assertEqual(marks[f"{name}-plain"], {"profile": "standard", "kind": "claude", "model": "opus"})
        self.assertNotIn(f"{name}-dropped", marks)  # given up: not listed as ended
        self.assertNotIn(f"{name}-byhand", marks)  # no worker record: nothing to say
        mine = [k for k in marks if k.startswith(f"{name}-")]
        self.assertEqual(len(mine), state_view.ENDED_ENGINES)  # the newest few of this PM only
        self.assertNotIn(f"{name}-old0", mine)


class ConversationLog(LedgerCase):
    """The conversation belongs to the project: a session appends to it, a fresh one reads it."""

    def test_turn_hook_keeps_what_was_said_in_a_pm_session(self):
        repo = self.plain_dir()
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        (self.ctx.home.registrations / "c.json").write_text(
            json.dumps({"name": "pm-c", "pane": "hc:t7", "project": "c", "repo": repo}))
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
        for who, event, payload in turns:
            self.be(who)
            stdin = io.StringIO(json.dumps({"hook_event_name": event, **payload}))
            with mock.patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(io.StringIO()):
                self.cmd(hooks.cmd_hook_turn, None)
        events = self.conversation(repo)
        self.assertEqual([(e["type"], e["text"]) for e in events],
                         [("user", "先做看板"), ("pm", "好，已派出。"), ("user", "[Image #1] 这里不对"),
                          ("agent", "task x is ready"), ("agent", "要不要兼容旧版？"), ("user", "/Users/me/a.png 看下")])
        self.assertEqual([e["by"] for e in events[3:5]], ["hc:t3", "hc:t5"])
        self.assertEqual(events[1]["by"], "hc:t7")                      # which session spoke

    def test_ledger_entries_and_decisions_join_the_log_and_a_handover_reads_it(self):
        repo = self.plain_dir()
        name = Path(repo).name
        talk = Conversation(self.ctx, repo)
        talk.record("user", text="连线别用直角")
        talk.record("pm", text="记下了，已派给 worker。")
        talk.record("agent", by="hc:t3", text="task wires is ready")
        talk.record("pm", text="收到，开始审查。")  # answers the worker, not the user
        with open(self.ctx.home.project_for(repo).ensure() / "conversation.jsonl", "a") as f:
            f.write('null\n[]\nnot json\n{"type": "pm", "text": null}\n')  # stray lines must not break a handover
        task = {"id": f"{name}-wires", "title": "改连线", "project": name, "repo": repo, "status": "in_progress",
                "owner": "pm", "base": "main", "created": self.clock.now()}
        Ledger(self.ctx).append_note(task, "dispatched to w1")
        self.save(task)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.cmd(memory_cmds.cmd_decide, type("A", (), {"repo": repo, "text": "连线不用直角", "quote": "别用直角"}))
            self.cmd(manager_cmds.cmd_handover, type("A", (), {"repo": repo, "turns": 6}))
            self.cmd(ledger_cmds.cmd_conversation,
                     type("A", (), {"repo": repo, "last": 20, "type": "thread,decision", "width": 300}))
        events = self.conversation(repo)
        self.assertEqual([e["type"] for e in events],
                         ["user", "pm", "agent", "pm", "pm", "thread", "decision", "memory"])  # a decision is remembered
        self.assertEqual((events[5]["task"], events[5]["status"], events[5]["text"]),
                         (f"{name}-wires", "in_progress", "dispatched to w1"))
        text = out.getvalue()
        self.assertIn("User: 连线别用直角\nPM: 记下了，已派给 worker。", text)  # the handover, with no transcript at all
        self.assertNotIn("收到，开始审查。", text)
        self.assertIn(f"[{name}-wires · in_progress]", text)                    # the conversation command
        self.assertIn('连线不用直角 — "别用直角"', text)

    def test_a_user_turn_is_paired_with_its_own_reply_only(self):
        repo = self.plain_dir()
        talk = Conversation(self.ctx, repo)
        for kind, text in (("user", "A"), ("pm", "reply to A"), ("pm", "a background wait finished"),
                           ("user", "B"), ("agent", "a worker reports"), ("pm", "answers the worker"),
                           ("user", "C")):
            talk.record(kind, text=text)
        tail = talk.tail()
        self.assertEqual(tail, [{"user": "A", "pm": "reply to A"}, {"user": "B", "pm": ""},
                                {"user": "C", "pm": ""}])


def init_repo(path):
    """A git repository at `path` with one commit on main."""
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *args: subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (path / "README.md").write_text("hi\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "init")
    return str(path.resolve())


class TaskNumbersTests(LedgerCase):
    TERMINALS = {"t30": {"state": "live", "turn": 3}}

    def setUp(self):
        super().setUp()
        for d in (self.home.tasks, self.home.registrations, self.home.projects, self.home.inbox):
            d.mkdir(parents=True, exist_ok=True)
        self.repo_a = init_repo(self.base / "alpha")
        self.repo_b = init_repo(self.base / "beta")
        # Register PMs so the store's registration index resolves slugs with real PM registrations present.
        for slug, repo, term in (("alpha", self.repo_a, "t10"), ("beta", self.repo_b, "t20")):
            self.ctx.store.change_registration(slug, lambda _cur, s=slug, r=repo, t=term: {
                "project": s, "repo": r, "name": f"pm-{s}", "runtime": "hc", "terminal": t, "pane": f"hc:{t}",
            })

    def _new(self, repo, title, **kw):
        ns = argparse.Namespace(
            repo=repo, title=title, status=kw.get("status", "in_progress"), base=None, owner=None,
            workspace=None, pane=kw.get("pane", "hc:t30"), agent=None, branch=kw.get("branch"),
            worktree=kw.get("worktree"), brief=kw.get("brief"), kind=None, slug=kw.get("slug"),
            note=kw.get("note", "init"), option=None, parent=kw.get("parent"),
            plan=kw.get("plan"), step=None, outer_plan=None, no_review=kw.get("no_review", False),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            return self.cmd(ledger_cmds.cmd_new, ns)

    def test_new_allocates_per_project_numbers_and_subtasks_get_own_numbers(self):
        a1 = self._new(self.repo_a, "First Alpha", branch="dev/a1")
        a2 = self._new(self.repo_a, "Child Alpha", branch="dev/a2", parent="#1")
        b1 = self._new(self.repo_b, "First Beta", branch="dev/b1")
        self.assertEqual(self.load(a1)["number"], 1)
        self.assertEqual(self.load(a2)["number"], 2)
        self.assertEqual(self.load(a2)["parent"], a1)  # stored parent remains canonical slug
        self.assertEqual(self.load(b1)["number"], 1)

        # dispatch --dry-run never burns a sequence number
        brief = self.base / "brief.md"
        brief.write_text("do work\n", encoding="utf-8")
        self.cmd_quiet(
            dispatch_cmds.cmd_dispatch,
            repo=self.repo_a, title="Dry", branch="dev/dry", label="dry", brief=str(brief), path=None,
            name=None, task=None, here=False, tab=None, bug=None, codex_profile=None, dry_run=True,
            base=None, prep=None, parent="#1", profile="standard", kind=None, model=None, effort=None,
            advisor=None, confirmed=False, plan=None, step=None, outer_plan=None, no_review=False, async_=False,
        )
        a3 = self._new(self.repo_a, "Third Alpha", branch="dev/a3")
        self.assertEqual(self.load(a3)["number"], 3)

        # Rename & reparent preserve immutable number.
        self.cmd_quiet(ledger_cmds.cmd_update, id="#2", title="Renamed Child", parent="", status=None,
                       note="renamed", send=False, ask=False)
        t2 = self.load(a2)
        self.assertEqual((t2["number"], t2["title"], t2.get("parent")), (2, "Renamed Child", None))

    def test_cli_resolution_scoping_ambiguity_and_reviews(self):
        a1 = self._new(self.repo_a, "Fix auth", branch="dev/a1", worktree=self.repo_a)
        b1 = self._new(self.repo_b, "Fix api", branch="dev/b1", worktree=self.repo_b)
        # Create a review thread tied to alpha#1 without allocating a sequence slot.
        rev_id = f"{a1}-review"
        now = self.clock.now()
        self.change(rev_id, lambda _cur: {
            "id": rev_id, "title": "Review: Fix auth", "project": "alpha", "repo": self.repo_a,
            "status": "in_progress", "base": "main", "owner": "pm", "review_of": a1,
            "pane": "hc:t40", "created": now, "log": [{"at": now, "by": "hc:t40", "text": "reviewing"}],
        }, create=True)
        ledger = Ledger(self.ctx)
        self.assertIsNone(self.load(rev_id).get("number"))
        self.assertEqual(ledger.task_num_label(self.load(rev_id)), "#1-review")

        # Ambiguous bare #1 across two registered projects when cwd is outside both repos.
        orig_cwd = os.getcwd()
        os.chdir(self.base)
        try:
            with self.assertRaises((SystemExit, Refused)) as amb:
                self.load("#1")
            self.assertIn("ambiguous task reference #1", str(amb.exception))
            self.assertEqual(ledger.resolve_id("alpha#1"), a1)
            self.assertEqual(ledger.resolve_id("beta#1"), b1)
            self.assertEqual(ledger.resolve_id("alpha#1-review"), rev_id)

            # Inside alpha repo, bare #1, 1, #1-review resolve within alpha only.
            os.chdir(self.repo_a)
            self.assertEqual(ledger.resolve_id("#1"), a1)
            self.assertEqual(ledger.resolve_id("1"), a1)
            self.assertEqual(ledger.resolve_id("#1-review"), rev_id)
            with self.assertRaises((SystemExit, NotFound)) as miss:
                self.load("#99")
            self.assertIn("no task #99 in project alpha", str(miss.exception))
        finally:
            os.chdir(orig_cwd)

        # CLI commands & mention_hints accept numeric references.
        self.assertIn(f"#1 {a1}", self.cmd_out(status_view.cmd_show, id="alpha#1", json=False))

        self.cmd(status_view.cmd_log, id="alpha#1", text="logged via project#num")
        self.assertEqual(self.load(a1)["log"][-1]["text"], "logged via project#num")

        self.cmd_quiet(workers_cmds.cmd_send, target="alpha#1", message="ping worker", file=None, task=None, repo=".",
                       timeout=10, wait=False)
        sends = [s["args"] for s in self.procs.spawned if s["args"][:1] == ["_deliver-send"]]
        self.assertEqual([(a[1], a[a.index("--task") + 1]) for a in sends], [("t30", a1)])  # handed to the background

        hints = hooks.mention_hints(self.repo_a, f"check [@Fix](thread:{a1}) and [alt](thread:#1)", ctx=self.ctx)
        self.assertTrue(any("#1; Fix auth" in h for h in hints))

    def test_outputs_state_board_deliver_and_legacy_peer_compatibility(self):
        a1 = self._new(self.repo_a, "Parent Epic", branch="dev/ep")
        a2 = self._new(self.repo_a, "Sub Task", branch="dev/sub", parent=a1)
        rev_id = f"{a1}-review"
        now = self.clock.now()
        self.change(rev_id, lambda _cur: {
            "id": rev_id, "title": "Review: Parent Epic", "project": "alpha", "repo": self.repo_a,
            "status": "done", "base": "main", "owner": "pm", "review_of": a1,
            "created": now, "log": [{"at": now, "by": "hc:t41", "text": "status=done; no blockers"}],
        }, create=True)
        # Closed retired child + legacy unnumbered closed task
        a3_closed = self._new(self.repo_a, "Retired Sub", branch="dev/old", parent=a1, status="merged")
        self.change(a3_closed, lambda cur: {**cur, "retired": True, "updated": "2020-01-01 00:00"})
        legacy_id = "alpha-legacy"
        self.ctx.store.change_task(legacy_id, lambda _c: {
            "id": legacy_id, "title": "Legacy Peer Task", "project": "alpha", "repo": self.repo_a,
            "status": "in_progress", "base": "main", "owner": "pm", "updated": now, "log": [],
        })

        # report_section includes number when numbered, omits when task absent.
        workers = Workers(self.ctx)
        self.assertIn(f"Reporting (task #1 {a1}):", workers.report_section(a1))
        self.assertIn("Reporting (task p-missing):", workers.report_section("p-missing"))

        # show includes parent number; status & handover & BOARD & batch_text include #N and #N-review.
        show_out = self.cmd_out(status_view.cmd_show, id=a2, json=False)
        self.assertIn(f"#2 {a2}", show_out)
        self.assertIn(f"parent=#1 {a1}", show_out)

        st_out = self.cmd_out(status_view.cmd_status, repo=self.repo_a, all=False, closed=True)
        self.assertIn(f"#1 {a1}", st_out)
        self.assertIn(f"#1-review {rev_id}", st_out)
        self.assertIn(f"[in_progress] {legacy_id}", st_out)

        for flags in ({"full": False, "compact": False}, {"full": False, "compact": True}, {"full": True, "compact": False}):
            self.assertIn(f"#1 {a1}", self.cmd_out(manager_cmds.cmd_handover, repo=self.repo_a, turns=4, **flags))

        board = Board(self.ctx).write(tasks=[t.raw for t in Ledger(self.ctx).all_tasks()])
        board_md = board.read_text(encoding="utf-8")
        self.assertEqual(board, self.ctx.home.board)
        self.assertIn(f"| #1 Parent Epic (`{a1}`) |", board_md)
        self.assertIn(f"| #1-review Review: Parent Epic (`{rev_id}`) |", board_md)

        ev_batch = Delivery(self.ctx, "").batch_text(0, 100, [
            {"event": {"type": "thread", "task": a1, "status": "review", "by": "hc:t30", "text": "done"}, "earlier": 0},
            {"event": {"type": "thread", "task": rev_id, "review_of": a1, "worker_commit": "abc", "worker_note": "ok",
                       "status": "done", "by": "hc:t41", "text": "no blockers"}, "earlier": 0},
        ])
        self.assertIn(f"#1 {a1}: review", ev_batch)
        self.assertIn(f"#1-review {rev_id} -> #1 {a1}: done", ev_batch)

        # dash_state & project_lost
        st = state_view.dash_state(ctx=self.ctx)
        by_id = {t["id"]: t for t in st["tasks"]}
        self.assertEqual(by_id[a1]["number"], 1)
        self.assertNotIn("number", by_id[rev_id])
        self.assertNotIn("number", by_id[legacy_id])
        self.assertEqual(st["task_numbers"][a3_closed], 3)
        parts_by_id = {p["id"]: p for p in st["retired_parts"]}
        self.assertEqual(parts_by_id[a3_closed]["number"], 3)

        lost = project_lost(
            {"project": "alpha", "repo": self.repo_a, "name": "pm-alpha", "terminal": "t10"},
            [t.raw for t in Ledger(self.ctx).all_tasks()], pms=None, pm_alive=True, hc_live=set(), ended={},
        )
        self.assertEqual(lost["threads"][0]["number"], 1)

    def test_cmd_backfill_numbers_creates_verified_backup_and_is_idempotent(self):
        legacy_a = "alpha-unnum-1"
        legacy_b = "alpha-unnum-2"
        self.ctx.store.change_task(legacy_a, lambda _c: {
            "id": legacy_a, "title": "First", "project": "alpha", "repo": self.repo_a,
            "status": "in_progress", "base": "main", "owner": "pm", "created": "2026-10-01 09:00",
            "updated": "2026-10-10 09:00", "log": [],
        })
        self.ctx.store.change_task(legacy_b, lambda _c: {
            "id": legacy_b, "title": "Second", "project": "alpha", "repo": self.repo_a,
            "status": "in_progress", "base": "main", "owner": "pm", "created": "2026-10-02 09:00",
            "updated": "2026-10-05 09:00", "log": [],
        })
        backup_dir = self.base / "backups"

        # Invalid backup_dir inside PM_HOME refused
        with self.assertRaises(SystemExit):
            self.cmd(ledger_cmds.cmd_backfill_numbers, project="alpha", dry_run=False,
                     backup_dir=str(self.home.root / "inside"), no_backup=False, json=False)

        # Dry-run
        dry_res = json.loads(self.cmd_out(ledger_cmds.cmd_backfill_numbers, project="alpha", dry_run=True,
                                          backup_dir=str(backup_dir), no_backup=False, json=True))
        self.assertTrue(dry_res["dry_run"])
        self.assertEqual(dry_res["total_assigned"], 2)
        self.assertFalse(backup_dir.exists())

        # Execute backfill with backup
        res = json.loads(self.cmd_out(ledger_cmds.cmd_backfill_numbers, project="alpha", dry_run=False,
                                      backup_dir=str(backup_dir), no_backup=False, json=True))
        self.assertEqual(res["total_assigned"], 2)
        self.assertTrue(Path(res["backup"]["path"]).is_file())
        self.assertEqual(self.load(legacy_a)["number"], 1)
        self.assertEqual(self.load(legacy_b)["number"], 2)
        self.assertIn("| #1 First", self.home.board.read_text(encoding="utf-8"))

        # Idempotent second run creates no second backup
        res2 = json.loads(self.cmd_out(ledger_cmds.cmd_backfill_numbers, project="alpha", dry_run=False,
                                       backup_dir=str(backup_dir), no_backup=False, json=True))
        self.assertEqual(res2["total_assigned"], 0)
        self.assertIsNone(res2["backup"])

    def test_first_new_after_install_auto_backups_and_backfills_in_temp_pm_home(self):
        # Isolated fresh PM_HOME simulating upgrade + immediately running `pm.py new` before `backfill-numbers`.
        fresh_home = self.base / "fresh-pm-home"
        backup_dir = self.base / "pm-backups"
        fake_bin = self.base / "fake-bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        hc_stub = fake_bin / "hc"
        hc_stub.write_text(f"#!{sys.executable}\nimport sys\nprint('{{}}')\n", encoding="utf-8")
        hc_stub.chmod(0o755)
        for sub in ("tasks", "pms", "projects", "inbox", "locks"):
            (fresh_home / sub).mkdir(parents=True, exist_ok=True)
        for slug, repo, term in (("alpha", self.repo_a, "t10"), ("beta", self.repo_b, "t20")):
            (fresh_home / "pms" / f"{slug}.json").write_text(json.dumps({
                "project": slug, "repo": repo, "name": f"pm-{slug}", "runtime": "hc",
                "terminal": term, "pane": f"hc:{term}",
            }), encoding="utf-8")

        def seed_task(tid, **fields):
            (fresh_home / "tasks" / f"{tid}.json").write_text(
                json.dumps({"id": tid, "base": "main", "owner": "pm", "status": "in_progress", "log": [], **fields}),
                encoding="utf-8",
            )

        seed_task("alpha-z-oldest", title="Oldest Alpha", project="alpha", repo=self.repo_a,
                  created="2026-10-01 09:00", updated="2026-11-20 10:00")
        seed_task("alpha-a-middle", title="Middle Alpha", project="alpha", repo=self.repo_a,
                  created="2026-10-02 09:00", updated="2026-10-05 09:00")
        seed_task("alpha-z-oldest-review", title="Review: Oldest Alpha", project="alpha", repo=self.repo_a,
                  review_of="alpha-z-oldest", created="2026-09-01 09:00", updated="2026-10-01 09:00")
        seed_task("beta-old-1", title="Old Beta", project="beta", repo=self.repo_b,
                  created="2026-10-01 08:00", updated="2026-10-01 08:00")
        self.assertFalse((fresh_home / "projects" / "alpha" / "task-seq.json").exists())
        self.assertFalse(backup_dir.exists())

        env = dict(os.environ)
        env["PM_HOME"] = str(fresh_home)
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
        for key in ("HERDR_PANE_ID", "HC_TERMINAL_ID", "HERDR_WORKSPACE_ID", "HERDR_ENV", "CLAUDE_CODE_SESSION_ID"):
            env.pop(key, None)
        pm_script = str(PM_SCRIPT)

        res1 = subprocess.run(
            [sys.executable, pm_script, "new", "Fresh Task", "--repo", self.repo_a,
             "--branch", "dev/fresh", "--pane", "hc:t30", "--note", "init"],
            env=env, cwd=self.repo_a, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(res1.returncode, 0, res1.stdout + res1.stderr)
        new_id = res1.stdout.strip()

        archives = sorted(backup_dir.glob("pm-*-before-backfill.tgz"))
        self.assertEqual(len(archives), 1)
        with tarfile.open(archives[0], "r:gz") as tf:
            old_snap = json.loads(tf.extractfile("pm/tasks/alpha-z-oldest.json").read().decode("utf-8"))
            mid_snap = json.loads(tf.extractfile("pm/tasks/alpha-a-middle.json").read().decode("utf-8"))
            self.assertNotIn("number", old_snap)
            self.assertNotIn("number", mid_snap)

        load_fresh = lambda tid: json.loads((fresh_home / "tasks" / f"{tid}.json").read_text(encoding="utf-8"))
        t_old = load_fresh("alpha-z-oldest")
        t_mid = load_fresh("alpha-a-middle")
        t_rev = load_fresh("alpha-z-oldest-review")
        t_new = load_fresh(new_id)
        t_beta = load_fresh("beta-old-1")
        self.assertEqual((t_old.get("number"), t_old.get("updated")), (1, "2026-11-20 10:00"))
        self.assertEqual((t_mid.get("number"), t_mid.get("updated")), (2, "2026-10-05 09:00"))
        self.assertNotIn("number", t_rev)
        self.assertEqual(t_new.get("number"), 3)
        self.assertNotIn("number", t_beta)

        seq = json.loads((fresh_home / "projects" / "alpha" / "task-seq.json").read_text(encoding="utf-8"))
        self.assertEqual(seq["last"], 3)
        self.assertTrue(seq.get("backfilled_at"))
        board_text = (fresh_home / "BOARD.md").read_text(encoding="utf-8")
        self.assertIn("#1 Oldest Alpha", board_text)
        self.assertIn("#2 Middle Alpha", board_text)
        self.assertIn("#1-review Review: Oldest Alpha", board_text)
        self.assertIn("#3 Fresh Task", board_text)

        res2 = subprocess.run(
            [sys.executable, pm_script, "new", "Second Fresh", "--repo", self.repo_a,
             "--branch", "dev/fresh2", "--pane", "hc:t31", "--note", "init"],
            env=env, cwd=self.repo_a, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(res2.returncode, 0, res2.stdout + res2.stderr)
        second_id = res2.stdout.strip()
        self.assertEqual(load_fresh(second_id).get("number"), 4)
        self.assertEqual(len(list(backup_dir.glob("pm-*-before-backfill.tgz"))), 1)

        bf = subprocess.run(
            [sys.executable, pm_script, "backfill-numbers", "--project", "alpha", "--json"],
            env=env, cwd=self.repo_a, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(bf.returncode, 0, bf.stdout + bf.stderr)
        bf_res = json.loads(bf.stdout)
        self.assertEqual(bf_res["total_assigned"], 0)
        self.assertIsNone(bf_res["backup"])
        self.assertEqual(len(list(backup_dir.glob("pm-*-before-backfill.tgz"))), 1)

        for ref, expected_id in (("#1", "alpha-z-oldest"), ("#3", new_id), ("#1-review", "alpha-z-oldest-review")):
            sh = subprocess.run(
                [sys.executable, pm_script, "show", ref, "--json"],
                env=env, cwd=self.repo_a, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(sh.returncode, 0, sh.stdout + sh.stderr)
            self.assertEqual(json.loads(sh.stdout)["id"], expected_id)


def make_repo(root):
    """A throwaway repository under `root` with a main branch and a task branch dev/x that adds new.txt."""
    repo = (root / "repo-land").resolve()
    repo.mkdir(parents=True)
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
    return repo, git


class TwoLayerPlanAndAutoReview(LedgerCase):
    """Two-layer plans (--plan/--step), silent worker subplan, plan-driven auto-review, and post-merge land."""

    def setUp(self):
        super().setUp()
        self.repo, self.git_run = make_repo(self.base)
        self.name = self.repo.name
        self.wt_root.mkdir(parents=True, exist_ok=True)
        self.hc.terminals.update({
            "t7": {"state": "live", "labels": {"pm": self.name}, "status": {"state": "idle"}},
            "t20": {"state": "live", "status": {"state": "working"}, "labels": {}},
        })
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        (self.ctx.home.registrations / f"{project_slug(self.repo)}.json").write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": str(self.repo),
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "agent": "claude",
        }))
        self.be("hc:t7")

    def make_worktree(self, branch="dev/x"):
        wt = self.wt_root / f"wt-{branch.replace('/', '-')}"
        subprocess.run(["git", "-C", str(self.repo), "branch", "-D", branch], capture_output=True)
        self.git_run("worktree", "add", "-q", str(wt), "-b", branch)
        subprocess.run(["git", "-C", str(wt), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "--allow-empty", "-q", "-m", "worker commit 1"], check=True)
        sha = subprocess.run(["git", "-C", str(wt), "rev-parse", "--short", "HEAD"],
                             check=True, capture_output=True, text=True).stdout.strip()
        return wt, sha

    def delivery(self):
        return Delivery(self.ctx, str(self.repo))

    def test_parse_plan_steps_and_negation_safe_anchors(self):
        steps, explicit = parse_plan_steps(
            "实现快照备份与清理脚本; 独立代码审查；挂在 dev/ledger-backup 分支待你验收（不合 main）\n同步安装到本机与 MBP 并跑检查"
        )
        self.assertFalse(explicit)
        self.assertEqual([s["text"] for s in steps], [
            "实现快照备份与清理脚本",
            "独立代码审查",
            "挂在 dev/ledger-backup 分支待你验收（不合 main）",
            "同步安装到本机与 MBP 并跑检查",
        ])
        self.assertEqual([step_anchor(s) for s in steps], ["work", "review", "custom", "custom"])
        self.assertTrue(all(s["state"] == "todo" for s in steps))
        self.assertTrue(all(s.get("anchor") in PLAN_ANCHORS for s in steps))

        en_steps, _ = parse_plan_steps([
            "[x] Design probe @work",
            "[>] Build interactive mock; Hold in worktree (no merge)",
            "[ ] No code review @custom",
            "Merge into main",
            "Await your review @custom",
        ])
        self.assertEqual([(s["state"], step_anchor(s)) for s in en_steps], [
            ("done", "work"), ("doing", "work"), ("todo", "custom"), ("todo", "custom"), ("todo", "merge"), ("todo", "custom")
        ])
        self.assertTrue(all(s.get("anchor") in PLAN_ANCHORS for s in en_steps))
        # --step keeps ';' intact inside a single step
        by_step, explicit2 = parse_plan_steps(
            step_vals=["[x] Part A; detail", "[*] Part B", "[ ] Merge into main"]
        )
        self.assertTrue(explicit2)
        self.assertEqual([(s["text"], s["state"], step_anchor(s)) for s in by_step], [
            ("Part A; detail", "done", "custom"),
            ("Part B", "doing", "custom"),
            ("Merge into main", "todo", "merge"),
        ])
        self.assertTrue(all(s.get("anchor") in PLAN_ANCHORS for s in by_step))

        # Tight review inference: mentioning review/审查 in a work/user step does NOT infer 'review'
        strict_cases = [
            ("实现审查面板", "work"),
            ("Fix review panel layout", "work"),
            ("Design review with user", "work"),
            ("Review with user", "custom"),
            ("审查并修改问题", "work"),
            ("Review and implement fixes", "work"),
            ("独立代码审查", "review"),
            ("独立复审（提交后自动拉起）", "review"),
            ("Independent code review (auto-started)", "review"),
            ("Re-review", "review"),
            ("审查", "review"),
            ("实现审查面板 @review", "review"),
            ("独立代码审查 @custom", "custom"),
        ]
        for text, expected in strict_cases:
            parsed, _ = parse_plan_steps(text)
            self.assertEqual(parsed[0]["anchor"], expected, text)
            self.assertEqual(step_anchor(parsed[0]), expected, text)

        # Stored object step without an explicit anchor defaults to 'custom' (matching model.js)
        no_anchor_obj = {"text": "独立代码审查", "state": "todo"}
        self.assertEqual(step_anchor(no_anchor_obj), "custom")
        self.assertFalse(has_pending_review_step({"plan": [no_anchor_obj]}))

        # Inner subplan steps do not persist 'anchor'
        sub_steps, _ = parse_plan_steps("独立代码审查; 实现功能", outer=False)
        self.assertTrue(all("anchor" not in s for s in sub_steps))

    def test_caller_role_routing_and_silent_worker_subplan(self):
        tid = f"{self.name}-route"
        now = self.clock.now()
        self.save({
            "id": tid, "title": "路由测试", "project": self.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:t20",
            "dispatched": True, "created": now, "log": [{"at": now, "by": "hc:t7", "text": "dispatched"}],
        })
        # PM writes outer plan
        self.be("hc:t7")
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid, plan=["实现功能; 独立审查; 合进 main"])
        t = self.load(tid)
        self.assertEqual([s["text"] for s in t["plan"]], ["实现功能", "独立审查", "合进 main"])
        self.assertEqual([s["state"] for s in t["plan"]], ["doing", "todo", "todo"])
        self.assertNotIn("subplan", t)
        log_len_before = len(t["log"])
        conv_len_before = len(self.conversation(str(self.repo)))

        # Worker writes --plan -> silently routes to subplan (no log, no conversation event, no deliver)
        self.be("hc:t20")
        self.clear_started()
        out = self.cmd_out(ledger_cmds.cmd_update, id=tid, plan=["[x] 盘点接口; [>] 写逻辑; [ ] 补单测"])
        self.assertIn("subplan 1/3", out)
        t = self.load(tid)
        self.assertEqual([s["text"] for s in t["plan"]], ["实现功能", "独立审查", "合进 main"])  # untouched
        self.assertEqual([(s["text"], s["state"]) for s in t["subplan"]], [
            ("盘点接口", "done"), ("写逻辑", "doing"), ("补单测", "todo")
        ])
        self.assertEqual(len(t["log"]), log_len_before)
        self.assertEqual(len(self.conversation(str(self.repo))), conv_len_before)
        self.assertEqual(self.started(), [])

        # Mixing --plan and --outer-plan is rejected
        with self.assertRaises(SystemExit):
            self.cmd(ledger_cmds.cmd_update, id=tid, plan=["a"], outer_plan=["b"])

        # Explicit --outer-plan / --subplan overrides work regardless of caller pane
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid, subplan=[""])
        self.assertNotIn("subplan", self.load(tid))

    def test_four_prompt_shapes_and_midflight_edit_and_legacy_fallback(self):
        # Shape A: Design & local preview only (no review, no merge)
        t_design = self.cmd_quiet(
            ledger_cmds.cmd_new,
            repo=str(self.repo), title="设计稿", status="in_progress", owner="pm", base="main",
            workspace="", pane="hc:t20", slug="shape-a", branch="dev/shape-a", note="start",
            plan=["真机探针验证; 出中英双语交互稿并起本地预览; 等你审阅定稿"],
        )
        td = self.load(t_design)
        self.assertEqual([step_anchor(s) for s in td["plan"]], ["custom", "work", "custom"])
        self.assertTrue(all(s.get("anchor") in PLAN_ANCHORS for s in td["plan"]))
        self.assertFalse(has_pending_review_step(td))

        # Shape B: Hold on branch (review, explicitly no merge)
        t_hold = self.cmd_quiet(
            ledger_cmds.cmd_new,
            repo=str(self.repo), title="台账备份", status="in_progress", owner="pm", base="main",
            workspace="", pane="hc:t20", slug="shape-b", branch="dev/shape-b", note="start",
            plan=["实现快照备份; 独立代码审查 @review; 挂分支待你验收（不合 main）"],
        )
        th = self.load(t_hold)
        self.assertEqual([step_anchor(s) for s in th["plan"]], ["work", "review", "custom"])

        # Shape C: Mid-flight PM edit inserts translation step without losing state
        self.be("hc:t7")
        self.cmd_quiet(ledger_cmds.cmd_update, id=t_hold,
                       plan=["[x] 盘点与脱敏初稿; [>] 全量译为英文; [ ] 独立审查; [ ] 合进 main"])
        tc = self.load(t_hold)
        self.assertEqual([(s["state"], step_anchor(s)) for s in tc["plan"]], [
            ("done", "work"), ("doing", "work"), ("todo", "review"), ("todo", "merge")
        ])

        # Legacy task without plan works untouched
        t_old = self.cmd_quiet(
            ledger_cmds.cmd_new,
            repo=str(self.repo), title="旧任务", status="in_progress", owner="pm", base="main",
            workspace="", pane="hc:t20", slug="legacy", branch="dev/legacy", note="old",
        )
        self.assertNotIn("plan", self.load(t_old))
        self.cmd_quiet(ledger_cmds.cmd_update, id=t_old, status="review", note="ready")
        self.assertNotIn("plan", self.load(t_old))

    def test_dispatch_with_plan_no_review_and_deep_held(self):
        brief = self.base / "brief.md"
        brief.write_text("Implement feature.\n")
        self.be("hc:t7")
        # Dry-run shows plan and no_review
        dry_out = self.cmd_out(
            dispatch_cmds.cmd_dispatch,
            title="计划派发", repo=str(self.repo), branch="dev/disp", label="disp",
            path=None, brief=str(brief), name="w-disp", task=None, here=False,
            tab=None, bug=None, codex_profile=None, dry_run=True, base="main", prep=None,
            parent=None, profile="standard", kind=None, model=None, effort=None, advisor=None,
            confirmed=False, plan=["[x] 对齐方案; 分支实现; 独立审查; 合进 main"],
            step=None, outer_plan=None, no_review=True,
        )
        dry_json = json.loads(dry_out)
        self.assertTrue(dry_json["no_review"])
        self.assertEqual(len(dry_json["plan"]), 4)

        # Deep profile holds plan & no_review until --confirmed
        held_id = self.cmd_quiet(
            dispatch_cmds.cmd_dispatch,
            title="深档任务", repo=str(self.repo), branch="dev/deep-plan", label="deep-plan",
            path=None, brief=str(brief), name="w-deep", task=None, here=False,
            tab=None, bug=None, codex_profile=None, dry_run=False, base="main", prep=None,
            parent=None, profile="deep", kind=None, model=None, effort=None, advisor=None,
            confirmed=False, plan=["实现功能; 独立审查; 合进 main"],
            step=None, outer_plan=None, no_review=False,
        )
        held = self.load(held_id)
        self.assertEqual(held["status"], "blocked")
        self.assertEqual([s["state"] for s in held["plan"]], ["todo", "todo", "todo"])

        self.cmd_quiet(
            dispatch_cmds.cmd_dispatch,
            title="深档任务", repo=str(self.repo), branch="dev/deep-plan", label="deep-plan",
            path=None, brief=str(brief), name="w-deep", task=None, here=False,
            tab=None, bug=None, codex_profile=None, dry_run=False, base="main", prep=None,
            parent=None, profile="deep", kind=None, model=None, effort=None, advisor=None,
            confirmed=True, plan=None, step=None, outer_plan=None, no_review=False,
        )
        resumed = self.load(held_id)
        self.assertEqual(resumed["status"], "in_progress")
        self.assertEqual([s["state"] for s in resumed["plan"]], ["doing", "todo", "todo"])

    def test_auto_review_lifecycle_single_combined_wake_and_multiround_limit(self):
        wt, sha1 = self.make_worktree("dev/ar")
        tid = f"{self.name}-ar"
        self.save({
            "id": tid, "title": "自动送审测试", "project": self.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "branch": "dev/ar",
            "worktree": str(wt), "pane": "hc:t20", "agent": "w-ar", "dispatched": True,
            "worker": {"profile": "standard", "kind": "claude", "model": "opus"},
            "created": self.clock.now(), "log": [],
            "plan": [
                {"text": "分支实现与单测", "state": "doing", "anchor": "work"},
                {"text": "独立代码审查", "state": "todo", "anchor": "review"},
                {"text": "合进 main", "state": "todo", "anchor": "merge"},
            ],
            "subplan": [{"text": "写代码", "state": "doing"}],
        })
        # 1. Worker reports review with --commit -> auto-review starts, PM is NOT woken yet
        self.be("hc:t20")
        self.clear_started()
        out = self.cmd_out(ledger_cmds.cmd_update, id=tid, status="review", commit=sha1, keep=False,
                           note="实现完成，42条单测通过")
        self.assertIn("auto-review started", out)
        t = self.load(tid)
        self.assertEqual([s["state"] for s in t["plan"]], ["done", "doing", "todo"])
        self.assertEqual(t["subplan"][0]["state"], "done")
        self.assertEqual(t["auto_review"]["status"], "running")
        self.assertEqual(t["auto_reviewed_commit"], subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "--verify", f"{sha1}^{{commit}}"],
            check=True, capture_output=True, text=True).stdout.strip())
        rev = self.load(f"{tid}-review")
        self.assertEqual(rev["status"], "in_progress")
        # Pending batch for PM must be empty before reviewer finishes!
        _, _, items = self.delivery().pending_batch()
        self.assertEqual(items, [])

        # Duplicate report with same commit does NOT start a second review
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid, status="review", commit=sha1, keep=False, note="same")
        self.assertEqual(self.hc.runs, 1)

        # 2. Reviewer reports blockers -> wakes PM once with BOTH worker summary and review findings
        rev_pane = rev["pane"]
        self.be(rev_pane)
        self.clear_started()
        self.cmd_quiet(ledger_cmds.cmd_update, id=f"{tid}-review", status="done", keep=False, note="1. 缺少边界校验")
        self.assertEqual(self.started(), [str(self.repo)])
        start, end, items = self.delivery().pending_batch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["event"]["task"], f"{tid}-review")
        batch = self.delivery().batch_text(start, end, items)
        self.assertIn(f"{tid}-review -> {tid}", batch)
        self.assertIn(f"(commit {sha1})", batch)
        self.assertIn("实现完成，42条单测通过", batch)
        self.assertIn("1. 缺少边界校验", batch)
        t = self.load(tid)
        self.assertEqual(t["auto_review"]["status"], "blockers")
        self.assertEqual([s["state"] for s in t["plan"]], ["done", "doing", "todo"])
        self.delivery().advance_delivered(end)

        # 3. PM sends findings back -> @review resets to todo and @work returns to doing
        self.be("hc:t7")
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid, status="in_progress", note="修边界校验", send=True)
        self.assertEqual([s["state"] for s in self.load(tid)["plan"]], ["doing", "todo", "todo"])

        # Round 2: new commit auto-reviews (rounds becomes 1)
        subprocess.run(["git", "-C", str(wt), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "--allow-empty", "-q", "-m", "worker commit 2"], check=True)
        sha2 = subprocess.run(["git", "-C", str(wt), "rev-parse", "--short", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
        self.be("hc:t20")
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid, status="review", commit=sha2, keep=False, note="已修边界")
        self.assertEqual(self.hc.runs, 2)
        self.assertEqual(self.load(tid)["rounds"], 1)

        # Round 2 reviewer also reports blockers
        self.be(self.load(f"{tid}-review")["pane"])
        self.cmd_quiet(ledger_cmds.cmd_update, id=f"{tid}-review", status="done", keep=False, note="1. 还有问题")
        _, end, _ = self.delivery().pending_batch()
        self.delivery().advance_delivered(end)

        # Round limit check: with blockers and rounds=1, next round hits AUTO_REVIEW_MAX_ROUNDS (2) and wakes PM directly
        self.be("hc:t7")
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid, status="in_progress", note="再修")
        subprocess.run(["git", "-C", str(wt), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "--allow-empty", "-q", "-m", "worker commit 3"], check=True)
        sha3 = subprocess.run(["git", "-C", str(wt), "rev-parse", "--short", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
        self.be("hc:t20")
        self.clear_started()
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid, status="review", commit=sha3, keep=False, note="第3次提交")
        self.assertEqual(self.hc.runs, 2)  # did NOT start a 3rd reviewer
        self.assertEqual(self.started(), [str(self.repo)])  # woke PM directly
        _, end, items = self.delivery().pending_batch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["event"]["task"], tid)
        self.delivery().advance_delivered(end)

        # Clean pass path on a separate task checks off @review step and wakes PM once
        wt_ok, sha_ok = self.make_worktree("dev/ar-ok")
        tid_ok = f"{self.name}-ar-ok"
        self.save({
            "id": tid_ok, "title": "自动送审通过", "project": self.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "branch": "dev/ar-ok",
            "worktree": str(wt_ok), "pane": "hc:t20", "agent": "w-ok", "dispatched": True,
            "worker": {"profile": "standard", "kind": "claude", "model": "opus"},
            "created": self.clock.now(), "log": [],
            "plan": [
                {"text": "分支实现", "state": "doing", "anchor": "work"},
                {"text": "独立代码审查", "state": "todo", "anchor": "review"},
                {"text": "合进 main", "state": "todo", "anchor": "merge"},
            ],
        })
        self.be("hc:t20")
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid_ok, status="review", commit=sha_ok, keep=False, note="完成")
        self.assertEqual(self.hc.runs, 3)
        self.be(self.load(f"{tid_ok}-review")["pane"])
        self.clear_started()
        self.cmd_quiet(ledger_cmds.cmd_update, id=f"{tid_ok}-review", status="done", keep=False, note="无阻塞，通过")
        t_ok = self.load(tid_ok)
        self.assertEqual([s["state"] for s in t_ok["plan"]], ["done", "done", "todo"])
        self.assertEqual(t_ok["auto_review"]["status"], "passed")
        self.assertEqual(self.started(), [str(self.repo)])
        start, end, items = self.delivery().pending_batch()
        self.assertEqual(len(items), 1)
        batch_ok = self.delivery().batch_text(start, end, items)
        self.assertIn("无阻塞，通过", batch_ok)
        self.assertIn("完成", batch_ok)

    def test_no_auto_review_without_review_step_legacy_no_review_or_no_commit(self):
        wt, sha = self.make_worktree("dev/skip-ar")
        cases = [
            ("no-rev-step", {"plan": [{"text": "改一行", "state": "doing", "anchor": "work"},
                                      {"text": "合进 main", "state": "todo", "anchor": "merge"}]}, sha),
            ("rev-word-in-work", {"plan": parse_plan_steps("[>] 实现审查面板; 合进 main")[0]}, sha),
            ("unanchored-obj", {"plan": [{"text": "实现", "state": "doing", "anchor": "work"},
                                         {"text": "独立代码审查", "state": "todo"}]}, sha),
            ("legacy", {}, sha),
            ("flag-off", {"no_review": True, "plan": [{"text": "实现", "state": "doing", "anchor": "work"},
                                                       {"text": "独立审查", "state": "todo", "anchor": "review"}]}, sha),
            ("no-commit", {"plan": [{"text": "调研", "state": "doing", "anchor": "work"},
                                    {"text": "独立审查", "state": "todo", "anchor": "review"}]}, None),
        ]
        self.be("hc:t20")
        for slug, extra, commit in cases:
            tid = f"{self.name}-{slug}"
            self.save({
                "id": tid, "title": slug, "project": self.name, "repo": str(self.repo),
                "status": "in_progress", "owner": "pm", "base": "main", "branch": "dev/skip-ar",
                "worktree": str(wt), "pane": "hc:t20", "dispatched": True, "created": self.clock.now(), "log": [],
                **extra,
            })
            self.clear_started()
            self.cmd_quiet(ledger_cmds.cmd_update, id=tid, status="review", commit=commit, keep=False, note="done")
            self.assertEqual(self.hc.runs, 0, slug)
            self.assertEqual(self.started(), [str(self.repo)], slug)
            self.assertFalse((self.ctx.home.tasks / f"{tid}-review.json").exists(), slug)

    def test_auto_review_startup_failure_rolls_back_and_wakes_pm(self):
        wt, sha = self.make_worktree("dev/ar-fail")
        tid = f"{self.name}-ar-fail"
        self.save({
            "id": tid, "title": "启动失败兜底", "project": self.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "branch": "dev/ar-fail",
            "worktree": str(wt), "pane": "hc:t20", "dispatched": True, "created": self.clock.now(), "log": [],
            "plan": [{"text": "实现", "state": "doing", "anchor": "work"},
                     {"text": "独立代码审查", "state": "todo", "anchor": "review"}],
        })
        self.hc.review_should_fail = True
        self.be("hc:t20")
        self.clear_started()
        out = self.cmd_out(ledger_cmds.cmd_update, id=tid, status="review", commit=sha, keep=False, note="ready")
        self.assertIn("auto-review failed", out)
        t = self.load(tid)
        self.assertEqual(t["auto_review"]["status"], "failed")
        self.assertEqual(t["plan"][1]["state"], "todo")
        self.assertEqual(self.started(), [str(self.repo)])
        _, _, items = self.delivery().pending_batch()
        self.assertEqual(len(items), 1)
        self.assertIn("auto-review failed", items[0]["event"]["text"])
        self.assertIn("ready", items[0]["event"]["text"])

    def test_land_with_post_merge_steps_stays_active_and_completes_on_done(self):
        vfile = self.ctx.home.project_for(str(self.repo)).verify
        vfile.parent.mkdir(parents=True, exist_ok=True)
        vfile.write_text("true\n")
        stalls = StallWatcher(self.ctx)

        # 1. Task with post-merge step stays in_progress after land
        wt, _ = self.make_worktree("dev/post-merge")
        (wt / "feat.txt").write_text("feature\n")
        subprocess.run(["git", "-C", str(wt), "add", "feat.txt"], check=True)
        subprocess.run(["git", "-C", str(wt), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "feat"], check=True)
        tid = f"{self.name}-post"
        self.save({
            "id": tid, "title": "带安装步", "project": self.name, "repo": str(self.repo),
            "status": "review", "owner": "pm", "base": "main", "branch": "dev/post-merge",
            "worktree": str(wt), "pane": "hc:t20", "dispatched": True, "created": self.clock.now(), "log": [],
            "plan": [
                {"text": "分支实现", "state": "done", "anchor": "work"},
                {"text": "独立审查", "state": "done", "anchor": "review"},
                {"text": "合进 main", "state": "todo", "anchor": "merge"},
                {"text": "同步安装到 MBP", "state": "todo"},
            ],
        })
        self.hc.terminals["t20"] = {"state": "live", "cwd": str(wt), "labels": {"task": tid},
                                    "status": {"state": "idle"}}
        self.be("hc:t7")
        out = self.cmd_out(review_cmds.cmd_land, id=tid, keep=False, message=None, timeout=60)
        self.assertIn("active 3/4", out)
        t = self.load(tid)
        self.assertEqual(t["status"], "in_progress")
        self.assertEqual([s["state"] for s in t["plan"]], ["done", "done", "done", "doing"])
        self.assertTrue(t["landed"]["commit"])
        self.assertEqual(t["pane"], "")
        self.assertEqual(t["worktree"], "")
        self.assertFalse(t.get("retired"))
        self.assertFalse(task_offline(t.raw, {"t7"}, None))
        self.assertFalse(stalls.watched_worker(t.raw))
        self.assertFalse(wt.exists())

        # Second land refuses cleanly
        with self.assertRaises(SystemExit) as stop, contextlib.redirect_stderr(io.StringIO()):
            self.cmd(review_cmds.cmd_land, id=tid, keep=False, message=None, timeout=60)
        self.assertEqual(stop.exception.code, LAND_REFUSED)

        # Completing remaining step via update --status done marks all steps done and closes task
        self.cmd_quiet(ledger_cmds.cmd_update, id=tid, status="done", note="已装到 MBP")
        t = self.load(tid)
        self.assertEqual(t["status"], "done")
        self.assertTrue(all(s["state"] == "done" for s in t["plan"]))

        # 2. Task whose outer plan ends at merge closes normally as merged
        wt2, _ = self.make_worktree("dev/merge-end")
        (wt2 / "feat2.txt").write_text("feature2\n")
        subprocess.run(["git", "-C", str(wt2), "add", "feat2.txt"], check=True)
        subprocess.run(["git", "-C", str(wt2), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "feat2"], check=True)
        tid2 = f"{self.name}-end"
        self.save({
            "id": tid2, "title": "合完即结束", "project": self.name, "repo": str(self.repo),
            "status": "review", "owner": "pm", "base": "main", "branch": "dev/merge-end",
            "worktree": str(wt2), "pane": "hc:t21", "dispatched": True, "created": self.clock.now(), "log": [],
            "plan": [
                {"text": "分支实现", "state": "done", "anchor": "work"},
                {"text": "合进 main", "state": "todo", "anchor": "merge"},
            ],
        })
        self.hc.terminals["t21"] = {"state": "live", "cwd": str(wt2), "labels": {"task": tid2},
                                    "status": {"state": "idle"}}
        self.cmd_quiet(review_cmds.cmd_land, id=tid2, keep=False, message=None, timeout=60)
        t2 = self.load(tid2)
        self.assertEqual(t2["status"], "merged")
        self.assertTrue(t2.get("retired"))
        self.assertTrue(all(s["state"] == "done" for s in t2["plan"]))

        # 3. land --keep with post-merge step preserves worktree but disables stall watching
        wt3, _ = self.make_worktree("dev/keep-post")
        (wt3 / "feat3.txt").write_text("feature3\n")
        subprocess.run(["git", "-C", str(wt3), "add", "feat3.txt"], check=True)
        subprocess.run(["git", "-C", str(wt3), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "feat3"], check=True)
        tid3 = f"{self.name}-keep"
        self.save({
            "id": tid3, "title": "keep测试", "project": self.name, "repo": str(self.repo),
            "status": "review", "owner": "pm", "base": "main", "branch": "dev/keep-post",
            "worktree": str(wt3), "pane": "hc:t22", "dispatched": True, "created": self.clock.now(), "log": [],
            "plan": [{"text": "实现", "state": "done", "anchor": "work"},
                     {"text": "合进 main", "state": "todo", "anchor": "merge"},
                     {"text": "安装验证", "state": "todo"}],
        })
        self.hc.terminals["t22"] = {"state": "live", "cwd": str(wt3), "labels": {"task": tid3},
                                    "status": {"state": "idle"}}
        self.cmd_quiet(review_cmds.cmd_land, id=tid3, keep=True, message=None, timeout=60)
        t3 = self.load(tid3)
        self.assertEqual(t3["status"], "in_progress")
        self.assertTrue(wt3.exists())
        self.assertFalse(stalls.watched_worker(t3.raw))

    def test_dash_state_and_show_and_handover_expose_plan_and_landed(self):
        tid = f"{self.name}-state-plan"
        now = self.clock.now()
        self.save({
            "id": tid, "title": "状态展示", "project": self.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "commit": "abc1234",
            "landed": {"commit": "abc1234", "base": "main", "branch": "dev/s", "at": now},
            "no_review": True, "created": now, "log": [],
            "plan": [{"text": "实现", "state": "done", "anchor": "work"},
                     {"text": "装到 MBP", "state": "doing"}],
            "subplan": [{"text": "子步1", "state": "done"}],
        })
        tid_legacy = f"{self.name}-state-old"
        self.save({
            "id": tid_legacy, "title": "旧任务", "project": self.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "created": now, "log": [],
        })
        state = state_view.dash_state(ctx=self.ctx)
        by_id = {t["id"]: t for t in state["tasks"]}
        self.assertEqual(len(by_id[tid]["plan"]), 2)
        self.assertEqual(len(by_id[tid]["subplan"]), 1)
        self.assertTrue(by_id[tid]["no_review"])
        self.assertEqual(by_id[tid]["landed"]["commit"], "abc1234")
        self.assertEqual(by_id[tid]["commit"], "abc1234")
        for absent in ("plan", "subplan", "no_review", "landed", "commit"):
            self.assertNotIn(absent, by_id[tid_legacy])

        show_out = self.cmd_out(status_view.cmd_show, id=tid, json=False)
        self.assertIn("plan (1/2):", show_out)
        self.assertIn("landed=abc1234", show_out)
        self.assertIn("[>] 装到 MBP", show_out)
        self.assertIn("      [x] 子步1", show_out)

        ho_out = self.cmd_out(manager_cmds.cmd_handover, repo=str(self.repo), compact=True, full=False, turns=2)
        self.assertIn("plan=1/2", ho_out)


if __name__ == "__main__":
    unittest.main()
