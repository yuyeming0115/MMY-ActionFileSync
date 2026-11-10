from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from models.transfer_job import TransferJob
from services.backup_service import BackupCancelledError, BackupService
from services.transfer_service import TransferService
from utils.cancel_token import CancellationToken


class TransferWorker(QObject):
    job_started = Signal(int)
    file_started = Signal(int, str, int)
    progress_changed = Signal(int, int)
    file_finished = Signal(int, str, bool)
    job_completed = Signal(int, int, int)
    job_failed = Signal(str)
    backup_started = Signal(int)
    backup_progress = Signal(int, int, str)
    backup_finished = Signal(bool, str, int, int)  # created, zip_path, file_count, total_bytes
    backup_skipped = Signal(str)
    backup_failed = Signal(str)

    def __init__(
        self,
        job: TransferJob,
        cancel_token: CancellationToken | None = None,
        backup_enabled: bool = False,
        backup_dir: str = "",
        left_root: str = "",
        right_root: str = "",
    ) -> None:
        super().__init__()
        self.job = job
        self.service = TransferService()
        self.backup_service = BackupService()
        self._cancel_token = cancel_token
        self._backup_enabled = backup_enabled
        self._backup_dir = backup_dir
        self._left_root = left_root
        self._right_root = right_root

    @Slot()
    def run(self) -> None:
        if self._backup_enabled:
            try:
                outcome = self.backup_service.backup_before_transfer(
                    self._left_root,
                    self._right_root,
                    self._backup_dir,
                    self.job,
                    progress_callback=self.backup_progress.emit,
                    cancel_token=self._cancel_token,
                    started_callback=self.backup_started.emit,
                )
                if outcome.created:
                    self.backup_finished.emit(
                        True,
                        outcome.zip_path,
                        outcome.file_count,
                        outcome.total_bytes,
                    )
                else:
                    self.backup_skipped.emit("目标目录没有会被覆盖的旧文件，跳过生成备份 zip")
            except BackupCancelledError:
                self.job_failed.emit("传输已取消（备份阶段中止，未修改任何目标文件）")
                self.job_completed.emit(0, 0, self.job.total_files)
                return
            except Exception as exc:  # noqa: BLE001
                detail = str(exc) or type(exc).__name__
                self.backup_failed.emit(detail)
                self.job_failed.emit(f"传输前备份失败（已中止传输，未修改任何目标文件）: {detail}")
                self.job_completed.emit(0, self.job.total_files, 0)
                return

        self.service.copy_job(
            self.job,
            callbacks={
                "job_started": self.job_started.emit,
                "file_started": self.file_started.emit,
                "progress_changed": self.progress_changed.emit,
                "file_finished": self.file_finished.emit,
                "job_completed": self.job_completed.emit,
                "job_failed": self.job_failed.emit,
            },
            cancel_token=self._cancel_token,
        )
