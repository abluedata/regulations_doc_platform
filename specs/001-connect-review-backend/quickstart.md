# Quickstart: 智能审查真实后端联通

This document describes the implementation and validation environment for the design. It does not imply that the planned review APIs already exist.

## 1. Prerequisites

Validated local baseline on 2026-07-26:

| Runtime/tool | Version |
|--------------|---------|
| Windows | 11 Pro 64-bit, 10.0.22631 |
| Python | 3.12.4 (repository supports 3.10-3.13) |
| Node.js | 24.13.0 |
| npm | 11.8.0 |
| Elasticsearch client | 8.19.3; server must remain compatible with ES 8.x |
| MinerU | 3.4.4 |

The Python dependency source is repository-root `requirements.txt`. The frontend dependency source is `frontend/package-lock.json`; use `npm ci` for validation.

Planned frontend additions:

```text
runtime: pdfjs-dist@5, dompurify@3
dev:     @playwright/test@1
```

Do not add a Python DB or export package: use standard-library `sqlite3` and installed `python-docx`.

## 2. Install

From repository root:

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt

Set-Location frontend
npm ci
Set-Location ..
```

When the planned frontend dependencies are first implemented, add and pin them through npm, commit the updated package manifest and lockfile, then repeat `npm ci` from a clean `node_modules` state.

## 3. Configuration and Data Paths

Keep existing `.env` settings for Elasticsearch, MinerU and LLM providers. Review code must reuse `backend/core/config.py` and the shared LLM client; it must not introduce a second provider configuration namespace.

Planned persistent paths:

```text
.data/
├── uploads/{document_id}/
│   ├── original.ext
│   ├── meta.json
│   └── versions/{version_id}/
│       ├── ir.json
│       ├── preview.md
│       └── manifest.json
└── reviews/
    ├── reviews.db
    └── exports/
```

The app initializes SQLite with WAL, foreign keys and schema migrations. Do not manually create/edit `reviews.db`. Existing document/chat JSON remains in its current location.

## 4. Start Services

Terminal 1, Elasticsearch:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_es.ps1
```

Terminal 2, MinerU adapter service:

```powershell
.\venv\Scripts\python.exe -m mineru_service.server
```

Terminal 3, backend. The documented repository command uses backend as cwd and port 8002:

```powershell
Set-Location backend
..\venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8002
```

MVP must use one Uvicorn worker. Do not add `--workers 2` or greater; the in-process persistent runner is designed for one application process.

Terminal 4, frontend:

```powershell
Set-Location frontend
npm run dev
```

## 5. Expected End-to-End Workflow

1. Create a ReviewBatch with name, declared type and OCR preference.
2. Upload PDF/DOCX through existing `/api/docs/upload`, poll its existing status and obtain `current_version_id`.
3. Add the explicit document version to the batch; do not pass only a mutable document ID.
4. List published TemplateVersions/RuleVersions, use a backend suggestion only as guidance, and explicitly select versions.
5. Start analysis with `Idempotency-Key`. Keep the returned job ID, load the initial REST snapshot, then subscribe to `/analysis-jobs/{job_id}/stream`.
6. Apply committed `fragment` events by stable Finding ID; after refresh/reconnect, use `Last-Event-ID` and reconcile through GET job/findings.
7. Select a risk and render the exact version through shared DocumentViewer. Never use quote-first search as a fallback.
8. Ask questions through review conversation SSE. Verify citations point only to the frozen snapshot.
9. Save finding/overall decisions using expected revisions, then request a DOCX export and poll the artifact.

## 6. Verification Commands

Backend tests, from repository root:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"
```

Frontend static/type/unit/build checks, from `frontend`:

```powershell
npm ci
npm exec vue-tsc -- --noEmit
npm test
npm run build
```

Browser evidence validation after Playwright is installed:

```powershell
npm exec playwright test
```

Focused fragment-stream validation after implementation:

```powershell
.\venv\Scripts\python.exe -m pytest backend\tests\test_review_fragment_stream.py backend\tests\test_review_api.py -q

Set-Location frontend
npm test -- --run src\api\review\review.spec.ts src\stores\review.spec.ts
npm exec playwright test tests\e2e\review-fragment-stream.spec.ts
Set-Location ..
```

The focused suites must prove that a committed fragment arrives before the terminal event, zero-finding fragments advance progress, reconnect does not duplicate Finding rows/cards, and each visible Finding is already available through REST.

Contract and design checks, from repository root:

```powershell
rg -n "NEEDS CLARIFICATION|\[FEATURE\]|\[DATE\]|\[###" specs\001-connect-review-backend
git diff --check
```

If a Python YAML/OpenAPI parser is already present in the environment, parse `contracts/review-api.openapi.yaml`; do not add a runtime dependency solely for document validation.

## 7. Required Test Fixtures

Keep deterministic fixtures small and legally safe:

- PDF with one repeated sentence on two pages and known normalized rectangles.
- Rotated PDF page and zoom/DPR browser cases.
- DOCX with repeated paragraph text, nested runs, Unicode text and tables containing repeated cell text.
- Source document with amount threshold and notification-period candidates.
- Multi-document batch where one analysis handler intentionally fails and is retryable.
- Malicious Markdown/HTML payload covering script, event attributes, unsafe links and malformed tables.

The fixtures must carry expected document version, quote hash, locator and finding IDs so browser/UI assertions prove the correct instance was highlighted.

## 8. Release Gates

- Existing docs upload/list/preview/reparse tests pass with old callers.
- Existing generic chat retains `meta/status/token/done/error`, stop and fallback behavior.
- Same idempotency key/request returns one analysis; changed payload returns 409.
- Restart recovers expired running jobs without duplicate findings.
- A delayed multi-fragment analysis emits its first committed `fragment` before `complete`.
- Every analysis business event has a monotonic SSE ID; Last-Event-ID replays only missing events.
- Zero-finding fragments advance committed progress; retries/replays do not change final finding count.
- SSE disconnect leaves the job running, and REST reconciliation restores the same result revision.
- Every deterministic finding has a valid exact/degraded EvidenceAnchor; invalid anchors become manual review.
- PDF and DOCX repeated-text fixtures locate the annotated instance; mismatch never highlights another instance.
- Rule candidates never enter analysis before confirm and publish.
- Page, reload and DOCX export agree on result/decision revisions.
- No unsanitized uploaded/model HTML reaches `v-html`.

## 9. Troubleshooting Boundaries

- **Legacy document has no precise locator**: reparse to create a new version; never retrofit a historical finding to mutable current content.
- **Elasticsearch record lacks version metadata**: generic search may continue, but review scope must reject/degrade it until reindex/reparse.
- **Job is running after a crash**: on startup the runner waits for/recognizes expired lease, requeues and increments attempt; do not edit the DB.
- **SSE disconnects**: keep the AnalysisJob running, reconnect with `Last-Event-ID`, and GET job/findings for authoritative reconciliation; do not infer failure from the connection alone.
- **Analysis event sequence has a gap**: stop applying incremental fragments, GET the authoritative result, then resume from the server-provided cursor; never guess the missing Finding payload.
- **Multiple backend workers requested**: stop and migrate runner/database locking to a supported external architecture before enabling them.

