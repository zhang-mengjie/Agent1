"""从模型回复里抽出 JSON。模型常包一层 markdown 代码块，或在结尾多一个逗号。"""

from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("模型返回为空")
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        blob = fence.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型没有返回 JSON 对象")
        blob = raw[start : end + 1]
    blob = re.sub(r",\s*([}\]])", r"\1", blob)
    data = json.loads(blob)
    if not isinstance(data, dict):
        raise ValueError("JSON 根必须是对象")
    return data
