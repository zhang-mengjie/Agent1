"""写出 Spine 4.1 的 character.json 和 character.atlas。

atlas 的 xy 原点在贴图左上角，和 Pillow 一致，官方运行时按这个约定读。
region 附件的宽高用像素，这样 1 个 Spine 单位等于 1 像素。
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def _bounds(bones: list[dict], attachments: list[dict]) -> tuple[float, float, float, float]:
    from spine_agent.services.rig import setup_world_positions

    world = setup_world_positions(bones)
    by_name = {bone["name"]: bone for bone in bones}
    min_x = min_y = 1e9
    max_x = max_y = -1e9
    found = False
    for attachment in attachments:
        bone = by_name.get(attachment["bone"])
        if bone is None or bone["name"] not in world:
            continue
        wx, wy, wrot = world[bone["name"]]
        radians_parent = math.radians(wrot)
        cosine, sine = math.cos(radians_parent), math.sin(radians_parent)
        ax, ay = float(attachment["x"]), float(attachment["y"])
        center_x = wx + ax * cosine - ay * sine
        center_y = wy + ax * sine + ay * cosine
        half_w = float(attachment["width"]) / 2
        half_h = float(attachment["height"]) / 2
        for ox, oy in ((-half_w, -half_h), (-half_w, half_h), (half_w, half_h), (half_w, -half_h)):
            corner_x = center_x + ox * cosine - oy * sine
            corner_y = center_y + ox * sine + oy * cosine
            min_x, max_x = min(min_x, corner_x), max(max_x, corner_x)
            min_y, max_y = min(min_y, corner_y), max(max_y, corner_y)
            found = True
    if not found:
        return -100, 0, 200, 200
    return min_x, min_y, max_x - min_x, max_y - min_y


def _omit_zero(payload: dict) -> dict:
    cleaned = {}
    for key, value in payload.items():
        if isinstance(value, float) and abs(value) < 1e-6:
            continue
        if value == 0:
            continue
        cleaned[key] = value
    return cleaned


def build_skeleton_document(project: dict, spine_version: str) -> dict:
    bones_out = []
    for bone in project.get("bones") or []:
        if bone["name"] == "root":
            bones_out.append({"name": "root"})
            continue
        item = {
            "name": bone["name"],
            "parent": bone.get("parent") or "root",
            "length": bone.get("length") or 40,
            "x": bone.get("x") or 0,
            "y": bone.get("y") or 0,
            "rotation": bone.get("rotation") or 0,
        }
        bones_out.append(_omit_zero(item) | {"name": item["name"], "parent": item["parent"]})

    slots_out = [
        {"name": slot["name"], "bone": slot["bone"], "attachment": slot["attachment"]}
        for slot in project.get("slots") or []
    ]
    skin_attachments: dict[str, dict] = {}
    for attachment in project.get("attachments") or []:
        region = {
            "x": attachment.get("x") or 0,
            "y": attachment.get("y") or 0,
            "rotation": attachment.get("rotation") or 0,
            "width": attachment["width"],
            "height": attachment["height"],
        }
        region = _omit_zero(region)
        region["width"] = attachment["width"]
        region["height"] = attachment["height"]
        skin_attachments.setdefault(attachment["slot"], {})[attachment["name"]] = region

    animations = project.get("animations") or {}
    x, y, width, height = _bounds(project.get("bones") or [], project.get("attachments") or [])
    document = {
        "skeleton": {
            "hash": "pending",
            "spine": spine_version,
            "x": round(x, 2),
            "y": round(y, 2),
            "width": round(width, 2),
            "height": round(height, 2),
            "images": "./",
            "audio": "",
        },
        "bones": bones_out,
        "slots": slots_out,
        "skins": [{"name": "default", "attachments": skin_attachments}],
        "animations": animations,
    }
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")
    document["skeleton"]["hash"] = hashlib.sha1(encoded).hexdigest()[:12]
    return document


def build_atlas_text(project: dict) -> str:
    texture = project.get("texture") or {}
    width = int(texture.get("width") or 0)
    height = int(texture.get("height") or 0)
    lines = [
        "texture.png",
        f"size: {width}, {height}",
        "format: RGBA8888",
        "filter: Linear,Linear",
        "repeat: none",
    ]
    for part in project.get("parts") or []:
        lines.extend(
            [
                part["name"],
                "  rotate: false",
                f"  xy: {int(part['atlas_x'])}, {int(part['atlas_y'])}",
                f"  size: {int(part['w'])}, {int(part['h'])}",
                f"  orig: {int(part['w'])}, {int(part['h'])}",
                "  offset: 0, 0",
                "  index: -1",
            ]
        )
    return "\n".join(lines) + "\n"


def write_spine_files(directory: Path, project: dict, spine_version: str) -> None:
    document = build_skeleton_document(project, spine_version)
    (directory / "character.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (directory / "character.atlas").write_text(build_atlas_text(project), encoding="utf-8")
    project["spine_files"] = True
