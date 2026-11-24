"""把骨骼描述变成 Spine 局部变换。

世界坐标与贴图阶段相同：脚底中心为原点，y 向上，旋转逆时针。
带 part 的骨骼放在该部件的轴点上，旋转等于部件的 setup 旋转。
没有贴图的结构骨（例如 hip）使用描述里的世界坐标；缺省时取子骨骼的平均位置。
写进 Spine 文件的 x/y/rotation 是相对父骨骼的局部值。
"""

from __future__ import annotations

import math
import re

from spine_agent.services.texture import Part

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_PIVOT = {
    "center": (0.0, 0.0),
    "top": (0.0, 0.5),
    "bottom": (0.0, -0.5),
    "left": (-0.5, 0.0),
    "right": (0.5, 0.0),
}


def _clean_name(value: object, fallback: str) -> str:
    if value is None or str(value).strip() == "":
        return fallback
    text = re.sub(r"[^a-z0-9_]+", "_", str(value).strip().lower()).strip("_")
    if not text or not text[0].isalpha() or not _NAME.match(text[:32]):
        return fallback
    return text[:32]


def pivot_world(part: Part) -> tuple[float, float, float]:
    """轴点的世界坐标，以及该部件的世界旋转。"""
    ox, oy = _PIVOT.get(part.pivot, (0.0, 0.0))
    ox *= part.w
    oy *= part.h
    radians = math.radians(part.rotation)
    world_x = part.x + ox * math.cos(radians) - oy * math.sin(radians)
    world_y = part.y + ox * math.sin(radians) + oy * math.cos(radians)
    return world_x, world_y, part.rotation


def attachment_local(part: Part) -> tuple[float, float]:
    """贴图中心相对骨骼原点的偏移。骨骼旋转已经表达了部件旋转，附件自身不再转。"""
    ox, oy = _PIVOT.get(part.pivot, (0.0, 0.0))
    return -ox * part.w, -oy * part.h


def default_rig(parts: list[Part]) -> dict:
    """按名字把部件挂到 root / hip / torso / head 上，模型失败时也能拆图。"""
    names = [part.name for part in parts]
    torso = next((name for name in names if any(token in name for token in ("torso", "body", "chest"))), None)
    head = next((name for name in names if "head" in name), None)
    hip_x, hip_y = 0.0, 70.0
    if torso:
        body = next(part for part in parts if part.name == torso)
        hip_x, hip_y = body.x, body.y - body.h * 0.45
    bones: list[dict] = [
        {"name": "root"},
        {"name": "hip", "parent": "root", "x": round(hip_x, 2), "y": round(hip_y, 2)},
    ]
    for part in parts:
        parent = "hip"
        if any(token in part.name for token in ("ear", "horn", "hair", "antenna")) and head:
            parent = head
        elif head and part.name == head:
            parent = torso or "hip"
        elif any(token in part.name for token in ("arm", "wing", "hand", "scarf", "cloth", "cape")):
            parent = torso or "hip"
        elif part.name == torso:
            parent = "hip"
        bones.append({"name": part.name, "parent": parent, "part": part.name})
    return {"bones": bones}


def _topo(bones: list[dict]) -> list[dict]:
    by_name = {bone["name"]: bone for bone in bones}
    ordered: list[dict] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(name: str) -> None:
        if name in visited or name not in by_name:
            return
        if name in visiting:
            return
        visiting.add(name)
        parent = by_name[name].get("parent")
        if parent:
            walk(parent)
        visiting.remove(name)
        visited.add(name)
        ordered.append(by_name[name])

    for bone in bones:
        walk(bone["name"])
    return ordered


def build_rig(parts: list[Part], spec: dict) -> tuple[dict, list[str]]:
    """返回写入工程的 bones / slots / attachments，以及警告。"""
    warnings: list[str] = []
    raw_bones = spec.get("bones") if isinstance(spec, dict) else None
    if not isinstance(raw_bones, list) or not raw_bones:
        spec = default_rig(parts)
        raw_bones = spec["bones"]
        warnings.append("骨骼描述无法解析，已按部件名字自动装骨架")

    parts_by_name = {part.name: part for part in parts}
    bones: list[dict] = []
    used: set[str] = set()
    for index, item in enumerate(raw_bones[:24]):
        if not isinstance(item, dict):
            continue
        fallback = "root" if index == 0 else f"bone_{index + 1:02d}"
        name = _clean_name(item.get("name"), fallback)
        if name in used:
            warnings.append(f"忽略重名骨骼 {name}")
            continue
        used.add(name)
        parent = item.get("parent")
        parent_name = None if name == "root" else _clean_name(parent, "root")
        if parent_name == name:
            parent_name = "root" if name != "root" else None
        part_name = item.get("part")
        part = None
        if part_name:
            cleaned = _clean_name(part_name, "")
            part = parts_by_name.get(cleaned) or parts_by_name.get(str(part_name))
            if part is None:
                warnings.append(f"骨骼 {name} 指向了不存在的部件 {part_name}")
        bone = {
            "name": name,
            "parent": parent_name,
            "part": part.name if part else None,
            "spec_x": item.get("x"),
            "spec_y": item.get("y"),
            "spec_rotation": item.get("rotation"),
        }
        bones.append(bone)

    if not any(bone["name"] == "root" for bone in bones):
        bones.insert(0, {"name": "root", "parent": None, "part": None, "spec_x": 0, "spec_y": 0, "spec_rotation": 0})
    else:
        for bone in bones:
            if bone["name"] == "root":
                bone["parent"] = None

    claimed = {bone["part"] for bone in bones if bone.get("part")}
    for part in parts:
        if part.name in claimed:
            continue
        bones.append(
            {
                "name": part.name if part.name not in used else f"{part.name}_slot",
                "parent": "root",
                "part": part.name,
                "spec_x": None,
                "spec_y": None,
                "spec_rotation": None,
            }
        )
        used.add(bones[-1]["name"])
        warnings.append(f"部件 {part.name} 没有被骨骼引用，已挂到 root")

    by_name = {bone["name"]: bone for bone in bones}
    for bone in bones:
        parent = bone.get("parent")
        if bone["name"] != "root" and parent not in by_name:
            bone["parent"] = "root"
            warnings.append(f"骨骼 {bone['name']} 的父级不存在，已改挂到 root")

    # 期望的世界姿态：带部件的骨骼放在轴点上。
    world: dict[str, tuple[float, float, float]] = {}
    for bone in bones:
        if bone["name"] == "root":
            world[bone["name"]] = (0.0, 0.0, 0.0)
            continue
        part = parts_by_name.get(bone.get("part") or "")
        if part is not None:
            world[bone["name"]] = pivot_world(part)
            continue
        if bone.get("spec_x") is not None and bone.get("spec_y") is not None:
            try:
                rotation = float(bone.get("spec_rotation") or 0)
            except (TypeError, ValueError):
                rotation = 0.0
            world[bone["name"]] = (float(bone["spec_x"]), float(bone["spec_y"]), rotation)

    children: dict[str, list[str]] = {bone["name"]: [] for bone in bones}
    for bone in bones:
        if bone.get("parent"):
            children[bone["parent"]].append(bone["name"])

    def fill(name: str) -> tuple[float, float, float]:
        if name in world:
            return world[name]
        points = [fill(child) for child in children.get(name, [])]
        if points:
            world[name] = (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
                0.0,
            )
        else:
            world[name] = (0.0, 0.0, 0.0)
        return world[name]

    for bone in bones:
        fill(bone["name"])

    # 结构骨离所有子骨骼都很远时，收到子骨骼中间，避免骨头穿过空白。
    for bone in bones:
        if bone["name"] == "root" or bone.get("part"):
            continue
        kids = children.get(bone["name"]) or []
        if not kids:
            continue
        wx, wy, rot = world[bone["name"]]
        nearest = min(math.hypot(world[child][0] - wx, world[child][1] - wy) for child in kids)
        if nearest <= 48:
            continue
        world[bone["name"]] = (
            sum(world[child][0] for child in kids) / len(kids),
            sum(world[child][1] for child in kids) / len(kids),
            rot,
        )

    ordered = _topo(bones)
    locals_out: list[dict] = []
    for bone in ordered:
        wx, wy, wrot = world[bone["name"]]
        parent_name = bone.get("parent")
        if not parent_name:
            local_x, local_y, local_rot = wx, wy, wrot
        else:
            px, py, prot = world[parent_name]
            radians = math.radians(prot)
            cosine, sine = math.cos(radians), math.sin(radians)
            dx, dy = wx - px, wy - py
            local_x = cosine * dx + sine * dy
            local_y = -sine * dx + cosine * dy
            local_rot = wrot - prot
        child_names = children.get(bone["name"], [])
        if child_names:
            length = max(
                math.hypot(world[child][0] - wx, world[child][1] - wy) for child in child_names
            )
        else:
            part = parts_by_name.get(bone.get("part") or "")
            length = max(part.h, part.w) * 0.5 if part else 40.0
        locals_out.append(
            {
                "name": bone["name"],
                "parent": parent_name,
                "x": round(local_x, 3),
                "y": round(local_y, 3),
                "rotation": round(local_rot, 3),
                "length": round(max(length, 8), 3),
                "part": bone.get("part"),
            }
        )

    slots = []
    attachments = []
    bound = [bone for bone in locals_out if bone.get("part") and bone["part"] in parts_by_name]
    bound.sort(key=lambda bone: (parts_by_name[bone["part"]].layer, bone["name"]))
    for bone in bound:
        part = parts_by_name[bone["part"]]
        ax, ay = attachment_local(part)
        slot_name = part.name
        slots.append(
            {
                "name": slot_name,
                "bone": bone["name"],
                "attachment": part.name,
                "layer": part.layer,
            }
        )
        attachments.append(
            {
                "name": part.name,
                "slot": slot_name,
                "bone": bone["name"],
                "x": round(ax, 3),
                "y": round(ay, 3),
                "rotation": 0,
                "width": part.w,
                "height": part.h,
                "src": [part.atlas_x, part.atlas_y, part.w, part.h],
            }
        )

    for bone in locals_out:
        bone.pop("spec_x", None)
        bone.pop("spec_y", None)
        bone.pop("spec_rotation", None)
    return {"bones": locals_out, "slots": slots, "attachments": attachments, "world": {
        name: {"x": round(pos[0], 3), "y": round(pos[1], 3), "rotation": round(pos[2], 3)}
        for name, pos in world.items()
    }}, warnings


def setup_world_positions(bones: list[dict]) -> dict[str, tuple[float, float, float]]:
    """用已烘焙的局部变换重算世界坐标，供自检和包围盒使用。"""
    by_name = {bone["name"]: bone for bone in bones}
    world: dict[str, tuple[float, float, float]] = {}

    def pose(name: str) -> tuple[float, float, float]:
        if name in world:
            return world[name]
        bone = by_name[name]
        parent = bone.get("parent")
        if not parent or parent not in by_name:
            world[name] = (float(bone["x"]), float(bone["y"]), float(bone["rotation"]))
            return world[name]
        px, py, prot = pose(parent)
        radians = math.radians(prot)
        cosine, sine = math.cos(radians), math.sin(radians)
        world_x = px + float(bone["x"]) * cosine - float(bone["y"]) * sine
        world_y = py + float(bone["x"]) * sine + float(bone["y"]) * cosine
        world[name] = (world_x, world_y, prot + float(bone["rotation"]))
        return world[name]

    for bone in bones:
        pose(bone["name"])
    return world
