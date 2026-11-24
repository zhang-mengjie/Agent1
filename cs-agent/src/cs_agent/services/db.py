"""异步 PostgreSQL：对话回合长期存储。

【初学者 · 目的】比 rag 多存 intent / need_human，方便质检「为何转人工」。
【易错点】端口 5433；create_all 不加列——改表结构后开发环境常需重建容器卷。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator  # Python 标准库：异步生成器类型，用于标注依赖注入的 yield 函数
from datetime import datetime  # Python 标准库：日期时间类型，用于标注 created_at 字段

from sqlalchemy import (  # SQLAlchemy Core：列类型与 SQL 表达式
    Boolean,  # 列类型：布尔值
    DateTime,  # 列类型：日期时间
    Integer,  # 列类型：整数
    String,  # 列类型：定长字符串
    Text,  # 列类型：长文本
    func,  # SQL 函数构造器：func.now() 对应数据库 NOW()
    text,  # 构造原生 SQL 语句（如 CREATE EXTENSION、SELECT 1）
)
from sqlalchemy.ext.asyncio import (  # SQLAlchemy asyncio：异步 ORM 支撑
    AsyncSession,  # 异步会话：执行 ORM 增删查改
    async_sessionmaker,  # 异步会话工厂：批量创建会话
    create_async_engine,  # 创建异步数据库引擎（asyncpg 驱动）
)
from sqlalchemy.orm import (  # SQLAlchemy ORM：声明式模型
    DeclarativeBase,  # 声明式基类：所有模型的根，承载 metadata
    Mapped,  # 类型标注：声明字段映射到表列
    mapped_column,  # 字段定义：配置列类型、主键、索引、默认值等
)

from cs_agent.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类，所有 ORM 模型继承它以统一 metadata。"""


class ConversationTurn(Base):
    """一轮用户或助手消息，对应表 ``conversation_turns``。

    比通用 rag 项目多存 intent / need_human，方便质检「为何转人工」。

    Attributes:
        id: 自增主键。
        session_id: 会话 ID，建索引以加速按会话查询。
        role: 角色，user 或 assistant。
        content: 消息正文。
        model: 生成该消息的模型名，可为空。
        used_rag: 该轮是否使用了 RAG。
        intent: 识别到的意图标签，可为空。
        need_human: 该轮是否建议转人工。
        customer_id: 客户标识，可为空。
        created_at: 入库时间，由数据库服务端生成（带时区）。
    """

    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    used_rag: Mapped[bool] = mapped_column(Boolean, default=False)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    need_human: Mapped[bool] = mapped_column(Boolean, default=False)
    customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """初始化对话数据库：确保 pgvector 扩展存在并按 ORM 模型建表。

    Note:
        ``Base.metadata.create_all`` 只建缺失的表，不会修改已有表结构；
        改动模型字段后开发环境通常需要删除容器卷重建。
    """
    async with engine.begin() as conn:  # SQLAlchemy：开启事务，退出时自动提交/回滚
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))  # 执行原生 SQL：创建 pgvector 扩展
        await conn.run_sync(Base.metadata.create_all)  # SQLAlchemy：把同步的建表操作放到线程池执行


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：为每个请求提供一个异步数据库会话，退出时自动关闭。

    Yields:
        AsyncSession: 绑定到当前请求的会话，供路由/agent 层执行 ORM 操作。
    """
    async with SessionLocal() as session:
        yield session


async def ping_db() -> bool:
    """探活：尝试连接数据库并执行 ``SELECT 1``。

    Returns:
        bool: 可连通返回 True，任何异常返回 False（供 /health 使用）。
    """
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
    intent: str | None = None,
    need_human: bool = False,
    customer_id: str | None = None,
) -> None:
    """追加一轮对话到 ``conversation_turns`` 表并提交。

    Args:
        session: 异步会话，由请求层提供。
        session_id: 会话 ID。
        role: 角色，user 或 assistant。
        content: 消息正文。
        model: 使用/生成该消息的模型名，可为空。
        used_rag: 该轮是否使用 RAG，默认 False。
        intent: 意图标签，可为空。
        need_human: 是否建议转人工，默认 False。
        customer_id: 客户标识，可为空。
    """
    session.add(  # SQLAlchemy：把新 ORM 对象加入会话（此时还未写库）
        ConversationTurn(
            session_id=session_id,
            role=role,
            content=content,
            model=model,
            used_rag=used_rag,
            intent=intent,
            need_human=need_human,
            customer_id=customer_id,
        )
    )
    await session.commit()  # SQLAlchemy：提交事务，真正执行 INSERT 落库
