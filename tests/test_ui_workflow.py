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
    from PySide6.QtWidgets import QAbstractButton, QApplication
    from PIL import Image

    from controllers.main_controller import MainController
    from views.action_diff_panel import ActionDiffPanel
    from views.main_window import MainWindow
    from views.preview_panel import SinglePreviewWidget
    from views.transfer_panel import TransferPanel
    from views.transfer_preview_dialog import TransferPreviewDialog


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

        panel.select_only_current()
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

        panel.select_only_current()

        self.assertEqual(
            panel.selected_paths,
            {"player/attack/attack_001.png", "player/idle/idle_001.png"},
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

        self.assertEqual(colors, ["#237a45", "#b42318"])
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
            self._wait_until(lambda: not controller._active_threads)
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
            self._wait_until(lambda: not first._scan_in_progress)
            self._wait_until(lambda: not first._active_threads)
            self._dispose(first)

            restored = MainController()
            self.assertEqual(restored.source_target_bar.paths(), (str(source), str(target)))
            restored.clear_all_lists()
            self.assertEqual(restored.source_target_bar.paths(), ("", ""))
            self._dispose(restored)

            restored_after_clear = MainController()
            self.assertEqual(restored_after_clear.source_target_bar.paths(), (str(source), str(target)))
            self._dispose(restored_after_clear)

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
            controller.action_diff_panel.select_only_current()
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
            self._wait_until(lambda: not controller._active_threads)
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
    def _dispose(cls, widget) -> None:
        widget.close()
        widget.deleteLater()
        cls.app.sendPostedEvents(None, QEvent.DeferredDelete)
        cls.app.processEvents()


if __name__ == "__main__":
    unittest.main()
