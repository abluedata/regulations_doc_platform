from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval.calibration import calculate_calibration
from eval.coverage import calculate_coverage
from eval.issue_associator import associate_issues
from eval.metric_calculator import calculate_metrics, dataset_sha256, file_sha256
from eval.regression import evaluate_regression


def write_gold_fixture(root: Path) -> Path:
    gold_dir = root / "gold"
    gold_dir.mkdir()
    documents = [
        {
            "schema_version": 1,
            "doc_id": "doc-a",
            "doc_type": "termination_agreement",
            "enabled_rules": ["notice_missing", "severance_underpayment"],
            "annotation": {"annotator": "a", "reviewer": "b"},
            "issues": [
                {
                    "issue_id": "g1",
                    "rule_id": "notice_missing",
                    "severity": "high",
                    "text": "协议未写明三十日通知或代通知金。",
                },
                {
                    "issue_id": "g2",
                    "rule_id": "severance_underpayment",
                    "severity": "high",
                    "text": "补偿金低于法定标准。",
                },
            ],
            "refusal_questions": [
                {
                    "question_id": "q-no-answer",
                    "question": "员工上一家公司的薪资是多少？",
                    "answerable": False,
                    "expected_refusal": True,
                },
                {
                    "question_id": "q-answerable",
                    "question": "协议是否约定补偿金？",
                    "answerable": True,
                    "expected_refusal": False,
                },
            ],
        },
        {
            "schema_version": 1,
            "doc_id": "doc-b",
            "doc_type": "termination_agreement",
            "enabled_rules": ["notice_missing"],
            "annotation": {"annotator": "a", "reviewer": "b"},
            "issues": [
                {
                    "issue_id": "g3",
                    "rule_id": "notice_missing",
                    "severity": "medium",
                    "text": "通知条款表述不清。",
                }
            ],
            "refusal_questions": [],
        },
    ]
    entries = []
    for document in documents:
        path = gold_dir / f"{document['doc_id']}.json"
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        entries.append({"path": path.name, "doc_id": document["doc_id"], "sha256": file_sha256(path)})
    manifest = {
        "schema_version": 1,
        "dataset_id": "test",
        "min_documents": 2,
        "documents": entries,
        "dataset_sha256": dataset_sha256(entries),
    }
    (gold_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return gold_dir


class EvalMetricsTests(unittest.TestCase):
    def test_association_requires_rule_severity_and_doc_type(self):
        result = associate_issues(
            [
                {
                    "doc_id": "d1",
                    "doc_type": "termination_agreement",
                    "rule_id": "notice_missing",
                    "severity": "high",
                    "text": "未提前三十日通知",
                }
            ],
            [
                {
                    "doc_id": "d1",
                    "doc_type": "termination_agreement",
                    "rule_id": "notice_missing",
                    "severity": "medium",
                    "text": "未提前三十日通知",
                }
            ],
        )

        self.assertEqual(0, result.true_positive_count)
        self.assertEqual(1, result.false_positive_count)
        self.assertEqual(1, result.false_negative_count)

    def test_metrics_emit_stratified_matrix_and_fp_fn_lists(self):
        with tempfile.TemporaryDirectory() as temp_name:
            gold_dir = write_gold_fixture(Path(temp_name))
            predictions = [
                {
                    "doc_id": "doc-a",
                    "rule_id": "notice_missing",
                    "severity": "high",
                    "text": "协议未写明三十日通知或代通知金。",
                    "confidence": 0.91,
                },
                {
                    "doc_id": "doc-b",
                    "rule_id": "notice_missing",
                    "severity": "high",
                    "text": "通知条款表述不清。",
                    "confidence": 0.77,
                },
                {
                    "doc_id": "doc-a",
                    "rule_id": "non_compete_overbroad",
                    "severity": "medium",
                    "text": "额外竞业限制。",
                    "confidence": 0.63,
                },
            ]

            report = calculate_metrics(gold_dir, predictions)

        self.assertEqual({"tp": 1, "fp": 2, "fn": 2}, {k: report["overall"][k] for k in ("tp", "fp", "fn")})
        high_notice = [
            row
            for row in report["confusion_matrix"]
            if row["rule_id"] == "notice_missing" and row["severity"] == "high"
        ][0]
        self.assertEqual(1, high_notice["tp"])
        self.assertEqual(1, high_notice["fp"])
        self.assertEqual(2, len(report["false_positives"]))
        self.assertEqual(2, len(report["false_negatives"]))

    def test_calibration_uses_prediction_buckets_actual_precision(self):
        with tempfile.TemporaryDirectory() as temp_name:
            gold_dir = write_gold_fixture(Path(temp_name))
            report = calculate_calibration(
                gold_dir,
                [
                    {
                        "doc_id": "doc-a",
                        "rule_id": "notice_missing",
                        "severity": "high",
                        "text": "协议未写明三十日通知或代通知金。",
                        "confidence": 0.91,
                    },
                    {
                        "doc_id": "doc-a",
                        "rule_id": "non_compete_overbroad",
                        "severity": "medium",
                        "text": "额外竞业限制。",
                        "confidence": 0.63,
                    },
                ],
            )

        by_bucket = {row["bucket"]: row for row in report["calibration"]}
        self.assertEqual(1.0, by_bucket["0.85-0.95"]["actual_precision"])
        self.assertEqual(0.0, by_bucket["0.50-0.70"]["actual_precision"])

    def test_regression_blocks_drop_over_two_points(self):
        baseline = {
            "overall": {"precision": 0.90, "recall": 0.91},
            "by_severity": {"high": {"precision": 0.88, "recall": 0.93}},
        }
        current = {
            "overall": {"precision": 0.89, "recall": 0.90},
            "by_severity": {"high": {"precision": 0.87, "recall": 0.90}},
        }

        report = evaluate_regression(baseline, current, max_drop_pp=2.0)

        self.assertFalse(report["passed"])
        self.assertEqual("by_severity.high", report["blocking_drops"][0]["series"])

    def test_coverage_and_refusal_metrics(self):
        with tempfile.TemporaryDirectory() as temp_name:
            gold_dir = write_gold_fixture(Path(temp_name))
            report = calculate_coverage(
                gold_dir,
                {
                    "documents": [
                        {"doc_id": "doc-a", "executed_rules": ["notice_missing"]},
                        {"doc_id": "doc-b", "executed_rules": ["notice_missing"]},
                    ],
                    "answers": [
                        {"question_id": "q-no-answer", "refused": True},
                        {"question_id": "q-answerable", "refused": False},
                    ],
                },
            )

        self.assertEqual("complete_degraded", report["rule_coverage"]["status"])
        self.assertAlmostEqual(2 / 3, report["rule_coverage"]["coverage"])
        self.assertEqual(1.0, report["refusal"]["refusal_accuracy"])
        self.assertEqual(1.0, report["refusal"]["answerability_accuracy"])


if __name__ == "__main__":
    unittest.main()

