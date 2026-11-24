"""票据原件落盘与哈希。

【初学者 · 目的】
OCR 只得到文本，审计/报销凭证必须保留原始图片或 PDF。
用文件内容 SHA256 做「同一张票只能报一次」。

【易错点】
1. 路径用 expense_id 隔离，勿用用户原始文件名直接当相对路径（防路径穿越）。
2. data/receipts 要进 .gitignore，别把票据提交进 git。
3. 哈希按「文件字节」算，改一个像素就变；发票号去重仍要并行。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from finance_agent.config import PROJECT_ROOT, get_settings

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


def receipt_root() -> Path:
    s = get_settings()
    root = Path(s.receipt_storage_dir)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_MEDIA_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _safe_filename(name: str) -> str:
    base = Path(name or "receipt.bin").name
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "receipt.bin"
    return cleaned[:120]


def guess_receipt_media_type(filename: str | None) -> str:
    """按扩展名推断 MIME，供预览时浏览器正确打开。"""
    suffix = Path(filename or "").suffix.lower()
    return _MEDIA_BY_SUFFIX.get(suffix, "application/octet-stream")


def ensure_filename_suffix(filename: str | None, path: Path) -> str:
    """保证下载/预览文件名带后缀（优先库内文件名，否则用磁盘文件名）。"""
    name = (filename or "").strip() or path.name
    name = Path(name).name
    if not Path(name).suffix and path.suffix:
        name = f"{name}{path.suffix}"
    return name or f"receipt{path.suffix or '.bin'}"


def save_receipt_file(
    *,
    expense_id: str,
    data: bytes,
    original_filename: str,
) -> dict[str, str]:
    """保存原件，返回 path/hash/filename 等元数据（相对项目根的路径字符串）。"""
    if not data:
        raise ValueError("票据文件为空")
    digest = content_hash(data)
    safe = _safe_filename(original_filename)
    folder = receipt_root() / expense_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / safe
    # 同名覆盖无妨：同一 expense_id 只应保存一次
    dest.write_bytes(data)
    meta = {
        "expense_id": expense_id,
        "receipt_hash": digest,
        "receipt_filename": safe,
        "receipt_path": str(dest.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "size": str(len(data)),
    }
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def delete_receipt_folder(expense_id: str) -> None:
    """删除某单号下全部原件目录。"""
    folder = receipt_root() / expense_id
    if not folder.is_dir():
        return
    import shutil

    shutil.rmtree(folder, ignore_errors=True)


def resolve_receipt_path(relative_or_abs: str | None) -> Path | None:
    if not relative_or_abs:
        return None
    p = Path(relative_or_abs)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    try:
        p = p.resolve()
        root = receipt_root().resolve()
        p.relative_to(root)  # 防路径穿越
    except Exception:
        return None
    return p if p.is_file() else None
