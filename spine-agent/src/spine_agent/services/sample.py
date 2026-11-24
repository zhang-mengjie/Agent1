"""内置橙猫。不调用模型也能走完贴图、拆图、动画三步。"""

from __future__ import annotations

import math


def texture_spec() -> dict:
    fur = "#f0a04b"
    fur_dark = "#c47a2c"
    belly = "#ffe0b8"
    scarf = "#2f6f8f"
    return {
        "title": "橙猫",
        "parts": [
            {
                "name": "leg_l",
                "shape": "capsule",
                "w": 36,
                "h": 92,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "top",
                "layer": 10,
                "x": -32,
                "y": 50,
                "rotation": 0,
                "details": [
                    {"shape": "ellipse", "cx": 0.5, "cy": 0.88, "w": 0.72, "h": 0.22, "fill": "#b56d28"},
                ],
            },
            {
                "name": "leg_r",
                "shape": "capsule",
                "w": 36,
                "h": 92,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "top",
                "layer": 10,
                "x": 32,
                "y": 50,
                "rotation": 0,
                "details": [
                    {"shape": "ellipse", "cx": 0.5, "cy": 0.88, "w": 0.72, "h": 0.22, "fill": "#b56d28"},
                ],
            },
            {
                "name": "tail",
                "shape": "capsule",
                "w": 138,
                "h": 28,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "right",
                "layer": 5,
                "x": -78,
                "y": 128,
                "rotation": -34,
                "details": [
                    {"shape": "ellipse", "cx": 0.1, "cy": 0.5, "w": 0.22, "h": 0.78, "fill": "#ffe0b8"},
                ],
            },
            {
                "name": "torso",
                "shape": "ellipse",
                "w": 148,
                "h": 156,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "center",
                "layer": 20,
                "x": 0,
                "y": 158,
                "rotation": 0,
                "details": [
                    {"shape": "ellipse", "cx": 0.5, "cy": 0.62, "w": 0.55, "h": 0.48, "fill": belly},
                    {"shape": "ellipse", "cx": 0.28, "cy": 0.34, "w": 0.16, "h": 0.1, "fill": "#d9842e"},
                    {"shape": "ellipse", "cx": 0.72, "cy": 0.34, "w": 0.16, "h": 0.1, "fill": "#d9842e"},
                ],
            },
            {
                "name": "arm_l",
                "shape": "capsule",
                "w": 32,
                "h": 100,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "top",
                "layer": 30,
                "x": -86,
                "y": 168,
                "rotation": -14,
                "details": [
                    {"shape": "ellipse", "cx": 0.5, "cy": 0.9, "w": 0.7, "h": 0.16, "fill": "#ffe0b8"},
                ],
            },
            {
                "name": "arm_r",
                "shape": "capsule",
                "w": 32,
                "h": 100,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "top",
                "layer": 30,
                "x": 86,
                "y": 168,
                "rotation": 14,
                "details": [
                    {"shape": "ellipse", "cx": 0.5, "cy": 0.9, "w": 0.7, "h": 0.16, "fill": "#ffe0b8"},
                ],
            },
            {
                "name": "scarf",
                "shape": "roundrect",
                "w": 132,
                "h": 28,
                "fill": scarf,
                "stroke": "#1d4e66",
                "pivot": "center",
                "layer": 35,
                "x": 8,
                "y": 214,
                "rotation": -6,
                "details": [
                    {"shape": "roundrect", "cx": 0.82, "cy": 0.5, "w": 0.22, "h": 0.7, "fill": "#e7d7a1"},
                ],
            },
            {
                "name": "head",
                "shape": "ellipse",
                "w": 136,
                "h": 122,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "bottom",
                "layer": 40,
                "x": 0,
                "y": 286,
                "rotation": 0,
                "details": [
                    {"shape": "ellipse", "cx": 0.34, "cy": 0.46, "w": 0.2, "h": 0.24, "fill": "#fff8ee"},
                    {"shape": "ellipse", "cx": 0.66, "cy": 0.46, "w": 0.2, "h": 0.24, "fill": "#fff8ee"},
                    {"shape": "ellipse", "cx": 0.35, "cy": 0.47, "w": 0.09, "h": 0.12, "fill": "#2a211c"},
                    {"shape": "ellipse", "cx": 0.67, "cy": 0.47, "w": 0.09, "h": 0.12, "fill": "#2a211c"},
                    {"shape": "ellipse", "cx": 0.22, "cy": 0.58, "w": 0.12, "h": 0.08, "fill": "#f0b0a0a0"},
                    {"shape": "ellipse", "cx": 0.78, "cy": 0.58, "w": 0.12, "h": 0.08, "fill": "#f0b0a0a0"},
                    {
                        "shape": "polygon",
                        "fill": "#c45b4a",
                        "points": [[0.5, 0.52], [0.42, 0.64], [0.58, 0.64]],
                    },
                    {"shape": "ellipse", "cx": 0.5, "cy": 0.72, "w": 0.16, "h": 0.08, "fill": "#6b3a32"},
                ],
            },
            {
                "name": "ear_l",
                "shape": "polygon",
                "w": 52,
                "h": 64,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "bottom",
                "layer": 50,
                "x": -40,
                "y": 352,
                "rotation": -8,
                "details": [
                    {
                        "shape": "polygon",
                        "fill": "#ffd7b0",
                        "points": [[0.5, 0.32], [0.3, 0.92], [0.7, 0.92]],
                    }
                ],
            },
            {
                "name": "ear_r",
                "shape": "polygon",
                "w": 52,
                "h": 64,
                "fill": fur,
                "stroke": fur_dark,
                "pivot": "bottom",
                "layer": 50,
                "x": 40,
                "y": 352,
                "rotation": 8,
                "details": [
                    {
                        "shape": "polygon",
                        "fill": "#ffd7b0",
                        "points": [[0.5, 0.32], [0.3, 0.92], [0.7, 0.92]],
                    }
                ],
            },
        ],
    }


def rig_spec() -> dict:
    return {
        "bones": [
            {"name": "root"},
            {"name": "hip", "parent": "root", "x": 0, "y": 100},
            {"name": "torso", "parent": "hip", "part": "torso"},
            {"name": "leg_l", "parent": "hip", "part": "leg_l"},
            {"name": "leg_r", "parent": "hip", "part": "leg_r"},
            {"name": "tail", "parent": "hip", "part": "tail"},
            {"name": "arm_l", "parent": "torso", "part": "arm_l"},
            {"name": "arm_r", "parent": "torso", "part": "arm_r"},
            {"name": "scarf", "parent": "torso", "part": "scarf"},
            {"name": "head", "parent": "torso", "part": "head"},
            {"name": "ear_l", "parent": "head", "part": "ear_l"},
            {"name": "ear_r", "parent": "head", "part": "ear_r"},
        ]
    }


def _wave_keys() -> list[dict]:
    duration = 1.4
    samples = [0.0, 0.25, 0.45, 0.7, 0.9, 1.0]
    angles = [0, 55, 110, 70, 120, 0]
    return [
        {"time": round(duration * sample, 3), "angle": angle}
        for sample, angle in zip(samples, angles, strict=True)
    ]


def anim_spec() -> dict:
    return {
        "animations": {
            "idle": {
                "duration": 1.6,
                "bones": {
                    "torso": {
                        "translate": [
                            {"time": round(1.6 * i / 8, 3), "y": round(5 * math.sin(2 * math.pi * i / 8), 2)}
                            for i in range(9)
                        ]
                    },
                    "head": {
                        "rotate": [
                            {"time": round(1.6 * i / 8, 3), "angle": round(5 * math.sin(2 * math.pi * i / 8 + 0.5), 2)}
                            for i in range(9)
                        ]
                    },
                    "tail": {
                        "rotate": [
                            {
                                "time": round(1.6 * i / 8, 3),
                                "angle": round(22 * math.sin(2 * math.pi * i / 8 + 1.0), 2),
                            }
                            for i in range(9)
                        ]
                    },
                    "ear_l": {
                        "rotate": [
                            {"time": round(1.6 * i / 8, 3), "angle": round(4 * math.sin(2 * math.pi * i / 8), 2)}
                            for i in range(9)
                        ]
                    },
                    "ear_r": {
                        "rotate": [
                            {"time": round(1.6 * i / 8, 3), "angle": round(-4 * math.sin(2 * math.pi * i / 8), 2)}
                            for i in range(9)
                        ]
                    },
                },
            },
            "wave": {
                "duration": 1.4,
                "bones": {
                    "arm_r": {"rotate": _wave_keys()},
                    "head": {
                        "rotate": [
                            {"time": 0, "angle": 0},
                            {"time": 0.45, "angle": 8},
                            {"time": 0.9, "angle": -4},
                            {"time": 1.4, "angle": 0},
                        ]
                    },
                },
            },
        }
    }
