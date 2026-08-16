# AI Review Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace review JSON and browser-local history with SQLite-backed review state, durable document-scoped conversations, and persisted document-grounded recommended questions.

**Architecture:** SQLAlchemy repositories own business data in `.data/platform.db`; the filesystem stores large artifacts. Backend APIs expose durable conversations and recommendations, while the Vue client treats server state as authoritative.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, SQLite, pytest, Vue 3, Pinia, TypeScript, Vitest.

---

## Workstream Boundaries

- Backend worker owns `requirements.txt`, `backend/core/database.py`, `backend/models/`, `backend/repositories/`, `backend/migrations/`, `backend/services/review/`, `backend/api/routes/review.py`, `backend/api/review_schemas.py`, and backend tests.
- Frontend worker owns `frontend/src/api/review/review.ts`, `frontend/src/components/review/ReviewAssistant.vue`, related frontend types, and frontend tests.
- Workers must preserve existing uncommitted changes, must not commit, and must report every modified file.

### Task 1: SQLite Foundation And Review Repository

**Files:**
- Modify: `requirements.txt`
- Create: `backend/core/database.py`
- Create: `backend/models/review.py`
- Create: `backend/repositories/review_repository.py`
- Create: `backend/migrations/0002_review_sqlite.sql`
- Create: `backend/tests/test_review_repository.py`

- [ ] **Step 1: Write failing repository tests**

Cover schema creation, WAL/foreign-key configuration, unique job-document conversation creation, message request idempotency, persisted recommended questions, finding deduplication, and document cascade deletion using a temporary SQLite database.

- [ ] **Step 2: Verify tests fail**

Run: `pytest backend/tests/test_review_repository.py -q`

Expected: collection/import failure because the database and repository modules do not exist.

- [ ] **Step 3: Add dependencies and database bootstrap**

Add `SQLAlchemy>=2.0,<3.0` and `alembic>=1.13,<2.0`. Build an engine factory that enables `foreign_keys=ON`, `journal_mode=WAL`, and a 5-second busy timeout on every SQLite connection. Provide session and transactional context managers without holding transactions across callbacks.

- [ ] **Step 4: Implement schema and repository methods**

Implement the approved entities and constraints. Repository operations must include job CRUD/status recovery, finding upsert by stable key, decision/audit persistence, conversation get-or-create, ordered message CRUD, recommendation replacement/supersession, and document cascade deletion plus cleanup queue creation.

- [ ] **Step 5: Verify repository tests pass**

Run: `pytest backend/tests/test_review_repository.py -q`

Expected: all tests pass with no SQLite thread or foreign-key warnings.

### Task 2: Persisted Review Execution And API

**Files:**
- Modify: `backend/services/review/job_runner.py`
- Modify: `backend/services/review/assistant.py`
- Create: `backend/services/review/recommended_questions.py`
- Modify: `backend/api/routes/review.py`
- Modify: `backend/api/review_schemas.py`
- Modify: `backend/api/main.py`
- Modify: `backend/tests/test_review_api.py`
- Modify: `backend/tests/test_review_qa_stream.py`
- Create: `backend/tests/test_recommended_questions.py`
- Create: `backend/tests/test_review_recovery.py`

- [ ] **Step 1: Add failing API, generation, and recovery tests**

Test get-or-create conversation by job/document, ordered server messages, `meta` message ids, one terminal SSE event, duplicate `request_id`, clear messages, recommendation regeneration, invalid external evidence rejection, deterministic fallback, interrupted stream recovery, queued job recovery, and document cascade cleanup scheduling.

- [ ] **Step 2: Verify focused tests fail**

Run: `pytest backend/tests/test_review_api.py backend/tests/test_review_qa_stream.py backend/tests/test_recommended_questions.py backend/tests/test_review_recovery.py -q`

Expected: failures identify the missing repository-backed contracts.

- [ ] **Step 3: Replace review JSON access with repositories**

Keep existing external endpoint behavior where practical, but make SQLite authoritative for batches, configurations, jobs, findings, decisions, events, exports, and conversations. Do not add a dual-write or JSON fallback. Startup creates the schema and performs idempotent state recovery.

- [ ] **Step 4: Implement durable stream lifecycle**

Before streaming, persist the user row and `streaming` assistant row. Emit their ids in `meta`. Persist citations and final content on `done`; persist `failed`, `cancelled`, or `interrupted` terminal states on exceptional paths. Return an already completed response for a repeated request id.

- [ ] **Step 5: Implement grounded question generation**

Generate structured questions from the selected document and its findings. Validate every `source_ref` against that document. Deduplicate and rank results, fill to at least three with deterministic finding/section templates, and persist generator provenance. Supersede rows when result revision changes.

- [ ] **Step 6: Verify backend tests**

Run: `pytest backend/tests/test_review_repository.py backend/tests/test_review_api.py backend/tests/test_review_qa_stream.py backend/tests/test_review_qa_retrieval.py backend/tests/test_recommended_questions.py backend/tests/test_review_recovery.py -q`

Expected: all focused persistence and existing review QA tests pass.

### Task 3: Server-Authoritative Assistant UI

**Files:**
- Modify: `frontend/src/api/review/review.ts`
- Modify: `frontend/src/types/review.ts`
- Modify: `frontend/src/components/review/ReviewAssistant.vue`
- Modify: `frontend/src/components/review/ReviewAssistant.spec.ts`

- [ ] **Step 1: Replace local-storage tests with server restoration tests**

Assert that mounting fetches the job/document conversation, renders persisted messages and recommended questions, reuses the returned conversation id, handles empty/error states, and never reads or writes the `review-assistant:*` local-storage key.

- [ ] **Step 2: Verify component tests fail**

Run: `npm --prefix frontend run test -- --run src/components/review/ReviewAssistant.spec.ts`

Expected: failures show current hard-coded suggestions and local-storage restoration.

- [ ] **Step 3: Add typed API functions**

Add conversation snapshot, message, recommendation, and stream-meta types. Implement get conversation, list messages, regenerate recommendations, clear messages, and streaming against the approved endpoints.

- [ ] **Step 4: Make server data authoritative**

Remove `localStorage`, the module-level conversation map, and the three hard-coded suggestions. Reload when `analysisJobId` or selected document version changes. Render server recommendations, retain in-memory tokens while streaming, and reconcile from the server after terminal or connection failure.

- [ ] **Step 5: Verify frontend tests and typecheck**

Run: `npm --prefix frontend run test -- --run src/components/review/ReviewAssistant.spec.ts`

Run: `npm --prefix frontend run build`

Expected: component tests pass and the production build completes without TypeScript errors.

### Task 4: Integrated Verification

**Files:**
- Modify only files required to fix failures caused by this feature, within the workstream owner boundaries.

- [ ] **Step 1: Run backend review regression tests**

Run: `pytest backend/tests/test_review_api.py backend/tests/test_review_engine.py backend/tests/test_review_suggestions.py backend/tests/test_review_qa_stream.py backend/tests/test_review_qa_retrieval.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run frontend review regression tests**

Run: `npm --prefix frontend run test -- --run src/components/review/ReviewAssistant.spec.ts src/stores/review.spec.ts src/views/review/ReviewConsoleView.spec.ts`

Expected: all tests pass.

- [ ] **Step 3: Verify no authoritative JSON/local-storage paths remain**

Run: `rg -n "ReviewStore|review-assistant:|const suggestions =" backend frontend/src`

Expected: no production reference to the old review JSON store, assistant history key, or hard-coded question list.

- [ ] **Step 4: Review the combined diff**

Confirm document cascade behavior, no existing user changes were reverted, schema and API names match, and no generated database or artifact files are tracked.

## Plan Self-Review

- Spec coverage: database ownership, execution persistence, conversations, grounded questions, recovery, deletion, and frontend restoration each map to an explicit task.
- Placeholder scan: all implementation behavior and verification commands are explicit; no deferred requirements remain.
- Type consistency: API names and identifiers use `job_id`, `document_version_id`, `conversation_id`, `request_id`, and `recommended_questions` consistently.
