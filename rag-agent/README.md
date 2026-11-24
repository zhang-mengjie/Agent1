# rag-agent

简易 RAG Agent：`Python` + `FastAPI` + `Pydantic` + `PostgreSQL(pgvector)` + `Redis` + `LangChain`。

模型参数可在 `.env` 全局配置，也可在 `/chat` 请求体里按次覆盖。

详细架构与数据流说明见 [ARCHITECTURE.md](./ARCHITECTURE.md)。同架构的企业客服项目见 `../cs-agent`。

## 目录

```text
rag-agent/
  docker-compose.yml          # Postgres(pgvector) + Redis
  .env.example
  src/rag_agent/
    main.py                   # FastAPI 入口
    config.py                 # pydantic-settings
    schemas/                  # 请求/响应模型
    api/routes.py             # HTTP 路由
    services/                 # DB / Redis / LLM / RAG
    agent/rag_agent.py        # 对话编排
    mcp_server.py             # Cursor MCP（stdio）
    static/                   # 简易前端
```

## 快速开始

```bash
cd rag-agent
cp .env.example .env
# 编辑 .env：填入 LLM_API_KEY（及 embedding 可用的 Key）

docker compose up -d
uv sync
uv run rag-agent
```

- 前端页面：<http://127.0.0.1:8001/>
- API 文档：<http://127.0.0.1:8001/docs>

> 若本机 8000 被僵死进程占用，默认改用 **8001**（见 `.env` 的 `API_PORT`）。

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 简易前端（提交知识库 / 查看向量化 / 对话） |
| GET | `/health` | Postgres / Redis 探活 |
| GET | `/config/model` | 查看默认模型参数 |
| POST | `/documents` | 文本入库（切分 + embedding） |
| POST | `/documents/pdf` | PDF 上传入库（解析文本 → 切分 → 向量化） |
| GET | `/documents` | 知识库切片列表（含是否已向量化） |
| GET | `/documents/stats` | 知识库统计（总数 / 已向量化 / 维度） |
| POST | `/chat` | RAG Agent 对话（严格仅知识库；未命中则告知无相关信息） |

### 入库示例

```bash
curl -s http://127.0.0.1:8001/documents -H "content-type: application/json" -d "{
  \"texts\": [\"本公司年假政策：正式员工每年享有 10 天带薪年假。\"],
  \"source\": \"hr-policy\"
}"
```

### PDF 入库示例

```bash
curl -s http://127.0.0.1:8001/documents/pdf \
  -F "file=@./handbook.pdf" \
  -F "source=handbook"
```

### 对话示例（可覆盖模型参数）

```bash
curl -s http://127.0.0.1:8001/chat -H "content-type: application/json" -d "{
  \"message\": \"年假有几天？\",
  \"use_rag\": true,
  \"model_params\": {
    \"model\": \"deepseek-chat\",
    \"temperature\": 0.2,
    \"max_tokens\": 1024
  }
}"
```

## 配置项

见 `.env.example`：

- `LLM_*`：Chat 模型（兼容 OpenAI / DeepSeek 等；需用网关的**模型组名**）
- `EMBEDDING_PROVIDER`：`openai` 走网关；`local` 用本机 FastEmbed（网关无 embedding 时推荐）
- `EMBEDDING_MODEL` / `EMBEDDING_DIMS` / `HF_ENDPOINT`
- `DATABASE_URL` / `REDIS_URL`
- `RAG_CHUNK_SIZE` / `RAG_TOP_K` 等

## Cursor MCP

项目已内置 MCP 服务 `rag-agent`，配置在仓库根目录 `.cursor/mcp.json`。

启用后可在 Cursor 里直接调用：

| 工具 | 作用 |
| --- | --- |
| `kb_health` | Postgres / Redis / 模型配置探活 |
| `kb_stats` | 知识库统计 |
| `kb_list` | 列出切片 |
| `kb_search` | 语义检索 |
| `kb_ingest_text` | 文本入库 |
| `kb_ingest_pdf` | 本地 PDF 路径入库 |
| `kb_ask` | 严格基于知识库问答 |

本地手动启动（stdio；请勿用 `uv run`，会因 `rag-agent.exe` 文件锁失败）：

```powershell
cd rag-agent
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m rag_agent.mcp_server
```

建议搭配的第三方 MCP（按需在 Cursor 设置里添加，本仓库未捆绑）：

- **Filesystem**：把本地文档目录暴露给 Agent，再配合 `kb_ingest_pdf`
- **PostgreSQL**：直接查 `conversation_turns` / `rag_chunks`（运维排查用）
- **Git**：变更代码时做上下文辅助

## 说明

- **PostgreSQL**：对话回合表 + `rag_chunks` 向量表（pgvector）
- **Redis**：会话短期记忆（TTL 可配）
- **LangChain**：`ChatOpenAI` + 文本切分 + 消息编排
- 对话默认严格基于知识库；未命中会明确说明没有相关信息
- MCP 与 HTTP API 共用同一套服务与数据库
