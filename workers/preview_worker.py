from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from models.tree_node import TreeNode
from services.preview_service import PreviewService


class PreviewWorker(QObject):
    finished = Signal(object)
    failed = Signal(str, str)

    def __init__(self, side: str, relative_path: str, node: TreeNode | None) -> None:
        super().__init__()
        self.side = side
        self.relative_path = relative_path
        self.node = node
        self.preview_service = PreviewService()

    @Slot()
    def run(self) -> None:
        try:
            item = self.preview_service.build_preview(self.side, self.relative_path, self.node)
            self.finished.emit(item)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.side, str(exc))
