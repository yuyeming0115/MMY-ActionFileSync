"""图集目录适配器：对外暴露与 :class:`LocalFolderAdapter` 一致的 scan 接口。"""

from __future__ import annotations

from adapters.base_source_adapter import BaseSourceAdapter
from models.tree_node import TreeNode
from services.atlas_scan_service import AtlasScanService, detect_atlas_directory
from utils.hash_utils import HashCache


class AtlasFolderAdapter(BaseSourceAdapter):
    source_type = "atlas"

    def __init__(self, hash_cache: HashCache | None = None) -> None:
        self._scanner = AtlasScanService(source_type=self.source_type, hash_cache=hash_cache)

    def scan(self, root_path: str, cancel_token: object | None = None) -> TreeNode:
        return self._scanner.scan(root_path, cancel_token=cancel_token)


class LayoutAwareFolderAdapter(BaseSourceAdapter):
    """按目录形态自动选择扫描器。

    - 平铺图集目录（只有 png/plist、无子目录）→ :class:`AtlasFolderAdapter`
    - 其余目录 → 普通序列帧扫描
    """

    def __init__(self, source_type: str, hash_cache: HashCache | None = None) -> None:
        self.source_type = source_type
        self._hash_cache = hash_cache
        self._atlas = AtlasFolderAdapter(hash_cache=hash_cache)
        self._normal = None

    def scan(
        self,
        root_path: str,
        cancel_token: object | None = None,
        progress_callback: object | None = None,
    ) -> TreeNode:
        if detect_atlas_directory(root_path):
            return self._atlas.scan(root_path, cancel_token=cancel_token)
        if self._normal is None:
            from services.scan_service import ScanService

            self._normal = ScanService(source_type=self.source_type, hash_cache=self._hash_cache)
        return self._normal.scan(root_path, cancel_token=cancel_token)