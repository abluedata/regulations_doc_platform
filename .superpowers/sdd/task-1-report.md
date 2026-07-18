# Task 1 Report: table_utils — 网格与双形态生成

**Date:** 2026-07-18  
**Plan:** docs/superpowers/plans/2026-07-18-table-fidelity-qa.md  
**Spec:** docs/superpowers/specs/2026-07-18-table-fidelity-qa-design.md  
**Task:** Task 1 — Create `table_utils.py` + unit tests for HTML/Markdown table grid conversion (high-fidelity dual form)

## Execution Summary

### Step 1: TDD — Write failing tests first
- Created `tests/test_table_utils.py` (22 test cases) covering:
  - `looks_like_html_table` / `looks_like_markdown_table`
  - `html_to_grid` (strip nested `<p>`, preserve "27个月本人工资", `<br>`→space, unescape, collapse ws)
  - `markdown_to_grid` (skip separator lines, pipe split)
  - `grid_to_html` (thead/th + tbody/td structure)
  - `grid_to_markdown` (header + `---` separator line + rows, `|` escaped as `\|`)
  - `normalize_table_fields` (prefer html, roundtrip, text==markdown, empty on fail)
- Explicit SAMPLE_HTML with nested `<p>` containing "27个月本人工资"
- Explicit test: `test_html_to_grid_strips_nested_p_and_preserves_text`
- Explicit test: `test_normalize_prefers_html_and_roundtrips_without_p`
- Explicit test: `test_grid_to_markdown_has_separator_with_dashes`
- Ran: `.\venv\Scripts\python.exe -m unittest tests.test_table_utils -v` → **ImportError: No module named 'table_utils'** (expected FAIL)

### Step 2: Implement table_utils.py (stdlib only)
- Used `html.parser.HTMLParser` subclass (`_TableHTMLParser`) for HTML→grid:
  - `handle_starttag`/`endtag` for tr/td/th/br
  - `handle_data` collects text only
  - `html.unescape` + collapse `\s+` → single space + strip
  - No third-party libs
- `markdown_to_grid`: filter `|...|` lines, skip `---` separators (flexible `---`/`:---:`), split on `|`
- Dual-form guarantee: `grid_to_html` + `grid_to_markdown` always emitted from **same** 2D grid
- `normalize_table_fields(*, html=None, markdown=None, text=None)`:
  - Prefers html → grid → html+md+text
  - Falls back markdown → grid
  - Falls back text (treated as md)
  - Returns `{"html":"","markdown":"","text":""}` on total failure
- `looks_like_*` heuristics for detection (table tag; ≥3 pipe-lines with sep)
- All cell text plain (no nested tags preserved)

### Step 3: Run tests (PASS)
```
Ran 22 tests in 0.001s
OK
```
All 22 tests passed, including the three required coverage items.

### Step 4: Commit
- `git add table_utils.py tests/test_table_utils.py`
- `git commit -m "feat: add table_utils for high-fidelity HTML/Markdown tables"`
- Hash: `eea4b8f`

## Deliverables

| File | Lines | Purpose |
|------|-------|---------|
| `table_utils.py` | ~230 | 7 public funcs + internal parser |
| `tests/test_table_utils.py` | ~226 | 22 unittest.TestCase tests |
| `.superpowers/sdd/task-1-report.md` | this file | Detailed report |

## Key Implementation Details

- **Dual form invariant**: `grid_to_html(grid)` and `grid_to_markdown(grid)` derive from identical grid → no drift.
- **HTML stripping**: `<p>27个月本人工资</p>` → cell `"27个月本人工资"` (verified).
- **No external deps**: pure stdlib (`html`, `html.parser`, `re`).
- **Markdown escaping**: `|` → `\|` in cells.
- **Separator**: always `| --- | --- | ... |` (no colons required by generator).
- **normalize strategy**: html first, then markdown, then text; always text = markdown.

## Test Coverage (Required)

1. ✅ SAMPLE_HTML with nested `<p>` → `html_to_grid` strips p, preserves `27个月本人工资` exactly.
2. ✅ `normalize_table_fields` roundtrip: output html has no `<p>`, markdown has pipes + `27个月`.
3. ✅ `grid_to_markdown` produces separator line containing `---`.

Additional guards:
- bad input → `[]` or `""`
- BR handling, entity unescape, whitespace collapse
- roundtrip idempotence
- prefer-html logic
- markdown separator variants (`---`, `:---:`)

## Files Changed (this task only)

```
A  table_utils.py
A  tests/test_table_utils.py
```

## Verification Commands

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_table_utils -v
# → OK (22 tests)
git log --oneline -1
# → eea4b8f feat: add table_utils for high-fidelity HTML/Markdown tables
```

## Concerns

- None for Task 1 scope. All requirements met, tests green, commit performed.
- Future tasks will integrate this module; current implementation is isolated and complete.

## Status

**DONE**

---

**Commit:** eea4b8f  
**One-line test summary:** 22/22 unittest tests passed (including SAMPLE_HTML nested-p strip, normalize roundtrip, and grid_to_markdown --- separator).  
**Concerns:** None
