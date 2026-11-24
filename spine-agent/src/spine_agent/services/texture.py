"""把部件画成一张互不重叠的贴图，并生成站立姿势的组装图。

贴图坐标：左上角为原点，y 向下（PNG / Spine atlas 的 xy 都是这个方向）。
角色坐标：脚底中心为原点，y 向上。部件的 x/y 是角色坐标里的中心点。
部件在贴图上分开排布，第 2 步按矩形裁切时不会把邻居裁进来。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageDraw, ImageFilter

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
SHAPES = {"ellipse", "roundrect", "capsule", "polygon"}
PIVOTS = {"center", "top", "bottom", "left", "right"}


@dataclass
class Part:
    name: str
    shape: str
    w: int
    h: int
    fill: tuple[int, int, int, int]
    stroke: tuple[int, int, int, int]
    pivot: str
    layer: int
    x: float
    y: float
    rotation: float
    details: list[dict] = field(default_factory=list)
    prompt: str = ""
    atlas_x: int = 0
    atlas_y: int = 0


def hex_color(value: object, default: str = "#888888") -> tuple[int, int, int, int]:
    text = str(value or "").strip()
    if not _HEX.match(text):
        text = default
    text = text.lstrip("#")
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    alpha = int(text[6:8], 16) if len(text) == 8 else 255
    return red, green, blue, alpha


def darken(color: tuple[int, int, int, int], amount: int = 36) -> tuple[int, int, int, int]:
    return (
        max(0, color[0] - amount),
        max(0, color[1] - amount),
        max(0, color[2] - amount),
        color[3],
    )


def guess_pivot(name: str) -> str:
    lowered = name.lower()
    if any(token in lowered for token in ("ear", "horn", "antenna", "hair", "head")):
        return "bottom"
    if any(token in lowered for token in ("arm", "leg", "hand", "foot", "wing", "thigh", "calf")):
        return "top"
    if "tail" in lowered:
        return "right"
    return "center"


def guess_layer(name: str) -> int:
    lowered = name.lower()
    if "tail" in lowered:
        return 5
    if any(token in lowered for token in ("leg", "foot")):
        return 10
    if any(token in lowered for token in ("torso", "body", "chest")):
        return 20
    if any(token in lowered for token in ("arm", "wing", "hand")):
        return 30
    if any(token in lowered for token in ("scarf", "cloth", "cape")):
        return 35
    if "head" in lowered:
        return 40
    if any(token in lowered for token in ("ear", "horn", "hair")):
        return 50
    return 25


def _clamp_int(value: object, low: int, high: int, default: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clamp_float(value: object, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clean_name(value: object, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    if not text or not text[0].isalpha():
        text = fallback
    text = text[:32]
    if not _NAME.match(text):
        return fallback
    return text


def _clean_details(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    details: list[dict] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        shape = str(item.get("shape") or "ellipse").lower()
        if shape not in {"ellipse", "roundrect", "polygon"}:
            shape = "ellipse"
        detail = {
            "shape": shape,
            "cx": _clamp_float(item.get("cx", 0.5), 0, 1, 0.5),
            "cy": _clamp_float(item.get("cy", 0.5), 0, 1, 0.5),
            "w": _clamp_float(item.get("w", 0.2), 0.02, 1, 0.2),
            "h": _clamp_float(item.get("h", 0.2), 0.02, 1, 0.2),
            "fill": "#{:02x}{:02x}{:02x}{:02x}".format(*hex_color(item.get("fill"), "#332820")),
        }
        points = []
        if isinstance(item.get("points"), list):
            for point in item["points"][:12]:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    points.append(
                        [
                            _clamp_float(point[0], -0.2, 1.2, 0),
                            _clamp_float(point[1], -0.2, 1.2, 0),
                        ]
                    )
        if len(points) >= 3:
            detail["points"] = points
        details.append(detail)
    return details


def normalize_parts(raw_parts: object) -> tuple[list[Part], list[str]]:
    """把模型输出收成可绘制的部件。返回 (部件, 警告)。"""
    warnings: list[str] = []
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ValueError("贴图规划里没有 parts")
    parts: list[Part] = []
    used: set[str] = set()
    for index, item in enumerate(raw_parts[:14]):
        if not isinstance(item, dict):
            continue
        fallback = f"part_{index + 1:02d}"
        name = _clean_name(item.get("name"), fallback)
        if name in used:
            name = _clean_name(f"{name}_{index + 1}", fallback)
        used.add(name)
        shape = str(item.get("shape") or "ellipse").lower()
        if shape not in SHAPES:
            shape = "ellipse"
        fill = hex_color(item.get("fill"), "#e09a45")
        stroke = hex_color(item.get("stroke"), "#{:02x}{:02x}{:02x}".format(*darken(fill)[:3]))
        pivot = str(item.get("pivot") or guess_pivot(name)).lower()
        if pivot not in PIVOTS:
            pivot = guess_pivot(name)
        part = Part(
            name=name,
            shape=shape,
            w=_clamp_int(item.get("w"), 20, 280, 80),
            h=_clamp_int(item.get("h"), 20, 320, 80),
            fill=fill,
            stroke=stroke,
            pivot=pivot,
            layer=_clamp_int(item.get("layer"), 0, 100, guess_layer(name)),
            x=_clamp_float(item.get("x"), -420, 420, 0),
            y=_clamp_float(item.get("y"), -40, 860, 80),
            rotation=_clamp_float(item.get("rotation"), -180, 180, 0),
            details=_clean_details(item.get("details")),
            prompt=str(item.get("prompt") or "").strip()[:240],
        )
        parts.append(part)
    if len(parts) < 2:
        raise ValueError("至少需要 2 个有效部件")
    if len(raw_parts) > 14:
        warnings.append("部件超过 14 个，已只保留前 14 个")
    return parts, warnings


def _mix(color: tuple[int, int, int, int], toward: tuple[int, int, int], amount: float) -> tuple[int, int, int, int]:
    return tuple(int(color[index] + (toward[index] - color[index]) * amount) for index in range(3)) + (color[3],)


def _shape_mask(width: int, height: int, shape: str) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    pad = max(3, min(width, height) // 40)
    box = [pad, pad, width - pad - 1, height - pad - 1]
    if shape == "polygon":
        draw.polygon([(width / 2, pad), (width - pad, height - pad), (pad, height - pad)], fill=255)
        return mask
    if shape == "ellipse":
        draw.ellipse(box, fill=255)
        return mask
    radius = min(box[2] - box[0], box[3] - box[1])
    radius *= 0.5 if shape == "capsule" else 0.28
    draw.rounded_rectangle(box, radius=radius, fill=255)
    return mask


def _gradient_fill(width: int, height: int, color: tuple[int, int, int, int], mask: Image.Image) -> Image.Image:
    light = _mix(color, (255, 255, 255), 0.34)
    dark = _mix(color, (40, 24, 16), 0.22)
    column = Image.new("RGBA", (1, height))
    pixels = column.load()
    for y in range(height):
        blend = y / max(height - 1, 1)
        pixels[0, y] = _mix(light, dark[:3], blend)
    gradient = column.resize((width, height), Image.Resampling.BILINEAR)
    gradient.putalpha(mask)
    return gradient


def _clip_to_mask(layer: Image.Image, mask: Image.Image) -> Image.Image:
    red, green, blue, alpha = layer.split()
    return Image.merge("RGBA", (red, green, blue, ImageChops.multiply(alpha, mask)))


def _paint_detail(canvas: Image.Image, detail: dict, width: int, height: int, mask: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    fill = hex_color(detail.get("fill"), "#332820")
    opaque = (fill[0], fill[1], fill[2], 255)
    if detail["shape"] == "polygon" and detail.get("points"):
        points = [(point[0] * width, point[1] * height) for point in detail["points"]]
        draw.polygon(points, fill=opaque)
    else:
        cx = detail["cx"] * width
        cy = detail["cy"] * height
        dw = max(2, detail["w"] * width)
        dh = max(2, detail["h"] * height)
        box = [cx - dw / 2, cy - dh / 2, cx + dw / 2, cy + dh / 2]
        if detail["shape"] == "ellipse":
            draw.ellipse(box, fill=opaque)
        else:
            radius = min(dw, dh) * (0.5 if detail["shape"] == "capsule" else 0.28)
            draw.rounded_rectangle(box, radius=radius, fill=opaque)
    if fill[3] < 255:
        alpha = layer.getchannel("A").point(lambda value: value * fill[3] // 255)
        layer.putalpha(alpha)
    return Image.alpha_composite(canvas, _clip_to_mask(layer, mask))


def _auto_details(part: Part) -> list[dict]:
    """模型没画五官时补一套，避免头和身体只剩一块色块。"""
    details = list(part.details)
    name = part.name
    if "head" in name and len(details) < 3:
        details = [
            {"shape": "ellipse", "cx": 0.33, "cy": 0.46, "w": 0.2, "h": 0.24, "fill": "#fff8ee"},
            {"shape": "ellipse", "cx": 0.67, "cy": 0.46, "w": 0.2, "h": 0.24, "fill": "#fff8ee"},
            {"shape": "ellipse", "cx": 0.34, "cy": 0.48, "w": 0.09, "h": 0.12, "fill": "#2a211c"},
            {"shape": "ellipse", "cx": 0.68, "cy": 0.48, "w": 0.09, "h": 0.12, "fill": "#2a211c"},
            {"shape": "ellipse", "cx": 0.5, "cy": 0.64, "w": 0.1, "h": 0.08, "fill": "#d46558"},
            {"shape": "ellipse", "cx": 0.5, "cy": 0.75, "w": 0.16, "h": 0.07, "fill": "#5c382f"},
            *details,
        ]
    elif any(token in name for token in ("torso", "body", "chest")) and not details:
        belly = "#{:02x}{:02x}{:02x}".format(*_mix(part.fill, (255, 255, 255), 0.45)[:3])
        details.append({"shape": "ellipse", "cx": 0.5, "cy": 0.62, "w": 0.52, "h": 0.46, "fill": belly})
    elif any(token in name for token in ("arm", "leg", "hand", "foot")) and not details:
        pad = "#{:02x}{:02x}{:02x}".format(*_mix(part.fill, (40, 24, 16), 0.28)[:3])
        details.append({"shape": "ellipse", "cx": 0.5, "cy": 0.86, "w": 0.62, "h": 0.18, "fill": pad})
    elif "ear" in name and not any(item.get("shape") == "polygon" for item in details):
        inner = "#{:02x}{:02x}{:02x}".format(*_mix(part.fill, (255, 220, 190), 0.55)[:3])
        details.append(
            {"shape": "polygon", "fill": inner, "points": [[0.5, 0.32], [0.32, 0.9], [0.68, 0.9]]}
        )
    return details


def render_part_image(part: Part) -> Image.Image:
    """超采样绘制：渐变填充、描边、高光，再叠五官。比直接铺纯色更接近贴纸角色。"""
    scale = 4
    width = part.w * scale
    height = part.h * scale
    mask = _shape_mask(width, height, part.shape)
    rim = max(5, min(width, height) // 18)
    if rim % 2 == 0:
        rim += 1
    outline_mask = mask.filter(ImageFilter.MaxFilter(rim))
    outline = Image.new("RGBA", (width, height), part.stroke)
    outline.putalpha(outline_mask)
    fill = _gradient_fill(width, height, part.fill, mask)
    image = Image.alpha_composite(outline, fill)
    highlight = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(highlight).ellipse(
        [width * 0.24, height * 0.08, width * 0.76, height * 0.4],
        fill=(255, 255, 255, 88),
    )
    image = Image.alpha_composite(image, _clip_to_mask(highlight, mask))
    for detail in _auto_details(part):
        image = _paint_detail(image, detail, width, height, mask)
    return image.resize((part.w, part.h), Image.Resampling.LANCZOS)


def _role(name: str) -> str:
    lowered = name.lower()
    if any(token in lowered for token in ("torso", "body", "chest")):
        return "torso"
    if "head" in lowered:
        return "head"
    if any(token in lowered for token in ("ear", "horn", "antenna", "hair")):
        return "ear"
    if any(token in lowered for token in ("leg", "thigh", "calf")) or lowered.startswith("foot") or "foot" in lowered:
        return "foot" if "foot" in lowered and "leg" not in lowered else "leg"
    if any(token in lowered for token in ("arm", "hand", "wing")):
        return "arm"
    if "tail" in lowered:
        return "tail"
    if any(token in lowered for token in ("scarf", "cloth", "cape")):
        return "cloth"
    return "other"


def _spread_x(parts: list[Part], anchor_x: float, span: float) -> None:
    ordered = sorted(parts, key=lambda part: (part.x, part.name))
    if len(ordered) == 1:
        ordered[0].x = anchor_x
        return
    for index, part in enumerate(ordered):
        part.x = anchor_x - span + (2 * span) * index / (len(ordered) - 1)


def connect_parts(parts: list[Part]) -> None:
    """把分开的部件拉到关节处相接，避免拼起来露缝、骨骼悬空。整图切片前调用。"""
    if not parts:
        return
    torso = next((part for part in parts if _role(part.name) == "torso"), None)
    if torso is None:
        torso = max(parts, key=lambda part: part.w * part.h)
    overlap = 18
    for part in parts:
        part.rotation = 0

    def meet_below(child: Part, parent: Part, pad: int = overlap) -> None:
        child.y = parent.y - parent.h / 2 + pad - child.h / 2

    def meet_above(child: Part, parent: Part, pad: int = overlap) -> None:
        child.y = parent.y + parent.h / 2 - pad + child.h / 2

    legs = [part for part in parts if part is not torso and _role(part.name) == "leg"]
    _spread_x(legs, torso.x, max(torso.w * 0.28, 16))
    for part in legs:
        meet_below(part, torso)

    arms = [part for part in parts if _role(part.name) == "arm"]
    arms.sort(key=lambda part: (part.x, part.name))
    shoulder = torso.y + torso.h * 0.2
    for index, part in enumerate(arms):
        part.y = shoulder - part.h / 2
        if len(arms) == 1:
            on_left = part.x < torso.x or part.name.endswith("_l")
        else:
            on_left = index < len(arms) / 2
        if on_left:
            part.x = torso.x - torso.w / 2 + overlap - part.w / 2
        else:
            part.x = torso.x + torso.w / 2 - overlap + part.w / 2

    head = next((part for part in parts if _role(part.name) == "head"), None)
    if head is not None and head is not torso:
        head.x = torso.x
        meet_above(head, torso)

    for part in parts:
        if _role(part.name) != "tail" or part is torso:
            continue
        part.y = torso.y - torso.h * 0.1
        part.x = torso.x - torso.w / 2 + overlap - part.w / 2

    for part in parts:
        if _role(part.name) != "cloth" or part is torso:
            continue
        part.x = torso.x
        part.y = torso.y + torso.h / 2 - part.h * 0.35

    if head is not None:
        ears = [part for part in parts if _role(part.name) == "ear"]
        _spread_x(ears, head.x, head.w * 0.26)
        for part in ears:
            meet_above(part, head, pad=max(10, part.h // 5))

    for part in parts:
        if _role(part.name) != "foot":
            continue
        owner_name = part.name.replace("foot", "leg")
        leg = next((item for item in legs if item.name == owner_name), None)
        if leg is None and legs:
            leg = min(legs, key=lambda item: abs(item.x - part.x))
        if leg is None:
            continue
            part.x = leg.x
            meet_below(part, leg, pad=10)


def parts_from_boxes(
    raw_parts: object,
    image_w: int,
    image_h: int,
) -> tuple[list[Part], list[tuple[int, int, int, int]], list[str]]:
    """视觉模型给出的图像矩形（左上角原点，y 向下）收成角色坐标里的部件。"""
    warnings: list[str] = []
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ValueError("拆解结果里没有 parts")
    cleaned: list[tuple[str, int, int, int, int, str, int]] = []
    used: set[str] = set()
    for index, item in enumerate(raw_parts[:14]):
        if not isinstance(item, dict):
            continue
        fallback = f"part_{index + 1:02d}"
        name = _clean_name(item.get("name"), fallback)
        if name in used:
            name = _clean_name(f"{name}_{index + 1}", fallback)
        used.add(name)
        try:
            x = int(float(item.get("x")))
            y = int(float(item.get("y")))
            w = int(float(item.get("w")))
            h = int(float(item.get("h")))
        except (TypeError, ValueError):
            warnings.append(f"忽略没有矩形的部件 {name}")
            continue
        pad = 8
        x -= pad
        y -= pad
        w += pad * 2
        h += pad * 2
        if x < 0:
            w += x
            x = 0
        if y < 0:
            h += y
            y = 0
        if x + w > image_w:
            w = image_w - x
        if y + h > image_h:
            h = image_h - y
        if w < 8 or h < 8:
            warnings.append(f"忽略过小的部件 {name}")
            continue
        pivot = str(item.get("pivot") or guess_pivot(name)).lower()
        if pivot not in PIVOTS:
            pivot = guess_pivot(name)
        layer = _clamp_int(item.get("layer"), 0, 100, guess_layer(name))
        cleaned.append((name, x, y, w, h, pivot, layer))
    if len(raw_parts) > 14:
        warnings.append("部件超过 14 个，已只保留前 14 个")
    if len(cleaned) < 2:
        raise ValueError("至少需要 2 个落在图像内的部件")
    origin_x = (min(item[1] for item in cleaned) + max(item[1] + item[3] for item in cleaned)) / 2
    torso = next((item for item in cleaned if _role(item[0]) == "torso"), None)
    if torso is not None:
        origin_x = torso[1] + torso[3] / 2
    foot_y = max(item[2] + item[4] for item in cleaned)
    fill = (224, 160, 90, 255)
    parts: list[Part] = []
    boxes: list[tuple[int, int, int, int]] = []
    for name, x, y, w, h, pivot, layer in cleaned:
        parts.append(
            Part(
                name=name,
                shape="roundrect",
                w=w,
                h=h,
                fill=fill,
                stroke=darken(fill),
                pivot=pivot,
                layer=layer,
                x=(x + w / 2) - origin_x,
                y=foot_y - (y + h / 2),
                rotation=0,
            )
        )
        boxes.append((x, y, w, h))
    return parts, boxes, warnings


def pack_atlas(parts: list[Part], images: dict[str, Image.Image]) -> Image.Image:
    """按行把部件排进一张贴图。返回的图与 part.atlas_x/y 对齐。"""
    padding = 10
    shelf = 768
    ordered = sorted(parts, key=lambda part: (-part.h, part.name))
    cursor_x = padding
    cursor_y = padding
    row_h = 0
    used_w = 0
    for part in ordered:
        if cursor_x + part.w + padding > shelf and cursor_x > padding:
            cursor_x = padding
            cursor_y += row_h + padding
            row_h = 0
        part.atlas_x = cursor_x
        part.atlas_y = cursor_y
        cursor_x += part.w + padding
        row_h = max(row_h, part.h)
        used_w = max(used_w, cursor_x)
    width = max(used_w + padding - 10, 32)
    height = max(cursor_y + row_h + padding, 32)
    if width % 2:
        width += 1
    if height % 2:
        height += 1
    atlas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for part in ordered:
        atlas.paste(images[part.name], (part.atlas_x, part.atlas_y), images[part.name])
    return atlas


def render_assembled(parts: list[Part], images: dict[str, Image.Image]) -> Image.Image:
    """按角色坐标把部件叠成站立图。rotation 为正表示逆时针。"""
    margin = 36
    min_x = min(part.x - part.w for part in parts)
    max_x = max(part.x + part.w for part in parts)
    min_y = min(part.y - part.h for part in parts)
    max_y = max(part.y + part.h for part in parts)
    width = int(max_x - min_x + margin * 2)
    height = int(max_y - min_y + margin * 2)
    width = max(width, 64)
    height = max(height, 64)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ground_y = height - margin - int(min(part.y - part.h / 2 for part in parts) - min_y)
    shadow = ImageDraw.Draw(canvas)
    shadow.ellipse([width * 0.28, ground_y - 10, width * 0.72, ground_y + 14], fill=(40, 28, 18, 50))
    for part in sorted(parts, key=lambda item: (item.layer, item.name)):
        sprite = images[part.name]
        if abs(part.rotation) > 0.1:
            sprite = sprite.rotate(part.rotation, expand=True, resample=Image.Resampling.BICUBIC)
        left = int(margin + (part.x - min_x) - sprite.width / 2)
        top = int(margin + (max_y - part.y) - sprite.height / 2)
        canvas.paste(sprite, (left, top), sprite)
    return canvas


def part_to_dict(part: Part) -> dict:
    return {
        "name": part.name,
        "shape": part.shape,
        "w": part.w,
        "h": part.h,
        "fill": "#{:02x}{:02x}{:02x}".format(*part.fill[:3]),
        "stroke": "#{:02x}{:02x}{:02x}".format(*part.stroke[:3]),
        "pivot": part.pivot,
        "layer": part.layer,
        "x": round(part.x, 2),
        "y": round(part.y, 2),
        "rotation": round(part.rotation, 2),
        "prompt": part.prompt,
        "atlas_x": part.atlas_x,
        "atlas_y": part.atlas_y,
        "details": part.details,
    }


def parts_from_dicts(rows: list[dict]) -> list[Part]:
    parts, _warnings = normalize_parts(rows)
    by_name = {part.name: part for part in parts}
    for row in rows:
        name = str(row.get("name") or "")
        part = by_name.get(name)
        if part is None:
            continue
        part.atlas_x = int(row.get("atlas_x") or 0)
        part.atlas_y = int(row.get("atlas_y") or 0)
    return [by_name[part.name] for part in parts if part.name in by_name]
