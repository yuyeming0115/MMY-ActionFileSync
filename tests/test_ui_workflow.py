from __future__ import annotations

import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path

from models.action_diff import ActionDiffItem, FileDiffItem
from models.preview_item import PreviewItem


HAS_QT = importlib.util.find_spec("PySide6") is not None

if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QItemSelectionModel, QSettings, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QApplication, QHeaderView, QMessageBox
    from PIL import Image

    from controllers.main_controller import MainController
    from utils.app_info import create_app_settings
    from utils.path_matcher import normalize_path
    from views.action_diff_panel import ActionDiffPanel
    from views.main_window import MainWindow
    from views.preview_panel import SinglePreviewWidget
    from views.redundancy_dialog import RedundancyDialog
    from views.transfer_panel import TransferPanel
    from views.transfer_preview_dialog import TransferPreviewDialog


def _thread_settled(thread) -> bool:
    """线程已结束或其 C++ 对象已被 Qt 删除（簿记 lambda 尚未送达）都视为收尾完成。"""
    try:
        return not thread.isRunning()
    except RuntimeError:
        return True


@unittest.skipUnless(HAS_QT, "需要安装 PySide6")
class UiWorkflowTests(unittest.TestCase):
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

    def test_action_selection_survives_search_filter(self) -> None:
        files = [
            FileDiffItem("player/idle/idle_001.png", "idle_001.png", "different", "source", "target", 100),
            FileDiffItem("player/idle/idle_002.png", "idle_002.png", "only_left", "source", None, 200),
        ]
        action = ActionDiffItem("player/idle", "idle", "player/idle", "different", None, None, files)
        panel = ActionDiffPanel()
        panel.populate([action])

        panel.select_changed()
        selected_before = set(panel.selected_paths)
        panel.search_edit.setText("missing")
        panel.search_edit.setText("idle")

        self.assertEqual(selected_before, {item.relative_path for item in files})
        self.assertEqual(panel.selected_paths, selected_before)
        self._dispose(panel)

    def test_ctrl_shift_style_highlight_can_select_multiple_actions(self) -> None:
        actions = [
            ActionDiffItem(
                action_id=name,
                action_name=name,
                relative_path=f"player/{name}",
                status="different",
                source_node=None,
                target_node=None,
                file_diffs=[
                    FileDiffItem(
                        f"player/{name}/{name}_001.png",
                        f"{name}_001.png",
                        "different",
                        "source",
                        "target",
                        100,
                    )
                ],
            )
            for name in ["attack", "idle", "run"]
        ]
        panel = ActionDiffPanel()
        panel.populate(actions)
        self.assertEqual(panel.model.item(0, 1).text(), "→")
        self.assertEqual(panel.model.item(0, 2).text(), "player")
        self.assertEqual(panel.model.item(0, 3).text(), "attack")
        self.assertEqual(panel.model.columnCount(), 7)
        selection = panel.view.selectionModel()
        selection.select(
            panel.proxy.index(0, 0),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        selection.select(
            panel.proxy.index(1, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )

        panel.toggle_highlighted()

        self.assertEqual(
            panel.selected_paths,
            {"player/attack/attack_001.png", "player/idle/idle_001.png"},
        )
        self._dispose(panel)

    def test_select_changed_checks_only_changed_actions(self) -> None:
        def make_action(name: str, file_status: str) -> ActionDiffItem:
            return ActionDiffItem(
                action_id=f"NW/{name}",
                action_name=name,
                relative_path=f"NW/{name}",
                status=file_status,
                source_node=None,
                target_node=None,
                file_diffs=[
                    FileDiffItem(
                        f"NW/{name}/{name}_001.png",
                        f"{name}_001.png",
                        file_status,
                        "source" if file_status != "same" else None,
                        "target" if file_status != "only_left" else None,
                        100,
                    )
                ],
            )

        actions = [
            make_action("idle", "different"),
            make_action("run", "only_left"),
            make_action("walk", "same"),
        ]
        panel = ActionDiffPanel()
        panel.populate(actions)
        panel.set_selected_paths({"NW/idle/idle_001.png"})

        panel.select_changed()

        self.assertEqual(
            panel.selected_paths,
            {"NW/idle/idle_001.png", "NW/run/run_001.png"},
        )
        self._dispose(panel)

    def test_log_levels_use_standard_colors(self) -> None:
        panel = TransferPanel()
        panel.append_log("文件完成", "success")
        panel.append_log("文件失败", "error")
        colors: list[str] = []
        block = panel.log.document().begin()
        while block.isValid():
            iterator = block.begin()
            if not iterator.atEnd():
                colors.append(iterator.fragment().charFormat().foreground().color().name())
            block = block.next()

        self.assertEqual(colors, ["#4caf50", "#ff6b5e"])
        self._dispose(panel)

    def test_file_rows_are_created_when_action_expands(self) -> None:
        file_item = FileDiffItem("idle/idle_001.png", "idle_001.png", "different", "source", "target", 100)
        action = ActionDiffItem("idle", "idle", "idle", "different", None, None, [file_item])
        panel = ActionDiffPanel()
        panel.populate([action])
        source_parent = panel.model.item(0, 0)
        self.assertEqual(source_parent.child(0, 0).data(Qt.UserRole + 1), "placeholder")

        panel._on_expanded(panel.proxy.index(0, 0))

        self.assertEqual(source_parent.rowCount(), 1)
        self.assertEqual(source_parent.child(0, 1).text(), "→")
        self.assertEqual(source_parent.child(0, 3).text(), "idle_001.png")
        self._dispose(panel)

    def test_direction_buttons_toggle_all_actions_in_direction(self) -> None:
        actions = [
            ActionDiffItem(
                action_id=f"{direction}-{name}",
                action_name=name,
                relative_path=f"{direction}/{name}",
                status="different",
                source_node=None,
                target_node=None,
                file_diffs=[
                    FileDiffItem(
                        f"{direction}/{name}/{name}_001.png",
                        f"{name}_001.png",
                        "different",
                        "source",
                        "target",
                        100,
                    )
                ],
            )
            for direction, name in [("NW", "idle"), ("SE", "idle"), ("E", "run")]
        ]
        panel = ActionDiffPanel()
        panel.populate(actions)

        layout = panel.direction_buttons_layout
        buttons = [layout.itemAt(index).widget() for index in range(layout.count())]
        self.assertEqual([button.text() for button in buttons], ["E", "NW", "SE"])
        self.assertFalse(panel.direction_buttons_row.isHidden())

        nw_button = buttons[1]
        nw_button.click()
        self.assertEqual(panel.selected_paths, {"NW/idle/idle_001.png"})
        self.assertTrue(nw_button.isChecked())

        nw_button.click()
        self.assertEqual(panel.selected_paths, set())
        self.assertFalse(nw_button.isChecked())
        self._dispose(panel)

    def test_direction_row_hidden_for_flat_action_structure(self) -> None:
        files = [FileDiffItem("idle/idle_001.png", "idle_001.png", "different", "source", "target", 100)]
        action = ActionDiffItem("idle", "idle", "idle", "different", None, None, files)
        panel = ActionDiffPanel()
        panel.populate([action])

        self.assertTrue(panel.direction_buttons_row.isHidden())
        self.assertEqual(panel.direction_buttons_layout.count(), 0)
        self._dispose(panel)

    @staticmethod
    def _make_direction_action(direction: str, name: str, status: str) -> ActionDiffItem:
        return ActionDiffItem(
            action_id=f"{direction}/{name}",
            action_name=name,
            relative_path=f"{direction}/{name}",
            status=status,
            source_node=None,
            target_node=None,
            file_diffs=[
                FileDiffItem(
                    f"{direction}/{name}/{name}_001.png",
                    f"{name}_001.png",
                    status,
                    "source" if status != "only_right" else None,
                    "target" if status != "only_left" else None,
                    100,
                )
            ],
        )

    def test_direction_compass_context_marks_availability_and_changes(self) -> None:
        actions = [
            self._make_direction_action("SE", "idle", "different"),
            self._make_direction_action("N", "idle", "same"),
            self._make_direction_action("W", "idle", "only_left"),
            self._make_direction_action("W", "run", "same"),
        ]
        panel = ActionDiffPanel()
        panel.populate(actions)
        widget = SinglePreviewWidget("来源｜新动作", "source")
        widget.set_direction_context("SE", "idle", panel.directions_for("idle"), panel.all_directions())

        compass = widget.compass
        buttons = {direction: compass.button_for(direction) for direction in ("SE", "N", "W")}
        self.assertTrue(compass.isVisibleTo(widget.canvas))
        self.assertTrue(buttons["SE"].isEnabled() and buttons["SE"].isChecked())
        self.assertEqual(buttons["SE"].change_color, "#e0a040")
        self.assertTrue(buttons["N"].isEnabled() and not buttons["N"].isChecked())
        self.assertEqual(buttons["N"].toolTip(), "预览 N/idle")
        self.assertIsNone(buttons["N"].change_color)
        self.assertTrue(buttons["W"].isEnabled())
        self.assertEqual(buttons["W"].change_color, "#4caf50")
        for direction in ("NW", "NE", "E", "SW", "S"):
            self.assertTrue(compass.button_for(direction).isHidden())

        received: list[str] = []
        widget.direction_clicked.connect(received.append)
        buttons["N"].click()
        self.assertEqual(received, ["N"])

        # run 只在 W 下存在：其余方向禁用且不可触发
        widget.set_direction_context("W", "run", panel.directions_for("run"), panel.all_directions())
        self.assertTrue(buttons["W"].isEnabled() and buttons["W"].isChecked())
        self.assertFalse(buttons["N"].isEnabled())
        received.clear()
        buttons["N"].click()
        self.assertEqual(received, [])

        # 无上下文（未选动作/无方向层）时整层隐藏
        widget.set_direction_context("", "", {}, set())
        self.assertTrue(compass.isHidden())
        self._dispose(panel)
        self._dispose(widget)

    def test_direction_compass_matches_case_insensitive_directions(self) -> None:
        actions = [self._make_direction_action("nw", "idle", "different")]
        panel = ActionDiffPanel()
        panel.populate(actions)
        widget = SinglePreviewWidget("来源｜新动作", "source")
        widget.set_direction_context("nw", "idle", panel.directions_for("idle"), panel.all_directions())

        nw = widget.compass.button_for("NW")
        self.assertTrue(nw.isVisibleTo(widget.canvas) and nw.isEnabled())
        received: list[str] = []
        widget.direction_clicked.connect(received.append)
        nw.click()
        self.assertEqual(received, ["NW"])
        self._dispose(panel)
        self._dispose(widget)

    def test_compass_button_hit_by_real_mouse_click(self) -> None:
        """真实鼠标命中测试：覆盖层绝不能挡住方向按钮的点击。

        QTest 的 QWidget 重载会把事件直接发给目标控件、绕过命中测试，测不出
        覆盖层挡点击的问题（WA_TransparentForMouseEvents 就曾导致整棵子树
        收不到真实点击）；必须走 windowHandle 的窗口级分发路径。
        """
        widget = SinglePreviewWidget("来源｜新动作", "source")
        widget.set_direction_context("NW", "attack", {"NW": "same", "N": "same"}, {"NW", "N"})
        widget.resize(420, 480)
        widget.show()
        self.app.processEvents()

        button = widget.compass.button_for("N")
        received: list[str] = []
        widget.direction_clicked.connect(received.append)
        window_pos = widget.mapFromGlobal(button.mapToGlobal(button.rect().center()))
        QTest.mouseClick(widget.windowHandle(), Qt.LeftButton, Qt.NoModifier, window_pos)
        self.assertEqual(received, ["N"])
        self._dispose(widget)

    def test_jump_to_action_relaxes_filter_and_selects_row(self) -> None:
        actions = [
            self._make_direction_action("NW", "idle", "different"),
            self._make_direction_action("SE", "idle", "same"),
        ]
        panel = ActionDiffPanel()
        received: list[str] = []
        relaxed: list[str] = []
        panel.action_selected.connect(received.append)
        panel.jump_filter_relaxed.connect(relaxed.append)
        panel.populate(actions)  # 默认「待更新」过滤：SE/idle 被隐藏
        received.clear()

        self.assertTrue(panel.jump_to_action("SE/idle"))
        self.assertEqual(received, ["SE/idle"])
        self.assertEqual(relaxed, ["SE/idle"])
        self.assertEqual(panel.proxy.status_filter, "all")
        self.assertTrue(panel.filter_buttons["all"].isChecked())

        # casefold 定位；重复跳转同一行不重复发信号
        self.assertTrue(panel.jump_to_action("se/idle"))
        self.assertEqual(received, ["SE/idle"])
        self.assertEqual(relaxed, ["SE/idle"])

        self.assertFalse(panel.jump_to_action("N/idle"))
        self._dispose(panel)

    def test_status_filter_hides_same_action_despite_placeholder_row(self) -> None:
        panel = ActionDiffPanel()
        panel.populate(
            [
                self._make_direction_action("NW", "idle", "different"),
                self._make_direction_action("SE", "idle", "same"),
            ]
        )

        # 「待更新」过滤下 SE/idle 必须隐藏（占位子行不再无条件放行）
        self.assertEqual(panel.proxy.rowCount(), 1)

        # 父动作可见时，其文件子行正常显示
        panel.view.expand(panel.proxy.index(0, 0))
        self.assertEqual(panel.proxy.rowCount(panel.proxy.index(0, 0)), 1)

        panel._apply_status_filter("all")
        self.assertEqual(panel.proxy.rowCount(), 2)
        self._dispose(panel)

    def test_identical_actions_stay_visible_and_select_first(self) -> None:
        """两侧目录相同（全部「已一致」）时清单不能空，否则预览区没动作可选。"""
        actions = [
            self._make_direction_action("SE", "idle", "same"),
            self._make_direction_action("N", "block", "same"),
        ]
        panel = ActionDiffPanel()
        received: list[str] = []
        panel.action_selected.connect(received.append)
        panel.populate(actions)

        self.assertEqual(panel.proxy.rowCount(), 2)
        self.assertEqual(panel.proxy.status_filter, "all")
        self.assertTrue(panel.filter_buttons["all"].isChecked())
        self.assertEqual(received, ["SE/idle"])
        self.assertTrue(panel._auto_relaxed)
        self._dispose(panel)

    def test_auto_relaxed_filter_restores_transfer_when_changes_appear(self) -> None:
        """自动放宽只是兜底：重新扫描出现待更新时切回「待更新」过滤。"""
        panel = ActionDiffPanel()
        panel.populate([self._make_direction_action("SE", "idle", "same")])
        self.assertEqual(panel.proxy.status_filter, "all")

        panel.populate(
            [
                self._make_direction_action("SE", "idle", "different"),
                self._make_direction_action("N", "block", "same"),
            ]
        )

        self.assertEqual(panel.proxy.status_filter, "transfer")
        self.assertEqual(panel.proxy.rowCount(), 1)
        self.assertFalse(panel._auto_relaxed)
        self._dispose(panel)

    def test_rescan_keeps_current_action_selected(self) -> None:
        """刷新后停在原动作上，预览才会跟着重新加载，而不是悄悄跳回第一行。"""
        actions = [
            self._make_direction_action("SE", "idle", "different"),
            self._make_direction_action("N", "block", "different"),
        ]
        panel = ActionDiffPanel()
        received: list[str] = []
        panel.action_selected.connect(received.append)
        panel.populate(actions)
        panel.view.setCurrentIndex(panel.proxy.index(1, 0))
        self.assertEqual(received[-1], "N/block")

        received.clear()
        panel.populate(actions)
        self.assertEqual(received, ["N/block"])
        self._dispose(panel)

    def test_direction_and_action_buttons_unstick_when_nothing_transferable(self) -> None:
        actions = [
            self._make_direction_action("SE", "idle", "same"),
            self._make_direction_action("N", "block", "same"),
        ]
        panel = ActionDiffPanel()
        panel.populate(actions)
        direction_buttons = [
            panel.direction_buttons_layout.itemAt(index).widget()
            for index in range(panel.direction_buttons_layout.count())
        ]
        action_buttons = [
            panel.action_buttons_layout.itemAt(index).widget()
            for index in range(panel.action_buttons_layout.count())
        ]

        # 全部已一致（无可传输文件）：点击不应把按钮留在 checked 视觉态
        direction_buttons[0].click()
        action_buttons[0].click()
        self.assertFalse(direction_buttons[0].isChecked())
        self.assertFalse(action_buttons[0].isChecked())
        self.assertEqual(panel.selected_paths, set())
        self._dispose(panel)

    def test_compass_toggle_persists_across_restart(self) -> None:
        settings = create_app_settings()
        settings.clear()
        settings.setValue("preview/compass_visible", False)
        settings.sync()
        window = MainWindow()
        self.assertFalse(window.preview_panel.compass_visible)
        self.assertFalse(window.preview_panel.left_preview.compass.user_visible)

        window.preview_panel.set_compass_visible(True)
        self.assertTrue(window.preview_panel.left_preview.compass.user_visible)
        self._dispose(window)
        settings.clear()
        settings.sync()

    def test_transfer_preview_columns_are_resizable_and_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            action = source / "NW" / "idle"
            action.mkdir(parents=True)
            (action / "idle_001.png").write_bytes(b"frame")
            paths = ["NW/idle/idle_001.png"]
            action_map = {paths[0]: "NW/idle"}

            dialog = TransferPreviewDialog(str(source), str(target), paths, action_map)
            header = dialog.tree.header()
            for column in range(4):
                self.assertEqual(header.sectionResizeMode(column), QHeaderView.Interactive)

            dialog.tree.setColumnWidth(0, 180)
            dialog.tree.setColumnWidth(1, 700)
            dialog.done(1)

            reopened = TransferPreviewDialog(str(source), str(target), paths, action_map)
            self.assertEqual(reopened.tree.columnWidth(0), 180)
            self.assertEqual(reopened.tree.columnWidth(1), 700)
            self._dispose(reopened)
            self._dispose(dialog)

    def test_transfer_preview_can_exclude_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            action = source / "player" / "idle"
            action.mkdir(parents=True)
            for name in ["idle_001.png", "idle_002.png"]:
                (action / name).write_bytes(name.encode("ascii"))
            paths = ["player/idle/idle_001.png", "player/idle/idle_002.png"]
            dialog = TransferPreviewDialog(
                str(source),
                str(target),
                paths,
                {path: "player/idle" for path in paths},
            )
            dialog.tree.topLevelItem(0).child(1).setCheckState(0, Qt.Unchecked)

            self.assertEqual(dialog.selected_paths(), ["player/idle/idle_001.png"])
            self._dispose(dialog)

    def test_transfer_preview_confirmation_starts_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            relative = "player/idle/idle_001.png"
            source_file = source / relative
            target_file = target / relative
            source_file.parent.mkdir(parents=True)
            target_file.parent.mkdir(parents=True)
            source_file.write_bytes(b"new-action-content")
            target_file.write_bytes(b"old-svn-content")
            os.utime(target_file, (1, 1))
            old_mtime = target_file.stat().st_mtime
            file_item = FileDiffItem(
                relative,
                "idle_001.png",
                "different",
                str(source_file),
                str(target_file),
                source_file.stat().st_size,
            )
            action = ActionDiffItem(
                "player/idle",
                "idle",
                "player/idle",
                "different",
                None,
                None,
                [file_item],
            )
            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)
            controller.state.action_items = [action]
            controller.action_diff_panel.populate([action], {relative})
            controller.state.selected_file_paths = {relative}
            backup_dir = root / "backups"
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
                    and target_file.read_bytes() == source_file.read_bytes()
                ),
                timeout=8.0,
            )

            self.assertGreater(target_file.stat().st_mtime, old_mtime)
            self.assertIn("成功 1", controller.transfer_panel.status_label.text())
            self.assertTrue(controller.transfer_panel.details_button.isChecked())
            self.assertIn("开始传输", controller.transfer_panel.log.toPlainText())
            self.assertIn("完成", controller.transfer_panel.log.toPlainText())
            self._wait_threads_released(controller)
            controller.settings.clear()
            controller.settings.sync()
            self._dispose(controller)

    def test_main_window_and_frame_mapping_smoke(self) -> None:
        window = MainWindow()
        self.assertGreaterEqual(window.minimumWidth(), 1100)
        self.assertEqual(window.main_splitter.count(), 2)
        self.assertEqual(SinglePreviewWidget._index_for_progress(0.5, 10), 4)
        self._dispose(window)

    def test_preview_canvases_stay_aligned_with_different_path_lengths(self) -> None:
        window = MainWindow()
        window.preview_panel.set_preview(
            "left",
            PreviewItem(
                side="left",
                relative_path="player/idle",
                source_path="D:/very/long/source/path/with/many/nested/folders/player/idle",
                cache_path=None,
                status="error",
            ),
        )
        window.preview_panel.set_preview(
            "right",
            PreviewItem(
                side="right",
                relative_path="player/idle",
                source_path="D:/SVN/idle",
                cache_path=None,
                status="error",
            ),
        )
        window.resize(1440, 900)
        window.show()
        self.app.processEvents()

        left_canvas = window.preview_panel.left_preview.canvas
        right_canvas = window.preview_panel.right_preview.canvas
        self.assertLessEqual(abs(left_canvas.width() - right_canvas.width()), 1)
        self.assertEqual(left_canvas.height(), right_canvas.height())
        self.assertEqual(
            window.preview_panel.left_preview.layout().contentsMargins(),
            window.preview_panel.right_preview.layout().contentsMargins(),
        )
        self._dispose(window)

    def test_recent_directories_survive_clear_and_restore_on_restart(self) -> None:
        settings = create_app_settings()
        settings.clear()
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            target = Path(temp_dir) / "target"
            source.mkdir()
            target.mkdir()

            first = MainController()
            first.on_paths_changed(str(source), str(target))
            self._wait_until(lambda: not first._scan_in_progress, timeout=10.0)
            self._wait_threads_released(first)
            self._dispose(first)

            restored = MainController()
            self.assertEqual(
                restored.source_target_bar.paths(),
                (normalize_path(str(source)), normalize_path(str(target))),
            )
            restored.clear_all_lists()
            self.assertEqual(restored.source_target_bar.paths(), ("", ""))
            self._dispose(restored)

            restored_after_clear = MainController()
            self.assertEqual(
                restored_after_clear.source_target_bar.paths(),
                (normalize_path(str(source)), normalize_path(str(target))),
            )
            self._dispose(restored_after_clear)

        settings.clear()
        settings.sync()

    def test_source_change_auto_matches_same_name_target(self) -> None:
        settings = create_app_settings()
        settings.clear()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            targets = base / "targets"
            (targets / "A_body").mkdir(parents=True)
            (targets / "B_body").mkdir()
            (targets / "group" / "C_body").mkdir(parents=True)
            sources = base / "sources"
            (sources / "B_body").mkdir(parents=True)
            (sources / "C_body").mkdir()
            (sources / "D_body").mkdir()

            controller = MainController()

            def wait_scan_idle() -> None:
                # 业务完成看 _scan_in_progress（硬等待）；线程簿记清空是尽力而为
                self._wait_until(lambda: not controller._scan_in_progress, timeout=10.0)
                self._wait_threads_released(controller)

            # 手动设置一次目标，控制器应记住其父目录作为目标根
            controller.on_paths_changed(str(sources), str(targets / "A_body"))
            wait_scan_idle()
            self.assertEqual(
                normalize_path(str(targets)),
                controller._target_root(),
            )

            # 父目录直查：来源换成 B_body 后目标自动切换为 targets/B_body
            controller.on_paths_changed(str(sources / "B_body"), str(targets / "A_body"))
            wait_scan_idle()
            self.assertEqual(controller.state.right_root_path, normalize_path(str(targets / "B_body")))
            self.assertEqual(controller.source_target_bar.paths()[1], normalize_path(str(targets / "B_body")))

            # 递归兜底：父目录下没有 C_body，但在目标根的子目录里能找到
            controller.on_paths_changed(str(sources / "C_body"), str(targets / "B_body"))
            wait_scan_idle()
            self.assertEqual(
                controller.state.right_root_path,
                normalize_path(str(targets / "group" / "C_body")),
            )

            # 未命中：保留原目标，不触发误匹配
            controller.on_paths_changed(str(sources / "D_body"), str(targets / "group" / "C_body"))
            wait_scan_idle()
            self.assertEqual(controller.state.right_root_path, normalize_path(str(targets / "group" / "C_body")))
            self._dispose(controller)

        settings.clear()
        settings.sync()

    def test_visible_controls_fit_at_minimum_window_size(self) -> None:
        window = MainWindow()
        window.resize(window.minimumSize())
        window.show()
        self.app.processEvents()
        clipped: list[str] = []
        for button in window.findChildren(QAbstractButton):
            if not button.isVisible() or not button.text():
                continue
            hint = button.sizeHint()
            if button.width() + 2 < hint.width() or button.height() + 2 < hint.height():
                clipped.append(f"{button.text()}({button.width()}×{button.height()} < {hint.width()}×{hint.height()})")
        self.assertFalse(clipped, f"按钮文字可能被截断: {clipped}")
        self.assertGreaterEqual(window.main_splitter.sizes()[0], 360)
        self.assertGreaterEqual(window.main_splitter.sizes()[1], 600)
        self.assertLessEqual(window.main_splitter.handleWidth(), 6)
        self.assertGreaterEqual(window.action_container.layout().contentsMargins().right(), 10)
        self.assertGreaterEqual(window.preview_container.layout().contentsMargins().left(), 10)
        self._dispose(window)

    def test_desktop_layout_shows_at_least_eighteen_action_rows(self) -> None:
        window = MainWindow()
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
        window.action_diff_panel.populate(actions)
        window.action_diff_panel.filter_buttons["all"].click()
        window.resize(1440, 900)
        window.show()
        self.app.processEvents()
        view = window.action_diff_panel.view
        viewport_rect = view.viewport().rect()
        visible_rows = sum(
            view.visualRect(window.action_diff_panel.proxy.index(row, 0)).intersects(viewport_rect)
            for row in range(window.action_diff_panel.proxy.rowCount())
        )
        self.assertGreaterEqual(visible_rows, 18)
        self._dispose(window)

    def test_scan_select_transfer_and_rescan_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            source_idle = source / "player" / "idle"
            target_idle = target / "player" / "idle"
            source_idle.mkdir(parents=True)
            target_idle.mkdir(parents=True)

            for index, color in [(1, "red"), (2, "green")]:
                Image.new("RGB", (16, 16), color).save(source_idle / f"idle_{index:03d}.png")
            (target_idle / "idle_001.png").write_bytes((source_idle / "idle_001.png").read_bytes())
            Image.new("RGB", (16, 16), "blue").save(target_idle / "idle_002.png")
            source_mtime = (source_idle / "idle_002.png").stat().st_mtime
            os.utime(target_idle / "idle_002.png", (source_mtime - 10, source_mtime - 10))

            controller = MainController()
            controller.on_paths_changed(str(source), str(target))
            self._wait_until(lambda: not controller._scan_in_progress)

            self.assertEqual([item.action_name for item in controller.state.action_items], ["idle"])
            self.assertFalse(controller.state.selected_file_paths)
            controller.action_diff_panel.view.setCurrentIndex(controller.action_diff_panel.proxy.index(0, 0))
            controller.action_diff_panel.select_changed()
            selected = set(controller.state.selected_file_paths)
            self.assertEqual(selected, {"player/idle/idle_002.png"})
            backup_dir = root / "backups"
            controller.source_target_bar.set_backup_config(True, str(backup_dir))

            controller._start_transfer(sorted(selected))
            self._wait_until(
                lambda: (
                    not controller._transfer_in_progress
                    and not controller._scan_in_progress
                    and not controller.state.selected_file_paths
                    and (target_idle / "idle_002.png").read_bytes()
                    == (source_idle / "idle_002.png").read_bytes()
                ),
                timeout=8.0,
            )

            self.assertEqual(
                (target_idle / "idle_002.png").read_bytes(),
                (source_idle / "idle_002.png").read_bytes(),
            )
            self.assertFalse(controller.state.selected_file_paths)
            self._wait_threads_released(controller)
            controller.clear_all_lists()
            controller.settings.clear()
            controller.settings.sync()
            self._dispose(controller)

    def test_same_directory_scan_previews_animation(self) -> None:
        """左右拖入同一目录：清单照常列出动作，两侧预览都要出动画帧。"""
        settings = create_app_settings()
        settings.clear()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "hero"
            idle = root / "SE" / "idle"
            idle.mkdir(parents=True)
            for index in (1, 2, 3):
                Image.new("RGB", (16, 16), "red").save(idle / f"idle_{index:03d}.png")

            controller = MainController()
            controller.on_paths_changed(str(root), str(root))
            self._wait_until(lambda: not controller._scan_in_progress, timeout=10.0)

            self.assertEqual([item.action_name for item in controller.state.action_items], ["idle"])
            self.assertIn("同一目录", controller.source_target_bar.status_label.text())
            self.assertEqual(controller.action_diff_panel.proxy.rowCount(), 1)
            self.assertEqual(controller.action_diff_panel.proxy.status_filter, "all")

            preview_panel = controller.preview_panel
            self._wait_until(
                lambda: (
                    preview_panel.left_preview.frame_count == 3
                    and preview_panel.right_preview.frame_count == 3
                ),
                timeout=8.0,
            )
            self.assertEqual(preview_panel.left_preview.action_label.text(), "SE · idle")
            self.assertEqual(preview_panel.frame_slider.maximum() + 1, 3)

            # 再点一次「刷新对比」：依然有清单和动画，不会变成空白
            controller.source_target_bar.refresh_button.click()
            self._wait_until(lambda: not controller._scan_in_progress, timeout=10.0)
            self._wait_until(
                lambda: preview_panel.left_preview.frame_count == 3,
                timeout=8.0,
            )
            self.assertEqual(controller.action_diff_panel.proxy.rowCount(), 1)

            self._wait_threads_released(controller)
            controller.settings.clear()
            controller.settings.sync()
            self._dispose(controller)

    def test_refresh_requested_during_scan_runs_afterwards(self) -> None:
        """扫描进行中再次请求刷新：结束后必须补跑，避免界面停在旧结果。"""
        settings = create_app_settings()
        settings.clear()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            first = base / "first"
            second = base / "second"
            for root, action in ((first, "idle"), (second, "attack")):
                target = root / "NW" / action
                target.mkdir(parents=True)
                Image.new("RGB", (8, 8), "red").save(target / f"{action}_001.png")

            controller = MainController()
            controller.on_paths_changed(str(first), str(second))
            # 扫描尚未结束就换成新目录：这次请求被记为 pending
            controller.on_paths_changed(str(second), str(second))
            self.assertTrue(controller._pending_refresh)
            self._wait_until(
                lambda: [item.action_name for item in controller.state.action_items] == ["attack"],
                timeout=10.0,
            )
            self._wait_until(lambda: not controller._scan_in_progress, timeout=10.0)
            self._wait_threads_released(controller)

            self.assertEqual([item.action_name for item in controller.state.action_items], ["attack"])
            self.assertIn("同一目录", controller.source_target_bar.status_label.text())
            controller.settings.clear()
            controller.settings.sync()
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
        """尽力等待线程簿记清空，超时静默返回。

        高负载下 Qt 的线程收尾事件（thread.finished 投递）可能延迟数秒才送达，
        但线程本身早已执行完毕，仅 _active_threads/_threads 列表未清空；这属于
        簿记抖动，不应导致测试失败。真正的业务完成由各测试对 _scan_in_progress
        等逻辑标志的硬等待保证。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cls.app.processEvents()
            if not getattr(controller, "_active_threads", None) and not getattr(controller, "_threads", None):
                return
            time.sleep(0.01)

    @classmethod
    def _dispose(cls, widget) -> None:
        # 先等后台线程真正结束（而非列表清空）；若簿记未及时送达导致 closeEvent
        # 弹出“任务进行中”确认框，用定时器自动点击“是”，避免模态卡死
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


@unittest.skipUnless(HAS_QT, "需要安装 PySide6")
class RedundancyDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        # 清掉上一个用例残留的规则持久化，保证默认值断言稳定
        create_app_settings().clear()

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

    @staticmethod
    def _make_tree(root: Path) -> None:
        """角色输出图结构：角色/方向/动作/帧。"""
        for relative in [
            "501_body/E/idle/idle_001.png",  # 保留动作
            "501_body/E/run/run_001.png",  # 保留动作
            "501_body/E/attack/attack_001.png",  # 冗余：E 方向非保留动作
            "501_body/W/attack/attack_001.png",  # 基准方向，永不冗余
            "502_body/S/hurt/hurt_001.png",  # 冗余：S 方向非保留动作
        ]:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png")

    def test_default_rules_scan_and_move_to_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scan_root = root / "角色输出图"
            backup = root / "backup"
            self._make_tree(scan_root)
            dialog = RedundancyDialog(default_root=str(scan_root))
            dialog.show()
            self.assertEqual(dialog.directions_edit.text(), "E, N, S")
            self.assertEqual(dialog.keep_edit.text(), "idle, run")

            dialog.start_scan()
            self._wait_until(
                lambda: not dialog._scanning and dialog.tree.topLevelItemCount() == 2, timeout=8.0
            )
            rows = {
                dialog.tree.topLevelItem(index).text(5)
                for index in range(dialog.tree.topLevelItemCount())
            }
            self.assertEqual(rows, {"501_body/E/attack", "502_body/S/hurt"})
            self.assertIn("已选 2/2", dialog.info_label.text())

            dialog.backup_edit.setText(str(backup))
            self.assertTrue(dialog.move_button.isEnabled())

            def confirm_move() -> None:
                box = QApplication.activeModalWidget()
                self.assertIsInstance(box, QMessageBox)
                box.button(QMessageBox.StandardButton.Yes).click()

            QTimer.singleShot(0, confirm_move)
            dialog.start_move()
            self._wait_until(lambda: not dialog._moving, timeout=10.0)
            self._wait_threads_released(dialog)

            self.assertTrue((backup / "501_body" / "E" / "attack" / "attack_001.png").is_file())
            self.assertTrue((backup / "502_body" / "S" / "hurt" / "hurt_001.png").is_file())
            self.assertFalse((scan_root / "501_body" / "E" / "attack").exists())
            self.assertTrue((scan_root / "501_body" / "W" / "attack" / "attack_001.png").is_file())
            self.assertTrue((scan_root / "501_body" / "E" / "idle" / "idle_001.png").is_file())
            self.assertEqual(dialog.tree.topLevelItemCount(), 0)
            self.assertTrue(dialog.moved_anything)
            self.assertEqual(dialog.scanned_root(), str(scan_root))
            dialog.settings.clear()
            dialog.settings.sync()
            self._dispose(dialog)

    def test_rule_fields_are_editable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scan_root = root / "角色输出图"
            self._make_tree(scan_root)
            dialog = RedundancyDialog(default_root=str(scan_root))
            dialog.directions_edit.setText("NE, S")
            dialog.keep_edit.setText("idle")

            dialog.start_scan()
            self._wait_until(
                lambda: not dialog._scanning and dialog.tree.topLevelItemCount() == 1, timeout=8.0
            )
            self.assertEqual(dialog.tree.topLevelItem(0).text(5), "502_body/S/hurt")
            dialog.settings.clear()
            dialog.settings.sync()
            self._dispose(dialog)

    def test_move_blocked_when_backup_inside_scan_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scan_root = root / "角色输出图"
            self._make_tree(scan_root)
            dialog = RedundancyDialog(default_root=str(scan_root))
            dialog.start_scan()
            self._wait_until(
                lambda: not dialog._scanning and dialog.tree.topLevelItemCount() == 2, timeout=8.0
            )
            dialog.backup_edit.setText(str(scan_root / "backup"))

            def dismiss_warning() -> None:
                box = QApplication.activeModalWidget()
                if isinstance(box, QMessageBox):
                    box.button(QMessageBox.StandardButton.Ok).click()

            QTimer.singleShot(0, dismiss_warning)
            dialog.start_move()
            self.app.processEvents()

            self.assertFalse(dialog._moving)
            self.assertTrue((scan_root / "501_body" / "E" / "attack" / "attack_001.png").is_file())
            dialog.settings.clear()
            dialog.settings.sync()
            self._dispose(dialog)

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
        """尽力等待线程簿记清空，超时静默返回。

        高负载下 Qt 的线程收尾事件（thread.finished 投递）可能延迟数秒才送达，
        但线程本身早已执行完毕，仅 _active_threads/_threads 列表未清空；这属于
        簿记抖动，不应导致测试失败。真正的业务完成由各测试对 _scan_in_progress
        等逻辑标志的硬等待保证。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cls.app.processEvents()
            if not getattr(controller, "_active_threads", None) and not getattr(controller, "_threads", None):
                return
            time.sleep(0.01)

    @classmethod
    def _dispose(cls, widget) -> None:
        # 先等后台线程真正结束（而非列表清空）；若簿记未及时送达导致 closeEvent
        # 弹出“任务进行中”确认框，用定时器自动点击“是”，避免模态卡死
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


@unittest.skipUnless(HAS_QT, "需要安装 PySide6")
class ExtraFilesAlertUiTests(unittest.TestCase):
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

    @staticmethod
    def _make_file(rel: str, status: str) -> FileDiffItem:
        return FileDiffItem(
            rel,
            Path(rel).name,
            status,
            f"src/{rel}" if status != "only_right" else None,
            f"dst/{rel}" if status != "only_left" else None,
            100,
        )

    def test_action_diff_panel_highlights_only_existing_target_extras(self) -> None:
        actions = [
            ActionDiffItem(
                "e/ride_idle",
                "ride_idle",
                "E/ride_idle",
                "different",
                None,
                None,
                [self._make_file(f"E/ride_idle/v2_{i}.png", "only_left") for i in range(8)]
                + [self._make_file(f"E/ride_idle/old_{i}.png", "only_right") for i in range(8)],
            ),
            ActionDiffItem(
                "se/idle",
                "idle",
                "SE/idle",
                "different",
                None,
                None,
                [self._make_file(f"SE/idle/idle_{i}.png", "different") for i in range(6)]
                + [self._make_file(f"SE/idle/idle_{i}.png", "only_left") for i in range(6, 8)],
            ),
            ActionDiffItem(
                "se/attack",
                "attack",
                "SE/attack",
                "different",
                None,
                None,
                [self._make_file(f"SE/attack/a_{i}.png", "different") for i in range(8)],
            ),
            ActionDiffItem(
                "w/hurt",
                "hurt",
                "W/hurt",
                "different",
                None,
                None,
                [self._make_file(f"W/hurt/h_{i}.png", "different") for i in range(7)]
                + [self._make_file("W/hurt/h_7.png", "only_right")],
            ),
            ActionDiffItem(
                "ne/skill",
                "skill",
                "NE/skill",
                "only_left",
                None,
                None,
                [self._make_file(f"NE/skill/s_{i}.png", "only_left") for i in range(8)],
            ),
            ActionDiffItem(
                "s/walk",
                "walk",
                "S/walk",
                "same",
                None,
                None,
                [self._make_file("S/walk/w_0.png", "same")],
            ),
        ]

        panel = ActionDiffPanel()
        panel.populate(actions)
        panel.filter_buttons["all"].click()

        by_path = {
            panel.model.item(row, 0).data(Qt.UserRole + 2).relative_path: row
            for row in range(panel.model.rowCount())
        }

        for path, expected_text in [("E/ride_idle", "+8 -8"), ("SE/idle", "+2 ~6")]:
            row = by_path[path]
            change_item = panel.model.item(row, 5)
            self.assertEqual(change_item.text(), expected_text)
            self.assertEqual(change_item.foreground().color().name(), "#ff6b5e")
            self.assertTrue(change_item.font().bold())
            self.assertIn("比 SVN 多出", change_item.toolTip())

        for path in ("SE/attack", "W/hurt", "NE/skill"):
            row = by_path[path]
            change_item = panel.model.item(row, 5)
            self.assertIsNone(change_item.data(Qt.ForegroundRole))
            self.assertFalse(change_item.font().bold())
            self.assertEqual(change_item.toolTip(), "")

        # 新增待传仍保持绿色，不变红
        skill_row = by_path["NE/skill"]
        self.assertEqual(panel.model.item(skill_row, 4).foreground().color().name(), "#4caf50")

        # 已一致保持绿色且不加粗
        walk_row = by_path["S/walk"]
        self.assertEqual(panel.model.item(walk_row, 5).foreground().color().name(), "#4caf50")
        self.assertFalse(panel.model.item(walk_row, 5).font().bold())

        # 展开 E/ride_idle：only_left 子行「变化」列标红 +1，only_right 不标
        ride_proxy = panel.proxy.mapFromSource(panel.model.index(by_path["E/ride_idle"], 0))
        panel._on_expanded(ride_proxy)
        ride_parent = panel.model.item(by_path["E/ride_idle"], 0)
        self.assertEqual(ride_parent.rowCount(), 16)
        for idx in range(8):
            child_change = ride_parent.child(idx, 5)
            self.assertEqual(child_change.text(), "+1")
            self.assertEqual(child_change.foreground().color().name(), "#ff6b5e")
            self.assertTrue(child_change.font().bold())
            self.assertIn("多出", child_change.toolTip())
        for idx in range(8, 16):
            child_change = ride_parent.child(idx, 5)
            self.assertEqual(child_change.text(), "")
            self.assertIsNone(child_change.data(Qt.ForegroundRole))
            self.assertFalse(child_change.font().bold())

        # 展开新增待传 NE/skill：子行不标红 +1
        skill_proxy = panel.proxy.mapFromSource(panel.model.index(skill_row, 0))
        panel._on_expanded(skill_proxy)
        skill_parent = panel.model.item(skill_row, 0)
        for idx in range(8):
            child_change = skill_parent.child(idx, 5)
            self.assertEqual(child_change.text(), "")
            self.assertIsNone(child_change.data(Qt.ForegroundRole))
        self._dispose(panel)

    def test_transfer_preview_dialog_flags_extra_files_and_clears_on_uncheck(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"

            # E/ride_idle: +2 -2（0 覆盖）
            for rel in ("E/ride_idle/v2_001.png", "E/ride_idle/v2_002.png"):
                (source / rel).parent.mkdir(parents=True, exist_ok=True)
                (source / rel).write_bytes(b"new")
            for rel in ("E/ride_idle/old_001.png", "E/ride_idle/old_002.png"):
                (target / rel).parent.mkdir(parents=True, exist_ok=True)
                (target / rel).write_bytes(b"old")

            # SE/attack: ~1（仅覆盖，无多出）
            (source / "SE/attack").mkdir(parents=True, exist_ok=True)
            (target / "SE/attack").mkdir(parents=True, exist_ok=True)
            (source / "SE/attack/a_001.png").write_bytes(b"new-a")
            (target / "SE/attack/a_001.png").write_bytes(b"old-a")

            # NE/skill: +1（全新动作，目标无该动作）
            (source / "NE/skill").mkdir(parents=True, exist_ok=True)
            (source / "NE/skill/s_001.png").write_bytes(b"new-s")

            rel_paths = [
                "E/ride_idle/v2_001.png",
                "E/ride_idle/v2_002.png",
                "SE/attack/a_001.png",
                "NE/skill/s_001.png",
            ]
            action_map = {
                "E/ride_idle/v2_001.png": "E/ride_idle",
                "E/ride_idle/v2_002.png": "E/ride_idle",
                "SE/attack/a_001.png": "SE/attack",
                "NE/skill/s_001.png": "NE/skill",
            }
            statuses = {
                "E/ride_idle": "different",
                "SE/attack": "different",
                "NE/skill": "only_left",
            }

            dialog = TransferPreviewDialog(
                str(source),
                str(target),
                rel_paths,
                action_map,
                backup_enabled=True,
                backup_dir="D:/Temp/Bak",
                action_statuses=statuses,
            )
            dialog.show()
            self.app.processEvents()

            expected_red = dialog._extra_fg.name()
            self.assertTrue(dialog.extra_warning_label.isVisibleTo(dialog))
            self.assertIn("1 个已存在动作包含 2 个", dialog.extra_warning_label.text())
            self.assertIn("比 SVN 多出", dialog.extra_warning_label.text())

            groups = {
                dialog.tree.topLevelItem(i).text(0): dialog.tree.topLevelItem(i)
                for i in range(dialog.tree.topLevelItemCount())
            }
            ride_group = groups["ride_idle"]
            self.assertEqual(ride_group.text(2), "2 个 · 多2")
            self.assertEqual(ride_group.foreground(2).color().name(), expected_red)
            self.assertTrue(ride_group.font(2).bold())
            for i in range(2):
                child = ride_group.child(i)
                self.assertEqual(child.text(2), "新增 · 多出")
                self.assertEqual(child.foreground(2).color().name(), expected_red)
                self.assertTrue(child.font(2).bold())

            attack_group = groups["attack"]
            self.assertEqual(attack_group.text(2), "1 个文件")
            self.assertIsNone(attack_group.data(2, Qt.ForegroundRole))
            self.assertEqual(attack_group.child(0).text(2), "覆盖")
            self.assertIsNone(attack_group.child(0).data(2, Qt.ForegroundRole))

            skill_group = groups["skill"]
            self.assertEqual(skill_group.text(2), "1 个文件")
            self.assertIsNone(skill_group.data(2, Qt.ForegroundRole))
            self.assertEqual(skill_group.child(0).text(2), "新增")
            self.assertIsNone(skill_group.child(0).data(2, Qt.ForegroundRole))

            # 取消勾选其中 1 个多出文件 -> 多1 同步更新
            ride_group.child(0).setCheckState(0, Qt.Unchecked)
            self.assertEqual(ride_group.text(2), "2 个 · 多1")
            self.assertIn("1 个已存在动作包含 1 个", dialog.extra_warning_label.text())

            # 全部取消该动作的多出文件 -> 恢复正常样式并隐藏警告条
            ride_group.child(1).setCheckState(0, Qt.Unchecked)
            self.assertEqual(ride_group.text(2), "2 个文件")
            self.assertIsNone(ride_group.data(2, Qt.ForegroundRole))
            self.assertIsNone(ride_group.data(2, Qt.FontRole))
            self.assertEqual(ride_group.toolTip(2), "")
            self.assertFalse(dialog.extra_warning_label.isVisibleTo(dialog))

            # 重新勾选 -> 红色提醒立即恢复
            ride_group.child(0).setCheckState(0, Qt.Checked)
            self.assertEqual(ride_group.text(2), "2 个 · 多1")
            self.assertEqual(ride_group.foreground(2).color().name(), expected_red)
            self.assertTrue(dialog.extra_warning_label.isVisibleTo(dialog))

            # 浅色独立窗口使用高对比度深红 #d32f2f
            self.assertEqual(expected_red, "#d32f2f")

            # 全不选 / 全选 按钮同样同步清理和恢复红色提示
            dialog.clear_button.click()
            self.assertEqual(ride_group.text(2), "2 个文件")
            self.assertIsNone(ride_group.data(2, Qt.ForegroundRole))
            self.assertIsNone(ride_group.data(2, Qt.FontRole))
            self.assertFalse(dialog.extra_warning_label.isVisibleTo(dialog))
            dialog.select_all_button.click()
            self.assertEqual(ride_group.text(2), "2 个 · 多2")
            self.assertEqual(ride_group.foreground(2).color().name(), expected_red)
            self.assertTrue(dialog.extra_warning_label.isVisibleTo(dialog))
            self._dispose(dialog)

            # 大小写不敏感匹配：action_statuses 小写键应匹配目录大写键
            ci_dialog = TransferPreviewDialog(
                str(source),
                str(target),
                ["E/ride_idle/v2_001.png"],
                {"e/ride_idle/v2_001.png": "E/ride_idle"},
                action_statuses={"e/ride_idle": "different"},
            )
            ci_dialog.show()
            self.app.processEvents()
            self.assertTrue(ci_dialog.extra_warning_label.isVisibleTo(ci_dialog))
            self.assertEqual(ci_dialog.tree.topLevelItem(0).child(0).text(2), "新增 · 多出")
            self._dispose(ci_dialog)

            # 图集条目：成对覆盖保持「覆盖」不标红；目标已有 .png 缺 .plist 时仅缺口 .plist 标红
            (source / "boss_se_attack.png").write_bytes(b"new-atlas-png")
            (source / "boss_se_attack.plist").write_text("<plist>new</plist>", encoding="utf-8")
            (target / "boss_se_attack.png").write_bytes(b"old-atlas-png")
            (target / "boss_se_attack.plist").write_text("<plist>old</plist>", encoding="utf-8")
            atlas_paired_dialog = TransferPreviewDialog(
                str(source),
                str(target),
                ["boss_se_attack.png", "boss_se_attack.plist"],
                {
                    "boss_se_attack.png": "boss_se_attack.png",
                    "boss_se_attack.plist": "boss_se_attack.png",
                },
                action_statuses={"boss_se_attack.png": "different"},
            )
            atlas_paired_dialog.show()
            self.app.processEvents()
            self.assertFalse(atlas_paired_dialog.extra_warning_label.isVisibleTo(atlas_paired_dialog))
            atlas_group = atlas_paired_dialog.tree.topLevelItem(0)
            self.assertEqual(atlas_group.text(2), "2 个文件")
            self.assertIsNone(atlas_group.data(2, Qt.ForegroundRole))
            for idx in range(2):
                self.assertEqual(atlas_group.child(idx).text(2), "覆盖")
                self.assertIsNone(atlas_group.child(idx).data(2, Qt.ForegroundRole))
            self._dispose(atlas_paired_dialog)

            (target / "boss_se_attack.plist").unlink()
            atlas_missing_plist_dialog = TransferPreviewDialog(
                str(source),
                str(target),
                ["boss_se_attack.png"],
                {"boss_se_attack.png": "boss_se_attack.png"},
                action_statuses={"boss_se_attack.png": "different"},
            )
            atlas_missing_plist_dialog.show()
            self.app.processEvents()
            self.assertTrue(atlas_missing_plist_dialog.extra_warning_label.isVisibleTo(atlas_missing_plist_dialog))
            atlas_partial = atlas_missing_plist_dialog.tree.topLevelItem(0)
            self.assertEqual(atlas_partial.text(2), "2 个 · 多1")
            by_name = {atlas_partial.child(i).text(0): atlas_partial.child(i) for i in range(2)}
            self.assertEqual(by_name["boss_se_attack.png"].text(2), "覆盖")
            self.assertEqual(by_name["boss_se_attack.plist"].text(2), "新增 · 多出")
            self.assertEqual(
                by_name["boss_se_attack.plist"].foreground(2).color().name(),
                atlas_missing_plist_dialog._extra_fg.name(),
            )
            self._dispose(atlas_missing_plist_dialog)

            # 不传 action_statuses 时，仅靠目标目录已有文件也能检出 +2 -2 多出情况
            fallback_dialog = TransferPreviewDialog(
                str(source),
                str(target),
                ["E/ride_idle/v2_001.png"],
                {"E/ride_idle/v2_001.png": "E/ride_idle"},
            )
            fallback_dialog.show()
            self.app.processEvents()
            self.assertTrue(fallback_dialog.extra_warning_label.isVisibleTo(fallback_dialog))
            self.assertEqual(fallback_dialog.tree.topLevelItem(0).child(0).text(2), "新增 · 多出")
            self._dispose(fallback_dialog)

            # 纯新增待传动作（无 action_statuses 且目标无目录）保持普通“新增”，不标红
            new_only_dialog = TransferPreviewDialog(
                str(source),
                str(target),
                ["NE/skill/s_001.png"],
                {"NE/skill/s_001.png": "NE/skill"},
            )
            new_only_dialog.show()
            self.app.processEvents()
            self.assertFalse(new_only_dialog.extra_warning_label.isVisibleTo(new_only_dialog))
            self.assertEqual(new_only_dialog.tree.topLevelItem(0).child(0).text(2), "新增")
            self._dispose(new_only_dialog)

    def test_main_controller_show_transfer_preview_passes_statuses_and_dark_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            (source / "E/ride_idle").mkdir(parents=True)
            (target / "E/ride_idle").mkdir(parents=True)
            (source / "E/ride_idle/v2_001.png").write_bytes(b"new")
            (target / "E/ride_idle/old_001.png").write_bytes(b"old")

            diffs = [
                FileDiffItem("E/ride_idle/v2_001.png", "v2_001.png", "only_left", str(source / "E/ride_idle/v2_001.png"), None, 3),
                FileDiffItem("E/ride_idle/old_001.png", "old_001.png", "only_right", None, str(target / "E/ride_idle/old_001.png"), 3),
            ]
            action = ActionDiffItem("E/ride_idle", "ride_idle", "E/ride_idle", "different", None, None, diffs)

            controller = MainController()
            controller.state.left_root_path = str(source)
            controller.state.right_root_path = str(target)
            controller.state.action_items = [action]
            controller.action_diff_panel.populate([action], {"E/ride_idle/v2_001.png"})
            controller.state.selected_file_paths = {"E/ride_idle/v2_001.png"}

            observed: dict[str, object] = {}

            def inspect_and_reject() -> None:
                modal = QApplication.activeModalWidget()
                observed["is_dialog"] = isinstance(modal, TransferPreviewDialog)
                if isinstance(modal, TransferPreviewDialog):
                    observed["parent_is_ctrl"] = modal.parent() is controller
                    observed["fg"] = modal._extra_fg.name()
                    observed["visible"] = modal.extra_warning_label.isVisibleTo(modal)
                    observed["status"] = modal.tree.topLevelItem(0).child(0).text(2)
                    modal.reject()

            QTimer.singleShot(0, inspect_and_reject)
            controller.show_transfer_preview()

            self.assertEqual(
                observed,
                {
                    "is_dialog": True,
                    "parent_is_ctrl": True,
                    "fg": "#ff6b5e",
                    "visible": True,
                    "status": "新增 · 多出",
                },
            )
            self._dispose(controller)

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
            QTimer.singleShot(0, lambda: UiWorkflowTests._dismiss_modal_question(widget))
        widget.close()
        widget.deleteLater()
        cls.app.sendPostedEvents(None, QEvent.DeferredDelete)
        cls.app.processEvents()


if __name__ == "__main__":
    unittest.main()
