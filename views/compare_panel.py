from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHeaderView, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from models.tree_node import TreeNode

# ── 常量 ─────────────────────────────────────────────────────

STATUS_LABELS = {
    "same": "一致", "different": "不同",
    "only_left": "仅左侧", "only_right": "仅右侧", "unknown": "未知",
}


# ── DropLineEdit ─────────────────────────────────────────────

class DropPathEdit(QLineEdit):
    path_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        p = urls[0].toLocalFile()
        if p:
            self.path_dropped.emit(p)


# ── DropTreeView ─────────────────────────────────────────────

class DropTreeView(QTreeView):
    folder_dropped = Signal(str)
    node_expanded = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            super().dropEvent(event)
            return
        p = urls[0].toLocalFile()
        if not p or not Path(p).is_dir():
            return
        self.folder_dropped.emit(p)
        event.acceptProposedAction()


# ── ComparePanel (整合: 路径选器 + 左右树) ────────────────

class ComparePanel(QWidget):
    path_changed = Signal(str, str)
    node_selected = Signal(str, str)
    node_expanded = Signal(str, str)
    folder_dropped = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        self.left_side = self._build_side("新文件夹列表", "left")
        self.right_side = self._build_side("SVN文件夹列表", "right")
        main_layout.addWidget(self.left_side["container"], 1)
        main_layout.addWidget(self.right_side["container"], 1)

    # ---- 构建单侧 ----
    def _build_side(self, title: str, side: str) -> dict:
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        # 路径行
        pr = QHBoxLayout()
        pr.setSpacing(6)
        pr.addWidget(QLabel(f"{title[:2]}:"))
        edit = DropPathEdit()
        pr.addWidget(edit)
        btn = QPushButton("选择")
        btn.setFixedWidth(44)
        pr.addWidget(btn)
        col.addLayout(pr)

        # 标题 + 树
        tl = QLabel(title)
        tl.setProperty("sectionTitle", True)
        col.addWidget(tl)

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
        hdr = view.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        view.setColumnWidth(1, 84)
        view.setColumnWidth(2, 96)
        col.addWidget(view)

        # 事件
        view.folder_dropped.connect(lambda p: self.folder_dropped.emit(side, p))
        view.expanded.connect(lambda idx: self._emit_expand(side, idx))
        view.selectionModel().selectionChanged.connect(lambda *_: self._emit_selection(side))
        edit.path_dropped.connect(lambda p: self._set_path(side, p))
        btn.clicked.connect(lambda: self._choose_path(side))

        return {"container": container, "view": view, "model": model, "side": side, "edit": edit}

    # ---- 路径操作 ----
    def set_paths(self, left: str, right: str) -> None:
        self.left_side["edit"].setText(left)
        self.right_side["edit"].setText(right)

    def get_paths(self) -> tuple[str, str]:
        return self.left_side["edit"].text(), self.right_side["edit"].text()

    def _set_path(self, side: str, path: str) -> None:
        e = self.left_side["edit"] if side == "left" else self.right_side["edit"]
        e.setText(path)
        l, r = self.get_paths()
        self.path_changed.emit(l, r)

    def _choose_path(self, side: str) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择目录")
        if p:
            self._set_path(side, p)

    # ---- 树面板 API ----
    def populate(self, left_root: TreeNode, right_root: TreeNode,
                 diff_only: bool, active_actions: list[str] | None = None) -> None:
        self._populate(self.left_side["model"], self.left_side["view"],
                       left_root, diff_only, "left", active_actions)
        self._populate(self.right_side["model"], self.right_side["view"],
                       right_root, diff_only, "right", active_actions)

    def expand_all(self) -> None:
        self.left_side["view"].expandAll()
        self.right_side["view"].expandAll()

    def collapse_all(self) -> None:
        self.left_side["view"].collapseAll()
        self.right_side["view"].collapseAll()
        self.left_side["view"].expandToDepth(0)
        self.right_side["view"].expandToDepth(0)

    def clear_all(self) -> None:
        self.left_side["model"].removeRows(0, self.left_side["model"].rowCount())
        self.right_side["model"].removeRows(0, self.right_side["model"].rowCount())
        self.left_side["edit"].clear()
        self.right_side["edit"].clear()

    # ── 内部 ──
    def _populate(self, model, view, root, diff_only, side, active_actions):
        model.removeRows(0, model.rowCount())
        row = self._build_item(root, diff_only, side, active_actions)
        if row:
            model.appendRow(row)
        view.expandToDepth(0)

    def _build_item(self, node, diff_only, side, active_actions):
        if active_actions is not None and node.relative_path and "/" in node.relative_path:
            parts = node.relative_path.split("/")
            if len(parts) >= 2 and parts[1]:
                if parts[1].lower() not in [a.lower() for a in active_actions]:
                    return None
        child_rows = []
        for ch in node.children:
            row = self._build_item(ch, diff_only, side, active_actions)
            if row:
                child_rows.append(row)
        visible = (not diff_only) or node.compare_status != "same" or bool(child_rows) or not node.relative_path
        if not visible:
            return None

        item = QStandardItem(node.name)
        item.setData(node.relative_path, Qt.UserRole)
        item.setData(node.source_type, Qt.UserRole + 1)
        item.setData(node.compare_status, Qt.UserRole + 2)

        size_text = f"{node.file_size_bytes / (1024 * 1024):.2f}" if node.file_size_bytes > 0 else ""
        size_item = QStandardItem(size_text)
        label = STATUS_LABELS.get(node.compare_status, node.compare_status)
        status_item = QStandardItem(label)

        bg = "#f0ece6"  # default
        if node.compare_status == "same":
            bg = "#f7f4ef"
        elif node.compare_status == "different":
            bg = "#f7ddd7" if side == "left" else "#dce7f6"
        elif node.compare_status == "only_left":
            bg = "#d9ebff" if side == "left" else "#e4f0fc"
        elif node.compare_status == "only_right":
            bg = "#eee7f9" if side == "left" else "#f2dbff"

        for ci in [item, size_item, status_item]:
            ci.setBackground(bg)
            ci.setEditable(False)

        for row in child_rows:
            item.appendRow(row)

        return [item, size_item, status_item]

    def _emit_selection(self, side: str) -> None:
        b = self.left_side if side == "left" else self.right_side
        idx = b["view"].currentIndex()
        if not idx.isValid():
            return
        it = b["model"].itemFromIndex(idx.siblingAtColumn(0))
        rp = it.data(Qt.UserRole)
        if rp is not None:
            self.node_selected.emit(side, rp)

    def _emit_expand(self, side: str, index) -> None:
        b = self.left_side if side == "left" else self.right_side
        it = b["model"].itemFromIndex(index.siblingAtColumn(0))
        rp = it.data(Qt.UserRole)
        if rp is not None:
            self.node_expanded.emit(side, rp)
