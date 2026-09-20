from __future__ import annotations

from models.compare_result import ComparePair, CompareResult
from models.tree_node import TreeNode


class CompareService:
    def compare(self, left_root: TreeNode, right_root: TreeNode) -> CompareResult:
        left_map = self._flatten(left_root)
        right_map = self._flatten(right_root)
        pairs: dict[str, ComparePair] = {}
        # 使用大小写不敏感的 key 匹配（Windows 文件系统特性），
        # 但保留原始大小写路径用于显示和实际文件操作。
        for case_key in sorted(set(left_map) | set(right_map)):
            left = left_map.get(case_key)
            right = right_map.get(case_key)
            status = self._resolve_status(left, right)
            # 展示路径优先取左侧（来源）原始大小写
            display_path = left.relative_path if left else right.relative_path if right else case_key
            if left:
                left.compare_status = status
            if right:
                right.compare_status = status
            pairs[display_path.casefold()] = ComparePair(display_path, left, right, status)
        return CompareResult(left_root=left_root, right_root=right_root, node_map=pairs)

    def _flatten(self, root: TreeNode) -> dict[str, TreeNode]:
        """以 casefold 后的相对路径为 key，保证两侧大小写不同也能匹配。"""
        result: dict[str, TreeNode] = {}
        stack = [root]
        while stack:
            node = stack.pop()
            result[node.relative_path.casefold()] = node
            stack.extend(reversed(node.children))
        return result

    def _resolve_status(self, left: TreeNode | None, right: TreeNode | None) -> str:
        if left and not right:
            return "only_left"
        if right and not left:
            return "only_right"
        if not left or not right:
            return "unknown"
        if left.node_type != right.node_type:
            return "different"
        if left.node_type == "sequence":
            # 帧文件集合使用 casefold 比较，避免大小写差异误判
            left_frames = {name.casefold() for name in left.frame_files}
            right_frames = {name.casefold() for name in right.frame_files}
            if len(left.frame_files) != len(right.frame_files) or left_frames != right_frames:
                return "different"
        if left.digest != right.digest:
            return "different"
        return "same"
