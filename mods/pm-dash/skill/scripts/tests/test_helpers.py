"""Helper lifecycle, limits, wait/timeout/watch reconciliation, hooks, session exclusion, and authorization.

Moved from test_pm.py `Helpers` (Stage 6b2, 19 tests). Every test runs on its own `make_ctx` Context with
`FakeHc`, `FakeProcs`, `FakeClock`, and `tests.legacy_bind.bound` around Layer 4 `cmd_*` calls.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-helpers")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

from pmlib import cli, hooks  # noqa: E402
from pmlib.agents.sessions import session_score  # noqa: E402
from pmlib.agents.transcripts import claude_folder  # noqa: E402
from pmlib.commands import helpers as helpers_cmds  # noqa: E402
from pmlib.context import StdOutput  # noqa: E402
from pmlib.events import stalls as stalls_mod  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.events.deliverer import Deliverer  # noqa: E402
from pmlib.helpers.config import resolve_helper_spec  # noqa: E402
from pmlib.helpers.records import (  # noqa: E402
    _match_helper,
    finalize_helper_for,
    helper_wait_guard_for,
    kill_helper_terminal_for,
    update_helper_owner_for,
)
from pmlib.helpers.service import HelperStartRequest  # noqa: E402
from pmlib.helpers.watch import HelperWatcher  # noqa: E402
from pmlib.home import Home, project_slug  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.store import lock_file, unlock_file  # noqa: E402
from pmlib.workers import codex_pool as codex_pool_mod  # noqa: E402
from pmlib.workers.sessions import find_session_for  # noqa: E402
from tests.fakes import FakeChangeWaiter, FakeClock, FakeHc, FakeProcs, make_ctx  # noqa: E402


def _row(kind: str, content, usage=None, side: bool = False) -> str:
    message = {"content": content}
    if usage:
        message["usage"] = usage
    return json.dumps({"type": kind, "message": message, "isSidechain": side})


class HelpersFakeHc(FakeHc):
    """FakeHc that records `run(...)` calls (including raw `placement` and `labels`) for helper assertions."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._next_id = 11
        self.run_records: list[dict] = []

    def run(
        self,
        argv,
        *,
        name: str = "",
        cwd="",
        labels=(),
        bg: bool = True,
        parent: str = "",
        keep: bool = False,
        no_parent: bool = False,
        placement=(),
        env=None,
    ):
        labels_list = list(labels)
        placement_list = list(placement)
        row = super().run(
            argv,
            name=name,
            cwd=cwd,
            labels=labels_list,
            bg=bg,
            parent=parent,
            keep=keep,
            no_parent=no_parent,
            placement=placement_list,
            env=env,
        )
        if row is not None:
            addr = row["address"]
            self.terminals[addr]["turn"] = 0
            self.terminals[addr]["screen"] = ""
            self.run_records.append({
                "address": addr,
                "argv": list(argv),
                "name": name,
                "cwd": str(cwd),
                "labels": labels_list,
                "placement": placement_list,
                "env": env,
            })
        return row


class HelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = str(self.base / "demo")
        Path(self.repo).mkdir()
        self.slug = project_slug(self.repo)
        self.cfg: dict = {
            "profiles": {
                "neon": {"kind": "agy", "model": "gemini-4-neon-high"},
                "carbon": {"kind": "agy", "model": "gemini-4-carbon-high"},
            },
            "agents": {
                "agy": {"argv": ["agy", "--dangerously-skip-permissions"], "model": ["--model", "{}"], "effort": []},
            },
        }
        self.clock = FakeClock("2026-11-23 10:00:00", mono=100.0)
        self.hc = HelpersFakeHc(clock=self.clock)
        self.home = Home(self.base / "ledger")
        self.procs = FakeProcs(self.home, env={"PM_HOME": str(self.home.root)})
        self.pm_term = "t1"
        self.worker_term = "t2"
        self.task_id = f"{self.slug}-work"
        self.hc.terminals[self.pm_term] = {
            "address": self.pm_term, "state": "live", "name": f"pm-{self.slug}",
            "labels": {"pm": Path(self.repo).name}, "status": {"state": "idle"}, "turn": 1,
        }
        self.hc.terminals[self.worker_term] = {
            "address": self.worker_term, "state": "live", "name": "worker-1",
            "labels": {"task": self.task_id}, "status": {"state": "working"}, "turn": 1,
        }
        self.ctx = self._ctx("")
        self.ctx.store.change_registration(self.slug, lambda _: {
            "name": f"pm-{self.slug}", "project": Path(self.repo).name, "repo": self.repo,
            "runtime": "hc", "terminal": self.pm_term, "pane": f"hc:{self.pm_term}", "claimed": self.clock.now(),
        })
        self.ctx.store.change_task(self.task_id, lambda _: {
            "id": self.task_id, "title": "Implement feature", "project": Path(self.repo).name, "repo": self.repo,
            "status": "in_progress", "owner": "pm", "base": "main", "pane": f"hc:{self.worker_term}",
            "worktree": self.repo, "created": self.clock.now(), "updated": self.clock.now(), "log": [], "dispatched": True,
        })

    def _ctx(self, term: str, *, env: dict[str, str] | None = None):
        return make_ctx(
            self.base,
            pane=f"hc:{term}" if term else "",
            hc_terminal=term,
            hc=self.hc,
            procs=self.procs,
            clock=self.clock,
            out=StdOutput(),
            config=self.cfg,
            env=env or {},
        )

    def _set_caller(self, term: str, *, env: dict[str, str] | None = None) -> None:
        self.ctx = self._ctx(term, env=env)

    def _write_cfg(self, cfg: dict) -> None:
        self.cfg = cfg
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run_cli(self, *argv: str) -> tuple[str, str]:
        parser = cli.build_parser()
        ns = parser.parse_args(list(argv))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            helpers_cmds.cmd_helper(ns, ctx=self.ctx)
        return out.getvalue(), err.getvalue()

    def test_default_profile_is_opus_then_neon_then_light(self) -> None:
        # With opus + neon configured, opus wins first.
        self._write_cfg({
            "profiles": {
                "opus": {"kind": "agy", "model": "claude-opus-5-5-medium"},
                "neon": {"kind": "agy", "model": "gemini-4-neon-high"},
                "carbon": {"kind": "agy", "model": "gemini-4-carbon-high"},
            },
            "agents": {
                "agy": {"argv": ["agy", "--dangerously-skip-permissions"], "model": ["--model", "{}"], "effort": []},
            },
        })
        s0 = resolve_helper_spec(self.ctx, HelperStartRequest())
        self.assertEqual((s0.profile, s0.kind, s0.model), ("opus", "agy", "claude-opus-5-5-medium"))

        # Without opus, neon is used.
        cfg2 = dict(self.cfg)
        cfg2["profiles"] = {k: v for k, v in self.cfg["profiles"].items() if k != "opus"}
        self._write_cfg(cfg2)
        s1 = resolve_helper_spec(self.ctx, HelperStartRequest())
        self.assertEqual((s1.profile, s1.kind, s1.model), ("neon", "agy", "gemini-4-neon-high"))

        # Explicit profile override
        s2 = resolve_helper_spec(self.ctx, HelperStartRequest(profile="carbon"))
        self.assertEqual((s2.profile, s2.kind, s2.model), ("carbon", "agy", "gemini-4-carbon-high"))

        # Explicit --kind without --profile respects that kind instead of forcing default profile's agy/model
        s3 = resolve_helper_spec(self.ctx, HelperStartRequest(kind="claude", model="sonnet"))
        self.assertEqual((s3.profile, s3.kind, s3.model), ("", "claude", "sonnet"))

        # Without opus or neon in config, falls back to built-in light
        self._write_cfg({})
        s4 = resolve_helper_spec(self.ctx, HelperStartRequest())
        self.assertEqual((s4.profile, s4.kind, s4.model, s4.effort), ("light", "claude", "sonnet", "medium"))

    def test_fable_helper_requires_confirmed_and_claude_helper_is_read_only_with_result_read_and_write(self) -> None:
        self._set_caller(self.pm_term)
        with self.assertRaises(SystemExit) as cm:
            self._run_cli("helper", "start", "deep research", "--profile", "deep", "--repo", self.repo)
        self.assertIn("Fable", str(cm.exception))

        out, _ = self._run_cli("helper", "start", "check api", "--name", "api", "--kind", "claude",
                               "--model", "sonnet", "--dry-run", "--repo", self.repo)
        plan = json.loads(out)
        self.assertEqual(plan["what"], "helper")
        self.assertIn("--disallowedTools", plan["argv"])
        self.assertEqual(plan["argv"][plan["argv"].index("--disallowedTools") + 1], "Edit,NotebookEdit")
        settings_path = Path(plan["argv"][plan["argv"].index("--settings") + 1])
        settings = json.loads(settings_path.read_text())
        self.assertIn(f"Read(/{plan['result']})", settings["permissions"]["allow"])
        self.assertIn(f"Write(/{plan['result']})", settings["permissions"]["allow"])
        self.assertNotIn("autoMemoryDirectory", settings)

    def test_pm_helper_start_done_and_deliver_pipeline(self) -> None:
        self._set_caller(self.pm_term)
        before_tasks = set(p.name for p in self.ctx.home.tasks.glob("*.json"))
        out1, _ = self._run_cli("helper", "start", "Inspect module A", "--name", "mod-a", "--repo", self.repo)
        out2, _ = self._run_cli("helper", "start", "Inspect module B", "--name", "mod-b", "--repo", self.repo)
        self.assertIn("helper=mod-a", out1)
        self.assertIn("helper=mod-b", out2)
        # No new ledger tasks created for helpers.
        self.assertEqual(set(p.name for p in self.ctx.home.tasks.glob("*.json")), before_tasks)

        # Verify hc run args: --parent t1 --no-notify, NO --outlive-parent, atomic labels.
        self.assertEqual(len(self.hc.run_records), 2)
        for rec in self.hc.run_records:
            pl = rec["placement"]
            self.assertIn("--parent", pl)
            self.assertEqual(pl[pl.index("--parent") + 1], self.pm_term)
            self.assertIn("--no-notify", pl)
            self.assertNotIn("--outlive-parent", pl)
            self.assertIn(f"helper.of=pm-{self.slug}", rec["labels"])

        reg = self.ctx.store.registration(self.slug)
        self.assertEqual([h["name"] for h in reg["helpers"]], ["mod-a", "mod-b"])
        h1, h2 = reg["helpers"]

        # Helper calling done with empty/missing result file is refused.
        self._set_caller(h1["terminal"])
        with self.assertRaises(SystemExit) as cm:
            self._run_cli("helper", "done")
        self.assertIn("missing or empty", str(cm.exception))

        # Helper 1 writes result file and runs done; helper 2 uses --text.
        Path(h1["result"]).write_text("# Findings A\nAll callers use change_task.\n", encoding="utf-8")
        self._run_cli("helper", "done")
        # Duplicate done is idempotent (no duplicate event).
        self._run_cli("helper", "done")

        self._set_caller(h2["terminal"])
        self._run_cli("helper", "done", "--text", "Module B has zero blockers.")

        reg = self.ctx.store.registration(self.slug)
        self.assertEqual([h["status"] for h in reg["helpers"]], ["done", "done"])
        events = [e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "helper"]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.get("wake") is True for e in events))

        # Deliver picks up both helper conclusions in one batch for the PM.
        delivery = Delivery(self.ctx, self.repo)
        start, end, items = delivery.pending_batch(offset=0)
        self.assertEqual(len(items), 2)
        text = delivery.batch_text(start, end, items)
        self.assertIn("mod-a", text)
        self.assertIn("mod-b", text)
        self.assertIn("All callers use change_task", text)
        self.assertIn("Module B has zero blockers", text)

    def test_worker_helper_limits_and_depth_guard(self) -> None:
        self._set_caller(self.worker_term)
        for i in range(1, 4):
            self._run_cli("helper", "start", f"Research part {i}", "--name", f"r{i}", "--repo", self.repo)
        task = self.ctx.store.task(self.task_id)
        self.assertEqual(len(task["helpers"]), 3)
        self.assertTrue(any("started helper r1" in e["text"] for e in task["log"]))

        # 4th helper for the same worker is rejected (max 3 per agent).
        with self.assertRaises(SystemExit) as cm:
            self._run_cli("helper", "start", "Research part 4", "--name", "r4", "--repo", self.repo)
        self.assertIn("3/3", str(cm.exception))
        self.assertIn("r1", str(cm.exception))

        # Depth limit: a helper cannot start another helper.
        helper_term = task["helpers"][0]["terminal"]
        self._set_caller(helper_term)
        with self.assertRaises(SystemExit) as cm:
            self._run_cli("helper", "start", "Nested helper", "--name", "nested", "--repo", self.repo)
        self.assertIn("depth", str(cm.exception))

        # Project-wide limit: set project_max=4 (1 active thread + 3 helpers = 4 -> PM's new helper rejected).
        self._write_cfg({**self.cfg, "helpers": {"project_max": 4}})
        self._set_caller(self.pm_term)
        with self.assertRaises(SystemExit) as cm:
            self._run_cli("helper", "start", "PM research", "--name", "pm-r1", "--repo", self.repo)
        self.assertIn("4/4", str(cm.exception))

        # Stopping one worker helper frees both per-worker and project slots.
        self._set_caller(self.worker_term)
        self._run_cli("helper", "stop", "r3", "--repo", self.repo)
        self._run_cli("helper", "start", "Research part 4", "--name", "r4", "--repo", self.repo)
        self.assertEqual(sum(1 for h in self.ctx.store.task(self.task_id)["helpers"] if h["status"] == "running"), 3)

    def test_worker_helper_done_notifies_worker_unless_helper_wait_active(self) -> None:
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Check logs", "--name", "logs", "--repo", self.repo)
        self._run_cli("helper", "start", "Check tests", "--name", "tests", "--repo", self.repo)
        h1, h2 = self.ctx.store.task(self.task_id)["helpers"]

        # Not waiting: helper done sends hc send to worker terminal.
        self.hc.sent.clear()
        self._set_caller(h1["terminal"])
        self._run_cli("helper", "done", "--text", "No errors in logs.")
        self.assertEqual(len(self.hc.sent), 1)
        self.assertEqual(self.hc.sent[0][0], self.worker_term)
        self.assertIn("helper logs done", self.hc.sent[0][1])

        # Actively waiting (helper_wait_guard_for held): helper done skips hc send to avoid duplicate turn.
        self.hc.sent.clear()
        self._set_caller(h2["terminal"])
        with helper_wait_guard_for(self.ctx, self.task_id):
            self._run_cli("helper", "done", "--text", "All tests green.")
        self.assertEqual(self.hc.sent, [])

    def test_helper_wait_unreported_screen_fallback_and_blocked_detection(self) -> None:
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Check config", "--name", "cfg", "--repo", self.repo)
        h = self.ctx.store.task(self.task_id)["helpers"][0]
        hterm = h["terminal"]

        # Simulate unhooked agent (agy) finishing its turn without writing result file or calling helper done.
        self.hc.terminals[hterm]["turn"] = 1
        self.hc.terminals[hterm]["status"] = {"state": "idle"}
        self.hc.terminals[hterm]["screen"] = "Checked config.py\nConclusion: timeout defaults to 1800s.\n"

        with mock.patch.object(stalls_mod, "STALL_GRACE", 0):
            out, _ = self._run_cli("helper", "wait", "cfg", "--json", "--repo", self.repo)
        rows = json.loads(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "done")
        self.assertEqual(rows[0]["fallback"], "screen")
        self.assertIn("timeout defaults to 1800s", rows[0]["content"])
        # Terminal was killed (exited) but NOT removed (still readable with hc read).
        self.assertIn(hterm, self.hc.terminals)
        self.assertEqual(self.hc.terminals[hterm]["state"], "exited")

        # Simulate a helper stuck on a dialog (blocked) -> helper wait returns exit 3 with alert instead of hanging.
        self._run_cli("helper", "start", "Check perms", "--name", "perm", "--repo", self.repo)
        h2 = self.ctx.store.task(self.task_id)["helpers"][-1]
        self.hc.terminals[h2["terminal"]]["status"] = {"state": "blocked"}
        self.hc.terminals[h2["terminal"]]["screen"] = "Allow tool execution? [Y/n]\n"
        with mock.patch.object(stalls_mod, "STALL_GRACE", 0), self.assertRaises(SystemExit) as cm:
            self._run_cli("helper", "wait", "perm", "--repo", self.repo)
        self.assertEqual(cm.exception.code, 3)

    def test_helper_timeout_reconciled_by_ls_and_watch_helpers(self) -> None:
        self._set_caller(self.pm_term)
        self._run_cli("helper", "start", "Slow query", "--name", "slow", "--timeout", "10", "--repo", self.repo)
        h = self.ctx.store.registration(self.slug)["helpers"][0]
        hterm = h["terminal"]
        self.hc.terminals[hterm]["screen"] = "Partial findings before timeout.\n"

        # Backdate started_ts past timeout.
        def _backdate(items):
            items[0]["started_ts"] = self.clock.time() - 60
            return True
        update_helper_owner_for(self.ctx, "pm", f"pm-{self.slug}", self.slug, _backdate)

        out, _ = self._run_cli("helper", "ls", "--json", "--repo", self.repo)
        rows = json.loads(out)
        self.assertEqual(rows[0]["status"], "timeout")
        self.assertEqual(self.hc.terminals[hterm]["state"], "exited")
        self.assertIn("Partial findings before timeout", Path(h["result"]).read_text(encoding="utf-8"))
        # PM got a wake event for the timeout.
        events = [e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "helper"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "timeout")

    def test_watch_helpers_harvests_unhooked_pm_helper_and_cleans_up_done_terminal(self) -> None:
        self._set_caller(self.pm_term)
        self._run_cli("helper", "start", "Scan repo", "--name", "scan", "--repo", self.repo)
        h = self.ctx.store.registration(self.slug)["helpers"][0]
        hterm = h["terminal"]
        Path(h["result"]).write_text("Found 3 callers.\n", encoding="utf-8")
        # Unhooked agy helper ends turn without calling helper done.
        self.hc.terminals[hterm]["turn"] = 1
        self.hc.terminals[hterm]["status"] = {"state": "done"}
        stops: dict = {}
        watcher = HelperWatcher(self.ctx)
        with mock.patch.object(stalls_mod, "STALL_GRACE", 0):
            watcher.look(self.repo, stops, {})
            watcher.look(self.repo, stops, {})
        reg = self.ctx.store.registration(self.slug)
        self.assertEqual(reg["helpers"][0]["status"], "done")
        self.assertEqual(self.hc.terminals[hterm]["state"], "exited")
        events = [e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "helper"]
        self.assertEqual(len(events), 1)
        self.assertIn("Found 3 callers", events[0]["text"])

    def test_hooks_handle_helper_session_start_and_stop_nudge_and_fallback(self) -> None:
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Read docs", "--name", "docs", "--kind", "claude", "--repo", self.repo)
        h = self.ctx.store.task(self.task_id)["helpers"][0]
        hterm = h["terminal"]

        # SessionStart hook inside helper prints helper reminder, not worker task registration advice.
        self._set_caller(hterm)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hooks.cmd_hook_session_start(argparse.Namespace(), ctx=self.ctx)
        self.assertIn("helper docs", out.getvalue())
        self.assertNotIn("register the task", out.getvalue())

        # Claude Code Stop hook blocks once to remind helper to run `helper done`.
        self._set_caller(hterm, env={"CLAUDE_CODE_SESSION_ID": "sess-helper-1"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hooks.helper_stopped({"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "Draft"}, ctx=self.ctx)
        decision = json.loads(out.getvalue())
        self.assertEqual(decision["decision"], "block")
        self.assertIn("helper done", decision["reason"])
        self.assertEqual(self.ctx.store.task(self.task_id)["helpers"][0]["status"], "running")

        # Second Stop hook (stop_hook_active=True) harvests last_assistant_message into result file & marks done.
        hooks.helper_stopped({"hook_event_name": "Stop", "stop_hook_active": True,
                              "last_assistant_message": "Final answer from assistant reply."}, ctx=self.ctx)
        updated = self.ctx.store.task(self.task_id)["helpers"][0]
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["fallback"], "reply")
        self.assertIn("Final answer from assistant reply.", Path(h["result"]).read_text(encoding="utf-8"))

    def test_helper_stop_refuses_bare_and_never_kills_pm(self) -> None:
        self._set_caller(self.pm_term)
        with self.assertRaises(SystemExit):
            self._run_cli("helper", "stop", "--repo", self.repo)
        self.assertFalse(kill_helper_terminal_for(self.ctx, self.pm_term))
        self.assertEqual(self.hc.terminals[self.pm_term]["state"], "live")

    def test_killed_helper_without_result_file_reconciles_as_exited_not_done(self) -> None:
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Mid-flight work", "--name", "mid", "--repo", self.repo)
        h = self.ctx.store.task(self.task_id)["helpers"][0]
        hterm = h["terminal"]
        # Terminal exits (e.g. parent died) mid-work without writing result file, though screen has partial text.
        self.hc.terminals[hterm]["state"] = "finished"
        self.hc.terminals[hterm]["screen"] = "Still scanning files...\n"
        out, _ = self._run_cli("helper", "ls", "--json", "--repo", self.repo)
        rows = json.loads(out)
        self.assertEqual(rows[0]["status"], "exited")
        self.assertEqual(rows[0]["fallback"], "screen")
        self.assertIn("Still scanning files", Path(h["result"]).read_text(encoding="utf-8"))

    def test_session_score_and_find_session_exclude_helper_transcripts(self) -> None:
        tid = self.task_id
        # EN helper brief, ZH helper brief, SessionStart hook reminder — all must score 0 even if quoting `update <id>`.
        en_helper = "\n".join([
            _row("user", f"[Helper audit for {tid}]\nInspect update {tid}"),
            _row("assistant", [{"type": "text", "text": "Done."}]),
        ])
        zh_helper = "\n".join([
            _row("user", f"【临时 helper 调研，归属 {tid}】\n检查 update {tid}"),
            _row("assistant", [{"type": "text", "text": "完成。"}]),
        ])
        hook_helper = "\n".join([
            _row("user", f"You are helper scan for {tid} (read-only). Write to x.md"),
            _row("assistant", [{"type": "text", "text": "Working."}]),
        ])
        self.assertEqual(session_score(en_helper, tid), 0)
        self.assertEqual(session_score(zh_helper, tid), 0)
        self.assertEqual(session_score(hook_helper, tid), 0)

        # A real worker that quotes helper text AFTER its first assistant reply is NOT excluded.
        real_worker = "\n".join([
            _row("user", f"Implement feature. Report with `pm.py update {tid} --status review`"),
            _row("assistant", [{"type": "text", "text": "Starting work."}]),
            _row("user", f"[Helper audit for {tid}] summary"),
        ])
        self.assertEqual(session_score(real_worker, tid), 2)

        # End-to-end find_session ignores a newer helper transcript in the same worktree and picks the worker.
        proj_folder = self.ctx.claude_projects / claude_folder(self.repo)
        proj_folder.mkdir(parents=True)
        worker_file = proj_folder / "worker-sess-1.jsonl"
        helper_file = proj_folder / "helper-sess-2.jsonl"
        worker_file.write_text(json.dumps({"cwd": self.repo, "type": "user", "message": {"content": f"update {tid}"}}) + "\n",
                               encoding="utf-8")
        helper_file.write_text(json.dumps({"cwd": self.repo, "type": "user", "message": {"content": f"[Helper h1 for {tid}]\nupdate {tid}"}}) + "\n",
                               encoding="utf-8")
        now_t = self.clock.time()
        os.utime(worker_file, (now_t - 10, now_t - 10))
        os.utime(helper_file, (now_t, now_t))  # newer than worker!
        found = find_session_for(self.ctx, self.ctx.store.task(tid))
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], "worker-sess-1")

    def test_watch_helpers_manages_worker_helpers_without_helper_wait(self) -> None:
        self._set_caller(self.worker_term)
        # 1. Worker helper calls `done` without `helper wait` -> watch_helpers kills terminal & clears cleanup_term.
        self._run_cli("helper", "start", "Quick check", "--name", "quick", "--repo", self.repo)
        h1 = self.ctx.store.task(self.task_id)["helpers"][0]
        self._set_caller(h1["terminal"])
        self._run_cli("helper", "done", "--text", "All good.")
        self.assertTrue(self.ctx.store.task(self.task_id)["helpers"][0].get("cleanup_term"))
        watcher = HelperWatcher(self.ctx)
        self.assertIn(h1["terminal"], watcher.active_terminals(self.repo))
        self.hc.terminals[h1["terminal"]]["status"] = {"state": "idle"}
        stops: dict = {}
        with mock.patch.object(stalls_mod, "STALL_GRACE", 0):
            watcher.look(self.repo, stops, {})
        self.assertEqual(self.hc.terminals[h1["terminal"]]["state"], "exited")
        self.assertFalse(self.ctx.store.task(self.task_id)["helpers"][0].get("cleanup_term"))

        # 2. Unhooked (agy) worker helper stops after its turn without calling `done` -> watch_helpers harvests & notifies.
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Scan API", "--name", "scan", "--repo", self.repo)
        h2 = self.ctx.store.task(self.task_id)["helpers"][-1]
        Path(h2["result"]).write_text("Found 2 endpoints.\n", encoding="utf-8")
        self.hc.terminals[h2["terminal"]]["turn"] = 1
        self.hc.terminals[h2["terminal"]]["status"] = {"state": "idle"}
        self.hc.sent.clear()
        with mock.patch.object(stalls_mod, "STALL_GRACE", 0):
            watcher.look(self.repo, stops, {})
            watcher.look(self.repo, stops, {})
        h2_after = self.ctx.store.task(self.task_id)["helpers"][-1]
        self.assertEqual(h2_after["status"], "done")
        self.assertEqual(self.hc.terminals[h2["terminal"]]["state"], "exited")
        sends = [text for t, text in self.hc.sent if t == self.worker_term]
        self.assertEqual(len(sends), 1)
        self.assertIn("Found 2 endpoints", sends[0])

        # 3. Worker helper gets blocked -> watch_helpers logs & notifies worker.
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Blocked check", "--name", "blk", "--repo", self.repo)
        h3 = self.ctx.store.task(self.task_id)["helpers"][-1]
        self.hc.terminals[h3["terminal"]]["status"] = {"state": "blocked"}
        self.hc.terminals[h3["terminal"]]["screen"] = "Approve command? [y/N]\n"
        self.hc.sent.clear()
        with mock.patch.object(stalls_mod, "STALL_GRACE", 0):
            watcher.look(self.repo, stops, {})
            watcher.look(self.repo, stops, {})
        sends = [text for t, text in self.hc.sent if t == self.worker_term]
        self.assertEqual(len(sends), 1)
        self.assertIn("blocked", sends[0])

        # 4. Worker helper terminal disappears (`gone`) -> watch_helpers reaps it as exited.
        self.hc.terminals[h3["terminal"]]["state"] = "finished"
        with mock.patch.object(stalls_mod, "STALL_GRACE", 0):
            watcher.look(self.repo, stops, {})
        self.assertEqual(self.ctx.store.task(self.task_id)["helpers"][-1]["status"], "exited")

    def test_worker_helper_notify_skips_when_task_submitted_or_pane_changed(self) -> None:
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Late finish", "--name", "late1", "--repo", self.repo)
        self._run_cli("helper", "start", "Pane moved", "--name", "late2", "--repo", self.repo)
        h1, h2 = self.ctx.store.task(self.task_id)["helpers"]

        # Worker submits task to review -> legacy helper finishing must NOT wake the worker terminal.
        self.ctx.store.change_task(self.task_id, lambda cur: {**cur, "status": "review"})
        self.hc.sent.clear()
        self._set_caller(h1["terminal"])
        self._run_cli("helper", "done", "--text", "Late result 1.")
        self.assertEqual(self.hc.sent, [])

        # Task back in_progress, but pane moved to a new terminal (reattached/escalated) -> must NOT wake old or new.
        self.hc.terminals["t99"] = {"address": "t99", "state": "live", "name": "worker-new", "labels": {"task": self.task_id},
                                    "status": {"state": "idle"}, "turn": 1}
        self.ctx.store.change_task(self.task_id, lambda cur: {**cur, "status": "in_progress", "pane": "hc:t99"})
        self.hc.sent.clear()
        self._set_caller(h2["terminal"])
        self._run_cli("helper", "done", "--text", "Late result 2.")
        self.assertEqual(self.hc.sent, [])

    def test_helper_start_applies_codex_pool_and_claude_defaults(self) -> None:
        self._write_cfg({
            "codex": {
                "profiles": [{"name": "pool-a", "max": 2}, {"name": "pool-b", "max": 1}],
                "allow_default": False,
                "model": "gpt-pool",
                "effort": "high",
            },
            "claude": {"effort": "high"},
        })
        self._set_caller(self.pm_term)
        with mock.patch.object(codex_pool_mod, "_live_codex_impl", return_value=[]):
            # Dry run checks codex pool selection (-p pool-a, model, effort).
            out, _ = self._run_cli("helper", "start", "Audit codex", "--name", "cx", "--kind", "codex",
                                   "--dry-run", "--repo", self.repo)
            plan = json.loads(out)
            self.assertEqual(plan["codex_profile"], "pool-a")
            self.assertEqual((plan["model"], plan["effort"]), ("gpt-pool", "high"))
            self.assertIn("-p", plan["argv"])
            self.assertEqual(plan["argv"][plan["argv"].index("-p") + 1], "pool-a")

            # Real start records provider and releases the actual per-project codex pool flock on disk.
            with mock.patch.object(codex_pool_mod, "_live_codex_impl", side_effect=[[], [{"profile": "pool-a"}]]):
                self._run_cli("helper", "start", "Audit codex", "--name", "cx", "--kind", "codex", "--repo", self.repo)
            self.assertIsNone(codex_pool_mod._POOL_LOCK)
            pool_lock_path = self.ctx.home.locks / f"codex-pool-{self.slug}.lock"
            self.assertTrue(pool_lock_path.is_file())
            with open(pool_lock_path, "a+") as probe_fh:
                lock_file(probe_fh)
                unlock_file(probe_fh)
            h = self.ctx.store.registration(self.slug)["helpers"][-1]
            self.assertEqual((h["provider"], h["model"], h["effort"]), ("pool-a", "gpt-pool", "high"))

            # Disallowed default codex profile is refused.
            with self.assertRaises(SystemExit) as cm:
                self._run_cli("helper", "start", "Audit default", "--name", "cxdef", "--kind", "codex",
                              "--codex-profile", "default", "--repo", self.repo)
            self.assertIn("default", str(cm.exception))
            self.assertIsNone(codex_pool_mod._POOL_LOCK)

        # Claude helper picks up config.json claude.effort via claude_defaults.
        out_cl, _ = self._run_cli("helper", "start", "Audit claude", "--name", "cl", "--kind", "claude",
                                  "--model", "sonnet", "--dry-run", "--repo", self.repo)
        plan_cl = json.loads(out_cl)
        self.assertEqual(plan_cl["effort"], "high")

    def test_worker_cannot_stop_done_wait_or_start_pm_or_other_task_helpers(self) -> None:
        # Create a PM helper and a second task with its own helper.
        self._set_caller(self.pm_term)
        self._run_cli("helper", "start", "PM research", "--name", "pmh", "--repo", self.repo)
        other_id = f"{self.slug}-other"
        self.hc.terminals["t3"] = {"address": "t3", "state": "live", "name": "worker-2", "labels": {"task": other_id},
                                   "status": {"state": "working"}, "turn": 1}
        self.ctx.store.change_task(other_id, lambda _: {
            "id": other_id, "title": "Other task", "project": Path(self.repo).name, "repo": self.repo,
            "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:t3",
            "worktree": self.repo, "created": self.clock.now(), "updated": self.clock.now(), "log": [], "dispatched": True,
        })
        self._set_caller("t3")
        self._run_cli("helper", "start", "Other research", "--name", "oth", "--repo", self.repo)

        # Worker t2 (task demo-work) attempts to stop/done/wait PM's helper or other task's helper -> all refused!
        self._set_caller(self.worker_term)
        for cmd in (
            ("helper", "stop", "pmh", "--pm", "--repo", self.repo),
            ("helper", "stop", "--all", "--pm", "--repo", self.repo),
            ("helper", "done", "pmh", "--pm", "--text", "hijack", "--repo", self.repo),
            ("helper", "wait", "pmh", "--pm", "--repo", self.repo),
            ("helper", "stop", "oth", "--task", other_id, "--repo", self.repo),
            ("helper", "done", "oth", "--task", other_id, "--text", "hijack", "--repo", self.repo),
            ("helper", "start", "bill other", "--task", other_id, "--repo", self.repo),
        ):
            with self.assertRaises(SystemExit, msg=f"expected refusal for {cmd}"):
                self._run_cli(*cmd)

        # PM's helper and other task's helper remain untouched and running.
        self.assertEqual(self.ctx.store.registration(self.slug)["helpers"][0]["status"], "running")
        self.assertEqual(self.ctx.store.task(other_id)["helpers"][0]["status"], "running")

        # A helper itself cannot call `done --pm` or `done <another>` or `stop --all`.
        pmh_term = self.ctx.store.registration(self.slug)["helpers"][0]["terminal"]
        self._set_caller(pmh_term)
        for cmd in (
            ("helper", "done", "--pm", "--text", "bad", "--repo", self.repo),
            ("helper", "done", "oth", "--text", "bad", "--repo", self.repo),
            ("helper", "stop", "--all", "--repo", self.repo),
        ):
            with self.assertRaises(SystemExit, msg=f"expected helper refusal for {cmd}"):
                self._run_cli(*cmd)

    def test_deliver_look_preserves_helper_stops_across_watch_workers_ticks(self) -> None:
        # Regression: watch_workers must NOT prune watch_helpers's ("helper", term) keys from shared `stops`.
        self._set_caller(self.pm_term)
        self._run_cli("helper", "start", "Unhooked scan", "--name", "agys", "--repo", self.repo)
        self._run_cli("helper", "start", "Dialog stuck", "--name", "dlg", "--repo", self.repo)
        h_idle, h_blk = self.ctx.store.registration(self.slug)["helpers"]
        Path(h_idle["result"]).write_text("Unhooked result ready.\n", encoding="utf-8")
        self.hc.terminals[h_idle["terminal"]]["turn"] = 1
        self.hc.terminals[h_idle["terminal"]]["status"] = {"state": "idle"}
        self.hc.terminals[h_blk["terminal"]]["status"] = {"state": "blocked"}
        self.hc.terminals[h_blk["terminal"]]["screen"] = "Approve? [y/N]\n"

        # Use a real non-zero STALL_GRACE and advance FakeClock across Deliverer.look ticks!
        stops: dict = {}
        bases: dict = {}
        watcher = HelperWatcher(self.ctx)
        deliverer = Deliverer(
            self.ctx,
            self.repo,
            watchers=[(watcher.active_terminals, watcher.look)],
            settle=0,
        )
        with mock.patch.object(stalls_mod, "STALL_GRACE", 5):
            deliverer.look(FakeChangeWaiter(), stops, bases)
            # Both helper stop keys must survive watch_workers on tick 1!
            self.assertIn(("helper", h_idle["terminal"]), stops)
            self.assertIn(("helper", h_blk["terminal"]), stops)
            self.assertEqual(self.ctx.store.registration(self.slug)["helpers"][0]["status"], "running")

            # Advance past STALL_GRACE and run deliver_look again: watch_workers runs FIRST and must NOT wipe them!
            self.clock.advance(6.0)
            deliverer.look(FakeChangeWaiter(), stops, bases)

        reg = self.ctx.store.registration(self.slug)
        self.assertEqual(reg["helpers"][0]["status"], "done")
        self.assertEqual(self.hc.terminals[h_idle["terminal"]]["state"], "exited")
        events = [e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "helper"]
        statuses = {(e["helper"], e["status"]) for e in events}
        self.assertIn(("agys", "done"), statuses)
        self.assertIn(("dlg", "blocked"), statuses)

    def test_match_helper_never_falls_back_to_name_when_term_is_specified(self) -> None:
        # Start helper `dup` -> stop it -> start a fresh helper also named `dup` on a new terminal.
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "First run", "--name", "dup", "--repo", self.repo)
        old_term = self.ctx.store.task(self.task_id)["helpers"][0]["terminal"]
        self._run_cli("helper", "stop", "dup", "--repo", self.repo)
        self._run_cli("helper", "start", "Second run", "--name", "dup", "--repo", self.repo)
        new_term = self.ctx.store.task(self.task_id)["helpers"][1]["terminal"]
        self.assertNotEqual(old_term, new_term)

        items = self.ctx.store.task(self.task_id)["helpers"]
        self.assertEqual(_match_helper(items, term=old_term, name="dup", running_only=True), -1)

        # A late finalize/harvest/Stop hook for old_term must NEVER mark or kill new_term!
        entry, transitioned = finalize_helper_for(
            self.ctx,
            "task", self.task_id, self.slug, self.repo,
            term=old_term, name="dup", status="done", summary="stale", kill_term=True, notify=False,
        )
        self.assertFalse(transitioned)
        self.assertEqual(entry["terminal"], old_term)
        fresh = self.ctx.store.task(self.task_id)["helpers"]
        self.assertEqual(fresh[1]["terminal"], new_term)
        self.assertEqual(fresh[1]["status"], "running")
        self.assertEqual(self.hc.terminals[new_term]["state"], "live")

    def test_external_helper_done_kills_terminal_and_avoids_self_notification(self) -> None:
        # 1. Worker finalizes its OWN helper externally -> kills helper terminal and does NOT hc send to itself.
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Work item", "--name", "wext", "--repo", self.repo)
        hw = self.ctx.store.task(self.task_id)["helpers"][0]
        self.hc.sent.clear()
        self._run_cli("helper", "done", "wext", "--text", "Manual finish.", "--repo", self.repo)
        self.assertEqual(self.hc.terminals[hw["terminal"]]["state"], "exited")
        self.assertEqual(self.hc.sent, [])

        # 2. PM finalizes its OWN helper externally -> kills helper terminal and does NOT emit a wake event to itself.
        self._set_caller(self.pm_term)
        self._run_cli("helper", "start", "PM item", "--name", "pext", "--repo", self.repo)
        hp = self.ctx.store.registration(self.slug)["helpers"][0]
        self._run_cli("helper", "done", "pext", "--text", "PM manual finish.", "--repo", self.repo)
        self.assertEqual(self.hc.terminals[hp["terminal"]]["state"], "exited")
        self.assertEqual([e for e in Conversation(self.ctx, self.repo).events() if e.get("type") == "helper"], [])

        # 3. PM finalizes a WORKER's helper externally -> kills helper terminal AND notifies the worker.
        self._set_caller(self.worker_term)
        self._run_cli("helper", "start", "Worker item 2", "--name", "wext2", "--repo", self.repo)
        hw2 = self.ctx.store.task(self.task_id)["helpers"][-1]
        self._set_caller(self.pm_term)
        self.hc.sent.clear()
        self._run_cli("helper", "done", "wext2", "--task", self.task_id, "--text", "Done by PM.", "--repo", self.repo)
        self.assertEqual(self.hc.terminals[hw2["terminal"]]["state"], "exited")
        sends = [text for t, text in self.hc.sent if t == self.worker_term]
        self.assertEqual(len(sends), 1)


if __name__ == "__main__":
    unittest.main()
