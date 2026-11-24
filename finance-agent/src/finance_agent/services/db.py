"""异步 Postgres：报销单与对话落库。

【初学者 · 目的】expense_records 是审批台账；conversation_turns 是制度问答审计。
【易错点】
1. create_all 不改旧列；审批字段用 ALTER IF NOT EXISTS 兼容已有库。
2. 端口 5434；连错库会「找不到单」或看到别的项目数据。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from finance_agent.config import get_settings


class Base(DeclarativeBase):
    pass


class ExpenseRecord(Base):
    __tablename__ = "expense_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    employee_id: Mapped[str] = mapped_column(String(64), index=True)
    employee_name: Mapped[str] = mapped_column(String(64))
    department: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text)
    invoice_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    # 票据原件：内容哈希用于「只能报一次」；path 指向磁盘原图/PDF
    receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    receipt_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    receipt_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    risk_level: Mapped[str] = mapped_column(String(16))
    erp_voucher_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    approver_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approver_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 财务手动标记是否已打款
    paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConversationTurn(Base):
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
        # 兼容已有库：补齐审批字段
        for stmt in (
            "ALTER TABLE expense_records ADD COLUMN IF NOT EXISTS approver_id VARCHAR(64)",
            "ALTER TABLE expense_records ADD COLUMN IF NOT EXISTS approver_name VARCHAR(64)",
            "ALTER TABLE expense_records ADD COLUMN IF NOT EXISTS approval_note TEXT",
            "ALTER TABLE expense_records ADD COLUMN IF NOT EXISTS receipt_hash VARCHAR(64)",
            "ALTER TABLE expense_records ADD COLUMN IF NOT EXISTS receipt_path VARCHAR(512)",
            "ALTER TABLE expense_records ADD COLUMN IF NOT EXISTS receipt_filename VARCHAR(255)",
            "ALTER TABLE expense_records ADD COLUMN IF NOT EXISTS paid BOOLEAN DEFAULT FALSE",
            "ALTER TABLE expense_records ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ",
        ):
            await conn.execute(text(stmt))
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expense_records_receipt_hash "
                "ON expense_records (receipt_hash)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expense_records_paid "
                "ON expense_records (paid)"
            )
        )


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


async def save_expense(session: AsyncSession, **kwargs) -> ExpenseRecord:
    row = ExpenseRecord(**kwargs)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


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
