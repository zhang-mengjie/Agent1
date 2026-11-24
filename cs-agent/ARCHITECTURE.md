# cs-agent 架构说明

企业客服 Agent，目录与数据流对齐 `rag-agent`，并增加客服领域能力：意图识别、转人工建议。

## 架构图

```text
浏览器 / MCP 客户端
        │
        ▼
   FastAPI (cs_agent.main)
        │
        ├─ /chat ──────────► agent.cs_agent.run_agent
        │                         │
        │                         ├─ intent.classify_intent   （意图）
        │                         ├─ rag.retrieve             （FAQ 向量检索）
        │                         ├─ llm.build_chat_model     （生成答复）
        │                         ├─ redis_memory             （短期会话）
        │                         └─ db.save_turn             （长期落库）
        │
        └─ /documents* ────► rag.ingest_* / pdf_ingest
                                   │
                                   ▼
                     PostgreSQL(pgvector) + Redis
```

## 与 rag-agent 的异同

| 点 | rag-agent | cs-agent |
| --- | --- | --- |
| 定位 | 通用知识库问答 | 企业客服 FAQ + 转人工 |
| 端口 | 8001 | 8002 |
| PG/Redis | 5432 / 6379 | 5433 / 6380（隔离） |
| 对话增强 | 严格 RAG | 严格 RAG + 意图 + 转人工 |
| 表结构 | conversation_turns + rag_chunks | 同构（可加 intent 字段） |

## 关键模块注释入口

- `cs_agent/main.py`：应用生命周期
- `cs_agent/agent/cs_agent.py`：客服编排主循环
- `cs_agent/services/intent.py`：规则意图分类
- `cs_agent/services/rag.py`：向量入库与检索
- `cs_agent/mcp_server.py`：Cursor MCP 工具
