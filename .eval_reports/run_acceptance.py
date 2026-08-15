"""生产验收采样：Part A 金标离线评测（M-01/M-02/M-09/M-10）+ Part B 20 次全链路（M-06）。

用法（Windows venv）：
  venv\\Scripts\\python.exe .eval_reports\\run_acceptance.py [--skip-api]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# ── Part A 规则定义（与金标 enabled_rules 对应）────────────────────────
GOLD_RULES = [
    {
        "rule_id": "severance_underpayment",
        "name": "经济补偿金低于法定标准",
        "risk_level": "high",
        "matcher": {"text_pattern": [
            {"kind": "phrase", "pattern": "一次性包干"},
            {"kind": "keyword", "pattern": "补偿金"},
        ]},
        "description": "补偿金需明确基数、年限与计算过程",
    },
    {
        "rule_id": "notice_or_pay_missing",
        "name": "未约定提前通知或代通知金",
        "risk_level": "high",
        "matcher": {"text_pattern": [
            {"kind": "keyword", "pattern": "提前三十日"},
            {"kind": "keyword", "pattern": "代通知金"},
        ]},
        "description": "解除须约定三十日通知或代通知金安排",
    },
    {
        "rule_id": "payment_deadline_missing",
        "name": "补偿款支付期限不明确",
        "risk_level": "medium",
        "matcher": {"text_pattern": [
            {"kind": "keyword", "pattern": "支付日期"},
            {"kind": "keyword", "pattern": "逾期责任"},
        ]},
        "description": "补偿款需写明支付日期与逾期责任",
    },
    {
        "rule_id": "release_scope_overbroad",
        "name": "解除范围过宽",
        "risk_level": "high",
        "matcher": {"text_pattern": [
            {"kind": "keyword", "pattern": "放弃"},
        ]},
        "description": "放弃条款需限制在已知争议范围",
    },
    {
        "rule_id": "social_insurance_unsettled",
        "name": "社保公积金未结清",
        "risk_level": "high",
        "matcher": {"text_pattern": [
            {"kind": "keyword", "pattern": "社保"},
        ]},
        "description": "需列明工资、社保、公积金结清状态",
    },
    {
        "rule_id": "non_compete_overbroad",
        "name": "竞业限制过宽",
        "risk_level": "medium",
        "matcher": {"text_pattern": [
            {"kind": "keyword", "pattern": "竞业"},
            {"kind": "keyword", "pattern": "不得从事"},
        ]},
        "description": "竞业义务需有补偿、地域与岗位边界",
    },
    {
        "rule_id": "confidentiality_overbroad",
        "name": "保密范围过宽",
        "risk_level": "low",
        "matcher": {"text_pattern": [
            {"kind": "keyword", "pattern": "保密"},
        ]},
        "description": "保密义务需排除公开信息或依法披露",
    },
    {
        "rule_id": "evidence_missing",
        "name": "解除事由证据缺失",
        "risk_level": "medium",
        "matcher": {"text_pattern": [
            {"kind": "keyword", "pattern": "违纪"},
            {"kind": "keyword", "pattern": "调查记录"},
            {"kind": "keyword", "pattern": "事实描述"},
        ]},
        "description": "解除事由需附件、调查记录或事实描述",
    },
]


def part_a_gold_eval() -> dict:
    from services.review.engine import ReviewEngine

    engine = ReviewEngine()
    gold_dir = BACKEND / "eval" / "gold"
    predictions: list[dict] = []
    per_doc: list[dict] = []
    for path in sorted(gold_dir.glob("termination_agreement_*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        ir = {
            "doc_id": gold["doc_id"],
            "title": gold.get("title", ""),
            "source": {"filename": f"{gold['doc_id']}.json"},
            "blocks": [{"block_id": "b1", "type": "paragraph", "text": gold["contract_excerpt"]}],
        }
        result = engine.analyze_document(ir, GOLD_RULES, allow_llm=False)
        findings = result.get("findings") or []
        doc_preds = []
        for f in findings:
            pred = {
                "doc_id": f.get("document_id") or gold["doc_id"],
                "doc_type": "termination_agreement",
                "rule_id": f.get("rule_id"),
                "severity": f.get("severity"),
                "text": f.get("quote") or "",
                "confidence": f.get("confidence") or "rule_deterministic",
            }
            predictions.append(pred)
            doc_preds.append(pred)
        per_doc.append({"doc_id": gold["doc_id"], "findings": doc_preds})

    report = {
        "predictions": predictions,
        "documents": per_doc,
        "meta": {"generated_by": "run_acceptance.part_a", "engine": "deterministic"},
    }
    out = ROOT / ".eval_reports" / "gold_predictions.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[A] predictions written: {out} ({len(predictions)} findings)")
    return report


def run_eval_review() -> dict:
    import subprocess
    py = str(ROOT / "venv" / "Scripts" / "python.exe")
    cmd = [
        py, str(ROOT / "scripts" / "eval_review.py"),
        "--predictions", str(ROOT / ".eval_reports" / "gold_predictions.json"),
        "--gold-dir", str(BACKEND / "eval" / "gold"),
        "--output-dir", str(ROOT / ".eval_reports" / "gold"),
    ]
    print("[A] running eval_review:", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    print(proc.stdout[-2000:] if proc.stdout else "")
    if proc.stderr:
        print("STDERR:", proc.stderr[-1000:])
    metrics_path = ROOT / ".eval_reports" / "gold" / "metrics.json"
    if metrics_path.exists():
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    return {"error": "metrics.json not produced", "stderr": proc.stderr[-800:]}


# ── Part B：20 次全链路 ──────────────────────────────────────────────
API = "http://127.0.0.1:8002/api/review"


def _post(path: str, payload: dict, timeout: int = 90) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode("utf-8")[:400]}


def _get(path: str) -> dict:
    try:
        with urllib.request.urlopen(API + path, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code}


def part_b_full_chain(n: int = 20) -> dict:
    # 用已 ready 的招标文件 + 已有招标规则做稳定输入
    docs = _get("../../api/docs?page=1&page_size=100".replace("../../api/docs", "/api/docs")) if False else None
    # 直接查文档列表
    req = urllib.request.Request("http://127.0.0.1:8002/api/docs?page=1&page_size=100")
    with urllib.request.urlopen(req, timeout=30) as r:
        docs_payload = json.loads(r.read())
    tender = next((d for d in docs_payload.get("items", []) if d.get("filename") == "tender_file.pdf" and d.get("status") == "ready"), None)
    if not tender:
        return {"error": "tender_file.pdf not ready"}
    doc_id = tender["id"]
    ver_id = tender["current_version_id"]

    rules = _get("/rules")
    rule_items = rules.get("items", [])
    tender_rules = [r for r in rule_items if "依法注册" in str(r.get("name")) or "合同业绩" in str(r.get("name"))]
    if not tender_rules:
        tender_rules = rule_items[:2]
    rule_ids = [r["id"] for r in tender_rules]

    runs = []
    signatures = {}
    for i in range(n):
        t0 = time.time()
        run = {"round": i + 1, "ok": False}
        try:
            batch = _post("/batches", {"name": f"验收采样-{i+1:02d}", "document_type": "招标文件", "ocr_required": False})
            if "id" not in batch:
                run["error"] = f"batch create failed: {batch}"
                runs.append(run); continue
            mem = _post(f"/batches/{batch['id']}/documents", {
                "document_id": doc_id, "document_version_id": ver_id,
                "filename": "tender_file.pdf", "status": "ready",
            })
            job = _post("/analysis-jobs", {
                "batch_id": batch["id"],
                "document_membership_ids": [mem["id"]],
                "template_version_id": None,
                "rule_selections": [{"rule_version_id": rid, "enabled": True, "overrides": {}} for rid in rule_ids],
                "sensitivity": 85, "analysis_profile_id": "accurate", "marking_mode": "standard",
            })
            if "id" not in job:
                run["error"] = f"job create failed: {job}"
                runs.append(run); continue
            # 等完成
            final = None
            for _ in range(30):
                time.sleep(1)
                j = _get(f"/analysis-jobs/{job['id']}")
                if j.get("status") in ("complete", "complete_degraded", "failed"):
                    final = j
                    break
            if not final:
                run["error"] = "job timeout"
                runs.append(run); continue
            findings = _get(f"/analysis-jobs/{job['id']}/findings")
            total = findings.get("total", 0)
            # 处置第一条
            decided = None
            if total and findings.get("items"):
                f0 = findings["items"][0]
                decided = _post(f"/findings/{f0['id']}/decision", {"decision_type": "accepted", "comment": "验收采样"})
            exported = _post(f"/analysis-jobs/{job['id']}/exports", {"format": "markdown"})
            run.update({
                "ok": final.get("status") in ("complete", "complete_degraded"),
                "status": final.get("status"),
                "findings": total,
                "decision": "ok" if decided and "id" in decided else ("skipped" if not total else "failed"),
                "export": "ok" if "id" in exported else "failed",
                "elapsed_s": round(time.time() - t0, 2),
                "job_id": job["id"],
                "error": final.get("error"),
            })
            sig = f"{final.get('status')}|{total}"
            signatures[sig] = signatures.get(sig, 0) + 1
        except Exception as e:  # noqa: BLE001
            run["error"] = repr(e)[:300]
        runs.append(run)
        print(f"[B] round {i+1:02d}: {run.get('status') or run.get('error')} findings={run.get('findings','-')} {run.get('elapsed_s','')}s")

    ok = sum(1 for r in runs if r.get("ok"))
    summary = {
        "total": n,
        "ok": ok,
        "ok_rate": ok / n if n else 0,
        "status_signatures": signatures,
        "avg_elapsed_s": round(sum(r.get("elapsed_s", 0) for r in runs) / max(1, len(runs)), 2),
        "runs": runs,
    }
    out = ROOT / ".eval_reports" / "full_chain_20.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[B] summary: {ok}/{n} ok, signatures={signatures}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-api", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("Part A: 金标离线评测 (M-01/M-02/M-09/M-10)")
    print("=" * 60)
    part_a_gold_eval()
    metrics = run_eval_review()

    result = {
        "part_a_metrics": metrics,
    }
    if not args.skip_api:
        print("=" * 60)
        print("Part B: 20 次全链路采样 (M-06)")
        print("=" * 60)
        result["part_b_full_chain"] = part_b_full_chain(20)

    out = ROOT / ".eval_reports" / "acceptance_sampling.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 60)
    print(f"report: {out}")
    if isinstance(metrics, dict) and "error" not in metrics:
        top = metrics.get("overall") or metrics.get("summary") or {}
        print("overall metrics:", json.dumps(top, ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
