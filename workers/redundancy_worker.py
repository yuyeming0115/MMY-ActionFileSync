from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services.redundancy_service import RedundancyItem, RedundancyService
from utils.cancel_token import CancellationToken


class RedundancyScanWorker(QObject):
    finished = Signal(object)  # list[RedundancyItem]
    failed = Signal(str)
    progress = Signal(int)  # 已遍历目录数

    def __init__(
        self,
        root: str,
        redundant_directions: list[str],
        keep_actions: list[str],
        cancel_token: CancellationToken | None = None,
    ) -> None:
        super().__init__()
        self.root = root
        self.redundant_directions = redundant_directions
        self.keep_actions = keep_actions
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            service = RedundancyService()
            items = service.scan(
                self.root,
                self.redundant_directions,
                self.keep_actions,
                cancel_token=self._cancel_token,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(items)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class RedundancyMoveWorker(QObject):
    item_started = Signal(int, int, str)
    item_finished = Signal(int, str, bool, str)  # index, relative_path, ok, error
    finished = Signal(object)  # MoveOutcome
    failed = Signal(str)

    def __init__(
        self,
        root: str,
        backup_root: str,
        items: list[RedundancyItem],
        cancel_token: CancellationToken | None = None,
    ) -> None:
        super().__init__()
        self.root = root
        self.backup_root = backup_root
        self.items = items
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            service = RedundancyService()
            outcome = service.move_to_backup(
                self.root,
                self.backup_root,
                self.items,
                callbacks={
                    "item_started": lambda index, total, rel: self.item_started.emit(index, total, rel),
                    "item_finished": lambda index, rel, ok, error: self.item_finished.emit(index, rel, ok, error),
                },
                cancel_token=self._cancel_token,
            )
            self.finished.emit(outcome)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
