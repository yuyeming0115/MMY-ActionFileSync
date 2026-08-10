from __future__ import annotations

from adapters.base_source_adapter import BaseSourceAdapter
from models.tree_node import TreeNode
from services.scan_service import ScanService


class LocalFolderAdapter(BaseSourceAdapter):
    source_type = "local"

    def __init__(self) -> None:
        self._scanner = ScanService(source_type=self.source_type)

    def scan(self, root_path: str) -> TreeNode:
        return self._scanner.scan(root_path)
