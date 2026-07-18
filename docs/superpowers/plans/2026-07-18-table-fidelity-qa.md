# 表格高保真解析与问答原表呈现 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从解析源头把表格统一为高保真 HTML+Markdown 原子 block，问答时以「叙述 + 服务端拼接原文表」呈现，使「待遇标准」类问题返回可渲染的原表而非模型改写列表。

**Architecture:** 新建 `table_utils.py` 负责 HTML/MD 与二维网格的同源生成与伪表升格；`document_pipeline` 在 IR 归一化前接入；`search` 透出 `block_type`/`section_path`；`qa_service` 抽表并在流式叙述结束后拼接固定 Markdown 模板。前端仅补表格 CSS。不考虑存量索引兼容，验收依赖 reparse/重传。

**Tech Stack:** Python 3.12、标准库 html/html.parser/re、现有 FastAPI SSE、Elasticsearch、Vue3 + marked GFM。

**Spec:** `docs/superpowers/specs/2026-07-18-table-fidelity-qa-design.md`

## Global Constraints

- 表 block 定稿必须同时具备 `type=table`、`html`、`markdown`、`text`（text 与 markdown 一致）
- `html` 与 `markdown` 只能由同一 2D 网格生成
- 合并单元格一期拆平为重复文本，不做 colspan/rowspan
- 不考虑存量数据兼容；验收前对目标样例 reparse/重传
- 答后最多附 2 张表；单元格数字不得改写（如「27个月本人工资」）
- 不新增 SSE 事件类型；不引入新第三方 HTML 解析依赖

## File Map

| 文件 | 职责 |
|------|------|
| `table_utils.py`（新建） | 网格转换、伪表检测、promote_raw_blocks、extract_tables_from_hits |
| `tests/test_table_utils.py`（新建） | 表工具单元测试 |
| `document_pipeline.py` | raw→IR 前升格；合并后重算双形态；chunk content 用 markdown |
| `config.py` | ANSWER_ATTACH_TABLES / ANSWER_MAX_TABLES / TABLE_CONTEXT_MAX_CHARS |
| `search.py` | search_local 透出字段；format_results_for_llm 表友好截断 |
| `qa_service.py` | 提示词增量、抽表、答后拼接 |
| `frontend/src/styles/main.css` | 助手消息表格样式 |
| `scripts/verify_table_qa.py`（新建） | e2e：stream「待遇标准」断言含原文表 |

---

### Task 1: table_utils — 网格与双形态生成

**Files:**
- Create: `table_utils.py`
- Create: `tests/test_table_utils.py`

**Interfaces:**
- Produces: `html_to_grid`, `markdown_to_grid`, `grid_to_html`, `grid_to_markdown`, `normalize_table_fields`, `looks_like_html_table`, `looks_like_markdown_table`

- [ ] **Step 1: 写失败单测** `tests/test_table_utils.py`（SAMPLE_HTML 含嵌套 p 与 27个月本人工资；断言 strip p、roundtrip、分隔行）
- [ ] **Step 2: pytest 确认 FAIL（无模块）**
- [ ] **Step 3: 实现 table_utils.py（标准库 HTMLParser；grid 同源生成 html+md；text=markdown）**
- [ ] **Step 4: pytest PASS**
- [ ] **Step 5: commit** `feat: add table_utils for high-fidelity HTML/Markdown tables`

### Task 2: promote_raw_blocks + extract_tables_from_hits

**Files:** Modify `table_utils.py`, `tests/test_table_utils.py`

- [ ] **Step 1: 单测** promote 伪段落 HTML→table；extract 优先 block_type=table
- [ ] **Step 2: pytest FAIL**
- [ ] **Step 3: 实现 promote_raw_blocks / is_valid_table_grid / extract_tables_from_hits（max_tables=2，≥2x2，按 markdown 去重）**
- [ ] **Step 4: pytest PASS**
- [ ] **Step 5: commit** `feat: promote pseudo-table blocks and extract tables from hits`

### Task 3: 接入 document_pipeline

**Files:** Modify `document_pipeline.py`；Create `tests/test_pipeline_table_promote.py`

- [ ] **Step 1: 单测** promote + `_normalize_ir` + `structure_aware_chunk` → type=table，content 含 GFM/27个月
- [ ] **Step 2: pytest 可能 FAIL**
- [ ] **Step 3: `_run_pipeline` 中 `_normalize_ir` 前 `promote_raw_blocks`；table 分支 `normalize_table_fields`；合并后重算；chunk body 优先 markdown（HTML 则再 normalize）**
- [ ] **Step 4: pytest PASS**
- [ ] **Step 5: commit** `feat: normalize tables at IR build for atomic table chunks`

### Task 4: config + search

**Files:** `config.py`, `search.py`, `tests/test_format_results_table.py`

- [ ] **Step 1: 配置** ANSWER_ATTACH_TABLES=true, ANSWER_MAX_TABLES=2, TABLE_CONTEXT_MAX_CHARS=2000
- [ ] **Step 2: search_local 返回 block_type、section_path**
- [ ] **Step 3: format_results_for_llm 表块用 TABLE_CONTEXT_MAX_CHARS；有表时提示勿逐格复述**
- [ ] **Step 4: 单测 format 保留 27个月与表格提示**
- [ ] **Step 5: commit** `feat: expose table fields in search and table-aware LLM context`

### Task 5: qa_service 答后拼接

**Files:** `qa_service.py`（必要时 `parallel_qa.py`）, `tests/test_attach_tables.py`

- [ ] **Step 1: build_table_appendix 纯函数 + 单测**
- [ ] **Step 2: SYSTEM_PROMPT 增加「有表时叙述+系统附表、勿逐格复述」**
- [ ] **Step 3: stream_answer 本地分支 hybrid_search 后 extract_tables_from_hits；done 前 yield appendix token**
- [ ] **Step 4: parallel 分支同样附表；pytest PASS**
- [ ] **Step 5: commit** `feat: append source markdown tables after QA narration`

### Task 6: 前端表格 CSS

**Files:** `frontend/src/styles/main.css`

- [ ] **Step 1: .msg.assistant table/th/td 边框、padding、横向滚动、斑马纹**
- [ ] **Step 2: 确认 ChatMessage class=role**
- [ ] **Step 3: commit** `style: render assistant markdown tables with borders`

### Task 7: reparse + e2e

**Files:** `scripts/verify_table_qa.py`

- [ ] **Step 1: 脚本 POST /api/chat/stream message=待遇标准；断言 原文表格、伤残等级、27个月、管道符**
- [ ] **Step 2: 目标文档 reparse；检查 ir.json type=table**
- [ ] **Step 3: 重启 API 后跑 verify_table_qa.py 期望 OK**
- [ ] **Step 4: commit 脚本**

## Spec Coverage

| Spec | Task |
|------|------|
| 同源 HTML/MD | 1 |
| 伪表升格 | 2 |
| IR/chunk 表原子 | 3 |
| 无存量兼容 | 3/7 reparse |
| search 字段 + 上下文 | 4 |
| 答后原表 + prompt | 5 |
| 前端样式 | 6 |
| e2e 待遇标准 | 7 |

## Execution

Plan path: `docs/superpowers/plans/2026-07-18-table-fidelity-qa.md`

1. Subagent-Driven（推荐）
2. Inline Execution

Which approach?
