# Task 7 Report (Partial): e2e verification script for table QA

**Date:** 2026-07-18  
**Plan:** docs/superpowers/plans/2026-07-18-table-fidelity-qa.md  
**Spec:** docs/superpowers/specs/2026-07-18-table-fidelity-qa-design.md  
**Task:** Task 7 (partial) — create `scripts/verify_table_qa.py` for D:\workspace\agent\regulations_doc_platform

## STATUS
**PARTIALLY COMPLETED** (script + commit only)

Per explicit request: "Implement Task 7 partially: create scripts/verify_table_qa.py for e2e verification."

Only Steps 1 and 4 of Task 7 executed:
- Script created and satisfies all listed requirements.
- Committed with exact message.

Steps 2 & 3 (target document reparse; restart API + run script) deliberately deferred.  
**Note:** reparse/restart will be done by controller if needed.

## Execution Summary

### Step 1: Create scripts/verify_table_qa.py
**File:** `D:\workspace\agent\regulations_doc_platform\scripts\verify_table_qa.py`

Implementation details:
- Uses `httpx` (consistent with existing verification scripts `verify_docx_flow.py`, `verify_mineru_upload.py`).
- `API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8002")`
- `POST /api/chat/stream` with exactly `{"message":"待遇标准","history":[]}`
- SSE parsing:
  - Tracks `event:` lines.
  - Accumulates `data:` lines.
  - On blank line, parses JSON (or falls back to `{"content": payload}`).
  - Concatenates `content` for `event == "token"` **or** any data object that has a `content` field.
  - Collects `event == "error"` payloads.
- Assertions (exact):
  1. `"原文表格" in full_text or "## 原文表格" in full_text`
  2. `"伤残等级" in full_text`
  3. `"27" in full_text and ("27个月" in full_text or "27 个月" in full_text)`
  4. `full_text.count("|") >= 6`
- Prints `PASS`/`FAIL` for each check + summary `OK` or `FAIL with details`.
- `sys.exit(0)` on success, `1` on failure.
- Timeout: 180s (connect 30s).
- UTF-8 handled by httpx.
- No new dependencies.

Script content (key excerpts):

```python
API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8002")
...
payload = {"message": "待遇标准", "history": []}
...
if event == "token" or (content is not None):
    if content:
        tokens.append(str(content))
if event == "error":
    errors.append(obj)
...
check_table_header = "原文表格" in full_text or "## 原文表格" in full_text
check_injury = "伤残等级" in full_text
check_27 = ("27" in full_text) and ("27个月" in full_text or "27 个月" in full_text)
check_pipes = full_text.count("|") >= 6
...
print("OK: table QA e2e verification passed") if all_ok else ...
return 0 if all_ok else 1
```

### Step 2-3: Deferred
- No document reparse performed.
- No API restart performed.
- `verify_table_qa.py` not executed against live server in this task.

### Step 4: Git commit
```bash
git add scripts/verify_table_qa.py
git commit -m "test: add table QA end-to-end verification script"
```
- Result: commit `47ec260`
- 1 file changed, 113 insertions(+)
- New file: `scripts/verify_table_qa.py`

## Commits
- `47ec260` test: add table QA end-to-end verification script

Preceding context (Task 6/5 chain):
- `83caa40` style: render assistant markdown tables with borders
- `69c0e57` feat: append source markdown tables after QA narration

## Files Created / Modified
- `D:\workspace\agent\regulations_doc_platform\scripts\verify_table_qa.py` (new, 113 lines)

## Concerns
- Script is ready but has not been run end-to-end yet (server must be up and target document must be parsed with current table pipeline for the assertions to pass).
- Full Task 7 acceptance requires reparse of the sample document (e.g. `验证样本-工伤保险待遇说明.docx`) + API restart + manual `python scripts/verify_table_qa.py` (or equivalent). **reparse/restart will be done by controller if needed.**
- Script relies on the same SSE shape (`event: token` + `{"content": "..."}`) and `## 原文表格` appendix produced by `qa_service.py` + `build_table_appendix`. Any upstream change to appendix format would require script update.
- Error events are collected but the script only fails if any were seen; transient model/stream issues could cause false FAIL.
- No handling for non-JSON data lines beyond the fallback `{"content": ...}` (matches other verify scripts).
- Windows CRLF line-ending warning on commit (cosmetic; same as prior scripts).
- Environment variable `API_BASE` allows overriding for CI/other hosts; default matches existing verification scripts.

## Verification Performed (pre-commit)
- File created with exact required behavior.
- Imports cleanly (no runtime execution against server in this partial task).
- Commit message exact match to spec.

## Next Steps (outside this partial task)
- Controller / follow-up: reparse sample doc, restart API on 8002, execute:
  ```powershell
  cd D:\workspace\agent\regulations_doc_platform
  .\venv\Scripts\python.exe scripts/verify_table_qa.py
  ```
- Expect `OK` once pipeline produces `## 原文表格` + GFM table containing `伤残等级` and `27个月`.

## Absolute Paths Referenced
- `D:\workspace\agent\regulations_doc_platform\scripts\verify_table_qa.py`
- `D:\workspace\agent\regulations_doc_platform\.superpowers\sdd\task-7-report.md`
- `D:\workspace\agent\regulations_doc_platform\docs\superpowers\plans\2026-07-18-table-fidelity-qa.md`

**Task 7 (partial) complete.** Script delivered and committed. Full e2e run pending controller-controlled reparse/restart.
