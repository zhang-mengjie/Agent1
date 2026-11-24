"""cs-agent MCP：把客服 FAQ / 问答能力暴露给 Cursor。

【初学者 · 目的】在 IDE 里直接搜 FAQ、模拟用户提问。

【易错点】
启动勿用 uv run（锁 exe）。推荐：
  .venv\\Scripts\\python.exe -m cs_agent.mcp_server
mcp.json 里 command 指向该 python 绝对路径。
"""

from __future__ import annotations

import asyncio  # Python 标准库：异步事件循环，此处用 asyncio.run 在同步工具中运行协程
from pathlib import Path  # Python 标准库：路径操作，此处解析本地 PDF 路径（~ 展开、绝对路径）
from typing import Any  # Python 标准库：类型标注，表示任意类型（用于工具返回的 dict 值）

from mcp.server.mcpserver import MCPServer  # MCP SDK：Server 类，注册工具并以 stdio 传输与 IDE 通信

from cs_agent.config import get_settings, reload_settings
from cs_agent.schemas.chat import AgentChatRequest, ModelParams
from cs_agent.services.db import SessionLocal, init_db, ping_db
from cs_agent.services.pdf_ingest import extract_pdf_text
from cs_agent.services.rag import (
    format_context,
    get_chunk_stats,
    ingest_texts,
    init_vector_schema,
    list_chunks,
    retrieve,
)
from cs_agent.services.redis_memory import memory

mcp = MCPServer(
    "cs-agent",
    instructions=(
        "企业客服 FAQ 工具。"
        "用 cs_search / cs_ask 查询；用 cs_ingest_text / cs_ingest_pdf 写入 FAQ。"
        "业务事实必须依据知识库。"
    ),
)


def _ensure_runtime() -> None:
    """确保 MCP 工具运行环境就绪：重载配置、设置 HF 镜像、初始化向量表。

    在每次工具调用前执行，使 .env 改动能被 MCP 进程感知；向量表初始化失败
    静默忽略（可能基础设施尚未启动）。
    """
    reload_settings()
    s = get_settings()
    if s.hf_endpoint:
        import os

        os.environ.setdefault("HF_ENDPOINT", s.hf_endpoint)
    try:
        init_vector_schema()
    except Exception:
        pass


@mcp.tool(description="客服系统探活")
def cs_health() -> dict[str, Any]:
    """工具：探活，返回 PostgreSQL / Redis 连通性、默认模型与企业名。

    Returns:
        dict: postgres / redis 布尔值，llm_model 与 company_name 字符串。
    """
    _ensure_runtime()

    async def _run() -> dict[str, Any]:
        await memory.connect()
        s = get_settings()
        return {
            "postgres": await ping_db(),
            "redis": await memory.ping(),
            "llm_model": s.llm_model,
            "company_name": s.company_name,
        }

    return asyncio.run(_run())


@mcp.tool(description="FAQ 知识库统计")
def cs_stats() -> dict[str, Any]:
    """工具：返回知识库切片统计，并附加逻辑集合名。

    Returns:
        dict: total_chunks / vectorized_chunks / embedding_dims / sources / collection。
    """
    _ensure_runtime()
    return {**get_chunk_stats(), "collection": get_settings().collection_name}


@mcp.tool(description="列出 FAQ 切片")
def cs_list(limit: int = 20, offset: int = 0, source: str | None = None) -> dict[str, Any]:
    """工具：分页列出已入库切片（limit 钳制到 1~100，offset 不小于 0）。

    Args:
        limit: 返回条数，默认 20，最大 100。
        offset: 分页偏移，默认 0。
        source: 来源标签过滤；None 表示不过滤。

    Returns:
        dict: total_returned 为本次返回条数，items 为切片列表。
    """
    _ensure_runtime()
    items = list_chunks(limit=max(1, min(limit, 100)), offset=max(0, offset), source=source)
    return {"total_returned": len(items), "items": items}


@mcp.tool(description="语义检索 FAQ")
def cs_search(query: str, top_k: int = 4) -> dict[str, Any]:
    """工具：对查询做语义检索，返回命中数、可读摘录与逐条命中详情。

    Args:
        query: 查询文本。
        top_k: 返回条数，钳制到 1~20，默认 4。

    Returns:
        dict: query、hit_count、context（拼接的知识库摘录）、
            hits（每项含 content / source / distance）。
    """
    _ensure_runtime()
    docs = retrieve(query, top_k=max(1, min(top_k, 20)))
    return {
        "query": query,
        "hit_count": len(docs),
        "context": format_context(docs),
        "hits": [
            {
                "content": d.page_content,
                "source": d.metadata.get("source"),
                "distance": d.metadata.get("distance"),
            }
            for d in docs
        ],
    }


@mcp.tool(description="写入 FAQ 文本")
def cs_ingest_text(text: str, source: str = "faq") -> dict[str, Any]:
    """工具：把一段文本切分、向量化后写入知识库。

    Args:
        text: 待入库文本，纯空白时返回错误。
        source: 来源标签，默认 "faq"。

    Returns:
        dict: 成功时 ok=True 并含 ingested_chunks / source；
            文本为空时 ok=False 并含 error。
    """
    _ensure_runtime()
    if not text.strip():
        return {"ok": False, "error": "text 不能为空"}
    count = ingest_texts([text], source=source or "faq")
    return {"ok": True, "ingested_chunks": count, "source": source}


@mcp.tool(description="从本地 PDF 路径写入 FAQ")
def cs_ingest_pdf(path: str, source: str | None = None) -> dict[str, Any]:
    """工具：读取本地 PDF 文件，抽取文本后写入知识库。

    仅支持可复制文本的 PDF（扫描件需先 OCR）。

    Args:
        path: PDF 文件路径，支持 ~ 展开；必须为存在的 .pdf 文件。
        source: 来源标签；留空时默认使用文件名。

    Returns:
        dict: 成功时 ok=True 并含 ingested_chunks / source；
            路径无效或解析失败时 ok=False 并含 error。
    """
    _ensure_runtime()
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists() or file_path.suffix.lower() != ".pdf":
        return {"ok": False, "error": "PDF 路径无效"}
    text = extract_pdf_text(file_path.read_bytes(), filename=file_path.name)
    src = (source or "").strip() or file_path.name
    count = ingest_texts([text], source=src, metadatas=[{"filename": file_path.name, "type": "pdf"}])
    return {"ok": True, "ingested_chunks": count, "source": src}


@mcp.tool(description="客服问答（含意图与转人工建议）")
def cs_ask(question: str, session_id: str | None = None) -> dict[str, Any]:
    """工具：完整走一次客服问答（RAG + 意图 + 转人工判断）。

    Args:
        question: 用户问题。
        session_id: 会话 ID；None 则新建。复用可延续多轮上下文。

    Returns:
        dict: 成功时 ok=True 并含 session_id / answer / intent / need_human /
            used_rag / sources；异常时 ok=False 并含 error。
    """
    _ensure_runtime()

    async def _run() -> dict[str, Any]:
        from cs_agent.agent import run_agent

        await memory.connect()
        await init_db()
        req = AgentChatRequest(
            message=question, session_id=session_id, use_rag=True, model_params=ModelParams()
        )
        async with SessionLocal() as db:
            result = await run_agent(req, db)
        return {
            "ok": True,
            "session_id": result.session_id,
            "answer": result.answer,
            "intent": result.intent,
            "need_human": result.need_human,
            "used_rag": result.used_rag,
            "sources": result.sources,
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> None:
    """MCP 服务入口：初始化运行环境后以 stdio 传输方式运行 MCP Server。"""
    _ensure_runtime()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
