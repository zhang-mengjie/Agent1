"""HTTP 路由：健康检查、客服对话、FAQ 入库/查询。

【初学者 · 目的】HTTP 外壳与 rag-agent 几乎一样，便于对照学习「同构项目差在 agent 层」。

【易错点】
1. /chat 返回里关注 need_human / intent，前端应展示「建议转人工」。
2. 探活 postgres=false 时仍可能 200 打开页面——先看 /health 再抱怨「问答失败」。
"""

from __future__ import annotations

from fastapi import (  # FastAPI：Web 框架核心组件
    APIRouter,  # 路由分组器：把一组相关接口组织在一起再挂到 app
    Depends,  # 依赖注入：声明接口参数由容器提供（如数据库会话）
    File,  # 参数声明：标记该参数为 multipart 上传文件
    Form,  # 参数声明：标记该参数来自表单字段
    HTTPException,  # 异常类：抛出后由 FastAPI 转为带状态码的 HTTP 错误响应
    Query,  # 参数声明：标记该参数来自 URL 查询串，并可设校验规则
    UploadFile,  # 上传文件对象：封装文件名、字节流等
)
from sqlalchemy.ext.asyncio import AsyncSession  # SQLAlchemy：异步数据库会话类型，由 Depends 注入

from cs_agent.agent import run_agent
from cs_agent.config import get_settings, reload_settings
from cs_agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentListResponse,
    DocumentStatsResponse,
    HealthResponse,
)
from cs_agent.services.db import get_session, ping_db
from cs_agent.services.pdf_ingest import extract_pdf_text
from cs_agent.services.rag import get_chunk_stats, ingest_texts, list_chunks
from cs_agent.services.redis_memory import memory

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """服务探活：检查应用自身及 PostgreSQL / Redis 两个依赖的连通状态。

    即使依赖不可用也返回 200 + 状态字段（soft-fail 策略），因此调用方应读取
    ``postgres`` / ``redis`` 字段判断真实可用性，不要只看 HTTP 状态码。

    Returns:
        HealthResponse: status 固定为 "ok"；app 为应用名；postgres / redis
            为布尔值表示对应依赖当前是否可连通；llm_model 为当前默认 Chat 模型。
    """
    s = get_settings()
    return HealthResponse(
        status="ok",
        app=s.app_name,
        postgres=await ping_db(),
        redis=await memory.ping(),
        llm_model=s.llm_model,
    )


@router.post("/chat", response_model=AgentChatResponse, tags=["cs"])
async def chat(
    request: AgentChatRequest,
    db: AsyncSession = Depends(get_session),
) -> AgentChatResponse:
    """客服对话：意图识别 + FAQ RAG 检索 + 转人工建议。

    Args:
        request: 对话请求体，字段见 ``AgentChatRequest``：
            - message：用户问题（1~8000 字符）。
            - session_id：会话 ID；为空则新建，前端应复用返回值维持多轮上下文。
            - customer_id：可选客户标识，仅作记录。
            - use_rag：是否检索 FAQ 知识库。
            - top_k：本次检索条数（1~20），为空则用配置默认值。
            - model_params：单次请求覆盖的模型参数，未指定则用全局配置。
        db: 由 ``Depends(get_session)`` 注入的异步数据库会话，用于持久化对话轮次。

    Returns:
        AgentChatResponse: answer 为回复文本，session_id 为会话 ID，model 为所用模型，
            used_rag 表示是否检索了 FAQ，intent 为识别到的意图，need_human 表示
            是否建议转人工，sources 为命中的 FAQ 摘要。

    Raises:
        HTTPException: 400——既未在请求体也未在全局配置中提供 LLM API Key。

    Note:
        判断是否建议转人工应读取响应字段 ``need_human``，不要仅凭答句文本推断。
    """
    s = get_settings()
    if not (request.model_params.api_key or s.llm_api_key):
        raise HTTPException(status_code=400, detail="未配置 LLM_API_KEY")
    return await run_agent(request, db)


@router.post("/documents", response_model=DocumentIngestResponse, tags=["faq"])
async def ingest_documents(request: DocumentIngestRequest) -> DocumentIngestResponse:
    """文本入库：将多段文本切分、向量化后写入 pgvector 知识库表 ``rag_chunks``。

    每段文本会经 ``RecursiveCharacterTextSplitter`` 按配置大小切分，每块生成
    embedding 后落库；该过程为同步阻塞调用（FastEmbed 本地向量化）。

    Args:
        request: 入库请求体，字段见 ``DocumentIngestRequest``：
            - texts：待入库文本列表（至少 1 条），每条单独切分。
            - metadatas：与 texts 一一对应的元数据列表；提供时长度必须一致。
            - source：来源标签，如 faq / policy / 文件名，默认 "faq"。

    Returns:
        DocumentIngestResponse: ingested_chunks 为实际写入的切片数，
            collection 为逻辑集合名，source 为本次入库使用的来源标签。

    Raises:
        HTTPException: 400——非 local embedding 时未配置 API Key，或 metadatas
            长度与 texts 不一致；500——切分/向量化/写库过程出错。
    """
    s = get_settings()
    if (s.embedding_provider or "").lower() != "local" and not s.effective_embedding_api_key:
        raise HTTPException(status_code=400, detail="未配置 embedding API Key")
    if request.metadatas is not None and len(request.metadatas) != len(request.texts):
        raise HTTPException(status_code=400, detail="metadatas 长度必须与 texts 一致")
    try:
        count = ingest_texts(request.texts, source=request.source, metadatas=request.metadatas)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"入库失败: {exc}") from exc
    return DocumentIngestResponse(
        ingested_chunks=count, collection=s.collection_name, source=request.source
    )


@router.post("/documents/pdf", response_model=DocumentIngestResponse, tags=["faq"])
async def ingest_pdf(
    file: UploadFile = File(...),
    source: str | None = Form(default=None),
) -> DocumentIngestResponse:
    """PDF 入库：解析上传 PDF 的可复制文本，再走文本切分与向量化流程。

    仅支持含可复制文本的 PDF；扫描件需先 OCR。解析出的文本作为单条文档传入
    ``ingest_texts``，元数据会带上 filename 与 type=pdf。

    Args:
        file: multipart/form-data 上传的 PDF 文件，扩展名须为 .pdf、非空，
            且大小不超过 ``max_pdf_bytes``（默认 10 MiB）。
        source: 可选表单字段，来源标签；留空或纯空白时默认使用上传文件名。

    Returns:
        DocumentIngestResponse: ingested_chunks 为写入切片数，collection 为
            逻辑集合名，source 为实际使用的来源标签（入参或文件名）。

    Raises:
        HTTPException: 400——文件非 .pdf、为空、超限，或解析器抛出 ValueError
            （如无文本层）；500——其他解析/入库异常。
    """
    s = get_settings()
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 .pdf")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > s.max_pdf_bytes:
        raise HTTPException(status_code=400, detail="文件过大")
    try:
        text = extract_pdf_text(data, filename=filename)
        src = (source or "").strip() or filename
        count = ingest_texts([text], source=src, metadatas=[{"filename": filename, "type": "pdf"}])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF 入库失败: {exc}") from exc
    return DocumentIngestResponse(ingested_chunks=count, collection=s.collection_name, source=src)


@router.get("/documents", response_model=DocumentListResponse, tags=["faq"])
async def list_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: str | None = None,
) -> DocumentListResponse:
    """分页查询已入库的文本切片（按 id 倒序，最新在前）。

    Args:
        limit: 每页返回条数，范围 1~200，默认 50。
        offset: 分页偏移量，从 0 开始，默认 0。
        source: 按来源标签精确过滤（匹配 metadata->>'source'）；None 表示不过滤。

    Returns:
        DocumentListResponse: total_returned 为本次返回条数（非表内总行数），
            items 为切片列表，含 id、content、source、metadata、向量维度、
            是否已向量化、创建时间等字段。

    Raises:
        HTTPException: 500——查询数据库出错。
    """
    try:
        items = list_chunks(limit=limit, offset=offset, source=source)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc
    return DocumentListResponse(total_returned=len(items), items=items)


@router.get("/documents/stats", response_model=DocumentStatsResponse, tags=["faq"])
async def documents_stats() -> DocumentStatsResponse:
    """知识库统计：切片总数、已向量化数、向量维度及按来源的分布。

    向量维度取自任一条已向量化记录，空库或未向量化时为 0。

    Returns:
        DocumentStatsResponse: total_chunks 为切片总数，vectorized_chunks 为
            非空向量数，embedding_dims 为样本向量维度，sources 为按来源分组的
            计数列表，collection 为逻辑集合名。

    Raises:
        HTTPException: 500——统计查询出错。
    """
    s = get_settings()
    try:
        stats = get_chunk_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"统计失败: {exc}") from exc
    return DocumentStatsResponse(
        total_chunks=stats["total_chunks"],
        vectorized_chunks=stats["vectorized_chunks"],
        embedding_dims=stats["embedding_dims"],
        sources=stats["sources"],
        collection=s.collection_name,
    )


@router.get("/config/model", tags=["system"])
async def get_model_config() -> dict:
    """返回当前生效的 LLM / embedding / RAG / 客服策略配置（只读）。

    注意：此接口调用 ``reload_settings()`` 清除配置缓存后重新读取 .env，
    因此会拿到最新配置，而应用其余接口使用 ``get_settings()`` 的缓存值，
    两者在运行时修改 .env 后可能短暂不一致。

    Returns:
        dict: 包含 llm 的 model/temperature/max_tokens/top_p/base_url，
            embedding 的 provider/model/dims，RAG 的 top_k/max_distance，
            以及 escalate_after_misses、company_name、strict_knowledge_only 等。
    """
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
        "escalate_after_misses": s.escalate_after_misses,
        "company_name": s.company_name,
        "strict_knowledge_only": True,
    }
