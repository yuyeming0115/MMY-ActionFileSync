"""图集（TexturePacker atlas）目录支持相关测试。"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from adapters.atlas_folder_adapter import AtlasFolderAdapter, LayoutAwareFolderAdapter
from models.action_diff import ActionDiffItem, FileDiffItem
from models.tree_node import TreeNode
from services.action_diff_service import ActionDiffService
from services.atlas_scan_service import detect_atlas_directory
from services.compare_service import CompareService
from services.preview_service import PreviewService
from services.refresh_service import RefreshService
from services.transfer_service import TransferService
from utils.atlas_naming import parse_atlas_name, strip_extension


def _make_png(path: Path, size: tuple[int, int] = (32, 32), color=(200, 30, 30, 255)) -> None:
    from PIL import Image

    Image.new("RGBA", size, color).save(path)


def _make_plist(path: Path, texture: str) -> None:
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0"><dict><key>frames</key><dict>'
        '<key>0001.png</key><dict><key>textureRect</key>'
        '<string>{{1,1},{30,30}}</string><key>spriteSourceSize</key>'
        '<string>{0,0}</string><key>spriteOffset</key><string>{0,0}</string>'
        '<key>textureRotated</key><false/></dict>'
        '</dict><key>metadata</key><dict><key>format</key><integer>3</integer>'
        '<key>realTextureFileName</key><string>' + texture + "</string>"
        "</dict></dict></plist>",
        encoding="utf-8",
    )


class AtlasNamingTests(unittest.TestCase):
    def test_with_part(self) -> None:
        entry = parse_atlas_name("501031001_shadow_E_idle.png")
        self.assertEqual(entry.role_id, "501031001")
        self.assertEqual(entry.part, "shadow")
        self.assertEqual(entry.direction, "E")
        self.assertEqual(entry.action, "idle")
        self.assertTrue(entry.is_structured)

    def test_without_part(self) -> None:
        entry = parse_atlas_name("503002_NW_block.png")
        self.assertEqual(entry.role_id, "503002")
        self.assertEqual(entry.part, "")
        self.assertEqual(entry.direction, "NW")
        self.assertEqual(entry.action, "block")

    def test_compound_action_not_truncated(self) -> None:
        """ride_idle 必须整体识别，不能被 idle 截断。"""
        entry = parse_atlas_name("501031001_shadow_E_ride_idle.png")
        self.assertEqual(entry.action, "ride_idle")
        self.assertEqual(entry.direction, "E")

    def test_compound_part(self) -> None:
        entry = parse_atlas_name("50302301_ride_back_N_ride_run.png")
        self.assertEqual(entry.role_id, "50302301")
        self.assertEqual(entry.part, "ride_back")
        self.assertEqual(entry.direction, "N")
        self.assertEqual(entry.action, "ride_run")

    def test_multi_digit_direction_wins(self) -> None:
        """NW 不能被 W 截断。"""
        entry = parse_atlas_name("502001_NW_idle.png")
        self.assertEqual(entry.direction, "NW")

    def test_bare_name_degrades_gracefully(self) -> None:
        """裸名不报错，字段留空，仍能进入清单。"""
        entry = parse_atlas_name("50105101.png")
        self.assertEqual(entry.role_id, "50105101")
        self.assertEqual(entry.direction, "")
        self.assertFalse(entry.is_structured)

    def test_plist_extension_stripped(self) -> None:
        self.assertEqual(strip_extension("a_b_c_NW_idle.plist"), "a_b_c_NW_idle")


class AtlasDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="atlas_detect_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_detects_flat_atlas_dir(self) -> None:
        for stem in ("501031001_shadow_E_idle", "503002_NW_block"):
            _make_png(self.tmp / f"{stem}.png")
            _make_plist(self.tmp / f"{stem}.plist", f"{stem}.png")
        self.assertTrue(detect_atlas_directory(str(self.tmp)))

    def test_rejects_sequence_dir_with_subdirs(self) -> None:
        """有子目录的序列帧目录不能被误判为图集目录。"""
        (self.tmp / "NW" / "idle").mkdir(parents=True)
        _make_png(self.tmp / "NW" / "idle" / "0001.png")
        _make_plist(self.tmp / "NW" / "idle" / "0001.plist", "0001.png")
        self.assertFalse(detect_atlas_directory(str(self.tmp)))

    def test_rejects_dir_without_plist(self) -> None:
        _make_png(self.tmp / "a.png")
        _make_png(self.tmp / "b.png")
        self.assertFalse(detect_atlas_directory(str(self.tmp)))


class AtlasScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="atlas_scan_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stems = [
            "501031001_shadow_E_idle",
            "501031001_shadow_NW_run",
            "503002_NW_block",
        ]
        for stem in self.stems:
            _make_png(self.tmp / f"{stem}.png")
            _make_plist(self.tmp / f"{stem}.plist", f"{stem}.png")

    def test_one_atlas_becomes_one_action(self) -> None:
        """核心诉求：一张图集 = 一个条目，而不是一堆帧。"""
        root = AtlasFolderAdapter().scan(str(self.tmp))
        self.assertEqual(root.node_type, "atlas_root")
        self.assertEqual(len(root.children), 3)
        for child in root.children:
            self.assertEqual(child.node_type, "atlas")
            self.assertEqual(len(child.frame_files), 2)

    def test_metadata_parsed_into_extra(self) -> None:
        root = AtlasFolderAdapter().scan(str(self.tmp))
        by_name = {child.name: child for child in root.children}
        node = by_name["501031001_shadow_NW_run.png"]
        self.assertEqual(node.extra["direction"], "NW")
        self.assertEqual(node.extra["action"], "run")
        self.assertEqual(node.extra["role_id"], "501031001")
        self.assertEqual(node.extra["part"], "shadow")

    def test_orphan_plist_still_listed(self) -> None:
        """有 plist 无 png 也不能丢，需在清单里暴露出来。"""
        _make_plist(self.tmp / "orphan_N_idle.plist", "missing.png")
        root = AtlasFolderAdapter().scan(str(self.tmp))
        orphan = next(c for c in root.children if c.name == "orphan_N_idle.plist")
        self.assertEqual(len(orphan.frame_files), 1)
        self.assertFalse(orphan.extra["has_png"])

    def test_layout_aware_adapter_picks_atlas_scanner(self) -> None:
        adapter = LayoutAwareFolderAdapter(source_type="left")
        root = adapter.scan(str(self.tmp))
        self.assertEqual(root.node_type, "atlas_root")

    def test_layout_aware_adapter_falls_back_to_sequence(self) -> None:
        seq = self.tmp / "seq" / "NW" / "idle"
        seq.mkdir(parents=True)
        _make_png(seq / "0001.png")
        _make_png(seq / "0002.png")
        root = LayoutAwareFolderAdapter(source_type="left").scan(str(self.tmp / "seq"))
        # 根目录本身是 folder，序列节点在下一层
        self.assertEqual(root.node_type, "folder")
        self.assertNotEqual(root.extra.get("layout"), "atlas")
        stack = [root]
        found: list[str] = []
        while stack:
            node = stack.pop()
            if node.node_type == "sequence":
                found.append(node.name)
            stack.extend(node.children)
        self.assertEqual(found, ["idle"])


class AtlasCompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="atlas_cmp_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = self.tmp / "src"
        self.dst = self.tmp / "dst"
        self.src.mkdir()
        self.dst.mkdir()
        self.stems = [
            "501031001_shadow_E_idle",
            "501031001_shadow_NW_run",
            "503002_NW_block",
        ]
        for stem in self.stems:
            for folder in (self.src, self.dst):
                _make_png(folder / f"{stem}.png", color=(10, 200, 10, 255))
                _make_plist(folder / f"{stem}.plist", f"{stem}.png")

    def _actions(self) -> list[ActionDiffItem]:
        result = RefreshService().refresh(str(self.src), str(self.dst))
        return ActionDiffService().build_actions(result)

    def test_identical_dirs_all_same(self) -> None:
        actions = self._actions()
        self.assertEqual(len(actions), 3)
        self.assertTrue(all(a.status == "same" for a in actions))
        self.assertTrue(all(a.transfer_file_count == 0 for a in actions))

    def test_changed_png_marks_different(self) -> None:
        _make_png(self.dst / "503002_NW_block.png", color=(1, 2, 3, 255))
        actions = {a.action_name: a for a in self._actions()}
        node = actions["503002_NW_block.png"]
        self.assertEqual(node.status, "different")
        # png 变了 → 整对（png + plist）一起标 different 一并重传，
        # 避免「新 png + 旧 plist」的错位图集。
        self.assertEqual(node.transfer_file_count, 2)
        self.assertTrue(all(f.status == "different" for f in node.file_diffs))

    def test_missing_entry_marks_only_left(self) -> None:
        os.remove(self.dst / "503002_NW_block.png")
        os.remove(self.dst / "503002_NW_block.plist")
        actions = {a.action_name: a for a in self._actions()}
        node = actions["503002_NW_block.png"]
        self.assertEqual(node.status, "only_left")
        self.assertEqual(node.transfer_file_count, 2)

    def test_missing_plist_only_reports_pair(self) -> None:
        """目标侧缺 plist 时，条目内的文件状态应暴露不一致，且缺失文件可传。"""
        os.remove(self.dst / "503002_NW_block.plist")
        actions = {a.action_name: a for a in self._actions()}
        node = actions["503002_NW_block.png"]
        self.assertEqual(node.status, "different")
        statuses = {f.name: f.status for f in node.file_diffs}
        self.assertEqual(statuses["503002_NW_block.plist"], "different")
        # 缺失的 plist 必须出现在可传输列表里，否则目标端补不齐
        self.assertIn("503002_NW_block.plist", {f.relative_path for f in node.transferable_files})

    def test_same_size_different_content_in_deep_mode(self) -> None:
        """deep_verify 模式下，同尺寸不同内容必须被抓出来。

        atlas 摘要只用「文件名 + 字节数」以换取扫描速度（实测
        2.8GB 目标目录下，默认模式 1.7 秒 vs 深校验 36 秒），
        因此极限精度需要显式开启 deep_verify。
        """
        from PIL import Image

        stem = "503002_NW_block"
        # 造两张 PNG：像素不同但压缩后字节数完全一致
        for folder, color in ((self.src, (10, 10, 10, 255)), (self.dst, (20, 20, 20, 255))):
            img = Image.new("RGBA", (16, 16), color)
            img.save(folder / f"{stem}.png", compress_level=9)
        sizes = [(self.src / f"{stem}.png").stat().st_size, (self.dst / f"{stem}.png").stat().st_size]
        self.assertEqual(sizes[0], sizes[1], "前置条件：两张图字节数应相同")

        result = RefreshService().refresh(str(self.src), str(self.dst))
        actions = {a.action_name: a for a in ActionDiffService(deep_verify=True).build_actions(result)}
        node = actions[f"{stem}.png"]
        self.assertEqual(node.status, "different")
        self.assertEqual(node.transfer_file_count, 2)

    def test_default_mode_is_size_based(self) -> None:
        """默认快路径：字节数相同即判一致，不读文件内容（保证秒级响应）。"""
        from PIL import Image

        stem = "503002_NW_block"
        for folder, color in ((self.src, (10, 10, 10, 255)), (self.dst, (20, 20, 20, 255))):
            img = Image.new("RGBA", (16, 16), color)
            img.save(folder / f"{stem}.png", compress_level=9)
        actions = {a.action_name: a for a in self._actions()}
        node = actions[f"{stem}.png"]
        self.assertEqual(node.status, "same")
        self.assertEqual(node.transfer_file_count, 0)

    def test_fingerprint_detects_head_tail_change(self) -> None:
        """采样指纹能识别文件头/尾变化（快路径的第二级判据）。"""
        from utils.hash_utils import fingerprints_equal

        self.assertTrue(fingerprints_equal(self.src / "503002_NW_block.png", self.dst / "503002_NW_block.png"))
        # 改掉首字节 → 指纹必然不同
        data = bytearray((self.dst / "503002_NW_block.png").read_bytes())
        data[0] ^= 0xFF
        (self.dst / "503002_NW_block.png").write_bytes(bytes(data))
        self.assertFalse(fingerprints_equal(self.src / "503002_NW_block.png", self.dst / "503002_NW_block.png"))

    def test_target_only_entry_does_not_crash(self) -> None:
        """回归：目标侧独有（来源缺失）的图集条目不能抛异常。

        这类条目的 source_node 为 None，早期实现返回了单个列表而非
        元组，导致 build_actions 整体崩溃 —— 界面表现为
        「正在扫描并对比目录」卡住、差异清单永远不出现。
        """
        _make_png(self.dst / "999999_orphan_N_idle.png")
        _make_plist(self.dst / "999999_orphan_N_idle.plist", "999999_orphan_N_idle.png")
        actions = {a.action_name: a for a in self._actions()}
        orphan = actions["999999_orphan_N_idle.png"]
        self.assertEqual(orphan.status, "only_right")
        self.assertEqual(orphan.transfer_file_count, 0)
        self.assertEqual(orphan.file_diffs, [])

    def test_action_name_and_group_columns(self) -> None:
        actions = {a.action_name: a for a in self._actions()}
        node = actions["501031001_shadow_NW_run.png"]
        self.assertEqual(node.source_node.extra["action"], "run")
        self.assertEqual(node.source_node.extra["group_label"], "501031001/shadow")

    def test_file_paths_are_actually_resolvable(self) -> None:
        """回归：atlas 节点的 absolute_path 指向文件本身。

        早期实现把它当目录再拼文件名，会产出
        ``xxx.png/xxx.png`` 这种不存在的路径，
        导致文件大小恒为 0、传输全部失败。
        """
        for action in self._actions():
            for item in action.file_diffs:
                if item.source_path:
                    self.assertTrue(
                        Path(item.source_path).is_file(),
                        f"来源路径不可解析: {item.source_path}",
                    )
                if item.target_path:
                    self.assertTrue(
                        Path(item.target_path).is_file(),
                        f"目标路径不可解析: {item.target_path}",
                    )

    def test_transfer_size_matches_real_bytes(self) -> None:
        """可传输条目的大小必须等于实际文件字节数，而不是 0。"""
        os.remove(self.dst / "503002_NW_block.plist")
        actions = {a.action_name: a for a in self._actions()}
        action = actions["503002_NW_block.png"]
        self.assertGreater(action.transfer_size_bytes, 0)
        real = sum(
            (self.src / f.name).stat().st_size
            for f in action.transferable_files
        )
        self.assertEqual(action.transfer_size_bytes, real)


class AtlasTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="atlas_xfer_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = self.tmp / "src"
        self.dst = self.tmp / "dst"
        self.src.mkdir()
        self.dst.mkdir()
        _make_png(self.src / "a_idle.png", color=(9, 9, 9, 255))
        _make_plist(self.src / "a_idle.plist", "a_idle.png")

    def test_selecting_png_auto_pairs_plist(self) -> None:
        """只勾 png 也必须把 plist 一起传，否则目标端图集直接损坏。"""
        job = TransferService().build_job_for_files(str(self.src), str(self.dst), ["a_idle.png"])
        self.assertEqual({item.relative_path for item in job.items}, {"a_idle.png", "a_idle.plist"})

    def test_selecting_plist_auto_pairs_png(self) -> None:
        job = TransferService().build_job_for_files(str(self.src), str(self.dst), ["a_idle.plist"])
        self.assertEqual({item.relative_path for item in job.items}, {"a_idle.png", "a_idle.plist"})

    def test_non_atlas_file_not_paired(self) -> None:
        """不成对的普通文件不应被硬塞一个不存在的伴随文件。"""
        _make_png(self.src / "loose.png")
        job = TransferService().build_job_for_files(str(self.src), str(self.dst), ["loose.png"])
        self.assertEqual({item.relative_path for item in job.items}, {"loose.png"})

    def test_copy_writes_both_files(self) -> None:
        job = TransferService().build_job_for_files(str(self.src), str(self.dst), ["a_idle.png"])
        completed: dict[str, tuple[int, int, int]] = {}
        callbacks = {
            "job_started": lambda _n: None,
            "file_started": lambda *_a: None,
            "file_finished": lambda *_a: None,
            "progress_changed": lambda *_a: None,
            "job_failed": self.fail,
            "job_completed": lambda s, f, k: completed.update({"r": (s, f, k)}),
        }
        TransferService().copy_job(job, callbacks)
        self.assertEqual(completed["r"], (2, 0, 0))
        self.assertTrue((self.dst / "a_idle.png").is_file())
        self.assertTrue((self.dst / "a_idle.plist").is_file())


class AtlasPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="atlas_prev_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        _make_png(self.tmp / "501031001_shadow_E_idle.png", size=(64, 48))
        _make_plist(self.tmp / "501031001_shadow_E_idle.plist", "501031001_shadow_E_idle.png")
        self.root = AtlasFolderAdapter().scan(str(self.tmp))
        self.node = self.root.children[0]

    def test_previews_whole_atlas_without_frame_slicing(self) -> None:
        """按需求不切帧：整张图集当单图显示。"""
        item = PreviewService().build_preview("left", self.node.relative_path, self.node)
        self.assertEqual(item.status, "ready")
        self.assertEqual(item.frame_count, 1)
        self.assertEqual((item.width, item.height), (64, 48))
        self.assertIn("未切帧", item.message)

    def test_preview_errors_when_png_missing(self) -> None:
        os.remove(self.tmp / "501031001_shadow_E_idle.png")
        root = AtlasFolderAdapter().scan(str(self.tmp))
        item = PreviewService().build_preview("left", root.children[0].relative_path, root.children[0])
        self.assertEqual(item.status, "error")


class AtlasUiScalingTests(unittest.TestCase):
    """图集条目上千时，界面快捷按钮与同步不能退化。

    真实场景：6913 个图集条目。
    历史问题：动作按钮按 action_name（完整文件名）去重，生成几千个按钮，
    加上每个按钮都遍历全部动作同步状态，刷新耗时 8.8 秒且界面卡死。
    """

    def _make_actions(self, count: int) -> list[ActionDiffItem]:
        from models.tree_node import TreeNode

        actions: list[ActionDiffItem] = []
        for index in range(count):
            name = f"{500000 + index:06d}_shadow_NW_idle"
            node = TreeNode(
                id=f"atlas:{name}",
                name=name,
                relative_path=name,
                absolute_path=name,
                node_type="atlas",
                source_type="atlas",
                frame_files=[f"{name}.png", f"{name}.plist"],
                extra={
                    "layout": "atlas",
                    "role_id": f"{500000 + index:06d}",
                    "part": "shadow",
                    "direction": "NW",
                    "action": "idle",
                    "search_text": name,
                },
            )
            actions.append(
                ActionDiffItem(
                    action_id=name,
                    action_name=name,
                    relative_path=name,
                    status="different",
                    source_node=node,
                    target_node=None,
                    file_diffs=[
                        FileDiffItem(f"{name}.png", f"{name}.png", "different", "source", None, 1000),
                        FileDiffItem(f"{name}.plist", f"{name}.plist", "different", "source", None, 100),
                    ],
                )
            )
        return actions

    def _make_panel(self):
        """构造 ActionDiffPanel；无 PySide6 环境跳过。"""
        import importlib.util

        if importlib.util.find_spec("PySide6") is None:
            self.skipTest("PySide6 不可用")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from views.action_diff_panel import ActionDiffPanel

        QApplication.instance() or QApplication([])
        panel = ActionDiffPanel()
        self.addCleanup(panel.deleteLater)
        return panel

    def test_action_buttons_do_not_explode(self) -> None:
        """上千个图集条目只能生成少量动作按钮（按动作名，而非文件名）。"""
        actions = self._make_actions(1500)
        panel = self._make_panel()
        panel.populate(actions)
        count = panel.action_buttons_layout.count()
        self.assertLessEqual(count, 24, f"动作按钮数量失控：{count}")
        # 全部条目动作都是 idle，应当只有一个按钮
        self.assertEqual(count, 1)
        button = panel.action_buttons_layout.itemAt(0).widget()
        self.assertEqual(button.text(), "idle")

    def test_action_button_toggles_all_matching(self) -> None:
        """点击动作按钮应勾选该动作下所有条目（1500 个条目全选）。"""
        actions = self._make_actions(1500)
        panel = self._make_panel()
        panel.populate(actions)
        button = panel.action_buttons_layout.itemAt(0).widget()
        button.click()
        # 1500 条目 × 2 文件
        self.assertEqual(len(panel.selected_paths), 3000)
        button.click()
        self.assertEqual(panel.selected_paths, set())

    def test_direction_buttons_sync_is_fast(self) -> None:
        """方向/动作按钮同步不能退化成 O(按钮数 × 条目数)。"""
        import time

        actions = self._make_actions(3000)
        panel = self._make_panel()
        panel.populate(actions)
        panel.select_changed()
        start = time.monotonic()
        panel._sync_direction_buttons()
        panel._sync_action_buttons()
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0, f"按钮同步过慢：{elapsed:.2f}s")

    def test_populate_handles_thousands_of_entries(self) -> None:
        """上千条目的 populate 不能超过数秒。"""
        import time

        actions = self._make_actions(3000)
        panel = self._make_panel()
        start = time.monotonic()
        panel.populate(actions)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 5.0, f"populate 过慢：{elapsed:.2f}s")
        self.assertEqual(panel.model.rowCount(), 3000)
        self.assertEqual(panel.proxy.rowCount(), 3000)


class AtlasIsolationTests(unittest.TestCase):
    """确保图集改动没有破坏传统序列帧流程。"""

    def test_sequence_workflow_unchanged(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="atlas_iso_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src = tmp / "src"
        dst = tmp / "dst"
        (src / "NW" / "idle").mkdir(parents=True)
        (dst / "NW" / "idle").mkdir(parents=True)
        _make_png(src / "NW" / "idle" / "0001.png", color=(1, 1, 1, 255))
        _make_png(dst / "NW" / "idle" / "0001.png", color=(2, 2, 2, 255))
        result = RefreshService().refresh(str(src), str(dst))
        actions = ActionDiffService().build_actions(result)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].status, "different")

    def test_redundancy_scan_ignores_flat_atlas_dir(self) -> None:
        """冗余扫描不能把平铺图集当成动作目录误判为冗余。"""
        from services.redundancy_service import RedundancyService

        tmp = Path(tempfile.mkdtemp(prefix="atlas_redun_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        _make_png(tmp / "503002_E_idle.png")
        _make_plist(tmp / "503002_E_idle.plist", "503002_E_idle.png")
        items = RedundancyService().scan(str(tmp), ["E", "N", "S"], ["idle", "run"])
        self.assertEqual(items, [])


class AtlasCompareServiceDirectTests(unittest.TestCase):
    def test_compare_same_dir(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="atlas_direct_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        _make_png(tmp / "a.png")
        _make_plist(tmp / "a.plist", "a.png")
        left = LayoutAwareFolderAdapter(source_type="left").scan(str(tmp))
        right = LayoutAwareFolderAdapter(source_type="right").scan(str(tmp))
        result = CompareService().compare(left, right)
        statuses = {pair.status for pair in result.node_map.values()}
        self.assertEqual(statuses, {"same"})


if __name__ == "__main__":
    unittest.main()