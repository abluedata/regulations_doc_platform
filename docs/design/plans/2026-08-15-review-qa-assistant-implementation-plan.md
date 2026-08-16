# 智能审查单文档问答助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在智能审查任务中实现绑定不可变单文档版本的流式问答，保证非拒答回答带逐字一致、可定位引用，无依据明确拒答，并输出可复跑质量报告。

**Architecture:** 会话在创建时绑定 batch document membership，并快照 `document_id` 与 `document_version_id`。检索层复用 BM25、向量和 RRF，但要求显式 `DocumentScope` 并在 BM25/kNN 两路强制版本过滤；候选命中回源 IR 形成可信 `EvidenceCandidate`，LLM 只选择候选编号，引用由服务端生成和校验。`AssistantStream` 用单向状态机统一成功、拒答、错误和取消，确保一个请求恰好一个终态；前端按文档维护会话并将结构化 locator 传给阅读区。

**Tech Stack:** Python 3.12、FastAPI/Pydantic、Elasticsearch、httpx/OpenAI-compatible LLM、Vue 3/TypeScript/Pinia、Vitest、pytest/unittest、SSE。

**PRD:** `docs/product/2026-08-15-review-qa-assistant-prd.md`

---

## Global Constraints

- 所有检索入口必须接收非空 `document_id` 与 `document_version_id`，不得隐式退回全索引。
- citation quote 只能来自规范 IR 原文，且满足 `quote == canonical_text[start:end]`。
- 非拒答回答至少一个有效 citation；引用校验失败时拒答。
- 拒答使用 `done`，基础设施/取消使用 `error`；终态集合 `{done,error}` 每请求恰好一个。
- 不调用 Tavily，不复用风险摘要作为正文证据，不修改通用 `/api/chat`。
- TDD 顺序为失败测试、最小实现、通过测试；第二阶段完成后单独提交。

## File Map

| 文件 | 职责 |
| --- | --- |
| `backend/services/search.py` | 增加必填 `DocumentScope`，BM25/kNN 双路过滤与单文档 RRF |
| `backend/services/review/qa_retrieval.py`（新建） | IR 回源、降级词法检索、候选证据和引用逐字/定位校验 |
| `backend/services/review/qa_answer.py`（新建） | LLM 结构化输出、证据门、拒答判定与最终回答组装 |
| `backend/services/review/assistant.py` | 会话 scope、幂等请求、SSE 状态机、取消与消息持久化 |
| `backend/services/review/store.py` | 创建固定文档范围 conversation、按 request_id 保存/读取消息 |
| `backend/api/review_schemas.py` | 创建会话 scope 与流式请求 schema |
| `backend/api/routes/review.py` | membership 校验、依赖注入、SSE headers 与异常映射 |
| `backend/core/config.py`、`.env.example` | 单文档 QA 候选数、上下文、证据门配置 |
| `backend/tests/test_review_qa_retrieval.py`（新建） | 单文档隔离、IR 回源、quote/span/locator 测试 |
| `backend/tests/test_review_qa_answer.py`（新建） | 可回答、拒答、模型越界和引用校验测试 |
| `backend/tests/test_review_qa_stream.py`（新建） | SSE 正常/拒答/失败/取消/幂等唯一终态测试 |
| `backend/tests/test_review_api.py` | 创建会话与 API scope 契约回归 |
| `frontend/src/api/review.ts` | 会话创建参数、typed SSE done/error/citation |
| `frontend/src/stores/review.ts` | 当前文档、每文档会话、定位目标与生成状态 |
| `frontend/src/components/review/ReviewAssistant.vue` | 文档选择、流式消息、拒答/错误、结构化引用按钮 |
| `frontend/src/views/review/ReviewConsoleView.vue` | 阅读区文档同步及引用定位/高亮 |
| 对应 `*.spec.ts` | 前端行为、终态去重与定位测试 |
| `backend/eval/gold/qa/`（新建） | 单文档 QA 金标与 hash manifest |
| `backend/eval/qa_metrics.py`（新建） | 准确率、引用、定位、拒答、SSE 指标 |
| `scripts/eval_review.py` | 接入 QA run file、质量门和 Markdown 报告 |
| `.eval_reports/review_qa/` | 每轮及最终测评报告（运行产物） |

## Task 1: 固化 API 与会话单文档范围

**Files:**
- Modify: `backend/api/review_schemas.py`
- Modify: `backend/services/review/store.py`
- Modify: `backend/api/routes/review.py`
- Modify: `backend/tests/test_review_api.py`

- [ ] **Step 1: 写创建会话范围失败测试**

加入测试：只有 `analysis_job_id` 的旧请求返回 422；合法 membership 返回固定 scope；其他 batch 或不在 job snapshot 的 membership 返回 409。

```python
response = client.post("/api/review/analysis-conversations", json={
    "analysis_job_id": job["id"],
    "document_membership_id": membership["id"],
})
assert response.status_code == 201
assert response.json()["document_version_id"] == membership["document_version_id"]
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest backend/tests/test_review_api.py -k conversation -q`  
Expected: FAIL，schema 尚未要求 membership，conversation 尚未保存 scope。

- [ ] **Step 3: 实现 schema 和 store**

```python
class CreateConversationRequest(BaseModel):
    analysis_job_id: str
    document_membership_id: str

def create_conversation(self, analysis_job_id: str, membership: Mapping[str, Any]) -> dict[str, Any]:
    return self.put("conversations", {
        "id": str(uuid4()), "analysis_job_id": analysis_job_id,
        "document_membership_id": membership["id"],
        "document_id": membership["document_id"],
        "document_version_id": membership["document_version_id"],
        "filename": membership.get("filename"), "revision": 0, "messages": [],
    })
```

route 从 job 的 batch 加载 membership，并确认它出现在 job documents snapshot 中且状态为 ready。

- [ ] **Step 4: 运行 API 测试确认 GREEN**

Run: `python -m pytest backend/tests/test_review_api.py -k conversation -q`  
Expected: 创建、越权、not-ready 和旧请求用例全部通过。

## Task 2: 为混合检索增加强制文档版本过滤

**Files:**
- Modify: `backend/services/search.py`
- Create: `backend/tests/test_review_qa_retrieval.py`

- [ ] **Step 1: 写 BM25 与 kNN filter 测试**

```python
scope = DocumentScope(document_id="doc-a", document_version_id="version-a")
results = search_document("付款期限", scope=scope, k=6)
assert all(item["doc_id"] == "doc-a" for item in results)
assert all(item["document_version_id"] == "version-a" for item in results)
```

mock ES 并断言两个 search body 都包含 `doc_id.keyword`、`document_version_id.keyword` 和 `is_visible=true` filter；夹入 `doc-b` 命中验证结果层再次防御过滤。

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest backend/tests/test_review_qa_retrieval.py -k search -q`  
Expected: FAIL，现有 `search_local` 无 scope 参数。

- [ ] **Step 3: 实现显式 scope API**

```python
@dataclass(frozen=True)
class DocumentScope:
    document_id: str
    document_version_id: str

def search_document(query: str, *, scope: DocumentScope, k: int = 6) -> list[dict[str, Any]]:
    if not scope.document_id or not scope.document_version_id:
        raise ValueError("document scope is required")
    # BM25 bool.filter and knn.filter use the same immutable scope.
```

保留 `search_local` 给通用问答使用，FR-07 只调用 `search_document`。返回字段补齐 version、block、locator；RRF 后再次按 scope 过滤。

- [ ] **Step 4: 运行检索测试确认 GREEN**

Run: `python -m pytest backend/tests/test_review_qa_retrieval.py -k search -q`  
Expected: 双路 filter、交叉文档污染和缺 scope 用例全部通过。

## Task 3: 建立 IR 回源与可信引用

**Files:**
- Create: `backend/services/review/qa_retrieval.py`
- Modify: `backend/tests/test_review_qa_retrieval.py`

- [ ] **Step 1: 写原文 span 和 locator 测试**

覆盖 PDF exact locator、PDF page locator、DOCX locator_id、chunk 含多个 block、ES 摘要被截断、错误 version/block 和重复文本。

```python
citation = build_citation(candidate, quote="三十日内付款")
canonical = candidate.canonical_text
assert citation.quote == canonical[citation.quote_start:citation.quote_end]
assert citation.document_version_id == scope.document_version_id
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest backend/tests/test_review_qa_retrieval.py -k 'citation or fallback' -q`  
Expected: FAIL，可信候选和 citation builder 尚不存在。

- [ ] **Step 3: 实现候选回源、降级与校验**

定义 `EvidenceCandidate`、`Citation` dataclass。按 `document_store.load_ir(doc_id, version_id=...)` 加载指定版本，以 block ID 回源 canonical text；ES 不可用时仅在这些 blocks 上做确定性 token overlap 排序。`build_citation` 使用 `str.find` 生成 span，找不到时抛 `CitationValidationError`，不得用规范化文本替换 quote。

- [ ] **Step 4: 运行引用测试确认 GREEN**

Run: `python -m pytest backend/tests/test_review_qa_retrieval.py -q`  
Expected: scope、降级、逐字引用和 locator 用例全部通过。

## Task 4: 实现结构化回答与拒答证据门

**Files:**
- Create: `backend/services/review/qa_answer.py`
- Create: `backend/tests/test_review_qa_answer.py`
- Modify: `backend/core/config.py`
- Modify: `.env.example`

- [ ] **Step 1: 写答案策略失败测试**

覆盖无候选、外部问题、合法候选、LLM JSON 解析失败、引用编号越界、引用文本不一致、无引用主张、provider 失败。

```python
result = answer_question("付款期限？", candidates, llm=fake_llm)
assert result.refused is False
assert result.citations
assert result.citations[0].quote in candidates[0].canonical_text
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest backend/tests/test_review_qa_answer.py -q`  
Expected: FAIL，answer pipeline 尚不存在。

- [ ] **Step 3: 实现 evidence gate 与 LLM JSON 契约**

模型只返回答案和候选编号：

```json
{"answer":"乙方应在三十日内付款。","citation_refs":["c1"],"refused":false}
```

服务端验证 candidate ID，并从规范原文确定性选取包含答案关键事实的完整句；无法可靠选句时引用完整候选 block，再生成和验证 quote、span、locator。无候选或验证失败返回标准拒答。provider 连接错误向上抛为基础设施错误，不伪装业务拒答。配置增加候选数、上下文字符数和词法 overlap 门槛，并把配置快照写入结果。

- [ ] **Step 4: 运行答案测试确认 GREEN**

Run: `python -m pytest backend/tests/test_review_qa_answer.py -q`  
Expected: 回答、拒答和 provider error 分类全部通过。

## Task 5: 重写 assistant SSE 唯一终态状态机

**Files:**
- Modify: `backend/services/review/assistant.py`
- Modify: `backend/services/review/store.py`
- Create: `backend/tests/test_review_qa_stream.py`

- [ ] **Step 1: 写所有终态路径失败测试**

参数化正常、拒答、检索异常、模型异常、stop、generator close、重复 request_id。解析事件并断言：

```python
terminal = [event for event in events if event.name in {"done", "error"}]
assert len(terminal) == 1
assert events[-1].name in {"done", "error"}
```

另断言 `done.refused=false` 必有 citation，拒答 citations 为空，error 不保存 complete assistant message，幂等重放不再次调用 LLM。

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest backend/tests/test_review_qa_stream.py -q`  
Expected: 现有 stopped 路径、异常路径、幂等和 scope meta 不满足契约。

- [ ] **Step 3: 实现 request 状态机**

```python
class StreamState:
    terminal_sent = False
    def terminal(self, event: str, payload: Mapping[str, Any]) -> str:
        if self.terminal_sent:
            raise RuntimeError("terminal event already emitted")
        self.terminal_sent = True
        return sse(event, payload)
```

`stream_answer` 只通过一个 `try/except/finally` 出口发送终态；每个事件携带 request_id。store 增加按 `(conversation_id, request_id)` 查询与原子追加，终态成功后才保存完整 assistant message。

- [ ] **Step 4: 运行 SSE 测试确认 GREEN**

Run: `python -m pytest backend/tests/test_review_qa_stream.py -q`  
Expected: 全部路径唯一终态且幂等通过。

## Task 6: 接入 FastAPI 流式接口和响应头

**Files:**
- Modify: `backend/api/routes/review.py`
- Modify: `backend/tests/test_review_api.py`

- [ ] **Step 1: 写流式 API 契约测试**

断言 headers、scope meta、done/error payload、未知会话、重复 request 和 stop；确保 route 不把 generator 错误转成第二终态。

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest backend/tests/test_review_api.py -k assistant -q`  
Expected: headers 和新 payload 契约失败。

- [ ] **Step 3: 接入新 assistant 依赖**

StreamingResponse 增加：

```python
headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
```

将 domain exception 映射为稳定 error code；请求建立后发生的错误由 SSE `error` 终结，请求建立前的 scope/validation 错误使用 HTTP 4xx。

- [ ] **Step 4: 运行后端定向与完整测试**

Run: `python -m pytest backend/tests/test_review_qa_retrieval.py backend/tests/test_review_qa_answer.py backend/tests/test_review_qa_stream.py backend/tests/test_review_api.py -q`  
Expected: 全部通过。

Run: `python -m pytest backend/tests -q`  
Expected: 无回归。

## Task 7: 前端 typed SSE 与按文档会话状态

**Files:**
- Modify: `frontend/src/api/review.ts`
- Modify: `frontend/src/stores/review.ts`
- Modify: `frontend/src/stores/review.spec.ts`

- [ ] **Step 1: 写 store 与 SSE 解析失败测试**

覆盖每个文档独立 conversation、切换恢复消息、终态后忽略 token/第二终态、拒答与 error 区分、AbortController 清理。

- [ ] **Step 2: 运行测试确认 RED**

Run: `npm test -- src/stores/review.spec.ts`（workdir `frontend`）  
Expected: 新 scope 和终态去重断言失败。

- [ ] **Step 3: 增加类型和状态**

```ts
export interface ReviewCitation {
  citation_id: string; document_id: string; document_version_id: string
  filename: string; block_id: string; chunk_id?: number; quote: string
  quote_start: number; quote_end: number; locator: Record<string, unknown>
}
```

`createConversation(jobId, membershipId)` 提交两个 ID；store 使用 `conversationByMembershipId`，以 request_id 保护事件归属，并在首个 done/error 后关闭该请求。

- [ ] **Step 4: 运行 store 测试确认 GREEN**

Run: `npm test -- src/stores/review.spec.ts`（workdir `frontend`）  
Expected: 全部通过。

## Task 8: 完成文档选择、流式回答与引用定位 UI

**Files:**
- Modify: `frontend/src/components/review/ReviewAssistant.vue`
- Modify: `frontend/src/components/review/ReviewAssistant.spec.ts`
- Modify: `frontend/src/views/review/ReviewConsoleView.vue`
- Modify: `frontend/src/views/review/ReviewConsoleView.spec.ts`

- [ ] **Step 1: 写组件行为失败测试**

覆盖文档 selector、未 ready 禁用、status 文案、流式 token、拒答样式、error 重试、citation 标签与 locate emit。Console 测试验证 PDF page/rect 与 DOCX block locator 被传给阅读区，版本不符时拒绝定位。

- [ ] **Step 2: 运行测试确认 RED**

Run: `npm test -- src/components/review/ReviewAssistant.spec.ts src/views/review/ReviewConsoleView.spec.ts`（workdir `frontend`）  
Expected: 文档选择和 locator 行为缺失。

- [ ] **Step 3: 实现 UI**

使用现有 Element Plus `el-select` 和图标。citation 按钮展示 `filename + page/section`，下方显示 quote；拒答是正常完成态但不渲染引用；error 提供明确重试命令。Console 根据 locator 更新活动文档、页码/块和高亮，不做相似文本搜索。

- [ ] **Step 4: 运行前端测试和构建**

Run: `npm test -- src/components/review/ReviewAssistant.spec.ts src/views/review/ReviewConsoleView.spec.ts src/stores/review.spec.ts`（workdir `frontend`）  
Expected: 全部通过。

Run: `npm run build`（workdir `frontend`）  
Expected: typecheck 和 Vite build 成功。

## Task 9: 建立 FR-07 金标集和指标计算器

**Files:**
- Create: `backend/eval/gold/qa/manifest.json`
- Create: `backend/eval/gold/qa/review_qa_v1.json`
- Create: `backend/eval/qa_metrics.py`
- Create: `backend/tests/test_eval_qa_metrics.py`

- [ ] **Step 1: 写指标失败测试**

固定样本覆盖正确答案、事实错误、精确 quote、span 错误、版本错误、locator 错误、正确/错误拒答、无引用回答和双终态。

```python
assert report["citation_exact_match_rate"] == 1.0
assert report["sse_unique_terminal_rate"] == 1.0
assert report["refusal"]["correct_rate"] == 1.0
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest backend/tests/test_eval_qa_metrics.py -q`  
Expected: FAIL，qa_metrics 尚不存在。

- [ ] **Step 3: 实现金标 manifest 与确定性指标**

金标至少 30 题，>=18 可回答、>=10 应拒答，包含 PDF 和 DOCX locator。计算器输出分子、分母、rate、逐题 failure codes 和门槛 pass/fail；manifest 校验复用 SHA-256 模式。

- [ ] **Step 4: 运行指标与 manifest 测试**

Run: `python -m pytest backend/tests/test_eval_qa_metrics.py backend/tests/test_eval_gold_manifest.py -q`  
Expected: 全部通过。

## Task 10: 扩展可复跑评测脚本与报告

**Files:**
- Modify: `scripts/eval_review.py`
- Modify: `backend/tests/test_quality_operations.py`
- Create: `.eval_reports/review_qa/.gitkeep`

- [ ] **Step 1: 写 CLI 失败测试**

使用固定 qa run fixture 执行 `--qa-run-file`，断言生成 `qa_metrics.json`、`qa_cases.json`、`review_qa_report.md`，硬门失败时退出码为 2。

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest backend/tests/test_quality_operations.py -k qa -q`  
Expected: CLI 尚不识别 `--qa-run-file`。

- [ ] **Step 3: 接入 QA 报告和质量门**

保留原有评测参数；新增 `--qa-gold-dir`、`--qa-run-file`。Markdown 报告记录 commit、dataset hash、运行配置、所有指标、分母、失败题和未决项。逐字引用、非拒答引用覆盖或 SSE 唯一终态低于 100% 时必定失败。

- [ ] **Step 4: 运行完整离线评测**

Run:

```powershell
python scripts/eval_review.py `
  --gold-dir backend/eval/gold `
  --predictions .eval_reports/gold_predictions.json `
  --run-file .eval_reports/full_chain_20.json `
  --qa-gold-dir backend/eval/gold/qa `
  --qa-run-file .eval_reports/review_qa/run.json `
  --baseline backend/eval/ci/baseline.json `
  --output-dir .eval_reports/review_qa/latest
```

Expected: 生成原有四类报告和三份 QA 报告；达标退出 0，未达标退出 2 并列出失败项。

## Task 11: 缺陷修复、复测与第二阶段提交

**Files:**
- Modify only files implicated by failing tests/evaluation
- Update: `.eval_reports/review_qa/latest/review_qa_report.md`

- [ ] **Step 1: 按 failure code 归因**

`hallucinated_claim` 修 evidence gate；`quote_mismatch` 修回源/span；`locator_mismatch` 修 locator；`false_refusal` 修召回；`missed_refusal` 收紧证据门；`multiple_terminal` 修状态机。不得通过降低 100% 硬门消除失败。

- [ ] **Step 2: 每次修复后运行最小测试**

Run: 对应 `python -m pytest ... -q` 或 `npm test -- ...`。  
Expected: 先复现失败，修复后通过。

- [ ] **Step 3: 运行完整验证**

Run: `python -m pytest backend/tests -q`  
Run: `npm test`（workdir `frontend`）  
Run: `npm run build`（workdir `frontend`）  
Run: Task 10 的完整评测命令。  
Expected: 测试与构建通过；全部 FR-07 指标达到 PRD 门槛，或报告明确记录未决项且不声称达标。

- [ ] **Step 4: 提交第二阶段实现**

```powershell
git add backend frontend .env.example
git commit -m "feat(review-qa): implement document-scoped grounded assistant"
```

实现提交不混入 `.eval_reports/` 最终测评结果，确保第三阶段可独立审计。

## Task 12: 第三阶段测评报告提交

**Files:**
- Add: `.eval_reports/review_qa/<run-id>/*`
- Add/Update: `.eval_reports/review_qa/latest/*`

- [ ] **Step 1: 从实现提交运行最终评测**

记录 git commit、配置、gold hash 和原始 run payload；不得手工修改指标 JSON。

- [ ] **Step 2: 核对硬门**

逐字引用一致率、SSE 唯一终态率、非拒答引用覆盖率均为 100%；答案准确率 >=90%；定位与拒答正确率 >=95%；错误拒答率 <=5%。

- [ ] **Step 3: 提交第三阶段报告**

```powershell
git add -f .eval_reports/review_qa
git commit -m "test(review-qa): add grounded assistant evaluation report"
```

如果未达标，commit message 使用 `test(review-qa): record evaluation gaps`，报告列出失败题、根因、影响与未决动作。

## Spec Coverage

| PRD 要求 | 实施任务 |
| --- | --- |
| 单文档版本绑定 | 1、7、8 |
| BM25+向量+RRF 单文档过滤 | 2 |
| IR 原文回源、逐字引用、locator | 3 |
| LLM 上下文与无依据拒答 | 4 |
| SSE 唯一终态、取消、幂等 | 5、6 |
| 文档选择→流式回答→点击定位 | 7、8 |
| 金标与全部硬性指标 | 9、10 |
| 幻觉/引用/拒答缺陷闭环 | 11 |
| 三阶段独立提交与最终报告 | 11、12 |

## Plan Self-Review

- [x] PRD 的每项范围、接口和验收要求均映射到任务。
- [x] 后端、前端、评测分别有失败测试、实现和验证命令。
- [x] 类型名、事件名和字段名在各任务中一致。
- [x] 无 TBD、TODO、“适当处理”等不可执行占位描述。
- [x] 第二阶段实现与第三阶段报告保持独立 commit。
