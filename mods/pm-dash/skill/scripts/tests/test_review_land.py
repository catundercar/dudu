"""Landing, code review, research collection, review-chain protection, and delegated execution tests.

Moved from test_pm.py (`LandAndReview` 12, `ResearchCollectionTests` 5, `ReviewChainAndStateHelpers` 7)
and all of `test_pm_delegate.py` (`DelegatedMergeTests` 8, `StuckPromptAndTriageTests` 5,
`AsyncSendHintsAndCompatTests` 2) — 39 tests total (Stage 6b2).

Every test runs on its own `make_ctx` Context with `FakeHc`, `FakeTui`, `FakeProcs`, `FakeClock`, real
`GitRepo` over throwaway repositories, and `tests.legacy_bind.bound` around Layer 4 `cmd_*` calls.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-review-land")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

from pmlib.agents.base import is_seat_argv, unwrap_seat_argv  # noqa: E402
from pmlib.commands import helpers as helpers_cmds  # noqa: E402
from pmlib.commands import ledger as ledger_cmds  # noqa: E402
from pmlib.commands import manager as manager_cmds  # noqa: E402
from pmlib.commands import review as review_cmds  # noqa: E402
from pmlib.commands import workers as workers_cmds  # noqa: E402
from pmlib.context import StdOutput  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.helpers.records import helper_entries  # noqa: E402
from pmlib.home import Home, project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.transition import FIELDS  # noqa: E402
from pmlib.manager.launch import PI_COMPACT_EXT, narrow_pm, pm_argv, pm_model, successor_argv  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import pm_name  # noqa: E402
from pmlib.review.land import LAND_CONFLICTS, LAND_REFUSED  # noqa: E402
from pmlib.terminals.screen import classify_stuck_screen, known_prompt_action, trust_keys, update_keys  # noqa: E402
from pmlib.views import state as state_view, status as status_view  # noqa: E402
from pmlib.project.readmodel import Projects  # noqa: E402
from pmlib.workers.dispatch import review_placement_for, worker_argv_for  # noqa: E402
from pmlib.workers.lifecycle import close_worker_for  # noqa: E402
from pmlib.workers.reattach import start_beside_pm_for  # noqa: E402
from pmlib.workers.service import Workers  # noqa: E402
from tests.fakes import FakeClock, FakeHc, FakeProcs, FakeTui, make_ctx, queued_sends, run_spawned_drains  # noqa: E402

PM_SCRIPT = SCRIPTS / "pm.py"
_OK_CMD = f'"{sys.executable}" -c "pass"' if os.name == "nt" else "true"
_FAIL_CMD = f'"{sys.executable}" -c "import sys; print(\'broken\'); sys.exit(1)"' if os.name == "nt" else "echo broken; false"
_STUCK_CMD = (
    f'"{sys.executable}" -c "import pathlib, sys; p=pathlib.Path(\'new.txt\'); '
    f'p.write_text(p.read_text()+\'changed\\n\'); sys.exit(1)"'
    if os.name == "nt" else "echo changed >> new.txt; false"
)
_SLOW_CMD = (
    f'"{sys.executable}" -c "import time; print(\'started\', flush=True); time.sleep(30)"'
    if os.name == "nt" else "echo started; sleep 30"
)
_SLEEP_CMD = f'"{sys.executable}" -c "import time; time.sleep(30)"' if os.name == "nt" else "sleep 30"
_CHECK_NEW_CMD = (
    f'"{sys.executable}" -c "import pathlib, sys; sys.exit(0 if pathlib.Path(\'new.txt\').is_file() else 1)"'
    if os.name == "nt" else "test -f new.txt"
)
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class RecordingHc(FakeHc):
    """FakeHc that records `run(...)` and `kill(...)` / `keys(...)` calls for assertions."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.run_records: list[dict] = []
        self.killed: list[str] = []
        self.key_calls: list[tuple[str, tuple[str, ...]]] = []

    def run(
        self,
        argv,
        *,
        name: str = "",
        cwd="",
        labels=(),
        bg: bool = True,
        parent: str = "",
        keep: bool = False,
        no_parent: bool = False,
        placement=(),
        env=None,
    ):
        labels_list = list(labels)
        placement_list = list(placement)
        row = super().run(
            argv,
            name=name,
            cwd=cwd,
            labels=labels_list,
            bg=bg,
            parent=parent,
            keep=keep,
            no_parent=no_parent,
            placement=placement_list,
            env=env,
        )
        if row is not None:
            addr = row["address"]
            self.terminals[addr]["turn"] = 0
            self.run_records.append({
                "address": addr,
                "argv": list(argv),
                "name": name,
                "cwd": str(cwd),
                "labels": labels_list,
                "placement": placement_list,
                "env": env,
            })
        return row

    def kill(self, term: str, *, errors: bool = False):
        key = term[3:] if term.startswith("hc:") else term
        self.killed.append(key)
        return super().kill(term, errors=errors)

    def keys(self, term: str, *keys: str, errors: bool = False):
        key = term[3:] if term.startswith("hc:") else term
        self.key_calls.append((key, tuple(keys)))
        return super().keys(term, *keys, errors=errors)


class SteppingClock(FakeClock):
    """FakeClock that invokes an optional callback on each sleep(dt) call."""

    def __init__(self, *args, on_sleep=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._on_sleep = on_sleep

    def sleep(self, seconds: float) -> None:
        super().sleep(seconds)
        if self._on_sleep is not None:
            self._on_sleep(seconds)


class ReviewLandCase(unittest.TestCase):
    """Isolated temporary ledger, fake terminals, and real git per test."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        env_patch = mock.patch.dict(os.environ, GIT_IDENTITY)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.clock = FakeClock("2026-11-23 10:00:00", mono=100.0)
        self.hc = RecordingHc(clock=self.clock)
        self.tui = FakeTui()
        self.wt_root = self.base / "worktrees"
        self.git = GitRepo(worktree_home_fn=lambda repo: self.wt_root / Path(repo).name)
        self.home = Home(self.base / "ledger")
        self.procs = FakeProcs(self.home, env={"PM_HOME": str(self.home.root)})
        self.ctx = self._ctx("")

    def _ctx(self, pane: str = "", *, clock: FakeClock | None = None, config: dict | None = None):
        return make_ctx(
            self.base,
            pane=pane,
            hc=self.hc,
            tui=self.tui,
            git=self.git,
            procs=self.procs,
            clock=clock or self.clock,
            out=StdOutput(),
            config=config,
        )

    def be(self, pane: str) -> None:
        self.ctx = self._ctx(pane)

    def _write_cfg(self, cfg: dict | None) -> None:
        if cfg is None:
            self.ctx.home.config.unlink(missing_ok=True)
        else:
            self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
            self.ctx.home.config.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_raw(self, rec: dict) -> None:
        Ledger(self.ctx).save(dict(rec))

    def load_raw(self, task_id: str) -> dict:
        return Ledger(self.ctx).load(task_id).raw


class LandAndReview(ReviewLandCase):
    def make_repo(self, name: str = "land-repo"):
        """A throwaway repository with a main branch and a task branch dev/x that adds new.txt."""
        repo = (self.base / "repos" / name).resolve()
        repo.mkdir(parents=True)

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                check=True, capture_output=True, text=True,
            ).stdout

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

    def task(self, repo: Path, task_id: str, **extra) -> None:
        self.save_raw({
            "id": task_id, "title": "加一行", "project": repo.name, "repo": str(repo), "status": "review",
            "owner": "pm", "base": "main", "branch": "dev/x", "dispatched": True, "created": self.clock.now(),
            **extra,
        })

    def land(self, task_id: str, keep: bool = False, timeout: int = 600) -> tuple[int, str]:
        out, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                review_cmds.cmd_land(argparse.Namespace(id=task_id, keep=keep, message=None, timeout=timeout), ctx=self.ctx)
        except SystemExit as stop:
            code = stop.code
        return code, out.getvalue()

    def verify(self, repo: Path, text: str) -> None:
        path = self.ctx.home.project_for(str(repo)).verify
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def clean(self, git) -> None:
        self.assertEqual(git("status", "--porcelain", "--untracked-files=no"), "")
        self.assertNotEqual(
            subprocess.run(
                ["git", "-C", git("rev-parse", "--show-toplevel").strip(), "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                capture_output=True,
            ).returncode,
            0,
        )

    def test_land_refuses_with_exit_2_and_changes_nothing(self) -> None:
        repo, git = self.make_repo("r-none")
        self.task(repo, "l-none")
        code, out = self.land("l-none")
        self.assertEqual(code, 2)
        self.assertIn(str(self.ctx.home.project_for(str(repo)).verify), out)
        self.verify(repo, "# only a comment\n\n")  # counts as no checks
        self.assertEqual(self.land("l-none")[0], 2)
        self.verify(repo, f"{_OK_CMD}\n")
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
        self.assertEqual(self.load_raw("l-none")["status"], "review")

    def test_a_failing_check_aborts_and_leaves_the_checkout_clean(self) -> None:
        repo, git = self.make_repo("r-fail")
        self.task(repo, "l-fail")
        self.verify(repo, f"# the checks\n{_OK_CMD}\n{_FAIL_CMD}\n")
        code, out = self.land("l-fail")
        self.assertEqual(code, 1)
        self.assertIn(_FAIL_CMD, out)
        self.assertIn("broken", out)
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertFalse((repo / "new.txt").exists())
        self.assertEqual(self.load_raw("l-fail")["status"], "review")
        self.assertIn(_FAIL_CMD, self.load_raw("l-fail")["log"][-1]["text"])

    def test_a_merge_that_cannot_be_undone_is_said_with_exit_5(self) -> None:
        # The check changes a file the merge brought in: git refuses both `merge --abort` and `reset --merge`.
        repo, git = self.make_repo("r-stuck")
        self.task(repo, "l-stuck")
        self.verify(repo, f"{_STUCK_CMD}\n")
        code, out = self.land("l-stuck")
        self.assertEqual(code, 5)
        self.assertIn("could not be undone", out)
        self.assertIn("MERGE_HEAD", out)
        self.assertIn("new.txt", out)
        self.assertNotIn("the merge is aborted", out)

    def test_checks_have_a_time_limit(self) -> None:
        repo, git = self.make_repo("r-slow")
        self.task(repo, "l-slow")
        self.verify(repo, f"{_SLOW_CMD}\n")
        began = time.time()
        code, out = self.land("l-slow", timeout=1)
        self.assertLess(time.time() - began, 10)
        self.assertEqual(code, 1)
        self.assertIn("timed out", out)
        self.assertIn("started", out)
        self.clean(git)

    @unittest.skipIf(os.name == "nt", "Windows TerminateProcess cannot be caught by Python signal handlers")
    def test_land_stopped_by_a_signal_undoes_the_merge(self) -> None:
        repo, git = self.make_repo("r-killed")
        self.task(repo, "l-killed")
        self.verify(repo, f"{_SLEEP_CMD}\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_"))}
        env["PM_HOME"] = str(self.home.root)
        proc = subprocess.Popen(
            [sys.executable, str(PM_SCRIPT), "land", "l-killed"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        for _ in range(100):  # until the merge has started and the check is running
            if (repo / ".git" / "MERGE_HEAD").exists():
                break
            time.sleep(0.05)
        time.sleep(0.5)
        proc.terminate()
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 128 + 15, out)
        self.assertIn("aborted", out)
        self.clean(git)
        self.assertFalse((repo / "new.txt").exists())

    def test_conflicts_abort_with_exit_4(self) -> None:
        repo, git = self.make_repo("r-conflict")
        (repo / "new.txt").write_text("other\n")
        git("add", "new.txt")
        git("commit", "-q", "-m", "conflicting new.txt")
        self.task(repo, "l-conflict")
        self.verify(repo, f"{_OK_CMD}\n")
        code, out = self.land("l-conflict")
        self.assertEqual(code, 4)
        self.assertIn("  new.txt\n", out)
        self.assertEqual(git("status", "--porcelain"), "")

    def test_passing_checks_commit_mark_merged_and_retire(self) -> None:
        repo, git = self.make_repo("r-pass")
        self.task(repo, "l-pass")
        self.verify(repo, f"{_OK_CMD}\n{_CHECK_NEW_CMD}\n")
        code, out = self.land("l-pass")
        self.assertEqual(code, 0, out)
        task = self.load_raw("l-pass")
        self.assertEqual((task["status"], task["commit"]), ("merged", git("rev-parse", "--short", "HEAD").strip()))
        self.assertTrue(task.get("retired"))
        self.assertIn("2", out.splitlines()[0])
        self.assertIn("branch dev/x", out)
        self.assertEqual(git("log", "-1", "--format=%s").strip(), "merge dev/x: 加一行")

    def test_review_makes_sure_a_deliverer_watches_the_reviewer(self) -> None:
        repo, git = self.make_repo("r-deliver")
        git("branch", "-D", "dev/x")  # the task's branch lives in its worktree here
        tree = self.base / "trees" / "tree-deliver"
        tree.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-q", str(tree), "-b", "dev/x")
        self.task(repo, "r-a", worktree=str(tree), brief="/briefs/a.md", agent="w-a")
        slug = project_slug(str(repo))
        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": repo.name}, "status": {"state": "idle"}}
        self.ctx.store.change_registration(slug, lambda _: {
            "name": pm_name(str(repo)), "project": repo.name, "repo": str(repo),
            "runtime": "hc", "terminal": "t1", "pane": "hc:t1", "agent": "claude",
        })
        self.verify(repo, "make test\n")
        self._write_cfg({"lang": "zh", "worker": {"kind": "codex"}, "reviewer": {"kind": "claude", "model": "opus"}})
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_review(argparse.Namespace(id="r-a", name=None, kind=None, model=None, effort=None), ctx=self.ctx)
        delivers = [s["args"] for s in self.procs.spawned if s["args"][:1] == ["deliver"]]
        self.assertEqual(delivers, [["deliver", self.load_raw("r-a")["repo"]]])

    def test_review_is_a_thread_with_a_generated_brief(self) -> None:
        repo, git = self.make_repo("r-brief")
        git("branch", "-D", "dev/x")  # the task's branch lives in its worktree here
        tree = self.base / "trees" / "tree-brief"
        tree.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-q", str(tree), "-b", "dev/x")
        self.task(repo, "r-a", worktree=str(tree), brief="/briefs/a.md", agent="w-a")
        slug = project_slug(str(repo))
        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": repo.name}, "status": {"state": "idle"}}
        self.ctx.store.change_registration(slug, lambda _: {
            "name": pm_name(str(repo)), "project": repo.name, "repo": str(repo),
            "runtime": "hc", "terminal": "t1", "pane": "hc:t1", "agent": "claude",
        })
        self.verify(repo, "make test\n")
        self._write_cfg({"lang": "zh", "worker": {"kind": "codex"}, "reviewer": {"kind": "claude", "model": "opus"}})

        def review():
            with contextlib.redirect_stdout(io.StringIO()):
                review_cmds.cmd_review(argparse.Namespace(id="r-a", name=None, kind=None, model=None, effort=None), ctx=self.ctx)

        review()
        task = self.load_raw("r-a-review")
        brief = Path(task["brief"]).read_text()
        run = self.hc.run_records[0]
        # The reviewer key wins over worker; Claude reviewers keep Edit/Write so they can fix test issues directly.
        self.assertEqual(run["argv"], ["claude", "--model", "opus"])
        self.assertEqual(run["cwd"], str(tree))
        t1 = run["address"]
        self.assertEqual((task["title"], task["pane"], task["status"]), ("审查：加一行", f"hc:{t1}", "in_progress"))
        for part in ("/briefs/a.md", "main...dev/x", "检查清单", "make test", "不改生产代码",
                     "生产代码问题", "测试类问题",
                     "update r-a-review --status done --note", "无阻塞"):
            self.assertIn(part, brief)
        self.assertIn((t1, brief), self.hc.sent)
        # Retiring the review itself ends its reviewer.
        with contextlib.redirect_stdout(io.StringIO()):
            workers_cmds.cmd_retire(argparse.Namespace(id="r-a-review", force=False), ctx=self.ctx)
        self.assertIn(t1, self.hc.killed)
        self.assertTrue(self.load_raw("r-a-review").get("retired"))
        self.assertTrue(tree.exists())  # the task's worktree is not the review's to remove
        # Run again, then retiring the task closes its review and ends the new reviewer's terminal.
        review()
        t2 = self.hc.run_records[1]["address"]
        self.assertFalse(self.load_raw("r-a-review").get("retired"))
        git("merge", "-q", "--no-ff", "-m", "m", "dev/x")
        with contextlib.redirect_stdout(io.StringIO()):
            workers_cmds.cmd_retire(argparse.Namespace(id="r-a", force=False), ctx=self.ctx)
        task = self.load_raw("r-a-review")
        self.assertTrue(task.get("retired"))
        self.assertEqual(task["status"], "done")
        self.assertIn(t2, self.hc.killed)
        self.assertFalse(tree.exists())

    def test_a_review_run_again_after_a_report_counts_a_round(self) -> None:
        repo, git = self.make_repo("r-rounds")
        git("branch", "-D", "dev/x")
        tree = self.base / "trees" / "tree-rounds"
        tree.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-q", str(tree), "-b", "dev/x")
        self.task(repo, "r-n", worktree=str(tree), status="in_progress")  # a task from before rounds: no field

        def review(report=False):
            with contextlib.redirect_stdout(io.StringIO()):
                review_cmds.cmd_review(argparse.Namespace(id="r-n", name=None, kind="claude", model="opus", effort=None), ctx=self.ctx)
                if report:
                    ledger_cmds.cmd_update(argparse.Namespace(
                        id="r-n-review", status="done", keep=False,
                        note=report if isinstance(report, str) else "1. 少一个测试",
                        **{f: None for f in FIELDS if f != "status"},
                    ), ctx=self.ctx)
            return self.load_raw("r-n").get("rounds")

        self.assertIsNone(review(report=True))  # the first review is no round of rework
        self.assertEqual(review(), 1)  # the first one reported: this is the second review
        self.assertEqual(review(report=True), 1)  # the one before never reported (restarted): not counted
        self.assertEqual(review(), 2)
        self.assertEqual(review(report="无阻塞。检查都过了"), 2)  # the one before never reported
        self.assertEqual(review(), 2)  # the one before passed: a re-review is no rework
        self.assertEqual(review(report=True), 2)
        with contextlib.redirect_stdout(io.StringIO()):
            workers_cmds.cmd_retire(argparse.Namespace(id="r-n-review", force=False), ctx=self.ctx)
        self.assertEqual(review(), 2)  # the thread was closed (as an escalation closes it): a fresh start

    def test_review_incremental_rereview_full_flag_and_ancestor_fallback(self) -> None:
        repo, git = self.make_repo("r-inc")
        git("branch", "-D", "dev/x")
        tree = self.base / "trees" / "tree-inc"
        tree.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-q", str(tree), "-b", "dev/x")

        def wt_git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                check=True, capture_output=True, text=True,
            ).stdout.strip()

        (tree / "feat.txt").write_text("v1\n")
        wt_git("add", "feat.txt")
        wt_git("commit", "-q", "-m", "v1")
        c1 = wt_git("rev-parse", "HEAD")

        self.task(repo, "r-inc", worktree=str(tree), brief="/briefs/inc.md", agent="w-inc", commit=c1[:7])
        self._write_cfg({"lang": "zh", "reviewer": {"kind": "claude", "model": "opus"}})

        def run_review(*, full: bool = False) -> str:
            with contextlib.redirect_stdout(io.StringIO()):
                review_cmds.cmd_review(
                    argparse.Namespace(id="r-inc", name=None, kind=None, model=None, effort=None, full=full),
                    ctx=self.ctx,
                )
            return Path(self.load_raw("r-inc-review")["brief"]).read_text(encoding="utf-8")

        def finish_review(note: str = "1. prod issue") -> None:
            with contextlib.redirect_stdout(io.StringIO()):
                ledger_cmds.cmd_update(argparse.Namespace(
                    id="r-inc-review", status="done", keep=False, note=note,
                    **{f: None for f in FIELDS if f != "status"},
                ), ctx=self.ctx)

        # 1. First review: full diff base...branch, does NOT write last_reviewed_commit on start; includes test-issue & no-blockers rules.
        brief1 = run_review()
        self.assertIn("`git diff main...dev/x`", brief1)
        self.assertNotIn("增量复审", brief1)
        self.assertIn("生产代码问题：只报告、不改生产代码", brief1)
        self.assertIn("测试类问题（测试替身失真、断言变弱、隔离泄漏、漏覆盖等）：可直接在本分支修改测试代码", brief1)
        self.assertIn("以「无阻塞」开头", brief1)
        self.assertIsNone(self.load_raw("r-inc").get("last_reviewed_commit"))

        # 2. First review interrupted (never reported done) + worker adds c2 (even if auto_reviewed_commit was set):
        #    MUST still do full review so c1 is not skipped.
        self.save_raw({**self.load_raw("r-inc"), "auto_reviewed_commit": c1})
        (tree / "feat.txt").write_text("v2\n")
        wt_git("add", "feat.txt")
        wt_git("commit", "-q", "-m", "v2")
        c2 = wt_git("rev-parse", "HEAD")
        c2_short = wt_git("rev-parse", "--short", c2)

        brief_after_abort = run_review()
        self.assertNotIn("增量复审", brief_after_abort)
        self.assertIn("`git diff main...dev/x`", brief_after_abort)
        self.assertIsNone(self.load_raw("r-inc").get("last_reviewed_commit"))

        # 3. Completing review (done) records last_reviewed_commit = c2; same-commit re-run falls back to full.
        finish_review("1. prod bug")
        self.assertEqual(self.load_raw("r-inc").get("last_reviewed_commit"), c2)
        brief_same = run_review()
        self.assertNotIn("增量复审", brief_same)
        self.assertIn("`git diff main...dev/x`", brief_same)

        # 4. Worker pushes fix c3: re-review defaults to incremental c2..HEAD; if interrupted before done,
        #    retrying on c3 STILL stays incremental c2..HEAD (does not lose baseline or fall back to full).
        (tree / "feat.txt").write_text("v3\n")
        wt_git("add", "feat.txt")
        wt_git("commit", "-q", "-m", "v3")
        c3 = wt_git("rev-parse", "HEAD")
        c3_short = wt_git("rev-parse", "--short", c3)

        brief_inc1 = run_review()
        self.assertIn("增量复审", brief_inc1)
        self.assertIn(f"`git diff {c2_short}..HEAD`", brief_inc1)
        self.assertEqual(self.load_raw("r-inc").get("last_reviewed_commit"), c2)

        brief_inc_retry = run_review()
        self.assertIn("增量复审", brief_inc_retry)
        self.assertIn(f"`git diff {c2_short}..HEAD`", brief_inc_retry)

        # 5. --full forces full diff even when last_reviewed_commit is a valid ancestor of HEAD.
        brief_full = run_review(full=True)
        self.assertNotIn("增量复审", brief_full)
        self.assertNotIn(f"{c2_short}..HEAD", brief_full)
        self.assertIn("`git diff main...dev/x`", brief_full)
        finish_review("1. still needs test fix")
        self.assertEqual(self.load_raw("r-inc").get("last_reviewed_commit"), c3)

        # 6. Reviewer fixes a test on the branch and reports done: sync_on_done refreshes last_reviewed_commit to c_test.
        (tree / "test_fix.txt").write_text("fix\n")
        wt_git("add", "test_fix.txt")
        wt_git("commit", "-q", "-m", "reviewer test fix")
        c_test = wt_git("rev-parse", "HEAD")
        c_test_short = wt_git("rev-parse", "--short", c_test)
        run_review()
        finish_review("1. prod issue; fixed test")
        self.assertEqual(self.load_raw("r-inc").get("last_reviewed_commit"), c_test)

        # 7. English incremental re-review after worker's next commit checks EN wording & test-issue/no-blockers rules.
        self._write_cfg({"lang": "en", "reviewer": {"kind": "claude", "model": "opus"}})
        (tree / "feat.txt").write_text("v4\n")
        wt_git("add", "feat.txt")
        wt_git("commit", "-q", "-m", "v4")
        c4 = wt_git("rev-parse", "HEAD")
        brief_en = run_review()
        self.assertIn("incremental re-review", brief_en)
        self.assertIn(f"`git diff {c_test_short}..HEAD`", brief_en)
        self.assertIn("Production code issues: report only, do not edit production code", brief_en)
        self.assertIn("Test issues (unrealistic fakes/doubles, weakened assertions, isolation leaks, missing coverage", brief_en)
        self.assertIn("start your report with `no blockers`", brief_en)
        finish_review("1. needs rebase")
        self.assertEqual(self.load_raw("r-inc").get("last_reviewed_commit"), c4)

        # 8. Ancestor invalidated (amend/reset): falls back to full diff base...branch.
        (tree / "feat.txt").write_text("v4-amended\n")
        wt_git("add", "feat.txt")
        wt_git("commit", "-q", "--amend", "-m", "v4 amended")
        c4_amended = wt_git("rev-parse", "HEAD")
        self.assertNotEqual(c4_amended, c4)
        brief_rebased = run_review()
        self.assertNotIn("incremental re-review", brief_rebased)
        self.assertIn("`git diff main...dev/x`", brief_rebased)
        finish_review("无阻塞")
        self.assertEqual(self.load_raw("r-inc").get("last_reviewed_commit"), c4_amended)

        # 9. Invalid/unknown last_reviewed_commit SHA also falls back to full diff cleanly.
        self.save_raw({**self.load_raw("r-inc"), "last_reviewed_commit": "deadbeef" * 5})
        brief_bad_sha = run_review()
        self.assertNotIn("incremental re-review", brief_bad_sha)
        self.assertIn("`git diff main...dev/x`", brief_bad_sha)

        # 10. CLI parser wires `--full` (default False).
        from pmlib.cli import build_parser
        parser = build_parser()
        self.assertFalse(parser.parse_args(["review", "r-inc"]).full)
        self.assertTrue(parser.parse_args(["review", "r-inc", "--full"]).full)

    def test_approve_and_land_accept_reviewer_test_fix_commit_after_done(self) -> None:
        repo, git = self.make_repo("r-revfix")
        git("branch", "-D", "dev/x")
        tree = self.base / "trees" / "tree-revfix"
        tree.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-q", str(tree), "-b", "dev/x")

        def wt_git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                check=True, capture_output=True, text=True,
            ).stdout.strip()

        (tree / "prod.txt").write_text("prod\n")
        wt_git("add", "prod.txt")
        wt_git("commit", "-q", "-m", "worker prod commit")
        c_worker = wt_git("rev-parse", "HEAD")

        slug = project_slug(str(repo))
        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": repo.name}, "status": {"state": "idle"}}
        self.hc.terminals["t20"] = {"state": "live", "labels": {"task": "r-revfix"}, "status": {"state": "idle"}}
        self.ctx.store.change_registration(slug, lambda _: {
            "name": pm_name(str(repo)), "project": repo.name, "repo": str(repo),
            "runtime": "hc", "terminal": "t1", "pane": "hc:t1", "agent": "claude",
        })
        self.task(repo, "r-revfix", worktree=str(tree), pane="hc:t20", worker_pane="hc:t20",
                  commit=c_worker[:7], auto_reviewed_commit=c_worker)
        self.verify(repo, f"{_OK_CMD}\n")
        self._write_cfg({"lang": "zh", "reviewer": {"kind": "claude", "model": "opus"}})

        self.be("hc:t1")
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_review(argparse.Namespace(id="r-revfix", name=None, kind=None, model=None, effort=None), ctx=self.ctx)

        # Reviewer fixes a test on the task branch, commits, and reports done starting with 无阻塞.
        (tree / "test_fixed.py").write_text("# fixed test\n")
        wt_git("add", "test_fixed.py")
        wt_git("commit", "-q", "-m", "test: reviewer fix")
        c_revfix = wt_git("rev-parse", "HEAD")
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_update(argparse.Namespace(
                id="r-revfix-review", status="done", keep=False, note="无阻塞；已修复 test_fixed.py",
                **{f: None for f in FIELDS if f != "status"},
            ), ctx=self.ctx)
        self.assertEqual(self.load_raw("r-revfix").get("last_reviewed_commit"), c_revfix)

        # PM approves without passing --commit: must accept c_revfix (from last_reviewed_commit), not refuse!
        self.be("hc:t1")
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_approve(
                argparse.Namespace(id="r-revfix", via="worker", keep=False, message=None, timeout=60, note=None),
                ctx=self.ctx,
            )
        self.assertEqual(self.load_raw("r-revfix")["land_approved"]["commit"], c_revfix)

        # Worker lands cleanly including the reviewer's test fix commit.
        self.be("hc:t20")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_land(argparse.Namespace(id="r-revfix", keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertIn("已合并为", out.getvalue())
        self.assertTrue((repo / "test_fixed.py").exists())
        self.assertEqual(self.load_raw("r-revfix")["status"], "merged")

    def _start_pm(self, repo: str, kind: str | None, model: str | None) -> list[str]:
        slug = project_slug(repo)
        self.ctx.home.registration(slug).unlink(missing_ok=True)
        self.hc.terminals.clear()
        self.hc.app_available = False
        before = len(self.hc.run_records)
        with contextlib.redirect_stdout(io.StringIO()):
            manager_cmds.cmd_start(argparse.Namespace(repo=repo, kind=kind, model=model), ctx=self.ctx)
        self.assertEqual(len(self.hc.run_records), before + 1)
        argv = self.hc.run_records[-1]["argv"]
        self.assertTrue(is_seat_argv(argv))
        return unwrap_seat_argv(argv)[1]

    def test_a_claude_pm_is_started_without_edit_tools(self) -> None:
        repo_dir = self.base / "plain-narrow"
        repo_dir.mkdir()
        repo = self.git.project_root(repo_dir)
        assert repo is not None

        seen1 = self._start_pm(repo, "claude", "")
        self.assertEqual(seen1[:5], ["claude", "--model", "opus", "--disallowedTools", "Edit,NotebookEdit"])
        self.assertEqual(seen1[-2], "--")  # the prompt cannot be read as one more tool name
        # A rotation carries the denial over once, and config can turn it off.
        old = seen1[1:]
        self.assertEqual(narrow_pm("claude", successor_argv("claude", old, "", "接手", ctx=self.ctx), ctx=self.ctx).count("--disallowedTools"), 1)
        self._write_cfg({"pm": {"narrow_tools": False}})
        seen2 = self._start_pm(repo, "claude", "")
        self.assertNotIn("--disallowedTools", seen2)
        self.assertNotIn("--disallowedTools", narrow_pm("claude", successor_argv("claude", old, "", "接手", ctx=self.ctx), ctx=self.ctx))
        # The configured command of a kind is used, narrowed.
        self._write_cfg({"agents": {"claude": {"argv": ["/opt/claude", "--x"]}}})
        seen3 = self._start_pm(repo, "claude", "m")
        self.assertEqual(seen3[:6], ["/opt/claude", "--x", "--model", "m", "--disallowedTools", "Edit,NotebookEdit"])
        self._write_cfg(None)
        seen4 = self._start_pm(repo, "codex", "")
        self.assertNotIn("--disallowedTools", seen4)  # other agents are started as before

    def test_a_claude_pm_starts_lean_on_opus(self) -> None:
        repo_dir = self.base / "plain-lean"
        repo_dir.mkdir()
        repo = self.git.project_root(repo_dir)
        assert repo is not None
        claude = self.ctx.claude_dir
        for name in ("pm", "chat-bot", "other-skill"):
            (claude / "skills" / name).mkdir(parents=True, exist_ok=True)
            (claude / "skills" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
        (claude / "skills" / "synced" / "b1").mkdir(parents=True, exist_ok=True)
        (claude / "skills" / "synced" / "b1" / "manifest.json").write_text(json.dumps({"skills": [{"name": "docs"}]}))
        (claude / "settings.json").write_text(json.dumps({"enabledPlugins": {"playwright@x": True, "off@x": False}}))
        settings = str(self.ctx.home.root / "pm-settings.json")

        argv = self._start_pm(repo, "claude", None)
        head = argv[:argv.index("--")]
        self.assertEqual(head, ["claude", "--model", "opus", "--disallowedTools", "Edit,NotebookEdit",
                                "--strict-mcp-config", "--no-chrome", "--settings", settings])
        # Plugins off, other skills hidden, plus guided compaction settings for Claude Code PM; pm stays listed.
        self.assertEqual(json.loads(Path(settings).read_text()), {
            "enabledPlugins": {"playwright@x": False},
            "skillOverrides": {"anthropic-skills:docs": "user-invocable-only", "chat-bot": "user-invocable-only",
                               "other-skill": "user-invocable-only"},
            "autoCompactWindow": 200000,
            "idleCompaction": True,
            "env": {"CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS": "150000"},
        })
        # A rotation: no flag twice, the outgoing model (Fable) is not carried over, an explicit one wins.
        old = ["--model", "fable"] + argv[3:]
        rotated = pm_argv("claude", successor_argv("claude", old, pm_model("claude", ctx=self.ctx), "接手", ctx=self.ctx), ctx=self.ctx)
        self.assertEqual(rotated, head + ["--", "接手"])
        self.assertNotIn("fable", rotated)
        self.assertEqual(pm_model("claude", "sonnet", ctx=self.ctx), "sonnet")
        self.assertEqual(self._start_pm(repo, "claude", "sonnet")[1:3], ["--model", "sonnet"])
        # config.json's pm.model is the default; for another kind it is not used by a rotation.
        self._write_cfg({"pm": {"model": "opus[1m]"}})
        self.assertEqual(pm_model("claude", ctx=self.ctx), "opus[1m]")
        self.assertEqual(self._start_pm(repo, "claude", None)[1:3], ["--model", "opus[1m]"])
        self._write_cfg({"pm": {"kind": "codex", "model": "gpt"}})
        self.assertEqual(pm_model("claude", ctx=self.ctx), "opus")
        codex_default = self._start_pm(repo, None, None)
        self.assertEqual(codex_default[codex_default.index("-m") + 1], "gpt")  # pm.kind's own model
        self.assertEqual(self._start_pm(repo, "claude", None)[1:3], ["--model", "opus"])  # not codex's
        # The README's example: pm.model belongs to claude, so `start --kind codex` (and restore) runs codex's own.
        self._write_cfg({"pm": {"kind": "claude", "model": "opus"}})
        codex_own = self._start_pm(repo, "codex", None)
        self.assertNotIn("opus", codex_own)
        self.assertNotIn("-m", codex_own[:-1])
        self.assertEqual(pm_model("codex", ctx=self.ctx), "")  # a rotated codex PM: the program's own model, as before
        # A --settings of the user's own is kept, and not doubled.
        mine = pm_argv("claude", ["claude", "--settings", "/me.json", "--", "p"], ctx=self.ctx)
        self.assertEqual(mine.count("--settings"), 1)
        self.assertIn("/me.json", mine)
        # {"pm": {"lean": false}} drops lean flags/plugins/skillOverrides while retaining compaction settings.
        self._write_cfg({"pm": {"lean": False}})
        plain = pm_argv("claude", successor_argv("claude", old, "", "接手", ctx=self.ctx), ctx=self.ctx)
        for flag in ("--strict-mcp-config", "--no-chrome"):
            self.assertNotIn(flag, plain)
        self.assertIn("--disallowedTools", plain)
        self.assertIn("--settings", plain)
        plain_settings = json.loads(Path(settings).read_text())
        self.assertNotIn("enabledPlugins", plain_settings)
        self.assertEqual(plain_settings["autoCompactWindow"], 200000)
        # {"pm": {"lean": false, "compact": false}} drops --settings too.
        self._write_cfg({"pm": {"lean": False, "compact": False}})
        bare = pm_argv("claude", successor_argv("claude", old, "", "接手", ctx=self.ctx), ctx=self.ctx)
        self.assertNotIn("--settings", bare)
        # Codex and pi PMs carry their compaction configs (idempotently), without Claude flags; workers stay unaffected.
        self._write_cfg(None)
        codex_argv = self._start_pm(repo, "codex", None)
        self.assertFalse({"--strict-mcp-config", "--no-chrome", "--settings", "--model"} & set(codex_argv))
        self.assertIn("model_auto_compact_token_limit=220000", codex_argv)
        self.assertIn("model_post_turn_compact_threshold_percent=80", codex_argv)
        self.assertTrue(any(str(x).startswith("compact_prompt=") for x in codex_argv))
        self.assertEqual(pm_argv("codex", codex_argv, ctx=self.ctx), codex_argv)
        codex_worker = worker_argv_for(self.ctx, argparse.Namespace(kind="codex", model=None, effort=None, name="w"), [], repo)
        self.assertNotIn("model_auto_compact_token_limit=220000", codex_worker)
        pi_argv = pm_argv("pi", ["pi", "x"], ctx=self.ctx)
        self.assertEqual(pi_argv, ["pi", "-e", str(PI_COMPACT_EXT), "x"])
        self.assertEqual(pm_argv("pi", pi_argv, ctx=self.ctx), pi_argv)
        self._write_cfg({"pm": {"compact": False}})
        self.assertEqual(pm_argv("pi", ["pi", "x"], ctx=self.ctx), ["pi", "x"])


class ResearchCollectionTests(ReviewLandCase):
    def make_repo(self, name: str = "demo", ignore_evidence: bool = True) -> tuple[Path, str]:
        repo = self.base / name
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        (repo / "app.txt").write_text("base\n", encoding="utf-8")
        if ignore_evidence:
            (repo / ".gitignore").write_text("evidence/\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
        slug = project_slug(repo)
        self.ctx.store.change_registration(slug, lambda _: {
            "name": f"pm-{slug}", "project": name, "repo": str(repo),
        })
        return repo, slug

    def add_worktree(self, repo: Path, branch: str, name: str) -> Path:
        wt = self.base / name
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", branch, str(wt), "main"], check=True)
        return wt

    def register_task(self, repo: Path, branch: str, worktree, title: str = "research task",
                      dispatched: bool = True, review_of: str | None = None) -> str:
        with contextlib.redirect_stdout(io.StringIO()):
            tid = ledger_cmds.cmd_new(argparse.Namespace(
                repo=str(repo), title=title, status="in_progress", owner="pm", base="main",
                workspace="", pane="", agent="w1", branch=branch, worktree=str(worktree) if worktree else "",
                brief="", slug=None, note="started", parent=None,
            ), ctx=self.ctx)

        def _patch(cur, _ch):
            if dispatched:
                cur.raw["dispatched"] = True
            if review_of:
                cur.raw["review_of"] = review_of
            return cur

        Ledger(self.ctx).change(tid, _patch)
        return tid

    def test_update_collects_worktree_research_reports_into_main_checkout_and_context(self) -> None:
        repo, slug = self.make_repo("demo-research", ignore_evidence=True)
        wt = self.add_worktree(repo, "dev/rotation-study", "wt-rotation")
        tid = self.register_task(repo, "dev/rotation-study", wt, title="轮换调研")

        # Worker writes research report + loose/sibling/render-check/screenshot/symlink noise.
        (wt / "evidence/rotation-study").mkdir(parents=True)
        report = wt / "evidence/rotation-study/README.md"
        report.write_text("# 轮换与压缩对比\n\n第一版结论。\n", encoding="utf-8")
        (wt / "evidence/rotation-study/notes.md").write_text("# 非 README 不收\n", encoding="utf-8")
        (wt / "evidence/rotation-study/shot.png").write_bytes(b"\x89PNG")
        (wt / "evidence/loose.md").write_text("# 顶层散落不收\n", encoding="utf-8")
        (wt / "evidence/render-check").mkdir(parents=True)
        (wt / "evidence/render-check/README.md").write_text("# render-check 排除\n", encoding="utf-8")
        (wt / "evidence/render-check-locked").mkdir(parents=True)
        (wt / "evidence/render-check-locked/README.md").write_text("# 锁屏渲染调研\n", encoding="utf-8")
        (wt / "evidence/probe-run").mkdir(parents=True)
        (wt / "evidence/probe-run/.render-check").write_text("marker\n", encoding="utf-8")
        (wt / "evidence/probe-run/README.md").write_text("# 标记目录不收\n", encoding="utf-8")
        outside = self.base / "outside.md"
        outside.write_text("# 外部\n", encoding="utf-8")
        (wt / "evidence/sym-topic").mkdir(parents=True)
        (wt / "evidence/sym-topic/README.md").symlink_to(outside)

        # Reporting to review collects only `<topic>/README.md` (keeping render-check-locked, skipping render-check & .render-check).
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger_cmds.cmd_update(argparse.Namespace(id=tid, status="review", note="调研完成", keep=False), ctx=self.ctx)
        self.assertIn("collected research: render-check-locked/README.md, rotation-study/README.md", out.getvalue())

        dst = repo / "evidence/rotation-study/README.md"
        self.assertEqual(dst.read_text(encoding="utf-8"), "# 轮换与压缩对比\n\n第一版结论。\n")
        self.assertEqual((repo / "evidence/render-check-locked/README.md").read_text(encoding="utf-8"), "# 锁屏渲染调研\n")
        self.assertFalse((repo / "evidence/rotation-study/notes.md").exists())
        self.assertFalse((repo / "evidence/rotation-study/shot.png").exists())
        self.assertFalse((repo / "evidence/loose.md").exists())
        self.assertFalse((repo / "evidence/sym-topic").exists())
        self.assertFalse((repo / "evidence/render-check").exists())
        self.assertFalse((repo / "evidence/probe-run").exists())

        # Immediately exposed by Projects.context / document under `research`.
        projects = Projects(self.ctx.store)
        research = {d["path"]: d for d in projects.context(slug) if d["root"] == "research"}
        self.assertEqual(set(research), {"render-check-locked/README.md", "rotation-study/README.md"})
        self.assertEqual(research["rotation-study/README.md"]["description"], "轮换与压缩对比")
        self.assertIn("第一版结论", projects.document(slug, "research", "rotation-study/README.md"))

        # Round 2 revision updates main checkout; strictly newer main edit is NOT clobbered on retire.
        report.write_text("# 轮换与压缩对比\n\n第二版结论。\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_update(argparse.Namespace(id=tid, status="review", note="补充第二版", keep=False), ctx=self.ctx)
        self.assertIn("第二版结论", dst.read_text(encoding="utf-8"))

        dst.write_text("# 轮换与压缩对比\n\n主检出人工修订。\n", encoding="utf-8")
        newer = report.stat().st_mtime + 10
        os.utime(dst, (newer, newer))
        with contextlib.redirect_stdout(io.StringIO()):
            workers_cmds.cmd_retire(argparse.Namespace(id=tid, force=False), ctx=self.ctx)
        self.assertFalse(wt.exists())
        self.assertIn("主检出人工修订", dst.read_text(encoding="utf-8"))

    def test_non_ignored_evidence_repo_collects_to_ledger_keeps_main_clean_and_retires_and_lands(self) -> None:
        # 1. Pure research thread in a repo where `evidence/` is NOT in .gitignore (e.g. an external app).
        repo, slug = self.make_repo("external-app", ignore_evidence=False)
        wt = self.add_worktree(repo, "dev/perf-study", "wt-perf-study")
        tid = self.register_task(repo, "dev/perf-study", wt, title="性能调研")
        (wt / "evidence/perf-study").mkdir(parents=True)
        (wt / "evidence/perf-study/README.md").write_text("# 渲染性能调研\n\n结论 A。\n", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_update(argparse.Namespace(id=tid, status="review", note="完成调研", keep=False), ctx=self.ctx)

        # Main checkout stays git-clean (no untracked evidence/ written into repo).
        self.assertFalse((repo / "evidence").exists())
        self.assertEqual(self.git.run(str(repo), "status", "--porcelain"), "")

        # Report lands in ledger `projects/<slug>/research/` and is exposed under `research` (not `project`).
        ledger_dst = self.home.projects / slug / "research/perf-study/README.md"
        self.assertTrue(ledger_dst.is_file())
        projects = Projects(self.ctx.store)
        docs = projects.context(slug)
        self.assertEqual([d["path"] for d in docs if d["root"] == "research"], ["perf-study/README.md"])
        self.assertFalse(any(d["root"] == "project" and "research" in d["path"] for d in docs))
        self.assertIn("结论 A", projects.document(slug, "research", "perf-study/README.md"))

        # Uncollected extra file still blocks retire; once removed, pure-research retire succeeds cleanly!
        extra = wt / "evidence/perf-study/uncollected.txt"
        extra.write_text("wip\n", encoding="utf-8")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            workers_cmds.cmd_retire(argparse.Namespace(id=tid, force=False), ctx=self.ctx)
        self.assertTrue(wt.exists())
        extra.unlink()

        with contextlib.redirect_stdout(io.StringIO()):
            workers_cmds.cmd_retire(argparse.Namespace(id=tid, force=False), ctx=self.ctx)
        self.assertFalse(wt.exists())
        self.assertIn("结论 A", projects.document(slug, "research", "perf-study/README.md"))

        # 2. Feature branch with commits + untracked `evidence/<topic>/README.md` in non-ignored repo:
        #    `pm.py land` merges, collects to ledger, and auto-retires worktree cleanly!
        wt2 = self.add_worktree(repo, "dev/feat-ll", "wt-feat-ll")
        (wt2 / "app.txt").write_text("updated\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(wt2), "commit", "-aq", "-m", "feat ll"], check=True)
        (wt2 / "evidence/feat-ll").mkdir(parents=True)
        (wt2 / "evidence/feat-ll/README.md").write_text("# 功能说明\n", encoding="utf-8")
        tid2 = self.register_task(repo, "dev/feat-ll", wt2, title="功能 LL")
        verify = self.home.project_for(str(repo)).verify
        verify.parent.mkdir(parents=True, exist_ok=True)
        verify.write_text(f"{_OK_CMD}\n", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_land(argparse.Namespace(id=tid2, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertFalse(wt2.exists())
        self.assertFalse((repo / "evidence").exists())
        self.assertEqual(self.git.run(str(repo), "status", "--porcelain"), "")
        self.assertIn("功能说明", projects.document(slug, "research", "feat-ll/README.md"))

    def test_update_falls_back_to_checkout_of_branch_when_worktree_not_recorded(self) -> None:
        repo, slug = self.make_repo("demo-branch-only", ignore_evidence=True)
        wt = self.add_worktree(repo, "dev/manual-wt", "wt-manual")
        # Registered only with `--branch` (empty `worktree`, like `pm.py new --branch`).
        tid = self.register_task(repo, "dev/manual-wt", "", title="自建工作树调研", dispatched=False)
        (wt / "evidence/manual-wt").mkdir(parents=True)
        (wt / "evidence/manual-wt/README.md").write_text("# 自建工作树结论\n", encoding="utf-8")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger_cmds.cmd_update(argparse.Namespace(id=tid, status="review", note="汇报", keep=False), ctx=self.ctx)
        self.assertIn("collected research: manual-wt/README.md", out.getvalue())
        self.assertEqual(
            (repo / "evidence/manual-wt/README.md").read_text(encoding="utf-8"),
            "# 自建工作树结论\n",
        )
        projects = Projects(self.ctx.store)
        self.assertEqual([d["path"] for d in projects.context(slug) if d["root"] == "research"],
                         ["manual-wt/README.md"])

    def test_land_preserves_ignored_research_and_skips_git_tracked_evidence_before_merge(self) -> None:
        # 1. Ignored evidence/: land collects report before auto-retire removes the worktree.
        repo, _ = self.make_repo("demo-land", ignore_evidence=True)
        wt = self.add_worktree(repo, "dev/feat-a", "wt-feat-a")
        (wt / "app.txt").write_text("feature a\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(wt), "commit", "-aq", "-m", "feat a"], check=True)
        (wt / "evidence/feat-a").mkdir(parents=True)
        (wt / "evidence/feat-a/README.md").write_text("# 功能 A 说明\n", encoding="utf-8")
        tid = self.register_task(repo, "dev/feat-a", wt, title="功能 A")
        verify = self.home.project_for(str(repo)).verify
        verify.parent.mkdir(parents=True, exist_ok=True)
        verify.write_text(f"{_OK_CMD}\n", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertFalse(wt.exists())
        self.assertEqual((repo / "evidence/feat-a/README.md").read_text(encoding="utf-8"), "# 功能 A 说明\n")

        # 2. Repo where evidence/ is tracked in git: update --status review must NOT pre-copy tracked files
        #    as untracked into main (which would cause `git merge` inside `land` to fail).
        repo2, _ = self.make_repo("demo-tracked", ignore_evidence=False)
        wt2 = self.add_worktree(repo2, "dev/tracked-ev", "wt-tracked")
        (wt2 / "evidence/tracked").mkdir(parents=True)
        (wt2 / "evidence/tracked/README.md").write_text("# 进仓文档\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(wt2), "add", "evidence/tracked/README.md"], check=True)
        subprocess.run(["git", "-C", str(wt2), "commit", "-q", "-m", "add tracked evidence"], check=True)
        tid2 = self.register_task(repo2, "dev/tracked-ev", wt2, title="进仓文档")
        verify2 = self.home.project_for(str(repo2)).verify
        verify2.parent.mkdir(parents=True, exist_ok=True)
        verify2.write_text(f"{_OK_CMD}\n", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_update(argparse.Namespace(id=tid2, status="review", note="ready", keep=False), ctx=self.ctx)
        self.assertFalse((repo2 / "evidence/tracked/README.md").exists())
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_land(argparse.Namespace(id=tid2, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertEqual((repo2 / "evidence/tracked/README.md").read_text(encoding="utf-8"), "# 进仓文档\n")

    def test_abandoned_forced_retire_and_review_threads_do_not_collect_research(self) -> None:
        repo, _ = self.make_repo("demo-skip", ignore_evidence=True)
        wt = self.add_worktree(repo, "dev/drop-me", "wt-drop")
        (wt / "evidence/drop-me").mkdir(parents=True)
        (wt / "evidence/drop-me/README.md").write_text("# 废弃草稿\n", encoding="utf-8")
        tid = self.register_task(repo, "dev/drop-me", wt, title="废弃草稿")
        rid = self.register_task(repo, "dev/drop-me", wt, title="审查", review_of=tid)

        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_update(argparse.Namespace(id=rid, status="done", note="无阻塞", keep=False), ctx=self.ctx)
            ledger_cmds.cmd_update(argparse.Namespace(id=tid, status="abandoned", note="不要了", keep=False), ctx=self.ctx)
            workers_cmds.cmd_retire(argparse.Namespace(id=tid, force=True), ctx=self.ctx)
        self.assertFalse((repo / "evidence/drop-me/README.md").exists())


class ReviewChainAndStateHelpers(ReviewLandCase):
    """Thread 1: review under worker (--parent <worker>, no --outlive-parent), active review guard, and state helpers."""

    def setUp(self) -> None:
        super().setUp()
        repo_dir = self.base / "pm-rc"
        repo_dir.mkdir()
        self.repo = self.git.project_root(repo_dir)
        assert self.repo is not None
        for cmd in (
            ["init", "-q", "-b", "main"],
            ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"],
        ):
            subprocess.run(["git", "-C", self.repo, *cmd], check=True)

    def save_task(self, tid: str, **extra) -> dict:
        rec = {
            "id": tid, "title": f"Task {tid}", "project": Path(self.repo).name, "repo": self.repo,
            "status": "review", "owner": "pm", "base": "main", "branch": "main",
            "worktree": self.repo, "created": self.clock.now(), "dispatched": True, **extra,
        }
        self.save_raw(rec)
        return rec

    def register_hc_pm(self, term: str = "t1") -> tuple[str, dict]:
        slug = project_slug(self.repo)
        rec = {
            "name": pm_name(self.repo), "project": Path(self.repo).name, "repo": self.repo,
            "pane": f"hc:{term}", "runtime": "hc", "terminal": term, "agent": "claude",
        }
        self.ctx.store.change_registration(slug, lambda _: dict(rec))
        return slug, rec

    def test_cmd_review_parents_under_live_worker_without_outlive_parent(self) -> None:
        self.save_task("rc-live", pane="hc:t5", agent="w-live")
        self.hc.terminals["t5"] = {"state": "live", "status": {"state": "idle"}, "labels": {"task": "rc-live"}}
        self.be("hc:t1")
        a = argparse.Namespace(id="rc-live", name=None, kind="claude", model="opus", effort=None)
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_review(a, ctx=self.ctx)
        self.assertEqual(len(self.hc.run_records), 1)
        pl = self.hc.run_records[0]["placement"]
        self.assertEqual(pl[pl.index("--parent") + 1], "t5")
        self.assertIn("--no-notify", pl)
        self.assertNotIn("--outlive-parent", pl)

    def test_review_placement_falls_back_to_pm_when_worker_offline_or_remote(self) -> None:
        # 1. Worker offline -> falls back to PANE (PM), still without --outlive-parent
        task = self.save_task("rc-off", pane="hc:t5")
        self.hc.terminals["t5"] = {"state": "finished"}
        self.be("hc:t1")
        self.assertEqual(review_placement_for(self.ctx, task), ["--parent", "t1", "--no-notify"])

        # 2. Worker offline and PANE empty -> falls back to live registered hc PM
        self.register_hc_pm("t1")
        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": Path(self.repo).name}, "status": {"state": "idle"}}
        self.be("")
        self.assertEqual(review_placement_for(self.ctx, task), ["--parent", "t1", "--no-notify"])

        # 3. Remote worker pane ("hc:mac/t5") -> does not pass remote addr as local --parent, falls back to PM
        remote_task = self.save_task("rc-rem", pane="hc:mac/t5")
        self.be("hc:t1")
        self.assertEqual(review_placement_for(self.ctx, remote_task), ["--parent", "t1", "--no-notify"])

        # 4. No worker, no PANE, no live PM -> --no-parent
        self.hc.terminals.clear()
        self.be("")
        self.assertEqual(review_placement_for(self.ctx, task), ["--no-parent"])

    def test_reattach_review_uses_review_placement_without_outlive_parent(self) -> None:
        self.register_hc_pm("t1")
        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": Path(self.repo).name}, "status": {"state": "idle"}}
        self.hc.terminals["t5"] = {"state": "live"}
        self.save_task("rc-ra", pane="hc:t5")
        rev = self.save_task("rc-ra-review", review_of="rc-ra", pane="hc:t6", status="in_progress")
        plan = {"cwd": self.repo, "kind": "claude", "argv": ["claude"], "prompt": "hi"}
        self.be("")
        pane, ws = start_beside_pm_for(self.ctx, rev, plan, "rev")
        self.assertEqual((pane, ws), (f"hc:{self.hc.run_records[0]['address']}", ""))
        pl = self.hc.run_records[0]["placement"]
        self.assertEqual(pl[pl.index("--parent") + 1], "t5")
        self.assertNotIn("--outlive-parent", pl)

    def test_active_review_protects_worker_in_idle_workers_and_status(self) -> None:
        self.save_task("rc-p1", status="review", pane="hc:t1")
        self.save_task("rc-p1-review", status="in_progress", review_of="rc-p1", pane="hc:t2")
        self.save_task("rc-p2", status="review", pane="hc:t3")
        self.save_task("rc-p2-review", status="done", review_of="rc-p2", pane="hc:t4")
        old = (self.clock.time() - 3600) * 1000
        self.hc.terminals["t1"] = {"state": "live", "status": {"state": "idle"}, "status_ms": old, "labels": {"task": "rc-p1"}}
        self.hc.terminals["t3"] = {"state": "live", "status": {"state": "idle"}, "status_ms": old, "labels": {"task": "rc-p2"}}

        # Unnamed --close: skips t1 (active review), closes t3 (review done)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            workers_cmds.cmd_idle_workers(argparse.Namespace(repo=self.repo, minutes=None, close=[], exited=False, json=False), ctx=self.ctx)
        self.assertIn("(review: rc-p1-review)", out.getvalue())
        self.assertEqual(self.hc.killed, ["t3"])
        self.assertNotIn("t3", self.hc.terminals)
        self.assertIn("t1", self.hc.terminals)

        # Restore t3 for subsequent sub-checks
        self.hc.terminals["t3"] = {"state": "live", "status": {"state": "idle"}, "status_ms": old, "labels": {"task": "rc-p2"}}
        self.hc.killed.clear()

        # Named --close hc:t1: still refused while review is active
        out_named = io.StringIO()
        with contextlib.redirect_stdout(out_named):
            workers_cmds.cmd_idle_workers(argparse.Namespace(repo=self.repo, minutes=None, close=["hc:t1"], exited=False, json=False), ctx=self.ctx)
        self.assertEqual(self.hc.killed, [])
        self.assertIn("rc-p1-review", out_named.getvalue())

        # JSON output includes active_review for rc-p1 only
        out_json = io.StringIO()
        with contextlib.redirect_stdout(out_json):
            workers_cmds.cmd_idle_workers(argparse.Namespace(repo=self.repo, minutes=None, close=None, exited=False, json=True), ctx=self.ctx)
        by_task = {w["task"]: w for w in json.loads(out_json.getvalue())}
        self.assertEqual(by_task["rc-p1"]["active_review"], "rc-p1-review")
        self.assertNotIn("active_review", by_task["rc-p2"])

        # cmd_status omits rc-p1 from "worker terminal still open" while review is active, shows rc-p2.
        st_out = io.StringIO()
        with contextlib.redirect_stdout(st_out):
            status_view.cmd_status(argparse.Namespace(repo=self.repo, all=False, closed=False), ctx=self.ctx)
        text = st_out.getvalue()
        section = text[text.index("worker terminal still open"):] if "worker terminal still open" in text else ""
        self.assertNotIn("rc-p1  hc:t1", section)
        self.assertIn("rc-p2  hc:t3", section)

        # Once rc-p1-review finishes (done), idle-workers --close closes t1
        self.save_raw({**self.load_raw("rc-p1-review"), "status": "done"})
        self.hc.killed.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            workers_cmds.cmd_idle_workers(argparse.Namespace(repo=self.repo, minutes=None, close=["hc:t1"], exited=False, json=False), ctx=self.ctx)
        self.assertEqual(self.hc.killed, ["t1"])

    def test_active_review_protects_worker_in_close_worker_and_cmd_close_worker(self) -> None:
        self._write_cfg({"workers": {"close_on_close": True}})
        task = self.save_task("rc-cw", status="done", pane="hc:t9")
        self.save_task("rc-cw-review", status="blocked", review_of="rc-cw", pane="hc:t10")
        self.hc.terminals["t9"] = {"state": "live", "status": {"state": "idle"}, "labels": {"task": "rc-cw"}}

        # 1. close_worker(task, forced=False) keeps worker while review is active (even blocked)
        msg = close_worker_for(self.ctx, task)
        self.assertIn("rc-cw-review", msg)
        self.assertEqual(self.hc.killed, [])

        # 2. cmd_close_worker waits while review is active, does not close before deadline
        self.save_raw({**task, "status": "review"})
        workers_cmds.cmd_close_worker(argparse.Namespace(terminal="t9", task="rc-cw", quiet=10, timeout=50, while_="review"), ctx=self.ctx)
        self.assertEqual(self.hc.killed, [])
        self.assertIn("t9", self.hc.terminals)

        # 3. cmd_close_worker closes once the review finishes and quiet elapses
        ticks = [0]

        def step_sleep(_dt):
            ticks[0] += 1
            if ticks[0] == 2:
                self.save_raw({**self.load_raw("rc-cw-review"), "status": "done"})

        step_clock = SteppingClock("2026-11-23 11:00:00", mono=200.0, on_sleep=step_sleep)
        step_ctx = self._ctx("", clock=step_clock)
        workers_cmds.cmd_close_worker(argparse.Namespace(terminal="t9", task="rc-cw", quiet=10, timeout=200, while_="review"), ctx=step_ctx)
        self.assertEqual(self.hc.killed, ["t9"])

    def test_dash_state_exposes_task_and_pm_helpers_with_liveness(self) -> None:
        slug, rec = self.register_hc_pm("t1")
        rec["helpers"] = [
            {"name": "pm-scan", "terminal": "t20", "parent": "t1", "owner": rec["name"], "owner_kind": "pm",
             "project": slug, "status": "running", "profile": "neon", "kind": "agy", "model": "gemini-4-neon",
             "effort": "high", "result": "/tmp/pm-scan.md", "prompt": "scan repo", "started": "2026-11-21 10:00:00",
             "started_ts": 1.0, "ended": "", "handed": True, "turn_base": 0, "summary": ""},
        ]
        self.ctx.store.change_registration(slug, lambda _: dict(rec))

        self.save_task("rc-h1", status="in_progress", pane="hc:t5", helpers=[
            {"name": "scan-pitfalls", "terminal": "t21", "parent": "t5", "owner": "rc-h1", "owner_kind": "task",
             "project": slug, "status": "running", "profile": "neon", "kind": "agy", "model": "gemini-4-neon",
             "effort": "high", "result": "/tmp/h1.md", "prompt": "check pitfalls", "started": "2026-11-21 10:01:00",
             "started_ts": 2.0, "ended": "", "handed": True, "turn_base": 1, "summary": "", "cleanup_term": False},
            {"name": "lost-helper", "terminal": "t22", "parent": "t5", "owner": "rc-h1", "owner_kind": "task",
             "project": slug, "status": "running", "profile": "opus", "kind": "claude", "model": "opus",
             "effort": "", "result": "/tmp/h2.md", "prompt": "read docs", "started": "2026-11-21 10:02:00",
             "started_ts": 3.0, "ended": "", "summary": ""},
            {"name": "done-helper", "terminal": "t23", "parent": "t5", "owner": "rc-h1", "owner_kind": "task",
             "project": slug, "status": "done", "profile": "opus", "kind": "claude", "model": "opus",
             "effort": "", "result": "/tmp/h3.md", "prompt": "done one", "started": "2026-11-21 09:00:00",
             "started_ts": 0.5, "ended": "2026-11-21 09:05:00", "summary": "all good", "fallback": "screen"},
        ])
        self.save_task("rc-h0", status="in_progress", pane="hc:t6")  # no helpers

        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": Path(self.repo).name}, "status": {"state": "idle"}}
        self.hc.terminals["t5"] = {"state": "live", "status": {"state": "working"}}
        self.hc.terminals["t6"] = {"state": "live", "status": {"state": "working"}}
        self.hc.terminals["t20"] = {"state": "live", "status": {"state": "working"}}
        self.hc.terminals["t21"] = {"state": "live", "status": {"state": "working"}}

        st = state_view.dash_state(ctx=self.ctx)

        tasks = {t["id"]: t for t in st["tasks"]}
        self.assertNotIn("helpers", tasks["rc-h0"])
        hs = tasks["rc-h1"]["helpers"]
        self.assertEqual([h["name"] for h in hs], ["scan-pitfalls", "lost-helper", "done-helper"])

        # Running live helper
        self.assertEqual(hs[0]["pane"], "hc:t21")
        self.assertEqual(hs[0]["terminal"], "t21")
        self.assertFalse(hs[0]["offline"])
        self.assertEqual(hs[0]["live_state"], "working")
        self.assertEqual(hs[0]["result"], "/tmp/h1.md")
        for internal in ("started_ts", "handed", "turn_base", "cleanup_term", "owner_kind"):
            self.assertNotIn(internal, hs[0])

        # Running helper whose terminal is missing from hc ls -> offline
        self.assertTrue(hs[1]["offline"])
        self.assertEqual(hs[1]["live_state"], "offline")

        # Finished helper -> not offline, preserves summary/ended/fallback
        self.assertFalse(hs[2]["offline"])
        self.assertNotIn("live_state", hs[2])
        self.assertEqual(hs[2]["summary"], "all good")
        self.assertEqual(hs[2]["fallback"], "screen")

        # PM entry also exposes its helpers
        pm_row = next(p for p in st["pms"] if p["name"] == rec["name"])
        self.assertEqual(len(pm_row["helpers"]), 1)
        self.assertEqual(pm_row["helpers"][0]["name"], "pm-scan")
        self.assertEqual(pm_row["helpers"][0]["live_state"], "working")
        self.assertFalse(pm_row["helpers"][0]["offline"])
        self.assertNotIn("for_task", pm_row["helpers"][0])

    def test_dash_state_helpers_expose_for_task_and_label_fallback(self) -> None:
        slug, rec = self.register_hc_pm("t1")
        rec["helpers"] = [
            {"name": "land-rc-ft1", "terminal": "t30", "parent": "t1", "owner": rec["name"], "owner_kind": "pm",
             "project": slug, "status": "done", "profile": "neon", "kind": "agy", "model": "gemini-4-neon",
             "effort": "", "result": "/tmp/ft1.md", "prompt": "merge rc-ft1", "started": "2026-11-23 10:00:00",
             "ended": "2026-11-23 10:05:00", "summary": "merged", "for_task": "rc-ft1"},
            {"name": "land-rc-ft2", "terminal": "t31", "parent": "t1", "owner": rec["name"], "owner_kind": "pm",
             "project": slug, "status": "running", "profile": "neon", "kind": "agy", "model": "gemini-4-neon",
             "effort": "", "result": "/tmp/ft2.md", "prompt": "legacy live", "started": "2026-11-23 10:06:00",
             "ended": "", "summary": ""},
            {"name": "triage-rc-ft3", "terminal": "t32", "parent": "t1", "owner": rec["name"], "owner_kind": "pm",
             "project": slug, "status": "done", "profile": "neon", "kind": "agy", "model": "gemini-4-neon",
             "effort": "", "result": "/tmp/ft3.md", "prompt": "legacy ended", "started": "2026-11-23 09:00:00",
             "ended": "2026-11-23 09:02:00", "summary": "triaged"},
            {"name": "old-reused", "terminal": "t33", "parent": "t1", "owner": rec["name"], "owner_kind": "pm",
             "project": slug, "status": "done", "profile": "neon", "kind": "agy", "model": "gemini-4-neon",
             "effort": "", "result": "/tmp/ft4.md", "prompt": "old", "started": "2026-11-23 08:00:00",
             "ended": "2026-11-23 08:02:00", "summary": "old"},
            {"name": "pm-general", "terminal": "t34", "parent": "t1", "owner": rec["name"], "owner_kind": "pm",
             "project": slug, "status": "running", "profile": "neon", "kind": "agy", "model": "gemini-4-neon",
             "effort": "", "result": "/tmp/ft5.md", "prompt": "general", "started": "2026-11-23 10:07:00",
             "ended": "", "summary": ""},
        ]
        self.ctx.store.change_registration(slug, lambda _: dict(rec))

        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": Path(self.repo).name}, "status": {"state": "idle"}}
        # Ledger for_task wins over a different terminal label.
        self.hc.terminals["t30"] = {"state": "ended", "labels": {"helper": "land-rc-ft1", "helper.task": "rc-other"}}
        # Live terminal label fallback when ledger lacks for_task.
        self.hc.terminals["t31"] = {
            "state": "live", "status": {"state": "working"},
            "labels": {"helper": "land-rc-ft2", "helper.of": rec["name"], "helper.task": "rc-ft2"},
        }
        # Ended terminal label fallback when ledger lacks for_task.
        self.hc.terminals["t32"] = {
            "state": "ended",
            "labels": {"helper": "triage-rc-ft3", "helper.of": rec["name"], "helper.task": "rc-ft3"},
        }
        # Reused terminal address belonging to a different helper name must not leak helper.task.
        self.hc.terminals["t33"] = {
            "state": "live", "status": {"state": "working"},
            "labels": {"helper": "someone-else", "helper.task": "rc-wrong"},
        }
        self.hc.terminals["t34"] = {"state": "live", "status": {"state": "working"}, "labels": {"helper": "pm-general"}}

        st = state_view.dash_state(ctx=self.ctx)
        pm_row = next(p for p in st["pms"] if p["name"] == rec["name"])
        by_name = {h["name"]: h for h in pm_row["helpers"]}

        self.assertEqual(by_name["land-rc-ft1"]["for_task"], "rc-ft1")
        self.assertEqual(by_name["land-rc-ft2"]["for_task"], "rc-ft2")
        self.assertEqual(by_name["triage-rc-ft3"]["for_task"], "rc-ft3")
        self.assertNotIn("for_task", by_name["old-reused"])
        self.assertNotIn("for_task", by_name["pm-general"])

    def test_adopt_task_refuses_when_active_review_is_running(self) -> None:
        self.register_hc_pm("t1")
        self.save_task("rc-ad", status="review", pane="hc:t5", worker={"kind": "claude"})
        self.save_task("rc-ad-review", status="in_progress", review_of="rc-ad", pane="hc:t6")
        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": Path(self.repo).name}, "status": {"state": "idle"}}
        self.hc.terminals["t5"] = {
            "state": "live", "parent": "t_old_pm", "cwd": self.repo,
            "labels": {"task": "rc-ad"}, "status": {"state": "idle"},
        }
        args = argparse.Namespace(
            candidate="rc-ad", confirmed=True, repo=self.repo,
            drop=False, text=None, name=None, type=None, quote=None, verified=None,
        )
        with self.assertRaises(SystemExit) as err:
            workers_cmds.adopt_task(args, ctx=self.ctx)
        msg = str(err.exception.code)
        self.assertIn("rc-ad-review", msg)
        self.assertIn("retire rc-ad-review", msg)
        self.assertEqual(self.hc.killed, [])
        self.assertEqual(self.hc.run_records, [])
        # Task status/pane untouched (no question card created either)
        self.assertEqual(self.load_raw("rc-ad")["pane"], "hc:t5")
        self.assertEqual(self.load_raw("rc-ad")["status"], "review")


AGY_TRUST = """\
Workspace Trust Required
Do you trust this workspace?
/Users/dev/.herdr/worktrees/dudu/dev-x

  ▸ 1. Trust this workspace
    2. Cancel
"""

AGY_TRUST_SECOND = """\
Do you trust this directory?
  1. Don't trust
▸ 2. Trust
"""

INLINE_TRUST = "Do you trust this folder /Users/dev/.herdr/worktrees/dudu/dev-x? [y/N]"

CODEX_UPDATE = """\
Update available! 0.171.0 -> 0.172.0
  ❯ 1. Update now
    2. Skip until next version
"""

QUOTA_SCREEN = """\
Error: 429 Too Many Requests - quota exceeded for model claude-opus.
Please wait or switch models.
"""

AUTH_SCREEN = """\
Authentication failed: token expired. Please login again.
"""

HOOK_SCREEN = """\
1 hook needs review before running.
"""


class DelegateBase(ReviewLandCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo = self.base / "proj"
        self.repo.mkdir()
        self.git_cmd("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        self.git_cmd("add", "a.txt")
        self.git_cmd("commit", "-q", "-m", "init")
        self.name = project_slug(str(self.repo))

        self.hc.terminals["t7"] = {
            "state": "live", "cwd": str(self.repo), "labels": {"pm": self.repo.name},
            "status": {"state": "idle"}, "turn": 1,
        }
        self.ctx.store.change_registration(self.name, lambda _: {
            "project": self.repo.name, "repo": str(self.repo), "name": f"pm-{self.name}",
            "runtime": "hc", "terminal": "t7", "pane": "hc:t7", "kind": "claude",
        })
        vfile = self.home.project_for(str(self.repo)).verify
        vfile.parent.mkdir(parents=True, exist_ok=True)
        vfile.write_text(f"{_OK_CMD}\n")

    def git_cmd(self, *args: str, cwd: Path | None = None) -> str:
        res = subprocess.run(
            ["git", "-C", str(cwd or self.repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True, capture_output=True, text=True,
        )
        return res.stdout.strip()

    def spawned_by(self, cmd: str) -> list[list[str]]:
        return [s["args"] for s in self.procs.spawned if s["args"][:1] == [cmd]]

    def async_sends(self) -> list[tuple[str, str]]:
        return queued_sends(self.ctx)

    def make_worker_task(self, slug: str, branch: str = "dev/feat", pane: str = "hc:t20",
                         status: str = "review", plan=None, extra_file: str = "feat.txt"):
        wt = self.base / f"wt-{slug}"
        self.git_cmd("worktree", "add", "-q", str(wt), "-b", branch, "main")
        (wt / extra_file).write_text(f"{slug}\n")
        self.git_cmd("add", extra_file, cwd=wt)
        self.git_cmd("commit", "-q", "-m", f"add {extra_file}", cwd=wt)
        sha = self.git_cmd("rev-parse", "--short", "HEAD", cwd=wt)
        tid = f"{self.name}-{slug}"
        task = {
            "id": tid, "title": f"任务 {slug}", "project": self.repo.name, "repo": str(self.repo),
            "status": status, "owner": "pm", "base": "main", "branch": branch,
            "worktree": str(wt), "pane": pane, "worker_pane": pane, "commit": sha,
            "dispatched": True, "created": self.clock.now(), "log": [],
        }
        if plan is not None:
            task["plan"] = plan
        self.save_raw(task)
        if pane.startswith("hc:"):
            self.hc.terminals[pane[3:]] = {
                "state": "live", "cwd": str(wt), "labels": {"task": tid},
                "status": {"state": "idle"}, "turn": 2,
            }
        return tid, wt, sha


class DelegatedMergeTests(DelegateBase):
    def test_worker_cannot_land_without_pm_approval_or_other_task(self) -> None:
        tid1, _, _ = self.make_worker_task("w1", branch="dev/w1", pane="hc:t20")
        tid2, _, _ = self.make_worker_task("w2", branch="dev/w2", pane="hc:t21")

        # Unapproved worker trying to land its own task -> refused (exit 2)
        self.be("hc:t20")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            review_cmds.cmd_land(argparse.Namespace(id=tid1, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertEqual(cm.exception.code, LAND_REFUSED)
        self.assertIn("not been approved", err.getvalue())

        # PM approves tid2, worker of tid1 tries to land tid2 -> refused (exit 2)
        self.be("hc:t7")
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_approve(argparse.Namespace(id=tid2, via="worker", keep=False, message=None, timeout=60, note=None), ctx=self.ctx)
        self.be("hc:t20")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            review_cmds.cmd_land(argparse.Namespace(id=tid2, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertEqual(cm.exception.code, LAND_REFUSED)
        self.assertIn("only land its own task", err.getvalue())

        # Worker cannot self-approve
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            review_cmds.cmd_approve(argparse.Namespace(id=tid1, via="auto", keep=False, message=None, timeout=60, note=None), ctx=self.ctx)
        self.assertEqual(cm.exception.code, LAND_REFUSED)

    def test_pm_approve_delegates_async_and_worker_lands_wakes_pm_and_schedules_retire(self) -> None:
        tid, wt, sha = self.make_worker_task("ok", branch="dev/ok", pane="hc:t20", plan=[
            {"text": "实现功能", "state": "done", "anchor": "work"},
            {"text": "独立审查", "state": "done", "anchor": "review"},
            {"text": "合进 main", "state": "todo", "anchor": "merge"},
        ])
        # PM approves -> immediate async send, no synchronous land run
        self.be("hc:t7")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_approve(argparse.Namespace(id=tid, via="auto", keep=False, message="merge ok", timeout=60, note=None), ctx=self.ctx)
        self.assertIn("delegated to worker hc:t20 (async)", out.getvalue())
        sends = self.async_sends()
        self.assertEqual(len(sends), 1)
        sent_term, sent_msg = sends[0]
        self.assertEqual(sent_term, "t20")
        self.assertIn(f"land {tid}", sent_msg)
        self.assertIn("git merge main", sent_msg)
        t = self.load_raw(tid)
        self.assertEqual(t["status"], "in_progress")
        self.assertEqual(t["land_approved"]["executor"], "worker")
        self.assertEqual([s["state"] for s in t["plan"]], ["done", "done", "doing"])

        # Worker executes pm.py land <id> (inherits PM's --message from land_approved!)
        self.be("hc:t20")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=None), ctx=self.ctx)
        self.assertIn("merged as", out.getvalue())
        self.assertIn("will retire once this turn ends", out.getvalue())
        t = self.load_raw(tid)
        self.assertEqual(t["status"], "merged")
        self.assertNotIn("land_approved", t)
        self.assertEqual([s["state"] for s in t["plan"]], ["done", "done", "done"])
        self.assertEqual(self.git_cmd("log", "-1", "--format=%s"), "merge ok")
        # Deferred retire was scheduled instead of deleting cwd mid-turn
        self.assertTrue(wt.is_dir())
        closes = self.spawned_by("close-worker")
        self.assertEqual(len(closes), 1)
        self.assertIn("--retire", closes[0])
        # PM is woken through pending_batch (not filtered out by MOVED_ON!)
        _, _, items = Delivery(self.ctx, str(self.repo)).pending_batch()
        self.assertEqual([i["event"]["task"] for i in items], [tid])
        self.assertEqual(items[0]["event"]["status"], "merged")

    def test_conflict_resolution_via_merge_main_preserves_approval_and_lands(self) -> None:
        tid, wt, _ = self.make_worker_task("conf", branch="dev/conf", pane="hc:t20", extra_file="shared.txt")
        # Create a conflicting commit on main
        (self.repo / "shared.txt").write_text("main version\n")
        self.git_cmd("add", "shared.txt")
        self.git_cmd("commit", "-q", "-m", "main change")

        self.be("hc:t7")
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_approve(argparse.Namespace(id=tid, via="worker", keep=False, message=None, timeout=60, note=None), ctx=self.ctx)

        # Worker tries land -> exit 4 with worker conflict hint
        self.be("hc:t20")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertEqual(cm.exception.code, LAND_CONFLICTS)
        self.assertIn("git merge main", out.getvalue())

        # Worker merges main into its branch, resolves conflict, commits, and re-runs land
        subprocess.run(["git", "-C", str(wt), "merge", "main"], capture_output=True)
        (wt / "shared.txt").write_text("resolved version\n")
        self.git_cmd("add", "shared.txt", cwd=wt)
        self.git_cmd("commit", "-q", "-m", "merge main and resolve", cwd=wt)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertIn("merged as", out.getvalue())
        self.assertEqual((self.repo / "shared.txt").read_text(), "resolved version\n")
        self.assertEqual(self.load_raw(tid)["status"], "merged")

    def test_post_merge_steps_stay_with_worker_step_done_and_finish_on_done(self) -> None:
        tid, wt, _ = self.make_worker_task("inst", branch="dev/inst", pane="hc:t20", plan=[
            {"text": "实现", "state": "done", "anchor": "work"},
            {"text": "合进 main", "state": "todo", "anchor": "merge"},
            {"text": "装到本机", "state": "todo", "anchor": "custom"},
            {"text": "同步装到 MBP", "state": "todo", "anchor": "custom"},
        ])
        self.be("hc:t7")
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_approve(argparse.Namespace(id=tid, via="worker", keep=False, message=None, timeout=60, note=None), ctx=self.ctx)
        _, sent_msg = self.async_sends()[-1]
        self.assertIn(".claude/coordination.md", sent_msg)
        self.assertIn("recall", sent_msg)
        self.assertIn("--step-done", sent_msg)
        self.assertNotIn("mbp-over-tailscale", sent_msg)
        self.assertNotIn("dev-update-on-request", sent_msg)

        # Worker lands -> stays in_progress, keeps worker & worktree alive, watches worker during post-merge steps
        self.be("hc:t20")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertIn("active 2/4", out.getvalue())
        t = self.load_raw(tid)
        self.assertEqual(t["status"], "in_progress")
        self.assertEqual(t["pane"], "hc:t20")
        self.assertTrue(t["landed"]["by_worker"])
        self.assertTrue(StallWatcher(self.ctx).watched_worker(t))
        self.assertEqual([s["state"] for s in t["plan"]], ["done", "done", "doing", "todo"])

        # Worker checks off intermediate step silently (--step-done)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_update(argparse.Namespace(id=tid, step_done=True), ctx=self.ctx)
        t = self.load_raw(tid)
        self.assertEqual([s["state"] for s in t["plan"]], ["done", "done", "done", "doing"])

        # Worker finishes remaining install step -> status=done, wakes PM, schedules deferred close+retire
        self.procs.spawned.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            ledger_cmds.cmd_update(argparse.Namespace(id=tid, status="done", note="已装到本机和 MBP"), ctx=self.ctx)
        t = self.load_raw(tid)
        self.assertEqual(t["status"], "done")
        self.assertTrue(all(s["state"] == "done" for s in t["plan"]))
        closes = self.spawned_by("close-worker")
        self.assertEqual(len(closes), 1)
        self.assertIn("--retire", closes[0])
        _, _, items = Delivery(self.ctx, str(self.repo)).pending_batch()
        self.assertEqual([i["event"]["task"] for i in items], [tid])
        self.assertEqual(items[0]["event"]["status"], "done")

    def test_approve_falls_back_to_exec_helper_when_worker_offline_and_authorizes_only_that_helper(self) -> None:
        tid, wt, _ = self.make_worker_task("off", branch="dev/off", pane="hc:t99")
        self.hc.terminals.pop("t99", None)  # worker is offline

        self.be("hc:t7")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_approve(argparse.Namespace(id=tid, via="auto", keep=False, message=None, timeout=60, note=None), ctx=self.ctx)
        self.assertIn("delegated to exec helper", out.getvalue())
        self.assertEqual(len(self.spawned_by("_deliver-ready")), 1)
        t = self.load_raw(tid)
        la = t["land_approved"]
        self.assertEqual(la["executor"], "helper")
        hterm = la["executor_pane"][3:]
        self.assertTrue(hterm)

        # An unrelated read-only helper is refused
        self.hc.terminals["t88"] = {
            "state": "live", "cwd": str(self.repo),
            "labels": {"helper.of": f"pm-{self.name}", "helper": "other", "helper.project": self.name},
        }
        self.be("hc:t88")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertEqual(cm.exception.code, LAND_REFUSED)

        # The authorized exec helper lands cleanly, retires the offline worktree, and its own `helper done` is quiet
        helper_entry = next(h for h in helper_entries(self.ctx.store.registration(self.name)) if h["name"] == la["helper_name"])
        self.assertTrue(helper_entry.get("quiet"))
        self.be(f"hc:{hterm}")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertIn("merged as", out.getvalue())
        self.assertEqual(self.load_raw(tid)["status"], "merged")
        self.assertTrue(self.load_raw(tid).get("retired"))
        self.assertFalse(wt.exists())

        # Helper reporting `helper done` after `land` already woke the PM with `status=merged` must NOT cause a 2nd wake.
        from pmlib.helpers.service import Helpers
        Helpers(self.ctx).done(text="Merged cleanly and retired.")
        helper_evs = [e for e in Conversation(self.ctx, str(self.repo)).events() if e.get("type") == "helper"]
        self.assertEqual(len(helper_evs), 1)
        self.assertFalse(helper_evs[0]["wake"])
        _, _, pending = Delivery(self.ctx, str(self.repo)).pending_batch()
        self.assertEqual([(p["event"]["type"], p["event"].get("status")) for p in pending], [("thread", "merged")])

        # Safety net: if a quiet `land` helper times out/exits while its task is still `in_progress`, it DOES wake PM.
        from pmlib.helpers.records import helper_should_wake_pm
        tid2, _, _ = self.make_worker_task("still-open", branch="dev/still-open", pane="hc:t98", status="in_progress")
        q_entry = {"quiet": True, "for_task": tid2}
        self.assertFalse(helper_should_wake_pm(self.ctx, q_entry, "done"))
        self.assertTrue(helper_should_wake_pm(self.ctx, q_entry, "timeout"))
        self.assertTrue(helper_should_wake_pm(self.ctx, q_entry, "exited"))
        self.assertTrue(helper_should_wake_pm(self.ctx, q_entry, "blocked"))
        # Once the task is already merged, timeout/exited stays quiet.
        self.assertFalse(helper_should_wake_pm(self.ctx, {"quiet": True, "for_task": tid}, "timeout"))

    def test_supervisor_hands_a_stalled_worker_merge_to_an_exec_helper_as_itself(self) -> None:
        """No `HC_TERMINAL_ID` posing as the PM: the stall watcher hands the approved merge over in process, as
        `Principal.supervisor`, from whatever terminal identity the process it runs in inherited."""
        tid, _wt, _ = self.make_worker_task("stall", branch="dev/stall", pane="hc:t20", status="in_progress")
        self.be("hc:t7")
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_approve(argparse.Namespace(id=tid, via="worker", keep=True, message="- merge stall",
                                                       timeout=420, note="- deploy"), ctx=self.ctx)
        self.assertEqual(self.load_raw(tid)["land_approved"]["executor"], "worker")
        # A drain started from the worker's own terminal (it inherited HC_TERMINAL_ID=t20) gives up on the send.
        self.be("hc:t20")
        self.assertTrue(StallWatcher(self.ctx).fallback_land_to_helper(self.load_raw(tid), reason="send failed",
                                                                       term="t20"))
        la = self.load_raw(tid)["land_approved"]
        self.assertEqual((la["executor"], la["by"]), ("helper", f"supervisor:{self.name}"))
        self.assertEqual((la["message"], la["keep"], la["timeout"], la["note"]), ("- merge stall", True, 420, "- deploy"))
        self.assertTrue(la["helper_name"].startswith(f"land-{tid}"))
        # Started beside the PM's terminal (t7), owned by the PM, scoped to this task.
        helper = next(h for h in helper_entries(self.ctx.store.registration(self.name)) if h["name"] == la["helper_name"])
        self.assertEqual((helper.get("parent"), helper.get("mode"), helper.get("for_task")), ("t7", "exec", tid))
        self.assertFalse([r for r in self.procs.ran if "approve" in r.get("argv", [])])

    def test_approve_revoke_blocks_subsequent_worker_land(self) -> None:
        tid, _, _ = self.make_worker_task("rev", branch="dev/rev", pane="hc:t20")
        self.be("hc:t7")
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_approve(argparse.Namespace(id=tid, via="worker", keep=False, message=None, timeout=60, note=None), ctx=self.ctx)
            review_cmds.cmd_approve(argparse.Namespace(id=tid, revoke=True), ctx=self.ctx)
        self.assertNotIn("land_approved", self.load_raw(tid))
        self.be("hc:t20")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertEqual(cm.exception.code, LAND_REFUSED)

    def test_unreviewed_commit_or_foreign_merge_after_approve_is_refused(self) -> None:
        tid, wt, _ = self.make_worker_task("bind", branch="dev/bind", pane="hc:t20")
        self.be("hc:t7")
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_approve(argparse.Namespace(id=tid, via="worker", keep=False, message=None, timeout=60, note=None), ctx=self.ctx)

        # Worker adds an unreviewed commit on top of the approved commit -> MUST be refused!
        (wt / "sneaky.txt").write_text("unreviewed\n")
        self.git_cmd("add", "sneaky.txt", cwd=wt)
        self.git_cmd("commit", "-q", "-m", "sneaky unreviewed commit", cwd=wt)
        self.be("hc:t20")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertEqual(cm.exception.code, LAND_REFUSED)
        self.assertIn("re-review", err.getvalue())

        # Reset back to approved commit and merge a foreign unreviewed branch -> MUST also be refused!
        self.git_cmd("reset", "--hard", "HEAD~1", cwd=wt)
        self.git_cmd("branch", "dev/foreign", "main")
        wt_f = self.base / "wt-foreign"
        self.git_cmd("worktree", "add", "-q", str(wt_f), "dev/foreign")
        (wt_f / "other.txt").write_text("foreign\n")
        self.git_cmd("add", "other.txt", cwd=wt_f)
        self.git_cmd("commit", "-q", "-m", "foreign commit", cwd=wt_f)
        self.git_cmd("merge", "--no-ff", "-m", "merge foreign", "dev/foreign", cwd=wt)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertEqual(cm.exception.code, LAND_REFUSED)
        self.assertIn("re-review", err.getvalue())

        # Reset back to approved commit and merge main (pure base merge) -> ALLOWED!
        self.git_cmd("reset", "--hard", "HEAD~1", cwd=wt)
        (self.repo / "main_only.txt").write_text("main\n")
        self.git_cmd("add", "main_only.txt")
        self.git_cmd("commit", "-q", "-m", "advance main")
        self.git_cmd("merge", "--no-ff", "-m", "merge main", "main", cwd=wt)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_land(argparse.Namespace(id=tid, keep=False, message=None, timeout=60), ctx=self.ctx)
        self.assertIn("merged as", out.getvalue())

    def test_worker_cannot_start_exec_helper(self) -> None:
        self.make_worker_task("noexec", branch="dev/noexec", pane="hc:t20", status="in_progress")
        self.be("hc:t20")
        with self.assertRaises(SystemExit) as cm:
            helpers_cmds.cmd_helper_start(argparse.Namespace(
                prompt="run install.sh", brief=None, name="inst", profile="light", kind=None, model=None,
                effort=None, advisor=None, codex_profile=None, timeout=None, cwd=None, task=None, pm=False,
                repo=str(self.repo), confirmed=False, dry_run=False, exec_mode=True, async_=True, for_task=None,
            ), ctx=self.ctx)
        self.assertIn("only the PM may start an execution helper", str(cm.exception.code))


class StuckPromptAndTriageTests(DelegateBase):
    def test_known_prompt_action_handles_agy_trust_inline_trust_and_update_prompts(self) -> None:
        self.assertEqual(trust_keys(AGY_TRUST), ["enter"])
        self.assertEqual(trust_keys(AGY_TRUST_SECOND), ["enter"])
        self.assertEqual(trust_keys(INLINE_TRUST), ["y", "enter"])
        self.assertEqual(update_keys(CODEX_UPDATE), ["down", "enter"])
        self.assertEqual(known_prompt_action(CODEX_UPDATE, allow_trust=False), ("update", ["down", "enter"]))
        self.assertEqual(known_prompt_action(AGY_TRUST, allow_trust=False), (None, None))
        self.assertEqual(known_prompt_action(AGY_TRUST, allow_trust=True), ("trust", ["enter"]))

    def test_scrollback_trust_or_update_never_auto_answers_destructive_or_permission_dialogs(self) -> None:
        # 1. Scrollback has earlier 'trust this folder', current bottom dialog asks to run rm -rf -> MUST NOT auto-press!
        scrollback_rm = (
            "Earlier startup: Do you trust this folder /Users/dev/.herdr/worktrees/dudu/dev-x?\n"
            + "\n".join(f"log line {i}" for i in range(10))
            + "\nDo you want to run `rm -rf /important`?\n"
            "  ❯ 1. Yes\n"
            "    2. No\n"
        )
        self.assertIsNone(trust_keys(scrollback_rm))
        self.assertEqual(known_prompt_action(scrollback_rm, allow_trust=True), (None, None))
        self.assertEqual(classify_stuck_screen(scrollback_rm)["kind"], "permission")

        # Even if 'trust this folder' appears only 2 lines above an rm -rf confirmation, forbidden filter blocks it!
        near_rm = (
            "Note: already checked trust this folder\n"
            "Do you want to run `rm -rf ./build`?\n"
            "  ❯ 1. Yes\n"
            "    2. No\n"
        )
        self.assertIsNone(trust_keys(near_rm))
        self.assertEqual(known_prompt_action(near_rm, allow_trust=True), (None, None))

        # 2. Scrollback has earlier 'Update available', current bottom prompt is a [y/n] question -> MUST NOT auto-press n!
        scrollback_yn = (
            "Update available! 0.171.0 -> 0.172.0\n"
            + "\n".join(f"output {i}" for i in range(6))
            + "\nOverwrite existing config file? [y/N]\n"
        )
        self.assertIsNone(update_keys(scrollback_yn))
        self.assertEqual(known_prompt_action(scrollback_yn, allow_trust=True), (None, None))

        # 3. Claude Code ready status bar ('bypass permissions on') is NOT classified as a permission dialog!
        claude_ready = "> \n  ⏵⏵ bypass permissions on"
        self.assertNotEqual(classify_stuck_screen(claude_ready)["kind"], "permission")

    def test_classify_stuck_screen_recognizes_quota_auth_hook_and_unknown(self) -> None:
        self.assertEqual(classify_stuck_screen(QUOTA_SCREEN)["kind"], "quota")
        self.assertEqual(classify_stuck_screen(AUTH_SCREEN)["kind"], "auth")
        self.assertEqual(classify_stuck_screen(HOOK_SCREEN)["kind"], "hook_review")

    def test_watch_workers_auto_handles_known_prompts_and_classifies_quota_without_hc_read(self) -> None:
        wt_root = Path.home() / ".herdr" / "worktrees" / "dudu" / "dev-auto-test"
        tid1 = f"{self.name}-auto1"
        tid2 = f"{self.name}-auto2"
        self.save_raw({
            "id": tid1, "title": "自动信任", "project": self.repo.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "branch": "dev/auto1",
            "worktree": str(wt_root), "pane": "hc:t30", "dispatched": True, "created": self.clock.now(), "log": [],
            "round": {"terminal": "t30", "at": self.clock.now(), "turn": 0},
        })
        self.save_raw({
            "id": tid2, "title": "配额错误", "project": self.repo.name, "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "branch": "dev/auto2",
            "worktree": str(wt_root), "pane": "hc:t31", "dispatched": True, "created": self.clock.now(), "log": [],
            "worker": {"kind": "agy"}, "round": {"terminal": "t31", "at": self.clock.now(), "turn": 0},
        })
        self.hc.terminals["t30"] = {"state": "live", "status": {"state": "blocked"}, "turn": 0, "screen": AGY_TRUST}
        self.hc.terminals["t31"] = {"state": "live", "status": {"state": "idle"}, "turn": 1, "screen": QUOTA_SCREEN}

        stops: dict = {}
        bases: dict = {}
        tasks = [self.load_raw(tid1), self.load_raw(tid2)]
        watcher = StallWatcher(self.ctx, stall_grace=0)
        watcher.watch_workers(tasks, stops, bases)
        watcher.watch_workers(tasks, stops, bases)

        # t30 trust dialog was auto-answered via hc keys, with NO stall event for PM
        self.assertIn(("t30", ("enter",)), self.hc.key_calls)
        stalls = [e for e in Conversation(self.ctx, str(self.repo)).events() if e.get("type") == "stall"]
        self.assertEqual([e["task"] for e in stalls], [tid2])
        self.assertIn("quota/rate limit", stalls[0]["text"])
        self.assertIn("escalate", stalls[0]["text"])
        self.assertNotIn("hc read", stalls[0]["text"])

    def test_triage_spawns_async_exec_helper_and_returns_immediately(self) -> None:
        tid, _, _ = self.make_worker_task("stuck", branch="dev/stuck", pane="hc:t20", status="in_progress")
        self.be("hc:t7")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review_cmds.cmd_triage(argparse.Namespace(
                id=tid, note="stuck on dialog", profile=None, kind=None,
                model=None, effort=None, advisor=None, codex_profile=None, confirmed=False,
            ), ctx=self.ctx)
        self.assertIn("triage delegated to exec helper", out.getvalue())
        self.assertEqual(len(self.spawned_by("_deliver-ready")), 1)
        reg = self.ctx.store.registration(self.name)
        helpers = helper_entries(reg)
        self.assertEqual(len(helpers), 1)
        self.assertEqual(helpers[0]["mode"], "exec")
        self.assertEqual(helpers[0]["for_task"], tid)


class AsyncSendHintsAndCompatTests(DelegateBase):
    def test_pm_send_is_async_by_default_and_deliver_send_handles_success_and_failure(self) -> None:
        tid, _, _ = self.make_worker_task("msg", branch="dev/msg", pane="hc:t20", status="in_progress")
        self.be("hc:t7")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            workers_cmds.cmd_send(argparse.Namespace(
                target=tid, message="继续做", file=None, task=None,
                repo=str(self.repo), timeout=180, wait=False,
            ), ctx=self.ctx)
        self.assertIn("queued async send to hc:t20", out.getvalue())
        sends = self.async_sends()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0], ("t20", "[from hc:t7] 继续做"))

        # The detached drain types it under the terminal's lease; once it went in, the round is handed.
        self.be("")
        self.assertEqual(run_spawned_drains(self.ctx), 1)
        self.assertIn(("t20", "[from hc:t7 #"), [(t, m[:len("[from hc:t7 #")]) for t, m in self.hc.sent])
        self.assertTrue(self.hc.sent[-1][1].endswith("] 继续做"))
        self.assertEqual(self.load_raw(tid)["round"]["turn"], 2)

        # A queued send that does not go in (terminal gone) wakes the PM with a triage hint.
        self.hc.terminals.pop("t20", None)
        self.be("hc:t7")
        with contextlib.redirect_stdout(io.StringIO()):
            Workers(self.ctx).send_async_later("t20", "[from hc:t7] 再试", task_id=tid, repo=str(self.repo))
        self.be("")
        run_spawned_drains(self.ctx)
        _, _, items = Delivery(self.ctx, str(self.repo)).pending_batch()
        self.assertEqual(len(items), 1)
        self.assertIn(f"pm.py triage {tid}", items[0]["event"]["text"])

    def test_batch_text_hints_approve_on_review_pass_and_legacy_worker_merged_wakes_pm(self) -> None:
        tid, _, sha = self.make_worker_task("revpass", branch="dev/rp", pane="hc:t20", status="review")
        delivery = Delivery(self.ctx, str(self.repo))
        # Simulate combined review pass event
        items = [{"event": {
            "type": "thread", "task": f"{tid}-review", "review_of": tid, "status": "done",
            "source": "worker", "by": "hc:t25", "worker_commit": sha, "worker_note": "all green",
            "text": "status=done; 无阻塞，测试全过",
        }, "earlier": 0}]
        rendered = delivery.batch_text(0, 100, items)
        self.assertIn(f"pm.py approve {tid}", rendered)

        # Simulate blockers verdict -> hints update --send or escalate
        items_blk = [{"event": {
            "type": "thread", "task": f"{tid}-review", "review_of": tid, "status": "done",
            "source": "worker", "by": "hc:t25", "worker_commit": sha, "worker_note": "all green",
            "text": "status=done; 1. 缺空值校验",
        }, "earlier": 0}]
        rendered_blk = delivery.batch_text(0, 100, items_blk)
        self.assertIn(f"pm.py update {tid} --status in_progress", rendered_blk)

        # A merged event with empty/missing `source` must NOT wake PM, while `source="worker"` DOES wake PM.
        conv = Conversation(self.ctx, str(self.repo))
        conv.record("thread", task=tid, title="legacy", status="merged",
                    by="hc:t20", text="status=merged, commit=abc1234; landed: 1 checks passed")
        t = self.load_raw(tid)
        t["status"] = "merged"
        self.save_raw(t)
        _, end, batch = delivery.pending_batch()
        self.assertEqual(batch, [])
        delivery.advance_delivered(end)

        conv.record("thread", task=tid, title="worker-landed", status="merged",
                    by="hc:t20", source="worker", text="status=merged, commit=abc1234; landed: 1 checks passed")
        _, _, batch2 = delivery.pending_batch()
        self.assertEqual([i["event"]["task"] for i in batch2], [tid])


class ReviewStage5FindingsTests(DelegateBase):
    """Regression tests for Stage 5 bugs found in pass-two final review r3."""

    def test_reviews_start_releases_codex_pool_lock_on_early_failure(self) -> None:
        from pmlib.homemove import _is_flock_held
        from pmlib.review.review import ReviewFailed, ReviewRequest, Reviews

        tid, _, _ = self.make_worker_task("pool", branch="dev/pool", pane="hc:t20", status="review")
        # Configure a codex pool so `Reviews.start` acquires `locks/codex-<project>.lock`.
        self.ctx.home.config.write_text(json.dumps({
            "codex": {"profiles": [{"name": "p1", "max": 2}]},
            "reviewer": {"kind": "codex", "model": "gpt-5"},
        }), encoding="utf-8")
        # Seed a conflicting `<tid>-review` task without `review_of == tid` so `Reviews.start` raises `ReviewFailed`
        # right after `apply_codex_pool(..., hold=True)`.
        self.save_raw({
            "id": f"{tid}-review", "title": "unrelated", "project": self.name,
            "repo": str(self.repo), "status": "in_progress", "base": "main",
            "review_of": "other-task", "log": [],
        })
        self.be("hc:t7")
        lock_path = self.ctx.home.lock(f"codex-pool-{self.name}")
        caught = None
        try:
            Reviews(self.ctx).start(ReviewRequest(id=tid, kind="codex"))
        except ReviewFailed as err:
            caught = err
        self.assertIsNotNone(caught)
        try:
            # Even while `caught` (and its traceback) is still live in scope, the exclusive pool lock must be released.
            self.assertFalse(_is_flock_held(lock_path), "Reviews.start leaked exclusive codex pool flock on ReviewFailed")
        finally:
            # Clean up leaked fd in test harness so expectedFailure does not emit ResourceWarning during GC.
            tb = caught.__traceback__
            while tb is not None:
                w = tb.tb_frame.f_locals.get("workers")
                fh = getattr(w, "_pool_lock", None)
                if fh is not None:
                    w._pool_lock = None
                    fh.close()
                tb = tb.tb_next


if __name__ == "__main__":
    unittest.main()
