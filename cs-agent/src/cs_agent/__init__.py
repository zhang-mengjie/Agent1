"""企业客服 Agent 包。

架构与 `rag-agent` 对齐：
FastAPI 提供 HTTP；PostgreSQL+pgvector 存对话与 FAQ 向量；
Redis 存短期会话；LangChain 负责切分与 Chat；本地 FastEmbed 做向量化。
"""

__version__ = "0.1.0"
