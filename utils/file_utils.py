from __future__ import annotations

from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def build_node_id(source_type: str, relative_path: str) -> str:
    return f"{source_type}:{relative_path or '/'}"


def ensure_cache_dir() -> Path:
    cache_dir = Path(".cache") / "preview_gifs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir.resolve()


def iter_files_recursively(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return [path for path in root.rglob("*") if path.is_file()]
