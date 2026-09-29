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
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings_dir.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
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
        settings = QSettings("MMY-Tools", "MMY-ActionFileSync")
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
        settings = QSettings("MMY-Tools", "MMY-ActionFileSync")
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
        settings = QSettings("MMY-Tools", "MMY-ActionFileSync")
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
        QSettings("MMY-Tools", "MMY-ActionFileSync").clear()

    @classmethod
    def setUpClass(cls) -> None:
        cls.settings_dir = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings_dir.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
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


if __name__ == "__main__":
    unittest.main()
