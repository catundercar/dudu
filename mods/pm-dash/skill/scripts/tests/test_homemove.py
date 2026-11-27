"""Ledger home resolution and `pm.py home --migrate` (~/.claude/pm -> ~/.dudu), moved from test_pm_home.py (Stage 6a).

In-process checks build their own `Context` with `make_ctx` (FakeHc for live terminals, env mapping for PM_HOME,
an explicit `Home` for the migrated ledger) and call `pmlib.context.default_home`, `pmlib.homemove.HomeMover` and
`pmlib.manager.launch.lean_pm` directly: no `pm.*` patches. The migration itself runs end to end through the real
`pm.py` CLI in a child process, under a temporary HOME with a standalone fake `hc` on PATH, so no test reads or
writes the real ~/.claude/pm, ~/.dudu or herdr-core.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fakes import FakeHc, make_ctx  # noqa: E402
from pmlib import context  # noqa: E402
from pmlib.home import Home  # noqa: E402
from pmlib.homemove import HomeMover  # noqa: E402
from pmlib.manager.launch import lean_pm  # noqa: E402

PM_SCRIPT = SCRIPTS / "pm.py"


def write_fake_hc(bin_dir: Path, terminals: list | None = None) -> Path:
    """Write a standalone fake `hc` script in `bin_dir` that answers `hc ls --json` without touching real herdr-core."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    hc_path = bin_dir / "hc"
    payload = json.dumps({"terminals": terminals or []})
    hc_path.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"print({payload!r})\n",
        encoding="utf-8",
    )
    hc_path.chmod(0o755)
    if os.name == "nt":
        (bin_dir / "hc.cmd").write_text(f'@echo off\r\n"{sys.executable}" "%~dp0hc" %*\r\n', encoding="utf-8")
    return hc_path


class HomeMoveTest(unittest.TestCase):
    def setUp(self) -> None:
        td_kw = {"ignore_cleanup_errors": True} if os.name == "nt" and sys.version_info >= (3, 10) else {}
        self.tmp = tempfile.TemporaryDirectory(prefix="pm-homemove-", **td_kw)
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.fake_bin = Path(self.tmp.name) / "bin"
        write_fake_hc(self.fake_bin, terminals=[])
        self.source = self.home / ".claude" / "pm"
        self.target = self.home / ".dudu"
        # Named "demo" so its project slug is the seeded project's ("demo"), with no project_slug patch.
        self.repo = Path(self.tmp.name) / "demo"
        self.repo.mkdir()
        self.procs: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            for stream in (proc.stdout, proc.stderr, proc.stdin):
                if stream is not None:
                    stream.close()

    # --- helpers -----------------------------------------------------------------------------------------------

    def ctx_for(self, *, hc: FakeHc | None = None, pm_home: str = ""):
        """A Context of this test's own (its ledger under tmp/ctx), with PM_HOME as given ("" = not set)."""
        return make_ctx(Path(self.tmp.name) / "ctx", hc=hc, env={"PM_HOME": pm_home})

    def child_env(self, **extra: str) -> dict[str, str]:
        base_path = os.environ.get("PATH", "/usr/bin:/bin")
        env = {
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "PATH": f"{self.fake_bin}{os.pathsep}{base_path}",
            "LANG": "en_US.UTF-8",
        }
        for key in ("SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP"):
            if key in os.environ:
                env[key] = os.environ[key]
        env.update(extra)
        return env

    def run_pm(self, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(PM_SCRIPT), *args],
            env=self.child_env(**(env_extra or {})),
            cwd=str(self.home),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def seed_legacy_ledger(self) -> None:
        """Populate a realistic legacy ledger under self.source (~/.claude/pm)."""
        for rel in ("tasks", "pms", "projects/demo/memory", "memory", "reads", "locks", "inbox", "waits"):
            (self.source / rel).mkdir(parents=True, exist_ok=True)
        (self.source / "config.json").write_text(json.dumps({"lang": "en"}) + "\n", encoding="utf-8")
        (self.source / "BOARD.md").write_text(
            f"# PM Board\n\nUpdated 2026-11-21 10:00. Ledger: `{self.source / 'tasks'}`.\n",
            encoding="utf-8",
        )
        (self.source / "pms" / "demo.json").write_text(
            json.dumps({
                "project": "demo",
                "repo": str(self.repo),
                "name": "pm-demo",
                "pane": "hc:t900",
                "runtime": "hc",
                "terminal": "t900",
                "agent": "claude",
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.source / "tasks" / "demo-1.json").write_text(
            json.dumps({
                "id": "demo-1",
                "title": "Sample open task",
                "project": "demo",
                "repo": str(self.repo),
                "status": "in_progress",
                "owner": "worker-1",
                "pane": "hc:t901",
                "agent": "codex",
                "base": "main",
                "branch": "",
                "worktree": "",
                "created": "2026-11-21 09:00",
                "updated": "2026-11-21 09:30",
                "log": [{"at": "2026-11-21 09:00", "by": "pm", "text": "started"}],
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.source / "memory" / "pref.md").write_text("---\nname: pref\ntype: user\n---\nKeep it clean.\n", encoding="utf-8")
        (self.source / "projects" / "demo" / "memory" / "rule.md").write_text(
            "---\nname: rule\ntype: project\n---\nProject rule.\n", encoding="utf-8"
        )
        (self.source / "projects" / "demo" / "conversation.jsonl").write_text(
            json.dumps({"at": "2026-11-21 09:00", "type": "user", "text": "hello"}) + "\n", encoding="utf-8"
        )
        (self.source / "projects" / "demo" / "pm-settings.json").write_text(
            json.dumps({
                "enabledPlugins": {},
                "autoMemoryEnabled": True,
                "autoMemoryDirectory": str(self.source / "projects" / "demo" / "memory"),
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.source / "reads" / "abc123def456.json").write_text(
            json.dumps({
                "autoMemoryEnabled": True,
                "autoMemoryDirectory": str(self.source / "projects" / "demo" / "memory" / "candidates" / "w1"),
            }, indent=1) + "\n",
            encoding="utf-8",
        )

    def seed_legacy_service_target(self) -> None:
        """Populate self.target (~/.dudu) with old standalone dudu service residue (non-ledger)."""
        for rel in ("agents", "bin", "hc"):
            (self.target / rel).mkdir(parents=True, exist_ok=True)
        (self.target / "dudu.db").write_bytes(b"SQLite format 3\x00dummy")
        (self.target / "dudu.db-shm").write_bytes(b"shm")
        (self.target / "dudu.db-wal").write_bytes(b"wal")
        (self.target / "service.lock").write_text("", encoding="utf-8")
        (self.target / "agents" / "old.txt").write_text("legacy agent", encoding="utf-8")
        # Create a real Unix domain socket on POSIX (short path check in case tmpdir is long).
        sock_path = self.target / "d.sock"
        if hasattr(socket, "AF_UNIX") and len(str(sock_path).encode("utf-8")) < 100:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.bind(str(sock_path))
            finally:
                s.close()

    def hold_flock(self, lock_path: Path) -> subprocess.Popen:
        """Start a child process holding an exclusive lock on `lock_path` until tearDown."""
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [
                sys.executable, "-c",
                "import os, sys, time\n"
                f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
                "from pmlib.store import lock_file\n"
                "f = open(sys.argv[1], 'a+')\n"
                "lock_file(f)\n"
                "f.seek(0); f.truncate(0); f.write(str(os.getpid())); f.flush()\n"
                "print('LOCKED', flush=True)\n"
                "time.sleep(30)\n",
                str(lock_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.procs.append(proc)
        line = proc.stdout.readline().strip()
        self.assertEqual(line, "LOCKED", proc.stderr.read() if line != "LOCKED" else "")
        return proc

    def hold_sleeper(self) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.procs.append(proc)
        return proc

    def tree_snapshot(self, root: Path) -> dict:
        snap = {}
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            filenames.sort()
            dp = Path(dirpath)
            for name in list(dirnames) + list(filenames):
                full = dp / name
                rel = str(full.relative_to(root))
                if full.is_symlink():
                    snap[rel] = ("symlink", os.readlink(full))
                elif full.is_dir():
                    snap[rel] = ("dir", None)
                elif full.is_file():
                    snap[rel] = ("file", full.read_bytes())
                else:
                    snap[rel] = ("special", None)
        return snap

    # --- tests -------------------------------------------------------------------------------------------------

    def test_default_home_resolution_rules(self):
        # The environment is passed in (no os.environ edits); Path.home() has no port, so it is patched.
        def resolved(env: dict[str, str]) -> Path:
            found = context.default_home(env=env)
            self.assertEqual(Home.from_env(env=env).root, found)  # the Home a Context is built on agrees
            return found

        with mock.patch.object(Path, "home", return_value=self.home):
            # Fresh install: ~/.dudu
            self.assertEqual(resolved({}), self.target)
            # Legacy directory at ~/.claude/pm: ~/.claude/pm
            self.source.mkdir(parents=True)
            self.assertEqual(resolved({}), self.source)
            # Explicit PM_HOME always wins
            self.assertEqual(resolved({"PM_HOME": str(self.home / "custom")}), self.home / "custom")
            # Migrated symlink ~/.claude/pm -> ~/.dudu: canonical ~/.dudu wins
            self.source.rmdir()
            self.target.mkdir(parents=True)
            os.symlink(str(self.target), str(self.source), target_is_directory=True)
            self.assertEqual(resolved({}), self.target)
            # Custom symlink ~/.claude/pm -> /elsewhere: keeps ~/.claude/pm
            self.source.unlink()
            elsewhere = self.home / "elsewhere"
            elsewhere.mkdir()
            os.symlink(str(elsewhere), str(self.source), target_is_directory=True)
            self.assertEqual(resolved({}), self.source)
            # Dangling symlink ~/.claude/pm -> missing: falls back to ~/.dudu
            self.source.unlink()
            os.symlink(str(self.home / "missing"), str(self.source), target_is_directory=True)
            self.assertEqual(resolved({}), self.target)

    def test_home_inspect_and_dry_run_write_nothing(self):
        self.seed_legacy_ledger()
        self.seed_legacy_service_target()

        # In process: HomeMover over a Context of its own sees the same as the CLI below.
        mine = HomeMover(self.ctx_for()).inspect(self.home)
        self.assertEqual(mine["status"], "legacy")
        self.assertEqual(mine["home"], str(self.source))
        self.assertEqual(mine["target_kind"], "legacy_service_dir")
        self.assertIn("dudu.db", mine["target_service_markers"])

        res = self.run_pm("home", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        info = json.loads(res.stdout)
        self.assertEqual(info["status"], "legacy")
        self.assertEqual(info["home"], str(self.source))
        self.assertEqual(info["target_kind"], "legacy_service_dir")
        self.assertIn("dudu.db", info["target_service_markers"])

        before = self.tree_snapshot(self.home)
        dry = self.run_pm("home", "--migrate", "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn("Dry run: migrate ledger", dry.stdout)
        self.assertIn("pm-backups", dry.stdout)
        self.assertIn(".dudu-legacy-service-", dry.stdout)
        self.assertIn("Compatibility symlink", dry.stdout.replace("compatibility symlink", "Compatibility symlink"))
        self.assertIn("no files changed", dry.stdout)
        # Dry run must not create or modify a single byte anywhere under HOME.
        self.assertEqual(self.tree_snapshot(self.home), before)

    def test_migrate_with_legacy_service_backup_symlink_and_dual_version_access(self):
        self.seed_legacy_ledger()
        self.seed_legacy_service_target()

        res = self.run_pm("home", "--migrate")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("Migrated ledger:", res.stdout)
        self.assertIn("Backup archive:", res.stdout)
        self.assertIn("Moved previous", res.stdout)
        self.assertIn("Compatibility symlink:", res.stdout)
        self.assertIn("Sessions to restart:", res.stdout)
        self.assertIn("pm-demo", res.stdout)
        self.assertIn("demo-1", res.stdout)

        # 1. Verified tarball exists in ~/.claude/pm-backups with original ledger contents.
        backups = sorted((self.home / ".claude" / "pm-backups").glob("pm-*-before-migrate.tgz"))
        self.assertEqual(len(backups), 1)
        with tarfile.open(backups[0], "r:gz") as tf:
            names = set(tf.getnames())
            self.assertIn("pm/tasks/demo-1.json", names)
            self.assertIn("pm/pms/demo.json", names)
            self.assertIn("pm/memory/pref.md", names)
            self.assertIn("pm/projects/demo/memory/rule.md", names)

        # 2. Legacy service files relocated intact (not deleted).
        day = datetime.datetime.now().strftime("%Y%m%d")
        relocated = self.home / f".dudu-legacy-service-{day}"
        self.assertTrue(relocated.is_dir())
        self.assertEqual((relocated / "dudu.db").read_bytes(), b"SQLite format 3\x00dummy")
        self.assertEqual((relocated / "agents" / "old.txt").read_text(), "legacy agent")

        # 3. Target ~/.dudu is a real directory with full ledger; ~/.claude/pm symlinks to it.
        self.assertTrue(self.target.is_dir() and not self.target.is_symlink())
        self.assertTrue(self.source.is_symlink())
        self.assertTrue(self.source.samefile(self.target))

        # 4. Generated autoMemoryDirectory settings and BOARD.md updated to ~/.dudu.
        pm_settings = json.loads((self.target / "projects" / "demo" / "pm-settings.json").read_text())
        self.assertEqual(pm_settings["autoMemoryDirectory"], str(self.target / "projects" / "demo" / "memory"))
        read_settings = json.loads((self.target / "reads" / "abc123def456.json").read_text())
        self.assertEqual(
            read_settings["autoMemoryDirectory"],
            str(self.target / "projects" / "demo" / "memory" / "candidates" / "w1"),
        )
        self.assertIn(f"`{self.target / 'tasks'}`", (self.target / "BOARD.md").read_text())

        # In process: after the move, HomeMover reports "migrated" and the ledger home is canonical ~/.dudu.
        after = HomeMover(self.ctx_for()).inspect(self.home)
        self.assertEqual((after["status"], after["home"]), ("migrated", str(self.target)))

        # 5. New pm.py resolves canonical ~/.dudu.
        state_new = self.run_pm("state")
        self.assertEqual(state_new.returncode, 0, state_new.stderr)
        parsed_new = json.loads(state_new.stdout)
        self.assertEqual(parsed_new["home"], str(self.target))
        self.assertEqual([t["id"] for t in parsed_new["tasks"]], ["demo-1"])

        # 6. Old pm.py behavior (pointing at ~/.claude/pm through the symlink) reads & writes the exact same ledger!
        state_old = self.run_pm("state", env_extra={"PM_HOME": str(self.source)})
        self.assertEqual(state_old.returncode, 0, state_old.stderr)
        parsed_old = json.loads(state_old.stdout)
        self.assertEqual(parsed_old["home"], str(self.source))
        self.assertEqual([t["id"] for t in parsed_old["tasks"]], ["demo-1"])

        upd_old = self.run_pm("update", "demo-1", "--note", "from-old-pm", env_extra={"PM_HOME": str(self.source)})
        self.assertEqual(upd_old.returncode, 0, upd_old.stderr)
        show_new = self.run_pm("show", "demo-1", "--json")
        self.assertEqual(show_new.returncode, 0, show_new.stderr)
        self.assertIn("from-old-pm", show_new.stdout)

        # 7. Idempotency: re-running migrate is a no-op and makes no second backup.
        again = self.run_pm("home", "--migrate")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("Already migrated", again.stdout)
        self.assertEqual(len(list((self.home / ".claude" / "pm-backups").glob("pm-*-before-migrate.tgz"))), 1)

    def test_migrate_relocation_avoids_name_collision(self):
        self.seed_legacy_ledger()
        self.seed_legacy_service_target()
        day = datetime.datetime.now().strftime("%Y%m%d")
        preexisting = self.home / f".dudu-legacy-service-{day}"
        preexisting.mkdir()
        (preexisting / "keep.txt").write_text("earlier backup")

        res = self.run_pm("home", "--migrate", "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        out = json.loads(res.stdout)
        self.assertEqual(out["relocated_target"], str(self.home / f".dudu-legacy-service-{day}-2"))
        self.assertEqual((preexisting / "keep.txt").read_text(), "earlier backup")
        self.assertTrue((Path(out["relocated_target"]) / "dudu.db").is_file())

    def test_refuses_when_target_already_contains_ledger(self):
        self.seed_legacy_ledger()
        (self.target / "tasks").mkdir(parents=True)
        (self.target / "tasks" / "other-1.json").write_text("{}\n")

        self.assertEqual(HomeMover(self.ctx_for()).inspect(self.home)["status"], "conflict")

        res = self.run_pm("home", "--migrate")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Auto-merge is refused", res.stderr)
        self.assertTrue(self.source.is_dir() and not self.source.is_symlink())
        self.assertTrue((self.target / "tasks" / "other-1.json").is_file())
        self.assertFalse((self.home / ".claude" / "pm-backups").exists())

    def test_refuses_when_pm_home_env_is_set(self):
        self.seed_legacy_ledger()
        # In process: PM_HOME from the Context's env is the effective home and is reported as such.
        info = HomeMover(self.ctx_for(pm_home=str(self.source))).inspect(self.home)
        self.assertEqual((info["home"], info["pm_home_env"]), (str(self.source), str(self.source)))

        res = self.run_pm("home", "--migrate", env_extra={"PM_HOME": str(self.source)})
        self.assertEqual(res.returncode, 2)
        self.assertIn("unset PM_HOME", res.stderr)
        self.assertTrue(self.source.is_dir() and not self.source.is_symlink())

    def test_refuses_when_backup_dir_inside_ledger(self):
        self.seed_legacy_ledger()
        res = self.run_pm("home", "--migrate", "--backup-dir", str(self.source / "bak"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("must be outside", res.stderr)

    def test_custom_backup_dir(self):
        self.seed_legacy_ledger()
        ext_bak = Path(self.tmp.name) / "external-backups"
        res = self.run_pm("home", "--migrate", "--backup-dir", str(ext_bak), "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        out = json.loads(res.stdout)
        self.assertTrue(Path(out["backup"]["path"]).is_file())
        self.assertEqual(Path(out["backup"]["path"]).parent, ext_bak.resolve())

    def test_refuses_on_active_locks_and_processes(self):
        cases = [
            ("deliver", lambda: self.hold_flock(self.source / "projects" / "demo" / "deliver.lock"), "deliver (demo)"),
            ("seat", lambda: self.hold_flock(self.source / "projects" / "demo" / "seat.lock"), "seat (demo)"),
            ("watch", lambda: self.hold_flock(self.source / "inbox" / "pm-demo.watch.lock"), "watch (pm-demo"),
            ("ledger_lock", lambda: self.hold_flock(self.source / "locks" / "task-demo-1.lock"), "ledger lock (task-demo-1)"),
            ("service_lock", lambda: (self.seed_legacy_service_target(), self.hold_flock(self.target / "service.lock"))[1],
             "legacy dudu service"),
        ]
        for label, setup_fn, expected in cases:
            with self.subTest(blocker=label):
                # Fresh home per subtest
                sub_tmp = tempfile.TemporaryDirectory(prefix="pm-homemove-sub-")
                self.addCleanup(sub_tmp.cleanup)
                orig_home, orig_source, orig_target = self.home, self.source, self.target
                self.home = Path(sub_tmp.name) / "home"
                self.home.mkdir()
                self.source = self.home / ".claude" / "pm"
                self.target = self.home / ".dudu"
                try:
                    self.seed_legacy_ledger()
                    proc = setup_fn()
                    try:
                        # In process: HomeMover over a Context of its own names the same blocker.
                        found = HomeMover(self.ctx_for(hc=FakeHc())).active_writers(self.source, self.target)
                        self.assertTrue(any(expected in b["detail"] for b in found), found)
                        # Dry-run shows plan + blocker and exits 2 without writing.
                        dry = self.run_pm("home", "--migrate", "--dry-run")
                        self.assertEqual(dry.returncode, 2, dry.stdout + dry.stderr)
                        self.assertIn(expected, dry.stdout)
                        # Real migrate refuses and makes no backup or move.
                        res = self.run_pm("home", "--migrate")
                        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
                        self.assertIn(expected, res.stderr)
                        self.assertTrue(self.source.is_dir() and not self.source.is_symlink())
                        self.assertFalse((self.home / ".claude" / "pm-backups").exists())
                    finally:
                        proc.terminate()
                        proc.wait(timeout=5)
                finally:
                    self.home, self.source, self.target = orig_home, orig_source, orig_target

    def test_refuses_on_live_wait_and_reattach_pids(self):
        self.seed_legacy_ledger()
        sleeper = self.hold_sleeper()
        (self.source / "waits" / "demo-1.json").write_text(
            json.dumps({"task": "demo-1", "by": "hc:t900", "pid": sleeper.pid, "since": "2026-11-21 10:00"}) + "\n"
        )
        found = HomeMover(self.ctx_for(hc=FakeHc())).active_writers(self.source)
        self.assertIn(f"wait (demo-1, pid {sleeper.pid})", [b["detail"] for b in found])
        res = self.run_pm("home", "--migrate")
        self.assertEqual(res.returncode, 2)
        self.assertIn("wait (demo-1", res.stderr)
        (self.source / "waits" / "demo-1.json").unlink()

        (self.source / "reattach").mkdir(parents=True, exist_ok=True)
        (self.source / "reattach" / "demo-1.lock").write_text(f"{sleeper.pid} 9999999999\n")
        found = HomeMover(self.ctx_for(hc=FakeHc())).active_writers(self.source)
        self.assertIn("reattach (demo-1)", [b["detail"] for b in found])
        res2 = self.run_pm("home", "--migrate")
        self.assertEqual(res2.returncode, 2)
        self.assertIn("reattach (demo-1)", res2.stderr)

    def test_refuses_on_live_pm_or_worker_terminal_in_hc(self):
        self.seed_legacy_ledger()
        live = [
            {"address": "t900", "state": "live", "labels": {"pm": "demo"}},
            {"address": "t901", "state": "live", "labels": {"task": "demo-1"}},
        ]
        # In process: the live terminals come from FakeHc injected into this test's Context.
        hc = FakeHc(terminals={row["address"]: row for row in live})
        details = [b["detail"] for b in HomeMover(self.ctx_for(hc=hc)).active_writers(self.source)]
        self.assertEqual(details, ["live PM terminal pm-demo (hc:t900)", "live worker terminal demo-1 (hc:t901)"])
        # Nothing live in hc: no terminal blocker.
        self.assertEqual(HomeMover(self.ctx_for(hc=FakeHc())).active_writers(self.source), [])

        # Under real hc ls contract (strict_ls=True, no `labels` on ls rows), active_writers still detects
        # PM, worker, and helper terminals (both via hc get labels and ledger helper records).
        strict_live = {
            "t900": {"address": "t900", "state": "live", "labels": {"pm": "demo"}},
            "t901": {"address": "t901", "state": "live", "labels": {"task": "demo-1"}},
            "t902": {"address": "t902", "state": "live", "labels": {"helper": "scout", "helper.of": "pm-demo"}},
        }
        strict_hc = FakeHc(terminals=strict_live, strict_ls=True)
        strict_details = [b["detail"] for b in HomeMover(self.ctx_for(hc=strict_hc)).active_writers(self.source)]
        self.assertEqual(strict_details, [
            "live PM terminal pm-demo (hc:t900)",
            "live worker terminal demo-1 (hc:t901)",
            "live helper terminal scout (hc:t902)",
        ])

        # End to end: the real CLI, with a standalone fake `hc` on PATH answering `hc ls`.
        write_fake_hc(self.fake_bin, terminals=live)
        res = self.run_pm("home", "--migrate")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("live PM terminal pm-demo (hc:t900)", res.stderr)
        self.assertIn("live worker terminal demo-1 (hc:t901)", res.stderr)
        self.assertTrue(self.source.is_dir() and not self.source.is_symlink())

    def test_lean_pm_recognizes_pre_migration_settings_via_symlink(self):
        self.seed_legacy_ledger()
        self.assertEqual(self.run_pm("home", "--migrate").returncode, 0)
        old_settings = str(self.source / "projects" / "demo" / "pm-settings.json")
        new_settings = str(self.target / "projects" / "demo" / "pm-settings.json")
        # A Context of its own whose ledger home is the migrated ~/.dudu (was: pm.STATE/PROJECTS patched); its
        # config.json is empty and its Claude folder (claude_dir) is the test's own empty one (was: pm.config and
        # pm.lean_settings patched); the repo folder is named "demo" (was: pm.project_slug patched).
        ctx = self.ctx_for()
        ctx.home = Home(self.target)
        argv = ["claude", "--strict-mcp-config", "--no-chrome", "--settings", old_settings, "--", "hello"]
        out = lean_pm("claude", argv, repo=str(self.repo), ctx=ctx)
        self.assertEqual(out.count("--settings"), 1)
        idx = out.index("--settings")
        self.assertEqual(out[idx + 1], new_settings)
        self.assertEqual(out[-2:], ["--", "hello"])
        # Written where the migrated ledger keeps it, reachable through the compatibility symlink too.
        self.assertTrue(Path(new_settings).is_file())
        self.assertTrue(Path(old_settings).samefile(new_settings))


if __name__ == "__main__":
    unittest.main()
