"""报销申请与审批流水线的数据结构。

【初学者 · 目的】用 Pydantic 做 API 合同：校验金额>0、补齐默认值、生成 OpenAPI。
【易错点】改字段要同步前端与 MCP；gt=0 会拒绝 0 元；category 拼错只当字符串不会自动纠正。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExpenseSubmitRequest(BaseModel):
    employee_id: str = Field(..., description="员工工号")
    employee_name: str = Field(..., description="员工姓名")
    department: str = Field(..., description="部门，如 研发中心")
    category: str = Field(
        ...,
        description="费用类别：meal/travel/transport/office/other",
    )
    amount: float = Field(..., gt=0, description="申报金额（元）")
    currency: str = "CNY"
    description: str = Field(..., min_length=1, max_length=2000)
    invoice_no: str | None = Field(default=None, description="发票号码")
    receipt_text: str | None = Field(
        default=None,
        description="票据 OCR/粘贴文本；用于结构化抽取",
    )
    expense_date: str | None = Field(default=None, description="费用发生日 YYYY-MM-DD")
    submit_to_erp: bool = Field(default=True, description="通过后是否提交 ERP")
    # 由上传接口填入：票据原件内容哈希（同一文件只能报一次）
    receipt_hash: str | None = Field(default=None, description="票据文件 SHA256")
    receipt_filename: str | None = Field(default=None, description="原始文件名")


class ParsedReceipt(BaseModel):
    vendor: str | None = None
    amount: float | None = None
    invoice_no: str | None = None
    tax_no: str | None = None
    date: str | None = None
    raw_excerpt: str | None = None
    confidence: float = 0.0
    source_method: str | None = Field(
        default=None,
        description="文本来源：paste / pdf_text / pdf_ocr / image_ocr",
    )
    source_filename: str | None = None


class ReceiptParseResponse(BaseModel):
    filename: str
    method: str
    extracted_text: str
    parsed: ParsedReceipt


class PipelineStepResult(BaseModel):
    step: str
    ok: bool
    message: str
    detail: dict = Field(default_factory=dict)


class ApprovalStep(BaseModel):
    role: str
    name: str
    required: bool = True


class ExpenseSubmitResponse(BaseModel):
    expense_id: str
    status: str = Field(description="auto_approved / pending_approval / rejected")
    risk_level: str
    need_manual_review: bool
    parsed_receipt: ParsedReceipt
    steps: list[PipelineStepResult]
    approval_chain: list[ApprovalStep]
    policy_sources: list[str] = Field(default_factory=list)
    erp_voucher_id: str | None = None
    summary: str
    receipt_hash: str | None = None
    receipt_filename: str | None = None
    has_receipt_file: bool = False
