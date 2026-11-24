"""Worker report/wait, offline/reattach and close-worker tests migrated from `test_pm.py` onto
per-test `make_ctx` + `fakes.py` (Stage 6b1)."""
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
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import FakeChangeWaiter, FakeClock, FakeHc, FakeProcs, FakeTui, make_ctx  # noqa: E402
from pmlib import osutil  # noqa: E402
from pmlib.agents import sessions as agents_sessions  # noqa: E402
from pmlib.commands import ledger as ledger_cmd, workers as workers_cmd  # noqa: E402
from pmlib.context import StdOutput  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.task import CLOSED, created_at  # noqa: E402
from pmlib.ledger.transition import FIELDS  # noqa: E402
from pmlib.project.project import pm_name, project_slug  # noqa: E402
from pmlib.views import state as state_view, status as status_view  # noqa: E402
from pmlib.workers import (  # noqa: E402
    brief as workers_brief,
    lifecycle as workers_lifecycle,
    reattach as workers_reattach,
    sessions as workers_sessions,
)
from pmlib.workers.service import Workers  # noqa: E402


class ReportAndWait(unittest.TestCase):
    """The worker reports in the ledger; the PM waits for that report instead of reading the screen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-report-wait-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_the_report_section_names_the_task_and_both_commands(self):
        for lang, word in (("en", "Reporting"), ("zh", "汇报")):
            ctx = make_ctx(self.root / f"lang-{lang}", config={"lang": lang})
            text = workers_brief.report_section_for(ctx, "p-x")
            self.assertIn(word, text)
            self.assertIn("update p-x --status review --commit <sha> --note", text)
            self.assertIn("update p-x --status blocked --note", text)
            self.assertIn("600", text)
        # What was sent is kept, report section included, for a resend by hand.
        ctx_en = make_ctx(self.root / "sent-en", config={})
        sent = workers_brief.keep_sent_for(ctx_en, "p-x", "Do the thing.")
        self.assertTrue(sent.read_text().startswith("Do the thing.\n\nReporting (task p-x)"))

    def _run_wait(self, ctx, task_id, terminal_states, update_after=None, timeout=60):
        """Run `wait` against a fake hc whose terminal reports the given states in turn."""
        states = iter(terminal_states)
        looks = []
        clock = FakeClock()

        def on_wait(step_timeout):
            step = min(step_timeout, 5)
            clock.advance(step)
            looks.append(1)
            if update_after is not None and len(looks) == update_after:
                with contextlib.redirect_stdout(io.StringIO()):
                    ledger_cmd.cmd_update(type("A", (), {
                        "id": task_id, "status": "review", "commit": "abc123", "keep": False,
                        "note": "wrote one line; tests pass; UI not checked",
                    }), ctx=ctx)

        class _WaitHc(FakeHc):
            def get_raw(self, term, *, errors=False):
                return next(states, None)

            def change_waiter(self, paths=(), hc_args=None, files=(), terminals=None, folders=(), *, hc=None, warn=None):
                return FakeChangeWaiter(
                    paths=paths, hc_args=hc_args, files=files, terminals=terminals,
                    folders=folders, on_wait=on_wait, clock=clock,
                )

        ctx.clock = clock
        ctx.hc = _WaitHc(clock=clock)
        out, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(out):
                workers_cmd.cmd_wait(type("A", (), {"id": task_id, "timeout": timeout}), ctx=ctx)
        except SystemExit as stop:
            code = stop.code
        return code, out.getvalue()

    def _make_task(self, task_id):
        ctx = make_ctx(self.root / f"wait-{task_id}", git=GitRepo(), out=StdOutput())
        repo = self.root / f"repo-{task_id}"
        repo.mkdir(exist_ok=True)
        Ledger(ctx).save({
            "id": task_id, "title": "t", "project": "p", "repo": str(repo),
            "status": "in_progress", "owner": "pm", "base": "main",
            "pane": "hc:t5", "created": ctx.clock.now(),
        })
        return ctx

    def test_wait_returns_the_report_once_the_status_leaves_in_progress(self):
        ctx = self._make_task("p-done")
        working = {"state": "live", "status": {"state": "working"}}
        code, out = self._run_wait(ctx, "p-done", [working] * 5, update_after=2)
        self.assertEqual(code, 0)
        self.assertIn("p-done: review (commit abc123)", out)
        self.assertIn("wrote one line; tests pass; UI not checked", out)
        self.assertIn("ahead=", out)

    def test_wait_times_out_with_exit_2(self):
        ctx = self._make_task("p-slow")
        code, out = self._run_wait(ctx, "p-slow", [{"state": "live", "status": {"state": "working"}}] * 3, timeout=0)
        self.assertEqual(code, 2)
        self.assertIn("no new report", out)

    def test_a_worker_idle_without_a_report_exits_3_with_a_reminder(self):
        ctx = self._make_task("p-quiet")
        idle = {"state": "live", "status": {"state": "idle"}}
        code, out = self._run_wait(ctx, "p-quiet", [idle, idle, idle])
        self.assertEqual(code, 3)
        self.assertIn("stopped (idle) without reporting", out)
        self.assertIn("hc send t5 ", out)
        self.assertIn("update p-quiet --status review|blocked", out)
        # An exited terminal counts too; a single idle look between turns does not.
        ctx2 = self._make_task("p-gone")
        code, _ = self._run_wait(
            ctx2, "p-gone",
            [idle, {"state": "live", "status": {"state": "working"}}, {"state": "exited"}, {"state": "exited"}],
        )
        self.assertEqual(code, 3)

    def test_blocked_errored_or_removed_workers_end_the_wait(self):
        ctx1 = self._make_task("p-ask")
        blocked = {"state": "live", "status": {"state": "blocked"}}
        code, out = self._run_wait(ctx1, "p-ask", [blocked, blocked])
        self.assertEqual((code, "blocked" in out, "hc read t5" in out), (3, True, True))
        ctx2 = self._make_task("p-err")
        code, out = self._run_wait(ctx2, "p-err", [{"state": "live", "status": {"state": "error"}}] * 2)
        self.assertEqual((code, "error" in out), (3, True))
        ctx3 = self._make_task("p-rm")
        gone = {"error": {"kind": "not_found", "message": "no terminal"}}
        code, out = self._run_wait(ctx3, "p-rm", [gone, gone])
        self.assertEqual((code, "removed" in out, "hc send" in out), (3, True, False))  # nobody left to remind
        ctx4 = self._make_task("p-nohc")  # hc unavailable: nothing is known, so wait runs to its timeout
        code, _ = self._run_wait(ctx4, "p-nohc", [None, None, None], timeout=0)
        self.assertEqual(code, 2)

    def test_an_old_report_is_not_returned_again(self):
        ctx = self._make_task("p-again")
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmd.cmd_update(type("A", (), {
                "id": "p-again", "status": "review", "commit": "c1", "keep": False, "note": "first report",
            }), ctx=ctx)
        working = {"state": "live", "status": {"state": "working"}}
        code, out = self._run_wait(ctx, "p-again", [working] * 3, timeout=0)
        self.assertEqual(code, 2)                       # the old report does not end the wait
        code, out = self._run_wait(ctx, "p-again", [working] * 5, update_after=2)
        self.assertEqual(code, 0)
        self.assertIn("wrote one line", out)            # the new one does
        self.assertNotIn("first report", out)


class _OfflineHc(FakeHc):
    """FakeHc for Offline tests: dynamic live set (None = unreachable), t70 on run, full call log."""

    def __init__(self, *, repo: str, name: str, live: set[str] | None, clock: FakeClock):
        super().__init__(clock=clock)
        self._repo = repo
        self._name = name
        self.live: set[str] | None = live
        self.raw_calls: list[tuple] = []

    def _ls_raw(self, *, all: bool = False):
        self.raw_calls.append(("ls", "--all") if all else ("ls",))
        if self.live is None:
            return None
        return {"terminals": [{"address": a, "state": "live"} for a in self.live]}

    def get_raw(self, term: str, *, errors: bool = False):
        self.raw_calls.append(("get", term))
        if term == "tpm":
            return {"address": "tpm", "state": "live", "labels": {"pm": self._name}, "cwd": self._repo}
        if self.live is not None and term in self.live:
            return {"address": term, "state": "live", "status": {"state": "idle"}}
        return {"address": term, "state": "finished", "cwd": self._repo}

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
        self.raw_calls.append(tuple(cmd))
        if self.live is not None:
            self.live.add("t70")
        return {"address": "t70", "id": "t70", "state": "live"}

    def send(self, term: str, text: str, *, if_state=None, timeout: float = 180, errors: bool = False):
        self.raw_calls.append(("send", term, text))
        return {"started": True}

    def label(self, term: str, *pairs: str, errors: bool = False):
        self.raw_calls.append(("label", term, *pairs))
        return {}


class Offline(unittest.TestCase):
    """A task whose terminal is gone is marked offline in `state`, and `reattach` brings its agent back."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-offline-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        git = GitRepo()
        self.repo = git.project_root(repo_dir)
        self.name = Path(self.repo).name
        self.hc = _OfflineHc(repo=self.repo, name=self.name, live={"t1", "tpm"}, clock=FakeClock())
        self.tui = FakeTui(agents=[], server_ok=True)
        self.ctx = make_ctx(
            self.root / "ctx",
            hc=self.hc,
            tui=self.tui,
            git=git,
            clock=FakeClock(),
            out=StdOutput(),
        )
        self.claude = self.ctx.claude_projects
        self.codex = self.ctx.codex_sessions
        self.claude.mkdir(parents=True, exist_ok=True)
        self.codex.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.ctx)
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        (self.ctx.home.registrations / f"{project_slug(self.repo)}.json").write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo,
            "runtime": "hc", "terminal": "tpm", "pane": "hc:tpm",
        }))

    def task(self, slug, status="in_progress", pane="hc:t2", **extra):
        task = {
            "id": f"{self.name}-{slug}", "title": f"线程 {slug}", "project": self.name,
            "repo": self.repo, "status": status, "owner": "pm", "base": "main",
            "pane": pane, "created": "2026-11-14 01:00", **extra,
        }
        self.ledger.save(task)
        return task["id"]

    def session(self, folder, sid, *texts, cwd=None):
        path = self.claude / agents_sessions.claude_folder(folder) / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [json.dumps({"type": "user", "cwd": cwd or folder, "message": {"content": t}}) for t in texts]
        path.write_text("\n".join(rows) + "\n")
        return path

    def reattach(self, task_id):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            workers_cmd.cmd_reattach(argparse.Namespace(id=task_id), ctx=self.ctx)
        return out.getvalue()

    def started(self):
        run = [c for c in self.hc.raw_calls if c[0] == "run"]
        self.assertEqual(len(run), 1)
        return list(run[0])

    def sent(self):
        return [c[2] for c in self.hc.raw_calls if c[0] == "send"]

    def offline_ids(self):
        return {t["id"] for t in state_view.dash_state(ctx=self.ctx)["tasks"] if t["offline"] and t["id"].startswith(self.name)}

    def working(self):
        return next(p for p in state_view.dash_state(ctx=self.ctx)["pms"] if p["repo"] == self.repo)["counts"]["working"]

    def test_state_marks_open_work_whose_terminal_is_gone(self):
        ids = {
            k: self.task(k, status, pane)
            for k, status, pane in (
                ("live", "in_progress", "hc:t1"), ("gone", "in_progress", "hc:t2"), ("review", "review", "hc:t3"),
                ("asks", "blocked", "hc:t4"), ("paused", "paused", "hc:t5"), ("merged", "merged", "hc:t6"),
                ("nopane", "in_progress", ""), ("remote", "in_progress", "hc:mbp/t7"), ("tui", "in_progress", "w1:p2"),
            )
        }
        self.tui._agents = [{"pane_id": "w9:p1", "name": "x"}]  # herdr answers, and no agent runs in w1:p2
        self.assertEqual(self.offline_ids(), {ids["gone"], ids["review"], ids["asks"], ids["tui"]})
        state = state_view.dash_state(ctx=self.ctx)
        gone = next(t for t in state["tasks"] if t["id"] == ids["gone"])
        self.assertEqual(gone["status"], "in_progress")  # the status is not changed for the PM
        self.tui._agents = []                             # herdr says nothing: the TUI pane is not judged
        self.assertNotIn(ids["tui"], self.offline_ids())
        self.hc.live = None                               # hc says nothing: no hc terminal is judged
        self.assertEqual(self.offline_ids(), set())

    def test_a_project_whose_only_work_is_offline_is_not_working(self):
        gone = self.task("gone", "in_progress", "hc:t2")
        self.assertEqual(self.working(), 0)
        self.assertEqual(self.ledger.load(gone)["status"], "in_progress")  # the ledger is left as it is
        self.task("live", "in_progress", "hc:t1")
        self.assertEqual(self.working(), 1)
        self.hc.live = None                               # hc says nothing: in progress counts as before
        self.assertEqual(self.working(), 2)

    def test_reattach_resumes_the_session_that_reports_on_the_task(self):
        tid = self.task("a", branch="dev/a")
        worker = self.session(self.repo, "s-worker", f"brief… pm.py update {tid} --status review --commit <sha>")
        # Newer, and naming the task, but not its agent: the PM, and a reviewer of the task.
        self.session(self.repo, "s-pm", f"You are pm-x, {agents_sessions.PM_SESSION_MARK}. dispatched {tid}")
        self.session(self.repo, "s-review", f"Review of task {tid}: pm.py update {tid}-review --status done")
        old = Path(self.claude / agents_sessions.claude_folder(self.repo) / "s-worker.jsonl")
        os.utime(old, (1, created_at(self.ledger.load(tid)) + 60))  # older than the others, still after the task began
        self.assertTrue(worker.exists())
        out = self.reattach(tid)
        run = self.started()
        self.assertEqual(run[run.index("--") + 1:], ["claude", "--resume", "s-worker"])
        self.assertEqual(run[run.index("--parent") + 1], "tpm")       # under the PM, as dispatch places a worker
        self.assertEqual(run[run.index("--cwd") + 1], self.repo)
        task = self.ledger.load(tid)
        self.assertEqual(
            (task["pane"], task["status"], task["session"]),
            ("hc:t70", "in_progress", {"kind": "claude", "id": "s-worker"}),
        )
        self.assertIn(("label", "t70", f"task={tid}"), self.hc.raw_calls)
        self.assertIn("s-worker", task["log"][-1]["text"])
        self.assertEqual(len(self.sent()), 1)
        self.assertIn(f"show {tid}", self.sent()[0])
        self.assertIn("resume claude pane=hc:t70", out)
        self.assertNotIn(tid, self.offline_ids())                      # the new terminal is the task's now

    def reviewer(self, folder, sid, tid, zh=False):
        """A reviewer's transcript in the reviewed task's worktree: its opening is the review brief, and later it
        quotes the reviewed task's ledger entries (`pm.py update <id> ...`) verbatim."""
        head = (
            f"审查（只读）任务 #7 {tid}：线程\n不提交、不改文件\n汇报：`pm.py update {tid}-review --status done --note`"
            if zh else f"Review (read-only) of task #7 {tid}: thread\nDo not commit\n"
            f"Report: `pm.py update {tid}-review --status done --note`"
        )
        path = self.session(folder, sid, head)
        reply = json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "reading"}})
        quotes = [
            json.dumps({"type": "user", "message": {"content": f"log: pm.py update {tid} --status review --commit abc{n}"}})
            for n in range(6)
        ]
        path.write_text(path.read_text() + "\n".join([reply, *quotes]) + "\n")
        return path

    def test_a_reviewers_session_in_the_worktree_is_not_the_workers(self):
        for zh in (False, True):
            with self.subTest(zh=zh):
                tid = self.task(f"rv{int(zh)}", branch="dev/rv", worker={"kind": "claude", "model": "opus"})
                self.session(self.repo, f"s-worker{int(zh)}", f"brief… pm.py update {tid} --status review")
                worker = self.claude / agents_sessions.claude_folder(self.repo) / f"s-worker{int(zh)}.jsonl"
                os.utime(worker, (1, created_at(self.ledger.load(tid)) + 60))  # older than the reviewer's
                self.reviewer(self.repo, f"s-review{int(zh)}", tid, zh=zh)
                self.assertEqual(workers_sessions.find_session_for(self.ctx, self.ledger.load(tid))["id"], f"s-worker{int(zh)}")
                worker.unlink()  # only the reviewer's is left: nothing is the worker's
                self.assertIsNone(workers_sessions.find_session_for(self.ctx, self.ledger.load(tid)))
                self.assertEqual(workers_reattach.reattach_plan_for(self.ctx, self.ledger.load(tid))["how"], "fresh")

    def test_a_task_dispatched_to_agy_never_resumes_a_claude_or_codex_session(self):
        tid = self.task("agy", branch="dev/agy", worker={"kind": "agy", "model": "opus"})
        self.session(self.repo, "s-claude", f"brief… pm.py update {tid} --status review")
        path = self.codex / "2026" / "11" / "14" / "rollout-agy.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": "c-agy", "cwd": self.repo}}) + "\n"
            + json.dumps({"type": "message", "text": f"pm.py update {tid} --status review"}) + "\n"
        )
        self.assertIsNone(workers_sessions.find_session_for(self.ctx, self.ledger.load(tid)))
        plan = workers_reattach.reattach_plan_for(self.ctx, self.ledger.load(tid))
        self.assertEqual((plan["how"], plan["kind"], plan["session"]), ("fresh", "agy", ""))

    def test_a_session_recorded_on_another_task_is_not_this_ones(self):
        tid = self.task("own", branch="dev/own", worker={"kind": "claude"})
        self.session(self.repo, "s-theirs", f"brief… pm.py update {tid} --status review")
        self.task("own-review", review_of=tid, worker={"kind": "claude"}, prior_sessions=["s-theirs"])
        self.assertIsNone(workers_sessions.find_session_for(self.ctx, self.ledger.load(tid)))

    def test_a_review_reattached_finds_its_reviewers_session(self):
        tid = self.task("rr", branch="dev/rr", worker={"kind": "claude"}, session={"kind": "claude", "id": "s-w"})
        rid = self.task("rr-review", review_of=tid, worker={"kind": "claude"})
        self.session(self.repo, "s-w", f"brief… pm.py update {tid} --status review --commit abc")
        self.reviewer(self.repo, "s-r", tid)
        self.assertEqual(
            agents_sessions.session_score((self.claude / agents_sessions.claude_folder(self.repo) / "s-r.jsonl").read_text(), rid),
            2,
        )
        self.assertEqual(workers_sessions.find_session_for(self.ctx, self.ledger.load(rid))["id"], "s-r")
        plan = workers_reattach.reattach_plan_for(self.ctx, self.ledger.load(rid))
        self.assertEqual((plan["how"], plan["session"]), ("resume", "s-r"))

    def test_state_reads_the_ledger_a_fixed_number_of_times_whatever_tasks_await_discovery(self):
        # Each open Claude task without a recorded session goes through discovery (task_session_info), which
        # excludes sessions claimed by other tasks: from the task list dash_state already read, not a new read.
        def reads(n):
            if self.ctx.home.tasks.exists():
                for path in self.ctx.home.tasks.glob(f"{self.name}-*.json"):
                    path.unlink()
            for k in range(n):
                self.task(f"d{k}", pane="hc:t1", worker={"kind": "claude"})
            with mock.patch.object(self.ctx.store, 'tasks', wraps=self.ctx.store.tasks) as spy:
                state_view.dash_state(ctx=self.ctx)
            return spy.call_count

        self.assertIsNotNone(agents_sessions.sessions_reader(cache=True))  # discovery runs at all
        self.assertEqual(reads(1), reads(6))

    def test_reattach_makes_sure_a_deliverer_watches_the_agent_brought_back(self):
        tid = self.task("dl", branch="dev/dl")
        self.ctx.procs.spawned.clear()
        self.reattach(tid)
        delivered = [s["args"][1] for s in self.ctx.procs.spawned if s["args"][:1] == ["deliver"]]
        self.assertEqual(delivered, [self.ledger.load(tid)["repo"]])

    def test_a_session_started_in_a_folder_above_the_repo_is_found(self):
        tid = self.task("up", owner="self")
        parent_dir = str(Path(self.repo).parent)
        self.session(parent_dir, "s-up", f"pm.py log {tid} 定位中", cwd=parent_dir)
        plan = workers_reattach.reattach_plan_for(self.ctx, self.ledger.load(tid))
        self.assertEqual((plan["how"], plan["argv"][-2:], plan["cwd"]), ("resume", ["--resume", "s-up"], parent_dir))

    def test_reattach_resumes_a_codex_session(self):
        tid = self.task("cx", log=[{
            "at": "2026-11-14 01:00", "by": "hc:tpm", "text": "dispatched to w-cx (codex gpt-x high)",
        }])
        path = self.codex / "2026" / "11" / "14" / "rollout-1.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": "c-123", "cwd": self.repo}}) + "\n"
            + json.dumps({"type": "message", "text": f"pm.py update {tid} --status review"}) + "\n"
        )
        self.reattach(tid)
        run = self.started()
        cmd = run[run.index("--") + 1:]
        self.assertEqual(cmd[:2], ["codex", "resume"])
        self.assertEqual(cmd[-1], "c-123")
        self.assertIn("gpt-x", cmd)
        self.assertEqual(run[run.index("--name") + 1], f"{self.name}-cx")

    def test_without_a_session_a_fresh_agent_gets_the_tasks_context(self):
        brief = self.root / "fresh-brief" / "brief.md"
        brief.parent.mkdir()
        brief.write_text("把断开的线程标出来")
        tid = self.task("new", brief=str(brief), agent="w-new", log=[
            {"at": "2026-11-14 01:00", "by": "hc:tpm", "text": "dispatched to w-new (codex gpt-x high)"},
            {"at": "2026-11-14 02:00", "by": "hc:t2", "text": "做了一半：state 已加字段"},
        ])
        self.session(self.repo, "s-other", "an unrelated session")
        out = self.reattach(tid)
        run = self.started()
        self.assertEqual(run[run.index("--") + 1:], self.ctx.agents.start_argv("codex", "gpt-x", "high"))
        self.assertEqual(run[run.index("--name") + 1], "w-new")
        text = self.sent()[0]
        for part in ("线程 new", tid, "把断开的线程标出来", "做了一半：state 已加字段", f"update {tid} --status review"):
            self.assertIn(part, text)
        task = self.ledger.load(tid)
        self.assertEqual((task["pane"], task["status"]), ("hc:t70", "in_progress"))
        self.assertNotIn("session", task)
        self.assertIn("fresh codex", out)

    def test_reattach_refuses_live_or_closed_work(self):
        live, merged = self.task("live", pane="hc:t1"), self.task("done", status="merged")
        for tid in (live, merged):
            with self.assertRaises(SystemExit):
                self.reattach(tid)
        self.assertFalse([c for c in self.hc.raw_calls if c[0] == "run"])
        self.assertEqual(self.ledger.load(live)["pane"], "hc:t1")

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
        self.assertEqual(self.ledger.load(tid)["workspace"], "")

    def test_a_herdr_tui_pm_gets_the_agent_in_a_tab_of_its_workspace(self):
        (self.ctx.home.registrations / f"{project_slug(self.repo)}.json").write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo,
            "pane": "wS:p1", "workspace": "wS",
        }))
        seen = []
        tui_agents = [{"pane_id": "wS:p1", "name": pm_name(self.repo), "workspace_id": "wS"}]

        class _TuiReattach(FakeTui):
            def herdr(self, *args, session=None):
                seen.append(args)
                if args[:2] == ("tab", "create"):
                    return {"tab": {"tab_id": "wS:t9"}, "root_pane": {"pane_id": "wS:p9"}}
                if args[:2] == ("agent", "list"):
                    return {"agents": list(tui_agents)}
                return {}

            def agents(self, *, session=None):
                return list(tui_agents)

        self.ctx.tui = _TuiReattach(agents=tui_agents)
        tid = self.nested("tui", pane="wS:p3", workspace="wS")  # its old pane: no agent runs there
        self.session(self.repo, "s-tui", f"pm.py update {tid} --note 定位中")
        self.assertIn(tid, self.offline_ids())
        out = self.reattach(tid)
        create = next(c for c in seen if c[:2] == ("tab", "create"))
        self.assertEqual(create[create.index("--workspace") + 1], "wS")
        self.assertEqual(create[create.index("--cwd") + 1], self.repo)   # where the session was started
        run = next(c for c in seen if c[:2] == ("pane", "run"))
        self.assertEqual(run[2], "wS:p9")
        argv = shlex.split(run[3])
        self.assertEqual(argv[:3], ["claude", "--resume", "s-tui"])
        self.assertIn(f"show {tid}", argv[3])                            # the prompt goes on its command line
        self.assertFalse([c for c in self.hc.raw_calls if c[0] == "run"])  # no hc terminal anywhere
        task = self.ledger.load(tid)
        self.assertEqual((task["pane"], task["workspace"], task["status"]), ("wS:p9", "wS", "in_progress"))
        self.assertIn("pane=wS:p9", out)

    def test_no_tab_in_the_tui_pms_workspace_means_nothing_changes(self):
        (self.ctx.home.registrations / f"{project_slug(self.repo)}.json").write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "wS:p1",
        }))
        tui_agents = [{"pane_id": "wS:p1", "name": pm_name(self.repo), "workspace_id": "wS"}]

        class _NoTabTui(FakeTui):
            def herdr(self, *args, session=None):
                return None

            def agents(self, *, session=None):
                return list(tui_agents)

        self.ctx.tui = _NoTabTui(agents=tui_agents)
        tid = self.task("notab", pane="wS:p3")
        with self.assertRaises(SystemExit):
            self.reattach(tid)
        self.assertFalse([c for c in self.hc.raw_calls if c[0] == "run"])
        self.assertEqual(self.ledger.load(tid)["pane"], "wS:p3")

    def test_only_a_sessions_opening_makes_it_a_pms(self):
        reply = json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "ok"}})
        hook = json.dumps({"attachment": {"type": "hook_success", "content": f"You are pm-x, {agents_sessions.PM_SESSION_MARK}."}})
        self.assertTrue(agents_sessions.pm_session(hook + "\n" + reply))
        self.assertTrue(agents_sessions.pm_session(json.dumps({"type": "user", "message": {"content": "[from pm.py rotate] 你是"}})))
        # A worker that later reads or quotes the PM's words is still the worker.
        worker = "\n".join([
            json.dumps({"type": "user", "message": {"content": "brief: update x-1 --status review"}}),
            reply,
            json.dumps({"type": "user", "message": {"content": f"cat: {agents_sessions.PM_SESSION_MARK}"}}),
        ])
        self.assertFalse(agents_sessions.pm_session(worker))
        self.assertEqual(agents_sessions.session_score(worker, "x-1"), 2)

    def test_a_lock_left_by_a_killed_reattach_does_not_hold(self):
        tid = self.task("lock")
        lock = self.ctx.home.root / "reattach" / f"{tid}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        dead = subprocess.Popen(["true"])
        dead.wait()
        lock.write_text(f"{dead.pid} 0\n")                     # its process is gone: taken over at once
        self.reattach(tid)
        self.assertFalse(lock.exists())
        self.assertEqual(self.ledger.load(tid)["pane"], "hc:t70")
        tid = self.task("held")
        lock = self.ctx.home.root / "reattach" / f"{tid}.lock"
        lock.write_text(f"{os.getpid()} 0\n")                  # a reattach that still runs
        with self.assertRaises(SystemExit):
            self.reattach(tid)
        os.utime(lock, (1, 1))                                 # unless it has run for more than five minutes
        self.assertTrue(osutil.stale_lock(lock))
        lock.unlink()

    def test_the_agents_own_ledger_writes_record_its_session(self):
        tid = self.task("own", pane="hc:t1")
        ctx_worker = make_ctx(
            self.root / "ctx",
            pane="hc:t1",
            hc=self.hc,
            tui=self.tui,
            git=self.ctx.git,
            env={"CLAUDE_CODE_SESSION_ID": "s-own"},
            out=StdOutput(),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmd.cmd_update(argparse.Namespace(
                id=tid, note="进展", keep=False, option=None,
                **{f: None for f in FIELDS},
            ), ctx=ctx_worker)
        self.assertEqual(self.ledger.load(tid)["session"], {"kind": "claude", "id": "s-own"})
        # the PM writing on its parked task: not its agent
        other = self.task("parked", pane="hc:tpm")
        ctx_pm = make_ctx(
            self.root / "ctx",
            pane="hc:tpm",
            hc=self.hc,
            tui=self.tui,
            git=self.ctx.git,
            env={"CLAUDE_CODE_SESSION_ID": "s-own"},
            out=StdOutput(),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmd.cmd_update(argparse.Namespace(
                id=other, note="进展", keep=False, option=None,
                **{f: None for f in FIELDS},
            ), ctx=ctx_pm)
        self.assertNotIn("session", self.ledger.load(other))


class CloseWorkers(unittest.TestCase):
    CONFIG = {"workers": {"close_on_close": True}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-close-workers-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _ctx(self, *, pane: str = "", terminals=None, config=None, clock=None, git=None):
        clk = clock if clock is not None else FakeClock()
        hc = FakeHc(terminals=terminals or {}, clock=clk)
        return make_ctx(
            self.root / "ctx",
            pane=pane,
            hc=hc,
            tui=FakeTui(server_ok=False),
            config=self.CONFIG if config is None else config,
            clock=clk,
            git=git if git is not None else GitRepo(),
            out=StdOutput(),
        )

    def task(self, **kw):
        return {"id": "p-1", "status": "done", "pane": "hc:t9", "repo": "/w/proj", "dispatched": True, **kw}

    def _term(self, status="idle", labels=None):
        return {"state": "live", "status": {"state": status}, "labels": labels if labels is not None else {"task": "p-1"}}

    def _ended_terms(self, hc: FakeHc):
        return [c[1] for c in hc.calls if c[:1] == ("kill",)]

    def test_idle_worker_is_ended(self):
        ctx = self._ctx(terminals={"t9": self._term()})
        self.assertEqual(Workers(ctx).close_worker(self.task()), "terminal hc:t9")
        self.assertNotIn("t9", ctx.hc.terminals)

    def test_working_worker_is_kept(self):
        ctx = self._ctx(terminals={"t9": self._term("working")})
        self.assertIn("kept", Workers(ctx).close_worker(self.task()))
        self.assertIn("t9", ctx.hc.terminals)

    def test_unlabelled_or_pm_terminal_is_kept(self):
        for labels in ({"task": "other"}, {"pm": "proj", "task": "p-1"}, {"where": "x"}):
            ctx = self._ctx(terminals={"t9": self._term(labels=labels)})
            self.assertEqual(Workers(ctx).close_worker(self.task(worker_pane="hc:t9")), "")
            self.assertIn("t9", ctx.hc.terminals)

    def test_a_session_that_registered_its_own_work_is_kept(self):
        # Its terminal is the user's conversation, even when something labelled it with the task (a reattach).
        own = self.task(dispatched=False)
        ctx = self._ctx(pane="hc:t9", terminals={"t9": self._term()})
        self.assertEqual(Workers(ctx).close_worker(own), "")
        self.assertEqual(Workers(ctx).close_reported({**own, "status": "review"}), "")
        self.assertIn("t9", ctx.hc.terminals)
        self.assertEqual(ctx.procs.spawned, [])

    def test_shared_terminal_is_kept(self):
        ctx = self._ctx(terminals={"t9": self._term()})
        Ledger(ctx).save(self.task(id="p-2", status="in_progress"))
        self.assertIn("kept", Workers(ctx).close_worker(self.task()))
        self.assertIn("t9", ctx.hc.terminals)

    def test_off_unless_configured(self):
        for cfg in ({}, {"workers": {"close_on_close": False}}):  # off by default: a reviewer stays until retire
            ctx = self._ctx(terminals={"t9": self._term()}, config=cfg)
            self.assertEqual(Workers(ctx).close_worker(self.task()), "")
            self.assertIn("t9", ctx.hc.terminals)

    def test_retire_ends_a_worker_that_had_no_worktree(self):
        repo = str(self.root / "repo-here")
        Path(repo).mkdir()
        ctx = self._ctx(
            terminals={"t9": {"state": "live", "status": {"state": "idle"}, "labels": {"task": "here-1"}}},
            config={},
        )
        Ledger(ctx).save({
            "id": "here-1", "project": "proj", "repo": repo, "status": "review", "owner": "pm",
            "base": "main", "created": ctx.clock.now(), "title": "t", "pane": "hc:t9",
            "dispatched": True, "in_place": repo,
        })
        with contextlib.redirect_stdout(io.StringIO()):
            workers_cmd.cmd_retire(argparse.Namespace(id="here-1", force=False), ctx=ctx)
        self.assertNotIn("t9", ctx.hc.terminals)
        self.assertIn("terminal hc:t9", Ledger(ctx).load("here-1")["log"][-1]["text"])

    def test_own_worker_ends_once_its_turn_is_over(self):
        ctx = self._ctx(pane="hc:t9", terminals={"t9": self._term("working")})
        self.assertIn("t9", Workers(ctx).close_worker(self.task()))
        self.assertIn("t9", ctx.hc.terminals)
        self.assertEqual(len(ctx.procs.spawned), 1)
        args = ctx.procs.spawned[0]["args"]
        self.assertEqual(args[:8], ["close-worker", "t9", "--task", "p-1", "--quiet", "20", "--timeout", "7200"])
        self.assertIn("--while", args)
        self.assertEqual(set(args[args.index("--while") + 1].split(",")), set(CLOSED))

    def test_close_worker_waits_for_quiet(self):
        clock = FakeClock()
        ctx = self._ctx(
            terminals={
                "t9": [
                    {"state": "live", "status": {"state": "working"}, "labels": {"task": "p-1"}},
                    {"state": "live", "status": {"state": "idle"}, "labels": {"task": "p-1"}},
                    {"state": "live", "status": {"state": "idle"}, "labels": {"task": "p-1"}},
                    {"state": "live", "status": {"state": "idle"}, "labels": {"task": "p-1"}},
                ]
            },
            clock=clock,
        )
        workers_cmd.cmd_close_worker(argparse.Namespace(terminal="t9", task="p-1", quiet=20, timeout=600), ctx=ctx)
        self.assertNotIn("t9", ctx.hc.terminals)

        ctx2 = self._ctx(terminals={"t9": {"state": "live", "labels": {"task": "another"}}})
        workers_cmd.cmd_close_worker(argparse.Namespace(terminal="t9", task="p-1", quiet=0, timeout=60), ctx=ctx2)
        self.assertIn("t9", ctx2.hc.terminals)  # relabelled for other work: left alone

    def test_close_worker_stops_once_the_task_moves_on(self):
        # A reported worker sent back to work, or blocked on a question for the user, is not closed.
        for status, ended in (("in_progress", False), ("blocked", False), ("review", True)):
            ctx = self._ctx(
                terminals={"t9": {"state": "live", "status": {"state": "idle"}, "labels": {"task": "cw-r"}}},
            )
            Ledger(ctx).save({
                "id": "cw-r", "project": "proj", "repo": "/w/proj", "status": status,
                "base": "main", "created": ctx.clock.now(), "title": "t",
            })
            workers_cmd.cmd_close_worker(
                argparse.Namespace(terminal="t9", task="cw-r", quiet=0, timeout=60, while_="review")
            , ctx=ctx)
            self.assertEqual("t9" not in ctx.hc.terminals, ended, status)

    def test_reported_worker_closes_only_when_configured(self):
        reported = self.task(status="review")
        ctx = self._ctx(pane="hc:t9", terminals={"t9": self._term()})
        self.assertEqual(Workers(ctx).close_reported(reported), "")  # off by default
        self.assertEqual(ctx.procs.spawned, [])
        ctx.home.config.write_text(json.dumps({"workers": {"close_reported": True, "idle_minutes": 45}}))
        self.assertIn("45", Workers(ctx).close_reported(reported))
        self.assertEqual(Workers(ctx).close_reported({**reported, "pane": "hc:t8"}), "")  # only from the worker's own terminal
        self.assertEqual(len(ctx.procs.spawned), 1)
        self.assertEqual(
            ctx.procs.spawned[0]["args"],
            ["close-worker", "t9", "--task", "p-1", "--quiet", str(45 * 60), "--timeout", str(45 * 60 + 4 * 3600), "--while", "review"],
        )

    def test_update_closes_and_keep_keeps(self):
        repo = str(self.root / "repo-upd-close")
        Path(repo).mkdir()
        ctx = self._ctx(
            terminals={
                "t9": {"state": "live", "status": {"state": "idle"}, "labels": {"task": "cw-a"}},
                "t8": {"state": "live", "status": {"state": "idle"}, "labels": {"task": "cw-b"}},
            },
        )
        ledger = Ledger(ctx)
        base = {
            "project": "proj", "repo": repo, "status": "review", "owner": "pm",
            "base": "main", "created": ctx.clock.now(), "title": "t", "pane": "hc:t9", "dispatched": True,
        }
        ledger.save({**base, "id": "cw-a"})
        ledger.save({**base, "id": "cw-b", "pane": "hc:t8"})
        args = lambda i, keep=False: argparse.Namespace(
            id=i, status="done", note="ok", keep=keep, option=None, why=None, recommend=False
        )
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmd.cmd_update(args("cw-a"), ctx=ctx)
            ledger_cmd.cmd_update(args("cw-b", keep=True), ctx=ctx)
        self.assertNotIn("t9", ctx.hc.terminals)
        self.assertIn("t8", ctx.hc.terminals)

    def test_idle_workers_lists_and_closes(self):
        clock = FakeClock()
        repo_dir = self.root / "repo-idle"
        repo_dir.mkdir()
        git = GitRepo()
        repo = git.project_root(repo_dir)
        old = (clock.time() - 3600) * 1000
        terms = {
            "t1": {"state": "live", "status": {"state": "idle"}, "status_ms": old, "labels": {"task": "iw-a"}},
            "t2": {"state": "live", "status": {"state": "working"}, "status_ms": old, "labels": {"task": "iw-b"}},
            "t3": {"state": "live", "status": None, "status_ms": old, "labels": {"task": "iw-c"}},
            "t4": {"state": "live", "status": {"state": "idle"}, "status_ms": old, "labels": {"task": "iw-d"}},
            "t5": {"state": "live", "status": {"state": "idle"}, "status_ms": old, "labels": {"task": "iw-e"}},
        }
        ctx = self._ctx(terminals=terms, clock=clock, git=git)
        ledger = Ledger(ctx)
        base = {
            "project": "proj", "repo": repo, "owner": "pm", "base": "main",
            "created": clock.now(), "title": "t", "dispatched": True,
        }
        ledger.save({**base, "id": "iw-a", "status": "review", "pane": "hc:t1"})
        ledger.save({**base, "id": "iw-b", "status": "in_progress", "pane": "hc:t2"})
        ledger.save({**base, "id": "iw-c", "status": "review", "pane": "hc:t3"})
        ledger.save({**base, "id": "iw-d", "status": "review", "pane": "hc:t4", "dispatched": False})  # its own work
        ledger.save({**base, "id": "iw-e", "status": "blocked", "pane": "hc:t5"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            workers_cmd.cmd_idle_workers(argparse.Namespace(repo=repo, minutes=None, close=[], exited=False, json=False), ctx=ctx)
        listed = out.getvalue()
        self.assertIn("iw-a", listed)
        self.assertIn("no-status", listed)  # listed, but ended only when named
        self.assertNotIn("iw-b", listed)  # at work
        self.assertNotIn("iw-d", listed)  # a session's own work is not a worker pm.py started
        self.assertIn("iw-e", listed)  # idle, but its task waits for the user: listed, not ended without its name
        self.assertNotIn("t1", ctx.hc.terminals)
        self.assertIn("t5", ctx.hc.terminals)
        with contextlib.redirect_stdout(io.StringIO()):
            workers_cmd.cmd_idle_workers(argparse.Namespace(repo=repo, minutes=None, close=["hc:t5"], exited=False, json=False), ctx=ctx)
        self.assertNotIn("t5", ctx.hc.terminals)  # named: ended

    def test_status_lists_reported_work_with_an_open_terminal(self):
        repo = str(self.root / "repo-status")
        Path(repo).mkdir()
        ctx = self._ctx(
            terminals={
                "t1": {"address": "t1", "state": "live", "status": "idle"},
                "t2": {"address": "t2", "state": "live", "status": "working"},
            },
        )
        ledger = Ledger(ctx)
        base = {
            "project": Path(repo).name, "repo": repo, "owner": "pm", "base": "main",
            "created": ctx.clock.now(), "title": "登录修复", "dispatched": True,
        }
        ledger.save({**base, "id": "st-a", "status": "review", "pane": "hc:t1"})
        ledger.save({**base, "id": "st-b", "status": "review", "pane": "hc:t2"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status_view.cmd_status(argparse.Namespace(repo=repo, all=False, closed=False), ctx=ctx)
        text = out.getvalue()
        section = text[text.index("worker terminal still open"):] if "worker terminal still open" in text else ""
        self.assertIn("st-a  hc:t1", section)
        self.assertNotIn("st-b", section)


if __name__ == "__main__":
    unittest.main()
