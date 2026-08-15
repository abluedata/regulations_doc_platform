# T12 修复报告：Embedding token 超限导致长文档入库失败

日期：2026-08-15 · 依据：实施计划 E-08 评测数据 + W1 金标、企业级可靠性 R-06

## 根因

BAAI/bge-large-zh-v1.5 上下文仅 512 token（中文约 1 字 ≈ 1 token）。实测中文文本超 ~616
字符即被 SiliconFlow 拒绝（HTTP 400, code 20015 "The parameter is invalid"）。
`structure_aware_chunk` 的 CHUNK_SIZE=512 字符，再叠加 [文档]/[章节] 头部注入与表格
markdown 语法（`| --- |`），实际 token 数超过 512 → 144 页 `tender_file.pdf` embedding
失败、文档 `status=failed`（错误码 20015 已在 `.data/docs_index.json` 确认）。

## 修复内容（代码）

1. **backend/core/config.py**
   - `CHUNK_SIZE` 512 → 384，`CHUNK_OVERLAP` 128 → 96（按比例 ~25%），为头部/表格语法留 token 余量；
   - 新增 `EMBED_MAX_CHARS = 450`（请求前硬阈值，显著低于实测 616 失败点）。

2. **backend/services/utils.py（新增共享函数）**
   - `truncate_for_embedding(text, max_chars=450)`：token 安全截断兜底——
     ≤阈值原样返回；超限时保留开头连续的 [文档]/[章节] 标题头部行，
     正文在剩余预算内优先按句界（。！？；）截断，无句界标点（如巨型表格行）则硬截断。

3. **backend/services/document_pipeline.py**
   - `_embed()` 在发起请求前对每个 chunk 执行 `truncate_for_embedding(..., EMBED_MAX_CHARS)`。
     索引的 `content` 字段仍保存全文（展示/BM25 不受影响），仅 embedding 请求文本被截断。

4. **backend/services/indexer.py**
   - `get_embeddings()` 同样加截断兜底；`main()` 中硬编码的 `chunk_size=512, overlap=128`
     打印改为引用 config 常量；`chunk_strategy.py` 文档字符串同步更新。

## 单元测试（新增 backend/tests/test_embed_safety.py，15 个用例 + 4 子用例）

- `truncate_for_embedding` 规则：短文本/边界不变、头部逐字保留、句界截断、无标点硬截断、
  头部超限硬截断、任意超长输入永不越界、非 str 透传；
- `document_pipeline._embed`：mock `core.http_client.requests_session` 捕获真实请求 payload，
  验证超限 chunk 请求前被截到 ≤450 且头部保留、多批（230 条）全部安全；
- `indexer.get_embeddings`：同验证（注意 patch 模块顶层导入的 `indexer.requests_session`）；
- 端到端：构造单行超长（3000 字符）表格 → `structure_aware_chunk` 产出超限 chunk →
  `_embed` 兜底后所有请求文本 ≤450；
- 配置不变量：`CHUNK_SIZE < EMBED_MAX_CHARS ≤ 500 < 616（实测失败点）`、overlap 按比例缩放。

## 验证结果

- **backend pytest 全绿**：176 tests collected / 0 failed（exit 0，默认 addopts `-ra -s`）。
- **live 验收**：启动 uvicorn API（127.0.0.1:8000，ES Docker 已运行）→
  `POST /api/docs/20260815_144140_4907511c/reparse`（tender_file.pdf，原 status=failed）→
  **status=ready**，chunk_count=1406，engine=mineru:pipeline，duration 105s，无 20015 错误；
  ES 中确认 1406 条 chunk 已入库；其中 8 条 content >450 字符、3 条 >616 字符（旧配置必失败），
  因请求前截断兜底全部 embedding 成功 —— 证明「任何超限内容都不会导致整篇文档入库失败」。

## 遗留

- 无代码遗留。可选项（未做）：对表块 `<= max_len*2` 的 2 倍窗口单独收紧；命中后如需
  可后续在 `_split_table_rows` 增加行级硬切。
- 验证用 uvicorn 进程已停止，环境恢复原状（后端/前端未运行）。
