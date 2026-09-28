from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from natsort import natsorted

from services.scan_service import ScanCancelledError
from utils.file_utils import IMAGE_EXTENSIONS


@dataclass
class RedundancyItem:
    """一个被判为冗余的动作目录。"""

    relative_path: str  # 相对扫描根的 posix 路径，如 "501121253_body/E/hurt"
    direction: str  # 方向目录名（原样大小写）
    action_name: str  # 动作目录名（原样大小写）
    frame_count: int  # 图片帧数
    file_count: int  # 全部文件数（含 GIF 预览）
    total_bytes: int


@dataclass
class MoveOutcome:
    moved: int = 0
    failed: int = 0
    cancelled: bool = False


class RedundancyService:
    """按「冗余方向 × 非保留动作」规则扫描并清理冗余动作目录。

    判定规则：任意深度下，含图片文件的叶子目录视为动作目录（与主扫描的
    sequence 判定一致）；其父目录名属于冗余方向集合、且自身目录名不属于
    保留动作集合时，整个动作目录判为冗余。方向/动作均按 casefold 匹配。
    """

    _PROGRESS_INTERVAL = 25  # 每遍历多少个目录回调一次进度

    def scan(
        self,
        root_path: str,
        redundant_directions: Iterable[str],
        keep_actions: Iterable[str],
        cancel_token: object | None = None,
        progress_callback: Callable[[int], None] | None = None,
    ) -> list[RedundancyItem]:
        root = Path(root_path)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"目录不存在: {root_path}")
        directions = {value.strip().casefold() for value in redundant_directions if value.strip()}
        keeps = {value.strip().casefold() for value in keep_actions if value.strip()}
        self._cancel_token = cancel_token
        self._progress_callback = progress_callback
        self._visited = 0
        try:
            return self._scan_root(root, directions, keeps)
        finally:
            self._cancel_token = None
            self._progress_callback = None

    def move_to_backup(
        self,
        root_path: str,
        backup_root: str,
        items: list[RedundancyItem],
        callbacks: dict[str, Callable[..., None]] | None = None,
        cancel_token: object | None = None,
    ) -> MoveOutcome:
        """把冗余动作目录整体移动到备份目录，保留相对结构，绝不覆盖同名目标。"""
        callbacks = callbacks or {}
        root = Path(root_path).resolve()
        backup = Path(backup_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"目录不存在: {root_path}")
        on_item_started = callbacks.get("item_started", lambda *args: None)
        on_item_finished = callbacks.get("item_finished", lambda *args: None)
        outcome = MoveOutcome()
        total = len(items)
        for index, item in enumerate(items, start=1):
            if cancel_token and cancel_token.is_cancelled():
                outcome.cancelled = True
                break
            on_item_started(index, total, item.relative_path)
            error = self._move_one(root, backup, item)
            if error is None:
                outcome.moved += 1
            else:
                outcome.failed += 1
            on_item_finished(index, item.relative_path, error is None, error or "")
        return outcome

    def _scan_root(self, root: Path, directions: set[str], keeps: set[str]) -> list[RedundancyItem]:
        items: list[RedundancyItem] = []
        for current, dir_names, file_names in os.walk(root):
            self._check_cancelled()
            self._report_progress()
            # 跳过隐藏目录（.svn 等），并保持遍历顺序稳定
            dir_names[:] = natsorted(name for name in dir_names if not name.startswith("."))
            current_path = Path(current)
            if current_path == root:
                continue
            image_names = [name for name in file_names if Path(name).suffix.lower() in IMAGE_EXTENSIONS]
            if not image_names:
                continue
            direction = current_path.parent.name
            if direction.casefold() not in directions:
                continue
            action_name = current_path.name
            if action_name.casefold() in keeps:
                continue
            file_sizes = [
                (current_path / name).stat().st_size
                for name in file_names
                if (current_path / name).is_file()
            ]
            items.append(
                RedundancyItem(
                    relative_path=current_path.relative_to(root).as_posix(),
                    direction=direction,
                    action_name=action_name,
                    frame_count=len(image_names),
                    file_count=len(file_sizes),
                    total_bytes=sum(file_sizes),
                )
            )
        return natsorted(items, key=lambda item: item.relative_path)

    def _move_one(self, root: Path, backup: Path, item: RedundancyItem) -> str | None:
        """移动单个动作目录，返回错误信息；成功返回 None。"""
        source = self._safe_join(root, item.relative_path)
        target = self._safe_join(backup, item.relative_path)
        if source is None or target is None:
            return "路径越界，已跳过"
        if not source.is_dir():
            return "源目录不存在，已跳过"
        final_target = self._unique_target(target)
        try:
            final_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(final_target))
        except (OSError, shutil.Error) as exc:
            return f"移动失败: {exc}"
        return None

    def _check_cancelled(self) -> None:
        if self._cancel_token and self._cancel_token.is_cancelled():
            raise ScanCancelledError("扫描已取消")

    def _report_progress(self) -> None:
        self._visited += 1
        if self._progress_callback and self._visited % self._PROGRESS_INTERVAL == 0:
            self._progress_callback(self._visited)

    @staticmethod
    def _safe_join(root: Path, relative_path: str) -> Path | None:
        """把相对路径安全拼接到根目录，越界返回 None。"""
        try:
            candidate = (root / Path(relative_path)).resolve()
            candidate.relative_to(root)
            return candidate
        except (ValueError, OSError):
            return None

    @staticmethod
    def _unique_target(target: Path) -> Path:
        """目标重名时追加 _1/_2 后缀，保证不覆盖已有目录。"""
        if not target.exists():
            return target
        for index in range(1, 1000):
            candidate = target.with_name(f"{target.name}_{index}")
            if not candidate.exists():
                return candidate
        return target.with_name(f"{target.name}_{uuid.uuid4().hex[:8]}")
