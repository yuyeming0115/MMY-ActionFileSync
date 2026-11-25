"""UI 资源扫描与双策略比对服务。

支持两种比对策略：
1. ``relative``：按相对路径 1:1 比对（适合平铺对平铺、同构多级目录树）。
2. ``filename``：按文件名跨层级定位（适合左多层→右平铺、左散图→右多级目录树回填），
   并自动检测右侧重名冲突与左侧多源同目标碰撞。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from natsort import natsorted

from models.compare_result import ComparePair, CompareResult
from models.sync_options import UI_MATCH_FILENAME, UI_MATCH_RELATIVE
from models.tree_node import TreeNode
from services.scan_service import ScanCancelledError
from utils.file_utils import IGNORED_FILENAMES, IMAGE_EXTENSIONS, build_node_id, read_image_dimensions
from utils.hash_utils import HashCache, files_equal, fingerprints_equal

_PROGRESS_INTERVAL = 50


class UIScanService:
    """递归扫描 UI 资源目录，把每个交付文件映射为独立的 ``ui_asset`` 节点。"""

    node_type = "ui_asset"

    def __init__(
        self,
        source_type: str,
        *,
        include_non_images: bool = False,
        hash_cache: HashCache | None = None,
    ) -> None:
        self.source_type = source_type
        self._include_non_images = include_non_images
        self._hash_cache = hash_cache
        self._cancel_token = None

    def scan(self, root_path: str, cancel_token: object | None = None) -> TreeNode:
        root = Path(root_path)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"目录不存在: {root_path}")
        self._cancel_token = cancel_token
        try:
            return self._build_root(root)
        finally:
            self._cancel_token = None

    def _check_cancelled(self) -> None:
        if self._cancel_token and self._cancel_token.is_cancelled():
            raise ScanCancelledError("扫描已取消")

    def _build_root(self, root: Path) -> TreeNode:
        children: list[TreeNode] = []
        total_size = 0
        scanned = 0

        for dirpath, dirnames, filenames in os.walk(root):
            self._check_cancelled()
            # 原地跳过 .svn / .git / .workbuddy 等隐藏或版本控制目录
            dirnames[:] = natsorted(
                [name for name in dirnames if not name.startswith(".")],
                key=lambda value: value.casefold(),
            )
            current_dir = Path(dirpath)
            for filename in natsorted(filenames, key=lambda value: value.casefold()):
                scanned += 1
                if scanned % _PROGRESS_INTERVAL == 0:
                    self._check_cancelled()
                if filename.startswith(".") or filename.lower() in IGNORED_FILENAMES:
                    continue
                file_path = current_dir / filename
                ext = file_path.suffix.lower()
                is_image = ext in IMAGE_EXTENSIONS
                if not self._include_non_images and not is_image:
                    continue
                try:
                    size = file_path.stat().st_size
                except OSError:
                    continue
                rel_posix = file_path.relative_to(root).as_posix()
                digest = self._build_file_digest(rel_posix, size)
                node = TreeNode(
                    id=build_node_id(self.source_type, rel_posix),
                    name=filename,
                    relative_path=rel_posix,
                    absolute_path=str(file_path),
                    node_type=self.node_type,
                    source_type=self.source_type,
                    children=[],
                    frame_files=[filename],
                    gif_path=None,
                    file_count=1,
                    file_size_bytes=size,
                    digest=digest,
                    extra={
                        "layout": "ui",
                        "is_image": is_image,
                        "ext": ext,
                    },
                )
                children.append(node)
                total_size += size

        children = natsorted(children, key=lambda item: item.relative_path.casefold())
        root_digest = self._build_root_digest(children)
        return TreeNode(
            id=build_node_id(self.source_type, ""),
            name=root.name,
            relative_path="",
            absolute_path=str(root),
            node_type="ui_root",
            source_type=self.source_type,
            children=children,
            frame_files=[],
            file_count=len(children),
            file_size_bytes=total_size,
            digest=root_digest,
            extra={
                "layout": "ui",
                "entry_count": len(children),
                "include_non_images": self._include_non_images,
            },
        )

    @staticmethod
    def _build_file_digest(relative_path: str, size: int) -> str:
        digest = hashlib.blake2b(digest_size=16)
        digest.update(relative_path.casefold().encode("utf-8"))
        digest.update(b":")
        digest.update(str(size).encode("ascii"))
        return digest.hexdigest()

    @staticmethod
    def _build_root_digest(children: list[TreeNode]) -> str:
        digest = hashlib.blake2b(digest_size=16)
        for child in children:
            digest.update(child.relative_path.encode("utf-8"))
            digest.update(child.digest.encode("utf-8"))
        return digest.hexdigest()


class UICompareService:
    """UI 资源双策略比对服务。"""

    def compare(
        self,
        left_root: TreeNode,
        right_root: TreeNode,
        *,
        match_strategy: str = UI_MATCH_RELATIVE,
        target_overrides: dict[str, str] | None = None,
        hash_cache: HashCache | None = None,
    ) -> CompareResult:
        if match_strategy == UI_MATCH_FILENAME:
            return self._compare_by_filename(
                left_root,
                right_root,
                target_overrides=target_overrides,
                hash_cache=hash_cache,
            )
        return self._compare_by_relative(left_root, right_root, hash_cache=hash_cache)

    def _compare_by_relative(
        self,
        left_root: TreeNode,
        right_root: TreeNode,
        *,
        hash_cache: HashCache | None = None,
    ) -> CompareResult:
        left_map = {node.relative_path.casefold(): node for node in left_root.children if node.relative_path}
        right_map = {node.relative_path.casefold(): node for node in right_root.children if node.relative_path}
        pairs: dict[str, ComparePair] = {}

        for key in sorted(set(left_map) | set(right_map)):
            left = left_map.get(key)
            right = right_map.get(key)
            extra: dict[str, object] = {"layout": "ui"}

            if left and not right:
                status = "only_left"
                target_rel = left.relative_path
            elif right and not left:
                status = "only_right"
                target_rel = right.relative_path
            elif left and right:
                status = "same" if self._nodes_equal(left, right, hash_cache=hash_cache) else "different"
                target_rel = right.relative_path
                src_dim, dst_dim = self._read_pair_dimensions(left, right)
                if src_dim is not None:
                    extra["source_dimensions"] = src_dim
                if dst_dim is not None:
                    extra["target_dimensions"] = dst_dim
            else:
                status = "unknown"
                target_rel = key

            display_path = left.relative_path if left else right.relative_path if right else key
            extra["target_relative_path"] = target_rel
            extra["display_relative_path"] = display_path

            if left is not None:
                left.compare_status = status
            if right is not None:
                right.compare_status = status
            pairs[display_path.casefold()] = ComparePair(
                relative_path=display_path,
                left=left,
                right=right,
                status=status,
                extra=extra,
            )
        return CompareResult(left_root=left_root, right_root=right_root, node_map=pairs)

    def _compare_by_filename(
        self,
        left_root: TreeNode,
        right_root: TreeNode,
        *,
        target_overrides: dict[str, str] | None = None,
        hash_cache: HashCache | None = None,
    ) -> CompareResult:
        overrides = {
            key.casefold(): str(value).replace("\\", "/")
            for key, value in (target_overrides or {}).items()
            if value
        }
        right_nodes = [node for node in right_root.children if node.relative_path]
        right_by_rel = {node.relative_path.casefold(): node for node in right_nodes}
        right_by_name: dict[str, list[TreeNode]] = {}
        for node in right_nodes:
            right_by_name.setdefault(node.name.casefold(), []).append(node)
        for group in right_by_name.values():
            group.sort(key=lambda item: item.relative_path.casefold())

        # 第一遍：为每个左侧文件寻找目标节点或记录重名候选
        pending: list[dict[str, object]] = []
        target_claims: dict[str, list[dict[str, object]]] = {}

        for left in left_root.children:
            if not left.relative_path:
                continue
            left_key = left.relative_path.casefold()
            override_rel = overrides.get(left_key)
            right_node: TreeNode | None = None
            candidate_targets: list[str] = []
            conflict_reason = ""
            manual_override = False

            if override_rel and override_rel.casefold() in right_by_rel:
                right_node = right_by_rel[override_rel.casefold()]
                target_rel = right_node.relative_path
                manual_override = True
            else:
                candidates = right_by_name.get(left.name.casefold(), [])
                if len(candidates) == 1:
                    right_node = candidates[0]
                    target_rel = right_node.relative_path
                elif len(candidates) > 1:
                    exact = next(
                        (item for item in candidates if item.relative_path.casefold() == left_key),
                        None,
                    )
                    if exact is not None:
                        right_node = exact
                        target_rel = exact.relative_path
                    else:
                        target_rel = ""
                        candidate_targets = [item.relative_path for item in candidates]
                        conflict_reason = f"目标存在 {len(candidates)} 个同名文件，请右键指定覆盖目标"
                else:
                    # 目标未命中同名文件：若允许新增，则落点到目标根目录下的同名文件
                    target_rel = left.name

            record: dict[str, object] = {
                "left": left,
                "right": right_node,
                "target_rel": target_rel,
                "candidate_targets": candidate_targets,
                "conflict_reason": conflict_reason,
                "manual_override": manual_override,
                "source_collision": False,
            }
            pending.append(record)
            if not conflict_reason and target_rel:
                target_claims.setdefault(target_rel.casefold(), []).append(record)

        # 第二遍：拦截左侧多个不同文件映射到同一目标路径的碰撞
        for claim_group in target_claims.values():
            if len(claim_group) > 1:
                for record in claim_group:
                    record["right"] = None
                    record["conflict_reason"] = "来源存在多个同名文件映射到同一目标，请缩小来源目录范围"
                    record["candidate_targets"] = []
                    record["source_collision"] = True

        # 第三遍：生成左侧 ComparePair，并记录已配对的右侧节点
        pairs: dict[str, ComparePair] = {}
        matched_right_keys: set[str] = set()
        for record in pending:
            left = record["left"]
            assert isinstance(left, TreeNode)
            right_node = record["right"] if isinstance(record["right"], TreeNode) else None
            conflict_reason = str(record["conflict_reason"] or "")
            candidate_targets = list(record["candidate_targets"])  # type: ignore[arg-type]
            target_rel = str(record["target_rel"] or "")
            extra: dict[str, object] = {
                "layout": "ui",
                "target_relative_path": target_rel,
                "display_relative_path": left.relative_path,
                "manual_override": bool(record["manual_override"]),
                "source_collision": bool(record["source_collision"]),
            }
            if candidate_targets:
                extra["candidate_targets"] = candidate_targets
            if conflict_reason:
                status = "conflict"
                extra["conflict_reason"] = conflict_reason
            elif right_node is None:
                status = "only_left"
            else:
                status = "same" if self._nodes_equal(left, right_node, hash_cache=hash_cache) else "different"
                matched_right_keys.add(right_node.relative_path.casefold())
                right_node.compare_status = status
                src_dim, dst_dim = self._read_pair_dimensions(left, right_node)
                if src_dim is not None:
                    extra["source_dimensions"] = src_dim
                if dst_dim is not None:
                    extra["target_dimensions"] = dst_dim

            left.compare_status = status
            pairs[left.relative_path.casefold()] = ComparePair(
                relative_path=left.relative_path,
                left=left,
                right=right_node,
                status=status,
                extra=extra,
            )

        # 第四遍：补齐未被任何左侧文件匹配到的目标独有文件
        for right_node in right_nodes:
            right_key = right_node.relative_path.casefold()
            if right_key in matched_right_keys:
                continue
            right_node.compare_status = "only_right"
            pair_rel = (
                right_node.relative_path
                if right_key not in pairs
                else f"__right__:{right_node.relative_path}"
            )
            pairs[pair_rel.casefold()] = ComparePair(
                relative_path=pair_rel,
                left=None,
                right=right_node,
                status="only_right",
                extra={
                    "layout": "ui",
                    "target_relative_path": right_node.relative_path,
                    "display_relative_path": right_node.relative_path,
                },
            )

        return CompareResult(left_root=left_root, right_root=right_root, node_map=pairs)

    @staticmethod
    def _nodes_equal(left: TreeNode, right: TreeNode, *, hash_cache: HashCache | None = None) -> bool:
        if left.file_size_bytes != right.file_size_bytes:
            return False
        if not left.absolute_path or not right.absolute_path:
            return left.digest == right.digest
        source_path = Path(left.absolute_path)
        target_path = Path(right.absolute_path)
        if hash_cache is not None:
            if not hash_cache.fingerprints_equal(source_path, target_path):
                return False
            return hash_cache.files_equal(source_path, target_path)
        if not fingerprints_equal(source_path, target_path):
            return False
        return files_equal(source_path, target_path)

    @staticmethod
    def _read_pair_dimensions(
        left: TreeNode,
        right: TreeNode,
    ) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        left_is_image = bool((left.extra or {}).get("is_image", True))
        right_is_image = bool((right.extra or {}).get("is_image", True))
        if not left_is_image or not right_is_image:
            return None, None
        src_dim = read_image_dimensions(Path(left.absolute_path)) if left.absolute_path else None
        dst_dim = read_image_dimensions(Path(right.absolute_path)) if right.absolute_path else None
        return src_dim, dst_dim
