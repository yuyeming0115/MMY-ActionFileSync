from __future__ import annotations

from pathlib import Path

from PIL import Image

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IGNORED_FILENAMES = {"thumbs.db", ".ds_store", "desktop.ini"}


def build_node_id(source_type: str, relative_path: str) -> str:
    return f"{source_type}:{relative_path or '/'}"


def iter_files_recursively(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return [path for path in root.rglob("*") if path.is_file()]


def is_image_file(path: Path) -> bool:
    """判断路径是否为支持预览与尺寸校验的图片格式。"""
    return path.suffix.lower() in IMAGE_EXTENSIONS


def read_image_dimensions(path: Path) -> tuple[int, int] | None:
    """仅读取图片头部尺寸，异常或非图片返回 None。"""
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width > 0 and height > 0:
                return (int(width), int(height))
    except Exception:  # noqa: BLE001
        return None
    return None
