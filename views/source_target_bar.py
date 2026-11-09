from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils.path_matcher import normalize_path
from utils.pinned_paths import contains_pinned_path, format_pinned_labels
from views.flow_layout import ButtonRowArea


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
            dropped = Path(path) if path else None
            # 拖入文件时取其所在目录；忽略不存在的路径
            if dropped is not None and dropped.is_file():
                dropped = dropped.parent
            if dropped is not None and dropped.is_dir():
                self.path_dropped.emit(str(dropped))


class PathRoleField(QFrame):
    path_changed = Signal(str)
    pin_clicked = Signal()

    def __init__(self, title: str, role_text: str, role: str, *, enable_pin: bool = False) -> None:
        super().__init__()
        self.setProperty("pathRole", role)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 7)
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
        self.pin_button: QToolButton | None = None
        if enable_pin:
            self.pin_button = QToolButton()
            self.pin_button.setText("📌")
            self.pin_button.setCheckable(True)
            self.pin_button.setProperty("pinToggle", True)
            self.pin_button.setEnabled(False)
            self.pin_button.setToolTip("请先选择右侧目录，再固定到常用")
            self.pin_button.setAccessibleName("固定当前右侧目录")
            self.pin_button.clicked.connect(self.pin_clicked.emit)
        self.recent_button = QToolButton()
        self.recent_button.setText("▼")
        self.recent_button.setToolTip("最近目录")
        self.recent_button.setAccessibleName("最近目录")
        path_row.addWidget(self.edit, 1)
        path_row.addWidget(self.button)
        if self.pin_button is not None:
            path_row.addWidget(self.pin_button)
        path_row.addWidget(self.recent_button)

        layout.addLayout(heading)
        layout.addLayout(path_row)

        self._recent_paths: list[str] = []
        self.edit.path_dropped.connect(self._set_path)
        self.button.clicked.connect(self._choose_path)
        self.recent_button.clicked.connect(self._show_recent_menu)

    def set_recent_paths(self, paths) -> None:
        self._recent_paths = list(paths or [])

    def set_pin_state(self, has_path: bool, pinned: bool) -> None:
        if self.pin_button is None:
            return
        self.pin_button.setEnabled(has_path)
        self.pin_button.setChecked(has_path and pinned)
        if not has_path:
            self.pin_button.setToolTip("请先选择右侧目录，再固定到常用")
        elif pinned:
            self.pin_button.setToolTip("已固定到右侧常用目录（点击取消固定）")
        else:
            self.pin_button.setToolTip("钉住当前目录到右侧常用")

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


class PinnedTargetBar(QFrame):
    """右侧常用目录钉固快捷栏：一键切换右侧目标目录，右键可取消固定或排序。"""

    path_selected = Signal(str)
    unpin_requested = Signal(str)
    add_requested = Signal()
    move_requested = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("pinnedBar", True)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._paths: list[str] = []
        self._active_path = ""
        self._buttons: list[tuple[str, QPushButton]] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(8)

        self.title_label = QLabel("右侧常用📌")
        self.title_label.setProperty("pinnedBarTitle", True)
        self.title_label.setToolTip("点击常用目录可一键切换右侧目标；右键可取消固定或调整顺序")
        self.title_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.flow_area = ButtonRowArea("右侧常用目录", max_lines=2, spacing=6, min_line_padding=4)
        self.flow_area.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        self.add_button = QPushButton("+", self.flow_area._row)
        self.add_button.setProperty("pinnedAddButton", True)
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.setToolTip("选择并固定新的右侧常用目录")
        self.add_button.setAccessibleName("添加右侧常用目录")
        self.add_button.clicked.connect(self.add_requested.emit)

        layout.addWidget(self.title_label, 0, Qt.AlignVCenter)
        layout.addWidget(self.flow_area, 1)

        self.set_paths([])

    def buttons(self) -> list[QPushButton]:
        return [button for _, button in self._buttons]

    def set_paths(self, paths: list[str], active_path: str = "") -> None:
        self._paths = list(paths or [])
        self._active_path = active_path
        flow = self.flow_area.flow()
        while flow.count():
            item = flow.takeAt(0)
            widget = item.widget()
            if widget is None or widget is self.add_button:
                continue
            widget.setParent(None)
            widget.deleteLater()

        self._buttons.clear()
        labels = format_pinned_labels(self._paths)
        for index, (path, label) in enumerate(zip(self._paths, labels)):
            button = QPushButton(label, self.flow_area._row)
            button.setProperty("pinnedDirButton", True)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"{path}\n点击一键切换右侧目录 · 右键可取消固定或调整顺序")
            button.setAccessibleName(f"右侧常用目录 {label}")
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.clicked.connect(lambda checked=False, p=path: self._on_chip_clicked(p))
            button.customContextMenuRequested.connect(
                lambda pos, b=button, p=path, i=index: self._show_context_menu(b, pos, p, i)
            )
            flow.addWidget(button)
            button.ensurePolished()
            button.setHidden(False)
            self._buttons.append((path, button))

        flow.addWidget(self.add_button)
        self.add_button.ensurePolished()
        self.add_button.setHidden(False)
        if not self._paths:
            hint = QLabel("点击上方 📌 或 + 固定常用目录", self.flow_area._row)
            hint.setProperty("pinnedEmptyHint", True)
            hint.setMinimumHeight(max(20, self.add_button.sizeHint().height()))
            flow.addWidget(hint)
            hint.ensurePolished()
            hint.setHidden(False)

        self.set_active_path(active_path)
        self.flow_area.sync_height()

    def set_active_path(self, active_path: str) -> None:
        self._active_path = active_path
        active_key = normalize_path(active_path.strip()).casefold() if active_path else ""
        for path, button in self._buttons:
            button.setChecked(bool(active_key) and normalize_path(path).casefold() == active_key)

    def _on_chip_clicked(self, path: str) -> None:
        # 点击已激活按钮时 Qt 会先翻转 checked 态，这里先回正，避免视觉闪烁失真
        self.set_active_path(self._active_path)
        self.path_selected.emit(path)

    def _show_context_menu(self, button: QPushButton, pos, path: str, index: int) -> None:
        menu = QMenu(self)
        menu.addAction("切换到此目录", lambda checked=False, p=path: self._on_chip_clicked(p))
        menu.addAction("取消固定", lambda checked=False, p=path: self.unpin_requested.emit(p))
        menu.addSeparator()
        move_left = menu.addAction("左移", lambda checked=False, p=path: self.move_requested.emit(p, -1))
        move_left.setEnabled(index > 0)
        move_right = menu.addAction("右移", lambda checked=False, p=path: self.move_requested.emit(p, 1))
        move_right.setEnabled(index < len(self._paths) - 1)
        menu.addSeparator()
        menu.addAction("在文件管理器中打开", lambda checked=False, p=path: self._open_in_explorer(p))
        menu.addAction("复制路径", lambda checked=False, p=path: QApplication.clipboard().setText(p))
        try:
            menu.exec(button.mapToGlobal(pos))
        finally:
            menu.deleteLater()

    def _open_in_explorer(self, path: str) -> None:
        if Path(path).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        QMessageBox.warning(self, "目录不存在", f"目录不存在或暂不可访问：\n{path}")


class SourceTargetBar(QWidget):
    path_changed = Signal(str, str)
    refresh_requested = Signal()
    cancel_requested = Signal()
    clear_requested = Signal()
    redundancy_scan_requested = Signal()
    pinned_target_selected = Signal(str)
    pin_current_target_requested = Signal()
    add_pinned_target_requested = Signal()
    unpin_target_requested = Signal(str)
    move_pinned_target_requested = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._pinned_targets: list[str] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        toolbar = QHBoxLayout()
        title = QLabel("MMY Action File Sync")
        title.setProperty("appTitle", True)
        self.status_label = QLabel("请选择来源和目标目录")
        self.status_label.setProperty("scanStatus", "idle")
        self.refresh_button = QPushButton("刷新对比")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setVisible(False)
        self.redundancy_button = QPushButton("冗余帧扫描")
        self.redundancy_button.setToolTip("扫描目录里多余方向的冗余动作帧，确认后整体移动到备份目录")
        self.redundancy_button.setAccessibleName("冗余帧扫描")
        self.clear_button = QPushButton("清空")
        toolbar.addWidget(title)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.status_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.cancel_button)
        toolbar.addWidget(self.redundancy_button)
        toolbar.addWidget(self.clear_button)

        path_grid = QGridLayout()
        path_grid.setContentsMargins(0, 0, 0, 0)
        path_grid.setHorizontalSpacing(12)
        path_grid.setVerticalSpacing(4)
        path_grid.setColumnStretch(0, 1)
        path_grid.setColumnStretch(1, 0)
        path_grid.setColumnStretch(2, 1)

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
        self.target_field = PathRoleField("目标｜SVN 工作目录", "将写入/覆盖", "target", enable_pin=True)
        self.pinned_target_bar = PinnedTargetBar()

        path_grid.addWidget(self.source_field, 0, 0)
        path_grid.addWidget(direction, 0, 1)
        path_grid.addWidget(self.target_field, 0, 2)
        path_grid.addWidget(self.pinned_target_bar, 1, 2)

        layout.addLayout(toolbar)
        layout.addLayout(path_grid)

        self.source_field.path_changed.connect(lambda _: self._emit_paths())
        self.target_field.path_changed.connect(lambda _: self._emit_paths())
        self.target_field.pin_clicked.connect(self._on_pin_clicked)
        self.target_field.edit.textChanged.connect(lambda _: self.sync_pinned_state())
        self.pinned_target_bar.path_selected.connect(self.pinned_target_selected.emit)
        self.pinned_target_bar.add_requested.connect(self.add_pinned_target_requested.emit)
        self.pinned_target_bar.unpin_requested.connect(self.unpin_target_requested.emit)
        self.pinned_target_bar.move_requested.connect(self.move_pinned_target_requested.emit)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        self.redundancy_button.clicked.connect(self.redundancy_scan_requested.emit)

    def set_paths(self, source: str, target: str) -> None:
        self.source_field.set_path(source)
        self.target_field.set_path(target)
        self.sync_pinned_state()

    def set_recent_paths(self, source_list, target_list) -> None:
        self.source_field.set_recent_paths(source_list)
        self.target_field.set_recent_paths(target_list)

    def set_pinned_targets(self, paths: list[str]) -> None:
        self._pinned_targets = list(paths or [])
        self.pinned_target_bar.set_paths(self._pinned_targets, self.target_field.path())
        self.sync_pinned_state()

    def sync_pinned_state(self) -> None:
        current = self.target_field.path().strip()
        is_pinned = contains_pinned_path(self._pinned_targets, current)
        self.target_field.set_pin_state(bool(current), is_pinned)
        self.pinned_target_bar.set_active_path(current)

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
        self.pinned_target_bar.setEnabled(not busy)
        self.refresh_button.setVisible(not busy)
        self.cancel_button.setVisible(busy)
        self.clear_button.setEnabled(not busy)
        self.redundancy_button.setEnabled(not busy)

    def _on_pin_clicked(self) -> None:
        self.sync_pinned_state()
        self.pin_current_target_requested.emit()

    def _emit_paths(self) -> None:
        self.path_changed.emit(*self.paths())
