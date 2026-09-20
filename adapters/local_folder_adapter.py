from __future__ import annotations

from adapters.base_source_adapter import BaseSourceAdapter
from models.tree_node import TreeNode
from services.scan_service import ScanService
from utils.hash_utils import HashCache


class LocalFolderAdapter(BaseSourceAdapter):
    source_type = "local"

    def __init__(self, hash_cache: HashCache | None = None) -> None:
        self._scanner = ScanService(source_type=self.source_type, hash_cache=hash_cache)

    def scan(self, root_path: str, cancel_token: object | None = None) -> TreeNode:
        return self._scanner.scan(root_path, cancel_token=cancel_token)
