"""Unit tests for deterministic review matchers and false-positive filters."""

from decimal import Decimal
import unittest

from services.review.anti_fp import (
    false_positive_reason,
    filter_false_positives,
    is_false_positive,
    partition_false_positives,
)
from services.review.matchers import (
    match_keyword,
    match_numeric,
    match_regex,
    match_rule,
    match_scope,
)


BLOCKS = [
    {
        "block_id": "b1",
        "type": "heading",
        "section_path": ["五、责任限制"],
        "text": "五、责任限制",
    },
    {
        "block_id": "b2",
        "type": "paragraph",
        "section_path": ["五、责任限制"],
        "text": "甲方累计责任上限为人民币500万元。",
    },
    {
        "block_id": "b3",
        "type": "paragraph",
        "section_path": ["五、责任限制"],
        "text": "任何一方均不承担间接损失。",
    },
    {
        "block_id": "b4",
        "type": "heading",
        "section_path": ["六、通知"],
        "text": "六、通知",
    },
    {
        "block_id": "b5",
        "type": "paragraph",
        "section_path": ["六、通知"],
        "text": "解除合同应提前30天书面通知。",
    },
]


class KeywordMatcherTests(unittest.TestCase):
    def test_matches_literal_case_insensitively_and_preserves_quote(self):
        hits = match_keyword("Aggregate LIABILITY applies", "aggregate liability")

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].quote, "Aggregate LIABILITY")
        self.assertEqual((hits[0].start, hits[0].end), (0, 19))

    def test_treats_regex_metacharacters_as_literal(self):
        hits = match_keyword("费用为 C++ 服务费", "C++")

        self.assertEqual([hit.quote for hit in hits], ["C++"])

    def test_whole_word_does_not_match_inside_identifier(self):
        self.assertEqual(match_keyword("prepayment", "payment", whole_word=True), [])
        self.assertEqual(len(match_keyword("make payment", "payment", whole_word=True)), 1)


class RegexMatcherTests(unittest.TestCase):
    def test_matches_each_occurrence_and_captures_named_groups(self):
        hits = match_regex("提前30天，最迟45天", r"(?P<days>\d+)\s*天")

        self.assertEqual([hit.quote for hit in hits], ["30天", "45天"])
        self.assertEqual(hits[0].details["groups"], {"days": "30"})

    def test_invalid_regex_has_clear_validation_error(self):
        with self.assertRaisesRegex(ValueError, "invalid regex pattern"):
            match_regex("text", "(")

    def test_skips_zero_width_matches(self):
        self.assertEqual(match_regex("abc", r"^"), [])


class ScopeMatcherTests(unittest.TestCase):
    def test_selects_matching_section_path(self):
        selected = match_scope(BLOCKS, {"section_match": "责任限制"})

        self.assertEqual([block["block_id"] for _, block in selected], ["b1", "b2", "b3"])

    def test_window_includes_blocks_after_a_heading_anchor(self):
        blocks = [
            {"block_id": "h", "type": "heading", "text": "赔偿", "section_path": []},
            {"block_id": "p1", "type": "paragraph", "text": "第一段", "section_path": []},
            {"block_id": "p2", "type": "paragraph", "text": "第二段", "section_path": []},
        ]

        selected = match_scope(blocks, {"section_match": "赔偿", "window_blocks": 1})

        self.assertEqual([block["block_id"] for _, block in selected], ["h", "p1"])

    def test_window_does_not_leak_past_the_next_heading(self):
        selected = match_scope(
            BLOCKS, {"section_match": "责任限制", "window_blocks": 10}
        )

        self.assertEqual([block["block_id"] for _, block in selected], ["b1", "b2", "b3"])

    def test_rejects_negative_window(self):
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            match_scope(BLOCKS, {"section_match": "责任", "window_blocks": -1})


class NumericMatcherTests(unittest.TestCase):
    def test_converts_chinese_money_scale_and_compares_absolute_threshold(self):
        result = match_numeric(
            "累计责任上限为人民币500万元",
            {"unit": "cny", "compare": "gt", "threshold": 4_000_000},
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.hits[0].value, Decimal("5000000"))
        self.assertEqual(result.hits[0].unit, "cny")

    def test_resolves_context_threshold_reference(self):
        result = match_numeric(
            "责任限额为$5,000,000 USD",
            {"unit": "usd", "compare": "gte", "threshold_ref": "contract_value"},
            context={"contract_value": "5,000,000"},
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.hits[0].value, Decimal("5000000"))

    def test_missing_threshold_reference_is_indeterminate(self):
        result = match_numeric(
            "提前30天通知",
            {"unit": "day", "compare": "lt", "threshold_ref": "notice_days"},
        )

        self.assertEqual(result.status, "indeterminate")
        self.assertIn("notice_days", result.reason or "")

    def test_wrong_unit_does_not_match(self):
        result = match_numeric(
            "补偿期限为12个月",
            {"unit": "day", "compare": "gt", "threshold": 10},
        )

        self.assertEqual(result.status, "no_match")

    def test_requires_supported_comparator(self):
        with self.assertRaisesRegex(ValueError, "numeric.compare"):
            match_numeric("30天", {"unit": "day", "compare": "ne", "threshold": 10})


class RulePipelineTests(unittest.TestCase):
    def test_scope_text_and_numeric_conditions_compose(self):
        result = match_rule(
            BLOCKS,
            {
                "scope": {"section_match": "责任限制"},
                "text_pattern": [{"kind": "keyword", "pattern": "责任上限"}],
                "numeric": {"unit": "cny", "compare": "gt", "threshold": 1_000_000},
            },
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.hits[0].block_id, "b2")
        self.assertEqual(result.hits[0].matcher, "numeric")

    def test_text_miss_is_completed_negative_result(self):
        result = match_rule(
            BLOCKS,
            {"text_pattern": [{"kind": "keyword", "pattern": "无限责任"}]},
        )

        self.assertEqual(result.status, "no_match")

    def test_empty_matcher_is_indeterminate(self):
        result = match_rule(BLOCKS, {})

        self.assertEqual(result.status, "indeterminate")


class FalsePositiveFilterTests(unittest.TestCase):
    def test_filters_sequence_markers(self):
        for value in ("1.", "(1)", "（一）", "①", "a.", "7"):
            with self.subTest(value=value):
                self.assertEqual(false_positive_reason(value), "sequence_marker")

    def test_filters_placeholders_checkboxes_and_formatting(self):
        cases = {
            "____年__月__日": "placeholder",
            "支付金额：___元": "placeholder",
            "☐ 同意  ☐ 不同意": "checkbox_or_option",
            "口 同意  口 不同意": "checkbox_or_option",
            "------": "placeholder",
            "：": "format_marker",
        }
        for value, reason in cases.items():
            with self.subTest(value=value):
                self.assertEqual(false_positive_reason(value), reason)

    def test_filters_isolated_contract_labels_amounts_and_dates(self):
        cases = {
            "甲方（盖章）：": "standard_contract_label",
            "乙方签字：": "standard_contract_label",
            "工资发放：": "standard_contract_label",
            "人民币5,000元": "isolated_numeric_value",
            "30天": "isolated_numeric_value",
            "2026年8月15日": "isolated_date",
        }
        for value, reason in cases.items():
            with self.subTest(value=value):
                self.assertEqual(false_positive_reason(value), reason)

    def test_keeps_substantive_contract_sentences(self):
        values = (
            "甲方应于三日内支付违约金。",
            "乙方应签字确认已收到全部款项。",
            "双方约定以口头通知方式解除合同。",
            "补偿金额为人民币5,000元，低于法定标准。",
            "合同于2026年8月15日生效。",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertFalse(is_false_positive(value))

    def test_filters_mapping_candidates_without_mutating_them(self):
        candidates = [
            {"quote": "(1)", "id": "noise"},
            {"quote": "甲方应支付经济补偿。", "id": "issue"},
        ]

        kept = filter_false_positives(candidates)
        kept_partition, rejected = partition_false_positives(candidates)

        self.assertEqual(kept, [candidates[1]])
        self.assertEqual(kept_partition, kept)
        self.assertEqual(rejected, [(candidates[0], "sequence_marker")])


if __name__ == "__main__":
    unittest.main()
