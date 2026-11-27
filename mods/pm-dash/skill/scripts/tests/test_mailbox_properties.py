"""Property & crash-injection tests for Layer 2 `MailboxStore` (§3.7, §10.2, C1-C5, G4-G5)."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pmlib.messaging.address import LogicalAddress
from pmlib.messaging.envelope import P0_CONTROL, P1_USER, P2_RESUME, P4_BATCH, Envelope, new_env_id
from pmlib.messaging.mailbox import MailboxStore
from pmlib.messaging.principal import Principal
from pmlib.store import StoreError


def _mk_env(
    *,
    kind: str = "chat.user",
    priority: int = P1_USER,
    text: str = "hello",
    idem_key: str = "",
    env_id: str | None = None,
    require_reply: bool = True,
    max_attempts: int = 3,
) -> Envelope:
    eid = env_id or new_env_id()
    return Envelope(
        env_id=eid,
        idempotency_key=idem_key,
        schema_version=1,
        created_ms=1_700_000_000_000,
        kind=kind,
        sender=Principal.user("proj"),
        recipient=LogicalAddress.pm("proj"),
        project="proj",
        cause={"kind": "test"},
        priority=priority,
        body={"text": text, "msg_id": eid},
        require_reply=require_reply,
        max_attempts=max_attempts,
    )


class TestMailboxProperties(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_monotonic_seq_priority_order_and_idempotency(self) -> None:
        mb = MailboxStore(self.root / "mb", segment_max_bytes=512, archive_keep=1)
        e_batch, c1 = mb.enqueue(_mk_env(kind="event.batch", priority=P4_BATCH, text="batch1", idem_key="k-b1"))
        e_user1, c2 = mb.enqueue(_mk_env(kind="chat.user", priority=P1_USER, text="u1", idem_key="k-u1"))
        e_user2, c3 = mb.enqueue(_mk_env(kind="chat.user", priority=P1_USER, text="u2", idem_key="k-u2"))
        e_ctrl, c4 = mb.enqueue(_mk_env(kind="ctrl.interrupt", priority=P0_CONTROL, text="esc", idem_key="k-c1"))
        e_dup, c5 = mb.enqueue(_mk_env(kind="chat.user", priority=P1_USER, text="u1", idem_key="k-u1"))

        self.assertTrue(all((c1, c2, c3, c4)))
        self.assertFalse(c5)
        self.assertEqual(e_dup.envelope.env_id, e_user1.envelope.env_id)
        self.assertLess(e_batch.seq, e_user1.seq)
        self.assertLess(e_user1.seq, e_user2.seq)
        self.assertLess(e_user2.seq, e_ctrl.seq)

        pending = mb.pending_for_endpoint()
        self.assertEqual(
            [it.envelope.env_id for it in pending],
            [e_ctrl.envelope.env_id, e_user1.envelope.env_id, e_user2.envelope.env_id, e_batch.envelope.env_id],
        )

    def test_illegal_transition_rejected(self) -> None:
        mb = MailboxStore(self.root / "mb")
        item, _ = mb.enqueue(_mk_env(idem_key="k-1"))
        mb.transition(item.envelope.env_id, "typed", endpoint_epoch=1)
        mb.transition(item.envelope.env_id, "consumed", turn_id="t-1")
        done = mb.transition(item.envelope.env_id, "answered", turn_id="t-1")
        self.assertEqual(done.state, "answered")
        with self.assertRaises(StoreError):
            mb.transition(item.envelope.env_id, "accepted")
        with self.assertRaises(StoreError):
            mb.transition(item.envelope.env_id, "failed")

    def test_c1_torn_tail_and_c2_corrupt_snapshot_recovery(self) -> None:
        mb = MailboxStore(self.root / "mb")
        it1, _ = mb.enqueue(_mk_env(text="first", idem_key="k-1"), now_ms=1000)
        it2, _ = mb.enqueue(_mk_env(text="second", idem_key="k-2"), now_ms=2000)
        mb.transition(it1.envelope.env_id, "typed", endpoint_epoch=1, now_ms=2100)

        seg = sorted((self.root / "mb").glob("mailbox.*.jsonl"))[-1]
        with open(seg, "ab") as f:
            f.write(b'{"rec":"st","env_id":"corrupt_partial_line')
        mb.state_path.write_text("{broken json", encoding="utf-8")

        reopened = MailboxStore(self.root / "mb")
        got1 = reopened.get(it1.envelope.env_id)
        got2 = reopened.get(it2.envelope.env_id)
        self.assertIsNotNone(got1)
        self.assertEqual(got1.state, "typed")
        self.assertIsNotNone(got2)
        self.assertEqual(got2.state, "accepted")
        it3, created3 = reopened.enqueue(_mk_env(text="third", idem_key="k-3"), now_ms=3000)
        self.assertTrue(created3)
        self.assertGreater(it3.seq, it1.seq)

    def test_c3_intent_g4_epoch_requeue_and_g5_turn_outcome(self) -> None:
        mb = MailboxStore(self.root / "mb")
        it, _ = mb.enqueue(_mk_env(text="hello", idem_key="k-u1", max_attempts=3), target_endpoint_uid="ep1", endpoint_epoch=1)
        with_intent = mb.record_intent(it.envelope.env_id, pre_turn=4, pre_status_ms=1000, attempt=1, endpoint_uid="ep1")
        self.assertIsNotNone(with_intent.intent)
        self.assertEqual(with_intent.intent["pre_turn"], 4)

        typed = mb.transition(it.envelope.env_id, "typed", attempts=1, endpoint_epoch=1, clear_intent=True)
        self.assertIsNone(typed.intent)
        self.assertEqual(typed.state, "typed")

        requeued = mb.requeue_unconsumed_on_epoch_change(2, endpoint_uid="ep1")
        self.assertEqual(len(requeued), 1)
        self.assertEqual(requeued[0].state, "accepted")
        self.assertEqual(requeued[0].endpoint_epoch, 2)

        # A user message the coordinator read ends answered whatever its turn's outcome (an Esc is the user's
        # call, never an automatic retype); the outcome is kept.
        mb.transition(it.envelope.env_id, "typed", attempts=1, endpoint_epoch=2)
        mb.transition(it.envelope.env_id, "consumed", turn_id="turn-1")
        after_esc = mb.reconcile_turn_outcome("turn-1", "interrupted")
        self.assertEqual([(x.state, x.meta.get("turn_outcome")) for x in after_esc], [("answered", "interrupted")])

        # A batch is done only when its turn replied (G5): otherwise it goes back for another attempt.
        b, _ = mb.enqueue(_mk_env(kind="event.batch", priority=P4_BATCH, text="batch", idem_key="k-b1"),
                          target_endpoint_uid="ep1", endpoint_epoch=2)
        mb.transition(b.envelope.env_id, "typed", attempts=1, endpoint_epoch=2)
        mb.transition(b.envelope.env_id, "consumed", turn_id="turn-3")
        retry = mb.reconcile_turn_outcome("turn-3", "interrupted")
        self.assertEqual([(x.state, x.attempts) for x in retry], [("accepted", 2)])
        mb.transition(b.envelope.env_id, "typed", attempts=2, endpoint_epoch=2)
        mb.transition(b.envelope.env_id, "consumed", turn_id="turn-4")
        after_reply = mb.reconcile_turn_outcome("turn-4", "replied")
        self.assertEqual(len(after_reply), 1)
        self.assertEqual(after_reply[0].state, "answered")

        # `cmd.resume_turn` is governed by W1/W2 recovery ladders (20s/90s backoff & circuit breakers),
        # so G5 must settle it as `answered` on error/interrupt rather than 0s-requeueing it!
        r_env, _ = mb.enqueue(
            _mk_env(kind="cmd.resume_turn", priority=P2_RESUME, text="[from pm.py supervisor] resume", idem_key="k-r1"),
            target_endpoint_uid="ep1",
            endpoint_epoch=2,
        )
        mb.transition(r_env.envelope.env_id, "typed", attempts=1, endpoint_epoch=2)
        mb.transition(r_env.envelope.env_id, "consumed", turn_id="turn-5")
        after_err = mb.reconcile_turn_outcome("turn-5", "errored")
        self.assertEqual([(x.state, x.meta.get("turn_outcome")) for x in after_err], [("answered", "errored")])

        # Unconsumed `cmd.resume_turn` from an old session epoch expires on rotation instead of retyping into the new session.
        r_old, _ = mb.enqueue(
            _mk_env(kind="cmd.resume_turn", priority=P2_RESUME, text="[from pm.py supervisor] old", idem_key="k-r2"),
            target_endpoint_uid="ep1",
            endpoint_epoch=2,
        )
        mb.transition(r_old.envelope.env_id, "typed", attempts=1, endpoint_epoch=2)
        self.assertEqual(mb.requeue_unconsumed_on_epoch_change(3, endpoint_uid="ep2"), [])
        self.assertEqual(mb.get(r_old.envelope.env_id).state, "expired")

    def test_g4_new_session_expires_reply_less_typed_items_and_retargets_queued_ones(self) -> None:
        """A rotation never retypes the old seat's opening prompt or notifies into the new session (no receipt ever
        ends them), still requeues unanswered user messages, and moves untyped ones to the new endpoint."""
        mb = MailboxStore(self.root / "mb")
        opening, _ = mb.enqueue(_mk_env(kind="cmd.send", priority=P0_CONTROL, text="you are the PM", idem_key="seat-1",
                                        require_reply=False), target_endpoint_uid="hc:local:t1", endpoint_epoch=1)
        notify, _ = mb.enqueue(_mk_env(kind="event.notify", priority=P4_BATCH, text="[from w] done", idem_key="n-1",
                                       require_reply=False), target_endpoint_uid="hc:local:t1", endpoint_epoch=1)
        user_typed, _ = mb.enqueue(_mk_env(text="answer me", idem_key="u-1"), target_endpoint_uid="hc:local:t1",
                                   endpoint_epoch=1)
        user_queued, _ = mb.enqueue(_mk_env(text="later", idem_key="u-2"), target_endpoint_uid="hc:local:t1",
                                    endpoint_epoch=1)
        for it in (opening, notify, user_typed):
            mb.transition(it.envelope.env_id, "typed", endpoint_epoch=1)

        requeued = mb.requeue_unconsumed_on_epoch_change(2, endpoint_uid="hc:local:t2")
        self.assertEqual([it.envelope.env_id for it in requeued], [user_typed.envelope.env_id])
        self.assertEqual(mb.get(opening.envelope.env_id).state, "expired")
        self.assertEqual(mb.get(notify.envelope.env_id).state, "expired")
        again = mb.get(user_typed.envelope.env_id)
        self.assertEqual((again.state, again.target_endpoint_uid, again.endpoint_epoch), ("accepted", "hc:local:t2", 2))
        moved = mb.get(user_queued.envelope.env_id)
        self.assertEqual((moved.state, moved.target_endpoint_uid), ("accepted", "hc:local:t2"))
        self.assertEqual(
            {it.envelope.env_id for it in mb.pending_for_endpoint("hc:local:t2")},
            {user_typed.envelope.env_id, user_queued.envelope.env_id},
        )

    def test_typist_lease_is_per_owner_token_shared_dir_and_renewable(self) -> None:
        shared = self.root / "typists"
        a = MailboxStore(self.root / "pm", typist_dir=shared)
        b = MailboxStore(self.root / "endpoint", typist_dir=shared)
        self.assertTrue(a.acquire_typist_lease("hc:local:t1", 100, ttl_ms=10_000, now_ms=0, owner="100:driver:x"))
        # Another mailbox, same endpoint: excluded, even from the same pid under another token.
        self.assertFalse(b.acquire_typist_lease("hc:local:t1", 100, ttl_ms=10_000, now_ms=1_000, owner="100:y"))
        self.assertFalse(b.acquire_typist_lease("hc:local:t1", 200, ttl_ms=10_000, now_ms=1_000))
        # The holder renews past its first expiry; nobody else gets in meanwhile.
        self.assertTrue(a.acquire_typist_lease("hc:local:t1", 100, ttl_ms=10_000, now_ms=9_000, owner="100:driver:x"))
        self.assertFalse(b.acquire_typist_lease("hc:local:t1", 200, ttl_ms=10_000, now_ms=15_000))
        self.assertEqual(a.typist_lease_holder("hc:local:t1", now_ms=15_000)["acquired_ms"], 0)
        # Release by someone else is a no-op; by the holder it frees the endpoint.
        b.release_typist_lease("hc:local:t1", 200)
        self.assertIsNotNone(b.typist_lease_holder("hc:local:t1", now_ms=15_000))
        a.release_typist_lease("hc:local:t1", 100, owner="100:driver:x")
        self.assertTrue(b.acquire_typist_lease("hc:local:t1", 200, ttl_ms=10_000, now_ms=16_000))
        # An expired lease is taken over.
        self.assertTrue(a.acquire_typist_lease("hc:local:t1", 300, ttl_ms=10_000, now_ms=26_001))

    def test_idempotency_window_outlives_the_completed_item_cache(self) -> None:
        """A key dedupes for the whole `recent_keys` window (2048), not only while its finished item is still in
        `recent_completed` (64): a UI retry of an old msg_id must not be typed again."""
        mb = MailboxStore(self.root / "mb")
        first = None
        for idx in range(70):
            it, _ = mb.enqueue(_mk_env(text=f"m{idx}", idem_key=f"ui:proj:m{idx}"))
            first = first or it
            for st in ("typed", "consumed", "answered"):
                mb.transition(it.envelope.env_id, st)
        again, created = mb.enqueue(_mk_env(text="m0", idem_key="ui:proj:m0"))
        self.assertFalse(created)
        self.assertEqual((again.state, again.envelope.env_id), ("answered", first.envelope.env_id))
        self.assertEqual(mb.active_items(), [])

    def test_segment_rollover_and_compaction(self) -> None:
        mb = MailboxStore(self.root / "mb", segment_max_bytes=400, archive_keep=1)
        mb.set_acked_seq(1)
        envs = []
        for idx in range(6):
            it, _ = mb.enqueue(_mk_env(text=f"message payload {idx} " + ("x" * 60), idem_key=f"seg-{idx}"))
            envs.append(it)
            mb.transition(it.envelope.env_id, "typed", endpoint_epoch=1)
            mb.transition(it.envelope.env_id, "consumed", turn_id=f"t-{idx}")
            mb.transition(it.envelope.env_id, "answered", turn_id=f"t-{idx}")

        segs_before = sorted((self.root / "mb").glob("mailbox.*.jsonl"))
        self.assertGreater(len(segs_before), 2)
        mb.set_acked_seq(envs[-1].seq + 10)
        segs_after = sorted((self.root / "mb").glob("mailbox.*.jsonl"))
        self.assertLessEqual(len(segs_after), 2)

    def test_legacy_pm_turn_migration_one_time(self) -> None:
        pm_turn = self.root / "pm-turn.json"
        pm_turn.write_text(json.dumps({
            "inflight": {"msg_id": "m-inf", "text": "in flight q", "at_ms": 111},
            "outbox": [{"msg_id": "m-out", "text": "queued q", "queued_ms": 222, "reason": "pm_working"}],
            "recent_msg_ids": {"m-done": {"state": "answered"}},
        }), encoding="utf-8")
        legacy_inbox = self.root / "inbox-t1.jsonl"
        legacy_inbox.write_text(
            json.dumps({"msg_id": "m-jsonl", "kind": "user", "text": "from jsonl", "state": "queued"}) + "\n",
            encoding="utf-8",
        )
        mb = MailboxStore(self.root / "mb")
        count = mb.migrate_legacy_pm_state(pm_turn, legacy_inbox, project="proj")
        self.assertEqual(count, 3)
        self.assertEqual(mb.migrate_legacy_pm_state(pm_turn, legacy_inbox, project="proj"), 0)
        # Seeded into recent_keys as historical: a retry of it dedupes (tombstone), and it is never queued again.
        done = mb.get_by_key("ui:proj:m-done")
        self.assertEqual((done.state, done.meta.get("compacted")), ("answered", True))
        self.assertNotIn("legacy:m-done", {it.envelope.env_id for it in mb.active_items()})
        texts = {it.envelope.body.get("text") for it in mb.active_items()}
        self.assertEqual(texts, {"in flight q", "queued q", "from jsonl"})


if __name__ == "__main__":
    unittest.main()
