from __future__ import annotations

import json
from pathlib import Path

from eval.qa_metrics import calculate_qa_metrics


def test_calculates_grounding_refusal_and_terminal_metrics(tmp_path: Path):
    gold = {
        "dataset_id": "qa-test", "dataset_sha256": "test",
        "cases": [
            {"question_id": "q1", "answerable": True, "required_facts": ["三十日"],
             "document_id": "d1", "document_version_id": "v1",
             "blocks": [{"block_id": "b1", "text": "应在三十日内付款。", "locator": {"kind": "pdf", "page_number": 1}}]},
            {"question_id": "q2", "answerable": False, "required_facts": [],
             "document_id": "d1", "document_version_id": "v1", "blocks": []},
        ],
    }
    run = {"answers": [
        {"question_id": "q1", "answer": "付款期限为三十日。", "refused": False,
         "citations": [{"document_id": "d1", "document_version_id": "v1", "block_id": "b1",
                         "quote": "三十日内付款", "quote_start": 2, "quote_end": 8,
                         "locator": {"kind": "pdf", "page_number": 1}}],
         "events": ["meta", "token", "done"]},
        {"question_id": "q2", "answer": "依据不足", "refused": True, "citations": [],
         "events": ["meta", "done"]},
    ]}
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
    report = calculate_qa_metrics(path, run, verify_hash=False)

    assert report["answer_accuracy"] == 1.0
    assert report["citation_exact_match_rate"] == 1.0
    assert report["citation_location_accuracy"] == 1.0
    assert report["refusal_rate"] == 0.5
    assert report["refusal_correct_rate"] == 1.0
    assert report["sse_unique_terminal_rate"] == 1.0
    assert report["passed"] is True
