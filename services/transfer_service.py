from __future__ import annotations

import hashlib
import os
import stat
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

from models.transfer_job import TransferItem, TransferJob
from services.atlas_scan_service import ATLAS_PNG, ATLAS_PLIST
from utils.file_utils import iter_files_recursively
from utils.hash_utils import hash_file


class PathEscapeError(ValueError):
    """相对路径越出根目录时抛出。"""


class TransferService:
    def build_job_for_files(self, left_root: str, right_root: str, relative_paths: list[str]) -> TransferJob:
        """按相对路径构建传输任务。

        图集条目强制「png + plist 成对传输」：只要勾选了其中任一文件，
        就把同名的另一个也一并纳入，避免目标端出现「有图无布局」或
        「有布局无图」的破损状态（客户端会直接渲染错乱）。
        """
        items: list[TransferItem] = []
        left = self._resolve_root(left_root)
        right = self._resolve_root(right_root)
        for relative_path in sorted(self._expand_atlas_pairs(left, relative_paths)):
            source = self._safe_join(left, relative_path)
            target = self._safe_join(right, relative_path)
            if source is None or target is None:
                continue
            if not source.exists() or not source.is_file():
                continue
            items.append(
                TransferItem(
                    relative_path=Path(relative_path).as_posix(),
                    source_path=str(source),
                    target_path=str(target),
                )
            )
        return TransferJob(items=items)

    @classmethod
    def expand_atlas_paths(cls, left_root: str | Path, relative_paths: list[str]) -> list[str]:
        """按来源目录展开图集伴随文件，返回去重排序后的相对路径列表。"""
        left = Path(left_root).resolve()
        return sorted(cls._expand_atlas_pairs(left, relative_paths))

    @classmethod
    def _expand_atlas_pairs(cls, left_root: Path, relative_paths: list[str]) -> set[str]:
        """把勾选的图集文件补全为成对集合（兼容扩展名大小写）。"""
        expanded: set[str] = set()
        seen_keys: set[str] = set()
        dir_entries: dict[Path, dict[str, str]] = {}
        case_insensitive = os.name == "nt" or sys.platform == "darwin"

        def _record(rel_text: str) -> None:
            key = rel_text.casefold() if case_insensitive else rel_text
            if key in seen_keys:
                return
            seen_keys.add(key)
            expanded.add(rel_text)

        def _entries_for(parent_dir: Path | None) -> dict[str, str]:
            if parent_dir is None:
                return {}
            cached = dir_entries.get(parent_dir)
            if cached is None:
                try:
                    cached = {
                        entry.name.casefold(): entry.name
                        for entry in os.scandir(parent_dir)
                        if entry.is_file()
                    }
                except OSError:
                    cached = {}
                dir_entries[parent_dir] = cached
            return cached

        for relative_path in relative_paths:
            raw_rel = (relative_path or "").replace("\\", "/")
            if not raw_rel.strip():
                continue
            rel_obj = Path(raw_rel)
            if rel_obj.is_absolute() or rel_obj.drive or rel_obj.root:
                continue
            rel_posix = rel_obj.as_posix()
            if not rel_posix or rel_posix == ".":
                continue
            if cls._safe_join(left_root, rel_posix) is None:
                continue

            parent = rel_obj.parent
            parent_dir = left_root if parent == Path(".") else cls._safe_join(left_root, parent.as_posix())
            entries = _entries_for(parent_dir)
            actual_self = entries.get(rel_obj.name.casefold(), rel_obj.name)
            _record((parent / actual_self).as_posix())

            name = rel_obj.name
            lower = name.lower()
            if lower.endswith(ATLAS_PNG):
                stem = name[: -len(ATLAS_PNG)]
                self_ext, partner_ext = ATLAS_PNG, ATLAS_PLIST
            elif lower.endswith(ATLAS_PLIST):
                stem = name[: -len(ATLAS_PLIST)]
                self_ext, partner_ext = ATLAS_PLIST, ATLAS_PNG
            else:
                continue

            self_actual = entries.get(f"{stem}{self_ext}".casefold())
            partner_actual = entries.get(f"{stem}{partner_ext}".casefold())
            if self_actual is None or partner_actual is None:
                continue
            partner_rel = (parent / partner_actual).as_posix()
            if cls._safe_join(left_root, partner_rel) is None:
                continue
            _record(partner_rel)
        return expanded

    def build_job_for_node(self, left_root: str, right_root: str, relative_paths: list[str]) -> TransferJob:
        items: list[TransferItem] = []
        left = self._resolve_root(left_root)
        right = self._resolve_root(right_root)
        for relative_path in relative_paths:
            source = self._safe_join(left, relative_path) if relative_path else left
            target = self._safe_join(right, relative_path) if relative_path else right
            if source is None or target is None:
                continue
            if not source.exists():
                continue
            for file in iter_files_recursively(source):
                target_file = target / file.relative_to(source)
                # 递归展开后再校验一次，防止 symlink 环逃逸
                try:
                    target_file_resolved = target_file.resolve()
                    right_resolved = right.resolve()
                    target_file_resolved.relative_to(right_resolved)
                except (ValueError, OSError):
                    continue
                rel = (Path(relative_path) / file.relative_to(source)).as_posix() if relative_path else file.relative_to(source).as_posix()
                items.append(TransferItem(relative_path=rel, source_path=str(file), target_path=str(target_file)))
        deduped = {item.relative_path: item for item in items}
        return TransferJob(items=list(deduped.values()))

    def copy_job(
        self,
        job: TransferJob,
        callbacks: dict[str, Callable[..., None]],
        cancel_token: object | None = None,
    ) -> None:
        callbacks["job_started"](job.total_files)
        success = 0
        failed = 0
        skipped = 0
        for index, item in enumerate(job.items, start=1):
            if cancel_token and cancel_token.is_cancelled():
                skipped += job.total_files - index + 1
                callbacks["job_failed"]("传输已取消")
                break
            source = Path(item.source_path)
            target = Path(item.target_path)
            if not source.exists():
                failed += 1
                callbacks["job_failed"](f"源文件不存在: {source}")
                continue
            callbacks["file_started"](index, item.relative_path, source.stat().st_size)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                self._copy_file(source, target, callbacks["progress_changed"], cancel_token)
                success += 1
                callbacks["file_finished"](index, item.relative_path, True)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                callbacks["job_failed"](f"{item.relative_path} 复制失败: {exc}")
                callbacks["file_finished"](index, item.relative_path, False)
        callbacks["job_completed"](success, failed, skipped)

    def _copy_file(
        self,
        source: Path,
        target: Path,
        progress_callback: Callable[[int, int], None],
        cancel_token: object | None = None,
    ) -> None:
        """原子复制：先写临时文件，校验通过后再替换目标。"""
        total = source.stat().st_size
        copied = 0
        source_digest = hashlib.blake2b(digest_size=16)
        # 进度回调节流：避免大文件高速复制时信号风暴阻塞 UI
        _progress_interval = 0.1  # 秒
        _last_progress_time = 0.0

        # 临时文件放在目标同目录，确保与目标在同一卷（os.replace 原子要求）
        tmp_path = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex[:8]}")
        try:
            with source.open("rb") as src, tmp_path.open("wb") as dst:
                while True:
                    if cancel_token and cancel_token.is_cancelled():
                        raise InterruptedError("传输已取消")
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    source_digest.update(chunk)
                    copied += len(chunk)
                    now = time.monotonic()
                    if now - _last_progress_time >= _progress_interval:
                        _last_progress_time = now
                        progress_callback(copied, total)

            # 最后再发一次最终进度，确保显示 100%
            if copied != total or total == 0:
                progress_callback(copied, total)

            # 先在临时文件上校验，失败则直接清理，不碰目标
            if source_digest.hexdigest() != hash_file(tmp_path):
                raise OSError(f"临时文件写入校验失败: {tmp_path}")

            # 目标若为只读，先去掉只读位再替换
            if target.exists():
                self._ensure_writable(target)

            os.replace(tmp_path, target)
        finally:
            # 任何异常（包括校验失败、权限错误）都清理临时文件
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _resolve_root(root: str) -> Path:
        return Path(root).resolve()

    @staticmethod
    def _safe_join(root: Path, relative_path: str) -> Path | None:
        """把相对路径安全拼接到根目录，越界返回 None。"""
        try:
            candidate = (root / Path(relative_path)).resolve()
            # 用 relative_to 验证是否在 root 之内
            candidate.relative_to(root)
            return candidate
        except (ValueError, OSError):
            return None

    @staticmethod
    def _ensure_writable(path: Path) -> None:
        """如果文件是只读的，去掉只读属性。"""
        try:
            mode = path.stat().st_mode
            if not (mode & stat.S_IWUSR):
                path.chmod(mode | stat.S_IWUSR)
        except OSError:
            # 改不动也别阻塞复制，让后面的 os.replace 自己报原始错误
            pass
