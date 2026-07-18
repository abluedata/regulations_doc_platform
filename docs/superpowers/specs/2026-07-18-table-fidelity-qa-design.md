# 表格高保真解析与问答原表呈现 — 设计规格

**日期：** 2026-07-18  
**状态：** 已评审（设计对话确认）  
**目标路径（实现阶段落盘）：** `docs/superpowers/specs/2026-07-18-table-fidelity-qa-design.md`  
**范围：** 解析源头表结构化（C）+ 问答「叙述 + 原表」拼接（B）  
**非目标：** 存量索引兼容、跨文档表合并 UI、Excel/CSV 导出、合并单元格 colspan/rowspan 保真（一期拆平不丢字）

---

## 1. 背景与问题

用户对「待遇标准」提问时期望看到**文档原表结构**（如伤残等级 / 一次性伤残补助金 / 伤残津贴），实际得到的是模型改写后的条目列表。

### 1.1 根因（样本 IR / ES 已核实）

| 环节 | 现象 |
|------|------|
| 解析 | MinerU 等将表落成 `type=paragraph`，HTML `<table>`（含嵌套 `<p>`）塞进 `text`，无独立 `markdown`/`html` |
| 分块 | `structure_aware_chunk` 仅对 `type==table` 整表打包；伪表段落走普通段落路径，`block_type` 入库为 `paragraph` |
| 问答 | 能检索到含表 chunk，但系统提示不要求表格输出，且**无服务端原表拼接**；模型改写为列表 |
| 前端 | `marked` + GFM **已能渲染** Markdown 表；瓶颈不在展示组件 |

### 1.2 目标

1. **从源头**将表格统一为**高保真 HTML + Markdown 双形态**结构化文本，表作为**原子 block**，消除表被当段落切碎导致的语义碎片化。  
2. 问答答案形态为：**简短叙述（流式）+ 文档原表（服务端拼接，模型不重写单元格）**。  
3. 主消费路径以 **GFM Markdown** 为准（聊天渲染）；规范 **HTML** 用于预览与同源保真。

### 1.3 成功标准

- 样例文档（如《验证样本-工伤保险待遇说明》）经上传/重解析后，IR 中待遇表为 `type=table`，且 `html`、`markdown` 均非空。  
- ES 对应 chunk：`block_type=table`，`content` 含 GFM 表（如 `| 伤残等级 |`）。  
- `POST /api/chat/stream` 问「待遇标准」：最终答案含叙述 + `## 原文表格` + GFM 表；一级伤残一次性补助金仍为 **27 个月本人工资**。  
- 前端聊天可见表格，而非仅列表复述。

### 1.4 存量数据策略

**不考虑存量索引兼容。** 实现后以**新上传或 reparse** 的结果为准；不为旧 `paragraph`+内嵌 HTML chunk 做长期兜底。交付时对目标样例执行一次 reparse/重新上传即可验收。

---

## 2. 方案选择

| 方案 | 描述 | 结论 |
|------|------|------|
| A | 仅改提示词，让模型抄表 | 否：仍会改写，不符「原表」 |
| B | 检索后抽原表，答案末尾服务端拼接 | **要做** |
| C | 解析侧强制 table + 双形态入库 | **要做** |
| 一期范围 | **B + C 同期** | 已确认 |

推荐数据流：

```text
原始 blocks（MinerU / DOCX / PDF）
  → TableNormalizer（伪表升格 + 网格 → html/md）
  → 跨页邻表合并（列数一致）+ 重算双形态
  → IR blocks（table 原子）
  → structure_aware_chunk（表整包 / 超长按行窗+重复表头）
  → ES（block_type=table，content=章节头+markdown）

问答
  → hybrid_search（透出 block_type、section_path、filename…）
  → extract_source_tables（type=table 或规范 MD 表）
  → format_results_for_llm（表用 MD；提示勿重写表）
  → LLM 流式叙述
  → append 原文表格（固定模板）
  → 前端 marked 渲染
```

---

## 3. 表 block 数据契约（高保真双形态）

每个定稿表 block **必须**满足：

| 字段 | 要求 |
|------|------|
| `type` | 恒为 `"table"` |
| `markdown` | GFM：表头行 + 分隔行 `| --- |` + 数据行 |
| `html` | 规范结构：`<table><thead>…</thead><tbody>…</tbody></table>`；单元格为纯文本，**去除**嵌套 `<p>`/`<span>` 等 |
| `text` | 与 `markdown` 一致（兼容旧读取路径） |
| `section_path` / 页码 | 与现有 IR 一致 |

**禁止定稿态：**

- `type=paragraph` 且正文内嵌整段 `<table>`  
- 仅有 HTML 或仅有 Markdown  
- HTML 与 Markdown 来自不同手写源（必须 **同一 2D 网格生成**）

**高保真定义（一期）：**

1. 行列数与解析网格一致；合并单元格一期**拆平为重复文本**，不丢字、不做 colspan。  
2. 单元格文案与原文一致（不得改写数字与称谓）。  
3. `html` 与 `markdown` 仅由同一网格生成，避免漂移。

---

## 4. 模块设计

### 4.1 TableNormalizer（新建，建议 `table_utils.py`）

**职责：**

- 检测伪表：`text`/`html` 含 `<table`；或连续 ≥3 行 GFM 管道表；或已有 `type=table` 仅补全字段。  
- HTML → 二维网格 → 再生 `html` + `markdown`。  
- Markdown → 二维网格 → 再生 `html` + `markdown`。  
- 单元格：去标签、空白归一；单元格内换行 → 空格。

**接口（示意）：**

```python
def html_to_grid(html: str) -> list[list[str]]: ...
def markdown_to_grid(md: str) -> list[list[str]]: ...
def grid_to_html(grid: list[list[str]]) -> str: ...
def grid_to_markdown(grid: list[list[str]]) -> str: ...
def normalize_table_fields(html=None, markdown=None, text=None) -> dict:
    """返回 {html, markdown, text}，同源网格。"""
def promote_raw_blocks(raw_blocks: list[dict]) -> list[dict]:
    """伪段落表 → type=table 并填双形态。"""
```

坏表 / 解析失败：跳过升格或跳过该块字段补全，**不抛死**整篇文档。

### 4.2 document_pipeline 接入点

1. 在 `build_ir` 使用 raw_blocks **之前**调用 `promote_raw_blocks`。  
2. `_merge_adjacent_tables` 合并后**重新** `normalize_table_fields`。  
3. table 分支写入完整 `html`/`markdown`/`text`（勿再仅用 `<pre>md</pre>` 敷衍，除非网格失败时的最后回退）。  
4. `structure_aware_chunk`：  
   - `content` = 章节头 + **`markdown`**（禁止主内容只存脏 HTML）。  
   - 表不走「第X条」段落切分；超长表按行窗口切并重复表头（现有思路保留）。

### 4.3 索引

- 写入字段：现有 `block_type`、`content`、`section_path` 等即可。  
- `content` 主体为 Markdown 表。  
- **一期不强制**新增 ES `table_html` 字段；完整 `html` 保留在 `ir.json` 供预览。  
- **无存量迁移**；验收依赖 reparse/重传。

### 4.4 检索 `search_local`

返回字典增加（ES 已有则透出）：

- `block_type`  
- `section_path`  
- （已有）`filename`、`doc_id`、`chunk_id`、`content`、`score`

### 4.5 问答侧

| 步骤 | 行为 |
|------|------|
| `extract_source_tables(hits)` | 优先 `block_type == "table"`；否则 content 为规范 GFM 表时可抽取。去重。最多 **2** 张。需 ≥2 行 × ≥2 列。 |
| `format_results_for_llm` | 表块完整纳入（建议单表上下文上限 ≥2000 字）；非表仍可 800。上下文注明：答案末将附原文表，**勿用列表逐格复述、勿编造行**。 |
| `SYSTEM_PROMPT` 增量 | 有表上下文时：文字概括要点与条款引用；表格以系统附赠原文为准。 |
| `stream_answer` | 流式输出叙述 tokens；在 `done` 前将固定模板拼到 `answer`（保证前端完整显示）。 |

**拼接模板：**

```markdown
（模型叙述）

---

## 原文表格

> 来源：{filename} · {section_path}

{markdown_table}
```

无合格表：行为与现网一致（纯叙述/列表），不强制空表头。

### 4.6 前端

- 聊天：依赖现有 `marked` + `gfm`；**建议**为 `.msg.assistant table` 增加边框、单元格 padding、横向滚动。  
- 文档预览：`type=table` 优先安全渲染规范 `html`，否则 `marked(markdown)`。  
- 不新增 SSE 事件类型。

### 4.7 配置（可选，有默认）

| 配置 | 默认 | 含义 |
|------|------|------|
| `ANSWER_ATTACH_TABLES` | `true` | 是否答后附表 |
| `ANSWER_MAX_TABLES` | `2` | 最多附表数 |
| `TABLE_CONTEXT_MAX_CHARS` | `2000` | 单表块进 LLM 上下文上限 |

---

## 5. API 兼容

- `POST /api/chat/stream`：事件协议不变；assistant 最终文本含附表。  
- 上传 / reparse：响应形状可不变；内部 IR 更干净。  
- 历史会话记录不回溯改写。

---

## 6. 测试计划

| 层级 | 用例 |
|------|------|
| 单元 | HTML→grid→MD 往返；伪段落升格；坏 HTML 不抛；「27个月本人工资」保留 |
| 管线 | 样例 DOCX 解析/reparse → IR `type=table` 双字段齐全；表不被条款规则切碎 |
| 检索 | `search_local('待遇标准')` 命中 `block_type=table` 且 content 为 MD 表 |
| 问答 e2e | stream「待遇标准」→ 含 `## 原文表格` 与 `| 伤残等级 |`；一级=27 个月 |
| 前端 | 聊天区可见表格（人工） |

---

## 7. 实现顺序

1. `table_utils`：网格与 HTML/MD 同源生成 + 伪表检测。  
2. 接入 `document_pipeline`（raw → IR → chunk → index）。  
3. `search` / `qa_service`：透出字段、上下文策略、抽表拼接、提示词。  
4. 前端表样式（小改）。  
5. 目标文档 reparse + e2e 验收。

---

## 8. 风险

| 风险 | 缓解 |
|------|------|
| 上游 MinerU 表质量差 | 归一化不发明单元格；抽表失败则不附表 |
| 双形态漂移 | 只允许 grid → html+md |
| 答案过长 | 最多 2 表；超长行数截断并注明 |
| reparse 耗时 | 验收仅目标文档；CPU 异步任务保持现有模型 |

---

## 9. 明确不做（一期）

- 为旧索引 paragraph 内嵌 HTML 做长期兼容分支  
- 合并单元格可视化（colspan/rowspan）  
- 表计算、导出 Excel、多知识库表对齐 UI  
- 强制所有问题都出表  
- **存量数据兼容**（用户明确不需要）

---

## 10. 设计对话结论摘要

- 期望形态：**叙述 + 文档原表**（非仅提示词抄表）。  
- 一期：**B（答后原表）+ C（解析双形态）一起做**。  
- 源头原则：**高保真 HTML + Markdown**，表原子化，消除语义碎片化。  
- **不考虑存量数据**；以 reparse/新上传为准。  

---

## 11. Spec 自检

- [x] 无 TBD/TODO 占位  
- [x] B/C 与数据契约一致  
- [x] 范围单一可做一份 implementation plan  
- [x] 存量策略唯一：不做兼容  
- [x] 成功标准可测（27 个月、GFM、block_type=table）  
