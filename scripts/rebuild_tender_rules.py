"""清理无用规则；根据招标文件重建带修改建议的条款规则；用已有配置驱动分析验证。

用法（Windows venv）:
    .\\venv\\Scripts\\python.exe scripts/rebuild_tender_rules.py
"""
from __future__ import annotations

import json
import sys
import urllib.request

API = "http://127.0.0.1:8002/api/review"

# (name, category, severity, pattern, description, suggested_fix)
TENDER_RULES = [
    ("投标保证金条款", "财务", "medium", "投标保证金", "投标保证金金额、递交形式、缴纳时限及不予退还情形审查。",
     "建议明确投标保证金金额、递交截止时间与账户信息，并列明不予退还的全部情形，避免产生歧义。"),
    ("履约保证金要求", "财务", "medium", "履约保证金", "履约保证金比例、提交形式、退还条件审查。",
     "建议明确履约保证金比例（如合同总价5%-10%）、提交时限（如中标通知书发出后30日内）与无息退还条件；本项目注明不要求，需人工确认是否接受该安排。"),
    ("最高投标限价", "财务", "medium", "最高投标限价", "投标报价不得超过最高投标限价，含税价与不含税价口径一致。",
     "建议在招标文件中明确超限价投标的否决规则，并统一各标段含税/不含税报价口径与税率计算方式。"),
    ("付款节点-按月据实结算", "财务", "medium", "按月度据实结算", "月度据实结算与考核扣款、违约金抵扣的付款节奏审查。",
     "建议明确每月付款申请提交截止日（如每月5日前）、发票要求（增值税专用发票）与考核扣款、违约金抵扣的结算公式。"),
    ("质量保证期条款", "质量", "high", "质量保证期", "质保期不得为空白占位；缺陷修复响应时限与费用承担审查。",
     "建议将质保期从空白占位“/ 个月”改为明确期限（如自服务期结束之日起12个月），并保留24小时到场修复、费用由乙方承担的条款。"),
    ("缺陷责任期条款", "质量", "medium", "缺陷责任", "缺陷责任期范围、连带责任与费用承担审查。",
     "建议明确缺陷责任期与质保期的衔接关系，缺陷修复费用承担主体及逾期未修复时甲方的替代修复权利。"),
    ("转包与违法分包禁止", "合规", "high", "转包", "不得整体转包、肢解转包或以劳务分包名义违法分包；分包商准入审查。",
     "建议保留禁止转包条款，并补充分包商须在集团生态协作平台注册准入、不得列入黑名单、分包只能发生一次等约束。"),
    ("农民工工资支付保障", "合规", "high", "农民工工资", "农民工工资专用账户、按时足额支付及欠薪兜底条款审查。",
     "建议增设农民工工资专用账户与银行代发条款，明确欠薪时甲方可直接从应付工程款中代付并追偿。"),
    ("保密义务条款", "合规", "medium", "保密", "技术信息与商业秘密保密义务、保密期限及违约责任审查。",
     "建议明确保密信息范围、保密期限（至信息公开或甲方书面解除之日）及违反保密义务的赔偿与违约责任。"),
    ("知识产权归属条款", "合规", "medium", "知识产权", "工作成果知识产权归属与第三方侵权责任承担审查。",
     "建议保留“工作成果知识产权归甲方所有”条款，并明确第三方侵权索赔由乙方负责交涉并承担全部责任与费用。"),
    ("争议解决条款", "合规", "medium", "争议解决", "诉讼与仲裁方式选择明确、管辖约定审查。",
     "建议明确选择诉讼或仲裁（当前文件勾选诉讼），并补充约定管辖法院或仲裁机构名称，避免空白占位。"),
    ("不可抗力条款", "合规", "medium", "不可抗力", "不可抗力定义、通知义务、减损义务与免责范围审查。",
     "建议补充不可抗力发生后的书面通知时限（如7日内）与证明材料要求，明确受影响方的减损义务及合同解除条件。"),
    ("联合体投标限制", "招标", "high", "联合体投标", "是否接受联合体投标及联合体协议、资质业绩互借禁止审查。",
     "建议明确不接受联合体投标（本项目已注明），并保留“母子公司资质业绩不得互相借用”条款。"),
    ("特种设备生产许可证", "资质", "high", "特种设备生产许可证", "特种设备生产许可证（起重机械制造含安装修理改造）有效性审查。",
     "建议要求投标人提供有效的《特种设备生产许可证》（许可项目：起重机械制造含安装、修理、改造，桥式/门式起重机B级及以上）并在投标文件中附复印件。"),
    ("失信行为与黑名单", "合规", "high", "黑名单", "严重违法失信名单、黑名单供应商排除及失信行为处理审查。",
     "建议保留黑名单与严重违法失信名单排除条款，明确评标委员会查询渠道（国家企业信用信息公示系统、信用中国、中国执行信息公开网）。"),
]

KEEP_RULES = {
    "履约担保",  # 财务/medium
    "质保金条款",  # 财务/medium
    "业绩要求-合同业绩",  # 业绩/high
    "投标人资质-独立法人",  # 资质/high
}


def api(path: str, payload: dict | None = None, method: str = "GET") -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def main() -> int:
    rules = api("/rules")["items"]
    removed = []
    for item in rules:
        name = item.get("name") or ""
        keep = name in KEEP_RULES or any(name == r[0] for r in TENDER_RULES)
        if not keep:
            try:
                api(f"/rules/{item['id']}", method="DELETE")
                removed.append(name)
                print(f"[DEL] {name!r} {item['id'][:8]}")
            except Exception as exc:  # noqa: BLE001
                print(f"[DEL-FAIL] {name}: {exc}")
    print(f"\n共删除无用规则 {len(removed)} 条")

    created = []
    for name, category, severity, pattern, description, suggested_fix in TENDER_RULES:
        payload = {
            "name": name,
            "category": category,
            "severity": severity,
            "definition": {
                "description": description,
                "suggested_fix": suggested_fix,
                "matcher": {"text_pattern": [{"kind": "keyword", "pattern": pattern}]},
            },
            "llm_fallback": False,
        }
        try:
            item = api("/rules", payload=payload, method="POST")
            created.append(item["id"])
            print(f"[OK] {name} {item['id'][:8]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name}: {exc}")

    final = api("/rules")["items"]
    print(f"\n当前规则总数: {len(final)}")
    for item in final:
        fix = (item.get("definition") or {}).get("suggested_fix") or ""
        print(f"  - {item['name']} [{item['category']}/{item['severity']}] 建议:{'有' if fix else '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
