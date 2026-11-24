"""部门预算检查（演示：Redis 键保存剩余额度）。

【初学者 · 目的】
模拟「先预占预算再审批」；通过则扣减，驳回则 release。

【易错点】
1. 键是 finance-agent:budget:{部门名}，部门字符串不一致会当成两个预算池。
2. 只预占成功却最终 rejected 时，pipeline 必须 release，否则额度泄漏。
3. Redis 被 flush 后额度恢复为 default_dept_budget——演示可接受，生产要用真账。
"""

from __future__ import annotations

from finance_agent.config import get_settings
from finance_agent.services.redis_memory import memory


async def check_and_reserve_budget(department: str, amount: float) -> tuple[bool, str, dict]:
    """检查部门剩余预算；通过则预占（演示用）。"""
    s = get_settings()
    await memory.connect()
    key = f"finance-agent:budget:{department}"
    raw = await memory.client.get(key)
    remaining = float(raw) if raw is not None else float(s.default_dept_budget)
    if amount > remaining:
        return (
            False,
            f"部门「{department}」剩余预算 {remaining:.2f}，不足以覆盖 {amount:.2f}",
            {"department": department, "remaining": remaining, "amount": amount},
        )
    new_remaining = round(remaining - amount, 2)
    await memory.client.set(key, str(new_remaining))
    return (
        True,
        f"预算预占成功，剩余 {new_remaining:.2f}",
        {"department": department, "remaining_before": remaining, "remaining_after": new_remaining},
    )


async def release_budget(department: str, amount: float) -> None:
    """驳回时释放预占。"""
    await memory.connect()
    key = f"finance-agent:budget:{department}"
    raw = await memory.client.get(key)
    remaining = float(raw) if raw is not None else float(get_settings().default_dept_budget)
    await memory.client.set(key, str(round(remaining + amount, 2)))
