"""FastAPI 入口。

【初学者 · 目的】
与 rag-agent 相同骨架；lifespan 对 Redis/PG 失败「打印警告但不崩」，
方便你先打开前端，再补 docker compose。

启动顺序：
1. Redis  2. 对话表  3. 向量表（失败不阻断）

【易错点】
1. ConnectionRefused 5433 → 先在本目录 docker compose up -d。
2. Windows 勿用 uv run 锁 exe；用 venv python -m uvicorn。
3. soft-fail 意味着 /health 可能 postgres=false，业务接口仍会在真正用库时报错。
"""

from __future__ import annotations

from contextlib import asynccontextmanager  # Python 标准库：把异步生成器装饰为 async with 上下文管理器（用于 lifespan）
from pathlib import Path  # Python 标准库：文件路径操作，此处拼接 static 目录绝对路径

import uvicorn  # ASGI 服务器：启动并运行 FastAPI 应用（HTTP 服务）
from fastapi import FastAPI  # FastAPI 主类：创建 Web 应用、注册路由与生命周期
from fastapi.responses import FileResponse  # FastAPI 响应类：把本地文件作为 HTTP 响应返回（此处返回 index.html）
from fastapi.staticfiles import StaticFiles  # FastAPI 工具：把一个目录挂载为静态资源路由（/static）

from cs_agent.api import router
from cs_agent.config import get_settings
from cs_agent.services.db import init_db
from cs_agent.services.rag import init_vector_schema
from cs_agent.services.redis_memory import memory

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期：启动时初始化基础设施，关闭时释放资源。

    启动顺序：Redis 连接 → 对话表 → 向量表；每步失败只打印警告不阻断进程，
    便于先打开前端再补 docker compose，真实状态由 /health 反映。
    退出时尝试关闭 Redis 连接。

    Args:
        _app: 当前 FastAPI 应用实例（未使用）。
    """
    # 基础设施未就绪时不阻断进程，便于先起 HTTP；/health 会反映真实状态
    try:
        await memory.connect()
    except Exception as exc:
        print(f"[cs-agent] Redis 连接失败（可稍后 docker compose up -d）: {exc}")
    try:
        await init_db()
    except Exception as exc:
        print(f"[cs-agent] Postgres 初始化失败（检查 5433 是否已启动）: {exc}")
    try:
        init_vector_schema()
    except Exception as exc:
        print(f"[cs-agent] 向量表初始化跳过: {exc}")
    yield
    try:
        await memory.close()
    except Exception:
        pass



def create_app() -> FastAPI:
    """构造并装配 FastAPI 应用。

    Returns:
        FastAPI: 已挂载 API 路由、静态目录 /static，并注册根路径返回前端 index.html
            的应用实例；生命周期由 ``lifespan`` 管理。
    """
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="企业客服 Agent：FAQ RAG + 意图识别 + 转人工建议",
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
    """以 uvicorn 启动 HTTP 服务（供 ``python -m cs_agent`` 与 cs-agent 命令调用）。

    监听地址/端口取自配置；app_env 为 "dev" 时开启 reload。
    等价于：python -m uvicorn cs_agent.main:app --app-dir src --port 8002
    """
    settings = get_settings()
    # 推荐用：.venv\\Scripts\\python.exe -m uvicorn cs_agent.main:app --app-dir src --port 8002
    uvicorn.run(  # uvicorn：以 ASGI 方式启动 HTTP 服务，字符串为 app 的导入路径
        "cs_agent.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "dev",
    )


if __name__ == "__main__":
    run()
