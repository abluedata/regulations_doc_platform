# Phase 0 Research: 智能审查真实后端联通

**Date**: 2026-07-26

**Spec**: [spec.md](spec.md)

## 1. 现有能力复用边界

**Decision**: 继续以现有文档和通用问答模块作为底座，仅在原模块中补充版本、定位、范围过滤和共享传输能力；审查域不建立第二套上传、解析、预览、SSE 或 LLM 客户端。

**Rationale**:

- `backend/api/routes/docs.py` 已提供 PDF/DOCX、50MB 校验、上传、状态、预览、删除和重析。
- `backend/services/document_pipeline.py` 已具备 MinerU 优先、pdfplumber/python-docx 降级、统一 IR、分块和 ES 入库流程。
- `backend/api/routes/chat.py` 与 `frontend/src/api/chat.ts` 已定义 `meta/status/token/done/error` 事件、请求身份和停止语义。
- 四个审查页面、路由、Pinia store 及卡片组件已经存在，只需替换 Mock 数据源和本地状态动作。

**Alternatives considered**:

- 新建 `/review/documents` 上传与预览：拒绝，会产生两套文档事实源。
- 直接把审查字段塞入现有 docs/chat 接口：拒绝，会污染通用工作台并破坏领域边界。
- 复制一套 SSE 解析和模型调用：拒绝，应抽取现有实现为共享 helper。

## 2. 审查领域持久化

**Decision**: 新增基于 Python 标准库 `sqlite3` 的审查领域存储，启用 WAL、外键和显式事务；文档制品继续保留在 `.data/uploads/` 和 Elasticsearch。审查数据库位于 `.data/reviews/reviews.db`。

**Rationale**:

- 完整 MVP 包含不可变版本、幂等操作、异步状态、逐文档部分失败、人工决定和审计事件，要求跨实体事务和唯一约束。
- 现有 `docs_index.json`、`.chat_data/*.json` 与进程内 `RLock` 不提供跨进程锁、事务或崩溃恢复。
- SQLite 不新增 Python 包或外部服务，符合当前本机单用户和单 Uvicorn worker 的部署方式。
- 通过 `review_store.py` 隔离存储接口，达到多用户或多进程升级触发条件后可替换为服务型数据库。

**Alternatives considered**:

- 扩展 JSON 文件：拒绝，无法可靠实现幂等唯一性和审计事务。
- PostgreSQL：拒绝，当前单用户本机部署不需要新增服务。
- Elasticsearch 同时保存领域状态：拒绝，ES 只承担检索，不适合作为事务事实源。

## 3. 文档不可变版本

**Decision**: 适配 `document_store.py` 和 `document_pipeline.py`，把解析产物保存为 `.data/uploads/{doc_id}/versions/{version_id}/`；`meta.json` 记录 `current_version_id`，旧版顶层 `ir.json/preview.md` 以兼容读取方式迁移。重析创建新版本，不覆盖旧产物。

**Rationale**:

- Analysis Snapshot 和 Finding 必须引用不会被重析覆盖的文档版本。
- 当前 `POST /docs/{id}/reparse` 删除旧 IR/preview 和 ES chunks，会使历史风险与问答上下文悬空。
- `version_id` 由源文件 SHA-256、解析 schema 版本和解析配置共同确定；同内容同配置可幂等复用。

**Alternatives considered**:

- 只保存 `doc_id + updated_at`：拒绝，不能证明内容与定位一致。
- 在审查数据库复制完整 IR：拒绝，会形成第二份文档制品并增加同步风险。

## 4. PDF 与 DOCX 证据定位

**Decision**: IR 使用判别联合定位类型。PDF 精确定位统一为 1-based 页码、左上角原点、0-1000 归一化矩形；DOCX 精确定位使用版本内稳定的正文块/段落或表格单元身份、文档顺序和 Unicode code point 半开区间 `[start,end)`。

**Rationale**:

- MinerU 3.4.4 的 content list 已生成 0-1000 归一化 `bbox`，当前 `mineru_service/adapter.py` 在转换 block 时丢弃了它，原位透传即可复用。
- pdfplumber 降级路径必须由 `extract_words()` 组合文本和坐标，不能从 `extract_text()` 事后恢复可信 bbox。
- DOCX 没有稳定分页，当前 `python-docx` fallback 也没有段落/表格单元序号；应在 XML 正文遍历时生成版本内稳定 ID。
- chunk 仅负责召回。Finding 落盘前必须回到版本固定 IR 解析定位并校验 quote/hash。

**Alternatives considered**:

- 所有格式只用 `block_id + quote`：拒绝，重复文本会误定位。
- 后端返回已插入高亮的 HTML：拒绝，版本耦合、XSS 和双向选择风险高。
- PDF 与 DOCX 共用一个位置结构：拒绝，两者布局语义不同。

## 5. 文档查看器

**Decision**: 将现有 `DocPreviewView.vue` 的查看能力抽取为共享 Document Viewer。PDF 新增 `pdfjs-dist` 5.x（由 lockfile 精确锁定）渲染原文件和坐标叠层；DOCX 使用后端结构化 IR 渲染带稳定 locator 属性的安全 DOM。审查控制台和知识库预览共同复用。

**Rationale**:

- 浏览器内置 PDF iframe 无法可靠控制页面坐标 overlay。
- 当前 Markdown `v-html` 不保留 PDF bbox 或 DOCX 段落身份，无法满足精确高亮。
- 共享 viewer 避免审查控制台与知识库预览形成两套渲染逻辑。

**Alternatives considered**:

- 后端生成页图：拒绝，需要额外图像制品与渲染依赖，缩放清晰度较差。
- DOCX 引入独立 mammoth 渲染：拒绝，现有 python-docx IR 可以直接扩展并保持 locator 一致。

## 6. HTML 与 Markdown 安全

**Decision**: 新增 `dompurify` 3.x，并抽取 `safeMarkdown.ts`；适配现有 ChatMessage、DocPreview 和审查问答输出，禁止未经消毒的文档/模型 HTML 进入 `v-html`。

**Rationale**: 当前 `marked` 输出直接进入 `v-html`。审查功能会扩大上传文档、表格和模型内容的呈现面，必须在共享边界统一消毒。

**Alternatives considered**:

- 依赖调用方手工转义：拒绝，容易遗漏表格、链接和模型生成 HTML。
- 全部降级纯文本：拒绝，会丢失现有 Markdown 和表格体验。

## 7. 异步任务与恢复

**Decision**: 分析、规则提取和导出均建模为持久任务；使用独立单进程 runner + `ThreadPoolExecutor` 执行，但任务状态、租约、幂等键和结果全部存入 SQLite。应用启动时将过期 `running` 任务回收为 `queued` 并恢复执行。

**Rationale**:

- 当前文档解析线程池的模式可复用，但其内存 Future 不能作为状态事实源。
- 本机单用户环境不需要 Celery/Redis；持久 repository + runner 边界保留后续替换空间。
- 状态 GET 是恢复事实源，SSE 进度仅用于降低延迟。

**Alternatives considered**:

- 复用文档解析的同一个单线程池：拒绝，解析与审查会互相阻塞且职责混杂。
- 单次 SSE 或同步请求承载分析：拒绝，断线无法恢复并违反幂等要求。
- 当前阶段引入 Celery/RQ/Redis：拒绝，部署复杂度超过单用户需要。

## 8. 审查算法组合

**Decision**: 审查采用三段式流水线：确定性结构检查 → 限定文档版本和规则版本的检索召回 → 结构化语义判定。LLM 只做分类、解释和建议，不能直接创造定位；无法由服务端验证的输出降级为 `manual_review`。

**Rationale**:

- 结构缺失、金额、日期、期限和阈值适合确定性检查。
- 范本/规范差异需要受控检索与语义判断。
- 仅靠知识库检索不能证明违规，且现有全局 `hybrid_search()` 会污染审查范围。

**Alternatives considered**:

- 全文一次性提交 LLM：拒绝，不可解释、不可稳定复现、定位不可信。
- 只有规则 DSL：拒绝，无法覆盖语义偏差和模糊条款。

## 9. 检索与模型客户端复用

**Decision**: 为 `search_local()` 增加可选 `document_version_ids/source_version_ids` 过滤，并在 ES 文档中补 `document_version_id/block_id/locator_refs/is_current`。从 `qa_service.py` 与 `parallel_qa.py` 抽取共享 `llm_client.py`，原工作台和审查服务共同调用。

**Rationale**: 默认参数维持现有通用问答行为；审查路径强制传范围。抽取共享模型客户端可以避免第三套 HTTP、超时、流式和错误处理。

**Alternatives considered**:

- 审查直接调用现有无范围 `hybrid_search()`：拒绝，会跨任务取证。
- 在 `review_analysis.py` 复制模型 HTTP 调用：拒绝，重复已有源码。

## 10. 审查问答

**Decision**: 新增 review-scoped conversation 资源和流式入口，复用共享 SSE decoder、framing、取消 registry 和 LLM transport；通用 `/api/chat/*` 保持不变。审查请求显式包含 job、可选 finding、history 和 request_id。

**Rationale**:

- 当前 `ChatStreamRequest.history` 已定义但后端 `chat_stream()` 没有传给 `stream_answer()`，不能照搬该缺口。
- 审查上下文必须限定在 snapshot 文档、Finding、RuleVersion 和来源证据，禁止 Web fallback。
- done 事件在保留旧字段的同时附加机器可读 citations。

**Alternatives considered**:

- 扩展通用 `/chat/stream` 可选字段：拒绝，通用与审查语义耦合。
- 前端把全部上下文拼进问题：拒绝，无法服务端校验权限、版本和引用。

## 11. 导出格式

**Decision**: MVP 导出 DOCX，复用已安装的 `python-docx 1.2.0`；导出任务冻结 result/decision revision，并从服务端同一事实源生成。产物保存到 `.data/reviews/exports/`。

**Rationale**: DOCX 符合法务继续编辑的工作方式，且不新增 PDF 报告库、中文字体或分页依赖。

**Alternatives considered**:

- PDF：延期。需要额外渲染库、字体部署和分页回归测试。
- 前端拼装报告：拒绝，无法保证与服务端结果和审计版本一致。

## 12. API 约定

**Decision**:

- 新领域统一在 `/api/review/*`；现有 `/api/docs/*` 和 `/api/chat/*` 向后兼容。
- UUID 资源 ID、ISO-8601 UTC 时间、`page/page_size` 与 `{items,total}` 列表包络。
- 分析启动、失败重试、规则提取/发布和导出使用 `Idempotency-Key`；同 key 同 payload 回放，同 key 不同 payload 返回 409。
- Review API 错误使用 `detail:{code,message,fields?,retryable?,trace_id?}`；前端 http adapter 同时兼容旧字符串 detail。
- 状态码：200/201/202/204、404、409、422、429、503。

**Rationale**: 与现有 FastAPI/Axios 风格兼容，同时补齐持久任务和业务冲突所需语义。

**Alternatives considered**:

- GraphQL：拒绝，项目已有 REST/SSE 模式。
- cursor pagination：拒绝，本机单用户规模下复用现有分页更简单。

## 13. 运行时与依赖基线

**Decision**:

- 验证环境：Windows 11 64-bit `10.0.22631`、Node `24.13.0`、npm `11.8.0`、Python `3.12.4`。
- Python 实装版本：FastAPI 0.139.2、Uvicorn 0.51.0、Pydantic 2.13.4、Elasticsearch client 8.19.3、MinerU 3.4.4、httpx 0.28.1、requests 2.34.2、python-docx 1.2.0、pdfplumber 0.11.10。
- 前端 lockfile：Vue 3.5.40、Pinia 2.3.1、Axios 1.18.1、Element Plus 2.14.3、Vite 6.4.3、Vitest 4.1.10、TypeScript 5.6.3。
- 新增前端运行依赖：`pdfjs-dist@5`、`dompurify@3`；新增开发依赖：`@playwright/test@1`。安装后由 package-lock 精确锁定。
- 不新增 Python 运行依赖；SQLite 为标准库，DOCX 导出复用 python-docx。

**Rationale**: 记录实际可运行环境，并把不可由现有依赖覆盖的 PDF 渲染、HTML 消毒和真实浏览器坐标验证控制在最小范围。

**Alternatives considered**:

- 只使用 Vitest/happy-dom 验证 PDF 坐标：拒绝，happy-dom 没有真实 layout/canvas。
- 使用 `npm install`：开发可用，但 CI/验证统一使用 `npm ci` 保证 lockfile 可复现。

## 14. 规模与并发约束

**Decision**: MVP 保持单用户、单 Uvicorn worker；单文件 50MB，单批次最多 20 份文档，同时最多 1 个活跃分析 job 和 1 个规则提取 job，API 列表默认 20、最大 200。超过限制返回 429/422 并提供可重试说明。

**Rationale**: 与当前 CPU MinerU、单机 ES 和 5 分钟单文档目标一致，防止完整 MVP 在无容量边界下失控。

**Alternatives considered**:

- 无限制批次和并发：拒绝，会造成 CPU、内存和模型调用争用。
- 首期多 worker：拒绝，需要分布式锁、任务租约和外部队列。

## 15. 配置语义

**Decision**:

- `sensitivity=0` 表示宽泛/高召回，`100` 表示严格/高置信。
- `analysis_profile_id` 只引用后端发布的 `accurate` 或 `fast` profile，不把真实模型名交给前端。
- `marking_mode=standard` 展示所有可见 finding；`high_only` 仍保存所有 finding，但非高风险标记为 suppressed，避免审计数据丢失。
- Reusable config 固定 rule version 和 override；失效规则返回 `invalid_rule_ids`，不静默升级。

**Rationale**: 把当前页面上的灵敏度、模型和标记逻辑转成稳定、可复现的业务语义。

**Alternatives considered**:

- 直接把模型 ID 保存到前端配置：拒绝，部署模型变更会破坏历史配置。
- `high_only` 丢弃低中风险：拒绝，无法审计和重新筛选。
