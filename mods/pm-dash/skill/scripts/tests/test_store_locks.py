"""Ledger store write safety on `make_ctx` + `tests/fakes.py`: per-file locks, atomic writes, damaged and
unreadable files, and real multi-process concurrency (update, land, retire, registration, session writes, delivered
cursor, task numbers). Moved from test_pm_store.py (Stage 6a): every test builds its own `Context`; what those
tests patched on `pm` is injected into the Context (a probing `FileStore`, `after_save` hooks, a `replace_fn`, a git
port) instead. Child processes run pmlib (or the real `pm.py` CLI) against the test's temporary ledger, never `pm`.

Later in this file: `WithoutFcntl` (pm.py where `import fcntl` fails, as on Windows).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

# pmlib works out its legacy ledger home when first imported. Name a fresh temporary one, so a legacy fallback still
# left in production code (ManagerSessions.rotate's deliver_later) never looks at a real ledger; a test file that
# imported pmlib earlier keeps its own.
if "pmlib.context" not in sys.modules:
    os.environ["PM_HOME"] = tempfile.mkdtemp(prefix="pm-store-locks-legacy-")
    os.environ.pop("HERDR_PANE_ID", None)
    os.environ.pop("HC_TERMINAL_ID", None)

from fakes import FakeHc, StubGit, make_ctx  # noqa: E402
from pmlib import osutil  # noqa: E402
from pmlib import store as store_mod  # noqa: E402
from pmlib.errors import NotFound  # noqa: E402
from pmlib.events.deliver import Delivery  # noqa: E402
from pmlib.gitrepo import GitRepo  # noqa: E402
from pmlib.home import project_slug  # noqa: E402
from pmlib.ledger.ledger import Ledger  # noqa: E402
from pmlib.manager.service import ManagerSessions  # noqa: E402
from pmlib.project.conversation import Conversation  # noqa: E402
from pmlib.project.project import ProjectRegistry  # noqa: E402
from pmlib.project.readmodel import Projects  # noqa: E402
from pmlib.store import FileStore  # noqa: E402
from pmlib.workers.service import Workers  # noqa: E402
from pmlib.workers.wait import wait_for_report_events_for  # noqa: E402

PM_SCRIPT = SCRIPTS / "pm.py"

# What a child process runs first: pmlib from this checkout, every module wired as the CLI wires it (pmlib.cli
# imports the caller, so Context.from_env() gets ctx.caller), against the PM_HOME of its environment.
CHILD_PRELUDE = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import pmlib.cli\n"
    "from pmlib.context import Context\n"
)


def clean_child_env(ledger_home: Path) -> dict:
    """Environment for child processes: points strictly at the temporary ledger, no herdr/hc terminal."""
    env = dict(os.environ)
    env["PM_HOME"] = str(ledger_home)
    for key in ("HERDR_PANE_ID", "HC_TERMINAL_ID", "HERDR_WORKSPACE_ID", "HERDR_ENV", "CLAUDE_CODE_SESSION_ID"):
        env.pop(key, None)
    return env


def init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *args: subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "initial")
    return path


class StoreLocksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-store-locks-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ctx = make_ctx(self.base, git=GitRepo())
        self.root = self.ctx.home.root
        self.pms = self.ctx.home.registrations
        self.tasks = self.ctx.home.tasks
        self.projects = self.ctx.home.projects
        for d in (self.pms, self.tasks, self.projects):
            d.mkdir(parents=True)

    def make_task(self, task_id="demo-t1", repo="/work/demo", status="in_progress", **extra):
        task = {
            "id": task_id,
            "title": "Test Task",
            "project": Path(repo).name,
            "repo": str(repo),
            "status": status,
            "base": "main",
            "owner": "pm",
            "pane": "",
            "created": "2026-11-21 10:00",
            "updated": "2026-11-21 10:00",
            "log": [{"at": "2026-11-21 10:00", "by": "pm", "text": "created"}],
            **extra,
        }
        self.ctx.store.change_task(task_id, lambda _cur: task)
        return task

    def run_children(self, codes_and_args, *, timeout=60):
        """Start every (code, extra argv) child at once against this test's ledger; their stdouts once all passed."""
        env = clean_child_env(self.root)
        procs = [subprocess.Popen([sys.executable, "-c", code, str(SCRIPTS), *map(str, args)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for code, args in codes_and_args]
        outs = []
        for p in procs:
            out, err = p.communicate(timeout=timeout)
            self.assertEqual(p.returncode, 0, f"child failed:\nstdout={out}\nstderr={err}")
            outs.append(out)
        return outs

    # --- locks, atomic writes, damaged files ---------------------------------------------------------------------

    def test_change_task_locks_under_locks_dir_and_unlocks_before_conversation_board_and_discord(self):
        self.make_task("demo-lock")
        lock_file = self.root / "locks" / "task-demo-lock.lock"
        self.assertTrue(lock_file.is_file())
        self.assertEqual(list(self.tasks.glob("*.tmp")), [])

        lock_states = []

        def probe_lock(label):
            with open(lock_file, "a+") as f:
                try:
                    store_mod.lock_file(f)
                    store_mod.unlock_file(f)
                    lock_states.append((label, "unlocked"))
                except OSError:
                    lock_states.append((label, "locked"))

        ctx, test = self.ctx, self

        class ProbingStore(FileStore):
            """The conversation event goes in through append_event: by then the task is saved and unlocked."""

            def append_event(self, slug, event, *, timeout=None):
                probe_lock("record")
                on_disk = FileStore.task(self, "demo-lock")
                test.assertTrue(any(e["text"] == "hello after unlock" for e in on_disk["log"]))
                return super().append_event(slug, event, timeout=timeout)

        ctx.store = ProbingStore(ctx.home)
        # The board and the Discord mirror are the Context's after_save hooks (write_board, post_board in the CLI).
        ctx.after_save = (lambda: probe_lock("write_board"), lambda: probe_lock("post_board"))

        def inside_change(cur, ch):
            probe_lock("inside")
            ch.note("hello after unlock")
            return cur

        Ledger(ctx).change("demo-lock", inside_change)

        self.assertEqual(lock_states, [
            ("inside", "locked"),
            ("record", "unlocked"),
            ("write_board", "unlocked"),
            ("post_board", "unlocked"),
        ])
        self.assertEqual([e["text"] for e in Conversation(ctx, "/work/demo").events()], ["hello after unlock"])

    def test_failed_write_cleans_up_temp_file_and_emits_no_orphan_event(self):
        self.make_task("demo-fail", repo=str(self.tmp.name))

        def boom(src, dst):
            self.assertTrue(src.name.startswith(f".demo-fail.json.{os.getpid()}."))
            self.assertTrue(src.name.endswith(".tmp"))
            raise OSError("disk full")

        self.ctx.store = FileStore(self.ctx.home, replace_fn=boom)
        with self.assertRaises(OSError):
            Ledger(self.ctx).change("demo-fail", lambda cur, ch: (ch.note("should not stick"), cur)[1])

        # Original task untouched, no orphan temp file, no orphan conversation event.
        self.assertEqual(len(self.ctx.store.task("demo-fail")["log"]), 1)
        self.assertEqual(list(self.tasks.glob("*.tmp")), [])
        self.assertEqual(Conversation(self.ctx, self.tmp.name).events(), [])

    def test_damaged_and_unreadable_files_are_never_overwritten(self):
        store = self.ctx.store
        # 1. Corrupt JSON task file
        bad_task = self.tasks / "demo-bad.json"
        bad_task.write_text("{truncated json", encoding="utf-8")
        with self.assertRaises(store_mod.DamagedFileError):
            store.change_task("demo-bad", lambda cur: {"id": "demo-bad", "title": "wiped"})
        self.assertEqual(bad_task.read_text(encoding="utf-8"), "{truncated json")

        # 2. Non-object JSON registration file
        bad_reg = self.pms / "demo.json"
        bad_reg.write_text("[1, 2, 3]\n", encoding="utf-8")
        with self.assertRaises(store_mod.DamagedFileError):
            store.change_registration("demo", lambda cur: {"name": "pm-demo"})
        self.assertEqual(bad_reg.read_text(encoding="utf-8"), "[1, 2, 3]\n")

        # 3. Symlink at target path (like app:service/ended.go openPlain)
        if os.name != "nt":
            target = self.base / "outside.json"
            target.write_text('{"id": "demo-link"}\n', encoding="utf-8")
            link = self.tasks / "demo-link.json"
            link.symlink_to(target)
            with self.assertRaises(store_mod.DamagedFileError):
                store.change_task("demo-link", lambda cur: {"id": "demo-link", "status": "done"})
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(encoding="utf-8"), '{"id": "demo-link"}\n')

        # 4. Unreadable file (permission denied)
        if os.name != "nt" and os.geteuid() != 0:
            locked_perm = self.tasks / "demo-noperm.json"
            locked_perm.write_text('{"id": "demo-noperm"}\n', encoding="utf-8")
            locked_perm.chmod(0o000)
            self.addCleanup(lambda: locked_perm.chmod(0o644) if locked_perm.exists() else None)
            with self.assertRaises(store_mod.UnreadableFileError):
                store.change_task("demo-noperm", lambda cur: {"id": "demo-noperm", "status": "done"})
            locked_perm.chmod(0o644)
            self.assertEqual(locked_perm.read_text(encoding="utf-8"), '{"id": "demo-noperm"}\n')

    def test_lock_timeout_and_automatic_recovery_after_holder_crash(self):
        self.make_task("demo-held")
        lock_path = self.root / "locks" / "task-demo-held.lock"

        # Spawn a real subprocess that grabs the per-task lock and holds it until killed.
        holder_code = (
            "import sys, time\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from pmlib import store\n"
            "f = open(sys.argv[2], 'a+')\n"
            "store.lock_file(f)\n"
            "print('LOCKED', flush=True)\n"
            "time.sleep(60)\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", holder_code, str(SCRIPTS), str(lock_path)],
            env=clean_child_env(self.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def _cleanup_proc():
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

        self.addCleanup(_cleanup_proc)
        self.assertEqual(proc.stdout.readline().strip(), "LOCKED")

        # While the other process holds the lock, change_task times out cleanly with LockTimeoutError.
        store = self.ctx.store
        t0 = time.monotonic()
        with self.assertRaises(store_mod.LockTimeoutError):
            store.change_task("demo-held", lambda cur: {**cur, "status": "done"}, timeout=0.15)
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 0.12)
        self.assertEqual(store.task("demo-held")["status"], "in_progress")

        # Simulate a hard crash (SIGKILL): OS releases the lock automatically; next write succeeds immediately.
        proc.kill()
        proc.wait()
        updated = store.change_task("demo-held", lambda cur: {**cur, "status": "done"}, timeout=1.0)
        self.assertEqual(updated["status"], "done")
        self.assertEqual(store.task("demo-held")["status"], "done")

    def test_append_event_returns_exact_byte_offset_compatible_with_events_window(self):
        store = self.ctx.store
        o1 = store.append_event("demo", {"at": "2026-11-21 10:00:01", "type": "user", "text": "你好\u2028世界"})
        o2 = store.append_event("demo", {"at": "2026-11-21 10:00:02", "type": "pm", "text": "收到"})
        log_path = self.projects / "demo" / "conversation.jsonl"
        self.assertEqual(o2, log_path.stat().st_size)
        self.assertGreater(o2, o1)

        page_before = store.events("demo", before=o2, limit=10)
        self.assertEqual([e["text"] for e in page_before["events"]], ["你好\u2028世界", "收到"])
        self.assertEqual(page_before["events"][0]["offset"], o1)
        self.assertEqual(page_before["events"][1]["offset"], o2)

        page_after = store.events("demo", after=o1, limit=10)
        self.assertEqual([e["text"] for e in page_after["events"]], ["收到"])
        self.assertEqual(page_after["offset"], o2)

    def test_ledger_reads_through_the_context_store_and_honours_an_injected_save(self):
        ctx = self.ctx
        repo = init_git_repo(self.base / "proj")
        slug = project_slug(repo)
        ctx.store.change_registration(slug, lambda _cur: {"name": f"pm-{slug}", "project": repo.name, "repo": str(repo)})
        self.assertEqual(ProjectRegistry(ctx).pm_record(str(repo))["name"], f"pm-{slug}")

        self.make_task("proj-1", repo=str(repo))
        ledger = Ledger(ctx)
        self.assertEqual(ledger.load("proj-1")["id"], "proj-1")
        self.assertEqual([t["id"] for t in ledger.all_tasks()], ["proj-1"])

        Conversation(ctx, repo).record("user", text="hi")
        self.assertEqual([e["text"] for e in Conversation(ctx, repo).events()], ["hi"])

        # A save hook given to the Ledger (what a pm.save spy was) is what change() saves through.
        seen = []

        def spy_save(task):
            seen.append(task["status"])
            ledger._save_impl(task)

        Ledger(ctx, _save_fn=spy_save).change("proj-1", lambda cur, ch: {**cur.raw, "status": "review"})
        self.assertEqual(seen, ["review"])
        self.assertEqual(Ledger(ctx).load("proj-1")["status"], "review")

    # --- many processes at once ----------------------------------------------------------------------------------

    def test_multiprocess_concurrent_updates_to_same_task_lose_zero_entries(self):
        repo = init_git_repo(self.base / "mp-repo")
        self.make_task("mp-repo-shared", repo=str(repo))

        n_procs = 4
        n_iters = 8
        # Each child runs the real `pm.py update <id> --note ...` command iters times in one process.
        worker_code = CHILD_PRELUDE + (
            "wid, iters = int(sys.argv[2]), int(sys.argv[3])\n"
            "for i in range(iters):\n"
            "    sys.argv = ['pm.py', 'update', 'mp-repo-shared', '--note', f'p{wid}-n{i}']\n"
            "    pmlib.cli.main()\n"
        )
        self.run_children([(worker_code, (w, n_iters)) for w in range(n_procs)])

        task = self.ctx.store.task("mp-repo-shared")
        texts = {e["text"] for e in task["log"]}
        expected = {f"p{w}-n{i}" for w in range(n_procs) for i in range(n_iters)}
        self.assertTrue(expected.issubset(texts), f"missing notes: {expected - texts}")
        self.assertEqual(len(task["log"]), 1 + n_procs * n_iters)

        # Every conversation event arrived intact with no torn lines.
        events = Conversation(self.ctx, repo).events()
        event_texts = {e["text"] for e in events if e.get("type") == "thread"}
        self.assertEqual(event_texts, expected)
        # No leftover .tmp files.
        self.assertEqual(list(self.tasks.glob("*.tmp")), [])

    def test_multiprocess_concurrent_registration_and_session_updates_lose_zero_fields(self):
        slug = "demo"
        self.ctx.store.change_registration(slug, lambda _cur: {"name": "pm-demo", "project": "demo", "repo": "/work/demo"})

        worker_code = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from pmlib.home import Home\n"
            "from pmlib.store import FileStore\n"
            "store = FileStore(Home(sys.argv[2]))\n"
            "wid, iters = int(sys.argv[3]), int(sys.argv[4])\n"
            "for i in range(iters):\n"
            "    def _upd(cur, _i=i):\n"
            "        cur = dict(cur)\n"
            "        cur[f'k{wid}'] = _i\n"
            "        cur['total'] = cur.get('total', 0) + 1\n"
            "        return cur\n"
            "    store.change_registration('demo', _upd)\n"
        )
        self.run_children([(worker_code, (self.root, w, 15)) for w in range(4)])

        rec = self.ctx.store.registration(slug)
        self.assertEqual(rec["total"], 60)
        for w in range(4):
            self.assertEqual(rec[f"k{w}"], 14)
        self.assertEqual(list(self.pms.glob("*.tmp")), [])

    def test_land_does_not_overwrite_worker_updates_during_checks_both_fail_and_pass(self):
        repo = init_git_repo(self.base / "land-repo")
        run = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
        run("checkout", "-q", "-b", "feat/x")
        (repo / "feat.txt").write_text("feature\n", encoding="utf-8")
        run("add", "feat.txt")
        run("commit", "-q", "-m", "add feat")
        run("checkout", "-q", "main")

        self.make_task("land-repo-x", repo=str(repo), branch="feat/x", status="review")
        slug = project_slug(repo)
        verify_path = self.projects / slug / "verify"
        verify_path.parent.mkdir(parents=True, exist_ok=True)

        # Case 1: check fails, but during the check a real worker process runs `pm.py update` and writes a note + commit.
        worker_cmd = (
            f'"{sys.executable}" "{PM_SCRIPT}" --home "{self.root}" '
            'update land-repo-x --commit abc1234 --note "worker-wrote-during-failed-land"'
        )
        verify_path.write_text(f"{worker_cmd}\nexit 1\n", encoding="utf-8")

        proc_fail = subprocess.run(
            [sys.executable, str(PM_SCRIPT), "--home", str(self.root), "land", "land-repo-x"],
            env=clean_child_env(self.root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc_fail.returncode, 1, proc_fail.stdout + proc_fail.stderr)
        after_fail = self.ctx.store.task("land-repo-x")
        self.assertEqual(after_fail.get("commit"), "abc1234")
        fail_texts = [e["text"] for e in after_fail["log"]]
        self.assertTrue(any("worker-wrote-during-failed-land" in t for t in fail_texts), fail_texts)
        self.assertTrue(any("check failed" in t or "检查失败" in t for t in fail_texts), fail_texts)

        # Case 2: check passes, and during the check a real worker process logs another note.
        worker_cmd_pass = (
            f'"{sys.executable}" "{PM_SCRIPT}" --home "{self.root}" '
            'log land-repo-x "worker-wrote-during-passing-land"'
        )
        verify_path.write_text(f"{worker_cmd_pass}\nexit 0\n", encoding="utf-8")

        proc_pass = subprocess.run(
            [sys.executable, str(PM_SCRIPT), "--home", str(self.root), "land", "land-repo-x", "--keep"],
            env=clean_child_env(self.root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc_pass.returncode, 0, proc_pass.stdout + proc_pass.stderr)
        after_pass = self.ctx.store.task("land-repo-x")
        self.assertEqual(after_pass["status"], "merged")
        pass_texts = [e["text"] for e in after_pass["log"]]
        self.assertTrue(any("worker-wrote-during-failed-land" in t for t in pass_texts), pass_texts)
        self.assertTrue(any("worker-wrote-during-passing-land" in t for t in pass_texts), pass_texts)
        self.assertTrue(any("landed:" in t or "已合并" in t for t in pass_texts), pass_texts)

    def test_retire_does_not_overwrite_worker_updates_during_cleanup(self):
        repo = init_git_repo(self.base / "retire-repo")
        run = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
        run("checkout", "-q", "-b", "feat/r")
        (repo / "r.txt").write_text("ok\n", encoding="utf-8")
        run("add", "r.txt")
        run("commit", "-q", "-m", "add r")
        run("checkout", "-q", "main")
        run("merge", "-q", "--no-ff", "feat/r", "-m", "merge r")

        self.make_task("retire-repo-r", repo=str(repo), branch="feat/r", status="merged")
        root, test = self.root, self
        wrote = []

        class WorkerWritesMidRetire(GitRepo):
            """retire's cleanup deletes the branch through the git port, after it read the task and before it saves
            its result: a real child process writes to the task right then."""

            def delete_branch(self, repo_, branch, *, force=True):
                proc = subprocess.run(
                    [sys.executable, str(PM_SCRIPT), "--home", str(root),
                     "log", "retire-repo-r", "worker-wrote-during-retire"],
                    env=clean_child_env(root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                test.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                wrote.append(branch)
                return super().delete_branch(repo_, branch, force=force)

        self.ctx.git = WorkerWritesMidRetire()
        result = Workers(self.ctx).retire("retire-repo-r")

        self.assertEqual(wrote, ["feat/r"])
        task = self.ctx.store.task("retire-repo-r")
        self.assertTrue(task.get("retired"))
        texts = [e["text"] for e in task["log"]]
        self.assertIn("worker-wrote-during-retire", texts)
        self.assertTrue(any("retired: removed" in t for t in texts), texts)
        self.assertIn("retired: removed", result.summary)
        self.assertIn("branch feat/r", result.summary)

    def test_mixed_version_old_pm_writer_does_not_collide_on_temp_filename(self):
        self.make_task("demo-mixed")

        # Simulate an older pm.py that writes `.demo-mixed.json.tmp` without holding the lock,
        # concurrently with the new FileStore using unique per-process temp files.
        old_writer = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "tasks = Path(sys.argv[2])\n"
            "for i in range(60):\n"
            "    tmp = tasks / '.demo-mixed.json.tmp'\n"
            "    tmp.write_text(json.dumps({'id': 'demo-mixed', 'title': 't', 'status': 'in_progress',\n"
            "                               'updated': '2026-11-21 10:00', 'old': i, 'log': []}) + '\\n')\n"
            "    tmp.replace(tasks / 'demo-mixed.json')\n"
        )
        new_writer = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from pmlib.home import Home\n"
            "from pmlib.store import FileStore\n"
            "store = FileStore(Home(sys.argv[2]))\n"
            "for i in range(60):\n"
            "    store.change_task('demo-mixed', lambda cur, _i=i: {**cur, 'new': _i})\n"
        )
        self.run_children([(old_writer, (self.tasks,)), (new_writer, (self.root,))], timeout=30)
        # Final file on disk must be valid JSON object.
        final = self.ctx.store.task("demo-mixed")
        self.assertIsInstance(final, dict)
        self.assertEqual(final["id"], "demo-mixed")

    def test_concurrent_session_round_and_update_preserve_all_fields(self):
        repo = init_git_repo(self.base / "sess-repo")
        self.make_task("sess-repo-w1", repo=str(repo), pane="hc:t9", worker_pane="hc:t9",
                       worker={"kind": "claude"}, status="in_progress")

        # Process 1: remember_worker_session style write (does not bump updated or touch log/round)
        p_sess_code = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from pmlib.home import Home\n"
            "from pmlib.store import FileStore\n"
            "store = FileStore(Home(sys.argv[2]))\n"
            "for i in range(15):\n"
            "    def _set(cur, _i=i):\n"
            "        cur['session'] = {'kind': 'claude', 'id': f'sid-{_i}'}\n"
            "        return cur\n"
            "    store.change_task('sess-repo-w1', _set)\n"
        )
        # Process 2: round_handed (deliver-related write), through the stall watcher over a live Context
        p_round_code = CHILD_PRELUDE + (
            "from pmlib.events.stalls import StallWatcher\n"
            "watcher = StallWatcher(Context.from_env())\n"
            "for i in range(15):\n"
            "    watcher.round_handed('sess-repo-w1', 't9', turn=i)\n"
        )
        # Process 3: worker log updates, the real `pm.py log` command
        p_log_code = CHILD_PRELUDE + (
            "for i in range(15):\n"
            "    sys.argv = ['pm.py', 'log', 'sess-repo-w1', f'step-{i}']\n"
            "    pmlib.cli.main()\n"
        )
        self.run_children([(p_sess_code, (self.root,)), (p_round_code, ()), (p_log_code, ())])

        task = self.ctx.store.task("sess-repo-w1")
        self.assertEqual(task.get("session"), {"kind": "claude", "id": "sid-14"})
        self.assertEqual((task.get("round") or {}).get("terminal"), "t9")
        self.assertEqual((task.get("round") or {}).get("turn"), 14)
        log_texts = {e["text"] for e in task["log"]}
        self.assertTrue({f"step-{i}" for i in range(15)}.issubset(log_texts))

    def test_advance_delivered_multiprocess_monotonic_and_atomic(self):
        repo = init_git_repo(self.base / "deliv-repo")
        slug = project_slug(repo)
        # Seed conversation.jsonl with enough bytes so offsets up to 5000 stay within file size.
        log_path = self.projects / slug / "conversation.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('{"type": "user", "text": "x"}\n' * 300, encoding="utf-8")

        code = CHILD_PRELUDE + (
            "from pmlib.events.deliver import Delivery\n"
            "repo, base = sys.argv[2], int(sys.argv[3])\n"
            "delivery = Delivery(Context.from_env(), repo)\n"
            "for i in range(25):\n"
            "    delivery.advance_delivered(base + i * 10)\n"
        )
        self.run_children([(code, (repo, b)) for b in (100, 200, 300, 400)], timeout=30)

        self.assertEqual(Delivery(self.ctx, str(repo)).delivered_offset(), 400 + 24 * 10)
        self.assertEqual(list((self.projects / slug).glob("*.tmp")), [])

    def test_ack_delivery_multiprocess_claims_once_and_advance_preserves_received(self):
        repo = init_git_repo(self.base / "ack-repo")
        slug = project_slug(repo)
        log_path = self.projects / slug / "conversation.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text('{"type": "user", "text": "x"}\n' * 300, encoding="utf-8")
        delivery = Delivery(self.ctx, str(repo))

        # Deliverer advances outbound cursor first; 4 hook processes race to ack the same batch (100-250).
        delivery.advance_delivered(250)
        code = CHILD_PRELUDE + (
            "from pmlib.events.deliver import Delivery\n"
            "print('CLAIMED' if Delivery(Context.from_env(), sys.argv[2]).ack_delivery(100, 250) else 'REPEAT')\n"
        )
        results = [out.strip() for out in self.run_children([(code, (repo,)) for _ in range(4)], timeout=30)]

        self.assertEqual(results.count("CLAIMED"), 1, results)
        self.assertEqual(results.count("REPEAT"), 3, results)
        # Subsequent outbound advance must preserve acknowledged ranges.
        delivery.advance_delivered(500)
        self.assertEqual(delivery.delivered_offset(), 500)
        self.assertEqual(delivery.received_ranges(), [[100, 250]])

    # --- strict reads ------------------------------------------------------------------------------------------

    def test_load_strict_raises_damaged_and_unreadable_so_wait_retries_and_unfailing_catches(self):
        ledger = Ledger(self.ctx)
        # 1. Genuinely absent task -> NotFound("no task ...")
        with self.assertRaises(NotFound) as cm:
            ledger.load("demo-missing")
        self.assertIn("no task demo-missing", str(cm.exception))

        # 2. Half-written JSON -> DamagedFileError (subclass of ValueError and StoreError, NOT SystemExit)
        half = self.tasks / "demo-half.json"
        half.write_text('{"id": "demo-half", "status":', encoding="utf-8")
        with self.assertRaises(store_mod.DamagedFileError) as cm_d:
            ledger.load("demo-half")
        self.assertIsInstance(cm_d.exception, ValueError)
        self.assertIsInstance(cm_d.exception, store_mod.StoreError)
        self.assertNotIsInstance(cm_d.exception, SystemExit)
        # Hook `unfailing` catches it cleanly instead of letting SystemExit escape.
        osutil.unfailing(ledger.load, "demo-half")

        # 3. Dangling symlink -> DamagedFileError (NOT falsely "no task")
        if os.name != "nt":
            dangling = self.tasks / "demo-dangling.json"
            dangling.symlink_to(self.root / "does-not-exist.json")
            with self.assertRaises(store_mod.DamagedFileError):
                ledger.load("demo-dangling")

        # 4. Unreadable file -> UnreadableFileError (subclass of OSError and StoreError, NOT SystemExit)
        if os.name != "nt" and os.geteuid() != 0:
            noperm = self.tasks / "demo-noperm-load.json"
            noperm.write_text('{"id": "demo-noperm-load"}\n', encoding="utf-8")
            noperm.chmod(0o000)
            self.addCleanup(lambda: noperm.chmod(0o644) if noperm.exists() else None)
            with self.assertRaises(store_mod.UnreadableFileError) as cm_u:
                ledger.load("demo-noperm-load")
            self.assertIsInstance(cm_u.exception, OSError)
            self.assertIsInstance(cm_u.exception, store_mod.StoreError)
            osutil.unfailing(ledger.load, "demo-noperm-load")

        # 5. Waiting for a report retries transient half-written JSON and a transient PermissionError,
        #    then returns cleanly once the valid report appears.
        repo = init_git_repo(self.base / "wait-repo")
        initial = self.make_task("wait-repo-t1", repo=str(repo), status="in_progress")
        task_path = self.tasks / "wait-repo-t1.json"
        # Start with half-written JSON on the first read, transient PermissionError on the second,
        # then valid review report on the third.
        task_path.write_text('{"id": "wait-repo-t1", "status":', encoding="utf-8")
        step = {"n": 0}

        class SteppingChanges:
            def wait(self, _timeout):
                step["n"] += 1
                if step["n"] == 2:
                    task_path.write_text(json.dumps({
                        **initial,
                        "status": "review",
                        "log": [*initial["log"], {"at": "2026-11-21 10:01", "by": "w", "text": "done!"}],
                    }), encoding="utf-8")
                return True

        class FlakyStore(FileStore):
            """A strict read of the task while the first wait is over: a transient sharing violation."""

            def task(self, task_id, *, strict=False):
                if strict and task_id == "wait-repo-t1" and step["n"] == 1:
                    raise store_mod.UnreadableFileError(13, "transient sharing violation", str(task_path))
                return super().task(task_id, strict=strict)

        self.ctx.store = FlakyStore(self.ctx.home)
        self.ctx.git = StubGit(states={(str(repo), "", "main"): (1, 0)})
        res = wait_for_report_events_for(self.ctx, "wait-repo-t1", SteppingChanges(), initial, timeout=5.0)
        self.assertEqual(step["n"], 2)
        out = "\n".join(res.lines)
        self.assertIn("wait-repo-t1: review", out)
        self.assertIn("done!", out)
        self.assertEqual((res.status, res.ahead, res.dirty), ("review", 1, 0))
        self.assertEqual(res.lines[2], "ahead=1 dirty=0")

    def test_change_registration_matches_legacy_filename_without_splitting_or_crashing_archive(self):
        ctx = self.ctx
        # Project directory was renamed so project_slug(repo) is "new-name", while the existing
        # registration file on disk still has stem "old-name.json".
        repo = init_git_repo(self.base / "new-name")
        legacy_path = self.pms / "old-name.json"
        legacy_rec = {
            "project": "new-name",
            "repo": str(repo),
            "name": "pm-new-name",
            "pane": "hc:t10",
            "workspace": "",
            "runtime": "hc",
            "terminal": "t10",
            "claimed": "2026-11-21 10:00",
        }
        legacy_path.write_text(json.dumps(legacy_rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Read and write must both target `pms/old-name.json`, never creating a duplicate `pms/new-name.json`.
        self.assertEqual(ProjectRegistry(ctx).pm_record(str(repo))["terminal"], "t10")

        updated = ctx.store.change_registration("new-name", lambda cur: {**cur, "space_name": "Renamed"})
        self.assertEqual(updated["space_name"], "Renamed")
        self.assertFalse((self.pms / "new-name.json").exists())
        self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))["space_name"], "Renamed")
        self.assertTrue((self.root / "locks" / "pm-old-name.lock").is_file())

        # Archiving must archive `pms/old-name.json` cleanly and NOT pass None to `end_pm`.
        # The old PM's terminal t10 is live but no longer labelled as this project's PM.
        hc = FakeHc(terminals={"t10": {"state": "live", "turn": 1}}, clock=ctx.clock, config=ctx.config)
        ctx.hc = hc
        archived_res = ManagerSessions(ctx).archive(str(repo))
        out = "\n".join(archived_res.lines)
        self.assertIn("new-name", out)
        self.assertIn("PM hc:t10 is not running", out)
        self.assertFalse((self.pms / "new-name.json").exists())
        archived = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertTrue(archived.get("archived"))
        self.assertIsNone(archived.get("agent_session"))

        # Rotating (hc path) must update `pms/old-name.json` in place without creating a second file.
        archived.pop("archived", None)
        legacy_path.write_text(json.dumps(archived, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        before = set(hc.terminals)
        rotated_res = ManagerSessions(ctx).rotate(str(repo), notes="handover")
        self.assertEqual(rotated_res.mode, "legacy_to_seat")
        made = (set(hc.terminals) - before).pop()             # the new seat terminal FakeHc started
        self.assertFalse((self.pms / "new-name.json").exists())
        rotated = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertEqual(rotated["terminal"], made)
        self.assertNotEqual(made, "t10")
        self.assertTrue(rotated["seat"])
        self.assertEqual(rotated["rotations"], 1)
        # The outgoing terminal ends later, from a background `pm.py end-session` (recorded, never run).
        self.assertEqual([s["args"] for s in ctx.procs.spawned if s["args"][:1] == ["end-session"]],
                         [["end-session", "t10", "--repo", str(repo.resolve()), "--kill-terminal"]])

    # --- task numbers ------------------------------------------------------------------------------------------

    def test_allocate_task_number_monotonic_per_project_multiprocess_and_context_excluded(self):
        init_git_repo(self.base / "alpha")
        init_git_repo(self.base / "beta")
        code = (
            "import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from pmlib.store import FileStore\n"
            "store = FileStore(sys.argv[2])\n"
            "slug = sys.argv[3]\n"
            "nums = [store.allocate_task_number(slug) for _ in range(5)]\n"
            "print(json.dumps(nums))\n"
        )
        outs = self.run_children([(code, (self.root, slug)) for slug in ("alpha", "alpha", "beta", "beta")],
                                 timeout=30)
        got = {"alpha": [], "beta": []}
        for idx, out in enumerate(outs):
            got["alpha" if idx < 2 else "beta"].extend(json.loads(out))

        self.assertEqual(sorted(got["alpha"]), list(range(1, 11)))
        self.assertEqual(sorted(got["beta"]), list(range(1, 11)))
        self.assertEqual(json.loads((self.projects / "alpha" / store_mod.TASK_SEQ_FILE).read_text())["last"], 10)
        self.assertEqual(json.loads((self.projects / "beta" / store_mod.TASK_SEQ_FILE).read_text())["last"], 10)
        self.assertEqual(list((self.projects / "alpha").glob("*.tmp")), [])
        # Next allocation never reuses prior numbers even when no task files exist.
        store = self.ctx.store
        self.assertEqual(store.allocate_task_number("alpha"), 11)
        # task-seq.json is internal metadata, never exposed in project context/library documents.
        self.assertIn(store_mod.TASK_SEQ_FILE, store_mod.INTERNAL_PROJECT_FILES)
        self.assertEqual([d["path"] for d in Projects(store).context("alpha") if d["path"] == store_mod.TASK_SEQ_FILE], [])

    def test_backfill_task_numbers_chronological_idempotent_skips_reviews_and_preserves_updated(self):
        repo = init_git_repo(self.base / "bf-proj")
        self.make_task("bf-a-oldest", repo=str(repo), created="2026-10-01 09:00", updated="2026-11-20 10:00")
        self.make_task("bf-b-log", repo=str(repo), created="", updated="2026-10-15 10:00",
                       log=[{"at": "2026-10-02 09:00", "by": "w", "text": "started"}])
        self.make_task("bf-c-upd", repo=str(repo), created="", updated="2026-10-03 09:00", log=[])
        no_ts = {"id": "bf-d-mtime", "title": "mtime", "project": "bf-proj", "repo": str(repo), "status": "done"}
        (self.tasks / "bf-d-mtime.json").write_text(json.dumps(no_ts), encoding="utf-8")
        os.utime(self.tasks / "bf-d-mtime.json", (1793000000, 1793000000))
        self.make_task("bf-b-log-review", repo=str(repo), review_of="bf-b-log",
                       created="2026-09-01 09:00", updated="2026-10-01 09:00")
        self.make_task("bf-e-existing", repo=str(repo), number=10,
                       created="2026-11-01 09:00", updated="2026-11-01 12:00")

        store = self.ctx.store
        dry = store.backfill_task_numbers("bf-proj", dry_run=True)
        self.assertEqual(dry["total_assigned"], 4)
        self.assertEqual(dry["projects"]["bf-proj"]["already_numbered"], 1)
        self.assertEqual(dry["projects"]["bf-proj"]["skipped_reviews"], 1)
        self.assertEqual(dry["projects"]["bf-proj"]["last"], 14)
        self.assertIsNone(store.task("bf-a-oldest").get("number"))
        self.assertFalse((self.projects / "bf-proj" / store_mod.TASK_SEQ_FILE).exists())

        res = store.backfill_task_numbers("bf-proj", dry_run=False)
        self.assertEqual(res["total_assigned"], 4)
        self.assertEqual(res["projects"]["bf-proj"]["assigned"], [
            {"id": "bf-a-oldest", "number": 11},
            {"id": "bf-b-log", "number": 12},
            {"id": "bf-c-upd", "number": 13},
            {"id": "bf-d-mtime", "number": 14},
        ])
        # `updated` must remain untouched, existing number preserved, review unnumbered.
        self.assertEqual(store.task("bf-a-oldest")["updated"], "2026-11-20 10:00")
        self.assertEqual(store.task("bf-e-existing")["number"], 10)
        self.assertIsNone(store.task("bf-b-log-review").get("number"))
        self.assertEqual(store.allocate_task_number("bf-proj"), 15)

        # Second backfill is idempotent and assigns nothing.
        res2 = store.backfill_task_numbers("bf-proj", dry_run=False)
        self.assertEqual(res2["total_assigned"], 0)
        self.assertEqual(res2["projects"]["bf-proj"]["already_numbered"], 5)
        self.assertEqual(res2["projects"]["bf-proj"]["last"], 15)

    def test_allocate_task_number_backfills_existing_chronologically_under_same_lock_and_races_safely(self):
        repo_a = init_git_repo(self.base / "auto-bf")
        self.make_task("ab-z-oldest", repo=str(repo_a), created="2026-10-01 09:00", updated="2026-11-20 10:00")
        self.make_task("ab-a-newer", repo=str(repo_a), created="2026-10-02 09:00", updated="2026-10-05 09:00")
        self.make_task("ab-z-oldest-review", repo=str(repo_a), review_of="ab-z-oldest",
                       created="2026-09-01 09:00", updated="2026-10-01 09:00")

        store = self.ctx.store
        calls = []

        def before_cb(slug, count):
            # Must run strictly before any existing task file is mutated.
            self.assertIsNone(store.task("ab-z-oldest").get("number"))
            self.assertIsNone(store.task("ab-a-newer").get("number"))
            calls.append((slug, count))

        self.assertEqual(store.allocate_task_number("auto-bf", before_backfill=before_cb), 3)
        self.assertEqual(calls, [("auto-bf", 2)])
        self.assertEqual(store.task("ab-z-oldest")["number"], 1)
        self.assertEqual(store.task("ab-z-oldest")["updated"], "2026-11-20 10:00")
        self.assertEqual(store.task("ab-a-newer")["number"], 2)
        self.assertIsNone(store.task("ab-z-oldest-review").get("number"))
        seq_doc = json.loads((self.projects / "auto-bf" / store_mod.TASK_SEQ_FILE).read_text(encoding="utf-8"))
        self.assertEqual(seq_doc["last"], 3)
        self.assertTrue(seq_doc.get("backfilled_at"))

        # Second allocation must not invoke before_backfill again.
        self.assertEqual(store.allocate_task_number("auto-bf", before_backfill=before_cb), 4)
        self.assertEqual(calls, [("auto-bf", 2)])

        # If before_backfill raises, nothing is mutated and task-seq.json is not created.
        repo_f = init_git_repo(self.base / "fail-bf")
        self.make_task("fb-old", repo=str(repo_f), created="2026-10-01 09:00", updated="2026-10-01 09:00")
        with self.assertRaises(RuntimeError):
            store.allocate_task_number("fail-bf", before_backfill=lambda _s, _c: (_ for _ in ()).throw(RuntimeError("disk full")))
        self.assertIsNone(store.task("fb-old").get("number"))
        self.assertFalse((self.projects / "fail-bf" / store_mod.TASK_SEQ_FILE).exists())

        # Concurrent first allocations race safely under the same seq lock; backfill + callback run once.
        repo_r = init_git_repo(self.base / "race-bf")
        self.make_task("rb-oldest", repo=str(repo_r), created="2026-10-01 09:00", updated="2026-10-10 09:00")
        self.make_task("rb-second", repo=str(repo_r), created="2026-10-02 09:00", updated="2026-10-05 09:00")
        marker = self.base / "race-cb.log"
        code = (
            "import json, pathlib, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from pmlib.store import FileStore\n"
            "store = FileStore(sys.argv[2])\n"
            "marker = pathlib.Path(sys.argv[3])\n"
            "def cb(slug, count):\n"
            "    with open(marker, 'a', encoding='utf-8') as f:\n"
            "        f.write(f'{slug}:{count}\\n')\n"
            "print(json.dumps(store.allocate_task_number('race-bf', before_backfill=cb)))\n"
        )
        allocated = [json.loads(out) for out in self.run_children([(code, (self.root, marker))] * 2, timeout=30)]
        self.assertEqual(sorted(allocated), [3, 4])
        self.assertEqual(store.task("rb-oldest")["number"], 1)
        self.assertEqual(store.task("rb-second")["number"], 2)
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["race-bf:2"])
        self.assertEqual(json.loads((self.projects / "race-bf" / store_mod.TASK_SEQ_FILE).read_text(encoding="utf-8"))["last"], 4)


# ---- without fcntl, as on Windows (moved from test_pm.py WithoutFcntl) ------------------------------------------

# A stand-in for Windows' msvcrt: byte-range locks that fail at once when another process holds them, as
# msvcrt.locking(fd, LK_NBLCK, n) does from the file's position. Built on fcntl, which the scripts never see.
FAKE_MSVCRT = """
import fcntl as _fcntl, os as _os
LK_UNLCK, LK_NBLCK = 0, 2
def locking(fd, mode, n):
    where = _os.lseek(fd, 0, _os.SEEK_CUR)
    # Windows locks a read-only handle too; POSIX takes a read lock on one.
    kind = _fcntl.LOCK_SH if _fcntl.fcntl(fd, _fcntl.F_GETFL) & _os.O_ACCMODE == _os.O_RDONLY else _fcntl.LOCK_EX
    _fcntl.lockf(fd, _fcntl.LOCK_UN if mode == LK_UNLCK else kind | _fcntl.LOCK_NB, n, where)
"""

# A child's InboxWatcher over the Context pm.py's main builds (Context.from_env, after the whole package is imported
# as cli imports it), with fcntl missing: pmlib.store must have fallen back to msvcrt.
WATCHER = ("import pmlib.cli; from pmlib import store; assert store.fcntl is None; "
           "from pmlib.context import Context; from pmlib.events.inbox import InboxWatcher; "
           "watcher = InboxWatcher(Context.from_env()); ")


class WithoutFcntl(unittest.TestCase):
    """pm.py where `import fcntl` fails, as on Windows (os.name stays posix: no UTF-8 re-run, POSIX paths). Each test
    runs child processes over a ledger of its own."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "fake").mkdir()
        (self.root / "fake/msvcrt.py").write_text(FAKE_MSVCRT)
        self.env = dict(os.environ, PM_HOME=str(self.root / "ledger"), HOME=str(self.root))
        for key in ("HERDR_PANE_ID", "HC_TERMINAL_ID"):
            self.env.pop(key, None)
        # subprocess takes msvcrt's presence for Windows: it is imported, the real way, before the stand-in.
        self.prelude = (f"import sys, subprocess; sys.path[:0] = [{str(self.root / 'fake')!r}, {str(SCRIPTS)!r}]; "
                        "import msvcrt; sys.modules['fcntl'] = None; ")

    def python(self, code, **kw):
        return subprocess.Popen([sys.executable, "-c", self.prelude + code], env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)

    def test_state_runs(self):
        script = SCRIPTS / "pm.py"
        proc = self.python(f"import runpy; sys.argv = ['pm.py', 'state']; runpy.run_path({str(script)!r}, run_name='__main__')")
        out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, err)
        state = json.loads(out)
        self.assertEqual((state["pms"], state["tasks"]), ([], []))

    def test_watcher_lock_through_msvcrt(self):
        holder = self.python(WATCHER + "f = watcher.watch_lock('demo'); print('held' if f else 'none', flush=True); "
                             "sys.stdin.read()", stdin=subprocess.PIPE)
        self.addCleanup(lambda: holder.poll() is None and holder.kill())
        self.assertEqual(holder.stdout.readline().strip(), "held")
        ask = WATCHER + "print(watcher.watcher_pid('demo')); print('again' if watcher.watch_lock('demo') is None else 'took')"
        out, err = self.python(ask).communicate(timeout=60)
        self.assertEqual(out.split(), [str(holder.pid), "again"], err)
        holder.communicate("", timeout=60)
        out, err = self.python(ask).communicate(timeout=60)
        self.assertEqual(out.split(), ["None", "took"], err)


if __name__ == "__main__":
    unittest.main()
