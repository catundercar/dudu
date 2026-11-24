"""Direct literal tests for pmlib.ledger.question: no ledger, no temp directory, no patching."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pmlib.errors import Refused  # noqa: E402
from pmlib.ledger import question  # noqa: E402


class StripRecommendMarkerTest(unittest.TestCase):
    def test_strips_supported_suffixes_case_insensitively(self):
        cases = [
            ("Ship now (Recommended)", ("Ship now", True)),
            ("Ship now [recommended]", ("Ship now", True)),
            ("先合并（推荐）", ("先合并", True)),
            ("先合并 [推荐]", ("先合并", True)),
            ("Keep waiting", ("Keep waiting", False)),
            ("", ("", False)),
            (None, ("", False)),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(question.strip_recommend_marker(raw), expected)

    def test_does_not_empty_marker_only_label(self):
        self.assertEqual(question.strip_recommend_marker("(Recommended)"), ("(Recommended)", False))
        self.assertEqual(question.strip_recommend_marker("（推荐）"), ("（推荐）", False))


class QuickAnswersTest(unittest.TestCase):
    def test_empty_args_returns_no_options(self):
        titles, fields = question.quick_answers(SimpleNamespace())
        self.assertEqual((titles, fields), ([], {}))

    def test_plain_options_and_notes(self):
        args = SimpleNamespace(option=["Yes", "No"], why={0: "fast", 1: "safer"}, recommend=False)
        titles, fields = question.quick_answers(args)
        self.assertEqual(titles, ["Yes", "No"])
        self.assertEqual(fields, {"options": ["Yes", "No"], "option_notes": ["fast", "safer"]})

    def test_recommend_flag_marks_first_option_without_index(self):
        args = SimpleNamespace(option=["Merge", "Hold"], why={}, recommend=True)
        titles, fields = question.quick_answers(args)
        self.assertEqual(titles, ["Merge", "Hold"])
        self.assertEqual(fields, {"options": ["Merge", "Hold"], "recommended": True})

    def test_inline_marker_on_second_option_sets_recommended_index(self):
        args = SimpleNamespace(option=["Wait", "Merge（推荐）"], why={}, recommend=False)
        titles, fields = question.quick_answers(args)
        self.assertEqual(titles, ["Wait", "Merge"])
        self.assertEqual(fields, {"options": ["Wait", "Merge"], "recommended": True, "recommended_index": 1})

    def test_inline_marker_on_first_option_omits_recommended_index(self):
        args = SimpleNamespace(option=["Merge (Recommended)", "Wait"], why={}, recommend=False)
        titles, fields = question.quick_answers(args)
        self.assertEqual(titles, ["Merge", "Wait"])
        self.assertEqual(fields, {"options": ["Merge", "Wait"], "recommended": True})

    def test_blank_options_are_dropped_and_notes_align_with_kept(self):
        args = SimpleNamespace(option=["  ", "Keep [推荐]"], why={1: "only choice"}, recommend=False)
        titles, fields = question.quick_answers(args)
        self.assertEqual(titles, ["Keep"])
        self.assertEqual(fields, {"options": ["Keep"], "option_notes": ["only choice"], "recommended": True})

    def test_recommend_without_first_option_raises_refused(self):
        with self.assertRaises(Refused):
            question.quick_answers(SimpleNamespace(option=[], why={}, recommend=True))
        with self.assertRaises(Refused):
            question.quick_answers(SimpleNamespace(option=["", "Later"], why={}, recommend=True))

    def test_why_on_empty_option_raises_refused(self):
        with self.assertRaises(Refused):
            question.quick_answers(SimpleNamespace(option=["", "B"], why={0: "explains nothing"}, recommend=False))

    def test_question_fields_matches_returned_keys(self):
        args = SimpleNamespace(option=["A", "B (Recommended)"], why={0: "note"}, recommend=False)
        _, fields = question.quick_answers(args)
        self.assertEqual(set(fields.keys()), set(question.QUESTION_FIELDS))


if __name__ == "__main__":
    unittest.main()
