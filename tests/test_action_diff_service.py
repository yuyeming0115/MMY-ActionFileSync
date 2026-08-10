from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from models.tree_node import TreeNode
from services.action_diff_service import ActionDiffService
from services.compare_service import CompareService


def image_node(root: Path, relative_path: str, digest: str, source: str) -> TreeNode:
    absolute = root / Path(relative_path)
    return TreeNode(
        id=f"{source}:{relative_path}",
        name=absolute.name,
        relative_path=relative_path,
        absolute_path=str(absolute),
        node_type="image",
        source_type=source,
        file_count=1,
        file_size_bytes=absolute.stat().st_size,
        digest=digest,
    )


def sequence_node(root: Path, relative_path: str, children: list[TreeNode], source: str) -> TreeNode:
    return TreeNode(
        id=f"{source}:{relative_path}",
        name=Path(relative_path).name,
        relative_path=relative_path,
        absolute_path=str(root / Path(relative_path)),
        node_type="sequence",
        source_type=source,
        children=children,
        frame_files=[child.name for child in children],
        file_count=len(children),
        file_size_bytes=sum(child.file_size_bytes for child in children),
        digest="|".join(child.digest for child in children),
    )


def root_node(root: Path, children: list[TreeNode], source: str) -> TreeNode:
    return TreeNode(
        id=f"{source}:/",
        name=root.name,
        relative_path="",
        absolute_path=str(root),
        node_type="folder",
        source_type=source,
        children=children,
        digest="root",
    )


class ActionDiffServiceTests(unittest.TestCase):
    def test_builds_action_rows_and_exact_transferable_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source_root = base / "source"
            target_root = base / "target"
            source_action = source_root / "player" / "idle"
            target_action = target_root / "player" / "idle"
            source_action.mkdir(parents=True)
            target_action.mkdir(parents=True)

            for name, content in {
                "idle_001.png": b"same",
                "idle_002.png": b"new",
                "idle_003.png": b"source-version",
                "preview.gif": b"gif",
            }.items():
                (source_action / name).write_bytes(content)
            for name, content in {
                "idle_001.png": b"same",
                "idle_003.png": b"target-version",
                "idle_004.png": b"target-only",
            }.items():
                (target_action / name).write_bytes(content)

            source_children = [
                image_node(source_root, "player/idle/idle_001.png", "same", "left"),
                image_node(source_root, "player/idle/idle_002.png", "new", "left"),
                image_node(source_root, "player/idle/idle_003.png", "source", "left"),
            ]
            target_children = [
                image_node(target_root, "player/idle/idle_001.png", "same", "right"),
                image_node(target_root, "player/idle/idle_003.png", "target", "right"),
                image_node(target_root, "player/idle/idle_004.png", "target-only", "right"),
            ]
            result = CompareService().compare(
                root_node(source_root, [sequence_node(source_root, "player/idle", source_children, "left")], "left"),
                root_node(target_root, [sequence_node(target_root, "player/idle", target_children, "right")], "right"),
            )

            actions = ActionDiffService().build_actions(result)

            self.assertEqual([action.action_name for action in actions], ["idle"])
            action = actions[0]
            self.assertEqual(action.status, "different")
            self.assertEqual(
                {item.name for item in action.transferable_files},
                {"idle_002.png", "idle_003.png", "preview.gif"},
            )
            self.assertEqual(action.change_summary, "+2 ~1 -1")

            selected = {item.relative_path for item in action.transferable_files}
            action_count, file_count, size_bytes = ActionDiffService().selected_summary(actions, selected)
            self.assertEqual((action_count, file_count), (1, 3))
            self.assertGreater(size_bytes, 0)

    def test_action_names_use_natural_sort_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "left"
            right = root / "right"
            for action_name in ["action10", "action2"]:
                (left / action_name).mkdir(parents=True)
                (right / action_name).mkdir(parents=True)
            left_nodes = [sequence_node(left, name, [], "left") for name in ["action10", "action2"]]
            right_nodes = [sequence_node(right, name, [], "right") for name in ["action10", "action2"]]
            result = CompareService().compare(root_node(left, left_nodes, "left"), root_node(right, right_nodes, "right"))

            actions = ActionDiffService().build_actions(result)

            self.assertEqual([action.action_name for action in actions], ["action2", "action10"])


if __name__ == "__main__":
    unittest.main()
