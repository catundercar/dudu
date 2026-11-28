"""Agent launch arguments, the codex profile pool, Codex /fast and readiness, and agent sessions (transcripts,
context tokens, `project session`, hook-recorded sessions).

Moved from test_pm.py `LaunchArgs`, `Pool`, `Fast` and the whole of test_pm_sessions.py (Stage 6a). Every test
runs on its own `make_ctx` Context: config.json is written into its own temporary ledger, herdr-core is a
`FakeHc`, herdr a `FakeTui`. Commands still reach their services through `legacy_context()`, which
`tests.legacy_bind.bound` points at the test's Context for the call.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
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
    os.environ["PM_HOME"] = str(Path(tempfile.gettempdir()) / "pm-home-for-test-agents-profiles")
    try:
        import pmlib.context  # noqa: F401, E402
    finally:
        if _saved_pm_home is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved_pm_home

import pmlib.cli  # noqa: F401, E402 - wires every pmlib module, as the command line does
from pmlib import hooks, osutil  # noqa: E402
import pmlib.agents.transcripts as pm_sessions  # noqa: E402 - what pm_sessions.py re-exports
from pmlib.agents.base import strip_codex_args  # noqa: E402
from pmlib.agents.codex_pool import codex_profile_of  # noqa: E402
from pmlib.agents.sessions import PM_SESSION_MARK  # noqa: E402
from pmlib.commands import manager as manager_cmds, review as review_cmds  # noqa: E402
from pmlib.commands import workers as workers_cmds  # noqa: E402
from pmlib.context import StdOutput  # noqa: E402
from pmlib.errors import Refused  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.manager import launch as launch_mod  # noqa: E402
from pmlib.manager.launch import claude_compact_settings, codex_pm_compact  # noqa: E402
from pmlib.manager.rotate import build_fallback_spec  # noqa: E402
from pmlib.project.project import pm_name  # noqa: E402
from pmlib.terminals.hc import HcHost  # noqa: E402
from pmlib.views import project as project_view, state as state_view  # noqa: E402
from pmlib.workers import codex_pool as codex_pool_mod  # noqa: E402
from pmlib.workers.service import Workers  # noqa: E402
from pmlib.workers.sessions import session_places_for  # noqa: E402
from tests.fakes import FakeClock, FakeHc, FakeTui, StubGit, make_ctx  # noqa: E402

SCRIPTS_DIR = SCRIPTS

POLICY = {
    "codex": {"projects": ["proj"],
              "profiles": [{"name": "team-a", "max": 2, "fast": True}, {"name": "team-b", "max": 3, "fast": True}],
              "allow_default": False, "model": "codex-model", "review_model": "review-model", "effort": "high",
              "fallback": {"worker": {"kind": "claude", "model": "opus", "effort": "high"},
                           "reviewer": {"kind": "claude", "model": "fable", "effort": "high"}}},
    "claude": {"launcher": ["zsh", "-ic", "my-claude --yes {args}"], "effort": "high", "fable_fallback": "opus"},
    "tabs": {"max": 20, "review": "审查", "bug_pattern": r"(?<![0-9])#?([0-9]{5})(?![0-9])"},
}


def ns(**kw):
    base = dict(kind="codex", model="", effort="", advisor="", fallback="", profile="", codex_profile=None)
    return argparse.Namespace(**{**base, **kw})


class ScreenHc(FakeHc):
    """FakeHc whose `hc read` of a terminal shows the next of the screens given for it (the last one stays)."""

    def __init__(self, *args, screens=None, **kw):
        super().__init__(*args, **kw)
        self.screens = {k: list(v) for k, v in (screens or {}).items()}

    def read(self, term, *, lines=None):
        shown = self.screens.get(term)
        if shown:
            return shown.pop(0) if len(shown) > 1 else shown[0]
        return super().read(term, lines=lines)


class Policy(unittest.TestCase):
    """config.json for one test, in that test's own ledger home."""
    CONFIG = POLICY

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.clock = FakeClock()
        self.hc = FakeHc(clock=self.clock)
        self.git = StubGit(roots={str(Path("/w/proj").resolve()): "/w/proj"}, worktree_base=self.base / "worktrees")
        self.ctx = make_ctx(self.base, hc=self.hc, git=self.git, clock=self.clock, out=StdOutput(),
                            config=self.CONFIG)

    def config(self, value):
        self.ctx.home.config.write_text(json.dumps(value))

    def live(self, sessions):
        """The codex sessions running in the project, as /proc would show them (None: nothing can be counted)."""
        found = None if sessions is None else [{"pid": i, "profile": p, "cwd": "/x"} for i, p in enumerate(sessions)]
        return mock.patch.object(codex_pool_mod, "_live_codex_impl", lambda ctx, repo: found)


class LaunchArgs(Policy):
    def test_strip_codex_args(self):
        args = ["--no-daemon", "-c", 'model_provider="acct"', "-c", 'service_tier="priority"', "-c", "x=1"]
        self.assertEqual(strip_codex_args(args), ["--no-daemon", "-c", "x=1"])

    def test_profile_of(self):
        self.assertEqual(codex_profile_of(["codex", "-p", "team-b", "-m", "x"]), "team-b")
        self.assertEqual(codex_profile_of(["codex", "--profile=team-a"]), "team-a")
        self.assertEqual(codex_profile_of(["codex", "-c", 'model_provider="team-a"']), "team-a")
        self.assertEqual(codex_profile_of(["codex", "-m", "gpt"]), "default")

    def test_launch_wrap(self):
        out = self.ctx.agents.launch_wrap("claude", ["claude", "--model", "opus", "--settings", "/a b/c.json"])
        quoted = osutil.shell_quote("/a b/c.json")
        self.assertEqual(out, ["zsh", "-ic", f"my-claude --yes --model opus --settings {quoted}"])
        self.assertEqual(self.ctx.agents.launch_wrap("codex", ["codex", "-p", "team-b"]),
                         ["codex", "-p", "team-b"])  # none set
        self.config({"codex": {"launcher": ["wrap", "--"]}})
        self.assertEqual(self.ctx.agents.launch_wrap("codex", ["codex", "-m", "x"]),
                         ["wrap", "--", "-m", "x"])  # no {args}: appended

    def test_no_launcher_by_default(self):
        self.config({})
        self.assertEqual(self.ctx.agents.launch_wrap("claude", ["claude", "--model", "opus"]),
                         ["claude", "--model", "opus"])

    def test_claude_effort_and_fable_fallback(self):
        a, _ = Workers(self.ctx).apply_codex_pool(ns(kind="claude", model="fable"), "/w/proj", hold=False)
        self.assertEqual(a.effort, "high")  # claude.effort where nothing else named one
        agents = self.ctx.agents
        self.assertEqual((agents.fable_fallback("claude", "fable", "worker"),
                          agents.fable_fallback("claude", "fable", "reviewer")), ("opus", "opus"))
        self.config({})
        self.assertEqual(agents.fable_fallback("claude", "fable", "reviewer"), "sonnet")  # built in

    def test_hc_path_from_config(self):
        host = HcHost(self.ctx.config)
        self.config({"hc": "/opt/hc/bin/hc"})
        self.assertEqual(host.bin(), "/opt/hc/bin/hc")
        self.config({})
        self.assertEqual(host.bin(), "hc")


class Pool(Policy):
    def run_pool(self, sessions, role="worker", **kw):
        """The pool's pick for a new worker; `warning` is what the command would print on stderr."""
        with self.live(sessions):
            a, self.warning = Workers(self.ctx).apply_codex_pool(ns(**kw), "/w/proj", role, hold=False)
        return a

    def test_first_free_in_order(self):
        a = self.run_pool(["team-b"])
        self.assertEqual((a.kind, a.provider, a.model, a.effort), ("codex", "team-a", "codex-model", "high"))
        self.assertIn("team-a 0/2", a.pool_said)

    def test_a_full_profile_goes_to_the_next(self):
        self.assertEqual(self.run_pool(["team-a", "team-a", "team-b"]).provider, "team-b")

    def test_all_full_falls_back_to_claude(self):
        a = self.run_pool(["team-a"] * 2 + ["team-b"] * 3)
        self.assertEqual((a.kind, a.model, a.effort, a.provider), ("claude", "opus", "high", ""))
        self.assertIn("opus", a.pool_said)

    def test_reviewer_fallback_is_fable_with_its_fallback(self):
        a = self.run_pool(["team-a"] * 2 + ["team-b"] * 3, role="reviewer")
        self.assertEqual((a.model, a.fallback), ("fable", "opus"))

    def test_fallback_without_config_follows_the_profiles(self):
        self.config({"codex": {"profiles": [{"name": "team-a", "max": 1}]}})
        a = self.run_pool(["team-a"])
        self.assertEqual((a.kind, a.model), ("claude", "opus"))  # the built-in standard profile
        self.assertEqual(self.run_pool(["team-a"], role="reviewer").model, "fable")  # the review table's standard
        self.config({"fable": False, "codex": {"profiles": [{"name": "team-a", "max": 1}]}})
        self.assertEqual(self.run_pool(["team-a"], role="reviewer").model, "sonnet")  # no Fable here

    def test_reviewer_model(self):
        self.assertEqual(self.run_pool([], role="reviewer").model, "review-model")

    def test_default_refused(self):
        with self.assertRaises(Refused):
            self.run_pool([], codex_profile="default")
        # The command line's wrapper turns the refusal into an exit.
        with self.live([]), contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            workers_cmds.apply_codex_pool(ns(codex_profile="default"), "/w/proj", "worker", hold=False, ctx=self.ctx)

    def test_named_profile_even_when_full(self):
        self.assertEqual(self.run_pool(["team-a"] * 2, codex_profile="team-a").provider, "team-a")
        self.assertIn("full", self.warning)
        err = io.StringIO()  # which the command line prints on stderr
        with self.live(["team-a"] * 2), contextlib.redirect_stderr(err):
            workers_cmds.apply_codex_pool(ns(codex_profile="team-a"), "/w/proj", "worker", hold=False, ctx=self.ctx)
        self.assertIn("full", err.getvalue())

    def test_uncounted_machine_says_so(self):
        a = self.run_pool(None)  # no /proc: nothing is counted
        self.assertEqual(a.provider, "team-a")
        self.assertIn("/proc", a.pool_said)

    def test_other_project_untouched(self):
        a, _ = Workers(self.ctx).apply_codex_pool(ns(), "/w/other", "worker", hold=False)
        self.assertEqual((a.provider, a.model), ("", ""))

    def test_argv(self):
        a = self.run_pool([])
        # The project's PM keeps codex args of its own (pm_record): they are left out of a pool worker's command.
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        (self.ctx.home.registrations / "proj.json").write_text(json.dumps({
            "name": "pm-proj", "project": "proj", "repo": "/w/proj",
            "codex": {"args": ["-c", 'service_tier="fast"']}}))
        argv = Workers(self.ctx).worker_argv(a, (), "/w/proj", wrap=True)
        self.assertEqual(argv, ["codex", "-p", "team-a", "-c", "check_for_update_on_startup=false", "-m",
                                "codex-model", "-c", 'model_reasoning_effort="high"'])

    def test_codex_cmd_with_the_pool(self):
        out = io.StringIO()
        command = argparse.Namespace(repo="/w/proj", project=None, model=None, effort="high", codex_profile=None)
        with self.live([]), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            workers_cmds.cmd_codex_cmd(command, ctx=self.ctx)
        self.assertTrue(out.getvalue().startswith("codex -p team-a "))
        with self.live(["team-a"] * 2 + ["team-b"] * 3), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stop:
                workers_cmds.cmd_codex_cmd(command, ctx=self.ctx)
        self.assertEqual(stop.exception.code, 3)  # all full: the Claude command it would start instead


class Fast(Policy):
    def fast_ctx(self, screens=None, terminals=None):
        self.hc = ScreenHc(terminals or {"t9": {"state": "live"}}, clock=self.clock, screens=screens)
        self.ctx = make_ctx(self.base, hc=self.hc, git=self.git, clock=self.clock, out=StdOutput())
        return Workers(self.ctx)

    def test_sends_once_when_not_fast(self):
        workers = self.fast_ctx({"t9": ["› Ask Codex\n  Model-X high · Context 0% used",
                                        "  Model-X high fast · Context 0%"]})
        said = workers.codex_fast("t9", ns(provider="team-b"))
        self.assertEqual(self.hc.sent, [("t9", "/fast")])
        self.assertEqual(self.hc.calls, [])  # nothing else asked of hc
        self.assertIn("fast", said)

    def test_already_fast_not_toggled(self):
        workers = self.fast_ctx({"t9": ["Model-X high fast · Context 0%"]})
        workers.codex_fast("t9", ns(provider="team-b"))
        self.assertEqual((self.hc.sent, self.hc.calls), ([], []))

    def test_no_fast_for_claude_or_default(self):
        workers = self.fast_ctx()
        self.assertEqual(workers.codex_fast("t9", ns(kind="claude")), "")
        self.assertEqual(workers.codex_fast("t9", ns(provider="")), "")
        self.assertEqual((self.hc.sent, self.hc.calls), ([], []))

    def test_ready_marks_for_a_program_without_status(self):
        # Started through a shell launcher, hc reports no status: its screen says when the input is ready.
        workers = self.fast_ctx({"t9": ["> \n  ⏵⏵ bypass permissions on"]}, {"t9": {"state": "live", "status": None}})
        self.assertTrue(workers.send_when_ready("t9", "brief", tries=2, strict=True, kind="claude"))
        self.assertEqual([text for _, text in self.hc.sent], ["brief"])
        workers = self.fast_ctx({"t9": ["Do you trust the files in this folder?"]},
                                {"t9": {"state": "live", "status": None}})
        self.assertFalse(workers.send_when_ready("t9", "brief", tries=2, strict=True, kind="claude"))
        self.assertEqual(self.hc.sent, [])


def make_row(rtype, content=None, *, ts="2026-11-16T14:45:00.000Z", usage=None,
             side=False, meta=False, extra=None):
    obj = {"type": rtype, "timestamp": ts}
    if side:
        obj["isSidechain"] = True
    if meta:
        obj["isMeta"] = True
    if content is not None or usage is not None:
        msg = {}
        if content is not None:
            msg["content"] = content
        if usage is not None:
            msg["usage"] = usage
        obj["message"] = msg
    if extra:
        obj.update(extra)
    return json.dumps(obj, ensure_ascii=False)


class TidierTests(unittest.TestCase):
    def test_unix_home_shortening(self):
        tidy = pm_sessions.Tidier(home="/Users/ann", is_windows=False)
        cases = {
            "/Users/ann/repo/a.py": "~/repo/a.py",
            "cd /Users/ann && ls /Users/ann/": "cd ~ && ls ~/",
            '{"path":"/Users/ann"}': '{"path":"~"}',
            "/Users/ann2/repo and /Users/ann": "/Users/ann2/repo and ~",
            "/Users/annex": "/Users/annex",
            "nothing to shorten": "nothing to shorten",
        }
        for raw, want in cases.items():
            self.assertEqual(tidy.short(raw), want)
        self.assertEqual(pm_sessions.Tidier(home="", is_windows=False).short("/Users/ann/x"), "/Users/ann/x")

    def test_windows_home_shortening_and_unicode_index_safety(self):
        tidy = pm_sessions.Tidier(home=r"C:\Users\Ann", is_windows=True)
        self.assertEqual(tidy.short(r"c:\users\ann\repo\a.py"), r"~\repo\a.py")
        self.assertEqual(tidy.short("C:/Users/Ann/repo/a.py"), "~/repo/a.py")
        self.assertEqual(tidy.short("/c/Users/Ann/repo/a.py"), "~/repo/a.py")
        self.assertEqual(tidy.short(r"C:\\Users\\Ann\\repo"), r"~\\repo")
        # Non-ASCII uppercase like Turkish dotted İ must not shift indices when case-folding.
        self.assertEqual(tidy.short("İ C:/users/ann/file.txt"), "İ ~/file.txt")

    def test_body_and_line_bounds(self):
        tidy = pm_sessions.Tidier(home="/Users/ann", is_windows=False)
        long_text = "长" * (pm_sessions.BODY_MAX + 5)
        self.assertEqual(tidy.body(long_text), "长" * pm_sessions.BODY_MAX + "…")
        long_line = "a.png\n\n  b.png " + "图" * (pm_sessions.SUMMARY_MAX + 50)
        self.assertEqual(tidy.line(long_line), "a.png b.png " + "图" * (pm_sessions.SUMMARY_MAX - 12))


class ClaudeSessionsTests(unittest.TestCase):
    SID = "62134ab3-e3ce-45b6-ad0e-45fa915220e3"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pm-sessions-unit-"))
        self.claude_projects = self.tmp / ".claude" / "projects"
        self.claude_projects.mkdir(parents=True)
        self.sessions = pm_sessions.default_sessions(
            projects_dir=self.claude_projects,
            home=str(self.tmp / "home"),
            cache_path=self.tmp / "cache" / "context-tokens.json",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_transcript(self, folder_name, sid, lines, *, trailing_newline=True):
        folder = self.claude_projects / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{sid}.jsonl"
        text = "\n".join(lines) + ("\n" if trailing_newline and lines else "")
        path.write_text(text, encoding="utf-8")
        return path

    def test_transcript_lookup_validation_hints_and_newest_mtime(self):
        # Unsafe ids are rejected (no path traversal or globbing).
        self.write_transcript("-tmp-a", "secret", [make_row("user", "no")])
        for bad in ("../secret", "a/b", "*", "?", ".hidden", ""):
            self.assertIsNone(self.sessions.transcript({"kind": "claude", "id": bad}))

        # Non-claude kinds are never resolved.
        self.write_transcript("-tmp-a", self.SID, [make_row("user", "hi")])
        self.assertIsNone(self.sessions.transcript({"kind": "codex", "id": self.SID}))
        self.assertIsNone(self.sessions.transcript({"kind": "agy", "id": self.SID}))

        # Newest mtime wins when the same session appears in two folders.
        sid_pair = "99999999-9999-4999-8999-999999999999"
        old = self.write_transcript("-tmp-old", sid_pair, [make_row("user", "old")])
        new = self.write_transcript("-tmp-new", sid_pair, [make_row("user", "new")])
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        fresh = pm_sessions.ClaudeSessions(projects_dir=self.claude_projects)
        self.assertEqual(fresh.transcript({"kind": "claude", "id": sid_pair}), new.resolve())

        # Hints check the matching worktree/repo folder directly first.
        worktree = "/tmp/my_worktree"
        hinted = self.write_transcript(pm_sessions.claude_folder(worktree), "s-hint", [make_row("user", "h")])
        self.assertEqual(fresh.transcript({"kind": "claude", "id": "s-hint", "hints": [worktree]}), hinted.resolve())

    def test_transcript_rejects_paths_outside_projects_dir_and_bad_id_before_path(self):
        outside = self.tmp / "outside.jsonl"
        outside.write_text(make_row("user", "secret") + "\n", encoding="utf-8")
        outside_named = self.tmp / f"{self.SID}.jsonl"
        outside_named.write_text(make_row("user", "outside same name") + "\n", encoding="utf-8")
        other_inside = self.write_transcript("-tmp-other", "other-sid", [make_row("user", "other")])
        # Symlink inside projects_dir pointing outside must also be rejected.
        sym_folder = self.claude_projects / "-tmp-sym"
        sym_folder.mkdir(parents=True)
        sym = sym_folder / f"{self.SID}.jsonl"
        sym.symlink_to(outside_named)

        # Invalid id with an existing path must never be trusted.
        self.assertIsNone(self.sessions.transcript({"kind": "claude", "id": "../bad", "path": str(outside)}))
        self.assertIsNone(self.sessions.transcript({"kind": "claude", "id": "", "path": str(outside)}))
        # Valid id with a path outside projects_dir or a symlink escaping projects_dir is rejected.
        self.assertIsNone(self.sessions.transcript({"kind": "claude", "id": self.SID, "path": str(outside)}))
        self.assertIsNone(self.sessions.transcript({"kind": "claude", "id": self.SID, "path": str(outside_named)}))
        self.assertIsNone(self.sessions.transcript({"kind": "claude", "id": self.SID, "path": str(sym)}))
        # Path inside projects_dir whose filename does not match id is rejected.
        self.assertIsNone(self.sessions.transcript({"kind": "claude", "id": self.SID, "path": str(other_inside)}))
        # Bare path outside projects_dir is also rejected by ClaudeSessions.transcript.
        self.assertIsNone(self.sessions.transcript(outside_named))

    def test_parse_items_tools_queued_sidechain_and_context(self):
        home_str = str(self.tmp / "home")
        long_output = "a.png\n\n  b.png " + "图" * (pm_sessions.SUMMARY_MAX + 50)
        long_text = "长" * (pm_sessions.BODY_MAX + 1)
        lines = [
            make_row("summary", extra={"summary": "ignored"}),
            make_row("user", "system note", meta=True),
            make_row("user", "帮我看一下", ts="2026-11-16T14:45:00.000Z"),
            make_row("assistant", [
                {"type": "text", "text": "好的"},
                {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": f"ls {home_str}/repo"}},
            ], ts="2026-11-16T14:45:01.000Z", usage={"input_tokens": 100, "cache_read_input_tokens": 2000}),
            make_row("user", [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": long_output},
            ], ts="2026-11-16T14:45:02.000Z"),
            make_row("assistant", [
                {"type": "tool_use", "id": "toolu_2", "name": "Read", "input": {"file_path": f"{home_str}/repo/a.png"}},
                {"type": "tool_use", "id": "toolu_3", "name": "WebFetch", "input": {"url": "https://example.com"}},
                {"type": "tool_use", "id": "toolu_4", "name": "Agent", "input": {"description": "look around"}},
            ], ts="2026-11-16T14:45:04.000Z",
                usage={"input_tokens": 12, "cache_read_input_tokens": 120000, "cache_creation_input_tokens": 3000}),
            make_row("user", [
                {"type": "tool_result", "tool_use_id": "toolu_2", "content": [{"type": "text", "text": "File missing"}], "is_error": True},
            ], ts="2026-11-16T14:45:04.500Z"),
            make_row("attachment", ts="2026-11-16T14:45:05.000Z",
                     extra={"attachment": {"type": "queued_command", "prompt": "继续"}}),
            make_row("assistant", [{"type": "text", "text": "sidechain"}],
                     ts="2026-11-16T14:45:06.000Z", usage={"input_tokens": 999999}, side=True),
            make_row("assistant", [{"type": "text", "text": long_text}], ts="2026-11-16T14:45:07.000Z"),
        ]
        self.write_transcript("-tmp-p", self.SID, lines)
        got = self.sessions.turns({"kind": "claude", "id": self.SID})
        d = got.to_dict()
        self.assertEqual(d["kind"], "claude")
        self.assertEqual(d["id"], self.SID)
        self.assertEqual(d["started"], "2026-11-16T14:45:00.000Z")
        self.assertEqual(d["ended"], "2026-11-16T14:45:07.000Z")
        self.assertEqual(d["context"], 123012)
        self.assertFalse(d["earlier"])
        self.assertNotIn("unknown", d)
        items = d["items"]
        self.assertEqual(len(items), 8)
        self.assertEqual((items[0]["type"], items[0]["text"]), ("user", "帮我看一下"))
        self.assertEqual((items[1]["type"], items[1]["text"]), ("text", "好的"))
        self.assertEqual(items[2]["name"], "Bash")
        self.assertEqual(items[2]["input"], "ls ~/repo")
        self.assertEqual(items[2]["output"], "a.png b.png " + "图" * (pm_sessions.SUMMARY_MAX - 12))
        self.assertFalse(items[2]["error"])
        self.assertEqual((items[3]["name"], items[3]["input"], items[3]["output"], items[3]["error"]),
                         ("Read", "~/repo/a.png", "File missing", True))
        self.assertEqual((items[4]["name"], items[4]["input"], items[4]["output"]),
                         ("WebFetch", '{"url":"https://example.com"}', ""))
        self.assertEqual((items[5]["name"], items[5]["input"]), ("Agent", "look around"))
        self.assertEqual((items[6]["type"], items[6]["text"]), ("user", "继续"))
        self.assertEqual(items[7]["text"], "长" * pm_sessions.BODY_MAX + "…")

    def test_pagination_before_after_and_orphan_results(self):
        lines = [make_row("user", f"第 {n} 句", ts=f"2026-11-16T{n // 60:02d}:{n % 60:02d}:00.000Z")
                 for n in range(12)]
        # Tool call on line 12, result on line 13, then half-written trailing line.
        lines.append(make_row("assistant", [
            {"type": "tool_use", "id": "toolu_9", "name": "Bash", "input": {"command": "make"}},
        ], ts="2026-11-17T00:00:00.000Z", usage={"input_tokens": 5000}))
        lines.append(make_row("user", [
            {"type": "tool_result", "tool_use_id": "toolu_9", "content": "done"},
        ], ts="2026-11-17T00:00:01.000Z"))
        lines.append(make_row("user", "最后一句", ts="2026-11-17T00:00:02.000Z"))
        path = self.write_transcript("-tmp-page", self.SID, lines)
        # Append an unterminated line being written.
        with open(path, "ab") as f:
            f.write(b'{"type": "user", "message": {"content": "half')

        # Limit=1 gets the newest user line (plus fallback context=5000 even though usage was earlier!).
        p1 = self.sessions.turns({"kind": "claude", "id": self.SID}, limit=1)
        self.assertEqual([(i["type"], i.get("text")) for i in p1.items], [("user", "最后一句")])
        self.assertTrue(p1.earlier)
        self.assertEqual(p1.started, "2026-11-16T00:00:00.000Z")
        self.assertEqual(p1.context, 5000)

        # Next page before p1.from_ walks back across the tool_result line to its tool_use (count=1 item)
        # and joins the result onto the tool call in place.
        p2 = self.sessions.turns({"kind": "claude", "id": self.SID}, before=p1.from_, limit=1)
        self.assertEqual(p2.started, "")
        self.assertEqual(p2.offset, p1.from_)
        self.assertEqual(len(p2.items), 1)
        self.assertEqual(p2.items[0]["type"], "tool")
        self.assertEqual(p2.items[0]["output"], "done")
        # Wait: let's also verify orphan result explicitly when the boundary splits call and result!
        # Let's walk all pages from end to 0 with limit=3 and confirm full reconstruction.
        collected = []
        cursor = None
        while True:
            page = self.sessions.turns({"kind": "claude", "id": self.SID}, before=cursor, limit=3)
            collected = page.items + collected
            if not page.earlier:
                self.assertEqual(page.from_, 0)
                break
            cursor = page.from_
        user_texts = [i["text"] for i in collected if i["type"] == "user"]
        self.assertEqual(user_texts, [f"第 {n} 句" for n in range(12)] + ["最后一句"])

        # After: finish the half-written line and read incrementally from p1.offset.
        with open(path, "ab") as f:
            f.write(b' finished"}}\n')
        inc = self.sessions.turns({"kind": "claude", "id": self.SID}, after=p1.offset)
        self.assertFalse(inc.reset)
        self.assertEqual([(i["type"], i["text"]) for i in inc.items], [("user", "half finished")])

        # Invalid/stale offsets raise clean errors or reset.
        with self.assertRaises(pm_sessions.SessionChangedError):
            self.sessions.turns({"kind": "claude", "id": self.SID}, before=99999999)
        with self.assertRaises(pm_sessions.InvalidOffsetError):
            self.sessions.turns({"kind": "claude", "id": self.SID}, before=p1.from_ + 1)
        with self.assertRaises(pm_sessions.InvalidOffsetError):
            self.sessions.turns({"kind": "claude", "id": self.SID}, limit=0)
        with self.assertRaises(pm_sessions.InvalidOffsetError):
            self.sessions.turns({"kind": "claude", "id": self.SID}, before=0, after=0)
        reset_win = self.sessions.turns({"kind": "claude", "id": self.SID}, after=99999999)
        self.assertTrue(reset_win.reset)

    def test_orphan_tool_result_emitted_when_call_is_before_window(self):
        # Two huge lines (> SESSION_BACK/2 each) or exact byte boundary splitting tool_use and tool_result.
        call_line = make_row("assistant", [
            {"type": "tool_use", "id": "toolu_split", "name": "Bash", "input": {"command": "echo hi"}},
        ], ts="2026-11-16T00:00:00.000Z")
        res_line = make_row("user", [
            {"type": "tool_result", "tool_use_id": "toolu_split", "content": "hi"},
            {"type": "text", "text": "next"},
        ], ts="2026-11-16T00:00:01.000Z")
        self.write_transcript("-tmp-split", self.SID, [call_line, res_line])
        got = self.sessions.turns({"kind": "claude", "id": self.SID}, limit=1)
        self.assertTrue(got.earlier)
        self.assertEqual([i["type"] for i in got.items], ["result", "user"])
        self.assertEqual((got.items[0]["id"], got.items[0]["output"]), ("toolu_split", "hi"))

    def test_unknown_shape_housekeeping_and_empty_transcripts(self):
        # Unknown shape reports distinct row types.
        self.write_transcript("-tmp-u", self.SID, [
            '{"type": "turn", "said": "hi"}',
            '{"type": "file-history-snapshot"}',
            'not JSON',
        ])
        got = self.sessions.turns({"kind": "claude", "id": self.SID})
        self.assertEqual(got.items, [])
        self.assertEqual(got.unknown, ["turn", "file-history-snapshot", "?"])

        # Housekeeping-only transcript is NOT unknown.
        self.write_transcript("-tmp-u", self.SID, [
            '{"type": "file-history-snapshot"}',
            '{"type": "summary", "summary": "x"}',
        ])
        self.assertIsNone(self.sessions.turns({"kind": "claude", "id": self.SID}).unknown)

        # Empty transcript is NOT unknown.
        self.write_transcript("-tmp-u", self.SID, [])
        self.assertIsNone(self.sessions.turns({"kind": "claude", "id": self.SID}).unknown)

    def test_large_sparse_file_without_newline_is_bounded(self):
        folder = self.claude_projects / "-tmp-sparse"
        folder.mkdir(parents=True)
        sparse = folder / f"{self.SID}.jsonl"
        with open(sparse, "wb") as f:
            f.truncate(pm_sessions.SESSION_TAIL + pm_sessions.SESSION_BACK + 1)
        got = self.sessions.turns({"kind": "claude", "id": self.SID})
        self.assertEqual((got.items, got.offset, got.earlier), ([], 0, False))

    def test_context_tokens_tail_scan_and_stat_cache_on_large_transcript(self):
        # Build a ~24 MB synthetic transcript with usage near the end; verify tail scan + cache hit.
        folder = self.claude_projects / "-tmp-big"
        folder.mkdir(parents=True)
        big = folder / f"{self.SID}.jsonl"
        filler = (make_row("user", "x" * 4000) + "\n").encode("utf-8")
        with open(big, "wb") as f:
            for _ in range(6000):  # ~24 MB
                f.write(filler)
            f.write((make_row("assistant", [{"type": "text", "text": "done"}],
                              usage={"input_tokens": 50, "cache_read_input_tokens": 140000,
                                     "cache_creation_input_tokens": 2000}) + "\n").encode("utf-8"))
            f.write((make_row("user", "thanks") + "\n").encode("utf-8"))

        t0 = time.monotonic()
        tokens = self.sessions.context_tokens({"kind": "claude", "id": self.SID})
        cold_s = time.monotonic() - t0
        self.assertEqual(tokens, 142050)
        self.assertLess(cold_s, 1.0)
        self.sessions.flush()

        # Warm lookup in a brand-new instance (simulating the next `pm.py state` subprocess)
        # must hit the disk cache via stat() without opening or scanning the transcript file.
        second = pm_sessions.default_sessions(
            projects_dir=self.claude_projects,
            cache_path=self.tmp / "cache" / "context-tokens.json",
        )
        with mock.patch.object(pm_sessions, "context_tokens_file", side_effect=AssertionError("should hit cache")):
            self.assertEqual(second.context_tokens({"kind": "claude", "id": self.SID}), 142050)

        # Appending a new assistant call changes size/mtime -> cache invalidates automatically.
        with open(big, "ab") as f:
            f.write((make_row("assistant", [{"type": "text", "text": "more"}],
                              usage={"input_tokens": 100, "cache_read_input_tokens": 180000}) + "\n").encode("utf-8"))
        self.assertEqual(second.context_tokens({"kind": "claude", "id": self.SID}), 180100)

    def test_unsupported_agent_kinds_do_not_guess(self):
        for kind in ("codex", "pi"):
            s = {"kind": kind, "id": self.SID}
            self.assertIsNone(self.sessions.transcript(s))
            self.assertEqual(self.sessions.context_tokens(s), 0)
            with self.assertRaises(pm_sessions.UnsupportedSessionError):
                self.sessions.turns(s)
        # agy is supported: a missing transcript reports SessionNotFoundError rather than UnsupportedSessionError.
        agy_missing = {"kind": "agy", "id": self.SID}
        self.assertIsNone(self.sessions.transcript(agy_missing))
        self.assertEqual(self.sessions.context_tokens(agy_missing), 0)
        with self.assertRaises(pm_sessions.SessionNotFoundError):
            self.sessions.turns(agy_missing)

    def test_compact_summary_rows_skipped_and_session_started_skips_summary(self):
        rows = [
            json.dumps({
                "type": "user", "timestamp": "2026-11-16T14:40:00.000Z",
                "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
                "message": {"role": "user", "content": "This session is being continued from a previous conversation."},
            }),
            make_row("user", "继续做第二步", ts="2026-11-16T14:45:00.000Z"),
            make_row("assistant", [{"type": "text", "text": "好，接着做。"}],
                     ts="2026-11-16T14:45:05.000Z", usage={"input_tokens": 18500}),
        ]
        self.write_transcript("-tmp-cs", self.SID, rows)
        got = self.sessions.turns({"kind": "claude", "id": self.SID})
        self.assertIsNone(got.unknown)
        self.assertEqual([(i["type"], i.get("text")) for i in got.items],
                         [("user", "继续做第二步"), ("text", "好，接着做。")])
        self.assertEqual(got.started, "2026-11-16T14:45:00.000Z")

    def test_compact_boundary_stops_context_scan_and_cache_version_2(self):
        # 1. compact_boundary stops backwards scan and returns postTokens instead of pre-compaction 195k usage.
        rows = [
            make_row("user", "很早的问题", ts="2026-11-16T14:00:00.000Z"),
            make_row("assistant", [{"type": "text", "text": "旧回复"}],
                     ts="2026-11-16T14:01:00.000Z", usage={"input_tokens": 195000}),
            json.dumps({
                "type": "system", "subtype": "compact_boundary", "isSidechain": False,
                "timestamp": "2026-11-16T14:10:00.000Z",
                "compactMetadata": {"trigger": "auto", "preTokens": 195000, "postTokens": 14500},
            }),
            json.dumps({
                "type": "user", "timestamp": "2026-11-16T14:10:01.000Z",
                "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
                "message": {"role": "user", "content": "Compacted summary"},
            }),
        ]
        p = self.write_transcript("-tmp-cb", self.SID, rows)
        self.assertEqual(pm_sessions.context_tokens_file(p), 14500)
        got = self.sessions.turns({"kind": "claude", "id": self.SID})
        self.assertIsNone(got.unknown)
        self.assertEqual(got.context, 14500)
        self.assertEqual([(i["type"], i.get("text")) for i in got.items],
                         [("user", "很早的问题"), ("text", "旧回复")])

        # 2. A post-compaction assistant usage supersedes compact_boundary postTokens.
        with open(p, "a", encoding="utf-8") as f:
            f.write(make_row("assistant", [{"type": "text", "text": "新回复"}],
                             ts="2026-11-16T14:11:00.000Z", usage={"input_tokens": 22000}) + "\n")
        self.assertEqual(pm_sessions.context_tokens_file(p), 22000)
        self.assertEqual(self.sessions.turns({"kind": "claude", "id": self.SID}).context, 22000)

        # 3. A second compact_boundary with postTokens=0 returns 0 instead of scanning behind it.
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "system", "subtype": "compact_boundary", "isSidechain": False,
                "timestamp": "2026-11-16T14:20:00.000Z",
                "compactMetadata": {"trigger": "manual", "postTokens": 0},
            }) + "\n")
        self.assertEqual(pm_sessions.context_tokens_file(p), 0)
        self.assertEqual(self.sessions.turns({"kind": "claude", "id": self.SID}).context, 0)

        # 4. _ContextCache ignores stale version 1 disk caches and writes version 2 on flush().
        cache_path = self.tmp / "cache" / "v-check.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        st = p.stat()
        cache_path.write_text(json.dumps({
            "version": 1,
            "entries": {str(p): [st.st_mtime_ns, st.st_size, 195000, 1]},
        }), encoding="utf-8")
        reloaded = pm_sessions.default_sessions(projects_dir=self.claude_projects, cache_path=cache_path)
        self.assertEqual(reloaded.context_tokens({"kind": "claude", "id": self.SID}), 0)
        reloaded.flush()
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], 2)

    def test_turns_extracts_structured_questions_without_truncating_options(self):
        long_desc = "详细说明" * 40  # > 300 chars total JSON when combined with multiple options
        lines = [
            make_row("user", "继续做 web-i18n", ts="2026-11-24T10:00:00.000Z"),
            make_row("assistant", [
                {"type": "tool_use", "id": "toolu_b1", "name": "Bash", "input": {"command": "git status"}},
                {
                    "type": "tool_use",
                    "id": "toolu_q1",
                    "name": "AskUserQuestion",
                    "input": {
                        "questions": [{
                            "header": "i18n 策略",
                            "question": "新增文案默认走英文还是中文？",
                            "options": [
                                {"label": "默认英文（推荐）", "description": long_desc},
                                {"label": "默认中文", "description": "仅中文界面展示"},
                                {"label": "双语并存", "description": "同时维护 en/zh 两套"},
                            ],
                        }],
                    },
                },
            ], ts="2026-11-24T10:00:05.000Z"),
        ]
        self.write_transcript("-tmp-ask", self.SID, lines)
        got = self.sessions.turns({"kind": "claude", "id": self.SID}).to_dict()
        q_item = next(i for i in got["items"] if i.get("name") == "AskUserQuestion")
        self.assertEqual(q_item["input"], "新增文案默认走英文还是中文？")
        self.assertEqual(len(q_item["questions"]), 1)
        q = q_item["questions"][0]
        self.assertEqual(q["header"], "i18n 策略")
        self.assertEqual(q["question"], "新增文案默认走英文还是中文？")
        self.assertEqual([o["label"] for o in q["options"]], ["默认英文（推荐）", "默认中文", "双语并存"])
        self.assertTrue(q["options"][0]["description"].startswith("详细说明"))




class PmStateAndCliTests(unittest.TestCase):
    SID_PM = "11111111-1111-4111-8111-111111111111"
    SID_TASK = "22222222-2222-4222-8222-222222222222"
    SID_FIND = "33333333-3333-4333-8333-333333333333"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="pm-sessions-int-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.repo = str((self.tmp / "proj").resolve())
        Path(self.repo).mkdir(parents=True)
        self.clock = FakeClock()
        # hc answers nothing (as `pm.hc = lambda *a, **kw: None` did) until a test gives it terminals.
        self.hc = FakeHc(clock=self.clock, server_running=False)
        self.tui = FakeTui()
        self.env = {}
        self.be("")
        self.claude = self.ctx.claude_projects
        self.claude.mkdir(parents=True)
        self.codex = self.ctx.codex_sessions
        self.codex.mkdir(parents=True)

    def be(self, pane):
        self.ctx = make_ctx(self.tmp / "ctx", pane=pane, hc=self.hc, tui=self.tui, clock=self.clock,
                            out=StdOutput(), env=self.env)

    @property
    def pms(self):
        self.ctx.home.registrations.mkdir(parents=True, exist_ok=True)
        return self.ctx.home.registrations

    def save(self, task):
        Ledger(self.ctx).save(task)

    def load(self, task_id):
        return Ledger(self.ctx).load(task_id)

    def dash_state(self):
        return state_view.dash_state(ctx=self.ctx)

    def write_claude(self, folder_path, sid, lines):
        folder = self.claude / pm_sessions.claude_folder(folder_path)
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{sid}.jsonl"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def fire_hook(self, payload):
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(io.StringIO()):
            hooks.cmd_hook_turn(None, ctx=self.ctx)

    def test_state_includes_optional_context_tokens_for_pm_and_tasks(self):
        slug = project_slug(self.repo)
        pm_transcript = self.write_claude(self.repo, self.SID_PM, [
            make_row("user", "hi"),
            make_row("assistant", [{"type": "text", "text": "hello"}],
                     usage={"input_tokens": 100, "cache_read_input_tokens": 85000}),
        ])
        (self.pms / f"{slug}.json").write_text(json.dumps({
            "name": pm_name(self.repo), "project": Path(self.repo).name, "repo": self.repo,
            "pane": "hc:tpm", "runtime": "hc", "terminal": "tpm", "agent": "claude",
            "agent_session": {"kind": "claude", "id": self.SID_PM, "path": str(pm_transcript)},
        }))
        # Second PM using codex: context_tokens must be omitted.
        repo2 = str((self.tmp / "proj2").resolve())
        Path(repo2).mkdir()
        (self.pms / f"{project_slug(repo2)}.json").write_text(json.dumps({
            "name": pm_name(repo2), "project": "proj2", "repo": repo2,
            "pane": "hc:tpm2", "runtime": "hc", "terminal": "tpm2", "agent": "codex",
        }))

        # Task with Claude session, task with Codex session, task without session.
        self.write_claude(self.repo, self.SID_TASK, [
            make_row("user", "do work"),
            make_row("assistant", [{"type": "text", "text": "working"}],
                     usage={"input_tokens": 50, "cache_read_input_tokens": 42000}),
        ])
        now = self.clock.now()
        self.save({"id": "proj-claude", "title": "Claude task", "project": "proj", "repo": self.repo,
                   "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:tw1",
                   "created": now, "session": {"kind": "claude", "id": self.SID_TASK}})
        self.save({"id": "proj-codex", "title": "Codex task", "project": "proj", "repo": self.repo,
                   "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:tw2",
                   "created": now, "session": {"kind": "codex", "id": "codex-1"}})
        self.save({"id": "proj-none", "title": "No session", "project": "proj", "repo": self.repo,
                   "status": "proposed", "owner": "pm", "base": "main", "created": now})

        state = self.dash_state()
        pms = {p["project"]: p for p in state["pms"]}
        tasks = {t["id"]: t for t in state["tasks"]}
        self.assertEqual(state["compact_tokens"], launch_mod.COMPACT_TOKENS)
        self.assertEqual(state["rotate_tokens"], launch_mod.COMPACT_TOKENS)
        self.assertEqual(pms["proj"]["context_tokens"], 85100)
        self.assertNotIn("context_tokens", pms["proj2"])
        self.assertEqual(tasks["proj-claude"]["context_tokens"], 42050)
        self.assertNotIn("context_tokens", tasks["proj-codex"])
        self.assertNotIn("context_tokens", tasks["proj-none"])
        # PM_COMPACT_TOKENS is read once, into the launch module's constant: set it for this block only.
        with mock.patch.object(launch_mod, "COMPACT_TOKENS", 350000):
            patched = self.dash_state()
            self.assertEqual(patched["compact_tokens"], 350000)
            self.assertEqual(patched["rotate_tokens"], 350000)
            patched_pms = {p["project"]: p for p in patched["pms"]}
            self.assertEqual(patched_pms["proj"]["compact_tokens"], 350000)

    def test_dash_state_pm_compact_tokens_per_agent(self):
        for slug, proj, agent in (
            ("claude", "p-claude", "claude"),
            ("codex", "p-codex", "codex"),
            ("pi", "p-pi", "pi"),
            ("agy", "p-agy", "agy"),
        ):
            repo = str(Path(self.tmp) / proj)
            Path(repo).mkdir(exist_ok=True)
            (self.pms / f"{slug}.json").write_text(json.dumps({
                "name": f"pm-{proj}", "project": proj, "repo": repo,
                "pane": f"hc:t-{slug}", "runtime": "hc", "terminal": f"t-{slug}", "agent": agent,
            }))
        state = self.dash_state()
        by_proj = {p["project"]: p for p in state["pms"]}
        self.assertEqual(by_proj["p-claude"]["compact_tokens"], claude_compact_settings(ctx=self.ctx)["autoCompactWindow"])
        self.assertEqual(by_proj["p-claude"]["compact_tokens"], 200_000)
        self.assertEqual(by_proj["p-codex"]["compact_tokens"], 220_000)
        self.assertIn("model_auto_compact_token_limit=220000", codex_pm_compact("codex", ["codex"], ctx=self.ctx))
        self.assertEqual(by_proj["p-pi"]["compact_tokens"], 220_000)
        self.assertEqual(by_proj["p-agy"]["compact_tokens"], 200_000)
        self.assertEqual(
            launch_mod.pm_compact_env("agy", ctx=self.ctx),
            {"AGY_CLI_AUTO_COMPACT_OVERRIDE": "200000"},
        )
        self.assertEqual(launch_mod.pm_compact_env("claude", ctx=self.ctx), {})

        cfg_path = self.ctx.home.config
        cfg_path.write_text(json.dumps({"pm": {"compact_tokens": 260_000}}))
        by_proj = {p["project"]: p for p in self.dash_state()["pms"]}
        self.assertEqual(by_proj["p-claude"]["compact_tokens"], 260_000)
        self.assertEqual(by_proj["p-codex"]["compact_tokens"], 260_000)
        self.assertEqual(by_proj["p-pi"]["compact_tokens"], 220_000)
        self.assertEqual(by_proj["p-agy"]["compact_tokens"], 260_000)
        self.assertEqual(
            launch_mod.pm_compact_env("agy", ctx=self.ctx),
            {"AGY_CLI_AUTO_COMPACT_OVERRIDE": "260000"},
        )
        self.assertIn("model_auto_compact_token_limit=260000", codex_pm_compact("codex", ["codex"], ctx=self.ctx))

        cfg_path.write_text(json.dumps({"pm": {"compact_tokens": 150_000}}))
        self.assertEqual(
            launch_mod.pm_compact_env("", ["agy", "--model", "gemini-4-neon-medium"], ctx=self.ctx),
            {"AGY_CLI_AUTO_COMPACT_OVERRIDE": "150000"},
        )
        cfg_path.write_text(json.dumps({"pm": {"compact_tokens": 260_000}}))

        self.env = {"PM_PI_COMPACT_TOKENS": "280000"}  # the session's environment
        self.be("")
        by_proj = {p["project"]: p for p in self.dash_state()["pms"]}
        self.assertEqual(by_proj["p-pi"]["compact_tokens"], 280_000)
        self.env = {}
        self.be("")

        cfg_path.write_text(json.dumps({"pm": {"compact": False}}))
        disabled = self.dash_state()
        by_proj = {p["project"]: p for p in disabled["pms"]}
        self.assertEqual(disabled["compact_tokens"], 0)
        self.assertEqual(by_proj["p-claude"]["compact_tokens"], 0)
        self.assertEqual(by_proj["p-codex"]["compact_tokens"], 0)
        self.assertEqual(by_proj["p-pi"]["compact_tokens"], 0)
        self.assertEqual(by_proj["p-agy"]["compact_tokens"], 0)
        self.assertEqual(launch_mod.pm_compact_env("agy", ctx=self.ctx), {})

    def test_pm_context_from_hook_turn_and_taken_in_fallback_excludes_previous(self):
        slug = project_slug(self.repo)
        rec_path = self.pms / f"{slug}.json"
        rec_path.write_text(json.dumps({
            "name": pm_name(self.repo), "project": "proj", "repo": self.repo,
            "pane": "hc:tpm", "runtime": "hc", "terminal": "tpm", "agent": "claude",
        }))
        old_t = self.write_claude(self.repo, "old-session", [
            make_row("assistant", [{"type": "text", "text": "old"}], usage={"input_tokens": 199000}),
        ])
        new_t = self.write_claude(self.repo, self.SID_PM, [
            make_row("user", "开始"),
            make_row("assistant", [{"type": "text", "text": "好"}], usage={"input_tokens": 12000}),
        ])
        # taken-in.json fallback works even before agent_session is written.
        mark_dir = self.ctx.home.projects / slug
        mark_dir.mkdir(parents=True)
        (mark_dir / "taken-in.json").write_text(json.dumps({"files": {str(old_t): {"offset": 0, "at": ""}}}))
        self.assertEqual(self.dash_state()["pms"][0]["context_tokens"], 199000)

        # After rotation sets previous.transcript == old_t, taken-in.json does not attribute old_t to the new PM.
        rec = json.loads(rec_path.read_text())
        rec["previous"] = {"transcript": str(old_t)}
        rec_path.write_text(json.dumps(rec))
        self.assertNotIn("context_tokens", self.dash_state()["pms"][0])

        # hook-turn records agent_session on pms/<slug>.json.
        self.be("hc:tpm")
        self.fire_hook({
            "hook_event_name": "UserPromptSubmit",
            "prompt": "查状态",
            "transcript_path": str(new_t),
            "session_id": self.SID_PM,
            "cwd": self.repo,
        })
        updated = json.loads(rec_path.read_text())
        self.assertEqual(updated["agent_session"]["id"], self.SID_PM)
        self.assertEqual(self.dash_state()["pms"][0]["context_tokens"], 12000)

    def test_project_session_cli_pagination_and_find_session_fallback(self):
        # Subprocess test with isolated temporary HOME and PM_HOME (never touches real ~/.claude).
        sub_home = self.tmp / "fake-home"
        sub_ledger = self.tmp / "fake-ledger"
        worktree = self.tmp / "wt-b"
        worktree.mkdir(parents=True)
        (sub_ledger / "tasks").mkdir(parents=True)
        # Task 1: explicit Claude session.
        t1_folder = sub_home / ".claude" / "projects" / pm_sessions.claude_folder(worktree)
        t1_folder.mkdir(parents=True)
        (t1_folder / f"{self.SID_TASK}.jsonl").write_text("\n".join([
            make_row("user", "第一句", ts="2026-11-16T10:00:00.000Z"),
            make_row("assistant", [{"type": "text", "text": "回复一"}],
                     ts="2026-11-16T10:00:01.000Z", usage={"input_tokens": 1000}),
            make_row("user", "第二句", ts="2026-11-16T10:01:00.000Z"),
            make_row("assistant", [{"type": "text", "text": "回复二"}],
                     ts="2026-11-16T10:01:01.000Z", usage={"input_tokens": 2500}),
        ]) + "\n", encoding="utf-8")
        (sub_ledger / "tasks" / "proj-t1.json").write_text(json.dumps({
            "id": "proj-t1", "title": "T1", "project": "proj", "repo": self.repo, "worktree": str(worktree),
            "status": "in_progress", "created": "2026-11-16 09:50",
            "session": {"kind": "claude", "id": self.SID_TASK},
        }))
        # Task 2: no session recorded -> located via pm.py's find_session (mentions `update proj-t2`).
        (t1_folder / f"{self.SID_FIND}.jsonl").write_text("\n".join([
            make_row("user", "run pm.py update proj-t2 --status review", ts="2026-11-16T11:00:00.000Z",
                     extra={"cwd": str(worktree)}),
            make_row("assistant", [{"type": "text", "text": "on it"}],
                     ts="2026-11-16T11:00:01.000Z", usage={"input_tokens": 3300}),
        ]) + "\n", encoding="utf-8")
        (sub_ledger / "tasks" / "proj-t2.json").write_text(json.dumps({
            "id": "proj-t2", "title": "T2", "project": "proj", "repo": self.repo, "worktree": str(worktree),
            "status": "in_progress", "created": "2026-11-16 10:50",
        }))
        # Task 3: Codex session -> refused cleanly, never guessed.
        (sub_ledger / "tasks" / "proj-codex.json").write_text(json.dumps({
            "id": "proj-codex", "title": "Codex", "project": "proj", "repo": self.repo,
            "status": "in_progress", "created": "2026-11-16 10:50",
            "session": {"kind": "codex", "id": "codex-abc"},
        }))
        # Task 4: agy worker without recorded session -> discovered via AGY_DATA_DIR & read with tool pairing.
        agy_dir = self.tmp / "fake-agy"
        agy_cid = "22222222-3333-4444-8555-666666666666"
        agy_logs = agy_dir / "brain" / agy_cid / ".system_generated" / "logs"
        agy_logs.mkdir(parents=True)
        (agy_logs / "transcript_full.jsonl").write_text("\n".join([
            json.dumps({
                "step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
                "created_at": "2026-11-16T12:00:00Z",
                "content": "<USER_REQUEST>\nTask brief: run pm.py update proj-agy --status review\n</USER_REQUEST>",
            }),
            json.dumps({
                "step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                "created_at": "2026-11-16T12:00:05Z", "input_tokens": 800, "cache_read_tokens": 4200,
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": '"pytest -q"'}}],
            }),
            json.dumps({
                "step_index": 2, "source": "MODEL", "type": "GENERIC", "status": "DONE",
                "created_at": "2026-11-16T12:00:06Z", "content": "3 passed",
            }),
            json.dumps({
                "step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                "created_at": "2026-11-16T12:00:10Z", "input_tokens": 900, "cache_read_tokens": 5100,
                "content": "全部完成。",
            }),
        ]) + "\n", encoding="utf-8")
        (sub_ledger / "tasks" / "proj-agy.json").write_text(json.dumps({
            "id": "proj-agy", "title": "Agy", "project": "proj", "repo": self.repo, "worktree": str(worktree),
            "status": "in_progress", "created": "2026-11-16 11:55",
            "worker": {"kind": "agy", "model": "gemini-4-neon-medium"},
        }))

        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sub_home), "USERPROFILE": str(sub_home),
               "PM_HOME": str(sub_ledger), "AGY_DATA_DIR": str(agy_dir)}
        run = lambda *args: subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "pm.py"), *args],
            capture_output=True, text=True, env=env, timeout=20,
        )

        r1 = run("project", "session", "proj-t1", "--limit", "2")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        page1 = json.loads(r1.stdout)
        self.assertEqual([i["text"] for i in page1["items"]], ["第二句", "回复二"])
        self.assertEqual(page1["context"], 2500)
        self.assertTrue(page1["earlier"])
        self.assertEqual(page1["started"], "2026-11-16T10:00:00.000Z")

        r2 = run("project", "session", "proj-t1", "--before", str(page1["from"]), "--limit", "2")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        page2 = json.loads(r2.stdout)
        self.assertEqual([i["text"] for i in page2["items"]], ["第一句", "回复一"])
        self.assertFalse(page2["earlier"])
        self.assertEqual(page2["from"], 0)

        # find_session fallback works for task without recorded session (Claude and agy).
        r_find = run("project", "session", "proj-t2")
        self.assertEqual(r_find.returncode, 0, r_find.stderr)
        found = json.loads(r_find.stdout)
        self.assertEqual(found["id"], self.SID_FIND)
        self.assertEqual(found["context"], 3300)

        r_agy = run("project", "session", "proj-agy", "--limit", "10")
        self.assertEqual(r_agy.returncode, 0, r_agy.stderr)
        agy_page = json.loads(r_agy.stdout)
        self.assertEqual(agy_page["kind"], "agy")
        self.assertEqual(agy_page["id"], agy_cid)
        self.assertEqual(agy_page["context"], 6000)
        self.assertEqual(agy_page["started"], "2026-11-16T12:00:00Z")
        self.assertTrue(any(i["type"] == "tool" and i["name"] == "run_command" and i["input"] == "pytest -q" and i["output"] == "3 passed" for i in agy_page["items"]))
        self.assertTrue(any(i["type"] == "text" and i["text"] == "全部完成。" for i in agy_page["items"]))

        # Codex session and missing/invalid task exit non-zero with clear error.
        r_codex = run("project", "session", "proj-codex")
        self.assertNotEqual(r_codex.returncode, 0)
        self.assertIn("codex", r_codex.stderr.lower())

        self.assertNotEqual(run("project", "session", "../escape").returncode, 0)
        self.assertNotEqual(run("project", "session", "no-such-task").returncode, 0)

    def test_missing_pm_sessions_module_degrades_state_and_errors_on_project_session(self):
        # Copy pm.py and its required sibling modules (pm_store.py, pm_project.py), omitting ONLY pm_sessions.py.
        solo = self.tmp / "solo"
        solo.mkdir()
        for name in ("pm.py", "pm_store.py", "pm_project.py"):
            shutil.copy2(SCRIPTS_DIR / name, solo / name)
        shutil.copytree(SCRIPTS_DIR / "pmlib", solo / "pmlib", ignore=shutil.ignore_patterns("__pycache__"))  # pm.py's code
        (solo / "pmlib" / "agents" / "transcripts.py").unlink()  # simulate missing transcript reader module
        sub_home = self.tmp / "solo-home"
        sub_ledger = self.tmp / "solo-ledger"
        (sub_ledger / "tasks").mkdir(parents=True)
        (sub_ledger / "tasks" / "proj-a.json").write_text(json.dumps({
            "id": "proj-a", "title": "A", "project": "proj", "repo": self.repo,
            "status": "in_progress", "created": "2026-11-16 10:00",
            "session": {"kind": "claude", "id": self.SID_TASK},
        }))
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sub_home), "USERPROFILE": str(sub_home),
               "PM_HOME": str(sub_ledger)}
        # `state` quietly degrades (returns valid state without context_tokens).
        st = subprocess.run([sys.executable, str(solo / "pm.py"), "state"],
                            capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(st.returncode, 0, st.stderr)
        data = json.loads(st.stdout)
        self.assertEqual(len(data["tasks"]), 1)
        self.assertNotIn("context_tokens", data["tasks"][0])
        # `project session` gives an explicit error naming pm_sessions.py.
        ps = subprocess.run([sys.executable, str(solo / "pm.py"), "project", "session", "proj-a"],
                            capture_output=True, text=True, env=env, timeout=20)
        self.assertNotEqual(ps.returncode, 0)
        self.assertIn("pm_sessions.py", ps.stderr)

    def test_in_progress_claude_task_review_in_place_and_strict_hook_ownership(self):
        wt = str((self.tmp / "wt-live").resolve())
        Path(wt).mkdir()
        in_place_dir = str((self.tmp / "custom-here").resolve())
        Path(in_place_dir).mkdir()
        other_repo = str((self.tmp / "other-repo").resolve())
        Path(other_repo).mkdir()

        # 1. Active Claude task, a real *-review.json WITHOUT `worktree` (only `review_of`), and a `--here --path`
        # task with `in_place` (empty `worktree`), all without recorded `session` (e.g. machine without hooks).
        self.write_claude(wt, self.SID_TASK, [
            make_row("user", "brief: run pm.py update proj-live --status review"),
            make_row("assistant", [{"type": "text", "text": "working"}], usage={"input_tokens": 31000}),
        ])
        self.write_claude(wt, "rev-sid", [
            make_row("user", "review proj-live; report with pm.py update proj-live-review --status done"),
            make_row("assistant", [{"type": "text", "text": "reviewing"}], usage={"input_tokens": 99000}),
        ])
        self.write_claude(wt, "pm-in-same-dir", [
            make_row("user", f"You are pm-proj, {PM_SESSION_MARK}. update proj-live"),
            make_row("assistant", [{"type": "text", "text": "pm"}], usage={"input_tokens": 777777}),
        ])
        self.write_claude(in_place_dir, "inplace-sid", [
            make_row("user", "brief: pm.py update proj-here --status review"),
            make_row("assistant", [{"type": "text", "text": "here"}], usage={"input_tokens": 27000}),
        ])
        now = self.clock.now()
        self.save({"id": "proj-live", "title": "Live Claude", "project": "proj", "repo": self.repo,
                   "worktree": wt, "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:tw1",
                   "worker": {"kind": "claude", "model": "opus"}, "created": now})
        # Notice: NO `worktree` field on *-review.json (matches real cmd_review output!).
        self.save({"id": "proj-live-review", "title": "Review", "project": "proj", "repo": self.repo,
                   "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:tw2",
                   "review_of": "proj-live", "worker": {"kind": "claude", "model": "opus"}, "created": now})
        self.save({"id": "proj-here", "title": "In place", "project": "proj", "repo": self.repo,
                   "worktree": "", "in_place": in_place_dir, "status": "in_progress", "owner": "pm",
                   "base": "main", "pane": "hc:tw4", "worker": {"kind": "claude", "model": "opus"},
                   "created": now})
        self.save({"id": "proj-agy-live", "title": "Live Agy", "project": "proj", "repo": self.repo,
                   "worktree": wt, "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:tw3",
                   "worker": {"kind": "agy", "model": "gemini-4-neon-high"}, "created": now})

        tasks = {t["id"]: t for t in self.dash_state()["tasks"]}
        self.assertEqual(tasks["proj-live"]["context_tokens"], 31000)
        self.assertEqual(tasks["proj-live-review"]["context_tokens"], 99000)
        self.assertEqual(tasks["proj-here"]["context_tokens"], 27000)
        self.assertNotIn("context_tokens", tasks["proj-agy-live"])
        # session_places also includes review_of's worktree and in_place.
        self.assertIn(wt, session_places_for(self.ctx, self.load("proj-live-review")))
        self.assertIn(in_place_dir, session_places_for(self.ctx, self.load("proj-here")))

        # 2. Strict hook ownership in hc: requires task=<id> label AND matching cwd.
        wt2 = str((self.tmp / "wt-hook").resolve())
        Path(wt2).mkdir()
        hook_sid = "44444444-4444-4444-8444-444444444444"
        stray_sid = "55555555-5555-4555-8555-555555555555"
        tpath = self.write_claude(wt2, hook_sid, [
            make_row("user", "start"),
            make_row("assistant", [{"type": "text", "text": "go"}], usage={"input_tokens": 18500}),
        ])
        self.save({"id": "proj-hooked", "title": "Hooked", "project": "proj", "repo": self.repo,
                   "worktree": wt2, "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:tw9",
                   "worker_pane": "hc:tw9", "worker": {"kind": "claude", "model": "opus"}, "created": now})

        def fire_turn(sid, path, cwd):
            self.fire_hook({"hook_event_name": "UserPromptSubmit", "prompt": "hi",
                            "transcript_path": str(path), "session_id": sid, "cwd": cwd})

        # 2a. Terminal WITHOUT task= label must NOT bind or overwrite task["session"].
        self.be("hc:tw9")
        self.hc.server_running = True
        self.hc.terminals["tw9"] = {"labels": {}, "cwd": wt2}
        fire_turn(stray_sid, tpath, wt2)
        self.assertNotIn("session", self.load("proj-hooked"))

        # 2b. Terminal WITH task= label but wrong cwd (another repo) must NOT bind.
        self.hc.terminals["tw9"] = {"labels": {"task": "proj-hooked"}, "cwd": other_repo}
        fire_turn(stray_sid, tpath, other_repo)
        self.assertNotIn("session", self.load("proj-hooked"))

        # 2c. Terminal WITH task= label AND matching cwd binds cleanly.
        self.hc.terminals["tw9"] = {"labels": {"task": "proj-hooked"}, "cwd": wt2}
        fire_turn(hook_sid, tpath, wt2)
        self.assertEqual(self.load("proj-hooked")["session"], {"kind": "claude", "id": hook_sid})
        self.assertEqual({t["id"]: t for t in self.dash_state()["tasks"]}["proj-hooked"]["context_tokens"], 18500)

        # 3. Strict hook ownership in herdr TUI: requires worker_pane + live agent name + cwd,
        # and NEVER overwrites an already-recorded session.
        self.be("w1:p5")
        self.save({"id": "proj-tui", "title": "TUI", "project": "proj", "repo": self.repo,
                   "worktree": wt2, "status": "in_progress", "owner": "pm", "base": "main",
                   "pane": "w1:p5", "worker_pane": "w1:p5", "agent": "w-tui",
                   "worker": {"kind": "claude", "model": "opus"}, "created": now})
        # Wrong cwd (same pane id in another repo) -> refused.
        self.tui = FakeTui(agents=[{"pane_id": "w1:p5", "name": "w-tui"}])
        self.be("w1:p5")
        fire_turn(stray_sid, tpath, other_repo)
        self.assertNotIn("session", self.load("proj-tui"))
        # Different agent in same pane -> refused.
        self.tui = FakeTui(agents=[{"pane_id": "w1:p5", "name": "other-agent"}])
        self.be("w1:p5")
        fire_turn(stray_sid, tpath, wt2)
        self.assertNotIn("session", self.load("proj-tui"))
        # Matching worker_pane + live agent + cwd -> recorded once.
        self.tui = FakeTui(agents=[{"pane_id": "w1:p5", "name": "w-tui"}])
        self.be("w1:p5")
        fire_turn(hook_sid, tpath, wt2)
        self.assertEqual(self.load("proj-tui")["session"], {"kind": "claude", "id": hook_sid})
        # Once recorded in TUI, another session in the same pane must NOT overwrite it.
        fire_turn(stray_sid, tpath, wt2)
        self.assertEqual(self.load("proj-tui")["session"], {"kind": "claude", "id": hook_sid})

    def test_re_review_fresh_reattach_and_stale_session_kind_conflict(self):
        wt = str((self.tmp / "wt-rerev").resolve())
        Path(wt).mkdir()
        round1_sid = "66666666-6666-4666-8666-666666666666"
        round1_t = self.write_claude(wt, round1_sid, [
            make_row("user", "pm.py update proj-r-review --status done"),
            make_row("assistant", [{"type": "text", "text": "round 1"}], usage={"input_tokens": 55000}),
        ])
        now = self.clock.now()
        self.save({"id": "proj-r", "title": "R", "project": "proj", "repo": self.repo,
                   "worktree": wt, "branch": "dev/r", "status": "review", "owner": "pm",
                   "base": "main", "pane": "hc:tw1", "created": now})
        self.save({"id": "proj-r-review", "title": "Review: R", "project": "proj", "repo": self.repo,
                   "status": "done", "owner": "pm", "base": "main", "pane": "hc:tr1", "worker_pane": "hc:tr1",
                   "review_of": "proj-r", "worker": {"kind": "claude", "model": "opus"},
                   "session": {"kind": "claude", "id": round1_sid}, "created": now})
        # The project's PM is a desktop-app terminal (what app_pm answered); hc starts the reviewer's terminal.
        (self.pms / f"{project_slug(self.repo)}.json").write_text(json.dumps({
            "name": pm_name(self.repo), "project": "proj", "repo": self.repo,
            "pane": "hc:tpm", "runtime": "hc", "terminal": "tpm", "agent": "claude"}))
        self.hc.server_running = True
        self.hc.terminals["tpm"] = {"state": "live", "labels": {"pm": "proj"}, "status": {"state": "idle"}}

        # 1. Re-review with fresh Claude clears old["session"] and blocks falling back to round1_t.
        with contextlib.redirect_stdout(io.StringIO()):
            review_cmds.cmd_review(argparse.Namespace(id="proj-r", name=None, kind="claude", model="opus",
                                                      effort=None, tab=None, bug=None, codex_profile=None,
                                                      dry_run=False), ctx=self.ctx)
        r2 = self.load("proj-r-review")
        self.assertNotIn("session", r2)
        self.assertIn(round1_sid, r2.get("prior_sessions") or [])
        self.assertTrue(r2["pane"].startswith("hc:") and r2["pane"] != "hc:tr1")  # a new reviewer terminal
        # Even though round1_t is in the same worktree and has score==2, neither state nor project session falls back to it.
        tasks = {t["id"]: t for t in self.dash_state()["tasks"]}
        self.assertNotIn("context_tokens", tasks["proj-r-review"])
        with self.assertRaises(SystemExit):
            project_view.cmd_project_session(argparse.Namespace(id="proj-r-review", before=None, after=None, limit=50), ctx=self.ctx)

        # 2. Legacy task with stale claude session while dispatched_with is agy: state omits context, project session refuses agy.
        self.save({"id": "proj-stale-agy", "title": "Stale Agy", "project": "proj", "repo": self.repo,
                   "worktree": wt, "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:tw5",
                   "worker": {"profile": "neon", "kind": "agy", "model": "gemini-4-neon-high"},
                   "session": {"kind": "claude", "id": round1_sid}, "created": now})
        tasks2 = {t["id"]: t for t in self.dash_state()["tasks"]}
        self.assertNotIn("context_tokens", tasks2["proj-stale-agy"])
        with self.assertRaises(SystemExit) as cm:
            project_view.cmd_project_session(argparse.Namespace(id="proj-stale-agy", before=None, after=None, limit=50), ctx=self.ctx)
        self.assertIn("agy", str(cm.exception).lower())

        # 3. Fresh reattach clears stale session so the new worker does not keep the old session id.
        self.save({"id": "proj-re", "title": "Re", "project": "proj", "repo": self.repo,
                   "worktree": wt, "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:gone",
                   "worker": {"kind": "claude", "model": "opus"},
                   "session": {"kind": "claude", "id": "dead-sid"}, "created": now})
        fresh = {"how": "fresh", "kind": "claude", "argv": ["claude"], "cwd": wt, "session": "", "prompt": "go"}
        # The plan is the one decision this step is about: a fresh start, whatever reattach_plan would pick.
        with mock.patch.object(Workers, "reattach_plan", lambda self, task, old_cwd="": dict(fresh)), \
                contextlib.redirect_stdout(io.StringIO()):
            workers_cmds.cmd_reattach(argparse.Namespace(id="proj-re"), ctx=self.ctx)
        re = self.load("proj-re")
        self.assertNotIn("session", re)
        self.assertIn("dead-sid", re.get("prior_sessions") or [])
        self.assertTrue(round1_t.is_file())

    def test_project_session_never_crosses_to_reviewer_or_other_session(self):
        sub_home = self.tmp / "iso-home"
        sub_ledger = self.tmp / "iso-ledger"
        wt = self.tmp / "wt-cross"
        wt.mkdir(parents=True)
        (sub_ledger / "tasks").mkdir(parents=True)
        folder = sub_home / ".claude" / "projects" / pm_sessions.claude_folder(wt)
        folder.mkdir(parents=True)
        # A Claude reviewer transcript in `wt` that mentions both `proj-agy` and `proj-no-own`,
        # and even quotes `update proj-agy` (reviewing an agy task) and `update proj-recorded`.
        (folder / "rev-claude.jsonl").write_text("\n".join([
            make_row("user", "review proj-agy (saw pm.py update proj-agy) and proj-no-own; "
                             "report via pm.py update proj-no-own-review --status done",
                     ts="2026-11-16T10:00:00.000Z", extra={"cwd": str(wt)}),
            make_row("assistant", [{"type": "text", "text": "reviewing"}],
                     ts="2026-11-16T10:00:01.000Z", usage={"input_tokens": 5000}),
        ]) + "\n", encoding="utf-8")
        (folder / "other-claude.jsonl").write_text("\n".join([
            make_row("user", "pm.py update proj-recorded --status review",
                     ts="2026-11-16T10:00:00.000Z", extra={"cwd": str(wt)}),
            make_row("assistant", [{"type": "text", "text": "wrong session"}],
                     ts="2026-11-16T10:00:01.000Z"),
        ]) + "\n", encoding="utf-8")
        # 1. agy task without `session`: must refuse via dispatched_with, never return rev-claude.
        (sub_ledger / "tasks" / "proj-agy.json").write_text(json.dumps({
            "id": "proj-agy", "title": "Agy", "project": "proj", "repo": self.repo, "worktree": str(wt),
            "status": "in_progress", "created": "2026-11-16 09:50",
            "worker": {"profile": "neon", "kind": "agy", "model": "gemini-4-neon-high"},
        }))
        # 2. Claude task with recorded session id whose file is missing: must NOT fall back to other-claude.
        (sub_ledger / "tasks" / "proj-recorded.json").write_text(json.dumps({
            "id": "proj-recorded", "title": "Missing file", "project": "proj", "repo": self.repo, "worktree": str(wt),
            "status": "in_progress", "created": "2026-11-16 09:50",
            "session": {"kind": "claude", "id": "00000000-0000-4000-8000-000000000000"},
        }))
        # 3. Claude task without `session` where only a score-1 reviewer mention exists: must refuse.
        (sub_ledger / "tasks" / "proj-no-own.json").write_text(json.dumps({
            "id": "proj-no-own", "title": "No own session", "project": "proj", "repo": self.repo, "worktree": str(wt),
            "status": "in_progress", "created": "2026-11-16 09:50",
            "worker": {"kind": "claude", "model": "opus"},
        }))
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sub_home), "USERPROFILE": str(sub_home),
               "PM_HOME": str(sub_ledger)}
        run = lambda tid: subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "pm.py"), "project", "session", tid],
            capture_output=True, text=True, env=env, timeout=20,
        )
        r_agy = run("proj-agy")
        self.assertNotEqual(r_agy.returncode, 0)
        self.assertIn("agy", r_agy.stderr.lower())

        r_rec = run("proj-recorded")
        self.assertNotEqual(r_rec.returncode, 0)
        self.assertIn("not found", r_rec.stderr.lower())

        r_mention = run("proj-no-own")
        self.assertNotEqual(r_mention.returncode, 0)
        self.assertIn("no unambiguous", r_mention.stderr.lower())

    def test_pm_claim_restart_same_pane_and_never_started_rollback(self):
        slug = project_slug(self.repo)
        rec_path = self.pms / f"{slug}.json"
        old_t = self.write_claude(self.repo, self.SID_PM, [
            make_row("assistant", [{"type": "text", "text": "old"}], usage={"input_tokens": 64000}),
        ])
        # Seed taken-in.json with old_t (as an offline PM before restart would leave behind).
        mark_dir = self.ctx.home.projects / slug
        mark_dir.mkdir(parents=True)
        (mark_dir / "taken-in.json").write_text(json.dumps({"files": {str(old_t): {"offset": 0, "at": ""}}}))
        rec_path.write_text(json.dumps({
            "name": pm_name(self.repo), "project": "proj", "repo": self.repo,
            "pane": "hc:t1", "runtime": "hc", "terminal": "t1", "agent": "claude",
            "agent_session": {"kind": "claude", "id": self.SID_PM, "path": str(old_t)},
        }))
        # 1. External claim on the SAME pane (e.g. new session started in hc:t1) clears stale agent_session
        # AND does not fall back to stale taken-in.json. No herdr agent is the PM (find_pm finds none).
        self.hc.server_running = True
        self.hc.terminals["t1"] = {"state": "live", "labels": {}}
        self.be("hc:other")
        with contextlib.redirect_stdout(io.StringIO()):
            manager_cmds.cmd_claim(argparse.Namespace(repo=self.repo, pane="hc:t1", kind="claude",
                                                      discord_channel=None, discord_users=None), ctx=self.ctx)
        self.assertIsNone(json.loads(rec_path.read_text())["agent_session"])
        self.assertNotIn("context_tokens", self.dash_state()["pms"][0])

        # 2. Seat startup fallback restores outgoing PM's agent_session from previous so its context_tokens survives.
        rec_path.write_text(json.dumps({
            "name": pm_name(self.repo), "project": "proj", "repo": self.repo,
            "pane": "hc:t1", "runtime": "hc", "terminal": "t1", "seat": True, "agent": "claude",
            "agent_session": None,
            "retired_sessions": [self.SID_PM],
            "previous": {"pane": "hc:t1", "terminal": "t1", "transcript": str(old_t),
                         "agent_session": {"kind": "claude", "id": self.SID_PM, "path": str(old_t)}},
        }))
        self.hc.terminals["t1"] = {"state": "live", "labels": {"pm": "proj", "pm.seat": "1"}}
        spec = build_fallback_spec(self.repo, {"kind": "claude", "previous": json.loads(rec_path.read_text())["previous"]},
                                   "exited with code 1", ctx=self.ctx)
        self.assertTrue(spec["is_fallback"])
        self.assertIn("--resume", spec["argv"])
        self.assertIn(self.SID_PM, spec["argv"])
        rolled = json.loads(rec_path.read_text())
        self.assertEqual(rolled["pane"], "hc:t1")
        self.assertEqual(rolled["agent_session"]["id"], self.SID_PM)
        self.assertNotIn("retired_sessions", rolled)
        self.assertEqual(self.dash_state()["pms"][0]["context_tokens"], 64000)


if __name__ == "__main__":
    unittest.main()
