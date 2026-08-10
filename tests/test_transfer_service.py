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


if __name__ == "__main__":
    unittest.main()
