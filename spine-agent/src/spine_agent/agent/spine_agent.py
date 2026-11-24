"""三步编排：描述 → 贴图，骨骼 → 碎图，动画 → Spine 文件。

对话模型只负责看整图拆部件、绑骨和写关键帧。第 1 步只生成一张全身图。
"""

from __future__ import annotations

from PIL import Image

from spine_agent.services import sample
from spine_agent.services.image_gen import generate_portrait, vision_payload
from spine_agent.services.llm import plan_animation, plan_cut, plan_rig
from spine_agent.services.pipeline import apply_animation, apply_cut, apply_portrait, apply_rig, apply_texture
from spine_agent.services.store import (
    empty_project,
    list_projects,
    load_project,
    project_dir,
    save_project,
    view,
)


def list_all() -> list[dict]:
    return list_projects()


def get_project(project_id: str) -> dict:
    return view(load_project(project_id))


def _cat_parts_present(project: dict) -> bool:
    names = {part["name"] for part in project.get("parts") or []}
    needed = {bone["part"] for bone in sample.rig_spec()["bones"] if bone.get("part")}
    return needed <= names


async def run_texture(project_id: str | None, prompt: str, offline: bool) -> dict:
    text = prompt.strip()
    if not offline and not text:
        raise ValueError("请填写角色描述，或改用内置示例")
    if project_id:
        project = load_project(project_id)
        directory = project_dir(project_id)
    else:
        project = empty_project()
        directory = project_dir(project["id"])
    project["content_prompt"] = text or "内置橙猫：站立，蓝围巾，长尾巴"
    if offline:
        project = apply_texture(directory, project, sample.texture_spec(), use_image=False)
    else:
        portrait = generate_portrait(text)
        project = apply_portrait(directory, project, portrait, text)
    save_project(directory, project)
    return view(project)


async def run_split(project_id: str, prompt: str, offline: bool) -> dict:
    text = prompt.strip()
    project = load_project(project_id)
    directory = project_dir(project_id)
    portrait_path = directory / "portrait.png"
    if not offline and not text:
        raise ValueError("请填写拆解说明，或改用内置示例")
    if offline:
        if not project.get("parts"):
            raise ValueError("还没有贴图，请先完成第 1 步")
        if _cat_parts_present(project):
            spec = sample.rig_spec()
        else:
            spec = {"bones": []}
        project["skeleton_prompt"] = text or "内置骨架：髋部连接身体、四肢和尾巴"
        project = apply_rig(directory, project, spec)
    elif portrait_path.is_file():
        portrait = Image.open(portrait_path)
        data_url, width, height, scale = vision_payload(portrait)
        spec = await plan_cut(text, width, height, data_url)
        spec = _scale_cut(spec, scale)
        project["skeleton_prompt"] = text
        project = apply_cut(directory, project, portrait, spec)
    elif project.get("parts"):
        spec = await plan_rig(text, project["parts"])
        project["skeleton_prompt"] = text
        project = apply_rig(directory, project, spec)
    else:
        raise ValueError("还没有整图，请先完成第 1 步")
    save_project(directory, project)
    return view(project)


def _scale_cut(spec: dict, scale: float) -> dict:
    parts = spec.get("parts")
    if not isinstance(parts, list) or abs(scale - 1) < 1e-6:
        return spec
    for item in parts:
        if not isinstance(item, dict):
            continue
        for key in ("x", "y", "w", "h"):
            try:
                item[key] = int(round(float(item[key]) * scale))
            except (TypeError, ValueError):
                continue
    return spec


async def run_animate(project_id: str, prompt: str, offline: bool) -> dict:
    text = prompt.strip()
    project = load_project(project_id)
    if not project.get("bones"):
        raise ValueError("还没有骨骼，请先完成第 2 步")
    if not offline and not text:
        raise ValueError("请填写动画描述，或改用内置示例")
    names = {bone["name"] for bone in project.get("bones") or []}
    if offline and {"tail", "arm_r", "head"} <= names:
        spec = sample.anim_spec()
    elif offline:
        spec = {"animations": {}}
    else:
        spec = await plan_animation(text, project["bones"])
    project["animation_prompt"] = text or "内置动画：待机与挥手"
    project = apply_animation(project_dir(project_id), project, spec)
    save_project(project_dir(project_id), project)
    return view(project)
