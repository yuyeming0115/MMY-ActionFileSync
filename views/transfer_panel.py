from __future__ import annotations

from PySide6.QtCore import QTime, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TransferPanel(QWidget):
    transfer_requested = Signal()
    clear_selection_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        summary_row = QHBoxLayout()
        self.selection_label = QLabel("未选择任何文件")
        self.selection_label.setProperty("selectionSummary", True)
        self.status_label = QLabel("")
        self.status_label.setProperty("secondaryText", True)
        self.details_button = QPushButton("详情")
        self.details_button.setCheckable(True)
        self.clear_button = QPushButton("清空选择")
        self.clear_button.setEnabled(False)
        self.transfer_button = QPushButton("传输预览并开始")
        self.transfer_button.setProperty("primaryAction", True)
        self.transfer_button.setEnabled(False)
        summary_row.addWidget(self.selection_label)
        summary_row.addSpacing(10)
        summary_row.addWidget(self.status_label, 1)
        summary_row.addWidget(self.details_button)
        summary_row.addWidget(self.clear_button)
        summary_row.addWidget(self.transfer_button)

        self.total_progress = QProgressBar()
        self.total_progress.setTextVisible(True)
        self.total_progress.setVisible(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setVisible(False)

        layout.addLayout(summary_row)
        layout.addWidget(self.total_progress)
        layout.addWidget(self.log)

        self.transfer_button.clicked.connect(self.transfer_requested.emit)
        self.clear_button.clicked.connect(self.clear_selection_requested.emit)
        self.details_button.toggled.connect(self.log.setVisible)

    def set_selection_summary(self, action_count: int, file_count: int, size_bytes: int) -> None:
        if not file_count:
            self.selection_label.setText("未选择任何文件")
        else:
            self.selection_label.setText(
                f"已选 {action_count} 个动作 · {file_count} 个文件 · {self._format_size(size_bytes)}"
            )
        self.transfer_button.setEnabled(bool(file_count) and not self._busy)
        self.clear_button.setEnabled(bool(file_count) and not self._busy)

    def append_log(self, message: str, level: str | None = None) -> None:
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        resolved_level = level or self._infer_log_level(message)
        colors = {
            "info": "#5b9bd5",
            "success": "#4caf50",
            "warning": "#e0a040",
            "error": "#ff6b5e",
            "neutral": "#96A1AD",
        }
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(colors.get(resolved_level, colors["neutral"])))
        cursor.setCharFormat(text_format)
        cursor.insertText(f"[{timestamp}] {message}")
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def set_transfer_enabled(self, enabled: bool) -> None:
        self._busy = not enabled
        self.transfer_button.setEnabled(enabled and "已选" in self.selection_label.text())
        self.clear_button.setEnabled(enabled and "已选" in self.selection_label.text())

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.total_progress.setVisible(busy)
        if busy:
            self.status_label.setText("正在传输")
            self.transfer_button.setText("传输中…")
            self.transfer_button.setEnabled(False)
            self.clear_button.setEnabled(False)
            self.details_button.setChecked(True)
        else:
            self.transfer_button.setText("传输预览并开始")

    def set_file_started(self, relative_path: str) -> None:
        self.status_label.setText(f"正在复制: {relative_path}")

    def set_stats(self, success: int, failed: int, skipped: int) -> None:
        self.status_label.setText(f"成功 {success} · 失败 {failed} · 跳过 {skipped}")

    def set_progress(self, current: int, total: int) -> None:
        self.total_progress.setRange(0, max(1, total))
        self.total_progress.setValue(current)
        self.total_progress.setFormat(f"总进度 {current}/{total}")

    def reset_progress(self) -> None:
        self.total_progress.setRange(0, 1)
        self.total_progress.setValue(0)
        self.total_progress.setVisible(False)
        self.status_label.clear()
        self._busy = False

    def reset_actions(self) -> None:
        self.selection_label.setText("未选择任何文件")
        self.status_label.clear()
        self.log.clear()
        self.transfer_button.setEnabled(False)
        self.clear_button.setEnabled(False)

    @staticmethod
    def _infer_log_level(message: str) -> str:
        if any(word in message for word in ("失败", "错误", "不存在", "校验失败")):
            return "error"
        if any(word in message for word in ("完成", "成功")):
            return "success"
        if any(word in message for word in ("警告", "跳过")):
            return "warning"
        if any(word in message for word in ("开始", "正在")):
            return "info"
        return "neutral"

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 ** 3:
            return f"{size / 1024 ** 3:.2f} GB"
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"
