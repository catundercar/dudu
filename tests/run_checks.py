#!/usr/bin/env python3
"""The full check before a merge, run in parallel: the mods' `herdr-app check`, their node model tests, every
pm unittest file and the scripts/tests safety net, `pm.py state`, and optionally `tests/render_check.py`.

    python3 tests/run_checks.py [--jobs N] [--only TEXT] [--render-check never|auto|always] [--keep] [--list]

Run from the repository root (land runs the verify file there). Prints one line per check as it ends, with its
wall time; then, for each failed check, the traceback of every failed test (or the last lines a failed command
printed); then a summary line. Exit 0 when everything passed, 1 when anything failed, 2 on bad usage.

With `--render-check auto`, staged changes (`git diff --cached --name-only HEAD`) are inspected in pure Python:
if any changed file is under `mods/<mod>/` (excluding `mods/pm-dash/skill/`) or `tests/render_check*`,
`tests/render_check.py` is scheduled at the highest priority so it runs in parallel with all other checks from
t=0. Exit 2 (BLOCKED / NOT JUDGED) from `render_check.py` still fails the run (exit 1) with an explicit message
so an unjudged UI merge is never silently passed.

How the unittest files run: each file (and the scripts/tests folder as one group) is first listed in a child
process, then split into shards: one per test method for modules/classes in SPLIT_METHODS, smaller chunks for
subprocess-heavy classes in SHARD_CHUNKS, CHUNK-sized chunks for large classes, and small normal TestCase
classes within the same module packed into CHUNK-sized shards to avoid redundant interpreter startups. Every
shard runs in its own `python3` process. Shards and the other checks share one pool of --jobs processes
(default: the number of CPUs), longest ones first (LPT). A file's tests are imported under the same module
names as `python3 -m unittest <file>` and `unittest discover` give them, so a test sees the same `__name__`,
`__file__` and `sys.path` as in the serial run. After the run, the tests run per group must equal the tests
listed, so a shard that loads fewer tests is a failure, not a silent pass.

Isolation: each test shard gets its own empty HOME (with a .gitconfig naming a test author and `main` as the
default branch, as this machine's has), PM_HOME and TMPDIR, and an environment without the terminal and agent
session variables (HC_*, HERDR_*, CLAUDE*, CODEX_*, PI_*, DISCORD_*, PM_*, GIT_DIR and friends): no shard reaches
the real ledger, lock files, hc terminals or another shard's temporary files. The command checks (herdr-app check,
node, pm.py state, render-check) run with the caller's environment, as the verify file ran them: `pm.py state` is
meant to read the real ledger, and `render_check.py` isolates its own private Herdr home and hc session.

Tests that cannot share the machine with others go in SERIAL (module or module.Class): they run one at a time,
after the parallel ones. None are needed today; see the comment there.

Standard library only; Python 3.9 or later; POSIX.
"""
import argparse
import fnmatch
import io
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "mods/pm-dash/skill/scripts"
SAFETY_NET = f"{SCRIPTS}/tests"

# Modules whose test methods each get a shard of their own: every method of test_replay replays a pm.py
# scenario on two sides; as one class shard they would add up linearly.
SPLIT_METHODS = {"test_replay"}

# Classes or modules whose tests spawn real subprocesses (pm.py, git, setup.py) and dominate the tail when left
# in CHUNK-sized (10) shards. Mapping to a smaller chunk size splits them finer and boosts their pool priority
# so they start right after listing and never hold up the end of the run.
SHARD_CHUNKS = {
    "test_replay": 1,
    "test_install.InstallTest": 5,
    "test_views.LibraryAndMemoryTests": 2,
    "test_transition_reactions.TransitionReactions": 2,
    "test_review_land.DelegatedMergeTests": 3,
    "test_review_land.LandAndReview": 3,
    "test_review_land.ResearchCollectionTests": 2,
    "test_ledger_transitions.TwoLayerPlanAndAutoReview": 3,
    "test_ledger_transitions.TaskNumbersTests": 2,
    "test_deliverer.Events": 5,
    "test_deliverer.TaskDependencies": 3,
    "test_homemove.HomeMoveTest": 3,
    "test_views.StoreAndProjectTests": 3,
    "test_views.ContextStoreAndProjectTests": 3,
    "test_views.LightOutput": 4,
    "test_store_locks.StoreLocksTest": 4,
    "test_workers_dispatch.Profiles": 5,
    "test_agents_profiles.PmStateAndCliTests": 4,
    "test_manager_seat.PMSeatAndAdopt": 4,
    "test_mod_error_contract.ModErrorContractTest": 1,
}

# Modules or module.Class names that must not run beside other tests (shared machine-wide state: a fixed port, a
# fixed path, a global lock, timing that breaks under load). They run one at a time after everything else.
# Empty: with each shard in its own HOME/PM_HOME/TMPDIR, all 803 tests passed in parallel run after run with 28
# jobs on a machine already at load 8-15 (2026-11-23). Add an entry here, with the reason, rather than retrying.
SERIAL = set()

# Environment variables a test shard does not inherit: the caller's terminal, agent session, ledger and git
# location. Prefixes end with "_"; the rest are exact names.
STRIP_PREFIXES = ("HC_", "HERDR_", "CLAUDE_", "CODEX_", "PI_", "DISCORD_", "PM_", "XDG_")
STRIP_NAMES = {"CLAUDECODE", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
               "GIT_COMMON_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG", "PYTHONPATH", "PYTHONSTARTUP"}
GITCONFIG = "[user]\n\tname = run-checks\n\temail = run-checks@example.invalid\n[init]\n\tdefaultBranch = main\n"

CHUNK = 10  # default max tests per shard (and bin capacity when packing small TestCase classes of one module)
TAIL = 30  # lines of a failed command's output to show, as the verify file's `| tail -30` did
RENDER_TAIL = 60  # render-check prints a compact multi-line report; keep all of it on failure
RENDER_CHECK_MATCH = re.compile(r"^(?:mods/[^/]+/|tests/render_check)")
RENDER_CHECK_EXCLUDE = "mods/pm-dash/skill/"
RENDER_CHECK_SUN_LEN = 104  # macOS sun_path limit for <dir>/app/herdr-app.sock
RENDER_NOT_JUDGED_MSG = "render-check 没有评判（见上面的 BLOCKED/NOT JUDGED），醒着屏幕再跑一次"


def shard_chunk_limit(short, cls):
    """Max tests per shard for module `short` and TestCase class `cls`."""
    key = f"{short}.{cls}" if cls else short
    if short in SPLIT_METHODS or key in SPLIT_METHODS:
        return 1
    if cls and key in SHARD_CHUNKS:
        return SHARD_CHUNKS[key]
    if short in SHARD_CHUNKS:
        return SHARD_CHUNKS[short]
    return CHUNK


def shard_priority(short, cls, count, serial):
    """Pool priority (higher runs sooner): LPT ordering so slow subprocess shards start immediately."""
    if serial:
        return -1
    key = f"{short}.{cls}" if cls else short
    if short in SPLIT_METHODS or key in SPLIT_METHODS:
        return 2000
    limit = shard_chunk_limit(short, cls)
    if limit <= 2:
        return 200 * count
    if limit <= 3:
        return 120 * count
    if limit <= 5:
        return 60 * count
    return count


def needs_render_check(paths):
    """Whether any changed path touches a UI mod (mods/* excluding mods/pm-dash/skill/) or render_check itself."""
    return any(RENDER_CHECK_MATCH.match(p) and not p.startswith(RENDER_CHECK_EXCLUDE) for p in paths)


def staged_files(root):
    """Staged file paths (`git diff --cached --name-only HEAD`) in pure Python, avoiding shell grep/ugrep traps."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "HEAD"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip() or f"exit {proc.returncode}"
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()], ""


# --- child side: list a group's tests, or run one shard, and write the result as JSON ---------------------------

def child_setup(spec):
    """sys.path as `python3 -m unittest` (cwd first) and, for a discovered folder, `discover -s` (it first)."""
    sys.path[0] = os.getcwd()  # replaces this script's own folder
    if spec["kind"] == "discover":
        sys.path.insert(0, os.path.abspath(spec["start"]))


def module_names(spec):
    """The modules of a group, named as unittest names them."""
    if spec["kind"] == "files":
        return [os.path.normpath(f)[:-3].replace(os.sep, ".") for f in spec["files"]]
    start = Path(spec["start"])
    return sorted(p.stem for p in start.iterdir()
                  if p.is_file() and fnmatch.fnmatch(p.name, spec["pattern"]) and p.stem.isidentifier())


def child_list(spec):
    """{"shards": [[names, count, serial, priority], ...], "total": n, "errors": [...]}: splits modules into
    shards using SHARD_CHUNKS / SPLIT_METHODS / CHUNK, and packs small normal TestCase classes within the same
    module into CHUNK-sized bins to save interpreter startups; falls back to the whole module when it has
    load_tests or when the split does not add up to what unittest loads from it."""
    loader = unittest.TestLoader()
    shards, errors = [], []
    for modname in module_names(spec):
        try:
            module = __import__(modname, fromlist=["*"])
        except BaseException:
            errors.append(f"cannot import {modname}:\n{traceback.format_exc()}")
            continue
        short = modname.rsplit(".", 1)[-1]
        whole = loader.loadTestsFromModule(module).countTestCases()
        mine = []  # (names to load, class or None, number of tests, serial, priority)
        if not hasattr(module, "load_tests"):
            packable = []  # (full class name, count) for small normal classes in this module
            for attr in dir(module):
                obj = getattr(module, attr)
                if not (isinstance(obj, type) and issubclass(obj, unittest.TestCase)):
                    continue
                methods = [f"{modname}.{attr}.{m}" for m in loader.getTestCaseNames(obj)]
                if not methods:
                    continue
                serial = short in SERIAL or f"{short}.{attr}" in SERIAL
                limit = shard_chunk_limit(short, attr)
                if limit == 1:
                    prio = shard_priority(short, attr, 1, serial)
                    mine += [([m], attr, 1, serial, prio) for m in methods]
                elif len(methods) > limit:
                    parts = -(-len(methods) // limit)
                    for i in range(parts):
                        chunk = methods[i::parts]
                        mine.append((chunk, attr, len(chunk), serial, shard_priority(short, attr, len(chunk), serial)))
                elif serial or limit < CHUNK:
                    mine.append(([f"{modname}.{attr}"], attr, len(methods), serial,
                                 shard_priority(short, attr, len(methods), serial)))
                else:
                    packable.append((f"{modname}.{attr}", len(methods)))
            if packable:
                # First-fit decreasing packing within the same module (same isolation as `unittest <module>`).
                bins = []  # ([class_names], total_tests)
                for full_name, n in sorted(packable, key=lambda x: (-x[1], x[0])):
                    for b in bins:
                        if b[1] + n <= CHUNK:
                            b[0].append(full_name)
                            b[1] += n
                            break
                    else:
                        bins.append([[full_name], n])
                for names, n in bins:
                    mine.append((names, None, n, False, n))
        if sum(n for _, _, n, _, _ in mine) != whole:
            serial = short in SERIAL
            mine = [([modname], None, whole, serial, shard_priority(short, None, whole, serial))] if whole else []
        for names, _cls, n, serial, prio in mine:
            shards.append([names, n, serial, prio])
    if spec["kind"] == "discover":  # anything discover would find that the module walk above did not
        found = unittest.TestLoader().discover(spec["start"], pattern=spec["pattern"]).countTestCases()
        listed = sum(n for _, n, *_ in shards)
        if found != listed and not errors:
            shards = [[["<discover>"], found, False, found]]
    return {"shards": shards, "total": sum(n for _, n, *_ in shards), "errors": errors}


def child_run(spec, names):
    loader = unittest.TestLoader()
    if names == ["<discover>"]:
        suite = loader.discover(spec["start"], pattern=spec["pattern"])
    else:
        suite = loader.loadTestsFromNames(names)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0, warnings="default").run(suite)

    def entries(pairs):
        return [{"test": str(t), "id": t.id(), "traceback": tb} for t, tb in pairs]
    return {"run": result.testsRun, "failures": entries(result.failures), "errors": entries(result.errors),
            "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
            "unexpected_successes": [str(t) for t in result.unexpectedSuccesses],
            "ok": result.wasSuccessful()}


def child_main(argv):
    mode, spec_json, out = argv[:3]
    spec = json.loads(spec_json)
    child_setup(spec)
    data = child_list(spec) if mode == "--_list" else child_run(spec, argv[3:])
    sys.stdout.flush()
    sys.stderr.flush()
    Path(out).write_text(json.dumps(data), encoding="utf-8")
    return 0


# --- parent side ----------------------------------------------------------------------------------------------

class Pool:
    """--jobs worker threads taking the highest-priority job first; a job may add more jobs."""

    def __init__(self, jobs):
        self.q = queue.PriorityQueue()
        self.seq = 0
        self.pending = 0
        self.cond = threading.Condition()
        self.threads = [threading.Thread(target=self.work, daemon=True) for _ in range(jobs)]
        for t in self.threads:
            t.start()

    def add(self, priority, fn):
        with self.cond:
            self.pending += 1
            self.seq += 1
            self.q.put((-priority, self.seq, fn))

    def work(self):
        while True:
            _, _, fn = self.q.get()
            try:
                fn()
            except BaseException:  # a bug here must not hang the run
                traceback.print_exc()
            with self.cond:
                self.pending -= 1
                self.cond.notify_all()

    def wait(self):
        with self.cond:
            while self.pending:
                self.cond.wait()


class Run:
    def __init__(self, jobs, keep):
        self.base = Path(tempfile.mkdtemp(prefix="rc-"))
        self.keep = keep
        self.n = 0
        self.lock = threading.Lock()
        self.extra_cleanup = []
        self.pool = Pool(jobs)
        self.serial_lock = threading.Lock()  # SERIAL shards hold it; they are queued last

    def scratch(self):
        """A fresh folder for one child process: logs, result, and (for test shards) its HOME/PM_HOME/TMPDIR."""
        with self.lock:
            self.n += 1
            folder = self.base / str(self.n)
        folder.mkdir()
        return folder

    def test_env(self, folder):
        home, pm_home, tmp = folder / "h", folder / "p", folder / "t"
        for d in (home, pm_home, tmp):
            d.mkdir()
        (home / ".gitconfig").write_text(GITCONFIG, encoding="utf-8")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(STRIP_PREFIXES) and k not in STRIP_NAMES}
        env.update(HOME=str(home), USERPROFILE=str(home), PM_HOME=str(pm_home),
                   TMPDIR=str(tmp), TEMP=str(tmp), TMP=str(tmp), PYTHONUTF8="1")
        return env


class Check:
    """One line of the report."""

    def __init__(self, label):
        self.label = label
        self.started = None
        self.ended = None
        self.ok = None
        self.summary = ""
        self.detail = []  # lines shown under the failure header
        self.done = threading.Event()

    @property
    def seconds(self):
        return (self.ended or time.time()) - (self.started or time.time())


class CommandCheck(Check):
    def __init__(self, label, argv, validate=None, cost=50):
        super().__init__(label)
        self.argv, self.validate, self.cost = argv, validate, cost

    def schedule(self, run, report):
        def job():
            self.started = time.time()
            folder = run.scratch()
            log = folder / "out.log"
            try:
                with open(log, "wb") as f:
                    proc = subprocess.run(self.argv, cwd=ROOT, stdout=subprocess.PIPE if self.validate else f,
                                          stderr=f, stdin=subprocess.DEVNULL)
            except FileNotFoundError as exc:
                self.ended = time.time()
                self.ok = False
                self.summary = f"command not found: {self.argv[0]}"
                self.detail = [str(exc)]
                report(self)
                return
            except OSError as exc:
                self.ended = time.time()
                self.ok = False
                self.summary = f"cannot start {self.argv[0]}: {exc}"
                self.detail = [str(exc)]
                report(self)
                return
            text = log.read_text(encoding="utf-8", errors="replace")
            self.ended = time.time()
            self.ok = proc.returncode == 0
            why = f"exit {proc.returncode}"
            if self.ok and self.validate:
                why = self.validate(proc.stdout)
                self.ok = why is None
            if not self.ok:
                self.summary = why
                self.detail = text.splitlines()[-TAIL:]
            report(self)
        run.pool.add(self.cost, job)


class FailedCheck(Check):
    """A check that already failed before starting (e.g. git diff failed while checking render-check trigger)."""

    def __init__(self, label, summary, detail=None):
        super().__init__(label)
        self._summary = summary
        self._detail = detail or []

    def schedule(self, run, report):
        now = time.time()
        self.started = self.ended = now
        self.ok = False
        self.summary = self._summary
        self.detail = list(self._detail)
        report(self)


class RenderCheck(CommandCheck):
    """Runs tests/render_check.py in parallel with the rest of the suite at top priority.

    Exit 2 means BLOCKED / NOT JUDGED: explicitly reported and fails the run (exit 1) so a UI merge cannot
    slip through without a real render judgement.
    """

    def __init__(self, root):
        super().__init__("render-check", [sys.executable, str(root / "tests/render_check.py")], cost=20000)
        self.root = root

    def _argv_for(self, run):
        argv = list(self.argv)
        if os.name != "nt":
            default_sock = self.root / "evidence/render-check/run/app/herdr-app.sock"
            if len(str(default_sock).encode()) >= RENDER_CHECK_SUN_LEN:
                cand = run.base / "rc"
                if len(str(cand / "app/herdr-app.sock").encode()) >= RENDER_CHECK_SUN_LEN:
                    cand = Path(tempfile.mkdtemp(prefix="dudu-rc-", dir="/tmp"))
                    with run.lock:
                        run.extra_cleanup.append(cand)
                argv += ["--dir", str(cand)]
        return argv

    def schedule(self, run, report):
        def job():
            self.started = time.time()
            folder = run.scratch()
            log = folder / "out.log"
            argv = self._argv_for(run)
            try:
                with open(log, "wb") as f:
                    proc = subprocess.run(argv, cwd=self.root, stdout=f, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL)
            except OSError as exc:
                self.ended = time.time()
                self.ok = False
                self.summary = f"cannot start {argv[0]}: {exc}"
                self.detail = [str(exc)]
                report(self)
                return
            text = log.read_text(encoding="utf-8", errors="replace")
            self.ended = time.time()
            self.ok = proc.returncode == 0
            if not self.ok:
                if proc.returncode == 2:
                    self.summary = f"exit 2: {RENDER_NOT_JUDGED_MSG}"
                else:
                    self.summary = f"exit {proc.returncode}"
                self.detail = text.splitlines()[-RENDER_TAIL:]
            report(self)
        run.pool.add(self.cost, job)


def json_output(stdout):
    try:
        json.loads(stdout)
        return None
    except ValueError as e:
        return f"output is not JSON: {e}"


class TestGroup(Check):
    def __init__(self, label, spec):
        super().__init__(label)
        self.spec = spec
        self.listed = 0
        self.ran = 0
        self.skipped = 0
        self.shards = 0
        self.work = 0.0
        self.failed = []  # (kind, entry)
        self.crashes = []
        self.left = 0
        self.mutex = threading.Lock()

    def child(self, run, mode, extra, env=None):
        folder = run.scratch()
        out = folder / "result.json"
        log = folder / "out.log"
        began = time.time()
        with open(log, "wb") as f:
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), mode, json.dumps(self.spec),
                                   str(out), *extra], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, env=env or run.test_env(folder))
        took = time.time() - began
        data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        return data, proc.returncode, log, took

    def schedule(self, run, report):
        def list_job():
            self.started = time.time()
            data, code, log, took = self.child(run, "--_list", [])
            with self.mutex:
                self.work += took
            if data is None:
                self.crashes.append(("listing the tests", code, log))
                return self.finish(report)
            for err in data["errors"]:
                self.crashes.append((err, None, None))
            self.listed = data["total"]
            self.shards = len(data["shards"])
            self.left = self.shards
            if not self.left:
                return self.finish(report)
            for shard in data["shards"]:
                names, count, serial = shard[:3]
                cost = shard[3] if len(shard) > 3 else (2000 if SPLIT_METHODS & set(names[0].split(".")) else count)
                run.pool.add(-1 if serial else cost, self.shard_job(run, report, names, serial))
        run.pool.add(10000, list_job)

    def shard_job(self, run, report, names, serial):
        def job():
            if serial:
                with run.serial_lock:
                    result = self.child(run, "--_run", names)
            else:
                result = self.child(run, "--_run", names)
            data, code, log, took = result
            with self.mutex:
                self.work += took
                if data is None:
                    self.crashes.append((f"shard {' '.join(names)}", code, log))
                else:
                    self.ran += data["run"]
                    self.skipped += data["skipped"]
                    self.failed += [("FAIL", e) for e in data["failures"]]
                    self.failed += [("ERROR", e) for e in data["errors"]]
                    self.failed += [("UNEXPECTED SUCCESS", {"test": t, "traceback": ""})
                                    for t in data["unexpected_successes"]]
                self.left -= 1
                last = self.left == 0
            if last:
                self.finish(report)
        return job

    def finish(self, report):
        self.ended = time.time()
        problems = []
        if self.failed:
            problems.append(f"{len(self.failed)} failed")
        if self.crashes:
            problems.append(f"{len(self.crashes)} could not run")
        if not self.crashes and self.ran != self.listed:
            problems.append(f"ran {self.ran} of {self.listed} listed")
        self.ok = not problems
        counts = f"{self.ran} tests" + (f", {self.skipped} skipped" if self.skipped else "")
        self.summary = (", ".join(problems) + "; " if problems else "") + \
            f"{counts} in {self.shards} shards, {self.work:.1f}s of work"
        for kind, e in sorted(self.failed, key=lambda x: x[1].get("id", x[1]["test"])):
            self.detail += ["-" * 70, f"{kind}: {e['test']}", *e["traceback"].rstrip().splitlines()]
        for what, code, log in self.crashes:
            self.detail += ["-" * 70, f"COULD NOT RUN: {what}" + (f" (exit {code})" if code is not None else "")]
            if log:
                self.detail += log.read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL:]
        report(self)


def checks(root, render_check="never"):
    found = []
    render_skipped = False
    if render_check == "always":
        found.append(RenderCheck(root))
    elif render_check == "auto":
        paths, err = staged_files(root)
        if err:
            found.append(FailedCheck("render-check", f"git diff --cached failed: {err}"))
        elif needs_render_check(paths):
            found.append(RenderCheck(root))
        else:
            render_skipped = True
    for mod in sorted(root.glob("mods/pm-*")):
        if mod.is_dir():
            found.append(CommandCheck(f"herdr-app check {mod.relative_to(root)}", ["herdr-app", "check", str(mod)]))
    for test in sorted(root.glob("mods/*/model.test.mjs")):
        rel = test.relative_to(root)
        cost = 1500 if rel.parts[1] == "pm-project" else 60
        found.append(CommandCheck(f"node --test {rel}", ["node", "--test", str(rel)], cost=cost))

    def files(label, *paths):
        return TestGroup(f"unittest {label}", {"kind": "files", "files": list(paths)})
    found.append(files("tests/test_install.py", "tests/test_install.py"))
    found.append(files("tests/test_render_check_win.py", "tests/test_render_check_win.py"))
    if (root / "tests/test_run_checks.py").is_file():
        found.append(files("tests/test_run_checks.py", "tests/test_run_checks.py"))
    if (root / SAFETY_NET).is_dir():
        found.append(TestGroup("unittest scripts/tests (discover)",
                               {"kind": "discover", "start": SAFETY_NET, "pattern": "test_*.py"}))
    found.append(CommandCheck("pm.py state (JSON)", [sys.executable, f"{SCRIPTS}/pm.py", "state"],
                              validate=json_output, cost=40))
    return found, render_skipped


def default_jobs():
    """Default worker count: on macOS, cap to Performance cores (<= 14) to avoid E-core throttling and
    XNU fork/APFS/pgrep contention observed above ~14-16 concurrent subprocess-heavy shards."""
    cpus = os.cpu_count() or 4
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["sysctl", "-n", "hw.perflevel0.physicalcpu"], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=2)
            if r.returncode == 0 and r.stdout.strip().isdigit():
                p_cores = int(r.stdout.strip())
                if p_cores > 0:
                    return max(1, min(p_cores, 14))
        except (OSError, subprocess.SubprocessError):
            pass
        return max(1, min(cpus, 14))
    return max(1, cpus)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--jobs", "-j", type=int, default=default_jobs(),
                   help="processes at once (default: P-cores capped at 14 on macOS, CPUs elsewhere)")
    p.add_argument("--only", action="append", default=[], help="run only the checks whose label contains this")
    p.add_argument("--render-check", choices=("never", "auto", "always"), default="never",
                   help="also run tests/render_check.py in parallel (auto: only when staged diff touches UI mods or render_check*)")
    p.add_argument("--keep", action="store_true", help="keep the logs and temporary homes, and say where")
    p.add_argument("--list", action="store_true", help="print the checks and exit")
    a = p.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        os.chdir(ROOT)
    all_checks, render_skipped = checks(ROOT, render_check=a.render_check)
    todo = [c for c in all_checks if not a.only or any(o in c.label for o in a.only)]
    render_selected = not a.only or any(o in "render-check" for o in a.only)
    if a.list or (not todo and not (render_skipped and render_selected)):
        lines = [c.label for c in todo]
        if a.list and render_skipped and render_selected:
            lines.append("render-check (skipped: no UI files in staged diff)")
        print("\n".join(lines) or "run_checks: no check matches")
        return 0 if lines else 2
    run = Run(max(1, a.jobs), a.keep)
    out = threading.Lock()
    began = time.time()
    if render_skipped and render_selected:
        print("skip   0.0s  render-check  (no UI files in staged diff)", flush=True)

    def report(check):
        with out:
            print(f"{'ok  ' if check.ok else 'FAIL'} {check.seconds:6.1f}s  {check.label}"
                  + (f"  ({check.summary})" if check.summary else ""), flush=True)
        check.done.set()

    for c in todo:
        c.schedule(run, report)
    run.pool.wait()
    for c in todo:  # a check that never reported (a bug in this script) is a failure, not a pass
        if not c.done.is_set():
            c.ok, c.ended = False, time.time()
            c.summary = "did not finish"
            report(c)
    failed = [c for c in todo if not c.ok]
    for c in failed:
        print(f"\n{'=' * 70}\nFAIL {c.label}: {c.summary}")
        print("\n".join(c.detail))
    tests = sum(c.ran for c in todo if isinstance(c, TestGroup))
    print(f"\nrun_checks: {len(todo)} checks, {len(failed)} failed, {tests} tests, "
          f"{time.time() - began:.1f}s with {a.jobs} jobs")
    if a.keep or failed:
        print(f"run_checks: logs in {run.base}")
    else:
        shutil.rmtree(run.base, ignore_errors=True)
        for extra in run.extra_cleanup:
            shutil.rmtree(extra, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--_list", "--_run"):
        sys.exit(child_main(sys.argv[1:]))
    sys.exit(main())
