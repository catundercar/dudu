"""Context-based unit tests for Stage 4c: Deliverer, Delivery, StallWatcher, DependencyWatcher, InboxWatcher, Notifier."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SCRIPTS / "tests") not in sys.path:
    sys.path.insert(0, str(SCRIPTS / "tests"))

from fakes import FakeChangeWaiter, FakeClock, FakeHc, FakeProcs, FakeTui, StubGit, make_ctx  # noqa: E402
from pmlib.context import DeliverWatcher  # noqa: E402
from pmlib.errors import NotFound, Refused  # noqa: E402
from pmlib.events.deliver import Delivery, DeliveryReceipt  # noqa: E402
from pmlib.events.deliverer import Deliverer  # noqa: E402
from pmlib.events.deps_watch import DependencyWatcher  # noqa: E402
from pmlib.events.inbox import InboxWatcher, WatchResult  # noqa: E402
from pmlib.events.notify import Notifier  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402


def _register_hc_pm(ctx, repo: str, terminal: str = "t7") -> dict:
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


def _write_task(ctx, task: dict) -> dict:
    ctx.home.tasks.mkdir(parents=True, exist_ok=True)
    ctx.home.task(task["id"]).write_text(json.dumps(task))
    return task


class DelivererServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def test_injected_watchers_and_holds_are_instance_scoped(self):
        clk = FakeClock()
        hc = FakeHc(terminals={"t7": {"state": "live", "status": {"state": "idle"}}}, clock=clk)
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        Conversation(ctx, self.repo).record("event", by="ci", text="build broke", source="external:ci", wake=True)

        calls = []
        w1 = DeliverWatcher(
            name="custom-1",
            terminals=lambda r: {"t-h1"},
            look=lambda r, s, b: (calls.append(("w1", r)), 12.0)[1],
        )
        w2 = DeliverWatcher(
            name="custom-2",
            terminals=lambda r: {"t-h2"},
            look=lambda r, s, b: (calls.append(("w2", r)), 2.0)[1],
        )
        held = [True]
        d_held = Deliverer(ctx, self.repo, watchers=(w1, w2), holds=(lambda r: held[0],), settle=0)
        d_open = Deliverer(ctx, self.repo, watchers=(), holds=(), settle=0)

        # Instance-scoped: d_held is held back and watches t-h1/t-h2, while d_open is not.
        self.assertTrue(d_held.is_held_back())
        self.assertFalse(d_open.is_held_back())
        self.assertEqual(d_held.watched_terminals(), {"t-h1", "t-h2"})
        self.assertEqual(d_open.watched_terminals(), set())

        changes = FakeChangeWaiter()
        due = d_held.look(changes, {}, {})
        self.assertEqual(changes.terminals, {"t7", "t-h1", "t-h2"})
        self.assertEqual(calls, [("w1", self.repo), ("w2", self.repo)])
        self.assertEqual(due, 2.0)
        # Held back: nothing sent yet, cursor stays at 0.
        self.assertEqual(hc.sent, [])
        self.assertEqual(d_held.delivered_offset(), 0)

        # Release hold: now batch is sent and outbound cursor advances without marking received.
        held[0] = False
        due2 = d_held.look(changes, {}, {})
        self.assertEqual(due2, 0)
        self.assertEqual(len(hc.sent), 1)
        self.assertEqual(hc.sent[0][0], "t7")
        self.assertIn("build broke", hc.sent[0][1])
        end = ctx.home.project_for(self.repo).conversation.stat().st_size
        self.assertEqual(d_held.delivered_offset(), end)
        self.assertEqual(d_held.received_ranges(), [])

    def test_took_delivery_and_bring_pending_return_values_without_printing(self):
        clk = FakeClock()
        ctx = make_ctx(self.tmp.name, clock=clk)
        _register_hc_pm(ctx, self.repo, "t7")
        Conversation(ctx, self.repo).record("event", by="ci", text="first event", source="external:ci", wake=True)

        d = Delivery(ctx, self.repo, settle=0)
        s1, e1, items1 = d.pending_batch()
        batch1 = d.batch_text(s1, e1, items1)
        d.advance_delivered(e1)

        # First receipt: no repeat warning, nothing written to ctx.out.
        r1 = d.took_delivery(batch1)
        self.assertIsInstance(r1, DeliveryReceipt)
        self.assertFalse(r1.repeated)
        self.assertIsNone(r1.warning)
        self.assertEqual((r1.start, r1.end), (s1, e1))
        self.assertEqual(ctx.out.stdout, "")
        self.assertEqual(d.received_ranges(), [[s1, e1]])

        # Second receipt of exact same batch: returns warning string, still zero output written.
        r2 = d.took_delivery(batch1)
        self.assertTrue(r2.repeated)
        self.assertIn("repeat", r2.warning or "")
        self.assertEqual(ctx.out.stdout, "")

        # New event rides with bring_pending and returns formatted text directly.
        Conversation(ctx, self.repo).record("event", by="ci", text="second event", source="external:ci", wake=True)
        brought = d.bring_pending()
        self.assertIsNotNone(brought)
        self.assertIn("second event", brought or "")
        self.assertEqual(ctx.out.stdout, "")
        # Calling bring_pending again returns None.
        self.assertIsNone(d.bring_pending())

    def test_ensure_running_spawns_deliver_via_procs_port(self):
        ctx = make_ctx(
            self.tmp.name,
            env={"PM_HOME": str(Path(self.tmp.name) / "ledger"), "HC_TERMINAL_ID": "t9", "CLAUDECODE": "1", "KEEP": "yes"},
        )
        _register_hc_pm(ctx, self.repo, "t7")
        Delivery(ctx, self.repo).ensure_running()
        self.assertEqual(len(ctx.procs.spawned), 1)
        spawn = ctx.procs.spawned[0]
        self.assertEqual(spawn["args"], ["deliver", self.repo])
        self.assertEqual(spawn["cwd"], str(ctx.home.root))
        self.assertNotIn("HC_TERMINAL_ID", spawn["env"])
        self.assertNotIn("CLAUDECODE", spawn["env"])
        self.assertEqual(spawn["env"].get("KEEP"), "yes")

    def test_deliverer_run_catches_pm_error_and_recovers(self):
        clk = FakeClock(mono=10.0)
        hc = FakeHc(clock=clk)
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        ctx.home.root.mkdir(parents=True, exist_ok=True)
        marks = iter(["v1", "v1", "v1", "v2", "v2"])
        attempts = [0]

        class _FlakyDeliverer(Deliverer):
            def look(self, changes, stops, bases=None):
                attempts[0] += 1
                if attempts[0] == 1:
                    raise NotFound("task vanished mid-look")
                return 0

        d = _FlakyDeliverer(ctx, self.repo, gap=0, pause=0, gone=0, script_mark_fn=lambda: next(marks, "v2"))
        self.assertTrue(d.run())
        self.assertEqual(attempts[0], 2)


class StallAndDepsWatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def test_worker_stopped_returns_claude_block_payload_without_printing(self):
        ctx = make_ctx(
            self.tmp.name,
            pane="hc:t20",
            hc_terminal="t20",
            env={"CLAUDE_CODE_SESSION_ID": "sess-1"},
        )
        _register_hc_pm(ctx, self.repo, "t7")
        _write_task(ctx, {
            "id": "demo-fix",
            "title": "fix",
            "repo": self.repo,
            "project": "demo",
            "status": "in_progress",
            "pane": "hc:t20",
            "dispatched": True,
        })
        payload = StallWatcher(ctx).worker_stopped({"stop_hook_active": False})
        self.assertIsNotNone(payload)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("demo-fix", payload["reason"])
        self.assertEqual(ctx.out.stdout, "")

    def test_sweep_exited_records_stall_and_spawns_deliverer(self):
        procs = FakeProcs(make_ctx(self.tmp.name).home)
        hc = FakeHc(terminals={"t20": {"state": "exited"}})
        ctx = make_ctx(self.tmp.name, hc=hc, procs=procs)
        _register_hc_pm(ctx, self.repo, "t7")
        _write_task(ctx, {
            "id": "demo-w1",
            "title": "w1",
            "repo": self.repo,
            "project": "demo",
            "status": "in_progress",
            "pane": "hc:t20",
            "dispatched": True,
        })
        StallWatcher(ctx).sweep_exited(self.repo)
        events = Conversation(ctx, self.repo).events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "stall")
        self.assertEqual(events[0]["key"], "t20:gone")
        self.assertEqual(len(procs.spawned), 1)
        # Idempotent on repeated sweep with same key.
        StallWatcher(ctx).sweep_exited(self.repo)
        self.assertEqual(len(Conversation(ctx, self.repo).events()), 1)

    def test_dependency_watcher_reconciles_and_wakes_pm(self):
        procs = FakeProcs(make_ctx(self.tmp.name).home)
        ctx = make_ctx(self.tmp.name, procs=procs)
        _register_hc_pm(ctx, self.repo, "t7")
        _write_task(ctx, {
            "id": "demo-a",
            "title": "A",
            "repo": self.repo,
            "project": "demo",
            "status": "merged",
        })
        _write_task(ctx, {
            "id": "demo-b",
            "title": "B",
            "repo": self.repo,
            "project": "demo",
            "status": "proposed",
            "depends_on": ["demo-a"],
        })
        emitted = DependencyWatcher(ctx).reconcile(self.repo)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0]["id"], "demo-b")
        events = Conversation(ctx, self.repo).events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source"], "deps")
        self.assertTrue(events[0]["wake"])
        self.assertEqual(len(procs.spawned), 1)
        # Second reconcile is idempotent.
        self.assertEqual(DependencyWatcher(ctx).reconcile(self.repo), [])


class InboxAndNotifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo_path = Path(self.tmp.name) / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())

    def test_inbox_watcher_tui_server_down_matches_tui_host(self):
        tui_down = FakeTui(server_ok=False)
        ctx = make_ctx(self.tmp.name, tui=tui_down)
        watcher = InboxWatcher(ctx)
        self.assertFalse(watcher.pane_busy("p1"))
        self.assertIsNone(watcher.watched_agents({"name": "pm-demo", "pane": "p0", "workspace": "w1", "repo": self.repo}))

    def test_inbox_watcher_watch_returns_result_and_commits_offset(self):
        clk = FakeClock(mono=10.0)
        hc = FakeHc(clock=clk)
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        watcher = InboxWatcher(ctx)
        watcher.append_inbox("pm-demo", "worker", "hello from worker")
        rec = {"name": "pm-demo", "pane": "hc:t7", "terminal": "t7", "repo": self.repo}
        res = watcher.watch(rec, timeout=5, interval=1)
        self.assertIsInstance(res, WatchResult)
        self.assertEqual(res.kind, "inbox")
        self.assertIn("hello from worker", res.text)
        self.assertEqual(ctx.out.stdout, "")
        # Offset is not updated until commit() is called.
        offset_file = ctx.home.inbox_offset("pm-demo")
        self.assertEqual(offset_file.read_text(), "0")
        res.commit()
        self.assertGreater(int(offset_file.read_text()), 0)

    @unittest.skipIf(os.name == "nt", "POSIX parents")
    def test_inbox_watcher_raises_refused_when_starter_gone(self):
        clk = FakeClock(mono=10.0)
        hc = FakeHc(clock=clk)
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        watcher = InboxWatcher(ctx)
        watcher.append_inbox("pm-demo", "worker", "keep unread")
        rec = {"name": "pm-demo", "pane": "hc:t7", "terminal": "t7", "repo": self.repo}
        with mock.patch.object(os, "getppid", side_effect=[100, 1, 1]):
            with self.assertRaises(Refused) as exc:
                watcher.watch(rec, timeout=5, interval=1)
        self.assertIn("what started it has gone", str(exc.exception))

    def test_notifier_resolves_project_and_workspace_with_fake_tui(self):
        tui = FakeTui(
            agents=[{"name": "pm-demo", "pane_id": "p1", "workspace_id": "w1"}],
            panes=[{"pane_id": "p1", "workspace_id": "w1", "agent": True}],
        )
        ctx = make_ctx(self.tmp.name, pane="p2", workspace="w1", tui=tui, git=StubGit(roots={self.repo: self.repo}))
        rec = _register_hc_pm(ctx, self.repo, "t7")
        pm_agent, found_rec, how = Notifier(ctx).target(self.repo)
        self.assertEqual(found_rec["name"], rec["name"])
        self.assertEqual(how, "project")

    @unittest.skipIf(os.name == "nt", "POSIX flock handover subprocess test")
    def test_new_to_old_subprocess_handover_releases_lock_and_preserves_cursor_and_stall_entries(self):
        import shutil
        import subprocess
        import time

        base = Path(self.tmp.name)
        pm_home = base / "pm_home"
        pm_home.mkdir()
        skill_copy = base / "installed_skill"
        shutil.copytree(
            SCRIPTS.parent,
            skill_copy,
            ignore=shutil.ignore_patterns("test_*.py", "tests", "__pycache__", ".DS_Store"),
        )
        hc_state_file = base / "hc_state.json"
        hc_state_file.write_text(json.dumps({
            "state": "live", "id": "t7", "address": "t7",
            "labels": {"pm": Path(self.repo).name},
            "status": {"state": "working", "msg": "busy"},
        }), encoding="utf-8")
        stop_events = base / "stop_events"
        fake_hc = base / "fake_hc.py"
        fake_hc.write_text(
            f"#!{sys.executable}\n"
            "import json, pathlib, sys, time\n"
            "args = [a for a in sys.argv[1:] if a != '--json']\n"
            "cmd = args[0] if args else ''\n"
            "if cmd == 'get':\n"
            f"    print(pathlib.Path({str(hc_state_file)!r}).read_text(encoding='utf-8'))\n"
            "elif cmd == 'ls':\n"
            "    print('[]')\n"
            "elif cmd == 'events':\n"
            "    print(json.dumps({'terminals': []}), flush=True)\n"
            f"    stop = pathlib.Path({str(stop_events)!r})\n"
            "    while not stop.exists():\n"
            "        time.sleep(0.05)\n"
            "else:\n"
            "    print(json.dumps({'started': True}))\n",
            encoding="utf-8",
        )
        fake_hc.chmod(0o755)
        (pm_home / "config.json").write_text(json.dumps({
            "hc": str(fake_hc),
            "deliver_warn_seconds": 0.01,
        }), encoding="utf-8")
        slug = project_slug(self.repo)
        (pm_home / "pms").mkdir(parents=True, exist_ok=True)
        (pm_home / "pms" / f"{slug}.json").write_text(json.dumps({
            "name": f"pm-{slug}",
            "project": Path(self.repo).name,
            "repo": self.repo,
            "runtime": "hc",
            "terminal": "t7",
            "pane": "hc:t7",
            "agent": "claude",
        }), encoding="utf-8")
        proj_dir = pm_home / "projects" / slug
        proj_dir.mkdir(parents=True, exist_ok=True)
        import datetime
        soon_at = (datetime.datetime.now() + datetime.timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
        conv_file = proj_dir / "conversation.jsonl"
        conv_file.write_text(
            json.dumps({
                "at": "2026-11-23 10:00:00", "type": "event", "by": "hc:t7",
                "source": "deliver-stall", "wake": False, "text": "prior 7c deliver-stall entry",
            }) + "\n"
            + json.dumps({
                "at": soon_at, "type": "event", "by": "hc:t7",
                "source": "deliver-stall", "wake": False, "text": "stall-for-old-to-skip",
            }) + "\n"
            + json.dumps({
                "at": soon_at, "type": "event", "by": "ci",
                "source": "external:ci", "wake": True, "text": "alert-after-downgrade",
            }) + "\n",
            encoding="utf-8",
        )

        env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_", "CLAUDE"))}
        env["PM_HOME"] = str(pm_home)
        handover_out = base / "old_deliverer_result.json"

        proc = subprocess.Popen(
            [sys.executable, str(skill_copy / "scripts" / "pm.py"), "deliver", self.repo],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        try:
            # 1. Wait until NEW deliverer acquires deliver.lock and advances delivered.json past line 1 (leaving unsettled tail).
            delivered_file = proj_dir / "delivered.json"
            deadline = time.monotonic() + 10.0
            ready = False
            while time.monotonic() < deadline:
                if delivered_file.exists():
                    state = json.loads(delivered_file.read_text(encoding="utf-8"))
                    if int(state.get("offset") or 0) > 0:
                        ready = True
                        break
                time.sleep(0.05)
            self.assertTrue(ready, "new deliverer did not advance delivered.json before handover")

            # 2. Downgrade installed_skill/scripts in place to a standalone pre-pmlib single-file pm.py!
            #    Because unsettled lines remain after `offset`, NEW deliverer wakes every SETTLE (2s) automatically,
            #    observes the new code_mark on two consecutive looks, releases deliver.lock, and spawns old pm.py.
            shutil.rmtree(skill_copy / "scripts")
            (skill_copy / "scripts").mkdir(parents=True)
            old_pm_py = skill_copy / "scripts" / "pm.py"
            old_pm_py.write_text(
                f"#!{sys.executable}\n"
                "import fcntl, json, os, pathlib, sys\n"
                "if len(sys.argv) >= 3 and sys.argv[1] == 'deliver':\n"
                "    repo = sys.argv[2]\n"
                f"    proj = pathlib.Path({str(proj_dir)!r})\n"
                "    lock_fh = open(proj / 'deliver.lock', 'a+')\n"
                "    try:\n"
                "        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                "        lock_ok = True\n"
                "    except OSError:\n"
                "        lock_ok = False\n"
                "    state = json.loads((proj / 'delivered.json').read_text(encoding='utf-8'))\n"
                "    raw = (proj / 'conversation.jsonl').read_bytes()[int(state.get('offset') or 0):]\n"
                "    events = [json.loads(l) for l in raw.decode('utf-8').splitlines() if l.strip()]\n"
                "    news = [e['text'] for e in events if e.get('wake') is not False]\n"
                f"    pathlib.Path({str(handover_out)!r}).write_text(\n"
                "        json.dumps({'lock_ok': lock_ok, 'news': news, 'events_seen': len(events)}),\n"
                "        encoding='utf-8',\n"
                "    )\n"
                "    if lock_ok:\n"
                "        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)\n"
                "    lock_fh.close()\n",
                encoding="utf-8",
            )
            old_pm_py.chmod(0o755)

            rc = proc.wait(timeout=15)
            stderr_out = proc.stderr.read() if proc.stderr else ""
            self.assertEqual(rc, 0, stderr_out)

            # 3. Wait for the spawned old single-file pm.py deliver to finish and verify lock + schema compatibility.
            deadline = time.monotonic() + 10.0
            while not handover_out.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(handover_out.exists(), "old pm.py deliver was not spawned after handover")
            result = json.loads(handover_out.read_text(encoding="utf-8"))
            self.assertTrue(result["lock_ok"], "deliver.lock was still held when old pm.py started")
            self.assertEqual(result["news"], ["alert-after-downgrade"])
            self.assertEqual(result["events_seen"], 2)  # saw stall-for-old-to-skip (wake=False) + alert-after-downgrade
        finally:
            stop_events.write_text("1", encoding="utf-8")
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            if proc.stderr:
                proc.stderr.close()

    def test_cli_deliver_context_from_env_hold_does_not_raise_type_error(self):
        import pmlib.cli  # noqa: F401 - populates sys.modules["pmlib.manager.seat"] as real CLI startup does
        from pmlib.context import Context

        ctx = Context.from_env(home_option=Path(self.tmp.name) / "p0-home")
        self.assertEqual(Deliverer(ctx, self.repo).is_held_back(), False)

    def test_context_from_env_without_cli_import_wires_deliver_holds_watchers_and_seat_alive(self):
        import subprocess

        code = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            "from pmlib.context import Context\n"
            "from pmlib.events.deliverer import Deliverer\n"
            "assert 'pmlib.cli' not in sys.modules\n"
            f"ctx = Context.from_env(home_option={str(Path(self.tmp.name) / 'isolated')!r})\n"
            f"d = Deliverer(ctx, {self.repo!r})\n"
            "print(json.dumps({\n"
            "    'seat_alive': ctx.seat_alive is not None,\n"
            "    'holds': len(d._holds),\n"
            "    'watchers': len(d._watchers),\n"
            "}))\n"
        )
        res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10, check=True)
        wired = json.loads(res.stdout)
        self.assertEqual(wired, {"seat_alive": True, "holds": 1, "watchers": 4})


if __name__ == "__main__":
    unittest.main()
