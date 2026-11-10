"""传输前自动回滚备份服务（方案 A：仅备份即将被覆盖的目标旧文件）。"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from models.transfer_job import TransferJob
from utils.path_matcher import normalize_path

DEFAULT_BACKUP_DIR_WINDOWS = "D:/GitWork/MiaoSpritesPackage/备份"
_MAX_COMMENT_BYTES = 65000
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def default_backup_dir() -> str:
    """返回当前平台下的默认备份目录。"""
    if os.name == "nt":
        return DEFAULT_BACKUP_DIR_WINDOWS
    try:
        return normalize_path(str(Path.home() / "Documents" / "MMY-ActionFileSync-Backups"))
    except NotImplementedError:
        # Windows 单元测试 mock os.name="posix" 时，Path 会因尝试实例化 PosixPath 而抛错
        home_dir = os.path.expanduser("~").replace("\\", "/").rstrip("/")
        return f"{home_dir}/Documents/MMY-ActionFileSync-Backups"


def paths_overlap(first: str, second: str) -> bool:
    """判断两路径是否相同或互为父子目录；空路径或解析异常返回 False。"""
    first_text = (first or "").strip()
    second_text = (second or "").strip()
    if not first_text or not second_text:
        return False
    try:
        first_resolved = Path(first_text).resolve()
        second_resolved = Path(second_text).resolve()
    except (OSError, ValueError):
        return False
    if sys.platform == "darwin":
        first_cmp = PurePosixPath(first_resolved.as_posix().casefold())
        second_cmp = PurePosixPath(second_resolved.as_posix().casefold())
        return (
            first_cmp == second_cmp
            or first_cmp.is_relative_to(second_cmp)
            or second_cmp.is_relative_to(first_cmp)
        )
    return (
        first_resolved == second_resolved
        or first_resolved.is_relative_to(second_resolved)
        or second_resolved.is_relative_to(first_resolved)
    )


class BackupCancelledError(InterruptedError):
    """传输前备份被取消时抛出。"""


@dataclass
class BackupOutcome:
    created: bool
    zip_path: str = ""
    file_count: int = 0
    total_bytes: int = 0
    skipped_reason: str = ""


class BackupService:
    """在覆盖目标文件前创建可一键解压回滚的 ZIP 备份。"""

    @staticmethod
    def validate_backup_dir(left_root: str, right_root: str, backup_dir: str) -> str:
        """校验备份目录非空、为绝对路径、非文件且不与来源/目标目录重叠，返回去除首尾空白后的路径。"""
        cleaned = (backup_dir or "").strip()
        if not cleaned:
            raise ValueError("备份目录不能为空，请先设置有效的备份目录。")
        backup_path = Path(cleaned)
        if not backup_path.is_absolute():
            raise ValueError("备份目录必须为完整绝对路径，不能使用相对路径。")
        try:
            resolved = backup_path.resolve()
        except (OSError, ValueError) as exc:
            raise ValueError(f"备份目录路径无效：{cleaned}") from exc
        if resolved.exists() and not resolved.is_dir():
            raise ValueError("备份路径已存在且是文件，请更换为文件夹路径。")
        if paths_overlap(cleaned, left_root):
            raise ValueError("备份目录不能与来源目录重合或互为父子目录，请更换为独立目录。")
        if paths_overlap(cleaned, right_root):
            raise ValueError("备份目录不能与目标目录重合或互为父子目录，请更换为独立目录。")
        return cleaned

    def collect_overwrite_targets(self, right_root: str, job: TransferJob) -> list[tuple[str, Path]]:
        """仅收集目标目录内实际存在且即将被 job 覆盖的旧文件。"""
        right_text = (right_root or "").strip()
        if not right_text:
            return []
        try:
            right_resolved = Path(right_text).resolve()
        except (OSError, ValueError):
            return []
        if not right_resolved.is_dir():
            return []

        targets: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for item in job.items:
            raw_rel = (item.relative_path or "").replace("\\", "/")
            if not raw_rel.strip():
                continue
            rel_path = Path(raw_rel)
            if rel_path.is_absolute() or rel_path.drive or rel_path.root:
                continue
            try:
                candidate = (right_resolved / rel_path).resolve()
                rel_inside = candidate.relative_to(right_resolved)
            except (ValueError, OSError):
                continue
            if not candidate.exists() or not candidate.is_file():
                continue
            rel_posix = rel_inside.as_posix()
            if not rel_posix or rel_posix == ".":
                continue
            seen_key = rel_posix.casefold() if (os.name == "nt" or sys.platform == "darwin") else rel_posix
            if seen_key in seen:
                continue
            seen.add(seen_key)
            targets.append((rel_posix, candidate))
        return targets

    def backup_before_transfer(
        self,
        left_root: str,
        right_root: str,
        backup_dir: str,
        job: TransferJob,
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_token: object | None = None,
        started_callback: Callable[[int], None] | None = None,
    ) -> BackupOutcome:
        """执行传输前备份（仅打包将被覆盖的旧文件）。"""
        self._check_cancelled(cancel_token)
        cleaned_backup_dir = self.validate_backup_dir(left_root, right_root, backup_dir)
        targets = self.collect_overwrite_targets(right_root, job)
        if not targets:
            return BackupOutcome(created=False, skipped_reason="no_overwrites")

        self._check_cancelled(cancel_token)
        if started_callback is not None:
            started_callback(len(targets))

        backup_root = Path(cleaned_backup_dir)
        backup_root.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        timestamp_for_name = now.strftime("%Y%m%d_%H%M%S")
        target_name = self._sanitize_target_name(right_root)
        zip_path = self._unique_zip_path(backup_root, target_name, timestamp_for_name)
        tmp_path = zip_path.with_name(f".{zip_path.name}.tmp-{uuid.uuid4().hex[:8]}")

        total = len(targets)
        total_bytes = 0
        written_files: list[str] = []

        try:
            self._check_cancelled(cancel_token)
            with zipfile.ZipFile(
                tmp_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=1,
                strict_timestamps=False,
            ) as zip_file:
                for index, (rel_posix, target_file) in enumerate(targets, start=1):
                    self._check_cancelled(cancel_token)
                    file_size = target_file.stat().st_size
                    zip_file.write(target_file, arcname=rel_posix)
                    total_bytes += file_size
                    written_files.append(rel_posix)
                    if progress_callback is not None:
                        progress_callback(index, total, rel_posix)

                comment_bytes = self._build_comment_bytes(
                    timestamp=now.isoformat(timespec="seconds"),
                    left_root=left_root,
                    right_root=right_root,
                    file_count=total,
                    total_bytes=total_bytes,
                    files=written_files,
                )
                zip_file.comment = comment_bytes

            self._check_cancelled(cancel_token)
            os.replace(tmp_path, zip_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        return BackupOutcome(
            created=True,
            zip_path=normalize_path(str(zip_path)),
            file_count=total,
            total_bytes=total_bytes,
        )

    @staticmethod
    def _check_cancelled(cancel_token: object | None) -> None:
        if cancel_token and cancel_token.is_cancelled():
            raise BackupCancelledError("传输已取消")

    @staticmethod
    def _sanitize_target_name(right_root: str) -> str:
        raw = (right_root or "").strip()
        if not raw:
            return "target"
        path = Path(raw)
        name = path.name
        if not name:
            try:
                name = path.resolve().name
            except (OSError, ValueError):
                name = ""
        if not name and path.drive:
            name = path.drive.rstrip(":\\/")
        sanitized = _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
        return sanitized or "target"

    @staticmethod
    def _unique_zip_path(backup_root: Path, target_name: str, timestamp: str) -> Path:
        base_stem = f"{target_name}_{timestamp}_rollback"
        candidate = backup_root / f"{base_stem}.zip"
        if not candidate.exists():
            return candidate
        index = 1
        while True:
            numbered = backup_root / f"{base_stem}_{index}.zip"
            if not numbered.exists():
                return numbered
            index += 1

    @staticmethod
    def _build_comment_bytes(
        timestamp: str,
        left_root: str,
        right_root: str,
        file_count: int,
        total_bytes: int,
        files: list[str],
        max_bytes: int = _MAX_COMMENT_BYTES,
    ) -> bytes:
        base_left = normalize_path((left_root or "").strip())
        base_right = normalize_path((right_root or "").strip())
        payload: dict[str, object] = {
            "timestamp": timestamp,
            "left_root": base_left,
            "right_root": base_right,
            "file_count": file_count,
            "total_bytes": total_bytes,
            "files": files,
            "files_truncated": False,
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) <= max_bytes:
            return encoded

        payload["files_truncated"] = True
        lo = 0
        hi = len(files)
        best: bytes | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            payload["files"] = files[:mid]
            candidate = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(candidate) <= max_bytes:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        if best is not None:
            return best

        # 极端兜底：即使 files 为空也超限（例如路径字符串本身超长）时逐步缩短根路径文本
        payload["files"] = []
        for bound in (1024, 256, 64, 0):
            payload["left_root"] = base_left[:bound]
            payload["right_root"] = base_right[:bound]
            minimal = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(minimal) <= max_bytes:
                return minimal
        return b"{}"
