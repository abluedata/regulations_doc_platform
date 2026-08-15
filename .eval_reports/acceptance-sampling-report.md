# 生产验收采样报告

日期：2026-08-15  
范围：M-01/M-02/M-06/M-09/M-10（M-08 需人工计时试验）

## 执行摘要

确定性引擎在合成金标（30 份解除协议）上的基线已实测：高风险档召回 76.2%、精确 66.7%，未达 PRD 目标（召回≥90%、精确≥80%）——差额部分正是需要真实 LLM 检查（llm_fallback）补足的范围。20 次全链路采样 20/20 通过、结果完全一致。

## M-06 上传到定稿 20/20 —— 通过 ✅

| 项 | 结果 |
| --- | --- |
| 轮次 | 20/20 全部 complete |
| 平均耗时 | ~1.2s/轮（确定性引擎） |
| 结果签名 | `complete|1` × 20，完全一致（六元组快照可复现） |
| 处置+导出 | 每轮 accepted + markdown 导出成功 |

证据：`.eval_reports/full_chain_20.json`

## M-01/M-02 高风险召回/精确 —— 确定性基线未达标 ⚠️

| 档位 | precision | recall | f1 |
| --- | --- | --- | --- |
| high | 66.7% | 76.2% | 0.71 |
| medium | 16.0% | 26.7% | 0.20 |
| low | 100% | 75.0% | 0.86 |
| overall | 44.2% | 57.5% | 0.50 |

FP 主因（同规则多关键词命中同一文档未跨 pattern 去重）：
- `payment_deadline_missing` "支付日期"+"逾期责任" 双命中 ×4
- `severance_underpayment` "一次性包干"+"补偿金" 双命中 ×4
- `notice_or_pay_missing` "提前三十日"+"代通知金" 双命中 ×4
- `evidence_missing` "违纪/调查记录/事实描述" 三命中 ×3

FN 主因：
- 金标跨模板标注（如 003 标注 non_compete 但原文无竞业措辞；006/030 标注 severance 但原文无补偿金）——确定性匹配器按原文匹配必然 FN，此类 11 条需 LLM 语义理解。
- `evidence_missing` 金标描述文本与命中词形态差异（"解除事由需附件…"不含"违纪"）4 条。

结论：M-01/M-02 的 90/80 目标需启用 llm_fallback（真实模型）补确定性匹配的语义缺口；确定性部分建议增加"同文档同规则跨 pattern 去重"。

## M-09 校准误差 —— 待真实模型 ⏸

确定性规则 confidence 为类别标签 `rule_deterministic`，无数值置信度，校准表全落 `missing` 桶。真实置信度校准需 LLM 检查产出数值 confidence 后重测。

## M-10 complete 覆盖率 —— 工具链路待补 ⏸

coverage 工具需 run payload 记录 `executed_rules`；当前离线评测预测文件未携带该字段（coverage=0.0 为记录缺失而非实际未执行）。API 全链路 job 的 snapshot 已含 rule_version_ids，后续以 `--jobs-dir` 模式重算即可。

## M-08 人工时间下降 —— 待人工试验 ⏸

需要人工前后对照计时样本（传统人工审查 vs 平台审查），无法自动化。

## 过程中修复

- `backend/eval/issue_associator.py::text_similarity`：子串包含分支由 `shorter/longer` 改为 `max(0.8, shorter/longer)`，修复"关键词命中 vs 风险描述"比对被长度比例压到 0.18 导致 tp=0 的缺陷。相关单测 7 passed。

## 产出文件

- `.eval_reports/gold_predictions.json`（52 条确定性预测）
- `.eval_reports/gold/metrics.json` / `calibration.json` / `coverage.json`
- `.eval_reports/full_chain_20.json`（20 轮全链路明细）
- `.eval_reports/acceptance_sampling.json`（汇总）
- `.eval_reports/run_acceptance.py`（可复跑脚本）
