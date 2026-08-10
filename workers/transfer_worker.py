from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from models.transfer_job import TransferJob
from services.transfer_service import TransferService


class TransferWorker(QObject):
    job_started = Signal(int)
    file_started = Signal(int, str, int)
    progress_changed = Signal(int, int)
    file_finished = Signal(int, str, bool)
    job_completed = Signal(int, int, int)
    job_failed = Signal(str)

    def __init__(self, job: TransferJob) -> None:
        super().__init__()
        self.job = job
        self.service = TransferService()

    @Slot()
    def run(self) -> None:
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
        )
