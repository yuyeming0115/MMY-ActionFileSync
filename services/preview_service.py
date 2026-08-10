from __future__ import annotations

from pathlib import Path

from PIL import Image

from models.preview_item import PreviewItem
from models.tree_node import TreeNode


class PreviewService:
    def build_preview(self, side: str, relative_path: str, node: TreeNode | None) -> PreviewItem:
        if not node:
            return PreviewItem(side=side, relative_path=relative_path, source_path=None, cache_path=None, status="missing", message=f"{'左侧' if side == 'left' else '右侧'}缺失")
        if not node.is_previewable():
            return PreviewItem(side=side, relative_path=relative_path, source_path=node.absolute_path, cache_path=None, status="not_previewable", message="当前节点不可预览")

        source_dir = Path(node.absolute_path or "")

        if node.node_type == "image":
            width, height, _ = self._read_image_meta(source_dir)
            return PreviewItem(side=side, relative_path=relative_path, source_path=str(source_dir), cache_path=str(source_dir), frame_paths=[str(source_dir)], frame_count=1, width=width, height=height, status="ready", message="单帧图片")

        frame_paths = [str(source_dir / name) for name in node.frame_files if (source_dir / name).exists()]
        if frame_paths:
            width, height, _ = self._read_image_meta(Path(frame_paths[0]))
            return PreviewItem(side=side, relative_path=relative_path, source_path=str(source_dir), cache_path=None, frame_paths=frame_paths, frame_interval_ms=80, frame_count=len(frame_paths), width=width, height=height, status="ready", message="使用序列帧预览")

        if node.gif_path and Path(node.gif_path).exists():
            width, height, frame_count = self._read_image_meta(Path(node.gif_path))
            return PreviewItem(side=side, relative_path=relative_path, source_path=str(source_dir), cache_path=node.gif_path, frame_count=frame_count, width=width, height=height, status="ready", message="使用目录内 GIF 预览")

        return PreviewItem(side=side, relative_path=relative_path, source_path=str(source_dir), cache_path=None, status="error", message="未找到可用预览帧")

    def _read_image_meta(self, image_path: Path) -> tuple[int, int, int]:
        with Image.open(image_path) as image:
            return image.size[0], image.size[1], getattr(image, "n_frames", 1)
