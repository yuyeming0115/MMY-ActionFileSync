from __future__ import annotations

from dataclasses import dataclass, field

from models.tree_node import TreeNode


TRANSFERABLE_STATUSES = {"only_left", "different"}


@dataclass(frozen=True)
class FileDiffItem:
    relative_path: str
    name: str
    status: str
    source_path: str | None
    target_path: str | None
    size_bytes: int = 0

    @property
    def is_transferable(self) -> bool:
        return bool(self.source_path) and self.status in TRANSFERABLE_STATUSES


@dataclass
class ActionDiffItem:
    action_id: str
    action_name: str
    relative_path: str
    status: str
    source_node: TreeNode | None
    target_node: TreeNode | None
    file_diffs: list[FileDiffItem] = field(default_factory=list)

    @property
    def transferable_files(self) -> list[FileDiffItem]:
        return [item for item in self.file_diffs if item.is_transferable]

    @property
    def transfer_file_count(self) -> int:
        return len(self.transferable_files)

    @property
    def transfer_size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.transferable_files)

    @property
    def change_counts(self) -> dict[str, int]:
        counts = {"only_left": 0, "different": 0, "only_right": 0}
        for item in self.file_diffs:
            if item.status in counts:
                counts[item.status] += 1
        return counts

    @property
    def only_left_count(self) -> int:
        return sum(1 for item in self.file_diffs if item.status == "only_left")

    @property
    def adds_extra_to_existing_target(self) -> bool:
        """目标侧已存在该动作，但本次仍包含会比 SVN 多出的来源独有文件。"""
        return self.status == "different" and self.only_left_count > 0

    @property
    def change_summary(self) -> str:
        counts = self.change_counts
        parts: list[str] = []
        if counts["only_left"]:
            parts.append(f"+{counts['only_left']}")
        if counts["different"]:
            parts.append(f"~{counts['different']}")
        if counts["only_right"]:
            parts.append(f"-{counts['only_right']}")
        return " ".join(parts) if parts else "0"
