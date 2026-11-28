"""Workers on another machine (`dispatch --on`, self-hosted nodes, the deliverer's pull of remote outboxes) stay off
unless config.json sets `{"experimental": {"remote_workers": true}}`. Projects on other machines need no flag."""
from __future__ import annotations

from pathlib import Path
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

from fakes import make_ctx  # noqa: E402
from pmlib import cli  # noqa: E402
from pmlib.errors import Refused  # noqa: E402
from pmlib.reports import RemoteReportSync  # noqa: E402
from pmlib.workers.remote import remote_workers_enabled  # noqa: E402
from pmlib.workers.service import DispatchRequest, Workers  # noqa: E402

ON = {"experimental": {"remote_workers": True}}


class RemoteWorkersFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def _ctx(self, config=None):
        return make_ctx(self.base / "c", config=config)

    def test_flag_reads_only_a_literal_true(self) -> None:
        self.assertFalse(remote_workers_enabled(self._ctx()))
        self.assertFalse(remote_workers_enabled(self._ctx({"experimental": {"remote_workers": "yes"}})))
        self.assertFalse(remote_workers_enabled(self._ctx({"experimental": True})))
        self.assertTrue(remote_workers_enabled(self._ctx(ON)))

    def test_dispatch_on_refused_before_anything_starts_when_off(self) -> None:
        ctx = self._ctx()
        with self.assertRaises(Refused) as cm:
            Workers(ctx).dispatch(DispatchRequest(title="x", repo=str(self.base), branch="dev/x", on="dev"))
        self.assertIn("experimental", str(cm.exception))
        self.assertEqual(list(ctx.home.root.glob("tasks/*.json")), [])

    def test_dispatch_on_dry_run_also_refused_when_off(self) -> None:
        with self.assertRaises(Refused):
            Workers(self._ctx()).dispatch(DispatchRequest(title="x", repo=str(self.base), branch="dev/x",
                                                          on="dev", dry_run=True))

    def test_worker_enroll_refused_when_off(self) -> None:
        ctx = self._ctx()
        with self.assertRaises(SystemExit) as cm:
            cli.main(["worker", "enroll", "--name", "n", "--projects", "p", "--json"], ctx=ctx)
        self.assertIn("experimental", str(cm.exception.code))
        self.assertFalse(Path(ctx.home.tokens, "workers.json").exists())

    def test_deliverer_watcher_skips_remote_outboxes_when_off(self) -> None:
        with mock.patch.object(RemoteReportSync, "remote_tasks", side_effect=AssertionError("pulled while off")):
            self.assertIsNone(RemoteReportSync(self._ctx()).look(str(self.base)))

    def test_deliverer_watcher_looks_when_on(self) -> None:
        with mock.patch.object(RemoteReportSync, "remote_tasks", return_value=[]) as rt:
            self.assertIsNone(RemoteReportSync(self._ctx(ON)).look(str(self.base)))
        rt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
