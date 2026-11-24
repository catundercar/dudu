"""Direct literal tests for pmlib.ledger.deps: no ledger, no temp directory, no patching."""
import os
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = "/nonexistent/pm-home-for-test_deps"
    try:
        from pmlib.ledger import deps  # noqa: E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved
else:
    from pmlib.ledger import deps  # noqa: E402


from pmlib.errors import Refused  # noqa: E402


class EvaluateDependsOnTest(unittest.TestCase):
    def test_no_dependencies_is_all_met_but_not_ready(self):
        info = deps.evaluate_depends_on({"id": "a", "status": "proposed"}, {})
        self.assertTrue(info["all_met"])
        self.assertFalse(info["ready"])
        self.assertEqual(deps.dep_key_for(info), "")
        self.assertEqual(deps.format_dep_summary(info), "")
        self.assertEqual(deps.format_dep_summary(info, include_empty=True), "no dependencies")

    def test_all_met_on_proposed_task_is_ready(self):
        by_id = {
            "d1": {"id": "d1", "status": "merged", "title": "First"},
            "d2": {"id": "d2", "status": "in_progress", "landed": "2026-11-22", "title": "Second"},
        }
        task = {"id": "t", "status": "proposed", "title": "Next", "depends_on": ["d1", "d2"], "parent": "epic"}
        info = deps.evaluate_depends_on(task, by_id)
        self.assertTrue(info["all_met"])
        self.assertTrue(info["ready"])
        self.assertEqual([d["reason"] for d in info["met"]], ["merged", "landed"])
        key = deps.dep_key_for(info)
        self.assertEqual(key, "ready:d1,d2")
        self.assertEqual(deps.format_dep_summary(info), "all deps met: d1 (merged), d2 (landed)")
        msg = deps._dep_event_message(task, info, key)
        self.assertIn("Dependencies met, ready to dispatch (Next)", msg)
        self.assertIn("; parent: epic", msg)

    def test_all_met_on_in_progress_task_is_not_ready(self):
        by_id = {"d1": {"id": "d1", "status": "done"}}
        info = deps.evaluate_depends_on({"id": "t", "status": "in_progress", "depends_on": ["d1"]}, by_id)
        self.assertTrue(info["all_met"])
        self.assertFalse(info["ready"])
        self.assertEqual(deps.dep_key_for(info), "")

    def test_waiting_dependency_blocks_ready(self):
        by_id = {
            "d1": {"id": "d1", "status": "merged"},
            "d2": {"id": "d2", "status": "review"},
        }
        info = deps.evaluate_depends_on({"id": "t", "status": "proposed", "depends_on": ["d1", "d2"]}, by_id)
        self.assertFalse(info["all_met"])
        self.assertFalse(info["ready"])
        self.assertEqual(deps.dep_key_for(info), "")
        self.assertEqual(deps.format_dep_summary(info), "waiting on: d2 (review)")

    def test_abandoned_dependency_reports_broken_and_sorted_key(self):
        by_id = {
            "b": {"id": "b", "status": "abandoned"},
            "a": {"id": "a", "status": "abandoned"},
            "c": {"id": "c", "status": "in_progress"},
        }
        task = {"id": "t", "status": "proposed", "title": "Child", "depends_on": ["b", "a", "c"]}
        info = deps.evaluate_depends_on(task, by_id)
        self.assertFalse(info["all_met"])
        self.assertFalse(info["ready"])
        key = deps.dep_key_for(info)
        self.assertEqual(key, "abandoned:a,b")
        self.assertEqual(deps.format_dep_summary(info),
                         "blocked by broken dep: b (abandoned!), a (abandoned!), c (in_progress)")
        msg = deps._dep_event_message(task, info, key)
        self.assertIn("Dependency abandoned (Child): b (abandoned!), a (abandoned!)", msg)

    def test_missing_dependency_is_broken_without_abandoned_key(self):
        info = deps.evaluate_depends_on({"id": "t", "status": "proposed", "depends_on": ["ghost"]}, {})
        self.assertFalse(info["all_met"])
        self.assertEqual(len(info["missing"]), 1)
        self.assertEqual(deps.dep_key_for(info), "")
        self.assertEqual(deps.format_dep_item(info["missing"][0]), "ghost (missing!)")
        self.assertEqual(deps.format_dep_summary(info), "blocked by broken dep: ghost (missing!)")


class ParseAndValidateDependsOnTest(unittest.TestCase):
    def test_none_and_empty_inputs(self):
        self.assertIsNone(deps.parse_depends_on(None))
        self.assertEqual(deps.parse_depends_on(""), [])
        self.assertEqual(deps.parse_depends_on(["  ,  "]), [])

    def test_incremental_removal_does_not_touch_disk(self):
        self.assertEqual(deps.parse_depends_on(["-a"], existing=["a", "b", "c"]), ["b", "c"])
        self.assertEqual(deps.parse_depends_on("-a,-c", existing=["a", "b", "c"]), ["b"])

    def test_mixing_incremental_and_full_ids_raises_refused(self):
        with self.assertRaises(Refused):
            deps.parse_depends_on(["+a", "b"])

    def test_self_cycle_and_invalid_id_raise_refused(self):
        with self.assertRaises(Refused):
            deps._check_dep_cycle("same", "same")
        with self.assertRaises(Refused):
            deps._validate_dep_id("../escape")


if __name__ == "__main__":
    unittest.main()
