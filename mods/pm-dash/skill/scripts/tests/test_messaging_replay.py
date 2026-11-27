"""Replay tests for Phase 3a Wave 2 coordinator single-typist & crash/rotation/interruption recovery (§10.4)."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pmlib import cli as cli_mod
from pmlib.commands import events as events_cmds
from pmlib.events.deliver import Delivery
from pmlib.events.supervisor import EndpointDriver
from pmlib.manager import rotate as rotate_mod
from pmlib.manager.seat import _seat_prompt_sender
from pmlib.messaging.address import Endpoint, LogicalAddress
from pmlib.messaging.envelope import P1_USER, P4_BATCH, Envelope, new_env_id
from pmlib.messaging.mailbox import MailboxStore
from pmlib.messaging.principal import Principal
from pmlib.messaging.transports import FakeTransport
from pmlib.project.conversation import Conversation
from pmlib.project.turn_state import TurnTracker
from tests.fakes import FakeClock, FakeHc, FakeTui, make_ctx, run_main


class TestMessagingReplay(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_dir = pathlib.Path(self._tmp.name) / "repo"
        self.repo_dir.mkdir(parents=True)
        self.clock = FakeClock()
        self.hc = FakeHc(terminals={"t1": {"address": "t1", "state": "live", "agent": "claude", "status": {"state": "idle"}, "turn": 1}})
        self.ctx = make_ctx(self._tmp.name, pane="hc:t1", clock=self.clock, hc=self.hc)
        self.slug = pathlib.Path(self.repo_dir).name
        self.ctx.store.change_registration(self.slug, lambda _: {
            "name": f"pm-{self.slug}",
            "repo": str(self.repo_dir),
            "pane": "hc:t1",
            "terminal": "t1",
            "runtime": "hc",
            "app_pm": True,
            "seat": True,
            "agent": "claude",
            "endpoint": {"runtime": "hc", "machine": None, "terminal": "t1", "epoch": 1},
            "epoch": 1,
        })

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_1_rotate_right_after_typing_requeues_and_redelivers_on_new_epoch(self) -> None:
        tracker = TurnTracker(self.ctx, self.repo_dir)
        res = tracker.send_user_message(msg_id="u-rot-1", text="check production alerts")
        self.assertEqual(res["status"], "accepted")
        env_id = res["env_id"]

        reg = self.ctx.store.registration(self.slug) or {}
        info = self.hc.get_raw("t1")
        driver = EndpointDriver(self.ctx, self.repo_dir)
        out1, _ = driver.drive_pm_endpoint(reg, info)
        self.assertIsNotNone(out1)
        self.assertEqual(out1.status, "typed")
        self.assertEqual(tracker.pm_mailbox.get(env_id).state, "typed")
        self.assertEqual(len(self.hc.sent), 1)

        # Rotate before UserPromptSubmit hook consumes `env_id`: epoch bumps 1 -> 2.
        reg2 = dict(reg)
        reg2["epoch"] = 2
        reg2["endpoint"] = {"runtime": "hc", "machine": None, "terminal": "t1", "epoch": 2}
        self.ctx.store.change_registration(self.slug, lambda _: reg2)

        out2, _ = driver.drive_pm_endpoint(reg2, info)
        self.assertIsNotNone(out2)
        self.assertEqual(out2.status, "typed")
        self.assertEqual(tracker.pm_mailbox.get(env_id).endpoint_epoch, 2)
        self.assertEqual(len(self.hc.sent), 2)

    def test_2_interrupted_batch_turn_retries_without_duplicate_suppression(self) -> None:
        tracker = TurnTracker(self.ctx, self.repo_dir)
        Conversation(self.ctx, self.repo_dir).record("event", by="worker-1", text="task #1 finished", source="worker", wake=True)
        dlv = Delivery(self.ctx, self.repo_dir, settle=0)
        start, end, items = dlv.pending_batch()
        batch_env_id = new_env_id(int(self.clock.time() * 1000))
        btext = dlv.batch_text(start, end, items, env_id=batch_env_id)
        batch_env = Envelope(
            env_id=batch_env_id,
            idempotency_key=f"batch:{self.slug}:{start}-{end}",
            schema_version=1,
            created_ms=int(self.clock.time() * 1000),
            kind="event.batch",
            sender=Principal.supervisor(self.slug),
            recipient=LogicalAddress.pm(self.slug),
            project=self.slug,
            cause={"kind": "deliver_batch", "start": start, "end": end},
            priority=P4_BATCH,
            body={"text": btext, "start": start, "end": end},
            require_reply=True,
        )
        tracker.pm_mailbox.enqueue(batch_env, initial_state="accepted")
        reg = self.ctx.store.registration(self.slug) or {}
        driver = EndpointDriver(self.ctx, self.repo_dir)
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(tracker.pm_mailbox.get(batch_env_id).state, "typed")

        # Hook receives typed batch -> consumed in turn seq:1
        r1 = dlv.took_delivery(self.hc.sent[0][1], turn_id="seq:1")
        self.assertFalse(r1.repeated)
        self.assertIsNone(r1.warning)
        self.assertEqual(tracker.pm_mailbox.get(batch_env_id).state, "consumed")

        # Turn interrupted -> G5 puts item back in accepted for retry
        retried = tracker.pm_mailbox.reconcile_turn_outcome("seq:1", "interrupted")
        self.assertEqual(retried[0].state, "accepted")

        # Driver delivers retry -> hook receives WITHOUT false duplicate warning!
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        r2 = dlv.took_delivery(self.hc.sent[1][1], turn_id="seq:2")
        self.assertFalse(r2.repeated)
        self.assertIsNone(r2.warning)
        answered = tracker.pm_mailbox.reconcile_turn_outcome("seq:2", "replied")
        self.assertEqual(answered[0].state, "answered")

    def test_3_concurrent_p1_and_p4_respect_priority_and_single_typist_lease(self) -> None:
        tracker = TurnTracker(self.ctx, self.repo_dir)
        reg = self.ctx.store.registration(self.slug) or {}
        ep = Endpoint(runtime="hc", machine=None, terminal="t1", epoch=1)
        # P4 arrives first, P1 arrives second -> P1 must deliver BEFORE P4
        b_env = Envelope(
            env_id=new_env_id(1_700_000_000_000),
            idempotency_key="b-1",
            schema_version=1,
            created_ms=1_700_000_000_000,
            kind="event.batch",
            sender=Principal.supervisor(self.slug),
            recipient=LogicalAddress.pm(self.slug),
            project=self.slug,
            cause={"kind": "batch"},
            priority=P4_BATCH,
            body={"text": "[from pm.py deliver] 1 event(s) (0-10)"},
            require_reply=True,
        )
        tracker.pm_mailbox.enqueue(b_env, initial_state="accepted", target_endpoint_uid=ep.uid, endpoint_epoch=1)
        res_u = tracker.send_user_message(msg_id="u-prio-1", text="urgent user prompt")

        driver = EndpointDriver(self.ctx, self.repo_dir)
        # While another PID holds typist lease, driver must NOT type anything
        self.assertTrue(tracker.pm_mailbox.acquire_typist_lease(ep.uid, 999_999, ttl_ms=60_000, now_ms=int(self.clock.time() * 1000)))
        out_busy, due_busy = driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertIsNone(out_busy)
        self.assertEqual(due_busy, 0.5)
        self.assertEqual(self.hc.sent, [])
        tracker.pm_mailbox.release_typist_lease(ep.uid, 999_999)

        # Once lease free: P1 user prompt goes first, then P4 batch second
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 1)
        self.assertEqual(self.hc.sent[0][1], "urgent user prompt")
        self.assertEqual(tracker.pm_mailbox.get(res_u["env_id"]).state, "typed")

        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 2)
        self.assertIn("[from pm.py deliver]", self.hc.sent[1][1])

    def test_4_terminal_unsent_draft_beyond_5s_marks_waiting_quiet_or_draft(self) -> None:
        tracker = TurnTracker(self.ctx, self.repo_dir)
        res = tracker.send_user_message(msg_id="u-draft-1", text="wait for user draft")
        env_id = res["env_id"]
        ep = Endpoint(runtime="hc", machine=None, terminal="t1", epoch=1)
        ft = FakeTransport(clock=self.clock)
        ft.configure(ep, live=True, agent_state="idle", can_report_status=True, draft_delay_ms=10_000)

        reg = self.ctx.store.registration(self.slug) or {}
        driver = EndpointDriver(self.ctx, self.repo_dir, transport=ft)
        # Initial kick starts non-blocking handle
        out0, due0 = driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertIsNone(out0)
        self.assertEqual(due0, 0.5)

        # Advance 6s (>5s threshold) -> still holding on draft -> hold_reason becomes waiting_quiet_or_draft
        self.clock.advance(6.0)
        out1, due1 = driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertIsNone(out1)
        self.assertEqual(due1, 0.5)
        self.assertEqual(tracker.pm_mailbox.get(env_id).hold_reason, "waiting_quiet_or_draft")

        # User clears draft (advance past 10s total) -> completes as typed!
        self.clock.advance(5.0)
        out2, due2 = driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertIsNotNone(out2)
        self.assertEqual(out2.status, "typed")
        self.assertEqual(due2, 0)
        self.assertEqual(tracker.pm_mailbox.get(env_id).state, "typed")

    def test_5_consume_ui_prompt_never_drops_accepted_or_substring_matches(self) -> None:
        tracker = TurnTracker(self.ctx, self.repo_dir)
        res_ok = tracker.send_user_message(msg_id="u-ok", text="ok")
        res_done = tracker.send_user_message(msg_id="u-done", text="done")
        # Transition ONLY res_done to typed; keep res_ok as accepted (untyped)
        tracker.pm_mailbox.transition(res_done["env_id"], "typed", now_ms=int(self.clock.time() * 1000))

        # 1) Substring in another prompt must neither match untyped 'ok' nor partial-match 'done'
        full1, ids1, _ = tracker.consume_ui_prompt("look at the ok button and not done yet", turn_id="t-1")
        self.assertFalse(full1)
        self.assertEqual(ids1, [])
        self.assertEqual(tracker.pm_mailbox.get(res_ok["env_id"]).state, "accepted")
        self.assertEqual(tracker.pm_mailbox.get(res_done["env_id"]).state, "typed")

        # 2) Even exact text 'ok' or msg_id/env_id match must NOT consume an untyped ('accepted') item
        full2, ids2, _ = tracker.consume_ui_prompt("ok", turn_id="t-2")
        self.assertFalse(full2)
        self.assertEqual(ids2, [])
        self.assertEqual(tracker.pm_mailbox.get(res_ok["env_id"]).state, "accepted")

        # 3) Once typed, exact text still won't match substring, and WILL consume exact text match
        tracker.pm_mailbox.transition(res_ok["env_id"], "typed", now_ms=int(self.clock.time() * 1000))
        full3, ids3, _ = tracker.consume_ui_prompt("look at the ok button", turn_id="t-3")
        self.assertFalse(full3)
        self.assertEqual(tracker.pm_mailbox.get(res_ok["env_id"]).state, "typed")

        full4, ids4, _ = tracker.consume_ui_prompt("ok", turn_id="t-4")
        self.assertTrue(full4)
        self.assertEqual(ids4, ["u-ok"])
        self.assertEqual(tracker.pm_mailbox.get(res_ok["env_id"]).state, "consumed")
        self.assertEqual(tracker.pm_mailbox.get(res_done["env_id"]).state, "typed")

    def test_6_still_running_notify_and_seat_respect_typist_lock_without_double_typing(self) -> None:
        ep = Endpoint(runtime="hc", machine=None, terminal="t1", epoch=1)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        self.ctx.store.change_registration(self.slug, lambda r: {**r, "previous": {"terminal": "t0"}})
        reg = self.ctx.store.registration(self.slug) or {}
        driver = EndpointDriver(self.ctx, self.repo_dir)

        # (a) still_running while typist.lock is held: enqueues only, zero direct hc.send, single delivery once lock released
        self.assertTrue(tracker.pm_mailbox.acquire_typist_lease(ep.uid, 888_888, ttl_ms=60_000, now_ms=int(self.clock.time() * 1000)))
        rotate_mod.still_running("t0", ["pytest"], ctx=self.ctx)
        self.assertEqual(self.hc.sent, [])
        accepted = [it for it in tracker.pm_mailbox.active_items(("accepted",)) if it.envelope.kind == "event.notify"]
        self.assertEqual(len(accepted), 1)
        tracker.pm_mailbox.release_typist_lease(ep.uid, 888_888)

        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 1)
        # A notify needs no reply: typed, then closed at once (nothing would ever end it otherwise).
        self.assertEqual(tracker.pm_mailbox.get(accepted[0].envelope.env_id).state, "answered")
        # Driving again must NOT double-type
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 1)

        # (b) still_running when lock is free delivers directly AND transitions to typed so driver won't double-type
        rotate_mod.still_running("t0", ["pytest2"], ctx=self.ctx)
        self.assertEqual(len(self.hc.sent), 2)
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 2)

        # (c) cmd_notify respects typist.lock and advances to typed without double-typing
        tui_repo = pathlib.Path(self._tmp.name) / "tui_repo"
        tui_repo.mkdir(parents=True, exist_ok=True)
        tui_slug = tui_repo.name
        tui_fake = FakeTui(
            agents=[{"name": f"pm-{tui_slug}", "pane_id": "%5", "role": "pm", "cwd": str(tui_repo)}],
            panes=[{"pane_id": "%5", "cwd": str(tui_repo)}],
        )
        notify_ctx = make_ctx(
            self._tmp.name,
            pane="hc:w9",
            clock=self.clock,
            hc=self.hc,
            tui=tui_fake,
        )
        notify_ctx.store.change_registration(
            tui_slug,
            lambda _: {
                "name": f"pm-{tui_slug}",
                "repo": str(tui_repo),
                "pane": "%5",
                "runtime": "tui",
                "agent": "claude",
            },
        )
        ep_tui = Endpoint(runtime="tui", machine=None, terminal="%5", epoch=1)
        tui_tracker = TurnTracker(notify_ctx, tui_repo)
        import argparse
        # Nothing drains a TUI PM's mailbox, so a busy lease is waited out (bounded) and then reported as a failure:
        # never typed over the holder, and never left `accepted` forever as a "queued" notify nobody will send.
        self.assertTrue(tui_tracker.pm_mailbox.acquire_typist_lease(ep_tui.uid, 888_889, ttl_ms=120_000, now_ms=int(self.clock.time() * 1000)))
        notify_ctx.out.clear()
        events_cmds.cmd_notify(argparse.Namespace(repo=str(tui_repo), text="ping while busy"), ctx=notify_ctx)
        self.assertEqual(tui_fake.prompts, [])
        self.assertIn("notify failed", notify_ctx.out.stdout)
        self.assertNotIn("queued notify", notify_ctx.out.stdout)
        self.assertEqual(
            [it for it in tui_tracker.pm_mailbox.active_items(("accepted",)) if it.envelope.kind == "event.notify"], []
        )
        tui_tracker.pm_mailbox.release_typist_lease(ep_tui.uid, 888_889)

        notify_ctx.out.clear()
        events_cmds.cmd_notify(argparse.Namespace(repo=str(tui_repo), text="ping when free"), ctx=notify_ctx)
        self.assertEqual(len(tui_fake.prompts), 1)
        self.assertIn("ping when free", tui_fake.prompts[0][1])
        self.assertIn("notified PM at %5", notify_ctx.out.stdout)
        typed_free = [it for it in self._items_of_kind(tui_tracker, "event.notify")
                      if "ping when free" in str((it.envelope.body or {}).get("text") or "")]
        self.assertEqual([(it.state, it.meta.get("closed")) for it in typed_free], [("answered", "no_reply_needed")])

        # (d) _seat_prompt_sender enforces typist.lock and avoids double-typing with EndpointDriver
        class _FakeProc:
            def __init__(self) -> None:
                self.calls = 0

            def poll(self):
                self.calls += 1
                return None if self.calls <= 3 else 0

        self.assertTrue(tracker.pm_mailbox.acquire_typist_lease(ep.uid, 888_890, ttl_ms=60_000, now_ms=int(self.clock.time() * 1000)))
        t_busy = _seat_prompt_sender(_FakeProc(), "t1", "claude", "opening busy", repo=self.repo_dir, ctx=self.ctx)
        t_busy.join(timeout=2.0)
        self.assertEqual(len(self.hc.sent), 2)  # could not acquire typist.lock; stays queued in mailbox
        tracker.pm_mailbox.release_typist_lease(ep.uid, 888_890)
        driver.drive_pm_endpoint(self.ctx.store.registration(self.slug) or {}, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 3)
        self.assertIn("opening busy", self.hc.sent[2][1])

        t_free = _seat_prompt_sender(_FakeProc(), "t1", "claude", "opening free", repo=self.repo_dir, ctx=self.ctx)
        t_free.join(timeout=2.0)
        self.assertEqual(len(self.hc.sent), 4)
        driver.drive_pm_endpoint(self.ctx.store.registration(self.slug) or {}, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 4)

    @staticmethod
    def _items_of_kind(tracker: TurnTracker, kind: str) -> list:
        rows, _ = tracker.pm_mailbox.read_stream_after(0, limit=0)
        ids = list(dict.fromkeys(r["env"]["env_id"] for r in rows if r.get("rec") == "enq" and r["env"]["kind"] == kind))
        return [tracker.pm_mailbox.get(i) for i in ids]

    def _notify_env(self, text: str) -> Envelope:
        now_ms = int(self.clock.time() * 1000)
        return Envelope(
            env_id=new_env_id(now_ms),
            idempotency_key="",
            schema_version=1,
            created_ms=now_ms,
            kind="event.notify",
            sender=Principal.supervisor(self.slug),
            recipient=LogicalAddress.pm(self.slug),
            project=self.slug,
            cause={"kind": "notify"},
            priority=P4_BATCH,
            body={"text": text},
        )

    def test_8_inflight_async_send_holds_typist_lease_until_it_settles(self) -> None:
        """Review 2026-11-26 07:02 #1: while an async `hc send` is in flight nobody else may type, for its whole life."""
        tracker = TurnTracker(self.ctx, self.repo_dir)
        self.ctx.store.change_registration(self.slug, lambda r: {**r, "previous": {"terminal": "t0"}})
        reg = self.ctx.store.registration(self.slug) or {}
        info = self.hc.get_raw("t1")
        ep = Endpoint(runtime="hc", machine=None, terminal="t1", epoch=1)
        res = tracker.send_user_message(msg_id="u-fly-1", text="a long send")
        ft = FakeTransport(clock=self.clock)
        ft.configure(ep, draft_delay_ms=100_000)  # hc waits on a draft for 100 s: longer than one lease TTL
        driver = EndpointDriver(self.ctx, self.repo_dir, transport=ft)

        out0, due0 = driver.drive_pm_endpoint(reg, info)
        self.assertIsNone(out0)
        self.assertEqual(due0, 0.5)
        self.assertTrue(driver.has_inflight())
        holder = tracker.pm_mailbox.typist_lease_holder(ep.uid)
        self.assertIsNotNone(holder)
        self.assertIn(":driver:", holder["owner"])
        self.assertTrue((self.ctx.home.typists / f"{'hc_local_t1'}.typist.json").is_file())

        # The reviewer's repro: another pid cannot take the lease, and still_running (same pid, in process) only queues.
        now_ms = int(self.clock.time() * 1000)
        self.assertFalse(tracker.pm_mailbox.acquire_typist_lease(ep.uid, 424_242, ttl_ms=60_000, now_ms=now_ms))
        rotate_mod.still_running("t0", ["pytest"], ctx=self.ctx)
        from pmlib.events.supervisor import deliver_under_typist_lock
        self.assertIsNone(deliver_under_typist_lock(self.ctx, ep, self._notify_env("in-process ping"), repo=self.repo_dir))
        self.assertEqual(self.hc.sent, [])
        queued = [it for it in tracker.pm_mailbox.active_items(("accepted",)) if it.envelope.kind == "event.notify"]
        self.assertEqual(len(queued), 2)
        self.assertTrue(all(it.hold_reason == "typist_busy" for it in queued))

        # Renewal: polled past the 75 s TTL the lease is still ours; nobody else ever gets it while hc send waits.
        for _ in range(18):  # 90 s
            self.clock.advance(5.0)
            out, due = driver.drive_pm_endpoint(reg, info)
            self.assertIsNone(out)
            self.assertFalse(tracker.pm_mailbox.acquire_typist_lease(
                ep.uid, 424_242, ttl_ms=60_000, now_ms=int(self.clock.time() * 1000)
            ))
        self.assertEqual(ft.deliveries, [])

        # The send settles: the lease is released, then the queued notifies are typed by the single typist, once each.
        self.clock.advance(15.0)
        out_done, due_done = driver.drive_pm_endpoint(reg, info)
        self.assertEqual(out_done.status, "typed")
        self.assertEqual(due_done, 0)
        self.assertFalse(driver.has_inflight())
        self.assertIsNone(tracker.pm_mailbox.typist_lease_holder(ep.uid))
        self.assertEqual(tracker.pm_mailbox.get(res["env_id"]).state, "typed")
        tracker.end_turn(has_reply=True)
        ft.configure(ep, agent_state="idle", draft_delay_ms=0)
        for _ in range(4):
            driver.drive_pm_endpoint(reg, info)
            ft.configure(ep, agent_state="idle")
            tracker.end_turn(has_reply=True)
        typed_ids = [d["env_id"] for d in ft.deliveries]
        self.assertEqual(typed_ids, [res["env_id"], *[it.envelope.env_id for it in queued]])
        self.assertEqual(self.hc.sent, [])

    def test_9_hook_consumes_inflight_and_uncertain_sends_and_settle_keeps_consumed(self) -> None:
        """Review 07:02 #3b: a typed-but-unsettled send (in flight / timeout_uncertain) is consumed by its hook."""
        from pmlib.messaging.transport import DeliverOutcome
        tracker = TurnTracker(self.ctx, self.repo_dir)
        reg = self.ctx.store.registration(self.slug) or {}
        info = self.hc.get_raw("t1")
        ep = Endpoint(runtime="hc", machine=None, terminal="t1", epoch=1)
        ft = FakeTransport(clock=self.clock)
        ft.configure(ep, draft_delay_ms=10_000)
        driver = EndpointDriver(self.ctx, self.repo_dir, transport=ft)

        # (a) The hook sees the prompt while the async send is still in flight.
        res = tracker.send_user_message(msg_id="u-race-1", text="ship it")
        self.assertEqual(driver.drive_pm_endpoint(reg, info), (None, 0.5))
        self.assertIsNotNone(tracker.pm_mailbox.get(res["env_id"]).intent)
        full, ids, rest = tracker.consume_ui_prompt("ship it", turn_id="seq:1")
        self.assertEqual((full, ids, rest), (True, ["u-race-1"], ""))
        self.assertEqual(tracker.pm_mailbox.get(res["env_id"]).state, "consumed")
        self.clock.advance(11.0)
        out, _ = driver.drive_pm_endpoint(reg, info)  # settles typed onto a consumed item: no illegal transition
        self.assertEqual(out.status, "typed")
        got = tracker.pm_mailbox.get(res["env_id"])
        self.assertEqual(got.state, "consumed")
        self.assertIsNone(got.intent)
        self.assertIsNone(tracker.pm_mailbox.typist_lease_holder(ep.uid))
        tracker.end_turn(has_reply=True)

        # (b) hc send came back timeout_uncertain (intent kept, not reconciled yet): the hook still consumes it.
        ft.configure(ep, agent_state="idle", draft_delay_ms=0,
                     next_deliver=DeliverOutcome(status="timeout_uncertain", detail="no reply"))
        res2 = tracker.send_user_message(msg_id="u-unc-1", text="second message")
        out2, _ = driver.drive_pm_endpoint(reg, info)
        self.assertEqual(out2.status, "timeout_uncertain")
        unc = tracker.pm_mailbox.get(res2["env_id"])
        self.assertEqual((unc.state, unc.hold_reason), ("accepted", "timeout_uncertain"))
        self.assertIsNotNone(unc.intent)
        full2, ids2, _ = tracker.consume_ui_prompt("second message", turn_id="seq:2")
        self.assertTrue(full2)
        self.assertEqual(ids2, ["u-unc-1"])
        self.assertEqual(tracker.pm_mailbox.get(res2["env_id"]).state, "consumed")

        # (c) Never sent (no intent): even the exact text is not consumed, so it is not lost.
        res3 = tracker.send_user_message(msg_id="u-q-1", text="ok")
        full3, ids3, _ = tracker.consume_ui_prompt("ok", turn_id="seq:3")
        self.assertFalse(full3)
        self.assertEqual(ids3, [])
        self.assertEqual(tracker.pm_mailbox.get(res3["env_id"]).state, "accepted")

    def _seat_hc(self, script: list[bool], *, late_start: bool = False) -> FakeHc:
        test = self

        class _ScriptedHc(FakeHc):
            bump_after: int | None = None

            def send(self, term, text, **kw):  # type: ignore[override]
                res = FakeHc.send(self, term, text, **kw)
                if isinstance(res, dict) and res.get("ok") and script:
                    started = script.pop(0)
                    # A status-reporting terminal's reply carries its status (a stateless one's is null).
                    res = {**res, "started": started, "status": {"state": "working" if started else "idle"}}
                    if late_start and not started:
                        self.bump_after = 1  # after the send's own post-check: the turn shows up a moment later
                return res

            def get_raw(self, term, *, errors=False):  # type: ignore[override]
                if self.bump_after is not None:
                    if self.bump_after == 0:
                        row = self._mutable_dict("t1")
                        row["turn"] = int(row.get("turn") or 0) + 1  # the turn ran after all (hc missed its start)
                        self.bump_after = None
                    else:
                        self.bump_after -= 1
                return FakeHc.get_raw(self, term, errors=errors)

        hc = _ScriptedHc(terminals={"t1": {"address": "t1", "state": "live", "agent": "claude",
                                           "status": {"state": "idle"}, "turn": 1}})
        test.ctx = make_ctx(test._tmp.name, pane="hc:t1", clock=test.clock, hc=hc)
        return hc

    class _Proc:
        def __init__(self, polls: int) -> None:
            self.calls = 0
            self.polls = polls

        def poll(self):
            self.calls += 1
            return None if self.calls <= self.polls else 0

    def test_10_seat_opening_prompt_retries_when_its_turn_never_started(self) -> None:
        """Review 07:02 #2: typed with started=false and no turn since -> the same envelope is typed again."""
        hc = self._seat_hc([False, True])
        t = _seat_prompt_sender(self._Proc(polls=8), "t1", "claude", "opening prompt", repo=self.repo_dir, ctx=self.ctx)
        t.join(timeout=5.0)
        opening = [text for _, text in hc.sent if "opening prompt" in text]
        self.assertEqual(len(opening), 2)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        items = self._items_of_kind(tracker, "cmd.send")
        self.assertEqual(len(items), 1)  # one envelope, typed twice
        self.assertTrue(items[0].meta.get("typed_started"))
        self.assertEqual(items[0].attempts, 2)
        self.assertEqual(items[0].state, "answered")  # needs no reply: closed once its turn started

    def test_11_seat_opening_prompt_not_retyped_when_its_turn_started_late(self) -> None:
        hc = self._seat_hc([False], late_start=True)
        t = _seat_prompt_sender(self._Proc(polls=8), "t1", "claude", "opening prompt", repo=self.repo_dir, ctx=self.ctx)
        t.join(timeout=5.0)
        self.assertEqual(len([text for _, text in hc.sent if "opening prompt" in text]), 1)
        tracker = TurnTracker(self.ctx, self.repo_dir)
        items = self._items_of_kind(tracker, "cmd.send")
        self.assertEqual(len(items), 1)
        self.assertIs(items[0].meta.get("typed_started"), True)
        self.assertEqual(items[0].state, "answered")

    def test_13_seat_retry_survives_a_driver_pass_after_rotation(self) -> None:
        """After a rotation the registration is at epoch >= 2 while the seat sender only knows the terminal (epoch 1):
        the typed opening prompt must carry the session's epoch, or the driver's G4 pass expires it and the retry
        never retypes it."""
        from pmlib.events.supervisor import deliver_under_typist_lock
        from pmlib.messaging.envelope import P0_CONTROL
        from pmlib.project.turn_reducer import parse_legacy_endpoint
        hc = self._seat_hc([False, True])
        self.ctx.store.change_registration(self.slug, lambda r: {
            **r, "epoch": 2, "endpoint": {"runtime": "hc", "machine": None, "terminal": "t1", "epoch": 2},
        })
        ep = parse_legacy_endpoint("t1", runtime_hint="hc")
        self.assertEqual(ep.epoch, 1)

        def opening() -> Envelope:
            now_ms = int(self.clock.time() * 1000)
            return Envelope(
                env_id=new_env_id(now_ms), idempotency_key="seat_opening:t1:rot", schema_version=1, created_ms=now_ms,
                kind="cmd.send", sender=Principal.supervisor(self.slug), recipient=LogicalAddress.pm(self.slug),
                project=self.slug, cause={"kind": "seat_opening_prompt", "retry_unstarted": True}, priority=P0_CONTROL,
                body={"text": "opening after rotation"},
            )

        out1 = deliver_under_typist_lock(self.ctx, ep, opening(), repo=self.repo_dir, retry_unstarted=True)
        self.assertEqual((out1.status, out1.started_turn), ("typed", False))
        tracker = TurnTracker(self.ctx, self.repo_dir)
        item = tracker.pm_mailbox.get_by_key("seat_opening:t1:rot")
        self.assertEqual((item.state, item.endpoint_epoch), ("typed", 2))

        # The deliverer's driver runs between two seat attempts (G4 at the registration's epoch 2).
        EndpointDriver(self.ctx, self.repo_dir).drive_pm_endpoint(
            self.ctx.store.registration(self.slug) or {}, hc.get_raw("t1")
        )
        self.assertEqual(tracker.pm_mailbox.get_by_key("seat_opening:t1:rot").state, "typed")

        self.clock.advance(2.0)
        out2 = deliver_under_typist_lock(self.ctx, ep, opening(), repo=self.repo_dir, retry_unstarted=True)
        self.assertEqual((out2.status, out2.started_turn), ("typed", True))
        self.assertEqual(len([t for _, t in hc.sent if "opening after rotation" in t]), 2)

    def _typed_user_message(self, tracker: TurnTracker, msg_id: str, text: str) -> str:
        res = tracker.send_user_message(msg_id=msg_id, text=text)
        tracker.pm_mailbox.transition(res["env_id"], "typed", now_ms=int(self.clock.time() * 1000))
        return res["env_id"]

    def _handover_unanswered(self, tracker: TurnTracker) -> list[str]:
        return [str(it.envelope.body.get("text")) for it in tracker.pm_mailbox.unanswered_user_items()]

    def test_14_agy_turn_close_answers_what_it_read(self) -> None:
        """Fable review #2: agy_watch closes turns with end_turn only; what the turn read must still end answered."""
        tracker = TurnTracker(self.ctx, self.repo_dir)
        env_id = self._typed_user_message(tracker, "u-agy-1", "what is the status of #12?")
        # agy_watch.py: consume_ui_prompt -> begin_turn(from_hook=True) -> (reply row) end_turn(has_reply=True)
        consumed, ids, _ = tracker.consume_ui_prompt("what is the status of #12?")
        self.assertTrue(consumed)
        tracker.begin_turn(terminal="hc:t1", agent_kind="agy", cause="user", msg_ids=ids, from_hook=True)
        self.assertEqual(tracker.pm_mailbox.get(env_id).state, "consumed")
        tracker.end_turn(has_reply=True)
        got = tracker.pm_mailbox.get(env_id)
        self.assertEqual((got.state, got.meta.get("turn_outcome")), ("answered", "replied"))
        self.assertEqual(self._handover_unanswered(tracker), [])

    def test_15_esc_interrupted_turn_is_settled_by_the_next_prompt_without_taking_its_message(self) -> None:
        """Fable review #2: an Esc leaves no Stop hook; the next prompt's turn closes it. Its message ends answered
        (never retyped), while the new prompt's message stays with the new turn until that one closes."""
        tracker = TurnTracker(self.ctx, self.repo_dir)
        first = self._typed_user_message(tracker, "u-esc-1", "first question")
        tracker.consume_ui_prompt("first question")
        s1 = tracker.begin_turn(terminal="hc:t1", agent_kind="claude", cause="user", msg_ids=["u-esc-1"], from_hook=True)
        self.clock.advance(3.0)  # Esc: no Stop hook for turn s1

        second = self._typed_user_message(tracker, "u-esc-2", "second question")
        tracker.consume_ui_prompt("second question")
        s2 = tracker.begin_turn(terminal="hc:t1", agent_kind="claude", cause="user", msg_ids=["u-esc-2"], from_hook=True)
        self.assertGreater(s2, s1)
        self.assertEqual(tracker.pm_mailbox.get(first).state, "answered")
        snd = tracker.pm_mailbox.get(second)
        self.assertEqual((snd.state, snd.bound_turn_id), ("consumed", f"seq:{s2}"))
        self.assertEqual(self._handover_unanswered(tracker), ["second question"])  # the turn still handling it

        tracker.end_turn(expected_seq=s2, has_reply=True)
        self.assertEqual(tracker.pm_mailbox.get(second).state, "answered")
        self.assertEqual(self._handover_unanswered(tracker), [])
        self.assertEqual(self.hc.sent, [])  # nothing retyped

    def test_16_turn_closed_by_the_terminal_going_idle_settles_its_messages(self) -> None:
        """No hook at all (the supervisor sees hc go back to idle): the turn's closure still settles what it read."""
        from pmlib.events.supervisor import ProjectSupervisor
        tracker = TurnTracker(self.ctx, self.repo_dir)
        env_id = self._typed_user_message(tracker, "u-idle-1", "third")
        tracker.consume_ui_prompt("third")
        tracker.begin_turn(terminal="hc:t1", agent_kind="claude", cause="user", msg_ids=["u-idle-1"], from_hook=True)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        reg = self.ctx.store.registration(self.slug) or {}
        row = self.hc._mutable_dict("t1")
        row.update({"status": {"state": "working"}, "status_ms": 2_000})
        self.clock.advance(1.0)
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        row.update({"status": {"state": "idle"}, "turn": 2, "status_ms": 5_000})
        self.clock.advance(5.0)
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        self.assertEqual(tracker.pm_mailbox.get(env_id).state, "answered")
        self.assertEqual(self._handover_unanswered(tracker), [])

    def test_17_waiting_batch_does_not_rewrite_pm_turn_on_every_look(self) -> None:
        """Fable review #3: the deliverer watches pm-turn.json; a held batch must not make each look rewrite it."""
        import json
        from pmlib.events.deliverer import Deliverer

        class _Waiter:
            terminals: set = set()
            files: list = []

            def wait(self, _t) -> None:
                return None

        row = self.hc._mutable_dict("t1")
        row.update({"status": {"state": "working"}, "status_ms": 5, "reported": True})
        tracker = TurnTracker(self.ctx, self.repo_dir)
        tracker.begin_turn(terminal="hc:t1", agent_kind="claude", cause="user", from_hook=True)
        Conversation(self.ctx, self.repo_dir).record("event", by="worker-1", text="task #1 finished", source="worker",
                                                     wake=True)
        d = Deliverer(self.ctx, self.repo_dir, settle=0)
        path = tracker.files.pm_turn
        d.look(_Waiter(), {}, {})
        self.clock.advance(1.0)
        d.look(_Waiter(), {}, {})  # settles whatever the first look started
        stamps = []
        for _ in range(4):
            self.clock.advance(1.0)
            d.look(_Waiter(), {}, {})
            st = path.stat()
            stamps.append((st.st_ino, st.st_mtime_ns, st.st_size))
        self.assertEqual(len(set(stamps)), 1, stamps)
        self.assertEqual(self.hc.sent, [])
        undelivered = tracker.read().get("undelivered")
        self.assertEqual(undelivered["count"], 1)
        self.assertNotIn("waiting_seconds", json.loads(path.read_text())["undelivered"])

    def _legacy_inflight(self, tracker: TurnTracker, *, turn_now: int) -> None:
        import json
        tracker.files.pm_turn.parent.mkdir(parents=True, exist_ok=True)
        now = int(self.clock.time() * 1000)
        tracker.files.pm_turn.write_text(json.dumps({
            "inflight": {"msg_id": "old-inflight", "text": "typed before the upgrade", "term": "t1", "pre_turn": 1,
                         "at_ms": now - 120_000, "lease_until_ms": now - 60_000},
            "outbox": [],
            "recent_msg_ids": {"old-done": {"seq": 3, "offset": 10, "at_ms": now - 600_000}},
        }))
        self.hc._mutable_dict("t1")["turn"] = turn_now

    def test_18_legacy_inflight_that_landed_is_not_retyped_after_the_upgrade(self) -> None:
        """Fable review minor 6: an old `inflight` keeps its pre_turn as a C3 intent; the turn moved past it -> typed."""
        tracker = TurnTracker(self.ctx, self.repo_dir)
        self._legacy_inflight(tracker, turn_now=2)
        self.assertEqual(tracker.ensure_mailbox_migrated(), 1)
        res = tracker.send_user_message(msg_id="old-done", text="delivered before the upgrade")
        self.assertEqual((res["status"], res.get("deduped")), ("delivered", True))
        reg = self.ctx.store.registration(self.slug) or {}
        driver = EndpointDriver(self.ctx, self.repo_dir)
        for _ in range(3):
            driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(self.hc.sent, [])
        moved = [it for it in self._items_of_kind(tracker, "chat.user") if it.envelope.body.get("msg_id") == "old-inflight"]
        self.assertEqual([it.state for it in moved], ["typed"])

    def test_19_legacy_inflight_that_never_landed_is_typed_once(self) -> None:
        tracker = TurnTracker(self.ctx, self.repo_dir)
        self._legacy_inflight(tracker, turn_now=1)
        tracker.ensure_mailbox_migrated()
        reg = self.ctx.store.registration(self.slug) or {}
        driver = EndpointDriver(self.ctx, self.repo_dir)
        for _ in range(3):
            driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual([t for _, t in self.hc.sent], ["typed before the upgrade"])

    def test_20_project_view_sees_mailbox_state_and_overdue_messages(self) -> None:
        """Fable review #4: the UI reads where each message is (turn2.inbox), accepting is not a receipt, and a
        message past its SLA reaches the banner/status (alert.undelivered's ui outlet) with its routed targets."""
        from pmlib.events.deliver import Delivery
        from pmlib.events.supervisor import read_pm_turn_view
        tracker = TurnTracker(self.ctx, self.repo_dir)
        self.hc._mutable_dict("t1")["status"] = {"state": "blocked"}  # a dialog in the PM terminal
        res = tracker.send_user_message(msg_id="u-view-1", text="are you there?")
        self.assertEqual(res["status"], "queued")
        self.assertEqual(Conversation(self.ctx, self.repo_dir).receipts(), [])  # accepted is not "read"

        reg = self.ctx.store.registration(self.slug) or {}
        view = read_pm_turn_view(self.ctx, self.repo_dir, reg, term_info=self.hc.get_raw("t1"), revive=False)
        rows = [r for r in view["turn2"]["inbox"] if r["id"] == "u-view-1"]
        self.assertEqual([(r["state"], r["hold_reason"], r["sending"]) for r in rows], [("accepted", "blocked_prompt", False)])
        self.assertEqual(view["turn2"]["undelivered"]["count"], 1)

        self.assertIsNone((Delivery(self.ctx, self.repo_dir).undelivered_status(live_state="blocked") or {}).get("messages"))
        self.clock.advance(150.0)  # past the 2-minute SLA of a user message
        undel = Delivery(self.ctx, self.repo_dir).undelivered_status(live_state="blocked")
        self.assertEqual((undel["messages"], undel["message_reason"]), (1, "blocked_prompt"))
        self.assertGreaterEqual(undel["waiting_seconds"], 150)

        EndpointDriver(self.ctx, self.repo_dir).drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        item = tracker.pm_mailbox.get(res["env_id"])
        self.assertEqual(item.state, "accepted")
        self.assertIn(f"ui://{self.slug}", item.meta["undelivered_alert"]["targets"])
        alerted = [r for r in tracker.read()["inbox"] if r["id"] == "u-view-1"]
        self.assertTrue(alerted[0]["alerted"])

        # Once the dialog is gone it is typed; the view follows (delivered, then read by the hook, then answered).
        self.hc._mutable_dict("t1")["status"] = {"state": "idle"}
        EndpointDriver(self.ctx, self.repo_dir).drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        typed = [r for r in tracker.read()["inbox"] if r["id"] == "u-view-1"]
        self.assertEqual(typed[0]["state"], "typed")
        self.assertIsNone(Delivery(self.ctx, self.repo_dir).undelivered_status(live_state="idle"))

    def test_21_batch_turn_closed_on_idle_before_the_stop_hook_is_not_retyped(self) -> None:
        """The supervisor can close a turn on hc idle (outcome inferred `silent`) before the Stop hook or the agy
        transcript says it replied: that is not evidence of an unhandled batch, so the batch is not sent again."""
        from pmlib.events.supervisor import ProjectSupervisor
        tracker = TurnTracker(self.ctx, self.repo_dir)
        Conversation(self.ctx, self.repo_dir).record("event", by="worker-1", text="task #7 finished", source="worker", wake=True)
        dlv = Delivery(self.ctx, self.repo_dir, settle=0)
        start, end, items = dlv.pending_batch()
        now_ms = int(self.clock.time() * 1000)
        batch_env_id = new_env_id(now_ms)
        tracker.pm_mailbox.enqueue(Envelope(
            env_id=batch_env_id, idempotency_key=f"batch:{self.slug}:{start}-{end}", schema_version=1, created_ms=now_ms,
            kind="event.batch", sender=Principal.supervisor(self.slug), recipient=LogicalAddress.pm(self.slug),
            project=self.slug, cause={"kind": "deliver_batch", "start": start, "end": end}, priority=P4_BATCH,
            body={"text": dlv.batch_text(start, end, items, env_id=batch_env_id), "start": start, "end": end},
            require_reply=True,
        ), initial_state="accepted")
        reg = self.ctx.store.registration(self.slug) or {}
        driver = EndpointDriver(self.ctx, self.repo_dir)
        driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 1)

        # The PM's hook takes the batch and starts the turn; the terminal works, then goes idle.
        dlv.took_delivery(self.hc.sent[0][1])
        tracker.begin_turn(terminal="hc:t1", agent_kind="claude", cause="deliver", batch=[start, end], from_hook=True)
        sup = ProjectSupervisor(self.ctx, self.repo_dir)
        row = self.hc._mutable_dict("t1")
        row.update({"status": {"state": "working"}, "status_ms": 2_000})
        self.clock.advance(1.0)
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))
        row.update({"status": {"state": "idle"}, "turn": 2, "status_ms": 5_000})
        self.clock.advance(5.0)
        sup.observe_and_reduce(reg, self.hc.get_raw("t1"))  # closes the turn before the Stop hook
        self.assertEqual(tracker.pm_mailbox.get(batch_env_id).state, "answered")
        tracker.end_turn(has_reply=True)  # the Stop hook, late
        for _ in range(3):
            self.clock.advance(1.0)
            driver.drive_pm_endpoint(reg, self.hc.get_raw("t1"))
        self.assertEqual(len(self.hc.sent), 1)
        self.assertEqual(tracker.pm_mailbox.get(batch_env_id).state, "answered")

    def test_22_project_events_contract_carries_msg_ids_and_their_inbox_rows(self) -> None:
        """What the project view reads (`pm.py project events <slug> --limit N`, model.js projectEventsArgv): each
        user event names its msg_id, and turn2.inbox has the row with that id (the line under the message)."""
        import json
        tracker = TurnTracker(self.ctx, self.repo_dir)
        self.hc._mutable_dict("t1")["status"] = {"state": "blocked"}
        tracker.send_user_message(msg_id="u-contract-1", text="first, still queued")
        self.hc._mutable_dict("t1")["status"] = {"state": "idle"}
        res2 = tracker.send_user_message(msg_id="u-contract-2", text="second, typed")
        tracker.pm_mailbox.transition(res2["env_id"], "typed", now_ms=int(self.clock.time() * 1000))
        tracker.sync_mailbox_projection()
        code, out_s, err_s = run_main(self.ctx, "project", "events", self.slug, "--limit", "200")
        self.assertEqual(code, 0, err_s)
        got = json.loads(out_s)
        users = {e["msg_id"]: e for e in got["events"] if e.get("type") == "user"}
        self.assertEqual(set(users), {"u-contract-1", "u-contract-2"})
        rows = {r["id"]: r for r in got["turn2"]["inbox"] if r.get("kind") == "user"}
        self.assertEqual({k: rows[k]["state"] for k in users}, {"u-contract-1": "accepted", "u-contract-2": "typed"})
        self.assertEqual(rows["u-contract-1"]["hold_reason"], "blocked_prompt")
        self.assertEqual(got["turn2"]["undelivered"]["count"], 1)
        self.assertEqual(got.get("receipts") or [], [])

    def test_23_reply_less_send_with_started_false_closes_unless_its_sender_retries(self) -> None:
        """FINDINGS-2 minor 3: a notify typed with started=false (a draft in the terminal) was still typed: it closes.
        Only the seat opening prompt (cause.retry_unstarted) stays typed for its retry, whoever typed it."""
        from pmlib.events.supervisor import deliver_under_typist_lock
        from pmlib.messaging.envelope import P0_CONTROL
        hc = self._seat_hc([False, False, False])
        ep = Endpoint(runtime="hc", machine=None, terminal="t1", epoch=1)
        out = deliver_under_typist_lock(self.ctx, ep, self._notify_env("[from w] behind a draft"), repo=self.repo_dir)
        self.assertEqual((out.status, out.started_turn), ("typed", False))
        tracker = TurnTracker(self.ctx, self.repo_dir)
        notes = self._items_of_kind(tracker, "event.notify")
        self.assertEqual([(it.state, it.meta.get("closed")) for it in notes], [("answered", "no_reply_needed")])

        # The driver types a seat opening prompt (lease was busy for the seat): it keeps it typed for the retry.
        now_ms = int(self.clock.time() * 1000)
        tracker.pm_mailbox.enqueue(Envelope(
            env_id=new_env_id(now_ms), idempotency_key="seat_opening:t1:drv", schema_version=1, created_ms=now_ms,
            kind="cmd.send", sender=Principal.supervisor(self.slug), recipient=LogicalAddress.pm(self.slug),
            project=self.slug, cause={"kind": "seat_opening_prompt", "retry_unstarted": True}, priority=P0_CONTROL,
            body={"text": "opening typed by the driver"},
        ), initial_state="accepted", target_endpoint_uid=ep.uid, endpoint_epoch=1)
        EndpointDriver(self.ctx, self.repo_dir).drive_pm_endpoint(
            self.ctx.store.registration(self.slug) or {}, hc.get_raw("t1"))
        self.assertEqual(tracker.pm_mailbox.get_by_key("seat_opening:t1:drv").state, "typed")
        self.assertEqual(len(hc.sent), 2)

    def test_12_no_repo_caller_shares_the_pm_endpoint_lease(self) -> None:
        """Review 07:02 #3a: without a repo the lease is still the endpoint's one, and the PM mailbox is found."""
        from pmlib.events.supervisor import deliver_under_typist_lock
        tracker = TurnTracker(self.ctx, self.repo_dir)
        ep = Endpoint(runtime="hc", machine=None, terminal="t1", epoch=1)
        now_ms = int(self.clock.time() * 1000)
        self.assertTrue(tracker.pm_mailbox.acquire_typist_lease(ep.uid, 777_777, ttl_ms=60_000, now_ms=now_ms))
        env = self._notify_env("no repo given")
        self.assertIsNone(deliver_under_typist_lock(self.ctx, ep, env))
        self.assertEqual(self.hc.sent, [])
        self.assertEqual(tracker.pm_mailbox.get(env.env_id).state, "accepted")  # in the drained PM mailbox
        self.assertFalse((self.ctx.home.root / "mailboxes" / "endpoints").exists())
        tracker.pm_mailbox.release_typist_lease(ep.uid, 777_777)

        # An endpoint no project owns: its own mailbox, but the same shared lease directory.
        ep9 = Endpoint(runtime="hc", machine=None, terminal="t9", epoch=1)
        other = MailboxStore(pathlib.Path(self._tmp.name) / "elsewhere", typist_dir=self.ctx.home.typists)
        self.assertTrue(other.acquire_typist_lease(ep9.uid, 777_778, ttl_ms=120_000, now_ms=now_ms))
        out = deliver_under_typist_lock(self.ctx, ep9, self._notify_env("to t9"))
        self.assertEqual((out.status, out.detail), ("rejected", "typist_busy"))
        self.assertEqual(self.hc.sent, [])

    def test_7_project_send_accepts_leading_dash_tokens(self) -> None:
        import json
        samples = [
            (["project", "send", self.slug, "--msg-id", "dash-1", "--", "-x"], "-x"),
            (["project", "send", self.slug, "--msg-id", "dash-2", "--", "--help"], "--help"),
            (["project", "send", self.slug, "--msg-id", "dash-3", "--text", "-x"], "-x"),
            (["project", "send", self.slug, "--msg-id", "dash-4", "--text", "--help"], "--help"),
            (["project", "send", self.slug, "--msg-id", "dash-5", "-x"], "-x"),
        ]
        tracker = TurnTracker(self.ctx, self.repo_dir)
        for argv, expected in samples:
            code, out_s, err_s = run_main(self.ctx, *argv)
            self.assertEqual(code, 0, msg=f"argv={argv} stderr={err_s}")
            payload = json.loads(out_s)
            self.assertIn(payload["status"], ("accepted", "queued"), msg=f"failed for argv={argv}")
            item = tracker.pm_mailbox.get(payload["env_id"])
            self.assertIsNotNone(item)
            self.assertEqual(item.envelope.body.get("text"), expected)


    def test_24_undelivered_alert_reaches_discord_when_on_and_a_failing_sink_never_blocks_it(self) -> None:
        """Phase 3b: `alert.undelivered` also goes to the human channels its route names besides the view and
        status (hub: `pm.py state`; Discord when configured), off the deliverer's loop; a sink that fails does
        not keep the alert from being marked sent (no re-alert every look)."""
        from pmlib.discord import DiscordMirror
        from pmlib.events.deliverer import Deliverer
        tracker = TurnTracker(self.ctx, self.repo_dir)
        self.hc._mutable_dict("t1")["status"] = {"state": "blocked"}
        res = tracker.send_user_message(msg_id="u-alert-1", text="still there?")
        self.clock.advance(150.0)
        reg = self.ctx.store.registration(self.slug) or {}

        def broken_sink(*_a):
            raise OSError("discord down")

        EndpointDriver(self.ctx, self.repo_dir).drive_pm_endpoint(reg, self.hc.get_raw("t1"),
                                                                 on_undelivered_alert=broken_sink)
        item = tracker.pm_mailbox.get(res["env_id"])
        self.assertTrue(item.meta.get("undelivered_alerted"))
        targets = item.meta["undelivered_alert"]["targets"]
        self.assertIn(f"discord://{self.slug}", targets)
        self.assertIn("hub://local", targets)

        # The deliverer hands the alert to every sink of the context, with its route's targets.
        got = []
        self.ctx.alert_sinks = (lambda slug, repo, alert: got.append((slug, repo, alert)),)
        alert_env = type("E", (), {"body": {"env_id": res["env_id"], "wait_seconds": 150, "reason": "blocked_prompt"}})()
        decision = type("D", (), {"targets": tuple(targets)})()
        Deliverer(self.ctx, self.repo_dir)._undelivered_alert(item, alert_env, decision)
        self.assertEqual([(s, r, a["wait_seconds"], a["kind"]) for s, r, a in got],
                         [(self.slug, str(self.repo_dir), 150, "chat.user")])

        # Discord: posted only when it is on and the PM's registration has a channel.
        posts = []
        mirror = DiscordMirror(self.ctx, api_fn=lambda m, path, body: posts.append((m, path, body)) or {"id": "1"})
        alert = {"wait_seconds": 150, "reason": "blocked_prompt", "targets": list(targets)}
        self.assertFalse(mirror.alert_undelivered(self.slug, str(self.repo_dir), alert, background=False))  # off
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text('{"discord": true}', encoding="utf-8")
        self.assertFalse(mirror.alert_undelivered(self.slug, str(self.repo_dir), alert, background=False))  # no channel
        self.ctx.store.change_registration(self.slug, lambda cur: {**cur, "discord": {"channel_id": "c-9"}})
        self.assertTrue(mirror.alert_undelivered(self.slug, str(self.repo_dir), alert, background=False))
        self.assertEqual([(m, path) for m, path, _b in posts], [("POST", "/channels/c-9/messages")])
        self.assertIn("2 min", posts[0][2]["content"])
        self.assertFalse(mirror.alert_undelivered(self.slug, str(self.repo_dir), {**alert, "targets": ["ui://x"]},
                                                  background=False))  # not routed there

if __name__ == "__main__":
    unittest.main()
