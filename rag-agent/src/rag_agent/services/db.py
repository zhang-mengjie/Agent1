"""异步 Postgres：对话回合长期落库。

【初学者 · 目的】
Redis 记「最近几轮」；这里记「完整历史」，方便排查 used_rag / 用了哪个模型。

【易错点】
1. DATABASE_URL 必须是 postgresql+asyncpg://…… 同步向量写入另用 psycopg。
2. create_all 只建缺表，不会改已有列——改模型后开发环境常要手工迁移或删库重建。
3. get_session 是依赖注入生成器：路由里用 Depends，不要自己忘记 close。
"""

from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rag_agent.config import get_settings


class Base(DeclarativeBase):
    pass


class ConversationTurn(Base):
    """对话回合落库（长期记录）。"""

    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    used_rag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def ping_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def save_turn(
    session: AsyncSession,
    *,
    session_id: str,
    role: str,
    content: str,
    model: str | None = None,
    used_rag: bool = False,
) -> None:
    session.add(
        ConversationTurn(
            session_id=session_id,
            role=role,
            content=content,
            model=model,
            used_rag=used_rag,
        )
    )
    await session.commit()


async def list_recent_turns(
    session: AsyncSession, session_id: str, limit: int = 20
) -> list[ConversationTurn]:
    stmt = (
        select(ConversationTurn)
        .where(ConversationTurn.session_id == session_id)
        .order_by(ConversationTurn.id.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(reversed(rows))
