from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QFrame, QLayout, QLayoutItem, QScrollArea, QWidget


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
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
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
    """按宽度换行的快捷按钮行：高度贴合内容，最多显示 MAX_LINES 行，超出才走纵向滚动。

    横向滚动条永远不出现（按钮自适应容器宽度）；行高随内容收缩，
    避免按钮行把主清单或顶部区域挤占过多空间。
    """

    MAX_LINES = 2

    def __init__(
        self,
        accessible_name: str,
        *,
        max_lines: int = MAX_LINES,
        spacing: int = 6,
        min_line_padding: int = 10,
    ) -> None:
        super().__init__()
        self._max_lines = max(1, max_lines)
        self._min_line_padding = min_line_padding
        self.setObjectName("buttonRowArea")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.viewport().setObjectName("buttonRowViewport")
        self.setAccessibleName(accessible_name)
        self._row = QWidget()
        self._row.setObjectName("buttonRowContent")
        self._row.setStyleSheet("background:transparent;")
        self._flow = FlowLayout(self._row, spacing=spacing)
        self.setWidget(self._row)
        self.sync_height()

    def flow(self) -> FlowLayout:
        return self._flow

    def sync_height(self) -> None:
        """按当前内容与可视宽度调整行高，在增删按钮和宽度变化后调用。"""
        line = self._line_height()
        cap = line * self._max_lines + self._flow.spacing() * (self._max_lines - 1)
        content = self._flow.heightForWidth(max(1, self.viewport().width()))
        target_height = max(line, min(content, cap))
        if self.minimumHeight() != target_height or self.maximumHeight() != target_height:
            self.setFixedHeight(target_height)
            self.updateGeometry()
            parent = self.parentWidget()
            if parent is not None:
                if parent.layout() is not None:
                    parent.layout().invalidate()
                parent.updateGeometry()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange):
            self.sync_height()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.sync_height()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.sync_height()

    def _line_height(self) -> int:
        max_hint = 0
        for index in range(self._flow.count()):
            item = self._flow.itemAt(index)
            if item is not None:
                max_hint = max(max_hint, item.sizeHint().height())
        return max(max_hint, self.fontMetrics().height() + self._min_line_padding)
