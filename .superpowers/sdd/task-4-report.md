# Task 4 Report: config + search table-aware context

**Date:** 2026-07-18  
**Plan:** docs/superpowers/plans/2026-07-18-table-fidelity-qa.md  
**Spec:** docs/superpowers/specs/2026-07-18-table-fidelity-qa-design.md  
**Task:** Task 4 — config + search (expose table fields + table-aware LLM context) for D:\workspace\agent\regulations_doc_platform

## Execution Summary

### Step 1: Add config flags
- Read `config.py`. Confirmed `_env_bool` did not exist yet.
- Added `_env_bool` helper (after `_env`).
- Added three new constants near other search params (after BM25_TITLE_BOOST) under new section header:
  ```python
  # ─── 表格问答参数 ────────────────────────────────────────────
  ANSWER_ATTACH_TABLES = _env_bool("ANSWER_ATTACH_TABLES", True)
  ANSWER_MAX_TABLES = int(_env("ANSWER_MAX_TABLES", "2"))
  TABLE_CONTEXT_MAX_CHARS = int(_env("TABLE_CONTEXT_MAX_CHARS", "2000"))
  ```
- Reuses the required `_env_bool` pattern exactly as specified (falls back to `_env`).

### Step 2: Modify search.py
- Added import:
  ```python
  from config import ( ... TABLE_CONTEXT_MAX_CHARS )
  ```
- Added imports from table_utils:
  ```python
  from table_utils import (
      looks_like_html_table,
      looks_like_markdown_table,
      normalize_table_fields,
  )
  ```
- In `search_local`, inside the `results.append({...})` dict:
  ```python
  "block_type": src.get("block_type"),
  "section_path": src.get("section_path") or "",
  ```
- Added helper:
  ```python
  def _is_table_hit(r: dict) -> bool:
      if (r.get("block_type") or "").lower() == "table":
          return True
      content = r.get("content", "") or ""
      return looks_like_html_table(content) or looks_like_markdown_table(content)
  ```
- Rewrote `format_results_for_llm` table-aware logic:
  - Tracks `has_table`.
  - For table hits: uses `TABLE_CONTEXT_MAX_CHARS` limit (default 2000).
  - If content looks like HTML table, calls `normalize_table_fields(html=content)` and reconstructs content preferring markdown while preserving any leading `[文档]` / `[章节]` header lines from the original content.
  - Non-table hits: keep 800-char limit.
  - Also renders `> 章节: {section_path}` line when present.
  - After building text, if `has_table`:
    ```python
    instr = "\n注意：系统将在答案后附加原文表格，请不要逐格复述表格内容，也不要编造表格行。"
    text = text + instr
    ```
  - Section path and filename headers are emitted for local results.

### Step 3: Create tests/test_format_results_table.py
- New unittest file with class `TestFormatResultsTableAware`.
- Three test methods:
  1. `test_format_results_for_llm_table_block_preserves_content_and_instruction`
     - Uses `block_type="table"` + markdown table containing `27个月本人工资`.
     - Asserts `"27个月本人工资" in ctx`.
     - Asserts instruction keywords: `("表格" in ctx) or ("原文" in ctx) or ("不要" in ctx)`.
  2. `test_format_results_for_llm_non_table_uses_800_limit`
     - Long non-table content; verifies truncation (no full 2000-char run remains).
  3. `test_format_results_for_llm_has_section_path_and_headers`
     - Verifies section_path and filename are present in context (adjusted final assertion to filename since `[文档]` header is injected by upstream pipeline, not here).
- File uses only stdlib `unittest` (consistent with sibling tests).

### Step 4: Verification
- Import smoke (exact command requested):
  ```powershell
  .\venv\Scripts\python.exe -c "from search import format_results_for_llm, search_local"; echo "IMPORT OK"
  ```
  → `IMPORT OK`
- Test execution (exact command requested):
  ```powershell
  .\venv\Scripts\python.exe -m unittest tests.test_format_results_table -v
  ```
  → `Ran 3 tests in 0.000s` → **OK** (all three pass; first test explicitly asserts 27个月 + instruction text).

### Step 5: Commit
```bash
git add config.py search.py tests/test_format_results_table.py
git commit -m "feat: expose table fields in search and table-aware LLM context"
```
- Resulting commit: `ef3ee19bd399e116d7dfc95233e3fe37f52a7b8a`

## Deliverables

| File | Change | Purpose |
|------|--------|---------|
| `D:\workspace\agent\regulations_doc_platform\config.py` | +16 lines | `_env_bool` + ANSWER_ATTACH_TABLES / ANSWER_MAX_TABLES / TABLE_CONTEXT_MAX_CHARS |
| `D:\workspace\agent\regulations_doc_platform\search.py` | +84 lines | block_type + section_path in search_local; table-aware format_results_for_llm + helper + imports |
| `D:\workspace\agent\regulations_doc_platform\tests\test_format_results_table.py` | +100 lines (new) | Dedicated unittest for table formatting behavior |
| `D:\workspace\agent\regulations_doc_platform\.superpowers\sdd\task-4-report.md` | new | This report |

## Key Implementation Details

**config.py (absolute path: D:\workspace\agent\regulations_doc_platform\config.py):**
```python
def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name, "true" if default else "false").lower()
    return v in ("1", "true", "yes", "on")

# ─── 表格问答参数 ────────────────────────────────────────────
ANSWER_ATTACH_TABLES = _env_bool("ANSWER_ATTACH_TABLES", True)
ANSWER_MAX_TABLES = int(_env("ANSWER_MAX_TABLES", "2"))
TABLE_CONTEXT_MAX_CHARS = int(_env("TABLE_CONTEXT_MAX_CHARS", "2000"))
```

**search.py excerpts:**
- search_local appends the two new fields directly from ES `_source`:
  ```python
  "block_type": src.get("block_type"),
  "section_path": src.get("section_path") or "",
  ```
- `_is_table_hit` and table branch in `format_results_for_llm` (lines ~320-370 range after edit):
  - Longer limit for tables.
  - HTML→markdown conversion via `normalize_table_fields`.
  - Header preservation logic for `[文档]` / `[章节]`.
  - Final appended instruction line when any table hit detected.

**tests/test_format_results_table.py (key assertions):**
```python
self.assertIn("27个月本人工资", ctx)
self.assertTrue(
    ("表格" in ctx) or ("原文" in ctx) or ("不要" in ctx),
    "Expected instruction text mentioning 表格/原文/不要 ..."
)
```

All changes strictly scoped to Task 4. No side effects on qa_service, parallel_qa, or document_pipeline (those are later tasks).

## Test Coverage (Required per plan)

- ✅ `format_results_for_llm` with `block_type=table` content containing markdown table with `27个月本人工资`.
- ✅ Assert `27个月` present in context.
- ✅ Assert presence of 表格/原文/不要 (instruction text) when tables are present.
- ✅ Non-table path still applies 800-char limit.
- ✅ `section_path` surfaces in formatted context.
- ✅ Exact commands executed:
  - Import verification
  - `.\venv\Scripts\python.exe -m unittest tests.test_format_results_table -v`
- ✅ `search` module still imports cleanly (`from search import format_results_for_llm, search_local`).

## Verification Commands & Results
```powershell
cd D:\workspace\agent\regulations_doc_platform
.\venv\Scripts\python.exe -c "from search import format_results_for_llm, search_local"; echo "IMPORT OK"
# → IMPORT OK

.\venv\Scripts\python.exe -m unittest tests.test_format_results_table -v
# → OK (3 tests)

git log --oneline -1
# → ef3ee19 feat: expose table fields in search and table-aware LLM context
```

## Files Changed (this task)

```
ef3ee19 feat: expose table fields in search and table-aware LLM context
 config.py                          |  16 +++++-
 search.py                          |  84 ++++++++++++++++++++++++++++---
 tests/test_format_results_table.py | 100 +++++++++++++++++++++++++++++++++++++
 3 files changed, 191 insertions(+), 9 deletions(-)
 create mode 100644 tests/test_format_results_table.py
```

## STATUS

**Completed successfully.**

- All config flags added (with reuse of `_env_bool` logic).
- `search_local` returns `block_type` + `section_path`.
- `format_results_for_llm` is table-aware (longer limit + HTML→MD conversion + instruction).
- New dedicated test file created and passes.
- Exact import check passed.
- Exact unittest command passed.
- Exact `git add` + commit performed with verbatim message.

## Commits

- `ef3ee19bd399e116d7dfc95233e3fe37f52a7b8a` — feat: expose table fields in search and table-aware LLM context

## Test Summary

```
Ran 3 tests in 0.000s
OK
```

Breakdown:
- `test_format_results_for_llm_table_block_preserves_content_and_instruction`: asserts 27个月 + instruction keywords (表格/原文/不要).
- `test_format_results_for_llm_non_table_uses_800_limit`: confirms non-table truncation.
- `test_format_results_for_llm_has_section_path_and_headers`: section_path and source filename visible.

All green on required venv python.

## Concerns

- The instruction text added is Chinese-only (matching the exact requirement phrasing "表格/原文/不要"). Future localization would require updates in one place.
- `[文档]` / `[章节]` header preservation in format_results_for_llm only applies when an embedded HTML table is detected inside the `content` string; pure markdown tables from upstream already carry the headers (as produced by `structure_aware_chunk`).
- `section_path` in search results is now surfaced in the LLM context for tables; this is new but non-breaking (existing callers ignore extra keys).
- No change to Tavily/web path or non-local results.
- Task 4 does not touch answer assembly / appendix splicing (Task 5 scope). The instruction line is only a hint inside the retrieval context passed to the LLM.
- No new dependencies; relies on already-implemented `table_utils` functions.
- Re-parse still required for full end-to-end table fidelity (consistent with prior task notes and spec "存量数据策略").

---

**End of Task 4 Report**
