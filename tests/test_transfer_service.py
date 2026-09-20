from __future__ import annotations

import tempfile
import os
import unittest
from pathlib import Path

from services.transfer_service import TransferService


class TransferServiceTests(unittest.TestCase):
    def test_build_job_for_files_is_exact_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            (source / "player" / "idle").mkdir(parents=True)
            (source / "player" / "idle" / "idle_001.png").write_bytes(b"frame")
            (source / "player" / "idle" / "idle_002.png").write_bytes(b"frame2")

            job = TransferService().build_job_for_files(
                str(source),
                str(target),
                [
                    "player/idle/idle_001.png",
                    "player/idle/idle_001.png",
                    "player/idle",
                    "missing.png",
                ],
            )

            self.assertEqual(job.total_files, 1)
            self.assertEqual(job.items[0].relative_path, "player/idle/idle_001.png")

    def test_copy_job_preserves_exact_selected_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            action = source / "player" / "idle"
            action.mkdir(parents=True)
            selected = action / "idle_001.png"
            excluded = action / "idle_002.png"
            selected.write_bytes(b"selected")
            excluded.write_bytes(b"excluded")
            service = TransferService()
            job = service.build_job_for_files(
                str(source),
                str(target),
                ["player/idle/idle_001.png"],
            )
            completed: list[tuple[int, int, int]] = []
            callbacks = {
                "job_started": lambda total: None,
                "file_started": lambda index, path, size: None,
                "progress_changed": lambda copied, total: None,
                "file_finished": lambda index, path, success: None,
                "job_failed": lambda message: self.fail(message),
                "job_completed": lambda success, failed, skipped: completed.append((success, failed, skipped)),
            }

            service.copy_job(job, callbacks)

            self.assertEqual((target / "player" / "idle" / "idle_001.png").read_bytes(), b"selected")
            self.assertFalse((target / "player" / "idle" / "idle_002.png").exists())
            self.assertEqual(completed, [(1, 0, 0)])

    def test_copy_job_overwrites_existing_target_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            relative = Path("player/idle/idle_001.png")
            (source / relative).parent.mkdir(parents=True)
            (target / relative).parent.mkdir(parents=True)
            (source / relative).write_bytes(b"new-action-content")
            (target / relative).write_bytes(b"old-svn-content")
            os.utime(target / relative, (1, 1))
            old_mtime = (target / relative).stat().st_mtime
            service = TransferService()
            job = service.build_job_for_files(str(source), str(target), [relative.as_posix()])
            completed: list[tuple[int, int, int]] = []

            service.copy_job(
                job,
                {
                    "job_started": lambda total: None,
                    "file_started": lambda index, path, size: None,
                    "progress_changed": lambda copied, total: None,
                    "file_finished": lambda index, path, success: None,
                    "job_failed": lambda message: self.fail(message),
                    "job_completed": lambda success, failed, skipped: completed.append((success, failed, skipped)),
                },
            )

            self.assertEqual((target / relative).read_bytes(), b"new-action-content")
            self.assertGreater((target / relative).stat().st_mtime, old_mtime)
            self.assertEqual(completed, [(1, 0, 0)])

    def test_atomic_copy_does_not_replace_on_hash_mismatch(self) -> None:
        """校验失败时，目标文件不应被替换，保持原有内容。"""
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            relative = Path("player/idle/idle_001.png")
            (source / relative).parent.mkdir(parents=True)
            (target / relative).parent.mkdir(parents=True)
            source_file = source / relative
            target_file = target / relative
            original_target = b"original-safe-content"
            source_file.write_bytes(b"new-content")
            target_file.write_bytes(original_target)

            service = TransferService()
            job = service.build_job_for_files(str(source), str(target), [relative.as_posix()])

            # mock hash_file 让它永远返回与源不同的值，模拟校验失败
            with patch("services.transfer_service.hash_file", return_value="mismatched_hash_xxxx"):
                failed: list[str] = []
                service.copy_job(
                    job,
                    {
                        "job_started": lambda total: None,
                        "file_started": lambda index, path, size: None,
                        "progress_changed": lambda copied, total: None,
                        "file_finished": lambda index, path, success: None,
                        "job_failed": lambda message: failed.append(message),
                        "job_completed": lambda success, failed_count, skipped: None,
                    },
                )

            self.assertTrue(failed, "校验失败应被报告")
            # 关键断言：目标文件内容必须保持原样，绝不能被不完整/不匹配的内容替换
            self.assertEqual(target_file.read_bytes(), original_target)
            # 目标目录内不应残留临时文件
            target_dir = target_file.parent
            leftovers = [p for p in target_dir.iterdir() if ".tmp-" in p.name]
            self.assertFalse(leftovers, f"校验失败后不应残留临时文件: {leftovers}")

    def test_build_job_rejects_path_traversal(self) -> None:
        """含 .. 的相对路径应被过滤，不能逃逸出根目录。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            outside = root / "outside_secret.txt"
            outside.write_bytes(b"should-not-be-copied")
            (source / "player" / "idle").mkdir(parents=True)
            (source / "player" / "idle" / "ok.png").write_bytes(b"frame")

            service = TransferService()
            job = service.build_job_for_files(
                str(source),
                str(target),
                [
                    "player/idle/ok.png",
                    "../../outside_secret.txt",
                    "../source/player/idle/ok.png",
                ],
            )

            # 只有合法路径应被保留
            self.assertEqual(job.total_files, 1)
            self.assertEqual(job.items[0].relative_path, "player/idle/ok.png")
            # 外部文件绝不能出现在传输列表里
            self.assertFalse(any("outside_secret" in item.target_path for item in job.items))

    def test_copy_job_handles_readonly_target(self) -> None:
        """目标文件为只读时，仍应能成功覆盖。"""
        import stat
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            relative = Path("player/idle/idle_001.png")
            (source / relative).parent.mkdir(parents=True)
            (target / relative).parent.mkdir(parents=True)
            (source / relative).write_bytes(b"new-content")
            target_file = target / relative
            target_file.write_bytes(b"old-readonly-content")
            # 设为只读
            target_file.chmod(target_file.stat().st_mode & ~stat.S_IWUSR)
            self.assertFalse(target_file.stat().st_mode & stat.S_IWUSR, "前置：目标应为只读")

            service = TransferService()
            job = service.build_job_for_files(str(source), str(target), [relative.as_posix()])
            completed: list[tuple[int, int, int]] = []

            service.copy_job(
                job,
                {
                    "job_started": lambda total: None,
                    "file_started": lambda index, path, size: None,
                    "progress_changed": lambda copied, total: None,
                    "file_finished": lambda index, path, success: None,
                    "job_failed": lambda message: self.fail(message),
                    "job_completed": lambda success, failed, skipped: completed.append((success, failed, skipped)),
                },
            )

            self.assertEqual(completed, [(1, 0, 0)])
            self.assertEqual(target_file.read_bytes(), b"new-content")

    def test_no_temp_files_left_after_copy(self) -> None:
        """复制完成后，目标目录内不应残留 .tmp- 临时文件。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            relative = Path("player/idle/idle_001.png")
            (source / relative).parent.mkdir(parents=True)
            (source / relative).write_bytes(b"clean-copy")

            service = TransferService()
            job = service.build_job_for_files(str(source), str(target), [relative.as_posix()])

            service.copy_job(
                job,
                {
                    "job_started": lambda total: None,
                    "file_started": lambda index, path, size: None,
                    "progress_changed": lambda copied, total: None,
                    "file_finished": lambda index, path, success: None,
                    "job_failed": lambda message: self.fail(message),
                    "job_completed": lambda success, failed, skipped: None,
                },
            )

            target_dir = target / "player" / "idle"
            leftovers = [p for p in target_dir.iterdir() if ".tmp-" in p.name]
            self.assertFalse(leftovers, f"不应残留临时文件: {leftovers}")


if __name__ == "__main__":
    unittest.main()
