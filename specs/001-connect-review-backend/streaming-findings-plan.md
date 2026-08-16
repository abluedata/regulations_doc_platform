# 方案与实现计划：审查发现片段实时输出

**状态**: Proposed  
**日期**: 2026-08-16  
**关联规格**: [spec.md](spec.md)  
**事件契约**: [contracts/review-analysis-events.md](contracts/review-analysis-events.md)

## 1. 目标

把当前“整份文档完成后批量出现发现”改为“每个分析片段完成后立即出现完整发现”，同时保持以下业务不变量：

- 分析任务仍是可查询、可恢复的持久异步任务，SSE 不是结果事实源。
- 前端只展示已经完成结构化解析、证据定位、证据校验和去重的 Finding。
- 连接中断不取消后台任务；刷新或重连后不重复结果、不丢结果。
- PDF/DOCX 证据契约、规则快照和人工决定语义不改变。
- 通用问答和审查问答的 token 流协议不改变。

## 2. 非目标

- 不把模型原始 token、思维过程、半截 JSON 或未校验证据展示为风险卡片。
- 不在本次引入 Redis、Celery、Kafka 或多 worker 分布式事件系统。
- 不改变任务输入快照、规则发布、人工决定和报告导出的领域边界。
- 不承诺所有规则都能片段化；全文一致性规则仍允许在文档末尾产出。

## 3. 当前差距

当前链路的产出边界是文档：

```text
ReviewEngine.analyze_document
  -> 汇总整份文档全部规则/块结果
  -> ReviewJobRunner.on_document_result
  -> 持久化全部 finding
  -> SSE issues
  -> 前端重新 GET 全量 findings
```

因此存在四个问题：

1. 首个完整 Finding 必须等待整份文档结束。
2. 单文档任务几乎看不到增量效果。
3. 每个 `issues` 事件都会触发一次全量 GET，事件增多后请求量和乱序风险上升。
4. SSE 只有连接内 `seen` 下标，没有持久 `event_seq` 和 `Last-Event-ID` 恢复语义。

## 4. 核心决策

### 4.1 输出单位

网络输出单位定义为 `AnalysisFragmentResult`：一个稳定片段完成后的完整结果，包含零个或多个 Finding。前端再把其中 Finding 逐条插入卡片列表。

```text
一个片段事件 != 一个模型 token
一个片段事件 = 一次可审计、可重放的已提交结果
```

即使片段没有发现，也必须提交片段完成状态，以便进度真实前进。

### 4.2 片段规划

第一版复用现有 `ReviewEngine.iter_chunks()` 的 32-block 基线，但显式区分：

- `owned_blocks`: 当前片段负责产出 Finding 的块范围。
- `context_blocks`: 为跨段语义提供的相邻上下文，不拥有产出归属。
- `fragment_id`: 由文档版本、planner 版本和 owned block 范围稳定生成。
- `fragment_index/fragment_total`: 仅用于进度和展示，不作为幂等身份。

上下文可以重叠，但 Finding 只允许归属到 `owned_blocks`，再通过 fingerprint 去重，避免边界重复。

### 4.3 规则执行范围

编译后的规则增加服务端执行范围，不作为用户自由编辑字段：

| 范围 | 语义 | 输出时机 |
|---|---|---|
| `fragment_local` | 关键词、局部金额/日期/期限、局部语义规则 | 每个片段完成后 |
| `document_global` | 缺失条款、跨段一致性、总额/主体一致性、冲突归并 | 文档全文检查完成后 |

未声明范围的存量规则默认 `document_global`，先保证语义不退化；确认片段安全后再逐条标记为 `fragment_local`。

### 4.4 完整 Finding 后再发送

模型可在服务端内部流式返回，但只有以下步骤全部成功后才能进入 `fragment.findings`：

```text
结构化输出闭合
  -> schema 校验
  -> quote/block 解析
  -> EvidenceAnchor 校验
  -> false-positive 过滤
  -> stable fingerprint 去重
  -> 建议字段完成或使用规则级安全回退
```

不引入 `provisional finding`。这样风险数量、定位和人工处置不会建立在半成品上。

## 5. 目标架构

```text
POST analysis-jobs
  -> 创建持久 Job/DocumentJob/FragmentTask
  -> 后台 runner 顺序领取片段
  -> engine.analyze_fragment(fragment, rules)
  -> evidence validation + dedupe
  -> repository.commit_fragment_result() [单事务]
       1. 标记 fragment completed/failed
       2. 幂等插入 Finding
       3. 更新 processed_fragments/finding_count/progress
       4. 增加 result_revision（仅结果变化时）
       5. 分配 event_seq 并写 AnalysisEvent
  -> 通知 SSE tailer
  -> SSE materializer 按 finding_id 读取已提交 Finding
  -> event: fragment
  -> 前端按 stable finding ID upsert
```

SSE 连接不拥有分析执行，也不直接接收 worker callback。事件必须先提交数据库，再通知连接。

## 6. 后端设计

### 6.1 引擎接口

保留现有聚合接口以降低回归面：

```python
analyze_document(ir, rules) -> DocumentAnalysisResult
```

新增片段接口：

```python
iter_document_fragments(ir, rules) -> Iterable[AnalysisFragmentResult]
analyze_fragment(ir, fragment, rules) -> AnalysisFragmentResult
analyze_document_global(ir, rules) -> AnalysisFragmentResult
```

`analyze_document()` 改为消费上述结果并聚合，原有单元测试仍可复用。

### 6.2 Runner 接口

把产出回调从文档边界下沉：

```python
on_fragment_start(fragment)
on_fragment_result(fragment_result)
on_document_result(document_summary)
```

第一版每份文档内顺序执行片段，不增加片段并发。现有 job 级 `max_workers=2` 保持不变，避免 SQLite 写竞争和模型限流复杂化。

### 6.3 原子提交

新增 repository 操作：

```python
commit_fragment_result(job_id, document_job_id, fragment_result)
```

同一事务完成：

- compare-and-set 片段状态，已完成片段重复提交直接回放原结果。
- 按 `(analysis_job_id, fingerprint)` 幂等插入 Finding。
- 更新 Job/DocumentJob 单调计数和 revision。
- 分配该 job 的下一 `event_seq`。
- 写入仅引用 finding IDs 的 AnalysisEvent/outbox。

事件日志不复制可变人工决定；SSE 输出时只按 `finding_ids` 读取不可变机器 Finding。人工决定继续由 REST 决定覆盖层提供，前端增量 upsert 时不得用分析事件清空已有决定。

### 6.4 唤醒与心跳

当前 0.5 秒盲轮询改为：

- 数据库事件日志继续作为恢复事实源。
- 单进程运行时用 `threading.Condition` 在事务提交后立即唤醒 tailer。
- Condition 丢失通知时仍以最多 1 秒数据库轮询兜底。
- 空闲连接每 15 秒发送 SSE comment heartbeat，不增加 `event_seq`。

### 6.5 取消与失败

- 取消在片段边界协作生效，已提交 Finding 保留。
- 单片段失败记录 `fragment_error`，其他片段继续；终态根据失败范围进入 `complete_degraded` 或 `failed`。
- 重试只重跑失败片段；成功片段和 Finding 通过稳定键复用。
- 证据无效的候选不得进入确定性 Finding，可降级为 `manual_review` 或片段错误。

## 7. SSE 与恢复设计

沿用当前 GET 路径：

```http
GET /api/review/analysis-jobs/{job_id}/stream
Accept: text/event-stream
Last-Event-ID: 41
```

业务事件：

```text
progress*
fragment*
complete | error
```

每个持久业务事件包含：

- SSE `id` 与 JSON `event_seq`，两者相同。
- `job_id`、`job_revision`、`result_revision`。
- 片段事件包含文档版本、fragment ID、进度计数和完整 Finding 数组。
- 终态唯一；终态之后不再发送业务事件。

客户端检测到序号间隙、游标失效或 payload 校验失败时，不猜测缺失内容，而是 GET job/findings 做权威同步，再用新的游标继续。

详细格式见 [contracts/review-analysis-events.md](contracts/review-analysis-events.md)。

## 8. 前端设计

### 8.1 API 层

`frontend/src/api/review/review.ts` 增加：

```ts
onFragment(data: AnalysisFragmentEvent): void
onProgress(data: AnalysisProgressEvent): void
```

共享 SSE decoder 必须支持：

- 一个事件跨多个网络 chunk。
- 一个网络 chunk 包含多个事件。
- UTF-8 中文字符跨 chunk。
- SSE `id`、comment heartbeat 和未知事件。

### 8.2 Store 层

不再在每个片段事件上调用 `loadFindings()`。Store 维护：

```text
findingById: Map<string, ReviewRisk>
lastEventSeq
analysisRevision
resultRevision
processedFragments / totalFragments
```

处理规则：

1. `event_seq <= lastEventSeq`：忽略重复事件。
2. `event_seq > lastEventSeq + 1`：暂停增量应用并执行权威同步。
3. `fragment`：按 finding ID upsert，保留本地选中状态和已加载决定。
4. `complete`：最后执行一次 `refreshJob()` + `loadFindings()` 对账。
5. SSE 断开：任务保持运行态，指数退避重连；不显示为分析失败。

### 8.3 兼容窗口

后端迁移期可同时发出旧 `issues` 和新 `fragment`：

- 新前端一旦收到 `fragment`，忽略同连接后续 `issues`。
- 连接只出现旧 `issues` 时，沿用全量 GET 回退。
- 全部客户端升级并通过 E2E 后删除旧 `issues`。

### 8.4 页面体验

分析中稳定展示：

```text
已检查 8/24 个片段
已标记 6 项风险
正在检查：付款与结算条款
```

风险卡片只在 Finding 完整后出现，不显示逐字变化的标题、理由或建议。用户可以立即定位和查看已完成卡片，但任务级批准/拒绝继续等到任务终态。

## 9. 数据迁移与兼容

- 新增 `analysis_fragments` 和 `analysis_events` 表，不重写历史 Finding。
- 历史终态任务没有 event sequence 时，SSE 直接合成一个终态事件；客户端通过 GET 获取结果。
- 历史运行中任务由启动恢复逻辑重新规划未完成片段；已存在 Finding 依靠 fingerprint 去重。
- 保留现有分析启动、状态、findings、决定和导出 REST 路径。
- 不修改 QA SSE 的 `meta/status/token/done/error` 语义。

## 10. 实现计划

### Phase 0：契约与基线

1. 固化分析状态枚举，以当前运行时 `queued/parsing/running/complete/complete_degraded/failed/cancelled` 为实现基线。
2. 为 `fragment/progress/complete/error`、SSE ID 和 `Last-Event-ID` 编写后端契约测试。
3. 为前端 decoder 编写 chunk boundary、重复、乱序和 heartbeat RED 测试。
4. 记录当前“按文档 issues + 全量 GET”基线，确保测试确实因缺少片段行为失败。

**退出条件**：事件契约无歧义，RED 测试因预期缺失行为失败。

### Phase 1：片段模型与幂等持久化

1. 增加 AnalysisFragment/AnalysisEvent schema 与迁移。
2. 保留引擎聚合 API，增加 fragment iterator 和 local/global rule 分类。
3. 将引擎已有稳定哈希作为 Finding fingerprint 输入；repository 按 `(analysis_job_id, fingerprint)` 返回既有持久 UUID，重复片段不得重新分配 Finding ID。
4. 实现 `commit_fragment_result()` 单事务和唯一约束。
5. 覆盖零发现、重复提交、失败重试、证据无效和全文规则测试。

**退出条件**：同一片段任意重放只产生一组 Finding 和一个有效提交结果。

### Phase 2：Runner 与可恢复 SSE

1. Runner 增加 fragment callbacks，文档内顺序执行。
2. 每个片段提交后写持久事件并立即唤醒 SSE tailer。
3. 实现 SSE `id`、Last-Event-ID、终态唯一和 heartbeat。
4. 连接断开测试证明后台任务继续；重连只回放缺失事件。
5. 迁移期保留旧 `issues` 兼容事件。

**退出条件**：带延迟的三片段测试中，首个 `fragment` 必须早于 `complete` 到达，断线重连无重复结果。

### Phase 3：前端增量合并

1. 增加事件类型和共享 decoder 支持。
2. Store 使用 Map/upsert 应用 Finding，不再每片段全量 GET。
3. 实现重复忽略、序号间隙同步、断线重连和终态对账。
4. 控制台显示片段进度和实时 finding count。
5. 保持选中 Finding、高亮和决定状态在增量插入时稳定。

**退出条件**：连续片段不会产生重复卡片，不会把状态倒退，也不会为每个片段发送 findings GET。

### Phase 4：端到端与性能门

1. 后端集成测试覆盖多文档、零发现、片段失败、取消、重启恢复和失败片段重试。
2. 浏览器 E2E 验证卡片在终态前出现、计数正确、可立即定位证据。
3. 记录 `time_to_first_fragment_ms`、`fragment_commit_ms`、`stream_reconnect_count` 和重复事件计数。
4. 使用快速确定性任务和慢速模型任务验证事件不会因 0.5 秒轮询被整体合并。
5. 完成后移除旧 `issues` 兼容分支。

**退出条件**：全部验收标准和既有 review 回归通过。

## 11. 重点文件

后端：

- `backend/services/review/engine.py`
- `backend/services/review/job_runner.py`
- `backend/services/review/store.py`
- `backend/repositories/review_repository.py`
- `backend/api/routes/review.py`
- `backend/api/review_schemas.py`
- `backend/migrations/`
- `backend/tests/test_review_engine.py`
- `backend/tests/test_review_api.py`
- `backend/tests/test_review_fragment_stream.py`（新增）

前端：

- `frontend/src/api/review/review.ts`
- `frontend/src/api/sse.ts`（按现有计划抽取/复用）
- `frontend/src/stores/review.ts`
- `frontend/src/types/review.ts`
- `frontend/src/views/review/ReviewConsoleView.vue`
- `frontend/src/stores/review.spec.ts`
- `frontend/src/api/review/review.spec.ts`
- `frontend/tests/e2e/review-fragment-stream.spec.ts`（新增）

## 12. 验收标准

- 首个完整 Finding 在所属片段提交后到达，不等待整份文档完成。
- 每个前端可见 Finding 都已持久化且包含有效或明确降级的 EvidenceAnchor。
- 零发现片段也推进 `processed_fragments`。
- 重复提交、片段重试、SSE 重放和页面刷新不会增加 Finding 数量。
- `event_seq` 严格单调；重连从 Last-Event-ID 后继续。
- SSE 断开不改变 Job 状态，也不取消后台执行。
- 前端检测序号间隙时通过 REST 恢复，不静默丢事件。
- `complete/error` 终态恰好一个，终态后无业务事件。
- 分析过程中不再为每个片段重新拉取全量 findings。
- 既有决定、证据高亮、导出和 QA 流测试保持通过。

## 13. 风险与控制

| 风险 | 控制 |
|---|---|
| 盲目切块破坏全文规则语义 | local/global 显式分类，存量默认 global |
| 重叠上下文产生重复 Finding | owned/context 分离 + stable fingerprint |
| 模型半成品进入 UI | 完整 schema + evidence 校验后才提交 |
| SQLite 高频小事务写竞争 | 第一版顺序片段、每片段一次事务、无新增并发 |
| SSE 重放重复卡片 | event_seq + stable finding ID 双重幂等 |
| 断线造成用户误判失败 | REST 为事实源，断线显示重连状态 |
| 快任务事件仍批量到达 | Condition 即时唤醒，数据库轮询仅兜底 |
| 新旧前端混用 | additive `fragment` + 临时 `issues` 兼容窗口 |

## 14. Constitution Check

项目 constitution 当前仍是模板；本增量沿用现有计划门禁：

| Gate | Result | Evidence |
|---|---|---|
| 复用现有能力 | PASS | 复用 ReviewEngine、持久队列、现有分析 SSE 和唯一 review store |
| 不建立第二事实源 | PASS | Finding/Job 仍由 SQLite/REST 权威读取，SSE 事件仅为提交后的 outbox |
| 结果可核验 | PASS | 仅发送证据校验后的完整 Finding |
| 可恢复 | PASS | event sequence、Last-Event-ID 和 REST 对账 |
| 向后兼容 | PASS | 原 REST 路径不变，旧 issues 提供迁移窗口，QA SSE 不变 |
| 控制复杂度 | PASS | 单 worker、顺序片段、SQLite + Condition，不引入外部队列 |
