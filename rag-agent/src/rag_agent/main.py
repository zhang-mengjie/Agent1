"""FastAPI 应用入口。

【初学者 · 目的】
- 把「路由 + 静态页 + 启停钩子」组装成一个 ASGI app，交给 uvicorn。
- lifespan：服务对外前先连 Redis/建表，退出时关闭连接。

【易错点】
1. Windows 用 `uv run rag-agent` 易锁 Scripts\\rag-agent.exe，改代码后无法覆盖。
   推荐：`python -m uvicorn rag_agent.main:app --reload --port 8001`（需 PYTHONPATH=src）。
2. 静态目录挂在 /static，首页单独 `/`；只开静态文件服务器没有 API。
3. init_vector_schema 失败被吞掉是为了「库未起也能看 /docs」——真正入库前仍要起 Postgres。
4. reload 只监视代码；改 .env 仍需手动重启或 reload_settings。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from rag_agent.api import router
from rag_agent.config import get_settings
from rag_agent.services.db import init_db
from rag_agent.services.rag import init_vector_schema
from rag_agent.services.redis_memory import memory

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用启停钩子：先连基础设施，再对外服务。"""
    await memory.connect()
    await init_db()
    try:
        init_vector_schema()
    except Exception:
        # Postgres 未就绪时仍允许启动，便于先看 /docs 与前端
        pass
    yield
    await memory.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Python + FastAPI + Pydantic + PostgreSQL + Redis + LangChain + RAG",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "rag_agent.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "dev",
    )


if __name__ == "__main__":
    run()
