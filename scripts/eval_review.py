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
from eval.qa_metrics import calculate_qa_metrics  # noqa: E402


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
    parser.add_argument("--qa-gold-file", default=str(ROOT / "backend" / "eval" / "gold" / "qa" / "review_qa_v1.json"))
    parser.add_argument("--qa-run-file", help="Optional single-document QA run payload.")
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

    qa_failed = False
    if args.qa_run_file:
        qa = calculate_qa_metrics(args.qa_gold_file, _read_json(args.qa_run_file))
        qa_path = _write_report(output_dir, "qa_metrics.json", qa)
        _write_report(output_dir, "qa_cases.json", {"cases": qa["cases"]})
        failed_cases = [case for case in qa["cases"] if not case["passed"]]
        report_lines = [
            "# FR-07 单文档问答测评报告", "",
            f"- 金标集：`{qa['dataset_id']}`", f"- 金标 SHA-256：`{qa['dataset_sha256']}`",
            f"- 样本数：{qa['case_count']}", "", "## 指标", "",
            "| 指标 | 结果 | 门槛 |", "| --- | ---: | ---: |",
            f"| 答案准确率 | {qa['answer_accuracy']:.2%} | >=90% |",
            f"| 原文引用逐字一致率 | {qa['citation_exact_match_rate']:.2%} | 100% |",
            f"| 引用定位正确率 | {qa['citation_location_accuracy']:.2%} | >=95% |",
            f"| 拒答率 | {qa['refusal_rate']:.2%} | 报告项 |",
            f"| 拒答正确率 | {qa['refusal_correct_rate']:.2%} | >=95% |",
            f"| 错误拒答率 | {qa['false_refusal_rate']:.2%} | <=5% |",
            f"| 非拒答引用覆盖率 | {qa['non_refusal_citation_coverage']:.2%} | 100% |",
            f"| SSE 终态唯一率 | {qa['sse_unique_terminal_rate']:.2%} | 100% |",
            "", f"## 结论", "", "达标。" if qa["passed"] else "未达标。",
        ]
        if failed_cases:
            report_lines.extend(["", "## 失败样本", ""] + [
                f"- `{case['question_id']}`：{', '.join(case['failures'])}" for case in failed_cases
            ])
        (output_dir / "review_qa_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        qa_failed = not qa["passed"]
        print(f"QA metrics: {qa_path}")

    if args.baseline:
        regression = evaluate_regression(args.baseline, metrics, max_drop_pp=args.max_drop_pp)
        _write_report(output_dir, "regression.json", regression)
        if not regression["passed"]:
            print(f"Regression gate failed; see {output_dir / 'regression.json'}", file=sys.stderr)
            return 2

    if qa_failed:
        print(f"FR-07 QA quality gate failed; see {output_dir / 'review_qa_report.md'}", file=sys.stderr)
        return 2

    print(f"Wrote eval reports to {output_dir} (metrics: {metrics_path})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

