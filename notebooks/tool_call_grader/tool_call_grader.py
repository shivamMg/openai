import json
from collections import Counter
from typing import Any, Dict, List


class GraderConfig:
    include_tools: List[str] = []
    """include_tools can be specified to grade only a subset of tool calls (by function name). Otherwise grader will grade all calls."""


def grade(sample: Dict, item: Dict) -> float:
    config = GraderConfig()
    return grade_with_config(sample, item, config)


def grade_with_config(sample: Dict, item: Dict, config: GraderConfig) -> float:
    actual_calls = sample.get("output_tools") or []
    expected_calls = item["reference_tool_calls"]

    if not actual_calls:  # just for /graders/run API, load from output_text since /graders/run API doesn't support output_tools yet
        try:
            actual_calls = json.loads(sample["output_text"])["output_tools"]
        except (KeyError, json.JSONDecodeError):
            pass

    if config.include_tools:
        actual_calls = [c for c in actual_calls if c["function"]["name"] in config.include_tools]
        expected_calls = [c for c in item["reference_tool_calls"] if c["function"]["name"] in config.include_tools]

    return grade_tool_calls(actual_calls, expected_calls)


def grade_tool_calls(actual: List[Dict], expected: List[Dict]) -> float:
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0

    actual_names = [c["function"]["name"] for c in actual]
    expected_names = [c["function"]["name"] for c in expected]

    # step 1: check tool names — partial score 0.0–0.5
    matched_count = sum((Counter(actual_names) & Counter(expected_names)).values())
    if matched_count == 0:
        return 0.0

    name_score = matched_count / max(len(expected), len(actual))
    if name_score < 1.0:
        return round(0.5 * name_score, 2)

    # step 2: all names matched — compare arguments for 0.5–1.0
    remaining = list(range(len(expected)))
    arg_scores = []
    for ai, a_name in enumerate(actual_names):
        for ei in remaining:
            if a_name == expected_names[ei]:
                a_args = json.loads(actual[ai]["function"]["arguments"])
                e_args = expected[ei]["function"]["arguments"]
                arg_scores.append(_compare_args(a_args, e_args))
                remaining.remove(ei)
                break

    avg_arg_score = sum(arg_scores) / len(arg_scores)
    return round(0.5 + 0.5 * avg_arg_score, 2)


def _compare_args(actual: Any, expected: Any) -> float:
    """Return 0.0-1.0 reflecting leaf-level match ratio."""
    matched, total = _count_leaves(actual, expected)
    return matched / total if total else 1.0


def _count_leaves(actual: Any, expected: Any) -> tuple[int, int]:
    """Recursively compare two structures; return (matched_leaves, total_leaves)."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return 0, _leaf_count(expected)
        matched = total = 0
        for key in expected:
            if key in actual:
                m, t = _count_leaves(actual[key], expected[key])
            else:
                m, t = 0, _leaf_count(expected[key])
            matched += m
            total += t
        return matched, total

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return 0, max(len(expected), 1)
        matched = total = 0
        for i, exp_item in enumerate(expected):
            if i < len(actual):
                m, t = _count_leaves(actual[i], exp_item)
            else:
                m, t = 0, 1
            matched += m
            total += t
        return matched, total

    return (1, 1) if actual == expected else (0, 1)


def _leaf_count(v: Any) -> int:
    """Count the number of leaf nodes in a nested structure."""
    if isinstance(v, dict):
        return sum(_leaf_count(val) for val in v.values()) if v else 1
    if isinstance(v, list):
        return sum(_leaf_count(item) for item in v) if v else 1
    return 1
