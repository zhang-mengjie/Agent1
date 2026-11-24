"""finance-agent MCP：报销审批与制度工具。

【初学者 · 目的】在 Cursor 里直接 submit / 解析发票路径 / 写入制度。
【易错点】mcp.json 用 venv python -m，勿 uv run；finance_submit 的 receipt_path 须是本机可读路径。
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.mcpserver import MCPServer

from finance_agent.config import get_settings, reload_settings
from finance_agent.schemas.expense import ExpenseSubmitRequest
from finance_agent.services.db import SessionLocal, init_db, ping_db
from finance_agent.services.rag import get_chunk_stats, ingest_texts, init_vector_schema, retrieve
from finance_agent.services.redis_memory import memory

mcp = MCPServer(
    "finance-agent",
    instructions="企业财务审批工具。用 finance_submit 走完整审批链；用 finance_ingest_policy 写入制度。",
)


def _ensure() -> None:
    reload_settings()
    s = get_settings()
    if s.hf_endpoint:
        import os

        os.environ.setdefault("HF_ENDPOINT", s.hf_endpoint)
    try:
        init_vector_schema()
    except Exception:
        pass


@mcp.tool(description="财务 Agent 探活")
def finance_health() -> dict[str, Any]:
    _ensure()

    async def _run() -> dict[str, Any]:
        await memory.connect()
        return {
            "postgres": await ping_db(),
            "redis": await memory.ping(),
            "model": get_settings().llm_model,
        }

    return asyncio.run(_run())


@mcp.tool(description="财务制度库统计")
def finance_stats() -> dict[str, Any]:
    _ensure()
    return {**get_chunk_stats(), "collection": get_settings().collection_name}


@mcp.tool(description="写入财务制度文本")
def finance_ingest_policy(text: str, source: str = "finance-policy") -> dict[str, Any]:
    _ensure()
    count = ingest_texts([text], source=source)
    return {"ok": True, "ingested_chunks": count}


@mcp.tool(description="检索财务制度")
def finance_search_policy(query: str, top_k: int = 4) -> dict[str, Any]:
    _ensure()
    docs = retrieve(query, top_k=top_k)
    return {
        "hits": [{"content": d.page_content, "distance": d.metadata.get("distance")} for d in docs]
    }


@mcp.tool(description="解析本地发票 PDF/图片，返回 OCR 文本与结构化字段")
def finance_parse_receipt(path: str) -> dict[str, Any]:
    _ensure()
    from pathlib import Path

    from finance_agent.services.receipt_ingest import extract_receipt_text
    from finance_agent.services.receipt_parser import parse_receipt_text

    file_path = Path(path)
    if not file_path.is_file():
        return {"ok": False, "error": f"文件不存在: {path}"}
    data = file_path.read_bytes()
    max_bytes = get_settings().max_receipt_bytes
    if len(data) > max_bytes:
        return {"ok": False, "error": "文件过大"}
    try:
        extracted = extract_receipt_text(data, filename=file_path.name)
        parsed = parse_receipt_text(extracted["text"])
        parsed.source_method = extracted["method"]
        parsed.source_filename = extracted["filename"]
        return {
            "ok": True,
            "filename": extracted["filename"],
            "method": extracted["method"],
            "extracted_text": extracted["text"],
            "parsed": parsed.model_dump(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool(description="提交报销并执行智能审批链路；可附带本地发票 PDF/图片路径")
def finance_submit(
    employee_id: str,
    employee_name: str,
    department: str,
    category: str,
    amount: float,
    description: str,
    invoice_no: str | None = None,
    receipt_text: str | None = None,
    receipt_path: str | None = None,
) -> dict[str, Any]:
    _ensure()

    async def _run() -> dict[str, Any]:
        from pathlib import Path

        from finance_agent.agent import run_expense_pipeline
        from finance_agent.services.receipt_ingest import extract_receipt_text

        text = receipt_text
        method = "paste" if text else None
        filename = None
        if receipt_path:
            p = Path(receipt_path)
            if not p.is_file():
                return {"ok": False, "error": f"发票文件不存在: {receipt_path}"}
            extracted = extract_receipt_text(p.read_bytes(), filename=p.name)
            text = extracted["text"]
            method = extracted["method"]
            filename = extracted["filename"]

        await memory.connect()
        await init_db()
        req = ExpenseSubmitRequest(
            employee_id=employee_id,
            employee_name=employee_name,
            department=department,
            category=category,
            amount=amount,
            description=description,
            invoice_no=invoice_no,
            receipt_text=text,
            submit_to_erp=True,
        )
        async with SessionLocal() as db:
            result = await run_expense_pipeline(req, db)
        if method:
            result.parsed_receipt.source_method = method
            result.parsed_receipt.source_filename = filename
        return result.model_dump()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> None:
    _ensure()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
