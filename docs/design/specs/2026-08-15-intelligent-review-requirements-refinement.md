# 智能审查需求细化（参考 LangChain v1.1 通用 AI 文档审核 Agent 实战项目）

> 日期：2026-08-15
> 状态：对 `2026-08-15-intelligent-review-solution.md`（v1 方案）的需求细化
> 参考项目：`E:\BaiduNetdiskDownload\...\【加餐】案例12：LangChian v1.1 通用AI文档审核v2.0Agent实战\ai-document-review`
> 结论先行：参考项目证明了"单文档 LLM 审查 + 人工处置 + HITL 门 + 评测"的完整链路。本文件把其中**经过实战验证的模型、提示词、证据定位、处置与评测机制**落回 v1 方案，形成 v2 需求。v1 的批次/范本/任务/报告/问答助手等差异化能力全部保留。

---

## 1. 参考项目分析

### 1.1 项目定位与技术栈

参考项目是一个可运行的"通用 AI 文档审核 v2.0 Agent"：

```text
React UI ──▶ FastAPI ──▶ SQLite (issues/rules)
                │
                ├── MinerU 解析 PDF → 段落
                ├── LangChain v1 (DeepSeek) 分块审查 → 结构化 Issue
                ├── HumanInTheLoopMiddleware 处置门（approve/edit/reject）
                └── eval/ 评测（IssueAssociator + MetricsCalculator）
```

- 审查对象：`解除、终止劳动合同协议书`（种子文档 24+ 份）、基金年报等。
- 内置问题类型：`Grammar & Spelling`（语法拼写）、`Definitive Language`（绝对化表述）。
- 自定义规则：`ReviewRule{name, description, risk_level, examples}` 动态注入系统提示词，成为新的问题类型。
- 人工处置：`not_reviewed → accepted / dismissed`，accept 可带修改字段，dismiss 可带理由。
- 证据定位：Issue 带 `location{source_sentence, page_num, bounding_box(quadpoints), para_index}`，PDF 高亮 3 级回退。
- 流式：`event: issues`（逐块产出）+ `event: complete | error`。
- HITL：`create_agent + HumanInTheLoopMiddleware + InMemorySaver`，`start → interrupt → resume(approve/edit/reject)`。
- 评测：检测结果与金标按文本相似度关联，输出按类型分组的 TP/FP/FN、精确率/召回率。

### 1.2 借鉴 → 落地映射

| # | 参考项目已验证机制 | v2 采纳方式 | 落地位置 |
| --- | --- | --- | --- |
| 1 | Issue 数据模型（location/status/modified_fields/dismissal_feedback） | 直接采纳并加证据链 | 风险实例契约（§2.1） |
| 2 | 规则即 LLM 检查项（name/description/risk_level/examples 注入 prompt） | 采纳，与确定性匹配器并存 | 规则模型（§2.2）、引擎（§3.1） |
| 3 | 反误报提示词（序号/占位符/勾选框/合同标准文本排除 + "宁可不报"） | 全文采纳并扩展中文合同场景 | 引擎（§3.1） |
| 4 | 证据定位 3 级回退（PDF 文本层 → MinerU layout span → 段落 bbox） | 采纳；DOCX 用 block/段落锚点 | 引擎（§3.2） |
| 5 | 分块流式（pagination=32 段/块，逐块产出） | 采纳；与任务状态机结合 | 引擎（§3.3） |
| 6 | HITL 处置门（approve/edit/reject） | 采纳交互语义；提供两档实现 | 处置（§4） |
| 7 | IssueAssociator + MetricsCalculator 评测 | 采纳为决策门指标测量工具 | 评测（§5） |
| 8 | SSE 事件（issues/complete/error）+ 重审 | 采纳（重审改为 `POST rerun`，避免副作用 GET） | API（§7） |
| 9 | 规则 CRUD + 文档-规则关联（按文档启停） | 采纳 | API（§7） |

### 1.3 不借鉴 / 需改造的部分

| 参考项目做法 | 不采纳原因 | v2 处理 |
| --- | --- | --- |
| 纯 LLM 规则，无确定性匹配器 | 成本高、结果漂移、不可单测 | 保留 v1 确定性优先通道 |
| 规则原地修改、无版本 | 结果不可复现 | 保留 v1 版本化范本 + 规则快照 |
| 单文档审查，无批次/任务 | 无法批量交付与恢复 | 保留 v1 批次 + ReviewJob 状态机 |
| Azure Entra/AAD 认证 | 本平台单机 loopback | 保留 v1 单机策略，团队模式另议 |
| PromptFlow + Azure 部署 | 依赖太重，本平台已有 LangChain 替代链路 | 不引入 |
| 用 Agent 发起"更新 issue"工具调用来触发 HITL 中断 | 处置动作由用户发起，无需 LLM 构造 | 见 §4.2 两档实现 |

---

## 2. 数据契约细化（v2）

### 2.1 风险实例（Issue）— 采纳参考模型 + 证据链

```jsonc
{
  "id": "issue_8f2a_liability-cap_3",
  "job_id": "job_8f2a",
  "doc_id": "batch_b3_doc_7",
  "filename": "解除_终止劳动合同协议书7.pdf",

  // —— 规则证据链（v1 要求，参考项目缺失，必须补齐）——
  "rule_id": "labor-compensation",
  "rule_version": "sha256:9f1c…",
  "rule_title": "经济补偿计算",

  // —— 类型与风险等级（参考模型）——
  "type": "Definitive Language",        // 内置类型名 或 自定义规则名
  "risk_level": "高",                   // 高|中|低，由规则定义决定

  // —— 内容（参考模型）——
  "text": "我们保证100%的投资回报率",    // 问题原文片段
  "explanation": "使用了绝对化表述'保证'，可能造成法律风险",
  "suggested_fix": "建议修改为'预期…可达'",

  // —— 位置证据（参考模型 + v1 锚点）——
  "location": {
    "source_sentence": "…完整段落原文…",
    "page_num": 3,
    "bounding_box": [0,0,0,0,0,0,0,0],  // PDF quadpoints 8*n
    "para_index": 17,
    "block_id": "block-42",             // DOCX/非 PDF 锚点
    "section_path": ["第三条", "经济补偿"]
  },

  // —— 来源与置信（v1）——
  "confidence": "rule_deterministic" | "llm_yes" | "llm_unknown",

  // —— 处置（参考模型）——
  "status": "not_reviewed",             // not_reviewed|accepted|dismissed
  "review_initiated_by": "local",
  "review_initiated_at_UTC": "2026-08-15T02:00:00Z",
  "resolved_by": null,
  "resolved_at_UTC": null,
  "modified_fields": null,              // {suggested_fix?, explanation?} 采纳时人工修改
  "dismissal_feedback": null,           // {reason?} 驳回理由
  "audit": []                           // 处置审计事件（派生视图；事实源为 jobs/{job_id}/audit.jsonl）
}
```

> 产品术语统一为**风险**（与现有前端原型 RiskCard 一致）；`Issue` 仅作为代码/契约命名保留。

处置状态机 v1 的 `open/approved/rejected/ignored` **收敛为参考模型的 3 态**：

```text
not_reviewed ──accept(可带 modified_fields)──▶ accepted
     │
     └──dismiss(必带/可选 reason)──▶ dismissed   （"忽略"用 reason 表达）
```

验收口径：100% 风险实例满足 `rule_version + location(source_sentence/定位器) + explanation + suggested_fix` 非空。

### 2.2 规则模型 — 采纳"规则即检查项"

```jsonc
{
  "id": "definitive-language",
  "name": "Definitive Language",
  "group": "compliance",                // v1 保留：finance|compliance|operations
  "description": "在正式承诺或保证语境中使用'必须/保证/一定/完全/绝对'等过度确定措辞。",
  "risk_level": "高",
  "examples": [                         // few-shot，注入 prompt（参考模型）
    { "text": "我们保证100%的投资回报率", "explanation": "绝对化承诺，应改为预期表述" }
  ],
  "status": "active",
  "created_at": "2026-08-01",
  "updated_at": null,
  // —— v1 确定性通道（可选，缺省 null 表示纯 LLM 检查项）——
  "matcher": null | { "text_pattern": […], "scope": {…}, "numeric": {…} },
  "threshold": null,
  "llm_fallback": true,                // 确定性未命中时是否进入 LLM 检查（成本开关）
}
```

文档级启停采用参考的关联模型：`DocumentRuleAssociation{doc_id, rule_id, enabled}`，由范本提供默认值。用户可在步骤三调整：默认仅存**会话草稿**，点"保存配置"才 PUT 持久化关联；**创建任务时总是固化快照**（保留 v1"配置只存草稿"原则）。

### 2.3 Location 契约

- **PDF**：`bounding_box` 采用 PDF quadpoints 规范（8\*n 坐标，origin=页面左下），直接供前端 PDF 高亮。
- **DOCX / 无稳定分页**：`bounding_box` 可为空，使用 `block_id + section_path + para_index` 锚点（v1 引用契约）。
- **`para_index` 为文档内绝对段落索引**（参考项目是 chunk 相对索引，不直接沿用）；LLM 输出的相对索引回填规则：绝对 = chunk 起始段索引 + 相对值。
- 规则：`location.source_sentence` 必须能在批次文档原文中精确复现（规范化空白后），否则该风险不可产出。

---

## 3. 审查引擎细化（v2）

### 3.1 双通道规则执行

```text
每条启用规则 → 先尝试确定性匹配器（v1）
   ├─ 命中/判定 → 直接产出风险（confidence=rule_deterministic），零 LLM 成本
   └─ 未命中 且 规则 llm_fallback=true（默认：高严重度 true / 低严重度 false）
        → 进入 LLM 检查项（参考模式）；llm_fallback=false 的规则未命中直接无风险
        ├─ 系统提示：允许报告的问题类型列表（内置 + 启用规则名）
        ├─ 指导段：反误报排除规则 + 每规则 few-shot examples（≤3 条）
        ├─ 输入：分块段落 "[i]段落内容"（pagination，默认 32 段/块）
        ├─ 输出：Pydantic 结构化 {issues:[{type,text,explanation,suggested_fix,para_index}]}
        └─ 产出 → 按规则 risk_level 定级，confidence=llm_yes|llm_unknown
```

**成本控制**：任务创建时按 文档数 × 启用规则数 ×（llm_fallback=true 的规则数）预估 LLM 调用上限，控制台展示预估量；确定性命中越多的规则组合成本越低。

**反误报排除规则**（直接移植参考项目，扩展中文合同场景，写入引擎内置常量，同时注入 prompt 与确定性过滤层）：

1. 序号与编号：`1.` `(1)` `（一）` `①` `a.` 及孤立数字/字母；
2. 表单占位符：`____年__月__日`、`___元`、下划线待填字段；
3. 勾选框与选项符号：`口 □ ☐ ○ ◯`；
4. 格式化标记：冒号、破折号、分隔线；
5. 合同/表单标准文本：甲方、乙方、签字、盖章、工资结算、发放等；
6. 金额/日期上下文误判：纯数字段落、带单位的孤立数值。
7. 原则：**不确定宁可不报**；确定性过滤层对命中以上模式的候选直接丢弃。

**LLM 输出健壮性**：结构化解析失败时重试 1 次（换宽松提示词）；仍失败则记录 `job.errors[]`（chunk 级、可重试）并在前端标注"该块未完成"，禁止静默丢弃（参考项目 `return []` 的静默行为不采纳）。

### 3.2 证据定位 3 级回退（PDF）+ DOCX 锚点

```
候选文本 = raw.text（问题片段）→ 段落原文 → 去空格变体 → 截断前 12 字符
   │
   ├─ 级1：PDF 文本层（PyMuPDF page.search_for）→ 直接命中 → quadpoints
   ├─ 级2：MinerU layout.json span 级 bbox
   │        span 精确匹配 → 子串按字符宽度权重定位 → 跨 span 合并 → 行级回退 → 模糊匹配
   ├─ 级3：段落 bbox 经 bbox_to_quadpoints 转换（origin/units/content_coverage 可配置）
   └─ 兜底：空 quadpoints（前端不显示高亮但风险仍可展示）
DOCX：用 block_id + para_index 定位，不做 bbox。
```

实现迁移：参考项目的 `bbox.py`（bbox_to_quadpoints、字符宽度权重、span 匹配）与 `lc_pipeline.py` 中的 `_find_pdf_quadpoints / _find_layout_quadpoints / _find_span_match / _substring_bbox_from_line` 可直接移植到 `backend/services/review/`。

### 3.3 任务执行与流式

- 参考项目"逐块流式产出"与 v1"任务状态机"**合并**：
  - `POST /jobs` → `queued → parsing → running`；`running` 期间每处理完一块，持久化该块风险并推送到 `GET /jobs/{id}/stream`（SSE，`event: issues`）。
  - 前端控制台打开时订阅 stream 增量渲染；刷新页面时轮询 `GET /jobs/{id}` + `GET /jobs/{id}/risks` 恢复全量（幂等，已存风险直接返回）。
  - `event: issues` 携带**空数组**表示"该块无发现"，前端必须视为正常进度而非错误；任务级"零风险"在 complete 时展示空态。
  - 终态：`complete | failed | cancelled` 三选一；`cancelled` 保留已产出风险。
- **任务快照**：含 `llm_model`（规则 LLM 检查用 fast 模型，参考项目 temperature=0.2）+ 灵敏度 + 启用规则 + 规则版本；问答助手/报告用 pro 模型（v1 §6.1 模型选择落地）。
- **重审**：`POST /jobs/{id}/rerun`（异步）：删除该任务已有风险后重跑，用于"调整规则后重审"。参考项目的 `GET?force=true` 属副作用 GET，不采纳。
- **任务级定稿**：全部风险处置完毕后触发"定稿"，生成只读报告快照（对应原型 approveDraft/rejectChanges 的整单语义）。

---

## 4. 人工处置细化（v2）：HITL 门

### 4.1 参考项目的 HITL 语义（保留）

- 任何写操作（accept/dismiss）先产生"提议操作"（proposed_action），等待人工三选一：
  - **approve 批准**：按提议执行；
  - **edit 修改**：提供 `edited_action`（仅允许编辑 `suggested_fix/explanation`，强制绑定 risk_id）；
  - **reject 拒绝**：必须带 `message`（写入 dismissal_feedback.reason）。
- 决策完成后写库并追加审计事件。

### 4.2 两档实现（按团队技术选型选择）

| 档位 | 实现 | 适用 |
| --- | --- | --- |
| A. 轻量状态机（推荐，单机） | 后端直接构造 proposed_action + 中断状态，`start → resume` 两个 REST 调用；不引入 LangChain Agent 依赖，语义与参考完全一致，可单测 | 本平台单机、无 LangChain 依赖 |
| B. 完整 LangChain HITL（可选） | 移植参考 `hitl_agent.py`：`create_agent + HumanInTheLoopMiddleware(interrupt_on={"update_issue": True}) + InMemorySaver`；`start_update → __interrupt__ → Command(resume={decisions:[…]})` | 团队想统一 LangChain 技术栈时 |

接口保持一致，两档可互换：

```text
POST /api/review/risks/{risk_id}/decisions/start
     body {action: "accept"|"dismiss", modified_fields?, dismissal_feedback?}
     → {thread_id, interrupt_id, proposed_action:{name:"update_risk", args:{…}}}

POST /api/review/risks/{risk_id}/decisions/resume
     body {thread_id, interrupt_id?, decision: {type:"approve"|"edit"|"reject", …}}
     → {risk}   // 更新后的完整风险实例
```

安全约束（移植参考）：edit 决策只允许编辑 `update_risk` 工具且 args 强制绑定 `risk_id`；reject 必须带 reason；任何决策写入 `jobs/{job_id}/audit.jsonl`（事实源，追加式），`issue.audit[]` 为派生视图。

---

## 5. 评测体系细化（v2）

移植参考项目 `eval/` 到 `backend/eval/`，作为决策门指标测量工具：

```text
backend/eval/
├── issue_associator.py    # 检测结果 ↔ 金标 文本相似度关联（阈值可配）
├── metric_calculator.py   # 按类型分组 TP/FP/FN、精确率/召回率/F1
└── tests/                 # 与参考项目同构的关联与指标单测
```

- 金标格式：`eval/gold/{doc_id}.json` = `[{type, text, explanation, location?}]`（双人标注、第三方裁决）。
- 关联算法：规范化空白后的文本相似度（SequenceMatcher，阈值默认 0.85），同文档同类型才可关联。
- 输出报表：按类型 + 总体：高风险召回率/精确率、F1、未关联检出（FP 清单）、漏报（FN 清单）。
- 接入：`scripts/eval_review.py --gold-dir eval/gold --jobs-dir .review_data/jobs`，输出与指标字典（§10.5）绑定的版本化 JSON。
- 决策门指标（v1 §10.2）用该工具实测：高风险召回率 ≥90%、精确率 ≥80%。

---

## 6. 纵切类型更新：劳动合同解除协议

参考项目实战验证的文档类型是**解除、终止劳动合同协议书**（种子文档 24+ 份），与本平台"保险/法规"领域相邻，且**已有大量可授权标注语料**，直接缓解决策门"≥30 份标注文档"的最硬前置。

- 首个纵切类型：**劳动合同解除/终止协议书**（替换 v1 建议的 MSA，保留 MSA 为二期候选）。
- 首集规则（10–20 条，由易到难）：
  1. 内置通用：`Definitive Language`（绝对化表述，高）、`Grammar & Spelling`（语法拼写，低）——参考项目已验证；
  2. 劳动合规（确定性 + LLM 混合）：经济补偿计算基数/年限、N/N+1 表述、竞业限制期限与补偿、违约金条款、30 天通知期、加班工资结算、社保公积金结清、保密义务期限；
  3. 文档完整性与一致性：金额大小写不一致、日期缺失、落款主体与合同抬头不一致（确定性匹配器主攻）。
- 种子数据：参考项目 `app/data/documents/` 的解除协议 PDF + MinerU JSON 作为评测集雏形；再按 §5 金标格式标注。
- 范本：`劳动合同解除协议审查 v1`（内置，规则引用上述列表，版本锁定）。

---

## 7. API 契约更新（v2）

在 v1 契约基础上新增/调整：

```text
# 规则管理（参考项目）
GET    /api/review/rules                     → 规则列表（内置 + 自定义）
POST   /api/review/rules                     → 创建规则 {name, description, risk_level, examples, group?, matcher?}
PATCH  /api/review/rules/{rule_id}           → 更新（生成新 rule_version；已引用该规则的任务不受影响）
DELETE /api/review/rules/{rule_id}           → 删除（被范本引用时拒绝，返回 409）

# 文档-规则关联（参考项目，步骤三数据源）
GET    /api/review/batches/{batch_id}/docs/{doc_id}/rules   → [DocumentRuleAssociation]
PUT    /api/review/batches/{batch_id}/docs/{doc_id}/rules/{rule_id}  {enabled}

# 任务流式与重审
GET    /api/review/jobs/{id}/stream          → SSE（event: issues | complete | error）
POST   /api/review/jobs/{id}/rerun           → 删除旧风险并重跑（异步，配合 stream/轮询）

# 处置（§4）
POST   /api/review/risks/{risk_id}/decisions/start
POST   /api/review/risks/{risk_id}/decisions/resume
```

前端 SSE 事件类型对齐参考：`issues`（增量风险数组）/ `complete` / `error`。

---

## 8. 前端集成细化（v2）

- **控制台文档阅读区**：PDF 用 pdf.js 渲染 + `bounding_box` quadpoints 高亮（选中风险时）；DOCX 用 v1 预览 DOM 锚点高亮。参考项目 UI 的标注交互（点风险 → 高亮原文）作为验收参照。
- **风险卡片**：`risk_level` 显示 高/中/低 标签；`confidence` 来源角标（规则命中 / AI 确认 / 待人工确认）；`type` 展示规则名。
- **处置交互**：卡片操作 → 弹出处置对话框：采纳（可编辑 `suggested_fix/explanation` → modified_fields）、驳回（必填理由 → dismissal_feedback.reason）；提交走 `decisions/start → resume`，中途可取消。现有原型 RiskCard 的 `RiskAction='pending'|'accepted'|'dismissed'` 与 v2 处置 3 态一致，无需改语义，仅把演示数据替换为真实 API。
- **任务级定稿**：全部风险处置完毕后提供"定稿并生成报告"（整单语义，与单条处置区分），定稿后报告只读快照。
- **流式体验**：审查运行中风险卡片增量出现（订阅 stream），顶部显示"已检查 X/Y 块、已发现 Z 条"。
- **重审入口**：任务完成后提供"调整规则重审"（`POST /jobs/{id}/rerun`）。
- 其余（批次上传、范本、规则配置、问答助手、报告）按 v1 不变。

---

## 9. 实施阶段调整（v2）

| 阶段 | 内容 | 参考项目迁移物 |
| --- | --- | --- |
| 0 数据模型与契约 | review 存储 + schemas + rules CRUD 契约测试 | `common/models.py` 的 Issue/Rule/Location 结构 |
| 1 审查引擎 | 确定性匹配器 + LLM 检查项 + 反误报规则 + 分块流式 | `lc_pipeline.py` 的 prompt 构造与分块（**不迁移其 mineru_client，复用本平台现有 MinerU 解析链路**）；`bbox.py` |
| 2 任务与 API | Job 状态机 + SSE stream + rerun 重审 + 处置两档实现 | `issues.py` 的 SSE/error 语义、HITL 参考实现 |
| 3 前端接入 | 批次/范本/规则页接 API；控制台流式 + PDF 高亮 + 处置对话框 | 参考 UI 的 PDF 标注交互语义 |
| 4 评测与验证 | `backend/eval/` 移植 + 金标标注 + 指标实测 + 三视口/E2E | `eval/src/issue_associator.py`、`metric_calculator.py` |
| 5（可选） | 完整 LangChain HITL 中间件档位 B | `hitl_agent.py` |

依赖顺序：0 → 1 → 2 → 3 → 4；档位 B 可并行准备。

## 10. 决策门 checklist 更新

- [ ] 合同类型冻结为**劳动合同解除/终止协议书**（参考项目种子语料佐证可行）
- [ ] ≥30 份标注文档：参考项目 24 份种子 + 补充 ≥6 份并完成 §5 金标格式标注
- [ ] 参考项目 24 份解除协议 PDF 的**授权使用**已确认（课程资料许可范围；无法确认则改用自备文档补齐 30 份）
- [ ] 规则所有人（`legal-core`）与更新流程确认；规则首集 10–20 条按 §6 冻结
- [ ] 召回/精确率目标：高风险召回 ≥90%、精确 ≥80%，用 §5 工具实测
- [ ] 部署模式确认（单机 loopback；团队模式另加认证/审计）
- [ ] HITL 实现档位选择（A 轻量 / B 完整 LangChain）

## 11. 文档自检

- [x] 参考项目 9 项已验证机制逐条映射到落地位置。
- [x] 明确不借鉴项及原因（纯 LLM 规则、无版本、单文档、Azure 依赖、副作用 GET、静默丢块）。
- [x] 风险实例、规则、Location 契约细化到字段级，处置状态机收敛为参考 3 态（与前端 RiskCard 对齐）。
- [x] 引擎双通道（含 llm_fallback 成本开关）、反误报规则、证据定位 3 级回退、分块流式均有明确实现迁移路径。
- [x] HITL 提供两档实现且接口一致可互换。
- [x] 评测工具、金标格式、决策门指标绑定到具体模块与脚本。
- [x] 纵切类型更新为劳动合同解除协议，种子语料来源与授权风险明确。
- [x] `para_index` 绝对/相对语义、审计单一事实源、LLM 解析失败不静默、任务级定稿、模型入快照均已定义。

## 12. 评审修订记录（2026-08-15）

针对评审发现的 1 阻断 + 3 主要 + 8 次要问题全部修订：

| 级别 | 问题 | 修订 |
| --- | --- | --- |
| 阻断 | `GET ?force=true` 副作用 GET + 同步阻塞 | 改为 `POST /jobs/{id}/rerun` 异步重审（§3.3/§7/§8） |
| 主要 | v1 与 v2 文档冲突未标注 | v1 头部增加 v2 覆盖对照（见 v1 文档） |
| 主要 | `para_index` 绝对/相对语义歧义 | 定义为文档内绝对索引，LLM 相对值按 chunk 偏移回填（§2.3） |
| 主要 | 确定性未命中全部进 LLM，成本不可控 | 增加 `llm_fallback` 规则级开关 + 任务 LLM 调用预估（§2.2/§3.1） |
| 次要 | 审计双写 | `audit.jsonl` 为事实源，`issue.audit[]` 为派生视图（§2.1/§4.2） |
| 次要 | LLM 解析失败静默丢块 | 重试 1 次 + 记 `job.errors[]` + 前端标注，禁止静默（§3.1） |
| 次要 | 种子文档授权未确认 | 决策门 checklist 增加授权确认项（§10） |
| 次要 | 步骤 3 写操作与 v1"配置只存草稿"矛盾 | 明确：保存配置才 PUT 关联，任务创建总是快照（§2.2） |
| 次要 | 任务级定稿缺失 | 补充"定稿并生成报告"整单语义（§3.3/§8） |
| 次要 | 模型选择未入契约 | 任务快照含 llm_model（规则用 fast、问答/报告用 pro）+ temperature=0.2（§3.3） |
| 次要 | 空风险流未定义 | `event: issues` 空数组=正常进度，complete 时展示零风险空态（§3.3） |
| 次要 | 术语混用 | 产品术语统一为"风险"，Issue 仅作契约命名（§2.1） |
