"""Direct literal tests for pmlib.ledger.plan: no ledger, no temp directory, no patching."""
import os
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if "pmlib.context" not in sys.modules:
    _saved = os.environ.get("PM_HOME")
    os.environ["PM_HOME"] = "/nonexistent/pm-home-for-test_plan"
    try:
        from pmlib.ledger import plan  # noqa: E402
    finally:
        if _saved is None:
            os.environ.pop("PM_HOME", None)
        else:
            os.environ["PM_HOME"] = _saved
else:
    from pmlib.ledger import plan  # noqa: E402


class PlanAnchorAndParseTest(unittest.TestCase):
    def test_infer_anchor_table(self):
        cases = [
            ("实现登录接口", "work"),
            ("独立代码审查", "review"),
            ("Review PR", "review"),
            ("免审查直接合进 main", "merge"),
            ("等你审阅后决定", "custom"),
            ("安装到本机", "custom"),
            ("合并进 main", "merge"),
            ("暂不合进 main，先实现", "work"),
            ("", "custom"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(plan.infer_anchor(text), expected)

    def test_step_anchor_defaults_to_custom_for_missing_or_invalid(self):
        self.assertEqual(plan.step_anchor({"text": "x", "anchor": "review"}), "review")
        self.assertEqual(plan.step_anchor({"text": "x", "anchor": "MERGE"}), "merge")
        self.assertEqual(plan.step_anchor({"text": "x", "anchor": "bogus"}), "custom")
        self.assertEqual(plan.step_anchor({"text": "x"}), "custom")
        self.assertEqual(plan.step_anchor("not a dict"), "custom")

    def test_parse_plan_steps_outer_states_and_tags(self):
        steps, explicit = plan.parse_plan_steps("[x] 实现; [>] 审查; [ ] 合 main; [ ] 装到本机 @none")
        self.assertTrue(explicit)
        self.assertEqual(steps, [
            {"text": "实现", "state": "done", "anchor": "work"},
            {"text": "审查", "state": "doing", "anchor": "review"},
            {"text": "合 main", "state": "todo", "anchor": "merge"},
            {"text": "装到本机", "state": "todo", "anchor": "custom"},
        ])

    def test_parse_plan_steps_inner_omits_anchors(self):
        steps, explicit = plan.parse_plan_steps(None, ["1. 写测试", "2. 跑验证"], outer=False)
        self.assertFalse(explicit)
        self.assertEqual(steps, [
            {"text": "写测试", "state": "todo"},
            {"text": "跑验证", "state": "todo"},
        ])

    def test_auto_review_max_rounds_falls_back_to_default_without_config(self):
        self.assertEqual(plan.auto_review_max_rounds(), plan.AUTO_REVIEW_MAX_ROUNDS)


class PlanQueryAndSyncTest(unittest.TestCase):
    def test_has_pending_review_step_and_has_unfinished_plan(self):
        task = {"plan": [
            {"text": "work", "state": "done", "anchor": "work"},
            {"text": "review", "state": "todo", "anchor": "review"},
        ]}
        self.assertTrue(plan.has_pending_review_step(task))
        self.assertTrue(plan.has_unfinished_plan(task))
        task["plan"][1]["state"] = "done"
        self.assertFalse(plan.has_pending_review_step(task))
        self.assertFalse(plan.has_unfinished_plan(task))

    def test_plan_progress_picks_doing_else_first_unfinished(self):
        steps = [
            {"text": "a", "state": "done"},
            {"text": "b", "state": "todo"},
            {"text": "c", "state": "doing"},
        ]
        self.assertEqual(plan.plan_progress(steps), (1, 3, "c"))
        steps[2]["state"] = "todo"
        self.assertEqual(plan.plan_progress(steps), (1, 3, "b"))
        self.assertEqual(plan.plan_progress([]), (0, 0, ""))

    def test_activate_first_todo_prefers_non_review_merge(self):
        steps = [
            {"text": "review", "state": "todo", "anchor": "review"},
            {"text": "impl", "state": "todo", "anchor": "work"},
        ]
        plan.activate_first_todo(steps)
        self.assertEqual([s["state"] for s in steps], ["todo", "doing"])

    def test_sync_plan_for_status_review_and_reopen_in_progress(self):
        task = {
            "plan": [
                {"text": "impl", "state": "doing", "anchor": "work"},
                {"text": "review", "state": "todo", "anchor": "review"},
                {"text": "merge", "state": "todo", "anchor": "merge"},
            ],
            "subplan": [{"text": "sub", "state": "doing"}],
        }
        plan.sync_plan_for_status(task, "review", prev_status="in_progress")
        self.assertEqual([s["state"] for s in task["plan"]], ["done", "doing", "todo"])
        self.assertEqual(task["subplan"][0]["state"], "done")

        plan.sync_plan_for_status(task, "in_progress", prev_status="review")
        self.assertEqual([s["state"] for s in task["plan"]], ["doing", "todo", "todo"])

    def test_sync_plan_on_approve_and_merge_with_post_merge_steps(self):
        task = {
            "plan": [
                {"text": "impl", "state": "done", "anchor": "work"},
                {"text": "review", "state": "doing", "anchor": "review"},
                {"text": "merge", "state": "todo", "anchor": "merge"},
                {"text": "install", "state": "todo", "anchor": "custom"},
            ],
        }
        plan.sync_plan_on_approve(task)
        self.assertEqual([s["state"] for s in task["plan"]], ["done", "done", "doing", "todo"])
        self.assertEqual([s["text"] for s in plan.post_merge_steps(task)], ["install"])

        has_more = plan.sync_plan_on_merge(task, advance_next=True)
        self.assertTrue(has_more)
        self.assertEqual([s["state"] for s in task["plan"]], ["done", "done", "done", "doing"])

    def test_advance_outer_plan_step_moves_cursor(self):
        task = {"plan": [
            {"text": "one", "state": "doing", "anchor": "work"},
            {"text": "two", "state": "todo", "anchor": "custom"},
        ]}
        changed, done_n, total_n, nxt = plan.advance_outer_plan_step(task)
        self.assertEqual((changed, done_n, total_n, nxt), (True, 1, 2, "two"))
        self.assertEqual([s["state"] for s in task["plan"]], ["done", "doing"])

    def test_sync_plan_for_done_closes_all_steps(self):
        task = {"plan": [
            {"text": "one", "state": "doing", "anchor": "work"},
            {"text": "two", "state": "todo", "anchor": "custom"},
        ]}
        plan.sync_plan_for_status(task, "done")
        self.assertEqual([s["state"] for s in task["plan"]], ["done", "done"])


if __name__ == "__main__":
    unittest.main()
