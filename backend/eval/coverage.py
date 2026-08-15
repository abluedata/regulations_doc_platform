"""Rule execution coverage and refusal metrics."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:  # pragma: no cover
    from .metric_calculator import load_gold_dataset
except ImportError:  # pragma: no cover
    from metric_calculator import load_gold_dataset


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _extract_documents(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        documents = payload.get("documents")
        if isinstance(documents, list):
            return [item for item in documents if isinstance(item, Mapping)]
    return []


def _extract_answers(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        answers = payload.get("answers") or payload.get("qa")
        if isinstance(answers, list):
            return [item for item in answers if isinstance(item, Mapping)]
        collected: list[Mapping[str, Any]] = []
        for document in _extract_documents(payload):
            doc_answers = document.get("answers")
            if isinstance(doc_answers, list):
                collected.extend(item for item in doc_answers if isinstance(item, Mapping))
        return collected
    return []


def calculate_coverage(
    gold_dir: str | Path,
    run_payload: Any,
    *,
    verify_manifest: bool = True,
) -> dict[str, Any]:
    gold = load_gold_dataset(gold_dir, verify_manifest=verify_manifest)
    run_by_doc = {
        str(document.get("doc_id") or document.get("document_id")): document
        for document in _extract_documents(run_payload)
    }
    per_document = []
    total_enabled = 0
    total_executed = 0
    for document in gold["documents"]:
        doc_id = str(document["doc_id"])
        enabled_rules = {str(rule_id) for rule_id in document.get("enabled_rules", [])}
        executed_rules = {
            str(rule_id)
            for rule_id in (run_by_doc.get(doc_id, {}).get("executed_rules") or [])
        }
        executed_enabled = enabled_rules & executed_rules
        coverage = len(executed_enabled) / len(enabled_rules) if enabled_rules else 1.0
        total_enabled += len(enabled_rules)
        total_executed += len(executed_enabled)
        per_document.append(
            {
                "doc_id": doc_id,
                "doc_type": document.get("doc_type", "unknown"),
                "enabled_rules": len(enabled_rules),
                "executed_rules": len(executed_enabled),
                "missing_rules": sorted(enabled_rules - executed_rules),
                "coverage": coverage,
                "status": "complete" if coverage == 1.0 else "complete_degraded",
            }
        )

    overall_coverage = total_executed / total_enabled if total_enabled else 1.0
    answers_by_id = {
        str(answer.get("question_id") or answer.get("id")): answer for answer in _extract_answers(run_payload)
    }
    refusal_total = 0
    correct_refusals = 0
    false_refusals = 0
    missed_refusals = 0
    total_questions = 0
    correct_answerability = 0
    for question in gold["refusal_questions"]:
        question_id = str(question.get("question_id") or question.get("id"))
        expected_refusal = bool(question.get("expected_refusal", not question.get("answerable", True)))
        predicted_refusal = bool(answers_by_id.get(question_id, {}).get("refused", False))
        total_questions += 1
        if predicted_refusal == expected_refusal:
            correct_answerability += 1
        if expected_refusal:
            refusal_total += 1
            if predicted_refusal:
                correct_refusals += 1
            else:
                missed_refusals += 1
        elif predicted_refusal:
            false_refusals += 1

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_dataset_sha256": (gold["manifest"] or {}).get("dataset_sha256"),
        "rule_coverage": {
            "enabled_rule_executions": total_enabled,
            "executed_rule_executions": total_executed,
            "coverage": overall_coverage,
            "status": "complete" if overall_coverage == 1.0 else "complete_degraded",
            "per_document": per_document,
        },
        "refusal": {
            "gold_no_answer_questions": refusal_total,
            "correct_refusals": correct_refusals,
            "missed_refusals": missed_refusals,
            "false_refusals": false_refusals,
            "refusal_accuracy": correct_refusals / refusal_total if refusal_total else 0.0,
            "answerability_accuracy": correct_answerability / total_questions if total_questions else 0.0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate rule coverage and refusal metrics.")
    parser.add_argument("--gold-dir", required=True)
    parser.add_argument("--run-file", required=True)
    parser.add_argument("--output")
    parser.add_argument("--no-verify-manifest", action="store_true")
    args = parser.parse_args(argv)
    report = calculate_coverage(
        args.gold_dir,
        _read_json(args.run_file),
        verify_manifest=not args.no_verify_manifest,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

