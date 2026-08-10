from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QTreeView


class TreeSyncService:
    def find_index(self, model: QStandardItemModel, relative_path: str):
        stack = [model.index(row, 0) for row in range(model.rowCount())]
        while stack:
            index = stack.pop(0)
            if index.data(Qt.UserRole) == relative_path:
                return index
            for row in range(model.rowCount(index)):
                stack.append(model.index(row, 0, index))
        return None

    def sync_expand(self, relative_path: str, target_view: QTreeView, target_model: QStandardItemModel) -> None:
        index = self.find_index(target_model, relative_path)
        if index is None:
            return
        current = index
        while current.isValid():
            target_view.expand(current)
            current = current.parent()

    def sync_select(self, relative_path: str, target_view: QTreeView, target_model: QStandardItemModel):
        index = self.find_index(target_model, relative_path)
        if index is None:
            return None
        target_view.setCurrentIndex(index)
        target_view.scrollTo(index, QTreeView.PositionAtCenter)
        return index

    def align_target_row(self, source_view: QTreeView, source_index, target_view: QTreeView, target_index) -> None:
        if source_index is None or target_index is None:
            return
        if not source_index.isValid() or not target_index.isValid():
            return
        source_rect = source_view.visualRect(source_index)
        target_rect = target_view.visualRect(target_index)
        if not source_rect.isValid() or not target_rect.isValid():
            return
        delta = target_rect.top() - source_rect.top()
        scrollbar = target_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.value() + delta)
