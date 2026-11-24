"""HTTP 路由：鉴权、报销审批、制度入库/问答。

【初学者 · 目的】
用 Depends(CurrentUser / AdminUser) 做权限门闩：
- 写制度 / 审批 → 必须 admin
- 列表：用户只看自己；管理员可看全量或 status=pending_approval

【易错点】
1. 未登录调业务接口 → 401；用户调审批 → 403。
2. submit-file 是 multipart；Content-Type 不要手写 boundary，交给浏览器/FormData。
3. 列表 mine=true 时管理员也只看本人，别和「全部单据」搞混。
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_agent.agent import decide_expense_manual, run_expense_pipeline, run_policy_chat
from finance_agent.config import get_settings, reload_settings
from finance_agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentListResponse,
    DocumentStatsResponse,
    ExpenseSubmitRequest,
    ExpenseSubmitResponse,
    HealthResponse,
)
from finance_agent.schemas.auth import (
    ExpenseDecideRequest,
    ExpensePaidRequest,
    LoginRequest,
    LoginResponse,
    UserInfo,
)
from finance_agent.schemas.expense import ReceiptParseResponse
from finance_agent.services.auth import (
    AdminUser,
    CurrentUser,
    authenticate,
    create_session,
    destroy_session,
    list_demo_accounts,
)
from finance_agent.services.db import ExpenseRecord, get_session, ping_db
from finance_agent.services.expense_export import build_forms_csv_utf8_bom, build_forms_xlsx
from finance_agent.services.pdf_ingest import extract_pdf_text
from finance_agent.services.rag import get_chunk_stats, ingest_texts, list_chunks
from finance_agent.services.receipt_ingest import extract_receipt_text, supported_receipt_filename
from finance_agent.services.receipt_parser import parse_receipt_text
from finance_agent.services.receipt_store import (
    content_hash,
    delete_receipt_folder,
    ensure_filename_suffix,
    guess_receipt_media_type,
    resolve_receipt_path,
)
from finance_agent.services.redis_memory import memory

router = APIRouter()


def _row_brief(r: ExpenseRecord) -> dict:
    return {
        "expense_id": r.expense_id,
        "employee_id": r.employee_id,
        "employee_name": r.employee_name,
        "department": r.department,
        "category": r.category,
        "amount": r.amount,
        "description": r.description,
        "status": r.status,
        "risk_level": r.risk_level,
        "invoice_no": r.invoice_no,
        "erp_voucher_id": r.erp_voucher_id,
        "summary": r.summary,
        "approver_name": r.approver_name,
        "approval_note": r.approval_note,
        "receipt_hash": r.receipt_hash,
        "receipt_filename": r.receipt_filename,
        "has_receipt_file": bool(r.receipt_path),
        "paid": bool(getattr(r, "paid", False)),
        "paid_at": r.paid_at.isoformat() if getattr(r, "paid_at", None) else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _apply_expense_filters(
    stmt,
    *,
    status: str | None,
    paid: bool | None,
    department: str | None,
    employee_id: str | None,
    q: str | None,
    date_from: str | None,
    date_to: str | None,
):
    if status:
        stmt = stmt.where(ExpenseRecord.status == status.strip())
    if paid is not None:
        stmt = stmt.where(ExpenseRecord.paid.is_(paid))
    if department:
        stmt = stmt.where(ExpenseRecord.department == department.strip())
    if employee_id:
        stmt = stmt.where(ExpenseRecord.employee_id == employee_id.strip())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (ExpenseRecord.expense_id.ilike(like))
            | (ExpenseRecord.employee_name.ilike(like))
            | (ExpenseRecord.invoice_no.ilike(like))
            | (ExpenseRecord.description.ilike(like))
        )
    if date_from:
        try:
            d0 = date_cls.fromisoformat(date_from.strip())
            stmt = stmt.where(ExpenseRecord.created_at >= datetime.combine(d0, datetime.min.time()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="date_from 格式应为 YYYY-MM-DD") from exc
    if date_to:
        try:
            d1 = date_cls.fromisoformat(date_to.strip())
            # 含结束日当天：用次日 0 点作为上界
            end = datetime.combine(d1 + timedelta(days=1), datetime.min.time())
            stmt = stmt.where(ExpenseRecord.created_at < end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="date_to 格式应为 YYYY-MM-DD") from exc
    return stmt


async def _load_receipt_bytes(file: UploadFile) -> tuple[bytes, str]:
    s = get_settings()
    filename = file.filename or "receipt.bin"
    if not supported_receipt_filename(filename):
        raise HTTPException(status_code=400, detail="仅支持发票 PDF 或图片（png/jpg/jpeg/webp/bmp/tif）")
    data = await file.read()
    if not data or len(data) > s.max_receipt_bytes:
        raise HTTPException(status_code=400, detail="发票文件无效或过大")
    return data, filename


async def _read_receipt_upload(file: UploadFile) -> dict[str, str]:
    data, filename = await _load_receipt_bytes(file)
    try:
        extracted = extract_receipt_text(data, filename=filename)
        extracted["receipt_hash"] = content_hash(data)
        return extracted
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"发票解析失败: {exc}") from exc


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok",
        app=s.app_name,
        postgres=await ping_db(),
        redis=await memory.ping(),
        llm_model=s.llm_model,
    )


@router.get("/auth/demo-users", tags=["auth"])
async def demo_users() -> dict:
    return {"items": list_demo_accounts()}


@router.post("/auth/login", response_model=LoginResponse, tags=["auth"])
async def login(request: LoginRequest) -> LoginResponse:
    user = authenticate(request.username, request.password)
    token = await create_session(user)
    return LoginResponse(token=token, user=user)


@router.post("/auth/logout", tags=["auth"])
async def logout(user: CurrentUser, authorization: str | None = None) -> dict:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if token:
        await destroy_session(token)
    return {"ok": True, "username": user.username}


@router.get("/auth/me", response_model=UserInfo, tags=["auth"])
async def me(user: CurrentUser) -> UserInfo:
    return user


@router.post("/expenses/submit", response_model=ExpenseSubmitResponse, tags=["expense"])
async def submit_expense(
    request: ExpenseSubmitRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
) -> ExpenseSubmitResponse:
    """JSON 提交（无原件）。生产环境请优先用 /expenses/submit-file 上传票据。"""
    if user.role != "admin":
        request = request.model_copy(
            update={
                "employee_id": user.employee_id,
                "employee_name": user.display_name,
                "department": user.department,
            }
        )
    if not (request.invoice_no or "").strip():
        raise HTTPException(
            status_code=400,
            detail="无票据文件时必须填写发票号；推荐使用「上传票据」接口提交原件",
        )
    return await run_expense_pipeline(request, db)


@router.post("/expenses/parse-receipt", response_model=ReceiptParseResponse, tags=["expense"])
async def parse_receipt_file(
    user: CurrentUser,
    file: UploadFile = File(...),
) -> ReceiptParseResponse:
    _ = user
    extracted = await _read_receipt_upload(file)
    parsed = parse_receipt_text(extracted["text"])
    parsed.source_method = extracted["method"]
    parsed.source_filename = extracted["filename"]
    return ReceiptParseResponse(
        filename=extracted["filename"],
        method=extracted["method"],
        extracted_text=extracted["text"],
        parsed=parsed,
    )


@router.post("/expenses/submit-file", response_model=ExpenseSubmitResponse, tags=["expense"])
async def submit_expense_with_file(
    user: CurrentUser,
    employee_id: str = Form(...),
    employee_name: str = Form(...),
    department: str = Form(...),
    category: str = Form(...),
    amount: float = Form(...),
    description: str = Form(...),
    invoice_no: str | None = Form(default=None),
    receipt_text: str | None = Form(default=None),
    submit_to_erp: bool = Form(default=True),
    receipt: UploadFile = File(..., description="票据原件（必传，同一文件只能报一次）"),
    db: AsyncSession = Depends(get_session),
) -> ExpenseSubmitResponse:
    """上传票据原件并提交；文件内容哈希全局唯一，不可二次提交。"""
    if user.role != "admin":
        employee_id = user.employee_id
        employee_name = user.display_name
        department = user.department

    data, filename = await _load_receipt_bytes(receipt)
    digest = content_hash(data)
    try:
        extracted = extract_receipt_text(data, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"发票解析失败: {exc}") from exc

    text = extracted["text"]
    if (receipt_text or "").strip():
        # 允许用户在 OCR 结果上微调，但不影响文件哈希去重
        text = receipt_text.strip()

    request = ExpenseSubmitRequest(
        employee_id=employee_id.strip(),
        employee_name=employee_name.strip(),
        department=department.strip(),
        category=category.strip(),
        amount=amount,
        description=description.strip(),
        invoice_no=(invoice_no or "").strip() or None,
        receipt_text=text,
        submit_to_erp=submit_to_erp,
        receipt_hash=digest,
        receipt_filename=filename,
    )
    result = await run_expense_pipeline(
        request,
        db,
        receipt_bytes=data,
        receipt_filename=filename,
    )
    result.parsed_receipt.source_method = extracted["method"]
    result.parsed_receipt.source_filename = filename
    if result.steps:
        detail = dict(result.steps[0].detail or {})
        detail["source_method"] = extracted["method"]
        detail["source_filename"] = filename
        detail["receipt_hash"] = digest
        result.steps[0].detail = detail
        result.steps[0].message = (
            f"票据结构化完成（{extracted['method']}），置信度 {result.parsed_receipt.confidence:.2f}"
        )
    return result


@router.post("/expenses/{expense_id}/decide", tags=["expense"])
async def decide_expense(
    expense_id: str,
    body: ExpenseDecideRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """管理员审批待办单据。"""
    try:
        return await decide_expense_manual(
            expense_id=expense_id,
            action=body.action,
            note=body.note,
            submit_to_erp=body.submit_to_erp,
            approver_id=admin.employee_id,
            approver_name=admin.display_name,
            db=db,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/expenses/{expense_id}", tags=["expense"])
async def get_expense(
    expense_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
) -> dict:
    row = (
        await db.execute(select(ExpenseRecord).where(ExpenseRecord.expense_id == expense_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="报销单不存在")
    if user.role != "admin" and row.employee_id != user.employee_id:
        raise HTTPException(status_code=403, detail="无权查看他人单据")
    return _row_brief(row)


@router.get("/expenses/{expense_id}/receipt", tags=["expense"])
async def get_expense_receipt(
    expense_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
) -> FileResponse:
    """下载/预览单张票据原件。"""
    row = (
        await db.execute(select(ExpenseRecord).where(ExpenseRecord.expense_id == expense_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="报销单不存在")
    if user.role != "admin" and row.employee_id != user.employee_id:
        raise HTTPException(status_code=403, detail="无权查看他人票据")
    path = resolve_receipt_path(row.receipt_path)
    if not path:
        raise HTTPException(status_code=404, detail="该单无票据原件")
    download_name = ensure_filename_suffix(row.receipt_filename, path)
    media_type = guess_receipt_media_type(download_name)
    return FileResponse(
        path,
        filename=download_name,
        media_type=media_type,
        content_disposition_type="inline",
    )


@router.get("/expenses", tags=["expense"])
async def list_expenses(
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(default=None),
    paid: bool | None = Query(default=None),
    department: str | None = Query(default=None),
    employee_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="关键词：单号/姓名/发票号/说明"),
    date_from: str | None = Query(default=None, description="上报日起 YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="上报日止 YYYY-MM-DD"),
    mine: bool = Query(default=False, description="普通用户忽略；管理员可仅看本人"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(ExpenseRecord).order_by(ExpenseRecord.id.desc()).limit(limit)
    if user.role != "admin" or mine:
        stmt = stmt.where(ExpenseRecord.employee_id == user.employee_id)
    stmt = _apply_expense_filters(
        stmt,
        status=status,
        paid=paid,
        department=department,
        employee_id=employee_id,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_row_brief(r) for r in rows], "role": user.role}


@router.post("/expenses/{expense_id}/paid", tags=["expense"])
async def set_expense_paid(
    expense_id: str,
    body: ExpensePaidRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """管理员手动标记已打款 / 取消打款。"""
    _ = admin
    row = (
        await db.execute(select(ExpenseRecord).where(ExpenseRecord.expense_id == expense_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="报销单不存在")
    row.paid = bool(body.paid)
    row.paid_at = datetime.now().astimezone() if body.paid else None
    await db.commit()
    await db.refresh(row)
    return _row_brief(row)


@router.delete("/expenses/{expense_id}", tags=["expense"])
async def delete_expense(
    expense_id: str,
    admin: AdminUser,
    db: AsyncSession = Depends(get_session),
) -> dict:
    """管理员删除单据及其票据原件（删除后同一票据可再次提交）。"""
    _ = admin
    row = (
        await db.execute(select(ExpenseRecord).where(ExpenseRecord.expense_id == expense_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="报销单不存在")
    eid = row.expense_id
    await db.delete(row)
    await db.commit()
    delete_receipt_folder(eid)
    return {"ok": True, "expense_id": eid}


@router.get("/admin/expenses/export", tags=["expense"])
async def export_expenses_batch(
    admin: AdminUser,
    limit: int = Query(200, ge=1, le=500),
    status: str | None = Query(default=None),
    paid: bool | None = Query(default=None),
    department: str | None = Query(default=None),
    q: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """管理员批量导出：ZIP 含 forms.xlsx（防乱码）+ UTF-8 BOM CSV + 原件。"""
    _ = admin
    stmt = select(ExpenseRecord).order_by(ExpenseRecord.id.desc()).limit(limit)
    stmt = _apply_expense_filters(
        stmt,
        status=status,
        paid=paid,
        department=department,
        employee_id=None,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )
    rows = (await db.execute(stmt)).scalars().all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        forms = [_row_brief(r) for r in rows]
        zf.writestr("forms.json", json.dumps(forms, ensure_ascii=False, indent=2))
        zf.writestr("forms.xlsx", build_forms_xlsx(forms))
        zf.writestr("forms.csv", build_forms_csv_utf8_bom(forms))

        for r in rows:
            path = resolve_receipt_path(r.receipt_path)
            if not path:
                continue
            fname = ensure_filename_suffix(r.receipt_filename, path)
            arc = f"receipts/{r.expense_id}_{fname}"
            zf.write(path, arcname=arc)

        zf.writestr(
            "README.txt",
            (
                "finance-agent export\n"
                f"exported_at={datetime.now().isoformat(timespec='seconds')}\n"
                f"count={len(rows)}\n"
                "forms.xlsx = Excel（推荐，中文不乱码）\n"
                "forms.csv = UTF-8 BOM，Excel 也可直接打开\n"
                "forms.json = 原始 JSON\n"
                "receipts/ = 票据原件\n"
            ),
        )

    buf.seek(0)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    headers = {"Content-Disposition": f'attachment; filename="expenses-export-{stamp}.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


@router.post("/chat", response_model=AgentChatResponse, tags=["policy"])
async def chat(
    request: AgentChatRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
) -> AgentChatResponse:
    _ = user
    s = get_settings()
    if not (request.model_params.api_key or s.llm_api_key):
        raise HTTPException(status_code=400, detail="未配置 LLM_API_KEY")
    return await run_policy_chat(request, db)


@router.post("/documents", response_model=DocumentIngestResponse, tags=["policy"])
async def ingest_documents(
    request: DocumentIngestRequest,
    admin: AdminUser,
) -> DocumentIngestResponse:
    _ = admin
    s = get_settings()
    try:
        count = ingest_texts(request.texts, source=request.source, metadatas=request.metadatas)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"入库失败: {exc}") from exc
    return DocumentIngestResponse(
        ingested_chunks=count, collection=s.collection_name, source=request.source
    )


@router.post("/documents/pdf", response_model=DocumentIngestResponse, tags=["policy"])
async def ingest_pdf(
    admin: AdminUser,
    file: UploadFile = File(...),
    source: str | None = Form(default=None),
) -> DocumentIngestResponse:
    _ = admin
    s = get_settings()
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 .pdf")
    data = await file.read()
    if not data or len(data) > s.max_pdf_bytes:
        raise HTTPException(status_code=400, detail="文件无效或过大")
    try:
        text = extract_pdf_text(data, filename=filename)
        src = (source or "").strip() or filename
        count = ingest_texts([text], source=src, metadatas=[{"filename": filename, "type": "pdf"}])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF 入库失败: {exc}") from exc
    return DocumentIngestResponse(ingested_chunks=count, collection=s.collection_name, source=src)


@router.get("/documents", response_model=DocumentListResponse, tags=["policy"])
async def list_documents(
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: str | None = None,
) -> DocumentListResponse:
    _ = user
    items = list_chunks(limit=limit, offset=offset, source=source)
    return DocumentListResponse(total_returned=len(items), items=items)


@router.get("/documents/stats", response_model=DocumentStatsResponse, tags=["policy"])
async def documents_stats(user: CurrentUser) -> DocumentStatsResponse:
    _ = user
    s = get_settings()
    stats = get_chunk_stats()
    return DocumentStatsResponse(
        total_chunks=stats["total_chunks"],
        vectorized_chunks=stats["vectorized_chunks"],
        embedding_dims=stats["embedding_dims"],
        sources=stats["sources"],
        collection=s.collection_name,
    )


@router.get("/config/model", tags=["system"])
async def get_model_config(user: CurrentUser) -> dict:
    _ = user
    s = reload_settings()
    return {
        "model": s.llm_model,
        "company_name": s.company_name,
        "auto_approve_limit": s.auto_approve_limit,
        "meal_limit_per_day": s.meal_limit_per_day,
        "travel_hotel_limit": s.travel_hotel_limit,
        "transport_taxi_limit": s.transport_taxi_limit,
        "default_dept_budget": s.default_dept_budget,
        "erp_mock": s.erp_mock,
        "embedding_model": s.embedding_model,
    }
