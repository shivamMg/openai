import json
import unittest

from tool_call_grader import grade, grade_tool_calls, grade_text, grade_with_config, GraderConfig


def _call(name, args=None):
    """Actual tool call (output_tools) — arguments as JSON string."""
    return {"function": {"name": name, "arguments": json.dumps(args or {})}}


def _ref(name, args=None):
    """Reference tool call — arguments as dict."""
    return {"function": {"name": name, "arguments": args or {}}}


def _grade_all(sample, item):
    """Grade with no include_tools filter (grades all tool calls)."""
    config = GraderConfig()
    config.include_tools = []
    return grade_with_config(sample, item, config)


class TestGrade(unittest.TestCase):

    def _run_cases(self, cases):
        for name, sample, item, expected in cases:
            with self.subTest(name):
                self.assertAlmostEqual(_grade_all(sample, item), expected, places=2)

    def test_grade_via_output_tools(self):
        cases = [
            (
                "both empty",
                {"output_tools": []},
                {"reference_tool_calls": []},
                0.9,
            ),
            (
                "expected empty, actual present",
                {"output_tools": [_call("foo")]},
                {"reference_tool_calls": []},
                0.0,
            ),
            (
                "actual empty, expected present",
                {"output_tools": []},
                {"reference_tool_calls": [_ref("foo")]},
                0.0,
            ),
            (
                "actual missing entirely",
                {},
                {"reference_tool_calls": [_ref("foo")]},
                0.0,
            ),
            (
                "perfect single call",
                {"output_tools": [_call("search", {"q": "hello"})]},
                {"reference_tool_calls": [_ref("search", {"q": "hello"})]},
                0.9,
            ),
            (
                "perfect multiple calls",
                {"output_tools": [_call("a", {"x": 1}), _call("b", {"y": 2})]},
                {"reference_tool_calls": [_ref("a", {"x": 1}), _ref("b", {"y": 2})]},
                0.9,
            ),
        ]
        self._run_cases(cases)

    def test_grade_via_output_text_fallback(self):
        """output_tools parsed from output_text JSON when output_tools key is absent."""
        payload = json.dumps({"output_tools": [_call("search", {"q": "hi"})]})
        sample = {"output_text": payload}
        item = {"reference_tool_calls": [_ref("search", {"q": "hi"})]}
        self.assertAlmostEqual(_grade_all(sample, item), 0.9)

    def test_grade_output_text_invalid_json(self):
        sample = {"output_text": "not json"}
        item = {"reference_tool_calls": [_ref("foo")]}
        self.assertAlmostEqual(_grade_all(sample, item), 0.0)

    def test_name_mismatch(self):
        cases = [
            (
                "completely wrong name",
                {"output_tools": [_call("wrong")]},
                {"reference_tool_calls": [_ref("right")]},
                0.0,
            ),
            (
                "partial name overlap — 1 of 2 correct",
                {"output_tools": [_call("a"), _call("c")]},
                {"reference_tool_calls": [_ref("a"), _ref("b")]},
                # matched=1, max(2,2)=2, name_score=0.5 → 0.5*0.5=0.25
                0.25,
            ),
            (
                "extra actual calls — 1 of 1 expected, 2 actual",
                {"output_tools": [_call("a"), _call("b")]},
                {"reference_tool_calls": [_ref("a")]},
                # matched=1, max(1,2)=2, name_score=0.5 → 0.25
                0.25,
            ),
            (
                "missing actual calls — 1 of 2 expected",
                {"output_tools": [_call("a")]},
                {"reference_tool_calls": [_ref("a"), _ref("b")]},
                0.25,
            ),
        ]
        self._run_cases(cases)

    def test_argument_scoring(self):
        cases = [
            (
                "names match, args completely wrong",
                {"output_tools": [_call("f", {"a": 1})]},
                {"reference_tool_calls": [_ref("f", {"a": 2})]},
                # name_score=1.0, arg_score=0.0 → 0.5
                0.5,
            ),
            (
                "names match, args partially correct",
                {"output_tools": [_call("f", {"a": 1, "b": 99})]},
                {"reference_tool_calls": [_ref("f", {"a": 1, "b": 2})]},
                # 1 of 2 leaves match → avg=0.5 → 0.5+0.4*0.5=0.7
                0.7,
            ),
            (
                "names match, missing arg key",
                {"output_tools": [_call("f", {"a": 1})]},
                {"reference_tool_calls": [_ref("f", {"a": 1, "b": 2})]},
                # a matches (1,1), b missing (0,1) → 1/2=0.5 → 0.7
                0.7,
            ),
            (
                "names match, empty args vs expected args",
                {"output_tools": [_call("f", {})]},
                {"reference_tool_calls": [_ref("f", {"a": 1})]},
                0.5,
            ),
            (
                "names match, both empty args",
                {"output_tools": [_call("f", {})]},
                {"reference_tool_calls": [_ref("f", {})]},
                0.9,
            ),
        ]
        self._run_cases(cases)

    def test_nested_arguments(self):
        cases = [
            (
                "nested dict — all match",
                {"output_tools": [_call("f", {"a": {"x": 1, "y": 2}})]},
                {"reference_tool_calls": [_ref("f", {"a": {"x": 1, "y": 2}})]},
                0.9,
            ),
            (
                "nested dict — partial match",
                {"output_tools": [_call("f", {"a": {"x": 1, "y": 9}})]},
                {"reference_tool_calls": [_ref("f", {"a": {"x": 1, "y": 2}})]},
                # 1 of 2 leaves → avg=0.5 → 0.7
                0.7,
            ),
            (
                "list argument — all match",
                {"output_tools": [_call("f", {"ids": [1, 2, 3]})]},
                {"reference_tool_calls": [_ref("f", {"ids": [1, 2, 3]})]},
                0.9,
            ),
            (
                "list argument — partial match",
                {"output_tools": [_call("f", {"ids": [1, 9, 3]})]},
                {"reference_tool_calls": [_ref("f", {"ids": [1, 2, 3]})]},
                # 2 of 3 list items match → avg=2/3 → 0.5+0.4*(2/3)≈0.77
                0.77,
            ),
            (
                "list shorter than expected",
                {"output_tools": [_call("f", {"ids": [1]})]},
                {"reference_tool_calls": [_ref("f", {"ids": [1, 2, 3]})]},
                # 1 of 3 → avg=1/3 → 0.5+0.4*(1/3)≈0.63
                0.63,
            ),
        ]
        self._run_cases(cases)

    def test_duplicate_tool_names(self):
        """Two calls with the same name should be matched independently."""
        actual = [_call("search", {"q": "a"}), _call("search", {"q": "b"})]
        expected = [_ref("search", {"q": "a"}), _ref("search", {"q": "b"})]
        self.assertAlmostEqual(grade_tool_calls(actual, expected), 0.9)

    def test_duplicate_names_wrong_args(self):
        actual = [_call("search", {"q": "a"}), _call("search", {"q": "wrong"})]
        expected = [_ref("search", {"q": "a"}), _ref("search", {"q": "b"})]
        # first "search" matched greedily: a→a (1.0), then wrong→b (0.0)
        # avg_arg = 0.5 → 0.5+0.4*0.5=0.7
        self.assertAlmostEqual(grade_tool_calls(actual, expected), 0.7)

    def test_include_tools_filters_to_subset(self):
        """Only the tool names in include_tools are graded; others are ignored."""
        sample = {"output_tools": [_call("a", {"x": 1}), _call("b", {"y": 2})]}
        item = {"reference_tool_calls": [_ref("a", {"x": 1}), _ref("b", {"y": 99})]}
        config = GraderConfig()
        config.include_tools = ["a"]
        # Only "a" is compared: perfect match → 0.9
        self.assertAlmostEqual(grade_with_config(sample, item, config), 0.9)

    def test_include_tools_no_match_in_filter(self):
        """When include_tools filters out everything, both sides are empty → 0.9."""
        sample = {"output_tools": [_call("a", {"x": 1})]}
        item = {"reference_tool_calls": [_ref("a", {"x": 1})]}
        config = GraderConfig()
        config.include_tools = ["z"]
        self.assertAlmostEqual(grade_with_config(sample, item, config), 0.9)

    def test_include_tools_missing_actual(self):
        """Included tool exists in expected but not in actual → 0.0."""
        sample = {"output_tools": [_call("a", {"x": 1})]}
        item = {"reference_tool_calls": [_ref("a", {"x": 1}), _ref("b", {"y": 2})]}
        config = GraderConfig()
        config.include_tools = ["b"]
        self.assertAlmostEqual(grade_with_config(sample, item, config), 0.0)

    def test_include_tools_empty_means_grade_all(self):
        """Empty include_tools grades all calls (default behavior)."""
        sample = {"output_tools": [_call("a", {"x": 1}), _call("b", {"y": 2})]}
        item = {"reference_tool_calls": [_ref("a", {"x": 1}), _ref("b", {"y": 2})]}
        config = GraderConfig()
        config.include_tools = []
        self.assertAlmostEqual(grade_with_config(sample, item, config), 0.9)


class TestGradeText(unittest.TestCase):

    def test_identical_texts(self):
        self.assertAlmostEqual(grade_text("hello world", "hello world"), 1.0)

    def test_completely_different(self):
        self.assertAlmostEqual(grade_text("foo bar", "baz qux"), 0.0)

    def test_partial_overlap(self):
        score = grade_text(
            "Your order has been cancelled successfully",
            "Your order was cancelled",
        )
        self.assertGreater(score, 0.5)
        self.assertLess(score, 1.0)

    def test_empty_actual(self):
        # rouge_scorer returns 0.0 when hypothesis is empty
        self.assertAlmostEqual(grade_text("", "some reference"), 0.0)

    def test_empty_reference(self):
        self.assertAlmostEqual(grade_text("some output", ""), 0.0)


class TestCombinedGrade(unittest.TestCase):

    def test_perfect_tools_and_text(self):
        sample = {
            "output_tools": [_call("search", {"q": "hello"})],
            "output_text": "Order cancelled successfully",
        }
        item = {
            "reference_tool_calls": [_ref("search", {"q": "hello"})],
            "reference_response": "Order cancelled successfully",
        }
        score = _grade_all(sample, item)
        # tool_score=0.9, text_score=1.0 → 0.9 + 0.1*1.0 = 1.0
        self.assertAlmostEqual(score, 1.0)

    def test_perfect_tools_no_text(self):
        sample = {"output_tools": [_call("search", {"q": "hello"})]}
        item = {"reference_tool_calls": [_ref("search", {"q": "hello"})]}
        score = _grade_all(sample, item)
        # tool_score=0.9, no text → 0.9
        self.assertAlmostEqual(score, 0.9)

    def test_perfect_tools_partial_text(self):
        sample = {
            "output_tools": [_call("search", {"q": "hello"})],
            "output_text": "Your order was cancelled",
        }
        item = {
            "reference_tool_calls": [_ref("search", {"q": "hello"})],
            "reference_response": "Your order has been cancelled successfully",
        }
        score = _grade_all(sample, item)
        # tool_score=0.9, text_score>0 → score > 0.9
        self.assertGreater(score, 0.9)
        self.assertLessEqual(score, 1.0)

    def test_no_tools_with_text(self):
        sample = {
            "output_tools": [],
            "output_text": "Order cancelled successfully",
        }
        item = {
            "reference_tool_calls": [_ref("search", {"q": "hello"})],
            "reference_response": "Order cancelled successfully",
        }
        score = _grade_all(sample, item)
        # tool_score=0.0, text_score=1.0 → 0.0 + 0.1 = 0.1
        self.assertAlmostEqual(score, 0.1)


if __name__ == "__main__":
    unittest.main()
