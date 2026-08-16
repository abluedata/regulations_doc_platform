"""补齐既有业务规则的修改建议；用已有配置驱动分析并验证 findings 输出修改建议。

用法（Windows venv）:
    .\\venv\\Scripts\\python.exe scripts/verify_tender_review.py
"""
from __future__ import annotations

import json
import sys
import urllib.request

API = "http://127.0.0.1:8002/api/review"

LEGACY_RULES = [
    {
        "name": "履约担保",
        "category": "财务",
        "severity": "medium",
        "kind": "keyword",
        "pattern": "履约担保",
        "description": "履约担保要求审查。",
        "suggested_fix": "建议明确履约担保的形式（银行保函/保证金）、金额比例、有效期及退还条件，与投标保证金退还顺序衔接。",
    },
    {
        "name": "质保金条款",
        "category": "财务",
        "severity": "medium",
        "kind": "keyword",
        "pattern": "质保金",
        "description": "付款包含质保金审查。",
        "suggested_fix": "建议明确质保金比例（如结算价的3%-5%）、扣留方式、缺陷责任期满后的无息退还时间与条件。",
    },
    {
        "name": "业绩要求-合同业绩",
        "category": "业绩",
        "severity": "high",
        "kind": "phrase",
        "pattern": "合同业绩",
        "description": "投标人须具有合同业绩。",
        "suggested_fix": "建议明确业绩的时间范围（如近3年）、数量（如不少于2份）、金额门槛及证明文件（合同、验收单、发票）。",
    },
    {
        "name": "投标人资质-独立法人",
        "category": "资质",
        "severity": "high",
        "kind": "phrase",
        "pattern": "依法注册的独立法人",
        "description": "投标人须为依法注册的独立法人或其他组织。",
        "suggested_fix": "建议要求投标人提供有效的营业执照/法人登记证明复印件，并明确“其他组织”的认定范围与证明文件要求。",
    },
]


def api(path: str, payload: dict | None = None, method: str = "GET") -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def rebuild_legacy_rules() -> None:
    items = api("/rules")["items"]
    for spec in LEGACY_RULES:
        olds = [it for it in items if it["name"] == spec["name"]]
        if len(olds) == 1 and (olds[0].get("definition") or {}).get("suggested_fix"):
            continue
        for old in olds:
            api(f"/rules/{old['id']}", method="DELETE")
        item = api(
            "/rules",
            payload={
                "name": spec["name"],
                "category": spec["category"],
                "severity": spec["severity"],
                "definition": {
                    "description": spec["description"],
                    "suggested_fix": spec["suggested_fix"],
                    "matcher": {"text_pattern": [{"kind": spec["kind"], "pattern": spec["pattern"]}]},
                },
                "llm_fallback": False,
            },
            method="POST",
        )
        print(f"[rule] {spec['name']} -> {item['id'][:8]} 带修改建议")


def main() -> int:
    rebuild_legacy_rules()

    rules = api("/rules")["items"]
    rule_ids = [it["id"] for it in rules]
    print(f"\n规则总数: {len(rules)}（全部带修改建议: {all((it.get('definition') or {}).get('suggested_fix') for it in rules)}）")

    # 保存已有配置：全部规则启用 + 偏好
    configuration = api(
        "/configurations",
        payload={
            "name": "招标文件审查默认配置",
            "rule_selections": [{"rule_version_id": rid, "enabled": True, "overrides": {}} for rid in rule_ids],
            "sensitivity": 80,
            "analysis_profile_id": "accurate",
            "marking_mode": "standard",
        },
        method="POST",
    )
    print(f"[config] {configuration['name']} {configuration['id'][:8]}")

    # 新建批次（使用真实版本号）
    batch = api(
        "/batches",
        payload={"name": "招标文件条款规则验证", "document_type": "维保服务", "ocr_required": False},
        method="POST",
    )
    version_id = "6b78417eb67927fbb6b11568863bc49d1576e4e48052b77a74ea1d85e491107c"
    membership = api(
        f"/batches/{batch['id']}/documents",
        payload={
            "document_id": "20260815_184602_15b5254b",
            "document_version_id": version_id,
            "filename": "tender_file.pdf",
            "status": "ready",
        },
        method="POST",
    )

    # 用配置驱动分析：请求体不传规则选择，后端按配置解析
    job = api(
        "/analysis-jobs",
        payload={
            "batch_id": batch["id"],
            "document_membership_ids": [membership["id"]],
            "rule_selections": [],
            "sensitivity": 10,
            "analysis_profile_id": "fast",
            "marking_mode": "high_only",
            "configuration_id": configuration["id"],
        },
        method="POST",
    )
    print(f"[job] {job['id'][:8]} status={job['status']} progress={job['progress']}")
    snap = job.get("snapshot") or {}
    print(f"[snapshot] sensitivity={snap.get('sensitivity')} profile={snap.get('analysis_profile_id')} "
          f"marking={snap.get('marking_mode')} rules={len(snap.get('rule_version_ids') or [])} "
          f"configuration={snap.get('configuration', {}).get('name')}")

    findings = api(f"/analysis-jobs/{job['id']}/findings")
    print(f"\n[findings] 共 {findings['total']} 项，severity 分布: {findings.get('counts')}")
    for item in findings["items"]:
        suggestion = item.get("suggestion") or "（无）"
        print(f"  - [{item['severity']}] {item['title']} | 原文: {item['quote'][:40]!r}")
        print(f"      建议: {suggestion[:70]}")
    with open(".data/logs/verify_findings.json", "w", encoding="utf-8") as f:
        json.dump({"job_id": job["id"], "findings": findings}, f, ensure_ascii=False, indent=1)
    print("\n结果已写入 .data/logs/verify_findings.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
