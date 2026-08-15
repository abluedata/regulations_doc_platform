# Review Event Contract

**Date**: 2026-07-26

**OpenAPI**: [review-api.openapi.yaml](review-api.openapi.yaml)

## Scope

审查问答复用原工作台的 SSE 事件名称和前端交互模型：`meta`、`status`、`token`、`done`、`error`。新增入口为：

```http
POST /api/review/conversations/{conversation_id}/stream
Accept: text/event-stream
Content-Type: application/json
```

通用 `/api/chat/*` 的路径、请求字段、事件字段和停止语义保持向后兼容。后端 `sse.py` 和前端 `api/sse.ts` 是两类入口共用的 framing/decoder；review endpoint 只增加审查范围校验和 `done.citations`。

## Wire Format

每个事件使用标准 SSE framing。`data` 必须是单个 JSON object；服务端通过 JSON encoder 处理换行，不手工拼接用户或模型文本。

```text
event: token
data: {"request_id":"...","text":"审查"}

```

Headers:

```http
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

所有事件必须带同一个 `request_id`。客户端发现 request ID 不匹配时忽略该事件，不得写入当前回答。

## Request

```json
{
  "request_id": "4a49fdea-ae15-48a2-adf5-86cecbca68d8",
  "message": "为什么这一条被判定为高风险？",
  "finding_id": "b61e60aa-d31d-4814-8064-44ee95a617f3",
  "history": [
    {"role": "user", "content": "这份合同最主要的问题是什么？", "status": "complete"},
    {"role": "assistant", "content": "主要问题位于付款条款……", "status": "complete"}
  ]
}
```

- `conversation_id` 已绑定一个 AnalysisJob，客户端不能在 body 覆盖 job scope。
- `finding_id` 可空；提供时必须属于该 job。
- 服务端从持久消息与请求 history 交叉校验顺序和内容，丢弃 `incomplete` assistant 消息作为后续事实上下文，但可以将其作为标明未完成的对话展示。
- review QA 只检索 snapshot 中的 document/source versions，不允许 Web fallback 或全局知识库补全。

## Event Types

### `meta`

必须是首个业务事件，用于确认请求身份和冻结的审查范围。

```text
event: meta
data: {"request_id":"4a49fdea-ae15-48a2-adf5-86cecbca68d8","conversation_id":"...","analysis_job_id":"...","snapshot_id":"...","finding_id":"..."}
```

Required fields: `request_id`, `conversation_id`, `analysis_job_id`, `snapshot_id`. `finding_id` may be null.

### `status`

表示可见处理阶段，不是持久 job 状态。

```text
event: status
data: {"request_id":"...","stage":"retrieving","message":"正在核对当前任务证据"}
```

Allowed `stage` values:

- `validating`: validating conversation, job and finding scope
- `retrieving`: retrieving only frozen document/rule/source versions
- `generating`: LLM generation has started
- `stopping`: cooperative stop was observed

客户端展示 message，但业务判断使用 `stage`。未知 stage 可展示为一般进度，不得导致 decoder 失败。

### `token`

```text
event: token
data: {"request_id":"...","text":"该条款约定的通知期限"}
```

- `text` may be an arbitrary Unicode fragment and is appended in receive order.
- Token text is not HTML. Rendering passes the final Markdown through shared `safeMarkdown.ts` and DOMPurify.
- Server must stop emitting token after a terminal event.

### `done`

唯一成功终态。正常完成与用户停止都使用 `done`，用 `incomplete` 区分；网络中断没有服务端可保证送达的终态，客户端随后 GET conversation 恢复。

```text
event: done
data: {
  "request_id": "4a49fdea-ae15-48a2-adf5-86cecbca68d8",
  "message_id": "064cb4cd-28d1-4622-a8a8-44923addc883",
  "content": "该条款……",
  "incomplete": false,
  "citations": [
    {
      "kind": "pdf",
      "document_id": "doc-123",
      "document_version_id": "version-abc",
      "precision": "exact",
      "quote": "通知期限为三个工作日",
      "quote_sha256": "...",
      "validation_status": "valid",
      "page_number": 4,
      "coordinate_space": "normalized-1000-top-left",
      "rects": [{"x0": 120, "y0": 318, "x1": 635, "y1": 354}],
      "block_ids": ["p4-b12"]
    }
  ]
}
```

Rules:

- `content` is the authoritative accumulated content; client may replace its locally joined tokens with this value.
- Any factual review explanation must contain at least one server-validated citation. When evidence is insufficient, content must explicitly say so; citations may be empty only for that scoped insufficiency response.
- `incomplete=true` means stopped generation. It can be displayed and persisted distinctly but must not be treated as a complete assistant answer in later history.
- `done` persistence uses compare-and-set on request state so a concurrent stop cannot also persist a complete message.

### `error`

唯一失败终态。Error data is never appended to assistant content or stored as an assistant message.

```text
event: error
data: {"request_id":"...","code":"REVIEW_QA_SCOPE_UNAVAILABLE","message":"当前审查证据不可用","retryable":true,"trace_id":"..."}
```

Required: `request_id`, `code`, `message`, `retryable`. `trace_id` may be null.

Typical codes:

| Code | Meaning | Retryable |
|------|---------|-----------|
| `REVIEW_QA_SCOPE_INVALID` | Conversation/finding does not belong to job | false |
| `REVIEW_QA_SCOPE_UNAVAILABLE` | Frozen IR/index temporarily unavailable | true |
| `REVIEW_QA_EVIDENCE_INSUFFICIENT` | No usable evidence; normally return done with scoped explanation | false |
| `REVIEW_QA_MODEL_TIMEOUT` | Model transport timed out | true |
| `REVIEW_QA_CANCELLED` | Internal cancellation before any stable content; user stop normally uses incomplete done | true |

## Ordering and Terminal Rules

```text
meta
  -> status*
  -> token*
  -> done | error
```

- Exactly one `meta` and at most one terminal event.
- `status` and `token` may interleave after meta.
- Server emits no event after terminal.
- Decoder tolerates unknown event types for forward compatibility and logs them without treating payload as text.
- Duplicate terminal event or token after terminal is ignored client-side and recorded as a telemetry/test failure.

## Stop Contract

```http
POST /api/review/conversations/{conversation_id}/stop
Content-Type: application/json

{"request_id":"4a49fdea-ae15-48a2-adf5-86cecbca68d8"}
```

Response `202`:

```json
{"request_id":"4a49fdea-ae15-48a2-adf5-86cecbca68d8","accepted":true}
```

- Cancellation registry key is `(conversation_id, request_id)`, not a global boolean.
- Stopping review QA cannot cancel another review request or any generic chat request.
- `accepted=false` is allowed when the request is already terminal; it is idempotent and not an error.
- The stream should visibly reach `status(stopping)` or `done(incomplete=true)` within 2 seconds under normal local execution.

## Disconnect and Recovery

SSE disconnect does not imply cancellation. The server may complete the answer. The client:

1. Marks the local pending answer as reconnecting, not failed content.
2. Calls `GET /api/review/conversations/{conversation_id}`.
3. If the request's message exists, replaces local state using its `complete/incomplete` status and citations.
4. If it does not exist and no generation is registered, exposes retry with a new `request_id`.

Analysis job progress is not transported through this QA stream. ReviewConsole recovers analysis exclusively through `GET /api/review/analysis-jobs/{job_id}` and ignores any response whose `revision` is lower than the current store revision.

## Shared Decoder Acceptance Cases

- UTF-8 Chinese tokens split across network chunks decode without corruption.
- Multiple SSE events in one chunk and one event across multiple chunks both parse.
- JSON `data` containing escaped newlines remains one payload.
- Unknown fields and events do not break generic chat.
- `error.message` is shown as error UI, never assistant Markdown.
- A stop/done race persists at most one assistant message and correctly marks `incomplete`.
- Review citations decode to the OpenAPI `EvidenceAnchor` discriminated union.
