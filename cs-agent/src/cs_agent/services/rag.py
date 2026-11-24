"""FAQ / 政策知识库：切分 → embedding → pgvector 存储与检索。

【初学者 · 目的】与 rag-agent/services/rag.py 同构，对照阅读即可理解「复制项目改端口」。

【易错点】
1. 小数据量不要建 IVFFlat，空索引近似检索可能 0 行。
2. EMBEDDING_DIMS 与模型不一致会建错列或检索炸。
3. collection_name 只是逻辑名；真正表名仍是 rag_chunks（三项目各自库内同表名没关系）。
"""

from __future__ import annotations

import json  # Python 标准库：JSON 序列化与反序列化，用于解析/生成切片 metadata

from langchain_core.documents import Document  # LangChain Core：文档对象，统一封装 page_content 与 metadata
from langchain_text_splitters import (  # LangChain：文本切分器
    RecursiveCharacterTextSplitter,  # 按字符递归切分长文本（按 chunk_size / chunk_overlap）
)
from sqlalchemy import text  # SQLAlchemy Core：构造原生 SQL（DDL、向量检索、统计）
from sqlalchemy.engine import create_engine  # SQLAlchemy：创建同步数据库引擎（psycopg 驱动）

from cs_agent.config import get_settings
from cs_agent.services.llm import build_embeddings


def _embedding_dims() -> int:
    """从配置读取当前 embedding 向量维度。"""
    return get_settings().embedding_dims


def _sync_engine():
    """创建同步 SQLAlchemy 引擎，供原生 SQL（DDL/向量读写）使用。"""
    return create_engine(get_settings().database_url_sync, pool_pre_ping=True)


def _table_embedding_type(conn) -> str | None:
    """查询 ``rag_chunks.embedding`` 列当前的数据库类型字符串（如 vector(512)）。

    Args:
        conn: 已连接的同步连接。

    Returns:
        str | None: 形如 "vector(512)" 的类型字符串；列不存在时返回 None。
    """
    row = conn.execute(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = 'rag_chunks'
              AND a.attname = 'embedding'
              AND a.attnum > 0
              AND NOT a.attisdropped
            LIMIT 1
            """
        )
    ).scalar()
    return str(row) if row else None


def init_vector_schema() -> None:
    """初始化向量表：确保 pgvector 扩展存在并按配置维度创建 ``rag_chunks``。

    若已有 embedding 列维度与配置不一致（如模型更换），会 ``DROP TABLE ... CASCADE``
    后重建，以免检索时报维度不匹配；同时删除旧向量索引（小数据量不用 IVFFlat）。

    Note:
        ``collection_name`` 仅是逻辑名，真实表名恒为 ``rag_chunks``。
    """
    dims = _embedding_dims()
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        existing = _table_embedding_type(conn)
        expected = f"vector({dims})"
        if existing and existing != expected:
            conn.execute(text("DROP TABLE IF EXISTS rag_chunks CASCADE"))
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id BIGSERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding vector({dims}) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(text("DROP INDEX IF EXISTS rag_chunks_embedding_idx"))
    engine.dispose()


def list_chunks(*, limit: int = 50, offset: int = 0, source: str | None = None) -> list[dict]:
    """分页列出知识库切片，按 id 倒序（最新在前）。

    Args:
        limit: 返回条数上限。
        offset: 分页偏移量。
        source: 按 metadata 中的 source 过滤；None 表示不过滤。

    Returns:
        list[dict]: 每项含 id、content、metadata、source、embedding_dims、
            vectorized、created_at（ISO 字符串或 None）。
    """
    engine = _sync_engine()
    clauses = []
    params: dict = {"limit": limit, "offset": offset}
    if source:
        clauses.append("metadata->>'source' = :source")
        params["source"] = source
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT id, content, metadata,
                       vector_dims(embedding) AS embedding_dims,
                       (embedding IS NOT NULL) AS vectorized,
                       created_at
                FROM rag_chunks
                {where}
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    engine.dispose()

    items: list[dict] = []
    for row in rows:
        meta = row["metadata"]
        if not isinstance(meta, dict):
            meta = json.loads(meta or "{}")
        items.append(
            {
                "id": row["id"],
                "content": row["content"],
                "metadata": meta,
                "source": meta.get("source", "unknown"),
                "embedding_dims": int(row["embedding_dims"] or 0),
                "vectorized": bool(row["vectorized"]),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        )
    return items


def get_chunk_stats() -> dict:
    """统计知识库切片概况。

    Returns:
        dict: total_chunks（总数）、vectorized_chunks（非空向量数）、
            embedding_dims（样本向量维度，空库为 0）、
            sources（按来源分组的 {"source", "count"} 列表）。
    """
    engine = _sync_engine()
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM rag_chunks")).scalar_one()
        vectorized = conn.execute(
            text("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        ).scalar_one()
        sources = conn.execute(
            text(
                """
                SELECT COALESCE(metadata->>'source', 'unknown') AS source, COUNT(*) AS count
                FROM rag_chunks GROUP BY 1 ORDER BY count DESC
                """
            )
        ).mappings().all()
        sample_dims = conn.execute(
            text(
                "SELECT vector_dims(embedding) FROM rag_chunks WHERE embedding IS NOT NULL LIMIT 1"
            )
        ).scalar()
    engine.dispose()
    return {
        "total_chunks": int(total or 0),
        "vectorized_chunks": int(vectorized or 0),
        "embedding_dims": int(sample_dims or 0),
        "sources": [{"source": r["source"], "count": int(r["count"])} for r in sources],
    }


def ingest_texts(
    texts: list[str],
    *,
    source: str = "faq",
    metadatas: list[dict] | None = None,
) -> int:
    """切分文本 → 本地/远程向量化 → 写入 ``rag_chunks`` 表。

    每条输入文本经 ``RecursiveCharacterTextSplitter`` 按配置大小与重叠切分，
    为每块生成 embedding 后以字符串形式 CAST 为 vector 落库。

    Args:
        texts: 待入库文本列表，每条独立切分。
        source: 来源标签，写入每条切片的 metadata，默认 "faq"。
        metadatas: 与 texts 一一对应的额外元数据；提供时长度须一致，
            会合并到默认 metadata（source 与 doc_index）中。

    Returns:
        int: 实际写入的切片数；文本为空返回 0。

    Raises:
        ValueError: metadatas 与 texts 长度不一致时由调用方校验；
            向量化/写库异常会向上抛出。
    """
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    embeddings = build_embeddings()
    docs: list[Document] = []
    for i, raw in enumerate(texts):
        meta = {"source": source, "doc_index": i}
        if metadatas and i < len(metadatas):
            meta.update(metadatas[i])
        docs.extend(splitter.create_documents([raw], metadatas=[meta]))  # LangChain：切分文本并生成 Document 列表
    if not docs:
        return 0

    vectors = embeddings.embed_documents([d.page_content for d in docs])  # LangChain：批量把多段文本向量化
    engine = _sync_engine()
    with engine.begin() as conn:
        for doc, vec in zip(docs, vectors, strict=True):
            conn.execute(
                text(
                    """
                    INSERT INTO rag_chunks (content, metadata, embedding)
                    VALUES (:content, CAST(:metadata AS jsonb), CAST(:embedding AS vector))
                    """
                ),
                {
                    "content": doc.page_content,
                    "metadata": json.dumps(doc.metadata, ensure_ascii=False),
                    "embedding": "[" + ",".join(str(x) for x in vec) + "]",
                },
            )
    engine.dispose()
    return len(docs)


def retrieve(query: str, top_k: int | None = None) -> list[Document]:
    """语义检索：把查询向量化后按余弦距离查找最相似的 FAQ 切片。

    使用 pgvector 的 ``<=>`` 运算符排序，并过滤掉距离超过
    ``rag_max_distance`` 的结果；未建向量索引，小数据量下全表精确检索。

    Args:
        query: 用户查询文本。
        top_k: 返回条数；None 时用配置 rag_top_k。

    Returns:
        list[Document]: 命中的文档，metadata 额外含 distance（余弦距离）；
            全部超阈值时返回空列表。
    """
    settings = get_settings()
    k = top_k or settings.rag_top_k
    qvec = build_embeddings().embed_query(query)  # LangChain：把单条查询文本向量化
    emb_literal = "[" + ",".join(str(x) for x in qvec) + "]"  # 转为 pgvector 接受的字面量格式 [x,y,...]
    engine = _sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT content, metadata,
                       embedding <=> CAST(:embedding AS vector) AS distance
                FROM rag_chunks
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :k
                """
            ),
            {"embedding": emb_literal, "k": k},
        ).mappings().all()  # SQLAlchemy：执行并把每行结果转为可按列名取值的字典
    engine.dispose()

    result: list[Document] = []
    for row in rows:
        distance = float(row["distance"]) if row["distance"] is not None else 999.0
        if distance > settings.rag_max_distance:
            continue
        meta = row["metadata"]
        if not isinstance(meta, dict):
            meta = json.loads(meta or "{}")
        result.append(Document(page_content=row["content"], metadata={**meta, "distance": distance}))
    return result


def format_context(docs: list[Document]) -> str:
    """把检索到的文档拼成供 LLM 阅读的知识库摘录文本。

    Args:
        docs: 检索命中的文档列表。

    Returns:
        str: 形如 ``[1] (source=xxx)\\n内容`` 的多段文本，段间空行分隔；
            空列表返回空字符串。
    """
    if not docs:
        return ""
    parts = []
    for i, doc in enumerate(docs, start=1):
        src = doc.metadata.get("source", "unknown")
        parts.append(f"[{i}] (source={src})\n{doc.page_content}")
    return "\n\n".join(parts)
