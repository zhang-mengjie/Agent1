"""把三步 Spine 制作暴露给 Cursor。

启动：.venv\\Scripts\\python.exe -m spine_agent.mcp_server
不要用 uv run，避免锁住 exe。
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.mcpserver import MCPServer

from spine_agent.agent.spine_agent import get_project, list_all, run_animate, run_split, run_texture
from spine_agent.config import get_settings, reload_settings

mcp = MCPServer(
    "spine-agent",
    instructions=(
        "Spine 制作工具，按顺序调用："
        "spine_texture 根据内容描述生成一张整图；"
        "spine_split 让模型看着整图拆成部件并绑骨；"
        "spine_animate 根据动画描述写出 Spine 4.1 文件。"
        "offline=true 时使用内置橙猫，不调用语言模型。"
    ),
)


def _run(coro) -> Any:
    reload_settings()
    try:
        return asyncio.run(coro)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool(description="探活。返回模型是否已配置，以及 Spine 版本。")
def spine_health() -> dict[str, Any]:
    reload_settings()
    settings = get_settings()
    return {
        "ok": True,
        "app": settings.app_name,
        "llm_configured": bool(settings.llm_api_key.strip()),
        "llm_model": settings.llm_model,
        "image_configured": bool(settings.image_api_key.strip()),
        "image_model": settings.image_model,
        "spine": settings.spine_version,
    }


@mcp.tool(description="列出已有 Spine 工程")
def spine_list() -> dict[str, Any]:
    reload_settings()
    return {"projects": list_all()}


@mcp.tool(description="读取一个工程的阶段、部件、骨骼和下载地址")
def spine_project(project_id: str) -> dict[str, Any]:
    return _run(_project(project_id))


async def _project(project_id: str) -> dict[str, Any]:
    return get_project(project_id)


@mcp.tool(description="第 1 步：按内容描述生成贴图。project_id 可空，空则新建。offline=true 使用内置橙猫。")
def spine_texture(prompt: str, project_id: str = "", offline: bool = False) -> dict[str, Any]:
    return _run(run_texture(project_id or None, prompt, offline))


@mcp.tool(description="第 2 步：按骨骼描述把贴图切成碎图并生成骨架。需要已有 project_id。")
def spine_split(project_id: str, prompt: str, offline: bool = False) -> dict[str, Any]:
    return _run(run_split(project_id, prompt, offline))


@mcp.tool(description="第 3 步：按动画描述写出 Spine JSON、atlas，并给出预览数据。")
def spine_animate(project_id: str, prompt: str, offline: bool = False) -> dict[str, Any]:
    return _run(run_animate(project_id, prompt, offline))


def main() -> None:
    reload_settings()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
