"""Direct literal and table tests for pmlib.ledger.family: no ledger, no real home access."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pmlib.ledger import deps, family  # noqa: E402

ACTIVE = ("proposed", "in_progress", "review", "blocked", "paused")
CLOSED = ("merged", "released", "done", "abandoned")


class _IsolatedPmHomeTestCase(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"PM_HOME": "/nonexistent/pm-home-for-test_family"})
        patch.start()
        self.addCleanup(patch.stop)


class FamilyHelpersTest(_IsolatedPmHomeTestCase):
    def test_task_children_map_groups_by_parent_and_excludes_review_of_only(self):
        # Current `task_children_map` behavior: only tasks carrying a truthy `parent` field are children.
        # Real `-review` tasks carry `review_of` (and no `parent`), so they are NOT children; if a
        # `-review` task explicitly sets `parent`, `task_children_map` includes it like any other task.
        tasks = [
            {"id": "epic", "status": "in_progress"},
            {"id": "c1", "status": "merged", "parent": "epic"},
            {"id": "c1-review", "status": "in_progress", "review_of": "c1"},
            {"id": "epic-review", "status": "in_progress", "review_of": "epic"},
            {"id": "c2", "status": "done", "parent": "epic"},
            {"id": "orphan", "status": "proposed"},
        ]
        grouped = family.task_children_map(tasks)
        self.assertEqual([t["id"] for t in grouped["epic"]], ["c1", "c2"])
        self.assertNotIn("c1", grouped)

    def test_format_children_summary_counts_done_ready_waiting_todo(self):
        c1 = {"id": "c1", "status": "merged", "parent": "p"}
        c2 = {"id": "c2", "status": "proposed", "parent": "p", "depends_on": ["c1"]}
        c3 = {"id": "c3", "status": "proposed", "parent": "p", "depends_on": ["c2"]}
        c4 = {"id": "c4", "status": "proposed", "parent": "p"}
        by_id = {t["id"]: t for t in (c1, c2, c3, c4)}
        dep_by_id = {tid: deps.evaluate_depends_on(t, by_id) for tid, t in by_id.items()}
        self.assertEqual(
            family.format_children_summary([c1, c2, c3, c4], dep_by_id=dep_by_id),
            "subtasks=1/4 (1 ready, 1 waiting, 1 todo)",
        )
        self.assertEqual(family.format_children_summary([]), "")

    def test_family_counts_and_summary(self):
        parent = {"id": "epic", "status": "in_progress"}
        children = [
            {"id": "c1", "status": "merged", "parent": "epic"},
            {"id": "c2", "status": "merged", "parent": "epic"},
            {"id": "c3", "status": "abandoned", "parent": "epic"},
        ]
        fam = family.Family(parent, children)
        self.assertEqual(fam.counts, {"merged": 2, "abandoned": 1})
        self.assertEqual(fam.summary(), "subtasks=2/3")


class FamilyRollupTableTest(_IsolatedPmHomeTestCase):
    def test_rollup_rules_table(self):
        cases = [
            (
                "no children -> None",
                {"id": "p", "status": "in_progress"},
                [],
                None,
                None,
                None,
            ),
            (
                "parent already done -> None",
                {"id": "p", "status": "done"},
                [{"id": "c1", "status": "merged"}],
                None,
                None,
                None,
            ),
            (
                "parent already merged -> None",
                {"id": "p", "status": "merged"},
                [{"id": "c1", "status": "merged"}],
                None,
                None,
                None,
            ),
            (
                "parent already abandoned -> None",
                {"id": "p", "status": "abandoned"},
                [{"id": "c1", "status": "abandoned"}],
                None,
                None,
                None,
            ),
            (
                "child still proposed -> None",
                {"id": "p", "status": "in_progress"},
                [{"id": "c1", "status": "merged"}, {"id": "c2", "status": "proposed"}],
                None,
                None,
                None,
            ),
            (
                "child still in_progress -> None",
                {"id": "p", "status": "in_progress"},
                [{"id": "c1", "status": "in_progress"}],
                None,
                None,
                None,
            ),
            (
                "child still in review -> None",
                {"id": "p", "status": "in_progress"},
                [{"id": "c1", "status": "merged"}, {"id": "c2", "status": "review"}],
                None,
                None,
                None,
            ),
            (
                "child still blocked -> None",
                {"id": "p", "status": "in_progress"},
                [{"id": "c1", "status": "blocked"}],
                None,
                None,
                None,
            ),
            (
                "child still paused -> None",
                {"id": "p", "status": "in_progress"},
                [{"id": "c1", "status": "paused"}],
                None,
                None,
                None,
            ),
            (
                "child with unknown status -> None",
                {"id": "p", "status": "in_progress"},
                [{"id": "c1", "status": "mystery"}],
                None,
                None,
                None,
            ),
            (
                "single merged child on open parent -> close",
                {"id": "p", "status": "in_progress"},
                [{"id": "c1", "status": "merged"}],
                "close",
                "children_finished",
                "1 child task finished (1 merged)",
            ),
            (
                "mixed merged and abandoned children -> close with breakdown",
                {"id": "p", "status": "proposed"},
                [
                    {"id": "c1", "status": "merged"},
                    {"id": "c2", "status": "merged"},
                    {"id": "c3", "status": "abandoned"},
                ],
                "close",
                "children_finished",
                "all 3 child tasks finished (2 merged, 1 abandoned)",
            ),
            (
                "done and released children -> close",
                {"id": "p", "status": "in_progress"},
                [
                    {"id": "c1", "status": "done"},
                    {"id": "c2", "status": "released"},
                ],
                "close",
                "children_finished",
                "all 2 child tasks finished (1 released, 1 done)",
            ),
            (
                "single abandoned child -> notify PM",
                {"id": "p", "status": "in_progress"},
                [{"id": "c1", "status": "abandoned"}],
                "notify",
                "all_abandoned",
                "1 child task abandoned",
            ),
            (
                "all children abandoned -> notify PM",
                {"id": "p", "status": "in_progress"},
                [
                    {"id": "c1", "status": "abandoned"},
                    {"id": "c2", "status": "abandoned"},
                ],
                "notify",
                "all_abandoned",
                "all 2 child tasks abandoned",
            ),
            (
                "parent itself is blocked (children finished) -> notify, do not silently close",
                {"id": "p", "status": "blocked"},
                [{"id": "c1", "status": "merged"}],
                "notify",
                "parent_blocked",
                "1 child task finished (1 merged)",
            ),
            (
                "parent itself is blocked (all children abandoned) -> notify all_abandoned",
                {"id": "p", "status": "blocked"},
                [{"id": "c1", "status": "abandoned"}],
                "notify",
                "all_abandoned",
                "1 child task abandoned",
            ),
            (
                "parent has own live worker -> notify parent_has_work",
                {"id": "p", "status": "in_progress", "dispatched": "2026-11-22 08:00"},
                [{"id": "c1", "status": "merged"}],
                "notify",
                "parent_has_work",
                "1 child task finished (1 merged)",
            ),
            (
                "parent has retired worker and no branch/plan -> close",
                {"id": "p", "status": "in_progress", "dispatched": "2026-11-22 08:00", "retired": "2026-11-22 09:00"},
                [{"id": "c1", "status": "merged"}],
                "close",
                "children_finished",
                "1 child task finished (1 merged)",
            ),
            (
                "parent has own branch -> notify parent_has_work",
                {"id": "p", "status": "in_progress", "branch": "dev/parent"},
                [{"id": "c1", "status": "merged"}],
                "notify",
                "parent_has_work",
                "1 child task finished (1 merged)",
            ),
            (
                "parent has unfinished plan step -> notify parent_has_work",
                {
                    "id": "p",
                    "status": "in_progress",
                    "plan": [{"text": "deploy", "state": "todo", "anchor": "custom"}],
                },
                [{"id": "c1", "status": "merged"}],
                "notify",
                "parent_has_work",
                "1 child task finished (1 merged)",
            ),
            (
                "parent with all-done plan -> close",
                {
                    "id": "p",
                    "status": "in_progress",
                    "plan": [{"text": "split", "state": "done", "anchor": "work"}],
                },
                [{"id": "c1", "status": "merged"}],
                "close",
                "children_finished",
                "1 child task finished (1 merged)",
            ),
        ]

        for label, parent, children, expected_action, expected_reason, expected_summary in cases:
            with self.subTest(case=label):
                parent_before = copy.deepcopy(parent)
                children_before = copy.deepcopy(children)
                res = family.Family(parent, children).rollup(ACTIVE, CLOSED)
                if expected_action is None:
                    self.assertIsNone(res)
                else:
                    self.assertIsNotNone(res)
                    self.assertEqual(res.action, expected_action)
                    self.assertEqual(res.reason, expected_reason)
                    self.assertEqual(res.summary, expected_summary)
                # Pure function: never mutates inputs.
                self.assertEqual(parent, parent_before)
                self.assertEqual(children, children_before)

    def test_review_tasks_follow_task_children_map_behavior(self):
        # 1) A normal `-review` task has `review_of` and NO `parent`: `task_children_map` does not treat
        #    it as a child, so an in-progress review task without `parent` does not block rollup.
        parent = {"id": "epic", "status": "in_progress"}
        tasks = [
            parent,
            {"id": "c1", "status": "merged", "parent": "epic"},
            {"id": "c1-review", "status": "in_progress", "review_of": "c1"},
            {"id": "epic-review", "status": "in_progress", "review_of": "epic"},
        ]
        fam = family.Family.from_tasks(parent, tasks)
        self.assertEqual([c["id"] for c in fam.children], ["c1"])
        res = fam.rollup(ACTIVE, CLOSED)
        self.assertIsNotNone(res)
        self.assertEqual(res.action, "close")

        # 2) If a `-review` task explicitly carries `parent`, `task_children_map` includes it as a child,
        #    so rollup treats it as a child too (blocks while in_progress, closes once done).
        with_parent_review = [
            parent,
            {"id": "c1", "status": "merged", "parent": "epic"},
            {"id": "c1-review", "status": "in_progress", "review_of": "c1", "parent": "epic"},
        ]
        fam_open = family.Family.from_tasks(parent, with_parent_review)
        self.assertEqual([c["id"] for c in fam_open.children], ["c1", "c1-review"])
        self.assertIsNone(fam_open.rollup(ACTIVE, CLOSED))

        with_parent_review[2]["status"] = "done"
        fam_done = family.Family.from_tasks(parent, with_parent_review)
        res_done = fam_done.rollup(ACTIVE, CLOSED)
        self.assertIsNotNone(res_done)
        self.assertEqual(res_done.action, "close")
        self.assertEqual(res_done.counts, {"merged": 1, "done": 1})

    def test_rollup_own_session_review_and_running_helper(self):
        c1 = [{"id": "c1", "status": "merged"}]
        # 1. own_session_live=True -> notify parent_has_work
        res = family.Family({"id": "p", "status": "in_progress", "pane": "hc:t9"}, c1).rollup(
            ACTIVE, CLOSED, own_session_live=True
        )
        self.assertIsNotNone(res)
        self.assertEqual((res.action, res.reason), ("notify", "parent_has_work"))

        # 2. own_session_live=False -> close even when pane is set
        res_dead = family.Family({"id": "p", "status": "in_progress", "pane": "hc:t9"}, c1).rollup(
            ACTIVE, CLOSED, own_session_live=False
        )
        self.assertIsNotNone(res_dead)
        self.assertEqual((res_dead.action, res_dead.reason), ("close", "children_finished"))

        # 3. parent status == review -> notify parent_has_work
        res_rev = family.Family({"id": "p", "status": "review"}, c1).rollup(ACTIVE, CLOSED)
        self.assertIsNotNone(res_rev)
        self.assertEqual((res_rev.action, res_rev.reason), ("notify", "parent_has_work"))

        # 4. parent has running helper -> notify parent_has_work
        res_helper = family.Family(
            {"id": "p", "status": "in_progress", "helpers": [{"name": "h1", "status": "running"}]},
            c1,
        ).rollup(ACTIVE, CLOSED)
        self.assertIsNotNone(res_helper)
        self.assertEqual((res_helper.action, res_helper.reason), ("notify", "parent_has_work"))

        # 5. parent has only finished helpers -> close
        res_helper_done = family.Family(
            {"id": "p", "status": "in_progress", "helpers": [{"name": "h1", "status": "done"}]},
            c1,
        ).rollup(ACTIVE, CLOSED)
        self.assertIsNotNone(res_helper_done)
        self.assertEqual((res_helper_done.action, res_helper_done.reason), ("close", "children_finished"))

        # 6. all_abandoned and parent_blocked still take precedence over own_session_live
        res_ab = family.Family({"id": "p", "status": "in_progress"}, [{"id": "c1", "status": "abandoned"}]).rollup(
            ACTIVE, CLOSED, own_session_live=True
        )
        self.assertEqual((res_ab.action, res_ab.reason), ("notify", "all_abandoned"))

        res_blk = family.Family({"id": "p", "status": "blocked"}, c1).rollup(
            ACTIVE, CLOSED, own_session_live=True
        )
        self.assertEqual((res_blk.action, res_blk.reason), ("notify", "parent_blocked"))

    def test_rollup_key_is_sorted_and_deterministic(self):
        fam_a = family.Family({"id": "p"}, [{"id": "c2", "status": "done"}, {"id": "c1", "status": "merged"}])
        fam_b = family.Family({"id": "p"}, [{"id": "c1", "status": "merged"}, {"id": "c2", "status": "done"}])
        self.assertEqual(fam_a.rollup_key, fam_b.rollup_key)
        self.assertTrue(fam_a.rollup_key)


if __name__ == "__main__":
    unittest.main()
