"""rag-agent MCP：把知识库与问答能力暴露给 Cursor / 其他 MCP 客户端。

【初学者 · 目的】
MCP = 让 IDE 里的 Agent 直接调你的工具（检索/入库），不必每次手点网页。

【易错点】
1. `.cursor/mcp.json` 在 Windows 上应用「venv 的 python.exe -m rag_agent.mcp_server」，
   不要用 `uv run`：会锁 exe，Cursor 连 MCP 反复失败。
2. 路径写绝对路径更稳；相对路径取决于 Cursor 启动 cwd。
3. MCP 工具里的 asyncio.run 与已有事件循环冲突时会报错——stdio 单进程通常没事。
4. 回答业务事实应走 kb_ask/kb_search，不要让上层模型空口编。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from rag_agent.config import get_settings, reload_settings
from rag_agent.schemas.chat import AgentChatRequest, ModelParams
from rag_agent.services.db import SessionLocal, init_db, ping_db
from rag_agent.services.pdf_ingest import extract_pdf_text
from rag_agent.services.rag import (
    format_context,
    get_chunk_stats,
    ingest_texts,
    init_vector_schema,
    list_chunks,
    retrieve,
)
from rag_agent.services.redis_memory import memory

mcp = MCPServer(
    "rag-agent",
    instructions=(
        "本地 RAG 知识库工具。"
        "优先用 kb_search / kb_ask 查询；用 kb_ingest_text 或 kb_ingest_pdf 写入。"
        "回答业务事实时应依据知识库，不要编造。"
    ),
)


def _ensure_runtime() -> None:
    reload_settings()
    settings = get_settings()
    if settings.hf_endpoint:
        import os

        os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
    try:
        init_vector_schema()
    except Exception:
        pass


@mcp.tool(description="探活：Postgres / Redis / 默认模型配置")
def kb_health() -> dict[str, Any]:
    _ensure_runtime()

    async def _run() -> dict[str, Any]:
        await memory.connect()
        s = get_settings()
        return {
            "postgres": await ping_db(),
            "redis": await memory.ping(),
            "llm_model": s.llm_model,
            "embedding_provider": s.embedding_provider,
            "embedding_model": s.embedding_model,
            "embedding_dims": s.embedding_dims,
        }

    return asyncio.run(_run())


@mcp.tool(description="知识库统计：切片数、已向量化数量、来源分布")
def kb_stats() -> dict[str, Any]:
    _ensure_runtime()
    stats = get_chunk_stats()
    s = get_settings()
    return {**stats, "collection": s.collection_name}


@mcp.tool(description="列出知识库切片（可按 source 过滤）")
def kb_list(limit: int = 20, offset: int = 0, source: str | None = None) -> dict[str, Any]:
    _ensure_runtime()
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    items = list_chunks(limit=limit, offset=offset, source=source)
    return {"total_returned": len(items), "items": items}


@mcp.tool(description="语义检索知识库，返回相关切片与距离")
def kb_search(query: str, top_k: int = 4) -> dict[str, Any]:
    _ensure_runtime()
    if not query.strip():
        return {"query": query, "hits": [], "error": "query 不能为空"}
    top_k = max(1, min(top_k, 20))
    docs = retrieve(query, top_k=top_k)
    hits = [
        {
            "content": d.page_content,
            "metadata": d.metadata,
            "source": d.metadata.get("source"),
            "distance": d.metadata.get("distance"),
        }
        for d in docs
    ]
    return {
        "query": query,
        "hit_count": len(hits),
        "context": format_context(docs),
        "hits": hits,
    }


@mcp.tool(description="把纯文本写入知识库（切分 + 向量化）")
def kb_ingest_text(text: str, source: str = "mcp-manual") -> dict[str, Any]:
    _ensure_runtime()
    if not text.strip():
        return {"ok": False, "error": "text 不能为空"}
    count = ingest_texts([text], source=source or "mcp-manual")
    return {
        "ok": True,
        "ingested_chunks": count,
        "source": source or "mcp-manual",
        "collection": get_settings().collection_name,
    }


@mcp.tool(description="从本地 PDF 路径解析文本并写入知识库")
def kb_ingest_pdf(path: str, source: str | None = None) -> dict[str, Any]:
    _ensure_runtime()
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        return {"ok": False, "error": f"文件不存在: {file_path}"}
    if file_path.suffix.lower() != ".pdf":
        return {"ok": False, "error": "仅支持 .pdf"}
    data = file_path.read_bytes()
    max_bytes = get_settings().max_pdf_bytes
    if len(data) > max_bytes:
        return {"ok": False, "error": f"文件过大，上限 {max_bytes} bytes"}
    try:
        text = extract_pdf_text(data, filename=file_path.name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    src = (source or "").strip() or file_path.name
    count = ingest_texts(
        [text],
        source=src,
        metadatas=[{"filename": file_path.name, "type": "pdf", "path": str(file_path)}],
    )
    return {
        "ok": True,
        "ingested_chunks": count,
        "source": src,
        "filename": file_path.name,
        "collection": get_settings().collection_name,
    }


@mcp.tool(description="基于知识库严格问答（启用 RAG；未命中会说明没有相关信息）")
def kb_ask(question: str, session_id: str | None = None, use_rag: bool = True) -> dict[str, Any]:
    _ensure_runtime()
    if not question.strip():
        return {"ok": False, "error": "question 不能为空"}

    async def _run() -> dict[str, Any]:
        from rag_agent.agent import run_agent

        await memory.connect()
        await init_db()
        request = AgentChatRequest(
            message=question,
            session_id=session_id,
            use_rag=use_rag,
            model_params=ModelParams(),
        )
        async with SessionLocal() as db:
            result = await run_agent(request, db)
        return {
            "ok": True,
            "session_id": result.session_id,
            "answer": result.answer,
            "model": result.model,
            "used_rag": result.used_rag,
            "sources": result.sources,
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> None:
    _ensure_runtime()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
