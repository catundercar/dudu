"""Tests for Layer 3 `pmlib.reports` (`ReportApplier`, `ReportClient`, C6a locked idempotency, §6.3/§6.4)."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pmlib.messaging.address import LogicalAddress
from pmlib.messaging.envelope import P0_CONTROL, Envelope, new_env_id
from pmlib.messaging.mailbox import MailboxStore
from pmlib.messaging.principal import Principal
from pmlib.reports import ReportClient
from tests.fakes import FakeClock, FakeHc, make_ctx


class _CrashAfterTaskWrite(RuntimeError):
    pass


class TestReportsAndC6a(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_dir = pathlib.Path(self._tmp.name) / "repo"
        self.repo_dir.mkdir(parents=True)
        self.clock = FakeClock()
        self.hc = FakeHc(terminals={
            "t1": {"address": "t1", "state": "live", "agent": "claude", "status": {"state": "idle"}},
            "t2": {"address": "t2", "state": "live", "agent": "codex", "status": {"state": "working"}},
        })
        self.ctx = make_ctx(self._tmp.name, pane="hc:t1", clock=self.clock, hc=self.hc)
        self.home = self.ctx.home
        self.store = self.ctx.store
        self.store.change_registration("demo", lambda _: {
            "name": "pm-demo",
            "repo": str(self.repo_dir),
            "pane": "hc:t1",
            "app_pm": True,
            "started": True,
            "endpoint": {"runtime": "hc", "machine": None, "terminal": "t1", "epoch": 1},
        })
        self.store.change_task("demo-1", lambda _: {
            "id": "demo-1",
            "title": "Sample task",
            "repo": str(self.repo_dir),
            "branch": "dev/sample",
            "base": "main",
            "status": "in_progress",
            "log": [],
            "endpoint": {"runtime": "hc", "machine": None, "terminal": "t2", "epoch": 2},
        })

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _report_env(
        self,
        *,
        kind: str = "report.task_update",
        sender: Principal | None = None,
        body: dict | None = None,
        idem_key: str = "idem-report-1",
    ) -> Envelope:
        return Envelope(
            env_id=new_env_id(),
            idempotency_key=idem_key,
            schema_version=1,
            created_ms=1_700_000_000_000,
            kind=kind,
            sender=sender or Principal.worker("demo", "demo-1", epoch=2),
            recipient=LogicalAddress.ledger("demo"),
            project="demo",
            cause={"kind": "worker_report"},
            priority=P0_CONTROL,
            body=body or {"task_id": "demo-1", "repo": str(self.repo_dir), "status": "review", "note": "ready for review"},
        )

    def test_c6a_crash_after_atomic_task_write_replays_cleanly_without_duplicate_log(self) -> None:
        client = ReportClient(self.ctx)
        env = self._report_env(idem_key="idem-c6a-1")

        def _crash(_tr) -> None:
            raise _CrashAfterTaskWrite("simulated kill -9 right after write_atomic")

        with self.assertRaises(_CrashAfterTaskWrite):
            client.submit(env, on_after_task_write=_crash)

        saved_mid = self.store.task("demo-1")
        self.assertIsNotNone(saved_mid)
        self.assertEqual(saved_mid["status"], "review")
        self.assertIn("idem-c6a-1", saved_mid.get("applied_reports") or {})
        log_len_mid = len(saved_mid.get("log") or [])
        self.assertEqual(log_len_mid, 1)

        replay = client.submit(env)
        self.assertEqual(replay.status, "applied")
        self.assertTrue(replay.already_applied)
        saved_after = self.store.task("demo-1")
        self.assertEqual(len(saved_after.get("log") or []), log_len_mid)

        fast = client.submit(env)
        self.assertEqual(fast.status, "applied")
        self.assertTrue(fast.already_applied)

    def test_task_log_idempotency(self) -> None:
        client = ReportClient(self.ctx)
        log_env = self._report_env(
            kind="report.task_log",
            idem_key="idem-log-1",
            body={"task_id": "demo-1", "repo": str(self.repo_dir), "text": "progress checkpoint"},
        )
        first = client.submit(log_env)
        self.assertEqual(first.status, "applied")
        self.assertFalse(first.already_applied)
        self.assertEqual(len(self.store.task("demo-1").get("log") or []), 1)

        second = client.submit(log_env)
        self.assertEqual(second.status, "applied")
        self.assertTrue(second.already_applied)
        self.assertEqual(len(self.store.task("demo-1").get("log") or []), 1)

    def test_stale_worker_epoch_downgraded_to_late_report_without_mutating_task(self) -> None:
        client = ReportClient(self.ctx)
        stale_env = self._report_env(
            sender=Principal.worker("demo", "demo-1", epoch=1),
            idem_key="idem-stale-1",
            body={"task_id": "demo-1", "repo": str(self.repo_dir), "status": "blocked", "note": "old worker"},
        )
        rec = client.submit(stale_env)
        self.assertEqual(rec.status, "applied")
        self.assertTrue(rec.late_report)
        self.assertEqual(self.store.task("demo-1")["status"], "in_progress")

        self.assertFalse(self.home.project_for(self.repo_dir).pm_mailbox.exists())
        mb = MailboxStore(self.home.project("demo").pm_mailbox)
        late_items = [it for it in mb.active_items() if it.envelope.kind == "event.late_report"]
        self.assertEqual(len(late_items), 1)
        self.assertEqual(late_items[0].envelope.body.get("sender_epoch"), 1)

    def test_authz_rejection_emits_report_rejected(self) -> None:
        # A queued report (nobody waiting on its answer, §6.4.2): the refusal is routed as an event.
        client = ReportClient(self.ctx)
        bad_env = self._report_env(
            sender=Principal.worker("demo", "demo-1", epoch=2),
            idem_key="idem-bad-1",
            body={"task_id": "demo-1", "repo": str(self.repo_dir), "status": "merged", "note": "unapproved merge"},
        )
        rec = client.apply_queued(bad_env)
        self.assertEqual(rec.status, "rejected")
        self.assertEqual(self.store.task("demo-1")["status"], "in_progress")

        self.assertFalse(self.home.project_for(self.repo_dir).pm_mailbox.exists())
        mb = MailboxStore(self.home.project("demo").pm_mailbox)
        rej_items = [it for it in mb.active_items() if it.envelope.kind == "event.report_rejected"]
        self.assertEqual(len(rej_items), 1)
        self.assertEqual(rej_items[0].envelope.body.get("task_id"), "demo-1")


if __name__ == "__main__":
    unittest.main()
