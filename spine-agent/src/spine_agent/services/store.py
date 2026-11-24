"""工程目录：data/projects/spn_xxxxxxxx/project.json 与图片。"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from spine_agent.config import get_settings

_ID = re.compile(r"^spn_[a-f0-9]{8}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_id(project_id: str) -> bool:
    return bool(_ID.match(project_id or ""))


def projects_root() -> Path:
    root = get_settings().projects_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_dir(project_id: str) -> Path:
    if not valid_id(project_id):
        raise ValueError("工程 id 不合法")
    return projects_root() / project_id


def empty_project(title: str = "") -> dict:
    stamp = now_iso()
    return {
        "id": "spn_" + secrets.token_hex(4),
        "title": (title or "未命名").strip()[:40] or "未命名",
        "created_at": stamp,
        "updated_at": stamp,
        "stage": "new",
        "content_prompt": "",
        "skeleton_prompt": "",
        "animation_prompt": "",
        "warnings": [],
        "parts": [],
        "texture": None,
        "bones": [],
        "slots": [],
        "attachments": [],
        "animations": {},
        "spine_files": False,
    }


def save_project(directory: Path, project: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    project["updated_at"] = now_iso()
    target = directory / "project.json"
    temporary = directory / "project.json.tmp"
    temporary.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_project(project_id: str) -> dict:
    path = project_dir(project_id) / "project.json"
    if not path.is_file():
        raise FileNotFoundError(project_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_projects() -> list[dict]:
    rows = []
    root = projects_root()
    for path in root.glob("spn_*/project.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            {
                "id": data.get("id"),
                "title": data.get("title"),
                "stage": data.get("stage"),
                "updated_at": data.get("updated_at"),
            }
        )
    rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return rows


def view(project: dict) -> dict:
    """给前端和 MCP 的公开字段。图片用 URL，不把像素塞进 JSON。"""
    project_id = project["id"]
    base = f"/api/projects/{project_id}"
    stage = project.get("stage") or "new"
    pieces = []
    if stage in {"split", "animate"}:
        pieces = [
            {"name": part["name"], "url": f"{base}/pieces/{part['name']}.png", "w": part["w"], "h": part["h"]}
            for part in project.get("parts") or []
        ]
    playback = None
    if project.get("bones") and project.get("attachments"):
        playback = {
            "texture": f"{base}/texture.png?v={project.get('updated_at', '')}",
            "texture_size": [
                (project.get("texture") or {}).get("width") or 0,
                (project.get("texture") or {}).get("height") or 0,
            ],
            "bones": [
                {
                    "name": bone["name"],
                    "parent": bone.get("parent"),
                    "x": bone.get("x") or 0,
                    "y": bone.get("y") or 0,
                    "rotation": bone.get("rotation") or 0,
                    "length": bone.get("length") or 40,
                }
                for bone in project.get("bones") or []
            ],
            "attachments": project.get("attachments") or [],
            "animations": project.get("animations") or {},
        }
    downloads = None
    if project.get("spine_files"):
        downloads = {
            "json": f"{base}/export/character.json",
            "atlas": f"{base}/export/character.atlas",
            "texture": f"{base}/export/texture.png",
            "zip": f"{base}/export.zip",
        }
    return {
        "id": project_id,
        "title": project.get("title"),
        "stage": stage,
        "created_at": project.get("created_at"),
        "updated_at": project.get("updated_at"),
        "content_prompt": project.get("content_prompt") or "",
        "skeleton_prompt": project.get("skeleton_prompt") or "",
        "animation_prompt": project.get("animation_prompt") or "",
        "warnings": project.get("warnings") or [],
        "parts": [
            {
                "name": part["name"],
                "shape": part["shape"],
                "w": part["w"],
                "h": part["h"],
                "fill": part["fill"],
                "pivot": part["pivot"],
                "layer": part["layer"],
                "x": part["x"],
                "y": part["y"],
            }
            for part in project.get("parts") or []
        ],
        "texture": project.get("texture"),
        "texture_url": f"{base}/texture.png?v={project.get('updated_at', '')}" if project.get("texture") else None,
        "assembled_url": f"{base}/assembled.png?v={project.get('updated_at', '')}" if project.get("texture") else None,
        "pieces": pieces,
        "bones": project.get("bones") or [],
        "slots": project.get("slots") or [],
        "animations": list((project.get("animations") or {}).keys()),
        "playback": playback,
        "downloads": downloads,
    }
