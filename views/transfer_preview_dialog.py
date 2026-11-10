from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.atlas_scan_service import ATLAS_PLIST, ATLAS_PNG
from services.transfer_service import TransferService
from utils.app_info import create_app_settings


COLUMN_COUNT = 4
DEFAULT_COLUMN_WIDTHS = [240, 540, 110, 90]
ROLE_EXTRA_NEW = Qt.UserRole + 1
EXTRA_TO_TARGET_DARK_BG = QColor("#ff6b5e")
EXTRA_TO_TARGET_LIGHT_BG = QColor("#d32f2f")


class TransferPreviewDialog(QDialog):
    def __init__(
        self,
        left_root: str,
        right_root: str,
        relative_paths: list[str],
        action_map: dict[str, str] | None = None,
        backup_enabled: bool = False,
        backup_dir: str = "",
        action_statuses: dict[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("确认传输范围")
        self.resize(1040, 620)
        self.left_root = Path(left_root)
        self.right_root = Path(right_root)
        self.action_map = action_map or {}
        self._action_map_ci = {key.casefold(): val for key, val in self.action_map.items()}
        self._action_statuses_ci = {key.casefold(): val for key, val in (action_statuses or {}).items()}
        self._backup_enabled = backup_enabled
        self._backup_dir = backup_dir.strip()
        self._updating_checks = False
        self._atlas_companions: dict[QTreeWidgetItem, QTreeWidgetItem] = {}
        self._extra_fg = self._pick_extra_foreground()

        layout = QVBoxLayout(self)
        heading = QLabel("请确认将从来源复制到目标的文件。可以取消动作或单个文件。")
        heading.setWordWrap(True)
        self.info_label = QLabel()
        self.info_label.setProperty("selectionSummary", True)
        self.backup_hint_label = QLabel()
        self.backup_hint_label.setProperty("secondaryText", True)
        self.backup_hint_label.setWordWrap(True)
        self.extra_warning_label = QLabel()
        self.extra_warning_label.setProperty("extraWarning", True)
        self.extra_warning_label.setStyleSheet(f"color: {self._extra_fg.name()}; font-weight: 600;")
        self.extra_warning_label.setWordWrap(True)
        self.extra_warning_label.setVisible(False)
        layout.addWidget(heading)
        layout.addWidget(self.info_label)
        layout.addWidget(self.backup_hint_label)
        layout.addWidget(self.extra_warning_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["动作 / 文件", "目标位置", "状态", "大小"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setIndentation(18)
        header = self.tree.header()
        header.setStretchLastSection(False)
        for column in range(COLUMN_COUNT):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        for column, width in enumerate(self._load_column_widths()):
            self.tree.setColumnWidth(column, width)
        layout.addWidget(self.tree, 1)

        button_row = QHBoxLayout()
        self.select_all_button = QPushButton("全选")
        self.clear_button = QPushButton("全不选")
        self.confirm_button = QPushButton("开始传输")
        self.confirm_button.setProperty("primaryAction", True)
        self.cancel_button = QPushButton("取消")
        button_row.addWidget(self.select_all_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.confirm_button)
        layout.addLayout(button_row)

        self._build_tree(relative_paths)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.select_all_button.clicked.connect(lambda: self._set_all_checks(Qt.Checked))
        self.clear_button.clicked.connect(lambda: self._set_all_checks(Qt.Unchecked))
        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self._update_summary()

    def _pick_extra_foreground(self) -> QColor:
        """深色主题用亮珊瑚红 #ff6b5e，浅色原生窗口用深红 #d32f2f 以保证对比度。"""
        widget: QWidget | None = self
        while widget is not None:
            sheet_lower = widget.styleSheet().lower()
            if "#1e2023" in sheet_lower or "#23262a" in sheet_lower:
                return EXTRA_TO_TARGET_DARK_BG
            widget = widget.parentWidget()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app_sheet_lower = app.styleSheet().lower()
            if "#1e2023" in app_sheet_lower or "#23262a" in app_sheet_lower:
                return EXTRA_TO_TARGET_DARK_BG
        if self.palette().color(self.backgroundRole()).lightness() < 128:
            return EXTRA_TO_TARGET_DARK_BG
        return EXTRA_TO_TARGET_LIGHT_BG

    def done(self, result: int) -> None:  # type: ignore[override]
        self._save_column_widths()
        super().done(result)

    def _load_column_widths(self) -> list[int]:
        saved = create_app_settings().value("transferPreview/columnWidths") or []
        if isinstance(saved, str):
            saved = [saved]
        try:
            widths = [int(value) for value in saved]
        except (TypeError, ValueError):
            widths = []
        if len(widths) == COLUMN_COUNT and all(width > 0 for width in widths):
            return widths
        return list(DEFAULT_COLUMN_WIDTHS)

    def _save_column_widths(self) -> None:
        widths = [self.tree.columnWidth(column) for column in range(COLUMN_COUNT)]
        create_app_settings().setValue("transferPreview/columnWidths", widths)

    def selected_paths(self) -> list[str]:
        paths: list[str] = []
        for group_index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(group_index)
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.checkState(0) == Qt.Checked:
                    relative_path = child.data(0, Qt.UserRole)
                    if relative_path:
                        paths.append(str(relative_path))
        return sorted(set(paths))

    def _resolve_action_group(self, relative_path: str) -> str:
        if relative_path in self.action_map:
            return self.action_map[relative_path]
        rel_ci = relative_path.casefold()
        if rel_ci in self._action_map_ci:
            return self._action_map_ci[rel_ci]
        rel_obj = Path(relative_path)
        name = rel_obj.name
        lower = name.lower()
        if lower.endswith(ATLAS_PNG):
            partner_name = f"{name[: -len(ATLAS_PNG)]}{ATLAS_PLIST}"
        elif lower.endswith(ATLAS_PLIST):
            partner_name = f"{name[: -len(ATLAS_PLIST)]}{ATLAS_PNG}"
        else:
            partner_name = ""
        if partner_name:
            partner_rel = (rel_obj.parent / partner_name).as_posix()
            if partner_rel in self.action_map:
                return self.action_map[partner_rel]
            partner_ci = partner_rel.casefold()
            if partner_ci in self._action_map_ci:
                return self._action_map_ci[partner_ci]
        return rel_obj.parent.as_posix()

    def _is_existing_target_action(
        self,
        action_path: str,
        entries: list[tuple[str, Path, Path]],
        target_dir_path: Path,
    ) -> bool:
        key = action_path.casefold()
        if key in self._action_statuses_ci:
            return self._action_statuses_ci[key] == "different"
        if any(target.exists() and target.is_file() for _rel, _source, target in entries):
            return True
        if action_path not in {"", "."} and target_dir_path.is_dir():
            try:
                return any(entry.is_file() for entry in target_dir_path.iterdir())
            except OSError:
                return False
        return False

    def _build_tree(self, relative_paths: list[str]) -> None:
        self._atlas_companions.clear()
        left_resolved = self.left_root.resolve()
        right_resolved = self.right_root.resolve()
        expanded_paths = TransferService.expand_atlas_paths(left_resolved, relative_paths)

        groups: dict[str, list[tuple[str, Path, Path]]] = defaultdict(list)
        for relative_path in expanded_paths:
            source = TransferService._safe_join(left_resolved, relative_path)
            target = TransferService._safe_join(right_resolved, relative_path)
            if source is None or target is None or not source.is_file():
                continue
            groups[self._resolve_action_group(relative_path)].append((relative_path, source, target))

        bold_font = QFont(self.tree.font())
        bold_font.setBold(True)

        self._updating_checks = True
        try:
            for action_path, entries in sorted(groups.items()):
                parent = QTreeWidgetItem(self.tree)
                parent.setText(0, Path(action_path).name or action_path)
                target_dir_path = (
                    right_resolved
                    if action_path in {"", "."}
                    else (TransferService._safe_join(right_resolved, action_path) or (right_resolved / Path(action_path)))
                )
                target_dir = target_dir_path.as_posix()
                parent.setText(1, target_dir)
                parent.setToolTip(1, target_dir)
                parent.setText(2, f"{len(entries)} 个文件")
                parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                parent.setCheckState(0, Qt.Checked)
                parent.setExpanded(True)

                is_existing_target = self._is_existing_target_action(action_path, entries, target_dir_path)
                by_rel: dict[str, QTreeWidgetItem] = {}
                for relative_path, source, target in entries:
                    will_overwrite = target.exists() and target.is_file()
                    is_extra_new = is_existing_target and not will_overwrite
                    size_bytes = source.stat().st_size
                    child = QTreeWidgetItem(parent)
                    child.setText(0, Path(relative_path).name)
                    child.setText(1, target.as_posix())
                    child.setToolTip(1, target.as_posix())
                    if is_extra_new:
                        child.setText(2, "新增 · 多出")
                        child.setForeground(2, self._extra_fg)
                        child.setFont(2, bold_font)
                        child.setToolTip(2, "强提示：目标 SVN 已有该动作但无此同名文件，传输后将比 SVN 多出此文件")
                    else:
                        child.setText(2, "覆盖" if will_overwrite else "新增")
                    child.setText(3, self._format_size(size_bytes))
                    child.setData(0, Qt.UserRole, relative_path)
                    child.setData(2, Qt.UserRole, will_overwrite)
                    child.setData(2, ROLE_EXTRA_NEW, is_extra_new)
                    child.setData(3, Qt.UserRole, size_bytes)
                    child.setToolTip(0, relative_path)
                    child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.Checked)
                    by_rel[relative_path] = child

                by_rel_ci = {rel_key.casefold(): item for rel_key, item in by_rel.items()}
                for rel_key, item in by_rel.items():
                    rel_obj = Path(rel_key)
                    lower = rel_obj.name.lower()
                    if not lower.endswith(ATLAS_PNG):
                        continue
                    stem = rel_obj.name[: -len(ATLAS_PNG)]
                    partner_rel = (rel_obj.parent / f"{stem}{ATLAS_PLIST}").as_posix()
                    partner_item = by_rel_ci.get(partner_rel.casefold())
                    if partner_item is not None:
                        self._atlas_companions[item] = partner_item
                        self._atlas_companions[partner_item] = item
        finally:
            self._updating_checks = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_checks or column != 0:
            return
        self._updating_checks = True
        try:
            if item.parent() is None:
                state = item.checkState(0)
                if state in {Qt.Checked, Qt.Unchecked}:
                    for index in range(item.childCount()):
                        item.child(index).setCheckState(0, state)
            else:
                companion = self._atlas_companions.get(item)
                if companion is not None and companion.checkState(0) != item.checkState(0):
                    companion.setCheckState(0, item.checkState(0))
                self._sync_parent(item.parent())
        finally:
            self._updating_checks = False
        self._update_summary()

    def _sync_parent(self, parent: QTreeWidgetItem) -> None:
        checked = sum(parent.child(index).checkState(0) == Qt.Checked for index in range(parent.childCount()))
        if checked == 0:
            parent.setCheckState(0, Qt.Unchecked)
        elif checked == parent.childCount():
            parent.setCheckState(0, Qt.Checked)
        else:
            parent.setCheckState(0, Qt.PartiallyChecked)

    def _set_all_checks(self, state: Qt.CheckState) -> None:
        self._updating_checks = True
        try:
            for group_index in range(self.tree.topLevelItemCount()):
                group = self.tree.topLevelItem(group_index)
                group.setCheckState(0, state)
                for child_index in range(group.childCount()):
                    group.child(child_index).setCheckState(0, state)
        finally:
            self._updating_checks = False
        self._update_summary()

    def _update_summary(self) -> None:
        action_count = 0
        file_count = 0
        overwrite_count = 0
        total_bytes = 0
        extra_new_count = 0
        extra_action_count = 0
        bold_font = QFont(self.tree.font())
        bold_font.setBold(True)
        for group_index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(group_index)
            group_has_selection = False
            group_extra = 0
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                if child.checkState(0) != Qt.Checked:
                    continue
                group_has_selection = True
                file_count += 1
                if bool(child.data(2, Qt.UserRole)):
                    overwrite_count += 1
                if bool(child.data(2, ROLE_EXTRA_NEW)):
                    group_extra += 1
                total_bytes += int(child.data(3, Qt.UserRole) or 0)
            action_count += int(group_has_selection)
            extra_new_count += group_extra
            extra_action_count += int(group_extra > 0)
            if group_extra > 0:
                group.setText(2, f"{group.childCount()} 个 · 多{group_extra}")
                group.setForeground(2, self._extra_fg)
                group.setFont(2, bold_font)
                group.setToolTip(2, f"强提示：该已存在动作勾选了 {group_extra} 个会比 SVN 多出的文件")
            else:
                group.setText(2, f"{group.childCount()} 个文件")
                group.setData(2, Qt.ForegroundRole, None)
                group.setData(2, Qt.FontRole, None)
                group.setToolTip(2, "")
        new_count = file_count - overwrite_count
        self.info_label.setText(
            f"将传输 {action_count} 个动作 · {file_count} 个文件（覆盖 {overwrite_count} · 新增 {new_count}）· {self._format_size(total_bytes)}"
        )
        if not self._backup_enabled:
            self.backup_hint_label.setText("传输前备份：未开启（可在顶部工具条勾选“传输前备份zip”）")
        elif file_count == 0:
            self.backup_hint_label.setText(f"传输前备份：已开启 → {self._backup_dir or '未设置目录'}")
        elif overwrite_count == 0:
            self.backup_hint_label.setText("传输前备份：已开启 · 本次全为新增文件，无需生成备份 zip")
        else:
            self.backup_hint_label.setText(
                f"传输前备份：已开启（方案 A）· 覆盖前将先打包 {overwrite_count} 个旧文件 zip 到 {self._backup_dir or '未设置目录'}"
            )
        if extra_new_count > 0:
            self.extra_warning_label.setText(
                f"⚠ 注意：其中 {extra_action_count} 个已存在动作包含 {extra_new_count} 个未覆盖同名旧文件的新增文件，传输后目标目录会比 SVN 多出这些文件。"
            )
            self.extra_warning_label.setVisible(True)
        else:
            self.extra_warning_label.clear()
            self.extra_warning_label.setVisible(False)
        self.confirm_button.setEnabled(file_count > 0)

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 ** 3:
            return f"{size / 1024 ** 3:.2f} GB"
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"
