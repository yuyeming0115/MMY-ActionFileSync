from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services.refresh_service import RefreshService


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, left_root: str, right_root: str) -> None:
        super().__init__()
        self.left_root = left_root
        self.right_root = right_root
        self.refresh_service = RefreshService()

    @Slot()
    def run(self) -> None:
        try:
            result = self.refresh_service.refresh(self.left_root, self.right_root)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
