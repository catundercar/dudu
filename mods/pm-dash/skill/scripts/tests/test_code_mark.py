"""Unit tests for code-change detection (procs.code_mark) and deliverer handover stability (Deliverer.run)."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SCRIPTS / "tests") not in sys.path:
    sys.path.insert(0, str(SCRIPTS / "tests"))

from fakes import FakeChangeWaiter, FakeClock, FakeHc, make_ctx  # noqa: E402
from pmlib import procs  # noqa: E402
from pmlib.events.deliverer import Deliverer  # noqa: E402


class CodeMarkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scripts = Path(self.tmp.name) / "scripts"
        self.pkg = self.scripts / "pmlib"
        (self.pkg / "sub").mkdir(parents=True)
        (self.pkg / "__pycache__").mkdir(parents=True)
        (self.scripts / "pm.py").write_text("# launcher\n")
        (self.scripts / "pm_store.py").write_text("# sibling\n")
        (self.pkg / "__init__.py").write_text("")
        (self.pkg / "old_mod.py").write_text("# old module\n")
        (self.pkg / "sub" / "mod.py").write_text("# mod\n")
        (self.pkg / "__pycache__" / "ignored.py").write_text("# ignored\n")

    def _patch_paths(self):
        return mock.patch.multiple(procs, _LAUNCHER=self.scripts / "pm.py", _PACKAGE=self.pkg)

    def test_remove_add_touch_and_missing_launcher(self):
        with self._patch_paths():
            first = procs.code_mark()
            self.assertIsNotNone(first)
            self.assertEqual(first, procs.code_mark())
            relpaths = [entry[0] for entry in first]
            self.assertEqual(
                relpaths,
                ["pm.py", "pm_store.py", "pmlib/__init__.py", "pmlib/old_mod.py", "pmlib/sub/mod.py"],
            )

            # Removing a file from the tree changes the mark rather than returning None.
            (self.pkg / "old_mod.py").unlink()
            after_delete = procs.code_mark()
            self.assertIsNotNone(after_delete)
            self.assertNotEqual(after_delete, first)
            self.assertNotIn("pmlib/old_mod.py", [entry[0] for entry in after_delete])

            # Adding a new file under pmlib/ changes the mark.
            (self.pkg / "x.py").write_text("X = 1\n")
            after_add = procs.code_mark()
            self.assertIsNotNone(after_add)
            self.assertNotEqual(after_add, after_delete)
            self.assertIn("pmlib/x.py", [entry[0] for entry in after_add])

            # Touching a file changes the mark.
            later = time.time() + 5
            os.utime(self.pkg / "sub" / "mod.py", (later, later))
            after_touch = procs.code_mark()
            self.assertIsNotNone(after_touch)
            self.assertNotEqual(after_touch, after_add)

            # Only a missing launcher pm.py returns None.
            (self.scripts / "pm.py").unlink()
            self.assertIsNone(procs.code_mark())


class DeliverBatchesHandoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = str(Path(self.tmp.name) / "repo")

    def _run(self, marks, look_results=None, gap=0, clock=None):
        calls = []
        looks = []
        mark_it = iter(marks)
        look_it = iter(look_results) if look_results is not None else None
        clk = clock if clock is not None else FakeClock(mono=100.0)
        hc = FakeHc(clock=clk)
        ctx = make_ctx(self.tmp.name, hc=hc, clock=clk)
        ctx.home.root.mkdir(parents=True, exist_ok=True)

        def next_mark():
            val = next(mark_it)
            calls.append(val)
            return val

        class _TestDeliverer(Deliverer):
            def look(self, changes, stops, bases=None):
                looks.append(len(calls))
                if look_it is None:
                    return 0
                return next(look_it, None)

        d = _TestDeliverer(ctx, self.repo, gap=gap, gone=0, pause=0, script_mark_fn=next_mark)
        result = d.run()
        return result, calls, looks, clk

    def test_hands_over_only_on_second_consecutive_matching_new_mark(self):
        result, calls, looks, _ = self._run(["old", "new-a", "new-b", "new-b"])
        self.assertTrue(result)
        self.assertEqual(calls, ["old", "new-a", "new-b", "new-b"])
        self.assertEqual(looks, [])  # skips running old-code look() once a new mark is observed

    def test_hands_over_after_directory_delete_and_copy_back(self):
        result, calls, looks, _ = self._run(["old", None, None, "new", "new"])
        self.assertTrue(result)
        self.assertEqual(calls, ["old", None, None, "new", "new"])
        self.assertEqual(looks, [2, 3])

    def test_non_consecutive_new_mark_after_none_does_not_hand_over(self):
        result, calls, looks, _ = self._run(["old", "new", None, "new", "new"])
        self.assertTrue(result)
        self.assertEqual(calls, ["old", "new", None, "new", "new"])
        self.assertEqual(looks, [3])

    def test_constant_old_mark_never_hands_over(self):
        result, calls, looks, _ = self._run(["old", "old", "old", "old"], look_results=[0, 0, None])
        self.assertFalse(result)
        self.assertEqual(calls, ["old", "old", "old", "old"])
        self.assertEqual(looks, [2, 3, 4])

    def test_consecutive_checks_wait_at_least_deliver_gap(self):
        clk = FakeClock(mono=100.0)
        result, calls, _, clk = self._run(["old", "new", "new"], gap=1, clock=clk)
        self.assertTrue(result)
        self.assertEqual(calls, ["old", "new", "new"])
        self.assertGreaterEqual(clk.monotonic() - 100.0, 1.0)


if __name__ == "__main__":
    unittest.main()
