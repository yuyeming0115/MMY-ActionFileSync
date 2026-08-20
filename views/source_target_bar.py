from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class DropPathEdit(QLineEdit):
    path_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setAcceptDrops(True)
        self.setPlaceholderText("拖入目录或点击选择")

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.path_dropped.emit(path)


class PathRoleField(QFrame):
    path_changed = Signal(str)

    def __init__(self, title: str, role_text: str, role: str) -> None:
        super().__init__()
        self.setProperty("pathRole", role)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 9)
        layout.setSpacing(4)

        heading = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setProperty("pathTitle", True)
        role_label = QLabel(role_text)
        role_label.setProperty("pathHint", True)
        heading.addWidget(title_label)
        heading.addStretch(1)
        heading.addWidget(role_label)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self.edit = DropPathEdit()
        self.button = QToolButton()
        self.button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.button.setToolTip("选择目录")
        self.button.setAccessibleName("选择目录")
        self.recent_button = QToolButton()
        self.recent_button.setText("▼")
        self.recent_button.setToolTip("最近目录")
        self.recent_button.setAccessibleName("最近目录")
        path_row.addWidget(self.edit, 1)
        path_row.addWidget(self.button)
        path_row.addWidget(self.recent_button)

        layout.addLayout(heading)
        layout.addLayout(path_row)

        self._recent_paths: list[str] = []
        self.edit.path_dropped.connect(self._set_path)
        self.button.clicked.connect(self._choose_path)
        self.recent_button.clicked.connect(self._show_recent_menu)

    def set_recent_paths(self, paths) -> None:
        self._recent_paths = list(paths or [])

    def _show_recent_menu(self) -> None:
        if not self._recent_paths:
            return
        menu = QMenu(self.recent_button)
        for path in self._recent_paths:
            menu.addAction(path, lambda checked=False, p=path: self._set_path(p))
        menu.exec(self.recent_button.mapToGlobal(self.recent_button.rect().bottomLeft()))

    def path(self) -> str:
        return self.edit.text()

    def set_path(self, path: str) -> None:
        self.edit.setText(path)

    def _choose_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目录", self.path())
        if path:
            self._set_path(path)

    def _set_path(self, path: str) -> None:
        self.set_path(path)
        self.path_changed.emit(path)


class SourceTargetBar(QWidget):
    path_changed = Signal(str, str)
    refresh_requested = Signal()
    clear_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        title = QLabel("MMY Action File Sync")
        title.setProperty("appTitle", True)
        self.status_label = QLabel("请选择来源和目标目录")
        self.status_label.setProperty("scanStatus", "idle")
        self.refresh_button = QPushButton("刷新对比")
        self.clear_button = QPushButton("清空")
        toolbar.addWidget(title)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.status_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.clear_button)

        path_row = QHBoxLayout()
        path_row.setSpacing(12)
        self.source_field = PathRoleField("来源｜新动作目录", "从这里读取", "source")
        direction = QWidget()
        direction_layout = QVBoxLayout(direction)
        direction_layout.setContentsMargins(4, 0, 4, 0)
        direction_layout.setSpacing(0)
        arrow = QLabel("→")
        arrow.setProperty("directionArrow", True)
        arrow.setAlignment(Qt.AlignCenter)
        copy_label = QLabel("复制到")
        copy_label.setProperty("directionLabel", True)
        copy_label.setAlignment(Qt.AlignCenter)
        direction_layout.addStretch(1)
        direction_layout.addWidget(arrow)
        direction_layout.addWidget(copy_label)
        direction_layout.addStretch(1)
        self.target_field = PathRoleField("目标｜SVN 工作目录", "将写入/覆盖", "target")
        path_row.addWidget(self.source_field, 1)
        path_row.addWidget(direction)
        path_row.addWidget(self.target_field, 1)

        layout.addLayout(toolbar)
        layout.addLayout(path_row)

        self.source_field.path_changed.connect(lambda _: self._emit_paths())
        self.target_field.path_changed.connect(lambda _: self._emit_paths())
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.clear_button.clicked.connect(self.clear_requested.emit)

    def set_paths(self, source: str, target: str) -> None:
        self.source_field.set_path(source)
        self.target_field.set_path(target)

    def set_recent_paths(self, source_list, target_list) -> None:
        self.source_field.set_recent_paths(source_list)
        self.target_field.set_recent_paths(target_list)

    def paths(self) -> tuple[str, str]:
        return self.source_field.path(), self.target_field.path()

    def set_scan_status(self, text: str, state: str = "idle") -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("scanStatus", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def set_busy(self, busy: bool) -> None:
        self.source_field.setEnabled(not busy)
        self.target_field.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy and all(self.paths()))
        self.clear_button.setEnabled(not busy)

    def _emit_paths(self) -> None:
        self.path_changed.emit(*self.paths())
