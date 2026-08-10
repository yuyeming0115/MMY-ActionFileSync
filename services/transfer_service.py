from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from models.transfer_job import TransferItem, TransferJob
from utils.file_utils import iter_files_recursively
from utils.hash_utils import hash_file


class TransferService:
    def build_job_for_files(self, left_root: str, right_root: str, relative_paths: list[str]) -> TransferJob:
        items: list[TransferItem] = []
        left = Path(left_root)
        right = Path(right_root)
        for relative_path in sorted(set(relative_paths)):
            source = left / Path(relative_path)
            if not source.exists() or not source.is_file():
                continue
            items.append(
                TransferItem(
                    relative_path=Path(relative_path).as_posix(),
                    source_path=str(source),
                    target_path=str(right / Path(relative_path)),
                )
            )
        return TransferJob(items=items)

    def build_job_for_node(self, left_root: str, right_root: str, relative_paths: list[str]) -> TransferJob:
        items: list[TransferItem] = []
        for relative_path in relative_paths:
            source = Path(left_root) / Path(relative_path) if relative_path else Path(left_root)
            target = Path(right_root) / Path(relative_path) if relative_path else Path(right_root)
            if not source.exists():
                continue
            for file in iter_files_recursively(source):
                target_file = target / file.relative_to(source)
                rel = (Path(relative_path) / file.relative_to(source)).as_posix() if relative_path else file.relative_to(source).as_posix()
                items.append(TransferItem(relative_path=rel, source_path=str(file), target_path=str(target_file)))
        deduped = {item.relative_path: item for item in items}
        return TransferJob(items=list(deduped.values()))

    def copy_job(self, job: TransferJob, callbacks: dict[str, Callable[..., None]]) -> None:
        callbacks["job_started"](job.total_files)
        success = 0
        failed = 0
        skipped = 0
        for index, item in enumerate(job.items, start=1):
            source = Path(item.source_path)
            target = Path(item.target_path)
            if not source.exists():
                failed += 1
                callbacks["job_failed"](f"源文件不存在: {source}")
                continue
            callbacks["file_started"](index, item.relative_path, source.stat().st_size)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                self._copy_file(source, target, callbacks["progress_changed"])
                success += 1
                callbacks["file_finished"](index, item.relative_path, True)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                callbacks["job_failed"](f"{item.relative_path} 复制失败: {exc}")
                callbacks["file_finished"](index, item.relative_path, False)
        callbacks["job_completed"](success, failed, skipped)

    def _copy_file(self, source: Path, target: Path, progress_callback: Callable[[int, int], None]) -> None:
        total = source.stat().st_size
        copied = 0
        source_digest = hashlib.blake2b(digest_size=16)
        with source.open("rb") as src, target.open("wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                source_digest.update(chunk)
                copied += len(chunk)
                progress_callback(copied, total)
        if source_digest.hexdigest() != hash_file(target):
            raise OSError(f"目标文件写入校验失败: {target}")
