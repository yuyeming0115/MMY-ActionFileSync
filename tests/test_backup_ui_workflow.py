from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import main as app_main
from models.action_diff import ActionDiffItem, FileDiffItem
from services.backup_service import BackupService, default_backup_dir

HAS_QT = importlib.util.find_spec("PySide6") is not None

if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QMimeData, QPointF, QSettings, QSize, QTimer, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QAbstractButton, QApplication, QMessageBox

    from controllers.main_controller import MainController
    from utils.app_info import create_app_settings
    from utils.path_matcher import normalize_path
    from views.transfer_preview_dialog import TransferPreviewDialog


def _thread_settled(thread) -> bool:
    try:
        return not thread.isRunning()
    except RuntimeError:
        return True


def _drop_url_onto(widget, local_path: Path) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(local_path))])
    event = QDropEvent(
        QPointF(widget.rect().center()),
        Qt.CopyAction,
        mime,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    widget.dropEvent(event)


@unittest.skipUnless(HAS_QT, "需要安装 PySide6")
class BackupUiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings_dir = tempfile.TemporaryDirectory()
        cls._prev_format = QSettings.defaultFormat()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings_dir.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
        QSettings.setDefaultFormat(cls._prev_format)
        cls.settings_dir.cleanup()

    def setUp(self) -> None:
        settings = create_app_settings()
        settings.clear()
        settings.sync()

    def tearDown(self) -> None:
        settings = create_app_settings()
        settings.clear()
        settings.sync()

    def test_qsettings_isolated_to_temp_ini_without_registry_leak(self) -> None:
        settings = create_app_settings()
        self.assertEqual(settings.format(), QSettings.IniFormat)
        ini_path = Path(settings.fileName()).resolve()
        temp_root = Path(self.settings_dir.name).resolve()
        self.assertTrue(ini_path.is_relative_to(temp_root))

        sentinel = "__isolated_backup_test_dir__"
        settings.setValue("transfer/backupDir", sentinel)
        settings.sync()
        self.assertIn(sentinel, ini_path.read_text(encoding="utf-8"))

        if os.name == "nt":
            import winreg

            for subkey in (
                r"Software\MMY-Tools\MMY-ActionFileSync",
                r"Software\MMY-Tools\MMY-ActionFileSync\transfer",
            ):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
                        index = 0
                        while True:
                            try:
                                _name, val, _kind = winreg.EnumValue(key, index)
                                self.assertNotEqual(val, sentinel)
                                index += 1
                            except OSError:
                                break
                except FileNotFoundError:
                    pass

    def test_default_backup_config_and_minimum_size_no_clipping(self) -> None:
        controller = MainController()
        bar = controller.source_target_bar
        self.assertEqual(bar.backup_config(), (True, default_backup_dir()))

        controller.resize(controller.minimumSize())
        controller.show()
        self.app.processEvents()

        self.assertLessEqual(abs(bar.source_field.width() - bar.target_field.width()), 1)
        self.assertLessEqual(abs(bar.backup_bar.width() - bar.source_field.width()), 1)
        self.assertEqual(bar.backup_bar.browse_button.iconSize(), QSize(14, 14))
        self.assertLessEqual(
            abs(bar.backup_bar.browse_button.height() - bar.backup_bar.path_edit.height()),
            2,
        )
        self.assertLessEqual(
            abs(bar.backup_bar.open_button.height() - bar.backup_bar.path_edit.height()),
            2,
        )

        # 验证自定义绘制勾选框开启/关闭状态渲染存在明显像素差异（白色对勾绘制生效）
        checked_img = bar.backup_bar.enabled_checkbox.grab().toImage()
        bar.backup_bar.enabled_checkbox.setChecked(False)
        self.app.processEvents()
        unchecked_img = bar.backup_bar.enabled_checkbox.grab().toImage()
        self.assertNotEqual(checked_img.constBits().tobytes(), unchecked_img.constBits().tobytes())
        bar.backup_bar.enabled_checkbox.setChecked(True)
        self.app.processEvents()

        clipped: list[str] = []
        for button in controller.findChildren(QAbstractButton):
            if not button.isVisible() or not button.text():
                continue
            hint = button.sizeHint()
            if button.width() + 2 < hint.width() or button.height() + 2 < hint.height():
                clipped.append(f"{button.text()}({button.width()}×{button.height()} < {hint.width()}×{hint.height()})")
        self.assertFalse(clipped, f"顶部工具条含备份控件存在文字裁切: {clipped}")

        # 桌面默认尺寸下左侧动作表可见行数不受顶部备份条影响
        actions = [
            ActionDiffItem(
                action_id=f"action-{index}",
                action_name=f"action_{index:02d}",
                relative_path=f"player/action_{index:02d}",
                status="same",
                source_node=None,
                target_node=None,
                file_diffs=[],
            )
            for index in range(30)
        ]
        controller.action_diff_panel.populate(actions)
        controller.action_diff_panel.filter_buttons["all"].click()
        controller.resize(1440, 900)
        self.app.processEvents()
        view = controller.action_diff_panel.view
        viewport_rect = view.viewport().rect()
        visible_rows = sum(
            view.visualRect(controller.action_diff_panel.proxy.index(row, 0)).intersects(viewport_rect)
            for row in range(controller.action_diff_panel.proxy.rowCount())
        )
        self.assertGreaterEqual(visible_rows, 18)
        self._dispose(controller)

    def test_backup_bar_set_busy_preserves_disabled_input_state(self) -> None:
        controller = MainController()
        bar = controller.source_target_bar
        backup_bar = bar.backup_bar

        backup_bar.enabled_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertFalse(backup_bar.path_edit.isEnabled())
        self.assertFalse(backup_bar.browse_button.isEnabled())
        self.assertTrue(backup_bar.open_button.isEnabled())

        bar.set_busy(True)
        self.assertFalse(backup_bar.enabled_checkbox.isEnabled())
        self.assertFalse(backup_bar.path_edit.isEnabled())
        self.assertFalse(backup_bar.browse_button.isEnabled())
        self.assertFalse(backup_bar.open_button.isEnabled())

        bar.set_busy(False)
        self.assertTrue(backup_bar.enabled_checkbox.isEnabled())
        self.assertFalse(backup_bar.enabled_checkbox.isChecked())
        self.assertFalse(backup_bar.path_edit.isEnabled())
        self.assertFalse(backup_bar.browse_button.isEnabled())
        self.assertTrue(backup_bar.open_button.isEnabled())

        backup_bar.enabled_checkbox.setChecked(True)
        bar.set_busy(True)
        bar.set_busy(False)
        self.assertTrue(backup_bar.path_edit.isEnabled())
        self.assertTrue(backup_bar.browse_button.isEnabled())
        self.assertTrue(backup_bar.open_button.isEnabled())
        self._dispose(controller)

    def test_backup_config_persists_drag_drop_edit_toggle_reset_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            dropped_dir = base / "拖入备份"
            typed_dir = base / "手动备份"
            dropped_dir.mkdir()
            typed_dir.mkdir()

            controller = MainController()
            backup_bar = controller.source_target_bar.backup_bar

            # 拖入目录立即记忆
            _drop_url_onto(backup_bar.path_edit, dropped_dir)
            self.app.processEvents()
            self.assertEqual(controller.source_target_bar.backup_config(), (True, normalize_path(str(dropped_dir))))

            # 手动编辑（含反斜杠）与勾选切换立即记忆
            raw_typed = str(typed_dir).replace("/", "\\")
            backup_bar.path_edit.setText(raw_typed)
            backup_bar.path_edit.textEdited.emit(raw_typed)
            backup_bar.path_edit.editingFinished.emit()
            self.assertEqual(backup_bar.path_edit.text(), normalize_path(str(typed_dir)))

            backup_bar.enabled_checkbox.setChecked(False)
            self.app.processEvents()
            self.assertFalse(backup_bar.path_edit.isEnabled())
            self.assertFalse(backup_bar.browse_button.isEnabled())
            self.assertTrue(backup_bar.open_button.isEnabled())

            # 清空当前列表不会抹掉记忆的备份目录与开关
            controller.clear_all_lists()
            self.assertEqual(controller.source_target_bar.backup_config(), (False, normalize_path(str(typed_dir))))
            self._dispose(controller)

            # 重启控制器恢复记住的状态与目录
            restarted = MainController()
            self.assertEqual(
                restarted.source_target_bar.backup_config(),
                (False, normalize_path(str(typed_dir))),
            )
            self.assertFalse(restarted.source_target_bar.backup_bar.path_edit.isEnabled())

            # 恢复默认备份目录（保留当前启用/关闭状态）
            restarted.source_target_bar.reset_backup_dir_requested.emit()
            self.assertEqual(
                restarted.source_target_bar.backup_config(),
                (False, default_backup_dir()),
            )
            self._dispose(restarted)

    def test_transfer_preview_dialog_displays_overwrite_counts_and_backup_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            (source / "NW" / "attack").mkdir(parents=True)
            (target / "NW" / "attack").mkdir(parents=True)
            (source / "NW" / "attack" / "a1.png").write_bytes(b"new1")
            (target / "NW" / "attack" / "a1.png").write_bytes(b"old1")
            (source / "NW" / "attack" / "a2.png").write_bytes(b"new2")

            paths = ["NW/attack/a1.png", "NW/attack/a2.png"]
            action_map = {path: "NW/attack" for path in paths}
            dialog = TransferPreviewDialog(
                str(source),
                str(target),
                paths,
                action_map,
                backup_enabled=True,
                backup_dir="D:/Temp/Bak",
            )
            self.assertIn("覆盖 1 · 新增 1", dialog.info_label.text())
            self.assertIn("1 个旧文件", dialog.backup_hint_label.text())
            self.assertIn("D:/Temp/Bak", dialog.backup_hint_label.text())

            # 取消勾选会被覆盖的文件，仅剩新增文件时提示无需备份
            dialog.tree.topLevelItem(0).child(0).setCheckState(0, Qt.Unchecked)
            self.assertIn("覆盖 0 · 新增 1", dialog.info_label.text())
            self.assertIn("无需生成备份", dialog.backup_hint_label.text())
            self._dispose(dialog)

            disabled_dialog = TransferPreviewDialog(
                str(source),
                str(target),
                paths,
                action_map,
                backup_enabled=False,
                backup_dir="D:/Temp/Bak",
            )
            self.assertIn("未开启", disabled_dialog.backup_hint_label.text())
            self._dispose(disabled_dialog)

    def test_transfer_preview_dialog_expands_and_syncs_subdir_atlas_pair_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            rel_png = "sub/hero.png"
            rel_plist = "sub/hero.plist"
            (source / "sub").mkdir(parents=True)
            (target / "sub").mkdir(parents=True)
            (source / rel_png).write_bytes(b"new-atlas-png")
            (source / rel_plist).write_text("<plist>new</plist>", encoding="utf-8")
            (target / rel_png).write_bytes(b"old-atlas-png")
            (target / rel_plist).write_text("<plist>old</plist>", encoding="utf-8")

            # 仅传入 .png：预览弹窗应自动补齐同子目录配套 .plist 并联动勾选
            dialog = TransferPreviewDialog(
                str(source),
                str(target),
                [rel_png],
                {rel_png: "sub"},
                backup_enabled=True,
                backup_dir=str(backup_dir),
            )
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            group = dialog.tree.topLevelItem(0)
            self.assertEqual(group.childCount(), 2)
            self.assertIn("覆盖 2 · 新增 0", dialog.info_label.text())
            self.assertIn("2 个旧文件", dialog.backup_hint_label.text())
            self.assertEqual(dialog.selected_paths(), [rel_plist, rel_png])

            by_rel = {
                group.child(index).data(0, Qt.UserRole): group.child(index)
                for index in range(group.childCount())
            }
            by_rel[rel_png].setCheckState(0, Qt.Unchecked)
            self.assertEqual(by_rel[rel_plist].checkState(0), Qt.Unchecked)
            self.assertEqual(dialog.selected_paths(), [])
            self.assertFalse(dialog.confirm_button.isEnabled())

            by_rel[rel_plist].setCheckState(0, Qt.Checked)
            self.assertEqual(by_rel[rel_png].checkState(0), Qt.Checked)
            self.assertEqual(dialog.selected_paths(), [rel_plist, rel_png])
            self.assertTrue(dialog.confirm_button.isEnabled())
            self._dispose(dialog)

            # 大小写混合后缀（.PNG + .PLIST）也应完成配对并在弹窗中双向联动勾选
            mixed_png = "sub/MixedBoss.PNG"
            mixed_plist = "sub/MixedBoss.PLIST"
            (source / mixed_png).write_bytes(b"mixed-new-png")
            (source / mixed_plist).write_text("<plist>mixed-new</plist>", encoding="utf-8")
            mixed_dialog = TransferPreviewDialog(
                str(source),
                str(target),
                [mixed_png],
                {mixed_png: "sub"},
                backup_enabled=False,
            )
            mixed_group = mixed_dialog.tree.topLevelItem(0)
            self.assertEqual(mixed_group.childCount(), 2)
            mixed_items = {
                mixed_group.child(index).data(0, Qt.UserRole).casefold(): mixed_group.child(index)
                for index in range(mixed_group.childCount())
            }
            mixed_items[mixed_png.casefold()].setCheckState(0, Qt.Unchecked)
            self.assertEqual(mixed_items[mixed_plist.casefold()].checkState(0), Qt.Unchecked)
            self._dispose(mixed_dialog)

            # 完整控制器闭环：仅勾选 sub/hero.png 触发传输，zip 与目标均成对覆盖并保留旧版
            diffs = [
                FileDiffItem(rel_png, "hero.png", "different", str(source / rel_png), str(target / rel_png), 13),
            ]
            action = ActionDiffItem("sub", "sub", "sub", "different", None, None, diffs)
            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)
            controller.state.action_items = [action]
            controller.action_diff_panel.populate([action], {rel_png})
            controller.state.selected_file_paths = {rel_png}
            controller.source_target_bar.set_backup_config(True, str(backup_dir))

            def confirm_modal() -> None:
                modal = QApplication.activeModalWidget()
                self.assertIsInstance(modal, TransferPreviewDialog)
                self.assertEqual(modal.selected_paths(), [rel_plist, rel_png])
                modal.confirm_button.click()

            QTimer.singleShot(0, confirm_modal)
            controller.show_transfer_preview()
            self._wait_until(
                lambda: (
                    not controller._transfer_in_progress
                    and not controller._scan_in_progress
                    and (target / rel_png).read_bytes() == b"new-atlas-png"
                    and (target / rel_plist).read_text(encoding="utf-8") == "<plist>new</plist>"
                ),
                timeout=8.0,
            )

            zips = list(backup_dir.glob("*.zip"))
            self.assertEqual(len(zips), 1)
            with zipfile.ZipFile(zips[0], "r") as zf:
                self.assertEqual(sorted(zf.namelist()), [rel_plist, rel_png])
                self.assertEqual(zf.read(rel_png), b"old-atlas-png")
                self.assertEqual(zf.read(rel_plist), b"<plist>old</plist>")
            self._wait_threads_released(controller)
            self._dispose(controller)

    def test_end_to_end_transfer_creates_rollback_zip_and_restores_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "角色目标目录"
            backup_dir = root / "备份仓库"

            rel_overwrite = "NW/attack/attack_001.png"
            rel_new = "NW/attack/attack_002.png"
            (source / rel_overwrite).parent.mkdir(parents=True)
            (target / rel_overwrite).parent.mkdir(parents=True)
            (source / rel_overwrite).write_bytes(b"new-frame-1")
            (source / rel_new).write_bytes(b"new-frame-2")
            (target / rel_overwrite).write_bytes(b"old-svn-frame-1")
            os.utime(target / rel_overwrite, (1, 1))  # 兼测 pre-1980 mtime

            diffs = [
                FileDiffItem(rel_overwrite, "attack_001.png", "different", str(source / rel_overwrite), str(target / rel_overwrite), 11),
                FileDiffItem(rel_new, "attack_002.png", "only_left", str(source / rel_new), None, 11),
            ]
            action = ActionDiffItem("NW/attack", "attack", "NW/attack", "different", None, None, diffs)

            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)
            controller.state.action_items = [action]
            controller.action_diff_panel.populate([action], {rel_overwrite, rel_new})
            controller.state.selected_file_paths = {rel_overwrite, rel_new}
            controller.source_target_bar.set_backup_config(True, str(backup_dir))

            def confirm_dialog() -> None:
                dialog = QApplication.activeModalWidget()
                self.assertIsInstance(dialog, TransferPreviewDialog)
                dialog.confirm_button.click()

            QTimer.singleShot(0, confirm_dialog)
            controller.show_transfer_preview()
            self._wait_until(
                lambda: (
                    not controller._transfer_in_progress
                    and not controller._scan_in_progress
                    and (target / rel_overwrite).read_bytes() == b"new-frame-1"
                    and (target / rel_new).read_bytes() == b"new-frame-2"
                ),
                timeout=8.0,
            )

            zips = list(backup_dir.glob("*.zip"))
            self.assertEqual(len(zips), 1)
            self.assertIn("角色目标目录_", zips[0].name)
            with zipfile.ZipFile(zips[0], "r") as zf:
                self.assertEqual(zf.namelist(), [rel_overwrite])
                self.assertEqual(zf.read(rel_overwrite), b"old-svn-frame-1")
                comment = json.loads(zf.comment.decode("utf-8"))
                self.assertEqual(comment["file_count"], 1)
                self.assertEqual(comment["files"], [rel_overwrite])
                # 直接解压即可覆盖回滚到旧版目标文件
                zf.extractall(target)
            self.assertEqual((target / rel_overwrite).read_bytes(), b"old-svn-frame-1")
            self.assertIn("传输前备份完成", controller.transfer_panel.log.toPlainText())
            self._wait_threads_released(controller)
            self._dispose(controller)

    def test_cancel_transfer_mid_backup_leaves_target_and_backup_dir_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            rels = ["SE/idle/01.png", "SE/idle/02.png", "SE/idle/03.png"]
            diffs: list[FileDiffItem] = []
            for rel in rels:
                (source / rel).parent.mkdir(parents=True, exist_ok=True)
                (target / rel).parent.mkdir(parents=True, exist_ok=True)
                (source / rel).write_bytes(f"new-{rel}".encode("utf-8"))
                (target / rel).write_bytes(f"old-{rel}".encode("utf-8"))
                diffs.append(
                    FileDiffItem(rel, Path(rel).name, "different", str(source / rel), str(target / rel), 16)
                )
            action = ActionDiffItem("SE/idle", "idle", "SE/idle", "different", None, None, diffs)

            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)
            controller.state.action_items = [action]
            controller.action_diff_panel.populate([action], set(rels))
            controller.state.selected_file_paths = set(rels)
            controller.source_target_bar.set_backup_config(True, str(backup_dir))

            cancel_issued = threading.Event()
            orig_backup = BackupService.backup_before_transfer
            orig_set_progress = controller.transfer_panel.set_progress

            def cancel_on_first_backup_progress(current: int, total: int, prefix: str = "总进度") -> None:
                orig_set_progress(current, total, prefix=prefix)
                if prefix == "备份进度" and current == 1 and not cancel_issued.is_set():
                    controller.cancel_transfer()
                    cancel_issued.set()

            def gated_backup(service_self, left_root, right_root, bak_dir, job, progress_callback=None, cancel_token=None, started_callback=None):
                def wrapped_progress(idx: int, total: int, rel: str) -> None:
                    if progress_callback is not None:
                        progress_callback(idx, total, rel)
                    if idx == 1:
                        cancel_issued.wait(timeout=3.0)

                return orig_backup(
                    service_self,
                    left_root,
                    right_root,
                    bak_dir,
                    job,
                    progress_callback=wrapped_progress,
                    cancel_token=cancel_token,
                    started_callback=started_callback,
                )

            with (
                patch.object(controller.transfer_panel, "set_progress", side_effect=cancel_on_first_backup_progress),
                patch.object(BackupService, "backup_before_transfer", gated_backup),
                patch.object(QMessageBox, "critical") as mock_critical,
            ):
                controller._start_transfer(rels)
                self._wait_until(lambda: not controller._transfer_in_progress, timeout=8.0)

            self.assertTrue(cancel_issued.is_set())
            self.assertFalse(mock_critical.called)
            self.assertFalse(controller._scan_in_progress)
            self.assertTrue(controller.transfer_panel.transfer_button.isEnabled())
            for rel in rels:
                self.assertEqual((target / rel).read_bytes(), f"old-{rel}".encode("utf-8"))
            self.assertEqual(list(backup_dir.iterdir()), [])
            self._wait_threads_released(controller)
            self._dispose(controller)

    def test_close_event_cancels_active_backup_worker_and_waits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            rels = ["SE/idle/01.png", "SE/idle/02.png"]
            for rel in rels:
                (source / rel).parent.mkdir(parents=True, exist_ok=True)
                (target / rel).parent.mkdir(parents=True, exist_ok=True)
                (source / rel).write_bytes(b"new-bytes")
                (target / rel).write_bytes(b"old-bytes")

            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)
            controller.source_target_bar.set_backup_config(True, str(backup_dir))

            paused_mid_backup = threading.Event()
            orig_backup = BackupService.backup_before_transfer

            def blocking_backup(service_self, left_root, right_root, bak_dir, job, progress_callback=None, cancel_token=None, started_callback=None):
                def wrapped_progress(idx: int, total: int, rel: str) -> None:
                    if progress_callback is not None:
                        progress_callback(idx, total, rel)
                    if idx == 1:
                        paused_mid_backup.set()
                        deadline = time.monotonic() + 5.0
                        while time.monotonic() < deadline and not (cancel_token and cancel_token.is_cancelled()):
                            time.sleep(0.01)

                return orig_backup(
                    service_self,
                    left_root,
                    right_root,
                    bak_dir,
                    job,
                    progress_callback=wrapped_progress,
                    cancel_token=cancel_token,
                    started_callback=started_callback,
                )

            with (
                patch.object(BackupService, "backup_before_transfer", blocking_backup),
                patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as mock_question,
                patch.object(QMessageBox, "critical") as mock_critical,
            ):
                controller._start_transfer(rels)
                self._wait_until(lambda: paused_mid_backup.is_set(), timeout=5.0)
                closed = controller.close()
                self._wait_threads_released(controller)

            self.assertTrue(closed)
            self.assertEqual(mock_question.call_count, 1)
            self.assertFalse(mock_critical.called)
            self.assertFalse(controller._scan_in_progress)
            self.assertEqual(controller._active_threads, [])
            self.assertEqual(list(backup_dir.iterdir()), [])
            for rel in rels:
                self.assertEqual((target / rel).read_bytes(), b"old-bytes")
            controller.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

    def test_disabled_backup_and_all_new_transfer_skip_creating_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            rel_over = "SE/idle/idle_001.png"
            rel_new = "SE/idle/idle_002.png"
            (source / rel_over).parent.mkdir(parents=True)
            (target / rel_over).parent.mkdir(parents=True)
            (source / rel_over).write_bytes(b"new-over")
            (source / rel_new).write_bytes(b"new-only")
            (target / rel_over).write_bytes(b"old-over")

            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)

            # 1) 关闭自动备份时覆盖目标不产生 zip
            controller.source_target_bar.set_backup_config(False, str(backup_dir))
            controller._start_transfer([rel_over])
            self._wait_until(
                lambda: not controller._transfer_in_progress and not controller._scan_in_progress,
                timeout=8.0,
            )
            self.assertEqual((target / rel_over).read_bytes(), b"new-over")
            self.assertFalse(backup_dir.exists())

            # 2) 开启自动备份但全是新增文件时不生成空 zip 且记录跳过日志
            controller.source_target_bar.set_backup_config(True, str(backup_dir))
            controller._start_transfer([rel_new])
            self._wait_until(
                lambda: not controller._transfer_in_progress and not controller._scan_in_progress,
                timeout=8.0,
            )
            self.assertEqual((target / rel_new).read_bytes(), b"new-only")
            self.assertFalse(backup_dir.exists())
            self.assertIn("跳过生成备份", controller.transfer_panel.log.toPlainText())
            self._wait_threads_released(controller)
            self._dispose(controller)

    def test_empty_or_overlapping_backup_dir_blocks_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            rel = "SE/idle/idle_001.png"
            (source / rel).parent.mkdir(parents=True)
            (target / rel).parent.mkdir(parents=True)
            (source / rel).write_bytes(b"new")
            (target / rel).write_bytes(b"old")

            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)

            with patch.object(QMessageBox, "warning") as mock_warning:
                for bad_dir in ("", str(target / "nested_bak"), str(source)):
                    controller.source_target_bar.set_backup_config(True, bad_dir)
                    controller._start_transfer([rel])
                    self.assertFalse(controller._transfer_in_progress)
                    self.assertEqual((target / rel).read_bytes(), b"old")
                self.assertEqual(mock_warning.call_count, 3)

            self._dispose(controller)

    def test_backup_failure_aborts_transfer_protects_target_and_reenables_ui(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            rel = "SE/idle/idle_001.png"
            (source / rel).parent.mkdir(parents=True)
            (target / rel).parent.mkdir(parents=True)
            (source / rel).write_bytes(b"new-bytes")
            (target / rel).write_bytes(b"old-protected")

            diffs = [FileDiffItem(rel, "idle_001.png", "different", str(source / rel), str(target / rel), 9)]
            action = ActionDiffItem("SE/idle", "idle", "SE/idle", "different", None, None, diffs)

            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)
            controller.state.action_items = [action]
            controller.action_diff_panel.populate([action], {rel})
            controller.state.selected_file_paths = {rel}
            controller.source_target_bar.set_backup_config(True, str(backup_dir))

            with (
                patch("workers.transfer_worker.BackupService.backup_before_transfer", side_effect=OSError("disk full")),
                patch.object(QMessageBox, "critical") as mock_critical,
            ):
                controller._start_transfer([rel])
                self._wait_until(
                    lambda: not controller._transfer_in_progress and mock_critical.called,
                    timeout=8.0,
                )

            self.assertEqual((target / rel).read_bytes(), b"old-protected")
            self.assertFalse(controller._scan_in_progress)
            self.assertTrue(controller.transfer_panel.transfer_button.isEnabled())
            self.assertIn("传输前备份失败", controller.transfer_panel.log.toPlainText())

            # 空消息异常（如 OSError()）也必须触发备份失败弹窗与中止，不得误报成功并复扫
            with (
                patch("workers.transfer_worker.BackupService.backup_before_transfer", side_effect=OSError()),
                patch.object(QMessageBox, "critical") as mock_empty_critical,
            ):
                controller._start_transfer([rel])
                self._wait_until(
                    lambda: not controller._transfer_in_progress and mock_empty_critical.called,
                    timeout=8.0,
                )

            self.assertEqual((target / rel).read_bytes(), b"old-protected")
            self.assertFalse(controller._scan_in_progress)
            self.assertIn("OSError", mock_empty_critical.call_args[0][2])
            self._wait_threads_released(controller)
            self._dispose(controller)

    def test_open_backup_dir_handles_existing_and_missing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            existing = base / "existing_bak"
            missing = base / "missing_bak"
            existing.mkdir()

            controller = MainController()
            controller.source_target_bar.set_backup_config(True, str(existing))
            with patch("controllers.main_controller.QDesktopServices.openUrl") as mock_open:
                controller.source_target_bar.backup_bar.open_button.click()
                mock_open.assert_called_once()
                self.assertEqual(Path(mock_open.call_args[0][0].toLocalFile()), existing)

            controller.source_target_bar.set_backup_config(True, str(missing))
            with (
                patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
                patch("controllers.main_controller.QDesktopServices.openUrl") as mock_open,
            ):
                controller.source_target_bar.backup_bar.open_button.click()
                self.assertTrue(missing.is_dir())
                mock_open.assert_called_once()
                self.assertEqual(Path(mock_open.call_args[0][0].toLocalFile()), missing)
            self._dispose(controller)

    @classmethod
    def _wait_until(cls, predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cls.app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("等待 Qt 异步任务超时")

    @classmethod
    def _wait_threads_released(cls, controller, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cls.app.processEvents()
            if not getattr(controller, "_active_threads", None):
                return
            time.sleep(0.01)

    @classmethod
    def _dispose(cls, widget) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            cls.app.processEvents()
            threads = list(getattr(widget, "_active_threads", []) or [])
            if all(_thread_settled(thread) for thread in threads):
                break
            time.sleep(0.01)
        if getattr(widget, "_active_threads", None):
            QTimer.singleShot(0, lambda: cls._dismiss_modal_question(widget))
        widget.close()
        widget.deleteLater()
        cls.app.sendPostedEvents(None, QEvent.DeferredDelete)
        cls.app.processEvents()

    @staticmethod
    def _dismiss_modal_question(widget) -> None:
        modal = QApplication.activeModalWidget()
        if isinstance(modal, QMessageBox) and modal.parent() is widget:
            yes = modal.button(QMessageBox.StandardButton.Yes)
            if yes is not None:
                yes.click()


class PackagingAndIconConfigTests(unittest.TestCase):
    def test_resolve_app_icon_path_platform_behavior(self) -> None:
        with patch.object(app_main.sys, "platform", "win32"):
            self.assertEqual(app_main.resolve_app_icon_path().name, "icon.ico")
        with patch.object(app_main.sys, "platform", "darwin"):
            self.assertEqual(app_main.resolve_app_icon_path().name, "icon.png")

    def test_build_dmg_script_and_macos_workflow_are_valid_and_lf_clean(self) -> None:
        root = Path(__file__).resolve().parent.parent
        build_dmg = root / "build_dmg.sh"
        workflow = root / ".github" / "workflows" / "build-macos.yml"
        gitattributes = root / ".gitattributes"

        self.assertTrue(build_dmg.is_file())
        self.assertTrue(workflow.is_file())
        self.assertTrue(gitattributes.is_file())

        dmg_bytes = build_dmg.read_bytes()
        self.assertFalse(dmg_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", dmg_bytes)
        dmg_text = dmg_bytes.decode("utf-8")
        self.assertTrue(dmg_text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("assets/icon.png", dmg_text)
        self.assertIn("hdiutil create", dmg_text)
        self.assertIn("MMY-ActionFileSync", dmg_text)
        self.assertIn('codesign --force --deep --sign - "$APP_BUNDLE"', dmg_text)
        self.assertIn('codesign --verify --deep --strict "$APP_BUNDLE"', dmg_text)

        wf_bytes = workflow.read_bytes()
        self.assertFalse(wf_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", wf_bytes)
        wf_text = wf_bytes.decode("utf-8")
        self.assertIn("macos-latest", wf_text)
        self.assertIn("macos-15-intel", wf_text)
        self.assertIn("build_dmg.sh", wf_text)
        self.assertIn("workflow_dispatch", wf_text)
        self.assertIn("APP_VERSION", wf_text)
        self.assertIn("GITHUB_REF_NAME", wf_text)
        self.assertIn("\n  release:\n", wf_text)
        self.assertIn("needs: build", wf_text)
        self.assertIn("GH_TOKEN", wf_text)
        self.assertIn("GH_REPO", wf_text)
        self.assertIn("gh release upload", wf_text)
        self.assertIn("build_info-${arch}.txt", wf_text)
        self.assertNotIn("merge-multiple: true", wf_text)

        attr_text = gitattributes.read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", attr_text)
        self.assertIn("*.yml text eol=lf", attr_text)
