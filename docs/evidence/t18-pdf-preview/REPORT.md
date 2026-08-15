# T18 前端任务验收报告：智能审查控制台 PDF 在线预览 + 证据高亮

## 交付文件

新增：
- `frontend/src/components/review/ReviewPdfPreview.vue` —— PDF 单页预览组件（pdfjs-dist 5.7.284，worker 经 `?url` 内联），
  工具栏（上一页/下一页、页码 x/总页数、缩放 50%–200%），单页 canvas 渲染（devicePixelRatio 高清），
  overlay 高亮（黄色底 rgba(255,200,0,.4) + 2px 红色边框），页级退化（页顶横条 + "该页存在风险点"角标），
  加载失败错误 + 重试按钮，加载/渲染中状态；emits `page-change(n)` / `loaded(total)`；
  props：`docId / highlightRects / activePage / scale`（+ 可选 `fileUrl` 覆盖加载地址，便于联调自测）。
- `frontend/src/components/review/ReviewPdfPreview.spec.ts` —— 12 个测试（mock pdfjs），覆盖加载/翻页/跳页/两种坐标系换算/页级退化/错误重试/缩放边界/fileUrl/卸载销毁。

修改：
- `frontend/src/views/review/ReviewConsoleView.vue` —— 三栏布局：300px 发现列表 | 1fr PDF 预览 | 320px 问题详情；
  选中 finding → 跳页 + 高亮（activeFindingId 驱动，选新清旧、再点同一取消）；每个卡片加"定位证据"眼睛按钮；
  详情面板：severity 徽章/title/quote/reason/suggestion/证据定位/采纳建议/忽略风险（decideRisk 真实落库）；
  保留原有功能（问答助手 tab、批准草案/拒绝更改、导出报告、统计汇总）；窄屏 <1200px 预览/详情 tab 切换；
  新增 `/review/console?jobId=xxx` deep-link（刷新后可直接恢复任务，也用于联调）。
- `frontend/src/components/review/RiskCard.vue` —— 新增 `selected` prop 高亮当前选中卡片。
- `frontend/src/stores/review.ts` —— findings 映射补上 `documentId/documentVersionId`；取消加载时自动选中第一条（选择态由控制台显式驱动）。
- `frontend/src/api/review.ts` / `frontend/src/types/index.ts` —— ReviewFinding 补 document_id/document_version_id；新增 ReviewHighlightRect 类型。
- `frontend/src/views/review/ReviewConsoleView.spec.ts` —— +7 个测试（三栏渲染、定位证据跳页+高亮 rects、再点取消、采纳/忽略决策、jobId deep-link）。
- `frontend/src/stores/review.spec.ts` —— 修复 3 处 mock 类型（`never` → `any`），typecheck 全绿。
- `docs/evidence/t18-pdf-preview/` —— 浏览器联调截图证据（console-wide.png / console-narrow.png / console-evidence.png / preview-rect.png）。

## 验证结果

- `npm run test`：13 个测试文件、**65 个测试全部通过**（原 41+ 无回归）。
- `npm run build`：成功（5.4s，无错误）。
- `npm run typecheck`：0 错误（顺带修复了 T17 遗留的 3 个 mock 类型错误）。
- `npm run lint`：0 错误 0 警告。

### 浏览器联调（orca browser + Playwright，真实后端数据 + demo PDF）

后端 T15b 的 `/api/docs/{doc_id}/file` 尚未交付（仍 404），按任务要求用 mock/自测方式验证渲染，
组件按约定地址 `/api/docs/{docId}/file` 取流，T15b 就绪后无需改动即可联调：

1. 控制台页（`/review/console?jobId=8941efd5-…`，真实 findings 2 条）：
   - PDF 正常渲染：真实 tender_file.pdf 144 页，页码指示器 "1 / 144"，canvas 渲染正常。
   - 点击"定位证据"→ 选中 finding、跳到第 1 页、出现页级退化角标"该页存在风险点"+页顶横条、详情面板展示 severity/title/引用/原因/建议。
   - 点另一条 finding → 详情与高亮切换；再点同一条 → 取消选中、高亮清除、详情回空态。
   - 翻页（下一页 → "2 / 144"，上一页按钮启用）、缩放（100% → 120%，canvas 290px → 348px）。
   - 采纳建议按钮 → PUT 决策落库，按钮变"已采纳建议"、卡片 data-action=accepted。
2. 矩形高亮（独立 demo 页注入第 6 页 pdf-pt bbox [115,529,877,601]）：
   - DOM 换算精确：canvas 705px / A4 页宽 595.3pt → k≈1.1842，left 136.18px / top 626.43px / 902.34×85.26px 与公式一致。
   - 像素取证：黄色填充 rgba(255,200,0,.4) 与白色背景混合 = (255,233,153)、2px 红色边框 #ba1a1a 1267 个采样点，
     截图 docs/evidence/t18-pdf-preview/preview-rect.png 可见黄色底+红框高亮。
3. 响应式（Playwright 双视口）：
   - 1024px 窄屏：出现"PDF 预览/问题详情"切换 tab，两 pane 互斥显示，无横向溢出。
   - 1440px 宽屏：三栏并排（findings 300 / 预览 1fr / 详情 320），无切换条。

## 遗留说明

- 联调数据中 bbox[115,529,877,601] 页宽 877pt 超出本地 A4 样本页宽（595pt），超出部分被页面框裁切——
  属数据与样本不匹配，组件按页点坐标等比换算逻辑本身正确（T15b 的 pdf-pt 坐标与页面尺寸一致时无此问题）。
- 组件同时兼容 `pdf-pt`（T15b）与现有后端 `normalized-1000-top-left` 两种坐标空间，以及 precision `rect/exact/page`。
- `start_vite.bat` 为工作区既有未跟踪文件，未改动。
