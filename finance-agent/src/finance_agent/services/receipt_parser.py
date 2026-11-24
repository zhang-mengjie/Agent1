"""票据结构化：从 OCR/粘贴文本中抽取金额、发票号、商户等。

【初学者 · 目的】
把非结构化票面文字变成 ParsedReceipt，供表单自动填充与风控使用。

【易错点】
1. 医疗财政票据用「票据号码」不是「发票号码」；正则必须写完整「号码」，
   若只写「票据号」会吃掉「号」后卡在「码」上，号码抽不出来。
2. 金额优先取「（小写）」/「价税合计」，避免抓到自付/其他支付等小数。
3. 自动填充时前端应以识别结果覆盖默认值。
"""

from __future__ import annotations

import re

from finance_agent.schemas.expense import ParsedReceipt


def _normalize(raw: str) -> str:
    return (
        raw.replace("：", ":")
        .replace("￥", "¥")
        .replace("，", ",")
        .replace("（", "(")
        .replace("）", ")")
    )


def _extract_invoice_no(text: str) -> str | None:
    """抽取发票号 / 票据号码（财政医疗票常见）。"""
    # 长标签必须排在短标签前，避免「票据号」半截匹配
    patterns = [
        r"(?:发票号码|票据号码|发票号|票据号|票据号吗|发票号吗|票号|Invoice\s*No\.?|Invoice\s*Number)\s*:?\s*([0-9A-Za-z\-]{6,40})",
        # 标签与号码拆行
        r"(?:发票号码|票据号码|发票号|票据号)\s*:?\s*[\r\n]+\s*([0-9A-Za-z\-]{6,40})",
        # OCR 把「号码」识别成单独一行旁边的纯数字（8–20 位）
        r"(?:发票号码|票据号码)\D{0,8}([0-9]{8,20})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)

    # 仍无标签时：财政电子票常见「票据代码」旁的号码段
    m_code = re.search(r"票据代码\s*:?\s*([0-9]{8,12})", text)
    m_near = re.search(r"票据号码\s*:?\s*([0-9]{8,20})", text)
    if m_near:
        return m_near.group(1)
    if m_code and ("医疗" in text or "财政" in text):
        # 仅有代码时不把代码当号码；再找同段 10 位票号
        m10 = re.search(r"(?<![0-9])(\d{10})(?![0-9])", text)
        if m10 and m10.group(1) != m_code.group(1):
            return m10.group(1)
    return None


def _extract_amount(text: str) -> float | None:
    """抽取应付/合计金额，避开自付、补助等明细。"""
    # 1) 小写合计（医疗财政票：（小写）72.00）
    m_small = re.search(
        r"(?:金额合计|价税合计|合计金额).{0,40}?\(小写\)\s*:?\s*(?:¥)?\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m_small:
        return float(m_small.group(1))

    m_small2 = re.search(r"\(小写\)\s*:?\s*(?:¥)?\s*([0-9]+(?:\.[0-9]{1,2})?)", text)
    if m_small2:
        return float(m_small2.group(1))

    # 2) 带标签的合计
    m_amt = re.search(
        r"(?:价税合计|合计金额|金额合计|总计|Total(?:\s*Amount)?)\s*:?\s*"
        r"(?:RMB|CNY|元|¥)?\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if m_amt:
        return float(m_amt.group(1))

    # 3) 「金额: 72.00」但排除自付/自费/支付/补助
    for m in re.finditer(
        r"(金额|Total|Amount|¥)\s*:?\s*(?:RMB|CNY|元)?\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text,
        re.IGNORECASE,
    ):
        start = max(0, m.start() - 6)
        ctx = text[start : m.start()]
        if any(bad in ctx for bad in ("自付", "自费", "支付", "补助", "先行")):
            continue
        return float(m.group(2))

    # 4) 回退：取文本前半段中最大的两位小数（票面主金额通常靠前）
    head = text[: max(120, len(text) // 2)]
    nums = [float(x) for x in re.findall(r"(?<![0-9])([0-9]{1,7}\.[0-9]{2})(?![0-9])", head)]
    if nums:
        return max(nums)
    nums_all = [float(x) for x in re.findall(r"(?<![0-9])([0-9]{1,7}\.[0-9]{2})(?![0-9])", text)]
    return max(nums_all) if nums_all else None


def parse_receipt_text(text: str | None, *, fallback_amount: float | None = None) -> ParsedReceipt:
    raw = (text or "").strip()
    if not raw:
        return ParsedReceipt(
            amount=fallback_amount,
            confidence=0.2 if fallback_amount else 0.0,
            raw_excerpt=None,
        )

    normalized = _normalize(raw)
    amount = _extract_amount(normalized)
    invoice_no = _extract_invoice_no(normalized)

    tax_no = None
    m_tax = re.search(
        r"(?:纳税人识别号|税号|统一社会信用代码|Tax\s*No\.?)\s*:?\s*([0-9A-Za-z*]{10,30})",
        normalized,
        re.IGNORECASE,
    )
    if m_tax:
        tax_no = m_tax.group(1)

    date = None
    m_date = re.search(
        r"(?:开票日期|就诊日期|Date|日期)\s*:?\s*(20\d{2}[-/\.年]?\d{1,2}[-/\.月]?\d{1,2})",
        normalized,
        re.IGNORECASE,
    ) or re.search(r"(20\d{2}[-/\.年]\d{1,2}[-/\.月]\d{1,2})", normalized)
    if m_date:
        d = m_date.group(1)
        if re.fullmatch(r"20\d{6}", d):
            date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        else:
            date = (
                d.replace("年", "-")
                .replace("月", "-")
                .replace("日", "")
                .replace("/", "-")
                .replace(".", "-")
            )

    vendor = None
    m_vendor = re.search(
        r"(?:收款单位|商户|销售方|开票方|店名|Merchant|Vendor)\s*:?\s*([^\n\r]{2,40})",
        normalized,
        re.IGNORECASE,
    )
    if m_vendor:
        vendor = m_vendor.group(1).strip()

    conf = 0.4
    if amount is not None:
        conf += 0.25
    if invoice_no:
        conf += 0.2
    if date:
        conf += 0.1
    if vendor:
        conf += 0.05

    if amount is None and fallback_amount is not None:
        amount = fallback_amount

    return ParsedReceipt(
        vendor=vendor,
        amount=amount,
        invoice_no=invoice_no,
        tax_no=tax_no,
        date=date,
        raw_excerpt=raw[:240],
        confidence=min(conf, 0.99),
    )
