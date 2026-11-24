import sys
import traceback

sys.path.insert(0, "src")

from sqlalchemy import text

from rag_agent.services.llm import build_embeddings
from rag_agent.services.rag import _sync_engine, retrieve

qtext = "公司"
emb = build_embeddings().embed_query(qtext)
literal = "[" + ",".join(str(x) for x in emb) + "]"
print("qdims", len(emb), "literal_len", len(literal))

engine = _sync_engine()
with engine.connect() as conn:
    print("count", conn.execute(text("SELECT COUNT(*) FROM rag_chunks")).scalar())
    try:
        rows = conn.execute(
            text(
                """
                SELECT id, left(content, 40) AS content,
                       embedding <=> CAST(:embedding AS vector) AS dist
                FROM rag_chunks
                """
            ),
            {"embedding": literal},
        ).mappings().all()
        print("select dist ok", rows)
    except Exception:
        traceback.print_exc()
        conn.rollback()

    try:
        rows = conn.execute(
            text(
                """
                SELECT content, metadata
                FROM rag_chunks
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :k
                """
            ),
            {"embedding": literal, "k": 4},
        ).mappings().all()
        print("order limit ok", len(rows), rows)
    except Exception:
        traceback.print_exc()
        conn.rollback()

    # pgvector python binding
    try:
        from pgvector.psycopg import register_vector

        raw = conn.connection.driver_connection
        register_vector(raw)
        with raw.cursor() as cur:
            cur.execute(
                "SELECT id, content FROM rag_chunks ORDER BY embedding <=> %s::vector LIMIT %s",
                (emb, 4),
            )
            print("psycopg direct", cur.fetchall())
    except Exception:
        traceback.print_exc()

print("retrieve() =>", retrieve(qtext, top_k=4))
