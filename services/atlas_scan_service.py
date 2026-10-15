"""图集目录扫描：把「一张图集 = 一个条目」映射成可对比的虚拟动作树。

背景：打包产物（TexturePacker atlas）是**平铺**在输出目录里的
``{角色ID}_{部件}_{方向}_{动作}.png + .plist`` 文件对，目录下没有任何子目录。
而现有 :class:`~services.scan_service.ScanService` 的模型是
「目录 = 动作、目录内图片 = 序列帧」，直接扫会得到「1 个动作 + 6746 帧」。

本模块不改传输内核，而是产出一棵**虚拟动作树**：
每个 ``png + plist`` 文件对被映射成一个 ``atlas`` 类型的 sequence 节点，
节点下的 frame_files 恰好是这一对文件。这样 CompareService /
ActionDiffService / 差异清单 / 传输流程全部零改动复用。

用户诉求是「不做切帧对比，单图对比 + 差异化 + 传递」，
所以 ``atlas`` 节点的预览就是整张图集，不还原动画。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from natsort import natsorted

from models.tree_node import TreeNode
from services.scan_service import ScanCancelledError
from utils.atlas_naming import AtlasEntry, parse_atlas_name, strip_extension
from utils.file_utils import build_node_id
from utils.hash_utils import HashCache, hash_file


ATLAS_PNG = ".png"
ATLAS_PLIST = ".plist"
ATLAS_EXTENSIONS = {ATLAS_PNG, ATLAS_PLIST}

# 一次扫描处理的进度回调间隔（每多少个条目回调一次）
_PROGRESS_INTERVAL = 50


def detect_atlas_directory(root_path: str) -> bool:
    """判断目录是否为「平铺图集目录」。

    判定条件（全部满足才认定为图集目录，避免误伤普通序列帧目录）：
    1. 目录下没有子目录；
    2. 至少存在 2 个 ``.plist`` 文件（plist 是图集独有的伴随文件）；
    3. 每个 ``.plist`` 都有同名 ``.png``。
    """
    root = Path(root_path)
    if not root.is_dir():
        return False
    try:
        entries = [entry for entry in os.scandir(root) if entry.is_file()]
    except OSError:
        return False
    # 存在子目录就不是平铺结构
    if any(Path(entry.path).is_dir() for entry in entries):
        return False
    names = {entry.name for entry in entries}
    plists = {name for name in names if name.lower().endswith(ATLAS_PLIST)}
    if len(plists) < 2:
        return False
    return all(f"{strip_extension(name)}{ATLAS_PNG}" in names for name in plists)


class AtlasScanService:
    """扫描平铺图集目录，产出「一图集一动作」的虚拟树。"""

    node_type = "atlas"

    def __init__(self, source_type: str, hash_cache: HashCache | None = None) -> None:
        self.source_type = source_type
        self._hash_cache = hash_cache
        self._cancel_token = None
        self._on_progress = None

    def scan(
        self,
        root_path: str,
        cancel_token: object | None = None,
        progress_callback: object | None = None,
    ) -> TreeNode:
        root = Path(root_path)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"目录不存在: {root_path}")
        self._cancel_token = cancel_token
        self._on_progress = progress_callback
        try:
            return self._build_root(root)
        finally:
            self._cancel_token = None
            self._on_progress = None

    def _check_cancelled(self) -> None:
        if self._cancel_token and self._cancel_token.is_cancelled():
            raise ScanCancelledError("扫描已取消")

    def _build_root(self, root: Path) -> TreeNode:
        try:
            names = [entry.name for entry in os.scandir(root) if entry.is_file()]
        except OSError as exc:
            raise FileNotFoundError(f"目录无法读取: {root}") from exc

        # 以 png 为锚点建条目，plist 通过同名配对挂载
        stems: dict[str, dict[str, str]] = {}
        for name in natsorted(names):
            lower = name.lower()
            if lower.endswith(ATLAS_PLIST):
                stem = strip_extension(name)
                stems.setdefault(stem.casefold(), {})[ATLAS_PLIST] = name
            elif lower.endswith(ATLAS_PNG):
                stem = strip_extension(name)
                stems.setdefault(stem.casefold(), {})[ATLAS_PNG] = name

        children: list[TreeNode] = []
        own_size = 0
        for index, (key, files) in enumerate(stems.items(), start=1):
            if index % _PROGRESS_INTERVAL == 0:
                self._check_cancelled()
                if callable(self._on_progress):
                    self._on_progress(index, len(stems))
            node = self._build_atlas_node(root, key, files)
            children.append(node)
            own_size += node.file_size_bytes

        children.sort(key=lambda node: node.name.casefold())
        digest = self._build_digest(children)
        return TreeNode(
            id=build_node_id(self.source_type, ""),
            name=root.name,
            relative_path="",
            absolute_path=str(root),
            node_type="atlas_root",
            source_type=self.source_type,
            children=children,
            frame_files=[],
            file_count=len(children),
            file_size_bytes=own_size,
            digest=digest,
            extra={"layout": "atlas", "entry_count": len(children)},
        )

    def _build_atlas_node(self, root: Path, key: str, files: dict[str, str]) -> TreeNode:
        png_name = files.get(ATLAS_PNG)
        plist_name = files.get(ATLAS_PLIST)
        # 锚点文件名决定条目的显示名与相对路径（成对时用 png，否则用 plist）
        anchor = png_name or plist_name or key
        entry: AtlasEntry = parse_atlas_name(anchor)

        # frame_files 收集这一对文件，顺序固定 png → plist，
        # 让 CompareService 的「帧集合比对」对成对关系稳定
        frame_files: list[str] = []
        size = 0
        for name in (png_name, plist_name):
            if not name:
                continue
            frame_files.append(name)
            file_path = root / name
            try:
                size += file_path.stat().st_size
            except OSError:
                continue

        # 摘要刻意「不读文件内容」：只用「文件名 + 字节数」。
        #
        # 原因：图集目录动辄数千条、数 GB 级别，全量内容哈希一次要十几秒；
        # 而打包产物一旦重打，png 与 plist 的字节数几乎必然变化，
        # 用 (name, size) 足以判变，且能让比较瞬间完成。
        #
        # 刻意 **不** 把 mtime 纳入摘要：SVN 检出/复制会重写时间戳，
        # 同样的字节内容也会被判成「变更」，制造大量假差异。
        #
        # 真正的内容级校验仍由差异服务在两侧都存在同名文件时按需触发
        # （HashCache.files_equal 先比 size 再比哈希），
        # 因此「同尺寸但内容不同」这种情况依然会被抓出来。
        digest = hashlib.blake2b(digest_size=16)
        digest.update(entry.stem.encode("utf-8"))
        for name in frame_files:
            digest.update(name.encode("utf-8"))
            digest.update(str(size).encode("ascii"))
        digest_hex = digest.hexdigest()

        missing_companion = "有图无 plist" if png_name and not plist_name else "有 plist 无图"
        return TreeNode(
            id=build_node_id(self.source_type, anchor),
            name=anchor,
            relative_path=anchor,
            absolute_path=str(root / anchor),
            node_type=self.node_type,
            source_type=self.source_type,
            children=[],
            frame_files=frame_files,
            gif_path=None,
            file_count=len(frame_files),
            file_size_bytes=size,
            digest=digest_hex,
            extra={
                "layout": "atlas",
                "stem": entry.stem,
                "role_id": entry.role_id,
                "part": entry.part,
                "direction": entry.direction,
                "action": entry.action,
                "group_label": entry.group_label,
                "search_text": entry.search_text,
                "has_png": bool(png_name),
                "has_plist": bool(plist_name),
                "missing_companion": missing_companion if missing_companion and (png_name or plist_name) and len(frame_files) < 2 else "",
                # 预览用：图集整图，不做切帧
                "preview_png": png_name or "",
                "preview_plist": plist_name or "",
            },
        )

    def _hash(self, name: str, path: Path) -> str:
        if self._hash_cache is not None:
            return self._hash_cache.hash_file(path)
        return hash_file(path)

    def _build_digest(self, children: list[TreeNode]) -> str:
        digest = hashlib.blake2b(digest_size=16)
        for child in children:
            digest.update(child.name.encode("utf-8"))
            digest.update(child.digest.encode("utf-8"))
        return digest.hexdigest()