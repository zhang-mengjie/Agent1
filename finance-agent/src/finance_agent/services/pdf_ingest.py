from io import BytesIO

from pypdf import PdfReader


def extract_pdf_text(data: bytes, *, filename: str = "upload.pdf") -> str:
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise ValueError(f"无法解析 PDF（{filename}）: {exc}") from exc
    parts = []
    for page in reader.pages:
        try:
            t = (page.extract_text() or "").strip()
        except Exception:
            t = ""
        if t:
            parts.append(t)
    content = "\n\n".join(parts).strip()
    if not content:
        raise ValueError(f"PDF 未提取到可用文本: {filename}")
    return content
