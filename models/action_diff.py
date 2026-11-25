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
    target_relative_path: str = ""
    blocked_reason: str = ""
    source_dimensions: tuple[int, int] | None = None
    target_dimensions: tuple[int, int] | None = None

    @property
    def resolved_target_relative_path(self) -> str:
        return self.target_relative_path or self.relative_path

    @property
    def has_dimension_mismatch(self) -> bool:
        return bool(
            self.source_dimensions
            and self.target_dimensions
            and self.source_dimensions != self.target_dimensions
        )

    @property
    def is_transferable(self) -> bool:
        return bool(self.source_path) and self.status in TRANSFERABLE_STATUSES and not self.blocked_reason


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
    def has_dimension_mismatch(self) -> bool:
        return any(item.has_dimension_mismatch for item in self.file_diffs)

    @property
    def dimension_mismatch_pair(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        for item in self.file_diffs:
            if item.has_dimension_mismatch and item.source_dimensions and item.target_dimensions:
                return (item.source_dimensions, item.target_dimensions)
        return None

    @property
    def blocked_reasons(self) -> list[str]:
        seen: list[str] = []
        for item in self.file_diffs:
            if item.blocked_reason and item.blocked_reason not in seen:
                seen.append(item.blocked_reason)
        return seen

    @property
    def candidate_target_paths(self) -> list[str]:
        if self.source_node and self.source_node.extra:
            raw = self.source_node.extra.get("candidate_targets")
            if isinstance(raw, list):
                return [str(p) for p in raw if p]
        return []

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
