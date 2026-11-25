"""Reproduction and regression tests from Pass-2 Final Review (lane r4).

All production issues originally captured in `evidence/pm-py-pass2/final-review-r4.md` are now fixed and verified here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
for p in (SCRIPTS, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fakes import FakeClock, FakeHc, make_ctx, run_main  # noqa: E402
from pmlib import cli  # noqa: E402
from pmlib.commands import (  # noqa: E402
    dispatch as dispatch_cmd,
    emit as emit_cmd,
    events as events_cmd,
    helpers as helpers_cmd,
    ledger as ledger_cmd,
    memory as memory_cmd,
    project as project_cmd,
    workers as workers_cmd,
)
from pmlib.context import BufferOutput  # noqa: E402
from pmlib.errors import IdentityError, PmError, StoreError  # noqa: E402
from pmlib.helpers.service import Helpers  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.memory.layer import MemoryLayer  # noqa: E402
from pmlib.store import DamagedFileError, FileStore  # noqa: E402
from pmlib.terminals.hc import TerminalInfo  # noqa: E402
from pmlib.views import status as status_view  # noqa: E402


class FakeHcLsShapeTest(unittest.TestCase):
    """`FakeHc._ls_raw` matches real `hc ls --json` (`status` is a string, whereas `hc get` wraps `{"state": ...}`)."""

    def test_fake_hc_ls_emits_string_status_for_helpers_ls_and_cmd_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = (base / "repo").resolve()
            repo.mkdir()
            slug = project_slug(str(repo))
            hc = FakeHc(terminals={
                "t1": {"state": "live", "status": {"state": "idle"}, "labels": {"task": "repo-1"}},
                "th": {"state": "live", "status": {"state": "idle"}, "labels": {"helper.of": f"pm-{slug}", "helper": "probe"}},
            })
            ctx = make_ctx(base / "home", hc=hc)
            # `hc get` retains dict status; `hc ls` flattens status to string.
            self.assertEqual(hc.get_raw("t1")["status"], {"state": "idle"})
            self.assertEqual(hc.live_rows()["t1"].raw["status"], "idle")

            ctx.store.change_registration(slug, lambda _: {
                "name": f"pm-{slug}", "project": repo.name, "repo": str(repo),
                "pane": "hc:t9", "runtime": "hc", "terminal": "t9",
                "helpers": [{
                    "name": "probe", "terminal": "th", "owner": f"pm-{slug}", "owner_kind": "pm",
                    "project": slug, "mode": "readonly", "cwd": str(repo), "status": "running",
                    "started": "2026-11-22 12:00:00", "started_ts": ctx.clock.time(), "timeout": 600,
                }],
            })
            Ledger(ctx).save({
                "id": "repo-1", "title": "Reported Worker", "project": repo.name, "repo": str(repo),
                "status": "review", "owner": "pm", "base": "main", "pane": "hc:t1", "worker_pane": "hc:t1",
                "dispatched": True, "created": ctx.clock.now(),
            })

            ls_res = Helpers(ctx).ls(show_all=True, repo=str(repo))
            self.assertEqual(ls_res.entries[0]["live_state"], "idle")
            self.assertIn("[running (idle)]", "\n".join(ls_res.lines))

            status_view.cmd_status(argparse.Namespace(repo=str(repo), all=False, closed=False), ctx=ctx)
            self.assertIn("worker terminal still open", ctx.out.stdout)
            self.assertIn("repo-1  hc:t1", ctx.out.stdout)


class FinalReviewR4ReprosTest(unittest.TestCase):
    """Regression tests for confirmed production issues from r4 final review."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = (self.base / "repo").resolve()
        self.repo.mkdir()

    def test_cli_deliver_holds_do_not_crash_deliverer_look_with_type_error(self) -> None:
        """P0: `procs.py:322` wires `ctx.deliver_holds = (lambda repo: seat_mod.next_session_ready(repo, ctx=ctx),)`,
        but `manager/seat.py:169` defines `def next_session_ready(repo)` without `ctx`, crashing every real
        `pm.py deliver <project>` on the first pending event with `TypeError`."""
        from pmlib.context import Context
        from pmlib.events.deliverer import Deliverer
        from pmlib.project.conversation import Conversation
        from pmlib.terminals.hc import HcHost

        home = self.base / "dlv-home"
        ctx = Context.from_env(home_option=home, env={"PM_HOME": str(home)})
        ctx.hc = HcHost(runner=lambda *a, **kw: (
            {"state": "live", "labels": {"pm": self.repo.name}, "status": {"state": "idle"}}
            if a[:2] == ("get", "t7") else {"started": True}
        ))
        slug = project_slug(str(self.repo))
        ctx.store.change_registration(slug, lambda _: {
            "name": f"pm-{slug}", "project": self.repo.name, "repo": str(self.repo),
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7", "agent": "claude",
        })
        dlv = Deliverer(ctx, str(self.repo), settle=0)
        dlv.start_mark({"pane": "hc:t7", "runtime": "hc", "terminal": "t7"})
        Conversation(ctx, str(self.repo)).record("event", by="ci", text="build broke", source="external:ci", wake=True)

        class _Looks:
            terminals = None

        dlv.look(_Looks(), {})

    def test_corrupt_task_commands_emit_ledger_store_error_prefix(self) -> None:
        """P1: `StoreError` subclasses `PmError`, so command/view `except PmError:` handlers swallow it before
        `cli.main()` can emit `ledger store error: ...`."""
        home = self.base / "home"
        tasks = home / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "bad-1.json").write_text("{corrupt json", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HC_", "HERDR_", "PM_"))}
        env["PM_HOME"] = str(home)
        for subcmd in (["show", "bad-1"], ["update", "bad-1", "--note", "x"], ["log", "bad-1", "x"], ["retire", "bad-1"]):
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "pm.py"), *subcmd],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 1, subcmd)
            self.assertIn("ledger store error:", proc.stderr, (subcmd, proc.stderr))

    def test_context_from_env_wires_hooks_without_importing_cli_first(self) -> None:
        """P2: `procs.build_env_context` uses `sys.modules.get(...)` instead of importing hook modules, leaving
        `caller`, `after_save`, `seat_alive`, `deliver_watchers`, `deliver_holds`, and `candidate_pruner` unwired
        when `pmlib.cli` has not been imported yet."""
        code = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from pmlib.context import Context\n"
            "ctx = Context.from_env(home_option=sys.argv[2], env={'PM_HOME': sys.argv[2]})\n"
            "assert ctx.caller is not None, 'caller is None'\n"
            "assert len(ctx.after_save) == 2, ctx.after_save\n"
            "assert ctx.seat_alive is not None, 'seat_alive is None'\n"
            "assert [w.name for w in ctx.deliver_watchers] == ['helpers', 'dependencies', 'agy-transcript', 'dream'], ctx.deliver_watchers\n"
            "assert len(ctx.deliver_holds) == 1, ctx.deliver_holds\n"
            "assert ctx.candidate_pruner is not None, 'candidate_pruner is None'\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code, str(SCRIPTS), str(self.base / "env-home")],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_cmd_new_and_cmd_show_respect_ctx_config_lang(self) -> None:
        """P3a: `commands/ledger.py:117` (`format_dep_summary` missing `tr_fn=tr`), `ledger/deps.py` (`parse_depends_on`),
        and `ledger/family.py` (`format_children_summary`) call global `config.tr()` instead of `ctx.config.tr`."""
        en_env_home = self.base / "en-env-home"
        en_env_home.mkdir()
        (en_env_home / "config.json").write_text(json.dumps({"lang": "en"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"PM_HOME": str(en_env_home)}):
            ctx_zh = make_ctx(self.base / "zh-ctx-home", env={"PM_HOME": str(self.base / "zh-ctx-home")})
            ctx_zh.home.config.parent.mkdir(parents=True, exist_ok=True)
            ctx_zh.home.config.write_text(json.dumps({"lang": "zh"}), encoding="utf-8")

            t_a = ledger_cmd.cmd_new(argparse.Namespace(
                repo=str(self.repo), title="前置任务", status="merged", owner="pm", base="main",
                workspace=None, pane=None, agent=None, branch=None, worktree=None, brief=None,
                slug="dep-a", note=None, parent=None, depends_on=None, kind=None,
            ), ctx=ctx_zh)
            ctx_zh.out.clear()
            ledger_cmd.cmd_new(argparse.Namespace(
                repo=str(self.repo), title="子任务", status="proposed", owner="pm", base="main",
                workspace=None, pane=None, agent=None, branch=None, worktree=None, brief=None,
                slug="child-b", note=None, parent=t_a, depends_on=[t_a], kind=None,
            ), ctx=ctx_zh)
            self.assertIn("前置已满足：", ctx_zh.out.stderr)
            self.assertNotIn("all deps met:", ctx_zh.out.stderr)

            ctx_zh.out.clear()
            status_view.cmd_show(argparse.Namespace(id=t_a, json=False), ctx=ctx_zh)
            self.assertIn("子任务=0/1", ctx_zh.out.stdout)
            self.assertNotIn("subtasks=", ctx_zh.out.stdout)

    def test_cmd_recall_search_uses_ctx_clock_and_lang_for_index_line(self) -> None:
        """P3b: `commands/memory.py:69` calls module-level `index_line(m)` (`Context.from_env()`) instead of
        `MemoryLayer(ctx, layer).index_line(m)`, ignoring `ctx.clock` and `ctx.config`."""
        en_env_home = self.base / "en-env-home"
        en_env_home.mkdir()
        (en_env_home / "config.json").write_text(json.dumps({"lang": "en"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"PM_HOME": str(en_env_home)}):
            clock = FakeClock("2026-01-01 10:00")
            ctx = make_ctx(self.base / "mem-home", clock=clock)
            ctx.home.config.parent.mkdir(parents=True, exist_ok=True)
            ctx.home.config.write_text(json.dumps({"lang": "zh"}), encoding="utf-8")
            MemoryLayer(ctx, self.repo).remember(
                "临时冻结发版窗口",
                writer=("user", "user"),
                kind="project",
                name="freeze-window",
                quote="这周先冻结发版",
                project_repo=str(self.repo),
            )
            clock.set("2099-01-02 10:00")
            memory_cmd.cmd_recall(
                argparse.Namespace(repo=str(self.repo), name=None, search="冻结", type=None, topic=None, personal=False),
                ctx=ctx,
            )
            self.assertIn("原话未对上", ctx.out.stdout)
            self.assertIn("天未确认", ctx.out.stdout)

    def test_events_commands_write_to_ctx_out(self) -> None:
        """P4a: `commands/events.py` uses bare `print(...)` instead of `ctx.out`."""
        ctx = make_ctx(self.base / "ev-home", out=BufferOutput())
        slug = project_slug(str(self.repo))
        ctx.store.change_registration(slug, lambda _: {
            "name": f"pm-{slug}", "project": self.repo.name, "repo": str(self.repo),
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7",
        })
        events_cmd.cmd_event(
            argparse.Namespace(repo=str(self.repo), source="ci", text="green", key="k1"),
            ctx=ctx,
        )
        self.assertIn("recorded;", ctx.out.stdout)

    def test_cli_main_errors_write_to_ctx_out(self) -> None:
        """P4b: `cli.main(..., ctx=ctx)` writes `IdentityError`/`StoreError`/`PmError` to `sys.stdout`/`sys.stderr`
        instead of `ctx.out`."""
        ctx = make_ctx(self.base / "cli-home", pane="", out=BufferOutput())
        with self.assertRaises(SystemExit) as cm:
            cli.main(["guard", "--action", "coordinate", "--repo", str(self.repo)], ctx=ctx)
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("PM identity check failed:", ctx.out.stderr)

    def test_cmd_home_migrate_uses_ctx_env_instead_of_host_os_environ(self) -> None:
        """P5: `commands/project.py:130` checks `os.environ.get('PM_HOME')` even when explicit `ctx` has no `PM_HOME`,
        and line 140 uses `Path.home()` instead of `ctx.env`."""
        fake_user = self.base / "fake-user"
        (fake_user / ".dudu" / "tasks").mkdir(parents=True)
        ctx = make_ctx(fake_user / ".dudu", env={"HOME": str(fake_user), "USERPROFILE": str(fake_user)}, out=BufferOutput())
        ctx.env = {"HOME": str(fake_user), "USERPROFILE": str(fake_user)}
        with mock.patch.dict(os.environ, {"PM_HOME": str(self.base / "host-leak")}):
            project_cmd.cmd_home(
                argparse.Namespace(migrate=True, dry_run=True, json=True, backup_dir=None),
                ctx=ctx,
            )
        payload = json.loads(ctx.out.stdout)
        self.assertTrue(payload["ok"], payload)

    def test_terminal_info_from_hc_ls_string_status_populates_agent_state(self) -> None:
        """P6: Real `hc ls --json` emits `status` as a string (e.g. `'idle'`), and `TerminalInfo.from_dict`
        populates `agent_state` and `has_status` for both string and Mapping `status`."""
        info = TerminalInfo.from_dict({"address": "t1", "state": "live", "status": "idle"})
        self.assertEqual(info.agent_state, "idle")
        self.assertTrue(info.has_status)


class LaneDFixesTest(unittest.TestCase):
    """Regression tests for lane D fixes (P1 code preservation, P3a cmd_new, P7, P8, P9)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = (self.base / "repo").resolve()
        self.repo.mkdir()

    def test_error_emitters_reraise_store_and_identity_and_preserve_code(self) -> None:
        ctx = make_ctx(self.base / "emit-home", out=BufferOutput())
        for emitter in (emit_cmd.exit_with, workers_cmd._emit_pm_error, helpers_cmd._emit_helper_error):
            with self.assertRaises(StoreError):
                emitter(ctx, DamagedFileError("bad json"))
            with self.assertRaises(IdentityError):
                emitter(ctx, IdentityError("bad seat"))
            ctx.out.clear()
            with self.assertRaises(SystemExit) as cm:
                emitter(ctx, PmError("custom fail", code=7))
            self.assertEqual(cm.exception.code, 7)
            self.assertIn("custom fail", ctx.out.stderr)

    def test_cmd_new_dep_summary_uses_ctx_config_lang(self) -> None:
        en_env_home = self.base / "en-env-home"
        en_env_home.mkdir()
        (en_env_home / "config.json").write_text(json.dumps({"lang": "en"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"PM_HOME": str(en_env_home)}):
            ctx_zh = make_ctx(self.base / "zh-home", env={"PM_HOME": str(self.base / "zh-home")})
            ctx_zh.home.config.parent.mkdir(parents=True, exist_ok=True)
            ctx_zh.home.config.write_text(json.dumps({"lang": "zh"}), encoding="utf-8")
            t_a = ledger_cmd.cmd_new(argparse.Namespace(
                repo=str(self.repo), title="前置", status="merged", owner="pm", base="main",
                workspace=None, pane=None, agent=None, branch=None, worktree=None, brief=None,
                slug="dep-a", note=None, parent=None, depends_on=None, kind=None,
            ), ctx=ctx_zh)
            ctx_zh.out.clear()
            ledger_cmd.cmd_new(argparse.Namespace(
                repo=str(self.repo), title="子任务", status="proposed", owner="pm", base="main",
                workspace=None, pane=None, agent=None, branch=None, worktree=None, brief=None,
                slug="child-b", note=None, parent=t_a, depends_on=[t_a], kind=None,
            ), ctx=ctx_zh)
            self.assertIn("前置已满足：", ctx_zh.out.stderr)
            self.assertNotIn("all deps met:", ctx_zh.out.stderr)

    def test_cmd_dispatch_forwards_ctx_to_wrapped_dispatch_hc(self) -> None:
        ctx = make_ctx(self.base / "disp-home", pane="hc:t1", out=BufferOutput())
        brief = self.base / "brief.md"
        brief.write_text("do work\n", encoding="utf-8")
        seen_ctx: list[object] = []

        def fake_hc(a, repo, b, held=None, *, ctx=None):
            seen_ctx.append(ctx)

        with mock.patch.object(dispatch_cmd, "dispatch_hc", fake_hc):
            dispatch_cmd.cmd_dispatch(argparse.Namespace(
                title="Test", repo=str(self.repo), branch=None, label=None, path=None,
                brief=str(brief), name=None, task=None, here=True, tab=None, bug="",
                codex_profile=None, dry_run=False, base="main", prep=None, parent=None,
                profile="light", kind="codex", model=None, effort=None, advisor=None,
                confirmed=False, plan=None, step=None, outer_plan=None, subplan=None,
                no_review=False, async_=False,
            ), ctx=ctx)
        self.assertEqual(seen_ctx, [ctx])

    def test_cmd_project_lets_damaged_file_bubble_and_catches_not_found(self) -> None:
        ctx = make_ctx(self.base / "proj-home", out=BufferOutput())
        slug = project_slug(str(self.repo))
        ctx.store.change_registration(slug, lambda _: {
            "name": f"pm-{slug}", "project": self.repo.name, "repo": str(self.repo),
            "pane": "hc:t7", "runtime": "hc", "terminal": "t7",
        })
        docs = ctx.home.root / "projects" / slug / "docs"
        docs.mkdir(parents=True)
        (docs / "bad-utf8.md").write_bytes(b"\xff\xfe\x00invalid")

        code, _out, err = run_main(ctx, "project", "file", "--root", "docs", "--", slug, "bad-utf8.md")
        self.assertEqual(code, 1)
        self.assertIn("ledger store error:", err)

        with self.assertRaises(SystemExit):
            project_cmd.cmd_project(
                argparse.Namespace(project_cmd="log", id="no-such-task", before=None, limit=50),
                ctx=ctx,
            )

    def test_file_store_optional_clock_used_for_backfill_and_history(self) -> None:
        clock = FakeClock("2099-05-06 07:08")
        root = self.base / "clock-store"
        store = FileStore(root, clock=clock)
        slug = project_slug(str(self.repo))
        store.change_task(
            f"{slug}-1",
            lambda _: {"id": f"{slug}-1", "project": self.repo.name, "repo": str(self.repo), "status": "in_progress"},
        )
        store.backfill_task_numbers(slug)
        seq = json.loads((root / "projects" / slug / "task-seq.json").read_text(encoding="utf-8"))
        self.assertEqual(seq["backfilled_at"], "2099-05-06 07:08")

        store.save_doc(slug, "notes.md", b"v1")
        store.save_doc(slug, "notes.md", b"v2")
        hist = store.doc_history(slug, "notes.md")
        self.assertEqual(len(hist), 1)
        self.assertTrue(hist[0]["version"].startswith("20990506-0708"), hist[0])


if __name__ == "__main__":
    unittest.main()
