# AI Review Persistence Design

**Date:** 2026-08-16
**Status:** Approved

## Goal

Make SQLite the single source of truth for review jobs, findings, decisions, audit events, document-scoped conversations, messages, and document-grounded recommended questions. Keep large document artifacts on disk.

## Scope Decisions

- Deployment is single-machine and single-user.
- Use SQLite for business records and the filesystem for original files, parsed artifacts, page images, and exported reports.
- Do not import existing `.data/reviews` JSON records.
- Deleting a document cascades through all review and conversation records.
- One conversation exists per analysis job and document version.
- Generate three to five recommended questions from the actual document and its review findings, persist them, and use deterministic templates when model generation fails.

## Architecture

Store `.data/platform.db` with foreign keys, WAL mode, and a busy timeout enabled. All business writes pass through SQLAlchemy repositories and short transactions. LLM calls, parsing, and file IO happen outside database transactions.

SQLite stores relationships, lifecycle states, results, provenance, and audit data. File paths in SQLite point only to completed artifacts. Files are written to temporary paths and atomically replaced before their database references are committed.

The frontend keeps only transient rendering state and in-progress stream tokens. It reloads durable conversation state from the server and no longer uses `localStorage` for messages or conversation identifiers.

## Data Model

The initial schema contains:

- `documents` and `document_versions` for document identity, hashes, parsing status, and artifact paths.
- `review_batches` and `batch_documents` for review inputs.
- `review_templates`, `review_rules`, and `review_configurations` for versioned review setup.
- `analysis_jobs` and `job_documents` for job state, immutable execution snapshots, engine provenance, and document scope.
- `findings` and `finding_decisions` for evidence-grounded review output and user disposition.
- `conversations` with a unique `(job_id, document_version_id)` constraint.
- `conversation_messages` for ordered user and assistant messages, request idempotency, citations, and terminal status.
- `recommended_questions` for question text, rationale, evidence references, rank, document/result version, model, prompt hash, and lifecycle status.
- `analysis_events` for state changes and audit records.
- `exports` for immutable report artifacts.
- `cleanup_queue` for retryable filesystem deletion.

Foreign keys cascade from documents through job-document membership, findings, conversations, messages, questions, and exports. Stable business keys prevent duplicate findings and messages during retries.

## Review Lifecycle

Creating a review job atomically saves the job, document membership, and configuration snapshot. The worker commits phase changes and findings in bounded transactions. A restarted service changes recoverable `parsing` or `running` jobs to `queued`; processing remains idempotent.

Every finding records its rule version, model version, prompt hash, evidence locator, explanation, and suggested fix. Decisions and exports remain linked to the exact result revision that produced them.

## Conversations

Opening the assistant resolves or creates the conversation for a job and document version, then returns its durable messages and active recommended questions. A submitted question creates the user message and a `streaming` assistant message before SSE begins. Completion updates the assistant row to `completed`; cancellation and failure update it to their corresponding terminal states. Startup marks abandoned `streaming` rows as `interrupted`.

`request_id` and role constraints make retries idempotent. The client renders incoming tokens in memory, but after refresh or reconnect it reloads authoritative messages from the server.

## Recommended Questions

Generation runs after a job finishes for each successfully reviewed document. Inputs are restricted to the current document title, section summaries, high-value chunks, findings, evidence, suggestions, and prior questions. The model returns structured JSON containing `question`, `rationale`, `source_refs`, and `rank`.

The service rejects references outside the current document and duplicate or empty questions. If fewer than three valid questions remain, deterministic templates fill the set using the document's finding categories and section titles. Each saved row records document version, result revision, generator/model version, and prompt hash. A changed parse version or result revision supersedes the previous set and triggers regeneration.

## API Contract

```text
GET    /api/review/jobs/{job_id}/documents/{document_version_id}/conversation
POST   /api/review/conversations/{conversation_id}/messages/stream
GET    /api/review/conversations/{conversation_id}/messages
POST   /api/review/conversations/{conversation_id}/recommended-questions/regenerate
DELETE /api/review/conversations/{conversation_id}/messages
DELETE /api/documents/{document_id}
```

The conversation endpoint returns the conversation, messages, and active recommended questions. SSE `meta` includes `conversation_id`, both message ids, and `request_id`. Exactly one of `done`, `error`, or `cancelled` is emitted, and its state matches the database row.

## Deletion And Recovery

Document deletion first commits the database cascade and a cleanup-queue entry. Artifact removal then runs outside the transaction. Success removes the queue item; failure records attempts and the last sanitized error for startup/background retry.

SQLite uses online backup rather than copying a live database file. Existing JSON is neither imported nor read after cutover.

## Testing And Acceptance

- Restart restores jobs, findings, decisions, conversations, messages, and recommended questions.
- Every model-generated recommended question has a valid reference to the selected document; fallback questions derive from its findings or sections.
- Normal completion, disconnect, cancellation, duplicate request, and restart produce correct message states without duplicates.
- Job retry does not duplicate findings.
- Document deletion removes all related database rows and eventually removes all artifacts.
- New code does not read or write the review JSON store.
- Backend tests, frontend tests, and the review end-to-end flow pass.

## Self-Review

- Placeholder scan: no TBD, TODO, or deferred behavior remains.
- Consistency: storage ownership, cascade semantics, conversation scope, and recommendation invalidation agree throughout.
- Scope: this is one vertical persistence migration with backend and frontend workstreams sharing a fixed API contract.
- Ambiguity: old JSON is explicitly discarded, SQLite is authoritative, and frontend browser storage is non-authoritative.
