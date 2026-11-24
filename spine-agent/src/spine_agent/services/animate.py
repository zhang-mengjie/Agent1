"""把动画描述烘焙成 Spine 时间轴。

模型给出的 rotate / translate 是相对 setup 姿态的偏移。
写进 JSON 的数值是骨骼局部变换的绝对值，和 Spine 运行时一致。
"""

from __future__ import annotations

import math
import re

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _clamp(value: object, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clean_anim_name(value: object, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    if not text or not text[0].isalpha() or not _NAME.match(text[:32]):
        return fallback
    return text[:32]


def _sine_rotate(amplitude: float, duration: float = 1.6, steps: int = 8, phase: float = 0.0) -> list[dict]:
    keys = []
    for index in range(steps + 1):
        keys.append(
            {
                "time": round(duration * index / steps, 3),
                "angle": round(amplitude * math.sin(2 * math.pi * index / steps + phase), 2),
            }
        )
    return keys


def _sine_translate(amp_y: float, duration: float = 1.6, steps: int = 8) -> list[dict]:
    keys = []
    for index in range(steps + 1):
        keys.append(
            {
                "time": round(duration * index / steps, 3),
                "x": 0,
                "y": round(amp_y * math.sin(2 * math.pi * index / steps), 2),
            }
        )
    return keys


def default_animation(bones: list[dict]) -> dict:
    """给一个能看出在动的待机：身体起伏，头和尾巴（如果有）轻轻摆。"""
    names = {bone["name"] for bone in bones}
    channels: dict[str, dict] = {}
    body = next((name for name in names if name in {"torso", "body", "chest", "hip"}), None)
    if body:
        channels[body] = {"translate": _sine_translate(6)}
    if "head" in names:
        channels["head"] = {"rotate": _sine_rotate(6, phase=0.4)}
    if "tail" in names:
        channels["tail"] = {"rotate": _sine_rotate(18, phase=1.0)}
    if "arm_r" in names:
        channels["arm_r"] = {"rotate": _sine_rotate(8, phase=0.2)}
    if "arm_l" in names:
        channels["arm_l"] = {"rotate": _sine_rotate(8, phase=math.pi)}
    if not channels:
        movable = next((bone["name"] for bone in bones if bone["name"] != "root"), None)
        if movable:
            channels[movable] = {"rotate": _sine_rotate(8)}
    return {"animations": {"idle": {"duration": 1.6, "bones": channels}}}


def _finalize_keys(keys: list[dict], duration: float, fields: list[str], setup: dict[str, float]) -> list[dict]:
    if not keys:
        keys = [{"time": 0.0, **setup}]
    keys = sorted(keys, key=lambda item: item["time"])
    cleaned = []
    for key in keys:
        if key["time"] < -0.001 or key["time"] > duration + 0.001:
            continue
        item = {"time": round(min(max(key["time"], 0.0), duration), 3)}
        for field in fields:
            item[field] = round(float(key.get(field, setup[field])), 3)
        cleaned.append(item)
    if not cleaned or cleaned[0]["time"] > 0.001:
        cleaned.insert(0, {"time": 0.0, **{field: round(setup[field], 3) for field in fields}})
    closing = {"time": round(duration, 3)}
    for field in fields:
        closing[field] = cleaned[0][field]
    if abs(cleaned[-1]["time"] - duration) < 0.02:
        cleaned[-1] = closing
    else:
        cleaned.append(closing)
    return cleaned


def _bake_once(spec: dict, bones: list[dict]) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    raw = spec.get("animations") if isinstance(spec, dict) else None
    if not isinstance(raw, dict):
        return {}, warnings

    by_name = {bone["name"]: bone for bone in bones}
    baked: dict[str, dict] = {}
    for index, (anim_name, anim) in enumerate(list(raw.items())[:3]):
        if not isinstance(anim, dict):
            continue
        name = _clean_anim_name(anim_name, f"anim_{index + 1}")
        duration = _clamp(anim.get("duration", 1.2), 0.4, 8, 1.2)
        bone_channels = anim.get("bones") if isinstance(anim.get("bones"), dict) else {}
        bones_out: dict[str, dict] = {}
        for bone_name, channels in bone_channels.items():
            cleaned = _clean_anim_name(bone_name, "")
            bone = by_name.get(cleaned) or by_name.get(str(bone_name))
            if bone is None or not isinstance(channels, dict):
                warnings.append(f"动画 {name} 忽略了未知骨骼 {bone_name}")
                continue
            out: dict[str, list] = {}
            if isinstance(channels.get("rotate"), list):
                keys = []
                for key in channels["rotate"][:16]:
                    if not isinstance(key, dict):
                        continue
                    keys.append(
                        {
                            "time": _clamp(key.get("time", 0), 0, duration, 0),
                            "angle": bone["rotation"] + _clamp(key.get("angle", 0), -180, 180, 0),
                        }
                    )
                out["rotate"] = _finalize_keys(keys, duration, ["angle"], {"angle": bone["rotation"]})
            if isinstance(channels.get("translate"), list):
                keys = []
                for key in channels["translate"][:16]:
                    if not isinstance(key, dict):
                        continue
                    keys.append(
                        {
                            "time": _clamp(key.get("time", 0), 0, duration, 0),
                            "x": bone["x"] + _clamp(key.get("x", 0), -220, 220, 0),
                            "y": bone["y"] + _clamp(key.get("y", 0), -220, 220, 0),
                        }
                    )
                out["translate"] = _finalize_keys(
                    keys, duration, ["x", "y"], {"x": bone["x"], "y": bone["y"]}
                )
            if isinstance(channels.get("scale"), list):
                keys = []
                for key in channels["scale"][:16]:
                    if not isinstance(key, dict):
                        continue
                    keys.append(
                        {
                            "time": _clamp(key.get("time", 0), 0, duration, 0),
                            "x": _clamp(key.get("x", 1), 0.2, 2.5, 1),
                            "y": _clamp(key.get("y", 1), 0.2, 2.5, 1),
                        }
                    )
                out["scale"] = _finalize_keys(keys, duration, ["x", "y"], {"x": 1.0, "y": 1.0})
            if out:
                bones_out[bone["name"]] = out
        if bones_out:
            baked[name] = {"bones": bones_out}
    return baked, warnings


def bake_animations(spec: dict, bones: list[dict]) -> tuple[dict, list[str]]:
    baked, warnings = _bake_once(spec, bones)
    if baked:
        return baked, warnings
    baked, extra = _bake_once(default_animation(bones), bones)
    warnings.extend(extra)
    warnings.append("没有可用的关键帧，已改成默认待机")
    if not baked:
        return {"idle": {"bones": {}}}, warnings
    return baked, warnings
