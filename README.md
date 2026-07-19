# regulations_doc_platform — 合同法规审核 Agent 平台

基于 **Elasticsearch** + **向量检索** + **大语言模型** 的合同/法规条款智能问答系统。

- 将文档（TXT / PDF / DOCX 等）分块后使用 Embedding 向量化，写入 Elasticsearch
- 混合检索（BM25 + 向量 + RRF）召回相关片段，流式生成回答
- 复杂问题（对比 / 总结等）自动切换大上下文并行问答
- 本地知识不足时可走 Tavily 网络补充（可选）
- Vue3 前端 + FastAPI 后端；支持历史、收藏、知识库上传与 MinerU 版面解析

## 系统架构

```
用户 (Vue3 :5173)
        │  /api  proxy
        ▼
FastAPI (backend/api/ :8002, cwd=backend)
        │
        ├── services/qa_service      流式问答
        ├── services/search          BM25 + Vector + RRF + Route
        ├── services/parallel_qa     大上下文并行问答
        ├── services/chat_manager    历史 / 收藏 (.chat_data/)
        ├── services/document_*      上传、解析、分块、入库
        └── core/                    配置
                │
                ├── Elasticsearch
                ├── Embedding API
                └── LLM API
                │
MinerU (:8001) + adapter (:8003)  ← 文档解析（一键启动脚本拉起）
```

代码分层依赖方向（单向）：

```
api  →  services  →  core
```

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| **前端** | Vue3 + Vite + Element Plus | 开发端口 5173；`/api` 代理到 8002 |
| **API** | FastAPI + Uvicorn | 业务 API，默认端口 **8002** |
| **解析** | MinerU pipeline + 本地 adapter | mineru-api :8001，adapter :8003 |
| **搜索** | Elasticsearch 8.x | `text` (BM25) + `dense_vector` |
| **向量** | OpenAI 兼容 Embeddings | 默认 SiliconFlow `BAAI/bge-large-zh-v1.5` (1024 维) |
| **LLM** | OpenAI 兼容 Chat Completions | DeepSeek / OpenAI / vLLM 等 |
| **网络搜索** | Tavily（可选） | 本地知识不足时触发 |
| **分块** | LangChain RecursiveCharacterTextSplitter | `chunk_size=512`, `overlap=128` |
| **融合** | RRF | `k=60` |

## 功能概要

### 混合检索

```
用户查询
   ├── BM25 全文 → title^3 + content
   ├── Vector 向量 → Embedding (1024 维)
   └── RRF 融合 → TOP-K
```

### 智能路由

| 结果 | 含义 | 行为 |
|---|---|---|
| **local** | 本地库足够 | 仅用本地检索结果回答 |
| **web** | 不足或不相关 | 调用 Tavily 补充后再答 |

### 复杂问题

| 模式 | 触发 | 策略 |
|---|---|---|
| 普通 | 简单事实问 | hybrid K=10，流式 LLM |
| 并行 | 长度 > 20 或含「比较/区别/总结…」等 | TOP-15 chunks，大 context + 快速模型 |

### 会话与知识库

- 历史 / 收藏：`.chat_data/history.json`、`.chat_data/favorites.json`
- 上传产物：`.data/uploads/`、`.data/docs_index.json`
- 前端支持文档列表、预览、重析、删除；解析链路可走 MinerU

## 快速开始

### 前置条件

- **Python 3.10–3.13**（推荐 **3.12**；勿用 3.14）
- Node.js + npm（前端）
- Elasticsearch 8.x
- 可访问 Embedding / LLM API 的网络

### 1. 安装依赖

```bash
git clone <your-repo-url>
cd regulations_doc_platform

# Windows
python -m venv venv
.\venv\Scripts\activate
.\venv\Scripts\pip install -r requirements.txt -i https://pypi.org/simple

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

前端：

```bash
cd frontend
npm install
cd ..
```

> `requirements.txt` 含 `mineru[pipeline]`，体积较大（含 torch 等）。仅验证 API 逻辑时可先装核心依赖，再按需安装 MinerU。

### 2. 启动 Elasticsearch

自行部署 ES 8.x，示例（Docker）：

```bash
docker run -p 9200:9200 -p 9300:9300 \
  -e "discovery.type=single-node" \
  -e "ELASTIC_PASSWORD=your_password" \
  docker.elastic.co/elasticsearch/elasticsearch:8.19.0
```

默认连接：`http://localhost:9200`，用户 `elastic`（以你的部署为准）。

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `ES_HOST` | ✅ | `http://localhost:9200` | ES 地址 |
| `ES_USER` | ✅ | `elastic` | ES 用户名 |
| `ES_PASS` | ✅ | — | ES 密码 |
| `ES_INDEX` | 可选 | `knowledge_base` | 索引名 |
| `EMBED_API_BASE` | 可选 | `https://api.siliconflow.cn/v1` | Embedding API |
| `EMBED_API_KEY` | ✅ | — | Embedding Key |
| `EMBED_MODEL` | 可选 | `BAAI/bge-large-zh-v1.5` | 模型名 |
| `EMBED_DIMS` | 可选 | `1024` | 维度 |
| `TAVILY_API_KEY` | 可选 | — | 网络搜索 |
| `LLM_API_BASE` | ✅ | `https://api.openai.com/v1` | LLM API |
| `LLM_API_KEY` | ✅ | — | LLM Key |
| `LLM_MODEL` | ✅ | `deepseek-v4-pro` | 主模型 |
| `LLM_MODEL_FAST` | 可选 | `deepseek-v4-flash` | 大上下文快速模型 |

### 4. 放入文档并建立索引（离线批量）

```bash
# 将 .txt / .pdf 放入 docs/
# cwd=backend，使 api/services/core 顶层包可 import
cd backend
python -m services.indexer
```

流程：扫描 `docs/` → 分块 → Embedding → 写入 ES 索引。

> 文件名建议 `序号-标题`（如 `01-雇主责任险条款.txt`），便于提取标题。  
> 也可在前端知识库页上传文档，走 MinerU 解析流水线入库。

### 5. 启动服务

**Windows 一键启动（推荐）：**

```powershell
.\start.ps1

# 常用参数
.\start.ps1 -Restart          # 释放端口后重启
.\start.ps1 -SkipFrontend     # 只起后端
.\start.ps1 -OpenBrowser      # 启动后打开浏览器
```

**macOS / Linux 一键启动：**

```bash
./start.sh

# 常用参数
./start.sh --restart
./start.sh --skip-frontend
./start.sh --skip-mineru      # 跳过 MinerU（仅 ES + API + 前端）
./start.sh --open-browser
```

一键脚本会拉起：

| 服务 | 默认端口 |
|---|---|
| Elasticsearch (Docker) | 9200 |
| mineru-api | 8001 |
| MinerU adapter | 8003 |
| 业务 API (`api.main`) | **8002** |
| 前端 Vite | 5173 |

> 脚本会先自动启动 / 检查 Docker 中的 `es-local` 容器（不存在则创建），无需手动 `docker run`。

停止：

```powershell
# Windows
.\stop.ps1
.\stop.ps1 -WithEs            # 同时停止 Docker 中的 ES 容器
```

```bash
# macOS / Linux
./stop.sh
./stop.sh --with-es           # 同时停止 Docker 中的 ES 容器
```

**单独启动 Elasticsearch（Docker 未开时脚本会提示先开 Docker）：**

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts\start_es.ps1
```

```bash
# macOS / Linux
bash scripts/start_es.sh
```

**手动启动（需与前端代理一致）：**

```bash
# 业务 API（默认与 vite proxy 对齐 8002）—— 注意 cwd=backend
cd backend
uvicorn api.main:app --reload --host 127.0.0.1 --port 8002

# 前端
cd frontend
npm run dev
```

访问：

| 入口 | URL |
|---|---|
| 前端 | http://127.0.0.1:5173 |
| API 文档 | http://127.0.0.1:8002/docs |
| 健康检查 | http://127.0.0.1:8002/api/health |

开发时 Vite 将 `/api` 代理到 `http://127.0.0.1:8002`。

若索引不存在，先执行（cwd=backend）`python -m services.indexer` 或通过前端上传入库。

### 6. 运行测试

```powershell
# Windows（cwd = backend，使 api/services/core 顶层包可 import）
cd backend
..\venv\Scripts\python.exe -m unittest discover -s tests -v
```

```bash
# macOS / Linux
cd backend
../venv/bin/python -m unittest discover -s tests -v
```

## 项目结构

```
regulations_doc_platform/
├── backend/                  # 后端（FastAPI + 业务）
│   ├── api/                  # HTTP 层
│   │   ├── main.py           # 应用入口：uvicorn api.main:app（cwd=backend）
│   │   ├── schemas.py
│   │   └── routes/           # chat / history / favorites / docs
│   ├── core/                 # 配置
│   │   └── config.py         # .env + 常量（_ROOT = 项目根）
│   ├── services/             # 业务服务 + 工具
│   │   ├── qa_service.py     # 流式问答
│   │   ├── parallel_qa.py    # 大上下文并行问答
│   │   ├── search.py         # 混合检索 + 路由
│   │   ├── chat_manager.py   # 历史 / 收藏
│   │   ├── document_pipeline.py  # 解析 → 分块 → 入库
│   │   ├── document_store.py # 上传元数据与 IR 本地存储
│   │   ├── chunk_strategy.py # 文本分块
│   │   ├── utils.py          # 表格 HTML/Markdown 规范化
│   │   └── indexer.py        # 离线索引：python -m services.indexer
│   └── tests/                # unittest
├── mineru_service/           # MinerU 适配服务（独立进程）
├── frontend/                 # Vue3 + Vite + Element Plus
├── scripts/                  # start_es / 验证脚本（.ps1 + .sh 双平台）
├── docs/                     # 示例文档 / design/ 设计文档
├── .data/                    # 运行时数据（上传、日志；gitignore）
├── .chat_data/               # 历史与收藏（gitignore）
├── .env.example
├── requirements.txt
├── start.ps1                 # 根目录一键启动入口（Windows）
├── start.sh                  # 根目录一键启动入口（macOS / Linux）
├── start.bat                 # 双击启动（调用 start.ps1）
├── stop.ps1                  # 根目录一键停止入口（Windows）
└── stop.sh                   # 根目录一键停止入口（macOS / Linux）
```

## API 密钥

| 服务 | 地址 | 用途 |
|---|---|---|
| SiliconFlow | https://cloud.siliconflow.com | 默认 Embedding |
| Tavily | https://tavily.com/ | 可选网络搜索 |
| DeepSeek 等 | 对应平台 | LLM 推理 |
| Elasticsearch | 本地 / 自建 | 混合检索索引 |

## 许可

MIT License — 见 [LICENSE](LICENSE)。

## 贡献

欢迎提交 Issue 或 Pull Request。
