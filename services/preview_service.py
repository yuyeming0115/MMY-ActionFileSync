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

        # 图集条目：一张打包图集就是一个整体，按用户诉求不做切帧动画还原，
        # 直接显示整张 png；plist 只作元信息提示。
        # 注意 atlas 节点的 absolute_path 指向「文件本身」而非所在目录，
        # 因此这里不能再往上拼文件名。
        if node.node_type == "atlas":
            return self._build_atlas_preview(side, relative_path, node, source_dir)

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

    def _build_atlas_preview(self, side: str, relative_path: str, node: TreeNode, source_dir: Path) -> PreviewItem:
        """图集条目预览：整张图集当单图显示。

        ``source_dir`` 实为 atlas 节点的绝对文件路径（png 自身）。
        若该 png 已不存在，则回退到「用 png 文件名去父目录里找」，
        兼容两侧大小写不一致导致的路径差异。
        """
        extra = node.extra or {}
        png_name = str(extra.get("preview_png") or "")
        anchor = source_dir
        if anchor.name.casefold() != png_name.casefold() and png_name:
            candidate = anchor.parent / png_name
            if candidate.exists():
                anchor = candidate
        if not anchor.exists() or not anchor.is_file():
            missing = "缺少 png" if not png_name else "png 不存在"
            return PreviewItem(
                side=side,
                relative_path=relative_path,
                source_path=str(source_dir),
                cache_path=None,
                status="error",
                message=f"图集{missing}，无法预览",
            )
        try:
            width, height, _ = self._read_image_meta(anchor)
        except Exception:  # noqa: BLE001 - 损坏/非图片文件一律按预览失败处理
            return PreviewItem(
                side=side,
                relative_path=relative_path,
                source_path=str(anchor),
                cache_path=None,
                status="error",
                message="图集无法读取为图片",
            )
        notes: list[str] = ["整张图集（未切帧）"]
        if not extra.get("has_plist"):
            notes.append("无 plist")
        return PreviewItem(
            side=side,
            relative_path=relative_path,
            source_path=str(anchor),
            cache_path=str(anchor),
            frame_paths=[str(anchor)],
            frame_interval_ms=80,
            frame_count=1,
            width=width,
            height=height,
            status="ready",
            message=" · ".join(notes),
        )

    def _read_image_meta(self, image_path: Path) -> tuple[int, int, int]:
        with Image.open(image_path) as image:
            return image.size[0], image.size[1], getattr(image, "n_frames", 1)
