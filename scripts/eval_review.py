"""Run the offline intelligent-review evaluation bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eval.calibration import calculate_calibration  # noqa: E402
from eval.coverage import calculate_coverage  # noqa: E402
from eval.metric_calculator import (  # noqa: E402
    calculate_metrics,
    load_prediction_file,
    load_predictions_from_jobs,
)
from eval.regression import evaluate_regression  # noqa: E402


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_report(output_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _predictions_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.predictions:
        return load_prediction_file(args.predictions)
    if args.jobs_dir:
        return load_predictions_from_jobs(args.jobs_dir)
    raise SystemExit("--predictions or --jobs-dir is required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run metrics, calibration, coverage, and regression gate.")
    parser.add_argument("--gold-dir", default=str(ROOT / "backend" / "eval" / "gold"))
    parser.add_argument("--predictions")
    parser.add_argument("--jobs-dir")
    parser.add_argument("--run-file", help="Optional run payload with executed_rules and answers.")
    parser.add_argument("--baseline", help="Optional previous metrics.json for regression gate.")
    parser.add_argument("--output-dir", default=str(ROOT / ".eval_reports"))
    parser.add_argument("--max-drop-pp", type=float, default=2.0)
    parser.add_argument("--no-verify-manifest", action="store_true")
    args = parser.parse_args(argv)

    predictions = _predictions_from_args(args)
    verify_manifest = not args.no_verify_manifest
    output_dir = Path(args.output_dir)

    metrics = calculate_metrics(args.gold_dir, predictions, verify_manifest=verify_manifest)
    calibration = calculate_calibration(args.gold_dir, predictions, verify_manifest=verify_manifest)
    if args.run_file:
        coverage_payload = _read_json(args.run_file)
    elif args.predictions:
        coverage_payload = _read_json(args.predictions)
    else:
        coverage_payload = {"documents": []}
    coverage = calculate_coverage(args.gold_dir, coverage_payload, verify_manifest=verify_manifest)

    metrics_path = _write_report(output_dir, "metrics.json", metrics)
    _write_report(output_dir, "calibration.json", calibration)
    _write_report(output_dir, "coverage.json", coverage)

    if args.baseline:
        regression = evaluate_regression(args.baseline, metrics, max_drop_pp=args.max_drop_pp)
        _write_report(output_dir, "regression.json", regression)
        if not regression["passed"]:
            print(f"Regression gate failed; see {output_dir / 'regression.json'}", file=sys.stderr)
            return 2

    print(f"Wrote eval reports to {output_dir} (metrics: {metrics_path})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

