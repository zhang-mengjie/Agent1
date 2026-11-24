"""FastAPI 入口。工程写在 data/projects/，不连接数据库。"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from spine_agent.api import router
from spine_agent.config import get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Spine 制作：描述生成贴图，按骨骼切碎图，导出 Spine 4.1 并预览",
        version="0.1.0",
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
        "spine_agent.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "dev",
    )


if __name__ == "__main__":
    run()
