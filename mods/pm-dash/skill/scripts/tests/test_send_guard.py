"""Async send calls (`Workers.send_back`, `cmd_send`, `Workers.send_ready_later`) route through `ctx.procs`
and never spawn real background `subprocess.Popen` processes when using `make_ctx` + `FakeProcs`."""
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

from fakes import FakeHc, StubGit, make_ctx  # noqa: E402
from pmlib.commands import review as review_cmd, workers as workers_cmd  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.workers.service import Workers  # noqa: E402


class SendLaterGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = (self.base / "repo").resolve()
        self.repo.mkdir(parents=True)

    def test_send_later_routes_through_ctx_procs_without_real_popen(self):
        slug = project_slug(str(self.repo))
        hc = FakeHc(terminals={
            "t2": {"state": "live", "turn": 3, "status": {"state": "idle"}, "labels": {"task": "t-guard"}},
            "t99": {"state": "live", "labels": {"pm": slug}},
        })
        git = StubGit(
            roots={str(self.repo): str(self.repo)},
            branches={"main", "dev/guard"},
            git_results={
                (str(self.repo), "rev-parse", "--verify", "--quiet", "refs/heads/dev/guard"): "abc1234",
                (str(self.repo), "rev-parse", "--verify", "--quiet", "dev/guard^{commit}"): "abc1234",
                (str(self.repo), "rev-parse", "--verify", "--quiet", "abc1234^{commit}"): "abc1234",
                (str(self.repo), "rev-parse", "--short", "abc1234"): "abc1234",
            },
        )
        ctx = make_ctx(self.base / "home", pane="hc:t99", hc_terminal="t99", hc=hc, git=git)
        ctx.store.change_registration(slug, lambda _: {
            "name": f"pm-{slug}", "project": self.repo.name, "repo": str(self.repo),
            "runtime": "hc", "terminal": "t99", "pane": "hc:t99",
        })
        task = {
            "id": "t-guard", "title": "guard", "project": self.repo.name, "repo": str(self.repo),
            "status": "review", "base": "main", "branch": "dev/guard", "commit": "abc1234",
            "pane": "hc:t2", "dispatched": True, "log": [],
        }
        ctx.store.change_task("t-guard", lambda _: dict(task))

        real_popen = subprocess.Popen

        def no_send_popen(argv, **kw):
            if "_deliver-send" in argv or "_deliver-ready" in argv:
                raise AssertionError(f"real background send Popen must not be called: {argv}")
            return real_popen(argv, **kw)

        with mock.patch.object(subprocess, "Popen", side_effect=no_send_popen):
            Workers(ctx).send_back(task, "hello from send_back")
            workers_cmd.cmd_send(
                argparse.Namespace(
                    target="t-guard", message="hello from cmd_send", file=None, task=None,
                    wait=False, timeout=180, repo=str(self.repo),
                ),
                ctx=ctx,
            )
            review_cmd.cmd_approve(
                argparse.Namespace(
                    id="t-guard", via="worker", keep=False, message=None, timeout=60, note=None,
                    commit=None, revoke=False,
                ),
                ctx=ctx,
            )
            Workers(ctx).send_ready_later("t2", "/tmp/fake.md", kind="claude", task_id="t-guard", repo=str(self.repo))

        send_spawns = [s for s in ctx.procs.spawned if s["args"][:1] == ["_deliver-send"]]
        ready_spawns = [s for s in ctx.procs.spawned if s["args"][:1] == ["_deliver-ready"]]
        self.assertEqual(len(send_spawns), 3, ctx.procs.spawned)
        self.assertEqual(len(ready_spawns), 1, ctx.procs.spawned)
        self.assertEqual(ready_spawns[0]["args"][1], "t2")


if __name__ == "__main__":
    unittest.main()
