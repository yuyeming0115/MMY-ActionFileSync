from __future__ import annotations

from pathlib import Path
import re

from models.action_diff import ActionDiffItem, FileDiffItem
from models.compare_result import ComparePair, CompareResult
from models.tree_node import TreeNode
from utils.hash_utils import HashCache, files_equal, fingerprints_equal


class ActionDiffService:
    def __init__(
        self,
        hash_cache: HashCache | None = None,
        deep_verify: bool = False,
    ) -> None:
        self._hash_cache = hash_cache
        # deep_verify=False（默认）：字节数相同即视为一致，不读文件内容。
        # 打开后对「字节数相同」的图集做完整内容哈希，精度更高但慢。
        self._deep_verify = deep_verify

    def build_actions(self, result: CompareResult) -> list[ActionDiffItem]:
        action_paths = self._collect_sequence_paths(result.left_root)
        action_paths.update(self._collect_sequence_paths(result.right_root))

        actions = [self._build_action(path, result) for path in action_paths if path]
        return sorted(actions, key=lambda item: self._natural_key(item.action_name))

    def selected_summary(
        self,
        actions: list[ActionDiffItem],
        selected_paths: set[str],
    ) -> tuple[int, int, int]:
        selected_actions = 0
        selected_files = 0
        selected_bytes = 0
        for action in actions:
            matched = [item for item in action.transferable_files if item.relative_path in selected_paths]
            if not matched:
                continue
            selected_actions += 1
            selected_files += len(matched)
            selected_bytes += sum(item.size_bytes for item in matched)
        return selected_actions, selected_files, selected_bytes

    @staticmethod
    def file_to_action(actions: list[ActionDiffItem]) -> dict[str, str]:
        return {
            file_item.relative_path: action.relative_path
            for action in actions
            for file_item in action.file_diffs
        }

    def _build_action(self, action_path: str, result: CompareResult) -> ActionDiffItem:
        pair = result.node_map.get(action_path.casefold())
        # 以 pair 的展示路径（优先来源原始大小写）作为动作的正式路径
        display_path = pair.relative_path if pair else action_path
        source_node = pair.left if pair else None
        target_node = pair.right if pair else None
        status = pair.status if pair else "unknown"
        if self._is_atlas_node(source_node) or self._is_atlas_node(target_node):
            file_diffs, detected = self._collect_atlas_file_diffs(
                display_path, source_node, target_node, status
            )
            # 内容探针可能纠正了条目级状态（例如摘要一致但字节内容不同）
            if detected:
                status = "different"
                if pair is not None:
                    pair.status = "different"
                if source_node is not None:
                    source_node.compare_status = "different"
                if target_node is not None:
                    target_node.compare_status = "different"
        else:
            file_diffs = self._collect_file_diffs(display_path, result)
            self._append_source_auxiliary_files(display_path, source_node, target_node, file_diffs)
        return ActionDiffItem(
            action_id=display_path.casefold(),
            action_name=Path(display_path).name,
            relative_path=display_path,
            status=status,
            source_node=source_node,
            target_node=target_node,
            file_diffs=sorted(file_diffs, key=lambda item: self._natural_key(item.relative_path)),
        )

    def _collect_atlas_file_diffs(
        self,
        action_path: str,
        source_node: TreeNode | None,
        target_node: TreeNode | None,
        status: str,
    ) -> tuple[list[FileDiffItem], bool]:
        """图集条目文件差异。

        返回 ``(文件差异列表, 内容探针是否发现差异)``。

        性能取舍（本项目实测：目标目录 2.8 GB / 6913 条图集，E 盘机械盘）：
        摘要只用「文件名 + 字节数」，**默认不做内容哈希**。
        若对「已一致」条目逐个读全量内容，一次要 30~60 秒，
        而打包产物重新出图时字节数几乎必然变化 —— 字节数判定
        在实践中足够可靠。

        需要极限精度时，可由调用方开启 ``deep_verify``：
        逐对做「字节数 → 采样指纹 → 完整哈希」三级校验，
        代价是读取全量内容。
        """
        if not source_node:
            # 目标独有（来源缺失）：没有可传输文件，也无从探针
            return [], False
        # atlas 节点的 absolute_path 指向「条目锚点文件本身」而非所在目录，
        # 文件都在它的父目录里。
        anchor = Path(source_node.absolute_path or "")
        source_dir = anchor.parent
        target_anchor = Path(target_node.absolute_path) if target_node and target_node.absolute_path else None
        target_dir = target_anchor.parent if target_anchor else None
        items: list[FileDiffItem] = []
        # atlas 条目的摘要基于「文件名 + 字节数」，不读内容。这里做
        # 「三级探针」，把内容校验的读取量压到最小：
        #   1) 字节数不同 → 立即判不同（0 读盘）
        #   2) 字节数相同 → 比「头尾各 4KB 采样指纹」（读 8KB）
        #   3) 采样也相同 → 才做完整内容哈希（读满文件）
        # 第 3 步是必要的兜底：中部字节改动会骗过采样指纹。
        # 但它只在「真的完全一致」的文件上触发，而这类文件通常
        # 已被 HashCache 按 (path,size,mtime) 缓存，二次刷新零开销。
        any_changed = False
        for name in source_node.frame_files:
            source_file = source_dir / name
            target_file = target_dir / name if target_dir else None
            if not (target_file and target_file.is_file() and source_file.is_file()):
                continue
            if status != "same":
                # 条目级已判变更，无需探针
                continue
            if not self._deep_verify:
                # 默认快路径：字节数相同即视为一致，不读内容
                continue
            if not self._probe_same(source_file, target_file):
                any_changed = True
                break
        # 整对文件状态：条目变更 / 内容探针发现差异 → 整对重传
        propagate = status == "different" or any_changed
        for name in source_node.frame_files:
            source_file = source_dir / name
            target_file = target_dir / name if target_dir else None
            if propagate:
                file_status = "different"
            elif target_file and target_file.exists():
                file_status = "same"
            else:
                file_status = "only_left"
            try:
                size = source_file.stat().st_size
            except OSError:
                size = 0
            items.append(
                FileDiffItem(
                    relative_path=name,
                    name=name,
                    status=file_status,
                    source_path=str(source_file),
                    target_path=str(target_file) if target_file else None,
                    size_bytes=size,
                )
            )
        return items, any_changed

    def _probe_same(self, source_file: Path, target_file: Path) -> bool:
        """三级探针判断两个文件内容是否一致。

        1. 字节数不同 → 不一致（不读盘）
        2. 头尾各 4KB 采样指纹不同 → 不一致（只读 8KB）
        3. 采样相同 → 完整内容哈希（读满文件，走缓存）

        这样「大多数文件其实没变」的场景下，单文件读取量从
        几百 KB 降到 8 KB；只有完全一致的文件才会读满，
        而它们会被 HashCache 缓存，二次刷新不再读盘。
        """
        try:
            if source_file.stat().st_size != target_file.stat().st_size:
                return False
        except OSError:
            return False
        if self._hash_cache is not None:
            if not self._hash_cache.fingerprints_equal(source_file, target_file):
                return False
            return self._hash_cache.files_equal(source_file, target_file)
        if not fingerprints_equal(source_file, target_file):
            return False
        return files_equal(source_file, target_file)

    @staticmethod
    def _is_atlas_node(node: TreeNode | None) -> bool:
        return bool(node and node.node_type == "atlas")

    def _collect_file_diffs(self, action_path: str, result: CompareResult) -> list[FileDiffItem]:
        # node_map 的 key 是 casefold 的，用 casefold prefix 匹配；
        # 但 FileDiffItem 的 relative_path 使用 pair.relative_path（原始大小写）。
        prefix = f"{action_path.casefold()}/"
        items: list[FileDiffItem] = []
        for _case_key, pair in result.node_map.items():
            if not pair.relative_path.casefold().startswith(prefix) or not self._is_image_pair(pair):
                continue
            source = pair.left
            target = pair.right
            size = source.file_size_bytes if source else target.file_size_bytes if target else 0
            items.append(
                FileDiffItem(
                    relative_path=pair.relative_path,
                    name=Path(pair.relative_path).name,
                    status=pair.status,
                    source_path=source.absolute_path if source else None,
                    target_path=target.absolute_path if target else None,
                    size_bytes=size,
                )
            )
        return items

    def _append_source_auxiliary_files(
        self,
        action_path: str,
        source_node: TreeNode | None,
        target_node: TreeNode | None,
        items: list[FileDiffItem],
    ) -> None:
        if not source_node or not source_node.absolute_path:
            return
        source_root = Path(source_node.absolute_path)
        if not source_root.is_dir():
            return
        known = {item.relative_path.casefold() for item in items}
        target_root = Path(target_node.absolute_path) if target_node and target_node.absolute_path else None
        for source_file in source_root.rglob("*"):
            if not source_file.is_file():
                continue
            within_action = source_file.relative_to(source_root)
            relative_path = (Path(action_path) / within_action).as_posix()
            if relative_path.casefold() in known:
                continue
            target_file = target_root / within_action if target_root else None
            status = self._compare_auxiliary_file(source_file, target_file)
            items.append(
                FileDiffItem(
                    relative_path=relative_path,
                    name=source_file.name,
                    status=status,
                    source_path=str(source_file),
                    target_path=str(target_file) if target_file else None,
                    size_bytes=source_file.stat().st_size,
                )
            )

    def _compare_auxiliary_file(self, source: Path, target: Path | None) -> str:
        if not target or not target.exists() or not target.is_file():
            return "only_left"
        if self._hash_cache is not None:
            return "same" if self._hash_cache.files_equal(source, target) else "different"
        return "same" if files_equal(source, target) else "different"

    @staticmethod
    def _is_image_pair(pair: ComparePair) -> bool:
        return bool(
            (pair.left and pair.left.node_type == "image")
            or (pair.right and pair.right.node_type == "image")
        )

    @staticmethod
    def _collect_sequence_paths(root: TreeNode) -> set[str]:
        """收集可作为「动作」展示的节点路径。

        ``sequence`` 为传统序列帧动作目录；``atlas`` 为图集条目
        （一张打包图集 = 一个动作，内部 png/plist 记在 frame_files）。
        """
        result: set[str] = set()
        stack = [root]
        while stack:
            node = stack.pop()
            if node.node_type in {"sequence", "atlas"} and node.relative_path:
                result.add(node.relative_path)
            stack.extend(node.children)
        return result

    @staticmethod
    def _natural_key(value: str) -> list[int | str]:
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]
