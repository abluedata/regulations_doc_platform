"""Build a deterministic FR-07 contract run from the locked QA gold set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic grounded-QA contract run.")
    parser.add_argument("--gold-file", default="backend/eval/gold/qa/review_qa_v1.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    gold = json.loads(Path(args.gold_file).read_text(encoding="utf-8"))
    answers = []
    for case in gold["cases"]:
        if not case["answerable"]:
            answers.append({
                "question_id": case["question_id"], "answer": "当前文档未提供足够依据，无法可靠回答该问题。",
                "refused": True, "citations": [], "events": ["meta", "status", "done"],
            })
            continue
        block = case["blocks"][0]
        fact = case["required_facts"][0]
        start = block["text"].index(fact)
        answers.append({
            "question_id": case["question_id"], "answer": f"根据当前文档，{fact}。", "refused": False,
            "citations": [{
                "document_id": case["document_id"], "document_version_id": case["document_version_id"],
                "block_id": block["block_id"], "quote": fact, "quote_start": start, "quote_end": start + len(fact),
                "locator": block["locator"],
            }],
            "events": ["meta", "status", "token", "done"],
        })
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema_version": 1, "run_kind": "deterministic_contract_fixture",
        "gold_dataset_sha256": gold["dataset_sha256"], "answers": answers,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(answers)} QA fixture answers to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
