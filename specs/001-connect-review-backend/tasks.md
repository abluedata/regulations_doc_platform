---
description: "TDD implementation tasks for intelligent review backend integration"
---

# Tasks: 智能审查真实后端联通

**Input**: Design documents from `/specs/001-connect-review-backend/`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: TDD is mandatory. Every RED task must be run and fail for the intended missing behavior before its paired implementation task starts. Every implementation task must run the focused test to GREEN and keep the relevant existing suite green.

**Organization**: Tasks are grouped by the five user stories. The complete P1/P2/P3 scope is MVP per the clarified specification.

## Phase 1: Setup and Baseline

**Purpose**: Prepare the isolated branch and reproducible test toolchain without changing feature behavior.

- [X] T001 Verify and document the isolated `new-agent` worktree baseline using backend unittest, frontend Vitest, typecheck, and build commands from `specs/001-connect-review-backend/quickstart.md`
- [X] T002 Add exact frontend runtime dependencies `pdfjs-dist` and `dompurify` plus dev dependency `@playwright/test` in `frontend/package.json` and `frontend/package-lock.json`
- [X] T003 [P] Create backend/frontend test fixture directories and legal-safe repeated-text PDF/DOCX fixture metadata in `backend/tests/fixtures/review/README.md` and `frontend/tests/e2e/fixtures/README.md`
- [X] T004 [P] Verify `.gitignore` covers Python, Node, test artifacts, `.data/`, and `.worktrees/` in `.gitignore`

**Checkpoint**: Dependencies are reproducible and existing behavior has a recorded clean baseline.

---

## Phase 2: Foundational Capabilities

**Purpose**: Build shared versioning, persistence, task, transport, search, and rendering boundaries that block every user story.

### Document versioning and locator-ready IR

- [ ] T005 Write and run failing immutable document version, legacy compatibility, and reparse preservation tests in `backend/tests/test_document_versions.py`
- [ ] T006 Implement immutable `versions/{version_id}` storage and compatible current-version reads in `backend/services/document_store.py` and `backend/services/document_pipeline.py`, then make T005 green
- [ ] T007 Write and run failing MinerU/PDF/DOCX locator preservation tests in `backend/tests/test_document_locators.py`
- [ ] T008 Preserve MinerU normalized bbox, build pdfplumber word rectangles, and assign stable DOCX paragraph/table-cell locators in `mineru_service/adapter.py` and `backend/services/document_pipeline.py`, then make T007 green

### Review repository and persistent jobs

- [ ] T009 Write and run failing SQLite schema, foreign-key, transaction, idempotency, revision, and migration tests in `backend/tests/test_review_store.py`
- [ ] T010 Implement WAL-enabled SQLite schema/repository and ordered migrations in `backend/services/review_store.py`, then make T009 green
- [ ] T011 Write and run failing persistent lease claim, heartbeat, recovery, retry, and single-active-kind tests in `backend/tests/test_review_jobs.py`
- [ ] T012 Implement the single-process persistent task runner and lifecycle handlers in `backend/services/review_jobs.py`, then make T011 green

### Shared LLM, SSE, scoped search, and API conventions

- [ ] T013 Write and run failing compatibility tests for generic chat SSE framing, request cancellation, and shared LLM transport in `backend/tests/test_chat_compatibility.py`
- [ ] T014 Extract shared LLM transport and SSE/cancellation helpers into `backend/services/llm_client.py` and `backend/services/sse.py`, adapt `backend/services/qa_service.py`, `backend/services/parallel_qa.py`, and `backend/api/routes/chat.py`, then make T013 green without changing `/api/chat/*`
- [ ] T015 Write and run failing Elasticsearch metadata and document/source version scope tests in `backend/tests/test_scoped_search.py`
- [ ] T016 Add `document_version_id`, `block_id`, locator references, `is_current`, and optional version filters in `backend/services/indexer.py` and `backend/services/search.py`, then make T015 green while preserving unscoped generic search
- [ ] T017 Write and run failing review error-envelope, pagination, legacy string-detail compatibility, and router lifecycle tests in `backend/tests/test_review_api_foundation.py` and `frontend/src/api/http.spec.ts`
- [ ] T018 Implement review Pydantic base schemas in `backend/api/review_schemas.py`, shared error translation in review routes, object/string detail handling in `frontend/src/api/http.ts`, and runner lifespan wiring in `backend/api/main.py`, then make T017 green

### Shared frontend safety and transport

- [ ] T019 Write and run failing SSE chunk-boundary/unknown-event tests and malicious Markdown sanitization tests in `frontend/src/api/sse.spec.ts` and `frontend/src/utils/safeMarkdown.spec.ts`
- [ ] T020 Extract the single SSE decoder to `frontend/src/api/sse.ts`, implement `marked` plus DOMPurify rendering in `frontend/src/utils/safeMarkdown.ts`, and adapt `frontend/src/api/chat.ts` and `frontend/src/components/ChatMessage.vue`, then make T019 green

**Checkpoint**: Immutable document versions, locator-ready IR, transactional review state, recoverable jobs, scoped retrieval, shared SSE/LLM, and safe rendering are independently tested.

---

## Phase 3: User Story 1 - 完成真实审查任务 (Priority: P1)

**Goal**: Replace all four-step Mock behavior with persistent batches, frozen snapshots, real asynchronous analysis, per-document status, reload recovery, and failed-document retry.

**Independent Test**: Upload supported documents through existing docs APIs, build a batch, select published inputs, launch once with an idempotency key, observe real per-document states/results, reload by job ID, and retry only failed documents.

### Tests for User Story 1 (RED first)

- [ ] T021 [P] [US1] Write and run failing batch membership/readiness and snapshot-freeze service tests in `backend/tests/test_review_batches.py`
- [ ] T022 [P] [US1] Write and run failing analysis structural-check, scoped semantic classification, conflict, manual-review, and finding fingerprint tests in `backend/tests/test_review_analysis.py`
- [ ] T023 [P] [US1] Write and run failing batch/analysis OpenAPI contract tests, idempotency replay/conflict tests, partial failure tests, and failed-only retry tests in `backend/tests/test_review_api.py`
- [ ] T024 [P] [US1] Write and run failing review API client/store revision, workflow gating, duplicate launch, and reload recovery tests in `frontend/src/api/review.spec.ts` and `frontend/src/stores/review.spec.ts`

### Implementation for User Story 1

- [ ] T025 [US1] Implement ReviewBatch, BatchDocument, readiness validation, AnalysisSnapshot, and launch transaction use cases in `backend/services/review_service.py` and `backend/services/review_store.py`, then make T021 green
- [ ] T026 [US1] Implement deterministic structure checks, scoped retrieval, structured semantic classification, conflict retention, evidence validation gating, and Finding persistence in `backend/services/review_analysis.py` and `backend/services/evidence.py`, then make T022 green
- [ ] T027 [US1] Implement batch, analysis job, findings, status, and failed-only retry endpoints in `backend/api/routes/reviews.py`, register the router in `backend/api/main.py`, and make T023 green
- [ ] T028 [US1] Implement the typed review client in `frontend/src/api/review.ts` and replace Mock actions with resource IDs, authoritative polling, and monotonic revisions in `frontend/src/stores/review.ts`, then make T024 green
- [ ] T029 [US1] Adapt `frontend/src/views/review/ReviewUploadView.vue` to existing docs upload/status plus ReviewBatch membership and real per-file removal/readiness states
- [ ] T030 [US1] Adapt `frontend/src/views/review/ReviewTemplatesView.vue` and `frontend/src/views/review/ReviewRulesView.vue` to persist selected resource versions and block launch until inputs are valid
- [ ] T031 [US1] Adapt `frontend/src/views/review/ReviewConsoleView.vue`, `frontend/src/components/review/ReviewFooter.vue`, and review summary components to show real job progress, per-document failure, retry, zero-risk, and reload states
- [ ] T032 [US1] Write and run the failing-then-green multi-document workflow integration test covering upload reference, launch, restart recovery, partial success, failed-only retry, and no duplicate findings in `backend/tests/test_review_workflow.py`

**Checkpoint**: User Story 1 is functional without Mock data and independently testable.

---

## Phase 4: User Story 2 - 查看可核验风险与原文高亮 (Priority: P1)

**Goal**: Bind every finding to an immutable, format-specific evidence anchor and provide precise, bidirectional PDF/DOCX highlighting with explicit degradation.

**Independent Test**: Click findings for repeated text, multi-rect PDF content, DOCX paragraphs and table cells; the exact annotated instance highlights, while version/quote mismatch never highlights another instance.

### Tests for User Story 2 (RED first)

- [ ] T033 [P] [US2] Write and run failing PDF/DOCX anchor schema, range, quote hash, exact/degraded/invalid, and immutable-version validation tests in `backend/tests/test_evidence_anchors.py`
- [ ] T034 [P] [US2] Write and run failing exact-version file/preview endpoint tests and legacy-version degradation tests in `backend/tests/test_document_preview_api.py`
- [ ] T035 [P] [US2] Write and run failing shared DocumentViewer dispatch, mismatch refusal, and bidirectional selection component tests in `frontend/src/components/document/DocumentViewer.spec.ts`

### Implementation for User Story 2

- [ ] T036 [US2] Complete typed PDF/DOCX evidence construction and validation with no quote-first fallback in `backend/services/evidence.py`, then make T033 green
- [ ] T037 [US2] Add exact-version file and locator-preserving preview responses to `backend/api/routes/docs.py` and document DTOs to `backend/api/schemas.py`, then make T034 green
- [ ] T038 [US2] Implement shared format dispatch and evidence selection events in `frontend/src/components/document/DocumentViewer.vue`, then make the dispatch portion of T035 green
- [ ] T039 [US2] Implement PDF.js canvas/text-layer rendering, normalized rectangle viewport transforms, zoom/rotation/DPR handling, and overlay selection in `frontend/src/components/document/PdfEvidenceViewer.vue`
- [ ] T040 [US2] Implement safe structured DOCX locator rendering, Unicode code-point range highlighting, table-cell handling, and block degradation in `frontend/src/components/document/DocxEvidenceViewer.vue`, then make T035 fully green
- [ ] T041 [US2] Adapt `frontend/src/views/DocPreviewView.vue`, `frontend/src/views/review/ReviewConsoleView.vue`, and `frontend/src/components/review/RiskCard.vue` to share DocumentViewer and synchronize active finding/evidence in both directions
- [ ] T042 [US2] Write and run failing-then-green Playwright tests for repeated PDF text, zoom/rotation/DPR overlays, DOCX repeated paragraphs/table cells, mismatch refusal, and overlap selection in `frontend/tests/e2e/review-highlighting.spec.ts`

**Checkpoint**: User Story 2 provides verifiable exact or explicitly degraded location and never silently highlights the wrong text.

---

## Phase 5: User Story 3 - 从范本和规范文件形成受控规则 (Priority: P2)

**Goal**: Register existing document versions as sources, extract evidence-backed draft candidates, require human confirmation, publish immutable rule/template versions, and load pinned reusable configurations.

**Independent Test**: Register a ready source containing a threshold and notice period, extract candidates, block invalid evidence, confirm/publish valid candidates, and prove old analysis snapshots do not change after a new version is published.

### Tests for User Story 3 (RED first)

- [ ] T043 [P] [US3] Write and run failing source, candidate state machine, evidence publication gate, immutable rule/template version, and configuration invalid-rule tests in `backend/tests/test_review_rules.py`
- [ ] T044 [P] [US3] Write and run failing source/extraction/candidate/template/rule/configuration contract and idempotency tests in `backend/tests/test_review_rules_api.py`
- [ ] T045 [P] [US3] Write and run failing template search/suggestion, real rule count, candidate editing, publish, and reusable configuration UI tests in `frontend/src/views/review/ReviewRulesView.spec.ts` and `frontend/src/views/review/ReviewTemplatesView.spec.ts`

### Implementation for User Story 3

- [ ] T046 [US3] Implement source registration, scoped candidate extraction, source evidence validation, candidate decisions, immutable rule/template publication, and pinned configuration services in `backend/services/review_rules.py` and `backend/services/review_store.py`, then make T043 green
- [ ] T047 [US3] Implement source/extraction job/candidate/template/rule/configuration endpoints in `backend/api/routes/review_rules.py`, wire extraction handlers in `backend/services/review_jobs.py`, register routes in `backend/api/main.py`, and make T044 green
- [ ] T048 [US3] Extend `frontend/src/api/review.ts`, `frontend/src/stores/review.ts`, and `frontend/src/types/index.ts` for sources, candidates, immutable versions, suggestions, profiles, sensitivity, marking mode, and invalid pinned rules
- [ ] T049 [US3] Adapt `frontend/src/views/review/ReviewTemplatesView.vue`, `frontend/src/views/review/ReviewRulesView.vue`, `frontend/src/components/review/TemplateCard.vue`, and `frontend/src/components/review/ClauseCard.vue` to real search, suggestions, candidate confirmation/publication, and reusable configuration behavior, then make T045 green
- [ ] T050 [US3] Write and run the failing-then-green source-to-publication integration test proving unpublished candidates never analyze and historical snapshots remain unchanged in `backend/tests/test_rule_publication_workflow.py`

**Checkpoint**: User Story 3 provides human-controlled, versioned review knowledge with no live drift into running jobs.

---

## Phase 6: User Story 4 - 围绕审查结果连续问答 (Priority: P2)

**Goal**: Provide review-scoped multi-turn QA using the original workbench event structure while enforcing frozen task/finding scope, real history, validated citations, stop isolation, and no Web fallback.

**Independent Test**: Ask why a selected finding exists, follow up without repeating context, verify all factual claims cite frozen evidence, stop one request without affecting another, and receive evidence-insufficient behavior outside scope.

### Tests for User Story 4 (RED first)

- [ ] T051 [P] [US4] Write and run failing scoped retrieval, history use, citation validation, evidence-insufficient, incomplete message, and no-Web-fallback service tests in `backend/tests/test_review_qa.py`
- [ ] T052 [P] [US4] Write and run failing conversation, stream framing, request-scoped stop, disconnect recovery, and generic chat compatibility tests in `backend/tests/test_review_chat_api.py`
- [ ] T053 [P] [US4] Write and run failing review assistant multi-turn, citation navigation, stop, retry, clear, error, and incomplete-answer tests in `frontend/src/components/review/ReviewAssistant.spec.ts`

### Implementation for User Story 4

- [ ] T054 [US4] Implement ReviewConversation/message persistence and frozen snapshot/finding QA orchestration using shared search and LLM transport in `backend/services/review_qa.py` and `backend/services/review_store.py`, then make T051 green
- [ ] T055 [US4] Implement review conversation GET/DELETE, compatible SSE stream, and request-scoped stop endpoints in `backend/api/routes/review_chat.py`, register routes in `backend/api/main.py`, and make T052 green
- [ ] T056 [US4] Extend shared SSE types and review conversation client methods in `frontend/src/api/sse.ts`, `frontend/src/api/review.ts`, and `frontend/src/types/index.ts`
- [ ] T057 [US4] Adapt `frontend/src/components/review/ReviewAssistant.vue` and `frontend/src/views/review/ReviewConsoleView.vue` for real scoped conversations, citations, navigation, stop/retry/clear, and incomplete/error separation, then make T053 green
- [ ] T058 [US4] Write and run a failing-then-green end-to-end review QA test covering multi-turn history, selected finding scope, citation highlighting, evidence insufficiency, stop isolation, and reload recovery in `frontend/tests/e2e/review-qa.spec.ts`

**Checkpoint**: User Story 4 is isolated from generic knowledge search while preserving the established workbench interaction contract.

---

## Phase 7: User Story 5 - 处理并导出审查结论 (Priority: P3)

**Goal**: Persist finding/overall human decisions independently of machine results, append audit events, and generate revision-frozen DOCX reports matching the UI.

**Independent Test**: Save finding dispositions/comments and an overall approve/reject decision, reload them, export DOCX, and verify document/rule versions, findings, evidence, decisions, and generation revision match the page.

### Tests for User Story 5 (RED first)

- [ ] T059 [P] [US5] Write and run failing optimistic decision revision, immutable finding, and append-only audit tests in `backend/tests/test_review_decisions.py`
- [ ] T060 [P] [US5] Write and run failing idempotent export job, frozen revision, DOCX content, checksum, atomic publication, and download contract tests in `backend/tests/test_review_export.py`
- [ ] T061 [P] [US5] Write and run failing risk disposition, overall decision, audit refresh, export progress/download, and page revision consistency UI tests in `frontend/src/views/review/ReviewConsoleView.spec.ts`

### Implementation for User Story 5

- [ ] T062 [US5] Implement separate HumanDecision persistence, optimistic revisions, decision endpoints, and append-only AuditEvent queries in `backend/services/review_service.py`, `backend/services/review_store.py`, and `backend/api/routes/reviews.py`, then make T059 green
- [ ] T063 [US5] Implement persistent revision-frozen DOCX export handlers with `python-docx`, atomic artifact publication, checksum, status, and download in `backend/services/review_service.py`, `backend/services/review_jobs.py`, and `backend/api/routes/reviews.py`, then make T060 green
- [ ] T064 [US5] Extend `frontend/src/api/review.ts`, `frontend/src/stores/review.ts`, `frontend/src/components/review/RiskCard.vue`, and `frontend/src/views/review/ReviewConsoleView.vue` for decisions, audit, export progress, and download, then make T061 green
- [ ] T065 [US5] Write and run the failing-then-green integration test asserting API reload and exported DOCX use identical result/decision revisions in `backend/tests/test_review_export_consistency.py`

**Checkpoint**: User Story 5 completes the review decision and delivery loop without modifying machine findings.

---

## Phase 8: Polish and Cross-Cutting Validation

**Purpose**: Validate compatibility, security, migration, performance, and all measurable outcomes across stories.

- [ ] T066 [P] Add and run legacy docs/chat regression tests covering old document artifacts, unscoped generic search, original SSE consumers, and existing frontend views in `backend/tests/test_legacy_compatibility.py` and `frontend/src/views/existing-views.spec.ts`
- [ ] T067 [P] Add and run uploaded/model HTML XSS regression tests across ChatMessage, DocPreview, DOCX viewer, and ReviewAssistant in `frontend/src/utils/safeMarkdown.spec.ts`
- [ ] T068 Add and run ES legacy mapping/reindex and degraded-anchor migration tests, then implement the migration/reparse utility in `scripts/reindex_document_versions.py` and `backend/tests/test_document_reindex.py`
- [ ] T069 Run the full backend test suite using `.\venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"` and resolve every regression through a failing test first
- [ ] T070 Run frontend `npm ci`, `npm exec vue-tsc -- --noEmit`, `npm test`, and `npm run build`, resolving every regression through a failing test first
- [ ] T071 Run Playwright review suites across desktop/mobile and multiple PDF zoom/DPR cases, capture evidence, and resolve every failure through a failing test first in `frontend/tests/e2e/`
- [ ] T072 Execute the workflow and release gates in `specs/001-connect-review-backend/quickstart.md`, including restart recovery, idempotency conflict, partial retry, citation scope, mismatch refusal, and DOCX consistency
- [ ] T073 Reconcile every FR/SC against tests and implementation, document any environment-dependent quality pilot results in `specs/001-connect-review-backend/validation.md`, and leave no unsupported completion claim

---

## Dependencies and Execution Order

### Phase Dependencies

- Phase 1 Setup has no feature dependency and must record baseline before production code.
- Phase 2 Foundational depends on Phase 1 and blocks all user stories.
- US1 depends on Phase 2.
- US2 depends on versioned/locator-ready documents from Phase 2 and findings from US1.
- US3 depends on Phase 2; it can be developed after the US1 contract is stable, but published rules are required for final US1 semantic acceptance.
- US4 depends on AnalysisSnapshot/Finding from US1 and published source/rule references from US3.
- US5 depends on terminal AnalysisJob/Finding from US1.
- Phase 8 depends on all five stories.

### TDD Pairing

- T005 -> T006; T007 -> T008; T009 -> T010; T011 -> T012; T013 -> T014; T015 -> T016; T017 -> T018; T019 -> T020.
- US1 RED T021-T024 precede GREEN T025-T028; integration T032 must fail before any integration-only correction.
- US2 RED T033-T035 precede GREEN T036-T040; Playwright T042 must demonstrate the missing/wrong overlay before correction.
- US3 RED T043-T045 precede GREEN T046-T049; integration T050 validates lifecycle invariants.
- US4 RED T051-T053 precede GREEN T054-T057; end-to-end T058 validates stream/stop/recovery.
- US5 RED T059-T061 precede GREEN T062-T064; integration T065 validates revision identity.

### Parallel Opportunities

- Only tasks explicitly marked `[P]` may be delegated in parallel, and never when they edit the same file or depend on an uncompleted RED/GREEN pair.
- Within a user story, independent backend service, API contract, and frontend behavior RED tests can be authored in parallel, but all must be observed failing for the intended reason.
- Implementation remains sequential where shared files (`review_store.py`, `review.ts`, `ReviewConsoleView.vue`, `main.py`) overlap.

## Implementation Strategy

1. Complete Setup and Foundational with compatibility tests first.
2. Deliver US1 real analysis vertical slice and validate it independently.
3. Add US2 precise evidence rendering before relying on review conclusions in the UI.
4. Add US3 controlled rule lifecycle and rerun US1 semantic analysis tests.
5. Add US4 scoped QA and US5 decisions/export.
6. Complete all cross-cutting gates. The clarified Spec declares all five stories part of MVP; no phase is optional for completion.

## Task Completion Rules

- Mark a task `[X]` only after its exact verification command passes.
- For every behavior change, retain evidence that its RED test failed for the expected missing behavior before implementation.
- Commit logical RED/GREEN groups on `new-agent`; never commit generated runtime data, secrets, `node_modules`, or worktree contents.
- Do not silently change the API contract. Any discovered contract defect must first update `contracts/review-api.openapi.yaml` and its contract test.
- Do not create duplicate document pipelines, LLM clients, SSE decoders, review stores, or review page/store trees.
