# rag-agent 架构说明

通用 RAG 知识库问答 Agent。

## 目标

把「文档 / 文本 → 切分 → 向量化 → 检索 → 严格基于摘录生成回答」做成可运行的最小闭环，并提供 HTTP 前端与 Cursor MCP。

## 分层

```text
┌─────────────────────────────────────────────┐
│  static/ 前端  ·  MCP(stdio)  ·  /docs      │
├─────────────────────────────────────────────┤
│  api/routes.py   HTTP 契约（Pydantic）      │
├─────────────────────────────────────────────┤
│  agent/rag_agent.py   编排：检索→提示→LLM   │
├─────────────────────────────────────────────┤
│  services/                                  │
│    llm.py      Chat / Embedding 工厂        │
│    rag.py      切分入库 + pgvector 检索     │
│    db.py       对话回合异步落库             │
│    redis_memory.py  短期会话                │
│    pdf_ingest.py    PDF 抽文本              │
├─────────────────────────────────────────────┤
│  PostgreSQL(pgvector)  ·  Redis             │
└─────────────────────────────────────────────┘
```

## 数据流（一次 /chat）

1. 校验是否配置了 `LLM_API_KEY`
2. `use_rag=true` 时：`embed(query)` → `ORDER BY embedding <=> query` → 按 `RAG_MAX_DISTANCE` 过滤
3. 有命中：把摘录拼进用户消息，系统提示要求**只依据摘录**
4. 无命中：明确告知知识库无相关信息（禁止用模型常识补业务事实）
5. Redis 追加本轮对话；Postgres 写入 `conversation_turns`

## 配置要点

| 变量 | 含义 |
| --- | --- |
| `LLM_*` | Chat 模型（网关需用**模型组名**） |
| `EMBEDDING_PROVIDER=local` | 本机 FastEmbed（推荐，当网关无 embedding 时） |
| `EMBEDDING_MODEL` | 仅 FastEmbed 支持的名字，如 `BAAI/bge-small-zh-v1.5` |
| `RAG_MAX_DISTANCE` | 余弦距离上限，越大越松 |
| `API_PORT` | 默认 8001（避开僵死 8000） |

## 已知坑

1. **IVFFlat + 少量数据** 会导致检索空结果 → 本项目默认不建 IVFFlat
2. **`uv run rag-agent`** 在 Windows 上若 exe 被占用会失败 → 用 `.venv\Scripts\python.exe -m uvicorn ...`
3. 改 `.env` 后需**重启进程**（`get_settings` 有缓存）

## 关键源码注释位置

- `src/rag_agent/main.py`
- `src/rag_agent/agent/rag_agent.py`
- `src/rag_agent/services/rag.py`
- `src/rag_agent/mcp_server.py`
