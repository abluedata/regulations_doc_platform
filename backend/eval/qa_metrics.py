"""Deterministic metrics for document-scoped review QA."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


TERMINALS = {"done", "error"}


def _dataset_hash(cases: list[dict[str, Any]]) -> str:
    payload = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rate(numerator: int, denominator: int, *, empty: float = 0.0) -> float:
    return numerator / denominator if denominator else empty


def calculate_qa_metrics(gold_file: str | Path, run_payload: Mapping[str, Any], *, verify_hash: bool = True) -> dict[str, Any]:
    gold = json.loads(Path(gold_file).read_text(encoding="utf-8"))
    cases = [dict(item) for item in gold.get("cases", [])]
    actual_hash = _dataset_hash(cases)
    if verify_hash and gold.get("dataset_sha256") != actual_hash:
        raise ValueError("QA gold dataset SHA-256 mismatch")
    answers = {str(item.get("question_id")): item for item in run_payload.get("answers", [])}

    answerable = correct_answers = expected_refusals = correct_refusals = false_refusals = 0
    refusal_count = total_citations = exact_citations = located_citations = grounded_answers = answered = 0
    terminal_ok = 0
    case_results = []
    for case in cases:
        answer = answers.get(str(case["question_id"]), {})
        refused = bool(answer.get("refused"))
        citations = answer.get("citations") if isinstance(answer.get("citations"), list) else []
        failures: list[str] = []
        events = [str(event.get("event")) if isinstance(event, Mapping) else str(event) for event in answer.get("events", [])]
        if len([event for event in events if event in TERMINALS]) == 1 and events and events[-1] in TERMINALS:
            terminal_ok += 1
        else:
            failures.append("invalid_terminal_count")

        if case.get("answerable"):
            answerable += 1
            if refused:
                false_refusals += 1
                failures.append("false_refusal")
            else:
                answered += 1
                text = str(answer.get("answer") or "")
                if all(str(fact) in text for fact in case.get("required_facts", [])):
                    correct_answers += 1
                else:
                    failures.append("answer_fact_mismatch")
                if citations:
                    grounded_answers += 1
                else:
                    failures.append("missing_citation")
        else:
            expected_refusals += 1
            if refused:
                correct_refusals += 1
            else:
                failures.append("missed_refusal")
        if refused:
            refusal_count += 1

        blocks = {str(block.get("block_id")): block for block in case.get("blocks", [])}
        for citation in citations:
            total_citations += 1
            block = blocks.get(str(citation.get("block_id")))
            canonical = str((block or {}).get("text") or "")
            start, end = citation.get("quote_start"), citation.get("quote_end")
            exact = (
                block is not None and citation.get("document_id") == case.get("document_id")
                and citation.get("document_version_id") == case.get("document_version_id")
                and isinstance(start, int) and isinstance(end, int)
                and citation.get("quote") == canonical[start:end]
            )
            if exact:
                exact_citations += 1
            else:
                failures.append("quote_mismatch")
            if exact and citation.get("locator") == block.get("locator"):
                located_citations += 1
            else:
                failures.append("locator_mismatch")
        case_results.append({"question_id": case["question_id"], "passed": not failures, "failures": sorted(set(failures))})

    total = len(cases)
    report = {
        "schema_version": 1, "dataset_id": gold.get("dataset_id"), "dataset_sha256": actual_hash,
        "case_count": total, "answerable_count": answerable, "expected_refusal_count": expected_refusals,
        "answer_accuracy": _rate(correct_answers, answerable),
        "citation_exact_match_rate": _rate(exact_citations, total_citations, empty=1.0),
        "citation_location_accuracy": _rate(located_citations, total_citations, empty=1.0),
        "refusal_rate": _rate(refusal_count, total),
        "refusal_correct_rate": _rate(correct_refusals, expected_refusals, empty=1.0),
        "false_refusal_rate": _rate(false_refusals, answerable),
        "non_refusal_citation_coverage": _rate(grounded_answers, answered, empty=1.0),
        "sse_unique_terminal_rate": _rate(terminal_ok, total),
        "counts": {
            "correct_answers": correct_answers, "total_citations": total_citations,
            "exact_citations": exact_citations, "located_citations": located_citations,
            "correct_refusals": correct_refusals, "false_refusals": false_refusals,
            "unique_terminal_requests": terminal_ok,
        },
        "cases": case_results,
    }
    report["passed"] = (
        report["answer_accuracy"] >= 0.90 and report["citation_exact_match_rate"] == 1.0
        and report["citation_location_accuracy"] >= 0.95 and report["refusal_correct_rate"] >= 0.95
        and report["false_refusal_rate"] <= 0.05 and report["non_refusal_citation_coverage"] == 1.0
        and report["sse_unique_terminal_rate"] == 1.0
    )
    return report


__all__ = ["calculate_qa_metrics"]
