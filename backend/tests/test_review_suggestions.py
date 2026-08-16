"""Tests for model-generated revision suggestions over deterministic findings."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.review.suggestions import generate_suggestions


def _finding(finding_id: str, title: str, quote: str) -> dict:
    return {
        "finding_id": finding_id,
        "title": title,
        "rule_id": f"rule-{finding_id}",
        "quote": quote,
        "explanation": f"{title}说明",
        "suggested_fix": "规则静态建议",
    }


class SuggestionsTests(unittest.TestCase):
    def test_model_suggestions_replace_static_text(self) -> None:
        findings = [_finding("f1", "投标保证金条款", "投标保证金"), _finding("f2", "质保金条款", "质保金")]

        def fake_llm(messages):
            self.assertIn("投标保证金", json.dumps(messages, ensure_ascii=False))
            return json.dumps(
                {
                    "items": [
                        {"finding_id": "f1", "suggestion": "建议明确投标保证金金额与退还条件。"},
                        {"finding_id": "f2", "suggestion": "建议明确质保金比例与退还时间。"},
                    ]
                },
                ensure_ascii=False,
            )

        enriched = generate_suggestions(findings, llm=fake_llm)

        self.assertEqual(enriched[0]["suggested_fix"], "建议明确投标保证金金额与退还条件。")
        self.assertEqual(enriched[0]["suggestion_source"], "model")
        self.assertEqual(enriched[1]["suggested_fix"], "建议明确质保金比例与退还时间。")
        self.assertEqual(enriched[1]["suggestion_source"], "model")

    def test_model_failure_keeps_rule_authored_suggestions(self) -> None:
        findings = [_finding("f1", "投标保证金条款", "投标保证金")]

        def broken_llm(_messages):
            raise RuntimeError("model down")

        enriched = generate_suggestions(findings, llm=broken_llm)

        self.assertEqual(enriched[0]["suggested_fix"], "规则静态建议")
        self.assertEqual(enriched[0]["suggestion_source"], "rule")

    def test_malformed_payload_degrades_without_losing_findings(self) -> None:
        findings = [_finding("f1", "投标保证金条款", "投标保证金")]

        def bad_json_llm(_messages):
            return "这不是JSON"

        enriched = generate_suggestions(findings, llm=bad_json_llm)

        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0]["suggested_fix"], "规则静态建议")
        self.assertEqual(enriched[0]["suggestion_source"], "rule")


if __name__ == "__main__":
    unittest.main()
