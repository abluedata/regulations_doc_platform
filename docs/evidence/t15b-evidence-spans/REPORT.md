# T15b — PDF 原始文件端点 + 证据坐标定位（验证报告）

日期：2026-08-15
仓库：D:\workspace\agent\regulations_doc_platform（branch main，HEAD b85c1f8）

## 交付物

### 1. GET /api/docs/{doc_id}/file —— 原始 PDF 下载端点

- `backend/api/routes/docs.py` 新增 `@router.get("/{doc_id}/file")`：
  FileResponse 返回 `.data/uploads/<doc_id>/original.pdf`，404 兜底（文档不存在 / 原始文件不存在），
  `Content-Disposition: inline`（前端 pdfjs 直接渲染），Range 请求由 FileResponse 自带支持（Accept-Ranges: bytes）。

### 2. 解析管线保存证据坐标（evidence_spans.json）

- 新增 `backend/services/evidence_spans.py`：
  - `spans_from_content_list`：把 MinerU `original_content_list.json` 精简为
    `{"spans":[{"text":..., "bbox":[x0,y0,x1,y1], "page": page_idx+1}]}`（PDF 原始坐标 pt，page 1-based）。
  - `ensure_doc_evidence_spans` / `backfill_doc_evidence_spans`：存量文档一次性 backfill，
    doc_id → mineru job 目录匹配 = meta 解析时间窗（±10min）+ 文本重叠验证（≥3 个 span 命中）。
  - `backfill_ir_pages`（可选加分项）：文本前缀匹配回填 ir.json 的 block page_start/page_end。
- `mineru_service/adapter.py`：/parse 响应透传上游 `content_list`（含 pt bbox 与 0-based page_idx）与 `task_id`。
- `backend/services/document_pipeline.py`：解析入库时把 content_list 精简为 evidence_spans 并随
  `write_version_artifacts` 原子落库；同源重析时对旧版本补写缺失的 evidence_spans.json。
- `backend/services/document_store.py`：`write_version_artifacts` 增加可选 `evidence_spans` 参数。
- `backend/backfill_evidence_spans.py`：独立 backfill 脚本（幂等）。
- `backend/api/main.py`：启动时懒生成（`backfill_all_ready_docs`，幂等）。

### 3. findings API 返回真实 evidence_anchor

- `backend/api/routes/review.py`：GET /analysis-jobs/{job_id}/findings 逐条
  `evidence_spans.enrich_evidence_anchor` 回填：
  - `page_number` = span.page（1-based）
  - `rects` = `[{"page":n,"x0":..,"y0":..,"x1":..,"y1":..,"space":"pdf-pt"}]`
  - `precision="rect"`、`validation_status="exact"`、`coordinate_space="pdf-pt"`
  - 找不到 span / 文档已删除时保持现有退化（precision:"page"、rects 空）。

## 验证输出（已记录）

### pytest

```
venv\Scripts\python.exe -m pytest backend/tests
exit=0（全绿）
-v 运行：232 PASSED，0 failed / 0 error
新增 backend/tests/test_evidence_spans.py：12 项用例
（覆盖 spans 精简、quote→span 匹配、写入/读取、时间窗+文本重叠 backfill、
 ir.json 页码回填、/file 端点 200/206/404、findings 富化与退化保持）
```

### HTTP 实测（powershell Invoke-WebRequest / curl，127.0.0.1:8002）

- `GET /api/docs/20260815_170313_10914490/file`
  → `200`，`Content-Type: application/pdf`，`Content-Disposition: inline; filename="tender_file.pdf"`，
  `Accept-Ranges: bytes`，710966 bytes。
- Range `bytes=0-99` → `206`，100 bytes。
- 不存在文档 → `404`。
- `GET /api/review/analysis-jobs/8941efd5-8d53-4d6f-b4c1-a4cd678b73cd/findings`（tender 分析 job）：
  - quote="合同业绩" → `page_number=6`、`rects=[{page:6, x0:115, y0:529, x1:877, y1:601, space:"pdf-pt"}]`、
    `precision="rect"`、`validation_status="exact"`、`coordinate_space="pdf-pt"` ✓（与 spec 示例一致）
  - quote="依法注册的独立法人" → `page_number=6`、rects 非空、precision="rect" ✓
- 已删除文档（20260815_144140_4907511c 等）的旧 findings 保持退化：precision="page"、rects 空 ✓。

### evidence_spans.json backfill（.data/uploads/*/versions/*/evidence_spans.json）

```
[OK  ] 20260815_170313_10914490（tender_file.pdf）: spans=1594
[OK  ] 20260815_091825_0aa947bb: spans=260
[OK  ] 20260815_091641_7537bfe7: spans=183
[SKIP] 20260718_201715_97b888e2（docx，python-docx，无 mineru job）
[SKIP] 20260718_111709_1f30291c（docx，同上）
```

- tender 文档验证：spans 中"合同业绩"位于 page 6，bbox [115,529,877,601] ✓
- 加分项 ir.json 页码回填：tender 1271/1349 blocks、蓝皮书 137/173、ClaudeCode 243/270 已带 page_start/page_end。

## 环境说明

- 规格中提到的 doc_id 20260815_144140_4907511c / 20260815_163440_ebe13cbd 的 uploads 目录在任务开始前已被删除
  （其 findings 保持退化，属预期）。当前在线 tender 文档为 20260815_170313_10914490（同 1406 chunks / 144 页），
  已按同一流程生成证据坐标并通过全部验证。
- 服务重启：8002（business API）与 8003（adapter）已重启并 health OK；前端未动（工作区含 T17/T18 未提交改动，未触碰）。
- 前端 build 不受影响（未改动任何 frontend 文件）。
