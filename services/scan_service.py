from __future__ import annotations

import hashlib
from pathlib import Path

from natsort import natsorted

from models.tree_node import TreeNode
from utils.file_utils import IMAGE_EXTENSIONS, build_node_id
from utils.hash_utils import hash_file


class ScanService:
    def __init__(self, source_type: str) -> None:
        self.source_type = source_type

    def scan(self, root_path: str) -> TreeNode:
        root = Path(root_path)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"目录不存在: {root_path}")
        return self._build_tree(root, root)

    def _build_tree(self, base_root: Path, current: Path) -> TreeNode:
        relative = "" if current == base_root else current.relative_to(base_root).as_posix()
        image_files = self._collect_image_files(current)
        gif_path = self._find_gif(current)
        children_dirs = [path for path in current.iterdir() if path.is_dir()]
        dir_children = [self._build_tree(base_root, child) for child in natsorted(children_dirs, key=lambda path: path.name)]
        image_children = [self._build_image_node(base_root, path) for path in image_files]
        children = dir_children + image_children
        digest = self._build_digest(gif_path, children)
        own_size_bytes = sum(path.stat().st_size for path in image_files)
        children_size_bytes = sum(child.file_size_bytes for child in dir_children)
        return TreeNode(
            id=build_node_id(self.source_type, relative),
            name=current.name,
            relative_path=relative,
            absolute_path=str(current),
            node_type="sequence" if image_files else "folder",
            source_type=self.source_type,
            children=children,
            frame_files=[file.name for file in image_files],
            gif_path=str(gif_path) if gif_path else None,
            file_count=len(image_files),
            file_size_bytes=own_size_bytes + children_size_bytes,
            digest=digest,
            extra={"has_gif": bool(gif_path)},
        )

    def _build_image_node(self, base_root: Path, image_path: Path) -> TreeNode:
        relative = image_path.relative_to(base_root).as_posix()
        file_size = image_path.stat().st_size
        return TreeNode(
            id=build_node_id(self.source_type, relative),
            name=image_path.name,
            relative_path=relative,
            absolute_path=str(image_path),
            node_type="image",
            source_type=self.source_type,
            children=[],
            frame_files=[],
            gif_path=None,
            file_count=1,
            file_size_bytes=file_size,
            digest=self._build_image_digest(image_path),
            extra={},
        )

    def _collect_image_files(self, directory: Path) -> list[Path]:
        files = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
        # 单帧动作（hurt/block/dead）是本项目美术输出的正常形态，1 张图也算序列
        if not files:
            return []
        return natsorted(files, key=lambda path: path.name)

    def _find_gif(self, directory: Path) -> Path | None:
        gifs = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".gif"]
        if not gifs:
            return None
        return natsorted(gifs, key=lambda path: path.name)[0]

    def _build_digest(self, gif_path: Path | None, children: list[TreeNode]) -> str:
        digest = hashlib.blake2b(digest_size=16)
        if gif_path:
            digest.update(gif_path.name.encode("utf-8"))
            digest.update(hash_file(gif_path).encode("ascii"))
        for child in children:
            digest.update(child.relative_path.encode("utf-8"))
            digest.update(child.digest.encode("utf-8"))
        return digest.hexdigest()

    def _build_image_digest(self, image_path: Path) -> str:
        return hash_file(image_path)
