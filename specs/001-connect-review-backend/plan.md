# Implementation Plan: 智能审查真实后端联通

**Branch**: `main` | **Date**: 2026-07-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-connect-review-backend/spec.md`

## Summary

在不复制现有文档上传、解析、检索、预览、通用问答和前端审查页面的前提下，将当前基于 Mock 数据的四步智能审查流程接入真实后端。现有 `/api/docs/*` 继续作为文档事实源并扩展为不可变版本；新增 `/api/review/*` 领域资源管理批次、来源、范本/规则版本、分析快照、持久异步任务、证据锚点、人工决定、审查问答和 DOCX 导出。分析采用“确定性结构检查 + 版本限定检索 + 结构化语义判定”，所有确定性发现必须经过服务端证据校验。PDF 使用页码和归一化矩形，DOCX 使用稳定段落/表格单元身份与字符范围，保证页面高亮与冻结的审核内容一致。

## Technical Context

**Language/Version**: Python 3.12.4（项目支持 3.10-3.13）；TypeScript 5.6.3；Vue 3.5.40；Node.js 24.13.0；npm 11.8.0

**Primary Dependencies**: FastAPI 0.139.2、Uvicorn 0.51.0、Pydantic 2.13.4、Elasticsearch client 8.19.3、MinerU 3.4.4、httpx 0.28.1、pdfplumber 0.11.10、python-docx 1.2.0；Vue Router 4.6.4、Pinia 2.3.1、Axios 1.18.1、Element Plus 2.14.3、marked 15.0.12、Vite 6.4.3、Vitest 4.1.10

**New Dependencies**: 前端运行时 `pdfjs-dist@5`、`dompurify@3`；前端开发时 `@playwright/test@1`，最终精确版本由 `package-lock.json` 固定；不新增 Python 依赖

**Storage**: 现有 `.data/uploads/` 文件制品和 Elasticsearch 检索索引；新增标准库 SQLite `.data/reviews/reviews.db`（WAL、外键、显式事务）及 `.data/reviews/exports/`

**Testing**: Python `unittest`/现有后端测试；Vitest + Vue Test Utils；Playwright 验证真实 PDF canvas/文本层和 DOCX DOM 高亮；OpenAPI 语法校验

**Target Platform**: Windows 11 本机单用户部署；浏览器前端；单个 Uvicorn worker

**Project Type**: Vue 单页应用 + FastAPI Web 服务 + 独立 MinerU 解析服务

**Performance Goals**: 正常解析且不超过 50 页的单文档，90% 在 5 分钟内产出完整结果；问答 95% 在 3 秒内出现状态或首 token；停止反馈不超过 2 秒；验收样本中 98% 风险首次定位正确

**Constraints**: 单文件 50MB；单批次最多 20 文档；最多 1 个活跃分析任务和 1 个规则提取任务；状态查询是恢复事实源；LLM 不得生成位置真值；运行中任务使用冻结版本；通用 docs/chat API 向后兼容

**Scale/Scope**: 单用户、完整 P1/P2/P3 MVP；列表默认 20、最大 200；不含多人权限、组织审批、电子签署、共同编辑、第三方云盘和外部法律库

## Constitution Check

### Phase 0 前检查

项目 constitution 文件仍为未填充模板，没有可执行的项目级门禁。以下用户约束视为本特性的强制门禁：

| Gate | Result | Evidence |
|------|--------|----------|
| 新功能优先复用源码能力 | PASS | 继续使用 docs 上传/解析/预览、ES 检索、chat SSE/取消和四个审查页面 |
| 已支持能力只做适配 | PASS | 文档版本、范围过滤、共享 SSE/LLM、共享 viewer 均在现有能力上扩展 |
| 不建立第二事实源 | PASS | 审查数据库仅引用 `doc_id + version_id`，不复制文档 IR 或文件 |
| 通用接口向后兼容 | PASS | `/api/docs/*` 增量扩展；`/api/chat/*` 请求和事件语义不变 |
| 结果可复现、证据可核验 | PASS | AnalysisSnapshot 固定输入版本，Finding 落盘前校验证据锚点 |

### Phase 1 后复查

设计仍满足全部门禁。新增 SQLite repository 是完整 MVP 中幂等、异步恢复、版本引用、决定与审计事务的最小必要边界，不替代现有文档存储；新增 review-scoped API 是领域隔离，不重建 docs/chat。新增 viewer 子组件来自现有 `DocPreviewView.vue` 的共享化，知识库预览和审查控制台共同使用。

## Project Structure

### Documentation (this feature)

```text
specs/001-connect-review-backend/
├── spec.md
├── plan.md
├── streaming-findings-plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── contracts/
    ├── review-api.openapi.yaml
    ├── review-analysis-events.md
    └── review-events.md
```

`tasks.md` 不由本命令创建，后续由 `/speckit-tasks` 根据上述设计产物生成。

### Source Code (repository root)

标注 `[adapt]` 的文件必须优先修改复用；标注 `[new]` 的文件仅承载现有模块没有的审查领域职责。

```text
backend/
├── api/
│   ├── main.py                              # [adapt] 注册 review routers；startup/shutdown 启停 runner
│   ├── schemas.py                           # [adapt] 保持 docs/chat DTO 兼容
│   ├── review_schemas.py                    # [new] 审查领域 Pydantic 判别联合与错误模型
│   └── routes/
│       ├── docs.py                          # [adapt] 返回 version_id/file/IR；重析创建版本
│       ├── chat.py                          # [adapt] 使用共享 SSE/取消 helper，保持契约不变
│       ├── reviews.py                       # [new] 批次、分析、finding、决定、审计、导出资源
│       ├── review_rules.py                  # [new] 来源、候选规则、范本/规则版本与配置
│       └── review_chat.py                   # [new] 任务限定的会话、stream、stop
├── services/
│   ├── document_store.py                    # [adapt] 不可变 versions 目录及兼容读取
│   ├── document_pipeline.py                 # [adapt] 版本化 IR、定位字段、ES version metadata
│   ├── indexer.py                           # [adapt] 保存 block_id/version_id/locator_refs/is_current
│   ├── search.py                            # [adapt] 可选 doc/source version 范围过滤
│   ├── qa_service.py                        # [adapt] 复用共享模型传输；通用行为不变
│   ├── parallel_qa.py                       # [adapt] 复用共享模型传输
│   ├── llm_client.py                        # [new/shared] 从现有 QA 抽取 HTTP、超时和流式模型调用
│   ├── sse.py                               # [new/shared] 从 chat 抽取 framing、取消 registry、request ID
│   ├── review_store.py                      # [new] SQLite schema/repository/事务/幂等/租约
│   ├── review_service.py                    # [new] 审查用例编排和资源状态约束
│   ├── review_analysis.py                   # [new] 结构检查、受限检索、语义判定、冲突合并
│   ├── review_rules.py                      # [new] 候选提取、人工确认、不可变发布
│   ├── review_qa.py                         # [new] snapshot/finding 限定的多轮问答
│   ├── review_jobs.py                       # [new] 持久 job runner、租约、恢复、并发限制
│   └── evidence.py                          # [new] PDF/DOCX anchor 建立、校验与降级
└── tests/
    ├── test_document_versions.py            # [new]
    ├── test_evidence_anchors.py              # [new]
    ├── test_review_store.py                  # [new]
    ├── test_review_api.py                    # [new]
    ├── test_review_analysis.py               # [new]
    ├── test_review_qa.py                     # [new]
    └── test_review_jobs.py                   # [new]

mineru_service/
└── adapter.py                               # [adapt] 透传 MinerU page/bbox，不另建解析器

frontend/
├── package.json                             # [adapt] pdfjs-dist、dompurify、Playwright
├── package-lock.json                        # [adapt] 固定依赖版本
├── src/
│   ├── api/
│   │   ├── http.ts                          # [adapt] 兼容 string/object detail
│   │   ├── docs.ts                          # [adapt] 文档版本、file、结构化预览
│   │   ├── chat.ts                          # [adapt] 使用共享 SSE decoder，通用签名不变
│   │   ├── review.ts                        # [new] `/api/review/*` typed client
│   │   └── sse.ts                           # [new/shared] 从 chat.ts 抽出的唯一 SSE decoder
│   ├── stores/
│   │   └── review.ts                        # [adapt] 唯一审查 store，移除 Mock，持久资源 ID
│   ├── types/
│   │   └── index.ts                         # [adapt] review API/anchor/job 判别联合
│   ├── utils/
│   │   └── safeMarkdown.ts                  # [new/shared] marked + DOMPurify 单一安全入口
│   ├── components/
│   │   ├── ChatMessage.vue                  # [adapt] 安全 Markdown
│   │   ├── document/
│   │   │   ├── DocumentViewer.vue           # [new/shared] 根据格式分派、选择/定位事件
│   │   │   ├── PdfEvidenceViewer.vue        # [new] PDF.js canvas/text/overlay
│   │   │   └── DocxEvidenceViewer.vue       # [new] 结构化 IR 与 locator DOM
│   │   └── review/
│   │       ├── ReviewAssistant.vue           # [adapt] review conversation API
│   │       ├── RiskCard.vue                  # [adapt] Finding + decision
│   │       ├── ClauseCard.vue                # [adapt] RuleCandidate/RuleVersion
│   │       └── TemplateCard.vue              # [adapt] TemplateVersion
│   └── views/
│       ├── DocPreviewView.vue                # [adapt] 改用共享 DocumentViewer
│       └── review/
│           ├── ReviewUploadView.vue          # [adapt] docs + batch 资源
│           ├── ReviewTemplatesView.vue       # [adapt] template API 与匹配建议
│           ├── ReviewRulesView.vue           # [adapt] rules/config API
│           └── ReviewConsoleView.vue         # [adapt] job/findings/viewer/QA/decision/export
└── tests/e2e/
    └── review-highlighting.spec.ts           # [new] PDF/DOCX 坐标与双向选择
```

**Structure Decision**: 保留现有 `backend + frontend + mineru_service` 三部分布局和现有四个审查路由。审查业务通过薄路由、用例服务、repository 和持久 runner 分层；文档制品仍由 docs/pipeline 管理，ES 仍只负责召回。前端只增加一个 API client 和共享 viewer/SSE/Markdown 基础件，不增加第二个 store、第二套页面或第二条文档管线。

## Existing Capability Reuse Matrix

| Business capability | Existing source | Planned adaptation | Explicitly prohibited duplicate |
|---------------------|-----------------|--------------------|---------------------------------|
| 上传/格式/50MB 校验 | `api/routes/docs.py` | 审查上传调用同一接口，返回 current version | `/review/documents/upload` |
| 文档元数据/制品 | `document_store.py` | 版本目录和兼容迁移 | review DB 复制 IR/原文件 |
| 解析/IR/分块 | `document_pipeline.py`、`mineru_service/adapter.py` | 保留 bbox、DOCX locator、版本化写入 | 第二解析服务 |
| 检索 | `search.py`、`indexer.py` | 增加版本范围过滤和 locator metadata | 独立 review 搜索索引客户端 |
| 模型调用 | `qa_service.py`、`parallel_qa.py` | 抽取 `llm_client.py` 后共同复用 | review 内自写 HTTP client |
| SSE/停止 | `api/routes/chat.py`、`api/chat.ts` | 抽共享 framing/decoder/cancel registry | 第二套事件解析器 |
| 文档预览 | `DocPreviewView.vue` | 抽 `DocumentViewer`，两处共同使用 | 审查专属独立预览协议 |
| 审查状态 | `stores/review.ts` | 替换 Mock action 为 API action | 新建 parallel review store |
| 四步界面 | `views/review/*.vue` | 保留布局和导航，绑定真实资源 | 新建重复页面 |

## Core Data Flows

### 1. 待审文档上传与版本冻结

```text
ReviewUploadView
  -> existing POST /api/docs/upload
  -> docs.py validates PDF/DOCX and 50MB
  -> document_pipeline parses via MinerU or existing fallback
  -> document_store writes immutable versions/{version_id}/ir.json
  -> indexer writes chunks carrying version_id + locator_refs
  -> frontend polls existing document status
  -> POST /api/review/batches/{batch_id}/documents references doc_id + version_id
```

批次只引用已 `ready` 的不可变版本。重析创建新 `version_id`，不会改变已加入快照的历史版本。旧文档制品首次读取时可被兼容层识别；只有显式重析/迁移才生成精确定位版本。

### 2. 范本/规范来源形成规则

```text
existing docs upload/parse
  -> POST /api/review/sources (doc_id + version_id + source_type)
  -> POST /api/review/sources/{id}/extraction-jobs [Idempotency-Key]
  -> review_jobs claims persistent task
  -> review_rules retrieves only source version blocks
  -> structured LLM extraction
  -> evidence.py validates every source anchor
  -> RuleCandidate(draft or blocked)
  -> human confirm/reject
  -> publish creates immutable RuleVersion/TemplateVersion
```

来源文件变化不会实时修改运行中任务。“实时规则”仅指新来源版本完成提取、人工确认并发布后，可立即被新快照明确选择。

### 3. 分析任务

```text
ReviewRulesView config
  -> POST /api/review/analysis-jobs [Idempotency-Key]
  -> review_service transaction:
       validate ready document versions + published rule/template versions
       create immutable AnalysisSnapshot
       create queued AnalysisJob + per-document jobs + audit event
  -> review_jobs runner claims lease
  -> per document:
       plan stable owned/context fragments
       -> per fragment: deterministic checks + scoped semantic classification
       -> evidence anchor validation + fingerprint dedupe
       -> atomically persist FragmentResult + Finding[] + result revision + event sequence
       -> emit durable `fragment` SSE after commit
       -> document-global rules run after local fragments
  -> aggregate complete / complete_degraded / failed / cancelled + monotonic revision
  -> ReviewConsole upserts committed findings from SSE and reconciles through GET status/findings
```

同一幂等键和同一规范化请求哈希返回原任务；相同键但不同请求返回 409。失败重试新建 retry job，但只包含失败的 `AnalysisDocumentJob` 或片段，成功结果不重复生成。分析 SSE 使用持久 `event_seq` 与 `Last-Event-ID` 加速界面，REST Job/Findings 始终是恢复事实源。详细方案见 [streaming-findings-plan.md](streaming-findings-plan.md)，线协议见 [contracts/review-analysis-events.md](contracts/review-analysis-events.md)。

### 4. 风险与高亮双向联动

```text
GET findings -> select RiskCard
  -> DocumentViewer loads exact document version
  -> evidence.py-compatible client validator checks quote/checksum
  -> PDF: page + normalized rects -> viewport transform -> overlay
  -> DOCX: locator_id -> [start,end) -> safe text range highlight
  -> emit active finding ID back to ReviewConsole

viewer selection/click
  -> resolve locator/rect overlap
  -> find matching Finding IDs
  -> focus corresponding RiskCard (multiple matches remain selectable)
```

版本、quote 或 checksum 不一致时不得进行字符串首次匹配。客户端显示 `degraded`，只跳到已验证页或块；服务端保留定位失败原因。PDF overlay 坐标变换覆盖 rotation、zoom 和 devicePixelRatio；DOCX 不使用不稳定分页。

### 5. 审查上下文问答

```text
ReviewAssistant creates conversation(job_id)
  -> POST /api/review/conversations/{id}/stream(request_id, finding_id?, history)
  -> review_qa loads frozen snapshot + validated findings/rules/sources
  -> scoped search only within version IDs; no web fallback
  -> shared llm_client streams tokens
  -> shared sse emits meta/status/token/done/error
  -> done includes validated citations
  -> frontend shared sse decoder updates the existing assistant UI
```

服务端实际使用完整有效 history；停止请求按 `request_id` 通过共享 cancellation registry 仅取消对应生成。中止/错误消息不作为完整 assistant message 写入后续上下文。通用 `/api/chat/*` 不改变。

### 6. 人工决定、审计和导出

```text
PUT finding decision / PUT job decision
  -> review_service validates revision and state
  -> transaction writes HumanDecision + AuditEvent (machine Finding unchanged)
  -> POST exports [Idempotency-Key]
  -> freeze result_revision + decision_revision
  -> persistent export job
  -> python-docx reads same repository snapshot
  -> .data/reviews/exports/{artifact_id}.docx
  -> GET artifact/download
```

页面、重新进入和导出全部读取同一 job revision。导出任务开始后的后续人工修改不会悄悄改变该制品；用户可显式重新导出新 revision。

## Backend Integration Design

### Application lifecycle and routing

- `backend/api/main.py` 注册三个 review router，并在 lifespan 中初始化 SQLite schema、回收过期租约、启动/停止 `ReviewJobRunner`。
- MVP 启动命令必须保持单 worker；检测到多 worker 配置时启动检查失败并给出升级外部队列/数据库的提示。
- API 路由只处理校验、HTTP 状态和 DTO；业务不直接访问 SQLite。

### Document subsystem adaptation

- `document_store.py` 增加 `get_version()`、`get_current_version()`、`create_version()`，并保持旧 `get_ir()` 等调用的 current-version 兼容行为。
- 版本 ID 基于文件 SHA-256、parser schema version 与解析配置哈希；manifest 包含格式、页数/块数、定位能力、checksum 与 created_at。
- `document_pipeline.py` 写入临时版本目录并原子发布 manifest，再将 `current_version_id` 写入 meta；失败版本不得变成 current。
- ES chunk 主键含 version ID；重析把旧版本标记 `is_current=false` 而不是删除。通用搜索默认只查 current，审查搜索必须显式按快照版本过滤。
- `/api/docs/{id}/file` 支持 PDF.js 获取原文件；结构化预览 endpoint 返回对应版本 IR，不让浏览器猜测 Markdown 中的位置。

### Review persistence and task execution

- `review_store.py` 是 SQLite 的唯一入口，统一连接配置、事务、row mapping、optimistic revision、幂等记录和 job lease。
- runner 与 repository 通过 `claim_next(kind, lease_until)`、`heartbeat()`、`complete()`、`fail()` 协作；不持有请求线程或内存 Future 作为事实。
- startup 将租约过期的 running job 回到 queued，保留 attempt 和 last_error；超过最大 attempt 后失败并可由显式 retry 恢复。
- 分析、规则提取、导出共享 runner 框架但使用独立 handler；并发槽按 task kind 限制。

### Analysis and evidence

- 结构检查器接收 IR，不接收渲染 HTML；输出候选 evidence reference 与可重复的 rule evaluation。
- 分析引擎保留文档聚合 API，并增加稳定片段 iterator；片段区分 owned blocks 与重叠 context blocks，Finding 只能归属 owned 范围。
- 编译后的规则明确标记 `fragment_local | document_global`；存量未标记规则默认全文执行，避免切块改变业务语义。
- `search_local()` 新过滤参数默认 `None`，以保持通用问答兼容；review caller 必须传非空 snapshot scope，空 scope 直接失败。
- 语义模型只返回 schema 化的 finding type/severity/reason/suggestion 与候选 block references；`evidence.py` 根据 IR 解析实际 quote、范围和 checksum。
- 每个片段只有在 Finding 完整、证据校验、fingerprint 去重后才原子提交；模型半截 JSON 或 provisional Finding 不进入 SSE/UI。
- 无法校验、OCR 低可信或只能页级/段落级定位的结果设置 `conclusion=manual_review`、`precision=page|block`，不能宣称直接违规。

### Review QA and compatibility

- 从现有 chat route 抽取 `sse.py` 后，对旧接口做回归测试确保事件名、字段、stop endpoint 和前端调用签名不变。
- 从 QA 模块抽 `llm_client.py` 时保留原 prompts/search/web fallback 行为；仅 review_qa 禁止跨范围检索和 Web fallback。
- review `done` 事件允许新增 `citations`、`message_id`、`incomplete`；旧 decoder 忽略未知字段，共享 decoder 将字段传给审查调用方。

## API Design Summary

完整请求/响应和 schema 见 [contracts/review-api.openapi.yaml](contracts/review-api.openapi.yaml)，分析片段 SSE 见 [contracts/review-analysis-events.md](contracts/review-analysis-events.md)，问答 SSE 与状态恢复规则见 [contracts/review-events.md](contracts/review-events.md)。核心资源组：

- `/api/docs/{doc_id}/versions/{version_id}`、`/file`、`/preview`：现有 docs 的版本化适配。
- `/api/review/batches`、`/{batch_id}/documents`：四步流程的持久容器。
- `/api/review/sources`、`/extraction-jobs`、`/rule-candidates`：受控规则提取。
- `/api/review/templates`、`/template-versions`、`/rules`、`/rule-versions`、`/configurations`：发布资源和复用配置。
- `/api/review/analysis-jobs`、`/findings`、`/retries`、`/decisions`、`/audit-events`：真实审查闭环。
- `/api/review/conversations`、`/stream`、`/stop`：任务限定问答。
- `/api/review/analysis-jobs/{id}/exports`、`/export-artifacts/{id}/download`：DOCX 报告。

通用约定为 UUID、UTC ISO-8601、`{items,total}`、`page/page_size`；幂等操作使用 `Idempotency-Key`；Review 错误 envelope 为 `detail.code/message/fields/retryable/trace_id`。`frontend/src/api/http.ts` 同时兼容旧字符串 `detail`。

## Implementation Sequence

1. **共享底座先行**：为文档增加不可变版本和 evidence-capable IR；ES mapping/reindex；抽取共享 SSE、LLM client、safe Markdown，并对旧功能做兼容回归。
2. **审查存储和只读目录**：SQLite schema/repository、batch/source/template/rule/configuration API；前端四步页面去除固定 Mock。
3. **规则生命周期**：持久 job runner、规则提取、候选人工确认和发布，所有来源 anchor 服务端校验。
4. **分析纵切**：snapshot、幂等 job、逐片段/逐文档状态、混合分析、Finding 原子提交、持久事件序号、断点续传、失败重试和恢复；详见 [streaming-findings-plan.md](streaming-findings-plan.md)。
5. **证据 viewer**：PDF.js 与 DOCX locator viewer，共享到知识预览，完成风险/原文双向选择和降级。
6. **问答/处理/导出**：review-scoped conversation、人工决定、审计、DOCX artifact。
7. **端到端验收**：重启恢复、幂等冲突、部分失败、旧 chat/docs 回归、PDF/DOCX 高亮、XSS、导出一致性和性能基线。

## Commands and Local Workflow

```powershell
# Python environment and backend dependencies (repository root)
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Elasticsearch (repository root)
powershell -ExecutionPolicy Bypass -File scripts\start_es.ps1

# MinerU service (repository root, terminal 1)
.\venv\Scripts\python.exe -m mineru_service.server

# FastAPI (backend cwd, terminal 2; MVP must not add --workers > 1)
Set-Location backend
..\venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8002

# Frontend install/run (frontend cwd, terminal 3)
Set-Location frontend
npm ci
npm run dev

# Backend verification (repository root)
.\venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"

# Frontend verification (frontend cwd)
npm exec vue-tsc -- --noEmit
npm test
npm run build
npm exec playwright test
```

实现依赖变化后必须使用 `npm install --save-exact` 生成 lockfile，再以 `npm ci` 验证。CI 和交付文档不得依赖本机全局包。

## Risk Register

| Priority | Risk | Impact | Mitigation / acceptance gate |
|----------|------|--------|------------------------------|
| P0 | MinerU bbox 当前在 adapter 被丢弃 | PDF 无法精确高亮 | 先透传 bbox；用固定样本校验 0-1000 坐标和 quote |
| P0 | pdfplumber fallback 仅提取纯文本 | 降级 PDF 无矩形 | 改用 `extract_words()` 组块；不可验证则只页级并标 manual_review |
| P0 | DOCX 当前无稳定段落/单元 ID | 重复文本误定位 | 按 XML 正文顺序生成版本内稳定 locator，使用 code-point range |
| P0 | 重析会覆盖旧 IR/删除旧 ES chunk | 历史 finding 悬空 | 不可变版本目录；旧 ES 版本不删；snapshot 引用 version ID |
| P0 | ES chunk 当前丢 block_id | 检索结果不能回溯证据 | mapping 加 version/block/locator；迁移前旧文档降级并提示重析 |
| P0 | 通用 QA 忽略 history 且全局搜索 | 审查问答污染/断上下文 | 独立 review 入口，强制 snapshot scope，实际传入有效 history |
| P0 | LLM 输出伪造 quote/位置 | 错误高亮和不可信结论 | LLM 只给候选 ref，服务端以 IR 重建并校验 anchor |
| P0 | `marked + v-html` 未消毒 | 上传内容/模型内容 XSS | 统一 safeMarkdown + DOMPurify，加入恶意 payload 回归 |
| P1 | SQLite 与多 worker 不兼容当前 runner | 重复 claim/并发不确定 | MVP 强制单 Uvicorn worker；repository/lease 边界支持后续迁移 |
| P1 | PDF rotation/zoom/DPR 坐标换算 | overlay 漂移 | PDF.js viewport transform；Playwright 多缩放/旋转截图和像素断言 |
| P1 | DOCX 浏览器排版与 Word 分页不同 | 页码误导 | 不承诺 DOCX 页码；按结构定位并展示段落/表格单元 |
| P1 | polling/SSE 乱序回写旧状态 | UI 状态倒退或重复卡片 | job/result 使用单调 revision，分析事件使用单调 event sequence；store 只应用连续的新事件，间隙触发 REST 对账 |
| P1 | 切块破坏全文规则或重叠片段重复命中 | 误报、漏报和重复 Finding | 规则分 `fragment_local/document_global`；owned/context 分离；稳定 fingerprint 唯一约束 |
| P1 | 模型半成品通过 SSE 进入风险卡片 | 无效证据被用户处置 | 完整 schema、证据校验和事务提交后才发送 fragment；禁止 provisional Finding |
| P1 | 只禁用按钮无法幂等 | 重复任务/导出 | SQLite unique idempotency key + request hash；冲突返回 409 |
| P1 | 现有 http.ts 压平结构错误 | 前端无法展示字段错误/可重试 | adapter 同时解析 string/object detail，保留 code/fields |
| P1 | Cooperative cancellation 与 done 竞态 | 错误保存完整回答 | request 状态 CAS；终态只能写一次；incomplete 独立字段 |
| P1 | 规则提取自动生效 | 未审核规则污染审查 | candidate 默认 draft；只有人工 confirmed 才能 publish |
| P1 | 部分失败重试重复成功 finding | 统计与导出重复 | retry 仅锁定失败 document jobs；finding 唯一键含 snapshot/doc/rule/evidence |
| P2 | 50MB/20 文档造成 CPU/模型压力 | 5 分钟目标不稳定 | 单活跃分析、逐文档进度、429、性能样本和超时预算 |
| P2 | 历史文档缺少 locator metadata | 无法满足精确高亮 | 标记 degraded；用户显式重析产生新版本，历史任务不伪造位置 |

## Test Strategy and Acceptance Gates

- **Unit**: 版本 ID、anchor checksum/range、状态机、幂等冲突、租约回收、配置失效、规则发布门禁、冲突 finding。
- **Contract**: OpenAPI 请求/响应、错误 envelope、分页、旧 docs/chat 向后兼容、SSE event schema。
- **Integration**: 上传到版本 IR、ES 范围过滤、规则提取到发布、分析部分失败/重试、进程重启恢复、决定与导出 revision 一致。
- **Frontend component**: store revision、防重复操作、四步 gating、错误状态、assistant stop/retry、viewer 降级。
- **Browser E2E**: 重复文本 PDF、旋转/缩放 PDF、DOCX 段落/表格、双向选择、重载恢复、XSS payload、导出下载。
- **Quality pilot**: 至少 30 份双人标注样本；高风险召回 >=85%、精确率 >=80%；确定性 finding 证据完整率 100%。

## Complexity Tracking

| Design addition | Why needed | Simpler alternative rejected because |
|-----------------|------------|--------------------------------------|
| SQLite review repository | 幂等唯一性、跨实体事务、任务恢复、不可变引用、决定和审计 | 扩展 JSON/RLock 无法在崩溃和并发操作下保证这些约束 |
| Persistent in-process runner | 分析/提取/导出断线后继续且重启可恢复 | 同步请求或内存 Future 不是持久事实源；Celery/Redis 对单用户过重 |
| Format-specific viewer | PDF 坐标与 DOCX 结构定位语义不同 | iframe/Markdown 无法精确定位重复文本，也无法双向映射 |
| Separate review-scoped QA route | 必须限定 snapshot/finding/rule 且保留通用 chat 兼容 | 给通用 chat 增加可选审查语义会耦合范围和回退行为 |
