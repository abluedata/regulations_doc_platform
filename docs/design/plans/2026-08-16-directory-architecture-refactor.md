# 目录架构优化规划：知识库 / 审查 / 公共 三域分层

日期：2026-08-16

## 现状问题

1. `backend/services/` 平铺混放知识库服务（qa_service/search/chat_manager/…）与审查域工具
   （evidence_spans.py 属审查证据定位，却放在 services 根目录）
2. `backend/backfill_evidence_spans.py` 脚本散落在 backend 根目录
3. 前端 `views/`、`components/` 平铺混放知识库视图与审查视图
4. 审查类型（Review*）与知识库类型混在同一个 `types/index.ts`
5. 跨域依赖成环：knowledge.document_pipeline → evidence_spans（审查工具）、
   review.qa_retrieval → knowledge.search/document_store

## 目标结构（后端）

```
backend/
├── api/                          # HTTP 层（薄）
│   ├── main.py
│   ├── schemas.py                # 知识库域 schema
│   ├── review_schemas.py         # 审查域 schema
│   ├── middleware/               # 公共：认证 / 错误 / 日志
│   └── routes/
│       ├── chat.py / docs.py / history.py / favorites.py   # 知识库接口
│       └── review.py             # 审查接口
├── core/                         # 公共核心（config / http_client / audit / metrics / log_redactor）
├── services/
│   ├── common/                   # 公共目录（跨域复用）
│   │   ├── utils.py              #  表格 HTML/Markdown 规范化（← services/utils.py）
│   │   ├── visibility.py         #  索引可见性映射（← services/visibility.py）
│   │   └── evidence_spans.py     #  证据 span 提取/定位（← services/evidence_spans.py）
│   ├── knowledge/                # 知识库域（问答 / 检索 / 文档 / 历史收藏）
│   │   ├── qa_service.py / parallel_qa.py / search.py / chat_manager.py
│   │   ├── document_pipeline.py / document_store.py / chunk_strategy.py / indexer.py
│   └── review/                   # 审查域（保持原结构，仅更新跨域 import）
│       ├── engine.py / job_runner.py / matchers.py / prompt.py / evidence.py
│       ├── suggestions.py / store.py / assistant.py / qa_answer.py / qa_retrieval.py
│       ├── report.py / hitl.py / anti_fp.py
├── scripts/                      # 后端脚本归位（新增）
│   └── backfill_evidence_spans.py  # ← backend/backfill_evidence_spans.py
├── tests/
└── eval/
```

## 目标结构（前端）

```
frontend/src/
├── api/
│   ├── http.ts                   # 公共：axios 实例 / 拦截器
│   ├── knowledge/                # 知识库接口
│   │   ├── chat.ts / docs.ts / history.ts / favorites.ts
│   └── review/
│       └── review.ts             # 审查接口（← api/review.ts）
├── components/
│   ├── common/                   # 公共组件
│   │   ├── SafeMarkdown.vue / SafeMarkdown.spec.ts
│   ├── layout/                   # 公共布局（SideNavigation / TopHeader）
│   ├── knowledge/                # 知识库组件
│   │   ├── ChatInput.vue / ChatMessage.vue / ExampleChips.vue / SessionTable.vue
│   └── review/                   # 审查组件（原样：RiskCard / ReviewPdfPreview / …）
├── views/
│   ├── knowledge/                # 知识库视图
│   │   ├── ChatView.vue / HistoryView.vue / FavoritesView.vue
│   │   ├── DocsListView.vue / DocPreviewView.vue / DetailView.vue
│   └── review/                   # 审查视图（原样）
├── stores/
│   ├── chat.ts                   # 知识库 store
│   └── review.ts                 # 审查 store
└── types/
    ├── index.ts                  # 公共 + 知识库类型，re-export review.ts
    └── review.ts                 # 审查类型（从 index.ts 拆出）
```

## 依赖方向（单向，无环）

```
api ──→ services/knowledge ──→ services/common ──→ core
api ──→ services/review ──→ services/knowledge + services/common ──→ core
```

- `evidence_spans`（被知识库管线与审查路由共用）移入 **common**，解除
  knowledge ↔ review 循环依赖
- `review → knowledge` 为刻意单向依赖：审查基于知识库文档检索与上传产物

## 实施步骤

### Phase 1 后端迁移
1. `git mv` 建 `services/common/`、`services/knowledge/`、`scripts/` 目录
2. 全局替换 import：`services.utils|visibility|evidence_spans` → `services.common.*`；
   `services.qa_service|parallel_qa|search|chat_manager|document_pipeline|document_store|chunk_strategy|indexer` → `services.knowledge.*`；
   `from services import evidence_spans|document_store` → `from services.common|knowledge import …`
3. review 域内跨域引用（qa_retrieval → search/document_store）同步更新
4. 后端测试 200 全过（cwd=backend）

### Phase 2 前端迁移
1. `git mv` 建 `api/knowledge/`、`api/review/`、`components/common/`、`components/knowledge/`、`views/knowledge/`
2. 拆分 `types/review.ts`，`types/index.ts` re-export 保持兼容
3. 更新所有 import（router / views / stores / specs）
4. vue-tsc 类型检查 + Vitest 57 全过

### Phase 3 验证与收尾
1. 后端 200 + 前端 57 全量测试
2. 服务重启冒烟（API 健康 + Vite 模块完整性 + Playwright 快速验证）
3. README「项目结构」章节同步更新
4. git commit + push

## 风险控制

- 全部改动为纯目录移动 + import 路径更新，无业务逻辑变更
- 每阶段完成后立即跑对应测试套件，失败即停
- Vite dev server 缓存空文件竞态：改动后验证关键模块 HTTP 输出完整性
- git 保留完整历史（git mv）
