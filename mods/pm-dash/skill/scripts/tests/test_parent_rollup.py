"""Context-based tests for Stage 7b: parent task automatic roll-up (#210, reactions.py row 10)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SCRIPTS / "tests") not in sys.path:
    sys.path.insert(0, str(SCRIPTS / "tests"))

from fakes import FakeClock, FakeHc, FakeProcs, FakeTui, make_ctx  # noqa: E402
from pmlib.messaging import router as policy  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.landing import ApproveRequest, LandRequest, Landing  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.transition import UpdateRequest  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.reactions import Updates  # noqa: E402


def _register_hc_pm(ctx, repo: str, terminal: str = "t1") -> dict:
    slug = project_slug(repo)
    rec = {
        "name": f"pm-{slug}",
        "project": Path(repo).name,
        "repo": repo,
        "runtime": "hc",
        "terminal": terminal,
        "pane": f"hc:{terminal}",
        "agent": "claude",
    }
    ctx.home.registrations.mkdir(parents=True, exist_ok=True)
    ctx.home.registration(slug).write_text(json.dumps(rec))
    return rec


def _write_task(ctx, repo: str, task_id: str, **extra) -> dict:
    ctx.home.tasks.mkdir(parents=True, exist_ok=True)
    task = {
        "id": task_id,
        "title": extra.pop("title", task_id),
        "project": Path(repo).name,
        "repo": repo,
        "status": extra.pop("status", "in_progress"),
        "base": "main",
        "owner": "pm",
        "workspace": "",
        "pane": "",
        "created": "2026-11-22 10:00",
        "log": [],
        **extra,
    }
    ctx.home.task(task_id).write_text(json.dumps(task))
    return task


class ParentRollupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def _make(self, *, pane: str = "hc:t1", terminals: dict | None = None, tui_agents: list | None = None,
              with_pm: bool = True):
        clk = FakeClock()
        terms = {"t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}}}
        if terminals:
            terms.update(terminals)
        hc = FakeHc(terminals=terms, clock=clk)
        tui = FakeTui(agents=tui_agents or [])
        ctx = make_ctx(self.tmp.name, pane=pane, hc=hc, tui=tui, clock=clk)
        if with_pm:
            _register_hc_pm(ctx, self.repo, "t1")
        return ctx, ctx.procs

    def test_all_children_finished_auto_closes_parent_wakes_pm_and_reconciles_dependents(self):
        ctx, procs = self._make(pane="hc:t1")
        _write_task(ctx, self.repo, "demo-parent", status="in_progress")
        _write_task(ctx, self.repo, "demo-c1", status="in_progress", parent="demo-parent")
        _write_task(ctx, self.repo, "demo-c2", status="in_progress", parent="demo-parent")
        _write_task(ctx, self.repo, "demo-after", status="proposed", depends_on=["demo-parent"])

        # Closing first child leaves parent open.
        Updates(ctx).update(UpdateRequest(id="demo-c1", status="merged", keep=True))
        self.assertEqual(ctx.store.task("demo-parent")["status"], "in_progress")
        self.assertEqual(procs.spawned, [])

        # Closing second child auto-closes parent to done, wakes PM, and triggers deps on demo-after.
        Updates(ctx).update(UpdateRequest(id="demo-c2", status="done", keep=True))
        parent = ctx.store.task("demo-parent")
        self.assertEqual(parent["status"], "done")
        self.assertTrue(any("status=done; all 2 child tasks finished" in e["text"] for e in parent["log"]))

        events = Conversation(ctx, self.repo).events()
        rollup_ev = [e for e in events if e.get("task") == "demo-parent" and e.get("source") == "rollup"]
        self.assertEqual(len(rollup_ev), 1)
        self.assertEqual(rollup_ev[0]["type"], "thread")
        self.assertEqual(rollup_ev[0]["status"], "done")
        self.assertTrue(rollup_ev[0].get("wake"))

        deps_ev = [e for e in events if e.get("task") == "demo-after" and e.get("source") == "deps"]
        self.assertEqual(len(deps_ev), 1)
        self.assertTrue(deps_ev[0].get("wake"))

        # Deliverer was started and pending_batch sees the rollup close event even though PM ran update.
        self.assertTrue(any(s["args"][:1] == ["deliver"] for s in procs.spawned))
        _s, _e, items = Delivery(ctx, self.repo).pending_batch(settle=False)
        self.assertTrue(any(i["event"].get("task") == "demo-parent" and i["event"].get("source") == "rollup" for i in items))

    def test_auto_close_without_app_pm_does_not_wake_or_spawn_deliver(self):
        ctx, procs = self._make(pane="", with_pm=False)
        _write_task(ctx, self.repo, "demo-parent", status="in_progress")
        _write_task(ctx, self.repo, "demo-c1", status="in_progress", parent="demo-parent")

        Updates(ctx).update(UpdateRequest(id="demo-c1", status="merged", keep=True))
        parent = ctx.store.task("demo-parent")
        self.assertEqual(parent["status"], "done")
        events = Conversation(ctx, self.repo).events()
        rollup_ev = [e for e in events if e.get("task") == "demo-parent" and e.get("source") == "rollup"]
        self.assertEqual(len(rollup_ev), 1)
        self.assertFalse(rollup_ev[0].get("wake"))
        self.assertEqual(procs.spawned, [])

    def test_at_least_one_non_abandoned_closes_but_all_abandoned_notifies_only(self):
        # Case A: 1 abandoned + 1 merged -> auto-close
        ctx, _procs = self._make()
        _write_task(ctx, self.repo, "demo-p1", status="in_progress")
        _write_task(ctx, self.repo, "demo-a1", status="abandoned", parent="demo-p1")
        _write_task(ctx, self.repo, "demo-a2", status="in_progress", parent="demo-p1")
        Updates(ctx).update(UpdateRequest(id="demo-a2", status="merged", keep=True))
        self.assertEqual(ctx.store.task("demo-p1")["status"], "done")

        # Case B: all abandoned -> notify only, parent stays open
        _write_task(ctx, self.repo, "demo-p2", status="in_progress")
        _write_task(ctx, self.repo, "demo-b1", status="abandoned", parent="demo-p2")
        _write_task(ctx, self.repo, "demo-b2", status="in_progress", parent="demo-p2")
        Updates(ctx).update(UpdateRequest(id="demo-b2", status="abandoned", keep=True))

        p2 = ctx.store.task("demo-p2")
        self.assertEqual(p2["status"], "in_progress")
        self.assertTrue(p2.get("rollup_notified"))
        events = Conversation(ctx, self.repo).events()
        ev = [e for e in events if e.get("task") == "demo-p2" and e.get("source") == "rollup"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["type"], "event")
        self.assertTrue(ev[0].get("wake"))
        self.assertIn("abandoned", ev[0]["text"])

    def test_parent_with_own_work_notifies_only(self):
        # 1. Parent in review status
        ctx, procs = self._make(terminals={"t9": {"state": "live", "status": {"state": "working"}}})
        _write_task(ctx, self.repo, "demo-rev", status="review")
        _write_task(ctx, self.repo, "demo-rev-c1", status="in_progress", parent="demo-rev")
        Updates(ctx).update(UpdateRequest(id="demo-rev-c1", status="done", keep=True))
        self.assertEqual(ctx.store.task("demo-rev")["status"], "review")
        self.assertTrue(ctx.store.task("demo-rev").get("rollup_notified"))
        self.assertTrue(any(s["args"][:1] == ["deliver"] for s in procs.spawned))

        # 2. Parent with running helper
        _write_task(ctx, self.repo, "demo-hlp", status="in_progress", helpers=[{"name": "h1", "status": "running"}])
        _write_task(ctx, self.repo, "demo-hlp-c1", status="in_progress", parent="demo-hlp")
        Updates(ctx).update(UpdateRequest(id="demo-hlp-c1", status="done", keep=True))
        self.assertEqual(ctx.store.task("demo-hlp")["status"], "in_progress")
        self.assertTrue(ctx.store.task("demo-hlp").get("rollup_notified"))

        # 3. Parent with live own hc session (not PM's terminal)
        _write_task(ctx, self.repo, "demo-own", status="in_progress", pane="hc:t9")
        _write_task(ctx, self.repo, "demo-own-c1", status="in_progress", parent="demo-own")
        Updates(ctx).update(UpdateRequest(id="demo-own-c1", status="done", keep=True))
        self.assertEqual(ctx.store.task("demo-own")["status"], "in_progress")
        self.assertTrue(ctx.store.task("demo-own").get("rollup_notified"))

        # 4. Parent with dead own hc session -> auto-closes
        _write_task(ctx, self.repo, "demo-dead", status="in_progress", pane="hc:t404")
        _write_task(ctx, self.repo, "demo-dead-c1", status="in_progress", parent="demo-dead")
        Updates(ctx).update(UpdateRequest(id="demo-dead-c1", status="done", keep=True))
        self.assertEqual(ctx.store.task("demo-dead")["status"], "done")

        # 5. Parent parked on PM's own terminal -> own_session_live is False -> auto-closes
        _write_task(ctx, self.repo, "demo-pmpane", status="in_progress", pane="hc:t1")
        _write_task(ctx, self.repo, "demo-pmpane-c1", status="in_progress", parent="demo-pmpane")
        Updates(ctx).update(UpdateRequest(id="demo-pmpane-c1", status="done", keep=True))
        self.assertEqual(ctx.store.task("demo-pmpane")["status"], "done")

    def test_parent_with_live_tui_or_remote_pane_notifies_only(self):
        ctx, _procs = self._make(tui_agents=[{"pane_id": "w1:p2", "name": "solo"}])
        _write_task(ctx, self.repo, "demo-tui", status="in_progress", pane="w1:p2")
        _write_task(ctx, self.repo, "demo-tui-c1", status="in_progress", parent="demo-tui")
        Updates(ctx).update(UpdateRequest(id="demo-tui-c1", status="done", keep=True))
        self.assertEqual(ctx.store.task("demo-tui")["status"], "in_progress")
        self.assertTrue(ctx.store.task("demo-tui").get("rollup_notified"))

        _write_task(ctx, self.repo, "demo-rem", status="in_progress", pane="dev/t5")
        _write_task(ctx, self.repo, "demo-rem-c1", status="in_progress", parent="demo-rem")
        Updates(ctx).update(UpdateRequest(id="demo-rem-c1", status="done", keep=True))
        self.assertEqual(ctx.store.task("demo-rem")["status"], "in_progress")
        self.assertTrue(ctx.store.task("demo-rem").get("rollup_notified"))

    def test_concurrent_children_closing_deduplicates_notify_and_clears_on_add_or_reopen(self):
        ctx, _procs = self._make()
        _write_task(ctx, self.repo, "demo-parent", status="in_progress", branch="dev/parent")
        _write_task(ctx, self.repo, "demo-c1", status="in_progress", parent="demo-parent")
        _write_task(ctx, self.repo, "demo-c2", status="in_progress", parent="demo-parent")

        barrier = threading.Barrier(2)
        errors = []

        def _close(tid: str):
            try:
                barrier.wait(timeout=5)
                Updates(ctx).update(UpdateRequest(id=tid, status="done", keep=True))
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=_close, args=("demo-c1",))
        t2 = threading.Thread(target=_close, args=("demo-c2",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        self.assertEqual(errors, [])

        events = [e for e in Conversation(ctx, self.repo).events()
                  if e.get("task") == "demo-parent" and e.get("source") == "rollup"]
        self.assertEqual(len(events), 1)
        self.assertTrue(ctx.store.task("demo-parent").get("rollup_notified"))

        # Reopening c2 clears rollup_notified; closing it again emits a second notice.
        Updates(ctx).update(UpdateRequest(id="demo-c2", status="in_progress"))
        self.assertNotIn("rollup_notified", ctx.store.task("demo-parent"))

        Updates(ctx).update(UpdateRequest(id="demo-c2", status="done", keep=True))
        events_after_reopen = [e for e in Conversation(ctx, self.repo).events()
                               if e.get("task") == "demo-parent" and e.get("source") == "rollup"]
        self.assertEqual(len(events_after_reopen), 2)

        # Adding a new child via Ledger.create clears rollup_notified.
        Ledger(ctx).create({
            "id": "demo-c3",
            "title": "demo-c3",
            "project": "demo",
            "repo": self.repo,
            "status": "in_progress",
            "base": "main",
            "owner": "pm",
            "workspace": "",
            "pane": "",
            "parent": "demo-parent",
            "created": "2026-11-22 10:05",
            "log": [],
        })
        self.assertNotIn("rollup_notified", ctx.store.task("demo-parent"))

    def test_multilevel_cascade_depth_cap_and_cycle_guard(self):
        # 6-level ancestor chain: leaf -> p1 -> p2 -> p3 -> p4 -> p5 -> p6
        # Depth limit is 5, so p1..p5 close and p6 stays open.
        ctx, _procs = self._make()
        _write_task(ctx, self.repo, "demo-p6", status="in_progress")
        _write_task(ctx, self.repo, "demo-p5", status="in_progress", parent="demo-p6")
        _write_task(ctx, self.repo, "demo-p4", status="in_progress", parent="demo-p5")
        _write_task(ctx, self.repo, "demo-p3", status="in_progress", parent="demo-p4")
        _write_task(ctx, self.repo, "demo-p2", status="in_progress", parent="demo-p3")
        _write_task(ctx, self.repo, "demo-p1", status="in_progress", parent="demo-p2")
        _write_task(ctx, self.repo, "demo-leaf", status="in_progress", parent="demo-p1")
        _write_task(ctx, self.repo, "demo-dep", status="proposed", depends_on=["demo-p5"])

        Updates(ctx).update(UpdateRequest(id="demo-leaf", status="done", keep=True))
        for pid in ("demo-p1", "demo-p2", "demo-p3", "demo-p4", "demo-p5"):
            self.assertEqual(ctx.store.task(pid)["status"], "done", f"{pid} should auto-close")
        self.assertEqual(ctx.store.task("demo-p6")["status"], "in_progress", "depth > 5 must not close")
        deps_ev = [e for e in Conversation(ctx, self.repo).events()
                   if e.get("task") == "demo-dep" and e.get("source") == "deps"]
        self.assertEqual(len(deps_ev), 1)

        # Cycle guard: corrupted cycle on disk (cyc1 <-> cyc2) must terminate without hanging.
        _write_task(ctx, self.repo, "demo-cyc1", status="in_progress", parent="demo-cyc2")
        _write_task(ctx, self.repo, "demo-cyc2", status="in_progress", parent="demo-cyc1")
        _write_task(ctx, self.repo, "demo-cyc-leaf", status="in_progress", parent="demo-cyc1")
        Updates(ctx).update(UpdateRequest(id="demo-cyc-leaf", status="done", keep=True))
        # cyc1 has child cyc-leaf (done) and cyc2 (in_progress) -> stays open; now test direct self-cycle:
        _write_task(ctx, self.repo, "demo-self", status="in_progress", parent="demo-self")
        _write_task(ctx, self.repo, "demo-self-leaf", status="in_progress", parent="demo-self")
        Updates(ctx).update(UpdateRequest(id="demo-self-leaf", status="done", keep=True))
        # Terminates cleanly; demo-self has child demo-self itself (in_progress), so it stays open.
        self.assertEqual(ctx.store.task("demo-self")["status"], "in_progress")


class ParentRollupReviewFindingsTests(unittest.TestCase):
    """Regression tests for Stage 6c3 / 7b bugs found in pass-two final review r3."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-rollup-r3-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo_path = self.base / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path)

    def test_delegated_land_by_worker_rolls_up_parent_task(self):
        # Standard dudu flow: PM approves child task C1 (`pm.py approve C1`), worker runs `pm.py land C1`.
        # When C1 is the last open child of planning parent P, `Landing._landed_delegated` must roll up P to `done`.
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True, env=git_env)
        (self.repo_path / "f.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", self.repo, "add", "f.txt"], check=True, env=git_env)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "init"], check=True, env=git_env)
        wt = self.base / "wt-c1"
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", "-b", "dev/c1", str(wt), "main"],
                       check=True, env=git_env)
        (wt / "f.txt").write_text("child change\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(wt), "add", "f.txt"], check=True, env=git_env)
        subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "c1 work"], check=True, env=git_env)
        sha = subprocess.check_output(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True).strip()

        clk = FakeClock()
        hc = FakeHc({
            "t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
            "t20": {"state": "live", "labels": {"task": "demo-c1"}, "status": {"state": "idle"}, "turn": 1},
        }, clock=clk)
        git = GitRepo(worktree_base=self.base / "wts")
        pm_ctx = make_ctx(self.base / "home", pane="hc:t1", hc=hc, git=git, clock=clk, env=git_env)
        _register_hc_pm(pm_ctx, self.repo, "t1")
        verify = pm_ctx.home.project_for(self.repo).ensure() / "verify"
        verify.write_text(f'"{sys.executable}" -c "pass"\n' if os.name == "nt" else "true\n", encoding="utf-8")

        _write_task(pm_ctx, self.repo, "demo-parent", status="in_progress")
        _write_task(
            pm_ctx, self.repo, "demo-c1",
            status="review", parent="demo-parent", pane="hc:t20",
            branch="dev/c1", worktree=str(wt), commit=sha[:7], dispatched=True,
        )

        Landing(pm_ctx).approve(ApproveRequest(id="demo-c1", via="worker"))
        worker_ctx = make_ctx(self.base / "home", pane="hc:t20", hc=hc, git=git, clock=clk, env=git_env)
        Landing(worker_ctx).land(LandRequest(id="demo-c1"))

        self.assertEqual(pm_ctx.store.task("demo-c1")["status"], "merged")
        self.assertEqual(pm_ctx.store.task("demo-parent")["status"], "done")

    def test_rollup_summary_and_dep_hint_respect_ctx_config_lang(self):
        # With PM_HOME pointing at an English/empty directory in os.environ, an explicit Context configured with
        # `lang="zh"` must produce Chinese rollup summaries and unmixed Chinese dependency hints.
        other_env_home = self.base / "other-env-home"
        other_env_home.mkdir()
        (other_env_home / "config.json").write_text(json.dumps({"lang": "en"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"PM_HOME": str(other_env_home)}):
            clk = FakeClock()
            hc = FakeHc({"t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}}}, clock=clk)
            ctx = make_ctx(self.base / "zh-home", pane="hc:t1", hc=hc, clock=clk, config={"lang": "zh"})
            _register_hc_pm(ctx, self.repo, "t1")
            _write_task(ctx, self.repo, "demo-parent", status="in_progress")
            _write_task(ctx, self.repo, "demo-c1", status="in_progress", parent="demo-parent")
            _write_task(ctx, self.repo, "demo-wait", status="proposed")

            Updates(ctx).update(UpdateRequest(id="demo-c1", status="done", keep=True))
            parent_log = [e["text"] for e in ctx.store.task("demo-parent")["log"]]
            self.assertTrue(any("个子任务已结束" in line for line in parent_log), parent_log)

            err_lines: list[str] = []
            Updates(ctx).update(
                UpdateRequest(id="demo-wait", depends_on=["demo-parent"]),
                say=lambda text, err=False: err_lines.append(text) if err else None,
            )
            self.assertTrue(err_lines)
            self.assertNotIn("all deps met", err_lines[0])

    def test_pending_items_deduplicates_rollup_events_and_drops_when_parent_closed_done(self):
        ev1 = {"type": "event", "source": "rollup", "task": "p", "wake": True, "text": "1 child task finished", "at": "2026-11-22 10:00:00"}
        ev2 = {"type": "event", "source": "rollup", "task": "p", "wake": True, "text": "all 2 child tasks finished", "at": "2026-11-22 10:01:00"}
        offsets = [(0, ev1), (100, ev2)]
        # 1) While parent is still open (e.g. blocked), repeated rollup notices collapse to the latest (`earlier=1`).
        _, items = policy.pending_items(offsets, {"hc:t1"}, {"p": {"status": "blocked"}}, 200)
        self.assertEqual([(i["event"]["text"], i["earlier"]) for i in items], [("all 2 child tasks finished", 1)])
        # 2) Once the PM manually closes the parent to `done`, stale `notify` rollup events are dropped.
        _, items_done = policy.pending_items(offsets, {"hc:t1"}, {"p": {"status": "done"}}, 200)
        self.assertEqual(items_done, [])

    def test_unlinking_last_open_child_rolls_up_former_parent(self):
        clk = FakeClock()
        hc = FakeHc({"t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}}}, clock=clk)
        ctx = make_ctx(self.base / "reparent", pane="hc:t1", hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t1")
        _write_task(ctx, self.repo, "demo-p1", status="in_progress")
        _write_task(ctx, self.repo, "demo-c1", status="merged", parent="demo-p1")
        _write_task(ctx, self.repo, "demo-c2", status="in_progress", parent="demo-p1")

        # Unlinking the only open child leaves demo-p1 with all remaining children closed -> should roll up to done.
        Updates(ctx).update(UpdateRequest(id="demo-c2", parent=""))
        self.assertEqual(ctx.store.task("demo-p1")["status"], "done")


if __name__ == "__main__":
    unittest.main()
