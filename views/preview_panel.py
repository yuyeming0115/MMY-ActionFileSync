from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
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


class PreviewCanvas(QLabel):
    resized = Signal()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.resized.emit()


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
    def __init__(self, title: str, role: str) -> None:
        super().__init__()
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
        return pixmap.scaled(desired, Qt.KeepAspectRatio, Qt.FastTransformation)

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
        scaled = self._pixmap.scaled(desired, Qt.KeepAspectRatio, Qt.FastTransformation)
        frame = QPixmap(available)
        frame.fill(Qt.transparent)
        painter = QPainter(frame)
        painter.drawPixmap(
            (available.width() - scaled.width()) // 2,
            (available.height() - scaled.height()) // 2 + self._offset_y,
            scaled,
        )
        painter.end()
        self.canvas.setText("")
        self.canvas.setPixmap(frame)


class PreviewPanel(QWidget):
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
        self.zoom_label = QLabel("缩放 100%")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setMaximumWidth(180)
        self.offset_label = QLabel("Y 位移 +50")
        self.offset_slider = QSlider(Qt.Horizontal)
        self.offset_slider.setRange(-200, 200)
        self.offset_slider.setValue(50)
        self.offset_slider.setMaximumWidth(180)
        controls.addWidget(self.play_button)
        controls.addWidget(self.frame_label)
        controls.addWidget(self.frame_slider, 1)
        controls.addWidget(self.zoom_label)
        controls.addWidget(self.zoom_slider)
        controls.addWidget(self.offset_label)
        controls.addWidget(self.offset_slider)

        layout.addLayout(header)
        layout.addWidget(self.preview_stack, 1)
        layout.addLayout(controls)

        self.play_button.clicked.connect(self._toggle_playback)
        self.frame_slider.valueChanged.connect(self._render_progress)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
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
