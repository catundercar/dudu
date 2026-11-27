"""Phase 3b wave 3: one typist per worker / reviewer / helper terminal (`pmlib/messaging/typist.py`).

Every keystroke into such a terminal goes through its own mailbox and the shared per-endpoint typist lease: queued
sends are typed once by whoever holds the lease, a sender that cannot get it waits instead of typing over another,
prompt keys are pressed only under the lease, and an interrupt is a `ctrl.interrupt` envelope.
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.stalls import StallWatcher  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.messaging.address import Endpoint, LogicalAddress  # noqa: E402
from pmlib.messaging.envelope import P0_CONTROL  # noqa: E402
from pmlib.messaging.principal import Principal  # noqa: E402
from pmlib.messaging.transport import InterruptOutcome  # noqa: E402
from pmlib.messaging.transports.fake import FakeTransport  # noqa: E402
from pmlib.messaging.transports.local_hc import LocalHcTransport  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.terminals.hc import HcHost  # noqa: E402
from pmlib.messaging.typist import (  # noqa: E402
    DRAIN_MAX_AGE_S,
    drain_endpoint,
    endpoint_mailbox,
    enqueue_for_endpoint,
    interrupt_endpoint,
    type_item_locked,
    unblock_endpoint,
)
from pmlib.workers.send import send_when_ready_for, terminal_envelope, worker_endpoint  # noqa: E402
from pmlib.workers.service import Workers  # noqa: E402
from tests.fakes import FakeClock, FakeHc, make_ctx, queued_sends, run_spawned_drains  # noqa: E402


# A stand-in for the hc binary that parses `send` as the real one (clap) does: an argument starting with "-" that is no
# known option is a usage error unless it comes after `--` (review of 9cc5b05: `hc send <term> <text>` had no `--`).
CLAP_LIKE_HC = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    argv = sys.argv[1:]
    cmd, rest = (argv[0] if argv else ""), argv[1:]
    pos, raw, i = [], False, 0
    while i < len(rest):
        a = rest[i]
        if raw: pos.append(a)
        elif a == "--": raw = True
        elif a in ("--json", "--force", "--wait"): pass
        elif a in ("--if", "--timeout"): i += 1
        elif a.startswith("-"):
            sys.stderr.write(json.dumps({"error": {"kind": "usage", "message": "unexpected argument %r" % a[:2]}}))
            sys.exit(2)
        else: pos.append(a)
        i += 1
    if cmd == "get":
        print(json.dumps({"address": pos[0], "state": "live", "status": {"state": "idle"}, "turn": 3, "status_ms": 1}))
    elif cmd == "send":
        with open(os.environ["CLAP_LIKE_HC_LOG"], "a") as f:
            f.write(json.dumps(pos) + "\\n")
        print(json.dumps({"ok": True, "started": True, "status": {"state": "working"}}))
    else:
        sys.stderr.write(json.dumps({"error": {"kind": "not_found", "message": cmd}})); sys.exit(3)
''')


class _HookedClock(FakeClock):
    """A FakeClock that runs `on_sleep(n)` on each sleep: what another process does while a sender waits."""

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.on_sleep = None
        self.n = 0

    def sleep(self, seconds: float) -> None:
        super().sleep(seconds)
        self.n += 1
        if self.on_sleep is not None:
            self.on_sleep(self.n)


class EndpointTypistTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = _HookedClock("2026-11-26 10:00:00", mono=100.0)
        self.hc = FakeHc(terminals={
            "t20": {"state": "live", "status": {"state": "idle"}, "turn": 4},
        }, clock=self.clock)
        self.ctx = make_ctx(self._tmp.name, hc=self.hc, clock=self.clock)
        self.ep = worker_endpoint("t20")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _env(self, text: str, **kw):
        return terminal_envelope(self.ctx, text, target="t20", **kw)

    def _hold_lease(self, owner: str = "other:1") -> None:
        mb = endpoint_mailbox(self.ctx, self.ep)
        self.assertTrue(mb.acquire_typist_lease(self.ep.uid, 4242, ttl_ms=75_000,
                                                now_ms=int(self.clock.time() * 1000), owner=owner))

    def _release_lease(self, owner: str = "other:1") -> None:
        endpoint_mailbox(self.ctx, self.ep).release_typist_lease(self.ep.uid, 4242, owner=owner)

    # --- mailbox delivery ---

    def test_a_queued_send_is_typed_once_by_its_drain_and_never_again(self) -> None:
        res = Workers(self.ctx).send("t20", "look at the logs")
        self.assertTrue(res.queued)
        self.assertEqual(self.hc.sent, [])  # nothing typed by the sender itself
        self.assertEqual(queued_sends(self.ctx), [("t20", "[from pm.py] look at the logs")])
        self.assertEqual(run_spawned_drains(self.ctx), 1)
        self.assertEqual(len(self.hc.sent), 1)
        self.assertRegex(self.hc.sent[0][1], r"^\[from pm\.py #env_[0-9a-f]+_[0-9a-f]+\] look at the logs$")
        # A second drain of the same envelope (a duplicate spawn) types nothing.
        env_id = self.ctx.procs.spawned[-1]["args"][3]
        Workers(self.ctx).drain_sends("t20", [env_id])
        self.assertEqual(len(self.hc.sent), 1)
        item = endpoint_mailbox(self.ctx, self.ep).get(env_id)
        self.assertEqual(item.state, "answered")
        self.assertIsNone(endpoint_mailbox(self.ctx, self.ep).typist_lease_holder(self.ep.uid))

    def test_the_same_idempotency_key_is_queued_and_typed_once(self) -> None:
        Workers(self.ctx).send("t20", "go", idempotency_key="ui:demo:m-1")
        Workers(self.ctx).send("t20", "go", idempotency_key="ui:demo:m-1")
        run_spawned_drains(self.ctx)
        self.assertEqual(len(self.hc.sent), 1)

    def test_a_sender_without_the_lease_waits_and_the_holder_types_its_envelope_once(self) -> None:
        ft = FakeTransport(clock=self.clock)
        mb, item = enqueue_for_endpoint(self.ctx, self.ep, self._env("second"))
        self._hold_lease()

        def holder_types_it(n: int) -> None:
            # The other process, still holding the lease, drains what was queued (ours included), then lets go.
            if n == 1:
                cur = mb.get(item.envelope.env_id)
                type_item_locked(self.ctx, mb, self.ep, cur, ft)
                self._release_lease()

        self.clock.on_sleep = holder_types_it
        res = drain_endpoint(self.ctx, self.ep, wait_for=[item.envelope.env_id], transport=ft, wait_s=30)
        self.assertEqual(res.typed, [])  # not typed by the waiting sender
        self.assertEqual([d["env_id"] for d in ft.deliveries], [item.envelope.env_id])  # typed exactly once
        self.assertFalse(res.waited_out)

    def test_a_lease_that_never_frees_fails_the_envelope_as_typist_busy(self) -> None:
        ft = FakeTransport(clock=self.clock)
        _mb, item = enqueue_for_endpoint(self.ctx, self.ep, self._env("stuck behind a draft"))
        self._hold_lease()
        self.clock.on_sleep = lambda n: self._hold_lease()  # the holder keeps renewing
        failed = []
        res = drain_endpoint(self.ctx, self.ep, wait_for=[item.envelope.env_id], transport=ft, wait_s=3,
                             on_failed=lambda it, out: failed.append((it.envelope.env_id, out.detail)))
        self.assertTrue(res.waited_out)
        self.assertEqual(ft.deliveries, [])
        self.assertEqual(failed, [(item.envelope.env_id, "typist_busy")])
        self.assertEqual(endpoint_mailbox(self.ctx, self.ep).get(item.envelope.env_id).state, "failed")

    def test_a_send_left_queued_by_a_dead_drain_expires_instead_of_going_in_late(self) -> None:
        ft = FakeTransport(clock=self.clock)
        _mb, old = enqueue_for_endpoint(self.ctx, self.ep, self._env("from an hour ago"))
        self.clock.advance(3600)
        _mb, new = enqueue_for_endpoint(self.ctx, self.ep, self._env("now"))
        failed = []
        res = drain_endpoint(self.ctx, self.ep, wait_for=[new.envelope.env_id], transport=ft,
                             on_failed=lambda it, out: failed.append((it.envelope.env_id, out.detail)))
        self.assertEqual([d["env_id"] for d in ft.deliveries], [new.envelope.env_id])
        self.assertEqual(failed, [(old.envelope.env_id, "expired")])
        self.assertEqual(endpoint_mailbox(self.ctx, self.ep).get(old.envelope.env_id).state, "expired")
        self.assertEqual(len(res.typed), 1)

    def test_a_synchronous_send_types_what_was_queued_before_it_and_runs_its_reactions(self) -> None:
        self.ctx.store.change_task("demo-1", lambda _: {
            "id": "demo-1", "title": "T", "repo": str(self._tmp.name), "status": "in_progress", "pane": "hc:t20",
            "log": [],
        })
        Workers(self.ctx).send("t20", "first", task_id="demo-1")  # queued; its drain has not run
        out = Workers(self.ctx).send("t20", "second", task_id="demo-1", wait=True)
        self.assertFalse(out.queued)
        self.assertEqual([t.split("] ", 1)[1] for _, t in self.hc.sent], ["first", "second"])
        # The queued one's reaction ran (its round was handed) although the synchronous sender typed it.
        self.assertEqual(self.ctx.store.task("demo-1")["round"]["turn"], 4)
        run_spawned_drains(self.ctx)  # its own drain finds nothing left to type
        self.assertEqual(len(self.hc.sent), 2)

    def test_an_idle_terminal_whose_turn_never_started_is_a_failed_send(self) -> None:
        class _NoStart(FakeHc):
            def send(self, term, text, **kw):
                super().send(term, text, **kw)
                return {"ok": True, "started": False, "status": {"state": "idle"}}

        hc = _NoStart(terminals={"t20": {"state": "live", "status": {"state": "idle"}, "turn": 4}}, clock=self.clock)
        ctx = make_ctx(self._tmp.name, hc=hc, clock=self.clock)
        failed = []
        ep = worker_endpoint("t20")
        enqueue_for_endpoint(ctx, ep, terminal_envelope(ctx, "approve", target="t20"))
        from pmlib.workers.send import took_in
        drain_endpoint(ctx, ep, accept=lambda it, o: took_in(ctx, ep, it, o),
                       on_failed=lambda it, o: failed.append(o.detail))
        self.assertEqual(failed, ["started_false"])

    def test_the_apps_own_words_go_in_as_written_and_a_failure_is_only_noted_on_the_thread(self) -> None:
        self.ctx.store.change_task("demo-1", lambda _: {
            "id": "demo-1", "title": "T", "repo": str(self._tmp.name), "status": "blocked", "pane": "hc:t20",
            "dispatched": True, "log": [{"at": "2026-11-26 09:00", "by": "hc:t20", "text": "status=blocked; which?"}],
        })
        Workers(self.ctx).send("t20", "- use the second one", task_id="demo-1", as_user=True)
        self.assertEqual(self.ctx.store.task("demo-1")["status"], "blocked")  # never "handled by the PM"
        rows = [r for r in endpoint_mailbox(self.ctx, self.ep).read_stream_after(0)[0] if r.get("rec") == "enq"]
        self.assertEqual((rows[-1]["env"]["kind"], rows[-1]["env"]["sender"]["role"]), ("chat.user", "user"))
        run_spawned_drains(self.ctx)
        self.assertEqual(self.hc.sent, [("t20", "- use the second one")])  # no [from …] line, no anchor
        # One that does not go in (a prompt holds the terminal): a note on the thread, no PM wake.
        self.hc.terminals["t20"]["status"] = {"state": "blocked"}
        orig = self.hc.send
        self.hc.send = lambda term, text, **kw: {"error": {"kind": "blocked", "message": "t20 is blocked"}}
        try:
            Workers(self.ctx).send("t20", "hello?", task_id="demo-1", as_user=True)
            run_spawned_drains(self.ctx)
        finally:
            self.hc.send = orig
        last = self.ctx.store.task("demo-1")["log"][-1]
        self.assertIn("was not delivered", last["text"])
        self.assertFalse(last.get("wake"))

    def test_hc_send_puts_the_terminal_and_text_after_double_dash(self) -> None:
        calls = []
        host = HcHost(None, runner=lambda *argv, **kw: calls.append(argv) or {"ok": True, "started": True})
        host.send("t20", "- item")
        host.send("t20", "--x", if_state="idle")
        self.assertEqual(calls, [("send", "--", "t20", "- item"), ("send", "--if", "idle", "--", "t20", "--x")])

    def test_the_users_words_starting_with_a_dash_reach_a_real_hc_binary(self) -> None:
        base = pathlib.Path(self._tmp.name)
        script, log = base / "hc", base / "typed.log"
        script.write_text(CLAP_LIKE_HC, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        os.environ["CLAP_LIKE_HC_LOG"] = str(log)
        self.addCleanup(os.environ.pop, "CLAP_LIKE_HC_LOG", None)
        ctx = make_ctx(str(base / "home"), clock=self.clock)
        ctx.hc = HcHost({"hc": str(script)})  # the production host: real argv to a binary
        for text in ("- use the second one", "--flag in a sentence", "-1"):
            self.assertFalse(Workers(ctx).send("t20", text, as_user=True, wait=True).queued)
        typed = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(typed, ['["t20", "- use the second one"]', '["t20", "--flag in a sentence"]', '["t20", "-1"]'])

    def test_a_waited_send_from_the_app_that_does_not_go_in_raises_for_the_window_to_show(self) -> None:
        from pmlib.errors import Refused
        orig = self.hc.send
        self.hc.send = lambda term, text, **kw: {"error": {"kind": "blocked", "message": "t20 is blocked"}}
        try:
            with self.assertRaises(Refused) as err:
                Workers(self.ctx).send("t20", "are you there?", as_user=True, wait=True, timeout=60)
        finally:
            self.hc.send = orig
        self.assertIn("t20 is blocked", str(err.exception))

    # --- control envelopes are never typed ---

    def test_a_drain_during_an_interrupt_never_types_the_interrupt(self) -> None:
        ctx = self.ctx
        ep = self.ep
        meanwhile = []

        class _DrainMeanwhile(LocalHcTransport):
            def interrupt(self, endpoint, *, timeout_s: float = 5.0):
                Workers(ctx).send("t20", "queued meanwhile")  # someone queues a send while hc interrupt runs
                meanwhile.append(drain_endpoint(ctx, endpoint))  # and its drain looks at the queue
                return super().interrupt(endpoint, timeout_s=timeout_s)

        out = interrupt_endpoint(ctx, ep, sender=Principal.pm("demo"), recipient=LogicalAddress.worker("demo-1", "demo"),
                                 project="demo", transport=_DrainMeanwhile(ctx))
        self.assertIsInstance(out, InterruptOutcome)
        self.assertEqual([t for _, t in self.hc.sent], [self.hc.sent[0][1]])  # only the queued text
        self.assertTrue(self.hc.sent[0][1].endswith("] queued meanwhile"))
        rows = [r for r in endpoint_mailbox(ctx, ep).read_stream_after(0)[0]
                if r.get("rec") == "enq" and r["env"]["kind"] == "ctrl.interrupt"]
        self.assertEqual(endpoint_mailbox(ctx, ep).get(rows[0]["env"]["env_id"]).state, "answered")

    def test_an_interrupt_left_open_by_a_dead_process_expires_and_is_never_typed(self) -> None:
        ft = FakeTransport(clock=self.clock)
        ft.configure(self.ep, agent_state="working")

        class _Dies(FakeTransport):
            def interrupt(self, endpoint, *, timeout_s: float = 5.0):
                raise KeyboardInterrupt  # the escalating process killed while `hc interrupt` runs

        with self.assertRaises(KeyboardInterrupt):
            interrupt_endpoint(self.ctx, self.ep, sender=Principal.pm("demo"),
                               recipient=LogicalAddress.worker("demo-1", "demo"), transport=_Dies(clock=self.clock))
        mb = endpoint_mailbox(self.ctx, self.ep)
        ctrl = [i for i in mb.active_items(("accepted",)) if i.envelope.kind == "ctrl.interrupt"]
        self.assertEqual(len(ctrl), 1)
        res = drain_endpoint(self.ctx, self.ep, transport=ft, wait_s=0)  # returns: nothing typable, no spinning
        self.assertEqual((res.typed, res.failed, ft.deliveries), ([], [], []))
        self.clock.advance(DRAIN_MAX_AGE_S + 1)
        drain_endpoint(self.ctx, self.ep, transport=ft, wait_s=0)
        self.assertEqual(mb.get(ctrl[0].envelope.env_id).state, "expired")
        self.assertEqual(ft.deliveries, [])

    def test_an_interrupt_whose_record_was_closed_meanwhile_does_not_fail_the_caller(self) -> None:
        mb = endpoint_mailbox(self.ctx, self.ep)

        class _ClosesIt(FakeTransport):
            def interrupt(self, endpoint, *, timeout_s: float = 5.0):
                for it in mb.active_items():
                    mb.transition(it.envelope.env_id, "failed", error="closed elsewhere")
                return InterruptOutcome(status="stopped", key_sent="esc")

        out = interrupt_endpoint(self.ctx, self.ep, sender=Principal.pm("demo"),
                                 recipient=LogicalAddress.worker("demo-1", "demo"), transport=_ClosesIt())
        self.assertEqual(out.status, "stopped")

    # --- prompt keys under the lease ---

    def test_prompt_keys_are_pressed_only_while_holding_the_lease(self) -> None:
        ft = FakeTransport(clock=self.clock)
        self._hold_lease()
        self.assertIsNone(unblock_endpoint(self.ctx, self.ep, ["enter"], transport=ft))  # not tried: busy
        self.assertEqual(ft.unblocks, [])
        self._release_lease()
        self.assertTrue(unblock_endpoint(self.ctx, self.ep, ["enter"], transport=ft))
        self.assertEqual(ft.unblocks, [(self.ep.uid, ("enter",))])
        self.assertIsNone(endpoint_mailbox(self.ctx, self.ep).typist_lease_holder(self.ep.uid))

    def test_the_stall_watcher_presses_known_prompt_keys_through_the_lease(self) -> None:
        stalls = StallWatcher(self.ctx)
        self._hold_lease()
        self.assertIsNone(stalls._unblock("t20", ["1", "enter"]))
        self.assertNotIn("keys", self.hc.terminals["t20"])
        self._release_lease()
        self.assertTrue(stalls._unblock("t20", ["1", "enter"]))
        self.assertEqual(self.hc.terminals["t20"]["keys"], [["1", "enter"]])

    def test_a_brief_typed_without_its_turn_starting_is_retyped_only_while_nothing_moved(self) -> None:
        replies = [{"ok": True, "started": False, "status": {"state": "idle"}},
                   {"ok": True, "started": True}]

        class _Scripted(FakeHc):
            def send(self, term, text, **kw):
                super().send(term, text, **kw)
                return replies.pop(0)

        hc = _Scripted(terminals={"t20": {"state": "live", "status": {"state": "idle"}, "turn": 4}}, clock=self.clock)
        ctx = make_ctx(self._tmp.name, hc=hc, clock=self.clock)
        seen: dict = {}
        self.assertTrue(send_when_ready_for(ctx, "t20", "the brief\n", tries=4, pause=0, seen=seen))
        self.assertEqual([t for _, t in hc.sent], ["the brief\n", "the brief\n"])  # the same text, typed again
        self.assertEqual(seen, {"turn": 4})

        # Typed without starting, but the terminal then moved on (the agent took it): never typed again.
        replies[:] = [{"ok": True, "started": False, "status": {"state": "idle"}}]

        def moves_on(n: int) -> None:
            if n == 2:
                hc.terminals["t20"]["turn"] = 5

        self.clock.n = 0
        self.clock.on_sleep = moves_on
        hc.sent.clear()
        self.assertTrue(send_when_ready_for(ctx, "t20", "brief two", tries=4, pause=0))
        self.assertEqual([t for _, t in hc.sent], ["brief two"])

    def test_a_brief_is_not_queued_until_its_terminal_is_ready_so_no_other_drain_types_it_early(self) -> None:
        self.hc.terminals["t20"]["status"] = {"state": "working"}  # still starting up

        def meanwhile(n: int) -> None:
            if n == 1:  # someone sends to the new worker before its brief went in: typed now, alone
                Workers(self.ctx).send("t20", "early note", wait=True)
            if n == 2:
                self.hc.terminals["t20"]["status"] = {"state": "idle"}

        self.clock.on_sleep = meanwhile
        self.assertTrue(send_when_ready_for(self.ctx, "t20", "the brief", tries=4, pause=0))
        self.assertEqual([t.split("] ", 1)[-1] for _, t in self.hc.sent], ["early note", "the brief"])

    # --- interrupt as a control envelope ---

    def test_escalate_interrupts_with_a_ctrl_interrupt_envelope(self) -> None:
        ft = FakeTransport(clock=self.clock)
        ft.configure(self.ep, agent_state="working")
        out = interrupt_endpoint(self.ctx, self.ep, sender=Principal.pm("demo"),
                                 recipient=LogicalAddress.worker("demo-1", "demo"), project="demo",
                                 cause={"kind": "escalate", "task_id": "demo-1"}, transport=ft)
        self.assertEqual(out.status, "stopped")
        self.assertEqual(len(ft.interrupts), 1)
        mb = endpoint_mailbox(self.ctx, self.ep)
        rows = [r for r in mb.read_stream_after(0)[0] if r.get("rec") == "enq"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["env"]["kind"], rows[0]["env"]["priority"]), ("ctrl.interrupt", P0_CONTROL))
        item = mb.get(rows[0]["env"]["env_id"])
        self.assertEqual(item.state, "answered")
        self.assertEqual(item.meta["interrupt"]["status"], "stopped")

    def test_an_interrupt_to_a_gone_endpoint_fails_its_envelope(self) -> None:
        ft = FakeTransport(clock=self.clock)
        ft.configure(self.ep, live=False)
        out = interrupt_endpoint(self.ctx, self.ep, sender=Principal.pm("demo"),
                                 recipient=LogicalAddress.worker("demo-1", "demo"), transport=ft)
        self.assertEqual(out.status, "endpoint_gone")
        rows = [r for r in endpoint_mailbox(self.ctx, self.ep).read_stream_after(0)[0] if r.get("rec") == "enq"]
        self.assertEqual(endpoint_mailbox(self.ctx, self.ep).get(rows[0]["env"]["env_id"]).state, "failed")

    def test_the_tui_interrupt_sends_the_esc_key_escalate_always_used(self) -> None:
        from pmlib.messaging.transports.tui import LocalTuiTransport
        out = LocalTuiTransport(self.ctx).interrupt(Endpoint(runtime="tui", terminal="w1:p2"))
        self.assertIsInstance(out, InterruptOutcome)
        self.assertIn(("w1:p2", ["esc"]), self.ctx.tui.sent_keys)

    # --- Phase 5: async send started=false auto-retry & wake=True PM alert ---

    def _setup_repo_task(self, ctx, repo_dir: pathlib.Path, *, pm_pane: str = "hc:t7", term: str = "t20") -> tuple[str, str]:
        repo_dir.mkdir(parents=True, exist_ok=True)
        repo = str(repo_dir.resolve())
        slug = project_slug(repo)
        ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        ctx.home.registration(slug).write_text(
            json.dumps({
                "name": f"pm-{slug}",
                "project": "demo",
                "repo": repo,
                "runtime": "hc",
                "terminal": pm_pane.split(":", 1)[1],
                "pane": pm_pane,
            }),
            encoding="utf-8",
        )
        ctx.home.tasks.mkdir(parents=True, exist_ok=True)
        tid = "demo-1"
        ctx.home.task(tid).write_text(
            json.dumps({
                "id": tid,
                "title": "async send retry task",
                "project": "demo",
                "repo": repo,
                "status": "in_progress",
                "pane": f"hc:{term}",
                "dispatched": True,
                "created": self.clock.now(),
                "log": [],
                "round": {"terminal": term, "at": self.clock.now(), "turn": 4},
            }),
            encoding="utf-8",
        )
        return repo, tid

    def test_async_send_transient_started_false_retries_and_succeeds(self) -> None:
        replies = [
            {"ok": True, "started": False, "status": {"state": "idle"}},
            {"ok": True, "started": True},
        ]

        class _Scripted(FakeHc):
            def send(self, term, text, **kw):
                super().send(term, text, **kw)
                return replies.pop(0) if replies else {"ok": True, "started": True}

        hc = _Scripted(terminals={
            "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}, "turn": 1},
            "t20": {"state": "live", "status": {"state": "idle"}, "turn": 4},
        }, clock=self.clock)
        ctx = make_ctx(self._tmp.name + "-retry-ok", hc=hc, clock=self.clock, pane="hc:t7")
        repo, tid = self._setup_repo_task(ctx, pathlib.Path(self._tmp.name) / "repo-ok")
        Workers(ctx).send("t20", "continue task", task_id=tid, repo=repo)
        run_spawned_drains(ctx)

        self.assertEqual(len(hc.sent), 2)
        mb = endpoint_mailbox(ctx, worker_endpoint("t20"))
        states = [mb.get(r["env"]["env_id"]).state for r in mb.read_stream_after(0)[0] if r.get("rec") == "enq"]
        self.assertEqual(states, ["answered"])
        self.assertEqual(Conversation(ctx, repo).events(), [])

    def test_async_send_late_turn_start_during_backoff_never_double_sends(self) -> None:
        class _Scripted(FakeHc):
            def send(self, term, text, **kw):
                super().send(term, text, **kw)
                return {"ok": True, "started": False, "status": {"state": "idle"}}

        hc = _Scripted(terminals={
            "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}, "turn": 1},
            "t20": {"state": "live", "status": {"state": "idle"}, "turn": 0, "status_ms": 0},
        }, clock=self.clock)

        def _starts_late(_n: int) -> None:
            hc.terminals["t20"]["status"] = {"state": "working"}
            hc.terminals["t20"]["turn"] = 1

        self.clock.on_sleep = _starts_late
        ctx = make_ctx(self._tmp.name + "-late", hc=hc, clock=self.clock, pane="hc:t7")
        repo, tid = self._setup_repo_task(ctx, pathlib.Path(self._tmp.name) / "repo-late")
        Workers(ctx).send("t20", "late take", task_id=tid, repo=repo)
        run_spawned_drains(ctx)

        self.assertEqual(len(hc.sent), 1)
        mb = endpoint_mailbox(ctx, worker_endpoint("t20"))
        states = [mb.get(r["env"]["env_id"]).state for r in mb.read_stream_after(0)[0] if r.get("rec") == "enq"]
        self.assertEqual(states, ["answered"])
        self.assertEqual(Conversation(ctx, repo).events(), [])

    def test_async_send_exhausted_retries_from_pm_pane_wakes_pm_via_pending_batch(self) -> None:
        class _AlwaysUnstarted(FakeHc):
            def send(self, term, text, **kw):
                super().send(term, text, **kw)
                return {"ok": True, "started": False, "status": {"state": "idle"}}

        hc = _AlwaysUnstarted(terminals={
            "t7": {"state": "live", "labels": {"pm": "demo"}, "status": {"state": "idle"}, "turn": 1},
            "t20": {"state": "live", "status": {"state": "idle"}, "turn": 4},
        }, clock=self.clock)
        ctx = make_ctx(self._tmp.name + "-exhaust", hc=hc, clock=self.clock, pane="hc:t7")
        ctx.procs.env["HC_TERMINAL_ID"] = "t7"
        repo, tid = self._setup_repo_task(ctx, pathlib.Path(self._tmp.name) / "repo-exhaust")
        Workers(ctx).send("t20", "please check", task_id=tid, repo=repo)

        drain_spawns = [s for s in ctx.procs.spawned if (s.get("args") or [None])[0] == "_drain-endpoint"]
        self.assertEqual(len(drain_spawns), 1)
        self.assertNotIn("HC_TERMINAL_ID", drain_spawns[0]["env"])

        run_spawned_drains(ctx)
        self.assertEqual(len(hc.sent), 3)  # initial + 2 retries
        events = Conversation(ctx, repo).events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].get("wake"))
        self.assertEqual(events[0].get("source"), "harness")
        self.assertEqual(events[0].get("by"), "harness")

        # Pending batch for PM must NOT drop this harness failure alert via PM-supersede.
        _start, _end, items = Delivery(ctx, repo).pending_batch(settle=False)
        self.assertEqual(len(items), 1)
        self.assertIn("failed", items[0]["event"]["text"])
        deliver_spawns = [s for s in ctx.procs.spawned if (s.get("args") or [None])[0] == "deliver"]
        self.assertEqual(len(deliver_spawns), 1)

    def test_local_hc_transport_reconciles_post_info_at_turn_zero(self) -> None:
        class _ReconcileZero(FakeHc):
            def send(self, term, text, **kw):
                super().send(term, text, **kw)
                self.terminals["t20"]["turn"] = 1
                self.terminals["t20"]["status"] = {"state": "working"}
                return {"ok": True, "started": False}

        hc = _ReconcileZero(
            terminals={"t20": {"state": "live", "status": {"state": "idle"}, "turn": 0, "status_ms": 0}},
            clock=self.clock,
        )
        ctx = make_ctx(self._tmp.name + "-t0", hc=hc, clock=self.clock)
        ep = Endpoint(runtime="hc", terminal="t20")
        mb = endpoint_mailbox(ctx, ep)
        env = terminal_envelope(ctx, "hello t0", target="t20")
        item, _ = mb.enqueue(env, initial_state="accepted", now_ms=1000, target_endpoint_uid=ep.uid)
        out = LocalHcTransport(ctx).deliver(ep, item, if_idle=False, pre_info=hc.get_raw("t20"))
        self.assertEqual(out.status, "typed")
        self.assertTrue(out.started_turn)
        self.assertEqual(out.observed_turn, 1)


if __name__ == "__main__":
    unittest.main()
