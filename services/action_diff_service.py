from __future__ import annotations

from pathlib import Path
import re

from models.action_diff import ActionDiffItem, FileDiffItem
from models.compare_result import ComparePair, CompareResult
from models.tree_node import TreeNode
from utils.hash_utils import files_equal


class ActionDiffService:
    def build_actions(self, result: CompareResult) -> list[ActionDiffItem]:
        action_paths = self._collect_sequence_paths(result.left_root)
        action_paths.update(self._collect_sequence_paths(result.right_root))

        actions = [self._build_action(path, result) for path in action_paths if path]
        return sorted(actions, key=lambda item: self._natural_key(item.action_name))

    def selected_summary(
        self,
        actions: list[ActionDiffItem],
        selected_paths: set[str],
    ) -> tuple[int, int, int]:
        selected_actions = 0
        selected_files = 0
        selected_bytes = 0
        for action in actions:
            matched = [item for item in action.transferable_files if item.relative_path in selected_paths]
            if not matched:
                continue
            selected_actions += 1
            selected_files += len(matched)
            selected_bytes += sum(item.size_bytes for item in matched)
        return selected_actions, selected_files, selected_bytes

    @staticmethod
    def file_to_action(actions: list[ActionDiffItem]) -> dict[str, str]:
        return {
            file_item.relative_path: action.relative_path
            for action in actions
            for file_item in action.file_diffs
        }

    def _build_action(self, action_path: str, result: CompareResult) -> ActionDiffItem:
        pair = result.node_map.get(action_path)
        source_node = pair.left if pair else None
        target_node = pair.right if pair else None
        status = pair.status if pair else "unknown"
        file_diffs = self._collect_file_diffs(action_path, result)
        self._append_source_auxiliary_files(action_path, source_node, target_node, file_diffs)
        return ActionDiffItem(
            action_id=action_path.casefold(),
            action_name=Path(action_path).name,
            relative_path=action_path,
            status=status,
            source_node=source_node,
            target_node=target_node,
            file_diffs=sorted(file_diffs, key=lambda item: self._natural_key(item.relative_path)),
        )

    def _collect_file_diffs(self, action_path: str, result: CompareResult) -> list[FileDiffItem]:
        prefix = f"{action_path}/"
        items: list[FileDiffItem] = []
        for relative_path, pair in result.node_map.items():
            if not relative_path.startswith(prefix) or not self._is_image_pair(pair):
                continue
            source = pair.left
            target = pair.right
            size = source.file_size_bytes if source else target.file_size_bytes if target else 0
            items.append(
                FileDiffItem(
                    relative_path=relative_path,
                    name=Path(relative_path).name,
                    status=pair.status,
                    source_path=source.absolute_path if source else None,
                    target_path=target.absolute_path if target else None,
                    size_bytes=size,
                )
            )
        return items

    def _append_source_auxiliary_files(
        self,
        action_path: str,
        source_node: TreeNode | None,
        target_node: TreeNode | None,
        items: list[FileDiffItem],
    ) -> None:
        if not source_node or not source_node.absolute_path:
            return
        source_root = Path(source_node.absolute_path)
        if not source_root.is_dir():
            return
        known = {item.relative_path.casefold() for item in items}
        target_root = Path(target_node.absolute_path) if target_node and target_node.absolute_path else None
        for source_file in source_root.rglob("*"):
            if not source_file.is_file():
                continue
            within_action = source_file.relative_to(source_root)
            relative_path = (Path(action_path) / within_action).as_posix()
            if relative_path.casefold() in known:
                continue
            target_file = target_root / within_action if target_root else None
            status = self._compare_auxiliary_file(source_file, target_file)
            items.append(
                FileDiffItem(
                    relative_path=relative_path,
                    name=source_file.name,
                    status=status,
                    source_path=str(source_file),
                    target_path=str(target_file) if target_file else None,
                    size_bytes=source_file.stat().st_size,
                )
            )

    @staticmethod
    def _compare_auxiliary_file(source: Path, target: Path | None) -> str:
        if not target or not target.exists() or not target.is_file():
            return "only_left"
        return "same" if files_equal(source, target) else "different"

    @staticmethod
    def _is_image_pair(pair: ComparePair) -> bool:
        return bool(
            (pair.left and pair.left.node_type == "image")
            or (pair.right and pair.right.node_type == "image")
        )

    @staticmethod
    def _collect_sequence_paths(root: TreeNode) -> set[str]:
        result: set[str] = set()
        stack = [root]
        while stack:
            node = stack.pop()
            if node.node_type == "sequence" and node.relative_path:
                result.add(node.relative_path)
            stack.extend(node.children)
        return result

    @staticmethod
    def _natural_key(value: str) -> list[int | str]:
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]
