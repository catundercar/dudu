"""`TransportContractTest` suite across `FakeTransport`, `LocalHcTransport`, and `LocalTuiTransport` (§5, §10.3)."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import time
from typing import Any
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pmlib.context import Context
from pmlib.home import Home
from pmlib.messaging.address import Endpoint, LogicalAddress
from pmlib.messaging.envelope import P1_USER, Envelope, new_env_id
from pmlib.messaging.mailbox import MailboxItem
from pmlib.messaging.principal import Principal
from pmlib.messaging.transports import FakeTransport, LocalHcTransport, LocalTuiTransport
from pmlib.terminals.hc import HcHost
from tests.fakes import FakeClock, FakeTui


def _make_item(text: str = "hello PM") -> MailboxItem:
    eid = new_env_id(1_700_000_000_000)
    env = Envelope(
        env_id=eid,
        idempotency_key="",
        schema_version=1,
        created_ms=1_700_000_000_000,
        kind="chat.user",
        sender=Principal.user("proj"),
        recipient=LogicalAddress.pm("proj"),
        project="proj",
        cause={"kind": "test"},
        priority=P1_USER,
        body={"text": text, "msg_id": "m-1"},
    )
    return MailboxItem(
        seq=1,
        envelope=env,
        state="accepted",
        attempts=0,
        accepted_ms=1_700_000_000_000,
        updated_ms=1_700_000_000_000,
    )


class _ScriptedHcRunner:
    """Deterministic `HcHost._runner` driving real `HcHost` + `LocalHcTransport` code paths."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict]] = []
        self.get_replies: list[dict | None] = []
        self.send_replies: list[dict | None] = []
        self.interrupt_replies: list[dict | None] = []
        self.keys_sent: list[tuple[str, ...]] = []

    def __call__(self, *argv: str, **kw: Any) -> Any:
        self.calls.append((argv, dict(kw)))
        cmd = argv[0] if argv else ""
        if cmd == "get":
            if self.get_replies:
                return self.get_replies.pop(0)
            return {"address": "t1", "state": "live", "turn": 1, "status": {"state": "idle"}, "status_ms": 100}
        if cmd == "keys":
            self.keys_sent.append(argv)
            return {"ok": True}
        if cmd == "send":
            if self.send_replies:
                return self.send_replies.pop(0)
            return {"ok": True, "started": True, "turn": 2, "status": {"state": "working"}}
        if cmd == "interrupt":
            if self.interrupt_replies:
                return self.interrupt_replies.pop(0)
            return {"status": "stopped", "key_sent": "Escape"}
        if cmd == "read":
            return "prompt> \n"
        return None


class TestTransportContractFake(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.tr = FakeTransport(clock=self.clock)
        self.ep = Endpoint(runtime="fake", machine="local", workspace="/repo", terminal="t1")

    def test_capabilities_deliver_observe_interrupt_and_partition(self) -> None:
        self.tr.configure(self.ep, live=True, agent_state="idle", can_report_status=True, turn=1)
        caps = self.tr.capabilities(self.ep)
        self.assertTrue(caps.can_report_status)
        self.assertTrue(caps.supports_if_idle)

        item = _make_item("run tests")
        out = self.tr.deliver(self.ep, item, if_idle=True)
        self.assertEqual(out.status, "typed")
        self.assertTrue(out.started_turn)

        self.tr.configure(self.ep, agent_state="working")
        mismatch = self.tr.deliver(self.ep, item, if_idle=True)
        self.assertEqual(mismatch.status, "status_mismatch")

        self.tr.configure(self.ep, link_state="disconnected")
        part_del = self.tr.deliver(self.ep, item, if_idle=False)
        part_int = self.tr.interrupt(self.ep)
        obs = self.tr.observe(self.ep, {})
        self.assertEqual(part_del.status, "partitioned")
        self.assertEqual(part_int.status, "partitioned")
        self.assertEqual(obs.link_state, "disconnected")

        self.tr.configure(self.ep, link_state="connected", agent_state="idle", draft_delay_ms=2000)
        handle = self.tr.start_deliver_async(self.ep, item, if_idle=True)
        self.assertIsNone(handle.poll())
        self.clock.advance(2.5)
        done = handle.poll()
        self.assertIsNotNone(done)
        self.assertEqual(done.status, "typed")


class TestTransportContractLocalHc(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.runner = _ScriptedHcRunner()
        self.ctx = Context(
            home=Home(pathlib.Path(self._tmp.name)),
            clock=self.clock,
            hc=HcHost(runner=self.runner, clock=self.clock),
        )
        self.tr = LocalHcTransport(self.ctx)
        self.ep = Endpoint(runtime="hc", machine=None, workspace="/repo", terminal="t1")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_started_false_with_no_progress_and_explicit_status_mismatch(self) -> None:
        self.runner.get_replies = [
            {"address": "t1", "state": "live", "turn": 3, "status": {"state": "idle"}, "status_ms": 500},
            {"address": "t1", "state": "live", "turn": 3, "status": {"state": "working"}, "status_ms": 500},
        ]
        self.runner.send_replies = [
            {"ok": True, "started": False, "turn": 3, "status": {"state": "working"}},
        ]
        out = self.tr.deliver(self.ep, _make_item("hi"), if_idle=False)
        self.assertEqual((out.status, out.started_turn), ("typed", False))

        self.runner.get_replies = [
            {"address": "t1", "state": "live", "turn": 3, "status": {"state": "working"}, "status_ms": 500},
        ]
        self.runner.send_replies = [
            {"error": {"kind": "status_mismatch", "message": "not idle"}},
        ]
        mismatch = self.tr.deliver(self.ep, _make_item("hi"), if_idle=True)
        self.assertEqual(mismatch.status, "status_mismatch")

    def test_started_false_reconciles_to_typed_when_turn_advances(self) -> None:
        self.runner.get_replies = [
            {"address": "t1", "state": "live", "turn": 3, "status": {"state": "idle"}, "status_ms": 500},
            {"address": "t1", "state": "live", "turn": 4, "status": {"state": "working"}, "status_ms": 600},
        ]
        self.runner.send_replies = [
            {"ok": True, "started": False, "turn": 3},
        ]
        out = self.tr.deliver(self.ep, _make_item("hi"), if_idle=False)
        self.assertEqual(out.status, "typed")
        self.assertTrue(out.started_turn)

    def test_timeout_reconciles_via_post_turn_advance_or_returns_timeout_uncertain(self) -> None:
        self.runner.get_replies = [
            {"address": "t1", "state": "live", "turn": 5, "status": {"state": "idle"}, "status_ms": 500},
            {"address": "t1", "state": "live", "turn": 6, "status": {"state": "working"}, "status_ms": 700},
        ]
        self.runner.send_replies = [None]
        reconciled = self.tr.deliver(self.ep, _make_item("hi"))
        self.assertEqual(reconciled.status, "typed")

        self.runner.get_replies = [
            {"address": "t1", "state": "live", "turn": 6, "status": {"state": "idle"}, "status_ms": 700},
            {"address": "t1", "state": "live", "turn": 6, "status": {"state": "idle"}, "status_ms": 700},
        ]
        self.runner.send_replies = [None]
        uncertain = self.tr.deliver(self.ep, _make_item("hi"))
        self.assertEqual(uncertain.status, "timeout_uncertain")

    def test_error_mapping_blocked_gone_partitioned_and_interrupt(self) -> None:
        self.runner.get_replies = [
            {"address": "t1", "state": "live", "turn": 1, "status": {"state": "idle"}, "status_ms": 100},
        ]
        self.runner.send_replies = [
            {"error": {"kind": "blocked", "message": "modal dialog"}},
        ]
        self.assertEqual(self.tr.deliver(self.ep, _make_item()).status, "blocked_prompt")

        self.runner.get_replies = [{"error": {"kind": "unavailable", "message": "host offline"}}]
        part_del = self.tr.deliver(self.ep, _make_item())
        self.assertEqual(part_del.status, "partitioned")

        self.runner.interrupt_replies = [{"error": {"kind": "unavailable", "message": "host offline"}}]
        self.assertEqual(self.tr.interrupt(self.ep).status, "partitioned")

        self.runner.interrupt_replies = [{"outcome": "still_working", "key": "esc"}]
        self.assertEqual(self.tr.interrupt(self.ep).status, "still_working")

        self.assertTrue(self.tr.unblock_prompt(self.ep, ("Escape", "Enter")))
        self.assertTrue(self.runner.keys_sent)


@unittest.skipIf(os.name == "nt" or " " in sys.executable, "the stand-in `hc` is a shebang script")
class TestLocalHcAsyncSubprocess(unittest.TestCase):
    """The branch production runs: an `HcHost` without a runner makes `start_deliver_async` spawn `hc send` and
    poll it. The suites above inject a runner, which takes the synchronous branch, so nothing else covers the argv
    it builds, how it reads the reply of the process, or what it does with a send that outlives its timeout."""

    PRE_INFO = {"address": "t1", "state": "live", "turn": 1, "status": {"state": "idle"}, "status_ms": 100}

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.clock = FakeClock()
        self.calls = self.dir / "calls.jsonl"
        self.ep = Endpoint(runtime="hc", machine=None, workspace="/repo", terminal="t1")
        self._procs: list[Any] = []

    def tearDown(self) -> None:
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
        self._tmp.cleanup()

    def _transport(self, on_send: str) -> LocalHcTransport:
        """A transport whose `hc` is a script: it logs its argv, answers `get` with PRE_INFO and runs `on_send`."""
        script = self.dir / "hc"
        script.write_text(
            f"#!{sys.executable}\n"
            "import json, sys, time\n"
            f"with open({str(self.calls)!r}, 'a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1] == 'get':\n"
            f"    print({json.dumps(self.PRE_INFO)!r})\n"
            "    sys.exit(0)\n"
            + on_send,
            encoding="utf-8",
        )
        script.chmod(0o755)
        ctx = Context(
            home=Home(self.dir / "home"),
            clock=self.clock,
            hc=HcHost({"hc": str(script)}, clock=self.clock),
        )
        return LocalHcTransport(ctx)

    def _start(self, tr: LocalHcTransport, text: str, **kw: Any) -> Any:
        handle = tr.start_deliver_async(self.ep, _make_item(text), pre_info=self.PRE_INFO, **kw)
        proc = getattr(handle, "_proc", None)
        self.assertIsNotNone(proc, "expected a spawned `hc send`, got the synchronous branch")
        self._procs.append(proc)
        return handle

    def _settle(self, handle: Any, seconds: float = 20.0) -> Any:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            out = handle.poll()
            if out is not None:
                return out
            time.sleep(0.02)
        self.fail("the spawned `hc send` did not settle")

    def _sends(self) -> list[list[str]]:
        rows = [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()]
        return [row for row in rows if row and row[0] == "send"]

    def test_spawned_send_types_and_keeps_a_leading_dash_payload_positional(self) -> None:
        tr = self._transport("print(json.dumps({'started': True, 'status': {'state': 'working'}}))\n")
        out = self._settle(self._start(tr, "-rf starts with a dash", if_idle=True))
        self.assertEqual((out.status, out.started_turn), ("typed", True))
        self.assertEqual(self._sends(), [["send", "--if", "idle", "--json", "--", "t1", "-rf starts with a dash"]])

        # Without `if_idle` no `--if` is passed (a user message is typed into a working PM too).
        self._settle(self._start(tr, "second"))
        self.assertEqual(self._sends()[-1], ["send", "--json", "--", "t1", "second"])

    def test_error_reply_on_stderr_is_not_reported_as_typed(self) -> None:
        tr = self._transport(
            "sys.stderr.write(json.dumps({'error': {'kind': 'blocked', 'message': 'modal dialog'}}))\n"
            "sys.exit(1)\n"
        )
        out = self._settle(self._start(tr, "hi"))
        self.assertEqual((out.status, out.detail), ("blocked_prompt", "modal dialog"))

    def test_send_outliving_its_timeout_is_killed_and_left_uncertain(self) -> None:
        tr = self._transport("time.sleep(120)\n")
        handle = self._start(tr, "hi", timeout_s=70.0)
        self.assertIsNone(handle.poll())
        self.clock.advance(69.0)
        self.assertIsNone(handle.poll())  # still inside the 70 s that cover hc's own draft wait

        self.clock.advance(2.0)
        out = handle.poll()
        self.assertIsNotNone(out)
        # The terminal did not move on (`get` still answers PRE_INFO): nobody knows whether it was typed.
        self.assertEqual(out.status, "timeout_uncertain")
        # The process is gone, so it cannot type after the caller decided to retry.
        self.assertIsNotNone(self._procs[-1].poll())
        self.assertIs(handle.poll(), out)


class TestTransportContractLocalTui(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tui = FakeTui(
            panes=[{"pane_id": "%1", "title": "PM", "session": "s1"}],
            pane_screens={"%1": "prompt> \n"},
            prompt_results=[True, False],
            current_session="s1",
        )
        self.ctx = Context(home=Home(pathlib.Path(self._tmp.name)), clock=FakeClock(), tui=self.tui)
        self.tr = LocalTuiTransport(self.ctx)
        self.ep = Endpoint(runtime="tui", machine=None, workspace="s1", terminal="%1")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tui_stateless_capabilities_deliver_observe_and_gone(self) -> None:
        caps = self.tr.capabilities(self.ep)
        self.assertFalse(caps.can_report_status)
        self.assertFalse(caps.supports_if_idle)

        out = self.tr.deliver(self.ep, _make_item("hello tui"), if_idle=True)
        self.assertEqual(out.status, "typed")
        self.assertEqual(self.tr.observe(self.ep, {}).link_state, "connected")

        del self.tui._panes["%1"]
        gone = self.tr.deliver(self.ep, _make_item("hello gone"))
        self.assertEqual(gone.status, "endpoint_gone")


if __name__ == "__main__":
    unittest.main()
