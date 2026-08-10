from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class TransferPreviewDialog(QDialog):
    def __init__(
        self,
        left_root: str,
        right_root: str,
        relative_paths: list[str],
        action_map: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("确认传输范围")
        self.resize(1040, 620)
        self.left_root = Path(left_root)
        self.right_root = Path(right_root)
        self.action_map = action_map or {}
        self._updating_checks = False

        layout = QVBoxLayout(self)
        heading = QLabel("请确认将从来源复制到目标的文件。可以取消动作或单个文件。")
        heading.setWordWrap(True)
        self.info_label = QLabel()
        self.info_label.setProperty("selectionSummary", True)
        layout.addWidget(heading)
        layout.addWidget(self.info_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["动作 / 文件", "目标位置", "状态", "大小"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setIndentation(18)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree, 1)

        button_row = QHBoxLayout()
        self.select_all_button = QPushButton("全选")
        self.clear_button = QPushButton("全不选")
        self.confirm_button = QPushButton("开始传输")
        self.confirm_button.setProperty("primaryAction", True)
        self.cancel_button = QPushButton("取消")
        button_row.addWidget(self.select_all_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.confirm_button)
        layout.addLayout(button_row)

        self._build_tree(relative_paths)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.select_all_button.clicked.connect(lambda: self._set_all_checks(Qt.Checked))
        self.clear_button.clicked.connect(lambda: self._set_all_checks(Qt.Unchecked))
        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self._update_summary()

    def selected_paths(self) -> list[str]:
        paths: list[str] = []
        for group_index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(group_index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.checkState(0) == Qt.Checked:
                    relative_path = child.data(0, Qt.UserRole)
                    if relative_path:
                        paths.append(str(relative_path))
        return sorted(set(paths))

    def _build_tree(self, relative_paths: list[str]) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for relative_path in sorted(set(relative_paths)):
            source = self.left_root / Path(relative_path)
            if source.is_file():
                groups[self.action_map.get(relative_path, Path(relative_path).parent.as_posix())].append(relative_path)

        self._updating_checks = True
        try:
            for action_path, paths in sorted(groups.items()):
                parent = QTreeWidgetItem(self.tree)
                parent.setText(0, Path(action_path).name or action_path)
                parent.setText(1, (self.right_root / Path(action_path)).as_posix())
                parent.setText(2, f"{len(paths)} 个文件")
                parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                parent.setCheckState(0, Qt.Checked)
                parent.setExpanded(True)
                for relative_path in paths:
                    source = self.left_root / Path(relative_path)
                    target = self.right_root / Path(relative_path)
                    child = QTreeWidgetItem(parent)
                    child.setText(0, Path(relative_path).name)
                    child.setText(1, target.as_posix())
                    child.setText(2, "覆盖" if target.exists() else "新增")
                    child.setText(3, self._format_size(source.stat().st_size))
                    child.setData(0, Qt.UserRole, relative_path)
                    child.setData(3, Qt.UserRole, source.stat().st_size)
                    child.setToolTip(0, relative_path)
                    child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.Checked)
        finally:
            self._updating_checks = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_checks or column != 0:
            return
        self._updating_checks = True
        try:
            if item.parent() is None:
                state = item.checkState(0)
                if state in {Qt.Checked, Qt.Unchecked}:
                    for index in range(item.childCount()):
                        item.child(index).setCheckState(0, state)
            else:
                self._sync_parent(item.parent())
        finally:
            self._updating_checks = False
        self._update_summary()

    def _sync_parent(self, parent: QTreeWidgetItem) -> None:
        checked = sum(parent.child(index).checkState(0) == Qt.Checked for index in range(parent.childCount()))
        if checked == 0:
            parent.setCheckState(0, Qt.Unchecked)
        elif checked == parent.childCount():
            parent.setCheckState(0, Qt.Checked)
        else:
            parent.setCheckState(0, Qt.PartiallyChecked)

    def _set_all_checks(self, state: Qt.CheckState) -> None:
        self._updating_checks = True
        try:
            for group_index in range(self.tree.topLevelItemCount()):
                group = self.tree.topLevelItem(group_index)
                group.setCheckState(0, state)
                for child_index in range(group.childCount()):
                    group.child(child_index).setCheckState(0, state)
        finally:
            self._updating_checks = False
        self._update_summary()

    def _update_summary(self) -> None:
        action_count = 0
        file_count = 0
        total_bytes = 0
        for group_index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(group_index)
            group_has_selection = False
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.checkState(0) != Qt.Checked:
                    continue
                group_has_selection = True
                file_count += 1
                total_bytes += int(child.data(3, Qt.UserRole) or 0)
            action_count += int(group_has_selection)
        self.info_label.setText(
            f"将传输 {action_count} 个动作 · {file_count} 个文件 · {self._format_size(total_bytes)}"
        )
        self.confirm_button.setEnabled(file_count > 0)

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 ** 3:
            return f"{size / 1024 ** 3:.2f} GB"
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"
