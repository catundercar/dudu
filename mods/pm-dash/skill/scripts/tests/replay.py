#!/usr/bin/env python3
"""Differential replay: run one sequence of pm.py commands against two copies of the scripts folder and compare.

    python3 replay.py --old <scripts dir> --new <scripts dir> [--keep] [--time]
    python3 replay.py --new <scripts dir> --time          (timing only)

Each side gets a copy of its skill folder (the scripts folder's parent, without tests), its own temporary HOME,
PM_HOME (the ledger), git repository `demo` and a fake `hc` (fake_hc.py) first on a PATH that holds nothing else
but the system folders, so no real herdr, herdr-app, claude or codex is reached. The environment is built from
scratch: no HC_TERMINAL_ID, HERDR_PANE_ID, HERDR_WORKSPACE_ID, HERDR_ENV, Claude or Codex session variables; a step
that runs as a terminal sets HC_TERMINAL_ID itself. Steps run interleaved (step n on old, then on new), so
relative times agree; before each step, if within MINUTE_GUARD_SECONDS of the next :00 minute boundary, the replay
waits past :00 so both sides stay in the same minute, and each side still records the wall-clock minute at the start
and end of every step as a fallback — if any step spans different minutes across old and new, the run is discarded and
retried up to MAX_ATTEMPTS times before reporting the last attempt's actual result with a warning. The replay holds
the project's deliver.lock the whole time: no background deliverer starts
(its timing would decide what is delivered when), and `deliver --dry-run` shows the pending batch. After each step
it waits for any other background pm.py process of that side to end (killed after BACKGROUND_WAIT s, which is
reported as part of the output).

Compared per step: exit code, stdout, stderr, and the calls the fake hc received; at the end the whole ledger tree
(file names and contents) and the fake hc state. Before comparing, the run's folder, timestamps, epoch numbers,
pids and hashed file names are normalized. Exit 0: no difference; 1: differences (printed briefly); 2: usage.
POSIX only (fcntl); standard library; Python 3.9 or later.

Commands not covered, and why:
- start, restore, launch, rotate, seat, end-session, name-agent, codex-cmd: start or swap agent sessions and
  terminals (exec, process groups, a seat that outlives the step); not replayable without a real agent.
- dispatch (real), review, escalate, reattach, approve, triage, retire, retab, wait, close-worker,
  _drain-endpoint, _deliver-ready, send: start workers or long-running background deliveries and waits; dispatch is
  covered as --dry-run, and land is covered for a passing merge, a failed check (exit 1) and a merge conflict (exit 4).
  retire needs a worker worktree from a real dispatch.
- deliver (real), watch: long-running loops by design (see the deliver.lock note above); deliver --dry-run is in.
- archive: stops the PM and pauses tasks through terminals that a later step would need; claim covers registration.
- dash: an HTTP server.  context: reads a live session's transcript.  adopt: needs an orphan worker or a worker's
  memory candidate written by an agent.  helper *: starts agent terminals (helper ls is in).
- project session, change, context, files, delete, restore, add, retopic, archive-decisions, research-migrate:
  session needs a transcript; the rest are Library writes whose shape `project save/history` already exercises.
- hook-session-start, hook-pre-compact, hook-mirror: read a live session's transcript or are kept for old installs;
  hook-pre-tool and hook-turn are in (and timed).
"""
import argparse
import compileall
from concurrent.futures import ThreadPoolExecutor
import contextlib
import difflib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
FAKE_HC = HERE / "fake_hc.py"
PROJECT = "demo"  # the repository's folder name, and so the project's slug
BACKGROUND_WAIT = 20
STEP_TIMEOUT = 120
MINUTE_GUARD_SECONDS = 3.0  # a step pair (old + new) typically takes ~0.8 s; wait past :00 if closer than this
MAX_ATTEMPTS = 3  # up to 3 runs total; if all 3 have a step split across minutes, report the last with a note
CLOCK_SKEW_NOTE = "some steps fell in different minutes on the two sides; the result may depend on the clock"
GIT_ENV = {"GIT_AUTHOR_NAME": "Replay", "GIT_AUTHOR_EMAIL": "replay@example.invalid",
           "GIT_COMMITTER_NAME": "Replay", "GIT_COMMITTER_EMAIL": "replay@example.invalid",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
           "GIT_CONFIG_NOSYSTEM": "1"}
SKIP_COPY = shutil.ignore_patterns("tests", "test_*.py", "__pycache__", ".DS_Store")


class Side:
    """One copy of pm.py with its own home, ledger, repository and fake hc."""

    def __init__(self, name, scripts, base):
        self.name = name
        self.root = base / name
        self.skill = self.root / "skill"
        shutil.copytree(Path(scripts).resolve().parent, self.skill, ignore=SKIP_COPY)
        # Compile the copy once: the steps run with PYTHONDONTWRITEBYTECODE, so without this every one of the ~170
        # pm.py runs would compile all of pmlib from source again (about 270 ms instead of 100 ms per run). The
        # same code runs either way; only the bytecode is cached.
        compileall.compile_dir(self.skill, quiet=1, workers=1)
        self.pm = self.skill / "scripts" / "pm.py"
        if not self.pm.is_file():
            raise SystemExit(f"replay: no pm.py in {scripts}")
        self.home = self.root / "home"
        self.ledger = self.root / "ledger"
        self.repo = self.root / PROJECT
        self.bin = self.root / "bin"
        self.hc_state = self.root / "hc-state.json"
        self.hc_log = self.root / "hc-calls.jsonl"
        for folder in (self.home, self.ledger, self.repo, self.bin, self.root / "tmp"):
            folder.mkdir(parents=True)
        (self.bin / "hc").write_text(f"#!{sys.executable}\n" + FAKE_HC.read_text(encoding="utf-8"), encoding="utf-8")
        (self.bin / "hc").chmod(0o755)
        (self.bin / "python3").symlink_to(sys.executable)
        git = shutil.which("git")
        if git:
            (self.bin / "git").symlink_to(git)
        self.hc_state.write_text(json.dumps({"terminals": {}, "next": 1}))
        self.hc_log.write_text("")
        self.env = {
            "HOME": str(self.home), "PM_HOME": str(self.ledger), "TMPDIR": str(self.root / "tmp"),
            "PATH": os.pathsep.join([str(self.bin), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
            "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8", "PM_NO_DISCORD": "1", "FAKE_HC_STATE": str(self.hc_state),
            "FAKE_HC_LOG": str(self.hc_log), "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"), **GIT_ENV,
        }
        self.lock = None

    def hold_deliver_lock(self):
        folder = self.ledger / "projects" / PROJECT
        folder.mkdir(parents=True, exist_ok=True)
        self.lock = open(folder / "deliver.lock", "a+")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True, capture_output=True)

    def hc_terminals(self, change):
        state = json.loads(self.hc_state.read_text())
        change(state["terminals"])
        self.hc_state.write_text(json.dumps(state, indent=1, sort_keys=True))

    def read_hc_since(self, before):
        with open(self.hc_log, encoding="utf-8") as f:
            f.seek(before)
            return f.read()

    def run(self, argv, env=None, stdin="", cwd=None, check_background=True):
        before = self.hc_log.stat().st_size
        try:
            out = subprocess.run([sys.executable, str(self.pm), *argv], cwd=str(cwd or self.repo),
                                 env={**self.env, **(env or {})}, input=stdin, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=STEP_TIMEOUT)
            code, stdout, stderr = out.returncode, out.stdout, out.stderr
        except subprocess.TimeoutExpired as e:
            code, stdout, stderr = "timeout", str(e.stdout or ""), str(e.stderr or "")
        background = self.wait_background() if check_background else ""
        calls = self.read_hc_since(before)
        result = {"exit": code, "stdout": stdout, "stderr": stderr, "hc": calls, "background": background,
                  "_hc_before": before}
        with open(self.root / "transcript.txt", "a", encoding="utf-8") as f:  # for a person, with --keep
            f.write(f"$ pm.py {' '.join(argv)}  {env or ''}\n" +
                    "".join(f"[{k}]\n{v}\n" for k, v in result.items()
                            if not k.startswith("_") and v not in ("", None)) + "\n")
        return result

    def wait_background(self):
        """Wait for background pm.py processes of this side (whose command line names its copy of pm.py)."""
        deadline = time.time() + BACKGROUND_WAIT
        while True:
            found = background_processes(str(self.pm))
            if not found:
                return ""
            if time.time() >= deadline:
                for pid, _ in found:
                    with contextlib.suppress(OSError):
                        os.kill(pid, 9)
                return "killed after waiting: " + "; ".join(sorted(cmd for _, cmd in found)) + "\n"
            time.sleep(0.1)

    def tree(self):
        """{relative path: content} of the ledger, then the fake hc state."""
        files = {}
        for path in sorted(self.ledger.rglob("*")):
            if path.is_file():
                files[path.relative_to(self.ledger).as_posix()] = path.read_bytes().decode("utf-8", "replace")
            elif path.is_dir() and not any(path.iterdir()):
                files[path.relative_to(self.ledger).as_posix() + "/"] = ""
        files["<fake hc state>"] = self.hc_state.read_text()
        return files


def _ere(text):
    """`text` as a POSIX extended regular expression matching it literally, or None if it holds a character that
    cannot simply be bracketed."""
    if any(c in text for c in "]^\\\n"):
        return None
    return "".join(c if c.isalnum() or c in "/-_ " else f"[{c}]" for c in text)


def background_processes(marker):
    # Fast path: pgrep reads the process table without formatting every process (about half the time of ps here,
    # and this runs after each of the ~170 steps). It only answers "is there any"; when there is, ps lists them.
    pattern = _ere(marker)
    if pattern and shutil.which("pgrep"):
        try:
            if subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=30).returncode == 1:
                return []
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        out = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        if marker in command and pid.isdigit() and int(pid) != os.getpid():
            found.append((int(pid), command.strip()))
    return found


def normalizer(side):
    roots = sorted({str(side.root), os.path.realpath(side.root)}, key=len, reverse=True)
    rules = [
        (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"), "<TIME>"),
        (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "<DATE>"),
        (re.compile(r"\b\d{8}-\d{6}\b"), "<STAMP>"),  # backup and archive names
        (re.compile(r"\b[0-9a-f]{16}-[0-9a-f]+\b"), "<VERSION>"),  # a document's version: mtime_ns and size, hex
        (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"), "<HH:MM>"),
        (re.compile(r"\b1[6-9]\d{8}(?:\.\d+)?\b"), "<EPOCH>"),
        (re.compile(r"\b1[6-9]\d{11,18}\b"), "<EPOCH>"),  # milliseconds and nanoseconds
        (re.compile(r"(\"pid\":\s*)\d+"), r"\1<PID>"),
        (re.compile(r"(send|msg|brief|tmp)-\d+-\d+"), r"\1-<PID>-<N>"),
        (re.compile(r"\.\d+\.tmp\b"), ".<PID>.tmp"),
        (re.compile(r"reads/[0-9a-f]{12}\.json"), "reads/<HASH>.json"),
        (re.compile(r"\benv_[0-9a-f]{12}_[0-9a-f]{8}\b"), "<ENV>"),  # an envelope's id (time + random)
        (re.compile(r"\b\d+(?:\.\d+)? ?(?:ms|s|sec|secs|seconds|m|min|mins|minutes|h|hours?) ago\b"), "<AGO>"),
    ]

    def norm(text):
        for root in roots:
            text = text.replace(root, "<ROOT>")
        for pattern, replacement in rules:
            text = pattern.sub(replacement, text)
        return text
    return norm


def compare_text(label, old, new, limit=30):
    if old == new:
        return []
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "old", "new", n=1, lineterm=""))
    return [f"--- {label}"] + diff[2:2 + limit] + ([f"... ({len(diff) - 2 - limit} more lines)"]
                                                   if len(diff) - 2 > limit else [])


# --- the scenario ------------------------------------------------------------------------------------------------

PM_TERM, WORKER_TERM = "t1", "t2"
AS_PM = {"HC_TERMINAL_ID": PM_TERM}
AS_WORKER = {"HC_TERMINAL_ID": WORKER_TERM}
FIRST, SECOND, THIRD = f"{PROJECT}-first", f"{PROJECT}-second", f"{PROJECT}-third"
LAND_OK, LAND_CONFLICT = f"{PROJECT}-land-ok", f"{PROJECT}-land-conflict"


def setup_repo(side):
    side.git("init", "-q", "-b", "main")
    (side.repo / "README.md").write_text("# demo\n")
    (side.repo / "app.py").write_text("print('hello')\n")
    side.git("add", "README.md", "app.py")
    side.git("commit", "-q", "-m", "initial")
    side.git("checkout", "-q", "-b", "feature")
    (side.repo / "app.py").write_text("print('hello, world')\n")
    (side.repo / "notes.txt").write_text("feature notes\n")
    side.git("add", "app.py", "notes.txt")
    side.git("commit", "-q", "-m", "feature: greet the world")
    side.git("checkout", "-q", "main")
    (side.root / "brief.md").write_text("# Third task\n\nDo the third thing.\n")


def setup_land_branches(side):
    side.git("checkout", "-q", "-b", "land-ok")
    (side.repo / "README.md").write_text("# demo (landed)\n")
    (side.repo / "land-ok.txt").write_text("ok\n")
    side.git("add", "README.md", "land-ok.txt")
    side.git("commit", "-q", "-m", "land-ok: add file")
    side.git("checkout", "-q", "main")
    side.git("checkout", "-q", "-b", "land-conflict")
    (side.repo / "README.md").write_text("# demo (conflicting)\n")
    side.git("add", "README.md")
    side.git("commit", "-q", "-m", "land-conflict: edit readme")
    side.git("checkout", "-q", "main")


def set_verify(content):
    def _write(side):
        path = side.ledger / "projects" / PROJECT / "verify"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return _write


def seed_pm_terminal(side):
    def change(terms):
        terms[PM_TERM] = {"state": "live", "name": "pm", "cwd": str(side.repo), "argv": ["claude"],
                          "foreground": {"argv": ["claude"]}, "labels": {}, "status": {"state": "idle"}}
    side.hc_terminals(change)


def seed_worker_terminal(side):
    def change(terms):
        terms[WORKER_TERM] = {"state": "live", "name": "first", "cwd": str(side.repo), "argv": ["codex"],
                              "foreground": {"argv": ["codex"]}, "labels": {"task": FIRST},
                              "status": {"state": "working"}}
    side.hc_terminals(change)


def worker_goes_idle(side):
    # The task is marked as `dispatch` marks the tasks it starts (only those workers are listed), and its worker
    # has been idle for 45.5 minutes as hc counts it (status_ms): idle-workers lists it, with the same whole minutes
    # on both sides as long as the two seeds are less than 30 s apart.
    path = side.ledger / "tasks" / f"{FIRST}.json"
    task = json.loads(path.read_text(encoding="utf-8"))
    task["dispatched"] = True
    path.write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    def change(terms):
        terms[WORKER_TERM]["status"] = {"state": "idle"}
        terms[WORKER_TERM]["status_ms"] = int(time.time() * 1000 - 45.5 * 60000)
    side.hc_terminals(change)


def feature_sha(side):
    return subprocess.run(["git", "rev-parse", "--short", "feature"], cwd=side.repo, env=side.env,
                          capture_output=True, text=True, check=True).stdout.strip()


# A step: a list of arguments (a command), or (arguments, options) with env, stdin; a callable prepares both sides
# alike and is not compared. "{sha}" in an argument is replaced by the feature branch's short commit.
SCENARIO = [
    setup_repo,
    ["status"],
    ["home", "--json"],
    ["home"],
    ["notify", "is anybody there"],  # no PM yet: an error
    ["new", "First task", "--slug", "first", "--note", "kick-off", "--plan", "[>] build; [ ] check"],
    ["new", "Second task", "--slug", "second", "--status", "proposed", "--parent", FIRST, "--depends-on", FIRST],
    ["update", FIRST, "--status", "blocked", "--note", "Which store?", "--option", "SQLite (recommended)",
     "--option", "Flat files"],
    ["update", FIRST, "--status", "in_progress", "--note", "flat files it is", "--branch", "feature",
     "--plan", "[x] build; [>] check; [ ] land"],
    ["update", SECOND, "--depends-on", "", "--note", "no longer waits"],
    ["update", SECOND, "--depends-on", f"+{FIRST}", "--parent", FIRST],
    ["log", FIRST, "looked at the logs; nothing odd"],
    ["show", FIRST, "--json"],
    ["show", FIRST],
    ["show", "no-such-task"],
    ["board"],
    ["find"],
    ["status"],
    ["status", "--closed", "--all"],
    ["diff", FIRST],
    ["event", "CI is green on main", "--source", "ci", "--key", "build-1"],
    ["event", "CI is green on main", "--source", "ci", "--key", "build-1"],  # same key: not recorded again
    ["event", "nightly finished", "--source", "schedule"],
    ["deliver", PROJECT, "--dry-run"],
    seed_pm_terminal,
    lambda side: side.hold_deliver_lock(),
    (["claim"], {"env": AS_PM}),
    ["guard", "--action", "coordinate"],
    (["guard", "--action", "coordinate"], {"env": AS_PM}),
    (["guard", "--action", "implement"], {"env": AS_PM}),
    ["notify", "a note for the PM"],
    ["deliver", PROJECT, "--dry-run"],
    seed_worker_terminal,
    (["guard", "--action", "implement"], {"env": AS_WORKER}),
    (["update", FIRST, "--plan", "[x] build; [>] check; [ ] land"], {"env": AS_WORKER}),
    (["update", FIRST, "--status", "review", "--commit", "{sha}", "--note", "ready: greets the world"],
     {"env": AS_WORKER}),
    (["notify", "worker says hi"], {"env": AS_WORKER}),
    ["deliver", PROJECT, "--dry-run"],
    ["deliver", PROJECT, "--dry-run", "--since", "0"],
    ["state"],
    (["update", FIRST, "--pane", f"hc:{WORKER_TERM}", "--agent", "codex"], {"env": AS_PM}),
    ["idle-workers", "--json"],
    worker_goes_idle,
    ["idle-workers", "--json"],
    ["idle-workers", "--minutes", "60"],
    ["idle-workers"],
    ["project", "events", PROJECT],
    ["project", "events", PROJECT, "--limit", "2"],
    ["project", "log", FIRST],
    ["project", "library", PROJECT],
    ["project", "memory", PROJECT],
    ["project", "save", PROJECT, "docs/notes.md", "--text", "# Notes\n\nFirst draft.\n"],
    ["project", "save", PROJECT, "docs/notes.md", "--text", "# Notes\n\nSecond draft.\n"],
    ["project", "history", PROJECT],
    ["project", "file", PROJECT, "docs/notes.md"],
    ["project", "file", PROJECT, "docs/missing.md"],
    (["remember", "Run the replay before every carve", "--name", "replay-before-carve", "--type", "pitfall",
      "--verified", "replay.py run on main"], {"env": AS_WORKER}),
    (["remember", "The board lives in BOARD.md", "--name", "board-file", "--type", "reference"], {"env": AS_PM}),
    ["recall", "replay-before-carve"],
    ["recall", "--search", "board"],
    ["recall", "--type", "pitfall"],
    ["memory"],
    (["decide", "Keep the ledger format as it is", "--quote", "don't change the files", "--name",
      "ledger-format-stays"], {"env": AS_PM}),
    (["decide", "push after this one", "--once"], {"env": AS_PM}),
    ["decisions"],
    ["forget", "board-file", "--why", "moved"],
    ["project", "memory", PROJECT],
    ["handover"],
    ["handover", "--compact"],
    ["conversation", "--last", "50", "--width", "0"],
    ["conversation", "--type", "thread,decision"],
    ["backfill-numbers", "--dry-run", "--json"],
    ["backfill-numbers", "--dry-run"],
    (["dispatch", "Third task", "--branch", "third", "--brief", "../brief.md", "--dry-run", "--kind", "codex"],
     {"env": AS_PM}),
    (["dispatch", "--task", SECOND, "--here", "--brief", "../brief.md", "--dry-run", "--profile", "standard"],
     {"env": AS_PM}),
    (["dispatch", "Third task", "--brief", "../brief.md", "--dry-run"], {"env": AS_PM}),  # neither --branch nor --here
    (["helper", "ls", "--json"], {"env": AS_PM}),
    (["hook-pre-tool"], {"env": AS_PM, "stdin": ""}),
    (["hook-pre-tool"], {"env": AS_PM, "stdin": json.dumps({"tool_name": "AskUserQuestion",
                                                             "tool_input": {"questions": []}})}),
    (["hook-turn"], {"env": AS_PM, "stdin": ""}),
    (["update", FIRST, "--status", "merged", "--note", "merged by hand", "--keep"], {"env": AS_PM}),
    (["update", SECOND, "--status", "abandoned", "--note", "folded into first"], {"env": AS_PM}),
    setup_land_branches,
    (["new", "Land clean", "--slug", "land-ok", "--branch", "land-ok"], {"env": AS_PM}),
    (["new", "Land conflict", "--slug", "land-conflict", "--branch", "land-conflict"], {"env": AS_PM}),
    set_verify("false\n"),
    (["land", LAND_OK], {"env": AS_PM}),  # check fails (exit 1); merge aborted
    set_verify("test -f land-ok.txt\n"),
    (["land", LAND_OK], {"env": AS_PM}),  # check passes (exit 0); merged onto main
    (["land", LAND_CONFLICT], {"env": AS_PM}),  # merge conflicts on README.md (exit 4); merge aborted
    ["status", "--closed"],
    ["state"],
    ["deliver", PROJECT, "--dry-run"],
]


def step_label(step):
    argv, opts = (step, {}) if isinstance(step, list) else step
    who = (opts.get("env") or {}).get("HC_TERMINAL_ID")
    return ("as " + who + ": " if who else "") + "pm.py " + " ".join(argv)


def run_step(side, step, check_background=True):
    argv, opts = (step, {}) if isinstance(step, list) else step
    sha = feature_sha(side) if any("{sha}" in a for a in argv) else ""
    argv = [a.replace("{sha}", sha) for a in argv]
    return side.run(argv, env=opts.get("env"), stdin=opts.get("stdin", ""), check_background=check_background)


def wall_time():
    """Current wall-clock epoch seconds; replaceable in tests."""
    return time.time()


def wall_minute():
    """Current wall-clock minute index (changes at each :00 boundary); replaceable in tests."""
    return int(wall_time()) // 60


_RUN_STEP = run_step
_WALL_MINUTE = wall_minute


def wait_past_minute_boundary(now=None, sleeper=None, guard=MINUTE_GUARD_SECONDS):
    """If within `guard` seconds of the next :00 minute boundary, sleep past it so old and new share one minute."""
    if guard <= 0:
        return 0.0
    remaining = 60.0 - ((now or wall_time)() % 60.0)
    if remaining <= guard:
        wait = remaining + 0.05
        (sleeper or time.sleep)(wait)
        return wait
    return 0.0


def steps_aligned(old_samples, new_samples):
    """Whether every step began and ended in the exact same wall-clock minute on both old and new."""
    return len(old_samples) == len(new_samples) and all(
        s_old == e_old == s_new == e_new
        for (s_old, e_old), (s_new, e_new) in zip(old_samples, new_samples)
    )


def cleanup_sides(sides):
    for side in sides:
        if side.lock:
            side.lock.close()
            side.lock = None
        shutil.rmtree(side.root, ignore_errors=True)


def replay(old, new, clock=None, sleeper=None):
    """Run one round of the scenario on both sides; return (commands, differences, aligned)."""
    minute_of = clock or wall_minute
    # Both sides have disjoint directories, repos, ledgers and fake hc files, so running each step on `old` and
    # `new` concurrently halves wall time and tightens clock alignment. Stay sequential when tests inject a mock
    # clock / wall_minute / run_step that expects deterministic old-then-new call order.
    parallel = clock is None and wall_minute is _WALL_MINUTE and run_step is _RUN_STEP
    differences, commands = [], 0
    old_minutes, new_minutes = [], []
    norm_old, norm_new = normalizer(old), normalizer(new)

    shared_base = str(old.root.parent) if old.root.parent == new.root.parent else ""

    def timed_step(side, step, check_background=True):
        started = minute_of()
        res = run_step(side, step, check_background=check_background) if not check_background else run_step(side, step)
        ended = minute_of()
        return started, res, ended

    with ThreadPoolExecutor(max_workers=2) if parallel else contextlib.nullcontext() as pool:
        for step in SCENARIO:
            if callable(step):
                if pool is not None:
                    f_old = pool.submit(step, old)
                    f_new = pool.submit(step, new)
                    f_old.result()
                    f_new.result()
                else:
                    step(old)
                    step(new)
                continue
            commands += 1
            if clock is None:
                wait_past_minute_boundary(sleeper=sleeper)
            if pool is not None:
                combined_bg = bool(shared_base)
                f_old = pool.submit(timed_step, old, step, not combined_bg)
                f_new = pool.submit(timed_step, new, step, not combined_bg)
                s_old, a, e_old = f_old.result()
                s_new, b, e_new = f_new.result()
                if combined_bg and background_processes(shared_base):
                    f_bg_old = pool.submit(old.wait_background)
                    f_bg_new = pool.submit(new.wait_background)
                    a["background"] = f_bg_old.result()
                    b["background"] = f_bg_new.result()
                    a["hc"] = old.read_hc_since(a["_hc_before"])
                    b["hc"] = new.read_hc_since(b["_hc_before"])
            else:
                s_old, a, e_old = timed_step(old, step)
                s_new, b, e_new = timed_step(new, step)
            old_minutes.append((s_old, e_old))
            new_minutes.append((s_new, e_new))
            lines = []
            for key in ("exit", "stdout", "stderr", "hc", "background"):
                lines += compare_text(key, norm_old(str(a[key])), norm_new(str(b[key])))
            if lines:
                differences += [f"step {commands}: {step_label(step)}"] + ["  " + line for line in lines]
        if pool is not None:
            f_old_tree = pool.submit(old.tree)
            f_new_tree = pool.submit(new.tree)
            raw_old, raw_new = f_old_tree.result(), f_new_tree.result()
        else:
            raw_old, raw_new = old.tree(), new.tree()
    tree_old = {norm_old(k): norm_old(v) for k, v in raw_old.items()}
    tree_new = {norm_new(k): norm_new(v) for k, v in raw_new.items()}
    for path in sorted(set(tree_old) | set(tree_new)):
        if path not in tree_new:
            differences.append(f"ledger: {path} only in old")
        elif path not in tree_old:
            differences.append(f"ledger: {path} only in new")
        else:
            differences += ["  " + line for line in compare_text(f"ledger: {path}", tree_old[path], tree_new[path])]
    return commands, differences, steps_aligned(old_minutes, new_minutes)


def timing(side, runs=10):
    """Median wall time in ms of hook-pre-tool (empty stdin), hook-turn and state, run as the PM's terminal."""
    result = {}
    for argv in (["hook-pre-tool"], ["hook-turn"], ["state"]):
        times = []
        for _ in range(runs):
            began = time.perf_counter()
            subprocess.run([sys.executable, str(side.pm), *argv], cwd=str(side.repo), env={**side.env, **AS_PM},
                           input="", capture_output=True, text=True, timeout=STEP_TIMEOUT)
            times.append((time.perf_counter() - began) * 1000)
            side.wait_background()
        result[" ".join(argv)] = statistics.median(times)
    return result


def main(argv=None, clock=None, sleeper=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--old", help="the scripts folder of the reference pm.py (e.g. from main)")
    p.add_argument("--new", required=True, help="the scripts folder of the pm.py under test")
    p.add_argument("--keep", action="store_true", help="keep the temporary folders and print where they are")
    p.add_argument("--time", action="store_true", help="also print the median startup time (ms) of hook-pre-tool, "
                                                      "hook-turn and state over 10 runs, per side")
    a = p.parse_args(argv)
    if not a.old and not a.time:
        p.error("--old is required unless only --time is asked for")
    base = Path(tempfile.mkdtemp(prefix="pm-replay-"))
    sides = []
    try:
        status = 0
        if a.old:
            for attempt in range(MAX_ATTEMPTS):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    f_old = pool.submit(Side, "old", a.old, base)
                    f_new = pool.submit(Side, "new", a.new, base)
                    sides = [f_old.result(), f_new.result()]
                commands, differences, aligned = replay(*sides, clock=clock, sleeper=sleeper)
                if aligned or attempt + 1 == MAX_ATTEMPTS:
                    break
                cleanup_sides(sides)
                sides = []
            if differences:
                print(f"replay: {commands} commands, differences:")
                print("\n".join(differences))
                status = 1
            else:
                print(f"replay: {commands} commands, no differences")
            if not aligned:
                print(f"replay: {CLOCK_SKEW_NOTE}")
        else:
            sides = [Side("new", a.new, base)]
        if a.time:
            if not a.old:
                for step in SCENARIO:
                    step(sides[0]) if callable(step) else run_step(sides[0], step)
            for side in sides:
                medians = timing(side)
                print(f"timing ({side.name}, median of 10): " +
                      ", ".join(f"{name} {ms:.0f} ms" for name, ms in medians.items()))
        return status
    finally:
        for side in sides:
            if side.lock:
                side.lock.close()
        if a.keep:
            print(f"kept: {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
