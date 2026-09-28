from __future__ import annotations

import os
from collections import deque
from pathlib import Path

# 递归兜底时最多访问的目录数，防止目标根目录过大时拖慢 UI 线程
_MAX_VISITED_DIRS = 500


def normalize_path(path: str) -> str:
    """把路径统一成正斜杠风格，保证设置存储与界面显示一致。"""
    if not path:
        return ""
    return str(Path(path)).replace("\\", "/")


def find_same_name_folder(name: str, *roots: str | None, max_depth: int = 3) -> str | None:
    """在若干候选根目录下查找名为 name 的子目录，浅层优先。

    roots 按优先级排列；每个根先直查 root/name，未命中再广度优先向下
    最多 max_depth 层（max_depth=3 即查 root/name、root/*/name、root/*/*/name）。
    隐藏目录（.svn 等）不作为结果也不深入。返回磁盘真实路径，找不到返回 None。
    """
    key = name.casefold()
    if not key:
        return None
    visited = 0
    for root in roots:
        if not root:
            continue
        base = Path(root)
        if not base.is_dir():
            continue
        queue: deque[tuple[Path, int]] = deque([(base, 0)])
        while queue:
            current, depth = queue.popleft()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            visited += 1
            if visited > _MAX_VISITED_DIRS:
                return None
            subdirs: list[tuple[Path, int]] = []
            for entry in entries:
                if not entry.is_dir():
                    continue
                if entry.name.casefold() == key:
                    return entry.path
                if not entry.name.startswith(".") and depth + 1 < max_depth:
                    subdirs.append((Path(entry.path), depth + 1))
            queue.extend(subdirs)
    return None
