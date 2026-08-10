from __future__ import annotations

from models.compare_result import ComparePair, CompareResult
from models.tree_node import TreeNode


class CompareService:
    def compare(self, left_root: TreeNode, right_root: TreeNode) -> CompareResult:
        left_map = self._flatten(left_root)
        right_map = self._flatten(right_root)
        pairs: dict[str, ComparePair] = {}
        for relative_path in sorted(set(left_map) | set(right_map)):
            left = left_map.get(relative_path)
            right = right_map.get(relative_path)
            status = self._resolve_status(left, right)
            if left:
                left.compare_status = status
            if right:
                right.compare_status = status
            pairs[relative_path] = ComparePair(relative_path, left, right, status)
        return CompareResult(left_root=left_root, right_root=right_root, node_map=pairs)

    def _flatten(self, root: TreeNode) -> dict[str, TreeNode]:
        result: dict[str, TreeNode] = {}
        stack = [root]
        while stack:
            node = stack.pop()
            result[node.relative_path] = node
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
            if left.file_count != right.file_count:
                return "different"
            if set(left.frame_files) != set(right.frame_files):
                return "different"
        if left.digest != right.digest:
            return "different"
        return "same"
