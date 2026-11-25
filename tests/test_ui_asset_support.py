from __future__ import annotations

import importlib.util
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from models.sync_options import (
    SYNC_MODE_AUTO,
    SYNC_MODE_UI,
    SyncOptions,
    UI_MATCH_FILENAME,
    UI_MATCH_RELATIVE,
)
from models.transfer_job import TransferItem, TransferJob
from services.action_diff_service import ActionDiffService
from services.backup_service import BackupService
from services.preview_service import PreviewService
from services.refresh_service import RefreshService
from services.transfer_service import TransferService
from services.ui_scan_service import UICompareService, UIScanService
from utils.hash_utils import HashCache

HAS_QT = importlib.util.find_spec("PySide6") is not None

if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings, QTimer, Qt
    from PySide6.QtWidgets import QAbstractButton, QApplication

    from controllers.main_controller import MainController
    from utils.app_info import create_app_settings
    from views.transfer_preview_dialog import TransferPreviewDialog


def _write_png(path: Path, size: tuple[int, int] = (32, 32), color: tuple[int, int, int, int] = (255, 0, 0, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path, format="PNG")


def _thread_settled(thread) -> bool:
    try:
        return not thread.isRunning()
    except RuntimeError:
        return True


class UIScanServiceTests(unittest.TestCase):
    def test_scan_filters_non_images_and_hidden_dirs_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_png(root / "icon_a.png")
            _write_png(root / "sub" / "icon_b.png")
            (root / "source.psd").write_bytes(b"psd-data")
            (root / "table.csv").write_text("id,name\n1,a\n", encoding="utf-8")
            (root / "Thumbs.db").write_bytes(b"db")
            (root / ".svn" / "wc.db").parent.mkdir(parents=True, exist_ok=True)
            (root / ".svn" / "wc.db").write_bytes(b"svn")
            (root / ".workbuddy" / "note.png").parent.mkdir(parents=True, exist_ok=True)
            _write_png(root / ".workbuddy" / "note.png")

            default_tree = UIScanService("left", include_non_images=False).scan(str(root))
            rels_default = [node.relative_path for node in default_tree.children]
            self.assertEqual(rels_default, ["icon_a.png", "sub/icon_b.png"])
            self.assertEqual(default_tree.node_type, "ui_root")
            self.assertTrue(all(node.node_type == "ui_asset" for node in default_tree.children))

            all_tree = UIScanService("left", include_non_images=True).scan(str(root))
            rels_all = [node.relative_path for node in all_tree.children]
            self.assertEqual(rels_all, ["icon_a.png", "source.psd", "sub/icon_b.png", "table.csv"])
            psd_node = next(node for node in all_tree.children if node.relative_path == "source.psd")
            self.assertFalse(psd_node.extra["is_image"])


class UICompareRelativeTests(unittest.TestCase):
    def test_flat_subset_same_size_content_diff_overwrite_only_and_dimension_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"

            # 1) 完全一致
            _write_png(left / "same.png", (64, 64), (10, 20, 30, 255))
            _write_png(right / "same.png", (64, 64), (10, 20, 30, 255))

            # 2) 尺寸一致但内容不同（甚至故意构造同字节长度的二进制伪装）
            (left / "same_bytes_diff.png").parent.mkdir(parents=True, exist_ok=True)
            (right / "same_bytes_diff.png").parent.mkdir(parents=True, exist_ok=True)
            _write_png(left / "same_bytes_diff.png", (64, 64), (10, 20, 30, 255))
            _write_png(right / "same_bytes_diff.png", (64, 64), (11, 20, 30, 255))

            # 3) 分辨率不一致
            _write_png(left / "resized.png", (128, 128), (200, 100, 50, 255))
            _write_png(right / "resized.png", (64, 64), (200, 100, 50, 255))

            # 4) 仅左侧新增
            _write_png(left / "brand_new.png", (64, 64), (0, 255, 0, 255))

            # 5) 右侧海量旧图（应保持 only_right 不被传输）
            _write_png(right / "old_only.png", (64, 64), (0, 0, 255, 255))

            # 6) 同构子目录
            _write_png(left / "ui" / "view" / "btn.png", (48, 48), (1, 2, 3, 255))
            _write_png(right / "ui" / "view" / "btn.png", (48, 48), (9, 8, 7, 255))

            hash_cache = HashCache()
            opts_allow_new = SyncOptions(mode=SYNC_MODE_UI, ui_match_strategy=UI_MATCH_RELATIVE, ui_overwrite_only=False)
            result = RefreshService(hash_cache=hash_cache).refresh(str(left), str(right), sync_options=opts_allow_new)

            actions_allow = ActionDiffService(hash_cache=hash_cache).build_actions(result, sync_options=opts_allow_new)
            by_rel = {a.relative_path: a for a in actions_allow}
            self.assertEqual(by_rel["same.png"].status, "same")
            self.assertEqual(by_rel["same_bytes_diff.png"].status, "different")
            self.assertEqual(by_rel["resized.png"].status, "different")
            self.assertTrue(by_rel["resized.png"].has_dimension_mismatch)
            self.assertEqual(by_rel["resized.png"].dimension_mismatch_pair, ((128, 128), (64, 64)))
            self.assertEqual(by_rel["brand_new.png"].status, "only_left")
            self.assertEqual(by_rel["brand_new.png"].transfer_file_count, 1)
            self.assertEqual(by_rel["old_only.png"].status, "only_right")
            self.assertEqual(by_rel["old_only.png"].transfer_file_count, 0)
            self.assertEqual(by_rel["ui/view/btn.png"].status, "different")

            # 开启「仅覆盖已有」后，only_left 必须被拦截不可传
            opts_overwrite_only = SyncOptions(mode=SYNC_MODE_UI, ui_match_strategy=UI_MATCH_RELATIVE, ui_overwrite_only=True)
            actions_blocked = ActionDiffService(hash_cache=hash_cache).build_actions(result, sync_options=opts_overwrite_only)
            by_rel_blocked = {a.relative_path: a for a in actions_blocked}
            self.assertEqual(by_rel_blocked["brand_new.png"].status, "only_left")
            self.assertEqual(by_rel_blocked["brand_new.png"].transfer_file_count, 0)
            self.assertTrue(bool(by_rel_blocked["brand_new.png"].blocked_reasons))
            self.assertEqual(by_rel_blocked["resized.png"].transfer_file_count, 1)

    def test_raw_same_byte_length_different_content_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            # 构造完全相同字节长度但中部字节不同的文件
            payload_a = b"\x89PNG\r\n\x1a\n" + b"A" * 10000 + b"END"
            payload_b = b"\x89PNG\r\n\x1a\n" + b"A" * 5000 + b"B" * 10 + b"A" * 4990 + b"END"
            (left / "mid.png").write_bytes(payload_a)
            (right / "mid.png").write_bytes(payload_b)

            left_tree = UIScanService("left").scan(str(left))
            right_tree = UIScanService("right").scan(str(right))
            result = UICompareService().compare(left_tree, right_tree, match_strategy=UI_MATCH_RELATIVE)
            self.assertEqual(result.node_map["mid.png"].status, "different")


class UICompareFilenameTests(unittest.TestCase):
    def test_cross_level_left_nested_to_right_flat_and_left_flat_to_right_nested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"

            # 左多层 -> 右平铺
            _write_png(left / "1001_束锋剑" / "一套装备" / "eq_1001.png", (64, 64), (255, 0, 0, 255))
            _write_png(right / "eq_1001.png", (64, 64), (0, 0, 0, 255))

            # 左平铺 -> 右多级目录树
            _write_png(left / "tf_001.png", (64, 64), (0, 255, 0, 255))
            _write_png(right / "T_tf_天赋" / "tf_001.png", (64, 64), (0, 0, 0, 255))

            # 右侧多同名触发 conflict
            _write_png(left / "dup_icon.png", (64, 64), (255, 255, 0, 255))
            _write_png(right / "J_jn_技能" / "dup_icon.png", (64, 64), (1, 1, 1, 255))
            _write_png(right / "T_tf_天赋" / "dup_icon.png", (64, 64), (2, 2, 2, 255))

            # 未命中文件
            _write_png(left / "unmatched.png", (64, 64), (123, 123, 123, 255))

            opts = SyncOptions(mode=SYNC_MODE_UI, ui_match_strategy=UI_MATCH_FILENAME, ui_overwrite_only=False)
            result = RefreshService().refresh(str(left), str(right), sync_options=opts)
            actions = ActionDiffService().build_actions(result, sync_options=opts)
            by_rel = {a.relative_path: a for a in actions}

            eq_action = by_rel["1001_束锋剑/一套装备/eq_1001.png"]
            self.assertEqual(eq_action.status, "different")
            self.assertEqual(eq_action.file_diffs[0].resolved_target_relative_path, "eq_1001.png")

            tf_action = by_rel["tf_001.png"]
            self.assertEqual(tf_action.status, "different")
            self.assertEqual(tf_action.file_diffs[0].resolved_target_relative_path, "T_tf_天赋/tf_001.png")

            dup_action = by_rel["dup_icon.png"]
            self.assertEqual(dup_action.status, "conflict")
            self.assertEqual(dup_action.transfer_file_count, 0)
            self.assertEqual(
                dup_action.candidate_target_paths,
                ["J_jn_技能/dup_icon.png", "T_tf_天赋/dup_icon.png"],
            )

            # 手动指定覆盖目标可解除冲突
            resolved = RefreshService().refresh(
                str(left),
                str(right),
                sync_options=opts,
                target_overrides={"dup_icon.png": "T_tf_天赋/dup_icon.png"},
            )
            resolved_actions = {a.relative_path: a for a in ActionDiffService().build_actions(resolved, sync_options=opts)}
            self.assertEqual(resolved_actions["dup_icon.png"].status, "different")
            self.assertEqual(
                resolved_actions["dup_icon.png"].file_diffs[0].resolved_target_relative_path,
                "T_tf_天赋/dup_icon.png",
            )
            self.assertEqual(resolved_actions["dup_icon.png"].transfer_file_count, 1)
            # 未被选中的 J_jn_技能/dup_icon.png 应作为 only_right 保留在结果里
            self.assertEqual(resolved_actions["J_jn_技能/dup_icon.png"].status, "only_right")

            # 未命中文件在 allow_new=False 时落点根目录；overwrite_only=True 时拦截
            self.assertEqual(by_rel["unmatched.png"].status, "only_left")
            self.assertEqual(by_rel["unmatched.png"].file_diffs[0].resolved_target_relative_path, "unmatched.png")
            opts_ow = SyncOptions(mode=SYNC_MODE_UI, ui_match_strategy=UI_MATCH_FILENAME, ui_overwrite_only=True)
            blocked_actions = {a.relative_path: a for a in ActionDiffService().build_actions(result, sync_options=opts_ow)}
            self.assertEqual(blocked_actions["unmatched.png"].transfer_file_count, 0)

    def test_left_source_collision_blocks_both_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            _write_png(left / "v1" / "shared.png", (32, 32), (10, 0, 0, 255))
            _write_png(left / "v2" / "shared.png", (32, 32), (20, 0, 0, 255))
            _write_png(right / "shared.png", (32, 32), (0, 0, 0, 255))

            opts = SyncOptions(mode=SYNC_MODE_UI, ui_match_strategy=UI_MATCH_FILENAME)
            result = RefreshService().refresh(str(left), str(right), sync_options=opts)
            actions = {a.relative_path: a for a in ActionDiffService().build_actions(result, sync_options=opts)}

            self.assertEqual(actions["v1/shared.png"].status, "conflict")
            self.assertEqual(actions["v2/shared.png"].status, "conflict")
            self.assertEqual(actions["v1/shared.png"].transfer_file_count, 0)
            self.assertEqual(actions["v2/shared.png"].transfer_file_count, 0)


class UITransferAndBackupTests(unittest.TestCase):
    def test_cross_level_transfer_and_rollback_backup_preserve_target_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            backup_dir = root / "backups"

            _write_png(left / "1001" / "item.png", (32, 32), (255, 0, 0, 255))
            _write_png(left / "flat_icon.png", (32, 32), (0, 255, 0, 255))
            (left / "notes.csv").write_text("new,1\n", encoding="utf-8")

            _write_png(right / "item.png", (32, 32), (1, 1, 1, 255))
            _write_png(right / "T_tf_天赋" / "flat_icon.png", (32, 32), (2, 2, 2, 255))
            _write_png(right / "T_tf_天赋" / "untouched.png", (32, 32), (3, 3, 3, 255))
            old_flat_bytes = (right / "T_tf_天赋" / "flat_icon.png").read_bytes()
            old_item_bytes = (right / "item.png").read_bytes()

            # 同时放一个同名 .plist 验证 UI 模式不会自动伴随展开 .plist
            (left / "flat_icon.plist").write_text("plist", encoding="utf-8")

            service = TransferService()
            job = service.build_job_for_files(
                str(left),
                str(right),
                ["1001/item.png", "flat_icon.png", "notes.csv"],
                target_map={
                    "1001/item.png": "item.png",
                    "flat_icon.png": "T_tf_天赋/flat_icon.png",
                },
                expand_atlas=False,
            )
            self.assertEqual(
                [(item.relative_path, item.effective_target_relative_path) for item in job.items],
                [
                    ("1001/item.png", "item.png"),
                    ("flat_icon.png", "T_tf_天赋/flat_icon.png"),
                    ("notes.csv", "notes.csv"),
                ],
            )
            self.assertFalse(any(item.relative_path.endswith(".plist") for item in job.items))

            outcome = BackupService().backup_before_transfer(str(left), str(right), str(backup_dir), job)
            self.assertTrue(outcome.created)
            with zipfile.ZipFile(outcome.zip_path, "r") as zf:
                names = sorted(zf.namelist())
                self.assertEqual(names, ["T_tf_天赋/flat_icon.png", "item.png"])
                self.assertEqual(zf.read("T_tf_天赋/flat_icon.png"), old_flat_bytes)
                self.assertEqual(zf.read("item.png"), old_item_bytes)

            callbacks = {
                "job_started": lambda _total: None,
                "file_started": lambda _i, _rel, _sz: None,
                "progress_changed": lambda _c, _t: None,
                "file_finished": lambda _i, _rel, _ok: None,
                "job_completed": lambda _s, _f, _sk: None,
                "job_failed": lambda msg: self.fail(f"不应失败: {msg}"),
            }
            service.copy_job(job, callbacks)

            self.assertEqual((right / "item.png").read_bytes(), (left / "1001" / "item.png").read_bytes())
            self.assertEqual((right / "T_tf_天赋" / "flat_icon.png").read_bytes(), (left / "flat_icon.png").read_bytes())
            self.assertEqual((right / "notes.csv").read_text(encoding="utf-8"), "new,1\n")
            self.assertFalse((right / "1001").exists())
            self.assertFalse((right / "T_tf_天赋" / "flat_icon.plist").exists())
            self.assertTrue((right / "T_tf_天赋" / "untouched.png").exists())

    def test_preview_service_handles_non_image_ui_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_file = root / "config.csv"
            csv_file.write_text("a,b\n", encoding="utf-8")
            tree = UIScanService("left", include_non_images=True).scan(str(root))
            preview = PreviewService().build_preview("left", "config.csv", tree.children[0])
            self.assertEqual(preview.status, "not_previewable")
            self.assertIn("非图片文件", preview.message)


@unittest.skipUnless(HAS_QT, "需要安装 PySide6")
class UIWorkflowModeTests(unittest.TestCase):
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

    def _dispose(self, widget) -> None:
        if isinstance(widget, MainController):
            deadline = time.monotonic() + 3.0
            while any(not _thread_settled(thread) for thread in list(widget._active_threads)) and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            widget._active_threads.clear()
            widget._active_workers.clear()
        widget.close()
        widget.deleteLater()
        self.app.processEvents()

    def test_ui_mode_controls_fit_at_minimum_size_and_toggle_cleanly(self) -> None:
        controller = MainController()
        controller.resize(controller.minimumSize())
        controller.show()
        self.app.processEvents()

        # 默认处于「动作/图集」模式
        self.assertFalse(controller.source_target_bar.ui_option_bar.isVisible())
        self.assertTrue(controller.source_target_bar.redundancy_button.isVisible())
        self.assertTrue(controller.preview_panel.play_button.isVisible())

        # 切换到「UI资源」模式
        controller.source_target_bar.mode_ui_button.click()
        self.app.processEvents()

        self.assertTrue(controller.source_target_bar.ui_option_bar.isVisible())
        self.assertFalse(controller.source_target_bar.redundancy_button.isVisible())
        self.assertFalse(controller.preview_panel.play_button.isVisible())
        self.assertFalse(controller.preview_panel.compass_toggle.isVisible())
        self.assertTrue(controller.action_diff_panel.filter_buttons["conflict"].isVisible())

        clipped: list[str] = []
        for button in controller.findChildren(QAbstractButton):
            if not button.isVisible() or not button.text():
                continue
            hint = button.sizeHint()
            if button.width() + 2 < hint.width() or button.height() + 2 < hint.height():
                clipped.append(f"{button.text()}({button.width()}×{button.height()} < {hint.width()}×{hint.height()})")
        self.assertFalse(clipped, f"UI 模式下按钮可能被截断: {clipped}")
        self._dispose(controller)

    def test_end_to_end_ui_mode_conflict_dimension_warning_transfer_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            backup_dir = root / "backups"

            _write_png(left / "hero" / "skill_01.png", (128, 128), (255, 0, 0, 255))
            _write_png(right / "T_tf_天赋" / "skill_01.png", (64, 64), (0, 0, 255, 255))

            _write_png(left / "dup.png", (64, 64), (0, 255, 0, 255))
            _write_png(right / "dir_a" / "dup.png", (64, 64), (10, 10, 10, 255))
            _write_png(right / "dir_b" / "dup.png", (64, 64), (20, 20, 20, 255))

            _write_png(left / "extra_new.png", (64, 64), (255, 255, 0, 255))

            controller = MainController()
            controller.show()
            self.app.processEvents()
            controller.source_target_bar.set_backup_config(True, str(backup_dir))
            controller.source_target_bar.mode_ui_button.click()
            controller.source_target_bar.ui_option_bar.filename_button.click()
            controller.on_paths_changed(str(left), str(right))

            deadline = time.monotonic() + 5.0
            while (controller._scan_in_progress or not controller.state.action_items) and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)

            by_rel = {a.relative_path: a for a in controller.state.action_items}
            self.assertEqual(by_rel["hero/skill_01.png"].status, "different")
            self.assertTrue(by_rel["hero/skill_01.png"].has_dimension_mismatch)
            self.assertEqual(by_rel["dup.png"].status, "conflict")
            # 默认开启「仅覆盖已有」，所以 extra_new.png 被拦截
            self.assertEqual(by_rel["extra_new.png"].transfer_file_count, 0)

            # 选中尺寸不一致条目触发预览并检查横幅
            controller.action_diff_panel.jump_to_action("hero/skill_01.png")
            preview_deadline = time.monotonic() + 3.0
            while not controller.preview_panel.dimension_warning_label.isVisible() and time.monotonic() < preview_deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertTrue(controller.preview_panel.dimension_warning_label.isVisible())
            self.assertIn("128×128", controller.preview_panel.dimension_warning_label.text())

            # 手动解决 dup.png 冲突
            controller.on_conflict_target_selected("dup.png", "dir_b/dup.png")
            deadline = time.monotonic() + 5.0
            while controller._scan_in_progress and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            by_rel = {a.relative_path: a for a in controller.state.action_items}
            self.assertEqual(by_rel["dup.png"].status, "different")
            self.assertEqual(by_rel["dup.png"].file_diffs[0].resolved_target_relative_path, "dir_b/dup.png")

            # 勾选有变更的文件并打开 TransferPreviewDialog 验证目标路径与尺寸预警
            controller.action_diff_panel.select_changed()
            self.app.processEvents()
            target_map, dim_mismatches = controller._build_transfer_metadata()
            dialog = TransferPreviewDialog(
                str(left),
                str(right),
                sorted(controller.state.selected_file_paths),
                controller.action_diff_service.file_to_action(controller.state.action_items),
                backup_enabled=True,
                backup_dir=str(backup_dir),
                action_statuses={a.relative_path: a.status for a in controller.state.action_items},
                target_map=target_map,
                dimension_mismatches=dim_mismatches,
                expand_atlas=False,
                ui_mode=True,
            )
            self.assertFalse(dialog.dimension_warning_label.isHidden())
            self.assertEqual(set(dialog.selected_paths()), {"dup.png", "hero/skill_01.png"})
            dialog.deleteLater()

            # 触发真实传输并等待复扫完成
            controller._start_transfer(sorted(controller.state.selected_file_paths))
            tx_deadline = time.monotonic() + 5.0
            while (controller._transfer_in_progress or controller._scan_in_progress) and time.monotonic() < tx_deadline:
                self.app.processEvents()
                time.sleep(0.01)
            # 等待 QTimer.singleShot(0, refresh_compare) 跑完
            post_deadline = time.monotonic() + 5.0
            while (
                controller._scan_in_progress
                or any(a.status == "different" for a in controller.state.action_items)
            ) and time.monotonic() < post_deadline:
                self.app.processEvents()
                time.sleep(0.01)

            self.assertEqual((right / "T_tf_天赋" / "skill_01.png").read_bytes(), (left / "hero" / "skill_01.png").read_bytes())
            self.assertEqual((right / "dir_b" / "dup.png").read_bytes(), (left / "dup.png").read_bytes())
            self.assertFalse((right / "extra_new.png").exists())
            self._dispose(controller)

            # 验证重启后持久化恢复 UI 模式与策略选项
            restored = MainController()
            self.assertEqual(restored.state.sync_options.mode, SYNC_MODE_UI)
            self.assertEqual(restored.state.sync_options.ui_match_strategy, UI_MATCH_FILENAME)
            self.assertTrue(restored.state.sync_options.ui_overwrite_only)
            self.assertTrue(restored.source_target_bar.mode_ui_button.isChecked())
            self.assertFalse(restored.source_target_bar.ui_option_bar.isHidden())
            self._dispose(restored)


if __name__ == "__main__":
    unittest.main()
