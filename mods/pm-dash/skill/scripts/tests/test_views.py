"""What the PM and the desktop project view read (Stage 6a, wave 6a3).

Moved from test_pm.py's LightOutput (wait, show, status and diff stay short) and ProjectView (quick answers on a
blocked task, where the log is), and from test_pm_project.py (Store, Projects read model, `pm.py project events/log/
change`, dash_state counts, end_terminal) and test_pm_context.py (Store.documents/document, Projects.context/document,
`pm.py project context/file/library/memory`). Every test builds its own Context with make_ctx (its own temporary
ledger, FakeHc, a FakeTui, a FakeClock); the commands run through cli.main on that Context. The `pm.py` subprocess
checks stay subprocesses: they run the real launcher on the test's own ledger (PM_HOME), as before.
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
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import FakeChangeWaiter, FakeClock, FakeHc, FakeTui, make_ctx  # noqa: E402
from pmlib import cli, hooks, store as store_mod  # noqa: E402
from pmlib.caller import Caller  # noqa: E402
from pmlib.commands import ledger as ledger_cmd, workers as workers_cmd  # noqa: E402
from pmlib.context import StdOutput, now as wall_now  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.memory.candidates import CANDIDATE_GRACE  # noqa: E402
from pmlib.project import readmodel  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import ProjectRegistry  # noqa: E402
from pmlib.store import FileStore  # noqa: E402
from pmlib.views import state as state_view, status as status_view  # noqa: E402
from pmlib.workers.lifecycle import end_terminal_for  # noqa: E402

SCRIPT = SCRIPTS / "pm.py"


def run_pm(ctx, *argv):
    """`pm.py <argv>` on ctx: stdout and stderr in one text, as test_pm.py's run_pm gave them, an exit as
    "\\nexit: <code>"."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            cli.main(list(argv), ctx=ctx)
        except SystemExit as stop:
            out.write(f"\nexit: {stop.code}")
    return out.getvalue()


def quiet(fn, *args, **kw):
    """Call a command function, its printing dropped."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kw)


class QuietTui(FakeTui):
    """A herdr TUI that answers nothing (herdr not running, as the earlier tests' unpatched `pm.herdr` gave on a
    machine without it), except `agent list`: `listing` (what the earlier tests put in pm.agents)."""

    def __init__(self, listing=()):
        super().__init__()
        self.listing = [dict(x) for x in listing]

    def herdr(self, *args, session=None):
        self.calls.append((session, args))
        if tuple(args[:2]) == ("agent", "list"):
            return {"agents": [dict(x) for x in self.listing]}
        return None

    def agents(self, *, session=None):
        return [dict(x) for x in self.listing]

    def panes(self, *, session=None):
        return None

    def workspaces(self, *, session=None):
        return None


class SplitHc(FakeHc):
    """herdr-core whose `hc get` and `hc ls --all` answer from two tables, which may disagree (a PM terminal `get`
    still shows live while `ls --all` already lists it finished), as test_pm_project's scripted fake did; any other
    command answers {}."""

    def __init__(self, gets, listing):
        super().__init__()
        self.gets, self.listing = gets, listing

    def hc(self, *args, errors=False, env=None, timeout=60):
        self.calls.append(args)
        if args and args[0] == "get":
            return self.get_raw(args[1])
        if args[:1] == ("ls",):
            return self._ls_raw(all="--all" in args)
        return {}

    def get_raw(self, term, *, errors=False):
        row = self.gets.get(term)
        return json.loads(json.dumps(row)) if row is not None else None

    def _ls_raw(self, *, all=False):
        return {"terminals": [json.loads(json.dumps(t)) for t in self.listing
                              if all or t.get("state", "live") == "live"]}

    def kill(self, term, *, errors=False):
        self.calls.append(("kill", term))
        return {}

    def remove(self, term, *, errors=False):
        self.calls.append(("rm", term))
        return {}


def load(ctx, task_id):
    return Ledger(ctx).load(task_id).raw


def make_repo(base):
    """A throwaway repository with a main branch and a task branch dev/x that adds new.txt."""
    repo = Path(tempfile.mkdtemp(prefix="land-", dir=base)).resolve()  # a project of its own
    git = lambda *args: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                       check=True, capture_output=True, text=True).stdout
    git("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "init")
    git("checkout", "-q", "-b", "dev/x")
    (repo / "new.txt").write_text("hello\n")
    git("add", "new.txt")
    git("commit", "-q", "-m", "add new.txt")
    git("checkout", "-q", "main")
    return repo, git


class ViewCase(unittest.TestCase):
    """A temporary folder with a ledger (make_ctx) and real git, the way the PM's view commands see a project."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="pm-views-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.ctx = self.make()
        env = mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        env.start()
        self.addCleanup(env.stop)

    def make(self, *, hc=None, tui=None, pane=""):
        """A Context on this test's ledger: real git, stdout output, the given (or empty) hosts."""
        return make_ctx(self.base, pane=pane, hc=hc if hc is not None else FakeHc(),
                        tui=tui if tui is not None else QuietTui(), git=GitRepo(worktree_base=self.base / "wt"),
                        out=StdOutput())

    def folder(self, prefix=""):
        return str(Path(tempfile.mkdtemp(prefix=prefix or "tmp", dir=self.base)).resolve())

    def project_root(self, path):
        return self.ctx.git.project_root(path)


class LightOutput(ViewCase):
    """What the PM reads stays short: wait prints the whole report, show and status a summary, diff only numbers."""

    def test_wait_prints_a_long_report_whole(self):
        working = {"state": "live", "status": {"state": "working"}}
        hc = FakeHc({"t5": [working] * 5})
        ctx = self.make(hc=hc)
        Ledger(ctx).save({"id": "p-long", "title": "t", "project": "p", "repo": self.folder(),
                          "status": "in_progress", "owner": "pm", "base": "main", "pane": "hc:t5",
                          "created": ctx.clock.now()})
        long = "改动说明。" * 300  # 1500 characters, more than the old 600 cut
        looks = []

        def look(timeout):
            ctx.clock.advance(min(timeout, 5))
            looks.append(1)
            if len(looks) == 2:
                quiet(ledger_cmd.cmd_update, type("A", (), {"id": "p-long", "status": "review", "commit": "abc",
                                                             "keep": False, "note": long}), ctx=ctx)
        hc.change_waiter = lambda *a, **kw: FakeChangeWaiter(on_wait=look)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            workers_cmd.cmd_wait(type("A", (), {"id": "p-long", "timeout": 60}), ctx=ctx)
        self.assertEqual(len(looks), 2)
        self.assertIn(long, out.getvalue())
        self.assertNotIn(" …", out.getvalue())

    def test_show_is_short_and_json_is_the_whole_record(self):
        repo = self.project_root(self.folder())
        Ledger(self.ctx).save({"id": "s-show", "title": "精简", "project": "s", "repo": repo, "status": "review",
                               "owner": "pm", "base": "main", "branch": "dev/s", "commit": "c0ffee",
                               "created": self.ctx.clock.now(),
                               "log": [{"at": f"11-15 0{i}", "by": "hc:t1", "text": f"entry {i}"} for i in range(5)]})
        out = run_pm(self.ctx, "show", "s-show")
        self.assertIn("s-show  [review]  精简", out)
        self.assertIn("branch=dev/s", out)
        self.assertIn("commit=c0ffee", out)
        self.assertEqual([n for n in range(5) if f"entry {n}" in out], [2, 3, 4])  # the last three only
        self.assertNotIn("{", out)
        whole = json.loads(run_pm(self.ctx, "show", "s-show", "--json"))
        self.assertEqual((len(whole["log"]), whole["commit"], set(whole["live"])), (5, "c0ffee", {"ahead", "dirty"}))

    def run_status(self, *argv, panes=()):
        """`pm.py status` with only `panes` in the herdr TUI and no herdr-core."""
        return run_pm(self.make(hc=FakeHc(server_running=False), tui=QuietTui(panes)), "status", *argv)

    def save(self, tid, repo, project, status="in_progress"):
        Ledger(self.ctx).save({"id": tid, "title": tid, "project": project, "repo": repo, "status": status,
                               "owner": "pm", "base": "main", "created": self.ctx.clock.now()})

    def test_status_lists_this_project_unless_all(self):
        here, there = (self.project_root(self.folder(n)) for n in ("here-", "there-"))
        for repo, tid, status in ((here, "here-task", "in_progress"), (there, "there-task", "in_progress"),
                                  (here, "here-old", "done")):
            self.save(tid, repo, Path(repo).name, status)
        mine = self.run_status("--repo", here)
        every = self.run_status("--repo", here, "--all")
        nowhere = self.run_status("--repo", self.folder())  # no project there: everything, as before
        self.assertIn("here-task", mine)
        self.assertNotIn("there-task", mine)
        self.assertTrue(all(t in out for out in (every, nowhere) for t in ("here-task", "there-task")))
        # --all widens the projects only; closed tasks need --closed, as the old --all gave them
        self.assertFalse(any("here-old" in out for out in (mine, every, nowhere)))
        self.assertIn("here-old", self.run_status("--repo", here, "--closed"))
        self.assertNotIn("there-task", self.run_status("--repo", here, "--closed"))

    def test_status_in_the_hub_lists_every_project(self):
        """The hub is registered (pms/hub.json) for a folder in the ledger home: it is no project to narrow to."""
        home = self.ctx.home
        hub = home.root / "hub"
        hub.mkdir(parents=True, exist_ok=True)
        home.registrations.mkdir(parents=True, exist_ok=True)
        (home.registrations / "hub.json").write_text(json.dumps({"project": "hub", "repo": str(hub),
                                                                 "name": "pm-hub"}))
        repo = self.project_root(self.folder("proj-"))
        self.save("proj-task", repo, Path(repo).name)
        out = self.run_status("--repo", str(hub))
        (home.registrations / "hub.json").unlink()
        self.assertIn("proj-task", out)
        self.assertNotIn("(--all", out)
        # a registration whose repo is another folder (the same slug by chance) does not narrow status either
        other = Path(self.folder()) / Path(repo).name
        other.mkdir()
        (home.registrations / f"{project_slug(repo)}.json").write_text(json.dumps({"repo": repo}))
        self.assertIn("proj-task", self.run_status("--repo", str(other)))

    def test_status_lists_the_folders_under_this_project(self):
        """A PM of a plain folder (issues) owns the projects inside it (issues/site-a), as the board counts them;
        a sibling that only starts with its name does not belong to it."""
        here = Path(self.project_root(self.folder("nest-")))
        (here / "site-a").mkdir()
        sibling = Path(f"{here}-old")
        sibling.mkdir()
        elsewhere = self.project_root(self.folder())
        for repo, tid, project in ((here / "site-a", "nest-sub", "site-a"), (sibling, "nest-sibling", sibling.name),
                                   (elsewhere, "nest-named", "nestp")):
            self.save(tid, str(repo), project)
        home = self.ctx.home
        home.registrations.mkdir(parents=True, exist_ok=True)
        registration = home.registrations / f"{project_slug(here)}.json"
        registration.write_text(json.dumps({"project": "nestp", "repo": str(here), "name": "pm-nestp"}))
        mine = self.run_status("--repo", str(here))
        self.assertIn(self.ctx.config.tr(f"Tasks of {here.name}", f"{here.name} 的任务"), mine)
        self.assertIn("nest-sub", mine)
        self.assertIn("nest-named", mine)  # elsewhere, but the board gives it to this PM by its project name
        self.assertNotIn("nest-sibling", mine)

    def test_status_unregistered_work_under_this_project(self):
        here = Path(self.project_root(self.folder("scope-")))
        self.save("scope-task", str(here), here.name)
        inner, outer = here / "inner", Path(self.folder("outer-")).resolve()
        for repo in (inner, outer):
            repo.mkdir(exist_ok=True)
            run = lambda *args: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                                                *args], check=True, capture_output=True)
            run("init", "-q", "-b", "main")
            (repo / "a.txt").write_text("one\n")
            run("add", "a.txt")
            run("commit", "-q", "-m", "init")
            (repo / "a.txt").write_text("two\n")  # uncommitted: unregistered work
        panes = [{"pane_id": f"w-{repo.name[:5]}", "cwd": str(repo), "agent_status": "idle", "agent": "claude",
                  "name": repo.name, "workspace_id": ""} for repo in (inner, outer)]
        mine = self.run_status("--repo", str(here), panes=panes)
        every = self.run_status("--repo", str(here), "--all", panes=panes)
        self.assertIn("pane w-inner", mine)
        self.assertNotIn("pane w-outer", mine)
        self.assertTrue("pane w-inner" in every and "pane w-outer" in every)

    def diff_task(self, repo, tid, branch, worktree=None):
        Ledger(self.ctx).save({"id": tid, "title": "d", "project": repo.name, "repo": str(repo), "status": "review",
                               "owner": "pm", "base": "main", "branch": branch, "created": self.ctx.clock.now(),
                               **({"worktree": worktree} if worktree else {})})
        return run_pm(self.ctx, "diff", tid)

    def test_diff_prints_the_stat_and_line_totals(self):
        repo, git = make_repo(self.base)
        git("checkout", "-q", "dev/x")
        (repo / "a.txt").write_text("one\ntwo\nthree\n")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text("x = 1\ny = 2\n")
        (repo / "evidence" / "截图").mkdir(parents=True)
        (repo / "evidence" / "截图" / "说明.md").write_text("看过了\n")
        git("add", "a.txt", "tests/test_a.py", "evidence")
        git("rm", "-q", "new.txt")  # added and deleted on the branch: not in the diff against main
        git("commit", "-q", "-m", "more")
        git("checkout", "-q", "main")
        out = self.diff_task(repo, "d-diff", "dev/x", worktree=str(repo / "gone"))  # its worktree was removed
        self.assertIn("git diff --stat main...dev/x", out)
        self.assertIn("evidence/截图/说明.md", out)  # the name as it is, not quoted escapes
        self.assertIn("total: 3 files, +5 -0 (5 lines)", out)
        self.assertIn("source (without tests and evidence): 1 files, +2 -0 (2 lines)", out)
        self.assertIn("worktree gone", out)
        self.assertIn("small (§4): yes", out)
        self.assertNotIn("+two", out)  # no diff text
        self.assertNotIn("deleted:", out)
        self.assertNotIn("exit:", out)

    def test_diff_says_what_is_not_small(self):
        repo, git = make_repo(self.base)
        git("checkout", "-q", "-b", "dev/y")
        git("rm", "-q", "a.txt")
        (repo / "mods" / "pm-x").mkdir(parents=True)
        (repo / "mods" / "pm-x" / "main.js").write_text("view();\n")
        (repo / "icon.png").write_bytes(b"\x89PNG\x00\x01")
        git("add", "mods", "icon.png")
        git("commit", "-q", "-m", "ui")
        git("checkout", "-q", "-b", "dev/big", "main")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_big.py").write_text("x = 1\n" * 160)  # tests only, but past the total cap
        git("add", "tests")
        git("commit", "-q", "-m", "big")
        git("checkout", "-q", "-b", "dev/swift", "main")
        for path, text in (("Sources/App/Panel.swift", "import Foundation\nimport SwiftUI\n"),
                           ("Sources/Core/Model.swift", "import Foundation\nstruct Model {}\n")):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text)
        git("add", "Sources")
        git("commit", "-q", "-m", "swift")
        git("checkout", "-q", "main")
        out = self.diff_task(repo, "d-swift", "dev/swift")  # a SwiftUI view shows on screen; a model does not
        self.assertIn("UI (visual result): Sources/App/Panel.swift\n", out)
        self.assertIn("small (§4): no, UI files", out)
        out = self.diff_task(repo, "d-ui", "dev/y")
        self.assertIn("deleted: a.txt", out)
        self.assertIn("binary: icon.png", out)
        self.assertIn("UI (visual result): icon.png, mods/pm-x/main.js", out)
        self.assertNotIn("worktree gone", out)  # it never had one
        self.assertIn("small (§4): no, deletes files; binary files; UI files", out)
        out = self.diff_task(repo, "d-big", "dev/big")
        self.assertIn("small (§4): no, 160 lines in all > 150", out)
        ui_file, side_file = status_view.ui_file, status_view.side_file
        self.assertEqual((ui_file("mods/pm-dash/skill/scripts/pm.py"), ui_file("mods/pm-x/model.test.mjs"),
                          ui_file("mods/pm-dash/skill/assets/dash.html")), (False, False, True))
        self.assertEqual((ui_file("App/Base.lproj/Main.storyboard"), ui_file("App/Assets.xcassets/a/Contents.json"),
                          ui_file("App/Remote.swift", "import AppKit\n")), (True, True, False))
        self.assertFalse(ui_file("Tests/AppTests/PanelTests.swift", "import SwiftUI\n"))  # a test, not a view
        self.assertTrue(side_file("Tests/AppTests/PanelTests.swift"))


class ProjectView(ViewCase):
    """What the desktop project view reads: quick answers on a blocked task, and where the log is."""

    def test_a_question_of_its_own_is_a_blocked_entry_with_quick_answers(self):
        repo = self.project_root(self.folder())
        blank = {f: None for f in ("owner", "workspace", "pane", "agent", "branch", "worktree", "base", "brief", "slug")}
        args = type("A", (), {**blank, "title": "推到 GitHub 并装到 MBP", "repo": repo, "status": "blocked",
                              "note": "这一轮的改动还没推，现在做吗？", "option": ["推并装", " 先不 "]})
        task_id = quiet(ledger_cmd.cmd_new, args, ctx=self.ctx)
        self.assertEqual(load(self.ctx, task_id)["options"], ["推并装", "先不"])
        event = Conversation(self.ctx, repo).events()[-1]
        self.assertEqual((event["status"], event["text"], event["options"]),
                         ("blocked", "这一轮的改动还没推，现在做吗？", ["推并装", "先不"]))

    def update(self, **kw):
        """`pm.py update` of the question task (its arguments as cmd_update gets them), output dropped."""
        args = type("A", (), {"id": self.tid, "note": None, "keep": False, "option": None, **kw})
        quiet(ledger_cmd.cmd_update, args, ctx=self.ctx)

    def question_task(self, title):
        repo = self.project_root(self.folder())
        name = Path(repo).name
        self.tid = f"{name}-q"
        Ledger(self.ctx).save({"id": self.tid, "title": title, "project": name, "repo": repo, "status": "in_progress",
                               "owner": "pm", "base": "main", "created": self.ctx.clock.now()})
        return repo

    def log(self, repo):
        return Conversation(self.ctx, repo).events()

    def test_options_are_kept_on_the_task_and_its_conversation_event(self):
        repo = self.question_task("去手")
        self.update(status="blocked", note="技能改动也交给线程吗？", option=["交给线程", " 仍由 PM 改 ", ""])
        self.assertEqual(load(self.ctx, self.tid)["options"], ["交给线程", "仍由 PM 改"])
        event = self.log(repo)[-1]
        self.assertEqual((event["type"], event["status"], event["options"]), ("thread", "blocked", ["交给线程", "仍由 PM 改"]))
        self.assertEqual(event["text"], "status=blocked; 技能改动也交给线程吗？")
        self.update(note="still waiting")                                    # a note alone keeps the question's answers
        self.assertEqual(load(self.ctx, self.tid)["options"], ["交给线程", "仍由 PM 改"])
        self.update(status="in_progress", note="用户选了交给线程")             # answered: they go
        self.assertNotIn("options", load(self.ctx, self.tid))
        self.assertNotIn("options", self.log(repo)[-1])
        self.update(option=["是", "否"])                                     # answers alone still reach the log
        self.assertEqual(self.log(repo)[-1]["options"], ["是", "否"])
        self.assertNotIn("option_notes", self.log(repo)[-1])                # plain answers carry nothing more
        self.assertNotIn("recommended", self.log(repo)[-1])

    def test_an_answer_can_say_why_and_the_first_can_be_recommended(self):
        repo = self.question_task("限流")
        self.update(status="blocked", note="计数放在哪？", recommend=True, option=["Redis", "git log | head", " 先不做 "],
                    why={0: " 一份共享的计数，用你已经在跑的 Redis ", 1: "每个实例各数各的"})
        task, event = load(self.ctx, self.tid), self.log(repo)[-1]
        for kept in (task, event):                                         # an answer is kept as written, `|` included
            self.assertEqual(kept["options"], ["Redis", "git log | head", "先不做"])
            self.assertEqual(kept["option_notes"], ["一份共享的计数，用你已经在跑的 Redis", "每个实例各数各的", ""])
            self.assertIs(kept["recommended"], True)
        self.update(status="in_progress", note="用户选了 Redis")             # answered: all of it goes
        task = load(self.ctx, self.tid)
        for gone in ("options", "option_notes", "recommended"):
            self.assertNotIn(gone, task)
            self.assertNotIn(gone, self.log(repo)[-1])
        # A recommendation or a reason without its answer is an error, and nothing is written.
        before = (load(self.ctx, self.tid), len(self.log(repo)))
        for bad in (dict(recommend=True), dict(recommend=True, option=["", "B"]), dict(option=["", "B"], why={0: "why"})):
            with self.assertRaises(SystemExit):
                self.update(status="blocked", note="?", **bad)
        self.assertEqual((load(self.ctx, self.tid), len(self.log(repo))), before)

    def test_why_explains_the_option_before_it(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--option", action="append")
        parser.add_argument("--why", action=ledger_cmd.Why)
        a = parser.parse_args(["--option", "A", "--why", "because", "--option", "B", "--option", "C", "--why", "c"])
        self.assertEqual((a.option, a.why), (["A", "B", "C"], {0: "because", 2: "c"}))
        self.assertIsNone(parser.parse_args(["--option", "A"]).why)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            parser.parse_args(["--why", "no answer before it", "--option", "A"])

    def test_state_names_each_pms_conversation_log_and_worktree_folder(self):
        repo = self.project_root(self.folder())
        home = self.ctx.home
        home.registrations.mkdir(parents=True, exist_ok=True)
        (home.registrations / "view.json").write_text(json.dumps({"name": "pm-view", "pane": "hc:t7", "project": "view",
                                                                  "repo": repo}))
        (home.registrations / "norepo.json").write_text(json.dumps({"name": "pm-norepo", "pane": ""}))
        state_ctx = self.make(tui=QuietTui([]))
        pms = {p["name"]: p for p in state_view.dash_state(ctx=state_ctx)["pms"]}
        path = Path(pms["pm-view"]["conversation"])
        self.assertEqual(path, home.projects / project_slug(repo) / "conversation.jsonl")
        self.assertFalse(path.parent.exists())  # reading state creates nothing
        self.assertEqual(pms["pm-norepo"]["conversation"], "")
        # Where dispatch makes this project's worktrees: the project view lists the sessions inside.
        self.assertEqual(Path(pms["pm-view"]["worktrees"]), self.base / "wt" / Path(repo).name)
        self.assertEqual(pms["pm-norepo"]["worktrees"], "")


class LedgerCase(unittest.TestCase):
    """A Context on a temporary ledger whose pms/, tasks/ and projects/ exist (test_pm_project's and test_pm_context's
    setUp), with its FileStore as ctx.store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = make_ctx(self.tmp.name, out=StdOutput())
        home = self.ctx.home
        self.root, self.pms, self.tasks, self.projects = home.root, home.registrations, home.tasks, home.projects
        for d in (self.pms, self.tasks, self.projects):
            d.mkdir(parents=True)
        self.store = self.ctx.store

    def write_reg(self, slug, **fields):
        data = {"name": f"pm-{slug}", "project": slug, "repo": f"/work/{slug}", **fields}
        (self.pms / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def cli_env(self):
        """The environment of a `pm.py` subprocess on this test's ledger."""
        env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "HC_TERMINAL_ID")}
        env["PM_HOME"] = str(self.root)
        return env


class StoreAndProjectTests(LedgerCase):
    """pm_store (pmlib.store) and pm_project (pmlib.project.readmodel) over a test's own FileStore, and `pm.py
    project events/log/change`. Moved from test_pm_project.py."""

    def write_task(self, task_id, **fields):
        data = {"id": task_id, "title": task_id, "project": "demo", "repo": "/work/demo",
                "status": "in_progress", "updated": "2026-11-20 10:00", "log": [], **fields}
        (self.tasks / f"{task_id}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def append_raw(self, slug, text):
        folder = self.projects / slug
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "conversation.jsonl", "ab") as f:
            f.write(text.encode("utf-8") if isinstance(text, str) else text)

    def test_pm_store_never_imports_pm_or_fixes_paths_at_import_time(self):
        # Verify in a clean subprocess that importing pm_store and pm_project does not load `pm`
        # and does not touch PM_HOME until methods are called.
        code = (
            "import os, sys; os.environ['PM_HOME'] = '/nonexistent-at-import'; "
            "import pm_store, pm_project; "
            "assert 'pm' not in sys.modules, 'pm_store imported pm'"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(SCRIPTS),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        # A FileStore reads the folders of its own Home, at call time; the legacy STORE reads whichever ledger the
        # process's context names when it is called (legacy_ctx.bound points it at a Context's).
        self.write_reg("alpha")
        self.assertEqual([r["name"] for r in self.store.registrations()], ["pm-alpha"])
        other = make_ctx(Path(self.tmp.name) / "other")
        other.home.registrations.mkdir(parents=True)
        (other.home.registrations / "beta.json").write_text(json.dumps({"name": "pm-beta", "project": "beta",
                                                                         "repo": "/work/beta"}))
        self.assertEqual([r["name"] for r in other.store.registrations()], ["pm-beta"])
        self.assertEqual(other.store.registration("beta")["project"], "beta")
        self.assertIsNone(other.store.registration("alpha"))
        self.assertEqual([r["name"] for r in self.ctx.store.registrations()], ["pm-alpha"])
        self.assertEqual([r["name"] for r in other.store.registrations()], ["pm-beta"])
        self.assertEqual(other.store.registration("beta")["project"], "beta")

    def test_store_registrations_and_tasks_follow_pm_ownership_and_skip_damaged_files(self):
        self.write_reg("demo", repo="/work/demo", project="Demo")
        self.write_reg("issues", repo="/work/issues", project="issues")
        (self.pms / ".demo.json.tmp").write_text("{}")
        (self.pms / "broken.json").write_text("{not json")
        (self.pms / "array.json").write_text("[1, 2]")

        self.write_task("demo-1", repo="/work/demo", updated="2026-11-20 10:01")
        self.write_task("demo-renamed", repo="/old/path", project="Demo", updated="2026-11-20 10:03")
        self.write_task("issues-sub", repo="/work/issues/site-a", project="site-a", updated="2026-11-20 10:02")
        self.write_task("other-1", repo="/somewhere/else", project="else", updated="2026-11-20 10:04")
        (self.tasks / ".demo-1.json.tmp").write_text("{}")
        (self.tasks / "corrupt.json").write_text("null")

        store = self.store
        self.assertEqual([r["name"] for r in store.registrations()], ["pm-demo", "pm-issues"])
        self.assertEqual(store.registration("demo")["project"], "Demo")
        self.assertIsNone(store.registration("../demo"))
        self.assertIsNone(store.registration("missing"))

        self.assertEqual([t["id"] for t in store.tasks()], ["other-1", "demo-renamed", "issues-sub", "demo-1"])
        self.assertEqual([t["id"] for t in store.tasks("demo")], ["demo-renamed", "demo-1"])
        self.assertEqual([t["id"] for t in store.tasks("issues")], ["issues-sub"])
        self.assertEqual(store.task("demo-1")["id"], "demo-1")
        self.assertIsNone(store.task("../demo-1"))
        self.assertIsNone(store.task(".demo-1"))
        self.assertIsNone(store.task("no-such-task"))

    def test_events_window_pages_backward_by_byte_offset_and_ignores_non_events_and_torn_lines(self):
        # Mirrors app:service/window_test.go TestAWindowGivesTheLastEventsAndTheOnesBefore,
        # plus U+2028 inside JSON text (which splitlines() would wrongly split).
        self.write_reg("demo")
        self.append_raw(
            "demo",
            '{"type": "user", "text": "1 line"}\n'
            'not an event\n'
            '{"type": "pm", "text": "2"}\n'
            '{"type": "user", "text": "3"}\n'
            '[]\n'
            '{"type": "pm", "text": "4"}\n'
            '{"type": "user", "text": "5"}\n'
            '{"type": "pm", "text": "半',
        )
        projects = readmodel.Projects(self.store)
        whole = projects.events("demo", limit=50)
        self.assertEqual([e["text"] for e in whole["events"]], ["1 line", "2", "3", "4", "5"])
        self.assertEqual((whole["from"], whole["earlier"]), (0, False))

        last = projects.events("demo", limit=2)
        self.assertEqual([e["text"] for e in last["events"]], ["4", "5"])
        self.assertEqual(last["offset"], whole["offset"])
        self.assertTrue(last["earlier"])
        self.assertEqual(last["from"], whole["events"][2]["offset"] + len(b"[]\n"))

        mid = projects.events("demo", before=last["from"], limit=2)
        self.assertEqual([e["text"] for e in mid["events"]], ["2", "3"])
        self.assertEqual(mid["offset"], last["from"])
        self.assertTrue(mid["earlier"])

        first = projects.events("demo", before=mid["from"], limit=5)
        self.assertEqual([e["text"] for e in first["events"]], ["1 line"])
        self.assertEqual((first["from"], first["offset"], first["earlier"]), (0, mid["from"], False))

        # Validation of bad parameters and replaced logs.
        for bad in (
            lambda: projects.events("demo", limit=0),
            lambda: projects.events("demo", limit=2001),
            lambda: projects.events("demo", before=-1),
            lambda: projects.events("demo", before=last["from"] + 1, limit=2),
            lambda: projects.events("demo", before=10, after=10, limit=2),
        ):
            with self.assertRaises(ValueError):
                bad()
        with self.assertRaises(store_mod.LogReplacedError):
            projects.events("demo", before=99_999_999, limit=2)
        with self.assertRaises(readmodel.NotFoundError):
            projects.events("no-such-project", limit=10)

        # A registered project with no conversation.jsonl yet gives an empty window, not NotFoundError;
        # underscore-prefixed slugs (which pm.py's project_slug produces for `_sandbox`) are accepted too.
        self.write_reg("quiet")
        self.assertEqual(projects.events("quiet", limit=200),
                         {"events": [], "from": 0, "offset": 0, "earlier": False})
        self.write_reg("_sandbox", repo="/work/_sandbox", project="_sandbox")
        self.append_raw("_sandbox", '{"type": "user", "text": "underscore"}\n')
        self.assertEqual([e["text"] for e in projects.events("_sandbox", limit=10)["events"]], ["underscore"])
        self.assertEqual(self.store.registration("_sandbox")["project"], "_sandbox")

    def test_windows_across_many_blocks_and_incremental_after_reconstruct_the_whole_log_once(self):
        self.write_reg("demo")
        chunks = []
        for i in range(2500):
            chunks.append(json.dumps({"type": "user", "text": f"{i} {'字' * (60 + i % 40)}"}, ensure_ascii=False) + "\n")
            if i % 500 == 0:
                chunks.append("not an event\n")
        self.append_raw("demo", "".join(chunks))

        projects = readmodel.Projects(self.store)
        w = projects.events("demo", limit=700)
        self.assertEqual(len(w["events"]), 700)
        self.assertTrue(w["earlier"])
        collected = list(w["events"])
        while w["earlier"]:
            earlier = projects.events("demo", before=w["from"], limit=600)
            self.assertGreater(len(earlier["events"]), 0)
            self.assertEqual(earlier["offset"], w["from"])
            collected = earlier["events"] + collected
            w = earlier
        self.assertEqual(w["from"], 0)
        self.assertEqual([e["text"].split()[0] for e in collected], [str(i) for i in range(2500)])

        # Concurrent appends after the end offset, including finishing a half-written line.
        end_offset = collected[-1]["offset"]
        self.assertEqual(projects.events("demo", after=end_offset, limit=200)["events"], [])
        self.append_raw("demo", '{"type": "pm", "text": "half')
        self.assertEqual(projects.events("demo", after=end_offset, limit=200)["events"], [])
        self.append_raw("demo", '-done"}\n{"type": "user", "text": "next"}\n')
        delta = projects.events("demo", after=end_offset, limit=1)
        self.assertEqual([e["text"] for e in delta["events"]], ["half-done"])
        self.assertTrue(delta["more"])
        self.assertFalse(delta["reset"])
        delta2 = projects.events("demo", after=delta["offset"], limit=10)
        self.assertEqual([e["text"] for e in delta2["events"]], ["next"])
        self.assertFalse(delta2["more"])

        # Replacing the log with a shorter file triggers reset=True on --after instead of losing sync.
        (self.projects / "demo/conversation.jsonl").write_text('{"type": "user", "text": "fresh"}\n', encoding="utf-8")
        reset = projects.events("demo", after=delta2["offset"], limit=200)
        self.assertTrue(reset["reset"])
        self.assertEqual([e["text"] for e in reset["events"]], ["fresh"])
        self.assertFalse(reset["earlier"])

    def test_large_conversation_log_reads_only_tail_blocks_not_the_whole_file(self):
        self.write_reg("huge")
        line = (json.dumps({"type": "user", "text": "x" * 200}) + "\n").encode("utf-8")
        # ~5 MB log (~21,000 events).
        log_path = self.projects / "huge/conversation.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_bytes(line * 21_000)
        total_size = log_path.stat().st_size
        self.assertGreater(total_size, 4_500_000)

        bytes_read = 0
        real_open = open

        class CountingReader:
            def __init__(self, raw):
                self._raw = raw

            def read(self, n=-1):
                nonlocal bytes_read
                data = self._raw.read(n)
                bytes_read += len(data)
                return data

            def __getattr__(self, name):
                return getattr(self._raw, name)

            def __enter__(self):
                self._raw.__enter__()
                return self

            def __exit__(self, *args):
                return self._raw.__exit__(*args)

        def tracked_open(path, mode="r", *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            return CountingReader(handle) if Path(path) == log_path and "b" in mode else handle

        projects = readmodel.Projects(self.store)
        with mock.patch("builtins.open", side_effect=tracked_open):
            w = projects.events("huge", limit=10)
            earlier = projects.events("huge", before=w["from"], limit=10)
        self.assertEqual(len(w["events"]), 10)
        self.assertTrue(w["earlier"])
        self.assertEqual(len(earlier["events"]), 10)
        self.assertTrue(earlier["earlier"])
        # Both calls combined read only a few 64 KiB blocks, nowhere near 5 MB.
        self.assertGreater(bytes_read, 0)  # the counter saw the reads (it would pass vacuously otherwise)
        self.assertLess(bytes_read, 256 << 10)

    def test_thread_log_pages_by_entry_index_whole_and_survives_concurrent_appends(self):
        long_note = "status=review, commit=abc1234; " + ("交接说明。" * 120)
        entries = [{"at": f"2026-11-20 10:{i % 60:02d}", "by": "hc:t1", "text": f"第 {i} 条"} for i in range(65)]
        entries.append({"at": "2026-11-20 11:05", "by": "hc:t2", "text": long_note})
        self.write_task("dudu-fix", status="review", log=entries)

        projects = readmodel.Projects(self.store)
        newest = projects.thread_log("dudu-fix", limit=60)
        self.assertEqual((newest["total"], newest["earlier"], len(newest["entries"]), newest["entries"][0]["n"]),
                         (66, 6, 60, 6))
        self.assertEqual(newest["entries"][-1]["text"], long_note)

        # Append two more entries to the task before fetching the earlier page: entry indices 0..5 do not shift!
        entries.extend([
            {"at": "2026-11-20 11:06", "by": "pm", "text": "status=merged"},
            {"at": "2026-11-20 11:06", "by": "pm", "text": "retired: removed nothing"},
        ])
        self.write_task("dudu-fix", status="merged", log=entries)
        older = projects.thread_log("dudu-fix", before=newest["earlier"], limit=60)
        self.assertEqual(([e["n"] for e in older["entries"]], older["earlier"], older["total"]),
                         ([0, 1, 2, 3, 4, 5], 0, 68))
        self.assertEqual(older["entries"][5]["text"], "第 5 条")

        with self.assertRaises(readmodel.NotFoundError):
            projects.thread_log("no-such-task")
        for bad in (lambda: projects.thread_log("dudu-fix", before=-1), lambda: projects.thread_log("dudu-fix", limit=0)):
            with self.assertRaises(ValueError):
                bad()

    def test_cli_project_events_and_log_and_missing_pm_store_error(self):
        self.write_reg("demo", project="Demo")
        (self.pms / "corrupt.json").write_text("{not valid json", encoding="utf-8")
        for i in range(5):
            self.append_raw("demo", json.dumps({"at": f"2026-11-20 12:00:0{i}", "type": "user", "text": f"hi {i}"}) + "\n")
        self.write_task("demo-a", log=[{"at": f"2026-11-20 12:0{i}", "by": "user", "text": f"step {i}"} for i in range(4)])

        env = self.cli_env()
        r1 = subprocess.run([sys.executable, str(SCRIPT), "project", "events", "Demo", "--limit", "3"],
                            env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        w1 = json.loads(r1.stdout)
        self.assertEqual(([e["text"] for e in w1["events"]], w1["earlier"]), (["hi 2", "hi 3", "hi 4"], True))
        self.assertEqual(ProjectRegistry(self.ctx).resolve_project_slug("pm-demo"), "demo")

        r2 = subprocess.run([sys.executable, str(SCRIPT), "--home", str(self.root), "project", "events", "demo",
                             "--before", str(w1["from"]), "--limit", "3"],
                            env={**env, "PM_HOME": str(Path(self.tmp.name) / "unused")},
                            capture_output=True, text=True, timeout=30)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        w2 = json.loads(r2.stdout)
        self.assertEqual(([e["text"] for e in w2["events"]], w2["earlier"]), (["hi 0", "hi 1"], False))

        r3 = subprocess.run([sys.executable, str(SCRIPT), "project", "log", "demo-a", "--before", "3", "--limit", "2"],
                            env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r3.returncode, 0, r3.stderr)
        p3 = json.loads(r3.stdout)
        self.assertEqual(([e["text"] for e in p3["entries"]], p3["earlier"], p3["total"]),
                         (["step 1", "step 2"], 1, 4))

        missing_proj = subprocess.run([sys.executable, str(SCRIPT), "project", "events", "nope"],
                                      env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(missing_proj.returncode, 0)
        self.assertIn("no project nope", missing_proj.stderr)
        self.assertNotIn("JSONDecodeError", missing_proj.stderr)

        # Copying pm.py alone without pm_store.py fails with one clear error line.
        alone = Path(self.tmp.name) / "alone"
        alone.mkdir()
        shutil.copy2(SCRIPT, alone / "pm.py")
        clean_env = {k: v for k, v in env.items() if k != "PYTHONPATH"}
        broken = subprocess.run([sys.executable, str(alone / "pm.py"), "state"],
                                env=clean_env, cwd=str(alone), capture_output=True, text=True, timeout=30)
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn("install or copy the whole skills/pm folder", broken.stderr)  # pm.py alone: no pmlib/ either
        self.assertNotIn("Traceback", broken.stderr)
        # pm.py with its package (pmlib/, where its code is since it became a launcher) but without pmlib/store.py.
        shutil.copytree(SCRIPTS / "pmlib", alone / "pmlib", ignore=shutil.ignore_patterns("__pycache__"))
        (alone / "pmlib" / "store.py").unlink()
        broken = subprocess.run([sys.executable, str(alone / "pm.py"), "state"],
                                env=clean_env, cwd=str(alone), capture_output=True, text=True, timeout=30)
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn("pmlib.store", broken.stderr)
        self.assertIn("install or copy the whole skills/pm folder", broken.stderr)
        self.assertNotIn("Traceback", broken.stderr)

    def test_pmpy_reference_sample_ledger_matches_spec(self):
        # Reference sample from app:service/testdata/pmpy (tasks + conversation.jsonl written by real pm.py).
        sample_lines = [
            {"at": "2026-11-20 11:19:16", "type": "thread", "task": "demo-pick-a-database", "title": "Pick a database", "status": "in_progress", "by": "user", "text": "registered (in_progress)", "source": "session"},
            {"at": "2026-11-20 11:19:16", "type": "thread", "task": "demo-pick-a-database", "title": "Pick a database", "status": "blocked", "by": "user", "text": "status=blocked; Postgres or SQLite for the cache?", "options": ["Postgres", "SQLite"], "option_notes": ["scales past one machine", ""], "recommended": True, "source": "session"},
            {"at": "2026-11-20 11:19:17", "type": "user", "text": "【Pick a database】SQLite"},
            {"at": "2026-11-20 11:19:19", "type": "thread", "task": "demo-pick-a-database", "title": "Pick a database", "status": "blocked", "by": "user", "text": "status=blocked; SQLite needs WAL mode; turn it on?", "options": ["Yes", "No"], "source": "session"},
            {"at": "2026-11-20 11:19:19", "type": "thread", "task": "demo-pick-a-database", "title": "Pick a database", "status": "blocked", "by": "user", "text": "read the WAL docs"},
            {"at": "2026-11-20 11:19:19", "type": "thread", "task": "demo-name-the-release", "title": "Name the release", "status": "blocked", "by": "user", "text": "What do we call 1.0?", "options": ["Aurora", "Borealis"], "source": "session"},
            {"at": "2026-11-20 11:19:20", "type": "user", "text": "【Name the release】Aurora"},
            {"at": "2026-11-20 11:19:20", "type": "thread", "task": "demo-fix-login", "title": "Fix login", "status": "in_progress", "by": "user", "text": "registered (in_progress)", "source": "session"},
            {"at": "2026-11-20 11:19:20", "type": "thread", "task": "demo-fix-login", "title": "Fix login", "status": "blocked", "by": "user", "text": "status=blocked; Need the staging API key", "source": "session"},
        ]
        self.append_raw("demo", "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in sample_lines))
        self.write_task(
            "demo-pick-a-database", title="Pick a database", status="blocked", options=["Yes", "No"],
            log=[
                {"at": "2026-11-20 11:19", "by": "user", "text": "registered (in_progress)"},
                {"at": "2026-11-20 11:19", "by": "user", "text": "status=blocked; Postgres or SQLite for the cache?"},
                {"at": "2026-11-20 11:19", "by": "user", "text": "status=blocked; SQLite needs WAL mode; turn it on?"},
                {"at": "2026-11-20 11:19", "by": "user", "text": "read the WAL docs"},
            ],
        )
        self.write_task(
            "demo-name-the-release", title="Name the release", status="blocked", options=["Aurora", "Borealis"],
            log=[{"at": "2026-11-20 11:19", "by": "user", "text": "What do we call 1.0?"}],
        )
        self.write_task(
            "demo-fix-login", title="Fix login", status="blocked",
            log=[
                {"at": "2026-11-20 11:19", "by": "user", "text": "registered (in_progress)"},
                {"at": "2026-11-20 11:19", "by": "user", "text": "status=blocked; Need the staging API key"},
            ],
        )

        projects = readmodel.Projects(self.store)
        # Even without a pms/demo.json registration, projects/demo and tasks belong to slug "demo".
        self.assertEqual(len(self.store.tasks("demo")), 3)
        w2 = projects.events("demo", limit=4)
        w1 = projects.events("demo", before=w2["from"], limit=10)
        self.assertFalse(w1["earlier"])
        self.assertEqual([e["text"] for e in w1["events"] + w2["events"]], [e["text"] for e in sample_lines])

        p_tail = projects.thread_log("demo-pick-a-database", limit=2)
        p_head = projects.thread_log("demo-pick-a-database", before=p_tail["earlier"], limit=2)
        self.assertEqual((p_head["earlier"], p_tail["earlier"], p_tail["total"]), (0, 2, 4))
        self.assertEqual([e["n"] for e in p_head["entries"] + p_tail["entries"]], [0, 1, 2, 3])

    def test_folded_status_and_review_map_edge_cases(self):
        folded_status, review_map = readmodel.folded_status, readmodel.review_map
        # No review -> own status and answered flag.
        t_ip = {"id": "a", "status": "in_progress"}
        t_blk = {"id": "b", "status": "blocked"}
        t_psd = {"id": "p", "status": "paused"}
        t_done = {"id": "d", "status": "done"}
        self.assertEqual(folded_status(t_ip, {}), ("in_progress", False))
        self.assertEqual(folded_status(t_blk, {}, {"b"}), ("blocked", True))

        # Open review folds into an open task: blocked review -> ("blocked", r answered), else ("review", False).
        r_ip = {"id": "a-review", "review_of": "a", "status": "in_progress"}
        r_blk = {"id": "a-review", "review_of": "a", "status": "blocked"}
        r_done = {"id": "a-review", "review_of": "a", "status": "done"}
        r_psd = {"id": "a-review", "review_of": "a", "status": "paused"}
        self.assertEqual(folded_status(t_ip, review_map([t_ip, r_ip])), ("review", False))
        self.assertEqual(folded_status(t_ip, review_map([t_ip, r_blk])), ("blocked", False))
        self.assertEqual(folded_status(t_ip, review_map([t_ip, r_blk]), {"a-review"}), ("blocked", True))
        # Closed or paused review leaves task's own status.
        self.assertEqual(folded_status(t_ip, review_map([t_ip, r_done])), ("in_progress", False))
        self.assertEqual(folded_status(t_ip, review_map([t_ip, r_psd])), ("in_progress", False))
        # A task that is itself blocked or paused keeps its own status even when its review is open/blocked.
        rb_blk = {"id": "b-review", "review_of": "b", "status": "blocked"}
        self.assertEqual(folded_status(t_blk, review_map([t_blk, rb_blk]), {"b-review"}), ("blocked", False))
        self.assertEqual(folded_status(t_psd, review_map([t_psd, {"id": "p-review", "review_of": "p", "status": "blocked"}])), ("paused", False))
        # Open review of a closed task is NOT folded (stays on its own).
        rd_open = {"id": "d-review", "review_of": "d", "status": "blocked"}
        self.assertEqual(review_map([t_done, rd_open]), {})
        # When two reviews exist for the same task, an open review wins over a closed one.
        r_old_done = {"id": "a-review-1", "review_of": "a", "status": "done"}
        self.assertEqual(review_map([r_old_done, r_blk, t_ip])["a"]["id"], "a-review")

    def test_projects_counts_and_dash_state_unified_definitions(self):
        # Active PM (offline itself — its tasks are still claimed!), archived PM, and unclaimed tasks.
        self.write_reg("alpha", project="Alpha", repo="/work/alpha", pane="hc:t-pm-gone", runtime="hc")
        self.write_reg("old", project="Old", repo="/work/old", archived="2026-11-01")

        # Alpha tasks:
        # 1. working (in_progress, live hc terminal)
        self.write_task("alpha-live", project="Alpha", repo="/work/alpha", status="in_progress", pane="hc:t1")
        # 2. in_progress but terminal offline -> NOT working
        self.write_task("alpha-off", project="Alpha", repo="/work/alpha", status="in_progress", pane="hc:t2")
        # 3. in_progress with TUI pane absent -> NOT working
        self.write_task("alpha-tui-off", project="Alpha", repo="/work/alpha", status="in_progress", pane="w1:p9")
        # 4. in_progress with remote pane -> NOT judged offline -> working
        self.write_task("alpha-remote", project="Alpha", repo="/work/alpha", status="in_progress", pane="hc:dev/t9")
        # 5. blocked, unanswered (even if terminal offline) -> waiting
        self.write_task("alpha-wait", title="需要确认", project="Alpha", repo="/work/alpha", status="blocked", pane="hc:t3")
        # 6. blocked, answered -> NOT waiting
        self.write_task("alpha-ans", title="选方案", project="Alpha", repo="/work/alpha", status="blocked",
                        log=[{"at": "2026-11-20 10:00", "by": "user", "text": "status=blocked; A or B?"}])
        self.append_raw("alpha", json.dumps({"at": "2026-11-20 10:01:00", "type": "user", "text": "【选方案】A"}) + "\n")
        # 7. review (not waiting!) + open in_progress review folded -> counts once as review, not working
        self.write_task("alpha-rev", project="Alpha", repo="/work/alpha", status="review")
        self.write_task("alpha-rev-review", project="Alpha", repo="/work/alpha", status="in_progress",
                        review_of="alpha-rev", pane="hc:t1")
        # 8. in_progress with blocked review -> folded as waiting (not working)
        self.write_task("alpha-rblk", project="Alpha", repo="/work/alpha", status="in_progress", pane="hc:t1")
        self.write_task("alpha-rblk-review", title="审查提问", project="Alpha", repo="/work/alpha", status="blocked",
                        review_of="alpha-rblk")
        # 9. merged today (dash_state counts by ctx.clock)
        today = self.ctx.clock.now()[:10]
        self.write_task("alpha-merged", project="Alpha", repo="/work/alpha", status="merged", updated=f"{today} 09:00")

        # Archived PM task (should not enter overview totals nor unclaimed_blocked)
        self.write_task("old-blk", project="Old", repo="/work/old", status="blocked")

        # Unclaimed tasks (no registered PM owns /work/nobody):
        # - blocked -> unclaimed_blocked (+1)
        self.write_task("nobody-blk", project="Nobody", repo="/work/nobody", status="blocked")
        # - review + blocked review -> folded as 1 unclaimed_blocked (+1)
        self.write_task("nobody-rev", project="Nobody", repo="/work/nobody", status="review")
        self.write_task("nobody-rev-review", project="Nobody", repo="/work/nobody", status="blocked", review_of="nobody-rev")
        # - unclaimed in_progress -> not in active projects' working
        self.write_task("nobody-ip", project="Nobody", repo="/work/nobody", status="in_progress", pane="hc:t1")

        live = readmodel.LiveSnapshot(hc_live=frozenset({"t1"}), tui_panes=frozenset({"w1:p1"}))
        projects = readmodel.Projects(self.store, live=live)
        counted = projects.counts(today=today)

        self.assertEqual(counted["by_pm"]["pm-alpha"], {
            "working": 2,       # alpha-live + alpha-remote
            "waiting": 2,       # alpha-wait + alpha-rblk (via blocked review)
            "review": 1,        # alpha-rev (folded with alpha-rev-review)
            "proposed": 0,
            "merged_today": 1,
        })
        self.assertEqual(counted["by_pm"]["pm-old"]["waiting"], 1)
        self.assertEqual(counted["totals"], {
            "projects": 1,            # only pm-alpha (pm-old is archived)
            "working": 2,
            "waiting": 2,
            "review": 1,
            "proposed": 0,
            "merged_today": 1,
            "unclaimed_blocked": 2,   # nobody-blk + nobody-rev (folded with blocked review); NOT old-blk
        })

        # Projects.list() separates project fields from coordinator and carries unified counts.
        listed = {p["name"]: p for p in projects.list(today=today)}
        self.assertEqual(listed["pm-alpha"]["slug"], "alpha")
        self.assertEqual(listed["pm-alpha"]["coordinator"]["status"], "offline")
        self.assertEqual(listed["pm-alpha"]["counts"], counted["by_pm"]["pm-alpha"])

        # dash_state() exposes top-level `counts` matching Projects.counts()["totals"]: herdr-core has t1 live (and
        # not the PM's t-pm-gone), the herdr TUI runs another agent in w1:p1.
        ctx = make_ctx(self.tmp.name, hc=FakeHc({"t1": {"state": "live"}}),
                       tui=QuietTui([{"pane_id": "w1:p1", "name": "other"}]))
        state = state_view.dash_state(ctx=ctx)
        self.assertEqual(state["counts"], counted["totals"])
        alpha_row = next(p for p in state["pms"] if p["name"] == "pm-alpha")
        self.assertEqual(alpha_row["status"], "offline")
        self.assertEqual(alpha_row["counts"], counted["by_pm"]["pm-alpha"])

    def test_end_terminal_consolidation_closed_marking_and_lost_agents(self):
        repo_dir = Path(self.tmp.name) / "work" / "alpha"
        repo_dir.mkdir(parents=True)
        wt_dir = Path(self.tmp.name) / "worktrees" / "alpha-retire"
        wt_dir.mkdir(parents=True)
        self.write_reg("alpha", project="Alpha", repo=str(repo_dir), pane="hc:tpm", terminal="tpm",
                       runtime="hc", agent="claude")
        self.write_reg("archived_proj", project="Archived", repo=str(repo_dir), pane="hc:tarch",
                       runtime="hc", archived="2026-11-10")

        # 1) Deliberately ending a reported worker (`idle-workers --close` and `close-worker`) records `closed`
        #    on the task WITHOUT altering `updated` or appending to `log`.
        orig_log = [{"at": "2026-11-20 09:30", "by": "hc:t_idle", "text": "status=review, commit=abc123; 全部测试通过"}]
        self.write_task("alpha-idle", project="Alpha", repo=str(repo_dir), status="review",
                        pane="hc:t_idle", worker_pane="hc:t_idle", dispatched=True,
                        updated="2026-11-20 09:30", log=list(orig_log))
        self.write_task("alpha-reported", project="Alpha", repo=str(repo_dir), status="review",
                        pane="hc:t_rep", worker_pane="hc:t_rep", dispatched=True,
                        updated="2026-11-20 09:45", log=[{"at": "2026-11-20 09:45", "by": "hc:t_rep", "text": "status=review; ok"}])

        hc = SplitHc(
            gets={
                "t_idle": {"address": "t_idle", "state": "live", "status": {"state": "idle"},
                           "status_ms": 1_000, "labels": {"task": "alpha-idle"}},
                "t_rep": {"address": "t_rep", "state": "live", "status": {"state": "idle"},
                          "labels": {"task": "alpha-reported"}},
                "t_ret": {"address": "t_ret", "state": "live", "cwd": str(wt_dir), "labels": {}},
                "tpm": {"address": "tpm", "state": "live", "labels": {"pm": "Alpha"}},
            },
            listing=[
                {"address": "t_live", "state": "live", "labels": {"task": "alpha-live"}},
                {"address": "tpm", "state": "finished", "reason": "server_stop"},
                {"address": "t_crashed", "state": "finished", "reason": "server_stop", "labels": {"task": "alpha-crashed"}},
                {"address": "t_exited", "state": "finished", "reason": "exited", "labels": {"task": "alpha-exited"}},
                {"address": "t_killed", "state": "finished", "reason": "killed", "finished_ms": 1_763_737_200_000},
            ])
        ctx = make_ctx(self.tmp.name, hc=hc, tui=QuietTui())

        with mock.patch("sys.stdout", new_callable=io.StringIO):
            # PM terminal is never ended by end_terminal.
            self.assertFalse(end_terminal_for(ctx, "tpm"))
            # `idle-workers --close` closes reported worker and records why="idle-workers --close".
            workers_cmd.cmd_idle_workers(argparse.Namespace(repo=str(repo_dir), minutes=1, exited=False, json=False,
                                                            close=[]), ctx=ctx)
            # `close-worker` with --while review records why="workers.close_reported".
            workers_cmd.cmd_close_worker(argparse.Namespace(terminal="t_rep", task="alpha-reported", quiet=0,
                                                            timeout=5, while_="review"), ctx=ctx)

        idle_saved = self.store.task("alpha-idle")
        self.assertEqual(idle_saved["updated"], "2026-11-20 09:30")
        self.assertEqual(idle_saved["log"], orig_log)
        self.assertEqual(idle_saved["closed"]["pane"], "hc:t_idle")
        self.assertEqual(idle_saved["closed"]["why"], "idle-workers --close")
        self.assertTrue(idle_saved["closed"]["at"])

        rep_saved = self.store.task("alpha-reported")
        self.assertEqual(rep_saved["closed"]["pane"], "hc:t_rep")
        self.assertEqual(rep_saved["closed"]["why"], "workers.close_reported")

        # 2) `cmd_retire` goes through `end_terminal` (even when unlabelled) without injecting extra log notes.
        #    Git (a StubGit): main is the merge target, dev/ret is merged into it, its worktree clean.
        self.write_task("alpha-retire", project="Alpha", repo=str(repo_dir), status="review",
                        pane="hc:t_ret", worktree=str(wt_dir), branch="dev/ret", base="main")
        ctx.git.ancestors.add(("dev/ret", "main"))
        ctx.git.branches.add("dev/ret")
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            workers_cmd.cmd_retire(argparse.Namespace(id="alpha-retire", force=False), ctx=ctx)
        ret_saved = self.store.task("alpha-retire")
        self.assertEqual(ret_saved["status"], "merged")
        self.assertEqual(ret_saved["closed"]["why"], "retire")
        self.assertEqual(len(ret_saved["log"]), 1)
        self.assertTrue(ret_saved["log"][0]["text"].startswith("retired: removed "))

        # 3) Updating a task's pane clears stale `closed`.
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            ledger_cmd.cmd_update(argparse.Namespace(
                id="alpha-reported", title=None, status=None, owner=None, workspace=None,
                pane="hc:t_live", agent=None, branch=None, worktree=None, base=None, brief=None,
                commit=None, release=None, parent=None, note="new pane", send=False, ask=False,
                option=None, option_note=None, recommended=False, keep=False,
            ), ctx=ctx)
        self.assertNotIn("closed", self.store.task("alpha-reported"))

        # 4) `dash_state()` + `project_lost()`:
        #    - `alpha-idle`: closed on purpose -> `offline=True`, `closed` present, NOT in `lost["threads"]`.
        #    - `alpha-killed`: finished with reason="killed" -> `offline=True`, `closed.why == "killed"`, NOT in `lost["threads"]`.
        #    - `alpha-crashed` (server_stop) & `alpha-exited` (exited) & `alpha-gone` (not in hc ls --all): in `lost["threads"]`!
        #    - `alpha-pm-card`: parked on the PM's own pane (`hc:tpm`) -> NOT in `lost["threads"]`!
        #    - `alpha-reattaching`: active reattach lock -> NOT in `lost["threads"]`!
        self.write_task("alpha-live", project="Alpha", repo=str(repo_dir), status="in_progress", pane="hc:t_live")
        self.write_task("alpha-crashed", title="Crashed worker", project="Alpha", repo=str(repo_dir), status="in_progress", pane="hc:t_crashed")
        self.write_task("alpha-exited", title="Exited reviewer", project="Alpha", repo=str(repo_dir), status="review", pane="hc:t_exited")
        self.write_task("alpha-gone", title="Vanished worker", project="Alpha", repo=str(repo_dir), status="blocked", pane="hc:t_vanished")
        self.write_task("alpha-killed", title="User closed tab", project="Alpha", repo=str(repo_dir), status="in_progress", pane="hc:t_killed")
        self.write_task("alpha-pm-card", title="Question on PM pane", project="Alpha", repo=str(repo_dir), status="blocked", pane="hc:tpm")
        self.write_task("alpha-reattaching", title="Already reattaching", project="Alpha", repo=str(repo_dir), status="in_progress", pane="hc:t_lock")
        lock_dir = self.root / "reattach"
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "alpha-reattaching.lock").write_text(f"{os.getpid()} 9999999999\n", encoding="utf-8")

        # No live PM (the earlier test pinned hc_pm to None; on these fakes it finds none by itself, as the
        # `lost["pm"]` assertion below shows).
        state = state_view.dash_state(ctx=ctx)

        by_tid = {t["id"]: t for t in state["tasks"]}
        # Deliberately closed tasks remain `offline=True` (so reattach icon stays available) AND carry `closed`.
        self.assertTrue(by_tid["alpha-idle"]["offline"])
        self.assertEqual(by_tid["alpha-idle"]["closed"]["why"], "idle-workers --close")
        self.assertTrue(by_tid["alpha-killed"]["offline"])
        self.assertEqual(by_tid["alpha-killed"]["closed"]["why"], "killed")
        self.assertTrue(by_tid["alpha-killed"]["closed"]["at"])
        # Crashed / vanished tasks are offline without `closed`.
        self.assertTrue(by_tid["alpha-crashed"]["offline"])
        self.assertNotIn("closed", by_tid["alpha-crashed"])
        self.assertFalse(by_tid["alpha-live"]["offline"])

        alpha_pm = next(p for p in state["pms"] if p["name"] == "pm-alpha")
        self.assertEqual((alpha_pm["runtime"], alpha_pm["repo_ok"]), ("hc", True))
        self.assertEqual(alpha_pm["lost"], {
            "pm": {"address": "tpm", "how": "server_stop"},
            "threads": [
                {"id": "alpha-crashed", "title": "Crashed worker", "address": "t_crashed", "how": "server_stop"},
                {"id": "alpha-exited", "title": "Exited reviewer", "address": "t_exited", "how": "exited"},
                {"id": "alpha-gone", "title": "Vanished worker", "address": "t_vanished", "how": "gone"},
            ],
            "restart": True,
            "key": "pm@tpm;alpha-crashed@t_crashed;alpha-exited@t_exited;alpha-gone@t_vanished",
        })
        archived_pm = next(p for p in state["pms"] if p["name"] == "pm-archived_proj")
        self.assertNotIn("lost", archived_pm)

        # When PM was killed on purpose by the user and no threads crashed, `lost` is None.
        self.assertIsNone(readmodel.project_lost(
            {"name": "pm-alpha", "repo": str(repo_dir), "pane": "hc:tpm", "runtime": "hc"},
            [self.store.task("alpha-idle"), self.store.task("alpha-killed")],
            pm_alive=False,
            hc_live={"t_live"},
            ended={"tpm": {"reason": "killed"}, "t_killed": {"reason": "killed"}},
            repo_exists=True,
        ))
        # When hc cannot be queried (`hc_live=None`), nothing is judged lost.
        self.assertIsNone(readmodel.project_lost(
            {"name": "pm-alpha", "repo": str(repo_dir), "pane": "hc:tpm", "runtime": "hc"},
            [self.store.task("alpha-crashed")],
            pm_alive=False,
            hc_live=None,
            repo_exists=True,
        ))

    def test_hook_turn_preserves_at_mentions_in_log_and_emits_hints(self):
        repo_dir = (Path(self.tmp.name) / "demo").resolve()
        (repo_dir / "src").mkdir(parents=True)
        (repo_dir / "src/app.py").write_text("print('ok')\n", encoding="utf-8")
        (self.projects / "demo/docs").mkdir(parents=True)
        spec = self.projects / "demo/docs/spec.md"
        spec.write_text("# Spec\n", encoding="utf-8")
        self.write_reg("demo", project="demo", repo=str(repo_dir), pane="hc:tpm")
        self.write_task("demo-t1", title="Fix mention", project="demo", repo=str(repo_dir),
                        status="review", branch="dev/fix", pane="hc:t5")

        # The session's pane is hc:tpm (as `pm.PANE` was set), its herdr-core terminal id unset, as then.
        ctx = make_ctx(self.tmp.name, pane="hc:tpm", tui=QuietTui(), out=StdOutput())
        ctx.hc_terminal = ""
        ctx.caller = Caller(ctx)

        def turn(prompt):
            out = io.StringIO()
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({
                    "hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": str(repo_dir)}))), \
                    mock.patch.object(sys, "stdout", out):
                hooks.cmd_hook_turn(None, ctx=ctx)
            return out.getvalue()

        prompt = (
            "请让 [@Fix mention](thread:demo-t1) 看 [@Spec](library:docs/spec.md) "
            "和 [@app.py](file:src/app.py) 再问 [@w1](session:hc:t9) "
            "[@BadLib](library:repo/secret) [@Git](file:.git/config)"
        )
        out = turn(prompt)
        self.assertIn("[mentions]", out)
        self.assertIn("thread:demo-t1 (Fix mention; status=review, branch=dev/fix, pane=hc:t5)", out)
        self.assertIn(f"library:docs/spec.md -> {spec.resolve()}", out)
        self.assertIn(f"file:src/app.py -> {repo_dir / 'src/app.py'}", out)
        self.assertIn("session:hc:t9", out)
        self.assertNotIn("repo/secret", out)
        self.assertNotIn(".git/config", out)

        self.assertEqual(turn("看下状态"), "")

        events = [json.loads(line) for line in (self.projects / "demo/conversation.jsonl").read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual([e["text"] for e in events if e.get("type") == "user"], [prompt, "看下状态"])

    def _run_git(self, cwd, *args):
        proc = subprocess.run(
            ["git", "-C", str(cwd), "-c", "user.name=Tester", "-c", "user.email=tester@example.com",
             "-c", "commit.gpgsign=false", *args],
            capture_output=True, text=True, check=True, timeout=15,
        )
        return proc.stdout.strip()

    def test_project_change_commits_files_renames_binary_pagination_and_edge_states(self):
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        repo = (Path(self.tmp.name) / "repo-change").resolve()
        wt = (Path(self.tmp.name) / "wt-change").resolve()
        repo.mkdir(parents=True)
        self._run_git(repo, "init", "-b", "main")
        (repo / "readme.md").write_text("line1\nline2\nline3\n", encoding="utf-8")
        (repo / "old_name.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        (repo / "drop.txt").write_text("to delete\n", encoding="utf-8")
        self._run_git(repo, "add", "-A")
        self._run_git(repo, "commit", "-m", "init")

        self._run_git(repo, "worktree", "add", "-b", "dev/feat", str(wt))
        (wt / "readme.md").write_text("line1\nline2-edited\nline3\n新增中文\n", encoding="utf-8")
        (wt / "目录").mkdir()
        (wt / "目录/中文.py").write_text("print('你好')\n", encoding="utf-8")
        (wt / "icon.bin").write_bytes(b"\x00\x01\x02\xff")
        self._run_git(wt, "add", "-A")
        self._run_git(wt, "commit", "-m", "feat: CJK & binary")
        c1 = self._run_git(wt, "rev-parse", "HEAD")

        self._run_git(wt, "mv", "old_name.txt", "renamed.txt")
        (wt / "renamed.txt").write_text("alpha\nbeta-two\ngamma\n", encoding="utf-8")
        (wt / "drop.txt").unlink()
        big_lines = [f"line {i:03d}" for i in range(45)] + ["Z" * 2150]
        (wt / "big.txt").write_text("\n".join(big_lines) + "\n", encoding="utf-8")
        self._run_git(wt, "add", "-A")
        self._run_git(wt, "commit", "-m", "refactor: rename and big file")
        c2 = self._run_git(wt, "rev-parse", "HEAD")

        # Main advances independently; main-only.txt must not leak into dev/feat change.
        (repo / "main-only.txt").write_text("main\n", encoding="utf-8")
        self._run_git(repo, "add", "main-only.txt")
        self._run_git(repo, "commit", "-m", "main moves on")
        main_commit = self._run_git(repo, "rev-parse", "HEAD")

        # Uncommitted change in worktree + .tools (ignored by uncommitted count).
        (wt / "dirty.txt").write_text("wip\n", encoding="utf-8")
        (wt / ".tools").write_text("ignored\n", encoding="utf-8")

        self.write_reg("demo", project="demo", repo=str(repo))
        self.write_reg("other", project="other", repo=str(Path(self.tmp.name) / "other"))
        self.write_task("demo-feat", project="demo", repo=str(repo), worktree=str(wt),
                        branch="dev/feat", base="dev/gone-base", status="review")

        projects = readmodel.Projects(self.store)

        # 1. Overview: base falls back to main when task.base is gone; uncommitted ignores .tools.
        ov = projects.change("demo", "demo-feat")
        self.assertEqual(ov["state"], "ok")
        self.assertEqual(ov["base"], "main")
        self.assertEqual(ov["branch"], "dev/feat")
        self.assertEqual(ov["uncommitted"], 1)
        self.assertEqual([c["hash"] for c in ov["commits"]], [c2, c1])
        by_path = {f["path"]: f for f in ov["files"]}
        self.assertNotIn("main-only.txt", by_path)
        self.assertEqual(by_path["目录/中文.py"]["status"], "A")
        self.assertEqual(by_path["readme.md"]["status"], "M")
        self.assertEqual(by_path["drop.txt"]["status"], "D")
        self.assertEqual(by_path["icon.bin"]["binary"], True)
        self.assertEqual(by_path["renamed.txt"]["status"], "R")
        self.assertEqual(by_path["renamed.txt"]["old_path"], "old_name.txt")

        # 2. Commits limit pagination flag.
        ov_lim = projects.change("demo", "demo-feat", commits_limit=1)
        self.assertEqual(len(ov_lim["commits"]), 1)
        self.assertTrue(ov_lim["more_commits"])

        # 3. Single commit view & unauthorized/invalid commit guards.
        c2_view = projects.change("demo", "demo-feat", commit=c2[:10])
        self.assertEqual(c2_view["commit"]["hash"], c2)
        c2_paths = {f["path"] for f in c2_view["files"]}
        self.assertIn("renamed.txt", c2_paths)
        self.assertNotIn("icon.bin", c2_paths)

        with self.assertRaises(readmodel.NotFoundError):
            projects.change("demo", "demo-feat", commit=main_commit)
        with self.assertRaises(ValueError):
            projects.change("demo", "demo-feat", commit="--output=/tmp/evil")
        with self.assertRaises(readmodel.NotFoundError):
            projects.change("other", "demo-feat")

        # 4. Single-file diff: rename metadata, line numbers, binary, pagination, and long-line clipping.
        ren_diff = projects.change("demo", "demo-feat", file="renamed.txt")
        self.assertFalse(ren_diff["binary"])
        kinds = [l["kind"] for l in ren_diff["lines"]]
        self.assertIn("hunk", kinds)
        self.assertIn("del", kinds)
        self.assertIn("add", kinds)
        self.assertTrue(any(l["kind"] == "meta" and "rename from old_name.txt" in l["text"] for l in ren_diff["lines"]))
        add_line = next(l for l in ren_diff["lines"] if l["kind"] == "add")
        self.assertEqual(add_line["text"], "beta-two")
        self.assertEqual(add_line["new_line"], 2)

        bin_diff = projects.change("demo", "demo-feat", file="icon.bin")
        self.assertTrue(bin_diff["binary"])
        self.assertEqual(bin_diff["lines"], [])

        p1 = projects.change("demo", "demo-feat", file="big.txt", offset=0, limit=20)
        self.assertEqual(len(p1["lines"]), 20)
        self.assertTrue(p1["has_more"])
        self.assertEqual(p1["next_offset"], 20)
        p2 = projects.change("demo", "demo-feat", file="big.txt", offset=20, limit=20)
        p3 = projects.change("demo", "demo-feat", file="big.txt", offset=40, limit=20)
        self.assertFalse(p3["has_more"])
        self.assertIsNone(p3["next_offset"])
        all_lines = p1["lines"] + p2["lines"] + p3["lines"]
        self.assertEqual(len(all_lines), p1["total_lines"])
        self.assertTrue(p3["truncated_lines"])
        self.assertTrue(all_lines[-1]["clipped"])
        self.assertLess(len(all_lines[-1]["text"]), 2100)

        # Byte-cap truncation preserves clean JSON and sets truncated=True.
        with mock.patch.object(readmodel, "DIFF_READ_MAX_BYTES", 140):
            capped = projects.change("demo", "demo-feat", file="big.txt", offset=0, limit=100)
            self.assertTrue(capped["truncated"])

        # 4b. Merge main into feature branch -> merges_base=True, accurate first-parent stats, main-only excluded from branch diff.
        self._run_git(wt, "merge", "--no-ff", "-m", "Merge branch 'main' into dev/feat", "main")
        merge_main_sha = self._run_git(wt, "rev-parse", "HEAD")
        ov_merged = projects.change("demo", "demo-feat")
        self.assertEqual([c["hash"] for c in ov_merged["commits"]], [merge_main_sha, c2, c1])
        m_entry, c2_entry, c1_entry = ov_merged["commits"]
        self.assertTrue(m_entry["merge"])
        self.assertTrue(m_entry["merges_base"])
        self.assertEqual(m_entry["files"], 1)
        self.assertEqual(m_entry["insertions"], 1)
        self.assertFalse(c2_entry["merge"])
        self.assertFalse(c2_entry["merges_base"])
        self.assertFalse(c1_entry["merge"])
        self.assertNotIn("main-only.txt", {f["path"] for f in ov_merged["files"]})
        m_commit = projects.change("demo", "demo-feat", commit=merge_main_sha)
        self.assertTrue(m_commit["commit"]["merge"])
        self.assertTrue(m_commit["commit"]["merges_base"])
        self.assertIn("main-only.txt", {f["path"] for f in m_commit["files"]})

        # 5. Merge + branch deletion -> branch_deleted with recorded_commit drill-down.
        self._run_git(repo, "checkout", "main")
        self._run_git(repo, "merge", "--no-ff", "-m", "merge feat", "dev/feat")
        merge_sha = self._run_git(repo, "rev-parse", "HEAD")
        self._run_git(repo, "worktree", "remove", "--force", str(wt))
        self._run_git(repo, "branch", "-D", "dev/feat")
        self.write_task("demo-feat", project="demo", repo=str(repo), branch="dev/feat",
                        base="main", commit=merge_sha[:8], status="merged")

        deleted_ov = projects.change("demo", "demo-feat")
        self.assertEqual(deleted_ov["state"], "branch_deleted")
        self.assertIn("dev/feat", deleted_ov["message"])
        self.assertIsNotNone(deleted_ov["recorded_commit"])
        self.assertEqual(deleted_ov["recorded_commit"]["hash"], merge_sha)
        self.assertTrue(deleted_ov["recorded_commit"]["merge"])
        self.assertFalse(deleted_ov["recorded_commit"]["merges_base"])

        rec_commit_files = projects.change("demo", "demo-feat", commit=merge_sha)
        self.assertIn("目录/中文.py", {f["path"] for f in rec_commit_files["files"]})
        rec_file_diff = projects.change("demo", "demo-feat", commit=merge_sha, file="readme.md")
        self.assertTrue(any(l["kind"] == "add" and l["text"] == "新增中文" for l in rec_file_diff["lines"]))

        # 6. Empty branch, no branch, missing repo, and non-git repo states.
        self._run_git(repo, "branch", "dev/empty", "main")
        self.write_task("demo-empty", project="demo", repo=str(repo), branch="dev/empty", base="main")
        self.assertEqual(projects.change("demo", "demo-empty")["state"], "empty")

        self.write_task("demo-nobranch", project="demo", repo=str(repo), branch="")
        self.assertEqual(projects.change("demo", "demo-nobranch")["state"], "no_branch")

        self.write_task("demo-norepo", project="demo", repo="/nonexistent/repo/path", branch="dev/x")
        self.assertEqual(projects.change("demo", "demo-norepo")["state"], "no_repo")

        plain_dir = Path(self.tmp.name) / "not-git"
        plain_dir.mkdir()
        self.write_reg("plain", project="plain", repo=str(plain_dir))
        self.write_task("plain-1", project="plain", repo=str(plain_dir), branch="dev/x")
        self.assertEqual(projects.change("plain", "plain-1")["state"], "not_git")

        # 7. CLI subprocess `pm.py project change` returns valid JSON.
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "project", "change", "demo", "demo-feat"],
            capture_output=True, text=True, env=self.cli_env(), timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cli_json = json.loads(proc.stdout)
        self.assertEqual(cli_json["state"], "branch_deleted")
        self.assertEqual(cli_json["recorded_commit"]["hash"], merge_sha)


class ContextStoreAndProjectTests(LedgerCase):
    """Store.documents/document, Projects.context/document and `pm.py project context/file`. Moved from
    test_pm_context.py."""

    def write_file(self, rel, content):
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        return target

    def test_documents_lists_project_and_user_context_and_excludes_internal_hidden_and_attachments(self):
        self.write_reg("dudu", project="dudu")
        self.write_file("projects/dudu/decisions.md", "- 2026-11-10 连线只用直线和曲线，不要直角线\n")
        self.write_file("projects/dudu/handover.md", "上一任 PM 交接说明\n")
        self.write_file("projects/dudu/verify", "#!/bin/sh\nexit 0\n")
        self.write_file("projects/dudu/shots/board.png", b"\x89PNG fake")
        self.write_file("projects/dudu/logo.svg", "<svg><script>alert(1)</script></svg>")
        self.write_file("projects/dudu/data.bin", b"\x00\x01\x02")
        self.write_file("projects/dudu/notes/taken-in.json", '{"nested": true}\n')
        self.write_file("projects/dudu/docs/spec.md", "# 规格\n")
        self.write_file("projects/dudu/docs/shots/board.png", b"\x89PNG fake")
        self.write_file("projects/dudu/docs/notes/taken-in.json", '{"nested": true}\n')
        self.write_file("projects/dudu/seat.json", '{"pid": 123}\n')
        self.write_file("projects/dudu/seat.lock", "")
        self.write_file("projects/dudu/next-session.json", '{"argv": ["claude"]}\n')

        # Project memory + index + worker candidate + hidden history/lock.
        self.write_file(
            "projects/dudu/memory/render-check-gates-merge.md",
            '---\nname: render-check-gates-merge\n'
            'description: "渲染检查只在合并动到界面 mod 时必跑"\n'
            'metadata:\n  node_type: memory\n  type: project\n'
            '  modified: 2026-11-21T18:16:37.000Z\n  by: "pm"\n---\n\n正文说明。\n',
        )
        self.write_file("projects/dudu/memory/MEMORY.md", "- [render-check-gates-merge](render-check-gates-merge.md)\n")
        self.write_file("projects/dudu/memory/.lock", "")
        self.write_file("projects/dudu/memory/.history/old.md", "old")
        self.write_file(
            "projects/dudu/memory/candidates/w1/draft-tip.md",
            '---\nname: draft-tip\ndescription: "worker 候选记忆"\nmetadata:\n  type: reference\n  modified: 2026-11-20\n---\n\n内容\n',
        )

        # Personal (user) memory + index + hidden lock.
        self.write_file(
            "memory/reply-in-chinese.md",
            '---\nname: reply-in-chinese\n'
            'description: "Always reply to the user in Chinese"\n'
            'metadata:\n  node_type: memory\n  type: feedback\n'
            '  modified: 2026-11-15T03:07:24.278Z\n---\n\nReply in Chinese.\n',
        )
        self.write_file("memory/MEMORY.md", "- [reply-in-chinese](reply-in-chinese.md)\n")
        self.write_file("memory/.lock", "")

        # Excluded internal files & attachments.
        for internal in ("conversation.jsonl", "delivered.json", "delivered.lock", "deliver.lock",
                         "turn-cause.json", "taken-in.json", "takeover.json", "pm-settings.json",
                         "schedules.json", "dudu-attachments.json"):
            self.write_file(f"projects/dudu/{internal}", "{}")
        self.write_file("projects/dudu/attachments/paste-20261121-100000.png", b"\x89PNG")
        self.write_file("projects/dudu/.DS_Store", b"junk")

        projects = readmodel.Projects(self.store)
        docs = projects.context("dudu")
        by_key = {f"{d['root']}/{d['path']}": d for d in docs}

        # Only the allow-list: decisions.md, docs/**, top-level memories (no MEMORY.md, candidates, history).
        self.assertEqual(by_key["project/decisions.md"]["kind"], "md")
        self.assertEqual(by_key["project/decisions.md"]["show"], "text")
        self.assertEqual(by_key["project/docs"]["kind"], "folder")
        self.assertEqual(by_key["project/docs/spec.md"]["kind"], "md")
        self.assertEqual(by_key["project/docs/shots"]["kind"], "folder")
        self.assertEqual(by_key["project/docs/shots/board.png"]["show"], "image")
        self.assertEqual(by_key["project/docs/notes/taken-in.json"]["show"], "text")
        for gone in ("project/handover.md", "project/verify", "project/shots", "project/shots/board.png",
                     "project/logo.svg", "project/data.bin", "project/notes/taken-in.json",
                     "project/memory/MEMORY.md", "project/memory/candidates", "project/memory/candidates/w1/draft-tip.md",
                     "user/MEMORY.md"):
            self.assertNotIn(gone, by_key)

        pmem = by_key["project/memory/render-check-gates-merge.md"]
        self.assertEqual((pmem["kind"], pmem["type"], pmem["description"], pmem["modified"], pmem["show"]),
                         ("memory", "project", "渲染检查只在合并动到界面 mod 时必跑", "2026-11-21T18:16:37Z", "text"))

        umem = by_key["user/reply-in-chinese.md"]
        self.assertEqual((umem["kind"], umem["type"], umem["description"], umem["modified"]),
                         ("memory", "feedback", "Always reply to the user in Chinese", "2026-11-15T03:07:24Z"))

        # Excluded files never appear.
        for forbidden in (
            "project/conversation.jsonl", "project/delivered.json", "project/delivered.lock",
            "project/deliver.lock", "project/turn-cause.json", "project/taken-in.json",
            "project/takeover.json", "project/pm-settings.json", "project/schedules.json",
            "project/dudu-attachments.json", "project/attachments",
            "project/attachments/paste-20261121-100000.png", "project/.DS_Store",
            "project/memory/.lock", "project/memory/.history", "project/memory/.history/old.md",
            "project/seat.json", "project/seat.lock", "project/next-session.json",
            "user/.lock",
        ):
            self.assertNotIn(forbidden, by_key)

    def test_document_reads_text_and_blocks_traversal_symlinks_internal_binary_and_oversized(self):
        self.write_reg("dudu")
        self.write_file("config.json", '{"secret": "outside"}')
        self.write_file("projects/dudu/decisions.md", "- 决定一\n")
        self.write_file("projects/dudu/notes/taken-in.json", '{"ok": 1}')
        self.write_file("projects/dudu/docs/notes/taken-in.json", '{"ok": 1}')
        self.write_file("projects/dudu/taken-in.json", '{"internal": 1}')
        self.write_file("projects/dudu/handover.md", "交接\n")
        self.write_file("projects/dudu/conversation.jsonl", '{"type":"user","text":"hi"}\n')
        self.write_file("projects/dudu/attachments/paste.txt", "attached")
        self.write_file("projects/dudu/memory/.history/old.md", "hidden")
        self.write_file("projects/dudu/docs/shots/board.png", b"\x89PNG")
        self.write_file("projects/dudu/docs/logo.svg", "<svg/>")
        self.write_file("projects/dudu/docs/binary.txt", b"\x00not-utf8")
        self.write_file("projects/dudu/docs/bad-utf8.md", b"\xff\xfe\xfd")
        self.write_file("projects/dudu/docs/huge.md", "a" * (store_mod.DOCUMENT_MAX + 1))
        self.write_file("memory/personal.md", "---\nname: personal\ndescription: x\n---\n\nhi\n")

        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text("secret outside ledger", encoding="utf-8")
        outside_dir = Path(self.tmp.name) / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "leak.md").write_text("leaked", encoding="utf-8")

        (self.projects / "dudu/docs/escape-file.md").symlink_to(outside)
        (self.projects / "dudu/docs/inside-link.md").symlink_to(self.projects / "dudu/decisions.md")
        (self.projects / "dudu/docs/escape-dir").symlink_to(outside_dir, target_is_directory=True)
        (self.root / "memory/escape-user.md").symlink_to(outside)

        projects = readmodel.Projects(self.store)
        # Symlinks are never listed either.
        listed = {f"{d['root']}/{d['path']}" for d in projects.context("dudu")}
        for sym in ("project/docs/escape-file.md", "project/docs/inside-link.md", "project/docs/escape-dir",
                    "project/docs/escape-dir/leak.md", "user/escape-user.md"):
            self.assertNotIn(sym, listed)

        # Valid reads in both roots, including nested file sharing a top-level internal name.
        self.assertEqual(projects.document("dudu", "project", "decisions.md").replace("\r\n", "\n"), "- 决定一\n")
        self.assertEqual(projects.document("dudu", "project", "docs/notes/taken-in.json"), '{"ok": 1}')
        self.assertEqual(projects.document("dudu", "docs", "notes/taken-in.json"), '{"ok": 1}')
        self.assertEqual(projects.document("dudu", "docs", "decisions.md").replace("\r\n", "\n"), "- 决定一\n")
        self.assertIn("hi", projects.document("dudu", "user", "personal.md"))

        # Traversal, bad roots, bad slugs -> ValueError / NotFoundError.
        for bad_call in (
            lambda: projects.document("dudu", "other", "decisions.md"),
            lambda: projects.document("dudu", "project", "../config.json"),
            lambda: projects.document("dudu", "project", "../../outside.md"),
            lambda: projects.document("dudu", "user", "../config.json"),
            lambda: projects.document("dudu", "project", "/etc/passwd"),
            lambda: projects.document("dudu", "project", "notes\\taken-in.json"),
            lambda: projects.document("dudu", "project", ""),
            lambda: projects.document("dudu", "project", "docs/shots/board.png"),
            lambda: projects.document("dudu", "docs", "logo.svg"),
            lambda: projects.document("dudu", "docs", "binary.txt"),
            lambda: projects.document("dudu", "docs", "bad-utf8.md"),
            lambda: projects.document("dudu", "docs", "huge.md"),
        ):
            with self.assertRaises(ValueError):
                bad_call()

        # Symlinks, folders, hidden, attachments, top-level internal (including case-insensitive) -> NotFoundError.
        for forbidden_call in (
            lambda: projects.document("dudu", "docs", "escape-file.md"),
            lambda: projects.document("dudu", "docs", "inside-link.md"),
            lambda: projects.document("dudu", "docs", "escape-dir/leak.md"),
            lambda: projects.document("dudu", "project", "notes/taken-in.json"),
            lambda: projects.document("dudu", "project", "handover.md"),
            lambda: projects.document("dudu", "docs", "handover.md"),
            lambda: projects.document("dudu", "user", "escape-user.md"),
            lambda: projects.document("dudu", "project", "notes"),
            lambda: projects.document("dudu", "project", "taken-in.json"),
            lambda: projects.document("dudu", "project", "TAKEN-IN.JSON"),
            lambda: projects.document("dudu", "project", "Schedules.json"),
            lambda: projects.document("dudu", "project", "conversation.jsonl"),
            lambda: projects.document("dudu", "project", "attachments/paste.txt"),
            lambda: projects.document("dudu", "project", "Attachments/paste.txt"),
            lambda: projects.document("dudu", "project", "memory/.history/old.md"),
            lambda: projects.document("no-such-project", "project", "decisions.md"),
            lambda: projects.context("no-such-project"),
        ):
            with self.assertRaises(readmodel.NotFoundError):
                forbidden_call()

        # Even if the entire project folder or user memory folder is replaced by a symlink, nothing leaks.
        self.write_reg("linked")
        (self.projects / "linked").symlink_to(outside_dir, target_is_directory=True)
        self.assertEqual([d for d in projects.context("linked") if d["root"] == "project"], [])
        with self.assertRaises(readmodel.NotFoundError):
            projects.document("linked", "project", "leak.md")

    def test_dynamic_paths_and_cli_project_context_and_file(self):
        self.write_reg("Demo", project="Demo", repo="/work/Demo")
        self.write_file("projects/demo/decisions.md", "- 2026-11-21 右侧放 Context 标签\n")
        self.write_file("projects/demo/handover.md", "交接笔记\n")
        self.write_file(
            "memory/prefer-carbon-neon.md",
            '---\nname: prefer-carbon-neon\ndescription: "派活优先用 carbon 和 neon"\nmetadata:\n  type: feedback\n---\n\n详情。\n',
        )

        # Another ledger: a FileStore on its Home reads that one; the legacy STORE reads whichever ledger the
        # process's context names at call time (legacy_ctx.bound points it at a Context's).
        alt = make_ctx(Path(self.tmp.name) / "alt")
        (alt.home.registrations).mkdir(parents=True)
        (alt.home.projects / "demo").mkdir(parents=True)
        (alt.home.registrations / "demo.json").write_text(json.dumps({"name": "pm-demo", "project": "demo",
                                                                       "repo": "/work/demo"}))
        (alt.home.projects / "demo/decisions.md").write_bytes("- 另一份账本\n".encode("utf-8"))
        self.assertEqual(alt.store.document("demo", "project", "decisions.md"), "- 另一份账本\n")
        self.assertIn("Context 标签", self.ctx.store.document("demo", "project", "decisions.md"))

        env = self.cli_env()

        # 1. `pm.py project context <slug>` accepts PM name / project name / --home flag.
        r_ctx = subprocess.run([sys.executable, str(SCRIPT), "--home", str(self.root), "project", "context", "pm-demo"],
                               env={**env, "PM_HOME": str(Path(self.tmp.name) / "unused")},
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(r_ctx.returncode, 0, r_ctx.stderr)
        ctx = json.loads(r_ctx.stdout)
        keys = {f"{f['root']}/{f['path']}" for f in ctx["files"]}
        self.assertEqual(keys, {"project/decisions.md", "user/prefer-carbon-neon.md"})  # handover.md is not listed

        # 2. `pm.py project file <slug> <path>` works with `<root>/<path>`, bare `<path>`, and `--root`.
        for args, want_root, want_path, needle in (
            (["project", "file", "demo", "project/decisions.md"], "project", "decisions.md", "Context 标签"),
            (["project", "file", "demo", "decisions.md"], "project", "decisions.md", "Context 标签"),
            (["project", "file", "demo", "user/prefer-carbon-neon.md"], "user", "prefer-carbon-neon.md", "详情。"),
            (["project", "file", "demo", "prefer-carbon-neon.md", "--root", "user"], "user", "prefer-carbon-neon.md", "详情。"),
        ):
            res = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 0, res.stderr)
            doc = json.loads(res.stdout)
            self.assertEqual((doc["root"], doc["path"]), (want_root, want_path))
            self.assertIn(needle, doc["text"])
            self.assertEqual(doc["size"], len(doc["text"].encode("utf-8")))

        # 3. Unknown-extension text (`verify.before-ui-only`) and leading-dash filenames (`-weird.md` with `--`).
        self.write_file("projects/demo/verify.before-ui-only", "#!/bin/sh\necho ui-check\n")
        self.write_file("projects/demo/docs/verify.before-ui-only", "#!/bin/sh\necho ui-check\n")
        self.write_file("projects/demo/docs/-weird.md", "# Leading dash filename\n")
        self.write_file("memory/-user-note.md", "---\nname: -user-note\ndescription: dash file\n---\n\nbody\n")
        self.write_file("projects/demo/docs/opaque.unknown", b"\x00\x01binary")

        r_ctx2 = subprocess.run([sys.executable, str(SCRIPT), "project", "context", "demo"],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r_ctx2.returncode, 0, r_ctx2.stderr)
        by_key2 = {f"{f['root']}/{f['path']}": f for f in json.loads(r_ctx2.stdout)["files"]}
        self.assertNotIn("project/verify.before-ui-only", by_key2)  # process files of the ledger are not listed
        self.assertEqual(by_key2["project/docs/verify.before-ui-only"]["kind"], "before-ui-only")
        self.assertNotIn("show", by_key2["project/docs/verify.before-ui-only"])
        self.assertIn("project/docs/-weird.md", by_key2)

        for args, want_root, want_path, needle in (
            (["project", "file", "--root", "project", "--", "demo", "docs/verify.before-ui-only"],
             "project", "docs/verify.before-ui-only", "ui-check"),
            (["project", "file", "--root", "docs", "--", "demo", "-weird.md"],
             "docs", "-weird.md", "Leading dash"),
            (["project", "file", "--root", "user", "--", "demo", "-user-note.md"],
             "user", "-user-note.md", "body"),
        ):
            res = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 0, res.stderr)
            doc = json.loads(res.stdout)
            self.assertEqual((doc["root"], doc["path"]), (want_root, want_path))
            self.assertIn(needle, doc["text"])

        r_bin = subprocess.run(
            [sys.executable, str(SCRIPT), "project", "file", "--root", "docs", "--", "demo", "opaque.unknown"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(r_bin.returncode, 0)
        self.assertIn("not a text file", r_bin.stderr)

        # 4. Missing project or forbidden path exits non-zero with a clean message (no traceback).
        for bad_args in (
            ["project", "context", "nope"],
            ["project", "file", "demo", "../pms/Demo.json"],
            ["project", "file", "demo", "project/conversation.jsonl"],
        ):
            bad = subprocess.run([sys.executable, str(SCRIPT), *bad_args], env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(bad.returncode, 0)
            self.assertNotIn("Traceback", bad.stderr)

    def test_os_open_includes_o_binary_for_windows_compatibility(self):
        self.write_reg("dudu")
        self.write_file("projects/dudu/decisions.md", "- 决定\r\n".encode("utf-8"))
        self.write_file(
            "projects/dudu/memory/win-rule.md",
            '---\nname: win-rule\ndescription: "Windows binary open check"\nmetadata:\n  type: project\n---\n\n内容\n',
        )
        projects = readmodel.Projects(self.store)
        real_open = os.open
        seen_flags = []

        def spy_open(path, flags, *args, **kwargs):
            seen_flags.append((Path(path).name, flags))
            return real_open(path, flags & ~0x8000, *args, **kwargs)

        with mock.patch.object(os, "O_BINARY", 0x8000, create=True), \
                mock.patch.object(os, "open", side_effect=spy_open):
            docs = projects.context("dudu")
            text = projects.document("dudu", "project", "decisions.md")

        self.assertEqual(text, "- 决定\r\n")
        self.assertTrue(any(d["path"] == "memory/win-rule.md" and d["kind"] == "memory" for d in docs))
        by_name = dict(seen_flags)
        self.assertIn("win-rule.md", by_name)
        self.assertIn("decisions.md", by_name)
        self.assertEqual(by_name["win-rule.md"] & 0x8000, 0x8000)
        self.assertEqual(by_name["decisions.md"] & 0x8000, 0x8000)

    def test_document_and_documents_use_store_strict_read_errors(self):
        self.write_reg("dudu")
        self.write_file("projects/dudu/docs/shots/board.png", b"\x89PNG")
        self.write_file("projects/dudu/docs/binary.txt", b"\x00not-utf8")
        self.write_file("projects/dudu/docs/bad-utf8.md", b"\xff\xfe\xfd")
        self.write_file("projects/dudu/docs/huge.md", "a" * (store_mod.DOCUMENT_MAX + 1))
        projects = readmodel.Projects(self.store)

        for damaged_path in ("shots/board.png", "binary.txt", "bad-utf8.md", "huge.md"):
            with self.assertRaises(store_mod.DamagedFileError):
                projects.document("dudu", "docs", damaged_path)

        if os.name != "nt" and os.geteuid() != 0:
            locked = self.write_file("projects/dudu/docs/secret.md", "top secret\n")
            locked.chmod(0o000)
            self.addCleanup(lambda: locked.chmod(0o644) if locked.exists() else None)
            with self.assertRaises(store_mod.UnreadableFileError):
                projects.document("dudu", "docs", "secret.md")

            r_cli = subprocess.run(
                [sys.executable, str(SCRIPT), "project", "file", "--root", "docs", "--", "dudu", "secret.md"],
                env=self.cli_env(), capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r_cli.returncode, 1)
            self.assertIn("ledger store error:", r_cli.stderr)

            proj_dir = self.projects / "dudu"
            proj_dir.chmod(0o000)
            self.addCleanup(lambda: proj_dir.chmod(0o755) if proj_dir.exists() else None)
            with self.assertRaises(store_mod.UnreadableFileError):
                projects.context("dudu")
            proj_dir.chmod(0o755)

    def test_research_root_lists_reads_headings_and_blocks_escapes_and_symlinks(self):
        repo = Path(self.tmp.name) / "repo-dudu"
        ev = repo / "evidence"
        (ev / "agents-helpers").mkdir(parents=True)
        (ev / "agents-helpers/README.md").write_text(
            "# 子 agent：线程 worker 和临时 helper（调研与设计）\n\n详细内容。\n", encoding="utf-8"
        )
        (ev / "agents-helpers/shot.png").write_bytes(b"\x89PNG fake")
        (ev / "agents-helpers/probe.log").write_text("log line\n", encoding="utf-8")
        (ev / "dev-pm-skill").mkdir(parents=True)
        (ev / "dev-pm-skill/README.md").write_text(
            "﻿---\ntitle: fallback\n---\n\n```bash\n# not a heading\n```\n\n## Skill 调研\n", encoding="utf-8"
        )
        (ev / "dev-pm-skill/skill-md-rules.md").write_text("# 同目录非 README 不该列\n", encoding="utf-8")
        (ev / "standalone.md").write_text("# 顶层散落 md 不该列\n", encoding="utf-8")
        (ev / "ended-row-chip").mkdir(parents=True)
        (ev / "ended-row-chip/panel.png").write_bytes(b"\x89PNG")
        (ev / "ledger-restore/ledger/memory").mkdir(parents=True)
        (ev / "ledger-restore/REPORT.md").write_text("# 非 README 不该列\n", encoding="utf-8")
        (ev / "ledger-restore/ledger/memory/dup.md").write_text("# 嵌套备份不该列\n", encoding="utf-8")
        (ev / "render-check").mkdir(parents=True)
        (ev / "render-check/README.md").write_text("# render-check 排除\n", encoding="utf-8")
        (ev / "render-check-locked").mkdir(parents=True)
        (ev / "render-check-locked/README.md").write_text("# 锁屏渲染检查调研\n\n正式报告应保留。\n", encoding="utf-8")
        (ev / "custom-probe-run").mkdir(parents=True)
        (ev / "custom-probe-run/.render-check").write_text("marker\n", encoding="utf-8")
        (ev / "custom-probe-run/README.md").write_text("# 带 .render-check 标记排除\n", encoding="utf-8")
        (ev / ".hidden").mkdir(parents=True)
        (ev / ".hidden/README.md").write_text("# 隐藏目录\n", encoding="utf-8")
        (ev / "huge-topic").mkdir(parents=True)
        (ev / "huge-topic/README.md").write_text("a" * (store_mod.DOCUMENT_MAX + 1), encoding="utf-8")
        (ev / "bad-utf8").mkdir(parents=True)
        (ev / "bad-utf8/README.md").write_bytes(b"\xff\xfe\xfd")
        (ev / "logo.svg").write_text("<svg/>", encoding="utf-8")

        # Ledger-stored research (used when a repo does not gitignore evidence/) merges cleanly and stays out of `project`.
        self.write_file("projects/dudu/research/ledger-topic/README.md", "# 台账侧调研报告\n\n来自未忽略仓。\n")

        outside = Path(self.tmp.name) / "outside-secret.md"
        outside.write_text("# 外部机密\n", encoding="utf-8")
        outside_dir = Path(self.tmp.name) / "outside-research"
        outside_dir.mkdir()
        (outside_dir / "README.md").write_text("# 外部目录\n", encoding="utf-8")
        (repo / "secret.txt").write_text("repo root secret\n", encoding="utf-8")

        (ev / "escape-dir").symlink_to(outside_dir, target_is_directory=True)
        (ev / "symlink-readme").mkdir(parents=True)
        (ev / "symlink-readme/README.md").symlink_to(outside)
        (ev / "inside-link").mkdir(parents=True)
        (ev / "inside-link/README.md").symlink_to(ev / "agents-helpers/README.md")

        self.write_reg("dudu", project="dudu", repo=str(repo))
        projects = readmodel.Projects(self.store)

        docs = projects.context("dudu")
        research = {d["path"]: d for d in docs if d["root"] == "research"}
        project_paths = {d["path"] for d in docs if d["root"] == "project"}
        self.assertEqual(
            set(research),
            {
                "agents-helpers/README.md",
                "dev-pm-skill/README.md",
                "render-check-locked/README.md",
                "huge-topic/README.md",
                "bad-utf8/README.md",
                "ledger-topic/README.md",
            },
        )
        # Ledger research folder never leaks into `project` root.
        self.assertFalse(any(p == "research" or p.startswith("research/") for p in project_paths))

        self.assertEqual(research["agents-helpers/README.md"]["kind"], "md")
        self.assertEqual(research["agents-helpers/README.md"]["show"], "text")
        self.assertEqual(
            research["agents-helpers/README.md"]["description"],
            "子 agent：线程 worker 和临时 helper（调研与设计）",
        )
        self.assertEqual(research["dev-pm-skill/README.md"]["description"], "Skill 调研")
        self.assertEqual(research["ledger-topic/README.md"]["description"], "台账侧调研报告")
        self.assertNotIn("show", research["huge-topic/README.md"])

        # Reading valid topic READMEs works (both repo and ledger); non-READMEs, excluded dirs, escapes, symlinks blocked.
        self.assertIn("详细内容", projects.document("dudu", "research", "agents-helpers/README.md"))
        self.assertIn("正式报告应保留", projects.document("dudu", "research", "render-check-locked/README.md"))
        self.assertIn("来自未忽略仓", projects.document("dudu", "research", "ledger-topic/README.md"))
        for bad_call in (
            lambda: projects.document("dudu", "research", "../secret.txt"),
            lambda: projects.document("dudu", "research", "agents-helpers/../../outside-secret.md"),
            lambda: projects.document("dudu", "research", "/etc/passwd"),
            lambda: projects.document("dudu", "research", "agents-helpers\\README.md"),
            lambda: projects.document("dudu", "research", "huge-topic/README.md"),
            lambda: projects.document("dudu", "research", "bad-utf8/README.md"),
        ):
            with self.assertRaises(ValueError):
                bad_call()
        for missing_call in (
            lambda: projects.document("dudu", "research", "agents-helpers/probe.log"),
            lambda: projects.document("dudu", "research", "agents-helpers/shot.png"),
            lambda: projects.document("dudu", "research", "dev-pm-skill/skill-md-rules.md"),
            lambda: projects.document("dudu", "research", "standalone.md"),
            lambda: projects.document("dudu", "research", "render-check/README.md"),
            lambda: projects.document("dudu", "research", "custom-probe-run/README.md"),
            lambda: projects.document("dudu", "research", "escape-dir/README.md"),
            lambda: projects.document("dudu", "research", "symlink-readme/README.md"),
            lambda: projects.document("dudu", "research", "inside-link/README.md"),
            lambda: projects.document("dudu", "research", ".hidden/README.md"),
            lambda: projects.document("dudu", "research", "agents-helpers"),
            lambda: projects.document("dudu", "project", "research/ledger-topic/README.md"),
        ):
            with self.assertRaises(readmodel.NotFoundError):
                missing_call()

        # CLI accepts both `research/<path>` and `--root research -- <slug> <path>`.
        env = self.cli_env()
        r_ctx = subprocess.run([sys.executable, str(SCRIPT), "project", "context", "dudu"],
                               env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r_ctx.returncode, 0, r_ctx.stderr)
        cli_files = json.loads(r_ctx.stdout)["files"]
        self.assertTrue(any(f["root"] == "research" and f["path"] == "agents-helpers/README.md" for f in cli_files))
        for args in (
            ["project", "file", "dudu", "research/agents-helpers/README.md"],
            ["project", "file", "--root", "research", "--", "dudu", "agents-helpers/README.md"],
            ["project", "file", "dudu", "research/ledger-topic/README.md"],
        ):
            res = subprocess.run([sys.executable, str(SCRIPT), *args],
                                 env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 0, res.stderr)
            doc = json.loads(res.stdout)
            self.assertEqual(doc["root"], "research")

        # Replacing `<repo>/evidence` itself with a symlink leaks nothing.
        repo_sym = Path(self.tmp.name) / "repo-sym"
        repo_sym.mkdir()
        (repo_sym / "evidence").symlink_to(outside_dir, target_is_directory=True)
        self.write_reg("symproj", project="symproj", repo=str(repo_sym))
        self.assertEqual([d for d in projects.context("symproj") if d["root"] == "research"], [])
        with self.assertRaises(readmodel.NotFoundError):
            projects.document("symproj", "research", "README.md")

        # Missing evidence/ or unregistered project with only task repo degrades cleanly.
        repo_no_ev = Path(self.tmp.name) / "repo-empty"
        repo_no_ev.mkdir()
        self.write_reg("emptyproj", project="emptyproj", repo=str(repo_no_ev))
        self.assertEqual([d for d in projects.context("emptyproj") if d["root"] == "research"], [])

        repo_task_only = Path(self.tmp.name) / "repo-task-only"
        (repo_task_only / "evidence/only-topic").mkdir(parents=True)
        (repo_task_only / "evidence/only-topic/README.md").write_text("# 无登记项目\n", encoding="utf-8")
        (self.tasks / "t1.json").write_text(json.dumps({
            "id": "t1", "title": "research", "project": "repo-task-only", "repo": str(repo_task_only),
            "status": "done", "updated": "2026-11-21 20:00",
        }), encoding="utf-8")
        self.assertEqual(
            [d["path"] for d in projects.context("repo-task-only") if d["root"] == "research"],
            ["only-topic/README.md"],
        )

    def test_documents_excludes_project_helpers_folder(self):
        self.write_reg("dudu", project="dudu")
        self.write_file("projects/dudu/decisions.md", "- keep\n")
        self.write_file("projects/dudu/helpers/pm/scan.md", "temporary helper conclusion\n")
        self.write_file("projects/dudu/helpers/dudu-work/check.md", "worker helper screen capture\n")
        docs = self.store.documents("dudu")
        paths = {d["path"] for d in docs if d["root"] == "project"}
        self.assertIn("decisions.md", paths)
        self.assertFalse(any(p == "helpers" or p.startswith("helpers/") for p in paths))
        with self.assertRaises(FileNotFoundError):
            self.store.document("dudu", "project", "helpers/pm/scan.md")


class LibraryAndMemoryTests(unittest.TestCase):
    """`pm.py project library|memory` (allow-listed roots) and the editing commands, run as `pm.py` on a test's own
    ledger (make_ctx's home). Moved from test_pm_context.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = make_ctx(self.tmp.name)
        self.root = self.ctx.home.root
        for d in ("pms", "tasks", "projects", "memory"):
            (self.root / d).mkdir(parents=True)
        self.repo = Path(self.tmp.name) / "proj"
        self.repo.mkdir()
        (self.root / "pms/proj.json").write_text(json.dumps({"name": "pm-proj", "project": "proj",
                                                              "repo": str(self.repo)}))
        self.env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "HC_TERMINAL_ID")}
        self.env["PM_HOME"] = str(self.root)
        self.script = SCRIPT

    def put(self, base, rel, content):
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        (target.write_bytes if isinstance(content, bytes) else target.write_text)(content)
        return target

    def task(self, tid, **fields):
        (self.root / "tasks" / f"{tid}.json").write_text(json.dumps(
            {"id": tid, "title": fields.pop("title", tid), "project": "proj", "repo": str(self.repo),
             "status": "done", "updated": "2026-11-21 20:00", **fields}))

    def pm(self, *args, ok=True):
        r = subprocess.run([sys.executable, str(self.script), "project", *args], env=self.env,
                           capture_output=True, text=True, timeout=30)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            return json.loads(r.stdout)
        return r

    def test_library_lists_docs_research_and_instructions_and_nothing_of_the_process(self):
        ledger = self.root / "projects/proj"
        self.put(ledger, "decisions.md", "- 2026-11-10 一\n- 2026-11-11 二\n")
        for junk in ("handover.md", "verify", "verify.before-ui-only", "conversation.jsonl"):
            self.put(ledger, junk, "x\n")
        self.put(ledger, "memory/a-rule.md", '---\nname: a-rule\ndescription: "规矩"\nmetadata:\n  type: feedback\n---\n')
        self.put(ledger, "docs/spec.md", "# 告警规格\n\n正文。\n")
        self.put(ledger, "docs/.history/old.md.20261101-000000.deleted", "old\n")
        self.put(ledger, "docs/research/ledger-report.md", "# 台账里的报告\n\n私有结论。\n")
        ev = self.repo / "evidence"
        self.put(ev, "alpha/README.md", "# Alpha 调研\n\n- **任务**：`proj-alpha-study`\n- **日期**：今天\n\n"
                                        "第一段结论，说明为什么。\n\n## 细节\n")
        self.put(ev, "alpha/shot.png", b"\x89PNG")
        self.put(ev, "alpha/probe.sh", "#!/bin/sh\n")
        self.put(ev, "beta/README.md", "# Beta 旧位置\n")
        self.put(ev, "gamma/README.md", "# Gamma\n\n结论。\n")
        self.put(ev, "published/README.md", "# 名叫 published 的本地原件\n")
        self.put(ev, "render-check/README.md", "# 截图\n")
        self.put(ledger, "docs/research/beta.md", "# Beta 新家\n\n搬过来的报告。\n")
        self.put(self.repo, "docs/research/alpha.md", "# Alpha（公开脱敏版）\n\n删掉了私有细节。\n")
        self.put(self.repo, "docs/research/only-public.md", "# 只有公开版\n\n正文。\n")
        self.task("proj-only-public", title="不该被猜成它")
        self.put(self.repo, "docs/guide.md", "# 网站文档\n")
        self.put(self.repo, "CLAUDE.md", "# 仓库规矩\n")
        self.put(self.repo, "AGENTS.md", "# Agents\n")
        self.put(self.repo, ".claude/coordination.md", "# 协调\n")
        self.put(self.repo, ".claude/rules/tests.md", "# 测试规矩\n")
        self.put(self.repo, ".claude/rules/notes.txt", "not a rule\n")
        self.task("proj-alpha-study", title="Alpha 调研任务")
        self.task("proj-beta-x", title="Beta", worktree="/wt/dev-beta")
        self.task("proj-gamma-1", title="Gamma 任务")
        FileStore(self.root).note_research_source("proj", "evidence/gamma/README.md", "proj-gamma-1")

        lib = self.pm("library", "proj")
        self.assertEqual([r["id"] for r in lib["roots"]], ["docs", "repo_docs", "research", "instructions"])
        self.assertEqual([r["writable"] for r in lib["roots"]], [True, False, False, False])
        by = {f"{f['root']}/{f['path']}": f for f in lib["files"]}
        self.assertEqual(set(by), {
            "docs/spec.md", "docs/decisions.md",
            "repo_docs/docs/guide.md",
            "research/docs/research/beta.md", "research/docs/research/ledger-report.md",
            "research/evidence/alpha/README.md", "research/evidence/gamma/README.md",
            "research/evidence/published/README.md",
            "research/published/only-public.md",
            "instructions/CLAUDE.md", "instructions/AGENTS.md", "instructions/.claude/coordination.md",
            "instructions/.claude/rules/tests.md",
        })
        self.assertIn("名叫 published 的本地原件",
                      self.pm("file", "proj", "research/evidence/published/README.md")["text"])
        self.assertEqual((by["docs/spec.md"]["title"], by["docs/spec.md"]["writable"]), ("告警规格", True))
        dec = by["docs/decisions.md"]
        self.assertEqual((dec["archive"], dec["hidden"], dec["writable"], dec["entries"]), (True, False, False, 2))
        alpha = by["research/evidence/alpha/README.md"]
        self.assertEqual((alpha["title"], alpha["summary"], alpha["task"], alpha["task_title"], alpha["source"]),
                         ("Alpha 调研", "第一段结论，说明为什么。", "proj-alpha-study", "Alpha 调研任务", "repo"))
        self.assertEqual(by["research/evidence/gamma/README.md"]["task"], "proj-gamma-1")
        # The local original stays the report; its redacted public copy only marks it. A public copy with no
        # original is listed, marked, and linked to a task only by what it says itself.
        self.assertEqual(alpha["published"], "published/alpha.md")
        public = by["research/published/only-public.md"]
        self.assertEqual((public["published"], public["source"], "task" in public), (True, "published", False))
        self.assertIn("删掉了私有细节", self.pm("file", "proj", "research/published/alpha.md")["text"])
        self.assertEqual((by["research/docs/research/beta.md"]["task"], by["research/docs/research/beta.md"]["title"]),
                         ("proj-beta-x", "Beta 新家"))  # the project's docs/research copy replaces evidence/beta
        self.assertEqual((by["research/docs/research/beta.md"]["source"],
                          by["research/docs/research/ledger-report.md"]["source"]), ("ledger", "ledger"))
        self.assertFalse(any(f["writable"] for f in lib["files"] if f["root"] != "docs" or f.get("archive")))

        doc = self.pm("file", "proj", "research/evidence/alpha/README.md")
        self.assertIn("第一段结论", doc["text"])
        self.assertTrue(doc["version"])
        self.assertIn("搬过来", self.pm("file", "proj", "research/docs/research/beta.md")["text"])
        self.assertIn("测试规矩", self.pm("file", "--root", "instructions", "--", "proj", ".claude/rules/tests.md")["text"])
        for bad in ("research/evidence/alpha/probe.sh", "instructions/.claude/rules/notes.txt",
                    "instructions/docs/guide.md", "docs/research/ledger-report.md", "docs/.history/old.md"):
            self.assertNotEqual(self.pm("file", "proj", bad, ok=False).returncode, 0, bad)

        self.assertEqual(self.pm("archive-decisions", "proj")["decisions"]["hidden"], True)
        hidden = {f["path"]: f for f in self.pm("library", "proj")["files"] if f["root"] == "docs"}
        self.assertTrue(hidden["decisions.md"]["hidden"])

    def test_docs_are_saved_deleted_restored_and_dropped_in_with_their_history(self):
        saved = self.pm("save", "proj", "docs/notes/plan.md", "--text", "# 计划\n\n第一版\n")
        self.assertTrue(saved["created"])
        again = self.pm("save", "proj", "docs/notes/plan.md", "--text", "# 计划\n\n第二版\n",
                        "--if-version", saved["version"])
        stale = self.pm("save", "proj", "docs/notes/plan.md", "--text", "# 冲突\n", "--if-version", saved["version"],
                        ok=False)
        self.assertEqual(stale.returncode, 4)
        self.assertEqual(json.loads(stale.stdout)["current"], again["version"])
        self.assertEqual(self.pm("history", "proj", "docs/notes/plan.md")["items"][0]["why"], "replaced")
        for refused in (["save", "proj", "docs/research/x.md", "--text", "x"],
                        ["save", "proj", "docs/decisions.md", "--text", "x"],
                        ["save", "proj", "docs/.hidden.md", "--text", "x"],
                        ["save", "proj", "docs/../escape.md", "--text", "x"],
                        ["save", "proj", "docs/pic.png", "--text", "x"],
                        ["save", "proj", "research/evidence/a/README.md", "--text", "x"],
                        ["save", "proj", "instructions/CLAUDE.md", "--text", "x"]):
            self.assertNotEqual(self.pm(*refused, ok=False).returncode, 0, refused)

        gone = self.pm("delete", "proj", "docs/notes/plan.md")
        self.assertTrue(gone["deleted"])
        self.assertFalse((self.root / "projects/proj/docs/notes/plan.md").exists())
        kept = self.pm("history", "proj", "--root", "docs")["items"]
        self.assertEqual([k["why"] for k in kept], ["deleted", "replaced"])
        self.assertEqual(len({k["version"] for k in kept}), 2)
        self.pm("restore", "proj", "docs/notes/plan.md")
        self.assertIn("第二版", (self.root / "projects/proj/docs/notes/plan.md").read_text())
        self.pm("restore", "proj", "docs/notes/plan.md", "--version", kept[1]["version"])
        self.assertIn("第一版", (self.root / "projects/proj/docs/notes/plan.md").read_text())

        drop = Path(self.tmp.name) / "设计 稿.md"
        drop.write_text("# 拖进来的\n")
        first = self.pm("add", "proj", str(drop))
        second = self.pm("add", "proj", str(drop), "--folder", "")
        self.assertEqual((first["path"], first["renamed"]), ("设计 稿.md", False))
        self.assertEqual((second["path"], second["renamed"]), ("设计 稿-2.md", True))
        replaced = self.pm("add", "proj", str(drop), "--replace")
        self.assertEqual((replaced["path"], replaced["replaced"]), ("设计 稿.md", True))
        exe = Path(self.tmp.name) / "tool.exe"
        exe.write_bytes(b"MZ")
        self.assertNotEqual(self.pm("add", "proj", str(exe), ok=False).returncode, 0)
        big = Path(self.tmp.name) / "big.pdf"
        with open(big, "wb") as f:
            f.truncate(store_mod.ADD_MAX + 1)
        self.assertIn("at most", self.pm("add", "proj", str(big), ok=False).stderr)
        self.assertNotEqual(self.pm("add", "proj", str(Path(self.tmp.name)), ok=False).returncode, 0)

    def test_memory_page_lists_both_layers_by_topic_and_edits_go_through_history(self):
        mem = self.root / "projects/proj/memory"
        self.put(mem, "no-right-angle-wires.md", '---\nname: no-right-angle-wires\ndescription: "连线不要直角"\n'
                                                 'metadata:\n  type: project\n  topic: ui\n  by: "pm"\n  quote: "不要直角线"\n---\n\n正文\n')
        self.put(mem, "hc-send-if.md", '---\nname: hc-send-if\ndescription: "hc send --if 只认 idle/working"\n'
                                      'metadata:\n  type: pitfall\n  verified: "实测"\n---\n\n正文\n')
        self.put(mem, "old-style.md", '---\nname: old-style\ndescription: "没有 topic 的旧记忆"\nmetadata:\n  type: feedback\n---\n')
        self.put(mem, "MEMORY.md", "- index\n")
        self.put(mem, "candidates/w1/tip.md", '---\nname: tip\ndescription: "候选"\nmetadata:\n  type: project\n---\n')
        (mem / "candidates/empty").mkdir(parents=True)
        self.put(self.root, "memory/reply-in-chinese.md",
                 '---\nname: reply-in-chinese\ndescription: "中文回复"\nmetadata:\n  type: feedback\n  quote: "中文"\n---\n')

        page = self.pm("memory", "proj")
        self.assertEqual([t["id"] for t in page["topics"]], ["architecture", "ui", "workflow", "ops", "reference", "pitfalls"])
        self.assertEqual([t["id"] for t in page["topics"] if t["folded"]], ["pitfalls"])
        self.assertEqual([t["id"] for t in page["types"]], ["project", "feedback", "reference", "pitfall", "user"])
        self.assertFalse(any("label" in t for t in page["topics"] + page["types"]))  # keys only: the UI translates
        rows = {(f["layer"], f["name"]): f for f in page["files"]}
        self.assertEqual(set(rows), {("project", "no-right-angle-wires"), ("project", "hc-send-if"),
                                     ("project", "old-style"), ("personal", "reply-in-chinese")})
        self.assertEqual((rows[("project", "hc-send-if")]["topic"], rows[("project", "no-right-angle-wires")]["topic"]),
                         ("pitfalls", "ui"))
        self.assertEqual((rows[("project", "old-style")]["topic"], rows[("project", "old-style")]["topic_inferred"]),
                         ("workflow", True))
        self.assertEqual([(c["worker"], c["name"]) for c in page["candidates"]], [("w1", "tip")])

        text = self.pm("file", "proj", "memory/no-right-angle-wires.md")
        edited = text["text"].replace("连线不要直角", "看板连线只用直线和曲线")
        row = self.pm("save", "proj", "memory/no-right-angle-wires.md", "--text", edited,
                      "--if-version", text["version"])
        self.assertEqual((row["description"], row["topic"], row["by"], row["quote"]),
                         ("看板连线只用直线和曲线", "ui", "pm", "不要直角线"))
        self.assertEqual(self.pm("save", "proj", "memory/no-right-angle-wires.md", "--text", edited,
                                 "--if-version", text["version"], ok=False).returncode, 4)
        body_only = self.pm("save", "proj", "memory/old-style.md", "--text", "新的正文")
        self.assertEqual(body_only["description"], "没有 topic 的旧记忆")
        for bad in ("---\nname: x\ndescription: d\nmetadata:\n  type: decision\n---\n",
                    "---\nname: x\ndescription: d\nmetadata:\n  type: project\n  topic: testing\n---\n",
                    "---\nname: x\ndescription: d\nmetadata:\n  type: project\n  topic: pitfalls\n---\n"):
            self.assertNotEqual(self.pm("save", "proj", "memory/new-one.md", "--text", bad, ok=False).returncode, 0)
        created = self.pm("save", "proj", "personal/short-replies.md", "--text",
                          '---\nname: short-replies\ndescription: "回复简短"\nmetadata:\n  type: feedback\n---\n\n正文\n')
        self.assertEqual((created["layer"], created["created"], created["topic"]), ("personal", True, "workflow"))
        moved = self.pm("retopic", "proj", "old-style", "--topic", "ops")
        self.assertEqual(moved["topic"], "ops")
        self.assertNotEqual(self.pm("retopic", "proj", "hc-send-if", "--topic", "ops", ok=False).returncode, 0)

        self.pm("delete", "proj", "memory/hc-send-if.md", "--why", "代码已修")
        self.assertFalse((mem / "hc-send-if.md").exists())
        kept = self.pm("history", "proj", "memory/hc-send-if.md")["items"]
        self.assertEqual(kept[0]["why"], "forgotten")
        self.pm("restore", "proj", "memory/hc-send-if.md")
        self.assertTrue((mem / "hc-send-if.md").exists())
        index = (mem / "MEMORY.md").read_text()
        self.assertIn("### Interface & interaction", index)
        self.assertNotIn("hc-send-if", index.split("(1 engineering pitfalls")[0])  # pitfalls go to briefs only
        self.assertFalse((mem / "candidates/empty").exists() and
                         (mem / "candidates/empty").stat().st_mtime < time.time() - CANDIDATE_GRACE)

    def test_research_migrate_is_a_dry_run_until_applied_and_never_overwrites(self):
        ev = self.repo / "evidence"
        ledger_research = self.root / "projects/proj/docs/research"
        self.put(ev, "alpha/README.md", "# Alpha\n\n![shot](shot.png) [web](https://example.com)\n")
        self.put(ev, "alpha/shot.png", b"\x89PNG")
        self.put(ev, "beta/README.md", "# Beta\n")
        self.put(ledger_research, "beta.md", "# 已有的不同版本\n")
        self.put(self.repo, "docs/research/alpha.md", "# 公开版\n")
        dry = self.pm("research-migrate", "proj")
        rows = {r["topic"]: r for r in dry["reports"]}
        self.assertEqual((dry["applied"], rows["alpha"]["status"], rows["beta"]["status"]), (False, "move", "exists"))
        self.assertEqual(rows["alpha"]["links_to_fix"], ["shot.png"])
        self.assertEqual(rows["alpha"]["dest"], str(ledger_research / "alpha.md"))  # the ledger, never the repo
        self.assertFalse((ledger_research / "alpha.md").exists())
        done = self.pm("research-migrate", "proj", "--apply")
        self.assertEqual({r["topic"]: r["status"] for r in done["reports"]}, {"alpha": "moved", "beta": "exists"})
        self.assertEqual((ledger_research / "beta.md").read_text(), "# 已有的不同版本\n")
        self.assertEqual((self.repo / "docs/research/alpha.md").read_text(), "# 公开版\n")
        self.assertTrue((ev / "alpha/README.md").exists())  # the evidence copy stays; the Library shows the new one
        research = {f["path"]: f for f in self.pm("library", "proj")["files"] if f["root"] == "research"}
        self.assertEqual(set(research), {"docs/research/alpha.md", "docs/research/beta.md"})
        self.assertEqual(research["docs/research/alpha.md"]["published"], "published/alpha.md")

    def test_repo_files_and_preview_allow_only_git_tracked_files(self):
        self.put(self.repo, "README.md", "# Demo Repo\n")
        self.put(self.repo, "src/app.py", "print('hello')\n")
        self.put(self.repo, ".gitignore", "ignored.log\n.env\n.claude/settings.local.json\n")
        self.put(self.repo, "ignored.log", "secret runtime log\n")
        self.put(self.repo, ".env", "API_KEY=secret-value\n")
        self.put(self.repo, ".claude/settings.local.json", '{"permissions":{"allow":["Bash(*)"]}}\n')
        self.put(self.repo, "untracked.md", "# Untracked\n")
        self.put(self.repo, "docs/中文 note.md", "# 中文笔记\n")
        self.put(self.repo, "bin.dat", b"\x00\x01\x02\x03")
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("outside secret\n", encoding="utf-8")
        (self.repo / "escape.txt").symlink_to(outside)
        (self.repo / "tracked-link.txt").symlink_to(outside)

        for cmd in (["git", "-C", str(self.repo), "init"],
                    ["git", "-C", str(self.repo), "config", "user.email", "t@example.com"],
                    ["git", "-C", str(self.repo), "config", "user.name", "Tester"],
                    ["git", "-C", str(self.repo), "add", "README.md", "src/app.py", ".gitignore",
                     "docs/中文 note.md", "bin.dat", "tracked-link.txt"]):
            r = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.assertEqual(r.returncode, 0)

        got = self.pm("files", "proj")
        self.assertEqual(got["project"], "proj")
        self.assertFalse(got["truncated"])
        self.assertIn("README.md", got["files"])
        self.assertIn("src/app.py", got["files"])
        self.assertIn(".gitignore", got["files"])
        self.assertIn("docs/中文 note.md", got["files"])
        self.assertNotIn("ignored.log", got["files"])
        self.assertNotIn(".env", got["files"])
        self.assertNotIn(".claude/settings.local.json", got["files"])
        self.assertNotIn("untracked.md", got["files"])
        self.assertFalse(any(p == ".git" or p.startswith(".git/") or "/.git/" in p for p in got["files"]))

        limited = self.pm("files", "proj", "--limit", "2")
        self.assertEqual(len(limited["files"]), 2)
        self.assertTrue(limited["truncated"])

        self.assertIn("hello", self.pm("file", "proj", "--root", "repo", "--", "src/app.py")["text"])
        self.assertIn(".env", self.pm("file", "proj", "--root", "repo", "--", ".gitignore")["text"])
        self.assertIn("中文笔记", self.pm("file", "proj", "--root", "repo", "--", "docs/中文 note.md")["text"])

        for bad in (
            ["file", "proj", "--root", "repo", "--", ".env"],
            ["file", "proj", "--root", "repo", "--", ".claude/settings.local.json"],
            ["file", "proj", "--root", "repo", "--", "ignored.log"],
            ["file", "proj", "--root", "repo", "--", "untracked.md"],
            ["file", "proj", "--root", "repo", "--", "*.py"],
            ["file", "proj", "--root", "repo", "--", "src"],
            ["file", "proj", "--root", "repo", "--", ".git/HEAD"],
            ["file", "proj", "--root", "repo", "--", "../outside.txt"],
            ["file", "proj", "--root", "repo", "--", "escape.txt"],
            ["file", "proj", "--root", "repo", "--", "tracked-link.txt"],
            ["file", "proj", "--root", "repo", "--", "bin.dat"],
            ["save", "proj", "repo/README.md", "--text", "overwrite"],
            ["delete", "proj", "repo/README.md"],
            ["restore", "proj", "repo/README.md"],
        ):
            self.assertNotEqual(self.pm(*bad, ok=False).returncode, 0, bad)

        self.assertNotEqual(self.pm("files", "missing-proj", ok=False).returncode, 0)

        # Non-git directories expose no repo files and allow no repo file preview.
        def _rm_readonly(func, p, _exc):
            os.chmod(p, 0o600)
            func(p)
        shutil.rmtree(self.repo / ".git", onerror=_rm_readonly)
        self.put(self.repo, "keep/hello.js", "export default 1;\n")
        nongit = self.pm("files", "proj")
        self.assertEqual(nongit, {"project": "proj", "files": [], "truncated": False})
        self.assertNotEqual(self.pm("file", "proj", "--root", "repo", "--", "README.md", ok=False).returncode, 0)

    def _init_git(self, repo: Path) -> None:
        for cmd in (["git", "-C", str(repo), "init"],
                    ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
                    ["git", "-C", str(repo), "config", "user.name", "Tester"],
                    ["git", "-C", str(repo), "add", "-A"]):
            subprocess.run(cmd, capture_output=True, text=True, check=True)

    def test_repo_docs_discovery_filtering_superseded_and_readonly(self):
        # Mix static site noise, media, framework dirs, i18n, boilerplate, cross-root files, and real docs.
        self.put(self.repo, "docs/index.html", "<html></html>\n")
        self.put(self.repo, "docs/.nojekyll", "")
        self.put(self.repo, "docs/demo.gif", b"GIF89a")
        self.put(self.repo, "docs/library.mp4", b"\x00\x00\x00\x18ftypmp42")
        self.put(self.repo, "docs/.vitepress/config.js", "export default {}\n")
        self.put(self.repo, "docs/_site/built.md", "# Built\n")
        self.put(self.repo, "docs/i18n/zh/a.md", "# 翻译\n")
        self.put(self.repo, "docs/CHANGELOG.md", "# Changelog\n")
        self.put(self.repo, "docs/research/r1.md", "# Research 1\n")
        self.put(self.repo, "CLAUDE.md", "# Claude rules\n")
        self.put(self.repo, "docs/design/auto-dream.md",
                 "# 后台记忆整理（autoDream）\n\n- **任务**：`proj-auto-dream`\n\n核心设计定稿摘要。\n")
        self.put(self.repo, "docs/guide.md", "# 使用指南\n\n快速上手。\n")
        outside = Path(self.tmp.name) / "secret.md"
        outside.write_text("# Secret\n", encoding="utf-8")
        (self.repo / "docs" / "escape.md").symlink_to(outside)
        self._init_git(self.repo)
        # Untracked file in git repo must not be listed or readable.
        self.put(self.repo, "docs/untracked-draft.md", "# Untracked\n")
        self.task("proj-auto-dream", title="autoDream 设计定稿")

        # Ledger drafts: auto-dream-draft.md matches normalized stem; explicit frontmatter overrides; generic names do not.
        ledger = self.root / "projects/proj"
        self.put(ledger, "docs/auto-dream-draft.md", "# autoDream 草稿\n\n旧版本。\n")
        self.put(ledger, "docs/custom-alias.md", "---\nsuperseded_by: docs/guide.md\n---\n# 别名草稿\n")
        self.put(ledger, "docs/notes.md", "# 随手笔记\n")
        self.put(ledger, "docs/README.md", "# 台账说明\n")

        lib = self.pm("library", "proj")
        roots = {r["id"]: r for r in lib["roots"]}
        self.assertEqual(roots["repo_docs"], {"id": "repo_docs", "writable": False, "truncated": False, "total": 2})

        repo_docs = {f["path"]: f for f in lib["files"] if f["root"] == "repo_docs"}
        self.assertEqual(set(repo_docs), {"docs/design", "docs/design/auto-dream.md", "docs/guide.md"})
        self.assertEqual(repo_docs["docs/design"]["kind"], "folder")
        self.assertFalse(repo_docs["docs/design"]["writable"])
        ad = repo_docs["docs/design/auto-dream.md"]
        self.assertEqual((ad["title"], ad["summary"], ad["task"], ad["task_title"], ad["writable"]),
                         ("后台记忆整理（autoDream）", "核心设计定稿摘要。", "proj-auto-dream", "autoDream 设计定稿", False))
        # No cross-root duplication: research/r1.md stays in research, CLAUDE.md stays in instructions.
        self.assertIn("published/r1.md", {f["path"] for f in lib["files"] if f["root"] == "research"})
        self.assertIn("CLAUDE.md", {f["path"] for f in lib["files"] if f["root"] == "instructions"})

        # Superseded_by annotations on ledger docs.
        ledger_docs = {f["path"]: f for f in lib["files"] if f["root"] == "docs"}
        self.assertEqual(ledger_docs["auto-dream-draft.md"].get("superseded_by"), "docs/design/auto-dream.md")
        self.assertEqual(ledger_docs["custom-alias.md"].get("superseded_by"), "docs/guide.md")
        self.assertNotIn("superseded_by", ledger_docs["notes.md"])
        self.assertNotIn("superseded_by", ledger_docs["README.md"])

        # Reading allowed repo_docs works; disallowed paths and writes are rejected.
        got = self.pm("file", "proj", "--root", "repo_docs", "--", "docs/design/auto-dream.md")
        self.assertIn("核心设计定稿摘要", got["text"])
        self.assertTrue(got["version"])
        self.assertIn("使用指南", self.pm("file", "proj", "repo_docs/docs/guide.md")["text"])

        for bad in (
            ["file", "proj", "--root", "repo_docs", "--", "docs/index.html"],
            ["file", "proj", "--root", "repo_docs", "--", "docs/CHANGELOG.md"],
            ["file", "proj", "--root", "repo_docs", "--", "docs/research/r1.md"],
            ["file", "proj", "--root", "repo_docs", "--", "docs/escape.md"],
            ["file", "proj", "--root", "repo_docs", "--", "docs/untracked-draft.md"],
            ["file", "proj", "--root", "repo_docs", "--", ".git/config"],
            ["file", "proj", "--root", "repo_docs", "--", "CLAUDE.md"],
            ["save", "proj", "repo_docs/docs/guide.md", "--text", "hack"],
            ["delete", "proj", "repo_docs/docs/guide.md"],
            ["restore", "proj", "repo_docs/docs/guide.md"],
        ):
            self.assertNotEqual(self.pm(*bad, ok=False).returncode, 0, bad)

    def test_repo_docs_singular_doc_rfcs_architecture_and_nongit_fallback(self):
        # Non-git repo with singular `doc/`, root `rfcs/`, and `ARCHITECTURE.md`.
        self.put(self.repo, "doc/manual.md", "# Manual\n")
        self.put(self.repo, "rfcs/0001-protocol.md", "# RFC 0001\n")
        self.put(self.repo, "ARCHITECTURE.md", "# System Architecture\n")
        self.put(self.repo, "README.md", "# Root README not included by default\n")

        lib = self.pm("library", "proj")
        paths = {f["path"] for f in lib["files"] if f["root"] == "repo_docs" and f["kind"] != "folder"}
        self.assertEqual(paths, {"doc/manual.md", "rfcs/0001-protocol.md", "ARCHITECTURE.md"})
        self.assertIn("System Architecture", self.pm("file", "proj", "repo_docs/ARCHITECTURE.md")["text"])

    def test_repo_docs_tier_cap_and_cli_config(self):
        # 5 Tier-1 design docs + 205 Tier-3 guides -> total 210, truncated to 200 with all 5 Tier-1 preserved.
        for i in range(5):
            self.put(self.repo, f"docs/design/spec-{i}.md", f"# Design {i}\n")
        for i in range(205):
            self.put(self.repo, f"docs/guides/g-{i:03d}.md", f"# Guide {i}\n")
        self.put(self.repo, "packages/core/docs/core.md", "# Core\n")
        self.put(self.repo, "README.md", "# Root README\n")
        self._init_git(self.repo)

        lib = self.pm("library", "proj")
        rd_root = next(r for r in lib["roots"] if r["id"] == "repo_docs")
        self.assertTrue(rd_root["truncated"])
        self.assertEqual(rd_root["total"], 210)
        rd_files = [f["path"] for f in lib["files"] if f["root"] == "repo_docs" and f["kind"] != "folder"]
        self.assertEqual(len(rd_files), 200)
        for i in range(5):
            self.assertIn(f"docs/design/spec-{i}.md", rd_files)

        # CLI `project repo-docs`: inspect, include/exclude, off/on, reset.
        cfg0 = self.pm("repo-docs", "proj")
        self.assertTrue(cfg0["enabled"])
        self.assertFalse(cfg0["custom"])
        self.assertEqual(cfg0["entries"], ["docs"])

        cfg1 = self.pm("repo-docs", "proj", "--include", "packages/core/docs", "--include", "README.md",
                       "--exclude", "docs/guides")
        self.assertTrue(cfg1["custom"])
        self.assertEqual(cfg1["include"], ["packages/core/docs", "README.md"])
        lib1 = self.pm("library", "proj")
        paths1 = {f["path"] for f in lib1["files"] if f["root"] == "repo_docs" and f["kind"] != "folder"}
        self.assertEqual(paths1, {"packages/core/docs/core.md", "README.md"})

        cfg_off = self.pm("repo-docs", "proj", "--off")
        self.assertFalse(cfg_off["enabled"])
        self.assertEqual([f for f in self.pm("library", "proj")["files"] if f["root"] == "repo_docs"], [])

        cfg_reset = self.pm("repo-docs", "proj", "--reset")
        self.assertTrue(cfg_reset["enabled"])
        self.assertFalse(cfg_reset["custom"])
        self.assertEqual(cfg_reset["include"], [])


class DashTurnWireEventsTests(unittest.TestCase):
    """Phase 5: pm-dash prompt/reply wire events come from `pm-turn-journal.jsonl` (+ 1-version `turns.log` fallback)."""

    def test_dash_state_emits_prompt_reply_wires_from_turn_journal_and_ignores_stale_turns_log(self) -> None:
        from pmlib.home import project_slug
        from pmlib.project.turn_state import TurnTracker
        from pmlib.views.state import dash_state

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_a = root / "alpha"
            repo_b = root / "legacy-beta"
            repo_a.mkdir()
            repo_b.mkdir()
            clk = FakeClock("2026-11-26 22:00:00")
            ctx = make_ctx(root / "ledger", clock=clk)
            slug_a = project_slug(repo_a)
            slug_b = project_slug(repo_b)
            ctx.home.registrations.mkdir(parents=True, exist_ok=True)
            ctx.home.registration(slug_a).write_text(json.dumps({
                "name": "pm-alpha", "project": "alpha", "repo": str(repo_a),
                "runtime": "hc", "terminal": "t7", "pane": "hc:t7", "agent": "claude",
            }), encoding="utf-8")
            ctx.home.registration(slug_b).write_text(json.dumps({
                "name": "pm-beta", "project": "beta", "repo": str(repo_b),
                "runtime": "hc", "terminal": "t8", "pane": "hc:t8", "agent": "claude",
            }), encoding="utf-8")

            tracker_a = TurnTracker(ctx, str(repo_a))
            t0_ms = int(clk.time() * 1000)
            tracker_a.append_observation({"src": "hook", "kind": "hook_prompt", "t": t0_ms, "cause": "user"}, reduce_now=True)
            tracker_a.append_observation({"src": "hook", "kind": "hook_stop", "t": t0_ms + 5000, "has_reply": True}, reduce_now=True)

            # Put a stale turns.log line for pm-alpha (must be ignored) and a legacy turns.log line for unupgraded pm-beta.
            ctx.home.turn_log.write_text(
                "2026-11-20 01:00 [hc:t7] UserPromptSubmit: turn\n"
                "2026-11-26 21:59 [hc:t8] Stop: turn\n",
                encoding="utf-8",
            )

            st = dash_state(ctx)
            alpha_wires = [e for e in st["events"] if e.get("pm") == "pm-alpha" and e.get("kind") in ("prompt", "reply")]
            self.assertEqual([e["kind"] for e in alpha_wires], ["prompt", "reply"])
            self.assertFalse(any("2026-11-20" in e.get("at", "") for e in alpha_wires))
            beta_wires = [e for e in st["events"] if e.get("pm") == "pm-beta" and e.get("kind") in ("prompt", "reply")]
            self.assertEqual([(e["kind"], e["at"]) for e in beta_wires], [("reply", "2026-11-26 21:59")])


if __name__ == "__main__":
    unittest.main()
