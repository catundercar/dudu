"""Tests for Layer 2 Router (§4.2.1 reactions, §4.2.2 routing, §4.3 3-tier readiness) and Principal Authz (§8.2)."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pmlib.messaging.address import Endpoint, LogicalAddress, parse_legacy_endpoint
from pmlib.messaging.authz import authorize_envelope
from pmlib.messaging.envelope import P0_CONTROL, P1_USER, P2_RESUME, P3_DIRECT, P4_BATCH, Envelope
from pmlib.messaging.principal import Principal
from pmlib.messaging.router import (
    EndpointSnapshot,
    Router,
    RoutingSnapshot,
    evaluate_batch_readiness,
    plan_task_reactions,
)


def _ep(terminal: str = "t1", epoch: int = 1, runtime: str = "hc") -> Endpoint:
    return Endpoint(
        runtime=runtime,
        machine=None,
        terminal=terminal,
        workspace="/repo",
        agent_kind="claude",
        epoch=epoch,
    )


def _env(
    kind: str,
    *,
    sender_role: str = "user",
    sender_id: str = "u1",
    sender_task_id: str = "",
    sender_epoch: int = 1,
    recipient: str = "pm://proj",
    priority: int = P1_USER,
    body: dict | None = None,
    cause: dict | None = None,
    coalesce_key: str = "",
    idem_key: str = "",
    env_id: str = "env_000000000001_aaaaaaaa",
) -> Envelope:
    return Envelope(
        env_id=env_id,
        idempotency_key=idem_key,
        schema_version=1,
        created_ms=1_700_000_000_000,
        kind=kind,
        sender=Principal(role=sender_role, actor_id=sender_id, project="proj", task_id=sender_task_id, epoch=sender_epoch),
        recipient=LogicalAddress.parse(recipient),
        project="proj",
        cause=dict(cause or {}),
        priority=priority,
        body=dict(body or {}),
        coalesce_key=coalesce_key,
    )


class TestLegacyEndpointParser(unittest.TestCase):
    def test_parses_all_legacy_pane_formats(self) -> None:
        bare_hc = parse_legacy_endpoint("t7", runtime_hint="hc")
        self.assertIsNotNone(bare_hc)
        self.assertEqual((bare_hc.runtime, bare_hc.terminal), ("hc", "t7"))

        hc = parse_legacy_endpoint("hc:t9")
        self.assertIsNotNone(hc)
        self.assertEqual((hc.runtime, hc.terminal), ("hc", "t9"))

        tui_colon = parse_legacy_endpoint("sess/%5:0")
        self.assertIsNotNone(tui_colon)
        self.assertEqual((tui_colon.runtime, tui_colon.workspace, tui_colon.terminal), ("tui", "sess", "%5:0"))

        tui_slash = parse_legacy_endpoint("sess/%5", runtime_hint="tui")
        self.assertIsNotNone(tui_slash)
        self.assertEqual((tui_slash.runtime, tui_slash.terminal), ("tui", "sess/%5"))

        remote = parse_legacy_endpoint("mac-mini/t3")
        self.assertIsNotNone(remote)
        self.assertEqual((remote.runtime, remote.machine, remote.terminal), ("hc", "mac-mini", "t3"))

        sh = parse_legacy_endpoint("sh:gpu1/w2")
        self.assertIsNotNone(sh)
        self.assertEqual((sh.runtime, sh.machine, sh.terminal), ("self_hosted", "gpu1", "w2"))

        self.assertIsNone(parse_legacy_endpoint(""))


class TestReactionTable(unittest.TestCase):
    def test_duplicate_running_commit_suppresses_wake(self) -> None:
        plan = plan_task_reactions(
            task={"id": "t-1", "status": "review"},
            changes=["commit=abc1234"],
            entry_fields={"wake": True, "source": "worker"},
            will_auto_review=False,
            skip_reason="duplicate running commit",
            commit="abc1234",
            resolved_sha="abc1234",
        )
        actions = [p.action for p in plan]
        self.assertNotIn("emit_task_updated", actions)
        self.assertIn("collect_research", actions)

    def test_auto_review_short_circuits_and_falls_back_on_error(self) -> None:
        ok_plan = plan_task_reactions(
            task={"id": "t-1", "status": "review"},
            changes=["status=review"],
            entry_fields={"wake": True, "source": "worker"},
            will_auto_review=True,
            resolved_sha="abc",
            commit="abc",
        )
        self.assertEqual([p.action for p in ok_plan], ["collect_research", "run_auto_review"])

        fail_plan = plan_task_reactions(
            task={"id": "t-1", "status": "review"},
            changes=["status=review"],
            entry_fields={"wake": True, "source": "worker"},
            will_auto_review=True,
            auto_review_failed=True,
            resolved_sha="abc",
            commit="abc",
        )
        self.assertEqual(
            [p.action for p in fail_plan],
            ["collect_research", "run_auto_review", "emit_task_updated"],
        )

    def test_worker_merged_e04_e05_and_retire_and_rollup(self) -> None:
        plan = plan_task_reactions(
            task={"id": "t-1", "status": "merged", "dispatched": True, "parent": "ep-1"},
            changes=["status=merged"],
            entry_fields={"wake": False, "source": "worker"},
            is_pm_caller=False,
            moved_status="merged",
            old_parent="ep-0",
        )
        actions = [p.action for p in plan]
        self.assertIn("emit_task_updated", actions)
        self.assertIn("retire_workspace", actions)
        self.assertIn("reconcile_dependents", actions)
        self.assertIn("rollup_ancestors", actions)


class TestEvaluateBatchReadiness(unittest.TestCase):
    def test_tier1_reported_states(self) -> None:
        idle = EndpointSnapshot(agent_state="idle", can_report_status=True)
        self.assertEqual(evaluate_batch_readiness(idle), (True, True, ""))

        busy = EndpointSnapshot(agent_state="working", can_report_status=True)
        self.assertEqual(evaluate_batch_readiness(busy), (False, False, "pm_working"))

        dlg = EndpointSnapshot(agent_state="idle", can_report_status=True, blocking_dialog=True)
        self.assertEqual(evaluate_batch_readiness(dlg), (False, False, "blocked_prompt"))

        bg = EndpointSnapshot(
            agent_state="working", status_msg="2 shells still running",
            can_report_status=True, last_turn_stopped=True,
        )
        self.assertEqual(evaluate_batch_readiness(bg), (True, False, ""))

        bg_running = EndpointSnapshot(
            agent_state="working", status_msg="2 shells still running",
            can_report_status=True, last_turn_stopped=False,
        )
        self.assertEqual(evaluate_batch_readiness(bg_running), (False, False, "pm_working"))

    def test_tier2_hooks_and_esc_fallback(self) -> None:
        stopped = EndpointSnapshot(can_report_status=False, last_turn_stopped=True)
        self.assertEqual(evaluate_batch_readiness(stopped), (True, False, ""))

        working = EndpointSnapshot(
            can_report_status=False, last_turn_stopped=False,
            screen_quiet_ms=5_000, step_quiet_ms=5_000, cpu_quiet_ms=5_000,
        )
        self.assertEqual(evaluate_batch_readiness(working), (False, False, "pm_working"))

        esc_aborted = EndpointSnapshot(
            can_report_status=False, last_turn_stopped=False,
            screen_quiet_ms=35_000, step_quiet_ms=35_000, cpu_quiet_ms=35_000,
        )
        self.assertEqual(evaluate_batch_readiness(esc_aborted), (True, False, ""))

    def test_tier3_blackbox_quiet_or_waited(self) -> None:
        cooling = EndpointSnapshot(
            can_report_status=False, last_turn_stopped=None,
            screen_quiet_ms=2_000, since_last_type_ms=30_000, waited_ms=2_000,
        )
        self.assertEqual(evaluate_batch_readiness(cooling), (False, False, "blackbox_cooldown"))

        quiet_ok = EndpointSnapshot(
            can_report_status=False, last_turn_stopped=None,
            screen_quiet_ms=12_000, since_last_type_ms=20_000, waited_ms=2_000,
        )
        self.assertEqual(evaluate_batch_readiness(quiet_ok), (True, False, ""))


class TestRouterRules(unittest.TestCase):
    def setUp(self) -> None:
        self.router = Router()
        self.pm_ep = _ep("t1", epoch=2)
        self.wk_ep = _ep("t2", epoch=3)
        self.snap = RoutingSnapshot(
            project="proj",
            endpoints={"pm://proj": self.pm_ep, "worker://t-1": self.wk_ep},
            endpoint_states={
                "pm://proj": EndpointSnapshot(endpoint=self.pm_ep, live_state="live", agent_state="idle", can_report_status=True),
                "worker://t-1": EndpointSnapshot(endpoint=self.wk_ep, live_state="live", agent_state="working", can_report_status=True),
            },
            tasks={"t-9": {"id": "t-9", "status": "merged"}, "t-1": {"id": "t-1", "status": "in_progress"}},
            active_coalesce_keys={"task:t-1": "env_existing"},
            known_idempotency_keys=frozenset({"idem-dup"}),
            active_turn_interrupts=frozenset({"turn-dup"}),
        )

    def test_routing_table_coverage(self) -> None:
        dec_live = self.router.route(
            _env("event.report_rejected", sender_role="supervisor", recipient="worker://t-1",
                 priority=P3_DIRECT, body={"task_id": "t-1", "sender_epoch": 3}),
            self.snap,
        )
        self.assertEqual((dec_live.rule_id, dec_live.action, dec_live.priority), ("R-REPORT-REJECTED", "deliver", P3_DIRECT))

        dec_gone = self.router.route(
            _env("event.report_rejected", sender_role="supervisor", recipient="worker://t-1",
                 priority=P3_DIRECT, body={"task_id": "t-1", "sender_epoch": 99}),
            self.snap,
        )
        self.assertEqual((dec_gone.rule_id, dec_gone.priority, dec_gone.endpoint), ("R-REPORT-REJECTED", P4_BATCH, self.pm_ep))

        dec_alert = self.router.route(
            _env("alert.undelivered", sender_role="supervisor", recipient="ui://proj", priority=P1_USER),
            self.snap,
        )
        self.assertEqual(dec_alert.action, "mirror_only")
        self.assertIn("hub://local", dec_alert.targets)
        self.assertIn("discord://proj", dec_alert.targets)

        dec_ctrl_dup = self.router.route(
            _env("ctrl.interrupt", priority=P0_CONTROL, cause={"turn_id": "turn-dup"}),
            self.snap,
        )
        self.assertEqual(dec_ctrl_dup.action, "drop_duplicate")
        dec_ctrl_ok = self.router.route(
            _env("ctrl.interrupt", priority=P0_CONTROL, cause={"turn_id": "turn-new"}),
            self.snap,
        )
        self.assertEqual((dec_ctrl_ok.action, dec_ctrl_ok.priority), ("deliver", P0_CONTROL))

        dec_dup = self.router.route(_env("chat.user", idem_key="idem-dup"), self.snap)
        self.assertEqual((dec_dup.rule_id, dec_dup.action), ("R-DEDUPE", "drop_duplicate"))

        err_snap = RoutingSnapshot(
            project="proj",
            endpoints={"pm://proj": self.pm_ep},
            endpoint_states={"pm://proj": EndpointSnapshot(endpoint=self.pm_ep, agent_state="error", can_report_status=True)},
        )
        dec_hold = self.router.route(_env("chat.user"), err_snap)
        self.assertEqual((dec_hold.action, dec_hold.hold_reason), ("hold", "pm is error"))
        self.assertEqual(self.router.route(_env("chat.user"), self.snap).action, "deliver")

        busy_snap = RoutingSnapshot(
            project="proj",
            endpoints={"pm://proj": self.pm_ep},
            endpoint_states={"pm://proj": EndpointSnapshot(endpoint=self.pm_ep, turn_phase="generating")},
        )
        dec_res = self.router.route(_env("cmd.resume_turn", sender_role="supervisor", priority=P2_RESUME), busy_snap)
        self.assertEqual((dec_res.action, dec_res.hold_reason), ("hold", "waiting_turn_leave_working"))

        dec_self = self.router.route(_env("event.task_updated", sender_role="pm", priority=P4_BATCH), self.snap)
        self.assertEqual((dec_self.rule_id, dec_self.action), ("R-SELF-SUPPRESS", "mirror_only"))
        dec_quiet = self.router.route(
            _env("event.task_updated", sender_role="worker", priority=P4_BATCH, body={"wake": False}),
            self.snap,
        )
        self.assertEqual((dec_quiet.rule_id, dec_quiet.action), ("R-QUIET", "mirror_only"))

        dec_moved = self.router.route(
            _env("event.batch", sender_role="supervisor", priority=P4_BATCH, body={"task_id": "t-9"}),
            self.snap,
        )
        self.assertEqual((dec_moved.rule_id, dec_moved.action), ("R-BATCH-PM", "drop_duplicate"))
        dec_coal = self.router.route(
            _env("event.batch", sender_role="supervisor", priority=P4_BATCH, coalesce_key="task:t-1", body={"task_id": "t-1"}),
            self.snap,
        )
        self.assertEqual((dec_coal.rule_id, dec_coal.action, dec_coal.coalesce_into_env_id), ("R-BATCH-PM", "coalesce", "env_existing"))

        hw_snap = RoutingSnapshot(
            project="proj",
            endpoints={"worker://t-1": self.wk_ep},
            endpoint_states={"worker://t-1": EndpointSnapshot(endpoint=self.wk_ep, helper_wait_active=True)},
            tasks={"t-1": {"id": "t-1", "status": "in_progress"}},
        )
        dec_hw = self.router.route(
            _env("event.helper_done", sender_role="helper", recipient="worker://t-1", priority=P4_BATCH),
            hw_snap,
        )
        self.assertEqual((dec_hw.rule_id, dec_hw.action), ("R-NOTIFY-WK", "mirror_only"))


class TestAuthorization(unittest.TestCase):
    def test_role_matrix(self) -> None:
        pm_ep = _ep("t1", epoch=5)
        snap = RoutingSnapshot(
            project="proj",
            endpoints={"pm://proj": pm_ep},
            tasks={
                "t-1": {"id": "t-1", "status": "review"},
                "t-approved": {"id": "t-approved", "status": "review", "land_approved": {"executor": "worker"}},
            },
        )
        self.assertFalse(authorize_envelope(
            Principal(role="worker", actor_id="worker:t-1", project="proj", task_id="t-1"),
            _env("cmd.send", sender_role="worker", recipient="pm://proj", priority=P3_DIRECT),
            snap,
        ).allowed)
        self.assertFalse(authorize_envelope(
            Principal(role="worker", actor_id="worker:t-1", project="proj", task_id="t-1"),
            _env("report.task_update", sender_role="worker", recipient="hub://local", body={"task_id": "t-other", "status": "review"}),
            snap,
        ).allowed)
        self.assertFalse(authorize_envelope(
            Principal(role="worker", actor_id="worker:t-1", project="proj", task_id="t-1"),
            _env("report.task_update", sender_role="worker", recipient="hub://local", body={"task_id": "t-1", "status": "merged"}),
            snap,
        ).allowed)
        self.assertTrue(authorize_envelope(
            Principal(role="worker", actor_id="worker:t-approved", project="proj", task_id="t-approved"),
            _env("report.task_update", sender_role="worker", recipient="hub://local", body={"task_id": "t-approved", "status": "merged"}),
            snap,
        ).allowed)

        stale_dec = authorize_envelope(
            Principal(role="pm", actor_id="pm:proj", project="proj", epoch=4),
            _env("cmd.approve_land", sender_role="pm", sender_epoch=4, recipient="worker://t-1", priority=P3_DIRECT),
            snap,
        )
        self.assertFalse(stale_dec.allowed)
        self.assertEqual(stale_dec.code, "stale_epoch")

        self.assertTrue(authorize_envelope(
            Principal(role="supervisor", actor_id="sup", project="proj"),
            _env("cmd.resume_turn", sender_role="supervisor", priority=P2_RESUME),
            snap,
        ).allowed)
        self.assertFalse(authorize_envelope(
            Principal(role="discord", actor_id="dc", project="proj"),
            _env("cmd.send", sender_role="discord", recipient="worker://t-1", priority=P3_DIRECT),
            snap,
        ).allowed)


if __name__ == "__main__":
    unittest.main()
