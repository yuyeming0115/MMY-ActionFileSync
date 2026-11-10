from __future__ import annotations

import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from models.action_diff import ActionDiffItem

HAS_QT = importlib.util.find_spec("PySide6") is not None

if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QSettings, QTimer, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QMenu, QMessageBox
    from PIL import Image

    from controllers.main_controller import MainController
    from utils.app_info import create_app_settings
    from utils.path_matcher import normalize_path
    from utils.pinned_paths import DEFAULT_PINNED_TARGET_PATHS


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
class PinnedTargetUiTests(unittest.TestCase):
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

    def test_default_pinned_targets_load_and_fit_minimum_and_desktop_window(self) -> None:
        controller = MainController()
        buttons = controller.source_target_bar.pinned_target_bar.buttons()
        self.assertEqual(
            [btn.text() for btn in buttons],
            ["角色输出图", "local-role", "3D角色-原始拆解序列帧"],
        )

        # 最小窗口下不能出现按钮裁切，且右侧常用栏与右侧目标框宽度严格对齐
        controller.resize(controller.minimumSize())
        controller.show()
        self.app.processEvents()
        bar = controller.source_target_bar
        self.assertLessEqual(abs(bar.source_field.width() - bar.target_field.width()), 1)
        self.assertEqual(bar.pinned_target_bar.width(), bar.target_field.width())

        clipped: list[str] = []
        for button in controller.findChildren(QAbstractButton):
            if not button.isVisible() or not button.text():
                continue
            hint = button.sizeHint()
            if button.width() + 2 < hint.width() or button.height() + 2 < hint.height():
                clipped.append(f"{button.text()}({button.width()}×{button.height()} < {hint.width()}×{hint.height()})")
        self.assertFalse(clipped, f"按钮文字被截断: {clipped}")

        # 桌面默认尺寸下仍能展示至少 18 行动作
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

    def test_live_show_pin_unpin_reorder_empty_hint_and_add_button_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_target = Path(temp_dir) / "角色常用输出_Live"
            custom_target.mkdir()
            norm_custom = normalize_path(str(custom_target))

            controller = MainController()
            controller.resize(1360, 820)
            controller.show()
            self.app.processEvents()

            pinned_bar = controller.source_target_bar.pinned_target_bar
            pin_btn = controller.source_target_bar.target_field.pin_button
            self.assertIsNotNone(pin_btn)
            self.assertTrue(pinned_bar.add_button.isVisible())
            self.assertFalse(pinned_bar.add_button.isHidden())

            # 窗口显示后选中目录并点击 📌 固定
            controller.on_paths_changed("", str(custom_target))
            self.app.processEvents()
            self.assertTrue(pin_btn.isEnabled())
            self.assertFalse(pin_btn.isChecked())

            pin_btn.click()
            self.app.processEvents()
            self.assertTrue(pin_btn.isChecked())
            self.assertTrue(pinned_bar.add_button.isVisible())
            buttons = pinned_bar.buttons()
            self.assertEqual(buttons[-1].text(), "角色常用输出_Live")
            self.assertTrue(buttons[-1].isVisible())
            self.assertTrue(buttons[-1].isChecked())

            # 窗口显示后再追加多个长名目录触发换行与 2 行封顶纵向滚动
            for idx in range(5):
                controller.pin_target_path(f"E:/Workspace/Project/Art/Folder_{idx}_SequenceFrames")
            self.app.processEvents()
            self.assertTrue(pinned_bar.add_button.isVisible())
            self.assertEqual(pinned_bar.flow_area.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
            self.assertEqual(pinned_bar.flow_area.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
            line_h = pinned_bar.flow_area._line_height()
            max_two_lines = line_h * 2 + pinned_bar.flow_area.flow().spacing() + 2
            self.assertLessEqual(pinned_bar.flow_area.height(), max_two_lines)

            # 窗口显示后调整顺序，+ 按钮必须保持可见
            controller.move_pinned_target(norm_custom, -1)
            self.app.processEvents()
            self.assertTrue(pinned_bar.add_button.isVisible())

            # 已固定状态下再次点击 📌 应取消固定
            pin_btn.click()
            self.app.processEvents()
            self.assertFalse(pin_btn.isChecked())
            self.assertTrue(pinned_bar.add_button.isVisible())
            self.assertNotIn("角色常用输出_Live", [b.text() for b in pinned_bar.buttons()])

            # 全部取消固定后：空提示可见且与 + 等高；重新固定后空提示消失
            for path in list(controller._pinned_targets):
                controller.unpin_target_path(path)
            self.app.processEvents()
            self.assertEqual(pinned_bar.buttons(), [])
            self.assertTrue(pinned_bar.add_button.isVisible())
            hints = [
                lbl
                for lbl in pinned_bar.flow_area.findChildren(QLabel)
                if lbl.property("pinnedEmptyHint")
            ]
            self.assertEqual(len(hints), 1)
            self.assertTrue(hints[0].isVisible())
            self.assertGreaterEqual(hints[0].minimumHeight(), pinned_bar.add_button.sizeHint().height())

            pin_btn.click()
            self.app.processEvents()
            remaining_hints = [
                lbl
                for lbl in pinned_bar.flow_area.findChildren(QLabel)
                if lbl.property("pinnedEmptyHint")
            ]
            self.assertEqual(remaining_hints, [])
            self.assertTrue(pinned_bar.add_button.isVisible())
            self._dispose(controller)

    def test_pin_unpin_reorder_and_clear_persist_across_restart_including_single_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_target = Path(temp_dir) / "角色单个固定目录"
            custom_target.mkdir()
            norm_custom = normalize_path(str(custom_target))

            first = MainController()
            first.on_paths_changed("", str(custom_target))
            pin_btn = first.source_target_bar.target_field.pin_button
            pin_btn.click()

            # 清空当前视图不会丢失固定目录
            first.clear_all_lists()
            self.assertEqual(first.source_target_bar.paths(), ("", ""))
            self.assertFalse(pin_btn.isEnabled())
            self.assertEqual(len(first.source_target_bar.pinned_target_bar.buttons()), 4)

            first.move_pinned_target(norm_custom, -1)
            self._dispose(first)

            restarted = MainController()
            self.assertEqual(
                [btn.text() for btn in restarted.source_target_bar.pinned_target_bar.buttons()],
                ["角色输出图", "local-role", "角色单个固定目录", "3D角色-原始拆解序列帧"],
            )

            # 只保留 1 个中文目录时，重启后应稳定恢复为单元素，不能退化为字符串或默认值
            for pinned in list(restarted._pinned_targets):
                if pinned != norm_custom:
                    restarted.unpin_target_path(pinned)
            self.assertEqual(restarted._pinned_targets, [norm_custom])
            self._dispose(restarted)

            after_single = MainController()
            self.assertEqual(after_single._pinned_targets, [norm_custom])
            self.assertEqual(
                [b.text() for b in after_single.source_target_bar.pinned_target_bar.buttons()],
                ["角色单个固定目录"],
            )

            # 全部取消固定后，重启应保持为空，不应重新恢复默认值
            after_single.unpin_target_path(norm_custom)
            self.assertEqual(after_single.source_target_bar.pinned_target_bar.buttons(), [])
            self._dispose(after_single)

            after_empty = MainController()
            self.assertEqual(after_empty.source_target_bar.pinned_target_bar.buttons(), [])
            self._dispose(after_empty)

            # QSettings 键被清除或损坏时应安全回落为 3 个默认目录
            settings = create_app_settings()
            settings.remove("paths/pinned_target_json")
            settings.sync()
            reset_defaults = MainController()
            self.assertEqual(reset_defaults._pinned_targets, list(DEFAULT_PINNED_TARGET_PATHS))
            self._dispose(reset_defaults)

            settings.setValue("paths/pinned_target_json", "{corrupted")
            settings.sync()
            corrupted_defaults = MainController()
            self.assertEqual(corrupted_defaults._pinned_targets, list(DEFAULT_PINNED_TARGET_PATHS))
            self._dispose(corrupted_defaults)

    def test_add_button_dialog_handles_cancel_new_and_duplicate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            new_dir = Path(temp_dir) / "new_pinned"
            new_dir.mkdir()
            controller = MainController()
            before = list(controller._pinned_targets)

            with patch("controllers.main_controller.QFileDialog.getExistingDirectory", return_value=""):
                controller.source_target_bar.pinned_target_bar.add_button.click()
            self.assertEqual(controller._pinned_targets, before)

            with patch("controllers.main_controller.QFileDialog.getExistingDirectory", return_value=str(new_dir)):
                controller.source_target_bar.pinned_target_bar.add_button.click()
            self.assertEqual(len(controller._pinned_targets), len(before) + 1)

            # 以反斜杠和小写重复添加，不新增并写提示日志
            dup_variant = str(new_dir).replace("/", "\\").lower()
            with patch("controllers.main_controller.QFileDialog.getExistingDirectory", return_value=dup_variant):
                controller.source_target_bar.pinned_target_bar.add_button.click()
            self.assertEqual(len(controller._pinned_targets), len(before) + 1)
            self.assertIn("已在右侧常用目录中", controller.transfer_panel.log.toPlainText())
            self._dispose(controller)

    def test_context_menu_actions_reorder_switch_unpin_copy_and_open_explorer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            dir_a = base / "ctx_alpha"
            dir_b = base / "ctx_beta"
            dir_c = base / "ctx_gamma"
            for folder in (dir_a, dir_b, dir_c):
                folder.mkdir()

            controller = MainController()
            controller.show()
            self.app.processEvents()
            for default_path in list(controller._pinned_targets):
                controller.unpin_target_path(default_path)
            for folder in (dir_a, dir_b, dir_c):
                controller.pin_target_path(str(folder))
            self.app.processEvents()

            bar = controller.source_target_bar.pinned_target_bar

            def _trigger_context_action(
                button,
                action_text: str | None = None,
                after_open=None,
            ) -> dict[str, bool]:
                states: dict[str, bool] = {}

                def _interact() -> None:
                    popup = QApplication.activePopupWidget()
                    self.assertIsInstance(popup, QMenu)
                    actions = {act.text(): act for act in popup.actions() if not act.isSeparator()}
                    states.update({name: act.isEnabled() for name, act in actions.items()})
                    if after_open is not None:
                        QTimer.singleShot(0, after_open)
                    if action_text:
                        target_action = actions[action_text]
                        popup.close()
                        target_action.trigger()
                    else:
                        popup.close()

                QTimer.singleShot(0, _interact)
                button.customContextMenuRequested.emit(QPoint(2, 2))
                self.app.processEvents()
                return states

            # 首项：左移禁用、右移可用 -> 触发右移
            states_first = _trigger_context_action(bar.buttons()[0], "右移")
            self.assertFalse(states_first["左移"])
            self.assertTrue(states_first["右移"])
            self.assertEqual([b.text() for b in bar.buttons()], ["ctx_beta", "ctx_alpha", "ctx_gamma"])

            # 末项：左移可用、右移禁用
            states_last = _trigger_context_action(bar.buttons()[-1], None)
            self.assertTrue(states_last["左移"])
            self.assertFalse(states_last["右移"])

            # 复制路径
            _trigger_context_action(bar.buttons()[1], "复制路径")
            self.assertEqual(QApplication.clipboard().text(), normalize_path(str(dir_a)))

            # 在文件管理器中打开（存在目录）
            with patch("views.source_target_bar.QDesktopServices.openUrl") as mock_open:
                _trigger_context_action(bar.buttons()[1], "在文件管理器中打开")
            mock_open.assert_called_once_with(QUrl.fromLocalFile(normalize_path(str(dir_a))))

            # 切换到此目录
            _trigger_context_action(bar.buttons()[2], "切换到此目录")
            self.assertEqual(controller.state.right_root_path, normalize_path(str(dir_c)))
            self.assertTrue(controller.source_target_bar.target_field.pin_button.isChecked())

            # 取消固定当前已切换的目录
            _trigger_context_action(bar.buttons()[2], "取消固定")
            self.assertEqual([b.text() for b in bar.buttons()], ["ctx_beta", "ctx_alpha"])
            self.assertFalse(controller.source_target_bar.target_field.pin_button.isChecked())

            # 仅剩 1 项时左右移均禁用；缺失目录在文件管理器中打开弹出“目录不存在”警告
            controller.unpin_target_path(str(dir_b))
            self.app.processEvents()
            dir_a.rmdir()

            seen_warning: list[str] = []

            def _dismiss_warning() -> None:
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox):
                    seen_warning.append(modal.windowTitle())
                    modal.accept()

            states_single = _trigger_context_action(
                bar.buttons()[0],
                "在文件管理器中打开",
                after_open=_dismiss_warning,
            )
            self.assertFalse(states_single["左移"])
            self.assertFalse(states_single["右移"])
            self.assertEqual(seen_warning, ["目录不存在"])
            self._dispose(controller)

    def test_drag_drop_and_auto_match_keep_pin_state_synced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            sources = base / "sources"
            targets = base / "targets"
            source_a = sources / "Hero_A"
            source_b = sources / "Hero_B"
            target_a = targets / "Hero_A"
            target_b = targets / "Hero_B"
            target_other = targets / "Hero_Other"
            for folder in (source_a, source_b, target_a, target_b, target_other):
                folder.mkdir(parents=True)
            frame_in_pinned = target_a / "sample.txt"
            frame_in_pinned.write_text("frame", encoding="utf-8")

            controller = MainController()
            controller.pin_target_path(str(target_a))
            pin_btn = controller.source_target_bar.target_field.pin_button
            bar = controller.source_target_bar.pinned_target_bar

            # 向 target_field 拖入已固定目录下的文件 -> 自动取 .parent 并点亮 📌 与快捷按钮
            _drop_url_onto(controller.source_target_bar.target_field.edit, frame_in_pinned)
            self._wait_until(lambda: not controller._scan_in_progress)
            self.assertEqual(controller.state.right_root_path, normalize_path(str(target_a)))
            self.assertTrue(pin_btn.isEnabled() and pin_btn.isChecked())
            self.assertTrue(bar.buttons()[-1].isChecked())

            # 向 target_field 拖入未固定目录 -> 📌 熄灭
            _drop_url_onto(controller.source_target_bar.target_field.edit, target_other)
            self._wait_until(lambda: not controller._scan_in_progress)
            self.assertTrue(pin_btn.isEnabled() and not pin_btn.isChecked())
            self.assertFalse(bar.buttons()[-1].isChecked())

            # 向预览右侧画布拖入已固定目录 -> 同步激活
            _drop_url_onto(controller.preview_panel.right_preview.canvas, target_a)
            self._wait_until(lambda: not controller._scan_in_progress)
            self.assertEqual(controller.state.right_root_path, normalize_path(str(target_a)))
            self.assertTrue(pin_btn.isChecked() and bar.buttons()[-1].isChecked())

            # 拖入/切换来源自动匹配目标：先换到未固定的 Hero_B，再换回已固定的 Hero_A
            controller.on_paths_changed(str(source_b), controller.state.right_root_path)
            self._wait_until(lambda: not controller._scan_in_progress)
            self.assertEqual(controller.state.right_root_path, normalize_path(str(target_b)))
            self.assertFalse(pin_btn.isChecked())
            self.assertFalse(bar.buttons()[-1].isChecked())

            controller.on_paths_changed(str(source_a), controller.state.right_root_path)
            self._wait_until(lambda: not controller._scan_in_progress)
            self.assertEqual(controller.state.right_root_path, normalize_path(str(target_a)))
            self.assertTrue(pin_btn.isChecked())
            self.assertTrue(bar.buttons()[-1].isChecked())

            # 大小写和反斜杠不同路径也能识别为同一固定目录
            controller.on_paths_changed(str(source_a), str(target_a).replace("/", "\\").lower())
            self._wait_until(lambda: not controller._scan_in_progress)
            self.assertTrue(pin_btn.isChecked())
            self.assertTrue(bar.buttons()[-1].isChecked())
            self._dispose(controller)

    def test_click_pinned_target_switches_right_directory_and_rescans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "sources" / "hero"
            target_a = base / "targets" / "target_alpha"
            target_b = base / "targets" / "target_beta"
            for folder in [
                source / "NW" / "idle",
                source / "SE" / "attack",
                target_a / "NW" / "idle",
                target_b / "SE" / "attack",
            ]:
                folder.mkdir(parents=True)
            Image.new("RGB", (8, 8), "red").save(source / "NW" / "idle" / "idle_001.png")
            Image.new("RGB", (8, 8), "blue").save(source / "SE" / "attack" / "attack_001.png")
            (target_a / "NW" / "idle" / "idle_001.png").write_bytes(
                (source / "NW" / "idle" / "idle_001.png").read_bytes()
            )
            (target_b / "SE" / "attack" / "attack_001.png").write_bytes(
                (source / "SE" / "attack" / "attack_001.png").read_bytes()
            )

            controller = MainController()
            controller.pin_target_path(str(target_a))
            controller.pin_target_path(str(target_b))

            # 来源为空时点击右侧常用目录：切换目标并更新状态提示，刷新按钮仍禁用
            btns_empty = {btn.text(): btn for btn in controller.source_target_bar.pinned_target_bar.buttons()}
            btns_empty["target_alpha"].click()
            self.app.processEvents()
            self.assertEqual(controller.state.right_root_path, normalize_path(str(target_a)))
            self.assertIn("请选择来源目录", controller.source_target_bar.status_label.text())
            self.assertFalse(controller.source_target_bar.refresh_button.isEnabled())
            self.assertTrue(controller.source_target_bar.target_field.pin_button.isChecked())

            controller.on_paths_changed(str(source), str(target_a))
            self._wait_until(lambda: not controller._scan_in_progress, timeout=10.0)
            self._wait_threads_released(controller)

            buttons = {btn.text(): btn for btn in controller.source_target_bar.pinned_target_bar.buttons()}
            self.assertTrue(buttons["target_alpha"].isChecked())
            self.assertFalse(buttons["target_beta"].isChecked())
            self.assertEqual(
                [item.action_name for item in controller.state.action_items if item.status == "only_left"],
                ["attack"],
            )

            # 一键点击另一个常用目录：立即切换右侧目录并自动重扫
            buttons["target_beta"].click()
            self._wait_until(
                lambda: (
                    not controller._scan_in_progress
                    and controller.state.right_root_path == normalize_path(str(target_b))
                    and [item.action_name for item in controller.state.action_items if item.status == "only_left"]
                    == ["idle"]
                ),
                timeout=10.0,
            )
            self._wait_threads_released(controller)

            buttons = {btn.text(): btn for btn in controller.source_target_bar.pinned_target_bar.buttons()}
            self.assertEqual(controller.source_target_bar.paths()[1], normalize_path(str(target_b)))
            self.assertTrue(buttons["target_beta"].isChecked())
            self.assertFalse(buttons["target_alpha"].isChecked())
            self.assertTrue(controller.source_target_bar.target_field.pin_button.isChecked())

            # 再次点击当前已激活的常用目录按钮：视觉选中态不能意外熄灭
            buttons["target_beta"].click()
            self.app.processEvents()
            self.assertTrue(buttons["target_beta"].isChecked())

            # 忙碌态应禁用右侧常用栏和钉固按钮，且扫描期间直接调用切换会被忽略
            controller.source_target_bar.set_busy(True)
            self.assertFalse(controller.source_target_bar.pinned_target_bar.isEnabled())
            self.assertFalse(controller.source_target_bar.target_field.pin_button.isEnabled())
            controller.source_target_bar.set_busy(False)
            controller._scan_in_progress = True
            controller.switch_to_pinned_target(str(target_a))
            self.assertEqual(controller.state.right_root_path, normalize_path(str(target_b)))
            controller._scan_in_progress = False
            self._dispose(controller)

            # 重启恢复路径（compare_result=None）后，点击当前已激活常用目录按钮应自动触发对比扫描
            restarted = MainController()
            self.assertIsNone(restarted.state.compare_result)
            restarted_btns = {btn.text(): btn for btn in restarted.source_target_bar.pinned_target_bar.buttons()}
            self.assertTrue(restarted_btns["target_beta"].isChecked())
            restarted_btns["target_beta"].click()
            self._wait_until(lambda: restarted.state.compare_result is not None and not restarted._scan_in_progress)
            self._wait_threads_released(restarted)
            self._dispose(restarted)

    def test_click_missing_pinned_target_prompts_to_unpin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gone = Path(temp_dir) / "removed_dir"
            gone.mkdir()
            controller = MainController()
            controller.pin_target_path(str(gone))
            gone.rmdir()

            btn = controller.source_target_bar.pinned_target_bar.buttons()[-1]
            self.assertEqual(btn.text(), "removed_dir")

            # 先选 No：目录应保留在常用栏，且按钮不能停留在 checked 状态
            def reject_remove() -> None:
                modal = QApplication.activeModalWidget()
                self.assertIsInstance(modal, QMessageBox)
                modal.button(QMessageBox.StandardButton.No).click()

            QTimer.singleShot(0, reject_remove)
            btn.click()
            self.app.processEvents()
            self.assertEqual(controller.state.right_root_path, "")
            self.assertFalse(btn.isChecked())
            self.assertIn(
                "removed_dir",
                [b.text() for b in controller.source_target_bar.pinned_target_bar.buttons()],
            )

            # 再选 Yes：从常用栏移除
            def accept_remove() -> None:
                modal = QApplication.activeModalWidget()
                self.assertIsInstance(modal, QMessageBox)
                modal.button(QMessageBox.StandardButton.Yes).click()

            QTimer.singleShot(0, accept_remove)
            btn.click()
            self.app.processEvents()

            self.assertEqual(controller.state.right_root_path, "")
            self.assertNotIn(
                "removed_dir",
                [b.text() for b in controller.source_target_bar.pinned_target_bar.buttons()],
            )
            self._dispose(controller)

    def test_many_pinned_targets_wrap_without_clipping(self) -> None:
        controller = MainController()
        for idx in range(6):
            controller.pin_target_path(f"E:/Workspace/Project/Art/Folder_{idx}_SequenceFrames")
        controller.resize(controller.minimumSize())
        controller.show()
        self.app.processEvents()

        flow_area = controller.source_target_bar.pinned_target_bar.flow_area
        line_h = flow_area._line_height()
        max_two_lines = line_h * 2 + flow_area.flow().spacing() + 2
        self.assertLessEqual(flow_area.height(), max_two_lines)
        self.assertEqual(flow_area.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

        clipped: list[str] = []
        for button in controller.findChildren(QAbstractButton):
            if not button.isVisible() or not button.text():
                continue
            hint = button.sizeHint()
            if button.width() + 2 < hint.width() or button.height() + 2 < hint.height():
                clipped.append(f"{button.text()}({button.width()}×{button.height()} < {hint.width()}×{hint.height()})")
        self.assertFalse(clipped, f"换行后按钮文字被截断: {clipped}")
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
            if not getattr(controller, "_active_threads", None) and not getattr(controller, "_threads", None):
                return
            time.sleep(0.01)

    @classmethod
    def _dispose(cls, widget) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            cls.app.processEvents()
            threads = list(getattr(widget, "_active_threads", []) or []) + list(
                getattr(widget, "_threads", []) or []
            )
            if all(_thread_settled(thread) for thread in threads):
                break
            time.sleep(0.01)
        if getattr(widget, "_active_threads", None) or getattr(widget, "_threads", None):
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


if __name__ == "__main__":
    unittest.main()
