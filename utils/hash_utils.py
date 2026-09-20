from __future__ import annotations

import hashlib
from pathlib import Path


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.blake2b(digest_size=16)
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def files_equal(source: Path, target: Path) -> bool:
    if not source.is_file() or not target.is_file():
        return False
    if source.stat().st_size != target.stat().st_size:
        return False
    return hash_file(source) == hash_file(target)


class HashCache:
    """基于 (path, size, mtime) 的文件内容哈希缓存。

    当文件大小和修改时间都未变化时，直接复用上次的哈希结果，
    避免重复读盘。适用于多次刷新、辅助文件比较等场景。
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    @staticmethod
    def _key(path: Path, size: int, mtime: float) -> str:
        return f"{path}|{size}|{mtime:.6f}"

    def hash_file(self, path: Path, chunk_size: int = 1024 * 1024) -> str:
        try:
            stat = path.stat()
        except OSError:
            return hash_file(path, chunk_size)
        key = self._key(path.resolve(), stat.st_size, stat.st_mtime)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = hash_file(path, chunk_size)
        self._cache[key] = result
        return result

    def files_equal(self, source: Path, target: Path) -> bool:
        """带缓存的文件相等性比较，优先比 size，再用缓存哈希比对。"""
        if not source.is_file() or not target.is_file():
            return False
        source_stat = source.stat()
        target_stat = target.stat()
        if source_stat.st_size != target_stat.st_size:
            return False
        return self.hash_file(source) == self.hash_file(target)

    def clear(self) -> None:
        self._cache.clear()
