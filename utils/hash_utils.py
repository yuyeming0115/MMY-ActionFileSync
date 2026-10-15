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


def fingerprint_file(path: Path, chunk_size: int = 4096) -> str:
    """采样指纹：只读文件头尾各 ``chunk_size`` 字节。

    用于「两侧字节数相同」时的快速排除：绝大多数未改动文件的头尾
    采样即相同，无需读完整文件。数 GB 图集目录下，这能把内容比对
    从「读满全量」降到「读 8 KB/文件」。
    """
    digest = hashlib.blake2b(digest_size=16)
    size = path.stat().st_size
    with path.open("rb") as stream:
        head = stream.read(chunk_size)
        digest.update(head)
        if size > chunk_size * 2:
            stream.seek(-chunk_size, 2)
            digest.update(stream.read(chunk_size))
    return digest.hexdigest()


def fingerprints_equal(source: Path, target: Path) -> bool:
    """采样级相等判定：字节数 + 头尾采样指纹。

    - 字节数不同 → 直接 False（无需读盘）
    - 头尾采样不同 → 直接 False（读 8 KB 即可确认差异）
    - 头尾采样相同 → 仍**可能**不同（中部改动会漏判），
      调用方如需绝对准确应改用 :func:`files_equal`
    """
    try:
        source_stat = source.stat()
        target_stat = target.stat()
    except OSError:
        return False
    if source_stat.st_size != target_stat.st_size:
        return False
    return fingerprint_file(source) == fingerprint_file(target)


class HashCache:
    """基于 (path, size, mtime) 的文件内容哈希缓存。

    当文件大小和修改时间都未变化时，直接复用上次的哈希结果，
    避免重复读盘。适用于多次刷新、辅助文件比较等场景。
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._fingerprint_cache: dict[str, str] = {}

    @staticmethod
    def _key(path: Path, size: int, mtime: float) -> str:
        return f"{path}|{size}|{mtime:.6f}"

    def fingerprint_file(self, path: Path, chunk_size: int = 4096) -> str:
        """带缓存的采样指纹（见 :func:`fingerprint_file`）。"""
        try:
            stat = path.stat()
        except OSError:
            return fingerprint_file(path, chunk_size)
        key = self._key(path.resolve(), stat.st_size, stat.st_mtime)
        cached = self._fingerprint_cache.get(key)
        if cached is not None:
            return cached
        result = fingerprint_file(path, chunk_size)
        self._fingerprint_cache[key] = result
        return result

    def fingerprints_equal(self, source: Path, target: Path) -> bool:
        """采样级相等判定（带缓存）。"""
        try:
            source_stat = source.stat()
            target_stat = target.stat()
        except OSError:
            return False
        if source_stat.st_size != target_stat.st_size:
            return False
        return self.fingerprint_file(source) == self.fingerprint_file(target)

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
        self._fingerprint_cache.clear()
