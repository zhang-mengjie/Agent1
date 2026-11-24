"""重复报销检测：发票号 / 票据文件哈希 / 业务指纹。

【初学者 · 目的】
同一张票只能报销一次：优先比「文件内容哈希」和「发票号码」，再比业务指纹。

【易错点】
1. 只比描述指纹不够——改几个字就能绕过；必须有 receipt_hash 或 invoice_no。
2. 已驳回的单仍占用票面（一次提交原则），避免驳回后再用同一张票重报刷单。
"""

from __future__ import annotations

import hashlib

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_agent.services.db import ExpenseRecord


def fingerprint(
    *,
    employee_id: str,
    amount: float,
    invoice_no: str | None,
    description: str,
) -> str:
    base = f"{employee_id}|{amount:.2f}|{(invoice_no or '').strip()}|{description.strip()[:80]}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


async def find_duplicate(
    session: AsyncSession,
    *,
    invoice_no: str | None,
    fp: str,
    receipt_hash: str | None = None,
) -> ExpenseRecord | None:
    """任一维度命中历史单即视为重复（含已驳回）。"""
    clauses = []
    if receipt_hash:
        clauses.append(ExpenseRecord.receipt_hash == receipt_hash)
    if invoice_no:
        clauses.append(ExpenseRecord.invoice_no == invoice_no)
    clauses.append(ExpenseRecord.fingerprint == fp)

    stmt = select(ExpenseRecord).where(or_(*clauses)).order_by(ExpenseRecord.id.asc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()
