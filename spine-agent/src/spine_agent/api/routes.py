"""HTTP：三步制作，以及贴图 / 碎图 / Spine 文件下载。"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from spine_agent.agent import get_project, list_all, run_animate, run_split, run_texture
from spine_agent.config import get_settings
from spine_agent.schemas import CreateProjectRequest, PromptRequest
from spine_agent.services.store import empty_project, project_dir, save_project, valid_id, view

router = APIRouter()
_PIECE = re.compile(r"^[a-z][a-z0-9_]{0,31}\.png$")


def _dir(project_id: str) -> Path:
    if not valid_id(project_id):
        raise HTTPException(status_code=404, detail="工程不存在")
    directory = project_dir(project_id)
    if not (directory / "project.json").is_file():
        raise HTTPException(status_code=404, detail="工程不存在")
    return directory


async def _guard(coro):
    try:
        return await coro
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="工程不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"生成失败：{exc}") from exc


@router.get("/health", tags=["system"])
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "llm_configured": bool(settings.llm_api_key.strip()),
        "llm_model": settings.llm_model,
        "image_configured": bool(settings.image_api_key.strip()),
        "image_model": settings.image_model,
        "spine": settings.spine_version,
    }


@router.get("/api/projects", tags=["project"])
async def list_projects() -> dict:
    return {"projects": list_all()}


@router.post("/api/projects", tags=["project"])
async def create_project(body: CreateProjectRequest) -> dict:
    project = empty_project(body.title)
    directory = project_dir(project["id"])
    save_project(directory, project)
    return view(project)


@router.get("/api/projects/{project_id}", tags=["project"])
async def read_project(project_id: str) -> dict:
    _dir(project_id)
    try:
        return get_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="工程不存在") from exc


@router.post("/api/projects/{project_id}/texture", tags=["spine"])
async def step_texture(project_id: str, body: PromptRequest) -> dict:
    _dir(project_id)
    return await _guard(run_texture(project_id, body.prompt, body.offline))


@router.post("/api/projects/{project_id}/split", tags=["spine"])
async def step_split(project_id: str, body: PromptRequest) -> dict:
    _dir(project_id)
    return await _guard(run_split(project_id, body.prompt, body.offline))


@router.post("/api/projects/{project_id}/animate", tags=["spine"])
async def step_animate(project_id: str, body: PromptRequest) -> dict:
    _dir(project_id)
    return await _guard(run_animate(project_id, body.prompt, body.offline))


def _file(directory: Path, name: str, media: str) -> FileResponse:
    path = directory / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"还没有 {name}")
    return FileResponse(path, media_type=media, filename=name)


@router.get("/api/projects/{project_id}/texture.png", tags=["files"])
async def texture_png(project_id: str) -> FileResponse:
    return _file(_dir(project_id), "texture.png", "image/png")


@router.get("/api/projects/{project_id}/assembled.png", tags=["files"])
async def assembled_png(project_id: str) -> FileResponse:
    return _file(_dir(project_id), "assembled.png", "image/png")


@router.get("/api/projects/{project_id}/pieces/{filename}", tags=["files"])
async def piece_png(project_id: str, filename: str) -> FileResponse:
    if not _PIECE.match(filename):
        raise HTTPException(status_code=404, detail="碎图不存在")
    directory = _dir(project_id)
    path = (directory / "pieces" / filename).resolve()
    if path.parent != (directory / "pieces").resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="碎图不存在")
    return FileResponse(path, media_type="image/png", filename=filename)


@router.get("/api/projects/{project_id}/export/character.json", tags=["files"])
async def export_json(project_id: str) -> FileResponse:
    return _file(_dir(project_id), "character.json", "application/json")


@router.get("/api/projects/{project_id}/export/character.atlas", tags=["files"])
async def export_atlas(project_id: str) -> FileResponse:
    return _file(_dir(project_id), "character.atlas", "text/plain")


@router.get("/api/projects/{project_id}/export/texture.png", tags=["files"])
async def export_texture(project_id: str) -> FileResponse:
    return _file(_dir(project_id), "texture.png", "image/png")


@router.get("/api/projects/{project_id}/export.zip", tags=["files"])
async def export_zip(project_id: str) -> Response:
    directory = _dir(project_id)
    if not (directory / "character.json").is_file():
        raise HTTPException(status_code=404, detail="还没有 Spine 文件，请先完成拆图")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("character.json", "character.atlas", "texture.png"):
            archive.write(directory / name, arcname=name)
        pieces = directory / "pieces"
        if pieces.is_dir():
            for piece in sorted(pieces.glob("*.png")):
                archive.write(piece, arcname=f"pieces/{piece.name}")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project_id}.zip"'},
    )
