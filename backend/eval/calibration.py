"""Confidence calibration for review findings."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover
    from .issue_associator import Issue, associate_issues
    from .metric_calculator import load_gold_dataset, load_prediction_file
except ImportError:  # pragma: no cover
    from issue_associator import Issue, associate_issues
    from metric_calculator import load_gold_dataset, load_prediction_file


DEFAULT_BINS: tuple[tuple[float, float], ...] = (
    (0.0, 0.5),
    (0.5, 0.7),
    (0.7, 0.85),
    (0.85, 0.95),
    (0.95, 1.000000001),
)


def _bucket_for(confidence: float | None, bins: Iterable[tuple[float, float]]) -> tuple[str, float | None, float | None]:
    if confidence is None:
        return ("missing", None, None)
    bounded = min(max(confidence, 0.0), 1.0)
    for lower, upper in bins:
        if lower <= bounded < upper:
            upper_label = 1.0 if upper > 1.0 else upper
            return (f"{lower:.2f}-{upper_label:.2f}", lower, upper_label)
    return ("missing", None, None)


def _entry(label: str, lower: float | None, upper: float | None) -> dict[str, Any]:
    return {
        "bucket": label,
        "lower": lower,
        "upper": upper,
        "predictions": 0,
        "true_positive": 0,
        "false_positive": 0,
        "actual_precision": 0.0,
    }


def calculate_calibration(
    gold_dir: str | Path,
    predictions: Iterable[Mapping[str, Any]],
    *,
    verify_manifest: bool = True,
    bins: Iterable[tuple[float, float]] = DEFAULT_BINS,
) -> dict[str, Any]:
    gold = load_gold_dataset(gold_dir, verify_manifest=verify_manifest)
    association = associate_issues(gold["issues"], predictions)
    bucket_list = tuple(bins)
    table: dict[str, dict[str, Any]] = {}

    def add_prediction(issue: Issue, *, is_true_positive: bool) -> None:
        label, lower, upper = _bucket_for(issue.confidence, bucket_list)
        table.setdefault(label, _entry(label, lower, upper))
        table[label]["predictions"] += 1
        if is_true_positive:
            table[label]["true_positive"] += 1
        else:
            table[label]["false_positive"] += 1

    for match in association.matches:
        add_prediction(match.prediction, is_true_positive=True)
    for issue in association.false_positives:
        add_prediction(issue, is_true_positive=False)

    rows = []
    for row in table.values():
        row["actual_precision"] = row["true_positive"] / row["predictions"] if row["predictions"] else 0.0
        rows.append(row)
    rows.sort(key=lambda row: (-1 if row["lower"] is None else row["lower"]))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_dataset_sha256": (gold["manifest"] or {}).get("dataset_sha256"),
        "calibration": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate confidence calibration table.")
    parser.add_argument("--gold-dir", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output")
    parser.add_argument("--no-verify-manifest", action="store_true")
    args = parser.parse_args(argv)
    report = calculate_calibration(
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

