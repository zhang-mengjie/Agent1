"""FastAPI 入口：财务审批 Agent。

【初学者 · 目的】与 rag/cs 同构的 create_app + lifespan。
【易错点】先 docker compose（5434/6381）再起 uvicorn :8003；改 .env 要重启。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from finance_agent.api import router
from finance_agent.config import get_settings
from finance_agent.services.db import init_db
from finance_agent.services.rag import init_vector_schema
from finance_agent.services.redis_memory import memory

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await memory.connect()
    except Exception as exc:
        print(f"[finance-agent] Redis 连接失败: {exc}")
    try:
        await init_db()
    except Exception as exc:
        print(f"[finance-agent] Postgres 初始化失败（检查 5434）: {exc}")
    try:
        init_vector_schema()
    except Exception as exc:
        print(f"[finance-agent] 向量表初始化跳过: {exc}")
    yield
    try:
        await memory.close()
    except Exception:
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="企业财务审批 Agent：报销结构化→制度检索→标准/预算→风险→动态审批→ERP",
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
        "finance_agent.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "dev",
    )


if __name__ == "__main__":
    run()
