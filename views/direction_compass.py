from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QPushButton, QSizePolicy, QWidget

# 罗盘固定槽位：四角 + 四边中点，中央留空给角色精灵；对齐方式让按钮贴画布外缘。
COMPASS_SLOTS: tuple[tuple[int, int, str, Qt.Alignment], ...] = (
    (0, 0, "NW", Qt.AlignLeft | Qt.AlignTop),
    (0, 1, "N", Qt.AlignTop | Qt.AlignHCenter),
    (0, 2, "NE", Qt.AlignRight | Qt.AlignTop),
    (1, 0, "W", Qt.AlignLeft | Qt.AlignVCenter),
    (1, 2, "E", Qt.AlignRight | Qt.AlignVCenter),
    (2, 0, "SW", Qt.AlignLeft | Qt.AlignBottom),
    (2, 1, "S", Qt.AlignBottom | Qt.AlignHCenter),
    (2, 2, "SE", Qt.AlignRight | Qt.AlignBottom),
)

# 变更圆点颜色与清单状态色保持一致：新增待传=绿、内容变更=橙。
CHANGE_DOT_COLORS = {"only_left": "#4caf50", "different": "#e0a040"}


class CompassButton(QPushButton):
    """罗盘方向按钮；可在右上角叠加变更状态圆点。"""

    def __init__(self, direction: str) -> None:
        super().__init__(direction)
        self.setProperty("compassButton", True)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._change_color: str | None = None

    @property
    def change_color(self) -> str | None:
        return self._change_color

    def set_change_color(self, color: str | None) -> None:
        if color != self._change_color:
            self._change_color = color
            self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self._change_color:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 选中态为金色底，圆点加深色描边保证可见
        painter.setPen(QPen(QColor("#1E2023"), 1) if self.isChecked() else Qt.NoPen)
        painter.setBrush(QColor(self._change_color))
        painter.drawEllipse(QPointF(self.width() - 5.0, 5.0), 2.5, 2.5)


class DirectionCompass(QWidget):
    """预览画布上的八方向罗盘覆盖层。

    覆盖层自身对鼠标透明（不挡画布拖放），只有 8 个方向按钮接收点击；
    点击只发出意图信号，跳转与预览刷新由左侧清单驱动（清单是唯一真相源）。
    """

    direction_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 注意：绝不能在此设 WA_TransparentForMouseEvents——Qt 命中测试会跳过该属性
        # 控件的整棵子树，8 个方向按钮将收不到任何真实鼠标点击（程序化 .click() 不受
        # 影响，因此单元测试测不出来）。空白区域的鼠标事件由 QWidget 默认 ignore()
        # 冒泡回画布，按钮/空白处拖放目标也都会沿父链找到 acceptDrops 的画布。
        self.setStyleSheet("background:transparent;")
        self._user_visible = True
        self._context_valid = False

        layout = QGridLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._buttons: dict[str, CompassButton] = {}
        for row, column, direction, alignment in COMPASS_SLOTS:
            button = CompassButton(direction)
            button.clicked.connect(
                lambda checked=False, b=button, d=direction: self.direction_clicked.emit(d) if b.isEnabled() else None
            )
            layout.addWidget(button, row, column, alignment)
            self._buttons[direction] = button
        center = QWidget()
        center.setStyleSheet("background:transparent;")
        layout.addWidget(center, 1, 1)
        self.hide()

    @property
    def user_visible(self) -> bool:
        return self._user_visible

    def button_for(self, direction: str) -> CompassButton | None:
        return self._buttons.get(direction.upper())

    def set_user_visible(self, visible: bool) -> None:
        """用户显示开关（持久化设置），与上下文有效性共同决定罗盘是否显示。"""
        if visible != self._user_visible:
            self._user_visible = visible
            self._update_visibility()

    def set_context(
        self,
        current_direction: str,
        action_name: str,
        direction_status: dict[str, str],
        known_directions: set[str] | None = None,
    ) -> None:
        """同步罗盘状态（方向匹配一律 casefold，兼容目录大小写差异）。

        Args:
            current_direction: 当前预览方向（relative_path 一级父目录，可为空）。
            action_name: 当前动作名。
            direction_status: 数据中存在同名动作的方向 -> 动作状态（大小写以目录为准）。
            known_directions: 整个清单中出现过的方向集合；槽位不在其中则隐藏，
                数据集不含的方向不占位（如纯四方向数据只显示 4 个槽位）。
        """
        current_fold = current_direction.casefold()
        known_fold = {d.casefold() for d in (known_directions if known_directions is not None else direction_status)}
        status_by_fold = {d.casefold(): s for d, s in direction_status.items()}
        name_by_fold = {d.casefold(): d for d in direction_status}
        for slot, button in self._buttons.items():
            fold = slot.casefold()
            if fold not in known_fold:
                button.hide()
                continue
            status = status_by_fold.get(fold)
            available = status is not None
            button.show()
            button.setEnabled(available)
            button.setChecked(available and fold == current_fold)
            button.set_change_color(CHANGE_DOT_COLORS.get(status) if available else None)
            if available:
                button.setToolTip(f"预览 {name_by_fold[fold]}/{action_name}")
            else:
                button.setToolTip(f"{slot} 方向下没有同名动作「{action_name}」")
        self._context_valid = bool(current_direction and action_name and direction_status)
        self._update_visibility()

    def _update_visibility(self) -> None:
        self.setVisible(self._user_visible and self._context_valid)
