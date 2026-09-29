from __future__ import annotations

from pathlib import PurePosixPath

from PySide6.QtCore import QPoint, QRect, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QLayout,
    QLayoutItem,
    QPushButton,
    QScrollArea,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from models.action_diff import ActionDiffItem, FileDiffItem


ROLE_KIND = Qt.UserRole + 1
ROLE_OBJECT = Qt.UserRole + 2
ROLE_STATUS = Qt.UserRole + 3
ROLE_SEARCH = Qt.UserRole + 4
ROLE_TRANSFERABLE = Qt.UserRole + 5

STATUS_LABELS = {
    "only_left": "新增待传",
    "different": "内容变更",
    "same": "已一致",
    "only_right": "目标独有",
    "unknown": "无法判断",
}

STATUS_FOREGROUND = {
    "only_left": QColor("#4caf50"),
    "different": QColor("#e0a040"),
    "same": QColor("#4caf50"),
    "only_right": QColor("#b985d9"),
    "unknown": QColor("#96A1AD"),
}

ACTION_HIGHLIGHT_STATUSES = ("only_left", "different")


class ActionFilterProxyModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.status_filter = "transfer"
        self.search_text = ""
        self.setRecursiveFilteringEnabled(True)

    def set_status_filter(self, value: str) -> None:
        self.status_filter = value
        self.refresh_filter()

    def set_search_text(self, value: str) -> None:
        self.search_text = value.casefold().strip()
        self.refresh_filter()

    def refresh_filter(self) -> None:
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:  # type: ignore[override]
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        if source_parent.isValid():
            # 子文件行继承父动作的过滤条件；占位行不能无条件放行，
            # 否则递归过滤会用它“救回”被状态过滤隐藏的父行（过滤失效）。
            parent = source_parent.siblingAtColumn(0)
            status = parent.data(ROLE_STATUS)
            searchable = str(parent.data(ROLE_SEARCH) or "").casefold()
            transferable = bool(parent.data(ROLE_TRANSFERABLE))
        else:
            status = index.data(ROLE_STATUS)
            searchable = str(index.data(ROLE_SEARCH) or "").casefold()
            transferable = bool(index.data(ROLE_TRANSFERABLE))
        if self.search_text and self.search_text not in searchable:
            return False
        if self.status_filter == "all":
            return True
        if self.status_filter == "transfer":
            return transferable and status in {"only_left", "different"}
        return status == self.status_filter


class FlowLayout(QLayout):
    """按容器宽度自动换行的流式布局；行高随内容增长，不出现横向滚动条。"""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []

    def addItem(self, item: QLayoutItem) -> None:  # type: ignore[override]
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:  # type: ignore[override]
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # type: ignore[override]
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        spacing = self.spacing()
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y = y + line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class ButtonRowArea(QScrollArea):
    """按宽度换行的快捷按钮行：高度贴合内容，最多显示两行，超出才走纵向滚动。

    横向滚动条永远不出现（用户要求按钮自适应适配宽度）；行高随内容收缩，
    避免大量动作时按钮行把清单树挤没。
    """

    MAX_LINES = 2

    def __init__(self, accessible_name: str) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setAccessibleName(accessible_name)
        self._row = QWidget()
        self._row.setStyleSheet("background:transparent;")
        self._flow = FlowLayout(self._row, spacing=6)
        self.setWidget(self._row)
        self.sync_height()

    def flow(self) -> FlowLayout:
        return self._flow

    def sync_height(self) -> None:
        """按当前内容与可视宽度调整行高，在增删按钮和宽度变化后调用。"""
        line = self._line_height()
        cap = line * self.MAX_LINES + self._flow.spacing() * (self.MAX_LINES - 1)
        content = self._flow.heightForWidth(max(1, self.viewport().width()))
        self.setFixedHeight(max(line, min(content, cap)))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.sync_height()

    def _line_height(self) -> int:
        item = self._flow.itemAt(0)
        hint = item.sizeHint().height() if item is not None else 0
        return max(hint, self.fontMetrics().height() + 10)


class ActionDiffPanel(QWidget):
    action_selected = Signal(str)
    selection_changed = Signal(object)
    jump_filter_relaxed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.actions: list[ActionDiffItem] = []
        self.selected_paths: set[str] = set()
        self._updating_checks = False
        self.filter_buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title = QLabel("动作差异清单")
        title.setProperty("sectionTitle", True)
        self.visible_label = QLabel("尚未扫描")
        self.visible_label.setProperty("secondaryText", True)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.visible_label)

        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(3)
        for label, value in [
            ("待更新", "transfer"),
            ("新增", "only_left"),
            ("内容变更", "different"),
            ("已一致", "same"),
            ("全部", "all"),
        ]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setProperty("filterValue", value)
            button.setProperty("baseLabel", label)
            if value == "transfer":
                button.setChecked(True)
            self.filter_group.addButton(button)
            self.filter_buttons[value] = button
            filter_row.addWidget(button)
        filter_row.addStretch(1)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索动作或相对路径")
        self.select_visible_button = QPushButton("全选当前结果")
        self.select_changed_button = QPushButton("仅勾选有变更")
        self.select_changed_button.setToolTip("只勾选所有有变更动作的文件，替换当前选择")
        self.clear_selection_button = QPushButton("清空选择")
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.select_visible_button)
        search_row.addWidget(self.select_changed_button)
        search_row.addWidget(self.clear_selection_button)

        self.direction_buttons_row, self.direction_buttons_layout = self._make_button_row("方向快捷选择")
        self.direction_buttons_row.hide()
        self.action_buttons_row, self.action_buttons_layout = self._make_button_row("动作快捷选择")

        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(["选择", "方向", "目录", "动作", "状态", "变化", "大小"])
        self.proxy = ActionFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.view = QTreeView()
        self.view.setModel(self.proxy)
        self.view.setRootIsDecorated(True)
        self.view.setUniformRowHeights(True)
        self.view.setAlternatingRowColors(True)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setToolTip("单击行切换预览；按空格切换勾选；Ctrl/Shift 多选后批量勾选")
        self.view.setIndentation(16)
        self.view.setExpandsOnDoubleClick(False)
        header = self.view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.view.setColumnWidth(2, 80)

        layout.addLayout(title_row)
        layout.addLayout(filter_row)
        layout.addLayout(search_row)
        layout.addWidget(self.direction_buttons_row)
        layout.addWidget(self.action_buttons_row)
        layout.addWidget(self.view, 1)

        self.filter_group.buttonClicked.connect(self._on_filter_changed)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.select_visible_button.clicked.connect(self.select_visible)
        self.select_changed_button.clicked.connect(self.select_changed)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.model.itemChanged.connect(self._on_item_changed)
        self.view.expanded.connect(self._on_expanded)
        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        self.view.clicked.connect(self._on_clicked)
        self.toggle_selection_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self.view)
        self.toggle_selection_shortcut.setContext(Qt.WidgetShortcut)
        self.toggle_selection_shortcut.activated.connect(self.toggle_highlighted)

    def populate(self, actions: list[ActionDiffItem], selected_paths: set[str] | None = None) -> None:
        self.actions = actions
        eligible = {
            item.relative_path
            for action in actions
            for item in action.transferable_files
        }
        self.selected_paths = set(selected_paths or set()) & eligible
        self._updating_checks = True
        try:
            self.model.removeRows(0, self.model.rowCount())
            for action in actions:
                self.model.appendRow(self._build_action_row(action))
        finally:
            self._updating_checks = False
        self.proxy.refresh_filter()
        self._update_filter_counts()
        self._update_visible_label()
        if self.proxy.rowCount() > 0:
            index = self.proxy.index(0, 0)
            self.view.setCurrentIndex(index)
            self._emit_action(index)
        self._rebuild_direction_buttons()
        self._rebuild_action_buttons()
        self._emit_selection()

    def reset(self) -> None:
        self.actions = []
        self.selected_paths.clear()
        self.model.removeRows(0, self.model.rowCount())
        self.search_edit.clear()
        self.visible_label.setText("尚未扫描")
        self._rebuild_direction_buttons()
        self._rebuild_action_buttons()
        self._emit_selection()

    def set_selected_paths(self, paths: set[str]) -> None:
        eligible = {
            item.relative_path
            for action in self.actions
            for item in action.transferable_files
        }
        self.selected_paths = set(paths) & eligible
        self._sync_all_checks()
        self._sync_direction_buttons()
        self._sync_action_buttons()
        self._emit_selection()

    def all_directions(self) -> set[str]:
        """清单中出现过的方向目录集合（大小写以目录为准）。"""
        return {direction for direction in (self._direction_of(action) for action in self.actions) if direction}

    def directions_for(self, action_name: str) -> dict[str, str]:
        """包含同名动作的方向映射：方向 -> 动作状态（动作名 casefold 匹配）。"""
        target = action_name.casefold()
        result: dict[str, str] = {}
        for action in self.actions:
            if action.action_name.casefold() == target:
                direction = self._direction_of(action)
                if direction:
                    result[direction] = action.status
        return result

    def jump_to_action(self, relative_path: str) -> bool:
        """把清单当前行定位到指定动作并触发预览联动。

        目标行被状态过滤/搜索隐藏时自动放宽（过滤切到「全部」、必要时清空搜索），
        放宽动作通过 jump_filter_relaxed 通知外部记日志。返回是否成功定位。
        """
        target = relative_path.casefold()
        row = next(
            (index for index, action in enumerate(self.actions) if action.relative_path.casefold() == target),
            None,
        )
        if row is None:
            return False
        source_index = self.model.index(row, 0)
        proxy_index = self.proxy.mapFromSource(source_index)
        relaxed = False
        if not proxy_index.isValid() and self.proxy.status_filter != "all":
            self._apply_status_filter("all")
            relaxed = True
            proxy_index = self.proxy.mapFromSource(source_index)
        if not proxy_index.isValid() and self.search_edit.text():
            self.search_edit.clear()
            relaxed = True
            proxy_index = self.proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            return False
        if relaxed:
            self.jump_filter_relaxed.emit(relative_path)
        self.view.scrollTo(proxy_index, QAbstractItemView.EnsureVisible)
        self.view.setCurrentIndex(proxy_index)
        return True

    def _apply_status_filter(self, value: str) -> None:
        """以编程方式切换状态过滤，并同步过滤按钮的选中态。"""
        button = self.filter_buttons.get(value)
        if button is not None:
            button.setChecked(True)
        self.proxy.set_status_filter(value)
        self._update_visible_label()

    @staticmethod
    def _make_button_row(accessible_name: str) -> tuple[ButtonRowArea, FlowLayout]:
        """按钮行容器：按钮按可用宽度自动换行，不出现横向滚动条。"""
        row = ButtonRowArea(accessible_name)
        return row, row.flow()

    @staticmethod
    def _direction_of(action: ActionDiffItem) -> str:
        parent = PurePosixPath(action.relative_path).parent.as_posix()
        return "" if parent == "." else parent

    def _direction_button_paths(self, direction: str) -> set[str]:
        """收集该方向（一级目录）下所有动作的可传输文件相对路径。"""
        paths: set[str] = set()
        for action in self.actions:
            if self._direction_of(action) == direction:
                paths.update(item.relative_path for item in action.transferable_files)
        return paths

    def _rebuild_direction_buttons(self) -> None:
        """根据当前动作清单重建方向快捷按钮（按自然顺序去重，无方向时隐藏整行）。"""
        layout = self.direction_buttons_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        directions = sorted(
            {direction for direction in (self._direction_of(action) for action in self.actions) if direction}
        )
        self.direction_buttons_row.setVisible(bool(directions))
        for direction in directions:
            button = QPushButton(direction)
            button.setCheckable(True)
            button.setProperty("directionButton", True)
            button.setToolTip(f"勾选 {direction} 下的所有动作")
            button.clicked.connect(
                lambda checked=False, d=direction: self._on_direction_button_toggled(d, checked)
            )
            layout.addWidget(button)
        self._sync_direction_buttons()
        self.direction_buttons_row.sync_height()

    def _sync_direction_buttons(self) -> None:
        """根据当前选中状态刷新各方向按钮的 checked 态。"""
        for index in range(self.direction_buttons_layout.count()):
            button = self.direction_buttons_layout.itemAt(index).widget()
            if not isinstance(button, QPushButton):
                continue
            paths = self._direction_button_paths(button.text())
            button.setChecked(bool(paths) and paths.issubset(self.selected_paths))

    def _on_direction_button_toggled(self, direction: str, checked: bool) -> None:
        """点击方向按钮：勾选/取消该方向下所有动作的可传输文件。"""
        paths = self._direction_button_paths(direction)
        if not paths:
            # 该方向没有可传输文件（如全部已一致）：勾选不生效，
            # 但 Qt 已翻转按钮视觉状态，需同步回真实选中状态（避免“空点亮起”）。
            self._sync_direction_buttons()
            return
        if checked:
            self.set_selected_paths(self.selected_paths | paths)
        else:
            self.set_selected_paths(self.selected_paths - paths)

    def _action_button_paths(self, name: str) -> set[str]:
        """收集所有同名动作的可传输文件相对路径。"""
        paths: set[str] = set()
        for action in self.actions:
            if action.action_name == name:
                paths.update(item.relative_path for item in action.transferable_files)
        return paths

    def _rebuild_action_buttons(self) -> None:
        """根据当前动作清单重建顶部动作快捷按钮（按首次出现顺序去重）。"""
        layout = self.action_buttons_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        seen: list[str] = []
        for action in self.actions:
            name = action.action_name
            if name and name not in seen:
                seen.append(name)
        for name in seen:
            button = QPushButton(name)
            button.setCheckable(True)
            button.setProperty("actionButton", True)
            button.setToolTip(f"勾选所有方向下的 {name} 动作")
            button.clicked.connect(
                lambda checked=False, n=name: self._on_action_button_toggled(n, checked)
            )
            layout.addWidget(button)
        self._sync_action_buttons()
        self.action_buttons_row.sync_height()

    def _sync_action_buttons(self) -> None:
        """根据当前选中状态刷新各动作按钮的 checked 态。"""
        for index in range(self.action_buttons_layout.count()):
            button = self.action_buttons_layout.itemAt(index).widget()
            if not isinstance(button, QPushButton):
                continue
            paths = self._action_button_paths(button.text())
            button.setChecked(bool(paths) and paths.issubset(self.selected_paths))

    def _on_action_button_toggled(self, name: str, checked: bool) -> None:
        """点击动作按钮：勾选/取消该动作在所有方向下的可传输文件。"""
        paths = self._action_button_paths(name)
        if not paths:
            # 无可传输文件时勾选不生效，同步回真实选中状态（避免“空点亮起”）。
            self._sync_action_buttons()
            return
        if checked:
            self.set_selected_paths(self.selected_paths | paths)
        else:
            self.set_selected_paths(self.selected_paths - paths)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.view.setEnabled(enabled)
        self.search_edit.setEnabled(enabled)
        for button in self.filter_group.buttons():
            button.setEnabled(enabled)
        self.select_visible_button.setEnabled(enabled)
        self.select_changed_button.setEnabled(enabled)
        self.clear_selection_button.setEnabled(enabled)

    def select_visible(self) -> None:
        selected = set(self.selected_paths)
        for row in range(self.proxy.rowCount()):
            action = self.proxy.index(row, 0).data(ROLE_OBJECT)
            if isinstance(action, ActionDiffItem):
                selected.update(item.relative_path for item in action.transferable_files)
        self.set_selected_paths(selected)

    def select_changed(self) -> None:
        """仅勾选所有有变更动作的可传输文件（替换当前选择，不受过滤和行高亮影响）。"""
        paths = {
            item.relative_path
            for action in self.actions
            for item in action.transferable_files
        }
        self.set_selected_paths(paths)

    def toggle_highlighted(self) -> None:
        paths = self._highlighted_transfer_paths()
        if not paths:
            return
        selected = set(self.selected_paths)
        if paths.issubset(selected):
            selected.difference_update(paths)
        else:
            selected.update(paths)
        self.set_selected_paths(selected)

    def clear_selection(self) -> None:
        self.set_selected_paths(set())

    def _highlighted_transfer_paths(self) -> set[str]:
        indexes = self.view.selectionModel().selectedRows(0)
        if not indexes and self.view.currentIndex().isValid():
            indexes = [self.view.currentIndex().siblingAtColumn(0)]
        paths: set[str] = set()
        for proxy_index in indexes:
            source_index = self.proxy.mapToSource(proxy_index)
            obj = source_index.data(ROLE_OBJECT)
            if isinstance(obj, ActionDiffItem):
                paths.update(item.relative_path for item in obj.transferable_files)
            elif isinstance(obj, FileDiffItem) and obj.is_transferable:
                paths.add(obj.relative_path)
        return paths

    def _build_action_row(self, action: ActionDiffItem) -> list[QStandardItem]:
        selection_item = QStandardItem()
        selection_item.setData("action", ROLE_KIND)
        selection_item.setData(action, ROLE_OBJECT)
        selection_item.setData(action.status, ROLE_STATUS)
        selection_item.setData(f"{action.action_name} {action.relative_path}", ROLE_SEARCH)
        selection_item.setData(action.transfer_file_count > 0, ROLE_TRANSFERABLE)
        if action.transfer_file_count:
            selection_item.setCheckable(True)
            selection_item.setUserTristate(True)
            selection_item.setCheckState(self._action_check_state(action))

        if action.file_diffs:
            placeholder = QStandardItem()
            placeholder.setData("placeholder", ROLE_KIND)
            selection_item.appendRow(
                [
                    placeholder,
                    QStandardItem(),
                    QStandardItem(),
                    QStandardItem("展开以查看文件"),
                    QStandardItem(),
                    QStandardItem(),
                    QStandardItem(),
                ]
            )

        direction_item = QStandardItem(self._direction_prefix(action))
        direction_item.setTextAlignment(Qt.AlignCenter)
        group_text, action_text = self._split_action_path(action.relative_path)
        group_item = QStandardItem(group_text)
        group_item.setToolTip(action.relative_path)
        action_item = QStandardItem(action_text)
        action_item.setToolTip(action.relative_path)
        status_color = STATUS_FOREGROUND.get(action.status, QColor("#96A1AD"))
        if action.status in ACTION_HIGHLIGHT_STATUSES:
            action_item.setForeground(status_color)
        status_item = QStandardItem(STATUS_LABELS.get(action.status, action.status))
        status_item.setData(action, ROLE_OBJECT)
        status_item.setForeground(status_color)
        change_item = QStandardItem(action.change_summary)
        size_item = QStandardItem(self._format_size(action.transfer_size_bytes))
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if action.status == "same":
            for it in (direction_item, group_item, action_item, status_item, change_item, size_item):
                it.setForeground(status_color)
        return [selection_item, direction_item, group_item, action_item, status_item, change_item, size_item]

    def _build_file_row(self, item: FileDiffItem) -> list[QStandardItem]:
        selection_item = QStandardItem()
        selection_item.setData("file", ROLE_KIND)
        selection_item.setData(item, ROLE_OBJECT)
        if item.is_transferable:
            selection_item.setCheckable(True)
            selection_item.setCheckState(Qt.Checked if item.relative_path in self.selected_paths else Qt.Unchecked)
        else:
            selection_item.setEnabled(False)
        direction_item = QStandardItem(self._file_direction(item))
        direction_item.setTextAlignment(Qt.AlignCenter)
        group_item = QStandardItem()
        file_item = QStandardItem(item.name)
        file_item.setToolTip(item.relative_path)
        status_color = STATUS_FOREGROUND.get(item.status, QColor("#96A1AD"))
        if item.status in ACTION_HIGHLIGHT_STATUSES:
            file_item.setForeground(status_color)
        status_item = QStandardItem(STATUS_LABELS.get(item.status, item.status))
        status_item.setForeground(status_color)
        change_item = QStandardItem()
        size_item = QStandardItem(self._format_size(item.size_bytes))
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if item.status == "same":
            for it in (direction_item, group_item, file_item, status_item, change_item, size_item):
                it.setForeground(status_color)
        return [selection_item, direction_item, group_item, file_item, status_item, change_item, size_item]

    def _on_expanded(self, proxy_index) -> None:
        source_index = self.proxy.mapToSource(proxy_index.siblingAtColumn(0))
        item = self.model.itemFromIndex(source_index)
        action = item.data(ROLE_OBJECT)
        if not isinstance(action, ActionDiffItem):
            return
        if item.rowCount() and item.child(0, 0).data(ROLE_KIND) != "placeholder":
            return
        self._updating_checks = True
        try:
            item.removeRows(0, item.rowCount())
            for file_item in action.file_diffs:
                item.appendRow(self._build_file_row(file_item))
        finally:
            self._updating_checks = False

    def _on_item_changed(self, item: QStandardItem) -> None:
        if self._updating_checks or item.column() != 0:
            return
        kind = item.data(ROLE_KIND)
        obj = item.data(ROLE_OBJECT)
        if kind == "action" and isinstance(obj, ActionDiffItem):
            paths = {file_item.relative_path for file_item in obj.transferable_files}
            if item.checkState() == Qt.Checked:
                self.selected_paths.update(paths)
            elif item.checkState() == Qt.Unchecked:
                self.selected_paths.difference_update(paths)
            self._sync_loaded_children(item)
        elif kind == "file" and isinstance(obj, FileDiffItem):
            if item.checkState() == Qt.Checked:
                self.selected_paths.add(obj.relative_path)
            else:
                self.selected_paths.discard(obj.relative_path)
            self._sync_parent_check(item.parent())
        self._emit_selection()

    def _sync_all_checks(self) -> None:
        self._updating_checks = True
        try:
            for row in range(self.model.rowCount()):
                item = self.model.item(row, 0)
                action = item.data(ROLE_OBJECT)
                if isinstance(action, ActionDiffItem) and item.isCheckable():
                    item.setCheckState(self._action_check_state(action))
                    self._sync_loaded_children(item)
        finally:
            self._updating_checks = False

    def _sync_loaded_children(self, parent: QStandardItem) -> None:
        if parent.rowCount() and parent.child(0, 0).data(ROLE_KIND) == "placeholder":
            return
        for row in range(parent.rowCount()):
            child = parent.child(row, 0)
            file_item = child.data(ROLE_OBJECT)
            if isinstance(file_item, FileDiffItem) and child.isCheckable():
                child.setCheckState(Qt.Checked if file_item.relative_path in self.selected_paths else Qt.Unchecked)

    def _sync_parent_check(self, parent: QStandardItem | None) -> None:
        if not parent:
            return
        action = parent.data(ROLE_OBJECT)
        if not isinstance(action, ActionDiffItem):
            return
        self._updating_checks = True
        try:
            parent.setCheckState(self._action_check_state(action))
        finally:
            self._updating_checks = False

    def _action_check_state(self, action: ActionDiffItem) -> Qt.CheckState:
        paths = {item.relative_path for item in action.transferable_files}
        selected_count = len(paths & self.selected_paths)
        if not selected_count:
            return Qt.Unchecked
        if selected_count == len(paths):
            return Qt.Checked
        return Qt.PartiallyChecked

    def _on_filter_changed(self, button: QPushButton) -> None:
        self._apply_status_filter(str(button.property("filterValue")))

    def _on_search_changed(self, text: str) -> None:
        self.proxy.set_search_text(text)
        self._update_visible_label()

    def _update_visible_label(self) -> None:
        self.visible_label.setText(f"{self.proxy.rowCount()} 个可见动作")

    def _update_filter_counts(self) -> None:
        counts = {
            "transfer": sum(action.transfer_file_count > 0 for action in self.actions),
            "only_left": sum(action.status == "only_left" for action in self.actions),
            "different": sum(action.status == "different" for action in self.actions),
            "same": sum(action.status == "same" for action in self.actions),
            "all": len(self.actions),
        }
        for value, button in self.filter_buttons.items():
            button.setText(f"{button.property('baseLabel')} {counts[value]}")

    def _on_current_changed(self, current, _previous) -> None:
        self._emit_action(current)

    def _on_clicked(self, proxy_index) -> None:
        """单击行切换当前预览；第 0 列复选框由 Qt 内置处理。"""
        # 单击不改变勾选状态，避免浏览时误操作。
        # 勾选通过：复选框点击（第 0 列）、空格快捷键、方向/动作快捷按钮。
        pass

    def _emit_action(self, proxy_index) -> None:
        if not proxy_index.isValid():
            return
        source_index = self.proxy.mapToSource(proxy_index.siblingAtColumn(0))
        while source_index.parent().isValid():
            source_index = source_index.parent()
        action = source_index.data(ROLE_OBJECT)
        if isinstance(action, ActionDiffItem):
            self.action_selected.emit(action.relative_path)

    def _emit_selection(self) -> None:
        self.selection_changed.emit(set(self.selected_paths))

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 ** 3:
            return f"{size / 1024 ** 3:.2f} GB"
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B" if size else "—"

    @staticmethod
    def _direction_prefix(action: ActionDiffItem) -> str:
        if action.transfer_file_count:
            return "→"
        if action.status == "only_right":
            return "SVN"
        if action.status == "same":
            return "="
        return "—"

    @staticmethod
    def _file_direction(item: FileDiffItem) -> str:
        if item.is_transferable:
            return "→"
        if item.status == "only_right":
            return "SVN"
        if item.status == "same":
            return "="
        return "—"

    @staticmethod
    def _split_action_path(relative_path: str) -> tuple[str, str]:
        path = PurePosixPath(relative_path)
        parent = path.parent.as_posix()
        return ("—" if parent == "." else parent, path.name)
