# 智能审查问答助手（FR-07）产品需求文档

> 日期：2026-08-15  
> 状态：实施基线  
> 优先级：P1  
> 关联：`docs/product/2026-08-15-intelligent-review-prd.md` FR-07  
> 适用范围：智能审查第四步中的单文档上下文问答

## 1. 背景与目标

现有 `ReviewAssistant` 只把审查任务的第一条风险摘要包装成回答，未检索用户选中的文档原文，也不能证明引用来自该文档。FR-07 要建立一个可核验的单文档问答闭环：用户在审查任务中明确选择一份文档，助手只基于该文档的固定版本回答；回答引用必须与该版本原文逐字一致并能定位；没有足够证据时明确拒答；流式请求必须且只能产生一个终态事件。

本功能的首要质量目标不是回答覆盖面，而是可验证性。系统不得用审查风险摘要、其他批次文档、模型常识或网络内容补齐证据缺口。

## 2. 用户与场景

主要用户为合同审查人员、法务和法规研究人员。

典型流程：

1. 用户进入已创建的审查任务。
2. 用户从任务包含的文档中选择一份文档。
3. 用户提出关于该文档条款、金额、日期、责任或风险的问题。
4. 助手流式返回答案，并在完成时返回一个或多个结构化引用。
5. 用户点击引用，文档阅读区定位到对应页码、块或段落锚点并高亮原文。
6. 如果原文不足以回答，助手明确说明“当前文档未提供足够依据”，不生成推测性答案。

## 3. 范围

### 3.1 本期范围

- 审查任务内选择一份文档，问答会话绑定该文档 membership 和不可变 document version。
- 在 Elasticsearch 中执行 BM25 + 向量 + RRF 混合检索，并强制按 `document_id` 与 `document_version_id` 过滤。
- Elasticsearch 不可用时允许从同一文档版本 IR 做确定性词法降级检索；不得扩大到任务内其他文档。
- 使用检索到的原文块构建 LLM 上下文；禁止网络补充。
- 服务端从原文块生成引用并做逐字包含校验，模型不能自行提供引用文本或定位器。
- 基于证据阈值、引用校验和答案可支持性执行拒答。
- SSE 流式返回 `meta`、`status`、`token`、`done|error`，确保唯一终态。
- 前端完成选文档、提问、流式显示、停止、失败/拒答状态、引用点击定位。
- 扩展离线金标和评测脚本，输出可复跑报告到 `.eval_reports/`。

### 3.2 非目标

- 不做跨文档比较、批次汇总问答或全知识库问答。
- 不使用 Tavily、互联网资料、模型常识补充或风险规则文本作为回答依据。
- 不生成法律结论或替代人工法律意见。
- 不在本期实现对话长期记忆检索；历史消息只用于界面连续性，不改变文档范围。
- 不承诺回答原文没有直接表达的推理题、计算题或预测题。
- 不改造通用 `/api/chat` 问答链路。

## 4. 核心约束

### 4.1 单文档与版本隔离

- 创建会话必须提交 `document_membership_id`。
- 服务端验证 membership 属于 `analysis_job_id` 对应批次，且文档状态可问答。
- 会话持久化 `document_id`、`document_version_id`、`document_membership_id` 和 `filename` 快照。
- 后续提问不得通过请求体切换文档；切换文档必须创建或切换到另一会话。
- 检索查询必须同时包含 `document_id` 和 `document_version_id` filter。缺失版本字段的旧索引结果不得进入上下文。
- 引用、消息和评测结果均记录同一文档版本，保证结果可复现。

### 4.2 原文与回答边界

- `quote` 只能由服务端从已加载的文档 IR block 原文切片得到。
- 引用生成后必须通过 `quote in canonical_block_text` 的精确字符串校验，不做空白归一化后替换原文。
- LLM 只输出答案正文和所依据的候选引用编号；服务端以候选编号映射到可信引用。
- 若答案包含可核查主张但没有通过校验的引用，整个回答降级为拒答。
- 非拒答回答至少有一个引用；每个核心主张必须被一个或多个引用直接支持。

## 5. 交互定义

### 5.1 文档选择

- 问答 Tab 顶部显示当前文档选择器，选项仅来自当前分析任务的文档。
- 默认选择当前阅读区文档；若任务只有一份文档则显示固定文档名。
- 切换文档时切换到该文档已有会话，若不存在则创建新会话；消息区不得混合不同文档的回答。
- 未选择文档、文档解析未完成、版本不可用时禁用输入并显示可恢复状态。

### 5.2 提问与流式回答

- 提交后立即追加用户消息和空的助手消息，输入框进入生成状态。
- `status=retrieving` 显示“正在检索当前文档”，`status=generating` 显示“正在组织回答”。
- `token` 只追加到当前 `request_id` 的助手消息。
- `done` 后显示回答、拒答状态和引用；`error` 后显示可重试错误，不保存为普通答案。
- 用户停止请求后，服务端以一个 `error` 终态返回 `code=request_cancelled`；前端保留已显示文本但标记未完成，不展示未验证引用。

### 5.3 引用定位

- 每条引用显示文件名、页码或章节/块标签以及原文短摘录。
- 点击 PDF 引用时定位到 `page_number`，有精确矩形时高亮 `rects`。
- 点击 DOCX 引用时按 `locator_id` 或 `block_id` 定位；缺少精确锚点时允许定位到 block，但必须标注 `precision=block`。
- 定位目标不存在、版本已删除或引用校验失败时显示“引用位置不可用”，不得静默跳到相似文本。

### 5.4 拒答

标准拒答文案：

> 当前文档未提供足够依据，无法可靠回答该问题。请核对问题是否针对所选文档，或查看文档原文。

以下情况必须拒答：

- 检索没有命中满足阈值的同版本原文块。
- 问题要求其他文档、外部事实、实时信息或主观预测。
- LLM 输出无法由候选证据直接支持。
- 所有候选引用均未通过逐字包含或定位校验。
- 文档 IR 或指定版本不可读取。

拒答以 `done` 正常终态返回，`refused=true`、`refusal_code` 非空、`citations=[]`。基础设施错误使用 `error` 终态，不伪装为拒答。

## 6. API 契约

API 前缀沿用 `/api/review`。

### 6.1 创建会话

`POST /analysis-conversations`

请求：

```json
{
  "analysis_job_id": "job-uuid",
  "document_membership_id": "membership-uuid"
}
```

成功响应 `201`：

```json
{
  "id": "conversation-uuid",
  "analysis_job_id": "job-uuid",
  "document_membership_id": "membership-uuid",
  "document_id": "doc-uuid",
  "document_version_id": "sha256",
  "filename": "合同.pdf",
  "revision": 0,
  "messages": []
}
```

服务端对 job、batch membership 和 document version 做关联校验；不匹配返回 `409 document_scope_mismatch`，不可问答返回 `409 document_not_ready`。

### 6.2 流式提问

`POST /analysis-conversations/{conversation_id}/stream`

请求：

```json
{
  "request_id": "client-generated-uuid",
  "message": "合同约定的付款期限是多少？",
  "finding_id": null,
  "history": []
}
```

`request_id` 在会话内幂等。重复已完成请求返回相同持久化结果，不再次调用模型；同一请求正在执行时返回 `409 request_in_progress`。

### 6.3 引用结构

```json
{
  "citation_id": "citation-uuid",
  "document_id": "doc-uuid",
  "document_version_id": "sha256",
  "filename": "合同.pdf",
  "block_id": "b42",
  "chunk_id": 17,
  "section_path": ["第五章", "付款"],
  "quote": "乙方应在收到发票之日起三十日内付款。",
  "quote_start": 0,
  "quote_end": 21,
  "locator": {
    "kind": "pdf",
    "page_number": 6,
    "precision": "exact",
    "rects": []
  }
}
```

不允许只返回 `chunk_id`、风险标题或模型生成摘要作为引用。

## 7. SSE 契约

响应头：`Content-Type: text/event-stream`、`Cache-Control: no-cache`、`X-Accel-Buffering: no`。每个事件 `data` 为 JSON。

允许的事件序列：

```text
meta -> status(retrieving) -> status(generating)? -> token* -> done
meta -> status* -> error
```

事件定义：

| 事件 | 是否终态 | 必填字段 | 语义 |
| --- | --- | --- | --- |
| `meta` | 否 | `request_id`、文档三个 scope ID | 确认请求与固定文档范围 |
| `status` | 否 | `request_id`、`type` | `retrieving` 或 `generating` |
| `token` | 否 | `request_id`、`content` | 已生成但尚未成为最终记录的正文增量 |
| `done` | 是 | `request_id`、`answer`、`refused`、`citations` | 成功回答或业务拒答 |
| `error` | 是 | `request_id`、`code`、`message`、`retryable` | 取消、依赖或内部错误 |

硬性语义：

- 一个请求必须恰好产生一个终态事件，终态集合为 `{done,error}`。
- 终态后生成器立即结束，不得再发送 token、heartbeat 或第二个终态。
- 正常回答：`done.refused=false` 且 `citations.length>=1`。
- 拒答：`done.refused=true`、`citations=[]` 且 `refusal_code` 非空。
- `error` 不得同时持久化一条状态为 complete 的助手消息。
- 客户端断连和 stop 共享取消信号；如连接仍可写则发送唯一 `error(request_cancelled)`，否则在服务端记录取消终态。

## 8. 检索、上下文与拒答策略

### 8.1 检索

- 复用 `backend/services/search.py` 的 embedding、BM25、向量和 RRF 算法。
- 新增文档范围参数对象，不允许调用方省略版本范围。
- ES BM25 `bool.filter` 与 kNN filter 均指定 `doc_id`、`document_version_id`、`is_visible=true`。
- 候选结果按 RRF 排序后回源 IR，使用 block/chunk 标识解析规范原文和 locator。
- 默认取前 6 个候选，单块最多 1800 字，总上下文最多 8000 字；截断只影响模型上下文，不改变引用中的原文。

### 8.2 证据门

以下任一条件成立则证据不足：

- 候选为空。
- 所有候选 BM25/向量均无有效命中，或 RRF 只含单路弱命中且问题关键词与原文无交集。
- 回源后 candidate 版本、block 或 quote 校验失败。
- 模型未选择任何候选引用或答案引用了候选外编号。

阈值作为命名配置进入报告，不把 provider 原始分值当跨模型稳定概率。评测未通过前只允许收紧阈值，不允许为提高回答率放宽引用校验。

### 8.3 LLM 输出

模型使用温度 `0`，输出结构化 JSON：`answer`、`citation_refs`、`refused`，其中 `citation_refs` 只能包含候选编号，不能包含 quote 或 locator。系统提示明确要求仅使用给定证据、保持数值与专有名词、证据不足拒答。服务端根据候选编号从规范原文确定性选取完整句或完整块并生成 quote/span；解析失败、引用越界或答案无法校验时拒答，不直接透传模型原始文本。

## 9. 数据与审计

- conversation 保存固定文档范围和 revision。
- assistant message 保存最终 `answer`、`refused`、`refusal_code`、完整 citations、模型与检索配置版本。
- 每个请求保存 `request_id`、开始/终态时间、终态类型、候选 block IDs、错误码；不保存 provider 密钥或完整 prompt 日志。
- 同一 `request_id` 的持久记录最多一条 assistant message。

## 10. 验收标准

### 10.1 功能验收

1. 当前任务的每份 ready 文档均可独立选择并提问，切换后不会混入其他文档消息或证据。
2. 所有非拒答回答至少有一个可点击引用；点击后打开同一文档版本并定位对应页或块。
3. 每个 `citation.quote` 在引用的规范原文 block 中逐字存在，`quote_start/end` 可精确切片还原 quote。
4. 对文档未包含的信息返回标准拒答，不生成外部知识或猜测。
5. ES 返回其他文档高分结果时不会进入上下文、回答或引用。
6. 正常、拒答、模型失败、检索失败、停止和断连测试中，每个 SSE 请求恰好一个终态。
7. 刷新或重放已完成 `request_id` 不产生重复回答。
8. 前端能展示生成状态、拒答、可重试错误，并能从引用定位阅读区。

### 10.2 质量门槛

| 指标 | 口径 | 门槛 |
| --- | --- | ---: |
| 答案准确率 | 可回答金标中，核心结论、数值和限定条件全部正确的题数/可回答题数 | >=90% |
| 原文引用逐字一致率 | `quote == canonical_text[quote_start:quote_end]` 的引用数/全部引用数 | **100%** |
| 引用定位正确率 | 定位器打开同版本目标且目标包含 quote 的引用数/全部引用数 | >=95% |
| 拒答率 | 实际拒答题数/全部问答题数；作为行为分布报告，不单独设越高越好门槛 | 必须报告 |
| 拒答正确率 | 应拒答题中正确拒答题数/应拒答题数 | >=95% |
| 错误拒答率 | 可回答题中被拒答题数/可回答题数 | <=5% |
| SSE 终态唯一率 | 恰好一个 `{done,error}` 的请求数/全部流请求数 | **100%** |
| 非拒答引用覆盖率 | 带至少一个有效引用的非拒答数/非拒答数 | **100%** |

逐字一致率、SSE 终态唯一率或非拒答引用覆盖率任一低于 100% 均为发布阻断，不以其他指标抵消。

## 11. 测评方案

### 11.1 金标扩展

在 `backend/eval/gold/qa/` 建立版本化单文档问答集和 manifest。每条样本至少包含：

- `question_id`、`doc_id`、`document_version_id`、`question`。
- `answerable` 与拒答理由。
- 可回答题的 `reference_answer`、必含事实/数值、可接受 block IDs 和精确 quote spans。
- 不可回答题的越界类型：其他文档、外部事实、缺失字段、预测/法律判断。

首个评测集至少 30 题，其中可回答题不少于 18 题、应拒答题不少于 10 题，并覆盖 PDF 页码定位和 DOCX block 定位。manifest 记录文件 SHA-256 和数据集 SHA-256。

### 11.2 自动指标

新增 `backend/eval/qa_metrics.py`：

- 逐字引用与 span 校验为确定性比较。
- 定位正确性验证文档版本、block、page/locator 和 quote 包含关系。
- 拒答与 SSE 指标按布尔/计数直接计算。
- 答案准确率使用金标必含事实的规范化精确匹配，并输出逐题失败原因；人工复核边界样本。

`scripts/eval_review.py` 增加 `--qa-run-file`，在原有 metrics/calibration/coverage/regression 之外生成：

- `.eval_reports/qa_metrics.json`
- `.eval_reports/qa_cases.json`
- `.eval_reports/review_qa_report.md`

报告必须记录 git commit、金标 hash、模型/embedding 名称、检索配置、运行时间、分母、失败题和未决项。命令可在无真实 provider 的固定预测模式复跑；真实模型运行另存 run payload 后用同一计算器评分。

### 11.3 缺陷闭环

按以下类别归因并修复后复测：

- 幻觉/无引用主张：收紧 evidence gate 或结构化输出校验。
- 引用不一致：禁止模型 quote，修复 IR 回源或 span 生成。
- 定位错误：修复 locator 映射，不用相似文本兜底。
- 错误拒答：改善单文档召回或同义词处理，不放宽引用校验。
- 漏拒答：提高证据门槛或增加问题范围判断。
- 多终态：统一生成器状态机并补异常/取消测试。

每轮报告写入独立时间戳子目录，同时将最终达标报告复制到 `.eval_reports/review_qa/latest/`。未达标时不得声称完成，必须在报告列出具体失败项、影响和后续动作。

## 12. 风险与防护

| 风险 | 影响 | 防护 |
| --- | --- | --- |
| 旧索引没有 version 字段 | 单文档隔离失效 | 版本 filter 为必需；缺字段结果直接排除并提示重建索引 |
| LLM 改写数字或引用 | 法务结论失真 | temperature=0、候选编号、服务端引用回源与事实校验 |
| ES/Embedding 故障 | 问答不可用 | 同版本 IR 词法降级；仍无证据则拒答或 error |
| stop 与生成并发 | 多终态、脏消息 | request 状态机、原子终态、终态后禁止写入 |
| 引用锚点漂移 | 无法核验 | 固定不可变 version，引用携带 version 和 canonical block ID |
| 为提高回答率降低门槛 | 幻觉上升 | 100% 引用硬门不变，阈值变更进入报告和回归门 |

## 13. 发布与回滚

- 新接口在现有 review API 下兼容扩展；旧的无 `document_membership_id` 创建会话请求返回明确 422，不隐式选择第一份文档。
- 发布前重建目标评测文档索引以包含 version 和 locator 字段。
- 回滚前端可隐藏问答 Tab；后端保留已写 conversation 数据，不降级为旧的风险摘要回答。
- 只有第 10.2 节全部门槛满足且报告可复跑时，FR-07 才标记完成。

## 14. 文档自检

- [x] 范围限定为审查任务中的单文档版本问答。
- [x] 明确文档选择、流式回答、拒答和引用定位交互。
- [x] API、引用和 SSE 唯一终态契约无歧义。
- [x] 引用逐字一致和无依据拒答为硬门。
- [x] 指标包含答案准确率、引用一致率、定位正确率、拒答率/正确率、SSE 唯一终态率。
- [x] 无 TBD、TODO 或依赖隐式产品决定的占位符。
