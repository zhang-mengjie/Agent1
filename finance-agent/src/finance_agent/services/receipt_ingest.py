"""发票附件抽取：PDF 文本层 / 扫描件 OCR / 图片 OCR。

【初学者 · 目的】
报销常上传照片/PDF，不能只靠手工粘贴。本模块统一变成「文本」，再交给 receipt_parser。

策略：PDF 先抽文字层；失败再渲染页 OCR；图片直接 OCR（RapidOCR）。

【易错点】
1. 首次 OCR 会下载模型，需 HF_ENDPOINT；失败别误判为「接口挂了」。
2. 扩展名白名单；改后缀骗过检查但内容不是图会在 PIL/OCR 处失败。
3. 扫描 PDF 依赖 pypdfium2；只装 pypdf 不够。
4. OCR 乱码时解析置信度低，风控可能抬高——可人工改 receipt_text 再提交。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from finance_agent.services.pdf_ingest import extract_pdf_text

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_PDF_EXTS = {".pdf"}

_ocr_engine: Any | None = None


def _suffix(filename: str) -> str:
    name = (filename or "").lower().strip()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def supported_receipt_filename(filename: str) -> bool:
    ext = _suffix(filename)
    return ext in _IMAGE_EXTS or ext in _PDF_EXTS


def _get_ocr() -> Any:
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def ocr_image_bytes(data: bytes) -> str:
    """对图片字节做 OCR，返回拼接文本。"""
    if not data:
        raise ValueError("图片内容为空")
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("缺少 pillow，无法处理图片发票") from exc

    try:
        import numpy as np

        img = Image.open(BytesIO(data)).convert("RGB")
        arr = np.asarray(img)
    except Exception as exc:
        raise ValueError(f"无法打开图片: {exc}") from exc

    engine = _get_ocr()
    result, _ = engine(arr)
    if not result:
        raise ValueError("OCR 未识别到文字，请换更清晰的发票图或改用票据文本")
    lines = [str(item[1]).strip() for item in result if item and len(item) >= 2 and str(item[1]).strip()]
    text = "\n".join(lines).strip()
    if not text:
        raise ValueError("OCR 结果为空")
    return text


def ocr_pdf_pages(data: bytes, *, max_pages: int = 5) -> str:
    """将 PDF 页渲染为图后 OCR（扫描件发票）。"""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ValueError("缺少 pypdfium2，无法 OCR 扫描版 PDF") from exc

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ValueError(f"无法打开 PDF: {exc}") from exc

    parts: list[str] = []
    n = min(len(doc), max_pages)
    for i in range(n):
        page = doc[i]
        bitmap = page.render(scale=2)
        pil = bitmap.to_pil()
        buf = BytesIO()
        pil.save(buf, format="PNG")
        try:
            parts.append(ocr_image_bytes(buf.getvalue()))
        except ValueError:
            continue
    text = "\n\n".join(p for p in parts if p).strip()
    if not text:
        raise ValueError("扫描 PDF OCR 未得到可用文字")
    return text


def extract_receipt_text(data: bytes, *, filename: str = "receipt.pdf") -> dict[str, str]:
    """从发票附件提取文本。

    返回: {"text", "method", "filename"}
    method: pdf_text | pdf_ocr | image_ocr
    """
    if not data:
        raise ValueError("附件内容为空")
    ext = _suffix(filename)
    if ext in _PDF_EXTS:
        try:
            text = extract_pdf_text(data, filename=filename)
            return {"text": text, "method": "pdf_text", "filename": filename}
        except ValueError:
            text = ocr_pdf_pages(data)
            return {"text": text, "method": "pdf_ocr", "filename": filename}

    if ext in _IMAGE_EXTS:
        text = ocr_image_bytes(data)
        return {"text": text, "method": "image_ocr", "filename": filename}

    raise ValueError("仅支持发票 PDF 或图片（png/jpg/jpeg/webp/bmp/tif）")
