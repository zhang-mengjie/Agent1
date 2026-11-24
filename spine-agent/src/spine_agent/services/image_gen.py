"""调用阿里云兼容文生图接口，只生成一张全身图。

部件不在这里画。第 2 步由视觉模型看着这张整图标出矩形，再从原图裁开。
"""

from __future__ import annotations

import base64
import hashlib
import io
from collections import deque

import httpx
from PIL import Image

from spine_agent.config import get_settings
from spine_agent.services.texture import Part, render_part_image

_MIN_AREA = 512 * 512
_MAX_AREA = 2048 * 2048


def output_size(width: int, height: int) -> str:
    """把部件宽高换成接口允许的像素尺寸。短边至少 512，总像素不超过 2048²。"""
    aspect = max(width, 1) / max(height, 1)
    aspect = min(8.0, max(1 / 8, aspect))
    short = 512
    if aspect >= 1:
        out_h = short
        out_w = int(round(short * aspect))
    else:
        out_w = short
        out_h = int(round(short / aspect))
    area = out_w * out_h
    if area > _MAX_AREA:
        scale = (_MAX_AREA / area) ** 0.5
        out_w = max(1, int(out_w * scale))
        out_h = max(1, int(out_h * scale))
    if out_w * out_h < _MIN_AREA:
        scale = (_MIN_AREA / (out_w * out_h)) ** 0.5
        out_w = int(out_w * scale) + 1
        out_h = int(out_h * scale) + 1
    return f"{out_w}x{out_h}"


def _shared_seed(character: str, style: str) -> int:
    text = f"{character}\n{style}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(text).digest()[:4], "big") % 2147483647


def _character_prompt(character: str, style: str) -> str:
    look = style.strip() or "干净的扁平卡通"
    who = character.strip() or "一个角色"
    return (
        "一张完整角色的正面站立全身图，只要这一只，居中。"
        "头、身体、四肢连成一个整体，不要拆开，不要画出第二只。"
        "脚靠近画面底部，头顶留一点空白。透明背景，不要场景，不要地面，不要阴影，不要文字，不要边框。"
        f"角色：{who}。画风：{look}。"
    )


def remove_flat_background(image: Image.Image) -> Image.Image:
    """四角已经透明就保留。四角是同一种纯色时，从边缘把这种颜色抠掉。"""
    image = image.convert("RGBA")
    width, height = image.size
    if width < 2 or height < 2:
        return image
    pixels = image.load()
    corners = [
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    ]
    if sum(pixel[3] for pixel in corners) < 80:
        return image
    red, green, blue = corners[0][:3]
    if any(abs(pixel[0] - red) + abs(pixel[1] - green) + abs(pixel[2] - blue) > 24 for pixel in corners[1:]):
        return image
    seen = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def consider(x: int, y: int) -> None:
        index = y * width + x
        if seen[index]:
            return
        seen[index] = 1
        pr, pg, pb, pa = pixels[x, y]
        if pa < 16:
            return
        if abs(pr - red) + abs(pg - green) + abs(pb - blue) > 48:
            return
        queue.append((x, y))

    for x in range(width):
        consider(x, 0)
        consider(x, height - 1)
    for y in range(height):
        consider(0, y)
        consider(width - 1, y)
    while queue:
        x, y = queue.popleft()
        pixels[x, y] = (0, 0, 0, 0)
        if x > 0:
            consider(x - 1, y)
        if x + 1 < width:
            consider(x + 1, y)
        if y > 0:
            consider(x, y - 1)
        if y + 1 < height:
            consider(x, y + 1)
    return image


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:240]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("code") or "")
        return message[:240]
    return response.text[:240]


def _download(client: httpx.Client, payload: dict) -> Image.Image:
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise RuntimeError("文生图接口没有返回图片")
    item = data[0]
    raw = item.get("b64_json")
    if isinstance(raw, str) and raw.strip():
        return Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGBA")
    url = str(item.get("url") or "").strip()
    if not url.startswith("https://"):
        raise RuntimeError("文生图接口没有返回图片地址")
    downloaded = client.get(url)
    downloaded.raise_for_status()
    return Image.open(io.BytesIO(downloaded.content)).convert("RGBA")


def generate_portrait(prompt: str) -> Image.Image:
    """生成一张正面站立的全身图，不拆件。"""
    settings = get_settings()
    if not settings.image_api_key.strip():
        raise RuntimeError("未配置 IMAGE_API_KEY")
    endpoint = settings.image_base_url.rstrip("/") + "/images/generations"
    body = {
        "model": settings.image_model,
        "prompt": _character_prompt(prompt, ""),
        "size": output_size(768, 1152),
        "n": 1,
        "seed": _shared_seed(prompt, ""),
        "watermark": False,
        "prompt_extend": False,
    }
    timeout = httpx.Timeout(180.0, connect=20.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.post(
            endpoint,
            json=body,
            headers={"Authorization": f"Bearer {settings.image_api_key}"},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"文生图接口 {response.status_code}：{_error_text(response)}")
        return _download(client, response.json()).convert("RGBA")


def vision_payload(image: Image.Image, max_side: int = 1024) -> tuple[str, int, int, float]:
    """缩小后交给视觉模型。返回 data URL、送给模型的宽高、以及乘回原图像素的比例。"""
    copy = image.convert("RGBA")
    scale = 1.0
    if max(copy.size) > max_side:
        scale = max_side / max(copy.size)
        copy = copy.resize(
            (max(1, int(round(copy.width * scale))), max(1, int(round(copy.height * scale)))),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    copy.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    back = copy.width / image.width if image.width else 1.0
    return f"data:image/png;base64,{encoded}", copy.width, copy.height, 1 / back if back else 1.0


def render_part_images(
    parts: list[Part],
    *,
    character: str,
    style: str,
    use_image: bool | None = None,
) -> tuple[dict[str, Image.Image], list[str]]:
    """本地贴纸。在线整图不走这里。use_image 保留给旧调用，不再按部件出图。"""
    del character, style, use_image
    return {part.name: render_part_image(part) for part in parts}, []
