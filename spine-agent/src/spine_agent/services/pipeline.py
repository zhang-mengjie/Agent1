"""三步流水线里不依赖模型的那一半：绘制、裁切、写 Spine 文件。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from spine_agent.config import get_settings
from spine_agent.services.animate import bake_animations
from spine_agent.services.rig import build_rig
from spine_agent.services.spine_export import write_spine_files
from spine_agent.services.image_gen import remove_flat_background, render_part_images
from spine_agent.services.texture import (
    normalize_parts,
    pack_atlas,
    part_to_dict,
    parts_from_boxes,
    parts_from_dicts,
    render_assembled,
)


def _clear_downstream(project: dict, keep_rig: bool) -> None:
    if not keep_rig:
        project["bones"] = []
        project["slots"] = []
        project["attachments"] = []
        project["spine_files"] = False
    project["animations"] = {}


def apply_texture(directory: Path, project: dict, spec: dict, *, use_image: bool | None = None) -> dict:
    parts, warnings = normalize_parts(spec.get("parts"))
    character = str(project.get("content_prompt") or spec.get("title") or "")
    images, image_warnings = render_part_images(
        parts,
        character=character,
        style=str(spec.get("style") or ""),
        use_image=use_image,
    )
    warnings.extend(image_warnings)
    atlas = pack_atlas(parts, images)
    assembled = render_assembled(parts, images)
    directory.mkdir(parents=True, exist_ok=True)
    atlas.save(directory / "texture.png")
    assembled.save(directory / "assembled.png")
    pieces_dir = directory / "pieces"
    if pieces_dir.exists():
        for old in pieces_dir.glob("*.png"):
            old.unlink()
    title = str(spec.get("title") or project.get("title") or "spine").strip()[:40]
    project["title"] = title or project.get("title") or "spine"
    project["parts"] = [part_to_dict(part) for part in parts]
    project["texture"] = {"width": atlas.width, "height": atlas.height}
    project["stage"] = "texture"
    project["warnings"] = warnings
    _clear_downstream(project, keep_rig=False)
    for name in ("character.json", "character.atlas"):
        path = directory / name
        if path.exists():
            path.unlink()
    return project


def apply_portrait(directory: Path, project: dict, image: Image.Image, title: str) -> dict:
    """第 1 步只保存整图。不满意就再生成一次，满意后再拆。"""
    directory.mkdir(parents=True, exist_ok=True)
    image = image.convert("RGBA")
    image.save(directory / "portrait.png")
    image.save(directory / "texture.png")
    image.save(directory / "assembled.png")
    pieces_dir = directory / "pieces"
    if pieces_dir.exists():
        for old in pieces_dir.glob("*.png"):
            old.unlink()
    for name in ("character.json", "character.atlas"):
        path = directory / name
        if path.exists():
            path.unlink()
    project["title"] = (title or project.get("title") or "角色").strip()[:40] or "角色"
    project["parts"] = []
    project["texture"] = {"width": image.width, "height": image.height, "kind": "portrait"}
    project["stage"] = "texture"
    project["warnings"] = ["这是整图。满意后再做第 2 步，AI 会按这张图拆成部件。"]
    project["bones"] = []
    project["slots"] = []
    project["attachments"] = []
    project["animations"] = {}
    project["spine_files"] = False
    return project


def _bones_without_coordinates(spec: dict) -> dict:
    bones = spec.get("bones")
    if not isinstance(bones, list):
        return {"bones": []}
    cleaned = []
    for item in bones:
        if not isinstance(item, dict):
            continue
        cleaned.append({"name": item.get("name"), "parent": item.get("parent"), "part": item.get("part")})
    return {"bones": cleaned}


def apply_cut(directory: Path, project: dict, portrait: Image.Image, spec: dict) -> dict:
    """按视觉模型标出的矩形，从整图裁出碎图并绑骨。"""
    portrait = portrait.convert("RGBA")
    parts, boxes, warnings = parts_from_boxes(spec.get("parts"), portrait.width, portrait.height)
    images = {
        part.name: remove_flat_background(portrait.crop((x, y, x + w, y + h)))
        for part, (x, y, w, h) in zip(parts, boxes)
    }
    atlas = pack_atlas(parts, images)
    assembled = render_assembled(parts, images)
    directory.mkdir(parents=True, exist_ok=True)
    atlas.save(directory / "texture.png")
    assembled.save(directory / "assembled.png")
    project["parts"] = [part_to_dict(part) for part in parts]
    project["texture"] = {"width": atlas.width, "height": atlas.height}
    project["warnings"] = warnings
    project = apply_rig(directory, project, _bones_without_coordinates(spec))
    project["warnings"] = warnings + list(project.get("warnings") or [])
    return project


def apply_rig(directory: Path, project: dict, spec: dict) -> dict:
    if not project.get("parts"):
        raise ValueError("还没有贴图，请先完成第 1 步")
    parts = parts_from_dicts(project["parts"])
    # normalize 会丢掉已经排好的 atlas 坐标，这里写回。
    saved = {row["name"]: row for row in project["parts"]}
    for part in parts:
        row = saved.get(part.name)
        if row:
            part.atlas_x = int(row["atlas_x"])
            part.atlas_y = int(row["atlas_y"])
            part.w = int(row["w"])
            part.h = int(row["h"])
    rig, warnings = build_rig(parts, spec)
    project["bones"] = rig["bones"]
    project["slots"] = rig["slots"]
    project["attachments"] = rig["attachments"]
    project["stage"] = "split"
    project["warnings"] = warnings
    project["animations"] = {}
    pieces_dir = directory / "pieces"
    pieces_dir.mkdir(parents=True, exist_ok=True)
    for old in pieces_dir.glob("*.png"):
        old.unlink()
    texture = Image.open(directory / "texture.png").convert("RGBA")
    for part in parts:
        crop = texture.crop((part.atlas_x, part.atlas_y, part.atlas_x + part.w, part.atlas_y + part.h))
        crop.save(pieces_dir / f"{part.name}.png")
    write_spine_files(directory, project, get_settings().spine_version)
    return project


def apply_animation(directory: Path, project: dict, spec: dict) -> dict:
    if not project.get("bones"):
        raise ValueError("还没有骨骼，请先完成第 2 步")
    animations, warnings = bake_animations(spec, project["bones"])
    project["animations"] = animations
    project["stage"] = "animate"
    project["warnings"] = warnings
    write_spine_files(directory, project, get_settings().spine_version)
    return project
