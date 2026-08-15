"""Fake-LLM integration tests for the W2 review engine."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.review.engine import LLMUnavailableError, ReviewEngine
from services.review.evidence import locate_evidence, quote_sha256
from services.review.job_runner import ChunkRuleTask, ReviewJobRunner, TransientReviewError
from services.review.prompt import build_review_messages, prompt_hash


PDF_IR = {
    "doc_id": "doc-1",
    "document_version_id": "ver-1",
    "source": {"filename": "termination.pdf", "mime": "application/pdf", "pages": 1},
    "blocks": [
        {
            "block_id": "b1",
            "type": "paragraph",
            "page_start": 1,
            "text": "甲方应支付经济补偿。",
            "locator": {
                "kind": "pdf",
                "page_number": 1,
                "origin": "top_left",
                "coordinate_system": "normalized_0_1000",
                "rects": [{"x0": 100, "y0": 100, "x1": 500, "y1": 150}],
                "precision": "exact",
            },
        },
        {
            "block_id": "b2",
            "type": "paragraph",
            "page_start": 1,
            "text": "补偿金额：____元",
            "locator": {
                "kind": "pdf",
                "page_number": 1,
                "origin": "top_left",
                "coordinate_system": "normalized_0_1000",
                "rects": [{"x0": 100, "y0": 180, "x1": 400, "y1": 220}],
                "precision": "exact",
            },
        },
        {
            "block_id": "b3",
            "type": "paragraph",
            "page_start": 1,
            "text": "解除合同未约定社保补缴情形。",
            "layout_spans": [
                {
                    "text": "解除合同未约定社保补缴情形。",
                    "page_number": 1,
                    "bbox": [80, 260, 620, 300],
                }
            ],
            "locator": {
                "kind": "pdf",
                "page_number": 1,
                "origin": "top_left",
                "coordinate_system": "normalized_0_1000",
                "rects": [{"x0": 70, "y0": 250, "x1": 650, "y1": 315}],
                "precision": "exact",
            },
        },
    ],
}

DOCX_IR = {
    "doc_id": "doc-2",
    "document_version_id": "ver-2",
    "source": {"filename": "termination.docx", "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "blocks": [
        {
            "block_id": "b1",
            "type": "paragraph",
            "text": "A😀B重复条款",
            "locator": {
                "kind": "docx",
                "locator_id": "docx-p-000000",
                "container_kind": "paragraph",
                "document_order": 0,
                "block_id": "b1",
                "text_range": {"start": 0, "end": 7, "unit": "unicode_code_point"},
                "precision": "exact",
            },
        }
    ],
}

RULES = [
    {
        "rule_id": "det-compensation",
        "rule_version": "rv-det-1",
        "template_version": "tv-1",
        "name": "经济补偿",
        "risk_level": "medium",
        "matcher": {"text_pattern": [{"kind": "keyword", "pattern": "经济补偿"}]},
        "llm_fallback": False,
    },
    {
        "rule_id": "llm-social-security",
        "rule_version": "rv-llm-1",
        "template_version": "tv-1",
        "name": "社保补缴",
        "description": "识别解除协议是否遗漏社保补缴安排。",
        "risk_level": "high",
        "matcher": {"text_pattern": [{"kind": "keyword", "pattern": "不会命中"}]},
        "llm_fallback": True,
        "examples": [
            {
                "input": "协议未提及社保补缴情形。",
                "output": {
                    "issues": [
                        {
                            "type": "社保补缴",
                            "text": "未提及社保补缴情形",
                            "explanation": "缺少社保处理安排。",
                            "suggested_fix": "补充社保补缴情形与责任。",
                            "para_index": 0,
                        }
                    ]
                },
            }
        ],
    },
]


class BadThenGoodFakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(self, *, messages, model, temperature, seed, response_format=None):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "seed": seed,
                "response_format": response_format,
            }
        )
        if len(self.calls) == 1:
            return {"content": "not json", "model": "fake-provider-v1", "finish_reason": "malformed"}
        return {
            "content": json.dumps(
                {
                    "issues": [
                        {
                            "type": "社保补缴",
                            "text": "未约定社保补缴情形",
                            "explanation": "解除协议未说明社保补缴。",
                            "suggested_fix": "补充社保补缴情形、期限与责任人。",
                            "para_index": 2,
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            "model": "fake-provider-v1",
            "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            "finish_reason": "stop",
        }


class UnavailableLLM:
    def complete(self, **_kwargs):
        raise LLMUnavailableError("fake provider down")


class PromptTests(unittest.TestCase):
    def test_prompt_includes_anti_false_positive_rules_examples_and_is_hashed(self):
        messages = build_review_messages(
            chunk_id="doc-1:0000",
            blocks=PDF_IR["blocks"],
            rules=RULES,
        )
        combined = "\n".join(message["content"] for message in messages)

        self.assertIn("不确定宁可不报", combined)
        self.assertIn("社保补缴", combined)
        self.assertIn("协议未提及社保补缴情形", combined)
        self.assertEqual(len(prompt_hash(messages)), 64)


class EvidenceTests(unittest.TestCase):
    def test_pdf_locator_prefers_mineru_span_then_paragraph_bbox_and_docx_anchors(self):
        span_anchor = locate_evidence(
            PDF_IR,
            "未约定社保补缴情形",
            block_index=2,
            document_version_id="ver-1",
        )
        paragraph_anchor = locate_evidence(
            PDF_IR,
            "甲方应支付经济补偿",
            block_index=0,
            document_version_id="ver-1",
        )
        docx_anchor = locate_evidence(
            DOCX_IR,
            "😀B",
            block_index=0,
            document_version_id="ver-2",
        )

        self.assertEqual(span_anchor["fallback_level"], "mineru_layout_span")
        self.assertEqual(span_anchor["page_number"], 1)
        self.assertTrue(span_anchor["bounding_box"])
        self.assertEqual(paragraph_anchor["fallback_level"], "paragraph_bbox")
        self.assertEqual(docx_anchor["kind"], "docx")
        self.assertEqual(docx_anchor["block_id"], "b1")
        self.assertEqual(docx_anchor["text_range"], {"start": 1, "end": 3, "unit": "unicode_code_point"})
        self.assertEqual(span_anchor["quote_hash"], quote_sha256("未约定社保补缴情形"))


class ReviewEngineTests(unittest.TestCase):
    def test_engine_runs_deterministic_then_llm_with_retry_and_snapshot_metadata(self):
        fake = BadThenGoodFakeLLM()
        engine = ReviewEngine(
            llm_client=fake,
            model="fake-review-model",
            temperature=0.2,
            seed=20260815,
            eval_set_hash="eval-hash",
        )

        result = engine.analyze_document(PDF_IR, RULES)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(fake.calls), 2, "malformed structured output should retry once")
        self.assertTrue(fake.calls[0]["seed"])
        findings = result["findings"]
        self.assertEqual([finding["rule_id"] for finding in findings], ["det-compensation", "llm-social-security"])
        self.assertEqual(findings[0]["confidence"], "rule_deterministic")
        self.assertEqual(findings[1]["confidence"], "llm_yes")
        self.assertEqual(findings[1]["evidence"]["fallback_level"], "mineru_layout_span")
        self.assertEqual(result["snapshot"]["llm_model"], "fake-review-model")
        self.assertEqual(result["snapshot"]["temperature"], 0.2)
        self.assertEqual(result["snapshot"]["seed"], 20260815)
        self.assertEqual(result["snapshot"]["eval_set_hash"], "eval-hash")
        self.assertEqual(len(result["snapshot"]["prompt_hash"]), 64)
        self.assertEqual(result["snapshot"]["provider_model"], "fake-provider-v1")
        self.assertEqual(result["snapshot"]["usage"], {"prompt_tokens": 10, "completion_tokens": 8})
        self.assertEqual(result["snapshot"]["finish_reason"], "stop")


class JobRunnerTests(unittest.TestCase):
    def test_llm_unavailable_completes_degraded_with_deterministic_findings(self):
        runner = ReviewJobRunner(
            ReviewEngine(
                llm_client=UnavailableLLM(),
                model="fake-review-model",
                eval_set_hash="eval-hash",
            ),
            sleeper=lambda _seconds: None,
        )

        result = runner.run_job("job-1", [PDF_IR], RULES)

        self.assertEqual(result["status"], "complete_degraded")
        self.assertEqual([finding["rule_id"] for finding in result["findings"]], ["det-compensation"])
        self.assertEqual(result["errors"][0]["code"], "llm_unavailable")

    def test_chunk_rule_idempotency_retries_and_dead_letters_are_explicit(self):
        calls: dict[tuple[str, str], int] = {}

        def processor(task: ChunkRuleTask):
            key = (task.chunk_id, task.rule_id)
            calls[key] = calls.get(key, 0) + 1
            if task.rule_id == "dead":
                raise TransientReviewError("still failing")
            return [{"finding_id": f"{task.chunk_id}:{task.rule_id}"}]

        runner = ReviewJobRunner(sleeper=lambda _seconds: None, max_retries=2)
        ok_task = ChunkRuleTask(job_id="job-2", document_id="doc-1", chunk_id="c1", rule_id="ok")
        dead_task = ChunkRuleTask(job_id="job-2", document_id="doc-1", chunk_id="c2", rule_id="dead")

        first = runner.run_tasks("job-2", [ok_task, dead_task], processor)
        second = runner.run_tasks("job-2", [ok_task], processor)

        self.assertEqual(first["status"], "partial_failed")
        self.assertEqual(second["status"], "completed")
        self.assertEqual(calls[("c1", "ok")], 1, "successful chunk/rule work must be idempotent")
        self.assertEqual(calls[("c2", "dead")], 3, "initial try plus at most two retries")
        self.assertEqual(first["dead_letters"][0]["chunk_id"], "c2")
        self.assertEqual(first["dead_letters"][0]["rule_id"], "dead")


if __name__ == "__main__":
    unittest.main()
