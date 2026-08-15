# 智能审查文档链路可靠性与企业级一致性审计

> 日期：2026-08-15
> 审计人角色：资深大模型算法工程师 + 企业级架构视角
> 审计范围：
> - `docs/product/2026-08-15-intelligent-review-prd.md`（PRD v1.1）
> - `docs/design/specs/2026-08-15-intelligent-review-requirements-refinement.md`（v2 需求细化）
> - `docs/design/specs/2026-08-15-intelligent-review-solution.md`（v1 方案设计）
> - 实际代码库（backend/、frontend/）企业级能力现状
> 评级：🔴 阻断（发布/开发前必须解决）、🟠 主要（进入对应阶段前必须解决）、🟡 次要（可排期）
> 对齐：平台级 P0 已由 `docs/product/2026-07-19-page-function-iteration-target.md` §6 覆盖，本审计聚焦**审查域增量缺口 + 阻塞审查交付的平台依赖**，不重复其结论。

---

## 一、审计结论先行

文档链（PRD → 需求细化 → 方案）在产品功能层面**完整且自洽**，但存在两类系统性缺口：

1. **算法可靠性缺口（R 类）**：评测颗粒度不足、置信度未校准、确定性未闭环、无回归防护、降级链未定义、错误处理不严谨。当前 M-01/M-02（高风险召回/精确率）无法支撑企业级"可证明可靠"的承诺。
2. **企业级一致性缺口（E 类）**：无认证授权、TLS 关闭校验（已证实在 8 处代码中）、审计不可篡改、密钥治理、输出消毒、错误协议、可观测性、数据治理、CI/CD 质量门、容量治理均缺失。

**结论**：产品方向正确，但按当前文档与代码进入开发，将无法通过企业级验收。必须先落地"可靠性工程"与"企业级底座"两类需求，且其中 TLS/认证/消毒/错误协议为**横切阻断项**，必须先行。

---

## 二、算法可靠性缺口（R 类）

### R-01 🔴 评测颗粒度不足

- 现状：PRD 仅定义高风险整体召回率/精确率（M-01/M-02），v2 §5 的 MetricsCalculator 只按 type 分组。
- 缺口：无 per-rule、per-severity、per-document-type 的 F1/混淆矩阵；无法定位"哪条规则误报高、哪条漏报"；无法支撑规则迭代。
- 要求：
  - 评测矩阵：按 `rule × severity × doc_type` 输出 TP/FP/FN/精确率/召回率/F1；
  - 高风险与低风险分开报告（低风险误报代价不同）；
  - 输出逐条 FP/FN 清单（可回看原文，支持规则调优）。

### R-02 🟠 置信度未校准

- 现状：`confidence = rule_deterministic | llm_yes | llm_unknown`，未与其真实准确率校准。
- 缺口：`llm_yes` 不意味着"90% 正确"；用户无法据此决策；违背"不伪装成功"原则。
- 要求：
  - 在评测集上计算每个 confidence 档位的实际精确率，形成**校准表**（随模型/规则版本发布）；
  - 前端展示"该档位历史准确率"（如"AI 确认，历史准确率 92%"）；
  - `llm_unknown` 强制人工确认，不计入自动通过。

### R-03 🔴 确定性/可复现未闭环

- 现状：v2 有规则版本 hash、temperature=0.2，但不足。
- 缺口：LLM 输出受 provider 端 seed/采样影响；缺 model snapshot、prompt 版本 hash、评测集版本 hash；`temperature=0.2` 无 seed 保证。
- 要求：
  - 任务快照补齐六元组：`rule_version + template_version + llm_model + temperature + prompt_version(hash) + eval_set_version`；
  - LLM 调用显式传 `seed`（provider 支持时）+ 记录 provider 返回的 `model/usage/finish_reason`；
  - 评测集与金标用 SHA-256 锁定，报告绑定该 hash（对齐产品文档 §10.5 指标字典）。

### R-04 🟠 无回归防护

- 现状：无"变更 prompt/模型/规则后必须跑回归评测"的门。
- 缺口：一次 prompt 调优可能引入大面积退化，无法发现。
- 要求：
  - 建立**回归评测门**：规则/prompt/模型/依赖变更 → 自动跑固定回归集 → 高风险召回/精确率不允许下降超过阈值（如 -2pp）→ 否则阻断合并；
  - 回归集与评测集分离（回归集固定且不可随迭代漂移）。

### R-05 🟠 降级链缺失

- 现状：v2 有 llm_fallback 规则级开关，但无系统级降级契约。
- 缺口：LLM 整体不可用/超时、MinerU 解析失败、检索失败时，任务是失败还是降级？用户看到什么？
- 要求（三档降级）：
  1. LLM 不可用 → 仅跑确定性规则，结果标注"降级审查（未执行 AI 检查项）"，任务置 `complete_degraded`；
  2. 单文件解析失败 → 该文件 `failed`，其余继续（已有）；
  3. 检索失败（问答助手）→ 明确返回"检索不可用"，不编造。

### R-06 🟠 错误处理不严谨

- 现状：参考项目 LLM 解析失败 `return []`（静默丢块），v2 已要求重试 1 次 + 记录，但仍缺系统性策略。
- 缺口：重试策略、幂等、死信、部分失败聚合、任务级重试语义未定义。
- 要求：
  - 每块处理幂等（`chunk_id + rule_id` 唯一键）；
  - LLM 失败指数退避重试（≤2 次）+ 死信（`job.errors[]` 可重试清单）；
  - 任务级 `retry_failed_chunks` 只重跑失败块，不重跑全量；
  - 明确 `complete` 与 `complete_degraded` 的 UI 区分。

### R-07 🟡 覆盖率/拒答率指标缺失

- 现状：无"覆盖率"（NN：多少规则/文档实际被执行）与"拒答准确率"。
- 要求：
  - 覆盖率 = 实际执行规则数 / 启用规则数（=100% 才算 complete，否则 degraded）；
  - 问答助手拒答率 + 拒答正确率（金标"无答案"问题集）。

---

## 三、企业级一致性缺口（E 类）

### E-01 🔴 无认证授权

- 证据：`backend/api/main.py` 无任何认证中间件，所有路由开放；无 RBAC/租户。
- 要求（分档）：
  - 单机模式：强制 loopback 绑定 + 启动检测拒绝非 loopback + 反向代理暴露拒绝；可选本地 token；
  - 团队模式（若启用）：身份认证 + RBAC（管理员/审查员/只读）+ 资源归属（批次/任务/范本 owner）+ 写操作审计（对齐产品文档 P0-1）。

### E-02 🔴 TLS 关闭校验（已证实）

- 证据（8 处）：`qa_service.py:63,67`（`urllib3.disable_warnings` + `verify=False`）、`parallel_qa.py:110`、`search.py:128,177`、`indexer.py:36`、`document_pipeline.py:772,857`、`main.py:84`（`verify_certs=False, ssl_show_warn=False`）。
- 要求：所有 ES/Embedding/LLM/MinerU HTTP 客户端默认 `verify=True`；支持受信 CA 配置；证书错误 fail-closed，删除所有 `verify=False`/`ssl_show_warn=False`/`disable_warnings` 生产路径。

### E-03 🟠 审计不可篡改

- 现状：v2 定义 `audit.jsonl` 追加式，但无防篡改/完整性保证；操作者单机为 `local`。
- 要求：
  - 审计日志带单调递增序号 + 前条 hash（或 WAL + 校验和），检测篡改；
  - 每条含：`event_id, timestamp, actor, action, resource, before/after, request_id`；
  - 提供只读审计导出（供法务核验）。

### E-04 🟠 密钥与敏感信息治理

- 现状：`.env` 明文、无 secret manager、密钥可能进入日志（未脱敏）。
- 要求：密钥不落日志；日志/错误统一脱敏；提供 `.env.example` 与启动密钥校验；团队模式用受管密钥。

### E-05 🔴 输出消毒缺失

- 现状：LLM 输出、历史答案、预览 Markdown、表格 HTML 直接 `v-html`（产品文档 P0-1 已列，未在审查文档中显式落地）。
- 要求：唯一安全渲染组件 + 严格 allowlist 消毒；禁止事件属性/`javascript:` URL/script/iframe/危险 SVG；审查报告、风险解释、修改建议同样走该组件。

### E-06 🟠 错误协议不统一

- 证据：`main.py:93` `/api/health/index` 直接 `str(e)` 返回 ES 连接堆栈。
- 要求：稳定错误码 + 用户可读说明 + `retryable` + `support_id`；禁止内部堆栈/连接串进入前端（对齐 P0-3）；审查任务错误同协议。

### E-07 🟠 可观测性缺失

- 证据：仅 `chat.py` 有 `request_id`（用于 cancel），无结构化日志框架、无 request_id 贯穿、无 trace/metric/告警。
- 要求：
  - `request_id/doc_id/version/task_id/rule_id/chunk_id` 贯穿日志；
  - 每任务/规则/块的耗时、token、成本、错误率指标；
  - 依赖健康（ES/Embedding/LLM/MinerU）暴露为只读健康页，不泄内部堆栈。

### E-08 🟡 数据治理

- 现状：无备份恢复、无迁移脚本版本化、无数据保留/出境说明。
- 要求：`.review_data/` 备份/恢复脚本；schema 迁移带版本；数据出境说明（Embedding/LLM provider）明示；删除任务=级联清理 + 可验证。

### E-09 🟠 CI/CD 质量门缺失

- 证据：`frontend/package.json` 无 `test/lint/typecheck` 脚本；`backend/tests/` 仅 5 个表格测试；无 CI。
- 要求：前端 `test/lint/typecheck` 脚本 + Vitest 覆盖率门；后端 pytest + fake 依赖集成测试；CI 跑全量 + 评测回归门（R-04）；bundle budget。

### E-10 🟡 容量与并发治理

- 现状：任务队列无背压/超时/分页/速率限制；批次 50 文件并发未定义上限。
- 要求：最小持久队列（产品文档 T03）→ 背压 + 死信 + 并发上限；LLM/MinerU 超时；列表分页；写操作速率限制。

---

## 四、文档链内部一致性结论

| 检查项 | 结论 |
| --- | --- |
| PRD ↔ 需求细化 ↔ 方案 引用链 | ✅ 完整，冲突已标注以 v2 为准 |
| 处置状态机 3 态 ↔ 前端 RiskCard | ✅ 一致 |
| 指标 ↔ 评测工具映射 | 🟠 M-01/M-02 有工具，但 R-01 颗粒度不足 |
| 企业级需求 ↔ 产品文档 P0 | 🟠 已列但未落地到审查文档的验收标准 |
| 数据契约 ↔ 实际存储 | ✅ v2 已定义 JSON+原子写+漂移扫描 |

---

## 五、修复映射（审计编号 → 实施 Workstream）

| 审计编号 | 归入 Workstream |
| --- | --- |
| E-01/E-02/E-04/E-05/E-06/E-07 | W0 平台底座（安全/认证/错误/可观测） |
| R-01/R-02/R-03/R-04/R-07 + E-08 | W1 评测与数据治理 |
| R-05/R-06 + R-03 引擎侧 | W2 审查引擎 |
| E-03/E-08（审计/恢复） | W3 审查后端服务 |
| E-05 前端侧 + E-09 前端质量门 | W4 前端 |
| E-09/E-10 + R-04 回归门 | W5 质量与运维 |

> 详细任务拆分、依赖与并行策略见 `docs/design/plans/2026-08-15-intelligent-review-implementation-plan.md`；需求落地见 PRD v2.0。
