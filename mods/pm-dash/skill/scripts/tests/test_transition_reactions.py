"""Characterization of `pm.py update` (cmd_update): its two silent fast paths and every post-save reaction, row by row
(pm-py-pass-two.md, sections 3.2 and 3.3).

Each case runs the real `pm.py` in a subprocess against a fresh temporary ledger (PM_HOME), git repository and a fake
`hc` (fake_hc.py) on a PATH that holds nothing else but the system folders. A `sitecustomize` module put on the
child's PYTHONPATH records every detached `pm.py` it would start in the background (deliverer, close-worker) instead
of starting it, so the background work shows up as an ordered list of argv and never runs.

Per case the test compares, after normalizing the run's folder and timestamps:
  exit code, stdout, stderr, the hc calls of the step (in order), the background spawns (in order), and the ledger:
  tasks/*.json, projects/<slug>/conversation.jsonl, BOARD.md, the project's memory candidates folders.
against tests/golden/transition_reactions.json, and also spells out the lines each reaction row is about.

Regenerate the golden file (only when a behavior change is intended): TRANSITION_GOLDEN=write python3 -m unittest
tests/test_transition_reactions.py. POSIX only (fake_hc.py uses fcntl).
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
PM = SCRIPTS / "pm.py"
FAKE_HC = HERE / "fake_hc.py"
GOLDEN = HERE / "golden" / "transition_reactions.json"
WRITE = os.environ.get("TRANSITION_GOLDEN") == "write"
PROJECT = "demo"
PM_TERM, WORKER_TERM, REVIEWER_TERM = "t1", "t2", "t3"
AS_PM = {"HC_TERMINAL_ID": PM_TERM}
AS_WORKER = {"HC_TERMINAL_ID": WORKER_TERM}
AS_REVIEWER = {"HC_TERMINAL_ID": REVIEWER_TERM}
GIT_ENV = {"GIT_AUTHOR_NAME": "Trace", "GIT_AUTHOR_EMAIL": "trace@example.invalid",
           "GIT_COMMITTER_NAME": "Trace", "GIT_COMMITTER_EMAIL": "trace@example.invalid",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
           "GIT_CONFIG_NOSYSTEM": "1"}

# Loaded by the child interpreter at startup (site.py imports `sitecustomize` from PYTHONPATH): a detached pm.py
# (`[python, <pm.py>, ...]` with stdin=DEVNULL) is logged and not started; everything else (hc, git) runs.
SITECUSTOMIZE = r'''
import json, os, subprocess
_LOG = os.environ.get("TRACE_SPAWN_LOG")
if _LOG:
    _Popen = subprocess.Popen

    class _NotStarted:
        pid, returncode, stdin, stdout, stderr = 0, 0, None, None, None
        def poll(self): return 0
        def wait(self, timeout=None): return 0
        def communicate(self, input=None, timeout=None): return (None, None)
        def kill(self): pass
        def terminate(self): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    class _Popen2(_Popen):
        def __new__(cls, args, *rest, **kw):
            argv = [str(x) for x in args] if isinstance(args, (list, tuple)) else [str(args)]
            if len(argv) > 1 and os.path.basename(argv[1]) == "pm.py" and kw.get("stdin") == subprocess.DEVNULL:
                with open(_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(["pm.py", *argv[2:]]) + "\n")
                return _NotStarted()
            return _Popen.__new__(cls)

    subprocess.Popen = _Popen2
'''

TIME = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")
# The board clips its Latest cell to a width, so where a path in it ends depends on the run folder's length: from the
# path to the end of the cell is one token.
CLIPPED_PATH = re.compile(r"(?<= )(?:/|<ROOT>)[^|]*(?= \|$)", re.M)
RULES = [
    (TIME, "<TIME>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "<DATE>"),
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"), "<HH:MM>"),
    (re.compile(r"\b1[6-9]\d{8}(?:\.\d+)?\b"), "<EPOCH>"),
    (re.compile(r"\b1[6-9]\d{11,18}\b"), "<EPOCH>"),
    (re.compile(r"(\"pid\":\s*)\d+"), r"\1<PID>"),
    (re.compile(r"(send|msg|brief|tmp)-\d+-\d+"), r"\1-<PID>-<N>"),
    (re.compile(r"\.\d+\.tmp\b"), ".<PID>.tmp"),
    (re.compile(r"\b\d+(?:\.\d+)? ?(?:ms|s|sec|secs|seconds|m|min|mins|minutes|h|hours?) ago\b"), "<AGO>"),
    (re.compile(r"\b\d{2}-\d{2}(?= <HH:MM>)"), "<MM-DD>"),  # the board's Updated column
    (re.compile(r"\benv_[0-9a-f]{12}_[0-9a-f]{8}\b"), "<ENV>"),  # an envelope's id (time + random)
]


class Bench:
    """One temporary ledger, home, git repository `demo`, fake hc and spawn log."""

    def __init__(self, base):
        self.root = Path(base)
        self.home, self.ledger, self.repo = self.root / "home", self.root / "ledger", self.root / PROJECT
        self.bin, self.site = self.root / "bin", self.root / "site"
        for folder in (self.home, self.ledger, self.repo, self.bin, self.site, self.root / "tmp"):
            folder.mkdir(parents=True)
        (self.bin / "hc").write_text(f"#!{sys.executable}\n" + FAKE_HC.read_text(encoding="utf-8"), encoding="utf-8")
        (self.bin / "hc").chmod(0o755)
        (self.bin / "python3").symlink_to(sys.executable)
        git = shutil.which("git")
        if git:
            (self.bin / "git").symlink_to(git)
        (self.site / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        self.hc_state, self.hc_log = self.root / "hc-state.json", self.root / "hc-calls.jsonl"
        self.spawn_log = self.root / "spawns.jsonl"
        self.hc_state.write_text(json.dumps({"terminals": {}, "next": 10}))
        for log in (self.hc_log, self.spawn_log):
            log.write_text("")
        self.env = {
            "HOME": str(self.home), "PM_HOME": str(self.ledger), "TMPDIR": str(self.root / "tmp"),
            "PATH": os.pathsep.join([str(self.bin), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
            "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8", "PM_NO_DISCORD": "1", "FAKE_HC_STATE": str(self.hc_state),
            "FAKE_HC_LOG": str(self.hc_log), "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
            "PYTHONPATH": str(self.site), "TRACE_SPAWN_LOG": str(self.spawn_log), **GIT_ENV,
        }
        self.roots = sorted({str(self.root), os.path.realpath(self.root)}, key=len, reverse=True)
        # Where this copy of the scripts and this Python live (a brief names `<scripts>/pm.py`): not the run's folder,
        # and different in a worktree, the main checkout or an installed copy.
        self.places = sorted({(str(SCRIPTS), "<SCRIPTS>"), (os.path.realpath(SCRIPTS), "<SCRIPTS>"),
                              (sys.executable, "<PYTHON>"), (os.path.realpath(sys.executable), "<PYTHON>")},
                             key=lambda pair: len(pair[0]), reverse=True)

    # --- setup helpers (not compared) ---

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=str(cwd or self.repo), env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def init_repo(self):
        self.git("init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("# demo\n")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "initial")
        self.git("checkout", "-q", "-b", "feature")
        (self.repo / "app.py").write_text("print('hello')\n")
        self.git("add", "app.py")
        self.git("commit", "-q", "-m", "feature: hello")
        self.git("checkout", "-q", "main")

    def worktree(self, branch="feature"):
        path = self.root / "wt" / branch
        path.parent.mkdir(exist_ok=True)
        self.git("worktree", "add", "-q", str(path), branch)
        return path

    def terminal(self, address, **fields):
        state = json.loads(self.hc_state.read_text())
        base = {"state": "live", "name": address, "cwd": str(self.repo), "argv": ["claude"],
                "foreground": {"argv": ["claude"]}, "labels": {}, "status": {"state": "idle"}}
        state["terminals"][address] = {**base, **fields}
        self.hc_state.write_text(json.dumps(state, indent=1, sort_keys=True))

    def config(self, value):
        (self.ledger / "config.json").write_text(json.dumps(value))

    def task_path(self, task_id):
        return self.ledger / "tasks" / f"{task_id}.json"

    def task(self, task_id):
        return json.loads(self.task_path(task_id).read_text(encoding="utf-8"))

    def edit(self, task_id, drop=(), **fields):
        task = self.task(task_id)
        task.update(fields)
        for key in drop:
            task.pop(key, None)
        self.task_path(task_id).write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def setup(self, argv, env=None):
        out = self._run(argv, env)
        if out.returncode:
            raise AssertionError(f"setup step failed: pm.py {' '.join(argv)}\n{out.stdout}\n{out.stderr}")
        return out.stdout.strip()

    def claim(self):
        self.terminal(PM_TERM, name="pm")
        self.setup(["claim"], AS_PM)

    # --- the step under test ---

    def _run(self, argv, env=None, stdin=""):
        return subprocess.run([sys.executable, str(PM), *argv], cwd=str(self.repo), env={**self.env, **(env or {})},
                              input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=120)

    def step(self, argv, env=None):
        """Run one `pm.py` command and return everything the case compares, normalized."""
        marks = {p: p.stat().st_size for p in (self.hc_log, self.spawn_log)}
        out = self._run(argv, env)

        def lines_since(path):
            with open(path, encoding="utf-8") as f:
                f.seek(marks[path])
                return [json.loads(line) for line in f.read().splitlines() if line.strip()]

        hc_calls = lines_since(self.hc_log)
        spawns = lines_since(self.spawn_log)
        return self.norm_obj({"exit": out.returncode, "stdout": out.stdout, "stderr": out.stderr, "hc": hc_calls,
                              "spawns": spawns, "ledger": self.ledger_tree()})

    def ledger_tree(self):
        files = {}
        for path in sorted((self.ledger / "tasks").glob("*.json")):
            files[f"tasks/{path.name}"] = path.read_text(encoding="utf-8")
        for rel in (f"projects/{PROJECT}/conversation.jsonl", "BOARD.md"):
            path = self.ledger / rel
            files[rel] = path.read_text(encoding="utf-8") if path.exists() else None
        if files["BOARD.md"]:
            files["BOARD.md"] = CLIPPED_PATH.sub("<PATH>", self.norm(files["BOARD.md"]))
        cand = self.ledger / "projects" / PROJECT / "memory" / "candidates"
        files["candidates/"] = sorted(p.name for p in cand.iterdir()) if cand.is_dir() else None
        return files

    def norm(self, text):
        for root in self.roots:
            text = text.replace(root, "<ROOT>")
        for place, token in self.places:
            text = text.replace(place, token)
        for pattern, replacement in RULES:
            text = pattern.sub(replacement, text)
        return text

    def norm_obj(self, value):
        if isinstance(value, str):
            return self.norm(value)
        if isinstance(value, list):
            return [self.norm_obj(v) for v in value]
        if isinstance(value, dict):
            return {k: self.norm_obj(v) for k, v in value.items()}
        return value


def load_golden():
    if WRITE or not GOLDEN.exists():
        return {}
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


_GOLDEN = load_golden()
_WRITTEN = {}


def tearDownModule():
    if WRITE and _WRITTEN:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        merged = {**json.loads(GOLDEN.read_text(encoding="utf-8")), **_WRITTEN} if GOLDEN.exists() else _WRITTEN
        GOLDEN.write_text(json.dumps(dict(sorted(merged.items())), indent=1, ensure_ascii=False) + "\n",
                          encoding="utf-8")


@unittest.skipIf(os.name == "nt", "fake_hc.py needs fcntl")
class TransitionReactions(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="pm-trace-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.b = Bench(tmp)
        self.b.init_repo()

    def golden(self, got):
        """Compare the whole normalized step with the golden file (or record it with TRANSITION_GOLDEN=write)."""
        key = self.id().rsplit(".", 1)[-1]
        if WRITE:
            _WRITTEN[key] = got
            return
        self.assertIn(key, _GOLDEN, f"no golden entry for {key}: run with TRANSITION_GOLDEN=write")
        want = _GOLDEN[key]
        for part in ("exit", "stdout", "stderr", "hc", "spawns"):
            self.assertEqual(got[part], want[part], f"{key}: {part}")
        self.assertEqual(got["ledger"], want["ledger"], f"{key}: ledger")

    def new(self, title, slug, *extra, env=AS_PM):
        return self.b.setup(["new", title, "--slug", slug, *extra], env)

    def worker_task(self, slug="work", *extra, **fields):
        """A task whose worker runs in hc:t2, as `dispatch` records one."""
        tid = self.new("Work", slug, "--pane", f"hc:{WORKER_TERM}", "--workspace", "", "--branch", "feature", *extra)
        self.b.edit(tid, **{"dispatched": True, "worker_pane": f"hc:{WORKER_TERM}", **fields})
        self.b.terminal(WORKER_TERM, name="work", labels={"task": tid})
        return tid

    # --- fast path 1: --step-done alone ---

    def test_fast_path_step_done(self):
        self.b.claim()
        tid = self.new("Plan", "plan", "--plan", "[>] build; [ ] check")
        got = self.b.step(["update", tid, "--step-done"], AS_PM)
        self.assertEqual(got["stdout"], f"{tid}: in_progress (plan 1/2, next: check)\n")
        self.assertEqual(got["spawns"], [])
        self.golden(got)

    # --- fast path 2: a worker's own --plan alone (subplan) ---

    def test_fast_path_worker_subplan(self):
        self.b.claim()
        tid = self.worker_task()
        got = self.b.step(["update", tid, "--plan", "[x] read; [>] write; [ ] test"], AS_WORKER)
        self.assertEqual(got["stdout"], f"{tid}: in_progress (subplan 1/3)\n")
        self.assertEqual(got["spawns"], [])
        self.golden(got)

    # --- row 1 (wake: deliver_later) and row 7 (close_reported, with a note on the task) ---

    def test_row1_wake_and_row7_close_reported(self):
        self.b.config({"workers": {"close_reported": True}})
        self.b.claim()
        tid = self.worker_task()
        got = self.b.step(["update", tid, "--status", "review", "--note", "ready for review"], AS_WORKER)
        self.assertEqual(got["stdout"], f"{tid}: review\n")
        self.assertEqual([s[1] for s in got["spawns"]], ["deliver", "close-worker"])
        self.assertIn("--while", got["spawns"][1])
        self.assertIn("workers.close_reported", self.b.task(tid)["log"][-1]["text"])
        self.golden(got)

    # --- row 2: research reports collected from the worker's worktree ---

    def test_row2_collect_research(self):
        self.b.claim()
        tid = self.worker_task()
        wt = self.b.worktree()
        self.b.edit(tid, worktree=str(wt))
        report = wt / "evidence" / "probe" / "README.md"
        report.parent.mkdir(parents=True)
        report.write_text("# Probe\n\nFound it.\n")
        got = self.b.step(["update", tid, "--status", "blocked", "--note", "need a decision"], AS_WORKER)
        self.assertEqual(got["stdout"].splitlines()[0], f"{tid}: blocked")
        self.assertIn(f"{tid}: collected research: probe", got["stdout"])
        self.golden(got)

    # --- row 3: auto-review started; the reactions stop there (row 7 would close_reported otherwise) ---

    def auto_review_task(self):
        self.b.config({"workers": {"close_reported": True}, "reviewer": {"kind": "claude"}})
        self.b.claim()
        tid = self.worker_task("rv", "--plan", "[x] build @work; [ ] review @review; [ ] merge @merge")
        wt = self.b.worktree()
        self.b.edit(tid, worktree=str(wt))
        return tid, self.b.git("rev-parse", "--short", "feature")

    def test_row3_auto_review_started_stops_the_reactions(self):
        tid, sha = self.auto_review_task()
        got = self.b.step(["update", tid, "--status", "review", "--commit", sha, "--note", "done"], AS_WORKER)
        self.assertEqual(got["stdout"], f"{tid}: review\n{tid}: auto-review started ({tid}-review)\n")
        self.assertNotIn("close-worker", [s[1] for s in got["spawns"]])
        self.assertEqual(self.b.task(tid)["auto_review"]["status"], "running")
        self.golden(got)

    def test_row3_auto_review_failed_is_handed_to_pm(self):
        tid, sha = self.auto_review_task()
        self.b.task_path(f"{tid}-review").write_text(json.dumps({
            "id": f"{tid}-review", "title": "Review: other", "project": PROJECT, "repo": str(self.b.repo),
            "status": "done", "base": "main", "owner": "pm", "review_of": "other", "created": "2026-01-01 00:00",
            "updated": "2026-01-01 00:00", "log": []}, indent=2) + "\n")
        got = self.b.step(["update", tid, "--status", "review", "--commit", sha, "--note", "done"], AS_WORKER)
        self.assertEqual(got["stdout"].splitlines()[0], f"{tid}: review")
        self.assertIn(f"{tid}: auto-review failed (task {tid}-review exists and is not a review of {tid}); "
                      "handed to PM", got["stdout"])
        self.assertEqual(len(got["stdout"].splitlines()), 2)
        self.assertNotIn("close-worker", [s[1] for s in got["spawns"]])
        self.golden(got)

    def test_row3_round_limit_skips_review_and_runs_the_rest(self):
        tid, sha = self.auto_review_task()
        self.b.edit(tid, rounds=99)
        got = self.b.step(["update", tid, "--status", "review", "--commit", sha, "--note", "done"], AS_WORKER)
        self.assertEqual(got["stdout"], f"{tid}: review\n")
        self.assertIn("(auto-review skipped: round limit reached)", self.b.task(tid)["log"][-2]["text"])
        self.assertIn("close-worker", [s[1] for s in got["spawns"]])
        self.golden(got)

    # --- row 4: --send (with auto_resume_blocked) and a synchronous --wait that fails ---

    def blocked_by_worker(self):
        self.b.claim()
        tid = self.worker_task()
        self.b.setup(["update", tid, "--status", "blocked", "--note", "which way?"], AS_WORKER)
        return tid

    def test_row4_send_wait_resumes_a_worker_blocked_task(self):
        tid = self.blocked_by_worker()
        got = self.b.step(["update", tid, "--send", "--wait", "--note", "go left"], AS_PM)
        lines = got["stdout"].splitlines()
        self.assertEqual(lines[0], f"{tid}: in_progress")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1], f"{tid}: sent to hc:{WORKER_TERM}")
        self.assertEqual(got["hc"][-1], ["send", "--", WORKER_TERM, f"[from hc:{PM_TERM} #<ENV>] go left"])
        self.golden(got)

    def test_row4_send_is_queued_and_typed_by_the_real_drain_process(self):
        """Without --wait the note is queued for the worker's terminal and `pm.py _drain-endpoint` (spawned, here
        run as the real process it is) types it under the terminal's typist lease: once."""
        tid = self.blocked_by_worker()
        got = self.b.step(["update", tid, "--send", "--note", "go right"], AS_PM)
        self.assertEqual(got["exit"], 0, got["stderr"])
        self.assertFalse([c for c in got["hc"] if c[:1] == ["send"]])  # the PM's command typed nothing itself
        raw = [json.loads(line) for line in self.b.spawn_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        drain = [a for a in raw if a[1:2] == ["_drain-endpoint"]]
        self.assertEqual(len(drain), 1)
        self.assertEqual(drain[0][2], WORKER_TERM)
        ran = self.b.step(drain[0][1:], AS_PM)
        self.assertEqual(ran["exit"], 0, ran["stderr"])
        sends = [c for c in ran["hc"] if c[:1] == ["send"]]
        self.assertEqual(sends, [["send", "--", WORKER_TERM, f"[from hc:{PM_TERM} #<ENV>] go right"]])
        again = self.b.step(drain[0][1:], AS_PM)  # a duplicate spawn of the same drain types nothing
        self.assertFalse([c for c in again["hc"] if c[:1] == ["send"]])

    def test_row4_send_wait_failure_exits_1_after_the_status_line(self):
        tid = self.blocked_by_worker()
        self.b.terminal(WORKER_TERM, state="exited", labels={"task": tid})
        got = self.b.step(["update", tid, "--send", "--wait", "--note", "go left"], AS_PM)
        self.assertEqual(got["exit"], 1)
        self.assertEqual(got["stdout"].splitlines()[0], f"{tid}: in_progress")
        self.golden(got)

    # --- row 5a: merged, not dispatched: its review thread closes; row 6 runs too (not exclusive with 5a) ---

    def review_thread(self, tid):
        rid = f"{tid}-review"
        self.b.task_path(rid).write_text(json.dumps({
            "id": rid, "title": "Review: x", "project": PROJECT, "repo": str(self.b.repo), "status": "in_progress",
            "base": "main", "owner": "pm", "pane": f"hc:{REVIEWER_TERM}", "worker_pane": f"hc:{REVIEWER_TERM}",
            "review_of": tid, "created": "2026-01-01 00:00", "updated": "2026-01-01 00:00", "log": []},
            indent=2) + "\n")
        self.b.terminal(REVIEWER_TERM, name="rv", labels={"task": rid})
        return rid

    def test_row5a_merged_closes_review_and_row6_still_runs(self):
        self.b.config({"workers": {"close_on_close": True}})
        self.b.claim()
        tid = self.worker_task()
        self.b.edit(tid, drop=("dispatched",), escalations=[{"at": "2026-01-01 00:00"}])
        rid = self.review_thread(tid)
        got = self.b.step(["update", tid, "--status", "merged", "--note", "merged by hand"], AS_PM)
        lines = got["stdout"].splitlines()
        self.assertEqual(lines[0], f"{tid}: merged")
        self.assertEqual(lines[1], f"{tid}: closed {rid}, terminal hc:{REVIEWER_TERM}")
        self.assertEqual(lines[2], f"{tid}: terminal hc:{WORKER_TERM}")
        self.golden(got)

    # --- row 5b: merged and dispatched: full retire; row 6 does not run (close_on_close is on) ---

    def test_row5b_merged_dispatched_retires_the_workspace(self):
        self.b.config({"workers": {"close_on_close": True}})
        self.b.claim()
        tid = self.worker_task()
        wt = self.b.worktree()
        self.b.edit(tid, worktree=str(wt))
        self.b.git("merge", "-q", "--no-edit", "feature")
        got = self.b.step(["update", tid, "--status", "merged", "--note", "landed"], AS_PM)
        self.assertEqual(got["stdout"].splitlines()[0], f"{tid}: merged")
        self.assertIn("retired", got["stdout"])
        self.assertFalse(wt.exists())
        self.golden(got)

    def test_row5b_retire_refused_prints_not_retired(self):
        self.b.config({"workers": {"close_on_close": True}})
        self.b.claim()
        tid = self.worker_task()
        wt = self.b.worktree()
        self.b.edit(tid, worktree=str(wt))
        got = self.b.step(["update", tid, "--status", "merged", "--note", "landed"], AS_PM)
        self.assertEqual(got["exit"], 0)
        self.assertEqual(got["stdout"].splitlines()[0], f"{tid}: merged")
        self.assertTrue(got["stdout"].splitlines()[-1].startswith("not retired: "))
        self.assertTrue(wt.exists())
        self.golden(got)

    def test_row5b_landed_done_self_closing_worker(self):
        self.b.config({"workers": {"close_on_close": True}})
        self.b.claim()
        tid = self.worker_task()
        self.b.edit(tid, landed={"commit": "abc1234", "base": "main", "branch": "feature", "at": "2026-01-01 00:00"})
        got = self.b.step(["update", tid, "--status", "done", "--note", "post-merge steps done"], AS_WORKER)
        self.assertEqual(got["stdout"], f"{tid}: done\n{tid}: hc:{WORKER_TERM} and workspace will retire once this "
                                        "turn ends\n")
        self.assertEqual([s[1] for s in got["spawns"]], ["deliver", "close-worker"])
        self.assertIn("--retire", got["spawns"][1])
        self.golden(got)

    # --- row 6: close_on_close ends the worker and prunes its empty memory-candidates folder ---

    def test_row6_close_on_close_and_prune_candidates(self):
        self.b.config({"workers": {"close_on_close": True}})
        self.b.claim()
        tid = self.worker_task()
        self.b.edit(tid, drop=("dispatched",), escalations=[{"at": "2026-01-01 00:00"}])
        cand = self.b.ledger / "projects" / PROJECT / "memory" / "candidates"
        (cand / tid).mkdir(parents=True)
        (cand / "someone-else").mkdir()
        got = self.b.step(["update", tid, "--status", "done", "--note", "finished"], AS_PM)
        self.assertEqual(got["stdout"], f"{tid}: done\n{tid}: terminal hc:{WORKER_TERM}\n")
        self.assertEqual(got["ledger"]["candidates/"], ["someone-else"])
        self.golden(got)

    # --- row 8: a review thread reports done: the parent's @review step and auto_review are updated ---

    def test_row8_review_done_syncs_the_parent(self):
        self.b.claim()
        tid = self.worker_task("par", "--plan", "[x] build @work; [>] review @review; [ ] merge @merge")
        self.b.edit(tid, status="review", auto_review={"status": "running", "review_id": f"{tid}-review",
                                                       "commit": "abc1234", "note": "done", "resolved": "abc1234"})
        rid = self.review_thread(tid)
        got = self.b.step(["update", rid, "--status", "done", "--note", "no blockers"], AS_REVIEWER)
        self.assertEqual(got["stdout"], f"{rid}: done\n")
        parent = self.b.task(tid)
        self.assertEqual(parent["auto_review"]["status"], "passed")
        self.assertEqual([s["state"] for s in parent["plan"]], ["done", "done", "todo"])
        self.golden(got)

    # --- row 9a: --depends-on on a proposed task whose prerequisites are all met: a stderr hint ---

    def test_row9a_dependencies_already_met(self):
        self.b.claim()
        first = self.new("First", "first", "--status", "done")
        second = self.new("Second", "second", "--status", "proposed")
        got = self.b.step(["update", second, "--depends-on", first], AS_PM)
        self.assertEqual(got["stdout"], f"{second}: proposed\n")
        self.assertTrue(got["stderr"].startswith(f"note: all dependencies of {second} are already met"))
        self.assertIn("deps_notified", self.b.task(second))
        self.golden(got)

    # --- row 9b: a prerequisite closes: its dependents are reconciled at once ---

    def test_row9b_closing_a_prerequisite_reconciles_dependents(self):
        self.b.claim()
        first = self.new("First", "first")
        second = self.new("Second", "second", "--status", "proposed", "--depends-on", first)
        got = self.b.step(["update", first, "--status", "abandoned", "--note", "dropped"], AS_PM)
        self.assertEqual(got["stdout"], f"{first}: abandoned\n")
        self.assertEqual(self.b.task(second)["deps_notified"], f"abandoned:{first}")
        self.golden(got)


if __name__ == "__main__":
    unittest.main()
