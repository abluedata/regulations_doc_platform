# Data Model: 智能审查真实后端联通

**Date**: 2026-07-26

**Spec**: [spec.md](spec.md)

**API**: [contracts/review-api.openapi.yaml](contracts/review-api.openapi.yaml)

## Modeling Principles

1. 文档原文件、IR 与 preview 的唯一事实源仍是现有 document store；审查数据库只保存 `document_id + document_version_id` 引用及必要的快照摘要。
2. 文档版本、来源版本、范本版本、规则版本和 AnalysisSnapshot 发布后不可变；更新通过新版本表达。
3. 机器分析、人工决定和导出制品分开保存。人工处理不得覆盖 Finding 原始内容。
4. 所有异步工作都使用持久 Job 状态、租约、attempt 和单调 revision；HTTP/SSE 不是状态事实源。
5. PDF 与 DOCX evidence 是判别联合，不能把不同格式的位置塞入可空通用字段。
6. SQLite 外键开启，时间为 UTC ISO-8601，ID 为 UUID 字符串；JSON 字段写入前规范化并进行 Pydantic 校验。

## Relationship Overview

```text
Document -> DocumentVersion (existing/adapted document store)
                    ^
                    | reference only
ReviewBatch -> BatchDocument
     |
     +-> AnalysisSnapshot -> AnalysisJob -> AnalysisDocumentJob -> Finding -> EvidenceAnchor
                              |                                  |
                              |                                  +-> HumanDecision(finding)
                              +-> HumanDecision(overall)
                              +-> ReviewConversation -> ReviewMessage
                              +-> ExportArtifact
                              +-> AuditEvent

DocumentVersion -> SourceVersion -> RuleCandidate -> RuleVersion
                               \-> TemplateVersion

ReviewConfiguration -> pinned RuleVersion[] + overrides + preferences
AnalysisSnapshot -> pinned DocumentVersion[] + TemplateVersion? + RuleVersion[] + preferences
```

## Existing Document Model Adaptation

### Document

Existing document identity remains `doc_id`. Add these metadata fields to `.data/uploads/{doc_id}/meta.json`:

| Field | Type | Rules |
|-------|------|-------|
| `doc_id` | UUID/string | Existing stable identity |
| `filename` | string | Original display name |
| `format` | `pdf \| docx` | Derived and validated at upload |
| `status` | existing status enum | Current processing status |
| `current_version_id` | string/null | Only points to atomically published version |
| `created_at`, `updated_at` | datetime | UTC |

### DocumentVersion

Stored in the document store, not duplicated as a SQLite content table.

| Field | Type | Rules |
|-------|------|-------|
| `version_id` | string | Hash of file SHA-256 + parser schema + parse configuration |
| `document_id` | string | Parent document |
| `file_sha256` | 64-char hex | Original file integrity |
| `parser_schema_version` | string | Changes when locator/IR semantics change |
| `parse_config_hash` | string | Includes OCR flag and parser options |
| `format` | `pdf \| docx` | Discriminator for IR/anchors |
| `status` | `processing \| ready \| failed \| manual_required` | Only ready versions can enter deterministic analysis |
| `location_capability` | `exact \| block \| page \| none` | Maximum evidence precision |
| `page_count` | integer/null | PDF or source-reported count; not authoritative for DOCX rendering |
| `block_count` | integer | IR block count |
| `ir_sha256` | string | Validates immutable IR |
| `created_at` | datetime | UTC |

Directory contract:

```text
.data/uploads/{doc_id}/
├── original.{ext}
├── meta.json
└── versions/{version_id}/
    ├── ir.json
    ├── preview.md
    └── manifest.json
```

Legacy top-level `ir.json`/`preview.md` are readable as a compatibility version but are not eligible for precise evidence until reparsed into the new schema.

## Review Domain Entities

### ReviewBatch

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `name` | string(1..200) | User supplied |
| `declared_document_type` | string(1..100) | Used for template applicability/readiness |
| `enhanced_ocr` | boolean | Persisted upload/parse preference |
| `status` | `draft \| ready \| analyzing \| completed \| partial \| failed` | Derived from membership/jobs; draft/ready stored for workflow |
| `created_at`, `updated_at` | datetime | UTC |
| `revision` | integer | Monotonic optimistic concurrency value |

Validation:

- At most 20 active members.
- Documents can be removed only while no snapshot referencing the member has been created; removal is soft/auditable.
- `ready` requires at least one non-removed member and every member version to be ready.

### BatchDocument

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `batch_id` | UUID | FK ReviewBatch |
| `document_id` | string | Existing docs identity |
| `document_version_id` | string | Immutable document version reference |
| `display_order` | integer | Unique in batch |
| `readiness` | `pending \| ready \| blocked \| removed` | Cached workflow state, reconciled from docs |
| `readiness_reason` | string/null | Machine-readable/detail pair in API |
| `added_at`, `removed_at` | datetime/null | UTC |

Unique active membership: `(batch_id, document_id, document_version_id)`.

### SourceVersion

Represents a normative source or template source registered from an existing document version.

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `source_family_id` | UUID | Stable family across source revisions |
| `name` | string | Display name |
| `source_type` | `template \| regulation \| policy \| guideline` | Determines publishing workflow |
| `document_id`, `document_version_id` | string | Existing immutable source document reference |
| `applicable_document_types_json` | array[string] | Non-empty for publishable source |
| `status` | `processing \| ready \| failed \| archived` | Ready required for extraction |
| `created_at` | datetime | UTC |

Unique: `(source_family_id, document_version_id)`.

### Template and TemplateVersion

`Template` is the stable family identity; `TemplateVersion` is immutable.

| Template field | Type | Rules |
|----------------|------|-------|
| `id` | UUID | Primary key |
| `name` | string | Searchable |
| `category` | string | Filterable |
| `description` | string | Display |
| `created_at` | datetime | UTC |

| TemplateVersion field | Type | Rules |
|-----------------------|------|-------|
| `id` | UUID | Primary key |
| `template_id` | UUID | FK Template |
| `version` | positive integer | Unique per family |
| `source_version_id` | UUID | FK SourceVersion |
| `applicability_json` | object | Document types/conditions |
| `rule_version_ids_json` | array[UUID] | Frozen rule membership |
| `status` | `draft \| published \| archived` | Only published selectable |
| `published_at` | datetime/null | Required iff published |
| `created_at` | datetime | UTC |

Publishing never updates an older version. Archiving prevents new selection but does not invalidate snapshots.

### RuleCandidate

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `source_version_id` | UUID | FK SourceVersion |
| `extraction_job_id` | UUID | Creating job |
| `name`, `category`, `description` | string | Human review fields |
| `applicability_json` | object | Document/section/entity scope |
| `condition_json` | object | Structured predicate/semantic instruction |
| `threshold_json` | object/null | Value/unit/operator when applicable |
| `default_severity` | `low \| medium \| high` | Required |
| `source_anchor_json` | EvidenceAnchor | Must validate before confirm |
| `status` | `draft \| confirmed \| rejected \| blocked \| published` | State machine below |
| `blocking_reason` | string/null | Required for blocked |
| `reviewed_at`, `created_at`, `updated_at` | datetime/null | UTC |

### Rule and RuleVersion

`Rule` is stable identity; `RuleVersion` is the immutable executable version.

| Rule field | Type | Rules |
|------------|------|-------|
| `id` | UUID | Primary key |
| `name`, `category` | string | Search/filter |
| `created_at` | datetime | UTC |

| RuleVersion field | Type | Rules |
|-------------------|------|-------|
| `id` | UUID | Primary key |
| `rule_id` | UUID | FK Rule |
| `version` | positive integer | Unique per rule |
| `candidate_id` | UUID/null | Origin candidate |
| `source_version_id` | UUID | Source provenance |
| `definition_json` | object | Applicability, condition, threshold, severity, prompt schema |
| `source_anchor_json` | EvidenceAnchor | Validated provenance |
| `configurable_fields_json` | array[string] | Allowlisted overrides only |
| `status` | `published \| disabled \| archived` | Only published selectable |
| `published_at`, `created_at` | datetime | UTC |

No update mutates `definition_json`; any substantive edit creates `version + 1`.

### ReviewConfiguration

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `name` | string(1..200) | User supplied |
| `rule_selections_json` | array of `{rule_version_id, enabled, overrides}` | Pins exact versions |
| `sensitivity` | integer 0..100 | 0 broad/high recall; 100 strict/high confidence |
| `analysis_profile_id` | `accurate \| fast` | Backend-published logical profile |
| `marking_mode` | `standard \| high_only` | Suppresses display, never deletes results |
| `created_at`, `updated_at` | datetime | UTC |
| `revision` | integer | Optimistic concurrency |

Loading returns `invalid_rule_ids`; it never silently upgrades or drops invalid selections.

### AnalysisSnapshot

Immutable normalized input created in the same transaction as AnalysisJob.

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `batch_id` | UUID | Batch at launch |
| `document_refs_json` | ordered array `{document_id, version_id}` | 1..20 ready versions |
| `template_version_id` | UUID/null | Published at launch |
| `rule_inputs_json` | ordered array `{rule_version_id, overrides}` | Published, enabled rules |
| `sensitivity` | 0..100 | Frozen |
| `analysis_profile_id` | `accurate \| fast` | Frozen logical profile |
| `marking_mode` | `standard \| high_only` | Frozen |
| `input_hash` | SHA-256 | Canonical JSON hash |
| `created_at` | datetime | UTC |

The snapshot stores enough immutable references for reproduction, not copies of IR or source files.

### AnalysisJob

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `snapshot_id` | UUID | FK, immutable |
| `parent_job_id` | UUID/null | Retry origin |
| `status` | `queued \| running \| completed \| partial \| failed` | State machine below |
| `progress` | integer 0..100 | Non-decreasing within revision |
| `revision` | integer | Strictly monotonic for UI ordering |
| `attempt` | integer | Claim attempt count |
| `lease_owner`, `lease_until` | string/datetime null | Persistent runner lease |
| `failure_code`, `failure_message` | string/null | Overall terminal error |
| `result_revision`, `decision_revision` | integer | Export consistency boundaries |
| `created_at`, `started_at`, `finished_at`, `updated_at` | datetime/null | UTC |

### AnalysisDocumentJob

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `analysis_job_id` | UUID | FK |
| `document_id`, `document_version_id` | string | Must occur in snapshot |
| `status` | `queued \| running \| completed \| failed` | Per-document state |
| `progress` | integer 0..100 | Non-decreasing |
| `attempt` | integer | Increment on retry claim |
| `failure_code`, `failure_message`, `retryable` | nullable | Required on failed |
| `started_at`, `finished_at` | datetime/null | UTC |

Unique `(analysis_job_id, document_version_id)`. A retry AnalysisJob references only failed document versions.

### Finding

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `analysis_job_id`, `analysis_document_job_id` | UUID | Origin |
| `snapshot_id` | UUID | Frozen inputs |
| `document_id`, `document_version_id` | string | Evidence target |
| `rule_version_id` | UUID/null | Null only for deterministic built-in structural rule with `checker_id` |
| `checker_id` | string/null | Versioned deterministic checker |
| `conclusion` | `direct_violation \| deviation \| insufficient_information \| manual_review` | Classification |
| `severity` | `low \| medium \| high` | Machine severity |
| `title`, `reason`, `suggestion`, `location_label` | string | Display content |
| `evidence_anchor_json` | EvidenceAnchor | Required; precision may be degraded |
| `reference_anchor_json` | EvidenceAnchor/null | Rule/template/source reference |
| `conflict_group_id` | UUID/null | Same value keeps conflicting findings together |
| `suppressed` | boolean | True for non-high in high_only mode; never deleted |
| `fingerprint` | SHA-256 | Snapshot/doc/rule/conclusion/evidence uniqueness |
| `created_at` | datetime | UTC |

Unique `(analysis_job_id, fingerprint)`. Original Finding rows are immutable.

## Evidence Anchor Discriminated Union

Common fields:

| Field | Type | Rules |
|-------|------|-------|
| `kind` | `pdf \| docx` | Discriminator |
| `document_id`, `document_version_id` | string | Must match loaded IR |
| `precision` | `exact \| block \| page` | `exact` only if all format requirements pass |
| `quote` | string | Exact evidence text |
| `quote_sha256` | string | Hash after documented line-ending normalization only |
| `validation_status` | `valid \| degraded \| invalid` | Invalid cannot persist as deterministic finding |

### PdfEvidenceAnchor

| Field | Type | Rules |
|-------|------|-------|
| `page_number` | integer >=1 | Source PDF page |
| `coordinate_space` | literal `normalized-1000-top-left` | No implicit coordinate inference |
| `rects` | array of `{x0,y0,x1,y1}` | For exact, non-empty; each 0..1000 and x0<x1/y0<y1 |
| `block_ids` | array[string] | IR references used for revalidation |

For page precision `rects` may be empty but `page_number` and validated page membership remain required.

### DocxEvidenceAnchor

| Field | Type | Rules |
|-------|------|-------|
| `container_kind` | `paragraph \| table_cell` | Locator interpretation |
| `locator_id` | string | Stable within the immutable document version |
| `document_order` | integer >=0 | Diagnostic/fallback order, not sole identity |
| `start` | integer >=0 | Unicode code-point offset, inclusive |
| `end` | integer > start | Unicode code-point offset, exclusive |
| `block_id` | string | IR block holding locator |

For block precision range may cover the validated container; exact requires `container_text[start:end] == quote` after only the contract's newline normalization.

## Decisions, Conversations, Audit, Export

### HumanDecision

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `analysis_job_id` | UUID | FK |
| `finding_id` | UUID/null | Null means overall decision |
| `decision_type` | finding: `open \| accepted \| dismissed \| resolved`; overall: `approved \| rejected` | Validated by target kind |
| `comment` | string/null | Human note |
| `revision` | integer | Increments per target |
| `created_at`, `updated_at` | datetime | UTC |

Unique active target `(analysis_job_id, finding_id)` with an audit event for every change.

### ReviewConversation and ReviewMessage

| Conversation field | Type | Rules |
|--------------------|------|-------|
| `id` | UUID | Primary key |
| `analysis_job_id` | UUID | Scope root |
| `created_at`, `updated_at` | datetime | UTC |
| `revision` | integer | Message list revision |

| Message field | Type | Rules |
|---------------|------|-------|
| `id` | UUID | Primary key |
| `conversation_id` | UUID | FK |
| `request_id` | UUID/null | Generation identity |
| `role` | `user \| assistant` | System context is reconstructed, not client persisted |
| `content` | string | Error text is not saved as assistant content |
| `finding_id` | UUID/null | Optional focus |
| `citations_json` | array[EvidenceAnchor] | Assistant facts require >=1 citation |
| `status` | `complete \| incomplete` | Stop/disconnect may persist incomplete content only when explicitly identified |
| `created_at` | datetime | UTC |

### AuditEvent

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `analysis_job_id` | UUID/null | Query scope |
| `event_type` | enum/string | job_created, snapshot_frozen, analysis_completed, decision_changed, export_created, etc. |
| `target_type`, `target_id` | string | Domain object |
| `payload_json` | object | Immutable before/after IDs/revisions, no full document content |
| `created_at` | datetime | UTC |

Append-only; API exposes no update/delete.

### ExportArtifact

| Field | Type | Rules |
|-------|------|-------|
| `id` | UUID | Primary key |
| `analysis_job_id` | UUID | FK |
| `status` | `queued \| running \| completed \| failed` | Persistent job state |
| `format` | literal `docx` | MVP only |
| `result_revision`, `decision_revision` | integer | Frozen at request time |
| `file_path` | string/null | Server-owned path under exports directory |
| `sha256`, `size_bytes` | nullable | Required completed |
| `failure_code`, `failure_message` | nullable | Required failed |
| `created_at`, `completed_at` | datetime/null | UTC |

### IdempotencyRecord

| Field | Type | Rules |
|-------|------|-------|
| `scope` | string | Route/action semantic scope |
| `key` | string(1..200) | `Idempotency-Key` |
| `request_hash` | SHA-256 | Canonical method/path/body/actor hash |
| `resource_type`, `resource_id` | string | Replay target |
| `status_code` | integer | Original success response |
| `created_at`, `expires_at` | datetime | Expiry must exceed retry/reload window |

Primary key `(scope, key)`. Same hash replays; different hash returns 409 `IDEMPOTENCY_KEY_REUSED`.

## State Transitions

### AnalysisJob

```text
queued -> running -> completed
                  -> partial
                  -> failed
running --expired lease/startup recovery--> queued
```

- `completed`: every selected document completed, including zero findings.
- `partial`: at least one document completed and at least one failed.
- `failed`: no selected document produced a valid completed result or a fatal snapshot/job error occurred.
- Retry creates a new child job; terminal rows are not reset to queued.

### AnalysisDocumentJob

```text
queued -> running -> completed
                  -> failed
running --expired lease--> queued
```

### RuleCandidate

```text
draft -> confirmed -> published
      -> rejected
      -> blocked
blocked -> draft   (only after source evidence/config correction)
```

Publication requires confirmed status, valid source anchor and successful immutable RuleVersion transaction.

### TemplateVersion

```text
draft -> published -> archived
```

No transition out of archived; create a new version instead.

### ExportArtifact

```text
queued -> running -> completed
                  -> failed
running --expired lease--> queued
```

## Transaction Boundaries

1. **Launch analysis**: validate references, create snapshot, job, document jobs, idempotency row and audit event in one transaction.
2. **Publish rule/template**: validate candidate/source evidence, allocate family version, insert immutable version, update candidate status and append audit event in one transaction.
3. **Persist findings**: insert validated findings and increment job `result_revision` atomically per completed document.
4. **Decision update**: compare expected revision, upsert HumanDecision, increment `decision_revision`, append audit event atomically.
5. **Create export**: capture current result/decision revisions, create artifact/idempotency/audit rows atomically; file is published atomically after checksum.
6. **Claim job**: conditional update from queued or expired lease to running with lease owner/expiry; only one row can be claimed.

## Indexes and Retention

Required SQLite indexes:

- `batch_documents(batch_id, readiness, display_order)`
- `source_versions(source_family_id, created_at)`
- `rule_versions(rule_id, version)` unique
- `template_versions(template_id, version)` unique
- `analysis_jobs(status, created_at)` and `(snapshot_id)`
- `analysis_document_jobs(analysis_job_id, status)`
- `findings(analysis_job_id, severity, suppressed)` and `(document_version_id)`
- `human_decisions(analysis_job_id, finding_id)` unique
- `review_messages(conversation_id, created_at)`
- `audit_events(analysis_job_id, created_at)`
- `export_artifacts(analysis_job_id, created_at)`

MVP does not implement automatic deletion. Deleting/archiving a document family must be blocked while any SourceVersion, Snapshot, Finding citation or ExportArtifact references its version. A later retention feature may archive cold artifacts only after referential and audit policy is defined.

## Migration and Compatibility

- SQLite schema uses `PRAGMA user_version` and ordered, transactional migrations; startup refuses to serve review routes if migration fails.
- Existing docs JSON and chat JSON remain untouched. Current docs methods transparently resolve `current_version_id`.
- Existing ES records without `document_version_id/locator_refs` remain usable for generic search, but review analysis rejects or degrades them until explicit reparse/reindex.
- No database row points to mutable `current`; snapshots always store an explicit `version_id`.
