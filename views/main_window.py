from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtWidgets import QMainWindow, QSplitter, QVBoxLayout, QWidget

from views.action_diff_panel import ActionDiffPanel
from views.preview_panel import PreviewPanel
from views.source_target_bar import SourceTargetBar
from views.transfer_panel import TransferPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("MMY-Tools", "MMY-ActionFileSync")
        self.setWindowTitle("MMY-Tools · Action File Sync v0.2.5")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 720)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self.source_target_bar = SourceTargetBar()
        self.action_diff_panel = ActionDiffPanel()
        self.preview_panel = PreviewPanel()
        self.transfer_panel = TransferPanel()

        self.action_container = QWidget()
        action_layout = QVBoxLayout(self.action_container)
        action_layout.setContentsMargins(0, 0, 10, 0)
        action_layout.setSpacing(0)
        action_layout.addWidget(self.action_diff_panel)

        self.preview_container = QWidget()
        preview_layout = QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(10, 0, 0, 0)
        preview_layout.setSpacing(0)
        preview_layout.addWidget(self.preview_panel)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(4)
        self.main_splitter.addWidget(self.action_container)
        self.main_splitter.addWidget(self.preview_container)
        self.action_container.setMinimumWidth(420)
        self.preview_container.setMinimumWidth(660)
        self.main_splitter.setStretchFactor(0, 40)
        self.main_splitter.setStretchFactor(1, 60)
        self.main_splitter.setSizes([520, 880])

        layout.addWidget(self.source_target_bar)
        layout.addWidget(self.main_splitter, 1)
        layout.addWidget(self.transfer_panel)

        self._apply_style()
        self._restore_layout()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/splitter", self.main_splitter.saveState())
        self.settings.setValue("preview/zoom", self.preview_panel.zoom_slider.value())
        self.settings.setValue("preview/offset_y", self.preview_panel.offset_slider.value())
        self.settings.sync()
        super().closeEvent(event)

    def _restore_layout(self) -> None:
        geometry = self.settings.value("window/geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        splitter = self.settings.value("window/splitter")
        if isinstance(splitter, QByteArray):
            self.main_splitter.restoreState(splitter)
        self.main_splitter.setHandleWidth(4)
        self.preview_panel.zoom_slider.setValue(int(self.settings.value("preview/zoom", 100)))
        self.preview_panel.offset_slider.setValue(int(self.settings.value("preview/offset_y", 50)))

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f3f5f7;
                color: #17212b;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }
            QLabel[appTitle="true"] { font-size: 16px; font-weight: 600; }
            QLabel[sectionTitle="true"] { font-size: 14px; font-weight: 600; }
            QLabel[secondaryText="true"], QLabel[pathDetail="true"], QLabel[directionLabel="true"] {
                color: #657386;
            }
            QLabel[scanStatus="ready"] { color: #237a45; }
            QLabel[scanStatus="error"] { color: #b42318; }
            QLabel[selectionSummary="true"] { font-weight: 600; }
            QFrame[pathRole="source"] {
                background: #eaf5ff;
                border: 1px solid #8ebce0;
                border-top: 4px solid #1769aa;
                border-radius: 5px;
            }
            QFrame[pathRole="target"] {
                background: #fff2e8;
                border: 1px solid #dfa879;
                border-top: 4px solid #a4510b;
                border-radius: 5px;
            }
            QFrame QLabel, QFrame QLineEdit, QFrame QToolButton { background: transparent; }
            QFrame[pathRole="source"] QLabel[pathTitle="true"], QLabel[previewRole="source"] {
                color: #1769aa; font-weight: 600;
            }
            QFrame[pathRole="target"] QLabel[pathTitle="true"], QLabel[previewRole="target"] {
                color: #a4510b; font-weight: 600;
            }
            QWidget[previewPanelRole="source"] {
                background: #edf7ff;
                border: 1px solid #8ebce0;
                border-radius: 5px;
            }
            QWidget[previewPanelRole="target"] {
                background: #fff4eb;
                border: 1px solid #dfa879;
                border-radius: 5px;
            }
            QWidget[previewPanelRole="source"] QLabel,
            QWidget[previewPanelRole="target"] QLabel { background: transparent; border: 0; }
            QLabel[pathHint="true"] { color: #657386; font-size: 12px; }
            QLabel[directionArrow="true"] { color: #364554; font-size: 24px; }
            QLabel[previewAction="true"] { font-weight: 600; }
            QLabel[hintBadge="true"] {
                background: #e9edf2; color: #445161; padding: 3px 8px; border-radius: 3px;
            }
            QPushButton, QToolButton {
                background: #ffffff;
                border: 1px solid #b9c3ce;
                border-radius: 4px;
                padding: 5px 10px;
                min-height: 28px;
            }
            QToolButton { padding: 4px; min-width: 28px; }
            QPushButton:hover, QToolButton:hover { background: #edf4fb; border-color: #7ba6ce; }
            QPushButton:disabled, QToolButton:disabled { background: #e7eaee; color: #929ba5; }
            QPushButton[primaryAction="true"] {
                background: #1769aa; color: #ffffff; border-color: #1769aa; font-weight: 600;
            }
            QPushButton[primaryAction="true"]:hover { background: #12578e; }
            QPushButton[segment="true"] { background: transparent; border-color: transparent; padding: 3px 8px; }
            QPushButton[segment="true"]:checked { background: #e6f1fb; color: #104f82; border-color: #87acd0; }
            QLineEdit {
                background: #ffffff; border: 1px solid #b9c3ce; border-radius: 4px; padding: 5px 8px;
                min-height: 28px;
            }
            QTreeView {
                background: #ffffff; alternate-background-color: #f7f9fb; border: 1px solid #cbd5df;
                selection-background-color: #dcecff; selection-color: #17212b;
            }
            QHeaderView::section {
                background: #edf1f5; border: 0; border-right: 1px solid #d2d9e1;
                border-bottom: 1px solid #cbd5df; padding: 5px 7px; font-weight: 600;
            }
            QPlainTextEdit { background: #ffffff; border: 1px solid #cbd5df; }
            QProgressBar {
                background: #e8edf2; border: 1px solid #c5ced8; border-radius: 3px;
                height: 18px; text-align: center;
            }
            QProgressBar::chunk { background: #237a45; }
            QSlider::groove:horizontal { height: 5px; background: #cbd3dc; }
            QSlider::handle:horizontal {
                background: #ffffff; border: 1px solid #5d6d7e; width: 14px; margin: -5px 0;
            }
            QLabel[previewCanvas="true"] { background: #d9dee4; border: 1px solid #bcc5cf; }
            QSplitter::handle:horizontal {
                background: #c4cdd7;
            }
            """
        )
