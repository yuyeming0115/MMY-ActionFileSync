from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QMainWindow, QSplitter, QVBoxLayout, QWidget

from utils.app_info import APP_VERSION, create_app_settings
from views.action_diff_panel import ActionDiffPanel
from views.preview_panel import PreviewPanel
from views.source_target_bar import SourceTargetBar
from views.transfer_panel import TransferPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = create_app_settings()
        self.setWindowTitle(f"MMY-Tools · Action File Sync v{APP_VERSION}")
        self.resize(1440, 900)
        self.setMinimumSize(1280, 720)

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
        self.preview_container.setMinimumWidth(740)
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
        self.settings.setValue("preview/compass_visible", self.preview_panel.compass_visible)
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
        compass_visible = self.settings.value("preview/compass_visible", True)
        self.preview_panel.set_compass_visible(str(compass_visible).lower() == "true")

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #1E2023;
                color: #E8E4D9;
                font-family: "Microsoft YaHei UI", "PingFang SC", "Hiragino Sans GB", "Helvetica Neue", sans-serif;
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
            QPushButton[actionButton="true"] { background: #2A2E33; border: 1px solid #3A3F46; border-radius: 6px; padding: 4px 12px; }
            QPushButton[actionButton="true"]:hover { border-color: #D4AF37; }
            QPushButton[actionButton="true"]:checked { background: rgba(212,175,55,0.22); color: #D4AF37; border-color: #D4AF37; font-weight: 600; }
            QPushButton[directionButton="true"] { background: #2A2E33; border: 1px solid #3A3F46; border-radius: 6px; padding: 4px 12px; }
            QPushButton[directionButton="true"]:hover { border-color: #5b9bd5; }
            QPushButton[directionButton="true"]:checked { background: rgba(91,155,213,0.22); color: #5b9bd5; border-color: #5b9bd5; font-weight: 600; }
            QPushButton[compassButton="true"] {
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 4px 14px;
                min-height: 0;
                color: #D4AF37;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton[compassButton="true"]:hover {
                background: rgba(212, 175, 55, 70);
            }
            QPushButton[compassButton="true"]:checked {
                background: #D4AF37;
                border: none;
                color: #1E2023;
            }
            QPushButton[compassButton="true"]:disabled {
                color: rgba(232, 228, 217, 60);
            }
            QToolButton[compassToggle="true"] { padding: 3px 8px; min-height: 0; }
            QToolButton[compassToggle="true"]:checked { color: #D4AF37; border-color: #D4AF37; }
            QFrame[backupBar="true"] {
                background: #1c242d;
                border: 1px solid #2b455f;
                border-radius: 6px;
            }
            QCheckBox[backupToggle="true"] {
                color: #82b8e8;
                font-size: 12px;
                font-weight: 600;
                spacing: 6px;
            }
            QCheckBox[backupToggle="true"]:disabled {
                color: #5A6068;
            }
            QCheckBox[backupToggle="true"]::indicator {
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid #4c6c8c;
                background: #1E2023;
            }
            QCheckBox[backupToggle="true"]::indicator:checked {
                background: #1769aa;
                border-color: #5b9bd5;
            }
            QCheckBox[backupToggle="true"]::indicator:disabled {
                background: #23262a;
                border-color: #3A3F46;
            }
            QFrame[backupBar="true"] QLineEdit[backupPathEdit="true"] {
                background: #222931;
                border: 1px solid #31475c;
                border-radius: 5px;
                padding: 2px 8px;
                min-height: 20px;
                font-size: 12px;
                color: #E8E4D9;
            }
            QFrame[backupBar="true"] QLineEdit[backupPathEdit="true"]:focus {
                border-color: #5b9bd5;
            }
            QFrame[backupBar="true"] QLineEdit[backupPathEdit="true"]:disabled {
                background: #1f2328;
                border-color: #32373d;
                color: #6D7782;
            }
            QFrame[backupBar="true"] QToolButton[backupToolButton="true"],
            QFrame[backupBar="true"] QPushButton[backupOpenButton="true"] {
                background: #2A2E33;
                border: 1px solid #364859;
                border-radius: 5px;
                padding: 2px 8px;
                min-height: 20px;
                font-size: 12px;
                color: #E8E4D9;
            }
            QFrame[backupBar="true"] QToolButton[backupToolButton="true"] {
                min-width: 24px;
                padding: 2px 5px;
            }
            QFrame[backupBar="true"] QToolButton[backupToolButton="true"]:hover,
            QFrame[backupBar="true"] QPushButton[backupOpenButton="true"]:hover {
                border-color: #5b9bd5;
                color: #ffffff;
            }
            QFrame[backupBar="true"] QToolButton[backupToolButton="true"]:disabled,
            QFrame[backupBar="true"] QPushButton[backupOpenButton="true"]:disabled {
                background: #23262a;
                border-color: #3A3F46;
                color: #5A6068;
            }
            QFrame[pinnedBar="true"] {
                background: #231e19;
                border: 1px solid #4d3726;
                border-radius: 6px;
            }
            QScrollArea#buttonRowArea, QWidget#buttonRowViewport, QWidget#buttonRowContent {
                background: transparent;
            }
            QLabel[pinnedBarTitle="true"] {
                color: #e08a3c;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel[pinnedEmptyHint="true"] {
                color: #96A1AD;
                font-size: 12px;
            }
            QToolButton[pinToggle="true"] {
                background: transparent;
                border: 1px solid #4d3726;
                border-radius: 6px;
                padding: 4px;
                min-width: 28px;
                min-height: 28px;
            }
            QToolButton[pinToggle="true"]:hover {
                border-color: #e08a3c;
                background: rgba(224, 138, 60, 0.12);
            }
            QToolButton[pinToggle="true"]:checked {
                background: rgba(224, 138, 60, 0.25);
                color: #f0a860;
                border-color: #e08a3c;
            }
            QToolButton[pinToggle="true"]:disabled {
                background: transparent;
                color: #5A6068;
                border-color: #3A3F46;
            }
            QPushButton[pinnedDirButton="true"] {
                background: #2A2E33;
                border: 1px solid #4A3E33;
                border-radius: 5px;
                padding: 2px 10px;
                min-height: 20px;
                font-size: 12px;
                color: #E8E4D9;
            }
            QPushButton[pinnedDirButton="true"]:hover {
                border-color: #e08a3c;
                color: #ffffff;
            }
            QPushButton[pinnedDirButton="true"]:checked {
                background: rgba(224, 138, 60, 0.25);
                color: #f0a860;
                border-color: #e08a3c;
                font-weight: 600;
            }
            QPushButton[pinnedDirButton="true"]:disabled {
                background: #2A2E33;
                color: #5A6068;
                border-color: #3A3F46;
            }
            QPushButton[pinnedAddButton="true"] {
                background: #2A2E33;
                border: 1px dashed #5A524A;
                border-radius: 5px;
                padding: 2px 9px;
                min-width: 24px;
                min-height: 20px;
                font-size: 12px;
                font-weight: 600;
                color: #96A1AD;
            }
            QPushButton[pinnedAddButton="true"]:hover {
                border-color: #e08a3c;
                color: #f0a860;
                background: rgba(224, 138, 60, 0.12);
            }
            QPushButton[pinnedAddButton="true"]:disabled {
                background: #2A2E33;
                color: #5A6068;
                border-color: #3A3F46;
            }
            QLineEdit {
                background: #2A2E33; border: 1px solid #3A3F46; border-radius: 6px; padding: 5px 8px;
                color: #E8E4D9; min-height: 28px;
            }
            QTreeView {
                background: #23262a; alternate-background-color: #1E2023; border: 1px solid #3A3F46;
                selection-background-color: rgba(212,175,55,0.15); selection-color: #D4AF37;
            }
            QTreeView::indicator { background: #1E2023; border: 1px solid #5A6068; border-radius: 2px; }
            QTreeView::indicator:checked, QTreeView::indicator:indeterminate {
                background: #D4AF37; border: 1px solid #D4AF37; border-radius: 2px;
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
