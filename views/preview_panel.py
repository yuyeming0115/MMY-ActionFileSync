from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from models.preview_item import PreviewItem


STATUS_EMPTY_TEXT = {
    "missing": "当前角色缺失",
    "not_previewable": "当前动作不可预览",
    "error": "预览失败",
}


def draw_hud_overlay(
    painter: QPainter,
    *,
    role: str,
    frame_number: int,
    frame_count: int,
    original_width: int,
    original_height: int,
    zoom_percent: int,
    draw_x: int,
    draw_y: int,
    scaled_width: int,
    scaled_height: int,
) -> None:
    """在 pixmap 四角绘制半透明 HUD 胶囊信息。

    Args:
        painter: 已激活的 QPainter
        role: "source" 或 "target"
        frame_number: 当前帧号（从 1 开始）
        frame_count: 总帧数
        original_width: 原始图像宽
        original_height: 原始图像高
        zoom_percent: 缩放百分比
        draw_x: 缩放后图像在画布上的 x 坐标
        draw_y: 缩放后图像在画布上的 y 坐标
        scaled_width: 缩放后图像宽
        scaled_height: 缩放后图像高
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    painter.setFont(font)

    side_color = "#4ade80" if role == "source" else "#60a5fa"
    side_label = "来源" if role == "source" else "目标"
    frame_text = f"{frame_number} / {max(1, frame_count)}"
    size_text = f"{original_width}×{original_height}"
    zoom_text = f"{zoom_percent}%"

    padding_x = 8
    padding_y = 4
    corner_radius = 4
    text_color = QColor("#f1f5f9")
    bg_color = QColor(0, 0, 0, 160)
    metrics = painter.fontMetrics()

    def _pill(x: int, y: int, text: str, dot_hex: str | None = None) -> None:
        text_w = metrics.horizontalAdvance(text)
        text_h = metrics.height()
        dot_offset = 10 if dot_hex else 0
        pill_w = text_w + padding_x * 2 + dot_offset
        pill_h = text_h + padding_y * 2 - 4

        path = QPainterPath()
        path.addRoundedRect(x, y, pill_w, pill_h, corner_radius, corner_radius)
        painter.fillPath(path, bg_color)

        painter.setPen(text_color)
        painter.drawText(x + padding_x + dot_offset, y + pill_h - padding_y + 1, text)
        if dot_hex:
            painter.setBrush(QColor(dot_hex))
            painter.setPen(Qt.NoPen)
            dot_r = 4
            painter.drawEllipse(x + padding_x + 1, y + pill_h // 2 - dot_r, dot_r * 2, dot_r * 2)

    # 左上：侧别 + 色点
    _pill(draw_x + 6, draw_y + 6, side_label, side_color)

    # 右上：帧号
    frame_w = metrics.horizontalAdvance(frame_text) + padding_x * 2
    _pill(draw_x + scaled_width - frame_w - 6, draw_y + 6, frame_text)

    # 左下：尺寸
    size_w = metrics.horizontalAdvance(size_text) + padding_x * 2
    _pill(draw_x + 6, draw_y + scaled_height - 22 - 6, size_text)

    # 右下：缩放
    zoom_w = metrics.horizontalAdvance(zoom_text) + padding_x * 2
    _pill(draw_x + scaled_width - zoom_w - 6, draw_y + scaled_height - 22 - 6, zoom_text)

    painter.restore()


class PreviewCanvas(QLabel):
    resized = Signal()
    path_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.resized.emit()

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.path_dropped.emit(path)


class ElidedPathLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self._full_text = "-"
        self.setProperty("pathDetail", True)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(self.fontMetrics().height() + 6)

    def set_path(self, path: str) -> None:
        self._full_text = path or "-"
        self.setToolTip(self._full_text)
        self._update_text()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_text()

    def _update_text(self) -> None:
        available = max(20, self.contentsRect().width())
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideMiddle, available))


class SinglePreviewWidget(QWidget):
    path_dropped = Signal(str, str)

    def __init__(self, title: str, role: str) -> None:
        super().__init__()
        self._role = role
        self._static_pixmap = QPixmap()
        self._frame_pixmaps: list[QPixmap] = []
        self._zoom_percent = 100
        self._offset_y = 50
        self._progress = 0.0
        self._item = PreviewItem(role, "", None, None)
        self.setProperty("previewPanelRole", role)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        top_row = QHBoxLayout()
        self.role_label = QLabel(title)
        self.role_label.setProperty("previewRole", role)
        self.action_label = QLabel("未选择动作")
        self.action_label.setProperty("previewAction", True)
        self.zoom_badge = QLabel("100%")
        self.zoom_badge.setProperty("hintBadge", True)
        top_row.addWidget(self.role_label)
        top_row.addWidget(self.action_label)
        top_row.addStretch(1)
        top_row.addWidget(self.zoom_badge)

        self.canvas = PreviewCanvas()
        self.canvas.setAlignment(Qt.AlignCenter)
        self.canvas.setMinimumHeight(360)
        self.canvas.setWordWrap(True)
        self.canvas.setProperty("previewCanvas", True)
        self.canvas.resized.connect(self._render_current_frame)
        self.canvas.path_dropped.connect(lambda p: self.path_dropped.emit(self._role, p))

        self.meta_label = QLabel("尺寸: - · 帧: -")
        self.meta_label.setProperty("secondaryText", True)
        self.meta_label.setFixedHeight(self.meta_label.fontMetrics().height() + 6)
        self.path_label = ElidedPathLabel()

        layout.addLayout(top_row)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.path_label)
        self._set_empty_state("请选择动作以预览")

    @property
    def frame_count(self) -> int:
        if self._frame_pixmaps:
            return len(self._frame_pixmaps)
        return max(0, self._item.frame_count)

    @property
    def frame_interval_ms(self) -> int:
        return max(16, self._item.frame_interval_ms)

    def set_zoom_percent(self, zoom_percent: int) -> None:
        self._zoom_percent = zoom_percent
        self.zoom_badge.setText(f"{zoom_percent}%")
        self._render_current_frame()

    def set_offset_y(self, offset_y: int) -> None:
        self._offset_y = offset_y
        self._render_current_frame()

    def set_preview(self, item: PreviewItem) -> None:
        self._item = item
        self._static_pixmap = QPixmap()
        self._frame_pixmaps = []
        self._progress = 0.0
        self.action_label.setText(self._action_name(item.relative_path))
        self.path_label.set_path(item.source_path or "-")

        if item.status == "ready":
            if item.frame_paths:
                frames = [QPixmap(path) for path in item.frame_paths]
                self._frame_pixmaps = [frame for frame in frames if not frame.isNull()]
                if len(self._frame_pixmaps) == 1:
                    self._static_pixmap = self._frame_pixmaps[0]
            elif item.cache_path:
                self._static_pixmap = QPixmap(item.cache_path)
            self._update_meta()
            self._render_current_frame()
            return

        self._update_meta()
        self._set_empty_state(STATUS_EMPTY_TEXT.get(item.status, "暂无预览"))

    def render_at_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self._update_meta()
        self._render_current_frame()

    def pixmap_at_progress(self, progress: float) -> QPixmap:
        if self._frame_pixmaps:
            index = self._index_for_progress(progress, len(self._frame_pixmaps))
            return self._frame_pixmaps[index]
        return self._static_pixmap

    def frame_number_at_progress(self, progress: float) -> int:
        count = max(1, self.frame_count)
        return self._index_for_progress(progress, count) + 1

    def clear_preview(self) -> None:
        self._item = PreviewItem(self._item.side, "", None, None)
        self._static_pixmap = QPixmap()
        self._frame_pixmaps = []
        self.action_label.setText("未选择动作")
        self.path_label.set_path("-")
        self.meta_label.setText("尺寸: - · 帧: -")
        self._set_empty_state("请选择动作以预览")

    def _render_current_frame(self) -> None:
        pixmap = self.pixmap_at_progress(self._progress)
        if pixmap.isNull():
            return
        available = self.canvas.contentsRect().size()
        if available.width() < 2 or available.height() < 2:
            return
        scaled = self._scale_pixmap(pixmap)
        frame = QPixmap(available)
        frame.fill(Qt.transparent)
        painter = QPainter(frame)
        draw_x = int((available.width() - scaled.width()) / 2)
        draw_y = int((available.height() - scaled.height()) / 2 + self._offset_y)
        painter.drawPixmap(draw_x, draw_y, scaled)

        # ===== HUD overlay =====
        draw_hud_overlay(
            painter,
            role=self._role,
            frame_number=self.frame_number_at_progress(self._progress),
            frame_count=max(1, self.frame_count),
            original_width=pixmap.width(),
            original_height=pixmap.height(),
            zoom_percent=self._zoom_percent,
            draw_x=draw_x,
            draw_y=draw_y,
            scaled_width=scaled.width(),
            scaled_height=scaled.height(),
        )

        painter.end()
        self.canvas.setText("")
        self.canvas.setPixmap(frame)

    def _scale_pixmap(self, pixmap: QPixmap) -> QPixmap:
        desired = QSize(
            max(1, int(pixmap.width() * self._zoom_percent / 100)),
            max(1, int(pixmap.height() * self._zoom_percent / 100)),
        )
        if desired == pixmap.size():
            return pixmap
        # 缩小用平滑变换（避免锯齿），放大用快速变换（保留像素风锐利边缘）
        mode = Qt.SmoothTransformation if self._zoom_percent < 100 else Qt.FastTransformation
        return pixmap.scaled(desired, Qt.KeepAspectRatio, mode)

    def _update_meta(self) -> None:
        size = f"{self._item.width}×{self._item.height}" if self._item.width else "-"
        if self.frame_count:
            current = self.frame_number_at_progress(self._progress)
            frames = f"{current}/{self.frame_count}"
        else:
            frames = "-"
        self.meta_label.setText(f"尺寸: {size} · 帧: {frames}")

    def _set_empty_state(self, message: str) -> None:
        self.canvas.setPixmap(QPixmap())
        self.canvas.setText(message)

    @staticmethod
    def _index_for_progress(progress: float, count: int) -> int:
        if count <= 1:
            return 0
        return min(count - 1, max(0, round(progress * (count - 1))))

    @staticmethod
    def _action_name(relative_path: str) -> str:
        return relative_path.rstrip("/").split("/")[-1] if relative_path else "未选择动作"


class BlinkPreviewWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._pixmap = QPixmap()
        self._role = "source"
        self._zoom_percent = 100
        self._offset_y = 50
        self._frame_number = 0
        self._frame_count = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel("来源｜新动作")
        self.title_label.setProperty("previewRole", "source")
        self.canvas = PreviewCanvas()
        self.canvas.setAlignment(Qt.AlignCenter)
        self.canvas.setMinimumHeight(420)
        self.canvas.setProperty("previewCanvas", True)
        self.canvas.resized.connect(self._render)
        self.meta_label = QLabel("差异闪烁模式")
        self.meta_label.setProperty("secondaryText", True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.meta_label)

    def show_frame(self, pixmap: QPixmap, role: str, frame_number: int, frame_count: int) -> None:
        self._pixmap = pixmap
        self._role = role
        self._frame_number = frame_number
        self._frame_count = frame_count
        role_text = "来源｜新动作" if role == "source" else "目标｜SVN"
        self.title_label.setText(role_text)
        self.title_label.setProperty("previewRole", role)
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)
        self.meta_label.setText(f"差异闪烁模式 · {frame_number}/{frame_count or 1}")
        self._render()

    def set_zoom_percent(self, value: int) -> None:
        self._zoom_percent = value
        self._render()

    def set_offset_y(self, value: int) -> None:
        self._offset_y = value
        self._render()

    def _render(self) -> None:
        if self._pixmap.isNull():
            self.canvas.setPixmap(QPixmap())
            self.canvas.setText("当前帧不可用")
            return
        available = self.canvas.contentsRect().size()
        if available.width() < 2 or available.height() < 2:
            return
        desired = QSize(
            max(1, int(self._pixmap.width() * self._zoom_percent / 100)),
            max(1, int(self._pixmap.height() * self._zoom_percent / 100)),
        )
        mode = Qt.SmoothTransformation if self._zoom_percent < 100 else Qt.FastTransformation
        scaled = self._pixmap.scaled(desired, Qt.KeepAspectRatio, mode)
        frame = QPixmap(available)
        frame.fill(Qt.transparent)
        painter = QPainter(frame)
        draw_x = (available.width() - scaled.width()) // 2
        draw_y = (available.height() - scaled.height()) // 2 + self._offset_y
        painter.drawPixmap(draw_x, draw_y, scaled)

        # HUD overlay（闪烁模式下侧别提示尤其重要）
        draw_hud_overlay(
            painter,
            role=self._role,
            frame_number=self._frame_number,
            frame_count=max(1, self._frame_count),
            original_width=self._pixmap.width(),
            original_height=self._pixmap.height(),
            zoom_percent=self._zoom_percent,
            draw_x=draw_x,
            draw_y=draw_y,
            scaled_width=scaled.width(),
            scaled_height=scaled.height(),
        )

        painter.end()
        self.canvas.setText("")
        self.canvas.setPixmap(frame)


class PreviewPanel(QWidget):
    path_dropped = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance_frame)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(450)
        self._blink_timer.timeout.connect(self._toggle_blink_side)
        self._blink_side = "source"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("同步动画对比")
        title.setProperty("sectionTitle", True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.parallel_button = QPushButton("并排")
        self.parallel_button.setCheckable(True)
        self.parallel_button.setChecked(True)
        self.parallel_button.setProperty("segment", True)
        self.blink_button = QPushButton("差异闪烁")
        self.blink_button.setCheckable(True)
        self.blink_button.setProperty("segment", True)
        self.mode_group.addButton(self.parallel_button, 0)
        self.mode_group.addButton(self.blink_button, 1)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.parallel_button)
        header.addWidget(self.blink_button)

        self.left_preview = SinglePreviewWidget("来源｜新动作", "source")
        self.right_preview = SinglePreviewWidget("目标｜SVN", "target")
        self.left_preview.path_dropped.connect(self.path_dropped)
        self.right_preview.path_dropped.connect(self.path_dropped)
        parallel_page = QWidget()
        parallel_layout = QHBoxLayout(parallel_page)
        parallel_layout.setContentsMargins(0, 0, 0, 0)
        parallel_layout.setSpacing(12)
        parallel_layout.addWidget(self.left_preview, 1)
        parallel_layout.addWidget(self.right_preview, 1)

        self.blink_preview = BlinkPreviewWidget()
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(parallel_page)
        self.preview_stack.addWidget(self.blink_preview)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.play_button = QToolButton()
        self.play_button.setIcon(self._tinted_icon(QStyle.SP_MediaPause))
        self.play_button.setToolTip("播放/暂停")
        self.play_button.setAccessibleName("播放或暂停")
        self.frame_label = QLabel("0 / 0")
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setRange(0, 0)
        self.fit_button = QToolButton()
        self.fit_button.setText("适应")
        self.fit_button.setToolTip("适应窗口大小")
        self.fit_button.setAutoRaise(True)
        self.fit_button.setStyleSheet("QToolButton { padding: 2px 6px; }")
        self.fit_button.setAccessibleName("适应窗口")
        self.reset_zoom_button = QToolButton()
        self.reset_zoom_button.setText("1:1")
        self.reset_zoom_button.setToolTip("实际大小 (100%)")
        self.reset_zoom_button.setAutoRaise(True)
        self.reset_zoom_button.setStyleSheet("QToolButton { padding: 2px 6px; }")
        self.reset_zoom_button.setAccessibleName("实际大小")
        self.zoom_label = QLabel("缩放 100%")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setMaximumWidth(100)
        self.reset_offset_button = QToolButton()
        self.reset_offset_button.setText("归位")
        self.reset_offset_button.setToolTip("Y 位移归零")
        self.reset_offset_button.setAutoRaise(True)
        self.reset_offset_button.setStyleSheet("QToolButton { padding: 2px 6px; }")
        self.offset_label = QLabel("Y 位移 +50")
        self.offset_slider = QSlider(Qt.Horizontal)
        self.offset_slider.setRange(-200, 200)
        self.offset_slider.setValue(50)
        self.offset_slider.setMaximumWidth(100)
        controls.addWidget(self.play_button)
        controls.addWidget(self.frame_label)
        controls.addWidget(self.frame_slider, 1)
        controls.addWidget(self.fit_button)
        controls.addWidget(self.reset_zoom_button)
        controls.addWidget(self.zoom_label)
        controls.addWidget(self.zoom_slider)
        controls.addWidget(self.reset_offset_button)
        controls.addWidget(self.offset_label)
        controls.addWidget(self.offset_slider)

        layout.addLayout(header)
        layout.addWidget(self.preview_stack, 1)
        layout.addLayout(controls)

        self.play_button.clicked.connect(self._toggle_playback)
        self.frame_slider.valueChanged.connect(self._render_progress)
        self.fit_button.clicked.connect(self._fit_to_window)
        self.reset_zoom_button.clicked.connect(lambda: self.zoom_slider.setValue(100))
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        self.reset_offset_button.clicked.connect(lambda: self.offset_slider.setValue(0))
        self.offset_slider.valueChanged.connect(self._on_offset_changed)
        self.mode_group.idClicked.connect(self._set_mode)
        self._play_timer.start(80)

    def set_preview(self, side: str, item: PreviewItem) -> None:
        preview = self.left_preview if side == "left" else self.right_preview
        preview.set_preview(item)
        self._reset_timeline()

    def clear_all(self) -> None:
        self.left_preview.clear_preview()
        self.right_preview.clear_preview()
        self.frame_slider.setRange(0, 0)
        self.frame_label.setText("0 / 0")

    def _reset_timeline(self) -> None:
        maximum = max(self.left_preview.frame_count, self.right_preview.frame_count, 1)
        self.frame_slider.blockSignals(True)
        self.frame_slider.setRange(0, maximum - 1)
        self.frame_slider.setValue(0)
        self.frame_slider.blockSignals(False)
        interval = min(self.left_preview.frame_interval_ms, self.right_preview.frame_interval_ms)
        self._play_timer.setInterval(max(16, interval))
        self._render_progress()

    def _advance_frame(self) -> None:
        maximum = self.frame_slider.maximum()
        if maximum <= 0:
            return
        self.frame_slider.setValue((self.frame_slider.value() + 1) % (maximum + 1))

    def _tinted_icon(self, standard_pixmap: QStyle.StandardPixmap) -> QIcon:
        """把 QStyle 标准图标着色为前景色，避免黑色图标在暗色主题下不可见。"""
        icon = self.style().standardIcon(standard_pixmap)
        size = icon.actualSize(QSize(16, 16))
        source = icon.pixmap(size)
        tinted = QPixmap(source.size())
        tinted.fill(Qt.transparent)
        painter = QPainter(tinted)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QColor("#E8E4D9"))
        painter.end()
        return QIcon(tinted)

    def _toggle_playback(self) -> None:
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.play_button.setIcon(self._tinted_icon(QStyle.SP_MediaPlay))
        else:
            self._play_timer.start()
            self.play_button.setIcon(self._tinted_icon(QStyle.SP_MediaPause))

    def _render_progress(self) -> None:
        maximum = self.frame_slider.maximum()
        progress = self.frame_slider.value() / maximum if maximum else 0.0
        self.left_preview.render_at_progress(progress)
        self.right_preview.render_at_progress(progress)
        self.frame_label.setText(f"{self.frame_slider.value() + 1} / {maximum + 1}")
        self._render_blink(progress)

    def _fit_to_window(self) -> None:
        """根据当前画面和画布尺寸，自动计算缩放比例使画面完整显示在画布内。"""
        # 从左右预览中取最大的 pixmap 尺寸作为基准
        max_width = 0
        max_height = 0
        for preview in (self.left_preview, self.right_preview):
            pixmap = preview.pixmap_at_progress(0.0)
            if not pixmap.isNull():
                max_width = max(max_width, pixmap.width())
                max_height = max(max_height, pixmap.height())
        if max_width == 0 or max_height == 0:
            return
        # 用左侧画布尺寸做参考（两侧画布大小相同）
        canvas = self.left_preview.canvas.contentsRect()
        if canvas.width() < 2 or canvas.height() < 2:
            return
        # 留一点边距
        margin = 20
        scale_x = (canvas.width() - margin) / max_width
        scale_y = (canvas.height() - margin) / max_height
        scale_percent = int(min(scale_x, scale_y) * 100)
        scale_percent = max(self.zoom_slider.minimum(), min(self.zoom_slider.maximum(), scale_percent))
        if scale_percent > 0:
            self.zoom_slider.setValue(scale_percent)

    def _set_mode(self, mode_id: int) -> None:
        self.preview_stack.setCurrentIndex(mode_id)
        if mode_id == 1:
            self._blink_timer.start()
            self._render_progress()
        else:
            self._blink_timer.stop()

    def _toggle_blink_side(self) -> None:
        self._blink_side = "target" if self._blink_side == "source" else "source"
        self._render_progress()

    def _render_blink(self, progress: float) -> None:
        preview = self.left_preview if self._blink_side == "source" else self.right_preview
        self.blink_preview.show_frame(
            preview.pixmap_at_progress(progress),
            self._blink_side,
            preview.frame_number_at_progress(progress),
            preview.frame_count,
        )

    def _on_zoom_changed(self, value: int) -> None:
        self.zoom_label.setText(f"缩放 {value}%")
        self.left_preview.set_zoom_percent(value)
        self.right_preview.set_zoom_percent(value)
        self.blink_preview.set_zoom_percent(value)

    def _on_offset_changed(self, value: int) -> None:
        self.offset_label.setText(f"Y 位移 {value:+d}")
        self.left_preview.set_offset_y(value)
        self.right_preview.set_offset_y(value)
        self.blink_preview.set_offset_y(value)
