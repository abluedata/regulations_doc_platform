# Review Analysis Event Contract

**Date**: 2026-08-16  
**OpenAPI**: [review-api.openapi.yaml](review-api.openapi.yaml)  
**Plan**: [../streaming-findings-plan.md](../streaming-findings-plan.md)

## Scope

本契约定义审查分析任务的增量结果流，不定义审查问答 token 流。入口保持：

```http
GET /api/review/analysis-jobs/{job_id}/stream
Accept: text/event-stream
Last-Event-ID: 41
```

分析是持久后台任务。SSE 断开不取消分析，REST Job/Findings 始终是恢复和最终结果的事实源。

## Response Headers

```http
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

服务端建议发送：

```text
retry: 1000
```

## Framing And Identity

每个持久业务事件必须包含 SSE `id`：

```text
id: 42
event: progress
data: {"job_id":"...","event_seq":42}

```

规则：

- `id` 是该 AnalysisJob 内严格单调递增的十进制整数。
- `data.event_seq` 必须等于 SSE `id`。
- 每个事件必须包含 `job_id`、`job_revision` 和 `result_revision`。
- JSON 由统一 encoder 产生，不手工拼接文档、规则或模型文本。
- 空闲连接可发送 `: heartbeat` comment；heartbeat 没有 ID，不是业务事件。

## Resume Request

客户端重连时发送已经完整应用的最高序号：

```http
Last-Event-ID: 41
```

服务端只返回 `event_seq > 41` 的事件。未发送该 header 等价于从 0 开始。

如果历史游标不可用，服务端发送 `reset`，客户端必须 GET job/findings 完成权威同步：

```text
id: 90
event: reset
data: {"job_id":"...","event_seq":90,"job_revision":18,"result_revision":7,"reason":"cursor_expired"}

```

MVP 不主动裁剪运行中任务事件，因此 `reset` 主要用于迁移和损坏恢复。

## Event Types

### `progress`

表示已经提交的处理进度，不携带半成品 Finding：

```text
id: 42
event: progress
data: {
  "job_id":"job-1",
  "event_seq":42,
  "job_revision":8,
  "result_revision":2,
  "status":"running",
  "document_id":"doc-1",
  "document_version_id":"version-1",
  "fragment_id":"version-1:planner-v1:0032-0064",
  "fragment_index":1,
  "fragment_total":24,
  "processed_fragments":1,
  "total_fragments":24,
  "finding_count":2,
  "message":"已检查 1/24 个片段"
}

```

`processed_fragments` 和 `total_fragments` 均为非负整数且前者不大于后者。同一 job 的已提交进度不得倒退。

### `fragment`

一个已经原子提交的分析片段。`findings` 可以为空：

```text
id: 43
event: fragment
data: {
  "job_id":"job-1",
  "event_seq":43,
  "job_revision":9,
  "result_revision":3,
  "document_id":"doc-1",
  "document_version_id":"version-1",
  "fragment_id":"version-1:planner-v1:0032-0064",
  "fragment_index":1,
  "fragment_total":24,
  "scope":"fragment_local",
  "processed_fragments":2,
  "total_fragments":24,
  "finding_count":3,
  "findings":[
    {
      "id":"stable-finding-id",
      "analysis_job_id":"job-1",
      "snapshot_id":"snapshot-1",
      "document_id":"doc-1",
      "document_version_id":"version-1",
      "conclusion":"direct_violation",
      "severity":"high",
      "title":"付款期限不明确",
      "reason":"付款期限缺少可执行日期或天数。",
      "suggestion":"明确约定收到合格发票后 30 日内付款。",
      "location_label":"付款条款",
      "evidence_anchor":{},
      "suppressed":false,
      "created_at":"2026-08-16T00:00:00Z"
    }
  ]
}

```

规则：

- `scope` 为 `fragment_local` 或 `document_global`。
- 每个 Finding 必须已经持久化，且可由 GET findings 读取。
- Finding ID 在该分析任务内稳定；重复事件不得创建新卡片。
- `findings=[]` 仍是有效片段完成事件。
- 未闭合模型 JSON、未经验证 quote、无效 EvidenceAnchor 不得出现。

### `fragment_error`

可恢复片段失败，不是任务终态：

```text
id: 44
event: fragment_error
data: {
  "job_id":"job-1",
  "event_seq":44,
  "job_revision":10,
  "result_revision":3,
  "document_id":"doc-1",
  "document_version_id":"version-1",
  "fragment_id":"version-1:planner-v1:0064-0096",
  "code":"ANALYSIS_FRAGMENT_MODEL_TIMEOUT",
  "message":"该片段分析超时，可在任务完成后重试。",
  "retryable":true,
  "processed_fragments":3,
  "total_fragments":24
}

```

客户端展示降级/失败计数，但不把 message 当作 Finding 内容。

### `complete`

唯一成功或降级终态：

```text
id: 71
event: complete
data: {
  "job_id":"job-1",
  "event_seq":71,
  "job_revision":21,
  "result_revision":9,
  "status":"complete_degraded",
  "processed_fragments":24,
  "total_fragments":24,
  "failed_fragments":1,
  "finding_count":9
}

```

`status` 只能是 `complete` 或 `complete_degraded`。客户端收到后必须执行一次 REST 对账。

### `error`

唯一失败/取消终态：

```text
id: 72
event: error
data: {
  "job_id":"job-1",
  "event_seq":72,
  "job_revision":22,
  "result_revision":3,
  "status":"failed",
  "code":"ANALYSIS_JOB_FAILED",
  "message":"审查任务失败。",
  "retryable":true
}

```

`status` 为 `failed` 或 `cancelled`。内部堆栈、provider 原始响应和密钥不得进入 payload。

### `issues` Compatibility Event

迁移窗口内服务端可以在同一片段提交后继续发送旧 `issues` 事件，其 `data` 为该片段的 Finding 数组。新客户端一旦收到 `fragment`，必须忽略同一连接后续 `issues`；只收到旧 `issues` 时，允许回退到 GET 全量 findings。

兼容窗口结束后删除 `issues`，不改变 `fragment` 契约。

## Ordering And Terminal Rules

```text
(progress | fragment | fragment_error | reset)*
  -> complete | error
```

- 每条连接最多一个终态事件。
- 终态后不得发送任何业务事件。
- `event_seq` 按数据库提交顺序分配；并发执行时不承诺 fragment index 顺序。
- 客户端必须按 event sequence 应用，页面可按 severity/document/location 独立排序。
- 未知事件必须被 decoder 安全忽略并记录，不得作为 Finding 或错误文本显示。

## Client Consistency Rules

客户端维护 `last_event_seq`：

1. `event_seq <= last_event_seq`: 重复事件，忽略。
2. `event_seq == last_event_seq + 1`: 正常应用。
3. `event_seq > last_event_seq + 1`: 检测到间隙，暂停增量应用并 GET job/findings。
4. `reset`: GET job/findings，并把响应的 event cursor 作为新起点。
5. `complete/error`: 终止当前连接；complete 对账，error 读取 Job 获取权威错误。

Finding 使用持久 UUID upsert，其幂等来源是服务端唯一 fingerprint；分析事件不覆盖已经通过 REST 加载的 HumanDecision。SSE payload 与 GET 结果冲突时，以更高 `result_revision` 的 REST 结果为准。

## Disconnect Semantics

- 断开连接不改变 Job 状态，也不触发取消。
- 客户端显示“正在重新连接”，不得把断开转换为分析失败。
- 重连使用 Last-Event-ID；重试超过前端预算后仍可降级为定期 GET 状态和 findings。
- 页面重新打开时先 GET Job/Findings，再从服务端返回的最新 event cursor 订阅。

## Acceptance Cases

- 首个 fragment 在任务 complete 之前到达。
- 零 Finding 片段仍产生 fragment/progress 并推进计数。
- UTF-8 中文和大型 Finding payload 跨网络 chunk 正确解析。
- 多个 SSE 事件同一网络 chunk 正确解析。
- 断开后使用 Last-Event-ID 只回放缺失事件。
- 重复 fragment 不产生重复卡片或重复 Finding。
- event sequence 间隙触发 REST 对账。
- fragment_error 后允许后续 fragment，并最终进入降级终态。
- complete/error 恰好一个，终态后没有业务事件。
- 旧客户端仍能通过 issues + GET 看到增量结果。
