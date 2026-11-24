"""HTTP API 路由。

【初学者 · 目的】
把「能从浏览器/curl 调用的能力」暴露成 REST；业务细节放在 agent/services。

分组：system（探活）/ agent（对话）/ rag（入库与列表）

【易错点】
1. Depends(get_session) 每请求一个 AsyncSession，用完关闭——不要在模块全局共用一个 session。
2. 上传 PDF 需要 python-multipart；缺依赖时 FastAPI 报「Form data requires...」。
3. 入库失败常见根因是 embedding 403 或 PG 未起，本文件对 403 做了提示拼接。
4. response_model 用 Pydantic：返回多余字段会被丢掉，缺字段会 500——改 schema 要同步。
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from rag_agent.agent import run_agent
from rag_agent.config import get_settings
from rag_agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentListResponse,
    DocumentStatsResponse,
    HealthResponse,
)
from rag_agent.services.db import get_session, ping_db
from rag_agent.services.pdf_ingest import extract_pdf_text
from rag_agent.services.rag import get_chunk_stats, ingest_texts, list_chunks
from rag_agent.services.redis_memory import memory

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        postgres=await ping_db(),
        redis=await memory.ping(),
        llm_model=settings.llm_model,
    )


@router.post("/chat", response_model=AgentChatResponse, tags=["agent"])
async def chat(
    request: AgentChatRequest,
    db: AsyncSession = Depends(get_session),
) -> AgentChatResponse:
    settings = get_settings()
    if not (request.model_params.api_key or settings.llm_api_key):
        raise HTTPException(status_code=400, detail="未配置 LLM_API_KEY，且请求未传 api_key")
    return await run_agent(request, db)


@router.post("/documents", response_model=DocumentIngestResponse, tags=["rag"])
async def ingest_documents(request: DocumentIngestRequest) -> DocumentIngestResponse:
    settings = get_settings()
    provider = (settings.embedding_provider or "openai").strip().lower()
    if provider != "local" and not settings.effective_embedding_api_key:
        raise HTTPException(status_code=400, detail="未配置 embedding / LLM API Key")
    if request.metadatas is not None and len(request.metadatas) != len(request.texts):
        raise HTTPException(status_code=400, detail="metadatas 长度必须与 texts 一致")

    try:
        count = ingest_texts(
            request.texts,
            source=request.source,
            metadatas=request.metadatas,
        )
    except Exception as exc:
        msg = str(exc)
        if "model group" in msg.lower() or "403" in msg:
            msg += (
                " | 提示：当前网关需使用模型组名，或将 EMBEDDING_PROVIDER=local"
                " 改用本机向量模型。"
            )
        raise HTTPException(status_code=500, detail=f"入库失败: {msg}") from exc

    return DocumentIngestResponse(
        ingested_chunks=count,
        collection=settings.collection_name,
        source=request.source,
    )


@router.post("/documents/pdf", response_model=DocumentIngestResponse, tags=["rag"])
async def ingest_pdf(
    file: UploadFile = File(..., description="PDF 文件"),
    source: str | None = Form(default=None, description="来源标签；默认用文件名"),
) -> DocumentIngestResponse:
    settings = get_settings()
    provider = (settings.embedding_provider or "openai").strip().lower()
    if provider != "local" and not settings.effective_embedding_api_key:
        raise HTTPException(status_code=400, detail="未配置 embedding / LLM API Key")

    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 .pdf 文件")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > settings.max_pdf_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大，上限 {settings.max_pdf_bytes // (1024 * 1024)} MB",
        )

    try:
        text = extract_pdf_text(data, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    src = (source or "").strip() or filename
    try:
        count = ingest_texts(
            [text],
            source=src,
            metadatas=[{"filename": filename, "type": "pdf"}],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF 入库失败: {exc}") from exc

    return DocumentIngestResponse(
        ingested_chunks=count,
        collection=settings.collection_name,
        source=src,
    )


@router.get("/documents", response_model=DocumentListResponse, tags=["rag"])
async def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None, description="按来源过滤"),
) -> DocumentListResponse:
    try:
        items = list_chunks(limit=limit, offset=offset, source=source)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc
    return DocumentListResponse(total_returned=len(items), items=items)


@router.get("/documents/stats", response_model=DocumentStatsResponse, tags=["rag"])
async def documents_stats() -> DocumentStatsResponse:
    settings = get_settings()
    try:
        stats = get_chunk_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"统计失败: {exc}") from exc
    return DocumentStatsResponse(
        total_chunks=stats["total_chunks"],
        vectorized_chunks=stats["vectorized_chunks"],
        embedding_dims=stats["embedding_dims"],
        sources=stats["sources"],
        collection=settings.collection_name,
    )


@router.get("/config/model", tags=["system"])
async def get_model_config() -> dict:
    """查看当前默认可配置模型参数（不含密钥）。"""
    from rag_agent.config import reload_settings

    s = reload_settings()
    return {
        "model": s.llm_model,
        "temperature": s.llm_temperature,
        "max_tokens": s.llm_max_tokens,
        "top_p": s.llm_top_p,
        "base_url": s.llm_base_url,
        "embedding_provider": s.embedding_provider,
        "embedding_model": s.embedding_model,
        "embedding_dims": s.embedding_dims,
        "rag_top_k": s.rag_top_k,
        "rag_max_distance": s.rag_max_distance,
        "rag_chunk_size": s.rag_chunk_size,
        "rag_chunk_overlap": s.rag_chunk_overlap,
        "strict_knowledge_only": True,
    }
