"""动态审批路径：按金额与风险决定审批链。

【初学者 · 目的】
用规则表达「谁该审」：金额/风险越高，链条越长；低风险小额可自动过。

【易错点】
1. decide_status 返回的是状态字符串，不是真正调用审批人——pending 要等管理员 API。
2. auto_approve 时 pipeline 会清空 chain，避免前端误显示还要找主管。
3. 重复报销 / 高风险超标会直接 rejected，与「待审」不同。
"""

from __future__ import annotations

from finance_agent.config import get_settings
from finance_agent.schemas.expense import ApprovalStep


def build_approval_chain(*, amount: float, risk_level: str) -> list[ApprovalStep]:
    s = get_settings()
    chain: list[ApprovalStep] = [
        ApprovalStep(role="direct_manager", name="直属主管", required=True),
    ]
    if amount > s.auto_approve_limit or risk_level in {"medium", "high"}:
        chain.append(ApprovalStep(role="finance_bp", name="财务 BP", required=True))
    if amount > s.auto_approve_limit * 2 or risk_level == "high":
        chain.append(ApprovalStep(role="cfo", name="财务负责人", required=True))
    return chain


def decide_status(
    *,
    amount: float,
    risk_level: str,
    standard_ok: bool,
    is_duplicate: bool,
) -> str:
    """auto_approved / pending_approval / rejected"""
    if is_duplicate:
        return "rejected"
    if not standard_ok and risk_level == "high":
        return "rejected"
    s = get_settings()
    if (
        standard_ok
        and risk_level == "low"
        and amount <= s.auto_approve_limit
    ):
        return "auto_approved"
    return "pending_approval"
