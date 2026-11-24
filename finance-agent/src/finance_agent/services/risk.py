"""风险分级：综合金额、标准违规、重复、票据置信度。

【初学者 · 目的】把多信号压成 low/medium/high，供审批策略使用。
【易错点】这是规则引擎不是 ML；调权重要同步看 approval.decide_status，否则「高风险却自动过」。
"""

from __future__ import annotations


def grade_risk(
    *,
    amount: float,
    standard_ok: bool,
    is_duplicate: bool,
    receipt_confidence: float,
    auto_approve_limit: float,
) -> tuple[str, list[str]]:
    """返回 (risk_level, reasons)。level: low/medium/high。"""
    reasons: list[str] = []
    score = 0

    if is_duplicate:
        score += 50
        reasons.append("疑似重复报销")
    if not standard_ok:
        score += 25
        reasons.append("超出报销标准")
    if receipt_confidence < 0.5:
        score += 15
        reasons.append("票据结构化置信度偏低")
    if amount > auto_approve_limit * 3:
        score += 20
        reasons.append("大额报销")
    elif amount > auto_approve_limit:
        score += 10
        reasons.append("超过自动审批阈值")

    if score >= 40:
        level = "high"
    elif score >= 20:
        level = "medium"
    else:
        level = "low"
        if not reasons:
            reasons.append("未见明显风险信号")
    return level, reasons
