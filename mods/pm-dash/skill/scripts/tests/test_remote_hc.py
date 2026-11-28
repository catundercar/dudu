"""Phase 6a (`pm-message-routing.md` §5.2, §6.1, §6.3, §7.2, §9.3, §11.3, §11.4; `pm-stuck-root-fix.md` §4.7): a worker
on another machine's herdr-core terminal (`dev/t7`) with the PM and the ledger here.

Everything runs against `SimHc` (tests/sim_hc.py): a stand-in for `hc` whose "machines" are temp folders, where
`hc exec --on dev` runs git for real against isolated local repositories. No SSH, no `hc machine add`, no real
terminal anywhere.
"""
from __future__ import annotations

import json
from pathlib import Path
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

from fakes import FakeClock, make_ctx  # noqa: E402
from sim_hc import SimHc  # noqa: E402
from pmlib.errors import Refused  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.landing import ApproveRequest, Landing  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.task import reconcile_task_endpoint  # noqa: E402
from pmlib.ledger.transition import UpdateRequest  # noqa: E402
from pmlib.messaging.address import Endpoint, LogicalAddress  # noqa: E402
from pmlib.messaging.envelope import P3_DIRECT, P4_BATCH, Envelope, new_env_id  # noqa: E402
from pmlib.messaging.mailbox import MailboxItem, MailboxStore  # noqa: E402
from pmlib.messaging.outbox import (  # noqa: E402
    TaskTokens,
    WorkerOutbox,
    WorkerState,
    parse_outbox_text,
    sign_envelope,
    verify_envelope,
    write_worker_state_files,
)
from pmlib.messaging.principal import Principal  # noqa: E402
from pmlib.messaging.transports.remote_hc import RemoteHcTransport  # noqa: E402
from pmlib.messaging.typist import drain_endpoint, endpoint_mailbox, enqueue_for_endpoint  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.turn_state import EndpointTurnStore  # noqa: E402
from pmlib.reports import (  # noqa: E402
    RemoteReportSync,
    ReportClient,
    task_log_report,
    task_update_report,
)
from pmlib.terminals.hc import HcHost  # noqa: E402
from pmlib.workers.remote import (  # noqa: E402
    RemoteWorkspace,
    machine_profile,
    next_remote_epoch,
    record_remote_worker,
    refresh_remote_context,
    worker_context,
)

EP = Endpoint(runtime="hc", machine="dev", terminal="t7", workspace="/w")


def _item(text: str = "hello", kind: str = "cmd.send") -> MailboxItem:
    env = Envelope(env_id=new_env_id(1_700_000_000_000), idempotency_key="", schema_version=1,
                   created_ms=1_700_000_000_000, kind=kind, sender=Principal.supervisor("demo"),
                   recipient=LogicalAddress.worker("demo-w1", project="demo"), project="demo",
                   cause={"kind": "test"}, priority=P3_DIRECT, body={"text": text})
    return MailboxItem(seq=1, envelope=env, state="accepted", attempts=0, accepted_ms=1, updated_ms=1)


def _git(cwd: Path | str, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
           "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.clk = FakeClock("2026-11-27 10:00:00")
        self.sim = SimHc(self.base, clock=self.clk)
        self.dev_home = self.sim.add_machine("dev")
        self.sim.add_term("dev/t7", status="working")


class RemoteTransportI4Tests(_Base):
    """§5.2: every flavour of a lost line is a partition (`unknown`), never `gone`, `stalled` or `exited`."""

    def _tr(self, **cfg) -> RemoteHcTransport:
        ctx = make_ctx(self.base / "c", hc=HcHost(runner=self.sim, clock=self.clk), clock=self.clk, config=cfg or None)
        return RemoteHcTransport(ctx, machine_ttl_s=0)

    def test_every_disconnected_machine_state_is_a_partition(self) -> None:
        tr = self._tr()
        for state, link in (("connecting", "connecting"), ("needs_login", "unauthorized"),
                            ("unreachable", "disconnected")):
            with self.subTest(state=state):
                self.sim.set_machine("dev", state)
                out = tr.deliver(EP, _item())
                self.assertEqual(out.status, "partitioned")
                batch = tr.observe(EP, {"outbox_seq": 2})
                self.assertEqual(batch.link_state, link)
                self.assertEqual([o["kind"] for o in batch.observations], ["link_state"])
                self.assertEqual(batch.observations[0]["health"], "unknown")
                self.assertEqual(batch.observations[0]["unknown_reason"], "machine_disconnected")
                self.assertEqual(batch.next_cursors, {"outbox_seq": 2})
                self.assertEqual(tr.interrupt(EP).status, "partitioned")
                self.assertEqual(tr.presence(EP), "unknown")
        # `hc get` kept answering the cached "live, working" state the whole time: never trusted while down.
        self.assertEqual(self.sim.typed_to("dev/t7"), [])

    def test_unknown_machine_and_a_silent_core_are_partitions_too(self) -> None:
        tr = self._tr()
        ep = Endpoint(runtime="hc", machine="nowhere", terminal="t7")
        self.assertEqual(tr.deliver(ep, _item()).status, "partitioned")
        self.assertEqual(tr.observe(ep, {}).link_state, "disconnected")
        tr.ctx.hc._runner = lambda *a, **k: None  # the local core does not answer at all
        tr.forget_machine_state()
        self.assertEqual(tr.deliver(EP, _item()).status, "partitioned")
        self.assertEqual(tr.presence(EP), "unknown")

    def test_unavailable_mid_call_outranks_a_cached_connected_line(self) -> None:
        tr = RemoteHcTransport(self._tr().ctx, machine_ttl_s=60)
        self.sim.terms["dev/t7"]["status"] = "idle"
        self.assertEqual(tr.link_state(EP), "connected")  # cached for 60 s
        self.sim.machines["dev"]["state"] = "unreachable"  # drops without a new `machine ls`
        self.assertEqual(tr.deliver(EP, _item()).status, "partitioned")
        self.assertEqual(tr.link_state(EP), "disconnected")
        self.assertEqual(tr.observe(EP, {}).link_state, "disconnected")

    def test_a_lost_terminal_is_unknown_and_only_a_connected_not_found_is_gone(self) -> None:
        tr = self._tr()
        self.sim.terms["dev/t7"]["state"] = "lost"
        self.assertEqual(tr.deliver(EP, _item()).status, "partitioned")
        self.assertEqual(tr.presence(EP), "unknown")
        self.sim.terms.pop("dev/t7")
        self.assertEqual(tr.deliver(EP, _item()).status, "endpoint_gone")
        self.assertEqual(tr.presence(EP), "gone")

    def test_remote_capabilities_follow_the_bridged_status(self) -> None:
        tr = self._tr()
        caps = tr.capabilities(EP)
        self.assertTrue(caps.can_report_status and caps.supports_if_idle and caps.can_interrupt)
        self.assertFalse(caps.can_observe_procs)  # no remote `ps` without the optional watcher (MR-D3)
        self.sim.terms["dev/t7"].update(status=None, reported=False)
        self.assertFalse(tr.capabilities(EP).supports_if_idle)
        self.sim.set_machine("dev", "unreachable")
        self.assertFalse(tr.capabilities(EP).can_report_status)


class UncertainSendAndQueueTests(_Base):
    """§5.1.2 + I6: a send that timed out as the line dropped is reconciled by `(turn, status_ms)`, never retyped
    blindly; envelopes queued across a partition are typed once after it."""

    def setUp(self) -> None:
        super().setUp()
        self.ctx = make_ctx(self.base / "c", hc=HcHost(runner=self.sim, clock=self.clk), clock=self.clk)
        self.sim.terms["dev/t7"]["status"] = "idle"

    def _env(self, text: str) -> Envelope:
        return Envelope(env_id=new_env_id(int(self.clk.time() * 1000)), idempotency_key=f"k:{text}", schema_version=1,
                        created_ms=int(self.clk.time() * 1000), kind="cmd.send", sender=Principal.supervisor("demo"),
                        recipient=LogicalAddress.worker("demo-w1", project="demo"), project="demo",
                        cause={"kind": "test"}, priority=P3_DIRECT, body={"text": text})

    def test_timeout_with_the_line_dropping_is_reconciled_not_retyped(self) -> None:
        sim = self.sim

        def typed_then_dropped(addr, text):
            sim.sent.append((addr, text))  # the bytes went in...
            sim.set_machine("dev", "unreachable")  # ...and the line dropped before the answer (or the mirror) came
            return None
        sim.send_hook = typed_then_dropped
        mb, item = enqueue_for_endpoint(self.ctx, EP, self._env("fix the test"))
        res = drain_endpoint(self.ctx, EP, wait_s=0, transport=RemoteHcTransport(self.ctx, machine_ttl_s=0))
        self.assertEqual([o.status for _, o in res.held], ["timeout_uncertain"])
        cur = mb.get(item.envelope.env_id)
        self.assertEqual(cur.state, "accepted")
        self.assertIsNotNone(cur.intent)  # the anchors stay for the reconcile

        sim.send_hook = None
        self.clk.advance(3600)
        sim.set_machine("dev", "connected")
        t = sim.terms["dev/t7"]  # reconnected: the mirror shows the turn that message opened
        t["turn"] += 1
        t["status"] = "working"
        t["status_ms"] = int(self.clk.time() * 1000)
        res2 = drain_endpoint(self.ctx, EP, wait_s=0, transport=RemoteHcTransport(self.ctx, machine_ttl_s=0))
        self.assertEqual([o.detail for _, o in res2.typed], ["reconciled_after_partition"])
        self.assertEqual(len(sim.typed_to("dev/t7")), 1, "typed exactly once")
        self.assertNotEqual(mb.get(item.envelope.env_id).state, "accepted")

    def test_timeout_without_progress_is_retyped_once_reconnected(self) -> None:
        sim = self.sim

        def lost(addr, text):
            sim.set_machine("dev", "unreachable")
            return None
        sim.send_hook = lost
        mb, item = enqueue_for_endpoint(self.ctx, EP, self._env("again"))
        drain_endpoint(self.ctx, EP, wait_s=0, transport=RemoteHcTransport(self.ctx, machine_ttl_s=0))
        sim.send_hook = None
        sim.set_machine("dev", "connected")
        res = drain_endpoint(self.ctx, EP, wait_s=0, transport=RemoteHcTransport(self.ctx, machine_ttl_s=0))
        self.assertEqual(len(res.typed), 1)
        self.assertEqual(len(sim.typed_to("dev/t7")), 1)

    def test_queue_survives_an_hour_partition_and_is_typed_once_in_order(self) -> None:
        self.sim.set_machine("dev", "unreachable")
        mb = endpoint_mailbox(self.ctx, EP)
        ids = [enqueue_for_endpoint(self.ctx, EP, self._env(t))[1].envelope.env_id for t in ("one", "two", "three")]
        for _ in range(12):  # an hour, a drain every 5 minutes
            self.clk.advance(300)
            res = drain_endpoint(self.ctx, EP, wait_s=0, transport=RemoteHcTransport(self.ctx, machine_ttl_s=0))
            self.assertEqual(res.failed, [])
            self.assertEqual(res.typed, [])
        self.assertEqual([mb.get(i).state for i in ids], ["accepted"] * 3)  # not expired, not failed
        self.sim.set_machine("dev", "connected")
        sim = self.sim

        def settle(addr, text):  # each typed message ends its turn at once, so the next one goes in too
            return "pass"
        sim.send_hook = settle
        for _ in range(3):
            sim.terms["dev/t7"]["status"] = "idle"
            drain_endpoint(self.ctx, EP, wait_s=0, transport=RemoteHcTransport(self.ctx, machine_ttl_s=0))
        typed = sim.typed_to("dev/t7")
        self.assertEqual(len(typed), 3)
        self.assertEqual([("one" in t, "two" in t, "three" in t) for t in typed],
                         [(True, False, False), (False, True, False), (False, False, True)])


class OutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "state"

    def _env(self, key: str) -> Envelope:
        return Envelope(env_id=new_env_id(1), idempotency_key=key, schema_version=1, created_ms=1,
                        kind="report.task_log", sender=Principal.worker("demo", "demo-w1"),
                        recipient=LogicalAddress.ledger("demo"), project="demo", cause={}, priority=P3_DIRECT,
                        body={"task_id": "demo-w1", "text": key})

    def test_append_is_monotonic_signed_and_idempotent(self) -> None:
        ob = WorkerOutbox(self.root)
        a = ob.append(self._env("a"), token="tok")
        b = ob.append(self._env("b"), token="tok")
        again = ob.append(self._env("a"), token="tok")
        self.assertEqual((a.seq, b.seq, again.seq), (1, 2, 1))
        rows = parse_outbox_text(ob.path.read_text(encoding="utf-8"))
        self.assertEqual([r.seq for r in rows], [1, 2])
        self.assertTrue(verify_envelope("tok", rows[0].envelope, rows[0].mac))
        self.assertFalse(verify_envelope("other", rows[0].envelope, rows[0].mac))
        forged = dict(rows[0].envelope, body={"task_id": "demo-other", "text": "x"})
        self.assertFalse(verify_envelope("tok", forged, rows[0].mac))
        # A torn last line (being written while read) is skipped, then read whole next time.
        self.assertEqual([r.seq for r in parse_outbox_text(ob.path.read_text(encoding="utf-8") + '{"seq": 3, "env')],
                         [1, 2])

    def test_task_tokens_are_per_epoch_and_private(self) -> None:
        tokens = TaskTokens(Path(self.tmp.name) / "tokens")
        c1 = tokens.issue("demo-w1", 1, machine="dev")
        self.assertEqual(tokens.issue("demo-w1", 1)["token"], c1["token"])
        c2 = tokens.issue("demo-w1", 2)
        self.assertNotEqual(c1["token"], c2["token"])
        self.assertEqual(tokens.token_for("demo-w1", 1), c1["token"])
        path = Path(self.tmp.name) / "tokens" / "task-demo-w1.json"
        if sys.platform != "win32":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class RemoteReportPathTests(_Base):
    """§6.1 branch 2a, §11.2, §11.3: the worker appends; the coordinator pulls by `seq`, verifies, applies once."""

    def setUp(self) -> None:
        super().setUp()
        self.repo_path = self.base / "demo"
        self.repo_path.mkdir()
        self.repo = str(self.repo_path.resolve())
        self.slug = project_slug(self.repo)
        self.ctx = make_ctx(self.base / "c", hc=HcHost(runner=self.sim, clock=self.clk), clock=self.clk)
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.ctx.home.registration(self.slug).write_text(json.dumps({
            "name": f"pm-{self.slug}", "project": "demo", "repo": self.repo, "runtime": "hc", "terminal": "t1",
            "pane": "hc:t1"}), encoding="utf-8")
        self.tid = "demo-w1"
        self.state1 = self.dev_home / ".herdr" / "pm-worker" / "demo-w1"
        task = {
            "id": self.tid, "title": "remote work", "repo": self.repo, "project": "demo", "status": "in_progress",
            "pane": "hc:dev/t7", "dispatched": True, "worker": {"kind": "claude"}, "created": self.clk.now(),
            "log": [], "branch": "dev/remote", "base": "main", "no_review": True,
            "round": {"terminal": "dev/t7", "at": self.clk.now(), "turn": 1},
            "remote": {"machine": "dev", "terminal": "t7", "epoch": 1, "worktree": str(self.dev_home / "wt"),
                       "state_dir": str(self.state1), "repo": "~/clone", "base_sha": ""},
            "endpoint": Endpoint(runtime="hc", machine="dev", terminal="t7", epoch=1).to_dict(),
        }
        self.ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        self.ctx.home.task(self.tid).write_text(json.dumps(task), encoding="utf-8")
        self.worker_ctx = self._worker_ctx(self.state1, 1)

    def _worker_ctx(self, state_dir: Path, epoch: int):
        cred = TaskTokens(self.ctx.home.tokens).issue(self.tid, epoch, machine="dev")
        task = Ledger(self.ctx).load(self.tid).raw
        context = dict(worker_context(self.ctx, task), epoch=epoch)
        write_worker_state_files(state_dir, context=context, credential=cred)
        # The worker's machine: its own home, no ledger of the coordinator's, PM_WORKER_STATE set.
        return make_ctx(self.base / f"worker-e{epoch}", clock=self.clk, env={"PM_WORKER_STATE": str(state_dir)})

    def _task(self) -> dict:
        return Ledger(self.ctx).load(self.tid).raw

    def _log_texts(self) -> list[str]:
        return [str(e.get("text") or "") for e in self._task().get("log") or []]

    def test_remote_commands_queue_into_the_outbox_without_touching_any_ledger(self) -> None:
        wctx = self.worker_ctx
        self.assertIsNotNone(WorkerState.from_env(wctx.env))
        rec = ReportClient(wctx).submit(task_log_report(wctx, "", "first step done"))
        self.assertTrue(rec.result.get("queued"))
        env = task_update_report(wctx, UpdateRequest(id="demo-w1", note="halfway"))
        self.assertEqual((env.sender.role, env.sender.task_id, env.sender.machine), ("worker", self.tid, "dev"))
        self.assertEqual(env.project, self.slug)
        ReportClient(wctx).submit(env)
        rows = WorkerOutbox(self.state1).lines()
        self.assertEqual([r.seq for r in rows], [1, 2])
        self.assertFalse(list(wctx.home.tasks.glob("*.json")) if wctx.home.tasks.exists() else [])
        self.assertIn("seq=2", wctx.out.stdout)

    def test_one_hour_partition_then_replay_applies_each_report_exactly_once(self) -> None:
        wctx = self.worker_ctx
        sync = RemoteReportSync(self.ctx)
        watcher = StallWatcher(self.ctx, stall_grace=0)
        task = self._task()
        stops, bases = {}, {}
        watcher.watch_workers([task], stops, bases)

        self.sim.set_machine("dev", "unreachable")
        pm_box = MailboxStore(self.ctx.home.project_for(self.repo).pm_mailbox, clock=self.ctx.clock)
        # The PM says something to the worker during the partition: it waits in the worker's mailbox.
        ep7 = Endpoint(runtime="hc", machine="dev", terminal="t7")
        _, queued = enqueue_for_endpoint(self.ctx, ep7, Envelope(
            env_id=new_env_id(int(self.clk.time() * 1000)), idempotency_key="pm-says", schema_version=1,
            created_ms=int(self.clk.time() * 1000), kind="cmd.send", sender=Principal.pm(self.slug),
            recipient=LogicalAddress.worker(self.tid, project=self.slug), project=self.slug, cause={},
            priority=P3_DIRECT, body={"text": "also cover the empty case"}))
        ReportClient(wctx).submit(task_log_report(wctx, "", "offline: fixed the edge case"))
        ReportClient(wctx).submit(task_update_report(wctx, UpdateRequest(id=self.tid, note="offline: all green")))
        ReportClient(wctx).submit(task_log_report(wctx, "", "offline: wrote evidence"))
        for _ in range(12):  # 60 virtual minutes
            self.clk.advance(300)
            res = sync.sync_task(self._task(), force=True)
            self.assertEqual([(r.link_state, r.applied, r.cursor) for r in res], [("disconnected", 0, 0)])
            watcher.watch_workers([self._task()], stops, bases)
        store = EndpointTurnStore(self.ctx, Endpoint(runtime="hc", machine="dev", terminal="t7"), repo=self.repo)
        self.assertEqual(store.read()["link_state"], "disconnected")
        self.assertEqual([e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "stall"], [])
        self.assertEqual(self._task()["status"], "in_progress")
        self.assertFalse([t for t in self._log_texts() if "offline:" in t])

        self.sim.set_machine("dev", "connected")
        self.clk.advance(5)
        res = sync.sync_task(self._task(), force=True)
        self.assertEqual([(r.applied, r.duplicates, r.rejected, r.cursor) for r in res], [(3, 0, 0, 3)])
        self.assertEqual(endpoint_mailbox(self.ctx, ep7).get(queued.envelope.env_id).state, "accepted")
        drains = [sp["args"] for sp in self.ctx.procs.spawned if sp["args"][:1] == ["_drain-endpoint"]]
        self.assertEqual(drains, [["_drain-endpoint", "dev/t7", "--timeout", "180"]])  # typed now the line is back
        offline = [t for t in self._log_texts() if "offline:" in t]
        self.assertEqual(len(offline), 3, offline)

        # The answer to the first pull is lost (the cursor was never saved): the same lines come again.
        state_file = next((self.ctx.home.project_for(self.repo).applied_reports_json.parent / "remote-sync").glob("*"))
        state_file.write_text(json.dumps({"outbox_seq": 0}), encoding="utf-8")
        res2 = sync.sync_task(self._task(), force=True)
        self.assertEqual([(r.applied, r.duplicates, r.cursor) for r in res2], [(0, 3, 3)])
        self.assertEqual(len([t for t in self._log_texts() if "offline:" in t]), 3, "zero duplicate apply")
        self.assertFalse([i for i in pm_box.active_items() if i.envelope.kind == "event.report_rejected"])

    def test_idle_backoff_and_no_pull_before_it_is_due(self) -> None:
        sync = RemoteReportSync(self.ctx)
        waits = [sync.sync_task(self._task(), force=True)[0].next_poll_s for _ in range(5)]
        self.assertEqual(waits, [2.0, 4.0, 8.0, 10.0, 10.0])
        skipped = sync.sync_task(self._task())[0]
        self.assertTrue(skipped.skipped)
        ReportClient(self.worker_ctx).submit(task_log_report(self.worker_ctx, "", "new"))
        self.clk.advance(11)
        self.assertEqual(sync.sync_task(self._task())[0].next_poll_s, 2.0)

    def test_a_missing_token_here_holds_the_lines_instead_of_refusing_them(self) -> None:
        ReportClient(self.worker_ctx).submit(task_log_report(self.worker_ctx, "", "signed"))
        tok = self.ctx.home.tokens / "task-demo-w1.json"
        saved = tok.read_bytes()
        tok.unlink()
        sync = RemoteReportSync(self.ctx)
        res = sync.sync_task(self._task(), force=True)[0]
        self.assertEqual((res.missing_token, res.rejected, res.applied, res.cursor), (True, 0, 0, 0))
        sync.sync_task(self._task(), force=True)
        self.assertEqual(len([t for t in self._log_texts() if "no task token" in t]), 1)  # said once
        tok.write_bytes(saved)
        res2 = sync.sync_task(self._task(), force=True)[0]
        self.assertEqual((res2.applied, res2.cursor), (1, 1))

    def test_a_forged_line_is_refused_and_does_not_block_the_ones_after_it(self) -> None:
        ob = WorkerOutbox(self.state1)
        env = task_log_report(self.worker_ctx, "", "forged")
        ob.append(env, token="not-the-task-token")
        ReportClient(self.worker_ctx).submit(task_log_report(self.worker_ctx, "", "honest"))
        res = RemoteReportSync(self.ctx).sync_task(self._task(), force=True)[0]
        self.assertEqual((res.applied, res.rejected, res.cursor), (1, 1, 2))
        texts = self._log_texts()
        self.assertTrue(any("refused" in t and "seq=1" in t for t in texts), texts)
        self.assertTrue(any(t == "honest" for t in texts))
        self.assertFalse(any(t == "forged" for t in texts))

    def test_a_signed_report_cannot_speak_for_another_task(self) -> None:
        other = dict(self._task(), id="demo-w2", pane="hc:dev/t8", remote=None, endpoint=None)
        self.ctx.home.task("demo-w2").write_text(json.dumps(other), encoding="utf-8")
        env = task_update_report(self.worker_ctx, UpdateRequest(id="demo-w2", status="abandoned", note="hijack"))
        ReportClient(self.worker_ctx).submit(env)
        res = RemoteReportSync(self.ctx).sync_task(self._task(), force=True)[0]
        self.assertEqual(res.rejected, 1)
        self.assertNotEqual(Ledger(self.ctx).load("demo-w2").raw.get("status"), "abandoned")

    def test_stale_epoch_report_is_archived_with_a_p4_summary_and_status_kept(self) -> None:
        # The task moved to a new remote worker (epoch 2) while the first one was offline.
        state2 = self.dev_home / ".herdr" / "pm-worker" / "demo-w1-e2"

        def _rotate(cur, _ch):
            raw = cur.raw
            raw["remote_history"] = [dict(raw["remote"])]
            raw["remote"] = dict(raw["remote"], terminal="t9", epoch=2, state_dir=str(state2))
            raw["endpoint"] = Endpoint(runtime="hc", machine="dev", terminal="t9", epoch=2).to_dict()
            raw["pane"] = "hc:dev/t9"
            raw["status"] = "in_progress"
            return raw
        Ledger(self.ctx).change(self.tid, _rotate)
        self._worker_ctx(state2, 2)
        old = self.worker_ctx  # epoch 1, still holding its own token
        ReportClient(old).submit(task_log_report(old, "", "old worker: found the root cause"))
        ReportClient(old).submit(task_update_report(old, UpdateRequest(id=self.tid, status="review", commit="8899aa1",
                                                                       note="done offline")))
        results = RemoteReportSync(self.ctx).sync_task(self._task(), force=True)
        by_epoch = {r.epoch: r for r in results}
        self.assertEqual((by_epoch[1].applied, by_epoch[1].late), (1, 1))
        task = self._task()
        self.assertEqual(task["status"], "in_progress", "current status untouched")
        self.assertEqual(task["pane"], "hc:dev/t9", "current worker untouched")
        texts = self._log_texts()
        self.assertTrue(any(t.startswith("[delayed report from epoch 1") and "root cause" in t for t in texts))
        late = [e for e in task["log"] if e.get("late_report")]
        self.assertEqual(len(late), 1)
        self.assertIn("commit=8899aa1", late[0]["text"])
        pm_box = MailboxStore(self.ctx.home.project_for(self.repo).pm_mailbox, clock=self.ctx.clock)
        events = [i for i in pm_box.active_items() if i.envelope.kind == "event.late_report"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].envelope.priority, P4_BATCH)
        # Pulled again: archived once, summarised once.
        RemoteReportSync(self.ctx).sync_task(self._task(), force=True)
        state_dir = self.ctx.home.project_for(self.repo).applied_reports_json.parent / "remote-sync"
        for f in state_dir.glob("*-e1.json"):
            f.write_text("{}", encoding="utf-8")
        RemoteReportSync(self.ctx).sync_task(self._task(), force=True)
        self.assertEqual(len([e for e in self._task()["log"] if e.get("late_report")]), 1)
        self.assertEqual(len([i for i in pm_box.active_items() if i.envelope.kind == "event.late_report"]), 1)

    def test_a_pane_moved_off_the_remote_endpoint_bumps_the_epoch(self) -> None:
        raw = dict(self._task(), pane="hc:t12")
        reconcile_task_endpoint(raw)
        self.assertEqual((raw["endpoint"]["terminal"], raw["endpoint"]["machine"], raw["endpoint"]["epoch"]),
                         ("t12", None, 2))
        self.assertNotIn("remote", raw)
        self.assertEqual(raw["remote_history"][0]["terminal"], "t7")
        self.assertEqual(next_remote_epoch(raw), 3)


class RemoteGitTests(_Base):
    """§7.3 items 1-3, §11.4: worktree there, branch back here, approve merges here (MR-D1)."""

    def setUp(self) -> None:
        super().setUp()
        self.repo_path = self.base / "demo"
        self.repo_path.mkdir()
        _git(self.repo_path, "init", "-q", "-b", "main")
        (self.repo_path / "a.txt").write_text("one\n", encoding="utf-8")
        _git(self.repo_path, "add", "a.txt")
        _git(self.repo_path, "commit", "-q", "-m", "one")
        self.repo = str(self.repo_path.resolve())
        self.slug = project_slug(self.repo)
        _git(self.dev_home, "clone", "-q", self.repo, str(self.dev_home / "clone"))
        cfg = {"machines": {"dev": {"repos": {self.slug: "~/clone"}, "pm": "python3 ~/pm/pm.py"}}}
        self.ctx = make_ctx(self.base / "c", hc=HcHost(runner=self.sim, clock=self.clk), clock=self.clk, config=cfg,
                            git=GitRepo(worktree_base=self.base / "local-wt"))
        self.ws = RemoteWorkspace(self.ctx, machine_profile(self.ctx, "dev", self.repo))

    def _task_for(self, prep, branch: str = "dev/remote") -> dict:
        tid = "demo-w1"
        self.ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        self.ctx.home.task(tid).write_text(json.dumps({
            "id": tid, "title": "t", "repo": self.repo, "status": "review", "branch": branch, "base": "main",
            "pane": "hc:dev/t7", "created": self.clk.now(), "log": [], "worker": {"kind": "claude"},
            "commit": ""}), encoding="utf-8")
        return record_remote_worker(self.ctx, tid, machine="dev", terminal="t7", epoch=1, prep=prep,
                                    pm_command="python3 ~/pm/pm.py")

    def _worker_commits(self, worktree: str, name: str = "b.txt") -> str:
        (Path(worktree) / name).write_text("remote work\n", encoding="utf-8")
        _git(worktree, "add", name)
        _git(worktree, "commit", "-q", "-m", f"add {name}")
        return _git(worktree, "rev-parse", "HEAD")

    def test_prepare_makes_the_worktree_there_and_brings_a_missing_base_by_bundle(self) -> None:
        (self.repo_path / "a.txt").write_text("two\n", encoding="utf-8")
        _git(self.repo_path, "commit", "-q", "-am", "two (not in the clone)")
        head = _git(self.repo_path, "rev-parse", "HEAD")
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        self.assertTrue(prep.worktree.startswith(str(self.dev_home)))
        self.assertEqual(_git(prep.worktree, "rev-parse", "HEAD"), head)
        self.assertEqual(_git(prep.worktree, "branch", "--show-current"), "dev/remote")
        self.assertTrue(prep.state_dir.endswith("-e1"))

    def test_same_machine_redispatch_reuses_the_worktree_and_brings_local_commits(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        task = self._task_for(prep)
        sha = self._worker_commits(prep.worktree)
        self.ws.fetch_branch(task)
        # A reviewer's test fix lands on the branch here, on top of the worker's commit.
        rev_wt = self.base / "rev-wt"
        _git(self.repo_path, "worktree", "add", "-q", str(rev_wt), "dev/remote")
        (rev_wt / "fix.txt").write_text("fix\n", encoding="utf-8")
        _git(rev_wt, "add", "fix.txt")
        _git(rev_wt, "commit", "-q", "-m", "reviewer fix")
        fix = _git(rev_wt, "rev-parse", "HEAD")
        _git(self.repo_path, "worktree", "remove", "--force", str(rev_wt))
        again = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main", epoch=2)
        self.assertEqual(again.worktree, prep.worktree)
        self.assertNotEqual(again.state_dir, prep.state_dir)  # its own outbox and token
        self.assertEqual(_git(prep.worktree, "rev-parse", "HEAD"), fix)
        self.assertEqual(_git(prep.worktree, "rev-parse", "HEAD~1"), sha)

    def test_pushes_of_unrelated_histories_for_tasks_on_one_machine_do_not_collide(self) -> None:
        # Task A is redispatched there carrying a reviewer fix the clone lacks (one push)...
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        task = self._task_for(prep)
        self._worker_commits(prep.worktree)
        self.ws.fetch_branch(task)
        rev_wt = self.base / "rev-wt"
        _git(self.repo_path, "worktree", "add", "-q", str(rev_wt), "dev/remote")
        (rev_wt / "fix.txt").write_text("fix\n", encoding="utf-8")
        _git(rev_wt, "add", "fix.txt")
        _git(rev_wt, "commit", "-q", "-m", "reviewer fix")
        _git(self.repo_path, "worktree", "remove", "--force", str(rev_wt))
        self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main", epoch=2)
        # ...then main moves on here (not a descendant of that fix) and task B starts from it on the same machine.
        (self.repo_path / "a.txt").write_text("main moved\n", encoding="utf-8")
        _git(self.repo_path, "commit", "-q", "-am", "main moves on")
        main_head = _git(self.repo_path, "rev-parse", "main")
        other = self.ws.prepare(local_repo=self.repo, branch="dev/other", base="main")
        self.assertEqual(_git(other.worktree, "rev-parse", "HEAD"), main_head)
        clone = self.dev_home / "clone"
        self.assertEqual(_git(clone, "for-each-ref", "refs/pm-remote/"), "")  # every push ref dropped there
        self.assertEqual(_git(self.repo_path, "for-each-ref", "refs/pm-remote/"), "")  # and here

    def test_a_refused_prepare_leaves_no_state_folder(self) -> None:
        bad = self.dev_home / ".herdr" / "worktrees" / self.slug / "dev-taken"
        bad.mkdir(parents=True)
        with self.assertRaises(Refused):
            self.ws.prepare(local_repo=self.repo, branch="dev/taken", base="main")
        self.assertFalse(list((self.dev_home / ".herdr").glob("pm-worker/*")))

    def test_redispatch_reuses_an_existing_branch_without_a_worktree(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        sha = self._worker_commits(prep.worktree)
        _git(self.dev_home / "clone", "worktree", "remove", "--force", prep.worktree)
        again = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main", epoch=2)
        self.assertEqual(_git(again.worktree, "rev-parse", "HEAD"), sha)

    def test_redispatch_refuses_diverged_histories_and_foreign_paths(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        self._worker_commits(prep.worktree, "remote.txt")
        _git(self.repo_path, "branch", "dev/remote", "main")
        rev_wt = self.base / "rev-wt"
        _git(self.repo_path, "worktree", "add", "-q", str(rev_wt), "dev/remote")
        (rev_wt / "here.txt").write_text("x\n", encoding="utf-8")
        _git(rev_wt, "add", "here.txt")
        _git(rev_wt, "commit", "-q", "-m", "here")
        _git(self.repo_path, "worktree", "remove", "--force", str(rev_wt))
        with self.assertRaises(Refused) as cm:
            self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main", epoch=2)
        self.assertIn("diverged", str(cm.exception))
        other = RemoteWorkspace(self.ctx, machine_profile(self.ctx, "dev", self.repo))
        with self.assertRaises(Refused) as cm2:
            other.prepare(local_repo=self.repo, branch="dev/other", base="main")  # fine: a new branch
            Path(self.dev_home / ".herdr" / "worktrees" / self.slug / "dev-third").mkdir(parents=True)
            other.prepare(local_repo=self.repo, branch="dev/third", base="main")
        self.assertIn("not a worktree", str(cm2.exception))

    def test_moving_to_another_machine_starts_from_the_commits_fetched_here(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        task = self._task_for(prep)
        sha = self._worker_commits(prep.worktree)
        self.ws.fetch_branch(task)
        mbp_home = self.sim.add_machine("mbp")
        _git(mbp_home, "clone", "-q", self.repo, str(mbp_home / "clone"))
        cfg = json.loads(self.ctx.home.config.read_text(encoding="utf-8"))
        cfg["machines"]["mbp"] = {"repos": {self.slug: "~/clone"}}
        self.ctx.home.config.write_text(json.dumps(cfg), encoding="utf-8")
        mbp = RemoteWorkspace(self.ctx, machine_profile(self.ctx, "mbp", self.repo))
        moved = mbp.prepare(local_repo=self.repo, branch="dev/remote", base="main", epoch=2)
        self.assertEqual(_git(moved.worktree, "rev-parse", "HEAD"), sha)

    def test_fetch_never_moves_the_branch_here_back_or_sideways(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        task = self._task_for(prep)
        self._worker_commits(prep.worktree)
        first = self.ws.fetch_branch(task)
        rev_wt = self.base / "rev-wt"
        _git(self.repo_path, "worktree", "add", "-q", str(rev_wt), "dev/remote")
        (rev_wt / "fix.txt").write_text("fix\n", encoding="utf-8")
        _git(rev_wt, "add", "fix.txt")
        _git(rev_wt, "commit", "-q", "-m", "reviewer fix")
        fix = _git(rev_wt, "rev-parse", "HEAD")
        _git(self.repo_path, "worktree", "remove", "--force", str(rev_wt))
        worker_next = self._worker_commits(prep.worktree, "c.txt")  # the worker went on without the fix
        with self.assertRaises(Refused) as cm:
            self.ws.fetch_branch(task)
        self.assertIn("fast-forward", str(cm.exception))
        self.assertEqual(_git(self.repo_path, "rev-parse", "refs/heads/dev/remote"), fix)  # the fix is kept
        self.assertEqual(_git(self.repo_path, "rev-parse", "refs/remotes/workers/dev/dev/remote"), worker_next)
        self.assertNotEqual(first, fix)
        with self.assertRaises(Refused):  # approve refuses too instead of merging something else
            Landing(self.ctx).approve(ApproveRequest(id="demo-w1", commit=fix))

    def test_credential_is_private_from_its_first_byte(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        leftover = Path(prep.state_dir) / "credential.json.tmp"
        leftover.write_text("old", encoding="utf-8")
        leftover.chmod(0o644)  # an earlier write that died midway
        self.ws.write_state(prep.state_dir, {"remote": True}, {"token": "secret"})
        cred = Path(prep.state_dir) / "credential.json"
        self.assertFalse(leftover.exists())
        self.assertEqual(json.loads(cred.read_text(encoding="utf-8"))["token"], "secret")
        if sys.platform != "win32":
            self.assertEqual(cred.stat().st_mode & 0o777, 0o600)
        self.assertFalse([c for c in self.sim.calls if c[:2] == ("file", "write") and "credential" in c[-1]])

    def test_fetch_brings_the_branch_back_and_refuses_clearly_when_unreachable(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        task = self._task_for(prep)
        sha = self._worker_commits(prep.worktree)
        self.assertEqual(self.ws.fetch_branch(task), sha)
        self.assertEqual(_git(self.repo_path, "rev-parse", "refs/heads/dev/remote"), sha)
        self.assertEqual(_git(self.repo_path, "rev-parse", "refs/remotes/workers/dev/dev/remote"), sha)
        sha2 = self._worker_commits(prep.worktree, "c.txt")  # a second round only sends what is new
        self.assertEqual(self.ws.fetch_branch(task), sha2)
        review_tree = self.ws.review_checkout(task, sha2)
        self.assertEqual(_git(review_tree, "rev-parse", "HEAD"), sha2)
        self.sim.set_machine("dev", "unreachable")
        with self.assertRaises(Refused) as cm:
            self.ws.fetch_branch(task)
        self.assertIn("unreachable", str(cm.exception))

    def test_approve_fetches_merges_here_and_refreshes_the_worker_context(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        task = self._task_for(prep)
        self.ws.write_state(prep.state_dir, worker_context(self.ctx, task))
        sha = self._worker_commits(prep.worktree)
        with self.assertRaises(Refused):  # MR-D1: a remote worker never pushes to the main checkout
            Landing(self.ctx).approve(ApproveRequest(id="demo-w1", via="worker", commit=sha))
        done = Landing(self.ctx).approve(ApproveRequest(id="demo-w1", commit=sha))
        approved = Ledger(self.ctx).load("demo-w1").raw["land_approved"]
        self.assertEqual(approved["commit"], sha)
        self.assertEqual(approved["executor"], "manual")  # no desktop PM in this test: the merge is run here by hand
        self.assertIn("land demo-w1", " ".join(t for _, t in done.said))
        ctx_json = json.loads((Path(prep.state_dir) / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(ctx_json["land_approved"]["commit"], sha)

    def test_approve_with_a_desktop_pm_delegates_to_a_local_helper_and_keeps_the_worker(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        task = self._task_for(prep)
        sha = self._worker_commits(prep.worktree)
        self.ctx.pane = "hc:t1"
        started = {}

        def fake_start(_self, fields, _done):
            started.update(fields)
            return "t30"
        sends = []
        with mock.patch.object(Landing, "_start", fake_start), \
                mock.patch("pmlib.caller.Caller.is_pm_caller", return_value=True), \
                mock.patch("pmlib.workers.service.Workers.send_async_later",
                           lambda _s, term, msg, **kw: sends.append((term, msg, kw)) or True), \
                mock.patch("pmlib.workers.service.Workers._deliver_later", lambda *_a, **_k: None):
            Landing(self.ctx).approve(ApproveRequest(id="demo-w1", commit=sha))
        approved = Ledger(self.ctx).load("demo-w1").raw["land_approved"]
        self.assertEqual(approved["executor"], "helper")
        self.assertEqual(approved["executor_pane"], "hc:t30")
        prompt = json.dumps(started, ensure_ascii=False)
        self.assertIn("dev/t7", prompt)  # conflicts go back to the remote worker
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][0], "dev/t7")
        self.assertIn("Stay available", sends[0][1])
        ctx_json = json.loads((Path(prep.state_dir) / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(ctx_json["land_approved"]["executor"], "helper")

    def test_context_refresh_reports_a_down_machine_instead_of_raising(self) -> None:
        prep = self.ws.prepare(local_repo=self.repo, branch="dev/remote", base="main")
        task = self._task_for(prep)
        self.sim.set_machine("dev", "unreachable")
        self.assertIn("unavailable", refresh_remote_context(self.ctx, task))


class _RemoteMachineSimRunner:
    """Routes `HcHost` calls inside a simulated remote machine (`dev`) to `SimHc` under `<machine>/<term>`."""

    def __init__(self, sim: SimHc, machine: str) -> None:
        self.sim = sim
        self.machine = machine

    def _q(self, term: str) -> str:
        return term if "/" in term else f"{self.machine}/{term}"

    def _strip(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        addr = str(out.get("address") or "")
        if addr.startswith(f"{self.machine}/"):
            out["address"] = addr[len(self.machine) + 1:]
        if str(out.get("id") or "").startswith(f"{self.machine}/"):
            out["id"] = str(out["id"])[len(self.machine) + 1:]
        return out

    def __call__(self, *argv: str, errors: bool = False, env: Any = None, timeout: float = 60,
                 input: str | None = None) -> Any:
        args = list(argv)
        cmd = args[0] if args else ""
        if cmd == "run":
            res = self.sim("run", "--on", self.machine, *args[1:], errors=errors, env=env, timeout=timeout)
            if isinstance(res, dict) and str(res.get("address") or "").startswith(f"{self.machine}/"):
                return {"address": res["address"][len(self.machine) + 1:]}
            return res
        if cmd in ("get", "label", "keep", "kill", "rm", "read"):
            res = self.sim(cmd, self._q(args[1]), *args[2:], errors=errors, env=env, timeout=timeout)
            return self._strip(res) if isinstance(res, dict) and "address" in res else res
        if cmd == "ls":
            res = self.sim(*args, errors=errors, env=env, timeout=timeout)
            if isinstance(res, dict) and isinstance(res.get("terminals"), list):
                prefix = f"{self.machine}/"
                return {"terminals": [self._strip(r) for r in res["terminals"] if str(r.get("address") or "").startswith(prefix)]}
            return res
        return self.sim(*args, errors=errors, env=env, timeout=timeout, input=input)


class RemoteProjectLifecycleTests(_Base):
    """Slice 2 remote end-to-end: SimHc 0-folder & multi-folder start --no-app-space, set-space, archive, restore."""

    def test_simhc_remote_create_bind_archive_restore_full_loop(self) -> None:
        from pmlib.manager.service import ManagerSessions
        from pmlib.views.state import dash_state
        from tests.fakes import run_main

        dev_ledger = self.dev_home / ".dudu"
        repo_a = self.dev_home / "repos" / "api"
        repo_b = self.dev_home / "repos" / "web"
        repo_a.mkdir(parents=True)
        repo_b.mkdir(parents=True)
        _git(repo_a, "init", "-b", "main")
        (repo_a / "a.txt").write_text("a\n", encoding="utf-8")
        _git(repo_a, "add", "a.txt")
        _git(repo_a, "commit", "-q", "-m", "init a")

        dev_hc = HcHost(runner=_RemoteMachineSimRunner(self.sim, "dev"), app_runner=lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("no gui")))
        dev_ctx = make_ctx(dev_ledger, hc=dev_hc, git=GitRepo(), clock=self.clk)

        # 1. Stage 1 on remote `dev`: start multi-folder project (1 git + 1 plain folder) with --no-app-space --json
        rc, out, err = run_main(
            dev_ctx, "start", "--folder", str(repo_a), "--folder", str(repo_b),
            "--name", "Remote Stack", "--kind", "agy", "--no-app-space", "--json",
        )
        self.assertEqual(rc, 0, err)
        created = json.loads(out)
        self.assertTrue(created["ok"])
        self.assertEqual(created["slug"], "remote-stack")
        self.assertTrue(created["terminal"].startswith("t"))
        self.assertEqual([f["alias"] for f in created["folders"]], ["api", "web"])
        self.assertEqual(created["folders"][0]["git"], True)
        self.assertEqual(created["folders"][1]["git"], False)
        self.assertEqual(created["space_id"], "")

        # Stage 2 from local client: label `dev/<term>` with herdr.space + herdr.tab and persist via `project set-space`
        q_term = f"dev/{created['terminal']}"
        self.sim("label", q_term, "herdr.space=sp-dev-stack", "herdr.tab=tb-dev-stack")
        rc_sp, out_sp, err_sp = run_main(dev_ctx, "project", "set-space", created["slug"], "sp-dev-stack", "--space-name", "Remote Stack")
        self.assertEqual(rc_sp, 0, err_sp)
        self.assertEqual(json.loads(out_sp)["space_id"], "sp-dev-stack")

        # Seed an active task on remote project, verify state, then archive via `pm.py archive --json`
        Ledger(dev_ctx).save({
            "id": "rs-1", "project": "remote-stack", "project_slug": "remote-stack",
            "repo": str(repo_a), "folder_alias": "api", "title": "Remote work",
            "status": "in_progress", "created": self.clk.now(),
        })
        st_before = dash_state(dev_ctx)
        pm_before = next(p for p in st_before["pms"] if p["slug"] == "remote-stack")
        self.assertEqual(pm_before["space_id"], "sp-dev-stack")
        self.assertEqual(pm_before["agent"], "agy")

        rc_ar, out_ar, err_ar = run_main(dev_ctx, "archive", "remote-stack", "--json")
        self.assertEqual(rc_ar, 0, err_ar)
        arch = json.loads(out_ar)
        self.assertEqual(arch["paused"], 1)
        self.assertEqual(arch["space_id"], "sp-dev-stack")
        self.assertEqual(Ledger(dev_ctx).load("rs-1").status, "paused")
        self.assertNotIn(q_term, self.sim.terms)  # PM terminal was ended & removed on remote host

        # Restore via `pm.py restore --no-app-space --json`
        rc_re, out_re, err_re = run_main(dev_ctx, "restore", "remote-stack", "--no-app-space", "--json")
        self.assertEqual(rc_re, 0, err_re)
        rest = json.loads(out_re)
        self.assertEqual(rest["restored"], 1)
        self.assertTrue(rest["terminal"].startswith("t"))
        self.assertNotEqual(rest["terminal"], created["terminal"])
        self.assertEqual(Ledger(dev_ctx).load("rs-1").status, "in_progress")

        # 2. Remote 0-folder project creation + archive + restore
        rc_z, out_z, err_z = run_main(dev_ctx, "start", "--name", "Remote Notes", "--kind", "claude", "--no-app-space", "--json")
        self.assertEqual(rc_z, 0, err_z)
        z_res = json.loads(out_z)
        self.assertEqual(z_res["folders"], [])
        self.assertEqual(Path(z_res["cwd"]).resolve(), dev_ctx.home.project("remote-notes").root.resolve())
        self.assertEqual(run_main(dev_ctx, "archive", "remote-notes", "--json")[0], 0)
        rc_zr, out_zr, err_zr = run_main(dev_ctx, "restore", "remote-notes", "--no-app-space", "--json")
        self.assertEqual(rc_zr, 0, err_zr)
        self.assertTrue(json.loads(out_zr)["terminal"].startswith("t"))


if __name__ == "__main__":
    unittest.main()
