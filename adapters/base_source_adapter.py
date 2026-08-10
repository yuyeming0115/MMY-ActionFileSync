from __future__ import annotations

from abc import ABC, abstractmethod

from models.tree_node import TreeNode


class BaseSourceAdapter(ABC):
    source_type: str = "base"

    @abstractmethod
    def scan(self, root_path: str) -> TreeNode:
        raise NotImplementedError
