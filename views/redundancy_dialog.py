from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from services.redundancy_service import MoveOutcome, RedundancyItem
from utils.cancel_token import CancellationToken
from views.source_target_bar import DropPathEdit
from workers.redundancy_worker import RedundancyMoveWorker, RedundancyScanWorker


COLUMN_COUNT = 6
DEFAULT_COLUMN_WIDTHS = [50, 90, 150, 70, 90]
DEFAULT_DIRECTIONS = "E, N, S"
DEFAULT_KEEP_ACTIONS = "idle, run"


class RedundancyDialog(QDialog):
    """冗余帧扫描工具：找出「冗余方向 × 非保留动作」的动作目录，确认后整体移动到备份目录。"""

    def __init__(self, default_root: str = "", parent=None) -> None:
        super().__init__(parent)
        self.settings = QSettings("MMY-Tools", "MMY-ActionFileSync")
        self.setWindowTitle("冗余帧扫描")
        self.resize(1020, 640)
        self._items: list[RedundancyItem] = []
        self._threads: list[QThread] = []
        self._workers: list[object] = []
        self._cancel_token: CancellationToken | None = None
        self._scanning = False
        self._moving = False
        self._updating_checks = False
        self._move_errors: list[str] = []
        self._moved_paths: set[str] = set()
        self.moved_anything = False
        self._scanned_root = ""

        layout = QVBoxLayout(self)

        scan_row = QHBoxLayout()
        scan_row.addWidget(QLabel("扫描目录"))
        self.root_edit = DropPathEdit()
        self.root_edit.setText(default_root or str(self.settings.value("redundancy/lastRoot", "") or ""))
        self.root_button = QToolButton()
        self.root_button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.root_button.setToolTip("选择目录")
        self.root_button.setAccessibleName("选择扫描目录")
        scan_row.addWidget(self.root_edit, 1)
        scan_row.addWidget(self.root_button)

        rule_row = QHBoxLayout()
        rule_row.addWidget(QLabel("冗余方向"))
        self.directions_edit = QLineEdit(self._load_setting("redundancy/directions", DEFAULT_DIRECTIONS))
        self.directions_edit.setToolTip("这些方向下、保留动作以外的动作目录会被判为冗余，逗号分隔")
        rule_row.addWidget(self.directions_edit, 1)
        rule_row.addSpacing(12)
        rule_row.addWidget(QLabel("保留动作"))
        self.keep_edit = QLineEdit(self._load_setting("redundancy/keepActions", DEFAULT_KEEP_ACTIONS))
        self.keep_edit.setToolTip("冗余方向里需要保留的动作目录，逗号分隔")
        rule_row.addWidget(self.keep_edit, 1)

        scan_action_row = QHBoxLayout()
        self.scan_button = QPushButton("开始扫描")
        self.scan_button.setAccessibleName("开始扫描冗余帧")
        self.scan_cancel_button = QPushButton("取消")
        self.scan_cancel_button.setVisible(False)
        self.status_label = QLabel("选择目录后点击“开始扫描”")
        self.status_label.setProperty("scanStatus", "idle")
        scan_action_row.addWidget(self.scan_button)
        scan_action_row.addWidget(self.scan_cancel_button)
        scan_action_row.addSpacing(12)
        scan_action_row.addWidget(self.status_label, 1)

        self.info_label = QLabel()
        self.info_label.setProperty("selectionSummary", True)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["勾选", "方向", "动作", "帧数", "大小", "相对路径"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        header = self.tree.header()
        header.setStretchLastSection(False)
        for column in range(COLUMN_COUNT - 1):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        # 最后一列（相对路径）自动拉伸，吃掉剩余宽度
        header.setSectionResizeMode(COLUMN_COUNT - 1, QHeaderView.Stretch)
        for column, width in enumerate(self._load_column_widths()):
            self.tree.setColumnWidth(column, width)

        backup_row = QHBoxLayout()
        backup_row.addWidget(QLabel("备份目录"))
        self.backup_edit = DropPathEdit()
        self.backup_edit.setPlaceholderText("选择备份目录（冗余动作整体移入，保留原结构，可找回）")
        self.backup_edit.setText(str(self.settings.value("redundancy/backupRoot", "") or ""))
        self.backup_button = QToolButton()
        self.backup_button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.backup_button.setToolTip("选择备份目录")
        self.backup_button.setAccessibleName("选择备份目录")
        self.move_button = QPushButton("移动到备份目录")
        self.move_button.setProperty("primaryAction", True)
        self.move_button.setAccessibleName("移动到备份目录")
        backup_row.addWidget(self.backup_edit, 1)
        backup_row.addWidget(self.backup_button)
        backup_row.addWidget(self.move_button)

        bottom_row = QHBoxLayout()
        self.select_all_button = QPushButton("全选")
        self.clear_checks_button = QPushButton("全不选")
        self.close_button = QPushButton("关闭")
        bottom_row.addWidget(self.select_all_button)
        bottom_row.addWidget(self.clear_checks_button)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.close_button)

        layout.addLayout(scan_row)
        layout.addLayout(rule_row)
        layout.addLayout(scan_action_row)
        layout.addWidget(self.info_label)
        layout.addWidget(self.tree, 1)
        layout.addLayout(backup_row)
        layout.addLayout(bottom_row)

        self.root_edit.path_dropped.connect(self._on_root_dropped)
        self.root_button.clicked.connect(self._choose_root)
        self.scan_button.clicked.connect(self.start_scan)
        self.scan_cancel_button.clicked.connect(self._cancel_scan)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.select_all_button.clicked.connect(lambda: self._set_all_checks(Qt.Checked))
        self.clear_checks_button.clicked.connect(lambda: self._set_all_checks(Qt.Unchecked))
        self.backup_edit.path_dropped.connect(self._on_backup_dropped)
        self.backup_button.clicked.connect(self._choose_backup)
        self.move_button.clicked.connect(self.start_move)
        self.close_button.clicked.connect(self.close)
        self.root_edit.textChanged.connect(lambda _: self._update_ui_state())
        self.backup_edit.textChanged.connect(lambda _: self._update_ui_state())
        self._update_ui_state()

    def done(self, result: int) -> None:  # type: ignore[override]
        self._persist_settings()
        super().done(result)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._scanning or self._moving:
            reply = QMessageBox.question(
                self,
                "任务进行中",
                "当前有正在执行的扫描或移动任务，是否取消并关闭？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            if self._cancel_token:
                self._cancel_token.cancel()
            # 等待后台线程退出，避免线程对象随窗口销毁
            deadline = time.monotonic() + 5.0
            while self._threads and time.monotonic() < deadline:
                QApplication.processEvents()
            if self._threads:
                event.ignore()
                return
        self._persist_settings()
        super().closeEvent(event)

    def scanned_root(self) -> str:
        return self._scanned_root

    def checked_items(self) -> list[RedundancyItem]:
        return [
            self.tree.topLevelItem(index).data(0, Qt.UserRole)
            for index in range(self.tree.topLevelItemCount())
            if self.tree.topLevelItem(index).checkState(0) == Qt.Checked
        ]

    def start_scan(self) -> None:
        if self._scanning or self._moving:
            return
        root = self.root_edit.text().strip()
        if not root or not Path(root).is_dir():
            QMessageBox.warning(self, "冗余帧扫描", "请先选择有效的扫描目录。")
            return
        directions = self._parse_list(self.directions_edit.text())
        keeps = self._parse_list(self.keep_edit.text())
        if not directions:
            QMessageBox.warning(self, "冗余帧扫描", "冗余方向不能为空。")
            return
        self._scanned_root = root
        self._scanning = True
        self._items = []
        self.tree.clear()
        self.status_label.setText("正在扫描…")
        self.status_label.setProperty("scanStatus", "busy")
        self._update_ui_state()
        self._cancel_token = CancellationToken()
        worker = RedundancyScanWorker(root, directions, keeps, cancel_token=self._cancel_token)
        worker.progress.connect(self._on_scan_progress)
        self._run_worker(worker, self._on_scan_finished, self._on_worker_failed)

    def start_move(self) -> None:
        if self._scanning or self._moving:
            return
        items = self.checked_items()
        if not items:
            QMessageBox.information(self, "冗余帧扫描", "请先勾选要移动的动作目录。")
            return
        backup = self.backup_edit.text().strip()
        if not backup:
            QMessageBox.warning(self, "冗余帧扫描", "请先选择备份目录。")
            return
        root = self.root_edit.text().strip()
        if self._paths_overlap(root, backup):
            QMessageBox.warning(
                self,
                "冗余帧扫描",
                "备份目录不能与扫描目录相同，也不能位于扫描目录内部，"
                "否则移动后的文件下次扫描会再次被扫出。",
            )
            return
        frame_count = sum(item.frame_count for item in items)
        reply = QMessageBox.question(
            self,
            "确认移动",
            f"将把 {len(items)} 个动作目录（共 {frame_count} 帧）移动到：\n{backup}\n\n"
            "移动后可从备份目录找回，原位置将清空。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.settings.setValue("redundancy/backupRoot", backup)
        self._moving = True
        self._move_errors = []
        self._moved_paths = set()
        self.status_label.setText("正在移动…")
        self.status_label.setProperty("scanStatus", "busy")
        self._update_ui_state()
        self._cancel_token = CancellationToken()
        worker = RedundancyMoveWorker(root, backup, items, cancel_token=self._cancel_token)
        worker.item_started.connect(self._on_move_item_started)
        worker.item_finished.connect(self._on_move_item_finished)
        self._run_worker(worker, self._on_move_completed, self._on_worker_failed)

    def _on_scan_finished(self, items: list[RedundancyItem]) -> None:
        self._scanning = False
        self._cancel_token = None
        self._items = items
        self._populate_tree(items)
        if items:
            self.status_label.setText(f"扫描完成 · 发现 {len(items)} 个冗余动作目录")
        else:
            self.status_label.setText("扫描完成 · 未发现冗余动作目录")
        self.status_label.setProperty("scanStatus", "ready")
        self._update_ui_state()

    def _on_worker_failed(self, message: str) -> None:
        self._scanning = False
        self._moving = False
        self._cancel_token = None
        self._update_ui_state()
        if "取消" in message:
            self.status_label.setText("已取消")
            self.status_label.setProperty("scanStatus", "idle")
        else:
            self.status_label.setText("执行失败")
            self.status_label.setProperty("scanStatus", "error")
            QMessageBox.critical(self, "冗余帧扫描", message)

    def _on_scan_progress(self, visited: int) -> None:
        if self._scanning:
            self.status_label.setText(f"正在扫描… 已遍历 {visited} 个目录")

    def _populate_tree(self, items: list[RedundancyItem]) -> None:
        self._updating_checks = True
        try:
            for item in items:
                node = QTreeWidgetItem(self.tree)
                node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
                node.setCheckState(0, Qt.Checked)
                node.setText(1, item.direction)
                node.setText(2, item.action_name)
                node.setText(3, str(item.frame_count))
                node.setText(4, self._format_size(item.total_bytes))
                node.setText(5, item.relative_path)
                node.setToolTip(5, item.relative_path)
                node.setData(0, Qt.UserRole, item)
        finally:
            self._updating_checks = False
        self._update_summary()

    def _on_move_item_started(self, index: int, total: int, relative_path: str) -> None:
        self.status_label.setText(f"正在移动 ({index}/{total}): {relative_path}")

    def _on_move_item_finished(self, index: int, relative_path: str, ok: bool, error: str) -> None:
        if ok:
            self._moved_paths.add(relative_path)
        else:
            self._move_errors.append(f"{relative_path}: {error}")

    def _on_move_completed(self, outcome: MoveOutcome) -> None:
        self._moving = False
        self._cancel_token = None
        self._remove_rows(self._moved_paths)
        if outcome.moved:
            self.moved_anything = True
        if outcome.cancelled:
            self.status_label.setText(
                f"移动已取消（成功 {outcome.moved} · 失败 {outcome.failed}）"
            )
        elif outcome.failed:
            self.status_label.setText(f"移动完成（成功 {outcome.moved} · 失败 {outcome.failed}）")
        else:
            self.status_label.setText(f"移动完成 · 已移动 {outcome.moved} 个动作目录")
        self.status_label.setProperty("scanStatus", "ready" if not outcome.failed else "error")
        self._update_ui_state()
        if outcome.failed:
            detail = "\n".join(self._move_errors[:10])
            more = f"\n… 等共 {outcome.failed} 项失败" if outcome.failed > 10 else ""
            QMessageBox.warning(self, "移动结果", f"成功 {outcome.moved} 个，失败 {outcome.failed} 个：\n{detail}{more}")

    def _remove_rows(self, relative_paths: set[str]) -> None:
        for index in range(self.tree.topLevelItemCount() - 1, -1, -1):
            item = self.tree.topLevelItem(index)
            data = item.data(0, Qt.UserRole)
            if data is not None and data.relative_path in relative_paths:
                self.tree.takeTopLevelItem(index)
        self._update_summary()

    def _cancel_scan(self) -> None:
        if self._cancel_token:
            self._cancel_token.cancel()
            self.status_label.setText("正在取消…")

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_checks or column != 0:
            return
        self._update_summary()

    def _set_all_checks(self, state: Qt.CheckState) -> None:
        self._updating_checks = True
        try:
            for index in range(self.tree.topLevelItemCount()):
                self.tree.topLevelItem(index).setCheckState(0, state)
        finally:
            self._updating_checks = False
        self._update_summary()

    def _update_summary(self) -> None:
        total = self.tree.topLevelItemCount()
        if not total:
            self.info_label.setText("")
        else:
            items = self.checked_items()
            frame_count = sum(item.frame_count for item in items)
            total_bytes = sum(item.total_bytes for item in items)
            self.info_label.setText(
                f"已选 {len(items)}/{total} 个动作目录 · {frame_count} 帧 · {self._format_size(total_bytes)}"
            )
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        busy = self._scanning or self._moving
        has_rows = self.tree.topLevelItemCount() > 0
        self.scan_button.setEnabled(not busy and bool(self.root_edit.text().strip()))
        self.scan_cancel_button.setVisible(self._scanning)
        self.root_edit.setEnabled(not busy)
        self.root_button.setEnabled(not busy)
        self.directions_edit.setEnabled(not busy)
        self.keep_edit.setEnabled(not busy)
        self.backup_edit.setEnabled(not busy)
        self.backup_button.setEnabled(not busy)
        self.select_all_button.setEnabled(not busy and has_rows)
        self.clear_checks_button.setEnabled(not busy and has_rows)
        self.move_button.setEnabled(
            not busy and has_rows and bool(self.checked_items()) and bool(self.backup_edit.text().strip())
        )

    def _choose_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择扫描目录", self.root_edit.text())
        if path:
            self.root_edit.setText(path)

    def _choose_backup(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择备份目录", self.backup_edit.text())
        if path:
            self.backup_edit.setText(path)

    def _on_root_dropped(self, path: str) -> None:
        self.root_edit.setText(path)

    def _on_backup_dropped(self, path: str) -> None:
        self.backup_edit.setText(path)

    def _persist_settings(self) -> None:
        self.settings.setValue("redundancy/directions", self.directions_edit.text())
        self.settings.setValue("redundancy/keepActions", self.keep_edit.text())
        self.settings.setValue("redundancy/backupRoot", self.backup_edit.text())
        if self._scanned_root:
            self.settings.setValue("redundancy/lastRoot", self._scanned_root)
        self.settings.setValue(
            "redundancyDialog/columnWidths",
            [self.tree.columnWidth(column) for column in range(COLUMN_COUNT - 1)],
        )
        self.settings.sync()

    def _load_setting(self, key: str, default: str) -> str:
        return str(self.settings.value(key, default) or default)

    def _load_column_widths(self) -> list[int]:
        saved = self.settings.value("redundancyDialog/columnWidths") or []
        if isinstance(saved, str):
            saved = [saved]
        try:
            widths = [int(value) for value in saved]
        except (TypeError, ValueError):
            widths = []
        if len(widths) == COLUMN_COUNT - 1 and all(width > 0 for width in widths):
            return widths
        return list(DEFAULT_COLUMN_WIDTHS)

    def _run_worker(self, worker, finished, failed) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(finished)
        worker.failed.connect(failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._release_worker(worker, thread))
        thread.started.connect(worker.run)
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    def _release_worker(self, worker: object, thread: QThread) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if thread in self._threads:
            self._threads.remove(thread)

    @staticmethod
    def _parse_list(text: str) -> list[str]:
        normalized = text.replace("，", ",").replace("、", ",")
        return [part.strip() for part in normalized.split(",") if part.strip()]

    @staticmethod
    def _paths_overlap(first: str, second: str) -> bool:
        try:
            a = Path(first).resolve()
            b = Path(second).resolve()
        except OSError:
            return False
        return a == b or a in b.parents or b in a.parents

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 ** 3:
            return f"{size / 1024 ** 3:.2f} GB"
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"
