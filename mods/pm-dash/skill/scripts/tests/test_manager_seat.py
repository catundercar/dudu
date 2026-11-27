"""Manager rotation, project lifecycle, seamless seat rotation, and adopt tests on `make_ctx` + `fakes.py`.

Moved from `test_pm.py` (`Rotation`, `ProjectLifecycle`, `SeamlessRotation`, `PMSeatAndAdopt` — Stage 6c2, 51 tests).
Every test runs on its own isolated `make_ctx` Context with `FakeHc`, `FakeTui`, `FakeProcs`, `FakeClock`, and
`tests.legacy_bind.bound` around Layer 4 `cmd_*` calls.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

# Isolate the process-wide legacy home before importing pmlib so any legacy fallback still left in production
# (e.g. ManagerSessions.rotate calling deliver_mod.deliver_later) never touches a real ledger.
if "pmlib.context" not in sys.modules:
    _saved_pm_home = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = tempfile.mkdtemp(prefix="pm-home-for-test-manager-seat-")
    os.environ.pop("HERDR_PANE_ID", None)
    os.environ.pop("HC_TERMINAL_ID", None)
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

from pmlib import hooks, osutil, procs as procs_mod  # noqa: E402
from pmlib.agents.base import unwrap_seat_argv  # noqa: E402
from pmlib.agents.sessions import context_tokens  # noqa: E402
from pmlib.agents.transcripts import claude_folder  # noqa: E402
from pmlib.caller import Caller  # noqa: E402
from pmlib.commands import ledger as ledger_cmds  # noqa: E402
from pmlib.commands import manager as manager_cmds  # noqa: E402
from pmlib.commands import memory as memory_cmds  # noqa: E402
from pmlib.commands import workers as workers_cmds  # noqa: E402
from pmlib.context import StdOutput  # noqa: E402
from pmlib.events import deliver as deliver_mod  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.ledger.transition import FIELDS  # noqa: E402
from pmlib.manager import launch as launch_mod  # noqa: E402
from pmlib.manager import rotate as rotate_mod  # noqa: E402
from pmlib.manager import seat as seat_mod  # noqa: E402
from pmlib.manager.handover import conversation_tail, unanswered  # noqa: E402
from pmlib.manager.launch import successor_argv  # noqa: E402
from pmlib.manager.rotate import (  # noqa: E402
    _end_session_later_impl,
    background_work,
    build_fallback_spec,
    successor_env,
)
from pmlib.manager.seat import (  # noqa: E402
    RETIRE_WAIT,
    SEAT_NEXT_MAX_AGE,
    _reset_seat_tty,
    _wait_seat_session,
    pop_next_session,
    seat_running,
    write_seat_state,
)
from pmlib.manager.service import ManagerSessions  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import ProjectRegistry, pm_name  # noqa: E402
from pmlib.project.readmodel import answered_tasks, task_offline  # noqa: E402
from pmlib.views import status as status_views  # noqa: E402
from pmlib.views.state import dash_state  # noqa: E402
from pmlib.workers.sessions import remember_pm_session_for  # noqa: E402
from tests.fakes import FakeClock, FakeHc, FakeProcs, FakeTui, make_ctx  # noqa: E402

PM_SCRIPT = SCRIPTS / "pm.py"
SPACED = "/Users/Jo Doe/.claude/skills/pm/scripts/pm.py"


def _row(kind: str, content: Any, usage: dict[str, Any] | None = None, side: bool = False) -> str:
    message: dict[str, Any] = {"content": content}
    if usage:
        message["usage"] = usage
    return json.dumps({"type": kind, "message": message, "isSidechain": side})


@contextlib.contextmanager
def _as_windows(
    ctx: Any = None,
    script: str = SPACED,
    py: bool = True,
    exe: str = r"C:\Program Files\Python312\python.exe",
):
    """Simulate Windows python/launcher resolution on `osutil` and `procs` (and optionally `ctx.procs`)."""
    real_which = shutil.which
    resolved_script = Path(script).resolve()
    saved_launcher = getattr(ctx.procs, "_launcher", None) if ctx is not None else None
    with mock.patch.object(osutil, "WINDOWS", True), \
            mock.patch.object(procs_mod, "launcher", lambda: resolved_script), \
            mock.patch.object(sys, "executable", exe), \
            mock.patch.object(shutil, "which", lambda name, *a, **kw: (r"C:\Windows\py.exe" if py else None)
                              if name == "py" else real_which(name, *a, **kw)):
        if ctx is not None and hasattr(ctx.procs, "_launcher"):
            ctx.procs._launcher = resolved_script
        try:
            yield
        finally:
            if ctx is not None and saved_launcher is not None:
                ctx.procs._launcher = saved_launcher


class ManagerFakeHc(FakeHc):
    """FakeHc recording structured `ops` for `hc` and `herdr-app` calls, with controllable spaces and replies."""

    def __init__(
        self,
        terminals: Mapping[str, Any] | None = None,
        *,
        app_reply: Any = None,
        spaces: list[dict[str, Any]] | None = None,
        run_addr: str | Callable[[int], str] = "t50",
        name_tab_result: bool | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(terminals, **kwargs)
        self.ops: list[tuple[Any, ...]] = []
        self.run_envs: list[Any] = []
        self.app_reply: Any = {"terminal": "t60"} if app_reply is None else app_reply
        self.spaces: list[dict[str, Any]] = list(spaces or [])
        self.on_app_do: Callable[[str, Mapping[str, Any]], None] | None = None
        self._run_addr = run_addr
        self._run_count = 0
        self._name_tab_result = name_tab_result

    def get_raw(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        self.ops.append(("hc", "get", term))
        return super().get_raw(term, errors=errors)

    def run(
        self,
        argv: Iterable[str],
        *,
        name: str = "",
        cwd: str | Path = "",
        labels: Iterable[str] = (),
        bg: bool = True,
        parent: str = "",
        keep: bool = False,
        no_parent: bool = False,
        placement: Iterable[str] = (),
        env: Any = None,
    ) -> dict[str, Any] | None:
        argv_list = list(argv)
        labels_list = list(labels)
        placement_list = list(placement)
        cmd: list[Any] = ["hc", "run"]
        if bg:
            cmd.append("--bg")
        if keep:
            cmd.append("--keep")
        if no_parent:
            cmd.append("--no-parent")
        if name:
            cmd += ["--name", name]
        if parent:
            cmd += ["--parent", parent]
        cmd += placement_list
        for kv in labels_list:
            cmd += ["--label", kv]
        if cwd:
            cmd += ["--cwd", str(cwd)]
        cmd += ["--", *argv_list]
        self.ops.append(tuple(cmd))
        self.run_envs.append(env)
        if not self.server_running:
            return None
        self._run_count += 1
        addr = self._run_addr(self._run_count) if callable(self._run_addr) else str(self._run_addr)
        parsed_labels = dict(kv.split("=", 1) for kv in labels_list if "=" in kv)
        existing = self.terminals.get(addr)
        if isinstance(existing, dict):
            row = existing
            row.setdefault("address", addr)
            row.setdefault("id", addr)
            row.setdefault("state", "live")
            row.setdefault("labels", {}).update(parsed_labels)
        else:
            row = {
                "address": addr,
                "id": addr,
                "state": "live",
                "name": name or addr,
                "cwd": str(cwd),
                "argv": argv_list,
                "labels": parsed_labels,
                "status": {"state": "idle"},
                "foreground": {"argv": argv_list},
            }
            if parent and not no_parent:
                row["parent"] = parent
            if keep:
                row["keep"] = True
            self.terminals[addr] = row
        return copy.deepcopy(row)

    def send(
        self,
        term: str,
        text: str,
        *,
        if_state: str | None = None,
        timeout: float = 180,
        errors: bool = False,
    ) -> dict[str, Any] | None:
        self.ops.append(("hc", "send", term, text))
        return super().send(term, text, if_state=if_state, timeout=timeout, errors=errors)

    def label(self, term: str, *pairs: str, errors: bool = False) -> dict[str, Any] | None:
        self.ops.append(("hc", "label", term, *pairs))
        if self.server_running and term not in self.terminals:
            self.terminals[term] = {"address": term, "id": term, "state": "live", "labels": {}}
        return super().label(term, *pairs, errors=errors)

    def keep(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        self.ops.append(("hc", "keep", term))
        if self.server_running and term not in self.terminals:
            self.terminals[term] = {"address": term, "id": term, "state": "live", "labels": {}}
        return super().keep(term, errors=errors)

    def kill(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        self.ops.append(("hc", "kill", term))
        return super().kill(term, errors=errors)

    def remove(self, term: str, *, errors: bool = False) -> dict[str, Any] | None:
        self.ops.append(("hc", "rm", term))
        return super().remove(term, errors=errors)

    def name_tab(self, terminal: str, name: str, only_if: str | None = None, wait: float = 0) -> bool:
        if self._name_tab_result is not None:
            self.tab_calls.append({"fn": "name_tab", "terminal": terminal, "name": name, "only_if": only_if, "wait": wait})
            return self._name_tab_result
        return super().name_tab(terminal, name, only_if=only_if, wait=wait)

    def app_spaces(self) -> list[dict[str, Any]]:
        self.ops.append(("herdr-app", "ls"))
        if not self.app_available:
            return []
        return copy.deepcopy(self.spaces)

    def app_do(self, command: str, payload: Mapping[str, Any], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        encoded = json.dumps(dict(payload))
        self.ops.append(("herdr-app", "do", command, encoded))
        self.tab_calls.append({"fn": "app_do", "command": command, "payload": dict(payload), "timeout": timeout})
        if self.on_app_do is not None:
            self.on_app_do(command, payload)
        if not self.app_available:
            raise FileNotFoundError("herdr-app")
        reply = self.app_reply(command, payload) if callable(self.app_reply) else self.app_reply
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, subprocess.CompletedProcess):
            return reply
        return subprocess.CompletedProcess(
            ["herdr-app", "do", command, encoded], 0, json.dumps(reply), ""
        )


class ManagerFakeTui(FakeTui):
    """FakeTui with controllable `pane close` failure for archive/restore lifecycle tests."""

    def __init__(self, *args: Any, close_ok: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.close_ok = close_ok

    def herdr(self, *args: Any, session: str | None = None) -> Any:
        parts = [str(a) for a in args]
        if parts[:2] == ["pane", "close"] and not self.close_ok:
            self.calls.append((session, args))
            return None
        return super().herdr(*args, session=session)


def _clean_child_env(ledger_home: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("HC_TERMINAL_ID", "HERDR_PANE_ID", "HERDR_WORKSPACE_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID"):
        env.pop(key, None)
    env["PM_HOME"] = str(ledger_home)
    env.update(extra)
    return env


class Rotation(unittest.TestCase):
    """Transcript context tokens, conversation tail, handover summary, language config, and successor argv."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="pm-rotation-")
        self.tmp = Path(self._tmp.name)
        self.ctx = make_ctx(self.tmp / "home", git=GitRepo(), out=StdOutput())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def transcript(self) -> str:
        path = self.tmp / "session.jsonl"
        path.write_text("\n".join([
            _row("user", "先做看板"),
            _row("assistant", [{"type": "text", "text": "好，开始。"}], {"input_tokens": 10, "cache_read_input_tokens": 1000}),
            _row("user", [{"type": "tool_result", "content": "ok"}]),
            _row("assistant", [{"type": "text", "text": "看板做完了。"}],
                 {"input_tokens": 5, "cache_read_input_tokens": 250000, "cache_creation_input_tokens": 20}),
            _row("assistant", [{"type": "text", "text": "side"}], {"input_tokens": 999999}, side=True),
            _row("user", "<system-reminder>notice</system-reminder>"),
            _row("user", "不要直角线"),
        ]), encoding="utf-8")
        return str(path)

    def test_context_is_the_input_side_of_the_latest_main_call(self) -> None:
        self.assertEqual(context_tokens(self.transcript()), 250025)
        self.assertEqual(context_tokens("/nonexistent"), 0)

    def test_tail_pairs_what_the_user_typed_with_the_final_reply(self) -> None:
        tail = conversation_tail(self.transcript())
        self.assertEqual([t["user"] for t in tail], ["先做看板", "不要直角线"])
        self.assertEqual(tail[0]["pm"], "看板做完了。")  # the later text of the turn wins; tool results are skipped
        self.assertEqual(tail[1]["pm"], "")

    def test_handover_carries_decisions_notes_and_open_work(self) -> None:
        repo_dir = self.tmp / "repo"
        repo_dir.mkdir()
        repo = str(repo_dir)
        root = self.ctx.git.project_root(repo)
        assert root is not None
        name = Path(root).name
        with contextlib.redirect_stdout(io.StringIO()):
            memory_cmds.cmd_decide(type("A", (), {"repo": repo, "text": "连线不用直角", "quote": "不要有直角线"}), ctx=self.ctx)
        handover_path = self.ctx.home.project_for(root).handover
        handover_path.parent.mkdir(parents=True, exist_ok=True)
        handover_path.write_text("用户正要验证点击跳转\n", encoding="utf-8")
        task = {"id": f"{name}-a", "title": "做看板", "project": name, "repo": root, "status": "in_progress",
                "owner": "pm", "base": "main", "pane": "hc:t9", "created": self.ctx.clock.now()}
        Ledger(self.ctx).save(task)

        def _add_note(cur: Any, ch: Any) -> Any:
            ch.note("dispatched")
            return cur

        Ledger(self.ctx).change(f"{name}-a", _add_note)
        for full in (False, True):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                manager_cmds.cmd_handover(type("A", (), {"repo": repo, "turns": 6, "full": full}), ctx=self.ctx)
            text = out.getvalue()
            for part in ("连线不用直角", "用户正要验证点击跳转", f"{name}-a", "dispatched"):
                self.assertIn(part, text)
            # The user's words are in the whole record (and `pm.py decisions`), not in the short handover.
            self.assertEqual('the user\'s words: "不要有直角线"' in text, full)

    def test_builtin_text_is_english_unless_configured(self) -> None:
        self.assertEqual(self.ctx.config.tr("User", "用户"), "User")
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({"lang": "zh"}), encoding="utf-8")
        self.assertEqual(self.ctx.config.tr("User", "用户"), "用户")
        self.assertEqual(dash_state(ctx=self.ctx)["lang"], "zh")

    def test_successor_keeps_flags_but_not_the_old_session(self) -> None:
        args = ["--resume", "abc-123", "--mcp-config", "/x/mcp.json", "--model", "old", "--chrome", "earlier prompt"]
        self.assertEqual(successor_argv("claude", args, "new", "接手", ctx=self.ctx),
                         ["claude", "--mcp-config", "/x/mcp.json", "--chrome", "--model", "new", "--", "接手"])
        # A flag that takes a value keeps it. `--allowed-tools` takes any number of values, so the prompt comes
        # after `--`; without it claude reads the prompt as one more tool name and starts with nothing to do.
        args = ["--plugin-dir", "/p", "--allowed-tools", "a", "--allowed-tools", "b", "--resume", "abc"]
        self.assertEqual(successor_argv("claude", args, "", "接手", ctx=self.ctx),
                         ["claude", "--plugin-dir", "/p", "--allowed-tools", "a", "--allowed-tools", "b", "--", "接手"])
        # The outgoing session was itself started this way: its `--` and first prompt are not carried over.
        args = ["--allowed-tools", "a", "--", "上一任的接手提示"]
        self.assertEqual(successor_argv("claude", args, "", "接手", ctx=self.ctx),
                         ["claude", "--allowed-tools", "a", "--", "接手"])
        args = ["--resume", "abc-123", "--mcp-config", "/x/mcp.json", "--model", "old", "--chrome", "earlier prompt"]
        # Other agents start from their registry entry; the outgoing session's flags are not theirs to carry.
        self.assertEqual(successor_argv("codex", args, "new", "接手", ctx=self.ctx),
                         ["codex", "-c", "check_for_update_on_startup=false", "-m", "new", "接手"])
        self.assertEqual(successor_argv("gemini", args, "", "接手", ctx=self.ctx), ["gemini"])  # prompt is typed in afterwards


class ProjectLifecycle(unittest.TestCase):
    """archive, restore and start's --name/--space, with fake hc, herdr-app, and herdr TUI."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="pm-lifecycle-")
        self.tmp = Path(self._tmp.name)
        repo_dir = self.tmp / "proj"
        repo_dir.mkdir()
        self.hc = ManagerFakeHc(app_reply={"terminal": "t60"}, spaces=[], run_addr="t50")
        self.tui = ManagerFakeTui(agents=[])
        self.clock = FakeClock(datetime.datetime.now().replace(microsecond=0))
        self.ctx = make_ctx(
            self.tmp / "home",
            hc=self.hc,
            tui=self.tui,
            git=GitRepo(),
            clock=self.clock,
            out=StdOutput(),
        )
        self.ctx.seat_alive = lambda repo, rec, term=None: seat_mod.seat_alive(repo, rec, term, ctx=self.ctx)
        root = self.ctx.git.project_root(str(repo_dir))
        assert root is not None
        self.repo = root
        self.name = Path(self.repo).name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def register(self, terminal: str = "t7") -> None:
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.ctx.home.registration(project_slug(self.repo)).write_text(json.dumps(
            {"name": pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": f"hc:{terminal}",
             "runtime": "hc", "terminal": terminal, "agent": "claude"}), encoding="utf-8")
        self.hc.terminals[terminal] = {"state": "live", "labels": {"pm": self.name}, "cwd": self.repo}

    def task(self, slug: str, status: str) -> None:
        Ledger(self.ctx).save({"id": f"{self.name}-{slug}", "title": slug, "project": self.name, "repo": self.repo,
                               "status": status, "owner": "pm", "base": "main", "created": self.ctx.clock.now()})

    def quiet(self, fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*args, ctx=self.ctx, **kw)

    def test_archive_pauses_open_tasks_ends_only_the_pm_terminal_and_runs_once(self) -> None:
        self.register()
        self.hc.terminals["t8"] = {"state": "live", "labels": {"task": f"{self.name}-a"}}  # a worker: left alone
        for slug, status in (("a", "in_progress"), ("b", "blocked"), ("c", "merged"), ("d", "paused")):
            self.task(slug, status)
        self.quiet(manager_cmds.cmd_archive, argparse.Namespace(project=self.repo))
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertEqual(rec["archived"], self.ctx.clock.now()[:10])
        got = {t["id"][len(self.name) + 1:]: (t["status"], t.get("paused_from"))
               for t in Ledger(self.ctx).project_tasks(self.repo)}
        self.assertEqual(got, {"a": ("paused", "in_progress"), "b": ("paused", "blocked"), "c": ("merged", None),
                               "d": ("paused", None)})
        self.assertIn("project archived", Ledger(self.ctx).load(f"{self.name}-a").raw["log"][-1]["text"])
        self.assertEqual([c for c in self.hc.ops if c[:2] in (("hc", "label"), ("hc", "kill"), ("hc", "rm"))],
                         [("hc", "label", "t7", "pm=", "pm.seat="), ("hc", "kill", "t7"),
                          ("hc", "rm", "t7")])
        # Again: nothing changes, nothing is ended.
        self.hc.ops.clear()
        before = [Ledger(self.ctx).load(f"{self.name}-{s}").raw for s in "abcd"]
        self.quiet(manager_cmds.cmd_archive, argparse.Namespace(project=self.name))  # by its name this time
        self.assertEqual([Ledger(self.ctx).load(f"{self.name}-{s}").raw for s in "abcd"], before)
        self.assertEqual(self.hc.ops, [])

    def test_archive_leaves_a_terminal_without_the_pm_label(self) -> None:
        self.register()
        self.hc.terminals["t7"]["labels"] = {}
        self.quiet(manager_cmds.cmd_archive, argparse.Namespace(project=self.repo))
        self.assertFalse([c for c in self.hc.ops if c[:2] in (("hc", "kill"), ("hc", "rm"))])
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertTrue(rec["archived"])

    def test_restore_puts_tasks_back_and_starts_a_pm_from_the_handover(self) -> None:
        self.register()
        self.task("a", "review")
        self.task("d", "paused")
        self.quiet(manager_cmds.cmd_archive, argparse.Namespace(project=self.repo))
        self.hc.terminals.pop("t7", None)  # ended by the archive
        self.quiet(manager_cmds.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        self.assertEqual(Ledger(self.ctx).load(f"{self.name}-a").raw["status"], "review")
        self.assertNotIn("paused_from", Ledger(self.ctx).load(f"{self.name}-a").raw)
        self.assertEqual(Ledger(self.ctx).load(f"{self.name}-d").raw["status"], "paused")  # paused by hand: stays
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertNotIn("archived", rec)
        self.assertEqual((rec["terminal"], rec["pane"]), ("t60", "hc:t60"))
        made = [json.loads(c[3]) for c in self.hc.ops if c[:3] == ("herdr-app", "do", "space.new")]
        self.assertEqual([(m["name"], m["folder"]) for m in made], [(self.name, self.repo)])
        self.assertIn("[from pm.py restore]", made[0]["argv"][-1])
        self.assertIn("handover", made[0]["argv"][-1])

    def test_the_handover_line_in_the_start_and_restore_prompts(self) -> None:
        def prompts() -> list[str]:
            return [json.loads(c[3])["argv"][-1] for c in self.hc.ops if c[:3] == ("herdr-app", "do", "space.new")]

        self.quiet(manager_cmds.cmd_start, argparse.Namespace(repo=self.repo, kind="claude", model=None, name="", space="new"))
        self.assertIn(f"`{self.ctx.procs.pm_script()} handover`", prompts()[-1])  # as before
        self.register()
        self.quiet(manager_cmds.cmd_archive, argparse.Namespace(project=self.repo))
        self.hc.terminals.pop("t7", None)
        spaced_resolved = Path(SPACED).resolve().as_posix() if osutil.WINDOWS else SPACED
        with _as_windows(self.ctx):
            self.quiet(manager_cmds.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        self.assertIn("[from pm.py restore]", prompts()[-1])
        self.assertIn(f'`py -3 "{spaced_resolved}" handover`', prompts()[-1])
        for path in self.ctx.home.registrations.glob("*.json"):
            path.unlink()
        with _as_windows(self.ctx):
            self.quiet(manager_cmds.cmd_start, argparse.Namespace(repo=self.repo, kind="claude", model=None, name="", space="new"))
        self.assertIn(f'`py -3 "{spaced_resolved}" handover`', prompts()[-1])

    def test_start_name_and_space(self) -> None:
        self.quiet(manager_cmds.cmd_start, argparse.Namespace(repo=self.repo, kind="codex", model=None, name="家里网络",
                                                              space="new"))
        made = [(c[2], json.loads(c[3])) for c in self.hc.ops if c[:2] == ("herdr-app", "do")]
        self.assertEqual([(cmd, m["name"], unwrap_seat_argv(m["argv"])[1][0]) for cmd, m in made],
                         [("space.new", "家里网络", "codex")])
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertEqual((rec["terminal"], rec["agent"], rec["space_name"], rec["seat"]),
                         ("t60", "codex", "家里网络", True))
        self.ctx.home.registration(project_slug(self.repo)).unlink()
        # current, from a terminal without a space: bare hc run, then terminal.keep gives it a tab and names it.
        self.hc.ops.clear()
        self.hc.tab_calls.clear()
        self.quiet(manager_cmds.cmd_start, argparse.Namespace(repo=self.repo, kind="pi", model=None, name=None,
                                                              space="current"))
        app_cmds = [(c[2], json.loads(c[3])) for c in self.hc.ops if c[:2] == ("herdr-app", "do")]
        self.assertEqual(app_cmds, [("terminal.keep", {"terminal": "t50", "place": "tab"})])
        self.assertTrue(any(c["fn"] == "name_tab" and c["terminal"] == "t50" and c["name"] == f"PM-{self.name}"
                            for c in self.hc.tab_calls))
        rec2 = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec2 is not None
        self.assertEqual((rec2["terminal"], rec2["seat"]), ("t50", True))
        self.assertNotIn("space_name", rec2)

    def test_start_fallback_attaches_tab_when_app_reachable_and_warns_when_unreachable(self) -> None:
        # 1. space.new exits non-0, fallback hc run creates t50, then terminal.keep retries past 0ms core sync
        #    race ("no running terminal") and renames the tab.
        keep_attempts = {"n": 0}

        def fail_space_keep_retry(command: str, payload: Mapping[str, Any]) -> Any:
            if command == "space.new":
                return subprocess.CompletedProcess(["herdr-app", "do", command], 1, '{"error":"busy"}', "")
            if command == "terminal.keep":
                keep_attempts["n"] += 1
                if keep_attempts["n"] == 1:
                    return subprocess.CompletedProcess(["herdr-app", "do", command], 1, '{"error":"no running terminal \\"t50\\""}', "")
            return {"pending": True}

        self.hc.app_reply = fail_space_keep_retry
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            manager_cmds.cmd_start(argparse.Namespace(repo=self.repo, kind="claude", model=None, name="", space="new"),
                                   ctx=self.ctx)
        app_cmds = [(c[2], json.loads(c[3])) for c in self.hc.ops if c[:2] == ("herdr-app", "do")]
        self.assertEqual([c for c, _ in app_cmds], ["space.new", "terminal.keep", "terminal.keep"])
        self.assertEqual(app_cmds[-1][1], {"terminal": "t50", "place": "tab"})
        self.assertTrue(any(c["fn"] == "name_tab" and c["terminal"] == "t50" and c["name"] == f"PM-{self.name}"
                            for c in self.hc.tab_calls))
        self.assertNotIn("without a desktop tab", out.getvalue())

        # 1b. Multiple spaces open (other project active, this project inactive): selects this project's space
        #     before terminal.keep so the PM does not land in the wrong active space.
        self.ctx.home.registration(project_slug(self.repo)).unlink()
        self.hc.terminals.pop("t50", None)
        self.hc.ops.clear()
        self.hc.tab_calls.clear()
        self.hc.spaces = [
            {"id": "sp-other", "name": "other", "folder": "/other/repo", "active": True, "tabs": []},
            {"id": "sp-mine", "name": self.name, "folder": self.repo, "active": False, "tabs": []},
        ]
        self.hc.app_reply = lambda cmd, _p: (
            subprocess.CompletedProcess(["herdr-app", "do", cmd], 1, '{"error":"busy"}', "")
            if cmd == "space.new" else {"ok": True}
        )
        out_multi = io.StringIO()
        with contextlib.redirect_stdout(out_multi):
            manager_cmds.cmd_start(argparse.Namespace(repo=self.repo, kind="claude", model=None, name="", space="new"),
                                   ctx=self.ctx)
        multi_cmds = [(c[2], json.loads(c[3])) for c in self.hc.ops if c[:2] == ("herdr-app", "do")]
        self.assertEqual(multi_cmds, [
            ("space.new", multi_cmds[0][1]),
            ("space.select", {"id": "sp-mine"}),
            ("terminal.keep", {"terminal": "t50", "place": "tab"}),
        ])
        self.assertNotIn("without a desktop tab", out_multi.getvalue())

        # 1c. Only another project's space is open (no space for this repo): adopts via fresh herdr.space/herdr.tab
        #     labels + space.rename instead of bare terminal.keep into the unrelated active space.
        self.ctx.home.registration(project_slug(self.repo)).unlink()
        self.hc.terminals.pop("t50", None)
        self.hc.ops.clear()
        self.hc.tab_calls.clear()
        self.hc.spaces = [
            {"id": "sp-other", "name": "other", "folder": "/other/repo", "active": True, "tabs": []},
        ]
        out_other = io.StringIO()
        with contextlib.redirect_stdout(out_other):
            manager_cmds.cmd_start(argparse.Namespace(repo=self.repo, kind="claude", model=None, name="自定义名", space="new"),
                                   ctx=self.ctx)
        other_cmds = [(c[2], json.loads(c[3])) for c in self.hc.ops if c[:2] == ("herdr-app", "do")]
        self.assertNotIn("terminal.keep", [c for c, _ in other_cmds])
        self.assertTrue(any(c == "space.rename" and p.get("name") == "自定义名" for c, p in other_cmds))
        t50_labels = self.hc.terminals["t50"]["labels"]
        self.assertTrue(str(t50_labels.get("herdr.space", "")).startswith("sp"))
        self.assertTrue(str(t50_labels.get("herdr.tab", "")).startswith("tb"))
        self.assertNotIn("without a desktop tab", out_other.getvalue())
        self.hc.spaces = []

        # 2. Both space.new and terminal.keep return non-0: start still succeeds but explicitly explains how to attach.
        self.ctx.home.registration(project_slug(self.repo)).unlink()
        self.hc.terminals.pop("t50", None)
        self.hc.ops.clear()
        self.hc.app_reply = subprocess.CompletedProcess(["herdr-app", "do"], 1, '{"error":"no window"}', "")
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2):
            manager_cmds.cmd_start(argparse.Namespace(repo=self.repo, kind="claude", model=None, name="", space="new"),
                                   ctx=self.ctx)
        self.assertIn("without a desktop tab", out2.getvalue())
        self.assertIn("terminal.keep", out2.getvalue())
        self.assertIn('"terminal":"t50"', out2.getvalue())

        # 3. app_do raises OSError (herdr-app missing): skips redundant terminal.keep and prints guidance (zh too).
        self.ctx.home.registration(project_slug(self.repo)).unlink()
        self.hc.terminals.pop("t50", None)
        self.hc.ops.clear()
        self.hc.app_available = False
        self.ctx.home.config.write_text(json.dumps({"lang": "zh"}), encoding="utf-8")
        out3 = io.StringIO()
        with contextlib.redirect_stdout(out3):
            manager_cmds.cmd_start(argparse.Namespace(repo=self.repo, kind="claude", model=None, name="", space="new"),
                                   ctx=self.ctx)
        self.assertEqual([c[2] for c in self.hc.ops if c[:2] == ("herdr-app", "do")], ["space.new"])
        self.assertIn("没有桌面标签页", out3.getvalue())
        self.assertIn("terminal.keep", out3.getvalue())
        self.assertIn('"terminal":"t50"', out3.getvalue())

    def test_rotate_legacy_to_seat_fallback_attaches_or_warns(self) -> None:
        self.register()
        self.ctx.store.change_registration(project_slug(self.repo), lambda cur: {**(cur or {}), "seat": False})
        self.hc.terminals["t7"] = {
            "state": "live",
            "labels": {"pm": self.name, "herdr.space": "sp-1"},
            "argv": ["claude", "--model", "opus"],
            "foreground": {"argv": ["claude", "--model", "opus"]},
        }
        # 1. tab.new returns non-0, terminal.keep succeeds and gives t50 a named tab.
        def fail_tab_keep_ok(command: str, payload: Mapping[str, Any]) -> Any:
            if command == "tab.new":
                return subprocess.CompletedProcess(["herdr-app", "do", command], 1, '{"error":"space gone"}', "")
            return {"ok": True}

        self.hc.app_reply = fail_tab_keep_ok
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            manager_cmds.cmd_rotate(argparse.Namespace(repo=self.repo, notes="swap", reason="test", model=None,
                                                       transcript=None), ctx=self.ctx)
        app_cmds = [(c[2], json.loads(c[3])) for c in self.hc.ops if c[:2] == ("herdr-app", "do")]
        self.assertEqual([c for c, _ in app_cmds], ["tab.new", "terminal.keep"])
        self.assertEqual(app_cmds[1][1], {"terminal": "t50", "place": "tab"})
        self.assertTrue(any(c["fn"] == "name_tab" and c["terminal"] == "t50" and c["name"] == f"PM-{self.name}"
                            for c in self.hc.tab_calls))
        self.assertNotIn("without a desktop tab", out.getvalue())

        # 2. app_do raises OSError on rotate: warns clearly with terminal.keep recovery command.
        self.hc.terminals.pop("t50", None)
        self.hc.terminals["t7"] = {
            "state": "live",
            "labels": {"pm": self.name, "herdr.space": "sp-1"},
            "argv": ["claude", "--model", "opus"],
            "foreground": {"argv": ["claude", "--model", "opus"]},
        }
        self.ctx.store.change_registration(project_slug(self.repo), lambda cur: {
            **(cur or {}), "pane": "hc:t7", "terminal": "t7", "seat": False,
        })
        self.hc.ops.clear()
        self.hc.app_available = False
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2):
            manager_cmds.cmd_rotate(argparse.Namespace(repo=self.repo, notes="swap", reason="test", model=None,
                                                       transcript=None), ctx=self.ctx)
        self.assertIn("without a desktop tab", out2.getvalue())
        self.assertIn("terminal.keep", out2.getvalue())

    def test_start_refuses_a_missing_folder_or_a_file(self) -> None:
        missing = str(Path(self.repo) / "nope")
        (Path(self.repo) / "file").write_text("x", encoding="utf-8")
        for repo in (missing, str(Path(self.repo) / "file")):
            with self.assertRaises(SystemExit):
                self.quiet(manager_cmds.cmd_start, argparse.Namespace(repo=repo, kind=None, model=None, name=None, space="new"))
        self.assertFalse(self.hc.ops)

    def archived_with_two_paused(self) -> str:
        self.register()
        self.task("a", "review")
        self.task("b", "blocked")
        self.quiet(manager_cmds.cmd_archive, argparse.Namespace(project=self.repo))
        self.hc.terminals.pop("t7", None)
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        return rec["archived"]

    def assert_still_archived(self, date: str) -> None:
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertEqual(rec["archived"], date)
        got = {t["id"][len(self.name) + 1:]: (t["status"], t.get("paused_from"))
               for t in Ledger(self.ctx).project_tasks(self.repo)}
        self.assertEqual(got, {"a": ("paused", "review"), "b": ("paused", "blocked")})

    def test_restore_checks_first_and_changes_nothing_when_it_cannot_start(self) -> None:
        date = self.archived_with_two_paused()
        self.hc.server_running = False  # herdr-core not reachable
        try:
            with self.assertRaises(SystemExit):
                self.quiet(manager_cmds.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        finally:
            self.hc.server_running = True
        self.assert_still_archived(date)
        self.hc.terminals["t7"] = {"state": "live", "labels": {"pm": self.name}}  # an old PM still runs
        with self.assertRaises(SystemExit):
            self.quiet(manager_cmds.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        self.assert_still_archived(date)
        self.assertFalse([c for c in self.hc.ops if c[:3] == ("herdr-app", "do", "space.new")])

    def test_a_restore_whose_start_fails_is_rolled_back_and_exits_non_zero(self) -> None:
        date = self.archived_with_two_paused()
        self.hc.app_reply = {}  # space.new answers without a terminal, and no new space is open
        with self.assertRaises(SystemExit) as stop:
            self.quiet(manager_cmds.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
        self.assertNotIn(stop.exception.code, (0, None))
        self.assert_still_archived(date)
        self.assertNotIn(("hc", "run"), [c[:2] for c in self.hc.ops])  # no bare-terminal PM either

    def test_archive_ends_a_herdr_tui_pm_and_restore_is_not_stuck_on_it(self) -> None:
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        reg_path = self.ctx.home.registration(project_slug(self.repo))
        reg_path.write_text(json.dumps(
            {"name": pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "wT:p1"}), encoding="utf-8")
        for close_ok in (True, False):
            self.tui._agents = [{"pane_id": "wT:p1", "name": pm_name(self.repo), "cwd": self.repo},
                                {"pane_id": "wT:p2", "name": "worker"}]
            self.tui.server_ok = True
            self.tui.close_ok = close_ok
            self.tui.calls.clear()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                manager_cmds.cmd_archive(argparse.Namespace(project=self.repo), ctx=self.ctx)
            tui_ops = [args for _, args in self.tui.calls if args[:2] in (("agent", "rename"), ("pane", "close"))]
            self.assertEqual(tui_ops,
                             [("agent", "rename", "wT:p1", f"ex-{pm_name(self.repo)}"),
                              ("pane", "close", "wT:p1")])
            if not close_ok:
                self.assertIn("close it by hand", out.getvalue())  # the pane is still there, renamed
            self.assertIsNone(ProjectRegistry(self.ctx).find_pm(repo=self.repo))
            self.quiet(manager_cmds.cmd_restore, argparse.Namespace(project=self.repo, kind=None, model=None))
            rec = ProjectRegistry(self.ctx).pm_record(self.repo)
            assert rec is not None
            self.assertEqual(rec["terminal"], "t60")
            self.hc.terminals.pop("t60", None)
            reg_path.write_text(json.dumps(
                {"name": pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "wT:p1"}), encoding="utf-8")
        self.tui.server_ok = False  # herdr not reachable: said, not silently skipped
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            manager_cmds.cmd_archive(argparse.Namespace(project=self.repo), ctx=self.ctx)
        self.assertIn("not reachable", out.getvalue())

    def test_a_space_new_that_times_out_reuses_the_space_it_made(self) -> None:
        old = {"id": "sp-old", "name": "家里网络", "tabs": [{"id": "tb1", "terminals": [{"terminal": "t1"}]}]}
        made = {"id": "sp-new", "name": "家里网络", "tabs": [{"id": "tb2", "terminals": [{"terminal": "t61"}]}]}
        self.hc.spaces = [old]  # an older space of the same name is not the one this start made
        self.hc.app_reply = subprocess.TimeoutExpired("herdr-app", 30)

        def on_do(command: str, payload: Mapping[str, Any]) -> None:
            if command == "space.new":
                self.hc.spaces = [old, made]  # the app made the space, but its answer came too late

        self.hc.on_app_do = on_do
        try:
            self.quiet(manager_cmds.cmd_start, argparse.Namespace(repo=self.repo, kind="codex", model=None, name="家里网络",
                                                                  space="new"))
        finally:
            self.hc.on_app_do = None
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertEqual(rec["terminal"], "t61")
        self.assertNotIn(("hc", "run"), [c[:2] for c in self.hc.ops])
        # Timed out and no new space under that name: an error, and no bare-terminal PM.
        self.ctx.home.registration(project_slug(self.repo)).unlink()
        self.hc.spaces = [old]
        self.hc.ops.clear()
        with self.assertRaises(SystemExit):
            self.quiet(manager_cmds.cmd_start, argparse.Namespace(repo=self.repo, kind="codex", model=None, name="家里网络",
                                                                  space="new"))
        self.assertNotIn(("hc", "run"), [c[:2] for c in self.hc.ops])
        self.assertIsNone(ProjectRegistry(self.ctx).pm_record(self.repo))

    def test_name_with_space_current_is_said_not_ignored(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.quiet(manager_cmds.cmd_start, argparse.Namespace(repo=self.repo, kind="pi", model=None, name="别名",
                                                                  space="current"))
        self.assertIn("--space current", err.getvalue())

    def test_state_has_archived_and_card_counts(self) -> None:
        self.register()
        for slug, status in (("a", "in_progress"), ("b", "blocked"), ("c", "review"), ("d", "proposed"),
                             ("e", "merged"), ("f", "paused")):
            self.task(slug, status)
        row = next(p for p in dash_state(ctx=self.ctx)["pms"] if p["repo"] == self.repo)
        self.assertIsNone(row["archived"])
        self.assertEqual(row["counts"], {"working": 1, "waiting": 1, "review": 1, "proposed": 1, "merged_today": 1})
        self.quiet(manager_cmds.cmd_archive, argparse.Namespace(project=self.repo))
        state = dash_state(ctx=self.ctx)
        row = next(p for p in state["pms"] if p["repo"] == self.repo)
        self.assertEqual(row["archived"], self.ctx.clock.now()[:10])
        self.assertEqual(row["counts"], {"working": 0, "waiting": 0, "review": 0, "proposed": 0, "merged_today": 1})
        a = next(t for t in state["tasks"] if t["id"] == f"{self.name}-a")
        self.assertEqual((a["status"], a["paused_from"]), ("paused", "in_progress"))

    def test_a_review_thread_names_its_task_and_counts_with_it(self) -> None:
        self.register()
        self.task("w", "review")
        Ledger(self.ctx).save({"id": f"{self.name}-w-review", "title": "审查：w", "project": self.name, "repo": self.repo,
                               "status": "in_progress", "owner": "pm", "base": "main", "review_of": f"{self.name}-w",
                               "created": self.ctx.clock.now()})
        state = dash_state(ctx=self.ctx)
        tasks = {t["id"]: t for t in state["tasks"]}
        self.assertEqual(tasks[f"{self.name}-w-review"]["review_of"], f"{self.name}-w")
        self.assertNotIn("review_of", tasks[f"{self.name}-w"])
        row = next(p for p in state["pms"] if p["repo"] == self.repo)
        self.assertEqual((row["counts"]["working"], row["counts"]["review"]), (0, 1))
        # The task counts as the views show it: in review while the review is open, waiting when the review asks,
        # its own status when either is paused.
        def counts() -> dict[str, int]:
            return next(p for p in dash_state(ctx=self.ctx)["pms"] if p["repo"] == self.repo)["counts"]

        mine = lambda c: (c["working"], c["waiting"], c["review"])
        rid, wid = f"{self.name}-w-review", f"{self.name}-w"

        def set_status(tid: str, s: str) -> None:
            data = json.loads(self.ctx.home.task(tid).read_text(encoding="utf-8"))
            Ledger(self.ctx).save({**data, "status": s})

        set_status(wid, "in_progress")
        self.assertEqual(mine(counts()), (0, 0, 1))
        set_status(rid, "blocked")
        self.assertEqual(mine(counts()), (0, 1, 0))
        set_status(wid, "paused")
        set_status(rid, "paused")
        self.assertEqual(mine(counts()), (0, 0, 0))
        # The task over while its review is open: the review counts on its own.
        set_status(wid, "abandoned")
        set_status(rid, "in_progress")
        self.assertEqual(mine(counts()), (1, 0, 0))
        set_status(wid, "review")
        # The task it reviews gone from the ledger: the review counts on its own again.
        os.remove(self.ctx.home.task(f"{self.name}-w"))
        row = next(p for p in dash_state(ctx=self.ctx)["pms"] if p["repo"] == self.repo)
        self.assertEqual((row["counts"]["working"], row["counts"]["review"]), (1, 0))

    def test_waiting_counts_each_blocked_task_once_by_repo_then_name(self) -> None:
        self.register()
        self.task("own", "blocked")
        # Another project's name, but in this PM's repo: the repo decides, it counts here.
        Ledger(self.ctx).save({"id": f"{self.name}-side", "title": "side", "project": "side-project", "repo": self.repo,
                               "status": "blocked", "owner": "pm", "base": "main", "created": self.ctx.clock.now()})
        # No PM for this repo or name: in no project's count, so not in the sidebar's total either.
        nobody = self.tmp / "nobody"
        nobody.mkdir()
        Ledger(self.ctx).save({"id": f"{self.name}-orphan", "title": "orphan", "project": f"{self.name}-nobody",
                               "repo": str(nobody), "status": "blocked", "owner": "pm", "base": "main",
                               "created": self.ctx.clock.now()})
        state = dash_state(ctx=self.ctx)
        row = next(p for p in state["pms"] if p["repo"] == self.repo)
        self.assertEqual(row["counts"]["waiting"], 2)
        mine = {t["id"]: t["pm"] for t in state["tasks"] if t["id"].startswith(f"{self.name}-")}
        self.assertEqual(mine, {f"{self.name}-own": row["name"], f"{self.name}-side": row["name"],
                                f"{self.name}-orphan": ""})
        self.assertEqual(sum(p["counts"]["waiting"] for p in state["pms"] if not p["archived"]), 2)

    def test_an_answered_question_is_not_waiting(self) -> None:
        """A blocked task whose question the user answered (the card's 【title】option) waits for the PM, not the user."""
        self.register()
        self.task("ask", "blocked")
        self.task("other", "blocked")
        tid = f"{self.name}-ask"
        conv = Conversation(self.ctx, self.repo)
        conv.record("thread", task=tid, title="ask", status="blocked", text="A or B?", options=["A", "B"])

        def state() -> dict[str, Any]:
            return dash_state(ctx=self.ctx)

        row = lambda s: next(p for p in s["pms"] if p["repo"] == self.repo)
        task = lambda s: next(t for t in s["tasks"] if t["id"] == tid)
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], "answered" in task(s)), (2, False))
        conv.record("user", text="【ask】A")
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], task(s).get("answered")), (1, True))
        self.assertNotIn("answered", next(t for t in s["tasks"] if t["id"] == f"{self.name}-other"))
        # A reply in between changes nothing; the task asking again is a new question, unanswered.
        conv.record("pm", text="收到")
        self.assertEqual(row(state())["counts"]["waiting"], 1)
        # The PM asks again while the task is still blocked: update --status blocked --ask says so in the log.
        conv.record("user", text="【ask】B")
        self.assertEqual(row(state())["counts"]["waiting"], 1)
        self.quiet(ledger_cmds.cmd_update, argparse.Namespace(
            id=tid, status="blocked", note="B 的哪一种？", option=None, why=None,
            recommend=False, keep=False, ask=True,
            **{f: None for f in FIELDS if f != "status"},
        ))
        self.assertTrue(conv.events()[-1]["text"].startswith("status=blocked; "))
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], "answered" in task(s)), (2, False))
        conv.record("user", text="【ask】B1")
        self.assertEqual(row(state())["counts"]["waiting"], 1)
        conv.record("thread", task=tid, title="ask", status="in_progress", text="doing A")
        conv.record("thread", task=tid, title="ask", status="blocked", text="C or D?", options=["C", "D"])
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], "answered" in task(s)), (2, False))

    def test_a_blocked_task_the_log_never_shows_is_answered_by_its_ledger_title(self) -> None:
        """Blocked before the conversation log began (no thread event; under the project's old name, owned by repo):
        it waits, and words that start with its 【title】 in the ledger answer it, as a card's would."""
        self.register()
        tid = f"{self.name}-ax"
        Ledger(self.ctx).save({"id": tid, "title": "辅助功能授权", "project": "OldName", "repo": self.repo,
                               "status": "blocked", "owner": "pm", "base": "main", "created": "2026-10-25 10:00",
                               "log": [
                                   {"at": "2026-10-25 10:00", "by": "hc:t9", "text": "registered (in_progress)"},
                                   {"at": "2026-10-25 10:30", "by": "hc:t9", "text": "status=blocked; 要不要开辅助功能权限？"},
                               ]})
        self.task("other", "blocked")
        conv = Conversation(self.ctx, self.repo)
        conv.record("thread", task=f"{self.name}-other", title="other", status="blocked", text="A or B?")

        def state() -> dict[str, Any]:
            return dash_state(ctx=self.ctx)

        row = lambda s: next(p for p in s["pms"] if p["repo"] == self.repo)
        task = lambda s: next(t for t in s["tasks"] if t["id"] == tid)
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], task(s)["pm"], "answered" in task(s)), (2, row(s)["name"], False))
        conv.record("user", text="现在开")                          # names no question
        self.assertEqual(row(state())["counts"]["waiting"], 2)
        conv.record("user", text="【辅助功能授权】现在开")
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], task(s).get("answered"), task(s)["asked_at"]),
                         (1, True, "2026-10-25 10:30"))
        # A note on it afterwards (pm.py log) asks nothing: the answer stands, as on a task with a card.
        self.quiet(status_views.cmd_log, argparse.Namespace(id=tid, text="等用户回家再开"))
        s = state()
        self.assertEqual((row(s)["counts"]["waiting"], task(s).get("answered")), (1, True))
        # Recording that answer with --status blocked again is refused, as for a task with a card.
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.quiet(ledger_cmds.cmd_update, argparse.Namespace(**{
                "id": tid, "option": None, "why": None, "recommend": False,
                "keep": False, "ask": False, "note": "用户：现在开",
                **{f: None for f in FIELDS}, "status": "blocked",
            }))

    def test_blocked_again_on_an_answered_task_needs_ask(self) -> None:
        """Recording an answer with --status blocked would open a new question: refused unless --ask."""
        self.task("q", "in_progress")
        tid = f"{self.name}-q"
        conv = Conversation(self.ctx, self.repo)
        update = lambda **kw: self.quiet(ledger_cmds.cmd_update, argparse.Namespace(**{
            "id": tid, "option": None, "why": None, "recommend": False, "keep": False, "ask": False, "note": None,
            **{f: None for f in FIELDS}, **kw,
        }))
        answered = lambda: tid in answered_tasks(conv.events())
        update(status="blocked", note="现在装还是做完再装？")  # the first question: no --ask needed
        update(status="blocked", note="补一句")              # not answered yet: blocked again as before
        self.assertEqual(Ledger(self.ctx).load(tid).raw["status"], "blocked")
        conv.record("user", text="【q】全部做好了再装")
        self.assertTrue(answered())
        before, events = Ledger(self.ctx).load(tid).raw, len(conv.events())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            update(status="blocked", note="用户：全部做好了再装")
        self.assertIn("--ask", str(stop.exception.code))
        self.assertEqual((Ledger(self.ctx).load(tid).raw, len(conv.events())), (before, events))  # nothing written
        self.assertTrue(answered())
        with self.assertRaises(SystemExit):
            update(status="in_progress", ask=True)          # --ask is only for asking
        update(status="blocked", note="装到哪台机器？", ask=True)  # a follow-up: a new question
        self.assertFalse(answered())
        conv.record("user", text="【q】dev")
        update(status="in_progress", note="用户：装到 dev")       # recording the answer: moves on
        self.assertEqual(Ledger(self.ctx).load(tid).raw["status"], "in_progress")
        self.assertFalse(answered())

    def test_answered_tasks_follow_the_question_cards_rule(self) -> None:
        ev = lambda kind, **f: {"type": kind, **f}
        asked = [ev("thread", task="k", title="old", status="in_progress"), ev("thread", task="k", status="blocked")]
        titles = {"k": "限流"}
        self.assertEqual(answered_tasks(asked, titles), set())
        self.assertEqual(answered_tasks(asked + [ev("user", text=" 【限流】 Redis ")], titles), {"k"})
        self.assertEqual(answered_tasks(asked + [ev("user", text="用 Redis 吧")], titles), set())   # names no question
        # The card's "own words" row: the box's words after the 【title】, with the files it carried.
        own = "【限流】都不要，先不限流\n\n附件：\n/tmp/a.png"
        self.assertEqual(answered_tasks(asked + [ev("user", text=own)], titles), {"k"})
        # With a pasted screenshot the log has its image mark first: still the card's answer, as in pm-project.
        for marked in ("[Image #1]【限流】都不要", "[Image #2] [Image #3]【限流】都不要", "[Image #1]\n【限流】都不要"):
            self.assertEqual(answered_tasks(asked + [ev("user", text=marked)], titles), {"k"}, marked)
        self.assertEqual(answered_tasks(asked + [ev("user", text="[Image #1]都不要")], titles), set())
        self.assertEqual(answered_tasks(asked + [ev("user", text="【old】Redis")]), {"k"})            # the log's title
        # Said before the question, or the task moved on: not answered.
        self.assertEqual(answered_tasks([asked[0], ev("user", text="【限流】Redis"), asked[1]], titles), set())
        self.assertEqual(answered_tasks(asked + [ev("user", text="【限流】Redis"),
                                                 ev("thread", task="k", status="in_progress")], titles), set())
        # Asked again while blocked (update --status blocked, or new options): unanswered; a plain note is not asking.
        answered = asked + [ev("user", text="【限流】Redis")]
        for again in (ev("thread", task="k", status="blocked", text="status=blocked; 哪个实例？"),
                      ev("thread", task="k", status="blocked", text="哪个实例？", options=["本机", "集群"])):
            self.assertEqual(answered_tasks(answered + [again], titles), set())
            self.assertEqual(answered_tasks(answered + [again, ev("user", text="【限流】集群")], titles), {"k"})
        self.assertEqual(answered_tasks(answered + [ev("thread", task="k", status="blocked", text="已转给 worker")], titles), {"k"})
        # Blocked in the ledger, never in the log (asked before it began): its ledger 【title】 anywhere answers it,
        # whatever its old entries say; nothing else does.
        older = [ev("thread", task="w", title="旧名", status="in_progress"), ev("user", text="好")]
        self.assertEqual(answered_tasks(older, {"w": "窗口"}), set())
        self.assertEqual(answered_tasks(older + [ev("user", text="【窗口】先不做")], {"w": "窗口"}), {"w"})
        self.assertEqual(answered_tasks([ev("user", text="【窗口】先不做")], {"w": "窗口"}), {"w"})
        self.assertEqual(answered_tasks([ev("user", text="【窗口】先不做")]), set())   # not blocked in the ledger
        self.assertEqual(answered_tasks(asked + [ev("user", text="【窗口】x")], {**titles, "w": "窗口"}), {"w"})
        # When the ledger asked (asked_at): words before it answered an older question, not this one; a note in
        # the log after it asks nothing, a new status=blocked does.
        when = {"w": "2026-11-15 10:00"}
        before = ev("user", at="2026-11-15 09:00:00", text="【窗口】先不做")
        after = ev("user", at="2026-11-15 10:05:00", text="【窗口】先不做")
        self.assertEqual(answered_tasks([before], {"w": "窗口"}, when), set())
        self.assertEqual(answered_tasks([before, after], {"w": "窗口"}, when), {"w"})
        noted = ev("thread", task="w", title="窗口", status="blocked", at="2026-11-15 10:10:00", text="等用户回家")
        self.assertEqual(answered_tasks([after, noted], {"w": "窗口"}, when), {"w"})
        again = ev("thread", task="w", title="窗口", status="blocked", at="2026-11-15 10:10:00", text="status=blocked; 还有一件")
        self.assertEqual(answered_tasks([after, again], {"w": "窗口"}, {"w": "2026-11-15 10:10"}), set())
        # Two open questions of one title: the words answer the newest.
        two = asked + [ev("thread", task="j", status="blocked"), ev("user", text="【限流】Redis")]
        self.assertEqual(answered_tasks(two, {"k": "限流", "j": "限流"}), {"j"})


class SeamlessRotation(unittest.TestCase):
    """A rotation the user does not notice: a short handover, the waits started again, the same tab, no greeting."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="pm-seamless-")
        self.tmp = Path(self._tmp.name)
        repo_dir = self.tmp / "proj"
        repo_dir.mkdir()
        self.hc = ManagerFakeHc(app_reply={"terminal": "t50"}, spaces=[], run_addr="t50")
        self.tui = ManagerFakeTui(agents=[])
        self.clock = FakeClock(datetime.datetime.now().replace(microsecond=0))
        self.ctx = make_ctx(
            self.tmp / "home",
            hc=self.hc,
            tui=self.tui,
            git=GitRepo(),
            clock=self.clock,
            out=StdOutput(),
        )
        self.ctx.seat_alive = lambda repo, rec, term=None: seat_mod.seat_alive(repo, rec, term, ctx=self.ctx)
        root = self.ctx.git.project_root(str(repo_dir))
        assert root is not None
        self.repo = root
        self.name = Path(self.repo).name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _set_pane(self, pane: str = "", hc_terminal: str = "") -> None:
        self.ctx.pane = pane
        self.ctx.hc_terminal = hc_terminal or (pane[3:] if pane.startswith("hc:") else "")
        self.ctx.caller = Caller(self.ctx)

    def out(self, fn: Callable[..., Any], *args: Any) -> str:
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            fn(*args, ctx=self.ctx)
        return text.getvalue()

    def task(self, slug: str, status: str, log: int = 1, **fields: Any) -> str:
        task = {"id": f"{self.name}-{slug}", "title": slug, "project": self.name, "repo": self.repo,
                "status": status, "owner": "pm", "base": "main", "created": self.ctx.clock.now(), **fields}
        task["log"] = [{"at": self.ctx.clock.now(), "by": "hc:t9", "text": f"{slug} entry {i} " + "long " * 100}
                       for i in range(log)]
        Ledger(self.ctx).save(task)
        return task["id"]

    def register(self, **labels: Any) -> list[str]:
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.ctx.home.registration(project_slug(self.repo)).write_text(json.dumps(
            {"name": pm_name(self.repo), "project": self.name, "repo": self.repo, "pane": "hc:t7",
             "runtime": "hc", "terminal": "t7", "agent": "claude"}), encoding="utf-8")
        wrapper = ["/bin/zsh", "-lic", '"$@"; exec "$0" -li', "/bin/zsh"]
        claude = ["claude", "--permission-mode", "bypassPermissions", "--", "[from pm.py start] 旧的提示"]
        self.hc.terminals["t7"] = {"state": "live", "argv": wrapper + claude, "foreground": {"argv": claude},
                                   "labels": {"pm": self.name, **labels}, "status": {"state": "working"}}
        self.hc.terminals["t50"] = {"state": "live", "turn": 1, "status": {"state": "working"}}  # the new PM, at work
        return wrapper

    def register_seat(self, agent: str = "claude", agent_pid: int = 4242, **labels: Any) -> list[str]:
        wrapper = self.register(**{"pm.seat": "1", **labels})
        reg_path = self.ctx.home.registration(project_slug(self.repo))
        rec = json.loads(reg_path.read_text(encoding="utf-8"))
        reg_path.write_text(json.dumps({**rec, "seat": True, "agent": agent}), encoding="utf-8")
        write_seat_state(self.repo, {"pid": 1111, "terminal": "t7", "agent_pid": agent_pid, "kind": agent,
                                     "argv": self.hc.terminals["t7"]["foreground"]["argv"],
                                     "started_at": self.ctx.clock.now(), "session_seq": 1}, ctx=self.ctx)
        return wrapper

    def _end_session_spawns(self) -> list[tuple[str, int | None, bool]]:
        out: list[tuple[str, int | None, bool]] = []
        for entry in self.ctx.procs.spawned:
            args = entry["args"]
            if args and args[0] == "end-session":
                term = args[1]
                agent_pid = int(args[args.index("--agent-pid") + 1]) if "--agent-pid" in args else None
                kill_terminal = "--kill-terminal" in args
                out.append((term, agent_pid, kill_terminal))
        return out

    def test_handover_is_short_and_says_where_the_rest_is(self) -> None:
        self.register()
        proj = self.ctx.home.project_for(self.repo)
        proj.root.mkdir(parents=True, exist_ok=True)
        proj.decisions.write_text("".join(f"- 2026-11-{i % 28 + 1:02d} 决定{i} " + "细" * 40
                                          + f" — 用户原话：「原话{i}」\n" for i in range(40)), encoding="utf-8")
        proj.handover.write_text("In flight: " + "a note " * 500, encoding="utf-8")
        for i in range(4):
            self.task(f"open{i}", "in_progress", log=10, pane=f"hc:t{20 + i}", agent=f"w{i}", branch=f"dev/o{i}")
        for i in range(30):
            self.task(f"closed{i}", "merged", retired="2026-11-15")
        conv = Conversation(self.ctx, self.repo)
        for i in range(20):
            conv.record("user", text=f"第{i}句 " + "said " * 100)
            conv.record("pm", text=f"回答{i}\n\n" + "a reply " * 100)
        args = argparse.Namespace(repo=self.repo, turns=6, full=False)
        text = self.out(manager_cmds.cmd_handover, args)
        notes = proj.handover.read_text(encoding="utf-8").strip()
        self.assertIn(notes, text)                                # the notes whole: what is in flight is not cut
        self.assertLessEqual(len(text.encode()) - len(notes.encode()), 16384)
        decisions = text.split("## Decisions")[1].split("\n## ")[0]
        self.assertIn("the latest 15 of 40; `pm.py decisions`", decisions)
        self.assertEqual([line[:5] for line in decisions.splitlines()[1:] if line].count("- 202"), 15)
        self.assertIn("决定39", decisions)
        self.assertNotIn("决定24 ", decisions)
        self.assertNotIn("原话", decisions)                     # the user's words: `pm.py decisions`
        # Latest open-task log keeps up to 600 chars while older entry stays clipped to 100 chars;
        # recent user/PM exchanges keep up to 400 chars each.
        entry9_line = next(l for l in text.splitlines() if "open3 entry 9" in l)
        entry8_line = next(l for l in text.splitlines() if "open3 entry 8" in l)
        self.assertGreater(len(entry9_line.strip()), 500)
        self.assertLessEqual(len(entry9_line.strip()), 630)
        self.assertLessEqual(len(entry8_line.strip()), 130)
        self.assertNotIn("open3 entry 7", text)                   # two entries per open task
        user19_line = next(l for l in text.splitlines() if "第19句" in l)
        pm19_line = next(l for l in text.splitlines() if "回答19" in l)
        self.assertGreater(len(user19_line), 350)
        self.assertGreater(len(pm19_line), 350)
        self.assertIn("Closed in the last 48 h: 30 (", text)
        self.assertNotIn(f"{self.name}-closed1", text)            # a count, not a list
        self.assertEqual(text.count("\n用户: ") + text.count("\nUser: "), 6)
        self.assertNotIn("第13句", text)
        full = self.out(manager_cmds.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=True))
        self.assertIn("— 用户原话：「原话0」", full)
        self.assertIn(f"- [merged] {self.name}-closed1: closed1", full)
        self.assertIn("open3 entry 7", full)
        every = self.out(memory_cmds.cmd_decisions, argparse.Namespace(repo=self.repo, last=0))
        self.assertEqual(len(every.splitlines()), 40)
        self.assertEqual(self.out(memory_cmds.cmd_decisions, argparse.Namespace(repo=self.repo, last=2)).count("— 用户原话"), 2)

    def test_handover_lists_the_waits_to_start_again(self) -> None:
        self.register()
        worker = self.task("worker", "in_progress", pane="hc:t20", agent="w1")
        self.task("own", "in_progress", pane="hc:t7")                          # the PM works on it itself
        self.task("nopane", "in_progress", agent="w2")
        reviewed = self.task("reviewed", "review", pane="hc:t21", agent="w3")  # findings sent, the wait was running
        self.task("ready", "review", pane="hc:t22", agent="w4")                # reported: the PM reviews, no wait
        merged = self.task("merged", "merged", pane="hc:t23", agent="w5")
        self.ctx.home.waits.mkdir(parents=True, exist_ok=True)
        for task_id in (reviewed, merged):  # left behind by waits that ended with the previous session
            (self.ctx.home.waits / f"{task_id}.json").write_text(json.dumps({"task": task_id, "pid": 1}), encoding="utf-8")
        # A desktop-app PM waits on nothing: reports are delivered to whichever session is the PM.
        self.assertNotIn("## Waits to start again", self.out(manager_cmds.cmd_handover, argparse.Namespace(
            repo=self.repo, turns=6, full=False)))
        path = self.ctx.home.registration(project_slug(self.repo))
        path.write_text(json.dumps({k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items()
                                    if k not in ("runtime", "terminal")}), encoding="utf-8")  # the same PM in the herdr TUI
        text = self.out(manager_cmds.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=False))
        waits = text.split("## Waits to start again")[1]
        self.assertIn(f"pm.py is `{self.ctx.procs.pm_command()}`", waits)
        self.assertEqual(sorted(line for line in waits.splitlines() if line.startswith("pm.py wait")),
                         [f"pm.py wait {reviewed} --timeout 3600", f"pm.py wait {worker} --timeout 3600"])
        self.assertIn("## Waits to start again", self.out(manager_cmds.cmd_handover, argparse.Namespace(
            repo=self.repo, turns=6, full=True)))

    def test_a_wait_says_so_while_it_runs_and_not_after(self) -> None:
        task_id = self.task("w", "in_progress", pane="hc:t20", agent="w1")
        seen: list[dict[str, Any]] = []

        def look(a: Any) -> None:
            seen.append(json.loads((self.ctx.home.waits / f"{task_id}.json").read_text(encoding="utf-8")))
            sys.exit(2)

        with mock.patch.object(workers_cmds, 'wait_for_report', look):
            with self.assertRaises(SystemExit):
                workers_cmds.cmd_wait(argparse.Namespace(id=task_id, timeout=1), ctx=self.ctx)
        self.assertEqual((seen[0]["task"], seen[0]["pid"]), (task_id, os.getpid()))
        self.assertFalse((self.ctx.home.waits / f"{task_id}.json").exists())

    def test_what_the_user_said_after_the_last_reply_is_handed_over_whole(self) -> None:
        self.register()
        conv = Conversation(self.ctx, self.repo)
        conv.record("user", text="先做看板")
        conv.record("pm", text="好")
        self.assertEqual(unanswered(conv.events()), [])
        conv.record("user", text="再把连线改成曲线" + "。" * 500)
        conv.record("thread", task="x", text="ledger entry")
        conv.record("user", text="还有颜色")
        self.assertEqual([e["text"][:4] for e in unanswered(conv.events())], ["再把连线", "还有颜色"])
        text = self.out(manager_cmds.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=False))
        self.assertIn("## Not answered yet", text)
        self.assertIn("再把连线改成曲线" + "。" * 500, text)
        self.assertIn("还有颜色", text.split("## Not answered yet")[1])

    def test_cmd_hook_turn_never_emits_rotate_reminder_above_200k(self) -> None:
        self.register()
        self._set_pane("hc:t7", "t7")
        transcript = Path(self.repo) / "big.jsonl"
        transcript.write_text(_row("assistant", [{"type": "text", "text": "x"}], {"input_tokens": 999999}) + "\n",
                              encoding="utf-8")
        for prompt in ("README 写了吗", "[from hc:t3] task x is ready", "<task-notification>x</task-notification>"):
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({
                "hook_event_name": "UserPromptSubmit", "prompt": prompt, "transcript_path": str(transcript),
            }))):
                out = self.out(hooks.cmd_hook_turn, None)
            self.assertEqual(out, "")

    def test_context_reports_auto_compact_target(self) -> None:
        transcript = Path(self.repo) / "cb.jsonl"
        transcript.write_text("\n".join([
            _row("assistant", [{"type": "text", "text": "old"}], {"input_tokens": 195000}),
            json.dumps({"type": "system", "subtype": "compact_boundary", "isSidechain": False,
                        "compactMetadata": {"postTokens": 24000}}),
        ]) + "\n", encoding="utf-8")
        with mock.patch.object(launch_mod, "COMPACT_TOKENS", 200000):
            out = self.out(memory_cmds.cmd_context, argparse.Namespace(transcript=str(transcript)))
        self.assertEqual(out.strip(), "24k context tokens (auto-compact target 200k)")

    def test_hook_pre_compact_emits_checklist_for_claude_and_json_for_codex(self) -> None:
        # 1. --print outputs the checklist unconditionally (used by pi extension).
        printed = self.out(hooks.cmd_hook_pre_compact, argparse.Namespace(print_only=True))
        self.assertIn("Compact Instructions for PM Coordinator:", printed)
        self.assertIn("unrecorded verbal user constraints", printed)
        self.assertIn("rejected technical alternatives", printed)
        self.assertIn("cross-thread conditional promises", printed)

        # 2. Non-PM cwd/pane emits nothing.
        other_dir = self.tmp / "other"
        other_dir.mkdir()
        other = self.ctx.git.project_root(str(other_dir))
        self._set_pane("hc:t999", "t999")
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"cwd": other}))):
            self.assertEqual(self.out(hooks.cmd_hook_pre_compact, argparse.Namespace(print_only=False)), "")

        # 3. Claude PM (no turn_id in stdin JSON) gets plain text instructions.
        self.register()
        self._set_pane("hc:t7", "t7")
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"cwd": self.repo, "trigger": "auto"}))):
            claude_out = self.out(hooks.cmd_hook_pre_compact, argparse.Namespace(print_only=False))
        self.assertIn("Compact Instructions for PM Coordinator:", claude_out)
        self.assertFalse(claude_out.lstrip().startswith("{"))

        # 4. Codex PM (turn_id present) gets valid JSON with systemMessage.
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"cwd": self.repo, "turn_id": "t1"}))):
            codex_out = self.out(hooks.cmd_hook_pre_compact, argparse.Namespace(print_only=False))
        parsed = json.loads(codex_out)
        self.assertTrue(parsed["continue"])
        self.assertIn("Compact Instructions for PM Coordinator:", parsed["systemMessage"])

    def test_hook_session_start_on_compact_emits_live_disk_sync(self) -> None:
        self.register()
        self._set_pane("hc:t7", "t7")
        self.task("open1", "review", log=2, pane="hc:t20", branch="dev/o1")
        self.task("m1", "merged", log=1)  # merged, not retired yet
        with contextlib.redirect_stdout(io.StringIO()):
            memory_cmds.cmd_decide(argparse.Namespace(repo=self.repo, text="全部做好后再装", quote="全部做好后再装", once=True), ctx=self.ctx)
        Conversation(self.ctx, self.repo).record("user", text="合并前看一眼测试")

        saved_cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"source": "startup", "cwd": self.repo}))):
                startup = self.out(hooks.cmd_hook_session_start, argparse.Namespace(compact=False))
            self.assertIn("run `pm.py handover` before anything else", startup)

            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"source": "compact", "cwd": self.repo}))):
                compacted = self.out(hooks.cmd_hook_session_start, argparse.Namespace(compact=False))
            self.assertIn("[pm post-compact live disk sync]", compacted)
            self.assertNotIn("run `pm.py handover` before anything else", compacted)
            self.assertIn(f"{self.name}-open1", compacted)
            self.assertIn(f"Merged, not retired yet (`pm.py retire <id>`): {self.name}-m1", compacted)
            self.assertIn("全部做好后再装", compacted)
            self.assertIn("合并前看一眼测试", compacted)

            with mock.patch.object(sys, "stdin", io.StringIO("{}")):
                flag_out = self.out(hooks.cmd_hook_session_start, argparse.Namespace(compact=True))
            self.assertIn("[pm post-compact live disk sync]", flag_out)
        finally:
            os.chdir(saved_cwd)

        cli_compact = self.out(manager_cmds.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=False, compact=True))
        self.assertIn("[pm post-compact live disk sync]", cli_compact)
        self.assertIn(f"{self.name}-open1", cli_compact)

    def test_swap_is_transparent_and_recovery_start_logs_notice(self) -> None:
        self.register_seat(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        self._set_pane("hc:t7", "t7")
        conv = Conversation(self.ctx, self.repo)
        conv.record("user", text="看看进度")
        self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes="在盯打包", reason="切换模型测试",
                                                             model=None, transcript=""))
        events = conv.events()
        self.assertEqual((events[-1]["type"], events[-1]["notice"], events[-1]["by"]), ("pm", True, "hc:t7"))
        self.assertIn("切换模型测试", events[-1]["text"])
        self.assertIn("from the ledger", events[-1]["text"])
        self.assertFalse((self.ctx.home.project_for(self.repo).root / "takeover.json").exists())
        self.assertFalse(any("pm.quiet" in str(c) for c in self.hc.ops))
        # Turn hook still records normal PM replies afterwards (nothing suppressed).
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({
                "hook_event_name": "Stop", "last_assistant_message": "已切换，继续盯打包。"}))):
            self.out(hooks.cmd_hook_turn, None)
        self.assertEqual(conv.events()[-1]["text"], "已切换，继续盯打包。")

        # Crash-recovery `cmd_start` on an existing project writes a recovery swap notice, whereas `cmd_restore` does not.
        before_count = len(conv.events())
        self.hc.terminals.pop("t7", None)  # no live PM
        self.hc.app_reply = {"terminal": "t51"}
        self.out(manager_cmds.cmd_start, argparse.Namespace(repo=self.repo, kind="claude", model=None, name="", space="new"))
        after_start = conv.events()
        self.assertEqual(len(after_start), before_count + 1)
        self.assertTrue(after_start[-1].get("notice"))
        self.assertIn("session recovery", after_start[-1]["text"])

        self.hc.terminals.pop("t51", None)
        self.ctx.store.change_registration(project_slug(self.repo), lambda cur: {**(cur or {}), "archived": "2026-11-20"})
        before_restore = len(conv.events())
        self.hc.app_reply = {"terminal": "t52"}
        self.out(manager_cmds.cmd_restore, argparse.Namespace(project=self.name, kind="claude", model=None))
        self.assertFalse(any("session recovery" in (e.get("text") or "")
                             for e in conv.events()[before_restore:]))

    def test_rotate_starts_the_successor_in_the_same_tab_and_ends_the_old_one(self) -> None:
        self.register_seat(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        self._set_pane("hc:t7", "t7")
        home_root = str(self.ctx.home.root)
        self.ctx.procs._env = {**self.ctx.procs.env, "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "old", "PM_HOME": home_root}
        env = successor_env(ctx=self.ctx)
        text = self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes="等 worker 汇报", model=None,
                                                                    transcript="/nonexistent"))
        # Successor sessions inside `seat` never inherit the outgoing session's own variables.
        self.assertEqual((env.get("CLAUDECODE"), env.get("CLAUDE_CODE_SESSION_ID"), env.get("PM_HOME")),
                         (None, None, home_root))
        # Seated rotation opens NO second terminal, split pane, pane.swap or terminal.park.
        self.assertFalse([c for c in self.hc.ops if c[:2] in (("hc", "run"), ("herdr-app", "do"))])
        spec = json.loads(self.ctx.home.project_for(self.repo).next_session.read_text(encoding="utf-8"))
        self.assertEqual(spec["argv"][0], "claude")
        self.assertIn("--permission-mode", spec["argv"])
        self.assertNotIn("quiet", spec)
        prompt = spec["argv"][-1]
        self.assertTrue(prompt.startswith("[from pm.py rotate] "))
        self.assertIn("handover", prompt)
        self.assertIn("Start no `wait` or `watch`", prompt)                  # reports are delivered in the app
        self.assertNotIn("in the background", prompt)
        self.assertNotIn("three or four sentences", prompt)
        self.assertEqual(self._end_session_spawns()[-1], ("t7", 4242, False))
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertEqual((rec["terminal"], rec["previous"]["terminal"], rec["rotations"], rec["seat"]),
                         ("t7", "t7", 1, True))
        self.assertFalse((self.ctx.home.project_for(self.repo).root / "takeover.json").exists())
        notice = Conversation(self.ctx, self.repo).events()[-1]
        self.assertEqual((notice["type"], notice["by"], notice["notice"]), ("pm", "hc:t7", True))
        self.assertIn("manual session swap", notice["text"])
        self.assertIn("等 worker 汇报", self.ctx.home.project_for(self.repo).handover.read_text(encoding="utf-8"))
        self.assertIn("same terminal", text)
        self.assertIn("End this turn briefly", text)
        self.assertNotIn("without a word", text)

    def test_unanswered_user_prompt_stays_in_handover_across_swap(self) -> None:
        self.register_seat(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        Conversation(self.ctx, self.repo).record("user", text="连线为什么是直角")
        self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        spec = json.loads(self.ctx.home.project_for(self.repo).next_session.read_text(encoding="utf-8"))
        self.assertNotIn("quiet", spec)
        handover = self.out(manager_cmds.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=False))
        self.assertIn("连线为什么是直角", handover.split("## Not answered yet")[1])

    def test_the_handover_line_in_the_rotate_prompt(self) -> None:
        self.register_seat(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        prompt = json.loads(self.ctx.home.project_for(self.repo).next_session.read_text(encoding="utf-8"))["argv"][-1]
        self.assertIn(f"`{self.ctx.procs.pm_script()} handover`", prompt)    # as before on macOS/Linux
        for path in self.ctx.home.registrations.glob("*.json"):
            path.unlink()
        self.hc.ops.clear()
        self.register_seat(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        with _as_windows(self.ctx):
            self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        prompt = json.loads(self.ctx.home.project_for(self.repo).next_session.read_text(encoding="utf-8"))["argv"][-1]
        spaced_resolved = Path(SPACED).resolve().as_posix() if osutil.WINDOWS else SPACED
        self.assertIn(f'`py -3 "{spaced_resolved}" handover`', prompt)

    def test_a_codex_pm_rotates_in_place_with_compaction_flags(self) -> None:
        wrapper = self.register_seat(agent="codex", **{"herdr.space": "sp1", "herdr.tab": "tb1"})
        codex_argv = ["codex", "-c", "check_for_update_on_startup=false"]
        self.hc.terminals["t7"]["argv"] = wrapper + codex_argv
        self.hc.terminals["t7"]["foreground"] = {"argv": codex_argv}
        write_seat_state(self.repo, {"pid": 1111, "terminal": "t7", "agent_pid": 4242, "kind": "codex",
                                     "argv": codex_argv, "started_at": self.ctx.clock.now(), "session_seq": 1},
                         ctx=self.ctx)
        self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        spec = json.loads(self.ctx.home.project_for(self.repo).next_session.read_text(encoding="utf-8"))
        self.assertEqual(spec["argv"][0], "codex")
        self.assertNotIn("quiet", spec)
        self.assertIn("model_auto_compact_token_limit=220000", spec["argv"])
        self.assertIn("model_post_turn_compact_threshold_percent=80", spec["argv"])
        self.assertTrue(any(str(x).startswith("compact_prompt=") for x in spec["argv"]))
        self.assertTrue(spec["argv"][-1].startswith("[from pm.py rotate] "))
        self.assertEqual(self._end_session_spawns()[-1], ("t7", 4242, False))

    def test_a_new_pm_that_does_not_start_falls_back_in_the_seat_and_keeps_unanswered_words(self) -> None:
        self.register_seat(**{"herdr.space": "sp1", "herdr.tab": "tb1"})
        reg_path = self.ctx.home.registration(project_slug(self.repo))
        rec = json.loads(reg_path.read_text(encoding="utf-8"))
        reg_path.write_text(json.dumps({
            **rec, "agent_session": {"kind": "claude", "id": "prev-sid"},
        }), encoding="utf-8")
        self._set_pane("hc:t7", "t7")
        conv = Conversation(self.ctx, self.repo)
        conv.record("user", text="连线为什么是直角")                 # the prompt the rotation came with
        self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        spec, _ = pop_next_session(self.repo, ctx=self.ctx)
        assert spec is not None
        # Simulate the rotated-in Claude session stuck at a startup dialog until SEAT_START_WAIT expires.
        self.hc.terminals["t7"] = {
            "state": "live", "turn": 0, "status": None,
            "labels": {"pm": self.name, "pm.seat": "1"},
            "screen": "Trust this folder?",
        }

        class HungProc:
            pid = 9999

            def poll(self) -> None:
                return None

        killed: list[int] = []
        with mock.patch.object(seat_mod, "SEAT_START_WAIT", 0), \
                mock.patch.object(osutil, "stop_pid_group", lambda pid: killed.append(pid)):
            ok, why = _wait_seat_session(self.repo, HungProc(), "claude", 0, rotated_in=True, stopping=[False], ctx=self.ctx)
            fallback = build_fallback_spec(self.repo, spec, why, ctx=self.ctx)
        self.assertFalse(ok)
        self.assertEqual(killed, [9999])
        self.assertTrue(fallback["is_fallback"])
        self.assertIn("--resume", fallback["argv"])
        self.assertIn("prev-sid", fallback["argv"])
        told = conv.events()[-1]
        self.assertEqual((told["type"], told["by"], told["notice"]), ("pm", "hc:t7", True))
        self.assertIn("Trust this folder?", told["text"])
        self.assertIn("prev-sid", told["text"])
        rec_after = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec_after is not None
        self.assertEqual(rec_after["agent_session"]["id"], "prev-sid")
        # The notice answers nothing: what the user said is still handed over.
        self.assertEqual([e["text"] for e in unanswered(conv.events())], ["连线为什么是直角"])
        self.assertEqual(conv.tail()[-1], {"user": "连线为什么是直角", "pm": ""})
        handover = self.out(manager_cmds.cmd_handover, argparse.Namespace(repo=self.repo, turns=6, full=False))
        self.assertIn("连线为什么是直角", handover.split("## Not answered yet")[1])

    def test_rotate_migrates_a_legacy_non_seat_pm_into_a_seat_once(self) -> None:
        self.register()  # legacy PM: no `seat: True` and no `pm.seat=1` label
        self._set_pane("hc:t9", "t9")
        text = self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        run = next(c for c in self.hc.ops if c[:2] == ("hc", "run"))
        self.assertIn("--keep", run)
        self.assertIn("pm.seat=1", run)
        _, inner = unwrap_seat_argv(run[run.index("--") + 1:])
        self.assertEqual(inner[0], "claude")
        self.assertIn(("hc", "label", "t50", f"pm={self.name}", "pm.seat=1"), self.hc.ops)
        self.assertIn(("hc", "label", "t7", "pm="), self.hc.ops)
        self.assertFalse([c for c in self.hc.ops if c[:3] == ("herdr-app", "do", "terminal.park")])
        self.assertEqual(self._end_session_spawns()[-1], ("t7", None, True))
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertEqual((rec["terminal"], rec["previous"]["terminal"], rec["seat"]), ("t50", "t7", True))
        self.assertIn("migrated from legacy PM hc:t7", text)
        self.assertNotIn("End this turn", text)  # not run by the old PM

    def test_rotate_in_the_herdr_tui_still_announces_the_takeover(self) -> None:
        self.register()
        reg_path = self.ctx.home.registration(project_slug(self.repo))
        rec = json.loads(reg_path.read_text(encoding="utf-8"))
        reg_path.write_text(json.dumps({**rec, "runtime": "", "pane": "w1:p1"}), encoding="utf-8")
        got: list[str] = []

        def fake_rotate_herdr(a: Any, repo: str, rec_arg: Any, previous: Any, prompt: str, is_self: bool, *, ctx: Any = None) -> list[str]:
            got.append(prompt)
            return []

        with mock.patch.object(rotate_mod, "_rotate_herdr_impl", fake_rotate_herdr):
            self.out(manager_cmds.cmd_rotate, argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""))
        self.assertIn("three or four sentences", got[0])

    def test_end_session_waits_for_the_turn_to_end_then_ends_only_the_outgoing_session(self) -> None:
        self.hc.terminals["t7"] = [
            {"state": "live", "status": {"state": "working"}},
            {"state": "live", "status": {"state": "done"}},
            {"state": "live", "status": {"state": "working"}},
            {"state": "live", "status": {"state": "idle"}},
            {"state": "live", "status": {"state": "idle"}},
        ]
        write_seat_state(self.repo, {"pid": 100, "terminal": "t7", "agent_pid": 555, "kind": "claude"}, ctx=self.ctx)
        stopped: list[int] = []
        with mock.patch.object(osutil, "pid_alive", return_value=True), \
                mock.patch.object(self.ctx.procs, "_background_work", lambda info: []), \
                mock.patch.object(osutil, "stop_pid_group", lambda pid: stopped.append(pid)):
            self.out(manager_cmds.cmd_end_session, argparse.Namespace(
                terminal="t7", repo=self.repo, agent_pid=555, kill_terminal=False, timeout=60,
            ))
        self.assertEqual(stopped, [555])
        self.assertFalse([c for c in self.hc.ops if c[:2] == ("hc", "kill")])  # seat terminal is NEVER hc-killed
        self.assertEqual(len([c for c in self.hc.ops if c[:2] == ("hc", "get")]), 5)
        # If seat has already moved on to another agent_pid, end-session leaves the new session alone.
        stopped.clear()
        write_seat_state(self.repo, {"pid": 100, "terminal": "t7", "agent_pid": 666, "kind": "claude"}, ctx=self.ctx)
        self.hc.terminals["t7"] = {"state": "live", "status": {"state": "idle"}}
        with mock.patch.object(osutil, "pid_alive", return_value=True), \
                mock.patch.object(osutil, "stop_pid_group", lambda pid: stopped.append(pid)):
            self.out(manager_cmds.cmd_end_session, argparse.Namespace(
                terminal="t7", repo=self.repo, agent_pid=555, kill_terminal=False, timeout=60,
            ))
        self.assertEqual(stopped, [])
        # With --kill-terminal (legacy transition), a terminal that is gone or labelled pm= again is left alone.
        for info in ({"state": "finished"}, {"state": "live", "labels": {"pm": "x"}}, None):
            self.hc.ops.clear()
            if info is None:
                self.hc.terminals.pop("t7", None)
            else:
                self.hc.terminals["t7"] = info
            self.out(manager_cmds.cmd_end_session, argparse.Namespace(
                terminal="t7", repo=self.repo, agent_pid=None, kill_terminal=True, timeout=60,
            ))
            self.assertFalse([c for c in self.hc.ops if c[:2] == ("hc", "kill")], info)

    def test_end_session_waits_for_background_work_and_never_cuts_it_off(self) -> None:
        self.register_seat(agent_pid=555)
        self.hc.terminals["t7"] = {"state": "live", "pid": 100, "status": {"state": "idle"}}
        work = iter([["until pm.py land demo-x; do sleep 60; done"]] * 3 + [[], []])
        stopped: list[int] = []
        with mock.patch.object(osutil, "pid_alive", return_value=True), \
                mock.patch.object(self.ctx.procs, "_background_work", lambda info: next(work)), \
                mock.patch.object(osutil, "stop_pid_group", lambda pid: stopped.append(pid)):
            self.out(manager_cmds.cmd_end_session, argparse.Namespace(
                terminal="t7", repo=self.repo, agent_pid=555, kill_terminal=False, timeout=60,
            ))
        self.assertEqual(stopped, [555])  # only once the land was over, two looks in a row
        self.assertEqual(len([c for c in self.hc.ops if c[:2] == ("hc", "get")]), 5)
        # Still busy at the end of the wait in seat mode: cancels next-session.json and records a notice.
        stopped.clear()
        nxt_path = self.ctx.home.project_for(self.repo).next_session
        nxt_path.parent.mkdir(parents=True, exist_ok=True)
        nxt_path.write_text('{"argv": ["claude"]}\n', encoding="utf-8")
        with mock.patch.object(osutil, "pid_alive", return_value=True), \
                mock.patch.object(self.ctx.procs, "_background_work", lambda info: ["until pm.py land demo-x; do sleep 60; done"]):
            self.out(manager_cmds.cmd_end_session, argparse.Namespace(
                terminal="t7", repo=self.repo, agent_pid=555, kill_terminal=False, timeout=60,
            ))
        self.assertEqual(stopped, [])
        self.assertFalse(nxt_path.exists())
        self.assertIn("pm.py land demo-x", Conversation(self.ctx, self.repo).events()[-1]["text"])
        # Legacy --kill-terminal timeout still notifies the new PM via still_running.
        reg_path = self.ctx.home.registration(project_slug(self.repo))
        rec = json.loads(reg_path.read_text(encoding="utf-8"))
        reg_path.write_text(json.dumps(
            {**rec, "pane": "hc:t50", "terminal": "t50", "previous": {"pane": "hc:t7", "terminal": "t7"}}),
            encoding="utf-8")
        self.hc.ops.clear()
        with mock.patch.object(self.ctx.procs, "_background_work", lambda info: ["until pm.py land demo-x; do sleep 60; done"]):
            self.out(manager_cmds.cmd_end_session, argparse.Namespace(
                terminal="t7", repo=self.repo, agent_pid=None, kill_terminal=True, timeout=60,
            ))
        self.assertFalse([c for c in self.hc.ops if c[:2] == ("hc", "kill")])
        sent = [c for c in self.hc.ops if c[:3] == ("hc", "send", "t50")]
        self.assertEqual(len(sent), 1)
        self.assertIn("pm.py land demo-x", sent[0][3])

    def test_background_work_is_read_from_the_shells_under_the_terminal(self) -> None:
        snap = "/bin/zsh -c source /Users/me/.claude/shell-snapshots/snapshot-zsh-1.sh 2>/dev/null || true && eval "
        ps = "\n".join([
            "  100     1 /bin/zsh -lic claude",
            "  101   100 claude --model opus",
            f"  102   101 {snap}'python3 /x/pm.py wait demo-a --timeout 3600' < /dev/null && pwd -P >| /tmp/cwd",
            "  103   102 python3 /x/pm.py wait demo-a --timeout 3600",
            f"  104   101 {snap}'until python3 /x/pm.py land demo-b; do sleep 60; done' < /dev/null && pwd -P >| /tmp/cwd",
            "  105   104 python3 /x/pm.py land demo-b",
            "  106   101 node mcp-server.js",
            f"  200     1 {snap}'git merge other' < /dev/null && pwd -P >| /tmp/cwd"])  # another session's
        run = lambda argv, **kw: type("R", (), {"returncode": 0, "stdout": ps, "stderr": ""})()
        with mock.patch.object(osutil, "WINDOWS", False), mock.patch.object(subprocess, "run", run):
            self.assertEqual(background_work({"pid": 100}), ["until python3 /x/pm.py land demo-b; do sleep 60; done"])
            self.assertEqual(background_work({}), [])

    def test_the_old_program_is_ended_from_a_process_of_its_own(self) -> None:
        real_procs = procs_mod.Processes(self.ctx.home)
        ctx = make_ctx(self.tmp / "home", procs=real_procs, hc=self.hc, git=GitRepo())
        with mock.patch.object(subprocess, "Popen") as popen:
            _end_session_later_impl(self.repo, "t7", agent_pid=4242, kill_terminal=False, ctx=ctx)
        argv, kw = popen.call_args
        self.assertEqual(argv[0][1:], [str(PM_SCRIPT.resolve()), "end-session", "t7", "--repo", self.repo,
                                       "--agent-pid", "4242"])
        if osutil.WINDOWS:
            self.assertTrue(kw["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertTrue(kw["start_new_session"])  # it outlives the session that ran rotate


class PMSeatAndAdopt(unittest.TestCase):
    """Tests for `pm.py seat`, fallback on failed startup, gap keystroke discard, crashed seat liveness, and
    `pm.py adopt <task> [--confirmed]`."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="pm-seat-",
            **({"ignore_cleanup_errors": True} if osutil.WINDOWS else {}),
        )
        self.tmp = Path(self._tmp.name)
        repo_dir = self.tmp / "seattest"
        repo_dir.mkdir()
        self.hc = ManagerFakeHc(run_addr=lambda n: f"t8{n}", name_tab_result=False)
        self.tui = ManagerFakeTui(agents=[])
        self.clock = FakeClock(datetime.datetime.now().replace(microsecond=0))
        self.ctx = make_ctx(
            self.tmp / "home",
            hc=self.hc,
            tui=self.tui,
            git=GitRepo(),
            clock=self.clock,
            out=StdOutput(),
        )
        self.ctx.seat_alive = lambda repo, rec, term=None: seat_mod.seat_alive(repo, rec, term, ctx=self.ctx)
        root = self.ctx.git.project_root(str(repo_dir))
        assert root is not None
        self.repo = root
        self.name = Path(self.repo).name
        self.claude_dir = self.ctx.claude_projects
        self.codex_dir = self.ctx.codex_sessions
        self.claude_dir.mkdir(parents=True, exist_ok=True)
        self.codex_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _set_pane(self, pane: str = "", hc_terminal: str = "") -> None:
        self.ctx.pane = pane
        self.ctx.hc_terminal = hc_terminal or (pane[3:] if pane.startswith("hc:") else "")
        self.ctx.caller = Caller(self.ctx)

    def test_seat_runs_sessions_sequentially_strips_session_env_and_blocks_second_seat(self) -> None:
        log_file = Path(self.repo) / "runs.jsonl"
        helper = Path(self.repo) / "fake_session.py"
        helper.write_text(
            "import json, os, sys, time\n"
            "tag = sys.argv[1]\n"
            "with open(sys.argv[2], 'a') as f:\n"
            "    pgrp = os.getpgrp() if hasattr(os, 'getpgrp') else os.getpid()\n"
            "    f.write(json.dumps({'tag': tag, 'pid': os.getpid(), 'pgrp': pgrp,\n"
            "                        'claudecode': os.environ.get('CLAUDECODE'),\n"
            "                        'pm_home': os.environ.get('PM_HOME')}) + '\\n')\n"
            "if tag == 's1':\n"
            "    nxt = sys.argv[3]\n"
            "    with open(nxt, 'w') as nf:\n"
            "        json.dump({'argv': [sys.executable, __file__, 's2', sys.argv[2]], 'kind': 'claude'}, nf)\n",
            encoding="utf-8",
        )
        proj = self.ctx.home.project_for(self.repo)
        proj.root.mkdir(parents=True, exist_ok=True)
        nxt_path = proj.next_session
        ledger_home = str(self.ctx.home.root)
        env = _clean_child_env(self.ctx.home.root, CLAUDECODE="1", CLAUDE_CODE_SESSION_ID="leak-me")
        res = subprocess.run(
            [sys.executable, str(PM_SCRIPT), "seat", "--repo", self.repo, "--no-shell", "--",
             sys.executable, str(helper), "s1", str(log_file), str(nxt_path)],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        runs = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["tag"] for r in runs], ["s1", "s2"])
        self.assertEqual(runs[0]["claudecode"], None)
        self.assertEqual(runs[1]["claudecode"], None)
        self.assertEqual(runs[0]["pm_home"], ledger_home)
        self.assertEqual(runs[0]["pid"], runs[0]["pgrp"])  # each session runs in its own process group
        self.assertEqual(runs[1]["pid"], runs[1]["pgrp"])
        self.assertFalse(proj.seat_state.exists())
        self.assertFalse(seat_running(self.repo, ctx=self.ctx))

        # While one seat holds seat.lock, a second seat for the same project is refused immediately.
        blocker = Path(self.repo) / "hold.py"
        ready_flag = Path(self.repo) / "ready"
        blocker.write_text(
            f"import pathlib, time; pathlib.Path({str(ready_flag)!r}).write_text('1'); time.sleep(30)\n",
            encoding="utf-8",
        )
        first = subprocess.Popen(
            [sys.executable, str(PM_SCRIPT), "seat", "--repo", self.repo, "--no-shell", "--",
             sys.executable, str(blocker)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                if ready_flag.exists() and seat_running(self.repo, ctx=self.ctx):
                    break
                time.sleep(0.05)
            self.assertTrue(seat_running(self.repo, ctx=self.ctx))
            second = subprocess.run(
                [sys.executable, str(PM_SCRIPT), "seat", "--repo", self.repo, "--no-shell", "--",
                 sys.executable, "-c", "pass"],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("already running", second.stderr)
        finally:
            first.terminate()
            first.wait(timeout=10)
        self.assertFalse(seat_running(self.repo, ctx=self.ctx))

    def test_sighup_or_sigterm_stops_seat_without_triggering_fallback(self) -> None:
        ready_flag = Path(self.repo) / "ready2"
        sleeper = Path(self.repo) / "sleeper.py"
        sleeper.write_text(
            f"import pathlib, time; pathlib.Path({str(ready_flag)!r}).write_text('1'); time.sleep(30)\n",
            encoding="utf-8",
        )
        env = _clean_child_env(self.ctx.home.root)
        popen_kw: dict[str, object] = {}
        if osutil.WINDOWS:
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            [sys.executable, str(PM_SCRIPT), "seat", "--repo", self.repo, "--no-shell", "--",
             sys.executable, str(sleeper)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **popen_kw,
        )
        for _ in range(100):
            if ready_flag.exists():
                break
            time.sleep(0.05)
        proj = self.ctx.home.project_for(self.repo)
        proj.root.mkdir(parents=True, exist_ok=True)
        proj.next_session.write_text('{"argv": ["false"], "kind": "claude"}\n', encoding="utf-8")
        if osutil.WINDOWS:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        proc.wait(timeout=10)
        self.assertEqual(Conversation(self.ctx, self.repo).events(), [])  # no fallback notice recorded when terminal closes
        self.assertFalse(proj.next_session.exists())
        self.assertFalse(proj.seat_state.exists())

    @unittest.skipIf(osutil.WINDOWS or seat_mod.termios is None, "POSIX PTY input flush test")
    def test_tty_reset_discards_keystrokes_typed_during_rotation_gap(self) -> None:
        import pty
        master, slave = pty.openpty()
        os.set_blocking(master, False)
        os.set_blocking(slave, False)
        try:
            saved = seat_mod.termios.tcgetattr(slave)
            os.write(master, b"half-typed draft during gap\n")
            time.sleep(0.02)
            # Drain echo on master before resetting, then verify slave has queued input before TCIFLUSH and none after.
            with contextlib.suppress(BlockingIOError):
                os.read(master, 4096)
            _reset_seat_tty(slave, saved, flush_input=True)
            with contextlib.suppress(BlockingIOError):
                os.read(master, 4096)
            with self.assertRaises(BlockingIOError):
                os.read(slave, 64)
        finally:
            os.close(master)
            os.close(slave)

    def test_seat_fallback_for_codex_resumes_and_for_agy_restarts_from_handover_once(self) -> None:
        slug = project_slug(self.repo)
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        reg_path = self.ctx.home.registration(slug)
        # 1. Codex PM transcript discovered on disk -> resumed with `codex resume <id>` + wakeup prompt.
        rollout = self.codex_dir / "2026" / "rollout-1.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text(
            json.dumps({"payload": {"id": "codex-pm-99", "cwd": str(Path(self.repo).resolve())}}) + "\n"
            + json.dumps({"type": "user", "message": {"content": "[from pm.py start] run handover"}}) + "\n",
            encoding="utf-8",
        )
        reg_path.write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo,
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "seat": True, "agent": "codex",
        }), encoding="utf-8")
        fb_codex = build_fallback_spec(self.repo, {"kind": "codex", "previous": {"agent": "codex"}}, "exited 1", ctx=self.ctx)
        self.assertEqual(fb_codex["argv"][:2], ["codex", "resume"])
        self.assertEqual(fb_codex["argv"][-1], "codex-pm-99")
        self.assertIn("codex-pm-99", fb_codex["prompt"])
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertEqual(rec["agent_session"], {"kind": "codex", "id": "codex-pm-99", "path": str(rollout)})

        # 2. agy PM (no resumable session, prompt_arg=False) -> fresh handover fallback + single-fallback cap.
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({
            "agents": {"agy": {"argv": ["agy", "chat"], "model": ["--model", "{}"]}}
        }), encoding="utf-8")
        reg_path.write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo,
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "seat": True, "agent": "agy",
        }), encoding="utf-8")
        fb_agy = build_fallback_spec(self.repo, {"kind": "agy", "previous": {"agent": "agy"}}, "exited 2", ctx=self.ctx)
        self.assertTrue(fb_agy["is_fallback"])
        self.assertEqual(fb_agy["argv"], ["agy", "chat"])
        self.assertIn("handover", fb_agy["prompt"])  # sent via _seat_prompt_sender since prompt_arg is False
        rec2 = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec2 is not None
        self.assertIsNone(rec2["agent_session"])
        self.assertTrue(Conversation(self.ctx, self.repo).events()[-1]["notice"])

        # Subprocess verification: rotated-in session fails -> fallback runs once and fails -> seat exits (no loop).
        runs_log = Path(self.repo) / "fb_runs.txt"
        runner = Path(self.repo) / "fb_runner.py"
        runner.write_text(
            "import json, sys\n"
            "mode = sys.argv[1]\n"
            f"open({str(runs_log)!r}, 'a').write(mode + '\\n')\n"
            "if mode == 's1':\n"
            "    with open(sys.argv[2], 'w') as f:\n"
            "        json.dump({'argv': [sys.executable, __file__, 'bad'], 'kind': 'agy',\n"
            "                   'previous': {'agent': 'agy'}}, f)\n"
            "    sys.exit(0)\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        self.ctx.home.config.write_text(json.dumps({
            "agents": {"agy": {"argv": [sys.executable, str(runner), "fallback"], "prompt_arg": False}}
        }), encoding="utf-8")
        proj = self.ctx.home.project_for(self.repo)
        proj.root.mkdir(parents=True, exist_ok=True)
        nxt = proj.next_session
        env = _clean_child_env(self.ctx.home.root)
        res = subprocess.run(
            [sys.executable, str(PM_SCRIPT), "seat", "--repo", self.repo, "--no-shell", "--",
             sys.executable, str(runner), "s1", str(nxt)],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(res.returncode, 1)
        self.assertEqual(runs_log.read_text(encoding="utf-8").splitlines(), ["s1", "bad", "fallback"])  # capped at 1 fallback!

    def test_claim_shell_revival_dead_seat_liveness_monotonic_turn_and_retired_hook_guard(self) -> None:
        slug = project_slug(self.repo)
        # 1. `claim --pane hc:t5` on an idle shell launches `exec ... pm.py seat ...` inside t5.
        self.hc.terminals["t5"] = {"state": "live", "argv": ["/bin/zsh", "-li"], "foreground": {"argv": ["-zsh"]}, "labels": {}}
        self._set_pane("hc:other", "other")
        with contextlib.redirect_stdout(io.StringIO()):
            manager_cmds.cmd_claim(argparse.Namespace(repo=self.repo, pane="hc:t5", kind="claude",
                                                      discord_channel=None, discord_users=None), ctx=self.ctx)
        rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec is not None
        self.assertTrue(rec["seat"])
        self.assertIn(("hc", "keep", "t5"), self.hc.ops)
        sent_cmds = [c[3] for c in self.hc.ops if c[:3] == ("hc", "send", "t5")]
        self.assertEqual(len(sent_cmds), 1)
        self.assertTrue(sent_cmds[0].startswith("exec ") and " seat " in sent_cmds[0])

        # 2. Dead seat (e.g. crashed or dropped to zsh): hc_pm returns None so deliver never types into zsh,
        # and `cmd_start` revives `pm.py seat` in place inside t5!
        self.hc.terminals["t5"] = {"state": "live", "argv": ["/bin/zsh", "-li"], "foreground": {"argv": ["-zsh"]},
                                   "labels": {"pm": self.name, "pm.seat": "1"},
                                   "status": {"app": "claude-code", "state": "idle"}, "seat_dead": True}
        self.assertIsNone(ProjectRegistry(self.ctx).hc_pm(self.repo))
        self.hc.ops.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            revived = manager_cmds.cmd_start(argparse.Namespace(repo=self.repo, kind="claude", model=None,
                                                                name="", space="new"), ctx=self.ctx)
        self.assertEqual(revived, "t5")  # reused the fixed seat terminal instead of opening a second space!
        self.assertTrue(any(c[:3] == ("hc", "send", "t5") and c[3].startswith("exec ") for c in self.hc.ops))

        # 3. Async Stop hook from rotated-out session in `retired_sessions` cannot overwrite `agent_session`.
        self.ctx.store.change_registration(slug, lambda cur: {**(cur or {}), "retired_sessions": ["old-sid"], "agent_session": None})
        remember_pm_session_for(self.ctx, ProjectRegistry(self.ctx).pm_record(self.repo), session_id="old-sid")
        rec_mid = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec_mid is not None
        self.assertIsNone(rec_mid["agent_session"])
        remember_pm_session_for(self.ctx, ProjectRegistry(self.ctx).pm_record(self.repo), session_id="new-sid")
        rec_end = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec_end is not None
        self.assertEqual(rec_end["agent_session"]["id"], "new-sid")

    def test_adopt_resumes_claude_and_codex_and_asks_via_question_card_before_fresh_agy(self) -> None:
        slug = project_slug(self.repo)
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.ctx.home.registration(slug).write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo,
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "seat": True, "agent": "claude",
        }), encoding="utf-8")
        self.hc.terminals["t7"] = {"state": "live", "labels": {"pm": self.name, "pm.seat": "1"}, "cwd": self.repo}
        wt = (self.tmp / "adoptwt").resolve()
        wt.mkdir()
        brief_path = Path(self.repo) / "brief.md"
        brief_path.write_text("Implement seat adopt.\n", encoding="utf-8")

        def run_adopt(candidate: str, confirmed: bool = False) -> str:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                memory_cmds.cmd_adopt(argparse.Namespace(
                    candidate=candidate, confirmed=confirmed, repo=self.repo,
                    drop=False, text=None, name=None, type=None, quote=None, verified=None,
                ), ctx=self.ctx)
            return out.getvalue()

        # 1. Idle Claude orphan -> resumed directly under PM seat (`--parent t7 --outlive-parent --no-notify`).
        t_claude = f"{self.name}-c1"
        folder = self.claude_dir / claude_folder(wt)
        folder.mkdir(parents=True)
        (folder / "sid-c1.jsonl").write_text(
            json.dumps({"cwd": str(wt), "type": "user", "message": {"content": f"pm.py update {t_claude}"}}) + "\n",
            encoding="utf-8",
        )
        Ledger(self.ctx).save({"id": t_claude, "title": "Claude orphan", "project": self.name, "repo": self.repo,
                               "worktree": str(wt), "brief": str(brief_path), "status": "review", "owner": "pm",
                               "base": "main", "pane": "hc:t20", "worker_pane": "hc:t20", "agent": "w-c1",
                               "dispatched": True, "worker": {"kind": "claude", "model": "opus"},
                               "session": {"kind": "claude", "id": "sid-c1"}, "created": self.ctx.clock.now()})
        self.hc.terminals["t20"] = {"state": "live", "parent": "t_old_pm", "cwd": str(wt),
                                    "labels": {"task": t_claude}, "status": {"state": "idle"}}
        self.hc.terminals["t81"] = {"state": "live", "parent": "t7", "cwd": str(wt),
                                    "labels": {"task": t_claude}, "status": {"state": "idle"}}
        out_claude = run_adopt(t_claude, confirmed=False)
        self.assertIn("resume claude pane=hc:t81 parent=hc:t7 session=sid-c1", out_claude)
        self.assertIn(("hc", "kill", "t20"), self.hc.ops)
        self.assertIn(("hc", "rm", "t20"), self.hc.ops)
        run_call = next(c for c in self.hc.ops if c[:2] == ("hc", "run"))
        self.assertIn("--parent", run_call)
        parent_idx = run_call.index("--parent")
        self.assertEqual(list(run_call[parent_idx:parent_idx + 3]), ["--parent", "t7", "--outlive-parent"])
        self.assertIn("--resume", run_call)
        self.assertIn("sid-c1", run_call)
        self.assertEqual(Ledger(self.ctx).load(t_claude).raw["pane"], "hc:t81")
        self.assertEqual(Ledger(self.ctx).load(t_claude).raw["status"], "review")

        # Already under PM seat -> idempotent no-op, nothing killed.
        self.hc.ops.clear()
        nop = run_adopt(t_claude, confirmed=False)
        self.assertIn("already under", nop)
        self.assertFalse([c for c in self.hc.ops if c[:2] in (("hc", "kill"), ("hc", "run"))])

        # Worker whose parent is another LIVE terminal (e.g. helper under t20, or live parent) -> refused!
        t_not_orphan = f"{self.name}-notorphan"
        self.hc.terminals["t_live_parent"] = {"state": "live"}
        Ledger(self.ctx).save({"id": t_not_orphan, "title": "Not orphan", "project": self.name, "repo": self.repo,
                               "worktree": str(wt), "status": "in_progress", "owner": "pm", "base": "main",
                               "pane": "hc:t23", "worker": {"kind": "claude"}, "created": self.ctx.clock.now()})
        self.hc.terminals["t23"] = {"state": "live", "parent": "t_live_parent", "status": {"state": "idle"}}
        self.hc.ops.clear()
        with self.assertRaises(SystemExit) as not_orphan_err:
            run_adopt(t_not_orphan, confirmed=False)
        self.assertIn("not an orphan", str(not_orphan_err.exception.code))
        self.assertFalse([c for c in self.hc.ops if c[:2] in (("hc", "kill"), ("hc", "run"))])

        # Busy worker -> refused cleanly without killing.
        t_busy = f"{self.name}-busy"
        Ledger(self.ctx).save({"id": t_busy, "title": "Busy", "project": self.name, "repo": self.repo,
                               "worktree": str(wt), "status": "in_progress", "owner": "pm", "base": "main",
                               "pane": "hc:t21", "worker": {"kind": "claude"}, "created": self.ctx.clock.now()})
        self.hc.terminals["t21"] = {"state": "live", "parent": "t_old", "status": {"state": "working"}}
        with self.assertRaises(SystemExit):
            run_adopt(t_busy, confirmed=False)
        self.assertFalse([c for c in self.hc.ops if c[:3] == ("hc", "kill", "t21")])

        # 2. Idle `agy` orphan (no resumable session) -> blocks with question card first, keeps t22 alive;
        # then with `--confirmed`, ends t22, starts fresh `agy` under t7, and restores `paused` status!
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({
            "agents": {"agy": {"argv": ["agy"], "model": ["--model", "{}"]}}
        }), encoding="utf-8")
        t_agy = f"{self.name}-agy1"
        Ledger(self.ctx).save({"id": t_agy, "title": "Agy orphan", "project": self.name, "repo": self.repo,
                               "worktree": str(wt), "brief": str(brief_path), "status": "paused", "owner": "pm",
                               "base": "main", "pane": "hc:t22", "worker_pane": "hc:t22", "agent": "w-agy",
                               "dispatched": True, "worker": {"kind": "agy", "model": "gemini-4-neon-high"},
                               "created": self.ctx.clock.now()})
        self.hc.terminals["t22"] = {"state": "live", "parent": "", "cwd": str(wt),
                                    "labels": {"task": t_agy}, "status": {"state": "idle"}}
        self.hc.ops.clear()
        ask_out = run_adopt(t_agy, confirmed=False)
        self.assertIn("blocked with a question card", ask_out)
        self.assertFalse([c for c in self.hc.ops if c[:2] in (("hc", "kill"), ("hc", "run"))])  # orphan NOT killed before user agrees!
        asked_task = Ledger(self.ctx).load(t_agy).raw
        self.assertEqual(asked_task["status"], "blocked")
        self.assertEqual(len(asked_task["options"]), 2)
        self.assertEqual(asked_task["adopting"], {"from": "paused", "pane": "hc:t22", "kind": "agy"})
        self.assertEqual(Conversation(self.ctx, self.repo).events()[-1]["options"], asked_task["options"])

        # Now user agrees -> `--confirmed` ends t22, attaches under t7, and restores `paused`!
        self.hc._run_count = 0  # next run returns t81
        self.hc.terminals["t81"] = {"state": "live", "parent": "t7", "cwd": str(wt),
                                    "labels": {"task": t_agy}, "status": {"state": "idle"}}
        conf_out = run_adopt(t_agy, confirmed=True)
        self.assertIn("fresh agy pane=hc:t81 parent=hc:t7", conf_out)
        self.assertIn(("hc", "kill", "t22"), self.hc.ops)
        done_task = Ledger(self.ctx).load(t_agy).raw
        self.assertEqual((done_task["pane"], done_task["status"]), ("hc:t81", "paused"))
        self.assertNotIn("options", done_task)
        self.assertNotIn("adopting", done_task)

    def test_pm_parked_tasks_follow_pm_when_terminal_changes_and_stay_online_in_seat(self) -> None:
        slug = project_slug(self.repo)
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        self.ctx.home.registration(slug).write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo,
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "agent": "claude",
            "previous": {"pane": "hc:t3", "terminal": "t3"},
        }), encoding="utf-8")
        self.hc.terminals["t7"] = {"state": "live", "argv": ["claude"], "foreground": {"argv": ["claude"]},
                                   "labels": {"pm": self.name}}
        self.hc.terminals["t81"] = {"state": "live", "labels": {"pm": self.name, "pm.seat": "1"}, "cwd": self.repo}
        self.hc.terminals["t20"] = {"state": "live", "labels": {"task": f"{self.name}-worker"}}

        def mk(suffix: str, status: str, pane: str = "hc:t7", **extra: Any) -> str:
            tid = f"{self.name}-{suffix}"
            Ledger(self.ctx).save({"id": tid, "title": suffix, "project": self.name, "repo": self.repo,
                                   "status": status, "owner": "pm", "base": "main", "pane": pane,
                                   "created": self.ctx.clock.now(), **extra})
            return tid

        epic = mk("epic", "in_progress")
        prop = mk("prop", "proposed")
        card = mk("card", "blocked", options=["A", "B"])
        older = mk("older", "in_progress", pane="hc:t3")  # left over from an earlier rotation
        worker = mk("worker", "in_progress", pane="hc:t20", worker_pane="hc:t20", dispatched=True)
        closed = mk("done", "done", pane="hc:t7")

        # 1. Legacy/crash-recovery rotate replaces terminal t7 -> t81: all open PM-parked tasks move to hc:t81!
        with contextlib.redirect_stdout(io.StringIO()):
            manager_cmds.cmd_rotate(argparse.Namespace(repo=self.repo, notes=None, model=None, transcript=""), ctx=self.ctx)
        self.hc.terminals["t7"] = {"state": "finished"}  # old PM terminal is now gone
        for tid in (epic, prop, card, older):
            self.assertEqual(Ledger(self.ctx).load(tid).raw["pane"], "hc:t81", tid)
            self.assertFalse(task_offline(Ledger(self.ctx).load(tid).raw, {"t81", "t20"}, None), tid)
        self.assertEqual(Ledger(self.ctx).load(worker).raw["pane"], "hc:t20")  # real worker untouched
        self.assertEqual(Ledger(self.ctx).load(closed).raw["pane"], "hc:t7")   # closed task untouched

        # 2. If the seat crashes and `pm.py start` opens a brand-new seat terminal t82, PM-parked tasks move to hc:t82!
        self.hc.terminals["t81"] = {"state": "finished"}
        self.hc.terminals["t82"] = {"state": "live", "labels": {"pm": self.name, "pm.seat": "1"}, "cwd": self.repo}
        with contextlib.redirect_stdout(io.StringIO()):
            made = manager_cmds.cmd_start(argparse.Namespace(repo=self.repo, kind="claude", model=None,
                                                             name="", space="current"), ctx=self.ctx)
        self.assertEqual(made, "t82")
        for tid in (epic, prop, card, older):
            self.assertEqual(Ledger(self.ctx).load(tid).raw["pane"], "hc:t82", tid)
            self.assertFalse(task_offline(Ledger(self.ctx).load(tid).raw, {"t82", "t20"}, None), tid)

    def test_expired_next_session_falls_back_instead_of_dropping_to_shell_and_timeout_restores_session(self) -> None:
        # 1. SEAT_NEXT_MAX_AGE is aligned with RETIRE_WAIT, and an expired next-session.json triggers fallback
        #    (resuming the previous session or restarting from handover) instead of dropping out to a shell!
        self.assertEqual(SEAT_NEXT_MAX_AGE, RETIRE_WAIT)
        runs_log = Path(self.repo) / "exp_runs.txt"
        runner = Path(self.repo) / "exp_runner.py"
        runner.write_text(
            "import json, os, sys, time\n"
            "mode = sys.argv[1]\n"
            f"open({str(runs_log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "if mode == 's1':\n"
            "    nxt = sys.argv[2]\n"
            "    with open(nxt, 'w') as f:\n"
            "        json.dump({'argv': ['claude', '--', 'new'], 'kind': 'claude', 'created_ts': 1,\n"
            "                   'previous': {'agent': 'claude', 'agent_session': {'kind': 'claude', 'id': 'sid-prev'}}}, f)\n"
            "    os.utime(nxt, (1, 1))\n",
            encoding="utf-8",
        )
        slug = project_slug(self.repo)
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        reg_path = self.ctx.home.registration(slug)
        reg_path.write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo,
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "seat": True, "agent": "claude",
            "agent_session": None, "retired_sessions": ["sid-prev"],
        }), encoding="utf-8")
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({
            "pm": {"lean": False, "narrow_tools": False},
            "agents": {"claude": {"argv": [sys.executable, str(runner), "resumed"], "prompt_arg": True}},
        }), encoding="utf-8")
        proj = self.ctx.home.project_for(self.repo)
        proj.root.mkdir(parents=True, exist_ok=True)
        nxt = proj.next_session
        env = _clean_child_env(self.ctx.home.root)
        res = subprocess.run(
            [sys.executable, str(PM_SCRIPT), "seat", "--repo", self.repo, "--no-shell", "--",
             sys.executable, str(runner), "s1", str(nxt)],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = runs_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("s1 "))
        self.assertIn("resumed --model opus --resume sid-prev --", lines[1])
        rec1 = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec1 is not None
        self.assertEqual(rec1["agent_session"], {"kind": "claude", "id": "sid-prev"})
        self.assertNotIn("retired_sessions", rec1)
        self.assertTrue(Conversation(self.ctx, self.repo).events()[-1]["notice"])

        # 2. When `end-session` times out and cancels a rotation, `agent_session` is restored and `retired_sessions`
        #    no longer blocks `remember_pm_session` from tracking the staying session!
        self.ctx.home.config.unlink(missing_ok=True)
        self.hc.terminals["t7"] = {"state": "live", "turn": 3, "labels": {"pm": self.name, "pm.seat": "1"},
                                   "foreground": {"argv": ["claude"]}, "status": {"state": "working"}}
        write_seat_state(self.repo, {"pid": 100, "terminal": "t7", "agent_pid": 777, "kind": "claude",
                                     "argv": ["claude"]}, ctx=self.ctx)
        reg_path.write_text(json.dumps({
            "name": pm_name(self.repo), "project": self.name, "repo": self.repo,
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "seat": True, "agent": "claude",
            "agent_session": {"kind": "claude", "id": "sid-stay"},
        }), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            manager_cmds.cmd_rotate(argparse.Namespace(repo=self.repo, notes="busy", model=None, transcript=""), ctx=self.ctx)
        mid_rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert mid_rec is not None
        self.assertIsNone(mid_rec["agent_session"])
        self.assertIn("sid-stay", mid_rec.get("retired_sessions") or [])

        self.hc.terminals["t7"]["pid"] = 100
        with mock.patch.object(osutil, 'pid_alive', return_value=True), \
                mock.patch.object(self.ctx.procs, '_background_work', lambda info: ['pm.py land x']):
            manager_cmds.cmd_end_session(argparse.Namespace(terminal="t7", repo=self.repo, agent_pid=777,
                                                            kill_terminal=False, timeout=60), ctx=self.ctx)
        after_rec = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert after_rec is not None
        self.assertEqual(after_rec["agent_session"], {"kind": "claude", "id": "sid-stay"})
        self.assertNotIn("retired_sessions", after_rec)
        self.assertFalse(proj.next_session.exists())
        # Subsequent hooks for `sid-stay` (with transcript path) still update `agent_session` cleanly!
        transcript = self.claude_dir / claude_folder(self.repo) / "sid-stay.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}\n", encoding="utf-8")
        remember_pm_session_for(self.ctx, after_rec, transcript=str(transcript), session_id="sid-stay")
        rec_final = ProjectRegistry(self.ctx).pm_record(self.repo)
        assert rec_final is not None
        self.assertEqual(rec_final["agent_session"]["path"], str(transcript))

    @unittest.skipIf(osutil.WINDOWS or seat_mod.termios is None, "POSIX PTY lifecycle test")
    def test_seat_real_pty_hands_foreground_pgrp_to_children_and_execs_shell_on_exit(self) -> None:
        import fcntl
        import pty

        log_file = Path(self.repo) / "pty_seat_runs.jsonl"
        fake_shell = Path(self.repo) / "fake_login_shell.py"
        fake_shell.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            f"with open({str(log_file)!r}, 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps({'tag': 'shell', 'pid': os.getpid(), 'pgrp': os.getpgrp(),\n"
            "                        'fg_pgrp': os.tcgetpgrp(0), 'argv': sys.argv[1:]}) + '\\n')\n",
            encoding="utf-8",
        )
        fake_shell.chmod(0o755)
        session_probe = Path(self.repo) / "pty_session_probe.py"
        session_probe.write_text(
            "import json, os, sys\n"
            "tag = sys.argv[1]\n"
            f"with open({str(log_file)!r}, 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps({'tag': tag, 'pid': os.getpid(), 'pgrp': os.getpgrp(),\n"
            "                        'fg_pgrp': os.tcgetpgrp(0), 'isatty': sys.stdin.isatty()}) + '\\n')\n"
            "if tag == 's1':\n"
            "    with open(sys.argv[2], 'w', encoding='utf-8') as nf:\n"
            "        json.dump({'argv': [sys.executable, __file__, 's2'], 'kind': 'claude'}, nf)\n",
            encoding="utf-8",
        )
        proj = self.ctx.home.project_for(self.repo)
        proj.root.mkdir(parents=True, exist_ok=True)
        env = _clean_child_env(self.ctx.home.root, SHELL=str(fake_shell))
        master, slave = pty.openpty()
        try:
            def _attach_ctty() -> None:
                os.setsid()
                fcntl.ioctl(0, seat_mod.termios.TIOCSCTTY, 0)

            proc = subprocess.Popen(
                [sys.executable, str(PM_SCRIPT), "seat", "--repo", self.repo, "--",
                 sys.executable, str(session_probe), "s1", str(proj.next_session)],
                stdin=slave, stdout=slave, stderr=slave, env=env, preexec_fn=_attach_ctty,
            )
            os.close(slave)
            slave = -1
            os.set_blocking(master, False)
            deadline = time.monotonic() + 15.0
            while proc.poll() is None and time.monotonic() < deadline:
                with contextlib.suppress(BlockingIOError, OSError):
                    os.read(master, 4096)
                time.sleep(0.02)
            self.assertEqual(proc.wait(timeout=5), 0)
        finally:
            if slave >= 0:
                os.close(slave)
            os.close(master)

        runs = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["tag"] for r in runs], ["s1", "s2", "shell"])
        self.assertTrue(runs[0]["isatty"] and runs[1]["isatty"])
        self.assertEqual(runs[0]["pid"], runs[0]["pgrp"])
        self.assertEqual(runs[0]["fg_pgrp"], runs[0]["pgrp"])
        self.assertNotEqual(runs[0]["pid"], proc.pid)
        self.assertEqual(runs[1]["pid"], runs[1]["pgrp"])
        self.assertEqual(runs[1]["fg_pgrp"], runs[1]["pgrp"])
        # On final session exit without --no-shell, cmd_seat reclaims the PTY and execvp's $SHELL -li in-place.
        self.assertEqual(runs[2]["pid"], proc.pid)
        self.assertEqual(runs[2]["fg_pgrp"], proc.pid)
        self.assertEqual(runs[2]["argv"], ["-li"])
        self.assertFalse(proj.seat_state.exists())
        self.assertFalse(seat_running(self.repo, ctx=self.ctx))

    @unittest.skipIf(osutil.WINDOWS or seat_mod.termios is None, "POSIX PTY claim execvp test")
    def test_claim_in_pane_real_pty_execs_seat_in_place(self) -> None:
        import fcntl
        import pty

        probe_out = Path(self.repo) / "claim_pty_probe.json"
        fake_hc = Path(self.repo) / "fake_hc.py"
        fake_hc.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "args = sys.argv[1:]\n"
            "if '--json' in args:\n"
            "    args = [a for a in args if a != '--json']\n"
            "cmd = args[0] if args else ''\n"
            "if cmd == 'get':\n"
            f"    done = {str(probe_out)!r}\n"
            "    import pathlib\n"
            "    if pathlib.Path(done).exists():\n"
            "        print(json.dumps({'state': 'finished', 'id': 't5', 'address': 't5'}))\n"
            "    else:\n"
            "        print(json.dumps({'state': 'live', 'id': 't5', 'address': 't5',\n"
            "                          'argv': ['/bin/zsh', '-li'], 'foreground': {'argv': ['-zsh']}, 'labels': {}}))\n"
            "elif cmd == 'ls':\n"
            "    print('[]')\n"
            "elif cmd in ('keep', 'label'):\n"
            "    print(json.dumps({'ok': True}))\n"
            "elif cmd == 'events':\n"
            "    print(json.dumps({'terminals': []}), flush=True)\n"
            "else:\n"
            "    print('{}')\n",
            encoding="utf-8",
        )
        fake_hc.chmod(0o755)
        agent_probe = Path(self.repo) / "fake_claude_pm.py"
        seat_state_path = self.ctx.home.project_for(self.repo).seat_state
        agent_probe.write_text(
            "import json, os, pathlib, sys\n"
            f"st = json.loads(pathlib.Path({str(seat_state_path)!r}).read_text(encoding='utf-8'))\n"
            f"pathlib.Path({str(probe_out)!r}).write_text(\n"
            "    json.dumps({'agent_pid': os.getpid(), 'ppid': os.getppid(), 'seat_pid': st['pid'], 'argv': sys.argv[1:]}),\n"
            "    encoding='utf-8',\n"
            ")\n",
            encoding="utf-8",
        )
        noop_shell = Path(self.repo) / "noop_shell.py"
        noop_shell.write_text(f"#!{sys.executable}\nimport sys; sys.exit(0)\n", encoding="utf-8")
        noop_shell.chmod(0o755)
        self.ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.home.config.write_text(json.dumps({
            "hc": str(fake_hc),
            "agents": {"claude": {"argv": [sys.executable, str(agent_probe)]}},
        }), encoding="utf-8")

        env = _clean_child_env(self.ctx.home.root, HC_TERMINAL_ID="t5", SHELL=str(noop_shell))
        master, slave = pty.openpty()
        try:
            def _attach_ctty() -> None:
                os.setsid()
                fcntl.ioctl(0, seat_mod.termios.TIOCSCTTY, 0)

            proc = subprocess.Popen(
                [sys.executable, str(PM_SCRIPT), "claim", "--repo", self.repo, "--kind", "claude"],
                stdin=slave, stdout=slave, stderr=slave, env=env, preexec_fn=_attach_ctty,
            )
            os.close(slave)
            slave = -1
            os.set_blocking(master, False)
            deadline = time.monotonic() + 15.0
            while proc.poll() is None and time.monotonic() < deadline:
                with contextlib.suppress(BlockingIOError, OSError):
                    os.read(master, 4096)
                time.sleep(0.02)
            self.assertEqual(proc.wait(timeout=5), 0)
        finally:
            if slave >= 0:
                os.close(slave)
            os.close(master)
            # Removing home.root wakes any detached deliverer immediately so it exits without waiting DELIVER_GONE.
            shutil.rmtree(self.ctx.home.root, ignore_errors=True)

        data = json.loads(probe_out.read_text(encoding="utf-8"))
        # `cmd_claim` execvp'd `pm.py seat` in-place, so seat's PID equals the original `claim` subprocess PID!
        self.assertEqual(data["seat_pid"], proc.pid)
        self.assertEqual(data["ppid"], proc.pid)

    def test_cmd_claim_flushes_stdout_before_execvp(self) -> None:
        from pmlib.terminals import hc as hc_mod

        class _BufferedTty(io.TextIOWrapper):
            def isatty(self) -> bool:
                return True

        raw = io.BytesIO()
        buffered_tty = _BufferedTty(io.BufferedWriter(raw, buffer_size=8192), encoding="utf-8", line_buffering=False)
        real_hc = hc_mod.HcHost(self.ctx.config, clock=self.clock)
        c = make_ctx(
            self.tmp / "flush-home",
            pane="hc:t5",
            hc_terminal="t5",
            hc=real_hc,
            git=GitRepo(),
            clock=self.clock,
            out=StdOutput(stdout=buffered_tty),
        )

        def fake_hc_run(argv: Any, **kw: Any) -> Any:
            if "get" in argv:
                payload: Any = {"state": "live", "id": "t5", "address": "t5", "argv": ["/bin/zsh"],
                                "foreground": {"argv": ["-zsh"]}, "labels": {}}
            elif "label" in argv:
                payload = {"ok": True}
            else:
                payload = []
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

        flushed_at_exec: list[bytes] = []

        def fake_execvp(file: str, args: list[str]) -> None:
            flushed_at_exec.append(raw.getvalue())
            raise SystemExit(0)

        tty_stdin = mock.MagicMock()
        tty_stdin.isatty.return_value = True
        with mock.patch.object(subprocess, "run", side_effect=fake_hc_run), \
                mock.patch.object(sys, "stdin", tty_stdin), \
                mock.patch.object(sys, "stdout", buffered_tty), \
                mock.patch.object(os, "execvp", side_effect=fake_execvp):
            with self.assertRaises(SystemExit):
                manager_cmds.cmd_claim(argparse.Namespace(
                    repo=self.repo, pane=None, kind="claude", discord_channel=None, discord_users=None,
                ), ctx=c)
        self.assertEqual(len(flushed_at_exec), 1)
        self.assertIn(b"hc:t5 is now", flushed_at_exec[0])

    @unittest.skipIf(osutil.WINDOWS or seat_mod.termios is None, "POSIX PTY shell fallback test")
    def test_cmd_seat_falls_back_when_shell_env_points_to_missing_binary(self) -> None:
        import pty

        master, slave = pty.openpty()
        tried: list[str] = []

        def fake_execvp(file: str, args: list[str]) -> None:
            tried.append(file)
            if file == "/nonexistent/broken-shell":
                raise FileNotFoundError(file)
            raise SystemExit(0)

        try:
            tty_in = open(slave, "rb", closefd=False)
            tty_out = open(slave, "wb", closefd=False)
            try:
                c = make_ctx(
                    self.tmp / "shell-fb-home",
                    git=GitRepo(),
                    clock=self.clock,
                    env={"SHELL": "/nonexistent/broken-shell"},
                )
                with mock.patch.dict(os.environ, {"SHELL": "/nonexistent/broken-shell"}, clear=False), \
                        mock.patch.object(sys, "stdin", tty_in), \
                        mock.patch.object(sys, "stdout", tty_out), \
                        mock.patch.object(os, "execvp", side_effect=fake_execvp):
                    with self.assertRaises(SystemExit):
                        manager_cmds.cmd_seat(argparse.Namespace(
                            repo=self.repo, argv=[sys.executable, "-c", "pass"],
                            kind="claude", prompt="", no_shell=False,
                        ), ctx=c)
            finally:
                tty_in.close()
                tty_out.close()
        finally:
            os.close(slave)
            os.close(master)
        self.assertGreaterEqual(len(tried), 2, f"expected fallback shell after broken SHELL, got {tried}")

    def test_pm_compact_tokens_reads_ctx_env_for_claude_and_codex(self) -> None:
        c = make_ctx(self.tmp / "compact-env-home", git=GitRepo(), env={"PM_COMPACT_TOKENS": "160000"})
        self.assertEqual(launch_mod.pm_compact_tokens("claude", ctx=c), 160000)
        self.assertEqual(launch_mod.pm_compact_tokens("codex", ctx=c), 160000)


if __name__ == "__main__":
    unittest.main()
