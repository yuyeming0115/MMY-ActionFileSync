from __future__ import annotations

from adapters.local_folder_adapter import LocalFolderAdapter
from models.compare_result import CompareResult
from services.compare_service import CompareService


class RefreshService:
    def __init__(self) -> None:
        self.left_adapter = LocalFolderAdapter()
        self.right_adapter = LocalFolderAdapter()
        self.compare_service = CompareService()

    def refresh(self, left_root_path: str, right_root_path: str) -> CompareResult:
        left_root = self.left_adapter.scan(left_root_path)
        right_root = self.right_adapter.scan(right_root_path)
        return self.compare_service.compare(left_root, right_root)
