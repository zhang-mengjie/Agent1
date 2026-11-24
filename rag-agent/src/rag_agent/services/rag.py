"""向量知识库服务。

【初学者 · 目的】
RAG = 检索增强生成：先从库里取出相关片段，再让 LLM 只依据片段回答，减少胡编。

流程：
1. init_vector_schema —— 建 rag_chunks 表（维度变了会 DROP 重建）
2. ingest_texts       —— 切分 + embedding + INSERT
3. retrieve           —— 按余弦距离排序，再用 RAG_MAX_DISTANCE 过滤

【易错点】
1. IVFFlat 在「数据很少」时近似检索可能返回 0 行 → 演示默认精确扫表，勿急着建空索引。
2. embedding 字符串要写成 `[0.1,0.2,...]` 再 CAST AS vector；格式错会 SQL 失败。
3. 换模型维度后旧向量不可用：本文件会检测 format_type 不一致并重建表（开发环境会丢数据）。
4. retrieve 用同步引擎：简单可靠；别在超高并发路径阻塞太久（演示可忽略）。
5. distance 是「距离」不是「相似度」：越大越不像；过滤条件是 `>` max_distance 丢弃。
"""

from __future__ import annotations

import json

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text
from sqlalchemy.engine import create_engine

from rag_agent.config import get_settings
from rag_agent.services.llm import build_embeddings


def _embedding_dims() -> int:
    return get_settings().embedding_dims


def _sync_engine():
    return create_engine(get_settings().database_url_sync, pool_pre_ping=True)


def _table_embedding_type(conn) -> str | None:
    row = conn.execute(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
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
    dims = _embedding_dims()
    # ivfflat 在空表上建索引可能失败；索引失败时仍保留表结构
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        existing = _table_embedding_type(conn)
        expected = f"vector({dims})"
        if existing and existing != expected:
            # 维度变更时重建表（开发环境常见：从 OpenAI 1536 切到本地 512）
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
        # 注意：小数据量下 IVFFlat 近似检索可能返回 0 行。
        # 简易演示默认走精确顺序扫描；数据量大时再手动建索引。
        conn.execute(text("DROP INDEX IF EXISTS rag_chunks_embedding_idx"))
    engine.dispose()


def list_chunks(*, limit: int = 50, offset: int = 0, source: str | None = None) -> list[dict]:
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
                SELECT
                    id,
                    content,
                    metadata,
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
                FROM rag_chunks
                GROUP BY 1
                ORDER BY count DESC
                """
            )
        ).mappings().all()
        sample_dims = conn.execute(
            text(
                """
                SELECT vector_dims(embedding) AS dims
                FROM rag_chunks
                WHERE embedding IS NOT NULL
                LIMIT 1
                """
            )
        ).scalar()
    engine.dispose()
    return {
        "total_chunks": int(total or 0),
        "vectorized_chunks": int(vectorized or 0),
        "embedding_dims": int(sample_dims or 0),
        "sources": [
            {"source": row["source"], "count": int(row["count"])} for row in sources
        ],
    }


def ingest_texts(
    texts: list[str],
    *,
    source: str = "manual",
    metadatas: list[dict] | None = None,
) -> int:
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
        docs.extend(splitter.create_documents([raw], metadatas=[meta]))

    if not docs:
        return 0

    vectors = embeddings.embed_documents([d.page_content for d in docs])
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
    settings = get_settings()
    k = top_k or settings.rag_top_k
    embeddings = build_embeddings()
    qvec = embeddings.embed_query(query)
    emb_literal = "[" + ",".join(str(x) for x in qvec) + "]"

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
        ).mappings().all()
    engine.dispose()

    result: list[Document] = []
    for row in rows:
        distance = float(row["distance"]) if row["distance"] is not None else 999.0
        if distance > settings.rag_max_distance:
            continue
        meta = row["metadata"]
        if not isinstance(meta, dict):
            meta = json.loads(meta or "{}")
        meta = {**meta, "distance": distance}
        result.append(Document(page_content=row["content"], metadata=meta))
    return result


def format_context(docs: list[Document]) -> str:
    if not docs:
        return ""
    parts = []
    for i, doc in enumerate(docs, start=1):
        src = doc.metadata.get("source", "unknown")
        parts.append(f"[{i}] (source={src})\n{doc.page_content}")
    return "\n\n".join(parts)
