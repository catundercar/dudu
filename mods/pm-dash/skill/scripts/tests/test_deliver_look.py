"""The deliverer's look as it runs for real, outside the replay (which holds deliver.lock and so never reaches the
loop): two looks at a PM behind a fake hc, one with an event waiting (sent as one batch, the mark moved over it) and
one without (nothing sent, the mark moved over what is not news). And a replaced `mark_fn` reaches the deliverer's
loop. Each case runs in a child process on a temporary ledger home, so nothing here touches a real ledger."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent

PRELUDE = textwrap.dedent("""
    import contextlib, io, json, sys, tempfile
    from pathlib import Path
    from unittest import mock
    sys.path.insert(0, sys.argv[1])
    import pmlib.cli  # ensure full startup registrations (seat_alive, deliver_watchers)
    from pmlib import hooks, procs
    from pmlib.context import Context
    from pmlib.events.deliverer import Deliverer
    from pmlib.manager import seat as manager_seat
    from pmlib.terminals.events import RECONCILE
    from pmlib.gitrepo import project_root
    from pmlib.home import project_slug
    from pmlib.project.conversation import Conversation
    from pmlib.project.project import ProjectRegistry, pm_name
    from pmlib.terminals.hc import HcHost

    repo = project_root(tempfile.mkdtemp(dir=sys.argv[2]))
    name = Path(repo).name
    calls = []

    def hc(*args, **kw):
        calls.append(args)
        if args[0] == "get" and args[1] == "t7":
            return {"state": "live", "labels": {"pm": name}, "status": {"state": "idle"}}
        if args[0] == "send":
            return {"started": True}
        return {}

    class Looks:
        terminals = None
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def wait(self, timeout):
            return True

    ctx = Context.from_env(env={**dict(__import__("os").environ), "HC_TERMINAL_ID": "t7"})
    assert ctx.seat_alive is not None
    assert [w.name for w in ctx.deliver_watchers] == ["helpers", "dependencies"], ctx.deliver_watchers
    assert len(ctx.deliver_holds) == 1, ctx.deliver_holds
    # Work around R4-P0 (`procs.py:322` passes unexpected `ctx=ctx` to `seat.next_session_ready`; covered by
    # `@expectedFailure` in `test_final_review_r4_repros.py`) so the rest of `TWO_LOOKS` still exercises real hold logic:
    ctx.deliver_holds = (lambda r: manager_seat._next_session_ready_impl(r, ctx=ctx),)
    ctx.hc = HcHost(runner=hc)
    ctx.home.registrations.mkdir(parents=True, exist_ok=True)
    (ctx.home.registrations / f"{project_slug(repo)}.json").write_text(json.dumps(
        {"name": pm_name(repo), "project": name, "repo": repo, "pane": "hc:t7", "runtime": "hc",
         "terminal": "t7", "agent": "claude"}))
    ctx.procs.spawn_pm = lambda *a, **kw: None
    dlv = Deliverer(ctx, repo, settle=0)
    conv = Conversation(ctx, repo)

    def size():
        return ctx.home.project_for(repo).conversation.stat().st_size
""")

TWO_LOOKS = PRELUDE + textwrap.dedent("""
    dlv.start_mark(ProjectRegistry(ctx).app_pm(repo))
    conv.record("event", by="ci", text="the nightly build broke", source="external:ci", wake=True)
    changes, stops = Looks(), {}
    due = dlv.look(changes, stops)
    assert changes.terminals == {"t7"}, changes.terminals
    sends = [c for c in calls if c[0] == "send"]
    assert len(sends) == 1, calls
    assert sends[0][1:3] == ("--if", "idle") and sends[0][3] == "t7", sends[0]
    assert "the nightly build broke" in sends[0][4] and sends[0][4].startswith("[from pm.py deliver] "), sends[0][4]
    assert due == 0, due
    first_end = size()
    assert dlv.delivered_offset() == first_end, (dlv.delivered_offset(), first_end)
    assert dlv.received_ranges() == [], dlv.received_ranges()

    # PM turn hook arrives AFTER deliver_look already advanced delivered_offset: first receipt must not warn repeat
    # on stdout, while the exact same batch arriving a second time DOES emit the repeat warning on stdout.
    hook_payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": sends[0][4], "cwd": repo})
    out1 = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(hook_payload)), contextlib.redirect_stdout(out1):
        hooks.cmd_hook_turn(None, ctx=ctx)
    assert out1.getvalue() == "", out1.getvalue()
    assert dlv.received_ranges() == [[0, first_end]], dlv.received_ranges()

    out2 = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(hook_payload)), contextlib.redirect_stdout(out2):
        hooks.cmd_hook_turn(None, ctx=ctx)
    assert "repeat" in out2.getvalue(), out2.getvalue()
    r2 = dlv.took_delivery(sends[0][4])
    assert r2 and r2.repeated and "repeat" in (r2.warning or ""), r2

    calls.clear()
    conv.record("event", by="ci", text="a line that is not news", source="external:ci", wake=False)
    assert dlv.delivered_offset() < size()
    due = dlv.look(changes, stops)
    assert [c for c in calls if c[0] == "send"] == [], calls
    assert [c[:2] for c in calls] == [("get", "t7")], calls
    assert due == RECONCILE, due
    assert dlv.delivered_offset() == size(), (dlv.delivered_offset(), size())
    assert dlv.received_ranges() == [[0, first_end]], dlv.received_ranges()
    print("ok")
""")

REPLACED_MARK = PRELUDE + textwrap.dedent("""
    assert dlv.current_script_mark() == procs.code_mark()
    ctx.hc.change_waiter = lambda *a, **kw: Looks()
    marks = iter(["old", "old", "new"])
    dlv2 = Deliverer(ctx, repo, gap=0, script_mark_fn=lambda: next(marks, "new"))
    assert dlv2.run() is True          # an install replaced the code: hand over
    assert next(marks, None) is None   # every mark was asked for, through the replacement
    assert dlv.current_script_mark() == procs.code_mark()
    print("ok")
""")


class DeliverLook(unittest.TestCase):
    def run_child(self, script):
        with tempfile.TemporaryDirectory(prefix="pm-deliver-look-") as home:
            env = {k: v for k, v in os.environ.items() if k not in ("HC_TERMINAL_ID", "HERDR_PANE_ID", "PM_REAL_HOME")}
            env["PM_HOME"] = str(Path(home) / "pm")
            done = subprocess.run([sys.executable, "-c", script, str(SCRIPTS), home], env=env, cwd=home,
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(done.stdout.strip().splitlines()[-1:], ["ok"], done.stdout + done.stderr)

    def test_two_looks_send_what_waits_then_move_the_mark_over_what_is_not_news(self):
        self.run_child(TWO_LOOKS)

    def test_a_replaced_script_mark_reaches_the_deliverers_loop(self):
        self.run_child(REPLACED_MARK)


if __name__ == "__main__":
    unittest.main()
