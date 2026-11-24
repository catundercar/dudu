"""replay.py against itself: the same scripts folder as old and new must show no difference.

A difference here means the replay is not deterministic or its normalization misses something (a time, a path, a
pid), and it would then report noise when a refactor is compared with main.
"""
import contextlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

WINDOWS = os.name == "nt"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if not WINDOWS:
    import replay  # noqa: E402
else:
    replay = None


@unittest.skipIf(WINDOWS, "replay.py is POSIX-only (uses fcntl)")
class ReplayTest(unittest.TestCase):
    def test_same_scripts_on_both_sides_show_no_difference(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = replay.main(["--old", str(HERE.parent), "--new", str(HERE.parent)])
        self.assertEqual(status, 0, out.getvalue())
        self.assertIn("no differences", out.getvalue())

    def test_a_changed_output_is_reported(self):
        # The comparison itself works: a pm.py whose `status` prints one more line differs at that step.
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            skill = Path(temp) / "skill"
            shutil.copytree(HERE.parent.parent, skill, ignore=replay.SKIP_COPY)
            pm = skill / "scripts" / "pmlib" / "cli.py"  # pm.py is the launcher; main() is here
            text = pm.read_text(encoding="utf-8")
            marker = "\ndef main(argv=None, ctx=None):\n    p = build_parser()\n"
            self.assertIn(marker, text)
            pm.write_text(text.replace(marker, marker + "    print('extra line')\n"), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                status = replay.main(["--old", str(HERE.parent), "--new", str(skill / "scripts")])
        self.assertEqual(status, 1, out.getvalue())
        self.assertIn("+extra line", out.getvalue())

    def test_minute_boundary_mismatch_retries_and_warns_after_three_attempts(self):
        short_scenario = [
            replay.setup_repo,
            ["status"],
            ["new", "First task", "--slug", "first"],
            ["state"],
        ]
        n_commands = 3  # steps 1, 2, 3

        def make_clock(skewed_attempts):
            # 4 clock reads per step: old start, old end, new start, new end.
            # On skewed attempts, the minute ticks between old and new during step 2 (old in M, new in M+1).
            reads = 0

            def clock():
                nonlocal reads
                attempt = reads // (n_commands * 4)
                within = reads % (n_commands * 4)
                step_idx = within // 4 + 1  # 1-based step index
                is_new = (within % 4) >= 2
                reads += 1
                base = 1000 + attempt * 10
                if attempt < skewed_attempts and (step_idx > 2 or (step_idx == 2 and is_new)):
                    return base + 1
                return base

            return clock

        real_run_step = replay.run_step

        with mock.patch.object(replay, "SCENARIO", short_scenario):
            # 1) On attempt 1, step 2 lands in different minutes on old vs new (with a spurious diff);
            #    attempt 2 stays aligned: replay discards attempt 1, reruns once, and reports no differences.
            with self.subTest("retries_and_discards_misaligned_attempt"):
                calls = 0

                def flaky_once(side, step):
                    nonlocal calls
                    calls += 1
                    res = real_run_step(side, step)
                    # Attempt 1, step 3, old side is the 5th run_step call (2 calls per step).
                    if calls == 5 and side.name == "old":
                        res = {**res, "stdout": res["stdout"] + "\nskew-only diff\n"}
                    return res

                out = io.StringIO()
                with mock.patch.object(replay, "run_step", side_effect=flaky_once):
                    with contextlib.redirect_stdout(out):
                        status = replay.main(["--old", str(HERE.parent), "--new", str(HERE.parent)],
                                             clock=make_clock(skewed_attempts=1))
                self.assertEqual(status, 0, out.getvalue())
                self.assertIn("no differences", out.getvalue())
                self.assertNotIn("skew-only diff", out.getvalue())
                self.assertNotIn(replay.CLOCK_SKEW_NOTE, out.getvalue())
                self.assertEqual(calls, 2 * n_commands * 2)

            # 2) Three consecutive misaligned attempts with a real diff: stops at 3 attempts,
            #    reports the real diff (exit 1) and includes the clock-skew note.
            with self.subTest("reports_real_diff_with_note_after_three_mismatches"):
                calls = 0

                def always_diff_step3(side, step):
                    nonlocal calls
                    calls += 1
                    res = real_run_step(side, step)
                    if side.name == "new" and step == ["state"]:
                        res = {**res, "stdout": res["stdout"] + "\nreal diff\n"}
                    return res

                out = io.StringIO()
                with mock.patch.object(replay, "run_step", side_effect=always_diff_step3):
                    with contextlib.redirect_stdout(out):
                        status = replay.main(["--old", str(HERE.parent), "--new", str(HERE.parent)],
                                             clock=make_clock(skewed_attempts=replay.MAX_ATTEMPTS))
                self.assertEqual(status, 1, out.getvalue())
                self.assertIn("+real diff", out.getvalue())
                self.assertIn(replay.CLOCK_SKEW_NOTE, out.getvalue())
                self.assertEqual(calls, replay.MAX_ATTEMPTS * n_commands * 2)

            # 3) Three consecutive misaligned attempts via module-level wall_minute patch with identical outputs:
            #    stops at 3 attempts, reports no differences (exit 0) and still includes the clock-skew note.
            with self.subTest("reports_clean_result_with_note_after_three_mismatches"):
                calls = 0

                def counting_run_step(side, step):
                    nonlocal calls
                    calls += 1
                    return real_run_step(side, step)

                out = io.StringIO()
                with mock.patch.object(replay, "run_step", side_effect=counting_run_step), \
                     mock.patch.object(replay, "wait_past_minute_boundary", return_value=0.0), \
                     mock.patch.object(replay, "wall_minute", side_effect=make_clock(skewed_attempts=replay.MAX_ATTEMPTS)):
                    with contextlib.redirect_stdout(out):
                        status = replay.main(["--old", str(HERE.parent), "--new", str(HERE.parent)])
                self.assertEqual(status, 0, out.getvalue())
                self.assertIn("no differences", out.getvalue())
                self.assertIn(replay.CLOCK_SKEW_NOTE, out.getvalue())
                self.assertEqual(calls, replay.MAX_ATTEMPTS * n_commands * 2)

            # 4) Near a :00 boundary, replay sleeps past :00 before starting the step pair (via injectable wall_time
            #    and sleeper, without actually sleeping) and completes in a single aligned attempt.
            with self.subTest("guard_sleeps_past_minute_boundary_in_replay"):
                fake_now = [120.0 + 58.0]  # 2.0 s before :00 -> triggers guard
                slept = []

                def fake_sleep(dt):
                    slept.append(dt)
                    fake_now[0] += dt

                out = io.StringIO()
                with mock.patch.object(replay, "wall_time", side_effect=lambda: fake_now[0]):
                    with contextlib.redirect_stdout(out):
                        status = replay.main(["--old", str(HERE.parent), "--new", str(HERE.parent)],
                                             sleeper=fake_sleep)
                self.assertEqual(status, 0, out.getvalue())
                self.assertIn("no differences", out.getvalue())
                self.assertNotIn(replay.CLOCK_SKEW_NOTE, out.getvalue())
                self.assertEqual(len(slept), 1)
                self.assertAlmostEqual(slept[0], 2.05)

        # 5) Unit checks on guard boundary threshold and step alignment rules (including mid-step straddling).
        with self.subTest("guard_and_alignment_rules"):
            slept = []
            self.assertAlmostEqual(replay.wait_past_minute_boundary(now=lambda: 120.0 + 57.5, sleeper=slept.append), 2.55)
            self.assertEqual(len(slept), 1)
            self.assertEqual(replay.wait_past_minute_boundary(now=lambda: 120.0 + 56.0, sleeper=slept.append), 0.0)
            self.assertEqual(replay.wait_past_minute_boundary(now=lambda: 120.0, sleeper=slept.append), 0.0)
            self.assertEqual(len(slept), 1)

            self.assertTrue(replay.steps_aligned([(10, 10), (10, 10), (11, 11)], [(10, 10), (10, 10), (11, 11)]))
            self.assertFalse(replay.steps_aligned([(10, 10), (10, 10)], [(10, 10), (11, 11)]))
            self.assertFalse(replay.steps_aligned([(10, 10), (10, 10)], [(10, 10), (10, 11)]))
            self.assertFalse(replay.steps_aligned([(10, 10), (10, 11)], [(10, 10), (11, 11)]))


if __name__ == "__main__":
    unittest.main()
