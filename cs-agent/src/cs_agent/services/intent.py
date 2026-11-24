"""客服意图识别（规则版，可替换为 LLM 分类）。

【初学者 · 目的】
先用关键词快速分流（退款/物流/人工…），成本低、可解释；后续可换成 LLM 分类器。

【设计取舍】
- 零额外模型调用 → 延迟低。
- 多意图命中取权重最高；全未命中 → other。

【易错点】
1. 关键词过短易误伤（如「单」）；过长又召回不足——按业务语料迭代。
2. 「人工」权重最高，是为了优先尊重用户明确诉求。
3. 规则分类 ≠ 答案来源；有意图仍必须 RAG/人工，不能凭意图编政策。
"""

from __future__ import annotations

# intent -> (权重, 关键词列表)
_RULES: list[tuple[str, int, tuple[str, ...]]] = [
    ("refund", 10, ("退款", "退货", "退换", "取消订单", "不想要了")),
    ("shipping", 10, ("物流", "快递", "发货", "到哪了", "运单", "配送")),
    ("account", 9, ("登录", "密码", "账号", "注册", "绑定手机")),
    ("invoice", 8, ("发票", "开票", "抬头")),
    ("product", 7, ("规格", "怎么用", "功能", "兼容", "保修")),
    ("human", 12, ("人工", "客服电话", "转人工", "真人")),
]


def classify_intent(message: str) -> str:
    """按关键词规则识别用户意图标签。

    统计每条规则中命中的关键词个数乘以权重，取分最高者；
    全未命中返回 "other"。

    Args:
        message: 用户消息文本。

    Returns:
        str: 意图标签，如 refund / shipping / account / invoice / product /
            human / other。
    """
    text = (message or "").strip().lower()
    best_intent = "other"
    best_score = 0
    for intent, weight, keywords in _RULES:
        hits = sum(1 for kw in keywords if kw in text)
        if hits <= 0:
            continue
        score = hits * weight
        if score > best_score:
            best_score = score
            best_intent = intent
    return best_intent


def wants_human(message: str, intent: str) -> bool:
    """判断用户是否明确要求转人工。

    Args:
        message: 用户消息文本。
        intent: ``classify_intent`` 识别出的意图标签。

    Returns:
        bool: 意图为 human，或文本含「转人工 / 人工客服 / 找人工」时返回 True。
    """
    if intent == "human":
        return True
    return any(k in (message or "") for k in ("转人工", "人工客服", "找人工"))
