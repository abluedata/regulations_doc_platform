"""Regression gate for review evaluation reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_GATED_METRICS: tuple[tuple[str, str], ...] = (
    ("overall", "precision"),
    ("overall", "recall"),
    ("by_severity.high", "precision"),
    ("by_severity.high", "recall"),
)


def _read_report(report_or_path: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(report_or_path, Mapping):
        return report_or_path
    return json.loads(Path(report_or_path).read_text(encoding="utf-8"))


def _get_path(report: Mapping[str, Any], path: str) -> Any:
    value: Any = report
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def evaluate_regression(
    baseline_report: Mapping[str, Any] | str | Path,
    current_report: Mapping[str, Any] | str | Path,
    *,
    max_drop_pp: float = 2.0,
    gated_metrics: tuple[tuple[str, str], ...] = DEFAULT_GATED_METRICS,
) -> dict[str, Any]:
    baseline = _read_report(baseline_report)
    current = _read_report(current_report)
    threshold = max_drop_pp / 100.0
    drops: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for series, metric in gated_metrics:
        baseline_series = _get_path(baseline, series)
        current_series = _get_path(current, series)
        if not isinstance(baseline_series, Mapping) or not isinstance(current_series, Mapping):
            continue
        baseline_value = baseline_series.get(metric)
        current_value = current_series.get(metric)
        if not isinstance(baseline_value, (int, float)) or not isinstance(current_value, (int, float)):
            continue
        drop = float(baseline_value) - float(current_value)
        comparison = {
            "series": series,
            "metric": metric,
            "baseline": float(baseline_value),
            "current": float(current_value),
            "drop_pp": drop * 100.0,
            "threshold_pp": max_drop_pp,
        }
        comparisons.append(comparison)
        if drop > threshold:
            drops.append(comparison)
    return {
        "schema_version": 1,
        "passed": not drops,
        "threshold_pp": max_drop_pp,
        "comparisons": comparisons,
        "blocking_drops": drops,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Block if eval metrics regress by more than the threshold.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--max-drop-pp", type=float, default=2.0)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = evaluate_regression(args.baseline, args.current, max_drop_pp=args.max_drop_pp)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0 if report["passed"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

