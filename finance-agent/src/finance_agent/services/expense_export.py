"""报销单导出：Excel（openpyxl）+ UTF-8 BOM CSV，避免 Excel 中文乱码。"""

from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import Workbook

# 中文表头，Excel 打开更友好
EXCEL_COLUMNS: list[tuple[str, str]] = [
    ("expense_id", "单号"),
    ("created_at", "上报日期"),
    ("employee_id", "工号"),
    ("employee_name", "姓名"),
    ("department", "部门"),
    ("category", "类别"),
    ("amount", "金额"),
    ("description", "费用说明"),
    ("invoice_no", "发票号"),
    ("status", "审批状态"),
    ("paid", "已打款"),
    ("paid_at", "打款时间"),
    ("risk_level", "风险"),
    ("erp_voucher_id", "ERP凭证"),
    ("receipt_filename", "票据文件名"),
    ("has_receipt_file", "有原件"),
    ("approver_name", "审批人"),
    ("approval_note", "审批意见"),
    ("summary", "摘要"),
]


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "是" if v else "否"
    return v


def build_forms_xlsx(forms: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "报销单据"
    headers = [h for _, h in EXCEL_COLUMNS]
    ws.append(headers)
    for item in forms:
        ws.append([_cell(item.get(k)) for k, _ in EXCEL_COLUMNS])
    for col in ws.columns:
        max_len = 0
        letter = col[0].column_letter
        for cell in col:
            max_len = max(max_len, len(str(cell.value or "")))
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 40)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def build_forms_csv_utf8_bom(forms: list[dict]) -> bytes:
    """带 BOM 的 UTF-8 CSV，Excel 直接双击也不会乱码。"""
    buf = io.StringIO()
    fieldnames = [k for k, _ in EXCEL_COLUMNS]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    # 第一行写中文表头
    writer.writerow({k: h for k, h in EXCEL_COLUMNS})
    for item in forms:
        writer.writerow({k: _cell(item.get(k)) for k, _ in EXCEL_COLUMNS})
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
