from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models.tree_node import TreeNode


@dataclass
class ComparePair:
    relative_path: str
    left: TreeNode | None
    right: TreeNode | None
    status: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompareResult:
    left_root: TreeNode
    right_root: TreeNode
    node_map: dict[str, ComparePair] = field(default_factory=dict)
