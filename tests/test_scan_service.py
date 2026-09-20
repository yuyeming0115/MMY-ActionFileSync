from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from services.compare_service import CompareService
from services.scan_service import ScanService


class ScanServiceContentHashTests(unittest.TestCase):
    def test_same_content_with_different_timestamps_is_same(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            left, right = self._make_roots(Path(temp_dir))
            for index, content in [(1, b"frame-a"), (2, b"frame-b")]:
                left_file = left / "idle" / f"idle_{index:03d}.png"
                right_file = right / "idle" / f"idle_{index:03d}.png"
                left_file.write_bytes(content)
                right_file.write_bytes(content)
                os.utime(right_file, (left_file.stat().st_mtime - 60, left_file.stat().st_mtime - 60))

            result = CompareService().compare(
                ScanService("left").scan(str(left)),
                ScanService("right").scan(str(right)),
            )

            self.assertEqual(result.node_map["idle"].status, "same")
            self.assertEqual(result.node_map["idle/idle_001.png"].status, "same")

    def test_same_size_and_timestamp_with_different_content_is_different(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            left, right = self._make_roots(Path(temp_dir))
            for index in [1, 2]:
                left_file = left / "idle" / f"idle_{index:03d}.png"
                right_file = right / "idle" / f"idle_{index:03d}.png"
                left_file.write_bytes(b"AAAA")
                right_file.write_bytes(b"BBBB" if index == 2 else b"AAAA")
                timestamp = left_file.stat().st_mtime
                os.utime(right_file, (timestamp, timestamp))

            result = CompareService().compare(
                ScanService("left").scan(str(left)),
                ScanService("right").scan(str(right)),
            )

            self.assertEqual(result.node_map["idle"].status, "different")
            self.assertEqual(result.node_map["idle/idle_002.png"].status, "different")

    def test_case_insensitive_path_matching(self) -> None:
        """来源和目标文件名大小写不同时，应正确匹配为同一文件。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            left = Path(temp_dir) / "left"
            right = Path(temp_dir) / "right"
            # 来源：小写目录和文件名
            (left / "idle").mkdir(parents=True)
            (left / "idle" / "idle_001.png").write_bytes(b"same-content")
            (left / "idle" / "idle_002.png").write_bytes(b"frame-two")
            # 目标：大写目录和文件名（Windows 上会是同一个文件）
            (right / "IDLE").mkdir(parents=True)
            (right / "IDLE" / "IDLE_001.PNG").write_bytes(b"same-content")
            # 只有一帧，idle_002 在目标缺失

            result = CompareService().compare(
                ScanService("left").scan(str(left)),
                ScanService("right").scan(str(right)),
            )

            # 动作级应匹配为内容变更（帧数不同），而非两个独立动作
            action_keys = [k for k in result.node_map if "/" not in k and k]
            self.assertEqual(len(action_keys), 1, "大小写不同的动作目录应合并为一个")
            action_pair = result.node_map[action_keys[0]]
            self.assertEqual(action_pair.status, "different")

            # 同名（大小写不同）的单帧应匹配为 same
            frame_pairs = [p for p in result.node_map.values() if p.left and p.left.node_type == "image"]
            same_frames = [p for p in frame_pairs if p.status == "same"]
            self.assertEqual(len(same_frames), 1, "内容相同但大小写不同的帧应判为 same")

            # 展示路径优先采用来源（左侧）的原始大小写
            self.assertEqual(action_pair.relative_path, "idle")

    @staticmethod
    def _make_roots(root: Path) -> tuple[Path, Path]:
        left = root / "left"
        right = root / "right"
        (left / "idle").mkdir(parents=True)
        (right / "idle").mkdir(parents=True)
        return left, right


if __name__ == "__main__":
    unittest.main()
