"""ERP 报销单提交。

【初学者 · 目的】把「审批通过」与「财务系统落单」解耦；默认 mock 生成凭证号。
【易错点】ERP_MOCK=false 时会 NotImplementedError——先保持 true，或在本文件接真实 API。
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from finance_agent.config import get_settings


async def submit_reimbursement(
    *,
    expense_id: str,
    employee_id: str,
    department: str,
    amount: float,
    category: str,
    description: str,
) -> dict:
    s = get_settings()
    if not s.erp_mock:
        # 预留真实对接点
        raise NotImplementedError("请实现真实 ERP 适配器，或将 ERP_MOCK=true")

    voucher_id = f"ERP-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"
    return {
        "ok": True,
        "voucher_id": voucher_id,
        "system": "mock-erp",
        "payload": {
            "expense_id": expense_id,
            "employee_id": employee_id,
            "department": department,
            "amount": amount,
            "category": category,
            "description": description,
        },
    }
