#!/usr/bin/env python3
"""The full check before a merge, run in parallel: the mods' `herdr-app check`, their node model tests, every
pm unittest file and the scripts/tests safety net, and `pm.py state`.

    python3 tests/run_checks.py [--jobs N] [--only TEXT] [--keep] [--list]

Run from the repository root (land runs the verify file there). Prints one line per check as it ends, with its
wall time; then, for each failed check, the traceback of every failed test (or the last lines a failed command
printed); then a summary line. Exit 0 when everything passed, 1 when anything failed, 2 on bad usage.

How the unittest files run: each file (and the scripts/tests folder as one group) is first listed in a child
process, then split into shards, one per TestCase class (a class of more than CHUNK tests in chunks; one per test
method for the modules in SPLIT_METHODS, whose methods each replay a whole scenario), and every shard runs in its own
`python3` process. Shards and the other
checks share one pool of --jobs processes (default: the number of CPUs), the longest ones first. A file's tests are
imported under the same module names as `python3 -m unittest <file>` and `unittest discover` give them, so a test
sees the same `__name__`, `__file__` and `sys.path` as in the serial run. After the run, the tests run per group
must equal the tests listed, so a shard that loads fewer tests is a failure, not a silent pass.

Isolation: each test shard gets its own empty HOME (with a .gitconfig naming a test author and `main` as the
default branch, as this machine's has), PM_HOME and TMPDIR, and an environment without the terminal and agent
session variables (HC_*, HERDR_*, CLAUDE*, CODEX_*, PI_*, DISCORD_*, PM_*, GIT_DIR and friends): no shard reaches
the real ledger, lock files, hc terminals or another shard's temporary files. The command checks (herdr-app check,
node, pm.py state) run with the caller's environment, as the verify file ran them: `pm.py state` is meant to read
the real ledger.

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

# Modules whose test methods each get a shard of their own: every method of test_replay replays the full pm.py
# scenario on two sides (~30 s); as one class shard they would add up to ~75 s.
SPLIT_METHODS = {"test_replay"}

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

CHUNK = 10  # a TestCase class with more tests than this is split into chunks of about this many
TAIL = 30  # lines of a failed command's output to show, as the verify file's `| tail -30` did


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
    """{"shards": [[names, count, serial], ...], "total": n, "errors": [...]}: one shard per TestCase class, a class
    of more than CHUNK tests in chunks of about CHUNK, one per method for SPLIT_METHODS; a whole module when it has
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
        mine = []  # (names to load, class or None, number of tests)
        if not hasattr(module, "load_tests"):
            for attr in dir(module):
                obj = getattr(module, attr)
                if not (isinstance(obj, type) and issubclass(obj, unittest.TestCase)):
                    continue
                methods = [f"{modname}.{attr}.{m}" for m in loader.getTestCaseNames(obj)]
                if short in SPLIT_METHODS:
                    mine += [([m], attr, 1) for m in methods]
                elif len(methods) > CHUNK:
                    parts = -(-len(methods) // CHUNK)
                    mine += [(methods[i::parts], attr, len(methods[i::parts])) for i in range(parts)]
                elif methods:
                    mine.append(([f"{modname}.{attr}"], attr, len(methods)))
        if sum(n for _, _, n in mine) != whole:
            mine = [([modname], None, whole)] if whole else []
        for names, cls, n in mine:
            serial = short in SERIAL or (cls is not None and f"{short}.{cls}" in SERIAL)
            shards.append([names, n, serial])
    if spec["kind"] == "discover":  # anything discover would find that the module walk above did not
        found = unittest.TestLoader().discover(spec["start"], pattern=spec["pattern"]).countTestCases()
        listed = sum(n for _, n, _ in shards)
        if found != listed and not errors:
            shards = [[["<discover>"], found, False]]
    return {"shards": shards, "total": sum(n for _, n, _ in shards), "errors": errors}


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
            for names, count, serial in data["shards"]:
                cost = 1000 if SPLIT_METHODS & set(names[0].split(".")) else count
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


def checks(root):
    found = []
    for mod in sorted(root.glob("mods/pm-*")):
        if mod.is_dir():
            found.append(CommandCheck(f"herdr-app check {mod.relative_to(root)}", ["herdr-app", "check", str(mod)]))
    for test in sorted(root.glob("mods/*/model.test.mjs")):
        rel = test.relative_to(root)
        found.append(CommandCheck(f"node --test {rel}", ["node", "--test", str(rel)], cost=60))

    def files(label, *paths):
        return TestGroup(f"unittest {label}", {"kind": "files", "files": list(paths)})
    found.append(files("tests/test_install.py", "tests/test_install.py"))
    found.append(files("tests/test_render_check_win.py", "tests/test_render_check_win.py"))
    if (root / SAFETY_NET).is_dir():
        found.append(TestGroup("unittest scripts/tests (discover)",
                               {"kind": "discover", "start": SAFETY_NET, "pattern": "test_*.py"}))
    found.append(CommandCheck("pm.py state (JSON)", [sys.executable, f"{SCRIPTS}/pm.py", "state"],
                              validate=json_output, cost=40))
    return found


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 4, help="processes at once (default: CPUs)")
    p.add_argument("--only", action="append", default=[], help="run only the checks whose label contains this")
    p.add_argument("--keep", action="store_true", help="keep the logs and temporary homes, and say where")
    p.add_argument("--list", action="store_true", help="print the checks and exit")
    a = p.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        os.chdir(ROOT)
    todo = [c for c in checks(ROOT) if not a.only or any(o in c.label for o in a.only)]
    if a.list or not todo:
        print("\n".join(c.label for c in todo) or "run_checks: no check matches")
        return 0 if todo else 2
    run = Run(max(1, a.jobs), a.keep)
    out = threading.Lock()
    began = time.time()

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
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--_list", "--_run"):
        sys.exit(child_main(sys.argv[1:]))
    sys.exit(main())
