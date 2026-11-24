# cs-agent

企业客服 Agent。架构与 `rag-agent` 对齐：`FastAPI + Pydantic + PostgreSQL(pgvector) + Redis + LangChain + RAG`。

相对 `rag-agent` 的增强：

- 意图识别（退款 / 物流 / 账号 / 发票 / 人工…）
- 连续 FAQ 未命中后建议转人工
- 对话落库带 `intent` / `need_human`

详细架构见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

## 快速开始

```powershell
cd cs-agent
# 编辑 .env：LLM_API_KEY 等（可从 rag-agent/.env 复制）
docker compose up -d
# 安装依赖（推荐直接用 venv，避免 uv 锁 rag/cs exe）
uv sync
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m uvicorn cs_agent.main:app --host 0.0.0.0 --port 8002 --reload --reload-dir src
```

- 前端：http://127.0.0.1:8002/
- API 文档：http://127.0.0.1:8002/docs

## 导入示例 FAQ

前端「FAQ 知识库」粘贴 `fixtures/sample_faq.txt` 内容，或：

```powershell
curl -s http://127.0.0.1:8002/documents -H "content-type: application/json" -d "@-" <<'EOF'
{"texts":["【退款政策】未发货可取消即时退款。"],"source":"faq"}
EOF
```

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 客服前端 |
| GET | `/health` | 探活 |
| POST | `/chat` | 客服对话（返回 intent / need_human） |
| POST | `/documents` | FAQ 文本入库 |
| POST | `/documents/pdf` | PDF 入库 |
| GET | `/documents` | 切片列表 |
| GET | `/documents/stats` | 统计 |

## MCP

仓库 `.cursor/mcp.json` 已配置 `cs-agent`（使用 venv python，避免 `uv run` 文件锁）。

工具：`cs_health` / `cs_stats` / `cs_list` / `cs_search` / `cs_ingest_text` / `cs_ingest_pdf` / `cs_ask`

## 端口约定

| 服务 | rag-agent | cs-agent |
| --- | --- | --- |
| API | 8001 | 8002 |
| Postgres | 5432 | 5433 |
| Redis | 6379 | 6380 |
