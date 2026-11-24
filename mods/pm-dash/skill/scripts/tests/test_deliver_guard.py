"""Deliverer spawning (`StallWatcher.stalled`, `cmd_event`, `Delivery.ensure_running`) routes through `ctx.procs`
and never spawns real `pm.py deliver` processes when using `make_ctx` + `FakeProcs`."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
for p in (SCRIPTS, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fakes import FakeHc, make_ctx  # noqa: E402
from pmlib.commands import events as events_cmd  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.home import project_slug  # noqa: E402


class DeliverLaterGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = (self.base / "repo").resolve()
        self.repo.mkdir(parents=True)

    def test_deliver_later_routes_through_ctx_procs(self):
        slug = project_slug(str(self.repo))
        hc = FakeHc(terminals={"t99": {"state": "live", "labels": {"pm": f"pm-{slug}"}}})
        ctx = make_ctx(self.base / "home", hc=hc)
        ctx.store.change_registration(slug, lambda _: {
            "name": f"pm-{slug}", "project": self.repo.name, "repo": str(self.repo),
            "runtime": "hc", "terminal": "t99", "pane": "hc:t99",
        })

        real_popen = subprocess.Popen

        def no_deliver_popen(argv, **kw):
            if "deliver" in argv:
                raise AssertionError(f"real deliver Popen must not be called: {argv}")
            return real_popen(argv, **kw)

        with mock.patch.object(subprocess, "Popen", side_effect=no_deliver_popen):
            StallWatcher(ctx).stalled(
                {"id": "t-1", "repo": str(self.repo), "title": "demo", "status": "in_progress", "pane": "hc:t2"},
                "worker stopped", key="t2:stop:1",
            )
            events_cmd.cmd_event(
                argparse.Namespace(repo=str(self.repo), source="ci", text="build green", key=None),
                ctx=ctx,
            )
            Delivery(ctx, self.repo).ensure_running()

        deliver_spawns = [s for s in ctx.procs.spawned if s["args"] == ["deliver", str(self.repo)]]
        self.assertEqual(len(deliver_spawns), 3, ctx.procs.spawned)
        self.assertEqual(Path(deliver_spawns[-1]["cwd"]), ctx.home.root)

        # Also verify real Processes.spawn_pm builds the exact launcher argv and cwd without spawning a child.
        from pmlib import procs as procs_mod
        spawned_real = []

        def capture_deliver_popen(argv, **kw):
            spawned_real.append((argv, kw))
            return mock.MagicMock()

        real_procs = procs_mod.Processes(ctx.home, env={"PM_HOME": str(ctx.home.root)})
        with mock.patch.object(subprocess, "Popen", side_effect=capture_deliver_popen):
            real_procs.spawn_pm(["deliver", str(self.repo)], env=real_procs.clean_session_env(), cwd=ctx.home.root)
        (argv, kw), = spawned_real
        self.assertEqual(argv, [sys.executable, str(procs_mod.launcher()), "deliver", str(self.repo)])
        self.assertEqual(Path(kw["cwd"]), ctx.home.root)


if __name__ == "__main__":
    unittest.main()
