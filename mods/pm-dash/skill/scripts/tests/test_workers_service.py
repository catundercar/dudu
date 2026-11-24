"""Context-based unit tests for Stage 4a `Workers(ctx)` service using `tests/fakes.py` (zero `pm.*` patches)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import FakeClock, FakeHc, FakeProcs, FakeTui, StubGit, make_ctx  # noqa: E402
from pmlib.agents.profiles import WorkerSpec  # noqa: E402
from pmlib.errors import Refused, WaitOutcome  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.store import lock_file, unlock_file  # noqa: E402
from pmlib.workers import codex_pool as codex_pool_mod  # noqa: E402
from pmlib.workers.service import DispatchRequest, EscalateRequest, Workers  # noqa: E402


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True, capture_output=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True)
    return path


class WorkersServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-workers-svc-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger_dir = self.root / "ledger"
        self.repo = _init_git_repo(self.root / "demo")
        self.brief = self.root / "brief.md"
        self.brief.write_text("# Task\nDo the work.\n")

    def _make_ctx(self, *, pane: str = "hc:t1", hc: FakeHc | None = None, tui: FakeTui | None = None,
                  config: dict | None = None, git: object = None, clock: FakeClock | None = None):
        return make_ctx(
            self.ledger_dir,
            pane=pane,
            hc=hc if hc is not None else FakeHc(terminals={
                "t1": {"state": "live", "name": "pm-demo", "labels": {"pm": "demo"}, "status": {"state": "idle"}, "turn": 1},
            }),
            tui=tui if tui is not None else FakeTui(),
            config=config or {},
            git=git if git is not None else GitRepo(),
            clock=clock if clock is not None else FakeClock(),
        )

    def _register_hc_pm(self, ctx, term: str = "t1") -> None:
        ctx.store.change_registration("demo", lambda _cur: {
            "name": "pm-demo",
            "project": "demo",
            "repo": str(self.repo),
            "runtime": "hc",
            "terminal": term,
            "pane": f"hc:{term}",
        })

    def test_dispatch_hc_dry_run_and_async(self) -> None:
        hc = FakeHc(terminals={
            "t1": {"state": "live", "name": "pm-demo", "labels": {"pm": "demo"}, "status": {"state": "idle"}, "turn": 1},
        })
        ctx = self._make_ctx(pane="hc:t1", hc=hc)
        self._register_hc_pm(ctx)
        svc = Workers(ctx)

        dry = svc.dispatch(DispatchRequest(
            title="Build widget", repo=str(self.repo), branch="dev/widget", brief=str(self.brief), dry_run=True,
        ))
        self.assertIsNotNone(dry.dry_run_plan)
        assert dry.dry_run_plan is not None
        self.assertEqual(dry.dry_run_plan["what"], "dispatch")
        self.assertEqual(Ledger(ctx).raw_tasks(), [])

        wt_path = self.root / "wt-widget"
        res = svc.dispatch(DispatchRequest(
            title="Build widget", repo=str(self.repo), branch="dev/widget",
            path=str(wt_path), brief=str(self.brief), async_=True,
        ))
        self.assertTrue(res.task_id.startswith("demo-"))
        self.assertTrue(res.pane.startswith("hc:t"))
        self.assertTrue(wt_path.is_dir())
        task = Ledger(ctx).load(res.task_id)
        self.assertEqual(task["status"], "in_progress")
        self.assertTrue(task["dispatched"])
        # Async brief delivery + deliverer spawned via FakeProcs (no real subprocesses).
        cmds = [entry["args"][0] for entry in ctx.procs.spawned]
        self.assertIn("_deliver-ready", cmds)

    def test_dispatch_deep_asks_first_without_confirmed(self) -> None:
        ctx = self._make_ctx(pane="hc:t1")
        self._register_hc_pm(ctx)
        svc = Workers(ctx)

        res = svc.dispatch(DispatchRequest(
            title="Deep dive", repo=str(self.repo), branch="dev/deep",
            brief=str(self.brief), profile="deep",
        ))
        self.assertTrue(res.asked)
        task = Ledger(ctx).load(res.task_id)
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(task["held"], "ask")
        self.assertTrue(task.get("options"))

    def test_send_when_ready_handles_idle_and_stop_on_exit(self) -> None:
        clock = FakeClock()
        hc = FakeHc(terminals={
            "t2": {"state": "live", "status": {"state": "idle"}, "turn": 4},
            "t3": {"state": "exited", "status": {}},
        })
        ctx = self._make_ctx(pane="hc:t1", hc=hc, clock=clock)
        svc = Workers(ctx)

        seen: dict = {}
        ok = svc.send_when_ready("t2", "hello worker", tries=3, pause=1, strict=True, seen=seen)
        self.assertTrue(ok)
        self.assertEqual(seen["turn"], 4)
        self.assertEqual(hc.sent, [("t2", "hello worker")])

        exited = svc.send_when_ready("t3", "hello", tries=5, pause=1, stop_on_exit=True)
        self.assertFalse(exited)

    def test_send_and_send_back_unblock_worker_blocked_task(self) -> None:
        hc = FakeHc(terminals={
            "t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}, "turn": 1},
            "t2": {"state": "live", "labels": {"task": "demo-1"}, "status": {"state": "idle"}, "turn": 2},
        })
        ctx = self._make_ctx(pane="hc:t1", hc=hc)
        self._register_hc_pm(ctx)
        Ledger(ctx).create({
            "id": "demo-1", "title": "Fix", "project": "demo", "repo": str(self.repo),
            "status": "blocked", "base": "main", "pane": "hc:t2", "dispatched": True,
            "log": [{"at": "2026-11-23 00:00", "by": "hc:t2", "text": "status=blocked; need answer"}],
        })
        svc = Workers(ctx)
        res = svc.send("demo-1", "go ahead", wait=False)
        self.assertTrue(res.queued)
        self.assertEqual(Ledger(ctx).load("demo-1")["status"], "in_progress")
        self.assertEqual(ctx.procs.spawned[-1]["args"][0], "_deliver-send")

        back = svc.send_back(Ledger(ctx).load("demo-1"), "sync note", wait=True)
        self.assertFalse(back.queued)
        self.assertIn("sent to hc:t2", back.message)

    def test_wait_outcomes_codes_2_3_4_and_report(self) -> None:
        clock = FakeClock()
        hc = FakeHc(terminals={
            "t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
            "t2": {"state": "live", "labels": {"task": "demo-w"}, "status": {"state": "idle"}},
        }, clock=clock)
        # Code 4: desktop-app PM cannot call wait
        ctx_pm = self._make_ctx(pane="hc:t1", hc=hc, clock=clock)
        self._register_hc_pm(ctx_pm)
        Ledger(ctx_pm).create({
            "id": "demo-w", "title": "Wait me", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "base": "main", "pane": "hc:t2", "log": [],
        })
        with self.assertRaises(WaitOutcome) as cm4:
            Workers(ctx_pm).wait("demo-w", timeout=10)
        self.assertEqual(cm4.exception.code, 4)

        # Code 3: worker stopped without reporting after grace period
        ctx_cli = self._make_ctx(pane="", hc=hc, clock=clock)
        with self.assertRaises(WaitOutcome) as cm3:
            Workers(ctx_cli).wait("demo-w", timeout=30)
        self.assertEqual(cm3.exception.code, 3)

        # Code 2: timeout while worker stays working
        hc.terminals["t2"]["status"] = {"state": "working"}
        with self.assertRaises(WaitOutcome) as cm2:
            Workers(ctx_cli).wait("demo-w", timeout=5)
        self.assertEqual(cm2.exception.code, 2)

        # Success: worker reports during wait -> WaitResult
        from pmlib.workers.wait import wait_for_report_events_for

        class _ReportingWaiter:
            def wait(self, _timeout: float) -> bool:
                Ledger(ctx_cli).change(
                    "demo-w",
                    lambda cur, ch: (cur.raw.update(status="review", commit="abc1234"), ch.note_on(cur.raw, "status=review; done"), cur.raw)[2],
                )
                return True

        res = wait_for_report_events_for(ctx_cli, "demo-w", _ReportingWaiter(), Ledger(ctx_cli).load("demo-w").raw, timeout=5)
        self.assertEqual(res.status, "review")
        self.assertEqual(res.commit, "abc1234")

    def test_retire_refuses_unmerged_and_succeeds_after_merge(self) -> None:
        hc = FakeHc(terminals={
            "t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
            "t2": {"state": "live", "labels": {"task": "demo-r"}, "cwd": str(self.root / "wt-r"), "status": {"state": "idle"}},
        })
        ctx = self._make_ctx(pane="hc:t1", hc=hc)
        self._register_hc_pm(ctx)
        wt = self.root / "wt-r"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", str(wt), "-b", "dev/r", "main"], check=True, capture_output=True)
        (wt / "feature.txt").write_text("new\n")
        subprocess.run(["git", "-C", str(wt), "add", "feature.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat"], check=True, capture_output=True)
        Ledger(ctx).create({
            "id": "demo-r", "title": "Feature", "project": "demo", "repo": str(self.repo),
            "status": "review", "base": "main", "branch": "dev/r", "worktree": str(wt),
            "pane": "hc:t2", "dispatched": True, "log": [],
        })
        svc = Workers(ctx)
        with self.assertRaises(Refused):
            svc.retire("demo-r", force=False)

        subprocess.run(["git", "-C", str(self.repo), "merge", "--no-ff", "dev/r", "-m", "merge"], check=True, capture_output=True)
        res = svc.retire("demo-r", force=False)
        self.assertIn("worktree", res.summary)
        self.assertIn("branch dev/r", res.summary)
        self.assertFalse(wt.exists())
        self.assertNotIn("t2", hc.terminals)

    def test_idle_workers_and_close_worker_respect_active_review(self) -> None:
        clock = FakeClock()
        old_ms = int((clock.time() - 3600) * 1000)
        hc = FakeHc(terminals={
            "t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
            "t2": {"state": "live", "labels": {"task": "demo-i"}, "status": {"state": "idle"}, "status_ms": old_ms, "name": "w-i"},
        })
        ctx = self._make_ctx(pane="hc:t1", hc=hc, clock=clock, config={"workers": {"close_on_close": True}})
        self._register_hc_pm(ctx)
        Ledger(ctx).create({
            "id": "demo-i", "title": "Idle task", "project": "demo", "repo": str(self.repo),
            "status": "review", "base": "main", "pane": "hc:t2", "dispatched": True, "log": [],
        })
        Ledger(ctx).create({
            "id": "demo-i-review", "title": "Review", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "base": "main", "review_of": "demo-i", "pane": "hc:t3", "log": [],
        })
        svc = Workers(ctx)
        # Active review keeps worker alive on both close_worker and idle_workers --close
        kept = svc.close_worker(Ledger(ctx).load("demo-i"))
        self.assertIn("active review demo-i-review", kept)
        res = svc.idle_workers(repo=str(self.repo), minutes=10, close=["t2"])
        self.assertEqual(len(res.rows), 1)
        self.assertIn("kept", res.closed_lines[0])
        self.assertIn("t2", hc.terminals)

    def test_codex_pool_and_fake_tui_server_down_alignment(self) -> None:
        # FakeTui(server_ok=False) aligns with TuiHost when Workers queries ctx.tui.
        tui_down = FakeTui(server_ok=False)
        ctx = self._make_ctx(
            pane="",
            tui=tui_down,
            config={"codex": {"profiles": [{"name": "p1", "max": 1}], "allow_default": False}},
        )
        svc = Workers(ctx)
        self.assertEqual(svc.live_worker({"id": "x", "pane": "w1:p2", "status": "in_progress"}), "")
        self.assertEqual(svc.end_worker({"id": "x", "pane": "w1:p2", "worker_pane": "w1:p2", "agent": "a"}), "")
        with self.assertRaises(Refused):
            svc.apply_codex_pool(WorkerSpec(kind="codex", codex_profile="default"), self.repo, hold=False)

    def test_codex_pool_lock_released_on_refused_and_tui_escalate(self) -> None:
        """Finding P4:
        1) `Workers.apply_codex_pool(..., hold=True)` releases `lock_fh` when `Refused` is raised;
        2) `Workers.dispatch` (`asks=True` or pre-start failure) and `Workers.escalate` (`asks=True` or `index.lock`
           failure) release `self._pool_lock`;
        3) TUI `Workers.escalate` explicitly unlocks & closes `pool_lock` in `start_escalated_for`."""
        cfg = {
            "codex": {"profiles": [{"name": "p1", "max": 2}], "allow_default": False, "model": "gpt-x"},
            "profiles": {"cx-next": {"kind": "codex", "model": "gpt-x", "effort": "high"}},
        }
        tui = FakeTui(
            agents=[{"pane_id": "w2:p1", "workspace_id": "w2", "name": "w-old", "agent_status": "idle"}],
            panes=[{"pane_id": "w2:p1", "workspace_id": "w2"}],
            workspaces=[{"workspace_id": "w2", "label": "demo"}],
        )
        ctx = self._make_ctx(pane="w1:p0", tui=tui, config=cfg)
        slug = project_slug(str(self.repo))
        lock_path = ctx.home.locks / f"codex-pool-{slug}.lock"

        def assert_unlocked() -> None:
            self.assertTrue(lock_path.is_file())
            with open(lock_path, "a+") as probe:
                try:
                    lock_file(probe)
                except OSError as exc:
                    self.fail(f"{lock_path} remained flock-locked: {exc}")
                else:
                    unlock_file(probe)

        with mock.patch.object(codex_pool_mod, "_live_codex_impl", return_value=[]):
            # 1. Refused inside apply_codex_pool leaves `lock_fh` unlocked.
            svc1 = Workers(ctx)
            try:
                svc1.apply_codex_pool(WorkerSpec(kind="codex", codex_profile="default"), str(self.repo), hold=True)
            except Refused:
                assert_unlocked()
            else:
                self.fail("expected Refused for disallowed default codex profile")

            # 2. Dispatch with `asks=True` (`codex -m fable`) returns early and releases `svc2._pool_lock`.
            svc2 = Workers(ctx)
            res_ask = svc2.dispatch(DispatchRequest(
                title="Ask first", repo=str(self.repo), branch="dev/ask", brief=str(self.brief),
                kind="codex", model="fable",
            ))
            self.assertTrue(res_ask.asked)
            self.assertIsNone(svc2._pool_lock)
            assert_unlocked()

            # 3. TUI escalate onto a codex profile explicitly unlocks & closes `pool_lock` without ResourceWarning.
            wt = self.root / "wt-cx"
            subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-b", "dev/cx", str(wt), "main"],
                           check=True, capture_output=True)
            Ledger(ctx).save({
                "id": "demo-cx", "title": "cx", "project": "demo", "repo": str(self.repo),
                "status": "review", "owner": "pm", "base": "main", "branch": "dev/cx", "worktree": str(wt),
                "workspace": "w2", "pane": "w2:p1", "worker_pane": "w2:p1", "agent": "w-old",
                "created": ctx.clock.now(), "worker": {"profile": "light", "kind": "claude", "model": "sonnet"},
            })
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                Workers(ctx).escalate(EscalateRequest(task_id="demo-cx", profile="cx-next"))
            leaked = [w for w in caught if issubclass(w.category, ResourceWarning) and "codex-pool" in str(w.message)]
            self.assertEqual(leaked, [])
            assert_unlocked()

    def test_worker_busy_and_wait_respect_background_work_and_land_approved(self) -> None:
        """`worker_busy_for` recognizes background work; `wait_for_report_events_for` respects
        `land_approved` + active `locks/land-<slug>.lock` and helper-executed merges."""
        from pmlib.errors import WaitOutcome
        from pmlib.workers.escalate import worker_busy_for
        from pmlib.workers.wait import wait_for_report_events_for

        clock = FakeClock("2026-11-23 12:00:00", mono=100.0)
        hc = FakeHc(clock=clock)
        hc.terminals["t20"] = {
            "address": "t20", "state": "live", "pid": 4321,
            "status": {"state": "done"}, "turn": 2,
        }
        ctx = self._make_ctx(pane="hc:t1", hc=hc, clock=clock)
        ctx.procs._background_work = {4321: ["python3 tests/run_checks.py"]}
        self.assertTrue(worker_busy_for(ctx, "hc:t20"))
        ctx.procs._background_work = {}
        self.assertFalse(worker_busy_for(ctx, "hc:t20"))

        class _ClockWaiter:
            def follow(self, _args=None):
                pass
            def wait(self, sec):
                clock.advance(max(sec, 1.0))

        # 1. land_approved with active land-<slug>.lock does not raise stopped-without-reporting (code 3);
        #    it waits until timeout (code 2).
        task = {
            "id": "demo-land", "title": "land", "project": "demo", "repo": str(self.repo),
            "status": "in_progress", "owner": "pm", "base": "main", "branch": "dev/land",
            "pane": "hc:t20", "created": clock.now(), "log": [],
            "land_approved": {"commit": "abc1234", "at": clock.now(), "by": "hc:t1", "executor": "worker"},
        }
        Ledger(ctx).save(task)
        land_lock = ctx.home.lock(f"land-{project_slug(str(self.repo))}")
        land_lock.parent.mkdir(parents=True, exist_ok=True)
        with open(land_lock, "a+") as held:
            lock_file(held)
            try:
                with self.assertRaises(WaitOutcome) as cm:
                    wait_for_report_events_for(ctx, "demo-land", _ClockWaiter(), task, timeout=10)
                self.assertEqual(cm.exception.code, 2)
            finally:
                unlock_file(held)

        # 2. land_approved with executor="helper" and exited original worker does not raise code 3.
        hc.terminals["t20"]["state"] = "exited"
        task["land_approved"]["executor"] = "helper"
        Ledger(ctx).save(task)
        with self.assertRaises(WaitOutcome) as cm2:
            wait_for_report_events_for(ctx, "demo-land", _ClockWaiter(), task, timeout=10)
        self.assertEqual(cm2.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
