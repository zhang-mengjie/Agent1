"""从 PDF 字节提取文本（制度/文档入库用）。

【初学者 · 目的】演示「上传 PDF → 文本 → 再走向量入库」。

【易错点】
1. 扫描件 PDF 往往没有文字层 → extract_text 为空（finance-agent 发票场景会再走 OCR）。
2. 加密 PDF / 损坏文件会抛错，调用方应转成 400 而不是 500 堆栈。
3. 超大文件先在路由层用 max_pdf_bytes 拦住，避免内存爆。
"""

from io import BytesIO

from pypdf import PdfReader


def extract_pdf_text(data: bytes, *, filename: str = "upload.pdf") -> str:
    """从 PDF 字节提取纯文本。"""
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise ValueError(f"无法解析 PDF（{filename}）: {exc}") from exc

    parts: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if text:
            parts.append(text)

    content = "\n\n".join(parts).strip()
    if not content:
        raise ValueError(f"PDF 未提取到可用文本（可能是扫描件/图片型 PDF）: {filename}")
    return content
