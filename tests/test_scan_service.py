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

    @staticmethod
    def _make_roots(root: Path) -> tuple[Path, Path]:
        left = root / "left"
        right = root / "right"
        (left / "idle").mkdir(parents=True)
        (right / "idle").mkdir(parents=True)
        return left, right


if __name__ == "__main__":
    unittest.main()
