"""Phase 3b wave 4: `pm.py update | log | remember | helper done` as `report.*` envelopes
(`ReportClient` -> `LocalReportTransport` -> `ReportApplier`, pm-message-routing.md §6, §9.2).

- The same report (one envelope, one idempotency key) applies once, also when the process died after writing
  the task file and before its receipt (the key lives in the target file, C6a), including the update fast paths.
- Two invocations are two reports: each applies.
- A refused report is never silent: synchronously, the command prints why and exits non-zero (no event typed into
  the PM); queued, it is routed as `event.report_rejected` (tests/test_reports.py).
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pmlib.ledger.transition import UpdateRequest  # noqa: E402
from pmlib.messaging.mailbox import MailboxStore  # noqa: E402
from pmlib.reports import (  # noqa: E402
    AppliedReportsStore,
    LocalFacts,
    ReportClient,
    helper_done_report,
    memory_report,
    task_log_report,
    task_update_report,
)
from tests.fakes import FakeClock, FakeHc, make_ctx, run_main  # noqa: E402


class _Crash(RuntimeError):
    pass


def _crash_on_applied(orig):
    """An `AppliedReportsStore.record` that dies on the first `applied` receipt (kill -9 after the target file was
    written, before the receipt was)."""
    state = {"armed": True}

    def record(self, receipt):
        if state["armed"] and receipt.status == "applied":
            state["armed"] = False
            raise _Crash("killed before the receipt")
        return orig(self, receipt)
    return record


class ReportCommandsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self._tmp.name)
        self.repo = self.base / "demo"
        self.repo.mkdir()
        self.clock = FakeClock("2026-11-26 10:00:00")
        self.hc = FakeHc(terminals={
            "t1": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}},
            "t2": {"state": "live", "labels": {"task": "demo-1"}, "status": {"state": "working"}, "turn": 3},
            "t3": {"state": "live", "labels": {"task": "demo-2"}, "status": {"state": "working"}, "turn": 1},
        }, clock=self.clock)
        self.worker = self.ctx("hc:t2")
        self.worker.store.change_registration("demo", lambda _: {
            "name": "pm-demo", "repo": str(self.repo), "pane": "hc:t1", "terminal": "t1", "app_pm": True,
            "started": True,
        })
        for tid, term, extra in (("demo-1", "t2", {}), ("demo-2", "t3", {})):
            self.worker.store.change_task(tid, lambda _, tid=tid, term=term, extra=extra: {
                "id": tid, "title": tid, "project": "demo", "repo": str(self.repo), "status": "in_progress",
                "base": "main", "branch": f"dev/{tid}", "pane": f"hc:{term}", "dispatched": True, "log": [],
                "plan": [{"text": "build", "state": "active"}, {"text": "verify", "state": "todo"}], **extra,
            })

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def ctx(self, pane: str = ""):
        return make_ctx(self.base, pane=pane, hc=self.hc, clock=self.clock)

    def task(self, tid: str = "demo-1") -> dict:
        return self.worker.store.task(tid)

    def assertExitedWith(self, code, err: str, text: str) -> None:
        """`sys.exit(message)`: exit status 1, the message on stderr (run_main hands back the message as the code)."""
        self.assertTrue(code == 1 or isinstance(code, str), code)
        self.assertIn(text, f"{err}{code if isinstance(code, str) else ''}")

    # --- the same report applies once -----------------------------------------------------------------------

    def test_the_same_update_report_twice_applies_once(self) -> None:
        req = UpdateRequest(id="demo-1", status="review", commit="abc1234", note="ready")
        env = task_update_report(self.worker, req)
        self.assertEqual((env.kind, env.sender.role, env.sender.task_id), ("report.task_update", "worker", "demo-1"))
        first = ReportClient(self.worker).submit(env)
        second = ReportClient(self.worker).submit(env)
        self.assertEqual((first.status, second.status, second.already_applied), ("applied", "applied", True))
        self.assertEqual(len(self.task()["log"]), 1)
        self.assertIn(env.idempotency_key, self.task()["applied_reports"])

    def test_two_invocations_are_two_reports(self) -> None:
        for _ in range(2):
            code, _out, _err = run_main(self.worker, "log", "demo-1", "tests pass")
            self.assertEqual(code, 0)
        self.assertEqual([e["text"] for e in self.task()["log"]], ["tests pass", "tests pass"])

    def test_a_log_replayed_after_a_crash_before_its_receipt_is_kept_once(self) -> None:
        env = task_log_report(self.worker, "demo-1", "checkpoint")
        with mock.patch.object(AppliedReportsStore, "record", _crash_on_applied(AppliedReportsStore.record)):
            with self.assertRaises(_Crash):
                ReportClient(self.worker).submit(env)
        self.assertEqual(len(self.task()["log"]), 1)  # the entry was written, its receipt was not
        again = ReportClient(self.worker).submit(env)
        self.assertEqual((again.status, again.already_applied), ("applied", True))
        self.assertEqual(len(self.task()["log"]), 1)

    def test_a_step_done_replayed_after_a_crash_advances_one_step(self) -> None:
        req = UpdateRequest(id="demo-1", step_done=True)
        env = task_update_report(self.worker, req)
        with mock.patch.object(AppliedReportsStore, "record", _crash_on_applied(AppliedReportsStore.record)):
            with self.assertRaises(_Crash):
                ReportClient(self.worker).submit(env, local=LocalFacts(request=req))
        after_crash = [s["state"] for s in self.task()["plan"]]
        self.assertEqual(after_crash[0], "done")
        ReportClient(self.worker).submit(env, local=LocalFacts(request=UpdateRequest(id="demo-1", step_done=True)))
        self.assertEqual([s["state"] for s in self.task()["plan"]], after_crash)  # the second step not checked off

    def test_the_same_memory_report_twice_writes_one_memory_also_after_a_crash(self) -> None:
        def env():
            return memory_report(self.worker, str(self.repo), text="hc get returns the foreground pid as fg_pid",
                                 type="pitfall", name="hc-get-fg-pid", verified="read hc get --json")
        writer = self.worker.caller.memory_writer(str(self.repo))
        self.assertEqual(writer[0], "worker")
        one = env()
        first = ReportClient(self.worker).submit(one, local=LocalFacts(memory_writer=writer))
        second = ReportClient(self.worker).submit(one, local=LocalFacts(memory_writer=writer))
        self.assertEqual((first.result["name"], second.already_applied), ("hc-get-fg-pid", True))
        # Killed after the memory file was written, before its receipt: the replay finds the memory, not a refusal.
        two = memory_report(self.worker, str(self.repo), text="a worker's queued send is typed by one drain",
                            type="pitfall", name="one-drain-types", verified="test_endpoint_typist")
        with mock.patch.object(AppliedReportsStore, "record", _crash_on_applied(AppliedReportsStore.record)):
            with self.assertRaises(_Crash):
                ReportClient(self.worker).submit(two, local=LocalFacts(memory_writer=writer))
        replay = ReportClient(self.worker).submit(two, local=LocalFacts(memory_writer=writer))
        self.assertEqual((replay.status, replay.result["name"], replay.already_applied),
                         ("applied", "one-drain-types", True))
        mem_dir = self.worker.home.project_for(self.repo).memory
        self.assertEqual(sorted(p.stem for p in mem_dir.glob("*.md") if p.name != "MEMORY.md"),
                         ["hc-get-fg-pid", "one-drain-types"])

    def test_the_same_helper_done_report_twice_finishes_the_helper_once(self) -> None:
        result = self.base / "h1.md"
        self.worker.store.change_task("demo-1", lambda cur: {**cur, "helpers": [{
            "name": "h1", "status": "running", "terminal": "t9", "result": str(result), "parent": "t2",
            "mode": "readonly",
        }]})
        env = helper_done_report(self.worker, repo=str(self.repo), name="h1", text="found it")
        self.assertEqual(env.project, "demo")
        first = ReportClient(self.worker).submit(env)
        self.assertTrue(first.result["transitioned"])
        second = ReportClient(self.worker).submit(env)
        self.assertTrue(second.already_applied)
        helpers = self.task()["helpers"]
        self.assertEqual([h["status"] for h in helpers], ["done"])
        self.assertEqual(result.read_text(encoding="utf-8"), "found it\n")

    # --- a refused report is seen --------------------------------------------------------------------------

    def test_a_worker_cannot_update_another_workers_task_and_is_told_on_stderr(self) -> None:
        code, out, err = run_main(self.worker, "update", "demo-2", "--status", "review", "--note", "not mine")
        self.assertExitedWith(code, err, "refused: worker demo-1 cannot modify task demo-2")
        self.assertEqual(self.task("demo-2")["status"], "in_progress")
        self.assertEqual(self.task("demo-2")["log"], [])
        # Synchronous: the worker saw it; nothing is typed into the PM for it.
        pm_box = MailboxStore(self.worker.home.project_for(self.repo).pm_mailbox)
        self.assertEqual([i for i in pm_box.active_items() if i.envelope.kind == "event.report_rejected"], [])
        receipts = AppliedReportsStore(self.worker.home.project_for(self.repo).applied_reports_json,
                                       self.worker.home.project_for(self.repo).applied_reports_lock)
        rows = receipts._read_unlocked()["receipts"]
        self.assertEqual([r["status"] for r in rows.values()], ["rejected"])

    def test_a_business_refusal_prints_and_exits_as_before(self) -> None:
        code, out, err = run_main(self.worker, "update", "demo-1", "--ask", "--note", "which way?")
        self.assertExitedWith(code, err, "--ask goes with --status blocked")

    def test_a_worker_reports_done_only_once_the_pm_approved_its_merge(self) -> None:
        code, _out, err = run_main(self.worker, "update", "demo-1", "--status", "done", "--note", "finished")
        self.assertExitedWith(code, err, "without matching land_approved")
        self.worker.store.change_task("demo-1", lambda cur: {**cur, "land_approved": {
            "by": "hc:t1", "executor": "worker", "commit": "abc1234"}, "landed": {"commit": "abc1234"}})
        code, out, _err = run_main(self.worker, "update", "demo-1", "--status", "done", "--note", "post-merge done")
        self.assertEqual(code, 0, _err)
        self.assertEqual(self.task()["status"], "done")

    def test_an_exec_helper_reports_on_the_merge_it_was_handed_and_a_readonly_one_cannot(self) -> None:
        # Labels as `helper start --exec --for-task` sets them on a PM-owned land helper's terminal.
        self.hc.terminals["t9"] = {"state": "live", "status": {"state": "working"}, "labels": {
            "helper.of": "pm-demo", "helper": "land-demo-1", "helper.project": "demo", "helper.mode": "exec",
            "helper.task": "demo-1"}}
        self.worker.store.change_task("demo-1", lambda cur: {**cur, "land_approved": {
            "by": "hc:t1", "executor": "helper", "helper_name": "land-demo-1", "commit": "abc1234"}})
        helper = self.ctx("hc:t9")
        env = task_update_report(helper, UpdateRequest(id="demo-1", status="blocked", note="conflict"))
        self.assertEqual((env.sender.role, env.sender.helper_mode, env.sender.for_task),
                         ("helper", "exec", "demo-1"))
        code, _out, err = run_main(helper, "update", "demo-1", "--status", "blocked", "--note", "merge conflict")
        self.assertEqual(code, 0, err)
        # Landed with post-merge steps: `land` dropped land_approved; the helper checks steps off and finishes.
        self.worker.store.change_task("demo-1", lambda cur: {
            **{k: v for k, v in cur.items() if k != "land_approved"}, "status": "in_progress",
            "landed": {"commit": "abc1234", "base": "main", "by": "helper"}})
        self.assertEqual(run_main(helper, "update", "demo-1", "--step-done")[0], 0)
        code, _out, err = run_main(helper, "update", "demo-1", "--status", "done", "--note", "deployed")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.task()["status"], "done")
        # No labels (a TUI helper, say): the helper's entry in its owner's record says it is an exec helper.
        self.worker.store.change_registration("demo", lambda cur: {**cur, "helpers": [
            {"name": "land-demo-2", "status": "running", "mode": "exec", "for_task": "demo-2", "terminal": "t10"}]})
        self.hc.terminals["t10"] = {"state": "live", "labels": {
            "helper.of": "pm-demo", "helper": "land-demo-2", "helper.project": "demo"}}
        rec_env = task_log_report(self.ctx("hc:t10"), "demo-2", "x")
        self.assertEqual((rec_env.sender.helper_mode, rec_env.sender.for_task), ("exec", "demo-2"))
        # A read-only helper reports only its own `helper done`.
        self.hc.terminals["t11"] = {"state": "live", "labels": {
            "helper.of": "pm-demo", "helper": "scan", "helper.project": "demo"}}
        code, _out, err = run_main(self.ctx("hc:t11"), "log", "demo-1", "found it")
        self.assertExitedWith(code, err, "helper (readonly) cannot send 'report.task_log'")

    def test_a_session_with_a_task_it_registered_itself_reports_as_the_user(self) -> None:
        own = self.ctx("hc:t4")
        self.hc.terminals["t4"] = {"state": "live", "labels": {"task": "demo-self"}, "status": {"state": "idle"}}
        own.store.change_task("demo-self", lambda _: {
            "id": "demo-self", "title": "mine", "project": "demo", "repo": str(self.repo), "status": "in_progress",
            "base": "main", "pane": "hc:t4", "log": [],
        })
        env = task_update_report(own, UpdateRequest(id="demo-self", status="done", note="did it myself"))
        self.assertEqual(env.sender.role, "user")
        code, _out, err = run_main(own, "update", "demo-self", "--status", "done", "--note", "did it myself")
        self.assertEqual(code, 0, err)
        self.assertEqual(own.store.task("demo-self")["status"], "done")


if __name__ == "__main__":
    unittest.main()
