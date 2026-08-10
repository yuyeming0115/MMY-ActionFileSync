from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class ActionFilterPanel(QWidget):
    actions_changed = Signal()
    transfer_preview_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("动作筛选")
        title.setProperty("sectionTitle", True)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.select_all_button = QPushButton("全选")
        self.deselect_all_button = QPushButton("全不选")
        self.invert_button = QPushButton("反选")
        self.preview_button = QPushButton("传输预览")
        btn_row.addWidget(self.select_all_button)
        btn_row.addWidget(self.deselect_all_button)
        btn_row.addWidget(self.invert_button)
        btn_row.addWidget(self.preview_button)
        btn_row.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(120)

        self.check_container = QWidget()
        self.grid_layout = QGridLayout(self.check_container)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        self.grid_layout.setSpacing(6)
        scroll.setWidget(self.check_container)

        self.checkboxes: dict[str, QCheckBox] = {}

        layout.addWidget(title)
        layout.addLayout(btn_row)
        layout.addWidget(scroll)

        self.select_all_button.clicked.connect(self._select_all)
        self.deselect_all_button.clicked.connect(self._deselect_all)
        self.invert_button.clicked.connect(self._invert)
        self.preview_button.clicked.connect(self._on_preview_requested)

    def populate(self, action_names: list[str]) -> None:
        for cb in self.checkboxes.values():
            cb.deleteLater()
        self.checkboxes.clear()
        unique = sorted(set(n.lower() for n in action_names))
        cols = 6
        for i, name in enumerate(unique):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.stateChanged.connect(self.actions_changed.emit)
            cb.setFont(self.font())
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(cb, row, col)
            self.checkboxes[name] = cb

    def reset(self) -> None:
        for cb in self.checkboxes.values():
            cb.deleteLater()
        self.checkboxes.clear()

    def get_checked(self) -> list[str]:
        return [name for name, cb in self.checkboxes.items() if cb.isChecked()]

    def set_enabled(self, enabled: bool) -> None:
        for cb in self.checkboxes.values():
            cb.setEnabled(enabled)
        self.select_all_button.setEnabled(enabled)
        self.deselect_all_button.setEnabled(enabled)
        self.invert_button.setEnabled(enabled)

    def _select_all(self) -> None:
        for cb in self.checkboxes.values():
            cb.setChecked(True)

    def _deselect_all(self) -> None:
        for cb in self.checkboxes.values():
            cb.setChecked(False)

    def _invert(self) -> None:
        for cb in self.checkboxes.values():
            cb.setChecked(not cb.isChecked())

    def _on_preview_requested(self) -> None:
        self.transfer_preview_requested.emit()
