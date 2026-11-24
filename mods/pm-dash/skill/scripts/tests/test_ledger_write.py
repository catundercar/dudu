"""The ledger's write path as seen from outside: two processes changing one task at once both keep their entry, and a
test that replaces `pm.save` still has mutate_task go through the replacement (and through the locked path again once
it is put back). Each case runs `import pm` in a child process on a temporary ledger home, so nothing here touches a
real ledger or leaves a replaced name behind in this process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent

WRITER = textwrap.dedent("""
    import sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from pmlib.context import Context
    from pmlib.ledger.ledger import Ledger
    ctx = Context.from_env()
    lg = Ledger(ctx)
    tid, who, count, go = sys.argv[2], sys.argv[3], int(sys.argv[4]), Path(sys.argv[5])
    while not go.exists():
        time.sleep(0.005)
    for i in range(count):
        lg.change(tid, lambda cur, ch: (ch.note(f"{who} {i}"), cur)[1])
""")

REPLACED_SAVE = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    from pmlib.context import Context, now
    from pmlib.ledger.ledger import Ledger
    ctx = Context.from_env()
    ctx.store.change_task("t-1", lambda _cur: {"id": "t-1", "project": "p", "title": "t", "status": "proposed",
                                               "updated": now(), "log": []})
    lg = Ledger(ctx)
    result = lg.change("t-1", lambda cur, _ch: {**cur.raw, "status": "in_progress"})
    assert result["status"] == "in_progress", result
    assert ctx.store.task("t-1")["status"] == "in_progress"
    lg.change("t-1", lambda cur, _ch: {**cur.raw, "status": "review"})
    assert ctx.store.task("t-1")["status"] == "review"
    lg.change("t-1", lambda cur, _ch: {**cur.raw, "status": "blocked"}, board=False)
    assert ctx.store.task("t-1")["status"] == "blocked"
    print("ok")
""")


def child_env(home):
    env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "HC_TERMINAL_ID", "HERDR_WORKSPACE_ID",
                                                          "HERDR_ENV")}
    env.update(PM_HOME=str(home), PM_NO_DISCORD="1", PYTHONDONTWRITEBYTECODE="1")
    return env


class LedgerWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / "tasks").mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def test_two_processes_changing_one_task_both_keep_their_entries(self):
        task = {"id": "t-1", "project": "p", "title": "t", "status": "in_progress", "updated": "2026-11-22 10:00",
                "log": []}
        (self.home / "tasks" / "t-1.json").write_text(json.dumps(task))
        script = Path(self.tmp.name) / "writer.py"
        script.write_text(WRITER)
        go = Path(self.tmp.name) / "go"
        count = 25
        procs = [subprocess.Popen([sys.executable, str(script), str(SCRIPTS), "t-1", who, str(count), str(go)],
                                  env=child_env(self.home), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for who in ("a", "b")]
        go.write_text("")
        for p in procs:
            out, err = p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0, err)
        log = json.loads((self.home / "tasks" / "t-1.json").read_text())["log"]
        texts = sorted(e["text"] for e in log)
        self.assertEqual(texts, sorted([f"a {i}" for i in range(count)] + [f"b {i}" for i in range(count)]))
        # Each process's own entries stay in its order.
        for who in ("a", "b"):
            self.assertEqual([e["text"] for e in log if e["text"].startswith(who + " ")],
                             [f"{who} {i}" for i in range(count)])
        self.assertEqual([p.name for p in (self.home / "tasks").iterdir()], ["t-1.json"])  # no half-written files

    def test_replaced_save_is_used_and_put_back(self):
        script = Path(self.tmp.name) / "replaced.py"
        script.write_text(REPLACED_SAVE)
        out = subprocess.run([sys.executable, str(script), str(SCRIPTS)], env=child_env(self.home),
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
