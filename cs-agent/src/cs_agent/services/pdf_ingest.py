"""PDF 文本抽取：仅支持内嵌文字型 PDF；扫描件需先 OCR。"""

from io import BytesIO  # Python 标准库：把 bytes 包装成类文件流，供 pypdf 读取

from pypdf import PdfReader  # pypdf：解析 PDF 文档，逐页提取内嵌文本


def extract_pdf_text(data: bytes, *, filename: str = "upload.pdf") -> str:
    """从 PDF 字节流中抽取可复制文本，逐页拼接。

    Args:
        data: PDF 文件原始字节。
        filename: 仅用于错误信息中的文件名标识。

    Returns:
        str: 各页文本以空行拼接并去除首尾空白。

    Raises:
        ValueError: PDF 无法解析，或未提取到任何可用文本（可能为扫描件，需先 OCR）。
    """
    try:
        reader = PdfReader(BytesIO(data))  # pypdf：从字节流构造 PDF 阅读器对象
    except Exception as exc:
        raise ValueError(f"无法解析 PDF（{filename}）: {exc}") from exc

    parts: list[str] = []
    for page in reader.pages:  # pypdf：遍历 PDF 每一页
        try:
            text = (page.extract_text() or "").strip()  # pypdf：抽取该页内嵌文本（扫描件为空）
        except Exception:
            text = ""
        if text:
            parts.append(text)

    content = "\n\n".join(parts).strip()
    if not content:
        raise ValueError(f"PDF 未提取到可用文本（可能是扫描件）: {filename}")
    return content
