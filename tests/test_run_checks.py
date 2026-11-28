"""Unit tests for tests/run_checks.py: render-check trigger & exit-2 gating, sharding, packing, and priority."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import run_checks as rc  # noqa: E402


class RenderCheckTriggerTests(unittest.TestCase):
    def test_needs_render_check_matches_ui_mods_and_render_check_scripts_only(self):
        self.assertFalse(rc.needs_render_check([]))
        self.assertFalse(rc.needs_render_check(["tests/run_checks.py", "docs/README.md"]))
        self.assertFalse(rc.needs_render_check(["mods/pm-dash/skill/scripts/pm.py", "mods/pm-dash/skill/SKILL.md"]))
        self.assertFalse(rc.needs_render_check(["mods/top-level-file.txt"]))

        self.assertTrue(rc.needs_render_check(["mods/pm-project/main.js"]))
        self.assertTrue(rc.needs_render_check(["mods/pm-dash/main.js"]))
        self.assertTrue(rc.needs_render_check(["mods/pm-dash/skill/scripts/pm.py", "mods/pm-list/model.js"]))
        self.assertTrue(rc.needs_render_check(["tests/render_check.py"]))
        self.assertTrue(rc.needs_render_check(["tests/render_check_win.py"]))

    def test_staged_files_reads_real_git_index_and_handles_empty_diff(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
            (repo / "a.txt").write_text("hi\n", encoding="utf-8")
            subprocess.run(["git", "add", "a.txt"], cwd=repo, env=env, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, env=env, check=True)

            # Empty staged diff: must return ([], "") and NEVER trigger render-check (unlike ugrep pitfall).
            paths, err = rc.staged_files(repo)
            self.assertEqual((paths, err), ([], ""))
            self.assertFalse(rc.needs_render_check(paths))

            # Stage a skill-only change: still no render-check.
            skill = repo / "mods/pm-dash/skill/scripts/pm.py"
            skill.parent.mkdir(parents=True)
            skill.write_text("# skill\n", encoding="utf-8")
            subprocess.run(["git", "add", str(skill.relative_to(repo))], cwd=repo, env=env, check=True)
            paths, err = rc.staged_files(repo)
            self.assertEqual(err, "")
            self.assertEqual(paths, ["mods/pm-dash/skill/scripts/pm.py"])
            self.assertFalse(rc.needs_render_check(paths))

            # Stage a UI mod change: triggers render-check.
            ui = repo / "mods/pm-project/main.js"
            ui.parent.mkdir(parents=True)
            ui.write_text("// ui\n", encoding="utf-8")
            subprocess.run(["git", "add", str(ui.relative_to(repo))], cwd=repo, env=env, check=True)
            paths, err = rc.staged_files(repo)
            self.assertEqual(err, "")
            self.assertTrue(rc.needs_render_check(paths))

    def test_staged_files_reports_error_on_non_repo(self):
        with tempfile.TemporaryDirectory() as td:
            paths, err = rc.staged_files(Path(td))
            self.assertIsNone(paths)
            self.assertTrue(err)


class RenderCheckExecutionTests(unittest.TestCase):
    def _run_render_check(self, returncode, output_text):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = rc.Run(jobs=1, keep=False)
            try:
                chk = rc.RenderCheck(root)
                reported = []

                def fake_subproc(argv, cwd, stdout, stderr, stdin):
                    stdout.write(output_text.encode("utf-8"))
                    return mock.Mock(returncode=returncode)

                with mock.patch.object(rc.subprocess, "run", side_effect=fake_subproc):
                    chk.schedule(run, reported.append)
                    run.pool.wait()
                return chk, reported
            finally:
                shutil.rmtree(run.base, ignore_errors=True)
                for extra in run.extra_cleanup:
                    shutil.rmtree(extra, ignore_errors=True)

    def test_exit_0_passes(self):
        chk, reported = self._run_render_check(0, "render-check: working tree\nPASS\n")
        self.assertEqual(len(reported), 1)
        self.assertTrue(chk.ok)
        self.assertEqual(chk.summary, "")

    def test_exit_1_fails_with_report_tail(self):
        chk, _ = self._run_render_check(1, "FAIL pm-project\nFAILED\n")
        self.assertFalse(chk.ok)
        self.assertEqual(chk.summary, "exit 1")
        self.assertIn("FAIL pm-project", chk.detail)

    def test_exit_2_not_judged_blocks_with_explicit_message(self):
        chk, _ = self._run_render_check(2, "BLOCKED the private window draws no frames\nNOT RUN\n")
        self.assertFalse(chk.ok)
        self.assertIn("exit 2", chk.summary)
        self.assertIn(rc.RENDER_NOT_JUDGED_MSG, chk.summary)
        self.assertIn("BLOCKED the private window draws no frames", chk.detail)

    def test_auto_mode_skips_cleanly_and_fails_closed_on_git_error(self):
        out = io.StringIO()
        with mock.patch.object(rc, "staged_files", return_value=(["mods/pm-dash/skill/scripts/pm.py"], "")), \
             contextlib.redirect_stdout(out):
            code = rc.main(["--render-check", "auto", "--only", "render-check"])
        self.assertEqual(code, 0)
        self.assertIn("skip   0.0s  render-check", out.getvalue())

        out2 = io.StringIO()
        with mock.patch.object(rc, "staged_files", return_value=(None, "fatal: not a git repo")), \
             contextlib.redirect_stdout(out2):
            code2 = rc.main(["--render-check", "auto", "--only", "render-check"])
        self.assertEqual(code2, 1)
        self.assertIn("git diff --cached failed", out2.getvalue())

    def test_long_root_path_passes_short_dir_flag_on_posix(self):
        if os.name == "nt":
            self.skipTest("Unix socket path limit is POSIX-only")
        long_root = Path("/tmp/" + "a" * 80)
        run = rc.Run(jobs=1, keep=False)
        try:
            chk = rc.RenderCheck(long_root)
            argv = chk._argv_for(run)
            self.assertIn("--dir", argv)
            rc_dir = Path(argv[argv.index("--dir") + 1])
            self.assertLess(len(str(rc_dir / "app/herdr-app.sock").encode()), rc.RENDER_CHECK_SUN_LEN)
        finally:
            shutil.rmtree(run.base, ignore_errors=True)
            for extra in run.extra_cleanup:
                shutil.rmtree(extra, ignore_errors=True)


class ShardingAndPriorityTests(unittest.TestCase):
    def test_child_list_packs_small_classes_and_splits_slow_classes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 1) Module with 4 tiny classes (2+2+3+2 = 9 <= CHUNK=10) -> packed into 1 shard.
            (root / "test_pack_sample.py").write_text(
                "import unittest\n"
                "class A(unittest.TestCase):\n    def test_1(self): pass\n    def test_2(self): pass\n"
                "class B(unittest.TestCase):\n    def test_1(self): pass\n    def test_2(self): pass\n"
                "class C(unittest.TestCase):\n    def test_1(self): pass\n    def test_2(self): pass\n    def test_3(self): pass\n"
                "class D(unittest.TestCase):\n    def test_1(self): pass\n    def test_2(self): pass\n",
                encoding="utf-8",
            )
            # 2) Slow class with 8 tests and chunk limit 2 -> 4 shards of 2 with high priority.
            methods = "\n".join(f"    def test_{i}(self): pass" for i in range(8))
            (root / "test_slow_sample.py").write_text(
                f"import unittest\nclass Heavy(unittest.TestCase):\n{methods}\n",
                encoding="utf-8",
            )
            spec = {"kind": "discover", "start": str(root), "pattern": "test_*.py"}
            sys.path.insert(0, str(root))
            try:
                with mock.patch.dict(rc.SHARD_CHUNKS, {"test_slow_sample.Heavy": 2}):
                    listed = rc.child_list(spec)
            finally:
                sys.path.remove(str(root))
                for m in ("test_pack_sample", "test_slow_sample"):
                    sys.modules.pop(m, None)

            self.assertEqual(listed["errors"], [])
            self.assertEqual(listed["total"], 17)
            pack_shards = [s for s in listed["shards"] if s[0][0].startswith("test_pack_sample.")]
            slow_shards = [s for s in listed["shards"] if s[0][0].startswith("test_slow_sample.")]
            self.assertEqual(len(pack_shards), 1)
            self.assertEqual(pack_shards[0][1], 9)
            self.assertEqual(len(slow_shards), 4)
            self.assertTrue(all(s[1] == 2 for s in slow_shards))
            # LPT priority: slow shards strictly outrank packed fast shards.
            self.assertGreater(slow_shards[0][3], pack_shards[0][3])

    def test_priority_orders_replay_over_slow_over_normal_over_serial(self):
        p_replay = rc.shard_priority("test_replay", "ReplayTest", 1, False)
        p_lib = rc.shard_priority("test_views", "LibraryAndMemoryTests", 2, False)
        p_install = rc.shard_priority("test_install", "InstallTest", 3, False)
        p_normal = rc.shard_priority("test_policy", "PolicyTest", 10, False)
        p_serial = rc.shard_priority("test_policy", "PolicyTest", 10, True)
        self.assertGreater(p_replay, p_lib)
        self.assertGreater(p_lib, p_install)
        self.assertGreater(p_install, p_normal)
        self.assertGreater(p_normal, p_serial)
        self.assertEqual(p_serial, -1)


    def test_default_jobs_caps_macos_p_cores_and_falls_back_cleanly(self):
        with mock.patch.object(rc.sys, "platform", "darwin"), \
             mock.patch.object(rc.os, "cpu_count", return_value=28), \
             mock.patch.object(rc.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="20\n")):
            self.assertEqual(rc.default_jobs(), 14)
        with mock.patch.object(rc.sys, "platform", "darwin"), \
             mock.patch.object(rc.os, "cpu_count", return_value=14), \
             mock.patch.object(rc.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="10\n")):
            self.assertEqual(rc.default_jobs(), 10)
        with mock.patch.object(rc.sys, "platform", "linux"), \
             mock.patch.object(rc.os, "cpu_count", return_value=16):
            self.assertEqual(rc.default_jobs(), 16)


if __name__ == "__main__":
    unittest.main()
