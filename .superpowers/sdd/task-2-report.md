# Task 2 Report: promote_raw_blocks + extract_tables_from_hits

**Date:** 2026-07-18  
**Plan:** docs/superpowers/plans/2026-07-18-table-fidelity-qa.md  
**Spec:** docs/superpowers/specs/2026-07-18-table-fidelity-qa-design.md  
**Task:** Task 2 — promote pseudo-table blocks and extract tables from hits (extend table_utils.py + tests)

## Execution Summary

### Step 1: Extend exports and add functions (after Task 1 base at eea4b8f)
- Updated `__all__` to export: `is_valid_table_grid`, `promote_raw_blocks`, `extract_tables_from_hits`
- Implemented:
  - `is_valid_table_grid(grid, min_rows=2, min_cols=2) -> bool`:
    - `len(grid) >= min_rows and min(len(r) for r in grid) >= min_cols`
    - Guards for None/empty/non-list.
  - `promote_raw_blocks(raw_blocks: list[dict]) -> list[dict]`:
    - Shallow copy every block.
    - Detects via `looks_like_*` on type=="table" OR text/html/markdown content.
    - Calls `normalize_table_fields` (prefers html→md→text).
    - If resulting markdown non-empty AND `is_valid_table_grid(markdown_to_grid(md))`: set type=table + html/markdown/text.
    - Never throws (bare except → leave original copy).
  - `extract_tables_from_hits(hits: list[dict], max_tables=2) -> list[dict]`:
    - Output shape: `{"markdown","filename","section_path","doc_id","chunk_id"}`
    - Prioritizes `block_type=="table"`.
    - Accepts content containing html/md tables.
    - Strips `^\[文档\]` / `^\[章节\]` header lines for detection/normalization (re.MULTILINE).
    - Dedups strictly by markdown string.
    - Stops at max_tables.
    - Only emits when `is_valid_table_grid(...)` (≥2×2).

### Step 2: Add 17 new unit tests (SAMPLE_HTML nested-p reused)
- `TestIsValidTableGrid`: 5 cases (valid 2x2, too-few-rows, too-few-cols, override, bad input).
- `TestPromoteRawBlocks`: 5 cases
  - `test_promote_nested_p_html_to_table` (explicitly uses SAMPLE_HTML)
  - markdown-in-text, already-table passthrough, bad-no-promote-no-throw, preserves other fields.
- `TestExtractTablesFromHits`: 7 cases
  - Prefer block_type=table
  - Extract from paragraph content with HTML table (SAMPLE_HTML)
  - Strip [文档]/[章节] headers
  - Dedup by markdown
  - max_tables limit
  - Only ≥2x2 valid grid accepted (fixed test case to truly 1-col)
  - Empty hits → []
- Total tests: 39 (22 prior + 17 new). All cover the required behaviors.

### Step 3: Run tests
```powershell
.\venv\Scripts\python.exe -m unittest tests.test_table_utils -v
```
**Result:** `Ran 39 tests in 0.002s` → **OK**

Explicit verification of SAMPLE_HTML nested p path:
- promote turns paragraph+SAMPLE_HTML → type=table with clean html (no <p>) + markdown containing "27个月".

All three new functions exported and present in `__all__`.

### Step 4: Commit
```bash
git add table_utils.py tests/test_table_utils.py
git commit -m "feat: promote pseudo-table blocks and extract tables from hits"
```
- Hash: 8a5cc84

## Deliverables

| File | Change | Purpose |
|------|--------|---------|
| `table_utils.py` | +~130 lines | Three new exported functions + helpers |
| `tests/test_table_utils.py` | +~110 lines | 17 new unittest cases (promote+extract) |
| `.superpowers/sdd/task-2-report.md` | new | This report |

## Key Implementation Details

- `promote_raw_blocks` always returns a list of dict copies (originals never mutated).
- Detection is conservative: any of type=table, or looks_like on any of text/html/markdown triggers normalize attempt.
- `extract_tables_from_hits` uses `re` for header stripping and always runs `markdown_to_grid + is_valid_table_grid` before acceptance.
- Dedup key = the final normalized markdown string (exact).
- Bad tables / 1-col / <2-row results are silently dropped (no exception).
- No third-party parsers; reuses existing `normalize_table_fields`/`markdown_to_grid`.

## Test Coverage (Required per plan)

- ✅ `promote_raw_blocks` on nested-p HTML (SAMPLE_HTML) → type=table, clean html/markdown, "27个月" preserved.
- ✅ `extract_tables_from_hits` prefers block_type=table; also pulls from content html/md.
- ✅ Header stripping for [文档]/[章节].
- ✅ Dedup + max_tables=2 (or user limit).
- ✅ Only ≥2×2 grids accepted (min row/col enforcement).
- ✅ 22 prior tests remain green (no regressions).

## Verification Commands
```powershell
.\venv\Scripts\python.exe -m unittest tests.test_table_utils -v
# → OK (39 tests)

git log --oneline -1
# → 8a5cc84 feat: promote pseudo-table blocks and extract tables from hits
```

## Files Changed (this task)

```
M  table_utils.py
M  tests/test_table_utils.py
```

## Concerns

- `extract_tables_from_hits` currently inspects only `content` + `block_type` + optional `markdown` on the hit. If future search hits add richer table fields (`html`, explicit `markdown`), the extractor will still work because it falls back to content heuristics and normalize. No breaking change.
- Header-stripping regex is narrow (only leading [文档]/[章节] lines) — matches current `_context_header` usage in pipeline. If header style evolves, update regex in one place.
- No mutation of input hits/raw_blocks (safe for callers).

## Status

**DONE**

---

**Commit:** 8a5cc84  
**One-line test summary:** 39/39 unittest tests passed (22 old + 17 new; promote on SAMPLE_HTML nested-p + extract priority/dedup/2x2 + headers).  
**Concerns:** None
