"""根据招标文件（tender_file.pdf）生成条款设置规则并创建到审查后端。

用法（Windows venv）:
    .\\venv\\Scripts\\python.exe scripts/create_tender_rules.py
"""
from __future__ import annotations

import json
import sys
import urllib.request

API = "http://127.0.0.1:8002/api/review/rules"

RULES = [
    # (name, category, severity, pattern, description)
    ("投标保证金条款", "财务", "medium", "投标保证金", "投标保证金金额、递交形式、缴纳时限及不予退还情形审查。"),
    ("履约保证金要求", "财务", "medium", "履约保证金", "履约保证金比例、提交形式、退还条件审查；本文件前附表注明不要求，需人工确认。"),
    ("最高投标限价", "财务", "medium", "最高投标限价", "投标报价不得超过最高投标限价，含税价与不含税价口径一致。"),
    ("付款节点-按月据实结算", "财务", "medium", "按月度据实结算", "月度据实结算与考核扣款、违约金抵扣的付款节奏审查。"),
    ("质量保证期条款", "质量", "high", "质量保证期", "质保期不得为空白占位（本文件为“/ 个月”）；缺陷修复响应时限与费用承担审查。"),
    ("缺陷责任期条款", "质量", "medium", "缺陷责任", "缺陷责任期范围、连带责任与费用承担审查。"),
    ("转包与违法分包禁止", "合规", "high", "转包", "不得整体转包、肢解转包或以劳务分包名义违法分包；分包商准入审查。"),
    ("农民工工资支付保障", "合规", "high", "农民工工资", "农民工工资专用账户、按时足额支付及欠薪兜底条款审查。"),
    ("保密义务条款", "合规", "medium", "保密", "技术信息与商业秘密保密义务、保密期限及违约责任审查。"),
    ("知识产权归属条款", "合规", "medium", "知识产权", "工作成果知识产权归属与第三方侵权责任承担审查。"),
    ("争议解决条款", "合规", "medium", "争议解决", "诉讼与仲裁方式选择明确、管辖约定审查；未选择的空白项需补齐。"),
    ("不可抗力条款", "合规", "medium", "不可抗力", "不可抗力定义、通知义务、减损义务与免责范围审查。"),
    ("联合体投标限制", "招标", "high", "联合体投标", "是否接受联合体投标及联合体协议、资质业绩互借禁止审查。"),
    ("特种设备生产许可证", "资质", "high", "特种设备生产许可证", "特种设备生产许可证（起重机械制造含安装修理改造）有效性审查。"),
    ("失信行为与黑名单", "合规", "high", "黑名单", "严重违法失信名单、黑名单供应商排除及失信行为处理审查。"),
]


def create_rule(rule: tuple[str, str, str, str, str]) -> dict:
    name, category, severity, pattern, description = rule
    payload = {
        "name": name,
        "category": category,
        "severity": severity,
        "definition": {
            "description": description,
            "matcher": {"text_pattern": [{"kind": "keyword", "pattern": pattern}]},
        },
        "llm_fallback": False,
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    created = []
    for rule in RULES:
        try:
            item = create_rule(rule)
            created.append((rule[0], item["id"], item["version"], item["status"]))
            print(f"[OK] {rule[0]:<12} {item['id']} v{item['version']} {item['status']}")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {rule[0]}: {exc}")
    print(f"\n共创建 {len(created)}/{len(RULES)} 条规则")
    return 0 if len(created) == len(RULES) else 1


if __name__ == "__main__":
    sys.exit(main())
