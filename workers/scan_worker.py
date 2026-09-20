from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services.refresh_service import RefreshService
from utils.cancel_token import CancellationToken
from utils.hash_utils import HashCache


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        left_root: str,
        right_root: str,
        hash_cache: HashCache | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        super().__init__()
        self.left_root = left_root
        self.right_root = right_root
        self.refresh_service = RefreshService(hash_cache=hash_cache)
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            result = self.refresh_service.refresh(
                self.left_root,
                self.right_root,
                cancel_token=self._cancel_token,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
