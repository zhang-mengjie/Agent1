"""报销标准校验：对照公司费用限额。

【初学者 · 目的】category → 限额；超标返回 ok=False（不一定立刻驳回，由风险+审批共同决定）。
【易错点】unknown category 走宽松默认；前端类别拼写错误会导致「不校验却以为校验了」。
"""

from __future__ import annotations

from finance_agent.config import get_settings


def validate_standard(*, category: str, amount: float) -> tuple[bool, str, dict]:
    s = get_settings()
    cat = (category or "other").lower()
    limits = {
        "meal": s.meal_limit_per_day,
        "travel": s.travel_hotel_limit,
        "transport": s.transport_taxi_limit,
    }
    if cat not in limits:
        return True, f"类别 {cat} 无硬性单笔限额，进入后续审核", {"limit": None, "category": cat}

    limit = limits[cat]
    if amount <= limit:
        return True, f"{cat} 金额 {amount} ≤ 标准上限 {limit}", {"limit": limit, "category": cat}
    return (
        False,
        f"{cat} 金额 {amount} 超过标准上限 {limit}",
        {"limit": limit, "category": cat, "over_by": round(amount - limit, 2)},
    )
