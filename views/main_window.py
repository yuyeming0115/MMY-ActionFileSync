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
                background: #1E2023;
                color: #E8E4D9;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }
            QLabel[appTitle="true"] { font-size: 16px; font-weight: 600; }
            QLabel[sectionTitle="true"] { font-size: 14px; font-weight: 600; }
            QLabel[secondaryText="true"], QLabel[pathDetail="true"], QLabel[directionLabel="true"] {
                color: #96A1AD;
            }
            QLabel[scanStatus="ready"] { color: #4caf50; }
            QLabel[scanStatus="error"] { color: #ff6b5e; }
            QLabel[selectionSummary="true"] { font-weight: 600; }
            QFrame[pathRole="source"] {
                background: #1f2d3a;
                border: 1px solid #2f5374;
                border-top: 4px solid #1769aa;
                border-radius: 6px;
            }
            QFrame[pathRole="target"] {
                background: #2a2118;
                border: 1px solid #7a4a2a;
                border-top: 4px solid #a4510b;
                border-radius: 6px;
            }
            QFrame QLabel, QFrame QLineEdit, QFrame QToolButton { background: transparent; }
            QFrame[pathRole="source"] QLabel[pathTitle="true"], QLabel[previewRole="source"] {
                color: #5b9bd5; font-weight: 600;
            }
            QFrame[pathRole="target"] QLabel[pathTitle="true"], QLabel[previewRole="target"] {
                color: #e08a3c; font-weight: 600;
            }
            QWidget[previewPanelRole="source"] {
                background: #1f2d3a;
                border: 1px solid #2f5374;
                border-radius: 6px;
            }
            QWidget[previewPanelRole="target"] {
                background: #2a2118;
                border: 1px solid #7a4a2a;
                border-radius: 6px;
            }
            QWidget[previewPanelRole="source"] QLabel,
            QWidget[previewPanelRole="target"] QLabel { background: transparent; border: 0; }
            QLabel[pathHint="true"] { color: #96A1AD; font-size: 12px; }
            QLabel[directionArrow="true"] { color: #96A1AD; font-size: 24px; }
            QLabel[previewAction="true"] { font-weight: 600; }
            QLabel[hintBadge="true"] {
                background: #2A2E33; color: #96A1AD; padding: 3px 8px; border-radius: 4px;
            }
            QPushButton, QToolButton {
                background: #2A2E33;
                border: 1px solid #3A3F46;
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 28px;
            }
            QToolButton { padding: 4px; min-width: 28px; }
            QPushButton, QToolButton { color: #E8E4D9; }
            QPushButton:hover, QToolButton:hover { background: #2A2E33; border-color: #D4AF37; }
            QPushButton:disabled, QToolButton:disabled { background: #2A2E33; color: #5A6068; }
            QPushButton[primaryAction="true"] {
                background: #1769aa; color: #ffffff; border-color: #1769aa; font-weight: 600;
            }
            QPushButton[primaryAction="true"]:hover { background: #12578e; }
            QPushButton[segment="true"] { background: transparent; border-color: transparent; padding: 3px 8px; }
            QPushButton[segment="true"]:checked { background: rgba(212,175,55,0.15); color: #D4AF37; border-color: #D4AF37; }
            QLineEdit {
                background: #2A2E33; border: 1px solid #3A3F46; border-radius: 6px; padding: 5px 8px;
                color: #E8E4D9; min-height: 28px;
            }
            QTreeView {
                background: #23262a; alternate-background-color: #1E2023; border: 1px solid #3A3F46;
                selection-background-color: rgba(212,175,55,0.15); selection-color: #D4AF37;
            }
            QHeaderView::section {
                background: #2A2E33; border: 0; border-right: 1px solid #3A3F46;
                border-bottom: 1px solid #3A3F46; padding: 5px 7px; font-weight: 600; color: #E8E4D9;
            }
            QPlainTextEdit { background: #23262a; border: 1px solid #3A3F46; color: #E8E4D9; }
            QProgressBar {
                background: #2A2E33; border: 1px solid #3A3F46; border-radius: 4px;
                height: 18px; text-align: center; color: #E8E4D9;
            }
            QProgressBar::chunk { background: #D4AF37; }
            QSlider::groove:horizontal { height: 5px; background: #3A3F46; }
            QSlider::handle:horizontal {
                background: #E8E4D9; border: 1px solid #96A1AD; width: 14px; margin: -5px 0;
            }
            QLabel[previewCanvas="true"] { background: #23262a; border: 1px solid #3A3F46; }
            QSplitter::handle:horizontal {
                background: #3A3F46;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background: transparent; border: none; margin: 0;
            }
            QScrollBar:vertical { width: 8px; }
            QScrollBar:horizontal { height: 8px; }
            QScrollBar::handle {
                background: #4A4F56; border-radius: 4px; min-height: 24px; min-width: 24px;
            }
            QScrollBar::handle:hover { background: #5A6068; }
            QScrollBar::add-line, QScrollBar::sub-line,
            QScrollBar::add-page, QScrollBar::sub-page { background: transparent; border: none; }
            """
        )
