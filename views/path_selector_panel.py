from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QGridLayout, QLabel, QLineEdit, QPushButton, QWidget


class DropPathLineEdit(QLineEdit):
    path_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setAcceptDrops(True)
        self.setPlaceholderText("可拖拽文件夹到此，或点击右侧按钮选择")

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if not urls:
            return
        local_path = urls[0].toLocalFile()
        if local_path:
            self.path_dropped.emit(local_path)


class PathSelectorPanel(QWidget):
    path_changed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)

        self.left_label = QLabel("新文件夹区域:")
        self.right_label = QLabel("SVN文件夹区域:")
        self.left_edit = DropPathLineEdit()
        self.right_edit = DropPathLineEdit()
        self.left_button = QPushButton("重新选择")
        self.right_button = QPushButton("重新选择")

        layout.addWidget(self.left_label, 0, 0)
        layout.addWidget(self.left_edit, 0, 1)
        layout.addWidget(self.left_button, 0, 2)
        layout.addWidget(self.right_label, 1, 0)
        layout.addWidget(self.right_edit, 1, 1)
        layout.addWidget(self.right_button, 1, 2)

        layout.setColumnStretch(1, 1)

        self.left_path = ""
        self.right_path = ""

        self.left_button.clicked.connect(lambda: self._choose_path("left"))
        self.right_button.clicked.connect(lambda: self._choose_path("right"))
        self.left_edit.path_dropped.connect(lambda path: self._set_path("left", path))
        self.right_edit.path_dropped.connect(lambda path: self._set_path("right", path))

    def set_paths(self, left_path: str, right_path: str) -> None:
        self.left_path = left_path
        self.right_path = right_path
        self.left_edit.setText(left_path)
        self.right_edit.setText(right_path)

    def _choose_path(self, side: str) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目录")
        if path:
            self._set_path(side, path)

    def _set_path(self, side: str, path: str) -> None:
        if side == "left":
            self.left_path = path
            self.left_edit.setText(path)
        else:
            self.right_path = path
            self.right_edit.setText(path)
        self.path_changed.emit(self.left_path, self.right_path)
