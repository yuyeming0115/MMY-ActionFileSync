from __future__ import annotations

from adapters.atlas_folder_adapter import LayoutAwareFolderAdapter
from models.compare_result import CompareResult
from services.compare_service import CompareService
from utils.hash_utils import HashCache


class RefreshService:
    def __init__(self, hash_cache: HashCache | None = None) -> None:
        self._hash_cache = hash_cache or HashCache()
        # 两侧都按目录形态自动选择扫描器（平铺图集 vs 序列帧目录）
        self.left_adapter = LayoutAwareFolderAdapter(source_type="left", hash_cache=self._hash_cache)
        self.right_adapter = LayoutAwareFolderAdapter(source_type="right", hash_cache=self._hash_cache)
        self.compare_service = CompareService()

    def refresh(self, left_root_path: str, right_root_path: str, cancel_token: object | None = None) -> CompareResult:
        left_root = self.left_adapter.scan(left_root_path, cancel_token=cancel_token)
        right_root = self.right_adapter.scan(right_root_path, cancel_token=cancel_token)
        return self.compare_service.compare(left_root, right_root)
