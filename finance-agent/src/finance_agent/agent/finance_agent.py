"""财务审批编排。

【初学者 · 目的】
把「报销审批」拆成可观测的流水线步骤（每步写入 steps），便于前端展示与排障。
1) run_expense_pipeline —— 申请到 ERP 的主链路
2) decide_expense_manual —— 管理员对 pending 单批准/驳回
3) run_policy_chat —— 制度问答（严格 RAG，同 rag-agent 思路）

【易错点】
1. 预算 check_and_reserve 会扣减；驳回必须 release_budget，否则部门额度被「吃掉」。
2. 解析出的 amount 优先于表单金额——用户填错金额时以票面为准（演示策略）。
3. auto_approved 才会自动 ERP；pending_approval 要等管理员 decide。
4. 重复发票号直接 rejected，测试时换新 invoice_no。
"""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from finance_agent.config import get_settings
from finance_agent.schemas.chat import AgentChatRequest, AgentChatResponse
from finance_agent.schemas.expense import (
    ExpenseSubmitRequest,
    ExpenseSubmitResponse,
    PipelineStepResult,
)
from finance_agent.services.approval import build_approval_chain, decide_status
from finance_agent.services.budget import check_and_reserve_budget, release_budget
from finance_agent.services.db import save_expense, save_turn
from finance_agent.services.duplicate import find_duplicate, fingerprint
from finance_agent.services.erp import submit_reimbursement
from finance_agent.services.llm import build_chat_model, resolve_model_name
from finance_agent.services.rag import format_context, retrieve
from finance_agent.services.receipt_parser import parse_receipt_text
from finance_agent.services.receipt_store import save_receipt_file
from finance_agent.services.redis_memory import memory
from finance_agent.services.risk import grade_risk
from finance_agent.services.standards import validate_standard


async def run_expense_pipeline(
    request: ExpenseSubmitRequest,
    db: AsyncSession,
    *,
    receipt_bytes: bytes | None = None,
    receipt_filename: str | None = None,
) -> ExpenseSubmitResponse:
    """执行智能审批链路并落库；若有 receipt_bytes 则保存原件。"""
    settings = get_settings()
    expense_id = f"EXP-{uuid4().hex[:10].upper()}"
    steps: list[PipelineStepResult] = []
    policy_sources: list[str] = []

    receipt_hash = request.receipt_hash
    receipt_name = receipt_filename or request.receipt_filename
    receipt_path: str | None = None

    # 1) 票据结构化（文本可由粘贴或 PDF/图片 OCR 提供）
    parsed = parse_receipt_text(request.receipt_text, fallback_amount=request.amount)
    if request.receipt_text and not parsed.source_method:
        parsed.source_method = "paste"
    if receipt_name and not parsed.source_filename:
        parsed.source_filename = receipt_name
    invoice_no = parsed.invoice_no or request.invoice_no
    amount = float(parsed.amount if parsed.amount is not None else request.amount)
    steps.append(
        PipelineStepResult(
            step="receipt_parse",
            ok=parsed.confidence >= 0.4 or not request.receipt_text,
            message=f"票据结构化完成，置信度 {parsed.confidence:.2f}",
            detail=parsed.model_dump(),
        )
    )

    # 2) 重复报销检测（文件哈希 / 发票号 / 指纹，任一命中即拒）
    fp = fingerprint(
        employee_id=request.employee_id,
        amount=amount,
        invoice_no=invoice_no,
        description=request.description,
    )
    dup = await find_duplicate(
        db, invoice_no=invoice_no, fp=fp, receipt_hash=receipt_hash
    )
    is_duplicate = dup is not None
    dup_reason = []
    if is_duplicate and dup is not None:
        if receipt_hash and dup.receipt_hash == receipt_hash:
            dup_reason.append("相同票据文件")
        if invoice_no and dup.invoice_no == invoice_no:
            dup_reason.append("相同发票号")
        if dup.fingerprint == fp:
            dup_reason.append("相同费用指纹")
    steps.append(
        PipelineStepResult(
            step="duplicate_check",
            ok=not is_duplicate,
            message=(
                f"票据不可重复提交（{'/'.join(dup_reason) or '重复'}），历史单号 {dup.expense_id}"
                if is_duplicate and dup is not None
                else "未发现重复报销"
            ),
            detail={
                "fingerprint": fp,
                "invoice_no": invoice_no,
                "receipt_hash": receipt_hash,
            },
        )
    )

    # 3) 财务制度检索
    policy_query = f"{request.category} 报销 标准 {request.description}"
    try:
        docs = retrieve(policy_query, top_k=settings.rag_top_k)
        policy_sources = [
            (d.page_content[:100] + "…") if len(d.page_content) > 100 else d.page_content
            for d in docs
        ]
        steps.append(
            PipelineStepResult(
                step="policy_retrieve",
                ok=True,
                message=f"命中制度切片 {len(docs)} 条" if docs else "未命中制度切片（将仅用硬编码标准）",
                detail={"hits": len(docs)},
            )
        )
    except Exception as exc:
        docs = []
        steps.append(
            PipelineStepResult(
                step="policy_retrieve",
                ok=False,
                message=f"制度检索失败: {exc}",
                detail={},
            )
        )

    # 4) 报销标准校验
    standard_ok, standard_msg, standard_detail = validate_standard(
        category=request.category, amount=amount
    )
    steps.append(
        PipelineStepResult(
            step="standard_check",
            ok=standard_ok,
            message=standard_msg,
            detail=standard_detail,
        )
    )

    # 5) 部门预算检查（重复/高风险拒绝前也会检查，拒绝时释放）
    budget_ok, budget_msg, budget_detail = await check_and_reserve_budget(
        request.department, amount
    )
    steps.append(
        PipelineStepResult(
            step="budget_check",
            ok=budget_ok,
            message=budget_msg,
            detail=budget_detail,
        )
    )

    # 6) 风险分级
    risk_level, risk_reasons = grade_risk(
        amount=amount,
        standard_ok=standard_ok and budget_ok,
        is_duplicate=is_duplicate,
        receipt_confidence=parsed.confidence,
        auto_approve_limit=settings.auto_approve_limit,
    )
    steps.append(
        PipelineStepResult(
            step="risk_grade",
            ok=risk_level != "high",
            message=f"风险等级 {risk_level}",
            detail={"reasons": risk_reasons},
        )
    )

    # 7) 动态审批
    status = decide_status(
        amount=amount,
        risk_level=risk_level,
        standard_ok=standard_ok and budget_ok,
        is_duplicate=is_duplicate,
    )
    if not budget_ok and status != "rejected":
        status = "rejected"
    chain = build_approval_chain(amount=amount, risk_level=risk_level)
    if status == "auto_approved":
        chain = []
    steps.append(
        PipelineStepResult(
            step="dynamic_approval",
            ok=status != "rejected",
            message=f"审批结论: {status}",
            detail={"chain": [c.model_dump() for c in chain]},
        )
    )

    # 驳回释放预算
    if status == "rejected" and budget_ok:
        await release_budget(request.department, amount)

    # 8) ERP 落单
    erp_voucher_id = None
    if status == "auto_approved" and request.submit_to_erp:
        try:
            erp = await submit_reimbursement(
                expense_id=expense_id,
                employee_id=request.employee_id,
                department=request.department,
                amount=amount,
                category=request.category,
                description=request.description,
            )
            erp_voucher_id = erp.get("voucher_id")
            steps.append(
                PipelineStepResult(
                    step="erp_submit",
                    ok=True,
                    message=f"已提交 ERP，凭证 {erp_voucher_id}",
                    detail=erp,
                )
            )
        except Exception as exc:
            steps.append(
                PipelineStepResult(
                    step="erp_submit",
                    ok=False,
                    message=f"ERP 提交失败: {exc}",
                    detail={},
                )
            )
            status = "pending_approval"
    elif status == "pending_approval":
        steps.append(
            PipelineStepResult(
                step="erp_submit",
                ok=True,
                message="待人工审批通过后再提交 ERP",
                detail={},
            )
        )
    else:
        steps.append(
            PipelineStepResult(
                step="erp_submit",
                ok=False,
                message="单据已驳回，不提交 ERP",
                detail={},
            )
        )

    summary_parts = [
        f"单号 {expense_id}",
        f"金额 {amount:.2f}",
        f"风险 {risk_level}",
        f"状态 {status}",
    ]
    if policy_sources:
        summary_parts.append(f"制度命中 {len(policy_sources)} 条")
    if erp_voucher_id:
        summary_parts.append(f"ERP {erp_voucher_id}")
    summary = "；".join(summary_parts)

    # 落盘原件：即使最终 rejected 也保留，便于审计与「一票一次」举证
    if receipt_bytes and not is_duplicate:
        try:
            saved = save_receipt_file(
                expense_id=expense_id,
                data=receipt_bytes,
                original_filename=receipt_name or "receipt.bin",
            )
            receipt_hash = saved["receipt_hash"]
            receipt_path = saved["receipt_path"]
            receipt_name = saved["receipt_filename"]
            steps.append(
                PipelineStepResult(
                    step="receipt_store",
                    ok=True,
                    message=f"已保存票据原件 {receipt_name}",
                    detail={"path": receipt_path, "hash": receipt_hash},
                )
            )
        except Exception as exc:
            steps.append(
                PipelineStepResult(
                    step="receipt_store",
                    ok=False,
                    message=f"票据原件保存失败: {exc}",
                    detail={},
                )
            )

    await save_expense(
        db,
        expense_id=expense_id,
        employee_id=request.employee_id,
        employee_name=request.employee_name,
        department=request.department,
        category=request.category,
        amount=amount,
        description=request.description,
        invoice_no=invoice_no,
        fingerprint=fp,
        receipt_hash=receipt_hash,
        receipt_path=receipt_path,
        receipt_filename=receipt_name,
        status=status,
        risk_level=risk_level,
        erp_voucher_id=erp_voucher_id,
        summary=summary,
    )

    return ExpenseSubmitResponse(
        expense_id=expense_id,
        status=status,
        risk_level=risk_level,
        need_manual_review=status == "pending_approval",
        parsed_receipt=parsed,
        steps=steps,
        approval_chain=chain,
        policy_sources=policy_sources,
        erp_voucher_id=erp_voucher_id,
        summary=summary,
        receipt_hash=receipt_hash,
        receipt_filename=receipt_name,
        has_receipt_file=bool(receipt_path),
    )


async def decide_expense_manual(
    *,
    expense_id: str,
    action: str,
    note: str | None,
    submit_to_erp: bool,
    approver_id: str,
    approver_name: str,
    db: AsyncSession,
) -> dict:
    """管理员人工审批：approve / reject。"""
    from sqlalchemy import select

    from finance_agent.services.db import ExpenseRecord

    action = (action or "").strip().lower()
    if action not in {"approve", "reject"}:
        raise ValueError("action 仅支持 approve / reject")

    row = (
        await db.execute(select(ExpenseRecord).where(ExpenseRecord.expense_id == expense_id))
    ).scalar_one_or_none()
    if not row:
        raise LookupError("报销单不存在")
    if row.status != "pending_approval":
        raise ValueError(f"当前状态为 {row.status}，仅待审批单据可操作")

    row.approver_id = approver_id
    row.approver_name = approver_name
    row.approval_note = (note or "").strip() or None

    if action == "reject":
        await release_budget(row.department, float(row.amount))
        row.status = "rejected"
        row.summary = (
            f"{row.summary or ''}；管理员 {approver_name} 驳回"
            + (f"：{row.approval_note}" if row.approval_note else "")
        ).strip("；")
        await db.commit()
        await db.refresh(row)
        return _expense_row_dict(row)

    row.status = "approved"
    if submit_to_erp and not row.erp_voucher_id:
        erp = await submit_reimbursement(
            expense_id=row.expense_id,
            employee_id=row.employee_id,
            department=row.department,
            amount=float(row.amount),
            category=row.category,
            description=row.description,
        )
        row.erp_voucher_id = erp.get("voucher_id")
    row.summary = (
        f"{row.summary or ''}；管理员 {approver_name} 已批准"
        + (f"：{row.approval_note}" if row.approval_note else "")
        + (f"；ERP {row.erp_voucher_id}" if row.erp_voucher_id else "")
    ).strip("；")
    await db.commit()
    await db.refresh(row)
    return _expense_row_dict(row)


def _expense_row_dict(row) -> dict:
    return {
        "expense_id": row.expense_id,
        "employee_id": row.employee_id,
        "employee_name": row.employee_name,
        "department": row.department,
        "category": row.category,
        "amount": row.amount,
        "description": row.description,
        "status": row.status,
        "risk_level": row.risk_level,
        "invoice_no": row.invoice_no,
        "erp_voucher_id": row.erp_voucher_id,
        "summary": row.summary,
        "approver_id": row.approver_id,
        "approver_name": row.approver_name,
        "approval_note": row.approval_note,
        "receipt_hash": row.receipt_hash,
        "receipt_filename": row.receipt_filename,
        "has_receipt_file": bool(row.receipt_path),
        "paid": bool(getattr(row, "paid", False)),
        "paid_at": row.paid_at.isoformat() if getattr(row, "paid_at", None) else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def run_policy_chat(
    request: AgentChatRequest,
    db: AsyncSession,
) -> AgentChatResponse:
    """财务制度问答（严格依据知识库）。"""
    settings = get_settings()
    session_id = request.session_id or memory.new_session_id()
    model_name = resolve_model_name(request.model_params)
    llm = build_chat_model(request.model_params)

    sources: list[str] = []
    context = ""
    used_rag = False
    if request.use_rag:
        try:
            docs = retrieve(request.message, top_k=request.top_k)
            if docs:
                used_rag = True
                context = format_context(docs)
                sources = [
                    (d.page_content[:120] + "…") if len(d.page_content) > 120 else d.page_content
                    for d in docs
                ]
        except Exception:
            used_rag = False

    history = await memory.get_history(session_id)
    messages: list = [
        SystemMessage(
            content=(
                f"你是「{settings.company_name}」财务制度助手。"
                "只能依据知识库摘录回答报销/审批制度问题；没有则明确说明。"
            )
        )
    ]
    for turn in history:
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn["content"]))

    if context:
        user_content = (
            f"知识库摘录：\n{context}\n\n用户问题：{request.message}\n只根据摘录回答。"
        )
    else:
        user_content = (
            f"用户问题：{request.message}\n知识库未命中。请说明没有相关制度信息，不要编造。"
        )
    messages.append(HumanMessage(content=user_content))

    result = await llm.ainvoke(messages)
    answer = result.content if isinstance(result.content, str) else str(result.content)

    await memory.append_turn(session_id, "user", request.message)
    await memory.append_turn(session_id, "assistant", answer)
    await save_turn(db, session_id=session_id, role="user", content=request.message, model=model_name, used_rag=used_rag)
    await save_turn(db, session_id=session_id, role="assistant", content=answer, model=model_name, used_rag=used_rag)

    return AgentChatResponse(
        session_id=session_id,
        answer=answer,
        model=model_name,
        used_rag=used_rag,
        sources=sources,
    )
