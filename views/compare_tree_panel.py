from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHeaderView, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QCheckBox,
    QGridLayout, QTreeView, QVBoxLayout, QWidget, QProgressBar,
)

from models.tree_node import TreeNode

STATUS_COLORS = {
    "same": QColor("#4caf50"),
    "different": QColor("#ff6b5e"),
    "only_left": QColor("#5b9bd5"),
    "only_right": QColor("#b985d9"),
    "unknown": QColor("#96A1AD"),
}

STATUS_BACKGROUNDS_LEFT = {
    "same": QColor("#1e2a1e"),
    "different": QColor("#3a2420"),
    "only_left": QColor("#1f2d3a"),
    "only_right": QColor("#2a2138"),
    "unknown": QColor("#23262a"),
}

STATUS_BACKGROUNDS_RIGHT = {
    "same": QColor("#1e2a1e"),
    "different": QColor("#1f2a3a"),
    "only_left": QColor("#1a2735"),
    "only_right": QColor("#241a30"),
    "unknown": QColor("#23262a"),
}

STATUS_LABELS = {
    "same": "一致",
    "different": "不同",
    "only_left": "仅左侧",
    "only_right": "仅右侧",
    "unknown": "未知",
}


class DropPathLineEdit(QLineEdit):
    path_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if not urls:
            return
        local = urls[0].toLocalFile()
        if local:
            self.path_dropped.emit(local)


class DropTreeView(QTreeView):
    folder_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if not urls:
            super().dropEvent(event)
            return
        local = urls[0].toLocalFile()
        if not local:
            return
        if not Path(local).is_dir():
            return
        self.folder_dropped.emit(local)
        event.acceptProposedAction()


class CompareTreePanel(QWidget):
    path_changed = Signal(str, str)
    node_selected = Signal(str, str)
    node_expanded = Signal(str, str)
    folder_dropped = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.left_tree = self._create_side("新文件夹列表", "left")
        self.right_tree = self._create_side("SVN文件夹列表", "right")
        layout.addWidget(self.left_tree["container"])
        layout.addWidget(self.right_tree["container"])

        self.left_tree["view"].expanded.connect(lambda idx: self._emit_expand("left", idx))
        self.right_tree["view"].expanded.connect(lambda idx: self._emit_expand("right", idx))
        self.left_tree["view"].selectionModel().selectionChanged.connect(lambda *_: self._emit_selection("left"))
        self.right_tree["view"].selectionModel().selectionChanged.connect(lambda *_: self._emit_selection("right"))

    # ── 构建单侧: 路径选择 + 树 ────────────────────────────
    def _create_side(self, title: str, side: str) -> dict:
        container = QWidget()
        col_layout = QVBoxLayout(container)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(4)

        # 路径行
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_row.addWidget(QLabel(f"{title[:2]}:"))

        edit = DropPathLineEdit()
        path_row.addWidget(edit)

        btn = QPushButton("选择")
        btn.setFixedWidth(44)
        path_row.addWidget(btn)
        col_layout.addLayout(path_row)

        # 标题 + 树
        title_label = QLabel(title)
        title_label.setProperty("sectionTitle", True)
        col_layout.addWidget(title_label)

        view = DropTreeView()
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(["名称", "大小(MB)", "状态"])
        view.setModel(model)
        view.setRootIsDecorated(True)
        view.setUniformRowHeights(True)
        view.setItemsExpandable(True)
        view.setAllColumnsShowFocus(True)
        view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        view.setSelectionBehavior(QAbstractItemView.SelectRows)
        view.setAlternatingRowColors(True)
        view.setIndentation(18)

        header = view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        view.setColumnWidth(1, 84)
        view.setColumnWidth(2, 96)

        col_layout.addWidget(view)

        # 事件
        view.folder_dropped.connect(lambda p: self.folder_dropped.emit(side, p))
        edit.path_dropped.connect(lambda p: self._set_path(side, p))
        btn.clicked.connect(lambda: self._choose_path(side))

        return {"container": container, "view": view, "model": model, "side": side, "edit": edit}

    # ── 路径操作 ────────────────────────────────────────────
    def set_paths(self, left: str, right: str) -> None:
        self.left_tree["edit"].setText(left)
        self.right_tree["edit"].setText(right)
        self.path_changed.emit(left, right)

    def get_paths(self) -> tuple[str, str]:
        return self.left_tree["edit"].text(), self.right_tree["edit"].text()

    def _set_path(self, side: str, path: str) -> None:
        edit = self.left_tree["edit"] if side == "left" else self.right_tree["edit"]
        edit.setText(path)
        l, r = self.get_paths()
        self.path_changed.emit(l, r)

    def _choose_path(self, side: str) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择目录")
        if p:
            self._set_path(side, p)

    # ── 树面板操作 ──────────────────────────────────────────
    def populate(self, left_root: TreeNode, right_root: TreeNode,
                 diff_only: bool, active_actions: list[str] | None = None) -> None:
        self._populate_model(self.left_tree["model"], self.left_tree["view"],
                             left_root, diff_only, "left", active_actions)
        self._populate_model(self.right_tree["model"], self.right_tree["view"],
                             right_root, diff_only, "right", active_actions)

    def expand_all(self) -> None:
        self.left_tree["view"].expandAll()
        self.right_tree["view"].expandAll()

    def collapse_all(self) -> None:
        self.left_tree["view"].collapseAll()
        self.right_tree["view"].collapseAll()
        self.left_tree["view"].expandToDepth(0)
        self.right_tree["view"].expandToDepth(0)

    def clear_all(self) -> None:
        self.left_tree["model"].removeRows(0, self.left_tree["model"].rowCount())
        self.right_tree["model"].removeRows(0, self.right_tree["model"].rowCount())
        self.left_tree["edit"].clear()
        self.right_tree["edit"].clear()

    # ─── internal ───────────────────────────────────────────
    def _populate_model(self, model, view, root, diff_only, side, active_actions=None):
        model.removeRows(0, model.rowCount())
        root_row = self._build_item(root, diff_only, side, active_actions)
        if root_row:
            model.appendRow(root_row)
        view.expandToDepth(0)

    def _build_item(self, node, diff_only, side, active_actions=None):
        if active_actions is not None and node.relative_path and "/" in node.relative_path:
            parts = node.relative_path.split("/")
            if len(parts) >= 2 and parts[1]:
                if parts[1].lower() not in [a.lower() for a in active_actions]:
                    return None
        child_rows = []
        for child in node.children:
            row = self._build_item(child, diff_only, side, active_actions)
            if row:
                child_rows.append(row)
        visible = (not diff_only) or node.compare_status != "same" or bool(child_rows) or node.relative_path == ""
        if not visible:
            return None
        item = QStandardItem(node.name)
        item.setData(node.relative_path, Qt.UserRole)
        item.setData(node.source_type, Qt.UserRole + 1)
        item.setData(node.compare_status, Qt.UserRole + 2)
        size_item = QStandardItem(self._build_size_text(node))
        status_item = QStandardItem(STATUS_LABELS.get(node.compare_status, node.compare_status))
        color = STATUS_COLORS.get(node.compare_status, STATUS_COLORS["unknown"])
        bg = (STATUS_BACKGROUNDS_LEFT if side == "left" else STATUS_BACKGROUNDS_RIGHT).get(node.compare_status, STATUS_BACKGROUNDS_LEFT["unknown"])
        for ci in [item, size_item, status_item]:
            ci.setForeground(color)
            ci.setBackground(bg)
            ci.setEditable(False)
        for row in child_rows:
            item.appendRow(row)
        return [item, size_item, status_item]

    @staticmethod
    def _build_size_text(node):
        if node.file_size_bytes <= 0:
            return ""
        return f"{node.file_size_bytes / (1024 * 1024):.2f}"

    def _emit_selection(self, side):
        bundle = self.left_tree if side == "left" else self.right_tree
        idx = bundle["view"].currentIndex()
        if not idx.isValid():
            return
        it = bundle["model"].itemFromIndex(idx.siblingAtColumn(0))
        rp = it.data(Qt.UserRole)
        if rp is not None:
            self.node_selected.emit(side, rp)

    def _emit_expand(self, side, index):
        bundle = self.left_tree if side == "left" else self.right_tree
        it = bundle["model"].itemFromIndex(index.siblingAtColumn(0))
        rp = it.data(Qt.UserRole)
        if rp is not None:
            self.node_expanded.emit(side, rp)
