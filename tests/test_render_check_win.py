import base64
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

import render_check as rc
import render_check_win as rcw


def _make_png(width, height):
    """Build a minimal valid PNG header (signature + IHDR) for dimension testing."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return sig + ihdr


class RenderCheckWindowsUnitTests(unittest.TestCase):
    def test_standin_command_branches_by_platform(self):
        with mock.patch.object(rc.sys, "platform", "darwin"):
            self.assertEqual(rc.standin_command(), ["cat"])
        with mock.patch.object(rc.sys, "platform", "win32"):
            cmd = rc.standin_command()
            self.assertEqual(cmd[0], sys.executable)
            self.assertEqual(cmd[1], "-c")
            self.assertIn("time.sleep", cmd[2])

    def test_win_window_schema(self):
        w = rc.win_window()
        self.assertEqual(w["state"], "windowed")
        self.assertEqual(w["bounds"], [80.0, 60.0, 1280.0, 820.0])
        w["bounds"][0] = 0.0
        self.assertEqual(rc.win_window()["bounds"][0], 80.0)

    def test_png_size_reads_ihdr_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ok.png"
            p.write_bytes(_make_png(1280, 820))
            self.assertEqual(rc.png_size(p), (1280, 820))

            bad = Path(td) / "bad.png"
            bad.write_bytes(b"not a png at all")
            self.assertIsNone(rc.png_size(bad))
            self.assertIsNone(rc.png_size(Path(td) / "missing.png"))

    def test_build_win_launcher_script_compiles_and_escapes_paths(self):
        script = rc.build_win_launcher_script(
            r"C:\Program Files\Herdr\herdr-app.exe",
            r"C:\Users\alice\AppData\Local\Temp\dudu-rc\app.log",
            r"C:\Users\alice\AppData\Local\Temp\dudu-rc\app.pid",
            {"HERDR_APP_HOME": r"C:\Temp\app", "HC_SESSION": "rc123", "RUST_LOG": "info"},
        )
        compile(script, "launch_win.py", "exec")
        self.assertIn(r"C:\\Program Files\\Herdr\\herdr-app.exe", script)
        self.assertIn("HERDR_APP_HOME", script)
        self.assertIn("PID_PATH", script)
        self.assertIn("CREATE_NEW_PROCESS_GROUP", script)

    def test_person_homes_includes_appdata_when_set(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"APPDATA": td}, clear=False):
                homes = rc.person_homes()
                self.assertIn((Path(td) / "herdr-app").resolve(), homes)

    def test_prepare_skips_sun_len_on_windows_and_rejects_linux(self):
        with tempfile.TemporaryDirectory() as td:
            long_dir = Path(td) / ("a" * 110)
            args = types.SimpleNamespace(
                dir=str(long_dir), rev=None, ledger=None, pm=None, thread=None,
                keep=False, verify_window_controls=False,
            )
            chk = rc.Check(args)
            with mock.patch.object(rc.shutil, "which", return_value="/fake/bin"), \
                 mock.patch.object(rc.sys, "platform", "linux"):
                with self.assertRaises(rc.Blocked) as ctx:
                    chk.prepare()
                self.assertIn("macOS and Windows", str(ctx.exception))

            # On Windows, SUN_LEN is not enforced (it fails later only on missing ledger).
            with mock.patch.object(rc.shutil, "which", return_value="/fake/bin"), \
                 mock.patch.object(rc.sys, "platform", "win32"), \
                 mock.patch.object(rc, "copy_plain"), \
                 mock.patch.object(rc, "ledger_source", return_value=Path(td) / "no-ledger"):
                with self.assertRaises(rc.Blocked) as ctx:
                    chk.prepare()
                self.assertIn("no ledger", str(ctx.exception))

    def test_verify_window_controls_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as td:
            args = types.SimpleNamespace(
                dir=td, rev=None, ledger=None, pm=None, thread=None,
                keep=False, verify_window_controls=True,
            )
            chk = rc.Check(args)
            chk.shots.mkdir(parents=True)
            chk.log.write_text("", encoding="utf-8")

            sizes = [(1280, 820), (1920, 1040), (1280, 820)]

            def fake_shoot(path, timeout=30):
                w, h = sizes.pop(0)
                Path(path).write_bytes(_make_png(w, h))
                return ""

            with mock.patch.object(chk, "poke"), \
                 mock.patch.object(chk, "do", return_value=""), \
                 mock.patch.object(chk, "shoot", side_effect=fake_shoot), \
                 mock.patch.object(rc, "nap"):
                res = chk.verify_window_controls()
            self.assertFalse(res["stalled"])
            self.assertEqual(res["problems"], [])
            self.assertEqual(res["state"]["before"], [1280, 820])
            self.assertEqual(res["state"]["maximized"], [1920, 1040])
            self.assertEqual(res["state"]["restored"], [1280, 820])
            self.assertTrue((chk.shots / "maximized.png").is_file())

            # Now test failure when maximize does not grow the window.
            sizes_fail = [(1280, 820), (1280, 820), (1280, 820)]

            def fake_shoot_fail(path, timeout=30):
                w, h = sizes_fail.pop(0)
                Path(path).write_bytes(_make_png(w, h))
                return ""

            with mock.patch.object(chk, "poke"), \
                 mock.patch.object(chk, "do", return_value=""), \
                 mock.patch.object(chk, "shoot", side_effect=fake_shoot_fail), \
                 mock.patch.object(rc, "nap"):
                res_fail = chk.verify_window_controls()
            self.assertFalse(res_fail["stalled"])
            self.assertTrue(any("did not grow" in p for p in res_fail["problems"]))

    def test_close_windows_cleans_task_and_kills_stuck_pid(self):
        with tempfile.TemporaryDirectory() as td:
            args = types.SimpleNamespace(
                dir=td, rev=None, ledger=None, pm=None, thread=None,
                keep=False, verify_window_controls=False,
            )
            chk = rc.Check(args)
            chk.app.mkdir(parents=True)
            chk.launched = True
            chk.pid = 42424
            chk.win_task_name = "DuduRC_999"
            run_calls = []

            def fake_run(cmd, **kwargs):
                run_calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(rc.sys, "platform", "win32"), \
                 mock.patch.object(chk, "herdr", return_value=subprocess.CompletedProcess([], 0, '{"ok":true}', "")) as m_herdr, \
                 mock.patch.object(chk, "alive", return_value=True), \
                 mock.patch.object(rc, "nap"), \
                 mock.patch.object(rc.time, "time", side_effect=[0, 11, 12]), \
                 mock.patch.object(rc.subprocess, "run", side_effect=fake_run):
                notes = chk.close()

            m_herdr.assert_called_once_with("do", "app.quit", timeout=10)
            self.assertIn(["taskkill", "/PID", "42424", "/T", "/F"], run_calls)
            self.assertIn(["schtasks", "/Delete", "/TN", "DuduRC_999", "/F"], run_calls)
            self.assertTrue(any("taskkill" in n for n in notes))

    def test_tidy_strips_windows_and_posix_paths(self):
        with tempfile.TemporaryDirectory() as td:
            args = types.SimpleNamespace(
                dir=td, rev=None, ledger=None, pm=None, thread=None,
                keep=False, verify_window_controls=False,
            )
            chk = rc.Check(args)
            raw = f"Error at {chk.app}\\mods\\pm-project\\main.real.js?v=2:10:5\n  at render ({chk.app}\\mods\\pm-project\\main.js:90:12)"
            tidied = chk.tidy(raw)
            self.assertIn("mods\\pm-project\\main.js:10:5", tidied)
            self.assertNotIn("main.real.js", tidied)
            self.assertNotIn("main.js:90:12", tidied)


class RenderCheckWinRunnerTests(unittest.TestCase):
    def _make_ledger(self, root):
        (root / "pms").mkdir(parents=True)
        (root / "projects" / "alpha").mkdir(parents=True)
        (root / "projects" / "beta").mkdir(parents=True)
        (root / "tasks").mkdir(parents=True)
        (root / "config.json").write_text('{"lang": "en"}\n', encoding="utf-8")
        (root / "pms" / "pm-alpha.json").write_text(
            json.dumps({"name": "pm-alpha", "project": "alpha"}), encoding="utf-8"
        )
        (root / "pms" / "pm-beta.json").write_text(
            json.dumps({"name": "pm-beta", "project": "beta"}), encoding="utf-8"
        )
        # alpha has 150 conversation lines, beta has 5
        conv_alpha = "\n".join(json.dumps({"i": i}) for i in range(150)) + "\n"
        (root / "projects" / "alpha" / "conversation.jsonl").write_text(conv_alpha, encoding="utf-8")
        (root / "projects" / "alpha" / "screenshot.png").write_bytes(_make_png(10, 10))
        (root / "projects" / "alpha" / "huge.txt").write_bytes(b"x" * (rcw.MAX_PROJECT_FILE_BYTES + 100))
        (root / "projects" / "alpha" / "notes.md").write_text("# notes\n", encoding="utf-8")
        (root / "projects" / "beta" / "conversation.jsonl").write_text('{"i": 0}\n', encoding="utf-8")

        # 25 tasks for pm-alpha, 1 for pm-beta
        for i in range(25):
            tid = f"alpha-task-{i:02d}"
            (root / "tasks" / f"{tid}.json").write_text(
                json.dumps({"id": tid, "pm": "pm-alpha", "updated": f"2026-11-{i + 1:02d} 10:00:00"}),
                encoding="utf-8",
            )
        (root / "tasks" / "beta-task-01.json").write_text(
            json.dumps({"id": "beta-task-01", "pm": "pm-beta", "updated": "2026-11-24 10:00:00"}),
            encoding="utf-8",
        )

    def test_resolve_host_and_missing_host_exit_2(self):
        args = rcw.parse_args([])
        self.assertEqual(rcw.resolve_host(args, env={}), "")
        self.assertEqual(rcw.resolve_host(args, env={"DUDU_WIN_HOST": "alice@win-box"}), "alice@win-box")
        args2 = rcw.parse_args(["--host", "bob@win-vm"])
        self.assertEqual(rcw.resolve_host(args2, env={"DUDU_WIN_HOST": "alice@win-box"}), "bob@win-vm")

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(rcw.main([]), 2)

    def test_invalid_remote_dir_exits_2(self):
        self.assertEqual(rcw.main(["--host", "user@host", "--remote-dir", "../escape"]), 2)

    def test_build_remote_run_args(self):
        args = rcw.parse_args(["--host", "user@host", "--pm", "pm-dudu", "--thread", "t1", "--keep"])
        flags = rcw.build_remote_run_args("dudu-rc-win", args)
        self.assertIn("--verify-window-controls", flags)
        self.assertIn("--keep", flags)
        self.assertIn("pm-dudu", flags)
        self.assertIn("t1", flags)

        args_no_wc = rcw.parse_args(["--host", "user@host", "--no-window-controls"])
        flags2 = rcw.build_remote_run_args("dudu-rc-win", args_no_wc)
        self.assertNotIn("--verify-window-controls", flags2)

    def test_slice_ledger_trims_conversation_skips_binaries_and_caps_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "src", Path(td) / "dst"
            self._make_ledger(src)
            pm, project, stats = rcw.slice_ledger(
                src, dst, thread_id="alpha-task-00", max_conv_lines=100, max_tasks=20
            )
            self.assertEqual(pm, "pm-alpha")
            self.assertEqual(project, "alpha")
            self.assertEqual(stats["tasks"], 20)
            self.assertTrue((dst / "config.json").is_file())
            self.assertTrue((dst / "pms" / "pm-alpha.json").is_file())
            self.assertFalse((dst / "pms" / "pm-beta.json").is_file())
            # conversation trimmed to last 100 lines (50..149)
            lines = (dst / "projects" / "alpha" / "conversation.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 100)
            self.assertEqual(json.loads(lines[0])["i"], 50)
            self.assertEqual(json.loads(lines[-1])["i"], 149)
            # binary & huge files skipped, normal notes kept
            self.assertFalse((dst / "projects" / "alpha" / "screenshot.png").exists())
            self.assertFalse((dst / "projects" / "alpha" / "huge.txt").exists())
            self.assertTrue((dst / "projects" / "alpha" / "notes.md").is_file())
            # requested thread_id included even though it was the oldest
            task_files = sorted(p.stem for p in (dst / "tasks").glob("*.json"))
            self.assertEqual(len(task_files), 20)
            self.assertIn("alpha-task-00", task_files)
            self.assertIn("alpha-task-24", task_files)
            self.assertNotIn("beta-task-01", task_files)

    def test_build_payload_creates_valid_tarball(self):
        with tempfile.TemporaryDirectory() as td:
            ledger_src = Path(td) / "ledger"
            self._make_ledger(ledger_src)
            tar_path = Path(td) / "payload.tar.gz"
            pm, project, _stats = rcw.build_payload(REPO, tar_path, ledger_src)
            self.assertEqual(pm, "pm-alpha")
            self.assertEqual(project, "alpha")
            with tarfile.open(tar_path, "r:gz") as tf:
                names = set(tf.getnames())
            self.assertIn("tests/render_check.py", names)
            self.assertIn("layouts/dudu.json", names)
            self.assertIn("ledger/pms/pm-alpha.json", names)
            self.assertTrue(any(n.startswith("mods/pm-project/") for n in names))

    def test_remote_python_cmd_round_trips_base64(self):
        script = "print('hello \\\"world\\\"')\n"
        cmd = rcw.remote_python_cmd(script)
        self.assertEqual(len(cmd), 1)
        self.assertTrue(cmd[0].startswith('python -c "'))
        b64 = cmd[0].rsplit(" ", 1)[1]
        decoded = base64.b64decode(b64).decode("utf-8")
        self.assertEqual(decoded, script)


if __name__ == "__main__":
    unittest.main()
