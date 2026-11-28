"""Phase 6b (`pm-message-routing.md` §5, §6.5, §7, §8, §9.3, §10, §11.5, §12.1; `pm-stuck-root-fix.md` §4.7):
self-hosted pull worker transport (`SelfHostedPullTransport`), node enrollment/auth/revocation, isomorphic HTTP +
stdio sync carriers, `worker-agent`, offline partition/reconnect replay, stale-epoch MR-D4 archiving, MR-D1 merge
delegation, and §6.5 privacy boundary.

Zero real network/SSH/external services: uses loopback `ThreadingHTTPServer`, WSGI `wsgi_app`, local pipe/subprocess
`StdioHubClient` (`pm.py mailbox-sync --stdio`), `InProcessHubClient`, and isolated local git repositories.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import FakeClock, make_ctx  # noqa: E402
from pmlib import cli  # noqa: E402
from pmlib.errors import Refused  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.landing import ApproveRequest, Landing  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.task import reconcile_task_endpoint  # noqa: E402
from pmlib.ledger.transition import UpdateRequest  # noqa: E402
from pmlib.memory.layer import MemoryLayer  # noqa: E402
from pmlib.messaging.address import Endpoint  # noqa: E402
from pmlib.messaging.mailbox import MailboxStore  # noqa: E402
from pmlib.messaging.nodes import (  # noqa: E402
    NodeError,
    NodeRegistry,
    NodeStreams,
    sign_request,
    signed_request,
    token_digest,
)
from pmlib.messaging.outbox import WorkerState  # noqa: E402
from pmlib.messaging.transports.self_hosted import SelfHostedPullTransport  # noqa: E402
from pmlib.nodes.agent import (  # noqa: E402
    CREDENTIAL,
    AgentError,
    FileDriver,
    TaskState,
    WorkerAgent,
    join as agent_join,
)
from pmlib.nodes.hub import SyncHub  # noqa: E402
from pmlib.nodes.wire import (  # noqa: E402
    HttpHubClient,
    InProcessHubClient,
    StdioHubClient,
    serve_http,
    serve_stdio,
    wsgi_app,
)
from pmlib.project.turn_state import EndpointTurnStore  # noqa: E402
from pmlib.reactions import Updates  # noqa: E402
from pmlib.reports import ReportClient, memory_report, task_log_report, task_update_report  # noqa: E402
from pmlib.review.review import ReviewRequest, Reviews  # noqa: E402
from pmlib.workers.lifecycle import live_worker_for  # noqa: E402
from pmlib.workers.self_hosted import (  # noqa: E402
    SelfHostedWorkspace,
    self_hosted_brief,
    self_hosted_context,
    self_hosted_endpoint,
)
from pmlib.workers.service import DispatchRequest, Workers  # noqa: E402
from sim_hc import SimHc  # noqa: E402
from pmlib.terminals.hc import HcHost  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@test",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@test",
    }
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env)
    return res.stdout.strip()


def _init_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    (path / "app.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "app.txt")
    _git(path, "commit", "-m", "init")
    return _git(path, "rev-parse", "HEAD")


class _ScriptedDriver:
    """Deterministic local worker driver for `WorkerAgent` tests."""

    def __init__(self, *, can_report_status: bool = True, can_interrupt: bool = True, can_unblock_keys: bool = True) -> None:
        self._caps = {
            "can_report_status": can_report_status,
            "can_interrupt": can_interrupt,
            "can_unblock_keys": can_unblock_keys,
            "can_observe_screen": False,
            "can_observe_procs": False,
            "can_observe_transcript": False,
        }
        self.started: list[tuple[str, str]] = []
        self.delivered: list[tuple[str, str, str]] = []
        self.interrupts: list[str] = []
        self.keys_sent: list[tuple[str, list[str]]] = []
        self.current_status: dict[str, dict] = {}
        self.next_deliver_status: str = "typed"

    def capabilities(self) -> dict[str, bool]:
        return dict(self._caps)

    def start(self, task: TaskState, brief) -> str:
        self.started.append((task.task_id, brief.env_id))
        return self.deliver(task, brief)

    def deliver(self, task: TaskState, env) -> str:
        if self.next_deliver_status != "typed":
            return self.next_deliver_status
        self.delivered.append((task.task_id, env.env_id, env.kind))
        return "typed"

    def interrupt(self, task: TaskState) -> str:
        self.interrupts.append(task.task_id)
        return "stopped" if self._caps["can_interrupt"] else "unsupported"

    def keys(self, task: TaskState, keys: list[str]) -> bool:
        self.keys_sent.append((task.task_id, list(keys)))
        return bool(self._caps["can_unblock_keys"])

    def status(self, task: TaskState) -> dict:
        return dict(self.current_status.get(task.task_id, {"status": "idle", "reported": self._caps["can_report_status"], "gone": False}))


class _SelfHostedBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.clock = FakeClock()
        self.repo = self.root / "alpha"
        self.base_sha = _init_repo(self.repo)
        self.slug = project_slug(self.repo)
        self.clone = self.root / "node-clones" / "alpha"
        subprocess.run(["git", "clone", "--quiet", str(self.repo), str(self.clone)], check=True)
        self.sim = SimHc(self.root / "sim", clock=self.clock)
        self.sim.add_term("t1")
        self.ctx = make_ctx(
            self.root / "home",
            clock=self.clock,
            git=GitRepo(worktree_base=self.root / "local-wt"),
            hc=HcHost(runner=self.sim, clock=self.clock),
            pane="hc:t1",
            hc_terminal="t1",
            env={"HOME": str(self.root / "user-home"), "PM_HOME": str(self.root / "home")},
            config={"experimental": {"remote_workers": True}},
        )
        self.ctx.store.change_registration(
            self.slug,
            lambda _: {"project": self.slug, "repo": str(self.repo), "pane": "hc:t1", "terminal": "t1"},
        )
        self.brief_file = self.root / "brief.md"
        self.brief_file.write_text("# Task\nImplement feature X.\n", encoding="utf-8")

    def _enroll_and_join(self, alias: str = "gpu-box", *, projects: list[str] | None = None,
                         client=None, state_dir: Path | None = None, driver=None) -> tuple[dict, Path, WorkerAgent]:
        reg = NodeRegistry(self.ctx.home.tokens, clock=self.clock)
        enr = reg.enroll(alias, projects or [self.slug])
        hub = SyncHub(self.ctx)
        cli_client = client or InProcessHubClient(hub)
        st = state_dir or (self.root / "agent-state" / alias)
        drv = driver or _ScriptedDriver()
        joined = agent_join(
            st, cli_client, enr.token, hub="in-process",
            repos={self.slug: str(self.clone)},
            worktrees=str(self.root / "node-wt" / alias),
            capabilities=drv.capabilities(),
        )
        agent = WorkerAgent(st, cli_client, drv, clock=self.clock)
        return joined, st, agent

    def _worker_ctx(self, task_dir: Path):
        return make_ctx(
            self.root / "no-ledger-on-node",
            clock=self.clock,
            git=GitRepo(),
            env={"PM_WORKER_STATE": str(task_dir)},
        )


class TestEnrollmentAuthRevocation(_SelfHostedBase):
    """§8.3: enroll -> join -> auth -> revoke, single-use & expired tokens, replay, clock skew, 0600 perms."""

    def test_enroll_token_hashed_single_use_expired_and_revoked(self) -> None:
        reg = NodeRegistry(self.ctx.home.tokens, clock=self.clock)
        enr = reg.enroll("edge-1", [self.slug], ttl_s=120.0)
        self.assertTrue(enr.token.startswith("enroll_"))
        self.assertGreaterEqual(len(enr.token), 7 + 64)

        # Plaintext token must NEVER appear in workers.json; only SHA-256 hash.
        raw_workers = reg.path.read_text(encoding="utf-8")
        self.assertNotIn(enr.token, raw_workers)
        self.assertIn(token_digest(enr.token), raw_workers)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(reg.path.stat().st_mode), 0o600)

        hub = SyncHub(self.ctx)
        client = InProcessHubClient(hub)
        st = self.root / "edge-1-state"
        joined = agent_join(st, client, enr.token, hub="http://127.0.0.1:0", capabilities=FileDriver().capabilities())
        node_id = joined["node_id"]
        cred_path = st / CREDENTIAL
        self.assertTrue(cred_path.is_file())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(cred_path.stat().st_mode), 0o600)

        # Single-use: reusing the same enroll token must fail with token_used.
        with self.assertRaises(AgentError) as reused:
            agent_join(self.root / "edge-1-reuse", client, enr.token, hub="http://127.0.0.1:0")
        self.assertIn("token_used", str(reused.exception))

        # Expired token must fail with token_expired.
        enr_exp = reg.enroll("edge-exp", [self.slug], ttl_s=60.0)
        self.clock.advance(65.0)
        with self.assertRaises(AgentError) as expired:
            agent_join(self.root / "edge-exp-state", client, enr_exp.token, hub="http://127.0.0.1:0")
        self.assertIn("token_expired", str(expired.exception))

        # Valid signed sync works; bad signature, clock skew, and nonce replay are rejected.
        cred = json.loads(cred_path.read_text(encoding="utf-8"))
        now_ms = int(self.clock.time() * 1000)
        req = signed_request(cred, {"op": "sync", "inbox_after": 0}, now_ms=now_ms)
        self.assertTrue(hub.handle(req)["ok"])

        # Replay of exact same nonce is rejected.
        replay_reply = hub.handle(req)
        self.assertFalse(replay_reply["ok"])
        self.assertEqual(replay_reply["error"]["code"], "replay")

        # Tampered signature is rejected.
        bad_sig = signed_request(cred, {"op": "sync", "inbox_after": 0}, now_ms=now_ms)
        bad_sig["auth"]["sig"] = "0" * 64
        self.assertEqual(hub.handle(bad_sig)["error"]["code"], "bad_signature")

        # Clock skew > 300s is rejected.
        skew = signed_request(cred, {"op": "sync", "inbox_after": 0}, now_ms=now_ms + 400_000)
        self.assertEqual(hub.handle(skew)["error"]["code"], "clock_skew")

        # Immediate revocation rejects subsequent sync with authz_denied and marks agent revoked.
        reg.revoke("edge-1")
        agent = WorkerAgent(st, client, FileDriver(), clock=self.clock)
        cyc = agent.run_once(force=True)
        self.assertTrue(cyc.revoked)
        self.assertIn("authz_denied", cyc.error)

        # Direct hub call also returns authz_denied.
        after_rev = signed_request(cred, {"op": "sync", "inbox_after": 0}, now_ms=now_ms)
        rev_reply = hub.handle(after_rev)
        self.assertFalse(rev_reply["ok"])
        self.assertEqual(rev_reply["error"]["code"], "authz_denied")
        self.assertEqual(SelfHostedPullTransport(self.ctx).link_state(
            Endpoint(runtime="self_hosted", machine=node_id, terminal="s1")
        ), "unauthorized")

    def test_project_scope_enforced_at_dispatch_and_sync(self) -> None:
        joined, _st, _agent = self._enroll_and_join("scoped-node", projects=["other-project"])
        with self.assertRaises(Refused) as err:
            Workers(self.ctx).dispatch(DispatchRequest(
                title="Unauthorized project", repo=str(self.repo), branch="dev/scoped",
                brief=str(self.brief_file), on="scoped-node",
            ))
        self.assertIn("not authorized", str(err.exception))


class TestIsomorphicHttpAndStdioCarriers(_SelfHostedBase):
    """MR-D2: HTTP (`POST /v1/worker/sync` & WSGI) and SSH stdio (`pm.py mailbox-sync --stdio`) carry identical JSON."""

    def test_http_wsgi_and_stdio_identical_sync_matrix(self) -> None:
        hub = SyncHub(self.ctx)
        # 1. Start local loopback HTTP server on ephemeral port.
        srv = serve_http(hub, host="127.0.0.1", port=0, serve=False)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), thread.join(timeout=5)))

        http_client = HttpHubClient(f"http://127.0.0.1:{port}")
        reg = NodeRegistry(self.ctx.home.tokens, clock=self.clock)

        # Join & sync over HTTP.
        enr_http = reg.enroll("http-node", [self.slug])
        st_http = self.root / "st-http"
        agent_join(st_http, http_client, enr_http.token, hub=f"http://127.0.0.1:{port}",
                   repos={self.slug: str(self.clone)}, capabilities=_ScriptedDriver().capabilities())
        drv_http = _ScriptedDriver()
        agent_http = WorkerAgent(st_http, http_client, drv_http, clock=self.clock)

        # Join & sync over stdio (`serve_stdio` in-memory pipe + real `StdioHubClient` subprocess).
        enr_stdio = reg.enroll("stdio-node", [self.slug])
        st_stdio = self.root / "st-stdio"
        stdio_env = {**os.environ, "PM_HOME": str(self.ctx.home.root), "PM_NO_DISCORD": "1",
                     "PYTHONDONTWRITEBYTECODE": "1"}
        stdio_argv = [sys.executable, str(SCRIPTS / "pm.py"), "mailbox-sync", "--stdio"]
        # Use a real clock for subprocess comparison since subprocess uses wall clock.
        real_reg = NodeRegistry(self.ctx.home.tokens)
        enr_sub = real_reg.enroll("sub-stdio", [self.slug])
        stdio_client = StdioHubClient(stdio_argv, env=stdio_env)
        joined_sub = agent_join(st_stdio, stdio_client, enr_sub.token, hub="ssh-host", hub_command=stdio_argv,
                                repos={self.slug: str(self.clone)}, capabilities=_ScriptedDriver().capabilities())
        drv_stdio = _ScriptedDriver()
        agent_stdio = WorkerAgent(st_stdio, stdio_client, drv_stdio)  # wall clock matches subprocess

        # Dispatch one task to each node and verify both pull cmd.brief, commit, report, and apply identically.
        for alias, agent, drv, branch in (
            ("http-node", agent_http, drv_http, "dev/http-task"),
            ("sub-stdio", agent_stdio, drv_stdio, "dev/stdio-task"),
        ):
            res = Workers(self.ctx).dispatch(DispatchRequest(
                title=f"Work on {alias}", repo=str(self.repo), branch=branch,
                brief=str(self.brief_file), on=alias,
            ))
            cyc1 = agent.run_once(force=True)
            self.assertTrue(cyc1.ok, cyc1.error)
            self.assertEqual(cyc1.pulled, 1)
            self.assertEqual(cyc1.handled, 1)
            self.assertEqual([t for t, _ in drv.started], [res.task_id])

            ts = agent.task(res.task_id, 1)
            self.assertIsNotNone(ts)
            assert ts is not None
            wt = Path(ts.worktree)
            self.assertTrue(wt.is_dir())
            (wt / f"{alias}.txt").write_text("done\n", encoding="utf-8")
            _git(wt, "add", f"{alias}.txt")
            _git(wt, "commit", "-m", f"work on {alias}")
            commit_sha = _git(wt, "rev-parse", "HEAD")

            wctx = self._worker_ctx(ts.dir)
            ReportClient(wctx).submit(task_update_report(
                wctx, UpdateRequest(id=res.task_id, status="review", commit=commit_sha, note=f"ready from {alias}")
            ))
            cyc2 = agent.run_once(force=True)
            self.assertTrue(cyc2.ok, cyc2.error)
            self.assertEqual(cyc2.applied, 1)

            task = Ledger(self.ctx).load(res.task_id).raw
            self.assertEqual(task["status"], "review")
            self.assertEqual(task["commit"], commit_sha)
            # Bundle uploaded and fast-forwardable into coordinator repo.
            fetched = SelfHostedWorkspace(self.ctx).fetch_branch(task)
            self.assertEqual(fetched, commit_sha)

        # Verify WSGI callable and serve_stdio return byte-identical JSON structure for same request schema.
        cred_http = json.loads((st_http / CREDENTIAL).read_text(encoding="utf-8"))
        req1 = signed_request(cred_http, {"op": "sync", "inbox_after": 1}, now_ms=int(self.clock.time() * 1000))
        req2 = signed_request(cred_http, {"op": "sync", "inbox_after": 1}, now_ms=int(self.clock.time() * 1000))

        # WSGI call
        app = wsgi_app(hub)
        raw1 = json.dumps(req1).encode("utf-8")
        statuses: list[str] = []
        body_wsgi = b"".join(app({
            "REQUEST_METHOD": "POST", "PATH_INFO": "/v1/worker/sync",
            "CONTENT_LENGTH": str(len(raw1)), "wsgi.input": io.BytesIO(raw1),
        }, lambda st, _h: statuses.append(st)))
        self.assertEqual(statuses, ["200 OK"])

        # serve_stdio call
        stdio_out: list[str] = []
        served = serve_stdio(hub, [json.dumps(req2) + "\n"], stdio_out.append)
        self.assertEqual(served, 1)
        self.assertEqual(set(json.loads(body_wsgi).keys()), set(json.loads(stdio_out[0]).keys()))
        self.assertEqual(json.loads(body_wsgi)["ok"], True)
        self.assertEqual(json.loads(stdio_out[0])["ok"], True)
        self.assertTrue(joined_sub["node_id"].startswith("node_"))


class TestPartitionReplayAndStaleEpoch(_SelfHostedBase):
    """I4 partition -> unknown (no stalls), offline buffering & idempotent replay, MR-D4 stale-epoch archive + P4."""

    def test_offline_partition_buffering_duplicate_push_and_reconnect(self) -> None:
        hub = SyncHub(self.ctx)
        client = InProcessHubClient(hub)
        drv = _ScriptedDriver()
        joined, _st, agent = self._enroll_and_join("part-node", client=client, driver=drv)
        node_id = joined["node_id"]

        res = Workers(self.ctx).dispatch(DispatchRequest(
            title="Partition resilience", repo=str(self.repo), branch="dev/part",
            brief=str(self.brief_file), on="part-node",
        ))
        tid = res.task_id
        self.assertTrue(agent.run_once(force=True).ok)
        ep = self_hosted_endpoint(Ledger(self.ctx).load(tid).raw)
        assert ep is not None
        ts = agent.task(tid, 1)
        assert ts is not None

        # Partition begins: network drops, clock advances 60 minutes (well past 30s lease).
        client.online = False
        self.clock.advance(3600.0)

        # Coordinator observes health: "unknown", link_state: "disconnected", ZERO stalls, live_worker stays non-empty.
        tr = SelfHostedPullTransport(self.ctx)
        batch = tr.observe(ep, {})
        self.assertEqual(batch.link_state, "disconnected")
        self.assertEqual(batch.observations[0]["health"], "unknown")
        self.assertTrue(live_worker_for(self.ctx, Ledger(self.ctx).load(tid).raw))

        stalls = StallWatcher(self.ctx)
        stalls.watch_workers([Ledger(self.ctx).load(tid).raw], {})
        snap = EndpointTurnStore(self.ctx, ep, repo=str(self.repo)).read()
        self.assertEqual(snap["turn"]["health"], "unknown")
        self.assertNotEqual(snap["turn"]["health"], "stalled")

        # While partitioned: PM sends a message -> stays queued in mailbox; agent backs off exponentially.
        Workers(self.ctx).send(tid, "please also add edge case test")
        c_off1 = agent.run_once(force=True)
        self.assertTrue(c_off1.offline)
        self.assertEqual(c_off1.next_s, 2.0)
        c_off2 = agent.run_once(force=True)
        self.assertTrue(c_off2.offline)
        self.assertEqual(c_off2.next_s, 4.0)

        # Worker runs two reports while completely offline (buffered in local outbox.jsonl).
        wctx = self._worker_ctx(ts.dir)
        ReportClient(wctx).submit(task_log_report(wctx, tid, "offline progress 1"))
        ReportClient(wctx).submit(task_update_report(wctx, UpdateRequest(id=tid, status="review", note="offline done")))
        # Ledger still has NOT changed while offline.
        self.assertEqual(Ledger(self.ctx).load(tid).raw["status"], "in_progress")

        # Reconnect, but simulate dropped response on first sync (hub applies, client misses reply -> resends same seqs).
        client.online = True
        saved_agent_state = agent.agent()
        cyc_first = agent.run_once(force=True)
        self.assertTrue(cyc_first.ok)
        self.assertEqual(cyc_first.applied, 2)
        self.assertEqual(Ledger(self.ctx).load(tid).raw["status"], "review")
        log_count_after_first = len(Ledger(self.ctx).load(tid).raw["log"])

        # Rewind agent cursors to simulate the reply having been dropped on the wire, and replay!
        agent._save_agent(saved_agent_state)
        cyc_replay = agent.run_once(force=True)
        self.assertTrue(cyc_replay.ok)
        # Zero duplicate report applications!
        self.assertEqual(cyc_replay.applied, 0)
        self.assertTrue(all(r["already_applied"] for r in cyc_replay.receipts))
        self.assertEqual(len(Ledger(self.ctx).load(tid).raw["log"]), log_count_after_first)
        # And the PM's queued message arrived exactly once (never delivered twice due to delivered.json dedup).
        cmd_sends = [e for _, e, k in drv.delivered if k == "cmd.send"]
        self.assertEqual(len(cmd_sends), 1)
        self.assertEqual(tr.link_state(ep), "connected")
        self.assertEqual(node_id, ep.machine)

    def test_stale_epoch_report_archives_and_emits_p4_summary_mr_d4(self) -> None:
        hub = SyncHub(self.ctx)
        client = InProcessHubClient(hub)
        _j1, _s1, agent1 = self._enroll_and_join("node-old", client=client)
        _j2, _s2, agent2 = self._enroll_and_join("node-new", client=client)

        # Dispatch epoch 1 to node-old; node-old pulls it.
        res1 = Workers(self.ctx).dispatch(DispatchRequest(
            title="Stale epoch task", repo=str(self.repo), branch="dev/stale",
            brief=str(self.brief_file), on="node-old",
        ))
        tid = res1.task_id
        self.assertTrue(agent1.run_once(force=True).ok)
        ts1 = agent1.task(tid, 1)
        assert ts1 is not None

        # node-old goes offline and finishes work locally on epoch 1.
        wctx1 = self._worker_ctx(ts1.dir)
        ReportClient(wctx1).submit(task_update_report(
            wctx1, UpdateRequest(id=tid, status="review", commit="deadbeef", note="finished offline on epoch 1")
        ))

        # Meanwhile PM moves the task to node-new (epoch 2). First mark old slot gone or advance endpoint via dispatch.
        NodeStreams(self.ctx.home.nodes, _j1["node_id"]).set_slot(ts1.slot, gone=True)
        Workers(self.ctx).dispatch(DispatchRequest(
            task=tid, repo=str(self.repo), branch="dev/stale",
            brief=str(self.brief_file), on="node-new",
        ))
        task_e2 = Ledger(self.ctx).load(tid).raw
        self.assertEqual(task_e2["endpoint"]["epoch"], 2)
        self.assertEqual(task_e2["status"], "in_progress")
        self.assertTrue(agent2.run_once(force=True).ok)

        # Now node-old reconnects and pushes its epoch 1 review report!
        cyc_old = agent1.run_once(force=True)
        self.assertTrue(cyc_old.ok)
        self.assertTrue(any(r.get("late_report") for r in cyc_old.receipts))

        # MR-D4: task status remains in_progress (epoch 2 untouched), late report archived in task log, P4 event queued.
        after = Ledger(self.ctx).load(tid).raw
        self.assertEqual(after["status"], "in_progress")
        self.assertEqual(after["endpoint"]["epoch"], 2)
        late_logs = [entry for entry in after["log"] if entry.get("late_report")]
        self.assertEqual(len(late_logs), 1)
        self.assertIn("deadbeef", late_logs[0]["text"])
        self.assertIn("finished offline on epoch 1", late_logs[0]["text"])

        pm_mb = MailboxStore(self.ctx.home.project_for(self.repo).pm_mailbox, clock=self.clock)
        late_envs = [it for it in pm_mb.active_items() if it.envelope.kind == "event.late_report"]
        self.assertEqual(len(late_envs), 1)
        self.assertEqual(late_envs[0].envelope.priority, 4)

    def test_reconcile_task_endpoint_moves_self_hosted_to_history(self) -> None:
        raw = {
            "id": "alpha-1",
            "pane": "hc:t9",
            "self_hosted": {"node_id": "node_abc", "alias": "n1", "slot": "s1", "epoch": 1},
            "endpoint": {"runtime": "self_hosted", "machine": "node_abc", "terminal": "s1", "epoch": 1},
        }
        reconcile_task_endpoint(raw)
        self.assertNotIn("self_hosted", raw)
        self.assertEqual(len(raw["self_hosted_history"]), 1)
        self.assertEqual(raw["endpoint"]["runtime"], "hc")
        self.assertEqual(raw["endpoint"]["epoch"], 2)


class TestPrivacyBoundaryAndMergeAndInterrupt(_SelfHostedBase):
    """§6.5 privacy boundary, MR-D1 coordinator-local merge, §11.5 can_interrupt=False, closed task grant drop."""

    def test_section_6_5_privacy_boundary_and_offline_recall(self) -> None:
        # Seed: (1) project memory, (2) private personal feedback memory, (3) private user memory,
        # (4) explicitly allowed personal feedback memory, (5) another project's memory.
        MemoryLayer(self.ctx, self.repo).remember(
            "Alpha architecture note", writer=("pm", "pm"), kind="project", name="alpha-arch", body="Alpha detail",
            verified="unit test",
        )
        MemoryLayer(self.ctx, None).remember(
            "Private personal preference", writer=("user", "user"), kind="feedback", name="priv-pref", body="SECRET_PERSONAL",
            verified="unit test",
        )
        MemoryLayer(self.ctx, None).remember(
            "User private bio", writer=("user", "user"), kind="user", name="priv-user", body="SECRET_USER_BIO",
            verified="unit test",
        )
        MemoryLayer(self.ctx, None).remember(
            "Shared coding rule", writer=("user", "user"), kind="feedback", name="shared-rule", body="ALLOWED_SHARED",
            verified="unit test",
        )
        other_repo = self.root / "beta"
        _init_repo(other_repo)
        MemoryLayer(self.ctx, other_repo).remember(
            "Beta secret", writer=("pm", "pm"), kind="project", name="beta-secret", body="SECRET_BETA",
            verified="unit test",
        )
        # Allowlist includes both `shared-rule` (allowed) and `priv-user` (MUST still be excluded because type=='user').
        self.ctx.home.config.write_text(json.dumps({
            "self_hosted": {"share_personal_memories": ["shared-rule", "priv-user"]},
            "experimental": {"remote_workers": True},
        }), encoding="utf-8")

        _joined, _st, agent = self._enroll_and_join("priv-node")
        res = Workers(self.ctx).dispatch(DispatchRequest(
            title="Check privacy", repo=str(self.repo), branch="dev/priv",
            brief=str(self.brief_file), on="priv-node",
        ))
        self.assertTrue(agent.run_once(force=True).ok)
        ts = agent.task(res.task_id, 1)
        assert ts is not None
        ctx_json = json.loads((ts.dir / "context.json").read_text(encoding="utf-8"))
        dumped = json.dumps(ctx_json, ensure_ascii=False)

        # Project memory & explicitly allowlisted non-user memory are present.
        names = {m["name"] for m in ctx_json["memories"]}
        self.assertIn("alpha-arch", names)
        self.assertIn("shared-rule", names)
        # Private personal, `user` type, other project, and coordinator repo path are NEVER present.
        self.assertNotIn("priv-pref", names)
        self.assertNotIn("priv-user", names)
        self.assertNotIn("beta-secret", names)
        self.assertNotIn("SECRET_PERSONAL", dumped)
        self.assertNotIn("SECRET_USER_BIO", dumped)
        self.assertNotIn("SECRET_BETA", dumped)
        self.assertNotIn(str(self.repo), dumped)

        # Brief also omits private personal memories.
        brief_text = self_hosted_brief(self.ctx, Ledger(self.ctx).load(res.task_id).raw, "Do work.", "pm.py")
        self.assertIn("alpha-arch", brief_text)
        self.assertNotIn("priv-pref", brief_text)
        self.assertNotIn("priv-user", brief_text)
        self.assertNotIn("beta-secret", brief_text)

        # What actually crossed the wire: the node's stored pull queue (the dispatched cmd.brief and all) carries the
        # project memory index and nothing private, no other project, no coordinator path.
        wire = (_st / "inbox.jsonl").read_text(encoding="utf-8")
        briefs = [json.loads(line)["envelope"] for line in wire.splitlines()
                  if (json.loads(line).get("envelope") or {}).get("kind") == "cmd.brief"]
        self.assertEqual(len(briefs), 1)
        sent_text = briefs[0]["body"]["text"]
        self.assertIn("Implement feature X.", sent_text)
        self.assertIn("alpha-arch", sent_text)
        for leak in ("priv-pref", "priv-user", "beta-secret", "SECRET_PERSONAL", "SECRET_USER_BIO", "SECRET_BETA",
                     str(self.repo), str(self.ctx.home.root)):
            self.assertNotIn(leak, wire)

        # Offline `pm.py recall` works purely from `<worker_state>/context.json` with no ledger on the node.
        wctx = self._worker_ctx(ts.dir)
        cli.main(["recall", "alpha-arch"], ctx=wctx)
        self.assertIn("Alpha detail", wctx.out.stdout)

    def test_mr_d1_approve_defaults_to_helper_refuses_via_worker_and_closed_drops_grant(self) -> None:
        hub = SyncHub(self.ctx)
        client = InProcessHubClient(hub)
        drv = _ScriptedDriver()
        joined, _st, agent = self._enroll_and_join("land-node", client=client, driver=drv)
        node_id = joined["node_id"]

        res = Workers(self.ctx).dispatch(DispatchRequest(
            title="Land via helper", repo=str(self.repo), branch="dev/land-sh",
            brief=str(self.brief_file), on="land-node",
        ))
        tid = res.task_id
        self.assertTrue(agent.run_once(force=True).ok)
        ts = agent.task(tid, 1)
        assert ts is not None
        wt = Path(ts.worktree)
        (wt / "feature.txt").write_text("hi\n", encoding="utf-8")
        _git(wt, "add", "feature.txt")
        _git(wt, "commit", "-m", "add feature")
        sha = _git(wt, "rev-parse", "HEAD")

        wctx = self._worker_ctx(ts.dir)
        ReportClient(wctx).submit(task_update_report(
            wctx, UpdateRequest(id=tid, status="review", commit=sha, note="ready to merge")
        ))
        self.assertTrue(agent.run_once(force=True).ok)

        # Review checkout works on self-hosted task (detached local checkout of uploaded bundle).
        rev_wt = SelfHostedWorkspace(self.ctx).review_checkout(
            Ledger(self.ctx).load(tid).raw,
            SelfHostedWorkspace(self.ctx).fetch_branch(Ledger(self.ctx).load(tid).raw),
        )
        self.assertTrue((Path(rev_wt) / "feature.txt").is_file())

        # MR-D1: `--via worker` is refused for self-hosted tasks.
        with self.assertRaises(Refused) as err:
            Landing(self.ctx).approve(ApproveRequest(id=tid, via="worker"))
        self.assertIn("land-node", str(err.exception))

        # Default `approve` uses coordinator-local helper and queues notification to the self-hosted worker.
        done = Landing(self.ctx).approve(ApproveRequest(id=tid))
        joined_out = "\n".join(text for _s, text in done.said)
        self.assertIn("exec helper", joined_out)
        cyc_notify = agent.run_once(force=True)
        self.assertTrue(cyc_notify.ok)
        self.assertTrue(any(k == "cmd.send" for _, _, k in drv.delivered))

        # Closing the task drops the node's grant and refuses any later reports with authz_denied.
        Updates(self.ctx).update(UpdateRequest(id=tid, status="done", note="completed"))
        reg = NodeRegistry(self.ctx.home.tokens, clock=self.clock)
        self.assertEqual(NodeRegistry.granted_epochs(reg.get(node_id), tid), [])
        ReportClient(wctx).submit(task_log_report(wctx, tid, "after close"))
        cyc_after = agent.run_once(force=True)
        self.assertTrue(cyc_after.ok)
        self.assertEqual(cyc_after.rejected, 1)
        self.assertEqual(cyc_after.receipts[0]["code"], "authz_denied")

    def test_can_interrupt_false_honest_unsupported_and_true_queues_ctrl(self) -> None:
        hub = SyncHub(self.ctx)
        client = InProcessHubClient(hub)
        # Non-interruptible node (§11.5)
        drv_no = _ScriptedDriver(can_interrupt=False, can_unblock_keys=False)
        _j1, _s1, agent_no = self._enroll_and_join("batch-node", client=client, driver=drv_no)
        r1 = Workers(self.ctx).dispatch(DispatchRequest(
            title="Batch job", repo=str(self.repo), branch="dev/batch",
            brief=str(self.brief_file), on="batch-node",
        ))
        self.assertTrue(agent_no.run_once(force=True).ok)
        ep1 = self_hosted_endpoint(Ledger(self.ctx).load(r1.task_id).raw)
        assert ep1 is not None
        tr = SelfHostedPullTransport(self.ctx)
        self.assertFalse(tr.capabilities(ep1).can_interrupt)
        self.assertEqual(tr.interrupt(ep1).status, "unsupported")
        self.assertFalse(tr.unblock_prompt(ep1, ["Enter"]))

        # Interruptible node queues ctrl.interrupt & agent executes it and reports observation.
        drv_yes = _ScriptedDriver(can_interrupt=True, can_unblock_keys=True)
        _j2, _s2, agent_yes = self._enroll_and_join("live-node", client=client, driver=drv_yes)
        r2 = Workers(self.ctx).dispatch(DispatchRequest(
            title="Live job", repo=str(self.repo), branch="dev/live",
            brief=str(self.brief_file), on="live-node",
        ))
        self.assertTrue(agent_yes.run_once(force=True).ok)
        ep2 = self_hosted_endpoint(Ledger(self.ctx).load(r2.task_id).raw)
        assert ep2 is not None
        self.assertTrue(tr.capabilities(ep2).can_interrupt)
        self.assertEqual(tr.interrupt(ep2).status, "unknown")
        self.assertTrue(tr.unblock_prompt(ep2, ["Enter"]))
        self.assertTrue(agent_yes.run_once(force=True).ok)
        self.assertEqual(drv_yes.interrupts, [r2.task_id])
        self.assertEqual(drv_yes.keys_sent, [(r2.task_id, ["Enter"])])
        # Next sync pushes the interrupt_outcome and keys_sent observations to coordinator.
        self.assertTrue(agent_yes.run_once(force=True).ok)
        obs = tr.observe(ep2, {})
        kinds = [o.get("kind") for o in obs.observations]
        self.assertIn("interrupt_outcome", kinds)
        self.assertIn("keys_sent", kinds)


class TestWorkerCliCommands(_SelfHostedBase):
    """CLI surface: `pm.py worker enroll|join|list|revoke` + `pm.py worker-agent --once`."""

    def test_cli_enroll_join_list_agent_and_revoke(self) -> None:
        hub = SyncHub(self.ctx)
        srv = serve_http(hub, host="127.0.0.1", port=0, serve=False)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), thread.join(timeout=5)))
        hub_url = f"http://127.0.0.1:{port}"

        # 1. `pm.py worker enroll`
        self.ctx.out.clear()
        cli.main(["worker", "enroll", "--name", "cli-node", "--projects", self.slug, "--ttl", "10m", "--hub", hub_url, "--json"],
                 ctx=self.ctx)
        enr = json.loads(self.ctx.out.stdout)
        self.assertTrue(enr["token"].startswith("enroll_"))
        self.assertIn(enr["token"], enr["join_command"])

        # 2. `pm.py worker join`
        st = self.root / "cli-agent-state"
        self.ctx.out.clear()
        cli.main(["worker", "join", "--hub", hub_url, "--token", enr["token"], "--state", str(st),
                  "--repo", f"{self.slug}={self.clone}", "--driver", "file", "--json"], ctx=self.ctx)
        joined = json.loads(self.ctx.out.stdout)
        self.assertEqual(joined["alias"], "cli-node")

        # 3. `pm.py worker-agent --once`
        self.ctx.out.clear()
        cli.main(["worker-agent", "--state", str(st), "--once", "--driver", "file", "--json"], ctx=self.ctx)
        cyc = json.loads(self.ctx.out.stdout)
        self.assertTrue(cyc["ok"])

        # 4. `pm.py worker list --json`
        self.ctx.out.clear()
        cli.main(["worker", "list", "--json"], ctx=self.ctx)
        rows = json.loads(self.ctx.out.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["alias"], "cli-node")
        self.assertEqual(rows[0]["link_state"], "connected")
        self.assertNotIn("secret", rows[0])

        # 5. `pm.py worker revoke`
        self.ctx.out.clear()
        cli.main(["worker", "revoke", "cli-node", "--json"], ctx=self.ctx)
        rev = json.loads(self.ctx.out.stdout)
        self.assertTrue(rev["revoked_ms"] > 0)
        self.assertNotIn("secret", rev)

        # 6. `pm.py worker-agent --once` after revoke exits with code 2.
        self.ctx.out.clear()
        with self.assertRaises(SystemExit) as sysexit:
            cli.main(["worker-agent", "--state", str(st), "--once", "--driver", "file", "--json"], ctx=self.ctx)
        self.assertEqual(sysexit.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
