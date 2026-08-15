"""Layered metrics for intelligent review findings."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover - exercised when called as a script
    from .issue_associator import associate_issues, issue_to_dict
except ImportError:  # pragma: no cover
    from issue_associator import associate_issues, issue_to_dict


MANIFEST_NAME = "manifest.json"


class GoldManifestError(ValueError):
    """Raised when the locked gold set manifest does not match disk."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_sha256(entries: Iterable[Mapping[str, str]]) -> str:
    normalized = [
        {"path": entry["path"], "sha256": entry["sha256"]}
        for entry in sorted(entries, key=lambda item: item["path"])
    ]
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def gold_files(gold_dir: str | Path) -> list[Path]:
    directory = Path(gold_dir)
    return sorted(
        path
        for path in directory.glob("*.json")
        if path.name != MANIFEST_NAME and not path.name.startswith("_")
    )


def verify_gold_manifest(gold_dir: str | Path) -> dict[str, Any]:
    directory = Path(gold_dir)
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.exists():
        raise GoldManifestError(f"missing gold manifest: {manifest_path}")
    manifest = _read_json(manifest_path)
    documents = manifest.get("documents")
    if not isinstance(documents, list):
        raise GoldManifestError("gold manifest must contain a documents list")

    manifest_by_path = {entry.get("path"): entry for entry in documents if isinstance(entry, Mapping)}
    actual_files = gold_files(directory)
    actual_names = {path.name for path in actual_files}
    manifest_names = set(manifest_by_path)
    missing = sorted(manifest_names - actual_names)
    extra = sorted(actual_names - manifest_names)
    if missing or extra:
        raise GoldManifestError(f"gold manifest path mismatch; missing={missing}, extra={extra}")

    for path in actual_files:
        expected = manifest_by_path[path.name].get("sha256")
        actual = file_sha256(path)
        if expected != actual:
            raise GoldManifestError(f"sha256 mismatch for {path.name}: expected {expected}, got {actual}")

    minimum = int(manifest.get("min_documents", 0))
    if len(actual_files) < minimum:
        raise GoldManifestError(f"gold set has {len(actual_files)} files, below required {minimum}")

    expected_dataset_hash = manifest.get("dataset_sha256")
    actual_dataset_hash = dataset_sha256(documents)
    if expected_dataset_hash != actual_dataset_hash:
        raise GoldManifestError(
            f"dataset sha256 mismatch: expected {expected_dataset_hash}, got {actual_dataset_hash}"
        )
    return manifest


def load_gold_dataset(gold_dir: str | Path, *, verify_manifest: bool = True) -> dict[str, Any]:
    manifest = verify_gold_manifest(gold_dir) if verify_manifest else None
    documents = [_read_json(path) for path in gold_files(gold_dir)]
    issues: list[dict[str, Any]] = []
    refusal_questions: list[dict[str, Any]] = []
    enabled_rule_pairs: list[tuple[str, str]] = []
    for document in documents:
        doc_id = str(document["doc_id"])
        doc_type = str(document.get("doc_type", "unknown"))
        for rule_id in document.get("enabled_rules", []):
            enabled_rule_pairs.append((doc_id, str(rule_id)))
        for issue in document.get("issues", []):
            normalized = dict(issue)
            normalized["doc_id"] = doc_id
            normalized["doc_type"] = doc_type
            issues.append(normalized)
        for question in document.get("refusal_questions", []):
            normalized_question = dict(question)
            normalized_question["doc_id"] = doc_id
            normalized_question["doc_type"] = doc_type
            refusal_questions.append(normalized_question)
    return {
        "manifest": manifest,
        "documents": documents,
        "issues": issues,
        "refusal_questions": refusal_questions,
        "enabled_rule_pairs": enabled_rule_pairs,
    }


def extract_findings(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("findings", "issues", "predictions"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    findings: list[dict[str, Any]] = []
    documents = payload.get("documents")
    if isinstance(documents, list):
        for document in documents:
            if not isinstance(document, Mapping):
                continue
            doc_id = document.get("doc_id") or document.get("document_id")
            doc_type = document.get("doc_type") or document.get("document_type")
            doc_findings = document.get("findings")
            if not isinstance(doc_findings, list):
                continue
            for finding in doc_findings:
                if not isinstance(finding, Mapping):
                    continue
                enriched = dict(finding)
                enriched.setdefault("doc_id", doc_id)
                enriched.setdefault("doc_type", doc_type)
                findings.append(enriched)
    return findings


def load_prediction_file(path: str | Path) -> list[dict[str, Any]]:
    return extract_findings(_read_json(Path(path)))


def load_predictions_from_jobs(jobs_dir: str | Path) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    for path in sorted(Path(jobs_dir).rglob("*.json")):
        try:
            predictions.extend(extract_findings(_read_json(path)))
        except json.JSONDecodeError:
            continue
    return predictions


def _counts_to_scores(counts: Mapping[str, int]) -> dict[str, Any]:
    tp = int(counts.get("tp", 0))
    fp = int(counts.get("fp", 0))
    fn = int(counts.get("fn", 0))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _key_dict(key: tuple[str, str, str]) -> dict[str, str]:
    rule_id, severity, doc_type = key
    return {"rule_id": rule_id, "severity": severity, "doc_type": doc_type}


def calculate_metrics(
    gold_dir: str | Path,
    predictions: Iterable[Mapping[str, Any]],
    *,
    verify_manifest: bool = True,
) -> dict[str, Any]:
    gold = load_gold_dataset(gold_dir, verify_manifest=verify_manifest)
    association = associate_issues(gold["issues"], predictions)

    buckets: Counter[tuple[str, str, str, str]] = Counter()
    severity_buckets: Counter[tuple[str, str]] = Counter()
    for match in association.matches:
        key = (match.gold.rule_id, match.gold.severity, match.gold.doc_type)
        buckets[(*key, "tp")] += 1
        severity_buckets[(match.gold.severity, "tp")] += 1
    for issue in association.false_positives:
        key = (issue.rule_id, issue.severity, issue.doc_type)
        buckets[(*key, "fp")] += 1
        severity_buckets[(issue.severity, "fp")] += 1
    for issue in association.false_negatives:
        key = (issue.rule_id, issue.severity, issue.doc_type)
        buckets[(*key, "fn")] += 1
        severity_buckets[(issue.severity, "fn")] += 1

    matrix_keys = sorted({(rule, severity, doc_type) for rule, severity, doc_type, _ in buckets})
    confusion_matrix = []
    for key in matrix_keys:
        counts = {metric: buckets.get((*key, metric), 0) for metric in ("tp", "fp", "fn")}
        confusion_matrix.append({**_key_dict(key), **_counts_to_scores(counts)})

    severities = sorted({severity for severity, _ in severity_buckets})
    by_severity = {
        severity: _counts_to_scores(
            {metric: severity_buckets.get((severity, metric), 0) for metric in ("tp", "fp", "fn")}
        )
        for severity in severities
    }

    overall = _counts_to_scores(
        {
            "tp": association.true_positive_count,
            "fp": association.false_positive_count,
            "fn": association.false_negative_count,
        }
    )
    manifest = gold["manifest"] or {}
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold": {
            "dataset_id": manifest.get("dataset_id"),
            "dataset_sha256": manifest.get("dataset_sha256"),
            "document_count": len(gold["documents"]),
            "issue_count": len(gold["issues"]),
        },
        "overall": overall,
        "by_severity": by_severity,
        "confusion_matrix": confusion_matrix,
        "false_positives": [issue_to_dict(issue) for issue in association.false_positives],
        "false_negatives": [issue_to_dict(issue) for issue in association.false_negatives],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate layered review metrics.")
    parser.add_argument("--gold-dir", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output")
    parser.add_argument("--no-verify-manifest", action="store_true")
    args = parser.parse_args(argv)

    report = calculate_metrics(
        args.gold_dir,
        load_prediction_file(args.predictions),
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

